# Mapa de recon: Scrapling (biblioteca Python + CLI + servidor MCP)

Alvo: Scrapling v0.5.1 (lançada em 2026-11-04), licença BSD-3-Clause, cerca de 105 mil estrelas no GitHub.
Escopo: o loop principal (fetch → parse → crawl → export), mais a CLI `extract` e o servidor MCP.
Para quem: o projeto `raspador`, de uso próprio. Premissa: não é um produto para vender; ajuste se for.
Data: 2026-11-25

## Premissas e adaptação do template

Scrapling é uma biblioteca, não um app com telas. Por isso o template foi adaptado assim:

- **"Tela" (S##)** = uma superfície de API pública, um comando de CLI ou um grupo de ferramentas MCP.
- **"Cliques"** = linhas de código ou comandos no caminho feliz.
- **"Estados"** = sucesso, HTTP 4xx/5xx, timeout, bloqueado (403/429/challenge), seleção vazia, JS não renderizado, pausado/retomado.
- `replica/screens/` e o diff de layout do replica-diff **não se aplicam**. Não há UI para capturar. Só o score de paridade por `features.csv` vale.
- Fontes usadas: só documentação pública (README, docs em readthedocs/repo, changelog, PyPI). Nenhum `.py` do pacote foi lido. As docs ficaram fora do projeto, em `$TMPDIR`.

## Risco número 1: construir, fazer fork ou empacotar

O Scrapling é BSD-3. A licença permite usar, fazer fork e redistribuir, desde que se mantenha o aviso de copyright. Isso muda a pergunta de "como clonar" para "por que clonar":

| opção | custo | ganho | onde quebra |
| --- | --- | --- | --- |
| Depender ou empacotar (`raspador` como camada fina sobre o `scrapling`) | dias | herda as correções do upstream, que lança versões a cada poucas semanas | fica preso às breaking changes do upstream (a v0.5 quebrou muita coisa) e às escolhas de evasão dele |
| Fork | semanas | controle total, dá para remover a família anti-bot | a manutenção é sua; o fork diverge rápido de um projeto com esse ritmo |
| Clean-room (o que este pack faz) | L (um trimestre) | código seu, superfície mínima, posicionamento próprio | só compensa com um motivo concreto (compliance, posicionamento, licença do cliente) |

Recomendação: **empacotar**, a menos que exista um motivo concreto para reescrever. O restante deste mapa vale para as três opções, porque descreve o comportamento-alvo.

### Decisão (2026-11-25): empacotar

O `raspador` é uma camada fina sobre `scrapling` (dependência fixa no PyPI). Consequências para o replica-architect:

- **Versão fixa e upgrade deliberado.** Fixar `scrapling==0.5.1` (ou `~=0.5.1`). Cada upgrade passa por uma suíte de contrato contra os fluxos F01-F14. A v0.5 mostrou que o upstream quebra a API sem aviso longo.
- **A família de evasão continua `skip`, agora como política da camada.** O código existe na dependência, então o raspador precisa:
  - não reexportar `StealthyFetcher` com `solve_cloudflare`, `impersonate` nem `stealthy_headers`
  - fixar esses parâmetros em off nas fábricas de sessão
  - rejeitá-los com erro explícito se alguém passar
  - não expor o servidor MCP do upstream como está; publicar um MCP próprio só com o subconjunto permitido, ou configurar o do upstream sem as ferramentas de evasão
- **Os padrões compliant são o valor da camada.** `robots_txt_obey=True`, AutoThrottle ligado, User-Agent identificado (`raspador/x.y (+contato)`), limites de concorrência por domínio conservadores.
- **Em `features.csv`, `clone` passa a significar "entregue e testado pelo raspador".** As notas dizem o marco (M0 a M4) e se a feature é "exposta pela camada" (vem do upstream) ou "reimplementada sobre Playwright/SDK mcp" (navegador e MCP).
- **Tamanho (corrigido em `architecture.md`):** HTTP, parser, spider e CLI ficam em **S** (dias). Navegador sobre o Playwright e MCP próprio ficam em **M** (semanas). Total: M.
- **Dependência do navegador (corrigido):** a ideia de usar só o núcleo mais o `playwright` puro **não funciona**. `scrapling.spiders` exige `patchright` no import (testado). O raspador depende de `scrapling[fetchers]`; `patchright` e `browserforge` ficam instalados e inertes. O v0.5 removeu o `DynamicFetcher`, então o navegador do raspador é um adaptador próprio sobre o Playwright puro. Detalhes em `architecture.md`.

## Fontes

| # | fonte | URL | notas |
| --- | --- | --- | --- |
| 1 | repositório + README | https://github.com/D4Vinci/Scrapling | pitch, lista de features, exemplos, patrocinadores |
| 2 | site de docs | https://scrapling.readthedocs.io/en/latest/ | lista de features mais completa |
| 3 | escolha de fetchers | https://scrapling.readthedocs.io/en/latest/fetching/choosing.html | comparação Fetcher × StealthyFetcher, Response |
| 4 | fetch HTTP | https://scrapling.readthedocs.io/en/latest/fetching/static.html | métodos, sessões, HTTP/3 |
| 5 | fetch com navegador | https://scrapling.readthedocs.io/en/latest/fetching/stealthy.html | sessões, estado, Shadow DOM, histórico de rede, CDP |
| 6 | seleção | https://scrapling.readthedocs.io/en/latest/parsing/selection.html | CSS/XPath, texto, regex, filtros, elementos similares, geração de seletor |
| 7 | classes de parsing | https://scrapling.readthedocs.io/en/latest/parsing/main_classes.html | Selector, Selectors, TextHandler, AttributesHandler |
| 8 | adaptativo | https://scrapling.readthedocs.io/en/latest/parsing/adaptive.html | fase de salvar e fase de casar, propriedades usadas |
| 9 | storage adaptativo | https://scrapling.readthedocs.io/en/latest/development/adaptive_storage_system.html | contrato `save`/`retrieve`, SQLite por padrão |
| 10 | spiders: começo | https://scrapling.readthedocs.io/en/latest/spiders/getting-started.html | primeiro spider, export, robots.txt |
| 11 | spiders: arquitetura | https://scrapling.readthedocs.io/en/latest/spiders/architecture.html | fluxo de dados, scheduler, checkpoint, cache |
| 12 | spiders: avançado | https://scrapling.readthedocs.io/en/latest/spiders/advanced.html | concorrência, AutoThrottle, pause/resume, modo dev, streaming, hooks |
| 13 | spiders: sessões | https://scrapling.readthedocs.io/en/latest/spiders/sessions.html | várias sessões roteadas por `sid` |
| 14 | spiders: requests | https://scrapling.readthedocs.io/en/latest/spiders/requests-responses.html | follow, prioridade, dedup, meta |
| 15 | spiders: proxy e bloqueio | https://scrapling.readthedocs.io/en/latest/spiders/proxy-blocking.html | ProxyRotator, detecção de bloqueio, retries |
| 16 | templates genéricos | https://scrapling.readthedocs.io/en/latest/spiders/generic-templates.html | CrawlSpider, SitemapSpider, feeds, ContentSpider, LinkExtractor |
| 17 | templates de plataforma | https://scrapling.readthedocs.io/en/latest/spiders/platform-templates.html | ShopifySpider |
| 18 | CLI | https://scrapling.readthedocs.io/en/latest/cli/overview.html | install, shell, extract |
| 19 | CLI extract | https://scrapling.readthedocs.io/en/latest/cli/extract-commands.html | get/post/put/delete/fetch, `--ai-targeted` |
| 20 | shell interativo | https://scrapling.readthedocs.io/en/latest/cli/interactive-shell.html | atalhos, `uncurl`, `view` |
| 21 | servidor MCP | https://scrapling.readthedocs.io/en/latest/ai/mcp-server.html | 17 ferramentas, transporte HTTP, autenticação |
| 22 | Agent Skill | https://scrapling.readthedocs.io/en/latest/ai/agent-skill.html | pacote de docs para agentes de código |
| 23 | RAG | https://scrapling.readthedocs.io/en/latest/ai/building-rag-systems.html | `markdown()`, ContentSpider |
| 24 | integração com Scrapy | https://scrapling.readthedocs.io/en/latest/integrations/scrapy.html | decorador `scrapling_response` |
| 25 | changelog | https://scrapling.readthedocs.io/en/latest/changelog.html | o que a v0.5 e a v0.5.1 priorizaram |
| 26 | benchmarks | https://scrapling.readthedocs.io/en/latest/benchmarks.html | a barra de performance a bater |
| 27 | PyPI | https://pypi.org/project/scrapling/ | versão, Python ≥3.10, extras e dependências |

Dependências declaradas no PyPI, que mostram a arquitetura:

- núcleo: lxml, cssselect, orjson, tld, w3lib
- `[fetchers]`: curl_cffi, playwright, patchright, browserforge, apify-fingerprint-datapoints, msgspec, anyio, protego
- `[ai]`: mcp, markdownify
- `[shell]`: IPython

## Loop principal

Buscar uma página (HTTP ou navegador), extrair campos com seletores que **sobrevivem a redesign** e escalar isso para um crawl concorrente, retomável e exportável. Tudo pela mesma API `Response`/`Selector`.

## Superfícies (equivalente a telas)

| ID | superfície | como acessar | propósito | componentes-chave | estados |
| --- | --- | --- | --- | --- | --- |
| S01 | `Fetcher` / `AsyncFetcher` | `Fetcher.get/post/put/delete(url, …)` | request HTTP avulso | Response, parser config | sucesso, 4xx/5xx, timeout, erro de SSL, redirect, encoding errado |
| S02 | `FetcherSession` | `with FetcherSession(...) as s:` (sync e async) | cookies e conexões persistentes | Session, ProxyRotator | aberta, fechada, proxy falhando |
| S03 | fetch com navegador avulso | `StealthyFetcher.fetch(url, …)` | renderizar JS, esperar seletor ou network idle | Response, WaitCondition | sucesso, timeout de espera, JS não renderizado, recurso bloqueado |
| S04 | sessão de navegador | `StealthySession` / `AsyncStealthySession` | navegador vivo entre fetches, `save_state`/`load_state`, `record_requests`, `cdp_url` | NetworkHistory, BrowserState, DomainBlocker | aberta, estado carregado, histórico cheio (limite), CDP remoto caiu |
| S05 | API de parsing | `page.css/xpath/find/find_all/find_by_text/find_by_regex/find_similar`, navegação | selecionar e extrair dados | Selector, Selectors, TextHandler(s), AttributesHandler | match, seleção vazia, HTML quebrado |
| S06 | parsing adaptativo | `css(..., auto_save=True)` e depois `adaptive=True`; backend plugável | reencontrar o elemento depois de mudança no site | StorageSystem, SimilarityMatcher | primeira gravação, match exato, match por similaridade, sem dados salvos, match errado |
| S07 | Spider | subclasse de `Spider`, `start()` / `stream()` | crawl concorrente com callbacks | Request, Scheduler, CrawlerEngine, SessionManager | rodando, pausado (Ctrl+C), retomado, concluído, erro em callback |
| S08 | templates de spider | `CrawlSpider`, `SitemapSpider`, `XMLFeedSpider`, `CSVFeedSpider`, `ContentSpider`, `ShopifySpider` | crawls comuns sem boilerplate | LinkExtractor, Rule | sitemap index, robots ausente, feed malformado, BOM |
| S09 | resultados e export | `result.items.to_json/jsonl/csv/xml`, `result.stats` | entregar os dados | ItemList, CrawlStats | vazio, parcial (pausado), completo |
| S10 | `scrapling install` | CLI | baixar navegadores e dependências de sistema | — | instalado, `--force`, falha de rede |
| S11 | `scrapling extract` | CLI `get/post/put/delete/fetch URL OUT` | scraping sem código; saída em .md, .html ou .txt pela extensão | CLIOptions, Sanitizer | sucesso, seletor sem match, erro HTTP |
| S12 | `scrapling shell` | CLI, IPython | explorar seletores interativamente | atalhos `get/fetch/page/pages`, `uncurl`, `curl2fetcher`, `view` | sessão viva, histórico das 5 últimas páginas |
| S13 | servidor MCP | `scrapling mcp` (stdio ou HTTP com auth) | agentes de IA navegam e extraem | 17 ferramentas: avulsas, sessão, estado, screenshot, extract, actions, evaluate, rede | sessão aberta, sessão perdida, erro com mensagem útil, conteúdo sanitizado |
| S14 | integração com Scrapy | decorador `@scrapling_response` em callback do Scrapy | usar o parser no Scrapy existente | adapter de Response | sucesso |
| S15 | Agent Skill | pacote de docs instalável | ensinar a API atual a agentes de código | — | desatualizada em relação à versão |
| S16 | imagem Docker | publicada a cada release | ambiente com navegadores prontos | — | — |

## Fluxos

```
F01 Extrair um campo de uma página estática
    S01 -> S05
    caminho feliz: 3 LOC (import, get, css().getall())
    borda: encoding errado, 403, seleção vazia, timeout

F02 Extrair de uma página renderizada por JS
    S03 -> S05
    caminho feliz: 3 LOC (+ network_idle ou wait_selector)
    borda: conteúdo carrega depois do idle, iframe, Shadow DOM aberto/fechado

F03 Fazer login uma vez e reutilizar
    S04 (login manual/automatizado) -> save_state(path) -> nova execução -> S04 load_state(path) -> S03/S05
    caminho feliz: ~6 LOC
    borda: estado expirado, incompatível com proxy_rotator, sessionStorage não persiste

F04 Descobrir a API por trás da página
    S04 record_requests=True -> navegar -> network.search(...) -> S02 chamar o endpoint direto
    caminho feliz: ~5 LOC
    borda: corpo binário não salvo, histórico estourou o limite, request não terminou

F05 Seletor que sobrevive a redesign
    S05 css(sel, auto_save=True) -> [site muda] -> S06 css(sel, adaptive=True)
    caminho feliz: 1 flag em cada execução
    borda: nada salvo para o domínio, match errado com score alto, identifier colidindo

F06 Crawl paginado com export
    S07 (start_urls, parse, response.follow) -> S09 to_json
    caminho feliz: ~12 LOC
    borda: loop de paginação, dedup por fingerprint, domínio fora do allowed

F07 Crawl longo com pausa e retomada
    S07 start(crawldir=...) -> Ctrl+C -> checkpoint -> S07 start(crawldir=...) (pula start_requests)
    caminho feliz: 1 argumento
    borda: crash no meio da escrita (precisa ser atômica), exceção deve preservar o checkpoint

F08 Iterar no parse sem bater no servidor
    S07 modo dev -> 1ª execução grava o cache -> próximas execuções reproduzem do cache
    borda: resposta bloqueada não pode entrar no cache como sucesso

F09 Spider com várias sessões
    S07 configure_sessions (HTTP + navegador) -> Request(sid=...) -> SessionManager roteia
    borda: sessão lazy, sessão de navegador lenta segurando a concorrência

F10 Página para Markdown sem código
    S11 scrapling extract get URL out.md [-s seletor] [--ai-targeted]
    caminho feliz: 1 comando
    borda: a extensão define o formato; seletor com vários matches

F11 Agente de IA raspa um site
    S13 browser_open -> browser_fetch -> browser_actions -> browser_extract -> close_session
    caminho feliz: 4-5 chamadas de ferramenta
    borda: prompt injection em conteúdo oculto, estouro de tokens, sessão órfã

F12 Corpus para RAG
    S08 ContentSpider -> arquivos .md sanitizados
    borda: conteúdo duplicado, páginas sem corpo principal

F13 Explorar seletores no terminal
    S12 get(url) -> page.css(...) -> view(page) / uncurl(curl do DevTools)
    borda: curl com cookies de sessão

F14 Adotar o parser num projeto Scrapy
    S14 @scrapling_response no callback
    caminho feliz: 1 decorador
```

## Componentes (primitivos públicos reutilizados entre superfícies)

| componente | variantes | estados | usado em |
| --- | --- | --- | --- |
| Response | HTTP, navegador | status, headers, cookies, body, encoding, meta | S01-S07, S13 |
| Selector / Selectors | elemento, lista | match, vazio | S05, S06, S07, S12, S14 |
| TextHandler(s) | string, lista | re, clean, json | S05 |
| AttributesHandler | — | busca por chave/valor, json | S05 |
| Session | HTTP sync/async, navegador sync/async | aberta, fechada | S02, S04, S07, S13 |
| ProxyRotator | cíclica, aleatória, ponderada, custom; override por request | proxy ok, proxy falhou | S02, S04, S07 |
| NetworkHistory | — | gravando, cheio, corpo não salvo + motivo | S04, S13 |
| BrowserState | — | salvo, carregado | S04, S13 |
| DomainBlocker / AdBlocker | lista própria, ~3.500 domínios | — | S03, S04, S13 |
| StorageSystem (adaptativo) | SQLite (padrão), Redis/custom | vazio, gravado | S06 |
| SimilarityMatcher | — | score por candidato | S06, `find_similar` |
| SelectorGenerator | CSS, XPath, completo ou curto | — | S05 |
| Request | direta, `response.follow` | prioridade, `dont_filter`, meta, `sid` | S07, S08 |
| Scheduler | BFS, DFS, prioridade | snapshot, restore | S07 |
| CrawlerEngine | — | concorrência global e por domínio, delay | S07 |
| AutoThrottle | — | acelera, recua (dobra o delay / Retry-After) | S07 |
| RobotsTxtChecker | — | permitido, negado, falha de lookup (não cacheia como permitido) | S07, S08 |
| BlockDetector + retry | padrão, custom | bloqueado, retry esgotado | S07 |
| Checkpoint | — | salvo periodicamente, final, limpo ao concluir | S07 |
| ResponseCache (modo dev) | — | hit, miss | S07 |
| LinkExtractor | allow/deny, domínios, escopo CSS/XPath, extensões, canonicalização | — | S08 |
| ItemList / CrawlStats | — | — | S07, S09 |
| Lifecycle hooks | on_start, on_close, on_error, on_scraped_item, start_requests | — | S07 |
| Markdown converter + AI sanitizer | página, elemento | remove hidden, aria-hidden, zero-width, comentários, template | S05, S11, S13, S08 |
| CLIOptions | conjunto comum de flags | — | S11 |
| MCPTool schema | avulsa, sessão | erro estruturado | S13 |

## Modelo de dados inferido

```
AdaptiveElementRecord  domain (da URL ou passado ao Selector), identifier,
                       tag, text, attributes{nome:valor}, siblings[tag], path[tag],
                       parent_tag, parent_attributes, parent_text
                       chave única: (domain, identifier)
                       evidência: parsing/adaptive.md, adaptive_storage_system.md
                       confiança: alta (campos); palpite (pesos do score de similaridade)

Request                url, method, headers, body, sid, callback, priority, meta, dont_filter
                       fingerprint = hash(url, method, body, sid)
                       evidência: spiders/architecture.md, requests-responses.md, changelog v0.5
                       confiança: alta (entradas do fingerprint); média (nomes exatos dos campos)

Checkpoint             pending_requests[Request], seen_fingerprints{set}
                       escrita atômica (tmp + rename), pickle, intervalo configurável
                       evidência: spiders/architecture.md, advanced.md
                       confiança: alta

CachedResponse         key = fingerprint, status, headers, body (base64), em JSON
                       evidência: spiders/architecture.md
                       confiança: alta

NetworkRecord          id, url, method, resource_type, status, request_headers, request_body,
                       response_headers, response_text (só Content-Type de texto), reason_if_not_saved
                       limite padrão: 1.000 requests; só requests concluídas (inclui 4xx/5xx)
                       evidência: changelog v0.5, ai/mcp-server.md
                       confiança: alta (comportamento); média (nomes dos campos)

BrowserState           cookies, localStorage, IndexedDB (JSON compatível com o storage_state do Playwright)
                       não inclui sessionStorage, abas nem settings
                       evidência: fetching/stealthy.md, ai/mcp-server.md
                       confiança: alta

CrawlStats             items_scraped, requests, status_{code}: n, bytes_por_domínio, completed/paused, ...
                       evidência: spiders/advanced.md
                       confiança: palpite (conjunto exato de campos)

MCPSession             session_id, session_type (static | browser), settings
                       evidência: ai/mcp-server.md
                       confiança: alta

Item                   dict livre emitido pelo callback
                       confiança: alta
```

Relacionamentos:

- Spider 1-n Session, roteada por `sid`
- Spider 1-1 Scheduler; Scheduler 1-n Request
- Request 1-1 Response, que gera 0-n Items e 0-n Requests
- Domain 1-n AdaptiveElementRecord
- BrowserSession 1-n NetworkRecord
- BrowserSession 0-1 BrowserState, por arquivo

## Matriz de features

Ver `features.csv`: 87 linhas. Must: 25, should: 29, could: 21. Clone=`skip`: 12 (10 da família de evasão). As contagens excluem as linhas `skip`.

S10 (`install`), S15 (Agent Skill) e S16 (Docker) não aparecem em nenhum fluxo. São superfícies de setup e distribuição, sem fluxo de usuário próprio.

## Fora de escopo (não pode ou não deve ser clonado)

A **família de evasão anti-bot** fica fora, como bloco único. O motivo é um só: é evasão de detecção e normalmente viola os termos de uso do site-alvo. Isso inclui:

- o solver de Cloudflare Turnstile/Interstitial
- a promessa do MCP de "resolver quase qualquer CAPTCHA"
- spoofing de fingerprint, ruído de canvas e patch de detecção headless
- patch de vazamento de CDP/WebRTC e defesa contra mismatch de timezone
- impersonação de TLS (`impersonate`) e `stealthy_headers`
- digitação "humana" com pausas aleatórias usada como camuflagem

Isso **remove um dos principais argumentos de venda do Scrapling**. O `raspador` vira um scraper compliant (robots.txt, AutoThrottle, User-Agent identificado), com outro posicionamento. Se esse diferencial importa para você, a opção certa é empacotar o upstream e responder por isso, não reescrever.

Também fica fora:

- o ecossistema de patrocinadores (proxies, APIs de token anti-bot)
- a comunidade (Discord, ~105 mil estrelas) e a marca
- as docs em 10 idiomas
- os binários de navegador (são dependência: Playwright/Chromium, não algo a construir)

Rodar a stack do Playwright não é evasão e fica no escopo. O mesmo vale para:

- sessões e estado salvo
- captura de rede
- rotação de proxy (uso legítimo: geolocalização)
- ShopifySpider (lê o JSON público da loja)

## Tamanho

Superfícies: 16. Fluxos: 14. Entidades: 9.

As partes difíceis:

1. **Qualidade do match adaptativo.** Score de similaridade sem falso positivo confiante; é o diferencial real e não tem spec pública dos pesos.
2. **Correção do engine.** Concorrência global e por domínio, dedup por fingerprint estável, checkpoint atômico, resume sem duplicar nem perder, cache dev que não guarda bloqueio.
3. **Robustez de sessões de navegador e captura de rede.** Ciclo de vida do Playwright, limites de histórico, decodificação de charset, CDP remoto.
4. **Economia de tokens do MCP e sanitização contra prompt injection.** Snapshots com referências de elemento, ações em lote, erros úteis.

Estimativa:

- **M** (algumas semanas) para o loop principal: HTTP + parser + adaptativo + spider + export + CLI extract
- **L** (um trimestre) somando sessões de navegador, captura de rede e servidor MCP
- empacotar o upstream: **S**

Sem promessa de paridade; o upstream lança versões a cada 2-6 semanas.
