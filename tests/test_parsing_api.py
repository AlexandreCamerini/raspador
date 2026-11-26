"""Parsing herdado do upstream, exposto pelo raspador.Selector: o contrato que a matriz de paridade conta."""

from raspador import Selector

HTML = (
    '<ul class="lista">'
    '<li class="item"><a href="/a">Um</a><span class="preco">R$ 10</span></li>'
    '<li class="item"><a href="/b">Dois</a><span class="preco">R$ 20</span></li>'
    '<li class="item"><a href="/c">Três</a><span class="preco">R$ 30</span></li>'
    "</ul>"
    '<p id="j" data-v="7">  {"k": 1}  </p>'
)


def _page():
    return Selector(HTML, url="https://ex.com/")


def test_find_similar_acha_os_irmaos_de_mesma_estrutura():
    primeiro = _page().css("li.item")[0]
    textos = [e.css("a::text").get() for e in primeiro.find_similar()]
    assert textos == ["Dois", "Três"]


def test_seletor_gerado_reencontra_o_mesmo_elemento():
    page = _page()
    alvo = page.css("li.item")[1]
    assert page.css(alvo.generate_css_selector)[0].css("a::text").get() == "Dois"
    assert page.xpath(alvo.generate_xpath_selector)[0].css("a::text").get() == "Dois"


def test_text_handler_limpa_extrai_regex_e_json():
    p = _page().css("#j")[0]
    assert p.text.clean() == '{"k": 1}'
    assert p.text.clean().json() == {"k": 1}
    assert _page().css(".preco::text").re(r"\d+") == ["10", "20", "30"]


def test_attributes_handler_le_atributos():
    attrib = _page().css("#j")[0].attrib
    assert attrib["data-v"] == "7"
    assert [dict(m) for m in attrib.search_values("7")] == [{"data-v": "7"}]
