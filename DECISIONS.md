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

## Pendente: publicação

Publicar é irreversível (um índice não aceita reenviar a mesma versão), então não foi executado:

1. No TestPyPI (conta do dono): Publishing → pending publisher com projeto `raspador-compliant`, owner
   `AlexandreCamerini`, repo `raspador`, workflow `publicar.yml`, environment `testpypi`.
2. No GitHub: criar o environment `testpypi` (Settings → Environments).
3. Push deste commit e `gh workflow run publicar.yml`.
4. Verificar: `uv venv /tmp/tp && uv pip install --python /tmp/tp --index-url https://test.pypi.org/simple/
   --extra-index-url https://pypi.org/simple/ raspador-compliant && /tmp/tp/bin/raspador --version`.
5. PyPI real: mesmo cadastro com environment `pypi`, depois `git tag v0.1.0 && git push origin v0.1.0`.
