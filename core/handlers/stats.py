from pyrogram.types import Message
import logging
import os
import shutil
from ..performance import performance_optimizer
from ..managers.download_manager import download_manager
from ..bot import safe_execute_send
from ..i18n import tr

logger = logging.getLogger(__name__)

async def stats_command(client, message: Message):
    """Show performance statistics."""
    logger.info(f"[HANDLER] /stats command received from user {message.from_user.id}")
    try:
        perf_stats = performance_optimizer.get_metrics()
        dl_stats = download_manager.get_stats()

        # Get disk space info
        try:
            disk_usage = shutil.disk_usage(".")
            free_gb = disk_usage.free / (1024**3)
            disk_info = {"free_gb": free_gb, "warning": free_gb < 1.0}
        except Exception:
            disk_info = {"free_gb": 0, "warning": False}
        
        # Get directory stats
        try:
            downloads_dir = "downloads"
            if os.path.exists(downloads_dir):
                downloaded_files = [
                    os.path.join(root, filename)
                    for root, _, filenames in os.walk(downloads_dir)
                    for filename in filenames
                    if not filename.startswith(".tgdl_collection_")
                ]
                total_files = len(downloaded_files)
                total_size = sum(os.path.getsize(filepath) for filepath in downloaded_files)
                dir_stats = {"total_files": total_files, "total_size_mb": total_size / (1024**2)}
            else:
                dir_stats = {"total_files": 0, "total_size_mb": 0}
        except Exception:
            dir_stats = {"total_files": 0, "total_size_mb": 0}

        stats_text = tr(message, "stats", downloads=perf_stats['total_downloads'],
                        uploads=perf_stats['total_uploads'], downloaded=perf_stats['total_data_downloaded_mb'],
                        uploaded=perf_stats['total_data_uploaded_mb'], download_speed=perf_stats['average_download_speed_mbps'],
                        upload_speed=perf_stats['average_upload_speed_mbps'], success_rate=perf_stats['success_rate'],
                        failed=perf_stats['failed_operations'], retries=perf_stats['retry_count'],
                        uptime=perf_stats['uptime_seconds'], max_concurrent=dl_stats['max_concurrent'],
                        active_tasks=dl_stats['active_tasks'], available_slots=dl_stats['available_slots'],
                        files=dir_stats['total_files'], size=dir_stats['total_size_mb'], free_gb=disk_info.get('free_gb', 0))

        if disk_info.get('warning'):
            stats_text += tr(message, "low_disk")

        await safe_execute_send(message.chat.id, message.reply_text, stats_text)
    except Exception as e:
        logger.error(f"[HANDLER] Error in /stats handler: {e}")
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "stats_failed", error=str(e)[:100]))
