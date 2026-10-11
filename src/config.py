"""Clouvia Suite - Configuration Loader."""
import os
from pathlib import Path
import toml

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config.toml"


def load_config():
    if CONFIG_PATH.exists():
        try:
            return toml.load(str(CONFIG_PATH))
        except Exception:
            return {}
    return {}


_cfg = load_config()


def get_cfg(section: str, key: str, default=None):
    return _cfg.get(section, {}).get(key, default)


TEMPIK_BASE = os.getenv("TEMPIK_BASE", get_cfg("api", "tempmail_base", "http://localhost:8080/api"))
NINE_ROUTER_URL = os.getenv("NINEROUTER_URL", get_cfg("router", "url", "http://127.0.0.1:20127"))
NINE_ROUTER_PASS = os.getenv("NINEROUTER_PASS", get_cfg("router", "password", ""))
HEADLESS = bool(get_cfg("general", "headless", True))
TIMEOUT = int(get_cfg("general", "timeout", 30))
