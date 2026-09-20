from pyrogram.types import Message
import logging
import os
import shutil
from datetime import datetime, timedelta
from ..bot import safe_execute_send
from ..i18n import tr

logger = logging.getLogger(__name__)

async def cleanup_command(client, message: Message):
    """Clean up old downloaded files."""
    logger.info(f"[HANDLER] /cleanup command received from user {message.from_user.id}")

    try:
        status_msg = await safe_execute_send(message.chat.id, message.reply_text, tr(message, "cleanup_start"))

        downloads_dir = "downloads"
        if not os.path.exists(downloads_dir):
            await status_msg.edit(tr(message, "cleanup_none"))
            return

        # Clean files older than 24 hours
        cleaned = 0
        cutoff_time = datetime.now() - timedelta(hours=24)
        
        for filename in os.listdir(downloads_dir):
            filepath = os.path.join(downloads_dir, filename)
            if os.path.isfile(filepath):
                file_modified = datetime.fromtimestamp(os.path.getmtime(filepath))
                if file_modified < cutoff_time:
                    try:
                        os.remove(filepath)
                        cleaned += 1
                    except Exception as e:
                        logger.warning(f"Could not remove {filename}: {e}")

        # Get updated stats
        total_files = len([f for f in os.listdir(downloads_dir) if os.path.isfile(os.path.join(downloads_dir, f))])
        total_size = sum(os.path.getsize(os.path.join(downloads_dir, f)) for f in os.listdir(downloads_dir) if os.path.isfile(os.path.join(downloads_dir, f)))
        
        # Get disk space
        disk_usage = shutil.disk_usage(".")
        free_gb = disk_usage.free / (1024**3)

        cleanup_text = tr(message, "cleanup_complete", cleaned=cleaned, total_files=total_files,
                          size=total_size / (1024**2), free_gb=free_gb)

        if status_msg:
            await safe_execute_send(message.chat.id, status_msg.edit, cleanup_text)
    except Exception as e:
        logger.error(f"[HANDLER] Error in /cleanup handler: {e}")
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "cleanup_failed", error=str(e)[:100]))
