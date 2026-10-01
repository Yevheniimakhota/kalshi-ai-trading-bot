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