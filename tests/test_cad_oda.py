"""ODA File Converter trouvé par le module CAD LUI-MÊME (`cad_export.oda_converter`), y compris dans son installation
standard (Program Files/ODA/ODAFileConverter <version>) : le 1er DWG ouvert était lu avant que le board ne pose
`ODA_PROVIDER` et disait ODA « introuvable » alors qu'il était installé (signalé 2026-10-31)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fm_cad import cad_export, cad_import  # noqa: E402


class OdaLookupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oda_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(setattr, cad_export, "ODA_PROVIDER", cad_export.ODA_PROVIDER)
        cad_export.ODA_PROVIDER = None                       # comme au 1er DWG ouvert

    def test_standard_install_is_found_newest_version_first(self):
        for version in ("ODAFileConverter 27.9.0", "ODAFileConverter 27.10.0", "ODAFileConverter 26.12.0"):
            exe = self.tmp / "ODA" / version / "ODAFileConverter.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"")
        env = {k: v for k, v in os.environ.items() if k != "ODA_FILE_CONVERTER"}
        env["ProgramFiles"] = str(self.tmp)
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(cad_export.shutil, "which",
                                                                              return_value=None):
            found = cad_export.oda_converter()
        self.assertEqual(Path(found).parent.name, "ODAFileConverter 27.10.0")

    def test_nothing_installed_gives_none(self):
        env = {k: v for k, v in os.environ.items() if k != "ODA_FILE_CONVERTER"}
        env["ProgramFiles"] = str(self.tmp)
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(cad_export.shutil, "which", return_value=None), \
                mock.patch.object(cad_export, "Path", side_effect=lambda *a: Path(self.tmp, "absent")
                                  if a == (r"C:\Program Files\ODA",) else Path(*a)):
            self.assertIsNone(cad_export.oda_converter())

    def test_real_dwg_opens_without_the_main_window(self):
        exe = cad_export.oda_converter()
        if not exe:
            self.skipTest("ODA File Converter absent")
        import ezdxf
        from ezdxf.addons import odafc
        doc = ezdxf.new()
        doc.modelspace().add_line((0, 0), (100, 50))
        ezdxf.options.set("odafc-addon", "win_exec_path", f'"{exe}"')
        with cad_export.oda_environment():
            odafc.export_dwg(doc, str(self.tmp / "essai.dwg"), version="R2018")
        ezdxf.options.set("odafc-addon", "win_exec_path", r"C:\nulle\part.exe")   # chemin oublié : à retrouver
        _data, report = cad_import.read_drawing(self.tmp / "essai.dwg")
        self.assertIn("1 objet", cad_import.describe(report))


if __name__ == "__main__":
    unittest.main()
