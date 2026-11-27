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
from scrapling.spiders import CSVFeedSpider as _UpstreamCSVFeedSpider
from scrapling.spiders import ShopifySpider as _UpstreamShopifySpider
from scrapling.spiders import SitemapSpider as _UpstreamSitemapSpider
from scrapling.spiders import Spider as _UpstreamSpider
from scrapling.spiders import XMLFeedSpider as _UpstreamXMLFeedSpider
from scrapling.spiders.robotstxt import RobotsTxtManager

from raspador import robots as robots_rules
from raspador._hosts import affinity_key, canonical_host
from raspador._redact import mask_proxy_value, scrub_response
from raspador.audit import AuditLog
from raspador.browser import AsyncBrowserSession
from raspador.crawldir import crawl_lock, secure_crawldir
from raspador.http import (
    DEFAULT_MAX_BYTES,
    HttpSession,
    InvalidURL,
    _PinnedFetcherSession,
    carries_credentials,
    check_redirect_target_async,
    check_size,
    check_url,
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
from raspador.proxies import ProxyPool, entry_url
from raspador.robots import RobotsDenied, RobotsUnavailable

__all__ = [
    "ContentSpider",
    "CrawlRule",
    "CrawlSpider",
    "DomainStopped",
    "LinkExtractor",
    "OffsiteRequest",
    "Request",
    "RobotsDenied",
    "CSVFeedSpider",
    "ShopifySpider",
    "SitemapSpider",
    "Spider",
    "XMLFeedSpider",
]

MAX_REDIRECT_HOPS = 10


class OffsiteRequest(Exception):
    """Request ou redirect para fora de `allowed_domains`."""


class DomainStopped(Exception):
    """Domínio parado depois de bloqueios seguidos."""


def _host(url: str) -> str:
    """Host canônico: grafias do mesmo host (IDN, fullwidth, maiúsculas) não dividem contador de bloqueio nem parada."""
    host = urlsplit(url).hostname or ""
    try:
        return canonical_host(host) if host else ""
    except ValueError:
        return host.lower()


class RaspadorRobots(RobotsTxtManager):
    """Uma busca de robots.txt por domínio, tratamento de status próprio, token `raspador`, TTL."""

    def __init__(self, fetch_fn: Any, is_offsite: Any = None) -> None:
        super().__init__(fetch_fn)
        self._fetched_at: dict[str, float] = {}
        self._failures: dict[str, str] = {}  # domínio -> motivo, enquanto o robots.txt não pôde ser lido
        self._is_offsite = is_offsite or (lambda url: False)
        self.on_denied: Any = None

    async def _get_parser(self, url: str, sid: str) -> Protego:
        try:
            check_url(url)
        except InvalidURL:
            # mailto:, tel:, file://...: não há robots a buscar; o manager recusa e audita com a URL certa
            return Protego.parse("")
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
        erro: BaseException | None = None
        try:
            response = await self._fetch_fn(robots_url, sid)
            status = response.status
            parser = robots_rules.parse(robots_rules.robots_content(status, response.body, response.encoding))
        except Exception as e:
            erro = e
            parser = robots_rules.parse(robots_rules.robots_content(None, b""))
        self._cache[domain] = parser
        reason = robots_rules.failure_reason(status, erro)
        if reason:
            self._failures[domain] = reason
        else:
            self._failures.pop(domain, None)
        # o cache do upstream não tem TTL; aqui a falha expira em minutos
        ttl = robots_rules.ttl_for(status)
        self._fetched_at[domain] = time.monotonic() - (robots_rules.ROBOTS_TTL_SECONDS - ttl)
        return parser

    async def can_fetch(self, url: str, sid: str) -> bool:
        parser = await self._get_parser(url, sid)
        allowed = parser.can_fetch(url, robots_rules.ROBOTS_TOKEN)
        if not allowed and self.on_denied:
            self.on_denied(url, self.failure_for(url))
        return allowed

    def failure_for(self, url: str) -> str | None:
        """Motivo de o robots.txt do domínio não ter sido lido (rede, proxy, 5xx); None se a regra é do site."""
        return self._failures.get(urlsplit(url).netloc)

    def denial(self, url: str) -> RobotsDenied:
        reason = self.failure_for(url)
        return RobotsUnavailable(url, reason) if reason else RobotsDenied(url)

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
        self._robots_clients: dict[str | None, tuple[Any, Any]] = {}  # proxy do navegador -> (sessão, cliente)
        self._egress: dict[str, str | None] = {}  # domínio registrável -> proxy do primeiro acesso no run
        self._pool: ProxyPool | None = None
        self._assigned: set[str] = set()

    def use_pool(self, pool: ProxyPool, contact: str | None) -> None:
        """Uma sessão HTTP por entrada do pool (lazy); todo request HTTP é roteado pelo domínio registrável."""
        for sid, session in self._sessions.items():
            if self._is_browser(sid):
                raise PolicyError(
                    "RSP-P006",
                    "proxy_pool",
                    sid,
                    "o pool v1 é só HTTP; um navegador no mesmo spider sairia por outro egress (e o robots.txt dele "
                    "antes de qualquer checagem).",
                    "rode as páginas de navegador num spider separado, com o proxy fixo do navegador.",
                )
            if getattr(session, "_default_proxy", None):
                raise PolicyError(
                    "RSP-P006",
                    "proxy_pool",
                    sid,
                    "com proxy_pool, uma sessão HTTP com proxy próprio daria dois egress para o mesmo domínio.",
                    "tire o proxy da sessão; quem escolhe o proxy por domínio é o pool (affinity).",
                )
        for entry in pool.entries:
            session = spider_session(contact, proxy=entry_url(entry), **pool.session_kwargs)
            self.add(f"proxy:{entry.label}", session, lazy=True)
        self._pool = pool

    def _route(self, request: Request) -> None:
        # sempre pela URL, inclusive se o sid já for "proxy:...": o robots.txt de um destino de redirect chega aqui
        # com o sid da origem
        if self._pool is None:
            return
        if self._is_browser(request.sid):
            return
        entry = self._pool.entry_for(request.url)
        request.sid = f"proxy:{entry.label}"
        key = affinity_key(request.url)
        if key not in self._assigned:
            self._assigned.add(key)
            self._spider._audit.record(
                "proxy_assigned", url=request.url, domain=key, label=entry.label, group=entry.group
            )

    def add(self, session_id: str, session: Any, *, default: bool = False, lazy: bool = False):
        if isinstance(session, AsyncBrowserSession):
            session._check_robots = False  # o engine já consultou; a URL final é checada pela própria sessão
            # duck typing: o SessionManager só usa __aenter__, __aexit__, _is_alive e fetch
            return super().add(session_id, cast(Any, session), default=default, lazy=lazy)
        if not isinstance(session, FetcherSession) or type(session) not in (FetcherSession, _PinnedFetcherSession):
            raise PolicyError(
                "RSP-P007",
                "session",
                type(session).__name__,
                "só entram no spider a sessão HTTP compliant e o navegador do raspador; as de navegador do "
                "upstream usam patchright.",
                "use raspador.http.spider_session() ou raspador.browser.AsyncBrowserSession().",
            )
        check_session(session)
        for attr, opcao in (("_default_proxies", "proxies"), ("_default_proxy_auth", "proxy_auth")):
            if getattr(session, attr, None):
                raise PolicyError(
                    "RSP-P006",
                    opcao,
                    "***",
                    "proxy por esquema ou credencial separada escapam da checagem de um egress por domínio.",
                    "use raspador.http.spider_session(proxy='http://usuario:senha@host:porta').",
                )
        if type(session) is FetcherSession:
            session.__class__ = _PinnedFetcherSession  # trust_env=False também na sessão crua do usuário
        return super().add(session_id, session, default=default, lazy=lazy)

    def _audit_robots(self, url: str, reason: str | None) -> None:
        if reason:
            self._spider._audit.record(
                "robots_unavailable", url=url, domain=_host(url), code=RobotsUnavailable.code, reason=reason
            )
        else:
            self._spider._audit.record("robots_denied", url=url, domain=_host(url))

    def _is_browser(self, sid: str | None) -> bool:
        if (sid or "").startswith("proxy:"):
            return False  # sids do pool são sempre HTTP, mesmo de uma entrada que não existe mais (é re-roteado)
        try:
            return isinstance(self.get(sid or self.default_session_id), AsyncBrowserSession)
        except KeyError:
            return False

    async def close(self) -> None:
        await super().close()
        for sessao, _ in self._robots_clients.values():
            await sessao.__aexit__(None, None, None)
        self._robots_clients.clear()

    async def start(self) -> None:
        await super().start()
        engine = getattr(self._spider, "_engine", None)
        if engine is not None and getattr(engine, "_robots_manager", None) is not None:
            self._robots = RaspadorRobots(self._fetch_robots, is_offsite=self._is_offsite)
            self._robots.on_denied = self._audit_robots
            engine._robots_manager = self._robots

    async def _fetch_robots(self, url: str, sid: str):
        if self._is_browser(sid):
            # robots.txt não precisa de navegador: vai por HTTP identificado, sem abrir aba, mas pelo mesmo egress
            # da sessão de navegador e só depois da checagem de um egress por domínio
            self._check_egress(Request(url, sid=sid), _host(url))
            nav = cast(AsyncBrowserSession, self.get(sid or self.default_session_id))
            if nav._proxy not in self._robots_clients:
                contact = nav._contact or self._spider.contact
                sessao = HttpSession(contact, proxy=nav._proxy) if nav._proxy else HttpSession(contact)
                self._robots_clients[nav._proxy] = (sessao, await sessao.__aenter__())
            return await self._robots_clients[nav._proxy][1]._client.get(url, follow_redirects="safe")
        return await self._guarded_fetch(Request(url, sid=sid), check_robots=False)

    async def fetch(self, request: Request):
        # o engine do upstream anota o proxy do request em stats.proxies logo antes de chamar fetch, e as stats saem
        # no log final e em CrawlResult: mascara a credencial antes que alguém as leia
        stats = getattr(getattr(self._spider, "_engine", None), "stats", None)
        if stats is not None and stats.proxies:
            stats.proxies[:] = [mask_proxy_value(p) for p in stats.proxies]
        opcao = next((k for k in ("proxy", "proxies") if k in request._session_kwargs), None)
        if opcao is not None:
            e = PolicyError(
                "RSP-P006",
                opcao,
                request._session_kwargs[opcao],
                "proxy por request permite trocar de proxy depois de um bloqueio, o que é evasão de rate limit.",
                "defina um proxy fixo na sessão: raspador.http.spider_session(proxy=...).",
            )
            self._spider._audit.record(
                "policy_error", url=request.url, domain=_host(request.url), code=e.code, detail=e.option
            )
            raise e
        return await self._guarded_fetch(request, check_robots=True)

    def _is_offsite(self, url: str) -> bool:
        # mesma forma canônica dos dois lados: allowed_domains={"müller.com"} casa com xn--mller-kva.com
        allowed = {_host(f"http://{d}/") for d in self._spider.allowed_domains or ()}
        host = _host(url)
        return bool(allowed) and not any(host == d or host.endswith("." + d) for d in allowed)

    async def _guarded_fetch(self, request: Request, *, check_robots: bool):
        spider = self._spider
        domain = _host(request.url)
        try:
            check_url(request.url)
        except InvalidURL as e:
            spider._audit.record("policy_error", url=request.url, domain=domain, code=e.code, detail="url")
            raise
        if domain in spider._stopped_domains:
            raise DomainStopped(domain)
        self._check_offsite(request.url)
        original = request
        if self._pool is not None:
            # roteia uma cópia: o sid do usuário segue no fingerprint (dedup) e no follow() das respostas
            request = request.copy()
            self._route(request)
        self._check_egress(request, domain)
        browser_sid = self._is_browser(request.sid)
        try:
            if browser_sid:
                check_browser_kwargs(request._session_kwargs, url=request.url)
            else:
                check_request_kwargs(request._session_kwargs, url=request.url)
            verify = request._session_kwargs.get("verify")
            if self._pool is not None and verify is not None and verify is not True and not isinstance(verify, str):
                raise PolicyError(
                    "RSP-P010",
                    "verify",
                    verify,
                    "com proxy_pool, desligar a verificação TLS deixa qualquer proxy do pool ler e alterar o HTTPS.",
                    "mantenha verify=True; para CA corporativa use verify='/caminho/ca.pem'.",
                )
        except PolicyError as e:
            spider._audit.record("policy_error", url=request.url, domain=domain, code=e.code, detail=e.option)
            raise
        if browser_sid:
            # o navegador segue redirects sozinho (e checa robots da URL final); aqui só o domínio final
            response = await self._fetch_upstream(request)
            self._check_offsite(response.url)
            check_size(response, spider.max_bytes)
            return response
        request._session_kwargs.pop("follow_redirects", None)
        response = await self._fetch_upstream(request)
        hops = 0
        while 300 <= response.status < 400 and hops < MAX_REDIRECT_HOPS:
            location = response.headers.get("location") or response.headers.get("Location")
            if not location:
                break
            target = urljoin(response.url, location)
            check_url(target)  # Location: file:///... não é seguido
            self._check_offsite(target)
            await check_redirect_target_async(response.url, target)
            cross_host = _host(target) != _host(response.url)
            if cross_host and carries_credentials(
                getattr(self.get(request.sid or self.default_session_id), "_default_headers", None)
            ):
                break  # credencial da sessão não pode ser retirada por salto: não segue
            if check_robots and self._robots and not await self._robots.can_fetch(target, request.sid):
                raise self._robots.denial(target)
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
            self._route(hop)  # destino em outro domínio sai pelo proxy do destino
            self._check_egress(hop, _host(target))
            response = await self._fetch_upstream(hop)
            hops += 1
        check_size(response, spider.max_bytes)
        response.request = original
        return response

    async def _fetch_upstream(self, request: Request):
        return scrub_response(await super().fetch(request))

    def _egress_of(self, sid: str | None) -> str | None:
        session = self.get(sid or self.default_session_id)
        proxy = getattr(session, "_default_proxy", None) or getattr(session, "_proxy", None)
        if not proxy:
            return None
        p = urlsplit(proxy)  # mesma saída escrita de outro jeito (maiúsculas, barra final) não é outro egress
        return f"{p.scheme.lower()}://{p.username or ''}@{(p.hostname or '').lower()}:{p.port or ''}"

    def _check_egress(self, request: Request, domain: str) -> None:
        """Um egress (proxy ou conexão direta) por domínio por run, entre todos os sids. Trocar de sid para sair por
        outro proxy no mesmo domínio é o ProxyRotator por outro caminho (RSP-P006)."""
        try:
            key = affinity_key(request.url)
        except ValueError:
            key = domain.rstrip(".")
        egress = self._egress_of(request.sid)
        first = self._egress.setdefault(key, egress)
        if first != egress:
            e = PolicyError(
                "RSP-P006",
                "sid",
                request.sid,
                "o domínio já foi acessado por outro proxy neste run; trocar de sessão para mudar o IP de saída é "
                "evasão de rate limit ou de bloqueio por IP.",
                "use uma sessão (um proxy) por domínio; proxies diferentes servem para domínios diferentes.",
            )
            self._spider._audit.record("policy_error", url=request.url, domain=domain, code=e.code, detail="sid")
            raise e

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
    proxy_pool: ClassVar[ProxyPool | None] = None

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
        if self.proxy_pool is not None:
            try:
                guarded.use_pool(self.proxy_pool, self.contact)
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


class XMLFeedSpider(Spider, _UpstreamXMLFeedSpider):
    """Feed XML/RSS nó a nó, com os padrões e a guarda do raspador."""


class CSVFeedSpider(Spider, _UpstreamCSVFeedSpider):
    """Feed CSV linha a linha, com os padrões e a guarda do raspador."""


class ShopifySpider(Spider, _UpstreamShopifySpider):
    """Produtos públicos de uma loja Shopify (JSON da própria loja). Respeite os termos de uso da loja."""
