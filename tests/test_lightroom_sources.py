import _isolate  # noqa: F401 -- aucune ecriture dans les reglages reels
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

import lightroom_bridge
from fm_visionneuse import focus

_app = QApplication.instance() or QApplication([])

UUID = "12345678-1234-1234-1234-123456789ABC"
DIGEST = "a" * 32


class LightroomSourcesTest(unittest.TestCase):
    """Proxy = apercu developpe de la pyramide Lightroom (le plus petit d'au moins 640 px) ; image
    en focus = le plus grand, jamais une vignette ; previews.db lue meme avec son journal."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.photo = self.base / "photos" / "photo.jpg"
        self.photo.parent.mkdir()
        QImage(30, 20, QImage.Format_RGB32).save(str(self.photo), "JPEG")
        self.catalog = self.base / "cat.lrcat"
        (self.photo.parent / lightroom_bridge.MARKER).write_text(
            json.dumps({"catalog": str(self.catalog)}), encoding="utf-8")
        self.store = self.base / "cat Previews.lrdata"
        self.cache = self.base / "cache"
        (self.cache / "images").mkdir(parents=True)
        self.info = {"uuid": "u", "local_id": 7, "revision": "1:1", "orientation": "AB"}
        lightroom_bridge._preview_path_cache.clear()
        self.addCleanup(lightroom_bridge._preview_path_cache.clear)
        self.addCleanup(lambda: lightroom_bridge._drop_previews_conn(self.store / "previews.db"))
        for patcher in (patch.object(lightroom_bridge, "_catalog_photo", return_value=self.info),
                        patch.object(lightroom_bridge, "_cache_root", return_value=self.cache)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _pyramid(self, sides, journal=False):
        self.store.mkdir(exist_ok=True)
        database = self.store / "previews.db"
        db = sqlite3.connect(database)
        db.executescript("""CREATE TABLE ImageCacheEntry (imageId, uuid, digest, orientation);
            CREATE TABLE PyramidLevel (uuid, digest, level, longDimension);""")
        db.execute("INSERT INTO ImageCacheEntry VALUES (7.0, ?, ?, 'AB')", (UUID, DIGEST))
        folder = self.store / UUID[0] / UUID[:4]
        folder.mkdir(parents=True, exist_ok=True)
        for level, side in enumerate(sides, 1):
            db.execute("INSERT INTO PyramidLevel VALUES (?, ?, ?, ?)", (UUID, DIGEST, level, float(side)))
            QImage(side, side * 2 // 3, QImage.Format_RGB32).save(str(folder / f"{UUID}-{DIGEST}_{side}"), "JPEG")
        db.commit()
        if journal:
            # Copie prise EN PLEINE ECRITURE : journal "chaud", comme celui que Lightroom laisse.
            # Une ouverture en lecture seule simple echoue alors ("readonly database").
            copy = self.base / "copy.db"
            db.execute("PRAGMA cache_size=1")
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE remplissage (x)")
            db.executemany("INSERT INTO remplissage VALUES (?)", [("x" * 500,)] * 400)
            db.execute("UPDATE ImageCacheEntry SET orientation='AB'")
            shutil.copyfile(database, copy)
            shutil.copyfile(str(database) + "-journal", str(copy) + "-journal")
            db.rollback()
            db.close()
            os.replace(copy, database)
            os.replace(str(copy) + "-journal", str(database) + "-journal")
        else:
            db.close()

    def test_proxy_and_fullscreen_levels(self):
        self._pyramid([320, 644, 1288, 2576])
        proxy, text = lightroom_bridge.proxy_file(self.photo)
        self.assertTrue(proxy.name.endswith("_644"))
        self.assertIn("644 px", text)
        large, text = lightroom_bridge.large_file(self.photo)
        self.assertTrue(large.name.endswith("_2576"))
        self.assertIn("Lightroom", lightroom_bridge.fullscreen_source(self.photo))

    def test_previews_db_with_hot_journal_is_still_read(self):
        self._pyramid([320, 644, 1288, 2576], journal=True)
        self.assertTrue((self.store / "previews.db-journal").is_file())
        plain = sqlite3.connect((self.store / "previews.db").as_uri() + "?mode=ro", uri=True)
        try:
            with self.assertRaises(sqlite3.OperationalError):     # ce qui arrivait au code d'avant
                plain.execute("SELECT * FROM ImageCacheEntry").fetchall()
        finally:
            plain.close()
        proxy = lightroom_bridge.proxy_file(self.photo)
        self.assertIsNotNone(proxy)
        self.assertTrue(proxy[0].name.endswith("_644"))

    def test_only_thumbnails_never_reach_fullscreen(self):
        self._pyramid([160, 320])
        self.assertIsNone(lightroom_bridge.large_file(self.photo))
        self.assertEqual(lightroom_bridge.fullscreen_source(self.photo), "Image originale")
        self.assertIn("320 px", lightroom_bridge.proxy_source(self.photo))

    def test_without_lightroom_preview_the_application_proxy_is_named(self):
        self.assertIsNone(lightroom_bridge.proxy_file(self.photo))
        app_proxy = lightroom_bridge._application_preview_path(
            self.photo, self.photo.stat().st_mtime, self.catalog)
        QImage(64, 40, QImage.Format_RGB32).save(str(app_proxy), "JPEG")
        self.assertTrue(lightroom_bridge.proxy_source(self.photo).startswith("Application"))

    def test_missing_proxy_is_created_by_the_application(self):
        # Photo sans apercu Lightroom ni proxy : la planche / la pellicule le creent (plus de case « JPG »).
        self.assertIsNone(lightroom_bridge.proxy_file(self.photo))
        with patch("previews._decode_2d_image", return_value=QImage(60, 40, QImage.Format_RGB32)):
            made = lightroom_bridge.ensure_proxy_path(self.photo)
        self.assertIsNotNone(made)
        self.assertTrue(made.is_file())
        self.assertTrue(lightroom_bridge.proxy_source(self.photo).startswith("Application"))

    def test_viewer_parameters_list_both_sources(self):
        self._pyramid([320, 644, 1288, 2576])
        rows = dict(focus.image_sources(self.photo, self.photo.stat().st_mtime))
        self.assertIn("644 px", rows["Source du proxy"])
        self.assertIn("2576 px", rows["Source de l'aperçu plein écran"])


class ProxySourceTipTest(unittest.TestCase):
    """Encart "Source du proxy" : Maj + survol d'une diapositive."""

    def _host(self):
        host = QWidget()
        host.resize(300, 200)
        host.show()
        self.addCleanup(host.deleteLater)
        return host

    def test_shift_hover_shows_the_proxy_source(self):
        host = self._host()
        path = "C:/photos/a.jpg"
        focus._PROXY_SOURCES[path] = "Lightroom · aperçu développé 644 px (Previews.lrdata)"
        self.addCleanup(focus._PROXY_SOURCES.pop, path, None)
        tip = focus.ProxySourceTip(host, lambda pos: path if pos.x() < 150 else None)
        tip.update_at(host.mapToGlobal(QPoint(40, 40)), shift=True)
        self.assertTrue(tip._badge.isVisible())
        self.assertIn("Source du proxy", tip._badge.text())
        self.assertIn("644 px", tip._badge.text())
        tip.update_at(host.mapToGlobal(QPoint(40, 40)), shift=False)     # Maj relachee
        self.assertFalse(tip._badge.isVisible())
        tip.update_at(host.mapToGlobal(QPoint(200, 40)), shift=True)     # hors d'une diapositive
        self.assertFalse(tip._badge.isVisible())

    def test_source_arriving_later_updates_the_tip(self):
        host = self._host()
        path = str(Path(tempfile.gettempdir()) / "b.jpg")
        self.addCleanup(focus._PROXY_SOURCES.pop, path, None)
        tip = focus.ProxySourceTip(host, lambda pos: path)
        with (patch.object(lightroom_bridge, "is_managed", return_value=True),
              patch.object(lightroom_bridge, "request_sources") as ask):
            tip.update_at(host.mapToGlobal(QPoint(10, 10)), shift=True)
        ask.assert_called_once()
        self.assertIn("lecture", tip._badge.text())
        tip._on_sources(path, "Lightroom · rendu du module SDK 2560 px", "x")
        self.assertIn("2560 px", tip._badge.text())


if __name__ == "__main__":
    unittest.main()
