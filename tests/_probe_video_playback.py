"""Sonde de LECTURE du module vidéo dans une vraie fenêtre (OpenGL + moteur choisi) : régularité des images
affichées, temps bloquant du fil de l'interface par image, pause exacte, lectures répétées.

    QT_QPA_PLATFORM=windows python tests/_probe_video_playback.py <vidéo> [secondes] [moteur vlc|pyav]

Rien n'est écrit dans les réglages (copies de tests/_isolate.py)."""
import _isolate  # noqa: F401

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication(sys.argv)

from settings_store import DEFAULT_SETTINGS  # noqa: E402
from fm_video import viewer as vviewer  # noqa: E402
from fm_video.pane import VideoPane  # noqa: E402


def pump(seconds):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        APP.processEvents()
        time.sleep(0.001)


def main():
    path = Path(sys.argv[1])
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 6.0
    engine = sys.argv[3] if len(sys.argv) > 3 else "vlc"
    host = QWidget()
    host.setGeometry(40, 40, 1600, 940)
    settings = dict(DEFAULT_SETTINGS, video_backend="opengl", video_autoplay=False, video_engine=engine,
                    video_volume=0)
    pane = VideoPane(host, settings)
    host.show()
    paints = []
    blocks = []
    if vviewer.GLViewer is not None and isinstance(pane.viewer, vviewer.GLViewer):
        orig_paint = pane.viewer.paintGL

        def paint():
            t = time.perf_counter()
            orig_paint()
            paints.append((t, time.perf_counter() - t))
        pane.viewer.paintGL = paint
    orig_frame = pane._on_vlc_frame

    def on_frame():
        t = time.perf_counter()
        orig_frame()
        blocks.append(time.perf_counter() - t)
    pane._on_vlc_frame = on_frame
    if pane._vlc is not None:
        pass
    t0 = time.perf_counter()
    ok = pane.open(path)
    pane.fade_in()
    print(f"ouverture {ok} en {time.perf_counter() - t0:.3f} s, moteur {pane._engine}, afficheur "
          f"{getattr(pane.viewer, 'engine', '?')}, zoom {pane.viewer.zoom():.3f} ({pane.viewer.zoom_mode()})")
    pump(1.0)
    if pane._vlc is not None:
        try:
            pane._vlc.frameReady.disconnect()
        except Exception:                                    # noqa: BLE001
            pass
        pane._vlc.frameReady.connect(on_frame)
    print("erreur afficheur :", repr(getattr(pane.viewer, "error", "")))
    paints.clear()
    blocks.clear()
    t_play = time.perf_counter()
    pane.play()
    pump(seconds)
    index_before = pane.index
    t_pause = time.perf_counter()
    pane.pause()
    pause_block = time.perf_counter() - t_pause
    pump(0.6)
    span = time.perf_counter() - t_play
    gaps = [b[0] - a[0] for a, b in zip(paints, paints[1:])]
    paint_ms = [d * 1000 for _t, d in paints]
    print(f"lecture {seconds:.1f} s : {len(paints)} peintures ({len(paints) / span:.1f} /s), "
          f"images du moteur {len(blocks)}")
    if gaps:
        gaps_ms = sorted(g * 1000 for g in gaps)
        print(f"  écart entre peintures : médiane {statistics.median(gaps_ms):.1f} ms, "
              f"95e {gaps_ms[int(len(gaps_ms) * .95)]:.1f}, max {gaps_ms[-1]:.1f} ms ; >50 ms : "
              f"{sum(1 for g in gaps_ms if g > 50)}")
        print(f"  peinture GL : médiane {statistics.median(paint_ms):.2f} ms, max {max(paint_ms):.2f} ms")
    if blocks:
        b = sorted(x * 1000 for x in blocks)
        print(f"  fil de l'interface par image : médiane {statistics.median(b):.2f} ms, max {b[-1]:.2f} ms")
    print(f"pause : bloquant {pause_block * 1000:.1f} ms, rang {index_before} -> {pane.index} (affiché "
          f"{pane._shown}), image du moteur exact : {pane.viewer.frame is not None and pane.viewer.frame.index}")
    if pane._engine == "vlc":
        for n in range(1, 21):
            pane.play()
            pump(0.5)
            vol = pane._vlc.player.audio_get_volume()
            mute = pane._vlc.player.audio_get_mute()
            track = pane._vlc.player.audio_get_track()
            pane.go_last() if n % 5 == 0 else pane.pause()
            pump(0.2)
            if n in (1, 2, 3, 5, 10, 20):
                print(f"  lecture {n} : volume VLC {vol}, muet {mute}, piste audio {track}, "
                      f"images VLC {pane._vlc.displayed}")
    pane.shutdown()


if __name__ == "__main__":
    main()
