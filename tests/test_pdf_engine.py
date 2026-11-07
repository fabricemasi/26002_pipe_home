"""Moteur PDF (fm_pdf/engine.py, worker.py) : ouverture, rendu par tuiles, texte, recherche, mot de passe, fichier
endommagé. Sans Qt."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import io
import unittest

import _pdf_samples as S
from fm_pdf import engine, native
from fm_pdf.worker import PRIO_BACKGROUND, PRIO_VISIBLE, get_engine


def _dark_pixels(data, w, h, stride):
    n = 0
    for y in range(0, h, 2):
        row = data[y * stride:(y * stride) + w * 4]
        n += sum(1 for x in range(0, len(row), 8) if row[x] < 128)
    return n


class EngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng = get_engine()
        cls.data = S.text_pdf(3)

    def call(self, fn):
        return self.eng.call(fn)

    def test_native_library_has_xfa(self):
        info = native.info()
        self.assertTrue(info["xfa"] and info["v8"], info)
        self.assertEqual(info["build"], native.PINNED_BUILD)

    def test_open_pages_text_and_search(self):
        def go():
            doc = self.eng.open_document(self.data, "t.pdf")
            try:
                self.assertEqual(doc.page_count(), 3)
                self.assertEqual([round(v) for v in doc.page_size(0)], [595, 842])
                self.assertIn("Bonjour le monde page 2", doc.text(1))
                hits = doc.search(2, "éléphant")
                self.assertEqual(len(hits), 1)
                start, count, rects = hits[0]
                self.assertEqual(count, len("éléphant"))
                x0, y0, x1, y1 = rects[0]
                self.assertTrue(72 < x0 < x1 < 400 and 120 < y0 < y1 < 150, rects)   # 2e ligne, y = 140 pt
                idx = doc.char_at(2, (x0 + x1) / 2, (y0 + y1) / 2)
                self.assertTrue(start <= idx < start + count)
                self.assertEqual(doc.search(0, "ÉLÉPHANT", match_case=True), [])
                self.assertEqual(len(doc.search(0, "ÉLÉPHANT")), 1)
                self.assertFalse(doc.security()["encrypted"])
                self.assertEqual(doc.outline(), [])
                return True
            finally:
                self.eng.close_document(doc)
        self.assertTrue(self.call(go))

    def test_tile_equals_part_of_full_render(self):
        def go():
            doc = self.eng.open_document(self.data, "t.pdf")
            try:
                full, w, h, stride = doc.render(0, 2.0)
                tile, tw, th, tstride = doc.render(0, 2.0, (100, 150, 256, 128))
                self.assertGreater(_dark_pixels(full, w, h, stride), 50)
                for row in range(th):
                    a = full[(150 + row) * stride + 100 * 4:(150 + row) * stride + (100 + tw) * 4]
                    b = tile[row * tstride:row * tstride + tw * 4]
                    self.assertEqual(a, b, "ligne %d de la tuile" % row)
                return w, h
            finally:
                self.eng.close_document(doc)
        self.assertEqual(self.call(go), (1190, 1684))

    def test_priorities_and_cancel(self):
        order = []
        gate = self.eng.submit(lambda: __import__("time").sleep(0.05), PRIO_BACKGROUND)
        low = self.eng.submit(lambda: order.append("fond"), PRIO_BACKGROUND)
        high = self.eng.submit(lambda: order.append("visible"), PRIO_VISIBLE)
        cancelled = self.eng.submit(lambda: order.append("annulée"), PRIO_VISIBLE)
        cancelled.cancel()
        for job in (gate, low, high, cancelled):
            job.done.wait(5)
        self.assertEqual(order, ["visible", "fond"])

    def test_password_protected(self):
        import pymupdf
        doc = pymupdf.open(stream=self.data)
        out = io.BytesIO()
        doc.save(out, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="maitre",
                 permissions=pymupdf.PDF_PERM_PRINT)
        data = out.getvalue()

        def go():
            with self.assertRaises(engine.PasswordError):
                self.eng.open_document(data, "p.pdf")
            with self.assertRaises(engine.PasswordError):
                self.eng.open_document(data, "p.pdf", password="faux")
            d = self.eng.open_document(data, "p.pdf", password="secret")
            try:
                sec = d.security()
                self.assertTrue(sec["encrypted"])
                self.assertTrue(sec["can_print"])
                self.assertFalse(sec["can_modify"])
                self.assertIn("Bonjour", d.text(0))
            finally:
                self.eng.close_document(d)
        self.call(go)

    def test_damaged_and_truncated(self):
        def go():
            with self.assertRaises(engine.EngineError):
                self.eng.open_document(b"%PDF-1.7\nceci n'est pas un pdf", "x.pdf")
            truncated = self.data[: len(self.data) * 2 // 3]
            try:                                   # PDFium répare souvent : aucune chute, au pire une erreur propre
                d = self.eng.open_document(truncated, "x.pdf")
                d.page_count()
                self.eng.close_document(d)
            except engine.EngineError:
                pass
            return True
        self.assertTrue(self.call(go))


if __name__ == "__main__":
    unittest.main()
