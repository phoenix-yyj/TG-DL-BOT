"""Shared test configuration without real Telegram credentials."""

import os

os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("OWNER_USER_ID", "123")
