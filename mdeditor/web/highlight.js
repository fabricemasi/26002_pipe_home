/* Module Markdown : langage d'un fichier ou d'un bloc de code, et coloration HORS editeur (mode lecture, apercu de
   l'inspecteur) avec les MEMES modes CodeMirror que l'edition : memes classes cm-*, donc memes couleurs (variables
   --md-syntax-* des reglages). */
(function () {
  "use strict";
  const MD = window.MD = window.MD || {};

  // Extensions absentes de la table de CodeMirror (meta.min.js) ou a classer autrement.
  const EXT_MODES = {
    vex: "text/x-csrc", vfl: "text/x-csrc", osl: "text/x-csrc", h: "text/x-csrc", hh: "text/x-c++src",
    hpp: "text/x-c++src", glsl: "text/x-c++src", hlsl: "text/x-c++src", mel: "text/x-csrc", cs: "text/x-csharp",
    ts: "text/typescript", tsx: "text/typescript-jsx", json: "application/json", jsonc: "application/json",
    ini: "text/x-properties", cfg: "text/x-properties", conf: "text/x-properties", env: "text/x-properties",
    toml: "text/x-toml", nk: "text/x-tcl", usda: "text/plain", rs: "text/x-rustsrc", ps1: "application/x-powershell",
    bat: "text/plain", cmd: "text/plain", txt: "text/plain", log: "text/plain", csv: "text/plain", tsv: "text/plain"
  };
  // Alias courants des blocs de code (```py, ```sh...) que la table ne connait pas sous ce nom.
  const ALIASES = { py: "python", sh: "shell", bash: "shell", zsh: "shell", ps: "powershell", ps1: "powershell",
    js: "javascript", ts: "typescript", yml: "yaml", md: "markdown", vex: "c", hlsl: "c++", glsl: "c++", cs: "c#",
    rs: "rust", h: "c", hpp: "c++", cpp: "c++", ini: "properties", conf: "properties", toml: "toml", html: "html",
    xml: "xml", json: "json", bat: "text", cmd: "text" };

  function usable(spec) {
    if (!spec) return null;
    const mode = typeof spec === "string" ? (CodeMirror.mimeModes[spec] || spec) : spec;
    const name = typeof mode === "string" ? mode : mode.name;
    return CodeMirror.modes[name] ? spec : null;
  }

  /** Mode CodeMirror d'une extension de fichier (texte brut si inconnu). */
  MD.modeForExtension = function (ext) {
    ext = String(ext || "").toLowerCase().replace(/^\./, "");
    if (EXT_MODES[ext]) return usable(EXT_MODES[ext]) || "text/plain";
    const info = CodeMirror.findModeByExtension && CodeMirror.findModeByExtension(ext);
    return (info && usable(info.mime || info.mode)) || "text/plain";
  };

  /** Mode CodeMirror du langage d'un bloc de code (```python), null si inconnu. */
  MD.modeForLanguage = function (lang) {
    lang = String(lang || "").trim().toLowerCase();
    if (!lang) return null;
    const name = ALIASES[lang] || lang;
    let info = CodeMirror.findModeByName && CodeMirror.findModeByName(name);
    if (!info && CodeMirror.findModeByExtension) info = CodeMirror.findModeByExtension(lang);
    if (info) return usable(info.mime || info.mode);
    return EXT_MODES[lang] ? usable(EXT_MODES[lang]) : null;
  };

  // Classes de Prism (coloration du mode lecture d'Obsidian) en plus : « .token.comment » d'une feuille d'Obsidian
  // vise les memes morceaux que « .cm-comment ».
  const PRISM = { comment: "comment", keyword: "keyword", string: "string", "string-2": "string", number: "number",
    atom: "boolean", def: "function", "variable-2": "variable", "variable-3": "variable", type: "class-name",
    builtin: "builtin", operator: "operator", property: "property", tag: "tag", attribute: "attr-name", meta: "important",
    bracket: "punctuation", punctuation: "punctuation" };
  function prismClasses(style) {
    const names = style.split(/ +/).map((s) => PRISM[s]).filter(Boolean);
    return names.length ? " token " + names.join(" ") : "";
  }

  /** Colore `text` avec le mode `spec` dans l'element `target` (spans « cm-<style> »). */
  MD.runMode = function (text, spec, target) {
    const mode = CodeMirror.getMode(CodeMirror.defaults, spec);
    const frag = document.createDocumentFragment();
    let state = CodeMirror.startState(mode);
    const lines = CodeMirror.splitLines(text);
    const append = (chunk, style) => {
      if (!chunk) return;
      if (!style) { frag.appendChild(document.createTextNode(chunk)); return; }
      const span = document.createElement("span");
      span.className = "cm-" + style.replace(/ +/g, " cm-") + prismClasses(style);
      span.textContent = chunk;
      frag.appendChild(span);
    };
    for (let i = 0; i < lines.length; i++) {
      if (i) frag.appendChild(document.createTextNode("\n"));
      const line = lines[i];
      if (!line) { if (mode.blankLine) mode.blankLine(state); continue; }
      const stream = new CodeMirror.StringStream(line, 4);
      let guard = 0;
      while (!stream.eol() && guard++ < 10000) {
        const style = mode.token(stream, state);
        append(stream.current(), style);
        stream.start = stream.pos;
      }
    }
    target.textContent = "";
    target.appendChild(frag);
  };

  /** Colore les blocs de code rendus (<pre><code class="language-x">) d'un conteneur. */
  MD.highlightAll = function (root) {
    if (typeof CodeMirror === "undefined") return;
    for (const code of root.querySelectorAll("pre > code[class*='language-']")) {
      if (code.dataset.mdHighlighted) continue;
      code.dataset.mdHighlighted = "1";
      const lang = (/language-([^\s]+)/.exec(code.className) || [, ""])[1];
      const spec = MD.modeForLanguage(lang);
      if (!spec) continue;
      try { MD.runMode(code.textContent.replace(/\n$/, ""), spec, code); } catch (err) { /* texte brut */ }
    }
  };
})();
