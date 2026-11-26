"""Spiders compliant sobre o engine do Scrapling.

O raspador troca três peças do upstream, todas por atributo privado (fixado em
tests/test_contract_upstream.py):

- `Spider._session_manager`: vira um `GuardedSessionManager`, o único ponto por onde passa
  todo request (start_requests, follow, retry, robots.txt).
- `CrawlerEngine._robots_manager`: vira `RaspadorRobots`, que consulta com o token `raspador`,
  trata 401/403 como negado e tem TTL.
- Redirects: a sessão não os segue; o manager segue cada salto validando domínio e robots.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, ClassVar, cast
from urllib.parse import urljoin, urlsplit

from protego import Protego
from scrapling.fetchers import FetcherSession
from scrapling.spiders import ContentSpider as _UpstreamContentSpider
from scrapling.spiders import CrawlRule, LinkExtractor, Request, SessionManager
from scrapling.spiders import CrawlSpider as _UpstreamCrawlSpider
from scrapling.spiders import SitemapSpider as _UpstreamSitemapSpider
from scrapling.spiders import Spider as _UpstreamSpider
from scrapling.spiders.robotstxt import RobotsTxtManager

from raspador import robots as robots_rules
from raspador.audit import AuditLog
from raspador.browser import AsyncBrowserSession
from raspador.crawldir import crawl_lock, secure_crawldir
from raspador.http import (
    DEFAULT_MAX_BYTES,
    HttpSession,
    carries_credentials,
    check_redirect_target_async,
    check_size,
    spider_session,
    strip_credentials,
)
from raspador.policy import (
    PolicyError,
    check_browser_kwargs,
    check_request_kwargs,
    check_session,
    check_spider_class,
)
from raspador.robots import RobotsDenied

__all__ = [
    "ContentSpider",
    "CrawlRule",
    "CrawlSpider",
    "DomainStopped",
    "LinkExtractor",
    "OffsiteRequest",
    "Request",
    "RobotsDenied",
    "SitemapSpider",
    "Spider",
]

MAX_REDIRECT_HOPS = 10


class OffsiteRequest(Exception):
    """Request ou redirect para fora de `allowed_domains`."""


class DomainStopped(Exception):
    """Domínio parado depois de bloqueios seguidos."""


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


class RaspadorRobots(RobotsTxtManager):
    """Uma busca de robots.txt por domínio, tratamento de status próprio, token `raspador`, TTL."""

    def __init__(self, fetch_fn: Any, is_offsite: Any = None) -> None:
        super().__init__(fetch_fn)
        self._fetched_at: dict[str, float] = {}
        self._is_offsite = is_offsite or (lambda url: False)
        self.on_denied: Any = None

    async def _get_parser(self, url: str, sid: str) -> Protego:
        if self._is_offsite(url):
            # Fora do escopo: não busca robots; o manager descarta e audita como offsite_dropped.
            return Protego.parse("")
        domain = urlsplit(url).netloc
        if (
            domain in self._cache
            and time.monotonic() - self._fetched_at.get(domain, 0) > robots_rules.ROBOTS_TTL_SECONDS
        ):
            del self._cache[domain]
        return await super()._get_parser(url, sid)

    async def _fetch_parser(self, scheme: str, domain: str, sid: str) -> Protego:
        robots_url = f"{scheme or 'https'}://{domain}/robots.txt"
        status: int | None = None
        try:
            response = await self._fetch_fn(robots_url, sid)
            status = response.status
            parser = robots_rules.parse(robots_rules.robots_content(status, response.body, response.encoding))
        except Exception:
            parser = robots_rules.parse(robots_rules.robots_content(None, b""))
        self._cache[domain] = parser
        # o cache do upstream não tem TTL; aqui a falha expira em minutos
        ttl = robots_rules.ttl_for(status)
        self._fetched_at[domain] = time.monotonic() - (robots_rules.ROBOTS_TTL_SECONDS - ttl)
        return parser

    async def can_fetch(self, url: str, sid: str) -> bool:
        parser = await self._get_parser(url, sid)
        allowed = parser.can_fetch(url, robots_rules.ROBOTS_TOKEN)
        if not allowed and self.on_denied:
            self.on_denied(url)
        return allowed

    async def get_delay_directives(self, url: str, sid: str):
        parser = await self._get_parser(url, sid)
        c_delay = parser.crawl_delay(robots_rules.ROBOTS_TOKEN)
        rate = parser.request_rate(robots_rules.ROBOTS_TOKEN)
        return (
            float(c_delay) if c_delay is not None else None,
            (rate.requests, rate.seconds) if rate is not None else None,
        )


class GuardedSessionManager(SessionManager):
    def __init__(self, spider: Spider) -> None:
        super().__init__()
        self._spider = spider
        self._robots: RaspadorRobots | None = None
        self._robots_http: Any = None  # sessão HTTP só para robots.txt de sids de navegador

    def add(self, session_id: str, session: Any, *, default: bool = False, lazy: bool = False):
        if isinstance(session, AsyncBrowserSession):
            session._check_robots = False  # o engine já consultou; a URL final é checada pela própria sessão
            # duck typing: o SessionManager só usa __aenter__, __aexit__, _is_alive e fetch
            return super().add(session_id, cast(Any, session), default=default, lazy=lazy)
        if not isinstance(session, FetcherSession):
            raise PolicyError(
                "RSP-P007",
                "session",
                type(session).__name__,
                "só entram no spider a sessão HTTP compliant e o navegador do raspador; as de navegador do "
                "upstream usam patchright.",
                "use raspador.http.spider_session() ou raspador.browser.AsyncBrowserSession().",
            )
        check_session(session)
        return super().add(session_id, session, default=default, lazy=lazy)

    def _is_browser(self, sid: str) -> bool:
        return isinstance(self.get(sid or self.default_session_id), AsyncBrowserSession)

    async def close(self) -> None:
        await super().close()
        if self._robots_http is not None:
            await self._robots_http.__aexit__(None, None, None)
            self._robots_http = None

    async def start(self) -> None:
        await super().start()
        engine = getattr(self._spider, "_engine", None)
        if engine is not None and getattr(engine, "_robots_manager", None) is not None:
            self._robots = RaspadorRobots(self._fetch_robots, is_offsite=self._is_offsite)
            self._robots.on_denied = lambda url: self._spider._audit.record("robots_denied", url=url, domain=_host(url))
            engine._robots_manager = self._robots

    async def _fetch_robots(self, url: str, sid: str):
        if self._is_browser(sid):
            # robots.txt não precisa de navegador: vai por HTTP identificado, sem abrir aba
            if self._robots_http is None:
                nav = cast(AsyncBrowserSession, self.get(sid or self.default_session_id))
                contact = nav._contact or self._spider.contact
                # mesmo proxy da sessão de navegador: o robots não pode sair pelo IP real
                self._robots_http = HttpSession(contact, proxy=nav._proxy) if nav._proxy else HttpSession(contact)
                self._robots_client = await self._robots_http.__aenter__()
            return await self._robots_client._client.get(url, follow_redirects="safe")
        return await self._guarded_fetch(Request(url, sid=sid), check_robots=False)

    async def fetch(self, request: Request):
        if "proxy" in request._session_kwargs:
            e = PolicyError(
                "RSP-P006",
                "proxy",
                request._session_kwargs["proxy"],
                "proxy por request permite trocar de proxy depois de um bloqueio, o que é evasão de rate limit.",
                "defina um proxy fixo na sessão: raspador.http.spider_session(proxy=...).",
            )
            self._spider._audit.record(
                "policy_error", url=request.url, domain=_host(request.url), code=e.code, detail=e.option
            )
            raise e
        return await self._guarded_fetch(request, check_robots=True)

    def _is_offsite(self, url: str) -> bool:
        allowed = self._spider.allowed_domains
        host = _host(url)
        return bool(allowed) and not any(host == d or host.endswith("." + d) for d in allowed)

    async def _guarded_fetch(self, request: Request, *, check_robots: bool):
        spider = self._spider
        domain = _host(request.url)
        if domain in spider._stopped_domains:
            raise DomainStopped(domain)
        self._check_offsite(request.url)
        browser_sid = self._is_browser(request.sid)
        try:
            if browser_sid:
                check_browser_kwargs(request._session_kwargs, url=request.url)
            else:
                check_request_kwargs(request._session_kwargs, url=request.url)
        except PolicyError as e:
            spider._audit.record("policy_error", url=request.url, domain=domain, code=e.code, detail=e.option)
            raise
        if browser_sid:
            # o navegador segue redirects sozinho (e checa robots da URL final); aqui só o domínio final
            response = await super().fetch(request)
            self._check_offsite(response.url)
            check_size(response, spider.max_bytes)
            return response
        request._session_kwargs.pop("follow_redirects", None)
        response = await super().fetch(request)
        hops = 0
        while 300 <= response.status < 400 and hops < MAX_REDIRECT_HOPS:
            location = response.headers.get("location") or response.headers.get("Location")
            if not location:
                break
            target = urljoin(response.url, location)
            self._check_offsite(target)
            await check_redirect_target_async(response.url, target)
            cross_host = _host(target) != _host(response.url)
            if cross_host and carries_credentials(
                getattr(self.get(request.sid or self.default_session_id), "_default_headers", None)
            ):
                break  # credencial da sessão não pode ser retirada por salto: não segue
            if check_robots and self._robots and not await self._robots.can_fetch(target, request.sid):
                raise RobotsDenied(target)
            kwargs = dict(request._session_kwargs)
            if cross_host:
                kwargs = strip_credentials(kwargs)
            if response.status in (301, 302, 303):
                kwargs = {k: v for k, v in kwargs.items() if k not in {"data", "json", "files", "multipart"}}
                kwargs["method"] = "GET"
            hop = Request(
                target,
                sid=request.sid,
                callback=request.callback,
                priority=request.priority,
                dont_filter=True,
                meta=dict(request.meta),
                **kwargs,
            )
            response = await super().fetch(hop)
            hops += 1
        check_size(response, spider.max_bytes)
        response.request = request
        return response

    def _check_offsite(self, url: str) -> None:
        if self._is_offsite(url):
            self._spider._audit.record("offsite_dropped", url=url, domain=_host(url))
            raise OffsiteRequest(url)


class Spider(_UpstreamSpider):
    """Spider do raspador: robots.txt obrigatório, ritmo conservador, request guardado."""

    robots_txt_obey = True
    autothrottle_enabled = True
    concurrent_requests = 4
    concurrent_requests_per_domain = 1
    download_delay = 1.0
    max_consecutive_blocks = 5
    max_bytes: ClassVar[int | None] = DEFAULT_MAX_BYTES
    contact: ClassVar[str | None] = None
    policy_override: ClassVar[str | None] = None
    audit_path: ClassVar[str | Path | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        check_spider_class(cls)

    def __init__(self, crawldir: str | Path | None = None, interval: float = 300.0) -> None:
        if crawldir is not None:
            crawldir = secure_crawldir(crawldir)
        self._stopped_domains: set[str] = set()
        self._block_streak: defaultdict[str, int] = defaultdict(int)
        audit_path = self.audit_path or (Path(crawldir) / "audit.jsonl" if crawldir else None)
        self._audit = AuditLog(audit_path, run_id=uuid.uuid4().hex[:12], spider=self.name)
        super().__init__(crawldir=crawldir, interval=interval)
        upstream = self._session_manager
        guarded = GuardedSessionManager(self)
        try:
            for sid, session in upstream._sessions.items():
                guarded.add(
                    sid,
                    session,
                    default=sid == upstream._default_session_id,
                    lazy=sid in upstream._lazy_sessions,
                )
        except PolicyError as e:
            self._audit.record("policy_error", code=e.code, detail=e.option)
            raise
        self._session_manager = guarded
        if self.development_mode and not self.development_cache_dir:
            # o padrão do upstream é .scrapling_cache/<nome>; o do raspador já está no .gitignore
            self.development_cache_dir = f".raspador-cache/{self.name}"
        if self.policy_override:
            self._audit.record("policy_override", detail=self.policy_override)

    def start(self, use_uvloop: bool = False, **backend_options: Any):
        if self.crawldir is None:
            return super().start(use_uvloop=use_uvloop, **backend_options)
        with crawl_lock(Path(self.crawldir)):
            return super().start(use_uvloop=use_uvloop, **backend_options)

    async def stream(self):
        if self.crawldir is None:
            async for item in super().stream():
                yield item
            return
        with crawl_lock(Path(self.crawldir)):
            async for item in super().stream():
                yield item

    def configure_sessions(self, manager: SessionManager) -> None:
        manager.add("default", spider_session(contact=self.contact))

    async def is_blocked(self, response: Any) -> bool:
        blocked = await super().is_blocked(response)
        domain = _host(response.url)
        if not blocked:
            self._block_streak[domain] = 0
            return False
        self._block_streak[domain] += 1
        if self._block_streak[domain] >= self.max_consecutive_blocks and domain not in self._stopped_domains:
            self._stopped_domains.add(domain)
            self._audit.record(
                "domain_stopped", domain=domain, detail=f"{self._block_streak[domain]} bloqueios seguidos"
            )
        elif domain not in self._stopped_domains:
            self._audit.record("blocked_retry", url=response.url, domain=domain, code=str(response.status))
        return True


class CrawlSpider(Spider, _UpstreamCrawlSpider):
    """`CrawlSpider` do upstream (regras + LinkExtractor) com os padrões e a guarda do raspador."""


class SitemapSpider(Spider, _UpstreamSitemapSpider):
    """`SitemapSpider` do upstream com os padrões e a guarda do raspador."""


class ContentSpider(Spider, _UpstreamContentSpider):
    """Site inteiro para Markdown sanitizado (F12). Não filtra dados pessoais: veja a LGPD antes de exportar."""
