"""Explorateur de fichiers et dialogues de vignettes. Carte : docs/agents/colonnes.md."""

import subprocess
import sys
from pathlib import Path
from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget
from config import THUMBNAIL_MAX_DIM
from previews import forget_mtime as _forget_mtime
from previews import _set_hidden, _smooth_scale_down
from . import capture as _capture
from . import icons as _icons

def open_path(path: Path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

def open_in_file_manager(path: Path):
    """Ouvre le dossier `path` lui-meme dans l'explorateur (double-clic sur un
    dossier, voir PipelineBrowser.on_activated)."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", str(path)])
    else:
        open_path(path)

def reveal_in_file_manager(path: Path):
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])

# Gestion de la vignette perso d'un dossier (voir project_thumbnail_path) —
# fonctions LIBRES (pas des methodes Column), pour etre partagees par
# Column._change_thumbnail/_capture_thumbnail/_save_thumbnail_pixmap/
# _reset_thumbnail (menu clic droit d'une ligne normale) ET
# _PreviewBlock._on_context_menu (menu clic droit d'un bloc Focus, voir sa
# remarque de tete) — voir la remarque de l'utilisateur, "les fichiers et
# dossiers de focus ne fonctionnent pas comme les autres colonnes,
# notamment pour le clic droit". `anchor` : SEULEMENT utilise comme parent
# de dialogue (QFileDialog/QMessageBox, n'importe quel QWidget convient)
# et pour garder une reference Python vivante sur la capture d'ecran en
# cours (voir _prompt_capture_thumbnail, `anchor._capture_overlay`) tant
# que la fenetre de selection est ouverte — jamais suppose etre un Column.
# `on_done` : callback SANS argument, appele apres une ecriture/suppression
# reussie (le SEUL bout specifique a l'appelant — un repaint de liste pour
# Column, un rechargement de pixmap pour _PreviewBlock).


def _prompt_change_thumbnail(anchor: QWidget, path: Path, on_done) -> None:
    # QTimer.singleShot(0, ...) : NE JAMAIS ouvrir ce QFileDialog
    # DIRECTEMENT depuis ce slot — appele depuis un menu CONTEXTUEL tout
    # juste ferme (voir Column._on_context_menu/_PreviewBlock.
    # _show_context_menu, menu.exec(...) qui vient de retourner) : ouvrir
    # un 2e dialogue modal DANS LE MEME CYCLE D'EVENEMENTS que la
    # fermeture du 1er est un piege Qt classique — le clic de
    # relachement qui a ferme le menu se fait parfois REINTERPRETER par
    # le NOUVEAU dialogue comme un clic EN DEHORS de lui, le refermant
    # INSTANTANEMENT — voir la remarque de l'utilisateur, "quand je
    # clique sur changer l'icone du logiciel, la fenetre pour choisir
    # une nouvelle image se referme tout de suite" (meme mecanisme,
    # voir _change_software_icon). QTimer.singleShot(150, ...) — PAS 0
    # (essaye puis insuffisant sur _change_software_icon, voir la
    # remarque de l'utilisateur "cette fois-ci aucune fenetre ne
    # s'ouvre" : un simple tour de boucle Qt ne suffit pas a laisser
    # Windows relacher completement le grab souris/clavier NATIF du
    # menu contextuel tout juste ferme). Meme delai deja utilise
    # ailleurs dans ce fichier pour un probleme de meme nature
    # (_capture_thumbnail/_capture_software_icon).
    def open_dialog():
        chosen, _ = QFileDialog.getOpenFileName(
            anchor, "Choisir une image", str(path),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff)",
        )
        if not chosen:
            return
        pix = QPixmap(chosen)
        if pix.isNull():
            QMessageBox.warning(anchor, "Image", "Impossible de charger cette image.")
            return
        _save_thumbnail_pixmap_for(path, pix, anchor, on_done)

    QTimer.singleShot(150, open_dialog)

def _prompt_capture_thumbnail(anchor: QWidget, path: Path, on_done) -> None:
    """Ouvre un selecteur de zone carree (un par ecran connecte) pour
    capturer une vignette de projet directement depuis l'affichage."""
    win = anchor.window()
    was_visible = win.isVisible()
    if was_visible:
        win.hide()
    QApplication.processEvents()

    def start_overlay():
        capture = _capture.MultiScreenCapture()
        anchor._capture_overlay = capture  # garde une reference tant que les fenetres sont ouvertes

        def finish():
            if was_visible:
                win.show()
            anchor._capture_overlay = None

        def on_captured(pix: QPixmap):
            finish()
            _save_thumbnail_pixmap_for(path, pix, anchor, on_done)

        capture.captured.connect(on_captured)
        capture.cancelled.connect(finish)

    # Laisse le temps a la fenetre principale de disparaitre avant la
    # capture, sinon elle apparait encore dans la vignette.
    QTimer.singleShot(150, start_overlay)

def _save_thumbnail_pixmap_for(path: Path, pix: QPixmap, anchor: QWidget, on_done) -> None:
    if pix.isNull():
        return
    if max(pix.width(), pix.height()) > THUMBNAIL_MAX_DIM:
        pix = _smooth_scale_down(pix, QSize(THUMBNAIL_MAX_DIM, THUMBNAIL_MAX_DIM), Qt.KeepAspectRatio)
    dest = _icons.project_thumbnail_path(path)
    _forget_mtime(dest)
    if not pix.save(str(dest), "PNG"):
        QMessageBox.warning(anchor, "Image", "Impossible d'enregistrer la vignette.")
        return
    _set_hidden(dest)
    on_done()

def _prompt_reset_thumbnail(anchor: QWidget, path: Path, on_done) -> None:
    thumb = _icons.project_thumbnail_path(path)
    _forget_mtime(thumb)
    if thumb.exists():
        try:
            thumb.unlink()
        except OSError as exc:
            QMessageBox.warning(anchor, "Image", f"Impossible de supprimer la vignette :\n{exc}")
            return
    on_done()
