"""Isolation des sondes sans changer leur mesure du préchargement des réglages."""
import os


def isolate():
    before = os.environ.get("PIPELINE_NO_PREBUILD")
    import _isolate
    if not _isolate.REAL_DATA_UNTOUCHED:
        raise RuntimeError("Les réglages réels ne sont pas isolés")
    if before is None:
        os.environ.pop("PIPELINE_NO_PREBUILD", None)


def protected_modules():
    """Modules déjà chargés ayant importé directement les fonctions neutralisées."""
    import sys
    prefixes = ("browser_core_parts.", "column_parts.", "main_window.")
    names = {"capture_widgets", "preview_column", "detail_panel"}
    return tuple(module for name, module in tuple(sys.modules.items())
                 if module is not None and (name in names or name.startswith(prefixes)))
