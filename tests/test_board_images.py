"""Images du board : decodage en fond, niveaux reduits, lissage aux petits zooms, glisser-deposer externe
(navigateur, bureau). `python tests/run.py fm_miro`."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtCore import QMimeData, QPointF, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

import app_style  # noqa: E402
import fm_board as board  # noqa: E402
from fm_board import drop, export, model, serialization  # noqa: E402
from fm_board import ui as board_ui  # noqa: E402
from fm_miro import items  # noqa: E402

_PANES = []


def settle(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.005)


def checker(path, side=400):
    """Damier d'UN pixel : le pire cas du crenelage (bien reduit, il devient un gris uniforme)."""
    image = QImage(side, side, QImage.Format_RGB32)
    arr = np.frombuffer(image.bits(), np.uint32).reshape(side, image.bytesPerLine() // 4)[:, :side]
    yy, xx = np.mgrid[0:side, 0:side]
    arr[:] = np.where((xx + yy) % 2 == 0, 0xff000000, 0xffffffff)
    image.save(str(path))
    return path


def solid_png(color="red", side=12) -> bytes:
    image = QImage(side, side, QImage.Format_RGB32)
    image.fill(QColor(color))
    return drop.png_bytes(image)


class _BoardCase(unittest.TestCase):
    def setUp(self):
        app_style.apply_style(APP)
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = board.create_board_file(self.dir / "b")
        self.host = QWidget()
        self.host.resize(900, 600)
        self.pane = board_ui.BoardPane(self.host)
        self.pane.setGeometry(self.host.rect())
        self.pane.set_module("miro")
        self.assertTrue(self.pane.open(self.path))
        self.host.show()
        self.pane.show()
        settle(0.1)
        self.addCleanup(self._drop)

    def _drop(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        self.pane._autosave.stop()
        self.pane.deleteLater()
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def images(self):
        return [i for i in self.pane.scene.board_items() if i.kind == "image"]


class ImageLevelsTest(_BoardCase):
    def test_decoded_in_background_then_repainted(self):
        name = serialization.import_asset(self.path, checker(self.dir / "c.png", 300))
        item = self.pane.scene.add_new(model.new_item("image", asset=name, w=300, h=300))
        items._IMAGES.pop((str(self.path), name), None)
        with mock.patch.object(item, "update") as update:
            self.assertIsNone(items.image_levels(self.path, name, item))       # en cours : rien de bloquant
            self.assertTrue(items.wait_images())
            update.assert_called()
        levels = items.image_levels(self.path, name, item)
        self.assertEqual(levels[0].width(), 300)
        self.assertEqual([i.width() for i in levels], [300, 150, 75, 37])  # moities jusqu'a IMAGE_MIP_MIN
        self.assertIs(items.pick_level(levels, 140), levels[1])            # le plus petit niveau qui couvre
        self.assertIs(items.pick_level(levels, 160), levels[0])
        self.assertIs(items.pick_level(levels, 10), levels[-1])
        self.assertIs(items.pick_level(levels, 900), levels[0])

    def test_missing_asset_and_synchronous_callers(self):
        self.assertEqual(items.image_levels(self.path, "pas-un-asset.png", object()), [])
        self.assertIsNone(items.image_levels(self.path, "0123456789abcdef.png", mock.Mock()))   # fichier absent
        self.assertTrue(items.wait_images())
        self.assertEqual(items.image_levels(self.path, "0123456789abcdef.png", mock.Mock()), [])
        name = serialization.import_image_bytes(self.path, solid_png("red"))
        self.assertEqual(items.asset_pixmap(self.path, name).width(), 12)      # Design, Illustrator : synchrone

    def test_export_waits_for_nothing(self):
        name = serialization.import_image_bytes(self.path, solid_png("#00ff00", 40))
        items._IMAGES.pop((str(self.path), name), None)
        item = self.pane.scene.add_new(model.new_item("image", asset=name, w=40, h=40))
        image = export.render_items(self.pane.scene, [item], scale=1.0)
        self.assertEqual(QColor(image.pixel(image.width() // 2, image.height() // 2)).name(), "#00ff00")


class SmoothingTest(_BoardCase):
    """Damier d'un pixel vu de loin : gris uniforme (lisse), pas des motifs (crenelage du bilineaire seul : ecart
    moyen au gris ~32 sur 128 avant le correctif)."""

    def spread(self, zoom):
        name = serialization.import_asset(self.path, checker(self.dir / "c.png", 400))
        item = self.pane.scene.add_new(model.new_item("image", asset=name, w=400, h=400, x=0.3, y=0.7))
        self.pane.scene.clearSelection()
        view = self.pane.view
        view.set_zoom(zoom)
        view.center_on(item.sceneBoundingRect().center())
        view._zoom_settled()
        settle(0.05)
        self.assertTrue(items.wait_images())
        settle(0.1)
        shot = view.viewport().grab().toImage().convertToFormat(QImage.Format_RGB32)
        box = view.mapFromScene(item.mapToScene(item.content_rect())).boundingRect().adjusted(3, 3, -3, -3)
        arr = np.frombuffer(shot.constBits(), np.uint8).reshape(shot.height(), shot.bytesPerLine() // 4, 4)
        part = arr[box.top():box.bottom(), box.left():box.right(), 1].astype(int)
        self.assertGreater(part.size, 100)
        return abs(part - 128).mean()

    def test_far_zoom_is_smooth(self):
        self.assertLess(self.spread(0.13), 6.0)

    def test_mid_zoom_is_smooth(self):
        self.assertLess(self.spread(0.55), 6.0)

    def test_continuous_zoom_uses_reduced_levels(self):
        self.assertLess(self.spread(0.3), 6.0)
        self.pane.view._set_item_cache(False)               # zoom continu : sans image gardee, niveau reduit
        settle(0.1)
        self.assertTrue(self.images())


class ExternalDropTest(_BoardCase):
    def drop(self, mime, at=QPointF(120, -40)):
        return self.pane.view.drop_mime(mime, at)

    def placed_at(self, at):
        item = self.images()[-1]
        center = item.sceneBoundingRect().center()
        self.assertAlmostEqual(center.x(), at.x(), delta=2)
        self.assertAlmostEqual(center.y(), at.y(), delta=2)
        return item

    def test_local_file_from_the_desktop(self):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(checker(self.dir / "bureau.png", 40)))])
        self.assertTrue(drop.accepts(mime))
        self.assertTrue(self.drop(mime))
        self.placed_at(QPointF(120, -40))

    def test_raw_image_bytes_are_kept(self):
        mime = QMimeData()
        data = solid_png("blue", 30)
        mime.setData("image/png", data)
        self.assertTrue(drop.accepts(mime))
        self.assertTrue(self.drop(mime))
        item = self.placed_at(QPointF(120, -40))
        self.assertEqual(serialization.asset_path(self.path, item.data["asset"]).read_bytes(), data)

    def test_bitmap_of_the_drag(self):
        mime = QMimeData()
        image = QImage(200, 100, QImage.Format_RGB32)
        image.fill(QColor("red"))
        mime.setImageData(image)
        self.assertTrue(self.drop(mime))
        item = self.placed_at(QPointF(120, -40))
        self.assertAlmostEqual(item.data["w"] / item.data["h"], 2.0, places=2)

    def test_web_image_is_downloaded_in_background(self):
        mime = QMimeData()
        mime.setHtml('<html><body><img alt="x" src="https://example.test/photo.png?a=1&amp;b=2"></body></html>')
        mime.setUrls([QUrl("https://example.test/page")])
        self.assertTrue(drop.accepts(mime))
        asked = []

        def fake(url):
            asked.append(url)
            return solid_png("green", 16)
        with mock.patch.object(drop, "download", side_effect=fake):
            self.assertTrue(self.drop(mime))
            self.assertEqual(self.images(), [])                # rien de pose avant l'arrivee
            end = time.monotonic() + 5
            while not self.images() and time.monotonic() < end:
                settle(0.02)
        self.assertEqual(asked[0], "https://example.test/photo.png?a=1&b=2")
        self.placed_at(QPointF(120, -40))

    def test_failed_download_falls_back_to_the_drag_bitmap(self):
        mime = QMimeData()
        mime.setUrls([QUrl("https://example.test/protegee.jpg")])
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(QColor("red"))
        mime.setImageData(image)
        with mock.patch.object(drop, "download", side_effect=OSError("hors ligne")):
            self.assertTrue(self.drop(mime))
            end = time.monotonic() + 5
            while not self.images() and time.monotonic() < end:
                settle(0.02)
        self.placed_at(QPointF(120, -40))

    def test_data_url_and_non_image(self):
        import base64
        mime = QMimeData()
        mime.setUrls([QUrl("data:image/png;base64," + base64.b64encode(solid_png("red", 5)).decode())])
        self.assertTrue(self.drop(mime))
        end = time.monotonic() + 5
        while not self.images() and time.monotonic() < end:
            settle(0.02)
        self.assertEqual(len(self.images()), 1)
        mime = QMimeData()
        mime.setText("du texte")
        self.assertFalse(drop.accepts(mime))
        self.assertFalse(self.drop(mime))


if __name__ == "__main__":
    unittest.main()
