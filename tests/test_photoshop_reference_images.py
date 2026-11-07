"""Module Photoshop : images de RÉFÉRENCE du moteur de trait (huit scènes déterministes, voir `_photoshop_scenes.py`).
Une régression de forme, d'anticrénelage ou d'accumulation change ces pixels. Régénérer volontairement :
    PS_UPDATE_REFS=1 python tests/run.py fm_photoshop     (puis relire les images avant de les commiter)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QImage

import _photoshop_scenes as S

FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "references", "photoshop_brush")          # v1 : JAMAIS régénéré
FOLDER_V2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "references", "photoshop_brush_v2")    # modèle hybride
FOLDER_V3 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "references", "photoshop_brush_v3")    # pointes douces fusionnées


def load(path) -> np.ndarray:
    image = QImage(path).convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.width(), 4).copy()


def save(path, pixels) -> None:
    pixels = np.ascontiguousarray(pixels)
    QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.shape[1] * 4, QImage.Format.Format_RGBA8888).copy().save(path)


class ReferenceImagesTest(unittest.TestCase):
    """Références v1 (moteur de la mission précédente) : conservées TELLES QUELLES. Ce que le modèle hybride ne devait pas
    changer (pointes dures, petits cercles, diamètre progressif, plafond, pointe douce) reste identique ; ce qu'il change
    volontairement (accumulation, pression sur l'opacité, douceur ajoutée) est mesuré et borné, jamais « régénéré »."""

    UNCHANGED = {"4_croisement_plafond": (16, 0.03), "5_petits_cercles": (14, 0.08), "6_courbe_diametre_progressif": (2, 0.05),
                 "7_pointe_dure": (2, 0.05), "8_pointe_douce": (2, 0.05)}
    SOFTER = {"1_trait_opacite_constante": (24, 0.8)}              # dureté 80 % : le bord gagne 1,5 px de douceur (feather)

    def test_unchanged_scenes_still_match_the_v1_references(self):
        for name, (limit, mean) in {**self.UNCHANGED, **self.SOFTER}.items():
            ref, got = load(os.path.join(FOLDER, name + ".png")), S.render(name)
            diff = np.abs(ref.astype(np.int32) - got.astype(np.int32))
            self.assertLessEqual(int(diff.max()), limit, f"{name} : écart max {int(diff.max())} / 255")
            self.assertLess(float(diff.mean()), mean, name)

    def test_intentional_changes_against_v1(self):
        ref3, got3 = load(os.path.join(FOLDER, "3_croisement_accumulation.png")), S.render("3_croisement_accumulation")
        self.assertLessEqual(int(got3[..., 0].min()), int(ref3[..., 0].min()) + 2)          # le croisement reste aussi foncé
        ink = lambda a: int((255 - a[..., 0].astype(int)).sum())
        self.assertGreater(ink(got3), 1.05 * ink(ref3))                                    # plus d'effet de tube : plus de matière sur les côtés

    def test_comparison_scenes_match_the_v2_references(self):
        update = os.environ.get("PS_UPDATE_REFS") == "1"
        if update:
            os.makedirs(FOLDER_V2, exist_ok=True)
        for name in S.SCENES_CMP:
            path = os.path.join(FOLDER_V2, name + ".png")
            got = S.render_cmp(name)
            if update:
                save(path, got)
                continue
            self.assertTrue(os.path.exists(path), f"référence manquante : {path} (PS_UPDATE_REFS=1 pour la créer)")
            ref = load(path)
            self.assertEqual(ref.shape, got.shape, name)
            diff = np.abs(ref.astype(np.int32) - got.astype(np.int32))
            self.assertLessEqual(int(diff.max()), 2, f"{name} : écart max {int(diff.max())} / 255")      # (arrondis flottants)
            self.assertLess(float(diff.mean()), 0.05, name)

    def test_soft_tip_scenes_match_the_v3_references(self):
        update = os.environ.get("PS_UPDATE_REFS") == "1"
        if update:
            os.makedirs(FOLDER_V3, exist_ok=True)
        for name in S.SCENES_SOFT:
            path = os.path.join(FOLDER_V3, name + ".png")
            got = S.render_soft(name)
            if update:
                save(path, got)
                continue
            self.assertTrue(os.path.exists(path), f"référence manquante : {path} (PS_UPDATE_REFS=1 pour la créer)")
            diff = np.abs(load(path).astype(np.int32) - got.astype(np.int32))
            self.assertLessEqual(int(diff.max()), 2, f"{name} : écart max {int(diff.max())} / 255")
            self.assertLess(float(diff.mean()), 0.05, name)


if __name__ == "__main__":
    unittest.main()
