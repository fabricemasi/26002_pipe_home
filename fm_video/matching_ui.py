"""Matching SDR explicite, prévisualisation et export en fond, sans modifier les médias."""
import threading
import json
from pathlib import Path
import numpy as np
from PySide6.QtCore import QObject,Signal,QRunnable,QThreadPool,QTimer,Qt
from PySide6.QtGui import QImage,QImageReader,QColorSpace
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,QComboBox,
                               QSpinBox,QCheckBox,QFileDialog)
from fm_video.matching import Match,fit_pair,fit_distribution,export_cube


def _rgb(image):
    if image.colorSpace().isValid():
        image = image.convertedToColorSpace(QColorSpace(QColorSpace.SRgb))
    image = image.convertToFormat(QImage.Format_RGBA8888)
    pixels = np.ndarray((image.height(),image.width(),4),dtype=np.uint8,
                        buffer=image.constBits(),strides=(image.bytesPerLine(),4,1))
    if (pixels[:,:,3]<255).any():
        raise ValueError('Le matching attend des images opaques. Aplatir la transparence dans un espace déclaré.')
    return pixels[:,:,:3].astype(np.float32)/255


def _image(rgb):
    data = np.ascontiguousarray(np.rint(np.clip(rgb,0,1)*255),dtype=np.uint8)
    image = QImage(data.data,data.shape[1],data.shape[0],data.strides[0],QImage.Format_RGB888).copy()
    image.setColorSpace(QColorSpace(QColorSpace.SRgb))
    return image


class _Signals(QObject):
    ready = Signal(int,object)
    failed = Signal(int,str)


class _Job(QRunnable):
    def __init__(self,revision,options,signals,cancel,cache):
        super().__init__()
        self.revision,self.options,self.signals,self.cancel,self.cache = revision,options,signals,cancel,cache

    def run(self):
        try:
            o = self.options
            if self.cancel.is_set():
                return
            if 'preview_model' in o:
                model = o['preview_model']
                image = o['source']
                result = dict(model=model,before=image,after=_image(model.apply(_rgb(image),o['intensity'])))
            elif 'preset' in o:
                preset = json.loads(Path(o['preset']).read_text(encoding='utf-8'))
                degree = preset.get('degree')
                coefficients = np.asarray(preset.get('coefficients'),dtype=float)
                if (preset.get('version')!=1 or preset.get('space')!='sRGB encoded SDR [0,1]' or degree not in (1,2)
                        or coefficients.shape != (4 if degree==1 else 10,3) or not np.isfinite(coefficients).all()):
                    raise ValueError('Preset de matching invalide ou espace incompatible.')
                model = Match(coefficients,degree,str(preset.get('method','Preset')),preset.get('metrics',{}))
                image = o['source']
                if not isinstance(image,QImage):
                    reader = QImageReader(image)
                    reader.setAutoTransform(True)
                    image = reader.read()
                if image.isNull():
                    raise ValueError('Image source illisible')
                if image.colorSpace().isValid():
                    image = image.convertedToColorSpace(QColorSpace(QColorSpace.SRgb))
                if image.width()>512 or image.height()>512:
                    image = image.scaled(512,512,Qt.KeepAspectRatio,Qt.FastTransformation)
                intensity = max(0,min(1,float(preset.get('intensity',1))))
                result = dict(model=model,before=image,after=_image(model.apply(_rgb(image),intensity)),intensity=intensity)
            elif 'export' in o:
                model = o['model']
                if Path(o['export']).suffix.lower()=='.json':
                    # Pas d'écriture tant que la demande est périmée.
                    preset = dict(version=1,space='sRGB encoded SDR [0,1]',method=model.method,
                                  coefficients=model.coefficients.tolist(),degree=model.degree,
                                  intensity=o['intensity'],metrics=model.metrics)
                    Path(o['export']).write_text(json.dumps(preset,indent=2),encoding='utf-8')
                    result = dict(export='Preset de matching enregistré')
                else:
                    metrics = export_cube(model,o['export'],o['size'],o['intensity'],self.cancel.is_set)
                    result = dict(export=f'LUT enregistrée · RMSE interpolation {metrics["interpolation_rgb_rmse"]:.6f} '
                                         f'· erreur max {metrics["interpolation_rgb_max"]:.6f}')
            else:
                def load(value):
                    if isinstance(value,QImage):
                        return value.convertedToColorSpace(QColorSpace(QColorSpace.SRgb)) if value.colorSpace().isValid() else value
                    if value not in self.cache:
                        reader = QImageReader(value)
                        reader.setAutoTransform(True)
                        image = reader.read()
                        if image.isNull():
                            raise ValueError(f'Image illisible : {reader.errorString()}')
                        if image.colorSpace().isValid():
                            image = image.convertedToColorSpace(QColorSpace(QColorSpace.SRgb))
                        # Deux médias au plus dans ce cache, relus uniquement si le chemin change.
                        self.cache[value] = image
                    return self.cache[value]
                source,reference = load(o['source']),load(o['reference'])
                if o['paired'] and source.size()!=reference.size():
                    raise ValueError('Paire alignée : dimensions identiques obligatoires. Choisir le fichier source original.')
                # Images d'analyse bornées sans filtrage pour préserver les correspondances.
                def reduce(image):
                    if image.width()>512 or image.height()>512:
                        return image.scaled(512,512,Qt.KeepAspectRatio,Qt.FastTransformation)
                    return image
                x,y = _rgb(reduce(source)),_rgb(reduce(reference))
                if self.cancel.is_set():
                    return
                model = fit_pair(x,y) if o['paired'] else fit_distribution(x,y)
                before = reduce(source)
                result = dict(model=model,before=before,after=_image(model.apply(_rgb(before),o['intensity'])))
            if not self.cancel.is_set():
                self.signals.ready.emit(self.revision,result)
        except InterruptedError:
            pass
        except Exception as exc:
            if not self.cancel.is_set():
                self.signals.failed.emit(self.revision,str(exc))


class MatchingDialog(QDialog):
    settingsChanged = Signal(str,object)
    def __init__(self,image,parent=None,settings=None):
        super().__init__(parent)
        settings = settings or {}
        self.setWindowTitle('Matching colorimétrique / LUT — sRGB SDR')
        self.resize(1000,760)
        self.source = image.copy()
        self.reference = None
        self.revision = 0
        self.cancel = threading.Event()
        self.cache = {}
        self.model = None
        self.preset_model = None
        self.result = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.signals = _Signals(self)
        self.signals.ready.connect(self._ready)
        self.signals.failed.connect(self._failed)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self._compute)
        root = QVBoxLayout(self)
        row = QHBoxLayout()
        for name,slot in (('Source…',lambda:self._choose(False)),('Référence…',lambda:self._choose(True))):
            button = QPushButton(name,self)
            button.clicked.connect(slot)
            row.addWidget(button)
        self.method = QComboBox(self)
        self.method.addItems(['Scènes différentes : statistiques RGB','Paire source / résultat alignée'])
        self.method.setCurrentIndex(int(settings.get('video_match_method',0)))
        self.method.currentIndexChanged.connect(self._schedule)
        row.addWidget(self.method)
        row.addWidget(QLabel('Intensité %',self))
        self.intensity = QSpinBox(self)
        self.intensity.setRange(0,100)
        self.intensity.setValue(int(settings.get('video_match_intensity',100)))
        self.intensity.valueChanged.connect(self._schedule)
        row.addWidget(self.intensity)
        root.addLayout(row)
        self.paths = QLabel('Source : image sélectionnée du moodboard · Référence : à choisir',self)
        self.paths.setWordWrap(True)
        root.addWidget(self.paths)
        root.addWidget(QLabel('sRGB SDR encodé · ICC converti si présent, sinon hypothèse sRGB. '
                              'La paire exige le même cadrage et des pixels correspondants.',self))
        from fm_video.analysis import _Image
        self.preview = _Image(self)
        self.preview.image = image.copy()
        root.addWidget(self.preview,1)
        row = QHBoxLayout()
        self.before = QCheckBox('Avant',self)
        self.before.toggled.connect(self._preview)
        row.addWidget(self.before)
        self.size = QComboBox(self)
        self.size.addItems(['17','33','65','129'])
        self.size.setCurrentText(str(settings.get('video_match_lut_size',33)))
        row.addWidget(QLabel('Résolution LUT',self))
        row.addWidget(self.size)
        self.memory = QLabel(self)
        row.addWidget(self.memory)
        self.size.currentTextChanged.connect(self._memory)
        self._memory()
        self.export = QPushButton('Exporter LUT / preset…',self)
        self.export.setEnabled(False)
        self.export.clicked.connect(self._export)
        row.addWidget(self.export)
        restore = QPushButton('Charger un preset…',self)
        restore.clicked.connect(self._restore)
        row.addWidget(restore)
        root.addLayout(row)
        self.status = QLabel('Choisir une référence pour calculer le matching.',self)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        from fm_video.help_ui import annotate
        for widget,key in ((self.method,'matching'),(self.intensity,'matching'),(self.preview,'matching'),
                           (self.status,'matching'),(self.size,'lut'),(self.export,'lut'),(restore,'lut'),
                           (self.memory,'lut'),(self.before,'matching')):
            annotate(widget,key)
        help_button = QPushButton('Aide matching / LUT',self)
        root.addWidget(help_button)
        help_button.clicked.connect(self._help)

    def _help(self):
        parent = self.parentWidget()
        controller = getattr(parent,'help',None)
        if controller is not None:
            controller.open_glossary('matching')

    def _memory(self,*_):
        n = int(self.size.currentText())
        self.memory.setText(f'Table : {n**3*12/1024**2:.1f} Mio')
        self.settingsChanged.emit('video_match_lut_size',n)

    def _choose(self,reference):
        path,_ = QFileDialog.getOpenFileName(self,'Image de référence' if reference else 'Image source',
                                            '', 'Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)')
        if path:
            self.preset_model = None
            if reference:
                self.reference = path
            else:
                self.source = path
            self.cache.clear()
            self.paths.setText(f'Source : {self.source if isinstance(self.source,str) else "proxy du moodboard"}\n'
                               f'Référence : {self.reference or "à choisir"}')
            self._schedule()

    def _schedule(self,*_):
        self.settingsChanged.emit('video_match_intensity',self.intensity.value())
        self.settingsChanged.emit('video_match_method',self.method.currentIndex())
        self.cancel.set()
        self.revision += 1
        self.model = None
        self.export.setEnabled(False)
        self.pool.clear()
        self.timer.start()

    def _compute(self):
        if self.preset_model is not None and self.result is not None:
            self._start(dict(preview_model=self.preset_model,source=self.result['before'],intensity=self.intensity.value()/100))
            return
        if self.reference is None:
            return
        self.status.setText('Calcul du matching…')
        self._start(dict(source=self.source,reference=self.reference,paired=self.method.currentIndex()==1,
                         intensity=self.intensity.value()/100))

    def _start(self,options):
        self.cancel = threading.Event()
        self.pool.start(_Job(self.revision,options,self.signals,self.cancel,self.cache))

    def _ready(self,revision,result):
        if revision!=self.revision:
            return
        if 'export' in result:
            self.status.setText(result['export'])
            self.export.setEnabled(self.model is not None)
            return
        self.result = result
        self.model = result['model']
        if 'intensity' in result:
            self.preset_model = self.model
            self.intensity.blockSignals(True)
            self.intensity.setValue(round(result['intensity']*100))
            self.intensity.blockSignals(False)
        self.export.setEnabled(True)
        self._preview()
        labels = {'rgb_rmse':'RMSE RGB sur pixels réservés','before_rgb_rmse':'RMSE RGB avant',
                  'out_of_range':'Fraction hors [0,1] avant limitation','validation_pixels':'Pixels réservés',
                  'before_mean_rgb_distance':'Distance des moyennes avant','after_mean_rgb_distance':'Distance des moyennes après'}
        self.status.setText(self.model.method+' · '+' · '.join(f'{labels[k]} : {v:.5g}' for k,v in self.model.metrics.items() if k in labels and isinstance(v,(int,float)))+
                            '\nCes métriques décrivent cette paire ; elles ne garantissent pas le résultat sur une autre scène.')

    def _preview(self,*_):
        if self.result:
            self.preview.image = self.result['before' if self.before.isChecked() else 'after']
            self.preview.update()

    def _failed(self,revision,message):
        if revision==self.revision:
            self.status.setText(message)
            self.export.setEnabled(self.model is not None)

    def _export(self):
        if self.model is None:
            return
        path,_ = QFileDialog.getSaveFileName(self,'Exporter le matching','matching.cube',
                                            'LUT 3D (*.cube);;Preset PIPE FMZ (*.json)')
        if path:
            self.status.setText('Export et vérification de l’interpolation…')
            self.export.setEnabled(False)
            self._start(dict(export=path,model=self.model,size=int(self.size.currentText()),intensity=self.intensity.value()/100))

    def _restore(self):
        path,_ = QFileDialog.getOpenFileName(self,'Preset de matching','','Preset PIPE FMZ (*.json)')
        if path:
            self._schedule()
            self.timer.stop()
            self._start(dict(preset=path,source=self.source))

    def closeEvent(self,event):
        self.cancel.set()
        self.revision += 1
        self.timer.stop()
        self.pool.clear()
        super().closeEvent(event)
