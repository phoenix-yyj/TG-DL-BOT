from pyrogram.types import Message
import logging
from ..i18n import tr

logger = logging.getLogger(__name__)

async def start_command(client, message: Message):
    logger.info(f"[HANDLER] /start command received from user {message.from_user.id}")
    try:
        # ``bot`` is a sibling of the handlers package, not a handlers module.
        # Keep this import lazy so loading the handler does not create a cycle
        # while core.bot is registering handlers.
        from ..bot import safe_execute_send
        
        response = tr(message, "start")
        # Use safe execute for reply
        await safe_execute_send(message.chat.id, message.reply_text, response)
        logger.info(f"[HANDLER] /start response sent successfully")
    except Exception as e:
        logger.error(f"[HANDLER] Error in /start handler: {e}")
