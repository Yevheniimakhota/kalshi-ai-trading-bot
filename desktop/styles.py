
SETTINGS_STYLE = """
QDialog {
    background-color: #FAFAFA;
    color: #202124;
    font-family: "Segoe UI";
    font-size: 13px;
}

QLabel {
    color: #555B65;
    background: transparent;
}

QTabWidget::pane {
    border: none;
    background: transparent;
    margin-top: 12px;
}

QTabBar::tab {
    background: #F1F2F4;
    color: #666B75;
    padding: 13px 26px;
    min-width: 145px;
    border: none;
    font-weight: 600;
}

QTabBar::tab:first {
    border-top-left-radius: 12px;
    border-bottom-left-radius: 12px;
}

QTabBar::tab:last {
    border-top-right-radius: 12px;
    border-bottom-right-radius: 12px;
}

QTabBar::tab:selected {
    background: #E5E7EB;
    color: #111827;
}

QLineEdit {
    background: white;
    color: #202124;
    border: 1px solid #E0E3E8;
    border-radius: 18px;
    padding: 9px 15px;
    min-height: 22px;
    selection-background-color: #CBD5E1;
}

QLineEdit:focus {
    border: 1px solid #64748B;
}

QPushButton {
    background: white;
    color: #374151;
    border: 1px solid #E0E3E8;
    border-radius: 17px;
    padding: 9px 18px;
    min-height: 22px;
}

QPushButton:hover {
    background: #F1F5F9;
    border-color: #CBD5E1;
}

QPushButton:pressed {
    background: #E2E8F0;
}

QPushButton#saveButton {
    background: #2563EB;
    color: white;
    border: none;
    font-weight: 600;
}

QPushButton#saveButton:hover {
    background: #1D4ED8;
}

QPushButton#cancelButton {
    background: #F1F2F4;
    border: none;
}

QFrame#separator {
    background: #E5E7EB;
    max-height: 1px;
    border: none;
}
"""



MAIN_WINDOW_STYLE = """
QMainWindow, QWidget#centralWidget { background-color: #F7F8FA; color: #202938; font-family: 'Segoe UI'; font-size: 13px; }
QFrame#panel { background-color: #FFFFFF; border: 1px solid #E5E9F0; border-radius: 16px; }
QLabel { background: transparent; color: #4B5563; }
QLabel#appTitle { color: #172033; font-size: 26px; font-weight: 700; }
QLabel#subtitle { color: #7B8797; font-size: 12px; }
QLabel#sectionTitle { color: #172033; font-size: 14px; font-weight: 700; }
QLabel#fieldLabel { color: #4B5563; font-size: 12px; font-weight: 600; }
QLabel#statusStopped { color: #64748B; font-weight: 700; padding: 7px 16px; background: #F1F5F9; border-radius: 12px; }
QLabel#statusRunning { color: #15803D; font-weight: 700; padding: 7px 16px; background: #DCFCE7; border-radius: 12px; }
QComboBox { background: #FFFFFF; color: #172033; border: 1px solid #DDE3EB; border-radius: 10px; padding: 10px 14px; min-height: 24px; }
QComboBox:hover, QComboBox:focus { border: 1px solid #94A3B8; }
QComboBox::drop-down { border: none; width: 32px; }
QComboBox QAbstractItemView { background: #FFFFFF; color: #172033; selection-background-color: #E8F0FE; border: 1px solid #DDE3EB; outline: 0; }
QRadioButton { color: #374151; padding: 10px 13px; spacing: 8px; }
QRadioButton::indicator { width: 17px; height: 17px; }
QPushButton { background: #FFFFFF; color: #344054; border: 1px solid #DDE3EB; border-radius: 10px; padding: 10px 14px; min-height: 23px; font-weight: 600; }
QPushButton:hover { background: #F1F5F9; border-color: #CBD5E1; }
QPushButton:pressed { background: #E2E8F0; }
QPushButton:disabled { color: #A5AFBE; background: #F1F3F6; border-color: #E6E9EE; }
QPushButton#primaryButton { color: white; background: #2563EB; border: 1px solid #2563EB; }
QPushButton#primaryButton:hover { background: #1D4ED8; }
QPushButton#primaryButton:disabled { color: #9CA3AF; background: #E5E7EB; border-color: #E5E7EB; }
QPushButton#stopButton { color: #B42318; border-color: #FECACA; background: #FFF7F7; }
QPushButton#stopButton:hover { background: #FEE2E2; }
QPushButton#stopButton:disabled { color: #A5AFBE; background: #F1F3F6; border-color: #E6E9EE; }
QTextEdit#logsView { background: #FBFCFE; color: #344054; border: 1px solid #E5E9F0; border-radius: 10px; padding: 10px; font-family: 'Consolas'; font-size: 12px; }
QScrollBar:vertical { width: 10px; background: transparent; }
QScrollBar::handle:vertical { background: #CDD5DF; border-radius: 5px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""



