"""Notes Markdown : rendu HTML (mode lecture du module Markdown, apercu de l'inspecteur) et lecture / ecriture
FIDELES des fichiers texte.

Conversion : markdown-it-py (+ mdit-py-plugins) — CommonMark, tableaux, barre, cases a cocher, notes de bas de page,
proprietes (front-matter) — plus la syntaxe courante des notes de l'utilisateur ecrites dans Obsidian : liens
[[note|alias]], images ![[image.png|300]], ==surlignage==, #tags, %%commentaires%%, callouts « > [!type] titre »,
adresses web en clair. Images et liens relatifs resolus depuis le dossier de la note (sous-dossiers compris), puis
par NOM dans la racine de la note (coffre = parent qui a un dossier .obsidian, sinon le dossier de la note) ;
references d'origine jamais modifiees (seul le HTML pointe vers les fichiers).

Apparence : AUCUN style ici ; la page de l'inspecteur prend la feuille du module (fm_markdown/web/base.css) et les
variables des reglages (fm_markdown/style.py) : meme rendu que le mode lecture du module.
Aucune dependance vers le reste de l'appli hors config."""
from __future__ import annotations

import html
import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote, unquote

MARKDOWN_EXTENSIONS = {".md", ".markdown"}
IMAGE_EMBED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".avif"}
INDEX_MAX_FILES = 30000          # au-dela, la recherche par nom s'arrete (racine geante : F:\PIPELINE...)
INDEX_TTL = 30.0                 # secondes avant de reparcourir une racine


def available() -> bool:
    try:
        import markdown_it  # noqa: F401
        return True
    except ImportError:
        return False


# -- Racine d'une note et coffres Obsidian ---------------------------------------------------------------------------

def note_root(note: Path) -> Path:
    """Racine de resolution par NOM : le coffre qui contient la note (parent avec `.obsidian`), sinon son dossier."""
    try:
        note = note.resolve()
    except OSError:
        pass
    for parent in note.parents:
        if (parent / ".obsidian").is_dir():
            return parent
    return note.parent


def vault_containing(note: Path) -> Path | None:
    """Coffre Obsidian qui CONTIENT la note (un parent avec `.obsidian`, ou un coffre declare dans
    %APPDATA%/obsidian/obsidian.json qui en est un parent) ; None sinon."""
    try:
        resolved = note.resolve()
    except OSError:
        return None
    for parent in resolved.parents:
        if (parent / ".obsidian").is_dir():
            return parent
    config = Path(os.environ.get("APPDATA", "")) / "obsidian" / "obsidian.json"
    try:
        vaults = json.loads(config.read_text(encoding="utf-8")).get("vaults", {}).values()
    except (OSError, ValueError):
        return None
    for vault in vaults:
        try:
            root = Path(vault.get("path", "")).resolve()
        except OSError:
            continue
        if root in resolved.parents:
            return root
    return None


def obsidian_open_url(note: Path) -> str | None:
    """Lien qui ouvre l'application Obsidian SUR cette note (`obsidian://open?path=<chemin absolu>`) ; None si la note
    n'est dans aucun coffre."""
    if note.suffix.lower() != ".md" or vault_containing(note) is None:
        return None
    return "obsidian://open?path=" + quote(str(note.resolve()), safe="")


# -- Index des noms de fichiers d'une racine (liens [[nom]], images ![[image.png]]) -----------------------------------

_INDEX: dict = {}
_INDEX_LOCK = threading.Lock()


def file_index(root: Path) -> dict:
    """{nom en minuscules: chemin} des fichiers de `root` (sous-dossiers compris, dossiers caches exclus), le plus
    proche de la racine gagne. Parcouru au plus une fois par `INDEX_TTL` (a appeler hors du fil de l'interface)."""
    key = str(root)
    now = time.monotonic()
    with _INDEX_LOCK:
        cached = _INDEX.get(key)
        if cached is not None and now - cached[0] < INDEX_TTL:
            return cached[1]
    names: dict = {}
    count = 0
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in files:
            names.setdefault(name.casefold(), os.path.join(folder, name))
            count += 1
        if count > INDEX_MAX_FILES:
            break
    with _INDEX_LOCK:
        _INDEX[key] = (now, names)
    return names


def forget_index(root: Path | None = None):
    with _INDEX_LOCK:
        if root is None:
            _INDEX.clear()
        else:
            _INDEX.pop(str(root), None)


class Resolver:
    """Fichier vise par un lien depuis une note : chemin relatif a la note, puis a la racine, puis par nom."""

    def __init__(self, note: Path, root: Path | None = None):
        self.note = note
        self.root = root or note_root(note)
        self._names = None

    def find(self, target: str) -> Path | None:
        target = unquote(target or "").strip().replace("\\", "/")
        if not target:
            return None
        if re.match(r"^[a-zA-Z]:/|^/", target):
            candidate = Path(target)
            return candidate if candidate.is_file() else None
        names = [target] if Path(target).suffix else [target + ".md", target]
        for base in (self.note.parent, self.root):
            for name in names:
                candidate = base / name
                try:
                    if candidate.is_file():
                        return candidate
                except OSError:
                    continue
        if self._names is None:
            self._names = file_index(self.root)
        for name in names:
            found = self._names.get(Path(name).name.casefold())
            if found is not None:
                return Path(found)
        return None


def file_url(path: Path) -> str:
    return Path(path).resolve().as_uri()


# -- Markdown -> HTML ---------------------------------------------------------------------------------------------------

_INLINE_RE = re.compile(
    r"(?P<wiki>(?P<bang>!)?\[\[(?P<target>[^\]\|]*?)(?:\|(?P<alias>[^\]]*))?\]\])"
    r"|(?P<mark>==(?P<marked>[^=\n]+?)==)"
    r"|(?P<tag>(?<![\w/&#])#(?P<tagname>[^\s\d#.,;:!?()\[\]{}'\"`][^\s#.,;:!?()\[\]{}'\"`]*))"
)
_URL_RE = re.compile(r"(?P<url>(?:https?|ftp)://[^\s<>\"'\[\]]*[^\s<>\"'\[\].,;:!?)])")
_CALLOUT_RE = re.compile(r"^\[!(?P<type>[^\]|]*)(?:\|(?P<meta>[^\]]*))?\](?P<fold>[+-]?)[ \t]*(?P<title>[^\n]*)\n?")
_COMMENT_RE = re.compile(r"%%.*?%%", re.S)
_SIZE_RE = re.compile(r"^\s*(\d+)(?:x(\d+))?\s*$")


def _size_attrs(text: str | None) -> str:
    match = _SIZE_RE.match(text or "")
    if not match:
        return ""
    return f' width="{match.group(1)}"' + (f' height="{match.group(2)}"' if match.group(2) else "")


def _make_parser(resolver: Resolver):
    from markdown_it import MarkdownIt
    from markdown_it.token import Token
    from mdit_py_plugins.footnote import footnote_plugin
    from mdit_py_plugins.front_matter import front_matter_plugin
    from mdit_py_plugins.tasklists import tasklists_plugin

    md = MarkdownIt("commonmark", {"html": True, "breaks": True}).enable(["table", "strikethrough"])
    # Cases actives (pas « disabled ») : un clic dans la lecture du module coche la tache dans le texte, comme Obsidian.
    md.use(front_matter_plugin).use(footnote_plugin).use(tasklists_plugin, enabled=True)

    # Callouts « > [!type] titre » : le blockquote devient un callout.
    def callouts(state):
        stack, tokens, i = [], state.tokens, 0
        while i < len(tokens):
            token = tokens[i]
            if token.type == "blockquote_open":
                inline = tokens[i + 2] if i + 2 < len(tokens) and tokens[i + 1].type == "paragraph_open" else None
                match = _CALLOUT_RE.match(inline.content) if inline is not None and inline.type == "inline" else None
                if match:
                    label = match.group("type").strip()
                    token.meta = {"callout": (label or "note").lower(), "fold": match.group("fold"),
                                  "title": match.group("title").strip(), "label": label}
                    inline.content = inline.content[match.end():]
                    if not inline.content.strip():
                        del tokens[i + 1:i + 4]          # paragraphe qui ne portait que le titre
                stack.append(bool(match))
            elif token.type == "blockquote_close" and stack:
                if stack.pop():
                    token.meta = {"callout": True}
            i += 1

    md.core.ruler.before("inline", "md_callouts", callouts)

    def blockquote_open(renderer, tokens, idx, options, env):
        meta = tokens[idx].meta or {}
        if not meta.get("callout"):
            return "<blockquote>\n"
        kind, fold = meta["callout"], meta["fold"]
        label = meta.get("label") or kind
        title = md.renderInline(meta["title"]) if meta["title"] else html.escape(label[:1].upper() + label[1:])
        classes = "callout" + (" is-collapsible" if fold else "") + (" is-collapsed" if fold == "-" else "")
        # Structure Obsidian : icone + titre + chevron, puis contenu. Les classes restent identiques en lecture
        # et dans le bloc de l'editeur, donc un snippet Obsidian peut les habiller sans adaptation.
        icons = {
            "info": "i", "note": "i", "abstract": "≡", "summary": "≡", "tldr": "≡", "tip": "✦",
            "hint": "✦", "important": "!", "success": "✓", "check": "✓", "done": "✓", "question": "?",
            "help": "?", "faq": "?", "warning": "!", "caution": "!", "attention": "!", "failure": "×",
            "fail": "×", "missing": "×", "danger": "⚠", "error": "×", "bug": "•", "example": "◇", "quote": "❝",
            "cite": "❝",
        }
        icon = html.escape(icons.get(kind, "i"))
        fold_attr = f' data-callout-fold="{html.escape(fold)}"' if fold else ""
        chevron = '<div class="callout-fold">⌄</div>' if fold else ""
        return (f'<div class="{classes}" data-callout="{html.escape(kind)}"{fold_attr}><div class="callout-title">'
                f'<div class="callout-icon" aria-hidden="true">{icon}</div><div class="callout-title-inner">{title}</div>{chevron}</div>'
                f'<div class="callout-content">\n')

    def blockquote_close(renderer, tokens, idx, options, env):
        return "</div></div>\n" if (tokens[idx].meta or {}).get("callout") else "</blockquote>\n"

    md.add_render_rule("blockquote_open", blockquote_open)
    md.add_render_rule("blockquote_close", blockquote_close)

    # Images markdown : chemin resolu depuis la note (la reference du texte ne change pas), « alt|300 » = largeur.
    def image(renderer, tokens, idx, options, env):
        token = tokens[idx]
        src = token.attrGet("src") or ""
        alt = renderer.renderInlineAsText(token.children or [], options, env)
        alt, _, size = alt.partition("|")
        if not re.match(r"^[a-zA-Z][\w+.-]*:", src):
            found = resolver.find(src)
            if found is None:
                return f'<span class="md-image-missing">{html.escape(src)}</span>'
            src = file_url(found)
        title = token.attrGet("title")
        extra = f' title="{html.escape(title)}"' if title else ""
        return f'<img src="{html.escape(src)}" alt="{html.escape(alt)}"{_size_attrs(size)}{extra}>'

    md.add_render_rule("image", image)

    # Liens markdown vers un fichier local : resolus, gardent leur cible d'origine (data-href) pour la navigation.
    def link_open(renderer, tokens, idx, options, env):
        token = tokens[idx]
        href = token.attrGet("href") or ""
        if href and not href.startswith("#") and not re.match(r"^[a-zA-Z][\w+.-]*:", href):
            found = resolver.find(href.split("#")[0])
            token.attrSet("data-href", href)
            token.attrSet("class", "internal-link" if found is not None else "internal-link is-unresolved")
            token.attrSet("href", file_url(found) if found is not None else "#")
        return renderer.renderToken(tokens, idx, options, env)

    md.add_render_rule("link_open", link_open)

    # Syntaxe propre aux notes Obsidian dans le texte (jamais dans le code).
    def replace(match) -> str:
        if match.group("wiki"):
            raw_target = match.group("target") or ""
            target, _, anchor = raw_target.partition("#")
            alias = match.group("alias")
            found = resolver.find(target) if target else None
            if match.group("bang"):
                if found is not None and found.suffix.lower() in IMAGE_EMBED_EXTENSIONS:
                    return (f'<img src="{html.escape(file_url(found))}" alt="{html.escape(found.name)}"'
                            f'{_size_attrs(alias)}>')
                if found is None and Path(target).suffix.lower() in IMAGE_EMBED_EXTENSIONS:
                    return f'<span class="md-image-missing">{html.escape(target)}</span>'
            label = alias or ((Path(target).stem + (f" > {anchor}" if anchor else "")) if target else anchor)
            classes = "internal-link" + ("" if found is not None or not target else " is-unresolved")
            href = file_url(found) if found is not None else "#"
            return (f'<a data-href="{html.escape(raw_target)}" href="{html.escape(href)}" class="{classes}">'
                    f"{html.escape(label or raw_target)}</a>")
        if match.group("mark"):
            return f"<mark>{html.escape(match.group('marked'))}</mark>"
        tag = match.group("tagname")
        return f'<a href="#" class="tag" data-tag="{html.escape(tag)}">#{html.escape(tag)}</a>'

    def split(content: str, in_link: bool) -> list:
        spans = [(m.start(), m.end(), replace(m)) for m in _INLINE_RE.finditer(content)]
        if not in_link:
            for m in _URL_RE.finditer(content):
                if not any(a < m.end() and m.start() < b for a, b, _ in spans):
                    url = html.escape(m.group("url"))
                    spans.append((m.start(), m.end(), f'<a class="external-link" href="{url}">{url}</a>'))
        return sorted(spans)

    def inline_rule(state):
        for token in state.tokens:
            if token.type != "inline" or not token.children:
                continue
            children, in_link = [], 0
            for child in token.children:
                if child.type in ("link_open", "link_close"):
                    in_link += 1 if child.type == "link_open" else -1
                spans = split(child.content, in_link > 0) if child.type == "text" else []
                if not spans:
                    children.append(child)
                    continue
                pos = 0
                for start, end, markup in spans:
                    if start > pos:
                        text = Token("text", "", 0)
                        text.content = child.content[pos:start]
                        children.append(text)
                    raw = Token("html_inline", "", 0)
                    raw.content = markup
                    children.append(raw)
                    pos = end
                if pos < len(child.content):
                    text = Token("text", "", 0)
                    text.content = child.content[pos:]
                    children.append(text)
            token.children = children

    md.core.ruler.after("inline", "md_inline", inline_rule)
    return md


def _properties_html(front_matter: str) -> str:
    """Proprietes (front-matter YAML simple : « cle: valeur » et listes « - element ») en tableau."""
    rows, key = [], None
    for line in front_matter.splitlines():
        if not line.strip():
            continue
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and key is not None:
            rows[-1][1].append(item.group(1).strip().strip("'\""))
            continue
        pair = re.match(r"^([^:#]+):\s*(.*)$", line)
        if pair:
            key = pair.group(1).strip()
            value = pair.group(2).strip().strip("'\"")
            rows.append((key, [value] if value else []))
    if not rows:
        return ""
    body = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(', '.join(v))}</td></tr>" for k, v in rows)
    return f'<div class="md-properties"><table><tbody>{body}</tbody></table></div>'


# Ancienne syntaxe HTML encore ecrite par plusieurs outils Markdown (et par l'ancienne barre) :
# Chromium ne lui applique pas toujours la couleur dans les contextes Obsidian. Un span CSS est interoperable.
_FONT_COLOR_RE = re.compile(r"<font\s+color\s*=\s*([\"']?)([^\s>\"']+)\1\s*>(.*?)</font\s*>", re.I | re.S)
def _normalise_legacy_fonts(text: str) -> str:
    return _FONT_COLOR_RE.sub(lambda m: f'<span style="color: {m.group(2)}">{m.group(3)}</span>', text)

def render_body(note: Path, text: str, *, root: Path | None = None, properties: bool = True) -> str:
    """HTML d'une note (sans titre ni page autour) : proprietes puis contenu. A appeler hors du fil de l'interface
    (la resolution par nom peut parcourir la racine une fois)."""
    text = _normalise_legacy_fonts(_COMMENT_RE.sub("", text))
    md = _make_parser(Resolver(note, root))
    env: dict = {}
    tokens = md.parse(text, env)
    body = md.renderer.render(tokens, md.options, env)
    if not properties:
        return body
    front = next((t.content for t in tokens if t.type == "front_matter"), "")
    return _properties_html(front) + body


def render_fragment(text: str, note: Path, *, root: Path | None = None) -> str:
    """Un bloc seul (tableau, callout de l'edition), rendu comme en lecture."""
    return render_body(note, text, root=root, properties=False)


def render_page(note: Path, text: str | None = None, settings: dict | None = None) -> str:
    """Page HTML complete d'une note pour l'inspecteur : feuille du module Markdown + variables des reglages, meme
    rendu que le mode lecture du module (coloration des blocs de code comprise)."""
    if text is None:
        text, _info = read_note(note)
    from fm_markdown import css_sync, style, web_dir
    if settings is None:
        import ui_state
        settings = ui_state.APPLIED_SETTINGS or {}
    body = render_body(note, text)
    # Inspecteur : apercu sans enregistrement, cases inertes.
    body = body.replace('<input class="task-list-item-checkbox"', '<input class="task-list-item-checkbox" disabled="disabled"')
    web = web_dir()
    scripts = ""
    if "<pre><code class=\"language-" in body:
        # Coloration des blocs de code : le moteur de l'editeur (CodeMirror) et sa coloration, charges seulement
        # quand la note en a besoin.
        names = ("vendor/codemirror.js", "vendor/meta.min.js", "vendor/markdown.js", "vendor/modes.min.js",
                 "highlight.js")
        scripts = "".join(f'<script src="{(web / n).as_uri()}"></script>' for n in names)
        scripts += "<script>MD.highlightAll(document.body)</script>"
    # Memes couches que le module : habillage des reglages, puis la feuille choisie (Reglages > Markdown > CSS),
    # avec les classes d'Obsidian. La page defile par `html` (jamais par `body`) : protege dans la 1re couche.
    imports = "\n".join(f"<style>{style.import_rule(url, layer)}</style>" for url, layer in (
        ((web / "bullets.css").as_uri(), "md-structure"), ((web / "base.css").as_uri(), "md-theme"),(style.user_css_url(settings), "md-user")) if url)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(note.stem)}</title>
<style>{style.LAYER_ORDER}
@layer md-structure {{ html {{ height: auto !important; overflow: auto !important; margin: 0 !important; }}
  body {{ height: auto !important; overflow: visible !important; margin: 0 !important; }} }}</style>
{imports}
<style>{css_sync.current_injection()}</style>
<style>{style.css_variables(settings)}</style>
</head><body class="md-page {style.theme_class(settings)}">
<div class="md-read md-view is-shown markdown-reading-view" style="position:static">
<div class="md-sizer markdown-preview-view markdown-rendered">
<div class="md-title inline-title">{html.escape(note.stem)}</div>
<div class="md-body md-rendered markdown-preview-sizer markdown-preview-section">{body}</div></div></div>
{scripts}
</body></html>"""


# -- Lecture / ecriture fideles ----------------------------------------------------------------------------------------

def read_note(path: Path) -> tuple[str, dict]:
    """(texte a fins de ligne « \n », infos pour le reecrire a l'identique : encodage, BOM, fins de ligne, date de
    modification lue)."""
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    encoding = "utf-8"
    try:
        text = raw[3 if bom else 0:].decode("utf-8")
    except UnicodeDecodeError:
        encoding, text = "cp1252", raw.decode("cp1252", errors="replace")
    newline = "\r\n" if "\r\n" in text else "\n"
    info = {"encoding": encoding, "bom": bom, "newline": newline, "mtime_ns": path.stat().st_mtime_ns}
    return text.replace("\r\n", "\n"), info


def changed_on_disk(path: Path, info: dict) -> bool:
    """Le fichier a ete modifie (ou supprime) depuis sa lecture : Obsidian, synchro..."""
    try:
        return path.stat().st_mtime_ns != info.get("mtime_ns")
    except OSError:
        return True


def write_note(path: Path, text: str, info: dict) -> None:
    """Reecrit le fichier avec l'encodage, la BOM et les fins de ligne d'origine ; fichier temporaire puis
    remplacement : jamais de fichier a moitie ecrit. Met a jour info["mtime_ns"]."""
    data = text.replace("\n", info.get("newline", "\n")).encode(info.get("encoding", "utf-8"), errors="replace")
    if info.get("bom"):
        data = b"\xef\xbb\xbf" + data
    temporary = path.with_name(f".{path.name}.pipeline-edit.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    info["mtime_ns"] = path.stat().st_mtime_ns
