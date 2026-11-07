"""Analyse des pixels d'affichage sRGB : clustering OKLab borné, exécuté en fond (MOTEUR, sans interface).

Les mesures décrivent le proxy affiché ; elles ne mesurent ni la scène ni un signal HDR. Interface : `analysis_ui.py`
(`ColorAnalysis`) ; `_Image` reste ici (aperçu du matching, `matching_ui.py`).
"""
import math
import numpy as np
import threading
from PySide6.QtCore import QObject, Signal, QRunnable, Qt, QRectF
from PySide6.QtGui import QImage, QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget

_LUMA = np.array([.2126, .7152, .0722])
_M1 = np.array([[.4122214708,.2119034982,.0883024619],
                [.5363325363,.6806995451,.2817188376],
                [.0514459929,.1073969566,.6299787005]])
_M2 = np.array([[.2104542553,1.9779984951,.0259040371],
                [.793617785,-2.428592205,.7827717662],
                [-.0040720468,.4505937099,-.808675766]])
SUBS = 6                    # nuances par couleur de la palette (maquette : 6 carrés sous la pastille choisie)
_GRID = None


def _lab(rgb01):
    """OKLab de couleurs sRGB encodées 0-1 (n, 3)."""
    linear = np.where(rgb01 <= .04045, rgb01 / 12.92, ((rgb01 + .055) / 1.055) ** 2.4)
    return np.cbrt(linear @ _M1) @ _M2


def _kmeans(lab, count, cancelled=None):
    """Centres OKLab : initialisation déterministe par distance maximale (depuis le plus sombre), puis Lloyd.
    None si annulé."""
    centers = [lab[np.argmin(lab[:, 0])]]
    for _ in range(count - 1):
        if cancelled and cancelled():
            return None
        dist = ((lab[:,None] - np.array(centers)[None]) ** 2).sum(2).min(1)
        if dist.max() < 1e-10:
            break
        centers.append(lab[np.argmax(dist)])
    centers = np.array(centers)
    for _ in range(16):
        if cancelled and cancelled():
            return None
        labels = ((lab[:,None] - centers[None]) ** 2).sum(2).argmin(1)
        updated = np.array([lab[labels == i].mean(0) if (labels == i).any() else c
                            for i,c in enumerate(centers)])
        if np.max(np.abs(updated - centers)) < 1e-5:
            centers = updated
            break
        centers = updated
    return centers


def label_map(rgb, centers, sub_centers):
    """Couleur et nuance de chaque pixel (uint8 h x w : j * SUBS + k) d'une image sRGB uint8 (h, w, 3), au plus
    proche en OKLab. Table 64³ (pas de 4 niveaux) : le coût ne dépend pas de la taille de l'image."""
    global _GRID
    if _GRID is None:
        v = (np.arange(64) * 4 + 2) / 255.0
        _GRID = _lab(np.stack(np.meshgrid(v, v, v, indexing='ij'), -1).reshape(-1, 3)).astype(np.float32)
    grid = _GRID
    c = np.asarray(centers, np.float32)
    main = (grid @ (-2 * c.T) + (c * c).sum(1)).argmin(1)
    table = np.zeros(len(grid), np.uint8)
    for j, sub in enumerate(sub_centers):
        idx = np.nonzero(main == j)[0]
        if not len(idx):
            continue
        s = np.asarray(sub, np.float32)
        table[idx] = j * SUBS + (grid[idx] @ (-2 * s.T) + (s * s).sum(1)).argmin(1)
    q = (rgb[..., 0].astype(np.int32) >> 2) * 4096 + (rgb[..., 1].astype(np.int32) >> 2) * 64 + (rgb[..., 2] >> 2)
    return table[q]


def oklch(rgb):
    """(L, C, h en degrés) OKLab d'une couleur sRGB 0-255 encodée."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    lin = np.where(c <= .04045, c / 12.92, ((c + .055) / 1.055) ** 2.4)
    lms = np.cbrt(lin @ np.array([[.4122214708,.2119034982,.0883024619],
                                  [.5363325363,.6806995451,.2817188376],
                                  [.0514459929,.1073969566,.6299787005]]))
    lab = lms @ np.array([[.2104542553,1.9779984951,.0259040371],
                          [.793617785,-2.428592205,.7827717662],
                          [-.0040720468,.4505937099,-.808675766]])
    return float(lab[0]), float(math.hypot(lab[1], lab[2])), float(math.degrees(math.atan2(lab[2], lab[1])) % 360)


def scope_data(rgb, zoom=1.6):
    """Waveform (alpha 256 x colonnes, densité log) et vectorscope (ARGB 256 x 256 : chaque case de la COULEUR moyenne
    des pixels qui y tombent) d'une image sRGB uint8 (h, w, 3) opaque. Valeurs ENCODÉES (Y′, Cb / Cr BT.709)."""
    f = rgb.astype(np.float32) / 255.0
    h, w = f.shape[:2]
    luma = f @ _LUMA.astype(np.float32)
    levels = np.clip((luma * 255 + .5).astype(np.int32), 0, 255)
    cols = np.broadcast_to(np.arange(w, dtype=np.int32), (h, w))
    wave = np.bincount(((255 - levels) * w + cols).ravel(), minlength=256 * w)[:256 * w].reshape(256, w)
    v = np.log1p(wave.astype(np.float32))
    wave_alpha = (np.clip(v / (float(v.max()) or 1.0) * 1.3, 0, 1) * 255).astype(np.uint8)
    cb = (f[..., 2] - luma) / 1.8556
    cr = (f[..., 0] - luma) / 1.5748
    x = np.clip((cb * zoom + .5) * 255 + .5, 0, 255).astype(np.int32)
    y = np.clip((.5 - cr * zoom) * 255 + .5, 0, 255).astype(np.int32)
    cell = (y * 256 + x).ravel()
    count = np.bincount(cell, minlength=65536)[:65536].astype(np.float32)
    flat = rgb.reshape(-1, 3).astype(np.float32)
    mean = np.stack([np.bincount(cell, flat[:, c], minlength=65536)[:65536] for c in range(3)], -1)
    mean /= np.maximum(count, 1)[:, None]
    # Teinte des pixels gardée, clarté remontée (sinon les tons sombres disparaissent sur le fond noir).
    mean = mean * (255.0 / np.maximum(mean.max(1, keepdims=True), 1.0)) * .75 + 255 * .25
    lv = np.log1p(count)
    alpha = np.clip(lv / (float(lv.max()) or 1.0) * 1.4, 0, 1)
    vec = np.zeros((65536, 4), np.uint8)                          # BGRA prémultiplié
    vec[:, 0] = (mean[:, 2] * alpha).astype(np.uint8)
    vec[:, 1] = (mean[:, 1] * alpha).astype(np.uint8)
    vec[:, 2] = (mean[:, 0] * alpha).astype(np.uint8)
    vec[:, 3] = (alpha * 255).astype(np.uint8)
    vec = vec.reshape(256, 256, 4)
    image = QImage(vec.data, 256, 256, 256 * 4, QImage.Format_ARGB32_Premultiplied).copy()
    return dict(wave_alpha=np.ascontiguousarray(wave_alpha), vec=image)


def analyze_rgb(rgb, count=16, exclude_black=False, exclude_white=False, cancelled=None):
    rgb = np.asarray(rgb, dtype=np.float64).reshape(-1, 3)
    if not len(rgb):
        return dict(colors=[], tones=[], histogram=[], luminance_histogram=[], samples=0)
    # Échantillonnage réparti sur TOUTE l'image, sans moyenner les frontières
    # des aplats : le filtre bilinéaire inventerait des teintes intermédiaires.
    rgb = rgb[np.linspace(0,len(rgb)-1,min(4096,len(rgb)),dtype=int)] / 255.0
    linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    lab = np.cbrt(linear @ _M1) @ _M2
    original_rgb, original_linear = rgb, linear
    keep = np.ones(len(rgb),dtype=bool)
    if exclude_black:
        keep &= rgb.max(axis=1) > 8/255
    if exclude_white:
        keep &= rgb.min(axis=1) < 247/255
    rgb, lab = rgb[keep], lab[keep]
    if not len(rgb):
        result = analyze_rgb(original_rgb*255,count,cancelled=cancelled)
        result['colors'] = result['subs'] = []
        return result
    count = max(1, min(int(count), len(lab), 32))
    centers = _kmeans(lab, count, cancelled)
    if centers is None:
        return None
    # Réassigner aux centres finaux : les pourcentages suivent le dernier pas.
    labels = ((lab[:,None] - centers[None]) ** 2).sum(2).argmin(1)
    colors, subs, kept, sub_centers = [], [], [], []
    for i in np.argsort(centers[:,0]):
        chosen = labels == i
        if chosen.any():
            colors.append((tuple(np.rint(rgb[chosen].mean(0) * 255).astype(int)), float(chosen.mean())))
            kept.append(centers[i])
            # Nuances : SUBS sous-groupes des échantillons de la couleur (moins s'ils sont trop peu), par clarté.
            part, part_rgb = lab[chosen], rgb[chosen]
            inner = _kmeans(part, min(SUBS, len(part)), cancelled)
            if inner is None:
                return None
            inner_labels = ((part[:,None] - inner[None]) ** 2).sum(2).argmin(1)
            shades, shade_centers = [], []
            for k in np.argsort(inner[:,0]):
                mine = inner_labels == k
                if mine.any():
                    shades.append((tuple(np.rint(part_rgb[mine].mean(0) * 255).astype(int)),
                                   float(mine.sum() / len(lab))))
                    shade_centers.append(inner[k])
            subs.append(shades)
            sub_centers.append(np.array(shade_centers))
    rgb, linear = original_rgb, original_linear
    y = linear @ np.array([.2126,.7152,.0722])
    tones = []
    for mask in (y < .09, (y >= .09) & (y < .5), y >= .5):
        tones.append((tuple(np.rint(rgb[mask].mean(0) * 255).astype(int)) if mask.any() else None,
                      float(mask.mean())))
    return dict(colors=colors, subs=subs, centers=np.array(kept), sub_centers=sub_centers, tones=tones,
                samples=len(rgb), luminance=dict(mean=float(y.mean()),
                minimum=float(y.min()),maximum=float(y.max()),
                black_clip=float((rgb <= 0).any(axis=1).mean()),white_clip=float((rgb >= 1).any(axis=1).mean()),
                percentiles=np.percentile(y, [1,5,50,95,99]).tolist()),
                luminance_histogram=np.histogram(y,bins=256,range=(0,1))[0].tolist(),
                histogram=[np.histogram(rgb[:,c], bins=256, range=(0,1))[0].tolist() for c in range(3)])


class _Signals(QObject):
    ready = Signal(int, object)
    failed = Signal(int, str)


class _Task(QRunnable):
    def __init__(self, image, count, revision, signals, options=None, cancel=None):
        super().__init__()
        self.image, self.count, self.revision, self.signals = image, count, revision, signals
        self.options = options or {}
        self.cancel = cancel or threading.Event()

    def run(self):
        try:
            if self.cancel.is_set():
                return
            image = self.image
            region = self.options.get('region')
            if region is not None:
                image = image.copy(region)
            if image.width()>256 or image.height()>256:
                image = image.scaled(256,256,Qt.KeepAspectRatio,Qt.FastTransformation)
            image = image.convertToFormat(QImage.Format_RGBA8888)
            rgba = np.ndarray((image.height(),image.width(),4), dtype=np.uint8,
                              buffer=image.constBits(), strides=(image.bytesPerLine(),4,1))
            # Ne pas compter les couleurs cachées derrière un alpha nul.
            pixels = rgba[:,:,:3][rgba[:,:,3] > 0]
            result = analyze_rgb(pixels, self.count, self.options.get('exclude_black',False),
                                 self.options.get('exclude_white',False),self.cancel.is_set)
            if result is not None and len(pixels) and not self.cancel.is_set():
                # Histogramme sur TOUS les pixels visibles du proxy réduit (pas les 4096 échantillons de la
                # palette) ; Y′ = luma ENCODÉE (axe 0-255), distincte du Y linéaire des statistiques.
                luma = np.clip((pixels.astype(np.float32) @ _LUMA.astype(np.float32) + .5).astype(np.int32), 0, 255)
                result['hist'] = [np.bincount(pixels[:, c], minlength=256)[:256] for c in range(3)] + [
                    np.bincount(luma, minlength=256)[:256]]
                # Waveform / vectorscope : spatiaux, seulement sur une région entièrement opaque.
                if self.options.get('scopes', True) and (rgba[:,:,3] == 255).all():
                    result['scopes'] = scope_data(rgba[:,:,:3], self.options.get('vec_zoom', 1.6))
                # « Localiser sur l'image » : couleur / nuance de chaque pixel de TOUTE l'image (pas seulement la
                # région), à la taille d'affichage (≤ 1024 px).
                if self.options.get('labels', True) and result.get('colors') and not self.cancel.is_set():
                    result['iso'] = self._labels(result)
            if result is not None and not self.cancel.is_set():
                self.signals.ready.emit(self.revision, result)
        except Exception as exc:
            self.signals.failed.emit(self.revision,str(exc))

    def _labels(self, result):
        image = self.image
        if image.width() > 1024 or image.height() > 1024:
            image = image.scaled(1024, 1024, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        image = image.convertToFormat(QImage.Format_RGBA8888)
        rgba = np.ndarray((image.height(), image.width(), 4), dtype=np.uint8, buffer=image.constBits(),
                          strides=(image.bytesPerLine(), 4, 1)).copy()
        return dict(rgba=rgba, labels=label_map(rgba[..., :3], result['centers'], result['sub_centers']))


class _Image(QWidget):
    sampled = Signal(object)
    regionChanged = Signal(object)
    def __init__(self, parent):
        super().__init__(parent)
        self.image = QImage()
        self.natural_width = 1500
        self.region = None
        self.start = None
        self.setMouseTracking(True)
        self.setToolTip('Clic : pipette sRGB. Glisser : analyser une région. Double-clic : image entière.')

    def image_rect(self):
        if self.image.isNull():
            return QRectF()
        size = self.image.size().scaled(min(1500,self.width(),self.image.width(),self.natural_width),self.height(),Qt.KeepAspectRatio)
        return QRectF((self.width()-size.width())/2,(self.height()-size.height())/2,size.width(),size.height())

    def pixel_at(self, position):
        rect = self.image_rect()
        if not rect.contains(position) or rect.isEmpty():
            return None
        return (min(self.image.width()-1,int((position.x()-rect.x())*self.image.width()/rect.width())),
                min(self.image.height()-1,int((position.y()-rect.y())*self.image.height()/rect.height())))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start = self.pixel_at(event.position())
            if self.start is not None:
                self.sampled.emit(self.image.pixelColor(*self.start))

    def mouseReleaseEvent(self, event):
        end = self.pixel_at(event.position())
        if self.start is not None and end is not None:
            x,y = self.start
            if abs(end[0]-x)+abs(end[1]-y)>4:
                from PySide6.QtCore import QRect
                self.region = QRect(min(x,end[0]),min(y,end[1]),abs(end[0]-x)+1,abs(end[1]-y)+1)
                self.regionChanged.emit(self.region)
                self.update()
        self.start = None

    def mouseDoubleClickEvent(self,event):
        self.region = None
        self.regionChanged.emit(None)
        self.update()
    def paintEvent(self, event):
        if self.image.isNull():
            return
        p = QPainter(self)
        rect = self.image_rect()
        p.drawImage(rect,self.image)
        if self.region is not None:
            p.setPen(QPen(QColor('#ffffff'),1))
            p.drawRect(QRectF(rect.x()+self.region.x()*rect.width()/self.image.width(),
                             rect.y()+self.region.y()*rect.height()/self.image.height(),
                             self.region.width()*rect.width()/self.image.width(),
                             self.region.height()*rect.height()/self.image.height()))
