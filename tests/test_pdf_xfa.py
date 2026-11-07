"""Formulaires XFA (« Please wait… » des lecteurs ordinaires) : chargement par PDFium V8/XFA, contenu RÉEL affiché,
saisie au clavier, Tab, enregistrement (complet et incrémental), réparation des paquets écrits par PDFium,
réouverture et vérification des DONNÉES (paquet datasets).

Fixtures (tests/fixtures/pdf/SOURCES.md) : formulaires réels publics du corpus de pdf.js (ACIA, IRCC, HSBC) et
tests de PDFium."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import io
import re
import unittest

import _pdf_samples as S
from _lent import lent
from fm_pdf import incremental, xfa_packets, xfa_save
from fm_pdf.worker import get_engine


def _first_field(doc, page, wanted=15, step=6):
    """Centre (points écran) du premier champ de type `wanted` (15 = texte XFA) en balayant la page."""
    w, h = doc.page_size(page)
    for y in range(step, int(h), step):
        for x in range(step, int(w), step):
            if doc.field_at(page, x, y) == wanted:
                return x + 2, y + 2
    return None


def _ink(doc, page, scale=0.5):
    data, w, h, stride = doc.render(page, scale)
    return sum(1 for k in range(0, len(data), 16) if data[k] < 200)


class PacketRepairTest(unittest.TestCase):
    def test_exact_inverse_of_pdfium_writers(self):
        written = (b'<xfa:datasets xmlns:xfa="http://www.xfa.org/schema/xfa-data/1.0/">\n<xfa:data>\n<form1>\n'
                   b'<Nom>\nDurand</Nom>\n<Vide />\n<Code>\n01</Code>\n<Note><![CDATA[a > b]]></Note>\n'
                   b'<Liste>\n\n\t<Item lic="1">\nUn</Item>\n</Liste>\n</form1>\n</xfa:data>\n</xfa:datasets>\n')
        fixed = xfa_packets.undo_pdfium_newlines(written)
        self.assertEqual(fixed, b'<xfa:datasets xmlns:xfa="http://www.xfa.org/schema/xfa-data/1.0/"><xfa:data>'
                                b'<form1><Nom>Durand</Nom><Vide /><Code>01</Code><Note><![CDATA[a > b]]></Note>'
                                b'<Liste>\n\t<Item lic="1">Un</Item></Liste></form1></xfa:data></xfa:datasets>')
        self.assertTrue(xfa_packets.looks_pdfium_written(written))
        self.assertFalse(xfa_packets.looks_pdfium_written(fixed))

    def test_list_body_values_keep_their_text(self):
        form = (b'<form xmlns="http://www.xfa.org/schema/xfa-form/2.8/">\n<field name="L">\n<value>\n'
                b'<exData contentType="text/xml">\n<ListBox1 xmlns="">\n<value>A</value>\n<value>B</value>\n'
                b'</ListBox1>\n</exData>\n</value>\n</field>\n</form>\n')
        self.assertEqual(xfa_packets.undo_pdfium_newlines(form),
                         b'<form xmlns="http://www.xfa.org/schema/xfa-form/2.8/"><field name="L"><value>'
                         b'<exData contentType="text/xml"><ListBox1 xmlns=""><value>A</value><value>B</value>'
                         b'</ListBox1></exData></value></field></form>')


class IncrementalTest(unittest.TestCase):
    def test_original_bytes_untouched_and_stream_replaced(self):
        import pikepdf
        pdf = pikepdf.new()
        pdf.add_blank_page()
        stream = pdf.make_stream(b"ancien")
        pdf.Root.Essai = stream
        out = io.BytesIO()
        pdf.save(out)
        data = out.getvalue()
        with pikepdf.open(io.BytesIO(data)) as again:              # qpdf renumérote à l'écriture
            objgen = again.Root.Essai.objgen
        updated = incremental.replace_streams(data, {objgen: b"nouveau contenu"})
        self.assertTrue(updated.startswith(data))                  # aucun octet d'origine modifié
        with pikepdf.open(io.BytesIO(updated)) as again:
            self.assertEqual(again.Root.Essai.read_bytes(), b"nouveau contenu")
            self.assertEqual(len(again.pages), 1)
        out = io.BytesIO()                                          # fichier à flux de références (PDF 1.5+)
        pdf.save(out, object_stream_mode=pikepdf.ObjectStreamMode.generate)
        data = out.getvalue()
        with pikepdf.open(io.BytesIO(data)) as again:
            objgen = again.Root.Essai.objgen
        updated = incremental.replace_streams(data, {objgen: b"bis"})
        with pikepdf.open(io.BytesIO(updated)) as again:
            self.assertEqual(again.Root.Essai.read_bytes(), b"bis")


COMPANY_NAME = (100.0, 190.0)        # « Company Name » (points, page 1 du formulaire de l'ACIA)
CITY = (380.0, 218.0)                # « City »


@unittest.skipUnless(S.has_fixture("xfa_fish_licence.pdf"), "fixture absente")
class XfaFillTest(unittest.TestCase):
    """Formulaire XFA DYNAMIQUE réel (ACIA, demande de licence) : rempli, enregistré, rouvert."""

    def test_real_content_instead_of_please_wait(self):
        eng = get_engine()
        data = S.fixture("xfa_fish_licence.pdf")

        def go():
            fallback = eng.open_document(data, "f.pdf", xfa=False)
            try:
                text = fallback.text(0)
                ink_fallback = _ink(fallback, 0)
            finally:
                eng.close_document(fallback)
            doc = eng.open_document(data, "f.pdf")
            try:
                return text, ink_fallback, doc.form_kind, doc.xfa_loaded, _ink(doc, 0), _first_field(doc, 0)
            finally:
                eng.close_document(doc)
        text, ink_fallback, kind, loaded, ink, field = eng.call(go)
        self.assertIn("Please wait", text)                          # le document est bien un « Please wait »
        self.assertEqual(kind, "xfa_dynamique")
        self.assertTrue(loaded)
        self.assertGreater(ink, ink_fallback * 3)                   # vrai contenu du formulaire
        self.assertIsNotNone(field)                                 # et de vrais champs

    def test_type_tab_save_reopen(self):
        eng = get_engine()
        data = S.fixture("xfa_fish_licence.pdf")

        def fill(incremental_save):
            doc = eng.open_document(data, "f.pdf")
            try:
                x, y = COMPANY_NAME
                self.assertEqual(doc.field_at(0, x, y), 15)           # texte XFA
                for kind in ("move", "down", "up"):
                    doc.mouse(0, kind, x, y)
                doc.select_all(0)
                doc.type_text(0, "Saisie Émile 42")
                typed = doc.focused_text(0)
                tab = lambda shift: (doc.key(0, "down", 0x09, shift), doc.key(0, "up", 0x09, shift))
                tab(0)
                away = doc.focused_text(0)                            # « Licence Type » : une liste
                tab(1)
                back = doc.focused_text(0)                            # Maj + Tab : retour au nom
                for kind in ("move", "down", "up"):
                    doc.mouse(0, kind, *CITY)
                doc.type_text(0, "Ottawa")
                city = doc.focused_text(0)
                out, repaired = doc.save_bytes(incremental=incremental_save)
                return typed, away, back, city, out, repaired
            finally:
                eng.close_document(doc)
        for inc in (False, True):
            typed, away, back, city, saved, repaired = eng.call(lambda: fill(inc))
            self.assertEqual(typed, "Saisie Émile 42")
            self.assertNotEqual(away, typed)                          # Tab : focus ailleurs
            self.assertEqual(back, typed)                             # Maj + Tab : revenu au champ
            self.assertEqual(city, "Ottawa")
            self.assertIn("datasets", repaired)
            if inc:
                self.assertTrue(saved.startswith(data))               # incrémental : octets d'origine intacts

            def reopen():
                doc = eng.open_document(saved, "f.pdf")
                try:
                    for kind in ("move", "down", "up"):
                        doc.mouse(0, kind, *COMPANY_NAME)
                    shown = doc.focused_text(0)
                    return doc.xfa_loaded, doc.xfa_packets().get("datasets", b""), _ink(doc, 0), shown
                finally:
                    eng.close_document(doc)
            loaded, datasets, ink, shown = eng.call(reopen)
            self.assertTrue(loaded)
            self.assertEqual(shown, "Saisie Émile 42")                 # rouvert : sans saut de ligne parasite
            self.assertIn("<companyName>Saisie Émile 42</companyName>".encode("utf-8"), datasets)
            self.assertIn(b"<companyCity>Ottawa</companyCity>", datasets)
            self.assertFalse(xfa_packets.looks_pdfium_written(datasets))
            self.assertGreater(ink, 0)


@lent
@unittest.skipUnless(S.has_fixture("xfa_filled_imm1344e.pdf"), "fixture absente")
class XfaImm1344Test(unittest.TestCase):
    """IRCC IMM 1344 (XFA dynamique, 10 -> 14 pages après mise en page, ~5-7 s d'ouverture) : nom, Tab, prénom,
    enregistrement incrémental, réouverture ; toutes les autres données intactes (listes « 01 », dates)."""

    def test_full_journey(self):
        eng = get_engine()
        data = S.fixture("xfa_filled_imm1344e.pdf")
        original = {k: v for k, v in xfa_save.packet_streams(data).items()}

        def fill():
            doc = eng.open_document(data, "imm1344e.pdf")
            try:
                self.assertEqual(doc.page_count(), 14)
                for kind in ("move", "down", "up"):
                    doc.mouse(0, kind, 100 / 1.5, 330 / 1.5)        # « Family Name » de la personne parrainée
                self.assertEqual(doc.focused_text(0), "Euler")
                doc.select_all(0)
                doc.type_text(0, "Bernoulli")
                doc.key(0, "down", 0x09)
                doc.key(0, "up", 0x09)
                self.assertEqual(doc.focused_text(0), "Leonhard")
                doc.select_all(0)
                doc.type_text(0, "Jakob")
                return doc.save_bytes(incremental=True)
            finally:
                eng.close_document(doc)
        saved, repaired = eng.call(fill)
        self.assertTrue(saved.startswith(data))
        after = xfa_save.packet_streams(saved)
        ds = after["datasets"][1]
        self.assertIn(b"<PAFamilyName>Bernoulli</PAFamilyName>", ds)
        self.assertIn(b"<PAGivenName>Jakob</PAGivenName>", ds)
        self.assertIn(b"<LangPref>01</LangPref>", ds)
        self.assertNotIn(b"<LangPref>\n", ds)
        self.assertIn(b"<PAFamilyName>Euler</PAFamilyName>", original["datasets"][1])


if __name__ == "__main__":
    unittest.main()
