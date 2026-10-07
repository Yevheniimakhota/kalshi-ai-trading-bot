import json
from pathlib import Path
import shutil

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
        self.private_key_path = (
            self.data_dir
            / "kalshi_private_key.pem"
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

    def import_private_key( self,source_path: str | Path,) -> Path:
        source = Path(source_path)

        if not source.exists():
            raise FileNotFoundError(
                f"Private key not found: {source}"
            )

        if not source.is_file():
            raise ValueError(
                "Selected private key is not a file."
            )

        if source.suffix.lower() != ".pem":
            raise ValueError(
                "Kalshi private key must be a .pem file."
            )

        shutil.copy2(
            source,
            self.private_key_path,
        )

        return self.private_key_path


    def get_private_key_path(self,) -> Path | None:

        if self.private_key_path.exists():
            return self.private_key_path

        return None

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