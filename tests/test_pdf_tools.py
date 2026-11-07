"""Outils du module PDF sans interface : pages (ordre, suppression, rotation, insertion, fusion, division,
extraction, numéros, filigrane), annotations (création, liste, suppression ; relues par MuPDF), caviardage RÉEL
(texte introuvable après coup), chiffrement / déchiffrement, signature numérique + vérification (et modification
après signature détectée), OCR Windows (page numérisée -> texte cherchable), optimisation sans perte."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import io
import unittest

import _pdf_samples as S
from fm_pdf import annots, exporting, pages, security
from fm_pdf.worker import get_engine


def _texts(data):
    import pymupdf
    doc = pymupdf.open(stream=data)
    try:
        return [p.get_text("text") for p in doc]
    finally:
        doc.close()


class PagesTest(unittest.TestCase):
    def test_reorder_delete_rotate_insert_merge_split_extract(self):
        data = S.text_pdf(4)
        moved = pages.move_pages(data, [3], 0)
        self.assertIn("page 4", _texts(moved)[0])
        self.assertEqual(len(_texts(pages.delete_pages(data, [1, 2]))), 2)
        with self.assertRaises(pages.PageError):
            pages.delete_pages(data, [0, 1, 2, 3])
        import pymupdf
        rotated = pymupdf.open(stream=pages.rotate_pages(data, [0], 1))
        self.assertEqual(rotated[0].rotation, 90)
        self.assertEqual(len(_texts(pages.insert_blank(data, 2))), 5)
        merged = pages.merge([data, S.text_pdf(2, "Autre")])
        self.assertEqual(len(_texts(merged)), 6)
        self.assertIn("Autre page 1", _texts(merged)[4])
        parts = pages.split(data, every=3)
        self.assertEqual([len(_texts(p)) for p in parts], [3, 1])
        self.assertEqual(len(_texts(pages.extract(data, [1, 3]))), 2)
        self.assertIn("2 / 4", _texts(pages.add_page_numbers(data))[1])
        self.assertIn("SECRET", _texts(pages.watermark(data, "SECRET"))[0])
        self.assertEqual(pages.parse_ranges("1-2, 4, 3-", 5), [0, 1, 3, 2, 4])

    def test_forms_survive_page_operations_and_xfa_is_refused(self):
        form = S.sample_form()
        doubled = pages.insert_from(form, S.text_pdf(1), 0)
        import pymupdf
        doc = pymupdf.open(stream=doubled)
        self.assertEqual(doc.page_count, 2)
        self.assertEqual(len(list(doc[1].widgets())), 12)          # les champs ont suivi leur page
        doc.close()
        if S.has_fixture("xfa_fish_licence.pdf"):
            with self.assertRaises(pages.PageError):
                pages.rotate_pages(S.fixture("xfa_fish_licence.pdf"), [0])


class AnnotsTest(unittest.TestCase):
    def test_add_list_update_delete(self):
        data = S.text_pdf(1)
        eng = get_engine()

        def rects(doc):
            return doc.search(0, "Bonjour")[0][2]
        doc = eng.call(lambda: eng.open_document(data, "a.pdf"))
        try:
            hit = eng.call(lambda: rects(doc))
        finally:
            eng.call(lambda: eng.close_document(doc))
        data, x1 = annots.add(data, 0, "highlight", {"rects": hit, "color": (1, 0.8, 0), "author": "Testeur",
                                                     "contents": "important"})
        data, x2 = annots.add(data, 0, "ink", {"strokes": [[(100, 300), (150, 320), (200, 300)]]})
        data, x3 = annots.add(data, 0, "note", {"point": (400, 100), "contents": "Note"})
        data, x4 = annots.add(data, 0, "arrow", {"points": ((50, 500), (200, 550))})
        data, x5 = annots.add(data, 0, "stamp", {"rect": (300, 600, 450, 650), "stamp": "Approuvé"})
        items = annots.list_all(data)
        self.assertEqual(sorted(a["kind"] for a in items), sorted(["highlight", "ink", "note", "line", "stamp"]))
        hl = next(a for a in items if a["kind"] == "highlight")
        self.assertEqual((hl["author"], hl["contents"]), ("Testeur", "important"))
        self.assertTrue(hl["date"].startswith("D:"))
        data = annots.update(data, 0, x1, {"contents": "modifié"})
        self.assertEqual(next(a for a in annots.list_all(data) if a["xref"] == x1)["contents"], "modifié")
        data = annots.delete(data, [(0, x2)])
        self.assertEqual(len(annots.list_all(data)), 4)


class SecurityTest(unittest.TestCase):
    def test_redaction_really_removes_text(self):
        data = S.text_pdf(1, "Numéro secret 4242 visible")
        eng = get_engine()
        doc = eng.call(lambda: eng.open_document(data, "r.pdf"))
        try:
            hit = eng.call(lambda: doc.search(0, "secret 4242"))[0][2][0]
        finally:
            eng.call(lambda: eng.close_document(doc))
        out, report = security.redact(data, [(0, hit)])
        self.assertTrue(report["ok"], report)
        text = _texts(out)[0]
        self.assertNotIn("4242", text)
        self.assertNotIn("secret", text)
        self.assertIn("visible", text)                                # le reste de la ligne demeure
        self.assertNotIn(b"4242", out)                                # ni dans les octets bruts

    def test_encrypt_decrypt_and_metadata(self):
        data = S.text_pdf(1)
        enc = security.encrypt(data, "ouvrir", "maitre", allowed=("print",))
        import pymupdf
        self.assertTrue(pymupdf.open(stream=enc).needs_pass)
        with self.assertRaises(security.SecurityError):
            security.decrypt(enc, "faux")
        plain = security.decrypt(enc, "ouvrir")
        self.assertFalse(pymupdf.open(stream=plain).needs_pass)
        doc = pymupdf.open(stream=data)
        doc.set_metadata({"author": "Quelqu'un", "title": "Titre"})
        out = io.BytesIO()
        doc.save(out)
        stripped = security.strip_metadata(out.getvalue())
        meta = security.metadata(stripped)
        self.assertFalse(meta.get("author"))
        self.assertFalse(meta.get("title"))

    def test_sign_verify_and_detect_later_change(self):
        data = S.sample_form()
        p12 = security.self_signed_pkcs12("Testeur Signature", "phrase")
        signed = security.sign(data, p12, "phrase", page_index=0, rect=(320, 700, 520, 760), reason="Approuvé")
        self.assertTrue(signed.startswith(data[:100]))
        (state,) = security.verify(signed)
        self.assertTrue(state["intact"] and state["valid"], state)
        self.assertFalse(state["trusted"])                            # auto-signé : jamais présenté comme approuvé
        self.assertIn("Testeur Signature", state["signer"])
        tampered = bytearray(signed)                                  # un octet du contenu signé change
        i = signed.find(b"Helv")
        tampered[i] = ord("X")
        (bad,) = security.verify(bytes(tampered))
        self.assertFalse(bad["intact"] and bad["valid"])


class OcrTest(unittest.TestCase):
    def test_scanned_page_becomes_searchable(self):
        from fm_pdf import ocr
        try:
            langs = ocr.available_languages()
        except ocr.OcrUnavailable as exc:
            self.skipTest(str(exc))
        if not any(l.lower().startswith("fr") for l in langs):
            self.skipTest("langue OCR française absente")
        import pymupdf
        src = pymupdf.open(stream=S.text_pdf(1, "Formulaire numérisé Dupont"))
        pix = src[0].get_pixmap(dpi=200)                              # page « numérisée » : une image seulement
        scan = pymupdf.open()
        page = scan.new_page(width=src[0].rect.width, height=src[0].rect.height)
        page.insert_image(page.rect, pixmap=pix)
        out = io.BytesIO()
        scan.save(out)
        data = out.getvalue()
        eng = get_engine()

        def work():
            doc = eng.open_document(data, "scan.pdf")
            try:
                self.assertTrue(ocr.is_scanned(doc, 0))
                w, h = doc.page_size(0)
                scale = 300 / 72
                buf, iw, ih, stride = doc.render(0, scale, None, forms=False)
                return scale, buf, iw, ih
            finally:
                eng.close_document(doc)
        scale, buf, iw, ih = eng.call(work)
        lines = ocr.recognize(buf, iw, ih, "fr-FR")
        text = " ".join(l["text"] for l in lines)
        self.assertIn("Dupont", text)
        layered = ocr.add_text_layer(data, {0: {"scale": scale, "lines": lines}})

        def search():
            doc = eng.open_document(layered, "scan.pdf")
            try:
                return doc.search(0, "Dupont")
            finally:
                eng.close_document(doc)
        self.assertEqual(len(eng.call(search)), 1)                    # cherchable, sélectionnable


class ExportTest(unittest.TestCase):
    def test_optimize_keeps_forms_and_never_grows(self):
        data = S.sample_form()
        out = exporting.optimize(data)
        self.assertLessEqual(len(out), len(data))
        import pymupdf
        self.assertEqual(len(list(pymupdf.open(stream=out)[0].widgets())), 12)


if __name__ == "__main__":
    unittest.main()
