# Arquitetura: raspador (camada compliant sobre o Scrapling 0.5.1)

Entrada: `replica/recon.md`, `replica/features.csv`, decisão de 2026-11-25 de **empacotar**.
Data: 2026-11-25

## Correção da recomendação anterior

No turno anterior recomendei usar só o núcleo do Scrapling mais o `playwright` puro, perdendo apenas a `StealthySession`. **Essa recomendação está errada.**

A prova saiu de um venv com `scrapling==0.5.1` e só as dependências não-stealth (curl_cffi, msgspec, anyio, protego, click, playwright):

| módulo | resultado sem patchright |
| --- | --- |
| `scrapling.parser` | importa |
| `scrapling.fetchers` | importa |
| `scrapling.spiders` | `ModuleNotFoundError: No module named 'patchright'` |

O certo é depender de `scrapling[fetchers]`. `patchright` e `browserforge` ficam instalados, mas o raspador nunca os executa.

## Evidência que define o desenho

Sondagem feita em 2026-11-25 contra `https://httpbin.org/headers`, só para ler os headers enviados:

| caminho | User-Agent | `Sec-Ch-Ua` | Referer |
| --- | --- | --- | --- |
| `Fetcher.get(url)` (padrão) | `Mozilla/5.0 (Windows NT 10.0; Win64; x64) … Chrome/152` | sim | `https://www.google.com/` (falso) |
| `FetcherSession()` (padrão) | idem | sim | idem |
| `Spider` sem `configure_sessions` | idem | sim | idem |
| `FetcherSession(impersonate=None, stealthy_headers=False, headers={UA raspador})` | `raspador/0.1 (+contato)` | não | nenhum |

Valores padrão do `Spider` lidos na classe:

- `robots_txt_obey=False`
- `autothrottle_enabled=False`
- `concurrent_requests=4`
- `concurrent_requests_per_domain=0` (sem limite)
- `download_delay=0.0`

Conclusão: **todo caminho padrão do upstream se disfarça de Chrome no Windows.** A política não pode ficar só na construção da sessão; tem que valer em cada fronteira por onde passa uma opção de fetch.

Outros fatos verificados:

- O único navegador do upstream é o `StealthyFetcher`, sobre o patchright. O `DynamicFetcher` (Playwright puro) foi removido na v0.5 (guia de migração). Logo, **todo navegador do raspador é implementação própria sobre o Playwright puro**.
- `SessionManager.add` aceita objetos duck-typed sem checar o tipo. O `SessionManager` usa `__aenter__`, `__aexit__`, `fetch` e `_is_alive`; `_client` só no ramo `FetcherSession`.
- O upstream não fixa mais as versões de `playwright` e `patchright`; o venv resolveu `playwright 1.65.2` e `patchright 1.64.4`.
- Venv completo: 332 MB. Sem os extras: 195 MB.

## Stack

| camada | escolha | por quê |
| --- | --- | --- |
| linguagem | Python ≥3.12 (testar 3.12-3.14) | o upstream exige ≥3.10; 3.12 está instalado aqui e tem tipagem moderna |
| projeto/env | `uv` + `pyproject.toml` (build hatchling), layout `src/raspador` | lock reprodutível; `uv` já está na máquina |
| dependência central | `scrapling[fetchers]==0.5.1` + **`uv.lock` commitado** | `==0.5.1` sozinho não fixa playwright nem patchright |
| HTTP | `FetcherSession` do upstream (curl_cffi) com `impersonate=None`, `stealthy_headers=False` | comprovado na sondagem; sem reimplementar o cliente |
| navegador | **extra opcional `raspador[browser]`**: adaptador próprio sobre `playwright` (já é dependência transitiva) | não existe navegador sem stealth no upstream; fica fora do núcleo para a camada continuar fina |
| parsing e adaptativo | `scrapling.parser.Selector` (puro, sem rede) | é o diferencial do upstream; zero risco de política |
| crawl | `scrapling.spiders.Spider` e templates, através de subclasses do raspador | herda o engine e o checkpoint; o raspador troca padrões, guarda a fronteira e corrige robots, redirects e bloqueio |
| Markdown | `markdownify` declarado direto no raspador | `scrapling[fetchers]` não o traz (só os extras `rag` e `ai`); `markdown()` existe em `Response`, não em `Selector` |
| CLI | `click` (já transitivo), comando `raspador` | mesma lib do upstream |
| MCP | **adiado (M4)**: SDK oficial `mcp` (FastMCP), servidor próprio, extra `raspador[mcp]` | o MCP do upstream expõe solver e stealth; um subconjunto próprio é mais seguro que filtrar, mas custa mais que o resto da camada |
| testes | pytest, pytest-asyncio, pytest-httpserver (servidor local) | testes de contrato de headers sem depender de terceiros |
| lint e tipos | ruff + pyright | o upstream também usa pyright |
| distribuição | wheel local; PyPI e Docker ficam para depois (could) | uso próprio |
| banco, auth, pagamento, email, hosting | **não se aplica** | é uma biblioteca local, sem servidor, usuários nem cobrança |

## Política (o núcleo da camada)

Revisada depois da revisão independente de 2026-11-25. Os achados marcados (✓) foram conferidos no código instalado.

**Modelo de ameaça:** evitar acidente e configuração errada, não impedir sabotagem. O `scrapling` está no mesmo ambiente; quem importar `scrapling.spiders.Spider` direto passa por cima da camada. O import guard e a doc tornam isso explícito.

Módulo `raspador.policy`. Erro: `PolicyError(option, reason)`.

**1. Allowlist de kwargs, não denylist.**

O motivo: o upstream repassa ao curl_cffi todo kwarg fora de um conjunto fixo (`_merge_request_args`). Por isso `ja3`, `akamai`, `extra_fp`, `default_headers` e `http_version` passariam por `Request(url, ja3=...)`. E `stealth=True` entra direto em `_make_request` (✓).

Kwargs aceitos em request, `Request(...)` e `follow(...)`:

| grupo | kwargs |
| --- | --- |
| HTTP | `headers`, `params`, `data`, `json`, `files`, `cookies`, `timeout`, `verify`, `cert`, `follow_redirects`, `max_redirects`, `retries`, `retry_delay` |
| proxy | `proxy`, só se fixo |
| navegador (adaptador próprio) | `wait_selector`, `wait_selector_state`, `network_idle`, `timeout`, `disable_resources`, `page_action`, `locale` |

Qualquer outro kwarg levanta `PolicyError`.

**2. Inspeção da instância, não só da classe.** O validador de `configure_sessions` checa, em cada sessão registrada, os atributos de estado reais: `_default_impersonate is None`, `_stealth is False` e `_default_headers` passando pela regra 3. Sem isso, `manager.add("x", FetcherSession())` passa e sai como Chrome. São atributos privados, então ficam fixados por teste de contrato no M0.

**3. Regra de headers (case-insensitive).**

| header | regra |
| --- | --- |
| `User-Agent` | obrigatório, começa com `raspador/` |
| `Sec-Ch-Ua*`, `Sec-Fetch-*`, `X-Forwarded-For`, `Client-IP`, `Forwarded`, `X-Real-IP` | proibidos |
| `Referer` | aceito só se for a URL de uma página do próprio crawl, como o `referer` que o `follow()` grava; Referer de terceiro (ex.: Google) é rejeitado |
| `Origin` | só o do próprio alvo |

**4. Padrões como atributos de classe, validados em `__init_subclass__`.**

O motivo: um context manager não pega uma subclasse que declara `download_delay = 0`.

| atributo | regra | padrão |
| --- | --- | --- |
| `robots_txt_obey` | **imutável, sempre `True`**; sem override | `True` |
| `download_delay` | ≥ 0.5 | 1.0 |
| `concurrent_requests_per_domain` | 1 a 4 | 1 |
| `concurrent_requests` | — | 4, o padrão do upstream |
| `autothrottle_enabled` | — | `True` |
| `autothrottle_start_delay` | — | 5.0, o padrão do upstream |

Observação: o `download_delay` é um sleep por slot, então com 1 slot por domínio a taxa fica em no máximo cerca de 1 req/s por domínio. Baixar o delay ou subir os slots além do limite exige `policy_override = "motivo"` declarado na classe, registrado no log C6.

**5. Fronteira por request.** `raspador.Spider.__init__` chama `super().__init__()` e troca `_session_manager` por um `GuardedSessionManager`, que valida cada `Request` (regras 1 e 3) antes de delegar. Depende de atributo privado; teste de contrato no M0. O `configure_sessions` do usuário roda contra o manager guardado.

**6. Proxy.** O upstream chama `proxy_rotator.get_proxy()` a cada tentativa, inclusive em retry de bloqueio (✓). Então:

- `ProxyRotator` é **proibido em spiders**.
- É permitido um proxy fixo por sessão (geolocalização).
- Se houver vários proxies, um por domínio, escolhido no início e mantido.
- Retry nunca muda de proxy.

**7. Bloqueio.** O `is_blocked` do upstream olha só o status (`{401, 403, 407, 429, 444, 500, 502, 503, 504}`) e não detecta challenge. Quando um request bloqueado esgota `max_blocked_retries`, o upstream só o descarta. O raspador acrescenta (**código novo**):

- respeitar `Retry-After`
- contar bloqueios por domínio
- **parar o domínio** depois de N bloqueios seguidos (padrão 5)
- registrar no log C6

**8. robots.txt.** O upstream consulta `can_fetch(url, "*")` (✓) e ignora regras para `User-agent: raspador`. Lookup 4xx (incluindo 401/403) vira "permitido"; 5xx ou exceção vira "negado"; não há TTL. O raspador sobrescreve (**código novo**):

- consulta com o token `raspador`
- 401/403 no robots tratado como negado
- TTL de 24 h no cache

**9. Domínio permitido e redirects.** O `allowed_domains` do upstream filtra só os requests gerados em callbacks, não o `start_requests`, o retry nem os redirects. O raspador:

- usa `follow_redirects=False` nas sessões de spider
- trata o redirect como um novo `Request` (que passa por domínio e robots)
- valida o `start_requests` contra `allowed_domains`

**10. Nunca reexportar** `Fetcher`, `AsyncFetcher`, `Fetcher.configure` (global), `StealthyFetcher`, `StealthySession`, `RemoteSession`, nem o MCP do upstream. Import guard (AST) no M0.

Notas sobre o upstream:

- O `response.follow` do upstream herda `headers` e proxy do request pai (segundo a revisão). Teste de contrato no M0 decide se o raspador limpa os headers no `follow`.
- `_client` só é usado no ramo `FetcherSession`. Uma sessão de navegador duck-typed precisa de `fetch`, `_is_alive`, `__aenter__` e `__aexit__`. O spike é menos frágil do que o rascunho dizia.

## Contratos de arquivo (substituem o schema SQL)

Não há `schema.sql`. O raspador não tem servidor nem banco próprio, e inventar um seria engenharia sem requisito. O que persiste são arquivos:

| # | arquivo | dono do formato | caminho padrão no raspador | regra |
| --- | --- | --- | --- | --- |
| C1 | storage adaptativo (SQLite) | upstream, chave (domínio, identifier) | `~/.raspador/adaptive.db` (ou `RASPADOR_HOME`) | o raspador só escolhe o caminho; o formato pode mudar a cada upgrade, então o teste de contrato cobre salvar → casar |
| C2 | checkpoint (`crawldir`) | upstream, **pickle** | escolhido pelo usuário | **carregar pickle não confiável executa código**. O upstream cria o `crawldir` com `mkdir` padrão. O raspador (código novo) cria com permissão 0700 e recusa carregar se o dono for outro ou se o diretório tiver escrita para grupo ou outros |
| C3 | cache do modo dev | upstream, JSON (chave = fingerprint, body em base64) | `.raspador-cache/` no projeto, no `.gitignore` | nunca em produção; resposta bloqueada não entra (fix do upstream na v0.5) |
| C4 | estado do navegador | Playwright `storage_state` (JSON) | escolhido pelo usuário | contém cookies de sessão: tratar como segredo, permissão 0600, nunca commitar |
| C5 | exports | upstream `ItemList` → JSON, JSONL, CSV, XML | escolhido pelo usuário | itens com dado pessoal sujeitos à LGPD (ver "Partes que mordem") |
| C6 | log de auditoria (F-AUD) | **raspador** (JSONL) | `<crawldir>/audit.jsonl` ou `~/.raspador/audit/` | uma linha por decisão de política: robots negado, override, domínio parado por bloqueio |

C6 é a única capacidade nova que não está no `features.csv`. Entra lá como linha `should` e fica fora da fatia vertical.

## API pública

As "rotas" de uma biblioteca são suas entradas públicas.

| entrada | faz | quem chama | entrada | saída | fluxo |
| --- | --- | --- | --- | --- | --- |
| `raspador.get/post/put/delete(url, **kw)` | request avulso compliant | código do usuário | url, headers, params, data/json, timeout, proxy | `Response` do upstream | F01 |
| `raspador.http_session(**kw)` / `async_http_session` | sessão HTTP compliant | código do usuário, spiders | o mesmo, mais `proxy_rotator` | `FetcherSession` configurada | F01, F04, F09 |
| `raspador.Selector` (reexport) | parsing e adaptativo sem rede | código do usuário | html, url, `adaptive`, `storage_args` | `Selector` | F05 |
| `raspador.adaptive.configure(path)` | define C1 | código do usuário | caminho | — | F05 |
| `raspador.browser.fetch(url, **kw)` | página renderizada avulsa (Playwright puro) | código do usuário | `wait_selector`, `network_idle`, `timeout`, `disable_resources`, `page_action`, `locale` | `Response` montado a partir do HTML final | F02 |
| `raspador.browser.BrowserSession` / `AsyncBrowserSession` | navegador vivo | código do usuário | as mesmas, mais `cdp_url`, `executable_path`, `record_requests` | `fetch()`, `save_state()`, `load_state()`, `network.search()` | F03, F04 |
| `raspador.Spider` | spider com padrões compliant e guarda por request | código do usuário | `start_urls`, `parse`, `crawldir` | `CrawlResult` (`items`, `stats`) | F06, F07, F08, F09 |
| `raspador.spiders.CrawlSpider`, `SitemapSpider`, `XMLFeedSpider`, `CSVFeedSpider`, `ContentSpider`, `ShopifySpider` | templates com os mesmos padrões | código do usuário | rules, sitemaps, feeds | `CrawlResult` | F06, F12 |
| atributo de classe `policy_override = "motivo"` | override auditado de delay e slots (nunca de robots) | código do usuário | motivo | validado em `__init_subclass__`, registrado em C6 | F06, F07 |
| CLI `raspador get/post/put/delete URL OUT` | extração sem código (formato pela extensão) | terminal | `-s`, `-H`, `--cookies`, `--timeout`, `--proxy`, `-p`, `-d`/`-j`, `--ai-targeted` | arquivo .md, .html ou .txt | F10 |
| CLI `raspador fetch URL OUT` | o mesmo, com navegador | terminal | os mesmos, mais `--wait-selector`, `--network-idle` | arquivo | F10 |
| CLI `raspador install` | **só** `playwright install chromium` | terminal | `--force` | — | — |
| CLI `raspador shell` (could) | IPython com atalhos | terminal | — | — | F13 |
| MCP `raspador mcp` (M4; stdio) | servidor para agentes | Claude Code, Claude Desktop | — | ferramentas abaixo | F11 |
| `raspador.integrations.scrapy.scrapling_response` (could) | reexport do decorador do upstream | projeto Scrapy | — | — | F14 |

**Ferramentas MCP do raspador.** Subconjunto, sem solver, sem CAPTCHA, sem ações "humanizadas":

| ferramenta | o que faz |
| --- | --- |
| `make_request` | request HTTP avulso |
| `open_request_session` / `session_make_request` | sessão HTTP |
| `browser_open` / `browser_fetch` / `close_session` / `list_sessions` | sessão de navegador |
| `browser_extract` | snapshot com referências, HTML, Markdown ou texto, sempre sanitizado |
| `browser_screenshot` (could) | captura de tela |
| `browser_network_requests` / `browser_network_request` | histórico de rede |
| `browser_save_state` / `browser_load_state` (could) | estado do navegador |
| `browser_actions` (M4) | click, fill, wait, sem modo slow |

Webhooks de entrada ou saída: não há. Jobs agendados: não há; agendar crawls é tarefa do cron ou do orquestrador do usuário.

Contagem: 15 entradas públicas de Python e CLI, e 14 ferramentas MCP.

## Partes que mordem

- **Breaking changes do upstream.** A v0.5 renomeou e removeu classes. Upgrade só com a suíte de contrato verde. `uv.lock` commitado. Ninguém de fora importa `scrapling` direto, só o `raspador`.
- **Atributos privados.** O engine usa `_client` e `_is_alive`. Um teste de contrato fixa a existência deles, para que o próximo upgrade quebre alto, não em silêncio.
- **Defaults hostis.** Qualquer caminho novo do upstream (uma classe nova, um parâmetro novo) nasce com disfarce ligado. O import guard e a validação por request são obrigatórios, não opcionais.
- **robots.txt.** Ver a regra 8 da política: o upstream consulta com `*` e trata 401/403 como permitido. O raspador corrige.
- **Idempotência no resume.** O checkpoint guarda requests pendentes e fingerprints vistos, não os itens já exportados. A entrega é pelo menos uma vez: itens podem duplicar em volta do ponto de pausa. Para dedup, oferecer `item_key` opcional no export.
- **Corrida no checkpoint.** A escrita é atômica no upstream (tmp + rename). Dois processos no mesmo `crawldir` corrompem o estado: lockfile no `crawldir`.
- **Rate limit.** `concurrent_requests_per_domain=0` no upstream quer dizer sem limite. O raspador fixa 1 (máximo 4).
- **Encoding.** O upstream corrigiu casos de charset; a suíte de contrato inclui páginas latin-1 e cp1252, comuns em sites brasileiros.
- **Tamanho de arquivo.** O upstream não tem `max_bytes`. O raspador limita o corpo (padrão de 20 MB) para não estourar a memória em crawl longo. É código novo.
- **Fuso horário.** Timestamps do log, das estatísticas e dos itens em UTC (ISO 8601 com `Z`).
- **LGPD.** O scraping de dado pessoal exige base legal e minimização. O raspador não decide isso por você; a doc avisa. O `ContentSpider` do upstream **não** filtra e-mail nem telefone. Um filtro opcional de PII no export é código novo (could).
- **Pickle (C2).** É risco de execução de código remoto se o `crawldir` vier de fora. Permissões verificadas antes de carregar.
- **Prompt injection (MCP).** Toda saída de `browser_extract` e `make_request` passa pelo sanitizador (hidden, aria-hidden, zero-width, comentários, template).
- **Peso.** O venv tem cerca de 330 MB, mais o Chromium. `patchright` e `browserforge` ficam instalados e inertes, um custo aceito para herdar o engine de spiders.
- **Navegador dentro do spider (spike).** Depende do contrato privado `_client`/`_is_alive`. Se o spike falhar, os spiders v1 ficam só com HTTP, e o navegador vive como superfície separada (S03/S04).

## Ordem de build

Revisada depois da revisão independente: os testes de contrato sobem para o M0, o navegador vai para o M3 como extra opcional e o MCP vai para o M4.

| marco | conteúdo | superfícies | contratos | entradas |
| --- | --- | --- | --- | --- |
| M0 esqueleto + contrato | `pyproject`, `uv.lock`, ruff, pyright, pytest; resolver o gate de porta local; **testes de contrato do upstream**: atributos privados (`_session_manager`, `_default_impersonate`, `_stealth`, `_default_headers`, `_is_alive`), allowlist contra `_merge_request_args`, herança de headers no `follow`, import guard | — | — | — |
| M1 fatia vertical | F01 + F06 só com HTTP; política 1-6 e 10; `__init_subclass__`; log C6 mínimo (JSONL, append); robots e allowed_domains com as correções 8 e 9; testes offline de `PolicyError`; teste de headers enviados | S01, S02, S05, S07, S09 | C5, C6 | `get…`, `http_session`, `Selector`, `Spider` |
| M2 musts restantes | adaptativo com caminho configurável (F05); pause/resume com 0700 e lockfile (F07); bloqueio por domínio (regra 7); `max_bytes`; `markdown()`; CLI get/post/put/delete e install (F10) | S06, S10, S11 | C1, C2 | `adaptive.configure`, CLI |
| M3 shoulds | extra `raspador[browser]`: fetch avulso, sessão, esperas e `save_state`/`load_state` (F02, F03); spike de navegador no spider (F09); CLI `fetch`; modo dev (F08); streaming; hooks; templates Crawl/Sitemap/Content (F12) | S03, S04, S08 | C3, C4 | `browser.fetch`, `BrowserSession`, templates |
| M4 coulds e adiados | MCP próprio (F11); `record_requests` (F04); shell (F13); integração Scrapy (F14); feeds XML/CSV; ShopifySpider; Shadow DOM; `cdp_url`; ad-block; HTTP/3; DoH; Docker; Agent Skill; filtro de PII | S12, S13, S14, S15, S16 | — | `raspador mcp`, `shell`, `integrations.scrapy` |
| M5 | correções do replica-entrepreneur, se rodar | — | — | — |

**Gate de teste.** O teste de headers enviados sobe um servidor local (pytest-httpserver). Este sandbox bloqueia porta local (EPERM), então resolver isso faz parte do M0. Há duas saídas:

- ligar `sandbox.network.allowLocalBinding: true`
- rodar a suíte fora do sandbox

Os testes de `PolicyError` e de contrato por `inspect` rodam offline. Nenhum teste acessa terceiros (httpbin foi só sondagem).

**Tamanho.** M0 a M2 (núcleo HTTP compliant): **S**, de 1 a 2 semanas. Cerca de metade do trabalho é código novo: allowlist, robots, redirects, bloqueio por domínio, `max_bytes`, permissões do checkpoint e C6. M3 com navegador: mais 1 a 2 semanas. M4 com MCP: **M**.
