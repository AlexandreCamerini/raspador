"""F05: seletor que sobrevive a redesign, gravado no storage do raspador e isolado por domínio."""

import os
from pathlib import Path

import scrapling

import raspador
from raspador import adaptive

V1 = """<html><body><div class="produto"><h1>Café</h1>
<span id="preco" class="valor destaque">R$ 32,90</span></div></body></html>"""

V2 = """<html><body><main><section class="item-card"><h2>Café</h2>
<div class="info"><p class="valor destaque novo" data-k="p">R$ 34,50</p></div></section></main></body></html>"""


def test_seletor_adaptativo_reencontra_elemento_apos_redesign():
    antes = raspador.Selector(V1, url="https://loja.exemplo.com/cafe", adaptive=True)
    assert antes.css("#preco", auto_save=True)[0].text == "R$ 32,90"

    depois = raspador.Selector(V2, url="https://loja.exemplo.com/cafe", adaptive=True)
    assert depois.css("#preco") == []  # o seletor original quebrou
    achado = depois.css("#preco", adaptive=True)
    assert achado and achado[0].text == "R$ 34,50"


def test_storage_fica_no_raspador_home_e_nao_no_site_packages():
    raspador.Selector(V1, url="https://loja.exemplo.com/cafe", adaptive=True).css("#preco", auto_save=True)
    assert adaptive.path() == Path(os.environ["RASPADOR_HOME"]) / "adaptive.db"
    assert adaptive.path().exists()
    assert Path(scrapling.__file__).parent not in adaptive.path().parents


def test_dados_de_um_dominio_nao_vazam_para_outro():
    raspador.Selector(V1, url="https://loja.exemplo.com/cafe", adaptive=True).css("#preco", auto_save=True)
    outro = raspador.Selector(V2, url="https://outra.exemplo.org/cafe", adaptive=True)
    assert outro.css("#preco", adaptive=True) == []


def test_configure_muda_o_arquivo(tmp_path):
    destino = adaptive.configure(tmp_path / "proj" / "adaptive.db")
    raspador.Selector(V1, url="https://loja.exemplo.com/cafe", adaptive=True).css("#preco", auto_save=True)
    assert destino.exists()


def test_adaptativo_por_resposta_http(site):
    site(
        {
            "https://loja.exemplo.com/robots.txt": (404, "", {}),
            "https://loja.exemplo.com/cafe": (200, V1, {}),
        }
    )
    with raspador.http_session(selector_config=adaptive.selector_config()) as s:
        page = s.get("https://loja.exemplo.com/cafe")
        page.css("#preco", auto_save=True)
    depois = raspador.Selector(V2, url="https://loja.exemplo.com/cafe", adaptive=True)
    assert depois.css("#preco", adaptive=True)[0].text == "R$ 34,50"
