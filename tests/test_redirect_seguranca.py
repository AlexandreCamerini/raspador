"""Segurança dos caminhos que o raspador assumiu do curl: robots com o mesmo transporte, credenciais em
redirect para outro host e endereços internos."""

import pytest

import raspador
from raspador import robots
from raspador.http import RedirectBlocked, check_redirect_target
from raspador.spiders import Spider

ROBOTS_OK = (200, "User-agent: *\nAllow: /", {})


def test_robots_avulso_usa_verify_proxy_e_timeout_da_requisicao(site):
    fake = site({"https://ex.com/robots.txt": ROBOTS_OK, "https://ex.com/p": (200, "x", {})})
    raspador.get("https://ex.com/p", verify=False, proxy="http://proxy.exemplo:3128", timeout=7)
    rob = [r for r in fake.requests if r["url"].endswith("/robots.txt")][0]["final"]
    assert rob["verify"] is False
    assert rob["proxy"] == "http://proxy.exemplo:3128"
    assert rob["timeout"] == 7


def test_falha_ao_buscar_robots_fica_em_cache_por_minutos_nao_por_um_dia(monkeypatch):
    cache = robots.RobotsCache()
    agora = [1000.0]
    monkeypatch.setattr(robots.time, "monotonic", lambda: agora[0])
    chamadas = []

    def falha(url):
        chamadas.append(url)
        raise OSError("dns")

    with pytest.raises(robots.RobotsDenied):
        cache.check("https://ex.com/a", falha)
    agora[0] += robots.ROBOTS_FAILURE_TTL_SECONDS + 1
    with pytest.raises(robots.RobotsDenied):
        cache.check("https://ex.com/a", falha)
    assert len(chamadas) == 2


def test_redirect_para_outro_host_nao_leva_credenciais_no_avulso(site):
    fake = site(
        {
            "https://ex.com/robots.txt": ROBOTS_OK,
            "https://outro.com/robots.txt": ROBOTS_OK,
            "https://ex.com/a": (302, "", {"location": "https://outro.com/b"}),
            "https://outro.com/b": (200, "b", {}),
        }
    )
    raspador.get("https://ex.com/a", headers={"Authorization": "Bearer x", "X-Ok": "1"}, cookies={"s": "1"})
    destino = [r for r in fake.requests if r["url"] == "https://outro.com/b"][0]["final"]
    nomes = {k.lower() for k in destino["headers"]}
    assert "authorization" not in nomes and "cookie" not in nomes
    assert "x-ok" in nomes
    assert not destino.get("cookies")


def test_credencial_na_sessao_impede_redirect_para_outro_host(site):
    fake = site(
        {
            "https://ex.com/robots.txt": ROBOTS_OK,
            "https://ex.com/a": (302, "", {"location": "https://outro.com/b"}),
        }
    )
    with raspador.http_session(headers={"Authorization": "Bearer x"}) as s:
        r = s.get("https://ex.com/a")
    assert r.status == 302
    assert "https://outro.com/b" not in fake.urls()


def test_redirect_do_spider_para_outro_host_nao_leva_credenciais(site, tmp_path):
    fake = site(
        {
            "https://ex.com/robots.txt": ROBOTS_OK,
            "https://outro.com/robots.txt": ROBOTS_OK,
            "https://ex.com/a": (302, "", {"location": "https://outro.com/b"}),
            "https://outro.com/b": (200, "<h1>b</h1>", {}),
        }
    )

    class S(Spider):
        name = "cred"
        download_delay = 0.0
        autothrottle_enabled = False
        policy_override = "teste automatizado em memória"
        audit_path = tmp_path / "a.jsonl"

        async def start_requests(self):
            yield raspador.Request("https://ex.com/a", headers={"Authorization": "Bearer x"}, cookies={"s": "1"})

        async def parse(self, response):
            yield {"h1": response.css("h1::text").get()}

    assert S().start().items == [{"h1": "b"}]
    destino = [r for r in fake.requests if r["url"] == "https://outro.com/b"][0]["final"]
    assert "authorization" not in {k.lower() for k in destino["headers"]}
    assert not destino.get("cookies")


@pytest.mark.parametrize(
    "alvo",
    ["http://[::ffff:127.0.0.1]/", "http://100.64.1.1/", "http://0.0.0.0/", "http://169.254.169.254/latest/meta-data/"],
)
def test_enderecos_internos_e_cgnat_sao_bloqueados(alvo):
    with pytest.raises(RedirectBlocked):
        check_redirect_target("https://ex.com/", alvo)
