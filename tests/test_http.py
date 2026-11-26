"""Fábricas HTTP: o que a sessão do raspador configura e o que ela envia."""

import json
import socket

import pytest

import raspador
from raspador.audit import AuditLog
from raspador.policy import PolicyError, check_session


def _pode_abrir_porta_local() -> bool:
    try:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
        return True
    except OSError:
        return False


localnet = pytest.mark.skipif(not _pode_abrir_porta_local(), reason="sandbox bloqueia porta local (EPERM)")


def test_sessao_de_spider_nasce_compliant():
    sessao = raspador.http.spider_session(contact="mailto:eu@exemplo.com")
    check_session(sessao)
    assert sessao._default_headers["User-Agent"] == "raspador/0.1.0 (+mailto:eu@exemplo.com)"


def test_fabrica_rejeita_opcao_de_evasao_na_criacao():
    with pytest.raises(PolicyError):
        raspador.http_session(impersonate="chrome")
    with pytest.raises(PolicyError):
        raspador.http.spider_session(headers={"User-Agent": "Mozilla/5.0"})


def test_sessao_guardada_rejeita_kwarg_por_requisicao_antes_da_rede():
    with raspador.http_session() as s, pytest.raises(PolicyError) as exc:
        s.get("https://exemplo.invalid/", impersonate="chrome")
    assert exc.value.code == "RSP-P002"


def test_get_avulso_rejeita_kwarg_antes_da_rede():
    with pytest.raises(PolicyError):
        raspador.get("https://exemplo.invalid/", ja3="771")


async def test_sessao_assincrona_rejeita_kwarg_antes_da_rede():
    async with raspador.async_http_session() as s:
        with pytest.raises(PolicyError):
            await s.get("https://exemplo.invalid/", headers={"Sec-Ch-Ua": "x"})


def test_log_de_auditoria_grava_jsonl_em_utc_sem_query(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", run_id="r1", spider="s")
    log.record("robots_denied", url="https://ex.com/a?token=segredo", domain="ex.com")
    linha = json.loads((tmp_path / "audit.jsonl").read_text().strip())
    assert linha["event"] == "robots_denied"
    assert linha["url"] == "https://ex.com/a"
    assert linha["ts"].endswith("Z")
    assert linha["run_id"] == "r1"


@localnet
def test_headers_enviados_identificam_o_raspador_e_nada_mais(httpserver):
    recebidos = {}

    def handler(request):
        from werkzeug import Response

        recebidos.update({k.lower(): v for k, v in request.headers.items()})
        return Response("ok")

    # sem robots.txt declarado o servidor de teste responde 500, que o raspador trata como "tudo negado"
    httpserver.expect_request("/robots.txt").respond_with_data("", status=404)
    httpserver.expect_request("/").respond_with_handler(handler)
    r = raspador.get(httpserver.url_for("/"))
    assert r.status == 200
    assert recebidos["user-agent"].startswith("raspador/")
    assert not any(k.startswith(("sec-ch-ua", "sec-fetch-")) for k in recebidos)
    assert "referer" not in recebidos


def test_get_avulso_ponta_a_ponta_offline_identifica_e_extrai(monkeypatch):
    """F01 sem rede: troca só o transporte síncrono e aplica o merge real do upstream."""
    from scrapling.engines.static import _SyncSessionLogic
    from scrapling.engines.toolbelt.custom import Response

    enviado = {}

    def _patched(self, method, stealth=None, **kwargs):
        merge = dict(kwargs) | ({"stealth": stealth} if stealth is not None else {})
        enviado.update(self._merge_request_args(**merge))
        html = b'<div class="q"><span class="t">um</span></div><div class="q"><span class="t">dois</span></div>'
        return Response(kwargs["url"], html, 200, "", {}, {}, {}, method=method, _log=False)

    monkeypatch.setattr(_SyncSessionLogic, "_make_request", _patched)
    page = raspador.get("https://quotes.exemplo.com/", contact="mailto:eu@exemplo.com")
    assert page.css(".q .t::text").getall() == ["um", "dois"]
    assert enviado["impersonate"] is None
    headers = {k.lower(): v for k, v in enviado["headers"].items()}
    assert headers["user-agent"] == "raspador/0.1.0 (+mailto:eu@exemplo.com)"
    assert not any(k.startswith(("sec-ch-ua", "sec-fetch-")) for k in headers)
    assert "referer" not in headers
