"""Workspace path constants and runtime environment configuration."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.getenv("CAREERFLOW_CONFIG_DIR", str(PROJECT_ROOT / "config")))
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
ROLE_TRACKS_DIR = CONFIG_DIR / "role_tracks"
RULES_PATH = CONFIG_DIR / "rules" / "big_tech_rules.yaml"
DATA_DIR = Path(os.getenv("CAREERFLOW_DATA_DIR", str(PROJECT_ROOT / "data")))
OUTPUT_DIR = Path(os.getenv("CAREERFLOW_OUTPUT_DIR", str(PROJECT_ROOT / "output")))
DEFAULT_DB_PATH = Path(os.getenv("CAREERFLOW_DB_PATH", str(DATA_DIR / "job_mark1.db")))
