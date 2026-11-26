"""Política do raspador.

Modelo de ameaça: evitar acidente e configuração errada, não impedir sabotagem. Quem importa
`scrapling` direto passa por cima desta camada.

A regra é uma allowlist: o upstream repassa ao curl_cffi qualquer kwarg que não conheça
(`ja3`, `akamai`, `extra_fp`...), então negar uma lista nunca fecha o buraco.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from raspador import __version__
from raspador._hosts import canonical_host
from raspador._redact import mask_proxy, redact_option

USER_AGENT_PREFIX = "raspador/"
MIN_DOWNLOAD_DELAY = 0.5
MAX_SLOTS_PER_DOMAIN = 4

# Kwargs aceitos numa requisição HTTP (avulsa, de sessão ou de Request em spider).
ALLOWED_REQUEST_KWARGS = frozenset(
    {
        "method",
        "headers",
        "params",
        "data",
        "json",
        "files",
        "multipart",
        "cookies",
        "timeout",
        "verify",
        "cert",
        "follow_redirects",
        "max_redirects",
        "retries",
        "retry_delay",
        "proxy",
        "selector_config",
        # `Response.follow()` do upstream grava o Referer aqui; é validado como header abaixo
        "extra_headers",
    }
)

# Kwargs que o upstream usa para disfarce. Só passam com o valor neutro.
_NEUTRAL_VALUES: dict[str, tuple[Any, ...]] = {
    "impersonate": (None,),
    "stealth": (False, None),
    "stealthy_headers": (False, None),
    "google_search": (False, None),
}

_EVASION_KWARGS = frozenset(
    {
        "impersonate",
        "stealth",
        "stealthy_headers",
        "solve_cloudflare",
        "hide_canvas",
        "block_webrtc",
        "google_search",
        "ja3",
        "akamai",
        "extra_fp",
        "default_headers",
        "http_version",
        "http3",
        "real_chrome",
    }
)

_FORBIDDEN_HEADER_PREFIXES = ("sec-ch-ua", "sec-fetch-")
_FORBIDDEN_HEADERS = frozenset({"x-forwarded-for", "client-ip", "forwarded", "x-real-ip", "true-client-ip"})


PROXY_SCHEMES = ("http", "https", "socks4", "socks4a", "socks5", "socks5h")


class InvalidProxy(ValueError):
    """Proxy sem esquema explícito: o curl aceita `usuario:senha@host`, e aí nada o reconhece como URL."""

    code = "RSP-U003"

    def __init__(self, value: Any) -> None:
        self.value = mask_proxy(value)
        super().__init__(
            f"{self.code}: proxy inválido {self.value!r}; use um esquema explícito ({', '.join(PROXY_SCHEMES)}), "
            "ex.: 'http://host:porta'."
        )


_USERINFO_OK = re.compile(r"^(?:[A-Za-z0-9\-._~!$&()*+,;=:]|%[0-9A-Fa-f]{2})*$")


def check_proxy(value: Any) -> None:
    if value is None:
        return
    # esquema explícito, host, porta válida e nada além: `#`, `/` ou `?` cru na senha viram fragmento, caminho ou
    # query no parse; a senha precisa vir em percent-encoding (`%23`, `%2F`, `%3F`)
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        raise InvalidProxy(value)  # urlsplit descarta tab e quebra de linha; o curl recebe a string crua
    parts = urlsplit(value)
    if parts.scheme.lower() not in PROXY_SCHEMES or not parts.hostname:
        raise InvalidProxy(value)
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise InvalidProxy(value)
    try:
        _ = parts.port  # ValueError para porta não numérica ou fora de 0-65535
    except ValueError:
        raise InvalidProxy(value) from None
    # userinfo só com unreserved, sub-delims sem aspas e %XX: aspas, espaço, tab, "<" e "\\" crus quebram o
    # mascaramento de log e meta; a senha precisa vir em percent-encoding
    if not _USERINFO_OK.match(parts.netloc.rpartition("@")[0]):
        raise InvalidProxy(value)


class PolicyError(ValueError):
    """Uma opção pedida contraria a política do raspador."""

    def __init__(self, code: str, option: str, value: Any, reason: str, alternative: str) -> None:
        self.code = code
        self.option = option
        self.value = redact_option(option, value)  # o segredo não fica nem no atributo
        self.reason = reason
        self.alternative = alternative
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"{self.code}: a opção {self.option}={self.value!r} não é permitida.\n"
            f"  motivo: {self.reason}\n"
            f"  em vez disso: {self.alternative}"
        )

    def __repr__(self) -> str:
        return f"PolicyError({self.code!r}, option={self.option!r})"


def default_user_agent(contact: str | None = None) -> str:
    """User-Agent identificado. `contact` é um e-mail ou URL para o dono do site falar com você."""
    base = f"{USER_AGENT_PREFIX}{__version__}"
    return f"{base} (+{contact})" if contact else base


def _host(url: str | None) -> str:
    """Host canônico (IDN em punycode, fullwidth, ponto final): `müller.com` e `xn--mller-kva.com` são o mesmo site."""
    host = (urlsplit(url).hostname or "") if url else ""
    try:
        return canonical_host(host) if host else ""
    except ValueError:
        return host.lower()


def _same_site(a: str, b: str) -> bool:
    return bool(a) and bool(b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def check_headers(headers: Mapping[str, Any] | None, url: str | None = None) -> None:
    """Valida headers sem diferenciar maiúsculas. `url` é o alvo, usado para validar o Referer."""
    if headers is not None and not isinstance(headers, Mapping):
        raise TypeError(f"headers precisa ser um dict {{'Nome': 'valor'}}, não {type(headers).__name__}")
    for name, value in (headers or {}).items():
        key = name.lower()
        if key == "proxy-authorization":
            raise PolicyError(
                "RSP-P003",
                f"headers[{name!r}]",
                "***",
                "em túnel HTTPS o libcurl manda header extra para o alvo, não para o proxy: a credencial vazaria.",
                "ponha a credencial na URL do proxy (proxy='http://usuario:senha@host:porta' ou RASPADOR_PROXY).",
            )
        if key in _FORBIDDEN_HEADERS or key.startswith(_FORBIDDEN_HEADER_PREFIXES):
            raise PolicyError(
                "RSP-P003",
                f"headers[{name!r}]",
                value,
                "esse header serve para se passar por navegador ou esconder a origem da requisição.",
                "remova o header; o raspador se identifica pelo User-Agent.",
            )
        if key == "user-agent" and not str(value).startswith(USER_AGENT_PREFIX):
            raise PolicyError(
                "RSP-P003",
                f"headers[{name!r}]",
                value,
                "o User-Agent precisa identificar o raspador para o dono do site saber quem acessa.",
                f"use raspador.policy.default_user_agent(contact=...), que gera '{USER_AGENT_PREFIX}...'.",
            )
        if key in {"referer", "origin"} and url and not _same_site(_host(str(value)), _host(url)):
            raise PolicyError(
                "RSP-P003",
                f"headers[{name!r}]",
                value,
                "Referer ou Origin de outro site finge uma navegação que não aconteceu.",
                "deixe sem Referer, ou use uma página do próprio site alvo.",
            )


def check_request_kwargs(kwargs: Mapping[str, Any], url: str | None = None) -> None:
    """Valida os kwargs de uma requisição contra a allowlist e a regra de headers."""
    for name, value in kwargs.items():
        if name in _NEUTRAL_VALUES and value in _NEUTRAL_VALUES[name]:
            continue
        if name in _EVASION_KWARGS:
            raise PolicyError(
                "RSP-P002",
                name,
                value,
                "imitar navegador, impressão digital TLS ou resolver desafios anti-bot é evasão de detecção.",
                "não há alternativa no raspador; ele acessa como cliente identificado.",
            )
        if name not in ALLOWED_REQUEST_KWARGS:
            raise PolicyError(
                "RSP-P001",
                name,
                value,
                "a opção não está na lista de opções permitidas; o upstream a repassaria direto ao cliente HTTP.",
                "use só: " + ", ".join(sorted(ALLOWED_REQUEST_KWARGS)) + ".",
            )
    check_proxy(kwargs.get("proxy"))
    check_headers(kwargs.get("headers"), url=url)
    check_headers(kwargs.get("extra_headers"), url=url)


# Opções aceitas pelo adaptador de navegador do raspador (Playwright puro). `init_script`, `extra_flags` e
# `additional_args` ficam fora: são exatamente os ganchos usados para patch de fingerprint.
ALLOWED_BROWSER_KWARGS = frozenset(
    {
        "wait_selector",
        "wait_selector_state",
        "network_idle",
        "load_dom",
        "timeout",
        "wait",
        "disable_resources",
        "page_action",
        "page_setup",
        "locale",
        "extra_headers",
        # `Response.follow()` grava o Referer em `headers`; no navegador vira extra_headers
        "headers",
        "selector_config",
        "max_bytes",
    }
)

_BROWSER_CREDENTIAL_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie"})


def check_browser_kwargs(kwargs: Mapping[str, Any], url: str | None = None) -> None:
    """Valida opções de navegador. `google_search=False` (que o `follow()` do upstream grava) é neutro."""
    for name, value in kwargs.items():
        if name in _NEUTRAL_VALUES and value in _NEUTRAL_VALUES[name]:
            continue
        if name in _EVASION_KWARGS or name in {"useragent", "init_script", "extra_flags", "additional_args"}:
            raise PolicyError(
                "RSP-P002",
                name,
                value,
                "a opção serve para disfarçar o navegador ou mexer na impressão digital dele.",
                "não há alternativa no raspador; o navegador acessa identificado como raspador.",
            )
        if name not in ALLOWED_BROWSER_KWARGS:
            raise PolicyError(
                "RSP-P001",
                name,
                value,
                "a opção não está na lista de opções de navegador permitidas.",
                "use só: " + ", ".join(sorted(ALLOWED_BROWSER_KWARGS)) + ".",
            )
    for key in ("headers", "extra_headers"):
        for name in kwargs.get(key) or {}:
            if name.lower() in _BROWSER_CREDENTIAL_HEADERS:
                raise PolicyError(
                    "RSP-P003",
                    f"{key}[{name!r}]",
                    "***",
                    "no navegador o header extra vai para toda requisição da página, inclusive CDN e analytics "
                    "de terceiros.",
                    "faça login uma vez e reutilize com save_state/load_state (storage_state).",
                )
        check_headers(kwargs.get(key), url=url)


def check_session(session: Any) -> None:
    """Valida o estado real de uma sessão HTTP do upstream antes de usá-la num spider."""
    impersonate = getattr(session, "_default_impersonate", None)
    stealth = getattr(session, "_stealth", False)
    if impersonate is not None or stealth:
        raise PolicyError(
            "RSP-P007",
            "session",
            f"impersonate={impersonate!r}, stealthy_headers={stealth!r}",
            "a sessão foi criada com os padrões do upstream, que se disfarçam de Chrome.",
            "crie a sessão com raspador.http.spider_session().",
        )
    if getattr(session, "_proxy_rotator", None) is not None:
        raise PolicyError(
            "RSP-P006",
            "proxy_rotator",
            "ProxyRotator",
            "o upstream troca de proxy a cada tentativa, inclusive depois de um bloqueio.",
            "use um proxy fixo por sessão (proxy='http://...') para geolocalização.",
        )
    headers = getattr(session, "_default_headers", None) or {}
    if not any(k.lower() == "user-agent" for k in headers):
        raise PolicyError(
            "RSP-P003",
            "headers['User-Agent']",
            None,
            "sem User-Agent definido, o cliente HTTP manda um genérico que não identifica o raspador.",
            "crie a sessão com raspador.http.spider_session().",
        )
    check_headers(headers)


def check_spider_class(cls: type) -> None:
    """Valida os atributos de classe de um spider. Chamado em `__init_subclass__`."""
    if getattr(cls, "robots_txt_obey", True) is not True:
        raise PolicyError(
            "RSP-P004",
            "robots_txt_obey",
            getattr(cls, "robots_txt_obey", None),
            "o robots.txt é obrigatório no raspador e não tem override.",
            "se o site é seu, ajuste o robots.txt dele.",
        )
    override = getattr(cls, "policy_override", None)
    delay = getattr(cls, "download_delay", MIN_DOWNLOAD_DELAY)
    slots = getattr(cls, "concurrent_requests_per_domain", 1)
    if override:
        return
    if delay < MIN_DOWNLOAD_DELAY:
        raise PolicyError(
            "RSP-P005",
            "download_delay",
            delay,
            f"abaixo de {MIN_DOWNLOAD_DELAY}s por domínio o crawl pode sobrecarregar o site.",
            'declare policy_override = "motivo" na classe; o motivo vai para o log de auditoria.',
        )
    if not 1 <= slots <= MAX_SLOTS_PER_DOMAIN:
        raise PolicyError(
            "RSP-P005",
            "concurrent_requests_per_domain",
            slots,
            f"0 significa sem limite; acima de {MAX_SLOTS_PER_DOMAIN} o crawl pode sobrecarregar o site.",
            'use de 1 a 4, ou declare policy_override = "motivo" na classe.',
        )
