import logging
import os
import sys
from pathlib import Path

_DEFAULT_LOG_ROOT = Path(__file__).parents[2] / "logs"
_LOG_ROOT = Path(os.environ.get("LOG_DIR", _DEFAULT_LOG_ROOT))


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


_LOG_TO_FILE = _env_flag("LOG_TO_FILE", default=True)

_CONSOLE_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

_FORMATTER = logging.Formatter(
    "[%(asctime)s] [%(module)s] [%(levelname)s] %(message)s",
    "%Y-%m-%d %H:%M:%S",
)

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(_CONSOLE_LEVEL)
    console_handler.setFormatter(_FORMATTER)
    root_logger.addHandler(console_handler)

    if _LOG_TO_FILE:
        _LOG_ROOT.mkdir(parents=True, exist_ok=True)

        debug_handler = logging.FileHandler(_LOG_ROOT / "debug.log", encoding="utf-8")
        debug_handler.setLevel(logging.DEBUG)
        debug_handler.setFormatter(_FORMATTER)

        info_handler = logging.FileHandler(_LOG_ROOT / "info.log", encoding="utf-8")
        info_handler.setLevel(logging.INFO)
        info_handler.setFormatter(_FORMATTER)

        error_handler = logging.FileHandler(_LOG_ROOT / "error.log", encoding="utf-8")
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(_FORMATTER)

        root_logger.addHandler(debug_handler)
        root_logger.addHandler(info_handler)
        root_logger.addHandler(error_handler)

    _configured = True
