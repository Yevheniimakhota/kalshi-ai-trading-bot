"""Dedicated desktop window hosting the local Streamlit dashboard."""
from PySide6.QtCore import QUrl, Signal
from PySide6.QtWidgets import QMainWindow
from PySide6.QtWebEngineWidgets import QWebEngineView
from pathlib import Path

from PySide6.QtWidgets import QFileDialog

class DashboardWindow(QMainWindow):
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Kalshi Trading Dashboard")
        self.resize(1100, 800)
        self.browser = QWebEngineView(self)
        self.browser.page().profile().downloadRequested.connect(
            self._handle_download
        )
        self.setCentralWidget(self.browser)


    def _handle_download(self, download):
        default_name = download.downloadFileName()

        default_path = str(
            Path.home() / "Downloads" / default_name
        )

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Trade History",
            default_path,
            "CSV Files (*.csv);;All Files (*)"
        )

        if path:
            selected = Path(path)

            download.setDownloadDirectory(str(selected.parent))
            download.setDownloadFileName(selected.name)
            download.accept()
        else:
            download.cancel()


    def open_dashboard(self, url: str):
        self.browser.setUrl(QUrl(url))
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        super().closeEvent(event)
        if event.isAccepted():
            self.closed.emit()
