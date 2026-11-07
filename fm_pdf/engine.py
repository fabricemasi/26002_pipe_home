"""Document PDFium (sans Qt) : ouverture, pages, rendu par tuiles, texte, recherche, liens, signets, métadonnées,
formulaires interactifs (AcroForm ET XFA), enregistrement.

RÈGLE : toute méthode s'appelle sur le FIL DU MOTEUR (`worker.Engine`) ; PDFium n'est pas réentrant entre fils.

Repères :
- coordonnées « écran » du module = POINTS, origine en haut à gauche de la page telle qu'affichée (rotation /Rotate
  comprise, + rotation de vue `rotate` 0-3) ; l'interface multiplie par son zoom. Les « coordonnées de page » de
  PDFium ne sont JAMAIS calculées à la main : pour une page XFA, PDFium utilise le repère XFA (origine en haut),
  pour une page PDF le repère PDF (origine en bas) — on passe toujours par FPDF_DeviceToPage / FPDF_PageToDevice
  (mesuré sur l'IMM 1344 : conversion à la main = zones de clic en miroir).
- XFA : après FPDF_LoadXFA, le PREMIER événement de formulaire refait la mise en page (l'IMM 1344 passe de 10 à 14
  pages) et rend les pages déjà chargées périmées : `_settle_xfa` le provoque à l'ouverture, puis toute
  FFI_PageEvent fait recharger les pages APRÈS la tâche en cours (jamais dans le rappel).
"""
from __future__ import annotations

import ctypes
import time

from . import formfill, native, xfa_save

FORM_TYPES = {0: "aucun", 1: "acroform", 2: "xfa_dynamique", 3: "xfa_statique"}
ERRORS = {1: "erreur inconnue", 2: "fichier introuvable ou illisible", 3: "fichier PDF endommagé ou format inconnu",
          4: "mot de passe requis ou incorrect", 5: "chiffrement non pris en charge", 6: "page introuvable"}
K = 16                                   # précision des conversions (1/16 de point)

# Modificateurs (FWL_EVENTFLAG_*) et touches (FWL_VKEY_* = codes virtuels Windows)
SHIFT, CTRL, ALT, META = 1, 2, 4, 8
VK = {"back": 0x08, "tab": 0x09, "return": 0x0D, "shift": 0x10, "control": 0x11, "menu": 0x12, "escape": 0x1B,
      "space": 0x20, "prior": 0x21, "next": 0x22, "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26,
      "right": 0x27, "down": 0x28, "insert": 0x2D, "delete": 0x2E}

_LIBRARY: dict = {}


class EngineError(Exception):
    pass


class PasswordError(EngineError):
    """Mot de passe requis (ou faux)."""


def init_library():
    """Charge et initialise PDFium (une fois, sur le fil du moteur)."""
    if "c" in _LIBRARY:
        return _LIBRARY["c"]
    c = native.load()
    cfg = c.FPDF_LIBRARY_CONFIG(version=2, m_pUserFontPaths=None, m_pIsolate=None, m_v8EmbedderSlot=0)
    t0 = time.perf_counter()
    c.FPDF_InitLibraryWithConfig(ctypes.byref(cfg))
    _LIBRARY["c"] = c
    _LIBRARY["init_ms"] = (time.perf_counter() - t0) * 1000
    return c


def fold(text: str, match_case: bool = False, ignore_accents: bool = False) -> str:
    """Repliement caractère par caractère, MÊME LONGUEUR (indices de PDFium gardés) : minuscules, accents retirés."""
    import unicodedata
    out = []
    for ch in text:
        if not match_case:
            low = ch.lower()
            ch = low if len(low) == 1 else ch
        if ignore_accents:
            base = unicodedata.normalize("NFD", ch)[0]
            ch = base if base else ch
        out.append(ch)
    return "".join(out)


def _addr(handle) -> int | None:
    return ctypes.cast(handle, ctypes.c_void_p).value if handle else None


def _wide_buf(text: str):
    raw = text.encode("utf-16-le") + b"\0\0"
    return (ctypes.c_ushort * (len(raw) // 2)).from_buffer_copy(raw)


def _read_wide(fn, *args) -> str:
    """Appelle fn(*args, buf, taille) (taille en octets, UTF-16LE terminé par 0) deux fois : taille puis texte."""
    n = fn(*args, None, 0)
    if not n or n <= 2:
        return ""
    buf = (ctypes.c_ushort * (n // 2 + 1))()
    fn(*args, buf, n)
    return bytes(buf)[: n - 2].decode("utf-16-le", "replace")


def _read_bytes(fn, *args) -> bytes:
    n = fn(*args, None, 0)
    if not n:
        return b""
    buf = ctypes.create_string_buffer(n)
    fn(*args, buf, n)
    return buf.raw[:n].rstrip(b"\0")


class Document:
    """Un PDF ouvert dans PDFium. `engine` fournit add_timer / kill_timer (minuteries des formulaires)."""

    def __init__(self, engine, data: bytes, path=None, password: str | None = None, *, javascript: bool = True,
                 xfa: bool = True, language: str = "FRA", highlight=(0xFFE4DD, 100)):
        self.c = c = init_library()
        self.engine = engine
        self.path = str(path) if path else None
        self.data = bytes(data)                   # gardé : PDFium lit dedans tant que le document est ouvert
        self._data_ptr = ctypes.c_char_p(self.data)
        self.language = language
        self.events: list = []
        self.blocked: list = []
        self.listener = None                      # f(events) : posé par l'interface (appelé sur le fil du moteur)
        self.asker = None                         # f(kind, title, message, extra) -> réponse (alertes des scripts)
        self.current_page = 0
        self.modified = False                     # valeurs de formulaire changées (FFI_OnChange)
        self.revision = 0                         # +1 à chaque changement de contenu (caches de l'interface)
        self.closed = False
        self._pages: dict[int, object] = {}
        self._page_index: dict[int, int] = {}
        self._page_rect: dict[int, tuple] = {}
        self._text: dict[int, object] = {}
        self._sizes: list | None = None
        self._stale_pages = False
        self._raw_invalid: list = []
        self._caret = None
        self._original_packets = None
        self._lru: list[int] = []
        pw = password.encode("utf-8") if password else None
        t0 = time.perf_counter()
        handle = c.FPDF_LoadMemDocument64(ctypes.cast(self._data_ptr, ctypes.c_void_p), len(self.data), pw)
        if not handle:
            err = c.FPDF_GetLastError()
            if err == 4:
                raise PasswordError(ERRORS[4])
            raise EngineError(ERRORS.get(err, "erreur %d" % err))
        self.handle = handle
        self.form_type = int(c.FPDF_GetFormType(handle))
        self.host = formfill.FormHost(c, self, engine, javascript=javascript, xfa=xfa)
        self.form = c.FPDFDOC_InitFormFillEnvironment(handle, ctypes.byref(self.host.info))
        self.xfa_loaded = False
        self.xfa_ms = 0.0
        if self.is_xfa and xfa and native.info().get("xfa"):
            t1 = time.perf_counter()
            self.xfa_loaded = bool(c.FPDF_LoadXFA(handle))
            self.xfa_ms = (time.perf_counter() - t1) * 1000
        if self.form:
            c.FPDF_SetFormFieldHighlightColor(self.form, 0, highlight[0])
            c.FPDF_SetFormFieldHighlightAlpha(self.form, highlight[1])
            c.FORM_DoDocumentJSAction(self.form)
            c.FORM_DoDocumentOpenAction(self.form)
        if self.xfa_loaded:
            self._settle_xfa()
        self.open_ms = (time.perf_counter() - t0) * 1000

    # -- propriétés --

    @property
    def is_xfa(self) -> bool:
        return self.form_type in (2, 3)

    @property
    def form_kind(self) -> str:
        return FORM_TYPES.get(self.form_type, "aucun")

    def page_count(self) -> int:
        return int(self.c.FPDF_GetPageCount(self.handle))

    def page_sizes(self) -> list[tuple[float, float]]:
        """[(largeur, hauteur)] en points, rotation /Rotate comprise (gardé jusqu'au prochain changement)."""
        if self._sizes is None:
            c = self.c
            size = c.FS_SIZEF()
            out = []
            for i in range(self.page_count()):
                if c.FPDF_GetPageSizeByIndexF(self.handle, i, ctypes.byref(size)):
                    out.append((float(size.width), float(size.height)))
                else:
                    out.append((612.0, 792.0))
            self._sizes = out
        return self._sizes

    def page_size(self, i: int, rotate: int = 0) -> tuple[float, float]:
        w, h = self.page_sizes()[i]
        return (h, w) if rotate % 2 else (w, h)

    # -- pages --

    def page(self, i: int):
        h = self._pages.get(i)
        if h is None:
            c = self.c
            h = c.FPDF_LoadPage(self.handle, i)
            if not h:
                raise EngineError("page %d introuvable" % (i + 1))
            if self.form:
                c.FORM_OnAfterLoadPage(h, self.form)
                c.FORM_DoPageAAction(h, self.form, c.FPDFPAGE_AACTION_OPEN)
            self._pages[i] = h
            self._page_index[_addr(h)] = i
            w, hh = self.page_size(i)
            self._page_rect[i] = self._rect_to_page(h, i, 0, 0, w, hh, 0)
            self._evict()
        if i in self._lru:
            self._lru.remove(i)
        self._lru.append(i)
        return h

    def _evict(self, keep: int = 48):
        """Au-delà de `keep` pages chargées, ferme les plus anciennes (jamais en XFA : sa mise en page les garde)."""
        if self.is_xfa:
            return
        while len(self._pages) > keep and self._lru:
            old = self._lru.pop(0)
            if old != self.current_page and old in self._pages:
                self._close_page(old)

    def _close_page(self, i: int):
        c = self.c
        tp = self._text.pop(i, None)
        if tp:
            c.FPDFText_ClosePage(tp)
        h = self._pages.pop(i, None)
        if h:
            self._page_index.pop(_addr(h), None)
            if self.form:
                c.FORM_DoPageAAction(h, self.form, c.FPDFPAGE_AACTION_CLOSE)
                c.FORM_OnBeforeClosePage(h, self.form)
            c.FPDF_ClosePage(h)
        self._page_rect.pop(i, None)

    def reload_pages(self):
        for i in list(self._pages):
            self._close_page(i)
        self._lru.clear()
        self._sizes = None
        self.revision += 1

    def page_address(self, i: int):
        """FFI_GetPage : adresse de la page `i` (chargée si besoin, comme pdfium_test)."""
        if i < 0 or i >= self.page_count():
            return None
        try:
            return _addr(self.page(i))
        except EngineError:
            return None

    def view_rect_for(self, page_handle):
        i = self._page_index.get(_addr(page_handle), 0)
        r = self._page_rect.get(i, (0.0, 0.0, 612.0, 792.0))
        return r[0], r[1], r[2], r[3]

    def _settle_xfa(self):
        """Provoque la remise en page XFA (premier événement) puis recharge les pages (voir l'en-tête)."""
        if self.page_count() <= 0:
            return
        self.c.FORM_OnMouseMove(self.form, self.page(0), 0, 5.0, 5.0)
        self.reload_pages()
        self._stale_pages = False

    # -- repères --

    def _rect_to_page(self, page, i, x0, y0, x1, y1, rotate):
        a = self._to_page(page, i, x0, y0, rotate)
        b = self._to_page(page, i, x1, y1, rotate)
        return a[0], a[1], b[0], b[1]

    def _to_page(self, page, i, dx, dy, rotate=0):
        w, h = self.page_size(i, rotate)
        px, py = ctypes.c_double(), ctypes.c_double()
        self.c.FPDF_DeviceToPage(page, 0, 0, int(round(w * K)), int(round(h * K)), rotate, int(round(dx * K)),
                                 int(round(dy * K)), ctypes.byref(px), ctypes.byref(py))
        return px.value, py.value

    def to_page(self, i, dx, dy, rotate=0):
        return self._to_page(self.page(i), i, dx, dy, rotate)

    def to_device(self, i, px, py, rotate=0):
        w, h = self.page_size(i, rotate)
        dx, dy = ctypes.c_int(), ctypes.c_int()
        self.c.FPDF_PageToDevice(self.page(i), 0, 0, int(round(w * K)), int(round(h * K)), rotate, px, py,
                                 ctypes.byref(dx), ctypes.byref(dy))
        return dx.value / K, dy.value / K

    def rect_to_device(self, i, l, t, r, b, rotate=0):
        x0, y0 = self.to_device(i, l, t, rotate)
        x1, y1 = self.to_device(i, r, b, rotate)
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)

    # -- rendu --

    def render(self, i: int, scale: float, tile=None, *, rotate: int = 0, forms: bool = True, flags: int | None = None,
               background: int = 0xFFFFFFFF, into=None):
        """Rend la page (ou la tuile `tile` = (x, y, l, h) en pixels de la page à cette échelle). Renvoie
        (octets BGRx, largeur, hauteur, pas). Taille de la page entière : page_size * scale (arrondi).
        `into` = (adresse, pas) : PDFium dessine DIRECTEMENT dans cette mémoire (QImage RGB32 de l'interface :
        aucune copie) ; les octets renvoyés valent alors None."""
        c = self.c
        page = self.page(i)
        w, h = self.page_size(i, rotate)
        full_w, full_h = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        tx, ty, tw, th = tile if tile else (0, 0, full_w, full_h)
        tw, th = max(1, int(tw)), max(1, int(th))
        if flags is None:
            flags = c.FPDF_ANNOT
        if into is not None:
            if int(into[1]) < tw * 4:
                raise EngineError("mémoire d'accueil trop étroite (%d octets par ligne pour %d pixels)" % (into[1], tw))
            bmp = c.FPDFBitmap_CreateEx(tw, th, c.FPDFBitmap_BGRx, ctypes.c_void_p(into[0]), int(into[1]))
        else:
            bmp = c.FPDFBitmap_CreateEx(tw, th, c.FPDFBitmap_BGRx, None, 0)
        if not bmp:
            raise EngineError("mémoire insuffisante pour une image de %d x %d" % (tw, th))
        try:
            c.FPDFBitmap_FillRect(bmp, 0, 0, tw, th, background)
            c.FPDF_RenderPageBitmap(bmp, page, -int(tx), -int(ty), full_w, full_h, rotate, flags)
            if forms and self.form:
                c.FPDF_FFLDraw(self.form, bmp, page, -int(tx), -int(ty), full_w, full_h, rotate, flags)
            stride = c.FPDFBitmap_GetStride(bmp)
            data = None if into is not None else ctypes.string_at(c.FPDFBitmap_GetBuffer(bmp), stride * th)
        finally:
            c.FPDFBitmap_Destroy(bmp)
        return data, tw, th, stride

    # -- texte --

    def text_page(self, i: int):
        tp = self._text.get(i)
        if tp is None:
            tp = self.c.FPDFText_LoadPage(self.page(i))
            self._text[i] = tp
        return tp

    def char_count(self, i: int) -> int:
        tp = self.text_page(i)
        return int(self.c.FPDFText_CountChars(tp)) if tp else 0

    def text(self, i: int, start: int = 0, count: int = -1) -> str:
        tp = self.text_page(i)
        if not tp:
            return ""
        n = self.char_count(i)
        if count < 0 or start + count > n:
            count = max(0, n - start)
        if count <= 0:
            return ""
        buf = (ctypes.c_ushort * (count + 1))()
        got = self.c.FPDFText_GetText(tp, start, count, buf)
        return bytes(buf)[: max(0, got - 1) * 2].decode("utf-16-le", "replace")

    def char_at(self, i: int, dx: float, dy: float, tolerance: float = 4.0) -> int:
        tp = self.text_page(i)
        if not tp:
            return -1
        px, py = self.to_page(i, dx, dy)
        return int(self.c.FPDFText_GetCharIndexAtPos(tp, px, py, tolerance, tolerance))

    def range_rects(self, i: int, start: int, count: int, rotate: int = 0) -> list[tuple]:
        """Rectangles (points écran) d'une plage de caractères : surlignage de sélection et de recherche."""
        tp = self.text_page(i)
        if not tp or count <= 0:
            return []
        c = self.c
        n = c.FPDFText_CountRects(tp, start, count)
        out = []
        l, t, r, b = ctypes.c_double(), ctypes.c_double(), ctypes.c_double(), ctypes.c_double()
        for k in range(n):
            if c.FPDFText_GetRect(tp, k, ctypes.byref(l), ctypes.byref(t), ctypes.byref(r), ctypes.byref(b)):
                out.append(self.rect_to_device(i, l.value, t.value, r.value, b.value, rotate))
        return out

    def search(self, i: int, query: str, match_case: bool = False, whole_word: bool = False,
               ignore_accents: bool = False, rotate: int = 0) -> list[tuple[int, int, list]]:
        """Occurrences de `query` sur la page : [(début, longueur, rectangles)].

        Faite en Python sur le texte de PDFium (un caractère = un indice, repliement qui garde les longueurs) : la
        recherche de PDFium ne replie pas la casse des lettres accentuées (« ÉLÉPHANT » ne trouvait pas
        « éléphant », mesuré)."""
        if not query:
            return []
        text = self.text(i)
        if not text:
            return []
        hay, needle = fold(text, match_case, ignore_accents), fold(query, match_case, ignore_accents)
        out = []
        pos = hay.find(needle)
        while pos >= 0 and len(out) < 5000:
            end = pos + len(needle)
            if not whole_word or ((pos == 0 or not hay[pos - 1].isalnum()) and (end >= len(hay) or not hay[end].isalnum())):
                out.append((pos, len(needle), self.range_rects(i, pos, len(needle), rotate)))
            pos = hay.find(needle, pos + 1)
        return out

    def has_text_layer(self, i: int) -> bool:
        return self.char_count(i) > 0

    def image_count(self, i: int) -> int:
        """Objets image de la page (détection des pages numérisées)."""
        c = self.c
        page = self.page(i)
        n = c.FPDFPage_CountObjects(page)
        return sum(1 for k in range(n) if c.FPDFPageObj_GetType(c.FPDFPage_GetObject(page, k)) == c.FPDF_PAGEOBJ_IMAGE)

    # -- liens, signets, métadonnées --

    def links(self, i: int, rotate: int = 0) -> list[dict]:
        c = self.c
        page = self.page(i)
        pos = ctypes.c_int(0)
        link = c.FPDF_LINK()
        rect = c.FS_RECTF()
        out = []
        while c.FPDFLink_Enumerate(page, ctypes.byref(pos), ctypes.byref(link)):
            if not c.FPDFLink_GetAnnotRect(link, ctypes.byref(rect)):
                continue
            item = {"rect": self.rect_to_device(i, rect.left, rect.top, rect.right, rect.bottom, rotate)}
            dest = c.FPDFLink_GetDest(self.handle, link)
            action = c.FPDFLink_GetAction(link) if not dest else None
            if action:
                kind = c.FPDFAction_GetType(action)
                if kind == c.PDFACTION_URI:
                    item["uri"] = _read_bytes(c.FPDFAction_GetURIPath, self.handle, action).decode("latin-1", "replace")
                elif kind == c.PDFACTION_GOTO:
                    dest = c.FPDFAction_GetDest(self.handle, action)
                elif kind in (c.PDFACTION_LAUNCH, c.PDFACTION_REMOTEGOTO):
                    item["external"] = _read_bytes(c.FPDFAction_GetFilePath, action).decode("utf-8", "replace")
            if dest:
                item["page"] = int(c.FPDFDest_GetDestPageIndex(self.handle, dest))
            out.append(item)
        return out

    def outline(self, limit: int = 20000) -> list[dict]:
        """Signets : [{'title', 'page', 'children'}] (cycles et arbres géants bornés)."""
        c = self.c
        seen = set()

        def walk(parent, depth):
            out = []
            bm = c.FPDFBookmark_GetFirstChild(self.handle, parent)
            while bm and len(seen) < limit and depth < 64:
                a = _addr(bm)
                if a in seen:
                    break
                seen.add(a)
                title = _read_wide(c.FPDFBookmark_GetTitle, bm)
                dest = c.FPDFBookmark_GetDest(self.handle, bm)
                if not dest:
                    action = c.FPDFBookmark_GetAction(bm)
                    if action and c.FPDFAction_GetType(action) == c.PDFACTION_GOTO:
                        dest = c.FPDFAction_GetDest(self.handle, action)
                page = int(c.FPDFDest_GetDestPageIndex(self.handle, dest)) if dest else -1
                out.append({"title": title, "page": page, "children": walk(bm, depth + 1)})
                bm = c.FPDFBookmark_GetNextSibling(self.handle, bm)
            return out
        return walk(None, 0)

    def metadata(self) -> dict:
        c = self.c
        out = {}
        for tag in ("Title", "Author", "Subject", "Keywords", "Creator", "Producer", "CreationDate", "ModDate"):
            out[tag] = _read_wide(c.FPDF_GetMetaText, self.handle, tag.encode())
        version = ctypes.c_int()
        out["version"] = "%.1f" % (version.value / 10) if c.FPDF_GetFileVersion(self.handle, ctypes.byref(version)) else ""
        return out

    def page_label(self, i: int) -> str:
        return _read_wide(self.c.FPDF_GetPageLabel, self.handle, i)

    def security(self) -> dict:
        c = self.c
        rev = int(c.FPDF_GetSecurityHandlerRevision(self.handle))
        perms = int(c.FPDF_GetDocPermissions(self.handle)) & 0xFFFFFFFF
        return {"encrypted": rev != -1, "revision": rev, "permissions": perms,
                "can_print": bool(perms & 4), "can_modify": bool(perms & 8), "can_copy": bool(perms & 16),
                "can_annotate": bool(perms & 32), "can_fill": bool(perms & 256) or bool(perms & 32)}

    def active_content(self) -> dict:
        """Contenu actif : scripts du document, pièces jointes, signatures."""
        c = self.c
        return {"javascript": int(c.FPDFDoc_GetJavaScriptActionCount(self.handle)),
                "attachments": int(c.FPDFDoc_GetAttachmentCount(self.handle)),
                "signatures": int(c.FPDF_GetSignatureCount(self.handle)), "xfa": self.is_xfa,
                "xfa_loaded": self.xfa_loaded}

    def attachments(self) -> list[str]:
        c = self.c
        return [_read_wide(c.FPDFAttachment_GetName, c.FPDFDoc_GetAttachment(self.handle, k))
                for k in range(c.FPDFDoc_GetAttachmentCount(self.handle))]

    # -- formulaires --

    def field_at(self, i: int, dx: float, dy: float) -> int:
        """Type du champ sous le point (formfill.FIELD_TYPES), -1 sinon."""
        if not self.form:
            return -1
        px, py = self.to_page(i, dx, dy)
        return int(self.c.FPDFPage_HasFormFieldAtPoint(self.form, self.page(i), px, py))

    def mouse(self, i: int, kind: str, dx: float, dy: float, mods: int = 0, delta=(0, 0)) -> bool:
        """Évènement souris transmis au formulaire ; vrai si un champ l'a pris."""
        if not self.form:
            return False
        c = self.c
        page = self.page(i)
        self.current_page = i
        px, py = self.to_page(i, dx, dy)
        if kind == "move":
            ok = c.FORM_OnMouseMove(self.form, page, mods, px, py)
        elif kind == "down":
            ok = c.FORM_OnLButtonDown(self.form, page, mods, px, py)
        elif kind == "up":
            ok = c.FORM_OnLButtonUp(self.form, page, mods, px, py)
        elif kind == "double":
            ok = c.FORM_OnLButtonDoubleClick(self.form, page, mods, px, py)
        elif kind == "rdown":
            ok = c.FORM_OnRButtonDown(self.form, page, mods, px, py)
        elif kind == "rup":
            ok = c.FORM_OnRButtonUp(self.form, page, mods, px, py)
        elif kind == "focus":
            ok = c.FORM_OnFocus(self.form, page, mods, px, py)
        else:
            raise ValueError(kind)
        return bool(ok)

    def key(self, i: int, kind: str, code: int, mods: int = 0) -> bool:
        if not self.form:
            return False
        c = self.c
        page = self.page(i)
        if kind == "down":
            return bool(c.FORM_OnKeyDown(self.form, page, code, mods))
        if kind == "up":
            return bool(c.FORM_OnKeyUp(self.form, page, code, mods))
        if kind == "char":
            return bool(c.FORM_OnChar(self.form, page, code, mods))
        raise ValueError(kind)

    def type_text(self, i: int, text: str) -> None:
        """Frappe de `text` (unités UTF-16 une par une, comme Chrome : les caractères hors BMP passent en paire).
        XFA : une frappe ne REMPLACE pas la sélection (elle s'ajoute, mesuré sur deux formulaires réels) ; avec une
        sélection, le texte passe donc par FORM_ReplaceSelection, qui la remplace."""
        if self.is_xfa and text and self.selected_text(i):
            self.replace_selection(i, text)
            return
        raw = text.encode("utf-16-le")
        for k in range(0, len(raw), 2):
            self.key(i, "char", raw[k] | (raw[k + 1] << 8))

    def kill_focus(self) -> bool:
        return bool(self.form and self.c.FORM_ForceToKillFocus(self.form))

    def focused_text(self, i: int) -> str:
        if not self.form:
            return ""
        return _read_wide(self.c.FORM_GetFocusedText, self.form, self.page(i))

    def selected_text(self, i: int) -> str:
        if not self.form:
            return ""
        return _read_wide(self.c.FORM_GetSelectedText, self.form, self.page(i))

    def replace_selection(self, i: int, text: str) -> None:
        if self.form:
            self.c.FORM_ReplaceSelection(self.form, self.page(i), _wide_buf(text))

    def select_all(self, i: int) -> bool:
        return bool(self.form and self.c.FORM_SelectAllText(self.form, self.page(i)))

    def form_undo(self, i: int, redo: bool = False) -> bool:
        if not self.form:
            return False
        c = self.c
        page = self.page(i)
        if redo:
            return bool(c.FORM_CanRedo(self.form, page) and c.FORM_Redo(self.form, page))
        return bool(c.FORM_CanUndo(self.form, page) and c.FORM_Undo(self.form, page))

    def focused_field(self) -> tuple[int, str] | None:
        """(page, nom) du champ AcroForm qui a le focus, sinon None (XFA : pas d'annotation PDF)."""
        if not self.form:
            return None
        c = self.c
        index = ctypes.c_int(-1)
        annot = c.FPDF_ANNOTATION()
        if not c.FORM_GetFocusedAnnot(self.form, ctypes.byref(index), ctypes.byref(annot)) or not annot:
            return None
        try:
            return index.value, _read_wide(c.FPDFAnnot_GetFormFieldName, self.form, annot)
        finally:
            c.FPDFPage_CloseAnnot(annot)

    def fields(self, rotate: int = 0) -> list[dict]:
        """Champs AcroForm (widgets) de tout le document : nom, type, valeur, drapeaux, rectangle, page."""
        if not self.form:
            return []
        c = self.c
        out = []
        rect = c.FS_RECTF()
        for i in range(self.page_count()):
            page = self.page(i)
            for k in range(c.FPDFPage_GetAnnotCount(page)):
                annot = c.FPDFPage_GetAnnot(page, k)
                if not annot:
                    continue
                try:
                    if c.FPDFAnnot_GetSubtype(annot) != c.FPDF_ANNOT_WIDGET:
                        continue
                    kind = int(c.FPDFAnnot_GetFormFieldType(self.form, annot))
                    item = {"page": i, "name": _read_wide(c.FPDFAnnot_GetFormFieldName, self.form, annot),
                            "type": kind, "type_name": formfill.FIELD_TYPES.get(kind, "?"),
                            "value": _read_wide(c.FPDFAnnot_GetFormFieldValue, self.form, annot),
                            "flags": int(c.FPDFAnnot_GetFormFieldFlags(self.form, annot)),
                            "tooltip": _read_wide(c.FPDFAnnot_GetFormFieldAlternateName, self.form, annot)}
                    if kind in (2, 3):
                        item["checked"] = bool(c.FPDFAnnot_IsChecked(self.form, annot))
                    if kind in (4, 5):
                        item["options"] = [_read_wide(c.FPDFAnnot_GetOptionLabel, self.form, annot, o)
                                           for o in range(max(0, c.FPDFAnnot_GetOptionCount(self.form, annot)))]
                    if c.FPDFAnnot_GetRect(annot, ctypes.byref(rect)):
                        item["rect"] = self.rect_to_device(i, rect.left, rect.top, rect.right, rect.bottom, rotate)
                    out.append(item)
                finally:
                    c.FPDFPage_CloseAnnot(annot)
        return out

    def xfa_packets(self) -> dict[str, bytes]:
        """{nom: contenu} des paquets XFA (état EN MÉMOIRE du fichier, pas du formulaire tant qu'il n'est pas
        enregistré)."""
        c = self.c
        out = {}
        for k in range(max(0, c.FPDF_GetXFAPacketCount(self.handle))):
            name = _read_bytes(c.FPDF_GetXFAPacketName, self.handle, k).decode("utf-8", "replace")
            size = ctypes.c_ulong()
            c.FPDF_GetXFAPacketContent(self.handle, k, None, 0, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            c.FPDF_GetXFAPacketContent(self.handle, k, buf, size.value, ctypes.byref(size))
            out[name] = buf.raw[: size.value]
        return out

    # -- évènements (rappels de formfill) --

    def post(self, event) -> None:
        self.events.append(event)

    def on_form_change(self):
        self.modified = True
        self.post(("changed",))

    def on_invalidate(self, page, l, t, r, b):
        i = self._page_index.get(_addr(page))
        if i is not None:
            self._raw_invalid.append((i, l, t, r, b))

    def on_selected_rect(self, page, l, t, r, b):
        pass

    def on_caret(self, page, visible, l, t, r, b):
        i = self._page_index.get(_addr(page))
        self._caret = (i, bool(visible), l, t, r, b) if i is not None else None

    def on_page_event(self, count, event):
        self._stale_pages = True
        self.post(("pages_changed", count, event))

    def ask(self, kind, title, message, extra):
        if self.asker is None:
            return 1 if kind == "alert" else None
        return self.asker(kind, title, message, extra)

    def take_events(self) -> list:
        """Après chaque tâche (fil du moteur) : convertit les zones en points écran, recharge les pages périmées,
        renvoie la liste des évènements à remettre à l'interface."""
        if self._stale_pages:
            self._stale_pages = False
            self.reload_pages()
        events, self.events = self.events, []
        if self._raw_invalid:
            raw, self._raw_invalid = self._raw_invalid, []
            for i, l, t, r, b in raw:
                if i < self.page_count():
                    try:
                        events.append(("invalidate", i, self.rect_to_device(i, l, t, r, b)))
                    except EngineError:
                        pass
        if self._caret is not None:
            i, visible, l, t, r, b = self._caret
            self._caret = None
            if i < self.page_count():
                events.append(("caret", i, visible, self.rect_to_device(i, l, t, r, b)))
        return events

    # -- enregistrement --

    def original_packets(self) -> dict[str, bytes]:
        if self._original_packets is None:
            try:
                self._original_packets = {k: v[1] for k, v in xfa_save.packet_streams(self.data).items()}
            except Exception:                                # noqa: BLE001 - structure illisible : rien à comparer
                self._original_packets = {}
        return self._original_packets

    def save_bytes(self, incremental: bool = False, kill_focus: bool = True) -> tuple[bytes, list[str]]:
        """Octets du document tel qu'il est (formulaire compris). XFA : paquets réparés (voir xfa_save) ;
        renvoie aussi la liste des paquets réparés."""
        c = self.c
        if kill_focus:
            self.kill_focus()
        chunks: list[bytes] = []
        writer = c.FPDF_FILEWRITE()
        writer.version = 1
        ftype = dict(c.FPDF_FILEWRITE._fields_)["WriteBlock"]

        def write(_self, data, size):
            chunks.append(ctypes.string_at(data, size))
            return 1
        cb = ftype(write)
        writer.WriteBlock = cb
        flags = c.FPDF_INCREMENTAL if incremental else c.FPDF_NO_INCREMENTAL
        if not c.FPDF_SaveAsCopy(self.handle, ctypes.byref(writer), flags):
            raise EngineError("PDFium n'a pas pu enregistrer le document")
        data = b"".join(chunks)
        repaired: list[str] = []
        if incremental:
            from . import incremental as inc
            data, fixed = inc.repair_xref_stream_type(data)
            if fixed:
                repaired.append("xref")
        if self.xfa_loaded:
            data, names = xfa_save.repair(data, self.original_packets())
            repaired += names
        return data, repaired

    # -- fin --

    def close(self):
        if self.closed:
            return
        self.closed = True
        c = self.c
        for i in list(self._pages):
            self._close_page(i)
        if self.form:
            c.FORM_DoDocumentAAction(self.form, c.FPDFDOC_AACTION_WC)
            c.FPDFDOC_ExitFormFillEnvironment(self.form)
            self.form = None
        c.FPDF_CloseDocument(self.handle)
        self.handle = None
        try:
            self.engine.kill_timers_of(self)
        except AttributeError:
            pass
