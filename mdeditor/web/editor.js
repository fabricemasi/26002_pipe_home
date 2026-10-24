/* Module Markdown : l'editeur (CodeMirror 5).

   1. Mode « pfm » : le mode markdown de CodeMirror + la syntaxe courante des notes (front-matter, [[liens]],
      ![[images]], #tags, %%commentaires%%, adresses en clair) + des CLASSES DE LIGNE (md-h1…md-h6, md-quote,
      md-codeblock, md-list-line…) : la feuille du module habille l'edition comme la lecture.
   2. Edition visuelle (LivePreview) : les balises (#, **, [[ ]], `…`) sont masquees hors de l'element que touche le
      curseur ; puces, cases a cocher, liens, images et filets sont dessines ; tableaux et callouts remplaces par leur
      rendu tant que le curseur n'y est pas. Seules les lignes VISIBLES sont traitees, et seules celles qui ont change
      (texte, curseur) sont refaites ; l'etat suit chaque document (revenir sur une note ne refait rien).
   3. Editor : une instance CodeMirror, un document par fichier ouvert (garde avec son historique d'annulation). */
(function () {
  "use strict";
  const MD = window.MD = window.MD || {};
  MD.IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "bmp", "svg", "webp", "avif"]);

  // -- 1. Mode ------------------------------------------------------------------------------------------------------
  const TAG_RE = /^#[^\s#.,;:!?()\[\]{}'"`<>=+*&^%$@|\\\/~]+/;
  const URL_RE = /^(?:https?|ftp):\/\/[^\s<>"'\[\]()]*[^\s<>"'\[\]().,;:!?]/;

  // Jetons d'Obsidian (CodeMirror 6) pour nos syntaxes ajoutees : liens internes, tags, commentaires %%.
  const TOKEN_ALIASES = { "md-wikilink": "hmd-internal-link", "md-tag": "hashtag", "md-comment": "comment" };
  const ALIAS_RE = /\bmd-(?:wikilink|tag|comment)\b/g, HAS_ALIAS = /\bmd-(?:wikilink|tag|comment)\b/;
  const alias = (style) => style && HAS_ALIAS.test(style) ?
    style.replace(ALIAS_RE, (m) => m + " " + TOKEN_ALIASES[m]) : style;

  CodeMirror.defineMode("pfm", function (config, modeCfg) {
    const md = CodeMirror.getMode(config, {
      name: "markdown", highlightFormatting: true, taskLists: true, strikethrough: true, highlight: true,
      fencedCodeBlockHighlighting: true, xml: !!(modeCfg && modeCfg.xml),   // HTML colore : cellules de tableau
      tokenTypeOverrides: { code: "inline-code", list1: "list-1", list2: "list-2", list3: "list-3" }
    });
    const yaml = CodeMirror.getMode(config, "yaml");
    // `code` compte aussi les accents graves du code en ligne : il ne suffit pas a identifier un bloc.
    const inFence = (s) => !!(s.md.fencedEndRE || s.md.localMode);

    function lineClasses(stream, s, style) {
      // Nos classes (md-…) et celles d'Obsidian (HyperMD-…, memes roles) : une feuille d'Obsidian s'applique ici.
      const out = [];
      const st = s.md;
      if (st.header) out.push("line-md-h" + st.header, "line-HyperMD-header", "line-HyperMD-header-" + st.header);
      if (st.quote) out.push("line-md-quote", "line-HyperMD-quote", "line-HyperMD-quote-" + Math.min(st.quote, 6));
      if (st.list !== false && st.listStack && st.listStack.length) {
        out.push("line-md-list-line", "line-HyperMD-list-line", "line-HyperMD-list-line-" + st.listStack.length);
      }
      if (style && /formatting-code-block/.test(style)) {
        const edge = st.fencedEndRE ? "begin" : "end";
        out.push("line-md-codeblock", "line-md-codeblock-" + edge, "line-HyperMD-codeblock", "line-HyperMD-codeblock-bg",
          "line-HyperMD-codeblock-" + edge, "line-HyperMD-codeblock-" + edge + "-bg");
      } else if (inFence(s)) {
        out.push("line-md-codeblock", "line-HyperMD-codeblock", "line-HyperMD-codeblock-bg");
      }
      return out.join(" ");
    }

    return {
      startState() {
        return { md: CodeMirror.startState(md), yaml: CodeMirror.startState(yaml), first: true, fm: 0, wiki: 0,
          embed: false, comment: false, tagRest: 0 };
      },
      copyState(s) {
        return { md: CodeMirror.copyState(md, s.md), yaml: CodeMirror.copyState(yaml, s.yaml), first: s.first,
          fm: s.fm, wiki: s.wiki, embed: s.embed, comment: s.comment, tagRest: s.tagRest };
      },
      blankLine(s) {
        s.first = false;
        s.wiki = 0;
        if (s.fm === 1) return "line-md-frontmatter";
        if (s.comment) return null;
        if (md.blankLine) md.blankLine(s.md);
        if (inFence(s)) return "line-md-codeblock line-HyperMD-codeblock line-HyperMD-codeblock-bg";
        return "line-md-line-blank";
      },
      token(stream, s) { return alias(rawToken(stream, s)); },
      innerMode(s) { return s.fm === 1 ? { state: s.yaml, mode: yaml } : { state: s.md, mode: md }; },
      indent(s, textAfter, line) { return md.indent ? md.indent(s.md, textAfter, line) : CodeMirror.Pass; },
      fold: "markdown"
    };

    function rawToken(stream, s) {
        const sol = stream.sol();
        if (sol) s.wiki = 0;
        if (sol && s.first) {
          s.first = false;
          if (/^---\s*$/.test(stream.string)) {
            s.fm = 1;
            stream.skipToEnd();
            return "formatting md-frontmatter line-md-frontmatter";
          }
        }
        if (s.fm === 1) {
          if (sol && /^(---|\.\.\.)\s*$/.test(stream.string)) {
            s.fm = 2;
            stream.skipToEnd();
            return "formatting md-frontmatter line-md-frontmatter";
          }
          const style = yaml.token(stream, s.yaml);
          return "md-frontmatter " + (style || "") + (sol ? " line-md-frontmatter" : "");
        }
        s.first = false;
        if (s.comment) {
          if (stream.match("%%")) { s.comment = false; return "md-comment formatting formatting-comment"; }
          while (!stream.eol() && !stream.match("%%", false)) stream.next();
          return "md-comment";
        }
        if (inFence(s)) {
          const style = md.token(stream, s.md);
          return (style || "") + (sol ? " " + lineClasses(stream, s, style) : "");
        }
        if (s.wiki === 1 || s.wiki === 2) {
          if (stream.match("]]")) {
            const embed = s.embed;
            s.wiki = 0; s.embed = false;
            return "formatting formatting-link formatting-link-end" + (embed ? " formatting-embed" : "");
          }
          if (s.wiki === 1 && stream.match("|")) { s.wiki = 2; return "md-wikilink formatting-link-alias-pipe"; }
          stream.match(s.wiki === 1 ? /^[^\]|]+/ : /^[^\]]+/) || stream.next();
          return "md-wikilink " + (s.wiki === 1 ? "md-link-target" : "md-link-alias");
        }
        if (!s.md.inlineCode && !s.md.code) {
          const prev = stream.pos > 0 ? stream.string.charAt(stream.pos - 1) : " ";
          if (stream.match(/^!?\[\[(?=[^\]]*\]\])/)) {
            s.embed = stream.current().charAt(0) === "!";
            s.wiki = 1;
            const style = "formatting formatting-link formatting-link-start" + (s.embed ? " formatting-embed" : "");
            return style + (sol ? " " + lineClasses(stream, s, style) : "");
          }
          if (stream.match("%%")) { s.comment = true; return "md-comment formatting formatting-comment"; }
          if (stream.peek() === "#" && /[\s(\[]/.test(prev) && !(sol && /^#+(\s|$)/.test(stream.string.slice(stream.pos)))) {
            const m = stream.match(TAG_RE, false);
            if (m && !/^#\d+$/.test(m[0])) {
              stream.next();
              s.tagRest = m[0].length - 1;
              return "md-tag";
            }
          }
          if (s.tagRest) {
            const n = s.tagRest; s.tagRest = 0;
            for (let i = 0; i < n; i++) stream.next();
            return "md-tag";
          }
          if ((/[\s(<]/.test(prev) || stream.pos === 0) && stream.match(URL_RE)) return "url md-bare-url";
        }
        let style = md.token(stream, s.md);
        // Un morceau de texte du mode markdown peut avaler le debut d'une syntaxe ajoutee : on revient juste avant.
        const text = stream.current();
        if (text.length > 1 && !(style && /formatting|inline-code|url/.test(style)) && !s.md.inlineCode) {
          const re = /\[\[|%%|(^|[\s(\[])#(?=[^\s#\d])|(^|[\s(<])(?:https?|ftp):\/\//g;
          let match;
          while ((match = re.exec(text))) {
            const at = match.index + (match[1] || match[2] ? 1 : 0);
            if (at > 0) { stream.backUp(text.length - at); break; }
          }
        }
        if (sol) style = (style || "") + " " + lineClasses(stream, s, style);
        return style;
    }
  });

  // -- Blocs rendus (tableaux, callouts) -------------------------------------------------------------------------
  const FENCE_RE = /^(\s*)(`{3,}|~{3,})/;
  const CALLOUT_RE = /^\s*>\s*\[![^\]\s]+\][+-]?/;
  const TABLE_DELIM_RE = /^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$/;

  function scanBlocks(doc) {
    const blocks = [];
    const n = doc.lineCount();
    const line = (i) => doc.getLine(i);
    let i = 0;
    if (n > 1 && /^---\s*$/.test(line(0))) {
      for (let j = 1; j < n; j++) if (/^(---|\.\.\.)\s*$/.test(line(j))) { i = j + 1; break; }
    }
    while (i < n) {
      const text = line(i);
      const m = FENCE_RE.exec(text);
      if (m) {
        const marker = m[2];
        const close = new RegExp("^\\s*" + marker.charAt(0) + "{" + marker.length + ",}\\s*$");
        let j = i + 1;
        while (j < n && !close.test(line(j))) j++;
        i = Math.min(j, n - 1) + 1;
        continue;
      }
      if (CALLOUT_RE.test(text)) {
        let j = i;
        while (j + 1 < n && /^\s*>/.test(line(j + 1))) j++;
        blocks.push({ type: "callout", from: i, to: j });
        i = j + 1;
        continue;
      }
      if (text.indexOf("|") >= 0 && i + 1 < n && TABLE_DELIM_RE.test(line(i + 1)) && line(i + 1).indexOf("-") >= 0 &&
          (line(i + 1).indexOf("|") >= 0 || text.trim().startsWith("|"))) {
        let j = i + 1;
        while (j + 1 < n && line(j + 1).indexOf("|") >= 0 && line(j + 1).trim() !== "") j++;
        blocks.push({ type: "table", from: i, to: j });
        i = j + 1;
        continue;
      }
      i++;
    }
    return blocks;
  }

  // -- 2. Edition visuelle --------------------------------------------------------------------------------------------
  const INLINE_KINDS = ["strong", "em", "strikethrough", "highlight", "code", "comment"];
  const hasClass = (type, cls) => (" " + (type || "") + " ").indexOf(" " + cls + " ") >= 0;

  const NAV_KEYS = { 33: "PageUp", 34: "PageDown", 35: "End", 36: "Home", 37: "ArrowLeft", 38: "ArrowUp",
    39: "ArrowRight", 40: "ArrowDown" };

  class LivePreview {
    constructor(cm, host) {
      this.cm = cm;
      this.host = host;            // resolution des fichiers, rendu des blocs, navigation (app.js)
      this.enabled = true;
      this.states = new WeakMap(); // etat PROPRE A CHAQUE DOCUMENT
      this.useDoc(cm.getDoc());
      this._timer = null;
      // Un widget qui change de taille (image decodee, bloc rendu) : seule SA ligne est remesuree.
      this._sized = new WeakMap();
      this._pendingSized = new Set();
      this._observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver((entries) => {
        for (const entry of entries) {
          const marker = this._sized.get(entry.target);
          if (marker) this._pendingSized.add(marker);
        }
        if (!this._sizedFrame) {
          this._sizedFrame = requestAnimationFrame(() => {
            this._sizedFrame = 0;
            const list = [...this._pendingSized];
            this._pendingSized.clear();
            if (list.length) this.cm.operation(() => { for (const m of list) if (m.find()) m.changed(); });
          });
        }
      }) : null;
      cm.on("changes", () => { this.state.scanDirty = true; this.schedule(); });
      cm.on("cursorActivity", () => { this.enterTable(); this.schedule(); });
      // Seules les touches de deplacement font entrer le curseur dans un tableau (pas l'ouverture d'une note).
      cm.on("keydown", (c, ev) => {
        const key = ev.key || NAV_KEYS[ev.keyCode] || "";
        this._navKey = /^(Arrow|Page|Home|End)/.test(key) ? key : null;
      });
      cm.on("viewportChange", () => this.schedule());
      cm.on("focus", () => this.schedule());
      cm.on("fold", () => this.schedule());
      cm.on("unfold", () => this.schedule());
      cm.on("blur", () => this.schedule());
    }

    useDoc(doc) {
      let state = this.states.get(doc);
      if (!state) {
        state = { blocks: [], blockMarks: new Map(), lineMarks: new Map(), active: new Set(), scanDirty: true, enabled: null,
          tableMarks: new Map(), rawTables: new Set() };
        this.states.set(doc, state);
      }
      this.state = state;
      if (state.enabled !== null && state.enabled !== this.enabled) { this.clearAll(); state.scanDirty = true; }
      state.enabled = this.enabled;
    }

    visibleRange(margin) {
      const cm = this.cm;
      const top = cm.getDoc().scrollTop || 0;
      const height = cm.getScrollerElement().clientHeight || 1200;
      const from = cm.lineAtHeight(top, "local"), to = cm.lineAtHeight(top + height, "local") + 1;
      return [Math.max(0, from - margin), Math.min(cm.lineCount(), to + margin)];
    }

    schedule() {
      if (this._timer) return;
      this._timer = requestAnimationFrame(() => { this._timer = null; this.refresh(); });
    }

    setEnabled(on) {
      if (this.enabled === on) return;
      this.enabled = on;
      this.state.enabled = on;
      this.clearAll();
      this.state.scanDirty = true;
      this.refresh();
    }

    clearAll() {
      const st = this.state;
      this.cm.operation(() => {
        for (const entry of st.blockMarks.values()) entry.marker.clear();
        st.blockMarks.clear();
        for (const entry of st.tableMarks.values()) { entry.dropping = true; entry.widget.destroy(); entry.marker.clear(); }
        st.tableMarks.clear();
        this.activeTable = null;
        for (const entry of st.lineMarks.values()) for (const mark of entry.marks) mark.clear();
        st.lineMarks.clear();
      });
    }

    activeLines() {
      const lines = new Set();
      if (!this.cm.hasFocus() && !this._keepActive) return lines;
      for (const range of this.cm.listSelections()) {
        const a = Math.min(range.anchor.line, range.head.line), b = Math.max(range.anchor.line, range.head.line);
        for (let i = a; i <= b; i++) lines.add(i);
      }
      return lines;
    }

    refresh() {
      if (!this.enabled || !this.host.isMarkdown()) return;
      const cm = this.cm, st = this.state;
      const t0 = performance.now();
      cm.operation(() => {
        if (!st.scanDirty && st.blocks.some((b) => b.to >= cm.lineCount())) st.scanDirty = true;
        if (st.scanDirty) { st.blocks = scanBlocks(cm.getDoc()); st.scanDirty = false; }
        const active = this.activeLines();
        const sel = cm.listSelections();
        this.refreshBlocks(active);
        const [from, to] = this.visibleRange(20);
        const covered = this.coveredLines();
        for (let i = from; i < to; i++) {
          if (covered.has(i)) continue;
          this.refreshLine(i, cm.getLineHandle(i), active.has(i), sel);
        }
        for (const [handle, entry] of st.lineMarks) {
          if (handle.lineNo() === null || covered.has(handle.lineNo())) {
            for (const mark of entry.marks) mark.clear();
            st.lineMarks.delete(handle);
          }
        }
      });
      MD.metrics && MD.metrics.add("lp", performance.now() - t0);
      // Un tableau recale (ligne ajoutee / retiree) : sa cellule active reprend la main apres la mise a jour.
      if (this._refocus) { const w = this._refocus; this._refocus = null; w.focusActive(); }
    }

    coveredLines() {
      const out = new Set();
      for (const entry of this.state.blockMarks.values()) for (let i = entry.block.from; i <= entry.block.to; i++) out.add(i);
      for (const entry of this.state.tableMarks.values()) {
        const f = entry.marker.find();
        if (f) for (let i = f.from.line; i <= f.to.line; i++) out.add(i);
      }
      return out;
    }

    refreshBlocks(active) {
      const doc = this.cm.getDoc(), st = this.state;
      const keep = new Set(), tables = new Set();
      for (const b of st.blocks) {
        if (b.type === "table") { this.refreshTable(b, active, tables); continue; }
        let revealed = false;
        for (let i = b.from; i <= b.to; i++) if (active.has(i)) { revealed = true; break; }
        if (revealed) continue;
        const text = doc.getRange({ line: b.from, ch: 0 }, { line: b.to, ch: doc.getLine(b.to).length });
        const key = b.type + ":" + b.from + ":" + text;
        keep.add(key);
        if (st.blockMarks.has(key)) continue;
        for (let i = b.from; i <= b.to; i++) {
          const handle = doc.getLineHandle(i);
          const entry = st.lineMarks.get(handle);
          if (entry) { for (const mark of entry.marks) mark.clear(); st.lineMarks.delete(handle); }
        }
        const el = this.renderBlock(b, text);
        let marker;
        try {
          marker = doc.markText({ line: b.from, ch: 0 }, { line: b.to, ch: doc.getLine(b.to).length },
            { replacedWith: el, handleMouseEvents: false, clearOnEnter: true, inclusiveLeft: false, inclusiveRight: false });
        } catch (err) {
          continue;
        }
        marker.on("clear", () => {
          const current = st.blockMarks.get(key);
          if (current && current.marker === marker) st.blockMarks.delete(key);
          if (this._observer) this._observer.unobserve(el);
        });
        this.watchSize(el, marker);
        st.blockMarks.set(key, { marker, block: b });
      }
      for (const [key, entry] of st.blockMarks) if (!keep.has(key)) { st.blockMarks.delete(key); entry.marker.clear(); }
      for (const [handle, entry] of st.tableMarks) {
        if (tables.has(handle)) continue;
        st.tableMarks.delete(handle);
        entry.dropping = true;
        entry.widget.destroy();
        if (this.activeTable === entry.widget) this.activeTable = null;
        entry.marker.clear();
      }
    }

    // -- Tableaux : toujours en cellules (table.js), sauf source demandee (« </> ») tant que le curseur y reste ----
    refreshTable(b, active, tables) {
      const doc = this.cm.getDoc(), st = this.state;
      const handle = doc.getLineHandle(b.from);
      if (st.rawTables.has(handle)) {
        let inside = false;
        for (let i = b.from; i <= b.to; i++) if (active.has(i)) { inside = true; break; }
        if (inside) return;
        st.rawTables.delete(handle);
      }
      const text = doc.getRange({ line: b.from, ch: 0 }, { line: b.to, ch: doc.getLine(b.to).length });
      if (!MD.tableModel.parseTable(text).valid) return;      // syntaxe incomplete : texte tel quel
      tables.add(handle);
      const entry = st.tableMarks.get(handle);
      if (entry) {
        const f = entry.marker.find();
        if (f && f.from.line === b.from && f.from.ch === 0 && f.to.line === b.to && f.to.ch === doc.getLine(b.to).length) {
          entry.widget.update(text);
          return;
        }
        // Lignes ajoutees / retirees : meme widget, recale sur les nouvelles lignes.
        const refocus = !!(entry.widget.active && entry.widget.nested);
        entry.dropping = true;
        entry.marker.clear();
        entry.dropping = false;
        this.clearLineMarks(b);
        const marker = this.markTable(b, entry.widget.el, handle);
        if (!marker) { st.tableMarks.delete(handle); entry.widget.destroy(); tables.delete(handle); return; }
        entry.marker = entry.widget.marker = marker;
        entry.widget.update(text);
        if (refocus) this._refocus = entry.widget;
        return;
      }
      this.clearLineMarks(b);
      const widget = new MD.TableWidget(this, text);
      const marker = this.markTable(b, widget.el, handle);
      if (!marker) { tables.delete(handle); return; }
      widget.marker = marker;
      st.tableMarks.set(handle, { marker, widget });
    }

    clearLineMarks(b) {
      const doc = this.cm.getDoc(), st = this.state;
      for (let i = b.from; i <= b.to; i++) {
        const h = doc.getLineHandle(i);
        const entry = st.lineMarks.get(h);
        if (entry) { for (const mark of entry.marks) mark.clear(); st.lineMarks.delete(h); }
      }
    }

    markTable(b, el, handle) {
      const doc = this.cm.getDoc(), st = this.state;
      let marker;
      try {
        marker = doc.markText({ line: b.from, ch: 0 }, { line: b.to, ch: doc.getLine(b.to).length },
          { replacedWith: el, handleMouseEvents: false, inclusiveLeft: false, inclusiveRight: false });
      } catch (err) {
        return null;
      }
      marker.on("clear", () => {
        const entry = st.tableMarks.get(handle);
        if (!entry || entry.marker !== marker || entry.dropping) return;
        st.tableMarks.delete(handle);       // texte du tableau supprime
        entry.widget.destroy();
      });
      this.watchSize(el, marker);
      return marker;
    }

    /** Ce qui a ete tape dans une cellule de tableau et pas encore ecrit dans la note : ecrit maintenant. */
    flushTables() {
      if (this.activeTable) this.activeTable.flush();
    }

    /** Cellule active d'un tableau (editeur CodeMirror de la cellule), sinon null. */
    activeCell() {
      return this.activeTable && this.activeTable.nested ? this.activeTable.nested : null;
    }

    tableActivated(widget) {
      if (widget && this.activeTable && this.activeTable !== widget) this.activeTable.deactivate(true);
      this.activeTable = widget;
    }

    /** « </> » : le tableau redevient du texte tant que le curseur y reste. */
    revealTable(widget, r) {
      const doc = this.cm.getDoc(), st = this.state;
      const handle = doc.getLineHandle(r.from);
      st.rawTables.add(handle);
      const entry = st.tableMarks.get(handle);
      if (entry) {
        st.tableMarks.delete(handle);
        entry.dropping = true;
        entry.widget.destroy();
        entry.marker.clear();
      }
      if (this.activeTable === widget) this.activeTable = null;
      this.skipTableEntry = true;
      this.cm.focus();
      this.cm.setCursor({ line: r.from, ch: 0 });
      this.skipTableEntry = false;
      this.refresh();
    }

    /** Le curseur de la note arrive dans un tableau (fleches, pages) : la cellule correspondante prend la main. */
    enterTable() {
      const key = this._navKey;
      this._navKey = null;
      const cm = this.cm;
      const pos = cm.getCursor(), prev = this._prevLine;
      this._prevLine = pos.line;
      if (!key || this.skipTableEntry || !cm.hasFocus() || cm.somethingSelected()) return;
      for (const entry of this.state.tableMarks.values()) {
        const w = entry.widget;
        const f = entry.marker.find();
        if (!f || pos.line < f.from.line || pos.line > f.to.line || !w.model || !w.model.valid) continue;
        const m = w.model;
        // Arrivee par le dessus : 1re cellule ; par le dessous : derniere ligne (le curseur de la note se pose au
        // debut ou a la fin du tableau masque, selon l'editeur).
        if (prev != null && prev < f.from.line) return w.activate(0, 0, 0);
        if (prev != null && prev > f.to.line) {
          const left = /Left/.test(key);
          return w.activate(m.rows.length - 1, left ? m.cols - 1 : 0, left ? "end" : 0);
        }
        const rel = pos.line - f.from.line;
        const r = rel <= 1 ? 0 : rel - 1;
        const row = m.rows[r];
        let c = 0;
        if (row) for (let i = 0; i < row.cells.length; i++) if (pos.ch >= row.cells[i].from) c = i;
        const cell = row && row.cells[c];
        return w.activate(r, Math.min(c, m.cols - 1), cell ? Math.max(0, pos.ch - cell.a) : 0);
      }
    }


    renderBlock(b, text) {
      const el = document.createElement("div");
      el.className = "md-block md-rendered md-block-" + b.type + " cm-embed-block markdown-rendered" +
        (b.type === "table" ? " cm-table-widget" : b.type === "callout" ? " cm-callout" : "");
      const reveal = (ev) => {
        if (ev && ev.target.closest("a, input, button")) return;
        if (ev) ev.preventDefault();
        this.cm.focus();
        this.cm.setCursor({ line: b.from, ch: 0 });
      };
      this.host.renderFragment(text, el);
      const button = document.createElement("div");
      button.className = "md-edit-block";
      button.textContent = "</>";
      button.title = "Modifier ce bloc";
      button.addEventListener("mousedown", (ev) => { ev.stopPropagation(); reveal(ev); });
      el.appendChild(button);
      el.addEventListener("mousedown", reveal);
      return el;
    }

    watchSize(el, marker) {
      if (!this._observer) return;
      this._sized.set(el, marker);
      this._observer.observe(el);
    }

    refreshLine(i, handle, isActive, sel) {
      const cm = this.cm, st = this.state;
      const text = handle.text;
      const cursors = [];
      if (cm.hasFocus() || this._keepActive) {
        for (const r of sel) {
          const lo = CodeMirror.cmpPos(r.anchor, r.head) <= 0 ? r.anchor : r.head, hi = lo === r.anchor ? r.head : r.anchor;
          if (lo.line > i || hi.line < i) continue;
          cursors.push([lo.line < i ? 0 : lo.ch, hi.line > i ? text.length : hi.ch]);
        }
      }
      const lineClass = (handle.styleClasses && handle.styleClasses.textClass) || "";
      const heading = /\bmd-h[1-6]\b/.test(lineClass);
      const folded = heading && cm.isFolded({ line: i, ch: text.length });
      const sig = text + "\u0000" + (isActive ? "A" : "") + (folded ? "F" : "") + cursors.map((c) => c.join(",")).join(";");
      const entry = st.lineMarks.get(handle);
      if (entry && entry.sig === sig) return;
      if (entry) for (const mark of entry.marks) mark.clear();
      const marks = [];
      st.lineMarks.set(handle, { sig, marks });
      if (!text) return;
      const touched = (from, to) => cursors.some(([a, b]) => a <= to && b >= from);
      let tokens;
      try { tokens = cm.getLineTokens(i, true); } catch (err) { return; }
      const doc = cm.getDoc();
      const hide = (from, to, group) => {
        if (to <= from) return;
        const m = doc.markText({ line: i, ch: from }, { line: i, ch: to }, { collapsed: true, inclusiveLeft: false,
          inclusiveRight: false, clearWhenEmpty: true });
        if (group) group.push(m);
        marks.push(m);
      };
      const widget = (from, to, node, mouse) => {
        const m = doc.markText({ line: i, ch: from }, { line: i, ch: to }, { replacedWith: node, handleMouseEvents: !!mouse,
          inclusiveLeft: false, inclusiveRight: false });
        marks.push(m);
        if (node.querySelector && node.querySelector("img")) this.watchSize(node, m);
        return m;
      };
      // Classe posee sur un morceau de texte (le texte reste, editable) : retraits, marques des listes, « > ».
      const cls = (from, to, className) => {
        if (to <= from) return;
        marks.push(doc.markText({ line: i, ch: from }, { line: i, ch: to }, { className, inclusiveLeft: false,
          inclusiveRight: false }));
      };
      // Le curseur qui entre dans une marque masquee revele tout l'element (ses deux balises).
      const revealOnEnter = (group) => { for (const m of group) m.on("beforeCursorEnter", () => { for (const x of group) x.clear(); }); };
      // Titre : chevron de repli (comme Obsidian), a gauche, hors du texte.
      if (heading) {
        const fold = document.createElement("span");
        fold.className = "md-fold cm-fold-indicator" + (folded ? " is-collapsed" : "");
        fold.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" ' +
          'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>';
        fold.title = folded ? "Déplier" : "Replier";
        fold.addEventListener("mousedown", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          const line = handle.lineNo();
          if (line !== null) this.toggleFold(line);
        });
        marks.push(doc.setBookmark({ line: i, ch: 0 }, { widget: fold, insertLeft: true, handleMouseEvents: true }));
      }
      // Dans les blocs de code, seuls les delimitateurs sont masques hors de leur ligne active.
      if (/\bmd-codeblock\b/.test(lineClass)) {
        if (!isActive && /\bmd-codeblock-(begin|end)\b/.test(lineClass)) {
          const fence = /^(\s*)(`{3,}|~{3,})/.exec(text);
          if (fence) {
            const group = [];
            hide(fence[1].length, fence[1].length + fence[2].length, group);
            revealOnEnter(group);
          }
        }
        return;
      }
      if (/\bmd-frontmatter\b/.test(lineClass)) return;
      // Listes, comme Obsidian : chaque cran de retrait a la largeur « Retrait des listes » ; la marque (puce,
      // numero, case) est decalee de 0,75 em (--list-indent-editing) et garde sa place quand le curseur la touche.
      if (/\bmd-list-line\b/.test(lineClass)) {
        const lead = /^\s*/.exec(text)[0];
        const unit = /^( {4})+$/.test(lead.replace(/\t/g, "")) ? 4 : 2;
        let at = 0;
        while (at < lead.length) {
          if (lead.charAt(at) === "\t") { at++; continue; }       // tabulation : largeur posee par la feuille (.cm-tab)
          const n = Math.min(unit, lead.length - at);
          let k = 0;
          while (k < n && lead.charAt(at + k) === " ") k++;
          cls(at, at + Math.max(k, 1), "md-indent");
          at += Math.max(k, 1);
        }
      }
      // Debut de ligne : titres, citations, puces, cases, filets.
      for (const t of tokens) {
        const type = t.type || "";
        if (hasClass(type, "formatting-header") && t.start === 0 && !isActive) {
          const g = []; hide(0, t.end + (text.charAt(t.end) === " " ? 1 : 0), g); revealOnEnter(g);
        } else if (hasClass(type, "formatting-quote")) {
          // « > » garde sa place (comme Obsidian : transparent hors de la ligne du curseur) : le texte ne saute pas.
          if (!isActive) cls(t.start, t.end, "md-quote-mark-hidden");
        } else if (hasClass(type, "formatting-list-ul")) {
          const task = tokens.some((x) => x.start >= t.end && hasClass(x.type, "formatting-task"));
          const level = (((Number((/list-(\d)/.exec(type) || [, 1])[1]) - 1) % 3) + 1);
          if (task) cls(t.start, t.start + 1, "md-list-mark md-task-dash");    // tache : le tiret reste, invisible
          else if (touched(t.start, t.end)) cls(t.start, t.start + 1, "md-list-mark");
          else {
            const wrap = document.createElement("span");
            wrap.className = "cm-formatting cm-formatting-list cm-formatting-list-ul cm-list-" + level + " md-list-mark";
            const span = document.createElement("span");
            span.className = "md-bullet level-" + level + " list-bullet";
            wrap.appendChild(span);
            widget(t.start, t.start + 1, wrap);
          }
        } else if (hasClass(type, "formatting-list-ol")) {
          const num = /^\s*\d+[.)]/.exec(text.slice(t.start));
          if (num) cls(t.start + num[0].length - num[0].trimStart().length, t.start + num[0].length, "md-list-mark");
        } else if (hasClass(type, "formatting-task") && !touched(t.start, t.end)) {
          const box = document.createElement("input");
          box.type = "checkbox";
          box.className = "md-checkbox task-list-item-checkbox";
          box.checked = text.charAt(t.start + 1) !== " ";
          box.addEventListener("mousedown", (ev) => {
            ev.preventDefault();
            const line = handle.lineNo();
            if (line === null) return;
            const at = t.start + 1;
            cm.replaceRange(box.checked ? " " : "x", { line, ch: at }, { line, ch: at + 1 }, "+task");
          });
          widget(t.start, t.end, box);
        } else if (hasClass(type, "hr") && !isActive && t.start === 0 && /^\s*([-*_])(\s*\1){2,}\s*$/.test(text)) {
          const hr = document.createElement("span");
          hr.className = "md-hr";
          widget(0, text.length, hr);
          return;
        }
      }
      // Elements en ligne : paires de balises masquees si le curseur ne les touche pas.
      const open = {}, spans = [];
      for (const t of tokens) {
        if (!hasClass(t.type, "formatting")) continue;
        let kind = null;
        for (const k of INLINE_KINDS) if (hasClass(t.type, "formatting-" + k)) { kind = k; break; }
        if (!kind) continue;
        if (open[kind]) { spans.push({ kind, a: open[kind], b: t }); open[kind] = null; } else open[kind] = t;
      }
      for (const s of spans) {
        if (s.kind === "comment" || touched(s.a.start, s.b.end)) continue;
        const g = [];
        hide(s.a.start, s.a.end, g);
        hide(s.b.start, s.b.end, g);
        revealOnEnter(g);
      }
      // Les anciennes commandes couleur de la barre ecrivent du HTML inline. Live Preview doit en montrer
      // l'effet (texte colore / surligne) et garder les balises accessibles seulement quand on les edite.
      const htmlColors = /<(font)\s+color\s*=\s*(["'])(#[\da-f]{3,8}|rgba?\([^)]*\)|hsla?\([^)]*\)|[a-z]+)\2\s*>([\s\S]*?)<\/font\s*>|<(mark)\s+style\s*=\s*(["'])\s*background(?:-color)?\s*:\s*(#[\da-f]{3,8}|rgba?\([^)]*\)|hsla?\([^)]*\)|[a-z]+)\s*;?\s*\6\s*>([\s\S]*?)<\/mark\s*>/gi;
      let colored;
      while ((colored = htmlColors.exec(text))) {
        const start = colored.index, end = start + colored[0].length;
        const revealMarkup = touched(start, end);
        const font = !!colored[1];
        const value = font ? colored[3] : colored[7];
        const content = font ? colored[4] : colored[8];
        const openEnd = font ? colored[0].indexOf(">") + 1 : colored[0].indexOf(">") + 1;
        const closeStart = start + colored[0].toLowerCase().lastIndexOf(font ? "</font" : "</mark");
        const inCode = tokens.some((t) => t.start < end && t.end > start &&
          (hasClass(t.type, "inline-code") || hasClass(t.type, "md-comment")));
        if (inCode || closeStart < start + openEnd) continue;
        const opening = [start, start + openEnd], closing = [closeStart, end];
        // Le curseur revele le code source, mais ne doit jamais annuler le style applique au contenu.
        if (!revealMarkup) {
          const pair = [];
          hide(opening[0], opening[1], pair);
          hide(closing[0], closing[1], pair);
          revealOnEnter(pair);
        }
        const attr = font ? { style: "color: " + value + " !important" }
          : { style: "background-color: " + value + " !important" };
        marks.push(doc.markText({ line: i, ch: start + openEnd }, { line: i, ch: closeStart },
          { className: font ? "md-inline-font-color" : "md-inline-background-color", attributes: attr,
            inclusiveLeft: false, inclusiveRight: false }));
      }
      this.decorateLinks(text, tokens, touched, widget);
    }

    /** Replie / deplie la partie d'un titre (jusqu'au titre suivant de meme niveau ou plus haut). */
    toggleFold(line) {
      if (!CodeMirror.fold || !CodeMirror.fold.markdown) return;
      const placeholder = document.createElement("span");
      placeholder.className = "cm-foldPlaceholder md-fold-placeholder";
      placeholder.textContent = "…";
      this.cm.foldCode({ line, ch: 0 }, { rangeFinder: CodeMirror.fold.markdown, widget: placeholder, scanUp: false });
      this.schedule();
    }

    decorateLinks(text, tokens, touched, widget) {
      const inCode = (start) => {
        const tok = tokens.find((t) => t.start <= start && t.end > start);
        return tok && (hasClass(tok.type, "inline-code") || hasClass(tok.type, "md-comment"));
      };
      // [[cible|alias]] / ![[image.png|300]]
      const re = /(!?)\[\[([^\]]*)\]\]/g;
      let m;
      while ((m = re.exec(text))) {
        const start = m.index, end = m.index + m[0].length;
        if (inCode(start) || touched(start, end)) continue;
        const [linkPath, alias] = splitOnce(m[2], "|");
        const [path, anchor] = splitOnce(linkPath, "#");
        const ext = (path.match(/\.([^.\/]+)$/) || [, ""])[1].toLowerCase();
        if (m[1] && MD.IMAGE_EXT.has(ext)) {
          widget(start, end, this.imageNode(this.host.resolve(path), path, alias), false);
          continue;
        }
        const node = document.createElement("span");
        const label = alias != null ? alias : (anchor != null ? (path ? path + " > " : "") + anchor.replace(/^\^/, "") : path);
        node.className = "md-link cm-hmd-internal-link" + (path && !this.host.exists(path) ? " is-unresolved" : "");
        node.textContent = label;
        node.addEventListener("mousedown", (ev) => {
          if (ev.button !== 0) return;
          ev.preventDefault();
          this.host.openLink(linkPath);
        });
        widget(start, end, node, false);
      }
      // [texte](url) et ![alt](url)
      const mdre = /(!?)\[((?:[^\]\\]|\\.)*)\]\(([^)\s]*(?:\s+"[^"]*")?)\)/g;
      while ((m = mdre.exec(text))) {
        const start = m.index, end = m.index + m[0].length;
        if (inCode(start) || touched(start, end)) continue;
        const url = m[3].replace(/\s+"[^"]*"$/, "");
        const external = /^[a-z][\w+.-]*:/i.test(url);
        if (m[1]) {
          const [alt, size] = splitOnce(m[2], "|");
          widget(start, end, this.imageNode(external ? url : this.host.resolve(safeDecode(url)), alt || url,
            size != null ? size : (/^\d+(x\d+)?$/.test(alt) ? alt : null)), false);
          continue;
        }
        const node = document.createElement("span");
        node.className = "md-link cm-link";
        node.innerHTML = renderInlineSimple(m[2]);
        node.addEventListener("mousedown", (ev) => {
          if (ev.button !== 0) return;
          ev.preventDefault();
          if (external) this.host.openExternal(url); else this.host.openLink(safeDecode(url));
        });
        widget(start, end, node, false);
      }
      // Adresses en clair : cliquables (le texte reste visible).
      for (const t of tokens) {
        if (!hasClass(t.type, "md-bare-url") || touched(t.start, t.end)) continue;
        const url = text.slice(t.start, t.end);
        const node = document.createElement("span");
        node.className = "md-link cm-url";
        node.textContent = url;
        node.addEventListener("mousedown", (ev) => {
          if (ev.button !== 0) return;
          ev.preventDefault();
          this.host.openExternal(url);
        });
        widget(t.start, t.end, node, false);
      }
    }

    imageNode(src, label, size) {
      const wrap = document.createElement("span");
      wrap.className = "md-image";
      if (!src) {
        wrap.className = "md-image is-unresolved";
        wrap.textContent = label;
        return wrap;
      }
      const img = document.createElement("img");
      img.src = src;
      img.alt = label || "";
      img.draggable = false;
      img.loading = "lazy";
      img.addEventListener("error", () => { wrap.className = "md-image is-unresolved"; wrap.textContent = label; });
      if (size && /^\s*\d+(x\d+)?\s*$/.test(size)) {
        const [w, h] = size.trim().split("x");
        img.setAttribute("width", w);
        if (h) img.setAttribute("height", h);
      }
      wrap.appendChild(img);
      return wrap;
    }
  }

  function splitOnce(text, sep) {
    const at = text.indexOf(sep);
    return at < 0 ? [text, undefined] : [text.slice(0, at), text.slice(at + 1)];
  }

  function safeDecode(text) {
    try { return decodeURIComponent(text); } catch (err) { return text; }
  }

  function escapeHtml(text) {
    return String(text == null ? "" : text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  }
  MD.escapeHtml = escapeHtml;

  function renderInlineSimple(text) {
    return escapeHtml(text).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>");
  }

  // -- 3. L'editeur ----------------------------------------------------------------------------------------------------
  class Editor {
    constructor(host, api) {
      this.host = host;
      this.api = api;               // app.js : textChanged, save, find…
      this.docs = new Map();         // chemin -> {doc, text, dirty, kind, fresh}
      this.path = null;
      this.kind = null;
      this._loading = false;
      const cm = this.cm = CodeMirror(host, {
        value: "", mode: "pfm", theme: "obsidian", lineWrapping: true, inputStyle: "contenteditable", spellcheck: false, tabSize: 4,
        indentUnit: 4, indentWithTabs: true, viewportMargin: 10, cursorScrollMargin: 40, dragDrop: true,
        autoCloseBrackets: "()[]{}``", undoDepth: 1000,
        extraKeys: {
          "Enter": (c) => this.kind === "markdown" ? c.execCommand("newlineAndIndentContinueMarkdownList") : c.execCommand("newlineAndIndent"),
          "Tab": (c) => this.indent(c, false), "Shift-Tab": (c) => this.indent(c, true),
          "Ctrl-B": () => MD.toolbar && MD.toolbar.run("editing-toolbar:toggle-bold"),
          "Ctrl-I": () => MD.toolbar && MD.toolbar.run("editing-toolbar:toggle-italics"),
          "Ctrl-L": () => MD.toolbar && MD.toolbar.run("editing-toolbar:editor:cycle-list-checklist"),
          "Ctrl-K": () => MD.toolbar && MD.toolbar.run("editing-toolbar:insert-link"),
          "Alt-Up": "swapLineUp", "Alt-Down": "swapLineDown",
          "Ctrl-F": () => this.find(), "F3": () => this.findNext(1), "Shift-F3": () => this.findNext(-1),
          "Ctrl-Z": "undo", "Ctrl-Y": "redo", "Shift-Ctrl-Z": "redo", "Ctrl-D": "deleteLine", "Ctrl-A": "selectAll"
        }
      });
      cm.on("renderLine", (c, line, elt) => this.decorateLine(line, elt));
      // Classes d'Obsidian sur l'editeur (cm-editor, cm-content) ; « cm-active » suit la ligne du curseur.
      cm.getWrapperElement().classList.add("cm-editor");
      cm.display.lineDiv.classList.add("cm-content");
      cm.on("cursorActivity", () => this.markActiveLine());
      cm.on("changes", () => {
        if (this._loading) return;
        const entry = this.docs.get(this.path);
        if (entry) entry.dirty = true;
        this.api.textChanged();
      });
      this.lp = new LivePreview(cm, {
        isMarkdown: () => this.kind === "markdown",
        resolve: (target) => MD.resolveFile(target),
        exists: (target) => MD.fileExists(target),
        openLink: (target) => MD.openLink(target),
        openExternal: (url) => MD.call("openExternal", url),
        renderFragment: (text, el) => MD.renderFragment(text, el),
        // Frappe dans une cellule de tableau (ecrite dans la note un peu plus tard) : la note est deja modifiee.
        edited: () => {
          const entry = this.docs.get(this.path);
          if (entry) entry.dirty = true;
          this.api.textChanged();
        }
      });
      cm.getInputField().addEventListener("keydown", () => { this._keyAt = performance.now(); }, true);
      cm.on("update", () => { if (this._keyAt) { MD.metrics.add("key", performance.now() - this._keyAt); this._keyAt = 0; } });
    }

    decorateLine(line, elt) {
      if (this.kind !== "markdown") return;
      elt.classList.add("cm-line");
      if (line === this._activeLine) elt.classList.add("cm-active");
      const text = line.text;
      const list = /^(\s*)([-*+]|\d+[.)])(\s+)(\[(.)\]\s+)?/.exec(text);
      if (list) {
        // Comme Obsidian : la 1re ligne part du bord (retraits, puis la marque), les lignes repliees s'alignent sur
        // le texte de l'element (retrait suspendu de la largeur des retraits + de la marque, mesuree une fois).
        const levels = list[1].replace(/ {4}/g, "\t").replace(/ {2}/g, "\t").replace(/ /g, "").length;
        const kind = list[4] ? "task" : /\d/.test(list[2]) ? "ol" : "ul";
        const width = this.markerWidth(kind, levels, list[2]);
        if (width != null) {
          const x = `calc(${levels} * var(--md-list-indent) + ${width}px)`;
          elt.style.textIndent = `calc(-1 * ${x})`;
          elt.style.paddingInlineStart = x;
        }
        if (list[5] && list[5] !== " ") { elt.classList.add("md-task-done"); elt.setAttribute("data-task", list[5]); }
        if (list[4]) elt.classList.add("HyperMD-task-line");
      }
      if (/^\s*>/.test(text)) {
        const no = line.lineNo();
        const prev = no > 0 ? this.cm.getLine(no - 1) : "", next = no + 1 < this.cm.lineCount() ? this.cm.getLine(no + 1) : "";
        if (!/^\s*>/.test(prev || "")) elt.classList.add("md-quote-first");
        if (!/^\s*>/.test(next || "")) elt.classList.add("md-quote-last");
      }
    }

    /** Largeur (px) de la marque d'un element de liste, espaces compris : mesuree dans la page avec la feuille en
        cours (puces, cases et numeros de la feuille de l'utilisateur), gardee jusqu'au prochain changement de style. */
    markerWidth(kind, levels, marker) {
      const level = (levels % 3) + 1;
      const key = kind + ":" + level + ":" + (kind === "ol" ? marker : "");
      const cache = this._markerWidths || (this._markerWidths = new Map());
      if (cache.has(key)) return cache.get(key).width;
      const width = this.measureMarker(kind, levels, marker);
      cache.set(key, { width, args: [kind, levels, marker] });
      return width;
    }

    measureMarker(kind, levels, marker) {
      const level = (levels % 3) + 1;
      const list = `cm-formatting cm-formatting-list cm-list-${level}`;
      const html = kind === "ul" ?
        `<span class="${list} cm-formatting-list-ul md-list-mark"><span class="md-bullet level-${level} list-bullet"></span></span><span class="${list} cm-formatting-list-ul"> </span>`
        : kind === "ol" ? `<span class="${list} cm-formatting-list-ol"><span class="md-list-mark">${MD.escapeHtml(marker)}</span> </span>`
        : `<span class="${list} cm-formatting-list-ul"><span class="md-list-mark md-task-dash">-</span> </span>` +
          `<input type="checkbox" class="md-checkbox task-list-item-checkbox"><span> </span>`;
      const pre = document.createElement("pre");
      pre.className = `CodeMirror-line cm-line md-list-line HyperMD-list-line HyperMD-list-line-${levels + 1}`;
      pre.innerHTML = html + '<span class="md-measure-end">x</span>';
      const box = this.cm.display.measure;
      box.appendChild(pre);
      const end = pre.lastChild;
      const width = Math.max(0, end.offsetLeft - (parseFloat(getComputedStyle(pre).paddingLeft) || 0));
      pre.remove();
      return width;
    }

    /** Feuille ou reglages changes : marques des listes remesurees, lignes redessinees. « light » (bloc gere de la
        feuille partagee, a chaque cran d'un reglage) : seules les marques sont remesurees (quelques mesures), et
        les lignes ne sont redessinees que si l'une d'elles a change de largeur (une couleur ne coute rien). */
    styleChanged(light) {
      this._styleFull = this._styleFull || !light;
      if (this._styleFrame) return;                // plusieurs messages de style dans la meme image : un seul passage
      this._styleFrame = requestAnimationFrame(() => {
        this._styleFrame = 0;
        const full = this._styleFull;
        this._styleFull = false;
        const cache = this._markerWidths;
        let moved = full;
        if (!full && cache) {
          for (const entry of cache.values()) {
            const width = this.measureMarker(...entry.args);
            if (Math.abs(width - entry.width) > 0.01) { entry.width = width; moved = true; }
          }
        }
        if (full && cache) cache.clear();
        if (moved) this.cm.refresh();
      });
    }

    markActiveLine() {
      const line = this.kind === "markdown" ? this.cm.getLineHandle(this.cm.getCursor().line) : null;
      if (line === this._activeLine) return;
      const before = this._activeLine && this.lineNode(this._activeLine);
      this._activeLine = line;
      const after = line && this.lineNode(line);
      if (before) before.classList.remove("cm-active");
      if (after) after.classList.add("cm-active");
    }

    lineNode(handle) {
      for (const view of this.cm.display.view) if (view.line === handle) return view.text;
      return null;
    }

    /** Ouvre (ou retrouve) le document d'un fichier. */
    open(info, options) {
      const t0 = performance.now();
      let entry = this.docs.get(info.path);
      if (!entry || (entry.text !== info.text && !entry.dirty)) {
        const mode = info.kind === "markdown" ? "pfm" : MD.modeForExtension(info.ext);
        entry = { doc: CodeMirror.Doc(info.text, mode), text: info.text, dirty: false, fresh: true, kind: info.kind };
        this.docs.set(info.path, entry);
        // Memoire : les documents les plus anciens partent (leur historique d'annulation avec eux).
        while (this.docs.size > 12) {
          const oldest = this.docs.keys().next().value;
          if (oldest === info.path) break;
          this.docs.delete(oldest);
        }
      } else {
        this.docs.delete(info.path);          // le plus recent en dernier
        this.docs.set(info.path, entry);
      }
      // UNE operation : document, edition visuelle et curseur poses ensemble (une seule mise en page).
      this.cm.operation(() => {
        this._loading = true;
        this.cm.swapDoc(entry.doc);
        this._loading = false;
        this.path = info.path;
        this.kind = info.kind;
        // L'etat de l'edition visuelle suit le document AVANT les options (qui peuvent l'allumer / l'eteindre).
        this.lp.useDoc(entry.doc);
        this.applyOptions(options);
        this.syncTitle(info.title);
        if (entry.fresh) {
          entry.fresh = false;
          this.cm.setCursor(info.kind === "markdown" ? this.firstBodyLine() : 0, 0);
          this.cm.scrollTo(null, 0);
        }
        this.lp.refresh();
      });
      MD.metrics.add("editor_open", performance.now() - t0);
    }

    firstBodyLine() {
      const doc = this.cm.getDoc();
      if (doc.lineCount() > 1 && /^---\s*$/.test(doc.getLine(0))) {
        for (let j = 1; j < doc.lineCount(); j++) if (/^(---|\.\.\.)\s*$/.test(doc.getLine(j))) return Math.min(j + 1, doc.lineCount() - 1);
      }
      return 0;
    }

    applyOptions(options) {
      const md = this.kind === "markdown";
      const o = options || MD.state.options || {};
      this.host.classList.toggle("is-code", !md);
      for (const cls of ["markdown-source-view", "mod-cm6", "is-live-preview"]) this.host.classList.toggle(cls, md);
      this.cm.setOption("lineNumbers", !md && !!o.lineNumbers);
      this.cm.setOption("lineWrapping", md || !!o.wrapCode);
      this.cm.setOption("styleActiveLine", !md);
      this.cm.setOption("tabSize", o.tabSize || 4);
      this.cm.setOption("indentUnit", o.tabSize || 4);
      this.lp.setEnabled(md && o.livePreview !== false);
    }

    syncTitle(title) {
      // Titre de la note au-dessus de la 1re ligne : un widget PAR document (garde avec lui).
      const doc = this.cm.getDoc();
      const want = this.kind === "markdown";
      if (doc.mdTitle && (!want || doc.mdTitle.line === null || doc.mdTitle.line.lineNo() !== 0)) {
        doc.mdTitle.clear();
        doc.mdTitle = null;
      }
      if (want && !doc.mdTitle && this.cm.lineCount()) {
        const node = document.createElement("div");
        node.className = "md-above";
        node.innerHTML = '<div class="md-title inline-title"></div>';
        doc.mdTitleNode = node;
        doc.mdTitle = this.cm.addLineWidget(0, node, { above: true, coverGutter: false });
      }
      if (doc.mdTitleNode && title != null) doc.mdTitleNode.firstChild.textContent = title;
    }

    getText() { this.lp.flushTables(); return this.cm.getValue(); }

    reloadText(path, text) {
      const entry = this.docs.get(path);
      if (!entry) return;
      entry.text = text;
      entry.dirty = false;
      if (path !== this.path) { this.docs.delete(path); return; }
      const cursor = this.cm.getCursor(), scroll = this.cm.getScrollInfo().top;
      this._loading = true;
      this.cm.setValue(text);
      this._loading = false;
      this.cm.setCursor(cursor);
      this.cm.scrollTo(null, scroll);
      this.syncTitle(null);
    }

    markSaved(path, text) {
      const entry = this.docs.get(path);
      if (entry) { entry.text = text; entry.dirty = false; }
    }

    indent(cm, back) {
      if (this.kind === "markdown") {
        const cmd = back ? "autoUnindentMarkdownList" : "autoIndentMarkdownList";
        if (CodeMirror.commands[cmd]) return CodeMirror.commands[cmd](cm);
      }
      if (back) return cm.execCommand("indentLess");
      if (cm.somethingSelected()) return cm.execCommand("indentMore");
      return cm.execCommand("insertTab");
    }

    toggleTask(index, checked) {
      // Case cochee depuis la lecture : la n-ieme case du texte (hors blocs de code).
      const doc = this.cm.getDoc();
      let count = -1, inFence = false;
      for (let i = 0; i < doc.lineCount(); i++) {
        const text = doc.getLine(i);
        if (/^\s*(`{3,}|~{3,})/.test(text)) inFence = !inFence;
        if (inFence) continue;
        const m = /^(\s*(?:[-*+]|\d+[.)])\s+\[)(.)\]/.exec(text);
        if (m && ++count === index) {
          doc.replaceRange(checked ? "x" : " ", { line: i, ch: m[1].length }, { line: i, ch: m[1].length + 1 }, "+task");
          return;
        }
      }
    }

    find() {
      const cm = this.cm;
      const initial = cm.getSelection() || this._query || "";
      cm.openDialog('<span>Rechercher :</span> <input type="text"/>', (query) => {
        this._query = query;
        this.findNext(1);
      }, { value: initial, closeOnEnter: true, selectValueOnOpen: true, bottom: false });
    }

    findNext(dir) {
      const cm = this.cm, query = this._query;
      if (!query) { this.find(); return; }
      let cursor = cm.getSearchCursor(query, dir > 0 ? cm.getCursor("to") : cm.getCursor("from"), { caseFold: true });
      let found = dir > 0 ? cursor.findNext() : cursor.findPrevious();
      if (!found) {
        cursor = cm.getSearchCursor(query, dir > 0 ? CodeMirror.Pos(cm.firstLine(), 0) : CodeMirror.Pos(cm.lastLine()), { caseFold: true });
        found = dir > 0 ? cursor.findNext() : cursor.findPrevious();
      }
      if (found) { cm.setSelection(cursor.from(), cursor.to()); cm.scrollIntoView({ from: cursor.from(), to: cursor.to() }, 80); }
      else MD.notice("« " + query + " » introuvable");
    }
  }

  MD.Editor = Editor;
  MD.scanBlocks = scanBlocks;
})();
