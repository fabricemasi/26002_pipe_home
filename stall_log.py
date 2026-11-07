"""Journal des BLOCAGES de l'interface (diagnostic de fluidité, 2026-11-05) : allumé seulement par la variable
d'environnement `PIPELINE_STALL_LOG=1` (lanceur `pipeline_browser_mesure.bat`) ou par la présence du fichier
`data/stall_log.on` (n'importe quel lanceur) ; sinon rien n'est posé (`PIPELINE_STALL_LOG=0` l'éteint toujours).

Un battement (QTimer, 15 ms) sur le fil de l'interface ; un fil de surveillance le regarde toutes les 5 ms. Dès que le
fil de l'interface ne bat plus depuis `THRESHOLD_MS`, sa pile est relevée toutes les 5 ms jusqu'à la reprise ; à la
reprise, une entrée est écrite dans `data/stalls.log` : durée, puis les lignes de code les plus vues pendant le blocage
(fichiers du projet seulement), la plus fréquente d'abord. Coût hors blocage : négligeable.
"""
from __future__ import annotations

import collections
import os
import sys
import threading
import time
import traceback
from pathlib import Path

THRESHOLD_MS = 50
LOG_PATH = Path(__file__).resolve().parent / "data" / "stalls.log"
_ROOT = str(Path(__file__).resolve().parent).lower()
_STATE: dict = {}


FLAG_PATH = Path(__file__).resolve().parent / "data" / "stall_log.on"   # present : allume, quel que soit le lanceur


def enabled() -> bool:
    if os.environ.get("PIPELINE_STALL_LOG", "") == "0":
        return False
    return os.environ.get("PIPELINE_STALL_LOG", "") != "" or FLAG_PATH.exists()


def _own_frames(frame) -> list[str]:
    """Lignes de la pile qui appartiennent au projet (hors .venv), de la plus profonde à la plus haute."""
    out = []
    for summary in reversed(traceback.extract_stack(frame)):
        name = summary.filename.lower()
        if name.startswith(_ROOT) and ".venv" not in name and "stall_log" not in name:
            out.append(f"{Path(summary.filename).name}:{summary.lineno} {summary.name}")
    return out


def _watch(ui_ident: int, beat: list) -> None:
    samples: collections.Counter = collections.Counter()
    tops: collections.Counter = collections.Counter()
    start = None
    while True:
        time.sleep(0.005)
        age = (time.perf_counter() - beat[0]) * 1000
        if age >= THRESHOLD_MS:
            if start is None:
                start = beat[0]
                samples.clear()
                tops.clear()
            frame = sys._current_frames().get(ui_ident)
            if frame is not None:
                lines = _own_frames(frame)
                samples.update(set(lines))
                if lines:
                    tops[lines[0]] += 1
            continue
        if start is not None:
            duration = (beat[0] - start) * 1000
            start = None
            if duration >= THRESHOLD_MS:
                _write(duration, samples, tops)


def _write(duration: float, samples, tops) -> None:
    lines = [f"--- {time.strftime('%H:%M:%S')}  blocage {duration:.0f} ms"]
    lines += [f"  au sommet x{n}: {line}" for line, n in tops.most_common(4)]
    lines += [f"  dans la pile x{n}: {line}" for line, n in samples.most_common(10)]
    try:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError:
        pass


def install(app) -> None:
    """Pose le battement et le fil de surveillance (une fois), si le journal est allumé."""
    if not enabled() or _STATE:
        return
    from PySide6.QtCore import QTimer
    beat = [time.perf_counter()]
    timer = QTimer(app)
    timer.setInterval(15)
    timer.timeout.connect(lambda: beat.__setitem__(0, time.perf_counter()))
    timer.start()
    _STATE["timer"] = timer
    try:
        LOG_PATH.write_text(f"Journal des blocages (> {THRESHOLD_MS} ms), {time.strftime('%Y-%m-%d %H:%M')}\n",
                            encoding="utf-8")
    except OSError:
        pass
    threading.Thread(target=_watch, args=(threading.get_ident(), beat), name="stall-log", daemon=True).start()
