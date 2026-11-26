"""Contrato com o Scrapling instalado. Se um upgrade mudar algo daqui, a camada quebra em silêncio:
este arquivo existe para ela quebrar alto. Rode antes de mudar a versão no pyproject."""

import ast
import importlib.metadata
import inspect
from pathlib import Path

from scrapling.engines.static import _ASyncSessionLogic
from scrapling.fetchers import FetcherSession
from scrapling.spiders import SessionManager
from scrapling.spiders import Spider as UpstreamSpider
from scrapling.spiders.engine import CrawlerEngine
from scrapling.spiders.robotstxt import RobotsTxtManager

SRC = Path(__file__).resolve().parents[1] / "src" / "raspador"


def test_versao_fixada():
    assert importlib.metadata.version("scrapling") == "0.5.1"


def test_atributos_privados_da_fetchersession():
    for attr in (
        "_default_impersonate",
        "_stealth",
        "_default_headers",
        "_proxy_rotator",
        "_client",
        "_is_alive",
    ):
        assert attr in FetcherSession.__slots__, attr


def test_atributos_privados_do_session_manager():
    m = SessionManager()
    for attr in ("_sessions", "_default_session_id", "_lazy_sessions"):
        assert hasattr(m, attr), attr


def test_spider_cria_session_manager_no_init_e_engine_no_run():
    src = inspect.getsource(UpstreamSpider)
    assert "self._session_manager = SessionManager()" in src
    assert "self._engine = CrawlerEngine(self, self._session_manager" in src


def test_engine_expoe_robots_manager_e_chama_on_start_dentro_do_manager():
    assert "self._robots_manager" in inspect.getsource(CrawlerEngine.__init__)
    crawl = inspect.getsource(CrawlerEngine.crawl)
    assert crawl.index("async with self.session_manager") < crawl.index("_prefetch_robots_txt")


def test_robots_manager_tem_os_ganchos_sobrescritos():
    for name in ("_get_parser", "_fetch_parser", "can_fetch", "get_delay_directives"):
        assert callable(getattr(RobotsTxtManager, name)), name
    assert "_cache" in inspect.getsource(RobotsTxtManager.__init__)


def test_transporte_tem_merge_e_make_request():
    assert callable(_ASyncSessionLogic._make_request)
    assert callable(_ASyncSessionLogic._merge_request_args)


def test_padroes_do_upstream_continuam_hostis():
    # Se isto mudar, a política ainda vale; o teste só avisa que o upstream mudou de comportamento.
    sig = inspect.signature(FetcherSession.__init__).parameters
    assert sig["impersonate"].default == "chrome"
    assert sig["stealthy_headers"].default is True
    assert UpstreamSpider.robots_txt_obey is False


FORBIDDEN_NAMES = {
    "StealthyFetcher",
    "StealthySession",
    "AsyncStealthySession",
    "RemoteSession",
    "AsyncRemoteSession",
    "Fetcher",
    "AsyncFetcher",
}
FORBIDDEN_MODULES = ("patchright", "browserforge", "camoufox")


def test_import_guard_raspador_nao_importa_caminho_stealth():
    problemas = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if (node.module or "").startswith(FORBIDDEN_MODULES):
                    problemas.append(f"{path.name}: from {node.module}")
                problemas += [f"{path.name}: {a.name}" for a in node.names if a.name in FORBIDDEN_NAMES]
            elif isinstance(node, ast.Import):
                problemas += [
                    f"{path.name}: import {a.name}" for a in node.names if a.name.startswith(FORBIDDEN_MODULES)
                ]
    assert problemas == []


def test_helpers_privados_usados_pela_cli_e_pelo_markdown():
    from scrapling.core.shell import Convertor
    from scrapling.engines.toolbelt.custom import Response

    for name in ("_sanitize_for_ai", "_strip_noise_tags", "_convert_to_markdown"):
        assert callable(getattr(Convertor, name)), name
    assert "main_content_only" in inspect.signature(Response.markdown).parameters


def test_storage_sqlite_continua_embrulhado_em_lru_cache_e_sem_url_quando_ha_storage_args():
    from scrapling.core.storage import SQLiteStorageSystem
    from scrapling.parser import Selector

    assert hasattr(SQLiteStorageSystem, "__wrapped__")
    src = inspect.getsource(Selector.__init__)
    # Se o upstream passar a injetar a URL em storage_args explícito, o RaspadorStorage pode ser revisto.
    assert '"storage_file": __DEFAULT_DB_FILE__' in src


def test_checkpoint_continua_pickle():
    from scrapling.spiders import checkpoint

    assert "pickle.loads" in inspect.getsource(checkpoint)


def test_playwright_fixado_na_revisao_do_chromium_do_patchright():
    import json

    import patchright
    import playwright

    def revisao(pkg):
        f = next(Path(pkg.__file__).parent.rglob("browsers.json"))
        return {b["name"]: b["revision"] for b in json.loads(f.read_text())["browsers"]}["chromium-headless-shell"]

    assert importlib.metadata.version("playwright").startswith("1.64.")
    assert revisao(playwright) == revisao(patchright)  # um só Chromium no disco


def test_route_fallback_existe_para_a_guarda_do_navegador():
    from playwright.async_api import Route as AsyncRoute
    from playwright.sync_api import Route

    assert callable(Route.fallback) and callable(AsyncRoute.fallback)


def test_templates_do_upstream_mantem_a_hierarquia_usada():
    from scrapling.spiders import ContentSpider, CrawlSpider, SitemapSpider

    assert issubclass(ContentSpider, CrawlSpider)
    assert UpstreamSpider in SitemapSpider.__mro__
    assert "development_cache_dir or" in inspect.getsource(CrawlerEngine.__init__)
