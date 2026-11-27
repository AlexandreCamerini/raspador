# Bugs: raspador

Build testado: `3c4e0db` (main). Data: 2026-11-26. Só entra o que foi reproduzido; o resto fica em "A conferir".

### BUG-001: esquema e host da URL nunca são validados; `file://` chega ao curl

- Severity: S1 (falha de segurança latente: leitura de arquivo local)
- Flow / case: F01-E1/E2/E3/N4, F02-E1, F06-E1, F10-E3, F11-N2
- Superfície: S01, S03, S07, S11, S13
- Build: `3c4e0db`, Python 3.12, curl_cffi 0.17

Passos
1. `raspador.get("file:///etc/passwd")`, ou `get("")`, `get("ex.com/p")`, `get("ftp://ex.com/x")`.
2. Ou: uma página `https://ex.com/r` responde `302 Location: file:///etc/hosts`.
3. Ou: `make_request` no MCP com `file:///...`; ou um spider com `start_urls = ["file:///..."]`.

Expected: recusa imediata, antes de qualquer acesso, com um erro claro de URL inválida.
Actual: a URL vai para o curl_cffi, que lê `file://` (confirmado: `curl_cffi.requests.get("file://.../segredo.txt")`
devolve o conteúdo do arquivo). Hoje o arquivo só não sai por acidente: o robots.txt de `file:///robots.txt` falha,
falha vira "tudo negado" e o erro aparece como RSP-R001 "o robots.txt de  não permite". Se existir um
`/robots.txt` local permitindo, o arquivo é lido. No redirect, o salto para `file:///etc/hosts` é seguido.
No MCP a URL vem de um modelo, que uma página pode induzir.
Evidence: tests/e2e/test_aceite.py::test_f01_e1_e2_e3_url_invalida_e_recusada_antes_da_rede (6 variantes),
test_f01_n4_redirect_para_file_nao_e_seguido, test_f02_e1, test_f06_e1, test_f10_e3, test_f11_n2 (3 variantes).
Sonda: `[..., 'file:///robots.txt', 'file:///etc/hosts']` na lista de requisições do transporte falso.
Suspected cause: nenhuma checagem de esquema; o robots e a guarda de SSRF supõem http(s) com host.
Status: fixed em `000b863`: `http.check_url` (só http/https com host) na primeira URL e em cada salto de redirect, no avulso, sessões, spider (o robots não busca nada para URL inválida; o manager audita uma linha policy_error RSP-U001 com a URL certa, sem robots_denied — achado na revisão: a primeira versão auditava `file:///robots.txt` e contava a start URL como robots negado, e cada link mailto:/tel:/javascript: inflava `robots_disallowed_count`), navegador (antes de abrir e na URL final), CLI (saída 2) e MCP. Confirmado com curl real: `raspador get file://.../segredo.txt -` sai com RSP-U001 e código 2

### BUG-002: seletor CSS inválido derruba a CLI (saída 1) e o MCP ("unexpected exception")

- Severity: S3 (quebrado, com contorno: corrigir o seletor)
- Flow / case: F10-E1, F11-N3
- Superfície: S11, S13

Passos
1. `raspador get https://ex.com/p out.md -s "[["`
2. MCP: `make_request(url=..., css_selector="[[")`

Expected: erro de uso com código (saída 2 na CLI; erro de ferramenta RSP-U002 no MCP).
Actual: CLI sai com 1 (código de bug) via `SelectorSyntaxError`; MCP registra traceback inteiro como
"Tool 'make_request' raised an unexpected exception" e devolve "Error executing tool make_request" sem dizer o quê.
Evidence: test_f10_e1_seletor_invalido_e_erro_de_uso, test_f11_n3_mcp_seletor_invalido_e_erro_de_ferramenta.
Status: fixed em `000b863`: `_render.check_selector` valida antes de buscar; CLI sai com 2 e RSP-U002, MCP devolve erro de ferramenta RSP-U002

### BUG-003: `headers` como texto dá `AttributeError` interno

- Severity: S4 (mensagem ruim; o uso é errado de qualquer forma)
- Flow / case: F01-N3

Passos: `raspador.get("https://ex.com/p", headers="User-Agent: x")`
Expected: `TypeError` dizendo que `headers` precisa ser um dict.
Actual: `AttributeError: 'str' object has no attribute 'items'` de dentro de `policy.check_headers`.
Evidence: test_f01_n3_headers_como_texto_da_erro_claro.
Status: fixed em `000b863`: `policy.check_headers` levanta TypeError dizendo que headers precisa ser dict

### BUG-004: `storage_state` inexistente é aceito na construção da sessão de navegador

- Severity: S3 (falha tardia, longe da causa)
- Flow / case: F03-N1

Passos: `browser.BrowserSession(storage_state="/nao/existe.json")`
Expected: erro imediato RSP-F004 com o caminho.
Actual: o objeto é criado sem reclamar; a falha só viria ao abrir o contexto do Chromium.
Evidence: test_f03_n1_estado_inexistente_falha_na_construcao.
Status: fixed em `000b863`: `StateFileMissing` (RSP-F004) na construção e em `load_state`

### BUG-005: filtro inválido nas ferramentas de rede do MCP vira "unexpected exception"

- Severity: S3 (quebrado, com contorno: corrigir o filtro)
- Flow / case: F04-N1
- Superfície: S13

Passos: `browser_open(record_requests=true)`, depois `browser_network_requests(url_pattern="[")` ou `(limit=0)`.
Expected: erro de ferramenta com código.
Actual: o `ValueError` do `NetworkRecorder.search` do upstream escapa da tradução de erros; o servidor loga
"raised an unexpected exception" e o modelo recebe só "Error executing tool browser_network_requests".
Evidence: tests/e2e/test_aceite.py::test_f04_n1_mcp_filtro_de_rede_invalido_e_erro_de_ferramenta (2 variantes).
Status: fixed em `000b863`: `ValueError` vira ToolError RSP-M005 com o motivo

### BUG-006: credencial de proxy vaza no log do upstream, em erros, stats, meta e argv do navegador

- Severity: S1 (vazamento de credencial no caminho padrão, disparável pelo alvo). Reclassificado de S2 depois da
  revisão independente: a primeira correção não pegava o caminho principal.
- Achado em: /replica-diff, ao avaliar o ProxyRotator; ampliado pela revisão adversarial
- Superfície: S01, S03, S07, S11

Passos
1. `RASPADOR_PROXY=http://cliente:senha@127.0.0.1:9 raspador get https://ex.com/ x.md` (sem `-v`).
2. Spider com `retry_blocked_request` que põe proxy por request.
3. `raspador.get(url, proxy="http://cliente:senha@p:8080")` e depois `response.follow(...)` num spider com crawldir.

Expected: a senha nunca aparece; o host do proxy continua visível para diagnóstico.
Actual (antes):
- o upstream loga `WARNING: Proxy 'http://cliente:senha@...' failed` em cada retry (`static.py:283/501`); o gatilho é
  substring ("connection reset", "failed to connect"), então o alvo dispara com um RST;
- `stats.proxies` e a mensagem do RSP-P006 mostravam a URL crua; `proxies` (dict) escapava do P006;
- `Response.meta["proxy"]` carregava a URL, `follow()` copiava para o próximo request e o checkpoint fazia pickle;
- proxy sem esquema (`cliente:senha@host:porta`, que o curl aceita) não era reconhecido pelo mascarador;
- `proxy_auth=("u", "senha")` e `curl_options` saíam inteiros na mensagem de P001;
- auditoria tirava só a query, não o `usuario:senha@`; `@` cru na senha deixava sobra;
- navegador: `{"server": url_com_senha}` vai para o argv do Chromium (`ps`) e para o call log do Playwright;
- `Proxy-Authorization` como header era aceito (em túnel HTTPS o libcurl manda para o alvo);
- a ajuda do `--proxy` sugeria pôr a senha na linha de comando.
Evidence: tests/test_segredos.py (8), tests/test_segredos_curl.py (12, na costura do curl_cffi: o log e o meta do
upstream rodam de verdade), test_contract_upstream::test_engine_anota_proxy_nas_stats_antes_do_fetch_do_manager.
Reprodução real repetida após a correção: `Proxy 'http://***@127.0.0.1:9'`, zero ocorrências da senha.
Status: fixed em `d5f9bc9`: `raspador._redact` (URL com e sem esquema, opções de
autenticação inteiras, fábrica de LogRecord para `scrapling.*` e `raspador.*`, limpeza de `meta`); proxy exige
esquema (RSP-U003, saída 2); `Proxy-Authorization` é RSP-P003; navegador passa `username`/`password` separados
(resolve C4); `--proxy` aceita `RASPADOR_PROXY`.

### BUG-007: trocar de `sid` muda o proxy de saída no mesmo domínio e contorna o RSP-P006

- Severity: S2 (furo de política: rotação de proxy após bloqueio sem nenhuma opção proibida)
- Achado em: revisão adversarial

Passos: duas sessões `spider_session(proxy=A)` e `spider_session(proxy=B)`; `retry_blocked_request` faz
`request.sid = "b"`.
Expected: recusa RSP-P006 auditada.
Actual: a página saiu por A e depois por B; a auditoria só registrou `blocked_retry`. Alternar sid em
`start_requests` dava rotação por request.
Evidence: test_segredos_curl::test_trocar_de_sid_para_sair_por_outro_proxy_no_mesmo_dominio_e_p006 (e o controle
test_dominios_diferentes_podem_usar_sessoes_com_proxies_diferentes).
Status: fixed em `d5f9bc9`: `GuardedSessionManager` fixa um egress (proxy ou direto) por
host no primeiro acesso do run; outro egress no mesmo host é RSP-P006 com `detail="sid"`. Limite: a chave é o host;
subdomínios diferentes podem usar proxies diferentes (ver plano do ProxyPool, B4).

### BUG-008: `NO_PROXY` no ambiente faz o libcurl ignorar o proxy explícito e sair pelo IP real

- Severity: S2 (vaza o IP real do operador; exige a variável no ambiente)
- Achado em: revisão adversarial

Passos: `NO_PROXY=ex.com RASPADOR_PROXY=http://p:8080 raspador get https://ex.com/ x.md`.
Expected: sai pelo proxy.
Actual: o curl_cffi usa `trust_env=True` e só zera `NOPROXY` com `trust_env=False`; o libcurl lê `no_proxy` sozinho
e conecta direto (página e robots.txt).
Evidence: test_segredos_curl::test_no_proxy_* (sync, async, spider_session).
Status: fixed em `d5f9bc9`: toda sessão curl do raspador nasce com `trust_env=False`.
Mudança de comportamento: `HTTP(S)_PROXY` do ambiente deixa de valer; o proxy precisa ser explícito (`--proxy`,
`RASPADOR_PROXY` ou `proxy=`). Documentar no changelog.

### BUG-009: grafias do mesmo host, sessão crua com `proxies=` e robots.txt de navegador escapavam do egress por domínio

- Severity: S2 (furo de política e conexão pelo IP real; achados na revisão adversarial do ProxyPool, mas existiam
  também sem pool)
- Achado em: revisão adversarial do ProxyPool v1

Passos e Actual (antes):
1. IDN: `https://müller.com/` e `https://xn--mller-kva.com/` (o mesmo host para o curl) tinham chaves diferentes:
   dois egress para o mesmo site, contadores de bloqueio e parada de domínio separados (alternar grafias contornava
   o `domain_stopped`), e o Referer do `follow()` entre as duas grafias caía em RSP-P003 falso. O mesmo para
   fullwidth (`ｅｘ.com`), `。` e IPv4 em decimal/hexadecimal (`1572395042`, `0x5d.0xb8.0xd8.0x22`).
2. `FetcherSession(..., proxies={...})` crua no spider: `_egress_of` só lia `_default_proxy`, então dois sids com
   `proxies` diferentes davam dois IPs no mesmo domínio sem P006; e a sessão crua ficava com `trust_env=True`.
3. robots.txt de sid de navegador saía por `_robots_http` sem checar o egress do domínio (e todos os navegadores
   dividiam o cliente de robots do primeiro, com o proxy dele).
4. Host com percent-encoding (`exa%6dple.com`) passava no `check_url`; o curl decodifica.
Evidence: tests/test_proxy_pool_revisao.py (R1, R2, R7, R11).
Status: fixed em `d5f9bc9`: `raspador._hosts.canonical_host` (UTS 46 via `idna`, IPv4 por
`inet_aton`) usado na política, no spider e na chave de afinidade; `add` recusa `proxies`/`proxy_auth` (P006) e fixa
`trust_env=False` também na `FetcherSession` crua; robots de navegador passa por `_check_egress`, um cliente por
proxy; `%` no host é RSP-U001; `allowed_domains` comparado na forma canônica; subclasse de
`FetcherSession` é RSP-P007; host que não canoniza (rótulo vazio, caractere invisível) é RSP-U001.

### BUG-010: navegador buscava subrecurso e redirect em hostname que resolve para IP interno

- Severity: S2 (SSRF pelo navegador: no MCP a URL vem de um modelo; a página carrega `https://intranet/` ou um nome
  que aponta para 169.254.169.254)
- Found: revisão independente do README, 2026-11-27
- Steps: `BrowserSession().fetch(url)` de página com `<img src="https://intranet.exemplo/x">`, onde
  `intranet.exemplo` resolve para 10.0.0.5.
- Expected: requisição abortada, como já era para `localhost` e IP literal.
- Actual: `route_decision` só olhava IP literal; a requisição saía. A URL final de um redirect só passava por
  `check_url` (esquema e host), sem checagem de rede interna.
- Fix: `browser.internal_by_dns` (uma consulta por host na sessão, em thread na versão async) na guarda de rota;
  `browser.check_final_url` reaproveita `http.check_redirect_target`. A revisão adversarial da correção achou mais:
  exceção não-`OSError` no DNS travava a rota (agora falha fechada), popup e WebSocket fora do `page.route` (guarda
  no contexto e `route_web_socket`), service worker (bloqueado), NAT64 `64:ff9b::/96` e IPv4-compatível `::/96` não
  vistos como internos (corrigido em `_is_internal`), e nenhuma saída para intranet (`allow_private`, repassado pelo
  MCP). Limite: DNS rebinding e redirect de subrecurso (o Playwright só roteia a primeira URL). Testes:
  tests/test_lacunas_politica.py.
- Status: fixed (c9431c4)

### BUG-011: credencial por request saía pelo proxy do pool

- Severity: S2 (furo de política: a sessão do pool recusa credencial do site, o request não)
- Found: revisão independente do README, 2026-11-27
- Steps: spider com `proxy_pool` e `Request(url, headers={"Authorization": "Bearer ..."})` (ou `cookies=`, `cert=`).
- Expected: RSP-P010, nada enviado.
- Actual: `check_request_kwargs` aceitava e o request saía pelo proxy do domínio com a credencial.
- Fix: `_check_pool_request_credentials` em `GuardedSessionManager._guarded_fetch` quando há pool; auditado como
  `policy_error` com valor `***`. Sem pool, credencial por request continua permitida. A revisão adversarial achou
  usuário e senha na URL (iam inclusive no robots.txt), `X-Api-Key`/`X-Auth-Token` (a primeira versão era denylist)
  e nome de header com espaço (`"Authorization "`); agora é allowlist (`proxies.POOL_REQUEST_HEADERS`), a URL é
  checada, e `check_headers` recusa nome fora do token HTTP (P003) em qualquer modo. Mensagens `RSP-U001`/`N002`
  mascaram usuário e senha da URL. Limite: token na query string. Testes:
  tests/test_lacunas_politica.py.
- Status: fixed (c9431c4)

## A conferir (não reproduzido)

- C1: (resolvido pelo BUG-004) o erro de launch com `storage_state` inexistente não acontece mais: o caminho é checado antes.
- C2: `timeout` negativo ou zero é repassado ao curl sem validação. Comportamento do curl não verificado.
- C4: fechado. Credencial do proxy no navegador vai em `username`/`password` (BUG-006); verificado com Chromium real atrás de proxy local com Basic auth (`test_chromium_real_autentica_no_proxy_e_a_senha_nao_vaza` e o caso de senha errada em tests/test_browser.py), fora do sandbox.
- C5: corrigido em `b10a737`. Falha de rede, proxy ou 5xx no robots.txt agora é `RobotsUnavailable` (RSP-R002, subclasse de `RobotsDenied`: o site continua fechado), com o motivo (nome da exceção, sem a mensagem do curl, que pode trazer credencial, ou `HTTP 5xx`). CLI sai com 5 (rede) e dica de rede/proxy; MCP diz que o site não negou nada; spider audita `robots_unavailable` com `code` e `reason`. 401/403 seguem RSP-R001. Testes: tests/test_robots_indisponivel.py e o caso de porta fechada em tests/test_mcp_stdio.py.
- C3: fechado. tests/test_mcp_stdio.py cobre o subprocesso `raspador mcp` em stdio contra servidor HTTP real (make_request, robots negado, sessão HTTP, recusa de localhost sem `--allow-private`, RSP-R002 com rede fora). Rodada com Claude Code real (`claude -p --strict-mcp-config --mcp-config ...`, haiku) chamou `make_request` em https://example.com e descreveu a página corretamente; reprodução: replica/c3-claude-code.sh. Pegadinha registrada: o example.com atual não tem `<h1>`, e `--allowedTools` variádico engole prompt posicional (mandar pelo stdin).

- C6: crawl real fechado (2026-11-27). examples/citacoes.py em https://quotes.toscrape.com (site de treino de scraping): robots.txt consultado, 3 páginas, 30 itens com texto, autor e tags, nenhum campo vazio, auditoria sem evento (o log só grava recusa e falha). No sandbox o DNS cai e o run termina em RSP-R002 sem buscar página, como esperado. A conferir (S4, cosmético): nesse caso o log do Scrapling diz "Request disallowed by robots.txt", embora a causa seja rede; a auditoria registra o motivo certo.

## Resumo da rodada (2026-11-26)

Casos no plano: 42 de fluxo + 3 manuais. Dos 42: 40 rodados e passando, 1 n/a (F13, shell não construído), 1 skip (F14, sem Scrapy). Manuais: 3 pass (C3 fechado em `2b5ca1d`). Bugs: S1 2, S2 5, S3 3, S4 1 (BUG-006 a 011 achados no /replica-diff e nas revisões);
todos corrigidos com o teste vermelho antes. Nenhum S1 aberto.
