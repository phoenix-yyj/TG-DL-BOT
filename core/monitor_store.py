"""Persistent state for automatic Telegram chat monitoring."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


class MonitorStore:
    """Small append-only journal with an atomic checkpoint.

    A message is identified by ``(chat_id, message_id)``.  The store is
    deliberately separate from collection manifests: monitored chats are
    long-lived and are not owned by a Telegram conversation.
    """

    def __init__(self, root: str | Path = "downloads") -> None:
        self.root = Path(root)
        self.path = self.root / ".tgdl_monitor_state.json"
        self.journal = self.root / ".tgdl_monitor_state.jsonl"
        self._items: dict[str, dict[str, Any]] = {}
        self._events = 0
        self._load()

    @staticmethod
    def key(chat_id: int | str, message_id: int) -> str:
        return f"{chat_id}:{message_id}"

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._items = {str(k): v for k, v in data.get("items", {}).items() if isinstance(v, dict)}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self._items = {}
        try:
            lines = self.journal.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                event = json.loads(line)
                key = event.pop("_key")
                self._items[key] = event
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
        self._events = len(lines)

    def get(self, chat_id: int | str, message_id: int) -> dict[str, Any] | None:
        return self._items.get(self.key(chat_id, message_id))

    def upsert(self, chat_id: int | str, message_id: int, **values: Any) -> dict[str, Any]:
        key = self.key(chat_id, message_id)
        item = dict(self._items.get(key, {}))
        item.update(values)
        item.update({"chat_id": chat_id, "message_id": message_id, "updated_at": time.time()})
        self._items[key] = item
        self.root.mkdir(parents=True, exist_ok=True)
        event = dict(item)
        event["_key"] = key
        with self.journal.open("a", encoding="utf-8") as output:
            output.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._events += 1
        if self._events >= 100:
            self.checkpoint()
        return item

    def checkpoint(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "items": self._items}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
        self.journal.unlink(missing_ok=True)
        self._events = 0

    def items_for_chat(self, chat_id: int | str) -> list[dict[str, Any]]:
        return [item for item in self._items.values() if item.get("chat_id") == chat_id]
