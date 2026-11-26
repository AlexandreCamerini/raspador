"""Achados da revisão adversarial do ProxyPool v1 (R1–R11) e lacunas de teste apontadas nela."""

import json
import pickle
from collections import defaultdict
from urllib.parse import urlsplit

import pytest
from curl_cffi.requests import AsyncSession, Session
from scrapling.fetchers import FetcherSession

import raspador
from raspador import browser, http
from raspador.policy import InvalidProxy, PolicyError
from raspador.proxies import ProxyEntry, ProxyPool, affinity_key
from raspador.spiders import Spider

SEGREDO = "s3nh4-rev"
OK = (200, "User-agent: *\nAllow: /\n", {})


def _pool(**kw):
    return ProxyPool(
        [
            ProxyEntry(f"http://u1:{SEGREDO}@pa.proxy:8080", label="pa"),
            ProxyEntry(f"http://u2:{SEGREDO}@pb.proxy:8080", label="pb"),
            ProxyEntry(f"http://u3:{SEGREDO}@pc.proxy:8080", label="pc"),
        ],
        **kw,
    )


def _audit(tmp_path):
    caminho = tmp_path / "audit.jsonl"
    return [json.loads(linha) for linha in caminho.read_text().splitlines()] if caminho.exists() else []


def _proxies_por_site(fake):
    """{eTLD+1: {hosts de proxy}}: um site com dois proxies aparece aqui com tamanho 2 (o dict url->proxy escondia)."""
    out = defaultdict(set)
    for r in fake.requests:
        out[affinity_key(r["url"])].add(urlsplit(r["final"].get("proxy") or "").hostname)
    return dict(out)


def _spider(tmp_path, urls, pool=None, **attrs):
    attrs.setdefault("audit_path", tmp_path / "audit.jsonl")
    attrs.setdefault("proxy_pool", pool if pool is not None else _pool())
    attrs.setdefault("start_urls", urls)

    async def parse(self, response):
        yield {"url": response.url}
        for href in response.css("a::attr(href)").getall():
            yield response.follow(href)

    attrs.setdefault("parse", parse)
    return type("S", (Spider,), {"name": "rev", **attrs})


# --- R1 e R11: chave canônica ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "variante",
    [
        "https://müller.com/",
        "https://xn--mller-kva.com/",
        "https://MÜLLER.com/",
        "https://www.müller.com./",
        "https://müller。com/",
    ],
)
def test_r1_grafias_do_mesmo_site_dao_a_mesma_chave(variante):
    assert affinity_key(variante) == "xn--mller-kva.com"


def test_r1_fullwidth_vira_ascii():
    assert affinity_key("https://ｅｘ.com/") == "ex.com"


def test_r1_host_que_nao_converte_em_idna_e_recusado():
    with pytest.raises(ValueError):
        affinity_key("https://exa_mple..com/")


def test_r1_spider_com_duas_grafias_do_host_sai_por_um_proxy_so(site, tmp_path):
    fake = site(
        {
            "https://müller.com/robots.txt": OK,
            "https://xn--mller-kva.com/robots.txt": OK,
            "https://müller.com/": (200, '<a href="https://xn--mller-kva.com/b">b</a>', {}),
            "https://xn--mller-kva.com/b": (200, "<p>b</p>", {}),
        }
    )
    _spider(tmp_path, ["https://müller.com/"])().start()
    assert {len(v) for v in _proxies_por_site(fake).values()} == {1}
    assert sum(1 for r in fake.requests if r["url"].endswith("/b")) == 1


@pytest.mark.parametrize("numerico", ["http://1572395042/", "http://0x5d.0xb8.0xd8.0x22/", "http://93.184.216.34/"])
def test_r11_ipv4_em_qualquer_forma_vira_a_mesma_chave(numerico):
    assert affinity_key(numerico) == "93.184.216.34"


def test_r11_percent_encoding_no_host_e_recusado():
    with pytest.raises(http.InvalidURL):
        http.check_url("https://exa%6dple.com/")


# --- R2: navegador com pool, e robots de navegador sem passar pelo egress --------------------------------------------


def test_r2_pool_com_sessao_de_navegador_e_recusado(tmp_path):
    def configure_sessions(self, manager):
        manager.add("default", http.spider_session(), default=True)
        manager.add("nav", browser.AsyncBrowserSession(), lazy=True)

    with pytest.raises(PolicyError) as exc:
        _spider(tmp_path, ["https://ex.com/"], configure_sessions=configure_sessions)()
    assert exc.value.code == "RSP-P006" and exc.value.option == "proxy_pool"


def test_r2_robots_do_navegador_passa_pelo_egress_antes_de_sair(site, tmp_path):
    """Sem pool: ex.com já saiu direto pelo HTTP; o navegador (outro proxy) não pode buscar robots de sub.ex.com."""
    fake = site({"https://ex.com/robots.txt": OK, "https://ex.com/": (200, "<p>a</p>", {})})

    class S(Spider):
        name = "navrobots"
        audit_path = tmp_path / "audit.jsonl"

        def configure_sessions(self, manager):
            manager.add("default", http.spider_session(), default=True)
            manager.add("nav", browser.AsyncBrowserSession(proxy="http://nav.proxy:3128"), lazy=True)

        async def start_requests(self):
            yield raspador.Request("https://ex.com/")
            yield raspador.Request("https://sub.ex.com/x", sid="nav")

        async def parse(self, response):
            yield {"url": response.url}

    S().start()
    assert not any("sub.ex.com" in r["url"] for r in fake.requests)
    assert ("RSP-P006", "sid") in [(e.get("code"), e.get("detail")) for e in _audit(tmp_path)]


# --- R3, R4, R5, R6: o pool não abre o que a política fecha ----------------------------------------------------------


def test_r3_verify_false_por_request_com_pool_e_p010(site, tmp_path):
    fake = site({"https://ex.com/robots.txt": OK, "https://ex.com/": (200, "<p>a</p>", {})})

    async def start_requests(self):
        yield raspador.Request("https://ex.com/", verify=False)

    _spider(tmp_path, [], start_requests=start_requests)().start()
    assert not any(r["url"] == "https://ex.com/" for r in fake.requests)
    assert ("RSP-P010", "verify") in [(e.get("code"), e.get("detail")) for e in _audit(tmp_path)]


@pytest.mark.parametrize("url", ["socks4://h:1080", "socks4a://h:1080", "socks5://h:1080"])
def test_r4_pool_so_aceita_http_https_e_socks5h(url):
    with pytest.raises(PolicyError) as exc:
        ProxyEntry(url, label="s")
    assert exc.value.code == "RSP-P010"
    for ok in ("http://h:1", "https://h:1", "socks5h://h:1"):
        ProxyEntry(ok, label="s")


@pytest.mark.parametrize(
    "url",
    [
        "http://user:pa#ss@h:1",
        "socks5h://user:pa#ss@h:1",
        "http://user:pa/ss@h:1",
        "http://user:pa?ss@h:1",
        "http://h:1/caminho",
        "http://h:porta",
        "http://h:99999",
    ],
)
def test_r5_url_de_proxy_malformada_e_recusada_sem_mostrar_a_senha(url):
    with pytest.raises((InvalidProxy, PolicyError)) as exc:
        ProxyEntry(url, label="s")
    assert "pa#ss" not in str(exc.value) and "ss@" not in str(exc.value)
    with pytest.raises((InvalidProxy, PolicyError)):
        raspador.http_session(proxy=url)


def test_r5_senha_com_reservado_codificado_funciona():
    ProxyEntry("http://user:pa%23ss@h:1", label="s")


@pytest.mark.parametrize(
    "kwargs",
    [{"headers": {"Authorization": "Bearer T"}}, {"headers": {"cookie": "a=1"}}, {"cookies": {"a": "1"}}],
)
def test_r6_credencial_em_session_kwargs_do_pool_e_recusada(kwargs):
    with pytest.raises(PolicyError) as exc:
        _pool(session_kwargs=kwargs)
    assert exc.value.code == "RSP-P010"


# --- R7: FetcherSession crua com proxies, e trust_env -----------------------------------------------------------------


def test_r7_sessao_crua_com_proxies_e_recusada(tmp_path):
    class S(Spider):
        name = "crua"
        start_urls = ["https://ex.com/"]

        def configure_sessions(self, manager):
            manager.add(
                "a", FetcherSession(**http._session_config(None, {}), proxies={"https": "http://pa.proxy:8080"})
            )

        async def parse(self, response):
            yield None

    with pytest.raises(PolicyError) as exc:
        S()
    assert exc.value.code == "RSP-P006"


def test_r7_sessao_crua_tambem_ignora_no_proxy(monkeypatch):
    vistos = []

    def req(self, method, url, *a, **k):
        vistos.append(self.trust_env)
        raise RuntimeError("parar aqui")

    monkeypatch.setattr(Session, "request", req)

    class S(Spider):
        name = "crua2"
        start_urls = ["https://ex.com/"]

        def configure_sessions(self, manager):
            manager.add(
                "a", FetcherSession(**http._session_config(None, {"proxy": "http://pa.proxy:8080", "retries": 1}))
            )

        async def parse(self, response):
            yield None

    sessao = S()._session_manager.get("a")
    with sessao as cliente, pytest.raises(RuntimeError):
        cliente.get("https://ex.com/")
    assert vistos == [False]


# --- R8, R9: roteamento não altera o request do usuário ---------------------------------------------------------------


def test_r8_follow_de_url_ja_vista_nao_busca_de_novo(site, tmp_path):
    fake = site(
        {
            "https://ex.com/robots.txt": OK,
            "https://ex.com/": (200, '<a href="/x">x</a>', {}),
            "https://ex.com/x": (200, '<a href="/">home</a>', {}),
        }
    )
    _spider(tmp_path, ["https://ex.com/", "https://ex.com/x"])().start()
    assert sum(1 for r in fake.requests if r["url"] == "https://ex.com/x") == 1
    assert sum(1 for r in fake.requests if r["url"] == "https://ex.com/") == 1


def test_r9_sid_de_entrada_inexistente_e_roteado_pelo_pool(site, tmp_path):
    fake = site({"https://ex.com/robots.txt": OK, "https://ex.com/": (200, "<p>a</p>", {})})

    async def start_requests(self):
        yield raspador.Request("https://ex.com/", sid="proxy:removido")

    itens = _spider(tmp_path, [], start_requests=start_requests)().start().items
    assert itens == [{"url": "https://ex.com/"}]
    assert _proxies_por_site(fake) == {"ex.com": {f"{_pool().entry_for('https://ex.com/').label}.proxy"}}


# --- R10: mapa affinity -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mapa",
    [{"https://store.com": "pa"}, {"store.com/loja": "pa"}, {"*.ex.com": "pa"}, {"a.ex.com": "pa", "b.ex.com": "pb"}],
)
def test_r10_chave_de_affinity_malformada_ou_colidindo_e_recusada(mapa):
    with pytest.raises(ValueError):
        _pool(affinity=mapa)


# --- lacunas de teste: caminho de sucesso na costura do curl (meta, follow, checkpoint) ---------------------------


def test_meta_e_follow_com_pool_no_caminho_de_sucesso_real(monkeypatch, tmp_path):
    class Resp:
        status_code, reason, encoding, http_version = 200, "OK", "utf-8", 2
        headers: dict = {}
        cookies: dict = {}
        history: list = []
        request = None

        def __init__(self, url):
            self.url = url
            self.content = b"User-agent: *\nAllow: /\n" if url.endswith("robots.txt") else b'<a href="/b">b</a>'

    async def responde(self, m, url, *a, **k):
        return Resp(url)

    monkeypatch.setattr(Session, "request", lambda self, m, url, *a, **k: Resp(url))
    monkeypatch.setattr(AsyncSession, "request", responde)
    monkeypatch.setattr(raspador.http, "resolve", lambda host: ["93.184.216.34"])
    vistos = []

    async def parse(self, response):
        seguinte = response.follow("/b")
        vistos.append((repr(response.meta), pickle.dumps(seguinte.meta), pickle.dumps(seguinte._session_kwargs)))
        yield {"ok": True}

    _spider(tmp_path, ["https://ex.com/"], parse=parse)().start()
    assert vistos
    for meta, follow_meta, follow_kwargs in vistos:
        assert SEGREDO not in meta
        assert SEGREDO.encode() not in follow_meta + follow_kwargs


# --- verificação da revisão: o que ficou parcial e as regressões ---------------------------------------------------


@pytest.mark.parametrize("senha", ["pa'ss", 'pa"ss', "pa ss", "pa\tss", "pa<ss", "pa\\ss"])
def test_v_a5_senha_com_caractere_fora_do_userinfo_e_recusada(senha):
    url = f"http://user:{senha}@host:1"
    with pytest.raises(InvalidProxy) as exc:
        raspador.http_session(proxy=url)
    assert senha not in str(exc.value)
    with pytest.raises((InvalidProxy, PolicyError)):
        ProxyEntry(url, label="s")


def test_v_a5_meta_e_stats_usam_mascara_de_proxy():
    from raspador._redact import scrub_response

    class R:
        meta = {"proxy": "http://user:pa'ss@host:1"}

    assert scrub_response(R()).meta["proxy"] == "http://***@host:1"


@pytest.mark.parametrize("header", ["X-Api-Key", "X-Auth-Token", "Api-Key", "X-Custom"])
def test_v_a6_session_kwargs_do_pool_so_aceita_headers_da_allowlist(header):
    with pytest.raises(PolicyError) as exc:
        _pool(session_kwargs={"headers": {header: "SEGREDO"}})
    assert exc.value.code == "RSP-P010" and "SEGREDO" not in str(exc.value)
    _pool(session_kwargs={"headers": {"Accept": "text/html", "Accept-Language": "pt-BR"}})


def test_v_allowed_domains_com_idn_unicode_continua_casando(site, tmp_path):
    fake = site({"https://müller.com/robots.txt": OK, "https://müller.com/": (200, "<p>a</p>", {})})

    class S(Spider):
        name = "idn-allowed"
        start_urls = ["https://müller.com/"]
        allowed_domains = {"müller.com", "EX.com"}
        audit_path = tmp_path / "audit.jsonl"

        async def parse(self, response):
            yield {"url": response.url}

    assert len(S().start().items) == 1
    assert any(r["url"] == "https://müller.com/" for r in fake.requests)


def test_v_subclasse_de_fetchersession_e_recusada_ou_fixada(tmp_path):
    class Sub(FetcherSession):
        pass

    class S(Spider):
        name = "sub"
        start_urls = ["https://ex.com/"]

        def configure_sessions(self, manager):
            manager.add("a", Sub(**http._session_config(None, {})))

        async def parse(self, response):
            yield None

    with pytest.raises(PolicyError) as exc:
        S()
    assert exc.value.code == "RSP-P007"


@pytest.mark.parametrize("url", ["https://a..b.com/", "https://\xad.com/", "https://exa​mple.com/"])
def test_v_host_que_nao_canoniza_e_url_invalida(url):
    with pytest.raises(http.InvalidURL):
        http.check_url(url)
