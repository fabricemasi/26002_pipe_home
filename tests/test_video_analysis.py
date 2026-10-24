import _isolate
import unittest
import numpy as np
from video.analysis import analyze_rgb


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
        from video.analysis import _Task,_Signals
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
        from video.analysis import ColorAnalysis
        from PySide6.QtGui import QImage
        widget = ColorAnalysis()
        image = QImage(20,10,QImage.Format_RGB888)
        image.fill(0xff0000)
        widget.show_image(image,'red')
        widget._start()
        widget.pool.waitForDone()
        self.app.processEvents()
        self.assertEqual(widget.palette.colors[0][0],(255,0,0))
        widget.stop()
        widget._ready(widget.revision-1,dict(colors=[((0,0,255),1)]))
        self.assertEqual(widget.palette.colors[0][0],(255,0,0))
        self.assertFalse(widget.debounce.isActive())
        widget.deleteLater()
