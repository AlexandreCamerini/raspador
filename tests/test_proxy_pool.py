"""ProxyPool v1: afinidade estática por domínio registrável, sem failover (replica/plano-seguranca-proxypool.md).

Os ids A## são os critérios de aceite do plano.
"""

import json
import logging

import pytest
from curl_cffi import CurlError
from curl_cffi.requests import AsyncSession, Session

import raspador
from raspador import http
from raspador.policy import InvalidProxy, PolicyError
from raspador.proxies import ProxyEntry, ProxyPool, affinity_key
from raspador.spiders import Spider

SEGREDO = "s3nh4-do-pool"
OK = (200, "User-agent: *\nAllow: /\n", {})


def _pool(**kw):
    return ProxyPool(
        [
            ProxyEntry(f"http://u1:{SEGREDO}@br1.proxy:8080", label="br-1", group="br"),
            ProxyEntry(f"http://u2:{SEGREDO}@br2.proxy:8080", label="br-2", group="br"),
            ProxyEntry(f"http://u3:{SEGREDO}@us1.proxy:8080", label="us-1", group="us"),
        ],
        **({"default_group": "br"} | kw),
    )


def _audit(tmp_path):
    return [json.loads(linha) for linha in (tmp_path / "audit.jsonl").read_text().splitlines()]


def _proxy_host(final):
    from urllib.parse import urlsplit

    return urlsplit(final.get("proxy") or "").hostname


def _um_proxy_por_url(fake):
    """{url: proxy_host}, falhando se a mesma URL saiu por dois proxies (o dict sozinho guardaria só o último)."""
    out: dict = {}
    for r in fake.requests:
        host = _proxy_host(r["final"])
        assert out.setdefault(r["url"], host) == host, (r["url"], out[r["url"]], host)
    return out


# --- chave e atribuição -------------------------------------------------------------------------------------------


def test_a20_variantes_de_host_viram_a_mesma_chave():
    chaves = {
        affinity_key(u) for u in ("https://EX.com/", "https://ex.com:443/a", "https://ex.com./", "https://a.ex.com/")
    }
    assert chaves == {"ex.com"}
    assert affinity_key("https://loja.com.br/") == "loja.com.br"
    assert affinity_key("https://b.ex.co.uk/") == "ex.co.uk"
    assert affinity_key("https://fulano.github.io/") == "fulano.github.io"  # sufixo privado: sites distintos
    assert affinity_key("http://10.0.0.1:8080/") == "10.0.0.1"


def test_a1_a2_mesmo_dominio_mesma_entrada_e_estavel_entre_instancias():
    p1, p2 = _pool(), _pool()
    urls = [f"https://{s}ex.com/p{i}" for i in range(50) for s in ("", "a.", "B.")]
    assert len({p1.entry_for(u).label for u in urls}) == 1
    assert {u: p1.entry_for(u).label for u in urls} == {u: p2.entry_for(u).label for u in urls}


def test_atribuicao_espalha_dominios_dentro_do_grupo_padrao():
    p = _pool()
    labels = {p.entry_for(f"https://site{i}.com/").label for i in range(40)}
    assert labels == {"br-1", "br-2"}  # nunca us-1: fora do grupo padrão


def test_rendezvous_remover_uma_entrada_so_move_os_dominios_dela():
    antes = _pool()
    depois = ProxyPool(
        [
            ProxyEntry(f"http://u1:{SEGREDO}@br1.proxy:8080", label="br-1", group="br"),
            ProxyEntry(f"http://u3:{SEGREDO}@us1.proxy:8080", label="us-1", group="us"),
        ],
        default_group="br",
    )
    for i in range(40):
        u = f"https://site{i}.com/"
        if antes.entry_for(u).label == "br-1":
            assert depois.entry_for(u).label == "br-1"


def test_mapa_explicito_por_label_e_por_grupo():
    p = _pool(affinity={"store.com": "us", "loja.com.br": "br-2"})
    assert p.entry_for("https://www.store.com/x").label == "us-1"
    assert p.entry_for("https://loja.com.br/").label == "br-2"


# --- validação na construção ---------------------------------------------------------------------------------------


def test_construcao_valida_entradas_mapa_e_grupo():
    with pytest.raises(ValueError):
        ProxyPool([])
    with pytest.raises(ValueError):  # label repetido
        ProxyPool([ProxyEntry("http://a:1", label="x"), ProxyEntry("http://b:1", label="x")])
    with pytest.raises(ValueError):  # mapa aponta para label/grupo inexistente
        _pool(affinity={"ex.com": "jp"})
    with pytest.raises(ValueError):  # vários grupos sem grupo padrão
        ProxyPool([ProxyEntry("http://a:1", label="a", group="g1"), ProxyEntry("http://b:1", label="b", group="g2")])
    with pytest.raises(InvalidProxy):
        ProxyEntry("u:p@host:1", label="sem-esquema")


def test_a13_pool_recusa_socks5_com_dns_local_e_verify_desligado():
    with pytest.raises(PolicyError) as exc:
        ProxyEntry("socks5://host:1080", label="s")
    assert exc.value.code == "RSP-P010"
    ProxyEntry("socks5h://host:1080", label="s")
    with pytest.raises(PolicyError) as exc:
        _pool(session_kwargs={"verify": False})
    assert exc.value.code == "RSP-P010"
    with pytest.raises(PolicyError):
        _pool(session_kwargs={"impersonate": "chrome"})


def test_a11_repr_e_str_nunca_mostram_url():
    p = _pool()
    texto = repr(p) + str(p) + repr(p.entry_for("https://ex.com/")) + str(p.entry_for("https://ex.com/"))
    assert SEGREDO not in texto and "br1.proxy" not in texto
    assert "br-1" in texto or "br-2" in texto


# --- integração com o Spider ---------------------------------------------------------------------------------------


def _spider(tmp_path, pool, urls, **attrs):
    class S(Spider):
        name = "pool"
        start_urls = urls
        proxy_pool = pool
        audit_path = tmp_path / "audit.jsonl"

        async def parse(self, response):
            yield {"url": response.url}

    for k, v in attrs.items():
        setattr(S, k, v)
    return S


def test_spider_roteia_pagina_e_robots_pelo_proxy_do_dominio(site, tmp_path):
    pool = _pool(affinity={"us.ex": "us"})
    fake = site(
        {
            "https://br.ex/robots.txt": OK,
            "https://us.ex/robots.txt": OK,
            "https://br.ex/": (200, "<p>br</p>", {}),
            "https://us.ex/": (200, "<p>us</p>", {}),
        }
    )
    itens = _spider(tmp_path, pool, ["https://br.ex/", "https://us.ex/"])().start().items
    assert len(itens) == 2
    por_url = _um_proxy_por_url(fake)
    esperado_br = pool.entry_for("https://br.ex/").label.replace("-", "") + ".proxy"
    assert por_url["https://us.ex/"] == por_url["https://us.ex/robots.txt"] == "us1.proxy"
    assert por_url["https://br.ex/"] == por_url["https://br.ex/robots.txt"] == esperado_br
    atribuidos = [(e["domain"], e["label"]) for e in _audit(tmp_path) if e["event"] == "proxy_assigned"]
    assert sorted(atribuidos) == sorted([("br.ex", pool.entry_for("https://br.ex/").label), ("us.ex", "us-1")])


def test_a3_pool_nao_cria_limiter_por_proxy(site, tmp_path):
    """Escopo honesto: prova que o pool não muda o ritmo configurado nem a chave do limiter do upstream (netloc do
    request, não o proxy). O limiter ainda ser por netloc cru é limite declarado da v1."""
    from scrapling.spiders.engine import CrawlerEngine

    site({"https://ex.com/robots.txt": OK, "https://ex.com/": (200, "<p>a</p>", {})})
    chaves = []
    original = CrawlerEngine._rate_limiter

    def espia(self, domain):
        chaves.append(domain)
        return original(self, domain)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(CrawlerEngine, "_rate_limiter", espia)
        s = _spider(tmp_path, _pool(), ["https://ex.com/"])()
        assert s.concurrent_requests_per_domain == 1 and s.download_delay == 1.0
        s.start()
    assert chaves and set(chaves) == {"ex.com"}


def test_a15_proxy_por_request_continua_p006_com_pool(site, tmp_path):
    site({"https://ex.com/robots.txt": OK, "https://ex.com/": (403, "", {})})

    async def troca(self, request, response):
        request._session_kwargs["proxy"] = "http://outro.proxy:8080"
        return request

    _spider(tmp_path, _pool(), ["https://ex.com/"], max_blocked_retries=1, retry_blocked_request=troca)().start()
    assert "RSP-P006" in [e.get("code") for e in _audit(tmp_path) if e["event"] == "policy_error"]


def test_pool_e_sessao_http_com_proxy_proprio_nao_convivem(tmp_path):
    class S(Spider):
        name = "conflito"
        start_urls = ["https://ex.com/"]
        proxy_pool = _pool()

        def configure_sessions(self, manager):
            manager.add("default", http.spider_session(proxy="http://outro.proxy:8080"))

        async def parse(self, response):
            yield None

    with pytest.raises(PolicyError) as exc:
        S()
    assert exc.value.code == "RSP-P006"


def test_redirect_para_outro_dominio_troca_para_o_proxy_do_destino(site, tmp_path):
    pool = _pool(affinity={"us.ex": "us", "br.ex": "br-1"})
    fake = site(
        {
            "https://br.ex/robots.txt": OK,
            "https://us.ex/robots.txt": OK,
            "https://br.ex/r": (302, "", {"location": "https://us.ex/fim"}),
            "https://us.ex/fim": (200, "<p>fim</p>", {}),
        }
    )
    _spider(tmp_path, pool, ["https://br.ex/r"], allowed_domains={"br.ex", "us.ex"})().start()
    por_url = _um_proxy_por_url(fake)
    assert por_url["https://br.ex/r"] == "br1.proxy"
    assert por_url["https://us.ex/fim"] == "us1.proxy"


# --- costura do curl: fail closed e varredura de segredo (A9, A11, A23) ---------------------------------------------


def test_a9_a23_proxy_morto_falha_fechado_sem_conexao_direta_e_sem_vazar(tmp_path, monkeypatch, caplog, capfd):
    vistos = []

    def cai(self, method, url, *a, **k):
        vistos.append((url, k.get("proxy"), self.trust_env))
        raise CurlError("Failed to connect to br1.proxy port 8080: Connection refused")

    async def cai_async(self, method, url, *a, **k):
        return cai(self, method, url, *a, **k)

    monkeypatch.setattr(Session, "request", cai)
    monkeypatch.setattr(AsyncSession, "request", cai_async)
    monkeypatch.setattr(raspador.http, "resolve", lambda host: ["93.184.216.34"])
    monkeypatch.setenv("NO_PROXY", "ex.com")
    with caplog.at_level(logging.DEBUG):
        resultado = _spider(tmp_path, _pool(), ["https://ex.com/"])().start()
    assert resultado.items == []
    assert vistos, "o transporte precisa ter sido chamado"
    assert all(proxy and trust_env is False for _, proxy, trust_env in vistos)  # nunca direto
    streams = capfd.readouterr()
    tudo = caplog.text + streams.out + streams.err + (tmp_path / "audit.jsonl").read_text()
    tudo += json.dumps(resultado.stats.to_dict(), default=str)
    assert SEGREDO not in tudo


def test_a14_nenhuma_ferramenta_mcp_aceita_proxy():
    pytest.importorskip("mcp")
    import asyncio

    from mcp import Client

    from raspador.mcp_server import build_server

    async def schemas():
        async with Client(build_server()) as c:
            return [t.input_schema for t in (await c.list_tools()).tools]

    for schema in asyncio.run(schemas()):
        assert not {"proxy", "proxy_pool", "proxies"} & set(schema.get("properties", {}))
