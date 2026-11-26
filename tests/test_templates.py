"""Templates do upstream (Crawl, Sitemap, Content) com os padrões e a guarda do raspador; modo dev,
streaming e hooks."""

import anyio
import pytest

from raspador.policy import PolicyError
from raspador.spiders import ContentSpider, CrawlRule, CrawlSpider, LinkExtractor, SitemapSpider, Spider

ROBOTS = (200, "User-agent: *\nAllow: /\n\nUser-agent: raspador\nDisallow: /privado\n", {})
TESTE = {"download_delay": 0.0, "autothrottle_enabled": False, "policy_override": "teste automatizado em memória"}


def _site_blog(site):
    return site(
        {
            "https://blog.ex.com/robots.txt": ROBOTS,
            "https://blog.ex.com/": (
                200,
                '<a href="/post/1">1</a><a href="/privado/x">p</a><a href="https://fora.com/z">f</a>',
                {},
            ),
            "https://blog.ex.com/post/1": (200, "<html><body><h1>Primeiro post</h1><p>Texto.</p></body></html>", {}),
            "https://blog.ex.com/privado/x": (200, "<h1>segredo</h1>", {}),
        }
    )


def test_templates_herdam_robots_obrigatorio():
    for base in (CrawlSpider, SitemapSpider, ContentSpider):
        with pytest.raises(PolicyError):
            type("S", (base,), {"name": "x", "robots_txt_obey": False})


def test_crawl_spider_segue_regras_respeitando_robots_e_dominio(site, tmp_path):
    fake = _site_blog(site)

    class Blog(CrawlSpider):
        name = "blog"
        start_urls = ["https://blog.ex.com/"]
        allowed_domains = {"blog.ex.com"}
        audit_path = tmp_path / "a.jsonl"
        vars().update(TESTE)

        def rules(self):
            return [CrawlRule(LinkExtractor(), callback=self.parse_item)]

        async def parse_item(self, response):
            yield {"h1": response.css("h1::text").get()}

    r = Blog().start()
    assert {i["h1"] for i in r.items} == {"Primeiro post"}
    assert "https://blog.ex.com/privado/x" not in fake.urls()
    assert not any("fora.com" in u for u in fake.urls())


def test_content_spider_gera_markdown_por_pagina(site, tmp_path):
    _site_blog(site)

    class Docs(ContentSpider):
        name = "docs"
        start_urls = ["https://blog.ex.com/"]
        allowed_domains = {"blog.ex.com"}
        output_dir = str(tmp_path / "md")
        audit_path = tmp_path / "a.jsonl"
        vars().update(TESTE)

    r = Docs().start()
    post = [i for i in r.items if i["url"].endswith("/post/1")][0]
    assert "Primeiro post" in post["markdown"]
    assert any((tmp_path / "md").glob("*.md"))
    assert not any("segredo" in i["markdown"] for i in r.items)


def test_sitemap_spider_le_sitemap_e_respeita_robots(site, tmp_path):
    sitemap = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://ex.com/a</loc></url><url><loc>https://ex.com/privado/b</loc></url></urlset>"""
    fake = site(
        {
            "https://ex.com/robots.txt": ROBOTS,
            "https://ex.com/sitemap.xml": (200, sitemap, {"content-type": "application/xml"}),
            "https://ex.com/a": (200, "<h1>a</h1>", {}),
            "https://ex.com/privado/b": (200, "<h1>b</h1>", {}),
        }
    )

    class Mapa(SitemapSpider):
        name = "mapa"
        sitemap_urls = ["https://ex.com/sitemap.xml"]
        audit_path = tmp_path / "a.jsonl"
        vars().update(TESTE)

        async def parse(self, response):
            yield {"h1": response.css("h1::text").get()}

    r = Mapa().start()
    assert [i["h1"] for i in r.items] == ["a"]
    assert "https://ex.com/privado/b" not in fake.urls()


def test_modo_dev_reproduz_do_cache_sem_rede(site, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake = site({"https://ex.com/robots.txt": (404, "", {}), "https://ex.com/": (200, "<h1>x</h1>", {})})

    class Dev(Spider):
        name = "dev"
        start_urls = ["https://ex.com/"]
        development_mode = True
        audit_path = tmp_path / "a.jsonl"
        vars().update(TESTE)

        async def parse(self, response):
            yield {"h1": response.css("h1::text").get()}

    Dev().start()
    paginas = fake.urls().count("https://ex.com/")
    r = Dev().start()
    assert r.items == [{"h1": "x"}]
    assert fake.urls().count("https://ex.com/") == paginas == 1
    assert r.stats.cache_hits == 1
    assert (tmp_path / ".raspador-cache" / "dev").is_dir()


def test_stream_e_on_scraped_item(site, tmp_path):
    site({"https://ex.com/robots.txt": (404, "", {}), "https://ex.com/": (200, "<h1>x</h1><h2>y</h2>", {})})

    class St(Spider):
        name = "stream"
        start_urls = ["https://ex.com/"]
        audit_path = tmp_path / "a.jsonl"
        vars().update(TESTE)

        async def parse(self, response):
            for t in response.css("h1::text, h2::text").getall():
                yield {"t": t}

        async def on_scraped_item(self, item):
            return None if item["t"] == "y" else {**item, "ok": True}

    async def coletar():
        return [item async for item in St().stream()]

    assert anyio.run(coletar) == [{"t": "x", "ok": True}]
