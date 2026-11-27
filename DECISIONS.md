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

## Pendente: PyPI real (irreversível)

1. Em pypi.org (a conta é separada da do TestPyPI): pending publisher com os mesmos campos e environment `pypi`.
2. `git tag v0.1.0 && git push origin v0.1.0`. O job confere se a tag bate com a versão do pyproject.
