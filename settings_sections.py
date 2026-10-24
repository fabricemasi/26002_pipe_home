from PySide6.QtCore import (
    QEvent, QMimeData, QPoint, Qt, Signal,
)
from PySide6.QtGui import (
    QColor,
    QDrag,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from app_style import (
    SEMANTIC_COLOR_SLOTS,
    installed_font_families,
    join_color_ref,
    split_color_ref,
)
from settings_theme import _set_text_role
from settings_store import (
    M,
    _resolve_color_value,
)
from settings_widgets import (
    Menu, menu_row, _ColorPickerPopup, DRAG_GHOST_OPACITY, _ColorSwatchButton, _SLOT_LABELS, _SliderField,
    _Toggle, _set_dimmed,
)
from settings_layout import (
    _build_linked_sides_toggle,
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


# ==========================================================================
# Section "Couleurs" — grille 2 colonnes, 8 pastilles semantiques (voir
# app_style.SEMANTIC_COLOR_SLOTS). "Selection en cours" et "Bouton" pilotent
# la MEME cle reelle ("accent", voir la remarque dans app_style.py) : les
# deux pastilles restent donc synchronisees, un changement sur l'une se
# repercute immediatement sur l'autre — fidele au reste de l'appli, qui n'a
# qu'une seule couleur d'accent pour les deux roles.
# ==========================================================================


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


def _solid_icon(hex_value: str):
    from PySide6.QtGui import QIcon, QPixmap
    pix = QPixmap(14, 14)
    pix.fill(QColor(hex_value))
    return QIcon(pix)





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
        # "app" a GAUCHE de son toggle, tres rapproches.
        app_box = QWidget()
        app_box.setStyleSheet("background: transparent;")
        app_box_l = QHBoxLayout(app_box)
        app_box_l.setContentsMargins(0, 0, 0, 0)
        app_box_l.setSpacing(3)
        app_box_l.addStretch(1)               # « app » + toggle collés à la pastille (côté droit de leur boîte)
        app_label = QLabel("app")
        _set_text_role(app_label, "mini_label")
        app_label.setContentsMargins(0, 0, 0, 3)   # remonte le texte : aligne avec le centre du toggle
        app_box_l.addWidget(app_label)
        self.app_toggle = _Toggle(is_slot, show_label=False)
        app_box_l.addWidget(self.app_toggle)
        layout.addWidget(app_box)

        self.swatch = _ColorSwatchButton()
        self.swatch.setFixedSize(swatch_size, swatch_size)
        self.swatch.clicked.connect(self._on_swatch_clicked)
        # Glisser une pastille sur une autre = lui copier sa couleur (demande de l'utilisateur, tous les
        # tableaux) : voir eventFilter.
        self.swatch.setAcceptDrops(True)
        self.swatch.installEventFilter(self)
        self._drag_press = None
        layout.addWidget(self.swatch)

        # "sys" a DROITE de son toggle, tres rapproches.
        sys_box = QWidget()
        sys_box.setStyleSheet("background: transparent;")
        sys_box_l = QHBoxLayout(sys_box)
        sys_box_l.setContentsMargins(0, 0, 0, 0)
        sys_box_l.setSpacing(3)
        self.system_toggle = _Toggle(not is_slot, show_label=False)
        sys_box_l.addWidget(self.system_toggle)
        sys_label = QLabel("sys")
        _set_text_role(sys_label, "mini_label")
        sys_label.setContentsMargins(0, 0, 0, 3)   # remonte le texte : aligne avec le centre du toggle
        sys_box_l.addWidget(sys_label)
        sys_box_l.addStretch(1)
        layout.addWidget(sys_box)
        # Boîtes de même largeur : la pastille est au CENTRE du champ (donc alignée sur l'axe du
        # toggle de bordure placé au-dessus, voir _side_parts de settings_window_v2).
        side_width = max(app_box.sizeHint().width(), sys_box.sizeHint().width())
        app_box.setFixedWidth(side_width)
        sys_box.setFixedWidth(side_width)

        self.app_toggle.toggled.connect(self._on_app_toggled)
        self.system_toggle.toggled.connect(self._on_system_toggled)
        self._refresh()

    def _is_slot(self) -> bool:
        return self._value.startswith("@")

    def _resolved_hex(self) -> str:
        return _resolve_color_value(self._value, self._colors)

    def _slot_alpha(self) -> tuple[str, int]:
        """(pastille, opacite %) d'une valeur « @slot » ou « @slot/75 »."""
        ref, alpha = split_color_ref(self._value)
        return ref[1:], alpha

    def _refresh(self):
        hexval = self._resolved_hex()
        self.swatch.setColorHex(hexval)
        if self._is_slot():
            slot, alpha = self._slot_alpha()
            label = _SLOT_LABELS.get(slot, hexval)
            self.swatch.setToolTip(label if alpha >= 100 else f"{label} · {alpha} %")
        else:
            self.swatch.setToolTip(hexval)

    # "app" et "sys" sont exclusifs : cocher l'un OU decocher l'autre change
    # de mode, et la VALEUR suit toujours (decocher "app" laissait la valeur
    # sur la pastille alors que "sys" s'affichait coche).
    def _on_app_toggled(self, checked: bool):
        self._use_app() if checked else self._use_system()

    def _on_system_toggled(self, checked: bool):
        self._use_system() if checked else self._use_app()

    def _sync_mode_toggles(self, app: bool):
        for toggle, on in ((self.app_toggle, app), (self.system_toggle, not app)):
            toggle.blockSignals(True)
            toggle.setChecked(on)
            toggle.blockSignals(False)

    def _use_app(self):
        self._sync_mode_toggles(True)
        if not self._is_slot():
            # Retour a la derniere pastille choisie, sinon la 1ere par ordre
            # alphabetique (MEME liste que _open_menu).
            self._last_custom = self._value
            slot = getattr(self, "_last_slot", None) or sorted(SEMANTIC_COLOR_SLOTS, key=lambda t: t[2])[0][0]
            # L'opacite de la couleur quittee est gardee : une couleur transparente ne devient pas opaque
            # (un aller-retour « app » / « sys » faisait passer un fond transparent au noir).
            alpha = round(QColor(self._last_custom).alpha() * 100 / 255) if QColor(self._last_custom).isValid() else 100
            self._value = join_color_ref(f"@{slot}", alpha)
            self._refresh()
            self.changed.emit(self._value)

    def _use_system(self):
        self._sync_mode_toggles(False)
        if self._is_slot():
            # Retour a la derniere couleur personnalisee, sinon la couleur de la pastille.
            self._last_slot = self._slot_alpha()[0]
            self._value = getattr(self, "_last_custom", None) or self._resolved_hex()
            self._refresh()
            self.changed.emit(self._value)

    def _on_swatch_clicked(self):
        if self.app_toggle.isChecked():
            self._open_menu()
        else:
            self._open_custom_picker()

    def _open_menu(self):
        # Menu contextuel de l'appli (habillage des reglages) : opacite de la couleur choisie (demande de
        # l'utilisateur : transparence sur une couleur de l'appli, partout), puis les pastilles.
        menu = Menu(self)
        alpha = self._slot_alpha()[1] if self._is_slot() else 100
        field = _SliderField(0, 100, alpha, unit="%")
        field.valueChanged.connect(self._set_alpha)
        menu_row(menu, "Opacité", field)
        menu.addSeparator()
        for slot, real, label in sorted(SEMANTIC_COLOR_SLOTS, key=lambda t: t[2]):
            action = menu.addAction(_solid_icon(self._colors.get(real, "#000")), label)
            action.triggered.connect(lambda _c=False, s=slot: self._select_slot(s))
        menu.exec(self.swatch.mapToGlobal(QPoint(0, self.swatch.height())))

    def _set_alpha(self, alpha: int):
        if not self._is_slot():
            return
        slot = self._slot_alpha()[0]
        self._value = join_color_ref(f"@{slot}", alpha)
        self._refresh()
        self.changed.emit(self._value)

    def _select_slot(self, slot: str):
        # L'opacite choisie est gardee quand on change de pastille.
        alpha = self._slot_alpha()[1] if self._is_slot() else 100
        self._value = join_color_ref(f"@{slot}", alpha)
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

    # -- glisser une couleur sur une autre : copie de la valeur (pastille de l'appli + opacite, ou couleur
    # personnalisee) ; la pastille tiree suit le curseur a DRAG_GHOST_OPACITY, la pastille visee s'entoure
    # de l'accent. Sans Ctrl : ce n'est pas un deplacement, le clic garde son sens (menu / selecteur). --

    MIME = "application/x-pipeline-color"

    def eventFilter(self, obj, event):
        if obj is not self.swatch:
            return super().eventFilter(obj, event)
        kind = event.type()
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._drag_press = event.position().toPoint()
        elif kind == QEvent.MouseMove and self._drag_press is not None and event.buttons() & Qt.LeftButton:
            if (event.position().toPoint() - self._drag_press).manhattanLength() >= QApplication.startDragDistance():
                self._start_color_drag()
                return True
        elif kind == QEvent.MouseButtonRelease:
            self._drag_press = None
        elif kind == QEvent.DragEnter:
            source = event.source()
            if event.mimeData().hasFormat(self.MIME) and source is not self.swatch:
                event.acceptProposedAction()
                self.swatch.set_drop_hover(True)
            else:
                event.ignore()
            return True
        elif kind == QEvent.DragLeave:
            self.swatch.set_drop_hover(False)
        elif kind == QEvent.Drop:
            self.swatch.set_drop_hover(False)
            if event.mimeData().hasFormat(self.MIME):
                value = bytes(event.mimeData().data(self.MIME)).decode("utf-8")
                event.acceptProposedAction()
                self.receive_color(value)
            return True
        return super().eventFilter(obj, event)

    def _start_color_drag(self):
        press, self._drag_press = self._drag_press, None
        self.swatch.setDown(False)
        mime = QMimeData()
        mime.setData(self.MIME, self._value.encode("utf-8"))
        grab = self.swatch.grab()
        ghost = QPixmap(grab.size())
        ghost.setDevicePixelRatio(grab.devicePixelRatio())
        ghost.fill(Qt.transparent)
        painter = QPainter(ghost)
        painter.setOpacity(DRAG_GHOST_OPACITY)
        painter.drawPixmap(0, 0, grab)
        painter.end()
        drag = QDrag(self.swatch)
        drag.setMimeData(mime)
        drag.setPixmap(ghost)
        drag.setHotSpot(press)
        drag.exec(Qt.CopyAction)
        self.swatch.setDown(False)

    def receive_color(self, value: str):
        """Couleur deposee (valeur complete « @slot/75 » ou « #hex ») : prise telle quelle, signalee comme
        un choix de l'utilisateur (apercu en direct, enregistrement, cotes lies)."""
        if not value or value == self._value:
            return
        _CompactAppOrCustomColorField.setValue(self, value)
        self.changed.emit(self._value)

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
                 thickness_field: QWidget | None = None, thickness_label: str = "Epaisseur",
                 linked: bool = False):
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
        toggle_row, self.link_toggle = _build_linked_sides_toggle(linked)
        self.link_toggle.toggled.connect(self._on_link_toggled)
        layout.addWidget(toggle_row)
        self.sides = _SideColorsField(sides, colors, enabled)
        if linked:
            self.sides.setLinked(True)
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

    def isLinked(self) -> bool:
        return self.link_toggle.isChecked()

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


class _InnerLineField(QWidget):
    """Reglage d'un filet de tableau : toggle (actif), couleur (app/sys),
    epaisseur. Valeur : (actif, couleur "#rrggbb" ou "@<slot>", epaisseur)."""

    changed = Signal()

    def __init__(self, enabled: bool, color: str, thickness: int, colors: dict, title: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.toggle = _Toggle(enabled, show_label=False)
        self.color = _CompactAppOrCustomColorField(color, colors, swatch_size=20, title=title)
        self.thickness = _SliderField(0, 8, thickness, slider_width=140, box_width=58)
        label = QLabel("Epaisseur")
        _set_text_role(label, "inline_label")
        layout.addWidget(self.toggle)
        layout.addWidget(self.color)
        layout.addWidget(label)
        layout.addWidget(self.thickness)
        self.toggle.toggled.connect(lambda _c: self.changed.emit())
        self.color.changed.connect(lambda _v: self.changed.emit())
        self.thickness.valueChanged.connect(lambda _v: self.changed.emit())

    def value(self) -> tuple[bool, str, int]:
        return self.toggle.isChecked(), self.color.value(), self.thickness.value()

    def setValue(self, enabled: bool, color: str, thickness: int):
        self.toggle.setChecked(bool(enabled))
        self.color.setValue(color)
        self.thickness.setValue(int(thickness))

    def refresh_colors(self, colors: dict):
        self.color.refresh_colors(colors)


