from PySide6.QtCore import Qt, QSignalBlocker
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
    QButtonGroup,
)

from desktop.command_builder import (
    Strategy,
    TradingMode,
    build_run_arguments,
    format_command,
)


from desktop.process_manager import ProcessManager
from desktop.config_manager import ConfigManager
from desktop.settings_dialog import SettingsDialog







class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Kalshi Trading Bot")
        self.setMinimumSize(700, 600)
        self.bot_process = ProcessManager(self)
        self.command_process = ProcessManager(self)
        self.config_manager = ConfigManager()
        self._build_ui()
        self._connect_process_signals()
        self._load_preferences()
        self._connect_preference_signals()

    def _connect_process_signals(self):
        for manager in (self.bot_process, self.command_process):
            manager.output_received.connect(self.log)
            manager.error_received.connect(self._log_error)
            manager.process_error.connect(self._on_process_error)

        self.bot_process.process_started.connect(self._on_process_started)
        self.bot_process.process_finished.connect(self._on_process_finished)
        self.command_process.process_started.connect(self._on_command_started)
        self.command_process.process_finished.connect(self._on_command_finished)

    def _connect_preference_signals(self):
        self.strategy_combo.currentIndexChanged.connect(self._save_preferences)
        self.demo_radio.toggled.connect(self._save_preferences)
        self.production_radio.toggled.connect(self._save_preferences)
        self.paper_radio.toggled.connect(self._save_preferences)
        self.live_radio.toggled.connect(self._save_preferences)

    def _on_command_started(self):
        self.health_button.setEnabled(False)
        self.status_button.setEnabled(False)
        self.log("Command started.")

    def _on_command_finished(self, exit_code: int):
        self.health_button.setEnabled(True)
        self.status_button.setEnabled(True)
        self.log(f"Command finished with exit code {exit_code}.")

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
        self.trading_mode_group = QButtonGroup(self)
        self.trading_mode_group.setExclusive(True)

        self.trading_mode_group.addButton(self.paper_radio)
        self.trading_mode_group.addButton(self.live_radio)

        mode_layout.addWidget(self.paper_radio)
        mode_layout.addWidget(self.live_radio)

        layout.addLayout(mode_layout)


        environment_label = QLabel("Kalshi Environment")
        layout.addWidget(environment_label)

        environment_layout = QHBoxLayout()

        self.demo_radio = QRadioButton("Demo")
        self.production_radio = QRadioButton("Production")

        self.demo_radio.setChecked(True)

        self.environment_group = QButtonGroup(self)
        self.environment_group.setExclusive(True)

        self.environment_group.addButton(self.demo_radio)
        self.environment_group.addButton(self.production_radio)

        environment_layout.addWidget(
            self.demo_radio
        )

        environment_layout.addWidget(
            self.production_radio
        )

        layout.addLayout(
            environment_layout
        )


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

        # Settings
        self.settings_button = QPushButton(
            "Settings"
        )

        layout.addWidget(
            self.settings_button
        )
        self.settings_button.clicked.connect(
            self._open_settings
        )

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


    def _build_process_environment(self,) -> dict[str, str]:

        environment = {}
        if self.demo_radio.isChecked():
            environment["KALSHI_ENV"] = "demo"
        else:
            environment["KALSHI_ENV"] = "prod"
        private_key_path = (
            self.config_manager
            .get_private_key_path()
        )


        kalshi_key = (
            self.config_manager
            .get_kalshi_api_key()
        )

        openrouter_key = (
            self.config_manager
            .get_openrouter_api_key()
        )

        if private_key_path:
                    environment[
                        "KALSHI_PRIVATE_KEY_PATH"
                    ] = str(private_key_path)

        if kalshi_key:
            environment[
                "KALSHI_API_KEY"
            ] = kalshi_key

        if openrouter_key:
            environment[
                "OPENROUTER_API_KEY"
            ] = openrouter_key

        # Force UTF-8 for child Python process
        environment[
            "PYTHONUTF8"
        ] = "1"

        environment[
            "PYTHONIOENCODING"
        ] = "utf-8"

        return environment

    def _open_settings(self):
        dialog = SettingsDialog(
            self.config_manager,
            self,
        )

        dialog.exec()

    def _on_status_clicked(self):
        self.log("")
        self.log("Checking portfolio status...")

        self.command_process.start_cli(
            ["status"],
            environment=self._build_process_environment(),
        )

    def _on_health_clicked(self):
        self.log("")
        self.log("Running health check...")

        self.command_process.start_cli(["health"], 
            environment=self._build_process_environment(),
        )

    def _on_start_clicked(self):
        strategy = self._selected_strategy()
        mode = self._selected_mode()

        # Live trading remains disabled during development.
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
                "Live start blocked during development."
            )
            return

        # Build CLI arguments first.
        args = build_run_arguments(
            strategy,
            mode,
        )

        # Build environment containing credentials + UTF-8 settings.
        environment = self._build_process_environment()

        self.log("")
        self.log(
            f"Starting {strategy.value}..."
        )
        self.log(
            f"Mode: {mode.value}"
        )
        self.log(
            f"Command: {format_command(args)}"
        )

        # Start the process only once.
        self.bot_process.start_cli(
            args, environment=environment,
        )

    def _on_stop_clicked(self):
        if not self.bot_process.is_running():
            self.log(
                "No process is currently running."
            )
            return
        self.bot_process.stop()

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


    def _load_preferences(self):
        preferences = self.config_manager.load_preferences()

        environment = preferences.get("environment", "demo")

        if environment == "prod":
            self.production_radio.setChecked(True)
        else:
            self.demo_radio.setChecked(True)

        trading_mode = preferences.get("trading_mode", "Paper")

        if trading_mode == "Live":
            self.live_radio.blockSignals(True)
            self.live_radio.setChecked(True)
            self.live_radio.blockSignals(False)
        else:
            self.paper_radio.setChecked(True)

        strategy = preferences.get("strategy", "AI Directional")

        index = self.strategy_combo.findData(strategy)

        if index >= 0:
            self.strategy_combo.setCurrentIndex(index)

    def _save_preferences(self, *args):
        preferences = {
            "environment": "demo" if self.demo_radio.isChecked() else "prod",
            "trading_mode": self._selected_mode().value,
            "strategy": self._selected_strategy().value,
        }
        self.config_manager.save_preferences(preferences)

    def closeEvent(self, event):
        if self.bot_process.is_running():
            QMessageBox.warning(
                self, "Bot Running",
                "Stop the trading bot before closing the application.",
            )
            event.ignore()
            return
        if self.command_process.is_running():
            QMessageBox.warning(
                self, "Command Running",
                "Wait for the current command to finish before closing.",
            )
            event.ignore()
            return
        event.accept()
