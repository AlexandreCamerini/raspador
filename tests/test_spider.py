"""raspador.Spider rodando o engine real do Scrapling contra um site falso em memória.

O transporte HTTP é substituído em `_ASyncSessionLogic._make_request`, o único ponto onde o
upstream chama o curl_cffi. Tudo acima dele (engine, scheduler, robots, sessão) é o código real.
"""

import json

import pytest
from scrapling.fetchers import FetcherSession

import raspador
from raspador.policy import PolicyError
from raspador.spiders import Spider

ROBOTS_OK = (200, "User-agent: *\nAllow: /", {})


class Base(Spider):
    name = "teste"
    download_delay = 0.0
    autothrottle_enabled = False
    policy_override = "teste automatizado em memória"


def _audit(tmp_path):
    p = tmp_path / "audit.jsonl"
    linhas = [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []
    return [e for e in linhas if e["event"] != "policy_override"]


def test_crawl_compliant_segue_links_e_se_identifica(site, tmp_path):
    fake = site(
        {
            "https://ex.com/robots.txt": ROBOTS_OK,
            "https://ex.com/": (200, '<a href="/p2">2</a><h1>um</h1>', {}),
            "https://ex.com/p2": (200, "<h1>dois</h1>", {}),
        }
    )

    class S(Base):
        start_urls = ["https://ex.com/"]
        audit_path = tmp_path / "audit.jsonl"

        async def parse(self, response):
            yield {"h1": response.css("h1::text").get()}
            for href in response.css("a::attr(href)").getall():
                yield response.follow(href)

    result = S().start()
    assert sorted(i["h1"] for i in result.items) == ["dois", "um"]
    pagina = [r for r in fake.requests if r["url"] == "https://ex.com/"][0]
    final = pagina["final"]
    assert final["impersonate"] is None
    assert final["headers"]["User-Agent"].startswith("raspador/")
    assert not any(k.lower().startswith(("sec-ch-ua", "sec-fetch-")) for k in final["headers"])
    assert "referer" not in {k.lower() for k in final["headers"]}
    seguida = [r for r in fake.requests if r["url"] == "https://ex.com/p2"][0]["final"]
    assert seguida["headers"]["referer"] == "https://ex.com/"
    assert [r["url"] for r in fake.requests].count("https://ex.com/robots.txt") == 1
    saida = tmp_path / "itens.json"
    result.items.to_json(saida)
    assert sorted(i["h1"] for i in json.loads(saida.read_text())) == ["dois", "um"]


def test_robots_respeita_grupo_especifico_do_raspador(site, tmp_path):
    site(
        {
            "https://ex.com/robots.txt": (
                200,
                "User-agent: *\nAllow: /\n\nUser-agent: raspador\nDisallow: /privado",
                {},
            ),
            "https://ex.com/privado": (200, "<h1>segredo</h1>", {}),
        }
    )

    class S(Base):
        start_urls = ["https://ex.com/privado"]
        audit_path = tmp_path / "audit.jsonl"

        async def parse(self, response):
            yield {"h1": response.css("h1::text").get()}

    result = S().start()
    assert result.items == []
    assert result.stats.robots_disallowed_count == 1
    assert [e["event"] for e in _audit(tmp_path)] == ["robots_denied"]


def test_robots_401_ou_403_bloqueia_o_dominio(site, tmp_path):
    site({"https://ex.com/robots.txt": (403, "", {}), "https://ex.com/": (200, "<h1>x</h1>", {})})

    class S(Base):
        start_urls = ["https://ex.com/"]
        audit_path = tmp_path / "audit.jsonl"

        async def parse(self, response):
            yield {"ok": True}

    assert S().start().items == []


def test_request_com_opcao_de_evasao_falha_e_e_auditado(site, tmp_path):
    fake = site({"https://ex.com/robots.txt": ROBOTS_OK, "https://ex.com/": (200, "<h1>x</h1>", {})})

    class S(Base):
        start_urls = ["https://ex.com/"]
        audit_path = tmp_path / "audit.jsonl"

        async def parse(self, response):
            yield raspador.spiders.Request("https://ex.com/b", impersonate="chrome")
            yield {"ok": True}

    result = S().start()
    assert result.items == [{"ok": True}]
    assert "https://ex.com/b" not in [r["url"] for r in fake.requests]
    eventos = _audit(tmp_path)
    assert eventos[0]["event"] == "policy_error" and eventos[0]["code"] == "RSP-P002"


def test_start_url_fora_de_allowed_domains_e_descartada(site, tmp_path):
    fake = site({"https://outro.com/robots.txt": ROBOTS_OK, "https://outro.com/": (200, "x", {})})

    class S(Base):
        start_urls = ["https://outro.com/"]
        allowed_domains = {"ex.com"}
        audit_path = tmp_path / "audit.jsonl"

        async def parse(self, response):
            yield {"ok": True}

    assert S().start().items == []
    assert fake.requests == []  # nem robots.txt de um domínio fora do escopo
    assert [e["event"] for e in _audit(tmp_path)] == ["offsite_dropped"]


def test_redirect_no_mesmo_site_e_seguido_e_para_outro_site_e_descartado(site, tmp_path):
    site(
        {
            "https://ex.com/robots.txt": ROBOTS_OK,
            "https://ex.com/a": (301, "", {"location": "/b"}),
            "https://ex.com/b": (200, "<h1>b</h1>", {}),
            "https://ex.com/c": (302, "", {"location": "https://fora.com/x"}),
        }
    )

    class S(Base):
        start_urls = ["https://ex.com/a", "https://ex.com/c"]
        allowed_domains = {"ex.com"}
        audit_path = tmp_path / "audit.jsonl"

        async def parse(self, response):
            yield {"url": response.url, "h1": response.css("h1::text").get()}

    result = S().start()
    assert result.items == [{"url": "https://ex.com/b", "h1": "b"}]
    assert [e["event"] for e in _audit(tmp_path)] == ["offsite_dropped"]


def test_dominio_para_depois_de_bloqueios_seguidos(site, tmp_path):
    pages = {"https://ex.com/robots.txt": ROBOTS_OK}
    pages |= {f"https://ex.com/{i}": (403, "", {}) for i in range(8)}
    fake = site(pages)

    class S(Base):
        start_urls = [f"https://ex.com/{i}" for i in range(8)]
        max_blocked_retries = 0
        max_consecutive_blocks = 3
        concurrent_requests = 1
        audit_path = tmp_path / "audit.jsonl"

        async def parse(self, response):
            yield {"ok": True}

    S().start()
    paginas = [r for r in fake.requests if not r["url"].endswith("robots.txt")]
    assert len(paginas) == 3
    assert [e["event"] for e in _audit(tmp_path)].count("domain_stopped") == 1


def test_classe_que_desliga_robots_nem_e_criada():
    with pytest.raises(PolicyError):

        class S(Spider):
            name = "x"
            robots_txt_obey = False

            async def parse(self, response):
                yield None


def test_sessao_com_padroes_do_upstream_e_recusada_no_init():
    class S(Base):
        start_urls = ["https://ex.com/"]

        def configure_sessions(self, manager):
            manager.add("default", FetcherSession())

        async def parse(self, response):
            yield None

    with pytest.raises(Exception) as exc:
        S()
    assert "RSP-P007" in str(exc.value)


def test_proxy_por_request_no_spider_e_recusado_mesmo_no_retry(site, tmp_path):
    fake = site({"https://ex.com/robots.txt": ROBOTS_OK, "https://ex.com/": (403, "", {})})

    class S(Base):
        start_urls = ["https://ex.com/"]
        max_blocked_retries = 1
        audit_path = tmp_path / "audit.jsonl"

        async def retry_blocked_request(self, request, response):
            request._session_kwargs["proxy"] = "http://outro-proxy:8080"
            return request

        async def parse(self, response):
            yield {"ok": True}

    S().start()
    assert [r["url"] for r in fake.requests].count("https://ex.com/") == 1
    erros = [e for e in _audit(tmp_path) if e["event"] == "policy_error"]
    assert [e["code"] for e in erros] == ["RSP-P006"]


def test_redirect_do_spider_para_ip_interno_e_bloqueado(site, tmp_path):
    fake = site(
        {
            "https://ex.com/robots.txt": ROBOTS_OK,
            "https://ex.com/a": (302, "", {"location": "http://10.0.0.5/painel"}),
        }
    )

    class S(Base):
        start_urls = ["https://ex.com/a"]
        audit_path = tmp_path / "audit.jsonl"

        async def parse(self, response):
            yield {"ok": True}

    assert S().start().items == []
    assert not any("10.0.0.5" in u for u in fake.urls())
