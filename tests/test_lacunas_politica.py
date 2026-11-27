"""Duas lacunas achadas na revisão do README (2026-11-27).

1. Navegador: dentro da página só `localhost` e IP literal interno eram abortados; um hostname que resolve para IP
   privado (intranet, DNS apontando para 10.x) passava, e a URL final de um redirect não era checada.
2. ProxyPool: credencial passada por request (`Authorization`, `Cookie`, `cookies=`, `cert=`) saía pelo proxy do
   domínio, embora a sessão do pool recuse a mesma credencial.
"""

import json

import pytest

import raspador
from raspador import browser
from raspador import http as http_mod
from raspador.http import RedirectBlocked
from raspador.proxies import ProxyEntry, ProxyPool
from raspador.spiders import Spider

OK = (200, "User-agent: *\nAllow: /\n", {})
INTERNOS = {"intranet.exemplo": ["10.0.0.5"], "metadados.exemplo": ["169.254.169.254"]}


class _Consultas(list):
    """Hosts consultados. `instalar()` repõe o DNS falso: a fixture `site` troca `http.resolve` de novo."""

    def __init__(self, monkeypatch):
        super().__init__()
        self._mp = monkeypatch
        self.instalar()

    def instalar(self):
        def resolve(host):
            self.append(host)
            return INTERNOS.get(host, ["93.184.216.34"])

        self._mp.setattr(http_mod, "resolve", resolve)


@pytest.fixture
def dns(monkeypatch):
    """DNS falso: hosts de INTERNOS resolvem para rede interna, o resto para um IP público."""
    return _Consultas(monkeypatch)


# --- 1. navegador -------------------------------------------------------------------------------------------------


def test_hostname_que_resolve_para_ip_interno_e_abortado(dns):
    cache: dict = {}
    assert browser.internal_by_dns("intranet.exemplo", "ex.com", cache) is True
    assert browser.internal_by_dns("metadados.exemplo", "ex.com", cache) is True
    assert browser.internal_by_dns("cdn.publico.exemplo", "ex.com", cache) is False


def test_host_alvo_ip_literal_e_localhost_nao_consultam_dns(dns):
    cache: dict = {}
    for host in ("ex.com", "10.0.0.1", "93.184.216.34", "localhost", "app.localhost", ""):
        assert browser.internal_by_dns(host, "ex.com", cache) is False
    assert dns == []  # já tratados por route_decision, sem custo de DNS


def test_dns_e_consultado_uma_vez_por_host_na_sessao(dns):
    cache: dict = {}
    for _ in range(5):
        browser.internal_by_dns("intranet.exemplo", "ex.com", cache)
    assert dns == ["intranet.exemplo"]


def test_falha_de_dns_nao_aborta(monkeypatch):
    def cai(host):
        raise OSError("NXDOMAIN")

    monkeypatch.setattr(http_mod, "resolve", cai)
    assert browser.internal_by_dns("nao-existe.exemplo", "ex.com", {}) is False  # o próprio Chromium falha


def test_url_final_de_redirect_para_rede_interna_e_recusada(dns):
    with pytest.raises(RedirectBlocked):
        browser.check_final_url("https://ex.com/p", "https://intranet.exemplo/admin")
    browser.check_final_url("https://ex.com/p", "https://ex.com/outra")  # mesmo host: ok
    browser.check_final_url("https://ex.com/p", "https://cdn.publico.exemplo/x")


def _chromium_abre() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


chromium = pytest.mark.skipif(not _chromium_abre(), reason="Chromium não abre neste ambiente")


@chromium
def test_chromium_real_nao_busca_subrecurso_em_hostname_interno(site, dns):
    site({"https://ex.com/robots.txt": OK})
    dns.instalar()  # depois de site(), que põe um resolve próprio
    html = """<html><body><h1>ok</h1>
    <img src="https://intranet.exemplo/segredo.png"><img src="https://cdn.publico.exemplo/foto.png">
    </body></html>"""
    vistos: list[str] = []

    def setup(page):
        def handler(route):
            vistos.append(route.request.url)
            if route.request.url.endswith(".png"):
                route.fulfill(status=200, body=b"\x89PNG", content_type="image/png")
            else:
                route.fulfill(status=200, body=html, content_type="text/html")

        page.route("**/*", handler)

    with browser.BrowserSession() as b:
        r = b.fetch("https://ex.com/p", page_setup=setup, network_idle=True)
    assert r.status == 200
    assert "https://cdn.publico.exemplo/foto.png" in vistos
    assert not any("intranet.exemplo" in u for u in vistos)
    assert "intranet.exemplo" in dns  # a guarda consultou o DNS (sem isso o teste passaria vazio)


# --- 2. ProxyPool ---------------------------------------------------------------------------------------------------


def _pool():
    return ProxyPool([ProxyEntry("http://u:s3nh4@br1.proxy:8080", label="br-1")])


def _spider(tmp_path, request_kwargs):
    class S(Spider):
        name = "pool-credencial"
        proxy_pool = _pool()
        audit_path = tmp_path / "audit.jsonl"

        async def start_requests(self):
            yield raspador.Request("https://ex.com/conta", **request_kwargs)

        async def parse(self, response):
            yield {"ok": True}

    return S


@pytest.mark.parametrize(
    "kwargs",
    [
        {"headers": {"Authorization": "Bearer token-do-site"}},
        {"headers": {"cookie": "sessao=abc"}},
        {"cookies": {"sessao": "abc"}},
        {"cert": "/caminho/cliente.pem"},
    ],
    ids=["authorization", "cookie-header", "cookies", "cert"],
)
def test_pool_recusa_credencial_por_request(site, tmp_path, kwargs):
    fake = site({"https://ex.com/robots.txt": OK, "https://ex.com/conta": (200, "<p>dados</p>", {})})
    resultado = _spider(tmp_path, kwargs)().start()
    assert resultado.items == []
    assert "https://ex.com/conta" not in fake.urls()  # nada saiu pelo proxy
    eventos = [json.loads(linha) for linha in (tmp_path / "audit.jsonl").read_text().splitlines()]
    erros = [e for e in eventos if e["event"] == "policy_error"]
    assert erros and erros[0]["code"] == "RSP-P010"
    assert "token-do-site" not in json.dumps(eventos) and "sessao=abc" not in json.dumps(eventos)


def test_pool_aceita_headers_sem_credencial_por_request(site, tmp_path):
    fake = site({"https://ex.com/robots.txt": OK, "https://ex.com/conta": (200, "<p>dados</p>", {})})
    resultado = _spider(tmp_path, {"headers": {"Accept-Language": "pt-BR"}})().start()
    assert len(resultado.items) == 1 and "https://ex.com/conta" in fake.urls()


def test_sem_pool_credencial_por_request_continua_permitida(site, tmp_path):
    fake = site({"https://ex.com/robots.txt": OK, "https://ex.com/conta": (200, "<p>dados</p>", {})})

    class S(Spider):
        name = "sem-pool"
        audit_path = tmp_path / "audit.jsonl"

        async def start_requests(self):
            yield raspador.Request("https://ex.com/conta", headers={"Authorization": "Bearer x"})

        async def parse(self, response):
            yield {"ok": True}

    assert len(S().start().items) == 1 and "https://ex.com/conta" in fake.urls()


# --- revisão adversarial das duas correções ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, kwargs",
    [
        ("https://user:segredo@ex.com/conta", {}),  # credencial no userinfo da URL
        ("https://ex.com/conta", {"headers": {"X-Api-Key": "segredo"}}),  # header fora da allowlist do pool
        ("https://ex.com/conta", {"headers": {"X-Auth-Token": "segredo"}}),
    ],
    ids=["userinfo", "x-api-key", "x-auth-token"],
)
def test_pool_recusa_credencial_fora_dos_headers_classicos(site, tmp_path, url, kwargs):
    fake = site({"https://ex.com/robots.txt": OK, "https://ex.com/conta": (200, "<p>dados</p>", {})})

    class S(Spider):
        name = "pool-credencial-2"
        proxy_pool = _pool()
        audit_path = tmp_path / "audit.jsonl"

        async def start_requests(self):
            yield raspador.Request(url, **kwargs)

        async def parse(self, response):
            yield {"ok": True}

    assert S().start().items == []
    assert not any("conta" in u or "segredo" in u for u in fake.urls())  # nem a página nem o robots.txt
    assert "segredo" not in (tmp_path / "audit.jsonl").read_text()


def test_pool_aceita_headers_comuns_de_request(site, tmp_path):
    fake = site({"https://ex.com/robots.txt": OK, "https://ex.com/conta": (200, "<p>dados</p>", {})})
    headers = {"Accept": "application/json", "Content-Type": "application/json", "If-None-Match": '"abc"'}
    resultado = _spider(tmp_path, {"headers": headers})().start()
    assert len(resultado.items) == 1 and "https://ex.com/conta" in fake.urls()


@pytest.mark.parametrize("nome", ["Authorization ", " Cookie", "X Api", "Auth\torization", ""])
def test_nome_de_header_fora_do_padrao_http_e_recusado(nome):
    from raspador.policy import PolicyError, check_headers

    with pytest.raises(PolicyError) as exc:
        check_headers({nome: "Bearer segredo"})
    assert "segredo" not in str(exc.value)


def test_excecao_qualquer_no_dns_aborta_em_vez_de_travar(monkeypatch):
    def cai(host):
        raise UnicodeError("label empty or too long")

    monkeypatch.setattr(http_mod, "resolve", cai)
    assert browser.internal_by_dns("a" * 70 + ".exemplo", "ex.com", {}) is True  # falha fechada


def test_falha_de_rede_no_dns_continua_sem_abortar(monkeypatch):
    def cai(host):
        raise OSError("NXDOMAIN")

    monkeypatch.setattr(http_mod, "resolve", cai)
    assert browser.internal_by_dns("nao-existe.exemplo", "ex.com", {}) is False


@pytest.mark.parametrize("addr", ["64:ff9b::a00:5", "64:ff9b::a9fe:a9fe", "::a00:5", "::7f00:1"])
def test_nat64_e_ipv4_compativel_apontando_para_rede_interna(addr):
    from raspador.http import _is_internal

    assert _is_internal(addr)


def test_nat64_para_ip_publico_continua_publico():
    from raspador.http import _is_internal

    assert not _is_internal("64:ff9b::5db8:d822")  # 93.184.216.34


def test_allow_private_libera_intranet_no_navegador(dns):
    cache: dict = {}
    assert browser.internal_by_dns("intranet.exemplo", "app.corp", cache, allow_private=True) is False
    browser.check_final_url("https://app.corp/", "https://intranet.exemplo/x", allow_private=True)
    s = browser.BrowserSession(allow_private=True)
    assert browser.route_decision("http://10.0.0.9/a.js", "script", "app.corp", False, allow_private=True) == "continue"
    assert s._allow_private is True


def test_contexto_bloqueia_service_worker():
    assert browser.BrowserSession()._context_kwargs()["service_workers"] == "block"


def test_mensagens_de_url_nao_mostram_senha():
    from raspador.http import InvalidURL, RedirectBlocked, check_url

    with pytest.raises(InvalidURL) as exc:
        check_url("https://u:senha-secreta@ex%41.com/")
    assert "senha-secreta" not in str(exc.value)
    assert "senha-secreta" not in str(RedirectBlocked("http://u:senha-secreta@10.0.0.1/"))


def test_mcp_repassa_allow_private_ao_navegador():
    import inspect

    from raspador import mcp_server

    assert "allow_private=allow_private" in inspect.getsource(mcp_server.build_server)
