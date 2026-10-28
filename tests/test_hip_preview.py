"""Apercus des scenes Houdini (.hip / .hiplc / .hipnc) : hython exporte la geometrie affichee, puis
meme rendu Blender que les autres fichiers 3D. Le rendu reel est saute sans Houdini ou Blender."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
from _lent import lent  # noqa: E402
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import config
import previews


class HoudiniDispatchTest(unittest.TestCase):
    def test_houdini_scenes_are_3d_previews(self):
        for suffix in (".hip", ".hiplc", ".hipnc"):
            self.assertIn(suffix, config.RENDERABLE_3D_EXTENSIONS)
            self.assertIn(suffix, config.PREVIEWABLE_EXTENSIONS)
            self.assertIn(suffix, previews.TURNTABLE_EXTENSIONS)

    def test_decode_task_uses_hython(self):
        image = QImage(4, 4, QImage.Format_RGB32)
        with mock.patch.object(previews, "_render_hip_wireframe", return_value=image) as render:
            task = previews._PreviewDecodeTask(Path("scene.hipnc"), 0.0, quiet=True, render_mode="high")
            self.assertIs(task._decode(), image)
        self.assertEqual(render.call_args.kwargs["render_mode"], "high")

    def test_without_houdini_nothing_is_rendered(self):
        messages = []
        with mock.patch.object(previews, "_hython_executable", return_value=None):
            result = previews._render_hip_wireframe(Path("scene.hip"), 256, lambda _p, m: messages.append(m))
        self.assertIsNone(result)
        self.assertIn("hython introuvable", messages[-1])


@lent
@unittest.skipUnless(previews._hython_executable() and previews._blender_executable(), "Houdini ou Blender absent")
class HoudiniRenderTest(unittest.TestCase):
    """Scene fabriquee par hython (une sphere affichee, une boite masquee), rendue de bout en bout."""

    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        cls.hip = cls.dir / "scene.hip"
        script = (
            "import hou\n"
            "geo = hou.node('/obj').createNode('geo', 'shown')\n"
            "geo.createNode('sphere').setDisplayFlag(True)\n"
            "hidden = hou.node('/obj').createNode('geo', 'hidden')\n"
            "hidden.createNode('box')\n"
            "hidden.setDisplayFlag(False)\n"
            "hou.hipFile.save(%r)\n" % str(cls.hip).replace("\\", "/")
        )
        subprocess.run([previews._hython_executable(), "-c", script], capture_output=True, timeout=300)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, True)

    def test_displayed_geometry_is_rendered(self):
        self.assertTrue(self.hip.is_file(), "hython n'a pas pu creer la scene de test")
        messages = []
        image = previews._render_hip_wireframe(self.hip, 256, lambda _p, m: messages.append(m))
        self.assertIsNotNone(image, messages[-3:])
        self.assertFalse(image.isNull())


if __name__ == "__main__":
    unittest.main()
