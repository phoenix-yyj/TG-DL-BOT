from types import SimpleNamespace

import pytest

from core.bot import fetch_message, select_source_client


class FakeClient:
    def __init__(self, message):
        self.message = message
        self.calls = []

    async def get_messages(self, chat_id, message_id):
        self.calls.append((chat_id, message_id))
        return self.message


def test_private_link_requires_user_session():
    bot = FakeClient(None)

    assert select_source_client(bot, None, "private") is None


def test_public_download_uses_same_user_session_as_message_lookup():
    bot = FakeClient(None)
    user = FakeClient(None)

    assert select_source_client(bot, user, "public") is user


@pytest.mark.asyncio
async def test_public_link_prefers_user_session_when_available():
    bot = FakeClient(None)
    user = FakeClient(SimpleNamespace(empty=False))

    result = await fetch_message(bot, user, "public_channel", 49, "public")

    assert result is user.message
    assert bot.calls == []
    assert user.calls == [("public_channel", 49)]


@pytest.mark.asyncio
async def test_public_link_falls_back_to_bot_without_user_session():
    bot = FakeClient(SimpleNamespace(empty=False))

    result = await fetch_message(bot, None, "public_channel", 49, "public")

    assert result is bot.message
    assert bot.calls == [("public_channel", 49)]
