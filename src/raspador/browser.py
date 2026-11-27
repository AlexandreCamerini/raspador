"""Navegador do raspador (extra `raspador[browser]`): Playwright puro, sem stealth.

O único navegador do upstream é o `StealthyFetcher` (patchright, fingerprint, solver de Cloudflare). Este
adaptador renderiza JavaScript e devolve o mesmo `Response` do Scrapling, com:

- User-Agent `raspador/...`; nada de `init_script`, flags ou patch de fingerprint. O Chromium continua
  mandando os próprios client hints e `navigator.webdriver = true`: é um navegador automatizado e diz isso.
- robots.txt antes de navegar e de novo na URL final, se o navegador foi redirecionado.
- Requisições para IP interno literal ou `localhost` abortadas (a página não usa sua rede local).
- `max_bytes` no HTML final.

`page_setup` e `page_action` recebem a página crua do Playwright: o modelo de ameaça é acidente, não sabotagem.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

from scrapling.engines.toolbelt.custom import Response

from raspador import http as http_mod
from raspador import robots
from raspador.adaptive import RaspadorStorage
from raspador.http import DEFAULT_MAX_BYTES, HttpSession, _is_internal, _literal_ip, check_size
from raspador.policy import PolicyError, check_browser_kwargs, default_user_agent

__all__ = ["AsyncBrowserSession", "BrowserSession", "BrowserUnavailable", "fetch"]

DEFAULT_TIMEOUT_MS = 30_000
# Mesmo conjunto que o upstream descarta com disable_resources.
_HEAVY_RESOURCES = frozenset(
    {"font", "image", "media", "beacon", "object", "imageset", "texttrack", "websocket", "csp_report", "stylesheet"}
)


class StateFileMissing(FileNotFoundError):
    code = "RSP-F004"

    def __init__(self, path: Path) -> None:
        super().__init__(f"{self.code}: arquivo de estado do navegador não existe: {path}. Gere com save_state().")


def _state_path(path: str | Path) -> str:
    p = Path(path).expanduser()
    if not p.is_file():
        raise StateFileMissing(p)
    return str(p)


class BrowserUnavailable(RuntimeError):
    code = "RSP-B001"

    def __init__(self, cause: Exception) -> None:
        super().__init__(
            f"{self.code}: não foi possível abrir o Chromium ({type(cause).__name__}). "
            "Baixe o Chromium com `raspador install`."
        )


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _matches(host: str, domains: frozenset[str]) -> bool:
    if not domains:
        return False
    parts = host.split(".")
    return any(".".join(parts[i:]) in domains for i in range(len(parts)))


def blocked_domains_for(block_ads: bool, blocked_domains: Any) -> frozenset[str]:
    """Domínios a bloquear: os do usuário mais, com `block_ads`, a lista de anúncios que o upstream já instala."""
    out = {d.lower().lstrip(".") for d in (blocked_domains or ())}
    if block_ads:
        from scrapling.engines.toolbelt.ad_domains import AD_DOMAINS

        out |= AD_DOMAINS
    return frozenset(out)


def check_cdp_url(cdp_url: str) -> None:
    """Navegador remoto só na sua máquina ou rede privada. Provedor público de "scraping browser" costuma
    resolver CAPTCHA e disfarçar fingerprint: é evasão terceirizada."""
    host = (urlsplit(cdp_url).hostname or "").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return
    literal = _literal_ip(host)
    addrs = [literal] if literal else http_mod.resolve(host)
    if addrs and all(_is_internal(a) for a in addrs):
        return
    raise PolicyError(
        "RSP-P009",
        "cdp_url",
        f"{urlsplit(cdp_url).scheme}://{host}",
        "navegador remoto em endereço público costuma ser um serviço que resolve CAPTCHA e disfarça o "
        "navegador, o que é evasão terceirizada.",
        "use um Chromium seu, na sua máquina ou rede privada (ws://127.0.0.1:9222/...).",
    )


def route_decision(
    request_url: str,
    resource_type: str,
    target_host: str,
    disable_resources: bool,
    blocked: frozenset[str] = frozenset(),
) -> str:
    """'abort' ou 'continue' para cada requisição da página. Função pura, testada sem navegador."""
    host = _host(request_url)
    if host and host != target_host and _matches(host, blocked):
        return "abort"
    if host and host != target_host:
        literal = _literal_ip(host)
        if host == "localhost" or host.endswith(".localhost") or (literal and _is_internal(literal)):
            return "abort"
    if disable_resources and resource_type in _HEAVY_RESOURCES:
        return "abort"
    return "continue"


def build_response(
    url: str,
    html: str,
    status: int,
    reason: str,
    headers: dict[str, str],
    cookies: dict[str, str],
    selector_config: dict[str, Any] | None,
) -> Response:
    config = {"storage": RaspadorStorage, **(selector_config or {})}
    return Response(
        url,
        html.encode("utf-8"),
        status,
        reason,
        cookies,
        headers,
        {},
        encoding="utf-8",
        method="GET",
        _log=False,
        **config,
    )


class _Options:
    def __init__(self, url: str, kwargs: dict[str, Any], defaults: dict[str, Any]) -> None:
        check_browser_kwargs(kwargs, url=url)
        merged = {**defaults, **kwargs}
        self.timeout: int = int(merged.get("timeout", DEFAULT_TIMEOUT_MS))
        self.wait_selector: str | None = merged.get("wait_selector")
        self.wait_selector_state: Literal["attached", "detached", "hidden", "visible"] = merged.get(
            "wait_selector_state", "attached"
        )
        self.network_idle: bool = bool(merged.get("network_idle", False))
        self.load_dom: bool = bool(merged.get("load_dom", True))
        self.wait_ms: int = int(merged.get("wait", 0))
        self.disable_resources: bool = bool(merged.get("disable_resources", False))
        self.page_action: Callable[[Any], Any] | None = merged.get("page_action")
        self.page_setup: Callable[[Any], Any] | None = merged.get("page_setup")
        self.extra_headers: dict[str, str] = {**(merged.get("headers") or {}), **(merged.get("extra_headers") or {})}
        self.selector_config: dict[str, Any] | None = merged.get("selector_config")
        self.max_bytes: int | None = merged.get("max_bytes", DEFAULT_MAX_BYTES)
        self.wait_until: Literal["commit", "domcontentloaded"] = "domcontentloaded" if self.load_dom else "commit"


def _recorder(enabled: bool, max_requests: int, asynchronous: bool) -> Any:
    """Histórico de rede do upstream (`NetworkRecorder`): genérico de Playwright, sem patchright."""
    from scrapling.engines._browsers._network import NetworkRecorder

    return NetworkRecorder(enabled=enabled, max_requests=max_requests, asynchronous=asynchronous)


def _cookies(raw: Any) -> dict[str, str]:
    return {c["name"]: c["value"] for c in raw}


def _private_file(path: str | Path) -> Path:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _playwright_proxy(url: str) -> dict[str, str]:
    """O Chromium ignora `usuario:senha@` em `--proxy-server`, e o Playwright põe esse valor no argv (visível no
    `ps`) e no call log de erro de launch. A credencial vai separada."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    server = f"{parts.scheme}://{host}" + (f":{parts.port}" if parts.port else "")
    out = {"server": server}
    if parts.username:
        out["username"] = unquote(parts.username)
    if parts.password:
        out["password"] = unquote(parts.password)
    return out


class BrowserSession:
    """Navegador vivo entre fetches. `with BrowserSession() as b: b.fetch(url)`."""

    def __init__(
        self,
        contact: str | None = None,
        *,
        headless: bool = True,
        locale: str | None = None,
        proxy: str | None = None,
        storage_state: str | Path | None = None,
        check_robots: bool = True,
        record_requests: bool = False,
        max_recorded_requests: int = 1000,
        blocked_domains: Any = None,
        block_ads: bool = False,
        cdp_url: str | None = None,
        **defaults: Any,
    ) -> None:
        check_browser_kwargs(defaults)
        if cdp_url:
            check_cdp_url(cdp_url)
        self._cdp_url = cdp_url
        self._record_requests = record_requests
        self._max_recorded = max_recorded_requests
        self._blocked = blocked_domains_for(block_ads, blocked_domains)
        self.network: Any = None
        self._contact = contact
        self._headless = headless
        self._locale = locale
        self._proxy = proxy
        self._storage_state = _state_path(storage_state) if storage_state else None
        self._check_robots = check_robots
        self._defaults = defaults
        self._http = HttpSession(contact, proxy=proxy) if proxy else HttpSession(contact)
        self._is_alive = False

    # -- ciclo de vida -------------------------------------------------------------------------------
    def _context_kwargs(self) -> dict[str, Any]:
        kw: dict[str, Any] = {"user_agent": default_user_agent(self._contact)}
        if self._locale:
            kw["locale"] = self._locale
        if self._storage_state:
            kw["storage_state"] = self._storage_state
        return kw

    def _launch_kwargs(self) -> dict[str, Any]:
        kw: dict[str, Any] = {"headless": self._headless}
        if self._proxy:
            kw["proxy"] = _playwright_proxy(self._proxy)
        return kw

    def __enter__(self) -> BrowserSession:
        from playwright.sync_api import sync_playwright

        try:
            self._pw = sync_playwright().start()
            if self._cdp_url:
                self._browser = self._pw.chromium.connect_over_cdp(self._cdp_url)
            else:
                self._browser = self._pw.chromium.launch(**self._launch_kwargs())
            self._context = self._browser.new_context(**self._context_kwargs())
        except Exception as e:
            self._close_quietly()
            raise BrowserUnavailable(e) from e
        self.network = _recorder(self._record_requests, self._max_recorded, asynchronous=False)
        self.network._attach(self._context)
        self._http_client = self._http.__enter__()
        self._is_alive = True
        return self

    def __exit__(self, *exc: Any) -> None:
        self._close_quietly()
        self._http.__exit__(*exc)
        self._is_alive = False

    def _close_quietly(self) -> None:
        for name in ("_context", "_browser"):
            obj = getattr(self, name, None)
            if obj is not None:
                with contextlib.suppress(Exception):
                    obj.close()
        pw = getattr(self, "_pw", None)
        if pw is not None:
            with contextlib.suppress(Exception):
                pw.stop()

    # -- estado -------------------------------------------------------------------------------------
    def save_state(self, path: str | Path) -> Path:
        """Cookies, localStorage e IndexedDB (formato storage_state do Playwright). Arquivo com 0600: é segredo."""
        p = _private_file(path)
        self._context.storage_state(path=str(p), indexed_db=True)
        os.chmod(p, 0o600)
        return p

    def load_state(self, path: str | Path) -> None:
        """Recria o contexto com o estado salvo. Abas abertas são fechadas."""
        self._storage_state = _state_path(path)
        self._context.close()
        self._context = self._browser.new_context(**self._context_kwargs())
        self.network._attach(self._context)

    # -- fetch --------------------------------------------------------------------------------------
    def _robots_fetch(self, robots_url: str):
        return self._http_client._client.get(robots_url, follow_redirects="safe")

    def fetch(self, url: str, **kwargs: Any) -> Response:
        http_mod.check_url(url)
        opts = _Options(url, kwargs, self._defaults)
        if self._check_robots:
            robots.shared_cache().check(url, self._robots_fetch)
        page = self._context.new_page()
        try:
            target = _host(url)

            def guard(route: Any) -> None:
                decision = route_decision(
                    route.request.url, route.request.resource_type, target, opts.disable_resources, self._blocked
                )
                # fallback() repassa a rotas registradas antes (page_setup) ou, sem elas, à rede
                route.abort() if decision == "abort" else route.fallback()

            if opts.extra_headers:
                page.set_extra_http_headers(opts.extra_headers)
            if opts.page_setup:
                opts.page_setup(page)
            # registrada por último = avaliada primeiro: nenhuma rota do usuário passa por cima da guarda
            page.route("**/*", guard)
            nav = page.goto(url, wait_until=opts.wait_until, timeout=opts.timeout)
            if opts.network_idle:
                page.wait_for_load_state("networkidle", timeout=opts.timeout)
            if opts.wait_selector:
                page.wait_for_selector(opts.wait_selector, state=opts.wait_selector_state, timeout=opts.timeout)
            if opts.page_action:
                opts.page_action(page)
            if opts.wait_ms:
                page.wait_for_timeout(opts.wait_ms)
            final_url = page.url
            if final_url != url:
                http_mod.check_url(final_url)
                robots.shared_cache().check(final_url, self._robots_fetch)
            response = build_response(
                final_url,
                page.content(),
                nav.status if nav else 0,
                nav.status_text if nav else "",
                dict(nav.headers) if nav else {},
                _cookies(self._context.cookies()),
                opts.selector_config,
            )
        finally:
            page.close()
        check_size(response, opts.max_bytes)
        return response


class AsyncBrowserSession(BrowserSession):
    """Versão assíncrona; também serve como sessão de spider (`configure_sessions`)."""

    async def __aenter__(self) -> AsyncBrowserSession:  # type: ignore[override]
        from playwright.async_api import async_playwright

        try:
            self._pw = await async_playwright().start()
            if self._cdp_url:
                self._browser = await self._pw.chromium.connect_over_cdp(self._cdp_url)
            else:
                self._browser = await self._pw.chromium.launch(**self._launch_kwargs())
            self._context = await self._browser.new_context(**self._context_kwargs())
        except Exception as e:
            await self._aclose_quietly()
            raise BrowserUnavailable(e) from e
        self.network = _recorder(self._record_requests, self._max_recorded, asynchronous=True)
        self.network._attach(self._context)
        self._http_client = await self._http.__aenter__()
        self._is_alive = True
        return self

    async def __aexit__(self, *exc: Any) -> None:  # type: ignore[override]
        await self._aclose_quietly()
        await self._http.__aexit__(*exc)
        self._is_alive = False

    async def _aclose_quietly(self) -> None:
        for name in ("_context", "_browser"):
            obj = getattr(self, name, None)
            if obj is not None:
                with contextlib.suppress(Exception):
                    await obj.close()
        pw = getattr(self, "_pw", None)
        if pw is not None:
            with contextlib.suppress(Exception):
                await pw.stop()

    async def save_state(self, path: str | Path) -> Path:  # type: ignore[override]
        p = _private_file(path)
        await self._context.storage_state(path=str(p), indexed_db=True)
        os.chmod(p, 0o600)
        return p

    async def load_state(self, path: str | Path) -> None:  # type: ignore[override]
        self._storage_state = _state_path(path)
        await self._context.close()
        self._context = await self._browser.new_context(**self._context_kwargs())
        self.network._attach(self._context)

    async def _robots_fetch(self, robots_url: str):  # type: ignore[override]
        return await self._http_client._client.get(robots_url, follow_redirects="safe")

    async def fetch(self, url: str, **kwargs: Any) -> Response:  # type: ignore[override]
        http_mod.check_url(url)
        opts = _Options(url, kwargs, self._defaults)
        if self._check_robots:
            await robots.shared_cache().check_async(url, self._robots_fetch)
        page = await self._context.new_page()
        try:
            target = _host(url)

            async def guard(route: Any) -> None:
                decision = route_decision(
                    route.request.url, route.request.resource_type, target, opts.disable_resources, self._blocked
                )
                await (route.abort() if decision == "abort" else route.fallback())

            if opts.extra_headers:
                await page.set_extra_http_headers(opts.extra_headers)
            if opts.page_setup:
                await _maybe_await(opts.page_setup(page))
            await page.route("**/*", guard)
            nav = await page.goto(url, wait_until=opts.wait_until, timeout=opts.timeout)
            if opts.network_idle:
                await page.wait_for_load_state("networkidle", timeout=opts.timeout)
            if opts.wait_selector:
                await page.wait_for_selector(opts.wait_selector, state=opts.wait_selector_state, timeout=opts.timeout)
            if opts.page_action:
                await _maybe_await(opts.page_action(page))
            if opts.wait_ms:
                await page.wait_for_timeout(opts.wait_ms)
            final_url = page.url
            if final_url != url:
                http_mod.check_url(final_url)
                await robots.shared_cache().check_async(final_url, self._robots_fetch)
            response = build_response(
                final_url,
                await page.content(),
                nav.status if nav else 0,
                nav.status_text if nav else "",
                dict(nav.headers) if nav else {},
                _cookies(await self._context.cookies()),
                opts.selector_config,
            )
        finally:
            await page.close()
        check_size(response, opts.max_bytes)
        return response


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


def fetch(url: str, contact: str | None = None, **kwargs: Any) -> Response:
    """Página renderizada avulsa: abre o navegador, busca e fecha."""
    session_kw = {k: kwargs.pop(k) for k in ("headless", "locale", "proxy", "storage_state") if k in kwargs}
    with BrowserSession(contact, **session_kw) as b:
        return b.fetch(url, **kwargs)
