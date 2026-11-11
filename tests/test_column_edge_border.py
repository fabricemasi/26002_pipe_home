"""Bordure masquee des cotes d'une colonne qui touchent le bord de la zone des colonnes
(`capture_widgets._column_edge_sides`, 2026-11-07) : gauche de la 1re colonne, haut / bas, droite de
l'inspecteur ; dans une pile verticale, haut = 1re, bas = derniere (sauf pile tassee en haut)."""
import _isolate  # noqa: F401
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget  # noqa: E402

import capture_widgets  # noqa: E402
from capture_widgets import _column_edge_sides, _column_hidden_sides  # noqa: E402
from fm_theme.style import column_frame_style  # noqa: E402

APP = QApplication.instance() or QApplication([])
_ZERO = {"top": 0, "right": 0, "bottom": 0, "left": 0}


class ColumnEdgeSidesTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(capture_widgets, "column_padding_for", lambda title: dict(_ZERO))
        patcher.start()
        self.addCleanup(patcher.stop)
        # Meme structure que PipelineBrowser : host -> [columns_layout, etirement, inspecteur]
        self.host = QWidget()
        self.addCleanup(self.host.deleteLater)
        host_layout = QHBoxLayout(self.host)
        self.row = QHBoxLayout()
        host_layout.addLayout(self.row)
        host_layout.addStretch(1)
        self.first, self.second = QWidget(self.host), QWidget(self.host)
        self.row.addWidget(self.first)
        self.row.addWidget(self.second)
        self.detail = QWidget(self.host)
        host_layout.addWidget(self.detail)

    def test_rangee(self):
        self.assertEqual(_column_edge_sides(self.first, "Type"), {"left", "top", "bottom"})
        self.assertEqual(_column_edge_sides(self.second, "Type"), {"top", "bottom"})
        self.assertEqual(_column_edge_sides(self.detail, "Inspecteur"), {"top", "bottom", "right"})

    def test_pile_verticale(self):
        wrapper = QWidget(self.host)
        stack = QVBoxLayout(wrapper)
        top, bottom = QWidget(wrapper), QWidget(wrapper)
        stack.addWidget(top)
        stack.addWidget(bottom)
        self.row.addWidget(wrapper)
        self.assertEqual(_column_edge_sides(top, "IN"), {"top"})
        self.assertEqual(_column_edge_sides(bottom, "IN"), {"bottom"})
        stack.setAlignment(Qt.AlignTop)              # pile Focus : ne descend pas jusqu'en bas
        self.assertEqual(_column_edge_sides(bottom, "IN"), set())

    def test_padding_garde_la_bordure(self):
        with mock.patch.object(capture_widgets, "column_padding_for",
                               lambda title: dict(_ZERO, left=4, top=2)):
            self.assertEqual(_column_edge_sides(self.first, "Type"), {"bottom"})

    def test_cadre_peint(self):
        hidden = _column_hidden_sides(self.second, "Type", True)
        self.assertEqual(hidden, {"left", "top", "bottom"})
        enabled = column_frame_style("Type", hidden_sides=hidden)["enabled"]
        for side in hidden:
            self.assertFalse(enabled[side])


if __name__ == "__main__":
    unittest.main()
