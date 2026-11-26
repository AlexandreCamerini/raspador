"""M4: feeds XML/CSV, ShopifySpider e integração com Scrapy, todos com a política do raspador."""

import pytest

from raspador.policy import PolicyError
from raspador.spiders import CSVFeedSpider, ShopifySpider, XMLFeedSpider

TESTE = {"download_delay": 0.0, "autothrottle_enabled": False, "policy_override": "teste automatizado em memória"}
ROBOTS_OK = (200, "User-agent: *\nAllow: /", {})


def test_templates_novos_herdam_robots_obrigatorio():
    for base in (XMLFeedSpider, CSVFeedSpider, ShopifySpider):
        with pytest.raises(PolicyError):
            type("S", (base,), {"name": "x", "robots_txt_obey": False})


def test_xml_feed_itera_por_tag(site, tmp_path):
    rss = """<?xml version="1.0"?><rss><channel><item><title>Um</title></item>
    <item><title>Dois</title></item></channel></rss>"""
    site(
        {
            "https://ex.com/robots.txt": ROBOTS_OK,
            "https://ex.com/feed.xml": (200, rss, {"content-type": "application/rss+xml"}),
        }
    )

    class Feed(XMLFeedSpider):
        name = "feed"
        start_urls = ["https://ex.com/feed.xml"]
        itertag = "item"
        audit_path = tmp_path / "a.jsonl"
        vars().update(TESTE)

        async def parse_node(self, response, node):
            yield {"t": node.findtext("title")}  # node é um elemento lxml, não um Selector

    assert [i["t"] for i in Feed().start().items] == ["Um", "Dois"]


def test_csv_feed_itera_por_linha(site, tmp_path):
    site(
        {
            "https://ex.com/robots.txt": ROBOTS_OK,
            "https://ex.com/precos.csv": (200, "produto,preco\ncafé,32.90\nchá,7.50\n", {"content-type": "text/csv"}),
        }
    )

    class Precos(CSVFeedSpider):
        name = "precos"
        start_urls = ["https://ex.com/precos.csv"]
        audit_path = tmp_path / "a.jsonl"
        vars().update(TESTE)

        async def parse_row(self, response, row):
            yield {"produto": row["produto"], "preco": float(row["preco"])}

    assert Precos().start().items == [{"produto": "café", "preco": 32.9}, {"produto": "chá", "preco": 7.5}]


def test_shopify_respeita_robots_da_loja(site, tmp_path):
    fake = site({"https://loja.ex.com/robots.txt": (200, "User-agent: *\nDisallow: /collections", {})})

    class Loja(ShopifySpider):
        name = "loja"
        target_website = "loja.ex.com"
        audit_path = tmp_path / "a.jsonl"
        vars().update(TESTE)

    assert Loja().start().items == []
    assert not any("/collections" in u for u in fake.urls())


class _HeadersFalsos(dict):
    def getlist(self, nome):
        return [b"s=1; Path=/"] if nome == b"Set-Cookie" else []

    def to_unicode_dict(self):
        return {"content-type": "text/html"}


class _RespostaScrapyFalsa:
    url = "https://loja.exemplo.com/cafe"
    body = b'<span id="preco">R$ 32,90</span>'
    status = 200
    encoding = "utf-8"
    request = None
    headers = _HeadersFalsos()


def test_integracao_scrapy_converte_e_usa_storage_do_raspador():
    pytest.importorskip("scrapy", reason="a integração do upstream exige Scrapy instalado (extra pesado, could)")
    from raspador.adaptive import RaspadorStorage
    from raspador.integrations.scrapy import convert_response, scrapling_response

    r = convert_response(_RespostaScrapyFalsa(), adaptive=True)
    assert r.css("#preco::text").get() == "R$ 32,90"
    assert isinstance(r._storage, RaspadorStorage.__wrapped__)

    class Spider:
        @scrapling_response
        def parse(self, response):
            yield {"preco": response.css("#preco::text").get()}

    assert list(Spider().parse(_RespostaScrapyFalsa())) == [{"preco": "R$ 32,90"}]
