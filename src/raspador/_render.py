"""Página para texto: Markdown, HTML ou texto puro, com sanitização opcional (CLI) ou obrigatória (MCP)."""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urljoin

from scrapling.core.shell import Convertor

Format = Literal["markdown", "html", "text"]

# Alvo de link/imagem Markdown: "](alvo" até espaço (título opcional) ou ")".
_MD_TARGET = re.compile(r"(\]\()([^)\s]+)")


def absolutize_markdown(markdown: str, base_url: str) -> str:
    """Links e imagens relativos viram absolutos: fora do site (arquivo, conversa com o Claude) continuam úteis.
    Absolutos, mailto: e afins passam intactos (urljoin preserva o que já tem esquema)."""
    if not base_url:
        return markdown
    return _MD_TARGET.sub(lambda m: m.group(1) + urljoin(base_url, m.group(2)), markdown)


class InvalidSelector(ValueError):
    code = "RSP-U002"

    def __init__(self, selector: str, cause: Exception) -> None:
        self.selector = selector
        super().__init__(f"{self.code}: seletor CSS inválido {selector!r}: {cause}")


def check_selector(selector: str | None) -> None:
    """Valida o seletor antes de buscar a página: erro de uso, não de rede nem de bug."""
    if not selector:
        return
    from cssselect.parser import SelectorSyntaxError
    from scrapling.parser import Selector

    try:
        Selector("<p></p>").css(selector)
    except SelectorSyntaxError as e:
        raise InvalidSelector(selector, e) from e


def format_for_path(path: str) -> Format:
    if path == "-":
        return "text"
    lower = path.lower()
    if lower.endswith(".md"):
        return "markdown"
    if lower.endswith((".html", ".htm")):
        return "html"
    return "text"


# O sanitizador do upstream não pega estes: atributo `hidden` em qualquer tag, input oculto e metadados do <head>.
_EXTRA_HIDDEN = ".//*[@hidden] | .//input[translate(@type, 'HIDEN', 'hiden')='hidden'] | .//meta | .//link"
# Invisíveis que o upstream mantém: tags Unicode (ASCII smuggling), controles bidi e marcas de direção.
_INVISIBLE = re.compile(r"[\U000e0000-\U000e007f\u202a-\u202e\u2066-\u2069\u200e\u200f\u061c]")


def _sanitized(page: Any, body_only: bool) -> Any:
    base = (page.css("body").first or page) if body_only else page
    clean = Convertor._sanitize_for_ai(Convertor._strip_noise_tags(base))
    for element in list(clean._root.xpath(_EXTRA_HIDDEN)):
        element.drop_tree()
    return clean


def render(page: Any, fmt: Format, selector: str | None = None, sanitize: bool = False) -> str:
    """`markdown` sempre remove o conteúdo oculto que o upstream conhece. `sanitize` (MCP) vai além: remove também
    `hidden`, input oculto, metadados e caracteres invisíveis, em qualquer formato, e no Markdown fica só com o
    <body>."""
    if not sanitize:
        if fmt == "markdown":
            md = page.markdown(css_selector=selector)
            return absolutize_markdown(md, str(getattr(page, "url", "") or ""))
        nodes = page.css(selector) if selector else [page]
    else:
        base = _sanitized(page, body_only=fmt == "markdown")
        nodes = base.css(selector) if selector else [base]
    if fmt == "markdown":
        md = "\n\n".join(Convertor._convert_to_markdown(n.html_content) for n in nodes)
        out = absolutize_markdown(md, str(getattr(page, "url", "") or ""))
    elif fmt == "html":
        out = "\n".join(str(n.html_content) for n in nodes)
    else:
        out = "\n".join(str(n.get_all_text(separator="\n", strip=True)) for n in nodes)
    return _INVISIBLE.sub("", out) if sanitize else out
