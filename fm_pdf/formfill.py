"""Environnement de formulaire PDFium (sans Qt) : rappels `FPDF_FORMFILLINFO` + `IPDF_JSPLATFORM`.

Tout s'exécute sur le FIL DU MOTEUR (worker.py). Les rappels ne font qu'enregistrer des ÉVÉNEMENTS (zones à
repeindre, focus, curseur, caret XFA, navigation demandée, changement du nombre de pages) que le document remet à
l'interface après chaque tâche (`Document.take_events`).

SÉCURITÉ (contenu actif d'un document non fiable) : PDFium n'a lui-même aucun accès aux fichiers ni au réseau depuis
le JavaScript ; tout passe par ces rappels. Ici, RIEN ne sort : envoi de formulaire, courriel, téléchargement,
requêtes POST / PUT, ouverture de fichier, parcours de fichier = REFUSÉS et notés (`blocked`, montrés à
l'utilisateur) ; liens (URI, GotoURL) = demandés à l'interface, qui demande l'accord de l'utilisateur ; impression
demandée par un script = événement (l'interface décide). Les alertes / questions des scripts passent par
`ask` (posé par l'interface ; défaut : réponse neutre immédiate).
"""
from __future__ import annotations

import ctypes
import time

# Types de champs renvoyés par FPDFPage_HasFormFieldAtPoint (fpdf_formfill.h).
FIELD_TYPES = {
    0: "inconnu", 1: "bouton", 2: "case", 3: "radio", 4: "liste déroulante", 5: "liste", 6: "texte",
    7: "signature", 8: "XFA", 9: "case XFA", 10: "liste déroulante XFA", 11: "image XFA", 12: "liste XFA",
    13: "bouton XFA", 14: "signature XFA", 15: "texte XFA",
}
TEXT_TYPES = {6, 15}
# Curseurs demandés (FFI_SetCursor)
CURSORS = {0: "arrow", 1: "nesw", 2: "nwse", 3: "vbeam", 4: "hbeam", 5: "hand"}


def wide(ptr) -> str:
    """FPDF_WIDESTRING (UTF-16LE terminé par 0) -> str."""
    if not ptr:
        return ""
    raw = bytearray()
    p = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ubyte))
    i = 0
    while i < 1 << 20:
        a, b = p[i], p[i + 1]
        if a == 0 and b == 0:
            break
        raw += bytes((a, b))
        i += 2
    return raw.decode("utf-16-le", "replace")


def put_wide(buf, size: int, text: str) -> int:
    """Écrit `text` en UTF-16LE terminé par 0 dans `buf` (si assez grand) ; renvoie la taille nécessaire."""
    raw = text.encode("utf-16-le") + b"\0\0"
    if buf and size >= len(raw):
        ctypes.memmove(buf, raw, len(raw))
    return len(raw)


class FormHost:
    """Rappels d'UN document. `doc` : le Document (engine.py) qui reçoit les événements."""

    def __init__(self, lib, doc, timers, *, javascript: bool = True, xfa: bool = True):
        self.c = lib
        self.doc = doc
        self.timers = timers                # Engine : add_timer(ms, fn) -> id, kill_timer(id)
        self._keep = []                     # rappels ctypes gardés en vie
        c = lib
        self.js = None
        if javascript:
            js = c.IPDF_JSPLATFORM()
            js.version = 3
            self._set(js, "app_alert", self._app_alert)
            self._set(js, "app_beep", lambda s, kind: None)
            self._set(js, "app_response", self._app_response)
            self._set(js, "Doc_getFilePath", self._doc_path)
            self._set(js, "Doc_mail", lambda *a: self._block("courriel (Doc.mail)"))
            self._set(js, "Doc_print", lambda s, ui, start, end, silent, shrink, fit, reverse, annots:
                      self.doc.post(("print_request",)))
            self._set(js, "Doc_submitForm", lambda *a: self._block("envoi du formulaire (submitForm)"))
            self._set(js, "Doc_gotoPage", lambda s, page: self.doc.post(("goto", int(page), None)))
            self._set(js, "Field_browse", lambda s, buf, n: (self._block("choix d'un fichier (browseForDoc)"), 0)[1])
            self.js = js
        info = c.FPDF_FORMFILLINFO()
        info.version = 2
        info.xfa_disabled = 0 if xfa else 1
        info.m_pJsPlatform = ctypes.pointer(self.js) if self.js is not None else None
        f = self._set
        f(info, "FFI_Invalidate", lambda s, page, l, t, r, b: self.doc.on_invalidate(page, l, t, r, b))
        f(info, "FFI_OutputSelectedRect", lambda s, page, l, t, r, b: self.doc.on_selected_rect(page, l, t, r, b))
        f(info, "FFI_SetCursor", lambda s, kind: self.doc.post(("cursor", CURSORS.get(int(kind), "arrow"))))
        f(info, "FFI_SetTimer", lambda s, ms, fn: self.timers.add_timer(int(ms), fn, self.doc))
        f(info, "FFI_KillTimer", lambda s, tid: self.timers.kill_timer(int(tid)))
        # FFI_GetLocalTime renvoie une structure : impossible en rappel ctypes, laissé vide (repli de PDFium).
        f(info, "FFI_OnChange", lambda s: self.doc.on_form_change())
        f(info, "FFI_GetPage", lambda s, d, index: self.doc.page_address(int(index)))
        f(info, "FFI_GetCurrentPage", lambda s, d: self.doc.page_address(self.doc.current_page))
        f(info, "FFI_GetRotation", lambda s, page: 0)
        f(info, "FFI_ExecuteNamedAction", lambda s, name: self.doc.post(("named_action", ctypes.string_at(name).decode(
            "latin-1", "replace") if name else "")))
        f(info, "FFI_SetTextFieldFocus", lambda s, value, n, focus: self.doc.post(("text_focus", bool(focus))))
        f(info, "FFI_DoURIAction", lambda s, uri: self.doc.post(("uri", ctypes.string_at(uri).decode(
            "latin-1", "replace") if uri else "")))
        f(info, "FFI_DoGoToAction", self._goto)
        f(info, "FFI_DisplayCaret", lambda s, page, visible, l, t, r, b: self.doc.on_caret(page, visible, l, t, r, b))
        f(info, "FFI_GetCurrentPageIndex", lambda s, d: int(self.doc.current_page))
        f(info, "FFI_SetCurrentPage", lambda s, d, index: self.doc.post(("goto", int(index), None)))
        f(info, "FFI_GotoURL", lambda s, d, url: self.doc.post(("uri", wide(url))))
        f(info, "FFI_GetPageViewRect", self._view_rect)
        f(info, "FFI_PageEvent", lambda s, count, event: self.doc.on_page_event(int(count), int(event)))
        f(info, "FFI_PopupMenu", lambda *a: 0)
        f(info, "FFI_OpenFile", lambda *a: (self._block("ouverture d'un fichier par le formulaire"), None)[1])
        f(info, "FFI_EmailTo", lambda *a: self._block("envoi par courriel"))
        f(info, "FFI_UploadTo", lambda *a: self._block("téléversement"))
        f(info, "FFI_GetPlatform", lambda s, buf, n: put_wide(buf, n, "WIN"))
        f(info, "FFI_GetLanguage", lambda s, buf, n: put_wide(buf, n, self.doc.language))
        f(info, "FFI_DownloadFromURL", lambda s, url: (self._block("téléchargement : " + wide(url)), None)[1])
        f(info, "FFI_PostRequestURL", lambda s, url, *a: (self._block("requête réseau POST : " + wide(url)), 0)[1])
        f(info, "FFI_PutRequestURL", lambda s, url, *a: (self._block("requête réseau PUT : " + wide(url)), 0)[1])
        f(info, "FFI_OnFocusChange", lambda s, annot, index: self.doc.post(("focus", int(index))))
        f(info, "FFI_DoURIActionWithKeyboardModifier", lambda s, uri, mods: self.doc.post(
            ("uri", ctypes.string_at(uri).decode("latin-1", "replace") if uri else "")))
        self.info = info

    def _set(self, struct, name, fn):
        ftype = dict(type(struct)._fields_)[name]
        cb = ftype(self._guard(name, fn))
        self._keep.append(cb)
        setattr(struct, name, cb)

    def _guard(self, name, fn):
        """Une exception Python dans un rappel ne doit jamais remonter dans PDFium : notée, valeur neutre."""
        def run(*args):
            try:
                return fn(*args)
            except Exception as exc:                        # noqa: BLE001
                self.doc.post(("error", f"rappel {name} : {exc!r}"))
                return 0                                    # 0 / NULL : valeur neutre pour tous les types
        return run

    def _block(self, what: str):
        self.doc.post(("blocked", what))
        self.doc.blocked.append((time.time(), what))

    def _app_alert(self, s, msg, title, kind, icon):
        return int(self.doc.ask("alert", wide(title) or "Message du document", wide(msg), int(kind)) or 1)

    def _app_response(self, s, question, title, default, label, password, buf, size):
        answer = self.doc.ask("response", wide(title) or "Question du document", wide(question), wide(default))
        if answer is None:
            return 0
        return put_wide(buf, size, str(answer)) if size else put_wide(None, 0, str(answer))

    def _doc_path(self, s, buf, size):
        raw = (self.doc.path or "").encode("utf-8") + b"\0"
        if buf and size >= len(raw):
            ctypes.memmove(buf, raw, len(raw))
        return len(raw)

    def _goto(self, s, page_index, zoom_mode, pos_array, array_size):
        pos = [pos_array[i] for i in range(array_size)] if pos_array and array_size > 0 else None
        self.doc.post(("goto", int(page_index), pos))

    def _view_rect(self, s, page, left, top, right, bottom):
        l, t, r, b = self.doc.view_rect_for(page)
        left[0], top[0], right[0], bottom[0] = l, t, r, b
