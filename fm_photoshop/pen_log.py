"""Journal du stylet (SANS Qt) : ce qui ARRIVE (évènements tablette et souris, bruts) et ce que le moteur EN FAIT.

Chaque ligne : type (press / move / release / hover), source (tablet / mouse / mouse_synth), horodatage, position flottante,
pression brute, inclinaison, rotation, périphérique, et pour les évènements transmis au moteur : pression filtrée, taille,
opacité, débit résultants, position effectivement utilisée, temps de traitement. Le journal s'enregistre en JSON et se REJOUE
(`stroke_samples`) : plusieurs algorithmes peuvent être comparés sur exactement les mêmes données."""
from __future__ import annotations

import json
import statistics


class PenLog:
    def __init__(self):
        self.events: list = []
        self._t0 = None
        self._prev_t = {}                   # source -> dernier horodatage (écart entre deux évènements)

    def add(self, kind: str, source: str, t: float, x: float, y: float, **extra) -> dict:
        if self._t0 is None:
            self._t0 = t
        prev = self._prev_t.get(source)
        self._prev_t[source] = t
        row = {"i": len(self.events), "t": round(t - self._t0, 6), "dt_ms": None if prev is None else round((t - prev) * 1000.0, 3),
               "kind": kind, "source": source, "x": x, "y": y}
        row.update(extra)
        self.events.append(row)
        return row

    # -- lecture --
    def stroke_samples(self) -> list:
        """Les traits transmis au moteur : une liste par trait de (x_doc, y_doc, pression_brute, t)."""
        strokes, current = [], None
        for e in self.events:
            if "doc" not in e:
                continue
            if e["kind"] == "press":
                current = []
                strokes.append(current)
            if current is not None:
                current.append((e["doc"][0], e["doc"][1], e.get("p_raw", 1.0), e["t"]))
        return strokes

    def stats(self) -> dict:
        """Diagnostic des entrées : cadence, régularité, quantification de la pression, doubles évènements."""
        tablet = [e for e in self.events if e["source"] == "tablet" and e["kind"] == "move"]
        mouse = [e for e in self.events if e["source"].startswith("mouse") and e["kind"] == "move"]
        out = {"evenements": len(self.events), "tablette_move": len(tablet), "souris_move": len(mouse),
               "souris_synthetisee": sum(1 for e in mouse if e["source"] == "mouse_synth")}
        dts = sorted(e["dt_ms"] for e in tablet if e["dt_ms"] is not None)
        if dts:
            out["dt_ms_mediane"] = statistics.median(dts)
            out["dt_ms_p95"] = dts[min(len(dts) - 1, int(0.95 * len(dts)))]
            out["dt_ms_max"] = dts[-1]
            out["cadence_hz"] = round(1000.0 / max(out["dt_ms_mediane"], 1e-6), 1)
        pressures = [e["p_raw"] for e in tablet if e.get("p_raw") is not None]
        if pressures:
            out["pression_min"], out["pression_max"] = min(pressures), max(pressures)
            out["pression_valeurs_distinctes"] = len({round(p, 5) for p in pressures})
            steps = sum(1 for a, b in zip(pressures, pressures[1:]) if a == b)
            out["pression_inchangee_pct"] = round(100.0 * steps / max(1, len(pressures) - 1), 1)
        out.update(self._hover_stats())
        timed = sorted(e["proc_ms"] for e in self.events if e.get("proc_ms") is not None)
        if timed:
            out["traitement_ms_mediane"] = round(statistics.median(timed), 3)
            out["traitement_ms_p95"] = round(timed[min(len(timed) - 1, int(0.95 * len(timed)))], 3)
            out["traitement_ms_p99"] = round(timed[min(len(timed) - 1, int(0.99 * len(timed)))], 3)
        return out

    def _hover_stats(self) -> dict:
        """Survol : source(s) des positions, bruit, quantification, alternance de sources, écart curseur affiché / position reçue."""
        rows = [e for e in self.events if e["kind"] == "hover"]
        if not rows:
            return {}
        out = {"survol": len(rows)}
        by_source = {}
        for e in rows:
            by_source.setdefault(e["source"], []).append(e)
        out["survol_sources"] = {k: len(v) for k, v in by_source.items()}

        def noise(points):
            if len(points) < 5:
                return None
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            res = []
            for i in range(2, len(points) - 2):
                mx, my = statistics.median(xs[i - 2:i + 3]), statistics.median(ys[i - 2:i + 3])
                res.append(((xs[i] - mx) ** 2 + (ys[i] - my) ** 2) ** 0.5)
            return round(statistics.median(res), 3), round(sorted(res)[min(len(res) - 1, int(0.95 * len(res)))], 3)

        merged = noise([(e["x"], e["y"]) for e in rows])
        if merged:
            out["survol_bruit_px_mediane_p95"] = merged
        for source, group in by_source.items():
            value = noise([(e["x"], e["y"]) for e in group])
            if value:
                out[f"survol_bruit_{source}"] = value
        whole = sum(1 for e in rows if float(e["x"]).is_integer() and float(e["y"]).is_integer())
        out["survol_positions_entieres_pct"] = round(100.0 * whole / len(rows), 1)
        flips = sum(1 for a, b in zip(rows, rows[1:]) if a["source"] != b["source"]
                    and ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5 > 0.3)
        out["survol_alternances_de_source"] = flips
        gaps = [((e["cursor"][0] - e["x"]) ** 2 + (e["cursor"][1] - e["y"]) ** 2) ** 0.5 for e in rows if e.get("cursor")]
        if gaps:
            out["survol_ecart_curseur_px_max"] = round(max(gaps), 3)
        devices = {(e.get("device"), e.get("device_type"), e.get("device_id")) for e in rows}
        out["survol_peripheriques"] = sorted(str(d) for d in devices)
        return out

    def summary(self) -> str:
        return ", ".join(f"{k}={v}" for k, v in self.stats().items())

    # -- fichier --
    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "stats": self.stats(), "events": self.events}, handle, ensure_ascii=False)

    @classmethod
    def load(cls, path: str) -> "PenLog":
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        log = cls()
        log.events = list(raw.get("events", []))
        return log
