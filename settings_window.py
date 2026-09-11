#!/usr/bin/env python3
"""
Fenetre de parametres de Pipeline Browser.

Reproduction fidele de la maquette html "Parametres generaux" (refonte totale,
remplace l'ancienne fenetre a navigation laterale + pages) : meme barre de
titre, meme barre d'outils presets, un unique panneau defilant a sections
(Application / Polices / Couleurs / Entetes / Geometrie), meme barre du bas
(Valeurs par defaut / Appliquer / Annuler / Enregistrer). La maquette avait
en plus un panneau "Apercu en direct" a droite (fenetre miniature simulee) —
supprime a la demande de l'utilisateur, la previsualisation en direct reste
assuree sur la VRAIE fenetre principale (voir settingsChanged).

La maquette n'expose que 8 couleurs semantiques, 4 roles de police (famille
seule, sans taille/gras/couleur/lissage) et aucun reglage par colonne — bien
moins que ce que l'appli sait faire (29 couleurs, 8 roles de police detailles,
5 pages de geometrie de colonnes, mode de sauvegarde...). Choix assume (voir
l'echange avec l'utilisateur) : fidelite totale a la maquette. Les reglages
qui n'y figurent plus RESTENT dans le fichier de reglages et continuent
d'etre appliques tels quels (voir DEFAULT_SETTINGS et apply_all_settings dans
pipeline_browser.py) — simplement plus aucune UI ici pour les changer, ils
restent fixes a leur valeur actuelle. Voir SEMANTIC_COLOR_SLOTS (app_style.py)
pour le detail du mappage des 8 couleurs vers les cles reelles de C.

Les couleurs/tailles ci-dessous (voir M) sont la palette FIXE de cette
fenetre, independante de celle (modifiable en direct) du navigateur
principal — memes raisons que l'ancienne fenetre : une fenetre de parametres
qui s'auto-appliquerait ses propres reglages pourrait se rendre illisible.

    python settings_window.py   (pour previsualiser la fenetre seule)
"""

import json
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIntValidator, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QDialog,
    QFileDialog,
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
    SEMANTIC_COLOR_SLOTS,
    apply_dwm_frame,
    auto_family_for_role,
    installed_font_families,
    resize_hit_test,
    start_native_move,
)

# ==========================================================================
# Palette et metriques FIXES de cette fenetre (voir la remarque de tete de
# fichier) — recopiees de la maquette html.
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
    "dirty_border": "#5c4f2a",
    "dirty_dot": "#c2914a",
    "clean_dot": "#3f8f6b",
    "close_hover_bg": "#232a30",
    "close_fg": "#7d858b",
    "close_hover_fg": "#d6d9dc",
    "dot_border": "#4d565c",
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
    "placeholder": "#5d656b",
    "section_title": "#5f9bd0",
    "group_title": "#d6d9dc",
    "group_note": "#5d656b",
    "row_label": "#cdd2d6",
    "row_label_off": "#7a828a",
    "row_note": "#5d656b",
    "value_text": "#e0e4e7",
    "value_text_off": "#6a7278",
    "unit": "#5d656b",
    "track_bg": "#25292d",
    "knob_off": "#5d656b",
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
    "preview_border": "#23282c",
    "reset_fg": "#9aa2a9",
    "reset_hover_fg": "#c8ced3",
    "edge_off": "#262a2e",
    "edge_hint": "#4c545a",
    "dash": "#454d53",
}

# ==========================================================================
# Persistance — un seul emplacement (voir la remarque de tete de fichier :
# le mode de sauvegarde a 4 positions de l'ancienne fenetre a disparu avec
# la maquette, qui n'a qu'un reglage "Preset" ; le fichier actif reste celui
# deja utilise aujourd'hui, aucun changement de comportement).
# ==========================================================================

_SCRIPT_DIR = Path(__file__).resolve().parent
_PER_USER_PATH = _SCRIPT_DIR / "pipeline_settings.json"
_PRESETS_PATH = _SCRIPT_DIR / "pipeline_settings.presets.json"

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
    "window_radius": 0,
    "header_height": 26,
    "header_padding": 0,
    "header_color": "skinN1",
    "header_radius": 0,
    "header_edges": {"top": False, "right": False, "bottom": True, "left": False},
    "header_font_family": "",   # fige : plus d'UI (voir remarque de tete de fichier)
    "input_frame": True,
    "input_radius": 0,
    "button_frame": True,
    "button_radius": 0,
    "colors": {key: C[key] for key, _, _ in COLOR_FIELDS},
    "font_main": dict(_DEFAULT_FONT),
    "font_titles": dict(_DEFAULT_FONT),
    "font_folders": dict(_DEFAULT_FONT),    # fige
    "font_files": dict(_DEFAULT_FONT),
    "font_buttons": dict(_DEFAULT_FONT),    # fige
    "font_colhead": dict(_DEFAULT_FONT),    # fige
    "font_info": dict(_DEFAULT_FONT),
    "font_info2": dict(_DEFAULT_FONT),      # fige
    "columns": json.loads(json.dumps(DEFAULT_COLUMNS)),   # fige
    "preview_pad": 0,     # fige
    "preview_radius": 0,  # fige
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
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    try:
        _PER_USER_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PER_USER_PATH.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
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
# Petits widgets reproduisant les controles de la maquette.
# ==========================================================================

def _qfont(size: int, weight: int = 400, mono: bool = False, tracking: float = 0.0) -> QFont:
    f = QFont("Consolas" if mono else "Segoe UI")
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    if tracking:
        f.setLetterSpacing(QFont.AbsoluteSpacing, tracking)
    return f


class _Btn(QPushButton):
    """Bouton rectangulaire plat (voir la meme classe dans l'ancienne
    fenetre — inchangee, deja fidele)."""

    def __init__(self, text: str, bg: str, border: str, fg: str, hover: str,
                 height: int = 24, weight: int = 500, padding: str = "0 11px", parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(height)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFont(_qfont(11, weight))
        border_rule = f"border: 1px solid {border};" if border else "border: none;"
        self.setStyleSheet(
            f"QPushButton {{ background: {bg}; {border_rule} color: {fg}; padding: {padding}; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
        )


class _MiniSlider(QWidget):
    """Slider peint a la main : filet 3px + curseur 3x14."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, value: int, width: int = 170, parent=None):
        super().__init__(parent)
        self._min, self._max = minimum, maximum
        self._value = max(minimum, min(maximum, value))
        self.setFixedSize(width, 22)
        self.setCursor(Qt.ArrowCursor)

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
        fill_w = round(self._pct() * self.width())
        if fill_w > 0:
            p.fillRect(0, mid_y - 1, fill_w, 3, QColor(M["accent"]))
        knob_x = max(0, min(self.width() - 3, fill_w - 1))
        p.fillRect(knob_x, mid_y - 7, 3, 14, QColor("#8fb4d5"))
        p.end()


class _SliderField(QWidget):
    """Slider + boite de lecture/saisie numerique a droite (unite comprise)."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, value: int, unit: str = "px",
                 slider_width: int = 170, box_width: int = 68, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.slider = _MiniSlider(minimum, maximum, value, slider_width)
        box = QWidget()
        box.setObjectName("SliderValueBox")
        box.setAttribute(Qt.WA_StyledBackground, True)
        box.setFixedSize(box_width, 25)
        box.setStyleSheet(f"#SliderValueBox {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; }}")
        box_l = QHBoxLayout(box)
        box_l.setContentsMargins(7, 0, 7, 0)
        box_l.setSpacing(4)
        self._min, self._max = minimum, maximum
        self.value_label = QLineEdit(str(value))
        self.value_label.setFont(_qfont(11, 400, mono=True))
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value_label.setFrame(False)
        self.value_label.setValidator(QIntValidator(self.value_label))
        self.value_label.setStyleSheet(f"background: transparent; border: none; padding: 0; color: {M['value_text']};")
        self.value_label.editingFinished.connect(self._on_text_edited)
        unit_label = QLabel(unit)
        unit_label.setFont(_qfont(9, 400, mono=True))
        unit_label.setStyleSheet(f"color: {M['unit']}; background: transparent;")
        box_l.addWidget(self.value_label, 1)
        box_l.addWidget(unit_label)
        layout.addWidget(self.slider)
        layout.addWidget(box)
        self.slider.valueChanged.connect(self._on_change)

    def _on_change(self, value: int):
        self.value_label.setText(str(value))
        self.valueChanged.emit(value)

    def _on_text_edited(self):
        text = self.value_label.text().strip()
        try:
            value = max(self._min, min(self._max, int(text)))
        except ValueError:
            value = self.slider.value()
        self.slider.setValue(value)
        self.value_label.setText(str(self.slider.value()))

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value: int):
        self.slider.setValue(value)


class _SelectField(QPushButton):
    """Bouton "select" (valeur + chevron), ouvre un QMenu."""

    changed = Signal(str)

    def __init__(self, options: list[str], current: str, width: int = 200, parent=None):
        super().__init__(parent)
        self._options = options
        self._value = current if current in options else options[0]
        self.setFixedSize(width, 25)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFont(_qfont(11, 400))
        self.setStyleSheet(
            f"QPushButton {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"color: {M['value_fg']}; text-align: left; padding: 0 8px; }}"
            f"QPushButton:hover {{ border-color: {M['field_border_hover']}; }}"
        )
        self.clicked.connect(self._open_menu)
        self._sync_text()

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
    """Variante de _SelectField pour choisir une police : vraie liste
    deroulante (scroll natif, molette comprise) ou chaque nom de police est
    rendu DANS cette police — voir la meme classe dans l'ancienne fenetre,
    logique inchangee."""

    def __init__(self, options: list[str], current: str, width: int = 200,
                 auto_label: str | None = None, parent=None):
        self._auto_label = auto_label
        super().__init__(options, current, width, parent)

    def _display_label(self, opt: str) -> str:
        if opt == "Systeme" and self._auto_label:
            return self._auto_label
        return opt

    def _sync_text(self):
        self.setText(self._display_label(self._value) + "  \u25be")

    def _open_menu(self):
        popup = QWidget(self, Qt.Popup)
        popup.setObjectName("FontPopup")
        popup.setAttribute(Qt.WA_StyledBackground, True)
        popup.setStyleSheet(f"#FontPopup {{ background: {M['toolbar_bg']}; border: 1px solid {M['field_border']}; }}")
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
                continue
            item = QListWidgetItem(self._display_label(opt))
            item.setData(Qt.UserRole, opt)
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


class _Toggle(QWidget):
    """Interrupteur peint a la main (piste 30x15 + curseur 11x11) + libelle
    d'etat a droite — utilise pour les cadres actif/sans de la page
    Geometrie."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, on_label="actif", off_label="sans", parent=None):
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
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#f2f6f9" if self._checked else M["knob_off"]))
        p.drawRect(knob_x, y + 2, 11, 11)
        p.setFont(_qfont(10, 400, mono=True))
        p.setPen(QColor(M["toggle_on_fg"] if self._checked else M["toggle_off_fg"]))
        p.drawText(38, 0, 40, self.height(), Qt.AlignVCenter | Qt.AlignLeft,
                   self._on_label if self._checked else self._off_label)
        p.end()


class _ColorField(QWidget):
    """Pastille cliquable (ouvre QColorDialog) + boite hexadecimale."""

    changed = Signal(str)

    def __init__(self, value: str, swatch_size: int = 24, parent=None):
        super().__init__(parent)
        self._value = value
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.swatch = QPushButton()
        self.swatch.setFixedSize(swatch_size, swatch_size)
        self.swatch.setCursor(Qt.ArrowCursor)
        self.swatch.setFocusPolicy(Qt.NoFocus)
        self.swatch.clicked.connect(self._pick)
        layout.addWidget(self.swatch)
        self._refresh()

    def _refresh(self):
        self.swatch.setStyleSheet(
            "QPushButton { background: " + self._value + "; border: 1px solid " + M["swatch_border"] + "; }"
            "QPushButton:hover { border-color: " + M["swatch_border_hover"] + "; }"
        )

    def _pick(self):
        chosen = QColorDialog.getColor(QColor(self._value), self, "Choisir une couleur")
        if chosen.isValid():
            self._value = chosen.name()
            self._refresh()
            self.changed.emit(self._value)

    def value(self) -> str:
        return self._value

    def setValue(self, value: str):
        self._value = value
        self._refresh()


class _CheckSquare(QWidget):
    """Petite case carree — purement decorative ici (voir _EdgeCheckItem :
    le clic est capte par la ligne entiere, pas par la case elle-meme)."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(14, 14)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if checked != self._checked:
            self._checked = checked
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        bg = QColor(M["accent"] if self._checked else M["field_bg"])
        bd = QColor(M["accent_border"] if self._checked else M["field_border"])
        p.setPen(bd)
        p.setBrush(bg)
        p.drawRect(0, 0, 13, 13)
        if self._checked:
            p.setPen(QColor(M["bold_mark_fg"]))
            p.setFont(_qfont(9, 700, mono=True))
            p.drawText(0, 0, 13, 13, Qt.AlignCenter, "\u2713")
        p.end()


# ==========================================================================
# Blocs de mise en page (sections / lignes), fideles a la maquette.
# ==========================================================================

def _label_block(text: str, note: str = "") -> QWidget:
    box = QWidget()
    box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 6, 0, 6)
    layout.setSpacing(1)
    name = QLabel(text)
    name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    name.setFont(_qfont(12, 400))
    name.setStyleSheet(f"color: {M['row_label']}; background: transparent;")
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
    """Ligne de reglage : libelle(+note) a gauche, controle a droite. Pas de
    filet de separation entre les lignes d'un groupe (juge parasite a
    l'usage — voir la remarque de l'utilisateur, capture a l'appui)."""

    def __init__(self, label: str, control: QWidget, note: str = "", parent=None):
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


class _Section(QWidget):
    """Section de la page : titre bleu petites capitales + note optionnelle,
    PAS de filet horizontal (la maquette n'en a pas ici, contrairement a
    l'ancien _Group) — juste un espacement genereux (voir SettingsWindow,
    layout.setSpacing(34) entre sections)."""

    def __init__(self, title: str, note: str = "", parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        head = QWidget()
        head_l = QHBoxLayout(head)
        head_l.setContentsMargins(0, 0, 0, 10)
        head_l.setSpacing(12)
        name = QLabel(title.upper())
        name.setFont(_qfont(10, 600, tracking=1.4))
        name.setStyleSheet(f"color: {M['section_title']}; background: transparent;")
        head_l.addWidget(name)
        if note:
            note_label = QLabel(note)
            note_label.setFont(_qfont(10, 400))
            note_label.setStyleSheet(f"color: {M['group_note']}; background: transparent;")
            head_l.addWidget(note_label)
        head_l.addStretch(1)
        self._layout.addWidget(head)

    def add(self, widget: QWidget):
        self._layout.addWidget(widget)


def _table_frame() -> tuple[QWidget, QVBoxLayout]:
    """Cadre exterieur complet (perimetre 1px) d'un tableau — entete et
    lignes empilees a l'interieur, separees seulement par un filet
    horizontal (voir _table_header/_table_row), jamais par des boites
    individuelles : un tableau bien "ferme" (un seul rectangle), pas une
    pile de rectangles accoles (voir la remarque de l'utilisateur, capture
    a l'appui — les tableaux Polices/Geometrie avaient chacun leur propre
    filet gauche/droite/bas, un empilement qui pouvait paraitre "ouvert")."""
    frame = QWidget()
    frame.setObjectName("TableFrame")
    frame.setAttribute(Qt.WA_StyledBackground, True)
    frame.setStyleSheet(f"#TableFrame {{ border: 1px solid {M['panel_border']}; }}")
    layout = QVBoxLayout(frame)
    # Marge de 1px (= l'epaisseur du filet de #TableFrame), PAS 0 : a marge
    # nulle, l'entete/les lignes (chacun avec son propre fond peint via
    # WA_StyledBackground) recouvrent exactement le filet du cadre et le
    # rendent invisible — meme bug, meme correctif que #Panel dans
    # SettingsWindow.__init__ (voir la remarque de l'utilisateur, capture
    # a l'appui : le cadre etait bel et bien absent a l'ecran).
    layout.setContentsMargins(1, 1, 1, 1)
    layout.setSpacing(0)
    return frame, layout


def _table_header(cells: list[tuple[str, int]]) -> QWidget:
    """cells : (libelle, largeur) — largeur 0 => colonne extensible. Filet
    du bas SEULEMENT (separation avec la premiere ligne) : le perimetre du
    tableau est deja fourni par _table_frame, pas par l'entete elle-meme."""
    head = QWidget()
    head.setObjectName("TableHead")
    head.setAttribute(Qt.WA_StyledBackground, True)
    head.setFixedHeight(26)
    head.setStyleSheet(f"#TableHead {{ background: {M['table_head_bg']}; border-bottom: 1px solid {M['panel_border']}; }}")
    layout = QHBoxLayout(head)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    for text, width in cells:
        cell = QLabel(text.upper())
        cell.setFont(_qfont(9, 600))
        cell.setStyleSheet(f"color: {M['table_head_fg']}; background: transparent; padding: 0 10px;")
        if width:
            cell.setFixedWidth(width)
            layout.addWidget(cell, 0)
        else:
            layout.addWidget(cell, 1)
    return head


def _table_row(bg: str, first: bool) -> tuple[QWidget, QHBoxLayout]:
    """`first` : la toute premiere ligne de donnees colle directement sous
    l'entete (qui a deja son propre filet du bas) — seules les lignes
    SUIVANTES ont besoin de leur propre filet du haut ; aucune ligne ne
    dessine plus ses propres cotes gauche/droite (voir _table_frame)."""
    row = QWidget()
    row.setObjectName("TableRow")
    row.setAttribute(Qt.WA_StyledBackground, True)
    row.setMinimumHeight(36)
    border = "" if first else f"border-top: 1px solid {M['panel_border']};"
    row.setStyleSheet(f"#TableRow {{ background: {bg}; {border} }}")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 6, 0, 6)
    layout.setSpacing(0)
    return row, layout


def _table_cell(widget: QWidget, width: int, layout: QHBoxLayout, center: bool = False):
    cell = QWidget()
    cell_l = QHBoxLayout(cell)
    cell_l.setContentsMargins(10, 0, 10, 0)
    if center:
        cell_l.setAlignment(Qt.AlignVCenter)
    cell_l.addWidget(widget)
    if width:
        cell.setFixedWidth(width)
        layout.addWidget(cell, 0)
    else:
        layout.addWidget(cell, 1)


# ==========================================================================
# Section "Polices" — table Role/Police/Apercu (3 colonnes, famille seule).
# Les 4 roles non repris ici (dossiers, boutons, entete de colonnes, info2)
# restent dans le fichier de reglages tels quels (voir DEFAULT_SETTINGS) :
# ils suivent silencieusement "Police principale" si elle est personnalisee
# (voir app_style.role_font), sinon l'auto-detection habituelle — exactement
# leur comportement actuel, juste sans UI pour le changer directement.
# ==========================================================================

_FONT_ROLES = [
    ("font_main", "app", "Police principale", "asset__spaceship_01"),
    ("font_info", "info", "Police informations", "121.7 KB · v004 · 2026-09-03"),
    ("font_titles", "titles", "Police principale titres", "Fichiers pour AIRPLANE"),
    ("font_files", "files", "Police fichiers", "foot.001.OBJ"),
]

def _font_choices() -> list[str]:
    return ["Systeme"] + installed_font_families()


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
        frame, layout = _table_frame()
        layout.addWidget(_table_header([("Role", 196), ("Police", 212), ("Apercu", 0)]))

        self.rows: dict[str, dict[str, Any]] = {}
        for i, (key, style_role, label, sample) in enumerate(_FONT_ROLES):
            conf = settings[key]
            bg = M["table_row_a"] if i % 2 else M["table_row_b"]
            row, row_l = _table_row(bg, first=(i == 0))

            name = QLabel(label)
            name.setFont(_qfont(12, 400))
            name.setStyleSheet(f"color: {M['row_label']}; background: transparent;")
            _table_cell(name, 196, row_l, center=True)

            current_family = conf.get("family") or "Systeme"
            auto_label = auto_family_for_role(style_role)
            font_select = _FontSelectField(_font_choices(), current_family, width=192, auto_label=auto_label)
            _table_cell(font_select, 212, row_l, center=True)

            preview = QLabel(sample)
            preview.setFont(QFont(current_family if current_family != "Systeme" else auto_label, 10))
            preview.setStyleSheet(f"color: {M['value_muted']}; background: transparent;")
            _table_cell(preview, 0, row_l, center=True)

            layout.addWidget(row)
            entry = {"field": font_select, "preview": preview, "auto": auto_label,
                     "custom": bool(conf.get("custom", False))}
            self.rows[key] = entry

            def _on_pick(family: str, e=entry):
                e["custom"] = True
                shown = family if family != "Systeme" else e["auto"]
                e["preview"].setFont(QFont(shown, 10))
                self.changed.emit()

            font_select.changed.connect(_on_pick)

        outer.addWidget(frame)

    def value(self) -> dict[str, dict]:
        out = {}
        for key, entry in self.rows.items():
            family = entry["field"].value()
            out[key] = {
                "family": "" if family == "Systeme" else family,
                "custom": entry["custom"],
            }
        return out


# ==========================================================================
# Section "Couleurs" — grille 2 colonnes, 8 pastilles semantiques (voir
# app_style.SEMANTIC_COLOR_SLOTS). "Selection en cours" et "Bouton" pilotent
# la MEME cle reelle ("accent", voir la remarque dans app_style.py) : les
# deux pastilles restent donc synchronisees, un changement sur l'une se
# repercute immediatement sur l'autre — fidele au reste de l'appli, qui n'a
# qu'une seule couleur d'accent pour les deux roles.
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
        self._fields_by_real_key: dict[str, list[_ColorField]] = {}
        self._hex_labels_by_real_key: dict[str, list[QLabel]] = {}
        for i, (slot, real_key, label) in enumerate(SEMANTIC_COLOR_SLOTS):
            cell = QWidget()
            cell.setStyleSheet(f"background: {M['table_row_b']};")
            cell_l = QHBoxLayout(cell)
            cell_l.setContentsMargins(10, 7, 10, 7)
            cell_l.setSpacing(10)
            field = _ColorField(colors.get(real_key, "#000000"), swatch_size=24)
            cell_l.addWidget(field)
            name = QLabel(label)
            name.setFont(_qfont(11, 400))
            name.setStyleSheet(f"color: {M['row_label']}; background: transparent;")
            name.setWordWrap(False)
            cell_l.addWidget(name, 1)
            hex_label = QLabel(colors.get(real_key, ""))
            hex_label.setFont(_qfont(10, 400, mono=True))
            hex_label.setStyleSheet(f"color: {M['table_head_fg']}; background: transparent;")
            cell_l.addWidget(hex_label)
            self._fields_by_real_key.setdefault(real_key, []).append(field)
            self._hex_labels_by_real_key.setdefault(real_key, []).append(hex_label)
            field.changed.connect(lambda v, rk=real_key: self._sync_key(rk, v))
            row, col = divmod(i, 2)
            grid.addWidget(cell, row, col)
        outer.addWidget(wrap)

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


# ==========================================================================
# Section "Entetes" — hauteur / couleur (choisie parmi les 8 pastilles
# semantiques) / rayon des angles / cadre par cote.
# ==========================================================================

_SLOT_LABELS = {slot: label for slot, _real, label in SEMANTIC_COLOR_SLOTS}
_SLOT_REAL = {slot: real for slot, real, _label in SEMANTIC_COLOR_SLOTS}


class _HeaderColorField(QWidget):
    """Ligne cliquable (pastille + libelle + chevron) ouvrant un QMenu sur
    les 8 pastilles semantiques, plus une boite hex a droite en lecture
    seule — la couleur elle-meme se change page Couleurs, ici on choisit
    juste QUELLE pastille alimente le fond de l'entete."""

    changed = Signal(str)

    def __init__(self, colors: dict, current_slot: str, parent=None):
        super().__init__(parent)
        self._colors = colors
        self._slot = current_slot if current_slot in _SLOT_LABELS else "skinN1"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.btn = QPushButton()
        self.btn.setFlat(True)
        self.btn.setCursor(Qt.ArrowCursor)
        self.btn.setFocusPolicy(Qt.NoFocus)
        self.btn.setFixedHeight(25)
        # Largeur fixe (280, meme calcul que les sliders de cette meme
        # section — voir _section_headers) : sans elle, ce bouton ne se
        # dimensionne que sur son propre texte et le controle entier ne
        # s'aligne pas avec les autres lignes du tableau Entetes.
        self.btn.setFixedWidth(280)
        self.btn.setStyleSheet(
            f"QPushButton {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"text-align: left; padding: 0 8px; }}"
            f"QPushButton:hover {{ border-color: {M['field_border_hover']}; }}"
        )
        self.btn.clicked.connect(self._open_menu)
        layout.addWidget(self.btn, 1)

        hex_box = QWidget()
        hex_box.setObjectName("HeaderHexBox")
        hex_box.setAttribute(Qt.WA_StyledBackground, True)
        hex_box.setFixedSize(68, 25)
        hex_box.setStyleSheet(f"#HeaderHexBox {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; }}")
        hex_l = QHBoxLayout(hex_box)
        hex_l.setContentsMargins(7, 0, 7, 0)
        self.hex_label = QLabel()
        self.hex_label.setFont(_qfont(11, 400, mono=True))
        self.hex_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.hex_label.setStyleSheet(f"color: {M['value_muted']}; background: transparent;")
        hex_l.addWidget(self.hex_label)
        layout.addWidget(hex_box)
        self._refresh()

    def _current_hex(self) -> str:
        return self._colors.get(_SLOT_REAL.get(self._slot, "chrome"), "#000000")

    def _refresh(self):
        swatch = f"background: {self._current_hex()}; border: 1px solid {M['swatch_border']};"
        self.btn.setIcon(_solid_icon(self._current_hex()))
        self.btn.setIconSize(self.btn.iconSize())
        self.btn.setText("  " + _SLOT_LABELS.get(self._slot, self._slot) + "  ▾")
        self.hex_label.setText(self._current_hex())

    def _open_menu(self):
        menu = QMenu(self)
        menu.setFont(_qfont(11, 400))
        menu.setStyleSheet(
            f"QMenu {{ background: {M['toolbar_bg']}; border: 1px solid {M['field_border']}; padding: 4px 0; }}"
            f"QMenu::item {{ padding: 5px 16px; color: {M['value_fg']}; }}"
            f"QMenu::item:selected {{ background: {M['accent']}; color: {M['accent_fg']}; }}"
        )
        for slot, _real, label in SEMANTIC_COLOR_SLOTS:
            action = menu.addAction(_solid_icon(self._colors.get(_SLOT_REAL[slot], "#000")), label)
            action.triggered.connect(lambda _c=False, s=slot: self._select(s))
        menu.exec(self.btn.mapToGlobal(QPoint(0, self.btn.height())))

    def _select(self, slot: str):
        if slot != self._slot:
            self._slot = slot
            self._refresh()
            self.changed.emit(slot)

    def value(self) -> str:
        return self._slot

    def refresh_colors(self, colors: dict):
        """A appeler quand la page Couleurs a change une valeur — la
        pastille choisie ici doit suivre (voir SettingsWindow._on_colors_changed)."""
        self._colors = colors
        self._refresh()

    def setValue(self, slot: str, colors: dict):
        """Reapplique a la fois le slot choisi ET la palette source —
        utilise par Valeurs par defaut / chargement d'un preset (voir
        SettingsWindow._apply_values_to_controls), qui doivent pouvoir
        changer les deux d'un coup sans emettre `changed` a chaque etape
        intermediaire."""
        self._slot = slot if slot in _SLOT_LABELS else "skinN1"
        self._colors = colors
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
        self.setStyleSheet(f"background: {M['field_bg']}; border: 1px dashed {M['panel_border']};")
        label = QLabel("entete", self)
        label.setFont(_qfont(9, 400, mono=True))
        label.setStyleSheet(f"color: {M['edge_hint']}; background: transparent;")
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

    def _toggle(self, name: str):
        bar = self.bars[name]
        bar.setOn(not bar._on)
        self.changed.emit(name)

    def value(self) -> dict[str, bool]:
        return {name: bar._on for name, bar in self.bars.items()}

    def setValue(self, edges: dict):
        for name, bar in self.bars.items():
            bar.setOn(bool(edges.get(name, False)))


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


# ==========================================================================
# Section "Geometrie" — table Element/Cadre/Coins arrondis, 3 lignes :
# Fenetres (rayon seul, pas de cadre reglable — le filet du panneau
# principal est structurel, voir #CentralFrame dans pipeline_browser.py),
# Zones de saisie et Boutons (cadre actif/sans + rayon).
# ==========================================================================

class _GeoTable(QWidget):
    changed = Signal()

    def __init__(self, window_radius: int, input_frame: bool, input_radius: int,
                 button_frame: bool, button_radius: int, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame_wrap, layout = _table_frame()
        layout.addWidget(_table_header([("Element", 0), ("Cadre", 150), ("Coins arrondis", 246)]))

        self.window_radius_field = _SliderField(0, 24, window_radius, slider_width=140, box_width=58)
        self.input_frame_toggle = _Toggle(input_frame)
        self.input_radius_field = _SliderField(0, 16, input_radius, slider_width=140, box_width=58)
        self.button_frame_toggle = _Toggle(button_frame)
        self.button_radius_field = _SliderField(0, 16, button_radius, slider_width=140, box_width=58)

        rows = [
            ("Fenetres", None, self.window_radius_field),
            ("Zones de saisie", self.input_frame_toggle, self.input_radius_field),
            ("Boutons", self.button_frame_toggle, self.button_radius_field),
        ]
        for i, (label, frame_toggle, radius_field) in enumerate(rows):
            bg = M["table_row_a"] if i % 2 else M["table_row_b"]
            row, row_l = _table_row(bg, first=(i == 0))
            name = QLabel(label)
            name.setFont(_qfont(12, 400))
            name.setStyleSheet(f"color: {M['row_label']}; background: transparent;")
            _table_cell(name, 0, row_l, center=True)
            if frame_toggle is not None:
                _table_cell(frame_toggle, 150, row_l, center=True)
                frame_toggle.toggled.connect(lambda _c: self.changed.emit())
            else:
                dash = QLabel("—")
                dash.setFont(_qfont(10, 400, mono=True))
                dash.setStyleSheet(f"color: {M['dash']}; background: transparent;")
                _table_cell(dash, 150, row_l, center=True)
            _table_cell(radius_field, 246, row_l, center=True)
            radius_field.valueChanged.connect(lambda _v: self.changed.emit())
            layout.addWidget(row)

        outer.addWidget(frame_wrap)

    def value(self) -> dict[str, Any]:
        return {
            "window_radius": self.window_radius_field.value(),
            "input_frame": self.input_frame_toggle.isChecked(),
            "input_radius": self.input_radius_field.value(),
            "button_frame": self.button_frame_toggle.isChecked(),
            "button_radius": self.button_radius_field.value(),
        }


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
        label.setFont(_qfont(11, 400))
        label.setStyleSheet(f"color: {M['value_fg']}; background: transparent;")
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


# ==========================================================================
# Fenetre principale (frameless, chrome propre a cette fenetre).
# ==========================================================================

class _SettingsTitleBar(QWidget):
    closeClicked = Signal()

    def __init__(self, dialog: QDialog, parent=None):
        super().__init__(parent)
        self._dialog = dialog
        self.setFixedHeight(28)
        self.setObjectName("SettingsTitleBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#SettingsTitleBar {{ background: {M['titlebar_bg']}; border-bottom: 1px solid {M['panel_border']}; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(9)
        dot = QLabel()
        dot.setFixedSize(9, 9)
        dot.setStyleSheet(f"border: 1px solid {M['dot_border']}; background: transparent;")
        layout.addWidget(dot)
        title = QLabel("Parametres generaux")
        title.setFont(_qfont(11, 400))
        title.setStyleSheet(f"color: {M['title_fg']}; background: transparent;")
        layout.addWidget(title)
        layout.addStretch(1)
        self.dirty_label = QLabel("")
        self.dirty_label.setFont(_qfont(10, 400, mono=True))
        layout.addWidget(self.dirty_label)
        self.close_btn = QPushButton("×")
        self.close_btn.setFixedSize(26, 20)
        self.close_btn.setCursor(Qt.ArrowCursor)
        self.close_btn.setFocusPolicy(Qt.NoFocus)
        self.close_btn.setFlat(True)
        self.close_btn.setFont(_qfont(11, 400, mono=True))
        self.close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 0; color: " + M["close_fg"] + "; }"
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
            start_native_move(self._dialog)
            event.accept()
        else:
            super().mousePressEvent(event)


class SettingsWindow(QDialog):
    """Fenetre de parametres, reproduction fidele de la maquette html
    "Parametres generaux". Chaque changement se previsualise en direct sur
    la fenetre principale (settingsChanged), sans toucher au disque ;
    Enregistrer persiste (settingsSaved)."""

    settingsChanged = Signal(dict)
    settingsSaved = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # 1020 (largeur maquette) - 284 (panneau "Apercu en direct", supprime
        # a la demande de l'utilisateur) : la page de gauche n'a plus besoin
        # de toute cette largeur.
        self.resize(760, 820)
        # Redimensionnable par l'utilisateur (voir nativeEvent ci-dessous,
        # meme mecanisme que PipelineBrowser) : largeur/hauteur minimales
        # sous lesquelles les lignes de reglage (slider+boite fixe a
        # droite) commenceraient a se chevaucher avec leur libelle.
        self.setMinimumSize(640, 480)

        self.settings = load_settings()
        self._original_settings = json.loads(json.dumps(self.settings))
        self._saved = False
        self._dirty = False
        self._current_preset = "Personnalise"

        # Voir la meme remarque dans l'ancienne fenetre : le rafraichissement
        # (previsualisation complete sur la fenetre principale) est lourd,
        # on le differe donc toujours de 30ms au fil d'un glisser de slider.
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
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        self.titlebar = _SettingsTitleBar(self)
        self.titlebar.closeClicked.connect(self.reject)
        root.addWidget(self.titlebar)

        root.addWidget(self._build_toolbar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_content(), 1)
        root.addLayout(body, 1)

        root.addWidget(self._build_bottom_bar())

        self._connect_live_updates()
        self._preview_now()

    # -- barre d'outils (preset) --

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(40)
        bar.setStyleSheet(f"background: {M['toolbar_bg']};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(8)

        tag = QLabel("Preset")
        tag.setFont(_qfont(9, 600, tracking=0.7))
        tag.setStyleSheet(f"color: {M['label_dim']}; background: transparent;")
        layout.addWidget(tag)

        # Double-clic pour renommer (en plus du bouton "Renommer" ci-dessous
        # — voir la remarque de l'utilisateur, capture a l'appui).
        self.preset_box = _DoubleClickBox()
        self.preset_box.setObjectName("PresetBox")
        self.preset_box.setAttribute(Qt.WA_StyledBackground, True)
        self.preset_box.setFixedSize(260, 26)
        self.preset_box.doubleClicked.connect(self._rename_preset)
        preset_l = QHBoxLayout(self.preset_box)
        preset_l.setContentsMargins(9, 0, 9, 0)
        preset_l.setSpacing(8)
        self.preset_name_label = QLabel()
        self.preset_name_label.setFont(_qfont(12, 400))
        preset_l.addWidget(self.preset_name_label, 1)
        self.preset_dot = QLabel()
        self.preset_dot.setFixedSize(6, 6)
        preset_l.addWidget(self.preset_dot)
        layout.addWidget(self.preset_box)

        # "Enregistrer" remplace l'ancien bouton "Renommer" — le double-clic
        # sur la boite de preset couvre deja le renommage (voir plus haut) ;
        # ce bouton sauvegarde directement les valeurs courantes dans le
        # preset actif (ou ouvre "Nouveau preset..." s'il n'y en a pas
        # encore un de charge) — voir la remarque de l'utilisateur, capture
        # a l'appui.
        save_btn = _Btn("Enregistrer", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=26)
        save_btn.clicked.connect(self._save_current_preset)
        layout.addWidget(save_btn)

        divider = QFrame()
        divider.setFixedSize(1, 16)
        divider.setStyleSheet(f"background: {M['panel_border']};")
        layout.addWidget(divider)

        # Un seul bouton icone remplace "Enregistrer sous…"/"Ouvrir un
        # preset…" (voir la remarque de l'utilisateur, capture a l'appui) :
        # ouvre une liste (voir _open_preset_popup) qui permet a la fois de
        # charger un preset existant, d'en supprimer un (croix), et d'en
        # enregistrer un nouveau ("+ Nouveau preset…", en tete de liste).
        self._preset_menu_btn = _HamburgerButton("")
        self._preset_menu_btn.setFixedSize(26, 26)
        self._preset_menu_btn.setCursor(Qt.ArrowCursor)
        self._preset_menu_btn.setFocusPolicy(Qt.NoFocus)
        self._preset_menu_btn.setStyleSheet(
            f"QPushButton {{ background: {M['btn_bg']}; border: 1px solid {M['btn_border']}; color: {M['btn_fg']}; }}"
            f"QPushButton:hover {{ background: {M['btn_hover']}; }}"
        )
        self._preset_menu_btn.clicked.connect(self._open_preset_popup)
        layout.addWidget(self._preset_menu_btn)

        layout.addStretch(1)

        path_label = QLabel(f"{_PRESETS_PATH.name} · {_PRESETS_PATH.parent}")
        path_label.setFont(_qfont(10, 400, mono=True))
        path_label.setStyleSheet(f"color: {M['group_note']}; background: transparent;")
        layout.addWidget(path_label)

        self._sync_preset_box()
        return bar

    def _sync_preset_box(self):
        border = M["dirty_border"] if self._dirty else M["field_border"]
        self.preset_box.setStyleSheet(
            f"#PresetBox {{ background: {M['field_bg']}; border: 1px solid {border}; }}"
        )
        self.preset_name_label.setText(self._current_preset + (" *" if self._dirty else ""))
        self.preset_name_label.setStyleSheet(f"color: {M['value_fg']}; background: transparent;")
        dot_color = M["dirty_dot"] if self._dirty else M["clean_dot"]
        self.preset_dot.setStyleSheet(f"background: {dot_color};")

    def _open_preset_popup(self):
        """Liste des presets (voir _PresetListRow) : "+ Nouveau preset…" en
        tete (enregistre les valeurs courantes sous un nouveau nom), puis
        chaque preset existant — clic sur le nom pour le charger, sur la
        croix pour le supprimer. Remplace les 2 anciens boutons "Enregistrer
        sous…"/"Ouvrir un preset…" (voir la remarque de l'utilisateur,
        capture a l'appui)."""
        popup = QWidget(self, Qt.Popup)
        popup.setObjectName("PresetPopup")
        popup.setAttribute(Qt.WA_StyledBackground, True)
        popup.setStyleSheet(f"#PresetPopup {{ background: {M['toolbar_bg']}; border: 1px solid {M['field_border']}; }}")
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        new_btn = _Btn("+  Nouveau preset…", "transparent", "", M["value_fg"], M["btn_hover"],
                       height=30, weight=500, padding="0 12px")
        new_btn.setStyleSheet(new_btn.styleSheet() + "QPushButton { text-align: left; }")
        new_btn.clicked.connect(lambda: (popup.close(), self._save_preset_as()))
        layout.addWidget(new_btn)

        presets = _load_presets()
        if presets:
            divider = QFrame()
            divider.setFixedHeight(1)
            divider.setStyleSheet(f"background: {M['field_border']};")
            layout.addWidget(divider)
            for name in presets:
                row = _PresetListRow(name)
                row.clicked.connect(lambda n=name: (popup.close(), self._load_preset(n, _load_presets())))
                row.deleteClicked.connect(lambda n=name: self._delete_preset(n, popup))
                layout.addWidget(row)
        else:
            empty = QLabel("(aucun preset enregistre)")
            empty.setFont(_qfont(11, 400))
            empty.setStyleSheet(f"color: {M['group_note']}; background: transparent; padding: 6px 12px;")
            layout.addWidget(empty)

        popup.setFixedWidth(max(self._preset_menu_btn.width(), 220))
        popup.adjustSize()
        popup.move(self._preset_menu_btn.mapToGlobal(QPoint(0, self._preset_menu_btn.height())))
        popup.show()

    def _delete_preset(self, name: str, popup: QWidget):
        presets = _load_presets()
        presets.pop(name, None)
        _save_presets(presets)
        if self._current_preset == name:
            self._current_preset = "Personnalise"
            self._sync_preset_box()
        popup.close()
        # Rouvre aussitot la liste a jour (sans le preset supprime) : plus
        # pratique que refermer purement et simplement si l'utilisateur
        # veut enchainer plusieurs suppressions.
        self._open_preset_popup()

    def _load_preset(self, name: str, presets: dict):
        data = presets.get(name)
        if not data:
            return
        # _apply_values_to_controls fusionne deja data par-dessus
        # DEFAULT_SETTINGS (voir sa docstring) : pas besoin de le refaire ici.
        self._apply_values_to_controls(data)
        self._current_preset = name
        self._dirty = False
        self.titlebar.set_dirty(False)
        self._sync_preset_box()
        self._preview_now()

    def _save_preset_as(self):
        name, ok = QInputDialog.getText(self, "Enregistrer sous", "Nom du preset :")
        if not ok or not name.strip():
            return
        presets = _load_presets()
        presets[name.strip()] = self._current_values()
        _save_presets(presets)
        self._current_preset = name.strip()
        self._dirty = False
        self.titlebar.set_dirty(False)
        self._sync_preset_box()

    def _save_current_preset(self):
        """Bouton "Enregistrer" de la barre a outils : sauvegarde les
        valeurs courantes dans le preset actif ; si aucun preset n'est
        charge (etat "Personnalise"), se rabat sur "Nouveau preset..."."""
        if not self._current_preset or self._current_preset == "Personnalise":
            self._save_preset_as()
            return
        presets = _load_presets()
        presets[self._current_preset] = self._current_values()
        _save_presets(presets)
        self._dirty = False
        self.titlebar.set_dirty(False)
        self._sync_preset_box()

    def _rename_preset(self):
        new_name, ok = QInputDialog.getText(self, "Renommer", "Nouveau nom :", text=self._current_preset)
        new_name = new_name.strip()
        if not ok or not new_name or new_name == self._current_preset:
            return
        presets = _load_presets()
        if self._current_preset in presets:
            presets[new_name] = presets.pop(self._current_preset)
            _save_presets(presets)
        self._current_preset = new_name
        self._sync_preset_box()

    def _apply_values_to_controls(self, data: dict):
        """Reapplique un dict complet de reglages sur TOUS les controles —
        utilise par Valeurs par defaut et le chargement d'un preset.

        Remplace D'ABORD self.settings par (une copie de) `data` en entier,
        AVANT de synchroniser les widgets : _current_values() fusionne les
        valeurs des widgets par-dessus self.settings pour les cles sans UI
        (couleurs non exposees, detail des polices figees..., voir la
        remarque de tete de fichier) — sans ce remplacement prealable,
        self.settings serait reste bloque sur son contenu de CONSTRUCTION
        (le fichier charge au demarrage), et "Valeurs par defaut"/le
        chargement d'un preset auraient eu l'air de fonctionner (les
        widgets suivent bien) sans jamais reellement s'appliquer aux cles
        gelees — bug reel confirme en repassant un preset "as-is" par ce
        chemin (voir git diff sur pipeline_settings.presets.json)."""
        self.settings = json.loads(json.dumps(DEFAULT_SETTINGS))
        self.settings.update(json.loads(json.dumps(data)))

        self.root_field.setText(self.settings.get("root_path", DEFAULT_SETTINGS["root_path"]))
        self.scale_field.setValue(int(self.settings.get("ui_scale", 100)))
        for key, entry in self.font_table.rows.items():
            conf = self.settings.get(key) or {}
            family = conf.get("family") or "Systeme"
            entry["field"].setValue(family)
            shown = family if family != "Systeme" else entry["auto"]
            entry["preview"].setFont(QFont(shown, 10))
            entry["custom"] = bool(conf.get("custom", False))
        for real_key, hexval in (self.settings.get("colors") or {}).items():
            if real_key in self.color_grid._fields_by_real_key:
                self.color_grid._sync_key(real_key, hexval)
        self.header_height_field.setValue(int(self.settings.get("header_height", 26)))
        self.header_padding_field.setValue(int(self.settings.get("header_padding", 0)))
        self.header_color_field.setValue(self.settings.get("header_color", "skinN1"), self.settings["colors"])
        self.header_radius_field.setValue(int(self.settings.get("header_radius", 0)))
        self.header_edges_field.setValue(self.settings.get("header_edges") or {})
        self.geo_table.window_radius_field.setValue(int(self.settings.get("window_radius", 0)))
        self.geo_table.input_frame_toggle.setChecked(bool(self.settings.get("input_frame", True)))
        self.geo_table.input_radius_field.setValue(int(self.settings.get("input_radius", 0)))
        self.geo_table.button_frame_toggle.setChecked(bool(self.settings.get("button_frame", True)))
        self.geo_table.button_radius_field.setValue(int(self.settings.get("button_radius", 0)))

    # -- contenu (sections) --

    def _build_content(self) -> QWidget:
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.NoFrame)
        scroller.setStyleSheet(f"background: {M['panel_bg']};")
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 18, 18, 26)
        layout.setSpacing(34)
        layout.addWidget(self._section_application())
        layout.addWidget(self._section_fonts())
        layout.addWidget(self._section_colors())
        layout.addWidget(self._section_headers())
        layout.addWidget(self._section_geometry())
        layout.addStretch(1)
        scroller.setWidget(inner)
        return scroller

    def _section_application(self) -> QWidget:
        section = _Section("Application")

        self.root_field = QLineEdit(self.settings["root_path"])
        self.root_field.setFont(_qfont(12, 400, mono=True))
        self.root_field.setFixedSize(268, 25)
        self.root_field.setStyleSheet(
            f"background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"color: {M['value_muted']}; padding: 0 8px;"
        )
        browse_btn = _Btn("Parcourir", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25)
        browse_btn.clicked.connect(self._browse_root)
        # Largeur FIXE (pas le sizeHint naturel du bouton) : le bloc de
        # controle de cette ligne (champ+bouton = 268+6+84 = 358) doit faire
        # exactement la meme largeur totale que celui de "Scale interface"
        # juste en dessous (slider 280 + espacement 10 + boite 68 = 358),
        # sans quoi les deux lignes ne s'alignent ni a gauche ni a droite
        # (voir la remarque de l'utilisateur, capture a l'appui).
        browse_btn.setFixedWidth(84)
        root_row = QWidget()
        root_row_l = QHBoxLayout(root_row)
        root_row_l.setContentsMargins(0, 0, 0, 0)
        root_row_l.setSpacing(6)
        root_row_l.addWidget(self.root_field)
        root_row_l.addWidget(browse_btn)
        section.add(_Row("Racine par defaut", root_row))

        self.scale_field = _SliderField(50, 200, int(self.settings["ui_scale"]), "%", slider_width=280, box_width=68)
        section.add(_Row("Scale interface", self.scale_field))
        return section

    def _section_fonts(self) -> QWidget:
        self.font_table = _SimpleFontTable(self.settings)
        return self.font_table

    def _section_colors(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        section = _Section("Couleurs")
        self.color_grid = _ColorGrid(self.settings["colors"])
        section.add(self.color_grid)
        layout.addWidget(section)
        return wrap

    def _section_headers(self) -> QWidget:
        wrap = QWidget()
        outer_layout = QVBoxLayout(wrap)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        section = _Section("Entetes")

        self.header_height_field = _SliderField(16, 56, int(self.settings["header_height"]), slider_width=280, box_width=68)
        self.header_padding_field = _SliderField(0, 32, int(self.settings.get("header_padding", 0)), slider_width=280, box_width=68)
        self.header_color_field = _HeaderColorField(self.settings["colors"], self.settings.get("header_color", "skinN1"))
        self.header_radius_field = _SliderField(0, 16, int(self.settings.get("header_radius", 0)), slider_width=280, box_width=68)
        self.header_edges_field = _HeaderEdgesField(self.settings.get("header_edges") or {})

        # Tableau ferme (voir _table_frame — meme technique que Polices/
        # Geometrie, voir la remarque de l'utilisateur, capture a l'appui) :
        # une ligne "libelle(+note) / controle" par reglage, pas de colonnes
        # multiples (une seule "valeur" par ligne, de nature differente
        # d'une ligne a l'autre) donc pas d'entete de colonnes ici.
        rows = [
            ("Hauteur des entetes", self.header_height_field, ""),
            ("Padding des entetes", self.header_padding_field, ""),
            ("Couleur des entetes", self.header_color_field, ""),
            ("Arrondi des angles", self.header_radius_field, ""),
            ("Cadre des entetes", self.header_edges_field, ""),
        ]
        frame, table_layout = _table_frame()
        for i, (label, control, note) in enumerate(rows):
            bg = M["table_row_a"] if i % 2 else M["table_row_b"]
            row, row_l = _table_row(bg, first=(i == 0))
            row_l.setContentsMargins(14, 8, 14, 8)
            row_l.setSpacing(14)
            row_l.addWidget(_label_block(label, note), 1)
            row_l.addWidget(control, 0, Qt.AlignVCenter)
            table_layout.addWidget(row)
        section.add(frame)
        outer_layout.addWidget(section)
        return wrap

    def _section_geometry(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        section = _Section("Geometrie")
        self.geo_table = _GeoTable(
            int(self.settings.get("window_radius", 0)),
            bool(self.settings.get("input_frame", True)),
            int(self.settings.get("input_radius", 0)),
            bool(self.settings.get("button_frame", True)),
            int(self.settings.get("button_radius", 0)),
        )
        section.add(self.geo_table)
        layout.addWidget(section)
        return wrap

    # -- barre du bas --

    def _build_bottom_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(46)
        bar.setStyleSheet(f"background: {M['toolbar_bg']}; border-top: 1px solid {M['panel_border']};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(8)

        reset_btn = _Btn("Valeurs par defaut", "transparent", M["btn_border"], M["reset_fg"], M["btn_bg"], height=27, padding="0 12px")
        reset_btn.clicked.connect(self._reset_defaults)
        layout.addWidget(reset_btn)
        layout.addStretch(1)

        apply_btn = _Btn("Appliquer", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=27, padding="0 13px")
        apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(apply_btn)

        cancel_btn = _Btn("Annuler", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=27, padding="0 13px")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        save_btn = _Btn("Enregistrer", M["accent"], M["accent_border"], M["accent_fg"], M["accent_hover"],
                        height=27, weight=600, padding="0 17px")
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn)
        return bar

    def _reset_defaults(self):
        defaults = json.loads(json.dumps(DEFAULT_SETTINGS))
        defaults["root_path"] = self.settings.get("root_path", DEFAULT_SETTINGS["root_path"])
        self._apply_values_to_controls(defaults)
        self._mark_dirty()
        self._preview_now()

    # -- actions --

    def _browse_root(self):
        chosen = QFileDialog.getExistingDirectory(self, "Racine par defaut", self.root_field.text())
        if chosen:
            self.root_field.setText(chosen)

    def _apply_panel_radius(self, radius: int):
        self.panel.setStyleSheet(
            f"#Panel {{ background: {M['panel_bg']}; border: 1px solid {M['panel_border']}; "
            f"border-radius: {radius}px; }}"
        )
        # resizable=True (voir PipelineBrowser._apply_native_frame, meme
        # appel) : pose WS_THICKFRAME cote Windows, sans quoi nativeEvent
        # ci-dessous n'aurait aucun bord natif a agrandir/retrecir.
        apply_dwm_frame(self, radius, M["panel_border"], resizable=True)

    _RESIZE_BORDER = 6

    def nativeEvent(self, eventType, message):
        """Redimensionnement par les bords de cette fenetre sans decoration
        systeme — voir app_style.resize_hit_test (partage avec
        PipelineBrowser.nativeEvent, meme mecanisme)."""
        if eventType == b"windows_generic_MSG":
            result = resize_hit_test(self, message, self._RESIZE_BORDER)
            if result is not None:
                return result
        return super().nativeEvent(eventType, message)

    def _connect_live_updates(self):
        self.scale_field.valueChanged.connect(self._mark_dirty)
        self.font_table.changed.connect(self._mark_dirty)
        self.color_grid.changed.connect(self._on_colors_changed)
        self.header_height_field.valueChanged.connect(self._mark_dirty)
        self.header_padding_field.valueChanged.connect(self._mark_dirty)
        self.header_color_field.changed.connect(self._mark_dirty)
        self.header_radius_field.valueChanged.connect(self._mark_dirty)
        self.header_edges_field.changed.connect(self._mark_dirty)
        self.geo_table.changed.connect(self._on_window_radius_changed)

    def _on_colors_changed(self):
        merged_colors = dict(self.settings["colors"])
        merged_colors.update(self.color_grid.value())
        self.header_color_field.refresh_colors(merged_colors)
        self._mark_dirty()

    def _on_window_radius_changed(self):
        self._apply_panel_radius(self.geo_table.window_radius_field.value())
        self._mark_dirty()

    def _current_values(self) -> dict:
        colors = dict(self.settings["colors"])
        colors.update(self.color_grid.value())
        geo = self.geo_table.value()
        out = dict(self.settings)
        out.update({
            "root_path": self.root_field.text().strip() or DEFAULT_SETTINGS["root_path"],
            "ui_scale": self.scale_field.value(),
            "colors": colors,
            "header_height": self.header_height_field.value(),
            "header_padding": self.header_padding_field.value(),
            "header_color": self.header_color_field.value(),
            "header_radius": self.header_radius_field.value(),
            "header_edges": self.header_edges_field.value(),
            **geo,
        })
        for key, conf in self.font_table.value().items():
            merged = dict(self.settings[key])
            merged.update(conf)
            out[key] = merged
        return out

    def _mark_dirty(self, *_args):
        self._dirty = True
        self.titlebar.set_dirty(True)
        self._sync_preset_box()
        self._live_pending = True
        if not self._live_timer.isActive():
            self._live_timer.start()

    def _flush_live_apply(self):
        if not self._live_pending:
            return
        self._live_pending = False
        self._preview_now()

    def _preview_now(self):
        self.settingsChanged.emit(self._current_values())

    def _on_apply(self):
        """Commit les valeurs courantes (y compris la racine, qui n'est PAS
        previsualisee en direct sur chaque frappe — voir la remarque de tete
        de fichier sur les 3 boutons) sans toucher au disque."""
        self._preview_now()

    def _on_save(self):
        self.settings = self._current_values()
        save_settings(self.settings)
        self._saved = True
        self._dirty = False
        self.titlebar.set_dirty(False)
        self._sync_preset_box()
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
