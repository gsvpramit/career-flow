"""Workspace path constants and runtime environment configuration."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
ROLE_TRACKS_DIR = CONFIG_DIR / "role_tracks"
RULES_PATH = CONFIG_DIR / "rules" / "big_tech_rules.yaml"
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
DEFAULT_DB_PATH = DATA_DIR / "job_mark1.db"
