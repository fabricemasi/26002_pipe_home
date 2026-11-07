"""Guides du magnétisme par SORTE d'aimantation (fm_board/snap_guides.py, Réglages > Module MRO > Magnétisme ;
demande de l'utilisateur 2026-11-06) : bords des documents (éléments du board, page de Design, plan de travail
d'Illustrator) / objets internes aux documents (tracés d'Illustrator, éléments d'une page de Design), chacun avec
son guide affiché ou non, sa couleur, son type de ligne du CAD et son échelle : une ligne du tableau Magnétisme par
sorte (cellule divisée), grisée quand le maître « Guides d'alignement » est coupé."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import copy
import unittest

from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QTransform

from test_design import APP, DesignTestCase, settle
from test_illustrator import IllTestCase
from fm_board import snap_guides
from fm_board.snap_guides import DOCUMENTS, INNER


class DashPatternTest(unittest.TestCase):
    def test_cad_linetypes_become_screen_dashes(self):
        from fm_cad import cad_model
        self.assertIsNone(snap_guides.qt_dashes(cad_model.LINETYPES["continuous"][1], 2.0))
        self.assertEqual(snap_guides.qt_dashes(cad_model.LINETYPES["dashed"][1], 2.0), [6.0, 3.0])
        self.assertEqual(snap_guides.qt_dashes(cad_model.LINETYPES["dashdot"][1], 2.0), [6.0, 3.0, 1.0, 3.0])
        self.assertEqual(snap_guides.qt_dashes(cad_model.LINETYPES["dot"][1], 1.0), [1.0, 1.5])   # point = 1 px
        self.assertEqual(snap_guides.qt_dashes((-1, 2, -1), 1.0), [2.0, 2.0])     # commence par un espace
        self.assertEqual(snap_guides.qt_dashes((2, -1, 3), 1.0), [5.0, 1.0])      # trait aux deux bouts : bouclé

    def test_settings_make_one_pen_per_kind_and_nothing_when_unchanged(self):
        settings = {"board_snap_doc_color": "#00ff00", "board_snap_doc_linetype": "continuous",
                    "board_snap_inner_color": "#0000ff", "board_snap_inner_linetype": "center",
                    "board_snap_inner_ltscale": 10}
        snap_guides.apply_settings(settings)
        self.assertFalse(snap_guides.apply_settings(settings))                  # chemin rapide : rien à refaire
        doc, inner = snap_guides.pen(DOCUMENTS), snap_guides.pen(INNER)
        self.assertEqual((doc.color().name(), doc.style()), ("#00ff00", Qt.SolidLine))
        self.assertEqual((inner.color().name(), inner.dashPattern()), ("#0000ff", [8.0, 1.5, 1.5, 1.5]))
        self.assertTrue(doc.isCosmetic() and inner.isCosmetic())
        self.assertTrue(snap_guides.apply_settings({**settings, "board_snap_inner_linetype": "inconnu"}))
        self.assertEqual(snap_guides.pen(INNER).style(), Qt.SolidLine)       # type disparu du CAD : continu
        snap_guides.apply_settings(None)

    def test_hidden_kinds_are_not_drawn(self):
        from PySide6.QtGui import QImage, QPainter
        lines = [snap_guides.GuideLine(0, 5, 40, 5, kind=DOCUMENTS), snap_guides.GuideLine(0, 15, 40, 15, kind=INNER)]

        def drawn(settings):
            snap_guides.apply_settings(settings)
            image = QImage(40, 20, QImage.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            snap_guides.draw(painter, lines)
            painter.end()
            return [QColor.fromRgba(image.pixel(20, y)).alpha() > 0 for y in (5, 15)]

        self.assertEqual(drawn(None), [True, True])
        self.assertEqual(drawn({"board_snap_inner_guides": False}), [True, False])        # toggle de la ligne
        self.assertEqual(drawn({"board_snap_doc_guides": False}), [False, True])
        self.assertEqual(drawn({"board_snap_guides": False}), [False, False])             # le maître
        self.assertFalse(snap_guides.shown(INNER))
        snap_guides.apply_settings(None)
        self.assertTrue(snap_guides.shown(INNER))


class SettingsTableTest(unittest.TestCase):
    def test_magnetism_table_has_one_split_row_per_kind(self):
        import settings_store
        import settings_window_v2 as v2
        from settings_catalog import CATALOG
        from fm_board.settings import MRO_TREE
        magnet = next(n for n in MRO_TREE if n.title == "Magnétisme")
        self.assertEqual((magnet.group, magnet.children), ("MRO", ()))            # plus de sous-section « Guides »
        labels = [sp.label for sp in CATALOG["MRO"]]
        at = labels.index("Guides d'alignement")
        self.assertEqual(labels[at + 1:at + 4], ["Bords des documents", "Objets internes aux documents",
                                                "Cadre sur son document"])
        row = CATALOG["MRO"][at + 1]
        self.assertEqual([caption for caption, _sub in row.params["parts"]],
                         ["Guide d'alignement", "Couleur du guide", "Type de ligne", "Échelle du type de ligne"])
        settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
        settings["board_snap_inner_linetype"] = "dashdot"
        settings["board_snap_doc_guides"] = False
        fields, record = {}, []
        frame = v2.build_group("MRO", v2.ScopeValues(settings, None), settings["colors"], fields, {}, [],
                               record, lambda: None)
        keys = {f"board_snap_{k}_{f}" for k in ("doc", "inner", "frame") for f in ("guides", "color", "linetype", "ltscale")}
        self.assertLessEqual(keys, set(fields))
        inner = fields["board_snap_inner_color"]
        self.assertEqual(inner.field("board_snap_inner_linetype").value(), "Tiret-point")   # types de ligne du CAD
        self.assertIn("Fantôme", [label for _k, label in inner.field("board_snap_inner_linetype")._choices])
        for spec, widget in record:                         # défauts déclarés, chaque champ relu à sa valeur
            for _caption, sub in spec.params.get("parts", ()):
                self.assertEqual(settings_store.DEFAULT_SETTINGS[sub.key], sub.default, sub.key)
            read = v2.read_spec(spec, widget)
            for key, value in read.items():
                self.assertEqual(value, settings[key], key)
        self.assertIs(v2.read_spec(row, fields["board_snap_doc_guides"])["board_snap_doc_guides"], False)
        master = fields["board_snap_guides"]
        self.assertTrue(inner.isEnabled())
        master.setChecked(False)                             # le maître coupé : les deux lignes grisées, en direct
        self.assertFalse(inner.isEnabled() or fields["board_snap_doc_color"].isEnabled())
        master.setChecked(True)
        fields["board_snap_enabled"].setChecked(False)      # le magnétisme coupé aussi
        self.assertFalse(inner.isEnabled())
        frame.deleteLater()


class BoardGuidesTest(DesignTestCase):
    def test_board_guides_follow_the_documents_row(self):
        self.pane.apply_settings({**self.pane._settings, "board_snap_doc_color": "#00ff00",
                                  "board_snap_doc_linetype": "dashed", "board_snap_doc_ltscale": 40})
        self.assertEqual(snap_guides.pen(DOCUMENTS).dashPattern(), [12.0, 6.0])
        self.view.set_zoom(1.0)
        self.view.center_on(QPointF(0, 0))
        settle()
        self.scene.guides = [QLineF(-200, 0, 200, 0)]
        self.scene.update()
        settle()
        image = self.view.viewport().grab().toImage()
        y = self.view.mapFromScene(QPointF(0, 0)).y()
        x0, x1 = self.view.mapFromScene(QPointF(-150, 0)).x(), self.view.mapFromScene(QPointF(150, 0)).x()
        def green(x):                                                   # trait anticrénelé : sur 1 ou 2 rangées
            colors = [QColor(image.pixel(x, y + d)) for d in (-1, 0, 1)]
            return any(c.green() - max(c.red(), c.blue()) > 60 for c in colors)
        row = [green(x) for x in range(x0, x1)]
        changes = sum(1 for a, b in zip(row, row[1:]) if a != b)
        self.assertGreater(sum(row), len(row) * 0.5)                   # 2/3 de trait
        self.assertLess(sum(row), len(row) * 0.85)                      # et des espaces
        self.assertGreater(changes, 20)                                 # ~16 tirets sur 300 px
        self.scene.guides = []
        self.pane.apply_settings({**self.pane._settings, "board_snap_doc_color": "#ff2fd0",
                                  "board_snap_doc_linetype": "continuous", "board_snap_doc_ltscale": 20})


class DesignGuidesTest(DesignTestCase):
    def test_page_edges_are_documents_and_objects_are_inner(self):
        page = self.page()
        lines = self.ctl._guide_lines(page, [("v", 0.0), ("v", 500.0), ("h", 800.0), ("v", 300.0),
                                             ("seg", 0.0, 0.0, 10.0, 0.0)])
        self.assertEqual([snap_guides.kind_of(line) for line in lines], [DOCUMENTS, DOCUMENTS, DOCUMENTS, INNER, INNER])
        page.data["guides"] = [{"axis": "v", "pos": 300.0}]                  # un repère de la page : la page
        self.assertEqual(snap_guides.kind_of(self.ctl._guide_lines(page, [("v", 300.0)])[0]), DOCUMENTS)

    def test_moving_an_object_shows_an_inner_guide_on_another_object(self):
        self.page()
        self.ctl.add_shape("rect", {"x": 100.0, "y": 100.0, "w": 200.0, "h": 100.0})     # bord droit : 300
        b = self.ctl.add_shape("rect", {"x": 620.0, "y": 440.0, "w": 100.0, "h": 60.0})     # loin de tout en y
        start = self.center(b)
        self.mouse(QEvent.MouseButtonPress, start, mods=Qt.ControlModifier)
        for n in (1, 2, 3):                                                   # gauche 620 -> 303 (près de 300)
            self.mouse(QEvent.MouseMove, start + QPointF(-317 * n / 3, 0), buttons=Qt.LeftButton,
                       mods=Qt.ControlModifier)
        kinds = [snap_guides.kind_of(line) for line in self.ctl.guides]
        self.mouse(QEvent.MouseButtonRelease, start + QPointF(-317, 0), mods=Qt.ControlModifier)
        settle()
        self.assertAlmostEqual(b.pos().x(), 300, delta=0.01)
        self.assertEqual(set(kinds), {INNER})


class _OwnDocument:
    """Élément redimensionné qui a un document dans son cadre (comme un PDF) : tailles de cadre qui l'ajustent."""
    item_id = "doc-cadre"

    def __init__(self, widths=(), heights=()):
        self.widths, self.heights = tuple(widths), tuple(heights)

    def snap_document_sizes(self, w, h):
        return self.widths, self.heights


class FrameOnDocumentTest(DesignTestCase):
    """« Le cadre bleu doit se snapper au document » (capture d'un PDF au cadre plus haut que sa page)."""

    def resize(self, item, rect, handle):
        self.view.set_zoom(1.0)
        return self.scene.snap_resize(item, rect, QTransform(), handle, Qt.NoModifier)

    def test_dragged_edge_snaps_to_the_document_and_shows_a_frame_guide(self):
        doc = _OwnDocument(widths=(300.0,), heights=(500.0,))
        out = self.resize(doc, QRectF(5000, 5000, 400, 503), "b")               # bas tiré 3 sous la page
        self.assertEqual((out.top(), out.height()), (5000, 500))
        self.assertEqual([(snap_guides.kind_of(g), g.y1()) for g in self.scene.guides], [(snap_guides.FRAME, 5500)])
        out = self.resize(doc, QRectF(5000, 4997, 400, 503), "t")               # haut tiré : le bas reste fixe
        self.assertEqual((out.top(), out.bottom()), (5000, 5500))
        out = self.resize(doc, QRectF(5000, 5000, 302, 500), "r")
        self.assertEqual(out.width(), 300)
        out = self.resize(doc, QRectF(5000, 5000, 400, 540), "b")               # trop loin : rien
        self.assertEqual((out.height(), self.scene.guides), (540, []))
        self.scene.clear_guides()

    def test_pdf_document_sizes_follow_its_fit(self):
        from unittest import mock
        from fm_pdf import board_docs
        from fm_pdf.board_item import PdfItem

        class Entry:
            info = {"sizes": [(612.0, 792.0)]}

            def ready(self):
                return True

        item = PdfItem({"type": "pdf_doc", "id": "pdf-test", "x": 0, "y": 0, "w": 400, "h": 600, "fit": "width"})
        with mock.patch.object(board_docs, "existing_entry", lambda _item: Entry()):
            widths, heights = item.snap_document_sizes(400, 600)               # pleine largeur : la hauteur seule
            self.assertEqual((widths, [round(h, 1) for h in heights]), ([], [517.6]))
            item.data.update(fit="", zoom=0.5)                                  # zoom fixe : largeur et hauteur
            self.assertEqual(item.snap_document_sizes(400, 600), ([306.0], [396.0]))
            item.data["fit"] = "page"                                           # pleine page, limitée en largeur
            self.assertEqual([round(h, 1) for h in item.snap_document_sizes(400, 600)[1]], [517.6])
            widths, heights = item.snap_document_sizes(400, 400)               # limitée en hauteur
            self.assertEqual(([round(w, 1) for w in widths], heights), ([309.1], []))
        with mock.patch.object(board_docs, "existing_entry", lambda _item: None):
            self.assertEqual(item.snap_document_sizes(400, 600), ((), ()))      # document pas prêt : rien


class BoardInnerObjectsTest(IllTestCase):
    def test_board_guide_along_illustrator_objects_only_is_inner(self):
        from fm_board.scene import guide_kind
        self.ctl.add_artboard(QRectF(0, 0, 400, 300))
        self.rect(100, 100, 50, 50)
        settle()
        others = self.scene._candidates(set())
        kinds = sorted(o.inner for o in others)
        self.assertIn(True, kinds)                                    # le tracé : interne au document
        self.assertIn(False, kinds)                                   # le plan de travail : bord du document
        moving = QRectF(100, 500, 80, 60)                             # un document aligné sous le tracé
        lines = self.scene._guide_lines(moving, (0.0, 100.0), None, others)
        self.assertEqual([snap_guides.kind_of(line) for line in lines], [INNER])
        lines = self.scene._guide_lines(moving.translated(-100, 0), (0.0, 0.0), None, others)   # bord du plan
        self.assertEqual([snap_guides.kind_of(line) for line in lines], [DOCUMENTS])
        self.assertEqual(guide_kind([]), DOCUMENTS)                   # rien d'aligné (grille) : bords
        self.assertEqual((self.scene._edge_kind(others, 100.0, 0), self.scene._edge_kind(others, 0.0, 0),
                          self.scene._edge_kind(others, 123.4, 0)), (INNER, DOCUMENTS, DOCUMENTS))   # redimensionner


class IllustratorGuidesTest(IllTestCase):
    def test_artboard_edges_are_documents_and_objects_are_inner(self):
        from fm_illustrator.tools_xform import Snapper
        self.ctl.add_artboard(QRectF(0, 0, 400, 300))
        self.rect(100, 100, 50, 50)
        moving = self.rect(250, 200, 30, 30)
        snapper = Snapper(self.ctl, exclude=[moving])
        _dx, _dy, lines = snapper.snap_rect(QRectF(402, 200, 30, 30))        # bord gauche près du bord du plan
        self.assertEqual([snap_guides.kind_of(line) for line in lines], [DOCUMENTS])
        _dx, _dy, lines = snapper.snap_rect(QRectF(152, 220, 30, 30))        # près du bord droit d'un objet
        self.assertEqual([snap_guides.kind_of(line) for line in lines], [INNER])


if __name__ == "__main__":
    unittest.main()
