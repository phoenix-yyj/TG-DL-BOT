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
from pyrogram.errors import AuthBytesInvalid, FileReferenceExpired
from pyrogram.file_id import FileId
from pyrogram.types import Message

from .archive_processor import process_download
from .monitor_store import MonitorStore
from .download_lifecycle import failed_dir, move_artifacts, remap_result_files

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
        peer = str(chat_id).strip().lstrip("@")
        if not peer or (not peer.lstrip("-").isdigit() and not re.fullmatch(r"[A-Za-z0-9_]{3,}", peer)):
            raise ValueError(f"无效的 chat_id 或公开用户名：{chat_id}")
        passwords = rule.get("passwords", [])
        if not isinstance(passwords, list) or not all(isinstance(p, str) for p in passwords):
            raise ValueError(f"chat {chat_id} 的 passwords 必须是字符串数组")
        result[peer] = {
            "_peer": peer,
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
    def __init__(self, client: Any, scheduler: Any, config_path: str | Path,
                 state_root: str | Path = "downloads", notifier: Any = None,
                 owner_id: int | None = None,
                 archive_config: dict[str, Any] | None = None) -> None:
        self.client = client
        self.scheduler = scheduler
        self.config_path = Path(config_path)
        self.rules = load_monitor_config(self.config_path)
        self.store = MonitorStore(state_root)
        self._registered = False
        self._history_task: asyncio.Task | None = None
        self._message_lock = asyncio.Lock()
        self._batches: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.notifier = notifier
        self.owner_id = owner_id
        self.archive_config = archive_config or {"passwords": [], "rules": []}
        self._status_messages: dict[str, Any] = {}
        self._last_status_text: dict[str, str] = {}
        self._status_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._active_downloads: defaultdict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
        self._status_context: dict[str, tuple[int | str, dict[str, Any], str, str, int, int, float]] = {}
        self._status_tasks: dict[str, asyncio.Task] = {}
        self._status_pending: set[str] = set()
        self._status_started: dict[str, float] = {}
        self._media_warmup_lock = asyncio.Lock()
        self._warmed_media_dcs: set[int] = set()
        self._job_tasks: set[asyncio.Task] = set()
        self._scheduled_keys: set[str] = set()
        self._volume_locks: defaultdict[tuple[int, str], asyncio.Lock] = defaultdict(asyncio.Lock)

    @staticmethod
    def _source_dir(output_dir: Path) -> Path:
        """Keep automatic-monitor inputs outside the published output tree."""
        return output_dir.parent / ".sources" / output_dir.name

    @staticmethod
    def _source_bucket(group: str | None, message_id: int) -> str:
        if group:
            bucket = Path(group).name
            bucket = re.sub(r"[^A-Za-z0-9_.-]+", "_", bucket).strip("._")
            return bucket[:120] or f"volume-{message_id}"
        return f"message-{message_id}"

    def _rule(self, chat_id: int | str, username: str | None = None) -> dict[str, Any] | None:
        rule = self.rules.get(str(chat_id))
        if rule is None and username:
            rule = self.rules.get(username.lstrip("@"))
        return rule if rule and rule.get("enabled", True) else None

    async def register(self) -> None:
        if self._registered or not self.rules:
            return
        ids = [int(chat_id) if chat_id.lstrip("-").isdigit() else chat_id
               for chat_id, rule in self.rules.items() if rule.get("enabled", True)]
        if not ids:
            return
        self.client.on_message(filters.chat(ids) & filters.document)(self._on_new_message)
        self._registered = True
        logger.info("[AUTO_MONITOR] 已注册 %d 个群聊监听", len(ids))
        # Announce the scan before history retrieval starts.  This also makes
        # an empty/non-archive history visibly distinguishable from a stuck
        # downloader.
        for peer in ids:
            rule = self.rules[str(peer)]
            await self._show_status(peer, rule, "历史消息", "正在扫描历史消息", 0, 0, 0)
        self._history_task = asyncio.create_task(self.scan_history(ids))

    async def scan_history(self, chat_ids: list[str]) -> None:
        for chat_id in chat_ids:
            try:
                messages = [message async for message in self.client.get_chat_history(chat_id)]
                for message in reversed(messages):
                    await self.submit(message, historical=True, peer=str(chat_id))
                counts = await self.flush(chat_id)
                logger.info("[AUTO_MONITOR] 群 %s 历史扫描完成，共 %d 条，发现压缩包 %d 条，跳过已下载 %d 条，已入队 %d 条",
                            chat_id, len(messages), counts.get("discovered", 0),
                            counts.get("skipped", 0), len(self._job_tasks))
                rule = self.rules[str(chat_id)]
                await self._show_status(chat_id, rule, "历史消息", "历史扫描完成，已加入下载队列", 0, 0, 0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[AUTO_MONITOR] 群 %s 历史扫描失败：%s", chat_id, str(exc)[:200])

    async def _on_new_message(self, _client: Any, message: Message) -> None:
        await self.submit(message, historical=False)

    async def submit(self, message: Message, historical: bool = False, peer: str | None = None) -> None:
        chat_id = int(message.chat.id)
        username = getattr(getattr(message, "chat", None), "username", None)
        # Historical messages may not carry ``chat.username`` even when the
        # history was fetched through a public username.  Keep the configured
        # peer from scan_history as the authoritative fallback.
        rule = self._rule(chat_id, username or peer)
        name = archive_name(message)
        if not rule or not name:
            return
        state_key = self.store.key(chat_id, message.id)
        record = self.store.get(chat_id, message.id)
        # Only a completed Telegram download is a permanent deduplication
        # marker.  ``discovered``, ``downloading`` and ``failed`` must be
        # retryable after a crash or a transient network error.
        terminal_statuses = {"downloaded", "processed", "processing_failed"}
        if record and record.get("status") in terminal_statuses:
            self._batches[str(chat_id)]["skipped"] += 1
            return
        if state_key in self._scheduled_keys:
            return
        group = volume_group(name)
        self.store.upsert(chat_id, message.id, file_name=name, status="discovered", volume_group=group,
                          historical=historical, rule_name=rule["name"])
        self._batches[str(chat_id)]["discovered"] += 1
        # Do not wait for one download before accepting the next historical or
        # live message.  DownloadScheduler applies the configured global
        # concurrency limit and fairly interleaves monitored chats.
        self._scheduled_keys.add(state_key)
        task = asyncio.create_task(self.scheduler.submit(
            f"auto:{chat_id}", [lambda: self._download(message, rule, group)],
            label=f"自动监听：{rule['name']}"
        ))
        self._job_tasks.add(task)
        task.add_done_callback(lambda done, key=state_key: self._job_finished(done, key))

    def _job_finished(self, task: asyncio.Task, state_key: str) -> None:
        self._job_tasks.discard(task)
        self._scheduled_keys.discard(state_key)

    async def _download(self, message: Message, rule: dict[str, Any], group: str | None) -> None:
        chat_id = int(message.chat.id)
        record = self.store.get(chat_id, message.id) or {}
        self.store.upsert(chat_id, message.id, status="downloading")
        output_dir = Path(rule["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        source_dir = self._source_dir(output_dir)
        source_dir.mkdir(parents=True, exist_ok=True)
        file_name = record.get("file_name") or archive_name(message) or f"message_{message.id}.bin"
        safe_name = Path(file_name).name
        source_bucket = source_dir / self._source_bucket(group, message.id)
        tmp_dir = source_bucket / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        target = tmp_dir / safe_name
        existing = Path(record["local_path"]) if record.get("local_path") else None
        reuse_existing = bool(existing and existing.is_file())
        source_path = existing if reuse_existing else target
        try:
            if reuse_existing:
                downloaded = str(source_path)
                await self._show_status(chat_id, rule, safe_name, "准备处理已有文件", 0, 0, 0, message.id)
            else:
                # History/live updates may contain an old file_reference. Fetch
                # the message again immediately before the media operation so
                # Telegram returns a current reference.
                message = await self._refresh_message(message)
                await self._show_status(chat_id, rule, safe_name, "准备下载", 0, 0, 0, message.id)
                for warm_attempt in range(2):
                    try:
                        await self._warm_media_session(message)
                        break
                    except FileReferenceExpired:
                        if warm_attempt:
                            raise
                        message = await self._refresh_message(message)
            started = time.monotonic()
            last_update = started
            last_bytes = 0

            async def progress(current: int, total: int) -> None:
                nonlocal last_update, last_bytes
                now = time.monotonic()
                if now - last_update < 1.5 and current < total:
                    return
                elapsed = max(now - last_update, 0.001)
                speed = max(current - last_bytes, 0) / elapsed
                last_update, last_bytes = now, current
                await self._show_status(chat_id, rule, safe_name, "正在下载", current, total, speed, message.id)

            if not reuse_existing:
                downloaded = None
                for attempt in range(3):
                    try:
                        downloaded = await self.client.download_media(
                            message, file_name=str(target), progress=progress
                        )
                        # Some Pyrogram builds log FILE_REFERENCE_EXPIRED and
                        # return None instead of propagating the RPC exception.
                        if downloaded:
                            break
                    except FileReferenceExpired:
                        downloaded = None
                    if attempt < 2:
                        message = await self._refresh_message(message)
                        await asyncio.sleep(0.5 * (attempt + 1))

            if not downloaded or not Path(downloaded).is_file():
                raise RuntimeError("Telegram 未返回有效文件")
            if not reuse_existing:
                moved = move_artifacts([target], tmp_dir, source_bucket)
                source_path = moved[0] if moved else source_bucket / safe_name
            self.store.upsert(chat_id, message.id, status="downloaded", local_path=str(source_path), downloaded_at=time.time())
            self._batches[str(chat_id)]["downloaded"] += 1
            total_size = source_path.stat().st_size
            elapsed = max(time.monotonic() - started, 0.001)
            await self._show_status(chat_id, rule, safe_name, "下载完成，正在处理", total_size, total_size,
                                     total_size / elapsed, message.id)
            chat_title = getattr(getattr(message, "chat", None), "title", None)
            if group:
                await self._process_volume_group(chat_id, group, rule, source_path, chat_title)
            else:
                await self._process(source_path, rule, chat_id, message.id, chat_title)
            await self._show_status(chat_id, rule, safe_name, "任务完成", total_size, total_size,
                                     total_size / elapsed, message.id)
        except asyncio.CancelledError:
            self.store.upsert(chat_id, message.id, status="discovered")
            raise
        except Exception as exc:
            # A successful Telegram download is never erased from the state;
            # processing failures are handled separately from re-downloads.
            current = self.store.get(chat_id, message.id) or {}
            known_path = current.get("local_path") or record.get("local_path")
            if target.exists():
                try:
                    failed_target = failed_dir(self._source_dir(Path(rule["output_dir"])))
                    move_artifacts([target], target.parent, failed_target)
                    known_path = str(failed_target / target.name)
                except OSError as move_exc:
                    logger.warning("[AUTO_MONITOR] 失败文件归档失败：%s", str(move_exc)[:160])
            else:
                failed_candidate = failed_dir(self._source_dir(Path(rule["output_dir"]))) / target.name
                if failed_candidate.exists():
                    known_path = str(failed_candidate)
            status = "processing_failed" if current.get("status") == "downloaded" else "failed"
            self.store.upsert(chat_id, message.id, status=status,
                              local_path=known_path, processing_error=str(exc)[:240])
            self._batches[str(chat_id)][status] += 1
            await self._show_status(chat_id, rule, safe_name, f"任务失败：{status}", 0, 0, 0, message.id)

    async def _refresh_message(self, message: Message) -> Message:
        """Reload a message to renew its Telegram media file reference."""
        refreshed = await self.client.get_messages(int(message.chat.id), message.id)
        if not refreshed or getattr(refreshed, "empty", False):
            raise RuntimeError("无法重新获取源消息，文件引用可能已失效")
        return refreshed

    async def _warm_media_session(self, message: Message) -> None:
        """Initialize Pyrogram's per-DC media session before parallel downloads.

        Pyrogram lazily creates media sessions.  If several downloads hit a new
        DC at exactly the same time, they can race during auth.ExportAuthorization
        and produce AUTH_BYTES_INVALID.  Reading one chunk serially avoids that
        initialization race; the real downloads remain concurrent afterwards.
        """
        document = getattr(message, "document", None)
        if not document or not getattr(document, "file_id", None):
            return
        file_id = FileId.decode(document.file_id)
        if file_id.dc_id in self._warmed_media_dcs:
            return
        async with self._media_warmup_lock:
            if file_id.dc_id in self._warmed_media_dcs:
                return
            for attempt in range(2):
                generator = self.client.get_file(file_id, getattr(document, "file_size", 0), 0, 0)
                try:
                    await generator.__anext__()
                    self._warmed_media_dcs.add(file_id.dc_id)
                    return
                except AuthBytesInvalid:
                    # Pyrogram stores the lazily-created session before the
                    # authorization import finishes.  Remove the invalid one
                    # before retrying the initialization.
                    session = self.client.media_sessions.pop(file_id.dc_id, None)
                    if session:
                        await session.stop()
                    if attempt == 1:
                        raise
                    await asyncio.sleep(1)
                finally:
                    await generator.aclose()

    @staticmethod
    def _format_bytes(value: float) -> str:
        number = float(value)
        for unit in ("B", "KB", "MB", "GB"):
            if number < 1024 or unit == "GB":
                return f"{number:.1f} {unit}"
            number /= 1024
        return f"{number:.1f} GB"

    async def _show_status(self, chat_id: int | str, rule: dict[str, Any], file_name: str,
                           state: str, current: int, total: int, speed: float,
                           message_id: int | None = None) -> None:
        """Queue a status update without blocking the media download."""
        if not self.notifier or not self.owner_id:
            return
        # A public username in config and its resolved numeric ID refer to the
        # same chat; use the configured peer as the stable status-message key.
        key = str(rule.get("_peer") or chat_id)
        if message_id is not None:
            if state == "任务完成" or state.startswith("任务失败"):
                self._active_downloads[key].pop(message_id, None)
            else:
                self._active_downloads[key][message_id] = {
                    "file_name": file_name, "state": state, "current": current,
                    "total": total, "speed": speed,
                }
        self._status_context[key] = (chat_id, rule, file_name, state, current, total, speed)
        self._status_pending.add(key)
        if key not in self._status_tasks or self._status_tasks[key].done():
            task = asyncio.create_task(self._status_worker(key))
            self._status_tasks[key] = task

    async def _status_worker(self, key: str) -> None:
        """Coalesce progress callbacks and edit at most once every five seconds."""
        try:
            while key in self._status_pending:
                self._status_pending.discard(key)
                if self._status_messages.get(key):
                    await asyncio.sleep(5)
                await self._send_status(key)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("[AUTO_MONITOR] 状态消息更新失败：%s", str(exc)[:160])
        finally:
            self._status_tasks.pop(key, None)

    async def _send_status(self, key: str) -> None:
        context = self._status_context.get(key)
        if not context:
            return
        chat_id, rule, file_name, state, current, total, speed = context
        percent = f"{current * 100 / total:.1f}%" if total else "--"
        queue = self.scheduler.snapshot()
        chat_queue = next((item for item in queue if item["group"] == f"auto:{chat_id}"), None)
        active = self._active_downloads[key]
        if active:
            rows = []
            for item in active.values():
                if item["total"]:
                    rows.append(
                        f"• `{item['file_name']}`：{item['state']} "
                        f"{item['current'] * 100 / item['total']:.1f}% "
                        f"({self._format_bytes(item['current'])}/{self._format_bytes(item['total'])}) "
                        f"{self._format_bytes(item['speed'])}/s"
                    )
                else:
                    rows.append(f"• `{item['file_name']}`：{item['state']}")
            files_text = "正在处理文件：\n" + "\n".join(rows)
            speed_text = f"总速度：{self._format_bytes(sum(item['speed'] for item in active.values()))}/s"
        else:
            files_text = f"文件：`{file_name}`\n状态：{state}\n进度：{percent}"
            speed_text = f"速度：{self._format_bytes(speed)}/s"
        text = (f"[AUTO_MONITOR] **自动任务：{rule['name']}**\n\n{files_text}\n"
                f"{speed_text}\n队列：活动 {chat_queue['active'] if chat_queue else 0}，"
                f"等待 {chat_queue['pending'] if chat_queue else 0}")
        try:
            # Several downloads for one chat can start at the same time.  The
            # lock makes the first send and all subsequent edits atomic, so a
            # chat always owns one status message per monitor process.
            async with self._status_locks[key]:
                # Reuse the bot's FloodWait-aware sender without importing bot
                # at module load time (bot imports this monitor module).
                from .bot import safe_execute_send

                status_message = self._status_messages.get(key)
                if status_message:
                    if self._last_status_text.get(key) == text:
                        return
                    updated = await safe_execute_send(self.owner_id, status_message.edit, text)
                    if updated is not None:
                        self._last_status_text[key] = text
                else:
                    status_message = await safe_execute_send(self.owner_id, self.notifier.send_message,
                                                             self.owner_id, text)
                if status_message:
                    self._status_messages[key] = status_message
                    self._last_status_text[key] = text
        except Exception as exc:
            logger.debug("[AUTO_MONITOR] 状态消息更新失败：%s", str(exc)[:160])

    def _archive_processing_config(self, rule: dict[str, Any]) -> dict[str, Any]:
        """Use archive_rules.json while allowing monitor passwords to override."""
        archive_config = {
            "passwords": list(self.archive_config.get("passwords", [])),
            "rules": list(self.archive_config.get("rules", [])),
        }
        if rule.get("passwords"):
            archive_config["passwords"] = list(rule["passwords"])
        return archive_config

    async def _process_volume_group(self, chat_id: int, group: str, rule: dict[str, Any], newest: Path,
                                    chat_title: str | None) -> None:
        lock = self._volume_locks[(chat_id, group)]
        async with lock:
            records = [item for item in self.store.items_for_chat(chat_id)
                       if item.get("volume_group") == group]
            paths = [Path(item["local_path"]) for item in records if item.get("local_path")]
            if not paths:
                return

            # A previous worker may already have completed the group.  Treat a
            # complete recorded result as authoritative and make retries
            # idempotent instead of invoking 7-Zip again.
            output_dir = Path(rule["output_dir"])
            processed = next((item for item in records
                              if item.get("status") == "processed" or item.get("processed_files")), None)
            if processed:
                result_files = []
                for path in processed.get("processed_files", []):
                    candidate = Path(path)
                    if not candidate.is_file():
                        candidate = output_dir / candidate
                    result_files.append(candidate)
                if not result_files or all(path.is_file() for path in result_files):
                    for item in records:
                        self.store.upsert(chat_id, int(item["message_id"]), status="processed",
                                          processed_files=[str(path) for path in result_files]
                                          if result_files else item.get("processed_files", []),
                                          processing_error=None)
                    return

            if any(not path.exists() for path in paths):
                return

            # 7-Zip discovers sibling volumes automatically.  The first
            # volume is the only input needed; an incomplete set remains in
            # the source directory and can be retried when another part lands.
            try:
                result = await process_download(
                    str(paths[0]), chat_title, "public",
                    self._archive_processing_config(rule), rule.get("_peer"),
                    result_dir=output_dir,
                )
                if result["status"] not in {"success", "not_archive", "no_rule"}:
                    raise RuntimeError(result.get("error") or "压缩包处理失败")
                result["files"] = remap_result_files(result["files"], output_dir, output_dir)
                self.store.upsert(chat_id, int(records[0]["message_id"]), status="processed",
                                  local_path=str(paths[0]), processed_files=result["files"],
                                  processing_error=None)
                for item in records[1:]:
                    self.store.upsert(chat_id, int(item["message_id"]), status="processed",
                                      local_path=str(item["local_path"]), processing_error=None)
            except Exception as exc:
                # Never downgrade a worker that has already committed success.
                current = [item for item in self.store.items_for_chat(chat_id)
                           if item.get("volume_group") == group]
                for item in current:
                    if item.get("status") != "processed":
                        self.store.upsert(chat_id, int(item["message_id"]), status="volume_waiting",
                                          processing_error=str(exc)[:240])

    async def _process(self, source: Path, rule: dict[str, Any], chat_id: int, message_id: int,
                       chat_title: str | None = None) -> None:
        output_dir = Path(rule["output_dir"])
        result = await process_download(str(source), chat_title, "public",
                                        self._archive_processing_config(rule), rule.get("_peer"),
                                        result_dir=output_dir)
        if result["status"] in {"success", "not_archive", "no_rule"}:
            result["files"] = remap_result_files(result.get("files", []), output_dir, output_dir)
            self.store.upsert(chat_id, message_id, status="processed", local_path=str(source),
                              processed_files=result["files"],
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
        if self._job_tasks:
            await asyncio.gather(*self._job_tasks, return_exceptions=True)
            self._job_tasks.clear()
        status_tasks = list(self._status_tasks.values())
        for task in status_tasks:
            task.cancel()
        if status_tasks:
            await asyncio.gather(*status_tasks, return_exceptions=True)
        self._status_tasks.clear()
        self.store.checkpoint()
