"""Sonde VISUELLE du module vidéo (vraie fenêtre OpenGL) : cadre de l'image (bordure, coins arrondis, ombre),
scopes, miniatures de la timeline, puis lecture avec scopes visibles (régularité). Capture écrite en PNG.

    QT_QPA_PLATFORM=windows python tests/_probe_video_look.py <vidéo> <capture.png>"""
import _isolate  # noqa: F401

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication(sys.argv)

from settings_store import DEFAULT_SETTINGS  # noqa: E402
from fm_video.pane import VideoPane  # noqa: E402


def pump(seconds):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        APP.processEvents()
        time.sleep(0.001)


def main():
    path, shot = Path(sys.argv[1]), Path(sys.argv[2])
    host = QWidget()
    host.setGeometry(40, 40, 1400, 860)
    sides = {"top": True, "right": True, "bottom": True, "left": True}
    settings = dict(DEFAULT_SETTINGS, video_backend="opengl", video_autoplay=False, video_volume=0,
                    video_default_zoom="fit", video_fit_margin=40,
                    video_frame_border_enabled=sides, video_frame_border_thickness=3,
                    video_frame_border={k: "#e0a040" for k in sides},
                    video_frame_radius={"top_left": 24, "top_right": 24, "bottom_right": 24, "bottom_left": 24},
                    video_frame_shadow_enabled=sides, video_frame_shadow="#d0000000", video_frame_shadow_size=24,
                    video_frame_shadow_offset_y=10)
    pane = VideoPane(host, settings)
    host.show()
    pane.open(path)
    pane.fade_in()
    pump(1.0)
    pane.toggle_scopes()
    pump(1.5)
    image = host.grab()
    gl = pane.viewer.grabFramebuffer() if hasattr(pane.viewer, "grabFramebuffer") else None
    if gl is not None:
        from PySide6.QtGui import QPainter
        painter = QPainter(image)
        painter.drawImage(pane.viewer.mapTo(host, pane.viewer.rect().topLeft()), gl)
        painter.end()
        # Scopes : widget posé sur l'afficheur, repeint par-dessus la capture GL.
        painter = QPainter(image)
        painter.drawPixmap(pane.scopes.mapTo(host, pane.scopes.rect().topLeft()), pane.scopes.grab())
        painter.end()
    image.save(str(shot))
    print("capture", shot, "erreur afficheur", repr(getattr(pane.viewer, "error", "")),
          "miniatures", len(pane.timeline.thumbs), "scopes", bool(pane.scopes.result))
    # Lecture avec scopes et effets : régularité.
    stamps = []
    orig = pane.viewer.paintGL

    def paint():
        stamps.append(time.perf_counter())
        orig()
    pane.viewer.paintGL = paint
    pane.play()
    pump(4.0)
    pane.pause()
    gaps = sorted((b - a) * 1000 for a, b in zip(stamps, stamps[1:]))
    if gaps:
        print(f"lecture avec scopes : {len(stamps)} peintures, médiane {statistics.median(gaps):.1f} ms, "
              f"95e {gaps[int(len(gaps) * .95)]:.1f} ms, max {gaps[-1]:.1f} ms")
    pane.shutdown()


if __name__ == "__main__":
    main()
