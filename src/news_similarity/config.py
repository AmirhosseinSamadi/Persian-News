"""Explicit environment configuration, with no secrets in representations."""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class ConfigurationError(ValueError):
    """An actionable, safe-to-display configuration error."""


def validate_database_url(value: str) -> None:
    try:
        url = make_url(value)
    except ArgumentError:
        raise ConfigurationError("DATABASE_URL must be a valid SQLite URL.") from None
    if (
        url.drivername not in {"sqlite", "sqlite+pysqlite"}
        or not url.database
        or url.host is not None
        or url.username is not None
        or url.password is not None
        or url.port is not None
        or url.query
    ):
        raise ConfigurationError(
            "DATABASE_URL must use sqlite:///path/to/file.db or sqlite:///:memory: "
            "without connection options."
        )


@dataclass(frozen=True)
class Settings:
    telegram_api_id: int | None = field(default=None, repr=False)
    telegram_api_hash: str | None = field(default=None, repr=False)
    telegram_session_name: str = "telegram_news"
    database_url: str = "sqlite:///./data/news.db"
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        validate_database_url(self.database_url)
        if self.telegram_api_id is not None and self.telegram_api_id <= 0:
            raise ConfigurationError("TELEGRAM_API_ID must be a positive integer.")
        if self.telegram_api_hash is not None and not re.fullmatch(
            r"[0-9a-fA-F]{32}", self.telegram_api_hash
        ):
            raise ConfigurationError(
                "TELEGRAM_API_HASH must be 32 hexadecimal characters."
            )
        if (
            not self.telegram_session_name.strip()
            or self.telegram_session_name == ":memory:"
        ):
            raise ConfigurationError(
                "TELEGRAM_SESSION_NAME must name a persistent file."
            )
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError(
                "LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL."
            )

    @classmethod
    def load(
        cls,
        env_file: str | Path = ".env",
        environ: Mapping[str, str] | None = None,
    ) -> "Settings":
        """Load the explicit .env path; process environment takes precedence."""
        values = {
            **dotenv_values(env_file, interpolate=False),
            **(os.environ if environ is None else environ),
        }
        api_id = (values.get("TELEGRAM_API_ID") or "").strip()
        try:
            parsed_id = int(api_id) if api_id else None
        except ValueError:
            raise ConfigurationError(
                "TELEGRAM_API_ID must be a positive integer."
            ) from None
        return cls(
            telegram_api_id=parsed_id,
            telegram_api_hash=(values.get("TELEGRAM_API_HASH") or "").strip() or None,
            telegram_session_name=values.get("TELEGRAM_SESSION_NAME")
            or "telegram_news",
            database_url=values.get("DATABASE_URL") or "sqlite:///./data/news.db",
            log_level=(values.get("LOG_LEVEL") or "INFO").upper(),
        )

    def require_telegram(self) -> tuple[int, str]:
        if self.telegram_api_id is None or self.telegram_api_hash is None:
            raise ConfigurationError(
                "Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env or the environment "
                "before collecting Telegram news."
            )
        return self.telegram_api_id, self.telegram_api_hash
