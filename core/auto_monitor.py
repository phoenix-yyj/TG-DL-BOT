"""Automatic archive monitoring for configured Telegram chats."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from pyrogram import filters
from pyrogram.types import Message

from .archive_processor import process_download
from .monitor_store import MonitorStore

logger = logging.getLogger(__name__)
ARCHIVE_SUFFIXES = {".zip", ".7z", ".rar"}
VOLUME_RE = re.compile(r"(?i)(?P<base>.+?)(?:\.part(?P<part>\d+)\.rar|\.(?P<kind>zip|7z)\.(?P<number>\d{3})|\.(?P<rar>r\d{2}))$")


def load_monitor_config(path: str | Path) -> dict[str, dict[str, Any]]:
    config_path = Path(path)
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取自动监听配置：{exc}") from exc
    chats = data.get("chats", {}) if isinstance(data, dict) else None
    if not isinstance(chats, dict):
        raise ValueError("自动监听配置的 chats 必须是对象")
    result: dict[str, dict[str, Any]] = {}
    for chat_id, rule in chats.items():
        if not isinstance(rule, dict):
            raise ValueError(f"chat {chat_id} 的规则必须是对象")
        try:
            int(chat_id)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"无效的 chat_id：{chat_id}") from exc
        passwords = rule.get("passwords", [])
        if not isinstance(passwords, list) or not all(isinstance(p, str) for p in passwords):
            raise ValueError(f"chat {chat_id} 的 passwords 必须是字符串数组")
        result[str(chat_id)] = {
            "name": str(rule.get("name") or chat_id),
            "enabled": bool(rule.get("enabled", True)),
            "passwords": passwords,
            "output_dir": str(rule.get("output_dir") or f"downloads/{chat_id}"),
        }
    return result


def archive_name(message: Message) -> str | None:
    document = getattr(message, "document", None)
    name = getattr(document, "file_name", None)
    if not name:
        return None
    lower = name.lower()
    if any(lower.endswith(suffix) for suffix in ARCHIVE_SUFFIXES):
        return name
    if VOLUME_RE.search(lower):
        return name
    return None


def volume_group(name: str) -> str | None:
    match = VOLUME_RE.match(name.lower())
    if not match:
        return None
    base = match.group("base")
    # .part1.rar and .rar/.r00 should resolve to the same base where possible.
    base = re.sub(r"\.part$", "", base, flags=re.I)
    return base


class AutoMonitor:
    def __init__(self, client: Any, scheduler: Any, config_path: str | Path, state_root: str | Path = "downloads") -> None:
        self.client = client
        self.scheduler = scheduler
        self.config_path = Path(config_path)
        self.rules = load_monitor_config(self.config_path)
        self.store = MonitorStore(state_root)
        self._registered = False
        self._history_task: asyncio.Task | None = None
        self._message_lock = asyncio.Lock()
        self._batches: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def _rule(self, chat_id: int | str) -> dict[str, Any] | None:
        rule = self.rules.get(str(chat_id))
        return rule if rule and rule.get("enabled", True) else None

    async def register(self) -> None:
        if self._registered or not self.rules:
            return
        ids = [int(chat_id) for chat_id, rule in self.rules.items() if rule.get("enabled", True)]
        if not ids:
            return
        self.client.on_message(filters.chat(ids) & filters.document)(self._on_new_message)
        self._registered = True
        logger.info("[AUTO_MONITOR] 已注册 %d 个群聊监听", len(ids))
        self._history_task = asyncio.create_task(self.scan_history(ids))

    async def scan_history(self, chat_ids: list[int]) -> None:
        for chat_id in chat_ids:
            try:
                messages = [message async for message in self.client.get_chat_history(chat_id)]
                for message in reversed(messages):
                    await self.submit(message, historical=True)
                await self.flush(chat_id)
                logger.info("[AUTO_MONITOR] 群 %s 历史扫描完成，共 %d 条", chat_id, len(messages))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[AUTO_MONITOR] 群 %s 历史扫描失败：%s", chat_id, str(exc)[:200])

    async def _on_new_message(self, _client: Any, message: Message) -> None:
        await self.submit(message, historical=False)

    async def submit(self, message: Message, historical: bool = False) -> None:
        chat_id = int(message.chat.id)
        rule = self._rule(chat_id)
        name = archive_name(message)
        if not rule or not name:
            return
        if self.store.get(chat_id, message.id):
            self._batches[str(chat_id)]["skipped"] += 1
            return
        group = volume_group(name)
        self.store.upsert(chat_id, message.id, file_name=name, status="discovered", volume_group=group,
                          historical=historical, rule_name=rule["name"])
        self._batches[str(chat_id)]["discovered"] += 1
        await self.scheduler.submit(
            f"auto:{chat_id}", [lambda: self._download(message, rule, group)], label=f"自动监听：{rule['name']}"
        )

    async def _download(self, message: Message, rule: dict[str, Any], group: str | None) -> None:
        chat_id = int(message.chat.id)
        record = self.store.get(chat_id, message.id) or {}
        self.store.upsert(chat_id, message.id, status="downloading")
        output_dir = Path(rule["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        file_name = record.get("file_name") or archive_name(message) or f"message_{message.id}.bin"
        safe_name = Path(file_name).name
        target = output_dir / safe_name
        try:
            downloaded = await self.client.download_media(message, file_name=str(target))
            if not downloaded or not Path(downloaded).is_file():
                raise RuntimeError("Telegram 未返回有效文件")
            self.store.upsert(chat_id, message.id, status="downloaded", local_path=str(target), downloaded_at=time.time())
            self._batches[str(chat_id)]["downloaded"] += 1
            if group:
                await self._process_volume_group(chat_id, group, rule, target)
            else:
                await self._process(target, rule, chat_id, message.id)
        except asyncio.CancelledError:
            self.store.upsert(chat_id, message.id, status="discovered")
            raise
        except Exception as exc:
            # A successful Telegram download is never erased from the state;
            # processing failures are handled separately from re-downloads.
            current = self.store.get(chat_id, message.id) or {}
            status = "processing_failed" if current.get("status") == "downloaded" else "failed"
            self.store.upsert(chat_id, message.id, status=status, processing_error=str(exc)[:240])
            self._batches[str(chat_id)][status] += 1

    async def _process_volume_group(self, chat_id: int, group: str, rule: dict[str, Any], newest: Path) -> None:
        records = [item for item in self.store.items_for_chat(chat_id) if item.get("volume_group") == group]
        paths = [Path(item["local_path"]) for item in records if item.get("local_path")]
        if not paths or any(not path.exists() for path in paths):
            return
        # 7-Zip discovers sibling volumes automatically.  The first volume is
        # the only input needed; testing it also tells us whether all volumes
        # have arrived without guessing a maximum sequence number.
        try:
            await self._process(paths[0], rule, chat_id, int(records[0]["message_id"]))
            for item in records[1:]:
                self.store.upsert(chat_id, int(item["message_id"]), status="processed",
                                  processing_error=None)
        except Exception as exc:
            for item in records:
                self.store.upsert(chat_id, int(item["message_id"]), status="volume_waiting",
                                  processing_error=str(exc)[:240])

    async def _process(self, source: Path, rule: dict[str, Any], chat_id: int, message_id: int) -> None:
        # Use the existing password-table path without requiring legacy
        # title-based archive rules.
        result = await process_download(str(source), rule.get("name"), "direct", {
            "passwords": rule.get("passwords", []), "rules": []
        })
        if result["status"] in {"success", "not_archive"}:
            self.store.upsert(chat_id, message_id, status="processed", processed_files=result.get("files", []),
                              processing_error=None)
        else:
            raise RuntimeError(result.get("error") or "压缩包处理失败")

    async def flush(self, chat_id: int) -> dict[str, int]:
        async with self._message_lock:
            counts = dict(self._batches.pop(str(chat_id), {}))
        return counts

    async def close(self) -> None:
        if self._history_task:
            self._history_task.cancel()
            await asyncio.gather(self._history_task, return_exceptions=True)
            self._history_task = None
        self.store.checkpoint()
