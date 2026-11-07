"""Élément « pdf_doc » du Board (Qt) : un PDF LIÉ (jamais copié dans le board).

Demande de l'utilisateur (2026-11-06) : « je veux que le document apparaisse et qu'il soit modifiable quand le module
est actif, avec toutes ses pages et avec sa barre des outils » (le Board montrait la page de repli « Please wait… »
d'un XFA de l'IRCC, une seule page).

- Document : celui de l'élément (`board_docs.DocEntry` : session ouverte UNE fois, JavaScript et XFA compris).
- APERÇU (module inactif, ou élément pas en cours d'édition) : TOUTES les pages en défilement continu, avec
  l'ajustement (pleine largeur / pleine page / zoom), la page et le défilement retenus dans l'élément (ceux de la
  dernière édition), peintes depuis des images de pages rendues dans le fil du moteur (jamais pendant la peinture :
  en attendant, la page blanche). Même mise en page que la vue (`layout_pages` = `PdfView.relayout`) : passer de
  l'aperçu à l'édition ne fait rien bouger.
- Module PDF actif : un clic dans le document l'ÉDITE SUR PLACE (`board_live.LiveDoc` dans l'élément : remplir les
  formulaires AcroForm et XFA, sélectionner, copier, liens) ; double-clic (module inactif) : active le module et
  l'édite. Un seul document édité à la fois (`PdfBoardController.make_live`).
- SEULEMENT LES PAGES (demande de l'utilisateur, 2026-11-06, capture annotée : « pas d'en-tête », « pas de fond, je
  veux uniquement les pages », « le fond doit être le fond du board ») : ni barre de titre ni fond, autour et entre
  les pages on voit le Board ; aperçu ET édition (vue transparente, `PdfView.set_transparent`). Nom, page et
  « modifié » : infobulle ; page courante et « modifié » aussi dans les barres du module (« n / N », Enregistrer)."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QGraphicsItem

from fm_miro.items import ITEM_CLASSES, BoardItem

from . import board_docs
from . import board_model as bm

TITLE_H = 0.0                              # plus de barre de titre (demande de l'utilisateur) : le document seul
GAP = 12.0                                 # = view.GAP (entre deux pages)
MARGIN, PAD = 0.0, 0                       # Board : pages BORD À BORD avec le cadre (demande de l'utilisateur :
                                           # « pas d'écart entre le bord de la page et le cadre ») ; la vue reçoit
                                           # les mêmes (`PdfView.margin`, `fit_pad`)


def layout_pages(sizes, fit: str, zoom: float, body_w: float, body_h: float, page: int = 0):
    """Mise en page de la vue en défilement continu : (zoom, [(x, y, l, h) en points], largeur, hauteur du contenu
    en points). `fit` : « width », « page », « » (zoom fixe)."""
    inner = max((w for w, _h in sizes), default=0.0)
    rects, y = [], MARGIN
    for w, h in sizes:
        rects.append((MARGIN + (inner - w) / 2, y, w, h))
        y += h + GAP
    content_w, content_h = inner + MARGIN * 2, (y - GAP + MARGIN) if sizes else 0.0
    vw, vh = body_w - PAD, body_h - PAD
    if fit == "width" and content_w > 0:
        zoom = vw / max(1.0, content_w)
    elif fit == "page" and rects:
        r = rects[min(max(0, page), len(rects) - 1)]
        zoom = min(vw / (r[2] + MARGIN * 2), vh / (r[3] + MARGIN * 2))
    return max(0.05, min(64.0, zoom)), rects, content_w, content_h


_SETTINGS = [None, None]                   # (réglages du Board, réglages « pdf_ » qui en sont tirés)


def _settings(item) -> dict:
    """Réglages du module (défauts + ceux du Board), refaits seulement quand le Board change de réglages (la
    peinture en a besoin : ne pas parcourir les réglages de l'appli à chaque image)."""
    board = item.board_pane()
    src = getattr(board, "_settings", None) or {}
    if _SETTINGS[0] is not src:
        from .settings_defaults import PDF_DEFAULTS
        s = dict(PDF_DEFAULTS)
        s.update({k: v for k, v in src.items() if k.startswith("pdf_")})
        _SETTINGS[:] = [src, s]
    return _SETTINGS[1]


class PdfItem(BoardItem):
    MODULE = "pdf"
    CONNECTABLE = True
    RESIZABLE = True
    KEEP_RATIO = False                      # toutes les pages défilent : un élément haut en montre plusieurs

    def __init__(self, data: dict):
        self._live = None
        self._proxy = None
        self._scale_queued = False
        self._path_cache = None
        self._tip = None
        super().__init__(data)

    # -- liens --

    def board_path(self):
        pane = self.board_pane()
        return getattr(pane, "path", None) if pane is not None else None

    def board_pane(self):
        scene = self.scene()
        parent = scene.parent() if scene is not None else None
        return parent if hasattr(parent, "save") else None

    def pdf_path(self):
        """Fichier lié (relatif au board d'abord) ; gardé 2 s (la peinture le demande à chaque image)."""
        now = time.monotonic()
        key = (self.data.get("path"), self.data.get("rel"), self.board_path())
        cached = self._path_cache
        if cached is not None and cached[0] == key and now - cached[2] < 2.0:
            return cached[1]
        path = bm.resolve(self.data, key[2])
        self._path_cache = (key, path, now)
        return path

    def entry(self):
        """Le document de l'élément (ouvert au premier appel : aperçu et édition)."""
        if self.scene() is None:
            return None
        path = self.pdf_path()
        if path is None:
            return board_docs.existing_entry(self)
        return board_docs.entry_for(self, path, _settings(self))

    @property
    def session(self):
        entry = self.entry()
        return entry.session if entry is not None else None

    # -- état --

    def to_dict(self) -> dict:
        if self._live is not None:
            self.data.update(self._live.view_state())         # l'endroit où l'on travaille est retenu
        return super().to_dict()

    def apply(self, data: dict):
        if self._live is not None:                            # annuler un déplacement : la vue garde son état
            data = dict(data)
            data.update(self._live.view_state())
        super().apply(data)

    def sync(self):
        super().sync()
        live = self._live
        if self._proxy is not None and live is not None and not live.fullscreen:
            w, h = self.size()
            self._proxy.setPos(0, 0)
            live.resize(max(40, int(round(w))), max(40, int(round(h))))

    def removing_from_scene(self, scene):
        self.stop_live()

    def fit_frame_once(self) -> None:
        """Élément posé AVANT les pages bord à bord (marges, ancienne barre de titre : un écart restait sous la
        page) : son cadre est recalé UNE fois sur la première page en pleine largeur (largeur et coin haut gauche
        gardés) ; ensuite, sa taille est celle que l'utilisateur lui donne."""
        scene = self.scene()
        if self.data.get("framed") or self.locked() or scene is None:
            return
        entry = board_docs.existing_entry(self)
        if entry is None or not entry.ready():
            return
        self.data["framed"] = True
        sizes = entry.info.get("sizes") or []
        if sizes and self.data.get("fit", "width") == "width":
            pw, ph = sizes[0]
            w = float(self.data.get("w") or bm.MIN_W)
            h = max(bm.MIN_H, round(w * ph / max(1.0, pw), 1))
            if abs(h - float(self.data.get("h") or 0.0)) > 0.5:
                self.prepareGeometryChange()               # index de la scène prévenu AVANT (piège du Board)
                self.data["h"] = h
                self.sync()
                self.update()
        if hasattr(scene, "contentChanged"):
            scene.contentChanged.emit()                     # retenu par l'enregistrement automatique

    def snap_document_sizes(self, w: float, h: float):
        """Magnétisme du CADRE sur son document (demande de l'utilisateur 2026-11-06 : « le cadre bleu doit se
        snapper au document » ; `BoardScene.snap_resize`, guide « Cadre sur son document ») : pour un cadre de
        w × h, les (largeurs, hauteurs) de cadre où un bord du document tombe sur le bord du cadre — bas de chaque
        page (défilement compris), largeur du contenu. Seulement celles qui ne suivent pas déjà le cadre (pleine
        largeur : pas de largeur ; pleine page limitée par la hauteur : pas de hauteur). Vide tant que le document
        n'est pas prêt."""
        entry = board_docs.existing_entry(self)
        sizes = entry.info.get("sizes") if entry is not None and entry.ready() else None
        if not sizes or w < 1 or h < 1:
            return (), ()
        fit = self.data.get("fit", "width")
        page = int(self.data.get("page", 0))
        zoom, rects, content_w, content_h = layout_pages(sizes, fit, float(self.data.get("zoom") or 1.0), w, h, page)
        scroll = max(0.0, min(float(self.data.get("scroll") or 0.0) * zoom, content_h * zoom - h))
        heights = [(y + ph) * zoom - scroll for _x, y, _pw, ph in rects]
        widths = [content_w * zoom]
        if fit == "width":
            widths = []
        elif fit == "page" and rects:
            _x, _y, pw, ph = rects[min(max(0, page), len(rects) - 1)]
            if h / max(1e-9, ph) <= w / max(1e-9, pw):      # limitée par la hauteur : la page suit le cadre
                heights = []
            else:
                widths = []
        return widths, [v for v in heights if v > 1.0]

    # -- peinture --

    def paint(self, painter: QPainter, option, widget=None):
        w, h = self.size()
        body = QRectF(0, 0, w, h)
        entry = self.entry()
        self._sync_tip(entry)
        painter.save()
        if self._live is None:
            self._paint_body(painter, body, entry, widget)
        else:
            self._schedule_scale()                           # les pages : la vue embarquée (transparente)
        painter.restore()
        self.paint_selection(painter)                        # sélection ordinaire du Board (cadre, poignées)

    def _sync_tip(self, entry) -> None:
        """Infobulle (plus de barre de titre) : nom, page / pages, « modifié » ; posée seulement si elle change."""
        path = self.pdf_path()
        title = self.data.get("title") or (path.stem if path else "PDF")
        tip = "PDF : %s — %s" % (title, self._page_text(entry))
        if tip != self._tip:
            self._tip = tip
            self.setToolTip(tip)

    def _page_text(self, entry) -> str:
        if entry is None or not entry.ready():
            return "p. %d" % (int(self.data.get("page", 0)) + 1)
        count = int(entry.info.get("page_count", 0))
        current = self._live.view.current if self._live is not None else int(self.data.get("page", 0))
        text = "p. %d / %d" % (min(count, current + 1), count)
        if entry.session.dirty:
            text += " — modifié"
        return text

    def _paint_message(self, painter, body: QRectF, message: str) -> None:
        """En attendant le document (ou s'il manque) : une page blanche qui le dit (aucun fond autour)."""
        page = body.adjusted(MARGIN * 0.5, MARGIN * 0.5, -MARGIN * 0.5, -MARGIN * 0.5)
        painter.fillRect(page.translated(2, 3), QColor(0, 0, 0, 60))
        painter.fillRect(page, Qt.white)
        font = QFont("Segoe UI")
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QColor("#777777"))
        painter.drawText(page.adjusted(8, 8, -8, -8), Qt.AlignCenter | Qt.TextWordWrap, message)

    def _paint_body(self, painter, body: QRectF, entry, widget) -> None:
        message = None
        if self.pdf_path() is None:
            message = "Fichier introuvable :\n%s" % (self.data.get("rel") or self.data.get("path"))
        elif entry is None:
            message = "…"
        elif entry.error:
            message = ("Document protégé par un mot de passe : activez le module PDF et cliquez ici."
                       if entry.needs_password else "Ouverture impossible :\n%s" % entry.error)
        elif not entry.ready():
            message = "Ouverture…"
        if message is not None:
            self._paint_message(painter, body, message)
            return
        entry.check_file()
        sizes = entry.info.get("sizes", [])
        fit = self.data.get("fit", "width")
        zoom, rects, content_w, content_h = layout_pages(sizes, fit, float(self.data.get("zoom") or 1.0),
                                                         body.width(), body.height(), int(self.data.get("page", 0)))
        scroll = float(self.data.get("scroll") or 0.0) * zoom
        scroll = max(0.0, min(scroll, content_h * zoom - body.height()))
        cx = max(0.0, (body.width() - content_w * zoom) / 2)
        dpr = widget.devicePixelRatioF() if widget is not None else 1.0
        screen = self._zoom() * dpr
        painter.setClipRect(body)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for i, (x, y, pw, ph) in enumerate(rects):
            target = QRectF(body.left() + cx + x * zoom, body.top() + y * zoom - scroll, pw * zoom, ph * zoom)
            if target.bottom() < body.top():
                continue
            if target.top() > body.bottom():
                break
            painter.fillRect(target.translated(2, 3), QColor(0, 0, 0, 60))
            painter.fillRect(target, Qt.white)
            img = entry.page_image(i, board_docs.width_bucket(target.width() * screen))
            if img is not None:
                painter.drawImage(target, img)

    # -- netteté de l'édition sur place --

    def _render_scale(self) -> float:
        live = self._live
        scene = self.scene()
        views = scene.views() if scene is not None else []
        board_dpr = views[0].devicePixelRatioF() if views else 1.0
        s = self._zoom() * board_dpr / max(0.1, live.view.devicePixelRatioF())
        s = 2 ** (round(math.log2(max(0.01, s)) * 8) / 8)        # par 1/8 d'octave : pas un rendu par cran
        return min(8.0, max(0.05, s))

    def _schedule_scale(self) -> None:
        live = self._live
        if live is None or live.fullscreen or self._scale_queued:
            return
        if abs(self._render_scale() - live.view.render_scale) > 1e-6:
            self._scale_queued = True
            QTimer.singleShot(0, self._apply_scale)

    def _apply_scale(self) -> None:
        self._scale_queued = False
        live = self._live
        if live is not None and not live.fullscreen:
            live.view.set_render_scale(self._render_scale())

    # -- souris --

    def _module_active(self) -> bool:
        pane = self.board_pane()
        ctl = getattr(pane, "pdf", None) if pane is not None else None
        return bool(ctl is not None and ctl.active)

    def mousePressEvent(self, event):
        if (event.button() == Qt.LeftButton and self._live is None
                and self._module_active() and not self.locked()
                and not event.modifiers() & Qt.ControlModifier):
            event.accept()
            self.go_live()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if not self.locked():
            event.accept()
            pane = self.board_pane()
            if pane is not None and pane.module != "pdf":
                pane.set_module("pdf")                              # double-clic : le module puis l'édition
            self.go_live()
            return
        super().mouseDoubleClickEvent(event)

    # -- édition sur place --

    def is_live(self) -> bool:
        return self._live is not None

    @property
    def live(self):
        return self._live

    def go_live(self):
        """Édition sur place par le contrôleur du module (un seul document édité à la fois)."""
        pane = self.board_pane()
        if pane is None:
            return None
        if getattr(pane, "pdf", None) is None:
            from .board_ui import PdfBoardController
            pane.pdf = PdfBoardController(pane)
        return pane.pdf.make_live(self)

    def start_live(self, focus: bool = True):
        """Le document de l'élément posé DANS l'élément (vue complète, toutes les pages). Rien n'est rouvert : la
        session de l'aperçu sert telle quelle."""
        if self._live is not None:
            if focus:
                self._focus_live()
            return self._live
        entry = self.entry()
        if entry is None or self.locked():
            return None
        if entry.needs_password and not self._ask_password(entry):
            return None
        if not entry.ready():                                 # ouverture en cours (gros XFA : quelques secondes) :
            if not entry.error:                               # l'édition démarre dès que le document est prêt
                entry.live_wanted = True
            return None
        from .board_live import EmbeddedPdf, LiveDoc
        state = {k: self.data.get(k) for k in ("fit", "zoom", "scroll", "page")}
        live = LiveDoc(entry, _settings(self), state, host=self.board_pane())
        live.item = self
        live.view.margin, live.view.fit_pad = MARGIN, PAD      # même mise en page que l'aperçu
        live.stateChanged.connect(self._live_changed)
        proxy = EmbeddedPdf(self)
        proxy.setWidget(live)
        self._live, self._proxy = live, proxy
        self.setCacheMode(QGraphicsItem.NoCache)
        self.sync()
        live.view.set_render_scale(self._render_scale())
        live.begin()
        if focus:
            self._focus_live()
        self.update()
        return live

    def _focus_live(self) -> None:
        if self._proxy is not None:
            self._proxy.setFocus(Qt.MouseFocusReason)
            self._live.view.setFocus(Qt.MouseFocusReason)

    def _ask_password(self, entry) -> bool:
        from . import ui_kit
        name = entry.path.name if entry.path else "PDF"
        pw = ui_kit.ask_text(self.board_pane(), "Document protégé", "« %s » demande un mot de passe." % name,
                             password=True, action="Ouvrir")
        if not pw:
            return False
        entry.session.open_path(entry.path, pw)
        return True

    def _live_changed(self) -> None:
        try:
            self._sync_tip(self.entry())                     # page courante, « modifié » (infobulle)
        except RuntimeError:
            pass

    def stop_live(self) -> None:
        """Fin de l'édition sur place (module désactivé, autre document édité) : l'endroit où l'on était est
        retenu dans l'élément ; le DOCUMENT reste ouvert (aperçu, saisies non enregistrées)."""
        live, proxy = self._live, self._proxy
        if live is None:
            return
        state = live.view_state()
        live.release()
        self._live = self._proxy = None
        changed = any(self.data.get(k) != v for k, v in state.items())
        self.data.update(state)
        scene = self.scene()
        if scene is not None and getattr(scene, "embedded_item", None) is self:
            scene.embedded_item = None
        proxy.setWidget(None)
        proxy.setParentItem(None)
        if proxy.scene() is not None:
            proxy.scene().removeItem(proxy)
        live.deleteLater()
        proxy.deleteLater()
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self.update()
        if scene is not None:
            if changed and hasattr(scene, "contentChanged"):
                scene.contentChanged.emit()                       # le board retient l'endroit (enregistrement auto)
            views = scene.views()
            if views:
                views[0].setFocus()

    def stop_edit(self) -> None:
        """Clic ailleurs sur le Board (`BoardView._end_embedded`) : le clavier quitte le document, qui reste éditable
        (module actif) ; un clic dessus y revient."""
        scene = self.scene()
        if scene is not None and getattr(scene, "embedded_item", None) is self:
            scene.embedded_item = None
        if self._proxy is not None:
            self._proxy.clearFocus()

    # -- éditeur plein cadre --

    def open_editor(self):
        pane = self.board_pane()
        path = self.pdf_path()
        if pane is None or path is None:
            return None
        if getattr(pane, "pdf", None) is None:
            from .board_ui import PdfBoardController
            pane.pdf = PdfBoardController(pane)
        return pane.pdf.open_editor(path, self)


ITEM_CLASSES[bm.PDF_DOC] = PdfItem
