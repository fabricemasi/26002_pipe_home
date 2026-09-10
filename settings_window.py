#!/usr/bin/env python3
"""
Fenetre de parametres de Pipeline Browser.

Reproduction fidele de la maquette html fournie ("VFX Pipeline Settings v2") :
meme barre de titre interne, meme barre d'outils (preset + recherche), meme
navigation laterale a rails, meme en-tete de page souligne d'accent, memes
lignes de reglage (chemin / slider / select / segmente / interrupteur /
couleur), meme table de polices, meme grille de couleurs, meme barre du bas.
Les couleurs/tailles ci-dessous (voir M) sont recopiees telles quelles de la
maquette plutot que de reutiliser la palette de app_style.C — c'est la
palette PROPRE a cette fenetre, independante de celle (modifiable) du
navigateur principal.

    python settings_window.py   (pour previsualiser la fenetre seule)
"""

import json
import sys
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QIntValidator, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QColorDialog,
    QDialog,
    QFileDialog,
    QFontComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app_style import (
    C,
    COLOR_FIELDS,
    SMOOTHING_CHOICES,
    SMOOTHING_LABELS_SHORT,
    WINDOW_ROUNDED_RADIUS,
    apply_dwm_frame,
    auto_family_for_role,
    installed_font_families,
    start_native_move,
)

# ==========================================================================
# Palette et metriques de LA MAQUETTE (independantes de app_style.C : voir
# la remarque en tete de fichier).
# ==========================================================================

M = {
    "accent": "#3f6f9f",
    "accent_border": "#4c80b3",
    "accent_hover": "#487bad",
    "accent_fg": "#f2f6f9",
    "panel_bg": "#16181a",
    "panel_border": "#2a2e32",
    "titlebar_bg": "#101214",
    "title_fg": "#8d949a",
    "dirty_fg": "#c2914a",
    "clean_fg": "#5d656b",
    "close_hover_bg": "#232a30",
    "close_fg": "#7d858b",
    "close_hover_fg": "#d6d9dc",
    "toolbar_bg": "#1b1e21",
    "field_bg": "#101214",
    "field_border": "#2e343a",
    "field_border_hover": "#3f6f9f",
    "label_dim": "#6e767c",
    "value_fg": "#d6d9dc",
    "value_muted": "#8d949a",
    "chevron": "#6e767c",
    "btn_bg": "#262b30",
    "btn_border": "#353b41",
    "btn_fg": "#c4cacf",
    "btn_hover": "#2f353b",
    "slash": "#4c545a",
    "placeholder": "#5d656b",
    "nav_bg": "#131517",
    "nav_group_fg": "#5d656b",
    "nav_fg": "#aab1b6",
    "nav_fg_active": "#eaf0f5",
    "nav_bg_active": "#20262b",
    "nav_hover": "#1c2125",
    "nav_glyph": "#4f565b",
    "nav_glyph_active": "#8fb4d5",
    "nav_count": "#4f565b",
    "nav_count_active": "#7f9dba",
    "page_head_bg": "#1b1e21",
    "page_title": "#cfe1f0",
    "page_hint": "#6e767c",
    "group_title": "#d6d9dc",
    "group_divider": "#262a2e",
    "group_note": "#5d656b",
    "row_divider": "#232629",
    "row_label": "#cdd2d6",
    "row_label_off": "#6a7278",
    "row_note": "#5d656b",
    "value_text": "#e0e4e7",
    "value_text_off": "#6a7278",
    "unit": "#5d656b",
    "track_bg": "#25292d",
    "knob_off": "#4f565b",
    "seg_fg": "#98a0a7",
    "toggle_on_fg": "#9dc0e0",
    "toggle_off_fg": "#5d656b",
    "swatch_border": "#3a4045",
    "swatch_border_hover": "#5f9bd0",
    "table_head_bg": "#1b1e21",
    "table_row_a": "#181b1d",
    "table_row_b": "#16181a",
    "table_head_fg": "#8d949a",
    "bold_mark_fg": "#0f1114",
    "preview_bg": "#131517",
    "preview_border": "#262a2e",
    "reset_fg": "#9aa2a9",
    "reset_hover_fg": "#c8ced3",
}

# ==========================================================================
# Persistance
# ==========================================================================

SAVE_MODES = ["Par utilisateur", "Global (partage)", "Par projet", "Fichier externe"]

_SCRIPT_DIR = Path(__file__).resolve().parent
_PER_USER_PATH = _SCRIPT_DIR / "pipeline_settings.json"
_SHARED_PATH = _SCRIPT_DIR / "pipeline_settings.shared.json"
_PRESETS_PATH = _SCRIPT_DIR / "pipeline_settings.presets.json"


def _settings_path(settings: dict) -> Path:
    mode = settings.get("save_mode", "Par utilisateur")
    if mode == "Global (partage)":
        return _SHARED_PATH
    if mode == "Par projet":
        root = settings.get("root_path") or str(_SCRIPT_DIR)
        return Path(root) / "pipeline_settings.json"
    if mode == "Fichier externe":
        external = settings.get("external_settings_path") or ""
        if external:
            return Path(external)
    return _PER_USER_PATH


_DEFAULT_FONT = {
    "family": "", "size": 12, "bold": False, "smoothing": "current", "color": "", "custom": False,
}

DEFAULT_COLUMNS: dict[str, dict[str, Any]] = {
    "Type":        {"width": 140, "height": 25, "spacing": 0},
    "Projets":     {"width": 208, "height": 58, "spacing": 1, "img_pad": 0, "img_radius": 0,
                    "sep_h": True, "sep_v": True},
    "Sous-projet": {"width": 208, "height": 58, "spacing": 1, "img_pad": 0, "img_radius": 0,
                    "img_pad_link": True, "img_radius_link": True, "sep_h": True, "sep_v": True},
    "Logiciels":   {"width": 186, "height": 30, "plain_height": 22, "spacing": 0, "img_pad": 3, "img_radius": 2,
                    "sep_h": True, "sep_v": True},
    "Contenu":     {"width": 186, "height": 25, "plain_height": 20, "spacing": 0, "img_pad": 3, "img_radius": 0,
                    "sep_h": True, "sep_v": True},
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "root_path": r"F:\PIPELINE",
    "ui_scale": 100,
    "save_mode": "Par utilisateur",
    "external_settings_path": "",
    "window_radius": 0,
    "header_height": 26,
    "header_font_family": "",
    "colors": {key: C[key] for key, _, _ in COLOR_FIELDS},
    "font_main": dict(_DEFAULT_FONT),
    "font_titles": dict(_DEFAULT_FONT),
    "font_folders": dict(_DEFAULT_FONT),
    "font_files": dict(_DEFAULT_FONT),
    "font_buttons": dict(_DEFAULT_FONT),
    "font_colhead": dict(_DEFAULT_FONT),
    "font_info": dict(_DEFAULT_FONT),
    "font_info2": dict(_DEFAULT_FONT),
    "button_radius": 0,
    "columns": json.loads(json.dumps(DEFAULT_COLUMNS)),
    "preview_pad": 0,
    "preview_radius": 0,
}


def load_settings() -> dict[str, Any]:
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))

    def _merge(data: dict):
        for key, value in data.items():
            if key not in DEFAULT_SETTINGS:
                continue
            if isinstance(value, dict) and isinstance(settings.get(key), dict):
                for sub_key, sub_val in value.items():
                    if isinstance(sub_val, dict) and isinstance(settings[key].get(sub_key), dict):
                        settings[key][sub_key].update(sub_val)
                    else:
                        settings[key][sub_key] = sub_val
            else:
                settings[key] = value

    try:
        if _PER_USER_PATH.is_file():
            _merge(json.loads(_PER_USER_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    try:
        real_path = _settings_path(settings)
        if real_path != _PER_USER_PATH and real_path.is_file():
            _merge(json.loads(real_path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    path = _settings_path(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _load_presets() -> dict[str, dict]:
    try:
        if _PRESETS_PATH.is_file():
            data = json.loads(_PRESETS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


def _save_presets(presets: dict[str, dict]) -> None:
    try:
        _PRESETS_PATH.write_text(json.dumps(presets, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ==========================================================================
# Petits widgets reproduisant exactement les controles de la maquette.
# ==========================================================================

def _qfont(size: int, weight: int = 400, mono: bool = False) -> QFont:
    f = QFont("Consolas" if mono else "Segoe UI")
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    return f


class _Btn(QPushButton):
    """Bouton rectangulaire plat, style boutons de la maquette (bg/bordure/
    hover uniformes, sans le degrade natif de Fusion)."""

    def __init__(self, text: str, bg: str, border: str, fg: str, hover: str,
                 height: int = 24, weight: int = 500, padding: str = "0 10px", parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(height)
        self.setCursor(Qt.ArrowCursor)
        # Sans ceci, Fusion dessine un rectangle pointille de focus autour du
        # texte du bouton des qu'il regoit le focus clavier (des le premier
        # clic) : ce cadre "sur le texte" est exactement ce qui etait signale.
        self.setFocusPolicy(Qt.NoFocus)
        self.setFont(_qfont(11, weight))
        self.setStyleSheet(
            f"QPushButton {{ background: {bg}; border: 1px solid {border}; color: {fg}; "
            f"padding: {padding}; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
        )


class _MiniSlider(QWidget):
    """Slider peint a la main : filet 3px + curseur rectangulaire 3x14,
    exactement la geometrie de la maquette (un QSlider stylise via QSS ne
    reproduit pas fidelement un curseur aussi fin)."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, value: int, width: int = 170,
                 muted: bool = False, parent=None):
        super().__init__(parent)
        self._min, self._max = minimum, maximum
        self._value = max(minimum, min(maximum, value))
        self._muted = muted
        self.setFixedSize(width, 22)
        self.setCursor(Qt.ArrowCursor)

    def setMuted(self, muted: bool):
        self._muted = muted
        self.update()

    def value(self) -> int:
        return self._value

    def setValue(self, value: int):
        value = max(self._min, min(self._max, value))
        if value != self._value:
            self._value = value
            self.update()
            self.valueChanged.emit(value)

    def _pct(self) -> float:
        span = self._max - self._min
        return 0.0 if span <= 0 else (self._value - self._min) / span

    def _set_from_x(self, x: int):
        pct = max(0.0, min(1.0, x / max(1, self.width())))
        self.setValue(round(self._min + pct * (self._max - self._min)))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._set_from_x(event.position().toPoint().x())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._set_from_x(event.position().toPoint().x())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        mid_y = self.height() // 2
        p.fillRect(0, mid_y - 1, self.width(), 3, QColor(M["track_bg"]))
        fill_color = M["knob_off"] if self._muted else M["accent"]
        knob_color = M["knob_off"] if self._muted else "#8fb4d5"
        fill_w = round(self._pct() * self.width())
        if fill_w > 0:
            p.fillRect(0, mid_y - 1, fill_w, 3, QColor(fill_color))
        knob_x = max(0, min(self.width() - 3, fill_w - 1))
        p.fillRect(knob_x, mid_y - 7, 3, 14, QColor(knob_color))
        p.end()


class _SliderField(QWidget):
    """Slider + boite de lecture numerique a droite (unite comprise) —
    assemble _MiniSlider avec sa valeur affichee, comme dans la maquette."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, value: int, unit: str = "px",
                 slider_width: int = 170, box_width: int = 68, muted: bool = False, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.slider = _MiniSlider(minimum, maximum, value, slider_width, muted)
        box = QWidget()
        box.setObjectName("SliderValueBox")
        box.setAttribute(Qt.WA_StyledBackground, True)
        box.setFixedSize(box_width, 25)
        # Selecteur scope a #SliderValueBox : une regle nue (sans selecteur)
        # cascade en QSS sur value_label/unit_label ci-dessous, y dessinant
        # chacun leur propre filet — c'etait le "border actif sur le texte"
        # signale par l'utilisateur (visible autour de la valeur numerique).
        box.setStyleSheet(f"#SliderValueBox {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; }}")
        box_l = QHBoxLayout(box)
        box_l.setContentsMargins(7, 0, 7, 0)
        box_l.setSpacing(4)
        self._min, self._max = minimum, maximum
        # QLineEdit plutot qu'un QLabel : la valeur doit rester saisissable
        # au clavier (selection + frappe directe), pas seulement lisible —
        # voir la remarque de l'utilisateur, capture a l'appui.
        self.value_label = QLineEdit(str(value))
        self.value_label.setFont(_qfont(11, 400, mono=True))
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value_label.setFrame(False)
        # Pas de bornes sur le validateur lui-meme : avec QIntValidator(min,
        # max), Qt considere un depassement comme durablement invalide et
        # bloque jusqu'au retour-arriere (Entree ne fait plus rien, le champ
        # reste coince sur un texte incoherent) — le clamp reel se fait a la
        # validation, dans _on_text_edited.
        self.value_label.setValidator(QIntValidator(self.value_label))
        self.value_label.setStyleSheet("background: transparent; border: none; padding: 0;")
        self.value_label.editingFinished.connect(self._on_text_edited)
        self.unit_label = QLabel(unit)
        self.unit_label.setFont(_qfont(9, 400, mono=True))
        self.unit_label.setStyleSheet(f"color: {M['unit']}; background: transparent;")
        box_l.addWidget(self.value_label, 1)
        box_l.addWidget(self.unit_label)
        self._box = box
        layout.addWidget(self.slider)
        layout.addWidget(box)
        self.setMuted(muted)
        self.slider.valueChanged.connect(self._on_change)

    def _on_change(self, value: int):
        self.value_label.setText(str(value))
        self.valueChanged.emit(value)

    def _on_text_edited(self):
        """Valide la saisie clavier a la validation (Entree ou perte de
        focus) : texte vide/invalide ou hors bornes revient simplement a la
        valeur courante du slider plutot que de planter/laisser un etat
        incoherent — QIntValidator borne deja la plupart des cas, ceci
        couvre le champ laisse vide ou juste "-"."""
        text = self.value_label.text().strip()
        try:
            value = max(self._min, min(self._max, int(text)))
        except ValueError:
            value = self.slider.value()
        self.slider.setValue(value)
        # setValue() ne re-emet valueChanged (donc ne retexte value_label)
        # que si la valeur a change — la reafficher nous-memes couvre aussi
        # le cas ou la saisie invalide revient a l'identique.
        self.value_label.setText(str(self.slider.value()))

    def setMuted(self, muted: bool):
        self.slider.setMuted(muted)
        color = M["value_text_off"] if muted else M["value_text"]
        self.value_label.setStyleSheet(f"background: transparent; border: none; padding: 0; color: {color};")

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value: int):
        self.slider.setValue(value)


class _SelectField(QPushButton):
    """Bouton "select" (valeur + chevron), ouvre un QMenu — reproduit la
    boite cliquable de la maquette plutot qu'un QComboBox natif."""

    changed = Signal(str)

    def __init__(self, options: list[str], current: str, width: int = 200, parent=None):
        super().__init__(parent)
        self._options = options
        self._value = current if current in options else options[0]
        self.setFixedSize(width, 25)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFont(_qfont(11, 400))
        self._apply_style()
        self.clicked.connect(self._open_menu)
        self._sync_text()

    def _apply_style(self):
        self.setStyleSheet(
            f"QPushButton {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"color: {M['value_fg']}; text-align: left; padding: 0 8px; }}"
            f"QPushButton:hover {{ border-color: {M['field_border_hover']}; }}"
        )

    def _sync_text(self):
        self.setText(self._value + "  \u25be")

    def _open_menu(self):
        menu = QMenu(self)
        menu.setFont(_qfont(11, 400))
        menu.setStyleSheet(
            f"QMenu {{ background: {M['toolbar_bg']}; border: 1px solid {M['field_border']}; padding: 4px 0; }}"
            f"QMenu::item {{ padding: 5px 16px; color: {M['value_fg']}; }}"
            f"QMenu::item:selected {{ background: {M['accent']}; color: {M['accent_fg']}; }}"
        )
        for opt in self._options:
            action = menu.addAction(opt)
            action.triggered.connect(lambda _checked=False, o=opt: self._select(o))
        menu.exec(self.mapToGlobal(QPoint(0, self.height())))

    def _select(self, opt: str):
        if opt != self._value:
            self._value = opt
            self._sync_text()
            self.changed.emit(opt)

    def value(self) -> str:
        return self._value

    def setValue(self, value: str):
        if value in self._options and value != self._value:
            self._value = value
            self._sync_text()


class _FontSelectField(_SelectField):
    """Variante de _SelectField pour choisir une police : un QMenu classique
    ne rend chaque entree que comme du texte plat dans une seule police, et
    ne defile que par petites fleches haut/bas des qu'il deborde de l'ecran
    — mediocre avec ~200 polices. Ici, une vraie liste deroulante (scroll
    natif fluide, molette comprise) ou chaque nom de police est rendu DANS
    cette police : l'apercu est direct, pas besoin de la selectionner pour
    voir a quoi elle ressemble.

    `auto_label`, si fourni, est le nom REEL de la police que l'auto-
    detection choisirait pour ce role (voir auto_family_for_role) : affiche
    a la place du mot generique "Systeme" partout ou l'entree "Systeme" est
    rendue (bouton + liste), sans changer la valeur STOCKEE (toujours
    "Systeme" en interne — la case reste bien "auto-detection", pas "police
    figee sur celle-ci en particulier" ; si l'auto-detection venait a
    resoudre une autre police, ce libelle suivrait tout seul)."""

    def __init__(self, options: list[str], current: str, width: int = 200,
                 auto_label: str | None = None, parent=None):
        self._auto_label = auto_label
        super().__init__(options, current, width, parent)

    def _display_label(self, opt: str) -> str:
        if opt == "Systeme" and self._auto_label:
            return self._auto_label
        return opt

    def _sync_text(self):
        self.setText(self._display_label(self._value) + "  ▾")

    def _open_menu(self):
        popup = QWidget(self, Qt.Popup)
        popup.setObjectName("FontPopup")
        popup.setAttribute(Qt.WA_StyledBackground, True)
        popup.setStyleSheet(
            f"#FontPopup {{ background: {M['toolbar_bg']}; border: 1px solid {M['field_border']}; }}"
        )
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        listw = QListWidget(popup)
        listw.setFrameShape(QFrame.NoFrame)
        listw.setUniformItemSizes(True)
        listw.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            f"QListWidget::item {{ padding: 6px 12px; color: {M['value_fg']}; }}"
            f"QListWidget::item:selected {{ background: {M['accent']}; color: {M['accent_fg']}; }}"
            f"QListWidget::item:hover:!selected {{ background: {M['close_hover_bg']}; }}"
        )
        current_item = None
        for opt in self._options:
            if opt == self._auto_label and opt != self._value:
                # Deja represente par l'entree "Systeme" ci-dessus (voir
                # _display_label) : ne PAS la retirer de self._options
                # (une police explicitement choisie qui coinciderait avec
                # l'auto-detection doit rester distincte, voir le
                # commentaire au point de construction), juste ne pas la
                # re-afficher en double ici.
                continue
            item = QListWidgetItem(self._display_label(opt))
            # La valeur reelle (potentiellement differente du texte affiche
            # pour l'entree "Systeme", voir _display_label) voyage a part —
            # lire item.text() au clic donnerait le libelle, pas la valeur.
            item.setData(Qt.UserRole, opt)
            # "Systeme" reste dans la police de l'appli (rien a previsualiser
            # de plus : son libelle EST deja le nom de la police reellement
            # utilisee) ; chaque police explicite est rendue dans elle-meme
            # — l'apercu direct demande par l'utilisateur.
            item.setFont(_qfont(12, 400) if opt == "Systeme" else QFont(opt, 12))
            listw.addItem(item)
            if opt == self._value:
                current_item = item
        listw.itemClicked.connect(lambda item: self._pick_from_popup(item.data(Qt.UserRole), popup))

        layout.addWidget(listw)
        popup.setFixedWidth(max(self.width(), 240))
        popup.setFixedHeight(320)
        popup.move(self.mapToGlobal(QPoint(0, self.height())))
        popup.show()
        if current_item is not None:
            listw.setCurrentItem(current_item)
            listw.scrollToItem(current_item)
        listw.setFocus()

    def _pick_from_popup(self, opt: str, popup: QWidget):
        popup.close()
        self._select(opt)


class _Segmented(QWidget):
    """Controle a positions exclusives (lissage 3 positions, etc.)."""

    changed = Signal(str)

    def __init__(self, choices: list[str], labels: dict[str, str], current: str,
                 height: int = 25, seg_width: int = 0, parent=None):
        super().__init__(parent)
        self._choices = choices
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._buttons: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for i, key in enumerate(choices):
            btn = QPushButton(labels.get(key, key))
            btn.setCheckable(True)
            btn.setChecked(key == current)
            btn.setFont(_qfont(10, 400))
            btn.setFixedHeight(height)
            # Largeur MINIMALE (pas fixe) : une largeur fixe trop etroite
            # rognait le texte des libelles les plus longs ("Moyen") — voir
            # sizeHint() ci-dessous, qui tient compte du texte reel.
            if seg_width:
                btn.setMinimumWidth(seg_width)
            btn.setCursor(Qt.ArrowCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            sep = "" if i == 0 else f"border-left: 1px solid {M['field_border']};"
            btn.setStyleSheet(
                "QPushButton { background: " + M["field_bg"] + "; border: 1px solid " + M["field_border"] +
                "; " + sep + f" color: {M['seg_fg']}; padding: 0 6px; }}"
                "QPushButton:checked { background: " + M["accent"] + "; color: " + M["accent_fg"] +
                "; font-weight: 600; }"
                "QPushButton:hover:!checked { background: #1c2328; }"
            )
            group.addButton(btn)
            layout.addWidget(btn)
            self._buttons[key] = btn
            btn.clicked.connect(lambda _checked, k=key: self._select(k))

    def _select(self, key: str):
        self.changed.emit(key)

    def value(self) -> str:
        for key, btn in self._buttons.items():
            if btn.isChecked():
                return key
        return self._choices[0]

    def setValue(self, key: str):
        if key in self._buttons:
            self._buttons[key].setChecked(True)


class _Toggle(QWidget):
    """Interrupteur peint a la main (piste 30x15 + curseur 11x11), fidele a
    la maquette — bien plus distinctif qu'une QCheckBox."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, on_label="lie", off_label="libre", parent=None):
        super().__init__(parent)
        self._checked = checked
        self._on_label, self._off_label = on_label, off_label
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(30 + 8 + 40, 25)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if checked != self._checked:
            self._checked = checked
            self.update()
            self.toggled.emit(checked)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        y = (self.height() - 15) // 2
        track_bg = QColor(M["accent"] if self._checked else M["field_bg"])
        track_bd = QColor(M["accent_border"] if self._checked else M["field_border"])
        p.setPen(track_bd)
        p.setBrush(track_bg)
        p.drawRect(0, y, 29, 14)
        knob_x = 1 + (29 - 1 - 11) if self._checked else 1
        knob_color = QColor("#f2f6f9" if self._checked else M["knob_off"])
        p.setPen(Qt.NoPen)
        p.setBrush(knob_color)
        p.drawRect(knob_x, y + 2, 11, 11)
        p.setFont(_qfont(10, 400, mono=True))
        p.setPen(QColor(M["toggle_on_fg"] if self._checked else M["toggle_off_fg"]))
        p.drawText(38, 0, 40, self.height(), Qt.AlignVCenter | Qt.AlignLeft,
                   self._on_label if self._checked else self._off_label)
        p.end()


class _ColorField(QWidget):
    """Pastille cliquable + boite hexadecimale a droite, exactement comme la
    maquette (le hex n'est pas dans un champ editable dans la maquette : ici
    aussi, purement en lecture, la pastille est le seul point d'entree)."""

    changed = Signal(str)

    def __init__(self, value: str, swatch_size: int = 25, hex_box: bool = True, parent=None):
        super().__init__(parent)
        self._value = value
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.swatch = QPushButton()
        self.swatch.setFixedSize(swatch_size, swatch_size)
        self.swatch.setCursor(Qt.ArrowCursor)
        self.swatch.setFocusPolicy(Qt.NoFocus)
        self.swatch.clicked.connect(self._pick)
        layout.addWidget(self.swatch)
        self.hex_label = None
        if hex_box:
            box = QWidget()
            box.setObjectName("HexBox")
            box.setAttribute(Qt.WA_StyledBackground, True)
            box.setFixedSize(88, 25)
            # Voir la meme remarque sur #SliderValueBox : sans ce selecteur,
            # le filet cascaderait sur hex_label ci-dessous.
            box.setStyleSheet(f"#HexBox {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; }}")
            box_l = QHBoxLayout(box)
            box_l.setContentsMargins(8, 0, 8, 0)
            self.hex_label = QLabel(value)
            self.hex_label.setFont(_qfont(11, 400, mono=True))
            self.hex_label.setStyleSheet(f"color: {M['value_muted']}; background: transparent;")
            box_l.addWidget(self.hex_label)
            layout.addWidget(box)
        self._refresh()

    def _refresh(self):
        # Un seul bloc QSS explicite (selecteur QPushButton), plutot que des
        # declarations nues suivies d'un rajout de regle a part : le melange
        # des deux formes dans un meme setStyleSheet() a le mauvais gout de
        # ne plus peindre du tout le fond selon le style actif.
        self.swatch.setStyleSheet(
            "QPushButton { background: " + self._value + "; border: 1px solid " + M["swatch_border"] + "; }"
            "QPushButton:hover { border-color: " + M["swatch_border_hover"] + "; }"
        )
        if self.hex_label is not None:
            self.hex_label.setText(self._value)

    def _pick(self):
        chosen = QColorDialog.getColor(QColor(self._value), self, "Choisir une couleur")
        if chosen.isValid():
            self._value = chosen.name()
            self._refresh()
            self.changed.emit(self._value)

    def value(self) -> str:
        return self._value


class _CheckSquare(QWidget):
    """Petite case carree (colonne "Gras" de la table de polices)."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(15, 15)
        self.setCursor(Qt.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if checked != self._checked:
            self._checked = checked
            self.update()
            self.toggled.emit(checked)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        bg = QColor(M["accent"] if self._checked else M["field_bg"])
        bd = QColor(M["accent_border"] if self._checked else M["field_border"])
        p.setPen(bd)
        p.setBrush(bg)
        p.drawRect(0, 0, 14, 14)
        if self._checked:
            p.setPen(QColor(M["bold_mark_fg"]))
            p.setFont(_qfont(9, 700, mono=True))
            p.drawText(0, 0, 14, 14, Qt.AlignCenter, "\u2713")
        p.end()


# ==========================================================================
# Blocs de mise en page (groupes / lignes / en-tetes), fideles a la maquette.
# ==========================================================================

def _label_block(text: str, note: str = "", off: bool = False) -> QWidget:
    box = QWidget()
    # Sans ceci, un QLabel a la ligne (note.setWordWrap) impose au premier
    # passage de mise en page sa largeur NON repliee comme sizeHint, et rien
    # ne la retrecit ensuite meme si le facteur d'etirement de la ligne (voir
    # _Row) devrait le forcer — toute la ligne (et son controle a droite,
    # pousse hors champ) se retrouve alors bien plus large que la fenetre.
    # Ignored laisse le stretch du parent dieter la largeur reelle.
    box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 6, 0, 6)
    layout.setSpacing(1)
    name = QLabel(text)
    name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    name.setFont(_qfont(12, 400))
    name.setStyleSheet(f"color: {M['row_label_off'] if off else M['row_label']}; background: transparent;")
    layout.addWidget(name)
    if note:
        sub = QLabel(note)
        sub.setWordWrap(True)
        sub.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        sub.setFont(_qfont(10, 400))
        sub.setStyleSheet(f"color: {M['row_note']}; background: transparent;")
        layout.addWidget(sub)
    return box


class _Row(QWidget):
    """Ligne de reglage : libelle+note a gauche, controle a droite. Pas de
    filet de separation entre les lignes d'un groupe (juge parasite a
    l'usage — voir la remarque de l'utilisateur, capture a l'appui)."""

    def __init__(self, label: str, control: QWidget, note: str = "", last: bool = False, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignVCenter)
        layout.addWidget(_label_block(label, note), 1)
        control.setParent(self)
        layout.addWidget(control, 0, Qt.AlignVCenter)
        self.setMinimumHeight(32)
        self.setObjectName("SettingsRow")


class _Group(QWidget):
    """Groupe de lignes avec titre + filet + note optionnelle en tete."""

    def __init__(self, title: str = "", note: str = "", parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        if title:
            head = QWidget()
            head_l = QHBoxLayout(head)
            head_l.setContentsMargins(0, 0, 0, 8)
            head_l.setSpacing(10)
            name = QLabel(title)
            name.setFont(_qfont(11, 600))
            name.setStyleSheet(f"color: {M['group_title']}; background: transparent;")
            head_l.addWidget(name)
            line = QFrame()
            line.setFixedHeight(1)
            line.setStyleSheet(f"background: {M['group_divider']};")
            head_l.addWidget(line, 1)
            if note:
                note_label = QLabel(note)
                note_label.setFont(_qfont(10, 400))
                note_label.setStyleSheet(f"color: {M['group_note']}; background: transparent;")
                # Ignored : ce libelle partage la ligne d'entete avec le
                # filet extensible juste avant lui — un texte plus long que
                # prevu ne doit jamais forcer toute la page a s'elargir (voir
                # la meme remarque dans _label_block). Reserve aux notes
                # COURTES (ex. "18 valeurs") ; un paragraphe explicatif va
                # dans une ligne a part, sous l'entete (voir add_note ci-dessous).
                note_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
                head_l.addWidget(note_label)
            self._layout.addWidget(head)

    def add(self, widget: QWidget):
        self._layout.addWidget(widget)

    def add_note(self, text: str):
        """Ligne de texte explicatif pleine largeur, correctement replie —
        a utiliser pour un paragraphe (l'entete de groupe ne convient qu'a
        une note courte, voir la remarque plus haut)."""
        label = QLabel(text)
        label.setWordWrap(True)
        label.setFont(_qfont(10, 400))
        label.setStyleSheet(f"color: {M['group_note']}; background: transparent; padding-bottom: 8px;")
        self._layout.addWidget(label)


def _page_header(title: str, hint: str) -> QWidget:
    header = QWidget()
    header.setObjectName("PageHeader")
    header.setAttribute(Qt.WA_StyledBackground, True)
    header.setFixedHeight(32)
    # Selecteur scope a #PageHeader : une regle nue (sans selecteur) cascade
    # en QSS sur tous les widgets enfants (voir la meme remarque pour
    # #SettingsRow/#NavWrap plus haut) — c'etait la vraie source du filet
    # bleu signale par l'utilisateur, qui persistait sous chaque libelle de
    # cet entete meme apres avoir retire le filet du groupe de reglages.
    # Suppression pure et simple du filet (juge parasite a l'usage).
    header.setStyleSheet(f"#PageHeader {{ background: {M['page_head_bg']}; }}")
    layout = QHBoxLayout(header)
    layout.setContentsMargins(18, 0, 18, 0)
    layout.setSpacing(10)
    title_label = QLabel(title.upper())
    title_label.setFont(_qfont(9, 600))
    title_label.setStyleSheet(f"color: {M['page_title']}; background: transparent; letter-spacing: 1px;")
    hint_label = QLabel(hint)
    hint_label.setFont(_qfont(11, 400))
    hint_label.setStyleSheet(f"color: {M['page_hint']}; background: transparent;")
    layout.addWidget(title_label)
    layout.addWidget(hint_label, 1)
    return header


# ==========================================================================
# Navigation laterale (rails, glyphes, compteurs, groupe "Colonnes")
# ==========================================================================

class _NavRow(QWidget):
    clicked = Signal()

    def __init__(self, label: str, count: str = "", indent: bool = False, parent=None):
        super().__init__(parent)
        # Indispensable pour qu'une sous-classe de QWidget peigne son propre
        # style (fond/rail) — voir la meme remarque pour TitleBar/Column
        # dans pipeline_browser.py.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._active = False
        self.setFixedHeight(29)
        self.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20 if indent else 12, 0, 12, 0)
        layout.setSpacing(9)
        self.glyph = QFrame()
        self.glyph.setFixedSize(3, 11)
        layout.addWidget(self.glyph, 0, Qt.AlignVCenter)
        self.text_label = QLabel(label)
        self.text_label.setFont(_qfont(12, 400))
        layout.addWidget(self.text_label, 1)
        self.count_label = QLabel(count)
        self.count_label.setFont(_qfont(9, 400, mono=True))
        layout.addWidget(self.count_label, 0, Qt.AlignRight)
        self._refresh()

    def setActive(self, active: bool):
        self._active = active
        self._refresh()
        self.text_label.setFont(_qfont(12, 600 if active else 400))

    def _refresh(self):
        a = self._active
        self.setStyleSheet(
            f"_NavRow {{ background: {M['nav_bg_active'] if a else 'transparent'}; "
            f"border-left: 2px solid {M['accent'] if a else 'transparent'}; }}"
            f"_NavRow:hover {{ background: {M['nav_bg_active'] if a else M['nav_hover']}; }}"
        )
        self.glyph.setStyleSheet(f"background: {M['nav_glyph_active'] if a else M['nav_glyph']};")
        self.text_label.setStyleSheet(
            f"color: {M['nav_fg_active'] if a else M['nav_fg']}; background: transparent;"
        )
        self.count_label.setStyleSheet(
            f"color: {M['nav_count_active'] if a else M['nav_count']}; background: transparent;"
        )

    def setFilterMatch(self, matches: bool):
        self.setVisible(matches)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


def _nav_group_header(label: str) -> QWidget:
    row = QWidget()
    row.setFixedHeight(26)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(12, 0, 12, 0)
    text = QLabel(label.upper())
    text.setFont(_qfont(9, 600))
    text.setStyleSheet(f"color: {M['nav_group_fg']}; background: transparent; letter-spacing: 1px;")
    layout.addWidget(text)
    return row


# ==========================================================================
# Page "Colonne ..." — largeur / hauteur / espacement (+ Images)
# ==========================================================================

class _ColumnPage(QWidget):
    changed = Signal()

    def __init__(self, conf: dict, show_images: bool, linkable: bool = False, mixed_rows: bool = False, parent=None):
        super().__init__(parent)
        self._linkable = linkable
        self._mixed_rows = mixed_rows
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        geo = _Group()
        self.width_field = _SliderField(120, 480, conf.get("width", 200))
        geo.add(_Row("Largeur de la colonne", self.width_field))
        self.height_field = _SliderField(16, 120, conf.get("height", 24))
        geo.add(_Row("Hauteur des lignes (avec apercu)" if mixed_rows else "Hauteur des lignes", self.height_field))
        self.plain_height_field = None
        if mixed_rows:
            # Seulement pour les colonnes qui melangent lignes normales et
            # lignes-carte avec vignette (Logiciels/Contenu, voir
            # RowDelegate.sizeHint) : Projets/Sous-projet affichent
            # systematiquement une vignette, une seule hauteur y suffit.
            self.plain_height_field = _SliderField(12, 100, conf.get("plain_height", conf.get("height", 24)))
            geo.add(_Row("Hauteur des lignes (sans apercu)", self.plain_height_field))
        self.spacing_field = _SliderField(0, 12, conf.get("spacing", 0))
        geo.add(_Row("Espacement entre fichiers", self.spacing_field, last=not show_images))
        layout.addWidget(geo)

        self.pad_link = None
        self.radius_link = None
        self.pad_field = None
        self.radius_field = None
        self.sep_h_field = None
        self.sep_v_field = None
        if show_images:
            img = _Group("Images")
            img.add_note(
                "Par defaut, l'image occupe la hauteur de la ligne ; sa taille reelle "
                "est reglee via le padding, applique a l'identique sur les 4 cotes."
            )
            if linkable:
                self.pad_link = _Toggle(conf.get("img_pad_link", True), "lie", "libre")
                img.add(_Row("Lier le padding aux images de Projets", self.pad_link))
            self.pad_field = _SliderField(0, 16, conf.get("img_pad", 0))
            img.add(_Row("Padding (4 cotes)", self.pad_field))
            if linkable:
                self.radius_link = _Toggle(conf.get("img_radius_link", True), "lie", "libre")
                img.add(_Row("Lier le border radius aux images de Projets", self.radius_link))
            self.radius_field = _SliderField(0, 24, conf.get("img_radius", 0))
            img.add(_Row("Border radius", self.radius_field, last=True))
            layout.addWidget(img)
            if linkable:
                self.pad_link.toggled.connect(self._update_link_state)
                self.radius_link.toggled.connect(self._update_link_state)
                self._update_link_state()

            sep = _Group("Separateurs")
            self.sep_h_field = _Toggle(conf.get("sep_h", True), "visible", "masquee")
            sep.add(_Row("Ligne horizontale (entre les lignes)", self.sep_h_field))
            self.sep_v_field = _Toggle(conf.get("sep_v", True), "visible", "masquee")
            sep.add(_Row("Ligne verticale (vignette / texte)", self.sep_v_field, last=True))
            layout.addWidget(sep)

        layout.addStretch(1)

        self.width_field.valueChanged.connect(lambda _: self.changed.emit())
        self.height_field.valueChanged.connect(lambda _: self.changed.emit())
        if mixed_rows:
            self.plain_height_field.valueChanged.connect(lambda _: self.changed.emit())
        self.spacing_field.valueChanged.connect(lambda _: self.changed.emit())
        if show_images:
            self.pad_field.valueChanged.connect(lambda _: self.changed.emit())
            self.radius_field.valueChanged.connect(lambda _: self.changed.emit())
            if linkable:
                self.pad_link.toggled.connect(lambda _: self.changed.emit())
                self.radius_link.toggled.connect(lambda _: self.changed.emit())
            self.sep_h_field.toggled.connect(lambda _: self.changed.emit())
            self.sep_v_field.toggled.connect(lambda _: self.changed.emit())

    def _update_link_state(self, *_args):
        self.pad_field.setMuted(self.pad_link.isChecked())
        self.pad_field.setEnabled(not self.pad_link.isChecked())
        self.radius_field.setMuted(self.radius_link.isChecked())
        self.radius_field.setEnabled(not self.radius_link.isChecked())

    def value(self) -> dict:
        out = {
            "width": self.width_field.value(),
            "height": self.height_field.value(),
            "spacing": self.spacing_field.value(),
        }
        if self.plain_height_field is not None:
            out["plain_height"] = self.plain_height_field.value()
        if self.pad_field is not None:
            out["img_pad"] = self.pad_field.value()
            out["img_radius"] = self.radius_field.value()
            out["sep_h"] = self.sep_h_field.isChecked()
            out["sep_v"] = self.sep_v_field.isChecked()
        if self._linkable:
            out["img_pad_link"] = self.pad_link.isChecked()
            out["img_radius_link"] = self.radius_link.isChecked()
        return out


# ==========================================================================
# Page "Polices de caracteres" — table Role/Police/Taille/Gras/Coul./Lissage
# ==========================================================================

_ROLE_ROWS = [
    ("font_main", "Police principale", "Corps de texte general"),
    ("font_titles", "Police principale titres", "Titres et intitules de fenetre"),
    ("font_folders", "Dossiers", "Rangees de dossiers"),
    ("font_files", "Fichiers", "Rangees de fichiers"),
    ("font_buttons", "Boutons", "Barre d'outils et actions"),
    ("font_colhead", "Entete de colonnes", "Bandeau haut de chaque colonne"),
    ("font_info", "Informations diverses / invites", "Compteurs, tailles, chemins"),
    ("font_info2", "Informations diverses / invites (2)", "Second jeu, notes/etats secondaires"),
]

# Cle de reglage -> role app_style.py (voir apply_all_settings dans
# pipeline_browser.py, meme mapping) : necessaire pour retrouver, pour
# chaque ligne de la table, quelle police l'auto-detection choisirait
# reellement (voir auto_family_for_role) et l'afficher au lieu du mot
# generique "Systeme" dans le selecteur.
_ROLE_KEY_TO_STYLE_ROLE = {
    "font_main": "app",
    "font_titles": "titles",
    "font_folders": "folders",
    "font_files": "files",
    "font_buttons": "buttons",
    "font_colhead": "colhead",
    "font_info": "info",
    "font_info2": "info2",
}


def _font_choices() -> list[str]:
    """"Systeme" (auto-detection, voir role_font) suivi de TOUTES les
    polices reellement installees sur la machine — plus la liste figee
    d'avant (6 polices "maison", pas forcement presentes chez
    l'utilisateur), voir installed_font_families dans app_style.py."""
    return ["Systeme"] + installed_font_families()


class _FontTable(QWidget):
    changed = Signal()

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(0)
        headers = [("Role", 1, 170), ("Police", 0, 146), ("Taille", 0, 132),
                   ("Gras", 0, 46), ("Coul.", 0, 56), ("Lissage", 0, 156)]
        head = QWidget()
        head.setObjectName("TableHead")
        head.setAttribute(Qt.WA_StyledBackground, True)
        head.setFixedHeight(26)
        # Scope a #TableHead : sinon le filet cascade sur chaque `cell` de
        # l'entete ci-dessous (meme bug que #SliderValueBox plus haut).
        head.setStyleSheet(f"#TableHead {{ background: {M['table_head_bg']}; border: 1px solid {M['panel_border']}; }}")
        head_l = QHBoxLayout(head)
        head_l.setContentsMargins(0, 0, 0, 0)
        head_l.setSpacing(0)
        for text, stretch, width in headers:
            cell = QLabel(text.upper())
            cell.setFont(_qfont(9, 600))
            cell.setStyleSheet(f"color: {M['table_head_fg']}; background: transparent; padding: 0 10px;")
            if stretch:
                head_l.addWidget(cell, 1)
            else:
                cell.setFixedWidth(width)
                head_l.addWidget(cell, 0)
        layout.addWidget(head)

        self.role_rows: dict[str, dict[str, Any]] = {}
        for i, (key, role_name, note) in enumerate(_ROLE_ROWS):
            conf = settings[key]
            row = QWidget()
            row.setObjectName("TableRow")
            row.setAttribute(Qt.WA_StyledBackground, True)
            row.setMinimumHeight(36)
            bg = M["table_row_a"] if i % 2 else M["table_row_b"]
            # Scope a #TableRow : sinon le filet cascade sur `name`/
            # `note_label` (et tout autre QLabel nu de la ligne) ci-dessous.
            row.setStyleSheet(
                f"#TableRow {{ background: {bg}; border: 1px solid {M['panel_border']}; border-top: none; }}"
            )
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(0, 6, 0, 6)
            row_l.setSpacing(0)

            role_cell = QWidget()
            role_l = QVBoxLayout(role_cell)
            role_l.setContentsMargins(10, 0, 10, 0)
            role_l.setSpacing(1)
            name = QLabel(role_name)
            name.setFont(_qfont(12, 400))
            name.setStyleSheet(f"color: {M['row_label']}; background: transparent;")
            note_label = QLabel(note)
            note_label.setFont(_qfont(10, 400))
            note_label.setStyleSheet(f"color: {M['row_note']}; background: transparent;")
            role_l.addWidget(name)
            role_l.addWidget(note_label)
            row_l.addWidget(role_cell, 1)

            style_role = _ROLE_KEY_TO_STYLE_ROLE[key]
            auto_label = auto_family_for_role(style_role)
            # La liste complete est gardee telle quelle (PAS de filtre) :
            # _FontSelectField se charge lui-meme de ne pas afficher deux
            # fois la police auto-detectee (une fois sous son vrai nom pour
            # "Systeme", une fois comme entree normale) SANS retirer cette
            # entree des valeurs valides — sinon un choix explicite qui
            # coincide avec l'auto-detection se ferait silencieusement
            # requalifier en "Systeme" a la prochaine sauvegarde.
            current_family = conf.get("family") or "Systeme"
            font_select = _FontSelectField(_font_choices(), current_family, width=126, auto_label=auto_label)
            font_cell = QWidget()
            font_cell.setFixedWidth(146)
            font_cell_l = QHBoxLayout(font_cell)
            font_cell_l.setContentsMargins(10, 0, 10, 0)
            font_cell_l.addWidget(font_select)
            row_l.addWidget(font_cell, 0)

            # box_width 32 (comme les autres champs a unite courte) etait
            # trop etroit pour 2 chiffres (10-20) : un nombre aligne a
            # droite qui deborde se fait couper a GAUCHE plutot qu'a droite,
            # donc "12" perdait son "1" et n'affichait plus que "2" — cause
            # du "on passe de 9 a 0" signale par l'utilisateur.
            size_field = _SliderField(4, 20, int(conf.get("size", 12)), unit="", slider_width=60, box_width=42)
            size_cell = QWidget()
            size_cell.setFixedWidth(132)
            size_cell_l = QHBoxLayout(size_cell)
            size_cell_l.setContentsMargins(10, 0, 10, 0)
            size_cell_l.addWidget(size_field)
            row_l.addWidget(size_cell, 0)

            bold_check = _CheckSquare(bool(conf.get("bold", False)))
            bold_cell = QWidget()
            bold_cell.setFixedWidth(46)
            bold_cell_l = QHBoxLayout(bold_cell)
            bold_cell_l.setContentsMargins(0, 0, 0, 0)
            bold_cell_l.setAlignment(Qt.AlignCenter)
            bold_cell_l.addWidget(bold_check)
            row_l.addWidget(bold_cell, 0)

            color_field = _ColorField(conf.get("color") or "#7d858b", swatch_size=22, hex_box=False)
            color_cell = QWidget()
            color_cell.setFixedWidth(56)
            color_cell_l = QHBoxLayout(color_cell)
            color_cell_l.setContentsMargins(0, 0, 0, 0)
            color_cell_l.setAlignment(Qt.AlignCenter)
            color_cell_l.addWidget(color_field)
            row_l.addWidget(color_cell, 0)

            aa_seg = _Segmented(list(SMOOTHING_CHOICES), SMOOTHING_LABELS_SHORT,
                                conf.get("smoothing") or "current", height=24, seg_width=44)
            aa_cell = QWidget()
            aa_cell.setFixedWidth(156)
            aa_cell_l = QHBoxLayout(aa_cell)
            aa_cell_l.setContentsMargins(10, 0, 10, 0)
            aa_cell_l.addWidget(aa_seg)
            row_l.addWidget(aa_cell, 0)

            layout.addWidget(row)

            entry = {
                "font": font_select, "size": size_field, "bold": bold_check,
                "color": color_field, "aa": aa_seg, "custom": conf.get("custom", False),
            }
            self.role_rows[key] = entry

            def _mark_custom(_x=None, e=entry):
                e["custom"] = True
                self.changed.emit()

            font_select.changed.connect(_mark_custom)
            size_field.valueChanged.connect(_mark_custom)
            bold_check.toggled.connect(_mark_custom)
            color_field.changed.connect(_mark_custom)
            aa_seg.changed.connect(_mark_custom)

        # -- barre d'apercu --
        preview = QWidget()
        preview.setObjectName("FontPreviewBar")
        preview.setAttribute(Qt.WA_StyledBackground, True)
        # Scope a #FontPreviewBar : sinon le filet cascade sur tag/name1/
        # name2/name3 ci-dessous.
        preview.setStyleSheet(
            f"#FontPreviewBar {{ background: {M['preview_bg']}; border: 1px solid {M['preview_border']}; }}"
        )
        preview.setFixedHeight(46)
        pv_l = QHBoxLayout(preview)
        pv_l.setContentsMargins(14, 0, 14, 0)
        pv_l.setSpacing(16)
        tag = QLabel("APERCU")
        tag.setFont(_qfont(9, 600))
        tag.setStyleSheet(f"color: {M['label_dim']}; background: transparent;")
        divider = QFrame()
        divider.setFixedSize(1, 24)
        divider.setStyleSheet(f"background: {M['panel_border']};")
        name1 = QLabel("asset__spaceship_01")
        name1.setFont(_qfont(12, 600))
        name1.setStyleSheet(f"color: {M['group_title']}; background: transparent;")
        name2 = QLabel("foot.001.OBJ")
        name2.setFont(_qfont(12, 400, mono=True))
        name2.setStyleSheet(f"color: #b3babf; background: transparent;")
        name3 = QLabel("121.7 KB \u00b7 v004")
        name3.setFont(_qfont(11, 400, mono=True))
        name3.setStyleSheet(f"color: #6a7278; background: transparent;")
        pv_l.addWidget(tag)
        pv_l.addWidget(divider)
        pv_l.addWidget(name1)
        pv_l.addWidget(name2)
        pv_l.addWidget(name3)
        pv_l.addStretch(1)
        layout.addSpacing(14)
        layout.addWidget(preview)
        layout.addStretch(1)

    def value(self) -> dict[str, dict]:
        out = {}
        for key, entry in self.role_rows.items():
            family = entry["font"].value()
            out[key] = {
                "family": "" if family == "Systeme" else family,
                "size": entry["size"].value(),
                "bold": entry["bold"].isChecked(),
                "smoothing": entry["aa"].value(),
                "color": entry["color"].value(),
                "custom": entry["custom"],
            }
        return out


# ==========================================================================
# Page "Couleurs de l'interface" — grille 2 colonnes
# ==========================================================================

class _ColorGrid(QWidget):
    changed = Signal()

    def __init__(self, colors: dict, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        wrap = QWidget()
        wrap.setStyleSheet(f"background: {M['panel_border']};")
        grid = QGridLayout(wrap)
        grid.setContentsMargins(1, 1, 1, 1)
        grid.setHorizontalSpacing(1)
        grid.setVerticalSpacing(1)
        self.fields: dict[str, _ColorField] = {}
        for i, (key, label, note) in enumerate(COLOR_FIELDS):
            cell = QWidget()
            cell.setStyleSheet(f"background: {M['table_row_b']};")
            cell_l = QHBoxLayout(cell)
            cell_l.setContentsMargins(10, 7, 10, 7)
            cell_l.setSpacing(10)
            field = _ColorField(colors.get(key, "#000000"), swatch_size=24, hex_box=False)
            self.fields[key] = field
            cell_l.addWidget(field)
            text_block = QWidget()
            text_l = QVBoxLayout(text_block)
            text_l.setContentsMargins(0, 0, 0, 0)
            text_l.setSpacing(1)
            name = QLabel(label)
            name.setFont(_qfont(11, 400))
            name.setStyleSheet(f"color: {M['row_label']}; background: transparent;")
            name.setWordWrap(False)
            sub = QLabel(note)
            sub.setFont(_qfont(9, 400))
            sub.setStyleSheet(f"color: {M['row_note']}; background: transparent;")
            text_l.addWidget(name)
            text_l.addWidget(sub)
            cell_l.addWidget(text_block, 1)
            hex_label = QLabel(colors.get(key, "").upper())
            hex_label.setFont(_qfont(10, 400, mono=True))
            hex_label.setStyleSheet(f"color: {M['table_head_fg']}; background: transparent;")
            cell_l.addWidget(hex_label)
            field.changed.connect(lambda v, hl=hex_label: hl.setText(v.upper()))
            field.changed.connect(lambda _: self.changed.emit())
            row, col = divmod(i, 2)
            grid.addWidget(cell, row, col)
        outer.addWidget(wrap)

    def value(self) -> dict[str, str]:
        return {key: field.value() for key, field in self.fields.items()}


# ==========================================================================
# Fenetre principale (frameless, meme chrome que le navigateur principal)
# ==========================================================================

class _SettingsTitleBar(QWidget):
    closeClicked = Signal()

    def __init__(self, dialog: QDialog, parent=None):
        super().__init__(parent)
        self._dialog = dialog
        self.setFixedHeight(28)
        # objectName + selecteur ID + WA_StyledBackground : sans ca, une
        # regle "nue" (sans selecteur) posee sur une SOUS-CLASSE de QWidget
        # ne se peint pas du tout OU (pire, une fois l'attribut seul ajoute
        # sans le ciblage par id) se propage a l'enfant sans bordure propre
        # le plus proche (ici title_label), qui se retrouve souligne sur sa
        # seule largeur de texte au lieu du filet courant sur toute la barre
        # — exactement la ligne partielle signalee.
        self.setObjectName("SettingsTitleBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#SettingsTitleBar {{ background: {M['titlebar_bg']}; border-bottom: 1px solid {M['panel_border']}; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(9)
        icon = QLabel()
        icon.setFixedSize(9, 9)
        icon.setStyleSheet(f"border: 1px solid {M['close_fg']}; background: transparent;")
        self.title_label = QLabel("Parametres \u2014 Pipeline Browser")
        self.title_label.setFont(_qfont(11, 400))
        self.title_label.setStyleSheet(f"color: {M['title_fg']}; background: transparent;")
        self.dirty_label = QLabel("")
        self.dirty_label.setFont(_qfont(10, 400, mono=True))
        layout.addWidget(icon)
        layout.addWidget(self.title_label)
        layout.addStretch(1)
        layout.addWidget(self.dirty_label)
        self.close_btn = QPushButton("\u00d7")
        self.close_btn.setFixedSize(26, 20)
        self.close_btn.setCursor(Qt.ArrowCursor)
        self.close_btn.setFocusPolicy(Qt.NoFocus)
        self.close_btn.setFlat(True)
        self.close_btn.setFont(_qfont(11, 400, mono=True))
        self.close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: " + M["close_fg"] + "; }"
            "QPushButton:hover { background: " + M["close_hover_bg"] + "; color: " + M["close_hover_fg"] + "; }"
        )
        self.close_btn.clicked.connect(self.closeClicked.emit)
        layout.addWidget(self.close_btn)
        self.set_dirty(False)

    def set_dirty(self, dirty: bool):
        self.dirty_label.setText("modifications non enregistrees" if dirty else "a jour")
        self.dirty_label.setStyleSheet(
            f"color: {M['dirty_fg'] if dirty else M['clean_fg']}; background: transparent;"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Voir app_style.start_native_move et la meme remarque dans
            # pipeline_browser.py.TitleBar.mousePressEvent.
            start_native_move(self._dialog)
            event.accept()
        else:
            super().mousePressEvent(event)


class SettingsWindow(QDialog):
    """Fenetre de parametres, reproduction fidele de la maquette html
    fournie. Chaque changement se previsualise en direct sur la fenetre
    principale (settingsChanged), sans toucher au disque ; Enregistrer
    persiste (settingsSaved)."""

    settingsChanged = Signal(dict)
    settingsSaved = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(1080, 800)

        self.settings = load_settings()
        self._original_settings = json.loads(json.dumps(self.settings))
        self._saved = False
        self._dirty = False
        self._current_preset = "Personnalise"

        # Le rafraichissement declenche par settingsChanged (recalcul complet
        # des colonnes dans la fenetre principale) est lourd : au fil d'un
        # glisser de slider, mouseMoveEvent tire des dizaines de crans par
        # seconde. L'appeler en direct depuis _on_live_change (donc depuis
        # la pile de mouseMoveEvent) empecherait Qt de repeindre le curseur
        # du slider tant que ce travail n'est pas fini. On le differe donc
        # TOUJOURS via ce timer (jamais d'appel synchrone), au plus une fois
        # toutes les 30ms tant que le slider bouge encore (~33 rafraichis-
        # sements/s, imperceptible), avec un dernier appel garanti sur la
        # valeur finale des que le mouvement s'arrete (voir _flush_live_apply).
        self._live_pending = False
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(30)
        self._live_timer.setSingleShot(True)
        self._live_timer.timeout.connect(self._flush_live_apply)

        self.panel = panel = QWidget(self)
        panel.setObjectName("Panel")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        self._apply_panel_radius(int(self.settings.get("window_radius", 0)))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)

        root = QVBoxLayout(panel)
        # Marge de 1px (= l'epaisseur du filet de #Panel, voir
        # _apply_panel_radius), PAS 0 : a marge nulle, les enfants
        # (titlebar, barre d'outils...) sont peints PAR-DESSUS la bordure du
        # panneau sur ses 4 cotes et la rendent invisible — meme bug, et
        # meme correctif, que #CentralFrame dans pipeline_browser.py.
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        self.titlebar = _SettingsTitleBar(self)
        self.titlebar.closeClicked.connect(self.reject)
        root.addWidget(self.titlebar)

        root.addWidget(self._build_toolbar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_nav())
        body.addWidget(self._build_pages(), 1)
        root.addLayout(body, 1)

        root.addWidget(self._build_bottom_bar())

        self._select_page(0)
        self._connect_live_updates()

    # -- barre d'outils (preset + recherche) --

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(36)
        bar.setStyleSheet(f"background: {M['toolbar_bg']};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)

        preset_box = QWidget()
        preset_box.setObjectName("PresetBox")
        preset_box.setAttribute(Qt.WA_StyledBackground, True)
        preset_box.setFixedHeight(24)
        # Scope a #PresetBox : sinon le filet cascade sur preset_tag
        # ci-dessous (qui pose deja son propre border-right, en double).
        preset_box.setStyleSheet(f"#PresetBox {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; }}")
        preset_l = QHBoxLayout(preset_box)
        preset_l.setContentsMargins(0, 0, 0, 0)
        preset_l.setSpacing(0)
        preset_tag = QLabel("PRESET")
        preset_tag.setFont(_qfont(9, 600))
        preset_tag.setStyleSheet(
            f"color: {M['label_dim']}; background: transparent; padding: 0 8px; "
            f"border-right: 1px solid {M['field_border']};"
        )
        preset_l.addWidget(preset_tag)
        self.preset_btn = QPushButton()
        self.preset_btn.setFlat(True)
        self.preset_btn.setCursor(Qt.ArrowCursor)
        self.preset_btn.setFocusPolicy(Qt.NoFocus)
        self.preset_btn.setFont(_qfont(11, 400))
        self.preset_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: " + M["value_fg"] +
            "; padding: 0 8px; text-align: left; }"
            "QPushButton:hover { background: #1a1f24; }"
        )
        self.preset_btn.clicked.connect(self._open_preset_menu)
        preset_l.addWidget(self.preset_btn, 1)
        self._sync_preset_label()
        layout.addWidget(preset_box)

        save_as_btn = _Btn("Enregistrer sous", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"])
        save_as_btn.clicked.connect(self._save_preset_as)
        import_btn = _Btn("Importer", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"])
        import_btn.clicked.connect(self._import_settings)
        export_btn = _Btn("Exporter", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"])
        export_btn.clicked.connect(self._export_settings)
        layout.addWidget(save_as_btn)
        layout.addWidget(import_btn)
        layout.addWidget(export_btn)
        layout.addStretch(1)

        search_box = QWidget()
        search_box.setObjectName("SearchBox")
        search_box.setAttribute(Qt.WA_StyledBackground, True)
        search_box.setFixedSize(210, 24)
        # Scope a #SearchBox : sans lui, le filet cascade sur `slash`
        # ci-dessous, dessinant un contour autour du seul "/" — exactement
        # ce que montrait la capture de l'utilisateur.
        search_box.setStyleSheet(f"#SearchBox {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; }}")
        search_l = QHBoxLayout(search_box)
        search_l.setContentsMargins(8, 0, 8, 0)
        search_l.setSpacing(7)
        slash = QLabel("/")
        slash.setFont(_qfont(10, 400, mono=True))
        slash.setStyleSheet(f"color: {M['slash']}; background: transparent;")
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Rechercher un parametre")
        self.search_field.setFont(_qfont(11, 400))
        self.search_field.setFrame(False)
        self.search_field.setStyleSheet(
            f"background: transparent; border: none; color: {M['value_fg']};"
        )
        search_l.addWidget(slash)
        search_l.addWidget(self.search_field)
        self.search_field.textChanged.connect(self._filter_nav)
        layout.addWidget(search_box)
        return bar

    def _sync_preset_label(self):
        self.preset_btn.setText(self._current_preset + "  \u25be")

    def _open_preset_menu(self):
        menu = QMenu(self)
        menu.setFont(_qfont(11, 400))
        menu.setStyleSheet(
            f"QMenu {{ background: {M['toolbar_bg']}; border: 1px solid {M['field_border']}; padding: 4px 0; }}"
            f"QMenu::item {{ padding: 5px 16px; color: {M['value_fg']}; }}"
            f"QMenu::item:selected {{ background: {M['accent']}; color: {M['accent_fg']}; }}"
        )
        presets = _load_presets()
        if not presets:
            action = menu.addAction("(aucun preset enregistre)")
            action.setEnabled(False)
        for name in presets:
            action = menu.addAction(name)
            action.triggered.connect(lambda _c=False, n=name, p=presets: self._load_preset(n, p))
        menu.exec(self.preset_btn.mapToGlobal(QPoint(0, self.preset_btn.height())))

    def _load_preset(self, name: str, presets: dict):
        data = presets.get(name)
        if not data:
            return
        merged = json.loads(json.dumps(DEFAULT_SETTINGS))
        merged.update(data)
        self._apply_values_to_controls(merged)
        self._current_preset = name
        self._sync_preset_label()
        self._on_live_change()

    def _save_preset_as(self):
        name, ok = QInputDialog.getText(self, "Enregistrer sous", "Nom du preset :")
        if not ok or not name.strip():
            return
        presets = _load_presets()
        presets[name.strip()] = self._current_values()
        _save_presets(presets)
        self._current_preset = name.strip()
        self._sync_preset_label()

    def _import_settings(self):
        path, _filter = QFileDialog.getOpenFileName(self, "Importer des parametres", "", "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        merged = json.loads(json.dumps(DEFAULT_SETTINGS))
        merged.update(data)
        self._apply_values_to_controls(merged)
        self._current_preset = Path(path).stem
        self._sync_preset_label()
        self._on_live_change()

    def _export_settings(self):
        path, _filter = QFileDialog.getSaveFileName(self, "Exporter les parametres", "parametres.json", "JSON (*.json)")
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(self._current_values(), indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _apply_values_to_controls(self, data: dict):
        """Reapplique un dict complet de reglages sur TOUS les controles —
        utilise par le chargement d'un preset/import. Reconstruit les pages
        qui n'exposent pas de setter direct plutot que d'ajouter un setter
        a chaque widget custom, plus simple et tout aussi fiable."""
        self.root_field.setText(data.get("root_path", DEFAULT_SETTINGS["root_path"]))
        self.scale_field.setValue(int(data.get("ui_scale", 100)))
        self.save_mode_select.setValue(data.get("save_mode", "Par utilisateur"))
        self.external_path_field.setText(data.get("external_settings_path", ""))
        self.window_radius_toggle.setChecked(int(data.get("window_radius", 0)) > 0)
        self.header_height_field.setValue(int(data.get("header_height", 26)))
        self.button_radius_field.setValue(int(data.get("button_radius", 0)))
        self.preview_pad_field.setValue(int(data.get("preview_pad", 0)))
        self.preview_radius_field.setValue(int(data.get("preview_radius", 0)))
        for key, field in self.color_grid.fields.items():
            new_val = (data.get("colors") or {}).get(key)
            if new_val:
                field._value = new_val
                field._refresh()

    # -- navigation --

    def _build_nav(self) -> QWidget:
        nav_wrap = QWidget()
        nav_wrap.setObjectName("NavWrap")
        nav_wrap.setFixedWidth(218)
        # Selecteur scope a #NavWrap : une regle nue cascaderait en QSS sur
        # chaque _NavRow (et ses QLabel internes), y dessinant un border-right
        # fantome a leur propre bord droit — memes filets parasites que le
        # border-bottom non scope de _Row (voir plus haut).
        nav_wrap.setStyleSheet(
            f"#NavWrap {{ background: {M['nav_bg']}; border-right: 1px solid {M['panel_border']}; }}"
        )
        layout = QVBoxLayout(nav_wrap)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(0)

        self._nav_rows: list[_NavRow] = []
        self._pages: list[tuple[str, str, QWidget]] = []  # (nav_label, page_id) filled in _build_pages
        self._page_specs = [
            ("General", "6", False),
            ("Couleurs de l'interface", str(len(COLOR_FIELDS)), False),
            ("Polices de caracteres", "8", False),
            ("Boutons", "1", False),
            ("Colonne Type", "3", True),
            ("Colonne Projets", "5", True),
            ("Colonne Sous-projet", "5", True),
            ("Colonne Logiciels", "5", True),
            ("Colonnes Contenu", "5", True),
            ("Images projets et sous-projets", "2", False),
        ]
        group_inserted = False
        for i, (label, count, in_columns_group) in enumerate(self._page_specs):
            if in_columns_group and not group_inserted:
                layout.addWidget(_nav_group_header("Colonnes"))
                group_inserted = True
            row = _NavRow(label, count, indent=in_columns_group)
            row.clicked.connect(lambda idx=i: self._select_page(idx))
            layout.addWidget(row)
            self._nav_rows.append(row)
        layout.addStretch(1)
        return nav_wrap

    def _select_page(self, index: int):
        for i, row in enumerate(self._nav_rows):
            row.setActive(i == index)
        self.stack_widgets[index].raise_()
        self.pages_area.setCurrentIndex(index)

    def _filter_nav(self, text: str):
        text = text.strip().lower()
        for row, (label, _count, _grp) in zip(self._nav_rows, self._page_specs):
            row.setFilterMatch(not text or text in label.lower())

    # -- pages --

    def _build_pages(self) -> QWidget:
        from PySide6.QtWidgets import QStackedWidget
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.pages_area = QStackedWidget()
        self.stack_widgets: list[QWidget] = []

        page_defs = [
            ("General", "Racine, echelle, sauvegarde, entete des colonnes", self._page_general),
            ("Couleurs de l'interface", "Cliquez une pastille pour parcourir la palette", self._page_colors),
            ("Polices de caracteres", "Un role par ligne : police, taille 4-20, gras, couleur, lissage", self._page_fonts),
            ("Boutons", "Geometrie des boutons de la barre d'outils", self._page_buttons),
            ("Colonne Type", "Colonne sans vignette", lambda: self._page_column("Type", False, False)),
            ("Colonne Projets", "Colonne a vignette \u2014 source du lien pour les sous-projets", lambda: self._page_column("Projets", True, False)),
            ("Colonne Sous-projet", "Vignette liee aux projets par defaut", lambda: self._page_column("Sous-projet", True, True)),
            ("Colonne Logiciels", "Icones logicielles", lambda: self._page_column("Logiciels", True, False, True)),
            ("Colonnes Contenu", "Toutes les colonnes de contenu au-dela des logiciels", lambda: self._page_column("Contenu", True, False, True)),
            ("Images projets et sous-projets", "Padding sur les 4 cotes \u2014 reglage global des vignettes de projet", self._page_preview),
        ]

        for title, hint, builder in page_defs:
            page_wrap = QWidget()
            page_l = QVBoxLayout(page_wrap)
            page_l.setContentsMargins(0, 0, 0, 0)
            page_l.setSpacing(0)
            page_l.addWidget(_page_header(title, hint))

            scroller = QScrollArea()
            scroller.setWidgetResizable(True)
            scroller.setFrameShape(QFrame.NoFrame)
            scroller.setStyleSheet(f"background: {M['panel_bg']};")
            inner = QWidget()
            inner_l = QVBoxLayout(inner)
            inner_l.setContentsMargins(18, 14, 18, 20)
            inner_l.addWidget(builder())
            scroller.setWidget(inner)
            page_l.addWidget(scroller, 1)

            self.pages_area.addWidget(page_wrap)
            self.stack_widgets.append(page_wrap)

        layout.addWidget(self.pages_area)
        return container

    def _page_general(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        group = _Group()
        self.root_field = QLineEdit(self.settings["root_path"])
        self.root_field.setFont(_qfont(12, 400, mono=True))
        self.root_field.setFixedHeight(25)
        self.root_field.setStyleSheet(
            f"background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"color: {M['value_muted']}; padding: 0 8px;"
        )
        browse_btn = _Btn("Parcourir", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25)
        browse_btn.clicked.connect(self._browse_root)
        root_row = QWidget()
        root_row_l = QHBoxLayout(root_row)
        root_row_l.setContentsMargins(0, 0, 0, 0)
        root_row_l.setSpacing(6)
        root_row_l.addWidget(self.root_field)
        root_row_l.addWidget(browse_btn)
        root_row.setFixedWidth(340)
        group.add(_Row("Racine par defaut", root_row))

        self.scale_field = _SliderField(50, 200, int(self.settings["ui_scale"]), "%")
        group.add(_Row("Scale general de l'interface", self.scale_field,
                        "Multiplie la taille de toutes les polices"))

        self.save_mode_select = _SelectField(SAVE_MODES, self.settings["save_mode"])
        group.add(_Row("Systeme de sauvegarde des differentes interfaces", self.save_mode_select))

        self.external_path_field = QLineEdit(self.settings.get("external_settings_path", ""))
        self.external_path_field.setFont(_qfont(11, 400, mono=True))
        self.external_path_field.setFixedHeight(25)
        self.external_path_field.setStyleSheet(
            f"background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"color: {M['value_muted']}; padding: 0 8px;"
        )
        external_btn = _Btn("...", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25, padding="0")
        external_btn.setFixedWidth(30)
        external_btn.clicked.connect(self._browse_external_settings)
        external_row = QWidget()
        external_row_l = QHBoxLayout(external_row)
        external_row_l.setContentsMargins(0, 0, 0, 0)
        external_row_l.setSpacing(6)
        external_row_l.addWidget(self.external_path_field)
        external_row_l.addWidget(external_btn)
        external_row.setFixedWidth(250)
        self._external_row_widget = _Row("Fichier externe (si choisi ci-dessus)", external_row, last=True)
        group.add(self._external_row_widget)
        layout.addWidget(group)

        header_group = _Group("Entete des colonnes")
        self.header_height_field = _SliderField(18, 56, int(self.settings["header_height"]))
        header_group.add(_Row("Hauteur de l'entete", self.header_height_field))
        # "colhead" : meme role que la table de polices utilise pour
        # "Entete de colonnes" (voir _ROLE_KEY_TO_STYLE_ROLE) — l'entete de
        # colonne suit la meme police, cette page ne fait que la surcharger
        # globalement (voir header_font_family dans apply_all_settings).
        self.header_font_select = _FontSelectField(
            _font_choices(), self.settings.get("header_font_family") or "Systeme",
            width=200, auto_label=auto_family_for_role("colhead"),
        )
        header_group.add(_Row("Police de caractere", self.header_font_select,
                              "Taille/gras/couleur/lissage : page Polices > Entete de colonnes", last=True))
        layout.addWidget(header_group)

        window_group = _Group()
        # Toggle plutot qu'un slider en pixels : Windows n'offre de toute
        # facon aucun controle fin du rayon cote DWM (juste rond/pas-rond,
        # voir apply_dwm_frame dans app_style.py) — un curseur laissait
        # croire a un reglage precis qui ne l'etait pas vraiment.
        self.window_radius_toggle = _Toggle(
            int(self.settings["window_radius"]) > 0, on_label="arrondi", off_label="carre"
        )
        window_group.add(_Row("Coins de la fenetre principale", self.window_radius_toggle, last=True))
        layout.addWidget(window_group)

        layout.addStretch(1)
        self.save_mode_select.changed.connect(self._update_save_mode_row)
        self._update_save_mode_row(self.save_mode_select.value())
        return wrap

    def _update_save_mode_row(self, *_args):
        self._external_row_widget.setVisible(self.save_mode_select.value() == "Fichier externe")

    def _page_colors(self) -> QWidget:
        self.color_grid = _ColorGrid(self.settings["colors"])
        return self.color_grid

    def _page_fonts(self) -> QWidget:
        self.font_table = _FontTable(self.settings)
        return self.font_table

    def _page_buttons(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        group = _Group()
        self.button_radius_field = _SliderField(0, 16, int(self.settings["button_radius"]))
        group.add(_Row("Border radius", self.button_radius_field, last=True))
        layout.addWidget(group)
        layout.addStretch(1)
        return wrap

    def _page_column(self, title: str, show_images: bool, linkable: bool, mixed_rows: bool = False) -> QWidget:
        page = _ColumnPage(self.settings["columns"][title], show_images, linkable, mixed_rows)
        if not hasattr(self, "column_pages"):
            self.column_pages = {}
        self.column_pages[title] = page
        return page

    def _page_preview(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        hint = QLabel("Padding et rayon de la grande vignette de l'apercu empile "
                      "(sous la liste Projets/Sous-projet, ou dans Logiciels).")
        hint.setWordWrap(True)
        hint.setFont(_qfont(10, 400))
        hint.setStyleSheet(f"color: {M['row_note']}; background: transparent;")
        layout.addWidget(hint)
        group = _Group()
        self.preview_pad_field = _SliderField(0, 24, int(self.settings["preview_pad"]))
        group.add(_Row("Padding (4 cotes)", self.preview_pad_field))
        self.preview_radius_field = _SliderField(0, 32, int(self.settings["preview_radius"]))
        group.add(_Row("Border radius", self.preview_radius_field, last=True))
        layout.addWidget(group)
        layout.addStretch(1)
        return wrap

    # -- barre du bas --

    def _build_bottom_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(46)
        bar.setStyleSheet(f"background: {M['toolbar_bg']}; border-top: 1px solid {M['panel_border']};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(8)

        reset_btn = _Btn("Valeurs par defaut", "transparent", M["btn_border"], M["reset_fg"], M["btn_bg"], height=27)
        reset_btn.clicked.connect(self._reset_defaults)
        layout.addWidget(reset_btn)

        self.footer_label = QLabel()
        self.footer_label.setFont(_qfont(10, 400, mono=True))
        self.footer_label.setStyleSheet(f"color: {M['group_note']}; background: transparent;")
        self._refresh_footer()
        layout.addWidget(self.footer_label)
        layout.addStretch(1)

        cancel_btn = _Btn("Annuler", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=27, padding="0 13px")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        save_btn = _Btn("Enregistrer", M["accent"], M["accent_border"], M["accent_fg"], M["accent_hover"],
                        height=27, weight=600, padding="0 17px")
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn)
        return bar

    def _refresh_footer(self):
        path = _settings_path(self._current_values() if hasattr(self, "root_field") else self.settings)
        self.footer_label.setText(f"{path.name} \u00b7 {path.parent}")

    def _reset_defaults(self):
        defaults = json.loads(json.dumps(DEFAULT_SETTINGS))
        defaults["root_path"] = self.settings.get("root_path", DEFAULT_SETTINGS["root_path"])
        self._apply_values_to_controls(defaults)
        self._on_live_change()

    # -- actions --

    def _browse_root(self):
        chosen = QFileDialog.getExistingDirectory(self, "Racine par defaut", self.root_field.text())
        if chosen:
            self.root_field.setText(chosen)

    def _browse_external_settings(self):
        chosen, _filter = QFileDialog.getSaveFileName(
            self, "Fichier de parametres externe", self.external_path_field.text(), "JSON (*.json)"
        )
        if chosen:
            self.external_path_field.setText(chosen)

    def _on_radius_toggled(self, checked: bool):
        self._apply_panel_radius(WINDOW_ROUNDED_RADIUS if checked else 0)

    def _apply_panel_radius(self, radius: int):
        """Coins arrondis du panneau lui-meme (voir WA_TranslucentBackground
        sur ce QDialog frameless) — la fenetre de parametres doit suivre le
        meme reglage "Border radius de la fenetre principale" que la fenetre
        du navigateur, pas rester a angles droits.

        apply_dwm_frame (voir app_style.py) est indispensable ici aussi :
        sans lui, DWM arrondit deja cette fenetre de lui-meme par defaut
        (accent systeme, meme sur cette boite de dialogue), ce qui
        contredirait un radius=0 tout comme sur la fenetre principale avant
        correction — cette fenetre restait la seule non couverte."""
        self.panel.setStyleSheet(
            f"#Panel {{ background: {M['panel_bg']}; border: 1px solid {M['panel_border']}; "
            f"border-radius: {radius}px; }}"
        )
        apply_dwm_frame(self, radius, M["panel_border"])

    def _connect_live_updates(self):
        self.scale_field.valueChanged.connect(self._on_live_change)
        self.save_mode_select.changed.connect(self._on_live_change)
        self.external_path_field.textChanged.connect(self._on_live_change)
        self.window_radius_toggle.toggled.connect(self._on_radius_toggled)
        self.window_radius_toggle.toggled.connect(self._on_live_change)
        self.header_height_field.valueChanged.connect(self._on_live_change)
        self.header_font_select.changed.connect(self._on_live_change)
        self.button_radius_field.valueChanged.connect(self._on_live_change)
        self.preview_pad_field.valueChanged.connect(self._on_live_change)
        self.preview_radius_field.valueChanged.connect(self._on_live_change)
        self.color_grid.changed.connect(self._on_live_change)
        self.font_table.changed.connect(self._on_live_change)
        for page in self.column_pages.values():
            page.changed.connect(self._on_live_change)

    def _current_values(self) -> dict:
        columns = {title: page.value() for title, page in self.column_pages.items()}
        header_family = self.header_font_select.value()
        return {
            "root_path": self.root_field.text().strip() or DEFAULT_SETTINGS["root_path"],
            "ui_scale": self.scale_field.value(),
            "save_mode": self.save_mode_select.value(),
            "external_settings_path": self.external_path_field.text().strip(),
            "window_radius": WINDOW_ROUNDED_RADIUS if self.window_radius_toggle.isChecked() else 0,
            "header_height": self.header_height_field.value(),
            "header_font_family": "" if header_family == "Systeme" else header_family,
            "colors": self.color_grid.value(),
            **self.font_table.value(),
            "button_radius": self.button_radius_field.value(),
            "columns": columns,
            "preview_pad": self.preview_pad_field.value(),
            "preview_radius": self.preview_radius_field.value(),
        }

    def _on_live_change(self, *_args):
        self._dirty = True
        self.titlebar.set_dirty(True)
        self._refresh_footer()
        self._live_pending = True
        # Toujours differe via le timer, MEME pour le tout premier cran :
        # appeler _flush_live_apply() directement ici l'executerait de
        # facon synchrone dans la pile de mouseMoveEvent, avant que Qt ait
        # pu redessiner le curseur du slider (son update() n'est que
        # planifie) — c'est ce qui donnait l'impression que le slider
        # lui-meme trainait derriere la souris. Le timer (intervalle fixe,
        # voir __init__) ne se declenche qu'une fois revenu dans la boucle
        # d'evenements, apres que Qt a eu l'occasion de peindre.
        if not self._live_timer.isActive():
            self._live_timer.start()

    def _flush_live_apply(self):
        if not self._live_pending:
            return
        self._live_pending = False
        self.settingsChanged.emit(self._current_values())

    def _on_save(self):
        self.settings = self._current_values()
        save_settings(self.settings)
        self._saved = True
        self._dirty = False
        self.titlebar.set_dirty(False)
        self.settingsSaved.emit(self.settings)
        self.accept()

    def reject(self):
        if not self._saved:
            self.settingsChanged.emit(self._original_settings)
        super().reject()


def main():
    from app_style import apply_style
    app = QApplication(sys.argv)
    apply_style(app)
    win = SettingsWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
