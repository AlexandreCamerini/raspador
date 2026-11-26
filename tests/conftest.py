"""Transporte falso compartilhado: troca só o `_make_request` do upstream e aplica o merge real de argumentos,
então o que os testes verificam é o que o curl_cffi receberia."""

import pytest
from scrapling.engines.static import _ASyncSessionLogic, _SyncSessionLogic
from scrapling.engines.toolbelt.convertor import ResponseFactory
from scrapling.engines.toolbelt.custom import Response


class SiteFalso:
    def __init__(self, pages: dict[str, tuple[int, str | bytes, dict]]):
        self.pages = pages
        self.requests: list[dict] = []

    def respond(self, client, method, stealth, kwargs):
        url = kwargs["url"]
        merge = dict(kwargs) | ({"stealth": stealth} if stealth is not None else {})
        final = client._merge_request_args(**merge)
        self.requests.append({"url": url, "final": final, "method": method})
        status, body, headers = self.pages.get(url, (404, "nada", {}))
        body = body.encode() if isinstance(body, str) else body
        selector_config = kwargs.get("selector_config") or client.selector_config or {}
        # Como o curl_cffi: o encoding vem do Content-Type (mesma função que o upstream usa no navegador)
        ctype = next((v for k, v in headers.items() if k.lower() == "content-type"), "")
        encoding = ResponseFactory._extract_encoding(ctype)
        return Response(
            url, body, status, "", {}, headers, {}, encoding=encoding, method=method, _log=False, **selector_config
        )

    def urls(self):
        return [r["url"] for r in self.requests]


@pytest.fixture
def site(monkeypatch):
    def install(pages):
        fake = SiteFalso(pages)
        # DNS falso: todo host do site falso resolve para um IP público (o sandbox não tem DNS)
        import raspador.http

        monkeypatch.setattr(raspador.http, "resolve", lambda host: ["93.184.216.34"])

        async def _async(self, method, stealth=None, **kwargs):
            return fake.respond(self, method, stealth, kwargs)

        def _sync(self, method, stealth=None, **kwargs):
            return fake.respond(self, method, stealth, kwargs)

        monkeypatch.setattr(_ASyncSessionLogic, "_make_request", _async)
        monkeypatch.setattr(_SyncSessionLogic, "_make_request", _sync)
        return fake

    return install


@pytest.fixture(autouse=True)
def _isolar_estado(tmp_path, monkeypatch):
    """Cada teste com RASPADOR_HOME próprio e caches de robots e storage limpos."""
    monkeypatch.setenv("RASPADOR_HOME", str(tmp_path / "home"))
    import raspador.adaptive as adaptive
    import raspador.robots as robots

    robots.clear_cache()
    adaptive.reset()
    yield
    robots.clear_cache()
    adaptive.reset()
