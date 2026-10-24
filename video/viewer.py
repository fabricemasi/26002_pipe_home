"""Affichage du module vidéo : image TOUJOURS centrée dans la zone (la surimpression d'infos se pose PAR-DESSUS,
elle ne la pousse jamais), zoom autour du curseur, déplacement, ajusté / 1:1 (pixels physiques : écrans HiDPI).

Deux moteurs, même interface (`set_frame`, `set_pipeline`, `set_view_state`, zoom) :
- `GLViewer` (QOpenGLWidget, OpenGL 3.3 core, PyOpenGL) : l'image est envoyée telle quelle au GPU (8 / 16 bits
  entiers, half, float — jamais réduite à 8 bits) et TOUT le pipeline couleur (OCIO entrée / affichage, corrections,
  LUT, niveaux, canal, écrêtage, alpha) tourne dans le shader : temps réel même sur des EXR 4K.
- `CPUViewer` (repli sans OpenGL) : le même calcul en numpy (`color.process_np`) sur la partie visible, à la taille
  de l'écran.
`create_viewer(préférence)` choisit."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QSurfaceFormat
from PySide6.QtWidgets import QWidget

from video import color as vcolor

# ==========================================================================
# Géométrie commune : centrage, zoom, déplacement
# ==========================================================================


class _ViewMixin:
    """Signaux déclarés par chaque classe concrète : zoomChanged(float), pixelHovered(x, y) (-1 hors image),
    viewClicked()."""

    def _init_view(self):
        self._img_w = self._img_h = 0
        self._par = 1.0
        self._mode = "fit"                   # « fit » : suit la zone ; « smart » : idem sans agrandir ; « free »
        self._scale = 1.0                    # pixels PHYSIQUES par pixel de l'image
        self._pan = QPointF(0, 0)            # décalage (logique) depuis la position centrée
        self._drag = None
        self.wheel_zoom = True
        self.zoom_step = 1.25
        self.pan_bounded = True
        self.fit_margin = 0
        self._region_mode = False            # capture d'une zone : le glisser trace un rectangle
        self._band = None                    # QRubberBand du tracé
        self._region_start = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # -- géométrie --

    def _dpr(self) -> float:
        return float(self.devicePixelRatioF() or 1.0)

    def image_size(self) -> tuple[int, int]:
        return self._img_w, self._img_h

    def set_image_size(self, width: int, height: int, par: float = 1.0):
        changed = (width, height, par) != (self._img_w, self._img_h, self._par)
        self._img_w, self._img_h, self._par = int(width), int(height), float(par or 1.0)
        if changed:
            if self._mode in ("fit", "smart"):
                self._scale = self._auto_scale()
            self._clamp_pan()

    def fit_scale(self) -> float:
        if not self._img_w or not self._img_h:
            return 1.0
        dpr = self._dpr()
        m = self.fit_margin
        w = max(1.0, (self.width() - 2 * m) * dpr)
        h = max(1.0, (self.height() - 2 * m) * dpr)
        return max(1e-4, min(w / (self._img_w * self._par), h / self._img_h))

    def _auto_scale(self) -> float:
        """Zoom des modes automatiques : « fit » ajuste toujours ; « smart » ajuste une image plus grande que la zone
        et montre une image plus petite à 100 % (jamais agrandie : elle resterait nette)."""
        scale = self.fit_scale()
        return min(1.0, scale) if self._mode == "smart" else scale

    def smart(self):
        """Zoom initial intelligent : réduite pour tenir dans la zone si elle est plus grande, sinon 1:1."""
        self._mode = "smart"
        self._scale = self._auto_scale()
        self._pan = QPointF(0, 0)
        self._changed()

    def zoom(self) -> float:
        return self._scale

    def zoom_mode(self) -> str:
        return self._mode

    def image_rect(self) -> QRectF:
        """Place de l'image (coordonnées logiques du widget) : centrée, plus le déplacement."""
        dpr = self._dpr()
        s = self._scale / dpr
        w, h = self._img_w * self._par * s, self._img_h * s
        cx = self.width() / 2.0 + self._pan.x()
        cy = self.height() / 2.0 + self._pan.y()
        # Coin calé sur un pixel PHYSIQUE : à 100 %, chaque pixel de l'image tombe sur un pixel de l'écran (un
        # demi-pixel de décalage mélangeait chaque pixel avec son voisin : image floue).
        left = round((cx - w / 2.0) * dpr) / dpr
        top = round((cy - h / 2.0) * dpr) / dpr
        return QRectF(left, top, w, h)

    def map_to_image(self, pos: QPointF):
        rect = self.image_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return None
        x = (pos.x() - rect.left()) / rect.width() * self._img_w
        y = (pos.y() - rect.top()) / rect.height() * self._img_h
        if 0 <= x < self._img_w and 0 <= y < self._img_h:
            return int(x), int(y)
        return None

    def fit(self):
        self._mode = "fit"
        self._scale = self.fit_scale()
        self._pan = QPointF(0, 0)
        self._changed()

    def one_to_one(self, anchor: QPointF | None = None):
        self.set_zoom(1.0, anchor)

    def recenter(self):
        self._pan = QPointF(0, 0)
        self._changed()

    def set_zoom(self, scale: float, anchor: QPointF | None = None):
        """Zoom `scale` (pixels physiques / pixel image), le point de l'image sous `anchor` reste en place."""
        scale = max(0.01, min(64.0, float(scale)))
        if anchor is None:
            anchor = QPointF(self.width() / 2.0, self.height() / 2.0)
        rect = self.image_rect()
        old = self._scale / self._dpr()
        new = scale / self._dpr()
        if rect.width() > 0 and old > 0:
            px = (anchor.x() - rect.left()) / old
            py = (anchor.y() - rect.top()) / old
            left = anchor.x() - px * new
            top = anchor.y() - py * new
            w, h = self._img_w * self._par * new, self._img_h * new
            self._pan = QPointF(left + w / 2.0 - self.width() / 2.0, top + h / 2.0 - self.height() / 2.0)
        self._mode = "free"
        self._scale = scale
        self._clamp_pan()
        self._changed()

    def zoom_by(self, steps: float, anchor: QPointF | None = None):
        self.set_zoom(self._scale * (self.zoom_step ** steps), anchor)

    KEEP_VISIBLE = 48                        # px de l'image toujours visibles quand on la déplace

    def _clamp_pan(self):
        """Déplacement possible à TOUS les zooms, au-delà des bords de l'image :
        KEEP_VISIBLE px restent visibles, même agrandie (sauf déplacement libre).
        Rien n'est recentré tout seul :
        « Recentrer la vidéo » (`recenter`) ou « Ajuster à l'écran » (`fit`) le font."""
        rect = self.image_rect()
        x, y = self._pan.x(), self._pan.y()
        for axis, size, zone in (("x", rect.width(), self.width()), ("y", rect.height(), self.height())):
            value = x if axis == "x" else y
            if size <= zone or self.pan_bounded:
                limit = max(0.0, (zone + size) / 2.0 - min(self.KEEP_VISIBLE, size))
            else:
                limit = None
            if limit is not None:
                value = max(-limit, min(limit, value))
            if axis == "x":
                x = value
            else:
                y = value
        self._pan = QPointF(x, y)

    def _changed(self):
        self.update()
        self.zoomChanged.emit(self._scale)

    # -- souris --

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._mode in ("fit", "smart"):
            self._scale = self._auto_scale()      # le zoom suit la zone ; un déplacement choisi est GARDÉ
        self._clamp_pan()
        self.zoomChanged.emit(self._scale)

    def wheelEvent(self, event):
        if not self.wheel_zoom or not self._img_w:
            event.ignore()
            return
        delta = event.angleDelta().y() / 120.0
        if delta:
            self.zoom_by(delta, event.position())
        event.accept()

    # -- zone tracée (capture) --

    def set_region_mode(self, on: bool):
        """Mode « zone » : le glisser gauche trace un rectangle sur l'image (pas de déplacement ni de lecture /
        pause) ; au relâchement `regionSelected(QRect)` en PIXELS DE L'IMAGE (bornés à l'image)."""
        self._region_mode = bool(on)
        self._region_start = None
        if self._band is not None:
            self._band.hide()
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)

    def region_mode(self) -> bool:
        return self._region_mode

    def _image_point(self, pos: QPointF) -> QPointF:
        """Position en pixels de l'image (sans borne : peut être hors de l'image)."""
        rect = self.image_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return QPointF(0, 0)
        return QPointF((pos.x() - rect.left()) / rect.width() * self._img_w,
                       (pos.y() - rect.top()) / rect.height() * self._img_h)

    def _region_rect(self, a: QPointF, b: QPointF) -> QRect:
        p, q = self._image_point(a), self._image_point(b)
        x0 = max(0, min(self._img_w, int(np.floor(min(p.x(), q.x())))))
        y0 = max(0, min(self._img_h, int(np.floor(min(p.y(), q.y())))))
        x1 = max(0, min(self._img_w, int(np.ceil(max(p.x(), q.x())))))
        y1 = max(0, min(self._img_h, int(np.ceil(max(p.y(), q.y())))))
        return QRect(x0, y0, x1 - x0, y1 - y0)

    def mousePressEvent(self, event):
        self.setFocus()
        if self._region_mode and event.button() == Qt.LeftButton:
            from PySide6.QtWidgets import QRubberBand
            self._region_start = event.position()
            if self._band is None:
                self._band = QRubberBand(QRubberBand.Rectangle, self)
            self._band.setGeometry(QRect(event.position().toPoint(), event.position().toPoint()))
            self._band.show()
            event.accept()
            return
        if event.button() in (Qt.MiddleButton, Qt.LeftButton):
            if event.button() == Qt.MiddleButton and event.modifiers() & Qt.ShiftModifier:
                self.one_to_one()
                self.recenter()
                event.accept()
                return
            self._drag = (event.position(), QPointF(self._pan), event.button(), False)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._region_start is not None:
            self._band.setGeometry(QRect(self._region_start.toPoint(), event.position().toPoint()).normalized())
            event.accept()
            return
        if self._drag is not None:
            start, pan, button, moved = self._drag
            delta = event.position() - start
            if moved or abs(delta.x()) + abs(delta.y()) > 3:
                self._drag = (start, pan, button, True)
                self._pan = pan + delta
                self._clamp_pan()
                self.update()
        hit = self.map_to_image(event.position())
        self.pixelHovered.emit(*(hit if hit else (-1, -1)))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._region_start is not None and event.button() == Qt.LeftButton:
            start, self._region_start = self._region_start, None
            self._band.hide()
            region = self._region_rect(start, event.position())
            if region.width() >= 2 and region.height() >= 2:
                self.regionSelected.emit(region)
            event.accept()
            return
        drag = self._drag
        self._drag = None
        # Clic SANS déplacement (sinon c'est un déplacement de l'image), sur l'IMAGE elle-même (pas à côté).
        if (drag is not None and not drag[3] and drag[2] == Qt.LeftButton
                and self.map_to_image(drag[0]) is not None):
            self.viewClicked.emit()
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        self.pixelHovered.emit(-1, -1)
        super().leaveEvent(event)


# ==========================================================================
# État d'affichage commun
# ==========================================================================

class _DisplayState:
    def _init_display(self):
        self.frame = None                     # media.Frame
        self.frame_version = 0
        self.pipeline: vcolor.ColorPipeline | None = None
        self.state = vcolor.ViewState(dict(vcolor.DEFAULT_GRADE))
        self.compare = "off"                  # off, split, before
        self.split = 0.5
        self.bg = QColor("#202020")
        self.checker_on = True
        self.checker_size = 12
        self.checker_colors = (QColor("#3a3a3a"), QColor("#2a2a2a"))
        self.interpolation = "auto"           # auto, linear, nearest
        self.mipmaps = True
        self.effects = {}
        self.error = ""

    def set_frame(self, frame):
        self.frame = frame
        self.frame_version += 1
        if frame is not None and frame.has_image:
            w, h = frame.size
            self.set_image_size(w, h, self._par)
        self.update()

    def set_pipeline(self, pipeline):
        self.pipeline = pipeline
        self._pipeline_changed()
        self.update()

    def set_view_state(self, state: vcolor.ViewState):
        lut_changed = state.lut is not getattr(self.state, "lut", None)
        self.state = state
        if lut_changed:
            self._lut_changed()
        self.update()

    def set_look(self, look: dict):
        self.bg = QColor(look.get("bg", "#202020"))
        self.checker_on = bool(look.get("checker", True))
        self.checker_size = int(look.get("checker_size", 12))
        self.checker_colors = (QColor(look.get("checker_a", "#3a3a3a")), QColor(look.get("checker_b", "#2a2a2a")))
        self.interpolation = look.get("interpolation", "auto")
        self.wheel_zoom = bool(look.get("wheel_zoom", True))
        self.zoom_step = 1.0 + max(1, int(look.get("zoom_step", 25))) / 100.0
        self.pan_bounded = look.get("pan", "bounded") == "bounded"
        self.fit_margin = int(look.get("fit_margin", 0))
        if self._mode in ("fit", "smart"):
            self._scale = self._auto_scale()
        self.update()

    def set_effects(self, effects: dict | None):
        """Bordure, coins arrondis et ombre AUTOUR du rectangle visible de l'image (affichage seulement, jamais
        exportés ; centrage et zoom inchangés). Voir `pane._effects`."""
        self.effects = effects or {}
        self.update()

    def set_compare(self, mode: str, split: float | None = None):
        self.compare = mode
        if split is not None:
            self.split = max(0.0, min(1.0, split))
        self.update()

    def _pipeline_changed(self):
        pass

    def _lut_changed(self):
        pass

    def _alpha_mode(self) -> int:
        """0 = sans alpha, 1 = prémultiplié, 2 = droit (EXR : prémultiplié ; autres : droit, sauf réglage)."""
        mode = self.state.alpha_mode
        if mode == "ignore":
            return 0
        if mode == "premult":
            return 1
        if mode == "straight":
            return 2
        return 1 if getattr(self, "media_ext", "") in (".exr", ".dpx") else 2


# ==========================================================================
# OpenGL
# ==========================================================================

_VERTEX = """#version 330 core
void main() {
    vec2 c = vec2(float(gl_VertexID & 1), float(gl_VertexID >> 1));
    gl_Position = vec4(c * 2.0 - 1.0, 0.0, 1.0);
}
"""

_FRAGMENT_HEAD = """#version 330 core
out vec4 fragColor;
uniform sampler2D uImage;
uniform vec4 uBox;
uniform int uYuv; uniform sampler2D uU; uniform sampler2D uV; uniform float uCode; uniform vec4 uYuvLv;
uniform vec2 uKrb; uniform vec2 uChromaMul; uniform float uChromaShift;
uniform vec4 uRadius; uniform float uBorderW; uniform vec4 uBorderOn;
uniform vec4 uBcL; uniform vec4 uBcT; uniform vec4 uBcR; uniform vec4 uBcB;
uniform int uShadowOn; uniform vec4 uShadowCol; uniform float uShadowBlur; uniform vec2 uShadowOff;
uniform float uShadowSpread; uniform vec4 uShadowSides;
uniform int uChannels;
uniform int uGradeOn;
uniform vec3 uWB; uniform vec3 uOffset; uniform vec3 uSlope; uniform vec3 uLift; uniform vec3 uPower;
uniform float uContrast; uniform float uPivot; uniform vec4 uTone;
uniform float uSat; uniform float uVib; uniform mat3 uHue; uniform vec3 uLuma;
uniform vec4 uLevels; uniform float uBright;
uniform int uLutPos; uniform int uLutKind; uniform sampler3D uLut3D; uniform sampler2D uLut1D;
uniform float uLutSize; uniform vec3 uLutMin; uniform vec3 uLutMax; uniform float uLutMix;
uniform int uView; uniform int uClip; uniform int uAlpha;
uniform vec3 uBg; uniform vec3 uCk1; uniform vec3 uCk2; uniform float uCkSize; uniform int uCkOn;
uniform int uCompare; uniform float uSplitX;
"""

_FRAGMENT_BODY = """
vec3 spow(vec3 x, vec3 p) { return sign(x) * pow(abs(x), p); }

vec3 grade(vec3 x) {
    x = x * uWB + uOffset;
    x = spow(x * uSlope + uLift, uPower);
    if (abs(uContrast - 1.0) > 1e-6) {
        vec3 c = uPivot * pow(max(x, vec3(1e-10)) / uPivot, vec3(uContrast));
        x = mix(x, c, vec3(greaterThan(x, vec3(0.0))));
    }
    if (any(greaterThan(abs(uTone), vec4(1e-6)))) {
        float lum = max(dot(x, uLuma), 1e-6);
        float st = log2(lum / 0.18);
        float ms = clamp(-st / 4.0, 0.0, 1.0);
        float mh = clamp(st / 3.0, 0.0, 1.0);
        float mb = clamp((-st - 3.0) / 3.0, 0.0, 1.0);
        float mw = clamp((st - 1.5) / 2.0, 0.0, 1.0);
        x *= exp2(uTone.x * ms + uTone.y * mh + uTone.z * mw + uTone.w * mb);
    }
    float lum = dot(x, uLuma);
    float sat = uSat;
    if (abs(uVib) > 1e-6) {
        float mx = max(x.r, max(x.g, x.b));
        float mn = min(x.r, min(x.g, x.b));
        float cur = clamp((mx - mn) / max(abs(mx), 1e-6), 0.0, 1.0);
        sat *= 1.0 + uVib * (1.0 - cur);
    }
    x = vec3(lum) + (x - vec3(lum)) * sat;
    return uHue * x;
}

vec3 applyLut(vec3 rgb) {
    vec3 x = clamp((rgb - uLutMin) / max(uLutMax - uLutMin, vec3(1e-9)), 0.0, 1.0);
    vec3 outc;
    if (uLutKind == 3) {
        vec3 coord = (x * (uLutSize - 1.0) + 0.5) / uLutSize;
        outc = texture(uLut3D, coord).rgb;
    } else {
        vec3 coord = (x * (uLutSize - 1.0) + 0.5) / uLutSize;
        outc = vec3(texture(uLut1D, vec2(coord.r, 0.5)).r, texture(uLut1D, vec2(coord.g, 0.5)).g,
                    texture(uLut1D, vec2(coord.b, 0.5)).b);
    }
    return mix(rgb, outc, uLutMix);
}

vec3 levels(vec3 x) {
    x = (x - vec3(uLevels.x)) / max(uLevels.y - uLevels.x, 1e-6);
    return x * (uLevels.w - uLevels.z) + vec3(uLevels.z) + vec3(uBright);
}

// Distance signée à un rectangle aux coins arrondis (r = haut gauche, haut droit, bas droit, bas gauche ;
// y vers le haut comme gl_FragCoord).
float sdBox(vec2 q, vec2 b, vec4 r) {
    float rr = q.x > 0.0 ? (q.y > 0.0 ? r.y : r.z) : (q.y > 0.0 ? r.x : r.w);
    rr = min(rr, min(b.x, b.y));
    vec2 d = abs(q) - b + rr;
    return min(max(d.x, d.y), 0.0) + length(max(d, 0.0)) - rr;
}

vec4 sampleSource(vec2 uv) {
    if (uYuv == 0) return texture(uImage, uv);
    // YUV planaire -> RVB (matrice et plage du fichier), comme VLC / FFmpeg ; chromas recalés s'ils sont à gauche.
    float y = texture(uImage, uv).r * uCode;
    vec2 cuv = vec2(uv.x * uChromaMul.x + uChromaShift, uv.y * uChromaMul.y);
    float u = texture(uU, cuv).r * uCode;
    float v = texture(uV, cuv).r * uCode;
    y = (y - uYuvLv.x) / uYuvLv.y;
    u = (u - uYuvLv.z) / uYuvLv.w;
    v = (v - uYuvLv.z) / uYuvLv.w;
    float kr = uKrb.x, kb = uKrb.y;
    float r = y + 2.0 * (1.0 - kr) * v;
    float b = y + 2.0 * (1.0 - kb) * u;
    float g = (y - kr * r - kb * b) / (1.0 - kr - kb);
    return vec4(clamp(vec3(r, g, b), 0.0, 1.0), 1.0);
}

void main() {
    vec2 p = gl_FragCoord.xy;
    vec2 bmin = uBox.xy, bmax = uBox.zw;
    vec2 c0 = (bmin + bmax) * 0.5, hb = (bmax - bmin) * 0.5;
    float dImg = sdBox(p - c0, hb, uRadius);
    vec3 outside = uBg;
    if (uShadowOn == 1) {
        // Côté allumé : ombre étendue de « spread » ; côté éteint : rentrée du flou (rien ne dépasse de ce côté).
        float bl = uShadowSides.x > 0.5 ? uShadowSpread : -uShadowBlur;
        float bt = uShadowSides.y > 0.5 ? uShadowSpread : -uShadowBlur;
        float br = uShadowSides.z > 0.5 ? uShadowSpread : -uShadowBlur;
        float bb = uShadowSides.w > 0.5 ? uShadowSpread : -uShadowBlur;
        vec2 smin = bmin - vec2(bl, bb) + uShadowOff, smax = bmax + vec2(br, bt) + uShadowOff;
        float ds = sdBox(p - (smin + smax) * 0.5, max((smax - smin) * 0.5, vec2(0.5)),
                         max(uRadius + vec4(uShadowSpread), vec4(0.0)));
        float sa = uShadowBlur > 0.5 ? 1.0 - smoothstep(-uShadowBlur, uShadowBlur, ds) : clamp(0.5 - ds, 0.0, 1.0);
        outside = mix(outside, uShadowCol.rgb, sa * uShadowCol.a);
    }
    if (uBorderW > 0.0) {
        vec2 omin = bmin - vec2(uBorderOn.x, uBorderOn.w) * uBorderW;
        vec2 omax = bmax + vec2(uBorderOn.z, uBorderOn.y) * uBorderW;
        float dOut = sdBox(p - (omin + omax) * 0.5, (omax - omin) * 0.5, uRadius + vec4(uBorderW));
        float ring = clamp(0.5 - dOut, 0.0, 1.0);
        vec2 q = p - c0;
        float ex = abs(q.x) - hb.x, ey = abs(q.y) - hb.y;
        vec4 bc = ex > ey ? (q.x < 0.0 ? uBcL : uBcR) : (q.y > 0.0 ? uBcT : uBcB);
        outside = mix(outside, bc.rgb, ring * bc.a);
    }
    float cov = clamp(0.5 - dImg, 0.0, 1.0);
    if (cov <= 0.0) { fragColor = vec4(outside, 1.0); return; }
    vec2 uv = (p - bmin) / max(bmax - bmin, vec2(1e-6));
    uv.y = 1.0 - uv.y;
    vec4 src = sampleSource(uv);
    if (uChannels == 1) src = vec4(src.rrr, 1.0);
    else if (uChannels == 2) src = vec4(src.rrr, src.g);
    else if (uChannels == 3) src.a = 1.0;
    bool after = uCompare == 0 || (uCompare == 1 && gl_FragCoord.x >= uSplitX);
    bool g = after && uGradeOn == 1;
    vec3 rgb = src.rgb;
    float a = src.a;
    if (g && uLutPos == 1) rgb = applyLut(rgb);
    rgb = OCIOIn(vec4(rgb, 1.0)).rgb;
    if (g) rgb = grade(rgb);
    rgb = OCIOOut(vec4(rgb, 1.0)).rgb;
    if (g && uLutPos == 2) rgb = applyLut(rgb);
    if (g) rgb = levels(rgb);
    if (uView == 1) rgb = rgb.rrr;
    else if (uView == 2) rgb = rgb.ggg;
    else if (uView == 3) rgb = rgb.bbb;
    else if (uView == 4) { rgb = vec3(a); a = 1.0; }
    else if (uView == 5) rgb = vec3(dot(rgb, vec3(0.2126, 0.7152, 0.0722)));
    if (uClip == 1) {
        if (any(greaterThan(rgb, vec3(1.0)))) rgb = vec3(1.0, 0.0, 1.0);
        else if (any(lessThan(rgb, vec3(0.0)))) rgb = vec3(0.0, 0.4, 1.0);
    }
    vec3 back = uBg;
    if (uCkOn == 1) {
        vec2 cell = floor(gl_FragCoord.xy / max(uCkSize, 1.0));
        back = mod(cell.x + cell.y, 2.0) < 1.0 ? uCk1 : uCk2;
    }
    if (uAlpha == 1) rgb = rgb + back * (1.0 - clamp(a, 0.0, 1.0));
    else if (uAlpha == 2) rgb = mix(back, rgb, clamp(a, 0.0, 1.0));
    if (uCompare == 1 && abs(gl_FragCoord.x - uSplitX) < 1.0) rgb = vec3(1.0);
    fragColor = vec4(mix(outside, rgb, cov), 1.0);
}
"""

_IDENTITY = {"in": "vec4 OCIOIn(vec4 c) { return c; }\n", "out": "vec4 OCIOOut(vec4 c) { return c; }\n"}


def gl_available() -> bool:
    try:
        import OpenGL.GL  # noqa: F401
        return True
    except Exception:                                        # noqa: BLE001
        return False


try:
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
except Exception:                                            # noqa: BLE001
    QOpenGLWidget = None


if QOpenGLWidget is not None:
    class GLViewer(_ViewMixin, _DisplayState, QOpenGLWidget):
        engine = "opengl"
        glFailed = Signal(str)
        zoomChanged = Signal(float)
        pixelHovered = Signal(int, int)
        viewClicked = Signal()
        regionSelected = Signal(object)          # QRect en pixels de l'image (capture d'une zone)

        def __init__(self, parent=None):
            QOpenGLWidget.__init__(self, parent)
            fmt = QSurfaceFormat()
            fmt.setVersion(3, 3)
            fmt.setProfile(QSurfaceFormat.CoreProfile)
            self.setFormat(fmt)
            self.setAttribute(Qt.WA_OpaquePaintEvent, True)   # rien à repeindre dessous
            self._init_view()
            self._init_display()
            self._program = None
            self._program_dirty = True
            self._tex = None
            self._tex_key = None
            self._uv_tex = None
            self._uv_keys = [None, None]
            self._yuv = None
            self._mips_version = -1
            self._uploaded = -1
            self._lut_tex = {}
            self._lut_dirty = True
            self._ocio_tex = []
            self._locs = {}
            self._vao = None
            self._gl_ready = False

        # -- ressources --

        def initializeGL(self):
            from OpenGL import GL
            try:
                self._vao = GL.glGenVertexArrays(1)
                self._tex = GL.glGenTextures(1)
                self._uv_tex = list(GL.glGenTextures(2))
                self._uv_keys = [None, None]
                self._mips_version = -1
                self._lut_tex = {3: GL.glGenTextures(1), 1: GL.glGenTextures(1)}
                self._ocio_tex = []
                self._program = None
                self._program_dirty = True
                self._lut_dirty = True
                self._uploaded = -1
                self._tex_key = None
                self._gl_ready = True
                ctx = self.context()
                if ctx is not None:
                    ctx.aboutToBeDestroyed.connect(self._release_gl)
            except Exception as exc:                         # noqa: BLE001
                self.error = f"OpenGL indisponible : {exc}"
                self._gl_ready = False
                self.glFailed.emit(self.error)

        def _release_gl(self):
            """Contexte détruit (changement de fenêtre parente, plein écran) : tout sera recréé."""
            self._gl_ready = False
            self._program = None

        def _pipeline_changed(self):
            self._program_dirty = True

        def _lut_changed(self):
            self._lut_dirty = True

        def _build_program(self):
            from OpenGL import GL
            from OpenGL.GL import shaders
            texts = dict(_IDENTITY)
            self._ocio_specs = []
            if self.pipeline is not None:
                for which in ("in", "out"):
                    try:
                        text, textures, _uniforms = self.pipeline.gpu_shader(which)
                        texts[which] = text
                        self._ocio_specs += textures
                    except Exception as exc:                 # noqa: BLE001
                        self.error = f"OCIO (GPU) : {exc}"
            source = _FRAGMENT_HEAD + texts["in"] + texts["out"] + _FRAGMENT_BODY
            try:
                vert = shaders.compileShader(_VERTEX, GL.GL_VERTEX_SHADER)
                frag = shaders.compileShader(source, GL.GL_FRAGMENT_SHADER)
                program = shaders.compileProgram(vert, frag, validate=False)
            except Exception as exc:                         # noqa: BLE001 - repli : sans OCIO
                self.error = f"Shader : {str(exc)[:400]}"
                source = _FRAGMENT_HEAD + _IDENTITY["in"] + _IDENTITY["out"] + _FRAGMENT_BODY
                vert = shaders.compileShader(_VERTEX, GL.GL_VERTEX_SHADER)
                frag = shaders.compileShader(source, GL.GL_FRAGMENT_SHADER)
                program = shaders.compileProgram(vert, frag, validate=False)
                self._ocio_specs = []
            if self._program is not None:
                try:
                    GL.glDeleteProgram(self._program)
                except Exception:                            # noqa: BLE001
                    pass
            self._program = program
            self._locs = {}
            if self._ocio_tex:
                GL.glDeleteTextures(self._ocio_tex)
            self._ocio_tex = []
            for spec in self._ocio_specs:
                self._ocio_tex.append(self._upload_aux_texture(spec))
            self._program_dirty = False

        def _upload_aux_texture(self, spec):
            from OpenGL import GL
            _name, dims, w, h, d, channels, values, linear = spec
            tex = GL.glGenTextures(1)
            target = GL.GL_TEXTURE_3D if dims == 3 else GL.GL_TEXTURE_2D
            GL.glBindTexture(target, tex)
            fmt = GL.GL_RGB if channels == 3 else GL.GL_RED
            internal = GL.GL_RGB32F if channels == 3 else GL.GL_R32F
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            data = np.ascontiguousarray(values, dtype=np.float32)
            if dims == 3:
                GL.glTexImage3D(target, 0, internal, w, h, d, 0, fmt, GL.GL_FLOAT, data)
            else:
                GL.glTexImage2D(target, 0, internal, w, h, 0, fmt, GL.GL_FLOAT, data)
            flt = GL.GL_LINEAR if linear else GL.GL_NEAREST
            GL.glTexParameteri(target, GL.GL_TEXTURE_MIN_FILTER, flt)
            GL.glTexParameteri(target, GL.GL_TEXTURE_MAG_FILTER, flt)
            for p in (GL.GL_TEXTURE_WRAP_S, GL.GL_TEXTURE_WRAP_T, GL.GL_TEXTURE_WRAP_R):
                GL.glTexParameteri(target, p, GL.GL_CLAMP_TO_EDGE)
            return tex

        def _upload_lut(self):
            from OpenGL import GL
            lut = self.state.lut
            self._lut_dirty = False
            if lut is None:
                return
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            if lut.kind == 3:
                GL.glBindTexture(GL.GL_TEXTURE_3D, self._lut_tex[3])
                GL.glTexImage3D(GL.GL_TEXTURE_3D, 0, GL.GL_RGB32F, lut.size, lut.size, lut.size, 0, GL.GL_RGB,
                                GL.GL_FLOAT, np.ascontiguousarray(lut.table, dtype=np.float32))
                target = GL.GL_TEXTURE_3D
            else:
                GL.glBindTexture(GL.GL_TEXTURE_2D, self._lut_tex[1])
                GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB32F, lut.size, 1, 0, GL.GL_RGB, GL.GL_FLOAT,
                                np.ascontiguousarray(lut.table, dtype=np.float32))
                target = GL.GL_TEXTURE_2D
            GL.glTexParameteri(target, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(target, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
            for p in (GL.GL_TEXTURE_WRAP_S, GL.GL_TEXTURE_WRAP_T, GL.GL_TEXTURE_WRAP_R):
                GL.glTexParameteri(target, p, GL.GL_CLAMP_TO_EDGE)

        def _upload_plane(self, tex, arr, width, height, key_holder, slot):
            """Un plan YUV (8 ou 16 bits) envoyé tel quel : ses lignes peuvent être plus larges que l'image
            (`GL_UNPACK_ROW_LENGTH`), aucune copie."""
            from OpenGL import GL
            eight = arr.dtype == np.uint8
            gl_type = GL.GL_UNSIGNED_BYTE if eight else GL.GL_UNSIGNED_SHORT
            internal = GL.GL_R8 if eight else GL.GL_R16
            GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            GL.glPixelStorei(GL.GL_UNPACK_ROW_LENGTH, int(arr.shape[1]))
            key = (width, height, arr.dtype.str)
            if key_holder[slot] == key:
                GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, width, height, GL.GL_RED, gl_type, arr)
            else:
                GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, internal, width, height, 0, GL.GL_RED, gl_type, arr)
                key_holder[slot] = key
            GL.glPixelStorei(GL.GL_UNPACK_ROW_LENGTH, 0)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)

        def _upload_frame(self):
            from OpenGL import GL
            yuv = self.frame.yuv
            if yuv is not None:
                holder = [self._tex_key]
                self._upload_plane(self._tex, yuv.planes[0], yuv.width, yuv.height, holder, 0)
                self._tex_key = holder[0]
                for i in (1, 2):
                    cw, ch = yuv.plane_size(i)
                    self._upload_plane(self._uv_tex[i - 1], yuv.planes[i], cw, ch, self._uv_keys, i - 1)
                self._yuv = yuv
                self._channels = 3
                self._uploaded = self.frame_version
                return
            self._yuv = None
            pixels = self.frame.pixels
            if pixels.ndim == 2:
                pixels = pixels[..., None]
            h, w, c = pixels.shape
            c = min(c, 4)
            if pixels.shape[2] != c:
                pixels = pixels[..., :4]
            pixels = np.ascontiguousarray(pixels)
            gl_type, internals = {
                np.dtype(np.uint8): (GL.GL_UNSIGNED_BYTE, (GL.GL_R8, GL.GL_RG8, GL.GL_RGB8, GL.GL_RGBA8)),
                np.dtype(np.uint16): (GL.GL_UNSIGNED_SHORT, (GL.GL_R16, GL.GL_RG16, GL.GL_RGB16, GL.GL_RGBA16)),
                np.dtype(np.float16): (GL.GL_HALF_FLOAT, (GL.GL_R16F, GL.GL_RG16F, GL.GL_RGB16F, GL.GL_RGBA16F)),
                np.dtype(np.float32): (GL.GL_FLOAT, (GL.GL_R32F, GL.GL_RG32F, GL.GL_RGB32F, GL.GL_RGBA32F)),
            }[pixels.dtype]
            fmt = (GL.GL_RED, GL.GL_RG, GL.GL_RGB, GL.GL_RGBA)[c - 1]
            internal = internals[c - 1]
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._tex)
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            key = (w, h, c, pixels.dtype.str)
            if key == self._tex_key:
                GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, w, h, fmt, gl_type, pixels)
            else:
                GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, internal, w, h, 0, fmt, gl_type, pixels)
                self._tex_key = key
            self._channels = c
            self._uploaded = self.frame_version
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)

        def _loc(self, name):
            from OpenGL import GL
            loc = self._locs.get(name)
            if loc is None:
                loc = self._locs[name] = GL.glGetUniformLocation(self._program, name)
            return loc

        # -- dessin --

        def paintGL(self):
            from OpenGL import GL
            if not self._gl_ready:
                return
            dpr = self._dpr()
            bg = self.bg
            GL.glViewport(0, 0, int(self.width() * dpr), int(self.height() * dpr))
            GL.glClearColor(bg.redF(), bg.greenF(), bg.blueF(), 1.0)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            if self.frame is None or not self.frame.has_image:
                return
            try:
                if self._program_dirty or self._program is None:
                    self._build_program()
                if self._uploaded != self.frame_version:
                    self._upload_frame()
                if self._lut_dirty:
                    self._upload_lut()
                self._draw(GL, dpr)
            except Exception as exc:                         # noqa: BLE001 - jamais de plantage de la peinture
                self.error = f"Affichage : {exc}"

        def _textures(self):
            return [self._tex] + (list(self._uv_tex) if self._yuv is not None else [])

        def _draw(self, GL, dpr):
            rect = self.image_rect()
            H = max(1, self.height()) * dpr
            GL.glUseProgram(self._program)
            x0 = rect.left() * dpr
            x1 = x0 + rect.width() * dpr
            y1 = H - rect.top() * dpr
            y0 = y1 - rect.height() * dpr
            GL.glUniform4f(self._loc("uBox"), x0, y0, x1, y1)
            # Filtrage : 100 % = pixels exacts, sinon bilinéaire (comme VLC) ; mipmaps SEULEMENT sous 50 % (au-dessus,
            # elles mélangeaient une version réduite de moitié : image nettement plus floue que dans VLC).
            nearest = self.interpolation == "nearest" or (
                self.interpolation == "auto" and (self._scale > 1.5 or abs(self._scale - 1.0) < 1e-6))
            mag = GL.GL_NEAREST if nearest else GL.GL_LINEAR
            mips = self.mipmaps and not nearest and self._scale < 0.5
            minf = GL.GL_LINEAR_MIPMAP_LINEAR if mips else mag
            if mips and self._mips_version != self.frame_version:
                for tex in self._textures():
                    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
                    GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
                self._mips_version = self.frame_version
            for tex in self._textures():
                GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, minf)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, mag)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._tex)
            GL.glUniform1i(self._loc("uImage"), 0)
            self._set_yuv_uniforms(GL)
            self._set_effect_uniforms(GL, dpr)
            GL.glUniform1i(self._loc("uChannels"), self._channels)
            st = self.state
            d = vcolor.derived(st.grade, self.pipeline.luma if self.pipeline else vcolor.LUMA_AP1)
            GL.glUniform1i(self._loc("uGradeOn"), 1 if st.grade_on else 0)
            for name, key in (("uWB", "wb"), ("uOffset", "offset"), ("uSlope", "slope"), ("uLift", "lift"),
                              ("uPower", "power"), ("uLuma", "luma")):
                GL.glUniform3f(self._loc(name), *(float(v) for v in d[key]))
            GL.glUniform1f(self._loc("uContrast"), d["contrast"])
            GL.glUniform1f(self._loc("uPivot"), d["pivot"])
            GL.glUniform4f(self._loc("uTone"), *(float(v) for v in d["tone"]))
            GL.glUniform1f(self._loc("uSat"), d["sat"])
            GL.glUniform1f(self._loc("uVib"), d["vib"])
            GL.glUniformMatrix3fv(self._loc("uHue"), 1, GL.GL_TRUE, np.ascontiguousarray(d["hue"], np.float32))
            GL.glUniform4f(self._loc("uLevels"), *(float(v) for v in d["levels"]))
            GL.glUniform1f(self._loc("uBright"), d["bright"])
            lut = st.lut
            pos = 0 if lut is None else (1 if st.lut_position == "source" else 2)
            GL.glUniform1i(self._loc("uLutPos"), pos)
            GL.glActiveTexture(GL.GL_TEXTURE1)
            GL.glBindTexture(GL.GL_TEXTURE_3D, self._lut_tex[3])
            GL.glUniform1i(self._loc("uLut3D"), 1)
            GL.glActiveTexture(GL.GL_TEXTURE2)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._lut_tex[1])
            GL.glUniform1i(self._loc("uLut1D"), 2)
            if lut is not None:
                GL.glUniform1i(self._loc("uLutKind"), lut.kind)
                GL.glUniform1f(self._loc("uLutSize"), float(lut.size))
                GL.glUniform3f(self._loc("uLutMin"), *(float(v) for v in lut.domain_min))
                GL.glUniform3f(self._loc("uLutMax"), *(float(v) for v in lut.domain_max))
                GL.glUniform1f(self._loc("uLutMix"), float(st.lut_mix))
            if self._yuv is not None:
                for unit, (name, tex) in enumerate((("uU", self._uv_tex[0]), ("uV", self._uv_tex[1])), 3):
                    GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
                    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
                    GL.glUniform1i(self._loc(name), unit)
            unit = 5
            for spec, tex in zip(self._ocio_specs, self._ocio_tex):
                GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
                GL.glBindTexture(GL.GL_TEXTURE_3D if spec[1] == 3 else GL.GL_TEXTURE_2D, tex)
                GL.glUniform1i(self._loc(spec[0]), unit)
                unit += 1
            GL.glUniform1i(self._loc("uView"), {"rgb": 0, "r": 1, "g": 2, "b": 3, "a": 4, "luma": 5}
                           .get(st.channel, 0))
            GL.glUniform1i(self._loc("uClip"), 1 if st.clipping else 0)
            GL.glUniform1i(self._loc("uAlpha"), self._alpha_mode() if self._channels in (2, 4) else 0)
            GL.glUniform3f(self._loc("uBg"), self.bg.redF(), self.bg.greenF(), self.bg.blueF())
            c1, c2 = self.checker_colors
            GL.glUniform3f(self._loc("uCk1"), c1.redF(), c1.greenF(), c1.blueF())
            GL.glUniform3f(self._loc("uCk2"), c2.redF(), c2.greenF(), c2.blueF())
            GL.glUniform1f(self._loc("uCkSize"), float(self.checker_size) * dpr)
            GL.glUniform1i(self._loc("uCkOn"), 1 if self.checker_on else 0)
            GL.glUniform1i(self._loc("uCompare"), {"off": 0, "split": 1, "before": 2}.get(self.compare, 0))
            GL.glUniform1f(self._loc("uSplitX"), (rect.left() + rect.width() * self.split) * dpr)
            GL.glBindVertexArray(self._vao)
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
            GL.glBindVertexArray(0)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glUseProgram(0)

        def _set_yuv_uniforms(self, GL):
            yuv = self._yuv
            GL.glUniform1i(self._loc("uYuv"), 0 if yuv is None else 1)
            if yuv is None:
                return
            _top, ya, yb, ca, cb = yuv.levels()
            GL.glUniform1f(self._loc("uCode"), 255.0 if yuv.planes[0].dtype == np.uint8 else 65535.0)
            GL.glUniform4f(self._loc("uYuvLv"), ya, yb, ca, cb)
            GL.glUniform2f(self._loc("uKrb"), yuv.kr, yuv.kb)
            cw, ch = yuv.plane_size(1)
            GL.glUniform2f(self._loc("uChromaMul"), yuv.width / yuv.sx / cw, yuv.height / yuv.sy / ch)
            GL.glUniform1f(self._loc("uChromaShift"), yuv.chroma_shift)

        def _set_effect_uniforms(self, GL, dpr):
            e = self.effects or {}
            radius = e.get("radius") or {}
            GL.glUniform4f(self._loc("uRadius"), *(float(radius.get(k, 0)) * dpr
                                                   for k in ("top_left", "top_right", "bottom_right", "bottom_left")))
            sides = e.get("border_on") or {}
            width = float(e.get("border_w", 0)) * dpr if any(sides.values()) else 0.0
            GL.glUniform1f(self._loc("uBorderW"), width)
            GL.glUniform4f(self._loc("uBorderOn"), *(1.0 if sides.get(k) else 0.0
                                                     for k in ("left", "top", "right", "bottom")))
            colors = e.get("border_colors") or {}
            for name, side in (("uBcL", "left"), ("uBcT", "top"), ("uBcR", "right"), ("uBcB", "bottom")):
                c = QColor(colors.get(side, "#808080"))
                GL.glUniform4f(self._loc(name), c.redF(), c.greenF(), c.blueF(), c.alphaF())
            sh = e.get("shadow")
            GL.glUniform1i(self._loc("uShadowOn"), 1 if sh else 0)
            if sh:
                c = QColor(sh["color"])
                GL.glUniform4f(self._loc("uShadowCol"), c.redF(), c.greenF(), c.blueF(), c.alphaF())
                GL.glUniform1f(self._loc("uShadowBlur"), float(sh.get("blur", 0)) * dpr)
                GL.glUniform2f(self._loc("uShadowOff"), float(sh.get("ox", 0)) * dpr, -float(sh.get("oy", 0)) * dpr)
                GL.glUniform1f(self._loc("uShadowSpread"), float(sh.get("spread", 0)) * dpr)
                on = sh.get("sides") or {}
                GL.glUniform4f(self._loc("uShadowSides"), *(1.0 if on.get(k) else 0.0
                                                            for k in ("left", "top", "right", "bottom")))
else:
    GLViewer = None


# ==========================================================================
# Repli CPU
# ==========================================================================

class CPUViewer(_ViewMixin, _DisplayState, QWidget):
    engine = "cpu"
    zoomChanged = Signal(float)
    pixelHovered = Signal(int, int)
    viewClicked = Signal()
    regionSelected = Signal(object)              # QRect en pixels de l'image (capture d'une zone)

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self._init_view()
        self._init_display()
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self._cache_key = None
        self._cache_img = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.bg)
        frame = self.frame
        if frame is None or not frame.has_image:
            return
        rect = self.image_rect()
        path = self._paint_effects(painter, rect)
        visible = rect.intersected(QRectF(self.rect()))
        if visible.isEmpty():
            return
        dpr = self._dpr()
        key = (self.frame_version, round(visible.left(), 1), round(visible.top(), 1), round(visible.width(), 1),
               round(visible.height(), 1), id(self.state), repr(sorted(self.state.grade.items())), self.state.channel,
               self.state.clipping, self.state.grade_on, self.state.lut_mix, self.compare, self.split,
               id(self.pipeline), self.checker_on, self.state.lut_position, id(self.state.lut))
        if key != self._cache_key:
            self._cache_img = self._render(frame, rect, visible, dpr)
            self._cache_key = key
        if self._cache_img is not None:
            if path is not None:
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setClipPath(path)
            painter.drawImage(visible, self._cache_img)

    def _paint_effects(self, painter, rect: QRectF):
        """Ombre et bordure (repli CPU) ; rend le chemin arrondi qui découpe l'image (None : coins droits)."""
        e = self.effects or {}
        radius = e.get("radius") or {}
        r = max([float(radius.get(k, 0)) for k in ("top_left", "top_right", "bottom_right", "bottom_left")] or [0])
        path = None
        if r > 0:
            path = QPainterPath()
            path.addRoundedRect(rect, r, r)
        sh = e.get("shadow")
        painter.setRenderHint(QPainter.Antialiasing, True)
        if sh:
            try:
                from settings_widgets import paint_shadow
                spread = float(sh.get("spread", 0))
                srect = rect.translated(float(sh.get("ox", 0)), float(sh.get("oy", 0))).adjusted(
                    -spread, -spread, spread, spread)
                paint_shadow(painter, srect, radius, {"on": sh.get("sides") or {}, "size": int(sh.get("blur", 0)),
                                                     "colors": {k: sh["color"] for k in ("top", "right", "bottom",
                                                                                          "left")}}, 1.0)
            except Exception:                                # noqa: BLE001 - ombre facultative
                pass
        sides = e.get("border_on") or {}
        width = float(e.get("border_w", 0))
        if width > 0 and any(sides.values()):
            colors = e.get("border_colors") or {}
            side = next(k for k in ("top", "right", "bottom", "left") if sides.get(k))
            outer = rect.adjusted(-width * bool(sides.get("left")), -width * bool(sides.get("top")),
                                  width * bool(sides.get("right")), width * bool(sides.get("bottom")))
            ring = QPainterPath()
            ring.addRoundedRect(outer, r + width, r + width)
            inner = QPainterPath()
            inner.addRoundedRect(rect, r, r)
            painter.fillPath(ring.subtracted(inner), QColor(colors.get(side, "#808080")))
        return path

    def _render(self, frame, rect: QRectF, visible: QRectF, dpr: float):
        pixels = frame.pixels
        h, w = pixels.shape[:2]
        x0 = int((visible.left() - rect.left()) / rect.width() * w)
        x1 = int(math.ceil((visible.right() - rect.left()) / rect.width() * w))
        y0 = int((visible.top() - rect.top()) / rect.height() * h)
        y1 = int(math.ceil((visible.bottom() - rect.top()) / rect.height() * h))
        out_w = max(1, int(visible.width() * dpr))
        out_h = max(1, int(visible.height() * dpr))
        xs = np.clip(np.linspace(x0, x1 - 1, out_w).astype(np.int64), 0, w - 1)
        ys = np.clip(np.linspace(y0, y1 - 1, out_h).astype(np.int64), 0, h - 1)
        crop = pixels[ys][:, xs]
        state = self.state
        if self.compare == "before":
            state = vcolor.ViewState(state.grade, False, state.lut, state.lut_position, state.lut_mix,
                                     state.channel, state.clipping, state.alpha_mode)
        rgb, alpha = vcolor.process_np(crop, self.pipeline, state)
        if self.compare == "split":
            plain = vcolor.ViewState(state.grade, False, state.lut, state.lut_position, state.lut_mix,
                                     state.channel, state.clipping, state.alpha_mode)
            before, _a = vcolor.process_np(crop, self.pipeline, plain)
            cut = int(((rect.left() + rect.width() * self.split) - visible.left()) * dpr)
            if cut > 0:
                rgb[:, :min(cut, out_w)] = before[:, :min(cut, out_w)]
        rgb = finish_np(rgb, alpha, state, self._alpha_mode(), self.bg, self.checker_on, self.checker_colors,
                        int(self.checker_size * dpr))
        data = np.ascontiguousarray((np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8))
        image = QImage(data.data, out_w, out_h, out_w * 3, QImage.Format_RGB888).copy()
        return image


def finish_np(rgb, alpha, state, alpha_mode: int, bg: QColor, checker: bool, colors, size: int):
    """Étapes d'affichage après le pipeline : canal, écrêtage, composition sur le fond (comme le shader)."""
    view = state.channel
    if view in ("r", "g", "b"):
        rgb = np.repeat(rgb[..., "rgb".index(view)][..., None], 3, axis=2)
    elif view == "a":
        rgb = np.repeat((alpha if alpha is not None else np.ones(rgb.shape[:2], np.float32))[..., None], 3, axis=2)
        alpha = None
    elif view == "luma":
        rgb = np.repeat(np.tensordot(rgb, np.array(vcolor.LUMA_709, np.float32), axes=([-1], [0]))[..., None],
                        3, axis=2)
    if state.clipping:
        over = np.any(rgb > 1.0, axis=-1)
        under = np.any(rgb < 0.0, axis=-1) & ~over
        rgb = rgb.copy()
        rgb[over] = (1.0, 0.0, 1.0)
        rgb[under] = (0.0, 0.4, 1.0)
    if alpha is not None and alpha_mode:
        h, w = rgb.shape[:2]
        back = np.empty((h, w, 3), np.float32)
        if checker:
            yy, xx = np.indices((h, w))
            mask = ((xx // max(1, size) + yy // max(1, size)) % 2 == 0)[..., None]
            c1 = np.array([colors[0].redF(), colors[0].greenF(), colors[0].blueF()], np.float32)
            c2 = np.array([colors[1].redF(), colors[1].greenF(), colors[1].blueF()], np.float32)
            back[:] = np.where(mask, c1, c2)
        else:
            back[:] = (bg.redF(), bg.greenF(), bg.blueF())
        a = np.clip(alpha, 0, 1)[..., None]
        rgb = rgb + back * (1 - a) if alpha_mode == 1 else back + (rgb - back) * a
    return rgb


def create_viewer(preference: str = "auto", parent=None):
    """« opengl », « cpu » ou « auto » (OpenGL si PyOpenGL est là ; un échec à l'initialisation est signalé par
    `glFailed` et le module repasse en CPU)."""
    if preference != "cpu" and GLViewer is not None and gl_available():
        return GLViewer(parent)
    return CPUViewer(parent)


# ==========================================================================
# Informations en surimpression
# ==========================================================================

class InfoOverlay(QWidget):
    """Panneau d'infos posé PAR-DESSUS l'image (coin choisi, marges) : fond semi-transparent, texte, catégories.
    Transparent à la souris : la navigation passe à travers ; le masquer ne bouge pas l'image."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._sections: list[tuple[str, list[tuple[str, str]]]] = []
        self.look = {}
        self.hide()

    def set_look(self, look: dict):
        self.look = dict(look)
        self._relayout()

    def set_sections(self, sections):
        if sections != self._sections:
            self._sections = sections
            self._relayout()

    def _font(self, bold=False) -> QFont:
        font = QFont(self.look.get("font", "") or self.font().family())
        font.setPixelSize(max(6, int(self.look.get("font_size", 12))))
        font.setBold(bold)
        return font

    def _lines(self):
        out = []
        compact = self.look.get("compact", False)
        show_titles = self.look.get("titles", True) and not compact
        for title, rows in self._sections:
            if not rows:
                continue
            if show_titles:
                out.append(("title", title, ""))
            for label, value in rows:
                out.append(("row", label, value))
        return out

    def _relayout(self):
        parent = self.parentWidget()
        if parent is None:
            return
        lines = self._lines()
        fm, fmb = QFontMetrics(self._font()), QFontMetrics(self._font(True))
        pad = int(self.look.get("padding", 10))
        spacing = int(self.look.get("line_spacing", 3))
        width = int(self.look.get("width", 0))
        if not width:
            label_w = max([fm.horizontalAdvance(l) for kind, l, _v in lines if kind == "row"] or [0])
            value_w = max([fm.horizontalAdvance(v) for kind, _l, v in lines if kind == "row"] or [0])
            title_w = max([fmb.horizontalAdvance(l) for kind, l, _v in lines if kind == "title"] or [0])
            width = max(title_w, label_w + 12 + value_w) + 2 * pad
        width = min(width, max(80, parent.width() - 2 * int(self.look.get("margin_x", 16))))
        height = 2 * pad + sum(fmb.height() if k == "title" else fm.height() for k, _l, _v in lines) \
            + spacing * max(0, len(lines) - 1)
        height = min(height, max(40, parent.height() - 2 * int(self.look.get("margin_y", 16))))
        self.resize(width, height)
        self._place()
        self.update()

    def _place(self):
        parent = self.parentWidget()
        mx, my = int(self.look.get("margin_x", 16)), int(self.look.get("margin_y", 16))
        corner = self.look.get("corner", "top_right")
        x = mx if "left" in corner else parent.width() - self.width() - mx
        y = my if "top" in corner else parent.height() - self.height() - my
        self.move(max(0, x), max(0, y))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        bg = QColor(self.look.get("bg", "#000000"))
        bg.setAlphaF(max(0.0, min(1.0, float(self.look.get("opacity", 60)) / 100.0)))
        radius = float(self.look.get("radius", 6))
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), radius, radius)
        painter.fillPath(path, bg)
        pad = int(self.look.get("padding", 10))
        spacing = int(self.look.get("line_spacing", 3))
        text = QColor(self.look.get("color", "#e8e8e8"))
        label_color = QColor(self.look.get("label_color", "#9aa0a6"))
        title_color = QColor(self.look.get("title_color", "#ffffff"))
        font, bold = self._font(), self._font(True)
        fm, fmb = QFontMetrics(font), QFontMetrics(bold)
        y = pad
        inner = self.width() - 2 * pad
        for kind, label, value in self._lines():
            if y > self.height() - pad:
                break
            if kind == "title":
                painter.setFont(bold)
                painter.setPen(title_color)
                painter.drawText(QRectF(pad, y, inner, fmb.height()), Qt.AlignLeft | Qt.AlignVCenter, label)
                y += fmb.height() + spacing
                continue
            painter.setFont(font)
            painter.setPen(label_color)
            painter.drawText(QRectF(pad, y, inner, fm.height()), Qt.AlignLeft | Qt.AlignVCenter, label)
            painter.setPen(text)
            elided = fm.elidedText(value, Qt.ElideMiddle, max(10, inner - fm.horizontalAdvance(label) - 12))
            painter.drawText(QRectF(pad, y, inner, fm.height()), Qt.AlignRight | Qt.AlignVCenter, elided)
            y += fm.height() + spacing

    def reposition(self):
        if self.isVisible():
            self._relayout()

