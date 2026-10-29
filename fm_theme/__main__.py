"""Lanceur `python -m fm_theme` (fm_theme.bat, à la racine) : l'éditeur fm_theme.

La fenêtre de réglages réduite à l'ASPECT, qui lit et écrit un preset fm_theme (fm_theme/presets/<nom>.json),
avec la gestion des presets et la diffusion en direct vers les applis ouvertes (theme_editor.py). Les applis
liées à ce preset le relisent à l'enregistrement.

Seul fichier du paquet qui importe fm_browser (l'éditeur s'appuie encore sur sa fenêtre de réglages) : un
lanceur, jamais importé par la bibliothèque.
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def main() -> int:
    import pipeline_browser as pb
    import theme_editor
    from fm_theme.live import LiveServer

    pb._install_error_log()
    pb._install_qt_message_filter()
    pb.apply_all_settings(pb.load_settings(startup=True))
    QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    pb.apply_style(app)
    pb._install_context_menus()
    editor = theme_editor.ThemeEditor(theme_editor.initial_preset(), server=LiveServer(app))
    app._fm_theme_editor = editor            # garde l'editeur en vie
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
