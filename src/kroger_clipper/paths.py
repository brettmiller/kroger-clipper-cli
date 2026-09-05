import os
from pathlib import Path

APP = "kroger-clipper"


def _xdg(var: str, fallback: str) -> Path:
    root = os.environ.get(var) or Path.home() / fallback
    return Path(root) / APP


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config")


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state")


def session_file() -> Path:
    return state_dir() / "session.json"


def browser_dir() -> Path:
    return state_dir() / "browser"
