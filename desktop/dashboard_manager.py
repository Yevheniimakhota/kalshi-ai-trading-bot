"""Run the existing Streamlit dashboard as a directly managed child process."""

from pathlib import Path
import sys
import urllib.request
import urllib.error

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal


class DashboardManager(QObject):
    output_received = Signal(str)
    error_received = Signal(str)
    dashboard_ready = Signal(str)
    dashboard_finished = Signal(int)

    URL = "http://127.0.0.1:8501"
    HEALTH_URL = URL + "/_stcore/health"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self._stop_requested = False
        self._checks = 0
        self._ready = False
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._check_ready)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.errorOccurred.connect(self._on_error)
        self.process.finished.connect(self._on_finished)

    def is_running(self) -> bool:
        return self.process.state() != QProcess.NotRunning

    @classmethod
    def _is_ready(cls) -> bool:
        try:
            with urllib.request.urlopen(cls.HEALTH_URL, timeout=0.25) as response:
                return response.status == 200
        except (OSError, urllib.error.URLError):
            return False

    def start(self, environment: dict[str, str] | None = None) -> bool:
        if self.is_running():
            if self._ready:
                self.dashboard_ready.emit(self.URL)
            else:
                self.output_received.emit("Dashboard is still starting...")
            return False

        # Do not accidentally open a dashboard belonging to another process.
        if self._is_ready():
            self.error_received.emit(
                "Port 8501 is already serving a Streamlit dashboard. "
                "Stop that server before launching this dashboard."
            )
            return False

        frozen = getattr(sys, "frozen", False)
        project_root = (Path(sys.executable).resolve().parent if frozen
                        else Path(__file__).resolve().parent.parent)
        bundle_root = (Path(sys._MEIPASS) if frozen else project_root)
        script = bundle_root / "scripts" / "trading_dashboard.py"
        if not script.is_file():
            self.error_received.emit(f"Dashboard script not found: {script}")
            return False

        self._stop_requested = False
        self._ready = False
        self._checks = 0
        self.process.setWorkingDirectory(str(project_root))
        process_env = QProcessEnvironment.systemEnvironment()
        process_env.insert("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "false")
        for name in ("KALSHI_API_KEY", "KALSHI_PRIVATE_KEY_PATH", "OPENROUTER_API_KEY", "KALSHI_API_BASE_URL", "KALSHI_ENV"):
            process_env.remove(name)
        for key, value in (environment or {}).items():
            if value:
                process_env.insert(key, value)
        process_env.insert("PYTHONUTF8", "1")
        process_env.insert("PYTHONIOENCODING", "utf-8")
        self.process.setProcessEnvironment(process_env)
        self.output_received.emit("Starting Streamlit dashboard on localhost:8501...")
        if frozen:
            program = sys.executable
            arguments = ["--internal-dashboard"]
        else:
            program = sys.executable
            arguments = [
                "-m", "streamlit", "run", str(script),
                "--server.address", "127.0.0.1",
                "--server.port", "8501",
                "--server.headless", "true",
                "--browser.gatherUsageStats", "false",
            ]
        self.process.start(program, arguments)
        self._timer.start()
        return True

    def _check_ready(self):
        if not self.is_running():
            self._timer.stop()
            return
        self._checks += 1
        if self._is_ready():
            self._timer.stop()
            self._ready = True
            self.dashboard_ready.emit(self.URL)
        elif self._checks >= 120:
            self._timer.stop()
            self.error_received.emit("Dashboard did not become ready within 60 seconds.")

    def stop(self):
        if not self.is_running():
            return
        self._stop_requested = True
        self._timer.stop()
        self.output_received.emit("Stopping dashboard...")
        self.process.terminate()
        if not self.process.waitForFinished(3000):
            self.process.kill()
            self.process.waitForFinished(2000)

    def _read_stdout(self):
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if data.strip():
            self.output_received.emit(data.rstrip())

    def _read_stderr(self):
        data = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        if data.strip():
            self.error_received.emit(data.rstrip())

    def _on_error(self, _error):
        if not self._stop_requested:
            self.error_received.emit(self.process.errorString())

    def _on_finished(self, exit_code, _status):
        self._timer.stop()
        self._ready = False
        self.dashboard_finished.emit(exit_code)
        self._stop_requested = False
