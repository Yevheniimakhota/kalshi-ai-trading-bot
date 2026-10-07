from pathlib import Path
import sys

from PySide6.QtCore import (
    QObject,
    QProcess,
    QProcessEnvironment,
    Signal,
)


class ProcessManager(QObject):
    output_received = Signal(str)
    error_received = Signal(str)

    process_started = Signal()
    process_finished = Signal(int)
    process_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.process = QProcess(self)
        self._stop_requested = False
        self.process.readyReadStandardOutput.connect(
            self._read_stdout
        )

        self.process.readyReadStandardError.connect(
            self._read_stderr
        )

        self.process.started.connect(
            self.process_started.emit
        )

        self.process.finished.connect(
            self._on_finished
        )

        self.process.errorOccurred.connect(
            self._on_error
        )

    def start_cli(self, arguments: list[str], environment: dict[str, str] | None = None,) -> bool:
        self._stop_requested = False
        if self.is_running():
            self.error_received.emit(
                "A process is already running."
            )
            return False

        project_root = (
            Path(__file__)
            .resolve()
            .parent
            .parent
        )

        cli_path = project_root / "cli.py"

        self.process.setWorkingDirectory(
            str(project_root)
        )

        program = sys.executable

        process_arguments = [
            str(cli_path),
            *arguments,
        ]

        self.output_received.emit(
            f"$ {program} {cli_path.name} "
            + " ".join(arguments)
        )
        process_env = (
            QProcessEnvironment.systemEnvironment()
        )

        if environment:
            for key, value in environment.items():
                if value:
                    process_env.insert(
                        key,
                        value,
                    )

        self.process.setProcessEnvironment(
            process_env
)
        self.process.start(
            program,
            process_arguments,
        )

        return True

    def stop(self):
        if not self.is_running():
            return

        self._stop_requested = True

        self.output_received.emit(
            "Stopping process..."
        )

        self.process.terminate()

        if not self.process.waitForFinished(3000):
            self.output_received.emit(
                "Process did not stop gracefully. "
                "Forcing shutdown..."
            )
            self.process.kill()

    def is_running(self) -> bool:
        return (
            self.process.state()
            != QProcess.NotRunning
        )

    def _read_stdout(self):
        data = (
            self.process
            .readAllStandardOutput()
            .data()
            .decode(
                "utf-8",
                errors="replace",
            )
        )

        if data:
            self.output_received.emit(
                data.rstrip()
            )

    def _read_stderr(self):
        data = (
            self.process
            .readAllStandardError()
            .data()
            .decode(
                "utf-8",
                errors="replace",
            )
        )

        if data:
            self.error_received.emit(
                data.rstrip()
            )

    def _on_finished(self,exit_code: int,exit_status,):
        if self._stop_requested:
            self.output_received.emit(
                "Process stopped by user."
            )

        self.process_finished.emit(
            exit_code
        )

        self._stop_requested = False

    def _on_error(self, error):
        if self._stop_requested:
            return

        self.process_error.emit(
            self.process.errorString()
    )