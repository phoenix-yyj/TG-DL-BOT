"""Regression checks for command-handler module loading."""

import asyncio
import inspect


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
