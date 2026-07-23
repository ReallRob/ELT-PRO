import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QLabel, QPlainTextEdit

from operators.panels.code_block_panel import CodeEditorDialog, PythonCodeEditor


class PythonCodeEditorHighlighterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = PythonCodeEditor()

    def tearDown(self):
        self.editor.deleteLater()

    def _colors_for_block(self, block_number):
        self.editor.syntax_highlighter.rehighlight()
        self.app.processEvents()
        block = self.editor.document().findBlockByNumber(block_number)
        return {
            text_range.format.foreground().color().name().lower()
            for text_range in block.layout().formats()
        }

    def test_highlights_python_tokens(self):
        self.editor.setPlainText('def clean(df):\n    return "# ready"  # note 42')

        first_line_colors = self._colors_for_block(0)
        second_line_colors = self._colors_for_block(1)

        self.assertIn("#c084fc", first_line_colors)
        self.assertIn("#93c5fd", first_line_colors)
        self.assertIn("#7dd3fc", first_line_colors)
        self.assertIn("#c084fc", second_line_colors)
        self.assertIn("#a7f3d0", second_line_colors)
        self.assertIn("#94a3b8", second_line_colors)

    def test_highlights_multiline_strings(self):
        self.editor.setPlainText('value = """first\n# still string\nlast"""')

        self.assertIn("#a7f3d0", self._colors_for_block(0))
        self.assertIn("#a7f3d0", self._colors_for_block(1))
        self.assertIn("#a7f3d0", self._colors_for_block(2))

    def test_line_numbers_reserve_a_dynamic_gutter(self):
        initial_width = self.editor.line_number_area_width()
        self.editor.setPlainText("\n".join("pass" for _ in range(100)))

        self.assertGreater(self.editor.line_number_area_width(), initial_width)
        self.assertEqual(self.editor.viewportMargins().left(), self.editor.line_number_area_width())

    def test_editor_dialog_allows_minimize_and_maximize(self):
        dialog = CodeEditorDialog()
        self.addCleanup(dialog.deleteLater)

        flags = dialog.windowFlags()
        self.assertTrue(flags & Qt.WindowMinimizeButtonHint)
        self.assertTrue(flags & Qt.WindowMaximizeButtonHint)
        self.assertTrue(flags & Qt.WindowCloseButtonHint)

    def test_editor_dialog_persists_independent_process_mode(self):
        dialog = CodeEditorDialog(execution_mode="process")
        self.addCleanup(dialog.deleteLater)

        self.assertTrue(dialog.process_mode_checkbox.isChecked())
        self.assertEqual(dialog.execution_mode(), "process")

    def test_editor_dialog_explains_the_run_status_api(self):
        dialog = CodeEditorDialog()
        self.addCleanup(dialog.deleteLater)

        titles = {
            label.text()
            for label in dialog.findChildren(QLabel, "assist_title")
        }
        help_text = "\n".join(
            editor.toPlainText()
            for editor in dialog.help_page.findChildren(QPlainTextEdit)
        )

        self.assertIn("运行状态", titles)
        self.assertIn("state['run_status']", help_text)
        self.assertIn("should_cancel()", help_text)
        self.assertIn("check_cancel()", help_text)

    def test_function_space_reference_name_is_saved_without_import_aliases(self):
        dialog = CodeEditorDialog(
            function_spaces=[
                {
                    "id": "text_utils",
                    "name": "文本函数",
                    "namespace": "text_utils",
                    "import_aliases": ["fun"],
                    "enabled": True,
                    "code": "def normalize(value):\n    return value",
                }
            ]
        )
        self.addCleanup(dialog.deleteLater)

        self.assertEqual(dialog.space_namespace_input.text(), "text_utils")
        self.assertFalse(hasattr(dialog, "space_import_aliases_input"))
        self.assertEqual(dialog.space_expose_checkbox.text(), "允许直接调用函数")
        dialog.space_namespace_input.setText("fun")
        space = dialog.function_spaces()[0]

        self.assertEqual(space["namespace"], "fun")
        self.assertNotIn("import_aliases", space)


if __name__ == "__main__":
    unittest.main()
