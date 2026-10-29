"""Sonde du module vidéo dans la VRAIE fenêtre principale (affichage natif Windows, fenêtre hors écran, OpenGL) :
double-clic sur une vidéo puis sur une image EXR d'une séquence = le module s'ouvre (jamais de logiciel externe),
temps bloquants mesurés (ouverture, pas à pas, lecture), image centrée gardée par les informations, plein écran,
fenêtres de corrections et d'export, rendu GPU = rendu CPU. Dossier temporaire, jamais les réglages réels.

    QT_QPA_PLATFORM=windows python tests/_probe_video_module.py
"""

from _probe_isolate import isolate as _isolate_probe, protected_modules as _probe_modules
_isolate_probe()
import copy, os, subprocess, sys, tempfile, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import settings_store, browser_core
import pipeline_browser as pb
from browser_core_parts import project_config as _core_project_config, settings as _core_settings
for module in (settings_store, pb, browser_core, _core_project_config, _core_settings, *_probe_modules()):
    for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting",
                 "save_live_state"):
        if hasattr(module, name):
            setattr(module, name, lambda *a, **k: None)
opened = []
pb.open_path = lambda path: opened.append(Path(path))
root = Path(tempfile.mkdtemp())
folder = root / "shot" / "renders"
folder.mkdir(parents=True)
W, H, N = 1920, 1080, 96
SRC = os.environ.get("SRC")                         # vidéo fournie : copiée à la place du clip généré
CLIP = "clip" + (Path(SRC).suffix if SRC else ".mp4")
PLAY = float(os.environ.get("PLAY", "2"))
if SRC:
    import shutil
    shutil.copy(SRC, folder / CLIP)
proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                         f"testsrc2=size={W}x{H}:rate=25:duration={N / 25}", "-f", "lavfi", "-i",
                         f"sine=frequency=440:duration={N / 25}", "-c:v", "libx264", "-g", "50", "-bf", "3",
                         "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(folder / ("gen.mp4" if SRC else "clip.mp4"))])
proc.wait()
import OpenImageIO as oiio
for n in range(1001, 1025):
    img = np.zeros((540, 960, 4), np.float32)
    img[..., 0] = np.linspace(0, 4, 960)[None, :] * (n - 1000) / 24
    img[..., 1] = 0.18
    img[..., 3] = 1.0
    out = oiio.ImageOutput.create("x.exr")
    out.open(str(folder / f"beauty.{n}.exr"), oiio.ImageSpec(960, 540, 4, oiio.HALF))
    out.write_image(img)
    out.close()
QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
app = QApplication(sys.argv)


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents(); QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete); time.sleep(0.002)


def wait(cond, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.002)
    return False


settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
settings["root_path"] = str(root)
settings["video_timeline_thumbs"] = os.environ.get("THUMBS", "1") == "1"
pb.apply_all_settings(settings)
pb.apply_style(app)
win = pb.PipelineBrowser(root); win._idle_preview_scheduler.timer.stop()
win.move(-3000, 0); win.resize(1400, 900); win.show()
QTest.qWaitForWindowActive(win)
pump(0.5)
win._navigate_to(folder); pump(1.0)
column = [c for c in [*win.columns, *win.group_columns] if c.directory == folder][0]


def double_click(name):
    lst = column.list
    item = next(lst.item(i) for i in range(lst.count()) if Path(lst.item(i).data(pb.ROLE_PATH)).name == name)
    lst.scrollToItem(item)
    pos = lst.visualItemRect(item).center()
    QTest.mouseClick(lst.viewport(), Qt.LeftButton, Qt.NoModifier, pos); pump(0.3)
    import cProfile, pstats
    prof = cProfile.Profile(); prof.enable()
    t = time.perf_counter()
    QTest.mouseDClick(lst.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
    dt = time.perf_counter() - t
    prof.disable()
    if os.environ.get("PROFILE"):
        pstats.Stats(prof).sort_stats("cumulative").print_stats(25)
    return dt


import fm_video as video
video.preload()                                    # fait en fond 4,5 s après le démarrage de l'appli
dt = double_click(CLIP)
pane = win._video
assert pane is not None and not opened, ("module non ouvert", opened)
print(f"double-clic vidéo -> module ouvert en {dt * 1000:.0f} ms (bloquant), moteur {pane.viewer.engine}")
assert wait(lambda: pane._shown == 0)
print("1re image affichée", pane.viewer.frame.size, "erreur GL:", repr(getattr(pane.viewer, "error", "")))
# pas à pas (temps bloquant de chaque touche + attente de l'image)
worst = 0.0
for key in [Qt.Key_Right] * 12 + [Qt.Key_Left] * 12:
    t = time.perf_counter()
    QTest.keyClick(pane.viewer, key)
    block = time.perf_counter() - t
    target = pane.index
    assert wait(lambda: pane._shown == target, 5), target
    worst = max(worst, block)
print(f"pas à pas : 24 crans, pire temps bloquant {worst * 1000:.1f} ms, image exacte à chaque fois")
# recul au-delà d'une image clé (GOP 50)
pane.go(60); wait(lambda: pane._shown == 60)
t = time.perf_counter()
for i in range(59, 44, -1):
    pane.step(-1)
    assert wait(lambda: pane._shown == i, 5)
print(f"recul de 15 images (traverse une image clé) : {(time.perf_counter() - t) * 1000 / 15:.1f} ms / image")
# lecture
pane.go(0); wait(lambda: pane._shown == 0)
pump(float(os.environ.get("WAIT", "0")))
import cProfile, pstats
main_prof = cProfile.Profile()
shown, swaps = [], []
# Images POSÉES dans l'afficheur (les deux moteurs : LibVLC passe par _on_vlc_frame, PyAV par _show).
_orig_set = pane.viewer.set_frame
pane.viewer.set_frame = lambda f: (shown.append((time.perf_counter(), f.index)), _orig_set(f))
pane.viewer.frameSwapped.connect(lambda: swaps.append(pane._shown))
vlc_before = pane._vlc.displayed if pane._vlc is not None else 0
stalls = []
if os.environ.get("STACKS"):
    import faulthandler
    _stacks = open(os.environ["STACKS"], "w")
    faulthandler.dump_traceback_later(0.25, repeat=True, file=_stacks)
pane.play(); main_prof.enable()
_end = time.monotonic() + PLAY
while time.monotonic() < _end:
    _t = time.perf_counter(); app.processEvents(); stalls.append(time.perf_counter() - _t); time.sleep(0.002)
main_prof.disable(); pane.pause()
if os.environ.get("STACKS"):
    faulthandler.cancel_dump_traceback_later()
    _stacks.close()
stalls.sort()
print(f"fil de l'interface pendant la lecture : {len(stalls)} tours, pire {stalls[-1] * 1000:.0f} ms, "
      f"> 30 ms : {sum(1 for x in stalls if x > 0.03)}")
if pane._vlc is not None:
    print("images rendues par VLC pendant la lecture :", pane._vlc.displayed - vlc_before)
pane.viewer.set_frame = _orig_set
print("moteur de lecture :", pane._engine)
if os.environ.get("CALLERS"):
    pstats.Stats(main_prof).sort_stats("cumulative").print_callers(os.environ["CALLERS"])
    pstats.Stats(main_prof).sort_stats("cumulative").print_stats(18)
if os.environ.get("PROFILE_PLAY"):
    pstats.Stats(main_prof).sort_stats("cumulative").print_stats(r"(previews|pipeline_browser|detail_panel|column|browser_core)\.py|(?:browser_core_parts|column_parts|preview_services|main_window)[/\\]", 25)
gaps = [b[0] - a[0] for a, b in zip(shown, shown[1:])]
_fps = float(pane.source.fps)
print(f"lecture {PLAY:g} s à {_fps:g} fps : {len({i for _t, i in shown})} images montrées (attendu ~{PLAY * _fps:.0f}), "
      f"écart moyen {np.mean(gaps) * 1000:.1f} ms, pire {max(gaps) * 1000:.1f} ms ; "
      f"{len(set(swaps))} images peintes à l'écran (fenêtre hors écran)")
# lecture d'une séquence EXR : même mesure plus bas
# informations : l'image ne bouge pas
before = pane.viewer.image_rect()
QTest.keyClick(pane.viewer, Qt.Key_I); pump(0.2)
assert pane.overlay.isVisible() and pane.viewer.image_rect() == before
print("touche I : informations affichées, image immobile ;", [t for t, _r in pane.info_sections()])
win._apply_settings(dict(settings, video_info_opacity=20))
assert pane.overlay.look["opacity"] == 20
# GPU = CPU
from fm_video import color as vcolor
img = pane.viewer.grabFramebuffer()
rect = pane.viewer.image_rect(); dpr = pane.viewer.devicePixelRatioF()
frame = pane.viewer.frame
ref, _a = vcolor.process_np(frame.pixels[540:541, 960:961], pane._pipeline, pane.view_state())
c = img.pixelColor(int((rect.left() + rect.width() * 960.5 / W) * dpr), int((rect.top() + rect.height() * 540.5 / H) * dpr))
pass
# corrections
window = pane.open_grade_window("grade_main"); pump(0.3)
t = time.perf_counter()
pane.set_grade({**vcolor.DEFAULT_GRADE, "exposure": 1.0}, save=False); pump(0.05)
print(f"correction appliquée en {(time.perf_counter() - t) * 1000:.1f} ms ; fenêtre « {window.windowTitle() or 'corrections'} » ouverte")
window.close()
# export
ew = pane.open_export_window(); pump(0.3)
print("fenêtre d'export ouverte :", ew is not None)
ew.close()
# plein écran
QTest.keyClick(pane.viewer, Qt.Key_F); pump(0.5)
assert pane.is_fullscreen()
assert wait(lambda: pane._shown >= 0)
QTest.keyClick(pane.viewer, Qt.Key_Escape); pump(0.5)
assert not pane.is_fullscreen() and win._video is pane
print("plein écran : entrée (F) / sortie (Échap) ok, image", pane.viewer.frame.size)
QTest.keyClick(pane.viewer, Qt.Key_Escape); pump(0.3)
assert win._video is None
print("Échap : module fermé, retour aux colonnes")
# séquence EXR au double-clic
dt = double_click("beauty.1010.exr")
pane = win._video
assert pane is not None and pane.source.kind == "sequence", "séquence non ouverte"
assert wait(lambda: pane._shown == 9)
print(f"double-clic EXR -> séquence {pane.source.frame_count} images, ouverte sur 1010 en {dt * 1000:.0f} ms ;",
      pane.viewer.frame.pixels.dtype)
win._close_video(); pump(0.3)
print("OK")
win.close()
