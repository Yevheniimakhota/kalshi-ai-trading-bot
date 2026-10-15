from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QColor
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
    QGraphicsDropShadowEffect,
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
from desktop.styles import MAIN_WINDOW_STYLE
from desktop.dashboard_manager import DashboardManager
from desktop.dashboard_window import DashboardWindow
from desktop.runtime_state import write_runtime_state
from desktop.paths import get_user_data_dir



def _panel() -> tuple[QFrame, QVBoxLayout]:
    panel = QFrame()
    panel.setObjectName("panel")
    panel_layout = QVBoxLayout(panel)
    panel_layout.setContentsMargins(22, 19, 22, 20)
    panel_layout.setSpacing(11)
    return panel, panel_layout


def _label(text: str, object_name: str = "fieldLabel") -> QLabel:
    label = QLabel(text)
    label.setObjectName(object_name)
    return label


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Kalshi Trading Bot")
        self.setMinimumSize(760, 700)
        self.resize(850, 810)
        self.setStyleSheet(MAIN_WINDOW_STYLE)
        self.bot_process = ProcessManager(self)
        self.command_process = ProcessManager(self)
        self.dashboard_manager = DashboardManager(self)
        self.dashboard_window = DashboardWindow(self)
        self.dashboard_window.closed.connect(self._on_dashboard_window_closed)
        self.config_manager = ConfigManager()
        self.runtime_state_path = get_user_data_dir() / "runtime_state.json"
        self._active_bot = None
        self._publish_runtime_state(False)
        self._build_ui()
        self._connect_process_signals()
        self._load_preferences()
        self._publish_runtime_state(False)
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
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(26, 22, 26, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header_text = QVBoxLayout()
        header_text.setSpacing(3)
        title = _label("Kalshi Trading Bot", "appTitle")
        subtitle = _label("Desktop trading control center", "subtitle")
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        header.addLayout(header_text)
        header.addStretch()
        self.status_label = _label("● Stopped", "statusStopped")
        self.status_label.setAlignment(Qt.AlignCenter)
        header.addWidget(self.status_label)
        layout.addLayout(header)

        config_panel, config_layout = _panel()
        config_layout.addWidget(_label("Trading configuration", "sectionTitle"))
        config_layout.addSpacing(5)
        config_layout.addWidget(_label("Strategy"))
        self.strategy_combo = QComboBox()
        for strategy in Strategy:
            self.strategy_combo.addItem(strategy.value, strategy.value)
        config_layout.addWidget(self.strategy_combo)

        choices = QHBoxLayout()
        choices.setSpacing(24)
        trading_col = QVBoxLayout()
        trading_col.setSpacing(6)
        trading_col.addWidget(_label("Trading mode"))
        trading_row = QHBoxLayout()
        self.paper_radio = QRadioButton("Paper")
        self.live_radio = QRadioButton("Live")
        self.paper_radio.setChecked(True)
        self.trading_mode_group = QButtonGroup(self)
        self.trading_mode_group.setExclusive(True)
        self.trading_mode_group.addButton(self.paper_radio)
        self.trading_mode_group.addButton(self.live_radio)
        trading_row.addWidget(self.paper_radio)
        trading_row.addWidget(self.live_radio)
        trading_row.addStretch()
        trading_col.addLayout(trading_row)
        choices.addLayout(trading_col, 1)

        environment_col = QVBoxLayout()
        environment_col.setSpacing(6)
        environment_col.addWidget(_label("Kalshi environment"))
        environment_row = QHBoxLayout()
        self.demo_radio = QRadioButton("Demo")
        self.production_radio = QRadioButton("Production")
        self.demo_radio.setChecked(True)
        self.environment_group = QButtonGroup(self)
        self.environment_group.setExclusive(True)
        self.environment_group.addButton(self.demo_radio)
        self.environment_group.addButton(self.production_radio)
        environment_row.addWidget(self.demo_radio)
        environment_row.addWidget(self.production_radio)
        environment_row.addStretch()
        environment_col.addLayout(environment_row)
        choices.addLayout(environment_col, 1)
        config_layout.addLayout(choices)
        layout.addWidget(config_panel)

        action_panel, action_layout = _panel()
        action_layout.addWidget(_label("Bot controls", "sectionTitle"))
        controls = QHBoxLayout()
        controls.setSpacing(12)
        self.start_button = QPushButton("▶  Start Bot")
        self.start_button.setObjectName("primaryButton")
        self.stop_button = QPushButton("■  Stop Bot")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.setEnabled(False)
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        action_layout.addLayout(controls)
        action_layout.addSpacing(4)
        tools = QHBoxLayout()
        tools.setSpacing(10)
        self.dashboard_button = QPushButton("◫  Open Dashboard")
        self.status_button = QPushButton("◉  Check Status")
        self.health_button = QPushButton("✓  Check Health")
        tools.addWidget(self.dashboard_button)
        tools.addWidget(self.status_button)
        tools.addWidget(self.health_button)
        self.dashboard_button.clicked.connect(self._on_dashboard_clicked)
        action_layout.addLayout(tools)
        self.settings_button = QPushButton("⚙  Settings")
        action_layout.addWidget(self.settings_button)
        layout.addWidget(action_panel)

        log_panel, log_layout = _panel()
        log_header = QHBoxLayout()
        log_header.addWidget(_label("Activity logs", "sectionTitle"))
        log_header.addStretch()
        self.clear_logs_button = QPushButton("Clear logs")
        self.clear_logs_button.setFixedWidth(110)
        log_header.addWidget(self.clear_logs_button)
        log_layout.addLayout(log_header)
        self.logs = QTextEdit()
        self.logs.setObjectName("logsView")
        self.logs.setReadOnly(True)
        log_layout.addWidget(self.logs, 1)
        layout.addWidget(log_panel, 1)

        self.start_button.clicked.connect(self._on_start_clicked)
        self.stop_button.clicked.connect(self._on_stop_clicked)
        self.live_radio.toggled.connect(self._on_live_toggled)
        self.production_radio.toggled.connect(self._on_environment_toggled)
        self.health_button.clicked.connect(self._on_health_clicked)
        self.status_button.clicked.connect(self._on_status_clicked)
        self.settings_button.clicked.connect(self._open_settings)
        self.clear_logs_button.clicked.connect(self.logs.clear)


        self.dashboard_manager.output_received.connect(self.log)
        self.dashboard_manager.dashboard_ready.connect(
            self._on_dashboard_ready
        )

        self.dashboard_manager.dashboard_finished.connect(
            self._on_dashboard_finished
        )

        self.dashboard_manager.error_received.connect(
            self._on_dashboard_error
        )
        # The dashboard button intentionally retains its existing behavior:
        # it is not connected to a new process until DashboardManager is added.
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



    def _on_dashboard_clicked(self):
        if self.dashboard_manager.is_running():
            self.dashboard_button.setEnabled(False)
            self.dashboard_button.setText("◌  Stopping Dashboard...")
            self.dashboard_manager.stop()
        else:
            self.dashboard_button.setEnabled(False)
            self.dashboard_button.setText("◌  Starting Dashboard...")

            self.dashboard_manager.start(
                environment={**self._build_process_environment(),
                             "KALSHI_RUNTIME_STATE_PATH": str(self.runtime_state_path)}
            )


    def _on_dashboard_ready(self, url: str):
        self.dashboard_button.setText("■  Stop Dashboard")
        self.dashboard_button.setEnabled(True)
        self.log(f"Dashboard ready: {url}")
        self.dashboard_window.open_dashboard(url)


    def _on_dashboard_window_closed(self):
        """Stop Streamlit when the dashboard is closed with the window X."""
        if self.dashboard_manager.is_running():
            self.dashboard_button.setEnabled(False)
            self.dashboard_button.setText("◌  Stopping Dashboard...")
            self.dashboard_manager.stop()
        else:
            self.dashboard_button.setText("◫  Start Dashboard")
            self.dashboard_button.setEnabled(True)

    def _on_dashboard_finished(self, exit_code: int):
        self.dashboard_button.setText("◫  Start Dashboard")
        self.dashboard_button.setEnabled(True)
        self.log(f"Dashboard stopped (exit code: {exit_code}).")
        self.dashboard_window.hide()


    def _on_dashboard_error(self, message: str):
        self.log(f"[DASHBOARD ERROR] {message}")

        if not self.dashboard_manager.is_running():
            self.dashboard_button.setText("◫  Start Dashboard")
            self.dashboard_button.setEnabled(True)
    
    def _build_process_environment(self) -> dict[str, str]:
        """Build environment variables for the selected Kalshi environment."""

        # Determine the selected Kalshi environment
        environment_name = (
            "demo" if self.demo_radio.isChecked() else "prod"
        )

        # Load credentials for the selected environment
        kalshi_key = self.config_manager.get_kalshi_api_key(
            environment_name
        )

        private_key_path = self.config_manager.get_private_key_path(
            environment_name
        )

        # OpenRouter API key is shared between environments
        openrouter_key = self.config_manager.get_openrouter_api_key()

        # Build child process environment
        environment = {
            "KALSHI_ENV": environment_name,
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }

        if kalshi_key:
            environment["KALSHI_API_KEY"] = kalshi_key

        if private_key_path:
            environment["KALSHI_PRIVATE_KEY_PATH"] = str(
                private_key_path
            )

        if openrouter_key:
            environment["OPENROUTER_API_KEY"] = openrouter_key

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

        selected_env = "demo" if self.demo_radio.isChecked() else "prod"
        if self.bot_process.is_running():
            self.log("Bot is already running.")
            return

        # Production + Live is deliberately locked until separately reviewed.
        if mode == TradingMode.LIVE and selected_env != "demo":
            QMessageBox.warning(self, "Production Live Disabled",
                "Live trading with real funds is disabled.\n"
                "Choose Demo environment to test Live order submission.")
            return

        if mode == TradingMode.LIVE:
            answer = QMessageBox.warning(self, "Confirm Demo Live Trading",
                "This sends actual orders to the Kalshi DEMO API.\n"
                "Demo funds only; orders may be filled.\n\n"
                "Continue?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return

        # Build CLI arguments first.
        args = build_run_arguments(
            strategy,
            mode,
        )

        # Build environment containing credentials + UTF-8 settings.
        environment = self._build_process_environment()

        if mode == TradingMode.LIVE:
            if not environment.get("KALSHI_API_KEY") or not environment.get("KALSHI_PRIVATE_KEY_PATH"):
                QMessageBox.warning(self, "Missing Demo Credentials",
                    "Configure Demo API Key and Demo private key in Settings first.")
                return

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
        started = self.bot_process.start_cli(args, environment=environment)
        if started:
            self._active_bot = {"environment": selected_env,
                                "mode": mode.value, "strategy": strategy.value}
            self._publish_runtime_state(True)

    def _on_stop_clicked(self):
        if not self.bot_process.is_running():
            self.log(
                "No process is currently running."
            )
            return
        self.bot_process.stop()

    def _on_environment_toggled(self, checked: bool):
        if checked and self.live_radio.isChecked():
            QMessageBox.information(self, "Production Safety",
                "Production Live is locked. Switching to Paper mode.")
            self.paper_radio.setChecked(True)

    def _on_live_toggled(self, checked: bool):
        if not checked:
            return

        if self.production_radio.isChecked():
            QMessageBox.warning(self, "Production Live Disabled",
                "Production Live is not enabled. Use Demo + Live for testing.")
            self.paper_radio.setChecked(True)
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


    def _publish_runtime_state(self, running: bool):
        active = self._active_bot or {}
        write_runtime_state(self.runtime_state_path, running=running,
            environment=active.get("environment", "demo" if self.demo_radio.isChecked() else "prod") if hasattr(self, "demo_radio") else "demo",
            mode=active.get("mode", self._selected_mode().value) if hasattr(self, "paper_radio") else "Paper",
            strategy=active.get("strategy", self._selected_strategy().value) if hasattr(self, "strategy_combo") else "AI Directional")

    def _on_process_started(self):
        self.status_label.setText(
            "● Running"
        )
        self.status_label.setObjectName("statusRunning")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

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
        self._publish_runtime_state(False)
        self._active_bot = None
        self.status_label.setText(
            "● Stopped"
        )
        self.status_label.setObjectName("statusStopped")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

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
        if self.dashboard_manager.is_running():
            self.dashboard_manager.stop()
        event.accept()
