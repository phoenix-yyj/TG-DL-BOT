"""Persistent collection-session state for local media downloads."""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


DOWNLOAD_ROOT = Path("downloads")
MANIFEST_PREFIX = ".tgdl_collection_"


def sanitize_collection_name(name: str) -> str:
    """Produce a portable, single directory name from user input."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name.strip())
    name = re.sub(r"\s+", " ", name).strip(". ")
    if not name:
        raise ValueError("合集名称不能为空")
    return name[:100]


@dataclass
class CollectionEntry:
    sequence: int
    source_chat_id: int | str
    message_id: int
    link_type: str  # direct, public, private
    status: str = "pending"  # pending, downloading, success, skipped, failed
    output_file: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CollectionEntry":
        return cls(**data)


@dataclass
class CollectionSession:
    name: str
    directory_name: str
    owner_user_id: int
    owner_chat_id: int
    phase: str = "collecting"  # collecting, downloading, completed
    entries: list[CollectionEntry] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)
    root: Path = field(default=DOWNLOAD_ROOT, repr=False, compare=False)

    @property
    def directory(self) -> Path:
        return self.root / self.directory_name

    @property
    def manifest_path(self) -> Path:
        return self.directory / f"{MANIFEST_PREFIX}{self.owner_chat_id}_{self.owner_user_id}.json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "name": self.name,
            "directory_name": self.directory_name,
            "owner_user_id": self.owner_user_id,
            "owner_chat_id": self.owner_chat_id,
            "phase": self.phase,
            "entries": [entry.to_dict() for entry in self.entries],
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], root: Path = DOWNLOAD_ROOT) -> "CollectionSession":
        data = data.copy()
        data.pop("version", None)
        data["entries"] = [CollectionEntry.from_dict(entry) for entry in data.get("entries", [])]
        return cls(**data, root=root)


class CollectionStore:
    """Manages collection manifests and reconstructs them after a restart."""

    def __init__(self, root: Path = DOWNLOAD_ROOT):
        self.root = Path(root)
        self._sessions: dict[tuple[int, int, str], CollectionSession] = {}

    @staticmethod
    def key(chat_id: int, user_id: int) -> tuple[int, int]:
        return chat_id, user_id

    def _persist(self, session: CollectionSession) -> None:
        session.directory.mkdir(parents=True, exist_ok=True)
        session.updated_at = time.time()
        temporary = session.manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, session.manifest_path)

    def _find_all_on_disk(self, chat_id: int, user_id: int) -> list[CollectionSession]:
        if not self.root.exists():
            return []
        pattern = f"*/{MANIFEST_PREFIX}{chat_id}_{user_id}.json"
        manifests = sorted(self.root.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
        sessions = []
        for manifest in manifests:
            try:
                session = CollectionSession.from_dict(json.loads(manifest.read_text(encoding="utf-8")), self.root)
                if session.owner_chat_id == chat_id and session.owner_user_id == user_id:
                    sessions.append(session)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return sessions

    @staticmethod
    def _session_key(session: CollectionSession) -> tuple[int, int, str]:
        return session.owner_chat_id, session.owner_user_id, session.directory_name

    def all(self, chat_id: int, user_id: int) -> list[CollectionSession]:
        """Return all known sessions for an owner, newest first."""
        for session in self._find_all_on_disk(chat_id, user_id):
            self._sessions.setdefault(self._session_key(session), session)
        return sorted(
            (session for key, session in self._sessions.items() if key[:2] == (chat_id, user_id)),
            key=lambda session: session.updated_at,
            reverse=True,
        )

    def get(self, chat_id: int, user_id: int, name: Optional[str] = None) -> Optional[CollectionSession]:
        sessions = self.all(chat_id, user_id)
        if name is not None:
            directory_name = sanitize_collection_name(name)
            return next((session for session in sessions if session.name == name or session.directory_name == directory_name), None)
        # There is at most one input session at a time. Prefer it over older
        # downloads/completed sessions; otherwise expose the newest session
        # for /resume and backwards-compatible callers.
        return next((session for session in sessions if session.phase == "collecting"), None) or (sessions[0] if sessions else None)

    def begin(self, chat_id: int, user_id: int, name: str) -> CollectionSession:
        sessions = self.all(chat_id, user_id)
        if any(existing.phase == "collecting" for existing in sessions):
            existing = next(existing for existing in sessions if existing.phase == "collecting")
            raise RuntimeError(f"已有进行中的合集：{existing.name}")

        directory_name = sanitize_collection_name(name)
        # Reopening the same completed collection deliberately appends to its
        # manifest so sequence-based names never overwrite prior downloads.
        existing = next((item for item in sessions if item.directory_name == directory_name), None)
        if existing and existing.phase == "downloading":
            raise RuntimeError(f"该合集正在下载：{existing.name}")
        if existing:
            existing.phase = "collecting"
            self._persist(existing)
            return existing

        session = CollectionSession(
            name=name.strip(), directory_name=directory_name,
            owner_user_id=user_id, owner_chat_id=chat_id, root=self.root,
        )
        self._sessions[self._session_key(session)] = session
        self._persist(session)
        return session

    def add_entry(self, session: CollectionSession, source_chat_id: int | str, message_id: int, link_type: str) -> CollectionEntry:
        if session.phase != "collecting":
            raise RuntimeError("该合集已结束收集")
        entry = CollectionEntry(
            sequence=len(session.entries) + 1,
            source_chat_id=source_chat_id,
            message_id=message_id,
            link_type=link_type,
        )
        session.entries.append(entry)
        self._persist(session)
        return entry

    def set_phase(self, session: CollectionSession, phase: str) -> None:
        session.phase = phase
        self._persist(session)

    def update_entry(self, session: CollectionSession, entry: CollectionEntry, status: str,
                     output_file: Optional[str] = None, error: Optional[str] = None) -> None:
        entry.status = status
        entry.output_file = output_file
        entry.error = error
        self._persist(session)

    @staticmethod
    def remaining_entries(session: CollectionSession) -> list[CollectionEntry]:
        return [entry for entry in session.entries if entry.status in {"pending", "failed", "downloading"}]


collection_store = CollectionStore()
