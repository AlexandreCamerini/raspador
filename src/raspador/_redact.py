"""Mascaramento de credencial (`esquema://usuario:senha@host`, `usuario:senha@host`, opções de autenticação).

Ponto único usado por mensagens de erro, CLI, auditoria, stats, meta de resposta e pelo log do upstream. Mascara
usuário e senha juntos: em provedores de proxy o "usuário" costuma carregar a chave da conta ou o id da sessão.
"""

from __future__ import annotations

import logging
import re
from typing import Any

# userinfo até o último "@" da autoridade (senha com "@" cru não deixa sobra)
_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/?#'\"]*@")
# sem esquema, que o curl aceita como proxy: "usuario:senha@host[:porta]"
_BARE_USERINFO = re.compile(r"(?<![\w.+\-/@:])[^\s/?#'\"@:=]+:[^\s/?#'\"]*@(?=[\w\[])")

# opções cujo valor inteiro é segredo, não importa o formato (tupla, dict de curl_options, bytes)
SECRET_OPTIONS = frozenset({"proxy_auth", "auth", "curl_options", "cert", "proxy_headers"})


def redact(text: str) -> str:
    return _BARE_USERINFO.sub("***@", _USERINFO.sub(r"\1***@", text))


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, bytes):
        return redact(value.decode("utf-8", "replace")).encode()
    if isinstance(value, dict):
        return {redact_value(k): redact_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return type(value)(redact_value(v) for v in value)
    return value


def mask_proxy(value: Any) -> str:
    """Para URL de proxy, inclusive malformada (`#`, `/` ou `?` cru na senha quebram o parse e o regex): tudo antes
    do último `@` some."""
    texto = str(value)
    if "@" not in texto:
        return texto
    esquema, sep, _ = texto.partition("://")
    return (f"{esquema}://" if sep else "") + "***@" + texto.rpartition("@")[2]


def redact_option(option: str, value: Any) -> Any:
    base = option.split("[", 1)[0].lower()
    if base == "proxy" and isinstance(value, str):
        return mask_proxy(value)
    if base in SECRET_OPTIONS or "pass" in base or "auth" in base:
        return "***"
    return redact_value(value)


_installed = False


def install_log_redaction() -> None:
    """Mascara credencial em todo registro de log do Scrapling e do raspador, na criação do registro.

    Filtro de logger não pega os loggers filhos (`scrapling.spiders.<nome>`) nem handlers de quem chama; a fábrica de
    registros pega. Só toca registros desses dois namespaces.
    """
    global _installed
    if _installed:
        return
    anterior = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = anterior(*args, **kwargs)
        if record.name.startswith(("scrapling", "raspador")):
            mensagem = record.getMessage()
            limpa = redact(mensagem)
            if limpa != mensagem:
                record.msg, record.args = limpa, None
        return record

    logging.setLogRecordFactory(factory)
    _installed = True


def scrub_response(response: Any) -> Any:
    """O upstream grava `meta={"proxy": url_com_senha}` na resposta; `follow()` copia para o próximo request e o
    checkpoint do crawldir faz pickle dele."""
    meta = getattr(response, "meta", None)
    if isinstance(meta, dict) and meta.get("proxy") is not None:
        meta["proxy"] = mask_proxy_value(meta["proxy"])
    return response


def mask_proxy_value(value: Any) -> Any:
    """URL de proxy (str, ou dict esquema->URL): máscara forte, que não depende de a URL ser bem formada."""
    if isinstance(value, str):
        return mask_proxy(value)
    if isinstance(value, dict):
        return {k: mask_proxy_value(v) for k, v in value.items()}
    return redact_value(value)
