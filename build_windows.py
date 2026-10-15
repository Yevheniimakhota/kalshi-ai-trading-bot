
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

command = [
    sys.executable,
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onedir",
    "--windowed",
    "--name", "KalshiTradingBot",

    # Main application
    "--paths", str(ROOT),

    # Streamlit runtime and dependencies
    "--collect-all", "streamlit",
    "--collect-all", "altair",
    "--collect-all", "plotly",

    # Qt WebEngine resources
    "--collect-all", "PySide6.QtWebEngineCore",
    "--collect-all", "PySide6.QtWebEngineWidgets",

    # Project modules
    "--collect-submodules", "desktop",
    "--collect-submodules", "src",
    "--collect-submodules", "scripts",

    # Include dashboard and project resources
    "--add-data", f"{ROOT / 'scripts'};scripts",

    str(ROOT / "desktop" / "launcher.py"),
]

subprocess.run(command, cwd=ROOT, check=True)
