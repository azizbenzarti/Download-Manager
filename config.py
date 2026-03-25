from __future__ import annotations

from pathlib import Path


# -----------------------------
# Paths
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp"
DB_PATH = BASE_DIR / "sdm.db"
DOWNLOADS_DIR = BASE_DIR / "downloads"


# -----------------------------
# Download settings
# -----------------------------
DEFAULT_THREAD_COUNT = 4
DEFAULT_CHUNK_SIZE = 8192
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 15


# -----------------------------
# App settings
# -----------------------------
APP_NAME = "Smart Download Manager"
APP_VERSION = "1.0.0"


def ensure_directories() -> None:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)