"""Module Photoshop : l'ACCÉLÉRATION du moteur de trait ne change AUCUN pixel.

Les optimisations (recomposition des pixels une fois par évènement au lieu d'une fois par tampon, canaux de couleur en tête,
puissances limitées au dégradé, tuiles sans effet sautées, appels NumPy regroupés) sont exactes : les empreintes SHA-1 ci-dessous
ont été calculées avec le moteur d'AVANT l'optimisation (copie de `brush.py` du 2026-11-01, comparée aussi sur 290 traits aléatoires
au bit près : sélection, masque, aérographe, retouche, fond semi-transparent, étapes d'annulation). Si l'un de ces tests échoue,
un pixel a changé : ce n'est PAS une optimisation (régénérer les empreintes seulement pour un changement VOULU du rendu)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import hashlib
import math
import os
import sys
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fm_photoshop import brush as BRUSH, model as M, selection as SEL  # noqa: E402
from fm_photoshop.planes import Plane  # noqa: E402

W, H = 420, 260


def walk(seed, n, speed):
    """Trajectoire déterministe : marche aléatoire avec demi-tours (pas de `speed[0]` à `speed[1]` pixels)."""
    rng = np.random.default_rng(seed)
    x, y = rng.uniform(80, W - 80), rng.uniform(60, H - 60)
    ang = rng.uniform(0, 2 * math.pi)
    points = [(x, y)]
    for _ in range(n):
        ang += rng.normal(0, 0.35) + (math.pi if rng.random() < 0.03 else 0.0)
        step = rng.uniform(*speed)
        x = min(W - 12, max(12, x + math.cos(ang) * step))
        y = min(H - 12, max(12, y + math.sin(ang) * step))
        points.append((x, y))
    return points


# nom -> (réglages de la brosse, genre, graine, nombre de points, vitesse)
SPECS = {
    "dur_24": (dict(size=24.0, hardness=1.0, spacing=0.2), "plain", 1, 60, (4.0, 30.0)),
    "dur_24_flux_30": (dict(size=24.0, hardness=0.8, flow=0.3), "plain", 2, 60, (4.0, 30.0)),
    "mou_100": (dict(size=100.0, hardness=0.0), "plain", 3, 40, (6.0, 30.0)),
    "cumul_60": (dict(size=60.0, hardness=0.5, paint_mode="buildup", flow=0.5), "plain", 4, 40, (4.0, 25.0)),
    "fin_6": (dict(size=6.0, hardness=1.0), "plain", 5, 70, (2.0, 14.0)),
    "fin_11_mou": (dict(size=11.0, hardness=0.3, flow=0.6), "plain", 6, 60, (2.0, 14.0)),
    "pression": (dict(size=40.0, hardness=0.6, pressure_size=True, pressure_flow=True), "plain", 7, 60, (3.0, 25.0)),
    "gomme_bruit": (dict(size=30.0, hardness=0.7, eraser=True), "noisy", 8, 50, (3.0, 25.0)),
    "selection": (dict(size=30.0, hardness=0.7, opacity=0.6), "selection", 9, 50, (3.0, 25.0)),
    "masque": (dict(size=36.0, hardness=0.4), "mask", 10, 50, (3.0, 25.0)),
    "stabilisateur": (dict(size=20.0, hardness=0.9, smoothing=0.7, smoothing_mode="stabilizer"), "plain", 11, 60, (3.0, 25.0)),
    "aerographe": (dict(size=50.0, hardness=0.0, flow=0.3, airbrush=True), "air", 12, 40, (3.0, 20.0)),
    "flou_bruit": (dict(size=30.0, hardness=0.5, mode="blur"), "noisy", 13, 40, (3.0, 20.0)),
    "tampon": (dict(size=24.0, hardness=0.8, mode="clone"), "noisy", 14, 40, (3.0, 20.0)),
    "grand_150": (dict(size=150.0, hardness=0.3), "plain", 15, 16, (10.0, 40.0)),
}

# Empreintes SHA-1 (pixels finaux du plan peint) calculées par le moteur d'AVANT l'optimisation.
GOLDEN = {
    "dur_24": "a50cdfa2daffba0172303a436df475f824bb45bc",
    "dur_24_flux_30": "7c8464d38fa99e7d20cc0e652d223d81b165dff4",
    "mou_100": "186eedeb9443b97a4e4a0fa823a6d0660226df77",
    "cumul_60": "a4bb6588da003ddfadb8ae96a8055c447638624a",
    "fin_6": "45c9302d6b27957cd8663e98a378bc99da285a6f",
    "fin_11_mou": "f0da516b6f57d1dc96c98ad389a0bc2e7aaccf93",
    "pression": "2b94339e0b375ccb9a363138135b1157719aa659",
    "gomme_bruit": "8e21ee6cf96544fbbca68e1f357b0008751d4926",
    "selection": "2eff5984f979310241332d0bad3453df3b219b50",
    "masque": "8f71b0ffbb1d94b076bcc5fdeb19bd6657f7888a",
    "stabilisateur": "0a0123fb5b88e554a3163f01edfa409bead9b234",
    "aerographe": "df5fa8baef8edd9212f7feee25ec862844dde381",
    "flou_bruit": "f9a894a6daac09674dd6ba49996f70b251d62faa",
    "tampon": "beff022c34b25e408977a50b3f0a64abd29d228c",
    "grand_150": "c9e8543c14b2d0d9f0f9b627e04a630de3f70d6c",
}


def run_spec(name, module=BRUSH, defer=None, count_writes=None):
    """Rend (pixels finaux, étape d'annulation) du scénario `name` avec le moteur `module`."""
    kwargs, kind, seed, n, speed = SPECS[name]
    rng = np.random.default_rng(seed + 500)
    doc = M.new_document(W, H, background=None)
    layer = doc.layers[0]
    if kind in ("noisy", "selection") or name == "mou_100":
        noise = rng.integers(0, 256, (H, W, 4), dtype=np.uint8)
        noise[..., 3] = rng.choice([0, 7, 128, 200, 255], size=(H, W))      # fond semi-transparent : le cas difficile
        layer.pix.set_all(0, 0, noise)
    selection, target, retouch = None, "pixels", None
    if kind == "selection":
        selection = SEL.ellipse(doc.rect(), (60, 40, W - 60, H - 40))
    if kind == "mask":
        layer.mask = M.Mask(Plane(1, 255), True)
        layer.mask.plane.set_all(0, 0, rng.integers(0, 256, (H, W, 1), dtype=np.uint8))
        target = "mask"
    if kwargs.get("mode") == "clone":
        retouch = {"offset": (-17, 11)}
    brush = module.Brush(color=(30, 90, 200), **kwargs)
    stroke = module.Stroke(layer, target, brush, doc.rect(), selection, retouch)
    if defer is not None:
        stroke._defer = defer
    plane = layer.mask.plane if target == "mask" else layer.pix
    patch = None
    if count_writes is not None:
        real = Plane.write

        def counting(self, rect, array, *args, **kwargs):
            if self is plane:
                count_writes.append(tuple(rect))
            return real(self, rect, array, *args, **kwargs)
        patch = mock.patch.object(Plane, "write", counting)
        patch.start()
    points = walk(seed, n, speed)
    air = kind == "air"
    stroke.begin(points[0][0], points[0][1], 0.6, air_now=0.0) if air else stroke.begin(points[0][0], points[0][1], 0.6)
    for i in range(1, len(points)):
        p = 0.5 + 0.5 * math.sin(i / 7.0) if kwargs.get("pressure_size") else 1.0
        if air:
            stroke.move(points[i][0], points[i][1], p, t=i / 120.0, air_now=i / 120.0)
            if i % 3 == 0:
                stroke.air_tick(i / 120.0 + 0.004)
        else:
            stroke.move(points[i][0], points[i][1], p, t=i / 120.0)
    stroke.finish_to(points[-1][0], points[-1][1], 0.5)
    command = stroke.end("essai")
    if patch is not None:
        patch.stop()
    pieces = [] if command is None else [(r, b.tobytes(), a.tobytes()) for r, b, a in command.pieces]
    return plane.read(doc.rect()), pieces


def digest(pixels, pieces) -> str:
    h = hashlib.sha1(pixels.tobytes())
    for rect, before, after in pieces:
        h.update(repr(rect).encode())
        h.update(before)
        h.update(after)
    return h.hexdigest()


class EngineIdentityTest(unittest.TestCase):
    def test_every_scenario_matches_the_engine_before_the_optimisation(self):
        for name in SPECS:
            with self.subTest(scenario=name):
                self.assertEqual(digest(*run_spec(name)), GOLDEN[name], f"{name} : un pixel (ou l'étape d'annulation) a changé")

    def test_deferred_recomposition_equals_immediate_recomposition(self):
        # La recomposition par évènement (défaut) et celle par tampon (ancienne méthode, gardée pour les outils de retouche)
        # donnent les mêmes octets : le différé est une pure économie.
        for name in ("dur_24", "mou_100", "cumul_60", "fin_11_mou", "gomme_bruit", "selection", "masque", "pression"):
            with self.subTest(scenario=name):
                late, immediate = run_spec(name, defer=True), run_spec(name, defer=False)
                np.testing.assert_array_equal(late[0], immediate[0])
                self.assertEqual(late[1], immediate[1])

    def test_pixels_are_recomposed_once_per_event_not_once_per_dab(self):
        deferred, immediate = [], []
        run_spec("dur_24", defer=True, count_writes=deferred)
        run_spec("dur_24", defer=False, count_writes=immediate)
        self.assertLess(len(deferred) * 4, len(immediate))                       # au moins 4 fois moins d'écritures du plan
        # et jamais de zone en attente entre deux appels publics
        kwargs, _kind, _seed, _n, _speed = SPECS["dur_24"]
        doc = M.new_document(W, H, background=None)
        stroke = BRUSH.Stroke(doc.layers[0], "pixels", BRUSH.Brush(color=(0, 0, 0), **kwargs), doc.rect())
        stroke.begin(50.0, 50.0, 1.0)
        self.assertEqual(stroke._pend, {})
        stroke.move(300.0, 80.0, 1.0, t=0.01)
        self.assertEqual(stroke._pend, {})
        self.assertGreater(stroke.dabs, 20)
        stroke.finish_to(320.0, 90.0, 1.0)
        self.assertEqual(stroke._pend, {})

    def test_retouch_tools_keep_the_immediate_path(self):
        # flou / netteté / tampon relisent le plan : jamais de recomposition différée ni de tuile sautée
        for name in ("flou_bruit", "tampon"):
            with self.subTest(scenario=name):
                kwargs, kind, seed, n, speed = SPECS[name]
                doc = M.new_document(W, H, background=None)
                retouch = {"offset": (-17, 11)} if kwargs.get("mode") == "clone" else None
                stroke = BRUSH.Stroke(doc.layers[0], "pixels", BRUSH.Brush(color=(0, 0, 0), **kwargs), doc.rect(), None, retouch)
                self.assertFalse(stroke._defer)


if __name__ == "__main__":
    unittest.main()
