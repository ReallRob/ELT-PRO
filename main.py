import sys
import os
import json
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QTabWidget,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from ui.design.design_mode import DesignModeWidget
from ui.execute.execute_mode import ExecuteModeWidget


def get_executable_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).parent.absolute()


CONFIG_DIR = get_executable_dir() / "config"
CONFIG_FILE_PATH = CONFIG_DIR / "workspace_config.json"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Excel ETL 数据工作站 - 专业版")    
        self.resize(1350, 900)
        self.init_ui()

        self.load_workspace_state()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.tabs = QTabWidget()

        # 修复显示不全：增加 min-width 强制分配空间，并减小左右 padding
        self.tabs.setStyleSheet("""
            QTabBar::tab {
                font-family: 'Microsoft YaHei';
                font-size: 14px;
                font-weight: bold;
                min-width: 220px;
                padding: 10px 10px;
                background-color: #E0E0E0;
                color: #555;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
                margin-top: 5px;
            }
            QTabBar::tab:selected {
                background-color: white;
                color: #2196F3;
                border: 1px solid #ccc;
                border-bottom: none;
            }
            QTabBar::tab:hover:!selected {
                background-color: #D6D6D6;
            }
            QTabWidget::pane {
                border-top: 1px solid #ccc;
                background-color: white;
            }
        """)

        self.page_design = DesignModeWidget()
        self.page_execute = ExecuteModeWidget()

        self.tabs.addTab(self.page_design, "设计模式 (构建规则)")
        self.tabs.addTab(self.page_execute, "执行模式 (自动运行)")

        main_layout.addWidget(self.tabs)

    def load_workspace_state(self):
        if not CONFIG_FILE_PATH.exists():
            return

        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)

            last_mode = state.get("last_mode_index", 0)
            self.tabs.setCurrentIndex(last_mode)

            exec_state = state.get("execute_mode", {})
            if hasattr(self.page_execute, "restore_state"):
                last_path = exec_state.get("last_workflow_path")
                saved_mappings = exec_state.get("file_mappings", {})
                if last_path:
                    self.page_execute.restore_state(last_path, saved_mappings)

        except Exception as e:
            print(f"工作区配置文件加载异常: {e}")

    def closeEvent(self, event):
        # 1. 先让设计模式写入 dock / 命名 / 可见性状态
        if hasattr(self.page_design, "save_design_state"):
            self.page_design.save_design_state()

        # 2. 收集执行模式状态
        exec_state = {}
        if hasattr(self.page_execute, "get_state"):
            exec_state = self.page_execute.get_state()

        # 3. 合并已有配置并写入
        existing = {}
        if CONFIG_FILE_PATH.exists():
            try:
                with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass

        state_to_save = {
            **existing,
            "last_mode_index": self.tabs.currentIndex(),
            "execute_mode": exec_state,
        }

        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(state_to_save, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"保存配置失败: {e}")

        event.accept()


if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    global_font = QFont("Microsoft YaHei", 10)
    app.setFont(global_font)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())
