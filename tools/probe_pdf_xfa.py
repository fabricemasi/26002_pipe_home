"""Prototype : PDFium V8/XFA via les bindings de pypdfium2 — chargement, rendu, saisie, enregistrement, réouverture."""
import ctypes, sys, os, time, pathlib
sys.path.insert(0, r"F:\SYNC\Sync\PROG\26002_pipe_home")
from fm_pdf import native

c = native.load()
print("DLL", native.info())
cfg = c.FPDF_LIBRARY_CONFIG(version=2, m_pUserFontPaths=None, m_pIsolate=None, m_v8EmbedderSlot=0)
t0 = time.perf_counter()
c.FPDF_InitLibraryWithConfig(ctypes.byref(cfg))
print("init %.1f ms" % ((time.perf_counter() - t0) * 1000))

KEEP = []
EVENTS = []


def cb(struct, name, fn):
    ftype = dict(struct._fields_)[name]
    f = ftype(fn)
    KEEP.append(f)
    return f


def wstr(p):
    if not p:
        return ""
    return ctypes.wstring_at(ctypes.cast(p, ctypes.c_wchar_p))


class Doc:
    def __init__(self, path):
        self.path = path
        self.data = pathlib.Path(path).read_bytes()
        self.buf = ctypes.create_string_buffer(self.data, len(self.data))
        self.doc = c.FPDF_LoadMemDocument64(self.buf, len(self.data), None)
        if not self.doc:
            raise RuntimeError("load error %d" % c.FPDF_GetLastError())
        self.pages = {}
        self.form_type = c.FPDF_GetFormType(self.doc)
        js = c.IPDF_JSPLATFORM()
        js.version = 3
        js.app_alert = cb(c.IPDF_JSPLATFORM, "app_alert", lambda s, m, t, ty, ic: (EVENTS.append(("alert", wstr(m))), 0)[1])
        js.app_beep = cb(c.IPDF_JSPLATFORM, "app_beep", lambda s, t: None)
        js.app_response = cb(c.IPDF_JSPLATFORM, "app_response", lambda *a: 0)
        js.Doc_getFilePath = cb(c.IPDF_JSPLATFORM, "Doc_getFilePath", lambda s, b, n: 0)
        js.Doc_mail = cb(c.IPDF_JSPLATFORM, "Doc_mail", lambda *a: EVENTS.append(("BLOCKED mail",)))
        js.Doc_print = cb(c.IPDF_JSPLATFORM, "Doc_print", lambda *a: EVENTS.append(("print",)))
        js.Doc_submitForm = cb(c.IPDF_JSPLATFORM, "Doc_submitForm", lambda *a: EVENTS.append(("BLOCKED submit",)))
        js.Doc_gotoPage = cb(c.IPDF_JSPLATFORM, "Doc_gotoPage", lambda s, p: EVENTS.append(("goto", p)))
        js.Field_browse = cb(c.IPDF_JSPLATFORM, "Field_browse", lambda s, b, n: 0)
        self.js = js
        F = c.FPDF_FORMFILLINFO
        info = F()
        info.version = 2
        info.m_pJsPlatform = ctypes.pointer(js)
        info.xfa_disabled = 0
        info.FFI_Invalidate = cb(F, "FFI_Invalidate", lambda s, p, l, t, r, b: EVENTS.append(("inval", round(l), round(t), round(r), round(b))))
        info.FFI_OutputSelectedRect = cb(F, "FFI_OutputSelectedRect", lambda *a: None)
        info.FFI_SetCursor = cb(F, "FFI_SetCursor", lambda s, t: None)
        self.timers = {}
        def set_timer(s, ms, fn):
            tid = len(self.timers) + 1
            self.timers[tid] = (ms, fn)
            return tid
        info.FFI_SetTimer = cb(F, "FFI_SetTimer", set_timer)
        info.FFI_KillTimer = cb(F, "FFI_KillTimer", lambda s, i: self.timers.pop(i, None))
        def local_time(s):
            st = c.FPDF_SYSTEMTIME()
            lt = time.localtime()
            st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond = lt.tm_year, lt.tm_mon, lt.tm_mday, lt.tm_hour, lt.tm_min, lt.tm_sec
            st.wDayOfWeek = (lt.tm_wday + 1) % 7
            return st
        # ctypes ne sait pas renvoyer une structure depuis un rappel : laissé vide (PDFium a son repli)
        info.FFI_OnChange = cb(F, "FFI_OnChange", lambda s: EVENTS.append(("change",)))
        addr = lambda p: ctypes.cast(p, ctypes.c_void_p).value if p else None
        info.FFI_GetPage = cb(F, "FFI_GetPage", lambda s, d, i: (EVENTS.append(("getpage", i)), addr(self.pages.get(i)))[1])
        info.FFI_GetCurrentPage = cb(F, "FFI_GetCurrentPage", lambda s, d: addr(self.pages.get(0)))
        info.FFI_GetRotation = cb(F, "FFI_GetRotation", lambda s, p: 0)
        info.FFI_ExecuteNamedAction = cb(F, "FFI_ExecuteNamedAction", lambda s, n: None)
        info.FFI_SetTextFieldFocus = cb(F, "FFI_SetTextFieldFocus", lambda s, v, n, f: EVENTS.append(("tffocus", bool(f))))
        info.FFI_DoURIAction = cb(F, "FFI_DoURIAction", lambda s, u: EVENTS.append(("BLOCKED uri",)))
        info.FFI_DoGoToAction = cb(F, "FFI_DoGoToAction", lambda *a: None)
        info.FFI_DisplayCaret = cb(F, "FFI_DisplayCaret", lambda s, p, v, l, t, r, b: EVENTS.append(("caret", bool(v), round(l, 1), round(t, 1), round(r, 1), round(b, 1))))
        info.FFI_GetCurrentPageIndex = cb(F, "FFI_GetCurrentPageIndex", lambda s, d: 0)
        info.FFI_SetCurrentPage = cb(F, "FFI_SetCurrentPage", lambda s, d, i: None)
        info.FFI_GotoURL = cb(F, "FFI_GotoURL", lambda s, d, u: EVENTS.append(("BLOCKED gotourl",)))
        def view_rect(s, p, l, t, r, b):
            l[0], t[0], r[0], b[0] = 0.0, 2000.0, 2000.0, 0.0
        info.FFI_GetPageViewRect = cb(F, "FFI_GetPageViewRect", view_rect)
        info.FFI_PageEvent = cb(F, "FFI_PageEvent", lambda s, n, ev: EVENTS.append(("pageevent", n, ev)))
        info.FFI_PopupMenu = cb(F, "FFI_PopupMenu", lambda *a: 0)
        info.FFI_OpenFile = cb(F, "FFI_OpenFile", lambda *a: (EVENTS.append(("BLOCKED openfile",)), None)[1])
        info.FFI_EmailTo = cb(F, "FFI_EmailTo", lambda *a: EVENTS.append(("BLOCKED email",)))
        info.FFI_UploadTo = cb(F, "FFI_UploadTo", lambda *a: EVENTS.append(("BLOCKED upload",)))
        def put_str(buf, n, text):
            raw = text.encode("utf-16-le") + b"\0\0"
            if buf and n >= len(raw):
                ctypes.memmove(buf, raw, len(raw))
            return len(raw)
        info.FFI_GetPlatform = cb(F, "FFI_GetPlatform", lambda s, b, n: put_str(b, n, "WIN"))
        info.FFI_GetLanguage = cb(F, "FFI_GetLanguage", lambda s, b, n: put_str(b, n, "FRA"))
        info.FFI_DownloadFromURL = cb(F, "FFI_DownloadFromURL", lambda *a: (EVENTS.append(("BLOCKED download",)), None)[1])
        info.FFI_PostRequestURL = cb(F, "FFI_PostRequestURL", lambda *a: (EVENTS.append(("BLOCKED post",)), 0)[1])
        info.FFI_PutRequestURL = cb(F, "FFI_PutRequestURL", lambda *a: (EVENTS.append(("BLOCKED put",)), 0)[1])
        info.FFI_OnFocusChange = cb(F, "FFI_OnFocusChange", lambda s, a, i: EVENTS.append(("focus", i)))
        info.FFI_DoURIActionWithKeyboardModifier = cb(F, "FFI_DoURIActionWithKeyboardModifier", lambda *a: EVENTS.append(("BLOCKED uri",)))
        self.info = info
        self.form = c.FPDFDOC_InitFormFillEnvironment(self.doc, ctypes.byref(info))
        self.xfa_loaded = None
        if self.form_type in (c.FORMTYPE_XFA_FULL, c.FORMTYPE_XFA_FOREGROUND):
            t0 = time.perf_counter()
            self.xfa_loaded = bool(c.FPDF_LoadXFA(self.doc))
            self.xfa_ms = (time.perf_counter() - t0) * 1000
        c.FPDF_SetFormFieldHighlightColor(self.form, 0, 0xFFE4DD)
        c.FPDF_SetFormFieldHighlightAlpha(self.form, 100)
        c.FORM_DoDocumentJSAction(self.form)
        c.FORM_DoDocumentOpenAction(self.form)

    def count(self):
        return c.FPDF_GetPageCount(self.doc)

    def page(self, i):
        if i not in self.pages:
            p = c.FPDF_LoadPage(self.doc, i)
            if not p:
                return None
            c.FORM_OnAfterLoadPage(p, self.form)
            c.FORM_DoPageAAction(p, self.form, c.FPDFPAGE_AACTION_OPEN)
            self.pages[i] = p
        return self.pages[i]

    def size(self, i):
        w, h = ctypes.c_double(), ctypes.c_double()
        c.FPDF_GetPageSizeByIndex(self.doc, i, ctypes.byref(w), ctypes.byref(h))
        return w.value, h.value

    def render(self, i, scale=1.0, forms=True):
        from PIL import Image
        p = self.page(i)
        w, h = self.size(i)
        W, H = int(w * scale), int(h * scale)
        bmp = c.FPDFBitmap_Create(W, H, 0)
        c.FPDFBitmap_FillRect(bmp, 0, 0, W, H, 0xFFFFFFFF)
        c.FPDF_RenderPageBitmap(bmp, p, 0, 0, W, H, 0, c.FPDF_ANNOT)
        if forms:
            c.FPDF_FFLDraw(self.form, bmp, p, 0, 0, W, H, 0, c.FPDF_ANNOT)
        buf = c.FPDFBitmap_GetBuffer(bmp)
        stride = c.FPDFBitmap_GetStride(bmp)
        data = ctypes.string_at(buf, stride * H)
        img = Image.frombuffer("RGBA", (W, H), data, "raw", "BGRA", stride, 1).convert("RGB")
        c.FPDFBitmap_Destroy(bmp)
        return img

    def text(self, i):
        tp = c.FPDFText_LoadPage(self.page(i))
        n = c.FPDFText_CountChars(tp)
        buf = (ctypes.c_ushort * (n + 1))()
        c.FPDFText_GetText(tp, 0, n, buf)
        c.FPDFText_ClosePage(tp)
        return bytes(buf)[: n * 2].decode("utf-16-le", "replace")

    def save(self, path, flags=0):
        chunks = []
        W = c.FPDF_FILEWRITE
        def write(s, data, size):
            chunks.append(ctypes.string_at(data, size))
            return 1
        fw = W()
        fw.version = 1
        fw.WriteBlock = cb(W, "WriteBlock", write)
        ok = c.FPDF_SaveAsCopy(self.doc, ctypes.byref(fw), flags)
        pathlib.Path(path).write_bytes(b"".join(chunks))
        return ok

    def close(self):
        for i, p in self.pages.items():
            c.FORM_DoPageAAction(p, self.form, c.FPDFPAGE_AACTION_CLOSE)
            c.FORM_OnBeforeClosePage(p, self.form)
            c.FPDF_ClosePage(p)
        self.pages.clear()
        c.FORM_DoDocumentAAction(self.form, c.FPDFDOC_AACTION_WC)
        c.FPDFDOC_ExitFormFillEnvironment(self.form)
        c.FPDF_CloseDocument(self.doc)


def page_to_dev(d, i, scale, x, y):
    """coordonnées page -> pixels (sans rotation)"""
    w, h = d.size(i)
    return x * scale, (h - y) * scale


def type_text(d, i, s):
    p = d.page(i)
    for ch in s:
        c.FORM_OnChar(d.form, p, ord(ch), 0)


def focused_text(d, i):
    p = d.page(i)
    n = c.FORM_GetFocusedText(d.form, p, None, 0)
    buf = ctypes.create_string_buffer(n)
    c.FORM_GetFocusedText(d.form, p, buf, n)
    return buf.raw.decode("utf-16-le", "replace").rstrip("\0")


def dev_to_page(d, i, scale, dx, dy):
    w, h = d.size(i)
    px, py = ctypes.c_double(), ctypes.c_double()
    c.FPDF_DeviceToPage(d.page(i), 0, 0, int(w * scale), int(h * scale), 0, int(dx), int(dy), ctypes.byref(px), ctypes.byref(py))
    return px.value, py.value


def click_dev(d, i, scale, dx, dy):
    x, y = dev_to_page(d, i, scale, dx, dy)
    click(d, i, x, y)
    return x, y


def click(d, i, x, y):
    p = d.page(i)
    c.FORM_OnMouseMove(d.form, p, 0, x, y)
    c.FORM_OnLButtonDown(d.form, p, 0, x, y)
    c.FORM_OnLButtonUp(d.form, p, 0, x, y)


def packet(d, name):
    doc = d.doc
    n = c.FPDF_GetXFAPacketCount(doc)
    for k in range(n):
        ln = c.FPDF_GetXFAPacketName(doc, k, None, 0)
        nb = ctypes.create_string_buffer(ln)
        c.FPDF_GetXFAPacketName(doc, k, nb, ln)
        if nb.value.decode() == name:
            size = ctypes.c_ulong()
            c.FPDF_GetXFAPacketContent(doc, k, None, 0, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            c.FPDF_GetXFAPacketContent(doc, k, buf, size.value, ctypes.byref(size))
            return buf.raw[: size.value]
    return b""


def interact(out, path):
    """Clic dans « Family Name » (IMM 1344 p.1), remplacement du texte, Tab, enregistrement, réouverture."""
    d = Doc(path)
    print("pages", d.count())
    c.FORM_OnMouseMove(d.form, d.page(0), 0, 5, 5)          # 1er événement : remise en page XFA
    print("pages après remise en page", d.count())
    reload_page(d, 0)
    EVENTS.clear()
    print(" clic page", click_dev(d, 0, 1.5, 100, 330))
    print(" après clic :", [e for e in EVENTS if e[0] != "inval"][:6])
    print(" texte du champ focalisé :", repr(focused_text(d, 0)))
    c.FORM_SelectAllText(d.form, d.page(0))
    t0 = time.perf_counter()
    type_text(d, 0, "Bernoulli")
    print(" saisie 9 car. %.1f ms" % ((time.perf_counter() - t0) * 1000))
    print(" après saisie :", repr(focused_text(d, 0)))
    EVENTS.clear()
    c.FORM_OnKeyDown(d.form, d.page(0), 0x09, 0)
    c.FORM_OnKeyUp(d.form, d.page(0), 0x09, 0)
    print(" après Tab :", [e for e in EVENTS if e[0] != "inval"][:4], "texte focalisé :", repr(focused_text(d, 0)))
    type_text(d, 0, "Jakob")
    print(" saisie dans le champ suivant :", repr(focused_text(d, 0)))
    c.FORM_ForceToKillFocus(d.form)
    d.render(0, 1.5).save(out / "imm1344_edited.png")
    ds = packet(d, "datasets")
    print(" datasets contient Bernoulli :", b"Bernoulli" in ds, "/ Jakob :", b"Jakob" in ds)
    saved = out / "imm1344_saved.pdf"
    t0 = time.perf_counter()
    ok = d.save(saved, 0)
    print(" enregistrement complet ok=%s %.0f ms, %d octets" % (ok, (time.perf_counter() - t0) * 1000, saved.stat().st_size))
    saved_inc = out / "imm1344_saved_incr.pdf"
    ok = d.save(saved_inc, c.FPDF_INCREMENTAL)
    print(" enregistrement incrémental ok=%s %d octets (original %d)" % (ok, saved_inc.stat().st_size, len(d.data)))
    d.close()
    for f in (saved, saved_inc):
        d2 = Doc(f)
        ds = packet(d2, "datasets")
        print(" réouverture %s : type %d xfa %s, Bernoulli %s, Jakob %s" % (f.name, d2.form_type, d2.xfa_loaded,
              b"Bernoulli" in ds, b"Jakob" in ds))
        d2.render(0, 1.5).save(out / (f.stem + "_reopen.png"))
        d2.close()


def scan(path, page=0, step=12):
    d = Doc(path)
    print("timers après chargement:", {k: v[0] for k, v in d.timers.items()}, "pages", d.count())
    p = d.page(page)
    print("timers après page:", {k: v[0] for k, v in d.timers.items()}, "pages", d.count())
    c.FPDFPage_HasFormFieldAtPoint(d.form, p, 10, 10)
    print("après 1er test:", [e for e in EVENTS if e[0] != "inval"], "pages", d.count())
    from PIL import ImageDraw
    img = d.render(page, 1.5).convert("RGBA")
    over = ImageDraw.Draw(img, "RGBA")
    w0, h0 = d.size(page)
    cols = {15: (255, 0, 0, 70), 9: (0, 160, 0, 90), 10: (0, 0, 255, 70), 13: (255, 160, 0, 90)}
    for yy in range(0, int(h0), 4):
        for xx in range(0, int(w0), 4):
            px, py = dev_to_page(d, page, 1.5, (xx + 2) * 1.5, (yy + 2) * 1.5)
            t = c.FPDFPage_HasFormFieldAtPoint(d.form, p, px, py)
            if t >= 0:
                over.rectangle([xx * 1.5, yy * 1.5, (xx + 4) * 1.5, (yy + 4) * 1.5], fill=cols.get(t, (128, 0, 128, 90)))
    img.save("tmp_shot/pdf/scan_overlay.png")
    print("overlay ok", flush=True)
    d.close()
    print("fermé", flush=True)
    return
    w, h = d.size(page)
    found = {}
    for yy in range(0, int(h), step):
        row = ""
        for xx in range(0, int(w), step):
            t = c.FPDFPage_HasFormFieldAtPoint(d.form, p, xx, h - yy)
            row += "." if t < 0 else "%x" % (t % 16)
            if t >= 0:
                found.setdefault(t, (xx, h - yy))
        print(row)
    print("types:", found, "count", d.count())
    d.close()





def settle(d):
    c.FORM_OnMouseMove(d.form, d.page(0), 0, 5, 5)
    reload_page(d, 0)


def roundtrip(out, path):
    """Aller-retour SANS saisie : original -> (remise en page) -> enregistrement -> réouverture."""
    d = Doc(path)
    settle(d)
    d.render(0, 1.5).save(out / "rt_orig_settled.png")
    for name, flags in (("rt_full.pdf", 0), ("rt_incr.pdf", c.FPDF_INCREMENTAL)):
        d.save(out / name, flags)
    raw = packet(d, "form")
    print("paquet form original :", len(raw), "octets")
    d.close()
    for name in ("rt_full.pdf", "rt_incr.pdf"):
        d2 = Doc(out / name)
        d2.render(0, 1.5).save(out / (name[:-4] + "_reopen.png"))
        settle(d2)
        d2.render(0, 1.5).save(out / (name[:-4] + "_reopen_settled.png"))
        f = packet(d2, "form")
        print(name, "pages", d2.count(), "paquet form", len(f), "octets ; datasets", len(packet(d2, "datasets")))
        (out / (name[:-4] + "_form.xml")).write_bytes(f)
        d2.close()
    (out / "orig_form.xml").write_bytes(raw)

if __name__ == "__main__" and sys.argv[1] not in ("exp", "scan", "interact", "rt"):
    out = pathlib.Path(sys.argv[1])
    for path in sys.argv[2:]:
        EVENTS.clear()
        t0 = time.perf_counter()
        d = Doc(path)
        ms = (time.perf_counter() - t0) * 1000
        name = pathlib.Path(path).stem
        print("\n==", name, "formtype", d.form_type, "xfa_loaded", d.xfa_loaded, "pages", d.count(), "open %.0f ms" % ms,
              ("xfa %.0f ms" % d.xfa_ms) if d.xfa_loaded is not None else "")
        print(" size p0", d.size(0))
        t0 = time.perf_counter()
        img = d.render(0, 1.5)
        print(" render p0 %.0f ms" % ((time.perf_counter() - t0) * 1000))
        img.save(out / (name + "_p0.png"))
        txt = d.text(0)
        print(" text p0 (%d car.) : %r" % (len(txt), txt[:160]))
        print(" events:", EVENTS[:12], "... total", len(EVENTS))
        d.close()


def reload_page(d, i):
    p = d.pages.pop(i, None)
    if p:
        c.FORM_DoPageAAction(p, d.form, c.FPDFPAGE_AACTION_CLOSE)
        c.FORM_OnBeforeClosePage(p, d.form)
        c.FPDF_ClosePage(p)
    return d.page(i)


def experiment(path):
    d = Doc(path)
    print("pages", d.count())
    p = d.page(0)
    EVENTS.clear()
    c.FORM_OnMouseMove(d.form, p, 0, 5, 5)
    print("après survol:", [e for e in EVENTS if e[0] != "inval"], "pages", d.count(), "timers", list(d.timers))
    for tid, (ms, fn) in list(d.timers.items()):
        fn(tid)
    print("après minuteries:", [e for e in EVENTS if e[0] != "inval"], "pages", d.count())
    reload_page(d, 0)
    EVENTS.clear()
    x, y = click_dev(d, 0, 1.5, 100, 330)
    print("clic", (round(x), round(y)), [e for e in EVENTS if e[0] != "inval"])
    print("annot focalisée:", bool(c.FORM_GetFocusedAnnot(d.form, ctypes.byref(ctypes.c_int()), ctypes.byref(c.FPDF_ANNOTATION()))))
    print("texte:", repr(focused_text(d, 0)))
    type_text(d, 0, "XY")
    print("après saisie:", repr(focused_text(d, 0)), [e for e in EVENTS if e[0] not in ("inval",)][-4:])
    d.close()


if __name__ == "__main__" and sys.argv[1] == "exp":
    experiment(sys.argv[2])

if __name__ == "__main__" and sys.argv[1] == "scan":
    scan(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 0)
    sys.exit()

if __name__ == "__main__" and sys.argv[1] == "interact":
    interact(pathlib.Path(sys.argv[2]), sys.argv[3])
    sys.exit()

if __name__ == "__main__" and sys.argv[1] == "rt":
    roundtrip(pathlib.Path(sys.argv[2]), sys.argv[3])
