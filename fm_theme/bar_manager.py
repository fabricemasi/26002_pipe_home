"""Moteur GÉNÉRIQUE des barres d'outils flottantes (la barre elle-même : `fm_theme/palette.py`). Spécification :
docs/agents/barres_outils_spec.md ; référence exacte : docs/agents/prototype_barres_outils.html (son code JS fait foi :
`computeSnap` -> `compute_snap`, `measureTouch` -> `measure_touch`, `onMove` / `onUp` -> `bar_drag_to` / `end_bar_drag`,
`item_drag_to` / `end_item_drag` ; `dropTarget` est remplacé par la case visée, `drop_cell`). Tous les modules l'utilisent ; aucun ne le recode.

- Déplacer une barre par son titre : aimantation EN DIRECT (la barre affichée est toujours à sa position aimantée) :
  près d'un bord elle s'y clipse et prend son orientation tout de suite ; sinon elle s'aimante aux autres barres (contact,
  alignements), une barre clipsée n'offrant que ses deux côtés le long de son bord ; au contact d'une barre clipsée elle
  se clipse sur le même bord. Trait d'accent de 3 px avec une lueur.
- Coins et bordures au contact (`measure_touch`, après chaque mise en page).
- Éléments : vers N'IMPORTE QUELLE case libre (capture annotée de l'utilisateur : la grille remplace les « étages » du
  prototype), de leur barre ou d'une autre, case de dépôt en pointillés accent, cases libres visibles pendant le geste ;
  lâchés dans le vide : nouvelle barre ; une barre vidée disparaît.
- Barre d'état : `statusChanged(texte)` à chaque action (« « Outils » clipsée en haut », « Opacité : largeur 260 px »…).

L'état (`state()`) est un dict JSON à enregistrer par l'hôte : barres (id, titre, bord, orientation, position, grille,
CASE de chaque élément [colonne, ligne, largeur]), largeurs des contrôles et valeurs (par clé : elles suivent l'élément
d'une barre à l'autre), mémoire des cases. `restore()` le reprend ; `reset()` revient au défaut de l'hôte. Les
éléments sont créés et branchés par l'hôte (`register`) : le gestionnaire ne connaît que leurs clés. Aucun import de l'appli.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from fm_theme import palette as P
from fm_theme.palette import ToolBar

DOCKS = ("top", "left", "right", "bottom")
EDGE_FR = {"top": "en haut", "bottom": "en bas", "left": "à gauche", "right": "à droite"}
EPS = 1.5                       # pixels : « au contact »
LINE = 3                        # épaisseur du trait d'aimantation
SAMPLE = 8                      # pixels lus derrière le bord d'une barre clipsée (bordure, puis fond du voisin)
GLOW = 7                        # lueur autour du trait


def clamp(value, low, high):
    return max(low, min(high, value))


def snap_to(value, candidates, tolerance):
    """La valeur de `candidates` la plus proche de `value` si elle est à moins de `tolerance`, sinon `value`."""
    best, best_d = value, tolerance
    for candidate in candidates:
        d = abs(candidate - value)
        if d < best_d:
            best, best_d = candidate, d
    return best


def snap_zone(value, candidates):
    """Comme `snap_to`, avec une zone par candidat : (valeur, zone avant, zone après) ; le plus proche l'emporte."""
    best, best_d = value, None
    for candidate, before, after in candidates:
        d = candidate - value
        if (0 <= d < before or 0 < -d < after) and (best_d is None or abs(d) < best_d):
            best, best_d = candidate, abs(d)
    return best


def dock_orient(edge: str) -> str:
    return "h" if edge in ("top", "bottom") else "v"


def edge_line(edge: str, width: int, height: int) -> tuple:
    """Trait d'aimantation le long d'un bord : (x, y, largeur, hauteur)."""
    return {"top": (0, 0, width, LINE), "bottom": (0, height - LINE, width, LINE),
            "left": (0, 0, LINE, height), "right": (width - LINE, 0, LINE, height)}[edge]


def measure_touch(rects: dict, width: int, height: int) -> dict:
    """Côtés et coins au contact (prototype `measureTouch`) pour chaque barre de `rects` ({id: (x, y, w, h)}) : coin
    carré (`tl`, `tr`, `br`, `bl`) si un côté du coin est plaqué contre un bord ou si une barre voisine couvre ce
    coin ; côté partagé (`nt`, `nr`, `nb`, `nl`) : la bordure du côté le plus court disparaît (égalité : celle de
    droite / du dessous) — une seule bordure de 1 px sépare deux barres."""
    boxes = {k: {"x": v[0], "y": v[1], "w": v[2], "h": v[3]} for k, v in rects.items()}
    out = {}
    for key, r in boxes.items():
        edges = {"l": r["x"] <= EPS, "t": r["y"] <= EPS, "r": r["x"] + r["w"] >= width - EPS, "b": r["y"] + r["h"] >= height - EPS}
        sq = {"tl": edges["t"] or edges["l"], "tr": edges["t"] or edges["r"], "br": edges["b"] or edges["r"],
              "bl": edges["b"] or edges["l"], "nl": False, "nt": False, "nr": False, "nb": False}
        for other_key, o in boxes.items():
            if other_key == key:
                continue
            v_over = r["y"] < o["y"] + o["h"] - 2 and r["y"] + r["h"] > o["y"] + 2
            h_over = r["x"] < o["x"] + o["w"] - 2 and r["x"] + r["w"] > o["x"] + 2
            for side, touching in (("sr", v_over and abs(r["x"] + r["w"] - o["x"]) <= EPS),
                                   ("sl", v_over and abs(o["x"] + o["w"] - r["x"]) <= EPS),
                                   ("sb", h_over and abs(r["y"] + r["h"] - o["y"]) <= EPS),
                                   ("st", h_over and abs(o["y"] + o["h"] - r["y"]) <= EPS)):
                if touching:                # côté collé à une autre barre (réglages « clipsée » : comme un bord)
                    sq[side] = other_key    # « g* » : la partie collée de ce côté (bordure ôtée là seulement)
                    lo, hi = ((max(r["y"], o["y"]) - r["y"], min(r["y"] + r["h"], o["y"] + o["h"]) - r["y"])
                              if side in ("sr", "sl") else
                              (max(r["x"], o["x"]) - r["x"], min(r["x"] + r["w"], o["x"] + o["w"]) - r["x"]))
                    sq["g" + side[1]] = tuple(sorted(sq.get("g" + side[1], ()) + ((round(lo), round(hi)),)))
            if v_over and abs(r["x"] + r["w"] - o["x"]) <= EPS:
                if r["h"] < o["h"] - 0.5:
                    sq["nr"] = True
                if o["y"] <= r["y"] + EPS:
                    sq["tr"] = True
                if o["y"] + o["h"] >= r["y"] + r["h"] - EPS:
                    sq["br"] = True
            if v_over and abs(o["x"] + o["w"] - r["x"]) <= EPS:
                if r["h"] <= o["h"] + 0.5:
                    sq["nl"] = True
                if o["y"] <= r["y"] + EPS:
                    sq["tl"] = True
                if o["y"] + o["h"] >= r["y"] + r["h"] - EPS:
                    sq["bl"] = True
            if h_over and abs(r["y"] + r["h"] - o["y"]) <= EPS:
                if r["w"] < o["w"] - 0.5:
                    sq["nb"] = True
                if o["x"] <= r["x"] + EPS:
                    sq["bl"] = True
                if o["x"] + o["w"] >= r["x"] + r["w"] - EPS:
                    sq["br"] = True
            if h_over and abs(o["y"] + o["h"] - r["y"]) <= EPS:
                if r["w"] <= o["w"] + 0.5:
                    sq["nt"] = True
                if o["x"] <= r["x"] + EPS:
                    sq["tl"] = True
                if o["x"] + o["w"] >= r["x"] + r["w"] - EPS:
                    sq["tr"] = True
        out[key] = sq
    return out


def compute_snap(x: float, y: float, w: float, h: float, others: list, width: int, height: int, tolerance: float,
                 size_for) -> dict:
    """Où ira une barre de w × h tirée en (x, y) (prototype `computeSnap`). `others` : [{x, y, w, h, dock}] ;
    `size_for(orientation)` -> (w, h) de la barre pour cette orientation (prototype : largeur et hauteur échangées).
    Rend {dock, along, x, y, line} : `dock` (bord, ou None si flottante), `along` (position le long du bord), (x, y)
    (position flottante, aimantée aux autres barres), `line` (x, y, w, h) du trait d'aimantation ou None."""
    x, y = clamp(x, 0, max(0, width - w)), clamp(y, 0, max(0, height - h))
    dist = {"top": y, "left": x, "right": width - (x + w), "bottom": height - (y + h)}
    edge, best = None, tolerance
    for key in ("top", "left", "right", "bottom"):
        if dist[key] < best:
            best, edge = dist[key], key
    if edge:
        horizontal = edge in ("top", "bottom")
        size_w, size_h = size_for(dock_orient(edge))
        length = size_w if horizontal else size_h
        limit = max(0, (width if horizontal else height) - length)
        candidates = [0, limit]
        for o in others:                    # toute barre présente dans la bande de ce bord
            in_band = (o["y"] < size_h if edge == "top" else o["y"] + o["h"] > height - size_h if edge == "bottom"
                       else o["x"] < size_w if edge == "left" else o["x"] + o["w"] > width - size_w)
            if not in_band:
                continue
            candidates += [o["x"] + o["w"], o["x"] - length] if horizontal else [o["y"] + o["h"], o["y"] - length]
        along = clamp(snap_to(x if horizontal else y, candidates, tolerance), 0, limit)
        return {"dock": edge, "along": along, "x": x, "y": y, "line": edge_line(edge, width, height)}
    xs, ys = [], []                         # (valeur, zone avant, zone après)
    for o in others:
        v_over = y < o["y"] + o["h"] and y + h > o["y"]
        h_over = x < o["x"] + o["w"] and x + w > o["x"]
        h_dock, v_dock = o["dock"] in ("top", "bottom"), o["dock"] in ("left", "right")
        # contre une face d'une autre barre (y compris la face intérieure d'une barre clipsée : une barre SOUS une
        # barre du haut) : même zone qu'un bord, qui retient aussi la barre enfoncée dedans (jusqu'à sa moitié)
        if v_over:
            xs += [(o["x"] + o["w"], o["w"] / 2, tolerance), (o["x"] - w, tolerance, o["w"] / 2)]
        if h_over:
            ys += [(o["y"] + o["h"], o["h"] / 2, tolerance), (o["y"] - h, tolerance, o["h"] / 2)]
        if not v_dock:
            xs += [(o["x"], tolerance, tolerance), (o["x"] + o["w"] - w, tolerance, tolerance)]
        if not h_dock:
            ys += [(o["y"], tolerance, tolerance), (o["y"] + o["h"] - h, tolerance, tolerance)]
    sx, sy = clamp(snap_zone(x, xs), 0, width - w), clamp(snap_zone(y, ys), 0, height - h)
    line, dock_to = None, None
    for o in others:                        # contact : avec une barre clipsée la barre se clipse sur le même bord
        y0, y1 = max(sy, o["y"]), min(sy + h, o["y"] + o["h"])
        x0, x1 = max(sx, o["x"]), min(sx + w, o["x"] + o["w"])
        on_right, on_left = abs(sx - (o["x"] + o["w"])) < 0.5, abs(sx + w - o["x"]) < 0.5
        below, above = abs(sy - (o["y"] + o["h"])) < 0.5, abs(sy + h - o["y"]) < 0.5
        if y1 - y0 > 2 and (on_right or on_left):
            if o["dock"] in ("top", "bottom"):
                dock_to = {"edge": o["dock"], "along": o["x"] + o["w"] if on_right else o["x"] - size_for("h")[0]}
                break
            line = ((sx if on_right else sx + w) - LINE / 2, y0, LINE, y1 - y0)
        elif x1 - x0 > 2 and (below or above):
            if o["dock"] in ("left", "right"):
                dock_to = {"edge": o["dock"], "along": o["y"] + o["h"] if below else o["y"] - size_for("v")[1]}
                break
            line = (x0, (sy if below else sy + h) - LINE / 2, x1 - x0, LINE)
        if line is not None:
            break
    if dock_to:
        return {"dock": dock_to["edge"], "along": max(0, dock_to["along"]), "x": sx, "y": sy,
                "line": edge_line(dock_to["edge"], width, height)}
    return {"dock": None, "along": 0, "x": sx, "y": sy, "line": line}


class _Patch(QWidget):
    """Pièce de la couleur de fond du voisin posée sur SA bordure, le long d'une barre clipsée ; transparente pour la
    souris."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._color = QColor()

    def set_color(self, color: str) -> None:
        if QColor(color) != self._color:
            self._color = QColor(color)
            self.update()

    def paintEvent(self, event):
        QPainter(self).fillRect(self.rect(), self._color)


class _SnapLine(QWidget):
    """Trait d'aimantation de 3 px, couleur d'accent, avec une lueur ; transparent pour la souris."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._key = None
        self.hide()

    def show_rect(self, rect: tuple, area_origin: QPoint) -> None:
        x, y, w, h = rect
        geometry = QRect(round(x) + area_origin.x() - GLOW, round(y) + area_origin.y() - GLOW,
                         max(1, round(w)) + 2 * GLOW, max(1, round(h)) + 2 * GLOW)
        if geometry != self.geometry():
            self.setGeometry(geometry)
        self.raise_()
        if not self.isVisible():
            self.show()

    def paintEvent(self, event):
        painter = QPainter(self)
        accent = P.LOOK["drop"]
        core = QRectF(self.rect()).adjusted(GLOW, GLOW, -GLOW, -GLOW)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        for step in range(GLOW, 0, -1):                  # lueur : couches de plus en plus serrées
            painter.setBrush(P._alpha(accent, 14))
            painter.drawRoundedRect(core.adjusted(-step, -step, step, step), step, step)
        painter.setBrush(QColor(accent))
        painter.drawRect(core)


class _Ghost(QWidget):
    """Vignette de l'élément tiré (prototype) : l'icône dans une case cernée d'accent, ou une étiquette « Type Libellé »
    pour un contrôle ; « + Nouvelle barre » à côté quand il serait lâché dans le vide. Coin haut gauche à (x − 17, y − 17)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._pixmap = None
        self._texts = None
        self._box = QRect()
        self._badge = QRect()
        self._new = False
        self.hide()

    def start(self, widget: QWidget) -> None:
        look = P.LOOK
        cell = look["cell"]
        metrics = QFontMetrics(P.look_font("bar"))
        if hasattr(widget, "ghost_pixmap"):
            size = widget.bar_size() if hasattr(widget, "bar_size") else widget.size()
            self._pixmap = widget.ghost_pixmap(self.devicePixelRatioF())
            self._texts = None
            self._box = QRect(0, 0, size.width(), size.height())
        else:
            kind = P.KIND_LABELS.get(getattr(widget, "kind", ""), "")
            label = getattr(widget, "label", "") or getattr(widget, "palette_key", "")
            self._pixmap = None
            self._texts = (kind, label)
            width = 12 + metrics.horizontalAdvance(kind) + (8 if kind else 0) + metrics.horizontalAdvance(label) + 12
            self._box = QRect(0, 0, width, cell)
        badge_w = metrics.horizontalAdvance("+ Nouvelle barre") + 16
        self._badge = QRect(self._box.right() + 1 + 8, (cell - 22) // 2, badge_w, 22)
        self.resize(self._badge.right() + 2, max(cell, self._box.height()) + 1)
        self._new = False

    def move_to(self, pos: QPoint) -> None:
        self.move(pos.x() - 17, pos.y() - 17)
        self.raise_()
        if not self.isVisible():
            self.show()

    def set_new(self, new: bool) -> None:
        if new != self._new:
            self._new = new
            self.update()

    def paintEvent(self, event):
        look = P.LOOK
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        box = QRectF(self._box).adjusted(.5, .5, -.5, -.5)
        painter.setPen(QPen(QColor(look["drop"]), 1))
        painter.setBrush(QColor(look["bg"]))
        painter.drawRoundedRect(box, look["cell_radius"], look["cell_radius"])
        if self._pixmap is not None:
            painter.drawPixmap(self._box.topLeft(), self._pixmap)
        elif self._texts is not None:
            kind, label = self._texts
            painter.setFont(P.look_font("bar"))
            metrics = painter.fontMetrics()
            x = self._box.left() + 12
            if kind:
                painter.setPen(QColor(look["bar_ink"]))
                painter.drawText(QRect(x, self._box.top(), metrics.horizontalAdvance(kind), self._box.height()),
                                 Qt.AlignVCenter | Qt.AlignLeft, kind)
                x += metrics.horizontalAdvance(kind) + 8
            painter.setPen(QColor(look["bar_value"]))
            painter.drawText(QRect(x, self._box.top(), self._box.right() - x, self._box.height()),
                             Qt.AlignVCenter | Qt.AlignLeft, label)
        if self._new:
            font = P.look_font("bar")
            font = type(font)(font)
            font.setWeight(font.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(QPen(QColor(look["drop"]), 1, Qt.DashLine))
            painter.setBrush(QColor(look["bg"]))
            painter.drawRoundedRect(QRectF(self._badge).adjusted(.5, .5, -.5, -.5), 4, 4)
            painter.setPen(QColor(look["bar_value"]))
            painter.drawText(self._badge, Qt.AlignCenter, "+ Nouvelle barre")


class _StatusLine(QWidget):
    """Ligne d'état des barres (spec § 9) quand l'hôte n'en a pas : une étiquette discrète en bas de la zone, au-dessus des
    barres clipsées en bas, effacée après `STATUS_MS` ; transparente pour la souris."""

    STATUS_MS = 2500

    def __init__(self, parent):
        super().__init__(parent)
        from PySide6.QtCore import QTimer
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._text = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def show_text(self, text: str, area: QRect, bottom: int) -> None:
        self._text = text
        metrics = QFontMetrics(P.look_font("bar"))
        width = min(max(40, area.width() - 16), metrics.horizontalAdvance(text) + 28)
        height = metrics.height() + 10
        self.setGeometry(area.x() + (area.width() - width) // 2, bottom - height - 8, width, height)
        self.raise_()
        self.show()
        self.update()
        self._timer.start(self.STATUS_MS)

    def paintEvent(self, event):
        look = P.LOOK
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(look["border"]["top"]), 1))
        painter.setBrush(QColor(look["bg"]))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 4, 4)
        painter.setFont(P.look_font("bar"))
        painter.setPen(QColor(look["bar_value"]))
        painter.drawText(self.rect().adjusted(10, 0, -10, 0), Qt.AlignCenter,
                         painter.fontMetrics().elidedText(self._text, Qt.ElideMiddle, max(1, self.width() - 20)))


class BarManager(QObject):
    """Les barres d'un espace de travail (un QWidget : les barres en sont les enfants). `set_area(rect)` : la zone où
    elles se clipsent (défaut : tout l'espace ; le Board la décale à droite de sa barre des modules). Signaux :
    `layoutChanged()` à la fin de chaque geste (l'hôte enregistre alors `state()`), `statusChanged(texte)`."""

    layoutChanged = Signal()
    statusChanged = Signal(str)

    def __init__(self, workspace: QWidget, parent=None):
        super().__init__(parent or workspace)
        self.ws = workspace
        self.bars: list[ToolBar] = []             # de l'arrière vers l'avant
        self.widgets: dict[str, QWidget] = {}     # éléments inscrits par l'hôte, par clé
        self.default_state: dict | None = None
        self.memory: dict[str, list] = {}         # clé -> [id de barre, rang] : même pour un élément absent
        self.dynamic: dict[str, list] = {}        # groupe -> clés des éléments refaits à la demande (`set_dynamic`)
        self.widths: dict[str, int] = {}          # largeur de chaque contrôle (px), par clé
        self.values: dict[str, object] = {}       # valeur de chaque contrôle enregistré (`persist_value`), par clé
        self.new_bar_title = "Barre {n}"
        self.status_text = ""
        self.show_status = True                   # ligne d'état propre (l'hôte qui a la sienne la coupe et suit `statusChanged`)
        self._status_line = None
        self._area: QRect | None = None
        self._next = 1
        self._visible = True
        self._bar_drag = None
        self.snap_color = None                     # hôte : (barre, bord) -> couleur de l'élément voisin, ou None
        self._snap_cache: dict = {}
        self._patches: dict = {}                 # pièces posées sur la bordure du voisin, par barre
        self._item_drag = None
        self._line = _SnapLine(workspace)
        self._ghost = _Ghost(workspace)
        workspace.installEventFilter(self)

    def status(self, text: str) -> None:
        self.status_text = text
        self.statusChanged.emit(text)
        if self.show_status and text and self.ws.isVisible():
            if self._status_line is None:
                self._status_line = _StatusLine(self.ws)
            area = self.area()
            bottom = min([b.y() for b in self.bars if b.isVisible() and b.dock == "bottom"] + [area.bottom() + 1])
            self._status_line.show_text(text, area, bottom)

    # -- Espace -------------------------------------------------------------------------------------------------------

    def area(self) -> QRect:
        return QRect(self._area) if self._area is not None else QRect(0, 0, self.ws.width(), self.ws.height())

    def set_area(self, rect: QRect | None) -> None:
        if rect != self._area:
            self._area = QRect(rect) if rect is not None else None
            self.relayout()

    def eventFilter(self, obj, event):
        if obj is self.ws and event.type() in (QEvent.Resize, QEvent.Show):
            self.relayout()                        # (montré : les contacts se mesurent sur les barres visibles)
        return False

    # -- Éléments et barres -------------------------------------------------------------------------------------------

    def register(self, key: str, widget: QWidget) -> QWidget:
        """Inscrit un élément (icône, contrôle) : il vit sur l'espace de travail, caché, jusqu'à ce qu'une barre le
        reprenne (`restore`)."""
        self.widgets[key] = widget
        widget.setParent(self.ws)
        widget.hide()
        self._apply_saved(key, widget)
        changed = getattr(widget, "valueChanged", None)
        if changed is not None and hasattr(widget, "saved_value"):
            changed.connect(lambda *_a, k=key, w=widget: self._value_changed(k, w))
        return widget

    def _apply_saved(self, key: str, widget: QWidget) -> None:
        if key in self.widths and hasattr(widget, "set_bar_width"):
            widget.set_bar_width(self.widths[key])
        if key in self.values and getattr(widget, "persist_value", False):
            try:
                widget.load_value(self.values[key])
            except (TypeError, ValueError):
                pass

    def _value_changed(self, key: str, widget: QWidget) -> None:
        """Un contrôle a changé : sa valeur est retenue (si enregistrée) et la barre d'état l'annonce (« Opacité : 80 % »)."""
        try:
            value = widget.saved_value()
        except RuntimeError:
            return
        if getattr(widget, "persist_value", False):
            self.values[key] = value
        unit = getattr(widget, "unit", "")
        self.status(f"{getattr(widget, 'label', key)} : {value}{(' ' + unit) if unit else ''}")

    def add_bar(self, title: str = "", cols: int = 3, rows: int = 1, dock: str | None = None, orient: str = "h",
                x: int = 0, y: int = 0, bar_id: str | None = None, along: int = 0, **_compat) -> ToolBar:
        number = self._next
        if not bar_id:
            bar_id = f"b{number}"
        if bar_id[1:].isdigit():
            number = int(bar_id[1:])
        self._next = max(self._next, number + 1)
        dock = dock if dock in DOCKS else None
        orient = dock_orient(dock) if dock else ("v" if orient == "v" else "h")
        bar = ToolBar(title or self.new_bar_title.format(n=number), cols, rows, self.ws, orient)
        bar.manager, bar.bar_id = self, bar_id
        bar.layoutChanged.connect(self._bar_changed)          # fin de geste d'une barre (taille, renommer, pivoter...)
        bar.end = False                                       # collée à la fin de son bord (droite / bas), quelle que soit la zone
        bar.after = ""                                        # collée derrière la barre de cet identifiant (même bord)
        bar.fx, bar.fy = x, y                                 # position flottante VOULUE (dans la zone) : l'affichage la borne
                                                              # à la zone du moment (démarrage : zone minuscule) sans l'oublier
        bar.set_dock(dock)
        bar.along = along
        bar.want = along                                      # place VOULUE le long du bord : une voisine qui grandit la
                                                              # repousse (`_push_apart`), elle y revient quand la place se libère
        self.bars.append(bar)
        bar.show()
        self.place(bar)
        return bar

    def bar(self, bar_id: str) -> ToolBar | None:
        return next((b for b in self.bars if b.bar_id == bar_id), None)

    def bar_of(self, key: str) -> ToolBar | None:
        return next((b for b in self.bars if key in b._items), None)

    def remove_bar(self, bar: ToolBar) -> None:
        if bar in self.bars:
            self.bars.remove(bar)
        for key in bar.keys():                    # ses éléments retournent sur l'espace de travail (cachés)
            widget = bar.detach_item(key).widget
            widget.setParent(self.ws)
            widget.hide()
        bar.hide()
        bar.setParent(None)
        bar.deleteLater()

    def bring_to_front(self, bar: ToolBar) -> None:
        if bar in self.bars:
            self.bars.remove(bar)
            self.bars.append(bar)
        bar.raise_()
        if self._line.isVisible():
            self._line.raise_()

    # -- Place et jonctions -------------------------------------------------------------------------------------------

    def place(self, bar: ToolBar, animate: bool = False) -> None:
        """Pose la barre selon son bord (`dock`, `along` ; clipsée à droite / en bas : par rapport à CE bord) ou sa
        position flottante, dans la zone. Pendant un déplacement de barre, celles qui lui font place sont menées par
        `_live_arrange`."""
        if self._bar_drag is not None and bar is not self._bar_drag["bar"] and getattr(bar, "_live", None) is not None:
            return
        area = self.area()
        w, h = bar.width(), bar.height()
        if area.width() <= 0 or area.height() <= 0:
            return
        prev = self.bar(bar.after) if bar.after else None
        if prev is not None and prev is not bar and prev.dock == bar.dock and bar.dock:
            bar.along = prev.along + (prev.height() if bar.dock in ("left", "right") else prev.width())
        along_x = max(0, area.width() - w) if bar.end else clamp(bar.along, 0, max(0, area.width() - w))
        along_y = max(0, area.height() - h) if bar.end else clamp(bar.along, 0, max(0, area.height() - h))
        if bar.dock == "top":
            pos = (along_x, 0)
        elif bar.dock == "bottom":
            pos = (along_x, area.height() - h)
        elif bar.dock == "left":
            pos = (0, along_y)
        elif bar.dock == "right":
            pos = (area.width() - w, along_y)
        else:
            pos = (clamp(bar.fx, 0, max(0, area.width() - w)), clamp(bar.fy, 0, max(0, area.height() - h)))
        target = QPoint(area.x() + round(pos[0]), area.y() + round(pos[1]))
        self._move_bar(bar, target, animate)

    def _docked_pos(self, bar: ToolBar, along: float) -> QPoint:
        """Position d'une barre clipsée posée à `along` le long de son bord (sans `after` ni `end`)."""
        area = self.area()
        w, h = bar.width(), bar.height()
        along_x, along_y = clamp(along, 0, max(0, area.width() - w)), clamp(along, 0, max(0, area.height() - h))
        pos = {"top": (along_x, 0), "bottom": (along_x, area.height() - h), "left": (0, along_y),
               "right": (area.width() - w, along_y)}[bar.dock]
        return QPoint(area.x() + round(pos[0]), area.y() + round(pos[1]))

    def _move_bar(self, bar: ToolBar, target: QPoint, animate: bool = False) -> None:
        """Pose une barre ; `animate` : elle GLISSE (barres qui font place, rangement Ctrl + clic)."""
        anim = getattr(bar, "_slide", None)
        if anim is not None:
            if anim.endValue() == target and anim.state() == QPropertyAnimation.Running:
                return
            anim.stop()
            bar._slide = None
        if bar.pos() == target:
            return
        ms = P.LOOK["slide_ms"]
        if not animate or not ms or not bar.isVisible():
            bar.move(target)
            return
        anim = QPropertyAnimation(bar, b"pos", self)
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setEndValue(target)
        anim.finished.connect(self.measure)        # coins et bordures au contact : à l'arrivée
        bar._slide = anim
        anim.start()

    def finish_slides(self) -> None:
        for bar in self.bars:
            anim = getattr(bar, "_slide", None)
            if anim is not None:
                end = anim.endValue()
                anim.stop()
                bar._slide = None
                bar.move(end)
        self.measure()

    def relayout(self, animate: bool = False) -> None:
        self._snap_cache.clear()                   # l'élément voisin a pu changer de couleur
        self._push_apart()
        for bar in self.bars:
            self.place(bar, animate)
        self.measure()

    def _edge_length(self, bar: ToolBar) -> int:
        return bar.width() if bar.dock in ("top", "bottom") else bar.height()

    def _arrange_edge(self, edge: str, dragged: ToolBar | None = None) -> dict:
        """Places le long d'un bord ({barre: début}) : chaque barre à sa place voulue, sans chevauchement (`_push_apart`) ;
        avec `dragged` (barre tirée sur ce bord) : les barres dont le milieu est avant le sien GLISSENT vers l'arrière pour
        lui faire place, les autres vers l'avant ; elle-même est poussée si le bord manque de place."""
        group = [b for b in self.bars if b.dock == edge and not b.isHidden() and b is not dragged]
        by_id = {b.bar_id: b for b in group}

        def anchor(b, depth=0):
            prev = by_id.get(b.after) if b.after else None
            return anchor(prev, depth + 1) + 0.5 if prev is not None and depth < 20 else float(b.want)

        horizontal = edge in ("top", "bottom")
        area = self.area()
        limit_all = area.width() if horizontal else area.height()
        pos, cursor = {}, 0
        for b in sorted((b for b in group if not b.end), key=anchor):
            start = cursor if b.after and b.after in by_id else max(b.want, cursor)
            pos[b] = start
            cursor = start + self._edge_length(b)
        for b in (b for b in group if b.end):
            pos[b] = max(0, limit_all - self._edge_length(b))
        if dragged is None:
            return pos
        length = self._edge_length(dragged)
        start = clamp(dragged.along, 0, max(0, limit_all - length))
        middle = start + length / 2
        order = sorted(group, key=lambda b: pos[b])
        before = [b for b in order if pos[b] + self._edge_length(b) / 2 < middle]
        after = [b for b in order if b not in before]
        limit = start
        for b in reversed(before):                 # vers l'arrière, collées devant elle si besoin
            if pos[b] + self._edge_length(b) > limit:
                pos[b] = limit - self._edge_length(b)
            limit = min(limit, pos[b])
        if before and pos[before[0]] < 0:          # plus de place devant : tout le bloc (et elle) avance
            shift = -pos[before[0]]
            for b in before:
                pos[b] += shift
            start += shift
        cursor = start + length
        for b in after:                            # vers l'avant, derrière elle
            pos[b] = max(pos[b], cursor)
            cursor = pos[b] + self._edge_length(b)
        pos[dragged] = start
        return pos

    def _live_arrange(self, bar: ToolBar) -> None:
        """Pendant un déplacement : sur le bord visé, les barres glissent pour faire place ; ailleurs elles reviennent."""
        for edge in DOCKS:
            pos = self._arrange_edge(edge, bar if bar.dock == edge else None)
            for other, start in pos.items():
                if other is bar:
                    bar.along = round(start)
                    continue
                other._live = start
                self._move_bar(other, self._docked_pos(other, start), animate=True)

    def _window_middle(self, edge: str) -> float:
        """Milieu de la fenêtre de premier niveau, le long de `edge`, en coordonnées de la zone des barres."""
        area = self.area()
        window = self.ws.window()
        center = self.ws.mapFrom(window, window.rect().center()) if window is not self.ws else self.ws.rect().center()
        return center.x() - area.x() if edge in ("top", "bottom") else center.y() - area.y()

    def align_edge(self, edge: str, mode: str) -> None:
        """Range les barres clipsées sur `edge` en un bloc : au début (« start »), au milieu (« center ») ou à la fin
        (« end ») du bord (Ctrl + clic milieu : sur un en-tête, centrer ; sur une tranche, pousser de ce côté).
        Centrer = au milieu de la FENÊTRE entière (demande de l'utilisateur), pas de la zone des barres."""
        group = sorted((b for b in self.bars if b.dock == edge and not b.isHidden()),
                       key=lambda b: b.x() if edge in ("top", "bottom") else b.y())
        if not group:
            return
        area = self.area()
        length = area.width() if edge in ("top", "bottom") else area.height()
        total = sum(self._edge_length(b) for b in group)
        low, high = self._edge_span(edge, group)
        high = max(high, low + total)
        middle = self._window_middle(edge)
        center = clamp(round(middle - total / 2), low, max(low, high - total))
        start = {"start": low, "center": center, "end": max(low, high - total)}[mode]
        for b in group:
            b.want = b.along = start
            b.after, b.end = "", False
            start += self._edge_length(b)
        self.relayout(animate=True)
        where = {"start": "au début", "center": "au milieu", "end": "à la fin"}[mode]
        self.status(f"Barres {EDGE_FR[edge]} rangées {where} du bord")
        self.remember()
        self.layoutChanged.emit()

    def _edge_span(self, edge: str, group: list) -> tuple:
        """Portion libre d'un bord pour ses barres : une barre clipsée sur un bord VOISIN qui occupe le coin (elle est
        dans la bande de ce bord) en est retirée : les barres se plaquent contre elle, pas contre le bord de la zone."""
        area = self.area()
        horizontal = edge in ("top", "bottom")
        length = area.width() if horizontal else area.height()
        band = max(b.height() if horizontal else b.width() for b in group)
        low, high = 0, length
        for b in self.bars:
            if b in group or b.isHidden() or b.dock not in DOCKS or dock_orient(b.dock) == dock_orient(edge):
                continue
            x, y = b.x() - area.x(), b.y() - area.y()
            start, size = (y, b.height()) if horizontal else (x, b.width())     # en travers du bord
            far = area.height() if horizontal else area.width()
            in_band = start < band if edge in ("top", "left") else start + size > far - band
            if not in_band:
                continue
            if b.dock in ("left", "top"):
                low = max(low, (x + b.width()) if horizontal else (y + b.height()))
            else:
                high = min(high, x if horizontal else y)
        return low, high

    def bar_resized(self, bar: ToolBar) -> None:
        """La taille d'une barre a changé : elle reste ancrée à son bord, ses voisines du même bord sont repoussées (ou
        reviennent), les jonctions sont refaites."""
        if bar not in self.bars:
            return
        self.relayout()

    def _push_apart(self) -> None:
        """Les barres clipsées sur un même bord ne se CHEVAUCHENT jamais : dans l'ordre le long du bord, chacune est posée
        à sa place voulue (`want`) ou, si la précédente déborde dessus, juste derrière elle (elle est repoussée) ; une
        barre collée derrière une autre (`after`) la suit. La barre en cours de déplacement n'est pas comptée (elle se
        range au relâchement) ; une barre cachée non plus."""
        dragged = self._bar_drag["bar"] if self._bar_drag else None
        for edge in DOCKS:
            group = [b for b in self.bars if b.dock == edge and not b.isHidden() and not b.end and b is not dragged]
            if len(group) < 2:
                for b in group:
                    if not b.after:
                        b.along = b.want
                continue
            horizontal = edge in ("top", "bottom")
            by_id = {b.bar_id: b for b in group}

            def anchor(b, depth=0):
                prev = by_id.get(b.after) if b.after else None
                return anchor(prev, depth + 1) + 0.5 if prev is not None and depth < 20 else float(b.want)

            cursor = 0
            for b in sorted(group, key=anchor):
                start = cursor if b.after and b.after in by_id else max(b.want, cursor)
                b.along = start
                cursor = start + (b.width() if horizontal else b.height())

    def measure(self) -> None:
        area = self.area()
        shown = [b for b in self.bars if b.isVisible()]
        touch = measure_touch({id(b): (b.x() - area.x(), b.y() - area.y(), b.width(), b.height()) for b in shown},
                              area.width(), area.height())
        look = P.LOOK
        sample = look["snap_header_color"] or look["snap_bg_color"] or look["snap_border_match"] \
            or look["snap_border_off"]
        by_id = {id(b): b for b in shown}
        neighbours = {}
        for bar in shown:
            x, y = bar.x() - area.x(), bar.y() - area.y()
            flags = dict(touch[id(bar)])            # côtés plaqués contre un bord de la zone (bordure ôtée au réglage)
            flags.update({"el": x <= EPS, "et": y <= EPS, "er": x + bar.width() >= area.width() - EPS,
                          "eb": y + bar.height() >= area.height() - EPS})
            neighbours[bar] = [by_id[flags[s]] for s in ("st", "sl", "sr", "sb") if flags.get(s) in by_id]
            bar.set_touch({k: v if k[0] == "g" else bool(v) for k, v in flags.items()})
        seen = set()
        if sample and self._bar_drag is None:      # pendant un geste : les couleurs d'avant (pas de capture)
            for bar in shown:                      # contre un bord de la zone : l'élément qui est derrière
                if bar.dock and bar.isVisible():
                    fill, border, border_w = self._outside(bar)
                    bar.set_snap_color(fill, border, border_w)
                    seen.add(bar)
            for _ in range(len(shown)):            # contre une autre barre : SES couleurs (de proche en proche)
                grown = False
                for bar in shown:
                    if bar in seen:
                        continue
                    near = next((n for n in neighbours[bar] if n in seen), None)
                    if near is None:
                        continue
                    bar.set_snap_color(*self._bar_colors(near))
                    seen.add(bar)
                    grown = True
                if not grown:
                    break
        if not sample:
            for bar in shown:
                bar.set_snap_color("")
        elif self._bar_drag is None:
            for bar in shown:                      # seule, sans voisin : pas de couleur empruntée
                if bar not in seen:
                    bar.set_snap_color("")
        self._sync_patches(shown if sample and look["snap_border_off"] else [])

    @staticmethod
    def _bar_colors(bar: ToolBar) -> tuple:
        """(fond, bordure, épaisseur) d'une barre voisine : ce qu'elle a emprunté, sinon son habillage."""
        look = P.LOOK
        fill = bar._snap_color if bar._snap_color and look["snap_bg_color"] else look["bg"]
        if bar._snap_border and look["snap_border_match"]:
            return fill, bar._snap_border, bar._snap_border_w
        if bar.borderless():                        # elle-même sans bordure (voisin sans bordure) : de proche en proche
            return fill, "", 0
        border = look["border"]["top"] if look["border_w"] and any(look["border_on"].values()) else ""
        return fill, border, look["border_w"] if border else 0

    def _sync_patches(self, bars: list) -> None:
        """« Clipsée : pas de bordure du côté collé » : la bordure de l'élément voisin disparaît aussi, le long de la
        barre seulement (une pièce de sa couleur de fond posée dessus, transparente pour la souris), sur CHAQUE bord de
        la zone que la barre touche (une barre du haut contre le bord gauche : la bordure du voisin de gauche aussi)."""
        keep = set()
        area = self.area()
        for bar in bars:
            if not bar.dock:
                continue
            for edge in self._touched_edges(bar, area):
                fill, border, border_w = (bar._snap_color, bar._snap_border, bar._snap_border_w)                     if edge == bar.dock else self._outside(bar, edge)
                if border and fill and self._place_patch(bar, edge, fill, max(1, border_w), area):
                    keep.add((bar, edge))
        for key in list(self._patches):
            if key not in keep:
                self._patches.pop(key).deleteLater()

    @staticmethod
    def _touched_edges(bar: ToolBar, area: QRect) -> list:
        geo = bar.geometry()
        return [edge for edge, hit in (("top", geo.top() - area.top() <= EPS),
                                       ("bottom", area.bottom() - geo.bottom() <= EPS),
                                       ("left", geo.left() - area.left() <= EPS),
                                       ("right", area.right() - geo.right() <= EPS)) if hit]

    def _place_patch(self, bar: ToolBar, edge: str, fill: str, bw: int, area: QRect) -> bool:
        """Pièce de la couleur `fill` sur la bordure du voisin derrière le bord `edge`, le long de la barre."""
        geo = bar.geometry()
        rect = {"top": QRect(geo.left(), area.top() - bw, geo.width(), bw),
                "bottom": QRect(geo.left(), area.bottom() + 1, geo.width(), bw),
                "left": QRect(area.left() - bw, geo.top(), bw, geo.height()),
                "right": QRect(area.right() + 1, geo.top(), bw, geo.height())}[edge]
        host = self.ws                         # la pièce vit au plus près : l'espace des barres s'il contient le
        if not host.rect().contains(rect):     # voisin, sinon son parent (jamais au-dessus du reste de l'appli)
            host = self.ws.parentWidget() or self.ws
            if host is not self.ws:
                rect = QRect(self.ws.mapTo(host, rect.topLeft()), rect.size())
        if not host.rect().intersects(rect):
            return False
        key = (bar, edge)
        patch = self._patches.get(key)
        if patch is not None and patch.parentWidget() is not host:
            self._patches.pop(key).deleteLater()
            patch = None
        if patch is None:
            patch = self._patches[key] = _Patch(host)
        patch.set_color(fill)
        patch.setGeometry(rect)
        patch.show()
        patch.raise_()
        return True

    def _outside_color(self, bar: ToolBar) -> str:
        return self._outside(bar)[0]

    def _outside(self, bar: ToolBar, edge: str = "") -> tuple:
        """(fond, bordure, épaisseur) de l'élément juste derrière le bord où la barre est clipsée : une bande de
        `SAMPLE` pixels de la fenêtre, prise au milieu du côté collé, vers l'extérieur ; ses premiers pixels, s'ils
        diffèrent de la suite, sont sa BORDURE (« » : pas de bordure), le fond est derrière. L'hôte peut donner le fond
        lui-même (`snap_color(barre, bord)`)."""
        edge = edge or bar.dock
        if self.snap_color is not None:
            color = self.snap_color(bar, edge)
            if color:
                return color, "", 0
        area, geo = self.area(), bar.geometry()
        cx, cy = geo.center().x(), geo.center().y()
        n = SAMPLE
        strip = {"top": QRect(cx, area.top() - n, 1, n), "bottom": QRect(cx, area.bottom() + 1, 1, n),
                 "left": QRect(area.left() - n, cy, n, 1), "right": QRect(area.right() + 1, cy, n, 1)}[edge]
        window = self.ws.window()
        if window is not self.ws:
            strip = QRect(self.ws.mapTo(window, strip.topLeft()), strip.size())
        strip = strip.intersected(window.rect())
        if strip.isEmpty():
            return "", "", 0
        key = (edge, strip.x(), strip.y(), strip.width(), strip.height())
        cached = self._snap_cache.get(key)
        if cached is not None:
            return cached
        patch = self._patches.get((bar, edge))    # sa propre pièce ne doit pas cacher la bordure du voisin
        if patch is not None:
            patch.hide()
        image = window.grab(strip).toImage()
        if patch is not None:
            patch.show()
        if image.isNull():
            return "", "", 0
        sx, sy = image.width() / max(1, strip.width()), image.height() / max(1, strip.height())
        pixels = [image.pixelColor(int(i * sx) if strip.height() == 1 else 0, 0 if strip.height() == 1 else int(i * sy))
                  .name() for i in range(max(strip.width(), strip.height()))]
        if edge in ("top", "left"):                # du bord de la zone vers l'extérieur
            pixels.reverse()
        run = 1
        while run < len(pixels) and pixels[run] == pixels[0]:
            run += 1
        if run < len(pixels) and run <= 4:         # quelques pixels différents de la suite : une bordure
            result = (pixels[min(run + 1, len(pixels) - 1)], pixels[0], run)
        else:
            result = (pixels[0], "", 0)
        self._snap_cache[key] = result
        return result

    # -- Visibilité ---------------------------------------------------------------------------------------------------

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        self.sync_visibility()
        if not self._visible:
            self._sync_patches([])

    def sync_visibility(self) -> None:
        """Une barre se montre si le gestionnaire est visible et si un de ses éléments l'est (l'hôte cache un outil
        qui ne s'applique pas : il sort de la mise en page) ; une barre dont tout est caché disparaît."""
        for bar in self.bars:
            shown = self._visible and any(not i.widget.isHidden() for i in bar._items.values())
            if shown == bar.isHidden():                 # (état demandé, pas visibilité effective : l'espace peut être caché)
                bar.setVisible(shown)
            bar.relayout()
        self.relayout()

    # -- Déplacer une barre : glisser son titre (prototype `onBarDown` / `onMove` / `onUp`) ---------------------------

    def begin_bar_drag(self, bar: ToolBar, global_pos: QPoint) -> None:
        p = self.ws.mapFromGlobal(global_pos)
        self.bring_to_front(bar)
        bar.set_moving(True)
        area = self.area()
        others = [{"x": b.x() - area.x(), "y": b.y() - area.y(), "w": b.width(), "h": b.height(), "dock": b.dock}
                  for b in self.bars if b is not bar and b.isVisible()]
        turned = bar.grid_size(bar.rows, bar.cols, "v" if bar.orient == "h" else "h")     # grille transposée
        self._bar_drag = {"bar": bar, "off": QPoint(p.x() - bar.x(), p.y() - bar.y()), "w": bar.width(),
                          "h": bar.height(), "orient": bar.orient, "others": others, "snap": None,
                          "layout": bar.layout_snapshot(), "turned": (turned.width(), turned.height())}
        self.bar_drag_to(bar, global_pos)          # aimantée dès l'appui, comme le prototype

    def bar_drag_to(self, bar: ToolBar, global_pos: QPoint) -> None:
        d = self._bar_drag
        if d is None or d["bar"] is not bar:
            return
        area = self.area()
        p = self.ws.mapFromGlobal(global_pos)
        w, h, orient, turned = d["w"], d["h"], d["orient"], d["turned"]
        snap = compute_snap(p.x() - d["off"].x() - area.x(), p.y() - d["off"].y() - area.y(), w, h, d["others"],
                            area.width(), area.height(), P.LOOK["snap"],
                            lambda o: (w, h) if o == orient else turned)
        d["snap"] = snap
        bar.end, bar.after = False, ""
        wanted = dock_orient(snap["dock"]) if snap["dock"] else orient
        if wanted != bar.orient:                   # la grille se transpose ; revenue à son sens, elle est remise telle quelle
            if wanted == orient:
                bar.apply_snapshot(d["layout"])
            else:
                bar.set_orient(wanted)
        if snap["dock"]:
            bar.along = bar.want = round(snap["along"])
            bar.set_dock(snap["dock"])
        else:
            bar.fx, bar.fy = round(snap["x"]), round(snap["y"])
            bar.set_dock(None)
        self._live_arrange(bar)                    # sur un bord, les autres barres glissent pour lui faire place
        self.place(bar)
        if snap["line"]:
            self._line.show_rect(snap["line"], area.topLeft())
        else:
            self._line.hide()
        self.measure()

    def end_bar_drag(self, bar: ToolBar) -> None:
        d, self._bar_drag = self._bar_drag, None
        self._line.hide()
        if d is None:
            return
        bar.set_moving(False)
        if bar.dock:                               # la place faite est gardée : ordre et positions du bord retenus
            for other in self.bars:
                if other.dock == bar.dock and not other.isHidden():
                    start = bar.along if other is bar else getattr(other, "_live", other.along)
                    other.want = other.along = round(start)
                    other.after, other.end = "", False
        for other in self.bars:
            other._live = None
        self.relayout(animate=True)                # rangée : ses voisines du bord la laissent en place
        title = bar.title()
        self.status(f"« {title} » clipsée {EDGE_FR[bar.dock]}" if bar.dock else f"« {title} » flottante")
        self.remember()
        self.layoutChanged.emit()

    def _bar_changed(self) -> None:
        for bar in self.bars:                      # taille / largeur changées : places à jour
            self.place(bar)
        self.measure()
        self.remember()
        self.layoutChanged.emit()

    # -- Déplacer un élément vers une case libre, d'une barre à l'autre ou dans le vide --------------------------------

    def item_dragging(self, widget: QWidget) -> bool:
        return self._item_drag is not None and self._item_drag["widget"] is widget

    def begin_item_drag(self, bar: ToolBar, item, global_pos: QPoint) -> None:
        widget = item.widget
        self._ghost.start(widget)
        self._item_drag = {"bar": bar, "key": item.key, "widget": widget, "w": item.w, "target": None, "cell": None,
                           "pos": self.ws.mapFromGlobal(global_pos)}
        bar.set_skip(item.key)                     # sa case est libre le temps du geste
        for b in self.bars:
            b.show_free(True)
        self.item_drag_to(global_pos)

    def _bar_at(self, ws_pos: QPoint) -> ToolBar | None:
        for bar in reversed(self.bars):
            if bar.isVisible() and bar.geometry().contains(ws_pos):
                return bar
        return None

    @staticmethod
    def drop_cell(bar: ToolBar, local: QPoint, w: int, key: str) -> tuple[int, int]:
        """Case visée par le curseur (`local` : coordonnées de la barre) pour un élément de `w` cases centré sous lui : la
        case elle-même si elle est libre, sinon la place libre la plus proche (la barre grandit si elle est pleine)."""
        origin, look = bar.origin(), P.LOOK
        stp = look["cell"] + look["gap"]
        col = round((local.x() - origin.x() - (P.cells_px(w)) / 2 + look["gap"] / 2) / stp)
        row = int((local.y() - origin.y() + look["gap"] / 2) // stp)
        base_cols, base_rows = bar._grid_before or (bar.cols, bar.rows)
        return clamp(col, 0, max(0, base_cols - w)), clamp(row, 0, base_rows - 1)     # prise : les autres glissent

    def item_drag_to(self, global_pos: QPoint) -> None:
        d = self._item_drag
        if d is None:
            return
        pos = self.ws.mapFromGlobal(global_pos)
        d["pos"] = pos
        self._ghost.move_to(pos)
        target = self._bar_at(pos)
        if target is not d["target"] and d["target"] is not None:
            d["target"].set_target(False, None)    # (rend sa grille à la barre quittée)
            target = self._bar_at(pos)
        cell = None
        if target is not None:
            cell = self.drop_cell(target, target.mapFromGlobal(global_pos), d["w"], d["key"])
            target.set_target(True, (cell[0], cell[1], d["w"]))
        d["target"], d["cell"] = target, cell
        self._ghost.set_new(target is None)

    def end_item_drag(self) -> None:
        d, self._item_drag = self._item_drag, None
        if d is None:
            return
        key, widget, source, target, cell = d["key"], d["widget"], d["bar"], d["target"], d["cell"]
        self._ghost.hide()
        for bar in self.bars:
            bar.show_free(False)
        source.set_skip("")
        label = getattr(widget, "label", "") or key
        placed = source.detach_item(key)
        width = placed.w if placed is not None else None
        if target is not None:
            target.commit_room()                   # ceux qui ont glissé gardent leur nouvelle case
            target.set_target(False, None)
            target.add_item(key, widget, cell[0], cell[1], width)
            target.finish_slides()
            message = f"{label} → « {target.title()} »"
        else:
            target = self._to_new_bar(key, widget, d["pos"], width)
            message = f"Nouvelle barre « {target.title()} » — Ctrl+clic sur son titre pour la renommer"
        source.relayout()
        if not source._items and source in self.bars:
            message += f" · « {source.title()} » vide, supprimée"
            self.remove_bar(source)                # barre vidée : supprimée
        widget.update()
        self.sync_visibility()
        self.status(message)
        self.remember()
        self.layoutChanged.emit()

    def _to_new_bar(self, key: str, widget: QWidget, ws_pos: QPoint, width: int | None = None) -> ToolBar:
        """Élément lâché dans le vide : une nouvelle barre flottante horizontale « Barre N » sous le curseur, juste à sa
        taille."""
        area = self.area()
        x = clamp(ws_pos.x() - area.x() - 24, 0, max(0, area.width() - 60))
        y = clamp(ws_pos.y() - area.y() - 20, 0, max(0, area.height() - 64))
        bar = self.add_bar(cols=1, rows=1, x=x, y=y)
        bar.add_item(key, widget, 0, 0, width)
        self.bring_to_front(bar)
        self.place(bar)
        return bar

    # -- Mémoire des places et éléments refaits à la demande ----------------------------------------------------------

    def remember(self) -> None:
        """Retient la case de chaque élément posé (les absents gardent la leur : un élément refait plus tard, comme les
        boutons de la barre contextuelle d'une sélection, retrouve sa case)."""
        for bar in self.bars:
            for key, placed in bar._items.items():
                self.memory[key] = [bar.bar_id, placed.col, placed.row, placed.w]
                if hasattr(placed.widget, "bar_width"):
                    self.widths[key] = P.cells_px(placed.w)

    def ensure_bar(self, bar_id: str) -> ToolBar | None:
        """La barre `bar_id`, refaite (vide) d'après la disposition par défaut si l'utilisateur l'avait vidée."""
        bar = self.bar(bar_id)
        if bar is not None:
            return bar
        for entry in (self.default_state or {}).get("bars") or []:
            if isinstance(entry, dict) and entry.get("id") == bar_id:
                return self._make_bar(entry)
        return None

    def _place_remembered(self, key: str, widget: QWidget, default_bar: str) -> None:
        mem = self.memory.get(key)
        bar = self.ensure_bar(mem[0]) if mem else None
        if bar is None:
            bar = self.ensure_bar(default_bar) or (self.bars[0] if self.bars else self.add_bar())
            mem = None
        self._apply_saved(key, widget)
        if mem is None:
            bar.add_item(key, widget)
        else:
            bar.add_item(key, widget, mem[1], mem[2], mem[3] if mem[3] > 0 else None)

    def set_dynamic(self, group: str, items: list, default_bar: str) -> None:
        """Remplace les éléments d'un GROUPE refait à la demande (`items` : [(clé, widget)]) : les anciens sont retirés et
        détruits, les nouveaux reprennent la case que l'utilisateur leur avait donnée (mémoire), sinon la première case
        libre de la barre `default_bar`. Rien n'est refait pour les éléments des autres groupes."""
        for key in self.dynamic.get(group, []):
            bar = self.bar_of(key)
            placed = bar.detach_item(key) if bar is not None else None
            widget = placed.widget if placed is not None else self.widgets.get(key)
            self.widgets.pop(key, None)
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.dynamic[group] = []
        for key, widget in items:
            self.widgets[key] = widget
            self._place_remembered(key, widget, default_bar)
            self.dynamic[group].append(key)
        self.sync_visibility()

    # -- État ---------------------------------------------------------------------------------------------------------

    def state(self) -> dict:
        """Disposition à enregistrer (JSON) : barres de l'arrière vers l'avant (bord, position, grille, cases des éléments
        [colonne, ligne, largeur]), largeurs (px) et valeurs des contrôles par clé, mémoire des cases."""
        self.remember()
        bars = []
        for bar in self.bars:
            entry = bar.layout_state()
            entry.update({"id": bar.bar_id, "title": bar.title(), "dock": bar.dock, "orient": bar.orient,
                          "along": bar.want, "end": bar.end, "after": bar.after, "x": bar.fx, "y": bar.fy})
            bars.append(entry)
        for key, widget in self.widgets.items():
            if getattr(widget, "persist_value", False):
                try:
                    self.values[key] = widget.saved_value()
                except RuntimeError:
                    pass
        return {"next": self._next, "bars": bars, "widths": dict(self.widths), "values": dict(self.values),
                "memory": {k: list(v) for k, v in self.memory.items()}}

    def _make_bar(self, entry: dict) -> ToolBar | None:
        """Une barre d'après son entrée d'état (`after` : collée derrière la barre de cet identifiant le long du même bord ;
        `end` : collée à la fin du bord)."""
        try:
            dock = entry.get("dock")
            bar = self.add_bar(str(entry.get("title") or ""), int(entry.get("cols", 3)), int(entry.get("rows", 1)), dock,
                               str(entry.get("orient") or "h"), int(entry.get("x", 0)), int(entry.get("y", 0)),
                               str(entry.get("id") or "") or None, int(entry.get("along", 0)))
        except (TypeError, ValueError):
            return None
        bar.end = bool(entry.get("end", False))
        bar.after = str(entry.get("after") or "") if dock in DOCKS else ""
        bar.set_seps(entry.get("seps"))
        bar.set_header_off(entry.get("header_off", False))
        self.place(bar)
        return bar

    def restore(self, state: dict | None, fallback: dict | None = None) -> None:
        """Reprend une disposition : barres refaites, éléments inscrits reposés dans leur case (clés inconnues ignorées ;
        un élément de largeur 0 = toute la largeur de la grille) ; un élément inscrit qui n'est dans aucune barre va à sa
        case mémorisée, sinon dans la première barre (un outil ajouté plus tard ne se perd pas). Un état illisible ou
        vide : `fallback`, sinon la disposition par défaut. (Une liste d'éléments sans cases est posée en ordre de
        lecture.)"""
        if not isinstance(state, dict) or not isinstance(state.get("bars"), list) or not state["bars"]:
            state = fallback or self.default_state
        state = state or {}
        for bar in list(self.bars):
            self.remove_bar(bar)
        self._next = 1
        widths, values = state.get("widths"), state.get("values")
        self.widths = {k: int(v) for k, v in widths.items() if isinstance(v, (int, float))} if isinstance(widths, dict) else {}
        self.values = dict(values) if isinstance(values, dict) else {}
        raw = state.get("memory")
        self.memory = {k: [str(v[0]), int(v[1]), int(v[2]), int(v[3])] for k, v in (raw.items() if isinstance(raw, dict)
                       else ()) if isinstance(v, (list, tuple)) and len(v) == 4 and all(isinstance(n, (int, float)) for n in v[1:])}
        placed: set[str] = set()
        for entry in (e for e in state.get("bars") or [] if isinstance(e, dict)):
            bar = self._make_bar(entry)
            if bar is None:
                continue
            items = entry.get("items") or {}
            cells = items.items() if isinstance(items, dict) else ((k, None) for k in items if isinstance(k, str))
            for key, cell in cells:
                widget = self.widgets.get(key)
                if widget is None or key in placed:
                    continue
                self._apply_saved(key, widget)
                try:
                    col, row, width = (int(v) for v in cell) if cell is not None else (None, None, None)
                except (TypeError, ValueError):
                    continue
                if width is not None and width <= 0:            # toute la largeur de la grille
                    width = max(P.need_cells(widget), bar.cols - (col or 0))
                bar.add_item(key, widget, col, row, width)
                placed.add(key)
        try:
            self._next = max(self._next, int(state.get("next", 1)))
        except (TypeError, ValueError):
            pass
        for key in [k for k in self.widgets if k not in placed]:
            self._place_remembered(key, self.widgets[key], self.bars[0].bar_id if self.bars else "")
        self.remember()
        self.sync_visibility()

    def reset(self) -> None:
        """Revient à la disposition par défaut de l'hôte (la mémoire des cases, les largeurs et les valeurs sont oubliées)."""
        self.memory, self.widths, self.values = {}, {}, {}
        for widget in self.widgets.values():
            if hasattr(widget, "default_width"):
                widget.bar_width = widget.default_width
        self.restore(self.default_state)
        self.layoutChanged.emit()


class _Workspace(QWidget):
    """Espace de travail d'exemple (aperçu de l'éditeur, tests) : fond d'aperçu des réglages, cadre fin."""

    def paintEvent(self, event):
        from fm_theme.tokens import M
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(M["preview_bg"]))
        painter.setPen(QColor(M["preview_border"]))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


def sample_workspace(width: int = 258, height: int = 400, parent=None) -> QWidget:
    """Espace de travail d'exemple : « Outils » clipsée en haut, « Créer » flottante (grille de 3 × 2 cases avec une case
    libre), « Contrôleurs » clipsée en bas avec les QUATRE types de contrôleur (slider, liste déroulante, zone de saisie,
    toggle) ; `workspace.manager` donne le gestionnaire. Tout y marche comme dans l'appli : l'éditeur y montre les
    réglages de la section « Palette »."""
    workspace = _Workspace(parent)
    workspace.setFixedSize(width, height)
    manager = BarManager(workspace)
    manager.show_status = False
    workspace.manager = manager
    for kind in ("square", "triangle", "circle", "table", "pen", "image"):
        manager.register(kind, P.PaletteButton(kind, kind, P.demo_glyph(kind)))
    controls = (P.PaletteSliderBar("opacity", "Opacité", 0, 100, 80, "%"),
                P.PaletteSelectBar("blend", "Fusion", ["Normal", "Multiplier", "Écran"], "Normal"),
                P.PaletteInputBar("name", "Nom", "Calque 1", "Nom du calque"),
                P.PaletteToggleBar("grid", "Grille", True))
    for control in controls:
        control.persist_value = True
        manager.register(control.palette_key, control)
    manager.default_state = {"next": 4, "bars": [
        {"id": "b1", "title": "Outils", "dock": "top", "orient": "h", "along": 0, "x": 0, "y": 0, "cols": 3, "rows": 1,
         "items": {"square": [0, 0, 1], "triangle": [1, 0, 1], "circle": [2, 0, 1]}},
        {"id": "b2", "title": "Créer", "dock": None, "orient": "h", "along": 0, "x": 120, "y": 76, "cols": 3, "rows": 2,
         "items": {"table": [0, 0, 1], "pen": [1, 0, 1], "image": [0, 1, 1]}},
        {"id": "b3", "title": "Contrôleurs", "dock": "bottom", "orient": "h", "along": 0, "x": 0, "y": 0, "cols": 6,
         "rows": 4, "items": {"opacity": [0, 0, 6], "blend": [0, 1, 6], "name": [0, 2, 6], "grid": [0, 3, 6]}}]}
    manager.restore(manager.default_state)
    return workspace
