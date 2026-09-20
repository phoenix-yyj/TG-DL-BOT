"""Regression checks for command-handler module loading."""

import asyncio
import inspect
from unittest.mock import MagicMock


def test_stats_handler_imports_without_removed_file_manager():
    from core.handlers import stats

    assert inspect.iscoroutinefunction(stats.stats_command)


def test_cleanup_handler_uses_native_file_operations():
    from core.handlers import cleanup

    assert inspect.iscoroutinefunction(cleanup.cleanup_command)
    assert hasattr(cleanup, "os")
    assert hasattr(cleanup, "shutil")


def test_start_handler_uses_core_bot_send_wrapper(monkeypatch):
    """/start must not look for a nonexistent ``core.handlers.bot`` module."""
    from core import bot
    from core.handlers import start

    calls = []

    async def safe_execute_send(chat_id, send_coro, *args, **kwargs):
        calls.append((chat_id, send_coro, args, kwargs))

    class FakeMessage:
        class from_user:
            id = 123

        class chat:
            id = 456

        async def reply_text(self, text):
            return text

    monkeypatch.setattr(bot, "safe_execute_send", safe_execute_send)
    asyncio.run(start.start_command(None, FakeMessage()))

    assert calls[0][0] == 456
    assert calls[0][1].__self__.chat.id == 456


def test_bot_command_menu_contains_all_registered_commands(monkeypatch):
    from core import bot

    published_commands = []

    class FakeBotClient:
        async def set_bot_commands(self, commands):
            published_commands.extend(commands)

    monkeypatch.setattr(bot, "bot_client", FakeBotClient())
    asyncio.run(bot.setup_bot_commands())

    assert {command.command for command in published_commands} == {
        "start",
        "help",
        "download",
        "collect",
        "end",
        "batch",
        "batch_status",
        "batch_pause",
        "batch_resume",
        "batch_cancel",
        "cancel",
        "speed",
        "stats",
        "cleanup",
        "test",
    }


def test_main_uses_pyrogram_current_event_loop(monkeypatch):
    """The client and its dispatcher must run on the loop used at creation."""
    from core import bot

    loop = MagicMock()
    coroutine = None

    def run_until_complete(value):
        nonlocal coroutine
        coroutine = value
        value.close()

    loop.run_until_complete.side_effect = run_until_complete
    monkeypatch.setattr(bot.asyncio, "get_event_loop", lambda: loop)
    monkeypatch.setattr(bot, "load_handlers", lambda: None)
    monkeypatch.setattr(bot, "start_server", lambda: None)

    bot.main()

    loop.run_until_complete.assert_called_once()
    assert coroutine.cr_code is bot.run_bot.__code__
