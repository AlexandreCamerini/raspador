"""Credencial de proxy (ou de URL) nunca sai em mensagem, log, relatório ou auditoria."""

import json
import logging

from click.testing import CliRunner

from raspador.audit import AuditLog
from raspador.cli import main
from raspador.policy import PolicyError
from raspador.spiders import Spider

SEGREDO = "s3nh4-do-proxy"
PROXY = f"http://cliente-br:{SEGREDO}@proxy.exemplo:8080"
ROBOTS_OK = (200, "User-agent: *\nAllow: /\n", {})


def _cli(*args, env=None):
    return CliRunner(env={"NO_COLOR": "1", **(env or {})}).invoke(main, list(args))


def test_policy_error_mascara_credencial_e_mantem_o_host():
    texto = str(PolicyError("RSP-P006", "proxy", PROXY, "motivo", "alternativa"))
    assert SEGREDO not in texto and "cliente-br" not in texto
    assert "proxy.exemplo:8080" in texto


def test_policy_error_mascara_credencial_dentro_de_dict():
    texto = str(PolicyError("RSP-P006", "proxies", {"https": PROXY}, "m", "a"))
    assert SEGREDO not in texto


def test_proxy_por_request_no_spider_nao_vaza_no_log_nem_na_auditoria(site, tmp_path, caplog, capfd):
    site({"https://ex.com/robots.txt": ROBOTS_OK, "https://ex.com/": (403, "", {})})

    class S(Spider):
        name = "segredo"
        start_urls = ["https://ex.com/"]
        max_blocked_retries = 1
        audit_path = tmp_path / "audit.jsonl"

        async def retry_blocked_request(self, request, response):
            request._session_kwargs["proxy"] = PROXY
            return request

        async def parse(self, response):
            yield {"ok": True}

    with caplog.at_level(logging.DEBUG):
        S().start()
    streams = capfd.readouterr()
    auditoria = (tmp_path / "audit.jsonl").read_text()
    assert "RSP-P006" in auditoria  # o teste só vale se a recusa aconteceu
    tudo = caplog.text + streams.out + streams.err + auditoria
    i = tudo.find(SEGREDO)
    assert i < 0, tudo[max(0, i - 200) : i + 40]


def test_auditoria_tira_credencial_da_url_do_alvo(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl", run_id="r")
    log.record("robots_denied", url=f"https://u:{SEGREDO}@ex.com/a", domain="ex.com")
    linha = json.loads((tmp_path / "a.jsonl").read_text())
    assert SEGREDO not in linha["url"] and linha["url"] == "https://ex.com/a"


def _rede_cai_citando_o_proxy(monkeypatch):
    from curl_cffi import CurlError

    import raspador.http as h

    def cai(*a, **k):
        raise CurlError(f"Failed to connect to proxy {PROXY}: Connection refused")

    monkeypatch.setattr(h, "get", cai)


def test_cli_verbosa_nao_vaza_credencial_do_proxy(monkeypatch, tmp_path):
    _rede_cai_citando_o_proxy(monkeypatch)
    r = _cli("get", "https://ex.com/p", str(tmp_path / "x.md"), "--proxy", PROXY, "-v")
    assert r.exit_code == 5
    assert SEGREDO not in r.stderr and SEGREDO not in r.stdout
    assert "proxy.exemplo:8080" in r.stderr  # o detalhe continua útil


def test_cli_report_json_nao_vaza_credencial_do_proxy(monkeypatch, tmp_path):
    _rede_cai_citando_o_proxy(monkeypatch)
    r = _cli("get", "https://ex.com/p", str(tmp_path / "x.md"), "--proxy", PROXY, "--report", "json", "-v")
    assert SEGREDO not in r.stdout + r.stderr


def test_cli_aceita_proxy_por_variavel_de_ambiente_e_ajuda_nao_sugere_senha(site, tmp_path):
    fake = site({"https://ex.com/robots.txt": ROBOTS_OK, "https://ex.com/p": (200, "<p>ok</p>", {})})
    r = _cli("get", "https://ex.com/p", str(tmp_path / "x.md"), env={"RASPADOR_PROXY": PROXY})
    assert r.exit_code == 0, r.stderr
    assert {req["final"].get("proxy") for req in fake.requests} == {PROXY}  # página e robots.txt
    ajuda = _cli("get", "--help").output
    assert "senha" not in ajuda and "RASPADOR_PROXY" in ajuda


def test_proxies_em_dict_por_request_tambem_e_p006(site, tmp_path):
    site({"https://ex.com/robots.txt": ROBOTS_OK, "https://ex.com/": (403, "", {})})

    class S(Spider):
        name = "proxies"
        start_urls = ["https://ex.com/"]
        max_blocked_retries = 1
        audit_path = tmp_path / "audit.jsonl"

        async def retry_blocked_request(self, request, response):
            request._session_kwargs["proxies"] = {"https": PROXY}
            return request

        async def parse(self, response):
            yield {"ok": True}

    resultado = S().start()
    erros = [json.loads(linha) for linha in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert [(e["code"], e["detail"]) for e in erros if e["event"] == "policy_error"] == [("RSP-P006", "proxies")]
    assert SEGREDO not in json.dumps(resultado.stats.to_dict(), default=str)
