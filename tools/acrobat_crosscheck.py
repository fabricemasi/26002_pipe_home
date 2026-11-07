"""Contre-vérification par ADOBE ACROBAT lui-même (automatisation COM d'Acrobat DC : AcroExch.App / AVDoc, objet
JavaScript des documents). Aucune action réseau ; les fichiers sont écrits dans le dossier donné.

    python tools/acrobat_crosscheck.py <dossier> [acroform] [xfa]

1. « acroform » : le module CRÉE un formulaire (tests/_pdf_samples.sample_form), le REMPLIT au clavier dans son
   moteur et l'enregistre ; Acrobat l'ouvre et RELIT chaque valeur (getField) ; Acrobat REMPLIT ensuite d'autres
   valeurs, recalcule, enregistre ; le module RELIT le fichier d'Acrobat (aller-retour complet, champs intacts).
2. « xfa » : le module remplit le formulaire XFA de l'ACIA (tests/fixtures/pdf/xfa_fish_licence.pdf) et
   l'enregistre (mise à jour incrémentale + réparation des paquets) ; Acrobat l'ouvre et lit le paquet `datasets`
   (`xfa.datasets.saveXML()`) et la valeur rendue du champ (`xfa.resolveNode`).

Sortie : un rapport JSON (stdout + <dossier>/acrobat_crosscheck.json). Délai de garde : chaque étape Acrobat est
bornée (une boîte de dialogue d'Acrobat qui bloque est signalée, rien n'est cliqué à la place de l'utilisateur).
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def _engine_fill_acroform(out: pathlib.Path) -> dict:
    import _pdf_samples as S
    from fm_pdf.worker import get_engine
    eng = get_engine()
    data = S.sample_form()

    def fill():
        doc = eng.open_document(data, str(out))
        try:
            fields = {}
            for f in doc.fields():
                fields.setdefault(f["name"], []).append(f)

            def click(name, k=0):
                x0, y0, x1, y1 = fields[name][k]["rect"]
                for kind in ("move", "down", "up"):
                    doc.mouse(0, kind, (x0 + x1) / 2, (y0 + y1) / 2)
            click("nom")
            doc.type_text(0, "Écrit par PIPE FMZ")
            doc.key(0, "down", 0x09)
            doc.type_text(0, "3")
            doc.key(0, "down", 0x09)
            doc.type_text(0, "12,5")
            doc.kill_focus()
            click("accord")
            click("taille", 2)
            doc.kill_focus()
            values = {f["name"]: f["value"] for f in doc.fields()}
            return doc.save_bytes()[0], values
        finally:
            eng.close_document(doc)
    blob, values = eng.call(fill)
    out.write_bytes(blob)
    return values


def _engine_read(path: pathlib.Path) -> dict:
    from fm_pdf.worker import get_engine
    eng = get_engine()

    def read():
        doc = eng.open_document(path.read_bytes(), str(path))
        try:
            return {f["name"]: f["value"] for f in doc.fields()}, len(doc.fields())
        finally:
            eng.close_document(doc)
    return eng.call(read)


class Acrobat:
    def __init__(self):
        import win32com.client
        self.w = win32com.client
        self.app = win32com.client.Dispatch("AcroExch.App")
        try:
            self.app.Hide()
        except Exception:                                    # noqa: BLE001
            pass

    def open(self, path: pathlib.Path):
        avdoc = self.w.Dispatch("AcroExch.AVDoc")
        if not avdoc.Open(str(path), ""):
            raise RuntimeError("Acrobat n'a pas ouvert %s" % path)
        pddoc = avdoc.GetPDDoc()
        return avdoc, pddoc, pddoc.GetJSObject()

    def close(self, avdoc):
        try:
            avdoc.Close(True)
        except Exception:                                    # noqa: BLE001
            pass

    def quit(self):
        try:
            self.app.CloseAllDocs()
            self.app.Exit()
        except Exception:                                    # noqa: BLE001
            pass


def check_acroform(folder: pathlib.Path, acro: Acrobat) -> dict:
    ours = folder / "cree_par_pipe.pdf"
    typed = _engine_fill_acroform(ours)
    report = {"fichier": str(ours), "saisi_par_le_module": typed}
    avdoc, pddoc, js = acro.open(ours)
    try:
        names = [js.getNthFieldName(k) for k in range(int(js.numFields))]
        seen = {}
        for name in names:
            field = js.getField(name)
            seen[name] = {"type": str(field.type), "value": str(field.value), "required": bool(field.required)}
        report["lu_par_acrobat"] = seen
        report["acrobat_voit_les_memes_valeurs"] = all(
            str(seen.get(k, {}).get("value", "")) in (str(v), str(v).replace(",", ".")) for k, v in typed.items()
            if k in ("nom", "qte", "total", "accord", "taille"))
        js.getField("nom").value = "Rempli dans Acrobat"
        js.getField("qte").value = "4"
        js.getField("pays").value = "Suisse"
        js.getField("taille").value = "S"
        js.calculateNow()
        report["total_calcule_par_acrobat"] = str(js.getField("total").value)
        back = folder / "rempli_par_acrobat.pdf"
        if not pddoc.Save(1, str(back)):                     # PDSaveFull
            raise RuntimeError("Acrobat n'a pas enregistré")
    finally:
        acro.close(avdoc)
    values, count = _engine_read(back)
    report["relu_par_le_module"] = values
    report["widgets_relus"] = count
    report["aller_retour_ok"] = (values.get("nom") == "Rempli dans Acrobat" and values.get("pays") == "Suisse"
                                 and values.get("taille") == "S" and count == 12)
    return report


def check_xfa(folder: pathlib.Path, acro: Acrobat) -> dict:
    from fm_pdf.worker import get_engine
    src = ROOT / "tests" / "fixtures" / "pdf" / "xfa_fish_licence.pdf"
    eng = get_engine()

    def fill():
        doc = eng.open_document(src.read_bytes(), str(src))
        try:
            for kind in ("move", "down", "up"):
                doc.mouse(0, kind, 100.0, 190.0)
            doc.select_all(0)
            doc.type_text(0, "Société PIPE FMZ")
            for kind in ("move", "down", "up"):
                doc.mouse(0, kind, 380.0, 218.0)
            doc.type_text(0, "Montréal")
            return doc.save_bytes(incremental=True)
        finally:
            eng.close_document(doc)
    blob, repaired = eng.call(fill)
    ours = folder / "xfa_rempli_par_pipe.pdf"
    ours.write_bytes(blob)
    report = {"fichier": str(ours), "paquets_repares": repaired}
    avdoc, pddoc, js = acro.open(ours)
    try:
        xml = str(js.xfa.datasets.saveXML())
        report["datasets_contient_nom"] = "<companyName>Société PIPE FMZ</companyName>" in xml
        report["datasets_contient_ville"] = "<companyCity>Montréal</companyCity>" in xml
        try:
            node = js.xfa.resolveNode("form1.Page1.sfLegalStatus.sfLicenceTypeOther.companyName")
            report["valeur_affichee_par_acrobat"] = str(node.rawValue)
        except Exception as exc:                             # noqa: BLE001
            report["valeur_affichee_par_acrobat"] = "non lue (%s)" % exc
    finally:
        acro.close(avdoc)
    return report


def main(argv) -> int:
    folder = pathlib.Path(argv[0]) if argv else ROOT / "tmp_shot" / "acrobat"
    folder.mkdir(parents=True, exist_ok=True)
    which = set(argv[1:]) or {"acroform", "xfa"}
    t0 = time.perf_counter()
    acro = Acrobat()
    report = {}
    try:
        if "acroform" in which:
            try:
                report["acroform"] = check_acroform(folder, acro)
            except Exception as exc:                         # noqa: BLE001
                report["acroform"] = {"erreur": repr(exc)}
        if "xfa" in which:
            try:
                report["xfa"] = check_xfa(folder, acro)
            except Exception as exc:                         # noqa: BLE001
                report["xfa"] = {"erreur": repr(exc)}
    finally:
        acro.quit()
    report["duree_s"] = round(time.perf_counter() - t0, 1)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    (folder / "acrobat_crosscheck.json").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
