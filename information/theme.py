"""
information/theme.py — Information 화면 색상·폰트·위젯 헬퍼 (런처·2D Design 과 같은 팔레트)
"""
import tkinter as tk
from tkinter import ttk

BG = "#0f1520"; BG2 = "#141d2e"; BG3 = "#1a2540"; BG4 = "#1f2d4a"; BG5 = "#263556"
BDR = "#2c3f62"; BDR2 = "#3a5280"
ACC = "#1a56db"; ACCH = "#2563eb"
GRN = "#15803d"; GRNH = "#16a34a"
RED = "#dc2626"; ORG = "#d97706"; YEL = "#f59e0b"
BLU = "#3b82f6"; CYN = "#06b6d4"; PRP = "#8b5cf6"
TXT = "#dde4f0"; TX2 = "#8fa3c0"; TX3 = "#546887"
WHI = "#f0f5ff"; DIS = "#3d5070"
CANV_BG = "#0a0e18"
ORANGE = "#f97316"

C_WIND = "#38bdf8"
C_SEIS = "#f87171"
C_SNOW = "#e2e8f0"
C_GEO = "#a78bfa"
C_OK = "#22c55e"
C_WARN = "#fbbf24"

FONT = ("Malgun Gothic", 9)
FONT_B = ("Malgun Gothic", 9, "bold")
FONT_S = ("Malgun Gothic", 8)
FONT_H = ("Malgun Gothic", 11, "bold")
FONT_BIG = ("Malgun Gothic", 16, "bold")
FONT_M = ("Consolas", 9)


def setup_style(root):
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure(".", background=BG2, foreground=TXT, fieldbackground=BG3,
                 bordercolor=BDR, lightcolor=BG3, darkcolor=BG2, font=FONT)
    st.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(2, 4, 2, 0))
    st.configure("TNotebook.Tab", background=BG3, foreground=TX2, padding=(14, 6), font=FONT_B, borderwidth=0)
    st.map("TNotebook.Tab", background=[("selected", BG2), ("active", BG4)],
           foreground=[("selected", WHI), ("active", TXT)])
    st.configure("Info.Treeview", background=BG2, fieldbackground=BG2, foreground=TXT,
                 rowheight=22, borderwidth=0, font=FONT)
    st.map("Info.Treeview", background=[("selected", ACC)], foreground=[("selected", WHI)])
    st.configure("Info.Treeview.Heading", background=BG4, foreground=TXT, font=FONT_S, relief="flat")
    st.map("Info.Treeview.Heading", background=[("active", BG5)])
    st.configure("TCombobox", fieldbackground=BG3, background=BG4, foreground=TXT, arrowcolor=TX2,
                 selectbackground=BG3, selectforeground=WHI)
    st.map("TCombobox", fieldbackground=[("readonly", BG3)], foreground=[("readonly", TXT)])
    root.option_add("*TCombobox*Listbox.background", BG3)
    root.option_add("*TCombobox*Listbox.foreground", TXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACC)
    root.option_add("*TCombobox*Listbox.font", FONT)
    for o in ("Vertical", "Horizontal"):
        st.configure(f"{o}.TScrollbar", background=BG4, troughcolor=BG2, bordercolor=BG2, arrowcolor=TX2)
    st.configure("Info.Horizontal.TProgressbar", background=ACCH, troughcolor=BG3, bordercolor=BG3)
    return st


def btn(parent, text, cmd, bg=BG4, fg=TXT, font=FONT, padx=8, pady=3, **kw):
    b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, font=font,
                  activebackground=BG5, activeforeground=WHI, relief="flat",
                  bd=0, cursor="hand2", padx=padx, pady=pady, highlightthickness=0, **kw)
    return b


def entry(parent, var, width=10, **kw):
    return tk.Entry(parent, textvariable=var, width=width, bg=BG3, fg=WHI, insertbackground=WHI,
                    relief="flat", font=FONT, highlightthickness=1, highlightbackground=BDR,
                    highlightcolor=ACCH, **kw)


def combo(parent, var, values, width=14, state="readonly"):
    return ttk.Combobox(parent, textvariable=var, values=values, width=width, state=state, font=FONT)


def check(parent, text, var, bg=BG2, **kw):
    return tk.Checkbutton(parent, text=text, variable=var, bg=bg, fg=TXT, selectcolor=BG4,
                          activebackground=bg, activeforeground=WHI, font=FONT,
                          highlightthickness=0, bd=0, **kw)


def label(parent, text="", fg=TX2, font=FONT, bg=BG2, **kw):
    return tk.Label(parent, text=text, fg=fg, font=font, bg=bg, **kw)


def section(parent, text, color=CYN, bg=BG2):
    f = tk.Frame(parent, bg=bg)
    f.pack(fill="x", pady=(10, 4))
    tk.Frame(f, bg=color, width=3, height=14).pack(side="left", padx=(0, 6))
    tk.Label(f, text=text, font=FONT_B, bg=bg, fg=WHI).pack(side="left")
    return f


def tree(parent, cols, widths, height=8, anchors=None):
    fr = tk.Frame(parent, bg=BG2)
    tv = ttk.Treeview(fr, columns=cols, show="headings", height=height, style="Info.Treeview")
    for i, (c, w) in enumerate(zip(cols, widths)):
        tv.heading(c, text=c)
        tv.column(c, width=w, anchor=(anchors[i] if anchors else ("w" if i == 0 else "center")), stretch=True)
    sb = ttk.Scrollbar(fr, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=sb.set)
    tv.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return fr, tv


class ScrollFrame(tk.Frame):
    """세로 스크롤 되는 영역 — .inner 에 위젯을 넣는다."""

    def __init__(self, parent, bg=BG2, width=None):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, width=width or 300)
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.sb.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        for w in (self.canvas, self.inner):
            w.bind("<Enter>", lambda e: self._bind_wheel(True))
            w.bind("<Leave>", lambda e: self._bind_wheel(False))

    def _bind_wheel(self, on):
        if on:
            self.canvas.bind_all("<MouseWheel>", self._wheel)
            self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
            self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(2, "units"))
        else:
            self.canvas.unbind_all("<MouseWheel>")
            self.canvas.unbind_all("<Button-4>")
            self.canvas.unbind_all("<Button-5>")

    def _wheel(self, e):
        self.canvas.yview_scroll(int(-e.delta / 120) * 2, "units")
