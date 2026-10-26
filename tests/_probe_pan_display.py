"""Sonde : retard de BOUT EN BOUT d'un deplacement du board (pan), lu SUR L'ECRAN.

La sonde `_probe_cad_latency.py` s'arrete quand l'appli a fini son image ; ce qui vient apres (file d'images du pilote,
composition de Windows) n'y est pas. Celle-ci lit le bureau COMPOSE par Windows (GDI BitBlt de l'ecran) : un trait
vertical du CAD est deplace par un pan au bouton du milieu (mouvements postes), et pour chaque nouvelle position vue a
l'ecran on cherche le mouvement qui l'a demandee -> retard mouvement -> ecran (le balayage de l'ecran lui-meme, une
demi-image en moyenne, n'est pas compte).

    QT_QPA_PLATFORM=windows python tests/_probe_pan_display.py
    GPU=1        rendu GPU des entites CAD (sinon processeur)
    SWAP1=1      ancien format : l'echange de tampons attend le balayage (l'appli : `cad_gpu.low_latency_format`)
    NOPACE=1     sans la cadence de la couche GPU (une image par demande)
    SECONDS=<s>  duree max (3)
    FILE=<.mro>  un vrai dessin (copie) autour du trait repere ; USER_SETTINGS=1 : les reglages de l'utilisateur
    SPEED=<px/s> vitesse de la souris (250)
    BOARD_ROOT=<dossier contenant un paquet board/>   (comparer avec une autre version du paquet)
Fenetre A L'ECRAN, sur l'ecran principal, rien par-dessus pendant la mesure."""
import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if os.environ.get("BOARD_ROOT"):
    sys.path.insert(0, os.environ["BOARD_ROOT"])
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

if os.environ.get("SWAP1"):                       # SWAP1=1 : l'ancien format (echange qui attend le balayage)
    from PySide6.QtGui import QSurfaceFormat
    _fmt = QSurfaceFormat.defaultFormat()
    _fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(_fmt)
else:                                            # comme l'appli (pipeline_browser.main)
    try:
        from board.cad_gpu import low_latency_format
        low_latency_format()
    except ImportError:
        pass
APP = QApplication.instance() or QApplication([])
import app_style  # noqa: E402
import board  # noqa: E402
from board import cad_model, model  # noqa: E402
from board import ui as board_ui  # noqa: E402
from board import view as view_mod  # noqa: E402

print("paquet board :", os.path.dirname(board.__file__))

gdi, user = ctypes.windll.gdi32, ctypes.windll.user32


class _Row:
    """Une rangee de pixels de l'ecran (bureau compose), lue par BitBlt."""

    def __init__(self, x, y, width):
        self.x, self.y, self.width = x, y, width
        self.screen = user.GetDC(None)
        self.dc = gdi.CreateCompatibleDC(self.screen)
        self.bmp = gdi.CreateCompatibleBitmap(self.screen, width, 1)
        gdi.SelectObject(self.dc, self.bmp)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]
        self.info = BITMAPINFOHEADER()
        self.info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        self.info.biWidth, self.info.biHeight, self.info.biPlanes = width, 1, 1
        self.info.biBitCount, self.info.biCompression = 32, 0
        self.buf = (ctypes.c_uint8 * (width * 4))()

    def read(self) -> bytes:
        gdi.BitBlt(self.dc, 0, 0, self.width, 1, self.screen, self.x, self.y, 0x00CC0020)   # SRCCOPY
        gdi.GetDIBits(self.dc, self.bmp, 0, 1, self.buf, ctypes.byref(self.info), 0)
        return bytes(self.buf)


def brightest(row: bytes, background: bytes) -> int | None:
    """Colonne du trait ROUGE vif (repere, distinct d'un vrai dessin), ou None. Pixels de GetDIBits : B, G, R."""
    best, where = 0, None
    for i in range(0, len(row), 4):
        d = row[i + 2] - max(row[i], row[i + 1])
        if d > best:
            best, where = d, i // 4
    return where if best > 80 else None


def settle(seconds):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        APP.processEvents()


def main():
    seconds = float(os.environ.get("SECONDS", "3"))
    app_style.apply_style(APP)
    from settings_store import DEFAULT_SETTINGS
    work = Path(tempfile.mkdtemp())
    path = board.create_board_file(work / "plan")
    host = QWidget()
    screen = APP.primaryScreen()
    area = screen.availableGeometry()
    host.resize(min(1600, area.width() - 80), min(900, area.height() - 80))
    host.move(area.left() + 40, area.top() + 40)
    host.show()
    host.raise_()
    base = DEFAULT_SETTINGS
    if os.environ.get("USER_SETTINGS"):           # USER_SETTINGS=1 : les reglages de l'utilisateur (copie, _isolate)
        from settings_store import load_settings
        base = load_settings()
    if os.environ.get("FILE"):                    # FILE=<.mro> : un vrai dessin (copie) autour du trait repere
        import shutil
        shutil.copy(os.environ["FILE"], path)
    pane = board_ui.BoardPane(host, dict(base, board_cad_gpu=bool(os.environ.get("GPU"))))
    pane.open(path)
    if not os.environ.get("FILE"):
        pane.scene.set_page({"grid": False}, record=False)
    pane.show()
    pane.fit()
    pane.toggle_cad(True)
    ctl = pane.cad
    cad = ctl.cad_page()
    view = pane.view
    vp = view.viewport()
    settle(0.8)
    ratio = screen.devicePixelRatio()
    y = int(vp.height() * 0.6)
    origin = vp.mapToGlobal(QPoint(0, y))
    row = _Row(int(origin.x() * ratio), int(origin.y() * ratio), int(vp.width() * ratio))
    background = row.read()                     # fond : la rangee AVANT le trait
    cx, cy = ctl.view_to_doc(vp.rect().center())           # au milieu de la vue (et du dessin)
    values = cad_model.new_line_values(cad, (cx, cy - 1e5), (cx, cy + 1e5))
    values.update(lineweight=3.0, color="#ff0000")   # repere : rouge vif, assez epais pour etre net
    pane.scene._add(model.new_item("cad_line", **values))
    ctl.touch_index()
    settle(0.5)

    # La souris « physique » avance a vitesse constante, dans un seul sens ; comme Windows (qui regroupe les
    # mouvements), un nouveau mouvement n'est envoye que quand le precedent a ete traite, a la position du moment.
    # Le pan deplace le dessin autant que la souris : le trait vu en colonne X correspond a la position que la souris
    # avait a l'instant t = debut + (X - X0) / vitesse -> retard = instant ou l'ecran le montre - t.
    speed = float(os.environ.get("SPEED", "250"))       # pixels logiques par seconde
    w = vp.width()
    start = QPointF(w * 0.3, y)
    line0 = brightest(row.read(), background)
    if line0 is None:
        print("trait introuvable a l'ecran")
        return
    span = w * 0.4
    seconds = min(seconds, span / speed)
    state = {"pending": False, "processed": 0}
    original = view_mod.BoardView.mouseMoveEvent

    def wrapped(self, event):
        original(self, event)
        state["pending"] = False
        state["processed"] += 1
    view_mod.BoardView.mouseMoveEvent = wrapped
    APP.sendEvent(vp, QMouseEvent(QEvent.MouseButtonPress, start, vp.mapToGlobal(start), Qt.MiddleButton,
                                  Qt.MiddleButton, Qt.NoModifier))
    settle(0.2)
    swaps = []
    gpu = getattr(view, "gpu", None)
    if gpu is not None and os.environ.get("NOPACE") and hasattr(gpu, "pacer"):
        gpu.pacer.active = False
    if gpu is not None:
        gpu.frameSwapped.connect(lambda: swaps.append(1))
    t_start = time.perf_counter()
    end = t_start + seconds

    import threading

    def mouse():                                # FIL A PART, comme le pilote de la souris (pas de minuterie Qt)
        while time.perf_counter() < end:
            if not state["pending"]:
                pos = QPointF(start.x() + speed * (time.perf_counter() - t_start), y)
                state["pending"] = True
                APP.postEvent(vp, QMouseEvent(QEvent.MouseMove, pos, vp.mapToGlobal(pos), Qt.NoButton,
                                              Qt.MiddleButton, Qt.NoModifier))
            time.sleep(0.001)
    seen = []                                   # (instant, colonne vue)
    every = []                                  # (instant, colonne vue) a CHAQUE lecture : regularite
    reads = []

    def watch():                                # FIL A PART : la lecture de l'ecran ne retarde pas l'interface
        last = None
        while time.perf_counter() < end + 0.2:
            t0 = time.perf_counter()
            pixels = row.read()
            reads.append((time.perf_counter() - t0) * 1000)
            found = brightest(pixels, background)
            every.append((time.perf_counter(), found))
            if found is not None and found != last:
                seen.append((time.perf_counter(), found))   # fin de la lecture : au plus tard la
                last = found
    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    threading.Thread(target=mouse, daemon=True).start()
    # Boucle d'evenements qui DORT entre deux evenements, comme dans l'appli (la faire tourner en continu cachait
    # l'imprecision des minuteries de Qt).
    from PySide6.QtCore import QEventLoop
    loop = QEventLoop()
    QTimer.singleShot(int((end + 0.2 - time.perf_counter()) * 1000), loop.quit)
    loop.exec()
    watcher.join()
    APP.sendEvent(vp, QMouseEvent(QEvent.MouseButtonRelease, start, vp.mapToGlobal(start), Qt.MiddleButton,
                                  Qt.NoButton, Qt.NoModifier))
    view_mod.BoardView.mouseMoveEvent = original
    lat = []
    for t, x in seen:
        moved = (x - line0) / ratio                # pixels logiques parcourus par la souris
        if 2 < moved < speed * seconds - 2:
            lat.append((t - (t_start + moved / speed)) * 1000)
    lat.sort()
    if not lat:
        print("aucune mesure")
        return
    q = lambda p: lat[min(len(lat) - 1, int(round(p * (len(lat) - 1))))]   # noqa: E731
    reads.sort()
    # Regularite : avance du trait entre deux lectures (une par composition) ; une image ratee = 0 puis le double.
    steps = [b[1] - a[1] for a, b in zip(every, every[1:]) if a[1] is not None and b[1] is not None
             and t_start + 0.1 < a[0] and b[0] < end - 0.05]
    steps = [d for d in steps if d >= 0]
    if steps:
        median = sorted(steps)[len(steps) // 2]
        odd = sum(1 for d in steps if abs(d - median) > max(1.5, median * 0.5))
        print(f"  regularite : avance mediane {median} px par image, {odd} / {len(steps)} images irregulieres "
              f"({100.0 * odd / len(steps):.0f} %)")
    print(f"rendu {'GPU' if gpu is not None else 'processeur'} ; {state['processed']} mouvements traites en "
          f"{seconds:.1f} s, {len(swaps)} images GPU rendues, {len(seen)} vues ; lecture de l'ecran p50 {reads[len(reads) // 2]:.1f} ms")
    print(f"  souris -> ecran  p50 {q(.5):6.1f}  p25 {q(.25):6.1f}  p75 {q(.75):6.1f}  p95 {q(.95):6.1f} ms  "
          f"(n={len(lat)} ; la lecture de l'ecran ajoute 0 a ~16 ms)")


if __name__ == "__main__":
    main()
