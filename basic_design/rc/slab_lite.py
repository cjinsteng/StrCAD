"""
basic_design/rc/slab_lite.py
RC Slab — Lite : 1방향 / 2방향 단일 슬래브(등분포하중) 설계 창

  왼쪽   부재 목록 (Memb List) — 추가 · 복제 · 삭제 · 순서 이동, 파일(.slab) 한 개에 모두 저장
  가운데 입력 패널 (Name · Type · 치수 · 재료 · 하중 · 지지 형식 · 사용 철근)
  오른쪽 계산서 (Design Conditions / Min. Thk. / Flexure / Summary / Shear)
  출력   A4 PDF (머릿말 "RC SLAB DESIGN") — 현재 부재 / 전체 부재
"""
import datetime
import json
import os
import re
import tempfile
import tkinter as tk
import tkinter.font as tkfont
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
PRINT_HEADER = "RC SLAB DESIGN"

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


# ── 입력값(문자열 dict) → 계산 입력 ──────────────────────────
def _num(vals, key):
    s = str(vals.get(key, "")).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        raise S.SlabInputError(f"'{LABELS.get(key, key)}' 값이 숫자가 아닙니다: \"{s}\"") from None


def _case_no(vals):
    try:
        return int(str(vals.get("case", "")).replace("Case", "").strip())
    except ValueError:
        return 2


def inputs_from_values(vals):
    """화면 입력값(문자열) → slab_calc.calculate() 입력 dict.  잘못된 값은 SlabInputError"""
    one = vals.get("type") == TYPE_1WAY
    inp = {"name": str(vals.get("name", "")).strip(), "type": "1way" if one else "2way",
           "bar": str(vals.get("bar", "")).strip() or "D10"}
    for k in ("t", "cc", "fck", "fy13", "fy16", "wd", "wl"):
        inp[k] = _num(vals, k)
    if one:
        inp["span"] = _num(vals, "span")
        inp["support"] = next((k for k, v in S.ONE_WAY_SUPPORTS.items() if v[0] == vals.get("support")), "CC")
        inp["spans"] = SPAN_OPTS.get(vals.get("spans"), 3)
        inp["kcr"] = S.EXPOSURES.get(vals.get("expo"), 210.0)
    else:
        inp["lx"] = _num(vals, "lx")
        inp["ly"] = _num(vals, "ly")
        inp["case"] = _case_no(vals)
        inp["beams"] = [(_num(vals, f"b{i}b"), _num(vals, f"b{i}h")) for i in range(1, 5)]
    return inp


def _safe_name(s):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", s).strip("_") or "slab"


class SlabLiteWindow:
    def __init__(self, parent, username=""):
        self.user = username
        self.path = None
        self.result = None
        self.report = None
        self.members = [{"values": dict(DEFAULTS), "ok": None}]      # 부재 목록
        self.cur = 0
        self._busy = False
        self.win = win = tk.Toplevel(parent)
        win.geometry("1560x880")
        win.minsize(1200, 620)
        win.configure(bg=T.SURFACE)
        T.set_icon(win)
        self.v = {k: tk.StringVar(win, value=val) for k, val in DEFAULTS.items()}
        self.f_n = (T.FAM, 9)
        self.f_b = (T.FAM, 9, "bold")
        self._build()
        self.v["type"].trace_add("write", lambda *_: self._on_type())
        self.v["case"].trace_add("write", lambda *_: self._draw_case())
        self.v["name"].trace_add("write", lambda *_: self._on_name())
        win.bind("<Return>", lambda _: self.calc())
        win.bind("<F5>", lambda _: self.calc())
        win.bind("<Control-s>", lambda _: self.save())
        win.bind("<Control-o>", lambda _: self.open())
        win.bind("<Control-p>", lambda _: self.print_pdf(False))
        self._update_title()
        self._on_type()
        self._refresh_list()
        win.lift()
        win.focus_force()

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

        def tbtn(txt, cmd, bg=T.NAVY_2):
            b = tk.Button(bar, text=txt, command=cmd, font=self.f_n, bg=bg, fg="white", relief="flat",
                          activebackground=T.ORANGE, activeforeground="white", cursor="hand2", padx=10, pady=3)
            b.pack(side="right", padx=(0, 6), pady=8)
            return b
        self.btn_print = tbtn("출력 (A4) ▾", self._print_menu, bg=T.ORANGE_D)
        tbtn("다른 이름으로", self.save_as)
        tbtn("저장", self.save)
        tbtn("열기", self.open)
        tbtn("새 파일", self.new)
        self.menu_print = m = tk.Menu(win, tearoff=0, font=self.f_n)
        m.add_command(label="현재 부재 출력 (A4)          Ctrl+P", command=lambda: self.print_pdf(False))
        m.add_command(label="전체 부재 출력 (A4)", command=lambda: self.print_pdf(True))
        m.add_separator()
        m.add_command(label="PDF로 저장 — 현재 부재…", command=lambda: self.print_pdf(False, ask=True))
        m.add_command(label="PDF로 저장 — 전체 부재…", command=lambda: self.print_pdf(True, ask=True))
        m.add_separator()
        m.add_command(label="계산서 텍스트 저장…", command=self.save_report)
        m.add_command(label="계산서 복사 (클립보드)", command=self.copy_report)

        self.status = tk.Label(win, text="", anchor="w", font=self.f_n, bg="#E5E9F0", fg=T.INK, padx=12, pady=4)
        self.status.pack(fill="x", side="bottom")

        # 부재 목록 | 입력·계산서  — 경계(sash)를 끌어 목록 폭 조절
        self.pane = pane = tk.PanedWindow(win, orient="horizontal", sashwidth=6, sashrelief="flat", bd=0,
                                          bg=T.LINE, opaqueresize=True)
        pane.pack(fill="both", expand=True)
        lst = tk.Frame(pane, bg=T.SURFACE)
        self._build_list(lst)
        main = tk.Frame(pane, bg=T.SURFACE)
        pane.add(lst, minsize=150, width=self._list_width)
        pane.add(main, minsize=760, stretch="always")
        try:
            pane.paneconfigure(lst, stretch="never")
        except tk.TclError:
            pass

        left = tk.Frame(main, bg=T.SURFACE, width=392)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Frame(main, bg=T.LINE, width=1).pack(side="left", fill="y")
        self._build_left(left)

        right = tk.Frame(main, bg=T.PANEL)
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

    # ── 부재 목록 ────────────────────────────────────────────
    def _build_list(self, p):
        hd = tk.Frame(p, bg=T.NAVY_2, height=26)
        hd.pack(fill="x")
        hd.pack_propagate(False)
        tk.Label(hd, text="Memb List", font=self.f_b, bg=T.NAVY_2, fg="white").pack(side="left", padx=10)
        self.lbl_cnt = tk.Label(hd, text="", font=(T.FAM, 8), bg=T.NAVY_2, fg="#B9C4DA")
        self.lbl_cnt.pack(side="right", padx=8)

        tb = tk.Frame(p, bg=T.SURFACE)
        tb.pack(fill="x", padx=6, pady=6)
        tk.Label(p, text="↔ 오른쪽 경계를 끌어 폭 조절", font=(T.FAM, 7), bg=T.SURFACE, fg=T.MUTED).pack(
            side="bottom", anchor="w", padx=8, pady=(0, 4))
        for txt, cmd in (("추가", self.member_add), ("복제", self.member_copy), ("삭제", self.member_delete),
                         ("▲", lambda: self.member_move(-1)), ("▼", lambda: self.member_move(1))):
            b = tk.Button(tb, text=txt, command=cmd, font=(T.FAM, 8), bg="white", fg=T.INK, relief="groove",
                          cursor="hand2", padx=5 if len(txt) > 1 else 4, pady=1)
            b.pack(side="left", padx=(0, 3))

        # 글꼴 크기(Windows 배율 포함)로 열 폭·행 높이를 정해 글자가 잘리지 않게
        fn = tkfont.Font(self.win, font=self.f_n)
        fb = tkfont.Font(self.win, font=self.f_b)
        pad = fn.measure("0") * 2 + 6
        widths = {"no": max(fb.measure("No"), fn.measure("999")) + pad,
                  "name": max(fn.measure("1RaS21-W"), fb.measure("Name")) + pad,
                  "type": max(fb.measure("형식"), fn.measure("2W")) + pad,
                  "res": max(fb.measure("결과"), fn.measure("NG")) + pad}
        sb_w = 18
        self._list_width = sum(widths.values()) + sb_w + 14
        st = ttk.Style(self.win)
        st.configure("BD.Treeview", font=self.f_n, rowheight=fn.metrics("linespace") + 8)
        st.configure("BD.Treeview.Heading", font=self.f_b)
        box = tk.Frame(p, bg=T.SURFACE)
        box.pack(fill="both", expand=True, padx=(6, 2), pady=(0, 2))
        self.tree = tr = ttk.Treeview(box, columns=("no", "name", "type", "res"), show="headings",
                                      selectmode="browse", style="BD.Treeview")
        for cid, txt, anc in (("no", "No", "center"), ("name", "Name", "w"), ("type", "형식", "center"),
                              ("res", "결과", "center")):
            tr.heading(cid, text=txt, anchor="w" if cid == "name" else "center")
            tr.column(cid, width=widths[cid], minwidth=widths[cid], anchor=anc, stretch=(cid == "name"))
        tr.tag_configure("ng", foreground=T.NG)
        tr.tag_configure("odd", background="#EEF2F8")
        sb = ttk.Scrollbar(box, orient="vertical", command=tr.yview)
        tr.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tr.pack(fill="both", expand=True)
        tr.bind("<<TreeviewSelect>>", self._on_tree_select)

    def _row_values(self, i):
        m = self.members[i]
        vals = m["values"]
        res = "" if m["ok"] is None else ("OK" if m["ok"] else "NG")
        return (i + 1, vals.get("name", ""), "1W" if vals.get("type") == TYPE_1WAY else "2W", res)

    def _row_tags(self, i):
        tags = ["odd"] if i % 2 else []
        if self.members[i]["ok"] is False:
            tags.append("ng")
        return tags

    def _refresh_list(self):
        """목록 전체 다시 그리기 + 현재 부재 선택"""
        self._busy = True
        try:
            tr = self.tree
            tr.delete(*tr.get_children())
            for i in range(len(self.members)):
                tr.insert("", "end", iid=str(i), values=self._row_values(i), tags=self._row_tags(i))
            tr.selection_set(str(self.cur))
            tr.see(str(self.cur))
            self.lbl_cnt.config(text=f"{len(self.members)}개")
            self.win.update_idletasks()                 # 선택 이벤트를 _busy 동안 비운다
        finally:
            self._busy = False

    def _refresh_row(self, i=None):
        i = self.cur if i is None else i
        if self.tree.exists(str(i)):
            self.tree.item(str(i), values=self._row_values(i), tags=self._row_tags(i))

    def _sync_current(self):
        """화면 입력값 → 현재 부재"""
        self.members[self.cur]["values"] = {k: var.get() for k, var in self.v.items()}

    def _load_member(self, i):
        """부재 i 를 화면에 올리고 계산"""
        self.cur = i
        vals = self.members[i]["values"]
        self._busy = True
        try:
            for k, var in self.v.items():
                var.set(str(vals.get(k, DEFAULTS[k])))
        finally:
            self._busy = False
        self._on_type()

    def _on_tree_select(self, _=None):
        if self._busy:
            return
        sel = self.tree.selection()
        if not sel:
            return
        i = int(sel[0])
        if i == self.cur or i >= len(self.members):
            return
        self._sync_current()
        self._load_member(i)

    def _on_name(self):
        if self._busy:
            return
        self.members[self.cur]["values"]["name"] = self.v["name"].get()
        self._refresh_row()

    def _unique_name(self, base):
        names = {m["values"].get("name", "") for m in self.members}
        if base not in names:
            return base
        m = re.match(r"^(.*?)(\d+)$", base)
        stem, n = (m.group(1), int(m.group(2))) if m else (base + "-", 1)
        while f"{stem}{n}" in names:
            n += 1
        return f"{stem}{n}"

    def member_add(self):
        self._sync_current()
        vals = dict(DEFAULTS)
        vals["type"] = self.v["type"].get()
        vals["name"] = self._unique_name("S1")
        self.members.insert(self.cur + 1, {"values": vals, "ok": None})
        self._load_member(self.cur + 1)
        self._refresh_list()

    def member_copy(self):
        self._sync_current()
        vals = dict(self.members[self.cur]["values"])
        vals["name"] = self._unique_name(vals.get("name") or "S1")
        self.members.insert(self.cur + 1, {"values": vals, "ok": None})
        self._load_member(self.cur + 1)
        self._refresh_list()

    def member_delete(self):
        nm = self.v["name"].get() or "(이름 없음)"
        if not messagebox.askyesno("부재 삭제", f"'{nm}' 부재를 목록에서 삭제할까요?", parent=self.win):
            return
        if len(self.members) == 1:
            self.members = [{"values": dict(DEFAULTS, type=self.v["type"].get()), "ok": None}]
            self._load_member(0)
        else:
            self.members.pop(self.cur)
            self._load_member(min(self.cur, len(self.members) - 1))
        self._refresh_list()

    def member_move(self, step):
        j = self.cur + step
        if not 0 <= j < len(self.members):
            return
        self._sync_current()
        self.members[self.cur], self.members[j] = self.members[j], self.members[self.cur]
        self.cur = j
        self._refresh_list()

    # ── 입력 패널 ────────────────────────────────────────────
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
        return ttk.Combobox(parent, textvariable=self.v[key], values=values, width=width, state=state, font=self.f_n)

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

        tk.Label(p, text="Enter / F5 : 계산    Ctrl+S : 저장    Ctrl+O : 열기    Ctrl+P : 출력", font=(T.FAM, 8),
                 bg=T.SURFACE, fg=T.MUTED).pack(side="bottom", pady=8)

    # ── Type 에 따라 달라지는 입력 ───────────────────────────
    def _on_type(self):
        if self._busy:
            return
        one = self.v["type"].get() == TYPE_1WAY
        for g in (self.g_dim, self.g_sup, self.g_bar):
            for w in g.winfo_children():
                w.destroy()
        if one:
            self._field(self.g_dim, 0, "Span :", "span", "m")
            self._lbl(self.g_dim, "(순경간 ln)", fg=T.MUTED).grid(row=1, column=0, columnspan=3, sticky="w")
        else:
            self._field(self.g_dim, 0, "Lx :", "lx", "m")
            self._field(self.g_dim, 1, "Ly :", "ly", "m")
            self._lbl(self.g_dim, "(Lx ≤ Ly, 중심간)", fg=T.MUTED).grid(row=2, column=0, columnspan=3, sticky="w")
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
        self._field(self.g_bar, 0, "철근 :", "bar", "", widget=self._cmb(self.g_bar, "bar", S.BAR_ORDER, 6, "readonly"))
        if one:
            self._field(self.g_bar, 1, "노출환경 :", "expo", "",
                        widget=self._cmb(self.g_bar, "expo", list(S.EXPOSURES), 19, "readonly"))
        self.calc(silent=True)

    def _copy_beam(self, i):
        """↑ : 바로 위 보 치수를 복사"""
        self.v[f"b{i}b"].set(self.v[f"b{i - 1}b"].get())
        self.v[f"b{i}h"].set(self.v[f"b{i - 1}h"].get())

    def _draw_case(self):
        cv = getattr(self, "case_cv", None)
        if cv is None or not cv.winfo_exists():
            return
        cv.delete("all")
        n = _case_no({"case": self.v["case"].get()})
        R.draw_plan_icon(cv, CASE_EDGES.get(n, CASE_EDGES[2]), 12, 10, 54, 72, labels=True, font=(T.FAM, 8, "bold"))
        if getattr(self, "case_lbl", None) is not None and self.case_lbl.winfo_exists():
            self.case_lbl.config(text=CASE_DESC.get(n, ""))

    # ── 계산 ─────────────────────────────────────────────────
    def collect(self):
        return inputs_from_values({k: var.get() for k, var in self.v.items()})

    def calc(self, silent=False):
        self._sync_current()
        try:
            res = S.calculate(self.collect())
        except S.SlabInputError as e:
            self.result = self.report = None
            self.members[self.cur]["ok"] = None
            self._refresh_row()
            self.cv.delete("all")
            self._set_status(f"입력 오류 — {str(e).splitlines()[0]}", ok=False)
            if not silent:
                messagebox.showwarning("입력 확인", str(e), parent=self.win)
            return None
        self.result = res
        self.report = R.build(res)
        fonts(self.win)
        render(self.cv, self.report, sketch=R.sketch(res), sketch_box=R.sketch_box(res))
        self.cv.yview_moveto(0)
        self.members[self.cur]["ok"] = res["ok"]
        self._refresh_row()
        nm = res["name"] or "(이름 없음)"
        kind = "1방향" if res["type"] == "1way" else "2방향"
        self._set_status(f"{nm}  ·  {kind} 슬래브  ·  T = {res['t']:g} mm  ─  "
                         + ("설계 결과 O.K." if res["ok"] else "N.G. 항목이 있습니다 — 계산서의 빨간 항목을 확인하세요."),
                         ok=res["ok"])
        return res

    def _calc_all(self):
        """모든 부재의 결과(OK/NG) 갱신"""
        for m in self.members:
            try:
                m["ok"] = S.calculate(inputs_from_values(m["values"]))["ok"]
            except S.SlabInputError:
                m["ok"] = None

    def _set_status(self, text, ok=True):
        self.status.config(text=text, fg=T.OK if ok else T.NG)

    def _update_title(self):
        f = os.path.basename(self.path) if self.path else "제목 없음"
        self.win.title(f"StrCAD - Basic Design │ RC Slab Lite  ─  {f}" + (f"  ─  {self.user}" if self.user else ""))

    # ── 파일 (부재 목록 전체를 한 파일에) ────────────────────
    def new(self):
        if len(self.members) > 1 and not messagebox.askyesno(
                "새 파일", "현재 부재 목록을 모두 비우고 새로 시작할까요?\n(저장하지 않은 내용은 사라집니다)", parent=self.win):
            return
        self.members = [{"values": dict(DEFAULTS, type=self.v["type"].get()), "ok": None}]
        self.path = None
        self._update_title()
        self._load_member(0)
        self._refresh_list()

    def _write(self, path):
        self._sync_current()
        data = {"app": "StrCAD Basic Design", "module": "rc_slab_lite", "version": 2, "current": self.cur,
                "members": [m["values"] for m in self.members]}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            messagebox.showerror("저장 실패", str(e), parent=self.win)
            return False
        self.path = path
        self._update_title()
        self._set_status(f"저장했습니다 (부재 {len(self.members)}개): {path}")
        return True

    def save(self):
        if self.path:
            return self._write(self.path)
        return self.save_as()

    def save_as(self):
        init = os.path.basename(self.path) if self.path else "slab_list.slab"
        path = filedialog.asksaveasfilename(parent=self.win, title="부재 목록 저장", defaultextension=".slab",
                                            filetypes=FILE_TYPES, initialfile=init)
        return self._write(path) if path else False

    def open(self):
        path = filedialog.askopenfilename(parent=self.win, title="부재 목록 열기", filetypes=FILE_TYPES)
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data.get("members"), list) and data["members"]:
                raw = data["members"]
            else:
                raw = [data["values"]]                    # version 1: 부재 한 개
            members = []
            for vals in raw:
                merged = dict(DEFAULTS)
                merged.update({k: str(val) for k, val in vals.items() if k in DEFAULTS})
                if merged["type"] not in (TYPE_1WAY, TYPE_2WAY):
                    merged["type"] = TYPE_2WAY
                members.append({"values": merged, "ok": None})
            cur = int(data.get("current", 0))
        except (OSError, ValueError, KeyError, AttributeError, TypeError) as e:
            messagebox.showerror("열기 실패", f"파일을 읽지 못했습니다.\n{e}", parent=self.win)
            return
        self.members = members
        self.path = path
        self._calc_all()
        self._update_title()
        self._load_member(cur if 0 <= cur < len(members) else 0)
        self._refresh_list()
        self._set_status(f"열었습니다 (부재 {len(members)}개): {path}")

    # ── 출력 ─────────────────────────────────────────────────
    def _print_menu(self):
        b = self.btn_print
        self.menu_print.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def _print_items(self, all_members):
        """[(report, sketch, sketch_box, name)], 건너뛴 부재 이름"""
        self._sync_current()
        targets = self.members if all_members else [self.members[self.cur]]
        items, skipped = [], []
        for m in targets:
            try:
                res = S.calculate(inputs_from_values(m["values"]))
            except S.SlabInputError:
                skipped.append(m["values"].get("name", "?"))
                continue
            items.append((R.build(res), R.sketch(res), R.sketch_box(res), res["name"]))
        return items, skipped

    def print_pdf(self, all_members=False, ask=False):
        """A4 PDF 를 만들어 PDF 뷰어로 연다(뷰어에서 인쇄).  ask=True 면 저장 위치를 묻고 열지는 않는다."""
        from .. import pdf_out
        items, skipped = self._print_items(all_members)
        if not items:
            messagebox.showwarning("출력", "출력할 수 있는 부재가 없습니다.\n입력값을 확인하세요.", parent=self.win)
            return None
        if not all_members:
            base = "RC_SLAB_" + _safe_name(items[0][3])
        elif self.path:
            base = "RC_SLAB_" + _safe_name(os.path.splitext(os.path.basename(self.path))[0])
        else:
            base = "RC_SLAB_전체"
        if ask:
            path = filedialog.asksaveasfilename(parent=self.win, title="PDF로 저장", defaultextension=".pdf",
                                                filetypes=[("PDF", "*.pdf")], initialfile=base + ".pdf")
            if not path:
                return None
        else:
            folder = os.path.join(tempfile.gettempdir(), "StrCAD_print")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"{base}_{datetime.datetime.now():%H%M%S}.pdf")
        self.win.config(cursor="watch")
        self._set_status("출력용 PDF 를 만드는 중…")
        self.win.update_idletasks()
        try:
            n = pdf_out.export_pdf(path, items, header=PRINT_HEADER)
        except (pdf_out.PdfExportError, OSError) as e:
            messagebox.showerror("출력 실패", str(e), parent=self.win)
            self._set_status("출력 실패", ok=False)
            return None
        finally:
            self.win.config(cursor="")
        msg = f"A4 {n}쪽 PDF 를 만들었습니다: {path}"
        if skipped:
            msg += f"   (입력 오류로 제외: {', '.join(skipped)})"
        self._set_status(msg)
        if not ask:
            try:
                pdf_out.open_file(path)
            except OSError as e:
                messagebox.showinfo("출력", f"PDF 를 만들었지만 자동으로 열지 못했습니다.\n{path}\n\n{e}", parent=self.win)
        return path

    def save_report(self):
        if self.calc() is None:
            return
        path = filedialog.asksaveasfilename(parent=self.win, title="계산서 저장", defaultextension=".txt",
                                            filetypes=[("텍스트", "*.txt")],
                                            initialfile=_safe_name(self.v["name"].get()) + "_계산서.txt")
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
