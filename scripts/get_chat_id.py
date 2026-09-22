"""查询 Telegram 群组/频道 Chat ID。

用法：
    uv run python scripts/get_chat_id.py zong1zuanqun067
    uv run python scripts/get_chat_id.py https://t.me/zong1zuanqun067
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re

from dotenv import load_dotenv
from pyrogram import Client


def normalize_target(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^https?://t\.me/", "", value, flags=re.I)
    value = value.split("/", 1)[0].split("?", 1)[0]
    return value.lstrip("@")


async def main(target: str) -> None:
    load_dotenv()
    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    session = os.getenv("SESSION")
    if not api_id or not api_hash or not session:
        raise SystemExit("请先在 .env 配置 API_ID、API_HASH 和 SESSION")

    async with Client(
        "chat_id_lookup",
        api_id=int(api_id),
        api_hash=api_hash,
        session_string=session,
    ) as app:
        chat = await app.get_chat(normalize_target(target))
        print(f"名称: {chat.title or chat.first_name or '(无名称)'}")
        print(f"Chat ID: {chat.id}")
        if chat.username:
            print(f"用户名: @{chat.username}")
        print("\n可直接复制到 auto_download.json：")
        print(f'"{chat.id}": {{')
        print(f'  "name": "{chat.title or chat.username or chat.id}",')
        print('  "enabled": true,')
        print('  "passwords": [],')
        print(f'  "output_dir": "downloads/{chat.username or chat.id}"')
        print("}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="查询 Telegram 群组或频道 Chat ID")
    parser.add_argument("target", help="群组用户名、@用户名或 t.me 链接")
    args = parser.parse_args()
    asyncio.run(main(args.target))
