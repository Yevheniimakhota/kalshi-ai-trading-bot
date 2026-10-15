"""Entry point for GUI and bundled child processes."""
import multiprocessing
import os
import sys
from pathlib import Path


os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(
            encoding="utf-8",
            errors="replace"
        )
        

# Must be set before importing Qt WebEngine/PySide6.
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--disable-gpu --disable-gpu-compositing --disable-features=Vulkan",
)


def run_internal_command():
    if len(sys.argv) < 2:
        return False
    configure_output_encoding()
    mode = sys.argv[1]
    if mode == "--internal-cli":
        from cli import main as cli_main
        sys.argv = ["cli.py", *sys.argv[2:]]
        result = cli_main()
        if isinstance(result, int):
            raise SystemExit(result)
        return True

    if mode == "--internal-dashboard":
        from streamlit.web import cli as stcli
        base = (Path(sys._MEIPASS) if getattr(sys, "frozen", False)
                else Path(__file__).resolve().parent.parent)
        dashboard = base / "scripts" / "trading_dashboard.py"
        if not dashboard.is_file():
            raise FileNotFoundError(f"Bundled dashboard missing: {dashboard}")
        sys.argv = [
            "streamlit", "run", str(dashboard),
            "--server.address=127.0.0.1",
            "--server.port=8501",
            "--server.headless=true",
            "--browser.gatherUsageStats=false",
            "--global.developmentMode=false",
        ]
        stcli.main()
        return True

    return False


def configure_output_encoding():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)

        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(
                    encoding="utf-8",
                    errors="replace"
                )
            except (OSError, ValueError):
                pass


def main():
    from PySide6.QtWidgets import QApplication
    from desktop.main_window import MainWindow
    app = QApplication(sys.argv)
    app.setApplicationName("Kalshi Trading Bot")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if not run_internal_command():
        sys.exit(main())
