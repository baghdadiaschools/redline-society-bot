from dataclasses import dataclass
import os
from pathlib import Path

from .runtime import load_dotenv


@dataclass(frozen=True)
class Config:
    token: str
    guild_id: int
    owner_id: int
    data: Path
    backups: Path
    backup_hours: int
    backup_keep: int
    max_upload: int
    storage_limit: int
    max_listings: int

    @classmethod
    def load(cls) -> "Config":
        load_dotenv()
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ValueError("Set DISCORD_TOKEN in your private .env or host secret settings.")

        def positive(name: str, default: str = "") -> int:
            value = os.getenv(name, default)
            if not value.isdigit() or int(value) <= 0:
                raise ValueError(f"{name} must be a positive integer.")
            return int(value)

        data = Path(os.getenv("DATA_DIR", "./data")).resolve()
        backups = Path(os.getenv("BACKUP_DIR", "./backups")).resolve()
        if data == backups or data in backups.parents or backups in data.parents:
            raise ValueError("DATA_DIR and BACKUP_DIR must be separate, non-nested directories.")
        return cls(token, positive("GUILD_ID"), positive("OWNER_ID"), data, backups,
                   positive("BACKUP_INTERVAL_HOURS", "24"), positive("BACKUP_KEEP", "7"),
                   positive("MAX_UPLOAD_MB", "8") * 1024**2,
                   positive("STORAGE_LIMIT_MB", "2048") * 1024**2,
                   positive("MAX_LISTINGS_PER_USER", "25"))

