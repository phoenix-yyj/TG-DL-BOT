from pyrogram.types import Message
import logging
import time
from ..bot import active_downloads, user_states, parse_link, userbot_client, bot_client, fetch_message, process_message, safe_execute_send
from ..i18n import tr

logger = logging.getLogger(__name__)

async def download_command(client, message: Message):
    logger.info(f"[HANDLER] /download command received from user {message.from_user.id}")
    user_id = message.from_user.id

    if user_id in active_downloads and active_downloads[user_id]:
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "download_in_progress"))
        return

    if len(message.command) > 1:
        link = " ".join(message.command[1:])
        await process_download_link(message, link)
    else:
        user_states[user_id] = {
            "step": "download",
            "chat_id": int(message.chat.id),
            "timestamp": time.time()
        }
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "download_prompt"))

async def process_download_link(m: Message, link: str) -> None:
    """Process a download link."""
    user_id = m.from_user.id
    destination = int(m.chat.id)

    # Mark as active
    active_downloads[user_id] = True

    try:
        # Parse link
        chat_id, message_id, link_type = parse_link(link)
        if not chat_id or not message_id:
            await safe_execute_send(m.chat.id, m.reply_text, tr(m, "invalid_link"))
            return

        # Check private channel access
        if link_type == "private" and not userbot_client:
            await safe_execute_send(m.chat.id, m.reply_text, tr(m, "private_access"))
            return

        # Start processing
        status_msg = await safe_execute_send(m.chat.id, m.reply_text, tr(m, "fetching"))

        # Fetch message
        msg = await fetch_message(bot_client, userbot_client, chat_id, message_id, link_type)

        if not msg:
            if status_msg:
                await safe_execute_send(m.chat.id, status_msg.edit, tr(m, "message_not_found"))
            return

        # Process the message
        result = await process_message(bot_client, userbot_client, msg, destination, link_type, user_id)

        # Update status based on result
        if "[OK]" in result:
            await status_msg.edit(tr(m, "download_complete"))
        else:
            await status_msg.edit(f"[WARNING] **Result**: {result}")

    except Exception as e:
        logger.error(f"Download processing error: {e}")
        await m.reply_text(tr(m, "processing_failed", error=str(e)[:100]))

    finally:
        # Clean up
        active_downloads.pop(user_id, None)
        user_states.pop(user_id, None)
