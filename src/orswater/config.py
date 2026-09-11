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
DEFAULT_ANSWER_BACKEND = "deterministic"
VALID_ANSWER_BACKENDS = {"deterministic", "anthropic"}

# The value .env.example used to document before an empty ANTHROPIC_API_KEY= was made the
# documented placeholder. A user's existing .env may still carry it -- treat it the same as
# an empty/missing key rather than a real credential.
PLACEHOLDER_ANTHROPIC_API_KEY = "sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def _is_real_anthropic_api_key(key: str | None) -> bool:
    return bool(key) and key != PLACEHOLDER_ANTHROPIC_API_KEY


@dataclass(frozen=True)
class Config:
    database_url: str
    anthropic_api_key: str | None
    anthropic_model: str
    answer_backend: str

    @property
    def has_anthropic_credentials(self) -> bool:
        return _is_real_anthropic_api_key(self.anthropic_api_key)


def load_config() -> Config:
    answer_backend = os.environ.get("ANSWER_BACKEND", DEFAULT_ANSWER_BACKEND).strip().lower()
    if answer_backend not in VALID_ANSWER_BACKENDS:
        raise ValueError(
            f"ANSWER_BACKEND={answer_backend!r} is not supported; "
            f"use one of {sorted(VALID_ANSWER_BACKENDS)}"
        )

    return Config(
        database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
        answer_backend=answer_backend,
    )
