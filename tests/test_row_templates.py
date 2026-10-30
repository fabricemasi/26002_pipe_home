"""Gabarits de lignes (fm_theme.cells, ROW_TEMPLATES_KEY) : toutes les lignes d'un meme type (Bordures, Border
radius...) ont le meme aspect ; modifier l'une recopie largeurs / justifications / hauteur sur les autres, y compris
celles d'un tableau affiche plus tard."""
import _isolate  # noqa: F401
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
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


class _Tables(unittest.TestCase):
    """Tableaux faits avec les briques des reglages, detruits a la fin du test."""

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


class RowTemplatesTest(_Tables):
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


def send_mouse(widget, kind, pos, buttons=Qt.LeftButton):
    event = QMouseEvent(kind, QPointF(pos), QPointF(widget.mapToGlobal(pos)),
                        Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton, buttons, Qt.NoModifier)
    QApplication.sendEvent(widget, event)


class ContentRowsTest(_Tables):
    """Lignes sans cellule divisee : meme gabarit quand elles ont le meme type de contenu (meme champ)."""

    def simple_table(self, *fields):
        rows = [(f"ligne {i}", f, None) for i, f in enumerate(fields)]
        frame = v2._flat_cells_table(rows)
        frame.show()
        self.frames.append(frame)
        return frame

    @staticmethod
    def slider(kind="slider"):
        from fm_theme.widgets import _SliderField
        field = _SliderField(0, 100, 10)
        field._row_kind = kind
        return field

    @staticmethod
    def toggle():
        from fm_theme.widgets import _Toggle
        field = _Toggle(False, show_label=False)
        field._row_kind = "bool"
        return field

    def test_rows_with_the_same_field_share_alignment_and_height(self):
        f1 = self.simple_table(self.slider(), self.toggle())
        f2 = self.simple_table(self.slider("ratio"))           # autre cle, meme champ : un curseur
        settle()
        s1, s2 = f1._extra_dims, f2._extra_dims
        self.assertEqual(s1.row_kinds[0], s2.row_kinds[0])
        s1.cells["r0c1"].setAlign("center", "top")
        settle()
        self.assertEqual(s2.cells["r0c1"].align(), ("center", "top"))
        self.assertEqual(s1.cells["r1c1"].align()[1], "center")   # le toggle : autre contenu, intact
        s1.heights.set_height(0, s1.heights.natural(0) + 20)
        settle()
        self.assertEqual(s2.heights.user[0], s1.heights.user[0])
        self.assertEqual(s1.heights.user[1], 0)

    def test_another_row_drag_does_not_reset_a_template_height(self):
        """Bug signale : les hauteurs changeaient toutes seules. Une ligne dont le contenu est plus haut que le
        gabarit gardait la hauteur du gabarit (sous son contenu) ; tirer une AUTRE ligne de son tableau la
        remettait a 0, ce qui passait pour une modification et remettait a 0 le gabarit de tout son type."""
        f1 = self.simple_table(self.slider())
        tall = self.slider()
        tall.setMinimumHeight(90)                              # contenu plus haut que le gabarit
        f2 = self.simple_table(tall, self.toggle())
        settle()
        s1, s2 = f1._extra_dims, f2._extra_dims
        s1.heights.set_height(0, s1.heights.natural(0) + 15)
        settle()
        wanted = s1.heights.user[0]
        s2.heights.set_height(1, s2.heights.natural(1) + 10)   # on tire la ligne du toggle
        settle()
        self.assertEqual(s1.heights.user[0], wanted)
        self.assertEqual(s2.heights.user[0], wanted)

    def test_generic_holder_has_no_template(self):
        holder = QWidget()
        holder._row_kind = "font_role"
        frame = self.simple_table(holder)
        self.assertEqual(frame._extra_dims.row_kinds, {})


class OpeningWindowTest(_Tables):
    def test_opening_a_settings_window_keeps_the_session_templates(self):
        """Bug signale : la fenetre de reglages qui s'ouvre relisait `table_dims` du fichier et effacait les
        gabarits poses dans la session (fm_theme puis Parametres generaux de fm_browser)."""
        _TABLE_DIMS[cells.ROW_TEMPLATES_KEY] = {"contenu:_SliderField": {"align": ["left,center"], "height": 61}}
        win = v2.SettingsWindowV2(module="theme")
        self.frames.append(win)
        self.assertEqual(_TABLE_DIMS[cells.ROW_TEMPLATES_KEY]["contenu:_SliderField"]["height"], 61)

class ThemePresetTest(_Tables):
    """Gabarits ranges dans le preset fm_theme (valeur generale `row_templates`, choix de l'utilisateur)."""

    def test_preset_round_trip(self):
        import fm_theme.presets as tp
        name = tp.unique_name("Gabarits")
        tp.save_preset(tp.from_settings({"ui_scale": 1.0}, name))
        rows = {"sides": {"align": ["left,center"], "height": 70}}
        self.assertTrue(tp.save_row_templates(name, rows))
        self.assertFalse(tp.save_row_templates(name, rows))            # inchange : pas d'ecriture
        preset = tp.load_preset(tp.find_preset(name))
        self.assertEqual(preset["general"]["row_templates"], rows)
        self.assertEqual(tp.to_settings(preset)["row_templates"], rows)
        tp.delete_preset(name)

    def test_change_is_handed_to_the_listeners_after_the_gesture(self):
        got = []

        class Window:
            def save(self, templates):
                got.append(templates)
        window = Window()
        cells.add_row_template_listener(window.save)
        _f1, (a,) = self.make(("corners", 5))
        settle()
        a.setWidths([0, 33, 0, 0, 0])
        a.changed.emit()
        settle(100)
        self.assertEqual(got, [])                                      # pas pendant le geste
        settle(450)
        self.assertEqual(got[-1]["corners"]["split"], [0, 33, 0, 0, 0])

    def test_window_takes_the_templates_of_the_theme_preset(self):
        rows = {"contenu:_SliderField": {"align": ["left,center", "center,center"], "height": 0}}
        saved = []

        class Store(v2.AppSettingsStore):
            def load(self):
                settings = super().load()
                settings["row_templates"] = rows
                return settings

            def save_row_templates(self, templates):
                saved.append(templates)
        _TABLE_DIMS[cells.ROW_TEMPLATES_KEY] = {"sides": {"height": 99}}  # session : le preset l'emporte
        win = v2.SettingsWindowV2(module="theme", store=Store())
        self.frames.append(win)
        self.assertEqual(_TABLE_DIMS[cells.ROW_TEMPLATES_KEY], rows)
        self.assertEqual(saved, [])                                    # rien a recopier

    def test_templates_read_back_from_the_preset_reach_the_rows(self):
        _f1, (a,) = self.make(("padding", 5))
        settle()
        cells.reload_row_templates({"padding": {"split": [0, 0, 47, 0, 0]}})
        settle()
        self.assertEqual(a.widths(), [0, 0, 47, 0, 0])

class HeightBadgeTest(_Tables):
    def test_dragging_a_row_height_shows_its_height_in_pixels(self):
        frame, _splits = self.make(("corners", 5), ("padding", 5))
        settle()
        row = frame._extra_dims.heights.rows[0]
        pos = QPoint(30, row.height() - 1)                  # bord bas de la ligne
        send_mouse(row, QEvent.MouseButtonPress, pos)
        send_mouse(row, QEvent.MouseMove, pos + QPoint(0, 25))
        badge = row._width_badge_list[0]
        self.assertTrue(badge.isVisible())
        self.assertEqual(badge.text(), f"{row.minimumHeight()} px")
        self.assertGreaterEqual(badge.x(), 30 + 16)         # decale du curseur : il ne le masque pas
        send_mouse(row, QEvent.MouseButtonRelease, pos + QPoint(0, 25), Qt.NoButton)
        self.assertFalse(badge.isVisible())

    def test_height_is_copied_on_release_not_during_the_drag(self):
        """Bug signale (lignes de ~900 px) : recopiee pendant le glissement, la hauteur faisait grandir les lignes
        identiques AU-DESSUS, la ligne tiree s'eloignait du curseur et on tirait encore pour la rattraper."""
        other, _s = self.make(("bg_fill", 2))
        frame, _s = self.make(("bg_fill", 2))
        settle()
        before = other._extra_dims.heights.rows[0].height()
        row = frame._extra_dims.heights.rows[0]
        press = row.mapToGlobal(QPoint(30, row.height() - 1))        # curseur reel : position ecran fixe

        def send(kind, g, buttons=Qt.LeftButton):
            QApplication.sendEvent(row, QMouseEvent(kind, QPointF(row.mapFromGlobal(g)), QPointF(g),
                                                    Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton,
                                                    buttons, Qt.NoModifier))
        send(QEvent.MouseButtonPress, press)
        for dy in (10, 20, 30):
            send(QEvent.MouseMove, press + QPoint(0, dy))
            settle(30)
            self.assertEqual(other._extra_dims.heights.rows[0].height(), before)   # rien ne bouge ailleurs
        send(QEvent.MouseButtonRelease, press + QPoint(0, 30), Qt.NoButton)
        settle(60)
        self.assertEqual(other._extra_dims.heights.rows[0].height(), row.height())
        self.assertEqual(row.height(), before + 30)


if __name__ == "__main__":
    unittest.main()
