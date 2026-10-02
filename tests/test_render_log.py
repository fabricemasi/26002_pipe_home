"""Journal tabulaire : progression compacte, details conserves et rotation quotidienne."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import datetime
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLineEdit
from PySide6.QtGui import QImage

APP = QApplication.instance() or QApplication([])
import pipeline_browser as p
import detail_panel as dp
from PySide6.QtWidgets import QMessageBox
import previews as pv


class RenderLogTest(unittest.TestCase):
    def test_requested_columns_and_render_metadata(self):
        with tempfile.TemporaryDirectory(prefix="render_columns_") as work:
            root = Path(work)
            source = root / "bib" / "projets" / "voiture_01.obj"
            output = root / "cache" / "turntable" / "frame_000.png"
            path = pv._write_render_log(root, "[10:00:00] > Aperçu en cours : " + str(source),
                                       str(source), "turntable", "high")
            pv._write_render_log(root, "[10:05:00] [100%] voiture_01.obj — Turntable prêt",
                                str(source), "turntable", "high", str(output))
            table = pv._RenderLogTable()
            table.load_entries(pv._read_render_log_entries(path))
            self.assertEqual(table.columnCount(), 8)
            self.assertEqual([table.item(0, col).text() for col in range(8)],
                             ["bib/projets/voiture_01.obj", "10:00:00", "10:05:00", "High poly",
                              "Turntable", str(output.parent), "frame_000.png", "Terminé"])
            self.assertEqual([table.horizontalHeaderItem(i).text() for i in range(8)], pv._RENDER_LOG_COLUMNS)
            self.assertEqual(path.read_text(encoding="utf-8").count("<th>"), 8)

    def test_worker_records_actual_generated_image(self):
        with tempfile.TemporaryDirectory(prefix="render_output_path_") as work:
            root = Path(work)
            source = root / "model.obj"
            source.touch()
            task = pv._PreviewDecodeTask(source, source.stat().st_mtime, force_render=True, render_mode="high")
            image = QImage(4, 4, QImage.Format_ARGB32)
            image.fill(0xff777777)
            with patch.object(pv, "FILE_IMAGE_DISK_CACHE_DIR", root / "cache"), \
                    patch.object(task, "_decode", return_value=image):
                task._run_preview()
            self.assertTrue(Path(task.output_path).is_file())
            manager = pv._PreviewDecodeManager()
            task.log_directory = root
            manager._write_task_log(task, "> Aperçu en cours : " + str(source))
            manager.active[str(source)] = task
            manager._on_task_progress(str(source), 100, "Image prête")
            row = pv._read_render_log_entries(pv._render_log_path(root))[0]
            self.assertEqual(row["poly"], "High poly")
            self.assertEqual(row["output_name"], Path(task.output_path).name)
            self.assertEqual(row["state"], "Terminé")

    def test_choose_day_and_refresh_preserves_selection(self):
        with tempfile.TemporaryDirectory(prefix="render_log_days_") as work:
            root = Path(work)
            with patch.object(pv, "datetime") as clock:
                clock.now.return_value = datetime(2026, 9, 30, 10, 0, 0)
                previous = pv._write_render_log(root, "> Aperçu en cours : ancien.blend", "ancien.blend")
            today = pv._write_render_log(root, "> Aperçu en cours : actuel.blend", "actuel.blend")
            original = previous.read_bytes()
            window = QWidget()
            window.root_field = QLineEdit(str(root), window)
            panel = dp.DetailPanel(window)
            try:
                panel.open_render_log_button.click()
                combo = panel._render_log_day_combo
                self.assertEqual(combo.count(), 2)
                self.assertEqual(combo.currentData(), today.stem.removeprefix("pipeline_preview_render_"))
                combo.setCurrentIndex(combo.findData("2026-09-30"))
                self.assertEqual(panel._render_log_dialog_table._entries[0]["file"], "ancien.blend")
                panel.open_preview_render_log()
                self.assertEqual(combo.currentData(), "2026-09-30")
                self.assertEqual(previous.read_bytes(), original)
            finally:
                window.deleteLater()
                APP.processEvents()

    def test_mixed_windows_encoding_is_readable_and_preserved_on_append(self):
        with tempfile.TemporaryDirectory(prefix="render_log_encoding_") as work:
            root = Path(work)
            path = pv._write_render_log(root, "> Aperçu en cours : modèle.blend", "modèle.blend")
            # Reproduit l'octet 0xa7 de la capture, dans du HTML et du JSON UTF-8.
            path.write_bytes(path.read_bytes().replace("modèle.blend".encode("utf-8"),
                                                       "modèle".encode("utf-8") + b"\xa7.blend"))
            entries = pv._read_render_log_entries(path)
            self.assertEqual(entries[0]["file"], "modèle§.blend")
            pv._write_render_log(root, "[100%] modèle§.blend — Aperçu terminé", "modèle§.blend")
            path.read_text(encoding="utf-8")
            self.assertEqual(pv._read_render_log_entries(path)[0]["state"], "Terminé")

    def test_button_opens_daily_table_and_refreshes_same_window(self):
        with tempfile.TemporaryDirectory(prefix="open_render_log_test_") as work:
            root = Path(work)
            pv._write_render_log(root, "> Aperçu en cours : model.blend", "model.blend")
            window = QWidget()
            window.root_field = QLineEdit(str(root), window)
            layout = QVBoxLayout(window)
            panel = dp.DetailPanel(window)
            layout.addWidget(panel)
            try:
                with patch.object(p, "open_path") as external_open:
                    panel.open_render_log_button.click()
                    dialog = panel._render_log_dialog
                    self.assertTrue(dialog.isVisible())
                    self.assertEqual(panel._render_log_dialog_table.rowCount(), 1)
                    external_open.assert_not_called()
                    pv._write_render_log(root, "[100%] model.blend — Aperçu terminé", "model.blend")
                    panel.open_preview_render_log()
                    self.assertIs(panel._render_log_dialog, dialog)
                    self.assertEqual(panel._render_log_dialog_table._entries[0]["state"], "Terminé")
                    dialog.close()
                    panel.open_render_log_button.click()
                    self.assertTrue(dialog.isVisible())
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_log_read_error_is_visible(self):
        window = QWidget()
        window.root_field = QLineEdit("missing", window)
        panel = dp.DetailPanel(window)
        try:
            with patch.object(dp, "_write_render_log", side_effect=OSError("Accès refusé")), \
                    patch.object(QMessageBox, "warning") as warning:
                panel.open_render_log_button.click()
                self.assertIn("Accès refusé", warning.call_args.args[2])
        finally:
            window.deleteLater()
            APP.processEvents()

    def test_one_row_per_render_and_details(self):
        table = pv._RenderLogTable()
        table.appendPlainText("[10:00:00] > Aperçu en cours : model.blend")
        table.appendPlainText("[10:00:05] [ 70%] model.blend — Turntable : image 1 / 72")
        table.appendPlainText("[10:00:10] [100%] model.blend — Turntable prêt")
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table._entries[0]["type"], "Turntable")
        self.assertEqual(table._entries[0]["state"], "Terminé")
        self.assertEqual(table._entries[0]["end"], "10:00:10")
        self.assertEqual(len(table._entries[0]["details"]), 3)
        table.appendPlainText("[10:10:00] > Aperçu en cours : model.blend")
        table.appendPlainText("[10:10:01] [ 99%] model.blend — Erreur de rendu")
        self.assertEqual(table.rowCount(), 2)
        self.assertEqual(table._entries[1]["state"], "Échec")
        table.clear()
        self.assertEqual(table.rowCount(), 0)
        self.assertEqual(table.columnCount(), 8)

    def test_daily_html_preserves_history_and_escapes_details(self):
        with tempfile.TemporaryDirectory(prefix="daily_table_test_") as work:
            root = Path(work)
            with patch.object(pv, "datetime") as clock:
                clock.now.return_value = datetime(2026, 10, 1, 23, 59, 59)
                first = pv._write_render_log(root, "> Aperçu en cours : model.blend", "model.blend")
                pv._write_render_log(root, "[ 50%] model.blend — <script>alert(1)</script>", "model.blend")
                clock.now.return_value = datetime(2026, 10, 2, 0, 0, 1)
                second = pv._write_render_log(root, "[100%] model.blend — Aperçu terminé", "model.blend")
            self.assertNotEqual(first, second)
            self.assertEqual(len(list(root.glob("*.html"))), 2)
            first_html = first.read_text(encoding="utf-8")
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", first_html)
            self.assertNotIn("<script>alert(1)</script>", first_html)
            match = re.search(r'<script id="render-data" type="application/json">(.*?)</script>', first_html, re.S)
            rows = json.loads(match.group(1))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["progress"], "50%")
            self.assertEqual(len(rows[0]["details"]), 2)
            self.assertIn("Terminé", second.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
