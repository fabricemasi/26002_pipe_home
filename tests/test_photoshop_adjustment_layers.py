"""Module Photoshop : calques de RÉGLAGE non destructifs — composition (effet sur ce qui est dessous, opacité, masque, alpha
intact, cachés), enregistrement, fenêtre (création, modification, annulation), l'image dessous n'est jamais modifiée."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest

import numpy as np

from _photoshop_case import PsCase, settle
from fm_photoshop import compose as C, container, dialogs, model as M, ops


def base_doc():
    doc = M.new_document(8, 8, background=None)
    doc.layers[0].pix.set_all(0, 0, np.full((8, 8, 4), (100, 150, 200, 255), np.uint8))
    return doc


class ComposeTest(unittest.TestCase):
    def test_invert_adjustment_affects_only_what_is_below(self):
        doc = base_doc()
        layer, cmd = ops.add_adjustment(doc, "invert")
        above = M.Layer("dessus")
        above.pix.set_all(0, 0, np.full((2, 2, 4), (10, 10, 10, 255), np.uint8))
        doc.layers.append(above)
        flat = C.flatten_u8(doc)
        self.assertEqual(tuple(flat[5, 5]), (155, 105, 55, 255))                       # dessous inversé
        self.assertEqual(tuple(flat[0, 0]), (10, 10, 10, 255))                         # au-dessus : intact
        self.assertEqual(tuple(doc.layers[0].pix.data[0, 0]), (100, 150, 200, 255))    # le calque dessous n'est PAS modifié
        layer.opacity = 0.5
        self.assertEqual(tuple(C.flatten_u8(doc)[5, 5][:3]), (128, 128, 128))          # 50 % : mélange
        layer.visible = False
        self.assertEqual(tuple(C.flatten_u8(doc)[5, 5]), (100, 150, 200, 255))
        cmd.undo()
        self.assertEqual(len(doc.layers), 2)

    def test_mask_and_transparent_pixels(self):
        doc = M.new_document(4, 1, background=None)
        doc.layers[0].pix.set_all(0, 0, np.array([[[100, 100, 100, 255], [100, 100, 100, 255], [100, 100, 100, 128],
                                                   [0, 0, 0, 0]]], np.uint8))
        layer, _c = ops.add_adjustment(doc, "invert")
        layer.mask = M.Mask()
        layer.mask.plane.set_all(0, 0, np.array([[[255], [0], [255], [255]]], np.uint8))
        flat = C.flatten_u8(doc)
        self.assertEqual(tuple(flat[0, 0]), (155, 155, 155, 255))
        self.assertEqual(tuple(flat[0, 1]), (100, 100, 100, 255))                      # masqué : pas d'effet
        self.assertEqual(int(flat[0, 2, 3]), 128)                                      # alpha jamais modifié
        self.assertEqual(int(flat[0, 3, 3]), 0)

    def test_brightness_params_and_unknown_effect_and_refusals(self):
        doc = base_doc()
        layer, _c = ops.add_adjustment(doc, "brightness_contrast", {"brightness": 0.2, "contrast": "x"})
        self.assertEqual(layer.adjustment["params"]["contrast"], 0.0)                  # valeur invalide : défaut
        self.assertGreater(int(C.flatten_u8(doc)[0, 0, 0]), 100)
        with self.assertRaises(ValueError):
            ops.add_adjustment(doc, "gaussian_blur")                                   # un filtre voisinage n'est pas un réglage
        layer.adjustment = {"effect": "inconnu", "params": {}}
        self.assertEqual(tuple(C.flatten_u8(doc)[0, 0]), (100, 150, 200, 255))         # effet inconnu : sans effet
        twin, _c2 = ops.duplicate_layer(doc, layer)
        self.assertEqual(twin.adjustment, layer.adjustment)
        self.assertIsNot(twin.adjustment, layer.adjustment)

    def test_container_roundtrip(self):
        doc = base_doc()
        layer, _c = ops.add_adjustment(doc, "hue_saturation", {"hue": 90})
        back = container.loads(container.dumps(doc))
        self.assertTrue(back.layers[1].is_adjustment() and back.layers[1].pix is None)
        self.assertEqual(back.layers[1].adjustment["params"]["hue"], 90.0)
        self.assertTrue(np.array_equal(C.flatten_u8(back), C.flatten_u8(doc)))


class DialogTest(PsCase):
    def test_create_edit_cancel_through_the_menu_and_dialogs(self):
        _item, std = self.editor(40, 30)
        s = std.session
        s.layer().pix.write((0, 0, 40, 30), np.full((30, 40, 4), (100, 100, 100, 255), np.uint8))
        base = s.layer().pix.data.copy()
        # création : valeurs choisies puis validation
        layer, cmd = std.canvas.actions.add_adjustment("brightness_contrast")
        dialog = dialogs.AdjustmentLayerDialog(s, std.canvas.actions, layer, cmd, std)
        settle(0.1)
        dialog.fields["brightness"][0].setValue(40)
        dialog.accept()
        self.assertEqual(len(s.doc.layers), 2)
        self.assertEqual(layer.adjustment["params"]["brightness"], 0.4)
        self.assertEqual(s.layer(), layer)
        self.assertGreater(int(C.flatten_u8(s.doc)[0, 0, 0]), 100)
        self.assertTrue(np.array_equal(s.doc.layers[0].pix.data, base))
        # modification annulable
        dialog = dialogs.AdjustmentLayerDialog(s, std.canvas.actions, layer, None, std)
        settle(0.1)
        self.assertEqual(dialog.fields["brightness"][0].value(), 40)                  # valeurs courantes reprises
        dialog.fields["brightness"][0].setValue(-30)
        dialog.accept()
        self.assertEqual(layer.adjustment["params"]["brightness"], -0.3)
        s.undo()
        self.assertEqual(layer.adjustment["params"]["brightness"], 0.4)
        s.undo()
        self.assertEqual(len(s.doc.layers), 1)
        s.redo(); s.redo()
        # annulation de la fenêtre : retour exact, pas d'étape
        n = len(s.history.done)
        dialog = dialogs.AdjustmentLayerDialog(s, std.canvas.actions, layer, None, std)
        settle(0.1)
        dialog.fields["brightness"][0].setValue(90)
        dialog.settle()
        self.assertEqual(layer.adjustment["params"]["brightness"], 0.9)
        dialog.reject()
        self.assertEqual(layer.adjustment["params"]["brightness"], -0.3)               # (état après rétablir)
        self.assertEqual(len(s.history.done), n)
        # création annulée : le calque disparaît
        layer2, cmd2 = std.canvas.actions.add_adjustment("invert")
        dialog = dialogs.AdjustmentLayerDialog(s, std.canvas.actions, layer2, cmd2, std)
        settle(0.1)
        dialog.reject()
        self.assertEqual(len(s.doc.layers), 2)
        # menus : entrées « Nouveau calque de réglage » et pixels refusés sur un calque de réglage
        texts = [a.text() for a in std.menubar.menu_for("adjust").actions()]
        self.assertTrue(any(t.startswith("Nouveau calque de réglage : Niveaux") for t in texts))
        s.select_layer(layer)
        a = std.canvas.actions
        self.assertEqual(a.fill_foreground(), "Calque verrouillé, groupe ou réglage : rien à remplir.")
        self.assertIsNone(std.canvas.start_free_transform())
        for d in list(std.findChildren(dialogs.AdjustmentLayerDialog)):        # (fenêtres détruites avant la fin du test)
            d.setParent(None)
            d.deleteLater()
        settle(0.05)


if __name__ == "__main__":
    unittest.main()
