"""Configuration management for the Telegram Saver Bot."""

import os
from typing import Optional
from dotenv import load_dotenv

class Config:
    """Configuration class to manage bot settings and credentials."""
    
    def __init__(self):
        # Load environment variables
        load_dotenv()
        
        # API credentials
        self.api_id: Optional[int] = None
        self.api_hash: Optional[str] = None
        self.bot_token: Optional[str] = None
        self.session: Optional[str] = None
        self.owner_user_id: Optional[int] = None
        
        # Rate limiter settings (per destination)
        self.rate_limit_rate: float = 1.0  # tokens per second
        self.rate_limit_per: float = 1.0  # refill period
        self.rate_limit_burst: int = 5    # max tokens to hold
        
        # Worker/concurrency settings
        self.bot_client_workers: int = 4      # down from 8 to reduce pressure
        self.userbot_client_workers: int = 2  # down from 4
        self.max_concurrent_downloads: int = 2 # reduced for stability
        self.min_concurrent_downloads: int = 1
        self.download_adaptive_cooldown_sec: int = 30
        self.download_timeout_sec: int = 300
        self.archive_rules_path: str = "attached_assets/archive_rules.json"
        
        # FloodWait settings
        self.flood_wait_max_cap: int = 60  # max sleep on flood wait
        self.max_send_retries: int = 3
        
        # Load and validate configuration
        self._load_config()
    
    def _load_config(self) -> None:
        """Load and validate configuration from environment variables."""
        try:
            api_id = os.getenv("API_ID")
            if api_id:
                self.api_id = int(api_id)
            
            self.api_hash = os.getenv("API_HASH")
            self.bot_token = os.getenv("BOT_TOKEN")
            self.session = os.getenv("SESSION")
            if owner_user_id := os.getenv("OWNER_USER_ID"):
                self.owner_user_id = int(owner_user_id)
            
            # Optional rate limit overrides from env
            if rate_limit := os.getenv("RATE_LIMIT_RATE"):
                self.rate_limit_rate = float(rate_limit)
            if burst := os.getenv("RATE_LIMIT_BURST"):
                self.rate_limit_burst = int(burst)
            if workers := os.getenv("BOT_WORKERS"):
                self.bot_client_workers = int(workers)
            if max_down := os.getenv("MAX_CONCURRENT_DOWNLOADS"):
                self.max_concurrent_downloads = int(max_down)
            if min_down := os.getenv("MIN_CONCURRENT_DOWNLOADS"):
                self.min_concurrent_downloads = int(min_down)
            if cooldown := os.getenv("DOWNLOAD_ADAPTIVE_COOLDOWN_SEC"):
                self.download_adaptive_cooldown_sec = int(cooldown)
            if timeout := os.getenv("DOWNLOAD_TIMEOUT_SEC"):
                self.download_timeout_sec = int(timeout)
            self.archive_rules_path = os.getenv("ARCHIVE_RULES_PATH", self.archive_rules_path)

            if self.max_concurrent_downloads < 1:
                raise ValueError("MAX_CONCURRENT_DOWNLOADS must be at least 1")
            if self.min_concurrent_downloads < 1 or self.min_concurrent_downloads > self.max_concurrent_downloads:
                raise ValueError("MIN_CONCURRENT_DOWNLOADS must be between 1 and MAX_CONCURRENT_DOWNLOADS")
            if self.download_adaptive_cooldown_sec < 1:
                raise ValueError("DOWNLOAD_ADAPTIVE_COOLDOWN_SEC must be at least 1")
            if self.download_timeout_sec < 1:
                raise ValueError("DOWNLOAD_TIMEOUT_SEC must be at least 1")
            
        except ValueError as e:
            raise ValueError(f"Invalid configuration value: {e}")
    
    def validate(self) -> bool:
        """Validate that all required configuration is present."""
        return all([
            self.api_id is not None,
            self.api_hash,
            self.bot_token,
            self.owner_user_id is not None,
        ])

# Create a global instance
config = Config()
