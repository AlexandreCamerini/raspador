"""Parser do raspador dentro de um projeto Scrapy.

Só o parsing passa pelo raspador: quem busca as páginas é o Scrapy, com as configurações dele. Para manter a
mesma postura, use no projeto Scrapy `ROBOTSTXT_OBEY = True`, um `USER_AGENT` identificado e
`AUTOTHROTTLE_ENABLED = True`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from scrapling.integrations.scrapy import convert_response as _convert_response
from scrapling.integrations.scrapy import scrapling_response as _scrapling_response

from raspador.adaptive import RaspadorStorage

__all__ = ["convert_response", "scrapling_response"]


def convert_response(response: Any, **selector_config: Any) -> Any:
    """Resposta do Scrapy para o `Response` do Scrapling, com o storage adaptativo do raspador."""
    return _convert_response(response, **{"storage": RaspadorStorage, **selector_config})


def scrapling_response(func: Callable | None = None, **selector_config: Any) -> Callable:
    """Decorador de callback do Scrapy (com ou sem parâmetros), com o storage adaptativo do raspador."""
    return _scrapling_response(func, **{"storage": RaspadorStorage, **selector_config})
