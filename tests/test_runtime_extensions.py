import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from core.packaging.external_extensions import (
    _LOCAL_COPY_SCRIPT,
    copy_installed_arguments,
    ExtensionBuildError,
    ExtensionVersionConflict,
    discard_extension_build,
    finalize_extension_build,
    import_extension_archive,
    merge_imported_extension,
    _promote_directory,
    prepare_extension_build,
)
from core.runtime_extensions import (
    SITE_PACKAGES_DIRECTORY,
    activate_external_extensions,
    active_extension_info,
    delete_extension_version,
    get_extensions_root,
    list_imported_extensions,
    runtime_identity,
    set_active_extension,
)


class RuntimeExtensionTests(unittest.TestCase):
    @staticmethod
    def _write_distribution(site_packages, distribution, version, module_name, value):
        package = site_packages / module_name
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("VALUE = {!r}\n".format(value), encoding="utf-8")
        metadata_directory = site_packages / "{}-{}.dist-info".format(distribution, version)
        metadata_directory.mkdir()
        (metadata_directory / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: {}\nVersion: {}\n".format(distribution, version),
            encoding="utf-8",
        )
        (metadata_directory / "RECORD").write_text(
            "{}/__init__.py,,\n{}/METADATA,,\n{}/RECORD,,\n".format(
                module_name, metadata_directory.name, metadata_directory.name
            ),
            encoding="utf-8",
        )

    def _create_packaged_version(self, root, version, dependencies, distributions):
        extension_root = get_extensions_root(root)
        version_root = extension_root / "versions" / version
        site_packages = version_root / SITE_PACKAGES_DIRECTORY
        site_packages.mkdir(parents=True)
        for distribution in distributions:
            self._write_distribution(site_packages, *distribution)
        (version_root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "version": version,
                    "runtime": runtime_identity(),
                    "requested_dependencies": dependencies,
                }
            ),
            encoding="utf-8",
        )
        return version_root, site_packages

    def _create_version(self, root, version, module_name="demo_extension"):
        extension_root = get_extensions_root(root)
        version_root = extension_root / "versions" / version
        site_packages = version_root / SITE_PACKAGES_DIRECTORY
        package = site_packages / module_name
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("VALUE = 'external'\n", encoding="utf-8")
        (version_root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "version": version,
                    "runtime": runtime_identity(),
                    "requested_dependencies": [{"module": module_name}],
                }
            ),
            encoding="utf-8",
        )
        return version_root, site_packages

    def test_active_extension_is_added_to_import_path(self):
        module_name = "demo_runtime_extension"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _version_root, site_packages = self._create_version(root, "20260717-01", module_name)
            set_active_extension("20260717-01", root)
            info = activate_external_extensions(root)

            module = importlib.import_module(module_name)

        self.assertTrue(info["activated"])
        self.assertEqual(module.VALUE, "external")
        self.assertIn(str(site_packages), sys.path)
        sys.modules.pop(module_name, None)
        while str(site_packages) in sys.path:
            sys.path.remove(str(site_packages))

    def test_imported_extension_archive_is_automatically_merged_into_current_environment(self):
        with tempfile.TemporaryDirectory() as source_directory, tempfile.TemporaryDirectory() as target_directory:
            source_root = Path(source_directory)
            extension_root = get_extensions_root(source_root)
            version = "20260717-02"
            staging_root = extension_root / (".staging-" + version)
            staging_site_packages = staging_root / SITE_PACKAGES_DIRECTORY
            staging_site_packages.mkdir(parents=True)
            (staging_site_packages / "archive_extension.py").write_text("VALUE = 2\n", encoding="utf-8")
            context = {
                "version": version,
                "runtime_root": str(source_root),
                "extension_root": extension_root,
                "staging_root": staging_root,
                "staging_site_packages": staging_site_packages,
                "version_root": extension_root / "versions" / version,
                "runtime": runtime_identity(),
                "dependencies": [{"module": "archive_extension", "distribution": "archive-extension"}],
            }

            built = finalize_extension_build(context, activate=True)
            archive_exists = built["archive_path"].is_file()
            archive_name = built["archive_path"].name
            source_version_exists = (extension_root / "versions" / version).exists()
            target_root = Path(target_directory)
            imported = import_extension_archive(built["archive_path"], target_root)
            active_version = active_extension_info(target_root)["version"]
            remaining_imports = list_imported_extensions(target_root)

        self.assertFalse(built["activated"])
        self.assertTrue(archive_exists)
        self.assertEqual(archive_name, "archive_extension.zip")
        self.assertFalse(source_version_exists)
        self.assertTrue(imported["auto_merged"])
        self.assertTrue(imported["created_initial_environment"])
        self.assertEqual(active_version, "current")
        self.assertEqual(remaining_imports, [])

    def test_imported_package_archive_merges_current_extension_and_replaces_confirmed_version(self):
        with tempfile.TemporaryDirectory() as source_directory, tempfile.TemporaryDirectory() as target_directory:
            source_root = Path(source_directory)
            target_root = Path(target_directory)
            active_dependencies = [{"module": "merge_selenium", "distribution": "selenium"}]
            self._create_packaged_version(
                target_root,
                "20260717-active",
                active_dependencies,
                [
                    ("selenium", "4.20.0", "merge_selenium", "selenium"),
                    ("urllib3", "1.26.18", "merge_shared", "old-urllib3"),
                ],
            )
            set_active_extension("20260717-active", target_root)

            source_extension_root = get_extensions_root(source_root)
            source_version = "20260717-requests"
            staging_root = source_extension_root / (".staging-" + source_version)
            staging_site_packages = staging_root / SITE_PACKAGES_DIRECTORY
            staging_site_packages.mkdir(parents=True)
            self._write_distribution(staging_site_packages, "requests", "2.32.3", "merge_requests", "requests")
            self._write_distribution(staging_site_packages, "urllib3", "2.2.2", "merge_shared", "new-urllib3")
            context = {
                "version": source_version,
                "runtime_root": str(source_root),
                "extension_root": source_extension_root,
                "staging_root": staging_root,
                "staging_site_packages": staging_site_packages,
                "version_root": source_extension_root / "versions" / source_version,
                "runtime": runtime_identity(),
                "dependencies": [{"module": "merge_requests", "distribution": "requests"}],
            }
            built = finalize_extension_build(context, activate=True)
            with zipfile.ZipFile(str(built["archive_path"]), "r") as archive:
                source_manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            self.assertEqual(source_manifest["requested_dependencies"][0]["version"], "2.32.3")

            imported = import_extension_archive(built["archive_path"], target_root)
            merged_site_packages = imported["version_root"] / SITE_PACKAGES_DIRECTORY
            merged_manifest = json.loads(
                (imported["version_root"] / "manifest.json").read_text(encoding="utf-8")
            )

            self.assertTrue(imported["merged_in_place"])
            self.assertFalse(imported["created_initial_environment"])
            self.assertEqual(active_extension_info(target_root)["version"], "20260717-active")
            self.assertEqual(list_imported_extensions(target_root), [])
            self.assertEqual(imported["updated_distributions"][0]["name"], "urllib3")
            self.assertEqual(
                [item.name for item in (get_extensions_root(target_root) / "versions").iterdir()],
                ["20260717-active"],
            )
            self.assertEqual((merged_site_packages / "merge_selenium" / "__init__.py").read_text(encoding="utf-8"), "VALUE = 'selenium'\n")
            self.assertEqual((merged_site_packages / "merge_requests" / "__init__.py").read_text(encoding="utf-8"), "VALUE = 'requests'\n")
            self.assertEqual((merged_site_packages / "merge_shared" / "__init__.py").read_text(encoding="utf-8"), "VALUE = 'new-urllib3'\n")
            self.assertFalse((merged_site_packages / "urllib3-1.26.18.dist-info").exists())
            self.assertEqual(
                {item["module"] for item in merged_manifest["requested_dependencies"]},
                {"merge_selenium", "merge_requests"},
            )

    def test_local_extension_copy_command_does_not_install_from_a_package_index(self):
        context = {
            "staging_site_packages": Path("C:/extensions/site-packages"),
            "requirements": ["selenium"],
        }

        arguments = copy_installed_arguments(context)

        self.assertEqual(arguments[0], "-c")
        self.assertNotIn("install", arguments)
        self.assertIn('"pip", "show"', arguments[1])

    def test_local_extension_copy_supports_linux_packages_without_file_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper_root = root / "helpers"
            pip_package = helper_root / "pip"
            pip_package.mkdir(parents=True)
            (pip_package / "__init__.py").write_text("", encoding="utf-8")
            (helper_root / "pkg_resources.py").write_text(
                "def get_distribution(name):\n    raise LookupError(name)\n",
                encoding="utf-8",
            )

            system_site_packages = root / "dist-packages"
            package = system_site_packages / "idna"
            metadata = system_site_packages / "idna-3.3.dist-info"
            package.mkdir(parents=True)
            metadata.mkdir()
            (package / "__init__.py").write_text("VALUE = 'local'\n", encoding="utf-8")
            (metadata / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: idna\nVersion: 3.3\n",
                encoding="utf-8",
            )
            pip_output = (
                "Name: idna\nVersion: 3.3\nLocation: {}\nRequires:\nFiles:\n".format(
                    system_site_packages
                )
            )
            (pip_package / "__main__.py").write_text(
                "print({!r})\n".format(pip_output),
                encoding="utf-8",
            )

            target = root / "target"
            environment = os.environ.copy()
            existing_python_path = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = str(helper_root) + (
                os.pathsep + existing_python_path if existing_python_path else ""
            )
            completed = subprocess.run(
                [sys.executable, "-c", _LOCAL_COPY_SCRIPT, str(target), json.dumps(["idna"])],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                env=environment,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((target / "idna" / "__init__.py").is_file())
            self.assertTrue((target / "idna-3.3.dist-info" / "METADATA").is_file())

    def test_discard_extension_build_ignores_missing_staging_path(self):
        self.assertIsNone(discard_extension_build({}))

    def test_promote_directory_retries_a_short_windows_file_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / ".staging-test"
            destination = root / "final"
            source.mkdir()
            (source / "payload.txt").write_text("ready", encoding="utf-8")
            original_replace = Path.replace
            calls = []

            def replace_with_one_lock(path, target):
                calls.append((path, target))
                if len(calls) == 1:
                    raise PermissionError("directory is locked")
                return original_replace(path, target)

            with patch.object(Path, "replace", new=replace_with_one_lock), patch(
                "core.packaging.external_extensions.time.sleep"
            ) as sleep:
                _promote_directory(source, destination, "测试提升", attempts=2)

            self.assertEqual(len(calls), 2)
            sleep.assert_called_once_with(0.25)
            self.assertTrue((destination / "payload.txt").is_file())

    def test_standard_library_cannot_be_built_as_external_extension(self):
        with self.assertRaisesRegex(ExtensionBuildError, "标准库"):
            prepare_extension_build(
                "python",
                [{"module": "tkinter", "distribution": "tkinter"}],
            )

    def test_active_extension_version_cannot_be_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._create_version(root, "20260717-03")
            self._create_version(root, "20260717-02")
            set_active_extension("20260717-03", root)

            with self.assertRaisesRegex(ValueError, "当前启用"):
                delete_extension_version("20260717-03", root)
            delete_extension_version("20260717-02", root)

            self.assertFalse((get_extensions_root(root) / "versions" / "20260717-02").exists())
