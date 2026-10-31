"""Aperçu du texte (Qt, peint) : ligne, paragraphe, cascade de tailles (waterfall), comparaison des masters ; édition
VISUELLE du crénage depuis la ligne de texte.

Deux moteurs :
- INSTANTANÉ (défaut) : avances + crénage lus dans le modèle à chaque peinture (aucune compilation) ; c'est lui qui
  sert au crénage interactif (Alt + flèches, Ctrl + glisser le glyphe de droite).
- FIDÈLE (HarfBuzz) : la police est compilée HORS du fil de l'interface (ufo2ft) quand le projet a changé et que
  l'aperçu est visible, puis mise en forme par HarfBuzz avec les features choisies ; les contours affichés sont
  ceux du modèle. Cache : un résultat par révision du projet (`project.revision`) ; un résultat compilé pendant
  qu'on modifiait le projet est jeté et refait.

Saisie : `/nom` insère un glyphe par son nom (« /f_i/eacute »), comme dans les éditeurs de polices."""
from __future__ import annotations

import re
import threading

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QTransform
from PySide6.QtWidgets import QWidget

from . import color as colr
from . import kerning
from .render import color_brush, color_layers

MODES = ("ligne", "paragraphe", "cascade", "masters")
WATERFALL = (12, 16, 24, 32, 48, 64, 96, 128)


def parse_text(text: str, cmap: dict, names) -> list[str]:
    """Texte -> noms de glyphes (`/nom ` ou `/nom/` = glyphe par son nom ; caractère sans glyphe : .notdef)."""
    out = []
    for token in re.finditer(r"/([A-Za-z0-9_.\-]+)\s?|(.)", text, flags=re.S):
        if token.group(1) is not None and token.group(1) in names:
            out.append(token.group(1))
        else:
            ch = token.group(2) if token.group(2) is not None else token.group(0)
            for c in ch:
                if c == "\n":
                    out.append("\n")
                else:
                    out.append(cmap.get(ord(c), ".notdef" if ".notdef" in names else None))
    return [n for n in out if n is not None]


class _Relay(QObject):
    done = Signal(int, object, object)                    # révision, octets, erreur


class PreviewWidget(QWidget):
    pairChanged = Signal(object)                          # (gauche, droite) choisie, ou None
    statusMessage = Signal(str)

    def __init__(self, project, cache, settings: dict, parent=None):
        super().__init__(parent)
        self.project = project
        self.cache = cache
        self.settings = settings
        self.text = settings.get("typo_preview_text", "Portez ce vieux whisky")
        self.size = int(settings.get("typo_preview_size", 72))
        self.mode = "ligne"
        self.master = 0
        self.use_hb = False
        self.features: dict[str, bool] = {}
        self.pair_index: int | None = None              # indice du glyphe de DROITE de la paire choisie
        self.exception = False
        self._layout_cache = None
        self._hb = {}                                     # (révision) -> Shaper
        self._hb_pending = None
        self._relay = _Relay()
        self._relay.done.connect(self._compiled)
        self._compile_timer = QTimer(self)
        self._compile_timer.setSingleShot(True)
        self._compile_timer.setInterval(350)
        self._compile_timer.timeout.connect(self._start_compile)
        self._drag = None
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(80)
        project.listeners.append(self._on_change)

    def detach(self):
        if self._on_change in self.project.listeners:
            self.project.listeners.remove(self._on_change)

    # -- réglages --

    def set_text(self, text: str):
        self.text = text
        self.pair_index = None
        self.update()

    def set_mode(self, mode: str):
        self.mode = mode if mode in MODES else "ligne"
        self.update()

    def set_size(self, size: int):
        self.size = max(6, min(int(size), 400))
        self.update()

    def set_hb(self, on: bool):
        self.use_hb = bool(on)
        if self.use_hb:
            self._compile_timer.start(0)
        self.update()

    def set_feature(self, tag: str, on: bool | None):
        if on is None:
            self.features.pop(tag, None)
        else:
            self.features[tag] = on
        self.update()

    def _on_change(self, kind, payload):
        if self.use_hb and self.isVisible():
            self._compile_timer.start()
        self.update()

    # -- mise en page --

    def glyph_names(self, master: int | None = None) -> list[str]:
        font = self.project.masters[self.master if master is None else master].font
        cmap = {c: g.name for g in font for c in g.unicodes}
        return parse_text(self.text, cmap, font)

    def layout_line(self, master: int | None = None) -> list[tuple[str, float, float]]:
        """[(nom, x en unités, y en unités)] : moteur instantané (avances + crénage), ou HarfBuzz si disponible."""
        master = self.master if master is None else master
        font = self.project.masters[master].font
        if self.use_hb and master == self.master:
            shaper = self._hb.get(self.project.revision)
            if shaper is not None:
                text = self.text
                out, x = [], 0.0
                for name, adv, xo, yo, _cl in shaper.shape(text, self.features):
                    if name in font:
                        out.append((name, x + xo, yo))
                    x += adv
                return out
        names = [n for n in self.glyph_names(master) if n != "\n"]
        index = kerning.group_index(font)
        out, x, prev = [], 0.0, None
        for name in names:
            if name not in font:
                continue
            if prev is not None:
                x += kerning.lookup(font, prev, name, index)[0]
            out.append((name, x, 0.0))
            x += font[name].width
            prev = name
        return out

    # -- dessin --

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self.settings.get("typo_canvas_bg", "#f4f4f2")))
        p.setRenderHint(QPainter.Antialiasing, True)
        fill = QColor(self.settings.get("typo_fill", "#1b1b1b"))
        muted = QColor(self.settings.get("typo_handle", "#8a8f98"))
        p.setFont(QFont(p.font().family(), 8))
        font = self.project.masters[self.master].font
        upm = font.info.unitsPerEm or 1000
        asc = font.info.ascender or upm * 0.8
        margin = 16
        if self.mode == "cascade":
            y = margin
            line = self.layout_line()
            for size in WATERFALL:
                s = size / upm
                p.setPen(muted)
                p.drawText(QPointF(4, y + asc * s), f"{size}")
                self._paint_line(p, line, margin + 24, y + asc * s, s, fill)
                y += size * 1.3
                if y > self.height():
                    break
        elif self.mode == "masters":
            y = margin
            s = self.size / upm
            for m in range(len(self.project.masters)):
                p.setPen(muted)
                p.drawText(QPointF(4, y + 10), self.project.masters[m].name)
                self._paint_line(p, self.layout_line(m), margin, y + asc * s + 12, s, fill, master=m)
                y += self.size * 1.3 + 14
        elif self.mode == "paragraphe":
            s = self.size / upm
            width = (self.width() - 2 * margin) / s
            x = 0.0
            y = margin + asc * s
            names = self.glyph_names()
            space = font["space"].width if "space" in font else upm * 0.25
            index = kerning.group_index(font)
            prev = None
            for name in names:
                if name == "\n" or x > width:
                    x, y, prev = 0.0, y + self.size * 1.25, None
                    if name == "\n":
                        continue
                if name not in font:
                    continue
                if prev is not None:
                    x += kerning.lookup(font, prev, name, index)[0]
                self._paint_glyph(p, name, margin + x * s, y, s, fill)
                x += font[name].width or space
                prev = name
                if y > self.height():
                    break
        else:
            s = self.size / upm
            line = self.layout_line()
            self._line_geometry = (margin, margin + asc * s, s)
            self._paint_line(p, line, margin, margin + asc * s, s, fill, pairs=True)
            if self.use_hb and self.project.revision not in self._hb:
                p.setPen(muted)
                p.drawText(QPointF(margin, self.height() - 6), "Compilation pour HarfBuzz…")
        p.end()

    def _paint_line(self, p, line, ox, baseline, s, fill, master=None, pairs=False):
        master = self.master if master is None else master
        font = self.project.masters[master].font
        sel = QColor(self.settings.get("typo_selection", "#e2572b"))
        for k, (name, x, y) in enumerate(line):
            if pairs and self.pair_index is not None and k in (self.pair_index - 1, self.pair_index):
                w = font[name].width * s
                color = QColor(sel)
                color.setAlpha(40)
                p.fillRect(QRectF(ox + x * s, baseline - (font.info.ascender or 800) * s, w,
                                  ((font.info.ascender or 800) - (font.info.descender or -200)) * s), color)
            self._paint_glyph(p, name, ox + x * s, baseline - y * s, s, fill, master)
            if ox + x * s > self.width():
                break
        if pairs and self.pair_index is not None and 0 < self.pair_index < len(line):
            left, right = line[self.pair_index - 1][0], line[self.pair_index][0]
            value, source = kerning.lookup(font, left, right)
            p.setPen(sel)
            where = f" ({source[0]}, {source[1]})" if source else ""
            p.drawText(QPointF(ox, self.height() - 6), f"{left} | {right} : {value:g}{where}")

    def _paint_glyph(self, p, name, x, baseline, s, fill, master=None):
        master = self.master if master is None else master
        p.save()
        p.setTransform(QTransform(s, 0, 0, -s, x, baseline), True)
        p.setPen(Qt.NoPen)
        font = self.project.masters[master].font
        layers = color_layers(font, name)
        if layers:                                          # glyphe couleur (COLR v0 / v1) : calques peints
            palette = font.lib[colr.PALETTES_KEY][0]
            for layer, paint in layers:
                if layer in font:
                    path = self.cache.path(master, layer)
                    p.setBrush(color_brush(palette, paint, path, fill))
                    p.drawPath(path)
        else:
            p.setBrush(fill)
            p.drawPath(self.cache.path(master, name))
        p.restore()

    # -- crénage interactif --

    def index_at(self, pos) -> int | None:
        if self.mode != "ligne" or not hasattr(self, "_line_geometry"):
            return None
        ox, _baseline, s = self._line_geometry
        font = self.project.masters[self.master].font
        for k, (name, x, _y) in enumerate(self.layout_line()):
            if ox + x * s <= pos.x() < ox + (x + font[name].width) * s:
                return k
        return None

    def current_pair(self):
        line = self.layout_line()
        if self.pair_index is None or not 0 < self.pair_index < len(line):
            return None
        return line[self.pair_index - 1][0], line[self.pair_index][0]

    def nudge(self, delta: float) -> None:
        """Change le crénage de la paire choisie (classe, ou exception si demandée), un pas d'annulation."""
        pair = self.current_pair()
        if pair is None:
            return
        font = self.project.masters[self.master].font
        target = kerning.target_pair(font, *pair, exception=self.exception)
        value, source = kerning.lookup(font, *pair)
        base = font.kerning.get(target, value if source == target else value)
        new = base + delta
        kerning.set_value(self.project, self.master, target, new if new else (0 if self.exception else None),
                          "Crénage")
        self.pairChanged.emit(pair)

    def mousePressEvent(self, event):
        self.setFocus()
        index = self.index_at(event.position())
        if index is None:
            return
        self.pair_index = index if index > 0 else None
        self.pairChanged.emit(self.current_pair())
        if event.modifiers() & Qt.ControlModifier and self.pair_index is not None:
            pair = self.current_pair()
            font = self.project.masters[self.master].font
            target = kerning.target_pair(font, *pair, exception=self.exception)
            # (x du clic, valeur effective, paire écrite, valeur d'avant dans le crénage — None : absente)
            self._drag = (event.position().x(), kerning.lookup(font, *pair)[0], target, font.kerning.get(target))
        self.update()

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        x0, value, target, _before = self._drag
        _ox, _b, s = self._line_geometry
        new = round(value + (event.position().x() - x0) / s)
        font = self.project.masters[self.master].font
        font.kerning[target] = new                       # en direct, l'étape d'annulation au relâché
        self.update()

    def mouseReleaseEvent(self, event):
        if self._drag is None:
            return
        _x0, value, target, before = self._drag
        self._drag = None
        font = self.project.masters[self.master].font
        new = font.kerning.get(target)
        if before is None:                               # remet l'avant, puis l'étape normale (annulable)
            font.kerning.pop(target, None)
        else:
            font.kerning[target] = before
        if new is not None and new != before:
            kerning.set_value(self.project, self.master, target, new, "Crénage")
        self.pairChanged.emit(self.current_pair())

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Left, Qt.Key_Right) and event.modifiers() & Qt.AltModifier and self.pair_index:
            step = 1 if event.modifiers() & Qt.ShiftModifier else 10
            self.nudge(step if key == Qt.Key_Right else -step)
            return
        if key in (Qt.Key_Left, Qt.Key_Right) and self.pair_index is not None:
            n = len(self.layout_line())
            self.pair_index = max(1, min(n - 1, self.pair_index + (1 if key == Qt.Key_Right else -1)))
            self.pairChanged.emit(self.current_pair())
            self.update()
            return
        super().keyPressEvent(event)

    # -- compilation de fond (HarfBuzz) --

    def _start_compile(self):
        revision = self.project.revision
        if revision in self._hb or self._hb_pending == revision:
            return
        self._hb_pending = revision
        # Instantané (quelques ms) : le fil compile une copie INDÉPENDANTE, jamais le modèle que l'on édite.
        from .autosave import _build, snapshot
        master = snapshot(self.project)["masters"][self.master]
        relay = self._relay

        def work():
            try:
                import ufo2ft
                from .compile import to_bytes
                tt = ufo2ft.compileTTF(_build(master), useProductionNames=False, removeOverlaps=False)
                relay.done.emit(revision, to_bytes(tt), None)
            except Exception as exc:                       # noqa: BLE001 - montré dans la barre d'état
                relay.done.emit(revision, None, f"{type(exc).__name__} : {exc}")
        threading.Thread(target=work, name="fm_font aperçu", daemon=True).start()

    def _compiled(self, revision, data, error):
        self._hb_pending = None
        if error is not None:
            self.statusMessage.emit(f"Aperçu HarfBuzz : {error}")
            return
        if revision != self.project.revision:              # modifié pendant la compilation : refaire
            self._compile_timer.start()
            return
        from .shaping import Shaper
        self._hb = {revision: Shaper(data)}
        self.update()
