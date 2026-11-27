"""C5: robots.txt que não pôde ser lido (rede, proxy fora do ar, 5xx) continua fechando o site, mas o erro diz isso.

Antes, a falha virava "tudo negado" e aparecia como RSP-R001 "o robots.txt não permite", o que manda o usuário
pedir acesso ao dono do site quando o problema é o proxy dele.
"""

import json

import pytest
from curl_cffi import CurlError

import raspador
from raspador import robots
from raspador.robots import RobotsDenied, RobotsUnavailable
from raspador.spiders import Spider

PAGINA = (200, "<h1>ok</h1>", {})
SEGREDO = "s3nh4-do-proxy"


def test_falha_de_rede_no_robots_e_r002_e_continua_fechada(site):
    fake = site({"https://ex.com/robots.txt": CurlError("Failed to connect to proxy"), "https://ex.com/p": PAGINA})
    with pytest.raises(RobotsUnavailable) as exc:
        raspador.get("https://ex.com/p")
    assert isinstance(exc.value, RobotsDenied)  # fail closed: quem tratava negado continua tratando
    assert exc.value.code == "RSP-R002"
    msg = str(exc.value)
    assert "não permite" not in msg
    assert "não foi possível ler o robots.txt de ex.com" in msg and "CurlError" in msg
    assert "https://ex.com/p" not in fake.urls()  # a página não foi buscada


def test_robots_5xx_tambem_e_r002_com_o_status(site):
    site({"https://ex.com/robots.txt": (503, "", {}), "https://ex.com/p": PAGINA})
    with pytest.raises(RobotsUnavailable) as exc:
        raspador.get("https://ex.com/p")
    assert "HTTP 503" in str(exc.value)


@pytest.mark.parametrize("status", [401, 403])
def test_robots_401_403_continua_sendo_negado_de_verdade(site, status):
    site({"https://ex.com/robots.txt": (status, "", {}), "https://ex.com/p": PAGINA})
    with pytest.raises(RobotsDenied) as exc:
        raspador.get("https://ex.com/p")
    assert not isinstance(exc.value, RobotsUnavailable) and exc.value.code == "RSP-R001"


def test_falha_em_cache_continua_r002_sem_nova_busca(site):
    fake = site({"https://ex.com/robots.txt": CurlError("Connection refused")})
    for _ in range(2):
        with pytest.raises(RobotsUnavailable):
            raspador.get("https://ex.com/p")
    assert fake.urls().count("https://ex.com/robots.txt") == 1


def test_mensagem_nao_carrega_a_senha_do_proxy(site):
    site({"https://ex.com/robots.txt": CurlError(f"Failed to connect to http://u:{SEGREDO}@proxy.ex:8080")})
    with pytest.raises(RobotsUnavailable) as exc:
        raspador.get("https://ex.com/p")
    assert SEGREDO not in str(exc.value)


def test_unidade_do_cache_dis_o_motivo():
    cache = robots.RobotsCache()

    def cai(url):
        raise TimeoutError("lento")

    with pytest.raises(RobotsUnavailable) as exc:
        cache.check("https://ex.com/a", cai)
    assert "TimeoutError" in str(exc.value)


def test_cli_proxy_fora_do_ar_sai_como_rede_e_nao_como_robots(site, tmp_path):
    from click.testing import CliRunner

    from raspador import _ui
    from raspador.cli import main

    site({"https://ex.com/robots.txt": CurlError("Failed to connect to proxy")})
    r = CliRunner(env={"NO_COLOR": None, "FORCE_COLOR": None}).invoke(
        main, ["get", "https://ex.com/p", str(tmp_path / "x.md"), "--proxy", "http://proxy.ex:8080"]
    )
    assert r.exit_code == _ui.EXIT_NETWORK
    assert "RSP-R002" in r.stderr and "RSP-R001" not in r.stderr
    assert "peça acesso ao dono" not in r.stderr
    assert "proxy" in r.stderr  # a dica aponta para rede/proxy


def test_spider_audita_robots_indisponivel_separado_de_negado(site, tmp_path):
    site({"https://ex.com/robots.txt": CurlError("Failed to connect to proxy"), "https://ex.com/": PAGINA})

    class S(Spider):
        name = "robots-fora"
        download_delay = 0.0
        autothrottle_enabled = False
        policy_override = "teste automatizado em memória"
        start_urls = ["https://ex.com/"]
        audit_path = tmp_path / "audit.jsonl"

        async def parse(self, response):
            yield {"ok": True}

    assert S().start().items == []
    eventos = [json.loads(linha) for linha in (tmp_path / "audit.jsonl").read_text().splitlines()]
    robots_ev = [e for e in eventos if e["event"].startswith("robots_")]
    assert [e["event"] for e in robots_ev] == ["robots_unavailable"]
    assert robots_ev[0]["code"] == "RSP-R002" and "CurlError" in robots_ev[0]["reason"]
