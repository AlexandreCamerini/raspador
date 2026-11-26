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
Status: fixed (árvore de trabalho, commit pendente): `http.check_url` (só http/https com host) na primeira URL e em cada salto de redirect, no avulso, sessões, spider (o robots não busca nada para URL inválida; o manager audita uma linha policy_error RSP-U001 com a URL certa, sem robots_denied — achado na revisão: a primeira versão auditava `file:///robots.txt` e contava a start URL como robots negado, e cada link mailto:/tel:/javascript: inflava `robots_disallowed_count`), navegador (antes de abrir e na URL final), CLI (saída 2) e MCP. Confirmado com curl real: `raspador get file://.../segredo.txt -` sai com RSP-U001 e código 2

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
Status: fixed (árvore de trabalho, commit pendente): `_render.check_selector` valida antes de buscar; CLI sai com 2 e RSP-U002, MCP devolve erro de ferramenta RSP-U002

### BUG-003: `headers` como texto dá `AttributeError` interno

- Severity: S4 (mensagem ruim; o uso é errado de qualquer forma)
- Flow / case: F01-N3

Passos: `raspador.get("https://ex.com/p", headers="User-Agent: x")`
Expected: `TypeError` dizendo que `headers` precisa ser um dict.
Actual: `AttributeError: 'str' object has no attribute 'items'` de dentro de `policy.check_headers`.
Evidence: test_f01_n3_headers_como_texto_da_erro_claro.
Status: fixed (árvore de trabalho, commit pendente): `policy.check_headers` levanta TypeError dizendo que headers precisa ser dict

### BUG-004: `storage_state` inexistente é aceito na construção da sessão de navegador

- Severity: S3 (falha tardia, longe da causa)
- Flow / case: F03-N1

Passos: `browser.BrowserSession(storage_state="/nao/existe.json")`
Expected: erro imediato RSP-F004 com o caminho.
Actual: o objeto é criado sem reclamar; a falha só viria ao abrir o contexto do Chromium.
Evidence: test_f03_n1_estado_inexistente_falha_na_construcao.
Status: fixed (árvore de trabalho, commit pendente): `StateFileMissing` (RSP-F004) na construção e em `load_state`

### BUG-005: filtro inválido nas ferramentas de rede do MCP vira "unexpected exception"

- Severity: S3 (quebrado, com contorno: corrigir o filtro)
- Flow / case: F04-N1
- Superfície: S13

Passos: `browser_open(record_requests=true)`, depois `browser_network_requests(url_pattern="[")` ou `(limit=0)`.
Expected: erro de ferramenta com código.
Actual: o `ValueError` do `NetworkRecorder.search` do upstream escapa da tradução de erros; o servidor loga
"raised an unexpected exception" e o modelo recebe só "Error executing tool browser_network_requests".
Evidence: tests/e2e/test_aceite.py::test_f04_n1_mcp_filtro_de_rede_invalido_e_erro_de_ferramenta (2 variantes).
Status: fixed (árvore de trabalho, commit pendente): `ValueError` vira ToolError RSP-M005 com o motivo

## A conferir (não reproduzido)

- C1: (resolvido pelo BUG-004) o erro de launch com `storage_state` inexistente não acontece mais: o caminho é checado antes.
- C2: `timeout` negativo ou zero é repassado ao curl sem validação. Comportamento do curl não verificado.
- C3: M3 do plano: `raspador mcp` configurado num Claude Code real ainda não foi testado à mão.

## Resumo da rodada (2026-11-26)

Casos no plano: 42 de fluxo + 3 manuais. Dos 42: 40 rodados e passando, 1 n/a (F13, shell não construído), 1 skip (F14, sem Scrapy). Manuais: 2 pass, 1 pendente (C3). Bugs: S1 1, S2 0, S3 3, S4 1;
todos corrigidos com o teste vermelho antes. Nenhum S1 aberto.
