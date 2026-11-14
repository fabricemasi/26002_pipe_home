"""Mode CONCEPTION de formulaires AcroForm (Qt) : surcouche de la vue + panneau des propriétés.

Distinct du mode Remplissage : ici les champs ne réagissent PAS comme des champs (PDFium ne reçoit rien), on les
place, dimensionne, nomme, configure. Retour au Remplissage = les mêmes champs deviennent interactifs (test
immédiat). Chaque changement validé (relâchement de la souris, propriété saisie) = UNE édition annulable
(`PdfSession.edit`, acroform.py) ; pendant le geste, seul l'aperçu de la surcouche bouge (aucun aller-retour).

Coordonnées des champs : points de la page affichée (moteur, origine en haut à gauche) ; la vue les convertit.
"""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal, QObject
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from . import acroform as af
from . import ui_kit
from .worker import PRIO_INPUT, PRIO_VISIBLE

HANDLE = 6.0                     # demi-côté des poignées (pixels écran)
DEFAULT_SIZES = {"text": (160, 20), "multiline": (240, 60), "number": (90, 20), "date": (100, 20),
                 "checkbox": (14, 14), "radio": (14, 14), "combo": (160, 20), "list": (160, 60),
                 "button": (90, 24), "signature": (180, 50)}
KIND_COLORS = {"text": QColor(66, 133, 244), "multiline": QColor(66, 133, 244), "number": QColor(52, 168, 83),
               "date": QColor(52, 168, 83), "checkbox": QColor(251, 140, 0), "radio": QColor(251, 140, 0),
               "combo": QColor(171, 71, 188), "list": QColor(171, 71, 188), "button": QColor(120, 120, 120),
               "signature": QColor(220, 60, 60)}


class DesignOverlay(QObject):
    selectionChanged = Signal(list)          # specs sélectionnés
    status = Signal(str)

    def __init__(self, controller):
        super().__init__()
        self.ctl = controller
        self.place_kind = None               # type à placer (bouton de la palette), None = sélection
        self.selected: list[int] = []        # xrefs
        self._drag = None
        self.tab_mode = False
        self._tab_sequence: list[int] = []

    # -- dessin --

    def paint(self, painter, view):
        specs = self.ctl.specs
        font = QFont(painter.font())
        font.setPointSizeF(8)
        painter.setFont(font)
        order = self.ctl.tab_numbers
        for spec in specs:
            if spec.page not in view._visible_indexes():
                continue
            rect = self._view_rect(view, spec)
            if self._drag and spec.xref in self.selected and self._drag.get("moved"):
                rect = self._dragged(view, spec, rect)
            color = KIND_COLORS.get(spec.kind, QColor(66, 133, 244))
            fill = QColor(color)
            fill.setAlpha(40)
            painter.fillRect(rect, fill)
            pen = QPen(color, 2 if spec.xref in self.selected else 1)
            painter.setPen(pen)
            painter.drawRect(rect)
            painter.setPen(QColor(30, 30, 30))
            if rect.height() >= 12 and rect.width() > 30:
                painter.drawText(rect.adjusted(3, 0, -2, 0), Qt.AlignVCenter | Qt.AlignLeft,
                                 ("* " if spec.required else "") + spec.name)
            if self.tab_mode:
                n = order.get(spec.xref)
                badge = QRectF(rect.left() - 9, rect.top() - 9, 18, 18)
                painter.setBrush(QColor(255, 140, 0) if spec.xref in self._tab_sequence else QColor(90, 90, 90))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(badge)
                painter.setPen(Qt.white)
                painter.drawText(badge, Qt.AlignCenter, str(n) if n else "?")
                painter.setBrush(Qt.NoBrush)
            if spec.xref in self.selected and len(self.selected) == 1 and not self.tab_mode:
                painter.setPen(QPen(color, 1))
                painter.setBrush(Qt.white)
                for h in self._handles(rect).values():
                    painter.drawRect(h)
                painter.setBrush(Qt.NoBrush)
        if self._drag and self._drag.get("kind") == "create" and self._drag.get("rect") is not None:
            painter.setPen(QPen(QColor(255, 140, 0), 1, Qt.DashLine))
            painter.drawRect(self._drag["rect"])

    def _view_rect(self, view, spec) -> QRectF:
        return view.engine_rect_to_view(spec.page, spec.rect)

    @staticmethod
    def _handles(rect: QRectF) -> dict:
        x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
        cx, cy = rect.center().x(), rect.center().y()
        pts = {"nw": (x0, y0), "n": (cx, y0), "ne": (x1, y0), "e": (x1, cy), "se": (x1, y1), "s": (cx, y1),
               "sw": (x0, y1), "w": (x0, cy)}
        return {k: QRectF(x - HANDLE / 2 - 1, y - HANDLE / 2 - 1, HANDLE + 2, HANDLE + 2) for k, (x, y) in pts.items()}

    def _dragged(self, view, spec, rect: QRectF) -> QRectF:
        d = self._drag
        dx, dy = d["dx"], d["dy"]
        if d["kind"] == "move":
            return rect.translated(dx, dy)
        h = d["handle"]
        r = QRectF(rect)
        if "w" in h:
            r.setLeft(min(r.right() - 4, r.left() + dx))
        if "e" in h:
            r.setRight(max(r.left() + 4, r.right() + dx))
        if "n" in h:
            r.setTop(min(r.bottom() - 4, r.top() + dy))
        if "s" in h:
            r.setBottom(max(r.top() + 4, r.bottom() + dy))
        return r

    # -- souris --

    def _spec_at(self, view, pos):
        for spec in reversed(self.ctl.specs):
            if spec.page in view._visible_indexes() and self._view_rect(view, spec).contains(pos):
                return spec
        return None

    def press(self, view, event, hit):
        if event.button() != Qt.LeftButton:
            if event.button() == Qt.RightButton and hit is not None:
                spec = self._spec_at(view, event.position())
                if spec is not None and spec.xref not in self.selected:
                    self.select([spec.xref])
                self.ctl.context_menu(event.globalPosition().toPoint(), hit)
                return True
            return False
        pos = event.position()
        if self.tab_mode:
            spec = self._spec_at(view, pos)
            if spec is not None:
                self.ctl.tab_click(spec)
            return True
        if self.place_kind and hit is not None:
            self._drag = {"kind": "create", "start": pos, "page": hit[0], "rect": None}
            return True
        if len(self.selected) == 1:
            spec = self.ctl.spec(self.selected[0])
            if spec is not None:
                for name, h in self._handles(self._view_rect(view, spec)).items():
                    if h.adjusted(-2, -2, 2, 2).contains(pos):
                        self._drag = {"kind": "resize", "handle": name, "start": pos, "dx": 0.0, "dy": 0.0,
                                      "moved": False}
                        return True
        spec = self._spec_at(view, pos)
        if spec is None:
            if not event.modifiers() & Qt.ShiftModifier:
                self.select([])
            return True
        if event.modifiers() & Qt.ShiftModifier:
            sel = list(self.selected)
            sel.remove(spec.xref) if spec.xref in sel else sel.append(spec.xref)
            self.select(sel)
        elif spec.xref not in self.selected:
            self.select([spec.xref])
        self._drag = {"kind": "move", "start": pos, "dx": 0.0, "dy": 0.0, "moved": False}
        return True

    def move(self, view, event, hit):
        pos = event.position()
        d = self._drag
        if d is None:
            spec = self._spec_at(view, pos)
            cursor = Qt.CrossCursor if self.place_kind else (Qt.SizeAllCursor if spec else Qt.ArrowCursor)
            if len(self.selected) == 1 and not self.place_kind:
                s = self.ctl.spec(self.selected[0])
                if s is not None:
                    for name, h in self._handles(self._view_rect(view, s)).items():
                        if h.adjusted(-2, -2, 2, 2).contains(pos):
                            cursor = Qt.SizeFDiagCursor if name in ("nw", "se") else Qt.SizeBDiagCursor \
                                if name in ("ne", "sw") else Qt.SizeHorCursor if name in ("e", "w") else Qt.SizeVerCursor
            view.viewport().setCursor(cursor)
            if hit is not None:
                self.status.emit("x %.1f  y %.1f pt" % (hit[1], hit[2]))
            return True
        if d["kind"] == "create":
            d["rect"] = QRectF(d["start"], pos).normalized()
        else:
            dx, dy = pos.x() - d["start"].x(), pos.y() - d["start"].y()
            if event.modifiers() & Qt.ShiftModifier and d["kind"] == "move":     # contraint à un axe
                dx, dy = (dx, 0.0) if abs(dx) >= abs(dy) else (0.0, dy)
            d["dx"], d["dy"] = dx, dy
            d["moved"] = d["moved"] or abs(dx) + abs(dy) > 2
            if d["moved"]:
                self.status.emit("Δ %.1f, %.1f pt" % (dx / view.zoom, dy / view.zoom))
        view.viewport().update()
        return True

    def release(self, view, event, hit):
        d, self._drag = self._drag, None
        if d is None:
            return True
        if d["kind"] == "create":
            rect = d.get("rect")
            page = d["page"]
            pr = view.page_rect(page)
            if rect is None or rect.width() < 4 or rect.height() < 4:
                w, h = DEFAULT_SIZES.get(self.place_kind, (120, 20))
                x, y = (d["start"].x() - pr.left()) / view.zoom, (d["start"].y() - pr.top()) / view.zoom
                box = (x, y, x + w, y + h)
            else:
                box = ((rect.left() - pr.left()) / view.zoom, (rect.top() - pr.top()) / view.zoom,
                       (rect.right() - pr.left()) / view.zoom, (rect.bottom() - pr.top()) / view.zoom)
            a = view.to_engine(page, box[0], box[1])
            b = view.to_engine(page, box[2], box[3])
            box = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
            self.ctl.create(self.place_kind, page, box)
            if not event.modifiers() & Qt.ShiftModifier:        # Maj : garder l'outil pour en placer d'autres
                self.ctl.set_place_kind(None)
        elif d.get("moved"):
            zoom = view.zoom
            changes = []
            for xref in self.selected:
                spec = self.ctl.spec(xref)
                if spec is None:
                    continue
                vr = self._view_rect(view, spec)
                nr = self._dragged(view, spec, vr)
                pr = view.page_rect(spec.page)
                a = view.to_engine(spec.page, (nr.left() - pr.left()) / zoom, (nr.top() - pr.top()) / zoom)
                b = view.to_engine(spec.page, (nr.right() - pr.left()) / zoom, (nr.bottom() - pr.top()) / zoom)
                changes.append(replace(spec, rect=(round(min(a[0], b[0]), 2), round(min(a[1], b[1]), 2),
                                                   round(max(a[0], b[0]), 2), round(max(a[1], b[1]), 2))))
            self.ctl.update_many(changes, "Déplacer" if d["kind"] == "move" else "Redimensionner")
        view.viewport().update()
        return True

    def double(self, view, event, hit):
        spec = self._spec_at(view, event.position())
        if spec is not None:
            self.ctl.focus_properties()
        return True

    def key(self, view, event):
        key = event.key()
        if key == Qt.Key_Escape:
            if self._drag:
                self._drag = None
            elif self.place_kind:
                self.ctl.set_place_kind(None)
            elif self.tab_mode:
                self.ctl.set_tab_mode(False)
            else:
                self.select([])
            view.viewport().update()
            return True
        if not self.selected:
            return False
        step = 10.0 if event.modifiers() & Qt.ShiftModifier else 1.0
        moves = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0), Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}
        if key in moves:
            dx, dy = moves[key]
            if event.modifiers() & Qt.AltModifier:                  # Alt + flèches : taille
                self.ctl.nudge(0, 0, dx, dy)
            else:
                self.ctl.nudge(dx, dy, dx, dy)
            return True
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.ctl.delete_selected()
            return True
        if key == Qt.Key_D and event.modifiers() & Qt.ControlModifier:
            self.ctl.duplicate_selected()
            return True
        if key == Qt.Key_A and event.modifiers() & Qt.ControlModifier:
            self.select([s.xref for s in self.ctl.specs if s.page == view.current])
            return True
        return False

    def select(self, xrefs) -> None:
        self.selected = [x for x in xrefs if self.ctl.spec(x) is not None]
        self.selectionChanged.emit([self.ctl.spec(x) for x in self.selected])
        self.ctl.view.viewport().update()


class DesignController(QObject):
    """État du mode Conception d'UN document : champs lus, sélection, éditions."""
    changed = Signal()

    def __init__(self, pane):
        super().__init__()
        self.pane = pane
        self.session = pane.session
        self.view = pane.view
        self.specs: list[af.FieldSpec] = []
        self.tab_numbers: dict[int, int] = {}
        self.overlay = DesignOverlay(self)
        self.overlay.status.connect(pane.status)
        self.panel = PropertiesPanel(self)
        self.overlay.selectionChanged.connect(self.panel.show_specs)
        self.active = False
        self._after_reload = None
        self.session.reloaded.connect(lambda _info: self.refresh())
        self.session.opened.connect(lambda _info: self.refresh())

    # -- état --

    def spec(self, xref):
        return next((s for s in self.specs if s.xref == xref), None)

    def refresh(self, then=None) -> None:
        if not self.active:
            return

        def job(doc):
            specs = af.read_fields(doc.data)
            orders = {}
            for page in sorted({s.page for s in specs}):
                for n, xref in enumerate(af.tab_order(doc.data, page), 1):
                    orders[xref] = n
            return specs, orders

        def done(result, error):
            if error is not None:
                self.pane.status("Lecture des champs impossible : %s" % error)
                return
            self.specs, self.tab_numbers = result
            self.overlay.select([x for x in self.overlay.selected if self.spec(x) is not None])
            callback = then or self._after_reload
            self._after_reload = None
            if callback:
                callback()
            self.view.viewport().update()
            self.changed.emit()
        self.session.run(job, PRIO_VISIBLE, done)

    def set_active(self, on: bool) -> None:
        self.active = on
        if on:
            self.view._kill_form_focus() if self.view.form_focus else None
            self.view.set_overlay(self.overlay)
            self.refresh()
        else:
            self.overlay.select([])
            self.set_place_kind(None)
            self.set_tab_mode(False)
            if self.view.overlay is self.overlay:
                self.view.set_overlay(None)

    def set_place_kind(self, kind) -> None:
        self.overlay.place_kind = kind
        self.pane.sync_design_tools(kind)
        if kind:
            self.pane.status("Glisser un rectangle sur la page (clic : taille par défaut, Maj : garder l'outil)")

    def set_tab_mode(self, on: bool) -> None:
        self.overlay.tab_mode = on
        self.overlay._tab_sequence = []
        self.pane.sync_tab_button(on)
        if on:
            self.pane.status("Ordre de tabulation : cliquez les champs dans l'ordre voulu (Échap : terminer)")
        self.view.viewport().update()

    # -- éditions --

    def _edit(self, label, fn, select=None) -> None:
        def done(extra, error):
            if error is None:
                created = extra if isinstance(extra, list) else None
                self.refresh(then=lambda: self.overlay.select(created if created else (select or [])))
        self.session.edit(label, fn, done)

    def create(self, kind, page, rect) -> None:
        names = {s.name for s in self.specs}
        base = {"text": "Texte", "multiline": "Notes", "number": "Nombre", "date": "Date", "checkbox": "Case",
                "radio": "Choix", "combo": "Liste", "list": "ListeMultiple", "button": "Bouton",
                "signature": "Signature"}[kind]
        name = af.unique_name(names, base)
        spec = af.FieldSpec(kind=kind, name=name, page=page, rect=tuple(round(v, 2) for v in rect))
        s = self.pane.settings
        spec.font_size = float(s.get("pdf_design_font_size", 0))
        if kind == "radio":
            spec.export_value = "Choix1"
        if kind in ("combo", "list"):
            spec.choices = ["Option 1", "Option 2", "Option 3"]
        if kind == "button":
            spec.caption = "Bouton"
        self._edit("Ajouter le champ « %s »" % name, lambda data: af.add_fields(data, [spec]))

    def update_many(self, specs, label="Modifier") -> None:
        if not specs:
            return
        xrefs = [s.xref for s in specs]

        def fn(data):
            for spec in specs:
                data = af.update_field(data, spec.xref, spec)
            return data
        self._edit("%s %d champ(s)" % (label, len(specs)), fn, select=xrefs)

    def update_spec(self, spec, label="Modifier le champ") -> None:
        self.update_many([spec], label)

    def nudge(self, dx0, dy0, dx1, dy1) -> None:
        changes = []
        for xref in self.overlay.selected:
            s = self.spec(xref)
            if s is not None:
                x0, y0, x1, y1 = s.rect
                changes.append(replace(s, rect=(x0 + dx0, y0 + dy0, max(x0 + dx0 + 2, x1 + dx1),
                                                max(y0 + dy0 + 2, y1 + dy1))))
        self.update_many(changes, "Ajuster")

    def delete_selected(self) -> None:
        xrefs = list(self.overlay.selected)
        if xrefs:
            self._edit("Supprimer %d champ(s)" % len(xrefs), lambda data: af.delete_fields(data, xrefs))

    def duplicate_selected(self) -> None:
        specs = [self.spec(x) for x in self.overlay.selected if self.spec(x) is not None]
        if not specs:
            return
        names = {s.name for s in self.specs}
        copies = []
        for s in specs:
            name = s.name if s.kind == "radio" else af.unique_name(names, s.name)
            names.add(name)
            x0, y0, x1, y1 = s.rect
            dy = (y1 - y0) + 6
            c = replace(s, name=name, xref=0, rect=(x0, y0 + dy, x1, y1 + dy))
            if s.kind == "radio":
                c.export_value = af.unique_name({x.export_value for x in self.specs if x.name == s.name},
                                                s.export_value)
                c.checked = False
            copies.append(c)
        self._edit("Dupliquer %d champ(s)" % len(copies), lambda data: af.add_fields(data, copies))

    def align(self, how: str) -> None:
        specs = [self.spec(x) for x in self.overlay.selected if self.spec(x) is not None]
        if len(specs) < 2:
            self.pane.status("Choisir au moins deux champs (Maj + clic)")
            return
        ref = specs[0]
        x0, y0, x1, y1 = ref.rect
        out = []
        if how in ("dist_h", "dist_v"):
            axis = 0 if how == "dist_h" else 1
            specs.sort(key=lambda s: s.rect[axis])
            if len(specs) < 3:
                self.pane.status("Distribuer : au moins trois champs")
                return
            first, last = specs[0].rect[axis], specs[-1].rect[axis]
            step = (last - first) / (len(specs) - 1)
            for k, s in enumerate(specs[1:-1], 1):
                r = list(s.rect)
                size = r[axis + 2] - r[axis]
                r[axis] = first + step * k
                r[axis + 2] = r[axis] + size
                out.append(replace(s, rect=tuple(r)))
        else:
            for s in specs[1:]:
                a0, b0, a1, b1 = s.rect
                w, h = a1 - a0, b1 - b0
                if how == "left":
                    a0 = x0
                elif how == "right":
                    a0 = x1 - w
                elif how == "top":
                    b0 = y0
                elif how == "bottom":
                    b0 = y1 - h
                elif how == "hcenter":
                    a0 = (x0 + x1) / 2 - w / 2
                elif how == "vcenter":
                    b0 = (y0 + y1) / 2 - h / 2
                elif how == "same_size":
                    w, h = x1 - x0, y1 - y0
                elif how == "same_width":
                    w = x1 - x0
                elif how == "same_height":
                    h = y1 - y0
                out.append(replace(s, rect=(a0, b0, a0 + w, b0 + h)))
        self.update_many(out, "Aligner")

    def tab_click(self, spec) -> None:
        seq = self.overlay._tab_sequence
        if spec.xref in seq:
            return
        seq.append(spec.xref)
        page = spec.page
        page_seq = [x for x in seq if self.spec(x) is not None and self.spec(x).page == page]
        self.tab_numbers.update({x: n for n, x in enumerate(page_seq, 1)})
        self.view.viewport().update()
        self._edit("Ordre de tabulation", lambda data: af.set_tab_order(data, page, page_seq),
                   select=[spec.xref])

    def context_menu(self, global_pos, hit) -> None:
        m = ui_kit.menu(self.pane)
        has = bool(self.overlay.selected)
        for text, slot, enabled in (("Propriétés…", self.focus_properties, has),
                                    ("Dupliquer (Ctrl+D)", self.duplicate_selected, has),
                                    ("Supprimer (Suppr)", self.delete_selected, has)):
            a = m.addAction(text)
            if slot == self.delete_selected:
                from fm_theme import icon_library
                style = icon_library.style_affiche()
                a.setIcon(icon_library.icone_cadree("general/supprimer_02", 16, self.view.devicePixelRatioF(), style=style,
                                                    teinte=None if style == icon_library.COULEUR else icon_library.encre_defaut()))
            a.setEnabled(enabled)
            a.triggered.connect(slot)
        m.addSeparator()
        for how, text in (("left", "Aligner à gauche"), ("right", "Aligner à droite"), ("top", "Aligner en haut"),
                          ("bottom", "Aligner en bas"), ("hcenter", "Centrer horizontalement"),
                          ("vcenter", "Centrer verticalement"), ("dist_h", "Distribuer horizontalement"),
                          ("dist_v", "Distribuer verticalement"), ("same_size", "Même taille"),
                          ("same_width", "Même largeur"), ("same_height", "Même hauteur")):
            a = m.addAction(text)
            a.setEnabled(len(self.overlay.selected) > 1)
            a.triggered.connect(lambda _c=False, h=how: self.align(h))
        m.exec(global_pos)

    def focus_properties(self) -> None:
        self.pane.show_properties()


class PropertiesPanel(QWidget):
    """Propriétés du champ choisi (tableau des réglages, valeurs posées sur place ; validation = une édition)."""

    ROWS = [("name", "Nom"), ("kind", "Type"), ("tooltip", "Info-bulle"), ("page", "Page"), ("x", "X (pt)"),
            ("y", "Y (pt)"), ("w", "Largeur (pt)"), ("h", "Hauteur (pt)"), ("required", "Obligatoire (oui / non)"),
            ("readonly", "Lecture seule (oui / non)"), ("value", "Valeur"), ("default", "Valeur par défaut"),
            ("font", "Police (Helvetica, Times, Courier)"), ("font_size", "Taille (0 = auto)"),
            ("text_color", "Couleur du texte (#rrvvbb)"), ("fill_color", "Fond (#rrvvbb ou vide)"),
            ("border_color", "Bordure (#rrvvbb ou vide)"), ("border_width", "Épaisseur de bordure"),
            ("border_style", "Style (solid, dashed, beveled, inset, underline)"),
            ("align", "Alignement (left, center, right)"), ("max_length", "Longueur max (0 = libre)"),
            ("choices", "Choix (séparés par « ; »)"), ("editable", "Liste modifiable (oui / non)"),
            ("multiselect", "Choix multiples (oui / non)"), ("export_value", "Valeur d'export (case, radio)"),
            ("decimals", "Décimales (nombre)"), ("currency", "Devise (nombre)"),
            ("date_format", "Format de date (dd/mm/yyyy…)"), ("min_value", "Minimum (validation)"),
            ("max_value", "Maximum (validation)"), ("calc", "Calcul (SUM / PRD / AVG / MIN / MAX : champs)"),
            ("calc_script", "Calcul personnalisé (JavaScript)"), ("validate_script", "Validation (JavaScript)"),
            ("caption", "Libellé (bouton)"), ("action_script", "Action au clic (JavaScript)")]

    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.specs: list = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.head = ui_kit.title("Propriétés du champ")
        lay.addWidget(self.head)
        self.hint = ui_kit.label("Choisissez un champ (clic), ou un type dans la barre « Champs » puis glissez un "
                                 "rectangle sur la page.", "value_muted")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        rows = [(k, text, k not in ("kind", "page"), (lambda v, k=k: self._commit(k, v))) for k, text in self.ROWS]
        self.table = ui_kit.Table("Propriété", rows, 150)
        lay.addWidget(self.table.frame)
        lay.addStretch(1)
        self.show_specs([])

    def show_specs(self, specs) -> None:
        self.specs = [s for s in specs if s is not None]
        one = self.specs[0] if len(self.specs) == 1 else None
        self.table.frame.setVisible(one is not None)
        self.hint.setVisible(one is None)
        if len(self.specs) > 1:
            self.hint.setText("%d champs choisis : clic droit pour aligner, distribuer, uniformiser." % len(self.specs))
        elif not self.specs:
            self.hint.setText("Choisissez un champ (clic), ou un type dans la barre « Champs » puis glissez un "
                              "rectangle sur la page.")
        if one is None:
            return
        s = one
        t = self.table
        x0, y0, x1, y1 = s.rect
        yes = lambda b: "oui" if b else "non"
        values = {"name": s.name, "kind": af.KIND_LABELS.get(s.kind, s.kind), "tooltip": s.tooltip,
                  "page": s.page + 1, "x": round(x0, 2), "y": round(y0, 2), "w": round(x1 - x0, 2),
                  "h": round(y1 - y0, 2), "required": yes(s.required), "readonly": yes(s.readonly),
                  "value": "oui" if s.kind in ("checkbox", "radio") and s.checked else (s.value if s.kind not in
                                                                                       ("checkbox", "radio") else "non"),
                  "default": s.default, "font": s.font, "font_size": s.font_size,
                  "text_color": _hex(s.text_color), "fill_color": _hex(s.fill_color),
                  "border_color": _hex(s.border_color), "border_width": s.border_width,
                  "border_style": s.border_style, "align": s.align, "max_length": s.max_length,
                  "choices": "; ".join(c if isinstance(c, str) else str(c[1]) for c in s.choices),
                  "editable": yes(s.editable), "multiselect": yes(s.multiselect), "export_value": s.export_value,
                  "decimals": s.decimals, "currency": s.currency, "date_format": s.date_format,
                  "min_value": "" if s.min_value is None else s.min_value,
                  "max_value": "" if s.max_value is None else s.max_value,
                  "calc": ("%s : %s" % (s.calc_op, ", ".join(s.calc_fields))) if s.calc_op else "",
                  "calc_script": s.calc_script, "validate_script": s.validate_script, "caption": s.caption,
                  "action_script": s.action_script}
        for key, value in values.items():
            t.set(key, value)
        relevant = {
            "value": s.kind not in ("button", "signature"), "default": s.kind in ("text", "multiline", "number",
                                                                                 "date", "combo", "list"),
            "font": s.kind not in ("checkbox", "radio", "signature"), "align": s.kind in ("text", "multiline",
                                                                                          "number", "date", "combo"),
            "max_length": s.kind in ("text", "multiline"), "choices": s.kind in ("combo", "list"),
            "editable": s.kind == "combo", "multiselect": s.kind == "list",
            "export_value": s.kind in ("checkbox", "radio"), "decimals": s.kind == "number",
            "currency": s.kind == "number", "date_format": s.kind == "date",
            "min_value": s.kind == "number", "max_value": s.kind == "number",
            "calc": s.kind in ("number", "text"), "calc_script": s.kind in ("number", "text"),
            "validate_script": s.kind in ("text", "number", "date"), "caption": s.kind == "button",
            "action_script": s.kind == "button"}
        for key, on in relevant.items():
            t.enable(key, on)

    def _commit(self, key, value) -> None:
        if len(self.specs) != 1:
            return
        s = self.specs[0]
        try:
            new = _apply_property(s, key, value)
        except ValueError as exc:
            self.ctl.pane.status("Valeur refusée : %s" % exc)
            self.show_specs(self.specs)
            return
        if new != s:
            self.ctl.update_spec(new, "Propriété « %s »" % dict(self.ROWS).get(key, key))


def _hex(color) -> str:
    if not color:
        return ""
    return "#%02x%02x%02x" % tuple(int(round(c * 255)) for c in color[:3])


def _color(text: str):
    text = text.strip()
    if not text:
        return None
    if not text.startswith("#") or len(text) != 7:
        raise ValueError("couleur attendue au format #rrvvbb")
    return tuple(int(text[k:k + 2], 16) / 255 for k in (1, 3, 5))


def _yes(text: str) -> bool:
    return text.strip().lower() in ("oui", "o", "yes", "y", "1", "vrai", "true", "x")


def _num(text: str) -> float:
    return float(text.replace(",", ".").strip())


def _apply_property(s, key, value):
    x0, y0, x1, y1 = s.rect
    v = value
    if key == "name":
        return replace(s, name=v.strip())
    if key == "tooltip":
        return replace(s, tooltip=v)
    if key in ("x", "y", "w", "h"):
        n = _num(v)
        if key == "x":
            return replace(s, rect=(n, y0, n + (x1 - x0), y1))
        if key == "y":
            return replace(s, rect=(x0, n, x1, n + (y1 - y0)))
        if n < 2:
            raise ValueError("taille trop petite")
        return replace(s, rect=(x0, y0, x0 + n, y1)) if key == "w" else replace(s, rect=(x0, y0, x1, y0 + n))
    if key in ("required", "readonly", "editable", "multiselect"):
        return replace(s, **{key: _yes(v)})
    if key == "value":
        if s.kind in ("checkbox", "radio"):
            return replace(s, checked=_yes(v))
        return replace(s, value=v)
    if key in ("default", "currency", "date_format", "calc_script", "validate_script", "caption", "action_script",
               "export_value"):
        if key == "date_format" and v and not any(t in v for t in ("d", "m", "y")):
            raise ValueError("format de date sans jour / mois / année")
        return replace(s, **{key: v})
    if key == "font":
        name = next((f for f in af.FONTS if f.lower() == v.strip().lower()), None)
        if name is None:
            raise ValueError("polices : " + ", ".join(af.FONTS))
        return replace(s, font=name)
    if key in ("font_size", "border_width"):
        return replace(s, **{key: max(0.0, _num(v))})
    if key in ("max_length", "decimals"):
        return replace(s, **{key: max(0, int(_num(v)))})
    if key in ("text_color", "fill_color", "border_color"):
        c = _color(v)
        if key == "text_color" and c is None:
            c = (0.0, 0.0, 0.0)
        return replace(s, **{key: c})
    if key == "border_style":
        if v.strip() not in af.BORDER_STYLES:
            raise ValueError(", ".join(af.BORDER_STYLES))
        return replace(s, border_style=v.strip())
    if key == "align":
        if v.strip() not in af.ALIGN:
            raise ValueError("left, center, right")
        return replace(s, align=v.strip())
    if key == "choices":
        return replace(s, choices=[c.strip() for c in v.split(";") if c.strip()])
    if key in ("min_value", "max_value"):
        return replace(s, **{key: None if not v.strip() else _num(v)})
    if key == "calc":
        if not v.strip():
            return replace(s, calc_op="", calc_fields=[])
        op, _, names = v.partition(":")
        op = op.strip().upper()
        if op not in af.CALC_OPS:
            raise ValueError("opérations : " + ", ".join(af.CALC_OPS))
        return replace(s, calc_op=op, calc_fields=[n.strip() for n in names.split(",") if n.strip()])
    return s
