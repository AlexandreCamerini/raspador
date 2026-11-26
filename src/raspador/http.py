"""Fábricas HTTP compliant sobre a FetcherSession do Scrapling.

Nunca reexporta `Fetcher`, `AsyncFetcher` nem `Fetcher.configure`: todos nascem disfarçados de Chrome.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlsplit

from scrapling.fetchers import FetcherSession

from raspador import robots
from raspador.adaptive import RaspadorStorage
from raspador.policy import check_headers, check_request_kwargs, default_user_agent

DEFAULT_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_REDIRECTS = 10
_BODY_KWARGS = frozenset({"data", "json", "files", "multipart"})

_SESSION_KWARGS = frozenset(
    {
        "headers",
        "timeout",
        "retries",
        "retry_delay",
        "follow_redirects",
        "max_redirects",
        "verify",
        "cert",
        "proxy",
        "selector_config",
    }
)


class RedirectBlocked(Exception):
    """Redirect para endereço interno (loopback, rede privada, link-local)."""

    code = "RSP-N002"

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(f"{self.code}: redirect para endereço interno bloqueado: {url}")


class InternalAddressBlocked(RedirectBlocked):
    """URL inicial em endereço interno, quando quem escolhe a URL não é o usuário (MCP)."""

    def __init__(self, url: str) -> None:
        Exception.__init__(self, f"{self.code}: endereço interno bloqueado: {url}")
        self.url = url


def check_public_url(url: str) -> None:
    """Recusa URL em loopback, rede privada, link-local ou CGNAT. Usado onde a URL vem de um modelo."""
    host = _host(url)
    if host == "localhost" or host.endswith(".localhost"):
        raise InternalAddressBlocked(url)
    literal = _literal_ip(host)
    addrs = [literal] if literal else resolve(host)
    if any(_is_internal(a) for a in addrs):
        raise InternalAddressBlocked(url)


class ResponseTooLarge(Exception):
    """Corpo maior que `max_bytes`. A checagem é depois do download: limita o que segue, não a memória do pico."""

    code = "RSP-N003"

    def __init__(self, url: str, size: int, limit: int) -> None:
        self.url, self.size, self.limit = url, size, limit
        super().__init__(f"{self.code}: resposta de {size} bytes acima do limite de {limit} em {url}")


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _is_internal(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not ip.is_global  # cobre privado, loopback, link-local, CGNAT (100.64/10), reservado, 0.0.0.0


def _literal_ip(host: str) -> str | None:
    try:
        return str(ipaddress.ip_address(host.strip("[]")))
    except ValueError:
        return None


def check_redirect_target(origin_url: str, target_url: str) -> None:
    """Equivalente ao `follow_redirects='safe'` do upstream para quem segue redirects manualmente."""
    origin, target = _host(origin_url), _host(target_url)
    if target == origin:
        return
    if target == "localhost" or target.endswith(".localhost"):
        raise RedirectBlocked(target_url)
    literal = _literal_ip(target)
    addrs = [literal] if literal else resolve(target)
    if any(_is_internal(a) for a in addrs):
        raise RedirectBlocked(target_url)


def resolve(host: str) -> list[str]:
    """Endereços de `host`. Ponto único de DNS da checagem SSRF (os testes o substituem)."""
    return [str(i[4][0]) for i in socket.getaddrinfo(host, None)]


async def check_redirect_target_async(origin_url: str, target_url: str) -> None:
    origin, target = _host(origin_url), _host(target_url)
    if target == origin or _literal_ip(target) or target == "localhost" or target.endswith(".localhost"):
        check_redirect_target(origin_url, target_url)
        return
    addrs = await asyncio.to_thread(resolve, target)
    if any(_is_internal(a) for a in addrs):
        raise RedirectBlocked(target_url)


_CREDENTIAL_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie"})
_TRANSPORT_KWARGS = ("verify", "proxy", "cert", "timeout")


def carries_credentials(headers: Any) -> bool:
    return any(k.lower() in _CREDENTIAL_HEADERS for k in (headers or {}))


def strip_credentials(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Para redirect a outro host: o libcurl não repassa Authorization nem cookies; quem segue à mão também não."""
    out = {k: v for k, v in kwargs.items() if k != "cookies"}
    for key in ("headers", "extra_headers"):
        if out.get(key):
            out[key] = {k: v for k, v in out[key].items() if k.lower() not in _CREDENTIAL_HEADERS}
    return out


def check_size(response: Any, limit: int | None) -> None:
    if limit is not None and len(response.body) > limit:
        raise ResponseTooLarge(response.url, len(response.body), limit)


def _session_config(contact: str | None, kwargs: dict[str, Any]) -> dict[str, Any]:
    check_request_kwargs(kwargs)
    unknown = set(kwargs) - _SESSION_KWARGS
    if unknown:
        # check_request_kwargs já recusou evasão; aqui sobram opções válidas por request mas não por sessão
        raise TypeError(f"opções não suportadas na sessão: {sorted(unknown)}")
    headers = dict(kwargs.pop("headers", None) or {})
    if not any(k.lower() == "user-agent" for k in headers):
        headers["User-Agent"] = default_user_agent(contact)
    check_headers(headers)
    selector_config = {"storage": RaspadorStorage, **(kwargs.pop("selector_config", None) or {})}
    return {
        **kwargs,
        "headers": headers,
        "impersonate": None,
        "stealthy_headers": False,
        "selector_config": selector_config,
    }


def spider_session(contact: str | None = None, **kwargs: Any) -> FetcherSession:
    """Sessão crua para `Spider.configure_sessions`. O spider guarda cada request e segue redirects sozinho."""
    config = _session_config(contact, kwargs)
    config["follow_redirects"] = False
    return FetcherSession(**config)


def _next_hop(method: str, kwargs: dict[str, Any], status: int) -> tuple[str, dict[str, Any]]:
    if status in (301, 302, 303) and method != "GET":
        return "GET", {k: v for k, v in kwargs.items() if k not in _BODY_KWARGS}
    return method, kwargs


class _GuardedClient:
    """Cliente guardado: allowlist por request, robots.txt (inclusive em cada redirect), SSRF e tamanho."""

    def __init__(self, client: Any, follow_redirects: bool, max_redirects: int, max_bytes: int | None) -> None:
        self._client = client
        self._follow = follow_redirects
        self._max_redirects = max_redirects
        self._max_bytes = max_bytes
        self._robots = robots.shared_cache()

    def _prepare(self, url: str, kwargs: dict[str, Any]) -> tuple[bool, int, int | None, dict[str, Any]]:
        follow = bool(kwargs.pop("follow_redirects", self._follow))
        max_r = int(kwargs.pop("max_redirects", self._max_redirects))
        max_bytes = kwargs.pop("max_bytes", self._max_bytes)
        check_request_kwargs(kwargs, url=url)
        return follow, max_r, max_bytes, {**kwargs, "follow_redirects": False}

    def _send(self, method: str, url: str, kwargs: dict[str, Any]):
        return getattr(self._client, method.lower())(url, **kwargs)

    def _robots_fetcher(self, kwargs: dict[str, Any]):
        transport = {k: kwargs[k] for k in _TRANSPORT_KWARGS if k in kwargs}
        return lambda robots_url: self._client.get(robots_url, follow_redirects="safe", **transport)

    def _session_has_credentials(self) -> bool:
        return carries_credentials(getattr(self._client, "_default_headers", None))

    def _hop(self, response: Any, method: str, kwargs: dict[str, Any]):
        """Próximo salto: (método, alvo, kwargs) ou None para parar e devolver o 3xx."""
        location = response.headers.get("location") or response.headers.get("Location")
        if not location:
            return None
        target = urljoin(response.url, location)
        if _host(target) != _host(response.url):
            if self._session_has_credentials():
                return None  # credencial da sessão não pode ser retirada por salto: não segue
            kwargs = strip_credentials(kwargs)
        method, kwargs = _next_hop(method, kwargs, response.status)
        return method, target, kwargs

    def request(self, method: str, url: str, **kwargs: Any):
        follow, max_r, max_bytes, kwargs = self._prepare(url, kwargs)
        robots_fetch = self._robots_fetcher(kwargs)
        self._robots.check(url, robots_fetch)
        response = self._send(method, url, kwargs)
        hops = 0
        while follow and 300 <= response.status < 400 and hops < max_r:
            nxt = self._hop(response, method, kwargs)
            if nxt is None:
                break
            method, target, kwargs = nxt
            check_redirect_target(response.url, target)
            self._robots.check(target, robots_fetch)
            response = self._send(method, target, kwargs)
            hops += 1
        check_size(response, max_bytes)
        return response

    def get(self, url: str, **kwargs: Any):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any):
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any):
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any):
        return self.request("DELETE", url, **kwargs)


class HttpSession:
    """Sessão HTTP guardada. Sync com `with`, async com `async with`."""

    def __init__(
        self,
        contact: str | None = None,
        *,
        max_bytes: int | None = DEFAULT_MAX_BYTES,
        **kwargs: Any,
    ) -> None:
        self._follow = bool(kwargs.pop("follow_redirects", True))
        self._max_redirects = int(kwargs.pop("max_redirects", DEFAULT_MAX_REDIRECTS))
        self._max_bytes = max_bytes
        config = _session_config(contact, kwargs)
        config["follow_redirects"] = False
        self._session = FetcherSession(**config)

    def __enter__(self) -> _GuardedClient:
        return _GuardedClient(self._session.__enter__(), self._follow, self._max_redirects, self._max_bytes)

    def __exit__(self, *exc: Any) -> None:
        self._session.__exit__(*exc)

    async def __aenter__(self) -> _AsyncGuardedClient:
        client = await self._session.__aenter__()
        return _AsyncGuardedClient(client, self._follow, self._max_redirects, self._max_bytes)

    async def __aexit__(self, *exc: Any) -> None:
        await self._session.__aexit__(*exc)


class _AsyncGuardedClient(_GuardedClient):
    async def _send(self, method: str, url: str, kwargs: dict[str, Any]):  # type: ignore[override]
        return await getattr(self._client, method.lower())(url, **kwargs)

    def _robots_fetcher(self, kwargs: dict[str, Any]):
        transport = {k: kwargs[k] for k in _TRANSPORT_KWARGS if k in kwargs}

        async def fetch(robots_url: str):
            return await self._client.get(robots_url, follow_redirects="safe", **transport)

        return fetch

    async def request(self, method: str, url: str, **kwargs: Any):  # type: ignore[override]
        follow, max_r, max_bytes, kwargs = self._prepare(url, kwargs)
        robots_fetch = self._robots_fetcher(kwargs)
        await self._robots.check_async(url, robots_fetch)
        response = await self._send(method, url, kwargs)
        hops = 0
        while follow and 300 <= response.status < 400 and hops < max_r:
            nxt = self._hop(response, method, kwargs)
            if nxt is None:
                break
            method, target, kwargs = nxt
            await check_redirect_target_async(response.url, target)
            await self._robots.check_async(target, robots_fetch)
            response = await self._send(method, target, kwargs)
            hops += 1
        check_size(response, max_bytes)
        return response

    async def get(self, url: str, **kwargs: Any):  # type: ignore[override]
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any):  # type: ignore[override]
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any):  # type: ignore[override]
        return await self.request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any):  # type: ignore[override]
        return await self.request("DELETE", url, **kwargs)


def http_session(contact: str | None = None, **kwargs: Any) -> HttpSession:
    return HttpSession(contact, **kwargs)


def async_http_session(contact: str | None = None, **kwargs: Any) -> HttpSession:
    return HttpSession(contact, **kwargs)


def _one_shot(method: str, url: str, kwargs: dict[str, Any]):
    contact = kwargs.pop("contact", None)
    max_bytes = kwargs.pop("max_bytes", DEFAULT_MAX_BYTES)
    check_request_kwargs({k: v for k, v in kwargs.items() if k not in {"follow_redirects", "max_redirects"}}, url=url)
    with http_session(contact, max_bytes=max_bytes) as s:
        return getattr(s, method)(url, **kwargs)


def get(url: str, **kwargs: Any):
    return _one_shot("get", url, kwargs)


def post(url: str, **kwargs: Any):
    return _one_shot("post", url, kwargs)


def put(url: str, **kwargs: Any):
    return _one_shot("put", url, kwargs)


def delete(url: str, **kwargs: Any):
    return _one_shot("delete", url, kwargs)
