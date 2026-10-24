"""Benchmark isolé et reproductible : dossiers locaux + latence de scan simulée.

QT_QPA_PLATFORM=windows python tests/_probe_navigation_loading.py
La fenêtre native est placée hors écran. Aucun accès aux fichiers de production.
"""
import _isolate  # noqa: F401
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
from pathlib import Path
import statistics
import tempfile
import time
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication
from column import Column
import column as column_module
import column_loading as loading

APP = QApplication.instance() or QApplication([])


def rss_mib():
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD),
                    *[(name, ctypes.c_size_t) for name in (
                        "peak", "working", "peak_paged", "paged", "peak_nonpaged",
                        "nonpaged", "pagefile", "peak_pagefile")]]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    process = ctypes.windll.kernel32.GetCurrentProcess
    process.restype = wintypes.HANDLE
    get_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if get_info(process(), ctypes.byref(counters), counters.cb):
        return round(counters.working / 1024**2, 1)
    return None


def percentile(values, fraction):
    return sorted(values)[max(0, int(len(values) * fraction + .999) - 1)]


def run(root, asynchronous, delay, repeats=7):
    loading._loader = loading.ColumnLoader()
    starts, firsts, totals, gaps, cpus = [], [], [], [], []
    original = column_module.list_entries
    original_read = loading.read_column
    rss_before = rss_mib()
    def slow_entries(*args, **kwargs):
        time.sleep(delay)
        return original(*args, **kwargs)
    def slow_read(*args, **kwargs):
        time.sleep(delay)
        return original_read(*args, **kwargs)
    for attempt in range(repeats):
        ticks = [time.perf_counter()]
        timer = QTimer()
        timer.setInterval(4)
        timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
        timer.start()
        cpu = time.process_time()
        started = time.perf_counter()
        with patch.object(column_module, "list_entries", side_effect=slow_entries), \
             patch.object(loading, "read_column", side_effect=slow_read):
            col = Column(root, "Contenu", async_load=asynchronous)
            starts.append((time.perf_counter() - started) * 1000)
            col.resize(260, 800)
            col.move(-4000, 0)
            col.show()
            first = None
            deadline = time.perf_counter() + 30
            while True:
                APP.processEvents()
                now = time.perf_counter()
                if first is None and col.list.count():
                    first = now
                if not col.loading:
                    break
                if now > deadline:
                    raise RuntimeError("Colonne non chargée")
                time.sleep(.001)
            totals.append((now - started) * 1000)
            firsts.append(((first or now) - started) * 1000)
            cpus.append((time.process_time() - cpu) * 1000)
            # Inclure le dernier intervalle même si aucun tick n'a eu lieu.
            ticks.append(now)
            gaps.append(max((b-a)*1000 for a,b in zip(ticks,ticks[1:])))
        timer.stop()
        col.cancel_loading()
        col.close()
        col.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    return {"mode": "async" if asynchronous else "sync", "delay_ms": delay*1000,
            "cold_constructor_ms": round(starts[0], 2), "cold_first_ms": round(firsts[0], 2),
            "cold_full_ms": round(totals[0], 2), "cold_gui_gap_ms": round(gaps[0], 2),
            "warm_constructor_p50_ms": round(statistics.median(starts[1:]), 2),
            "warm_constructor_p95_ms": round(percentile(starts[1:], .95), 2),
            "warm_full_p50_ms": round(statistics.median(totals[1:]), 2),
            "warm_gui_gap_max_ms": round(max(gaps[1:]), 2),
            "cpu_p50_ms": round(statistics.median(cpus), 2),
            "process_rss_before_mib": rss_before, "process_rss_after_mib": rss_mib(),
            "directory_scans": loading.loader().scans if asynchronous else repeats}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="pipe_nav_bench_") as temp:
        root = Path(temp)
        for count in (30, 5000):
            folder = root / str(count)
            folder.mkdir()
            for i in range(count):
                (folder / f"file_{i:05d}.txt").touch()
            for delay in ((0, .25) if count == 30 else (0,)):
                for asynchronous in (False, True):
                    print(json.dumps({"files": count, **run(folder, asynchronous, delay)}), flush=True)
