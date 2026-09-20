"""Commands for collecting Telegram media into a local directory."""
from pyrogram.types import Message

from ..collection_store import collection_store
from ..i18n import tr


async def collect_command(client, message: Message) -> None:
    from ..bot import safe_execute_send

    name = " ".join(message.command[1:]).strip()
    if not name:
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_usage"))
        return
    try:
        session = collection_store.begin(int(message.chat.id), message.from_user.id, name)
    except (ValueError, RuntimeError) as exc:
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_start_failed", error=str(exc)))
        return
    await safe_execute_send(message.chat.id, message.reply_text, tr(
        message, "collect_started", name=session.name, directory=str(session.directory),
    ))


async def end_command(client, message: Message) -> None:
    from ..bot import safe_execute_send, start_collection_download

    session = collection_store.get(int(message.chat.id), message.from_user.id)
    if not session:
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_none"))
        return
    if session.phase == "downloading":
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_downloading"))
        return
    remaining = collection_store.remaining_entries(session)
    if not remaining:
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_no_items"))
        return

    collection_store.set_phase(session, "downloading")
    await safe_execute_send(message.chat.id, message.reply_text, tr(
        message, "collect_ending", total=len(remaining), directory=str(session.directory),
    ))
    start_collection_download(session, message)
