# Plano de testes: raspador

Build: `3c4e0db`; correções em `000b863`. Data: 2026-11-26. Ambiente: local, transporte HTTP falso (só
`_make_request` trocado, merge real do upstream), Chromium real fora do sandbox.

## Adaptação do replica-test

- **e2e** = testes de aceite em pytest, por fluxo, no próprio projeto (`tests/e2e/` para os casos novos desta
  rodada e os testes de módulo já existentes para o que eles cobrem). Playwright em TypeScript, axe e largura
  mobile não se aplicam: não há interface.
- **"Servidor original"**: nenhum teste toca o Scrapling remoto nem sites de terceiros. Os testes ao vivo do
  M2 foram manuais, em quotes.toscrape.com (site feito para treino), fora da suíte.
- Casos de borda da lista da skill que se aplicam a uma biblioteca de scraping: entrada vazia, malformada ou
  longa, acentos e emoji, dois processos ao mesmo tempo, repetir a execução, interromper no meio, rede lenta
  ou fora do ar, sessão expirada, encoding. Os de interface (back button, double click, leitor de tela, fuso
  na tela) não existem aqui.

## Casos

Coluna `auto`: o teste que cobre o caso. `e2e` = `tests/e2e/test_aceite.py`.

| case | fluxo | tipo | passos | esperado | auto | resultado |
| --- | --- | --- | --- | --- | --- | --- |
| F01-H1 | campo de página estática | happy | `raspador.get(url).css(sel).getall()` | valores, UA `raspador/`, sem `Sec-*`/Referer | test_http::test_get_avulso_ponta_a_ponta_offline | pass |
| F01-E1 | | URL vazia | `get("")` | RSP-U001 antes de qualquer rede | e2e | fail → BUG-001 → pass |
| F01-E2 | | URL sem esquema | `get("ex.com/p")` | RSP-U001 | e2e | fail → BUG-001 → pass |
| F01-E3 | | esquema não-HTTP | `get("file:///etc/passwd")`, `ftp://` | RSP-U001, nada lido | e2e | fail → BUG-001 → pass |
| F01-E4 | | acentos e emoji | página UTF-8 e latin-1 com "Promoção ☕" | texto intacto | e2e, test_heranca | pass |
| F01-E5 | | URL muito longa | query de 10 000 caracteres | requisição feita, sem erro da camada | e2e | pass |
| F01-E6 | | rede fora do ar | DNS falha | CLI: RSP-N001, saída 5 | e2e | pass |
| F01-N1 | | robots nega | `/privado` negado para `raspador` | RSP-R001, página não buscada | test_robots_avulso | pass |
| F01-N2 | | opção de evasão | `impersonate="chrome"`, `ja3=...` | RSP-P002 antes da rede | test_http, test_policy | pass |
| F01-N3 | | header inválido | `headers="User-Agent: x"` (string) | erro de uso claro | e2e | fail → BUG-003 → pass |
| F01-N4 | | redirect para `file://` | 302 `Location: file:///etc/hosts` | RSP-U001, salto não seguido | e2e | fail → BUG-001 → pass |
| F02-H1 | página com JS | happy | `browser.fetch(url, wait_selector=...)` | conteúdo renderizado, UA raspador | test_browser (Chromium) | pass (fora do sandbox) |
| F02-E1 | | `file://` no navegador | `browser.fetch("file:///etc/passwd")` | RSP-U001 antes de abrir o Chromium | e2e | fail → BUG-001 → pass |
| F02-N1 | | seletor nunca aparece | `wait_selector` inexistente | CLI: RSP-B002, saída 5 | test_cli | pass |
| F03-H1 | login reutilizado | happy | `save_state` → nova sessão com `storage_state` | cookie presente, arquivo 0600 | test_browser (Chromium) | pass (fora do sandbox) |
| F03-N1 | | estado inexistente | `BrowserSession(storage_state="/nao/existe.json")` | RSP-F004 na construção | e2e | fail → BUG-004 → pass |
| F04-H1 | API por trás da página | happy | `record_requests=True` → `network.search` | JSON da API sem refazer a requisição | test_browser (Chromium) | pass (fora do sandbox) |
| F04-N1 | | filtro de rede inválido (MCP) | `browser_network_requests(url_pattern="[")`, `limit=0` | erro de ferramenta RSP-M005 | e2e | fail → BUG-005 → pass |
| F05-H1 | seletor após redesign | happy | `auto_save` na v1, `adaptive` na v2 | elemento reencontrado | test_adaptive | pass |
| F05-E1 | | outro domínio | mesmo identifier em outro site | nada vaza | test_adaptive | pass |
| F06-H1 | crawl paginado + export | happy | Spider com follow → `to_json` | itens, robots uma vez por domínio | test_spider | pass |
| F06-E1 | | start_url `file://` | `start_urls = ["file:///etc/hosts"]` | descartada (RSP-U001 auditado), nada lido | e2e | fail → BUG-001 → pass |
| F06-E2 | | executar duas vezes | mesmo spider, sem crawldir | mesmos itens, sem estado residual | e2e | pass |
| F06-E3 | | links mailto/tel/javascript | página com esses links seguidos | nenhuma busca, nenhum robots_denied, uma linha de auditoria por link | e2e | fail → BUG-001 → pass |
| F06-N1 | | domínio bloqueia | 403 seguidos | domínio parado, auditado | test_spider | pass |
| F07-H1 | pausa e retomada | happy | `pause()` → nova execução | sem refazer o feito, log das duas | test_crawldir | pass |
| F07-E1 | | dois processos | lock de processo vivo | RSP-F002 | test_crawldir | pass |
| F07-N1 | | crawldir inseguro | 0777 | RSP-F001 | test_crawldir | pass |
| F08-H1 | modo dev | happy | duas execuções | segunda sem rede | test_templates | pass |
| F09-H1 | HTTP + navegador | happy | sessão de navegador com follow | renderiza e segue link | test_browser (Chromium) | pass (fora do sandbox) |
| F10-H1 | página → Markdown sem código | happy | `raspador get URL out.md` | arquivo, linha `ok` no stderr | test_cli | pass |
| F10-E1 | | seletor CSS inválido | `-s "[["` | erro de uso, saída 2, sem traceback | e2e | fail → BUG-002 → pass |
| F10-E2 | | diretório de saída inexistente | `OUT=/nao/existe/x.md` | RSP-F003, saída 7 | e2e | pass |
| F10-E3 | | URL `file://` na CLI | `raspador get file:///etc/hosts -` | saída 2, RSP-U001 | e2e | fail → BUG-001 → pass |
| F11-H1 | agente raspa | happy | cliente MCP → make_request | markdown sanitizado | test_mcp | pass |
| F11-E1 | | stdio de verdade | subprocesso `raspador mcp` | lista as 9 ferramentas | test_mcp | pass |
| F11-N1 | | endereço interno | 127.0.0.1, metadados de nuvem | RSP-N002 | test_mcp | pass |
| F11-N2 | | `file://` e URL vazia | `make_request("file:///etc/hosts")` | RSP-U001 | e2e | fail → BUG-001 → pass |
| F11-N3 | | seletor inválido | `css_selector="[["` | erro de ferramenta RSP-U002, sem "unexpected exception" | e2e | fail → BUG-002 → pass |
| F12-H1 | corpus RAG | happy | ContentSpider | Markdown por página | test_templates | pass |
| F13 | shell | — | — | não construído (could) | — | n/a |
| F14-H1 | parser no Scrapy | happy | `@scrapling_response` | Response do raspador | test_m4_templates | skip (Scrapy ausente) |

## Manual

| caso | por quê | resultado |
| --- | --- | --- |
| M1: crawl real de 2 páginas em quotes.toscrape.com | rede real; fora da suíte para não depender de terceiros | pass (M2) |
| M2: `raspador get` e `-H "User-Agent: Mozilla"` ao vivo | idem | pass (M2/M3) |
| M3: `raspador mcp` no Claude Code real | precisa configurar o cliente do usuário | pendente: ver bugs.md |
