"""Página para texto: Markdown, HTML ou texto puro, com sanitização opcional (CLI) ou obrigatória (MCP)."""

from __future__ import annotations

from typing import Any, Literal

from scrapling.core.shell import Convertor

Format = Literal["markdown", "html", "text"]


def format_for_path(path: str) -> Format:
    if path == "-":
        return "text"
    lower = path.lower()
    if lower.endswith(".md"):
        return "markdown"
    if lower.endswith((".html", ".htm")):
        return "html"
    return "text"


def render(page: Any, fmt: Format, selector: str | None = None, sanitize: bool = False) -> str:
    """`markdown` sempre remove o conteúdo oculto (upstream); `sanitize` faz o mesmo em html e texto e, no
    Markdown, fica só com o <body>."""
    if fmt == "markdown":
        return page.markdown(css_selector=selector, main_content_only=sanitize)
    base = Convertor._sanitize_for_ai(Convertor._strip_noise_tags(page)) if sanitize else page
    nodes = base.css(selector) if selector else [base]
    if fmt == "html":
        return "\n".join(str(n.html_content) for n in nodes)
    return "\n".join(str(n.get_all_text(separator="\n", strip=True)) for n in nodes)
