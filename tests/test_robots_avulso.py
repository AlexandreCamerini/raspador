"""robots.txt também vale para raspador.get/post/... e para as sessões guardadas."""

import pytest

import raspador
from raspador.robots import RobotsDenied, robots_content

ROBOTS = "User-agent: *\nAllow: /\n\nUser-agent: raspador\nDisallow: /privado\n"


def test_get_avulso_respeita_robots_do_raspador(site):
    fake = site({"https://ex.com/robots.txt": (200, ROBOTS, {}), "https://ex.com/privado/x": (200, "x", {})})
    with pytest.raises(RobotsDenied) as exc:
        raspador.get("https://ex.com/privado/x")
    assert exc.value.code == "RSP-R001"
    assert fake.urls() == ["https://ex.com/robots.txt"]


def test_robots_buscado_uma_vez_por_dominio_na_mesma_sessao(site):
    fake = site(
        {
            "https://ex.com/robots.txt": (200, ROBOTS, {}),
            "https://ex.com/a": (200, "a", {}),
            "https://ex.com/b": (200, "b", {}),
        }
    )
    with raspador.http_session() as s:
        assert s.get("https://ex.com/a").status == 200
        assert s.get("https://ex.com/b").status == 200
    assert fake.urls().count("https://ex.com/robots.txt") == 1


async def test_sessao_assincrona_tambem_respeita_robots(site):
    site({"https://ex.com/robots.txt": (200, ROBOTS, {})})
    async with raspador.async_http_session() as s:
        with pytest.raises(RobotsDenied):
            await s.get("https://ex.com/privado/1")


@pytest.mark.parametrize(
    "status, body, permitido",
    [
        (200, "User-agent: *\nDisallow: /", False),
        (404, "", True),
        (401, "", False),
        (403, "", False),
        (500, "", False),
        (None, "", False),
    ],
)
def test_regras_de_status_do_robots(status, body, permitido):
    from protego import Protego

    parser = Protego.parse(robots_content(status, body.encode()))
    assert parser.can_fetch("https://ex.com/qualquer", "raspador") is permitido


def test_redirect_avulso_checa_robots_em_cada_salto(site):
    fake = site(
        {
            "https://ex.com/robots.txt": (200, ROBOTS, {}),
            "https://ex.com/a": (302, "", {"location": "/privado/x"}),
        }
    )
    with pytest.raises(RobotsDenied):
        raspador.get("https://ex.com/a")
    assert "https://ex.com/privado/x" not in fake.urls()


def test_redirect_avulso_no_mesmo_site_e_seguido(site):
    site(
        {
            "https://ex.com/robots.txt": (200, ROBOTS, {}),
            "https://ex.com/a": (301, "", {"location": "/b"}),
            "https://ex.com/b": (200, "<h1>b</h1>", {}),
        }
    )
    r = raspador.get("https://ex.com/a")
    assert r.status == 200 and r.url == "https://ex.com/b"


def test_redirect_para_ip_interno_e_bloqueado(site):
    from raspador.http import RedirectBlocked

    fake = site(
        {
            "https://ex.com/robots.txt": (200, ROBOTS, {}),
            "https://ex.com/a": (302, "", {"location": "http://127.0.0.1:8080/admin"}),
            "http://127.0.0.1:8080/robots.txt": (404, "", {}),
        }
    )
    with pytest.raises(RedirectBlocked) as exc:
        raspador.get("https://ex.com/a")
    assert exc.value.code == "RSP-N002"
    assert not any(u.startswith("http://127.0.0.1") for u in fake.urls())


def test_resposta_maior_que_o_limite_e_recusada(site):
    from raspador.http import ResponseTooLarge

    site({"https://ex.com/robots.txt": (200, ROBOTS, {}), "https://ex.com/grande": (200, b"x" * 2048, {})})
    with pytest.raises(ResponseTooLarge) as exc:
        raspador.get("https://ex.com/grande", max_bytes=1024)
    assert exc.value.code == "RSP-N003"
