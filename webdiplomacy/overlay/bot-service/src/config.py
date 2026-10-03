from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_url: str
    api_keys: tuple[str, ...]
    poll_seconds: int
    dry_run: bool
    run_once: bool

    @classmethod
    def from_env(cls) -> "Settings":
        raw_keys = os.getenv(
            "WEBDIP_API_KEYS",
            "bot1,bot2,bot3,bot4,bot5,bot6,bot7",
        )

        api_keys = tuple(
            key.strip()
            for key in raw_keys.split(",")
            if key.strip()
        )

        if not api_keys:
            raise ValueError("WEBDIP_API_KEYS ne contient aucune clé.")

        return cls(
            api_url=os.getenv(
                "WEBDIP_API_URL",
                "http://webserver/api.php",
            ).rstrip("/"),
            api_keys=api_keys,
            poll_seconds=max(
                3,
                int(os.getenv("BOT_POLL_SECONDS", "10")),
            ),
            dry_run=os.getenv(
                "BOT_DRY_RUN",
                "false",
            ).lower() in {"1", "true", "yes", "on"},
            run_once=os.getenv(
                "BOT_RUN_ONCE",
                "false",
            ).lower() in {"1", "true", "yes", "on"},
        )
