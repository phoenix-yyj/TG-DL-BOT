"""Commands for collecting Telegram media into a local directory."""
from pyrogram.types import Message

from ..collection_store import collection_store
from ..i18n import tr


async def collect_command(client, message: Message) -> None:
    from ..bot import safe_execute_send

    args = message.command[1:]
    # A one-link collection can be started and downloaded in one command:
    # /collect <name> <Telegram message link>
    link = args[-1] if args and "t.me/" in args[-1] else None
    name = " ".join(args[:-1] if link else args).strip()
    if not name:
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_usage"))
        return

    if link:
        from ..bot import add_collection_link, parse_link, start_collection_download

        chat_id, message_id, link_type = parse_link(link)
        if not chat_id or not message_id:
            await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_invalid_link"))
            return
        if link_type == "private":
            from .. import bot as bot_module
            if not bot_module.userbot_client:
                await safe_execute_send(message.chat.id, message.reply_text, tr(message, "private_access"))
                return
    try:
        session = collection_store.begin(int(message.chat.id), message.from_user.id, name)
    except (ValueError, RuntimeError) as exc:
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_start_failed", error=str(exc)))
        return
    await safe_execute_send(message.chat.id, message.reply_text, tr(
        message, "collect_started", name=session.name, directory=str(session.directory),
    ))
    if link:
        await add_collection_link(message, link, session)
        remaining = collection_store.remaining_entries(session)
        if remaining:
            collection_store.set_phase(session, "downloading")
            await safe_execute_send(message.chat.id, message.reply_text, tr(
                message, "collect_ending", total=len(remaining), directory=str(session.directory),
            ))
            start_collection_download(session, message)


async def end_command(client, message: Message) -> None:
    from ..bot import collection_task_key, collection_tasks, safe_execute_send, start_collection_download

    session = collection_store.get(int(message.chat.id), message.from_user.id)
    if not session:
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_none"))
        return
    if session.phase == "downloading":
        task = collection_tasks.get(collection_task_key(session))
        if task and not task.done():
            await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_downloading"))
            return
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_already_ended"))
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


async def resume_command(client, message: Message) -> None:
    """Resume an interrupted collection download without reopening collection input."""
    from ..bot import collection_task_key, collection_tasks, safe_execute_send, start_collection_download

    requested_name = " ".join(message.command[1:]).strip() or None
    try:
        session = collection_store.get(int(message.chat.id), message.from_user.id, requested_name)
    except ValueError:
        session = None
    if not session:
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_none"))
        return
    task = collection_tasks.get(collection_task_key(session))
    if task and not task.done():
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_downloading"))
        return
    remaining = collection_store.remaining_entries(session)
    if not remaining:
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_no_items"))
        return
    collection_store.set_phase(session, "downloading")
    await safe_execute_send(message.chat.id, message.reply_text, tr(
        message, "collect_resuming", total=len(remaining), directory=str(session.directory),
    ))
    start_collection_download(session, message)


async def queue_command(client, message: Message) -> None:
    from ..bot import download_scheduler, safe_execute_send

    rows = download_scheduler.snapshot()
    if not rows:
        text = tr(message, "queue_empty")
    else:
        lines = [tr(message, "queue_summary", active=download_scheduler.active,
                    limit=download_scheduler.target_concurrency, maximum=download_scheduler.max_concurrency,
                    pending=download_scheduler.pending)]
        lines.extend(tr(message, "queue_item", group=row["label"], active=row["active"], pending=row["pending"])
                     for row in rows)
        text = "\n".join(lines)
    await safe_execute_send(message.chat.id, message.reply_text, text)


async def cancel_command(client, message: Message) -> None:
    from ..bot import (collection_task_key, collection_sessions, collection_tasks, download_group_key,
                       download_scheduler, safe_execute_send)

    requested_name = " ".join(message.command[1:]).strip() or None
    owner = (int(message.chat.id), message.from_user.id)
    if requested_name is None:
        active = [session for key, session in collection_sessions.items() if key[:2] == owner]
        session = active[-1] if active else None
    else:
        try:
            session = collection_store.get(*owner, requested_name)
        except ValueError:
            session = None
    if not session:
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_none"))
        return
    task = collection_tasks.get(collection_task_key(session))
    if not task or task.done():
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "cancel_no_task"))
        return
    count = await download_scheduler.cancel_group(download_group_key(session))
    await safe_execute_send(message.chat.id, message.reply_text,
                            tr(message, "cancel_done", name=session.name, count=count))
