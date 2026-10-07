from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QFileDialog
)


from pathlib import Path
import shutil

from desktop.config_manager import ConfigManager


class SettingsDialog(QDialog):
    def __init__(
        self,
        config_manager: ConfigManager,
        parent=None,
    ):
        super().__init__(parent)

        self.config_manager = config_manager

        self.setWindowTitle(
            "Configuration"
        )

        self.setMinimumWidth(500)

        self._build_ui()
        self._load_existing_values()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel(
            "API Configuration"
        )

        font = title.font()
        font.setPointSize(16)
        font.setBold(True)

        title.setFont(font)

        layout.addWidget(title)

        form = QFormLayout()

        # Kalshi
        self.kalshi_key_input = QLineEdit()

        self.kalshi_key_input.setEchoMode(
            QLineEdit.Password
        )

        self.kalshi_key_input.setPlaceholderText(
            "Kalshi API Key"
        )

        form.addRow(
            "Kalshi API Key:",
            self.kalshi_key_input,
        )

        # OpenRouter
        self.openrouter_key_input = QLineEdit()

        self.openrouter_key_input.setEchoMode(
            QLineEdit.Password
        )

        self.openrouter_key_input.setPlaceholderText(
            "OpenRouter API Key"
        )

        form.addRow(
            "OpenRouter API Key:",
            self.openrouter_key_input,
        )

        layout.addLayout(form)

        self.private_key_input = QLineEdit()
        self.private_key_input.setReadOnly(True)
        self.private_key_input.setPlaceholderText(
            "No private key selected"
        )

        self.private_key_button = QPushButton(
            "Select .pem"
        )

        private_key_layout = QHBoxLayout()

        private_key_layout.addWidget(
            self.private_key_input
        )

        private_key_layout.addWidget(
            self.private_key_button
        )

        form.addRow(
            "Kalshi Private Key:",
            private_key_layout,
        )

        self.private_key_button.clicked.connect(
            self._select_private_key
        )

        
        
        # Buttons
        buttons = QHBoxLayout()

        self.save_button = QPushButton(
            "Save"
        )

        self.cancel_button = QPushButton(
            "Cancel"
        )

        buttons.addStretch()

        buttons.addWidget(
            self.save_button
        )

        buttons.addWidget(
            self.cancel_button
        )

        layout.addLayout(buttons)

        self.save_button.clicked.connect(
            self._save
        )

        self.cancel_button.clicked.connect(
            self.reject
        )

    def _select_private_key(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Kalshi Private Key",
            "",
            "PEM files (*.pem);;All files (*)",
        )

        if not file_path:
            return

        try:
            saved_path = (
                self.config_manager
                .import_private_key(file_path)
            )

            self.private_key_input.setText(
                str(saved_path)
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Private Key Error",
                str(exc),
            )

    def _load_existing_values(self):
        kalshi_key = (
            self.config_manager
            .get_kalshi_api_key()
        )

        openrouter_key = (
            self.config_manager
            .get_openrouter_api_key()
        )
        private_key_path = (
            self.config_manager
            .get_private_key_path()
        )

        if private_key_path:
            self.private_key_input.setText(
                str(private_key_path)
            )

        if kalshi_key:
            self.kalshi_key_input.setText(
                kalshi_key
            )

        if openrouter_key:
            self.openrouter_key_input.setText(
                openrouter_key
            )

    def _save(self):
        kalshi_key = (
            self.kalshi_key_input
            .text()
            .strip()
        )

        openrouter_key = (
            self.openrouter_key_input
            .text()
            .strip()
        )

        if kalshi_key:
            self.config_manager.set_kalshi_api_key(
                kalshi_key
            )

        if openrouter_key:
            self.config_manager.set_openrouter_api_key(
                openrouter_key
            )

        QMessageBox.information(
            self,
            "Saved",
            "Configuration saved successfully.",
        )

        self.accept()