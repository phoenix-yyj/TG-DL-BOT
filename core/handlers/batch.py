from pyrogram.types import Message
import logging
import time
from ..bot import user_states, batch_controller, process_batch_messages, active_downloads, safe_execute_send
from ..batch import BatchState
from ..i18n import tr
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)

async def batch_command(client, message: Message):
    """Handle batch processing command."""
    logger.info(f"[HANDLER] /batch command received from user {message.from_user.id}")
    user_id = message.from_user.id

    # Check if user already has an active batch
    current_batch = await batch_controller.get_progress(user_id)
    if current_batch and current_batch.state in [BatchState.RUNNING, BatchState.PAUSED]:
        await safe_execute_send(message.chat.id, message.reply_text, tr(
            message, "batch_running", current=current_batch.current,
            total=current_batch.total, state=current_batch.state.value
        ))
        return

    # Start new batch setup
    user_states[user_id] = {
        "step": "batch_link",
        "chat_id": int(message.chat.id),
        "timestamp": time.time()
    }

    await safe_execute_send(message.chat.id, message.reply_text, tr(message, "batch_setup"))

async def batch_status_command(client, message: Message):
    """Show current batch status."""
    logger.info(f"[HANDLER] /batch_status command received from user {message.from_user.id}")
    user_id = message.from_user.id

    current_batch = await batch_controller.get_progress(user_id)
    if not current_batch:
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "no_active_batch"))
        return

    # Calculate progress percentage
    progress_percent = (current_batch.current / current_batch.total * 100) if current_batch.total > 0 else 0

    # Calculate elapsed time
    elapsed = datetime.now() - current_batch.start_time
    elapsed_str = str(elapsed).split('.')[0]  # Remove microseconds

    status_text = tr(message, "batch_status", current=current_batch.current,
                     total=current_batch.total, percent=progress_percent,
                     state=current_batch.state.value.title(), elapsed=elapsed_str,
                     last_id=current_batch.last_processed_id)

    if current_batch.state == BatchState.RUNNING:
        status_text += tr(message, "batch_controls_running")
    elif current_batch.state == BatchState.PAUSED:
        status_text += tr(message, "batch_controls_paused")
    elif current_batch.state == BatchState.COMPLETED:
        status_text += tr(message, "batch_completed")
        await batch_controller.cleanup_completed(user_id)
    elif current_batch.state == BatchState.CANCELLED:
        status_text += tr(message, "batch_was_cancelled")
        await batch_controller.cleanup_completed(user_id)

    await message.reply_text(status_text)

async def batch_pause_command(client, message: Message):
    """Pause current batch operation."""
    logger.info(f"[HANDLER] /batch_pause command received from user {message.from_user.id}")
    user_id = message.from_user.id

    if await batch_controller.pause_batch(user_id):
        await message.reply_text(tr(message, "batch_paused"))
    else:
        await message.reply_text(tr(message, "no_batch_to_pause"))

async def batch_resume_command(client, message: Message):
    """Resume paused batch operation."""
    logger.info(f"[HANDLER] /batch_resume command received from user {message.from_user.id}")
    user_id = message.from_user.id

    # Get the current batch progress
    progress = await batch_controller.get_progress(user_id)
    if not progress or progress.state != BatchState.PAUSED:
        await message.reply_text(tr(message, "no_paused_batch"))
        return

    # Resume the batch
    if await batch_controller.resume_batch(user_id):
        await message.reply_text(tr(message, "batch_resumed"))

        # Recalculate remaining messages and the new starting point
        remaining_count = progress.total - progress.current
        new_start_message_id = progress.last_processed_id + 1

        # Restart the batch processing logic
        asyncio.create_task(
            process_batch_messages(
                user_id,
                progress.chat_id,
                new_start_message_id,
                remaining_count,
                progress.destination,
                progress.link_type
            )
        )
    else:
        await message.reply_text(tr(message, "batch_resume_failed"))

async def batch_cancel_command(client, message: Message):
    """Cancel current batch operation."""
    logger.info(f"[HANDLER] /batch_cancel command received from user {message.from_user.id}")
    user_id = message.from_user.id

    if await batch_controller.cancel_batch(user_id):
        await message.reply_text(tr(message, "batch_cancelled"))
        # Clean up user state
        user_states.pop(user_id, None)
        active_downloads.pop(user_id, None)
        await batch_controller.cleanup_completed(user_id)
    else:
        await message.reply_text(tr(message, "no_operation_to_cancel"))
