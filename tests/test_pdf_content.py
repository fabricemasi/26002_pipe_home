"""Édition RÉELLE du contenu (fm_pdf/content.py) : le texte d'un objet change dans le flux de contenu (relu par
MuPDF, aucune superposition), police incorporée en sous-ensemble sans les glyphes = repli explicite sur une police
standard, déplacement / taille / rotation / couleur, ajout de texte, forme et image, suppression, superposition."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import io
import unittest

import _pdf_samples as S
from fm_pdf import content
from fm_pdf.worker import get_engine


def _text(data):
    import pymupdf
    doc = pymupdf.open(stream=data)
    try:
        return doc[0].get_text("text")
    finally:
        doc.close()


def _subset_pdf() -> bytes:
    """Texte dans une police TrueType INCORPORÉE en sous-ensemble (seuls les glyphes de « abc ABC »)."""
    import pymupdf
    font = r"C:\Windows\Fonts\arial.ttf"
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=300)
    page.insert_font(fontname="F0", fontfile=font)
    page.insert_text((50, 100), "abc ABC", fontname="F0", fontsize=20)
    doc.subset_fonts()
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


class ContentTest(unittest.TestCase):
    def setUp(self):
        self.eng = get_engine()

    def run_on(self, data, fn):
        def go():
            doc = self.eng.open_document(data, "c.pdf")
            try:
                result = fn(doc)
                return result, doc.save_bytes()[0]
            finally:
                self.eng.close_document(doc)
        return self.eng.call(go)

    def test_replace_text_in_the_content_stream(self):
        data = S.text_pdf(1)

        def edit(doc):
            item = content.object_at(doc, 0, 100, 95)
            self.assertEqual(item["type_name"], "texte")
            self.assertIn("Bonjour", item["text"])
            return content.set_text(doc, 0, item["index"], "Bonsoir tout le monde")
        result, out = self.run_on(data, edit)
        self.assertIsNone(result["fallback"])
        text = _text(out)
        self.assertIn("Bonsoir tout le monde", text)
        self.assertNotIn("Bonjour", text)                             # remplacé, pas recouvert
        self.assertIn("éléphant", text)                               # le reste de la page intact

    def test_missing_glyphs_fall_back_to_a_standard_font(self):
        data = _subset_pdf()

        def edit(doc):
            item = content.object_at(doc, 0, 60, 95)
            return content.set_text(doc, 0, item["index"], "Zèbre XYZ")
        result, out = self.run_on(data, edit)
        self.assertEqual(result["fallback"], "Helvetica")
        self.assertIn("Zèbre XYZ", _text(out))

    def test_move_resize_color_add_delete_restack(self):
        data = S.text_pdf(1)
        from PySide6.QtGui import QImage

        def edit(doc):
            item = content.object_at(doc, 0, 100, 95)
            before = item["rect"]
            content.move(doc, 0, item["index"], 30, 40)
            moved = content.objects(doc, 0)[item["index"]]["rect"]
            content.resize(doc, 0, item["index"], (moved[0], moved[1], moved[0] + 2 * (moved[2] - moved[0]),
                                                   moved[1] + 2 * (moved[3] - moved[1])))
            big = content.objects(doc, 0)[item["index"]]["rect"]
            content.set_colors(doc, 0, item["index"], fill=(200, 0, 0))
            n = len(content.objects(doc, 0))
            content.add_text(doc, 0, 72, 400, "Ajouté\nsur deux lignes", 14)
            content.add_shape(doc, 0, "rect", (60, 500, 260, 560), stroke=(0, 0, 200), fill=(220, 220, 255), width=2)
            img = QImage(20, 10, QImage.Format_ARGB32)
            img.fill(0xFF00AA00)
            raw = bytes(img.constBits())
            content.add_image(doc, 0, (300, 500, 400, 550), raw, 20, 10, img.bytesPerLine())
            objs = content.objects(doc, 0)
            self.assertEqual(len(objs), n + 4)
            self.assertEqual(objs[-1]["type_name"], "image")
            new = content.restack(doc, 0, len(objs) - 1, 0)
            self.assertEqual(content.objects(doc, 0)[new]["type_name"], "image")
            content.delete(doc, 0, new)
            return before, moved, big, len(content.objects(doc, 0)), n
        (before, moved, big, count, n), out = self.run_on(data, edit)
        self.assertAlmostEqual(moved[0] - before[0], 30, delta=0.5)
        self.assertAlmostEqual(moved[1] - before[1], 40, delta=0.5)
        self.assertAlmostEqual(big[2] - big[0], 2 * (moved[2] - moved[0]), delta=1.0)
        self.assertEqual(count, n + 3)
        text = _text(out)
        self.assertIn("Ajouté", text)
        self.assertIn("sur deux lignes", text)
        import pymupdf
        doc = pymupdf.open(stream=out)
        self.assertEqual(len(doc[0].get_images()), 0)                 # l'image a été supprimée pour de bon
        self.assertTrue(any(d["rect"].width > 190 for d in doc[0].get_drawings()))   # le rectangle ajouté

    def test_xfa_content_is_refused(self):
        if not S.has_fixture("xfa_fish_licence.pdf"):
            self.skipTest("fixture absente")
        with self.assertRaises(content.ContentError):
            self.run_on(S.fixture("xfa_fish_licence.pdf"), lambda doc: content.move(doc, 0, 0, 1, 1))


if __name__ == "__main__":
    unittest.main()
