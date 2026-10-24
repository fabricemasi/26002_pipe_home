"""Isolement des tests : les fichiers de reglages, de presets et d'etat des fenetres sont redirigés vers des
COPIES temporaires. A importer en tete de tout test qui ouvre une fenetre de reglages ou enregistre quoi que
ce soit (`import _isolate  # noqa`), AVANT les modules de l'appli.

Pourquoi (signale) : SaveTest enregistrait, et l'enregistrement met aussi a jour le preset ACTIF
(settings_store.update_active_preset) dans le VRAI fichier de presets — le preset « fab » de l'utilisateur
recevait les valeurs du test (curseurs 20 / 9), que l'appli rejouait ensuite par-dessus ses reglages."""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import settings_store  # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="pipe_tests_"))
atexit.register(shutil.rmtree, _TMP, True)
# Registre des mots cles deja employes (file_attributes.KEYWORDS_PATH) : jamais celui de l'utilisateur.
os.environ["PIPELINE_KEYWORDS_FILE"] = str(_TMP / "file_keywords.json")

for _name in ("_PER_USER_PATH", "_PRESETS_PATH", "_WINDOW_STATE_PATH"):
    _real = getattr(settings_store, _name)
    _copy = _TMP / _real.name
    if _real.is_file():
        shutil.copyfile(_real, _copy)          # memes valeurs que l'utilisateur, mais jamais son fichier
    setattr(settings_store, _name, _copy)

REAL_DATA_UNTOUCHED = True

# État de la FENÊTRE PRINCIPALE (distinct de celui des réglages ci-dessus).
# Les sondes de navigation ferment des fenêtres hors écran : ne jamais
# enregistrer leur géométrie / dernier chemin dans la vraie session.
os.environ["PIPELINE_MAIN_WINDOW_STATE_FILE"] = str(_TMP / "pipeline_window_state.json")

# La fenetre de reglages construit ses sections en fond a l'ouverture (~20 s) : inutile et lent en test.
os.environ.setdefault("PIPELINE_NO_PREBUILD", "1")
# Feuille CSS partagee avec Obsidian (Reglages > Markdown > CSS, par defaut celle du coffre de l'utilisateur) : la
# synchronisation ne lit ni n'ecrit jamais ce fichier en test ; seuls les tests de mdeditor/css_sync.py l'allument,
# sur des copies temporaires.
os.environ["PIPELINE_NO_CSS_SYNC"] = "1"
