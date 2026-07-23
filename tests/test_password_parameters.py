import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QComboBox, QLineEdit

from core.manifest_builder import build_run_manifest
from crpa_launcher.app import CrpaLauncher
from operators.panels.advanced_param_mapping import AdvancedParamMappingPanel


class PasswordParameterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_designer_password_parameter_is_masked_and_exports_as_password(self):
        panel = AdvancedParamMappingPanel(None, editor_mode=True)
        self.addCleanup(panel.deleteLater)
        row = panel.param_rows.itemAt(0).widget()
        type_combo = row.findChild(QComboBox, "input_type")
        type_combo.setCurrentText("密码")
        row.findChild(QLineEdit, "field_name").setText("api_password")
        row._value_input.setText("top-secret")
        self.app.processEvents()

        self.assertEqual(row._value_input.echoMode(), QLineEdit.Password)
        params = panel.get_custom_params()
        self.assertEqual(params["advanced_parameters"][0]["dataType"], "Password")
        self.assertEqual(params["advanced_parameters"][0]["input"], "top-secret")

        manifest = build_run_manifest(
            {"steps": [{"action": "advanced_param_mapping", "params": params}]}
        )
        self.assertEqual(manifest["parameters"][0]["type"], "password")
        self.assertEqual(manifest["parameters"][0]["default"], "top-secret")

    def test_runner_masks_password_but_keeps_its_runtime_value(self):
        launcher = CrpaLauncher()
        self.addCleanup(launcher.deleteLater)

        widget = launcher._make_param_widget(
            {"key": "api_password", "type": "password", "default": "top-secret"}
        )

        self.assertIsInstance(widget, QLineEdit)
        self.assertEqual(widget.echoMode(), QLineEdit.Password)
        self.assertEqual(widget.text(), "top-secret")

    def test_console_payload_redacts_saved_passwords_without_mutating_execution_payload(self):
        payload = {
            "parameters": {"api_password": "top-secret", "report_name": "monthly"},
            "manifest": {
                "parameters": [
                    {"key": "api_password", "type": "password", "default": "top-secret"},
                    {"key": "report_name", "type": "text", "default": "monthly"},
                ]
            },
        }

        redacted = CrpaLauncher._redact_crpa_payload(payload)

        self.assertEqual(redacted["parameters"]["api_password"], "******")
        self.assertEqual(redacted["manifest"]["parameters"][0]["default"], "******")
        self.assertEqual(redacted["parameters"]["report_name"], "monthly")
        self.assertEqual(payload["parameters"]["api_password"], "top-secret")
        self.assertEqual(payload["manifest"]["parameters"][0]["default"], "top-secret")


if __name__ == "__main__":
    unittest.main()
