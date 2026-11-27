"""robots.txt do raspador: regras de status, token `raspador`, cache com TTL.

Usado pelo spider (`RaspadorRobots`) e pelas chamadas avulsas e sessões guardadas.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

from protego import Protego

ROBOTS_TOKEN = "raspador"
ROBOTS_TTL_SECONDS = 24 * 3600
# Falha (rede, 5xx) vira "tudo negado", mas por pouco tempo: um erro passageiro não bloqueia o domínio por um dia.
ROBOTS_FAILURE_TTL_SECONDS = 300
DISALLOW_ALL = "User-agent: *\nDisallow: /"


class RobotsDenied(Exception):
    """O robots.txt do site não permite esta URL para o raspador."""

    code = "RSP-R001"

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(f"{self.code}: o robots.txt de {urlsplit(url).netloc} não permite {url} para o raspador.")


class RobotsUnavailable(RobotsDenied):
    """O robots.txt não pôde ser lido (rede, proxy, 5xx). Fecha o site como `RobotsDenied`, mas não é uma negação
    do dono do site: o erro diz o motivo para o usuário olhar a própria rede ou o proxy."""

    code = "RSP-R002"

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        Exception.__init__(
            self,
            f"{self.code}: não foi possível ler o robots.txt de {urlsplit(url).netloc} ({reason}); sem ele o raspador "
            f"não busca nada no site. Nova tentativa em {ROBOTS_FAILURE_TTL_SECONDS // 60} min.",
        )


def failure_reason(status: int | None, exc: BaseException | None = None) -> str | None:
    """Motivo legível quando o robots.txt não foi lido; None quando a resposta vale como regra (200, 4xx).

    Só o nome da exceção: a mensagem do curl pode trazer a URL do proxy com credencial.
    """
    if exc is not None:
        return f"falha de rede ou proxy: {type(exc).__name__}"
    if status is None:
        return "falha de rede ou proxy"
    if status >= 500:
        return f"HTTP {status}"
    return None


def robots_content(status: int | None, body: bytes, encoding: str | None = "utf-8") -> str:
    """Texto de robots.txt a usar, dado o resultado da busca.

    200: o corpo. 401/403: tudo negado (acesso negado ao robots não é permissão).
    Outros 4xx: robots ausente, tudo permitido. 5xx ou falha de rede (status None): tudo negado.
    """
    if status == 200:
        return body.decode(encoding or "utf-8", errors="replace").removeprefix("\N{BYTE ORDER MARK}")
    if status in (401, 403):
        return DISALLOW_ALL
    if status is not None and 400 <= status < 500:
        return ""
    return DISALLOW_ALL


def ttl_for(status: int | None) -> float:
    return ROBOTS_FAILURE_TTL_SECONDS if status is None or status >= 500 else ROBOTS_TTL_SECONDS


def parse(content: str) -> Protego:
    try:
        return Protego.parse(content)
    except Exception:
        return Protego.parse("")


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme or 'https'}://{parts.netloc}"


class RobotsCache:
    def __init__(self) -> None:
        self._parsers: dict[str, tuple[float, float, Protego, str | None]] = {}
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._parsers.clear()

    def _cached(self, origin: str) -> tuple[Protego, str | None] | None:
        hit = self._parsers.get(origin)
        if hit and time.monotonic() - hit[0] <= hit[1]:
            return hit[2], hit[3]
        return None

    def _store(
        self, origin: str, status: int | None, body: bytes, encoding: str | None, exc: BaseException | None = None
    ) -> tuple[Protego, str | None]:
        parser = parse(robots_content(status, body, encoding))
        reason = failure_reason(status, exc)
        with self._lock:
            self._parsers[origin] = (time.monotonic(), ttl_for(status), parser, reason)
        return parser, reason

    @staticmethod
    def _verdict(url: str, parser: Protego, reason: str | None) -> None:
        if not parser.can_fetch(url, ROBOTS_TOKEN):
            raise RobotsUnavailable(url, reason) if reason else RobotsDenied(url)

    def check(self, url: str, fetch: Callable[[str], Any]) -> None:
        origin = _origin(url)
        hit = self._cached(origin)
        if hit is None:
            try:
                r = fetch(origin + "/robots.txt")
                hit = self._store(origin, r.status, r.body, r.encoding)
            except Exception as e:
                hit = self._store(origin, None, b"", None, e)
        self._verdict(url, *hit)

    async def check_async(self, url: str, fetch: Callable[[str], Awaitable[Any]]) -> None:
        origin = _origin(url)
        hit = self._cached(origin)
        if hit is None:
            try:
                r = await fetch(origin + "/robots.txt")
                hit = self._store(origin, r.status, r.body, r.encoding)
            except Exception as e:
                hit = self._store(origin, None, b"", None, e)
        self._verdict(url, *hit)


_CACHE = RobotsCache()


def shared_cache() -> RobotsCache:
    return _CACHE


def clear_cache() -> None:
    _CACHE.clear()
