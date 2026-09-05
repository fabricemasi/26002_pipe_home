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
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
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

from app_style import C, apply_style, font

# ==========================================================================
# Persistance (fichier JSON a cote du script)
# ==========================================================================

SETTINGS_PATH = Path(__file__).resolve().parent / "pipeline_settings.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "root_path": r"F:\PIPELINE",
    "remember_last_root": False,
    "column_width": 220,
    "project_row_height": 64,
    "thumbnail_max_dim": 1024,
    "software_icon_max_dim": 128,
    "confirm_before_move": True,
}


def load_settings() -> dict[str, Any]:
    """Charge les parametres depuis le disque, en completant les cles
    manquantes avec les valeurs par defaut (fichier absent, corrompu, ou
    version anterieure de l'appli avec moins de reglages)."""
    settings = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_PATH.is_file():
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                settings.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
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
        heading.setFont(font(10, 600, tracking=0.9, caps=True))
        heading.setStyleSheet(f"color: {C['header']}; background: transparent;")
        layout.addWidget(heading)

        self.form = QFormLayout()
        self.form.setSpacing(10)
        self.form.setLabelAlignment(Qt.AlignLeft)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(self.form)

    def add_row(self, label_text: str, widget: QWidget):
        label = QLabel(label_text)
        label.setFont(font(11, 400))
        label.setStyleSheet(f"color: {C['text']}; background: transparent;")
        self.form.addRow(label, widget)


class SettingsWindow(QDialog):
    """Fenetre modale de parametres de l'application."""

    # Emis avec le dict complet des parametres, apres un clic sur Enregistrer.
    settingsSaved = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Parametres")
        self.setMinimumWidth(460)
        self.setStyleSheet(f"background: {C['window']}; color: {C['text']};")

        self.settings = load_settings()

        title = QLabel("Parametres")
        title.setFont(font(14, 600))
        title.setStyleSheet(f"color: {C['text']}; background: transparent;")

        subtitle = QLabel("Pipeline Browser")
        subtitle.setFont(font(10, 400, mono=True))
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

        # --- Securite ---
        safety = _Section("Securite")
        self.confirm_move_check = self._make_check(self.settings["confirm_before_move"])
        safety.add_row("Confirmer avant de deplacer des fichiers", self.confirm_move_check)

        # --- Boutons ---
        self.status_label = QLabel("")
        self.status_label.setFont(font(10, 400, mono=True))
        self.status_label.setStyleSheet(f"color: {C['dim']}; background: transparent;")

        cancel_btn = QPushButton("Annuler")
        cancel_btn.setFont(font(11, 500))
        cancel_btn.setFixedHeight(28)
        cancel_btn.setCursor(Qt.ArrowCursor)
        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("Enregistrer")
        save_btn.setFont(font(11, 500))
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
        for section in (general, display, thumbs, safety):
            layout.addWidget(self._with_separator(section))
        layout.addStretch(1)
        layout.addLayout(buttons)

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

    def _on_save(self):
        self.settings = {
            "root_path": self.root_field.text().strip() or DEFAULT_SETTINGS["root_path"],
            "remember_last_root": self.remember_root_check.isChecked(),
            "column_width": self.column_width_spin.value(),
            "project_row_height": self.row_height_spin.value(),
            "thumbnail_max_dim": self.thumb_dim_spin.value(),
            "software_icon_max_dim": self.icon_dim_spin.value(),
            "confirm_before_move": self.confirm_move_check.isChecked(),
        }
        save_settings(self.settings)
        self.settingsSaved.emit(self.settings)
        self.accept()


def main():
    app = QApplication(sys.argv)
    apply_style(app)
    win = SettingsWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
