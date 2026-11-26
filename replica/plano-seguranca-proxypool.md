# Plano de segurança: ProxyPool (substituto compliant do ProxyRotator)

Status: proposta v2, 2026-11-26, revisada por revisão adversarial independente. Pré-requisitos já feitos na árvore
de trabalho: BUG-006 (mascaramento central), BUG-007 (um egress por host por run) e BUG-008 (`trust_env=False`).

## Decisão após a revisão

- **Failover (passo 3) bloqueado.** Classificar a falha como "do proxy" exige ler o handle do libcurl
  (`CURLINFO_HTTP_CONNECTCODE`, `CURLINFO_CONNECT_TIME`, `CURLINFO_PROXY_ERROR`) depois do erro. O `FetcherSession`
  do upstream esconde o handle, devolve-o ao pool no async e faz 3 retries antes de o raspador ver a exceção. Sem essa
  costura, I3 e I4 não são implementáveis com segurança. Desbloqueia só com um spike que prove a costura (curl_cffi
  direto ou hook em `curl_options`).
- **v1 = afinidade estática.** Mapa explícito domínio→entrada (ou hash por domínio normalizado), sem failover. Falha
  do proxy = RSP-N004. Isso cobre egress por região, que já é o uso mais comum, e não depende de classificar erro.
- **Alternativa honesta:** `skip`. Egress por região já funciona hoje com uma sessão por proxy por domínio (BUG-007
  garante que um domínio não troca de sessão). O pool só acrescenta conveniência até o failover existir.

## Achados da revisão incorporados

| id | achado | onde entra |
| --- | --- | --- |
| B1 | Alvo `http://` não usa túnel: o 407 do próprio alvo chega como `response.status` e dispararia failover | I3: 407 só conta via `CURLINFO_HTTP_CONNECTCODE`; A18 |
| B2 | Timeout ou erro 7 no CONNECT pode ser o alvo dando DROP no IP do proxy (banimento) | I3: failover só em erro 5, ou 7/28 com `CONNECT_TIME == 0`, ou CONNECTCODE 407; nunca reusar o `is_proxy_error` do upstream (substring); A19 |
| B3 | Handle do curl inacessível depois do erro | "Decisão" acima |
| B4 | `Request.domain` é netloc cru: `EX.com`, `ex.com:443`, `ex.com.`, `u@ex.com` viram limiters e proxies diferentes; DNS curinga multiplica | chave de afinidade = eTLD+1 normalizado (minúsculas, sem porta, ponto final ou userinfo); A20 |
| B5 | Troca por `sid` contornava P006 | feito (BUG-007); I12 ampliado; A21 |
| B6 | `NO_PROXY` desviava o proxy explícito | feito (BUG-008); A22 |
| B7 | Sonda na mesma CDN/WAF do alvo cai junto com um banimento de borda | I4: sonda é infraestrutura do operador fora de CDN compartilhada; proxy só "morto" se a sonda falha por ele e passa por um irmão; sondas com limite de taxa |
| B8 | Checagem de SSRF resolve DNS localmente: o resolvedor do operador vê o nome escolhido pelo alvo, e a rede interna do proxy fica sem proteção | limite conhecido, documentado; A23 só garante que não há conexão direta |
| B9 | Varredura de segredo com transporte falso não vê log, meta nem argv | feito: tests/test_segredos_curl.py na costura do curl_cffi; A11 passa a rodar lá |
| B10 | Estabilidade entre runs | rendezvous hashing: remover uma entrada só move os domínios dela |

## Premissas

- O `ProxyRotator` do upstream continua proibido (RSP-P006). Este plano cria outra coisa: um pool com afinidade por
  domínio e failover por saúde do proxy. Ele não distribui um domínio por vários IPs e não reage a bloqueio.
- Usos que justificam o pool: failover de proxy corporativo, egress por região (conteúdo que muda por país),
  repartir carga entre os próprios proxies do operador. Se nenhum se aplica, a alternativa é `skip` na matriz.
- Quem configura o pool é o operador (código, variável de ambiente, arquivo). Nunca o alvo, nunca um modelo via MCP.

## Ativos e ameaças

| ativo | ameaça | origem |
| --- | --- | --- |
| credencial do proxy | vazar em log, erro, stats, auditoria, checkpoint, `ps`, histórico do shell | descuido do raspador ou do upstream |
| IP real do operador | sair direto quando todos os proxies falham | fallback mal feito |
| política do alvo (rate limit, bloqueio por IP) | ser contornada pela troca de proxy | o próprio raspador (evasão) |
| sessão autenticada (cookies) | passar por um proxy de outro fornecedor/nível de confiança no failover | failover sem fronteira |
| conteúdo da página | ser lido ou alterado por proxy não confiável (HTTP puro, TLS sem verificação) | proxy malicioso |
| rede interna do proxy | alcançada via SSRF, porque é o proxy que resolve e conecta | URL escolhida pelo alvo/modelo |
| topologia do operador | exposta no log de auditoria compartilhado | auditoria com URL do proxy |

## Invariantes (o que o código garante; cada um vira teste)

- **I1 Identidade única por domínio.** Num run, um domínio usa um proxy só. Troca apenas por failover (I3), e a troca
  é definitiva: não volta ao anterior no mesmo run.
- **I2 Vazão não multiplica.** `concurrent_requests_per_domain`, `download_delay`, AutoThrottle, cache de robots e
  contador de bloqueios continuam chaveados pelo domínio (a mesma chave do engine), nunca por (domínio, proxy).
  Trocar de proxy não zera nada.
- **I3 Failover só por falha do proxy, nunca do alvo.** Dispara: falha ao resolver o proxy, falha de TCP/TLS até o
  proxy, timeout de conexão até o proxy, 407. Não dispara: qualquer status do alvo (403, 429, 503, desafio),
  timeout de leitura, falha do túnel CONNECT (502/503/504 do proxy ao falar com o alvo).
  Motivo do último item: se o alvo derruba seu IP no nível de TCP, o proxy devolve erro de CONNECT; trocar de proxy
  aí seria contornar banimento por IP.
- **I4 Confirmação por sonda.** Antes de marcar um proxy como morto, o pool faz uma sonda independente do alvo
  (endpoint de saúde configurado pelo operador, ou CONNECT a um host neutro configurado). Sonda ok → o erro foi do
  alvo → sem failover, erro RSP-N001 normal. Sem sonda configurada, só 407 e falha de resolução/TCP até o proxy
  disparam failover.
- **I5 Teto de failover.** No máximo `max_failovers_per_domain` (padrão 2) trocas por domínio por run. Passou disso:
  `domain_stopped` com motivo `proxy_failover_limit`, igual ao que já acontece com bloqueios seguidos.
- **I6 Fail closed.** Sem proxy saudável no grupo, o request falha com RSP-N004 ("nenhum proxy disponível").
  Nunca há conexão direta. O robots.txt sai sempre pelo mesmo proxy do domínio (já é assim com proxy fixo).
- **I7 Fronteira de confiança.** Cada entrada tem um `group`. Failover só troca dentro do mesmo grupo. Afinidade por
  mapa explícito (`{"loja.com.br": "br"}`) fixa o grupo daquele domínio.
- **I8 Segredo nunca sai.** URL do proxy não aparece em `repr`, `str`, erro, log, stats, `CrawlResult`, auditoria nem
  checkpoint. Auditoria e checkpoint usam só o `label` da entrada. Entrada por variável de ambiente ou arquivo 0600.
- **I9 Identidade igual em todos os proxies.** UA, contato e headers são da sessão, não da entrada do pool. Nenhuma
  opção por entrada que mude identidade.
- **I10 TLS ligado.** Pool com `verify=False` é recusado (RSP-P010) salvo `policy_override` com motivo. Proxy com
  esquema fora de `http`, `https`, `socks5h` é recusado (`socks5` resolve DNS local e vaza o alvo para o resolvedor).
- **I11 Fora do alcance do modelo.** O MCP não ganha parâmetro de proxy. Se um dia houver pool no MCP, ele vem da
  configuração do servidor (`raspador mcp --proxy-pool arquivo`), nunca de argumento de ferramenta.
- **I12 Política antiga intacta.** Proxy por request, `proxies` por request, `ProxyRotator` e troca de `sid` para
  outro proxy no mesmo domínio continuam RSP-P006. `Proxy-Authorization` como header é RSP-P003.
- **I13 Egress só explícito.** Nenhuma sessão lê proxy do ambiente (`trust_env=False`); `NO_PROXY` não desvia.

## Desenho

```python
pool = ProxyPool(
    [
        ProxyEntry(url=env("PROXY_BR_1"), label="br-1", group="br"),
        ProxyEntry(url=env("PROXY_BR_2"), label="br-2", group="br"),
        ProxyEntry(url=env("PROXY_US_1"), label="us-1", group="us"),
    ],
    affinity="domain",              # ou {"loja.com.br": "br", "store.com": "us"}
    default_group="br",
    failover=True,
    probe_url=env("PROXY_PROBE"),   # opcional; sem ele, failover só em 407 e falha até o proxy
    max_failovers_per_domain=2,
)
raspador.http.spider_session(proxy_pool=pool)
```

- Atribuição: hash estável do domínio (mesma chave do engine) sobre as entradas saudáveis do grupo, para que o mesmo
  domínio caia no mesmo proxy entre runs. Fica registrada em memória para o run inteiro.
- Implementação no ponto que já é dono do request: `GuardedSessionManager` escolhe a entrada e passa para uma
  `HttpSession` por entrada (pool de sessões, uma por label). O upstream não vê o pool; não usa `_proxy_rotator`.
- Estado do pool protegido por `asyncio.Lock`; marcações de saúde com `cooldown` só valem para atribuições novas.
- `ProxyEntry.__repr__` mostra só `label` e `group`. A URL fica num atributo privado e só é lida ao criar a sessão.
- Navegador (v1): só afinidade, sem failover. Um contexto do Chromium é preso a um proxy; trocar exigiria novo
  contexto e perderia estado. Falha do proxy no navegador = RSP-N004. Credencial vai em `username`/`password`
  separados para o Playwright (resolve o C4 do bugs.md).
- Pausa e retomada: o checkpoint guarda `{domínio: label}` e o hash da lista de labels. Na retomada, se o pool não
  tiver os mesmos labels, falha com RSP-F005 em vez de reatribuir em silêncio.

## Auditoria (novos eventos C6)

| evento | campos | quando |
| --- | --- | --- |
| `proxy_assigned` | domain, label, group | primeira atribuição do domínio no run |
| `proxy_failover` | domain, from_label, to_label, reason (`proxy_auth`, `proxy_unreachable`, `proxy_resolve`) | troca por I3/I4 |
| `proxy_exhausted` | domain, group | I6 disparou |

Nunca a URL. `reason` é um código fechado, não a mensagem do libcurl.

## Critérios de aceite (todos automatizados, transporte falso)

| id | teste | invariante |
| --- | --- | --- |
| A1 | 100 requests ao mesmo domínio saem pela mesma entrada | I1 |
| A2 | dois runs seguidos atribuem a mesma entrada ao domínio | I1 |
| A3 | com 3 proxies, a concorrência por domínio continua 1 e o delay não cai | I2 |
| A4 | 403, 429, 503 e página de desafio do alvo não mudam a entrada nem a saúde do pool | I3 |
| A5 | timeout de leitura e falha de CONNECT 502 não disparam failover | I3 |
| A6 | 407 e falha de conexão até o proxy disparam failover e registram `proxy_failover` | I3 |
| A7 | erro com sonda ok não dispara failover; com sonda falhando, dispara | I4 |
| A8 | terceiro failover no mesmo domínio vira `domain_stopped` | I5 |
| A9 | todos os proxies mortos: RSP-N004, e o transporte falso não recebe nenhuma requisição sem proxy (robots incluso) | I6 |
| A10 | failover não cruza grupo; domínio do mapa explícito não sai do grupo | I7 |
| A11 | varredura de segredo: senha do proxy ausente de caplog, stderr, stats, `CrawlResult`, auditoria e checkpoint em todos os testes acima | I8 |
| A12 | UA e headers idênticos em todas as entradas | I9 |
| A13 | `verify=False` com pool: RSP-P010; `socks5://` recusado, `socks5h://` aceito | I10 |
| A14 | nenhuma ferramenta MCP aceita `proxy`/`proxy_pool` (schema) | I11 |
| A15 | proxy e `proxies` por request continuam P006 com pool configurado | I12 |
| A16 | retomada com labels diferentes: RSP-F005 | I8 |
| A17 | contrato com o upstream: o pool não toca `_proxy_rotator`; teste de contrato atualizado | I12 |
| A18 | alvo http responde 407: nenhuma mudança de entrada nem de saúde | I3 |
| A19 | CONNECT sem resposta (alvo dropando o IP do proxy): sem failover, RSP-N001 | I3 |
| A20 | `EX.com`, `ex.com:443`, `ex.com.` e `a.ex.com` caem na mesma entrada e no mesmo limiter | I1, I2 |
| A21 | dois sids com proxies diferentes no mesmo domínio: P006 (feito) | I12 |
| A22 | `NO_PROXY=<alvo>` no ambiente: nenhuma conexão sem proxy, testado na costura do curl (feito) | I6, I13 |
| A23 | todos os testes de A9 e A11 rodam na costura do curl_cffi, não em `_make_request` | I6, I8 |
| A24 | launch kwargs do Playwright sem userinfo no `server` (feito) | I8 |

Além dos automatizados, um manual fora do sandbox: dois proxies reais (um derrubado de propósito) contra um servidor
de teste próprio, conferindo no log do servidor que só um IP de saída aparece por domínio.

## Degradação e falha

- Pool vazio ou todas as URLs inválidas: erro na construção (RSP-U003), antes de qualquer rede.
- Sonda configurada mas inalcançável na partida: aviso e failover reduzido ao modo sem sonda (I4), não erro.
- Lock ou estado corrompido: a exceção sobe como bug (saída 1); não há caminho que "sai direto" por exceção.

## Ordem de entrega

1. Feito: BUG-006, BUG-007, BUG-008. Base para A11, A21, A22, A24.
2. Feito (v1, `raspador.ProxyPool`; tests/test_proxy_pool.py e tests/test_proxy_pool_revisao.py): HTTP com
   afinidade estática por eTLD+1 do host canônico (IDN/fullwidth em punycode via `idna` UTS 46, IPv4 em qualquer
   notação, sem porta/userinfo/ponto final; `publicsuffixlist` embutida), rendezvous hashing, sem failover.
   Segunda revisão adversarial (12 achados) corrigida antes do commit:
   - chave canônica (R1, R11) também na política (Referer) e nos contadores do spider (BUG-009);
   - pool recusa sessão de navegador no mesmo spider (R2); robots de navegador passa pelo egress (BUG-009);
   - `verify` diferente de True/caminho por request com pool: RSP-P010 (R3);
   - entradas só `http`, `https`, `socks5h` (R4); URL de proxy com caminho, query, fragmento ou porta inválida é
     recusada e a mensagem mascara tudo antes do último `@` (R5; senha com `#`, `/`, `?` precisa de percent-encoding);
   - `session_kwargs` do pool recusa `Authorization`, `Cookie`, `cookies` e `cert` (R6): iriam para todos os domínios;
   - `FetcherSession` crua com `proxies`/`proxy_auth` é P006 e ganha `trust_env=False` (R7, BUG-009);
   - o roteamento atua numa cópia do request: o sid do usuário segue no fingerprint e no `follow()` (R8);
   - sid `proxy:<label>` de entrada removida é re-roteado pelo pool em vez de sumir (R9);
   - chave de `affinity` com esquema, `/`, `*` ou duas chaves do mesmo site: ValueError (R10).
   Verificação da correção (mesmo revisor): 9 fechados, A5 e A6 parciais, A12 aberto. Fechados depois:
   - A5: userinfo do proxy só com unreserved, sub-delims sem aspas e `%XX`; espaço, tab e controle recusados na
     string crua (o `urlsplit` descarta tab, o curl não); meta e `stats.proxies` usam a máscara forte (`mask_proxy`);
   - A6: `session_kwargs.headers` do pool só aceita Accept, Accept-Language, Accept-Encoding e User-Agent;
   - regressão: `allowed_domains` com IDN Unicode bloqueava tudo; agora os dois lados são canônicos;
   - subclasse de `FetcherSession` (escapava do `trust_env=False`): RSP-P007;
   - host que não canoniza (rótulo vazio, soft hyphen, zero-width) é RSP-U001 no `check_url`, auditado.
   Limites conhecidos da v1:
   - `stats.sessions_requests_count` e `response.request.sid` mostram o sid do usuário (ex.: `default`), não a
     entrada do pool: o roteamento é numa cópia de propósito (dedup e `follow()`); a entrada fica na auditoria
     (`proxy_assigned`);
   - robots.txt e limiter do upstream por netloc cru: duas grafias do mesmo host buscam o robots duas vezes (pelo
     mesmo IP);
   - P006 de egress no robots.txt de um navegador aparece como falha de robots (o request some como negado); a
     auditoria registra o `policy_error` com a URL do robots.txt;
   - redirect do robots.txt de navegador (`follow_redirects="safe"`) não passa por `_check_egress` (pré-existente);
   - o `CapacityLimiter` do upstream é por netloc cru. Correção da v1 do plano: isso NÃO vai na direção segura.
     `a.ex.com`, `b.ex.com` e `EX.com` ganham cada um seu `concurrent_requests_per_domain` e saem pelo mesmo IP, então
     o alvo vê a concorrência somada (R12). Mitigação até lá: `concurrent_requests` global baixo; correção real exige
     trocar a chave do limiter no engine (atributo privado, entra no teste de contrato);
   - navegador não usa o pool (recusado no mesmo spider);
   - sem checkpoint de atribuição (A16): a atribuição é determinística.
   Mudança de comportamento também sem pool: o egress por domínio usa eTLD+1, então subdomínios do mesmo site em
   sessões com proxies diferentes (`br.loja.com` por um proxy BR, `us.loja.com` por um US) agora caem em RSP-P006;
   `HTTP(S)_PROXY` do ambiente não vale mais (BUG-008). Ambas vão para o changelog.
3. Bloqueado: spike da costura do handle do curl. Só depois, failover com sonda e teto (A4–A8, A10, A16, A18, A19).
4. Navegador com afinidade e credencial separada (fecha C4).
5. Docs na primeira tela: o que o pool faz e o que não faz. `features.csv`: ProxyRotator → `partial`, nota "pool com
   afinidade e failover; rotação por request fora por política".

## Fora de escopo

Rotação por request, distribuição de um domínio por vários IPs, troca por bloqueio do alvo, pool configurável pelo
MCP, proxies residenciais "rotativos" do fornecedor (o fornecedor rotaciona por trás; a doc deve avisar que isso
quebra I1 sem o raspador ver, e recomendar sessão fixa do fornecedor).

## Questões abertas

1. Resolvida pela revisão: eTLD+1 normalizado. A divergência com a chave do throttle do upstream vai na direção
   segura. Custo: dependência da lista de sufixos públicos (`tldextract` com cache offline, ou `publicsuffix2`).
   O egress por run do BUG-007 hoje usa host; migrar para a mesma chave no passo 2.
2. Sonda obrigatória quando `failover=True`? Obrigatória deixa I3 mais forte; opcional deixa o pool usável sem
   infraestrutura extra.
3. `max_failovers_per_domain=2` é razoável para proxy corporativo, ou 1 basta?
