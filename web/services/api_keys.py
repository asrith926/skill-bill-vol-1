"""API key storage -- persisted to local config file."""
import json
from pathlib import Path

from skillbill.config import DATA_DIR

DEFAULT_CONFIG_PATH = DATA_DIR / ".config.json"


def load_api_key(config_path: Path = DEFAULT_CONFIG_PATH) -> tuple[str, str]:
    """Load saved API key. Returns (provider, key) or ("", "") if not set."""
    if not config_path.exists():
        return "", ""
    try:
        data = json.loads(config_path.read_text())
        return data.get("provider", ""), data.get("api_key", "")
    except (json.JSONDecodeError, KeyError):
        return "", ""


def save_api_key(
    provider: str,
    api_key: str,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> None:
    """Save API key to local config file."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({
        "provider": provider,
        "api_key": api_key,
    }))


def clear_api_key(config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Remove saved API key."""
    if config_path.exists():
        config_path.unlink()
