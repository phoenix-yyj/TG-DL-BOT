"""检查群聊历史消息中的媒体类型和文件名。

用法：
    uv run python scripts/inspect_chat_media.py example_public_group --limit 100
"""
from __future__ import annotations

import argparse
import asyncio
import os
from collections import Counter

from dotenv import load_dotenv
from pyrogram import Client


async def main(target: str, limit: int) -> None:
    load_dotenv()
    required = (os.getenv("API_ID"), os.getenv("API_HASH"), os.getenv("SESSION"))
    if not all(required):
        raise SystemExit("请先在 .env 配置 API_ID、API_HASH 和 SESSION")

    async with Client(
        "inspect_chat_media",
        api_id=int(required[0]),
        api_hash=required[1],
        session_string=required[2],
    ) as app:
        counts: Counter[str] = Counter()
        documents: list[tuple[int, str | None, str | None]] = []
        text_archive_markers: list[tuple[int, str]] = []
        total = 0

        async for message in app.get_chat_history(target):
            total += 1
            if message.document:
                counts["document"] += 1
                documents.append((message.id, message.document.file_name, message.document.mime_type))
            elif message.photo:
                counts["photo"] += 1
            elif message.video:
                counts["video"] += 1
            elif message.audio:
                counts["audio"] += 1
            elif message.animation:
                counts["animation"] += 1
            elif message.text or message.caption:
                counts["text"] += 1
                body = message.text or message.caption or ""
                if any(ext in body.lower() for ext in (".zip", ".7z", ".rar")):
                    text_archive_markers.append((message.id, body[:160].replace("\n", " ")))
            else:
                counts["other"] += 1
            if total >= limit:
                break

        print(f"扫描消息数: {total}")
        print("消息类型:", dict(counts))
        print("\n文件消息（最多 50 条）:")
        for message_id, name, mime in documents[:50]:
            print(f"  id={message_id} name={name!r} mime={mime!r}")
        print("\n正文中包含压缩包扩展名的消息（最多 20 条）:")
        for message_id, text in text_archive_markers[:20]:
            print(f"  id={message_id} text={text!r}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="检查 Telegram 群聊历史媒体类型")
    parser.add_argument("target", help="群组用户名、@用户名或 chat_id")
    parser.add_argument("--limit", type=int, default=100, help="最多检查多少条消息，默认 100")
    args = parser.parse_args()
    asyncio.run(main(args.target.lstrip("@"), max(1, args.limit)))
