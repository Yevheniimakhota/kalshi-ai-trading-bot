import json
from pathlib import Path

import keyring

from desktop.paths import get_user_data_dir


SERVICE_NAME = "KalshiTradingBot"

KALSHI_API_KEY = "kalshi_api_key"
OPENROUTER_API_KEY = "openrouter_api_key"


class ConfigManager:
    def __init__(self):
        self.data_dir = get_user_data_dir()

        self.config_path = (
            self.data_dir / "config.json"
        )

    # -------------------------
    # Secret credentials
    # -------------------------

    def set_kalshi_api_key(
        self,
        value: str,
    ):
        keyring.set_password(
            SERVICE_NAME,
            KALSHI_API_KEY,
            value,
        )

    def get_kalshi_api_key(self) -> str | None:
        return keyring.get_password(
            SERVICE_NAME,
            KALSHI_API_KEY,
        )

    def set_openrouter_api_key(
        self,
        value: str,
    ):
        keyring.set_password(
            SERVICE_NAME,
            OPENROUTER_API_KEY,
            value,
        )

    def get_openrouter_api_key(
        self,
    ) -> str | None:
        return keyring.get_password(
            SERVICE_NAME,
            OPENROUTER_API_KEY,
        )

    # -------------------------
    # Normal application config
    # -------------------------

    def load_config(self) -> dict:
        if not self.config_path.exists():
            return {}

        try:
            with self.config_path.open(
                "r",
                encoding="utf-8",
            ) as file:
                return json.load(file)

        except (
            json.JSONDecodeError,
            OSError,
        ):
            return {}

    def save_config(
        self,
        config: dict,
    ):
        with self.config_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                config,
                file,
                indent=4,
            )