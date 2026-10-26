"""Runtime configuration, read from environment variables (and backend/.env if present).

API keys are only ever read from the environment. They are never logged,
returned by the API, or written to disk by the application.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env")

DEFAULT_MODELS = {
    "anthropic": "claude-haiku-5-5",
    "openai": "gpt-4.1-mini",
    "gemini": "gemini-2.5-flash",
}
KEY_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _resolve_provider() -> str | None:
    requested = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if requested in ("none", "off", "disabled"):
        return None
    if requested in KEY_VARS:
        return requested if os.getenv(KEY_VARS[requested]) else None
    for provider, var in KEY_VARS.items():
        if os.getenv(var):
            return provider
    return None


@dataclass(frozen=True)
class Settings:
    llm_provider: str | None = field(default_factory=_resolve_provider)
    llm_model_override: str | None = field(default_factory=lambda: os.getenv("LLM_MODEL") or None)
    # Optional: route requests through a compatible proxy/gateway instead of the provider's public URL.
    llm_base_url: str | None = field(default_factory=lambda: (os.getenv("LLM_BASE_URL") or "").rstrip("/") or None)
    llm_timeout_s: int = field(default_factory=lambda: _int("LLM_TIMEOUT_SECONDS", 30))
    max_upload_mb: int = field(default_factory=lambda: _int("MAX_UPLOAD_MB", 25))
    max_rows: int = field(default_factory=lambda: _int("MAX_ROWS", 500_000))
    max_columns: int = field(default_factory=lambda: _int("MAX_COLUMNS", 200))
    max_datasets: int = field(default_factory=lambda: _int("MAX_DATASETS_IN_MEMORY", 10))
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip()
            for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
            if o.strip()
        )
    )
    sample_data_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("SAMPLE_DATA_PATH", REPO_DIR / "sample-data" / "retail_sales_2025.csv")
        )
    )
    frontend_dist: Path = field(default_factory=lambda: REPO_DIR / "frontend" / "dist")

    @property
    def llm_model(self) -> str | None:
        if not self.llm_provider:
            return None
        return self.llm_model_override or DEFAULT_MODELS[self.llm_provider]

    @property
    def llm_api_key(self) -> str | None:
        if not self.llm_provider:
            return None
        return os.getenv(KEY_VARS[self.llm_provider])

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def get_settings() -> Settings:
    return Settings()
