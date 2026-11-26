"""Primitivos de saída do terminal (replica/design/components.md).

Regras: significado sempre em palavras; sem matiz ANSI (só vídeo reverso e negrito, cujo contraste é o do
tema do usuário); estilo só em TTY, sem NO_COLOR e com TERM != dumb; stdout é dado, stderr é para pessoas.
"""

from __future__ import annotations

import os
import sys
import unicodedata
from typing import IO, Literal

ColorMode = Literal["auto", "always", "never"]

EXIT_OK = 0
EXIT_BUG = 1
EXIT_USAGE = 2
EXIT_POLICY = 3
EXIT_EMPTY = 4
EXIT_NETWORK = 5
EXIT_BLOCKED = 6
EXIT_FILE = 7

REVERSE_BOLD = "1;7"
BOLD = "1"


def styled(stream: IO[str], mode: ColorMode = "auto") -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if mode == "never":
        return False
    if mode == "always" or os.environ.get("FORCE_COLOR"):
        return True
    return os.environ.get("TERM") != "dumb" and bool(getattr(stream, "isatty", lambda: False)())


def _encoding(stream: IO[str]) -> str:
    return (getattr(stream, "encoding", None) or "ascii").lower()


def tag_text(text: str, encoding: str) -> str:
    """Rótulo da tag; sem UTF-8 vira ASCII (POLÍTICA -> POLITICA)."""
    if encoding.replace("_", "-") in {"utf-8", "utf8"}:
        return text
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def tag(label: str, stream: IO[str], mode: ColorMode, sgr: str = REVERSE_BOLD) -> str:
    text = tag_text(label, _encoding(stream))
    return f"\x1b[{sgr}m {text} \x1b[0m" if styled(stream, mode) else f"[{text}]"


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB"):
        n /= 1024  # type: ignore[assignment]
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}".replace(".", ",")
    return f"{n} B"  # pragma: no cover


def human_seconds(s: float) -> str:
    return f"{s:.1f} s".replace(".", ",") if s < 60 else f"{int(s // 60)} min {int(s % 60)} s"


def error(
    code: str,
    message: str,
    *,
    hint: str | None = None,
    detail: str | None = None,
    policy: bool = False,
    mode: ColorMode = "auto",
    verbose: bool = False,
    stream: IO[str] | None = None,
) -> None:
    out: IO[str] = stream or sys.stderr
    label = "POLÍTICA" if policy else "ERRO"
    lines = [f"raspador: {tag(label, out, mode)} {code}: {message}"]
    if hint:
        lines.append(f"  dica: {hint}")
    if detail and verbose:
        lines.append(f"  detalhe: {detail}")
    print("\n".join(lines), file=out)


def policy_error(err: object, *, mode: ColorMode = "auto", stream: IO[str] | None = None) -> None:
    """PolicyError tem três linhas próprias (código, motivo, alternativa)."""
    out: IO[str] = stream or sys.stderr
    print(f"raspador: {tag('POLÍTICA', out, mode)} {err}", file=out)


def warning(message: str, *, mode: ColorMode = "auto", stream: IO[str] | None = None) -> None:
    out: IO[str] = stream or sys.stderr
    print(f"raspador: {tag('aviso:', out, mode, sgr=BOLD).strip('[]')} {message}", file=out)


def result_line(
    status: int,
    url: str,
    output: str,
    size: int,
    elapsed: float,
    *,
    empty_selector: str | None = None,
    mode: ColorMode = "auto",
    stream: IO[str] | None = None,
) -> None:
    out: IO[str] = stream or sys.stderr
    if empty_selector is not None:
        tail = f"(vazio: o seletor '{empty_selector}' não encontrou nada)"
    else:
        tail = f"({human_size(size)}, {human_seconds(elapsed)})"
    print(f"ok  {status}  {url}  -> {output} {tail}", file=out)
