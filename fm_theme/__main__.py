"""Lanceur `python -m fm_theme` (fm_theme.bat, à la racine).

TEMPORAIRE, en attendant l'éditeur fm_theme (étape 5 de docs/agents/fm_theme.md) : ouvre SEULE la fenêtre de
réglages de fm_browser (Général : l'aspect), sans le navigateur. Les modifications sont enregistrées dans les
réglages et le preset actif, comme depuis l'appli ; une appli déjà ouverte ne les voit qu'à sa prochaine lecture
des réglages (le canal temps réel est l'étape 4).

Seul fichier du paquet qui importe fm_browser : un lanceur, jamais importé par la bibliothèque.
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def main() -> int:
    import pipeline_browser as pb
    from settings_window_v2 import SettingsWindowV2

    pb._install_error_log()
    pb._install_qt_message_filter()
    pb.apply_all_settings(pb.load_settings(startup=True))
    QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    pb.apply_style(app)
    pb._install_context_menus()
    window = SettingsWindowV2()
    # Temps reel : pendant un geste, les valeurs d'aspect modifiees partent vers les applis ouvertes (canal
    # local) ; a l'enregistrement, le preset fm_theme lie est ecrit et les applis relisent son fichier.
    from fm_theme.live import LiveServer
    from fm_theme.presets import theme_key
    from settings_store import theme_in_use
    server = LiveServer(app)

    def broadcast(settings: dict):
        keys = getattr(window, "live_changed_keys", None) or ()
        values = {k: settings[k] for k in keys if k in settings and theme_key(k)}
        name = theme_in_use(settings)
        if name and values:
            server.broadcast(name, values)

    window.settingsChanged.connect(broadcast)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
