/* Module Markdown : TABLEAUX EDITABLES de l'edition visuelle (comme Obsidian).

   Un tableau Markdown est montre en vraies cellules. La cellule ACTIVE montre sa source dans un petit editeur
   CodeMirror (coloration « pfm ») ; les autres restent rendues (meme moteur que la lecture). Chaque frappe est ecrite
   AUSSITOT dans la note, a sa place exacte (une cellule = un morceau de ligne) : annulation / retablissement de la
   note, enregistrement, modifications exterieures marchent comme pour le reste du texte. Seule la cellule touchee
   change dans le fichier (alignements, echappements, liens, balises et espaces des autres cellules gardes).

   Clavier : Tab / Maj+Tab = cellule suivante / precedente (Tab sur la derniere = nouvelle ligne), Entree = cellule
   du dessous (nouvelle ligne en bas), Maj+Entree = <br>, fleches aux bords = cellule voisine ou sortie du tableau,
   Echap = sortie. « | » tape dans une cellule est echappe (« \| »), un saut de ligne colle devient <br>.
   Boutons « + » (bas / droite) et menu contextuel : lignes, colonnes, alignements, source.

   Modele : parseTable / splitRow (pur, teste), operations qui rendent des modifications {line, from, to, text}
   (lignes relatives au tableau). */
(function () {
  "use strict";
  const MD = window.MD = window.MD || {};

  // -- Modele -----------------------------------------------------------------------------------------------------
  /** Cellules d'une ligne : {from, to} = morceau entre deux barres ; {a, b} = contenu sans les espaces autour. */
  function splitRow(text) {
    const pipes = [];
    for (let i = 0; i < text.length; i++) {
      const ch = text.charCodeAt(i);
      if (ch === 92) { i++; continue; }          // \ : le caractere suivant est echappe
      if (ch === 124) pipes.push(i);
    }
    const first = text.search(/\S/);
    const lead = pipes.length > 0 && pipes[0] === first;
    let pos = lead ? pipes.shift() + 1 : 0;
    const cells = [];
    const seg = (from, to) => {
      const s = text.slice(from, to);
      const left = s.length - s.replace(/^\s+/, "").length;
      if (left === s.length) {
        const at = from + Math.min(1, s.length);  // cellule vide : apres une espace
        return { from, to, a: at, b: at, empty: true };
      }
      return { from, to, a: from + left, b: to - (s.length - s.replace(/\s+$/, "").length), empty: false };
    };
    for (const p of pipes) { cells.push(seg(pos, p)); pos = p + 1; }
    const trail = pos > 0 && !/\S/.test(text.slice(pos));
    if (!trail) cells.push(seg(pos, text.length));
    return { cells, lead, trail };
  }

  const DELIM_CELL = /^:?-+:?$/;

  /** Un tableau : lignes (sans la ligne de separation), colonnes, alignements ; valid = rendu en tableau. */
  function parseTable(text) {
    const lines = text.split("\n");
    const rows = [];
    const split = lines.map(splitRow);
    const delim = split[1] || { cells: [] };
    const cols = split[0] ? split[0].cells.length : 0;
    const aligns = delim.cells.map((c) => {
      const t = lines[1].slice(c.a, c.b);
      const l = t.startsWith(":"), r = t.endsWith(":");
      return l && r ? "center" : r ? "right" : l ? "left" : "";
    });
    const valid = lines.length >= 2 && cols > 0 && delim.cells.length === cols &&
      delim.cells.every((c) => DELIM_CELL.test(lines[1].slice(c.a, c.b)));
    for (let i = 0; i < lines.length; i++) {
      if (i === 1) continue;
      rows.push({ line: i, text: lines[i], cells: split[i].cells, lead: split[i].lead, trail: split[i].trail });
    }
    return { lines, rows, cols, aligns, valid, delim };
  }

  const lineOf = (r) => (r === 0 ? 0 : r + 1);

  function cellSource(model, r, c) {
    const row = model.rows[r];
    const cell = row && row.cells[c];
    return cell ? row.text.slice(cell.a, cell.b) : "";
  }

  /** « | » non echappe -> « \| », sauts de ligne -> <br> (une cellule tient sur une ligne). */
  function sanitize(value) {
    let out = "", run = 0;
    const text = String(value).replace(/\r?\n/g, "<br>");
    for (const ch of text) {
      if (ch === "|" && run % 2 === 0) out += "\\";
      out += ch;
      run = ch === "\\" ? run + 1 : 0;
    }
    return out;
  }

  function setCell(model, r, c, value) {
    value = sanitize(value);
    const row = model.rows[r];
    if (!row) return [];
    const line = lineOf(r), text = row.text;
    if (c < row.cells.length) {
      const cell = row.cells[c];
      if (!cell.empty) return [{ line, from: cell.a, to: cell.b, text: value }];
      if (cell.to - cell.from >= 2) return [{ line, from: cell.from + 1, to: cell.from + 1, text: value }];
      return [{ line, from: cell.from, to: cell.to, text: " " + value + " " }];
    }
    // Ligne trop courte : cellules ajoutees jusqu'a celle-ci.
    const end = text.replace(/\s+$/, "").length;
    const add = (row.trail ? "" : " |") + "   |".repeat(c - row.cells.length) + " " + value + " |";
    return [{ line, from: end, to: text.length, text: add }];
  }

  function emptyRow(model) {
    const head = model.rows[0];
    const body = new Array(model.cols).fill("  ").join("|");
    return (head.lead ? "|" : "") + body + (head.trail || head.lead ? "|" : "");
  }

  /** Nouvelle ligne AVANT la ligne « at » (1 = sous l'entete ; rows.length = a la fin). */
  function insertRow(model, at) {
    at = Math.max(1, Math.min(at, model.rows.length));
    const row = emptyRow(model);
    if (at < model.rows.length) return [{ line: lineOf(at), from: 0, to: 0, text: row + "\n" }];
    const last = model.lines.length - 1;
    return [{ line: last, from: model.lines[last].length, to: model.lines[last].length, text: "\n" + row }];
  }

  function deleteRow(model, r) {
    if (r < 1 || r >= model.rows.length) return [];
    const line = lineOf(r);
    if (line < model.lines.length - 1) return [{ line, from: 0, to: null, toLine: line + 1, text: "" }];
    return [{ line: line - 1, from: model.lines[line - 1].length, to: model.lines[line].length, toLine: line, text: "" }];
  }

  /** Nouvelle colonne AVANT la colonne « at » (cols = a la fin), sur toutes les lignes (separation comprise). */
  function insertColumn(model, at) {
    const out = [];
    for (let i = 0; i < model.lines.length; i++) {
      const text = model.lines[i];
      const { cells, trail } = splitRow(text);
      const fill = i === 1 ? "---" : " ";
      if (at < cells.length) out.push({ line: i, from: cells[at].from, to: cells[at].from, text: " " + fill + " |" });
      else if (at === cells.length) {
        const end = text.replace(/\s+$/, "").length;
        out.push({ line: i, from: end, to: end, text: trail ? " " + fill + " |" : " | " + fill });
      }
    }
    return out;
  }

  function deleteColumn(model, c) {
    if (model.cols <= 1) return [];
    const out = [];
    for (let i = 0; i < model.lines.length; i++) {
      const text = model.lines[i];
      const { cells, lead } = splitRow(text);
      if (c >= cells.length) continue;
      const cell = cells[c];
      if (c > 0 || lead) out.push({ line: i, from: cell.from - 1, to: cell.to, text: "" });
      else if (cell.to < text.length) out.push({ line: i, from: cell.from, to: cell.to + 1, text: "" });
    }
    return out;
  }

  function colorCells(model, axis, index, color, padding = "4px 8px") {
    if (!/^#(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(color)) return [];
    const edits = [];
    for (let r = 0; r < model.rows.length; r++) for (let c = 0; c < model.cols; c++) {
      if ((axis === "row" && r !== index) || (axis === "column" && c !== index)) continue;
      const value = cellSource(model, r, c)
        .replace(/^<span class="pb-table-cell-bg" style="[^"]*">([\s\S]*)<\/span>$/i, "$1")
        .replace(/^<span style="background-color:\s*#[0-9a-f]{3,8}">([\s\S]*)<\/span>$/i, "$1");
      const style = `--pb-table-cell-bg:${color};background-color:${color};display:block;width:100%;box-sizing:border-box;` +
        `padding:${padding};box-shadow:0 0 0 100vmax var(--pb-table-cell-bg)`;
      edits.push(...setCell(model, r, c, `<span class="pb-table-cell-bg" style="${style}">${value}</span>`));
    }
    return edits;
  }

  function setAlign(model, c, align) {
    const cell = model.delim.cells[c];
    if (!cell) return [];
    const dashes = Math.max(3, model.lines[1].slice(cell.a, cell.b).replace(/:/g, "").length);
    const bar = "-".repeat(dashes);
    const text = align === "center" ? ":" + bar + ":" : align === "right" ? bar + ":" : align === "left" ? ":" + bar : bar;
    return [{ line: 1, from: cell.a, to: cell.b, text }];
  }

  /** Applique des modifications (lignes relatives) a un texte : pour les tests et les apercus. */
  function applyEdits(text, edits) {
    const lines = text.split("\n");
    const offsets = [];
    let at = 0;
    for (const l of lines) { offsets.push(at); at += l.length + 1; }
    const abs = (line, ch) => offsets[line] + ch;
    const sorted = edits.map((e) => ({ a: abs(e.line, e.from), b: e.toLine != null ?
      (e.to == null ? offsets[e.toLine] : abs(e.toLine, e.to)) : abs(e.line, e.to), text: e.text }))
      .sort((x, y) => y.a - x.a);
    for (const e of sorted) text = text.slice(0, e.a) + e.text + text.slice(e.b);
    return text;
  }

  MD.tableModel = { splitRow, parseTable, sanitize, setCell, insertRow, deleteRow, insertColumn, deleteColumn,
    setAlign, colorCells, applyEdits, cellSource };

  // -- Widget ---------------------------------------------------------------------------------------------------------
  const PLUS = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>';

  const WRITE_DELAY_MS = 250;

  class TableWidget {
    constructor(lp, text) {
      this.lp = lp;
      this.cm = lp.cm;
      this.text = null;
      this.model = null;
      this.marker = null;
      this.active = null;          // {r, c}
      this.nested = null;
      this._silent = false;
      this._menu = false;
      const el = this.el = document.createElement("div");
      el.className = "md-block md-rendered md-block-table cm-embed-block cm-table-widget markdown-rendered";
      el.setAttribute("cm-ignore-events", "true");
      // Les evenements de la cellule active ne doivent pas atteindre l'editeur de la note (il relirait son DOM).
      for (const type of ["keydown", "keypress", "keyup", "input", "compositionstart", "compositionupdate",
        "compositionend", "paste", "copy", "cut", "beforeinput", "dragstart", "drop"]) {
        el.addEventListener(type, (ev) => ev.stopPropagation());
      }
      el.addEventListener("mousedown", (ev) => this.onMouseDown(ev));
      el.addEventListener("contextmenu", (ev) => this.onContextMenu(ev));
      this.update(text);
    }

    // -- Place dans la note --------------------------------------------------------------------------------------
    /** Lignes du tableau dans la note : debut = celui du widget, fin relue (une ligne ajoutee a la fin est hors du
        widget jusqu'a son prochain recalage). */
    range() {
      const f = this.marker && this.marker.find();
      if (!f) return null;
      const doc = this.cm.getDoc(), n = doc.lineCount();
      let to = Math.min(f.from.line + 1, n - 1);
      while (to + 1 < n && doc.getLine(to + 1).indexOf("|") >= 0 && doc.getLine(to + 1).trim() !== "") to++;
      return { from: f.from.line, to };
    }

    docText() {
      const r = this.range();
      if (!r) return this.text;
      const doc = this.cm.getDoc();
      return doc.getRange({ line: r.from, ch: 0 }, { line: r.to, ch: doc.getLine(r.to).length });
    }

    /** Ecrit des modifications dans la note (une etape d'annulation, groupee avec la frappe). */
    apply(edits, origin) {
      const r = this.range();
      if (!r || !edits.length) return false;
      const doc = this.cm.getDoc();
      const sorted = edits.slice().sort((x, y) => (y.line - x.line) || (y.from - x.from));
      const hadFocus = this.nested && this.nested.hasFocus();
      this.cm.operation(() => {
        for (const e of sorted) {
          const line = r.from + e.line;
          const from = { line, ch: e.from };
          const to = e.toLine != null ? (e.to == null ? { line: r.from + e.toLine, ch: 0 } : { line: r.from + e.toLine, ch: e.to })
            : { line, ch: e.to };
          doc.replaceRange(e.text, from, to, origin || "+table");
        }
      });
      // La ligne de l'editeur est redessinee : le widget est replace dans la page, la cellule garde la main.
      if (hadFocus) this.focusActive();
      return true;
    }

    // -- Rendu --------------------------------------------------------------------------------------------------
    update(text) {
      if (text === this.text) return true;
      const old = this.model;
      const model = parseTable(text);
      this.text = text;
      this.model = model;
      if (!model.valid) return false;
      const same = old && old.valid && this.table && old.rows.length === model.rows.length && old.cols === model.cols;
      if (!same) {
        const keep = this.active && { r: this.active.r, c: this.active.c, at: this.caret() };
        this.deactivate(true);
        this.build();
        this.paint(null);
        if (keep && keep.r < model.rows.length && keep.c < model.cols) this.activate(keep.r, keep.c, keep.at);
        return true;
      }
      for (let c = 0; c < model.cols; c++) {
        if (old.aligns[c] !== model.aligns[c]) {
          for (const row of this.table.rows) if (row.cells[c]) row.cells[c].style.textAlign = model.aligns[c] || "";
        }
      }
      const dirty = new Set();
      for (let r = 0; r < model.rows.length; r++) {
        for (let c = 0; c < model.cols; c++) {
          const src = cellSource(model, r, c);
          if (src === cellSource(old, r, c)) continue;
          if (this.active && this.active.r === r && this.active.c === c) {
            if (this.nested && sanitize(this.nested.getValue()).trim() !== src) {
              clearTimeout(this._timer);
              this._pending = false;                 // la note a change ailleurs (annulation, fichier) : elle gagne
              const at = Math.min(this.caret(), src.length);
              this._silent = true;
              this.nested.setValue(src);
              this.nested.setCursor(0, at);
              this._silent = false;
            }
          } else dirty.add(r + ":" + c);
        }
      }
      if (dirty.size) this.paint(dirty);
      return true;
    }

    build() {
      const m = this.model;
      const wrap = document.createElement("div");
      wrap.className = "table-wrapper";
      const table = this.table = document.createElement("table");
      table.className = "table-editor";
      const head = table.createTHead().insertRow();
      const body = m.rows.length > 1 ? table.createTBody() : null;
      for (let r = 0; r < m.rows.length; r++) {
        const tr = r === 0 ? head : body.insertRow();
        for (let c = 0; c < m.cols; c++) {
          const cell = document.createElement(r === 0 ? "th" : "td");
          if (m.aligns[c]) cell.style.textAlign = m.aligns[c];
          const inner = document.createElement("div");
          inner.className = "table-cell-wrapper";
          inner.textContent = cellSource(m, r, c);   // en attendant le rendu
          cell.appendChild(inner);
          tr.appendChild(cell);
        }
      }
      wrap.appendChild(table);
      const col = document.createElement("div");
      col.className = "table-col-btn";
      col.title = "Ajouter une colonne";
      col.innerHTML = PLUS;
      const row = document.createElement("div");
      row.className = "table-row-btn";
      row.title = "Ajouter une ligne";
      row.innerHTML = PLUS;
      wrap.append(col, row);
      // Tirer le « + » vers l'interieur retire les dernieres colonnes/lignes ; un clic simple conserve l'ajout.
      this.bindShrink(col, "column");
      this.bindShrink(row, "row");
      const source = document.createElement("div");
      source.className = "md-edit-block";
      source.textContent = "</>";
      source.title = "Modifier la source du tableau";
      this.el.replaceChildren(wrap, source);
    }

    bindShrink(handle, axis) {
      handle.addEventListener("pointerdown", (ev) => {
        if (ev.button !== 0) return;
        const start = axis === "column" ? ev.clientX : ev.clientY;
        let delta = 0;
        const move = (e) => { delta = (axis === "column" ? e.clientX : e.clientY) - start; };
        const done = () => {
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", done);
          if (delta >= -18) return;
          const cell = axis === "column" ? this.table.rows[0].cells[this.model.cols - 1] : this.table.rows[this.model.rows.length - 1];
          const unit = axis === "column" ? (cell && cell.getBoundingClientRect().width || 60) : (cell && cell.getBoundingClientRect().height || 28);
          const count = Math.max(1, Math.floor(-delta / Math.max(1, unit)));
          this._skipAdd = true;
          for (let i = 0; i < count; i++) {
            if (axis === "column") { if (this.model.cols <= 1 || !this.edit(deleteColumn, this.model.cols - 1)) break; }
            else { if (this.model.rows.length <= 1 || !this.edit(deleteRow, this.model.rows.length - 1)) break; }
          }
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", done, { once: true });
      });
    }

    cellEl(r, c) {
      const row = this.table && this.table.rows[r];
      return row ? row.cells[c] : null;
    }

    /** Rendu des cellules (toutes, ou celles de « only ») ; la cellule active garde sa source. */
    paint(only) {
      const text = this.text;
      const fill = (html) => {
        if (this.text !== text || !this.table) return;
        const holder = document.createElement("div");
        holder.innerHTML = html;
        const table = holder.querySelector("table");
        if (!table) return;
        if (MD.fixRelative) MD.fixRelative(table);
        for (let r = 0; r < this.model.rows.length; r++) {
          for (let c = 0; c < this.model.cols; c++) {
            if (only && !only.has(r + ":" + c)) continue;
            if (this.active && this.active.r === r && this.active.c === c) continue;
            const src = table.rows[r] && table.rows[r].cells[c];
            const cell = this.cellEl(r, c);
            if (cell) {
              cell.firstChild.innerHTML = src ? src.innerHTML : "";
              const marker = cell.firstChild.querySelector(".pb-table-cell-bg");
              cell.style.backgroundColor = marker ? marker.style.backgroundColor : "";
              if (marker) {
                cell.style.padding = "0";
                cell.style.overflow = "hidden";
                marker.style.display = "block";
                marker.style.width = "100%";
                marker.style.boxSizing = "border-box";
              } else {
                cell.style.padding = "";
                cell.style.overflow = "";
              }
            }
          }
        }
      };
      const cached = MD.renderCachedHtml && MD.renderCachedHtml(text);
      if (cached != null) { fill(cached); return; }
      if (only) {
        for (const key of only) {
          const [r, c] = key.split(":").map(Number);
          const cell = this.cellEl(r, c);
          if (cell) cell.firstChild.textContent = cellSource(this.model, r, c);
        }
      }
      if (MD.renderHtml) MD.renderHtml(text).then(fill).catch(() => {});
    }

    // -- Cellule active -----------------------------------------------------------------------------------------
    caret() {
      return this.nested ? this.nested.getCursor().ch : 0;
    }

    /** Active une cellule ; « where » = position dans la source (nombre), "end", ou {x, y} (clic). */
    activate(r, c, where) {
      const m = this.model;
      if (!m || !m.valid) return;
      r = Math.max(0, Math.min(r, m.rows.length - 1));
      c = Math.max(0, Math.min(c, m.cols - 1));
      if (!(this.active && this.active.r === r && this.active.c === c && this.nested)) {
        this.deactivate(true);
        const cell = this.cellEl(r, c);
        if (!cell) return;
        this.active = { r, c };
        cell.classList.add("is-active-cell");
        const inner = cell.firstChild;
        inner.textContent = "";
        const nested = this.nested = CodeMirror(inner, {
          value: cellSource(m, r, c), mode: { name: "pfm", xml: true }, theme: "obsidian", lineWrapping: true, scrollbarStyle: "null",
          viewportMargin: Infinity, spellcheck: false, undoDepth: 1, cursorScrollMargin: 0,
          extraKeys: this.keys()
        });
        nested.getWrapperElement().classList.add("md-cell-editor");
        nested.on("beforeChange", (inst, change) => {
          if (this._silent || change.origin === "setValue") return;
          const typed = change.text.join("\n");
          const clean = sanitize(typed);
          // « \| » deja tape en deux temps : la barre precedee d'une barre oblique reste telle quelle.
          const before = inst.getRange({ line: 0, ch: Math.max(0, change.from.ch - 1) }, change.from);
          const fixed = before === "\\" && typed === "|" ? typed : clean;
          if (fixed !== typed) change.update(change.from, change.to, [fixed]);
        });
        // La frappe ne touche que la cellule ; la note la recoit apres une courte pause (ou avant tout ce qui la
        // lit : changement de cellule, annulation, enregistrement) — l'ecrire a chaque touche faisait retokeniser
        // tout le tableau par l'editeur de la note (~11 ms par touche sur 60 lignes).
        nested.on("changes", () => {
          if (this._silent) return;
          this._pending = true;
          clearTimeout(this._timer);
          this._timer = setTimeout(() => this.flush(), WRITE_DELAY_MS);
          this.lp.host.edited();
        });
        nested.on("blur", () => setTimeout(() => this.onBlur(), 0));
        nested.refresh();
      }
      const nested = this.nested;
      if (where && typeof where === "object") nested.setCursor(nested.coordsChar({ left: where.x, top: where.y }, "window"));
      else if (where === "end") nested.setCursor(0, nested.getLine(0).length);
      else if (typeof where === "number") nested.setCursor(0, Math.min(where, nested.getLine(0).length));
      this.focusActive();
      this.el.classList.add("has-focus");
      this.lp.tableActivated(this);
    }

    focusActive() {
      if (this.nested) this.nested.focus();
    }

    /** Ecrit dans la note ce qui a ete tape dans la cellule active et pas encore ecrit. */
    flush() {
      clearTimeout(this._timer);
      if (!this._pending) return;
      this._pending = false;
      if (this.nested) this.write(this.nested.getValue());
    }

    deactivate(silent) {
      if (!this.active) return;
      this.flush();
      const { r, c } = this.active;
      this.active = null;
      const nested = this.nested;
      this.nested = null;
      this.el.classList.remove("has-focus");
      const cell = this.cellEl(r, c);
      if (cell) {
        cell.classList.remove("is-active-cell");
        cell.firstChild.textContent = cellSource(this.model, r, c);
        this.paint(new Set([r + ":" + c]));
      }
      if (nested) nested.getWrapperElement().remove();
      if (!silent) this.lp.tableActivated(null);
    }

    onBlur() {
      if (this._menu || !this.nested) return;
      const focused = document.activeElement;
      if (focused && this.el.contains(focused) && this.nested.hasFocus()) return;
      // Le widget a ete replace dans la page (ligne redessinee) : la cellule reprend la main.
      if (this._refocusing) return;
      if (!document.hasFocus()) return;           // fenetre quittee (menu, autre appli) : la cellule reste active
      this.deactivate(false);
    }

    write(value) {
      if (!this.active) return;
      const current = parseTable(this.docText());
      if (!current.valid) return;
      const { r, c } = this.active;
      value = sanitize(value).trim();            // espaces autour d'une cellule : sans effet en Markdown
      if (cellSource(current, r, c) === value) return;
      const edits = setCell(current, r, c, value);
      this._refocusing = true;
      this.apply(edits);
      this._refocusing = false;
      this.syncText();
    }

    /** Le texte du widget suit la note sans rien redessiner (c'est la cellule active qui l'a change). */
    syncText() {
      const text = this.docText();
      const model = parseTable(text);
      if (model.valid && this.model && model.rows.length === this.model.rows.length && model.cols === this.model.cols) {
        this.text = text;
        this.model = model;
      }
    }

    keys() {
      const move = (dr, dc, where) => () => this.go(dr, dc, where);
      return {
        "Tab": () => this.next(1), "Shift-Tab": () => this.next(-1),
        "Enter": () => this.down(), "Shift-Enter": (cm) => cm.replaceSelection("<br>"),
        "Up": (cm) => this.vertical(cm, -1), "Down": (cm) => this.vertical(cm, 1),
        "Left": (cm) => this.horizontal(cm, -1), "Right": (cm) => this.horizontal(cm, 1),
        "Esc": () => this.exit(1),
        "Ctrl-Z": () => this.history("undo"), "Ctrl-Y": () => this.history("redo"),
        "Shift-Ctrl-Z": () => this.history("redo"),
        "Ctrl-B": (cm) => wrap(cm, "**"), "Ctrl-I": (cm) => wrap(cm, "*"),
        "Ctrl-A": (cm) => cm.execCommand("selectAll"),
        "Alt-Up": move(-1, 0, 0), "Alt-Down": move(1, 0, 0)
      };
    }

    go(dr, dc, where) {
      const { r, c } = this.active;
      this.activate(r + dr, c + dc, where);
    }

    next(dir) {
      const { r, c } = this.active;
      const m = this.model;
      let nr = r, nc = c + dir;
      if (nc >= m.cols) { nr++; nc = 0; }
      if (nc < 0) { nr--; nc = m.cols - 1; }
      if (nr < 0) return this.exit(-1);
      if (nr >= m.rows.length) {
        this.addRow(m.rows.length);
        return this.activate(m.rows.length, 0, 0);
      }
      this.activate(nr, nc, "end");
    }

    down() {
      const { r, c } = this.active;
      if (r + 1 >= this.model.rows.length) this.addRow(this.model.rows.length);
      this.activate(r + 1, c, "end");
    }

    vertical(cm, dir) {
      const cur = cm.cursorCoords(null, "local");
      const edge = dir < 0 ? cm.charCoords({ line: 0, ch: 0 }, "local").top
        : cm.charCoords({ line: 0, ch: cm.getLine(0).length }, "local").top;
      if (Math.abs(cur.top - edge) > 2) return CodeMirror.Pass;   // retour a la ligne : on reste dans la cellule
      const { r, c } = this.active;
      if (r + dir < 0) return this.exit(-1);
      if (r + dir >= this.model.rows.length) return this.exit(1);
      const x = cm.cursorCoords(null, "window").left;
      this.activate(r + dir, c, 0);
      const target = this.nested;
      const box = target.getWrapperElement().getBoundingClientRect();
      target.setCursor(target.coordsChar({ left: x, top: dir < 0 ? box.bottom - 2 : box.top + 2 }, "window"));
    }

    horizontal(cm, dir) {
      if (cm.somethingSelected()) return CodeMirror.Pass;
      const ch = cm.getCursor().ch;
      if (dir < 0 ? ch > 0 : ch < cm.getLine(0).length) return CodeMirror.Pass;
      const { r, c } = this.active;
      const m = this.model;
      if (dir < 0) {
        if (c > 0) return this.activate(r, c - 1, "end");
        if (r > 0) return this.activate(r - 1, m.cols - 1, "end");
        return this.exit(-1);
      }
      if (c + 1 < m.cols) return this.activate(r, c + 1, 0);
      if (r + 1 < m.rows.length) return this.activate(r + 1, 0, 0);
      return this.exit(1);
    }

    /** Annuler / retablir : l'historique de la note (la cellule suit son texte). */
    history(kind) {
      this.flush();
      this.cm.getDoc()[kind]();
      const r = this.range();
      if (r && this.active) {
        this.update(this.docText());
        if (this.nested) this.focusActive();
      }
    }

    /** Sortie du tableau : curseur de la note juste avant (dir < 0) ou juste apres (dir > 0). */
    exit(dir) {
      this.flush();
      const r = this.range();
      this.deactivate(true);
      this.lp.tableActivated(null);
      if (!r) return;
      const cm = this.cm, doc = cm.getDoc();
      this.lp.skipTableEntry = true;
      cm.operation(() => {
        if (dir < 0) {
          if (r.from === 0) doc.replaceRange("\n", { line: 0, ch: 0 }, null, "+table");
          const line = Math.max(0, (r.from === 0 ? 1 : r.from) - 1);
          cm.setCursor({ line, ch: doc.getLine(line).length });
        } else {
          if (r.to >= doc.lastLine()) doc.replaceRange("\n", { line: r.to, ch: doc.getLine(r.to).length }, null, "+table");
          cm.setCursor({ line: r.to + 1, ch: 0 });
        }
      });
      cm.focus();
      this.lp.skipTableEntry = false;
    }

    // -- Lignes et colonnes ---------------------------------------------------------------------------------------
    edit(fn, ...args) {
      this.flush();
      const model = parseTable(this.docText());
      if (!model.valid) return false;
      const edits = fn(model, ...args);
      if (!edits.length) return false;
      this.apply(edits, "table");
      this.update(this.docText());
      return true;
    }

    addRow(at) { return this.edit(insertRow, at); }
    addColumn(at) { return this.edit(insertColumn, at); }

    // -- Souris ---------------------------------------------------------------------------------------------------
    onMouseDown(ev) {
      ev.stopPropagation();
      if (ev.button !== 0) return;
      const t = ev.target;
      if (t.closest(".table-row-btn")) {
        if (this._skipAdd) { this._skipAdd = false; return; }
        ev.preventDefault();
        const n = this.model.rows.length;
        this.addRow(n);
        this.activate(n, 0, 0);
        return;
      }
      if (t.closest(".table-col-btn")) {
        if (this._skipAdd) { this._skipAdd = false; return; }
        ev.preventDefault();
        const n = this.model.cols;
        this.addColumn(n);
        this.activate(0, n, 0);
        return;
      }
      if (t.closest(".md-edit-block")) {
        ev.preventDefault();
        this.showSource();
        return;
      }
      const cell = t.closest("th, td");
      if (!cell || !this.table || !this.table.contains(cell)) return;
      if (cell.classList.contains("is-active-cell")) return;      // l'editeur de la cellule gere le clic
      const link = t.closest("a");
      if (link) {
        ev.preventDefault();
        if (link.dataset.href != null) MD.openLink(link.dataset.href);
        else {
          const href = link.getAttribute("href") || "";
          if (/^[a-z][\w+.-]*:/i.test(href)) MD.call("openExternal", href);
        }
        return;
      }
      ev.preventDefault();
      const r = cell.parentElement.rowIndex, c = cell.cellIndex;
      this.activate(r, c, { x: ev.clientX, y: ev.clientY });
    }

    showSource() {
      this.flush();
      const r = this.range();
      if (!r) return;
      this.deactivate(false);
      this.lp.revealTable(this, r);
    }

    async onContextMenu(ev) {
      const cell = ev.target.closest("th, td");
      if (!cell || !this.table || !this.table.contains(cell)) return;
      ev.preventDefault();
      ev.stopPropagation();
      const r = cell.parentElement.rowIndex, c = cell.cellIndex;
      const m = this.model;
      const entries = [
        { title: "Insérer une ligne au-dessus" }, { title: "Insérer une ligne en dessous" },
        { title: "Insérer une colonne à gauche" }, { title: "Insérer une colonne à droite" }, "-",
        { title: "Supprimer la ligne" }, { title: "Supprimer la colonne" }, "-",
        { title: "Aligner à gauche" }, { title: "Centrer" }, { title: "Aligner à droite" },
        { title: "Sans alignement" }, "-", { title: "Changer la couleur de la ligne" },
        { title: "Changer la couleur de la colonne" }, "-", { title: "Modifier la source du tableau" }
      ];
      this._menu = true;
      let index = -1;
      try { index = await MD.menu(entries, ev.clientX, ev.clientY); } finally { this._menu = false; }
      switch (index) {
        case 0: if (r > 0) { this.addRow(r); this.activate(r, c, 0); } break;
        case 1: this.addRow(r + 1); this.activate(r + 1, c, 0); break;
        case 2: this.addColumn(c); this.activate(r, c, 0); break;
        case 3: this.addColumn(c + 1); this.activate(r, c + 1, 0); break;
        case 4: if (r > 0 && this.edit(deleteRow, r)) this.activate(Math.min(r, this.model.rows.length - 1), c, 0); break;
        case 5: if (m.cols > 1 && this.edit(deleteColumn, c)) this.activate(r, Math.min(c, this.model.cols - 1), 0); break;
        case 6: case 7: case 8: case 9:
          this.edit(setAlign, c, ["left", "center", "right", ""][index - 6]); break;
        case 10: this.changeColor("row", r, getComputedStyle(cell).padding); break;
        case 11: this.changeColor("column", c, getComputedStyle(cell).padding); break;
        case 12: this.showSource(); break;
        default: if (this.nested) this.focusActive();
      }
    }

    changeColor(axis, index, padding) {
      const label = axis === "row" ? "Couleur d'arrière-plan de la ligne (#RRGGBB)" : "Couleur d'arrière-plan de la colonne (#RRGGBB)";
      MD.prompt(label, "#334155", (color) => {
        if (!color) return;
        if (!/^#(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(color.trim())) { MD.notice("Couleur attendue : #RRGGBB"); return; }
        MD.call("ensureTableCellBackgroundCss").catch(() => false).finally(() =>
          this.edit(colorCells, axis, index, color.trim(), padding));
      });
    }

    destroy() {
      this.deactivate(true);
    }
  }

  function wrap(cm, mark) {
    const sel = cm.getSelection();
    if (sel.startsWith(mark) && sel.endsWith(mark) && sel.length >= 2 * mark.length) {
      cm.replaceSelection(sel.slice(mark.length, sel.length - mark.length), "around");
    } else {
      cm.replaceSelection(mark + sel + mark, "around");
      if (!sel) { const p = cm.getCursor(); cm.setCursor(0, p.ch - mark.length); }
    }
  }

  MD.TableWidget = TableWidget;
})();
