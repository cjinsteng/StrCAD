"""
design_2d/section/theme.py — 단면해석 화면 공통 색상·폰트·위젯 헬퍼
"""

import tkinter as tk
from tkinter import ttk

from ..constants import (BG, BG2, BG3, BG4, BG5, BDR, BDR2, ACC, ACCH,
                         GRN, GRNH, RED, ORG, YEL, BLU, CYN, PRP,
                         TXT, TX2, TX3, WHI, DIS, CANV_BG)

FONT = ("Malgun Gothic", 9)
FONT_B = ("Malgun Gothic", 9, "bold")
FONT_S = ("Malgun Gothic", 8)
FONT_H = ("Malgun Gothic", 10, "bold")
FONT_M = ("Consolas", 9)
FONT_C = ("Malgun Gothic", 8)          # 캔버스 라벨

# 캔버스 색상
C_GRID = "#162036"
C_GRID2 = "#1e2b47"
C_AXIS = "#2f4470"
C_RC = "#f87171"
C_STEEL = "#60a5fa"
C_ELEM = "#cbd5e1"
C_NODE = "#22c55e"
C_SEL = "#fbbf24"
C_HOV = "#ffffff"
C_DROP = "#22d3ee"
C_SUP = "#38bdf8"
C_LOAD = "#facc15"
C_LOAD2 = "#fb923c"
C_TXT = "#94a3b8"
C_M = "#f472b6"; C_M_F = "#3b1630"
C_V = "#34d399"; C_V_F = "#0f3027"
C_N = "#a78bfa"; C_N_F = "#251c45"
C_D = "#60a5fa"
C_R = "#facc15"

ORANGE = "#f97316"     # StrCAD 포인트 색


def setup_style(root):
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure(".", background=BG2, foreground=TXT, fieldbackground=BG3,
                 bordercolor=BDR, lightcolor=BG3, darkcolor=BG2, font=FONT)
    st.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(2, 4, 2, 0))
    st.configure("TNotebook.Tab", background=BG3, foreground=TX2,
                 padding=(12, 5), font=FONT_B, borderwidth=0)
    st.map("TNotebook.Tab",
           background=[("selected", BG2), ("active", BG4)],
           foreground=[("selected", WHI), ("active", TXT)])
    st.configure("Works.Treeview", background=BG2, fieldbackground=BG2,
                 foreground=TXT, rowheight=22, borderwidth=0, font=FONT)
    st.map("Works.Treeview", background=[("selected", ACC)],
           foreground=[("selected", WHI)])
    st.configure("Works.Treeview.Heading", background=BG3, foreground=TX2,
                 font=FONT_S, relief="flat")
    st.configure("Tbl.Treeview", background=BG2, fieldbackground=BG2,
                 foreground=TXT, rowheight=20, borderwidth=0, font=FONT_M)
    st.map("Tbl.Treeview", background=[("selected", ACC)])
    st.configure("Tbl.Treeview.Heading", background=BG4, foreground=TXT,
                 font=FONT_S, relief="flat")
    st.map("Tbl.Treeview.Heading", background=[("active", BG5)])
    st.configure("TCombobox", fieldbackground=BG3, background=BG4,
                 foreground=TXT, arrowcolor=TX2, selectbackground=BG3,
                 selectforeground=WHI)
    st.map("TCombobox", fieldbackground=[("readonly", BG3)],
           foreground=[("readonly", TXT)])
    root.option_add("*TCombobox*Listbox.background", BG3)
    root.option_add("*TCombobox*Listbox.foreground", TXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACC)
    root.option_add("*TCombobox*Listbox.font", FONT)
    st.configure("Vertical.TScrollbar", background=BG4, troughcolor=BG2,
                 bordercolor=BG2, arrowcolor=TX2)
    st.configure("Horizontal.TScrollbar", background=BG4, troughcolor=BG2,
                 bordercolor=BG2, arrowcolor=TX2)
    return st


# ── 위젯 헬퍼 ───────────────────────────────────────────────
def btn(parent, text, cmd, bg=BG3, fg=TXT, font=FONT, padx=8, pady=3, **kw):
    b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, font=font,
                  activebackground=BG5, activeforeground=WHI, relief="flat",
                  bd=0, cursor="hand2", padx=padx, pady=pady,
                  highlightthickness=0, **kw)
    return b


def section_title(parent, text, color=CYN):
    f = tk.Frame(parent, bg=BG2)
    f.pack(fill="x", pady=(10, 4))
    tk.Frame(f, bg=color, width=3, height=14).pack(side="left", padx=(0, 6))
    tk.Label(f, text=text, font=FONT_B, bg=BG2, fg=WHI).pack(side="left")
    return f


def entry(parent, var, width=10, **kw):
    return tk.Entry(parent, textvariable=var, width=width, bg=BG3, fg=WHI,
                    insertbackground=WHI, relief="flat", font=FONT,
                    highlightthickness=1, highlightbackground=BDR,
                    highlightcolor=ACCH, **kw)


def combo(parent, var, values, width=14, state="readonly"):
    cb = ttk.Combobox(parent, textvariable=var, values=values, width=width,
                      state=state, font=FONT)
    return cb


def check(parent, text, var, **kw):
    return tk.Checkbutton(parent, text=text, variable=var, bg=BG2, fg=TXT,
                          selectcolor=BG4, activebackground=BG2,
                          activeforeground=WHI, font=FONT,
                          highlightthickness=0, bd=0, **kw)


def radio(parent, text, var, value, **kw):
    return tk.Radiobutton(parent, text=text, variable=var, value=value,
                          bg=BG2, fg=TXT, selectcolor=BG4,
                          activebackground=BG2, activeforeground=WHI,
                          font=FONT, highlightthickness=0, bd=0, **kw)


class Form:
    """라벨 | 위젯 2열 그리드 폼"""

    def __init__(self, parent, lw=12):
        self.f = tk.Frame(parent, bg=BG2)
        self.f.pack(fill="x", padx=2)
        self.f.columnconfigure(1, weight=1)
        self.r = 0
        self.lw = lw

    def row(self, label, widget_fn, unit=""):
        tk.Label(self.f, text=label, font=FONT, bg=BG2, fg=TX2,
                 width=self.lw, anchor="w").grid(row=self.r, column=0,
                                                 sticky="w", pady=2)
        w = widget_fn(self.f)
        w.grid(row=self.r, column=1, sticky="ew", pady=2)
        if unit:
            tk.Label(self.f, text=unit, font=FONT_S, bg=BG2, fg=TX3).grid(
                row=self.r, column=2, sticky="w", padx=(4, 0))
        self.r += 1
        return w

    def text(self, label, value, fg=TXT):
        tk.Label(self.f, text=label, font=FONT, bg=BG2, fg=TX2,
                 width=self.lw, anchor="w").grid(row=self.r, column=0, sticky="w", pady=1)
        lb = tk.Label(self.f, text=value, font=FONT, bg=BG2, fg=fg, anchor="w")
        lb.grid(row=self.r, column=1, columnspan=2, sticky="w", pady=1)
        self.r += 1
        return lb


def fnum(v, nd=2):
    try:
        v = float(v)
    except Exception:
        return str(v)
    if abs(v) < 0.5 * 10 ** (-nd):
        v = 0.0
    return f"{v:.{nd}f}"


def parse_float(s, default=None):
    try:
        return float(str(s).replace(",", "").strip())
    except Exception:
        return default


class ScrollFrame(tk.Frame):
    """세로 스크롤 가능한 프레임 (self.inner 에 위젯 배치)"""

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG2, **kw)
        self.cv = tk.Canvas(self, bg=BG2, highlightthickness=0, bd=0)
        self.vs = ttk.Scrollbar(self, orient="vertical", command=self.cv.yview)
        self.inner = tk.Frame(self.cv, bg=BG2)
        self._win = self.cv.create_window(0, 0, window=self.inner, anchor="nw")
        self.cv.configure(yscrollcommand=self.vs.set)
        self.cv.pack(side="left", fill="both", expand=True)
        self.vs.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self.cv.bind("<Configure>", lambda e: self.cv.itemconfigure(self._win, width=e.width))
        for w in (self.cv, self.inner):
            w.bind("<Enter>", self._bind_wheel)
            w.bind("<Leave>", self._unbind_wheel)

    def _bind_wheel(self, e):
        self.cv.bind_all("<MouseWheel>", self._wheel)
        self.cv.bind_all("<Button-4>", lambda e: self.cv.yview_scroll(-2, "units"))
        self.cv.bind_all("<Button-5>", lambda e: self.cv.yview_scroll(2, "units"))

    def _unbind_wheel(self, e):
        self.cv.unbind_all("<MouseWheel>")
        self.cv.unbind_all("<Button-4>")
        self.cv.unbind_all("<Button-5>")

    def _wheel(self, e):
        if self.inner.winfo_reqheight() > self.cv.winfo_height():
            self.cv.yview_scroll(int(-e.delta / 120) * 2, "units")

    def clear(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.cv.yview_moveto(0)
