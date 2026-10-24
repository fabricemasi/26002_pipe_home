"""Fenêtre d'export du module vidéo : la fenêtre « Changement de style à la volée » (briques des réglages : mêmes
champs, mêmes tableaux, mise en forme retenue), avec ses lignes d'export, une ligne « Exporter / Annuler » et la
progression. Les derniers paramètres sont retenus (`video_export_last`, état temps réel). Les options affichées
suivent le format et le codec : les encodeurs absents du FFmpeg installé ne sont pas proposés, RIFE seulement s'il
est installé."""
from __future__ import annotations

from pathlib import Path

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QWidget

import settings_window_v2 as v2
from settings_quick_style import QuickStyleWindow
from settings_store import M
from video import export as vexport
from video import media as vmedia

FORMATS = (("mp4", "MP4"), ("mov", "MOV"), ("mkv", "MKV"), ("webm", "WEBM"), ("exr", "Séquence EXR"),
           ("tiff", "Séquence TIFF"), ("png", "Séquence PNG"), ("dpx", "Séquence DPX"))
CODEC_LABELS = {"h264": "H.264", "h265": "H.265 / HEVC", "prores": "ProRes", "dnxhr": "DNxHR", "av1": "AV1",
                "vp9": "VP9"}


def _button(text: str, accent: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setCursor(Qt.ArrowCursor)
    bg = M["accent"] if accent else M.get("field_bg", "#2a2d31")
    fg = M["accent_fg"] if accent else M.get("value_fg", "#d6d9dc")
    button.setStyleSheet(f"QPushButton {{ background: {bg}; color: {fg}; border: 1px solid {M['field_border']}; "
                         f"border-radius: 4px; padding: 4px 14px; }}"
                         f"QPushButton:disabled {{ color: {M.get('dim', '#666')}; }}")
    return button


class ExportWindow(QuickStyleWindow):
    def __init__(self, pane, settings: dict):
        self.pane = pane
        last = dict(settings.get("video_export_last") or {})
        get = lambda k, d: last.get(k, settings.get(k, d))      # noqa: E731
        codecs = vexport.available_codecs() or ["h264"]
        rife = vexport.rife_path(str(settings.get("video_rife_path") or ""))
        src = pane.source
        # Dossier : le dernier utilisé (retenu), sinon celui des réglages, sinon celui du média.
        folder = last.get("x_dir") or settings.get("video_export_dir", "") or (str(pane.path.parent) if pane.path
                                                                               else "")
        name = f"{(src.sequence.head.rstrip('._-') if getattr(src, 'sequence', None) else pane.path.stem)}_export" \
            if pane.path else "export"
        has_range = pane.timeline.in_point is not None or pane.timeline.out_point is not None
        values = {
            "x_fmt": get("video_export_format", "mp4"), "x_codec": get("video_export_codec", "h264")
            if get("video_export_codec", "h264") in codecs else codecs[0],
            "x_profile": last.get("x_profile", "3"), "x_crf": int(get("video_export_crf", 18)),
            "x_preset": get("video_export_preset", "medium"), "x_bitrate": int(last.get("x_bitrate", 0)),
            "x_width": int(last.get("x_width", 0)), "x_height": int(last.get("x_height", 0)),
            "x_fps": last.get("x_fps", "source"), "x_fps_mode": get("video_export_fps_mode", "resample"),
            "x_interp": get("video_export_interp", "minterpolate"), "x_content": get("video_export_color", "display"),
            "x_lut": bool(get("video_export_lut", True)), "x_depth": get("video_export_depth", "half"),
            "x_alpha": bool(last.get("x_alpha", False)), "x_audio": bool(get("video_export_audio", True)),
            "x_range": "selection" if has_range else "all", "x_numbering": get("video_export_numbering", "source"),
            "x_overwrite": bool(get("video_export_overwrite", False)), "x_dir": folder, "x_name": name,
            "x_all_layers": bool(last.get("x_all_layers", False)),
        }
        if values["x_interp"] == "rife" and not rife:
            values["x_interp"] = "minterpolate"
        interp = [("minterpolate", "Flux optique (FFmpeg minterpolate)"), ("blend", "Fondu (FFmpeg)")]
        interp.append(("rife", "IA : RIFE (rife-ncnn-vulkan)") if rife else ("minterpolate", "RIFE : non installé"))
        fps = (("source", "Celle de la source"),) + tuple(vmedia.FPS_CHOICES)
        S = v2.Spec
        specs = [
            S("x_fmt", "Format", "choice", values["x_fmt"], {"choices": FORMATS}),
            S("x_codec", "Codec (vidéo)", "choice", values["x_codec"],
              {"choices": tuple((c, CODEC_LABELS[c]) for c in codecs)}),
            S("x_profile", "Profil (ProRes / DNxHR)", "choice", values["x_profile"],
              {"choices": vexport.PRORES_PROFILES + vexport.DNXHR_PROFILES}),
            S("x_crf", "Qualité (CRF, plus bas = meilleur)", "slider", values["x_crf"], {"min": 0, "max": 51, "unit": ""}),
            S("x_preset", "Preset d'encodage", "choice", values["x_preset"],
              {"choices": tuple((p, p) for p in vexport.X26X_PRESETS)}),
            S("x_bitrate", "Débit (0 = selon la qualité)", "slider", values["x_bitrate"],
              {"min": 0, "max": 200000, "unit": "kb/s"}),
            S("x_width", "Largeur (0 = source)", "slider", values["x_width"], {"min": 0, "max": 8192}),
            S("x_height", "Hauteur (0 = selon le ratio)", "slider", values["x_height"], {"min": 0, "max": 8192}),
            S("x_fps", "FPS", "choice", values["x_fps"], {"choices": fps}),
            S("x_fps_mode", "Changement de FPS", "choice", values["x_fps_mode"],
              {"choices": (("resample", "Rééchantillonner (durée gardée, images dupliquées / retirées)"),
                           ("reinterpret", "Réinterpréter (mêmes images, durée changée)"),
                           ("interpolate", "Générer des images intermédiaires (durée gardée)")), "width": 300}),
            S("x_interp", "Méthode d'interpolation", "choice", values["x_interp"],
              {"choices": tuple(interp), "width": 300}),
            S("x_content", "Contenu", "choice", values["x_content"],
              {"choices": (("display", "Tel qu'affiché (corrections, LUT, affichage OCIO)"),
                           ("working", "Linéaire corrigé (séquences EXR / TIFF flottant)"),
                           ("data", "Données source, sans aucune transformation")), "width": 300}),
            S("x_lut", "Inclure la LUT", "bool", values["x_lut"]),
            S("x_depth", "Profondeur (séquences)", "choice", values["x_depth"],
              {"choices": (("half", "16 bits flottants (EXR half)"), ("float", "32 bits flottants"),
                           ("16", "16 bits entiers"), ("8", "8 bits"))}),
            S("x_alpha", "Alpha (EXR, TIFF, PNG, ProRes 4444, VP9)", "bool", values["x_alpha"]),
            S("x_audio", "Audio (vidéo source)", "bool", values["x_audio"]),
            S("x_range", "Plage", "choice", values["x_range"],
              {"choices": (("selection", "Sélection IN / OUT"), ("all", "Média complet"))}),
            S("x_all_layers", "Tous les calques (AOV) et métadonnées (EXR -> EXR, sans transformation)", "bool",
              values["x_all_layers"]),
            S("x_numbering", "Numérotation (séquences)", "choice", values["x_numbering"],
              {"choices": (("source", "Celle de la source"), ("1", "À partir de 1"), ("1001", "À partir de 1001"))}),
            S("x_overwrite", "Écraser les fichiers existants", "bool", values["x_overwrite"]),
            S("x_name", "Nom", "text", values["x_name"]),
        ]
        # Dossier : zone de saisie (chemin tapé ou collé, réseau compris) + « Parcourir… » (sélecteur natif).
        from settings_cells import _TextField
        folder_row = QWidget()
        frow = QHBoxLayout(folder_row)
        frow.setContentsMargins(0, 0, 0, 0)
        frow.setSpacing(6)
        self.dir_field = _TextField(values["x_dir"], width=300)
        self.dir_field.setToolTip("Dossier de destination (chemin local ou réseau, ex. \\\\serveur\\partage)")
        browse = _button("Parcourir…")
        browse.clicked.connect(self._browse_folder)
        frow.addWidget(self.dir_field)
        frow.addWidget(browse)
        frow.addStretch(1)
        specs.insert(len(specs) - 1, ("Dossier", folder_row, lambda _w: {"x_dir": self.dir_field.text().strip()}))
        actions = QWidget()
        row = QHBoxLayout(actions)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.export_btn = _button("Exporter", accent=True)
        self.cancel_btn = _button("Annuler l'export")
        self.cancel_btn.setEnabled(False)
        row.addWidget(self.export_btn)
        row.addWidget(self.cancel_btn)
        row.addStretch(1)
        self.progress = QLabel("")
        self.progress.setWordWrap(True)
        self.progress.setMinimumWidth(280)
        self.progress.setStyleSheet(f"color: {M.get('value_fg', '#d6d9dc')}; background: transparent;")
        specs += [("Action", actions, lambda _w: {}), ("Progression", self.progress, lambda _w: {})]
        super().__init__("Module vidéo : export", specs, values, title="Exporter", settings=settings,
                         parent=pane.window())
        self._values = values
        self.styleChanged.connect(self._remember)
        self.dir_field.editingFinished.connect(lambda: self._remember({"x_dir": self.dir_field.text().strip()}))
        self.export_btn.clicked.connect(self._start)
        self.cancel_btn.clicked.connect(self._cancel)
        self._job = None
        job = getattr(pane, "_export_job", None)
        if job is not None and not job.cancelled and job.thread_alive():
            self._attach(job)

    def _browse_folder(self):
        """Sélecteur de dossier NATIF de Windows (disques, réseau, chemins Unicode) ; le choix va dans le champ."""
        start = self.dir_field.text().strip()
        if not start or not os.path.isdir(start):
            start = str(self.pane.path.parent) if self.pane.path else ""
        chosen = QFileDialog.getExistingDirectory(self, "Dossier de destination de l'export", start)
        if chosen:
            self.dir_field.setText(os.path.normpath(chosen))
            self._remember({"x_dir": self.dir_field.text()})

    def _remember(self, values: dict):
        self._values.update(values)
        from video.pane import HOOKS
        hook = HOOKS.get("save_state")
        if hook is not None:
            keep = {k: v for k, v in self._values.items() if k != "x_name"}     # dossier retenu, pas le nom
            try:
                hook("video_export_last", keep)
            except Exception:                                # noqa: BLE001
                pass

    def build_settings(self) -> vexport.ExportSettings | None:
        pane = self.pane
        values = dict(self._values)
        values.update(self.style())
        fmt = values["x_fmt"]
        folder_text = (values.get("x_dir") or "").strip() or (str(pane.path.parent) if pane.path else "")
        if not folder_text:
            self.progress.setText("Choisissez un dossier de destination.")
            return None
        folder = Path(folder_text)
        if not folder.is_dir():
            self.progress.setText(f"Dossier introuvable (ou réseau inaccessible) : {folder}")
            return None
        if not os.access(folder, os.W_OK):
            self.progress.setText(f"Dossier en lecture seule : {folder}")
            return None
        name = (values["x_name"] or "export").strip()
        if not name or any(c in name for c in '<>:"/\\|?*'):
            self.progress.setText("Nom de fichier invalide (caractères interdits : < > : \" / \\ | ? *).")
            return None
        ext = vexport.VIDEO_CONTAINERS.get(fmt) or vexport.SEQUENCE_FORMATS.get(fmt, "")
        output = folder / f"{name}{ext}"
        if pane.path is not None and output.resolve() == pane.path.resolve():
            self.progress.setText("Le fichier exporté ne peut pas remplacer l'original.")
            return None
        lo, hi = pane.timeline.range() if values["x_range"] == "selection" else (0, pane.source.frame_count - 1)
        content = values["x_content"]
        if fmt in vexport.VIDEO_CONTAINERS and content == "working":
            content = "display"
        view = pane.view_state(display=False)       # vraies corrections, jamais l'« avant » de comparaison
        if not values["x_lut"]:
            view.lut = None
        view.channel = "rgb"
        view.clipping = False
        fps = None if values["x_fps"] == "source" else vmedia.parse_fps(values["x_fps"])
        codec = values["x_codec"]
        if fmt in vexport.VIDEO_CONTAINERS and fmt not in vexport.CODECS[codec][1]:
            allowed = [c for c, (_e, conts) in vexport.CODECS.items() if fmt in conts]
            self.progress.setText(f"{CODEC_LABELS[codec]} n'est pas permis en {fmt.upper()} "
                                  f"(possibles : {', '.join(CODEC_LABELS[c] for c in allowed)}).")
            return None
        all_layers = bool(values.get("x_all_layers"))
        if all_layers:
            src_ext = pane.path.suffix.lower() if pane.path else ""
            if fmt != "exr" or src_ext != ".exr":
                self.progress.setText("« Tous les calques » : séquence EXR exportée en EXR seulement.")
                return None
            if int(values["x_width"]) or int(values["x_height"]):
                self.progress.setText("« Tous les calques » recopie les images telles quelles : largeur et hauteur "
                                      "à 0.")
                return None
        if fmt not in vexport.VIDEO_CONTAINERS and values["x_fps_mode"] == "interpolate":
            self.progress.setText("Images intermédiaires : réservées aux exports vidéo (les séquences gardent leurs "
                                  "images d'origine).")
            return None
        return vexport.ExportSettings(
            output=output, fmt=fmt, codec=codec, crf=int(values["x_crf"]), preset=values["x_preset"],
            bitrate_kbps=int(values["x_bitrate"]), profile=values["x_profile"], width=int(values["x_width"]),
            height=int(values["x_height"]), fps=fps, fps_mode=values["x_fps_mode"], interp=values["x_interp"],
            content=content, depth=values["x_depth"], alpha=bool(values["x_alpha"]), audio=bool(values["x_audio"]),
            range=(lo, hi), numbering=values["x_numbering"], overwrite=bool(values["x_overwrite"]),
            all_layers=all_layers,
            rife_exe=str(pane._settings.get("video_rife_path") or ""), view=view, pipeline=pane._pipeline,
            missing="hold" if pane._settings.get("video_missing") == "hold" else "black")

    def _start(self):
        pane = self.pane
        if pane.source is None:
            return
        settings = self.build_settings()
        if settings is None:
            return
        try:
            source = pane.source.clone()
        except Exception as exc:                             # noqa: BLE001
            self.progress.setText(f"Source illisible : {exc}")
            return
        job = vexport.ExportJob(source, settings)
        pane._export_job = job
        self._attach(job)
        job.start()

    def _attach(self, job):
        self._job = job
        job.progress.connect(self._on_progress)
        job.finished.connect(self._on_finished)
        self.export_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setText("Démarrage…")

    def _cancel(self):
        if self._job is not None:
            self._job.cancel()
            self.progress.setText("Annulation…")

    def _on_progress(self, done: int, total: int, speed: float, eta: float, state: str):
        import time
        elapsed = time.monotonic() - self._job.started_at if self._job else 0
        rest = f", reste ~{eta:.0f} s" if eta >= 0 else ""
        self.progress.setText(f"{state} : {done} / {total} images — {speed:.1f} img/s, {elapsed:.0f} s écoulées{rest}")

    def _on_finished(self, ok: bool, message: str, path: str):
        self.export_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setText(message + (f"\n{path}" if ok and path else ""))
        self.pane._status(message)
        if self.pane._export_job is self._job:
            self.pane._export_job = None
        self._job = None
