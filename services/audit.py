"""Append-only structured audit events with secret redaction."""

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from services.security import redact_secrets


class AuditLogger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def write(self, event: str, **fields: Any) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            **fields,
        }
        serialized = redact_secrets(json.dumps(record, ensure_ascii=False, default=str))
        with self._lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(serialized + "\n")
