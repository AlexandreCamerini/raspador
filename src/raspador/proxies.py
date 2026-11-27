"""ProxyPool v1: afinidade estática por domínio registrável, sem failover.

Para que serve: egress por região (conteúdo que muda por país) e repartir domínios entre os proxies do operador.
O que não faz, por política (replica/plano-seguranca-proxypool.md):

- não distribui um domínio por vários IPs: cada domínio registrável (eTLD+1) sai sempre pela mesma entrada;
- não troca de proxy por bloqueio, erro ou retry: proxy fora do ar é falha de rede do request (sem failover, sem
  conexão direta);
- não muda identidade: User-Agent, contato e headers são os da sessão, iguais em todas as entradas.

A URL de cada entrada (com credencial) só é lida para criar a sessão; `repr`, auditoria e checkpoint usam o label.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

from raspador._hosts import affinity_key, canonical_host  # noqa: F401 (reexport)
from raspador.policy import PolicyError, check_headers, check_proxy, check_request_kwargs

_LABEL = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


POOL_SCHEMES = frozenset({"http", "https", "socks5h"})
_POOL_HEADERS = frozenset({"accept", "accept-language", "accept-encoding", "user-agent"})
# Por request, com pool: os da sessão mais os de conteúdo e cache. Allowlist, como na sessão: `X-Api-Key`,
# `X-Auth-Token` e afins são credencial com outro nome.
POOL_REQUEST_HEADERS = _POOL_HEADERS | frozenset(
    {
        "referer",
        "origin",
        "content-type",
        "cache-control",
        "pragma",
        "if-none-match",
        "if-modified-since",
        "range",
    }
)


class ProxyEntry:
    """Um proxy do pool. `label` aparece em auditoria e erros; a URL nunca."""

    __slots__ = ("_url", "group", "label")

    def __init__(self, url: str, *, label: str, group: str = "default") -> None:
        check_proxy(url)
        if urlsplit(url).scheme.lower() not in POOL_SCHEMES:
            raise PolicyError(
                "RSP-P010",
                "proxy",
                url,
                "socks4/socks4a/socks5 resolvem o DNS do alvo localmente (ou não autenticam): o resolvedor do "
                "operador vê cada domínio raspado.",
                "use http://, https:// ou socks5h:// (resolve no proxy).",
            )
        for nome, valor in (("label", label), ("group", group)):
            if not _LABEL.match(valor):
                raise ValueError(f"{nome} inválido {valor!r}: use [a-z0-9_-], até 32 caracteres")
        self._url = url
        self.label = label
        self.group = group

    def __repr__(self) -> str:
        return f"ProxyEntry(label={self.label!r}, group={self.group!r})"

    __str__ = __repr__


class ProxyPool:
    """Pool com afinidade estática. `affinity` mapeia domínio registrável para um label ou um grupo."""

    def __init__(
        self,
        entries: Iterable[ProxyEntry],
        *,
        affinity: Mapping[str, str] | None = None,
        default_group: str | None = None,
        session_kwargs: Mapping[str, Any] | None = None,
    ) -> None:
        self._entries = list(entries)
        if not self._entries:
            raise ValueError("ProxyPool precisa de pelo menos uma entrada")
        labels = [e.label for e in self._entries]
        if len(set(labels)) != len(labels):
            raise ValueError(f"labels repetidos no ProxyPool: {sorted(labels)}")
        self._by_label = {e.label: e for e in self._entries}
        self._groups: dict[str, list[ProxyEntry]] = {}
        for e in self._entries:
            self._groups.setdefault(e.group, []).append(e)
        if default_group is None:
            if len(self._groups) > 1:
                raise ValueError("ProxyPool com vários grupos precisa de default_group")
            default_group = self._entries[0].group
        if default_group not in self._groups:
            raise ValueError(f"default_group {default_group!r} não existe no pool")
        self.default_group = default_group
        self._affinity: dict[str, str] = {}
        origem: dict[str, str] = {}
        for dominio, alvo in (affinity or {}).items():
            if not isinstance(dominio, str) or re.search(r"[/*\s]|://", dominio):
                raise ValueError(f"affinity[{dominio!r}]: use só o domínio, ex.: 'loja.com.br' (sem esquema, / ou *)")
            if alvo not in self._by_label and alvo not in self._groups:
                raise ValueError(f"affinity[{dominio!r}] aponta para {alvo!r}, que não é label nem grupo do pool")
            key = affinity_key(f"http://{dominio}/")
            if key in origem:
                raise ValueError(
                    f"affinity[{dominio!r}] e affinity[{origem[key]!r}] são o mesmo site ({key}); a afinidade é por "
                    "domínio registrável, um destino só"
                )
            origem[key] = dominio
            self._affinity[key] = alvo
        kwargs = dict(session_kwargs or {})
        check_request_kwargs(kwargs)
        if "proxy" in kwargs:
            raise ValueError("session_kwargs não leva proxy: o proxy vem da entrada do pool")
        if (
            "cookies" in kwargs
            or "cert" in kwargs
            or any(str(k).lower() in {"authorization", "cookie"} for k in (kwargs.get("headers") or {}))
        ):
            raise PolicyError(
                "RSP-P010",
                "session_kwargs",
                "***",
                "as sessões do pool atendem todos os domínios: credencial aqui iria para todos eles (e robots.txt).",
                "credencial por site fica fora do pool v1; use um spider só para o site autenticado, com proxy fixo.",
            )
        fora = [k for k in (kwargs.get("headers") or {}) if str(k).lower() not in _POOL_HEADERS]
        if fora:
            raise PolicyError(
                "RSP-P010",
                "session_kwargs.headers",
                sorted(fora),
                "as sessões do pool atendem todos os domínios: um header próprio (chave de API, token) iria para "
                "todos eles; só passam " + ", ".join(sorted(_POOL_HEADERS)) + ".",
                "credencial por site fica fora do pool v1; use um spider só para o site autenticado, com proxy fixo.",
            )
        check_headers(kwargs.get("headers"))
        if kwargs.get("verify") is False:
            raise PolicyError(
                "RSP-P010",
                "verify",
                False,
                "sem verificação TLS, qualquer proxy do pool pode ler e alterar o tráfego HTTPS.",
                "mantenha verify=True; para CA corporativa use verify='/caminho/ca.pem'.",
            )
        self.session_kwargs = kwargs

    @property
    def entries(self) -> list[ProxyEntry]:
        return list(self._entries)

    def entry_for(self, url: str) -> ProxyEntry:
        key = affinity_key(url)
        alvo = self._affinity.get(key, self.default_group)
        if alvo in self._by_label:
            return self._by_label[alvo]
        candidatos = self._groups[alvo]
        # rendezvous hashing: estável entre runs, e remover uma entrada só move os domínios dela
        return max(candidatos, key=lambda e: hashlib.sha256(f"{key}|{e.label}".encode()).digest())

    def __repr__(self) -> str:
        grupos = {g: [e.label for e in es] for g, es in self._groups.items()}
        return f"ProxyPool(groups={grupos!r}, default_group={self.default_group!r})"

    __str__ = __repr__


def entry_url(entry: ProxyEntry) -> str:
    """Única leitura da URL com credencial: ao criar a sessão do pool."""
    return entry._url
