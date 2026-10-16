import _isolate  # noqa: F401 -- aucune ecriture dans les reglages reels
import tempfile
import unittest
from pathlib import Path

import browser_core


class ProjectConfigDefaultsTest(unittest.TestCase):
    def setUp(self):
        browser_core.invalidate_project_columns_cache()

    def tearDown(self):
        browser_core.invalidate_project_columns_cache()

    def test_new_direct_project_inherits_its_root_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "PROG"
            project = root / "projet_a_venir"
            project.mkdir(parents=True)
            config = {
                "columns": [],
                "work_dir": {"type": "standard", "show_dirs": True, "show_files": True},
                "set_enabled": False,
                "focus_enabled": False,
                "in_over_out_enabled": False,
            }

            browser_core.save_project_columns_defaults(root, config)

            self.assertEqual(browser_core.load_project_columns(project), {
                "columns": [],
                "work_dir": {
                    "type": "standard", "show_dirs": True, "show_files": True,
                    "omit_dirs": [], "omit_files": [],
                },
                "set_enabled": False,
                "focus_enabled": False,
                "in_over_out_enabled": False,
            })

    def test_project_config_overrides_its_root_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "PROG"
            project = root / "projet_personnalise"
            project.mkdir(parents=True)
            browser_core.save_project_columns_defaults(root, {
                "columns": [], "work_dir": {"type": "standard"},
                "set_enabled": False, "focus_enabled": False, "in_over_out_enabled": False,
            })
            browser_core.save_project_columns(project, {
                "columns": [], "work_dir": {"type": "logiciel"},
                "set_enabled": True, "focus_enabled": True, "in_over_out_enabled": True,
            })

            self.assertEqual(browser_core.load_project_columns(project)["work_dir"]["type"], "logiciel")
            self.assertTrue(browser_core.load_project_columns(project)["set_enabled"])


if __name__ == "__main__":
    unittest.main()
