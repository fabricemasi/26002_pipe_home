"""Visionneuse du mode focus (focus.py) : images decodees en fond (taille reelle, version ajustee,
orientation EXIF), ruban qui glisse puis revient au repos, rebond, zoom autour d'un point, pellicule
(clic = rang), planche (taille des vignettes a la molette, zoom « semantique », vague d'ouverture)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, QSizeF, Qt
from PySide6.QtGui import QColor, QImage, QImageIOHandler, QImageWriter, QPixmap, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

APP = QApplication.instance() or QApplication([])

from fm_visionneuse import focus
import previews


def pump(seconds: float, until=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.005)
    return until() if until is not None else True


def solid(w: int, h: int, color: str = "#3070c0") -> QPixmap:
    pix = QPixmap(w, h)
    pix.fill(QColor(color))
    return pix


class LoaderTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _image(self, name: str, w: int, h: int) -> Path:
        path = self.dir / name
        image = QImage(w, h, QImage.Format_RGB32)
        image.fill(QColor("#884422"))
        self.assertTrue(image.save(str(path)))
        return path

    def test_full_and_fitted_versions_are_decoded_in_background(self):
        path = self._image("grande.png", 3000, 2000)
        loader = focus.FocusImageLoader()
        loader.set_fit(QSize(800, 600))
        self.assertEqual(loader.natural_size(path), QSizeF(3000, 2000))     # entete seul
        self.assertIsNone(loader.get(path))
        ready = []
        loader.ready.connect(ready.append)
        loader.request(path, urgent=True)
        self.assertTrue(pump(10, lambda: ready))
        pixmap, full, natural = loader.get(path)
        self.assertEqual(full.size(), QSize(3000, 2000))
        self.assertEqual(natural, QSizeF(3000, 2000))
        self.assertLessEqual(pixmap.width(), 800)
        self.assertLessEqual(pixmap.height(), 600)
        self.assertAlmostEqual(pixmap.width() / pixmap.height(), 1.5, places=2)

    def test_selected_image_decodes_when_mtime_cache_is_memory_only(self):
        path = self._image("selection.png", 2400, 1600)
        loader = focus.FocusImageLoader()
        loader.set_fit(QSize(800, 600))
        ready = []
        loader.ready.connect(ready.append)
        with previews.memory_only():
            loader.request(path, urgent=True)
        self.assertTrue(pump(10, lambda: str(path) in ready))
        _fitted, full, _natural = loader.get(path)
        self.assertEqual(full.size(), QSize(2400, 1600))

    def test_small_lightroom_proxy_falls_back_to_original_photo(self):
        path = self._image("source.jpg", 2400, 1600)
        proxy = self._image("lightroom-small.jpg", 320, 213)
        loader = focus.FocusImageLoader()
        loader.set_fit(QSize(1200, 800))
        ready = []
        loader.ready.connect(ready.append)
        with (patch("lightroom_bridge.is_managed", return_value=True),
              patch("lightroom_bridge.proxy_path", return_value=proxy),
              patch("lightroom_bridge.preview_origin", return_value="lightroom"),
              patch("lightroom_bridge.orientation", return_value="AB")):
            loader.request(path, urgent=True)
            self.assertTrue(pump(10, lambda: str(path) in ready))
        _fitted, full, _natural = loader.get(path)
        self.assertEqual(full.size(), QSize(2400, 1600))
        self.assertEqual(loader.origin(path), "Image originale")

    def test_new_preview_restarts_decode_that_was_already_pending(self):
        path = self._image("pending.jpg", 800, 600)
        key = str(path)
        mtime = previews.cached_mtime(path)
        loader = focus.FocusImageLoader()
        loader._pending[key] = mtime
        loader.invalidate(path)
        with patch.object(loader, "request") as request:
            loader._on_done(key, mtime, None, None, None, "original")
        request.assert_called_once_with(path, urgent=True)
        self.assertNotIn(key, loader._pending)

    def test_retain_cancels_queued_decodes(self):
        paths = [self._image(f"i{i}.png", 1200, 900) for i in range(12)]
        loader = focus.FocusImageLoader()
        loader._pool.setMaxThreadCount(1)
        ready = []
        loader.ready.connect(ready.append)
        for path in paths:
            loader.request(path)
        loader.retain(paths[-1:])                     # on s'est arrete sur la derniere
        self.assertLessEqual(len(loader._pending), 2)  # au plus celle deja commencee + la gardee
        self.assertTrue(pump(10, lambda: str(paths[-1]) in ready))
        self.assertLessEqual(len(ready), 2)

    def test_unreadable_file_is_ignored(self):
        path = self.dir / "casse.png"
        path.write_bytes(b"pas une image")
        loader = focus.FocusImageLoader()
        loader.request(path)
        self.assertTrue(pump(5, lambda: str(path) in loader._failed))
        self.assertIsNone(loader.get(path))
        loader.request(path)                           # pas de nouvel essai pour la meme date
        self.assertNotIn(str(path), loader._pending)

    def test_exif_orientation_is_applied(self):
        path = self.dir / "photo.jpg"
        image = QImage(400, 200, QImage.Format_RGB32)
        image.fill(QColor("#224488"))
        writer = QImageWriter(str(path))
        if not writer.supportsOption(QImageIOHandler.ImageOption.ImageTransformation):
            self.skipTest("le JPEG de Qt n'ecrit pas l'orientation EXIF")
        writer.setTransformation(QImageIOHandler.Transformation.TransformationRotate90)
        self.assertTrue(writer.write(image))
        loader = focus.FocusImageLoader()
        self.assertEqual(loader.natural_size(path), QSizeF(200, 400))
        loader.request(path)
        self.assertTrue(pump(10, lambda: loader.get(path) is not None))
        _pixmap, full, natural = loader.get(path)
        self.assertEqual((full.width(), full.height()), (200, 400))
        self.assertEqual(natural, QSizeF(200, 400))


class OverlayViewerTest(unittest.TestCase):
    def setUp(self):
        self.host = QWidget()
        self.host.resize(1000, 700)
        self.host.show()
        self.addCleanup(self.host.deleteLater)
        pix = solid(800, 600)
        target = focus.fit_rect(QSizeF(4000, 3000), self.host.rect())
        self.overlay = focus.FocusOverlay(self.host, pix, target, target, 1.0, 1.0, 1,
                                          on_double_click=lambda: None)
        self.overlay.show()
        self.assertTrue(pump(1, lambda: not self.overlay.running))
        self.overlay.set_natural(QSizeF(4000, 3000), self.host.rect())
        self.moves = []
        self.overlay.set_viewer(lambda k: (solid(800, 600, "#c03030"), None), self.moves.append)

    def test_slide_starts_offset_and_settles(self):
        overlay = self.overlay
        overlay.show_image(solid(800, 600, "#30c030"), QSizeF(4000, 3000), None, 1)
        self.assertAlmostEqual(overlay.ribbon_offset(), 1.0, places=2)   # la suivante arrive de la droite
        self.assertTrue(overlay.animating())
        self.assertTrue(pump(2, lambda: not overlay.animating()))
        self.assertEqual(overlay.ribbon_offset(), 0.0)
        self.assertTrue(self.moves and self.moves[-1] == 0.0)            # la pellicule a suivi jusqu'au bout
        # Pas rapides : le decalage s'accumule (le ruban defile), borne a 3 images.
        for _ in range(6):
            overlay.show_image(solid(800, 600), QSizeF(4000, 3000), None, 1)
        self.assertLessEqual(overlay.ribbon_offset(), 3.0)
        self.assertGreater(overlay.ribbon_offset(), 2.0)
        self.assertTrue(pump(2, lambda: not overlay.animating()))

    def test_bump_returns_to_rest(self):
        overlay = self.overlay
        overlay.bump(1)
        pump(0.1)
        self.assertLess(overlay.ribbon_offset(), 0.0)      # esquisse le mouvement vers la gauche
        self.assertTrue(pump(1, lambda: not overlay.animating()))
        self.assertEqual(overlay.ribbon_offset(), 0.0)

    def test_zoom_keeps_anchor_and_covers_area(self):
        overlay = self.overlay
        anchor = QPointF(620, 300)
        before = overlay._view_rect()
        u = (anchor.x() - before.x()) / before.width()
        v = (anchor.y() - before.y()) / before.height()
        overlay.zoom_by(2.0, anchor)
        self.assertTrue(pump(2, lambda: not overlay.animating()))
        after = overlay._view_rect()
        self.assertAlmostEqual(after.width() / before.width(), 2.0, places=2)
        self.assertAlmostEqual(after.x() + u * after.width(), anchor.x(), delta=1.0)
        self.assertAlmostEqual(after.y() + v * after.height(), anchor.y(), delta=1.0)
        self.assertTrue(overlay.zoomed())
        # Deplacement a la souris : l'image zoomee couvre toujours la zone (pas de bord vide).
        QTest.mousePress(overlay, Qt.LeftButton, Qt.NoModifier, QPoint(500, 350))
        QTest.mouseMove(overlay, QPoint(2500, 2350))
        QTest.mouseRelease(overlay, Qt.LeftButton, Qt.NoModifier, QPoint(2500, 2350))
        rect = overlay._view_rect()
        self.assertLessEqual(rect.left(), 0.5)
        self.assertLessEqual(rect.top(), 0.5)
        overlay.zoom_reset()
        self.assertTrue(pump(2, lambda: not overlay.animating()))
        self.assertFalse(overlay.zoomed())
        self.assertEqual(overlay._view_rect(), overlay._target)

    def test_new_image_resets_zoom(self):
        overlay = self.overlay
        overlay.zoom_by(3.0)
        pump(2, lambda: not overlay.animating())
        overlay.show_image(solid(400, 400), QSizeF(400, 400), None, 1)
        self.assertFalse(overlay.zoomed())


class FilmstripTest(unittest.TestCase):
    def test_click_on_a_thumbnail_chooses_its_rank(self):
        paths = [Path(f"C:/x/image_{i:02d}.png") for i in range(20)]
        strip = focus.FocusFilmstrip(None, lambda path, side: solid(90, 60))
        self.addCleanup(strip.deleteLater)
        strip.resize(900, strip.strip_height())
        strip.set_paths(paths, 5)
        strip.show()
        strip.reveal()
        self.assertTrue(pump(1, lambda: strip.visible_amount() > 0.95))
        chosen = []
        strip.chosen.connect(chosen.append)
        centre = QPoint(strip.width() // 2, strip.height() - 30)
        self.assertEqual(strip._index_at(QPointF(centre)), 5)
        step = strip._tw + strip._gap
        QTest.mouseClick(strip, Qt.LeftButton, Qt.NoModifier, centre + QPoint(2 * step, 0))
        self.assertEqual(chosen, [7])
        strip.set_position(6.5)                          # suit le ruban en continu
        self.assertEqual(strip._index_at(QPointF(centre + QPoint(step // 2, 0))), 7)

    def test_conceal_fades_out(self):
        strip = focus.FocusFilmstrip(None, lambda path, side: None)
        self.addCleanup(strip.deleteLater)
        strip.set_paths([Path("C:/x/a.png")], 0)
        strip.reveal()
        pump(1, lambda: strip.visible_amount() > 0.95)
        strip.conceal()
        self.assertTrue(pump(2, lambda: strip.visible_amount() == 0.0))


class GalleryTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.paths = []
        for i in range(120):
            path = self.dir / f"img_{i:03d}.png"
            path.write_bytes(b"x")
            self.paths.append(path)
        self.host = QWidget()
        self.host.resize(1200, 800)
        self.host.show()
        self.addCleanup(self.host.deleteLater)
        self._size = focus.FocusGallery.tile_size
        self.addCleanup(setattr, focus.FocusGallery, "tile_size", self._size)
        focus.FocusGallery.tile_size = 200
        self.gallery = focus.FocusGallery(self.host, self.paths, str(self.paths[10]))
        self.gallery.setGeometry(self.host.rect())
        self.gallery.show()
        self.gallery.reveal_current()

    def _ctrl_wheel(self, delta: int):
        viewport = self.gallery.viewport()
        pos = QPointF(300, 200)
        event = QWheelEvent(pos, QPointF(viewport.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, delta),
                            Qt.NoButton, Qt.ControlModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(viewport, event)

    def test_ctrl_wheel_resizes_then_zooms_into_a_tile(self):
        gallery = self.gallery
        self._ctrl_wheel(120)
        self.assertGreater(gallery.TILE, 200)
        self.assertEqual(focus.FocusGallery.tile_size, gallery.TILE)       # retenue pour la prochaine fois
        self._ctrl_wheel(-240)
        self.assertLess(gallery.TILE, 200)
        opened = []
        gallery.zoomed_into.connect(opened.append)
        for _ in range(20):
            self._ctrl_wheel(120)
            if opened:
                break
        self.assertEqual(gallery.TILE, gallery.TILE_MAX)
        self.assertEqual(len(opened), 1)
        self.assertIn(opened[0], self.paths)

    def test_few_files_fill_the_screen_before_zooming_into_one(self):
        """Peu de fichiers : Ctrl+molette avant les grossit, puis ils REMPLISSENT l'ecran tous ensemble,
        et seulement ensuite on entre dans une image ; Ctrl+molette arriere revient en arriere."""
        gallery = self._gallery_of(4, QSize(1600, 900))
        self.gallery = gallery
        opened = []
        gallery.zoomed_into.connect(opened.append)
        sides = [gallery.gridSize().width()]
        for _ in range(40):
            self._ctrl_wheel(120)
            sides.append(gallery.gridSize().width())
            self.assertTrue(gallery._shows_all(gallery._plan(gallery.TILE)), "un fichier est sorti de l'ecran")
            if opened:
                break
        self.assertEqual(len(opened), 1)
        self.assertTrue(gallery._filled)
        # Juste avant d'entrer : 2 x 2 cases qui remplissent l'ecran (900 / 2 de haut).
        self.assertEqual((gallery._cols, gallery._rows), (2, 2))
        self.assertEqual(gallery.gridSize().height(), 450)
        self.assertEqual(sides, sorted(sides))                   # ne fait que grossir
        self._ctrl_wheel(-120)
        self.assertFalse(gallery._filled)
        self.assertLess(gallery.gridSize().height(), 450)

    def test_ripple_spreads_from_current_tile(self):
        gallery = self.gallery
        gallery.start_ripple()
        pump(0.05)
        current = gallery.visualItemRect(gallery.currentItem())
        far = gallery.visualItemRect(gallery.item(0))
        near_opacity = gallery.ripple_state(current)[0]
        far_opacity = gallery.ripple_state(far)[0]
        self.assertGreater(near_opacity, far_opacity)
        self.assertTrue(pump(3, lambda: gallery._ripple_origin is None))
        self.assertEqual(gallery.ripple_state(far), (1.0, 1.0))

    def _table_in_gallery(self, gallery) -> QRect:
        """La partie VISIBLE du tableau dans le repere de la planche (marges du viewport = sa place)."""
        margins = gallery.viewportMargins()
        grid = gallery.gridSize()
        return QRect(margins.left(), margins.top(), gallery._table.width(), gallery._visible_rows * grid.height())

    def _gallery_of(self, count: int, size: QSize):
        gallery = focus.FocusGallery(self.host, self.paths[:count], str(self.paths[0]))
        self.addCleanup(gallery.deleteLater)
        gallery.setGeometry(QRect(QPoint(0, 0), size))
        gallery.show()
        gallery.reveal_current()
        pump(0.02)
        return gallery

    def _assert_square(self, gallery, tolerance=0.25):
        grid = gallery.gridSize()
        self.assertLess(abs(grid.width() / grid.height() - 1.0), tolerance, grid)

    def test_tiles_come_from_a_proxy_slightly_larger_than_the_cell(self):
        """Apercu du pipeline trop petit pour la case : la vignette est refaite depuis un proxy decode
        en fond un poil plus grand que la case."""
        big = self.dir / "big.png"
        image = QImage(2400, 2400, QImage.Format_RGB32)
        image.fill(QColor("#c08040"))
        image.save(str(big))
        other = self.dir / "other.png"
        image.save(str(other))
        mtime = previews.cached_mtime(big)
        self.addCleanup(previews._file_image_cache.pop, str(big), None)
        self.addCleanup(focus._PROXIES.pop, str(big), None)
        previews._file_image_cache[str(big)] = (mtime, solid(120, 120))
        gallery = focus.FocusGallery(self.host, [big, other], str(big))
        self.addCleanup(gallery.deleteLater)
        gallery.setGeometry(QRect(0, 0, 1600, 900))
        gallery.show()
        gallery.reveal_current()
        pump(0.02)
        side = round(gallery._box_side * (gallery.devicePixelRatioF() or 1.0))
        self.assertGreater(side, 120)
        gallery.tile_pixmap(big, mtime)                    # provisoire (apercu agrandi) + proxy demande
        self.assertTrue(pump(5, lambda: str(big) in focus._PROXIES))
        proxy = focus._PROXIES[str(big)][2]
        self.assertGreaterEqual(max(proxy.width(), proxy.height()), side * focus.PROXY_MARGIN - 1)
        self.assertLess(max(proxy.width(), proxy.height()), 2400)    # pas la pleine definition
        tile = gallery.tile_pixmap(big, mtime)
        self.assertEqual(max(tile.width(), tile.height()), side)

    def test_table_fills_the_screen_with_square_cells(self):
        for size in (QSize(1200, 800), QSize(1920, 1080), QSize(900, 1300), QSize(1500, 500)):
            gallery = self._gallery_of(120, size)          # plus de fichiers que l'ecran n'en montre
            table, grid = self._table_in_gallery(gallery), gallery.gridSize()
            # Cale sur les 4 bords (il ne reste que l'arrondi : < 1 px par colonne / ligne).
            self.assertLessEqual(table.left(), gallery._cols, size)
            self.assertLessEqual(size.width() - table.right() - 1, gallery._cols + 1, size)
            self.assertLessEqual(table.top(), gallery._visible_rows, size)
            self.assertLessEqual(size.height() - table.bottom() - 1, gallery._visible_rows, size)
            self._assert_square(gallery)
            # Une cellule par fichier, dans l'ordre ; les lignes suivantes sont sous la zone.
            first = gallery.visualItemRect(gallery.item(0))
            self.assertEqual(first.size(), grid)
            hidden = gallery.item(gallery._visible_rows * gallery._cols)
            self.assertGreaterEqual(gallery.visualItemRect(hidden).top(), gallery.viewport().height())
        self.assertTrue(gallery.item(0).data(Qt.UserRole + 2).startswith("PNG"))   # type et poids

    def _wheel(self, gallery, delta: int):
        viewport = gallery.viewport()
        pos = QPointF(300, 200)
        event = QWheelEvent(pos, QPointF(viewport.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, delta),
                            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(viewport, event)

    def _scroll_setting(self, animated: bool):
        import ui_state
        old = ui_state.APPLIED_SETTINGS
        self.addCleanup(setattr, ui_state, "APPLIED_SETTINGS", old)
        ui_state.APPLIED_SETTINGS = {**(old or {}), "viewer_scroll_animated": animated}

    def test_wheel_scrolls_by_whole_rows(self):
        self._scroll_setting(False)
        gallery = self._gallery_of(30, QSize(1200, 800))
        grid = gallery.gridSize()
        gallery._scroll_to_row(0)
        self._wheel(gallery, -120)
        self.assertEqual(gallery.verticalScrollBar().value(), grid.height())       # saut sec
        self.assertEqual(gallery.visualItemRect(gallery.item(gallery._cols)).top(), 0)

    def test_glide_band_looks_like_the_planche(self):
        # Pendant le glissement, la planche est une image des lignes qui defilent : la meme qu'a l'arret.
        gallery = self._gallery_of(60, QSize(1200, 800))
        # Les controles d'attributs du survol se cachent pendant le glissement : hors de la comparaison.
        gallery.attr_editing_allowed = lambda: False
        gallery._scroll_to_row(2)
        gallery.repaint()
        still = gallery.viewport().grab().toImage()
        gallery._glide_band = gallery._render_band(1, 2 + gallery._visible_rows + 1)
        gallery.viewport().repaint()
        glide = gallery.viewport().grab().toImage()
        gallery._stop_scroll()
        self.assertIsNone(gallery._glide_band)
        self.assertEqual(still, glide)

    def test_animated_wheel_glides_to_whole_rows(self):
        self._scroll_setting(True)
        gallery = self._gallery_of(60, QSize(1200, 800))
        grid = gallery.gridSize()
        gallery._scroll_to_row(0)
        self._wheel(gallery, -120)
        bar = gallery.verticalScrollBar()
        self.assertLess(bar.value(), grid.height())                  # pas encore arrivee : elle glisse
        self.assertEqual(gallery.first_visible_row(), 1)             # ... vers la ligne suivante
        self._wheel(gallery, -120)                                   # cran rapide : se cumule
        self.assertEqual(gallery.first_visible_row(), 2)
        seen = set()
        self.assertTrue(pump(2, lambda: seen.add(bar.value()) or gallery._scroll_goal is None))
        self.assertEqual(bar.value(), 2 * grid.height())             # lignes calees a l'arrivee
        self.assertGreater(len(seen), 3)                             # des positions intermediaires

    def test_files_that_fit_make_a_square_table(self):
        for count, shape in ((4, (2, 2)), (5, (3, 2)), (9, (3, 3)), (2, (2, 1)), (3, (2, 2))):
            gallery = self._gallery_of(count, QSize(1600, 900))
            self.assertEqual((gallery._cols, gallery._rows), shape, count)
            self._assert_square(gallery, 0.05)

    def test_few_files_keep_the_size_of_a_full_screen(self):
        # Peu de fichiers : les cases ne grandissent pas pour remplir l'ecran, elles ont la taille
        # qu'elles auraient si le dossier le remplissait.
        for size in (QSize(1600, 900), QSize(2540, 1380), QSize(900, 1300)):
            full = self._gallery_of(30, size).gridSize()
            for count in (1, 4, 9):
                self.assertEqual(self._gallery_of(count, size).gridSize(), full, (size, count))

    def test_few_files_stay_square_and_centred(self):
        gallery = self._gallery_of(3, QSize(1600, 900))
        self._assert_square(gallery, 0.05)
        table = self._table_in_gallery(gallery)
        self.assertLessEqual(abs(table.center().x() - 800), 2)
        self.assertLessEqual(abs(table.center().y() - 450), 2)


if __name__ == "__main__":
    unittest.main()
