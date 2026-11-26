"""Política do raspador: o que pode e o que não pode passar por uma requisição."""

import pytest

from raspador.policy import (
    PolicyError,
    check_request_kwargs,
    check_session,
    check_spider_class,
    default_user_agent,
)


def test_kwargs_permitidos_passam():
    check_request_kwargs({"headers": {"Accept": "text/html"}, "params": {"q": "x"}, "timeout": 10, "data": {"a": 1}})


@pytest.mark.parametrize(
    "opcao, valor",
    [
        ("impersonate", "chrome"),
        ("stealth", True),
        ("stealthy_headers", True),
        ("solve_cloudflare", True),
        ("ja3", "771,4865-4866"),
        ("akamai", "1:65536"),
        ("extra_fp", {"tls": 1}),
        ("default_headers", True),
        ("http_version", 3),
        ("proxies", {"https": "http://p:1"}),
        ("proxy_auth", ("u", "p")),
    ],
)
def test_opcao_de_evasao_ou_desconhecida_e_rejeitada(opcao, valor):
    with pytest.raises(PolicyError) as exc:
        check_request_kwargs({opcao: valor})
    assert exc.value.option == opcao
    assert exc.value.code in {"RSP-P001", "RSP-P002"}


def test_impersonate_none_e_stealth_false_sao_aceitos():
    check_request_kwargs({"impersonate": None, "stealthy_headers": False, "stealth": False})


def test_kwargs_que_o_follow_do_upstream_gera_passam_e_extra_headers_e_validado():
    url = "https://ex.com/p2"
    check_request_kwargs({"extra_headers": {"referer": "https://ex.com/"}, "google_search": False}, url=url)
    with pytest.raises(PolicyError):
        check_request_kwargs({"google_search": True}, url=url)
    with pytest.raises(PolicyError):
        check_request_kwargs({"extra_headers": {"Sec-Ch-Ua": "x"}}, url=url)


@pytest.mark.parametrize(
    "header",
    ["Sec-Ch-Ua", "sec-ch-ua-platform", "Sec-Fetch-Mode", "X-Forwarded-For", "client-ip", "Forwarded"],
)
def test_header_de_disfarce_e_rejeitado_sem_diferenciar_caixa(header):
    with pytest.raises(PolicyError) as exc:
        check_request_kwargs({"headers": {header: "x"}})
    assert exc.value.code == "RSP-P003"


def test_user_agent_precisa_identificar_o_raspador():
    check_request_kwargs({"headers": {"User-Agent": "raspador/0.1 (+mailto:eu@exemplo.com)"}})
    with pytest.raises(PolicyError) as exc:
        check_request_kwargs({"headers": {"user-agent": "Mozilla/5.0 Chrome/152"}})
    assert exc.value.code == "RSP-P003"


def test_referer_de_terceiro_e_rejeitado_e_o_do_proprio_site_aceito():
    check_request_kwargs(
        {"headers": {"referer": "https://loja.exemplo.com.br/lista"}},
        url="https://loja.exemplo.com.br/produto/1",
    )
    with pytest.raises(PolicyError):
        check_request_kwargs(
            {"headers": {"Referer": "https://www.google.com/"}}, url="https://loja.exemplo.com.br/produto/1"
        )


def test_mensagem_de_policy_error_tem_motivo_e_alternativa():
    with pytest.raises(PolicyError) as exc:
        check_request_kwargs({"impersonate": "chrome"})
    texto = str(exc.value)
    assert "RSP-P002" in texto
    assert "motivo:" in texto
    assert "em vez disso:" in texto
    assert exc.value.reason and exc.value.alternative


def test_user_agent_padrao_identifica_o_raspador():
    assert default_user_agent().startswith("raspador/")


class _SessaoFalsa:
    def __init__(self, impersonate=None, stealth=False, headers=None, rotator=None):
        self._default_impersonate = impersonate
        self._stealth = stealth
        self._default_headers = headers if headers is not None else {"User-Agent": default_user_agent()}
        self._proxy_rotator = rotator


def test_sessao_compliant_passa():
    check_session(_SessaoFalsa())


def test_sessao_com_padroes_do_upstream_e_rejeitada():
    with pytest.raises(PolicyError) as exc:
        check_session(_SessaoFalsa(impersonate="chrome", stealth=True))
    assert exc.value.code == "RSP-P007"


def test_sessao_com_rotator_e_rejeitada_em_spider():
    with pytest.raises(PolicyError) as exc:
        check_session(_SessaoFalsa(rotator=object()))
    assert exc.value.code == "RSP-P006"


class _Base:
    robots_txt_obey = True
    download_delay = 1.0
    concurrent_requests_per_domain = 1
    policy_override = None


def test_spider_que_desliga_robots_e_rejeitado_mesmo_com_override():
    attrs = {"robots_txt_obey": False, "policy_override": "é meu site"}
    with pytest.raises(PolicyError) as exc:
        check_spider_class(type("S", (_Base,), attrs))
    assert exc.value.code == "RSP-P004"


def test_spider_com_delay_baixo_exige_override():
    with pytest.raises(PolicyError) as exc:
        check_spider_class(type("S", (_Base,), {"download_delay": 0.1}))
    assert exc.value.code == "RSP-P005"
    check_spider_class(type("S", (_Base,), {"download_delay": 0.1, "policy_override": "API interna com cota"}))


def test_spider_com_slots_demais_ou_ilimitados_exige_override():
    for slots in (0, 5):
        with pytest.raises(PolicyError):
            check_spider_class(type("S", (_Base,), {"concurrent_requests_per_domain": slots}))


def test_opcoes_de_navegador_permitidas_e_as_de_disfarce_recusadas():
    from raspador.policy import check_browser_kwargs

    check_browser_kwargs({"wait_selector": "h1", "network_idle": True, "disable_resources": True, "locale": "pt-BR"})
    for opcao, valor in [
        ("solve_cloudflare", True),
        ("hide_canvas", True),
        ("block_webrtc", True),
        ("real_chrome", True),
        ("google_search", True),
        ("useragent", "Mozilla/5.0"),
        ("init_script", "/tmp/x.js"),
        ("additional_args", {"x": 1}),
        ("extra_flags", ["--x"]),
    ]:
        with pytest.raises(PolicyError):
            check_browser_kwargs({opcao: valor})
    with pytest.raises(PolicyError):
        check_browser_kwargs({"extra_headers": {"Referer": "https://www.google.com/"}}, url="https://ex.com/")
