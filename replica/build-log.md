# Build log: raspador

Uma linha por marco/superfície. "Mais difícil que o esperado" fica explícito.

| ID | data | status | o que falta | mais difícil que o esperado |
| --- | --- | --- | --- | --- |
| M0 | 2026-11-26 | done | gate não registrado (sandbox bloqueia `~/.local/state/raiz`); git não iniciado | `uv` precisou de cache no scratchpad; pyright precisou de `venvPath` |
| S05 | 2026-11-26 | partial | só `response.css` exercitado; `Selector`, XPath, find, regex e navegação não reexportados nem testados (M1 restante) | — |
| S01 | 2026-11-26 | partial | robots.txt no request avulso; F01 provado offline, teste no fio pulado (porta local bloqueada) | `FetcherSession.__enter__` devolve o cliente interno: kwargs por request escapariam; virou wrapper guardado |
| S02 | 2026-11-26 | done | — | — |
| S07 | 2026-11-26 | partial | Retry-After próprio; teste de pause/resume (M2) | robots, allowed_domains e redirects precisaram de código novo; o robots só é trocável dentro de `SessionManager.start()`, por atributo privado do engine |
| S09 | 2026-11-26 | partial | `to_json` testado; JSONL/CSV/XML e stats sem teste próprio | — |

## Notas

- O `Response.follow()` do upstream injeta `extra_headers` (Referer) e `google_search=False`. A allowlist precisou aceitar os valores neutros e validar `extra_headers` como header. Achado no TDD, não previsto na arquitetura.
- O teste de spider troca só `_ASyncSessionLogic._make_request` e chama o `_merge_request_args` real. Os headers verificados são os que o curl_cffi receberia.
- Mudanças de upstream detectáveis: `tests/test_contract_upstream.py` (10 testes). Rodar antes de qualquer upgrade da versão fixada.
- Revisão do advisor antes de fechar encontrou 3 bugs que a suíte não via (asserções frouxas), todos corrigidos com teste vermelho antes:
  robots.txt buscado 2x por domínio; `proxy` por request reabria a rotação após bloqueio (agora RSP-P006 no spider);
  URL fora de `allowed_domains` disparava busca de robots e era auditada como `robots_denied`.
- Limite conhecido: uma start URL fora do escopo ainda conta em `CrawlStats.failed_requests_count` (o engine do upstream conta a exceção). O log de auditoria é a fonte de verdade.

## M2 (2026-11-26)

| ID | data | status | o que falta | mais difícil que o esperado |
| --- | --- | --- | --- | --- |
| S01 | 2026-11-26 | done | — | redirects avulsos seguidos à mão para checar robots em cada salto; isso tirou a proteção SSRF do `follow_redirects="safe"` do upstream, reimplementada (IP literal e DNS) também no spider, que já tinha o mesmo furo desde o M1 |
| S05 | 2026-11-26 | done | — | o site falso montava o Response sem o charset do header; o teste de latin-1 só ficou válido depois de usar a mesma extração de encoding do upstream |
| S06 | 2026-11-26 | done | backend plugável não exposto | `storage_args` explícito faz o upstream perder a URL e todos os domínios colidem; virou classe de storage própria |
| S07 | 2026-11-26 | done | Retry-After próprio; progresso e resumo da CLI de crawl (M3) | — |
| S10 | 2026-11-26 | done | — | — |
| S11 | 2026-11-26 | done | `extract fetch` (navegador) é M3 | o logger do upstream vazava `INFO: Fetched` no stderr; `--report json` com `-` misturava dado e relatório (os dois achados no teste ao vivo, não na suíte) |

Notas do M2:
- Teste ao vivo (2026-11-26) contra quotes.toscrape.com, site feito para treino de raspagem: CLI `get` para .md e para `-`, e um spider de 2 páginas (20 itens, robots.txt consultado, crawldir 0700, checkpoint limpo). 8,3 s para 2 páginas: o AutoThrottle começa em 5 s por domínio. É o ritmo conservador previsto, não um defeito.
- `max_bytes` checa depois do download: limita o que segue no pipeline, não o pico de memória. Limite real exigiria streaming no curl_cffi.
- O DNS da checagem SSRF é resolvido antes do request; entre a checagem e a conexão o nome pode mudar (DNS rebinding). Mesma limitação do modo "safe" do upstream.
- Revisão do advisor no fechamento do M2 achou mais 2 furos do caminho manual de redirect/robots, invisíveis ao site falso; corrigidos com teste vermelho antes:
  a busca do robots.txt avulso ignorava `verify`, `proxy`, `cert` e `timeout` da requisição (com `--no-verify` todo site virava "robots negou"; com `--proxy` o robots saía pelo IP real);
  redirect para outro host reenviava `Authorization` e cookies (o libcurl não faz isso). Agora retira as credenciais por salto e, se a credencial é da sessão, não segue e devolve o 3xx.
- Também: falha ao buscar robots expira em 5 min, não em 24 h; SSRF bloqueia tudo que não é `is_global` (CGNAT 100.64/10, metadados 169.254.169.254, IPv4 mapeado em IPv6); a CLI só trata erro de rede como rede, e bug do raspador sai com 1.
- Conferido e descartado: a limpeza do checkpoint do upstream apaga só o arquivo de checkpoint, não o log de auditoria (teste de pause/resume agora prova as duas execuções no log). O `max_body_bytes` do upstream existe só na gravação de rede do navegador, não no HTTP.

## M3 (2026-11-26)

| ID | data | status | o que falta | mais difícil que o esperado |
| --- | --- | --- | --- | --- |
| S03 | 2026-11-26 | done | — | o sandbox do agente bloqueia as portas Mach do Chromium no macOS; não há como ver o navegador rodar daqui |
| S04 | 2026-11-26 | done | `record_requests` e `cdp_url` são M4 | ordem das rotas do Playwright: a última registrada roda primeiro e `continue_()` pula as outras. A guarda (SSRF e recursos) é registrada depois do `page_setup` e usa `fallback()` |
| S08 | 2026-11-26 | done | XMLFeed/CSVFeed/Shopify são M4 | — |
| S11 | 2026-11-26 | done | — | `raspador fetch` reaproveita o pipeline de erros e saída do `get` |

Notas do M3:
- O Playwright foi fixado em `>=1.64,<1.65` no extra `browser`: o 1.65 resolvido antes pedia o Chromium 1255, e o instalado era o 1248, a mesma revisão do patchright que o `scrapling[fetchers]` já instala. Um só Chromium no disco e nenhum download. Teste de contrato fixa as duas revisões iguais.
- O navegador do raspador não esconde que é automatizado: UA `raspador/...`, `navigator.webdriver = true` e os client hints do próprio Chromium. Opções de patch (`init_script`, `extra_flags`, `additional_args`, `useragent`) são recusadas com RSP-P002.
- No spider, o robots.txt de um sid de navegador vai por uma sessão HTTP identificada, sem abrir aba.
- A guarda de rota bloqueia só IP interno literal e `localhost` (não resolve DNS para cada recurso da página, por custo). Um nome que resolve para IP interno passa, como num navegador comum.
- Revisão do advisor no fechamento do M3, achados corrigidos com teste vermelho antes:
  `response.follow()` num spider de navegador gravava `headers` (Referer) e era recusado com RSP-P001, então o F09 só funcionava para `start_urls`. Agora `headers` é aceito no navegador, validado e vira `extra_headers`;
  o robots.txt de sid de navegador saía sem o proxy da sessão (pelo IP real); agora usa o mesmo proxy e contato;
  credenciais em `headers`/`extra_headers` de navegador são recusadas (o header vai para todo recurso da página, inclusive terceiros); login é por `storage_state`;
  erros do Playwright na CLI (timeout, rede) viram RSP-B002 com saída 5, não traceback com saída 1.
- Os 5 testes com Chromium real ainda não rodaram em lugar nenhum: rodam pela primeira vez no gate, fora do sandbox. As linhas de navegador do features.csv ficam `partial` até lá.
- 2026-11-26: os 5 testes com Chromium real e o teste de headers no fio passaram fora do sandbox (`29 passed`, 0 skipped em test_browser.py + test_http.py). S03 e S04 passam a done; o follow() no spider de navegador está provado com Chromium.
