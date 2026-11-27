"""0.1.1: CLI para quem não é desenvolvedor. `raspador ler URL`, saída opcional, ajuda com exemplos."""

import pytest
from click.testing import CliRunner

from raspador.cli import main

ROBOTS = "User-agent: *\nAllow: /\n\nUser-agent: raspador\nDisallow: /privado\n"
PAGINA = "<html><body><h1>Título</h1><p class='a'>um <a href='/x'>link</a></p><p class='a'>dois</p></body></html>"


@pytest.fixture
def run():
    def _run(*args):
        return CliRunner(env={"NO_COLOR": None, "FORCE_COLOR": None}).invoke(main, list(args))

    return _run


@pytest.fixture
def pagina(site):
    return site(
        {
            "https://ex.com/robots.txt": (200, ROBOTS, {}),
            "https://ex.com/p": (200, PAGINA, {}),
        }
    )


def test_ler_imprime_a_pagina_legivel_na_tela(run, pagina):
    r = run("ler", "https://ex.com/p")
    assert r.exit_code == 0, r.stderr
    assert "Título\n===" in r.stdout  # Markdown (título sublinhado): estrutura e links continuam legíveis
    assert "[link](https://ex.com/x)" in r.stdout
    assert "dois" in r.stdout
    assert r.stderr == ""


def test_ler_deixa_os_links_absolutos(run, site):
    html = (
        "<html><body><a href='/autor/x'>autor</a> <a href='pag/2'>rel</a> <a href='https://outro.com/y'>fora</a>"
        " <a href='mailto:a@b.com'>mail</a> <img src='/i.png' alt='img'></body></html>"
    )
    site({"https://ex.com/robots.txt": (404, "", {}), "https://ex.com/dir/p": (200, html, {})})
    r = run("ler", "https://ex.com/dir/p")
    assert r.exit_code == 0, r.stderr
    assert "[autor](https://ex.com/autor/x)" in r.stdout
    assert "[rel](https://ex.com/dir/pag/2)" in r.stdout
    assert "[fora](https://outro.com/y)" in r.stdout
    assert "[mail](mailto:a@b.com)" in r.stdout
    assert "![img](https://ex.com/i.png)" in r.stdout


def test_ler_com_o_grava_no_arquivo_e_avisa(run, pagina, tmp_path):
    out = tmp_path / "p.md"
    r = run("ler", "https://ex.com/p", "-o", str(out))
    assert r.exit_code == 0, r.stderr
    assert "Título" in out.read_text()
    assert r.stdout == ""
    assert r.stderr.startswith("ok  200  https://ex.com/p  -> ")


def test_ler_com_seletor_traz_so_o_trecho(run, pagina):
    r = run("ler", "https://ex.com/p", "-s", "h1")
    assert r.exit_code == 0, r.stderr
    assert "Título" in r.stdout and "dois" not in r.stdout


def test_ler_respeita_o_robots(run, pagina):
    r = run("ler", "https://ex.com/privado/a")
    assert r.exit_code == 6
    assert "RSP-R001" in r.stderr
    assert r.stdout == ""


def test_ler_com_js_usa_o_navegador(run, monkeypatch):
    from raspador import browser

    chamadas = []

    def falso(url, contact=None, **kw):
        chamadas.append(url)
        return browser.build_response(url, "<h1>renderizado</h1>", 200, "OK", {}, {}, None)

    monkeypatch.setattr(browser, "fetch", falso)
    r = run("ler", "https://ex.com/app", "--js")
    assert r.exit_code == 0, r.stderr
    assert chamadas == ["https://ex.com/app"]
    assert "renderizado" in r.stdout


def test_get_sem_output_vai_para_a_tela(run, pagina):
    r = run("get", "https://ex.com/p", "-s", "p.a")
    assert r.exit_code == 0, r.stderr
    assert "um" in r.stdout and "dois" in r.stdout


def test_sem_argumentos_mostra_exemplos_e_sai_0(run):
    r = run()
    assert r.exit_code == 0
    assert "raspador ler https://" in r.stdout


def test_ajuda_principal_mostra_o_essencial_e_esconde_verbos_http(run):
    r = run("--help")
    comandos = r.stdout.split("Commands:")[1]
    assert "ler" in comandos and "fetch" in comandos and "mcp" in comandos
    for verbo in ("post", "put", "delete"):
        assert f"  {verbo} " not in comandos
