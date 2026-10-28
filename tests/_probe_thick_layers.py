"""Sonde : cout de la peinture des traits EPAIS par couches (cad_items.ThickPaths) contre une seule couche.
python tests/_probe_thick_layers.py [nombre de lignes]"""
import _isolate  # noqa: F401
import sys
import time
import unittest

from fm_cad import cad_items, cad_model
from fm_board import model
import test_cad as T

COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 3000


class Probe(T.CadBoardCase):
    def test_cost(self):
        scene = self.pane.scene
        cad = self.ctl.cad_page()
        x = y = 0.0
        for n in range(COUNT):                                  # polylignes de 40 segments, bouts ronds, epaisseur 6
            if n % 40 == 0:
                x, y = (n // 40 % 10) * 130.0, (n // 400) * 120.0
            nx, ny = x + 3.0 + (n % 3), y + (2.5 if n % 2 else -2.0)
            values = cad_model.new_line_values(cad, (x, y), (nx, ny))
            values.update(lineweight=6.0, color="#ffffff", end1={"style": "round"}, end2={"style": "round"})
            scene._add(model.new_item("cad_line", **values))
            x, y = nx, ny
        self.ctl.touch_index()
        self.pane.view.fit_all()
        T.settle(0.3)
        self.ctl.overlay.hide()
        vp = self.pane.view.viewport()

        def paint_ms():
            for batch in scene.cad_layer.batches:
                batch._ops = None
            vp.repaint()
            start = time.perf_counter()
            for _ in range(8):
                vp.repaint()
            return (time.perf_counter() - start) / 8 * 1000
        layers = [len(op[2].layers) for b in scene.cad_layer.batches for op in (b._ops or []) if op[2] is not None
                  and not op[0][0]]
        many = paint_ms()
        layers = [len(op[2].layers) for b in scene.cad_layer.batches for op in (b._ops or []) if op[2] is not None
                  and not op[0][0]]
        old = cad_items.ThickPaths.MAX_LAYERS
        cad_items.ThickPaths.MAX_LAYERS = 1
        try:
            one = paint_ms()
        finally:
            cad_items.ThickPaths.MAX_LAYERS = old
        start = time.perf_counter()
        for batch in scene.cad_layer.batches:
            for op in batch._ops or []:
                op[2] = None
                batch._op_cache(op)
        build = (time.perf_counter() - start) * 1000
        cad_items.ThickPaths.MAX_LAYERS = 1
        start = time.perf_counter()
        for batch in scene.cad_layer.batches:
            for op in batch._ops or []:
                op[2] = None
                batch._op_cache(op)
        build_one = (time.perf_counter() - start) * 1000
        scene.cad_linear_blend = False
        plain = paint_ms()
        scene.cad_linear_blend = True
        cad_items.ThickPaths.MAX_LAYERS = old
        print(f"\nlistes a une couche {build_one:.1f} ms ; peinture sans melange lineaire {plain:.1f} ms")
        print(f"\n{COUNT} traits epais : couches {layers} ; peinture {many:.1f} ms (couches) / {one:.1f} ms (une) ; "
              f"listes refaites {build:.1f} ms")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
