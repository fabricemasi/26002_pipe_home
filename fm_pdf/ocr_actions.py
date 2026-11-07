"""OCR depuis l'éditeur (Qt) : choix des pages (numérisées détectées), langue, traitement ASYNCHRONE et ANNULABLE
(rendu des pages dans le fil du moteur, reconnaissance dans un fil à part : la saisie dans les formulaires et le
défilement restent fluides), avancement dans la barre d'état, relecture / correction des lignes reconnues avant
d'ajouter la couche texte (une édition annulable ; le contenu d'origine n'est pas touché)."""
from __future__ import annotations

import ctypes
import threading

from PySide6.QtCore import QObject, Signal

from . import ocr, ui_kit
from .worker import PRIO_BACKGROUND

OCR_DPI = 300


class _Relay(QObject):
    progress = Signal(int, int)
    finished = Signal(object, object)


def ocr_dialog(pane) -> None:
    try:
        langs = ocr.available_languages()
    except ocr.OcrUnavailable as exc:
        pane.status("OCR indisponible : %s" % exc)
        return
    if not langs:
        pane.status("Aucune langue OCR installée dans Windows (Paramètres > Heure et langue)")
        return
    wanted = [t.strip() for t in str(pane.settings.get("pdf_ocr_languages", "fr;en")).split(";") if t.strip()]
    tag = next((l for l in langs for w in wanted if l.lower().startswith(w.lower())), langs[0])

    def scanned(doc):
        return [i for i in range(doc.page_count()) if ocr.is_scanned(doc, i)]

    def detected(pages, error):
        if error is not None:
            pane.status(str(error))
            return
        n = pane.session.info.get("page_count", 0)
        default = ", ".join(str(p + 1) for p in pages[:50]) if pages else "%d" % (pane.view.current + 1)
        text = ui_kit.ask_text(pane, "OCR (%s)" % tag, "%d page(s) numérisée(s) détectée(s). Pages à reconnaître "
                               "(langues installées : %s) :" % (len(pages), ", ".join(langs)), default=default,
                               action="Reconnaître")
        if not text:
            return
        from .pages import parse_ranges
        run_ocr(pane, parse_ranges(text, n), tag)
    pane.session.run(scanned, PRIO_BACKGROUND, detected)


def run_ocr(pane, pages: list[int], tag: str, review: bool = True) -> dict:
    """Lance l'OCR ; renvoie l'état (clé « cancel » : threading.Event pour annuler)."""
    state = {"cancel": threading.Event(), "results": {}, "relay": _Relay()}
    relay = state["relay"]
    relay.progress.connect(lambda k, n: pane.status("OCR : page %d / %d… (Échap dans la barre : annuler)" % (k, n)))
    relay.finished.connect(lambda results, error: _done(pane, results, error, review))
    pane._ocr_state = state
    scale = OCR_DPI / 72.0

    def worker():
        results = {}
        try:
            limit = ocr.max_dimension()
            for k, page in enumerate(pages, 1):
                if state["cancel"].is_set():
                    raise RuntimeError("annulé")
                relay.progress.emit(k, len(pages))

                def render(doc, page=page):
                    w, h = doc.page_size(page)
                    s = min(scale, limit / max(w, h))
                    data, iw, ih, stride = doc.render(page, s, None, forms=False)
                    return s, data, iw, ih, stride
                s, data, iw, ih, stride = pane.session.engine.call(lambda: render(pane.session.doc),
                                                                   PRIO_BACKGROUND, 300)
                if stride != iw * 4:
                    data = b"".join(data[y * stride:y * stride + iw * 4] for y in range(ih))
                results[page] = {"scale": s, "lines": ocr.recognize(data, iw, ih, tag)}
            relay.finished.emit(results, None)
        except Exception as exc:                            # noqa: BLE001
            relay.finished.emit(results, exc)
    threading.Thread(target=worker, name="fm_pdf-ocr", daemon=True).start()
    return state


def cancel(pane) -> None:
    state = getattr(pane, "_ocr_state", None)
    if state:
        state["cancel"].set()


def _done(pane, results, error, review) -> None:
    if error is not None and not results:
        pane.status("OCR interrompu : %s" % error)
        return
    words = sum(len(l["words"]) for r in results.values() for l in r["lines"])
    if review and results:
        lines = [(p, k, l) for p, r in sorted(results.items()) for k, l in enumerate(r["lines"])]
        preview = ["p. %d : %s" % (p + 1, l["text"]) for p, _k, l in lines[:40]]
        choice = ui_kit.choose(pane, "OCR : %d mot(s) reconnus" % words,
                               "Relisez le texte reconnu. « Corriger » ouvre chaque ligne douteuse (jusqu'à 40) "
                               "pour la retoucher avant d'ajouter la couche texte INVISIBLE (l'image ne change pas).",
                               [("apply", "Ajouter la couche texte"), ("fix", "Corriger…")])
        if choice is None:
            return
        if choice == "fix":
            for p, k, line in lines[:40]:
                fixed = ui_kit.ask_text(pane, "Corriger (page %d)" % (p + 1), "Ligne reconnue :",
                                        default=line["text"], action="Suivante")
                if fixed is None:
                    break
                if fixed != line["text"]:
                    _replace_line(line, fixed)
    pane.session.edit("Couche texte OCR (%d page(s))" % len(results), lambda d: ocr.add_text_layer(d, results),
                      lambda _x, err: pane.status("Couche OCR impossible : %s" % err if err else
                                                  "OCR : %d mot(s) ajoutés, texte cherchable et sélectionnable" % words))


def _replace_line(line: dict, text: str) -> None:
    """Ligne corrigée : ses mots sont répartis sur le rectangle de la ligne, au prorata de leur longueur."""
    words = text.split()
    if not words:
        line["words"] = []
        return
    x0, y0, x1, y1 = line["rect"]
    total = sum(len(w) for w in words) + (len(words) - 1)
    x = x0
    out = []
    for w in words:
        width = (x1 - x0) * len(w) / total
        out.append({"text": w, "rect": (x, y0, x + width, y1)})
        x += width + (x1 - x0) / total
    line["words"] = out
    line["text"] = text
