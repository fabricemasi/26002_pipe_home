"""Analyse des pixels d'affichage sRGB : clustering OKLab borné, exécuté en fond.

Les mesures décrivent le proxy affiché ; elles ne mesurent ni la scène ni un signal HDR.
"""
import numpy as np
import threading
from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool, Qt, QRectF, QTimer
from PySide6.QtGui import QImage, QPainter, QColor, QPainterPath, QPen
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSpinBox,
                               QFileDialog, QCheckBox, QComboBox)


def analyze_rgb(rgb, count=16, exclude_black=False, exclude_white=False, cancelled=None):
    rgb = np.asarray(rgb, dtype=np.float64).reshape(-1, 3)
    if not len(rgb):
        return dict(colors=[], tones=[], histogram=[], luminance_histogram=[], samples=0)
    # Échantillonnage réparti sur TOUTE l'image, sans moyenner les frontières
    # des aplats : le filtre bilinéaire inventerait des teintes intermédiaires.
    rgb = rgb[np.linspace(0,len(rgb)-1,min(4096,len(rgb)),dtype=int)] / 255.0
    linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    lms = linear @ np.array([[.4122214708,.2119034982,.0883024619],
                            [.5363325363,.6806995451,.2817188376],
                            [.0514459929,.1073969566,.6299787005]])
    lab = np.cbrt(lms) @ np.array([[.2104542553,1.9779984951,.0259040371],
                                  [.793617785,-2.428592205,.7827717662],
                                  [-.0040720468,.4505937099,-.808675766]])
    original_rgb, original_linear = rgb, linear
    keep = np.ones(len(rgb),dtype=bool)
    if exclude_black:
        keep &= rgb.max(axis=1) > 8/255
    if exclude_white:
        keep &= rgb.min(axis=1) < 247/255
    rgb, lab = rgb[keep], lab[keep]
    if not len(rgb):
        result = analyze_rgb(original_rgb*255,count,cancelled=cancelled)
        result['colors'] = []
        return result
    count = max(1, min(int(count), len(lab), 32))
    centers = [lab[np.argmin(lab[:, 0])]]
    # Initialisation déterministe par distance maximale, puis Lloyd en OKLab.
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
    # Réassigner aux centres finaux : les pourcentages suivent le dernier pas.
    labels = ((lab[:,None] - centers[None]) ** 2).sum(2).argmin(1)
    colors = []
    for i in np.argsort(centers[:,0]):
        chosen = labels == i
        if chosen.any():
            colors.append((tuple(np.rint(rgb[chosen].mean(0) * 255).astype(int)), float(chosen.mean())))
    rgb, linear = original_rgb, original_linear
    y = linear @ np.array([.2126,.7152,.0722])
    tones = []
    for mask in (y < .09, (y >= .09) & (y < .5), y >= .5):
        tones.append((tuple(np.rint(rgb[mask].mean(0) * 255).astype(int)) if mask.any() else None,
                      float(mask.mean())))
    return dict(colors=colors, tones=tones, samples=len(rgb), luminance=dict(mean=float(y.mean()),
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
            if result is not None and self.options.get('scopes') and not self.cancel.is_set():
                from video.scopes import compute, _gray_image
                # Ces scopes décrivent des valeurs ENCODÉES sRGB SDR : Y' est
                # distinct du Y linéaire des statistiques de luminance.
                if (rgba[:,:,3] == 255).all():
                    scopes = compute(rgba[:,:,:3].astype(np.float32)/255)
                    result['scopes'] = dict(hist=scopes['hist'],
                                            images=dict(wave=_gray_image(scopes['wave']),vec=_gray_image(scopes['vec'])))
            if result is not None and not self.cancel.is_set():
                self.signals.ready.emit(self.revision, result)
        except Exception as exc:
            self.signals.failed.emit(self.revision,str(exc))


class _Swatches(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.colors = []
        self.setFixedHeight(68)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        p = QPainter(self)
        for i,(rgb,weight) in enumerate(self.colors):
            p.fillRect(QRectF(i*self.width()/len(self.colors),0,self.width()/len(self.colors)+1,48),QColor(*rgb))

    def mouseMoveEvent(self, event):
        if self.colors:
            rgb,weight = self.colors[min(len(self.colors)-1,int(event.position().x()*len(self.colors)/max(1,self.width())))]
            self.setToolTip(f'{QColor(*rgb).name()} · RGB {rgb} · {weight:.1%} des pixels échantillonnés')

    def mousePressEvent(self, event):
        if self.colors:
            from PySide6.QtWidgets import QApplication
            rgb,_ = self.colors[min(len(self.colors)-1,int(event.position().x()*len(self.colors)/max(1,self.width())))]
            QApplication.clipboard().setText(QColor(*rgb).name())


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


class _Histogram(QWidget):
    """Tracés déjà calculés : aucune analyse de pixels pendant la peinture."""
    def __init__(self,parent):
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.setMaximumHeight(200)
        self.setMouseTracking(True)
        self.result = {}
        self.enabled = [True,True,True,False]
        self.logarithmic = False

    def paintEvent(self,event):
        p = QPainter(self)
        rect = self.rect().adjusted(35,12,-10,-22)
        p.fillRect(rect,QColor('#171717'))
        p.setPen(QColor('#aaaaaa'))
        p.drawRect(rect)
        p.drawText(0,12,'Pixels')
        p.drawText(rect.left(),self.height()-4,'0')
        p.drawText(rect.right()-90,self.height()-4,'255 RGB / 1 Y')
        arrays = self.result.get('histogram',[])+[self.result.get('luminance_histogram',[])]
        peak = max((max(a) for a,on in zip(arrays,self.enabled) if on and a),default=1) or 1
        denominator = np.log1p(peak) if self.logarithmic else peak
        for values,on,color in zip(arrays,self.enabled,('#ff6868','#66dd88','#669dff','#ffffff')):
            if not on or not values:
                continue
            path = QPainterPath()
            for i,value in enumerate(values):
                value = np.log1p(value) if self.logarithmic else value
                x,y = rect.x()+i*rect.width()/255,rect.bottom()-value*rect.height()/denominator
                path.moveTo(x,y) if i==0 else path.lineTo(x,y)
            p.setPen(QPen(QColor(color),1))
            p.drawPath(path)

    def mouseMoveEvent(self,event):
        rect = self.rect().adjusted(35,12,-10,-22)
        index = max(0,min(255,round((event.position().x()-rect.x())*255/max(1,rect.width()))))
        arrays = self.result.get('histogram',[])+[self.result.get('luminance_histogram',[])]
        self.setToolTip(f'Niveau RGB {index} · Y {index/255:.4f}\n'+' · '.join(
            f'{name} : {values[index]} pixels' for name,values in zip(('R','V','B','Y'),arrays) if values))


class ColorAnalysis(QWidget):
    back = Signal()
    settingsChanged = Signal(str, object)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.revision = 0
        self.cancel = threading.Event()
        self.latest = {}
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.signals = _Signals(self)
        self.signals.ready.connect(self._ready)
        self.signals.failed.connect(self._failed)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(100)
        self.debounce.timeout.connect(self._start)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        back = QPushButton('Retour au moodboard',self)
        back.clicked.connect(self.back)
        row.addWidget(back)
        self.title = QLabel(self)
        row.addWidget(self.title,1)
        row.addWidget(QLabel('Couleurs',self))
        self.count = QSpinBox(self)
        self.count.setRange(2,32)
        self.count.setValue(16)
        self.count.valueChanged.connect(self._submit)
        row.addWidget(self.count)
        export = QPushButton('Exporter la palette…', self)
        export.clicked.connect(self.export_palette)
        row.addWidget(export)
        matching = QPushButton('Matching / LUT…',self)
        matching.clicked.connect(self._open_matching)
        row.addWidget(matching)
        from video.help_ui import HelpController,annotate
        ancestor = self.parentWidget()
        self.help = None
        while ancestor is not None and self.help is None:
            self.help = getattr(ancestor,'_color_help',None)
            ancestor = ancestor.parentWidget()
        if self.help is None:
            self.help = HelpController(self)
        glossary = QPushButton('Aide / glossaire',self)
        glossary.clicked.connect(lambda:self.help.open_glossary())
        row.addWidget(glossary)
        layout.addLayout(row)
        options = QHBoxLayout()
        self.black = QCheckBox('Exclure noirs ≤ 8 (palette)',self)
        self.white = QCheckBox('Exclure blancs ≥ 247 (palette)',self)
        self.order = QComboBox(self)
        self.order.addItems(['Clarté','Proportion'])
        self.order.currentIndexChanged.connect(self._sort_palette)
        for control in (self.black,self.white):
            options.addWidget(control)
            control.toggled.connect(self._submit)
        options.addWidget(QLabel('Ordre',self))
        options.addWidget(self.order)
        options.addStretch(1)
        layout.addLayout(options)
        self.image = _Image(self)
        self.image.regionChanged.connect(self._submit)
        self.image.sampled.connect(self._sampled)
        layout.addWidget(self.image,1)
        self.palette = _Swatches(self)
        layout.addWidget(self.palette)
        self.tones = QLabel(self)
        self.tones.setTextFormat(Qt.RichText)
        layout.addWidget(self.tones)
        self.statistics = QLabel(self)
        layout.addWidget(self.statistics)
        self.sample = QLabel('Pipette : clic sur l’image · Région : glisser · Image entière : double-clic',self)
        layout.addWidget(self.sample)
        histogram_controls = QHBoxLayout()
        self.histogram = _Histogram(self)
        self.scopes_toggle = QCheckBox('Waveform / vectorscope',self)
        self.scopes_toggle.toggled.connect(self._show_scopes)
        histogram_controls.addWidget(self.scopes_toggle)
        for i,name in enumerate(('Rouge','Vert','Bleu','Luminance Y')):
            checkbox = QCheckBox(name,self)
            checkbox.setChecked(self.histogram.enabled[i])
            checkbox.toggled.connect(lambda on,c=i: self._histogram_channel(c,on))
            histogram_controls.addWidget(checkbox)
        log = QCheckBox('Échelle logarithmique',self)
        log.toggled.connect(self._histogram_log)
        histogram_controls.addWidget(log)
        layout.addLayout(histogram_controls)
        layout.addWidget(self.histogram)
        from video.scopes import ScopesPanel, SIZE
        self.scopes = ScopesPanel(self)
        self.scopes.setMinimumSize(SIZE*3+40,SIZE+28)
        self.scopes.setMaximumHeight(SIZE+28)
        self.scopes.setToolTip('Waveform : Y′ encodé BT.709, position horizontale dans la région. '
                               'Vectorscope : Cb/Cr BT.709, gain 1,8. Proxy SDR sRGB ; pas une mesure HDR. '
                               'Scopes indisponibles pour une région partiellement transparente.')
        layout.addWidget(self.scopes)
        layout.addWidget(QLabel('Pixels du proxy affiché · hypothèse sRGB SDR · OKLab · clic sur une couleur : copier HEX',self))
        for widget,key in ((self.count,'palette'),(self.black,'palette'),(self.white,'palette'),
                           (self.order,'palette'),(self.palette,'palette'),(self.image,'region'),
                           (self.sample,'region'),(self.histogram,'histogram'),(log,'histogram'),
                           (self.statistics,'histogram'),(self.scopes,'scopes'),(self.scopes_toggle,'scopes'),
                           (matching,'matching'),(export,'palette')):
            annotate(widget,key)
        self.setToolTip('Maintenir Ctrl + Shift sur un outil pour son aide détaillée ; F1 pour l’explication complète.')

    def show_image(self, image, title):
        self.title.setText(title)
        self.image.image = image.copy()
        self.image.region = None
        self.palette.colors = []
        self.palette.update()
        self.latest = {}
        self.histogram.result = {}
        self.histogram.update()
        self.scopes.set_result(None)
        self.statistics.clear()
        self.image.update()
        self._submit()

    def _submit(self, *_):
        if self.image.image.isNull():
            return
        self.cancel.set()
        self.revision += 1
        self.pool.clear()
        self.debounce.start()

    def _start(self):
        self.cancel = threading.Event()
        self.tones.setText('Analyse colorimétrique en cours…')
        options = dict(region=self.image.region,exclude_black=self.black.isChecked(),exclude_white=self.white.isChecked(),
                       scopes=self.scopes_toggle.isChecked())
        self.pool.start(_Task(self.image.image, self.count.value(), self.revision, self.signals,options,self.cancel))
        for key,value in (('video_analysis_colors',self.count.value()),('video_analysis_exclude_black',self.black.isChecked()),
                          ('video_analysis_exclude_white',self.white.isChecked())):
            self.settingsChanged.emit(key,value)

    def stop(self):
        self.help.dismiss()
        self.cancel.set()
        self.debounce.stop()
        self.revision += 1
        self.pool.clear()

    def apply_settings(self,settings):
        self.settings = dict(settings)
        self.help.settings = self.settings
        for control,key,default in ((self.count,'video_analysis_colors',16),(self.black,'video_analysis_exclude_black',False),
                                    (self.white,'video_analysis_exclude_white',False)):
            control.blockSignals(True)
            if isinstance(control,QSpinBox):
                control.setValue(settings.get(key,default))
            else:
                control.setChecked(settings.get(key,default))
            control.blockSignals(False)

    def _failed(self, revision, message):
        if revision == self.revision:
            self.tones.setText('Analyse impossible : '+message)

    def _sampled(self,color):
        self.sample.setText(f'Pipette sRGB : {color.name()} · RGB {color.red()}, {color.green()}, {color.blue()} · '
                           f'HSV {max(0,color.hsvHue())}°, {color.hsvSaturationF():.1%}, {color.valueF():.1%}')

    def _histogram_channel(self,index,on):
        self.histogram.enabled[index] = on
        self.histogram.update()

    def _histogram_log(self,on):
        self.histogram.logarithmic = on
        self.histogram.update()

    def _show_scopes(self,on):
        self.scopes.setVisible(on)
        self._submit()

    def _sort_palette(self,*_):
        self.palette.colors = list(self.latest.get('colors',[]))
        if self.order.currentIndex()==1:
            self.palette.colors.sort(key=lambda item:item[1],reverse=True)
        self.palette.update()

    def _ready(self, revision, result):
        if revision != self.revision:
            return
        self.latest = result
        self._sort_palette()
        self.histogram.result = result
        self.histogram.update()
        self.scopes.set_result(result.get('scopes'))
        labels = ('Ombres (Y < 0,09)', 'Tons moyens (0,09 ≤ Y < 0,5)', 'Hautes lumières (Y ≥ 0,5)')
        self.tones.setText(' &nbsp; | &nbsp; '.join(
            f'{name} : <span style="color:{QColor(*rgb).name()}">■</span> {QColor(*rgb).name()} · {weight:.1%}'
            if rgb else f'{name} : aucun pixel' for name,(rgb,weight) in zip(labels,result['tones'])))
        stats = result.get('luminance')
        if stats:
            values = ' · '.join(f'P{p} {v:.4f}' for p,v in zip((1,5,50,95,99),stats['percentiles']))
            self.statistics.setText(f'Luminance linéaire relative Y (sRGB / Rec.709) : moyenne {stats["mean"]:.4f} · {values}')
            self.statistics.setToolTip(f'Y min {stats["minimum"]:.5f}, max {stats["maximum"]:.5f}\n'
                                       f'Pixels ayant au moins un canal à 0 : {stats["black_clip"]:.1%}\n'
                                       f'Pixels ayant au moins un canal à 255 : {stats["white_clip"]:.1%}\n'
                                       f'{result["samples"]} pixels échantillonnés ; hors région et exclusions de palette traités séparément.')
        else:
            self.statistics.clear()
            self.tones.setText('Aucun pixel visible dans cette région')

    def export_palette(self):
        if not self.palette.colors:
            return
        filename, _ = QFileDialog.getSaveFileName(self, 'Exporter la palette', 'palette.json',
                                                 'JSON (*.json);;CSS (*.css);;PNG (*.png)')
        if not filename:
            return
        import json
        from pathlib import Path
        from PySide6.QtWidgets import QMessageBox
        path = Path(filename)
        colors = [dict(hex=QColor(*rgb).name(), rgb=[int(v) for v in rgb], weight=weight)
                  for rgb,weight in self.palette.colors]
        try:
            if path.suffix.lower() == '.png':
                image = QImage(len(colors)*80,80,QImage.Format_RGB888)
                painter = QPainter(image)
                for i,item in enumerate(colors):
                    painter.fillRect(i*80,0,80,80,QColor(item['hex']))
                painter.end()
                if not image.save(str(path),'PNG'):
                    raise OSError('Impossible de sauvegarder la palette')
            elif path.suffix.lower() == '.css':
                path.write_text(':root {\n'+'\n'.join(f'  --palette-{i+1}: {item["hex"]};' for i,item in enumerate(colors))+'\n}\n',encoding='utf-8')
            else:
                path.write_text(json.dumps(dict(space='sRGB SDR (hypothèse du proxy affiché)',
                                                clustering='OKLab',colors=colors),indent=2),encoding='utf-8')
        except OSError as exc:
            QMessageBox.warning(self,'Export de palette',str(exc))

    def _open_matching(self):
        if self.image.image.isNull():
            return
        from video.matching_ui import MatchingDialog
        dialog = getattr(self,'matching_dialog',None)
        if dialog is not None and dialog.isVisible():
            dialog.raise_()
            return
        if dialog is not None:
            dialog.source = self.image.image.copy()
            dialog.preview.image = dialog.source
            dialog.reference = None
            dialog.result = None
            dialog.model = None
            dialog.preset_model = None
            dialog.paths.setText('Source : proxy du moodboard · Référence : à choisir')
            dialog.status.setText('Choisir une référence pour calculer le matching.')
            dialog.export.setEnabled(False)
            dialog.preview.update()
        else:
            self.matching_dialog = MatchingDialog(self.image.image,self,getattr(self,'settings',{}))
            self.matching_dialog.settingsChanged.connect(self.settingsChanged.emit)
        self.matching_dialog.show()
