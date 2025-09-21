from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv
import logging

load_dotenv()


def env(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    value = os.getenv(name, default)
    if required and (value is None or str(value).strip() == ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y"}


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logging.getLogger("aixplain").setLevel(logging.WARNING)
log = logging.getLogger("policy-navigator")

DATA_DIR = Path("data")
KAGGLE_DIR = DATA_DIR / "kaggle"
WEB_DIR = DATA_DIR / "web"
UPLOADS_DIR = DATA_DIR / "uploads"
SESSIONS_DIR = DATA_DIR / "sessions"

for d in (DATA_DIR, KAGGLE_DIR, WEB_DIR, UPLOADS_DIR, SESSIONS_DIR):
    d.mkdir(parents=True, exist_ok=True)

__all__ = [
    "env",
    "env_bool",
    "log",
    "DATA_DIR",
    "KAGGLE_DIR",
    "WEB_DIR",
    "UPLOADS_DIR",
    "SESSIONS_DIR",
]
