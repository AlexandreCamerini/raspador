"""O README não pode mentir: exemplos compilam, o do ProxyPool roda, os códigos de erro batem com o código."""

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
README = (RAIZ / "README.md").read_text()
BLOCOS = re.findall(r"```python\n(.*?)```", README, re.S)


def _codigos_no_codigo() -> set[str]:
    achados: set[str] = set()
    for arquivo in (RAIZ / "src" / "raspador").rglob("*.py"):
        achados |= set(re.findall(r"RSP-[A-Z]\d{3}", arquivo.read_text()))
    return achados


def _codigos_no_readme() -> set[str]:
    achados = set(re.findall(r"RSP-[A-Z]\d{3}", README))
    # faixas "RSP-U001 / U002 / U003" e "RSP-F001 … F004"
    for prefixo, ini, fim in re.findall(r"RSP-([A-Z])(\d{3}) … [A-Z](\d{3})", README):
        achados |= {f"RSP-{prefixo}{n:03d}" for n in range(int(ini), int(fim) + 1)}
    for _prefixo, resto in re.findall(r"RSP-([A-Z])\d{3}((?: / [A-Z]\d{3})+)", README):
        achados |= {f"RSP-{c}" for c in re.findall(r"[A-Z]\d{3}", resto)}
    return achados


def test_ha_exemplos_python():
    assert len(BLOCOS) >= 4


@pytest.mark.parametrize("bloco", BLOCOS, ids=[f"bloco{i}" for i in range(len(BLOCOS))])
def test_exemplo_compila(bloco):
    compile(bloco, "README.md", "exec")


def test_exemplo_do_proxy_pool_roda_offline():
    bloco = next(b for b in BLOCOS if "ProxyPool(" in b)
    ns: dict = {}
    exec(bloco, ns)
    pool = ns["pool"]
    assert pool.entry_for("https://www.loja.com.br/x").label == "br1"
    assert pool.entry_for("https://outra.com/").group == "eua"
    assert "senha" not in repr(pool)


def test_exemplo_do_spider_define_a_classe_sem_rede():
    bloco = next(b for b in BLOCOS if "class Noticias" in b)
    ns: dict = {}
    exec(bloco.split("\nresultado =", 1)[0], ns)
    assert ns["Noticias"].download_delay >= 0.5


def test_todo_codigo_do_readme_existe_e_todo_codigo_esta_no_readme():
    no_codigo = _codigos_no_codigo()
    no_readme = {c for c in _codigos_no_readme() if not c.startswith("RSP-H")}  # RSP-H<status> é montado no código
    assert no_readme - no_codigo == set(), "o README cita códigos que não existem"
    assert no_codigo - no_readme == set(), "códigos sem linha no README"


def test_comandos_da_cli_citados_existem():
    from raspador.cli import main

    citados = set(re.findall(r"^raspador (\w+)", README, re.M))
    assert citados <= set(main.commands), citados - set(main.commands)


def test_ferramentas_mcp_citadas_sao_as_do_servidor():
    from raspador.mcp_server import TOOL_NAMES

    trecho = README.split("O servidor oferece estas ferramentas", 1)[1].split(".", 1)[0]  # só a frase da lista
    assert set(re.findall(r"`(\w+)`", trecho)) == set(TOOL_NAMES)
