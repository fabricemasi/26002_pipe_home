"""Gabarits de lignes (fm_theme.cells, ROW_TEMPLATES_KEY) : toutes les lignes d'un meme type (Bordures, Border
radius...) ont le meme aspect ; modifier l'une recopie largeurs / justifications / hauteur sur les autres, y compris
celles d'un tableau affiche plus tard."""
import _isolate  # noqa: F401
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

import settings_window_v2 as v2  # noqa: E402
from fm_theme import cells  # noqa: E402
from fm_theme.widgets import _TABLE_DIMS  # noqa: E402


def field(kind: str, parts: int = 5):
    split = cells.SplitCell([(f"p{i}", [QLabel("x")]) for i in range(parts)])
    holder = cells.wrap_split(split)
    holder._row_kind = kind
    return holder


def table(*kinds):
    rows = [(f"ligne {i}", field(kind, parts), None) for i, (kind, parts) in enumerate(kinds)]
    frame = v2._flat_cells_table(rows)
    frame.show()
    return frame, [cells.split_of(f) for _l, f, _t in rows]


def settle(ms: int = 40):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QCoreApplication.processEvents()


class RowTemplatesTest(unittest.TestCase):
    def setUp(self):
        _TABLE_DIMS.clear()
        self.frames = []

    def tearDown(self):
        for frame in self.frames:
            frame.close()
            frame.deleteLater()
        settle(5)
        _TABLE_DIMS.clear()

    def make(self, *kinds):
        frame, splits = table(*kinds)
        self.frames.append(frame)
        return frame, splits

    def test_widths_follow_on_every_row_of_the_same_kind(self):
        _f1, (a, other) = self.make(("sides", 5), ("corners", 5))
        _f2, (b,) = self.make(("sides", 5))
        settle()
        a.setWidths([0, 50, 60, 0, 0])
        a.changed.emit()
        settle()
        self.assertEqual(b.widths(), [0, 50, 60, 0, 0])
        self.assertEqual(other.widths(), [0] * 5)          # autre type : intact

    def test_bordures_with_thickness_share_the_template(self):
        _f1, (a,) = self.make(("sides", 5))
        _f2, (b,) = self.make(("sides_thick", 6))
        settle()
        b.setWidths([0, 0, 70, 0, 0, 90])
        b.changed.emit()
        settle()
        self.assertEqual(a.widths(), [0, 0, 70, 0, 0])
        a.setWidths([40, 0, 70, 0, 0])
        a.changed.emit()
        settle()
        self.assertEqual(b.widths(), [40, 0, 70, 0, 0, 90])  # l'epaisseur garde sa largeur

    def test_alignment_and_height_follow(self):
        f1, (a,) = self.make(("corners", 5))
        f2, (b,) = self.make(("corners", 5))
        settle()
        a.setSubAlign(2, "left", "top")
        settle()
        self.assertEqual(b.aligns()[2], ("left", "top"))
        state1, state2 = f1._extra_dims, f2._extra_dims
        state1.heights.set_height(0, state1.heights.natural(0) + 30)
        settle()
        self.assertEqual(state2.heights.user[0], state1.heights.user[0])

    def test_table_shown_later_takes_the_template(self):
        _f1, (a,) = self.make(("padding", 5))
        settle()
        a.setWidths([30, 0, 0, 0, 80])
        a.changed.emit()
        settle()
        _f2, (b,) = self.make(("padding", 5))
        settle()
        self.assertEqual(b.widths(), [30, 0, 0, 0, 80])
        self.assertIn("padding", _TABLE_DIMS[cells.ROW_TEMPLATES_KEY])

    def test_template_wins_over_the_table_own_dims(self):
        f1, (a,) = self.make(("corners", 5))
        settle()
        dims = f1.collectDims()                             # largeurs propres au tableau : naturelles
        a.setWidths([0, 0, 0, 55, 0])
        a.changed.emit()
        settle()
        f1.applyDims(dims)
        self.assertEqual(a.widths(), [0, 0, 0, 55, 0])

    def test_table_off_screen_follows_when_the_gesture_pauses(self):
        _f1, (a,) = self.make(("sides", 5))
        holder = QWidget()
        holder.resize(300, 200)
        frame, (b,) = table(("sides", 5))
        frame.setParent(holder)
        frame.move(0, 5000)                                 # hors de la zone visible de son parent
        holder.show()
        self.frames += [holder]
        settle()
        self.assertTrue(frame.visibleRegion().isEmpty())
        a.setWidths([0, 45, 0, 0, 0])
        a.changed.emit()
        settle(60)
        self.assertEqual(b.widths(), [0] * 5)               # pendant le geste : seulement les tableaux a l'ecran
        settle(300)
        self.assertEqual(b.widths(), [0, 45, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
