"""Entry point for the isolated CRPA JSON launcher."""

import multiprocessing
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication

from crpa_launcher.app import CrpaLauncher
from crpa_launcher.settings import get_last_workflow_path
from core.qt_wheel_guard import install_combo_wheel_guard
from core.runtime_extensions import activate_external_extensions


def main():
    multiprocessing.freeze_support()
    activate_external_extensions()

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    install_combo_wheel_guard(app)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))

    window = CrpaLauncher()
    if len(sys.argv) > 1:
        window.load_json(sys.argv[1])
    else:
        last_path = get_last_workflow_path()
        if last_path:
            window.load_json(last_path)
    window.show()

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
