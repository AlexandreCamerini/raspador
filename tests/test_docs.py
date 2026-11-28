"""Docs públicas (guia e SECURITY) não podem mentir: exemplos compilam, códigos existem, links internos resolvem."""

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
DOCS = [RAIZ / "README.md", RAIZ / "docs" / "GUIA.md", RAIZ / "SECURITY.md"]
CREDITO = "semente.dev"


def _codigos_no_codigo() -> set[str]:
    achados: set[str] = set()
    for arquivo in (RAIZ / "src" / "raspador").rglob("*.py"):
        achados |= set(re.findall(r"RSP-[A-Z]\d{3}", arquivo.read_text()))
    return achados


def _slug(titulo: str) -> str:
    """Âncora no estilo do GitHub: minúsculas, sem pontuação (mantém letras acentuadas), espaço vira hífen."""
    s = titulo.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def _ancoras(md: Path) -> set[str]:
    return {_slug(h) for h in re.findall(r"^#{1,6} (.+)$", md.read_text(), re.M)}


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_doc_existe_e_credita_a_semente(doc):
    assert doc.exists(), f"{doc} não existe"
    assert CREDITO in doc.read_text()


@pytest.mark.parametrize("doc", DOCS[1:], ids=lambda p: p.name)
def test_exemplos_python_compilam(doc):
    for bloco in re.findall(r"```python\n(.*?)```", doc.read_text(), re.S):
        compile(bloco, doc.name, "exec")


@pytest.mark.parametrize("doc", DOCS[1:], ids=lambda p: p.name)
def test_codigos_citados_existem(doc):
    citados = {c for c in re.findall(r"RSP-[A-Z]\d{3}", doc.read_text()) if not c.startswith("RSP-H")}
    assert citados - _codigos_no_codigo() == set()


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_links_internos_resolvem(doc):
    quebrados = []
    for alvo in re.findall(r"\]\(([^)\s]+)\)", doc.read_text()):
        if re.match(r"[a-z]+:", alvo):
            continue
        caminho, _, ancora = alvo.partition("#")
        destino = (doc.parent / caminho).resolve() if caminho else doc
        ancora_quebrada = bool(ancora) and destino.suffix == ".md" and ancora not in _ancoras(destino)
        if not destino.exists() or ancora_quebrada:
            quebrados.append(alvo)
    assert quebrados == []
