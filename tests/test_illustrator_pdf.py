"""Module Illustrator, tranche 16 : export PDF : une page par plan de travail à sa taille exacte (points), relu par
QtPdf et vérifié au pixel (objets, texte, masque, fond), sans sélection ; tracés vectoriels (aucune image dans le
PDF), images incorporées en pleine résolution, mode Tracés ignoré, sans plan de travail = cadre du dessin."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import re
import unittest

from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtPdf import QPdfDocument

from test_illustrator_images import ImageTestCase
from fm_illustrator import bezier as bz


def load(path):
    doc = QPdfDocument()
    doc.load(str(path))
    return doc


def page_image(doc, index, width) -> QImage:
    size = doc.pagePointSize(index)
    return doc.render(index, QSize(width, round(width * size.height() / size.width())))


class PdfTest(ImageTestCase):
    def setUp(self):
        super().setUp()
        self.board_a = self.ctl.add_artboard(QRectF(0, 0, 400, 300), "Recto")
        self.board_b = self.ctl.add_artboard(QRectF(500, 0, 200, 400), "Verso")

    def red_rect(self):
        item = self.ctl.new_path(bz.rect(0, 0, 100, 100), QPointF(50, 50),
                                 dict(self.ctl.style, fill="#ff0000", stroke="", fill_gradient=None))
        self.ctl.commit_new(item, "r")
        return item

    def test_one_page_per_artboard_at_exact_size(self):
        item = self.red_rect()
        self.ctl.select([item])                                  # la sélection ne doit pas être exportée
        target = self.ctl.export_pdf(self.tmp / "plans.pdf")
        doc = load(target)
        self.assertEqual(doc.pageCount(), 2)
        self.assertAlmostEqual(doc.pagePointSize(0).width(), 300.0, delta=0.5)    # 400 unités = 300 pt
        self.assertAlmostEqual(doc.pagePointSize(1).height(), 300.0, delta=0.5)
        image = page_image(doc, 0, 400)                                            # 1 px = 1 unité
        self.assertEqual(image.pixelColor(100, 100).name(), "#ff0000")
        self.assertEqual(image.pixelColor(300, 250).name(), "#ffffff")
        self.assertEqual(image.pixelColor(50, 50).name(), "#ff0000")             # coin : pas de filet bleu
        self.assertNotIn(b"/Subtype /Image", target.read_bytes())                 # tout vectoriel

    def test_text_mask_and_outline_mode(self):
        self.red_rect()
        text = self.ctl.new_text(QPointF(220, 150), text="AB", font_size=60.0, fill="#0000ff")
        self.ctl.commit_new(text, "t")
        art = self.ctl.new_path(bz.rect(0, 0, 100, 100), QPointF(250, 180),
                                dict(self.ctl.style, fill="#00aa00", stroke="", fill_gradient=None))
        self.ctl.commit_new(art, "a")
        clip = self.ctl.new_path(bz.rect(0, 0, 40, 40), QPointF(250, 180), dict(self.ctl.style, fill="#000000"))
        self.ctl.commit_new(clip, "m")
        self.ctl.select([art, clip])
        self.ctl.make_mask("clip")
        self.ctl.toggle_outline()                               # mode Tracés à l'écran : pas dans le PDF
        doc = load(self.ctl.export_pdf(self.tmp / "recto.pdf", [self.board_a]))
        self.assertEqual(doc.pageCount(), 1)
        image = page_image(doc, 0, 400)
        blue = [image.pixelColor(x, y) for x in range(220, 290, 2) for y in range(110, 150, 2)]
        self.assertTrue(any(c.blue() > 200 and c.red() < 80 for c in blue))      # lettres peintes
        self.assertEqual(image.pixelColor(260, 190).name(), "#00aa00")           # dans le masque
        self.assertEqual(image.pixelColor(320, 250).name(), "#ffffff")           # écrêté
        self.assertTrue(getattr(self.scene, "ill_outline"))                       # rendu à l'écran inchangé

    def test_image_full_resolution_and_no_artboard(self):
        big = QImage(3000, 1500, QImage.Format_RGB32)
        big.fill(QColor("#336699"))
        path = self.tmp / "grande.png"
        big.save(str(path))
        item = self.ctl.place_image(path, QPointF(200, 150))
        self.ctl.select([item])
        rect = self.ctl.selection_rect()
        self.ctl.transform_selection(bz.scale(0.1, 0.1, rect.center().x(), rect.center().y()), "Réduire")
        target = self.ctl.export_pdf(self.tmp / "image.pdf", [self.board_a])
        raw = target.read_bytes()
        widths = [int(w) for w in re.findall(rb"/Width (\d+)", raw)]
        self.assertIn(3000, widths)                                                # pas la version réduite
        c = page_image(load(target), 0, 400).pixelColor(200, 150)          # compression de l'image : ±2 niveaux
        self.assertTrue(abs(c.red() - 0x33) <= 2 and abs(c.green() - 0x66) <= 2 and abs(c.blue() - 0x99) <= 2, c.name())
        for board in (self.board_a, self.board_b):
            self.scene.delete_items([board])
        doc = load(self.ctl.export_pdf(self.tmp / "dessin.pdf"))
        self.assertEqual(doc.pageCount(), 1)
        self.assertAlmostEqual(doc.pagePointSize(0).width(), (300 + 40) * 0.75, delta=1.0)


if __name__ == "__main__":
    unittest.main()
