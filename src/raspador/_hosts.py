"""Host canônico e domínio registrável: a forma que o curl de fato acessa, para comparar hosts sem ser enganado por
grafias (IDN, fullwidth, maiúsculas, ponto final, IPv4 em decimal ou hexadecimal)."""

from __future__ import annotations

import ipaddress
import re
import socket
import unicodedata
from urllib.parse import urlsplit

import idna
from publicsuffixlist import PublicSuffixList

_PSL = PublicSuffixList()  # lista embutida no pacote: sem rede
_NUMERIC_HOST = re.compile(r"^[0-9a-fx.]+$", re.IGNORECASE)


def canonical_host(host: str) -> str:
    """Forma que o curl de fato acessa: IDN e fullwidth em punycode (UTS 46), IPv4 em qualquer notação na forma
    pontuada, minúsculas, sem ponto final. Host que não converte levanta ValueError."""
    host = host.strip().rstrip(".").rstrip("\u3002\uff0e\uff61")
    if not host:
        raise ValueError("host vazio")
    if any(unicodedata.category(c) in {"Cf", "Cc", "Zs", "Zl", "Zp"} for c in host):
        # caractere invisível (soft hyphen, zero-width): o UTS 46 apaga, e cada cliente pode apagar diferente
        raise ValueError("host com caractere invisível")
    try:
        return str(ipaddress.ip_address(host.strip("[]")))
    except ValueError:
        pass
    if _NUMERIC_HOST.match(host):
        try:
            return socket.inet_ntoa(socket.inet_aton(host))  # 1572395042, 0x5d.0xb8.0xd8.0x22
        except OSError:
            pass
    if host.isascii():
        host = host.lower()
    else:
        try:
            host = idna.encode(host, uts46=True, std3_rules=False).decode()
        except idna.IDNAError as e:
            raise ValueError(f"host IDN inválido: {e}") from None
    if any(not label for label in host.split(".")):
        raise ValueError(f"host com rótulo vazio: {host!r}")
    return host


def affinity_key(url: str) -> str:
    """Domínio registrável (eTLD+1) do host canônico, sem porta nem userinfo. IP fica como está."""
    netloc = urlsplit(url).netloc.rpartition("@")[2]
    if netloc.startswith("["):
        host = netloc[1:].partition("]")[0]
    else:
        host = netloc.rpartition(":")[0] if netloc.count(":") == 1 else netloc
    host = canonical_host(host)
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        return _PSL.privatesuffix(host) or host
