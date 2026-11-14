"""Traitements de FM Audio qui produisent une NOUVELLE RÉVISION du son (fichier neuf), dans un
fil de travail ; le clip est repointé en une étape d'annulation ; l'original n'est jamais touché.
Un résultat obsolète (projet modifié entre-temps) n'est pas appliqué."""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

from fm_audio_engine import analysis, dsp_offline, media, wavio
from fm_sound_ui.ui_kit import ask_value, menu


class _Relay(QObject):
    done = Signal(object)


def revisions_dir(pane) -> Path:
    d = pane.session.media_folder()
    if d is None:
        d = media.cache_dir() / "revisions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _clip_audio(pane, tid, cid):
    t = pane.project.track(tid)
    c = next(x for x in t.clips if x.id == cid)
    src = pane.session.resolve(c)
    n = int(np.ceil(c.length * c.rate))
    data, sr = wavio.read(src, c.offset, n)
    if c.reverse:
        data = data[:, ::-1]
    return c, data, sr


def run(pane, label: str, fn, need_selection: bool = False) -> None:
    """Applique `fn(data, sr, clip, sel_rel) -> (nouvelles données, message)` aux clips choisis."""
    items = list(pane.view.sel_clips)
    if not items:
        pane.set_status("Choisir un ou plusieurs clips")
        return
    if need_selection and not pane.view.sel:
        pane.set_status("Faire d'abord une sélection temporelle (profil / zone)")
        return
    rev0 = pane.project.revision
    sel = pane.view.sel
    relay = _Relay(pane)
    out_dir = revisions_dir(pane)

    def work():
        results = []
        for tid, cid in items:
            try:
                c, data, sr = _clip_audio(pane, tid, cid)
                rel = None
                if sel:
                    rel = (max(0, int((sel[0] - c.start) * c.rate)), max(0, int((sel[1] - c.start) * c.rate)))
                y, msg = fn(data, sr, c, rel)
                stem = Path(c.path).stem.split("__")[0]
                k = 1
                while (out_dir / f"{stem}__r{c.revision + k}.wav").exists():
                    k += 1
                path = wavio.write(out_dir / f"{stem}__r{c.revision + k}.wav", y, sr)
                results.append((tid, cid, str(path), y.shape[1], c.revision + k, msg))
            except Exception as e:  # signalé, rien n'est remplacé
                results.append((tid, cid, None, 0, 0, f"échec : {e}"))
        relay.done.emit(results)

    def apply(results):
        if pane.project.revision != rev0:
            pane.set_status(f"{label} : projet modifié pendant le calcul, résultat NON appliqué (fichiers conservés)")
            return
        msgs = []
        with pane.project.edit(label, *{r[0] for r in results}):
            for tid, cid, path, frames, rev, msg in results:
                msgs.append(msg)
                if path is None:
                    continue
                c = next(x for x in pane.project.track(tid).clips if x.id == cid)
                c.path, c.offset, c.rate, c.reverse, c.revision = path, 0, 1.0, False, rev
                c.length = frames
                c.fade_in, c.fade_out = min(c.fade_in, frames), min(c.fade_out, frames)
        pane.set_status(f"{label} : " + " ; ".join(m for m in msgs if m))

    relay.done.connect(apply)
    pane.set_status(f"{label} : calcul en cours…")
    threading.Thread(target=work, daemon=True, name="fmz-audio-process").start()


def menu_for(pane) -> None:
    m = menu(pane)
    acts = {
        m.addAction("Étirer le temps…"): "stretch",
        m.addAction("Transposer…"): "pitch",
        m.addAction("Réduire le bruit (profil = sélection)"): "denoise",
        m.addAction("Écouter le bruit retiré (résidu)"): "residual",
        m.addAction("Atténuer une zone spectrale (sélection × bande)…"): "spectral",
        m.addAction("Supprimer les clics"): "declick",
        m.addAction("Analyser (crête, true peak, loudness)"): "analyze",
        m.addAction("Accordeur (note du clip)"): "tune",
    }
    chosen = m.exec(pane.mapToGlobal(pane.view.geometry().center()))
    what = acts.get(chosen)
    if what == "stretch":
        v = ask_value(pane, "Étirer le temps", "Nouvelle durée en % (hauteur conservée)", "100")
        if v:
            f = float(v.replace(",", ".")) / 100
            run(pane, "Étirement", lambda x, sr, c, r: (dsp_offline.time_stretch(x, f, sr), f"durée × {f:.3f}"))
    elif what == "pitch":
        v = ask_value(pane, "Transposer", "Demi-tons (durée conservée)", "0")
        if v:
            st = float(v.replace(",", "."))
            run(pane, "Transposition", lambda x, sr, c, r: (dsp_offline.pitch_shift(x, st, sr), f"{st:+g} demi-tons"))
    elif what in ("denoise", "residual"):
        def fn(x, sr, c, r, keep_residual=(what == "residual")):
            y, res = dsp_offline.noise_reduce(x, x[:, r[0]:max(r[0] + 2048, r[1])])
            before = analysis.peak_dbfs(x)
            return (res if keep_residual else y), f"bruit retiré (crête avant {before:.1f} dBFS)"
        run(pane, "Réduction de bruit" if what == "denoise" else "Résidu de réduction", fn, need_selection=True)
    elif what == "spectral" and getattr(getattr(pane, "spectro", None), "sel", None):
        t0, t1, lo, hi = pane.spectro.sel             # zone tracée sur le spectrogramme
        v = ask_value(pane, "Zone spectrale", f"{lo:.0f}-{hi:.0f} Hz : atténuation en dB", "-60")
        if v:
            gain = float(v.replace(",", "."))
            def fn(x, sr, c, r, t0=t0, t1=t1):
                a, b = (t0 - c.start) * c.rate / sr, (t1 - c.start) * c.rate / sr
                return dsp_offline.spectral_edit(x, sr, a, b, lo, hi, gain), f"{lo:.0f}-{hi:.0f} Hz à {gain:+.0f} dB"
            run(pane, "Édition spectrale", fn)
    elif what == "spectral":
        v = ask_value(pane, "Zone spectrale", "Bande en Hz « bas-haut » et atténuation en dB, ex. 2800-3200 -60", "2800-3200 -60")
        if v:
            band, _, g = v.partition(" ")
            lo, hi = (float(z) for z in band.split("-"))
            gain = float(g or -60)
            run(pane, "Édition spectrale",
                lambda x, sr, c, r: (dsp_offline.spectral_edit(x, sr, r[0] / sr, r[1] / sr, lo, hi, gain), f"{lo:.0f}-{hi:.0f} Hz à {gain:+.0f} dB"),
                need_selection=True)
    elif what == "declick":
        def fn(x, sr, c, r):
            y, n = dsp_offline.declick(x)
            return y, f"{n} clic(s) corrigé(s)"
        run(pane, "Déclic", fn)
    elif what in ("analyze", "tune"):
        items = list(pane.view.sel_clips)
        if not items:
            pane.set_status("Choisir un clip")
            return
        c, data, sr = _clip_audio(pane, *items[0])
        if what == "analyze":
            L = analysis.loudness(data, sr)
            pane.set_status(f"crête {analysis.peak_dbfs(data):.2f} dBFS, true peak {analysis.true_peak_dbtp(data[:, :sr * 60]):.2f} dBTP, "
                            f"{L['integrated']:.1f} LUFS intégré, LRA {L['lra']:.1f} LU")
        else:
            f = analysis.pitch_yin(data[:, :sr // 2], sr)
            if f is None:
                pane.set_status("Accordeur : aucune note stable")
            else:
                ref = float(pane._settings().get("audio_tuner_reference", 440.0))
                t = analysis.tuner(f, ref)
                pane.set_status(f"Accordeur : {t['note']}{t['octave']} {t['cents']:+.1f} cents ({f:.2f} Hz, la = {ref:g} Hz)")
