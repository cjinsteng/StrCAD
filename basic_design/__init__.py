"""
basic_design/__init__.py
Basic Design — 부재별 기본 설계 모듈 (launcher.py 에서 호출)

    from basic_design import open_basic_design
    open_basic_design(self, username=self._user)

선택 흐름:  재료(RC / Steel / Other)  →  부재(Slab, Beam, …)  →  설계 방식(Lite / Pro / Table …)
새 설계 모듈은 CATALOG 의 해당 항목에 "open": "패키지.모듈:함수" 만 넣으면 연결된다.
"""
import importlib
import tkinter as tk
from tkinter import messagebox

from . import theme as T

__version__ = "0.1.0"

# ── 메뉴 구성 ────────────────────────────────────────────────
# open: "모듈경로:함수"  (없으면 '준비 중')
CATALOG = [
    {"id": "rc", "title": "RC", "sub": "철근콘크리트", "color": "#ef4444", "members": [
        {"id": "slab", "title": "Slab", "sub": "슬래브", "modes": [
            {"id": "lite", "title": "Lite", "sub": "1방향·2방향 등분포하중\n단일 슬래브 설계",
             "open": "basic_design.rc.slab_lite:open_slab_lite"},
            {"id": "pro", "title": "Pro", "sub": "집중·라인·분포하중 자유 재하\n유한요소해석 설계"},
            {"id": "table", "title": "Table", "sub": "강도·배근 입력 →\n배근별 모멘트 일람표"},
        ]},
        {"id": "beam", "title": "Beam", "sub": "보", "modes": [
            {"id": "lite", "title": "Lite", "sub": "단일 보 단면 설계"},
            {"id": "pro", "title": "Pro", "sub": "연속보 해석·설계"},
        ]},
        {"id": "column", "title": "Column", "sub": "기둥", "modes": [
            {"id": "lite", "title": "Lite", "sub": "P-M 상관도 단면 검토"},
        ]},
        {"id": "footing", "title": "Footing", "sub": "기초", "modes": [
            {"id": "lite", "title": "Lite", "sub": "독립기초 설계"},
        ]},
        {"id": "underground", "title": "Underground", "sub": "지하 구조", "modes": [
            {"id": "basement_wall", "title": "Basement Wall", "sub": "지하외벽 설계"},
            {"id": "buttress", "title": "Buttress", "sub": "부벽(버트레스) 설계"},
        ]},
    ]},
    {"id": "steel", "title": "Steel", "sub": "강구조", "color": "#60a5fa", "members": []},
    {"id": "other", "title": "Other", "sub": "기타", "color": "#a78bfa", "members": []},
]


class BasicDesignHub(tk.Toplevel):
    """재료 → 부재 → 설계 방식 선택 창"""

    def __init__(self, parent, username=""):
        super().__init__(parent)
        self.username = username
        self._mat = None
        self._mem = None
        self.title("Basic Design" + (f"  ─  {username}" if username else ""))
        self.configure(bg=T.BG)
        self.geometry("860x610")
        self.minsize(780, 560)
        T.set_icon(self)
        self._build()
        self.update_idletasks()
        try:
            px = parent.winfo_rootx() + parent.winfo_width() // 2
            py = parent.winfo_rooty() + parent.winfo_height() // 2
            self.geometry(f"+{max(px - 430, 0)}+{max(py - 305, 0)}")
        except tk.TclError:
            pass
        self.bind("<Escape>", lambda _: self.destroy())
        self._select_material(CATALOG[0])
        self.lift()
        self.focus_force()

    # ── 화면 ─────────────────────────────────────────────────
    def _build(self):
        hdr = tk.Frame(self, bg=T.BG2, height=58)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="📐  Basic Design", font=(T.FAM, 14, "bold"), bg=T.BG2, fg=T.WHI).pack(side="left", padx=22)
        tk.Label(hdr, text="재료  →  부재  →  설계 방식을 선택하세요", font=(T.FAM, 9), bg=T.BG2,
                 fg=T.TX2).pack(side="left", padx=6)
        tk.Frame(self, bg=T.BDR, height=1).pack(fill="x")

        body = tk.Frame(self, bg=T.BG)
        body.pack(fill="both", expand=True, padx=20, pady=18)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=2, uniform="c")
        body.columnconfigure(1, weight=3, uniform="c")
        body.columnconfigure(2, weight=4, uniform="c")
        self.col_mat, self.box_mat = self._column(body, 0, "① 재료")
        self.col_mem, self.box_mem = self._column(body, 1, "② 부재")
        self.col_mode, self.box_mode = self._column(body, 2, "③ 설계 방식")

    def _column(self, parent, col, title):
        f = tk.Frame(parent, bg=T.BG2, highlightbackground=T.BDR, highlightthickness=1)
        f.grid(row=0, column=col, sticky="nsew", padx=6)
        lbl = tk.Label(f, text=title, font=(T.FAM, 10, "bold"), bg=T.BG2, fg=T.TX2, anchor="w")
        lbl.pack(fill="x", padx=14, pady=(12, 6))
        tk.Frame(f, bg=T.BDR, height=1).pack(fill="x", padx=12)
        box = tk.Frame(f, bg=T.BG2)
        box.pack(fill="both", expand=True, padx=12, pady=10)
        return lbl, box

    def _item(self, parent, title, sub, on_click, selected=False, ready=True, accent=None, badge=None, arrow=False):
        """선택 카드 한 개"""
        bg = T.BG5 if selected else (T.BG4 if ready else T.BG3)
        fg = T.WHI if ready else T.DIS
        card = tk.Frame(parent, bg=bg, highlightthickness=1,
                        highlightbackground=(accent or T.ACCH) if selected else T.BDR,
                        cursor="hand2" if ready else "arrow")
        card.pack(fill="x", pady=4)
        if accent:
            tk.Frame(card, bg=accent if ready else T.DIS, width=4).pack(side="left", fill="y")
        inn = tk.Frame(card, bg=bg)
        inn.pack(side="left", fill="both", expand=True, padx=12, pady=8)
        top = tk.Frame(inn, bg=bg)
        top.pack(fill="x")
        tk.Label(top, text=title, font=(T.FAM, 12, "bold"), bg=bg, fg=fg, anchor="w").pack(side="left")
        if badge:
            tk.Label(top, text=f" {badge} ", font=(T.FAM, 7, "bold"), bg=T.GRN if ready else T.BG5,
                     fg=T.WHI if ready else T.TX3).pack(side="left", padx=8)
        if arrow:
            tk.Label(top, text="›", font=(T.FAM, 13, "bold"), bg=bg, fg=T.TX2 if ready else T.DIS).pack(side="right")
        if sub:
            tk.Label(inn, text=sub, font=(T.FAM, 8), bg=bg, fg=T.TX2 if ready else T.DIS, anchor="w",
                     justify="left").pack(fill="x", pady=(2, 0))

        def bind(w):
            w.bind("<Button-1>", lambda _: on_click())
            if ready and not selected:
                w.bind("<Enter>", lambda _: card.configure(highlightbackground=T.ACCH))
                w.bind("<Leave>", lambda _: card.configure(highlightbackground=T.BDR))
            for ch in w.winfo_children():
                bind(ch)
        bind(card)
        return card

    @staticmethod
    def _clear(box):
        for w in box.winfo_children():
            w.destroy()

    def _hint(self, box, text):
        tk.Label(box, text=text, font=(T.FAM, 9), bg=T.BG2, fg=T.TX3, justify="center").pack(expand=True)

    # ── 선택 동작 ────────────────────────────────────────────
    def _select_material(self, mat):
        self._mat, self._mem = mat, None
        self._clear(self.box_mat)
        for m in CATALOG:
            self._item(self.box_mat, m["title"], m["sub"], lambda m=m: self._select_material(m),
                       selected=(m is mat), ready=True, accent=m["color"], arrow=True)
        self.col_mem.config(text=f"② 부재  ·  {mat['title']}")
        self.col_mode.config(text="③ 설계 방식")
        self._clear(self.box_mem)
        self._clear(self.box_mode)
        if not mat["members"]:
            self._hint(self.box_mem, f"{mat['title']} 설계 모듈은\n준비 중입니다.")
            self._hint(self.box_mode, "")
            return
        for mem in mat["members"]:
            self._item(self.box_mem, mem["title"], mem["sub"], lambda mem=mem: self._select_member(mem),
                       ready=True, arrow=True)
        self._hint(self.box_mode, "부재를 선택하세요.")

    def _select_member(self, mem):
        self._mem = mem
        self._clear(self.box_mem)
        for m in self._mat["members"]:
            self._item(self.box_mem, m["title"], m["sub"], lambda m=m: self._select_member(m),
                       selected=(m is mem), ready=True, arrow=True)
        self.col_mode.config(text=f"③ 설계 방식  ·  {self._mat['title']} {mem['title']}")
        self._clear(self.box_mode)
        for mode in mem["modes"]:
            ready = bool(mode.get("open"))
            self._item(self.box_mode, mode["title"], mode["sub"], lambda mode=mode: self._open(mode),
                       ready=ready, badge=None if ready else "준비 중")

    def _open(self, mode):
        target = mode.get("open")
        label = f"{self._mat['title']} {self._mem['title']} — {mode['title']}"
        if not target:
            messagebox.showinfo("준비 중", f"{label}\n모듈 준비 중입니다.", parent=self)
            return
        try:
            mod, func = target.split(":")
            getattr(importlib.import_module(mod), func)(self.master, username=self.username)
        except Exception as e:           # noqa: BLE001
            import traceback
            messagebox.showerror("Basic Design 오류", f"{label}\n{e}\n\n{traceback.format_exc()}", parent=self)


_hub = {"win": None}


def open_basic_design(parent, username=""):
    """Basic Design 선택 창을 연다 (이미 열려 있으면 앞으로 가져온다)."""
    win = _hub["win"]
    if win is not None:
        try:
            if win.winfo_exists():
                win.deiconify(); win.lift(); win.focus_force()
                return win
        except tk.TclError:
            pass
    win = BasicDesignHub(parent, username=username)
    _hub["win"] = win
    return win
