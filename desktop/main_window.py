from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from desktop.command_builder import (
    Strategy,
    TradingMode,
    build_run_arguments,
    format_command,
)


from desktop.process_manager import ProcessManager



class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Kalshi Trading Bot")
        self.setMinimumSize(700, 600)
        self.process_manager = ProcessManager(self)
        self._build_ui()
        self._connect_process_signals()

    def _connect_process_signals(self):
        self.process_manager.output_received.connect(
            self.log
        )

        self.process_manager.error_received.connect(
            self._log_error
        )

        self.process_manager.process_started.connect(
            self._on_process_started
        )

        self.process_manager.process_finished.connect(
            self._on_process_finished
        )

        self.process_manager.process_error.connect(
            self._on_process_error
        )


    def _build_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setSpacing(15)

        # Title
        title = QLabel("Kalshi Trading Bot")
        title.setAlignment(Qt.AlignCenter)

        font = title.font()
        font.setPointSize(20)
        font.setBold(True)
        title.setFont(font)

        layout.addWidget(title)

        # Status
        self.status_label = QLabel("● Stopped")
        self.status_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(self.status_label)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        layout.addWidget(line)

        # Strategy
        strategy_label = QLabel("Strategy")
        layout.addWidget(strategy_label)

        self.strategy_combo = QComboBox()

        for strategy in Strategy:
            self.strategy_combo.addItem(
                strategy.value,
                strategy.value,
            )

        layout.addWidget(self.strategy_combo)

        # Trading mode
        mode_label = QLabel("Trading Mode")
        layout.addWidget(mode_label)

        mode_layout = QHBoxLayout()

        self.paper_radio = QRadioButton("Paper")
        self.live_radio = QRadioButton("Live")

        self.paper_radio.setChecked(True)

        mode_layout.addWidget(self.paper_radio)
        mode_layout.addWidget(self.live_radio)

        layout.addLayout(mode_layout)

        # Start / Stop
        controls_layout = QHBoxLayout()

        self.start_button = QPushButton("Start Bot")
        self.stop_button = QPushButton("Stop Bot")

        self.stop_button.setEnabled(False)

        controls_layout.addWidget(self.start_button)
        controls_layout.addWidget(self.stop_button)

        layout.addLayout(controls_layout)

        # Secondary controls
        tools_layout = QHBoxLayout()

        self.dashboard_button = QPushButton(
            "Open Dashboard"
        )

        self.status_button = QPushButton(
            "Check Status"
        )

        self.health_button = QPushButton(
            "Check Health"
        )

        tools_layout.addWidget(
            self.dashboard_button
        )

        tools_layout.addWidget(
            self.status_button
        )

        tools_layout.addWidget(
            self.health_button
        )


        layout.addLayout(tools_layout)

        # Logs
        layout.addWidget(QLabel("Logs"))

        self.logs = QTextEdit()
        self.logs.setReadOnly(True)

        layout.addWidget(self.logs)

        # Events
        self.start_button.clicked.connect(
            self._on_start_clicked
        )

        self.stop_button.clicked.connect(
            self._on_stop_clicked
        )

        self.live_radio.toggled.connect(
            self._on_live_toggled
        )

        self.health_button.clicked.connect(
            self._on_health_clicked
        )

        self.status_button.clicked.connect(
            self._on_status_clicked
        )
        
        self.log("Application started.")
        self.log("Ready.")

    def log(self, message: str):
        self.logs.append(message)

    def _selected_strategy(self) -> Strategy:
        return Strategy(self.strategy_combo.currentData())

    def _selected_mode(self) -> TradingMode:
        if self.live_radio.isChecked():
            return TradingMode.LIVE

        return TradingMode.PAPER


    def _on_status_clicked(self):
        self.log("")
        self.log("Checking portfolio status...")

        self.process_manager.start_cli(
            ["status"]
        )

    def _on_health_clicked(self):
        self.log("")
        self.log("Running health check...")

        self.process_manager.start_cli(
            ["health"]
        )

    def _on_start_clicked(self):
        strategy = self._selected_strategy()
        mode = self._selected_mode()

        if mode == TradingMode.LIVE:
            QMessageBox.warning(
                self,
                "Live Trading Disabled",
                (
                    "Live trading is temporarily "
                    "disabled during desktop "
                    "application development.\n\n"
                    "Use Paper mode for testing."
                ),
            )

            self.log(
                "Live start blocked during "
                "development."
            )

            return

        args = build_run_arguments(
            strategy,
            mode,
        )

        self.log("")
        self.log(
            f"Starting {strategy.value}..."
        )

        self.log(
            f"Mode: {mode.value}"
        )

        self.process_manager.start_cli(
            args
        )

    def _on_stop_clicked(self):
        if not self.process_manager.is_running():
            self.log(
                "No process is currently running."
            )
            return

        self.process_manager.stop()
    def _on_live_toggled(self, checked: bool):
        if not checked:
            return

        result = QMessageBox.warning(
            self,
            "Enable Live Trading",
            (
                "Live Trading can place real orders "
                "using your Kalshi account.\n\n"
                "Real money may be used.\n\n"
                "Do you want to enable Live mode?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if result != QMessageBox.Yes:
            self.paper_radio.setChecked(True)

    def _log_error(self, message: str):
        self.log(
            f"[ERROR] {message}"
        )


    def _on_process_started(self):
        self.status_label.setText(
            "● Running"
        )

        self.start_button.setEnabled(
            False
        )

        self.stop_button.setEnabled(
            True
        )

        self.log(
            "Process started."
        )


    def _on_process_finished(
        self,
        exit_code: int,
    ):
        self.status_label.setText(
            "● Stopped"
        )

        self.start_button.setEnabled(
            True
        )

        self.stop_button.setEnabled(
            False
        )

        self.log(
            f"Process finished "
            f"with exit code {exit_code}."
        )


    def _on_process_error(
        self,
        message: str,
    ):
        self.log(
            f"[PROCESS ERROR] {message}"
        )