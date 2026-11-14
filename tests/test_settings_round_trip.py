"""Aller-retour de TOUS les champs de réglages (2026-11-12, « il y a encore des bugs dans les settings ») : pour chaque
ligne de chaque fenêtre (CATALOG), avec de vraies valeurs (défauts, réglages de l'utilisateur, chaque preset fm_theme),
le champ construit sur ces valeurs les RELIT à l'identique, et les mêmes valeurs VERSÉES dans un champ construit sur
les défauts (chemin des variantes / presets : `write_spec`) aussi. Un écart = ouvrir les réglages puis enregistrer
sans rien toucher change l'aspect. Bugs trouvés ainsi : padding de page Markdown rogné à 32 (défaut 40), rayon
Bouton / Zone de saisie à None affiché 0, paddings Focus > Zone titre liés par défaut avec des côtés inégaux."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import copy
import json
import os
import re
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import settings_store as ss  # noqa: E402
import settings_window_v2 as v2  # noqa: E402
from _lent import lent  # noqa: E402
from settings_catalog import CATALOG  # noqa: E402
from fm_theme.style import BUTTON_STATE_FOLLOW, button_state_override, button_state_value  # noqa: E402

_OVERRIDE_FLAG = re.compile(r"^button_(hover|focus|active)_ovr_(\w+)$")
_CORNERS = ("top_left", "top_right", "bottom_right", "bottom_left")

# Écarts VOULUS (une raison chacun) ; tout le reste fait échouer le test.
_ALLOWED = (
    # Lissage : le toggle « Forcer » a été supprimé (demande de l'utilisateur), le lissage choisi s'applique toujours.
    lambda key, _a, _b: key.endswith(("_smoothing_enabled", "_antialias_override_enabled")),
    # Copies des menus du board et overrides de la barre : override coupé = la valeur SUIVIE est affichée.
    lambda key, _a, _b: key.startswith(("board_ctx_menu", "navtool_")),
    # Types de ligne CAD : liste vide = ceux du board, affichés.
    lambda key, _a, _b: key == "board_cad_linetypes",
    # Ancien rayon de fenêtre (entier) devenu un toggle (0 / WINDOW_RADIUS_ON).
    lambda key, _a, _b: key == "window_radius",
    # Ancien format « bordure : True » = les 4 côtés.
    lambda _k, a, b: a is True and isinstance(b, dict) and all(x is True for x in b.values()),
    # Rayon None = l'ancien rayon `<prefix>_radius`, relu à sa valeur.
    lambda key, a, _b: a is None and key in ("button_corner_radius", "input_corner_radius"),
)


def _norm(value):
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, dict) and set(value) == set(_CORNERS) and len(set(value.values())) == 1:
        return next(iter(value.values()))                      # rayon uniforme = nombre
    if (isinstance(value, dict) and set(value) <= {"left", "top", "right", "bottom"}
            and all(x in (0, None) and not isinstance(x, bool) for x in value.values())):
        return {}                                              # padding nul = {}
    if isinstance(value, str) and value.startswith("#"):
        return value.lower()
    if isinstance(value, dict):
        return {k: _norm(x) for k, x in value.items()}
    if isinstance(value, (list, tuple)):
        return [_norm(x) for x in value]
    return value


def _sources() -> dict:
    out = {"défauts": copy.deepcopy(ss.DEFAULT_SETTINGS), "utilisateur": ss.load_settings()}
    for name in ss.preset_names():
        values = copy.deepcopy(ss.DEFAULT_SETTINGS)
        values.update(ss._load_theme_values(name))
        out[f"preset {name}"] = values
    return out


class RoundTripTest(unittest.TestCase):
    @lent                                  # ~9 000 champs construits (une à deux minutes)
    def test_every_field_reads_back_what_it_was_given(self):
        families = set(QFontDatabase.families())
        defaults = copy.deepcopy(ss.DEFAULT_SETTINGS)
        problems = []

        def check(stage, group, label, src, got):
            for key, value in got.items():
                if ss._ACTIVATION_KEY.search(key) or key not in src:
                    continue
                want = src[key]
                if key in BUTTON_STATE_FOLLOW:                 # état du bouton : la valeur qu'il UTILISE (override)
                    want = button_state_value(src, key, want)
                    if want is None and key.endswith("_corner_radius"):
                        want = src.get("button_radius", 0)     # rayon None = l'ancien rayon des boutons, relu
                elif _OVERRIDE_FLAG.match(key) and want is None:  # toggle jamais enregistré : déduit des valeurs
                    state, row = _OVERRIDE_FLAG.match(key).groups()
                    want = button_state_override(src, state, row)
                if key.endswith("font_family") and want and want not in families:
                    continue                                   # police absente de cette machine / plateforme
                if isinstance(want, dict) and want.get("family") and want["family"] not in families:
                    want = dict(want, family=value.get("family") if isinstance(value, dict) else "")
                if json.dumps(_norm(value), sort_keys=True) == json.dumps(_norm(want), sort_keys=True):
                    continue
                if any(rule(key, want, value) for rule in _ALLOWED):
                    continue
                problems.append(f"{stage} | {group} | {key} | {label} | attendu {want!r} | relu {value!r}")

        for label, src in _sources().items():
            colors = src.get("colors", defaults["colors"])
            for group, specs in CATALOG.items():
                for spec in specs:
                    if isinstance(spec, str) or spec.kind == "ui_icon" or spec.kind not in v2.FIELD_FACTORIES:
                        continue
                    built = v2.make_field(spec, v2.ScopeValues(copy.deepcopy(src), None), colors)
                    check("construit", group, label, src, v2.read_spec(spec, built))
                    built.deleteLater()
                    if spec.kind in v2.FIELD_WRITERS:
                        poured = v2.make_field(spec, v2.ScopeValues(copy.deepcopy(defaults), None), defaults["colors"])
                        if v2.write_spec(spec, poured, src):
                            check("versé", group, label, src, v2.read_spec(spec, poured))
                        poured.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        if problems:
            self.fail(f"{len(problems)} écart(s) :\n" + "\n".join(problems))

    def test_no_default_links_unequal_sides(self):
        """« lier les 4 » vrai par défaut avec des côtés inégaux : le champ alignait tout sur le 1er côté."""
        bad = []
        for key, value in ss.DEFAULT_SETTINGS.items():
            if key.endswith("_linked") and value is True:
                sides = ss.DEFAULT_SETTINGS.get(key[:-len("_linked")])
                if isinstance(sides, dict) and len({json.dumps(x) for x in sides.values()}) > 1:
                    bad.append((key, sides))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
