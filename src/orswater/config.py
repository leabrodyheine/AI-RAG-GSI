"""Runtime configuration, read once from the environment (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass

try:  # .env is a convenience for local dev; real environment variables always win.
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:
    pass

DEFAULT_DATABASE_URL = "postgresql://orswater:orswater@localhost:5432/orswater"
DEFAULT_MODEL = "claude-sonnet-5"


@dataclass(frozen=True)
class Config:
    database_url: str
    anthropic_api_key: str | None
    anthropic_model: str


def load_config() -> Config:
    return Config(
        database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
    )
