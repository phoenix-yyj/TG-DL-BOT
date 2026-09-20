from pyrogram.types import Message
import logging
from ..speed_test import run_speedtest
from ..bot import safe_execute_send
from ..i18n import tr

logger = logging.getLogger(__name__)

async def speed_command(client, message: Message):
    """Run internet speed test."""
    logger.info(f"[HANDLER] /speed command received from user {message.from_user.id}")
    try:
        result = await run_speedtest(client, message)
        if result:
            await safe_execute_send(message.chat.id, message.reply_text, result)
    except Exception as e:
        logger.error(f"[HANDLER] Error in /speed handler: {e}")
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "speed_failed", error=str(e)[:100]))
