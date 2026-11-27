"""Navegador do raspador. As funções puras rodam em qualquer lugar; os testes com Chromium real pulam
quando o navegador não abre (o sandbox do agente bloqueia as portas Mach do Chromium no macOS)."""

import stat

import pytest

from raspador import browser
from raspador.policy import PolicyError
from raspador.robots import RobotsDenied


@pytest.mark.parametrize(
    "url, tipo, disable, esperado",
    [
        ("https://ex.com/app.js", "script", False, "continue"),
        ("https://cdn.ex.net/a.png", "image", True, "abort"),
        ("https://cdn.ex.net/a.png", "image", False, "continue"),
        ("http://127.0.0.1:8080/x", "xhr", False, "abort"),
        ("http://[::ffff:10.0.0.1]/x", "fetch", False, "abort"),
        ("http://169.254.169.254/latest", "xhr", False, "abort"),
        ("http://localhost:3000/api", "fetch", False, "abort"),
    ],
)
def test_decisao_de_rota(url, tipo, disable, esperado):
    assert browser.route_decision(url, tipo, "ex.com", disable) == esperado


def test_alvo_local_pode_carregar_os_proprios_recursos():
    assert browser.route_decision("http://localhost:3000/app.js", "script", "localhost", False) == "continue"


def test_response_do_navegador_usa_storage_do_raspador_e_parseia():
    r = browser.build_response("https://ex.com/", "<h1>Olá</h1>", 200, "OK", {}, {"s": "1"}, None)
    assert r.css("h1::text").get() == "Olá"
    assert r.cookies == {"s": "1"}


def test_sessao_recusa_opcao_de_disfarce_sem_abrir_navegador():
    with pytest.raises(PolicyError):
        browser.BrowserSession(solve_cloudflare=True)
    with pytest.raises(PolicyError):
        browser.BrowserSession(init_script="/tmp/patch.js")


def _chromium_abre() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


chromium = pytest.mark.skipif(not _chromium_abre(), reason="Chromium não abre neste ambiente")

ROBOTS = (200, "User-agent: *\nAllow: /\n\nUser-agent: raspador\nDisallow: /privado\n", {})
PAGINA_JS = """<html><body><h1>estático</h1>
<script>setTimeout(() => document.body.insertAdjacentHTML('beforeend', '<p id="js">renderizado</p>'), 50)</script>
<img src="https://cdn.ex.net/foto.png"></body></html>"""


def _servir(vistos):
    def setup(page):
        def handler(route):
            vistos.append({"url": route.request.url, "ua": route.request.headers.get("user-agent", "")})
            if route.request.url.endswith(".png"):
                route.fulfill(status=200, body=b"\x89PNG", content_type="image/png")
            else:
                route.fulfill(
                    status=200, body=PAGINA_JS, content_type="text/html", headers={"set-cookie": "sessao=abc; Path=/"}
                )

        page.route("**/*", handler)

    return setup


@chromium
def test_renderiza_js_identificado_e_sem_recursos_pesados(site):
    site({"https://ex.com/robots.txt": ROBOTS})
    vistos = []
    with browser.BrowserSession(disable_resources=True) as b:
        r = b.fetch("https://ex.com/p", wait_selector="#js", page_setup=_servir(vistos))
    assert r.status == 200
    assert r.css("#js::text").get() == "renderizado"
    assert vistos[0]["ua"].startswith("raspador/")
    assert not any(v["url"].endswith(".png") for v in vistos)


@chromium
def test_robots_negado_nem_abre_a_pagina(site):
    site({"https://ex.com/robots.txt": ROBOTS})
    vistos = []
    with browser.BrowserSession() as b, pytest.raises(RobotsDenied):
        b.fetch("https://ex.com/privado/x", page_setup=_servir(vistos))
    assert vistos == []


@chromium
def test_salva_e_recarrega_estado(site, tmp_path):
    site({"https://ex.com/robots.txt": ROBOTS})
    estado = tmp_path / "estado.json"
    with browser.BrowserSession() as b:
        b.fetch("https://ex.com/login", page_setup=_servir([]))
        b.save_state(estado)
    assert stat.S_IMODE(estado.stat().st_mode) == 0o600
    assert "sessao" in estado.read_text()
    with browser.BrowserSession(storage_state=estado) as b:
        assert any(c["name"] == "sessao" for c in b._context.cookies())


@chromium
async def test_sessao_assincrona_renderiza(site):
    site({"https://ex.com/robots.txt": ROBOTS})
    vistos = []

    async def setup(page):
        async def handler(route):
            vistos.append(route.request.url)
            await route.fulfill(status=200, body=PAGINA_JS, content_type="text/html")

        await page.route("**/*", handler)

    async with browser.AsyncBrowserSession() as b:
        r = await b.fetch("https://ex.com/p", wait_selector="#js", page_setup=setup)
    assert r.css("#js::text").get() == "renderizado"


def test_spider_aceita_navegador_do_raspador_e_valida_opcoes_por_request(site, tmp_path):
    import raspador
    from raspador.spiders import Spider

    site({"https://ex.com/robots.txt": ROBOTS})

    class S(Spider):
        name = "nav"
        download_delay = 0.0
        autothrottle_enabled = False
        policy_override = "teste automatizado em memória"
        audit_path = tmp_path / "a.jsonl"

        def configure_sessions(self, manager):
            manager.add("http", raspador.http.spider_session())
            manager.add("nav", browser.AsyncBrowserSession(), lazy=True)

        async def start_requests(self):
            yield raspador.Request("https://ex.com/p", sid="nav", solve_cloudflare=True)

        async def parse(self, response):
            yield {"ok": True}

    assert S().start().items == []
    eventos = (tmp_path / "a.jsonl").read_text()
    assert '"code": "RSP-P002"' in eventos


@chromium
def test_spider_renderiza_pelo_navegador_e_segue_link(site, tmp_path):
    from raspador.spiders import Spider

    site({"https://ex.com/robots.txt": ROBOTS})
    paginas = {
        "https://ex.com/p": PAGINA_JS.replace("<h1>estático</h1>", '<h1>estático</h1><a href="/p2">2</a>'),
        "https://ex.com/p2": PAGINA_JS,
    }

    async def setup(page):
        async def handler(route):
            corpo = paginas.get(route.request.url.split("#")[0])
            if corpo is None:
                await route.fulfill(status=404, body="")
            else:
                await route.fulfill(status=200, body=corpo, content_type="text/html")

        await page.route("**/*", handler)

    class S(Spider):
        name = "nav2"
        start_urls = ["https://ex.com/p"]
        download_delay = 0.0
        autothrottle_enabled = False
        policy_override = "teste automatizado em memória"
        audit_path = tmp_path / "a.jsonl"

        def configure_sessions(self, manager):
            manager.add("nav", browser.AsyncBrowserSession(page_setup=setup, wait_selector="#js"))

        async def parse(self, response):
            yield {"url": response.url, "js": response.css("#js::text").get()}
            for href in response.css("a::attr(href)").getall():
                yield response.follow(href)

    itens = sorted(S().start().items, key=lambda i: i["url"])
    assert itens == [
        {"url": "https://ex.com/p", "js": "renderizado"},
        {"url": "https://ex.com/p2", "js": "renderizado"},
    ]


def test_follow_num_spider_de_navegador_passa_na_politica():
    from scrapling.engines.toolbelt.custom import Response
    from scrapling.spiders import Request

    from raspador.policy import check_browser_kwargs

    r = Response("https://ex.com/", b"<a href=/x>x</a>", 200, "", {}, {}, {}, _log=False)
    r.request = Request("https://ex.com/", sid="nav")
    seguido = r.follow("/x")
    check_browser_kwargs(seguido._session_kwargs, url=seguido.url)
    opts = browser._Options(seguido.url, dict(seguido._session_kwargs), {})
    assert opts.extra_headers == {"referer": "https://ex.com/"}


@pytest.mark.parametrize("header", ["Authorization", "cookie", "Proxy-Authorization"])
def test_credencial_em_header_de_navegador_e_recusada(header):
    from raspador.policy import check_browser_kwargs

    for chave in ("extra_headers", "headers"):
        with pytest.raises(PolicyError) as exc:
            check_browser_kwargs({chave: {header: "x"}}, url="https://ex.com/")
        assert "storage_state" in exc.value.alternative


def test_robots_de_sid_de_navegador_sai_pelo_proxy_da_sessao(site, tmp_path):
    import raspador
    from raspador.spiders import Spider

    fake = site({"https://ex.com/robots.txt": ROBOTS})

    class S(Spider):
        name = "navproxy"
        download_delay = 0.0
        autothrottle_enabled = False
        policy_override = "teste automatizado em memória"
        audit_path = tmp_path / "a.jsonl"

        def configure_sessions(self, manager):
            manager.add("nav", browser.AsyncBrowserSession(proxy="http://proxy.exemplo:3128"), lazy=True)

        async def start_requests(self):
            yield raspador.Request("https://ex.com/privado/x", sid="nav")

        async def parse(self, response):
            yield {"ok": True}

    assert S().start().items == []  # negado pelo robots, sem abrir o navegador
    rob = [r for r in fake.requests if r["url"].endswith("/robots.txt")][0]["final"]
    assert rob["proxy"] == "http://proxy.exemplo:3128"


# ---- M4: domínios bloqueados, anúncios, CDP local e histórico de rede ----


def test_dominio_bloqueado_e_subdominios_sao_abortados():
    bloqueados = frozenset({"rastreio.com"})
    assert browser.route_decision("https://cdn.rastreio.com/p.js", "script", "ex.com", False, bloqueados) == "abort"
    assert browser.route_decision("https://rastreio.com/p.js", "script", "ex.com", False, bloqueados) == "abort"
    assert browser.route_decision("https://outrorastreio.com/p.js", "script", "ex.com", False, bloqueados) == "continue"


def test_block_ads_usa_a_lista_do_upstream():
    dominios = browser.blocked_domains_for(block_ads=True, blocked_domains=None)
    assert len(dominios) > 3000 and "doubleclick.net" in dominios


@pytest.mark.parametrize(
    "url",
    [
        "ws://127.0.0.1:9222/devtools/browser/x",
        "http://localhost:9222",
        "http://192.168.0.10:9222",
        "http://[::1]:9222",
    ],
)
def test_cdp_local_e_aceito(url):
    browser.check_cdp_url(url)


@pytest.mark.parametrize("url", ["wss://chrome.provedor-de-scraping.example/?token=x", "ws://8.8.8.8:9222"])
def test_cdp_publico_e_recusado(url, monkeypatch):
    import raspador.http

    monkeypatch.setattr(raspador.http, "resolve", lambda host: ["34.120.0.1"])
    with pytest.raises(PolicyError) as exc:
        browser.check_cdp_url(url)
    assert exc.value.code == "RSP-P009"


def test_sessao_com_cdp_publico_nem_e_criada(monkeypatch):
    import raspador.http

    monkeypatch.setattr(raspador.http, "resolve", lambda host: ["34.120.0.1"])
    with pytest.raises(PolicyError):
        browser.BrowserSession(cdp_url="wss://remoto.example/x")


@chromium
def test_record_requests_guarda_a_api_por_tras_da_pagina(site):
    site({"https://ex.com/robots.txt": ROBOTS})
    html = """<html><body><div id="out"></div><script>
      fetch('/api/dados').then(r => r.json()).then(d => document.getElementById('out').textContent = d.nome)
    </script></body></html>"""

    def setup(page):
        def handler(route):
            if route.request.url.endswith("/api/dados"):
                route.fulfill(status=200, body='{"nome": "café"}', content_type="application/json")
            else:
                route.fulfill(status=200, body=html, content_type="text/html")

        page.route("**/*", handler)

    with browser.BrowserSession(record_requests=True) as b:
        r = b.fetch("https://ex.com/p", wait_selector="#out:not(:empty)", page_setup=setup)
        api = b.network.search(url_pattern=r"/api/dados$")
    assert r.css("#out::text").get() == "café"
    assert len(api) == 1 and api[0].json() == {"nome": "café"}


# ---- C4: Chromium real atrás de proxy com Basic auth ----


def _pode_abrir_porta_local() -> bool:
    import socket

    try:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
        return True
    except OSError:
        return False


localnet = pytest.mark.skipif(not _pode_abrir_porta_local(), reason="sandbox bloqueia porta local (EPERM)")

SENHA_PROXY = "s3nh@:/do-proxy"  # "@", ":" e "/" crus obrigam o percent-encoding e o unquote


class _ProxyComSenha:
    """Proxy HTTP de encaminhamento mínimo: 407 sem Proxy-Authorization correto; com ela, responde a página."""

    def __init__(self, usuario: str, senha: str) -> None:
        import base64
        import http.server
        import threading

        esperado = "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()
        self.vistos: list[dict] = []
        dono = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _autenticado(self) -> bool:
                auth = self.headers.get("Proxy-Authorization")
                dono.vistos.append({"metodo": self.command, "alvo": self.path, "ok": auth == esperado})
                if auth == esperado:
                    return True
                self.send_response(407)
                self.send_header("Proxy-Authenticate", 'Basic realm="raspador-teste"')
                self.send_header("Content-Length", "0")
                self.end_headers()
                return False

            def do_CONNECT(self):  # upgrade automático para HTTPS: recusa o túnel e o Chromium volta ao http
                if self._autenticado():
                    self.send_response(502)
                    self.send_header("Content-Length", "0")
                    self.end_headers()

            def do_GET(self):
                if not self._autenticado():
                    return
                corpo = b"<html><body><h1 id='via'>pelo proxy</h1></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)

            def log_message(self, format, *args):  # noqa: A002 (nome da assinatura da base)
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.porta = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def url(self, usuario: str, senha: str) -> str:
        from urllib.parse import quote

        return f"http://{quote(usuario, safe='')}:{quote(senha, safe='')}@127.0.0.1:{self.porta}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def proxy_com_senha():
    p = _ProxyComSenha("cliente-br", SENHA_PROXY)
    yield p
    p.close()


@chromium
@localnet
def test_chromium_real_autentica_no_proxy_e_a_senha_nao_vaza(site, proxy_com_senha, caplog, capfd):
    import logging

    site({"http://ex.com/robots.txt": ROBOTS})  # robots.txt vai pelo curl (falso aqui); a página, pelo Chromium
    with (
        caplog.at_level(logging.DEBUG),
        browser.BrowserSession(proxy=proxy_com_senha.url("cliente-br", SENHA_PROXY)) as b,
    ):
        r = b.fetch("http://ex.com/p")
    assert r.status == 200
    assert r.css("#via::text").get() == "pelo proxy"
    gets = [v for v in proxy_com_senha.vistos if v["metodo"] == "GET"]
    assert any(v["alvo"] == "http://ex.com/p" and v["ok"] for v in gets)  # passou pelo proxy, autenticado
    streams = capfd.readouterr()
    for texto in (caplog.text, streams.out, streams.err, repr(r.meta), repr(r.headers)):
        assert SENHA_PROXY not in texto and "s3nh%40" not in texto


@chromium
@localnet
def test_chromium_com_senha_errada_nao_abre_a_pagina_nem_mostra_a_senha(site, proxy_com_senha, caplog, capfd):
    import logging

    site({"http://ex.com/robots.txt": ROBOTS})
    errada = "senha-errada-123"
    erro = ""
    with caplog.at_level(logging.DEBUG), browser.BrowserSession(proxy=proxy_com_senha.url("cliente-br", errada)) as b:
        try:
            r = b.fetch("http://ex.com/p", timeout=10_000)
            assert r.status == 407 and r.css("#via").get() is None
        except AssertionError:
            raise
        except Exception as e:  # erro de navegação também serve: o que importa é não passar e não vazar
            erro = str(e)
    assert not any(v["ok"] for v in proxy_com_senha.vistos)
    streams = capfd.readouterr()
    for texto in (caplog.text, streams.out, streams.err, erro):
        assert errada not in texto
