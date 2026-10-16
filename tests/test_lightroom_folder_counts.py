import _isolate  # noqa: F401 -- aucune ecriture dans les reglages reels
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import lightroom_bridge


class LightroomFolderCountsTest(unittest.TestCase):
    def test_counts_only_catalogued_media_recursively(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            shortcut = base / "Raccourci photos"
            event = shortcut / "2025" / "Evenement"
            event.mkdir(parents=True)
            catalog = base / "catalogue.lrcat"
            (shortcut / lightroom_bridge.MARKER).write_text(
                json.dumps({"catalog": str(catalog)}), encoding="utf-8")
            (event / "absente-du-catalogue.jpg").touch()
            with closing(sqlite3.connect(catalog)) as db, db:
                db.executescript("""
                    CREATE TABLE AgLibraryRootFolder (id_local INTEGER, absolutePath TEXT);
                    CREATE TABLE AgLibraryFolder (id_local INTEGER, pathFromRoot TEXT, rootFolder INTEGER);
                    CREATE TABLE AgLibraryFile (folder INTEGER, idx_filename TEXT);
                """)
                db.execute("INSERT INTO AgLibraryRootFolder VALUES (?, ?)", (1, str(shortcut)))
                db.executemany("INSERT INTO AgLibraryFolder VALUES (?, ?, ?)",
                               [(1, "", 1), (2, "2025/Evenement", 1)])
                db.executemany("INSERT INTO AgLibraryFile VALUES (?, ?)",
                               [(1, "racine.NEF"), (2, "photo1.CR2"), (2, "photo2.JPG"),
                                (2, "film.MP4"), (2, "document.pdf")])

            counts = lightroom_bridge.folder_media_counts([shortcut, event])
            self.assertEqual(counts[str(shortcut.resolve())], (3, 1))
            self.assertEqual(counts[str(event.resolve())], (2, 1))

    def test_unavailable_catalog_does_not_report_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "Photos"
            folder.mkdir()
            (folder / lightroom_bridge.MARKER).write_text(
                json.dumps({"catalog": str(Path(temp) / "missing.lrcat")}), encoding="utf-8")
            counts = lightroom_bridge.folder_media_counts([folder])
            self.assertNotIn(str(folder.resolve()), counts)


if __name__ == "__main__":
    unittest.main()
