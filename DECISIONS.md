# Decisões

## 2026-11-27: nome de distribuição `raspador-compliant`

- Contexto: `raspador` no PyPI pertence a outro projeto (fgmacedo/raspador, "extract data from semi-structured
  text documents", última versão 0.2.2 em 2013-10-30). No TestPyPI o nome está livre, mas publicar lá com um nome
  que não dá para usar no PyPI não testa nada de útil.
- Decisão: distribuição `raspador-compliant` (`pip install raspador-compliant`). Import, CLI (`raspador`) e
  repositório não mudam.
- Motivo: livre no PyPI e no TestPyPI; diz o diferencial no nome. Reversível até o primeiro upload ao PyPI real.
- Alternativas descartadas: `raspador-br` (sugere escopo só brasileiro); reivindicar `raspador` pela PEP 541
  (semanas ou meses, pode ser negado, publicação parada até lá).
- Risco conhecido: o pacote antigo também instala o módulo `raspador`. Quem tiver os dois no mesmo ambiente terá
  conflito de import. Improvável (o antigo está parado há 13 anos), mas fica aqui.
- Decisão tomada sem pergunta (sessão autônoma). Revisar antes do upload ao PyPI.

## 2026-11-27: TestPyPI publicado

- `raspador-compliant` 0.1.0 publicado no TestPyPI pela run 46026659979 (Trusted Publishing, sem token).
- A primeira tentativa falhou com `invalid-publisher` porque não havia pending publisher na conta do TestPyPI.
  O publisher foi cadastrado em 2026-11-27 (projeto `raspador-compliant`, `AlexandreCamerini/raspador`,
  `publicar.yml`, environment `testpypi`) e a run seguinte passou. O environment do GitHub foi criado sozinho.
- Verificado num venv limpo com
  `uv pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/
  --index-strategy unsafe-best-match raspador-compliant==0.1.0`: `raspador --version` retorna 0.1.0 e
  `import raspador` resolve para o site-packages do venv.
- `unsafe-best-match` só se usa neste teste. O TestPyPI aceita upload de qualquer pessoa, então uma dependência
  pode vir de lá. Isso não acontece com quem instala pelo PyPI real.

## 2026-11-27: PyPI publicado

- `raspador-compliant` 0.1.0 publicado em https://pypi.org/project/raspador-compliant/ pela run 46049021655,
  disparada pela tag `v0.1.0`.
- As duas primeiras tentativas falharam com `invalid-publisher`: a conta do pypi.org não tinha pending publisher.
  Ele foi cadastrado com environment `pypi` e o job passou na mesma tag.
- Verificado num venv limpo, só com o índice padrão: `uv pip install raspador-compliant==0.1.0`,
  `raspador --version` retorna 0.1.0.
- Próxima versão: subir `version` no pyproject e em `__init__.py`, depois criar a tag `vX.Y.Z`. O publisher do
  PyPI já está ativo, então não precisa cadastrar de novo.

## 2026-11-27: 0.1.1 publicada (CLI amigável)

- Contexto: na 0.1.0 a CLI copiava a interface do Scrapling. `get` exigia o argumento OUTPUT, e quem não é
  desenvolvedor não conseguia usar.
- Mudanças:
  - novo comando `raspador ler URL`, que mostra a página em Markdown na tela, com `-o`, `-s` e `--js`;
  - OUTPUT opcional em `get` e `fetch`;
  - `raspador` sem argumentos mostra exemplos;
  - `post`, `put` e `delete` continuam funcionando, mas não aparecem mais na ajuda.
- Links e imagens relativos no Markdown passam a sair absolutos, resolvidos contra a URL da página. A correção
  fica em `render()` (`_render.py`) e por isso vale para a CLI e para o MCP. `mailto:` e URLs que já são
  absolutas passam sem mudança. A correção foi feita depois que um teste manual da 0.1.1 ainda sem publicar
  mostrou links como `(about)`, que não funcionam fora do site.
- Publicada pela run 46078289400, disparada pela tag `v0.1.1` (commit 72f6404), que passou na primeira tentativa.
  Gate antes da tag: ruff limpo, pyright sem erros, pytest com 355 passed e 14 skipped.
- Verificação depois da publicação, instalando do PyPI com `uv tool install --force "raspador-compliant[mcp]==0.1.1"`:
  - `raspador --version` mostra 0.1.1;
  - `ler` em quotes.toscrape.com devolve links absolutos;
  - `httpbin.org/deny` é recusado com RSP-R001 e exit 6.
- Teste do MCP:
  - Por um cliente stdio: as 9 tools aparecem, `make_request` traz as 10 citações de quotes.toscrape.com e
    `httpbin.org/deny` é recusado com RSP-R001.
  - Pelo Claude Code em modo headless (Haiku), com um pedido em linguagem natural: as 10 citações saíram com os
    autores corretos.
- Problema que pode voltar: depois de instalar uma versão nova, o zsh pode continuar chamando o binário antigo
  em `~/.local/bin` porque guarda o caminho em cache. `hash -r` resolve.
