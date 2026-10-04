from typing import Any
from PySide6.QtCore import (
    QPoint, Qt, Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from app_style import (
    SEMANTIC_COLOR_SLOTS,
    SMOOTHING_CHOICES,
    SMOOTHING_LABELS_SHORT,
    auto_family_for_role,
    installed_font_families,
)
from settings_theme import _input_radius, _register_input, _set_text_role, _text_label  # noqa: F401
from settings_store import (
    M,
    _SLOT_REAL,
    _resolve_color_value,
)
from settings_colorpicker import (
    _CheckSquare,
    _ColorField,
)
from settings_widgets import (
    _ColorPickerPopup,
    _ColorSwatchButton,
    _FontSelectField,
    _SLOT_LABELS,
    _SelectField,
    _SliderField,
    _SteppedSliderField,
    _Toggle,
    _apply_stylesheet_cached,
    _qfont,
    _restyle_table_row,
    _set_dimmed,
    _table_frame,
)
from settings_layout import (
    _build_linked_sides_toggle,
    _lock_min_height,
    _restyle_table_head,
    _table_cell,
    _table_header,
    _table_row,
    _wire_resizable_columns,
)


# ==========================================================================
# Registre "item_*" (famille Texte) — SOURCE UNIQUE decrivant chaque champ
# simple (slider/toggle/couleur) present A LA FOIS dans General > Colonnes
# > Texte ET dans Colonnes > Type (surcharge par cle) — voir la remarque de
# l'utilisateur, "je veux que toutes les options a overider dans
# colonnes/types soient constamment synchronisees, c'est a dire que si on
# rajoute une option dans les settings de base, elle se retrouve aussi
# dans les options a overider". Ajouter une entree ICI suffit desormais a
# la faire apparaitre aux deux endroits (widget General, widget+toggle
# Colonnes > Type, attribut de _ITEM_TEXT_FIELD_ATTR, extraction
# _read_override_field_raw, seed au chargement, connexion _mark_dirty,
# sauvegarde) SANS toucher chacun de
# ces endroits a la main — voir SettingsWindow._build_column_type_page/
# __init__/_apply_values_to_controls/_current_values, plus bas, qui
# bouclent tous sur cette liste. Ne couvre PAS les champs plus complexes
# (police, bordures a 4 cotes, paddings lies...) qui restent geres a la
# main comme avant.
# ==========================================================================

class _ItemFieldSpec:
    __slots__ = ("key", "label", "kind", "default", "vmin", "vmax")

    def __init__(self, key: str, label: str, kind: str, default, vmin=None, vmax=None):
        self.key = key
        self.label = label
        self.kind = kind  # "slider" | "toggle" | "color"
        self.default = default
        self.vmin = vmin
        self.vmax = vmax

    def make_field(self, seed, colors: dict, *, slider_width: int):
        if self.kind == "slider":
            return _SliderField(self.vmin, self.vmax, int(seed), slider_width=slider_width, box_width=68)
        if self.kind == "toggle":
            return _Toggle(bool(seed), style_override="toggle1")
        if self.kind == "color":
            # _CompactAppOrCustomColorField (pas la variante large) : ce
            # champ est EMBARQUE dans la ligne "Police" du gabarit police
            # (voir _build_font_gabarit_row/Colonnes > Lignes > Texte), donc
            # partage la meme instance que sa reprise standalone dans
            # Colonnes > Type/Projets/Sous-projet (_build_column_type_page,
            # meme spec.make_field) — voir la remarque de l'utilisateur,
            # capture d'ecran, "voici a quoi doit ressembler la ligne
            # police".
            return _CompactAppOrCustomColorField(seed, colors, swatch_size=20, title=self.label)
        raise ValueError(self.kind)

    def raw_value(self, widget):
        if self.kind == "toggle":
            return widget.isChecked()
        return widget.value()

    def seed_widget(self, widget, value):
        if self.kind == "slider":
            widget.setValue(int(value))
        elif self.kind == "toggle":
            widget.setChecked(bool(value))
        else:
            widget.setValue(value)

    def dirty_signal(self, widget):
        if self.kind == "slider":
            return widget.valueChanged
        if self.kind == "toggle":
            return widget.toggled
        return widget.changed

_ITEM_TEXT_FIELD_SPECS = [
    _ItemFieldSpec("item_color", "Couleur", "color", "#d6d9dc"),
    # "Icone" (item_icon_enabled) retiree de cette liste (voir la remarque
    # de l'utilisateur, "supprime la ligne Icone") — remplacee par le
    # toggle PAR COLONNE "Afficher l'icone" du menu contextuel (voir
    # Column._on_context_menu/_show_icon_override) ; la cle/le comportement
    # (repli a True) restent INCHANGES, seule cette ligne de reglage
    # GENERAL disparait.
    _ItemFieldSpec("item_row_height", "Hauteur de la ligne", "slider", 25, 14, 80),
    _ItemFieldSpec("item_icon_size", "Taille de l'icone par defaut (0 = hauteur de ligne)", "slider", 0, 0, 128),
    _ItemFieldSpec("item_icon_padding_left", "Padding gauche de l'icone", "slider", 0, 0, 64),
    _ItemFieldSpec("item_row_spacing", "Espacement entre les lignes", "slider", 1, 0, 20),
    _ItemFieldSpec("item_text_padding", "Padding du texte", "slider", 8, 0, 32),
    # "Bordure entre les lignes" (toggle + couleur + epaisseur) N'EST PAS
    # ici : elle tient dans UNE SEULE ligne/UN SEUL widget (_RowBorderField,
    # voir sa remarque de tete de classe et la remarque de l'utilisateur,
    # "rassemble bordure couleur et epaisseur dans une seule ligne") plutot
    # que dans 3 champs separes comme le reste de ce registre suppose (1
    # cle = 1 widget) — geree a la main comme item_selection_border/
    # header_border (meme situation : 1 widget pour plusieurs cles), voir
    # plus bas (_read_override_field_raw/_build_column_type_page/
    # SettingsWindow.__init__).
]

_ITEM_TEXT_FIELD_BY_KEY = {spec.key: spec for spec in _ITEM_TEXT_FIELD_SPECS}

# Attribut portant chaque champ GENERAL — "item_icon_enabled" garde son
# ancien nom d'attribut "item_icon_field" (pre-existant, reference
# ailleurs dans le fichier), les autres suivent la convention "<cle>_field".
_ITEM_TEXT_FIELD_ATTR = {
    spec.key: ("item_icon_field" if spec.key == "item_icon_enabled" else f"{spec.key}_field")
    for spec in _ITEM_TEXT_FIELD_SPECS
}

# Cles dont le reglage LIE ("linked"/"libre", voir _CornerRadiusField/
# _CellPaddingField) doit aussi etre suivi/persiste a part (voir
# SettingsWindow._type_override_linked/_current_values).
_TYPE_LINKED_KEYS = (
    "header_radius", "column_padding", "column_border_radius", "item_selection_padding", "item_selection_radius",
    "item_image_padding", "item_image_radius",
    "item_selection_unfocus_padding", "item_selection_unfocus_radius",
    "item_selection_hover_padding", "item_selection_hover_radius",
    "item_selection_idle_padding", "item_selection_idle_radius",
)

def _read_override_field_raw(key: str, widget):
    """Valeur BRUTE (meme forme que dans settings.json — pas de couleur
    "@slot" resolue, voir app_style.resolve_color_ref, qui s'en charge cote
    appli reelle) d'un champ de Colonnes > Type OU de son homologue GENERAL
    (voir SettingsWindow._resolve_type_effective, appele sur l'un ou
    l'autre selon l'etat du toggle de la ligne)."""
    if key in _ITEM_TEXT_FIELD_BY_KEY:
        return _ITEM_TEXT_FIELD_BY_KEY[key].raw_value(widget)
    # "item_selection_<etat>_<champ>_override" (etat = unfocus/hover/idle) :
    # PAS un champ propre, TOUJOURS True des que Type/Projets/Sous-projet
    # surcharge le champ associe (voir _build_column_override_page, MEME
    # toggle que "item_selection_<etat>_<champ>") — si CETTE colonne a sa
    # propre valeur, elle doit evidemment s'appliquer, jamais retomber en
    # silence sur Focus faute d'avoir aussi surcharge ce flag separement.
    if key.startswith("item_selection_") and key.endswith("_override"):
        return True
    if key == "item_row_border_enabled":
        return widget.enabledValue()
    if key == "item_row_border_color":
        return widget.colorValue()
    if key == "item_row_border_thickness":
        return widget.thicknessValue()
    # "item_selection_<etat>_radius"/"..._border_enabled"/"..._border"/
    # "..._padding" (etat = unfocus/hover/idle, voir _build_column_
    # override_page/build_state_override) — MEMES suffixes, memes widgets,
    # que "item_selection_radius"/etc (Focus) ci-dessous : verifies par
    # SUFFIXE plutot qu'enumeres un par un, pour rester automatiquement a
    # jour avec build_state_override sans y revenir a chaque nouvel etat.
    if key in ("header_radius", "column_border_radius", "item_image_radius") or (
        key.startswith("item_selection_") and key.endswith("_radius")
    ):
        return widget.cornersValue()
    # "_edge_border" AVANT "_border_enabled"/"_border" ci-dessous (piege :
    # "item_selection_<etat>_edge_border" se termine AUSSI par "_border",
    # mais c'est un simple _Toggle, PAS un _ToggleSideColorsField — voir
    # la branche isChecked() plus bas, DOIT rester prioritaire ici).
    if key.startswith("item_selection_") and key.endswith("_edge_border"):
        return widget.isChecked()
    if key in ("header_border_enabled", "column_border_enabled", "item_image_border_enabled") or (
        key.startswith("item_selection_") and key.endswith("_border_enabled")
    ):
        return widget.sidesEnabledValue()
    if key in ("header_border", "column_border", "item_image_border") or (
        key.startswith("item_selection_") and key.endswith("_border")
    ):
        return widget.sidesValue()
    if key in ("column_padding", "item_image_padding") or (
        key.startswith("item_selection_") and key.endswith("_padding")
    ):
        return widget.sidesValue()
    if key == "header_color":
        return widget.value()
    if key in ("item_font_family", "header_font_family"):
        v = widget.value()
        return "" if v == "Systeme" else v
    if key == "item_font_bold" or key == "header_visible" or key == "header_font_bold":
        return widget.isChecked()
    if key == "header_font_color" or (
        key.startswith("item_selection_") and key.endswith("_color")
    ):
        return widget.value()
    if key == "item_image_ratio":
        return widget.value() / 100.0   # slider en % (100 = 1.0, voir sa remarque de construction)
    return widget.value()  # sliders (int) : header_height/padding/thickness..., item_row_height/spacing/text_padding

# ==========================================================================
# Section "Polices" — table Role/Police/Lissage/Apercu (4 colonnes, famille
# + niveau de lissage). Les 4 roles non repris ici (dossiers, boutons,
# entete de colonnes, info2) restent dans le fichier de reglages tels quels
# (voir DEFAULT_SETTINGS) : ils suivent silencieusement "Police principale"
# si elle est personnalisee (voir app_style.role_font), sinon
# l'auto-detection habituelle — exactement leur comportement actuel, juste
# sans UI pour le changer directement.
# ==========================================================================

_FONT_ROLES = [
    ("font_main", "app", "Police principale", "asset__spaceship_01"),
    ("font_info", "info", "Police informations", "121.7 KB · v004 · 2026-09-03"),
    ("font_titles", "titles", "Police principale titres", "Fichiers pour AIRPLANE"),
    ("font_files", "files", "Police fichiers", "foot.001.OBJ"),
    # "Code" : role ajoute sur demande de l'utilisateur, Consolas explicite
    # (voir app_style.code_family) — pas encore consommee ailleurs dans
    # l'appli (meme principe que "table_head"/"table_row" en leur temps).
    ("font_code", "code", "Police code", "def render(frame: int) -> None:"),
]

def _font_choices() -> list[str]:
    return ["Systeme"] + installed_font_families()

# Ordre des 3 crans du slider Lissage (voir _SteppedSliderField), du moins
# au plus lisse — cles de app_style.SMOOTHING_CHOICES/SMOOTHING_LABELS_SHORT,
# juste reordonnees pour correspondre a la remarque de l'utilisateur :
# "0=pas du tout, 1=un peu, 2=important".
_SMOOTHING_STEPS = ("none", "previous", "current")

class _SimpleFontTable(QWidget):
    """Une ligne par role (voir _FONT_ROLES) : nom de role, selecteur de
    police, apercu du nom de fichier/dossier dans cette police. Choisir une
    police (meme "Systeme" explicitement) marque le role "personnalise"
    (voir _current_values dans SettingsWindow) — sinon le changement de
    famille resterait sans effet si ce role n'avait encore jamais ete
    personnalise (voir app_style.role_font : la famille stockee n'est prise
    en compte que si `custom` est vrai)."""

    changed = Signal()

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame, layout = _table_frame()
        frame = self.frame
        self.head = _table_header([("Role", 150), ("Police", 170), ("Lissage", 170), ("Apercu", 0)])
        layout.addWidget(self.head)

        # Libelles dans l'ORDRE des crans du slider (voir _SMOOTHING_STEPS,
        # 0 = pas du tout, 2 = important) — slider a positions FIXES plutot
        # qu'un menu deroulant (voir la remarque de l'utilisateur : "slider
        # 3 points (crante)"), le lissage n'ayant de toute facon que ces 3
        # niveaux reels cote Qt/Windows (voir app_style.font()).
        smoothing_labels = [SMOOTHING_LABELS_SHORT[key] for key in _SMOOTHING_STEPS]

        self.rows: dict[str, dict[str, Any]] = {}
        self._row_meta: list[tuple[QWidget, str, bool]] = []
        # Toutes les cellules (_table_cell), TOUTES colonnes confondues —
        # separee de column_cells ci-dessous (qui ne sert qu'au cablage du
        # redimensionnement par colonne, voir _wire_resizable_columns) :
        # necessaire pour le padding (voir setCellPadding/SettingsWindow.
        # _apply_cell_padding), qui doit toucher CHAQUE cellule.
        self._cells: list[QWidget] = []
        column_cells: dict[int, list[QWidget]] = {}
        for i, (key, style_role, label, sample) in enumerate(_FONT_ROLES):
            conf = settings[key]
            bg = M["table_row_a"] if i % 2 else M["table_row_b"]
            row, row_l = _table_row(bg, first=(i == 0))
            self._row_meta.append((row, bg, i == 0))

            name = QLabel(label)
            _set_text_role(name, "row_label")
            cell = _table_cell(name, 150, row_l, center=True)
            column_cells.setdefault(0, []).append(cell)
            self._cells.append(cell)

            current_family = conf.get("family") or "Systeme"
            auto_label = auto_family_for_role(style_role)
            font_select = _FontSelectField(_font_choices(), current_family, width=162, auto_label=auto_label)
            cell = _table_cell(font_select, 170, row_l, center=True)
            column_cells.setdefault(1, []).append(cell)
            self._cells.append(cell)

            current_smoothing = conf.get("smoothing") or "current"
            if current_smoothing not in SMOOTHING_CHOICES:
                current_smoothing = "current"
            smoothing_step = _SMOOTHING_STEPS.index(current_smoothing)
            smoothing_select = _SteppedSliderField(smoothing_labels, smoothing_step, slider_width=20, box_width=90)
            cell = _table_cell(smoothing_select, 170, row_l, center=True)
            column_cells.setdefault(2, []).append(cell)
            self._cells.append(cell)

            preview = QLabel(sample)
            preview.setFont(QFont(current_family if current_family != "Systeme" else auto_label, 10))
            preview.setStyleSheet(f"color: {M['value_muted']}; background: transparent;")
            self._cells.append(_table_cell(preview, 0, row_l, center=True))

            _lock_min_height(row)
            layout.addWidget(row)
            entry = {
                "field": font_select, "smoothing_field": smoothing_select,
                "preview": preview, "auto": auto_label, "custom": bool(conf.get("custom", False)),
            }
            self.rows[key] = entry

            def _on_pick(family: str, e=entry):
                e["custom"] = True
                shown = family if family != "Systeme" else e["auto"]
                e["preview"].setFont(QFont(shown, 10))
                self.changed.emit()

            font_select.changed.connect(_on_pick)
            smoothing_select.changed.connect(lambda _step: self.changed.emit())
        _wire_resizable_columns(self.head, column_cells)
        # Largeurs sauvegardees (voir _GeoTable, meme raison de venir APRES
        # le cablage ci-dessus).
        saved_widths = settings.get("font_table_columns")
        if saved_widths:
            self.head.setColumnWidths(saved_widths)

        outer.addWidget(frame)

    def value(self) -> dict[str, dict]:
        out = {}
        for key, entry in self.rows.items():
            family = entry["field"].value()
            out[key] = {
                "family": "" if family == "Systeme" else family,
                "smoothing": _SMOOTHING_STEPS[entry["smoothing_field"].value()],
                "custom": entry["custom"],
            }
        return out

    def apply_radius(self, radius: int):
        """Voir _TableFrame : l'entete porte les coins hauts, la derniere
        ligne les coins bas — jamais le cadre lui-meme au-dela de son propre
        filet 1px. `bg` est RECALCULEE ici (pas reprise telle quelle depuis
        `_row_meta`, qui ne la garde que pour son ordre pair/impair) : cette
        methode sert aussi de rafraichissement apres un changement de
        couleur (voir SettingsWindow._refresh_dynamic_colors, qui l'appelle
        avec le rayon courant), donc la valeur stockee peut etre perimee."""
        self.frame.setRadius(radius)
        _restyle_table_head(self.head, radius)
        last = len(self._row_meta) - 1
        new_meta = []
        for i, (row, _old_bg, first) in enumerate(self._row_meta):
            bg = M["table_row_a"] if i % 2 == 0 else M["table_row_b"]
            _restyle_table_row(row, bg, first, bottom_radius=(radius if i == last else 0))
            new_meta.append((row, bg, first))
        self._row_meta = new_meta

    def apply_border(self, enabled: dict, colors: dict, thickness: int):
        self.frame.setBorder(enabled, colors, thickness)

    def setCellPadding(self, sides: dict):
        """Tableaux > Padding des cellules (voir SettingsWindow.
        _apply_cell_padding) : applique aux cellules (_table_cell) de CE
        tableau — contrairement aux tableaux "1 valeur par ligne", le
        padding touche ici chaque _table_cell individuellement (pas la
        ligne elle-meme, qui n'a pas de marge propre — voir _table_cell,
        (0, 6, 0, 6) fige a la construction), et l'entete (voir
        _ResizableTableHeader.setCellPadding) suit le GAUCHE/DROITE pour
        rester aligne avec le contenu — voir la remarque de l'utilisateur,
        "je ne vois pas pourquoi ca ne fonctionnerait pas" (Polices/
        Geometrie en etaient exclus jusqu'ici)."""
        left, top = int(sides.get("left", 10)), int(sides.get("top", 0))
        right, bottom = int(sides.get("right", 10)), int(sides.get("bottom", 0))
        for cell in self._cells:
            cell.layout().setContentsMargins(left, top, right, bottom)
        for row, _bg, _first in self._row_meta:
            row.setMinimumHeight(0)
            _lock_min_height(row)
        self.head.setCellPadding(left, right)

# ==========================================================================
# Section "Couleurs" — grille 2 colonnes, 8 pastilles semantiques (voir
# app_style.SEMANTIC_COLOR_SLOTS). "Selection en cours" et "Bouton" pilotent
# la MEME cle reelle ("accent", voir la remarque dans app_style.py) : les
# deux pastilles restent donc synchronisees, un changement sur l'une se
# repercute immediatement sur l'autre — fidele au reste de l'appli, qui n'a
# qu'une seule couleur d'accent pour les deux roles.
# ==========================================================================

class _ColorGrid(QWidget):
    """Grille 2 colonnes des pastilles semantiques — visuellement aussi un
    "tableau" (perimetre + gouttiere 1px entre cellules, voir wrap) que
    Polices/Entetes/Geometrie, donc suit lui aussi le slider Geometrie >
    Tableaux > Coins arrondis (voir setRadius) — voir la remarque de
    l'utilisateur, capture a l'appui : il manquait a l'appel."""

    changed = Signal()

    def __init__(self, colors: dict, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.wrap = wrap = QWidget()
        wrap.setAttribute(Qt.WA_StyledBackground, True)
        grid = QGridLayout(wrap)
        grid.setContentsMargins(1, 1, 1, 1)
        grid.setHorizontalSpacing(1)
        grid.setVerticalSpacing(1)
        self._fields_by_real_key: dict[str, list[_ColorField]] = {}
        self._hex_labels_by_real_key: dict[str, list[QLabel]] = {}
        # (widget, row, col) de chaque cellule — voir setRadius, qui a
        # besoin de savoir laquelle occupe chaque coin de la grille (le
        # nombre de pastilles etant impair, la derniere rangee n'a qu'une
        # seule cellule, en colonne 0 : voir _last_row/_last_col_in_last_row).
        self._cells: list[tuple[QWidget, int, int]] = []
        n = len(SEMANTIC_COLOR_SLOTS)
        self._last_row = (n - 1) // 2
        for i, (slot, real_key, label) in enumerate(SEMANTIC_COLOR_SLOTS):
            cell = QWidget()
            cell.setAttribute(Qt.WA_StyledBackground, True)
            cell_l = QHBoxLayout(cell)
            cell_l.setContentsMargins(10, 7, 10, 7)
            cell_l.setSpacing(10)
            field = _ColorField(colors.get(real_key, "#000000"), swatch_size=24, title=label)
            cell_l.addWidget(field)
            name = QLabel(label)
            _set_text_role(name, "inline_label")
            name.setWordWrap(False)
            cell_l.addWidget(name, 1)
            hex_label = QLabel(colors.get(real_key, ""))
            _set_text_role(hex_label, "table_head_mono")
            cell_l.addWidget(hex_label)
            self._fields_by_real_key.setdefault(real_key, []).append(field)
            self._hex_labels_by_real_key.setdefault(real_key, []).append(hex_label)
            field.changed.connect(lambda v, rk=real_key: self._sync_key(rk, v))
            row, col = divmod(i, 2)
            self._cells.append((cell, row, col))
            # Voir _lock_min_height : meme risque de tassement que les
            # lignes de _table_row (fenetre trop petite/pas assez de
            # place), ici sur une CELLULE de grille plutot qu'une ligne de
            # tableau — sans ca, la pastille de couleur (fixe, 24px) finit
            # par deborder du bas de sa cellule une fois celle-ci ecrasee
            # sous les ~38px qu'elle demande reellement (24 + marges 7/7),
            # recouvrant le filet de separation du bas — voir la remarque
            # de l'utilisateur, capture annotee a l'appui.
            _lock_min_height(cell)
            grid.addWidget(cell, row, col)
        self.setRadius(0)
        outer.addWidget(wrap)

    def setRadius(self, radius: int):
        """Voir _TableFrame.setRadius : le cadre exterieur (wrap, qui joue
        ici a la fois le role du cadre ET des filets entre cellules) porte
        toujours le rayon sur ses 4 coins ; seule la cellule qui occupe
        REELLEMENT un coin donne (voir self._cells) recoit ce meme rayon sur
        CE coin precis, pour ne pas laisser son angle carre depasser du
        cadre arrondi."""
        radius = max(0, int(radius))
        _apply_stylesheet_cached(self.wrap, f"background: {M['panel_border']}; border-radius: {radius}px;")
        for cell, row, col in self._cells:
            tl = radius if (row == 0 and col == 0) else 0
            tr = radius if (row == 0 and col == 1) else 0
            bl = radius if (row == self._last_row and col == 0) else 0
            br = radius if (row == self._last_row and col == 1) else 0
            _apply_stylesheet_cached(
                cell,
                f"background: {M['table_row_b']}; "
                f"border-top-left-radius: {tl}px; border-top-right-radius: {tr}px; "
                f"border-bottom-left-radius: {bl}px; border-bottom-right-radius: {br}px;",
            )

    def _sync_key(self, real_key: str, value: str):
        """Repercute un changement sur TOUTES les pastilles qui pointent
        vers la meme cle reelle (voir la remarque de tete de classe :
        selCur/button partagent "accent")."""
        for field in self._fields_by_real_key[real_key]:
            field.setValue(value)
        for label in self._hex_labels_by_real_key[real_key]:
            label.setText(value)
        self.changed.emit()

    def value(self) -> dict[str, str]:
        return {real_key: fields[0].value() for real_key, fields in self._fields_by_real_key.items()}

class _CornerRadiusSliders(QWidget):
    """4 sliders cote a cote (Haut-Gauche/Haut-Droite/Bas-Droite/Bas-Gauche)
    — MEME mecanique que _SidePaddingField (lien PERMANENT ou transfert
    PONCTUEL du 1er coin sur les 3 autres, voir sa remarque de tete de
    classe), transposee du padding au rayon des coins — voir la remarque de
    l'utilisateur, "dans tous les parametres de coins arrondis, je veux
    exactement le meme fonctionnement que les padding (un par coin)"."""

    changed = Signal()

    _ORDER = [("top_left", "HG"), ("top_right", "HD"), ("bottom_right", "BD"), ("bottom_left", "BG")]
    _LEADER = _ORDER[0][0]
    _OTHERS = tuple(key for key, _label in _ORDER[1:])

    def __init__(self, corners: dict, minimum: int = 0, maximum: int = 40, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._linked = False
        self.fields: dict[str, _SliderField] = {}
        for key, letter in self._ORDER:
            wrap = QWidget()
            wrap.setStyleSheet("background: transparent;")
            wrap_l = QVBoxLayout(wrap)
            wrap_l.setContentsMargins(0, 0, 0, 0)
            wrap_l.setSpacing(3)
            tag = QLabel(letter)
            _set_text_role(tag, "side_letter")
            wrap_l.addWidget(tag)
            field = _SliderField(minimum, maximum, int(corners.get(key, 0)), slider_width=60, box_width=42)
            field.valueChanged.connect(lambda _v, k=key: self._on_side_changed(k))
            self.fields[key] = field
            wrap_l.addWidget(field)
            layout.addWidget(wrap)

    def _on_side_changed(self, key: str):
        if self._linked and key == self._LEADER:
            value = self.fields[self._LEADER].value()
            for other_key in self._OTHERS:
                self.fields[other_key].setValue(value)
        self.changed.emit()

    def value(self) -> dict[str, int]:
        return {key: field.value() for key, field in self.fields.items()}

    def setValue(self, corners: dict):
        for key, field in self.fields.items():
            field.setValue(int(corners.get(key, field.value())))

    def setLinked(self, linked: bool):
        self._linked = linked
        if linked:
            value = self.fields[self._LEADER].value()
            for key in self._OTHERS:
                self.fields[key].setValue(value)
        for key in self._OTHERS:
            _set_dimmed(self.fields[key], linked)

    def setRadius(self, radius: int):
        for field in self.fields.values():
            field.setRadius(radius)

    def copyLeaderToOthers(self):
        value = self.fields[self._LEADER].value()
        for key in self._OTHERS:
            self.fields[key].setValue(value)
        self.changed.emit()

class _CornerRadiusField(QWidget):
    """Rayon des angles avec toggle "lie"/"libre" (voir _Toggle) + les 4
    sliders par coin (_CornerRadiusSliders) — "lie" : le coin Haut-Gauche
    pilote alors les 3 autres, exactement comme _CellPaddingField pour le
    padding des cellules — voir la remarque de l'utilisateur, "dans tous
    les parametres de coins arrondis, je veux exactement le meme
    fonctionnement que les padding (un par coin)"."""

    changed = Signal()

    def __init__(self, linked: bool, corners: dict, minimum: int = 0, maximum: int = 40, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        # GABARIT "coins arrondis" (voir _build_linked_sides_toggle) : pas
        # de bouton "Copier", toggle "lier les 4" AVANT le toggle.
        toggle_row, self.toggle = _build_linked_sides_toggle(linked)
        self.toggle.toggled.connect(self._on_toggled)
        layout.addWidget(toggle_row)
        self.sides = _CornerRadiusSliders(corners, minimum, maximum)
        self.sides.changed.connect(self.changed.emit)
        layout.addWidget(self.sides)
        self.sides.setLinked(linked)

    def _on_toggled(self, checked: bool):
        self.sides.setLinked(checked)
        self.changed.emit()

    def isLinked(self) -> bool:
        return self.toggle.isChecked()

    def cornersValue(self) -> dict[str, int]:
        return self.sides.value()

    def setValue(self, linked: bool, corners: dict):
        self.toggle.setChecked(linked)
        self.sides.setValue(corners)
        self.sides.setLinked(linked)

    def setRadius(self, radius: int):
        self.sides.setRadius(radius)

class _HeaderColorField(QWidget):
    """Ligne cliquable (pastille + libelle + chevron) ouvrant un QMenu sur
    les 8 pastilles semantiques + "Personnalisee..." tout en bas (ouvre
    alors le popup HSL/RVB/hex habituel, voir _ColorPickerPopup) — une
    boite hex a droite en lecture seule affiche toujours la couleur
    resolue, quel que soit le mode — voir la remarque de l'utilisateur,
    "je veux pouvoir personnaliser la couleur" (deja possible cote
    bordures de Toggles/Sliders, voir _AppOrCustomColorField ; meme choix
    ici, transpose a ce widget bouton+chevron plutot qu'une simple
    pastille).

    Valeur stockee (voir value()/setValue()) : un nom de pastille
    semantique (INCHANGE par rapport a avant, seul format possible
    jusqu'ici — retro-compatible) OU une chaine hex "#rrggbb" (couleur
    personnalisee, nouveau) — un nom de pastille ne commence jamais par
    "#", ce prefixe suffit donc a distinguer les 2 sans marqueur dedie."""

    changed = Signal(str)

    def __init__(self, colors: dict, current_value: str, parent=None):
        super().__init__(parent)
        self._colors = colors
        self._value = current_value if (current_value in _SLOT_LABELS or current_value.startswith("#")) else "skinN1"
        self._radius = _input_radius()
        _register_input(self)
        self._before_pick = self._value
        self._popup: _ColorPickerPopup | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # GABARIT "couleur" (voir _AppOrCustomColorField, MEME mecanique —
        # seul le format de valeur differe ici : un nom de slot NU, pas
        # "@<slot>", voir la remarque de tete de classe).
        self._slot_options = sorted(SEMANTIC_COLOR_SLOTS, key=lambda t: t[2])
        self._slot_to_label = {slot: label for slot, _real, label in self._slot_options}
        self._label_to_slot = {label: slot for slot, _real, label in self._slot_options}
        labels = [label for _slot, _real, label in self._slot_options]

        is_custom = self._is_custom()

        app_label = QLabel("Couleur application")
        _set_text_role(app_label, "choice_label")
        layout.addWidget(app_label)
        self.app_toggle = _Toggle(not is_custom, show_label=False)
        layout.addWidget(self.app_toggle)
        current_label = self._slot_to_label.get(self._value, labels[0]) if not is_custom else labels[0]
        self.app_field = _SelectField(labels, current_label, width=170)
        layout.addWidget(self.app_field)

        system_label = QLabel("Couleur systeme")
        _set_text_role(system_label, "choice_label")
        layout.addWidget(system_label)
        self.system_toggle = _Toggle(is_custom, show_label=False)
        layout.addWidget(self.system_toggle)
        self.swatch = _ColorSwatchButton()
        self.swatch.setFixedSize(24, 24)
        self.swatch.clicked.connect(self._open_custom_picker)
        layout.addWidget(self.swatch)

        self.hex_box = hex_box = QWidget()
        hex_box.setObjectName("HeaderHexBox")
        hex_box.setAttribute(Qt.WA_StyledBackground, True)
        hex_box.setFixedSize(68, 25)
        hex_l = QHBoxLayout(hex_box)
        hex_l.setContentsMargins(7, 0, 7, 0)
        self.hex_label = QLabel()
        _set_text_role(self.hex_label, "value_muted_mono")
        self.hex_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hex_l.addWidget(self.hex_label)
        layout.addWidget(hex_box)

        self.app_toggle.toggled.connect(self._on_app_toggled)
        self.system_toggle.toggled.connect(self._on_system_toggled)
        self.app_field.changed.connect(self._on_app_field_changed)
        self._refresh_style()
        self._refresh_dim()
        self._refresh()

    def _is_custom(self) -> bool:
        return self._value.startswith("#")

    def _current_hex(self) -> str:
        if self._is_custom():
            return self._value
        return self._colors.get(_SLOT_REAL.get(self._value, "chrome"), "#000000")

    def _refresh_style(self):
        """Habillage (fond/bordure/coins) de la boite hex — a part de
        _refresh (contenu : couleur/valeur), pour pouvoir suivre le slider
        Zones de saisie sans redemander la couleur courante (voir
        setRadius)."""
        self.hex_box.setStyleSheet(
            f"#HeaderHexBox {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; }}"
        )

    def setRadius(self, radius: int):
        self._radius = max(0, int(radius))
        self._refresh_style()
        self.app_field.setRadius(radius)

    def _refresh_dim(self):
        _set_dimmed(self.app_field, not self.app_toggle.isChecked())
        _set_dimmed(self.swatch, not self.system_toggle.isChecked())

    def _refresh(self):
        hexval = self._current_hex()
        self.swatch.setColorHex(hexval)
        self.hex_label.setText(hexval)

    def _on_app_toggled(self, checked: bool):
        if checked:
            self.system_toggle.blockSignals(True)
            self.system_toggle.setChecked(False)
            self.system_toggle.blockSignals(False)
        elif not self.system_toggle.isChecked():
            self.system_toggle.blockSignals(True)
            self.system_toggle.setChecked(True)
            self.system_toggle.blockSignals(False)
        self._refresh_dim()
        if checked:
            self._select(self._label_to_slot[self.app_field.value()])
        else:
            self.changed.emit(self._value)

    def _on_system_toggled(self, checked: bool):
        if checked:
            self.app_toggle.blockSignals(True)
            self.app_toggle.setChecked(False)
            self.app_toggle.blockSignals(False)
            if not self._is_custom():
                self._value = self._current_hex()
                self._refresh()
        elif not self.app_toggle.isChecked():
            self.app_toggle.blockSignals(True)
            self.app_toggle.setChecked(True)
            self.app_toggle.blockSignals(False)
        self._refresh_dim()
        self.changed.emit(self._value)

    def _on_app_field_changed(self, label: str):
        if self.app_toggle.isChecked():
            self._select(self._label_to_slot[label])

    def _select(self, slot: str):
        if slot != self._value:
            self._value = slot
            self._refresh()
            self.changed.emit(slot)

    def _open_custom_picker(self):
        if not self.system_toggle.isChecked():
            return
        self._before_pick = self._value
        popup = _ColorPickerPopup(self._current_hex(), "Couleur", self)
        self._popup = popup
        popup.colorChanged.connect(self._apply_custom_live)
        popup.committed.connect(self._apply_custom_live)
        popup.cancelled.connect(lambda: self._apply_custom_live(self._before_pick))
        popup.show_near(self.swatch)

    def _apply_custom_live(self, value: str):
        self._value = value
        self._refresh()
        self.changed.emit(self._value)

    def value(self) -> str:
        return self._value

    def refresh_colors(self, colors: dict):
        """A appeler quand la page Couleurs a change une valeur — la
        pastille choisie ici doit suivre (voir SettingsWindow._on_colors_changed)."""
        self._colors = colors
        self._refresh()

    def setValue(self, value: str, colors: dict):
        """Reapplique a la fois la valeur (slot OU hex personnalise) ET la
        palette source — utilise par Valeurs par defaut / chargement d'un
        preset (voir SettingsWindow._apply_values_to_controls), qui
        doivent pouvoir changer les deux d'un coup sans emettre `changed` a
        chaque etape intermediaire."""
        self._value = value if (value in _SLOT_LABELS or value.startswith("#")) else "skinN1"
        self._colors = colors
        is_custom = self._is_custom()
        self.app_toggle.blockSignals(True)
        self.system_toggle.blockSignals(True)
        self.app_toggle.setChecked(not is_custom)
        self.system_toggle.setChecked(is_custom)
        self.app_toggle.blockSignals(False)
        self.system_toggle.blockSignals(False)
        if not is_custom and self._value in self._slot_to_label:
            self.app_field.setValue(self._slot_to_label[self._value])
        self._refresh_dim()
        self._refresh()

def _solid_icon(hex_value: str):
    from PySide6.QtGui import QIcon, QPixmap
    pix = QPixmap(14, 14)
    pix.fill(QColor(hex_value))
    return QIcon(pix)

class _EdgeBar(QWidget):
    """Un des 4 filets cliquables de _EdgeBox (haut/droite/bas/gauche)."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._on = False
        self.setCursor(Qt.PointingHandCursor)

    def setOn(self, on: bool):
        if on != self._on:
            self._on = on
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(M["accent"] if self._on else M["edge_off"]))
        p.end()

class _EdgeBox(QWidget):
    """Rectangle en pointilles (92x52) representant l'entete, avec ses 4
    cotes cliquables — voir _HeaderEdgesField pour la synchronisation avec
    la liste de cases a cocher juxtaposee."""

    changed = Signal(str)   # emet le cote qui vient de changer

    def __init__(self, edges: dict, parent=None):
        super().__init__(parent)
        self.setFixedSize(92, 52)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._refresh_style()
        label = QLabel("entete", self)
        _set_text_role(label, "edge_hint")
        label.adjustSize()
        label.move((92 - label.width()) // 2, (52 - label.height()) // 2)
        self.bars: dict[str, _EdgeBar] = {}
        for name in ("top", "right", "bottom", "left"):
            bar = _EdgeBar(self)
            bar.setOn(bool(edges.get(name, False)))
            bar.clicked.connect(lambda n=name: self._toggle(n))
            self.bars[name] = bar
        self.bars["top"].setGeometry(0, 0, 92, 3)
        self.bars["bottom"].setGeometry(0, 49, 92, 3)
        self.bars["left"].setGeometry(0, 0, 3, 52)
        self.bars["right"].setGeometry(89, 0, 3, 52)

    def _refresh_style(self):
        self.setStyleSheet(f"background: {M['field_bg']}; border: 1px dashed {M['panel_border']};")

    def _toggle(self, name: str):
        bar = self.bars[name]
        bar.setOn(not bar._on)
        self.changed.emit(name)

    def value(self) -> dict[str, bool]:
        return {name: bar._on for name, bar in self.bars.items()}

    def setValue(self, edges: dict):
        for name, bar in self.bars.items():
            bar.setOn(bool(edges.get(name, False)))

    def refresh_colors(self):
        self._refresh_style()

class _EdgeCheckItem(QWidget):
    """Une ligne de la liste 2x2 (case + libelle) — toute la ligne est
    cliquable, pas seulement la case (voir _CheckSquare.WA_TransparentFor
    MouseEvents : la case est purement decorative ici)."""

    clicked = Signal()

    def __init__(self, label: str, on: bool, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.box = _CheckSquare(on)
        layout.addWidget(self.box)
        self.text = QLabel(label)
        self.text.setFont(_qfont(11, 400))
        layout.addWidget(self.text, 1)
        self._refresh_label(on)

    def _refresh_label(self, on: bool):
        self.text.setStyleSheet(f"color: {M['row_label'] if on else M['row_label_off']}; background: transparent;")

    def setOn(self, on: bool):
        self.box.setChecked(on)
        self._refresh_label(on)

    def isOn(self) -> bool:
        return self.box.isChecked()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

class _HeaderEdgesField(QWidget):
    """Boite a cotes cliquables + liste de cases 2x2, synchronisees dans
    les deux sens (cliquer un cote de la boite coche/decoche la case
    correspondante, et inversement)."""

    changed = Signal()

    _ORDER = [("top", "Haut"), ("right", "Droite"), ("bottom", "Bas"), ("left", "Gauche")]

    def __init__(self, edges: dict, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.box = _EdgeBox(edges)
        self.box.changed.connect(self._on_box_toggled)
        layout.addWidget(self.box)

        grid_wrap = QWidget()
        grid = QGridLayout(grid_wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(5)
        self.items: dict[str, _EdgeCheckItem] = {}
        for i, (key, label) in enumerate(self._ORDER):
            item = _EdgeCheckItem(label, bool(edges.get(key, False)))
            item.clicked.connect(lambda k=key: self._toggle(k))
            self.items[key] = item
            row, col = divmod(i, 2)
            grid.addWidget(item, row, col)
        layout.addWidget(grid_wrap, 1)

    def _toggle(self, key: str):
        item = self.items[key]
        new_on = not item.isOn()
        item.setOn(new_on)
        self.box.bars[key].setOn(new_on)
        self.changed.emit()

    def _on_box_toggled(self, key: str):
        """Clic direct sur un cote de la boite (plutot que sur la ligne de
        la liste) : repercute l'etat du filet sur la case correspondante."""
        self.items[key].setOn(self.box.bars[key]._on)
        self.changed.emit()

    def value(self) -> dict[str, bool]:
        return {key: item.isOn() for key, item in self.items.items()}

    def setValue(self, edges: dict):
        self.box.setValue(edges)
        for key, item in self.items.items():
            item.setOn(bool(edges.get(key, False)))

    def refresh_colors(self):
        self.box.refresh_colors()

class _CompactAppOrCustomColorField(QWidget):
    """Variante COMPACTE de _AppOrCustomColorField, pour tenir DANS une
    ligne "police" deja chargee (voir _build_font_gabarit_row et la
    remarque de l'utilisateur, capture d'ecran a l'appui, "voici a quoi
    doit ressembler la ligne police") : UNE seule pastille (pas de liste
    deroulante, trop large ici) dont le CLIC ouvre le menu des pastilles
    semantiques quand "app" est actif, ou directement le popup HSL/RVB/hex
    quand "sys" est actif — libelles courts "app"/"sys" (pas "Couleur
    application"/"Couleur systeme", trop long sur cette ligne), toggles
    SANS libelle integre, places AVANT chacun. Meme format de valeur que
    _AppOrCustomColorField ("#rrggbb" ou "@<slot>")."""

    changed = Signal(str)

    def __init__(self, value: str, colors: dict, swatch_size: int = 20, title: str = "Couleur", parent=None):
        super().__init__(parent)
        self._value = value
        self._colors = colors
        self._title = title
        self._before_pick = value
        self._popup: _ColorPickerPopup | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Libelle CENTRE AU-DESSUS de son toggle (voir la remarque de
        # l'utilisateur, "pour les toggle de couleur, place leur texte
        # correspondant bien centre au dessus du toggle") — remplace
        # l'ancien libelle "avant" le toggle sur la meme ligne.
        is_slot = value.startswith("@")
        app_stack = QWidget()
        app_stack.setStyleSheet("background: transparent;")
        app_stack_l = QVBoxLayout(app_stack)
        app_stack_l.setContentsMargins(0, 0, 0, 0)
        app_stack_l.setSpacing(2)
        app_label = QLabel("app")
        _set_text_role(app_label, "mini_label")
        app_label.setAlignment(Qt.AlignHCenter)
        app_stack_l.addWidget(app_label)
        self.app_toggle = _Toggle(is_slot, show_label=False)
        app_stack_l.addWidget(self.app_toggle, 0, Qt.AlignHCenter)
        layout.addWidget(app_stack)

        self.swatch = _ColorSwatchButton()
        self.swatch.setFixedSize(swatch_size, swatch_size)
        self.swatch.clicked.connect(self._on_swatch_clicked)
        layout.addWidget(self.swatch)

        sys_stack = QWidget()
        sys_stack.setStyleSheet("background: transparent;")
        sys_stack_l = QVBoxLayout(sys_stack)
        sys_stack_l.setContentsMargins(0, 0, 0, 0)
        sys_stack_l.setSpacing(2)
        sys_label = QLabel("sys")
        _set_text_role(sys_label, "mini_label")
        sys_label.setAlignment(Qt.AlignHCenter)
        sys_stack_l.addWidget(sys_label)
        self.system_toggle = _Toggle(not is_slot, show_label=False)
        sys_stack_l.addWidget(self.system_toggle, 0, Qt.AlignHCenter)
        layout.addWidget(sys_stack)

        self.app_toggle.toggled.connect(self._on_app_toggled)
        self.system_toggle.toggled.connect(self._on_system_toggled)
        self._refresh()

    def _is_slot(self) -> bool:
        return self._value.startswith("@")

    def _resolved_hex(self) -> str:
        return _resolve_color_value(self._value, self._colors)

    def _refresh(self):
        hexval = self._resolved_hex()
        self.swatch.setColorHex(hexval)
        self.swatch.setToolTip(_SLOT_LABELS.get(self._value[1:], hexval) if self._is_slot() else hexval)

    def _on_app_toggled(self, checked: bool):
        if checked:
            self.system_toggle.blockSignals(True)
            self.system_toggle.setChecked(False)
            self.system_toggle.blockSignals(False)
            if not self._is_slot():
                # Bascule vers "app" depuis une couleur personnalisee (voir
                # la remarque de l'utilisateur, "les couleurs applications
                # ne fonctionnent pas") : sans ceci, la valeur restait
                # figee sur l'ancien hex personnalise jusqu'a un clic
                # SUPPLEMENTAIRE sur la pastille — bascule desormais tout
                # de suite sur une pastille semantique par defaut (la 1ere
                # par ordre alphabetique, MEME liste que _open_menu).
                default_slot = sorted(SEMANTIC_COLOR_SLOTS, key=lambda t: t[2])[0][0]
                self._select_slot(default_slot)
        elif not self.system_toggle.isChecked():
            self.system_toggle.blockSignals(True)
            self.system_toggle.setChecked(True)
            self.system_toggle.blockSignals(False)

    def _on_system_toggled(self, checked: bool):
        if checked:
            self.app_toggle.blockSignals(True)
            self.app_toggle.setChecked(False)
            self.app_toggle.blockSignals(False)
            if self._is_slot():
                self._value = self._resolved_hex()
                self._refresh()
                self.changed.emit(self._value)
        elif not self.app_toggle.isChecked():
            self.app_toggle.blockSignals(True)
            self.app_toggle.setChecked(True)
            self.app_toggle.blockSignals(False)

    def _on_swatch_clicked(self):
        if self.app_toggle.isChecked():
            self._open_menu()
        else:
            self._open_custom_picker()

    def _open_menu(self):
        menu = QMenu(self)
        menu.setFont(_qfont(11, 400))
        menu.setStyleSheet(
            f"QMenu {{ background: {M['toolbar_bg']}; border: 1px solid {M['field_border']}; padding: 4px 0; }}"
            f"QMenu::item {{ padding: 5px 16px; color: {M['value_fg']}; }}"
            f"QMenu::item:selected {{ background: {M['accent']}; color: {M['accent_fg']}; }}"
        )
        for slot, real, label in sorted(SEMANTIC_COLOR_SLOTS, key=lambda t: t[2]):
            action = menu.addAction(_solid_icon(self._colors.get(real, "#000")), label)
            action.triggered.connect(lambda _c=False, s=slot: self._select_slot(s))
        menu.exec(self.swatch.mapToGlobal(QPoint(0, self.swatch.height())))

    def _select_slot(self, slot: str):
        self._value = f"@{slot}"
        self._refresh()
        self.changed.emit(self._value)

    def _open_custom_picker(self):
        self._before_pick = self._value
        popup = _ColorPickerPopup(self._resolved_hex(), self._title, self)
        self._popup = popup
        popup.colorChanged.connect(self._apply_custom_live)
        popup.committed.connect(self._apply_custom_live)
        popup.cancelled.connect(lambda: self._apply_custom_live(self._before_pick))
        popup.show_near(self.swatch)

    def _apply_custom_live(self, value: str):
        self._value = value
        self._refresh()
        self.changed.emit(self._value)

    def value(self) -> str:
        return self._value

    def setValue(self, value: str):
        self._value = value
        is_slot = value.startswith("@")
        self.app_toggle.blockSignals(True)
        self.system_toggle.blockSignals(True)
        self.app_toggle.setChecked(is_slot)
        self.system_toggle.setChecked(not is_slot)
        self.app_toggle.blockSignals(False)
        self.system_toggle.blockSignals(False)
        self._refresh()

    def refresh_colors(self, colors: dict):
        self._colors = colors
        self._refresh()

class _SideColorsField(QWidget):
    """4 pastilles de couleur cote a cote (Gauche/Haut/Bas/Droite — meme
    ordre, pour la meme raison, que _SidePaddingField, voir sa remarque de
    tete de classe) — utilise pour la bordure du selecteur de slider (voir
    Geometrie > Slider), des lignes "Bordure" de Toggles > Cadre/Coche ET
    de Colonnes > Bordure, qui ont besoin d'une couleur INDEPENDANTE par
    cote (contrairement a _HeaderEdgesField ci-dessus, une seule couleur
    partagee + un simple on/off par cote).

    Chaque cote a aussi son PROPRE interrupteur actif/inactif — un vrai
    _Toggle (MEME widget que partout ailleurs dans cette fenetre, voir
    enabledValue/setEnabledValue), pas une case a cocher a part : voir la
    remarque de l'utilisateur, "les toggles que tu as mis en place doivent
    etre du type de ceux de la fenetre de settings" (corrige une 1ere
    version qui utilisait une petite case dediee, _SideEnableCheck,
    abandonnee). Remplace l'ancien interrupteur global unique de
    _ToggleSideColorsField, voir la remarque de l'utilisateur, "au lieu
    d'avoir un seul toggle pour activer les bordures, je veux un toggle
    par cote" : un cote desactive grise sa pastille (non cliquable, meme
    mecanique que l'ancien setLocked, mais desormais PAR cote plutot que
    global).

    Le 1er cote de _ORDER (_LEADER) peut piloter les 3 autres — COULEUR ET
    interrupteur actif/inactif — lien PERMANENT (voir setLinked) ou
    transfert PONCTUEL (voir copyLeaderToOthers) — memes 2 mecaniques,
    memes raisons, que _SidePaddingField (voir sa remarque de tete de
    classe) : la aussi, reordonner _ORDER suffit a changer QUEL cote est
    le maitre. Lie, seul l'interrupteur du maitre reste cliquable, les 3
    autres suivent (voir _on_side_enabled_changed/la remarque de
    l'utilisateur, "quand les 4 cotes sont lies, et que l'on active la
    bordure du premier cote, les autres ne suivent pas").

    Chaque pastille est un _CompactAppOrCustomColorField (pas un simple
    _ColorField) : couleur PARMI les pastilles semantiques de l'appli OU
    personnalisee, MEME systeme compact ("app"/"sys" de part et d'autre de
    la pastille, texte centre AU-DESSUS de chaque toggle) que les lignes
    "police" — voir la remarque de l'utilisateur, "pour les lignes
    bordures, utilise le meme systeme que dans les textes pour le choix de
    la couleur"."""

    changed = Signal()

    _ORDER = [("left", "G"), ("top", "H"), ("bottom", "B"), ("right", "D")]
    _LEADER = _ORDER[0][0]
    _OTHERS = tuple(key for key, _label in _ORDER[1:])

    def __init__(self, sides: dict, colors: dict, enabled: dict | None = None, parent=None):
        super().__init__(parent)
        # Fond transparent EXPLICITE (self ET wrap ci-dessous) : meme piege/
        # correctif que _SidePaddingField (voir son commentaire) — sans lui,
        # ces QWidget nus se voient quand meme peints (le style sheet global
        # de l'appli active WA_StyledBackground implicitement sur tout
        # QWidget), masquant le fond alterne de la ligne de tableau
        # (table_row_a/table_row_b) sous les toggles/pastilles — voir la
        # remarque de l'utilisateur, "le fond des modificateur n'est pas le
        # fond des tableaux alors qu'il devraient l'etre".
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._linked = False
        enabled = enabled or {}
        self._enabled: dict[str, bool] = {key: bool(enabled.get(key, True)) for key, _ in self._ORDER}
        self.fields: dict[str, _CompactAppOrCustomColorField] = {}
        self.side_checks: dict[str, _Toggle] = {}
        for i, (key, letter) in enumerate(self._ORDER):
            if i > 0:
                # Ligne verticale entre chaque cote (voir la remarque de
                # l'utilisateur, "est il possible de rajouter une ligne
                # verticale qui separe les differents cote ? (de mm couleur
                # que les bordures)") — meme couleur que la bordure elle-
                # meme (M['field_border'], deja utilisee comme couleur de
                # bordure de champ ailleurs dans cette fenetre).
                sep = QFrame()
                sep.setFrameShape(QFrame.VLine)
                sep.setFixedWidth(1)
                sep.setStyleSheet(f"background: {M['field_border']}; border: none;")
                layout.addWidget(sep)
            wrap = QWidget()
            wrap.setStyleSheet("background: transparent;")
            wrap_l = QVBoxLayout(wrap)
            wrap_l.setContentsMargins(0, 0, 0, 0)
            wrap_l.setSpacing(3)
            wrap_l.setAlignment(Qt.AlignHCenter)
            check = _Toggle(self._enabled[key], style_override="toggle2", show_label=False)
            check.toggled.connect(lambda on, k=key: self._on_side_enabled_changed(k, on))
            self.side_checks[key] = check
            wrap_l.addWidget(check, 0, Qt.AlignHCenter)
            field = _CompactAppOrCustomColorField(
                sides.get(key, "#000000"), colors, swatch_size=20, title=f"Bordure {letter}")
            field.changed.connect(lambda _v, k=key: self._on_side_changed(k))
            self.fields[key] = field
            wrap_l.addWidget(field, 0, Qt.AlignHCenter)
            tag = QLabel(letter)
            _set_text_role(tag, "side_letter")
            tag.setAlignment(Qt.AlignHCenter)
            wrap_l.addWidget(tag)
            layout.addWidget(wrap)
        self._refresh_field_states()

    def _on_side_changed(self, key: str):
        # Voir _SidePaddingField._on_side_changed, meme mecanique : le
        # maitre (_LEADER) pilote les 3 autres tant que le lien est actif ;
        # les 3 autres sont de toute facon non cliquables pendant ce temps
        # (voir setLinked), ce cas ne peut donc survenir qu'en changeant le
        # maitre lui-meme.
        if self._linked and key == self._LEADER:
            value = self.fields[self._LEADER].value()
            for other_key in self._OTHERS:
                self.fields[other_key].setValue(value)
        self.changed.emit()

    def _on_side_enabled_changed(self, key: str, on: bool):
        # Voir _on_side_changed, meme mecanique : le maitre (_LEADER)
        # pilote aussi les 3 autres INTERRUPTEURS tant que le lien est
        # actif (pas seulement les couleurs, voir setLinked) — voir la
        # remarque de l'utilisateur, "quand les 4 cotes sont lies, et que
        # l'on active la bordure du premier cote, les autres ne suivent
        # pas". Les 3 autres sont de toute facon non cliquables pendant ce
        # temps (voir _refresh_field_states), ce cas ne peut donc survenir
        # qu'en changeant le maitre lui-meme.
        self._enabled[key] = bool(on)
        if self._linked and key == self._LEADER:
            for other_key in self._OTHERS:
                self._enabled[other_key] = self._enabled[key]
                self.side_checks[other_key].setChecked(self._enabled[key])
        self._refresh_field_states()
        self.changed.emit()

    def value(self) -> dict[str, str]:
        return {key: field.value() for key, field in self.fields.items()}

    def setValue(self, sides: dict):
        for key, field in self.fields.items():
            field.setValue(sides.get(key, field.value()))

    def enabledValue(self) -> dict[str, bool]:
        return dict(self._enabled)

    def setEnabledValue(self, enabled: dict):
        for key, check in self.side_checks.items():
            on = bool(enabled.get(key, self._enabled.get(key, True)))
            self._enabled[key] = on
            check.setChecked(on)
        self._refresh_field_states()

    def _refresh_field_states(self):
        """Une pastille est non cliquable/grisee si SON PROPRE cote est
        desactive (_enabled, voir side_checks) OU si le lien est actif et
        que ce n'est pas le maitre (_linked, voir setLinked) — le maitre,
        lui, reste toujours editable tant que SON PROPRE cote est actif,
        lien ou pas (voir _CellPaddingField, meme principe transpose des
        valeurs px aux couleurs). Meme chose pour l'interrupteur actif/
        inactif de chaque cote (voir side_checks) : lie, seul celui du
        maitre reste cliquable, les 3 autres suivent (voir
        _on_side_enabled_changed)."""
        for key, field in self.fields.items():
            locked = not self._enabled.get(key, True) or (self._linked and key != self._LEADER)
            _set_dimmed(field, locked)
        for key, check in self.side_checks.items():
            lock_toggle = self._linked and key != self._LEADER
            _set_dimmed(check, lock_toggle)

    def setLinked(self, linked: bool):
        """Voir _SidePaddingField.setLinked, meme mecanique (le maitre
        pilote les 3 autres, resynchronises TOUT DE SUITE dessus des
        l'activation du lien) — COULEUR ET interrupteur actif/inactif du
        maitre (voir _on_side_enabled_changed/la remarque de l'utilisateur,
        "quand les 4 cotes sont lies, et que l'on active la bordure du
        premier cote, les autres ne suivent pas")."""
        self._linked = linked
        if linked:
            value = self.fields[self._LEADER].value()
            enabled = self._enabled[self._LEADER]
            for key in self._OTHERS:
                self.fields[key].setValue(value)
                self._enabled[key] = enabled
                self.side_checks[key].setChecked(enabled)
        self._refresh_field_states()

    def copyLeaderToOthers(self):
        """Voir _SidePaddingField.copyLeaderToOthers, meme mecanique :
        transfert PONCTUEL, sans activer le lien permanent. COULEUR ET
        interrupteur actif/inactif du maitre (voir _on_side_enabled_changed)
        — voir la remarque de l'utilisateur, "je veux que copier G concerne
        aussi les toggle d'activation" (contrairement au lien "lie"/"libre"
        permanent, qui reste lui COULEUR uniquement, voir setLinked)."""
        value = self.fields[self._LEADER].value()
        enabled = self._enabled[self._LEADER]
        for key in self._OTHERS:
            self.fields[key].setValue(value)
            self._enabled[key] = enabled
            self.side_checks[key].setChecked(enabled)
        self._refresh_field_states()
        self.changed.emit()

    def refresh_colors(self, colors: dict):
        """Voir _AppOrCustomColorField.refresh_colors, meme raison —
        rappele sur les 4 pastilles a la fois."""
        for field in self.fields.values():
            field.refresh_colors(colors)

class _ToggleSideColorsField(QWidget):
    """Bordure, avec un interrupteur INDEPENDANT par cote (un vrai _Toggle
    par cote, voir _SideColorsField.side_checks — remplace l'ancien
    interrupteur global unique, voir la remarque de l'utilisateur, "au
    lieu d'avoir un seul toggle pour activer les bordures, je veux un
    toggle par cote") + un toggle "lie"/"libre" + bouton "Copier" (voir
    _SideColorsField.setLinked/copyLeaderToOthers, memes 2 mecaniques que
    _CellPaddingField pour le padding, transposees aux couleurs — voir la
    remarque de l'utilisateur) + ses 4 couleurs par cote (_SideColorsField)
    — un cote desactive grise sa propre pastille (voir _SideColorsField.
    _refresh_field_states), independamment des 3 autres."""

    changed = Signal()

    def __init__(self, enabled: dict, sides: dict, colors: dict, parent=None,
                 thickness_field: QWidget | None = None, thickness_label: str = "Epaisseur"):
        super().__init__(parent)
        # Fond transparent EXPLICITE : meme piege/correctif que
        # _SideColorsField ci-dessus (voir son commentaire) — voir la
        # remarque de l'utilisateur, "le fond des modificateur n'est pas le
        # fond des tableaux alors qu'il devraient l'etre".
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        # GABARIT "bordures" (voir _build_linked_sides_toggle) : pas de
        # bouton "Copier", toggle "lier les 4" AVANT le toggle.
        toggle_row, self.link_toggle = _build_linked_sides_toggle(False)
        self.link_toggle.toggled.connect(self._on_link_toggled)
        layout.addWidget(toggle_row)
        self.sides = _SideColorsField(sides, colors, enabled)
        self.sides.changed.connect(self.changed.emit)
        layout.addWidget(self.sides)
        # Epaisseur DESORMAIS DANS LA MEME ligne (voir la remarque de
        # l'utilisateur, "un slider Epaisseur, avec texte 'Epaisseur' juste
        # avant, et une invite de texte juste apres, indiquant en temps reel
        # l'epaisseur en px") — le champ (_SliderField, deja construit par
        # l'appelant, MEME attribut `self.xxx_border_thickness_field`
        # partout ailleurs dans cette fenetre) est simplement DEPLACE ici,
        # jamais recree : _current_values/_apply_values_to_controls/
        # _apply_dropdown_radius continuent de le lire/l'ecrire SANS
        # changement. `thickness_field=None` (repli) : garde l'ancien
        # comportement (ligne separee, geree par l'appelant) pour tout site
        # pas encore migre.
        self.thickness_field = thickness_field
        if thickness_field is not None:
            thickness_label_w = QLabel(thickness_label)
            _set_text_role(thickness_label_w, "inline_label")
            layout.addWidget(thickness_label_w)
            layout.addWidget(thickness_field)
        layout.addStretch(1)

    def _on_link_toggled(self, checked: bool):
        self.sides.setLinked(checked)
        self.changed.emit()

    def sidesValue(self) -> dict[str, str]:
        return self.sides.value()

    def sidesEnabledValue(self) -> dict[str, bool]:
        return self.sides.enabledValue()

    def setValue(self, enabled: dict, sides: dict):
        self.sides.setValue(sides)
        self.sides.setEnabledValue(enabled)

    def setRadius(self, radius: int):
        if self.thickness_field is not None:
            self.thickness_field.setRadius(radius)

    def refresh_colors(self, colors: dict):
        """Voir _SideColorsField.refresh_colors, meme raison."""
        self.sides.refresh_colors(colors)

class _SidePaddingField(QWidget):
    """4 sliders cote a cote (Gauche/Haut/Bas/Droite — voir la remarque de
    l'utilisateur pour cet ordre precis, DIFFERENT de celui de
    _SideColorsField/_HeaderEdgesField ; meme disposition — tag au-dessus,
    controle en dessous) : un slider de valeur px par cote, pour le padding
    du texte des cellules de tableau (voir _CellPaddingField).

    Le 1er cote de _ORDER (pas force "top") pilote les 3 autres quand le
    lien est actif (voir setLinked) — c'est lui que _CellPaddingField
    propose de recopier sur les 3 autres (bouton "Copier"), voir
    copyLeaderToOthers : reordonner _ORDER suffit donc a changer QUEL cote
    est le "maitre", pas seulement l'ordre d'affichage."""

    changed = Signal()

    # Ordre PAR DEFAUT (4 cotes) — `order` (voir __init__) permet de n'en
    # afficher qu'un SOUS-ENSEMBLE (ex. Colonnes > Apercu > Zone titre,
    # "Titre - padding"/"Apercu des dossiers - padding" : voir la remarque
    # de l'utilisateur, "titre - padding : supprime padding D" / "apercu
    # des dossiers - padding : supprime padding G et B").
    _ORDER = [("left", "G"), ("top", "H"), ("bottom", "B"), ("right", "D")]
    _LEADER = _ORDER[0][0]
    _OTHERS = tuple(key for key, _label in _ORDER[1:])

    def __init__(self, sides: dict, minimum: int = 0, maximum: int = 32,
                 order: list[tuple[str, str]] | None = None, parent=None):
        super().__init__(parent)
        self._order = list(order) if order is not None else list(self._ORDER)
        self._leader = self._order[0][0]
        self._others = tuple(key for key, _label in self._order[1:])
        # Fond transparent EXPLICITE (self ET wrap ci-dessous) : meme piege/
        # correctif que _table_cell (voir son commentaire) — sans lui, ce
        # QWidget nu se voit quand meme peint (le style sheet global de
        # l'appli active WA_StyledBackground implicitement sur tout
        # QWidget), masquant le fond alterne de la ligne de tableau
        # (table_row_a/table_row_b) sous les sliders — voir la remarque de
        # l'utilisateur, capture a l'appui : "je veux la couleur fond
        # tableau" sous les sliders.
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._linked = False
        self.fields: dict[str, _SliderField] = {}
        for key, letter in self._order:
            wrap = QWidget()
            wrap.setStyleSheet("background: transparent;")
            wrap_l = QVBoxLayout(wrap)
            wrap_l.setContentsMargins(0, 0, 0, 0)
            wrap_l.setSpacing(3)
            tag = QLabel(letter)
            _set_text_role(tag, "side_letter")
            wrap_l.addWidget(tag)
            field = _SliderField(minimum, maximum, int(sides.get(key, 0)), slider_width=60, box_width=42)
            field.valueChanged.connect(lambda _v, k=key: self._on_side_changed(k))
            self.fields[key] = field
            wrap_l.addWidget(field)
            layout.addWidget(wrap)

    def _on_side_changed(self, key: str):
        # Le "maitre" (_LEADER, 1er cote de _ORDER) pilote les 3 autres
        # tant que le lien est actif (voir _CellPaddingField/setLinked) —
        # glisser un des 3 AUTRES ne fait rien ici : ils sont de toute
        # facon desactives par setLinked pendant que le lien est actif
        # (voir plus bas), ce cas ne peut donc survenir qu'en glissant le
        # maitre lui-meme.
        if self._linked and key == self._leader:
            value = self.fields[self._leader].value()
            for other_key in self._others:
                self.fields[other_key].setValue(value)
        self.changed.emit()

    def value(self) -> dict[str, int]:
        return {key: field.value() for key, field in self.fields.items()}

    def setValue(self, sides: dict):
        for key, field in self.fields.items():
            field.setValue(int(sides.get(key, field.value())))

    def setLinked(self, linked: bool):
        """Lien actif : le maitre (_leader) pilote les autres, qui
        deviennent non modifiables directement (meme correctif que
        _SideColorsField.setLocked — un simple setEnabled resterait
        invisible a l'oeil sans l'effet d'opacite, voir sa remarque de tete
        de methode) — et on resynchronise TOUT DE SUITE sur le maitre pour
        qu'un lien qu'on vient d'activer ne laisse pas les autres a une
        ancienne valeur divergente tant qu'on n'a pas retouche le maitre."""
        self._linked = linked
        if linked:
            value = self.fields[self._leader].value()
            for key in self._others:
                self.fields[key].setValue(value)
        for key in self._others:
            _set_dimmed(self.fields[key], linked)

    def setRadius(self, radius: int):
        for field in self.fields.values():
            field.setRadius(radius)

    def copyLeaderToOthers(self):
        """Bouton "Copier" de _CellPaddingField : transfert PONCTUEL du
        maitre (_LEADER, 1er cote de _ORDER) sur les 3 autres cotes, sans
        activer le lien permanent (voir setLinked) — contrairement au
        lien, les 3 autres restent ensuite modifiables independamment.
        Inutile (et le bouton reste desactive, voir _CellPaddingField.
        _on_toggled) tant que le lien est deja actif, les 3 autres suivant
        alors deja le maitre en direct — voir la remarque de l'utilisateur :
        "un petit bouton qui me permette de transferer la premiere valeur
        sur les trois autres"."""
        value = self.fields[self._leader].value()
        for key in self._others:
            self.fields[key].setValue(value)
        self.changed.emit()

class _CellPaddingField(QWidget):
    """Padding du texte a l'interieur des cellules de tableau — toggle
    "lie"/"libre" (voir _Toggle) + les 4 sliders par cote (_SidePaddingField)
    — "lie" : le slider "Haut" pilote alors les 3 autres cotes, exactement
    comme _ToggleSideColorsField ci-dessus pour la bordure du selecteur/du
    rail, meme mecanique transposee des couleurs aux valeurs px."""

    changed = Signal()

    def __init__(self, linked: bool, sides: dict, order: list[tuple[str, str]] | None = None, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")  # voir _SidePaddingField, meme correctif
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        # GABARIT "padding" (voir _build_linked_sides_toggle) : pas de
        # bouton "Copier", toggle "lier les 4" AVANT le toggle. `order`
        # (defaut : les 4 cotes, voir _SidePaddingField._ORDER) permet de
        # n'exposer qu'un SOUS-ENSEMBLE de cotes — voir Colonnes > Apercu >
        # Zone titre, "Titre - padding"/"Apercu des dossiers - padding".
        order = list(order) if order is not None else list(_SidePaddingField._ORDER)
        toggle_row, self.toggle = _build_linked_sides_toggle(linked)
        self.toggle.toggled.connect(self._on_toggled)
        layout.addWidget(toggle_row)
        self.sides = _SidePaddingField(sides, order=order)
        self.sides.changed.connect(self.changed.emit)
        layout.addWidget(self.sides)
        self.sides.setLinked(linked)

    def _on_toggled(self, checked: bool):
        self.sides.setLinked(checked)
        self.changed.emit()

    def isLinked(self) -> bool:
        return self.toggle.isChecked()

    def sidesValue(self) -> dict[str, int]:
        return self.sides.value()

    def setValue(self, linked: bool, sides: dict):
        self.toggle.setChecked(linked)
        self.sides.setValue(sides)
        self.sides.setLinked(linked)

    def setRadius(self, radius: int):
        self.sides.setRadius(radius)

# ==========================================================================
# Section "Geometrie" — table Element/Cadre/Coins arrondis, 2 lignes :
# Zones de saisie et Boutons (cadre actif/sans + rayon). "Fenetres" a
# demenage dans Application (voir _section_application, self.window_
# radius_toggle) — voir la remarque de l'utilisateur, "geometrie/fenetre :
# deplace cette ligne dans general/application mais transforme le slider
# en toggle".
# ==========================================================================

class _GeoTable(QWidget):
    changed = Signal()

    def __init__(self, input_frame: bool, input_radius: int,
                 button_frame: bool, button_radius: int,
                 column_widths: list[int] | None = None, parent=None):
        super().__init__(parent)
        self.frame_wrap = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame_wrap, layout = _table_frame()
        self.frame_wrap = frame_wrap
        self.head = _table_header([("Element", 0), ("Cadre", 150), ("Coins arrondis", 246)])
        layout.addWidget(self.head)

        self.input_frame_toggle = _Toggle(input_frame)
        self.input_radius_field = _SliderField(0, 16, input_radius, slider_width=140, box_width=58)
        self.button_frame_toggle = _Toggle(button_frame)
        self.button_radius_field = _SliderField(0, 16, button_radius, slider_width=140, box_width=58)

        # "Tableaux" deplace dans sa propre section (voir la remarque de
        # l'utilisateur, capture a l'appui) — voir SettingsWindow.
        # _section_tables/self.table_radius_field.
        rows = [
            ("Zones de saisie", self.input_frame_toggle, self.input_radius_field),
            ("Boutons", self.button_frame_toggle, self.button_radius_field),
        ]
        self._row_meta: list[tuple[QWidget, str, bool]] = []
        # Voir _SimpleFontTable._cells, meme raison (toutes les cellules,
        # pas seulement celles cablees au redimensionnement par colonne).
        self._cells: list[QWidget] = []
        column_cells: dict[int, list[QWidget]] = {}
        for i, (label, frame_toggle, radius_field) in enumerate(rows):
            bg = M["table_row_a"] if i % 2 else M["table_row_b"]
            row, row_l = _table_row(bg, first=(i == 0))
            self._row_meta.append((row, bg, i == 0))
            name = QLabel(label)
            _set_text_role(name, "row_label")
            self._cells.append(_table_cell(name, 0, row_l, center=True))
            if frame_toggle is not None:
                cell = _table_cell(frame_toggle, 150, row_l, center=True)
                frame_toggle.toggled.connect(lambda _c: self.changed.emit())
            else:
                dash = QLabel("—")
                _set_text_role(dash, "dash")
                cell = _table_cell(dash, 150, row_l, center=True)
            column_cells.setdefault(1, []).append(cell)
            self._cells.append(cell)
            cell = _table_cell(radius_field, 246, row_l, center=True)
            column_cells.setdefault(2, []).append(cell)
            self._cells.append(cell)
            radius_field.valueChanged.connect(lambda _v: self.changed.emit())
            _lock_min_height(row)
            layout.addWidget(row)
        _wire_resizable_columns(self.head, column_cells)
        # Largeurs sauvegardees (voir SettingsWindow._current_values, un
        # preset) — APRES le cablage ci-dessus, pas avant : setColumnWidths
        # emet resized par colonne, qui ne repercute sur les lignes que si
        # _wire_resizable_columns les a deja enregistrees (sinon l'entete
        # affiche la largeur sauvegardee mais les lignes restent a la
        # largeur par defaut).
        if column_widths:
            self.head.setColumnWidths(column_widths)

        outer.addWidget(frame_wrap)

    def value(self) -> dict[str, Any]:
        return {
            "input_frame": self.input_frame_toggle.isChecked(),
            "input_radius": self.input_radius_field.value(),
            "button_frame": self.button_frame_toggle.isChecked(),
            "button_radius": self.button_radius_field.value(),
        }

    def apply_radius(self, radius: int):
        """Voir _SimpleFontTable.apply_radius (meme logique : entete =
        coins hauts, derniere ligne = coins bas, `bg` recalculee a chaque
        appel, pas reprise de `_row_meta`)."""
        self.frame_wrap.setRadius(radius)
        _restyle_table_head(self.head, radius)
        last = len(self._row_meta) - 1
        new_meta = []
        for i, (row, _old_bg, first) in enumerate(self._row_meta):
            bg = M["table_row_a"] if i % 2 == 0 else M["table_row_b"]
            _restyle_table_row(row, bg, first, bottom_radius=(radius if i == last else 0))
            new_meta.append((row, bg, first))
        self._row_meta = new_meta

    def apply_border(self, enabled: dict, colors: dict, thickness: int):
        self.frame_wrap.setBorder(enabled, colors, thickness)

    def setCellPadding(self, sides: dict):
        """Voir _SimpleFontTable.setCellPadding, meme logique."""
        left, top = int(sides.get("left", 10)), int(sides.get("top", 0))
        right, bottom = int(sides.get("right", 10)), int(sides.get("bottom", 0))
        for cell in self._cells:
            cell.layout().setContentsMargins(left, top, right, bottom)
        for row, _bg, _first in self._row_meta:
            row.setMinimumHeight(0)
            _lock_min_height(row)
        self.head.setCellPadding(left, right)

class _TablePreview(QWidget):
    """Apercu de tableau (2 colonnes x 3 lignes, AVEC entete) pour Tableaux
    > l'apercu au-dessus de son tableau de reglages (voir
    _section_preview_wrap/SettingsWindow._section_tables) — contenu
    purement demonstratif (pas de vraies donnees), mais suit EN DIRECT les
    3 reglages de la section (Rayon des angles/Padding des cellules/
    Couleur d'en-tete, voir SettingsWindow._apply_table_radius/
    _apply_cell_padding/_apply_table_head_color, qui l'incluent desormais
    comme un 3e tableau a en-tete, au meme titre que Polices/Geometrie) —
    voir la remarque de l'utilisateur, "un tableau de 2 colonnes et 3
    lignes avec entete"."""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame, layout = _table_frame()
        self.head = _table_header([("Colonne A", 100), ("Colonne B", 100)])
        layout.addWidget(self.head)
        self._row_meta: list[tuple[QWidget, str, bool]] = []
        self._cells: list[QWidget] = []
        for i in range(3):
            bg = M["table_row_a"] if i % 2 else M["table_row_b"]
            row, row_l = _table_row(bg, first=(i == 0))
            self._row_meta.append((row, bg, i == 0))
            for col in (0, 1):
                value = QLabel(str(i * 2 + col + 1))
                _set_text_role(value, "value_muted_mono")
                self._cells.append(_table_cell(value, 100, row_l, center=True))
            _lock_min_height(row)
            layout.addWidget(row)
        outer.addWidget(self.frame)

    def apply_radius(self, radius: int):
        """Voir _SimpleFontTable.apply_radius, meme logique."""
        self.frame.setRadius(radius)
        _restyle_table_head(self.head, radius)
        last = len(self._row_meta) - 1
        new_meta = []
        for i, (row, _old_bg, first) in enumerate(self._row_meta):
            bg = M["table_row_a"] if i % 2 == 0 else M["table_row_b"]
            _restyle_table_row(row, bg, first, bottom_radius=(radius if i == last else 0))
            new_meta.append((row, bg, first))
        self._row_meta = new_meta

    def apply_border(self, enabled: dict, colors: dict, thickness: int):
        self.frame.setBorder(enabled, colors, thickness)

    def setCellPadding(self, sides: dict):
        """Voir _SimpleFontTable.setCellPadding, meme logique."""
        left, top = int(sides.get("left", 10)), int(sides.get("top", 0))
        right, bottom = int(sides.get("right", 10)), int(sides.get("bottom", 0))
        for cell in self._cells:
            cell.layout().setContentsMargins(left, top, right, bottom)
        for row, _bg, _first in self._row_meta:
            row.setMinimumHeight(0)
            _lock_min_height(row)
        self.head.setCellPadding(left, right)

class _HamburgerButton(QPushButton):
    """Bouton icone "liste de presets" — 3 barres dessinees au QPainter au
    lieu d'un glyphe unicode (le glyphe "hamburger" n'est pas garanti par
    toutes les polices systeme et rendait un carre vide a l'ecran)."""

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        color = self.palette().color(self.foregroundRole())
        painter.setPen(QPen(QColor(color), 1.4))
        w, h = self.width(), self.height()
        bar_w = 12
        x0 = (w - bar_w) / 2
        for i, dy in enumerate((-4, 0, 4)):
            y = h / 2 + dy
            painter.drawLine(int(x0), int(y), int(x0 + bar_w), int(y))
        painter.end()

class _DoubleClickBox(QWidget):
    """QWidget generique qui emet doubleClicked — utilise pour la boite de
    preset (double-clic pour renommer, voir SettingsWindow._build_toolbar)."""

    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

class _PresetListRow(QWidget):
    """Une ligne de la liste de presets (voir SettingsWindow.
    _open_preset_popup) : nom cliquable (charge ce preset) + croix a droite
    (le supprime) — toute la ligne HORS la croix reagit au clic, voir
    mousePressEvent."""

    clicked = Signal()
    deleteClicked = Signal()

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("PresetListRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(28)
        self.setStyleSheet(
            f"#PresetListRow {{ background: transparent; }}"
            f"#PresetListRow:hover {{ background: {M['btn_hover']}; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(8)
        label = QLabel(name)
        _set_text_role(label, "value")
        layout.addWidget(label, 1)
        del_btn = QPushButton("×")
        del_btn.setFlat(True)
        del_btn.setCursor(Qt.ArrowCursor)
        del_btn.setFocusPolicy(Qt.NoFocus)
        del_btn.setFixedSize(20, 20)
        del_btn.setFont(_qfont(13, 400, mono=True))
        del_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 0; color: " + M["close_fg"] + "; }"
            "QPushButton:hover { background: " + M["close_hover_bg"] + "; color: #ff8a80; }"
        )
        del_btn.clicked.connect(self.deleteClicked.emit)
        layout.addWidget(del_btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
