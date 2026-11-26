"""F07: crawldir privado, recusa de diretório inseguro, lockfile e pause/resume de ponta a ponta."""

import os
import stat

import pytest

from raspador.crawldir import CrawldirLocked, UnsafeCrawldir, crawl_lock, secure_crawldir
from raspador.spiders import Spider

ROBOTS_OK = (200, "User-agent: *\nAllow: /", {})


def test_crawldir_novo_nasce_privado(tmp_path):
    d = secure_crawldir(tmp_path / "crawl")
    assert stat.S_IMODE(d.stat().st_mode) == 0o700


def test_crawldir_com_escrita_para_outros_e_recusado(tmp_path):
    d = tmp_path / "aberto"
    d.mkdir()
    d.chmod(0o777)
    with pytest.raises(UnsafeCrawldir) as exc:
        secure_crawldir(d)
    assert exc.value.code == "RSP-F001"


def test_lock_impede_dois_processos_no_mesmo_crawldir(tmp_path):
    d = secure_crawldir(tmp_path / "c")
    (d / ".lock").write_text(str(os.getppid()))  # processo vivo que não é este
    with pytest.raises(CrawldirLocked) as exc, crawl_lock(d):
        pass
    assert exc.value.code == "RSP-F002"


def test_lock_orfao_e_assumido_e_liberado_no_fim(tmp_path):
    d = secure_crawldir(tmp_path / "c")
    (d / ".lock").write_text("999999")  # pid que não existe
    with crawl_lock(d):
        assert (d / ".lock").read_text() == str(os.getpid())
    assert not (d / ".lock").exists()


def test_pausa_e_retoma_sem_refazer_o_que_ja_foi_feito(site, tmp_path):
    fake = site(
        {
            "https://ex.com/robots.txt": ROBOTS_OK,
            "https://ex.com/1": (200, '<a href="/2">2</a><h1>1</h1>', {}),
            "https://ex.com/2": (200, "<h1>2</h1>", {}),
        }
    )
    crawldir = tmp_path / "crawl"

    class S(Spider):
        name = "pausa"
        start_urls = ["https://ex.com/1"]
        download_delay = 0.0
        autothrottle_enabled = False
        concurrent_requests = 1
        policy_override = "teste automatizado em memória"

        async def parse(self, response):
            yield {"h1": response.css("h1::text").get()}
            for href in response.css("a::attr(href)").getall():
                yield response.follow(href)
            if response.url.endswith("/1"):
                self.pause()

    primeira = S(crawldir=crawldir).start()
    assert primeira.paused is True
    assert [i["h1"] for i in primeira.items] == ["1"]
    assert stat.S_IMODE(crawldir.stat().st_mode) == 0o700
    assert not (crawldir / ".lock").exists()

    segunda = S(crawldir=crawldir).start()
    assert segunda.paused is False
    assert [i["h1"] for i in segunda.items] == ["2"]
    assert fake.urls().count("https://ex.com/1") == 1
    # a limpeza do upstream apaga só o checkpoint; o log de auditoria tem as duas execuções
    eventos = [line for line in (crawldir / "audit.jsonl").read_text().splitlines() if "policy_override" in line]
    assert len(eventos) == 2
