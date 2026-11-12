#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GreenHub Key Gen — Windows 11 Fluent 界面（精简 + 动画）
=======================================================

* 字体：Tk 默认字体族（不硬编码 Segoe UI Variable），字号按 DPI 缩放
* 动画：分段指示器滑动、按钮悬浮渐变、结果淡入、主题切换渐变
* 精简：去掉副标题、结果标题、状态栏、DWM 徽标，输入框与按钮并排

运行：
  python greenhub_gui.py
  python greenhub_gui.py --dark
"""

import contextlib
import ctypes
import io
import os
import sys
import threading
import time
import tkinter as tk
import unicodedata
from tkinter import font as tkfont

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _import_core():
    try:
        import greenhub_keygen as m
        return m
    except ImportError as exc:
        raise SystemExit("缺少 greenhub_keygen.py：%s" % exc)


core = _import_core()

# ---------------------------------------------------------------- Win32

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWCP_ROUND = 2
DWMSBT_MAINWINDOW = 2


def enable_dpi_awareness():
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def system_dpi():
    try:
        return int(ctypes.windll.user32.GetDpiForSystem()) or 96
    except Exception:
        return 96


def _hwnd_of(win):
    hwnd = win.winfo_id()
    return ctypes.windll.user32.GetParent(hwnd) or hwnd


def apply_fluent(window, dark):
    """Mica / 圆角 / 深色标题栏；返回生效项给状态展示。"""
    caps = []
    try:
        hwnd = _hwnd_of(window)
        dwm, user32 = ctypes.windll.dwmapi, ctypes.windll.user32

        def set_attr(attr, value):
            v = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), attr, ctypes.byref(v),
                ctypes.sizeof(v)) == 0

        if set_attr(DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0):
            caps.append("dark")
        if set_attr(DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND):
            caps.append("round")
        if set_attr(DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_MAINWINDOW):
            caps.append("mica")
        set_attr(DWMWA_CAPTION_COLOR, 0x00202020 if dark else 0x00F3F3F3)
        set_attr(DWMWA_TEXT_COLOR, 0x00FFFFFF if dark else 0x001A1A1A)

        SWP = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020
        user32.SetWindowPos(ctypes.c_void_p(hwnd), None, 0, 0, 0, 0, SWP)
        user32.RedrawWindow(ctypes.c_void_p(hwnd), None, None, 0x0501)
        user32.SendMessageW(ctypes.c_void_p(hwnd), 0x031A, 0, 0)
        user32.SendMessageW(ctypes.c_void_p(hwnd), 0x0085, 1, 0)
    except Exception:
        pass
    return caps


def build_icon(root, color):
    try:
        img = tk.PhotoImage(width=32, height=32)
        img.put(color, to=(6, 6, 26, 26))
        img.put("#FFFFFF", to=(9, 9, 23, 23))
        img.put(color, to=(12, 14, 20, 18))
        img.put(color, to=(20, 14, 24, 16))
        root.iconphoto(True, img)
        root._icon_ref = img
    except Exception:
        pass


# ---------------------------------------------------------------- 主题

LIGHT = {
    "bg": "#F3F3F3", "card": "#FFFFFF", "field": "#FFFFFF",
    "field_stroke": "#E3E3E3", "stroke": "#E5E5E5",
    "text": "#1A1A1A", "sub": "#616161", "muted": "#909090",
    "accent": "#0067C0", "accent_hover": "#1A78CE", "accent_text": "#FFFFFF",
    "ok": "#0F7B0F", "bad": "#C42B1C",
    "seg_track": "#FFFFFF", "seg_track_stroke": "#E3E3E3",
    "seg_sel": "#EDEDED", "seg_sel_stroke": "#D6D6D6",
    "code_bg": "#FAFAFA", "code_stroke": "#E8E8E8",
    "ghost_hover": "#E9E9E9",
}

DARK = {
    "bg": "#1F1F1F", "card": "#2B2B2B", "field": "#323232",
    "field_stroke": "#474747", "stroke": "#3D3D3D",
    "text": "#FFFFFF", "sub": "#B0B0B0", "muted": "#8A8A8A",
    "accent": "#4CC2FF", "accent_hover": "#76D2FF", "accent_text": "#0A0A0A",
    "ok": "#6CCB5F", "bad": "#FF99A4",
    "seg_track": "#2B2B2B", "seg_track_stroke": "#3D3D3D",
    "seg_sel": "#3C3C3C", "seg_sel_stroke": "#4E4E4E",
    "code_bg": "#262626", "code_stroke": "#363636",
    "ghost_hover": "#3A3A3A",
}

MODES = [
    ("verify", "校验", "校验"),
    ("gen", "生成", "生成"),
    ("fromid", "派生", "派生"),
    ("hunt", "枚举", "枚举"),
]

HINT = {
    "verify": ("激活码", "24 位，含连字符"),
    "gen": ("Seed", "14 位字母数字"),
    "fromid": ("客户 ID", "cus_ 开头"),
    "hunt": ("数量", "默认 5"),
}


def _has_cjk(s):
    return any(unicodedata.east_asian_width(ch) in ("W", "F") for ch in s)


def _rgb(hexstr):
    h = hexstr.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lerp(c1, c2, t):
    """两色插值，返回 #RRGGBB。"""
    a, b = _rgb(c1), _rgb(c2)
    return "#%02X%02X%02X" % tuple(
        int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _ease_out(t):
    return 1 - (1 - t) ** 3


def _ease_in_out(t):
    return 3 * t * t - 2 * t * t * t


# ---------------------------------------------------------------- 主体

class App:
    W, H = 720, 520

    def __init__(self, root, dark=False):
        self.root = root
        self.dark = dark
        self.theme = DARK if dark else LIGHT
        self.mode = "verify"
        self.live_mode = False
        self.busy = False
        self.destroyed = False

        self.S = max(1.0, system_dpi() / 96.0)
        self._anims = {}
        self._redraw_job = None

        root.title("GreenHub Key Gen")
        root.minsize(self._px(620), self._px(440))
        root.geometry("%dx%d" % (self._px(self.W), self._px(self.H)))
        root.configure(bg=self.theme["bg"])
        build_icon(root, self.theme["accent"])

        self.cv = tk.Canvas(root, highlightthickness=0, bd=0,
                            bg=self.theme["bg"])
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<Configure>", self._on_resize)

        self._init_fonts()
        self._init_widgets()

        self.caps = apply_fluent(root, dark)
        root.after(20, self._redraw)
        root.bind("<Destroy>", self._on_destroy)
        root.bind("<Escape>", lambda e: self.root.destroy())

    # ---------------------------------------------------- 基础

    def _px(self, v):
        return int(round(v * self.S))

    def _init_fonts(self):
        """全部用 Tk 默认字体族，只改字号/粗细，DPI 交给 Tk 自己缩放。"""
        base = tkfont.nametofont("TkDefaultFont").actual()
        self.FAM = base["family"]
        size = base["size"]
        self._base = size           # 正数=磅，负数=像素，原样沿用

        def f(mult, bold=False, fam=None):
            fam = fam or self.FAM
            s = int(round(self._base * mult))
            if s == 0:
                s = 1 if self._base > 0 else -1
            return (fam, s, "bold" if bold else "normal")

        fixed = tkfont.nametofont("TkFixedFont").actual()["family"]
        self.F_TITLE = f(1.8, bold=True)
        self.F_SUB = f(1.0)
        self.F_BODY = f(1.0)
        self.F_LABEL = f(0.92)
        self.F_BTN = f(1.0, bold=True)
        self.F_SMALL = f(0.85)
        # 输出区也用默认字体族：对齐由 tab stop 保证，不需要等宽字体。
        # 中文 Windows 上 TkFixedFont 会落到「新宋体」，反而更难读。
        self.F_MONO = f(0.95)

    def _init_widgets(self):
        t = self.theme
        self.entry = tk.Entry(self.root, relief="flat", bd=0,
                              highlightthickness=0, bg=t["field"],
                              fg=t["text"], insertbackground=t["text"],
                              font=self.F_BODY)
        self.entry.bind("<Return>", lambda e: self._primary())
        self.entry.bind("<FocusIn>", self._focus_in)
        self.entry.bind("<FocusOut>", self._focus_out)
        self.entry.bind("<Key>", self._clear_ph)

        self.out = tk.Text(self.root, relief="flat", bd=0,
                           highlightthickness=0, bg=t["code_bg"],
                           fg=t["text"], font=self.F_MONO, wrap="none",
                           padx=self._px(11), pady=self._px(9),
                           selectbackground=t["accent"],
                           selectforeground=t["accent_text"],
                           state="disabled", cursor="arrow")
        self._retag()

        self.ph = ""
        self.showing_ph = False
        self._apply_placeholder()

        self.ph = ""
        self.showing_ph = False
        self._apply_placeholder()

    # ---------------------------------------------------- 动画引擎

    def _tw(self, key, duration, on_frame, on_done=None, ease=_ease_out):
        """通用补间：key 相同的动画会互相打断。"""
        self._cancel(key)
        start = time.perf_counter()

        def tick():
            t = (time.perf_counter() - start) / duration
            k = ease(min(1.0, t))
            try:
                on_frame(k)
            except tk.TclError:
                self._anims.pop(key, None)
                return
            if t >= 1.0:
                self._anims.pop(key, None)
                if on_done:
                    on_done()
                return
            self._anims[key] = self.root.after(16, tick)

        self._anims[key] = self.root.after(16, tick)

    def _cancel(self, key=None):
        keys = [key] if key else list(self._anims)
        for k in keys:
            job = self._anims.pop(k, None)
            if job:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass

    # ---------------------------------------------------- 占位符

    def _apply_placeholder(self):
        self.ph = HINT[self.mode][1]
        self.showing_ph = True
        self.entry.delete(0, "end")
        self.entry.insert(0, self.ph)
        self.entry.configure(fg=self.theme["muted"])

    def _focus_in(self, _e=None):
        if self.showing_ph:
            self.showing_ph = False
            self.entry.delete(0, "end")
            self.entry.configure(fg=self.theme["text"])
        self._redraw()

    def _focus_out(self, _e=None):
        if not self.entry.get().strip():
            self._apply_placeholder()
        self._redraw()

    def _clear_ph(self, _e=None):
        if self.showing_ph:
            self.showing_ph = False
            self.entry.delete(0, "end")
            self.entry.configure(fg=self.theme["text"])

    def _value(self):
        if self.showing_ph:
            return ""
        return self.entry.get().strip()

    # ---------------------------------------------------- 绘制

    def _on_resize(self, _e=None):
        if self.destroyed:
            return
        if self._redraw_job:
            try:
                self.root.after_cancel(self._redraw_job)
            except Exception:
                pass
        self._redraw_job = self.root.after(40, self._redraw)

    def _rr(self, x1, y1, x2, y2, r, fill="", outline="", width=1, tags=()):
        r = max(1, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
               x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
               x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.cv.create_polygon(pts, smooth=True, splinesteps=32,
                                      fill=fill, outline=outline,
                                      width=width, tags=tags)

    def _redraw(self, seg_from_x=None):
        self._redraw_job = None
        self._cancel("seg")
        cv, t = self.cv, self.theme
        cv.delete("all")
        cv.configure(bg=t["bg"])

        W = cv.winfo_width() or self._px(self.W)
        H = cv.winfo_height() or self._px(self.H)
        pad = self._px(28)

        # 标题 + 主题开关
        cv.create_text(pad, pad - self._px(6), text="GreenHub Key Gen",
                       font=self.F_TITLE, fill=t["text"], anchor="nw")
        gw, gh = self._px(34), self._px(30)
        self._ghost(W - pad - gw, pad - self._px(6), gw, gh,
                    "☾" if self.dark else "☀", "theme", self.F_BODY)
        cv.tag_bind("theme", "<Button-1>", lambda e: self._toggle_theme())
        cv.tag_bind("theme", "<Enter>", lambda e: self._hover("theme", 1))
        cv.tag_bind("theme", "<Leave>", lambda e: self._hover("theme", 0))

        # 分段控件
        seg_y = pad + self._px(46)
        seg_h = self._px(34)
        item_w = self._px(88)
        seg_w = item_w * len(MODES)
        seg_r = seg_h / 2
        self._rr(pad, seg_y, pad + seg_w, seg_y + seg_h, seg_r,
                 fill=t["seg_track"], outline=t["seg_track_stroke"])

        idx = [k for k, _l, _b in MODES].index(self.mode)
        target_x = pad + idx * item_w + self._px(3)
        here_x = target_x if seg_from_x is None else seg_from_x

        ind = self._rr(here_x, seg_y + self._px(3),
                       here_x + item_w - self._px(6), seg_y + seg_h - self._px(3),
                       seg_r - self._px(3),
                       fill=t["seg_sel"], outline=t["seg_sel_stroke"],
                       tags=("segind",))

        for i, (key, label, _b) in enumerate(MODES):
            sx = pad + i * item_w
            cv.create_text(sx + item_w / 2, seg_y + seg_h / 2, text=label,
                           font=self.F_BODY,
                           fill=t["text"] if key == self.mode else t["sub"],
                           anchor="center", tags=("segtxt_%s" % key,))
            hit = "seghit_%s" % key
            cv.create_rectangle(sx, seg_y, sx + item_w, seg_y + seg_h,
                                fill="", outline="", tags=(hit,))
            cv.tag_bind(hit, "<Button-1>", lambda e, k=key: self._set_mode(k))

        if seg_from_x is not None and abs(seg_from_x - target_x) > 1:
            self._tw("seg", 0.22, lambda k: cv.coords(
                ind, *self._seg_points(seg_from_x, target_x, seg_y,
                                       item_w, seg_h, k)),
                ease=_ease_in_out)

        # 输入行 + 按钮
        row_y = seg_y + seg_h + self._px(30)
        row_h = self._px(34)
        btn_w = self._px(84)
        btn_x = W - pad - btn_w

        if self.mode == "hunt":
            entry_w = self._px(88)
        else:
            entry_w = btn_x - self._px(10) - pad

        ex = pad
        focused = self.root.focus_get() is self.entry and not self.showing_ph
        self._rr(ex, row_y, ex + entry_w, row_y + row_h, self._px(6),
                 fill=t["field"],
                 outline=t["accent"] if focused else t["field_stroke"])
        self.entry.configure(bg=t["field"], fg=t["text"],
                             insertbackground=t["text"])
        nat = self.entry.winfo_reqheight() or self._px(20)
        cv.create_window(ex + self._px(9), row_y + row_h / 2,
                         window=self.entry, anchor="w",
                         width=entry_w - self._px(18),
                         height=min(nat, row_h))

        if self.mode == "hunt":
            self._checkbox(ex + entry_w + self._px(14),
                           row_y + (row_h - self._px(17)) / 2,
                           self.live_mode, "联网")
            cv.tag_bind("chk", "<Button-1>", lambda e: self._toggle_live())

        label, _hint = HINT[self.mode]
        cv.create_text(pad, row_y - self._px(12), text=label,
                       font=self.F_SMALL, fill=t["muted"], anchor="w")

        btn_label = "···" if self.busy else dict(
            (k, b) for k, _l, b in MODES)[self.mode]
        self._accent_btn(btn_x, row_y, btn_w, row_h, btn_label)

        # 输出区
        out_y = row_y + row_h + self._px(16)
        out_h = max(self._px(110), H - out_y - pad)
        out_w = W - pad * 2
        self._rr(pad, out_y, pad + out_w, out_y + out_h, self._px(8),
                 fill=t["code_bg"], outline=t["code_stroke"])
        self.out.configure(bg=t["code_bg"], fg=t["text"],
                           font=self.F_MONO,
                           selectbackground=t["accent"],
                           selectforeground=t["accent_text"])
        cv.create_window(pad + self._px(7), out_y + self._px(7),
                         window=self.out, anchor="nw",
                         width=out_w - self._px(14),
                         height=out_h - self._px(14))

    def _seg_points(self, x0, x1, seg_y, item_w, seg_h, k):
        x = x0 + (x1 - x0) * k
        r = seg_h / 2 - self._px(3)
        y1 = seg_y + self._px(3)
        y2 = seg_y + seg_h - self._px(3)
        rr = max(1, min(r, self._px(6)))
        return (x + rr, y1, x + item_w - self._px(6) - rr, y1,
                x + item_w - self._px(6), y1, x + item_w - self._px(6), y1 + rr,
                x + item_w - self._px(6), y2 - rr,
                x + item_w - self._px(6), y2,
                x + item_w - self._px(6) - rr, y2,
                x + rr, y2, x, y2, x, y2 - rr, x, y1 + rr, x, y1)

    def _accent_btn(self, x, y, w, h, label):
        t = self.theme
        self._rr(x, y, x + w, y + h, self._px(6), fill=t["accent"],
                 tags=("btn",))
        self.cv.create_text(x + w / 2, y + h / 2, text=label,
                            font=self.F_BTN, fill=t["accent_text"],
                            anchor="center", tags=("btn",))
        self.cv.tag_bind("btn", "<Button-1>", lambda e: self._primary())
        self.cv.tag_bind("btn", "<Enter>", lambda e: self._hover("btn", 1))
        self.cv.tag_bind("btn", "<Leave>", lambda e: self._hover("btn", 0))

    def _ghost(self, x, y, w, h, label, tag, font):
        t = self.theme
        self._rr(x, y, x + w, y + h, self._px(5), fill="", tags=(tag,))
        self.cv.create_text(x + w / 2, y + h / 2, text=label, font=font,
                            fill=t["sub"], anchor="center", tags=(tag,))

    def _checkbox(self, x, y, checked, label):
        t = self.theme
        b = self._px(17)
        if checked:
            self._rr(x, y, x + b, y + b, self._px(4), fill=t["accent"],
                     tags=("chk",))
            self.cv.create_text(x + b / 2, y + b / 2 - self._px(1), text="✓",
                                font=self.F_SMALL, fill=t["accent_text"],
                                anchor="center", tags=("chk",))
        else:
            self._rr(x, y, x + b, y + b, self._px(4), fill="",
                     outline=t["field_stroke"], tags=("chk",))
        self.cv.create_text(x + b + self._px(7), y + b / 2, text=label,
                            font=self.F_SMALL, fill=t["sub"], anchor="w",
                            tags=("chk",))

    def _hover(self, tag, on):
        """悬浮渐变动画：主按钮提亮 / 幽灵按钮浮出浅底。"""
        t = self.theme
        poly = [i for i in self.cv.find_withtag(tag)
                if self.cv.type(i) == "polygon"]
        if not poly:
            return
        cur = self.cv.itemcget(poly[0], "fill") or t["code_bg"]
        if tag == "btn":
            target = t["accent_hover"] if on else t["accent"]
        else:
            target = t["ghost_hover"] if on else t["bg"]

        def frame(k):
            c = _lerp(cur, target, k)
            for i in poly:
                try:
                    self.cv.itemconfigure(i, fill=c)
                except tk.TclError:
                    return

        self._tw("hover_" + tag, 0.14, frame)

    # ---------------------------------------------------- 输出

    def _render_rows(self, rows, silent=False):
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")
        for key, value, tone in rows:
            if not key and not value:
                self.out.insert("end", "\n")
                continue
            tag = "row_cn" if _has_cjk(key) else "row"
            if key:
                self.out.insert("end", key + "\t", (tag,))
            if value:
                self.out.insert("end", value, (tag, tone or ""))
            self.out.insert("end", "\n")
        self.out.configure(state="disabled")
        if rows and not silent:
            self._fade_in()

    def _fade_in(self):
        """结果从底色渐变到前景色。"""
        t = self.theme
        targets = {"row": t["text"], "row_cn": t["text"],
                   "val_ok": t["ok"], "val_bad": t["bad"]}
        start = t["code_bg"]

        def frame(k):
            for tag, dst in targets.items():
                try:
                    self.out.tag_configure(
                        tag, foreground=_lerp(start, dst, k))
                except tk.TclError:
                    return

        def done():
            for tag, dst in targets.items():
                self.out.tag_configure(tag, foreground=dst)

        self._tw("fade", 0.3, frame, done)

    def _render_text(self, text):
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")
        self.out.insert("1.0", text, ("row",))
        self.out.configure(state="disabled")
        self._fade_in()

    # ---------------------------------------------------- 交互

    def _set_mode(self, mode):
        if self.mode == mode:
            return
        old_x = self.cv.coords(self.cv.find_withtag("segind"))
        if old_x:
            old_x = old_x[0]
        self.mode = mode
        self.showing_ph = False
        self.entry.delete(0, "end")
        self._redraw(seg_from_x=old_x)
        self._apply_placeholder()
        self._render_rows([], silent=True)

    def _toggle_live(self):
        self.live_mode = not self.live_mode
        self._redraw()

    def _toggle_theme(self):
        old, new = self.theme, (LIGHT if self.dark else DARK)
        self._cancel()

        def frame(k):
            c = _lerp(old["bg"], new["bg"], k)
            self.cv.configure(bg=c)
            self.root.configure(bg=c)

        def done():
            self.dark = not self.dark
            self.theme = DARK if self.dark else LIGHT
            self._retag()
            self.out.configure(bg=self.theme["code_bg"],
                               selectbackground=self.theme["accent"],
                               selectforeground=self.theme["accent_text"])
            apply_fluent(self.root, self.dark)
            self._redraw()

        self._tw("theme", 0.2, frame, done)

    def _retag(self):
        """主题切换后重建输出区所有 tag 的前景色与 tab。"""
        t = self.theme
        tab = self._px(88)
        try:
            self.out.tag_configure("row", font=self.F_MONO, tabs=(tab,),
                                   foreground=t["text"])
            self.out.tag_configure("row_cn", font=self.F_MONO, tabs=(tab,),
                                   foreground=t["text"])
            self.out.tag_configure("val_ok", foreground=t["ok"])
            self.out.tag_configure("val_bad", foreground=t["bad"])
        except tk.TclError:
            pass

    def _fail(self, msg):
        self._render_rows([("!", msg, "val_bad")])

    def _primary(self):
        if self.busy:
            return
        raw = self._value()
        mode = self.mode

        if mode == "verify":
            if not raw:
                return self._fail("请输入激活码")
            ok, why = core.is_valid_key(raw)
            tone = "val_ok" if ok else "val_bad"
            rows = [("激活码", raw, tone),
                    ("结果", "有效" if ok else "无效", tone)]
            if ok:
                d = core.derive_from_customer_id("cus_" + raw.replace("-", "")[:14])
                rows += [("", "", None),
                         ("客户 ID", d["customerId"], None),
                         ("serial", d["serial"], None),
                         ("checksum", d["checksum"], None)]
            else:
                rows.append(("详情", why, None))
            return self._render_rows(rows)

        if mode == "gen":
            if not raw:
                return self._fail("请输入 14 位 Seed")
            try:
                key = core.derive_key(raw)
            except ValueError as exc:
                return self._fail(str(exc))
            ok = core.is_valid_key(key)[0]
            return self._render_rows([
                ("Seed", raw, None),
                ("serial", core.serial2(raw), None),
                ("checksum", core.checksum4(raw + core.serial2(raw)), None),
                ("", "", None),
                ("激活码", key, "val_ok" if ok else "val_bad"),
            ])

        if mode == "fromid":
            if not raw:
                return self._fail("请输入客户 ID")
            try:
                d = core.derive_from_customer_id(raw)
            except ValueError as exc:
                return self._fail(str(exc))
            ok = core.is_valid_key(d["key"])[0]
            return self._render_rows([
                ("客户 ID", d["customerId"], None),
                ("Seed", d["seed"], None),
                ("", "", None),
                ("激活码", d["key"], "val_ok" if ok else "val_bad"),
            ])

        if mode == "hunt":
            try:
                limit = max(1, min(50, int(raw or "5")))
            except ValueError:
                return self._fail("数量需为整数")
            self.busy = True
            self._redraw()
            self._run_hunt(limit, self.live_mode)

    def _run_hunt(self, limit, live):
        def work():
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    core.hunt(limit=limit, live=live)
                text = buf.getvalue()
            except Exception as exc:
                text = "枚举失败：%s" % exc
            self.root.after(0, lambda: self._hunt_done(text))

        threading.Thread(target=work, daemon=True).start()

    def _hunt_done(self, text):
        self.busy = False
        self._render_text(text.rstrip())
        self._redraw()

    def _on_destroy(self, e):
        if e.widget is self.root:
            self.destroyed = True
            self._cancel()


# ---------------------------------------------------------------- 入口

def main():
    enable_dpi_awareness()
    dark = "--dark" in sys.argv
    root = tk.Tk()
    App(root, dark=dark)
    root.mainloop()


if __name__ == "__main__":
    main()
