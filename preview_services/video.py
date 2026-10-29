"""Extraction d’une image vidéo.

Carte et pièges : docs/agents/apercus.md.
"""

from pathlib import Path
from PySide6.QtCore import QEventLoop, Qt, QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from PySide6.QtGui import QImage

VIDEO_PREVIEW_SEEK_FRACTION = 0.1   # position dans la video (evite les frames noires/logo d'intro a 0%)

VIDEO_PREVIEW_TIMEOUT_MS = 6000     # securite : fichier corrompu, codec manquant, partage reseau lent...

def _decode_video_frame(path: Path, max_dim: int, cancel_event=None) -> QImage | None:
    """Extrait une frame a ~10% de la duree d'une video via QtMultimedia
    (QMediaPlayer + QVideoSink, module fourni avec PySide6 — ffmpeg deja
    embarque, aucune dependance externe). L'API est asynchrone (chargement
    et decodage se font en arriere-plan) : cette fonction tourne une
    QEventLoop locale jusqu'a recevoir une frame ou expirer
    (VIDEO_PREVIEW_TIMEOUT_MS), pour rester utilisable comme les autres
    decodeurs synchrones d'appel (cache par file_image_pixmap). None si
    aucune frame n'a pu etre obtenue a temps."""
    player = QMediaPlayer()
    sink = QVideoSink()
    player.setVideoSink(sink)
    player.setSource(QUrl.fromLocalFile(str(path)))

    loop = QEventLoop()
    result: dict = {}

    def on_frame(frame):
        if frame.isValid() and "image" not in result:
            result["image"] = frame.toImage()
            loop.quit()

    def on_status(status):
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            duration = player.duration()
            if duration > 0:
                player.setPosition(int(duration * VIDEO_PREVIEW_SEEK_FRACTION))
            # setPosition() seul, meme a l'arret, ne fait pas toujours
            # decoder/emettre une frame selon le backend — play() force le
            # pipeline a produire au moins la premiere image utile, qu'on
            # recupere puis on coupe aussitot (voir on_frame).
            player.play()
        elif status in (QMediaPlayer.MediaStatus.InvalidMedia, QMediaPlayer.MediaStatus.NoMedia):
            loop.quit()

    def on_error(*_args):
        loop.quit()

    sink.videoFrameChanged.connect(on_frame)
    player.mediaStatusChanged.connect(on_status)
    player.errorOccurred.connect(on_error)

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(VIDEO_PREVIEW_TIMEOUT_MS)

    cancel_timer = QTimer()
    if cancel_event is not None:
        cancel_timer.setInterval(25)
        cancel_timer.timeout.connect(lambda: loop.quit() if cancel_event.is_set() else None)
        cancel_timer.start()
    loop.exec()
    cancel_timer.stop()
    player.stop()
    player.setSource(QUrl())
    sink.videoFrameChanged.disconnect(on_frame)
    player.mediaStatusChanged.disconnect(on_status)
    player.errorOccurred.disconnect(on_error)
    player.setVideoSink(None)

    image = result.get("image")
    if image is None or image.isNull():
        return None
    if max(image.width(), image.height()) > max_dim:
        image = image.scaled(max_dim, max_dim, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return image
