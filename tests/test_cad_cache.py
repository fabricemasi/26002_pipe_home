"""Cache disque des dessins DXF / DWG convertis (`fm_cad/cad_cache.py`, demande de l'utilisateur : rouvrir un gros DWG
sans refaire ODA, ezdxf ni la conversion) : copie reprise si rien n'a change, refaite sinon, jamais d'erreur, taille
bornee, jamais le vrai dossier de l'utilisateur en test."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import fm_board  # noqa: E402,F401  (avant fm_cad.cad_import : ordre d'import de l'appli)
from fm_cad import cad_cache, cad_import  # noqa: E402

ISOLATED = os.environ.get("PIPELINE_CAD_CACHE_DIR")                       # pose par _isolate


class CadCacheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from fm_cad import cad_import
        cls._native = cad_import.NATIVE_BLOCKS
        cad_import.NATIVE_BLOCKS = False        # ces tests portent sur l'import ECLATE (blocs natifs : test_cad_blocks)

    @classmethod
    def tearDownClass(cls):
        from fm_cad import cad_import
        cad_import.NATIVE_BLOCKS = cls._native
        super().tearDownClass()

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.cache = self.dir / "cache"
        patcher = mock.patch.dict(os.environ, {"PIPELINE_CAD_CACHE_DIR": str(self.cache)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def drawing(self, name="plan.dxf", length=40):
        ezdxf = __import__("ezdxf")
        doc = ezdxf.new("R2018")
        doc.modelspace().add_line((0, 0), (length, 0))
        doc.modelspace().add_circle((0, 0), 5)
        path = self.dir / name
        doc.saveas(path)
        return path

    def files(self):
        return sorted(p.name for p in self.cache.glob("*" + cad_cache.SUFFIX)) if self.cache.is_dir() else []

    def test_tests_never_use_the_users_folder(self):
        self.assertTrue(ISOLATED and Path(ISOLATED).is_relative_to(_isolate._TMP))
        self.assertEqual(cad_cache.folder(), self.cache)

    def test_second_open_reuses_the_copy_without_reading(self):
        path = self.drawing()
        data, report = cad_import.open_drawing(path)
        self.assertFalse(report.get("cached"))
        self.assertEqual(len(self.files()), 1)
        with mock.patch.object(cad_import, "read_drawing", side_effect=AssertionError("relu")):
            again, report2 = cad_import.open_drawing(path)
        self.assertTrue(report2["cached"])
        self.assertEqual(again, data)                                       # memes donnees, deja normalisees
        self.assertEqual([i["type"] for i in again["items"]], ["cad_line", "cad_circle"])
        self.assertIn("copie convertie gardée", cad_import.describe(report2))

    def test_modified_drawing_is_converted_again_and_old_copy_removed(self):
        path = self.drawing(length=40)
        cad_import.open_drawing(path)
        first = self.files()
        time.sleep(0.02)
        self.drawing(length=80)                                             # meme fichier, contenu change
        os.utime(path, ns=(time.time_ns(), time.time_ns() + 10_000_000))
        data, report = cad_import.open_drawing(path)
        self.assertFalse(report.get("cached"))
        line = next(i for i in data["items"] if i["type"] == "cad_line")
        fresh = next(i for i in cad_import.read_drawing(path)[0]["items"] if i["type"] == "cad_line")
        self.assertEqual((line["p1"], line["p2"]), (fresh["p1"], fresh["p2"]))  # le nouveau contenu
        self.assertEqual(len(self.files()), 1)                              # une seule copie par dessin
        self.assertNotEqual(self.files(), first)

    def test_changed_converter_means_a_new_conversion(self):
        path = self.drawing()
        cad_import.open_drawing(path)
        with mock.patch.object(cad_cache, "_converter_stamp", return_value="autre convertisseur"):
            _data, report = cad_import.open_drawing(path)
        self.assertFalse(report.get("cached"))

    def test_damaged_copy_or_forbidden_folder_never_raise(self):
        path = self.drawing()
        cad_import.open_drawing(path)
        (self.cache / self.files()[0]).write_bytes(b"abime")
        _data, report = cad_import.open_drawing(path)                      # relu, copie refaite
        self.assertFalse(report.get("cached"))
        self.assertTrue(cad_import.open_drawing(path)[1]["cached"])
        blocker = self.dir / "fichier"
        blocker.write_text("x")
        with mock.patch.dict(os.environ, {"PIPELINE_CAD_CACHE_DIR": str(blocker / "sous")}):
            data, report = cad_import.open_drawing(self.drawing("autre.dxf"))
        self.assertEqual(len(data["items"]), 2)
        self.assertFalse(cad_cache.store(None, data, report))
        self.assertIsNone(cad_cache.load(None))
        self.assertIsNone(cad_cache.entry(self.dir / "absent.dwg"))

    def test_size_is_bounded_least_recently_opened_first(self):
        paths = [self.drawing(f"plan{n}.dxf") for n in range(3)]
        with mock.patch.object(cad_cache, "MAX_FILES", 2):
            cad_import.open_drawing(paths[0])
            cad_import.open_drawing(paths[1])
            for item in self.cache.iterdir():                           # plan0 ouvert il y a longtemps
                stamp = time.time() - (1000 if item.name == cad_cache.entry(paths[0])[1] else 10)
                os.utime(item, (stamp, stamp))
            cad_import.open_drawing(paths[2])
        names = self.files()
        self.assertEqual(len(names), 2)
        self.assertNotIn(cad_cache.entry(paths[0])[1], names)
        self.assertIn(cad_cache.entry(paths[2])[1], names)


if __name__ == "__main__":
    unittest.main()
