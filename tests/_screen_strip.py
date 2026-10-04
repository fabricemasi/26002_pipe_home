"""Capture en boucle une ligne de pixels de l'ecran (BitBlt GDI = image composee
par DWM) : python _screen_strip.py x y w out.txt duree_s. Ecrit 'perf_counter hash'."""
import ctypes, sys, time, zlib
from ctypes import wintypes as W
x, y, w, out, dur = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], float(sys.argv[5])
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
u, g = ctypes.windll.user32, ctypes.windll.gdi32
g.CreateCompatibleDC.restype = W.HDC; u.GetDC.restype = W.HDC
g.CreateCompatibleBitmap.restype = W.HBITMAP
g.CreateCompatibleDC.argtypes = [W.HDC]; g.CreateCompatibleBitmap.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int]
g.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
g.BitBlt.argtypes = [W.HDC] + [ctypes.c_int]*4 + [W.HDC, ctypes.c_int, ctypes.c_int, W.DWORD]
g.GetBitmapBits.argtypes = [W.HBITMAP, ctypes.c_long, ctypes.c_void_p]
sdc = u.GetDC(None); mdc = g.CreateCompatibleDC(sdc); bmp = g.CreateCompatibleBitmap(sdc, w, 1); g.SelectObject(mdc, bmp)
buf = ctypes.create_string_buffer(w * 4)
lines = []
end = time.perf_counter() + dur
while time.perf_counter() < end:
    g.BitBlt(mdc, 0, 0, w, 1, sdc, x, y, 0x00CC0020)
    g.GetBitmapBits(bmp, w * 4, buf)
    lines.append(f"{time.perf_counter():.5f} {zlib.crc32(buf.raw)}")
open(out, "w").write("\n".join(lines))
