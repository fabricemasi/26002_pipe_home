"""Captures du module vidéo : l'image affichée (ou une zone tracée sur elle) enregistrée en PNG, en PLEINE
définition, couleurs telles qu'à l'écran (même calcul que l'affichage : OCIO, corrections, LUT — `color.process_np`).

Dossier : à côté du média, au nom du film (`<dossier du film>/<nom>/`) ; fichiers `<nom>_001.png`, `<nom>_002.png`…
(numéro suivant le plus grand présent) ; zones : `z_<nom>_001.png`… dans le même dossier. Calcul et écriture
EN FOND (`SnapshotSaver`) : rien de lourd sur le fil de l'interface, la lecture continue."""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtGui import QImage

from fm_video import color as vcolor

ZONE_PREFIX = "z_crop_"
BAND = 128                      # lignes calculées d'un coup (voir render)


def media_name(source) -> str:
    """Nom du film : nom du fichier sans extension ; séquence : sa tête sans le séparateur (« beauty.#### »
    -> « beauty »)."""
    sequence = getattr(source, "sequence", None)
    if sequence is not None:
        name = sequence.head.rstrip("._- ")
        if name:
            return name
    return Path(source.path).stem


def snapshot_dir(source) -> Path:
    return Path(source.path).parent / media_name(source)


def next_path(directory: Path, base: str) -> Path:
    """`<base>_NNN.png` avec le numéro suivant le plus grand déjà présent (001 au départ)."""
    pattern = re.compile(re.escape(base) + r"_(\d+)\.png$", re.IGNORECASE)
    highest = 0
    try:
        for entry in directory.iterdir():
            match = pattern.match(entry.name)
            if match:
                highest = max(highest, int(match.group(1)))
    except OSError:
        pass
    return directory / f"{base}_{highest + 1:03d}.png"


def render(frame, pipeline, state, region: QRect | None = None) -> QImage:
    """Image (ou zone, en pixels de l'image) telle qu'affichée, 8 bits ; alpha gardé s'il y en a un."""
    pixels = frame.pixels
    if region is not None:
        x0, y0 = max(0, region.left()), max(0, region.top())
        x1 = min(pixels.shape[1], region.left() + region.width())
        y1 = min(pixels.shape[0], region.top() + region.height())
        pixels = pixels[y0:y1, x0:x1]
    # Par bandes de lignes, en rendant la main entre elles : un seul calcul de toute une 4K gardait le GIL assez
    # longtemps pour figer l'interface (~80 ms, lecture comprise). Calcul par pixel : bandes = image entière.
    rgb_parts, alpha_parts = [], []
    for y in range(0, pixels.shape[0], BAND):
        rgb_band, alpha_band = vcolor.process_np(pixels[y:y + BAND], pipeline, state)
        rgb_parts.append(rgb_band)
        alpha_parts.append(alpha_band)
        time.sleep(0)
    rgb = np.clip(np.concatenate(rgb_parts, axis=0), 0.0, 1.0)
    alpha = None if alpha_parts[0] is None else np.concatenate(alpha_parts, axis=0)
    if alpha is not None:
        data = np.dstack([rgb, np.clip(alpha, 0.0, 1.0)])
        data = np.ascontiguousarray((data * 255.0 + 0.5).astype(np.uint8))
        h, w = data.shape[:2]
        return QImage(data.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
    data = np.ascontiguousarray((rgb * 255.0 + 0.5).astype(np.uint8))
    h, w = data.shape[:2]
    return QImage(data.data, w, h, w * 3, QImage.Format_RGB888).copy()


class SnapshotSaver(QObject):
    """Une capture par appel de `save`, dans un fil de fond ; `done(chemin, erreur)` au retour."""
    done = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()          # deux captures rapprochées : numéros distincts

    def save(self, frame, pipeline, state, directory: Path, base: str, region: QRect | None = None):
        threading.Thread(target=self._run, args=(frame, pipeline, state, Path(directory), base, region),
                         name="video-snapshot", daemon=True).start()

    def save_image(self, image: QImage, directory: Path, base: str):
        """Enregistre une image déjà rendue (par exemple une capture complète du moodboard), en fond."""
        threading.Thread(target=self._run_image, args=(image.copy(), Path(directory), base),
                         name="video-snapshot-image", daemon=True).start()

    def _run_image(self, image, directory, base):
        try:
            with self._lock:
                directory.mkdir(parents=True, exist_ok=True)
                path = next_path(directory, base)
                part = path.with_name(path.stem + ".part.png")
                if not image.save(str(part), "PNG"):
                    raise OSError("écriture impossible (droits, disque plein ?)")
                try:
                    part.replace(path)
                except PermissionError:
                    path.write_bytes(part.read_bytes())
                    part.unlink(missing_ok=True)
            self.done.emit(str(path), "")
        except Exception as exc:                             # noqa: BLE001
            try:
                self.done.emit("", str(exc))
            except RuntimeError:
                pass

    def _run(self, frame, pipeline, state, directory, base, region):
        try:
            image = render(frame, pipeline, state, region)
            with self._lock:
                directory.mkdir(parents=True, exist_ok=True)
                path = next_path(directory, base)
                part = path.with_name(path.stem + ".part.png")
                if not image.save(str(part), "PNG"):
                    raise OSError("écriture impossible (droits, disque plein ?)")
                try:
                    part.replace(path)
                except PermissionError:
                    # Certains dossiers Windows autorisent la création mais refusent le renommage atomique.
                    # Le numéro est unique sous le verrou : recopier le PNG produit garde la capture disponible.
                    path.write_bytes(part.read_bytes())
                    part.unlink(missing_ok=True)
            self.done.emit(str(path), "")
        except Exception as exc:                             # noqa: BLE001 - dit à l'utilisateur, jamais de plantage
            try:
                self.done.emit("", str(exc))
            except RuntimeError:
                pass
