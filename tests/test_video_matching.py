import _isolate
import tempfile
import unittest
from pathlib import Path
import numpy as np
from fm_video.matching import fit_pair,fit_distribution,export_cube
from fm_video.color import load_cube


class MatchingTest(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(42)

    def test_neutral_pair_exports_neutral_lut(self):
        source = self.rng.random((100,100,3))
        model = fit_pair(source,source)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            path = Path(folder)/'neutral.cube'
            metrics = export_cube(model,path,17)
            lut = load_cube(path)
            samples = self.rng.random((300,3))
            np.testing.assert_allclose(lut.apply_np(samples),samples,atol=1e-6)
            self.assertLess(metrics['interpolation_rgb_max'],1e-6)

    def test_known_grade_generalizes_to_new_pixels(self):
        source = self.rng.random((100,100,3))
        matrix = np.array([[.8,.02,0],[.02,.85,.03],[0,.01,.7]])
        def grade(rgb):
            return rgb@matrix+np.array([.04,.02,.1])
        model = fit_pair(source,grade(source),degree=1)
        validation = self.rng.random((500,3))
        self.assertLess(np.sqrt(np.mean((model.apply(validation)-grade(validation))**2)),.005)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            path = Path(folder)/'grade.cube'
            export_cube(model,path,33)
            np.testing.assert_allclose(load_cube(path).apply_np(validation),model.apply(validation),atol=1e-6)

    def test_distribution_moves_means_and_constant_images_stay_finite(self):
        source = self.rng.random((40,40,3))*.5
        reference = source*.8+.15
        model = fit_distribution(source,reference)
        self.assertLess(model.metrics['after_mean_rgb_distance'],model.metrics['before_mean_rgb_distance'])
        constant = np.full((10,10,3),.2)
        self.assertTrue(np.isfinite(fit_distribution(constant,constant).apply(constant)).all())

    def test_cancelled_export_does_not_replace_existing_file(self):
        source = self.rng.random((20,20,3))
        model = fit_pair(source,source)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            path = Path(folder)/'existing.cube'
            path.write_text('existing')
            with self.assertRaises(InterruptedError):
                export_cube(model,path,17,cancelled=lambda:True)
            self.assertEqual(path.read_text(),'existing')

    def test_paired_dimensions_and_hdr_must_be_explicit(self):
        with self.assertRaises(ValueError):
            fit_pair(np.zeros((20,3)),np.zeros((21,3)))
        with self.assertRaises(ValueError):
            fit_distribution(np.ones((20,3))*2,np.zeros((20,3)))
