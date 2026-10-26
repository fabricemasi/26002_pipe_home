"""PROTOTYPE du moteur GPU du CAD (mesure seulement, rien de l'appli n'en depend) : N segments en instances, dessines
par SDF dans un QOpenGLWidget transparent posé sur un fond raster, pan / zoom = une matrice. Mesure l'intervalle entre
images (frameSwapped) et le temps de paintGL.

    QT_QPA_PLATFORM=windows python tests/_proto_gpu_cad.py [N] [secondes] [swap 0|1] [shot.png]
"""
import math
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QSurfaceFormat  # noqa: E402
from PySide6.QtOpenGLWidgets import QOpenGLWidget  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
SWAP = int(sys.argv[3]) if len(sys.argv) > 3 else 1
SHOT = sys.argv[4] if len(sys.argv) > 4 else ""

VERT = """#version 330 core
layout(location=0) in vec2 corner;          // (0..1 le long de l'axe, -1..1 en travers)
layout(location=1) in vec4 seg;             // a.xy, b.xy (monde)
layout(location=2) in vec2 style;           // demi-epaisseur (monde), reserve
layout(location=3) in vec4 color;
uniform vec2 scale;                          // pixels par unite
uniform vec2 offset;                         // pixels
uniform vec2 viewport;
out vec2 v_local;                            // pixels : (u le long, v en travers) depuis a
out float v_len;
out float v_half;
out vec4 v_color;
void main() {
    vec2 a = seg.xy * scale + offset;
    vec2 b = seg.zw * scale + offset;
    float hw = max(style.x * scale.x, 0.5);
    float len = length(b - a);
    vec2 d = len > 1e-6 ? (b - a) / len : vec2(1.0, 0.0);
    vec2 n = vec2(-d.y, d.x);
    float pad = 1.0;
    float u = mix(-hw - pad, len + hw + pad, corner.x);
    float v = corner.y * (hw + pad);
    vec2 p = a + d * u + n * v;
    v_local = vec2(u, v);
    v_len = len;
    v_half = hw;
    v_color = color;
    gl_Position = vec4(p.x / viewport.x * 2.0 - 1.0, 1.0 - p.y / viewport.y * 2.0, 0.0, 1.0);
}
"""

FRAG = """#version 330 core
in vec2 v_local;
in float v_len;
in float v_half;
in vec4 v_color;
out vec4 frag;
void main() {
    float u = clamp(v_local.x, 0.0, v_len);                 // capsule : bouts arrondis (SDF)
    float d = length(vec2(v_local.x - u, v_local.y));
    float cov = clamp(v_half + 0.5 - d, 0.0, 1.0);
    frag = vec4(v_color.rgb * cov, cov);                    // premultiplie ; fusion par MAX
}
"""


class Layer(QOpenGLWidget):
    def __init__(self, parent, segments):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        fmt.setAlphaBufferSize(8)
        fmt.setSwapInterval(SWAP)
        self.setFormat(fmt)
        self.setAttribute(Qt.WA_AlwaysStackOnTop, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.segments = segments
        self.zoom = 1.0
        self.pan = np.array([0.0, 0.0])
        self.paint_ms = []
        self.swaps = []
        self.frameSwapped.connect(lambda: self.swaps.append(time.perf_counter()))

    def initializeGL(self):
        from OpenGL import GL
        from OpenGL.GL import shaders
        GL.glDisable(GL.GL_DEPTH_TEST)
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
        data = self.segments
        self.inst = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.inst)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, data.nbytes, data, GL.GL_STATIC_DRAW)
        stride = data.shape[1] * 4
        for loc, size, off in ((1, 4, 0), (2, 2, 16), (3, 4, 24)):
            GL.glEnableVertexAttribArray(loc)
            GL.glVertexAttribPointer(loc, size, GL.GL_FLOAT, False, stride, GL.ctypes.c_void_p(off))
            GL.glVertexAttribDivisor(loc, 1)
        GL.glBindVertexArray(0)

    def paintGL(self):
        from OpenGL import GL
        t0 = time.perf_counter()
        ratio = self.devicePixelRatioF()
        w, h = self.width() * ratio, self.height() * ratio
        GL.glViewport(0, 0, int(w), int(h))
        GL.glClearColor(0, 0, 0, 0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendEquation(GL.GL_MAX)                       # couvertures qui se chevauchent : maximum
        GL.glUseProgram(self.prog)
        GL.glUniform2f(GL.glGetUniformLocation(self.prog, "scale"), self.zoom * ratio, self.zoom * ratio)
        GL.glUniform2f(GL.glGetUniformLocation(self.prog, "offset"), self.pan[0] * ratio, self.pan[1] * ratio)
        GL.glUniform2f(GL.glGetUniformLocation(self.prog, "viewport"), w, h)
        GL.glBindVertexArray(self.vao)
        GL.glDrawArraysInstanced(GL.GL_TRIANGLE_STRIP, 0, 4, len(self.segments))
        GL.glBindVertexArray(0)
        GL.glBlendEquation(GL.GL_FUNC_ADD)
        GL.glDisable(GL.GL_BLEND)
        GL.glUseProgram(0)
        if os.environ.get("QPAINT"):                     # QPainter par-dessus le trace brut (selection, apercus, reticule)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.fillRect(100, 100, 200, 80, QColor("#ff0000"))
            painter.drawText(110, 140, "QPainter dans paintGL")
            painter.end()
        self.paint_ms.append((time.perf_counter() - t0) * 1000)


class Back(QWidget):
    """Fond raster (comme la scene du board : grille + fond)."""

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#f2f2f2"))
        p.setPen(QColor("#e2e2e2"))
        for x in range(0, self.width(), 32):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 32):
            p.drawLine(0, y, self.width(), y)


def main():
    app = QApplication([])
    side = int(math.sqrt(N))
    rng = np.random.default_rng(1)
    rows = []
    for n in range(N):
        x, y = (n % side) * 20.0, (n // side) * 20.0
        rows.append([x, y, x + 15.0, y + 9.0 + (n % 7), 0.0 if n % 5 else 1.5, 0.0, 0.1, 0.1, 0.1, 1.0])
    data = np.array(rows, dtype=np.float32)
    host = QWidget()
    screen = app.primaryScreen().availableGeometry()
    host.resize(min(2400, screen.width() - 80), min(1300, screen.height() - 80))
    host.move(screen.left() + 40, screen.top() + 40)
    back = Back(host)
    back.resize(host.size())
    layer = Layer(host, data)
    layer.resize(host.size())
    layer.zoom = 2.0
    host.show()
    t_end = time.perf_counter() + 1.0
    while time.perf_counter() < t_end:
        app.processEvents()
    layer.paint_ms.clear()
    layer.swaps.clear()
    start = time.perf_counter()
    state = {"n": 0}

    def tick():
        state["n"] += 1
        t = time.perf_counter() - start
        layer.pan = np.array([-300 + 250 * math.sin(t * 1.3), -200 + 150 * math.sin(t * 0.9)])
        layer.zoom = 2.0 * (1.0 + 0.3 * math.sin(t * 0.7))
        layer.update()
        if t > SECONDS:
            timer.stop()
    timer = QTimer()
    timer.setTimerType(Qt.PreciseTimer)
    timer.timeout.connect(tick)
    timer.start(1)
    while timer.isActive():
        app.processEvents()
    t_end = time.perf_counter() + 0.3
    while time.perf_counter() < t_end:
        app.processEvents()
    if SHOT:
        host.grab().save(SHOT)
    gaps = np.diff(layer.swaps) * 1000 if len(layer.swaps) > 2 else np.array([0.0])
    paint = np.array(layer.paint_ms)
    print(f"{N} segments, swapInterval={SWAP}, {len(layer.swaps)} images en {SECONDS:.0f} s")
    print(f"  intervalle entre images : p50 {np.percentile(gaps, 50):.1f}  p95 {np.percentile(gaps, 95):.1f}  "
          f"max {gaps.max():.1f} ms")
    print(f"  paintGL (processeur)    : p50 {np.percentile(paint, 50):.2f}  p95 {np.percentile(paint, 95):.2f} ms")


main()
