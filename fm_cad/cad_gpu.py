"""Module CAD du board : MOTEUR DE RENDU GPU (OpenGL 3.3) des entites CAD — option `board_cad_gpu` (Reglages > Module
CAD > Affichage), le rendu par lots du processeur (`cad_items.CadBatch`) reste le secours.

Pourquoi (mesure, octobre 2026, 5 000 lignes, fenetre 2400 x 1300) : le rendu raster coute ~11-15 ms de peinture de la
scene par cran de zoom et ~8-10 ms d'envoi de la fenetre a Windows, quelle que soit l'astuce ; un simple viewport
OpenGL (`QPainter` en OpenGL) etait PIRE. Un vrai moteur GPU, lui : la geometrie est chargee UNE fois dans des tampons,
pan et zoom ne changent qu'une transformation (uniforme), `paintGL` coute ~0,5 ms de processeur (prototype
`tests/_proto_gpu_cad.py` : 60 images / s constantes).

Comment :
- UNE couche `GpuCadLayer` (`QOpenGLWidget` transparent, pose sur le viewport de la vue) dessine TOUTES les entites CAD
  (lignes, arcs, cercles, polylignes) ; la scene Qt ne les peint plus (`ItemHasNoContents`), mais elles y restent :
  selection, accrochage, annulation, enregistrement, deplacement par le board sont inchanges. Consequence assumee : les
  entites CAD sont peintes AU-DESSUS des autres elements du board (post-it, formes…) au lieu de s'y intercaler.
- Chaque segment visible = UNE INSTANCE (extremites en coordonnees de scene relatives a l'origine du lot, demi-epaisseur,
  rayons et codes des terminaisons, couleur) ; le shader trace le segment par son champ de distance (SDF) : trait,
  extremites franches / arrondies (disque) / « border radius » (boite arrondie), couverture ANALYTIQUE (anticrenelage
  exact, sans MSAA), remappee pour un melange en lumiere LINEAIRE (meme formule que `cad_items.linear_blend_table`),
  traits fins (< 1 pixel) = un pixel net (horizontaux / verticaux recales sur le centre d'un pixel). Les couvertures
  qui se chevauchent sont fusionnees par MAXIMUM (`glBlendEquation(GL_MAX)`) : angles et joints sans surepaisseur
  (le meme principe que `ThickPaths`).
- Courbes : arcs et cercles TESSELES en segments (a un quart de pixel, `tess_band`, refaits seulement a la fin d'un zoom,
  comme le rendu par lots) dont les joints interieurs sont arrondis ; polylignes : memes joints (les angles vifs sont
  donc ARRONDIS, pas en onglet, au rendu GPU).
- Motifs des types de ligne : les traits sont des instances (calcules par l'entite, `_thin_dashes`) ; motif plus serre
  que `board_cad_dense_px` : trait continu (instances refaites au franchissement du seuil, seuls les elements a motif).
- Lots (`CHUNK` entites) : un tampon par lot, origine PROPRE au lot (flottants 32 bits precis a l'echelle du lot ; la
  transformation en double precision est faite par le processeur par lot), refait seulement quand une de ses entites
  change ; lots hors de l'ecran non dessines.
- MODE « PUR CAD » (`set_pure`) : quand le board ne contient QUE des entites CAD et que la grille est en lignes, la
  couche est OPAQUE et dessine aussi le fond et la grille (lignes d'un pixel, instances, `_grid_rows`) ; les entites
  vont d'abord dans une texture (fusion par MAXIMUM) puis sont posees sur la grille. La vue raster ne peint plus rien
  (`viewport.setUpdatesEnabled(False)`) : pan et zoom ne repeignent ni ne renvoient plus 12 Mo de fenetre a chaque
  image (mesure : image a 21 ms au lieu de 16,7 avec le fond raster recompose). Un autre element (post-it…), une
  grille en points / croix : retour au mode translucide (le fond raster reste dessous).
- Selection (halo + poignees), apercus, reticule, infobulles : peints par `QPainter` DANS la couche (`paintGL`) apres le
  trace GPU (`CadOverlay.paint_into`) ; les panneaux flottants du board (barres, proprietes…) sont des widgets AU-DESSUS
  de la vue : la couche en efface les zones (`obstacles`) pour qu'ils ne soient jamais recouverts.
- Exports (PNG / SVG / PDF) : les entites reprennent leur peinture ordinaire le temps de l'export (`CadLayer.exporting`).

Aucune dependance vers le reste de l'appli ; PyOpenGL (deja requis par le module video)."""
from __future__ import annotations

import math
import os
import sys
import time

import numpy as np

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QSurfaceFormat

from . import cad_shapes

EPS = 1e-9
FILTER_RADIUS = 0.75               # rayon (pixels de sortie) par defaut du filtre en triangle du suréchantillonnage
SYNC_BUDGET_S = 0.006           # temps maximal de reconstruction des lots par image
CHUNK = 2048                    # entites par lot
CAP_CODES = {"flat": 0, "round": 1, "radius": 2}
JOIN = 3                        # extremite interieure d'une courbe tessellee : toujours arrondie
PENDING = object()               # `GpuStore.build` : lot inacheve (budget de temps)
FLOATS = 12                     # par instance : ax ay bx by | demi-epaisseur r1 r2 codes | r g b a


# ==========================================================================
# Cadence des images (retard du rendu pendant un pan, demande de l'utilisateur)
# ==========================================================================
# L'echange de tampons de la fenetre attendait le balayage de l'ecran (intervalle d'echange 1) : le fil de l'interface
# restait BLOQUE a chaque image, un mouvement de souris attendait la fin de l'image en cours puis une image entiere —
# mesure de bout en bout (`tests/_probe_pan_display.py`, ecran lu) : ~20 ms souris -> ecran au lieu de ~5. L'appli regle
# donc l'intervalle d'echange a 0 (`low_latency_format`, AVANT la QApplication : c'est le format de la FENETRE qui compte)
# — Windows compose de toute facon (pas de dechirure) — et la couche cadence elle-meme ses images : UNE par balayage,
# lancee juste avant que Windows compose (instants des balayages : `DwmGetCompositionTimingInfo`), avec la position la
# plus fraiche ; sans cela elle en rendait ~400 par seconde pour 60 montrees.

def low_latency_format():
    """Format par defaut de l'appli (a poser AVANT la QApplication) : echange sans attente du balayage."""
    fmt = QSurfaceFormat.defaultFormat()
    fmt.setSwapInterval(0)
    QSurfaceFormat.setDefaultFormat(fmt)


class _DwmClock:
    """Instants des balayages de l'ecran (secondes de `time.perf_counter`), lus aupres du compositeur de Windows."""

    def __init__(self):
        self.ok = False
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import c_uint32, c_uint64

            class RATIO(ctypes.Structure):
                _pack_ = 1
                _fields_ = [("num", c_uint32), ("den", c_uint32)]

            class TIMING(ctypes.Structure):          # DWM_TIMING_INFO (dwmapi.h, aligne sur 1 octet)
                _pack_ = 1
                _fields_ = [("cbSize", c_uint32), ("rateRefresh", RATIO), ("qpcRefreshPeriod", c_uint64),
                            ("rateCompose", RATIO), ("qpcVBlank", c_uint64), ("cRefresh", c_uint64),
                            ("cDXRefresh", c_uint32), ("qpcCompose", c_uint64), ("cFrame", c_uint64),
                            ("cDXPresent", c_uint32), ("cRefreshFrame", c_uint64), ("cFrameSubmitted", c_uint64),
                            ("cDXPresentSubmitted", c_uint32), ("cFrameConfirmed", c_uint64),
                            ("cDXPresentConfirmed", c_uint32), ("cRefreshConfirmed", c_uint64),
                            ("cDXRefreshConfirmed", c_uint32), ("cFramesLate", c_uint64),
                            ("cFramesOutstanding", c_uint32), ("cFrameDisplayed", c_uint64),
                            ("qpcFrameDisplayed", c_uint64), ("cRefreshFrameDisplayed", c_uint64),
                            ("cFrameComplete", c_uint64), ("qpcFrameComplete", c_uint64),
                            ("cFramePending", c_uint64), ("qpcFramePending", c_uint64),
                            ("cFramesDisplayed", c_uint64), ("cFramesComplete", c_uint64),
                            ("cFramesPending", c_uint64), ("cFramesAvailable", c_uint64),
                            ("cFramesDropped", c_uint64), ("cFramesMissed", c_uint64),
                            ("cRefreshNextDisplayed", c_uint64), ("cRefreshNextPresented", c_uint64),
                            ("cRefreshesDisplayed", c_uint64), ("cRefreshesPresented", c_uint64),
                            ("cRefreshStarted", c_uint64), ("cPixelsReceived", c_uint64),
                            ("cPixelsDrawn", c_uint64), ("cBuffersEmpty", c_uint64)]
            self._info = TIMING()
            self._info.cbSize = ctypes.sizeof(TIMING)
            self._call = ctypes.windll.dwmapi.DwmGetCompositionTimingInfo
            freq = ctypes.c_int64()
            ctypes.windll.kernel32.QueryPerformanceFrequency(ctypes.byref(freq))
            counter = ctypes.c_int64()
            ctypes.windll.kernel32.QueryPerformanceCounter(ctypes.byref(counter))
            self._freq = float(freq.value)
            self._offset = time.perf_counter() - counter.value / self._freq   # QPC -> perf_counter
            self.ok = self.read() is not None
        except Exception:                               # noqa: BLE001 - pas de compositeur : cadence simple
            self.ok = False

    def read(self):
        """(instant du dernier balayage, periode) en secondes, ou None."""
        if self._call(None, __import__("ctypes").byref(self._info)) != 0:
            return None
        period = self._info.qpcRefreshPeriod / self._freq
        if not 0.002 < period < 0.1:
            return None
        return self._info.qpcVBlank / self._freq + self._offset, period


class FramePacer:
    """Une image par balayage, lancee juste avant que Windows compose : `request()` a la place de `update()`. Sans
    compositeur, une image par periode de l'ecran au plus. Inactif (`update()` direct) quand l'echange attend le
    balayage (intervalle d'echange 1 : la cadence est alors celle du pilote).

    L'instant de lancement est attendu par un FIL A PART (`time.sleep`, precis a ~0,5 ms) qui reveille l'interface
    par un signal : une minuterie de Qt, boucle d'evenements endormie, arrivait jusqu'a 10 ms en retard (p95, mesure)
    — l'image ratait son balayage, le pan SACCADAIT (signale ; la sonde, qui faisait tourner la boucle sans arret, ne
    le voyait pas)."""

    # Avance sur le balayage (Windows compose un peu AVANT lui). Mesure en boucle endormie (sonde _probe_pan_display) :
    # 2-4 ms = ~6 % d'images qui ratent leur balayage (saccades), 6 ms = aussi regulier que sans cadence (~13 ms de
    # retard souris -> ecran, contre ~35 ms avec l'echange qui attend le balayage).
    MARGIN_S = 0.006

    def __init__(self, widget, refresh_hz: float = 60.0):
        import threading
        from PySide6.QtCore import QObject, Signal

        class Waker(QObject):
            go = Signal()
        self.widget = widget
        self.active = QSurfaceFormat.defaultFormat().swapInterval() == 0
        self.clock = _DwmClock() if self.active else None
        self.period = 1.0 / max(24.0, float(refresh_hz or 60.0))
        self.cost = 0.004                           # duree estimee d'une image (moyenne glissante)
        self.last_target = None                     # balayage vise par la derniere image
        self.last_frame = 0.0
        self._waker = Waker(widget)                # vit dans le fil de l'interface : le signal du fil y est mis en file
        self._waker.go.connect(self._wake)
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._deadline = None                       # instant (perf_counter) ou lancer l'image ; None = rien de prevu
        self._thread = None
        self._closed = False
        widget.destroyed.connect(self._close)
        self.pending = False                        # `update()` deja demande, image pas encore presentee
        self.fired_at = 0.0
        widget.frameSwapped.connect(self._swapped)

    def request(self):
        if not self.active:
            self.widget.update()
            return
        now = time.perf_counter()
        if self.scheduled() or (self.pending and now - self.fired_at < 0.1):
            return                                  # l'image a venir prendra l'etat le plus frais
        timing = self.clock.read() if self.clock is not None and self.clock.ok else None
        if timing is None:                          # cadence simple : une image par periode au plus
            wait = self.last_frame + self.period - now
            if wait <= 0:
                self._fire()
            else:
                self._schedule(now + wait)
            return
        vblank, period = timing
        k = math.floor((now - vblank) / period) + 1
        target = vblank + k * period                # prochain balayage
        if self.last_target is not None and abs(target - self.last_target) < period / 2:
            target += period                        # une image vise deja ce balayage : le suivant
        start = target - self.cost - self.MARGIN_S
        wait = start - now
        self.last_target = target
        if wait <= 0.0005:
            self._fire()
        else:
            self._schedule(start)

    def scheduled(self) -> bool:
        return self._deadline is not None

    def _schedule(self, deadline: float):
        import threading
        with self._lock:
            self._deadline = deadline
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="cad-gpu-pacer", daemon=True)
            self._thread.start()
        self._event.set()

    def _run(self):
        """Fil de cadence : attend l'instant prevu (`time.sleep`, precis) puis reveille l'interface."""
        while not self._closed:
            self._event.wait()
            self._event.clear()
            while not self._closed:
                with self._lock:
                    deadline = self._deadline
                if deadline is None:
                    break
                remaining = deadline - time.perf_counter()
                if remaining > 0:
                    time.sleep(remaining)
                    continue
                try:
                    self._waker.go.emit()
                except RuntimeError:                # widget detruit
                    return
                break

    def _wake(self):
        with self._lock:
            self._deadline = None
        if not self._closed:
            self._fire()

    def _close(self, *_args):
        self._closed = True
        self._event.set()

    def _fire(self):
        self.pending = True
        self.fired_at = time.perf_counter()
        self.widget.update()

    def _swapped(self):
        """Image presentee : sa duree (demande -> presentation, composition de la fenetre comprise) sert a lancer la
        suivante assez tot ; prochaine demande possible."""
        now = time.perf_counter()
        if self.pending:
            # Moyenne glissante (mesure : la meilleure) ; une image exceptionnelle (la 1re, un dessin a recharger)
            # plafonnee pour ne pas faire partir les suivantes trop tot.
            took = min(0.02, max(0.0005, now - self.fired_at))
            self.cost = 0.8 * self.cost + 0.2 * took
        self.pending = False
        self.last_frame = now


def available() -> bool:
    """PyOpenGL et QOpenGLWidget presents."""
    try:
        if "OpenGL.GL" not in sys.modules:
            import OpenGL
            OpenGL.ERROR_CHECKING = False                    # chaque appel verifie coutait ~10 ms par image (module video)
        import OpenGL.GL  # noqa: F401
        from PySide6.QtOpenGLWidgets import QOpenGLWidget  # noqa: F401
        return True
    except Exception:                                        # noqa: BLE001
        return False


# ==========================================================================
# Instances d'une entite
# ==========================================================================

def _caps(props: dict, hw: float):
    """(code, rayon) des terminaisons debut / fin / segments interieurs d'un trait de demi-epaisseur `hw`."""
    out = []
    for key in ("end1", "end2", "inner"):
        end = props[key]
        style = end.get("style", "flat")
        code = CAP_CODES.get(style, 0)
        radius = hw * max(0.0, min(100.0, float(end.get("radius", 0.0)))) / 100.0 if style == "radius" else 0.0
        out.append((code, radius))
    return out


def _rgba(color) -> tuple:
    c = QColor(color if isinstance(color, str) else "#1a1a1a")
    return c.redF(), c.greenF(), c.blueF(), c.alphaF()


def item_instances(item, dense: bool, tol: float):
    """Instances (tableau float64 (n, 12), coordonnees de SCENE absolues) d'une entite CAD ; None = rien a dessiner.
    `dense` : motif trop serre a ce zoom (trait continu) ; `tol` : fleche de tessellation des courbes (unites de scene)."""
    props = item.props()
    if not props["visible"]:
        return None
    hw = float(props["lineweight"]) / 2.0
    color = _rgba(props["color"])
    (c1, r1), (c2, r2), (ci, ri) = _caps(props, hw)
    ox, oy = item.pos().x(), item.pos().y()
    rows = []

    def add(a, b, ca, ra, cb, rb):
        rows.append((a[0], a[1], b[0], b[1], hw, ra, rb, ca + 4 * cb, *color))

    intervals = None if dense else item._thin_dashes
    if not item.CURVED:
        a, b = item._local_points()
        a, b = (a.x() + ox, a.y() + oy), (b.x() + ox, b.y() + oy)
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if intervals is None or length <= EPS:
            add(a, b, c1, r1, c2, r2)
        else:
            d = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
            for u0, u1 in intervals:
                pa = (a[0] + d[0] * u0, a[1] + d[1] * u0)
                pb = (a[0] + d[0] * u1, a[1] + d[1] * u1)
                first = (c1, r1) if u0 <= EPS else (ci, ri)
                last = (c2, r2) if u1 >= length - EPS else (ci, ri)
                add(pa, pb, first[0], first[1], last[0], last[1])
    else:
        prims = item._prims_local
        closed = item.closed()
        length = item._length

        def chains(parts, start_style, end_style):
            for pts in cad_shapes.tessellate(parts, tol):
                n = len(pts) - 1
                for k in range(n):
                    p, q = pts[k], pts[k + 1]
                    a, b = (p[0] + ox, -p[1] + oy), (q[0] + ox, -q[1] + oy)
                    if a == b and n > 1:
                        continue
                    ca, ra = start_style if k == 0 else (JOIN, 0.0)
                    cb, rb = end_style if k == n - 1 else (JOIN, 0.0)
                    add(a, b, ca, ra, cb, rb)
                if n == 0:
                    p = pts[0]
                    a = (p[0] + ox, -p[1] + oy)
                    add(a, a, *start_style, *end_style)

        if intervals is None or length <= EPS:
            chains(prims, (JOIN, 0.0) if closed else (c1, r1), (JOIN, 0.0) if closed else (c2, r2))
        else:
            for u0, u1 in intervals:
                if u1 - u0 <= EPS:                               # point : un disque / carre a la place voulue
                    p, s = _locate(prims, u0)
                    q = cad_shapes.prim_point(p, s)
                    a = (q[0] + ox, -q[1] + oy)
                    add(a, a, ci, ri, ci, ri)
                    continue
                parts = cad_shapes.sub_prims(prims, u0, u1)
                if not parts:
                    continue
                first = (c1, r1) if (u0 <= EPS and not closed) else (ci, ri)
                last = (c2, r2) if (u1 >= length - EPS and not closed) else (ci, ri)
                chains(parts, first, last)
    if not rows:
        return None
    return np.array(rows, dtype=np.float64)


def _locate(prims, u: float):
    pos = 0.0
    for p in prims:
        n = cad_shapes.prim_length(p)
        if u <= pos + n or p is prims[-1]:
            return p, max(0.0, min(n, u - pos))
        pos += n
    return prims[0], 0.0


# ==========================================================================
# Lots d'instances
# ==========================================================================

class Chunk:
    def __init__(self):
        self.items: list = []
        self.origin = None                  # (x, y) scene : origine des coordonnees relatives du lot
        self.count = 0
        self.bounds = None                  # (x0, y0, x1, y1) scene, demi-epaisseurs comprises
        self.vbo = None
        self.dirty = True


class GpuStore:
    """Instances de toutes les entites CAD, en lots. Aucun appel OpenGL ici hors `upload` / `free` (contexte courant)."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.chunks: list[Chunk] = []
        self.where: dict = {}               # id(entite) -> (entite, lot)
        self.cache: dict = {}               # id(entite) -> (cle, tableau)
        self.dense: dict = {}               # id(entite) -> motif trop serre ?
        self.patterned: dict = {}           # id(entite) -> entite (a motif : seuil de zoom)
        self.dead: list = []                # entites detruites trouvees en construisant un lot

    # -- membres --
    def mark(self, item, present: bool):
        """Entite ajoutee / changee (`present`) ou retiree."""
        key = id(item)
        entry = self.where.get(key)
        if present:
            self.cache.pop(key, None)
            if entry is None:
                chunk = self.chunks[-1] if self.chunks and len(self.chunks[-1].items) < CHUNK else None
                if chunk is None:
                    chunk = Chunk()
                    self.chunks.append(chunk)
                chunk.items.append(item)
                self.where[key] = (item, chunk)
                entry = self.where[key]
            entry[1].dirty = True
            if item.props()["pattern"]:
                self.patterned[key] = item
            else:
                self.patterned.pop(key, None)
        elif entry is not None:
            chunk = entry[1]
            try:
                chunk.items.remove(item)
            except ValueError:
                pass
            chunk.dirty = True
            del self.where[key]
            self.cache.pop(key, None)
            self.dense.pop(key, None)
            self.patterned.pop(key, None)

    def invalidate_all(self):
        self.cache.clear()
        for chunk in self.chunks:
            chunk.dirty = True

    def zoom_changed(self, zoom: float, dense_px: float):
        """Motifs qui franchissent le seuil « trop serre » : leurs instances sont refaites."""
        for key, item in list(self.patterned.items()):
            dense = item._period > 0 and item._period * zoom < dense_px
            if self.dense.get(key, False) != dense:
                self.dense[key] = dense
                self.cache.pop(key, None)
                entry = self.where.get(key)
                if entry is not None:
                    entry[1].dirty = True

    # -- construction (processeur) --
    def build(self, chunk: Chunk, tol: float, band: float, deadline: float = None):
        """Instances du lot. Seules les courbes dependent de la finesse (`band`) : changer de finesse ne refait pas les
        lignes. Passe `deadline` (horloge `perf_counter`) : on rend None (lot a reprendre a l'image suivante, l'ancien
        contenu reste affiche) plutot que de bloquer l'interface."""
        arrays = []
        for item in chunk.items:
            key = id(item)
            want = band if item.CURVED else 0.0
            cached = self.cache.get(key)
            if cached is None or cached[0] != want:
                if deadline is not None and time.perf_counter() > deadline:
                    return PENDING
                try:
                    data = item_instances(item, self.dense.get(key, False), tol)
                except RuntimeError:                  # entite detruite (suppression) restee dans le lot : retiree
                    chunk.dirty = True
                    self.dead.append(item)
                    continue
                cached = self.cache[key] = (want, data)
            if cached[1] is not None:
                arrays.append(cached[1])
        while self.dead:
            self.mark(self.dead.pop(), False)         # hors du lot, pour de bon
        if not arrays:
            chunk.count = 0
            chunk.bounds = None
            return None
        data = np.concatenate(arrays)
        if chunk.origin is None:
            chunk.origin = (float(data[0, 0]), float(data[0, 1]))
        rel = data.copy()
        rel[:, 0] -= chunk.origin[0]
        rel[:, 2] -= chunk.origin[0]
        rel[:, 1] -= chunk.origin[1]
        rel[:, 3] -= chunk.origin[1]
        hw = float(data[:, 4].max())
        chunk.bounds = (min(data[:, 0].min(), data[:, 2].min()) - hw, min(data[:, 1].min(), data[:, 3].min()) - hw,
                        max(data[:, 0].max(), data[:, 2].max()) + hw, max(data[:, 1].max(), data[:, 3].max()) + hw)
        chunk.count = len(rel)
        return rel.astype(np.float32)

    def prune(self):
        self.chunks = [c for c in self.chunks if c.items or c.vbo is not None]


# ==========================================================================
# Shaders
# ==========================================================================

VERT = """#version 330 core
layout(location=0) in vec2 corner;          // (0..1 le long de l'axe, -1..1 en travers)
layout(location=1) in vec4 seg;             // a.xy, b.xy : scene, relatifs a l'origine du lot
layout(location=2) in vec4 style;           // demi-epaisseur, rayon debut, rayon fin, codes (c1 + 4 c2)
layout(location=3) in vec4 color;
uniform vec2 scale;                          // pixels par unite de scene
uniform vec2 offset;                         // pixels : origine du lot dans la vue
uniform vec2 viewport;                       // pixels
uniform float crisp;                             // traits fins horizontaux / verticaux calees sur un pixel
uniform float ss;                                // suréchantillonnage : pixels du tampon par pixel de sortie
uniform vec3 background;
out vec4 v_loc;                              // u, v, longueur, demi-epaisseur (pixels)
out vec4 v_ext;                              // extension debut / fin, rayon debut / fin (pixels)
out vec4 v_color;
flat out vec4 v_lum;                         // luminances lineaires et sRGB du fond et du trait

float to_linear(float c) { return c <= 0.04045 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4); }
float to_srgb(float c) { return c <= 0.0031308 ? c * 12.92 : 1.055 * pow(c, 1.0 / 2.4) - 0.055; }
float luma(vec3 c) { return dot(vec3(0.2126, 0.7152, 0.0722), vec3(to_linear(c.r), to_linear(c.g), to_linear(c.b))); }

void main() {
    float s = scale.x;
    vec2 a = seg.xy * s + offset;
    vec2 b = seg.zw * s + offset;
    float hw = style.x * s;
    bool thin = hw <= 0.5 * ss;                       // un trait fin fait 1 pixel de SORTIE de large
    float hwp = max(hw, 0.5 * ss);
    float c1 = mod(style.w, 4.0);
    float c2 = floor(style.w / 4.0);
    if (thin && crisp > 0.5 && ss < 1.5 && c1 < 2.5 && c2 < 2.5) {      // pas sur une courbe : un segment calé sur un pixel casserait le tracé
        vec2 dd = b - a;
        if (abs(dd.y) < 1e-3) { float y = floor(a.y) + 0.5; a.y = y; b.y = y; }
        else if (abs(dd.x) < 1e-3) { float x = floor(a.x) + 0.5; a.x = x; b.x = x; }
    }
    float len = length(b - a);
    if (thin && c1 < 2.5) c1 = 0.0;                 // trait fin : bouts francs (sauf joint de courbe)
    if (thin && c2 < 2.5) c2 = 0.0;
    if (len < 0.5 * ss) { if (c1 < 0.5) c1 = 1.0; if (c2 < 0.5) c2 = 1.0; }   // un point : disque
    vec2 d = len > 1e-6 ? (b - a) / len : vec2(1.0, 0.0);
    vec2 n = vec2(-d.y, d.x);
    float ext1 = (c1 > 0.5 && c1 < 1.5 || c1 > 2.5) ? hwp : 0.0;
    float ext2 = (c2 > 0.5 && c2 < 1.5 || c2 > 2.5) ? hwp : 0.0;
    float rr1 = (c1 > 0.5 && c1 < 1.5 || c1 > 2.5) ? hwp : (c1 > 1.5 ? min(style.y * s, hwp) : 0.0);
    float rr2 = (c2 > 0.5 && c2 < 1.5 || c2 > 2.5) ? hwp : (c2 > 1.5 ? min(style.z * s, hwp) : 0.0);
    float pad = 1.0;
    float u = mix(-ext1 - pad, len + ext2 + pad, corner.x);
    float v = corner.y * (hwp + pad);
    vec2 p = a + d * u + n * v;
    v_loc = vec4(u, v, len, hwp);
    v_ext = vec4(ext1, ext2, rr1, rr2);
    v_color = color;
    float yb = luma(background), yc = luma(color.rgb);
    v_lum = vec4(yb, yc, to_srgb(yb), to_srgb(yc));
    gl_Position = vec4(p.x / viewport.x * 2.0 - 1.0, 1.0 - p.y / viewport.y * 2.0, 0.0, 1.0);
}
"""

FRAG = """#version 330 core
in vec4 v_loc;
in vec4 v_ext;
in vec4 v_color;
flat in vec4 v_lum;
uniform float linear_blend;
uniform float antialias;
out vec4 frag;

float to_srgb(float c) { return c <= 0.0031308 ? c * 12.92 : 1.055 * pow(c, 1.0 / 2.4) - 0.055; }

void main() {
    float u = v_loc.x, v = v_loc.y, len = v_loc.z, hw = v_loc.w;
    float u0 = -v_ext.x, u1 = len + v_ext.y;
    float cu = 0.5 * (u0 + u1);
    float hl = 0.5 * (u1 - u0);
    float rr = u < cu ? v_ext.z : v_ext.w;
    rr = min(rr, min(hl, hw));
    vec2 q = abs(vec2(u - cu, v)) - vec2(hl, hw) + rr;       // boite arrondie (rayons propres a chaque bout)
    float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - rr;
    float cov = clamp(0.5 - d, 0.0, 1.0);
    if (antialias < 0.5) cov = step(0.5, cov);
    float a = cov;
    float lb = v_lum.z, lc = v_lum.w;
    if (linear_blend > 0.5 && abs(lc - lb) > 0.02)             // melange en lumiere lineaire (cad_items.linear_blend_table)
        a = clamp((to_srgb(v_lum.x + cov * (v_lum.y - v_lum.x)) - lb) / (lc - lb), 0.0, 1.0);
    a *= v_color.a;
    frag = vec4(v_color.rgb * a, a);                            // premultiplie ; fusion par MAXIMUM
}
"""


COMP_VERT = """#version 330 core
out vec2 uv;
void main() {                                   // un triangle plein ecran, sans tampon
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    uv = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""

TEX_VERT = """#version 330 core
uniform vec2 viewport;                           // pixels de l'appareil
uniform vec2 offset;                             // decalage du contenu : u = pixel - offset
uniform vec2 texsize;
out vec2 uv;
void main() {                                    // plein ecran, bande de 4 sommets, sans tampon
    vec2 c = vec2(float(gl_VertexID & 1), float(gl_VertexID >> 1));
    vec2 px = c * viewport;
    uv = (px - offset) / texsize;                // la texture se REPETE : tampon torique
    gl_Position = vec4(c.x * 2.0 - 1.0, 1.0 - c.y * 2.0, 0.0, 1.0);
}
"""

TEX_FRAG = """#version 330 core
in vec2 uv;
uniform sampler2D tex;
out vec4 frag;
void main() { frag = vec4(texture(tex, uv).rgb, 1.0); }
"""


COMP_FRAG = """#version 330 core
in vec2 uv;
uniform sampler2D tex;
uniform float mimic;                              // 1 : meme rendu qu'une couche translucide (voir `_draw_via_texture`)
out vec4 frag;
void main() {
    vec4 t = texture(tex, uv);                    // premultiplie : pose par (ONE, ONE_MINUS_SRC_ALPHA)
    if (mimic > 0.5) t.rgb *= t.a;
    frag = t;
}
"""


COMP_SS_FRAG = """#version 330 core
uniform sampler2D tex;                           // dessin suréchantillonné : couleur premultipliee (couverture brute)
uniform int ss;                                  // texels par pixel de sortie, par axe
uniform float radius;                            // rayon du filtre en triangle, en pixels de sortie
uniform vec3 background;
uniform float linear_blend;
uniform float mimic;                             // 1 : meme rendu qu'une couche translucide (voir `_draw_via_texture`)
out vec4 frag;

float to_linear(float c) { return c <= 0.04045 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4); }
float to_srgb(float c) { return c <= 0.0031308 ? c * 12.92 : 1.055 * pow(c, 1.0 / 2.4) - 0.055; }
float luma(vec3 c) { return dot(vec3(0.2126, 0.7152, 0.0722), vec3(to_linear(c.r), to_linear(c.g), to_linear(c.b))); }

void main() {
    ivec2 size = textureSize(tex, 0);
    vec2 center = gl_FragCoord.xy;               // centre du pixel de sortie
    ivec2 base = ivec2(floor(center * float(ss)));
    int reach = int(ceil(radius * float(ss)));
    vec4 acc = vec4(0.0);
    float total = 0.0;
    for (int j = -reach; j <= reach; j++) {
        for (int i = -reach; i <= reach; i++) {
            ivec2 at = base + ivec2(i, j);
            vec2 d = (vec2(at) + 0.5) / float(ss) - center;
            float w = max(0.0, 1.0 - abs(d.x) / radius) * max(0.0, 1.0 - abs(d.y) / radius);
            if (w <= 0.0) continue;
            at = clamp(at, ivec2(0), size - 1);
            acc += w * texelFetch(tex, at, 0);
            total += w;
        }
    }
    acc /= max(total, 1e-6);
    if (acc.a < 1e-4) { frag = vec4(0.0); return; }
    vec3 c = acc.rgb / acc.a;
    float cov = acc.a;
    float yb = luma(background), yc = luma(c);
    float lb = to_srgb(yb), lc = to_srgb(yc);
    float a = cov;
    if (linear_blend > 0.5 && abs(lc - lb) > 0.02)
        a = clamp((to_srgb(yb + cov * (yc - yb)) - lb) / (lc - lb), 0.0, 1.0);
    frag = vec4(c * a * (mimic > 0.5 ? a : 1.0), a);   // premultiplie : pose par (ONE, ONE_MINUS_SRC_ALPHA)
}
"""


# ==========================================================================
# Couche OpenGL
# ==========================================================================

def _make_layer_class():
    from PySide6.QtOpenGLWidgets import QOpenGLWidget

    class _Layer(QOpenGLWidget):
        failed = Signal(str)

        def __init__(self, view):
            super().__init__(view)                      # voisine du viewport (ses mises a jour peuvent etre coupees)
            self.view = view
            self.pure = False
            self.tex_mode = False                       # deplacement du board : contenu raster en TEXTURE decalee par le GPU
            self.texture_provider = None                # rappel(rect logique de la vue) -> QImage de cette zone (contenu raster)
            self._tex = None
            self._tex_size = None                       # (largeur, hauteur) de la texture torique, pixels de l'appareil
            self._tex_valid = None                      # zone (x, y, l, h) du contenu deja dans la texture, en « u » (voir plus bas)
            self._tex_zoom = None
            self.fbo_cad = None                         # (fbo, texture, largeur, hauteur) du mode pur
            self.store = GpuStore()
            self.paint_hook = None                      # rappel(painter) : selection, apercus, reticule (QPainter)
            self.under_hook = None                      # rappel(painter, transform) : remplissages (hachures pleines), SOUS les traits
            self.under_bounds = None                    # rappel() -> QRect (viewport) de ce dessin
            self.paint_bounds = None                    # rappel() -> QRect (viewport) qui contient ce dessin ; None = tout
            self.obstacles = lambda: []                 # zones (viewport) des panneaux flottants a laisser libres
            self.broken = False
            self._ready = False
            self._zoom = None
            self._band = None
            self.frame_ms = 0.0
            self._overlay_images = []                  # une image par zone peinte (`_paint_qt`)
            self._under_image = None
            fmt = QSurfaceFormat()
            fmt.setVersion(3, 3)
            fmt.setProfile(QSurfaceFormat.CoreProfile)
            fmt.setAlphaBufferSize(8)
            fmt.setSwapInterval(QSurfaceFormat.defaultFormat().swapInterval())       # celui de la fenetre (`low_latency_format`)
            fmt.setSamples(4)                           # QPainter (selection, elastique, reticule) n anticrenele que sur un tampon multi-echantillons
            self.setFormat(fmt)
            screen = view.screen() if hasattr(view, "screen") else None
            self.pacer = FramePacer(self, screen.refreshRate() if screen is not None else 60.0)
            self.setAttribute(Qt.WA_AlwaysStackOnTop, True)
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setFocusPolicy(Qt.NoFocus)
            self.setGeometry(view.viewport().geometry())
            view.viewport().installEventFilter(self)

        # -- suivi de la vue --
        def eventFilter(self, obj, event):
            from PySide6.QtCore import QEvent
            if event.type() in (QEvent.Resize, QEvent.Move) and obj is self.view.viewport():
                self.setGeometry(obj.geometry())
            return False

        # -- deplacement du board en texture (tout le contenu, pas seulement le CAD) --
        # Le contenu raster du board (fond, grille, post-it, formes, textes… ; le CAD est peint par le GPU) vit dans une
        # TEXTURE TORIQUE de la taille de la vue : le pixel « u » du contenu (u = pixel de la vue - decalage du defilement,
        # independant du defilement) est a la case u modulo la taille. Un pas de deplacement ne rend que les BANDES qui
        # apparaissent (comme le pan raster, `BoardView._pan_paint`) et les envoie au GPU ; l'image est ensuite posee en
        # decalee (la texture se repete). Plus de peinture ni de recomposition de la fenetre par Windows pendant le geste.
        def begin_texture(self):
            if self.pure or self.tex_mode or self.texture_provider is None or not self._ready:
                return False
            ratio = self.devicePixelRatioF() or 1.0
            if abs(ratio - round(ratio)) > 1e-6:
                return False                            # echelle non entiere : les bandes ne tomberaient pas sur des pixels
            self.tex_mode = True
            self._tex_valid = None
            self.setAttribute(Qt.WA_TranslucentBackground, False)
            self.view.viewport().setUpdatesEnabled(False)
            self.request()
            return True

        def end_texture(self):
            if not self.tex_mode:
                return
            self.tex_mode = False
            viewport = self.view.viewport()
            viewport.setUpdatesEnabled(True)
            if not self.pure:
                viewport.repaint()                      # la vue raster est a jour AVANT que la couche redevienne transparente
                self.setAttribute(Qt.WA_TranslucentBackground, True)
            else:
                viewport.setUpdatesEnabled(False)
            self._tex_valid = None
            self.request()

        def stale_texture(self):
            self._tex_valid = None                      # contenu change : tout est refait a la prochaine image

        def _ensure_content_texture(self, width, height):
            GL = self._GL
            size = (width + 16, height + 16)
            if self._tex is not None and self._tex_size == size:
                return
            if self._tex is None:
                self._tex = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._tex)
            for name, value in ((GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST), (GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST),
                                (GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT), (GL.GL_TEXTURE_WRAP_T, GL.GL_REPEAT)):
                GL.glTexParameteri(GL.GL_TEXTURE_2D, name, value)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, size[0], size[1], 0, GL.GL_BGRA, GL.GL_UNSIGNED_BYTE, None)
            self._tex_size = size
            self._tex_valid = None

        @staticmethod
        def _missing(need, have):
            """Parties du rectangle `need` (x, y, l, h) absentes de `have` (ou None) : au plus 2 bandes."""
            if have is None:
                return [need]
            nx, ny, nw, nh = need
            hx, hy, hw, hh = have
            ix0, iy0 = max(nx, hx), max(ny, hy)
            ix1, iy1 = min(nx + nw, hx + hw), min(ny + nh, hy + hh)
            if ix0 >= ix1 or iy0 >= iy1:
                return [need]
            out = []
            if iy0 > ny:
                out.append((nx, ny, nw, iy0 - ny))                  # bande du haut (toute la largeur)
            if iy1 < ny + nh:
                out.append((nx, iy1, nw, ny + nh - iy1))            # bande du bas
            if ix0 > nx:
                out.append((nx, iy0, ix0 - nx, iy1 - iy0))          # a gauche (entre les deux)
            if ix1 < nx + nw:
                out.append((ix1, iy0, nx + nw - ix1, iy1 - iy0))    # a droite
            return out

        def _put_strip(self, ux, uy, image):
            """Image posee a la case (ux, uy) de la texture torique (coupee la ou elle passe d'un bord a l'autre)."""
            GL = self._GL
            tw, th = self._tex_size
            ratio = int(round(self.devicePixelRatioF() or 1.0))
            w, h = image.width(), image.height()
            data = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(h, image.bytesPerLine() // 4, 4)[:, :w]
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._tex)
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            x = 0
            while x < w:
                tx = (ux + x) % tw
                run_w = min(w - x, tw - tx)
                y = 0
                while y < h:
                    ty = (uy + y) % th
                    run_h = min(h - y, th - ty)
                    block = np.ascontiguousarray(data[y:y + run_h, x:x + run_w])
                    GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, tx, ty, run_w, run_h, GL.GL_BGRA, GL.GL_UNSIGNED_BYTE, block)
                    y += run_h
                x += run_w
            del ratio

        def _draw_content_texture(self, vt, ratio, width, height):
            """Met a jour les bandes qui manquent, puis pose le contenu decale du defilement."""
            GL = self._GL
            self._ensure_content_texture(width, height)
            dxd, dyd = int(round(vt.dx() * ratio)), int(round(vt.dy() * ratio))
            if self._tex_zoom != vt.m11():
                self._tex_zoom = vt.m11()
                self._tex_valid = None
            need = (-dxd, -dyd, width, height)                      # contenu visible, en « u »
            r = int(round(ratio))
            for x, y, w, h in self._missing(need, self._tex_valid):
                # zone de la vue (pixels logiques entiers, arrondie vers l'exterieur)
                lx0, ly0 = (x + dxd) // r, (y + dyd) // r
                lx1, ly1 = -((-(x + dxd + w)) // r), -((-(y + dyd + h)) // r)
                rect = QRect(lx0, ly0, lx1 - lx0, ly1 - ly0).intersected(self.view.viewport().rect())
                if rect.isEmpty():
                    continue
                image = self.texture_provider(rect)
                if image is None:
                    continue
                self._put_strip(rect.x() * r - dxd, rect.y() * r - dyd, image)
            self._tex_valid = need
            GL.glUseProgram(self.tex_prog)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._tex)
            GL.glUniform2f(self.tex_u["viewport"], float(width), float(height))
            GL.glUniform2f(self.tex_u["offset"], float(dxd), float(dyd))
            GL.glUniform2f(self.tex_u["texsize"], float(self._tex_size[0]), float(self._tex_size[1]))
            GL.glUniform1i(self.tex_u["tex"], 0)
            GL.glDisable(GL.GL_BLEND)
            GL.glBindVertexArray(self.empty_vao)
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
            GL.glBindVertexArray(0)
            GL.glUseProgram(0)

        def set_pure(self, on: bool):
            """Mode « pur CAD » (voir l'en-tete) : fond + grille sur le GPU, vue raster figee."""
            if on == self.pure:
                return
            self.pure = on
            if self.tex_mode:
                return
            self.setAttribute(Qt.WA_TranslucentBackground, not on)
            viewport = self.view.viewport()
            viewport.setUpdatesEnabled(not on)
            if not on:
                viewport.update()
            self.request()

        def request(self):
            if self.isVisible():
                self.pacer.request()                    # une image par balayage, juste avant la composition

        # -- OpenGL --
        def initializeGL(self):
            try:
                from OpenGL import GL
                from OpenGL.GL import shaders
                self._GL = GL
                self.prog = shaders.compileProgram(shaders.compileShader(VERT, GL.GL_VERTEX_SHADER),
                                                   shaders.compileShader(FRAG, GL.GL_FRAGMENT_SHADER))
                self.vao = GL.glGenVertexArrays(1)
                GL.glBindVertexArray(self.vao)
                quad = np.array([0, -1, 1, -1, 0, 1, 1, 1], dtype=np.float32)
                self.quad = GL.glGenBuffers(1)
                GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.quad)
                GL.glBufferData(GL.GL_ARRAY_BUFFER, quad.nbytes, quad, GL.GL_STATIC_DRAW)
                GL.glEnableVertexAttribArray(0)
                GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, False, 8, None)
                GL.glBindVertexArray(0)
                self.uniforms = {name: GL.glGetUniformLocation(self.prog, name) for name in (
                    "scale", "offset", "viewport", "crisp", "background", "linear_blend", "antialias", "ss")}
                self.grid_vao = GL.glGenVertexArrays(1)           # grille : memes instances, tampon refait a chaque image
                self.grid_vbo = GL.glGenBuffers(1)
                GL.glBindVertexArray(self.grid_vao)
                GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.quad)
                GL.glEnableVertexAttribArray(0)
                GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, False, 8, None)
                GL.glBindVertexArray(0)
                self.comp = shaders.compileProgram(shaders.compileShader(COMP_VERT, GL.GL_VERTEX_SHADER),
                                                   shaders.compileShader(COMP_FRAG, GL.GL_FRAGMENT_SHADER))
                self.comp_ss = shaders.compileProgram(shaders.compileShader(COMP_VERT, GL.GL_VERTEX_SHADER),
                                                      shaders.compileShader(COMP_SS_FRAG, GL.GL_FRAGMENT_SHADER))
                self.tex_prog = shaders.compileProgram(shaders.compileShader(TEX_VERT, GL.GL_VERTEX_SHADER),
                                                       shaders.compileShader(TEX_FRAG, GL.GL_FRAGMENT_SHADER))
                self.tex_u = {name: GL.glGetUniformLocation(self.tex_prog, name) for name in ("viewport", "offset", "texsize", "tex")}
                self.empty_vao = GL.glGenVertexArrays(1)
                self.max_texture = int(GL.glGetIntegerv(GL.GL_MAX_TEXTURE_SIZE))
                self._ready = True
            except Exception as exc:                     # noqa: BLE001 - pilote sans OpenGL 3.3 : secours raster
                self.broken = True
                self.failed.emit(str(exc))

        def _bind(self, chunk: Chunk):
            GL = self._GL
            GL.glBindVertexArray(self.vao)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, chunk.vbo)
            stride = FLOATS * 4
            for loc, size, off in ((1, 4, 0), (2, 4, 16), (3, 4, 32)):
                GL.glEnableVertexAttribArray(loc)
                GL.glVertexAttribPointer(loc, size, GL.GL_FLOAT, False, stride, GL.ctypes.c_void_p(off))
                GL.glVertexAttribDivisor(loc, 1)

        def _sync(self, scene):
            """Lots refaits (processeur) puis envoyes (GPU) : seulement ceux dont une entite a change."""
            from .cad_items import tess_band
            GL = self._GL
            store = self.store
            band = tess_band(scene)
            if band != self._band:
                self._band = band
                for chunk in store.chunks:              # seules les courbes sont refaites (cle du cache : `build`)
                    chunk.dirty = True
            tol = 0.12 / band
            deadline = time.perf_counter() + SYNC_BUDGET_S
            late = False
            for chunk in store.chunks:
                if not chunk.dirty:
                    continue
                if late:
                    continue
                data = store.build(chunk, tol, band, deadline if chunk.vbo is not None else None)
                if data is PENDING:
                    late = True                         # reste a refaire : image suivante (l'ancien dessin reste)
                    continue
                chunk.dirty = False
                if data is None:
                    if chunk.vbo is not None:
                        GL.glDeleteBuffers(1, [chunk.vbo])
                        chunk.vbo = None
                    continue
                if chunk.vbo is None:
                    chunk.vbo = GL.glGenBuffers(1)
                GL.glBindBuffer(GL.GL_ARRAY_BUFFER, chunk.vbo)
                GL.glBufferData(GL.GL_ARRAY_BUFFER, data.nbytes, data, GL.GL_DYNAMIC_DRAW)
            for chunk in store.chunks:
                if not chunk.items and chunk.vbo is not None:
                    GL.glDeleteBuffers(1, [chunk.vbo])
                    chunk.vbo = None
            store.prune()
            if late:
                self.update()

        def paintGL(self):
            try:
                self._paint_gl()
            except Exception as exc:                      # noqa: BLE001 - jamais un ecran noir permanent
                self._paint_failed(exc)

        def _paint_failed(self, exc):
            """Une image a echoue : couche videe (transparente, les panneaux restent visibles) ; plusieurs de suite = retour
            au rendu du processeur (`failed`)."""
            import traceback
            traceback.print_exc()
            self._errors = getattr(self, '_errors', 0) + 1
            try:
                GL = self._GL
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
                GL.glDisable(GL.GL_SCISSOR_TEST)
                GL.glClearColor(0.0, 0.0, 0.0, 0.0)
                GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            except Exception:                           # noqa: BLE001
                pass
            if self._errors >= 3 and not self.broken:
                self.broken = True
                self.failed.emit(f'erreur de dessin : {exc}')

        def _paint_gl(self):
            t0 = time.perf_counter()
            GL = self._GL if self._ready else None
            if GL is None:
                return
            view = self.view
            scene = view.scene()
            ratio = self.devicePixelRatioF() or 1.0
            width, height = int(self.width() * ratio), int(self.height() * ratio)
            fbo = self.defaultFramebufferObject()
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
            GL.glViewport(0, 0, width, height)
            GL.glDisable(GL.GL_SCISSOR_TEST)
            bg = QColor(getattr(scene, "background", QColor("#ffffff")))
            if self.pure or self.tex_mode:
                GL.glClearColor(bg.redF(), bg.greenF(), bg.blueF(), 1.0)
            else:
                GL.glClearColor(0.0, 0.0, 0.0, 0.0)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            vt = view.viewportTransform()
            zoom = vt.m11()
            if zoom != self._zoom:
                self._zoom = zoom
                self.store.zoom_changed(zoom, float(getattr(scene, "cad_dense_px", 4.0)))
            self._sync(scene)
            if self.tex_mode:
                self._draw_content_texture(vt, ratio, width, height)
            if self.pure and scene.page.get("grid", True):
                self._draw_grid(scene, vt, zoom, ratio, width, height)
            if self.pure and self.under_hook is not None:
                self._paint_under(GL, fbo, vt, width, height)
            if any(c.count for c in self.store.chunks):
                ss = self._supersampling(scene, width, height)
                if self.pure or self.tex_mode or ss > 1:
                    self._draw_via_texture(scene, vt, zoom, ratio, width, height, ss)
                else:
                    self._draw(scene, vt, zoom, ratio, width, height)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
            self._paint_qt(scene, vt)
            self._clear_obstacles(GL, ratio, height)
            self.frame_ms = (time.perf_counter() - t0) * 1000.0
            self._errors = 0

        # -- mode pur : grille et composition --
        def _grid_rows(self, scene, vt, zoom, ratio, width, height):
            """Lignes de la grille du board (instances en PIXELS de l'appareil) : un pixel net par ligne, niveaux
            fondus comme `scene._paint_grid_fast` ; axes de la grille a la suite."""
            look = scene.grid_look
            levels, _period, ink, strength = scene._grid_levels(zoom)
            s = zoom * ratio
            ox, oy = scene.grid_origin()
            dx, dy = vt.dx() * ratio, vt.dy() * ratio
            thick = max(1, int(look["thickness"]))
            hw = thick / 2.0
            parts = []
            r, g, b = ink.redF(), ink.greenF(), ink.blueF()
            for step, gain in levels:
                alpha = min(1.0, strength * gain)
                k0, k1 = math.ceil((-dx / s - ox) / step), math.floor(((width - dx) / s - ox) / step)
                j0, j1 = math.ceil((-dy / s - oy) / step), math.floor(((height - dy) / s - oy) / step)
                if (k1 - k0) + (j1 - j0) > 4000:
                    return None                               # jamais a l'apparition des niveaux : trop de lignes
                xs = np.floor((ox + np.arange(k0, k1 + 1) * step) * s + dx + 0.5) + hw
                ys = np.floor((oy + np.arange(j0, j1 + 1) * step) * s + dy + 0.5) + hw
                col = np.array([r, g, b, alpha])
                if len(xs):
                    block = np.zeros((len(xs), FLOATS))
                    block[:, 0], block[:, 2], block[:, 3], block[:, 4] = xs, xs, height, hw
                    block[:, 8:12] = col
                    parts.append(block)
                if len(ys):
                    block = np.zeros((len(ys), FLOATS))
                    block[:, 1], block[:, 3], block[:, 2], block[:, 4] = ys, ys, width, hw
                    block[:, 8:12] = col
                    parts.append(block)
            if look["axes"]:
                axes = QColor(look["axes_color"])
                at = max(1, int(look["axes_thickness"]))
                x = math.floor(ox * s + dx + 0.5) + at / 2.0
                y = math.floor(oy * s + dy + 0.5) + at / 2.0
                color = [axes.redF(), axes.greenF(), axes.blueF(), axes.alphaF()]
                if 0 <= x <= width:
                    parts.append(np.array([[x, 0, x, height, at / 2.0, 0, 0, 0, *color]]))
                if 0 <= y <= height:
                    parts.append(np.array([[0, y, width, y, at / 2.0, 0, 0, 0, *color]]))
            if not parts:
                return np.zeros((0, FLOATS), dtype=np.float32)
            return np.concatenate(parts).astype(np.float32)

        def _set_uniforms(self, scene, scale, offset, width, height, crisp, linear, ss=1.0):
            GL = self._GL
            u = self.uniforms
            GL.glUseProgram(self.prog)
            GL.glUniform2f(u["scale"], scale, scale)
            GL.glUniform2f(u["offset"], *offset)
            GL.glUniform2f(u["viewport"], float(width), float(height))
            GL.glUniform1f(u["crisp"], 1.0 if crisp else 0.0)
            GL.glUniform1f(u["ss"], float(ss))
            GL.glUniform1f(u["linear_blend"], 1.0 if linear else 0.0)
            GL.glUniform1f(u["antialias"], 1.0 if getattr(scene, "cad_antialiasing", True) else 0.0)
            bg = QColor(getattr(scene, "background", QColor("#ffffff")))
            GL.glUniform3f(u["background"], bg.redF(), bg.greenF(), bg.blueF())

        def _draw_grid(self, scene, vt, zoom, ratio, width, height):
            GL = self._GL
            rows = self._grid_rows(scene, vt, zoom, ratio, width, height)
            if rows is None or not len(rows):
                return
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendEquation(GL.GL_FUNC_ADD)
            GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
            self._set_uniforms(scene, 1.0, (0.0, 0.0), width, height, False, False)
            GL.glBindVertexArray(self.grid_vao)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.grid_vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, rows.nbytes, rows, GL.GL_STREAM_DRAW)
            stride = FLOATS * 4
            for loc, size, off in ((1, 4, 0), (2, 4, 16), (3, 4, 32)):
                GL.glEnableVertexAttribArray(loc)
                GL.glVertexAttribPointer(loc, size, GL.GL_FLOAT, False, stride, GL.ctypes.c_void_p(off))
                GL.glVertexAttribDivisor(loc, 1)
            GL.glDrawArraysInstanced(GL.GL_TRIANGLE_STRIP, 0, 4, len(rows))
            GL.glBindVertexArray(0)
            GL.glDisable(GL.GL_BLEND)
            GL.glUseProgram(0)

        def _supersampling(self, scene, width, height) -> int:
            """Texels par pixel de sortie et par axe (reglage « anticrenelage » : n echantillons = ceil(racine(n)) par axe),
            limites par la taille de texture du pilote et ~64 Mpixels de memoire."""
            wanted = int(getattr(scene, "cad_samples", 1) or 1)
            ss = max(1, int(math.ceil(math.sqrt(wanted))))
            limit = max(1, self.max_texture // max(width, height, 1))
            memory = max(1, int(math.sqrt(64e6 / max(width * height, 1))))
            return max(1, min(ss, limit, memory))

        def _ensure_texture(self, width, height):
            GL = self._GL
            if self.fbo_cad is not None and self.fbo_cad[2:] == (width, height):
                return self.fbo_cad
            if self.fbo_cad is not None:
                GL.glDeleteFramebuffers(1, [self.fbo_cad[0]])
                GL.glDeleteTextures(1, [self.fbo_cad[1]])
            texture = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, width, height, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
            fbo = GL.glGenFramebuffers(1)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
            GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, texture, 0)
            self.fbo_cad = (fbo, texture, width, height)
            return self.fbo_cad

        def _draw_via_texture(self, scene, vt, zoom, ratio, width, height, ss=1):
            """Entites dans une texture (fusion par MAXIMUM, couverture seule), puis posees sur la grille. `ss` > 1 :
            texture `ss` fois plus fine par axe (suréchantillonnage), ramenee a la taille de l'ecran par un filtre en
            triangle qui lisse l'escalier des traits fins (puis le melange en lumiere lineaire, ici)."""
            GL = self._GL
            fbo, texture, _w, _h = self._ensure_texture(width * ss, height * ss)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
            GL.glViewport(0, 0, width * ss, height * ss)
            GL.glClearColor(0.0, 0.0, 0.0, 0.0)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            self._draw(scene, vt, zoom, ratio, width, height, ss)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
            GL.glViewport(0, 0, width, height)
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendEquation(GL.GL_FUNC_ADD)
            GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
            program = self.comp_ss if ss > 1 else self.comp
            GL.glUseProgram(program)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
            GL.glUniform1i(GL.glGetUniformLocation(program, "tex"), 0)
            # Une couche TRANSLUCENTE est composee par Qt en alpha droit (la couleur deja multipliee par l'alpha l'est une
            # 2e fois : traits un peu plus fins que le rendu du processeur, mesure) ; pendant un deplacement la couche est
            # opaque : meme rendu reproduit ici pour que le trait ne change pas d'epaisseur au debut / a la fin du geste.
            GL.glUniform1f(GL.glGetUniformLocation(program, "mimic"), 1.0 if (self.tex_mode and not self.pure) else 0.0)
            if ss > 1:
                GL.glUniform1i(GL.glGetUniformLocation(program, "ss"), int(ss))
                radius = float(getattr(scene, "cad_filter", FILTER_RADIUS * 100.0)) / 100.0
                GL.glUniform1f(GL.glGetUniformLocation(program, "radius"), max(0.5, min(2.0, radius)))
                bg = QColor(getattr(scene, "background", QColor("#ffffff")))
                GL.glUniform3f(GL.glGetUniformLocation(program, "background"), bg.redF(), bg.greenF(), bg.blueF())
                GL.glUniform1f(GL.glGetUniformLocation(program, "linear_blend"),
                               1.0 if getattr(scene, "cad_linear_blend", True) else 0.0)
            GL.glBindVertexArray(self.empty_vao)
            GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
            GL.glBindVertexArray(0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glDisable(GL.GL_BLEND)
            GL.glUseProgram(0)

        def _draw(self, scene, vt, zoom, ratio, width, height, ss=1):
            GL = self._GL
            u = self.uniforms
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendEquation(GL.GL_MAX)
            s = zoom * ratio * ss
            self._set_uniforms(scene, s, (0.0, 0.0), width * ss, height * ss, getattr(scene, "cad_crisp", True),
                               getattr(scene, "cad_linear_blend", True) and ss == 1, ss)
            view_rect = (-vt.dx() / zoom, -vt.dy() / zoom, (self.width() - vt.dx()) / zoom,
                         (self.height() - vt.dy()) / zoom)
            for chunk in self.store.chunks:
                if not chunk.count or chunk.vbo is None or chunk.bounds is None:
                    continue
                b = chunk.bounds
                if b[2] < view_rect[0] or b[0] > view_rect[2] or b[3] < view_rect[1] or b[1] > view_rect[3]:
                    continue                                 # lot hors de l'ecran
                ox = (chunk.origin[0] * zoom + vt.dx()) * ratio * ss  # double precision : calculs du processeur
                oy = (chunk.origin[1] * zoom + vt.dy()) * ratio * ss
                GL.glUniform2f(u["offset"], ox, oy)
                self._bind(chunk)
                GL.glDrawArraysInstanced(GL.GL_TRIANGLE_STRIP, 0, 4, chunk.count)
            GL.glBindVertexArray(0)
            GL.glBlendEquation(GL.GL_FUNC_ADD)
            GL.glDisable(GL.GL_BLEND)
            GL.glUseProgram(0)

        def _paint_under(self, GL, fbo, vt, width, height):
            """Remplissages des hachures pleines (peints par QPainter) entre la grille et les traits."""
            bounds = self.under_bounds() if self.under_bounds is not None else self.rect()
            area = self.rect().intersected(bounds)
            if area.isEmpty():
                return
            ratio = self.devicePixelRatioF()
            size = (max(1, int(area.width() * ratio)), max(1, int(area.height() * ratio)))
            image = self._under_image
            if image is None or (image.width(), image.height()) != size:
                image = self._under_image = QImage(size[0], size[1], QImage.Format_ARGB32_Premultiplied)
                image.setDevicePixelRatio(ratio)
            image.fill(0)
            raster = QPainter(image)
            raster.setRenderHint(QPainter.Antialiasing, True)
            raster.translate(-area.x(), -area.y())
            try:
                self.under_hook(raster, vt)
            finally:
                raster.end()
            painter = QPainter(self)
            try:
                painter.drawImage(area.topLeft(), image)
            finally:
                painter.end()
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)       # QPainter laisse son etat : le notre est repose
            GL.glViewport(0, 0, width, height)
            GL.glDisable(GL.GL_SCISSOR_TEST)
            GL.glDisable(GL.GL_BLEND)
            GL.glUseProgram(0)

        def _paint_qt(self, scene, vt):
            """Selection, apercus, reticule, infobulles : QPainter par-dessus le trace GPU."""
            hook = self.paint_hook
            if hook is None:
                return
            areas = [self.rect()]
            if self.paint_bounds is not None:
                found = self.paint_bounds()             # seules les zones qui contiennent du dessin (une ou plusieurs)
                areas = [self.rect().intersected(r) for r in (found if isinstance(found, list) else [found])]
            areas = [r for r in areas if not r.isEmpty()]
            if not areas:
                return
            ratio = self.devicePixelRatioF()
            images = self._overlay_images
            painter = QPainter(self)
            try:
                for index, area in enumerate(areas):
                    size = (max(1, int(area.width() * ratio)), max(1, int(area.height() * ratio)))
                    image = images[index] if index < len(images) else None
                    if image is None or (image.width(), image.height()) != size:
                        image = QImage(size[0], size[1], QImage.Format_ARGB32_Premultiplied)
                        image.setDevicePixelRatio(ratio)
                        if index < len(images):
                            images[index] = image
                        else:
                            images.append(image)
                    image.fill(0)
                    raster = QPainter(image)            # moteur raster de Qt : couverture exacte (le moteur GL de Qt
                    raster.setRenderHint(QPainter.Antialiasing, True)   # ne donne que 4 niveaux, tirets baves)
                    raster.translate(-area.x(), -area.y())
                    try:
                        hook(raster, vt)
                    finally:
                        raster.end()
                    painter.drawImage(area.topLeft(), image)
            finally:
                painter.end()
            self._overlay_images = images[:len(areas)]

        def _clear_obstacles(self, GL, ratio, height):
            """Zones des panneaux flottants (widgets AU-DESSUS de la vue) : rien du CAD n'y est dessine."""
            rects = self.obstacles()
            if not rects:
                return
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
            GL.glEnable(GL.GL_SCISSOR_TEST)
            GL.glClearColor(0.0, 0.0, 0.0, 0.0)
            for r in rects:
                x, y = int(r.x() * ratio), int((self.height() - r.y() - r.height()) * ratio)
                GL.glScissor(x, y, int(math.ceil(r.width() * ratio)), int(math.ceil(r.height() * ratio)))
                GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            GL.glDisable(GL.GL_SCISSOR_TEST)

        def release(self):
            """Tampons liberes (contexte courant) avant la destruction."""
            if not self._ready:
                return
            self.makeCurrent()
            try:
                GL = self._GL
                for chunk in self.store.chunks:
                    if chunk.vbo is not None:
                        GL.glDeleteBuffers(1, [chunk.vbo])
                        chunk.vbo = None
                if self.fbo_cad is not None:
                    GL.glDeleteFramebuffers(1, [self.fbo_cad[0]])
                    GL.glDeleteTextures(1, [self.fbo_cad[1]])
                    self.fbo_cad = None
            finally:
                self.doneCurrent()

    return _Layer


_LAYER_CLASS = None


def create_layer(view):
    """La couche GPU de `view` (None si PyOpenGL / QOpenGLWidget manquent)."""
    global _LAYER_CLASS
    if not available():
        return None
    if _LAYER_CLASS is None:
        _LAYER_CLASS = _make_layer_class()
    return _LAYER_CLASS(view)
