"""Panneaux du module (Qt), construits AVEC les briques des réglages (tableaux `build_cells_table`, zones de saisie
`_TextField`, libellés par rôle de texte, toggles) : glyphe (nom, Unicode, chasse, approches, coordonnées du point
choisi), famille (métriques verticales), crénage du glyphe, features, diagnostic, masters.

Chaque tableau est construit UNE fois ; ensuite seules les valeurs sont posées (`updaters`), comme le panneau des
propriétés du CAD (refaire un tableau coûte ~70 ms, poser une valeur ~0,05 ms)."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from . import axes as axes_model
from . import color, features, geometry, interpolation, kerning, metrics, validation
from .document import ProjectError


def _label(text: str, role: str = "row_label") -> QLabel:
    from fm_theme.theme import _text_label
    return _text_label(text, role)


def _title(text: str) -> QLabel:
    from fm_theme.theme import _text_label
    return _text_label(text, "card_title")


def button(text: str, tip: str, slot, parent=None) -> QPushButton:
    """Bouton d'action : aspect = fm_theme seul (`theme_button`, 2026-11-12)."""
    from fm_theme.style import theme_button
    b = theme_button(QPushButton(text, parent))
    b.setToolTip(tip)
    b.setCursor(Qt.ArrowCursor)
    b.setFixedHeight(26)
    b.setMinimumWidth(b.sizeHint().width())
    if slot is not None:
        b.clicked.connect(lambda _c=False: slot())
    return b


def _num(text: str) -> float:
    return float(text.replace(",", ".").strip())


def _fmt(value) -> str:
    if value is None:
        return ""
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


class _Table:
    """Tableau « libellé | valeur » des briques des réglages, valeurs posées sur place."""

    def __init__(self, title_left: str, rows, width: int = 150):
        from fm_theme.cells import _TextField, build_cells_table
        self.fields: dict[str, QWidget] = {}
        self.commits: dict[str, callable] = {}
        cells = []
        for key, label, editable, commit in rows:
            if editable:
                field = _TextField("", width)
                field._start = ""
                field.editingFinished.connect(lambda k=key: self._commit(k))
            else:
                field = _label("", "value")
            self.fields[key] = field
            self.commits[key] = commit
            cells.append([(_label(label), "left", "center"), (field, "left", "center")])
        self.frame, self.head, self.cells = build_cells_table([(title_left, 130), ("Valeur", 0)], cells)

    def _commit(self, key):
        field = self.fields[key]
        if field.text() == field._start:
            return
        value, field._start = field.text(), field.text()
        QTimer.singleShot(0, lambda: self.commits[key](value))

    def set(self, key: str, value) -> None:
        field = self.fields[key]
        text = _fmt(value)
        if hasattr(field, "_start"):
            field._start = text
            if not field.hasFocus() and field.text() != text:
                field.setText(text)
        elif field.text() != text:
            field.setText(text)

    def enable(self, key: str, on: bool) -> None:
        self.fields[key].setEnabled(on)


class GlyphPanel(QWidget):
    """Glyphe courant : nom (renommer partout), Unicode, chasse, approches, point choisi (saisie précise)."""
    message = Signal(str)

    def __init__(self, pane, parent=None):
        super().__init__(parent)
        self.pane = pane
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_title("Glyphe"))
        self.table = _Table("Glyphe", [
            ("name", "Nom", True, self._rename),
            ("unicodes", "Unicode (hex)", True, self._unicodes),
            ("width", "Chasse", True, lambda v: self._metric("width", v)),
            ("lsb", "Approche gauche", True, lambda v: self._metric("lsb", v)),
            ("rsb", "Approche droite", True, lambda v: self._metric("rsb", v)),
            ("x", "Point X", True, lambda v: self._coord(0, v)),
            ("y", "Point Y", True, lambda v: self._coord(1, v)),
            ("layers", "Calques couleur", True, self._layers),
            ("info", "Contenu", False, None),
        ])
        self.table.fields["layers"].setToolTip(
            "Glyphe couleur (COLR) : « A.rouge:0, A.bleu:lin(0,1), A.o:rad(2,0) ».\nglyphe:indice = aplat de la "
            "palette ; lin(a,b[,angle]) = dégradé linéaire de la couleur a à b (90 = de bas en haut) ; rad(a,b) = "
            "dégradé radial (COLR v1). Visible dans l'aperçu.")
        layout.addWidget(self.table.frame)
        layout.addStretch(1)

    def refresh(self) -> None:
        cv = self.pane.canvas
        glyph = cv.glyph if self.pane.current_name else None
        if glyph is None and self.pane.current_name and self.pane.current_name in cv.font:
            glyph = cv.font[self.pane.current_name]
        t = self.table
        if glyph is None:
            for key in t.fields:
                t.set(key, "")
            return
        t.set("name", glyph.name)
        t.set("unicodes", " ".join(f"{u:04X}" for u in glyph.unicodes))
        t.set("width", round(glyph.width, 2))
        lsb, rsb = metrics.left_margin(glyph, cv.font), metrics.right_margin(glyph, cv.font)
        t.set("lsb", None if lsb is None else round(lsb, 2))
        t.set("rsb", None if rsb is None else round(rsb, 2))
        pts = geometry.selection_points(glyph, cv.selection) if cv.name == glyph.name else []
        bounds = geometry.bounds_of_points(pts)
        t.set("x", "" if bounds is None else round(bounds[0], 2))
        t.set("y", "" if bounds is None else round(bounds[1], 2))
        t.enable("x", bool(pts))
        t.enable("y", bool(pts))
        t.set("layers", color.format_layers(color.layers(cv.font, glyph.name)))
        points = sum(len(c) for c in glyph.contours)
        t.set("info", f"{len(glyph.contours)} contours, {points} points, {len(glyph.components)} composants, "
                      f"{len(glyph.anchors)} ancres")

    def _glyph_name(self):
        return self.pane.current_name

    def _rename(self, value):
        old = self._glyph_name()
        try:
            self.pane.project.rename_glyph(old, value.strip())
            self.pane.show_glyph(value.strip())
        except ProjectError as exc:
            self.message.emit(str(exc))
            self.refresh()

    def _unicodes(self, value):
        try:
            codes = [int(v.upper().replace("U+", ""), 16) for v in value.replace(",", " ").split()]
            self.pane.project.set_unicodes(self._glyph_name(), codes)
        except (ValueError, ProjectError) as exc:
            self.message.emit(str(exc) if isinstance(exc, ProjectError) else "Unicode : codes hexadécimaux attendus.")
        self.refresh()

    def _layers(self, value):
        """COLR : « A.rouge:0, A.bleu:lin(0,1) » (aplat ou dégradé de la palette de la famille) ; vide = aucun."""
        try:
            color.set_layers(self.pane.project, self._glyph_name(), color.parse_layers(value))
        except color.ColorError as exc:
            self.message.emit(str(exc))
        self.refresh()

    def _metric(self, which, value):
        try:
            number = _num(value)
        except ValueError:
            self.refresh()
            return
        font = self.pane.canvas.font
        fn = {"width": lambda g: metrics.set_width(g, number),
              "lsb": lambda g: metrics.set_left_margin(g, number, font),
              "rsb": lambda g: metrics.set_right_margin(g, number, font)}[which]
        self.pane.project.edit_glyph(self._glyph_name(), "Métriques", fn, master=self.pane.canvas.master)
        self.refresh()

    def _coord(self, axis, value):
        cv = self.pane.canvas
        try:
            number = _num(value)
        except ValueError:
            self.refresh()
            return
        pts = geometry.selection_points(cv.glyph, cv.selection)
        bounds = geometry.bounds_of_points(pts)
        if bounds is None:
            return
        delta = number - bounds[axis]
        cv.edit("Coordonnées", lambda g: geometry.move_points(g, cv.selection, delta if axis == 0 else 0,
                                                                 delta if axis == 1 else 0))
        self.refresh()


class FontPanel(QWidget):
    """Famille et master courant : noms, unités par em, métriques verticales, angle d'italique."""
    message = Signal(str)
    FIELDS = (("familyName", "Famille", True), ("styleName", "Style (master)", False),
              ("unitsPerEm", "Unités par em", True), ("ascender", "Ascendante", False),
              ("descender", "Descendante", False), ("capHeight", "Hauteur de capitale", False),
              ("xHeight", "Hauteur d'x", False), ("italicAngle", "Angle d'italique", False))

    def __init__(self, pane, parent=None):
        super().__init__(parent)
        self.pane = pane
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_title("Famille"))
        self.table = _Table("Famille", [(attr, label, True, (lambda v, a=attr, g=glob: self._commit(a, v, g)))
                                        for attr, label, glob in self.FIELDS]
                            + [("palette", "Palette couleur (CPAL)", True, self._palette)])
        layout.addWidget(self.table.frame)

    def refresh(self) -> None:
        info = self.pane.canvas.font.info
        for attr, _label_text, _glob in self.FIELDS:
            self.table.set(attr, getattr(info, attr))
        self.table.set("palette", " ".join(color.palette(self.pane.canvas.font)))

    def _palette(self, value):
        """« #ff0000 #0000ff80 » : palette 0 de la famille (polices couleur COLR / CPAL) ; vide = aucune."""
        try:
            color.set_palette(self.pane.project, color.parse_palette(value))
        except color.ColorError as exc:
            self.message.emit(str(exc))
        self.refresh()

    def _commit(self, attr, value, all_masters):
        project = self.pane.project
        master = self.pane.canvas.master
        if attr in ("familyName", "styleName"):
            text = value.strip()
            if not text:
                self.refresh()
                return
            project.set_info(attr, text, master=master, all_masters=all_masters)
            if attr == "styleName":
                project.masters[master].name = text
        else:
            try:
                number = _num(value)
            except ValueError:
                self.refresh()
                return
            if attr == "unitsPerEm" and not 16 <= number <= 16384:
                self.message.emit("Unités par em : de 16 à 16384.")
                self.refresh()
                return
            number = int(number) if attr != "italicAngle" else number
            project.set_info(attr, number, master=master, all_masters=all_masters)
        self.pane.canvas.update()


class KerningPanel(QWidget):
    """Crénage du glyphe courant (paires où il est à gauche ou à droite, 40 au plus) et aide automatique."""
    message = Signal(str)

    def __init__(self, pane, parent=None):
        super().__init__(parent)
        self.pane = pane
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.addWidget(_title("Crénage"))
        self.summary = _label("", "note")
        self.summary.setWordWrap(True)
        self.layout_.addWidget(self.summary)
        row = QHBoxLayout()
        row.addWidget(button("Suggérer", "Aide automatique : paires du texte de l'aperçu comparées à « nn » ; "
                                         "rien n'est appliqué sans « Appliquer »", self.suggest))
        self.apply_button = button("Appliquer", "Appliquer les suggestions (une étape d'annulation)", self.apply)
        self.apply_button.setEnabled(False)
        row.addWidget(self.apply_button)
        row.addStretch(1)
        self.layout_.addLayout(row)
        self.suggestions: dict = {}

    def refresh(self) -> None:
        name = self.pane.current_name
        font = self.pane.canvas.font
        if not name:
            self.summary.setText("")
            return
        left = kerning.group_of(font, name, 1)
        right = kerning.group_of(font, name, 2)
        pairs = [(p, v) for p, v in font.kerning.items() if name in p or left in p or right in p][:40]
        lines = [f"Classes : gauche {left or '—'}, droite {right or '—'}"]
        lines += [f"{a} | {b} : {v:g}" for (a, b), v in pairs]
        self.summary.setText("\n".join(lines))

    def suggest(self) -> None:
        preview = self.pane.preview
        names = [n for n in preview.glyph_names() if n != "\n"]
        pairs = list(dict.fromkeys(zip(names, names[1:])))
        font = self.pane.canvas.font
        self.suggestions = kerning.suggest(font, pairs, reference=("n", "n") if "n" in font else ("H", "H"))
        if not self.suggestions:
            self.message.emit("Aucune suggestion (paires déjà équilibrées, ou référence nn / HH absente).")
        else:
            self.message.emit("Suggestions : " + ", ".join(f"{a}{b} {v:+g}" for (a, b), v in
                                                            list(self.suggestions.items())[:12]))
        self.apply_button.setEnabled(bool(self.suggestions))

    def apply(self) -> None:
        if not self.suggestions:
            return
        project, master = self.pane.project, self.pane.canvas.master
        font = project.masters[master].font
        targets = {kerning.target_pair(font, a, b): v for (a, b), v in self.suggestions.items()}
        before = {t: font.kerning.get(t) for t in targets}

        def put(values):
            for t, v in values.items():
                if v is None:
                    font.kerning.pop(t, None)
                else:
                    font.kerning[t] = v
            project.notify("kerning", None)
        put(targets)
        project.undo.push(f"Crénage automatique ({len(targets)} paires)", lambda: put(before), lambda: put(targets))
        self.suggestions = {}
        self.apply_button.setEnabled(False)
        self.refresh()


class FeaturesPage(QWidget):
    """Éditeur .fea : vérification à la frappe (temporisée, erreurs lisibles avec ligne / colonne), génération des
    features courantes, application au projet (une étape)."""
    message = Signal(str)

    def __init__(self, pane, parent=None):
        super().__init__(parent)
        self.pane = pane
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        bar = QHBoxLayout()
        bar.addWidget(_title("Features OpenType"))
        bar.addStretch(1)
        self.generate_button = button("Générer…", "liga, dlig, smcp, c2sc, onum, lnum, tnum, pnum, case, salt, ssXX "
                                                  "(d'après les glyphes présents)", self.generate_menu)
        bar.addWidget(self.generate_button)
        bar.addWidget(button("Appliquer", "Enregistrer ce texte dans le projet (Ctrl+Entrée)", self.apply))
        layout.addLayout(bar)
        self.editor = QPlainTextEdit(self)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(10)
        self.editor.setFont(mono)
        layout.addWidget(self.editor, 1)
        self.errors = _label("", "row_note")
        self.errors.setWordWrap(True)
        layout.addWidget(self.errors)
        note = _label("kern, mark et mkmk sont générés à la compilation depuis le crénage et les ancres "
                      "(ne les écrivez que pour les remplacer).", "note")
        note.setWordWrap(True)
        layout.addWidget(note)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self.check)
        self.editor.textChanged.connect(self._timer.start)

    def refresh(self) -> None:
        text = self.pane.canvas.font.features.text or ""
        if self.editor.toPlainText() != text:
            self.editor.blockSignals(True)
            self.editor.setPlainText(text)
            self.editor.blockSignals(False)
        self.check()

    def check(self) -> list:
        errors = features.check(self.editor.toPlainText(), self.pane.canvas.font.keys())
        self.errors.setText("\n".join(str(e) for e in errors) if errors else "Aucune erreur de syntaxe.")
        return errors

    def apply(self) -> bool:
        if self.check():
            self.message.emit("Features non appliquées : corrigez d'abord l'erreur.")
            return False
        features.set_features(self.pane.project, self.editor.toPlainText())
        self.message.emit("Features enregistrées dans le projet.")
        return True

    def generate_menu(self) -> None:
        from fm_theme.menu import Menu
        menu = Menu(self)
        for tag in ("liga", "dlig", "smcp", "c2sc", "onum", "lnum", "tnum", "pnum", "case", "salt", "ss01", "ss02"):
            menu.addAction(f"{tag} — {features.DESCRIPTIONS.get(tag, '')}").triggered.connect(
                lambda _c=False, t=tag: self.generate([t]))
        menu.exec(self.generate_button.mapToGlobal(self.generate_button.rect().bottomLeft()))

    def generate(self, tags) -> str:
        code = features.generate(self.pane.canvas.font, tags)
        if not code:
            self.message.emit(f"{', '.join(tags)} : aucun glyphe correspondant (ex. f_i, a.sc, one.osf).")
            return ""
        self.editor.setPlainText(features.merge(self.editor.toPlainText(), code))
        return code


class _Relay(QObject):
    done = Signal(object)                                   # résultat d'un fil de fond, rendu au fil de l'interface


class DiagnosticsPage(QWidget):
    """Diagnostic en trois niveaux ; clic sur une ligne qui nomme un glyphe = l'ouvrir."""
    glyphRequested = Signal(str)

    def __init__(self, pane, parent=None):
        super().__init__(parent)
        self.pane = pane
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(8, 4, 8, 4)
        bar = QHBoxLayout()
        bar.addWidget(_title("Diagnostic"))
        self.counts = _label("", "value_muted")
        bar.addWidget(self.counts)
        bar.addStretch(1)
        bar.addWidget(button("Analyser", "Analyser le projet (tous les masters)", self.run))
        bar.addWidget(button("FontBakery…", "Contrôle FontBakery de la police compilée (s'il est installé)",
                             self.fontbakery))
        self.layout_.addLayout(bar)
        self.body = QVBoxLayout()
        self.layout_.addLayout(self.body, 1)
        self.table = None
        self.found = []

    def run(self) -> list:
        self.found = validation.diagnose(self.pane.project, variable=len(self.pane.project.masters) > 1)
        self._show(self.found)
        return self.found

    def _show(self, found, prefix: str = "") -> None:
        n = {lvl: sum(1 for d in found if d.level == lvl) for lvl in
             (validation.BLOCKING, validation.WARNING, validation.SUGGESTION)}
        self.counts.setText(f"  {prefix}{n[validation.BLOCKING]} bloquant(s), {n[validation.WARNING]} "
                            f"avertissement(s), {n[validation.SUGGESTION]} suggestion(s)")
        if self.table is not None:
            self.table.hide()
            self.table.deleteLater()
        from fm_theme.cells import build_cells_table
        rows = []
        for d in found[:150]:
            text = _label(str(d), "value")
            text.setWordWrap(True)
            if d.glyph:
                text.setCursor(Qt.PointingHandCursor)
                text.mousePressEvent = lambda _e, g=d.glyph: self.glyphRequested.emit(g)
            rows.append([(_label(d.level, "row_label"), "left", "center"), (text, "left", "center")])
        if not rows:
            rows = [[(_label("—", "row_label"), "left", "center"),
                     (_label("Aucun problème trouvé.", "value"), "left", "center")]]
        self.table, _head, _cells = build_cells_table([("Niveau", 110), ("Message", 0)], rows)
        self.body.addWidget(self.table)

    def fontbakery(self):
        """Compile le master courant et lance FontBakery dans un FIL (instantané du projet ici, quelques ms) : les
        résultats arrivent dans le tableau. Renvoie le fil (None si FontBakery manque ou tourne déjà)."""
        if not validation.fontbakery_available():
            self.counts.setText("  FontBakery n'est pas installé (pip install fontbakery).")
            return None
        if getattr(self, "_fb_thread", None) is not None and self._fb_thread.is_alive():
            return None
        import subprocess
        import tempfile
        import threading
        from pathlib import Path
        from .autosave import project_from_snapshot, snapshot
        from .compile import CompileError, compile_static, to_bytes
        snap, master = snapshot(self.pane.project), self.pane.canvas.master
        relay = self._fb_relay = _Relay()
        relay.done.connect(lambda found: self._show(found, "FontBakery : "))
        self.counts.setText("  FontBakery en cours (quelques secondes)…")

        def work():
            try:
                with tempfile.TemporaryDirectory(prefix="fmfont_fb_") as folder:
                    path = Path(folder) / "verif.ttf"
                    path.write_bytes(to_bytes(compile_static(project_from_snapshot(snap).masters[master].font,
                                                             "ttf")))
                    relay.done.emit(validation.run_fontbakery(path))
            except (CompileError, OSError, subprocess.SubprocessError) as exc:
                relay.done.emit([validation.Diagnostic(validation.BLOCKING, f"FontBakery impossible : {exc}")])
        self._fb_thread = threading.Thread(target=work, name="fm_font FontBakery", daemon=True)
        self._fb_thread.start()
        return self._fb_thread


class MastersPanel(QWidget):
    """Masters : liste, ajout (copie du master courant, contours compatibles), compatibilité."""
    message = Signal(str)

    def __init__(self, pane, parent=None):
        super().__init__(parent)
        self.pane = pane
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_title("Masters"))
        self.summary = _label("", "note")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = _Table("Variation", [("axes", "Axes et cartes", True, self._axes),
                                          ("position", "Position du master", True, self._position),
                                          ("instances", "Instances nommées", True, self._instances)], width=190)
        self.table.fields["axes"].setToolTip(
            "« Nom étiquette min défaut max [carte u>c …] », axes séparés par « ; ».\nEx. « Weight wght 100 400 900 "
            "carte 100>20 400>80 900>200 ; Width wdth 75 100 125 ».\nMin / défaut / max : valeurs UTILISATEUR "
            "(fvar) ; la carte les relie aux valeurs de CONCEPTION des masters (table avar).")
        self.table.fields["position"].setToolTip("Position de CONCEPTION du master courant, ex. « Weight=80 Width=100 »")
        self.table.fields["instances"].setToolTip(
            "Ex. « Light 300, Regular 400, Bold 700 » (premier axe) ou « Bold Condensed wght=700 wdth=75 » "
            "(valeurs utilisateur) : instances de la police variable et des exports statiques")
        layout.addWidget(self.table.frame)
        row = QHBoxLayout()
        row.addWidget(button("Ajouter un master", "Copie du master courant (graisse 700 sur l'axe Weight)",
                             self.add))
        row.addWidget(button("Compatibilité", "Vérifier que les masters s'interpolent", self.check))
        row.addStretch(1)
        layout.addLayout(row)

    def refresh(self) -> None:
        p = self.pane.project
        axes = ", ".join(f"{a.name} ({a.tag}) {a.minimum:g}–{a.maximum:g}" for a in p.axes) or "aucun axe"
        lines = [f"Axes : {axes}"] + [f"{'▶ ' if i == self.pane.canvas.master else ''}{m.name} "
                                      f"{m.location or ''}" for i, m in enumerate(p.masters)]
        self.summary.setText("\n".join(lines))
        master = p.masters[min(self.pane.canvas.master, len(p.masters) - 1)]
        self.table.set("axes", axes_model.format_axes(p.axes))
        self.table.set("position", axes_model.format_location(p, master.location))
        self.table.set("instances", axes_model.format_instances(p))
        for key in ("position", "instances"):
            self.table.enable(key, bool(p.axes))

    def _model_call(self, fn) -> None:
        try:
            fn()
        except ProjectError as exc:
            self.message.emit(str(exc))
        self.pane.masters_changed()                          # rafraîchit aussi ce panneau (texte refusé effacé)

    def _axes(self, value) -> None:
        p = self.pane.project
        self._model_call(lambda: axes_model.set_axes(p, axes_model.parse_axes(value)))

    def _position(self, value) -> None:
        p = self.pane.project
        self._model_call(lambda: axes_model.set_master_location(p, self.pane.canvas.master,
                                                                axes_model.parse_location(p, value)))

    def _instances(self, value) -> None:
        p = self.pane.project
        self._model_call(lambda: p.set_instances(axes_model.parse_instances(p, value)))

    def add(self) -> None:
        p = self.pane.project
        from .document import _axis
        if not p.axes:
            p.axes.append(_axis("Weight", "wght", 400, 400, 700))
            p.masters[0].location = {"Weight": 400}
        axis = p.axes[0]
        used = {m.location.get(axis.name) for m in p.masters}
        if axis.map:                                         # carte posée : rester dans l'axe, ne pas l'étendre
            low, high = axes_model.design_ranges(p)[axis.name][0::2]
            value = next((v for v in (high, low, (low + high) / 2) if v not in used), None)
            if value is None:
                self.message.emit("Axe déjà occupé : élargissez-le (Axes et cartes) avant d'ajouter un master.")
                return
        else:
            value = next(v for v in (700, 900, 100, 300, 500, 600, 800, 200) if v not in used)
            axis.minimum, axis.maximum = min(axis.minimum, value), max(axis.maximum, value)
        name = {100: "Thin", 200: "ExtraLight", 300: "Light", 500: "Medium", 600: "SemiBold", 700: "Bold",
                800: "ExtraBold", 900: "Black"}.get(value, f"W{value}")
        p.add_master(name, {axis.name: value}, copy_from=self.pane.canvas.master)
        self.message.emit(f"Master « {name} » ajouté (copie : modifiez ses contours sans changer leur structure).")
        self.pane.masters_changed()

    def check(self) -> None:
        problems = interpolation.incompatibilities(self.pane.project)
        self.message.emit("Masters compatibles." if not problems else
                          f"{len(problems)} problème(s) : {problems[0]}")

