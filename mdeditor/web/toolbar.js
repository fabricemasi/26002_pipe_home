/* Module Markdown : barre d'outils reprise du plugin Obsidian « Editing Toolbar » (meme ergonomie, memes commandes).

   Ses commandes, icones et couleurs viennent de mdeditor/toolbar.json (instantane AUTONOME de la configuration de
   l'utilisateur : plus rien n'est lu dans Obsidian) ; son habillage, des reglages (Markdown > Barre d'outils).
   Sous-menus au survol ; menus deroulants et palettes de couleurs = menus contextuels de l'appli (pont « menu »).
   Chaque commande agit sur la selection ou le curseur, dans l'historique d'annulation, avec la syntaxe du plugin
   (<u>, <center>, <p align>, <font color>, <mark style="background:…">…). */
(function () {
  "use strict";
  const MD = window.MD = window.MD || {};

  const WRAPS = {
    "toggle-bold": ["**", "**"], "toggle-italics": ["*", "*"], "toggle-strikethrough": ["~~", "~~"],
    "toggle-highlight": ["==", "=="], "underline": ["<u>", "</u>"], "superscript": ["<sup>", "</sup>"],
    "subscript": ["<sub>", "</sub>"], "editor:toggle-code": ["`", "`"],
    "justify": ['<p align="justify">', "</p>"], "left": ['<p align="left">', "</p>"],
    "right": ['<p align="right">', "</p>"], "center": ["<center>", "</center>"],
    "editor:toggle-comments": ["%%", "%%"]
  };

  const NAMES_FR = {
    "Undo Edit": "Annuler", "Redo Edit": "Rétablir", "Format Brush": "Pinceau de format",
    "Clear Text Formatting": "Effacer la mise en forme", "Bold": "Gras", "Italic": "Italique",
    "Strikethrough": "Barré", "Underline": "Souligné", "Highlight": "Surligner", "Header 1": "Titre 1",
    "Header 2": "Titre 2", "Header 3": "Titre 3", "Header 4": "Titre 4", "Header 5": "Titre 5", "Header 6": "Titre 6",
    "submenu": "Titres", "Text Tools": "Outils de texte", "Get Plain Text": "Texte brut",
    "Full Half Converter": "Pleine / demi-chasse", "Line Operations": "Lignes", "Text Processing": "Texte",
    "Advanced Tools": "Avancé", "Insert Blank Lines": "Insérer des lignes vides",
    "Remove Blank Lines": "Retirer les lignes vides", "Split Lines": "Couper les lignes",
    "Merge Lines": "Fusionner les lignes", "Dedupe Lines": "Dédoublonner les lignes",
    "Add Prefix/Suffix": "Préfixe / suffixe", "Number Lines (Custom)": "Numéroter les lignes",
    "Trim Line Ends": "Rogner les fins de ligne", "Shrink Extra Spaces": "Compresser les espaces",
    "Remove All Whitespace": "Retirer tous les espaces", "List to Table": "Liste vers tableau",
    "Table to List": "Tableau vers liste", "Extract Between Strings": "Extraire entre deux chaînes",
    "Cut": "Couper", "Copy": "Copier", "Paste": "Coller", "Swap Line Down": "Descendre la ligne",
    "Swap Line Up": "Monter la ligne", "Attach File": "Joindre un fichier", "Insert Table": "Insérer un tableau",
    "Cycle List and Checklist": "Liste / case à cocher", "Blockquote": "Citation", "Callout": "Callout",
    "Superscript": "Exposant", "Subscript": "Indice", "Inline Code": "Code en ligne", "Code Block": "Bloc de code",
    "Wikilink": "Lien interne", "Embed": "Intégration", "Link": "Lien", "Horizontal Divider": "Séparateur",
    "Checklist": "Cocher / décocher", "Renumber Ordered List": "Renuméroter", "Ordered List": "Liste numérotée",
    "Unordered List": "Liste à puces", "Unindent List": "Désindenter", "Indent list": "Indenter",
    "Justify Text": "Justifier", "Align Text Left": "Gauche", "Center Text": "Centrer", "Align Text Right": "Droite",
    "Change Font Color": "Couleur du texte",
    "Change Background Color": "Couleur de fond"
  };
  const DIVIDER = "editingToolbar-Divider-Line";

  class Toolbar {
    constructor(host) {
      this.host = host;
      this.data = null;
      this.brush = null;
      this.fontColor = null;
      this.backgroundColor = null;
      this.colorButtons = {};
    }

    get cm() { return MD.editor && ((MD.editor.lp && MD.editor.lp.activeCell()) || MD.editor.cm); }   // cellule de tableau active : elle

    configure(data) {
      this.data = data || { commands: [] };
      this.fontColor = this.data.fontColor || "#D83931";
      this.backgroundColor = this.data.backgroundColor || "#FFB78B8C";
      this.colorButtons = {};
      this.build();
      this.syncColorIcons();
    }

    label(item) {
      const name = (item.name || item.id || "").trim();
      return NAMES_FR[name] || name;
    }

    iconHtml(item) {
      if (item.icon && /^\s*<svg/.test(item.icon)) return item.icon;
      const m = /header(\d)-text/.exec(item.id || "");
      return m ? '<span style="font:600 12px var(--md-text-font)">H' + m[1] + "</span>" : MD.escapeHtml(this.label(item).slice(0, 2));
    }

    button(item) {
      const b = document.createElement("button");
      b.className = "md-tool";
      b.title = this.label(item);
      b.innerHTML = this.iconHtml(item);
      b.dataset.command = item.id;
      b.addEventListener("mousedown", (ev) => ev.preventDefault());
      return b;
    }

    build() {
      const frag = document.createDocumentFragment();
      const items = [...(this.data.commands || [])];
      // H1 doit etre directement disponible et place juste avant H2.
      const headings = items.find((item) => item && item.SubmenuCommands);
      const h1 = items.find((item) => item && item.id === "editing-toolbar:header1-text") ||
        (headings && headings.SubmenuCommands.find((item) => item.id === "editing-toolbar:header1-text"));
      if (h1) {
        const oldIndex = items.findIndex((item) => item && item.id === h1.id);
        if (oldIndex >= 0) items.splice(oldIndex, 1);
        const h2Index = items.findIndex((item) => item && item.id === "editing-toolbar:header2-text");
        items.splice(h2Index >= 0 ? h2Index : items.length, 0, h1);
      }
      for (const item of items) {
        if (item.id === DIVIDER) {
          const sep = document.createElement("span");
          sep.className = "md-sep";
          frag.appendChild(sep);
          continue;
        }
        const b = this.button(item);
        if (/change-(font|background)-color$/.test(item.id)) {
          const font = item.id.indexOf("font") >= 0;
          const group = document.createElement("div");
          group.className = "md-color-split";
          group.title = this.label(item);
          b.classList.add("md-color-main");
          b.addEventListener("click", () => this.run(item.id));
          const caret = document.createElement("button");
          caret.type = "button";
          caret.className = "md-color-caret";
          caret.title = font ? "Choisir la couleur du texte" : "Choisir la couleur de fond";
          caret.setAttribute("aria-label", caret.title);
          caret.addEventListener("mousedown", (ev) => ev.preventDefault());
          caret.addEventListener("click", (ev) => {
            ev.preventDefault(); ev.stopPropagation(); this.colorMenu(item.id, caret);
          });
          group.append(b, caret);
          this.colorButtons[item.id] = b;
          frag.appendChild(group);
          continue;
        }
        if (item.SubmenuCommands) {
          if (item.menuType === "dropdown") {
            b.insertAdjacentHTML("beforeend", '<span class="md-caret"></span>');
            b.addEventListener("click", (ev) => this.dropdown(item, ev.currentTarget));
          } else {
            const sub = document.createElement("div");
            sub.className = "md-sub";
            for (const child of item.SubmenuCommands) {
              if (child.id === DIVIDER) continue;
              const c = this.button(child);
              c.addEventListener("click", (ev) => { ev.stopPropagation(); this.run(child.id); });
              sub.appendChild(c);
            }
            b.appendChild(sub);
          }
        } else {
          b.addEventListener("click", () => this.run(item.id));
        }
        frag.appendChild(b);
      }
      this.host.replaceChildren(frag);
    }

    syncColorIcons() {
      const values = {
        "editing-toolbar:change-font-color": this.fontColor,
        "editing-toolbar:change-background-color": this.backgroundColor
      };
      for (const [id, color] of Object.entries(values)) {
        const iconId = id.indexOf("font") >= 0 ? "change-font-color-icon" : "change-background-color-icon";
        const path = this.colorButtons[id]?.querySelector("svg #" + iconId);
        if (path) {
          const rgba = /^#([0-9a-f]{2})([0-9a-f]{6})$/i.exec(color || "");
          path.style.fill = rgba
            ? `rgba(${parseInt(rgba[2].slice(0, 2), 16)}, ${parseInt(rgba[2].slice(2, 4), 16)}, ${parseInt(rgba[2].slice(4, 6), 16)}, ${parseInt(rgba[1], 16) / 255})`
            : color;
        }
      }
    }

    async dropdown(item, anchor) {
      const entries = [], ids = [];
      for (const child of item.SubmenuCommands) {
        if (child.id === DIVIDER) { entries.push({ section: this.label(child) }); continue; }
        entries.push({ title: this.label(child), svg: /^\s*<svg/.test(child.icon || "") ? child.icon : null });
        ids.push(child.id);
      }
      anchor.classList.add("is-open");
      const r = anchor.getBoundingClientRect();
      const index = await MD.menu(entries, r.left, r.bottom + 2).finally(() => anchor.classList.remove("is-open"));
      if (index >= 0 && ids[index]) this.run(ids[index]);
    }

    async colorMenu(id, anchor) {
      const font = id.indexOf("font") >= 0;
      const key = font ? "fontColor" : "backgroundColor";
      try {
        const color = await MD.call("pickColor", this[key], font ? "Couleur du texte" : "Couleur de fond");
        if (!color) return;
        this[key] = color;
        this.syncColorIcons();
        MD.call("saveToolbarColors", { fontColor: this.fontColor, backgroundColor: this.backgroundColor })
          .catch(() => {});
        this.run(id);
      } catch (err) { MD.notice(err.message); }
    }

    visible() {
      const s = MD.state;
      return !!(s.options && s.options.toolbar && s.current && s.current.kind === "markdown" && s.mode === "edit");
    }

    sync() {
      const shown = this.visible();
      this.host.classList.toggle("is-shown", shown);
      const rect = shown ? this.host.getBoundingClientRect() : null;
      const css = shown ? getComputedStyle(this.host) : null;
      const height = shown ? rect.height + (parseFloat(css.marginTop) || 0) + (parseFloat(css.marginBottom) || 0) : 0;
      if (height !== this._height) {
        this._height = height;
        document.documentElement.style.setProperty("--md-toolbar-height", height + "px");
        if (MD.editor) MD.editor.cm.setSize(null, null);
      }
    }

    // -- commandes ------------------------------------------------------------------------------------------------
    run(id) {
      const cm = this.cm;
      if (!cm || !MD.state.current || MD.state.current.kind !== "markdown" || MD.state.mode !== "edit") return;
      const short = id.replace(/^editing-toolbar:/, "");
      cm.focus();
      try {
        cm.operation(() => this.exec(short, cm));
      } catch (err) {
        MD.notice("Commande « " + short + " » : " + err.message);
      }
    }

    exec(cmd, cm) {
      if (WRAPS[cmd]) { this.toggleWrap(cm, WRAPS[cmd][0], WRAPS[cmd][1]); return; }
      const m = /^header(\d)-text$/.exec(cmd);
      if (m) { this.heading(cm, Number(m[1])); return; }
      switch (cmd) {
        case "editor-undo": cm.undo(); return;
        case "editor-redo": cm.redo(); return;
        case "format-eraser": this.eraseFormat(cm); return;
        case "toggle-format-brush": this.formatBrush(cm); return;
        case "change-font-color": this.color(cm, true); return;
        case "change-background-color": this.color(cm, false); return;
        case "editor:insert-wikilink": this.insertAround(cm, "[[", "]]"); return;
        case "editor:insert-embed": this.insertAround(cm, "![[", "]]"); return;
        case "insert-link": this.insertLink(cm); return;
        case "hrline": this.insertBlock(cm, "---"); return;
        case "codeblock": this.wrapBlock(cm, "```", "```"); return;
        case "editor:insert-table": this.insertBlock(cm, "| Colonne 1 | Colonne 2 | Colonne 3 |\n| --- | --- | --- |\n|  |  |  |"); return;
        case "insert-callout": this.callout(cm); return;
        case "editor:toggle-blockquote": this.togglePrefix(cm, /^>\s?/, "> "); return;
        case "toggle-bullet-list": case "editor:toggle-bullet-list": this.toggleList(cm, "bullet"); return;
        case "toggle-numbered-list": case "editor:toggle-numbered-list": this.toggleList(cm, "number"); return;
        case "editor:toggle-checklist-status": this.toggleChecked(cm); return;
        case "editor:cycle-list-checklist": this.cycleList(cm); return;
        case "renumber-ordered-list": this.renumber(cm); return;
        case "indent-list": MD.editor.indent(cm, false); return;
        case "undent-list": MD.editor.indent(cm, true); return;
        case "editor:swap-line-down": cm.execCommand("swapLineDown"); return;
        case "editor:swap-line-up": cm.execCommand("swapLineUp"); return;
        case "editor-cut": document.execCommand("cut"); return;
        case "editor-copy": document.execCommand("copy"); return;
        case "editor-paste": MD.call("clipboardText").then((t) => { if (t != null) cm.replaceSelection(t); }); return;
        case "editor:attach-file":
          MD.call("attachFile", MD.state.current.path).then((r) => { if (r && r.length) cm.replaceSelection(r.join("\n")); })
            .catch((err) => MD.notice(err.message));
          return;
        case "get-plain-text": this.mapSelection(cm, (t) => stripMarkdown(t)); return;
        case "smart-symbols": this.mapSelection(cm, (t) => fullHalf(t)); return;
        case "insert-blank-lines": this.mapLines(cm, (lines) => lines.flatMap((l, i) => i < lines.length - 1 ? [l, ""] : [l])); return;
        case "remove-blank-lines": this.mapLines(cm, (lines) => lines.filter((l) => l.trim())); return;
        case "split-lines":
          MD.prompt("Couper les lignes au séparateur", ",", (sep) => {
            if (sep) cm.operation(() => this.mapLines(cm, (lines) => lines.flatMap((l) => l.split(sep).map((p) => p.trim()))));
          });
          return;
        case "merge-lines":
          MD.prompt("Fusionner les lignes avec", " ", (sep) => {
            cm.operation(() => this.mapLines(cm, (lines) => [lines.map((l) => l.trim()).filter(Boolean).join(sep == null ? " " : sep)]));
          });
          return;
        case "dedupe-lines": this.mapLines(cm, (lines) => lines.filter((l, i) => !l.trim() || lines.indexOf(l) === i)); return;
        case "add-wrap":
          MD.prompt("Encadrer : préfixe|suffixe", "**|**", (spec) => {
            if (!spec) return;
            const [a, b] = spec.split("|");
            cm.operation(() => this.mapLines(cm, (lines) => lines.map((l) => l.trim() ? a + l + (b === undefined ? a : b) : l)));
          });
          return;
        case "number-lines": { let n = 0; this.mapLines(cm, (lines) => lines.map((l) => l.trim() ? (++n) + ". " + l : l)); return; }
        case "remove-whitespace-trim": this.mapLines(cm, (lines) => lines.map((l) => l.trim())); return;
        case "remove-whitespace-compress": this.mapLines(cm, (lines) => lines.map((l) => l.replace(/[ \t]{2,}/g, " ").trim())); return;
        case "remove-whitespace-all": this.mapSelection(cm, (t) => t.replace(/[ \t]+/g, "")); return;
        case "list-to-table": this.listToTable(cm); return;
        case "table-to-list": this.tableToList(cm); return;
        case "extract-between":
          MD.prompt("Extraire entre : début|fin", "(|)", (spec) => {
            if (!spec) return;
            const [a, b] = spec.split("|");
            cm.operation(() => this.mapSelection(cm, (t) => {
              const out = [];
              let at = 0;
              for (;;) {
                const s = t.indexOf(a, at); if (s < 0) break;
                const e = t.indexOf(b, s + a.length); if (e < 0) break;
                out.push(t.slice(s + a.length, e)); at = e + b.length;
              }
              return out.join("\n");
            }));
          });
          return;
        default:
          MD.notice("Commande non prise en charge : " + cmd);
      }
    }

    selectionOrWord(cm) {
      if (cm.somethingSelected()) return null;
      const cur = cm.getCursor();
      const line = cm.getLine(cur.line);
      let a = cur.ch, b = cur.ch;
      while (a > 0 && /[\wÀ-ɏ'-]/.test(line.charAt(a - 1))) a--;
      while (b < line.length && /[\wÀ-ɏ'-]/.test(line.charAt(b))) b++;
      return a < b ? { from: { line: cur.line, ch: a }, to: { line: cur.line, ch: b } } : null;
    }

    toggleWrap(cm, open, close) {
      const word = this.selectionOrWord(cm);
      if (word) cm.setSelection(word.from, word.to);
      const out = cm.listSelections().map((r) => {
        const from = CodeMirror.cmpPos(r.anchor, r.head) <= 0 ? r.anchor : r.head;
        const to = from === r.anchor ? r.head : r.anchor;
        const text = cm.getRange(from, to);
        const before = cm.getRange({ line: from.line, ch: Math.max(0, from.ch - open.length) }, from);
        const after = cm.getRange(to, { line: to.line, ch: to.ch + close.length });
        if (before === open && after === close) {
          cm.replaceRange(text, { line: from.line, ch: from.ch - open.length }, { line: to.line, ch: to.ch + close.length }, "+toolbar");
          return { anchor: { line: from.line, ch: from.ch - open.length }, head: { line: to.line, ch: to.ch - (from.line === to.line ? open.length : 0) } };
        }
        if (text.startsWith(open) && text.endsWith(close) && text.length >= open.length + close.length) {
          const inner = text.slice(open.length, text.length - close.length);
          cm.replaceRange(inner, from, to, "+toolbar");
          return { anchor: from, head: cm.findPosH(from, inner.length, "char") };
        }
        cm.replaceRange(open + text + close, from, to, "+toolbar");
        const start = { line: from.line, ch: from.ch + open.length };
        return { anchor: start, head: cm.findPosH(start, text.length, "char") };
      });
      cm.setSelections(out);
    }

    insertAround(cm, open, close) {
      const text = cm.getSelection();
      cm.replaceSelection(open + text + close, "around");
      const cur = cm.getCursor("from");
      if (!text) cm.setCursor({ line: cur.line, ch: cur.ch + open.length });
      else cm.setSelection({ line: cur.line, ch: cur.ch + open.length }, { line: cur.line, ch: cur.ch + open.length + text.length });
    }

    insertLink(cm) {
      const text = cm.getSelection();
      if (/^https?:\/\//.test(text)) {
        cm.replaceSelection("[](" + text + ")");
        const c = cm.getCursor();
        cm.setCursor({ line: c.line, ch: c.ch - text.length - 3 });
        return;
      }
      cm.replaceSelection("[" + text + "]()");
      const c = cm.getCursor();
      cm.setCursor({ line: c.line, ch: c.ch - 1 });
    }

    heading(cm, level) {
      const lines = this.selectedLines(cm);
      const same = lines.every((i) => new RegExp("^#{" + level + "}\\s").test(cm.getLine(i)));
      for (const i of lines) {
        const text = cm.getLine(i);
        const stripped = text.replace(/^#{1,6}\s+/, "");
        cm.replaceRange(same ? stripped : "#".repeat(level) + " " + stripped, { line: i, ch: 0 }, { line: i, ch: text.length }, "+toolbar");
      }
    }

    selectedLines(cm) {
      const out = new Set();
      for (const r of cm.listSelections()) {
        const a = Math.min(r.anchor.line, r.head.line), b = Math.max(r.anchor.line, r.head.line);
        const endCh = r.anchor.line === b ? r.anchor.ch : r.head.ch;
        const end = b > a && endCh === 0 ? b - 1 : b;
        for (let i = a; i <= Math.max(a, end); i++) out.add(i);
      }
      return [...out].sort((x, y) => x - y);
    }

    togglePrefix(cm, re, prefix) {
      const lines = this.selectedLines(cm);
      const all = lines.every((i) => re.test(cm.getLine(i)));
      for (const i of lines) {
        const text = cm.getLine(i);
        cm.replaceRange(all ? text.replace(re, "") : prefix + text, { line: i, ch: 0 }, { line: i, ch: text.length }, "+toolbar");
      }
    }

    toggleList(cm, kind) {
      const lines = this.selectedLines(cm);
      const re = kind === "bullet" ? /^(\s*)[-*+]\s+(?!\[.\])/ : /^(\s*)\d+[.)]\s+/;
      const all = lines.every((i) => re.test(cm.getLine(i)));
      let n = 0;
      for (const i of lines) {
        const text = cm.getLine(i);
        let next;
        if (all) next = text.replace(re, "$1");
        else {
          const m = /^(\s*)(?:[-*+]\s+(?:\[.\]\s+)?|\d+[.)]\s+)?(.*)$/.exec(text);
          next = m[1] + (kind === "bullet" ? "- " : (++n) + ". ") + m[2];
        }
        cm.replaceRange(next, { line: i, ch: 0 }, { line: i, ch: text.length }, "+toolbar");
      }
    }

    cycleList(cm) {
      // texte -> puce -> case -> texte
      for (const i of this.selectedLines(cm)) {
        const text = cm.getLine(i);
        let next;
        const m = /^(\s*)([-*+]|\d+[.)])\s+(\[.\]\s+)?(.*)$/.exec(text);
        if (!m) { const lead = /^\s*/.exec(text)[0]; next = lead + "- " + text.slice(lead.length); }
        else if (!m[3]) next = m[1] + m[2] + " [ ] " + m[4];
        else next = m[1] + m[4];
        cm.replaceRange(next, { line: i, ch: 0 }, { line: i, ch: text.length }, "+toolbar");
      }
    }

    toggleChecked(cm) {
      for (const i of this.selectedLines(cm)) {
        const text = cm.getLine(i);
        const m = /^(\s*(?:[-*+]|\d+[.)])\s+\[)(.)\]/.exec(text);
        if (m) cm.replaceRange(m[2] === " " ? "x" : " ", { line: i, ch: m[1].length }, { line: i, ch: m[1].length + 1 }, "+toolbar");
      }
    }

    renumber(cm) {
      const cur = cm.getCursor().line;
      const isItem = (i) => /^\s*\d+[.)]\s/.test(cm.getLine(i) || "");
      if (!isItem(cur)) return;
      let a = cur, b = cur;
      while (a > 0 && isItem(a - 1)) a--;
      while (b < cm.lineCount() - 1 && isItem(b + 1)) b++;
      const counters = {};
      for (let i = a; i <= b; i++) {
        const m = /^(\s*)(\d+)([.)])/.exec(cm.getLine(i));
        const depth = m[1].length;
        Object.keys(counters).forEach((d) => { if (Number(d) > depth) delete counters[d]; });
        counters[depth] = (counters[depth] || 0) + 1;
        cm.replaceRange(m[1] + counters[depth] + m[3], { line: i, ch: 0 }, { line: i, ch: m[0].length }, "+toolbar");
      }
    }

    insertBlock(cm, text) {
      const cur = cm.getCursor();
      const line = cm.getLine(cur.line);
      const before = line.trim() ? "\n" : "";
      cm.replaceRange(before + text + "\n", { line: cur.line, ch: line.length }, null, "+toolbar");
      cm.setCursor({ line: cur.line + (before ? 1 : 0) + text.split("\n").length, ch: 0 });
    }

    wrapBlock(cm, open, close) {
      const text = cm.getSelection();
      const from = cm.getCursor("from");
      const pre = from.ch > 0 ? "\n" : "";
      cm.replaceSelection(pre + open + "\n" + text + "\n" + close + "\n", "start");
      cm.setCursor({ line: from.line + (pre ? 2 : 1), ch: 0 });
    }

    callout(cm) {
      const text = cm.getSelection();
      const body = text ? text.split("\n").map((l) => "> " + l).join("\n") : "> ";
      const from = cm.getCursor("from");
      cm.replaceSelection((from.ch > 0 ? "\n" : "") + "> [!note] \n" + body);
    }

    color(cm, font) {
      const value = font ? this.fontColor : this.backgroundColor;
      const word = this.selectionOrWord(cm);
      if (word) cm.setSelection(word.from, word.to);
      const text = cm.getSelection();
      cm.replaceSelection(font ? '<font color="' + value + '">' + text + "</font>"
        : '<mark style="background:' + value + '">' + text + "</mark>", "around");
    }

    stripColor(font) {
      const cm = this.cm;
      if (!cm) return;
      cm.operation(() => this.mapSelection(cm, (t) => font
        ? t.replace(/<font color="[^"]*">([\s\S]*?)<\/font>/g, "$1")
        : t.replace(/<(mark|span) style="background:[^"]*">([\s\S]*?)<\/\1>/g, "$2")));
    }

    eraseFormat(cm) {
      const word = this.selectionOrWord(cm);
      if (word) cm.setSelection(word.from, word.to);
      this.mapSelection(cm, (t) => stripInline(t));
    }

    formatBrush(cm) {
      const button = this.host.querySelector('[data-command="editing-toolbar:toggle-format-brush"]');
      if (this.brush) {
        this.brush = null;
        if (button) button.classList.remove("is-active");
        return;
      }
      // Les balises qui entourent la selection deviennent le format a appliquer a la prochaine selection.
      const text = cm.getSelection();
      const marks = [];
      for (const [open, close] of [["**", "**"], ["*", "*"], ["~~", "~~"], ["==", "=="], ["<u>", "</u>"], ["`", "`"]]) {
        const from = cm.getCursor("from"), to = cm.getCursor("to");
        const before = cm.getRange({ line: from.line, ch: Math.max(0, from.ch - open.length) }, from);
        const after = cm.getRange(to, { line: to.line, ch: to.ch + close.length });
        if ((before === open && after === close) || (text.startsWith(open) && text.endsWith(close))) marks.push([open, close]);
      }
      if (!marks.length) { MD.notice("Sélectionnez un texte mis en forme pour copier son format."); return; }
      this.brush = marks;
      if (button) button.classList.add("is-active");
      cm.getWrapperElement().addEventListener("mouseup", () => {
        setTimeout(() => {
          if (!this.brush || !cm.somethingSelected()) return;
          cm.operation(() => { for (const [o, c] of this.brush) this.toggleWrap(cm, o, c); });
          this.brush = null;
          if (button) button.classList.remove("is-active");
        }, 0);
      }, { once: true });
    }

    mapSelection(cm, fn) {
      if (!cm.somethingSelected()) {
        const line = cm.getCursor().line;
        cm.setSelection({ line, ch: 0 }, { line, ch: cm.getLine(line).length });
      }
      cm.replaceSelection(fn(cm.getSelection()), "around", "+toolbar");
    }

    mapLines(cm, fn) {
      if (!cm.somethingSelected()) cm.setSelection({ line: 0, ch: 0 }, { line: cm.lastLine(), ch: cm.getLine(cm.lastLine()).length });
      const from = cm.getCursor("from"), to = cm.getCursor("to");
      const start = { line: from.line, ch: 0 }, end = { line: to.line, ch: cm.getLine(to.line).length };
      cm.replaceRange(fn(cm.getRange(start, end).split("\n")).join("\n"), start, end, "+toolbar");
    }

    listToTable(cm) {
      this.mapLines(cm, (lines) => {
        const items = lines.map((l) => l.replace(/^\s*(?:[-*+]|\d+[.)])\s+/, "").trim()).filter(Boolean);
        const cells = items.map((l) => l.split(/\s*[,;|]\s*|\t/));
        const width = Math.max(1, ...cells.map((c) => c.length));
        const row = (c) => "| " + Array.from({ length: width }, (_, i) => c[i] || "").join(" | ") + " |";
        return [row(cells[0] || []), "|" + " --- |".repeat(width)].concat(cells.slice(1).map(row));
      });
    }

    tableToList(cm) {
      this.mapLines(cm, (lines) => lines.filter((l) => !/^\s*\|?\s*:?-+/.test(l))
        .map((l) => "- " + l.replace(/^\s*\||\|\s*$/g, "").split("|").map((c) => c.trim()).filter(Boolean).join(", ")));
    }
  }

  function stripInline(text) {
    return text.replace(/<font color="[^"]*">([\s\S]*?)<\/font>/g, "$1")
      .replace(/<(mark|span) style="[^"]*">([\s\S]*?)<\/\1>/g, "$2")
      .replace(/<\/?(u|sup|sub|center|p[^>]*|b|i|s)>/g, "")
      .replace(/(\*\*|__)(.+?)\1/g, "$2").replace(/(\*|_)(.+?)\1/g, "$2")
      .replace(/~~(.+?)~~/g, "$1").replace(/==(.+?)==/g, "$1").replace(/`([^`]+)`/g, "$1");
  }

  function stripMarkdown(text) {
    return stripInline(text).replace(/^\s{0,3}#{1,6}\s+/gm, "").replace(/^\s*>\s?/gm, "")
      .replace(/^\s*(?:[-*+]|\d+[.)])\s+(?:\[.\]\s+)?/gm, "")
      .replace(/!?\[\[([^\]|]*)\|?([^\]]*)\]\]/g, (a, t, alias) => alias || t)
      .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1");
  }

  function fullHalf(text) {
    // Pleine chasse <-> demi-chasse (sens choisi d'apres le premier caractere convertible).
    const toHalf = /[！-～　]/.test(text);
    return text.replace(toHalf ? /[！-～　]/g : /[!-~ ]/g, (c) => {
      const code = c.charCodeAt(0);
      if (toHalf) return code === 0x3000 ? " " : String.fromCharCode(code - 0xFEE0);
      return code === 0x20 ? "　" : String.fromCharCode(code + 0xFEE0);
    });
  }

  MD.Toolbar = Toolbar;
})();
