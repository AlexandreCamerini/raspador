"""Storage do parsing adaptativo (contrato C1).

O padrão do upstream grava em `site-packages/scrapling/elements_storage.db`: some a cada reinstalação e é
compartilhado entre projetos. O raspador grava em `$RASPADOR_HOME/adaptive.db` (padrão `~/.raspador`).
Não usa `storage_args`: passado explicitamente, o upstream deixa de injetar a URL e todos os domínios
colidiriam na mesma chave.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from scrapling.core.storage import SQLiteStorageSystem
from scrapling.parser import Selector as _UpstreamSelector

_configured: Path | None = None


def home() -> Path:
    return Path(os.environ.get("RASPADOR_HOME") or Path.home() / ".raspador")


def path() -> Path:
    return _configured or home() / "adaptive.db"


def configure(db_path: str | Path) -> Path:
    """Define o arquivo SQLite do adaptativo. Vale para as próximas páginas parseadas."""
    global _configured
    _configured = Path(db_path).expanduser().resolve()
    RaspadorStorage.cache_clear()
    return _configured


def reset() -> None:
    global _configured
    _configured = None
    RaspadorStorage.cache_clear()


def _ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)


@lru_cache(64, typed=True)
class RaspadorStorage(SQLiteStorageSystem.__wrapped__):  # type: ignore[name-defined, misc]
    """SQLite do upstream, no caminho do raspador. A chave continua (domínio, identifier)."""

    def __init__(self, storage_file: str | None = None, url: str | None = None) -> None:
        target = path()
        _ensure_parent(target)
        super().__init__(str(target), url)


def selector_config(adaptive: bool = True, **extra: Any) -> dict[str, Any]:
    """`selector_config` para sessões e requests: liga o adaptativo no storage do raspador."""
    return {"adaptive": adaptive, "storage": RaspadorStorage, **extra}


class Selector(_UpstreamSelector):
    """`Selector` do Scrapling com o storage adaptativo do raspador por padrão."""

    def __init__(self, *args: Any, storage: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, storage=storage or RaspadorStorage, **kwargs)
