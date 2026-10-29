"""Inspecteur : source de l'image focus, badges d'aperçu périmé / d'origine, sources et profil Lightroom.

Découpé de detail_panel.py (2026-10-29) ; carte : docs/agents/inspecteur.md."""
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize

from config import _STALE_PREVIEW_PATHS
from previews import _turntable_frames


class SourcesMixin:
    """Méthodes de DetailPanel : inspecteur : source de l'image focus, badges d'aperçu périmé / d'origine, sources et profil Lightroom."""

    def focus_source(self):
        """Objet en focus (aujourd'hui : l'apercu image/turntable affiche) pour
        l'animation « masquer les colonnes » : (pixmap pleine taille, QRect de
        l'image telle qu'affichee, en coordonnees de ce panneau), ou None si
        rien d'affichable (pas d'apercu, journal de rendu, video...)."""
        shown = self.well_label.pixmap()
        if (self._preview_pixmap is None or self._preview_pixmap.isNull() or shown is None or shown.isNull()
                or not self.well_label.isVisible()):
            return None
        dpr = shown.devicePixelRatio() or 1.0
        w, h = round(shown.width() / dpr), round(shown.height() / dpr)
        label = self.well_label.rect()
        top_left = self.well_label.mapTo(self, QPoint((label.width() - w) // 2, (label.height() - h) // 2))
        return self._preview_pixmap, QRect(top_left, QSize(w, h))

    def _refresh_preview_stale_badge(self, path: Path | None = None):
        key = str(path) if path is not None else self._current_path
        if key and self._selected_preview_media() == "turntable":
            try:
                mode = self._preview_render_modes.get((key, "turntable"), "low")
                stale = bool(self._turntable_frame_paths and not _turntable_frames(
                    Path(key), Path(key).stat().st_mtime, render_mode=mode))
            except OSError:
                stale = False
            self.preview_stale_badge.setVisible(stale)
            return
        self.preview_stale_badge.setVisible(bool(key and self._preview_pixmap is not None and key in _STALE_PREVIEW_PATHS))
        self._refresh_preview_origin_badge(key)

    def _refresh_preview_origin_badge(self, path_key: str | None = None, force: bool = False):
        """Lignes « Source du proxy » / « Source de l'aperçu plein écran » du tableau (plus d'encart
        au-dessus de l'image) : lues EN FOND (catalogue et Previews.lrdata de Lightroom), relues
        quand l'aperçu arrive (`force`, la source a pu changer)."""
        self.preview_origin_badge.hide()
        path_key = path_key or self._current_path
        if not path_key or (not force and path_key == getattr(self, "_sources_asked", None)):
            return
        self._sources_asked = path_key
        try:
            import lightroom_bridge
            if lightroom_bridge.is_managed(Path(path_key)):
                lightroom_bridge.request_sources(Path(path_key))
        except (ImportError, OSError, ValueError):
            pass

    def _on_lightroom_sources(self, path_key: str, proxy: str, full: str):
        if path_key != self._current_path:
            return
        for key, text in (("proxy_source", proxy), ("full_source", full)):
            self.values[key].setText(text)
            self.values[key].setToolTip(text)

    def _set_source_rows_visible(self, visible: bool):
        """Lignes des sources : seulement pour une photo d'un dossier associe a Lightroom ; masquees,
        elles sortent aussi des lignes du tableau (alternance, arrondi du bas)."""
        meta = self.preview_info_table._flat_rows
        if not hasattr(self, "_source_rows"):
            # Ligne du tableau (entree de _flat_rows) qui contient chaque valeur, relevee une fois.
            self._source_rows = [entry for entry in meta
                                 if any(entry[0].isAncestorOf(self.values[key]) for key in self._SOURCE_ROWS)]
        for entry in self._source_rows:
            if visible and entry not in meta:
                controls = getattr(self, "_controls_row_meta", None)       # toujours la derniere
                meta.insert(meta.index(controls) if controls in meta else len(meta), entry)
            elif not visible and entry in meta:
                meta.remove(entry)
            entry[0].setVisible(visible)
        self._restyle_info_table()

    def _on_lightroom_profile_ready(self, path_key: str, profile: str, base_profile: str, error: str):
        if path_key != self._current_path:
            return
        if error:
            self.preview_profile_badge.setText("PROFIL LR INDISPONIBLE")
            self.preview_profile_badge.setToolTip(error)
            foreground, background = "#ffd28a", "#493515"
        elif profile:
            self.preview_profile_badge.setText(f"PROFIL LR : {profile}")
            details = f"Profil de développement Lightroom : {profile}"
            if base_profile and base_profile != profile:
                details += f" (profil caméra de base : {base_profile})"
            self.preview_profile_badge.setToolTip(details)
            foreground, background = "#9ed8ff", "#17364a"
        else:
            self.preview_profile_badge.setText("PROFIL LR NON IDENTIFIÉ")
            self.preview_profile_badge.setToolTip(
                "Lightroom n’a pas renvoyé de nom de profil pour cette photo."
            )
            foreground, background = "#ffd28a", "#493515"
        self.preview_profile_badge.setStyleSheet(
            f"color: {foreground}; background: {background}; border-radius: 2px; padding: 1px 5px;"
        )
        self.preview_profile_badge.show()

    def _request_lightroom_profile(self, path: Path):
        try:
            import lightroom_bridge
            cached = lightroom_bridge.develop_profile(path)
            if cached:
                self._on_lightroom_profile_ready(str(path), cached[0], cached[1], "")
            else:
                self.preview_profile_badge.setText("PROFIL LR : lecture…")
                self.preview_profile_badge.setToolTip(
                    "Lecture des paramètres de développement de cette photo dans Lightroom."
                )
                self.preview_profile_badge.setStyleSheet(
                    "color: #9ed8ff; background: #17364a; border-radius: 2px; padding: 1px 5px;"
                )
                self.preview_profile_badge.show()
            lightroom_bridge.request_develop_profile(path)
        except (ImportError, OSError, ValueError):
            self.preview_profile_badge.hide()
