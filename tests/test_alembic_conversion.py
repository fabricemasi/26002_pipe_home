import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "conversion", Path(__file__).resolve().parents[1] / "tools" / "convert_legacy_alembic.py")
conversion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conversion)


class AlembicConversionTests(unittest.TestCase):
    def fixture(self, folder):
        root = folder / "assets"
        staging = folder / "staging"
        root.mkdir()
        staging.mkdir()
        source = root / "asset.abc"
        target = staging / "asset.abc"
        source.write_bytes(conversion.HDF5 + b"original")
        target.write_bytes(b"Ogawa\x00\x00\x00converted")
        item = {"source": str(source), "converted": str(target), "status": "validated",
                "source_sha256": conversion.digest(source), "converted_sha256": conversion.digest(target)}
        manifest = folder / "manifest.json"
        manifest.write_text(json.dumps({"root": str(root), "staging": str(staging), "files": [item]}))
        return source, target, manifest

    def test_publish_keeps_exact_backup_and_same_source_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target, manifest = self.fixture(Path(tmp))
            original = source.read_bytes()
            conversion.publish(manifest)
            self.assertEqual(source.read_bytes(), target.read_bytes())
            self.assertEqual(source.with_name("asset.abc.hdf5.bak").read_bytes(), original)
            self.assertEqual(json.loads(manifest.read_text())["files"][0]["status"], "published")
            self.assertFalse(source.with_name("asset.abc.ogawa.pending").exists())

    def test_changed_source_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, _, manifest = self.fixture(Path(tmp))
            source.write_bytes(conversion.HDF5 + b"changed")
            with self.assertRaisesRegex(RuntimeError, "Source changed"):
                conversion.publish(manifest)
            self.assertTrue(source.read_bytes().endswith(b"changed"))

    def test_existing_backup_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, _, manifest = self.fixture(Path(tmp))
            backup = source.with_name("asset.abc.hdf5.bak")
            backup.write_bytes(b"precious")
            with self.assertRaisesRegex(RuntimeError, "Backup already exists"):
                conversion.publish(manifest)
            self.assertEqual(backup.read_bytes(), b"precious")
            self.assertEqual(conversion.header(source), conversion.HDF5)

    def test_structure_only_ignores_library_version(self):
        self.assertEqual(conversion.structure(b"  using Alembic : 1.5\nmesh\n"),
                         conversion.structure(b"  using Alembic : 1.8\nmesh\n"))
        self.assertNotEqual(conversion.structure(b"mesh: samples=1\n"),
                            conversion.structure(b"mesh: samples=2\n"))


if __name__ == "__main__":
    unittest.main()
