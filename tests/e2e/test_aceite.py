"""Testes de aceite por fluxo (replica/test-plan.md). Casos novos desta rodada; os demais vivem nos testes de
módulo citados no plano. IDs no nome: F01-E1 -> test_f01_e1_..."""

import json

import pytest
from click.testing import CliRunner

import raspador
from raspador.cli import main

ROBOTS_OK = (200, "User-agent: *\nAllow: /", {})
INVALIDAS = ["", "ex.com/p", "file:///etc/passwd", "ftp://ex.com/arquivo", "javascript:alert(1)", "https:///sem-host"]


def _cli(*args):
    return CliRunner(env={"NO_COLOR": None}).invoke(main, list(args))


# ---- F01 ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("url", INVALIDAS)
def test_f01_e1_e2_e3_url_invalida_e_recusada_antes_da_rede(site, url):
    from raspador.http import InvalidURL

    fake = site({"https://ex.com/robots.txt": ROBOTS_OK})
    with pytest.raises(InvalidURL) as exc:
        raspador.get(url)
    assert exc.value.code == "RSP-U001"
    assert fake.requests == []


def test_f01_e4_acentos_e_emoji_intactos(site):
    site({"https://ex.com/robots.txt": ROBOTS_OK, "https://ex.com/p": (200, "<h1>Promoção ☕ São João</h1>", {})})
    assert raspador.get("https://ex.com/p").css("h1::text").get() == "Promoção ☕ São João"


def test_f01_e5_url_muito_longa(site):
    url = "https://ex.com/p?q=" + "a" * 10_000
    site({"https://ex.com/robots.txt": ROBOTS_OK, url: (200, "<p>ok</p>", {})})
    assert raspador.get(url).status == 200


def test_f01_e6_rede_fora_do_ar_na_cli(monkeypatch, tmp_path):
    from curl_cffi.requests.exceptions import DNSError

    import raspador.http as h

    def sem_rede(*a, **k):
        raise DNSError("Could not resolve host")

    monkeypatch.setattr(h, "get", sem_rede)
    r = _cli("get", "https://nao-existe.example/", str(tmp_path / "x.md"))
    assert r.exit_code == 5 and "RSP-N001" in r.stderr


def test_f01_n3_headers_como_texto_da_erro_claro(site):
    site({"https://ex.com/robots.txt": ROBOTS_OK})
    with pytest.raises(TypeError) as exc:
        raspador.get("https://ex.com/p", headers="User-Agent: x")
    assert "dict" in str(exc.value)


def test_f01_n4_redirect_para_file_nao_e_seguido(site):
    from raspador.http import InvalidURL

    fake = site(
        {"https://ex.com/robots.txt": ROBOTS_OK, "https://ex.com/r": (302, "", {"location": "file:///etc/hosts"})}
    )
    with pytest.raises(InvalidURL):
        raspador.get("https://ex.com/r")
    assert not any(u.startswith("file:") for u in fake.urls())


# ---- F02 / F03 ----------------------------------------------------------------------------------------------


def test_f02_e1_file_no_navegador_recusado_antes_de_abrir():
    from raspador import browser
    from raspador.http import InvalidURL

    sessao = browser.BrowserSession()  # não entra no `with`: o erro tem de vir antes de qualquer Chromium
    with pytest.raises(InvalidURL):
        sessao.fetch("file:///etc/passwd")


def test_f03_n1_estado_inexistente_falha_na_construcao(tmp_path):
    from raspador import browser
    from raspador.browser import StateFileMissing

    with pytest.raises(StateFileMissing) as exc:
        browser.BrowserSession(storage_state=tmp_path / "nao-existe.json")
    assert exc.value.code == "RSP-F004"


# ---- F06 ----------------------------------------------------------------------------------------------------


def _base(tmp_path):
    from raspador.spiders import Spider

    class Base(Spider):
        name = "aceite"
        download_delay = 0.0
        autothrottle_enabled = False
        policy_override = "teste automatizado em memória"
        audit_path = tmp_path / "audit.jsonl"

    return Base


def test_f06_e1_start_url_file_descartada_e_auditada(site, tmp_path):
    fake = site({"https://ex.com/robots.txt": ROBOTS_OK, "https://ex.com/": (200, "<h1>ok</h1>", {})})

    class S(_base(tmp_path)):
        start_urls = ["file:///etc/hosts", "https://ex.com/"]

        async def parse(self, response):
            yield {"h1": response.css("h1::text").get()}

    r = S().start()
    assert r.items == [{"h1": "ok"}]
    assert not any(u.startswith("file:") for u in fake.urls())
    assert r.stats.robots_disallowed_count == 0
    assert _eventos(tmp_path) == [("policy_error", "RSP-U001", "file:///etc/hosts")]


def _eventos(tmp_path):
    linhas = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    return [(e["event"], e.get("code"), e.get("url")) for e in linhas if e["event"] != "policy_override"]


def test_f06_e3_links_mailto_tel_javascript_nao_viram_robots_negado(site, tmp_path):
    html = '<h1>ok</h1><a href="mailto:a@b.com">m</a><a href="tel:+551199">t</a><a href="javascript:void(0)">j</a>'
    fake = site({"https://ex.com/robots.txt": ROBOTS_OK, "https://ex.com/": (200, html, {})})

    class S(_base(tmp_path)):
        start_urls = ["https://ex.com/"]

        async def parse(self, response):
            yield {"h1": response.css("h1::text").get()}
            for href in response.css("a::attr(href)").getall():
                yield response.follow(href)

    r = S().start()
    assert fake.urls() == ["https://ex.com/robots.txt", "https://ex.com/"]
    assert r.stats.robots_disallowed_count == 0
    assert _eventos(tmp_path) == [
        ("policy_error", "RSP-U001", "mailto:a@b.com"),
        ("policy_error", "RSP-U001", "tel:+551199"),
        ("policy_error", "RSP-U001", "javascript:void(0)"),
    ]


def test_f06_e2_executar_duas_vezes_da_o_mesmo_resultado(site, tmp_path):
    site({"https://ex.com/robots.txt": ROBOTS_OK, "https://ex.com/": (200, "<h1>a</h1><h1>b</h1>", {})})

    class S(_base(tmp_path)):
        start_urls = ["https://ex.com/"]

        async def parse(self, response):
            for t in response.css("h1::text").getall():
                yield {"t": t}

    assert S().start().items == S().start().items == [{"t": "a"}, {"t": "b"}]


# ---- F10 ----------------------------------------------------------------------------------------------------


def test_f10_e1_seletor_invalido_e_erro_de_uso(site, tmp_path):
    site({"https://ex.com/robots.txt": ROBOTS_OK, "https://ex.com/p": (200, "<h1>x</h1>", {})})
    r = _cli("get", "https://ex.com/p", str(tmp_path / "x.md"), "-s", "[[")
    assert r.exit_code == 2
    assert "RSP-U002" in r.stderr and "Traceback" not in r.stderr


def test_f10_e2_diretorio_de_saida_inexistente(site, tmp_path):
    site({"https://ex.com/robots.txt": ROBOTS_OK, "https://ex.com/p": (200, "<h1>x</h1>", {})})
    r = _cli("get", "https://ex.com/p", str(tmp_path / "nao" / "existe" / "x.md"))
    assert r.exit_code == 7 and "RSP-F003" in r.stderr


def test_f10_e3_url_file_na_cli(site):
    site({})
    r = _cli("get", "file:///etc/hosts", "-")
    assert r.exit_code == 2 and "RSP-U001" in r.stderr and r.stdout == ""


# ---- F11 ----------------------------------------------------------------------------------------------------


async def _mcp(name, args):
    from mcp import Client

    from raspador.mcp_server import build_server

    async with Client(build_server()) as c:
        r = await c.call_tool(name, args)
    return r.is_error, "\n".join(getattr(x, "text", "") for x in r.content)


@pytest.mark.parametrize("url", ["file:///etc/hosts", "", "ftp://ex.com/x"])
async def test_f11_n2_mcp_recusa_url_invalida(site, url):
    fake = site({})
    erro, texto = await _mcp("make_request", {"url": url})
    assert erro and "RSP-U001" in texto
    assert fake.requests == []


async def test_f11_n3_mcp_seletor_invalido_e_erro_de_ferramenta(site):
    site({"https://ex.com/robots.txt": ROBOTS_OK, "https://ex.com/p": (200, "<h1>x</h1>", {})})
    erro, texto = await _mcp("make_request", {"url": "https://ex.com/p", "css_selector": "[["})
    assert erro and "RSP-U002" in texto


@pytest.mark.parametrize("args", [{"url_pattern": "["}, {"limit": 0}])
async def test_f04_n1_mcp_filtro_de_rede_invalido_e_erro_de_ferramenta(monkeypatch, args):
    from mcp import Client

    import raspador.mcp_server as m
    from raspador import browser
    from raspador.mcp_server import build_server

    async def falso_aenter(self):
        self.network = browser._recorder(True, 10, asynchronous=True)
        self._is_alive = True
        return self

    async def falso_aexit(self, *a):
        self._is_alive = False

    monkeypatch.setattr(m.AsyncBrowserSession, "__aenter__", falso_aenter)
    monkeypatch.setattr(m.AsyncBrowserSession, "__aexit__", falso_aexit)
    async with Client(build_server()) as c:
        aberta = await c.call_tool("browser_open", {"record_requests": True})
        sid = json.loads(aberta.content[0].text)["session_id"]
        r = await c.call_tool("browser_network_requests", {"session_id": sid, **args})
    texto = "\n".join(getattr(x, "text", "") for x in r.content)
    assert r.is_error and "RSP-M005" in texto
