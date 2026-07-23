"""Small background scanners used by operator configuration panels."""

from PyQt5.QtCore import QThread, pyqtSignal


class ExcelSheetScanThread(QThread):
    finished_signal = pyqtSignal(int, str, object, str)

    def __init__(self, generation, path, parent=None):
        super().__init__(parent)
        self.generation = int(generation)
        self.path = str(path or "")

    def run(self):
        sheets = []
        error = ""
        try:
            import pandas as pd

            with pd.ExcelFile(self.path) as excel:
                sheets = list(excel.sheet_names)
        except Exception as exc:
            error = str(exc)
        self.finished_signal.emit(self.generation, self.path, sheets, error)

