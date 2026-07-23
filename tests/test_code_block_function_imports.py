import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from openpyxl import Workbook

from core.dataframe_ops.code_exec import run_dataframe_code


class FunctionSpaceImportTests(unittest.TestCase):
    @staticmethod
    def _space(namespace="text_utils", code=None):
        return {
            "id": namespace,
            "name": namespace,
            "namespace": namespace,
            "enabled": True,
            "expose_globals": False,
            "code": code or "def normalize(value):\n    return str(value).strip().upper()",
        }

    @staticmethod
    def _returned_value(result):
        return result.outputs[0].data.iloc[0]["值"]

    def test_star_import_from_function_space_reference_name(self):
        result = run_dataframe_code(
            {},
            "from fun import *\nreturn normalize('  demo  ')",
            function_spaces=[self._space("fun")],
        )

        self.assertEqual(self._returned_value(result), "DEMO")

    def test_run_status_is_available_without_manual_state_setup(self):
        result = run_dataframe_code({}, "return state['run_status']")

        self.assertEqual(self._returned_value(result), "running")

    def test_code_block_activates_external_extensions_before_execution(self):
        with patch("core.dataframe_ops.code_exec.activate_external_extensions") as activate_extensions:
            result = run_dataframe_code({}, "return 1")

        self.assertEqual(self._returned_value(result), 1)
        activate_extensions.assert_called()

    def test_code_block_can_write_a_config_file_with_open(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file = os.path.join(directory, "config.ini")
            result = run_dataframe_code(
                {},
                "with open(params['config_file'], 'w', encoding='utf-8') as configfile:\n"
                "    configfile.write('[app]\\nclosed = true\\n')\n"
                "return 'saved'",
                runtime_parameters={"config_file": config_file},
            )

            with open(config_file, encoding="utf-8") as configfile:
                saved_config = configfile.read()

        self.assertEqual(self._returned_value(result), "saved")
        self.assertEqual(saved_config, "[app]\nclosed = true\n")

    def test_code_block_allows_standard_library_submodule_imports(self):
        result = run_dataframe_code(
            {},
            "from urllib import parse\nreturn parse.__name__",
        )

        self.assertEqual(self._returned_value(result), "urllib.parse")

    def test_explicit_and_module_imports_from_function_space_reference_name(self):
        space = self._space(
            code="def add(left, right):\n    return left + right",
        )
        explicit_result = run_dataframe_code(
            {},
            "from text_utils import add\nreturn add(2, 3)",
            function_spaces=[space],
        )
        module_result = run_dataframe_code(
            {},
            "import text_utils as helpers\nreturn helpers.add(4, 5)",
            function_spaces=[space],
        )
        namespace_result = run_dataframe_code(
            {},
            "return text_utils.add(6, 7)",
            function_spaces=[space],
        )

        self.assertEqual(self._returned_value(explicit_result), 5)
        self.assertEqual(self._returned_value(module_result), 9)
        self.assertEqual(self._returned_value(namespace_result), 13)

    def test_legacy_global_code_is_available_by_its_reference_name(self):
        result = run_dataframe_code(
            {},
            "from global_funcs import *\nreturn twice(6)",
            global_code="def twice(value):\n    return value * 2",
        )

        self.assertEqual(self._returned_value(result), 12)

    def test_duplicate_function_space_reference_names_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "函数空间引用名称重复: fun"):
            run_dataframe_code(
                {},
                "return 1",
                function_spaces=[
                    self._space("fun"),
                    self._space("fun", "def other():\n    return 1"),
                ],
            )

    def test_function_spaces_resolve_from_imports_out_of_list_order(self):
        result = run_dataframe_code(
            {},
            "from reports import make_label\nreturn make_label(' demo ')",
            function_spaces=[
                self._space(
                    "reports",
                    "from text_utils import normalize\n\ndef make_label(value):\n    return '报告:' + normalize(value)",
                ),
                self._space(
                    "text_utils",
                    "def normalize(value):\n    return str(value).strip().upper()",
                ),
            ],
        )

        self.assertEqual(self._returned_value(result), "报告:DEMO")

    def test_function_spaces_can_reference_each_other_with_module_imports(self):
        result = run_dataframe_code(
            {},
            "return left_space.add_one(3)",
            function_spaces=[
                self._space(
                    "left_space",
                    "import right_space\n\ndef add_one(value):\n    return right_space.double(value) + 1",
                ),
                self._space(
                    "right_space",
                    "import left_space\n\ndef double(value):\n    return value * 2",
                ),
            ],
        )

        self.assertEqual(self._returned_value(result), 7)

    def test_circular_from_imports_report_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, "函数空间存在循环引用"):
            run_dataframe_code(
                {},
                "return 1",
                function_spaces=[
                    self._space("one", "from two import helper\n\ndef first():\n    return helper()"),
                    self._space("two", "from one import first\n\ndef helper():\n    return first()"),
                ],
            )

    def test_independent_process_reads_parameters_and_main_entry(self):
        logs = []
        result = run_dataframe_code(
            {},
            "if __name__ == '__main__':\n    print(params['title'])\n    return param('value') * 2",
            runtime_parameters={"title": "child-ready", "value": 21},
            execution_mode="process",
            log_callback=logs.append,
        )

        self.assertEqual(self._returned_value(result), 42)
        self.assertIn("代码块输出: child-ready", logs)

    def test_independent_process_rejects_memory_workbooks(self):
        with self.assertRaisesRegex(ValueError, "不支持内存 Workbook"):
            run_dataframe_code(
                {},
                "return 1",
                workbooks={"wb": Workbook()},
                execution_mode="process",
            )

    def test_independent_process_accepts_clean_system_exit(self):
        result = run_dataframe_code(
            {},
            "import sys\nif __name__ == '__main__':\n    sys.exit(0)",
            execution_mode="process",
        )

        self.assertEqual(result.outputs, [])

    def test_independent_process_can_run_a_qt_event_loop(self):
        previous_platform = os.environ.get("QT_QPA_PLATFORM")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        try:
            result = run_dataframe_code(
                {},
                "import sys\n"
                "from PyQt5.QtCore import QTimer\n"
                "from PyQt5.QtWidgets import QApplication, QWidget\n"
                "if __name__ == '__main__':\n"
                "    app = QApplication(sys.argv)\n"
                "    window = QWidget()\n"
                "    window.show()\n"
                "    QTimer.singleShot(20, app.quit)\n"
                "    sys.exit(app.exec_())",
                execution_mode="process",
            )
        finally:
            if previous_platform is None:
                os.environ.pop("QT_QPA_PLATFORM", None)
            else:
                os.environ["QT_QPA_PLATFORM"] = previous_platform

        self.assertEqual(result.outputs, [])

    def test_independent_process_stops_when_parent_state_changes(self):
        state = {"run_status": "running"}
        outcome = {}

        def run_code():
            try:
                run_dataframe_code(
                    {},
                    "import time\ntime.sleep(30)",
                    state=state,
                    execution_mode="process",
                )
            except Exception as exc:
                outcome["error"] = exc

        runner = threading.Thread(target=run_code)
        runner.start()
        time.sleep(0.4)
        state["run_status"] = "stopped"
        runner.join(timeout=10)

        self.assertFalse(runner.is_alive())
        self.assertIsInstance(outcome.get("error"), RuntimeError)
        self.assertIn("独立进程已终止", str(outcome["error"]))

    def test_independent_process_receives_live_state_updates(self):
        state = {"run_status": "running", "signal": ""}
        outcome = {}

        def run_code():
            outcome["result"] = run_dataframe_code(
                {},
                "import time\n"
                "while state.get('signal') != 'ready':\n"
                "    time.sleep(0.05)\n"
                "return state['signal']",
                state=state,
                execution_mode="process",
            )

        runner = threading.Thread(target=run_code)
        runner.start()
        time.sleep(0.4)
        state["signal"] = "ready"
        runner.join(timeout=10)

        self.assertFalse(runner.is_alive())
        self.assertEqual(self._returned_value(outcome["result"]), "ready")

    def test_missing_function_space_and_non_bundle_imports(self):
        with self.assertRaisesRegex(ValueError, "No module named 'fun'"):
            run_dataframe_code({}, "from fun import *\nreturn 1")
        result = run_dataframe_code({}, "from pathlib import Path\nreturn Path('folder').name")
        self.assertEqual(self._returned_value(result), "folder")


if __name__ == "__main__":
    unittest.main()
