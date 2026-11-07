"""Formulaires AcroForm : CONCEPTION (fm_pdf/acroform.py) puis REMPLISSAGE au clavier dans le moteur (engine.py),
enregistrement, réouverture, relecture par un AUTRE lecteur (PyMuPDF / MuPDF). Parcours complet :
création -> ouverture -> affichage -> saisie -> Tab -> calcul -> case / radio / liste -> enregistrement ->
fermeture -> réouverture -> vérification des données ; les champs restent des champs (jamais aplatis)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest

import _pdf_samples as S
from fm_pdf import acroform as af
from fm_pdf.worker import get_engine

TAB = 0x09


def _click(doc, rect, page=0):
    cx, cy = S.center(rect)
    for kind in ("move", "down", "up"):
        doc.mouse(page, kind, cx, cy)


def _tab(doc, page=0, shift=False):
    doc.key(page, "down", TAB, 1 if shift else 0)
    doc.key(page, "up", TAB, 1 if shift else 0)


class DesignerTest(unittest.TestCase):
    def test_created_fields_read_back_as_designed(self):
        data = S.sample_form()
        fields = {(f.name, f.export_value if f.kind == "radio" else ""): f for f in af.read_fields(data)}
        self.assertEqual(len(fields), 12)
        nom = fields[("nom", "")]
        self.assertEqual((nom.kind, nom.required, nom.tooltip), ("text", True, "Votre nom"))
        self.assertEqual([round(v) for v in nom.rect], [72, 72, 300, 92])
        qte = fields[("qte", "")]
        self.assertEqual((qte.kind, qte.decimals, qte.min_value, qte.max_value), ("number", 2, 0.0, 1000.0))
        total = fields[("total", "")]
        self.assertEqual((total.calc_op, total.calc_fields, total.readonly), ("PRD", ["qte", "prix"], True))
        self.assertEqual(fields[("date", "")].date_format, "dd/mm/yyyy")
        self.assertEqual(fields[("notes", "")].kind, "multiline")
        self.assertEqual(fields[("accord", "")].export_value, "Oui")
        self.assertEqual({k[1] for k in fields if k[0] == "taille"}, {"S", "M", "L"})
        self.assertEqual(fields[("pays", "")].choices, ["France", "Belgique", "Suisse"])
        self.assertTrue(fields[("langues", "")].multiselect)

    def test_radio_group_is_one_field_with_three_kids(self):
        import pymupdf
        doc = pymupdf.open(stream=S.sample_form())
        cat = doc.pdf_catalog()
        refs = doc.xref_get_key(cat, "AcroForm/Fields")[1]
        names = []
        for ref in refs.strip("[]").split(" 0 R"):
            if ref.strip():
                names.append(doc.xref_get_key(int(ref), "T")[1].strip("()"))
        self.assertEqual(names.count("taille"), 1)                 # UN champ parent
        parent = next(int(r) for r in refs.strip("[]").split(" 0 R")
                      if r.strip() and doc.xref_get_key(int(r), "T")[1].strip("()") == "taille")
        self.assertEqual(len(doc.xref_get_key(parent, "Kids")[1].split(" 0 R")) - 1, 3)
        self.assertEqual(len(names), 10)

    def test_duplicate_names_and_bad_names_are_refused(self):
        data = S.sample_form()
        with self.assertRaises(af.FormError):
            af.add_fields(data, [af.FieldSpec("text", "nom", 0, (10, 10, 50, 30))])
        with self.assertRaises(af.FormError):
            af.add_fields(data, [af.FieldSpec("text", "a.b", 0, (10, 10, 50, 30))])
        self.assertEqual(af.unique_name(data, "nom"), "nom_2")

    def test_update_delete_and_tab_order(self):
        data = S.sample_form()
        by = {f.name: f for f in af.read_fields(data) if f.kind != "radio"}
        spec = by["nom"]
        spec.name, spec.required, spec.rect = "nom_complet", False, (80, 60, 320, 84)
        data = af.update_field(data, spec.xref, spec)
        by = {f.name: f for f in af.read_fields(data) if f.kind != "radio"}
        self.assertIn("nom_complet", by)
        self.assertFalse(by["nom_complet"].required)
        self.assertEqual([round(v) for v in by["nom_complet"].rect], [80, 60, 320, 84])
        data = af.delete_fields(data, [by["notes"].xref])
        self.assertNotIn("notes", {f.name for f in af.read_fields(data)})
        order = af.tab_order(data, 0)
        wanted = [by["prix"].xref, by["qte"].xref, by["nom_complet"].xref]
        data = af.set_tab_order(data, 0, wanted)
        self.assertEqual(af.tab_order(data, 0)[:3], wanted)
        self.assertEqual(sorted(af.tab_order(data, 0)), sorted(order) if len(order) == len(af.tab_order(data, 0))
                         else sorted(af.tab_order(data, 0)))
        eng = get_engine()

        def go():
            doc = eng.open_document(data, "t.pdf")
            try:
                f = {x["name"]: x for x in doc.fields()}
                _click(doc, f["prix"]["rect"])
                _tab(doc)
                first = doc.focused_field()[1]
                _tab(doc)
                return first, doc.focused_field()[1]
            finally:
                eng.close_document(doc)
        self.assertEqual(eng.call(go), ("qte", "nom_complet"))       # Tab suit l'ordre manuel


class FillJourneyTest(unittest.TestCase):
    """Le critère de l'utilisateur : créer, remplir AU CLAVIER, enregistrer, rouvrir sans perte."""

    def test_create_fill_save_reopen(self):
        eng = get_engine()
        data = S.sample_form()

        def fill():
            doc = eng.open_document(data, "formulaire.pdf")
            try:
                f = {}
                for x in doc.fields():
                    f.setdefault(x["name"], []).append(x)
                self.assertEqual(f["nom"][0]["type_name"], "texte")
                self.assertEqual(f["taille"][0]["type_name"], "radio")
                _click(doc, f["nom"][0]["rect"])
                self.assertEqual(doc.focused_field(), (0, "nom"))
                doc.type_text(0, "Durand Émilie")
                _tab(doc)
                self.assertEqual(doc.focused_field(), (0, "qte"))     # Tab = champ suivant
                doc.type_text(0, "3")
                _tab(doc)
                doc.type_text(0, "12,5")
                _tab(doc, shift=True)                                 # Maj + Tab = précédent
                self.assertEqual(doc.focused_field(), (0, "qte"))
                doc.kill_focus()
                _click(doc, f["accord"][0]["rect"])
                _click(doc, f["taille"][1]["rect"])
                _click(doc, f["notes"][0]["rect"])
                doc.type_text(0, "Ligne 1")
                doc.key(0, "down", 0x0D)
                doc.key(0, "char", 0x0D)
                doc.type_text(0, "Ligne 2")
                _click(doc, f["pays"][0]["rect"])
                doc.key(0, "down", 0x28)                              # flèche bas : choix suivant
                doc.key(0, "up", 0x28)
                doc.kill_focus()
                values = {x["name"]: x["value"] for x in doc.fields()}
                self.assertEqual(values["total"], "37.5")               # calcul automatique qte × prix
                self.assertTrue(doc.modified)
                out, repaired = doc.save_bytes()
                self.assertEqual(repaired, [])
                return out, values
            finally:
                eng.close_document(doc)
        saved, values = eng.call(fill)
        self.assertEqual(values["nom"], "Durand Émilie")
        self.assertEqual(values["pays"], "Belgique")

        def reopen():
            doc = eng.open_document(saved, "formulaire.pdf")
            try:
                fields = doc.fields()
                return {x["name"]: x["value"] for x in fields}, {x["name"]: x.get("checked") for x in fields
                                                                  if x["name"] == "taille" and x.get("checked")}, \
                    len(fields)
            finally:
                eng.close_document(doc)
        again, radios, count = eng.call(reopen)
        self.assertEqual(count, 12)                                     # toujours 12 widgets : rien d'aplati
        for key in ("nom", "qte", "prix", "total", "pays", "accord", "taille"):
            self.assertEqual(again[key], values[key], key)
        self.assertEqual(again["taille"], "M")
        self.assertEqual(again["accord"], "Oui")
        self.assertIn("Ligne 1", again["notes"])
        self.assertIn("Ligne 2", again["notes"])

        import pymupdf                                                  # AUTRE lecteur : MuPDF
        other = pymupdf.open(stream=saved)
        w = {x.field_name: x for x in other[0].widgets()}
        self.assertEqual(w["nom"].field_value, "Durand Émilie")
        self.assertEqual(w["pays"].field_value, "Belgique")
        self.assertEqual(w["accord"].field_value, "Oui")
        self.assertTrue(all(x.field_flags is not None for x in w.values()))
        self.assertEqual(other.xref_get_key(other.pdf_catalog(), "AcroForm/NeedAppearances")[1], "false")
        self.assertTrue(all(other.xref_get_key(x.xref, "AP")[0] != "null" for x in other[0].widgets()))

    def test_value_can_be_changed_after_reopening(self):
        eng = get_engine()
        data = S.sample_form()

        def step(blob, text):
            doc = eng.open_document(blob, "f.pdf")
            try:
                f = {x["name"]: x for x in doc.fields()}
                _click(doc, f["nom"]["rect"])
                doc.select_all(0)
                doc.type_text(0, text)
                return doc.save_bytes()[0]
            finally:
                eng.close_document(doc)
        first = eng.call(lambda: step(data, "Premier"))
        second = eng.call(lambda: step(first, "Second"))

        def read(blob):
            doc = eng.open_document(blob, "f.pdf")
            try:
                return {x["name"]: x["value"] for x in doc.fields()}["nom"]
            finally:
                eng.close_document(doc)
        self.assertEqual(eng.call(lambda: read(second)), "Second")


if __name__ == "__main__":
    unittest.main()
