"""Lecture / écriture WAV (RIFF, RF64) en numpy, sans dépendance audio tierce.

Les données sont des tableaux float32 de forme (canaux, images). L'écriture passe par un
fichier `.part` puis un renommage : un fichier existant n'est jamais remplacé en silence.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np


class WavError(ValueError):
    pass


@dataclass
class WavInfo:
    sample_rate: int
    channels: int
    bits: int
    is_float: bool
    frames: int
    data_offset: int
    rf64: bool = False


def probe(path: str | os.PathLike) -> WavInfo:
    with open(path, "rb") as f:
        head = f.read(12)
        if len(head) < 12 or head[8:12] != b"WAVE" or head[:4] not in (b"RIFF", b"RF64", b"BW64"):
            raise WavError(f"pas un fichier WAV : {path}")
        rf64 = head[:4] != b"RIFF"
        ds64_data = 0
        fmt = None
        size_total = os.fstat(f.fileno()).st_size
        while True:
            ck = f.read(8)
            if len(ck) < 8:
                break
            cid, size = ck[:4], struct.unpack("<I", ck[4:])[0]
            here = f.tell()
            if cid == b"ds64":
                d = f.read(24)
                ds64_data = struct.unpack("<Q", d[8:16])[0]
            elif cid == b"fmt ":
                d = f.read(min(size, 40))
                tag, ch, sr = struct.unpack("<HHI", d[:8])
                bits = struct.unpack("<H", d[14:16])[0]
                if tag == 0xFFFE and len(d) >= 26:
                    tag = struct.unpack("<H", d[24:26])[0]
                if tag not in (1, 3):
                    raise WavError(f"format WAV non pris en charge (tag {tag})")
                fmt = (sr, ch, bits, tag == 3)
            elif cid == b"data":
                if fmt is None:
                    raise WavError("chunk data avant fmt")
                n = ds64_data if (rf64 and size == 0xFFFFFFFF) else size
                avail = size_total - here
                if n > avail or (n == 0 and avail > 0):
                    n = avail  # prise interrompue : on lit ce qui existe
                sr, ch, bits, flt = fmt
                bpf = ch * bits // 8
                return WavInfo(sr, ch, bits, flt, n // bpf if bpf else 0, here, rf64)
            f.seek(here + size + (size & 1))
    raise WavError("chunk data absent")


def read(path: str | os.PathLike, start: int = 0, count: int = -1) -> tuple[np.ndarray, int]:
    """Retourne (données float32 (canaux, images), fréquence)."""
    info = probe(path)
    start = max(0, min(start, info.frames))
    n = info.frames - start if count < 0 else min(count, info.frames - start)
    bps = info.bits // 8
    with open(path, "rb") as f:
        f.seek(info.data_offset + start * info.channels * bps)
        raw = f.read(n * info.channels * bps)
    n = len(raw) // (info.channels * bps)
    raw = raw[: n * info.channels * bps]
    if info.is_float:
        a = np.frombuffer(raw, dtype="<f4" if bps == 4 else "<f8").astype(np.float32)
    elif bps == 2:
        a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif bps == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        v = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
        v = np.where(v >= 1 << 23, v - (1 << 24), v)
        a = v.astype(np.float32) / 8388608.0
    elif bps == 4:
        a = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    return a.reshape(-1, info.channels).T.copy(), info.sample_rate


def write(path: str | os.PathLike, data: np.ndarray, sample_rate: int, *, fmt: str = "f32",
          overwrite: bool = False) -> Path:
    """Écrit (canaux, images) ; fmt : f32, pcm16, pcm24. RF64 automatique au-delà de 4 Gio."""
    path = Path(path)
    if path.exists() and not overwrite:
        raise FileExistsError(f"le fichier existe déjà : {path}")
    data = np.atleast_2d(np.asarray(data, dtype=np.float32))
    ch, n = data.shape
    inter = np.nan_to_num(data.T, nan=0.0, posinf=0.0, neginf=0.0)
    if fmt == "pcm16":
        payload = np.clip(np.round(inter * 32767.0), -32768, 32767).astype("<i2").tobytes()
        bits, tag = 16, 1
    elif fmt == "pcm24":
        q = np.clip(np.round(inter * 8388607.0), -8388608, 8388607).astype(np.int32).reshape(-1)
        b = np.empty((q.size, 3), dtype=np.uint8)
        b[:, 0] = q & 0xFF
        b[:, 1] = (q >> 8) & 0xFF
        b[:, 2] = (q >> 16) & 0xFF
        payload = b.tobytes()
        bits, tag = 24, 1
    else:
        payload = inter.astype("<f4").tobytes()
        bits, tag = 32, 3
    big = len(payload) + 72 > 0xFFFFFFF0
    block = ch * bits // 8
    hdr = bytearray()
    hdr += b"RF64" if big else b"RIFF"
    hdr += struct.pack("<I", 0xFFFFFFFF if big else 72 + len(payload))
    hdr += b"WAVE"
    hdr += (b"ds64" if big else b"JUNK") + struct.pack("<I", 28)
    hdr += struct.pack("<QQQI", 72 + len(payload), len(payload), n, 0) if big else bytes(28)
    hdr += b"fmt " + struct.pack("<IHHIIHH", 16, tag, ch, sample_rate, sample_rate * block, block, bits)
    hdr += b"data" + struct.pack("<I", 0xFFFFFFFF if big else len(payload))
    tmp = path.with_name(path.name + ".part")
    with open(tmp, "wb") as f:
        f.write(hdr)
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path) if overwrite else _rename_new(tmp, path)
    return path


def _rename_new(tmp: Path, path: Path) -> None:
    if path.exists():
        tmp.unlink(missing_ok=True)
        raise FileExistsError(f"le fichier existe déjà : {path}")
    os.rename(tmp, path)


class StreamWriter:
    """Écriture progressive float32 (décodage, rendu) : `.part`, en-tête corrigé à la fin, renommage."""

    def __init__(self, path: str | os.PathLike, sample_rate: int, channels: int, *, overwrite: bool = False):
        self.path = Path(path)
        if self.path.exists() and not overwrite:
            raise FileExistsError(f"le fichier existe déjà : {self.path}")
        self.overwrite = overwrite
        self.sr, self.ch = int(sample_rate), int(channels)
        self.frames = 0
        self.tmp = self.path.with_name(self.path.name + ".part")
        self.f = open(self.tmp, "wb")
        self.f.write(self._header(0))

    def _header(self, nbytes: int) -> bytes:
        big = nbytes + 72 > 0xFFFFFFF0
        block = self.ch * 4
        h = bytearray()
        h += b"RF64" if big else b"RIFF"
        h += struct.pack("<I", 0xFFFFFFFF if big else 72 + nbytes)
        h += b"WAVE" + (b"ds64" if big else b"JUNK") + struct.pack("<I", 28)
        h += struct.pack("<QQQI", 72 + nbytes, nbytes, nbytes // block, 0) if big else bytes(28)
        h += b"fmt " + struct.pack("<IHHIIHH", 16, 3, self.ch, self.sr, self.sr * block, block, 32)
        h += b"data" + struct.pack("<I", 0xFFFFFFFF if big else nbytes)
        return bytes(h)

    def write(self, data: np.ndarray) -> None:
        data = np.atleast_2d(np.asarray(data, dtype=np.float32))
        if data.shape[0] != self.ch:
            raise WavError(f"{data.shape[0]} canaux pour un fichier à {self.ch}")
        self.f.write(np.ascontiguousarray(data.T).astype("<f4").tobytes())
        self.frames += data.shape[1]

    def close(self) -> Path:
        nbytes = self.frames * self.ch * 4
        self.f.seek(0)
        self.f.write(self._header(nbytes))
        self.f.flush()
        os.fsync(self.f.fileno())
        self.f.close()
        if self.overwrite:
            os.replace(self.tmp, self.path)
        else:
            _rename_new(self.tmp, self.path)
        return self.path

    def abort(self) -> None:
        try:
            self.f.close()
        finally:
            self.tmp.unlink(missing_ok=True)