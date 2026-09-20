from pyrogram.types import Message
import logging
import os
import shutil
import json
from datetime import datetime, timedelta
from ..bot import safe_execute_send
from ..i18n import tr

logger = logging.getLogger(__name__)


def _active_collection_directories(downloads_dir: str) -> set[str]:
    """Return collection folders whose manifests must not be cleaned."""
    protected = set()
    for root, _, files in os.walk(downloads_dir):
        for filename in files:
            if not filename.startswith(".tgdl_collection_") or not filename.endswith(".json"):
                continue
            try:
                with open(os.path.join(root, filename), encoding="utf-8") as manifest:
                    if json.load(manifest).get("phase") in {"collecting", "downloading"}:
                        protected.add(os.path.abspath(root))
            except (OSError, ValueError, json.JSONDecodeError):
                # Preserve data when a manifest cannot be read.
                protected.add(os.path.abspath(root))
    return protected

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
        
        protected_dirs = _active_collection_directories(downloads_dir)
        for root, _, filenames in os.walk(downloads_dir):
            if os.path.abspath(root) in protected_dirs:
                continue
            for filename in filenames:
                # Manifests are recovery metadata, not disposable downloads.
                if filename.startswith(".tgdl_collection_") and filename.endswith(".json"):
                    continue
                filepath = os.path.join(root, filename)
                file_modified = datetime.fromtimestamp(os.path.getmtime(filepath))
                if file_modified < cutoff_time:
                    try:
                        os.remove(filepath)
                        cleaned += 1
                    except Exception as e:
                        logger.warning(f"Could not remove {filename}: {e}")

        # Get updated stats
        downloaded_files = [
            os.path.join(root, filename)
            for root, _, filenames in os.walk(downloads_dir)
            for filename in filenames
            if not filename.startswith(".tgdl_collection_")
        ]
        total_files = len(downloaded_files)
        total_size = sum(os.path.getsize(filepath) for filepath in downloaded_files)
        
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
