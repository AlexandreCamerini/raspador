"""Comportamentos herdados do upstream que o raspador expõe: parsing, encoding, dedup e estatísticas."""

import raspador
from raspador.spiders import Spider

HTML = """<html><body><ul id="l">
<li class="p" data-id="1"><a href="/a">Café</a><span>R$ 10,00</span></li>
<li class="p" data-id="2"><a href="/b">Chá</a><span>R$ 7,50</span></li>
</ul></body></html>"""


def test_xpath_find_regex_e_navegacao():
    page = raspador.Selector(HTML, url="https://ex.com/")
    assert page.xpath("//li/a/text()").getall() == ["Café", "Chá"]
    itens = page.find_all("li", {"class": "p"})
    assert [i.attrib["data-id"] for i in itens] == ["1", "2"]
    assert page.find_by_text("Chá").tag == "a"
    assert page.css("span::text").re(r"R\$ (\d+,\d+)") == ["10,00", "7,50"]
    primeiro = itens[0]
    assert primeiro.parent.attrib["id"] == "l"
    assert primeiro.next.attrib["data-id"] == "2"
    assert [c.tag for c in primeiro.children] == ["a", "span"]


def test_encoding_latin1_declarado_no_header(site):
    corpo = "<html><body><h1>Promoção de pão</h1></body></html>".encode("latin-1")
    site(
        {
            "https://ex.com/robots.txt": (404, "", {}),
            "https://ex.com/p": (200, corpo, {"content-type": "text/html; charset=ISO-8859-1"}),
        }
    )
    page = raspador.get("https://ex.com/p")
    assert page.css("h1::text").get() == "Promoção de pão"


def test_dedup_por_fingerprint_e_estatisticas(site, tmp_path):
    fake = site(
        {
            "https://ex.com/robots.txt": (200, "User-agent: *\nAllow: /", {}),
            "https://ex.com/": (200, '<a href="/x">x</a><a href="/x">de novo</a><a href="/y">y</a>', {}),
            "https://ex.com/x": (200, "<h1>x</h1>", {}),
            "https://ex.com/y": (404, "", {}),
        }
    )

    class S(Spider):
        name = "dedup"
        start_urls = ["https://ex.com/"]
        download_delay = 0.0
        autothrottle_enabled = False
        policy_override = "teste automatizado em memória"
        audit_path = tmp_path / "a.jsonl"

        async def parse(self, response):
            for href in response.css("a::attr(href)").getall():
                yield response.follow(href)
            yield {"url": response.url}

    r = S().start()
    assert fake.urls().count("https://ex.com/x") == 1
    assert r.stats.response_status_count == {"status_200": 2, "status_404": 1}
    assert r.stats.requests_count == 3
    assert r.stats.domains_response_bytes["ex.com"] > 0
