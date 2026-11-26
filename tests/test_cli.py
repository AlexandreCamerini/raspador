"""F10: CLI `raspador get/post/put/delete URL OUT` e `raspador install`, contra components.md."""

import json
import subprocess

import pytest
from click.testing import CliRunner

from raspador import _ui
from raspador.cli import main

ROBOTS = "User-agent: *\nAllow: /\n\nUser-agent: raspador\nDisallow: /privado\n"
PAGINA = "<html><body><h1>Título</h1><p class='a'>um</p><p class='a'>dois</p></body></html>"


@pytest.fixture
def run():
    def _run(*args, env=None):
        return CliRunner(env={"NO_COLOR": None, "FORCE_COLOR": None, **(env or {})}).invoke(main, list(args))

    return _run


@pytest.fixture
def pagina(site):
    return site(
        {
            "https://ex.com/robots.txt": (200, ROBOTS, {}),
            "https://ex.com/p": (200, PAGINA, {}),
            "https://ex.com/sumiu": (404, "nada", {}),
            "https://ex.com/barrado": (403, "", {}),
        }
    )


def test_get_para_markdown_grava_arquivo_e_relata_no_stderr(run, pagina, tmp_path):
    out = tmp_path / "p.md"
    r = run("get", "https://ex.com/p", str(out))
    assert r.exit_code == 0, r.stderr
    assert "Título" in out.read_text()
    assert r.stdout == ""
    assert r.stderr.startswith("ok  200  https://ex.com/p  -> ")


def test_saida_no_stdout_so_tem_dado(run, pagina):
    r = run("get", "https://ex.com/p", "-", "-s", "p.a")
    assert r.exit_code == 0
    assert r.stdout.split() == ["um", "dois"]
    assert r.stderr == ""


def test_html_e_txt_pela_extensao(run, pagina, tmp_path):
    assert run("get", "https://ex.com/p", str(tmp_path / "p.html"), "-s", "h1").exit_code == 0
    assert (tmp_path / "p.html").read_text().strip() == "<h1>Título</h1>"
    assert run("get", "https://ex.com/p", str(tmp_path / "p.txt"), "-s", "h1").exit_code == 0
    assert (tmp_path / "p.txt").read_text().strip() == "Título"


def test_seletor_sem_match_sai_com_4(run, pagina, tmp_path):
    r = run("get", "https://ex.com/p", str(tmp_path / "v.md"), "-s", ".nao-existe")
    assert r.exit_code == 4
    assert "vazio" in r.stderr


def test_header_de_disfarce_sai_com_3_e_explica(run, pagina, tmp_path):
    r = run("get", "https://ex.com/p", str(tmp_path / "x.md"), "-H", "User-Agent: Mozilla/5.0")
    assert r.exit_code == 3
    assert "[POLÍTICA] RSP-P003" in r.stderr
    assert "motivo:" in r.stderr and "em vez disso:" in r.stderr
    assert not (tmp_path / "x.md").exists()


def test_robots_negado_sai_com_6(run, pagina, tmp_path):
    r = run("get", "https://ex.com/privado/a", str(tmp_path / "x.md"))
    assert r.exit_code == 6
    assert "RSP-R001" in r.stderr


def test_http_404_sai_com_5_e_403_com_6_sem_gravar(run, pagina, tmp_path):
    r = run("get", "https://ex.com/sumiu", str(tmp_path / "a.md"))
    assert r.exit_code == 5 and "RSP-H404" in r.stderr
    r = run("get", "https://ex.com/barrado", str(tmp_path / "b.md"))
    assert r.exit_code == 6 and "RSP-H403" in r.stderr
    assert "não tenta contornar" in r.stderr
    assert list(tmp_path.iterdir()) == []


def test_sem_tty_nao_ha_escape_ansi_e_com_always_ha(run, pagina, tmp_path):
    r = run("get", "https://ex.com/sumiu", str(tmp_path / "a.md"))
    assert "\x1b" not in r.stderr
    r = run("get", "https://ex.com/sumiu", str(tmp_path / "a.md"), "--color", "always")
    assert "\x1b[1;7m" in r.stderr


def test_no_color_vence_always(run, pagina, tmp_path):
    r = run("get", "https://ex.com/sumiu", str(tmp_path / "a.md"), "--color", "always", env={"NO_COLOR": "1"})
    assert "\x1b" not in r.stderr


def test_report_json_no_stdout(run, pagina, tmp_path):
    r = run("get", "https://ex.com/sumiu", str(tmp_path / "a.md"), "--report", "json")
    dado = json.loads(r.stdout)
    assert dado["ok"] is False and dado["status"] == 404
    assert dado["error"]["code"] == "RSP-H404"
    assert r.exit_code == 5


def test_post_com_json_de_corpo(run, site, tmp_path):
    fake = site({"https://ex.com/robots.txt": (404, "", {}), "https://ex.com/api": (200, "<p>ok</p>", {})})
    r = run("post", "https://ex.com/api", str(tmp_path / "r.txt"), "-j", '{"q": "café"}')
    assert r.exit_code == 0, r.stderr
    assert fake.requests[-1]["method"] == "POST"


def test_install_so_chama_playwright_chromium(run, monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        subprocess, "run", lambda args, **kw: chamadas.append(args) or subprocess.CompletedProcess(args, 0)
    )
    r = run("install", "--force")
    assert r.exit_code == 0
    assert len(chamadas) == 1
    assert chamadas[0][1:] == ["-m", "playwright", "install", "--force", "chromium"]
    assert "scrapling" not in " ".join(chamadas[0])


def test_ui_fallback_ascii_quando_stream_nao_e_utf8():
    assert _ui.tag_text("POLÍTICA", "ascii") == "POLITICA"
    assert _ui.tag_text("POLÍTICA", "utf-8") == "POLÍTICA"


def test_ui_tamanho_legivel_em_pt_br():
    assert _ui.human_size(12_600) == "12,3 KB"
    assert _ui.human_size(512) == "512 B"


def test_log_info_do_upstream_nao_vaza_sem_verbose(run, site, tmp_path, monkeypatch):
    import logging

    site({"https://ex.com/robots.txt": (404, "", {}), "https://ex.com/p": (200, PAGINA, {})})
    upstream = logging.getLogger("scrapling")
    monkeypatch.setattr(upstream, "level", logging.INFO)
    run("get", "https://ex.com/p", str(tmp_path / "p.md"))
    assert upstream.getEffectiveLevel() >= logging.WARNING


def test_report_json_com_stdout_e_erro_de_uso(run, pagina):
    r = run("get", "https://ex.com/p", "-", "--report", "json")
    assert r.exit_code == 2
    assert "--report json" in r.stderr


def test_erro_inesperado_do_raspador_sai_com_1_e_nao_vira_falha_de_rede(run, monkeypatch, tmp_path):
    import raspador.http

    def bug(*a, **k):
        raise TypeError("bug interno")

    monkeypatch.setattr(raspador.http, "get", bug)
    r = run("get", "https://ex.com/p", str(tmp_path / "x.md"))
    assert r.exit_code == 1
    assert "RSP-N001" not in (r.stderr or "")


def test_fetch_pelo_navegador_usa_o_mesmo_pipeline(run, monkeypatch, tmp_path):
    from raspador import browser

    chamadas = {}

    def falso(url, contact=None, **kw):
        chamadas.update(kw)
        return browser.build_response(url, "<h1>renderizado</h1>", 200, "OK", {}, {}, None)

    monkeypatch.setattr(browser, "fetch", falso)
    r = run("fetch", "https://ex.com/app", str(tmp_path / "a.txt"), "--wait-selector", "h1", "--timeout", "5")
    assert r.exit_code == 0, r.stderr
    assert (tmp_path / "a.txt").read_text().strip() == "renderizado"
    assert chamadas["wait_selector"] == "h1" and chamadas["timeout"] == 5000


def test_fetch_sem_chromium_explica_como_instalar(run, monkeypatch, tmp_path):
    from raspador import browser

    def sem_chromium(url, **kw):
        raise browser.BrowserUnavailable(RuntimeError("Executable doesn't exist"))

    monkeypatch.setattr(browser, "fetch", sem_chromium)
    r = run("fetch", "https://ex.com/app", str(tmp_path / "a.txt"))
    assert r.exit_code == 5
    assert "RSP-B001" in r.stderr and "raspador install" in r.stderr


def test_fetch_com_timeout_do_navegador_sai_com_5_e_dica(run, monkeypatch, tmp_path):
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    from raspador import browser

    def lento(url, **kw):
        raise PlaywrightTimeout("Timeout 5000ms exceeded waiting for selector")

    monkeypatch.setattr(browser, "fetch", lento)
    r = run("fetch", "https://ex.com/app", str(tmp_path / "a.txt"), "--wait-selector", "#x")
    assert r.exit_code == 5
    assert "RSP-B002" in r.stderr and "--timeout" in r.stderr
