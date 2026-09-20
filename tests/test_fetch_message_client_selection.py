from types import SimpleNamespace

import pytest

import core.bot as bot_module
from core.bot import fetch_message, select_source_client
from core.collection_store import CollectionStore


class FakeClient:
    def __init__(self, message):
        self.message = message
        self.calls = []
        self.download_calls = 0

    async def get_messages(self, chat_id, message_id):
        self.calls.append((chat_id, message_id))
        return self.message

    async def download_media(self, message, file_name):
        self.download_calls += 1
        if self.download_calls == 1:
            # Pyrogram can swallow FILE_REFERENCE_EXPIRED and return None.
            return None
        with open(file_name, "wb") as output:
            output.write(b"data")
        return file_name


def test_private_link_requires_user_session():
    bot = FakeClient(None)

    assert select_source_client(bot, None, "private") is None


def test_public_download_uses_same_user_session_as_message_lookup():
    bot = FakeClient(None)
    user = FakeClient(None)

    assert select_source_client(bot, user, "public") is user


def test_direct_upload_uses_bot_session_that_received_the_message():
    bot = FakeClient(None)
    user = FakeClient(None)

    assert select_source_client(bot, user, "direct") is bot


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


@pytest.mark.asyncio
async def test_incomplete_download_refreshes_message_and_retries(tmp_path, monkeypatch):
    message = SimpleNamespace(
        empty=False,
        media=True,
        document=SimpleNamespace(file_name="sample.bin", file_size=4),
        video=None,
        audio=None,
        voice=None,
        animation=None,
        photo=None,
        sticker=None,
        video_note=None,
    )
    user = FakeClient(message)
    store = CollectionStore(tmp_path)
    session = store.begin(1, 2, "test")
    entry = store.add_entry(session, "public_channel", 49, "public")
    monkeypatch.setattr(bot_module, "collection_store", store)
    monkeypatch.setattr(bot_module, "bot_client", FakeClient(None))
    monkeypatch.setattr(bot_module, "userbot_client", user)

    result = await bot_module.download_collection_entry(session, entry)

    assert result[0] == "success"
    assert user.download_calls == 2
    assert user.calls == [("public_channel", 49), ("public_channel", 49)]
