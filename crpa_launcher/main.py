"""Entry point for the isolated CRPA JSON launcher."""

import multiprocessing
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt5.QtWidgets import QApplication

from crpa_launcher.app import CrpaLauncher
from crpa_launcher.settings import get_last_workflow_path
from core.qt_wheel_guard import install_combo_wheel_guard


def main():
    multiprocessing.freeze_support()

    app = QApplication(sys.argv)
    install_combo_wheel_guard(app)
    app.setStyle("Fusion")

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
