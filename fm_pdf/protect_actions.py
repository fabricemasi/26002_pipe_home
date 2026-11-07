"""Actions de l'outil « Protéger » (Qt) : zones de caviardage tracées sur la page puis appliquées (suppression
RÉELLE, vérifiée), caviardage des résultats de recherche, chiffrement, retrait du chiffrement et des métadonnées,
signature visuelle (image, SANS valeur cryptographique — dit à l'utilisateur), signature numérique (pyHanko,
enregistrée dans un nouveau fichier comme dans Acrobat) et vérification des signatures."""
from __future__ import annotations

import pathlib

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QFileDialog

from . import security, ui_kit


class RectPlacer:
    """Surcouche : glisser un rectangle sur une page -> callback(page, rect en points du moteur). Les zones
    `marks` [(page, rect)] sont peintes (caviardage en attente). `default_size` (l, h en points) : un simple CLIC
    pose un rectangle de cette taille à cet endroit (signatures ; sans lui, un clic sans glisser ne faisait rien,
    piège signalé par l'utilisateur)."""

    def __init__(self, callback, color="#d32f2f", keep=True, default_size=None, on_cancel=None):
        self.callback = callback
        self.color = QColor(color)
        self.keep = keep
        self.default_size = default_size
        self.on_cancel = on_cancel
        self.marks: list = []
        self._drag = None

    def paint(self, painter, view):
        fill = QColor(self.color)
        fill.setAlpha(70)
        for page, rect in self.marks:
            if page in view._visible_indexes():
                r = view.engine_rect_to_view(page, rect)
                painter.fillRect(r, fill)
                painter.setPen(QPen(self.color, 1))
                painter.drawRect(r)
        if self._drag and self._drag.get("end") is not None:
            painter.setPen(QPen(self.color, 1, Qt.DashLine))
            painter.drawRect(QRectF(self._drag["start"], self._drag["end"]).normalized())

    def press(self, view, event, hit):
        if event.button() != Qt.LeftButton or hit is None:
            return False
        self._drag = {"page": hit[0], "start": event.position(), "end": None}
        return True

    def move(self, view, event, hit):
        if self._drag is None:
            view.viewport().setCursor(Qt.CrossCursor)
            return True
        self._drag["end"] = event.position()
        view.viewport().update()
        return True

    def release(self, view, event, hit):
        d, self._drag = self._drag, None
        if d is None:
            return True
        page = d["page"]
        pr = view.page_rect(page)
        r = QRectF(d["start"], d["end"] or d["start"]).normalized()
        if (r.width() < 4 or r.height() < 4) and self.default_size:       # simple clic : taille standard
            w, h = self.default_size
            r = QRectF(d["start"].x(), d["start"].y(), w * view.zoom, h * view.zoom)
        a = view.to_engine(page, (r.left() - pr.left()) / view.zoom, (r.top() - pr.top()) / view.zoom)
        b = view.to_engine(page, (r.right() - pr.left()) / view.zoom, (r.bottom() - pr.top()) / view.zoom)
        rect = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        if rect[2] - rect[0] > 2 and rect[3] - rect[1] > 2:
            if self.keep:
                self.marks.append((page, rect))
            self.callback(page, rect)
        view.viewport().update()
        return True

    def double(self, view, event, hit):
        return True

    def key(self, view, event):
        if event.key() == Qt.Key_Escape:
            view.set_overlay(None)
            if self.on_cancel:
                self.on_cancel()
            return True
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.marks:
            self.marks.pop()
            view.viewport().update()
            return True
        return False


def _placer(pane):
    return getattr(pane, "_redact_placer", None)


def leave(pane) -> None:
    placer = _placer(pane)
    if placer is not None and pane.view.overlay is placer:
        pane.view.set_overlay(None)


def redact_tool(pane) -> None:
    placer = _placer(pane)
    if placer is None:
        placer = pane._redact_placer = RectPlacer(lambda page, rect: pane.status(
            "%d zone(s) à caviarder (Suppr : retirer la dernière ; « Appliquer le caviardage » pour supprimer le "
            "contenu)" % len(pane._redact_placer.marks)))
    pane.view.set_overlay(None if pane.view.overlay is placer else placer)


def redact_search(pane) -> None:
    hits = pane.view.search_hits
    if not hits:
        pane.status("Lancez d'abord une recherche : toutes ses occurrences seront marquées")
        return
    placer = _placer(pane)
    if placer is None:
        redact_tool(pane)
        placer = _placer(pane)
    for page, items in hits.items():
        for _start, _count, rects in items:
            for r in rects:
                placer.marks.append((page, tuple(r)))
    pane.view.set_overlay(placer)
    pane.status("%d zone(s) marquées : vérifiez puis « Appliquer le caviardage »" % len(placer.marks))


def apply_redactions(pane) -> None:
    placer = _placer(pane)
    if placer is None or not placer.marks:
        pane.status("Aucune zone à caviarder")
        return
    marks = list(placer.marks)
    if not ui_kit.confirm(pane, "Caviarder", "Le texte, les images et les tracés sous %d zone(s) vont être "
                          "SUPPRIMÉS du document (vérifié après coup). Annuler reste possible avant "
                          "l'enregistrement." % len(marks), "Caviarder"):
        return
    password = pane.session.password

    def fn(data):
        return security.redact(data, marks, password=password)

    def done(report, error):
        if error is not None:
            pane.status("Caviardage refusé : %s" % error)
            return
        placer.marks.clear()
        pane.view.set_overlay(None)
        pane.status("Caviardage appliqué et vérifié : %d zone(s), aucun texte récupérable" % report["zones"])
    pane.session.edit("Caviarder %d zone(s)" % len(marks), fn, done)


def encrypt(pane) -> None:
    user = ui_kit.ask_text(pane, "Chiffrer (AES-256)", "Mot de passe d'OUVERTURE (vide : le document s'ouvre sans "
                           "mot de passe, avec des permissions restreintes)", password=True, action="Suivant")
    if user is None:
        return
    owner = ui_kit.ask_text(pane, "Chiffrer (AES-256)", "Mot de passe du PROPRIÉTAIRE (permissions)", password=True,
                            action="Chiffrer")
    if owner is None or not (user or owner):
        pane.status("Il faut au moins un mot de passe")
        return
    old = pane.session.password
    pane.session.password = user or None
    pane.session.edit("Chiffrer", lambda d: security.encrypt(d, user, owner, password=old),
                      lambda _x, err: pane.status("Chiffrement impossible : %s" % err if err else
                                                  "Chiffré (AES-256) : enregistrez pour l'écrire sur le disque"))


def decrypt(pane) -> None:
    pw = pane.session.password
    pane.session.edit("Retirer le chiffrement", lambda d: security.decrypt(d, pw),
                      lambda _x, err: pane.status("Impossible : %s" % err if err else "Chiffrement retiré"))


def strip_metadata(pane) -> None:
    pw = pane.session.password
    pane.session.edit("Retirer les métadonnées", lambda d: security.strip_metadata(d, pw),
                      lambda _x, err: pane.status("Impossible : %s" % err if err else
                                                  "Métadonnées retirées (Info et XMP)"))


def _text_signature_png(text: str) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QFont, QFontMetrics, QImage, QPainter
    font = QFont("Segoe Script", 48)
    m = QFontMetrics(font)
    w, h = m.horizontalAdvance(text) + 40, m.height() + 20
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setFont(font)
    p.setPen(QColor(20, 40, 120))
    p.drawText(img.rect(), Qt.AlignCenter, text)
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def _place_signature(pane, placed, what: str) -> None:
    """Dernière étape (souvent manquée : la consigne n'était que dans la ligne d'état) : bandeau bien visible, un
    clic suffit (taille standard), ou glisser pour choisir la taille ; Échap annule."""
    def done(page, rect):
        pane.banner.hide()
        placed(page, rect)
    pane.view.set_overlay(RectPlacer(done, "#1e40af", keep=False, default_size=(180, 54),
                                     on_cancel=lambda: (pane.banner.hide(), pane.status("Signature annulée"))))
    pane._banner("%s — dernière étape : CLIQUEZ sur la page à l'endroit où la signature doit apparaître (ou glissez "
                 "un rectangle pour choisir sa taille). Échap : annuler." % what)
    pane.view.setFocus()


def visual_signature(pane) -> None:
    choice = ui_kit.choose(pane, "Signature visuelle", "Une signature VISUELLE est une image posée sur la page : "
                           "elle n'a AUCUNE valeur cryptographique (utilisez « Signer numériquement » pour une "
                           "signature vérifiable).", [("text", "Écrire mon nom"), ("image", "Image…")])
    if choice is None:
        return
    if choice == "image":
        path, _ = QFileDialog.getOpenFileName(pane, "Image de signature", "", "Images (*.png *.jpg *.jpeg)")
        if not path:
            return
        image = pathlib.Path(path).read_bytes()
    else:
        text = ui_kit.ask_text(pane, "Signature visuelle", "Nom à écrire", action="Placer")
        if not text:
            return
        image = _text_signature_png(text)
    pw = pane.session.password

    def placed(page, rect):
        pane.view.set_overlay(None)
        pane.session.edit("Signature visuelle", lambda d: security.insert_image(d, page, rect, image, pw),
                          lambda _x, err: pane.status("Impossible : %s" % err if err else
                                                      "Signature visuelle posée (non cryptographique)"))
    _place_signature(pane, placed, "Signature VISUELLE")


def digital_signature(pane) -> None:
    if pane.session.info.get("security", {}).get("encrypted"):
        pane.status("Document chiffré : retirez le chiffrement avant de signer")
        return
    choice = ui_kit.choose(pane, "Signer numériquement", "Signature cryptographique (PAdES de base, pyHanko) avec un "
                           "certificat PKCS#12 (.p12 / .pfx). Le document signé est enregistré dans un NOUVEAU "
                           "fichier.", [("file", "Choisir mon certificat…"),
                                        ("self", "Créer un certificat personnel (auto-signé)")])
    if choice is None:
        return
    if choice == "file":
        path, _ = QFileDialog.getOpenFileName(pane, "Certificat", "", "Certificats (*.p12 *.pfx)")
        if not path:
            return
        p12 = pathlib.Path(path).read_bytes()
        passphrase = ui_kit.ask_text(pane, "Certificat", "Phrase de passe du certificat", password=True)
        if passphrase is None:
            return
    else:
        name = ui_kit.ask_text(pane, "Certificat personnel", "Nom du signataire", action="Créer")
        if not name:
            return
        passphrase = ui_kit.ask_text(pane, "Certificat personnel", "Phrase de passe qui protégera le certificat",
                                     password=True, action="Créer")
        if passphrase is None:
            return
        p12 = security.self_signed_pkcs12(name, passphrase)
        target, _ = QFileDialog.getSaveFileName(pane, "Enregistrer le certificat", "%s.p12" % name,
                                                "Certificats (*.p12)")
        if target:
            pathlib.Path(target).write_bytes(p12)
    reason = ui_kit.ask_text(pane, "Signer", "Motif (facultatif)", default="Approuvé", action="Suivant") or ""

    def placed(page, rect):
        pane.view.set_overlay(None)
        stem = pane.session.path.stem if pane.session.path else "document"
        start = str(pane.session.path.with_name(stem + "_signé.pdf")) if pane.session.path else stem + "_signé.pdf"
        out, _ = QFileDialog.getSaveFileName(pane, "Enregistrer le document signé", start, "PDF (*.pdf)")
        if not out:
            return
        from . import fileio

        def job(doc):
            data = doc.save_bytes()[0]
            signed = security.sign(data, p12, passphrase, page_index=page, rect=rect, reason=reason)
            fileio.write_atomic(out, signed, verify=lambda d: fileio.verify_pdf(d))
            return out

        def done(result, error):
            if error is not None:
                pane.status("Signature impossible : %s" % error)
                ui_kit.confirm(pane, "Signature impossible", str(error), "OK")
                return
            pane.open_path(result)
            ui_kit.confirm(pane, "Document signé", "Le document signé est enregistré : %s. Il est rouvert ici. "
                           "Avec un certificat personnel (auto-signé), Acrobat affiche « validité inconnue » tant que "
                           "votre certificat n'est pas ajouté à ses certificats approuvés : la signature est pourtant "
                           "intacte (« Vérifier les signatures »)." % result, "OK")
        pane.session.run(job, 5, done)
    _place_signature(pane, placed, "Signature NUMÉRIQUE")


def verify_signatures(pane) -> None:
    def done(items, error):
        if error is not None:
            pane.status("Vérification impossible : %s" % error)
            return
        if not items:
            pane.status("Aucune signature numérique dans ce document")
            return
        lines = []
        for it in items:
            if it.get("error"):
                lines.append("%s : ILLISIBLE (%s)" % (it["field"], it["error"]))
                continue
            state = "INTACTE" if it["intact"] and it["valid"] else "ALTÉRÉE OU INVALIDE"
            trust = "approuvée (chaîne vers une autorité de Windows)" if it["trusted"] else \
                "NON approuvée (certificat inconnu ou auto-signé)"
            lines.append("%s — %s, %s ; signataire : %s ; couverture : %s ; modifications après : %s" % (
                it["field"], state, trust, it.get("signer", "?"), it.get("coverage", "?"), it.get("modification", "?")))
        ui_kit.confirm(pane, "Signatures", "Révocation non vérifiée (aucun accès réseau).", "OK", items=lines)
    pane.session.run(lambda doc: security.verify(doc.data), 40, done)
