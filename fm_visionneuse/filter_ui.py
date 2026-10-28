"""Filtres de la visionneuse : pastilles (FilterChips), fenêtre de filtre et son menu.

Découpé de focus.py (2026-10-28) ; carte : docs/agents/fm_visionneuse.md."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QHBoxLayout, QWidget

from app_style import C, scaled

from .attributes_ui import _ColorLabels, _StarRating


# -- Filtres de la planche (demande de l'utilisateur) : bouton filtre, fenetre, elements ecrits a cote --
class FilterChips(QWidget):
    """Elements du filtre applique, ecrits a cote du bouton filtre de la planche en « style code » : police
    et couleur du role « Police code » (Reglages > Polices principales), chacun dans une pastille teintee
    de cette couleur, arrondie comme les zones de saisie. Transparent a la souris (la planche reste
    cliquable dessous) ; `set_items` retaille le widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._items: list[str] = []
        self.restyle()

    def restyle(self):
        from app_style import role_color, role_font
        self._font = role_font("code", 10)
        self._color = role_color("code", C["text"])
        self._layout()

    def set_items(self, items: list[str]):
        self._items = list(items)
        self._layout()

    def _layout(self):
        metrics = QFontMetrics(self._font)
        pad, gap = scaled(6), scaled(4)
        self._boxes = []
        x = 0
        height = metrics.height() + scaled(6)
        for text in self._items:
            width = metrics.horizontalAdvance(text) + 2 * pad
            self._boxes.append((QRectF(x, 0, width, height), text))
            x += width + gap
        self.setFixedSize(max(1, int(x - gap if self._items else 1)), height)
        self.update()

    def paintEvent(self, event):
        from settings_widgets import _input_radius
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setFont(self._font)
        radius = min(_input_radius(), self.height() / 2)
        tint = QColor(self._color)
        tint.setAlphaF(0.16)
        for rect, text in self._boxes:
            p.setPen(Qt.NoPen)
            p.setBrush(tint)
            p.drawRoundedRect(rect, radius, radius)
            p.setPen(QColor(self._color))
            p.drawText(rect, Qt.AlignCenter, text)
        p.end()


def filter_window(spec: dict, scopes: list[tuple[str, str]], settings: dict | None = None, parent=None,
                  provenances: list[tuple[str, str]] | None = None):
    """Fenetre des filtres de la planche : la fenetre « Changement de style a la volee » (briques des
    reglages, mise en forme retenue sous « Filtres »), une ligne par critere. `scopes` : (cle, libelle) des
    portees proposees ; `provenances` : (cle, libelle) des provenances (file_filters.provenance_choices).
    Valeurs en direct par `styleChanged` -> dict du filtre (file_filters)."""
    from fm_visionneuse import file_filters as ff
    from settings_cells import _TextField
    from settings_quick_style import QuickStyleWindow
    from settings_widgets import _SelectField, _SliderField, _Toggle
    spec = ff.normalized(spec)
    width = scaled(190)
    scope_labels = [label for _k, label in scopes]
    scope = _SelectField(scope_labels, dict(scopes).get(spec["scope"], scope_labels[0]), width=width)
    origins = [("", "Toutes")] + list(provenances if provenances is not None else ff.PROVENANCE_FIXED)
    if spec["provenance"] and spec["provenance"] not in dict(origins):
        origins.append((spec["provenance"], spec["provenance"][len(ff.PROV_IO):]))
    origin = _SelectField([label for _k, label in origins], dict(origins)[spec["provenance"]], width=width)
    # Note : « au moins » / « egal a » puis les etoiles, cote a cote dans la cellule (sans entete ni
    # bordures de sous-cellules : demande de l'utilisateur).
    rating = QWidget()
    rating.setStyleSheet("background: transparent;")
    row_layout = QHBoxLayout(rating)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(scaled(10))
    rating.mode = _SelectField([l for _k, l in ff.RATING_MODES], dict(ff.RATING_MODES)[spec["rating_mode"]],
                               width=scaled(90))
    rating.stars = _StarRating()
    rating.stars.setValue(spec["rating"])
    rating._v2_parts = {"mode": rating.mode, "stars": rating.stars}
    row_layout.addWidget(rating.mode, 0, Qt.AlignVCenter)
    row_layout.addWidget(rating.stars, 0, Qt.AlignVCenter)
    colors = _ColorLabels(multi=True)
    colors.setValues(spec["color"])
    # Mots cles : comme dans les attributs, separes par des espaces, autocompletion des mots deja employes.
    from fm_visionneuse import file_attributes
    from settings_cells import _WordsField
    keywords = _WordsField(spec["keywords"], suggestions=file_attributes.known_keywords, width=width)
    keywords.setPlaceholderText("ciel nuit…")
    statuses = (("", "Tous"), ("keep", "Marquées"), ("delete", "Rejetées"), (ff.STATUS_NONE, "Neutres"))
    status = _SelectField([l for _k, l in statuses], dict(statuses)[spec["status"]], width=width)
    extensions = _TextField(" ".join(spec["extensions"]), width=width)
    extensions.setPlaceholderText("jpg png blend…")
    size_min = _SliderField(0, 2000, spec["size_min"], "Mo", slider_width=scaled(120), box_width=68)
    size_max = _SliderField(0, 2000, spec["size_max"], "Mo", slider_width=scaled(120), box_width=68)
    period = _SelectField([l for _k, l in ff.DATE_PERIODS], dict(ff.DATE_PERIODS)[spec["period"]], width=width)
    date_from = _TextField(spec["date_from"], width=width)
    date_to = _TextField(spec["date_to"], width=width)
    for field in (date_from, date_to):
        field.setPlaceholderText("JJ/MM/AAAA")

    def key_of(pairs, label):
        return next((k for k, l in pairs if l == label), pairs[0][0])

    rows = [
        ("Portée", scope, lambda w: {"scope": key_of(scopes, w.value())}),
        ("Provenance", origin, lambda w: {"provenance": key_of(origins, w.value())}),
        ("Note", rating, lambda w: {"rating": w.stars.value(),
                                     "rating_mode": key_of(ff.RATING_MODES, w.mode.value())}),
        ("Couleurs", colors, lambda w: {"color": w.values()}),
        ("Mots clés", keywords, lambda w: {"keywords": w.words()}),
        ("Drapeau", status, lambda w: {"status": key_of(statuses, w.value())}),
        ("Type de fichier", extensions, lambda w: {"extensions": ff.parse_extensions(w.text())}),
        ("Taille min (0 = aucune)", size_min, lambda w: {"size_min": w.value()}),
        ("Taille max (0 = aucune)", size_max, lambda w: {"size_max": w.value()}),
        ("Date", period, lambda w: {"period": key_of(ff.DATE_PERIODS, w.value())}),
        ("Modifié depuis le", date_from, lambda w: {"date_from": w.text().strip()}),
        ("Modifié jusqu'au", date_to, lambda w: {"date_to": w.text().strip()}),
    ]
    window = QuickStyleWindow("Filtres", rows, {}, title="Filtres", settings=settings, parent=parent)
    window.filter_fields = {label: widget for label, widget, _r in rows}

    def refresh_marks(*_a):
        """Lignes ou un filtre est applique (valeur differente de « aucun filtre ») : fond / bordures de
        Reglages > Visionneuse > Filtres (clic droit > « Style des filtres actives »)."""
        from settings_widgets import set_row_mark
        look = filter_row_look()
        for _label, widget, reader in rows:
            values = reader(widget)
            current = ff.normalized(values)
            active = any(current[k] != ff.DEFAULT_FILTER[k] for k in values if k not in ff.MODIFIERS)
            try:
                set_row_mark(widget, look if active else None)
            except RuntimeError:                  # fenetre fermee
                return
    window.refresh_marks = refresh_marks
    window.styleChanged.connect(refresh_marks)
    refresh_marks()
    return window


def filter_row_look() -> dict:
    """Marque des lignes actives de la fenetre des filtres (settings_widgets.set_row_mark), d'apres les
    reglages appliques."""
    import ui_state
    from app_style import resolve_color_ref
    from settings_store import DEFAULT_SETTINGS
    from settings_store import _coerce_corner_radius
    from settings_widgets import _coerce_side_enabled
    s = {**DEFAULT_SETTINGS, **(ui_state.APPLIED_SETTINGS or {})}
    bg = resolve_color_ref(s["viewer_filter_row_bg_color"]) if s["viewer_filter_row_bg_enabled"] else None
    return {"bg": bg, "sides": _coerce_side_enabled(s["viewer_filter_row_border_enabled"]),
            "colors": {k: resolve_color_ref(v) for k, v in (s["viewer_filter_row_border"] or {}).items()},
            "thickness": int(s["viewer_filter_row_border_thickness"] or 0),
            "radius": _coerce_corner_radius(s["viewer_filter_row_radius"]),
            "margin": {k: int((s["viewer_filter_row_margin"] or {}).get(k, 0) or 0)
                       for k in ("left", "top", "right", "bottom")}}


def _filter_window_menu_extra(widget, menu):
    """Clic droit dans la fenetre des filtres : « Style des filtres actives… » (fond, bordures)."""
    window = widget.window() if widget is not None else None
    handler = getattr(window, "on_row_style", None)
    if handler is None:
        return
    menu.addSeparator()
    menu.addAction("Style des filtres activés…", handler)


def _install_filter_menu():
    from settings_widgets import CONTEXT_MENU_EXTRAS
    if _filter_window_menu_extra not in CONTEXT_MENU_EXTRAS:
        CONTEXT_MENU_EXTRAS.append(_filter_window_menu_extra)


_install_filter_menu()
