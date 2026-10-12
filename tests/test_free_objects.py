"""Objets libres des tableaux a cellules (demande de l'utilisateur) : Ctrl+Maj + glisser un objet d'une
ligne = le deplacer librement dans sa cellule ; Ctrl+Maj+X + glisser un de ses bords = le redimensionner,
aimante aux extremites des objets de la ligne sous le curseur ; retenu avec les dimensions du tableau."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QWidget

app = QApplication.instance() or QApplication([])

import settings_cells as sc
from settings_widgets import _SliderField

CTRL_SHIFT = Qt.ControlModifier | Qt.ShiftModifier


def settle():
    for _ in range(4):
        app.processEvents()


def pair():
    """Deux boutons cote a cote dans un champ compose (comme la ligne Note des filtres)."""
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(30)
    holder.a, holder.b = QPushButton("A"), QPushButton("B")
    for button in (holder.a, holder.b):
        button.setFixedSize(60, 22)
        layout.addWidget(button)
    return holder


class FreeObjectsTest(unittest.TestCase):
    def setUp(self):
        # Touche X : jamais lue sur le vrai clavier pendant les tests (l'utilisateur tape peut-etre).
        p = mock.patch.object(sc, "resize_key_held", return_value=False)
        p.start()
        self.addCleanup(p.stop)
    def build(self):
        self.slider = _SliderField(0, 100, 10, "px", slider_width=120, box_width=50)
        self.pair = pair()
        self.lone = QPushButton("seul")
        self.lone.setFixedSize(50, 22)
        split = sc.SplitCell([("Un", [self.lone])])
        holder = sc.wrap_split(split)
        frame, head, cells = sc.build_cells_table(
            [("Paramètre", 140), ("Valeur", 420)],
            [[QLabel("Curseur"), self.slider], [QLabel("Paire"), self.pair], [QLabel("Divisée"), holder]])
        self.split = split
        self.frame, self.cells = frame, cells
        self.state = frame._extra_dims
        frame.resize(frame.sizeHint())
        frame.show()
        self.addCleanup(frame.deleteLater)
        settle()
        return frame

    def drag(self, widget, start: QPoint, delta: QPoint, mods=CTRL_SHIFT, resize=False):
        # Mouvements envoyes au cadre (immobile) : QTest place ses points par rapport au widget, qui bouge.
        # resize : touche X tenue (Ctrl+Maj+X + glisser = redimensionner), simulee.
        origin = self.frame.mapFromGlobal(widget.mapToGlobal(start))
        with mock.patch.object(sc, "resize_key_held", return_value=resize):
            QTest.mousePress(widget, Qt.LeftButton, mods, start)
        QTest.mouseMove(self.frame, origin + QPoint(delta.x() // 2, delta.y() // 2))
        QTest.mouseMove(self.frame, origin + delta)
        QTest.mouseRelease(self.frame, Qt.LeftButton, mods, origin + delta)
        settle()

    def test_ctrl_shift_drag_moves_one_object_inside_its_cell(self):
        nosnap = mock.patch.object(sc, "OBJECT_SNAP", 0)     # deplacement LIBRE teste ici (aimantation : a part)
        nosnap.start()
        self.addCleanup(nosnap.stop)
        self.build()
        rail = self.slider.slider
        cell = self.cells[0][1]
        before = rail.mapTo(cell, QPoint(0, 0))
        box_before = self.slider.box.mapTo(cell, QPoint(0, 0))
        self.drag(rail, QPoint(10, 5), QPoint(40, 0))
        after = rail.mapTo(cell, QPoint(0, 0))
        self.assertEqual(after - before, QPoint(40, 0))
        self.assertEqual(self.slider.box.mapTo(cell, QPoint(0, 0)), box_before)   # le reste ne bouge pas
        self.assertIsNone(rail.graphicsEffect())                                   # fantome retire
        key = next(iter(self.state.objects))
        self.assertTrue(key.startswith("r0c1|"))
        self.assertEqual(self.state.collect()["objects"][key][:2], [40, 0])
        # Jamais hors de sa cellule.
        self.drag(rail, QPoint(10, 5), QPoint(5000, 5000))
        geo = rail.geometry()
        self.assertLessEqual(geo.right(), cell.width() - 1)
        self.assertLessEqual(geo.bottom(), cell.height() - 1)

    def test_plain_drag_and_ctrl_drag_are_untouched(self):
        self.build()
        rail = self.slider.slider
        # Ctrl+Maj+Alt ne redimensionne plus (remplace par Ctrl+Maj+X) : c'est un deplacement.
        width = rail.width()
        self.drag(rail, QPoint(rail.width() - 1, 5), QPoint(-20, 0), mods=CTRL_SHIFT | Qt.AltModifier)
        self.assertEqual(rail.width(), width)
        self.state.set_object(next(iter(self.state.objects)), None)
        self.drag(rail, QPoint(10, 5), QPoint(40, 0), mods=Qt.NoModifier)
        self.drag(rail, QPoint(10, 5), QPoint(40, 0), mods=Qt.ControlModifier)
        self.assertEqual(self.state.objects, {})
        self.assertIsNone(getattr(rail, "_float_slot", None))

    def test_ctrl_shift_alt_drag_resizes_and_snaps_to_the_row_objects(self):
        self.build()
        a, b = self.pair.a, self.pair.b
        cell = self.cells[1][1]
        gap = b.mapTo(cell, QPoint(0, 0)).x() - (a.mapTo(cell, QPoint(0, 0)).x() + a.width())
        self.assertEqual(gap, 30)
        # Bord droit de A tire vers le bord gauche de B, a 4 px pres : il s'y aimante.
        self.drag(a, QPoint(a.width() - 1, 10), QPoint(gap - 4, 0), resize=True)
        right_a = a.mapToGlobal(QPoint(a.width(), 0)).x()
        self.assertEqual(right_a, b.mapToGlobal(QPoint(0, 0)).x())
        self.assertEqual(a.width(), 90)
        # Loin de tout repere : taille libre.
        self.drag(a, QPoint(a.width() - 1, 10), QPoint(-15, 0), resize=True)
        self.assertEqual(a.width(), 75)
        # Bord gauche : la droite reste en place.
        right = a.mapTo(cell, QPoint(a.width(), 0)).x()
        self.drag(a, QPoint(0, 10), QPoint(12, 0), resize=True)
        self.assertEqual(a.mapTo(cell, QPoint(a.width(), 0)).x(), right)
        self.assertEqual(a.width(), 63)

    def test_ctrl_z_undoes_moves_resizes_and_resets(self):
        self.build()
        b = self.pair.b
        cell = self.cells[1][1]
        home = b.mapTo(cell, QPoint(0, 0))
        self.drag(b, QPoint(10, 10), QPoint(-20, 0))
        moved = b.mapTo(cell, QPoint(0, 0))
        self.drag(b, QPoint(b.width() - 1, 10), QPoint(-10, 0), resize=True)
        self.assertEqual(b.width(), 50)
        window = self.frame.window()
        self.assertTrue(sc.undo_object_change(window))          # le redimensionnement
        self.assertEqual(b.width(), 60)
        self.assertEqual(b.mapTo(cell, QPoint(0, 0)), moved)
        self.assertTrue(sc.undo_object_change(window))          # le deplacement : retour a sa place
        self.assertIsNone(getattr(b, "_float_slot", None))
        self.assertEqual(b.mapTo(cell, QPoint(0, 0)), home)
        self.drag(b, QPoint(10, 10), QPoint(-20, 0))
        cell._reset_objects()                                    # « Remettre les objets a leur place »
        self.assertTrue(sc.undo_object_change(window))
        self.assertEqual(b.mapTo(cell, QPoint(0, 0)), moved)
        # Ctrl+Z de la fenetre : un raccourci pose sur elle au premier geste.
        self.assertIsNotNone(getattr(window, "_object_undo_shortcut", None))

    def test_q_and_z_constrain_the_move(self):
        nosnap = mock.patch.object(sc, "OBJECT_SNAP", 0)     # deplacement LIBRE teste ici (aimantation : a part)
        nosnap.start()
        self.addCleanup(nosnap.stop)
        self.build()
        rail = self.slider.slider
        cell = self.cells[0][1]
        for key, expected in ((Qt.Key_Q, lambda d: QPoint(0, d.y())), (Qt.Key_Z, lambda d: QPoint(d.x(), 0))):
            before = rail.mapTo(cell, QPoint(0, 0))
            origin = self.frame.mapFromGlobal(rail.mapToGlobal(QPoint(10, 5)))
            delta = QPoint(30, 4)
            QTest.mousePress(rail, Qt.LeftButton, CTRL_SHIFT, QPoint(10, 5))
            QTest.mouseMove(self.frame, origin + QPoint(5, 1))
            QTest.keyPress(self.frame, key, CTRL_SHIFT)              # touche tenue pendant le geste
            QTest.mouseMove(self.frame, origin + delta)
            QTest.mouseRelease(self.frame, Qt.LeftButton, CTRL_SHIFT, origin + delta)
            QTest.keyRelease(self.frame, key, CTRL_SHIFT)
            settle()
            moved = rail.mapTo(cell, QPoint(0, 0)) - before
            want = expected(delta)
            self.assertEqual(moved.x(), want.x(), key)
            self.assertEqual(moved.y(), min(want.y(), moved.y()) if want.y() else 0, key)

    def test_a_moved_object_that_grows_keeps_its_whole_size(self):
        # Ex. toggle deplace puis change de style (plus grand) : il etait peint dans son ancienne taille,
        # coupe (signale). Sa nouvelle taille devient sa taille d'origine ; sa place suit.
        self.build()
        b = self.pair.b
        self.drag(b, QPoint(10, 10), QPoint(-20, 0))
        self.assertIsNotNone(b._float_slot)
        b.setFixedSize(84, 20)
        settle()
        self.assertEqual((b.width(), b.height()), (84, 20))
        self.assertEqual(b._float_slot.size(), b.size())

    def test_moves_snap_to_the_objects_of_the_row(self):
        # Deplacement AIMANTE (demande de l'utilisateur) : B tire a 4 px du bord droit de A s'y colle.
        self.build()
        a, b = self.pair.a, self.pair.b
        a_right = a.mapToGlobal(QPoint(a.width(), 0)).x()
        gap = b.mapToGlobal(QPoint(0, 0)).x() - a_right
        self.drag(b, QPoint(10, 10), QPoint(-(gap - 4), 0))
        self.assertEqual(b.mapToGlobal(QPoint(0, 0)).x(), a_right)
        # Q tenue (vertical seul) : pas d'aimantation horizontale.
        before = b.mapToGlobal(QPoint(0, 0)).x()
        origin = self.frame.mapFromGlobal(b.mapToGlobal(QPoint(10, 10)))
        QTest.mousePress(b, Qt.LeftButton, CTRL_SHIFT, QPoint(10, 10))
        QTest.mouseMove(self.frame, origin + QPoint(0, 2))
        QTest.keyPress(self.frame, Qt.Key_Q, CTRL_SHIFT)
        QTest.mouseMove(self.frame, origin + QPoint(-6, 0))
        QTest.mouseRelease(self.frame, Qt.LeftButton, CTRL_SHIFT, origin + QPoint(-6, 0))
        QTest.keyRelease(self.frame, Qt.Key_Q, CTRL_SHIFT)
        settle()
        self.assertEqual(b.mapToGlobal(QPoint(0, 0)).x(), before)

    def test_saved_with_the_table_and_reset(self):
        self.build()
        self.drag(self.pair.b, QPoint(10, 10), QPoint(-20, 3))
        self.drag(self.lone, QPoint(10, 10), QPoint(25, 0))
        dims = self.state.collect()
        self.assertEqual(len(dims["objects"]), 2)
        self.assertTrue(any("|0/0/s0/0" in k or "s0" in k for k in dims["objects"]))
        # Un tableau identique reprend les memes places.
        first_b = self.pair.b.mapTo(self.cells[1][1], QPoint(0, 0))
        first_lone = self.lone.mapTo(self.cells[2][1], QPoint(0, 0))
        self.build()
        self.state.apply(dims)
        settle()
        self.assertEqual(self.pair.b.mapTo(self.cells[1][1], QPoint(0, 0)), first_b)
        self.assertEqual(self.lone.mapTo(self.cells[2][1], QPoint(0, 0)), first_lone)
        # La cellule divisee remet ses widgets en page (justification) : l'objet garde sa place.
        self.split.setSubAlign(0, "left", "top")
        settle()
        self.assertIsNotNone(self.lone._float_slot)
        self.assertIs(self.lone.parentWidget(), self.cells[2][1])
        # « Remettre les objets a leur place » (clic droit sur la cellule).
        self.cells[1][1]._reset_objects()
        settle()
        self.assertIsNone(getattr(self.pair.b, "_float_slot", None))
        self.assertIs(self.pair.b.parentWidget(), self.pair)
        self.assertEqual(len(self.state.collect()["objects"]), 1)


if __name__ == "__main__":
    unittest.main()
