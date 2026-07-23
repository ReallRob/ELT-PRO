import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QFrame, QLabel, QMessageBox, QToolButton, QWidget

from crpa_launcher import settings as crpa_settings
from crpa_launcher.app import CrpaLauncher, ExtensionArchiveImportThread
from core.packaging.external_extensions import ExtensionBuildError
from ui.design.import_export_ui import ImportExportUIMixin
from ui.design.workflow_io import load_workflow_file


class _EmptyScene:
    def items(self):
        return []


class _WorkflowContext:
    def __init__(self):
        self.workflow_config = None

    def build_workflow_logic(self, nodes):
        self.nodes = nodes
        self.workflow_config = {
            "workflow_name": "Original workflow",
            "state": {"run_status": "ready"},
            "steps": [],
        }
        return self.workflow_config


class _DesignSaveHarness(ImportExportUIMixin):
    def __init__(self, path):
        self._last_workflow_path = path
        self.canvas_scene = _EmptyScene()
        self.ctx = _WorkflowContext()
        self.workflow_name = "Original workflow"
        self.global_code = ""
        self.function_spaces = []
        self.runtime_parameters = {}
        self.parameter_mappings = {}
        self.crpa_metadata = {"name": "Example CRPA"}
        self.run_manifest = {}
        self.draft_saved = 0
        self.runtime_synced = 0
        self.settings_saved = 0

    def save_current_node_draft(self):
        self.draft_saved += 1

    def _sync_runtime_parameters(self):
        self.runtime_synced += 1

    def _save_app_settings(self):
        self.settings_saved += 1


class WorkflowSaveTests(unittest.TestCase):
    def test_close_save_writes_back_the_loaded_workflow_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "loaded.json")
            editor = _DesignSaveHarness(path)

            self.assertTrue(editor.save_workflow_before_close())
            saved = load_workflow_file(path)

        self.assertEqual(saved["workflow_name"], "Original workflow")
        self.assertEqual(saved["crpa"]["name"], "Example CRPA")
        self.assertEqual(editor.draft_saved, 1)
        self.assertEqual(editor.runtime_synced, 1)
        self.assertEqual(editor.settings_saved, 1)


class HistoryTagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_history_tag_edit_button_opens_tag_editor_for_its_json(self):
        launcher = CrpaLauncher()
        self.addCleanup(launcher.deleteLater)
        edits = []
        launcher._edit_history_tag = lambda path, tag: edits.append((path, tag))

        card = launcher._make_history_row(
            {
                "path": "C:/workflows/monthly.json",
                "crpa_code": "CRPA-01",
                "crpa_name": "Monthly",
                "tag": "Finance",
                "open_count": 1,
            }
        )
        tag_button = card.findChild(QToolButton, "historyEditTag")

        self.assertIsNotNone(tag_button)
        tag_button.click()

        self.assertEqual(edits, [("C:/workflows/monthly.json", "Finance")])

    def test_history_card_keeps_name_tag_and_code_on_separate_rows(self):
        launcher = CrpaLauncher()
        self.addCleanup(launcher.deleteLater)
        edits = []
        launcher._edit_history_name = lambda path, name: edits.append((path, name))
        card = launcher._make_history_row(
            {
                "path": "C:/workflows/monthly.json",
                "crpa_code": "CRPA-01",
                "crpa_name": "Monthly",
                "display_name": "财务月报",
                "tag": "Finance",
                "open_count": 1,
            }
        )

        name_button = card.findChild(QLabel, "historyName")
        tag_button = card.findChild(QLabel, "historyTag")
        code_label = card.findChild(QLabel, "historyCode")

        self.assertEqual(name_button.text(), "名称：财务月报")
        self.assertEqual(tag_button.text(), "标签：Finance")
        self.assertEqual(code_label.text(), "CRPA 代码：CRPA-01")
        self.assertIsNotNone(card.findChild(QToolButton, "historyEditTag"))
        self.assertGreaterEqual(card.minimumHeight(), 122)
        self.assertGreater(card.maximumHeight(), card.minimumHeight())
        card.findChild(QToolButton, "historyEditName").click()
        self.assertEqual(edits, [("C:/workflows/monthly.json", "财务月报")])

    def test_history_text_click_loads_json_without_opening_an_editor(self):
        launcher = CrpaLauncher()
        self.addCleanup(launcher.deleteLater)
        with patch.object(launcher, "_load_history_json") as load_json:
            card = launcher._make_history_row(
                {
                    "path": "C:/workflows/monthly.json",
                    "crpa_code": "CRPA-01",
                    "crpa_name": "Monthly",
                }
            )
            card.resize(240, 220)
            card.show()
            self.addCleanup(card.close)
            self.app.processEvents()

            QTest.mouseClick(card.findChild(QLabel, "historyName"), Qt.LeftButton)
            self.app.processEvents()

        load_json.assert_called_once_with("C:/workflows/monthly.json")

    def test_history_search_matches_name_tag_and_code_by_containment(self):
        launcher = CrpaLauncher()
        self.addCleanup(launcher.deleteLater)
        history = [
            {
                "path": "C:/workflows/finance.json",
                "crpa_code": "CRPA-FIN-01",
                "crpa_name": "月度财务",
                "display_name": "财务总览",
                "tag": "月报",
                "open_count": 1,
            },
            {
                "path": "C:/workflows/sales.json",
                "crpa_code": "CRPA-SALES-02",
                "crpa_name": "销售日报",
                "tag": "销售",
                "open_count": 1,
            },
        ]
        with patch("crpa_launcher.app.get_json_history", return_value=history):
            launcher.history_search_input.setText("fin")
            self.app.processEvents()

            self.assertEqual(launcher.history_list_layout.count(), 1)
            card = launcher.history_list_layout.itemAt(0).widget()
            self.assertEqual(card.findChild(QLabel, "historyName").text(), "名称：财务总览")

    def test_history_count_records_only_after_a_valid_run_starts(self):
        launcher = CrpaLauncher()
        self.addCleanup(launcher.deleteLater)
        launcher.workflow_path = "C:/workflows/monthly.json"
        launcher.workflow = {"run_manifest": {}}
        launcher.crpa_code = "CRPA-01"
        launcher.name = "Monthly"
        launcher.writeback_check.setChecked(False)
        launcher._build_current_runtime_workflow = lambda: ({}, {}, {}, {})
        launcher._start_engine = lambda workflow, *_args: None
        launcher._refresh_history_panel = lambda: None

        with patch("crpa_launcher.app.build_crpa_payload", return_value={}), patch(
            "crpa_launcher.app.record_json_open"
        ) as record_open:
            launcher.run_workflow()

        record_open.assert_called_once_with(
            "C:/workflows/monthly.json", "CRPA-01", "Monthly"
        )

    def test_loading_json_does_not_increment_history_count(self):
        launcher = CrpaLauncher()
        self.addCleanup(launcher.deleteLater)
        workflow = {
            "workflow_name": "Monthly",
            "crpa": {"code": "CRPA-01", "name": "Monthly"},
            "run_manifest": {"file_resources": [], "data_sources": [], "parameters": []},
        }

        with patch("crpa_launcher.app.load_workflow_json", return_value=workflow), patch(
            "crpa_launcher.app.record_json_load"
        ) as record_load, patch("crpa_launcher.app.record_json_open") as record_open, patch(
            "crpa_launcher.app.set_last_workflow_path"
        ):
            launcher.load_json("C:/workflows/monthly.json")

        record_open.assert_not_called()
        record_load.assert_called_once_with("C:/workflows/monthly.json", "CRPA-01", "Monthly")

    def test_loading_registers_history_with_zero_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "launcher-config.json"
            workflow_path = Path(directory) / "monthly.json"
            with patch.object(crpa_settings, "CONFIG_PATH", config_path), patch.object(
                crpa_settings, "LEGACY_CONFIG_PATH", Path(directory) / "legacy.json"
            ):
                crpa_settings.record_json_load(workflow_path, "CRPA-01", "Monthly")
                loaded = crpa_settings.get_json_history()
                crpa_settings.record_json_open(workflow_path, "CRPA-01", "Monthly")
                ran = crpa_settings.get_json_history()

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["open_count"], 0)
        self.assertEqual(ran[0]["open_count"], 1)

    def test_runner_has_extension_import_button(self):
        launcher = CrpaLauncher()
        self.addCleanup(launcher.deleteLater)

        self.assertEqual(launcher.btn_import_extension.text(), "导入扩展包")
        self.assertTrue(launcher.findChild(QFrame, "runPanel").isAncestorOf(launcher.btn_import_extension))
        self.assertEqual(launcher.findChild(QLabel, "sideTitle").text(), "操作区")
        self.assertFalse(hasattr(launcher, "file_count_label"))

    def test_runner_uses_compact_side_panels(self):
        launcher = CrpaLauncher()
        self.addCleanup(launcher.deleteLater)

        run_panel = launcher.findChild(QFrame, "runPanel")
        self.assertEqual(launcher.history_panel.width(), 220)
        self.assertEqual(run_panel.width(), 270)
        self.assertTrue(run_panel.findChild(QWidget, "operationActions").isAncestorOf(launcher.btn_import_extension))
        self.assertTrue(launcher.status_label.wordWrap())

    def test_history_card_allows_long_fields_to_expand(self):
        launcher = CrpaLauncher()
        self.addCleanup(launcher.deleteLater)
        card = launcher._make_history_row(
            {
                "path": "C:/workflows/very-long-workflow-name.json",
                "crpa_code": "CRPA-VERY-LONG-CODE-20260721",
                "crpa_name": "需要完整显示的较长流程名称",
                "display_name": "需要完整显示的较长流程名称",
                "tag": "较长的业务标签",
            }
        )

        self.assertTrue(card.findChild(QLabel, "historyName").wordWrap())
        self.assertTrue(card.findChild(QLabel, "historyTag").wordWrap())
        self.assertTrue(card.findChild(QLabel, "historyCode").wordWrap())
        self.assertTrue(card.findChild(QLabel, "historyFile").wordWrap())

    def test_extension_import_thread_merges_the_archive(self):
        result = {
            "created_initial_environment": False,
            "added_distributions": ["requests"],
            "updated_distributions": [],
        }

        thread = ExtensionArchiveImportThread(r"D:\received\requests.zip")
        with patch("crpa_launcher.app.import_extension_archive", return_value=result) as import_archive:
            thread.run()

        import_archive.assert_called_once_with(r"D:\received\requests.zip")
        self.assertEqual(thread.result, result)
        self.assertEqual(thread.error, "")

    def test_extension_import_failure_is_reported_after_thread_finishes(self):
        launcher = CrpaLauncher()
        self.addCleanup(launcher.deleteLater)

        thread = ExtensionArchiveImportThread(r"D:\received\broken.zip")
        thread.error = "broken archive"
        thread.error_trace = "traceback"
        launcher._extension_import_thread = thread
        launcher.btn_import_extension.setEnabled(False)
        with patch.object(QMessageBox, "warning") as warning:
            launcher._on_extension_import_thread_finished()

        self.assertEqual(launcher.status_label.text(), "扩展导入失败")
        warning.assert_called_once()
        self.assertTrue(launcher.btn_import_extension.isEnabled())

    def test_extension_import_restarts_the_launcher_after_success(self):
        launcher = CrpaLauncher()
        self.addCleanup(launcher.deleteLater)
        thread = ExtensionArchiveImportThread(r"D:\received\requests.zip")
        thread.result = {
            "created_initial_environment": False,
            "added_distributions": ["requests"],
            "updated_distributions": [],
        }
        launcher._extension_import_thread = thread

        with patch("crpa_launcher.app.QProcess.startDetached", return_value=True) as start_detached, patch(
            "crpa_launcher.app.QTimer.singleShot"
        ) as single_shot:
            launcher._on_extension_import_thread_finished()

        start_detached.assert_called_once()
        single_shot.assert_called_once()


if __name__ == "__main__":
    unittest.main()
