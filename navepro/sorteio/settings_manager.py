import json
import os
from typing import Any

from navepro.core.log import get_logger
from navepro.core.paths import DATA_USER_DIR

from . import APP_VERSION

log = get_logger()

DATA_DIR = os.environ.get("RAFFLE_DATA_DIR") or os.path.join(
    DATA_USER_DIR, "sorteio"
)
CONFIG_DIR = os.path.join(DATA_DIR, "config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")


class SettingsManager:
    _instance = None

    def __new__(cls) -> "SettingsManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._settings: dict[str, Any] = self._load_defaults()
        self._load()

    def _load_defaults(self) -> dict[str, Any]:
        return {
            "animation": {
                "duration": 5.0,
                "initial_speed": 30,
                "slowdown_factor": 1.08,
                "min_speed": 200,
            },
            "appearance": {
                "theme": "dark",
                "primary_color": "#00d4ff",
                "secondary_color": "#ff00ff",
                "font_family": "Orbitron",
                "font_fallback": "Arial",
            },
            "sound": {
                "enabled": True,
                "volume": 0.6,
            },
            "display": {
                "fullscreen": False,
                "monitor_index": 0,
                "public_monitor": 1,
                "public_alpha": 0.65,
                "public_transparent": True,
                "public_bg": "",
                "public_primary": "",
                "public_text": "",
                "public_text_secondary": "",
            },
            "ui": {
                "settings_w": 820,
                "settings_h": 720,
            },
            "history": {
                "auto_export": False,
                "export_format": "csv",
                "save_path": "exports/",
            },
        }

    def _load(self) -> None:
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, encoding="utf-8") as f:
                    loaded = json.load(f)
                    self._deep_merge(self._settings, loaded)
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Config load error: %s. Using defaults.", e)

    def _deep_merge(self, base: dict, override: dict) -> None:
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def save(self) -> None:
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            self._settings["_version"] = APP_VERSION
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
        except OSError as e:
            log.warning("Config save error: %s", e)

    def get(self, *keys: str) -> Any:
        value = self._settings
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value

    def set(self, *args: Any) -> None:
        if len(args) < 2:
            return
        *keys, val = args
        target = self._settings
        for key in keys[:-1]:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
            target = target[key]
        target[keys[-1]] = val
        self.save()

    @property
    def all(self) -> dict[str, Any]:
        return self._settings
