"""Segredos e egress na costura do curl_cffi: o loop de retry, o log e o meta do upstream rodam de verdade.

Os testes de test_segredos.py trocam `_make_request` inteiro e por isso não enxergam o que o upstream faz ali dentro
(log com a URL do proxy, `meta={"proxy": ...}`). Aqui só `curl_cffi.Session.request` é falso.
"""

import logging
import pickle

import pytest
from curl_cffi import CurlError
from curl_cffi.requests import AsyncSession, Session

import raspador
from raspador import browser, http
from raspador._redact import redact
from raspador.policy import PolicyError, check_headers, check_request_kwargs

SEGREDO = "s3nh4-do-proxy"
FALHA = (CurlError, raspador.RobotsDenied)  # o robots.txt falha primeiro e falha vira "negado"
PROXY = f"http://cliente-br:{SEGREDO}@proxy.exemplo:8080"


@pytest.fixture
def curl_cai(monkeypatch):
    """Toda requisição falha como RST: o `is_proxy_error` do upstream casa e ele loga a URL do proxy."""
    vistos = []

    def cai(self, method, url, *a, **k):
        vistos.append({"url": url, "proxy": k.get("proxy"), "trust_env": self.trust_env})
        raise CurlError("Recv failure: Connection reset by peer")

    async def cai_async(self, method, url, *a, **k):
        return cai(self, method, url, *a, **k)

    monkeypatch.setattr(Session, "request", cai)
    monkeypatch.setattr(AsyncSession, "request", cai_async)
    return vistos


def test_log_do_upstream_em_falha_de_proxy_nao_mostra_a_senha(curl_cai, caplog, capfd):
    with caplog.at_level(logging.DEBUG), pytest.raises(FALHA):
        raspador.get("https://ex.com/p", proxy=PROXY, retries=2, retry_delay=0)
    streams = capfd.readouterr()
    tudo = caplog.text + streams.out + streams.err
    assert "proxy.exemplo:8080" in tudo and "failed" in tudo  # o upstream logou a falha
    assert SEGREDO not in tudo


def test_no_proxy_do_ambiente_nao_desvia_o_proxy_explicito(curl_cai, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "ex.com")
    monkeypatch.setenv("no_proxy", "ex.com")
    with pytest.raises(FALHA):
        raspador.get("https://ex.com/p", proxy=PROXY, retries=1)
    assert curl_cai and all(v["trust_env"] is False for v in curl_cai)


async def test_no_proxy_vale_tambem_na_sessao_assincrona(curl_cai, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "ex.com")
    async with raspador.async_http_session(proxy=PROXY, retries=1) as s:
        with pytest.raises(FALHA):
            await s.get("https://ex.com/p")
    assert curl_cai and all(v["trust_env"] is False for v in curl_cai)


def test_spider_session_tambem_ignora_no_proxy(curl_cai):
    sessao = http.spider_session(proxy=PROXY, retries=1)
    with sessao as cliente, pytest.raises(FALHA):
        cliente.get("https://ex.com/p")
    assert curl_cai and all(v["trust_env"] is False for v in curl_cai)


def test_meta_da_resposta_nao_carrega_a_senha_nem_vai_para_o_checkpoint(monkeypatch):
    from scrapling.spiders import Request

    class Resp:
        status_code, url, content, headers, cookies, reason, encoding = (
            200,
            "https://ex.com/p",
            b"<a href='/b'>b</a>",
            {},
            {},
            "OK",
            "utf-8",
        )
        history, request, http_version = [], None, 2

    monkeypatch.setattr(Session, "request", lambda self, m, url, *a, **k: Resp())
    page = raspador.get("https://ex.com/p", proxy=PROXY)
    assert SEGREDO not in repr(page.meta)
    page.request = Request("https://ex.com/p")  # no spider quem preenche é o manager
    seguinte = page.follow("/b")
    assert isinstance(seguinte, Request)
    assert SEGREDO.encode() not in pickle.dumps(seguinte.meta)


def test_redact_cobre_proxy_sem_esquema_e_arroba_na_senha():
    assert SEGREDO not in redact(f"cliente:{SEGREDO}@proxy.ex:8080")
    assert "ss" not in redact("http://user:p@ss@host:8080").split("@host")[0].replace("***", "")
    assert redact("http://user:p@ss@host:8080").endswith("@host:8080")
    assert redact("mande para eu@exemplo.com") == "mande para eu@exemplo.com"  # e-mail solto não é credencial


def test_proxy_sem_esquema_e_recusado_antes_da_rede():
    with pytest.raises(ValueError) as exc:
        raspador.http_session(proxy=f"cliente:{SEGREDO}@proxy.ex:8080")
    assert "RSP-U003" in str(exc.value) and SEGREDO not in str(exc.value)
    with pytest.raises(ValueError):
        check_request_kwargs({"proxy": f"cliente:{SEGREDO}@proxy.ex:8080"})


def test_valor_de_opcao_de_autenticacao_sai_mascarado_inteiro():
    with pytest.raises(PolicyError) as exc:
        check_request_kwargs({"proxy_auth": ("cliente", SEGREDO)})
    assert SEGREDO not in str(exc.value)
    with pytest.raises(PolicyError) as exc:
        check_request_kwargs({"curl_options": {"PROXYUSERPWD": f"u:{SEGREDO}"}})
    assert SEGREDO not in str(exc.value)


def test_proxy_authorization_como_header_e_recusado():
    with pytest.raises(PolicyError) as exc:
        check_headers({"Proxy-Authorization": f"Basic {SEGREDO}"})
    assert exc.value.code == "RSP-P003" and SEGREDO not in str(exc.value)


def test_navegador_passa_credencial_do_proxy_separada_do_server():
    kw = browser.BrowserSession(proxy=PROXY)._launch_kwargs()["proxy"]
    assert kw == {"server": "http://proxy.exemplo:8080", "username": "cliente-br", "password": SEGREDO}
    assert browser.BrowserSession(proxy="http://proxy.exemplo:8080")._launch_kwargs()["proxy"] == {
        "server": "http://proxy.exemplo:8080"
    }


def test_trocar_de_sid_para_sair_por_outro_proxy_no_mesmo_dominio_e_p006(site, tmp_path):
    """Duas sessões com proxies diferentes e um retry que troca o sid: é o ProxyRotator por outro caminho."""
    import json

    from raspador.spiders import Spider

    fake = site({"https://ex.com/robots.txt": (200, "User-agent: *\nAllow: /\n", {}), "https://ex.com/": (403, "", {})})

    class S(Spider):
        name = "troca-sid"
        start_urls = ["https://ex.com/"]
        max_blocked_retries = 1
        audit_path = tmp_path / "audit.jsonl"

        def configure_sessions(self, manager):
            manager.add("a", http.spider_session(proxy="http://proxy-a.exemplo:8080"), default=True)
            manager.add("b", http.spider_session(proxy="http://proxy-b.exemplo:8080"))

        async def retry_blocked_request(self, request, response):
            request.sid = "b"
            return request

        async def parse(self, response):
            yield {"ok": True}

    S().start()
    proxies = [r["final"].get("proxy") for r in fake.requests if r["url"] == "https://ex.com/"]
    assert proxies == ["http://proxy-a.exemplo:8080"]
    eventos = [json.loads(linha) for linha in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert ("RSP-P006", "sid") in [(e.get("code"), e.get("detail")) for e in eventos if e["event"] == "policy_error"]


def test_dominios_diferentes_podem_usar_sessoes_com_proxies_diferentes(site, tmp_path):
    from raspador.spiders import Spider

    ok = (200, "User-agent: *\nAllow: /\n", {})
    fake = site(
        {
            "https://br.ex/robots.txt": ok,
            "https://us.ex/robots.txt": ok,
            "https://br.ex/": (200, "<p>br</p>", {}),
            "https://us.ex/": (200, "<p>us</p>", {}),
        }
    )

    class S(Spider):
        name = "geo"
        audit_path = tmp_path / "audit.jsonl"

        def configure_sessions(self, manager):
            manager.add("br", http.spider_session(proxy="http://proxy-br.exemplo:8080"), default=True)
            manager.add("us", http.spider_session(proxy="http://proxy-us.exemplo:8080"))

        async def start_requests(self):
            yield raspador.Request("https://br.ex/", sid="br")
            yield raspador.Request("https://us.ex/", sid="us")

        async def parse(self, response):
            yield {"url": response.url}

    assert len(S().start().items) == 2
    por_url = {r["url"]: r["final"].get("proxy") for r in fake.requests if not r["url"].endswith("robots.txt")}
    assert por_url == {
        "https://br.ex/": "http://proxy-br.exemplo:8080",
        "https://us.ex/": "http://proxy-us.exemplo:8080",
    }
