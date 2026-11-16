"""
basic_design/rc/slab_lite.py
RC Slab — Lite : 1방향 / 2방향 단일 슬래브(등분포하중) 설계 창

  왼쪽  입력 패널 (Name · Type · 치수 · 재료 · 하중 · 지지 형식 · 사용 철근)
  오른쪽 계산서 (Design Conditions / Min. Thk. / Flexure / Summary / Shear)
"""
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .. import theme as T
from ..report import render, fonts
from . import slab_calc as S
from . import slab_report as R
from .slab_coef import CASE_EDGES, CASE_DESC

TYPE_1WAY = "1방향 슬래브"
TYPE_2WAY = "2방향 슬래브"
SPAN_OPTS = {"3경간 이상": 3, "2경간": 2}
FILE_TYPES = [("Slab Lite 파일", "*.slab"), ("모든 파일", "*.*")]

DEFAULTS = {
    "name": "S1", "type": TYPE_2WAY,
    "span": "4", "lx": "4", "ly": "6", "t": "150", "cc": "20",
    "fck": "24", "fy13": "400", "fy16": "500", "wd": "5", "wl": "3",
    "support": S.ONE_WAY_SUPPORTS["CC"][0], "spans": "3경간 이상", "expo": "그 외 환경 (κcr=210)",
    "case": "Case2", "bar": "D10",
    "b1b": "400", "b1h": "600", "b2b": "400", "b2h": "600", "b3b": "400", "b3h": "600", "b4b": "400", "b4h": "600",
}
LABELS = {
    "span": "Span", "lx": "Lx", "ly": "Ly", "t": "두께 T", "cc": "피복 Cc", "fck": "fck", "fy13": "fy(D13↓)",
    "fy16": "fy(D16↑)", "wd": "고정하중 Wd", "wl": "활하중 Wl",
    "b1b": "B1 폭", "b1h": "B1 춤", "b2b": "B2 폭", "b2h": "B2 춤", "b3b": "B3 폭", "b3h": "B3 춤", "b4b": "B4 폭", "b4h": "B4 춤",
}


class SlabLiteWindow:
    def __init__(self, parent, username=""):
        self.user = username
        self.path = None
        self.result = None
        self.report = None
        self.win = win = tk.Toplevel(parent)
        win.title("StrCAD - Basic Design │ RC Slab Lite" + (f"  ─  {username}" if username else ""))
        win.geometry("1300x840")
        win.minsize(1080, 620)
        win.configure(bg=T.SURFACE)
        T.set_icon(win)
        self.v = {k: tk.StringVar(win, value=val) for k, val in DEFAULTS.items()}
        self._style()
        self._build()
        self.v["type"].trace_add("write", lambda *_: self._on_type())
        self.v["case"].trace_add("write", lambda *_: self._draw_case())
        win.bind("<Return>", lambda _: self.calc())
        win.bind("<F5>", lambda _: self.calc())
        win.bind("<Control-s>", lambda _: self.save())
        win.bind("<Control-o>", lambda _: self.open())
        self._on_type()
        win.lift()
        win.focus_force()

    # ── 스타일 ───────────────────────────────────────────────
    def _style(self):
        st = ttk.Style(self.win)
        st.configure("BD.TCombobox", padding=2)
        self.f_n = (T.FAM, 9)
        self.f_b = (T.FAM, 9, "bold")

    # ── 화면 구성 ────────────────────────────────────────────
    def _build(self):
        win = self.win
        bar = tk.Frame(win, bg=T.NAVY, height=44)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, text="RC Slab", font=(T.FAM, 13, "bold"), bg=T.NAVY, fg="white").pack(side="left", padx=(16, 6))
        tk.Label(bar, text=" Lite ", font=(T.FAM, 8, "bold"), bg=T.ORANGE, fg="white").pack(side="left")
        tk.Label(bar, text="단일 슬래브 · 등분포하중 · 1방향 / 2방향", font=(T.FAM, 9), bg=T.NAVY,
                 fg="#B9C4DA").pack(side="left", padx=14)
        for txt, cmd in (("계산서 복사", self.copy_report), ("계산서 저장", self.save_report), ("저장", self.save),
                         ("열기", self.open), ("새로 만들기", self.new)):
            b = tk.Button(bar, text=txt, command=cmd, font=self.f_n, bg=T.NAVY_2, fg="white", relief="flat",
                          activebackground=T.ORANGE, activeforeground="white", cursor="hand2", padx=10, pady=3)
            b.pack(side="right", padx=(0, 6), pady=8)

        self.status = tk.Label(win, text="", anchor="w", font=self.f_n, bg="#E5E9F0", fg=T.INK, padx=12, pady=4)
        self.status.pack(fill="x", side="bottom")

        left = tk.Frame(win, bg=T.SURFACE, width=398)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Frame(win, bg=T.LINE, width=1).pack(side="left", fill="y")
        self._build_left(left)

        right = tk.Frame(win, bg=T.PANEL)
        right.pack(side="left", fill="both", expand=True)
        self.cv = cv = tk.Canvas(right, bg=T.PANEL, highlightthickness=0)
        vs = ttk.Scrollbar(right, orient="vertical", command=cv.yview)
        hs = ttk.Scrollbar(right, orient="horizontal", command=cv.xview)
        cv.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        vs.pack(side="right", fill="y")
        hs.pack(side="bottom", fill="x")
        cv.pack(fill="both", expand=True)
        cv.bind("<MouseWheel>", lambda e: cv.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        cv.bind("<Button-4>", lambda _: cv.yview_scroll(-1, "units"))
        cv.bind("<Button-5>", lambda _: cv.yview_scroll(1, "units"))

    def _group(self, parent, title):
        return tk.LabelFrame(parent, text=title, font=self.f_b, bg=T.SURFACE, fg=T.NAVY, bd=1, relief="groove",
                             padx=8, pady=6)

    def _lbl(self, parent, text, **kw):
        kw.setdefault("fg", T.INK)
        return tk.Label(parent, text=text, font=self.f_n, bg=T.SURFACE, **kw)

    def _ent(self, parent, key, width=7):
        e = tk.Entry(parent, textvariable=self.v[key], width=width, font=self.f_n, fg=T.INPUT_FG, bg="white",
                     relief="solid", bd=1, highlightthickness=0)
        e.bind("<FocusIn>", lambda _: e.select_range(0, "end"))
        return e

    def _cmb(self, parent, key, values, width=7, state="normal"):
        return ttk.Combobox(parent, textvariable=self.v[key], values=values, width=width, state=state,
                            font=self.f_n, style="BD.TCombobox")

    def _field(self, parent, row, label, key, unit, width=7, widget=None):
        self._lbl(parent, label, anchor="e").grid(row=row, column=0, sticky="e", pady=2)
        w = widget or self._ent(parent, key, width)
        w.grid(row=row, column=1, sticky="w", padx=(4, 4), pady=2)
        if unit:
            self._lbl(parent, unit).grid(row=row, column=2, sticky="w")
        return w

    def _build_left(self, p):
        top = tk.Frame(p, bg=T.SURFACE)
        top.pack(fill="x", padx=10, pady=(12, 6))
        f = tk.Frame(top, bg=T.SURFACE)
        f.pack(side="left")
        self._lbl(f, "Name :").grid(row=0, column=0, sticky="e", pady=2)
        self._ent(f, "name", 15).grid(row=0, column=1, sticky="w", padx=4)
        self._lbl(f, "Type :").grid(row=1, column=0, sticky="e", pady=2)
        self._cmb(f, "type", [TYPE_1WAY, TYPE_2WAY], 13, "readonly").grid(row=1, column=1, sticky="w", padx=4)
        b = tk.Button(top, text="계   산", command=self.calc, font=(T.FAM, 11, "bold"), bg=T.ORANGE, fg="white",
                      activebackground=T.ORANGE_D, activeforeground="white", relief="flat", cursor="hand2",
                      padx=20, pady=8)
        b.pack(side="right")

        row1 = tk.Frame(p, bg=T.SURFACE)
        row1.pack(fill="x", padx=10, pady=4)
        self.g_dim = self._group(row1, "슬래브 치수")
        self.g_dim.pack(side="left", fill="y")
        g = self._group(row1, "재료강도")
        g.pack(side="left", fill="y", padx=(8, 0))
        self._field(g, 0, "fck :", "fck", "N/mm²", widget=self._cmb(g, "fck", ["21", "24", "27", "30", "35", "40"], 5))
        self._field(g, 1, "fy(D13↓) :", "fy13", "N/mm²", widget=self._cmb(g, "fy13", ["300", "400", "500", "600"], 5))
        self._field(g, 2, "fy(D16↑) :", "fy16", "N/mm²", widget=self._cmb(g, "fy16", ["300", "400", "500", "600"], 5))

        row2 = tk.Frame(p, bg=T.SURFACE)
        row2.pack(fill="x", padx=10, pady=4)
        g = self._group(row2, "두께")
        g.pack(side="left", fill="y")
        self._field(g, 0, "T :", "t", "mm")
        self._field(g, 1, "Cc :", "cc", "mm")
        g = self._group(row2, "하중")
        g.pack(side="left", fill="y", padx=(8, 0))
        self._field(g, 0, "Wd :", "wd", "kN/m²")
        self._field(g, 1, "Wl :", "wl", "kN/m²")

        self.g_sup = tk.Frame(p, bg=T.SURFACE)
        self.g_sup.pack(fill="x", padx=10, pady=4)

        row4 = tk.Frame(p, bg=T.SURFACE)
        row4.pack(fill="x", padx=10, pady=4)
        self.g_bar = self._group(row4, "사용 철근")
        self.g_bar.pack(side="left", fill="y")

        tk.Label(p, text="Enter / F5 : 계산     Ctrl+S : 저장     Ctrl+O : 열기", font=(T.FAM, 8), bg=T.SURFACE,
                 fg=T.MUTED).pack(side="bottom", pady=8)

    # ── Type 에 따라 달라지는 입력 ───────────────────────────
    def _on_type(self):
        one = self.v["type"].get() == TYPE_1WAY
        for g in (self.g_dim, self.g_sup, self.g_bar):
            for w in g.winfo_children():
                w.destroy()
        # 치수
        if one:
            self._field(self.g_dim, 0, "Span :", "span", "m")
            self._lbl(self.g_dim, "(순경간 ln)", fg=T.MUTED).grid(row=1, column=0, columnspan=3, sticky="w")
        else:
            self._field(self.g_dim, 0, "Lx :", "lx", "m")
            self._field(self.g_dim, 1, "Ly :", "ly", "m")
            self._lbl(self.g_dim, "(Lx ≤ Ly, 중심간)", fg=T.MUTED).grid(row=2, column=0, columnspan=3, sticky="w")
        # 지지 형식
        if one:
            g = self._group(self.g_sup, "지지형식")
            g.pack(fill="x")
            self._field(g, 0, "지지형식 :", "support", "",
                        widget=self._cmb(g, "support", [v[0] for v in S.ONE_WAY_SUPPORTS.values()], 22, "readonly"))
            self._field(g, 1, "경간 수 :", "spans", "", widget=self._cmb(g, "spans", list(SPAN_OPTS), 22, "readonly"))
            self._lbl(g, "※ 모멘트 계수법 (KDS 14 20 10 4.3.1 근사해법)", fg=T.MUTED).grid(
                row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        else:
            g = self._group(self.g_sup, "슬래브 지지 형식")
            g.pack(side="left", fill="y")
            self.case_cv = tk.Canvas(g, width=78, height=92, bg=T.SURFACE, highlightthickness=0)
            self.case_cv.grid(row=0, column=0, padx=(2, 6))
            f = tk.Frame(g, bg=T.SURFACE)
            f.grid(row=0, column=1, sticky="n")
            self._cmb(f, "case", [f"Case{i}" for i in range(1, 10)], 7, "readonly").pack(anchor="w", pady=(6, 4))
            self.case_lbl = self._lbl(f, "", fg=T.MUTED)
            self.case_lbl.pack(anchor="w")
            self._lbl(f, "빗금 = 연속단", fg="#c026d3").pack(anchor="w")
            g2 = self._group(self.g_sup, "지지보 치수 (b × h)")
            g2.pack(side="left", fill="y", padx=(8, 0))
            for i in range(1, 5):
                self._lbl(g2, f"B{i}:").grid(row=i - 1, column=0, sticky="e", pady=1)
                self._ent(g2, f"b{i}b", 5).grid(row=i - 1, column=1, padx=(3, 2))
                self._lbl(g2, "×").grid(row=i - 1, column=2)
                self._ent(g2, f"b{i}h", 5).grid(row=i - 1, column=3, padx=(2, 3))
                if i == 1:
                    self._lbl(g2, "mm").grid(row=0, column=4, sticky="w")
                else:
                    tk.Button(g2, text="↑", font=(T.FAM, 7), width=2, relief="groove", bg="white", cursor="hand2",
                              command=lambda k=i: self._copy_beam(k)).grid(row=i - 1, column=4, sticky="w")
            self._draw_case()
        # 사용 철근
        self._field(self.g_bar, 0, "철근 :", "bar", "", widget=self._cmb(self.g_bar, "bar", ["D10", "D13", "D16"], 6, "readonly"))
        if one:
            self._field(self.g_bar, 1, "노출환경 :", "expo", "",
                        widget=self._cmb(self.g_bar, "expo", list(S.EXPOSURES), 19, "readonly"))
        self.calc(silent=True)

    def _copy_beam(self, i):
        """↑ : 바로 위 보 치수를 복사"""
        self.v[f"b{i}b"].set(self.v[f"b{i - 1}b"].get())
        self.v[f"b{i}h"].set(self.v[f"b{i - 1}h"].get())

    def _case_no(self):
        try:
            return int(self.v["case"].get().replace("Case", "").strip())
        except ValueError:
            return 2

    def _draw_case(self):
        cv = getattr(self, "case_cv", None)
        if cv is None or not cv.winfo_exists():
            return
        cv.delete("all")
        n = self._case_no()
        R.draw_plan_icon(cv, CASE_EDGES.get(n, CASE_EDGES[2]), 12, 10, 54, 72, labels=True, font=(T.FAM, 8, "bold"))
        if getattr(self, "case_lbl", None) is not None and self.case_lbl.winfo_exists():
            self.case_lbl.config(text=CASE_DESC.get(n, ""))

    # ── 입력 수집 ────────────────────────────────────────────
    def _num(self, key):
        s = self.v[key].get().strip().replace(",", "")
        try:
            return float(s)
        except ValueError:
            raise S.SlabInputError(f"'{LABELS.get(key, key)}' 값이 숫자가 아닙니다: \"{s}\"") from None

    def collect(self):
        one = self.v["type"].get() == TYPE_1WAY
        inp = {"name": self.v["name"].get().strip(), "type": "1way" if one else "2way",
               "bar": self.v["bar"].get().strip() or "D10"}
        for k in ("t", "cc", "fck", "fy13", "fy16", "wd", "wl"):
            inp[k] = self._num(k)
        if one:
            inp["span"] = self._num("span")
            inp["support"] = next((k for k, val in S.ONE_WAY_SUPPORTS.items() if val[0] == self.v["support"].get()), "CC")
            inp["spans"] = SPAN_OPTS.get(self.v["spans"].get(), 3)
            inp["kcr"] = S.EXPOSURES.get(self.v["expo"].get(), 210.0)
        else:
            inp["lx"] = self._num("lx")
            inp["ly"] = self._num("ly")
            inp["case"] = self._case_no()
            inp["beams"] = [(self._num(f"b{i}b"), self._num(f"b{i}h")) for i in range(1, 5)]
        return inp

    # ── 계산 ─────────────────────────────────────────────────
    def calc(self, silent=False):
        try:
            res = S.calculate(self.collect())
        except S.SlabInputError as e:
            self.result = self.report = None
            self._set_status(f"입력 오류 — {str(e).splitlines()[0]}", ok=False)
            if not silent:
                messagebox.showwarning("입력 확인", str(e), parent=self.win)
            return None
        self.result = res
        self.report = R.build(res)
        fonts(self.win)
        render(self.cv, self.report, sketch=R.sketch(res))
        self.cv.yview_moveto(0)
        nm = res["name"] or "(이름 없음)"
        kind = "1방향" if res["type"] == "1way" else "2방향"
        self._set_status(f"{nm}  ·  {kind} 슬래브  ·  T = {res['t']:g} mm  ─  "
                         + ("설계 결과 O.K." if res["ok"] else "N.G. 항목이 있습니다 — 계산서의 빨간 항목을 확인하세요."),
                         ok=res["ok"])
        return res

    def _set_status(self, text, ok=True):
        self.status.config(text=text, fg=T.OK if ok else T.NG)

    # ── 파일 ─────────────────────────────────────────────────
    def new(self):
        typ = self.v["type"].get()
        for k, val in DEFAULTS.items():
            if k != "type":
                self.v[k].set(val)
        self.path = None
        self.v["type"].set(typ)            # trace → 화면 갱신 + 계산

    def save(self):
        path = filedialog.asksaveasfilename(parent=self.win, title="슬래브 저장", defaultextension=".slab",
                                            filetypes=FILE_TYPES, initialfile=(self.v["name"].get() or "slab") + ".slab")
        if not path:
            return
        data = {"app": "StrCAD Basic Design", "module": "rc_slab_lite", "version": 1,
                "values": {k: var.get() for k, var in self.v.items()}}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            messagebox.showerror("저장 실패", str(e), parent=self.win)
            return
        self.path = path
        self._set_status(f"저장했습니다: {path}")

    def open(self):
        path = filedialog.askopenfilename(parent=self.win, title="슬래브 열기", filetypes=FILE_TYPES)
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                vals = json.load(f).get("values", {})
        except (OSError, ValueError, AttributeError) as e:
            messagebox.showerror("열기 실패", f"파일을 읽지 못했습니다.\n{e}", parent=self.win)
            return
        typ = str(vals.get("type", self.v["type"].get()))
        for k, val in vals.items():
            if k in self.v and k != "type":
                self.v[k].set(str(val))
        self.path = path
        self.v["type"].set(typ if typ in (TYPE_1WAY, TYPE_2WAY) else TYPE_2WAY)

    def save_report(self):
        if self.calc() is None:
            return
        path = filedialog.asksaveasfilename(parent=self.win, title="계산서 저장", defaultextension=".txt",
                                            filetypes=[("텍스트", "*.txt")],
                                            initialfile=(self.v["name"].get() or "slab") + "_계산서.txt")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write(self.report.to_text())
        except OSError as e:
            messagebox.showerror("저장 실패", str(e), parent=self.win)
            return
        self._set_status(f"계산서를 저장했습니다: {path}")

    def copy_report(self):
        if self.calc() is None:
            return
        self.win.clipboard_clear()
        self.win.clipboard_append(self.report.to_text())
        self._set_status("계산서를 클립보드에 복사했습니다.")


def open_slab_lite(parent, username=""):
    return SlabLiteWindow(parent, username=username)
