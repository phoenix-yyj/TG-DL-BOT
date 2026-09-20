from pyrogram.types import Message
import logging
from ..i18n import tr

logger = logging.getLogger(__name__)

async def help_command(client, message: Message):
    """Show help information."""
    logger.info(f"[HANDLER] /help command received from user {message.from_user.id}")
    
    # Import safe_execute_send from bot module
    from ..bot import safe_execute_send

    help_text = tr(message, "help")

    await safe_execute_send(message.chat.id, message.reply_text, help_text)
