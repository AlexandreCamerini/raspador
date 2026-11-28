"""Correções da auditoria de 2026-11-28 (SECURITY.md): sanitização, escrita no MCP, limites e permissões."""

import os
import stat

import pytest

from raspador.audit import AuditLog
from raspador.crawldir import UnsafeCrawldir, secure_crawldir
from raspador.mcp_server import build_server

ROBOTS = (200, "User-agent: *\nAllow: /\n", {})
OCULTO = (
    "<html><head><meta name='x' content='META-INJ'></head><body><main><h1>Visível</h1>"
    "<div hidden>HIDDEN-ATTR-INJ</div>"
    "<p hidden=''>HIDDEN-P-INJ</p>"
    "<input type='hidden' value='INPUT-INJ'>"
    "<p>texto\U000e0049\U000e0047\U000e004e normal\u202e invertido\u2066x\u2069</p>"
    "</main></body></html>"
)


def _texto(r):
    return "\n".join(c.text for c in r.content if getattr(c, "type", "") == "text")


async def _chamar(nome, args, **server_kw):
    from mcp import Client

    async with Client(build_server(**server_kw)) as c:
        return await c.call_tool(nome, args)


@pytest.fixture
def pagina(site):
    return site({"https://ex.com/robots.txt": ROBOTS, "https://ex.com/o": (200, OCULTO, {})})


# M1: conteúdo oculto que o sanitizador do upstream deixava passar
@pytest.mark.parametrize("fmt", ["markdown", "text", "html"])
async def test_mcp_remove_hidden_input_meta_e_caracteres_invisiveis(pagina, fmt):
    r = await _chamar("make_request", {"url": "https://ex.com/o", "format": fmt})
    assert not r.is_error, _texto(r)
    corpo = _texto(r)
    assert "Visível" in corpo and "normal" in corpo
    for marca in ("HIDDEN-ATTR-INJ", "HIDDEN-P-INJ", "INPUT-INJ", "META-INJ"):
        assert marca not in corpo, (fmt, marca)
    for ch in ("\U000e0049", "\u202e", "\u2066", "\u2069"):
        assert ch not in corpo, (fmt, hex(ord(ch)))


# M7: o modelo não escreve em sites de terceiros sem o usuário liberar
@pytest.mark.parametrize("metodo", ["POST", "PUT", "DELETE"])
async def test_mcp_recusa_escrita_por_padrao(pagina, metodo):
    r = await _chamar("make_request", {"url": "https://ex.com/o", "method": metodo})
    assert r.is_error
    assert "RSP-M006" in _texto(r) and "--allow-write" in _texto(r)
    assert all(req["method"] == "GET" for req in pagina.requests)  # nada além do robots.txt saiu


async def test_mcp_recusa_escrita_tambem_na_sessao(pagina):
    from mcp import Client

    async with Client(build_server()) as c:
        import json

        sid = json.loads(_texto(await c.call_tool("open_request_session", {})))["session_id"]
        r = await c.call_tool("session_make_request", {"session_id": sid, "url": "https://ex.com/o", "method": "POST"})
        assert r.is_error and "RSP-M006" in _texto(r)
        await c.call_tool("close_session", {"session_id": sid})


async def test_mcp_permite_escrita_com_allow_write(pagina):
    r = await _chamar("make_request", {"url": "https://ex.com/o", "method": "POST", "data": "a=1"}, allow_write=True)
    assert not r.is_error, _texto(r)
    assert pagina.requests[-1]["method"] == "POST"


def test_cli_mcp_tem_allow_write():
    from click.testing import CliRunner

    from raspador.cli import main

    assert "--allow-write" in CliRunner().invoke(main, ["mcp", "--help"]).stdout


# M3: limites que o modelo não pode desligar
@pytest.mark.parametrize(
    "args",
    [
        {"max_chars": 0},
        {"max_chars": 10_000_000},
        {"timeout": 0},
        {"timeout": 100_000},
    ],
)
async def test_mcp_recusa_limites_fora_da_faixa(pagina, args):
    r = await _chamar("make_request", {"url": "https://ex.com/o", **args})
    assert r.is_error
    assert pagina.requests == []


async def test_mcp_limita_sessoes_http_abertas(site):
    from mcp import Client

    from raspador.mcp_server import MAX_HTTP_SESSIONS

    async with Client(build_server()) as c:
        for _ in range(MAX_HTTP_SESSIONS):
            assert not (await c.call_tool("open_request_session", {})).is_error
        r = await c.call_tool("open_request_session", {})
        assert r.is_error and "RSP-M004" in _texto(r)


# M4: o checkpoint guarda headers e cookies do site; o diretório não pode ser legível por outros
@pytest.mark.parametrize("modo", [0o750, 0o705, 0o755])
def test_crawldir_legivel_por_outros_e_recusado(tmp_path, modo):
    d = tmp_path / "crawl"
    d.mkdir()
    d.chmod(modo)
    with pytest.raises(UnsafeCrawldir, match="leitura"):
        secure_crawldir(d)


def test_crawldir_0700_existente_continua_aceito(tmp_path):
    d = tmp_path / "crawl"
    d.mkdir()
    d.chmod(0o700)
    assert secure_crawldir(d) == d.resolve()


# B2: auditoria só para o dono
def test_audit_jsonl_nasce_0600(tmp_path):
    caminho = tmp_path / "audit.jsonl"
    old = os.umask(0o022)
    try:
        AuditLog(caminho, run_id="r1", spider="s").record("robots_denied", url="https://ex.com/a")
    finally:
        os.umask(old)
    assert stat.S_IMODE(caminho.stat().st_mode) == 0o600


# B4: --report json não devolve credencial da URL
def test_report_json_mascara_credencial_na_url(site, tmp_path):
    import json

    from click.testing import CliRunner

    from raspador.cli import main

    site({"https://ex.com/robots.txt": (200, "User-agent: *\nDisallow: /\n", {})})
    r = CliRunner().invoke(main, ["get", "https://u:SENHA@ex.com/a", str(tmp_path / "o.txt"), "--report", "json"])
    assert "SENHA" not in r.stdout
    assert json.loads(r.stdout.strip().splitlines()[-1])["ok"] is False
