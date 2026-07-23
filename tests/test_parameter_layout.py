import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QComboBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QWidget

from core.manifest_builder import build_run_manifest
from crpa_launcher.app import CrpaLauncher
from operators.panels.advanced_param_mapping import AdvancedParamMappingPanel


class ParameterLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = AdvancedParamMappingPanel(None, editor_mode=True)

    def tearDown(self):
        self.panel.deleteLater()

    @staticmethod
    def _name(row):
        return row.findChild(QLineEdit, "field_name").text()

    def test_value_editor_uses_a_single_type_page(self):
        row = self.panel.param_rows.itemAt(0).widget()
        type_combo = row.findChild(QComboBox, "input_type")

        self.assertEqual(row._value_stack.currentIndex(), 0)
        self.assertTrue(row._filters_row.isHidden())
        default_row = next(
            field_row
            for field_row in row.findChildren(QWidget, "param_field_row")
            if field_row.findChild(QLabel, "param_field_label").text() == "默认值"
        )
        self.assertTrue(default_row.findChild(QLabel, "param_field_label").alignment() & Qt.AlignTop)
        type_combo.setCurrentText("勾选框")
        self.assertEqual(row._value_stack.currentIndex(), 1)
        self.assertLess(row._value_stack.sizeHint().height(), 50)
        type_combo.setCurrentText("列表")
        self.assertEqual(row._value_stack.currentIndex(), 2)
        type_combo.setCurrentText("键值对")
        self.assertEqual(row._value_stack.currentIndex(), 3)
        type_combo.setCurrentText("下拉选择")
        self.assertEqual(row._value_stack.currentIndex(), 4)
        type_combo.setCurrentText("文本")
        self.assertEqual(row._value_stack.currentIndex(), 0)

    def test_prompt_information_is_saved_and_used_as_an_input_placeholder(self):
        row = self.panel.param_rows.itemAt(0).widget()
        row.findChild(QLineEdit, "field_name").setText("report_month")
        row.findChild(QLineEdit, "tip").setText("例如：2026-07")

        params = self.panel.get_custom_params()
        self.assertEqual(params["advanced_parameters"][0]["tip"], "例如：2026-07")

        launcher = CrpaLauncher()
        self.addCleanup(launcher.deleteLater)
        widget = launcher._make_param_widget(
            {"key": "report_month", "type": "text", "tip": "例如：2026-07"}
        )
        self.assertEqual(widget.placeholderText(), "例如：2026-07")

    def test_list_parameter_initial_count_and_upper_limit_round_trip_to_runner(self):
        row = self.panel.param_rows.itemAt(0).widget()
        row.findChild(QLineEdit, "field_name").setText("recipients")
        row.findChild(QComboBox, "input_type").setCurrentText("列表")
        row._list_initial_count.setValue(2)
        row._list_max_items.setValue(3)

        params = self.panel.get_custom_params()
        configured = params["advanced_parameters"][0]
        self.assertEqual(configured["initial_count"], 2)
        self.assertEqual(configured["max_items"], 3)

        manifest = build_run_manifest(
            {"steps": [{"action": "advanced_param_mapping", "params": params}]}
        )
        self.assertEqual(manifest["parameters"][0]["initial_count"], 2)
        self.assertEqual(manifest["parameters"][0]["max_items"], 3)

        launcher = CrpaLauncher()
        self.addCleanup(launcher.deleteLater)
        widget = launcher._make_param_widget(manifest["parameters"][0])
        self.addCleanup(widget.deleteLater)
        widget.show()
        self.app.processEvents()

        self.assertEqual(widget._row_count(), 2)
        widget.add_btn.click()
        self.app.processEvents()
        self.assertEqual(widget._row_count(), 3)
        self.assertFalse(widget.add_btn.isEnabled())
        self.assertIn("上限", widget.add_btn.text())

        first_row = widget.list_layout.itemAt(0).widget()
        widget._remove_item(first_row)
        self.app.processEvents()
        self.assertEqual(widget._row_count(), 2)
        self.assertTrue(widget.add_btn.isEnabled())

    def test_new_list_item_is_revealed_and_focused_when_list_scrolls(self):
        launcher = CrpaLauncher()
        self.addCleanup(launcher.deleteLater)
        widget = launcher._make_param_widget(
            {
                "key": "recipients",
                "type": "list",
                "initial_count": 5,
                "max_items": 6,
            }
        )
        self.addCleanup(widget.deleteLater)
        widget.resize(700, 400)
        widget.show()
        self.app.processEvents()

        widget.add_btn.click()
        self.app.processEvents()

        scrollbar = widget.list_scroll.verticalScrollBar()
        new_row = widget.list_layout.itemAt(5).widget()
        new_line = new_row.findChild(QLineEdit, "listParamItem")
        self.assertEqual(scrollbar.value(), scrollbar.maximum())
        self.assertTrue(new_line.hasFocus())

    def test_key_value_parameter_uses_the_same_initial_and_upper_limits(self):
        row = self.panel.param_rows.itemAt(0).widget()
        row.findChild(QLineEdit, "field_name").setText("docx_replacements")
        row.findChild(QComboBox, "input_type").setCurrentText("键值对")
        row._key_value_initial_count.setValue(2)
        row._key_value_max_items.setValue(3)
        default_row = row._key_value_editor.findChild(QWidget, "key_value_item_row")
        default_row.findChild(QLineEdit, "key_value_key").setText("docx{姓名}")
        default_row.findChild(QLineEdit, "key_value_value").setText("小明")

        params = self.panel.get_custom_params()
        configured = params["advanced_parameters"][0]
        self.assertEqual(configured["dataType"], "Object")
        self.assertEqual(configured["value"], {"docx{姓名}": "小明"})
        self.assertEqual(configured["initial_count"], 2)
        self.assertEqual(configured["max_items"], 3)

        manifest = build_run_manifest(
            {"steps": [{"action": "advanced_param_mapping", "params": params}]}
        )
        parameter = manifest["parameters"][0]
        self.assertEqual(parameter["type"], "key_value")
        self.assertEqual(parameter["max_items"], 3)

        launcher = CrpaLauncher()
        self.addCleanup(launcher.deleteLater)
        widget = launcher._make_param_widget(parameter)
        self.addCleanup(widget.deleteLater)
        self.assertEqual(widget.property("param_type"), "key_value")
        self.assertEqual(widget._row_count(), 2)
        self.assertEqual(widget.value(), {"docx{姓名}": "小明"})

        widget.add_btn.click()
        self.app.processEvents()
        self.assertEqual(widget._row_count(), 3)
        self.assertFalse(widget.add_btn.isEnabled())

    def test_parameter_editor_can_collapse_all_rows(self):
        self.panel.add_parameter_row("second", focus_new=False)

        self.panel._toggle_all_parameter_bodies()

        for row in self.panel._parameter_rows_in_order():
            self.assertTrue(row.findChild(QLineEdit, "field_name"))
            self.assertTrue(row.findChild(QWidget, "param_body").isHidden())
        self.assertEqual(self.panel.collapse_all_button.text(), "展开全部")

    def test_parameters_can_move_up_and_down_without_dragging(self):
        first = self.panel.param_rows.itemAt(0).widget()
        first.findChild(QLineEdit, "field_name").setText("first")
        second = self.panel.add_parameter_row("second", focus_new=False)

        self.panel._move_parameter(second, -1)
        self.assertEqual([self._name(row) for row in self.panel._parameter_rows_in_order()], ["second", "first"])

        self.panel._move_parameter(second, 1)
        self.assertEqual([self._name(row) for row in self.panel._parameter_rows_in_order()], ["first", "second"])

    def test_container_layout_round_trips_to_manifest_and_runner(self):
        root_row = self.panel.param_rows.itemAt(0).widget()
        root_row.findChild(QLineEdit, "field_name").setText("report_name")
        container = self.panel.add_parameter_container("筛选条件", focus_new=False)
        self.panel.add_parameter_row("department", parent_container=container, focus_new=False)
        self.panel.add_parameter_row("month", parent_container=container, focus_new=False)

        params = self.panel.get_custom_params()
        layout = params["parameter_layout"]
        self.assertEqual(layout[0], {"kind": "parameter", "fieldName": "report_name"})
        self.assertEqual(layout[1]["title"], "筛选条件")
        self.assertEqual(
            [child["fieldName"] for child in layout[1]["children"]],
            ["department", "month"],
        )

        manifest = build_run_manifest(
            {"steps": [{"action": "advanced_param_mapping", "params": params}]}
        )
        self.assertEqual(manifest["parameter_layout"], layout)

        launcher = CrpaLauncher()
        self.addCleanup(launcher.deleteLater)
        card = launcher._create_param_card(manifest["parameters"], manifest["parameter_layout"])
        self.addCleanup(card.deleteLater)
        group = card.findChild(QGroupBox, "paramHorizontalGroup")
        self.assertIsNotNone(group)
        self.assertIsInstance(group.layout(), QHBoxLayout)
        self.assertEqual(set(launcher.param_inputs), {"report_name", "department", "month"})

    def test_parameter_can_move_into_and_out_of_a_container(self):
        row = self.panel.param_rows.itemAt(0).widget()
        row.findChild(QLineEdit, "field_name").setText("department")
        container = self.panel.add_parameter_container("筛选条件", focus_new=False)

        self.panel._move_parameter_to_container(row, container)
        self.assertIs(row._parent_container, container)
        self.assertEqual(container._parameter_children_layout.count(), 1)

        self.panel._move_parameter_to_root(row)
        self.assertIsNone(row._parent_container)
        self.assertEqual(container._parameter_children_layout.count(), 0)

    def test_compact_panel_edits_parameters_in_an_independent_window(self):
        compact_panel = AdvancedParamMappingPanel(None)
        self.addCleanup(compact_panel.deleteLater)

        self.assertFalse(hasattr(compact_panel, "param_rows"))
        self.assertTrue(compact_panel.top_card.isHidden())
        self.assertEqual(compact_panel.parameter_editor_button.text(), "编辑运行参数")
        compact_panel._open_parameter_editor()
        dialog = compact_panel._parameter_editor_dialog
        self.addCleanup(dialog.close)
        self.assertTrue(dialog.editor._editor_mode)

        row = dialog.editor.param_rows.itemAt(0).widget()
        row.findChild(QLineEdit, "field_name").setText("report_name")
        dialog._accept_parameters()

        self.assertEqual(compact_panel.get_custom_params()["advanced_parameters"][0]["fieldName"], "report_name")


if __name__ == "__main__":
    unittest.main()
