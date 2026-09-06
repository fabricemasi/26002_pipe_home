#!/usr/bin/env python3
"""
Fenetre de parametres de Pipeline Browser.

Regroupe les reglages ajustables par l'utilisateur (racine par defaut,
tailles de vignettes/icones, dimensions des colonnes, confirmations...),
persistes dans un petit fichier JSON a cote du script. Reprend le meme
habillage visuel que le reste des applications du pipeline (voir
app_style.py : memes tokens de couleur, memes polices).

    python settings_window.py   (pour previsualiser la fenetre seule)
"""

import json
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app_style import C, SMOOTHING_CHOICES, SMOOTHING_LABELS, apply_style, font, role_font, set_role_font

# ==========================================================================
# Persistance (fichier JSON a cote du script)
# ==========================================================================

SETTINGS_PATH = Path(__file__).resolve().parent / "pipeline_settings.json"

# Police vide ("family": "") = automatique (laisse l'appli choisir/replier
# comme si aucune surcharge n'existait pour ce role). Voir app_style.role_font.
# "smoothing" : "current" (lissage actuel), "previous" (lissage precedent),
# "none" (pas de lissage). "color" vide = couleur par defaut du role.
_DEFAULT_FONT = {"family": "", "size": 12, "bold": False, "smoothing": "current", "color": ""}

DEFAULT_SETTINGS: dict[str, Any] = {
    "root_path": r"F:\PIPELINE",
    "remember_last_root": False,
    "column_width": 220,
    "project_row_height": 64,
    "row_spacing": 1,
    "thumbnail_max_dim": 1024,
    "software_icon_max_dim": 128,
    "show_file_image_previews": True,
    "file_preview_size": 64,
    "confirm_before_move": True,
    "font_files": dict(_DEFAULT_FONT),
    "font_folders": dict(_DEFAULT_FONT),
    "font_info": dict(_DEFAULT_FONT),
    "font_buttons": dict(_DEFAULT_FONT),
    "font_app": dict(_DEFAULT_FONT),
}


def load_settings() -> dict[str, Any]:
    """Charge les parametres depuis le disque, en completant les cles
    manquantes avec les valeurs par defaut (fichier absent, corrompu, ou
    version anterieure de l'appli avec moins de reglages). Les reglages de
    police sont des dict imbriques : on les complete cle par cle plutot que
    de remplacer tout le sous-dict, pour rester compatible si de nouvelles
    sous-cles (italique...) sont ajoutees plus tard."""
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))  # copie profonde
    try:
        if SETTINGS_PATH.is_file():
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key, value in data.items():
                    if key not in DEFAULT_SETTINGS:
                        continue
                    if isinstance(value, dict) and isinstance(settings.get(key), dict):
                        settings[key].update(value)
                    else:
                        settings[key] = value
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    try:
        SETTINGS_PATH.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


# ==========================================================================
# UI
# ==========================================================================

class _Section(QWidget):
    """Bloc de reglages avec titre de section, meme style que les en-tetes
    de colonne du navigateur (police majuscule espacee, couleur 'header')."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        heading = QLabel(title)
        heading.setFont(role_font("app", 10, 600, tracking=0.9, caps=True))
        heading.setStyleSheet(f"color: {C['header']}; background: transparent;")
        layout.addWidget(heading)

        self.form = QFormLayout()
        self.form.setSpacing(10)
        self.form.setLabelAlignment(Qt.AlignLeft)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(self.form)

    def add_row(self, label_text: str, widget: QWidget):
        label = QLabel(label_text)
        label.setFont(role_font("app", 11, 400))
        label.setStyleSheet(f"color: {C['text']}; background: transparent;")
        self.form.addRow(label, widget)


class _FontRow(QWidget):
    """Ligne de reglage typographique (police + taille + gras + lissage +
    couleur) pour un role donne (fichiers, dossiers, informations, boutons,
    ensemble de l'appli). « Automatique » = pas de surcharge de police,
    l'appli garde son choix habituel ; le lissage et la couleur s'appliquent
    independamment de ce choix."""

    AUTO_LABEL = "Automatique"
    AUTO_COLOR_LABEL = "Automatique"
    changed = Signal()

    def __init__(self, value: dict, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # -- ligne 1 : police / taille / gras --
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(8)

        self.family_combo = QFontComboBox()
        self.family_combo.setFont(font(11, 400))
        self.family_combo.setFixedHeight(24)
        self.family_combo.setCursor(Qt.ArrowCursor)
        self.family_combo.setStyleSheet(
            f"QFontComboBox {{ background: {C['well']}; border: 1px solid {C['border_soft']}; "
            f"color: {C['text_mono']}; padding: 0 6px; }}"
        )
        self.family_combo.insertItem(0, self.AUTO_LABEL)
        family = (value.get("family") or "").strip()
        if family:
            idx = self.family_combo.findText(family)
            self.family_combo.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            self.family_combo.setCurrentIndex(0)

        self.size_spin = QSpinBox()
        self.size_spin.setRange(6, 48)
        self.size_spin.setValue(int(value.get("size", 12)))
        self.size_spin.setSuffix(" px")
        self.size_spin.setFont(font(11, 400, mono=True))
        self.size_spin.setFixedHeight(24)
        self.size_spin.setFixedWidth(80)
        self.size_spin.setCursor(Qt.ArrowCursor)
        self.size_spin.setStyleSheet(
            f"background: {C['well']}; border: 1px solid {C['border_soft']}; "
            f"color: {C['text_mono']}; padding: 0 6px;"
        )

        self.bold_check = QCheckBox("Gras")
        self.bold_check.setFont(font(11, 400))
        self.bold_check.setChecked(bool(value.get("bold", False)))
        self.bold_check.setCursor(Qt.ArrowCursor)
        self.bold_check.setStyleSheet(f"color: {C['text']};")

        row1.addWidget(self.family_combo, 1)
        row1.addWidget(self.size_spin)
        row1.addWidget(self.bold_check)

        # -- ligne 2 : lissage / couleur --
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(8)

        self.smoothing_combo = QComboBox()
        self.smoothing_combo.setFont(font(11, 400))
        self.smoothing_combo.setFixedHeight(24)
        self.smoothing_combo.setCursor(Qt.ArrowCursor)
        self.smoothing_combo.setStyleSheet(
            f"QComboBox {{ background: {C['well']}; border: 1px solid {C['border_soft']}; "
            f"color: {C['text_mono']}; padding: 0 6px; }}"
        )
        for key in SMOOTHING_CHOICES:
            self.smoothing_combo.addItem(SMOOTHING_LABELS[key], key)
        smoothing = value.get("smoothing") or "current"
        idx = self.smoothing_combo.findData(smoothing)
        self.smoothing_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self._color = (value.get("color") or "").strip()
        self.color_btn = QPushButton()
        self.color_btn.setFixedHeight(24)
        self.color_btn.setFixedWidth(48)
        self.color_btn.setCursor(Qt.PointingHandCursor)
        self.color_btn.clicked.connect(self._pick_color)

        self.color_reset_btn = QPushButton("Auto")
        self.color_reset_btn.setFont(font(10, 400))
        self.color_reset_btn.setFixedHeight(24)
        self.color_reset_btn.setCursor(Qt.ArrowCursor)
        self.color_reset_btn.clicked.connect(self._reset_color)

        row2.addWidget(self.smoothing_combo, 1)
        row2.addWidget(self.color_btn)
        row2.addWidget(self.color_reset_btn)

        outer.addLayout(row1)
        outer.addLayout(row2)

        self._update_color_btn()

        self.family_combo.currentIndexChanged.connect(lambda _: self.changed.emit())
        self.size_spin.valueChanged.connect(lambda _: self.changed.emit())
        self.bold_check.toggled.connect(lambda _: self.changed.emit())
        self.smoothing_combo.currentIndexChanged.connect(lambda _: self.changed.emit())

    def _update_color_btn(self):
        if self._color:
            self.color_btn.setStyleSheet(
                f"background: {self._color}; border: 1px solid {C['border_soft']};"
            )
            self.color_btn.setText("")
        else:
            self.color_btn.setStyleSheet(
                f"background: {C['well']}; border: 1px solid {C['border_soft']}; color: {C['dim']};"
            )
            self.color_btn.setText("—")

    def _pick_color(self):
        initial = QColor(self._color) if self._color else QColor(C["text"])
        chosen = QColorDialog.getColor(initial, self, "Couleur du texte")
        if chosen.isValid():
            self._color = chosen.name()
            self._update_color_btn()
            self.changed.emit()

    def _reset_color(self):
        if self._color:
            self._color = ""
            self._update_color_btn()
            self.changed.emit()

    def value(self) -> dict:
        idx = self.family_combo.currentIndex()
        family = "" if idx == 0 else self.family_combo.currentText()
        return {
            "family": family,
            "size": self.size_spin.value(),
            "bold": self.bold_check.isChecked(),
            "smoothing": self.smoothing_combo.currentData() or "current",
            "color": self._color,
        }


class SettingsWindow(QDialog):
    """Fenetre (non modale) de parametres de l'application. Chaque
    changement est previsualise en direct sur la fenetre principale
    (settingsChanged) sans toucher au disque ; Enregistrer persiste et
    confirme (settingsSaved). Annuler / fermer sans enregistrer restaure la
    previsualisation a l'etat d'avant ouverture."""

    # Emis a CHAQUE changement de reglage (previsualisation, pas persiste).
    settingsChanged = Signal(dict)
    # Emis une fois, apres un clic sur Enregistrer (persiste sur le disque).
    settingsSaved = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Parametres")
        self.setMinimumWidth(460)
        self.setStyleSheet(f"background: {C['window']}; color: {C['text']};")

        self.settings = load_settings()
        self._original_settings = json.loads(json.dumps(self.settings))  # copie profonde
        self._saved = False

        title = QLabel("Parametres")
        title.setFont(role_font("app", 14, 600))
        title.setStyleSheet(f"color: {C['text']}; background: transparent;")

        subtitle = QLabel("Pipeline Browser")
        subtitle.setFont(role_font("info", 10, 400))
        subtitle.setStyleSheet(f"color: {C['dim']}; background: transparent;")

        # --- General ---
        general = _Section("General")

        self.root_field = QLineEdit(self.settings["root_path"])
        self.root_field.setFont(font(12, 400, mono=True))
        self.root_field.setFixedHeight(24)
        self.root_field.setStyleSheet(
            f"background: {C['well']}; border: 1px solid {C['border_soft']}; "
            f"color: {C['text_mono']}; padding: 0 8px;"
        )
        browse_btn = QPushButton("Parcourir")
        browse_btn.setFont(font(11, 500))
        browse_btn.setFixedHeight(24)
        browse_btn.setCursor(Qt.ArrowCursor)
        browse_btn.clicked.connect(self._browse_root)

        root_row = QWidget()
        root_row_layout = QHBoxLayout(root_row)
        root_row_layout.setContentsMargins(0, 0, 0, 0)
        root_row_layout.setSpacing(8)
        root_row_layout.addWidget(self.root_field, 1)
        root_row_layout.addWidget(browse_btn)
        general.add_row("Racine par defaut", root_row)

        self.remember_root_check = self._make_check(self.settings["remember_last_root"])
        general.add_row("Se souvenir de la derniere racine parcourue", self.remember_root_check)

        # --- Affichage ---
        display = _Section("Affichage")
        self.column_width_spin = self._make_spin(120, 640, self.settings["column_width"], " px")
        display.add_row("Largeur des colonnes", self.column_width_spin)
        self.row_height_spin = self._make_spin(
            40, 160, self.settings["project_row_height"], " px"
        )
        display.add_row("Hauteur des lignes Projets / Sous-projet", self.row_height_spin)
        self.row_spacing_spin = self._make_spin(0, 20, self.settings["row_spacing"], " px")
        display.add_row("Espacement entre les fichiers", self.row_spacing_spin)

        # --- Vignettes et icones ---
        thumbs = _Section("Vignettes et icones")
        self.thumb_dim_spin = self._make_spin(
            128, 4096, self.settings["thumbnail_max_dim"], " px"
        )
        thumbs.add_row("Taille max. des vignettes de projet", self.thumb_dim_spin)
        self.icon_dim_spin = self._make_spin(
            32, 1024, self.settings["software_icon_max_dim"], " px"
        )
        thumbs.add_row("Taille max. des icones logicielles", self.icon_dim_spin)
        self.file_preview_check = self._make_check(self.settings["show_file_image_previews"])
        thumbs.add_row(
            "Afficher un apercu (style Projets) pour les fichiers image",
            self.file_preview_check,
        )
        self.file_preview_size_spin = self._make_spin(
            40, 200, self.settings["file_preview_size"], " px"
        )
        thumbs.add_row("Taille de l'apercu des fichiers image", self.file_preview_size_spin)

        # --- Securite ---
        safety = _Section("Securite")
        self.confirm_move_check = self._make_check(self.settings["confirm_before_move"])
        safety.add_row("Confirmer avant de deplacer des fichiers", self.confirm_move_check)

        # --- Typographie ---
        typo = _Section("Typographie")
        self.font_files_row = _FontRow(self.settings["font_files"])
        typo.add_row("Fichiers", self.font_files_row)
        self.font_folders_row = _FontRow(self.settings["font_folders"])
        typo.add_row("Dossiers", self.font_folders_row)
        self.font_info_row = _FontRow(self.settings["font_info"])
        typo.add_row("Informations diverses (compteurs, chemins...)", self.font_info_row)
        self.font_buttons_row = _FontRow(self.settings["font_buttons"])
        typo.add_row("Boutons", self.font_buttons_row)
        self.font_app_row = _FontRow(self.settings["font_app"])
        typo.add_row("Ensemble de l'appli (repli des roles ci-dessus)", self.font_app_row)

        # --- Boutons ---
        self.status_label = QLabel("")
        self.status_label.setFont(role_font("info", 10, 400))
        self.status_label.setStyleSheet(f"color: {C['dim']}; background: transparent;")

        cancel_btn = QPushButton("Annuler")
        cancel_btn.setFont(role_font("buttons", 11, 500))
        cancel_btn.setFixedHeight(28)
        cancel_btn.setCursor(Qt.ArrowCursor)
        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("Enregistrer")
        save_btn.setFont(role_font("buttons", 11, 500))
        save_btn.setFixedHeight(28)
        save_btn.setCursor(Qt.ArrowCursor)
        save_btn.setStyleSheet(
            f"QPushButton {{ background: {C['accent']}; border: 1px solid {C['accent']}; "
            f"color: {C['accent_text']}; padding: 0 14px; }}"
        )
        save_btn.clicked.connect(self._on_save)

        buttons = QHBoxLayout()
        buttons.addWidget(self.status_label)
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(20)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        for section in (general, display, thumbs, safety, typo):
            layout.addWidget(self._with_separator(section))
        layout.addStretch(1)
        layout.addLayout(buttons)

        # -- previsualisation en direct : tout changement (hors racine, qui
        # ne s'applique qu'a l'enregistrement pour eviter de re-scanner le
        # disque a chaque frappe) previsualise immediatement sur la fenetre
        # principale, sans toucher au disque. --
        self.column_width_spin.valueChanged.connect(self._on_live_change)
        self.row_height_spin.valueChanged.connect(self._on_live_change)
        self.row_spacing_spin.valueChanged.connect(self._on_live_change)
        self.thumb_dim_spin.valueChanged.connect(self._on_live_change)
        self.icon_dim_spin.valueChanged.connect(self._on_live_change)
        self.file_preview_check.toggled.connect(self._on_live_change)
        self.file_preview_size_spin.valueChanged.connect(self._on_live_change)
        self.confirm_move_check.toggled.connect(self._on_live_change)
        for row in (
            self.font_files_row, self.font_folders_row, self.font_info_row,
            self.font_buttons_row, self.font_app_row,
        ):
            row.changed.connect(self._on_live_change)

    # -- petits constructeurs de widgets, pour rester coherent visuellement --

    def _make_spin(self, minimum: int, maximum: int, value: int, suffix: str = "") -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setFont(font(11, 400, mono=True))
        spin.setFixedHeight(24)
        spin.setFixedWidth(110)
        spin.setCursor(Qt.ArrowCursor)
        spin.setStyleSheet(
            f"background: {C['well']}; border: 1px solid {C['border_soft']}; "
            f"color: {C['text_mono']}; padding: 0 6px;"
        )
        spin.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        return spin

    def _make_check(self, checked: bool) -> QCheckBox:
        check = QCheckBox()
        check.setChecked(checked)
        check.setCursor(Qt.ArrowCursor)
        return check

    def _with_separator(self, widget: QWidget) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(widget)
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {C['border']};")
        layout.addWidget(line)
        return container

    # -- actions --

    def _browse_root(self):
        chosen = QFileDialog.getExistingDirectory(self, "Racine par defaut", self.root_field.text())
        if chosen:
            self.root_field.setText(chosen)

    def _current_values(self) -> dict:
        """Etat courant de tous les controles (utilise a la fois pour la
        previsualisation en direct et pour l'enregistrement final)."""
        return {
            "root_path": self.root_field.text().strip() or DEFAULT_SETTINGS["root_path"],
            "remember_last_root": self.remember_root_check.isChecked(),
            "column_width": self.column_width_spin.value(),
            "project_row_height": self.row_height_spin.value(),
            "row_spacing": self.row_spacing_spin.value(),
            "thumbnail_max_dim": self.thumb_dim_spin.value(),
            "software_icon_max_dim": self.icon_dim_spin.value(),
            "show_file_image_previews": self.file_preview_check.isChecked(),
            "file_preview_size": self.file_preview_size_spin.value(),
            "confirm_before_move": self.confirm_move_check.isChecked(),
            "font_files": self.font_files_row.value(),
            "font_folders": self.font_folders_row.value(),
            "font_info": self.font_info_row.value(),
            "font_buttons": self.font_buttons_row.value(),
            "font_app": self.font_app_row.value(),
        }

    def _on_live_change(self, *_args):
        self.settingsChanged.emit(self._current_values())

    def _on_save(self):
        self.settings = self._current_values()
        save_settings(self.settings)
        self._saved = True
        self.settingsSaved.emit(self.settings)
        self.accept()

    def reject(self):
        # Annuler (ou fermer via la croix, qui appelle reject() par defaut) :
        # si rien n'a ete enregistre, on restaure la previsualisation a
        # l'etat d'avant ouverture de la fenetre.
        if not self._saved:
            self.settingsChanged.emit(self._original_settings)
        super().reject()


def main():
    app = QApplication(sys.argv)
    apply_style(app)
    win = SettingsWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
