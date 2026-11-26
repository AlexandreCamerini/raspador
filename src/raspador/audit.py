"""Log de auditoria (contrato C6): uma linha JSONL por decisão de política."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

EVENTS = frozenset(
    {
        "robots_denied",
        "policy_error",
        "policy_override",
        "domain_stopped",
        "blocked_retry",
        "offsite_dropped",
        "proxy_assigned",
    }
)


def _strip_query(url: str) -> str:
    """Sem query, fragmento nem credencial (`usuario:senha@`)."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.rpartition("@")[2], parts.path, "", ""))


class AuditLog:
    """Append-only. Nunca grava corpo de resposta, cookies nem query string."""

    def __init__(self, path: str | Path | None, run_id: str, spider: str | None = None) -> None:
        self.path = Path(path) if path else None
        self.run_id = run_id
        self.spider = spider
        self._lock = threading.Lock()
        self.events: list[dict[str, Any]] = []

    def record(self, event: str, **fields: Any) -> dict[str, Any]:
        if event not in EVENTS:
            raise ValueError(f"evento de auditoria desconhecido: {event}")
        if "url" in fields and fields["url"]:
            fields["url"] = _strip_query(str(fields["url"]))
        line = {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "run_id": self.run_id,
            "spider": self.spider,
            "event": event,
            **fields,
        }
        with self._lock:
            self.events.append(line)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
        return line
