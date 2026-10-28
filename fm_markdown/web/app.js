/* Module Markdown : la page, reliee a Python par QWebChannel (objet « bridge »).

   Python fait tout ce qui touche au disque (lecture / ecriture fideles, rendu de lecture, resolution des liens),
   EN FOND ; la page ne fait qu'afficher et editer. Un fichier ouvert = un document CodeMirror garde en memoire avec
   son historique d'annulation ; la page n'est jamais rechargee (style, options et fichiers arrivent par messages).
   Modes : « edit » (CodeMirror, mis en forme par la feuille du module) et « reading » (rendu HTML). Les fichiers de
   code n'ont que le mode edition (coloration du langage). */
(function () {
  "use strict";
  const MD = window.MD = window.MD || {};

  MD.metrics = {
    data: {},
    add(name, ms) { (this.data[name] = this.data[name] || []).push(ms); if (this.data[name].length > 500) this.data[name].shift(); },
    take() { const d = this.data; this.data = {}; return d; }
  };

  // -- Pont avec Python -----------------------------------------------------------------------------------------
  let seq = 0;
  const waiting = new Map();
  MD.call = function (name, ...args) {
    return new Promise((resolve, reject) => {
      if (!MD.bridge) { reject(new Error("pont absent")); return; }
      const id = ++seq;
      waiting.set(id, { resolve, reject });
      MD.bridge.request(id, name, JSON.stringify(args));
    });
  };
  function onReply(id, payload) {
    const entry = waiting.get(id);
    if (!entry) return;
    waiting.delete(id);
    let data;
    try { data = JSON.parse(payload); } catch (err) { entry.reject(err); return; }
    if (data && data.__error__) entry.reject(new Error(data.__error__)); else entry.resolve(data);
  }

  // -- Etat ---------------------------------------------------------------------------------------------------------
  const S = MD.state = { options: {}, current: null, mode: "edit", names: {}, sendTimer: null, rendered: null };
  const $ = (id) => document.getElementById(id);

  MD.notice = function (text) {
    const el = $("md-notice");
    el.textContent = text;
    el.classList.add("is-shown");
    clearTimeout(MD._noticeTimer);
    MD._noticeTimer = setTimeout(() => el.classList.remove("is-shown"), 2600);
  };

  /** Menu contextuel de l'appli (Python) sous le point (x, y) de la page ; rend l'indice choisi ou -1. */
  MD.menu = function (entries, x, y) {
    return MD.call("menu", entries, x, y).then((i) => (typeof i === "number" ? i : -1)).catch(() => -1);
  };

  /** Petite saisie dans la page (outils de texte de la barre). */
  MD.prompt = function (label, value, done) {
    const box = document.createElement("div");
    box.className = "md-prompt";
    box.innerHTML = "<div></div><input type='text'>";
    box.firstChild.textContent = label;
    const input = box.lastChild;
    input.value = value || "";
    const close = (ok) => {
      box.remove();
      MD.editor.cm.focus();
      if (ok) done(input.value);
    };
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); close(true); }
      else if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); close(false); }
    });
    input.addEventListener("blur", () => setTimeout(() => box.isConnected && close(false), 0));
    document.body.appendChild(box);
    input.focus();
    input.select();
  };

  // -- Fichiers lies a la note : liens, images ---------------------------------------------------------------------
  function dirUrl() { return S.current ? S.current.dirUrl : ""; }

  /** Adresse d'un fichier vise depuis la note (image, lien) : relatif a la note, sinon par nom dans sa racine. */
  MD.resolveFile = function (target) {
    if (!target) return null;
    if (/^[a-z][\w+.-]*:/i.test(target)) return target;
    const clean = target.replace(/\\/g, "/").split("#")[0];
    const name = clean.slice(clean.lastIndexOf("/") + 1).toLowerCase();
    if (clean.indexOf("/") < 0) {
      const found = S.names[name] || S.names[name + ".md"];
      if (found) return found;
    }
    if (/^[a-zA-Z]:\//.test(clean)) return "file:///" + encodeURI(clean);
    return dirUrl() + clean.split("/").map(encodeURIComponent).join("/");
  };

  MD.fileExists = function (target) {
    const clean = String(target || "").replace(/\\/g, "/").split("#")[0];
    if (!clean) return true;
    const name = clean.slice(clean.lastIndexOf("/") + 1).toLowerCase();
    return !!(S.names[name] || S.names[name + ".md"]) || clean.indexOf("/") >= 0;
  };

  MD.openLink = function (target) {
    flushText();
    target = String(target || "");
    if (target.startsWith("#")) { MD.scrollToAnchor(target.slice(1)); return; }      // titre de la meme note
    MD.call("openLink", S.current ? S.current.path : "", target).then((r) => {
      if (r && r.error) MD.notice(r.error);
    }).catch((err) => MD.notice(err.message));
  };

  /** Va au titre « anchor » (ou au bloc « ^id ») de la note affichee, dans le mode en cours. */
  MD.scrollToAnchor = function (anchor) {
    const want = safeDecode(String(anchor || "")).replace(/^\^/, "").trim().toLowerCase();
    if (!want) return;
    if (S.mode === "reading") {
      const body = $("md-read-body");
      const heading = [...body.querySelectorAll("h1, h2, h3, h4, h5, h6")]
        .find((h) => h.textContent.trim().toLowerCase() === want);
      if (heading) $("md-read").scrollTop += heading.getBoundingClientRect().top - $("md-read").getBoundingClientRect().top - 16;
      return;
    }
    const cm = MD.editor.cm;
    for (let i = 0; i < cm.lineCount(); i++) {
      const text = cm.getLine(i);
      const h = /^#{1,6}\s+(.*?)\s*#*$/.exec(text);
      const plain = h ? h[1].replace(/[*_=`~]/g, "").trim().toLowerCase() : null;
      if (plain === want || (anchor.startsWith("^") && text.trim().endsWith("^" + want))) {
        cm.setCursor({ line: i, ch: 0 });
        cm.scrollTo(null, Math.max(0, cm.charCoords({ line: i, ch: 0 }, "local").top - 40));
        cm.focus();
        return;
      }
    }
    MD.notice("Titre « " + anchor + " » introuvable");
  };

  function safeDecode(text) {
    try { return decodeURIComponent(text); } catch (err) { return text; }
  }

  // Blocs rendus de l'edition (tableaux, callouts) : meme moteur que la lecture, garde par texte.
  const fragments = new Map();
  MD.renderFragment = function (text, el) {
    const key = (S.current ? S.current.path : "") + "\u0000" + text;
    const place = (html) => {
      const holder = document.createElement("div");
      holder.innerHTML = html;
      fixRelative(holder);
      MD.highlightAll(holder);
      el.prepend(...holder.childNodes);
    };
    if (fragments.has(key)) { place(fragments.get(key)); return; }
    el.insertAdjacentHTML("afterbegin", "<pre style='opacity:.5;margin:0'>" + MD.escapeHtml(text) + "</pre>");
    const pending = el.firstChild;
    MD.call("render", S.current ? S.current.path : "", text, false).then((html) => {
      if (fragments.size > 300) fragments.clear();
      fragments.set(key, html);
      if (pending.isConnected) pending.remove();
      place(html);
    }).catch(() => {});
  };

  /** Rendu HTML d'un morceau (meme cache que les blocs) : promesse ; renderCachedHtml = deja rendu, sinon null. */
  MD.renderCachedHtml = function (text) {
    const key = (S.current ? S.current.path : "") + "\u0000" + text;
    return fragments.has(key) ? fragments.get(key) : null;
  };
  MD.applyTableCellBackgrounds = function (root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll("td, th").forEach((cell) => {
      const marker = cell.querySelector(".pb-table-cell-bg");
      if (!marker) return;
      const color = marker.style.backgroundColor;
      if (!color) return;
      cell.style.backgroundColor = color;
      cell.style.padding = "0";
      cell.style.overflow = "hidden";
      marker.style.display = "block";
      marker.style.width = "100%";
      marker.style.boxSizing = "border-box";
    });
  };
  MD.renderHtml = function (text) {
    const key = (S.current ? S.current.path : "") + "\u0000" + text;
    if (fragments.has(key)) return Promise.resolve(fragments.get(key));
    return MD.call("render", S.current ? S.current.path : "", text, false).then((html) => {
      if (fragments.size > 300) fragments.clear();
      fragments.set(key, html);
      return html;
    });
  };
  MD.fixRelative = (root) => fixRelative(root);

  function fixRelative(root) {
    // Images ecrites en HTML dans la note (<img src="images/x.png">) : relatives au dossier de la note.
    for (const img of root.querySelectorAll("img[src]")) {
      const src = img.getAttribute("src");
      if (src && !/^[a-z][\w+.-]*:/i.test(src)) img.src = MD.resolveFile(decodeURIComponent(src));
    }
  }

  // -- Ouverture d'un fichier ----------------------------------------------------------------------------------------
  function open(info) {
    const t0 = performance.now();
    flushText();
    S.current = info;
    S.names = info.names || S.names;
    S.rendered = null;
    const md = info.kind === "markdown";
    $("md-read-title").textContent = info.title;
    MD.editor.open(info, S.options);
    S.anchor = info.anchor || null;              // lien « note#titre » : on y va une fois la note affichee
    setMode(md ? (info.mode || "edit") : "edit", { focus: true, keepScroll: false });
    MD.metrics.add("open", performance.now() - t0);
  }

  function setMode(mode, opts) {
    opts = opts || {};
    const md = S.current && S.current.kind === "markdown";
    if (!md) mode = "edit";
    const previous = S.mode;
    S.mode = mode;
    const edit = $("md-edit"), read = $("md-read");
    // Les deux vues ont chacune leur scroller natif. Entre elles, les hauteurs ne
    // sont pas identiques : la position proportionnelle est le seul repere stable.
    // Elle est lue une fois au changement de mode, jamais pendant le defilement.
    let ratio = 0;
    if (opts.keepScroll !== false && previous !== mode) {
      if (previous === "edit") {
        const info = MD.editor.cm.getScrollInfo();
        ratio = info.height > info.clientHeight ? info.top / (info.height - info.clientHeight) : 0;
      } else {
        ratio = read.scrollHeight > read.clientHeight ? read.scrollTop / (read.scrollHeight - read.clientHeight) : 0;
      }
    }
    edit.classList.toggle("is-shown", mode === "edit");
    read.classList.toggle("is-shown", mode === "reading");
    MD.toolbar.sync();
    if (mode === "edit") {
      MD.editor.shown();
      if (opts.keepScroll !== false && previous !== mode) {
        const info = MD.editor.cm.getScrollInfo();
        MD.editor.cm.scrollTo(null, ratio * Math.max(0, info.height - info.clientHeight));
      }
      if (opts.focus !== false) setTimeout(() => MD.editor.cm.focus(), 0);
      takeAnchor();
    } else {
      renderReading().then(() => {
        if (opts.keepScroll !== false && previous !== mode) read.scrollTop = ratio * Math.max(0, read.scrollHeight - read.clientHeight);
        else if (opts.keepScroll === false) read.scrollTop = 0;
        read.focus();
        takeAnchor();
      });
    }
    MD.call("modeChanged", mode).catch(() => {});
  }
  MD.setMode = setMode;

  function takeAnchor() {
    if (!S.anchor) return;
    const anchor = S.anchor;
    S.anchor = null;
    setTimeout(() => MD.scrollToAnchor(anchor), 0);
  }
  MD.toggleMode = () => setMode(S.mode === "edit" ? "reading" : "edit");

  function renderReading() {
    if (!S.current) return Promise.resolve();
    const text = MD.editor.getText();
    if (S.rendered === text) return Promise.resolve();
    const t0 = performance.now();
    const path = S.current.path;
    // Le rendu arrive en fond et remplace la page : la lecture reste ou elle etait (jamais renvoyee en haut).
    const read = $("md-read");
    const previousTop = read.scrollTop;
    return MD.call("render", path, text, true).then((html) => {
      if (!S.current || S.current.path !== path) return;
      const body = $("md-read-body");
      body.innerHTML = html;
      MD.applyTableCellBackgrounds(body);
      fixRelative(body);
      MD.highlightAll(body);
      S.rendered = text;
      if (S.mode === "reading") read.scrollTop = previousTop;
      MD.metrics.add("reading", performance.now() - t0);
    }).catch((err) => MD.notice(err.message));
  }

  // Lecture : liens, cases a cocher, callouts repliables.
  function onReadingClick(ev) {
    const box = ev.target.closest("input.task-list-item-checkbox");
    if (box) {
      const boxes = [...$("md-read-body").querySelectorAll("input.task-list-item-checkbox")];
      MD.editor.toggleTask(boxes.indexOf(box), box.checked);
      S.rendered = null;
      renderReading();
      return;
    }
    const title = ev.target.closest(".callout.is-collapsible > .callout-title");
    if (title) { title.parentElement.classList.toggle("is-collapsed"); return; }
    const a = ev.target.closest("a");
    if (!a) return;
    ev.preventDefault();
    if (a.classList.contains("tag")) return;
    if (a.dataset.href != null) { MD.openLink(a.dataset.href); return; }
    const href = a.getAttribute("href") || "";
    if (/^[a-z][\w+.-]*:/i.test(href)) MD.call("openExternal", href);
  }

  // -- Texte modifie : envoye a Python (qui enregistre 800 ms apres la frappe) ---------------------------------------
  function textChanged() {
    S.rendered = null;
    clearTimeout(S.sendTimer);
    S.sendTimer = setTimeout(flushText, 250);
  }

  function flushText() {
    if (!S.sendTimer || !S.current) return;
    clearTimeout(S.sendTimer);
    S.sendTimer = null;
    MD.call("changed", S.current.path, MD.editor.getText()).catch(() => {});
  }
  MD.flushText = flushText;
  MD.currentText = () => (S.current ? [S.current.path, MD.editor.getText()] : null);

  // -- Messages de Python ----------------------------------------------------------------------------------------------
  function applyStyle(message) {
    let tag = $("md-vars");
    tag.textContent = message.css;
    if (message.theme) {
      document.body.classList.toggle("theme-dark", message.theme === "theme-dark");
      document.body.classList.toggle("theme-light", message.theme === "theme-light");
    }
    if (message.options) {
      S.options = message.options;
      if (MD.editor && S.current) MD.editor.applyOptions(S.options);
    }
    if (MD.toolbar) MD.toolbar.sync();
    // Dimensions changees (police, taille, espacements) : l'editeur remesure ses lignes ; une couleur seule, non.
    if (MD.editor && message.layout !== false) MD.editor.styleChanged();
  }

  function onPush(text) {
    let message;
    try { message = JSON.parse(text); } catch (err) { return; }
    switch (message.type) {
      case "style": applyStyle(message); break;
      case "userCss": {
        // Feuille choisie (Reglages > Markdown > CSS), couche « md-user » : chargee sans recharger la page.
        const tag = $("md-user-css");
        if (tag.textContent !== message.rule) tag.textContent = message.rule;
        setTimeout(() => MD.editor && MD.editor.styleChanged(), 60);
        break;
      }
      case "managedCss": {
        // Bloc synchronise de la feuille partagee (reglages en cours, avant leur ecriture) : apres la feuille.
        const tag = $("md-managed");
        if (tag.textContent !== message.css) {
          tag.textContent = message.css;
          if (MD.editor) MD.editor.styleChanged(true);       // marques des listes remesurees, rien d autre
        }
        break;
      }
      case "toolbar": MD.toolbar.configure(message.data); MD.toolbar.sync(); break;
      case "open": open(message.info); break;
      case "names": if (S.current && message.path === S.current.path) { S.names = message.names; MD.editor.lp.invalidate(); MD.editor.requestImageSizes(); } break;
      case "mode": setMode(message.mode); break;
      case "toggleMode": MD.toggleMode(); break;
      case "reload":
        MD.editor.reloadText(message.path, message.text);
        if (S.current && S.current.path === message.path && S.mode === "reading") { S.rendered = null; renderReading(); }
        break;
      case "saved": MD.editor.markSaved(message.path, message.text); break;
      case "find": if (S.mode === "edit") MD.editor.find(); break;
      case "focus": if (S.mode === "edit") MD.editor.cm.focus(); else $("md-read").focus(); break;
      case "notice": MD.notice(message.text); break;
      case "anchor": MD.scrollToAnchor(message.anchor); break;
    }
  }

  // -- Clavier, souris -------------------------------------------------------------------------------------------------
  function onKey(ev) {
    const ctrl = ev.ctrlKey || ev.metaKey;
    if (ctrl && !ev.shiftKey && !ev.altKey && ev.key.toLowerCase() === "s") {
      ev.preventDefault(); flushText(); MD.call("save"); return;
    }
    if (ctrl && !ev.shiftKey && !ev.altKey && ev.key.toLowerCase() === "e") { ev.preventDefault(); MD.toggleMode(); return; }
    if (ev.altKey && (ev.key === "ArrowLeft" || ev.key === "ArrowRight")) {
      ev.preventDefault(); flushText(); MD.call("go", ev.key === "ArrowLeft" ? -1 : 1); return;
    }
    // Echap dans une cellule de tableau : sortie du tableau (table.js), pas fermeture du module.
    const inCell = document.activeElement && document.activeElement.closest && document.activeElement.closest(".cm-table-widget");
    if (ev.key === "Escape" && !inCell && !ev.defaultPrevented && !document.querySelector(".md-prompt, .CodeMirror-dialog")) {
      ev.preventDefault(); flushText(); MD.call("close");
    }
  }

  function onWheel(ev) {
    // Fichiers de code : Ctrl + molette = taille du texte (retenue). Ecoute posee sur l'EDITEUR seulement (dont
    // CodeMirror ecoute deja la molette) : la lecture garde un defilement entierement natif, sans passer par la page.
    if (!(ev.ctrlKey && S.current && S.current.kind !== "markdown")) return;
    ev.preventDefault();
    MD.call("zoomCode", ev.deltaY < 0 ? 1 : -1);
  }

  // -- Demarrage ---------------------------------------------------------------------------------------------------------
  function start() {
    document.body.classList.add("md-page", "theme-dark");
    document.body.innerHTML =
      '<div id="md-toolbar" class="md-toolbar"></div>' +
      // Classes d'Obsidian en plus des notres (memes roles) : une feuille ecrite pour Obsidian s'applique ici.
      '<div id="md-edit" class="md-view md-edit markdown-source-view mod-cm6 is-live-preview"></div>' +
      '<div id="md-read" class="md-view md-read markdown-reading-view" tabindex="-1">' +
      '<div class="md-sizer markdown-preview-view markdown-rendered">' +
      '<div id="md-read-title" class="md-title inline-title"></div>' +
      '<div id="md-read-body" class="md-body md-rendered markdown-preview-sizer markdown-preview-section"></div></div></div>' +
      '<div id="md-notice" class="md-notice"></div>';
    MD.editor = new MD.Editor($("md-edit"), { textChanged });
    MD.toolbar = new MD.Toolbar($("md-toolbar"));
    $("md-read").addEventListener("click", onReadingClick);
    document.addEventListener("keydown", onKey, true);
    $("md-edit").addEventListener("wheel", onWheel, { passive: false });
    document.addEventListener("mouseup", (ev) => {
      if (ev.button === 3 || ev.button === 4) { ev.preventDefault(); flushText(); MD.call("go", ev.button === 3 ? -1 : 1); }
    });
    window.addEventListener("resize", () => MD.toolbar.sync());
    new QWebChannel(qt.webChannelTransport, (channel) => {
      MD.bridge = channel.objects.bridge;
      MD.bridge.reply.connect(onReply);
      MD.bridge.push.connect(onPush);
      MD.bridge.ready();
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
