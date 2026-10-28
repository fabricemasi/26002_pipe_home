"""Miniatures de la timeline du module vidéo : lues EN FOND par une source à part (jamais celle de la lecture),
une demande remplace la précédente (vue de la timeline changée : seules les miniatures visibles sont lues), mises en
cache par rang. Vidéo : saut à l'image clé la plus proche et 1re image décodée (rapide ; une miniature n'a pas
besoin d'être exacte) ; image d'une séquence : lue puis réduite. Couleurs = celles de l'affichage (même pipeline
OCIO / corrections, sur la petite image).

`set_playing(True)` pendant la lecture : les miniatures continuent d'arriver, mais une à la fois avec un repos entre
deux (`PLAY_GAP_S`, plus long pour un fichier réseau) — la lecture garde le disque / le réseau et le processeur.
`set_height` : hauteur de décodage = hauteur de la bande de la timeline (pixels physiques)."""
from __future__ import annotations

import threading
import hashlib
import json
import os
import tempfile
from collections import OrderedDict
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QImage, QImageReader

from fm_video import color as vcolor

THUMB_H = 48                    # hauteur de décodage par défaut (pixels)
PLAY_GAP_S = 0.12               # repos entre deux miniatures pendant la lecture (fichier local)
PLAY_GAP_REMOTE_S = 0.5         # idem, fichier sur un partage réseau
MOODBOARD_PROXY_WIDTH = 1200


class MoodboardProxyCache:
    """JPEG dans Moodboards/<nom du film> - <empreinte>, près de la vidéo.

    Pixels vidéo avant corrections : le même proxy reste valable après un changement de couleurs.
    La date et la taille distinguent les versions de la vidéo, sans relire son contenu.
    """
    def __init__(self, path, width=MOODBOARD_PROXY_WIDTH):
        self.path = Path(path)
        self.width = max(128, min(7680, int(width)))
        self.disk_enabled = True
        self.selection = {}
        stamp = self.path.stat()
        # Empreinte bornée (192 Kio au plus), stable après renommage du film.
        digest = hashlib.sha256(str(stamp.st_size).encode())
        with self.path.open('rb') as stream:
            for offset in sorted({0, max(0, stamp.st_size // 2 - 32768), max(0, stamp.st_size - 65536)}):
                stream.seek(offset)
                digest.update(stream.read(65536))
        self.identity = digest.hexdigest()[:24]
        self.version = hashlib.sha1(
            f"v1:{stamp.st_mtime_ns}:{stamp.st_size}".encode()).hexdigest()[:12]
        root = self.path.parent / 'Moodboards'
        # Le nom reste lisible dans l'Explorateur ; l'empreinte, elle, permet
        # de déplacer ce même dossier quand le MKV est renommé, sans régénérer.
        self.directory = root / f'{self.path.stem} - {self.identity}'
        self._adopt_directory(root)

    def _adopt_directory(self, root):
        """Retrouve le cache par empreinte et lui donne le nom courant du film."""
        if self.directory.exists():
            return
        candidates = [root / self.identity]
        try:
            candidates.extend(path for path in root.glob(f'* - {self.identity}') if path != self.directory)
        except OSError:
            pass
        for previous in candidates:
            if not previous.is_dir():
                continue
            try:
                previous.rename(self.directory)
                return
            except OSError:
                # Un dossier ouvert/partagé garde son nom temporairement ; les
                # proxies y restent néanmoins réutilisables à l'ouverture.
                self.directory = previous
                return

        # Migration des caches produits avant l'ajout de l'empreinte au nom.
        old = self.path.parent / 'Moodboards' / self.path.stem
        if (old / '.moodboard.json').is_file():
            try:
                metadata = json.loads((old / '.moodboard.json').read_text(encoding='utf-8'))
                if metadata.get('source') == self.path.name and metadata.get('version') == self.version:
                    old.rename(self.directory)
                    for proxy in self.directory.glob('*.moodboard_*.jpg'):
                        if proxy.name.startswith(self.path.name + '.moodboard_'):
                            proxy.rename(proxy.with_name(self.identity + proxy.name[len(self.path.name):]))
                    metadata['source'] = self.identity
                    (self.directory / '.moodboard.json').write_text(json.dumps(metadata), encoding='utf-8')
            except (OSError, ValueError):
                pass

    def filename(self, index):
        return self.directory / (
            f"{self.identity}.moodboard_{self.version}_{int(index):08d}_{self.width}.jpg")

    def prepare(self, indices, layout=(), is_current=None):
        """Vérifie UN moodboard complet en fond ; toute différence remplace ses proxies."""
        directory = self.filename(0).parent
        manifest = directory / ".moodboard.json"
        signature = dict(source=self.identity, version=self.version, width=self.width,
                         indices=list(indices), layout=list(layout))
        directory.mkdir(parents=True, exist_ok=True)
        self.selection = {}
        try:
            saved = json.loads((directory / '.moodboard_selection.json').read_text(encoding='utf-8'))
            if all(saved.get(k)==signature[k] for k in ('source','version','indices','layout')):
                self.selection = {int(k):int(v) for k,v in saved.get('selection',{}).items()
                                  if int(k) in indices and int(v)>=0}
        except (OSError,ValueError,TypeError):
            pass
        files = list(directory.glob("*.moodboard_*.jpg"))
        expected = {self.filename(i).name for i in indices}
        try:
            matches = json.loads(manifest.read_text(encoding="utf-8")) == signature
        except (OSError, ValueError):
            matches = False
        if matches and {p.name for p in files} == expected:
            for path in files:
                if is_current is not None and not is_current():
                    raise InterruptedError('Vérification suspendue')
                reader = QImageReader(str(path))
                if not reader.canRead() or reader.size().width() != self.width:
                    matches = False
                    break
        else:
            matches = False
        # Nettoyer aussi les anciens proxies déposés directement près de la vidéo.
        prefix = f"{self.path.name}.moodboard_"
        previous = [p for p in self.path.parent.iterdir()
                    if p.name.startswith(prefix) and p.suffix.lower() == ".jpg"]
        for path in previous + ([] if matches else files):
            if is_current is not None and not is_current():
                raise InterruptedError('Nettoyage suspendu')
            path.unlink(missing_ok=True)
        if not matches:
            temporary = manifest.with_suffix(".tmp")
            temporary.write_text(json.dumps(signature, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, manifest)
        return matches

    def export(self, indices, layout, is_current=None):
        if not self.disk_enabled:
            return
        from fm_video.moodboard_export import export_board
        export_board(self, indices, layout, is_current)

    def save_selection(self):
        manifest = json.loads((self.directory / '.moodboard.json').read_text(encoding='utf-8'))
        manifest['selection'] = self.selection
        target = self.directory / '.moodboard_selection.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(manifest),encoding='utf-8')
        os.replace(temporary,target)

    def pixels(self, source, index, height, is_current=None, force=False, exact=False, frame=None):
        destination = self.filename(index)
        actual = self.selection.get(index,index) if frame is None else frame
        image = QImage(str(destination)) if self.disk_enabled and not force else QImage()
        if image.isNull() or image.width() != self.width:
            proxy_height = max(1, round(self.width * source.height / max(1, source.width)))
            pixels = (source.thumbnail(actual,proxy_height) if exact or index in self.selection
                      else video_thumbnail(source, actual, proxy_height))
            if pixels is None:
                return None
            pixels = np.ascontiguousarray(pixels, dtype=np.uint8)
            h, w = pixels.shape[:2]
            image = QImage(pixels.data, w, h, pixels.strides[0], QImage.Format_RGB888).copy()
            image = image.scaled(self.width, proxy_height,
                                 Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            temporary = None
            try:
                if not self.disk_enabled or (is_current is not None and not is_current()):
                    return self._pixels(image, height)
                # Un fichier interrompu ne doit jamais remplacer un proxy valide.
                destination.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(prefix=".moodboard_", suffix=".jpg", dir=destination.parent)
                os.close(fd)
                if image.save(temporary, "JPEG", 92) and (is_current is None or is_current()):
                    os.replace(temporary, destination)
            except OSError:
                pass  # Dossier en lecture seule : le moodboard reste utilisable en mémoire.
            finally:
                if temporary is not None:
                    try:
                        os.unlink(temporary)
                    except OSError:
                        pass
        return self._pixels(image, height)

    @staticmethod
    def _pixels(image, height):
        if height < image.height():
            image = image.scaledToHeight(max(1, height), Qt.SmoothTransformation)
        image = image.convertToFormat(QImage.Format_RGB888)
        return np.ndarray((image.height(), image.width(), 3), dtype=np.uint8,
                          buffer=image.constBits(), strides=(image.bytesPerLine(), 3, 1)).copy()


def video_thumbnail(source, index: int, height: int = THUMB_H) -> np.ndarray | None:
    """Image proche du rang `index` (image clé d'avant), réduite : uint8 H x W x 3."""
    container, stream = source._container, source._stream
    pts = source.pts_of(index)
    try:
        container.seek(int(pts), backward=True, any_frame=False, stream=stream)
        for frame in container.decode(stream):
            break
        height = min(int(height), int(frame.height))
        width = max(2, int(round(frame.width * height / max(1, frame.height))) // 2 * 2)
        small = frame.reformat(width=width, height=height, format="rgb24")
        return small.to_ndarray()
    except Exception:                                        # noqa: BLE001 - miniature absente, rien de plus
        return None
    return None


def image_thumbnail(source, index: int, height: int = THUMB_H) -> np.ndarray | None:
    try:
        frame = source.read(index)
    except Exception:                                        # noqa: BLE001
        return None
    pixels = frame.pixels
    if pixels is None:
        return None
    step = max(1, pixels.shape[0] // height)
    return np.ascontiguousarray(pixels[::step, ::step])


def to_qimage(pixels: np.ndarray, pipeline, state) -> QImage:
    rgb, alpha = vcolor.process_np(pixels, pipeline, state)
    if alpha is not None:
        rgb = rgb * np.clip(alpha, 0, 1)[..., None]
    data = np.ascontiguousarray((np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8))
    h, w = data.shape[:2]
    return QImage(data.data, w, h, w * 3, QImage.Format_RGB888).copy()


class ThumbnailLoader(QObject):
    ready = Signal(int, QImage)
    edited = Signal(int,int,QImage,bool)
    selectionReady = Signal(object)
    editFailed = Signal(int,str)

    def __init__(self, path, settings: dict | None = None, parent=None, limit: int = 600,
                 max_height: int = 512, exact_video: bool = False, workers: int = 1,
                 shared_index=None, moodboard_proxies: bool = False):
        super().__init__(parent)
        self.path = path
        self.settings = settings
        self.limit = limit
        self.max_height = max(16, int(max_height))
        self.exact_video = bool(exact_video)
        self.workers = 1 if moodboard_proxies else max(1, min(4, int(workers)))
        self.shared_index = shared_index
        self.moodboard_proxies = bool(moodboard_proxies)
        self.proxy_width = max(128, min(7680, int((settings or {}).get(
            "video_moodboard_proxy_width", MOODBOARD_PROXY_WIDTH))))
        self.cache: OrderedDict[int, QImage] = OrderedDict()
        self._cond = threading.Condition()
        self._wanted: list[int] = []
        self._busy: set[int] = set()
        self._playing = False
        self._stop = False
        self._board_indices = None
        self._board_layout = ()
        self._board_revision = 0
        self._board_done: set[int] = set()
        self._edits = OrderedDict()
        self._edit_versions = {}
        self.height = THUMB_H
        try:
            from fm_video.vlc_engine import is_remote
            self._remote = bool(is_remote(path))
        except Exception:                                    # noqa: BLE001
            self._remote = False
        self._look = (None, vcolor.ViewState(dict(vcolor.DEFAULT_GRADE)))
        self._threads = [threading.Thread(target=self._run, name=f"video-thumbs-{i + 1}", daemon=True)
                         for i in range(self.workers)]
        for thread in self._threads:
            thread.start()

    def set_look(self, pipeline, state):
        """Nouvelles couleurs (corrections, OCIO) : miniatures refaites."""
        with self._cond:
            self._look = (pipeline, state)
            self.cache.clear()

    def request(self, indices):
        """Miniatures voulues (visibles), dans l'ordre. Celles déjà lues sont RENVOYÉES aussitôt : la timeline peut
        les avoir oubliées (index des images prêt, média recalé) — ne pas les renvoyer laissait la bande vide tant
        qu'un défilement ne demandait pas d'autres rangs (bug signalé)."""
        indices = tuple(dict.fromkeys(int(i) for i in indices))
        known = []
        with self._cond:
            if self.moodboard_proxies and self._board_indices is None:
                self._board_indices = indices
                self._board_revision += 1
            if self.moodboard_proxies:
                # Le zoom donne priorité aux images visibles, sans abandonner le reste du moodboard.
                indices = tuple(dict.fromkeys((*indices, *(i for i in self._board_indices
                                                           if i not in self._board_done))))
            wanted = []
            for i in dict.fromkeys(int(i) for i in indices):
                image = self.cache.get(i)
                if image is None:
                    wanted.append(i)
                else:
                    known.append((i, image))
            self._wanted = wanted
            self._cond.notify()
        for i, image in known:
            self.ready.emit(i, image)

    def set_playing(self, playing: bool):
        with self._cond:
            self._playing = bool(playing)
            self._cond.notify()

    def set_height(self, height: int):
        """Hauteur de décodage (bande de la timeline agrandie / réduite) : miniatures refaites à cette taille."""
        height = max(16, min(self.max_height, int(height)))
        with self._cond:
            if height != self.height:
                self.height = height
                self.cache.clear()

    def stop(self):
        with self._cond:
            self._stop = True
            self._cond.notify()

    def set_proxy_width(self, width: int):
        """Invalide seulement les images en mémoire ; aucun accès disque sur le fil UI."""
        width = max(128, min(7680, int(width)))
        with self._cond:
            if width == self.proxy_width:
                return False
            self.proxy_width = width
            self._board_revision += 1
            self._board_done.clear()
            self.cache.clear()
        return True

    def set_moodboard(self, indices, layout=()):
        """Nouvelle ouverture / disposition : seule la vérification en fond décide de réutiliser le disque."""
        with self._cond:
            self._board_indices = tuple(int(i) for i in indices)
            self._board_layout = tuple(layout)
            self._board_revision += 1
            self._board_done.clear()
            self.cache.clear()
            self._wanted.clear()
            self._edits.clear()

    def edit_frame(self,slot,frame,final=False):
        """Demande locale remplaçable, servie par le MÊME décodeur que les proxies."""
        with self._cond:
            self._edit_versions[slot] = self._edit_versions.get(slot,0)+1
            self._edits[slot] = (int(frame),bool(final),self._edit_versions[slot])
            self._edits.move_to_end(slot)
            self._cond.notify()

    def _run(self):
        from fm_video import media as vmedia
        try:
            source = vmedia.open_media(self.path, self.settings)
        except Exception:                                    # noqa: BLE001 - média illisible : pas de miniatures
            return
        if source.kind == "video" and self.shared_index is not None:
            source._index = self.shared_index
            if self.shared_index.count:
                source.frame_count = self.shared_index.count
        proxies = None
        if source.kind == "video" and self.moodboard_proxies:
            try:
                proxies = MoodboardProxyCache(self.path, self.proxy_width)
            except OSError:
                pass
        if source.kind == "video":
            # UN fil de décodage : une miniature (image clé seule) n'y gagne rien en vitesse (~70 ms en 4K HEVC
            # dans les deux cas), mais les fils automatiques de FFmpeg prenaient tous les cœurs et le GIL (jusqu'à
            # 10 ms d'attente de l'interface par miniature, mesuré) : la lecture saccadait pendant qu'elles arrivaient.
            try:
                source._stream.codec_context.thread_count = 1
            except Exception:                                # noqa: BLE001
                pass
        try:
            prepared_revision = -1
            while True:
                with self._cond:
                    while not self._stop and not self._wanted and not self._edits:
                        self._cond.wait()
                    if self._stop:
                        return
                    if self._playing:
                        # Lecture en cours : une miniature puis un repos (réveillé par stop / pause).
                        self._cond.wait(PLAY_GAP_REMOTE_S if self._remote else PLAY_GAP_S)
                        if self._stop:
                            return
                        if not self._wanted:
                            continue
                    editing = bool(self._edits)
                    edit = None
                    if editing:
                        index,edit = self._edits.popitem(last=False)
                    else:
                        index = self._wanted.pop(0)
                    self._busy.add(index)
                    pipeline, state = self._look
                    height = self.height
                    proxy_width = self.proxy_width
                    board_revision = self._board_revision
                    board_indices = self._board_indices
                    board_layout = self._board_layout
                try:
                    if proxies is not None and prepared_revision != board_revision:
                        proxies = MoodboardProxyCache(self.path, proxy_width)
                        try:
                            proxies.prepare(board_indices or (), board_layout)
                        except OSError:
                            # Un nettoyage impossible ne doit pas ajouter un deuxième jeu sur le disque.
                            proxies.disk_enabled = False
                        prepared_revision = board_revision
                        self.selectionReady.emit(dict(proxies.selection))
                    if editing:
                        if proxies is None or index not in (board_indices or ()):
                            raise ValueError('Les proxies du moodboard ne sont pas disponibles')
                        frame,final,version = edit
                        valid = lambda: not self._stop and board_revision==self._board_revision and self._edit_versions.get(index)==version
                        # Les aperçus du glissement restent en mémoire ; seul le
                        # relâchement écrit LE proxy modifié et la sélection.
                        disk = proxies.disk_enabled
                        if not final:
                            proxies.disk_enabled = False
                        try:
                            pixels = proxies.pixels(source,index,height,is_current=valid,force=True,exact=True,frame=frame)
                        finally:
                            proxies.disk_enabled = disk
                        if pixels is None or not valid():
                            with self._cond:
                                self._busy.discard(index)
                            continue
                        image = to_qimage(pixels,pipeline,state)
                        if final:
                            proxies.selection[index] = frame
                            proxies.save_selection()
                            with self._cond:
                                self.cache[index] = image
                                while len(self.cache)>self.limit:
                                    self.cache.popitem(last=False)
                                self._board_done.add(index)
                                self._wanted = [i for i in self._wanted if i!=index]
                        with self._cond:
                            self._busy.discard(index)
                        self.edited.emit(index,frame,image,final)
                        if final and board_indices and set(board_indices).issubset(self._board_done):
                            try:
                                proxies.export(board_indices,board_layout,is_current=valid)
                            except OSError:
                                pass
                        continue
                    if index in self.cache:
                        pixels = None
                    elif source.kind == "video":
                        pixels = (proxies.pixels(source, index, height, is_current=lambda:
                                  not self._stop and board_revision == self._board_revision) if proxies is not None
                                  else source.thumbnail(index, height) if self.exact_video
                                  else video_thumbnail(source, index, height))
                    else:
                        pixels = image_thumbnail(source, index, height)
                    if pixels is None:
                        with self._cond:
                            self._busy.discard(index)
                        continue
                    image = to_qimage(pixels, pipeline, state)
                except Exception as exc:                     # noqa: BLE001
                    if editing:
                        self.editFailed.emit(index,str(exc))
                    with self._cond:
                        self._busy.discard(index)
                    continue
                with self._cond:
                    self._busy.discard(index)
                    # Une résolution peut être demandée pendant le décodage : ne jamais émettre cette ancienne
                    # définition comme si elle répondait à la nouvelle demande.
                    if height != self.height or board_revision != self._board_revision:
                        if (index not in self._wanted and
                                (self._board_indices is None or index in self._board_indices)):
                            self._wanted.insert(0, index)
                        self._cond.notify()
                        continue
                    self.cache[index] = image
                    if self.moodboard_proxies:
                        self._board_done.add(index)
                    while len(self.cache) > self.limit:
                        self.cache.popitem(last=False)
                try:
                    self.ready.emit(index, image)
                except RuntimeError:
                    return
                if (proxies is not None and board_indices and
                        set(board_indices).issubset(self._board_done)):
                    try:
                        proxies.export(board_indices, board_layout, is_current=lambda:
                                       not self._stop and board_revision == self._board_revision)
                    except OSError:
                        pass
        finally:
            source.close()
