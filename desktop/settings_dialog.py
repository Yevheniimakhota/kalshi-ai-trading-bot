
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QTabWidget,
    QWidget,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QFrame
)

from desktop.styles import SETTINGS_STYLE



class SettingsDialog(QDialog):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)

        self.config_manager = config_manager
        self.selected_files = {}

        self.setWindowTitle("Kalshi API Settings")
        self.resize(660, 440)
        self.setMinimumSize(650, 420)
        self.setStyleSheet(SETTINGS_STYLE)
        self._build_ui()
        self._load_settings()

    def _build_ui(self):

        
        layout = QVBoxLayout(self)
        header = QLabel("Kalshi API Settings")
        header.setStyleSheet("""
            font-size: 19px;
            font-weight: 700;
            color: #111827;
        """)

        layout.addWidget(header)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)
        separator = QFrame()
        separator.setObjectName("separator")
        separator.setFrameShape(QFrame.HLine)

        layout.addWidget(separator)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(True)
        self.environment_fields = {}

        for environment, title in (
            ("demo", "Demo Account"),
            ("prod", "Production Account"),
        ):
            page = QWidget()
            form = QFormLayout(page)

            api_input = QLineEdit()
            api_input.setEchoMode(QLineEdit.Password)
            api_input.setPlaceholderText("Enter Kalshi API Key ID")
            api_input.setMinimumHeight(42)

            key_status = QLabel("Not configured")

            browse_button = QPushButton(
                "Import private key (.pem)"
            )
            browse_button.setMinimumHeight(40)
            browse_button.clicked.connect(
                lambda checked=False, env=environment:
                    self._browse_private_key(env)
            )

            form.addRow("Kalshi API Key:", api_input)
            form.addRow("Private key:", key_status)
            form.addRow("", browse_button)

            self.environment_fields[environment] = {
                "api_input": api_input,
                "key_status": key_status,
            }

            self.tabs.addTab(page, title)

        layout.addWidget(self.tabs)

        shared_label = QLabel(
            "OpenRouter API Key (shared)"
        )
        layout.addWidget(shared_label)

        self.openrouter_input = QLineEdit()
        self.openrouter_input.setMinimumHeight(42)

        self.openrouter_input.setEchoMode(
            QLineEdit.Password
        )
        self.openrouter_input.setPlaceholderText(
            "Enter OpenRouter API Key"
        )
        layout.addWidget(self.openrouter_input)

        buttons = QHBoxLayout()

        save_button = QPushButton("Save Settings")
        save_button.setObjectName("saveButton")
        cancel_button = QPushButton("Cancel")
        cancel_button.setObjectName("cancelButton")

        save_button.clicked.connect(self._save_settings)
        cancel_button.clicked.connect(self.reject)

        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)

        layout.addLayout(buttons)

    def _load_settings(self):
        for environment, fields in (
            self.environment_fields.items()
        ):
            api_key = (
                self.config_manager.get_kalshi_api_key(
                    environment
                )
            )

            if api_key:
                fields["api_input"].setText(api_key)

            private_key = (
                self.config_manager.get_private_key_path(
                    environment
                )
            )

            if private_key:
                fields["key_status"].setText(
                    "✓ Private key configured"
                )

        openrouter_key = (
            self.config_manager.get_openrouter_api_key()
        )

        if openrouter_key:
            self.openrouter_input.setText(
                openrouter_key
            )

    def _browse_private_key(self, environment):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Kalshi Private Key",
            "",
            "PEM Files (*.pem)",
        )

        if not path:
            return

        self.selected_files[environment] = path

        self.environment_fields[
            environment
        ]["key_status"].setText(
            f"Selected: {Path(path).name}"
        )

    def _save_settings(self):
        try:
            for environment, fields in (
                self.environment_fields.items()
            ):
                api_key = (
                    fields["api_input"].text().strip()
                )

                if api_key:
                    self.config_manager.set_kalshi_api_key(
                        api_key,
                        environment,
                    )

                selected_file = self.selected_files.get(
                    environment
                )

                if selected_file:
                    self.config_manager.import_private_key(
                        selected_file,
                        environment,
                    )

            openrouter_key = (
                self.openrouter_input.text().strip()
            )

            if openrouter_key:
                self.config_manager.set_openrouter_api_key(
                    openrouter_key
                )

            QMessageBox.information(
                self,
                "Settings Saved",
                "Credentials saved successfully.",
            )

            self.accept()

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Settings Error",
                str(exc),
            )
