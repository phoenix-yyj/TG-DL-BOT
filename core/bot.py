#!/usr/bin/env python3
"""
Fixed Telegram Message Saver Bot with complete functionality
"""

import os
import re
import time
import logging
import asyncio
import atexit
import random
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime
from mimetypes import guess_type
from concurrent.futures import ThreadPoolExecutor

# Third-party imports
from pyrogram import Client, filters, idle
from pyrogram.errors import FloodWait
from pyrogram.types import BotCommand, Message
from dotenv import load_dotenv

# Local imports
from .server import start_server
from .batch import BatchController, BatchState
from .speed_test import run_speedtest
from .config import config
from .performance import performance_optimizer
from .managers.download_manager import download_manager, DownloadTask
from .i18n import tr
from .collection_store import CollectionEntry, CollectionSession, collection_store

# Performance optimization
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

# Configure logging with Windows-compatible encoding
import sys

class SafeFormatter(logging.Formatter):
    def format(self, record):
        msg = super().format(record)
        emoji_replacements = {
            '✅': '[OK]', '❌': '[ERROR]', '⚠️': '[WARNING]', '🚀': '[START]',
            '🤖': '[BOT]', '🌐': '[SERVER]', '📊': '[METRICS]', '🔍': '[SEARCH]',
            '📥': '[DOWNLOAD]', '📤': '[UPLOAD]', '⚡': '[FAST]', '🎉': '[SUCCESS]'
        }
        for emoji, replacement in emoji_replacements.items():
            msg = msg.replace(emoji, replacement)
        return msg

# Setup logging handlers
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(SafeFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

file_handler = logging.FileHandler('bot.log', mode='a', encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler], force=True)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Validate credentials
if not config.validate():
    logger.error("Missing API credentials! Check your .env file.")
    exit(1)
logger.info("[OK] Credentials validated successfully")

# Initialize clients with optimized settings
bot_client = Client(
    "bot_session",
    api_id=config.api_id,
    api_hash=config.api_hash,
    bot_token=config.bot_token,
    workers=config.bot_client_workers,
    workdir="./sessions"
)

userbot_client = None
if config.session:
    try:
        userbot_client = Client(
            "userbot_session",
            api_id=config.api_id,
            api_hash=config.api_hash,
            session_string=config.session,
            workers=config.userbot_client_workers,
            workdir="./sessions"
        )
        logger.info("[OK] Userbot configured - Private channel access enabled")
    except Exception as e:
        logger.warning(f"[WARNING] Could not configure userbot: {e}")
        logger.warning("[WARNING] Bot will work for public channels only")
        userbot_client = None
else:
    logger.warning("[WARNING] No session string found. Bot will work for public channels only")
    logger.info("[INFO] Configure SESSION to enable private-channel access")

# Enhanced state management
user_states: Dict[int, Dict[str, Any]] = {}
progress_info: Dict[int, Dict[str, Any]] = {}
active_downloads: Dict[int, bool] = {}
rate_limits: Dict[int, Dict[str, Any]] = {}
collection_tasks: Dict[tuple[int, int], asyncio.Task] = {}

# Batch operation controller
batch_controller = BatchController()

# Thread pool for CPU-intensive operations
thread_pool = ThreadPoolExecutor(max_workers=4)

# Optimized constants
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]
RATE_LIMIT_WINDOW = 60
MAX_REQUESTS = 30
MAX_FILE_SIZE = 2000 * 1024 * 1024  # 2GB

# Cleanup function
async def cleanup_resources():
    """Enhanced cleanup function with proper resource management."""
    try:
        if userbot_client and userbot_client.is_connected:
            await userbot_client.stop()
            logger.info("[OK] Userbot stopped successfully")
        
        if bot_client.is_connected:
            await bot_client.stop()
            logger.info("[OK] Bot client stopped successfully")
        
        thread_pool.shutdown(wait=True)
        logger.info("[OK] Thread pool shutdown complete")
        
        user_states.clear()
        progress_info.clear()
        active_downloads.clear()
        rate_limits.clear()
        for task in collection_tasks.values():
            task.cancel()
        collection_tasks.clear()
        
        session_dir = "./sessions"
        if os.path.exists(session_dir):
            for file in os.listdir(session_dir):
                if file.endswith(('.session', '.session-journal')):
                    try:
                        os.remove(os.path.join(session_dir, file))
                    except Exception as e:
                        logger.warning(f"Could not remove session file {file}: {e}")
        
        logger.info("[OK] Cleanup completed successfully")
        
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

def sync_cleanup():
    """Synchronous wrapper for cleanup."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(cleanup_resources())
        else:
            loop.run_until_complete(cleanup_resources())
    except RuntimeError:
        # At interpreter shutdown there may be no current event loop.
        return
    except Exception as e:
        logger.error(f"Error in sync cleanup: {e}")

atexit.register(sync_cleanup)

# Core utility functions
def sanitize_filename(filename: str, max_length: int = 200) -> str:
    """
    Sanitize filename for Windows compatibility.
    Removes or replaces invalid characters.
    """
    # Characters invalid on Windows: < > : " / \ | ? *
    invalid_chars = r'<>:"/\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Remove leading/trailing spaces and dots
    filename = filename.strip('. ')
    
    # Limit length (Windows has 255 char limit per filename)
    if len(filename) > max_length:
        name, ext = os.path.splitext(filename)
        filename = name[:max_length-len(ext)] + ext
    
    # If filename is empty, use a default
    if not filename:
        filename = "download"
    
    return filename

def parse_link(link: str) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """
    Parses a Telegram message link and extracts the chat ID, message ID, and link type.

    Args:
        link: The Telegram message link to parse.

    Returns:
        A tuple containing the chat ID, message ID, and link type ('public' or 'private').
        Returns (None, None, None) if the link is invalid.
    """
    if not link or not isinstance(link, str):
        return None, None, None

    link = link.strip()
    
    # Handle links without protocol
    if not link.startswith(('http://', 'https://')):
        if link.startswith('t.me/'):
            link = f"https://{link}"
        elif 't.me/' in link:
            link = f"https://{link}"
        else:
            return None, None, None
    
    try:
        # Private channel patterns
        private_patterns = [
            r"https://t\.me/c/(\d+)/(\d+)/?(?:\?[^/]*)?$",  # Standard private link
            r"https://t\.me/c/(\d+)/\d+/(\d+)/?(?:\?[^/]*)?$",  # Thread message in private channel
        ]
        
        for pattern in private_patterns:
            match = re.match(pattern, link)
            if match:
                chat_id = int(f"-100{match.group(1)}")
                message_id = int(match.group(2))
                logger.debug(f"Parsed private link: chat_id={chat_id}, message_id={message_id}")
                return chat_id, message_id, "private"
        
        # Public channel pattern - more flexible username validation
        public_match = re.match(r"https://t\.me/([^/?]+)/(\d+)/?(?:\?[^/]*)?$", link)
        if public_match:
            username = public_match.group(1)
            message_id = int(public_match.group(2))
            
            # Telegram username validation: 5-32 chars, alphanumeric + underscore, can't start/end with underscore
            # But allow some flexibility for edge cases and bots
            if (len(username) >= 3 and len(username) <= 32 and 
                re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_]*[a-zA-Z0-9]$", username) or
                re.match(r"^[a-zA-Z0-9]{3,32}$", username)):  # Handle usernames without underscores
                logger.debug(f"Parsed public link: username={username}, message_id={message_id}")
                return username, message_id, "public"
            else:
                logger.warning(f"Invalid username format: {username}")
        
        logger.warning(f"Unsupported link format: {link}")
        return None, None, None
        
    except (ValueError, AttributeError) as e:
        logger.error(f"Error parsing link {link}: {e}")
        return None, None, None


def is_retryable_error(error: BaseException) -> bool:
    """Classify transient transport/API failures without retrying known bad input."""
    if isinstance(error, (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError, FloodWait)):
        return True
    error_text = str(error).lower()
    return any(marker in error_text for marker in (
        "flood wait", "timeout", "timed out", "connection", "network",
        "internal server", "rpc call fail", "temporarily unavailable",
    ))

async def fetch_message(client: Client, userbot: Optional[Client], chat_id: Any, message_id: int, link_type: str) -> Optional[Message]:
    """
    Fetches a message from a public or private channel with retry logic.

    Args:
        client: The bot's Pyrogram client.
        userbot: The user's Pyrogram client for private channels.
        chat_id: The ID of the chat where the message is located.
        message_id: The ID of the message to fetch.
        link_type: The type of link ('public' or 'private').

    Returns:
        The fetched message object, or None if the message could not be fetched.
    """
    target_client = client if link_type == "public" else userbot
    
    if not target_client:
        logger.error(f"No client available for {link_type} channel access")
        return None
    
    for attempt in range(MAX_RETRIES):
        try:
            logger.debug(f"Fetching message {message_id} from {chat_id} (attempt {attempt + 1})")
            
            message = await asyncio.wait_for(
                target_client.get_messages(chat_id, message_id),
                timeout=30.0
            )
            
            if message and not message.empty:
                logger.debug(f"Successfully fetched message {message_id}")
                return message
            else:
                logger.warning(f"Message {message_id} is empty or deleted")
                return None
                
        except FloodWait as flood_wait:
            wait_time = min(int(getattr(flood_wait, "value", 5)), config.flood_wait_max_cap)
            logger.warning(f"Flood wait: sleeping for {wait_time}s")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(wait_time)
                continue
        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching message {message_id} (attempt {attempt + 1})")
        except Exception as e:
            error_msg = str(e).lower()
            
            if "message not found" in error_msg or "chat not found" in error_msg:
                logger.warning(f"Message {message_id} not found or inaccessible")
                return None
            if not is_retryable_error(e):
                logger.warning(f"Non-retryable fetch error for message {message_id}: {e}")
                return None
            logger.error(f"Error fetching message {message_id} (attempt {attempt + 1}): {e}")
            
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[attempt])
    
    logger.error(f"Failed to fetch message {message_id} after {MAX_RETRIES} attempts")
    return None


async def safe_send_message(client: Client, chat_id: Any, text: str, max_retries: int = 2, max_wait_cap: int = 60):
    """Send a message while handling FloodWait and transient errors.

    Returns the sent message object on success or None on failure/skip.
    """
    for attempt in range(max_retries + 1):
        try:
            await rate_limiter.acquire(chat_id)
            return await client.send_message(chat_id, text)
        except FloodWait as fw:
            try:
                wait_time = int(re.search(r"\d+", str(fw)).group())
            except Exception:
                wait_time = 5
            wait_time = min(wait_time, max_wait_cap)
            # small jitter to reduce contention
            jitter = random.uniform(0, 1)
            logger.warning(f"Flood wait while sending message: sleeping for {wait_time + jitter:.1f}s (attempt {attempt + 1})")
            await asyncio.sleep(wait_time + jitter)
            continue
        except Exception as e:
            logger.warning(f"Failed to send message to {chat_id}: {e}")
            return None

    logger.error(f"Could not send message to {chat_id} after {max_retries + 1} attempts")
    return None


class RateLimiter:
    """Simple token-bucket rate limiter per key (chat_id).

    Defaults to 1 token/sec with burst up to 5 tokens.
    """
    def __init__(self, rate: float = 1.0, per: float = 1.0, burst: int = 5):
        self.rate = rate
        self.per = per
        self.burst = burst
        self._allowance: Dict[Any, float] = {}
        self._last_check: Dict[Any, float] = {}

    async def acquire(self, key: Any) -> None:
        now = time.time()
        allowance = self._allowance.get(key, float(self.burst))
        last = self._last_check.get(key, now)

        # refill tokens
        elapsed = now - last
        allowance = min(self.burst, allowance + elapsed * (self.rate / self.per))

        if allowance >= 1.0:
            allowance -= 1.0
            self._allowance[key] = allowance
            self._last_check[key] = now
            return

        # need to wait for tokens
        needed = 1.0 - allowance
        # time per token
        token_time = self.per / self.rate if self.rate > 0 else 1.0
        wait_time = needed * token_time
        # small jitter
        wait_time += random.uniform(0, 0.5)
        await asyncio.sleep(wait_time)
        # consume token
        self._allowance[key] = 0.0
        self._last_check[key] = time.time()


# Global rate limiter instance - initialized with config values
rate_limiter = RateLimiter(
    rate=config.rate_limit_rate,
    per=config.rate_limit_per,
    burst=config.rate_limit_burst
)


async def safe_execute_send(chat_id: Any, send_coro, *args, max_retries: int = 3, max_wait_cap: int = 300, **kwargs):
    """Execute a send/copy/upload coroutine with rate limiting and FloodWait handling.

    `send_coro` must be an awaitable/coroutine function (callable).
    """
    for attempt in range(max_retries + 1):
        try:
            await rate_limiter.acquire(chat_id)
            result = await send_coro(*args, **kwargs)
            return result
        except FloodWait as fw:
            try:
                wait_time = int(re.search(r"\d+", str(fw)).group())
            except Exception:
                wait_time = 5
            wait_time = min(wait_time, max_wait_cap)
            jitter = random.uniform(0, 1)
            logger.warning(f"Flood wait in send operation: sleeping {wait_time + jitter:.1f}s (attempt {attempt + 1})")
            await asyncio.sleep(wait_time + jitter)
            continue
        except Exception as e:
            logger.warning(f"Send operation failed (attempt {attempt + 1}): {e}")
            if attempt < max_retries:
                delay = min(2 ** attempt + random.uniform(0, 0.5), 10)
                await asyncio.sleep(delay)
                continue
            return None

    return None

async def safe_remove_file(file_path: str) -> bool:
    """
    Safely removes a file from the local filesystem.

    Args:
        file_path: The path to the file to remove.

    Returns:
        True if the file was successfully removed, False otherwise.
    """
    if not file_path or not isinstance(file_path, str):
        return False
    
    try:
        if os.path.exists(file_path):
            await asyncio.get_event_loop().run_in_executor(thread_pool, os.remove, file_path)
            logger.debug(f"Removed file: {os.path.basename(file_path)}")
            return True
        return False
    except Exception as e:
        logger.warning(f"Could not remove file {os.path.basename(file_path)}: {e}")
        return False

async def validate_file(file_path: str) -> tuple[bool, str]:
    """
    Validates a file to ensure it exists, is a file, and is not empty or too large.

    Args:
        file_path: The path to the file to validate.

    Returns:
        A tuple containing a boolean indicating whether the file is valid and a message.
    """
    if not file_path or not isinstance(file_path, str):
        return False, "Invalid file path"
    
    try:
        def check_file():
            if not os.path.exists(file_path):
                return False, "File does not exist"
            
            if not os.path.isfile(file_path):
                return False, "Path is not a file"
            
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                return False, "File is empty"
            
            if file_size > MAX_FILE_SIZE:
                return False, f"File size ({file_size/1024/1024:.1f}MB) exceeds 2GB limit"
            
            try:
                with open(file_path, 'rb') as f:
                    f.read(1024)
            except Exception:
                return False, "File is not readable"
            
            return True, f"Valid file ({file_size/1024/1024:.1f}MB)"
        
        return await asyncio.get_event_loop().run_in_executor(thread_pool, check_file)
        
    except Exception as e:
        return False, f"Validation error: {str(e)}"


def get_media_file_size(message: Message) -> int:
    """Return Telegram's declared media size when the message exposes one."""
    for attribute in ("document", "video", "audio", "voice", "animation", "photo"):
        media = getattr(message, attribute, None)
        size = getattr(media, "file_size", None)
        if isinstance(size, int):
            return size
    return 0


def collection_file_name(entry: CollectionEntry, message: Message) -> str:
    """Create a stable, collision-free local filename for a collection item."""
    source_name = None
    extension = ".bin"
    if message.document:
        source_name = message.document.file_name
    elif message.video:
        extension = ".mp4"
    elif message.audio:
        extension = ".mp3"
    elif message.photo:
        extension = ".jpg"
    elif message.animation:
        extension = ".gif"
    elif message.voice:
        extension = ".ogg"
    elif message.video_note:
        extension = ".mp4"
    elif message.sticker:
        extension = ".webp"

    if source_name:
        original_name = sanitize_filename(os.path.basename(source_name))
        stem, source_extension = os.path.splitext(original_name)
        return f"{entry.sequence:04d}_{sanitize_filename(stem)}{source_extension or extension}"
    return f"{entry.sequence:04d}_message_{entry.message_id}{extension}"


async def download_collection_entry(session: CollectionSession, entry: CollectionEntry) -> tuple[str, Optional[str], Optional[str]]:
    """Download one saved message reference to its collection directory only."""
    collection_store.update_entry(session, entry, "downloading")
    source_link_type = "private" if entry.link_type == "private" else "public"
    message = await fetch_message(
        bot_client, userbot_client, entry.source_chat_id, entry.message_id, source_link_type,
    )
    if not message:
        return "failed", None, "无法获取源消息"
    if not message.media:
        return "skipped", None, "消息不包含媒体"

    declared_size = get_media_file_size(message)
    if declared_size > MAX_FILE_SIZE:
        return "failed", None, "文件超过 2GB 限制"

    target_client = userbot_client if entry.link_type == "private" else bot_client
    if not target_client:
        return "failed", None, "私有频道需要配置 userbot"

    output_name = collection_file_name(entry, message)
    output_path = session.directory / output_name
    started_at = time.monotonic()
    for attempt in range(MAX_RETRIES):
        try:
            downloaded_path = await asyncio.wait_for(
                target_client.download_media(message, file_name=str(output_path)),
                timeout=float(config.download_timeout_sec),
            )
            valid, validation_message = await validate_file(downloaded_path)
            if not valid:
                await safe_remove_file(downloaded_path)
                return "failed", None, validation_message
            performance_optimizer.record_download(os.path.getsize(downloaded_path), time.monotonic() - started_at)
            return "success", os.path.basename(downloaded_path), None
        except Exception as exc:
            if attempt < MAX_RETRIES - 1 and is_retryable_error(exc):
                await safe_remove_file(str(output_path))
                await asyncio.sleep(performance_optimizer.get_retry_delay(attempt, jitter=True))
                continue
            await safe_remove_file(str(output_path))
            return "failed", None, str(exc)[:160]
    return "failed", None, "下载重试次数已耗尽"


def collection_summary(session: CollectionSession) -> tuple[int, int, int]:
    success = sum(entry.status == "success" for entry in session.entries)
    skipped = sum(entry.status == "skipped" for entry in session.entries)
    failed = sum(entry.status == "failed" for entry in session.entries)
    return success, skipped, failed


def start_collection_download(session: CollectionSession, request_message: Message) -> None:
    """Launch the persistent local-download worker once for a collection."""
    key = (session.owner_chat_id, session.owner_user_id)
    if task := collection_tasks.get(key):
        if not task.done():
            return
    collection_tasks[key] = asyncio.create_task(process_collection_download(session, request_message))


async def process_collection_download(session: CollectionSession, request_message: Message) -> None:
    """Run a bounded local-only download queue and persist each completed item."""
    pending = collection_store.remaining_entries(session)
    status_message = await safe_send_message(
        bot_client, session.owner_chat_id,
        tr(request_message, "collect_progress", name=session.name, done=0, total=len(pending),
           success=0, skipped=0, failed=0),
    )
    queue: asyncio.Queue[Optional[CollectionEntry]] = asyncio.Queue()
    for entry in pending:
        queue.put_nowait(entry)
    completed = 0
    last_update = 0.0
    progress_lock = asyncio.Lock()

    async def update_progress(force: bool = False) -> None:
        nonlocal last_update
        now = time.monotonic()
        if not status_message or (not force and now - last_update < 3):
            return
        last_update = now
        success, skipped, failed = collection_summary(session)
        await safe_execute_send(
            session.owner_chat_id, status_message.edit,
            tr(request_message, "collect_progress", name=session.name, done=completed,
               total=len(pending), success=success, skipped=skipped, failed=failed),
        )

    async def worker() -> None:
        nonlocal completed
        while True:
            entry = await queue.get()
            try:
                if entry is None:
                    return
                status, output_file, error = await download_collection_entry(session, entry)
                collection_store.update_entry(session, entry, status, output_file, error)
                async with progress_lock:
                    completed += 1
                    await update_progress(force=completed == len(pending))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                collection_store.update_entry(session, entry, "failed", error=str(exc)[:160])
                async with progress_lock:
                    completed += 1
                    await update_progress(force=completed == len(pending))
            finally:
                queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(min(config.max_concurrent_downloads, len(pending)))]
    try:
        await queue.join()
        for _ in workers:
            queue.put_nowait(None)
        await asyncio.gather(*workers)
        collection_store.set_phase(session, "completed")
        success, skipped, failed = collection_summary(session)
        completion = tr(request_message, "collect_complete", name=session.name,
                        directory=str(session.directory), success=success, skipped=skipped, failed=failed)
        if status_message:
            await safe_execute_send(session.owner_chat_id, status_message.edit, completion)
        else:
            await safe_send_message(bot_client, session.owner_chat_id, completion)
    except asyncio.CancelledError:
        collection_store.set_phase(session, "completed")
        raise
    except Exception as exc:
        collection_store.set_phase(session, "completed")
        await safe_send_message(bot_client, session.owner_chat_id, tr(request_message, "collect_failed", error=str(exc)[:160]))
    finally:
        collection_tasks.pop((session.owner_chat_id, session.owner_user_id), None)

async def process_message(bot_client: Client, userbot: Optional[Client], message: Message, 
                        destination: int, link_type: str, user_id: int,
                        show_progress: bool = True) -> str:
    """
    Processes a fetched message, downloading and forwarding media or copying text.

    Args:
        bot_client: The bot's Pyrogram client.
        userbot: The user's Pyrogram client for private channels.
        message: The message to process.
        destination: The chat ID where the message should be sent.
        link_type: The type of link ('public' or 'private').
        user_id: The ID of the user who initiated the request.

    Returns:
        A string indicating the result of the operation.
    """
    if not message:
        return "[ERROR] Message not found"
    
    try:
        # Log message details
        logger.info(f"[PROCESS] Message ID: {message.id}, Has media: {bool(message.media)}, Has text: {bool(message.text)}")
        
        if message.media:
            media_type = None
            if message.photo:
                media_type = "photo"
            elif message.video:
                media_type = "video"
            elif message.document:
                media_type = "document"
            elif message.audio:
                media_type = "audio"
            elif message.voice:
                media_type = "voice"
            elif message.video_note:
                media_type = "video_note"
            elif message.sticker:
                media_type = "sticker"
            elif message.animation:
                media_type = "animation"
            else:
                media_type = "unknown"
            
            logger.info(f"[PROCESS] Media type detected: {media_type}")
        
        # Handle media messages
        if message.media:
            # Try simple copy first for public channels
            if link_type == "public":
                try:
                    logger.info(f"[PROCESS] Attempting simple copy for public channel media")
                    res = await safe_execute_send(destination, message.copy, chat_id=destination)
                    if res is not None:
                        return "[OK] Media sent (copied)"
                    else:
                        logger.warning("[PROCESS] Copy returned None, falling back to download/upload")
                except Exception as copy_error:
                    logger.warning(f"[PROCESS] Copy failed, falling back to download/upload: {copy_error}")
            
            # Use download/upload method for private channels or if copy failed
            return await process_media_message(
                bot_client, userbot, message, destination, link_type, user_id, show_progress
            )
        
        # Handle text messages
        elif message.text:
                try:
                    logger.info(f"[PROCESS] Processing text message")
                    if link_type == "private" and userbot:
                        sent_message = await safe_send_message(bot_client, destination, message.text)
                        if sent_message is None:
                            raise RuntimeError("Could not send text message")
                    else:
                        res = await safe_execute_send(destination, message.copy, chat_id=destination)
                        if res is None:
                            raise Exception("Copy failed")
                    return "[OK] Text sent"
                except Exception as e:
                    logger.error(f"Error sending text message: {e}")
                    return f"[ERROR] Text failed: {str(e)[:50]}"
        
        else:
            logger.warning(f"[PROCESS] Unsupported message type - no media or text")
            return "[ERROR] Unsupported message type"
            
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return f"[ERROR] Error: {str(e)[:50]}"

async def process_media_message(bot_client: Client, userbot: Optional[Client], message: Message, 
                               destination: int, link_type: str, user_id: int,
                               show_progress: bool = True) -> str:
    """
    Downloads, uploads, and forwards a media message with progress updates.

    Args:
        bot_client: The bot's Pyrogram client.
        userbot: The user's Pyrogram client for private channels.
        message: The message containing the media to process.
        destination: The chat ID where the media should be sent.
        link_type: The type of link ('public' or 'private').
        user_id: The ID of the user who initiated the request.

    Returns:
        A string indicating the result of the operation.
    """
    target_client = userbot if link_type == "private" and userbot else bot_client
    downloaded_file = None
    status_msg = None
    
    # Progress callback for downloads (optimized)
    async def download_progress(current, total):
        try:
            if show_progress and status_msg:
                percentage = int((current / total) * 100) if total > 0 else 0
                
                # Initialize timing
                if not hasattr(download_progress, 'start_time'):
                    download_progress.start_time = time.time()
                    download_progress.last_update = 0
                    download_progress.last_percentage = -1
                
                elapsed = time.time() - download_progress.start_time
                
                # Use performance optimizer for intelligent throttling
                if not performance_optimizer.should_update_progress(
                    current, total, download_progress.last_update, download_progress.last_percentage
                ):
                    return
                
                # Calculate speed
                if elapsed > 0:
                    speed = current / elapsed / (1024 * 1024)  # MB/s
                    eta = performance_optimizer.calculate_eta(current, total, elapsed)
                else:
                    speed = 0
                    eta = "calculating..."
                
                # Create progress bar
                filled = int(percentage / 5)  # 20 blocks
                bar = "█" * filled + "░" * (20 - filled)
                
                progress_text = (
                    f"📥 **Downloading** (Optimized)\n\n"
                    f"`{bar}` {percentage}%\n\n"
                    f"🚀 Speed: {speed:.1f} MB/s\n"
                    f"⏱️ ETA: {eta}\n"
                    f"📦 {current/(1024*1024):.1f}/{total/(1024*1024):.1f} MB"
                )
                
                try:
                    await status_msg.edit(progress_text)
                    download_progress.last_update = time.time()
                    download_progress.last_percentage = percentage
                except Exception:
                    pass  # Ignore edit errors
        except Exception as e:
            logger.debug(f"Progress update error: {e}")
    
    # Progress callback for uploads (optimized)
    async def upload_progress(current, total):
        try:
            if show_progress and status_msg:
                percentage = int((current / total) * 100) if total > 0 else 0
                
                # Initialize timing
                if not hasattr(upload_progress, 'start_time'):
                    upload_progress.start_time = time.time()
                    upload_progress.last_update = 0
                    upload_progress.last_percentage = -1
                
                elapsed = time.time() - upload_progress.start_time
                
                # Use performance optimizer for intelligent throttling
                if not performance_optimizer.should_update_progress(
                    current, total, upload_progress.last_update, upload_progress.last_percentage
                ):
                    return
                
                # Calculate speed
                if elapsed > 0:
                    speed = current / elapsed / (1024 * 1024)  # MB/s
                    eta = performance_optimizer.calculate_eta(current, total, elapsed)
                else:
                    speed = 0
                    eta = "calculating..."
                
                # Create progress bar
                filled = int(percentage / 5)  # 20 blocks
                bar = "█" * filled + "░" * (20 - filled)
                
                progress_text = (
                    f"📤 **Uploading** (Optimized)\n\n"
                    f"`{bar}` {percentage}%\n\n"
                    f"🚀 Speed: {speed:.1f} MB/s\n"
                    f"⏱️ ETA: {eta}\n"
                    f"📦 {current/(1024*1024):.1f}/{total/(1024*1024):.1f} MB"
                )
                
                try:
                    await status_msg.edit(progress_text)
                    upload_progress.last_update = time.time()
                    upload_progress.last_percentage = percentage
                except Exception:
                    pass  # Ignore edit errors
        except Exception as e:
            logger.debug(f"Progress update error: {e}")
    
    try:
        declared_size = get_media_file_size(message)
        if declared_size > MAX_FILE_SIZE:
            return f"[ERROR] File size ({declared_size / 1024 / 1024:.1f}MB) exceeds 2GB limit"

        # Ensure downloads directory exists
        os.makedirs("downloads", exist_ok=True)
        
        # Send initial status (use safe sender to handle FloodWait)
        if show_progress:
            status_msg = await safe_send_message(bot_client, destination, "📥 **Starting download...**")
        
        # Generate a sanitized filename
        file_ext = ""
        if message.media:
            # Get the file extension based on media type
            if message.video:
                file_ext = ".mp4"
            elif message.audio:
                file_ext = ".mp3"
            elif message.document:
                file_ext = os.path.splitext(message.document.file_name)[1] if message.document.file_name else ".bin"
            elif message.photo:
                file_ext = ".jpg"
            elif message.animation:
                file_ext = ".gif"
            else:
                file_ext = ".bin"
        
        # Create a unique sanitized filename
        message_title = message.chat.title or f"message_{message.id}"
        sanitized_title = sanitize_filename(message_title)
        # The same message can be requested concurrently, and different chats can
        # share both a title and a message ID.  A per-transfer suffix prevents one
        # task from overwriting or deleting another task's temporary file.
        unique_filename = f"{sanitized_title}_{message.id}_{uuid.uuid4().hex}{file_ext}"
        filepath = os.path.join("downloads", unique_filename)
        
        # Download media
        for attempt in range(MAX_RETRIES):
            try:
                logger.info(f"[DOWNLOAD] Attempt {attempt + 1} to download media from message {message.id}")
                
                downloaded_file = await asyncio.wait_for(
                    target_client.download_media(
                        message, 
                        file_name=filepath,
                        progress=download_progress
                    ),
                    timeout=float(config.download_timeout_sec)
                )
                
                logger.info(f"[DOWNLOAD] Downloaded file: {downloaded_file}")
                
                if downloaded_file:
                    is_valid, validation_msg = await validate_file(downloaded_file)
                    if is_valid:
                        break
                    else:
                        await safe_remove_file(downloaded_file)
                        downloaded_file = None
                        raise Exception(f"File validation failed: {validation_msg}")
                        
            except asyncio.TimeoutError:
                logger.warning(f"Download timeout (attempt {attempt + 1})")
                performance_optimizer.record_retry()
                if attempt < MAX_RETRIES - 1:
                    retry_delay = performance_optimizer.get_retry_delay(attempt, jitter=True)
                    logger.debug(f"Retrying after {retry_delay:.2f}s with jitter")
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    raise Exception("Download timeout after retries")
                    
            except Exception as e:
                logger.warning(f"Download attempt {attempt + 1} failed: {e}")
                performance_optimizer.record_retry()
                if attempt < MAX_RETRIES - 1 and is_retryable_error(e):
                    retry_delay = performance_optimizer.get_retry_delay(attempt, jitter=True)
                    logger.debug(f"Retrying after {retry_delay:.2f}s with jitter")
                    await asyncio.sleep(retry_delay)
                    continue
                raise
        
        if not downloaded_file:
            raise Exception("Download failed after all retries")
        
        # Upload media
        for attempt in range(MAX_RETRIES):
            try:
                caption = message.caption if message.caption else ""
                
                # Update status for upload
                if show_progress and status_msg:
                    try:
                        await status_msg.edit("📤 **Starting upload...**")
                    except Exception:
                        pass
                
                # Choose appropriate upload method with progress
                if message.photo:
                    sent_message = await safe_execute_send(destination, bot_client.send_photo, destination, photo=downloaded_file, caption=caption, progress=upload_progress)
                elif message.video:
                    sent_message = await safe_execute_send(destination, bot_client.send_video, destination, video=downloaded_file, caption=caption, progress=upload_progress)
                elif message.document:
                    sent_message = await safe_execute_send(destination, bot_client.send_document, destination, document=downloaded_file, caption=caption, progress=upload_progress)
                elif message.audio:
                    sent_message = await safe_execute_send(destination, bot_client.send_audio, destination, audio=downloaded_file, caption=caption, progress=upload_progress)
                elif message.voice:
                    sent_message = await safe_execute_send(destination, bot_client.send_voice, destination, voice=downloaded_file, progress=upload_progress)
                elif message.video_note:
                    sent_message = await safe_execute_send(destination, bot_client.send_video_note, destination, video_note=downloaded_file, progress=upload_progress)
                elif message.sticker:
                    sent_message = await safe_execute_send(destination, bot_client.send_sticker, destination, sticker=downloaded_file, progress=upload_progress)
                elif message.animation:
                    sent_message = await safe_execute_send(destination, bot_client.send_animation, destination, animation=downloaded_file, caption=caption, progress=upload_progress)
                else:
                    sent_message = await safe_execute_send(destination, bot_client.send_document, destination, document=downloaded_file, caption=caption, progress=upload_progress)
                
                if sent_message is None:
                    raise RuntimeError("Media upload did not complete")

                # Record actual transferred bytes.  ``message.document`` only
                # covers one media type, so it previously recorded zero for most
                # photos, videos, audio and animations.
                file_size = os.path.getsize(downloaded_file)
                if hasattr(download_progress, 'start_time'):
                    download_duration = time.time() - download_progress.start_time
                    performance_optimizer.record_download(
                        file_size,
                        download_duration
                    )
                
                if hasattr(upload_progress, 'start_time'):
                    upload_duration = time.time() - upload_progress.start_time
                    performance_optimizer.record_upload(
                        file_size,
                        upload_duration
                    )
                
                # Cleanup and return
                await safe_remove_file(downloaded_file)
                downloaded_file = None
                
                if show_progress and status_msg:
                    try:
                        await status_msg.delete()
                    except Exception:
                        pass
                
                return "[OK] Media sent"
                
            except Exception as e:
                error_msg = str(e).lower()
                performance_optimizer.record_retry()
                if "flood wait" in error_msg:
                    wait_time = min(int(re.search(r'\d+', str(e)).group()) if re.search(r'\d+', str(e)) else 5, 60)
                    logger.warning(f"Flood wait during upload: {wait_time}s")
                    await asyncio.sleep(wait_time)
                    continue
                elif attempt < MAX_RETRIES - 1 and is_retryable_error(e):
                    logger.warning(f"Upload attempt {attempt + 1} failed: {e}")
                    retry_delay = performance_optimizer.get_retry_delay(attempt, jitter=True)
                    logger.debug(f"Retrying upload after {retry_delay:.2f}s with jitter")
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    raise
        
        raise Exception("Upload failed after all retries")
        
    except Exception as e:
        logger.error(f"Media processing error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        try:
            if show_progress and status_msg:
                await status_msg.edit(f"[ERROR] Failed: {str(e)[:100]}")
        except Exception as edit_error:
            logger.error(f"Could not edit status message: {edit_error}")
        
        return f"[ERROR] Failed: {str(e)[:50]}"
        
    finally:
        if downloaded_file:
            await safe_remove_file(downloaded_file)

# Bot handlers









async def add_collection_link(message: Message, link: str, session: CollectionSession) -> None:
    chat_id, message_id, link_type = parse_link(link)
    if not chat_id or not message_id:
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_invalid_link"))
        return
    if link_type == "private" and not userbot_client:
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "private_access"))
        return
    entry = collection_store.add_entry(session, chat_id, message_id, link_type)
    await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_item_added", sequence=entry.sequence))


async def add_collection_media(message: Message) -> None:
    """Record a direct or forwarded media message while a collection is open."""
    if not message.from_user:
        return
    session = collection_store.get(int(message.chat.id), message.from_user.id)
    if not session or session.phase != "collecting":
        return
    entry = collection_store.add_entry(session, int(message.chat.id), message.id, "direct")
    await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_item_added", sequence=entry.sequence))


COLLECTION_COMMANDS = [
    "start", "test", "download", "help", "speed", "stats", "cleanup", "batch",
    "batch_status", "batch_pause", "batch_resume", "batch_cancel", "cancel", "collect", "end",
]


@bot_client.on_message(filters.text & ~filters.command(COLLECTION_COMMANDS))
async def handle_text_message(_: Client, m: Message) -> None:
    """Handle text messages for download links and batch setup."""
    user_id = m.from_user.id

    collection = collection_store.get(int(m.chat.id), user_id)
    if collection and collection.phase == "collecting":
        if "t.me/" in m.text:
            await add_collection_link(m, m.text, collection)
        else:
            await safe_execute_send(m.chat.id, m.reply_text, tr(m, "collect_text_ignored"))
        return
    
    # Check if user is in download state
    if user_id in user_states and user_states[user_id].get("step") == "download":
        await process_download_link(m, m.text)
        return
    
    # Check if user is in batch setup state
    if user_id in user_states and user_states[user_id].get("step") == "batch_link":
        await process_batch_setup(m, m.text)
        return
    
    # Check if user is in batch count state
    if user_id in user_states and user_states[user_id].get("step") == "batch_count":
        await process_batch_count(m, m.text)
        return
    
    # Otherwise, treat as potential download link
    if "t.me/" in m.text:
        logger.info(f"[HANDLER] Potential download link received from user {user_id}")
        await process_download_link(m, m.text)
    else:
        # Echo for testing
        await m.reply_text(tr(m, "echo", text=m.text))


@bot_client.on_message(
    filters.photo | filters.video | filters.document | filters.audio | filters.voice |
    filters.animation | filters.video_note | filters.sticker
)
async def handle_collection_media(_: Client, m: Message) -> None:
    await add_collection_media(m)

async def process_batch_setup(m: Message, link: str) -> None:
    """Process batch setup with the starting link."""
    user_id = m.from_user.id
    
    try:
        # Parse the link
        chat_id, message_id, link_type = parse_link(link)
        
        if not chat_id or not message_id:
            await m.reply_text(tr(m, "batch_invalid_link"))
            return
        
        # Check private channel access
        if link_type == "private" and not userbot_client:
            await m.reply_text(tr(m, "batch_private_access"))
            return
        
        # Store batch info and ask for count
        user_states[user_id].update({
            "step": "batch_count",
            "chat_id_target": chat_id,
            "start_message_id": message_id,
            "link_type": link_type
        })
        
        await m.reply_text(tr(m, "batch_link_valid", chat_id=chat_id, message_id=message_id,
                              link_type="私有频道" if link_type == "private" else "公开频道"))
        
    except Exception as e:
        logger.error(f"Batch setup error: {e}")
        await m.reply_text(tr(m, "batch_setup_failed", error=str(e)[:100]))

async def process_batch_count(m: Message, count_text: str) -> None:
    """Process batch count and start the batch operation."""
    user_id = m.from_user.id
    
    try:
        # Parse count
        try:
            count = int(count_text.strip())
        except ValueError:
            await m.reply_text(tr(m, "invalid_number"))
            return
        
        # Validate count
        if count < 1 or count > 300:
            await m.reply_text(tr(m, "invalid_range"))
            return
        
        # Get batch info from state
        state = user_states[user_id]
        chat_id_target = state["chat_id_target"]
        start_message_id = state["start_message_id"]
        link_type = state["link_type"]
        destination = state["chat_id"]
        
        # Clean up any previous completed batches
        await batch_controller.cleanup_completed(user_id)
        
        # Initialize batch operation
        success = await batch_controller.start_batch(user_id, count, start_message_id, chat_id_target, link_type, destination)
        if not success:
            await m.reply_text(tr(m, "batch_init_failed"))
            return
        
        # Clean up user state
        user_states.pop(user_id, None)
        
        # Start batch processing
        await m.reply_text(tr(m, "batch_started", count=count, message_id=start_message_id))
        
        # Start the actual batch processing
        task = asyncio.create_task(
            process_batch_messages(user_id, chat_id_target, start_message_id, count, destination, link_type)
        )
        await batch_controller.attach_task(user_id, task)
        
    except Exception as e:
        logger.error(f"Batch count processing error: {e}")
        await m.reply_text(tr(m, "batch_processing_failed", error=str(e)[:100]))

async def process_batch_messages(user_id: int, chat_id: Any, start_message_id: int, 
                               count: int, destination: int, link_type: str) -> None:
    """Process batch messages with parallel downloads for better performance."""
    logger.info(f"[BATCH] Starting PARALLEL batch processing for user {user_id}: {count} messages from {start_message_id}")
    
    batch_status_msg = await safe_send_message(bot_client, destination, tr(None, "batch_processing"))
    last_batch_progress_update = 0.0

    async def process_batch_message(*args) -> str:
        return await process_message(*args, show_progress=False)

    try:
        # Create download tasks
        tasks = [
            DownloadTask(
                chat_id=chat_id,
                message_id=start_message_id + i,
                link_type=link_type,
                destination=destination,
                user_id=user_id
            )
            for i in range(count)
        ]
        
        # Progress callback for batch
        async def batch_progress_callback(completed: int, total: int, message_id: int):
            nonlocal last_batch_progress_update
            progress = await batch_controller.get_progress(user_id)
            if progress and progress.state == BatchState.RUNNING:
                # Update progress with the actual message ID of the completed task
                if completed > 0:
                    await batch_controller.update_progress(user_id, message_id)

                now = time.monotonic()
                if batch_status_msg and (completed == total or now - last_batch_progress_update >= 3):
                    last_batch_progress_update = now
                    await safe_execute_send(
                        destination, batch_status_msg.edit,
                        tr(None, "batch_progress", completed=completed, total=total,
                           percent=(completed / total * 100) if total else 0),
                    )
        
        # Use parallel download manager (3 concurrent downloads)
        logger.info(f"[BATCH] Using parallel download manager with 3 concurrent downloads")
        results = await download_manager.download_batch_parallel(
            bot_client,
            userbot_client,
            tasks,
            fetch_message,
            process_batch_message,
            progress_callback=batch_progress_callback,
            wait_until_runnable=lambda: batch_controller.wait_until_runnable(user_id),
        )
        
        # Count successes and failures
        successes = sum(1 for _, result in results if "[OK]" in result or "[SUCCESS]" in result)
        failures = len(results) - successes
        
        # Check final status
        final_progress = await batch_controller.get_progress(user_id)
        if final_progress:
            elapsed = datetime.now() - final_progress.start_time
            elapsed_str = str(elapsed).split('.')[0]
            
            try:
                completion_text = tr(
                    None, "batch_complete", total=len(results), successes=successes, failures=failures,
                    elapsed=elapsed_str, rate=len(results) / elapsed.total_seconds(),
                )
                if batch_status_msg:
                    await safe_execute_send(destination, batch_status_msg.edit, completion_text)
                else:
                    await safe_send_message(bot_client, destination, completion_text)
            except Exception as e:
                logger.error(f"[BATCH] Error sending completion message: {e}")
        
    except Exception as e:
        logger.error(f"[BATCH] Fatal error in batch processing: {e}")
        performance_optimizer.record_failure()
        try:
            await safe_send_message(
                bot_client,
                destination,
                tr(None, "batch_failed", error=str(e)[:100])
            )
        except Exception:
            pass
    
    logger.info(f"[BATCH] Batch processing completed for user {user_id}")

def load_handlers():
    """Dynamically load and register all handlers."""
    try:
        # Import handler modules to get their functions
        from .handlers import start, test, help, speed, cleanup, cancel, download, batch, stats, collection
        
        # Register handlers with bot_client
        bot_client.on_message(filters.command("start"))(start.start_command)
        bot_client.on_message(filters.command("test"))(test.test_command)
        bot_client.on_message(filters.command("help"))(help.help_command)
        bot_client.on_message(filters.command("speed"))(speed.speed_command)
        bot_client.on_message(filters.command("cleanup"))(cleanup.cleanup_command)
        bot_client.on_message(filters.command("cancel"))(cancel.cancel_command)
        bot_client.on_message(filters.command("download"))(download.download_command)
        bot_client.on_message(filters.command("collect"))(collection.collect_command)
        bot_client.on_message(filters.command("end"))(collection.end_command)
        
        # Batch handlers
        bot_client.on_message(filters.command("batch"))(batch.batch_command)
        bot_client.on_message(filters.command("batch_status"))(batch.batch_status_command)
        bot_client.on_message(filters.command("batch_pause"))(batch.batch_pause_command)
        bot_client.on_message(filters.command("batch_resume"))(batch.batch_resume_command)
        bot_client.on_message(filters.command("batch_cancel"))(batch.batch_cancel_command)
        
        # Stats handler
        bot_client.on_message(filters.command("stats"))(stats.stats_command)
        
        logger.info("Successfully loaded all handlers")
        
    except Exception as e:
        logger.error(f"Failed to load handlers: {e}")
        import traceback
        traceback.print_exc()


async def setup_bot_commands() -> None:
    """Publish the command-menu shortcuts shown in the Telegram client."""
    commands = [
        BotCommand("start", "启动机器人"),
        BotCommand("help", "查看帮助"),
        BotCommand("download", "下载单条消息"),
        BotCommand("collect", "开始本地合集收集"),
        BotCommand("end", "结束合集并下载"),
        BotCommand("batch", "开始批量处理"),
        BotCommand("batch_status", "查看批量进度"),
        BotCommand("batch_pause", "暂停批量任务"),
        BotCommand("batch_resume", "继续批量任务"),
        BotCommand("batch_cancel", "取消批量任务"),
        BotCommand("cancel", "取消当前操作"),
        BotCommand("speed", "网络测速"),
        BotCommand("stats", "查看运行状态"),
        BotCommand("cleanup", "清理旧下载文件"),
        BotCommand("test", "测试机器人响应"),
    ]

    try:
        await bot_client.set_bot_commands(commands)
        logger.info("[OK] Bot command menu configured")
    except Exception as e:
        logger.warning(f"[WARNING] Could not configure bot command menu: {e}")


async def run_bot() -> None:
    """Start the bot, synchronize its command menu, then wait for shutdown."""
    await bot_client.start()
    try:
        await setup_bot_commands()
        await idle()
    finally:
        await bot_client.stop()

def main():
    """Main function to start the bot."""
    try:
        os.makedirs("./sessions", exist_ok=True)
        
        load_handlers()

        start_server()
        logger.info("[OK] Health check server started")
        
        if userbot_client:
            logger.info("[INFO] Starting userbot...")
            userbot_client.start()
            logger.info("[OK] Userbot started successfully")
        
        logger.info("[INFO] Starting bot client...")
        logger.info("[OK] Bot is ready and listening for messages...")
        logger.info("[INFO] Send /start or /test to the bot to verify it's working")
        
        # ``Client`` and the health-check task are both bound to the current
        # event loop when they are created.  Do not use ``asyncio.run()`` here:
        # it creates a second loop, which leaves Pyrogram handler workers on
        # the original loop and eventually stops command processing.
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_bot())
        
    except KeyboardInterrupt:
        logger.info("[STOP] Bot stopped by user")
    except Exception as e:
        logger.error(f"[ERROR] Bot startup error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("[STOP] Bot shutdown complete")
