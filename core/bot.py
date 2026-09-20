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
from pyrogram.errors import FileReferenceExpired, FloodWait
from pyrogram.types import BotCommand, Message
from dotenv import load_dotenv

# Local imports
from .server import start_server
from .config import config
from .performance import performance_optimizer
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
    logger.error("Missing API credentials or OWNER_USER_ID! Check your .env file.")
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

rate_limits: Dict[int, Dict[str, Any]] = {}
collection_tasks: Dict[tuple[int, int, str], asyncio.Task] = {}
pending_collection_items: Dict[tuple[int, int], tuple[int | str, int, str]] = {}


def collection_task_key(session: CollectionSession) -> tuple[int, int, str]:
    return session.owner_chat_id, session.owner_user_id, session.directory_name
owner_filter = filters.user(config.owner_user_id)

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


def select_source_client(client: Client, userbot: Optional[Client], link_type: str) -> Optional[Client]:
    """Select the same account for resolving and downloading a source message."""
    if link_type == "private":
        return userbot
    if link_type == "direct":
        # Standalone uploads live in the bot's private chat, not the user's
        # userbot session.
        return client
    return userbot or client

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
    # User accounts can read public channel posts they are not subscribed to;
    # prefer that session when configured, and fall back to the bot otherwise.
    # Private links and direct messages require the user session.
    target_client = select_source_client(client, userbot, link_type)
    
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
    source_link_type = entry.link_type
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

    target_client = select_source_client(bot_client, userbot_client, source_link_type)
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
            if valid and declared_size and os.path.getsize(downloaded_path) != declared_size:
                valid = False
                validation_message = "下载文件大小与 Telegram 声明不符，可能是文件引用过期"
            if not valid:
                await safe_remove_file(downloaded_path)
                await safe_remove_file(str(output_path))
                if attempt >= MAX_RETRIES - 1:
                    return "failed", None, validation_message
                # Pyrogram may log FILE_REFERENCE_EXPIRED internally and
                # return None/partial output instead of propagating the error.
                message = await fetch_message(
                    bot_client, userbot_client, entry.source_chat_id, entry.message_id, source_link_type,
                )
                if not message or not message.media:
                    return "failed", None, "下载失败，且无法重新获取源消息"
                await asyncio.sleep(performance_optimizer.get_retry_delay(attempt, jitter=True))
                continue
            performance_optimizer.record_download(os.path.getsize(downloaded_path), time.monotonic() - started_at)
            return "success", os.path.basename(downloaded_path), None
        except FileReferenceExpired as exc:
            await safe_remove_file(str(output_path))
            if attempt >= MAX_RETRIES - 1:
                return "failed", None, str(exc)[:160]
            # Telegram may expire a file reference between message lookup and
            # download. Refresh it from the same account before retrying.
            message = await fetch_message(
                bot_client, userbot_client, entry.source_chat_id, entry.message_id, source_link_type,
            )
            if not message or not message.media:
                return "failed", None, "文件引用过期，且无法重新获取源消息"
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
    key = collection_task_key(session)
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
        collection_tasks.pop(collection_task_key(session), None)

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
    chat_id, user_id = int(message.chat.id), message.from_user.id
    session = collection_store.get(chat_id, user_id)
    if not session or session.phase != "collecting":
        await request_single_item_name(message, chat_id, user_id, chat_id, message.id, "direct")
        return
    entry = collection_store.add_entry(session, int(message.chat.id), message.id, "direct")
    await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_item_added", sequence=entry.sequence))


async def request_single_item_name(message: Message, owner_chat_id: int, owner_user_id: int,
                                   source_chat_id: int | str, message_id: int, link_type: str) -> None:
    key = (owner_chat_id, owner_user_id)
    if key in pending_collection_items:
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "single_item_pending"))
        return
    pending_collection_items[key] = (source_chat_id, message_id, link_type)
    await safe_execute_send(message.chat.id, message.reply_text, tr(message, "single_item_ask_name"))


async def finish_single_item(message: Message, name: str) -> None:
    """Turn a pending standalone link/media message into an auto-downloading collection."""
    key = (int(message.chat.id), message.from_user.id)
    pending = pending_collection_items.get(key)
    if not pending:
        return
    source_chat_id, message_id, link_type = pending
    if link_type == "private" and not userbot_client:
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "private_access"))
        return
    try:
        session = collection_store.begin(key[0], key[1], name)
    except (ValueError, RuntimeError) as exc:
        await safe_execute_send(message.chat.id, message.reply_text, tr(message, "collect_start_failed", error=str(exc)))
        return
    pending_collection_items.pop(key, None)
    collection_store.add_entry(session, source_chat_id, message_id, link_type)
    collection_store.set_phase(session, "downloading")
    await safe_execute_send(message.chat.id, message.reply_text, tr(
        message, "single_item_started", name=session.name, directory=str(session.directory),
    ))
    start_collection_download(session, message)


COLLECTION_COMMANDS = [
    "start", "help", "stats", "collect", "end", "resume", "cancel",
]


@bot_client.on_message(filters.text & ~filters.command(COLLECTION_COMMANDS) & owner_filter)
async def handle_text_message(_: Client, m: Message) -> None:
    """Collect only links while the owner has an open collection."""
    user_id = m.from_user.id

    collection = collection_store.get(int(m.chat.id), user_id)
    if collection and collection.phase == "collecting":
        if "t.me/" in m.text:
            await add_collection_link(m, m.text, collection)
        else:
            await safe_execute_send(m.chat.id, m.reply_text, tr(m, "collect_text_ignored"))
    elif (int(m.chat.id), user_id) in pending_collection_items:
        await finish_single_item(m, m.text.strip())
    elif "t.me/" in m.text:
        chat_id, message_id, link_type = parse_link(m.text)
        if not chat_id or not message_id:
            await safe_execute_send(m.chat.id, m.reply_text, tr(m, "collect_invalid_link"))
        elif link_type == "private" and not userbot_client:
            await safe_execute_send(m.chat.id, m.reply_text, tr(m, "private_access"))
        else:
            await request_single_item_name(m, int(m.chat.id), user_id, chat_id, message_id, link_type)
    return


@bot_client.on_message(
    (filters.photo | filters.video | filters.document | filters.audio | filters.voice |
     filters.animation | filters.video_note | filters.sticker) & owner_filter
)
async def handle_collection_media(_: Client, m: Message) -> None:
    await add_collection_media(m)

def load_handlers():
    """Dynamically load and register all handlers."""
    try:
        from .handlers import start, help, stats, collection
        
        # Register handlers with bot_client
        bot_client.on_message(filters.command("start") & owner_filter)(start.start_command)
        bot_client.on_message(filters.command("help") & owner_filter)(help.help_command)
        bot_client.on_message(filters.command("collect") & owner_filter)(collection.collect_command)
        bot_client.on_message(filters.command("end") & owner_filter)(collection.end_command)
        bot_client.on_message(filters.command("resume") & owner_filter)(collection.resume_command)
        bot_client.on_message(filters.command("cancel") & owner_filter)(collection.cancel_command)
        bot_client.on_message(filters.command("stats") & owner_filter)(stats.stats_command)
        
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
        BotCommand("collect", "开始本地合集收集"),
        BotCommand("end", "结束合集并下载"),
        BotCommand("resume", "继续未完成下载"),
        BotCommand("cancel", "取消等待命名的单项任务"),
        BotCommand("stats", "查看运行状态"),
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
