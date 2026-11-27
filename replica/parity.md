# Paridade: raspador vs Scrapling 0.5.1

Data: 2026-11-27. Build: `2b5ca1d` (primeira versão em `000b863`; ProxyPool v1 em `d5f9bc9`, C4 em `cfd4bf1`, C5 e testes MCP em `b10a737`).
Score gerado por `parity.py replica/features.csv`; números abaixo são a saída real, não estimativa.

## Resumo

| métrica | valor |
| --- | --- |
| Overall | 84.9 / 100 (= feature score; não há layout) |
| Feature score | 84.9 (74 features pontuadas; 10 skip de evasão e 2 de rede/comunidade fora) |
| Must-haves | 25 de 25 |
| Layout score | n/a: biblioteca + CLI + MCP, sem tela. `imgdiff.py` não se aplica |
| Bugs abertos | 0 de qualquer severidade (bugs.md: BUG-001 a 009 fixed; C3, C4, C5 fechados) |

Correção da matriz nesta rodada: três linhas de parsing (TextHandler/AttributesHandler, `find_similar`, geração de
seletor CSS/XPath) estavam `no` embora funcionem via `raspador.Selector`, que herda o parser do upstream. Agora têm
teste de contrato e estão `yes`. Efeito: 80.3 → 84.2; depois o ProxyPool v1 (ProxyRotator `partial`) levou a 84.9. Nada foi marcado `yes` sem teste.

## Verdict

**Shippable.** A condição da rodada anterior foi cumprida: o gate completo passou fora do sandbox (Chromium,
porta local, MCP em stdio contra servidor HTTP real) e o Claude Code real chamou o `raspador mcp` com sucesso
(`replica/c3-claude-code.sh`). Só o template do Scrapy pula (extra não instalado). Para distribuir a terceiros já
existem README, LICENSE + NOTICE do Scrapling e CI; falta publicar (PyPI ou repositório) e um crawl real num site
com permissão. "Better than the original" não se aplica: `/replica-entrepreneur` não rodou.

## By area, weakest first
- distribution                   0.0  (1 features)
- mcp                           30.0  (10 features)
- integration                   50.0  (1 features)
- fetch-http                    84.2  (8 features)
- spiders                       85.7  (15 features)
- adaptive                      87.5  (3 features)
- fetch-browser                 90.9  (12 features)
- cli                           90.9  (5 features)
- parsing                       92.9  (11 features)
- templates                     93.8  (5 features)
- output                       100.0  (2 features)
- quality                      100.0  (1 features)

## Missing, in build order
- [should] parsing: Performance de parsing no nível de lxml (barra: benchmarks.md), no  ([M2] exposto pela camada; medir contra o benchmark de 5.000 elementos aninhados)
- [should] adaptive: Backend de storage plugável (SQLite padrão, thread-safe), partial  ([M2] exposto pela camada; | M2: SQLite do upstream em caminho próprio (adaptive.configure); backend plugável não exposto)
- [should] fetch-http: ProxyRotator: cíclica, aleatória, ponderada, custom, partial  ([M4] exposto pela camada; proibido em spiders (upstream troca proxy a cada retry); só proxy fixo por domínio | v1: raspador.ProxyPool com afinidade estática por eTLD+1 (mapa ou rendezvous), sem failover; rotação por request e troca por bloqueio fora por política (P006); tests/test_proxy_pool.py)
- [should] spiders: AutoThrottle com backoff em bloqueio e Retry-After, partial  ([M1] exposto pela camada; | M1: ligado por padrão; sem teste próprio)
- [should] spiders: Detecção de bloqueio + retries customizáveis, partial  ([M2] exposto pela camada; código novo: is_blocked do upstream só olha status; Retry-After + parar domínio após N bloqueios; sem rotação de proxy | M1: domínio para após N bloqueios seguidos; testado. Falta: Retry-After próprio (hoje só via AutoThrottle do upstream))
- [should] spiders: Lifecycle hooks: on_start, on_close, on_error, on_scraped_item, partial  ([M3] exposto pela camada; | M3: on_scraped_item testado; on_start/on_close/on_error sem teste próprio)
- [could] cli: Shell interativo IPython com atalhos, uncurl/curl2fetcher e view (S12), no  ([M4] reimplementado sobre Playwright/SDK mcp, sem StealthySession;)
- [could] distribution: Imagem Docker com navegadores a cada release (S16), no  ([M4] exposto pela camada;)
- [could] fetch-browser: Download de arquivos pelo navegador, no  ([M4] reimplementado sobre Playwright/SDK mcp, sem StealthySession;)
- [could] fetch-browser: Shadow DOM: pierce_shadow e seletores em shadow root fechado, no  ([M4] reimplementado sobre Playwright/SDK mcp, sem StealthySession;)
- [could] fetch-http: DNS-over-HTTPS para evitar vazamento de DNS com proxy, no  ([M4] exposto pela camada;)
- [could] fetch-http: HTTP/3, no  ([M4] exposto pela camada; via curl_cffi ou httpx[http3]; avaliar se vale)
- [could] mcp: Agent Skill com a API atual (S15), no  ([M4] reimplementado sobre Playwright/SDK mcp, sem StealthySession; barata se gerada das docs do clone)
- [could] mcp: MCP: browser_actions em lote (clicar, preencher, teclado, esperar, diálogos), no  ([M4] reimplementado sobre Playwright/SDK mcp, sem StealthySession; should→could: MCP adiado para M4 | M4: fora do subconjunto; ações em lote ficam para depois)
- [could] mcp: MCP: browser_evaluate (JS na página), no  ([M4] reimplementado sobre Playwright/SDK mcp, sem StealthySession;)
- [could] mcp: MCP: save/load de estado do navegador, no  ([M4] reimplementado sobre Playwright/SDK mcp, sem StealthySession;)
- [could] mcp: MCP: screenshot (viewport, página, elemento) e observe, no  ([M4] reimplementado sobre Playwright/SDK mcp, sem StealthySession;)
- [could] mcp: MCP: transporte HTTP streamable com autenticação, no  ([M4] reimplementado sobre Playwright/SDK mcp, sem StealthySession; should→could: MCP adiado para M4)
- [could] spiders: Estratégia BFS/DFS, no  ([M4] exposto pela camada;)
- [could] spiders: uvloop opcional, no  ([M4] exposto pela camada;)
- [could] integration: Decorador scrapling_response para callbacks do Scrapy (S14), partial  ([M4] exposto pela camada; | M4: reexport com storage do raspador; teste pula sem Scrapy instalado (o upstream exige Scrapy))
- [could] mcp: MCP: browser_extract (snapshot com refs, HTML, Markdown, texto, busca por regex), partial  ([M4] reimplementado sobre Playwright/SDK mcp, sem StealthySession; should→could: MCP adiado para M4 | M4: browser_fetch devolve markdown/html/text sanitizado com seletor; snapshot com refs de elemento não feito)
- [could] mcp: MCP: network_requests e network_request, partial  ([M4] reimplementado sobre Playwright/SDK mcp, sem StealthySession; should→could: MCP adiado para M4 | M4: browser_network_requests/request sobre o NetworkRecorder; sem teste MCP ponta a ponta com Chromium | id corrigido para network_id (o upstream não grava request_id); contrato fixa a chave)
- [could] templates: ShopifySpider (produtos públicos, um item por variante), partial  ([M4] exposto pela camada; lê o JSON público da loja; respeitar os ToS da loja | M4: herança; robots da loja testado; extração de produtos sem teste próprio)

Left out on purpose (not scored)
- Solver de Cloudflare Turnstile/Interstitial (solve_cloudflare): família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- MCP resolvendo CAPTCHA durante a navegação: família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- Spoofing de fingerprint do navegador (browserforge, datapoints): família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- Ruído de canvas contra fingerprinting: família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- Patch de detecção headless e de fingerprints do Playwright (patchright): família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- Patch de vazamento de CDP runtime e WebRTC: família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- Defesa contra mismatch de timezone: família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- Impersonação de fingerprint TLS (impersonate): família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- stealthy_headers (headers falsos coerentes com navegador real): família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- Digitação humana com pausas aleatórias usada como camuflagem: família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- Ecossistema de patrocinadores (proxies residenciais, APIs de token anti-bot): parcerias comerciais, não é produto
- Docs em 10 idiomas e comunidade (Discord, ~105 mil estrelas): rede e confiança não se clonam; docs só em PT-BR/EN

Yours, not in the original (not scored)
- Log de auditoria JSONL de decisões de política (C6)

## Left out on purpose (not scored)
- Solver de Cloudflare Turnstile/Interstitial (solve_cloudflare): família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- MCP resolvendo CAPTCHA durante a navegação: família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- Spoofing de fingerprint do navegador (browserforge, datapoints): família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- Ruído de canvas contra fingerprinting: família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- Patch de detecção headless e de fingerprints do Playwright (patchright): família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- Patch de vazamento de CDP runtime e WebRTC: família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- Defesa contra mismatch de timezone: família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- Impersonação de fingerprint TLS (impersonate): família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- stealthy_headers (headers falsos coerentes com navegador real): família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- Digitação humana com pausas aleatórias usada como camuflagem: família de evasão anti-bot: evasão de detecção, normalmente viola os ToS do alvo; fora do escopo
- Ecossistema de patrocinadores (proxies residenciais, APIs de token anti-bot): parcerias comerciais, não é produto
- Docs em 10 idiomas e comunidade (Discord, ~105 mil estrelas): rede e confiança não se clonam; docs só em PT-BR/EN

## Yours, not in the original (not scored)
- Log de auditoria JSONL de decisões de política (C6)

## Diferenças de comportamento

Comparação pela documentação pública e pelo código do upstream lido no recon; nenhum teste tocou servidores de
terceiros.

| fluxo | Scrapling faz | raspador faz | decisão |
| --- | --- | --- | --- |
| F01 identidade | `impersonate='chrome'`, `stealthy_headers=True`, Referer falso do Google | UA `raspador/x (+contato)`, sem `Sec-*`, sem Referer | keep (núcleo do produto) |
| F01/F06 robots.txt | `robots_txt_obey=False` por padrão | obrigatório; 401/403/5xx/falha = negado | keep |
| F06 concorrência | `concurrent_requests_per_domain=0` (sem limite), sem delay | 1 por domínio, `download_delay=1.0` | keep; mais lento por padrão, configurável |
| F06 bloqueio | troca de proxy a cada retry após bloqueio | para o domínio após N bloqueios seguidos, auditado | keep |
| F02 desafio anti-bot | `solve_cloudflare`, fingerprint, patchright | falha com RSP-H403 e dica "não há contorno" | keep |
| F01 URL | repassa qualquer esquema ao curl (`file://` lido) | só http/https com host, inclusive em cada redirect | keep (o upstream tem o furo do BUG-001) |
| F01 redirect | segue qualquer salto | checa SSRF, robots e offsite por salto; tira credencial cross-host | keep |
| F10 seletor inválido | `SelectorSyntaxError` com traceback | RSP-U002, saída 2, antes da rede | keep |
| F11 MCP | 17 ferramentas: screenshot, extract com refs, evaluate, ações em lote, estado, CAPTCHA | 9: buscar, ler, rede; primeira URL checada contra endereço interno | fix parcial: screenshot é o próximo candidato; evaluate/CAPTCHA ficam fora |
| F10 CLI | `scrapling extract get URL OUT` | `raspador get URL OUT` (um token a menos) | keep |
| F06 auditoria | não existe | JSONL por decisão de política | keep (só no clone) |
| install | navegadores patchright + dados de fingerprint | só `playwright install chromium` | keep |

Custo honesto das diferenças: em sites com anti-bot o raspador simplesmente falha onde o Scrapling passa. É
intencional, mas quem migrar esperando a mesma taxa de sucesso vai se frustrar; a documentação precisa dizer isso
na primeira tela (feito: README, seção de abertura).

## Próximos cinco (por peso no score e custo)

1. **Benchmark de parsing** (should, `no`). O parser é o mesmo do upstream; falta só medir contra o caso de 5 000
   elementos aninhados e registrar. Barato; +2 pontos de peso.
2. **Testes de `on_start`/`on_close`/`on_error`** (should, `partial`). Código herdado, sem teste próprio. Barato.
3. **Retry-After próprio + teste do AutoThrottle** (dois should `partial`). Hoje só o AutoThrottle do upstream
   honra Retry-After, e sem teste.
4. **Backend de storage adaptativo plugável** (should, `partial`). Expor a classe de storage em `adaptive.configure`.
5. ~~ProxyRotator~~ decidido: `raspador.ProxyPool` v1 com afinidade estática por eTLD+1, sem failover (`partial`);
   rotação por request e troca por bloqueio seguem proibidas (P006). Próximo candidato no lugar: MCP `screenshot`.

Depois disso, entre os could: MCP `screenshot`, download pelo navegador e Shadow DOM.
