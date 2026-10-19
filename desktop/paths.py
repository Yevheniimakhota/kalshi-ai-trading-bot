from pathlib import Path
import os
import sys


APP_NAME = "KalshiBot"


def get_user_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(
            os.getenv(
                "APPDATA",
                Path.home() / "AppData" / "Roaming",
            )
        )
        path = base / APP_NAME

    elif sys.platform == "darwin":
        path = (
            Path.home()
            / "Library"
            / "Application Support"
            / APP_NAME
        )

    else:
        path = (
            Path.home()
            / ".local"
            / "share"
            / APP_NAME
        )

    path.mkdir(
        parents=True,
        exist_ok=True,
    )

    return path

def get_trading_db_path(environment: str | None = None) -> Path:
    """Persistent, environment-specific database. Never store it in _internal."""
    env = (environment or os.getenv("KALSHI_ENV", "prod")).strip().lower()
    if env not in ("demo", "prod"):
        raise ValueError(f"Invalid KALSHI_ENV: {env!r}")
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / APP_NAME
    else:
        root = get_user_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root / f"trading_system_{env}.db"
