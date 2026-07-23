import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QMessageBox

from core.packaging.dependency_manifest import (
    bundled_import_roots,
    load_dependencies,
    requires_collect_all,
    runtime_stdlib_hidden_imports,
    runtime_stdlib_import_roots,
)
from core.packaging.spec_generator import _render_spec
from core.runtime_extensions import SITE_PACKAGES_DIRECTORY, get_extensions_root, runtime_identity, set_active_extension
from ui.design.package_manager_page import (
    AddDependencyDialog,
    ExtensionArchiveImportThread,
    ExtensionManifestDialog,
    PackageManagerPage,
)


class PackageManagerPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.page = PackageManagerPage()

    def tearDown(self):
        self.page.deleteLater()

    def test_shows_current_bundle_roots(self):
        all_modules = {item["module"] for item in self.page.dependencies()}
        modules = {
            item["module"]
            for item in self.page.dependencies()
            if item.get("delivery") != "external"
        }

        self.assertEqual(modules, set(bundled_import_roots()))
        self.assertEqual(self.page.tabs.count(), 3)
        self.assertEqual(
            [self.page.tabs.tabText(index) for index in range(self.page.tabs.count())],
            ["构建程序", "外置扩展", "程序基础包"],
        )
        self.assertEqual(self.page.dependency_table.rowCount(), len(all_modules))

    def test_baseline_dependencies_are_restored_from_a_partial_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            config.mkdir()
            (config / "dynamic_imports.json").write_text(
                '{"schema_version": 2, "packages": [{"module": "selenium", "delivery": "external"}]}',
                encoding="utf-8",
            )

            modules = {item["module"] for item in load_dependencies(root)}

        self.assertTrue({"PyQt5", "numpy", "openpyxl", "pandas"}.issubset(modules))
        self.assertIn("selenium", modules)

    def test_http_stdlib_submodules_are_precollected_for_external_packages(self):
        self.assertNotIn("http", bundled_import_roots("crpa_launcher"))
        self.assertFalse(requires_collect_all("http"))
        self.assertIn("http.cookies", runtime_stdlib_hidden_imports())

    def test_specs_collect_the_build_host_runtime_standard_library(self):
        roots = runtime_stdlib_import_roots()

        self.assertIn("http", roots)
        self.assertIn("os", roots)
        self.assertNotIn("ensurepip", roots)
        self.assertIn("runtime_stdlib_hidden_imports", _render_spec("crpa_launcher"))

    def test_extension_manifest_dialog_does_not_modify_builtin_draft(self):
        builtin_modules = {item["module"] for item in self.page.dependencies()}
        dialog = ExtensionManifestDialog(
            [{"name": "requests", "version": "2.32.3", "module": "requests"}],
            self.page,
        )
        self.addCleanup(dialog.deleteLater)

        dialog.available_list.setCurrentRow(0)
        dialog._add_selected_package()

        self.assertEqual(dialog.dependencies[0]["module"], "requests")
        self.assertEqual(dialog.dependencies[0]["delivery"], "external")
        self.assertEqual(dialog.archive_name(), "requests")
        dialog._add_dependency(
            {
                "module": "selenium",
                "distribution": "selenium",
                "collect": "all",
                "delivery": "external",
                "targets": ["main"],
                "source": "manual",
            }
        )
        self.assertEqual(dialog.archive_name(), "requests_selenium")
        self.assertEqual({item["module"] for item in self.page.dependencies()}, builtin_modules)

    def test_extension_manifest_dialog_keeps_a_custom_archive_name(self):
        dialog = ExtensionManifestDialog([], self.page)
        self.addCleanup(dialog.deleteLater)
        dialog.archive_name_input.setText("业务自动化")
        dialog._mark_archive_name_customized("业务自动化")

        dialog._add_dependency(
            {
                "module": "requests",
                "distribution": "requests",
                "collect": "all",
                "delivery": "external",
                "targets": ["main"],
                "source": "manual",
            }
        )

        self.assertEqual(dialog.archive_name(), "业务自动化")

    def test_filters_dependency_rows(self):
        self.page._dependencies = [
            {
                "module": "pandas",
                "distribution": "pandas",
                "collect": "all",
                "delivery": "bundled",
                "targets": ["main"],
                "source": "manual",
            },
            {
                "module": "selenium",
                "distribution": "selenium",
                "collect": "all",
                "delivery": "external",
                "targets": ["main"],
                "source": "manual",
            },
        ]
        self.page._refresh_dependency_table()
        self.page.dependency_search.setText("pandas")
        self.app.processEvents()

        self.assertEqual(self.page.dependency_table.rowCount(), 1)
        self.assertEqual(self.page.dependency_table.item(0, 0).text(), "pandas")

    def test_marks_tkinter_as_a_collect_all_standard_library(self):
        self.page._dependencies = [
            {
                "module": "tkinter",
                "distribution": "tkinter",
                "collect": "all",
                "delivery": "bundled",
                "targets": ["main"],
                "source": "stdlib",
            }
        ]
        self.page._refresh_dependency_table()
        rows = {
            self.page.dependency_table.item(row, 0).text(): row
            for row in range(self.page.dependency_table.rowCount())
        }

        tkinter_row = rows["tkinter"]
        self.assertEqual(self.page.dependency_table.item(tkinter_row, 2).text(), "标准库 · collect_all")
        self.assertEqual(self.page.dependency_table.item(tkinter_row, 4).text(), "标准库")
        self.assertIn("tkinter 的 Tcl/Tk", self.page.stdlib_notice.text())

    def test_rejects_tkinter_as_an_external_extension(self):
        dialog = AddDependencyDialog(["main"])
        self.addCleanup(dialog.deleteLater)
        dialog.module_input.setText("tkinter")
        dialog.delivery_combo.setCurrentIndex(dialog.delivery_combo.findData("external"))

        dialog._validate_and_accept()

        self.assertFalse(dialog.error_label.isHidden())
        self.assertIn("标准库", dialog.error_label.text())

    def test_add_dialog_lists_searches_and_prefills_environment_packages(self):
        dialog = AddDependencyDialog(
            ["main"],
            available_packages=[
                {"name": "requests", "version": "2.32.3", "module": "requests"},
                {"name": "selenium", "version": "4.20.0", "module": "selenium"},
            ],
        )
        self.addCleanup(dialog.deleteLater)

        self.assertEqual(dialog.package_list.count(), 3)
        dialog.package_search.setText("selen")
        self.app.processEvents()
        self.assertEqual(dialog.package_list.count(), 1)

        dialog.package_list.setCurrentRow(0)
        self.assertEqual(dialog.module_input.text(), "selenium")
        self.assertEqual(dialog.distribution_input.text(), "selenium")

    def test_add_dialog_marks_tkinter_as_standard_library(self):
        dialog = AddDependencyDialog(["main"])
        self.addCleanup(dialog.deleteLater)
        dialog.package_search.setText("tkinter")
        self.app.processEvents()

        self.assertEqual(dialog.package_list.count(), 1)
        dialog.package_list.setCurrentRow(0)
        self.assertEqual(dialog.dependency()["source"], "stdlib")
        self.assertEqual(dialog.delivery_combo.currentData(), "bundled")

    def test_extension_manifest_dialog_forces_external_delivery(self):
        dialog = AddDependencyDialog(
            ["main"],
            available_packages=[{"name": "requests", "version": "2.32.3", "module": "requests"}],
            extension_manifest=True,
        )
        self.addCleanup(dialog.deleteLater)

        self.assertEqual(dialog.delivery_combo.currentData(), "external")
        self.assertFalse(dialog.delivery_combo.isEnabled())

    def test_extension_list_includes_requested_package_versions(self):
        text = PackageManagerPage._extension_modules(
            {
                "manifest": {
                    "requested_dependencies": [
                        {"module": "requests", "version": "2.32.3"},
                        {"module": "selenium", "version": "4.20.0"},
                    ]
                }
            }
        )

        self.assertEqual(text, "requests 2.32.3、selenium 4.20.0")

    def test_extension_list_includes_all_distribution_versions(self):
        text = PackageManagerPage._extension_distributions(
            {
                "manifest": {
                    "distributions": [
                        {"name": "requests", "version": "2.32.3"},
                        {"name": "urllib3", "version": "2.2.2"},
                    ]
                }
            }
        )

        self.assertEqual(text, "requests 2.32.3、urllib3 2.2.2")

    def test_python_command_uses_the_platform_default_and_is_restorable(self):
        expected = "python" if os.name == "nt" else "python3"
        self.assertEqual(self.page.get_state()["python_command"], expected)

        self.page.restore_state({"python_command": r"D:\Python37\python.exe"})

        self.assertEqual(self.page.python_command_input.text(), r"D:\Python37\python.exe")

    def test_environment_scan_uses_the_selected_python_runtime_payload(self):
        runtime, packages = PackageManagerPage._parse_environment_scan_output(
            json.dumps(
                {
                    "python": "3.7.3",
                    "executable": r"D:\Python37\python.exe",
                    "architecture": "32bit",
                    "packages": [
                        {
                            "name": "selenium-wire",
                            "version": "5.1.0",
                            "modules": ["seleniumwire"],
                        }
                    ],
                }
            )
        )

        self.assertEqual(runtime["python"], "3.7.3")
        self.assertEqual(packages[0]["module"], "seleniumwire")
        self.page._environment_packages = packages
        self.assertTrue(self.page._module_is_available("seleniumwire", "selenium-wire"))

    def test_dependency_commands_use_prominent_button_styles(self):
        self.assertEqual(self.page.add_button.text(), "新增库")
        self.assertEqual(self.page.save_button.text(), "保存基础清单")
        self.assertIn("#475569", self.page.save_button.styleSheet())

    def test_generates_selected_spec_files_from_saved_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page = PackageManagerPage(project_root=root)
            self.addCleanup(page.deleteLater)
            page._target_checks["crpa_launcher"].setChecked(False)
            page._target_checks["crpa_json"].setChecked(False)
            page._dependencies.append(
                {
                    "module": "selenium",
                    "distribution": "selenium",
                    "collect": "all",
                    "targets": ["main"],
                    "source": "manual",
                }
            )
            page._draft_dirty = True

            page._generate_specs()

            main_spec = root / "main.spec"
            self.assertTrue(main_spec.exists())
            self.assertFalse((root / "crpa_launcher.spec").exists())
            self.assertIn('bundled_import_roots("main", PROJECT_ROOT)', main_spec.read_text(encoding="utf-8"))
            self.assertIn('"module": "selenium"', (root / "config" / "dynamic_imports.json").read_text(encoding="utf-8"))

    def test_external_dependency_is_not_added_to_bundled_spec_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page = PackageManagerPage(project_root=root)
            self.addCleanup(page.deleteLater)
            page._dependencies = [
                {
                    "module": "selenium",
                    "distribution": "selenium",
                    "collect": "all",
                    "delivery": "external",
                    "targets": ["main", "crpa_launcher"],
                    "source": "manual",
                }
            ]

            self.assertTrue(page._save_manifest())

            self.assertNotIn("selenium", bundled_import_roots("main", root))

    def test_import_automatically_merges_the_archive(self):
        result = {
            "version": "current",
            "created_initial_environment": True,
            "added_distributions": ["requests"],
            "updated_distributions": [],
        }
        thread = ExtensionArchiveImportThread(
            r"D:\received\requests.zip", self.page._extension_runtime_root()
        )
        with patch(
            "ui.design.package_manager_page.import_extension_archive",
            return_value=result,
        ) as import_archive, patch.object(self.page, "_refresh_extensions"):
            thread.run()
            self.page._extension_import_thread = thread
            self.page._on_extension_import_thread_finished()

        import_archive.assert_called_once_with(
            r"D:\received\requests.zip", self.page._extension_runtime_root()
        )
        self.assertIn("自动创建当前扩展环境", self.page.status_label.text())

    def test_extensions_tab_shows_current_loaded_environment_and_auto_import_action(self):
        self.assertEqual(self.page.extensions_table.horizontalHeaderItem(0).text(), "包名")
        self.assertEqual(self.page.extension_build_button.text(), "生成扩展包")
        self.assertEqual(self.page.extension_import_button.text(), "导入并自动合并")

    def test_report_panel_starts_collapsed_and_opens_for_reports(self):
        self.assertTrue(self.page.report_panel.isHidden())
        self.assertFalse(self.page.report_toggle.isChecked())

        self.page._show_report_panel()
        self.app.processEvents()

        self.assertTrue(self.page.report_toggle.isChecked())
        self.assertFalse(self.page.report_panel.isHidden())

    def test_current_extension_table_shows_loaded_root_and_distribution_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            version_root = get_extensions_root(root) / "versions" / "current"
            site_packages = version_root / SITE_PACKAGES_DIRECTORY
            site_packages.mkdir(parents=True)
            (version_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "version": "current",
                        "runtime": runtime_identity(),
                        "requested_dependencies": [{"module": "requests", "version": "2.32.3"}],
                        "distributions": [
                            {"name": "requests", "version": "2.32.3"},
                            {"name": "urllib3", "version": "2.2.2"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            set_active_extension("current", root)
            self.page._extension_runtime_root = lambda: root
            self.page._refresh_extensions()

            self.assertEqual(self.page.extensions_table.rowCount(), 2)
            self.assertEqual(self.page.extensions_table.item(0, 0).text(), "requests")
            self.assertEqual(self.page.extensions_table.item(0, 1).text(), "2.32.3")
            self.assertEqual(self.page.extensions_table.item(0, 2).text(), "根包")
            self.assertEqual(self.page.extensions_table.item(1, 0).text(), "urllib3")
            self.assertEqual(self.page.extensions_table.item(1, 2).text(), "依赖")

    def test_unexpected_extension_finalization_error_is_reported_and_preserves_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            staging_root = Path(directory) / ".staging-test"
            staging_root.mkdir()
            self.page._extension_build_context = {
                "version": "20260717-test",
                "staging_root": staging_root,
            }
            with patch(
                "ui.design.package_manager_page.finalize_extension_build",
                side_effect=OSError("file is locked"),
            ):
                self.page._on_extension_process_finished(0, 0)

            self.assertIn("未预期错误", self.page.status_label.text())
            self.assertIn("OSError", self.page.report_view.toPlainText())
            self.assertIn("暂存目录已保留", self.page.report_view.toPlainText())
            self.assertTrue(staging_root.exists())


if __name__ == "__main__":
    unittest.main()
