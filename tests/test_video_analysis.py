import _isolate
import unittest
import numpy as np
from fm_video.analysis import analyze_rgb


class AnalysisTest(unittest.TestCase):
    def test_constant_red_is_preserved(self):
        result = analyze_rgb(np.full((100,3), [255,0,0]),16)
        self.assertEqual(result['colors'], [((255,0,0),1.0)])
        self.assertAlmostEqual(result['luminance']['mean'],.2126,places=5)

    def test_known_weights_and_tones(self):
        result = analyze_rgb(np.array([[0,0,0]]*75 + [[255,255,255]]*25),16)
        self.assertEqual(result['colors'], [((0,0,0),.75),((255,255,255),.25)])
        self.assertEqual(result['tones'][0],((0,0,0),.75))
        self.assertEqual(result['tones'][2],((255,255,255),.25))
        self.assertEqual(sum(result['histogram'][0]),100)

    def test_exclusions_do_not_change_luminance_statistics(self):
        pixels = np.array([[0,0,0]]*30+[[255,255,255]]*30+[[255,0,0]]*40)
        original = analyze_rgb(pixels)
        result = analyze_rgb(pixels,exclude_black=True,exclude_white=True)
        self.assertEqual(result['colors'],[((255,0,0),1.0)])
        self.assertEqual(result['luminance'],original['luminance'])

    def test_empty_and_cancelled_analysis(self):
        self.assertEqual(analyze_rgb(np.empty((0,3)))['samples'],0)
        self.assertIsNone(analyze_rgb(np.arange(300).reshape(100,3)%256,cancelled=lambda:True))

    def test_sampling_covers_bottom_of_large_image(self):
        pixels = np.array([[0,0,0]]*5000+[[255,255,255]]*5000)
        result = analyze_rgb(pixels,2)
        self.assertAlmostEqual(result['colors'][0][1],.5,places=2)
        self.assertAlmostEqual(result['colors'][1][1],.5,places=2)


class AnalysisWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_roi_and_transparency_are_respected_by_worker(self):
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QImage, QColor
        from fm_video.analysis import _Task,_Signals
        image = QImage(20,10,QImage.Format_RGBA8888)
        image.fill(QColor(0,0,0,0))
        for y in range(10):
            for x in range(10):
                image.setPixelColor(x,y,QColor(255,0,0))
        signals = _Signals()
        results = []
        signals.ready.connect(lambda revision,result:results.append(result))
        _Task(image,16,1,signals,dict(region=QRect(0,0,10,10))).run()
        self.assertEqual(results[0]['colors'],[((255,0,0),1.0)])
        results.clear()
        _Task(image,16,2,signals,dict(region=QRect(10,0,10,10))).run()
        self.assertEqual(results[0]['samples'],0)

    def test_latest_request_and_return_cancel_pending_analysis(self):
        from fm_video.analysis_ui import ColorAnalysis
        from PySide6.QtGui import QImage
        widget = ColorAnalysis()
        image = QImage(20,10,QImage.Format_RGB888)
        image.fill(0xff0000)
        widget.show_image(image,'red')
        widget._start()
        widget.pool.waitForDone()
        self.app.processEvents()
        self.assertEqual(widget.colors[0]['rgb'],(255,0,0))
        widget.stop()
        widget._ready(widget.revision-1,dict(colors=[((0,0,255),1)]))
        self.assertEqual(widget.colors[0]['rgb'],(255,0,0))
        self.assertFalse(widget.debounce.isActive())
        widget.deleteLater()


class AnalysisViewTest(unittest.TestCase):
    """Vue de la maquette « Analyse — Image 4207 » (analysis_ui / analysis_widgets / analysis_look)."""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _view(self):
        from fm_video.analysis_ui import ColorAnalysis
        from PySide6.QtGui import QImage, QColor
        view = ColorAnalysis()
        self.addCleanup(view.deleteLater)
        view.resize(1440, 960)
        image = QImage(64, 32, QImage.Format_RGB888)
        for x in range(64):
            for y in range(32):
                image.setPixelColor(x, y, QColor(200, 40, 30) if x < 48 else QColor(20, 20, 24))
        view.show_image(image, 'Image 7')
        view._start()
        view.pool.waitForDone()
        self.app.processEvents()
        return view

    def test_oklch_and_scope_data(self):
        from fm_video.analysis import oklch, scope_data
        L, C, _h = oklch((255, 255, 255))
        self.assertAlmostEqual(L, 1.0, places=3)
        self.assertLess(C, 1e-3)
        data = scope_data(np.full((4, 8, 3), 128, np.uint8))
        self.assertEqual(data['wave_alpha'].shape, (256, 8))
        self.assertEqual((data['vec'].width(), data['vec'].height()), (256, 256))

    def test_mockup_values_are_defaults_and_settings(self):
        from fm_video.analysis_look import analysis_look
        from fm_video.settings_defaults import VIDEO_DEFAULTS
        from settings_catalog import CATALOG
        look = analysis_look({})
        self.assertEqual((look['bg_color'], look['accent_color'], look['inspector_width'], look['swatch_height']),
                         ('#101112', '#e0b062', 340, 76))
        self.assertEqual(VIDEO_DEFAULTS['video_analysis_panel_color'], '#161719')
        import fm_video.settings  # noqa: F401 - remplit CATALOG
        keys = {spec.key for spec in CATALOG['Vidéo : Analyse colorimétrique']}
        self.assertIn('video_analysis_accent_color', keys)
        self.assertIn('video_analysis_hist_height', keys)
        self.assertTrue(all(k in VIDEO_DEFAULTS for k in keys))
        changed = analysis_look({'video_analysis_inspector_width': 9999, 'video_analysis_accent_color': '#123456'})
        self.assertEqual((changed['inspector_width'], changed['accent_color']), (600, '#123456'))
        self.assertNotEqual(changed['key'], look['key'])

    def test_settings_window_builds_the_section(self):
        import copy
        import settings_store
        import settings_window_v2 as v2
        import fm_video.settings  # noqa: F401 - remplit CATALOG
        settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
        fields = {}
        table = v2.build_group("Vidéo : Analyse colorimétrique", v2.ScopeValues(settings, None), settings["colors"],
                               fields, {}, [], [], lambda: None)
        self.addCleanup(table.deleteLater)
        self.assertIn("video_analysis_accent_color", fields)
        self.assertIn("video_analysis_swatch_height", fields)

    def test_view_fills_every_zone_from_real_analysis(self):
        view = self._view()
        self.assertEqual(len(view.colors), 2)
        self.assertEqual(view.selection.data['rgb'], (200, 40, 30))        # la plus couvrante choisie
        self.assertEqual(view.palette_title.text, 'Palette · 2 couleurs')
        self.assertEqual(len(view.tones.tones), 3)
        self.assertIsNotNone(view.gauge.stats)
        self.assertEqual(sum(view.hist.hist[0]), 64 * 32)
        self.assertIsNotNone(view.wave.alpha)
        self.assertIsNotNone(view.vec.image)
        self.assertEqual(view.title.subtitle, 'Proxy 64 × 32 · sRGB SDR')

    def test_display_changes_do_not_reanalyse(self):
        view = self._view()
        emitted = []
        view.settingsChanged.connect(lambda k, v: emitted.append((k, v)))
        revision = view.revision
        view.order.setCurrentIndex(1)                                      # Couverture
        self.assertEqual(view.colors[0]['rgb'], (200, 40, 30))
        view._set_state('order', 'L')
        self.assertEqual(view.colors[0]['rgb'], (20, 20, 24))
        view._scope('wave')
        self.assertFalse(view.hist.isVisibleTo(view))
        self.assertTrue(view.wave.isVisibleTo(view))
        view.chips.toggled.emit('rg')
        view._viewer_bg(0)
        self.assertEqual(view.image.bg.name(), '#000000')
        self.assertEqual(view.revision, revision)                         # rien de recalculé
        self.assertIn(('video_analysis_scope', 'wave'), emitted)
        self.assertIn(('video_analysis_viewer_bg', 0), emitted)

    def test_pipette_region_and_whole_image(self):
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QColor
        view = self._view()
        view._sampled(QColor(10, 20, 30))
        self.assertEqual(view.selection.data['rgb'], (10, 20, 30))
        self.assertIsNone(view.palette.current)
        view.image.region = QRect(48, 0, 16, 32)
        view.image.regionChanged.emit(view.image.region)
        self.assertIn('région 16 × 32 px', view.footer.left)
        view.debounce.stop()
        view._start()
        view.pool.waitForDone()
        self.app.processEvents()
        self.assertEqual([c['rgb'] for c in view.colors], [(20, 20, 24)])
        view._tool('I')
        self.assertIsNone(view.image.region)
        self.assertEqual(view.footer.right, 'Image entière : analyse de tout le cadre')

    def test_shades_and_pixel_map(self):
        from fm_video.analysis import SUBS, analyze_rgb, label_map
        rgb = np.array([[200, 40, 30], [190, 50, 40], [20, 20, 24], [30, 25, 30]] * 50, np.uint8)
        result = analyze_rgb(rgb, 2)
        self.assertEqual(len(result['subs']), 2)
        self.assertEqual(len(result['subs'][1]), 2)                      # 2 nuances distinctes
        self.assertAlmostEqual(sum(w for shades in result['subs'] for _rgb, w in shades), 1.0)
        labels = label_map(np.array([[[200, 40, 30], [20, 20, 24]]], np.uint8), result['centers'],
                           result['sub_centers'])
        self.assertEqual((labels[0, 0] // SUBS, labels[0, 1] // SUBS), (1, 0))

    def test_isolation_render(self):
        from fm_video.analysis_isolate import Isolation
        rgba = np.zeros((1, 2, 4), np.uint8)
        rgba[0, 0] = (200, 40, 30, 255)
        rgba[0, 1] = (100, 100, 100, 255)
        iso = Isolation(rgba, np.array([[6, 0]], np.uint8), [(10, 10, 10), (210, 50, 40)])
        image = iso.render({6}, False, False, 50, 0, '#000000', False)
        self.assertEqual(image.pixelColor(0, 0).getRgb()[:3], (200, 40, 30))   # choisie : d'origine
        self.assertEqual(image.pixelColor(1, 0).getRgb()[:3], (50, 50, 50))    # autre : gris x 50 %
        image = iso.render({6}, True, True, 50, 0, '#ff00ff', False)
        self.assertEqual(image.pixelColor(0, 0).getRgb()[:3], (210, 50, 40))   # aplat de palette
        self.assertEqual(image.pixelColor(1, 0).getRgb()[:3], (255, 0, 255))   # autre : unie
        self.assertEqual(iso.plain(True).pixelColor(1, 0).getRgb()[:3], (10, 10, 10))

    def test_select_shades_pipette_and_isolation(self):
        view = self._view()
        red = next(c for c in view.colors if c['rgb'] == (200, 40, 30))['i']
        self.assertIsNotNone(view.isolation)
        self.assertEqual((view.state['iso'], view.state['render']), (False, 'orig'))   # défauts demandés
        self.assertEqual(view.picks, view._group(red))                    # la couleur entière
        view.iso_toggle.toggled.emit(True)
        view.render_timer.stop()
        view._render()
        self.assertIsNotNone(view.image.display)
        self.assertIn("de l'image", view.image.tag[2])
        other = 1 - red
        view._select(other, ctrl=True)                                     # Ctrl : ajoute
        self.assertEqual(view.picks, view._group(red) | view._group(other))
        view._select(other, ctrl=True)                                     # Ctrl : retire
        self.assertEqual(view.picks, view._group(red))
        view._select_sub(red, 0)
        self.assertEqual((view.picks, view.sub), ({red * 6}, 0))
        self.assertEqual(view.selection.data['digits'], 2)
        view._select_sub(red, 0)                                           # 2e clic : la couleur entière
        self.assertEqual((view.picks, view.sub), (view._group(red), None))
        view._picked(60, 10)                                               # pixel sombre
        self.assertEqual((view.selected, view.image.marker), (other, (60, 10)))
        revision = view.revision
        emitted = []
        view.settingsChanged.connect(lambda k, v: emitted.append((k, v)))
        view.iso_toggle.toggled.emit(False)
        view._set_state('render', 'pal')
        view.render_timer.stop()
        view._render()
        self.assertIsNone(view.image.tag)
        self.assertFalse(view.iso_bar.isEnabled())
        self.assertEqual(view.revision, revision)                         # rien de réanalysé
        self.assertFalse([k for k, _v in emitted if k in ('video_analysis_iso', 'video_analysis_render')])
        view.show_image(view.image.image, 'Image 7')                       # nouvelle ouverture
        self.assertEqual((view.state['iso'], view.state['render']), (False, 'orig'))

    def test_shade_squares_at_most_a_third_of_the_swatch(self):
        from PySide6.QtCore import QRectF
        view = self._view()                                                # 2 couleurs : pastilles très larges
        tile = QRectF(1, 1, 500, 76)
        rects = view.palette._sub_rects(tile, 6)
        self.assertLessEqual(rects[0].height(), 76 / 3)
        self.assertEqual(rects[0].bottom(), tile.bottom())

    def test_coverage_bar_selects_and_region_in_title(self):
        from PySide6.QtCore import QPointF, QRect
        view = self._view()
        view.palette.resize(1000, view.palette.height())
        _bar, segments = view.palette._segments()
        c, rect = segments[0]
        hit = view.palette._hit(QPointF(rect.center().x(), rect.center().y()))
        self.assertEqual(view.palette.colors[hit[0]]['i'], c['i'])
        self.assertIsNone(hit[1])
        view.image.region = QRect(48, 0, 16, 32)
        view._start()
        view.pool.waitForDone()
        self.app.processEvents()
        self.assertIn('région 16 × 32 px', view.palette_title.text)

    def test_iso_sliders_snap_to_100(self):
        view = self._view()
        slider = view.iso_bar.light.slider
        slider.resize(156, 24)
        at_100 = 8 + 140 * 100 / 150
        slider._set_from(at_100 + 5)                                       # près du cran : aimanté
        self.assertEqual(slider.value, 100)
        slider._set_from(at_100 + 20)                                      # loin : valeur libre
        self.assertNotEqual(slider.value, 100)
        self.assertEqual(view.iso_bar.sat.slider.detent, 100)

    def test_settings_restyle_only_when_look_changes(self):
        view = self._view()
        before = view.look
        view.apply_settings({})
        self.assertIs(view.look, before)
        view.apply_settings({'video_analysis_inspector_width': 400, 'video_analysis_scope': 'vec'})
        self.assertEqual(view.inspector.width(), 400)
        self.assertTrue(view.vec.isVisibleTo(view))

    def test_render_offscreen(self):
        view = self._view()
        view.show()
        self.app.processEvents()
        pixmap = view.grab()
        self.assertFalse(pixmap.isNull())
        self.assertEqual(pixmap.toImage().pixelColor(5, 5).name(), '#161719')  # barre du haut
        view.hide()


class MatchingViewTest(unittest.TestCase):
    """Onglet Matching / LUT (seconde maquette : matching_view / matching_widgets)."""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_table_size_matches_mockup_format(self):
        from fm_video.matching_view import table_size
        self.assertEqual(table_size(33), '421,1 Kio')
        self.assertEqual(table_size(17), '57,6 Kio')
        self.assertEqual(table_size(129), '24,6 Mio')

    def test_tab_reference_intensity_and_removal(self):
        import os, tempfile
        from unittest.mock import patch
        from PySide6.QtGui import QImage, QColor
        from fm_video.analysis_ui import ColorAnalysis
        view = ColorAnalysis()
        self.addCleanup(view.deleteLater)
        view.apply_settings({'video_match_method': 1})
        source = QImage(32, 16, QImage.Format_RGB888)
        reference = QImage(32, 16, QImage.Format_RGB888)
        for x in range(32):
            for y in range(16):
                v = (x * 8) % 256
                source.setPixelColor(x, y, QColor(v, 255 - v, (v * 3) % 256))
                reference.setPixelColor(x, y, QColor(min(255, v + 20), 255 - v, (v * 3) % 256 // 2))
        view.show_image(source, 'Image 3')
        self.assertIsNone(view.matching)                              # rien de construit avant le 1er clic
        view._tab('M')
        m = view.matching
        self.assertIs(view.body.currentWidget(), m)
        self.assertEqual(view.export.text, 'Exporter la LUT')
        self.assertFalse(view.export.active)
        self.assertEqual([s[0] for s in m.steps.steps], ['done', 'current', 'todo'])
        self.assertEqual(view.footer.right, 'Référence manquante : matching non calculé')
        path = os.path.join(tempfile.mkdtemp(), 'ref.png')
        reference.save(path)
        m.set_reference(path)
        m.fit_timer.stop()
        m._fit()
        m.pool.waitForDone()
        self.app.processEvents()
        self.assertIsNotNone(m.model)
        self.assertTrue(view.export.active and m.export.active)
        self.assertEqual([s[0] for s in m.steps.steps], ['done', 'done', 'done'])
        self.assertIsNotNone(m.reference_card.thumb)
        with patch.object(m, '_fit') as fit:                          # l'intensité ne refait pas l'ajustement
            m.intensity.setValue(40)
            m._intensity_changed(40)
            m.preview_timer.stop()
            m._preview()
            m.pool.waitForDone()
            self.app.processEvents()
            fit.assert_not_called()
        self.assertEqual(m.viewer.intensity, 40)
        m._drag_pos(25)
        self.assertEqual((m.view, m.viewer.pos), ('split', 25))
        m._pick_view('after')
        self.assertEqual(m.viewer.pos, 0)
        m.clear_reference()
        self.assertIsNone(m.model)
        self.assertFalse(view.export.active)
        view._tab('A')
        self.assertEqual(view.export.text, 'Exporter la palette')
        self.assertTrue(view.export.active)
