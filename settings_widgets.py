"""Ancien nom de `fm_theme.widgets` (transition fm_theme, étape 2) : c'est le MÊME module (alias dans
sys.modules), donc les patches des tests et les valeurs réaffectées à l'exécution restent communs.
Ne rien ajouter ici : le code est dans fm_theme/."""
import sys

from fm_theme import widgets as _module

sys.modules[__name__] = _module
