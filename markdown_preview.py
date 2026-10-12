"""Apercu des notes Markdown avec le CSS d'Obsidian : page HTML complete (pour QWebEngineView,
voir DetailPanel) qui reproduit la structure du mode lecture d'Obsidian, pour que ses regles
s'appliquent telles quelles.

CSS, dans l'ordre d'Obsidian : son app.css (lu dans SON installation, archive obsidian.asar,
extrait une fois avec ses polices dans data/obsidian_cache/<date de l'archive>/), le theme du
coffre puis ses snippets ACTIVES (.obsidian/themes, .obsidian/snippets, relus a chaque rendu),
et les reglages d'apparence du coffre (clair/sombre, accent, polices, taille de texte). Coffre =
celui qui contient la note (dossier .obsidian dans un parent), sinon celui ouvert dans Obsidian
(%APPDATA%/obsidian/obsidian.json).

Conversion : markdown-it-py (+ mdit-py-plugins) et la syntaxe propre a Obsidian ajoutee par-dessus :
[[liens]] et ![[integrations]] (resolus dans le dossier de la note puis dans le coffre), callouts
« > [!type] titre », ==surlignage==, #tags, %%commentaires%%, proprietes (front-matter).
Pas encore : formules ($...$) et diagrammes Mermaid (montres comme du code).
Aucune dependance vers le reste de l'appli hors config."""
from __future__ import annotations

import colorsys
import html
import json
import os
import re
import shutil
import struct
import threading
from pathlib import Path

from config import DATA_DIR

MARKDOWN_EXTENSIONS = {".md", ".markdown"}
IMAGE_EMBED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".avif"}
CACHE_DIR = DATA_DIR / "obsidian_cache"
_LOCK = threading.Lock()


def available() -> bool:
    try:
        import markdown_it  # noqa: F401
        return True
    except ImportError:
        return False


# -- Installation d'Obsidian : app.css et ses ressources ------------------------------------------

def obsidian_asar() -> Path | None:
    candidates = []
    if os.environ.get("OBSIDIAN_ASAR"):
        candidates.append(Path(os.environ["OBSIDIAN_ASAR"]))
    for root in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles"), r"C:\Program Files"):
        if root:
            candidates += [Path(root) / "Programs" / "Obsidian" / "resources" / "obsidian.asar",
                           Path(root) / "Obsidian" / "resources" / "obsidian.asar"]
    return next((p for p in candidates if p.is_file()), None)


def _asar_entries(asar: Path) -> tuple[dict, int]:
    """(arbre des fichiers, debut des donnees) d'une archive asar (format d'Electron : entete
    JSON precede de sa taille)."""
    with open(asar, "rb") as stream:
        _, header_size, _, json_size = struct.unpack("<4I", stream.read(16))
        return json.loads(stream.read(json_size)), 8 + header_size


def _asar_extract(asar: Path, header: dict, base: int, inner: str, dest: Path):
    """Extrait le fichier ou le dossier `inner` (chemin a / dans l'archive) sous `dest`."""
    node = header
    for part in inner.split("/"):
        node = node.get("files", {}).get(part)
        if node is None:
            return
    with open(asar, "rb") as stream:
        def write(entry: dict, rel: str):
            if "files" in entry:
                for name, child in entry["files"].items():
                    write(child, f"{rel}/{name}")
                return
            if entry.get("unpacked") or "offset" not in entry:
                return
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            stream.seek(base + int(entry["offset"]))
            target.write_bytes(stream.read(int(entry["size"])))
        write(node, inner)


def obsidian_assets() -> Path | None:
    """Dossier local avec app.css, public/ (polices, images) et lib/prism.min.js, extraits de
    l'installation d'Obsidian. Refait quand l'archive change (mise a jour d'Obsidian)."""
    asar = obsidian_asar()
    if asar is None:
        return None
    try:
        stamp = str(int(asar.stat().st_mtime))
    except OSError:
        return None
    dest = CACHE_DIR / stamp
    with _LOCK:
        if (dest / "app.css").is_file():
            return dest
        try:
            header, base = _asar_entries(asar)
            work = CACHE_DIR / (stamp + ".tmp")
            shutil.rmtree(work, ignore_errors=True)
            for inner in ("app.css", "public", "lib/prism.min.js"):
                _asar_extract(asar, header, base, inner, work)
            if not (work / "app.css").is_file():
                return None
            shutil.rmtree(dest, ignore_errors=True)
            work.rename(dest)
            for old in CACHE_DIR.iterdir():          # versions precedentes d'Obsidian
                if old != dest:
                    shutil.rmtree(old, ignore_errors=True)
            return dest
        except (OSError, ValueError, KeyError, struct.error):
            return None


# -- Coffre (vault) et son apparence ---------------------------------------------------------------

def vault_for(note: Path) -> Path | None:
    for parent in note.resolve().parents:
        if (parent / ".obsidian").is_dir():
            return parent
    config = Path(os.environ.get("APPDATA", "")) / "obsidian" / "obsidian.json"
    try:
        vaults = json.loads(config.read_text(encoding="utf-8")).get("vaults", {}).values()
    except (OSError, ValueError):
        return None
    ordered = sorted(vaults, key=lambda v: (bool(v.get("open")), v.get("ts", 0)), reverse=True)
    for vault in ordered:
        path = Path(vault.get("path", ""))
        if (path / ".obsidian").is_dir():
            return path
    return None


def vault_containing(note: Path) -> Path | None:
    """Coffre Obsidian qui CONTIENT vraiment la note (un parent avec `.obsidian`, ou un coffre declare dans
    %APPDATA%/obsidian/obsidian.json qui en est un parent) ; None sinon (contrairement a vault_for, pas
    de repli sur le coffre ouvert)."""
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
    """Lien qui ouvre Obsidian SUR cette note (`obsidian://open?path=<chemin absolu>` : Obsidian ouvre le
    coffre qui la contient) ; None si la note n'est dans aucun coffre."""
    if note.suffix.lower() != ".md" or vault_containing(note) is None:
        return None
    from urllib.parse import quote
    return "obsidian://open?path=" + quote(str(note.resolve()), safe="")


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _hex_to_hsl(value: str):
    value = value.lstrip("#")
    if len(value) != 6:
        return None
    try:
        r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return None
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return round(h * 360), round(s * 100), round(l * 100)


def _body(appearance: dict, app_settings: dict) -> tuple[str, str]:
    """(classes, style) du <body>, comme Obsidian les pose d'apres l'apparence du coffre."""
    theme = appearance.get("theme", "obsidian")
    classes = ["obsidian-app", "mod-windows", "theme-light" if theme == "moonstone" else "theme-dark"]
    if app_settings.get("showInlineTitle", True):
        classes.append("show-inline-title")
    style = []
    hsl = _hex_to_hsl(appearance.get("accentColor") or "")
    if hsl:
        style.append("--accent-h: %d; --accent-s: %d%%; --accent-l: %d%%;" % hsl)
    for key, var in (("interfaceFontFamily", "--font-interface-override"),
                     ("textFontFamily", "--font-text-override"),
                     ("monospaceFontFamily", "--font-monospace-override")):
        family = (appearance.get(key) or "").strip()
        if family:
            style.append("%s: '%s';" % (var, family.replace("'", "")))
    if appearance.get("baseFontSize"):
        style.append("--font-text-size: %dpx;" % int(appearance["baseFontSize"]))
    return " ".join(classes), " ".join(style)


def vault_stylesheets(vault: Path | None, appearance: dict) -> list[Path]:
    """Theme puis snippets ACTIVES du coffre, dans l'ordre d'Obsidian (fichiers existants)."""
    if vault is None:
        return []
    sheets = []
    theme = (appearance.get("cssTheme") or "").strip()
    if theme:
        for candidate in (vault / ".obsidian" / "themes" / theme / "theme.css",
                          vault / ".obsidian" / "themes" / f"{theme}.css"):
            if candidate.is_file():
                sheets.append(candidate)
                break
    for name in appearance.get("enabledCssSnippets") or []:
        snippet = vault / ".obsidian" / "snippets" / f"{name}.css"
        if snippet.is_file():
            sheets.append(snippet)
    return sheets


# -- Markdown -> HTML ------------------------------------------------------------------------------

_INLINE_RE = re.compile(
    r"(?P<wiki>(?P<bang>!)?\[\[(?P<target>[^\]\|]*?)(?:\|(?P<alias>[^\]]*))?\]\])"
    r"|(?P<mark>==(?P<marked>[^=\n]+?)==)"
    r"|(?P<tag>(?<![\w/&#])#(?P<tagname>[^\s\d#.,;:!?()\[\]{}'\"`][^\s#.,;:!?()\[\]{}'\"`]*))"
)
# Adresses web ecrites en clair (Obsidian en fait des liens), hors des liens existants.
_URL_RE = re.compile(r"(?P<url>(?:https?|ftp)://[^\s<>\"'\[\]]*[^\s<>\"'\[\].,;:!?)])")
_CALLOUT_RE = re.compile(r"^\[!(?P<type>[^\]\s]+)\](?P<fold>[+-]?)[ \t]*(?P<title>[^\n]*)\n?")
_COMMENT_RE = re.compile(r"%%.*?%%", re.S)


class _Resolver:
    """Trouve le fichier vise par un [[lien]] : chemin relatif a la note, puis au coffre, puis
    par nom n'importe ou dans le coffre (index construit une fois par rendu)."""

    def __init__(self, note: Path, vault: Path | None):
        self.note, self.vault = note, vault
        self._index = None

    def find(self, target: str) -> Path | None:
        target = target.strip().replace("\\", "/")
        if not target:
            return self.note
        names = [target] if Path(target).suffix else [target + ".md", target]
        for base in filter(None, (self.note.parent, self.vault)):
            for name in names:
                candidate = base / name
                if candidate.is_file():
                    return candidate
        if self.vault is None:
            return None
        if self._index is None:
            self._index = {}
            for root, dirs, files in os.walk(self.vault):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for file_name in files:
                    self._index.setdefault(file_name.casefold(), Path(root) / file_name)
        for name in names:
            found = self._index.get(Path(name).name.casefold())
            if found is not None:
                return found
        return None


def _file_url(path: Path) -> str:
    return path.resolve().as_uri()


def _make_parser():
    from markdown_it import MarkdownIt
    from mdit_py_plugins.footnote import footnote_plugin
    from mdit_py_plugins.front_matter import front_matter_plugin
    from mdit_py_plugins.tasklists import tasklists_plugin

    md = MarkdownIt("commonmark", {"html": True, "breaks": True}).enable(["table", "strikethrough"])
    md.use(front_matter_plugin).use(footnote_plugin).use(tasklists_plugin)

    def callouts(state):
        """> [!type] titre : le blockquote devient un callout (balisage d'Obsidian)."""
        stack = []
        tokens = state.tokens
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token.type == "blockquote_open":
                inline = tokens[i + 2] if i + 2 < len(tokens) and tokens[i + 1].type == "paragraph_open" else None
                match = _CALLOUT_RE.match(inline.content) if inline is not None and inline.type == "inline" else None
                if match:
                    token.meta = {"callout": match.group("type").lower(), "fold": match.group("fold"),
                                  "title": match.group("title").strip()}
                    inline.content = inline.content[match.end():]
                    if not inline.content.strip():
                        del tokens[i + 1:i + 4]          # paragraphe qui ne portait que le titre
                stack.append(bool(match))
            elif token.type == "blockquote_close" and stack:
                if stack.pop():
                    token.meta = {"callout": True}
            i += 1

    md.core.ruler.before("inline", "obsidian_callouts", callouts)

    def render_blockquote_open(renderer, tokens, idx, options, env):
        meta = tokens[idx].meta or {}
        if not meta.get("callout"):
            return "<blockquote>\n"
        kind, fold = meta["callout"], meta["fold"]
        title = md.renderInline(meta["title"]) if meta["title"] else html.escape(kind.capitalize())
        classes = "callout" + (" is-collapsible" if fold else "") + (" is-collapsed" if fold == "-" else "")
        return (f'<div data-callout-metadata="" data-callout-fold="{fold}" data-callout="{html.escape(kind)}" '
                f'class="{classes}"><div class="callout-title"><div class="callout-icon"></div>'
                f'<div class="callout-title-inner">{title}</div></div><div class="callout-content">\n')

    def render_blockquote_close(renderer, tokens, idx, options, env):
        return "</div></div>\n" if (tokens[idx].meta or {}).get("callout") else "</blockquote>\n"

    md.add_render_rule("blockquote_open", render_blockquote_open)
    md.add_render_rule("blockquote_close", render_blockquote_close)
    return md


def _obsidian_inline(md, resolver: _Resolver):
    """[[liens]], ![[integrations]], ==surlignage== et #tags dans le texte (jamais dans le code)."""
    from markdown_it.token import Token

    def replace(match) -> str:
        if match.group("wiki"):
            raw_target = match.group("target") or ""
            target, _, anchor = raw_target.partition("#")
            alias = match.group("alias")
            found = resolver.find(target)
            if match.group("bang") and found is not None and found.suffix.lower() in IMAGE_EMBED_EXTENSIONS:
                size = ""
                if alias and re.fullmatch(r"\d+(x\d+)?", alias.strip()):
                    width, _, height = alias.strip().partition("x")
                    size = f' width="{width}"' + (f' height="{height}"' if height else "")
                return (f'<span class="internal-embed media-embed image-embed is-loaded" src="{html.escape(raw_target)}">'
                        f'<img src="{_file_url(found)}"{size} alt="{html.escape(found.name)}"></span>')
            label = alias or (Path(target).stem if target else "") + (f" > {anchor}" if anchor else "")
            classes = "internal-link" + ("" if found is not None else " is-unresolved")
            href = _file_url(found) if found is not None else "#"
            return (f'<a data-href="{html.escape(raw_target)}" href="{html.escape(href)}" class="{classes}">'
                    f"{html.escape(label or raw_target)}</a>")
        if match.group("mark"):
            return f"<mark>{html.escape(match.group('marked'))}</mark>"
        tag = match.group("tagname")
        return f'<a href="#{html.escape(tag)}" class="tag">#{html.escape(tag)}</a>'

    def split(content: str, in_link: bool) -> list:
        """Morceaux (debut, fin, html) a remplacer dans `content`, sans chevauchement."""
        spans = [(m.start(), m.end(), replace(m)) for m in _INLINE_RE.finditer(content)]
        if not in_link:
            for m in _URL_RE.finditer(content):
                if not any(a < m.end() and m.start() < b for a, b, _ in spans):
                    url = html.escape(m.group("url"))
                    spans.append((m.start(), m.end(),
                                  f'<a class="external-link" href="{url}" target="_blank">{url}</a>'))
        return sorted(spans)

    def rule(state):
        for token in state.tokens:
            if token.type != "inline" or not token.children:
                continue
            children = []
            in_link = 0
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
                    html_token = Token("html_inline", "", 0)
                    html_token.content = markup
                    children.append(html_token)
                    pos = end
                if pos < len(child.content):
                    text = Token("text", "", 0)
                    text.content = child.content[pos:]
                    children.append(text)
            token.children = children

    md.core.ruler.after("inline", "obsidian_inline", rule)


def _properties_html(front_matter: str) -> str:
    """Proprietes (front-matter YAML simple : « cle: valeur » et listes « - element »)."""
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
    body = "".join(
        f'<div class="metadata-property" data-property-key="{html.escape(k)}">'
        f'<div class="metadata-property-key"><span class="metadata-property-key-input">{html.escape(k)}</span></div>'
        f'<div class="metadata-property-value">{html.escape(", ".join(v))}</div></div>'
        for k, v in rows)
    return ('<div class="metadata-container"><div class="metadata-properties-heading">'
            '<div class="metadata-properties-title">Propriétés</div></div>'
            f'<div class="metadata-content"><div class="metadata-properties">{body}</div></div></div>')


def _blocks_html(md, tokens, env) -> str:
    """Chaque bloc de premier niveau dans son <div class="el-…">, comme le mode lecture."""
    out, i = [], 0
    while i < len(tokens):
        token = tokens[i]
        if token.type == "front_matter":
            i += 1
            continue
        j = i
        if token.nesting == 1:
            depth = 0
            while j < len(tokens):
                depth += tokens[j].nesting
                if depth == 0:
                    break
                j += 1
        tag = token.tag or token.type.split("_")[0]
        if token.type == "fence" or token.type == "code_block":
            tag = "pre"
        elif token.type.startswith("footnote"):
            tag = "section"
        chunk = md.renderer.render(tokens[i:j + 1], md.options, env)
        out.append(f'<div class="el-{html.escape(tag)}">{chunk}</div>')
        i = j + 1
    return "\n".join(out)


def render_page(note: Path, text: str | None = None) -> str:
    """Page HTML complete de la note `note` (contenu `text`, sinon lu sur le disque)."""
    if text is None:
        text = note.read_text(encoding="utf-8", errors="replace")
    text = _COMMENT_RE.sub("", text)
    vault = vault_for(note)
    appearance = _read_json(vault / ".obsidian" / "appearance.json") if vault else {}
    app_settings = _read_json(vault / ".obsidian" / "app.json") if vault else {}
    md = _make_parser()
    _obsidian_inline(md, _Resolver(note, vault))
    env: dict = {}
    tokens = md.parse(text, env)
    front = next((t.content for t in tokens if t.type == "front_matter"), "")
    blocks = _blocks_html(md, tokens, env)

    assets = obsidian_assets()
    links = []
    if assets is not None:
        links.append(f'<link rel="stylesheet" href="{_file_url(assets / "app.css")}">')
    links += [f'<link rel="stylesheet" href="{_file_url(sheet)}">' for sheet in vault_stylesheets(vault, appearance)]
    prism = assets / "lib" / "prism.min.js" if assets is not None else None
    script = f'<script src="{_file_url(prism)}"></script>' if prism is not None and prism.is_file() else ""
    classes, style = _body(appearance, app_settings)
    readable = " is-readable-line-width" if app_settings.get("readableLineLength", True) else ""
    title = html.escape(note.stem)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
{chr(10).join(links)}
<style>
/* Page autonome : la note defile dans la page, plus dans l'espace de travail d'Obsidian. */
/* Le DOCUMENT defile (html) : un body en overflow:auto se retrouvait a 0 px de haut et
   decoupait toute la note. */
html {{ height: auto !important; overflow: auto !important; background-color: var(--background-primary); }}
body {{ height: auto !important; min-height: 100%; overflow: visible !important; contain: none !important;
  background-color: var(--background-primary); }}
.app-container, .workspace-leaf-content, .view-content, .markdown-reading-view, .markdown-preview-view {{
  height: auto !important; overflow: visible !important; }}
.markdown-preview-view {{ user-select: text; }}
</style>
{script}
</head>
<body class="{classes}" style="{style}">
<div class="app-container"><div class="workspace-leaf-content" data-type="markdown" data-mode="preview">
<div class="view-content"><div class="markdown-reading-view">
<div class="markdown-preview-view markdown-rendered node-insert-event allow-fold-headings show-indentation-guide show-properties{readable}">
<div class="markdown-preview-sizer markdown-preview-section">
<div class="mod-header"><div class="inline-title">{title}</div>{_properties_html(front)}</div>
{blocks}
</div></div></div></div></div></div>
</body></html>"""


# -- Edition depuis l'inspecteur : lecture / ecriture fideles du fichier ----------------------------

def read_note(path: Path) -> tuple[str, dict]:
    """(texte a fins de ligne « \n », infos pour le reecrire a l'identique : encodage, BOM, fins
    de ligne, date de modification lue)."""
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
    """Reecrit la note avec l'encodage, la BOM et les fins de ligne d'origine ; fichier temporaire
    puis remplacement : jamais de note a moitie ecrite. Met a jour info["mtime_ns"]."""
    data = text.replace("\n", info.get("newline", "\n")).encode(info.get("encoding", "utf-8"), errors="replace")
    if info.get("bom"):
        data = b"\xef\xbb\xbf" + data
    temporary = path.with_name(f".{path.name}.pipeline-edit.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    info["mtime_ns"] = path.stat().st_mtime_ns
