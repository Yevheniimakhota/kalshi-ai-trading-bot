import json
from pathlib import Path
import shutil

import keyring

from desktop.paths import get_user_data_dir


SERVICE_NAME = "KalshiTradingBot"

KALSHI_API_KEY = "kalshi_api_key"
OPENROUTER_API_KEY = "openrouter_api_key"


VALID_ENVIRONMENTS = {"demo", "prod"}


def validate_environment(environment: str) -> str:
    if environment not in VALID_ENVIRONMENTS:
        raise ValueError(
            f"Unsupported Kalshi environment: {environment}"
        )
    return environment




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

    def load_preferences(self) -> dict:
        return self.load_config().get("preferences", {})

    def save_preferences(self, preferences: dict) -> None:
        config = self.load_config()
        config["preferences"] = {**config.get("preferences", {}), **preferences}
        self.save_config(config)

    # -------------------------
    # Secret credentials
    # -------------------------

    def set_kalshi_api_key(self,value: str, environment: str,):
        environment = validate_environment(environment)

        keyring.set_password(
            SERVICE_NAME,
            f"kalshi_api_key_{environment}",
            value,
        )


    def get_kalshi_api_key(self,environment: str,) -> str | None:
        environment = validate_environment(environment)

        return keyring.get_password(
            SERVICE_NAME,
            f"kalshi_api_key_{environment}",
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

    def import_private_key(self,source_path: str | Path,environment: str,) -> Path:
        environment = validate_environment(environment)
        source = Path(source_path).resolve()

        if not source.is_file():
            raise FileNotFoundError(
                f"Private key not found: {source}"
            )

        if source.suffix.lower() != ".pem":
            raise ValueError("Private key must be a .pem file.")

        destination = (
            self.data_dir /
            f"kalshi_private_key_{environment}.pem"
        ).resolve()

        self.data_dir.mkdir(parents=True, exist_ok=True)

        if source != destination:
            shutil.copy2(source, destination)

        return destination


    def get_private_key_path( self, environment: str,  ) -> Path | None:
        environment = validate_environment(environment)

        path = (
            self.data_dir /
            f"kalshi_private_key_{environment}.pem"
        )

        return path if path.is_file() else None

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
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = self.config_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(config, indent=4), encoding="utf-8")
        temporary_path.replace(self.config_path)