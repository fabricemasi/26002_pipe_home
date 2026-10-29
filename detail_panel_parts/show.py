"""Inspecteur : affichage d'un chemin (show_path), vidéo, nombre d'éléments d'un dossier.

Découpé de detail_panel.py (2026-10-29) ; carte : docs/agents/inspecteur.md."""
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl

from datetime import datetime
from app_style import C, role_color, role_font
from config import (
    ABC_EXTENSIONS, ABR_EXTENSIONS, BLEND_EXTENSIONS, DWG_EXTENSIONS, DXF_EXTENSIONS, EXR_EXTENSIONS, FBX_EXTENSIONS,
    CUBE_EXTENSIONS, RAW_EXTENSIONS, HDR_EXTENSIONS, HOUDINI_SCENE_EXTENSIONS, FONT_EXTENSIONS,
    ILLUSTRATOR_EXTENSIONS, IMAGE_EXTENSIONS, MAYA_SCENE_EXTENSIONS, OBJ_EXTENSIONS, PREVIEW_MAX_HEIGHT,
    PREVIEW_MIN_HEIGHT, PDF_EXTENSIONS, PSD_EXTENSIONS, PUR_PREVIEW_EXTENSIONS, RENDERABLE_3D_EXTENSIONS,
    TEXT_PREVIEW_EXTENSIONS, TX_EXTENSIONS, VIDEO_EXTENSIONS, VIDEO_PLAYBACK_ENABLED, _MANUAL_3D_PREVIEW_MODE,
    _MANUAL_3D_PREVIEW_REQUESTS,
)
from previews import (
    TURNTABLE_EXTENSIONS, _cached_file_image_pixmap, _is_preview_protected, file_image_pixmap, ai_has_pdf_content,
    pdf_page_count,
)
from browser_core import count_entries, entry_is_dir, entry_mtime, entry_size, listed_count, human_size
from preview_column import pur_image_files, pur_embedded_image_ranges, pur_file_major_version, read_text_preview


class ShowMixin:
    """Méthodes de DetailPanel : inspecteur : affichage d'un chemin (show_path), vidéo, nombre d'éléments d'un dossier."""

    def _show_video(self, path: Path):
        """Dimensionne le lecteur video sur la frame deja mise en cache
        (voir file_image_pixmap/_decode_video_frame) — meme calcul que
        _update_preview pour une image fixe — puis lance la lecture,
        silencieuse et en boucle (voir __init__)."""
        static = file_image_pixmap(path)
        avail_w = max(self.width() - 32, 50)
        if static is not None and not static.isNull() and static.width() > 0 and static.height() > 0:
            scale = min(1.0, avail_w / static.width(), PREVIEW_MAX_HEIGHT / static.height())
            self.video_widget.setFixedSize(
                max(1, round(static.width() * scale)), max(1, round(static.height() * scale))
            )
        else:
            self.video_widget.setFixedSize(avail_w, PREVIEW_MIN_HEIGHT)
        self.video_widget.show()
        self._video_player.setSource(QUrl.fromLocalFile(str(path)))
        self._video_player.play()

    def _fill_folder_count(self, path: str, scan=True):
        from previews import is_remote_path
        if getattr(self, "_current_path", None) != path:
            return                                # selection changee entre-temps
        count = listed_count(path)
        if count is None:
            if not scan or is_remote_path(path):
                return
            count = count_entries(Path(path))
        self.values["size"].setText(f"{count} elements")

    def show_path(self, path: Path):
        if getattr(self, "_md_path", None) is not None and Path(self._md_path) != path:
            self._flush_markdown()             # note en cours d'edition : enregistree avant de partir
        self._turntable_timer.stop()
        self.turntable_play_button.setText("▶")
        self._turntable_frame_paths = []
        self._current_path = str(path)
        self._refresh_render_action_buttons()
        # Type, date et taille repris de la lecture du dossier (`os.scandir`) : chaque `is_dir()` / `stat()`
        # etait un aller-retour de plus par clic sur un partage reseau (6 par selection, mesure).
        is_dir = entry_is_dir(path)
        supports_turntable = not is_dir and path.suffix.lower() in TURNTABLE_EXTENSIONS
        try:
            import lightroom_bridge
            lightroom_managed = not is_dir and lightroom_bridge.is_managed(path)
        except (ImportError, OSError, ValueError):
            lightroom_managed = False
        self.lightroom_preview_button.setVisible(lightroom_managed)
        self.lightroom_preview_button.setText("Créer l’aperçu Lightroom")
        self.lightroom_preview_button.setEnabled(True)
        self._set_preview_controls_visible(supports_turntable or lightroom_managed)
        self._set_source_rows_visible(lightroom_managed)
        if lightroom_managed:
            for key in self._SOURCE_ROWS:
                self.values[key].setText("…")
            self._refresh_preview_origin_badge(str(path), force=True)
        preferred_media = self._preview_media_preferences.get(str(path), "image")
        self.preview_media_buttons.get(preferred_media, self.preview_image_button).setChecked(True)
        self.turntable_controls.setVisible(supports_turntable and preferred_media == "turntable")
        self._update_turntable_control_state(False)
        self._pur_image_path = None
        self._pur_image_ranges = []
        self._pur_exported_images = []
        self._pur_image_index = 0
        if self._pur_wanted is not None and self._pur_wanted[0] != str(path):
            self._pur_wanted = None              # rang demande pour une autre planche : oublie
        self._pdf_path = None
        self.pur_navigation.hide()
        self.name.setText(path.name)
        is_renderable_3d = not is_dir and path.suffix.lower() in RENDERABLE_3D_EXTENSIONS
        self.render_protection_toggle.blockSignals(True)
        self.render_protection_toggle.setChecked(
            is_renderable_3d and _is_preview_protected(path)
        )
        self.render_protection_toggle.blockSignals(False)
        self.render_protection_toggle.setVisible(is_renderable_3d)
        self.name.setFont(role_font("folders" if is_dir else "files", 12, 600, tracking=0.12))
        self.name.setStyleSheet(
            f"color: {role_color('folders' if is_dir else 'files', C['text'])}; background: transparent;"
        )
        self._preview_pixmap = None
        self._preview_request_path = None
        self.preview_stale_badge.hide()
        self.preview_origin_badge.hide()
        self.preview_profile_badge.hide()
        if lightroom_managed:
            self._request_lightroom_profile(path)
        self.preview_progress.hide()
        if self._preview_generation_paths:
            self.preview_log.show()
            self.well_label.hide()
        else:
            self.preview_log.hide()
            self.well_label.show()
        self._stop_video()
        is_text_preview = not is_dir and path.suffix.lower() in TEXT_PREVIEW_EXTENSIONS
        # Lecture coupee (VIDEO_PLAYBACK_ENABLED) : une video passe par l'apercu fixe plus bas.
        is_video = VIDEO_PLAYBACK_ENABLED and not is_dir and path.suffix.lower() in VIDEO_EXTENSIONS
        if is_video:
            # Lecture reelle (voir _stop_video/video_widget), pas la frame
            # figee de file_image_pixmap : celle-ci ne sert plus ici qu'a
            # dimensionner le lecteur avant que la premiere image ne soit
            # decodee (voir _show_video). well/text_preview jamais affiches
            # en meme temps.
            self.well.hide()
            self._hide_text_views()
            self._show_video(path)
        elif is_text_preview and self._show_markdown(path):
            # Note Markdown rendue comme le mode lecture du module Markdown (voir _show_markdown).
            self.well.hide()
        elif is_text_preview:
            # Extrait de contenu (voir read_text_preview) plutot que le
            # "well" image : les deux ne s'affichent jamais ensemble.
            self.well.hide()
            self._hide_markdown()
            content_text = read_text_preview(path)
            self.text_preview.setPlainText(content_text if content_text is not None else "(apercu indisponible)")
            self.text_preview.show()
        else:
            self._hide_text_views()
            self.well.show()
            if not is_dir:
                suffix = path.suffix.lower()
                if suffix in IMAGE_EXTENSIONS:
                    # Décodage et lecture du cache disque par le worker existant.
                    self._preview_pixmap = file_image_pixmap(path, asynchronous=True)
                elif suffix in OBJ_EXTENSIONS | ABC_EXTENSIONS:
                    if str(path) in _MANUAL_3D_PREVIEW_REQUESTS:
                        _MANUAL_3D_PREVIEW_REQUESTS.discard(str(path))
                        render_mode = _MANUAL_3D_PREVIEW_MODE.pop(str(path), "low")
                        self._preview_render_modes[(str(path), "image")] = render_mode
                        _cached_file_image_pixmap(path)  # charge l'ancien rendu si disponible
                        self._start_3d_preview(path, render_mode)
                    else:
                        self._preview_pixmap = _cached_file_image_pixmap(
                            path, self._preview_render_modes.get((str(path), "image"), "low"))
                elif suffix in (BLEND_EXTENSIONS | MAYA_SCENE_EXTENSIONS | FBX_EXTENSIONS | HOUDINI_SCENE_EXTENSIONS):
                    if str(path) in _MANUAL_3D_PREVIEW_REQUESTS:
                        _MANUAL_3D_PREVIEW_REQUESTS.discard(str(path))
                        render_mode = _MANUAL_3D_PREVIEW_MODE.pop(str(path), "low")
                        self._preview_render_modes[(str(path), "image")] = render_mode
                        _cached_file_image_pixmap(path)
                        self._start_3d_preview(path, render_mode)
                    else:
                        self._preview_pixmap = _cached_file_image_pixmap(
                            path, self._preview_render_modes.get((str(path), "image"), "low"))
                elif suffix in ILLUSTRATOR_EXTENSIONS and not ai_has_pdf_content(path):
                    # .ai sans contenu PDF : vignette XMP (voir previews._decode_ai_image).
                    pix = file_image_pixmap(path)
                    if pix is not None and not pix.isNull():
                        self._preview_pixmap = pix
                    else:
                        self.well_label.setText("Fichier Illustrator sans aperçu (enregistré sans contenu PDF).")
                elif suffix in PDF_EXTENSIONS or suffix in ILLUSTRATOR_EXTENSIONS:
                    # Un .ai moderne est un PDF : memes planches feuilletables.
                    self._pdf_pages = pdf_page_count(path)
                    if self._pdf_pages:
                        self._pdf_path = str(path)
                        self._pdf_page = 0
                        self._pdf_zoom = 1.0
                        self._pdf_view = [0.0, 0.0]
                        self.pur_navigation.show()
                        self._navigate_pdf_page(0)
                    else:
                        self.well_label.setText("PDF illisible (protégé ou corrompu).")
                elif suffix in DWG_EXTENSIONS or suffix in DXF_EXTENSIONS:
                    pix = file_image_pixmap(path)
                    if pix is not None and not pix.isNull():
                        self._preview_pixmap = pix
                elif suffix in PUR_PREVIEW_EXTENSIONS:
                    # Indexe les images embarquees sans les decoder, puis
                    # l'inspecteur ne charge que celle actuellement choisie.
                    try:
                        mtime = path.stat().st_mtime
                    except OSError:
                        mtime = None
                    self._pur_image_ranges = pur_embedded_image_ranges(path, mtime)
                    pur_version = pur_file_major_version(path)
                    is_pur_v2 = pur_version is not None and pur_version >= 2
                    if self._pur_image_ranges or is_pur_v2:
                        self._pur_image_path = str(path)
                        self.pur_navigation.show()
                        self.pur_previous_button.setEnabled(False)
                        self.pur_next_button.setEnabled(len(self._pur_image_ranges) > 1)
                        ready = pur_image_files(path, mtime) if (is_pur_v2 and mtime is not None) else None
                        if is_pur_v2 and ready:
                            # Deja extraites (par la visionneuse ou une visite precedente) : tout de suite,
                            # sans attendre une nouvelle extraction (qui finissait sur la 1re image).
                            self._pur_exported_images = [str(p) for p in ready]
                        elif is_pur_v2:
                            self.pur_image_counter.setText("Extraction des images PureRef…")
                            self.pur_next_button.setEnabled(False)
                            if mtime is not None:
                                self._start_pur_export(path, mtime)
                        if self._pur_image_ranges or self._pur_exported_images:
                            self._apply_pur_wanted(str(path))
                            self._navigate_pur_image(0)
                        else:
                            self.well_label.setText("Extraction des images PureRef en cours…")
                    else:
                        self.well_label.setText("Aucune image intégrée lisible dans ce fichier PureRef.")
                elif (suffix in PSD_EXTENSIONS
                      or suffix in EXR_EXTENSIONS or suffix in HDR_EXTENSIONS
                      or suffix in CUBE_EXTENSIONS or suffix in RAW_EXTENSIONS
                      or suffix in TX_EXTENSIONS or suffix in FONT_EXTENSIONS
                      or suffix in ABR_EXTENSIONS or suffix in VIDEO_EXTENSIONS):
                    # Rendu genere (.obj, voir _decode_obj_image), vignette
                    # embarquee extraite (.psd/.psb, voir
                    # _decode_psd_thumbnail) ou tone-mapping HDR (.exr/.hdr,
                    # voir _decode_exr_image/_decode_hdr_image) : pas un
                    # fichier que QPixmap sait charger directement, passe
                    # par le meme cache que les cartes-fichier
                    # (file_image_pixmap).
                    pix = file_image_pixmap(path)
                    if pix is not None and not pix.isNull():
                        self._preview_pixmap = pix
            self._update_preview()
            self._refresh_preview_stale_badge(path)
        stamp = entry_mtime(path)
        modified = datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M") if stamp is not None else "-"
        if is_dir:
            kind = "Dossier"
            # Nombre d'elements : repris de la lecture du dossier par la colonne qui s'ouvre juste apres (meme
            # clic, avant le retour a la boucle) ; sinon compte a ce moment-la. Jamais une 2e lecture du dossier.
            size = "…"
            # La colonne le fournit à son arrivée ; attendre ne doit jamais
            # déclencher une seconde énumération sur le fil de l'interface.
            QTimer.singleShot(0, self, lambda p=str(path): self._fill_folder_count(p, scan=False))
        else:
            kind = (path.suffix[1:].upper() + " file") if path.suffix else "Fichier"
            file_size = entry_size(path)
            size = human_size(file_size) if file_size is not None else "-"
        self.values["kind"].setText(kind)
        self.values["size"].setText(size)
        self.values["modified"].setText(modified)
        if supports_turntable and preferred_media == "turntable":
            self._select_preview_media()

        if is_dir:
            self.badge.setText("DOSSIER")
            self.badge.setStyleSheet(f"color: {role_color('info', C['dim'])}; background: transparent;")
        else:
            self.badge.setText(path.suffix[1:].upper() if path.suffix else "FICHIER")
            self.badge.setStyleSheet("color: #7fa8cf; background: transparent;")

# ==========================================================================
# Etat de session (position/taille de la fenetre, dernier dossier parcouru) :
# separe des parametres utilisateur (pipeline_settings.json, gere par
# settings_window.py) puisque ce n'est pas un reglage mais un etat automatique
# de l'appli, sauvegarde a la fermeture et restaure au demarrage suivant.
# ==========================================================================
