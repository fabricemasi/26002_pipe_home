/* Module Markdown : barre d'outils reprise du plugin Obsidian « Editing Toolbar » (meme ergonomie, memes commandes).

   Ses commandes, icones et couleurs viennent de fm_markdown/toolbar.json (instantane AUTONOME de la configuration de
   l'utilisateur : plus rien n'est lu dans Obsidian). Les BOUTONS sont une barre flottante de fm_theme cote Qt
   (fm_markdown/bars.py, aspect = section « Barres d'outils » de fm_theme) qui envoie les commandes (message
   « command ») ; ici : les commandes et la place prise par les barres clipsees.
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

  class Toolbar {
    // Les BOUTONS sont une barre flottante de fm_theme, cote Qt (fm_markdown/bars.py) : la page garde les commandes
    // (`run`), les couleurs actives et la place que les barres clipsees prennent sur les bords (`setInsets`).
    constructor() {
      this.data = null;
      this.brush = null;
      this.fontColor = null;
      this.backgroundColor = null;
      this.insets = { top: 0, left: 0, right: 0, bottom: 0 };
      this._insetKey = "";
    }

    get cm() { return MD.editor && ((MD.editor.lp && MD.editor.lp.activeCell()) || MD.editor.cm); }   // cellule de tableau active : elle

    configure(data) {
      this.data = data || {};
      this.fontColor = this.data.fontColor || "#D83931";
      this.backgroundColor = this.data.backgroundColor || "#FFB78B8C";
    }

    setColors(colors) {
      if (colors && colors.fontColor) this.fontColor = colors.fontColor;
      if (colors && colors.backgroundColor) this.backgroundColor = colors.backgroundColor;
    }

    setInsets(insets) {
      this.insets = Object.assign({ top: 0, left: 0, right: 0, bottom: 0 }, insets || {});
      this.sync();
    }

    // Place prise par les barres clipsees (px CSS) : la page de l'editeur et de la lecture commence apres elles.
    sync() {
      const i = this.insets;
      const key = [i.top, i.left, i.right, i.bottom].join(",");
      if (key === this._insetKey) return;
      this._insetKey = key;
      const root = document.documentElement.style;
      root.setProperty("--md-toolbar-height", (i.top || 0) + "px");
      root.setProperty("--md-bars-left", (i.left || 0) + "px");
      root.setProperty("--md-bars-right", (i.right || 0) + "px");
      root.setProperty("--md-bars-bottom", (i.bottom || 0) + "px");
      if (MD.editor) MD.editor.cm.setSize(null, null);
    }

    setActive(id, active) {
      if (MD.call) MD.call("toolActive", id, !!active).catch(() => {});
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
      const brushId = "editing-toolbar:toggle-format-brush";
      if (this.brush) {
        this.brush = null;
        this.setActive(brushId, false);
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
      this.setActive(brushId, true);
      cm.getWrapperElement().addEventListener("mouseup", () => {
        setTimeout(() => {
          if (!this.brush || !cm.somethingSelected()) return;
          cm.operation(() => { for (const [o, c] of this.brush) this.toggleWrap(cm, o, c); });
          this.brush = null;
          this.setActive(brushId, false);
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
