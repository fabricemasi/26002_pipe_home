"""MASQUES et IMAGES du module CAD (fm_cad/cad_image.py, hachures « wipeout », fm_cad/cad_commands_images.py ;
2026-11-05) : import WIPEOUT / IMAGE d'un DXF, entites sur le board (transformations, choix), commandes, export."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import tempfile
import unittest
from pathlib import Path

from PySide6.QtGui import QColor, QImage

from fm_cad import cad_hatch, cad_image, cad_shapes
from test_cad import CadBoardCase


def rnd(p):
    return tuple(round(v, 6) + 0.0 for v in p)


def make_png(folder: Path, name="photo.png", w=40, h=20) -> Path:
    image = QImage(w, h, QImage.Format_ARGB32)
    image.fill(QColor("#ff0000"))
    path = folder / name
    image.save(str(path))
    return path


class PureImageTest(unittest.TestCase):
    def test_corners_transform_inside(self):
        data = cad_image.placed("x.png", (10, 0), 40, 20, 90)
        self.assertEqual([rnd(c) for c in cad_image.corners(data)], [(10, 0), (10, 40), (-10, 40), (-10, 0)])
        self.assertTrue(cad_image.inside(data, (0, 20)))
        self.assertFalse(cad_image.inside(data, (20, 20)))
        moved = cad_shapes.mirrored("cad_image", data, (0, 0), (0, 1))         # symetrie : les coins suivent
        self.assertEqual(rnd(moved["pu"]), (-10, 40))
        self.assertEqual(len(cad_shapes.prims("cad_image", data)), 4)
        self.assertEqual(cad_hatch.style_of({"hatch_pattern": "wipeout"})["pattern"], cad_hatch.WIPEOUT)
        self.assertEqual(cad_hatch.prims({"hatch_pattern": "wipeout", "loops": [[[0, 0], [1, 0], [1, 1]]]})[0][1],
                         (0, 0))                                               # aucun trait de motif


class ImportTest(unittest.TestCase):
    def test_wipeout_and_image_are_imported(self):
        import fm_board  # noqa: F401
        from fm_cad import cad_import
        ezdxf = __import__("ezdxf")
        folder = Path(tempfile.mkdtemp())
        png = make_png(folder)
        doc = ezdxf.new("R2018")
        doc.header["$INSUNITS"] = 0                                         # unites du board telles quelles
        msp = doc.modelspace()
        msp.add_wipeout([(0, 0), (10, 0), (10, 5)])
        image_def = doc.add_image_def("photo.png", (40, 20))                   # chemin RELATIF au dessin
        msp.add_image(image_def, (100, 0), (80, 40), rotation=0)
        path = folder / "plan.dxf"
        doc.saveas(path)
        data, report = cad_import.read_drawing(path, native_blocks=False)
        self.assertEqual(report["ignored"], {})
        (mask,) = [i for i in data["items"] if i["type"] == "cad_hatch"]
        self.assertEqual(mask["hatch_pattern"], cad_hatch.WIPEOUT)
        (img,) = [i for i in data["items"] if i["type"] == "cad_image"]
        self.assertEqual(Path(img["path"]), png.resolve())
        self.assertEqual([rnd(c) for c in cad_image.corners(img)][:2], [(100, 0), (180, 0)])


class OnTheBoardTest(CadBoardCase):
    def kinds(self, kind):
        return [i for i in self.ctl.cad_items() if i.kind == kind]

    def test_imageattach_move_pick_export(self):
        png = make_png(self.dir)
        self.type("IMAGEATTACH", str(png), "0,0", "", "")
        (img,) = self.kinds("cad_image")
        self.assertEqual(rnd(cad_image.corners(img.data)[2]), (40.0 * self.ctl.unit() / self.ctl.unit(), 20.0))
        self.assertIsNotNone(img._fill._image)                                # fichier lu, peint sous les traits
        self.ctl.undo()
        self.assertEqual(self.kinds("cad_image"), [])
        self.ctl.redo()
        (img,) = self.kinds("cad_image")
        self.pane.scene.clearSelection()
        img.setSelected(True)
        self.type("M", "0,0", "100,0")
        self.assertEqual(rnd(img.points()[0]), (100.0, 0.0))
        from fm_cad import cad_export
        ezdxf = __import__("ezdxf")
        target = self.dir / "image.dxf"
        cad_export.export_dxf(self.pane.scene, target, "px" if "px" in cad_export.UNITS else "mm")
        doc = ezdxf.readfile(target)
        (entity,) = doc.modelspace().query("IMAGE")
        self.assertEqual(tuple(entity.dxf.image_size)[:2], (40, 20))

    def test_wipeout_command_hides_lines_and_exports(self):
        self.line((0, 5), (20, 5))
        self.type("WIPEOUT", "0,0", "10,0", "10,10", "0,10", "")
        (mask,) = self.kinds("cad_hatch")
        self.assertEqual(cad_hatch.style_of(mask.data)["pattern"], cad_hatch.WIPEOUT)
        self.assertTrue(mask._text_item._solid)                                 # peint au-dessus des traits
        self.assertFalse(mask._fill._solid)
        from fm_cad import cad_export
        ezdxf = __import__("ezdxf")
        target = self.dir / "masque.dxf"
        cad_export.export_dxf(self.pane.scene, target, "px" if "px" in cad_export.UNITS else "mm")
        self.assertEqual(len(ezdxf.readfile(target).modelspace().query("WIPEOUT")), 1)

    def test_gradient_hatch_is_painted_and_exported(self):
        item = self.ctl.create_entity("cad_hatch", {"loops": [[[0, 0], [50, 0], [50, 30]]], "hatch_pattern": "gradient",
                                                    "hatch_color2": "#00ff00", "hatch_gradient": "SPHERICAL",
                                                    "hatch_alpha": 100.0, "color": "#ff0000"})
        self.ctl.commit_created([item], "degrade")
        self.assertTrue(item._fill._solid)
        self.assertEqual(item._fill._gradient["gradient"], "SPHERICAL")
        image = QImage(200, 200, QImage.Format_ARGB32)
        image.fill(0)
        from PySide6.QtGui import QPainter
        painter = QPainter(image)
        painter.translate(10, 150)
        item._fill.paint(painter, None)
        painter.end()
        self.assertNotEqual(image.pixelColor(45, 140).alpha(), 0)                # peint (degrade)
        from fm_cad import cad_export
        ezdxf = __import__("ezdxf")
        target = self.dir / "degrade.dxf"
        cad_export.export_dxf(self.pane.scene, target, "px" if "px" in cad_export.UNITS else "mm")
        (hatch,) = ezdxf.readfile(target).modelspace().query("HATCH")
        self.assertEqual(hatch.gradient.name, "SPHERICAL")
        self.assertEqual(tuple(hatch.gradient.color2), (0, 255, 0))


if __name__ == "__main__":
    unittest.main()
