"""Module Markdown / code : le panneau Qt (une QWebEngineView qui recouvre la zone des colonnes) et tout ce qui touche
au disque pour la page (fm_markdown/web/).

- Page chargee UNE fois (prechargee cachee au demarrage de l'appli) : ouvrir un fichier ne recharge jamais la page,
  on lui envoie des messages (QWebChannel, objet « bridge »). Fermer le module CACHE la page (reouverture immediate).
- Lecture des fichiers, rendu de lecture, index des noms de la racine : EN FOND (pool de 2 fils) ; le resultat
  revient sur le fil de l'interface par un signal. Seules les ecritures (et leurs questions de conflit) sont sur le
  fil de l'interface.
- Enregistrement FIDELE (encodage, BOM, fins de ligne : `markdown_preview.read_note` / `write_note`),
  automatique 800 ms apres la frappe, aussitot a la navigation / fermeture ; fichier modifie ailleurs (Obsidian,
  synchronisation) : sans modification ici il est recharge, sinon « Garder ma version / Recharger le fichier /
  Annuler » — jamais d'ecrasement silencieux.
- Apparence : `style.css_variables` (reglages `md_*`) posee dans la page a chaque changement, sans rechargement ;
  feuille choisie dans Reglages > Markdown > CSS (par ex. celle d'Obsidian) en couche « md-user », prioritaire sur
  l'habillage des reglages, jamais sur la structure (web/structure.css) : voir `style.LAYER_ORDER`.

Aucune dependance vers la fenetre principale : elle pose `HOOKS` (`settings()`, `save_state(cle, valeur)`) et ecoute
les signaux."""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (QByteArray, QEasingCurve, QEventLoop, QFileSystemWatcher, QObject, QPoint,
                            QPropertyAnimation, QTimer, QUrl, Qt, Signal, Slot)
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QFileDialog, QGraphicsOpacityEffect, QMessageBox, QVBoxLayout, QWidget

from fm_markdown import preview as markdown_preview
from config import DATA_DIR
from fm_markdown import PACKAGE_DIR, css_sync, is_markdown, is_text_file, style, web_dir

MODULE_DIR = DATA_DIR / "mdeditor"
AUTOSAVE_MS = 800
FADE_MS = 160
MAX_TEXT_BYTES = 16 * 1024 * 1024
NAMES_MAX = 6000                     # noms de fichiers envoyes a la page (images, notes) pour les liens par nom
IMAGE_SIZES_MAX = 800                # images dont la page demande les dimensions (hauteur reservee a l'edition)
NAME_EXTENSIONS = markdown_preview.IMAGE_EMBED_EXTENSIONS | {".md", ".markdown", ".pdf"}

# Branche par l'appli : settings() -> reglages appliques, save_state(cle, valeur) -> etat temps reel.
HOOKS: dict = {}


def _settings() -> dict:
    return (HOOKS.get("settings") or dict)()


def open_extensions(settings: dict | None) -> set[str]:
    """Extensions ouvertes par le module au DOUBLE-CLIC (onglet Markdown) ; « .md » toujours compris."""
    raw = (settings or {}).get("md_open_extensions") or [".md"]
    if isinstance(raw, str):
        raw = re.split(r"[,;\s]+", raw)
    out = {".md"}
    for item in raw:
        text = str(item).strip().lower().lstrip("*")
        if text:
            out.add(text if text.startswith(".") else "." + text)
    return out


def looks_binary(path: Path) -> bool:
    """Fichier binaire (octet nul ou trop d'octets de controle au debut) : jamais traite comme du texte."""
    try:
        with open(path, "rb") as stream:
            head = stream.read(8192)
    except OSError:
        return True
    if b"\x00" in head:
        return not (head.startswith(b"\xff\xfe") or head.startswith(b"\xfe\xff"))
    control = sum(1 for byte in head if byte < 9 or 13 < byte < 32)
    return bool(head) and control / len(head) > 0.1


def opens_on_double_click(path: Path, settings: dict | None = None) -> bool:
    path = Path(path)
    return path.suffix.lower() in open_extensions(settings if settings is not None else _settings())


@dataclass
class _Buffer:
    path: Path
    info: dict
    saved: str
    text: str
    error: str | None = None

    @property
    def dirty(self) -> bool:
        return self.text != self.saved


class _Relay(QObject):
    done = Signal(object)


def _page_class():
    from PySide6.QtWebEngineCore import QWebEnginePage

    class Page(QWebEnginePage):
        """Page du module : garde les messages de la console (erreurs JavaScript) pour le diagnostic et les sondes."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.console: list[tuple[int, str, int, str]] = []

        def javaScriptConsoleMessage(self, level, message, line, source):
            self.console.append((int(level.value) if hasattr(level, "value") else int(level), message, line,
                                 source.rsplit("/", 1)[-1]))
            del self.console[:-200]
            if os.environ.get("PIPELINE_MD_DEBUG"):
                print(f"[md js] {message} ({source.rsplit('/', 1)[-1]}:{line})")

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            # La page ne quitte jamais le module : un lien qui chargerait une autre page s'ouvre a l'exterieur.
            if is_main_frame and url.isValid() and not url.toLocalFile().endswith("shell.html"):
                QDesktopServices.openUrl(url)
                return False
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    return Page


class Bridge(QObject):
    """Objet expose a la page (QWebChannel)."""

    reply = Signal(int, str)
    push = Signal(str)

    def __init__(self, pane: "MarkdownPane"):
        super().__init__()
        self._pane = pane

    @Slot()
    def ready(self):
        self._pane._on_page_ready()

    @Slot(int, str, str)
    def request(self, req_id: int, name: str, args: str):
        self._pane._dispatch(req_id, name, args)


_ASYNC = object()


class MarkdownPane(QWidget):
    """Le module : recouvre la zone des colonnes (comme le board)."""

    closeRequested = Signal()
    stateChanged = Signal()                  # fichier, modifications, historique, mode : la barre de l'appli suit
    pathChanged = Signal(str)                # chemin du fichier affiche

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("MarkdownPane")
        self.path: Path | None = None
        self.kind = "markdown"
        self.mode = "edit"
        self.buffers: dict[str, _Buffer] = {}
        self.history: list[Path] = []
        self.history_index = -1
        self._page_ready = False
        self._pending_open = None
        self._metrics: dict = {}
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="mdeditor")
        self._relay = _Relay()
        self._relay.done.connect(lambda fn: fn(), Qt.QueuedConnection)
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(AUTOSAVE_MS)
        self._autosave.timeout.connect(self.save_all)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._css_watcher = QFileSystemWatcher(self)          # feuille de Reglages > Markdown > CSS
        self._css_watcher.fileChanged.connect(self._on_css_file_changed)
        css_sync.engine().injectionChanged.connect(self._on_managed_css)
        css_sync.engine().fileChanged.connect(lambda: self._push_user_css(_settings(), force=True))
        self._user_css_url = None
        self.css_status = ""
        self._fade = None
        self._style_key = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtWebEngineCore import QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView
        self.view = QWebEngineView(self)
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        page = _page_class()(self.view)
        self.view.setPage(page)
        settings = _settings()
        self._apply_module_padding(settings)
        page.setBackgroundColor(QColor(style.css_color(settings.get("md_bg_color") or "#1b1c1d", "#1b1c1d")[:7]))
        web = page.settings()
        for attribute in (QWebEngineSettings.LocalContentCanAccessFileUrls, QWebEngineSettings.JavascriptCanAccessClipboard,
                          QWebEngineSettings.JavascriptCanPaste):
            try:
                web.setAttribute(attribute, True)
            except (AttributeError, TypeError):
                pass
        self.bridge = Bridge(self)
        self.channel = QWebChannel(page)
        self.channel.registerObject("bridge", self.bridge)
        page.setWebChannel(self.channel)
        layout.addWidget(self.view)
        self._apply_zoom(settings.get("md_zoom", 100))
        self._load_shell(settings)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._on_quit)

    # -- page ------------------------------------------------------------------------------------------------------------
    def _load_shell(self, settings: dict):
        web = web_dir()
        url = lambda name: (web / name).as_uri() + f"?v={int((web / name).stat().st_mtime)}"   # noqa: E731
        scripts = ["vendor/codemirror.js", "vendor/addons.js", "vendor/overlay.js", "vendor/meta.min.js",
                   "vendor/markdown.js", "vendor/modes.min.js", "highlight.js", "table.js", "editor.js", "toolbar.js", "app.js"]
        # Couches : structure protegee, habillage des reglages, feuille choisie (Reglages > Markdown > CSS) ; les
        # variables des reglages (hors couche) reprennent d'abord celles d'Obsidian que cette feuille definit.
        page = ['<!doctype html>', '<html><head><meta charset="utf-8"><title>Markdown</title>',
                f'<style id="md-layers">{style.LAYER_ORDER}</style>',
                f'<style>{style.import_rule(url("structure.css"), "md-structure")}</style>',
                f'<style>{style.import_rule(url("bullets.css"), "md-structure")}</style>',
                f'<style>{style.import_rule(url("base.css"), "md-theme")}</style>',
                f'<style id="md-user-css">{style.import_rule(style.user_css_url(settings), "md-user")}</style>',
                # Bloc synchronise de la feuille partagee, tel que les reglages le donnent (avant meme son ecriture).
                f'<style id="md-managed">{css_sync.engine().injection}</style>',
                f'<style id="md-vars">{style.css_variables(settings)}</style>',
                '<script src="qrc:///qtwebchannel/qwebchannel.js"></script>']
        page += [f'<script src="{url(name)}"></script>' for name in scripts]
        page.append('</head><body></body></html>')
        MODULE_DIR.mkdir(parents=True, exist_ok=True)
        shell = MODULE_DIR / "shell.html"
        text = "\n".join(page)
        try:
            if not shell.is_file() or shell.read_text(encoding="utf-8") != text:
                shell.write_text(text, encoding="utf-8")
        except OSError:
            pass
        self._load_started = time.perf_counter()
        self.view.load(QUrl.fromLocalFile(str(shell)))

    def _on_page_ready(self):
        self._page_ready = True
        self._metrics["page_load"] = time.perf_counter() - getattr(self, "_load_started", time.perf_counter())
        self._push_style(_settings(), force=True)
        self._push_user_css(_settings(), force=True)
        self._push({"type": "managedCss", "css": css_sync.engine().injection})
        try:
            toolbar = json.loads((PACKAGE_DIR / "toolbar.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            toolbar = {"commands": []}
        settings = _settings()
        toolbar["fontColor"] = settings.get("md_toolbar_font_color", toolbar.get("fontColor", "#D83931"))
        toolbar["backgroundColor"] = settings.get("md_toolbar_background_color",
                                                   toolbar.get("backgroundColor", "#FFB78B8C"))
        self._push({"type": "toolbar", "data": toolbar})
        if self._pending_open is not None:
            info, self._pending_open = self._pending_open, None
            self._push({"type": "open", "info": info})

    def _push(self, message: dict):
        self.bridge.push.emit(json.dumps(message, ensure_ascii=False, default=str))

    def _reply(self, req_id: int, value):
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as exc:
            text = json.dumps({"__error__": str(exc)})
        self.bridge.reply.emit(req_id, text)

    def _in_background(self, fn, done):
        """`fn()` en fond, `done(resultat)` sur le fil de l'interface (une erreur devient {"__error__": …})."""
        def work():
            try:
                value = fn()
            except Exception as exc:          # noqa: BLE001 - toute erreur va a la page, jamais de plantage
                value = {"__error__": f"{type(exc).__name__}: {exc}"}
            self._relay.done.emit(lambda: done(value))
        self._pool.submit(work)

    # -- reglages --------------------------------------------------------------------------------------------------------
    def _push_style(self, settings: dict, force: bool = False, layout: bool = True):
        """Variables CSS et options a la page. `layout` faux (seules des couleurs ont change) : l'editeur n'est pas
        remis en page (aucune taille de ligne ne bouge)."""
        css = style.css_variables(settings)
        options = style.page_options(settings)
        key = (css, json.dumps(options, sort_keys=True))
        if key == self._style_key and not force:
            return
        self._style_key = key
        self._push({"type": "style", "css": css, "options": options, "layout": layout or force,
                    "theme": style.theme_class(settings)})

    def _apply_zoom(self, zoom):
        try:
            self.view.setZoomFactor(max(0.25, min(5.0, float(zoom or 100) / 100)))
        except (TypeError, ValueError):
            pass

    def _apply_module_padding(self, settings):
        try:
            margin = max(0, int(settings.get("md_module_padding", 0)))
        except (TypeError, ValueError):
            margin = 0
        self.layout().setContentsMargins(margin, 0, margin, 0)

    def _push_user_css(self, settings, force: bool = False):
        """Feuille choisie dans Reglages > Markdown > CSS (couche « md-user ») : posee sans recharger la page ; absente
        ou illisible = style integre. Suivie sur le disque : modifiee (dans Obsidian par ex.), elle est relue."""
        path, status = style.user_css(settings)
        self.css_status = status
        url = style.user_css_url(settings)
        watched = self._css_watcher.files()
        if watched and (path is None or str(path) not in watched):
            self._css_watcher.removePaths(watched)
        if path is not None and str(path) not in self._css_watcher.files():
            self._css_watcher.addPath(str(path))
        if url == self._user_css_url and not force:
            return
        self._user_css_url = url
        if self._page_ready:
            self._push({"type": "userCss", "rule": style.import_rule(url, "md-user")})

    def _on_managed_css(self, css: str):
        if self._page_ready:
            self._push({"type": "managedCss", "css": css})

    def _on_css_file_changed(self, _path: str):
        sync = css_sync.engine()
        if sync.path is not None and str(sync.path) == _path:
            return            # feuille partagee : le moteur la relit et previent (fileChanged), ses ecritures non

        # Un enregistrement par fichier temporaire + remplacement retire le fichier du suivi : il est repris.
        QTimer.singleShot(150, lambda: self._push_user_css(_settings()))

    def apply_settings(self, settings: dict, changed: set | None = None):
        """Onglet Markdown des reglages : applique a la page aussitot, sans la recharger (seul ce qui change)."""
        if changed is None or "md_module_padding" in changed:
            self._apply_module_padding(settings)
        css_sync.engine().update(settings, changed)          # sans effet si l'appli l'a deja fait
        if changed is None or "md_css_path" in changed:
            self._push_user_css(settings)
        if changed is None or "md_zoom" in changed:
            self._apply_zoom(settings.get("md_zoom", 100))
        if changed is None or "md_bg_color" in changed:
            self.view.page().setBackgroundColor(QColor(style.css_color(settings.get("md_bg_color") or "#1b1c1d")[:7]))
        if self._page_ready:
            colors_only = changed is not None and all(style.is_color_key(k) for k in changed)
            self._push_style(settings, layout=not colors_only)

    # -- ouverture ---------------------------------------------------------------------------------------------------------
    def can_open(self, path: Path) -> str | None:
        """None si le fichier peut s'ouvrir, sinon la raison."""
        try:
            if not path.is_file():
                return f"« {path.name} » n'existe pas."
            if path.stat().st_size > MAX_TEXT_BYTES:
                return "Fichier trop gros pour l'éditeur (plus de 16 Mo)."
        except OSError as exc:
            return str(exc)
        if not is_markdown(path) and looks_binary(path):
            return "Fichier binaire : il n'est pas ouvert comme du texte."
        return None

    def open(self, path: Path, *, record: bool = True, anchor: str | None = None) -> bool:
        """Ouvre un fichier (note, texte, code). Le texte est lu en fond ; la page le recoit des qu'il est pret.
        `anchor` : titre (ou « ^bloc ») vers lequel defiler (lien « note#titre »)."""
        path = Path(path)
        if self.can_open(path) is not None:
            return False
        if self.path is not None and path != self.path:
            self.flush()
        if record:
            if self.history_index < len(self.history) - 1:
                del self.history[self.history_index + 1:]
            if not self.history or self.history[-1] != path:
                self.history.append(path)
                del self.history[:-100]
            self.history_index = len(self.history) - 1
        self.path = path
        self.kind = "markdown" if is_markdown(path) else "code"
        settings = _settings()
        if self.kind == "markdown":
            default = settings.get("md_default_mode", "last")
            self.mode = settings.get("md_last_mode", "edit") if default == "last" else default
            self.mode = "reading" if self.mode == "reading" else "edit"
        else:
            self.mode = "edit"
        started = time.perf_counter()
        key = str(path)

        def read():
            buffer = self.buffers.get(key)
            if buffer is not None and buffer.dirty:
                return {"text": buffer.text, "info": None}
            text, info = markdown_preview.read_note(path)
            return {"text": text, "info": info}

        def done(value):
            if self.path != path:
                return                                      # un autre fichier a ete demande entre-temps
            if "__error__" in value:
                self._push({"type": "notice", "text": f"{path.name} : {value['__error__']}"})
                return
            if value["info"] is not None:
                self.buffers[key] = _Buffer(path, value["info"], value["text"], value["text"])
                if key not in self._watcher.files():
                    self._watcher.addPath(key)
            info = {"path": key, "title": path.stem if self.kind == "markdown" else path.name, "kind": self.kind,
                    "ext": path.suffix.lstrip(".").lower() or path.name.lower(), "text": value["text"],
                    "dirUrl": path.parent.resolve().as_uri().rstrip("/") + "/", "mode": self.mode,
                    "names": self._cached_names(path), "anchor": anchor}
            self._metrics["read"] = time.perf_counter() - started
            if self._page_ready:
                self._push({"type": "open", "info": info})
            else:
                self._pending_open = info
            if self.kind == "markdown":
                self._refresh_names(path)
        self._in_background(read, done)
        self.pathChanged.emit(key)
        self.stateChanged.emit()
        return True

    # Noms de fichiers de la racine de la note (liens [[nom]], images ![[image.png]]) : gardes par racine, refaits en fond.
    _NAMES: dict = {}

    def _cached_names(self, path: Path) -> dict:
        if self.kind != "markdown":
            return {}
        return self._NAMES.get(str(markdown_preview.note_root(path)), {})

    def _refresh_names(self, path: Path):
        root = markdown_preview.note_root(path)

        def build():
            names = {}
            for name, full in markdown_preview.file_index(root).items():
                if os.path.splitext(name)[1] in NAME_EXTENSIONS:
                    names[name] = Path(full).as_uri()
                    if len(names) >= NAMES_MAX:
                        break
            return names

        def done(names):
            if not isinstance(names, dict) or "__error__" in names:
                return
            changed = self._NAMES.get(str(root)) != names
            self._NAMES[str(root)] = names
            if changed and self.path == path and self._page_ready:
                self._push({"type": "names", "path": str(path), "names": names})
        self._in_background(build, done)

    # -- requetes de la page -------------------------------------------------------------------------------------------------
    def _dispatch(self, req_id: int, name: str, args: str):
        try:
            values = json.loads(args) if args else []
        except ValueError:
            values = []
        handler = getattr(self, "op_" + name, None)
        if handler is None:
            self._reply(req_id, {"__error__": f"operation inconnue : {name}"})
            return
        try:
            result = handler(req_id, *values)
        except Exception as exc:              # noqa: BLE001
            self._reply(req_id, {"__error__": f"{type(exc).__name__}: {exc}"})
            return
        if result is not _ASYNC:
            self._reply(req_id, result)

    def op_changed(self, req_id, path, text):
        buffer = self.buffers.get(path)
        if buffer is None or not isinstance(text, str):
            return False
        was_dirty = buffer.dirty
        buffer.text = text
        if buffer.dirty:
            self._autosave.start()
        if buffer.dirty != was_dirty:
            self.stateChanged.emit()
        return True

    def op_save(self, req_id):
        return self.save_all()

    def op_render(self, req_id, path, text, full=True):
        note = Path(path) if path else MODULE_DIR / "note.md"

        def work():
            if full:
                return markdown_preview.render_body(note, text or "")
            return markdown_preview.render_fragment(text or "", note)
        self._in_background(work, lambda html: self._reply(req_id, html))
        return _ASYNC

    def op_imageSizes(self, req_id, urls):
        """Dimensions des images d'une note (adresses file:/// deja resolues par la page), lues dans leur ENTETE en
        fond, sans decodage : l'editeur reserve leur hauteur avant qu'elles soient affichees (barre de defilement
        juste, rien ne saute). Une image absente ou illisible est omise."""
        urls = [u for u in (urls or []) if isinstance(u, str) and u.startswith("file:")][:IMAGE_SIZES_MAX]

        def work():
            from PySide6.QtGui import QImageReader
            out = {}
            for url in urls:
                local = QUrl(url).toLocalFile()
                if not local:
                    continue
                size = QImageReader(local).size()
                if size.isValid() and size.width() > 0 and size.height() > 0:
                    out[url] = [size.width(), size.height()]
            return out
        self._in_background(work, lambda sizes: self._reply(req_id, sizes))
        return _ASYNC

    def op_openLink(self, req_id, source, target):
        """Lien de la note : un fichier texte s'ouvre dans le module (historique), les autres dans leur logiciel."""
        target = str(target or "").strip()
        if not target:
            return {}
        note = Path(source) if source else self.path
        if note is None:
            return {"error": "Aucune note ouverte."}
        name, _, anchor = target.partition("#")

        def find():
            found = markdown_preview.Resolver(note).find(name) if name else note
            return str(found) if found is not None else None

        def done(found):
            if not isinstance(found, str):
                self._reply(req_id, {"error": f"« {name} » introuvable."})
                return
            found_path = Path(found)
            if is_text_file(found_path) and self.can_open(found_path) is None:
                if found_path != self.path:
                    self.open(found_path, anchor=anchor or None)
                elif anchor:
                    self._push({"type": "anchor", "anchor": anchor})
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(found))
            self._reply(req_id, {"path": found})
        self._in_background(find, done)
        return _ASYNC

    def op_openExternal(self, req_id, url):
        if re.match(r"^(https?|mailto|ftp|obsidian|file):", str(url), re.I):
            QDesktopServices.openUrl(QUrl(str(url)))
        return True

    def op_go(self, req_id, delta):
        self.go(int(delta))
        return True

    def op_close(self, req_id):
        QTimer.singleShot(0, self.closeRequested.emit)
        return True

    def op_modeChanged(self, req_id, mode):
        self.mode = "reading" if mode == "reading" else "edit"
        if self.kind == "markdown":
            saver = HOOKS.get("save_state")
            if saver is not None and _settings().get("md_last_mode") != self.mode:
                saver("md_last_mode", self.mode)
        self.stateChanged.emit()
        return True

    def op_zoomCode(self, req_id, delta):
        settings = _settings()
        zoom = max(-8, min(24, int(settings.get("md_code_font_zoom") or 0) + int(delta)))
        saver = HOOKS.get("save_state")
        if saver is not None:
            saver("md_code_font_zoom", zoom)
        self._push_style({**settings, "md_code_font_zoom": zoom})
        return zoom

    def op_clipboardText(self, req_id):
        return QApplication.clipboard().text()

    def op_attachFile(self, req_id, path):
        """Joindre un fichier : copie dans le dossier de la note (sauf s'il y est deja), lien d'integration."""
        note = Path(path) if path else self.path
        if note is None:
            return []
        files, _ = QFileDialog.getOpenFileNames(self.window(), "Joindre un fichier", str(note.parent))
        links = []
        for name in files:
            source = Path(name)
            try:
                target = source if source.parent.resolve() == note.parent.resolve() else note.parent / source.name
                if target != source:
                    stem, n = target.stem, 1
                    while target.exists():
                        target = target.with_name(f"{stem} {n}{target.suffix}")
                        n += 1
                    import shutil
                    shutil.copy2(source, target)
            except OSError as exc:
                self._push({"type": "notice", "text": str(exc)})
                continue
            rel = target.name.replace(" ", "%20")
            links.append(("!" if target.suffix.lower() in markdown_preview.IMAGE_EMBED_EXTENSIONS else "")
                         + f"[{target.stem}]({rel})")
        if links:
            markdown_preview.forget_index(markdown_preview.note_root(note))
        return links

    def op_menu(self, req_id, entries, x, y):
        """Menu deroulant de la barre d'outils : un menu contextuel de l'appli (habillage des reglages)."""
        from settings_menu import Menu, _section_action
        menu = Menu(self, key="mdeditor:toolbar", editable=False)
        actions = []
        for entry in entries or []:
            if entry == "-":
                menu.addSeparator()
                continue
            if isinstance(entry, dict) and entry.get("section"):
                menu.addAction(_section_action(menu, entry["section"]))
                continue
            action = menu.addAction(str(entry.get("title", "")))
            icon = _entry_icon(entry, self.devicePixelRatioF())
            if icon is not None:
                action.setIcon(icon)
            actions.append(action)
        zoom = self.view.zoomFactor()
        chosen = menu.exec(self.view.mapToGlobal(QPoint(int(float(x) * zoom), int(float(y) * zoom))))
        menu.deleteLater()
        return actions.index(chosen) if chosen in actions else -1

    def op_pickColor(self, req_id, initial="#D83931", title="Couleur"):
        """Ouvre le selecteur de couleurs de l'interface et renvoie la couleur validee."""
        from settings_widgets import _ColorPickerPopup
        popup = _ColorPickerPopup(str(initial or "#D83931"), str(title or "Couleur"), self)
        popup.committed.connect(lambda value: (self._reply(req_id, value), popup.deleteLater()))
        popup.cancelled.connect(lambda: (self._reply(req_id, None), popup.deleteLater()))
        popup.show_near(self.view)
        return _ASYNC

    def op_saveToolbarColors(self, req_id, colors):
        """Garde les couleurs actives de la barre d'outils pour les prochaines ouvertures."""
        saver = HOOKS.get("save_state")
        if saver is None or not isinstance(colors, dict):
            return False
        for source, key in (("fontColor", "md_toolbar_font_color"),
                            ("backgroundColor", "md_toolbar_background_color")):
            color = QColor(str(colors.get(source, "")))
            if color.isValid():
                value = color.name(QColor.NameFormat.HexArgb) if color.alpha() < 255 else color.name()
                saver(key, value)
        return True

    def op_ensureTableCellBackgroundCss(self, req_id):
        return css_sync.engine().ensure_table_cell_background_css()

    def op_metrics(self, req_id, data):
        self._metrics["page"] = data
        return True

    # -- historique ---------------------------------------------------------------------------------------------------------
    @property
    def can_back(self) -> bool:
        return self.history_index > 0

    @property
    def can_forward(self) -> bool:
        return 0 <= self.history_index < len(self.history) - 1

    def go(self, delta: int):
        index = self.history_index + delta
        while 0 <= index < len(self.history):
            target = self.history[index]
            if self.can_open(target) is None:
                self.history_index = index
                self.open(target, record=False)
                return
            del self.history[index]                         # fichier disparu : retire de l'historique
            if delta < 0:
                index -= 1
                self.history_index -= 1

    # -- commandes de la barre de l'appli ---------------------------------------------------------------------------------
    def toggle_mode(self):
        if self.kind == "markdown":
            self._push({"type": "toggleMode"})

    def find(self):
        self._push({"type": "find"})

    def open_in_obsidian(self) -> bool:
        url = markdown_preview.obsidian_open_url(self.path) if self.path is not None else None
        return bool(url) and QDesktopServices.openUrl(QUrl(url))

    def metrics(self) -> dict:
        return dict(self._metrics)

    # -- enregistrement -----------------------------------------------------------------------------------------------------
    def save(self, buffer: _Buffer) -> bool:
        if not buffer.dirty:
            return True
        path, info = buffer.path, buffer.info
        if markdown_preview.changed_on_disk(path, info):
            box = QMessageBox(QMessageBox.Warning, "Fichier modifié ailleurs",
                              f"« {path.name} » a été modifié en dehors de l'éditeur (Obsidian, synchronisation…) "
                              "depuis son ouverture.", parent=self.window())
            keep = box.addButton("Garder ma version", QMessageBox.AcceptRole)
            reload = box.addButton("Recharger le fichier", QMessageBox.DestructiveRole)
            box.addButton("Annuler", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is reload:
                try:
                    text, buffer.info = markdown_preview.read_note(path)
                except OSError as exc:
                    buffer.error = f"{path.name} : {exc}"
                    return False
                buffer.saved = buffer.text = text
                buffer.error = None
                self._push({"type": "reload", "path": str(path), "text": text})
                self.stateChanged.emit()
                return True
            if box.clickedButton() is not keep:
                buffer.error = "Non enregistré : le fichier a été modifié ailleurs."
                self._push({"type": "notice", "text": buffer.error})
                return False
        text = buffer.text
        try:
            markdown_preview.write_note(path, text, info)
        except OSError as exc:
            buffer.error = f"Enregistrement impossible : {exc}"
            self._push({"type": "notice", "text": buffer.error})
            self.stateChanged.emit()
            return False
        buffer.saved = text
        buffer.error = None
        self._push({"type": "saved", "path": str(path), "text": text})
        self.stateChanged.emit()
        return True

    def save_all(self) -> bool:
        self._autosave.stop()
        ok = True
        for buffer in list(self.buffers.values()):
            if buffer.dirty:
                ok = self.save(buffer) and ok
        # Memoire : seuls les fichiers modifies et le fichier affiche restent.
        for key in [k for k, b in self.buffers.items() if not b.dirty and Path(k) != self.path]:
            self.buffers.pop(key, None)
            if key in self._watcher.files():
                self._watcher.removePath(key)
        return ok

    def is_dirty(self) -> bool:
        return any(buffer.dirty for buffer in self.buffers.values())

    def flush(self, timeout_ms: int = 600) -> bool:
        """Recupere le texte en cours dans la page (frappe des 250 dernieres ms) puis enregistre."""
        self._pull_text(timeout_ms)
        return self.save_all()

    def _pull_text(self, timeout_ms: int = 600):
        """Texte du fichier affiche tel qu'il est DANS la page (la frappe recente n'est pas encore envoyee)."""
        if self._page_ready and self.path is not None:
            loop = QEventLoop()
            result = {}

            def got(value):
                result["value"] = value
                loop.quit()
            # En JSON : un tableau JavaScript arrive vide de ce cote (conversion de QtWebEngine).
            self.view.page().runJavaScript(
                "(function(){try{return JSON.stringify(MD.currentText())}catch(e){return 'null'}})()", got)
            QTimer.singleShot(timeout_ms, loop.quit)
            loop.exec()
            try:
                value = json.loads(result.get("value") or "null")
            except (TypeError, ValueError):
                value = None
            if isinstance(value, list) and len(value) == 2 and isinstance(value[1], str):
                buffer = self.buffers.get(value[0])
                if buffer is not None:
                    buffer.text = value[1]

    def _on_file_changed(self, path_text: str):
        """Fichier ouvert modifie sur le disque : le notre (rien a faire), ou celui d'Obsidian / de la synchro."""
        path = Path(path_text)
        buffer = self.buffers.get(path_text)
        if path.exists() and path_text not in self._watcher.files():
            self._watcher.addPath(path_text)          # remplace par un nouveau fichier (synchro) : on le suit encore
        if buffer is None or not markdown_preview.changed_on_disk(path, buffer.info):
            return
        if Path(path_text) == self.path:
            self._pull_text(300)                     # frappe pas encore envoyee : elle compte comme une modification
        if buffer.dirty:
            return                                   # la question sera posee a l'enregistrement
        try:
            text, info = markdown_preview.read_note(path)
        except OSError:
            return
        buffer.info, buffer.saved, buffer.text = info, text, text
        self._push({"type": "reload", "path": path_text, "text": text})

    # -- affichage ------------------------------------------------------------------------------------------------------------
    def attach(self, host: QWidget):
        """Pose le panneau sur la zone des colonnes (et le garde a sa taille)."""
        if self.parentWidget() is not host:
            self.setParent(host)
        self.setGeometry(host.rect())
        host.installEventFilter(self)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.parentWidget() and event.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
        return False

    def fade_in(self):
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        self.show()
        self.raise_()
        animation = self._fade = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(FADE_MS)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.finished.connect(lambda: self.setGraphicsEffect(None))
        animation.start()
        self.view.setFocus()
        self._push({"type": "focus"})

    def fade_out(self, done=None):
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        animation = self._fade = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(FADE_MS)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)

        def finished():
            self.hide()
            self.setGraphicsEffect(None)
            if done is not None:
                done()
        animation.finished.connect(finished)
        animation.start()

    def confirm_leave(self) -> bool:
        """Avant de fermer : tout est enregistre (les conflits demandent a l'utilisateur). False = annule."""
        if not self.flush():
            box = QMessageBox(QMessageBox.Warning, "Modifications non enregistrées",
                              "Certaines modifications n'ont pas pu être enregistrées.", parent=self.window())
            stay = box.addButton("Rester dans l'éditeur", QMessageBox.RejectRole)
            box.addButton("Fermer quand même", QMessageBox.DestructiveRole)
            box.exec()
            if box.clickedButton() is stay:
                return False
        self.buffers = {k: b for k, b in self.buffers.items() if b.dirty}
        return True

    def _on_quit(self):
        try:
            self.flush(300)
        except RuntimeError:
            pass
        self._pool.shutdown(wait=False, cancel_futures=True)


def _entry_icon(entry: dict, ratio: float) -> QIcon | None:
    """Icone d'une ligne de menu : pastille de couleur, ou icone SVG de la barre d'outils."""
    size = 16
    if entry.get("color"):
        pixmap = QPixmap(int(size * ratio), int(size * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        value = str(entry["color"])
        # Couleurs de la barre au format CSS « #rrggbbaa » ; QColor lit « #aarrggbb ».
        color = QColor(f"#{value[7:9]}{value[1:7]}" if len(value) == 9 and value.startswith("#") else value)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(1, 1, size - 2, size - 2, 3, 3)
        painter.end()
        return QIcon(pixmap)
    svg = entry.get("svg")
    if svg:
        try:
            from PySide6.QtSvg import QSvgRenderer
        except ImportError:
            return None
        text = re.sub(r'stroke="currentColor"', 'stroke="#d6d9dc"', svg)
        text = re.sub(r'fill="currentColor"', 'fill="#d6d9dc"', text)
        renderer = QSvgRenderer(QByteArray(text.encode("utf-8")))
        if not renderer.isValid():
            return None
        pixmap = QPixmap(int(size * ratio), int(size * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)
    return None


# -- Instance unique (prechargee) ----------------------------------------------------------------------------------------

_PANE: MarkdownPane | None = None


def instance(create: bool = True) -> MarkdownPane | None:
    global _PANE
    if _PANE is not None:
        try:
            _PANE.isVisible()
        except RuntimeError:
            _PANE = None
    if _PANE is None and create:
        _PANE = MarkdownPane()
        _PANE.hide()
    return _PANE
