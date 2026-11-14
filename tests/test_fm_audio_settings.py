"""Réglages de FM Audio / FM Music : défauts déclarés, lignes du CATALOG, fenêtre « Réglages : Audio »."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from _window_cleanup import WindowTestCase, track  # noqa: E402
import settings_store  # noqa: E402

app = QApplication.instance() or QApplication([])


class AudioSettingsTest(WindowTestCase):
    def test_defaults_catalog_and_window(self):
        import settings_window_v2 as v2
        from fm_audio.settings import AUDIO_TAB, AUDIO_TREE
        from fm_audio.settings_defaults import AUDIO_DEFAULTS
        from settings_catalog import CATALOG
        from fm_music.settings import MUSIC_TAB, MUSIC_TREE
        keys = {s.key for tree in (AUDIO_TREE, MUSIC_TREE) for node in tree for s in CATALOG[node.group]
                if s.kind != "ui_icon"}                  # icônes du cadre : clés d'icône, pas des valeurs
        self.assertTrue(keys)
        from fm_music.settings_defaults import MUSIC_DEFAULTS
        self.assertTrue(keys <= set(AUDIO_DEFAULTS) | set(MUSIC_DEFAULTS))
        self.assertTrue(keys <= set(settings_store.DEFAULT_SETTINGS))
        loaded = settings_store.load_settings()
        for k in keys:
            self.assertIn(k, loaded)
        self.assertEqual(v2.MODULE_SCOPES["audio"], [(AUDIO_TAB, None)])
        self.assertEqual(v2.MODULE_SCOPES["music"], [(MUSIC_TAB, None)])
        self.assertEqual((v2.MODULE_TITLES["audio"], v2.MODULE_TITLES["music"]), ("FM Audio", "FM Music"))
        for module in ("audio", "music"):
            w = track(v2.SettingsWindowV2(None, module=module))
            self.assertIsNotNone(w)


if __name__ == "__main__":
    unittest.main()
