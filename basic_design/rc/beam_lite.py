"""
basic_design/rc/beam_lite.py
RC Beam — Lite : 직사각형 보 단면 검토 창

  · 단면 1~3개: 전단면 / 단부·중앙부 / 연속단부·중앙부·불연속단부(머리글 클릭 → 연속단부로 전환)
  · 입력 표: 단면별 열에 모멘트·전단·비틀림·상하부 배근(1·2단)·측면철근·띠철근을 입력하면
             옆 칸에 OK/NG(비율)가 바로 표시된다
  · 철근 직경: 기본은 한 단면의 주근이 모두 같은 직경, '다른 철근 사용' 체크 시 단마다 따로
  · 주근 개수: 숫자 입력 또는 +/− 버튼 (1단 개수 제한을 넘으면 2단으로)
  · 방향키로 입력칸 이동
  · 배근 복사: 상·하부 배근 변경 / 단부 배근 복사
  · 결과: Simple(표, 기본) / Detail(풀이)
  (부재 목록 · 저장 · A4 출력은 공통 틀 member_app.MemberWindow)
"""
import tkinter as tk
from tkinter import ttk

from .. import theme as T
from ..member_app import MemberWindow
from . import beam_calc as B
from . import slab_calc as S

TYPE_RECT = "사각 보"
END_DISC, END_CONT = "불연속단부", "연속단부"
SEC_KEYS = ["tn1", "tn2", "tb", "tb2", "bn1", "bn2", "bb", "bb2", "sn", "sb", "vl", "vb", "vs", "mn", "mp", "vu", "tu"]
REBAR_KEYS = [k for k in SEC_KEYS if k not in ("mn", "mp", "vu", "tu")]
SWAP = {"tn1": "bn1", "tn2": "bn2", "tb": "bb", "tb2": "bb2", "bn1": "tn1", "bn2": "tn2", "bb": "tb", "bb2": "tb2"}
SEC_DEFAULT = {"tn1": "3", "tn2": "0", "tb": "D22", "tb2": "D22", "bn1": "3", "bn2": "0", "bb": "D22", "bb2": "D22",
               "sn": "0", "sb": "D13", "vl": "2", "vb": "D10", "vs": "0", "mn": "0", "mp": "100", "vu": "100", "tu": "0"}
DEFAULTS = {"name": "B1", "type": TYPE_RECT, "b": "400", "h": "600", "cc": "40", "fck": "24", "fy": "400", "fys": "400",
            "phi_f": "0.85", "phi_v": "0.75", "expo": "그 외 환경 (κcr=210)", "n_sec": "1", "end3": END_DISC,
            "opt_diff": "0", "n1max": "0"}
for _k in (1, 2, 3):
    for _key, _v in SEC_DEFAULT.items():
        DEFAULTS[f"{_k}_{_key}"] = _v
LABELS = {"b": "B", "h": "H", "cc": "순피복 Cc", "fck": "fck", "fy": "fy", "fys": "fys", "phi_f": "휨 φf", "phi_v": "전단 φv",
          "tn1": "상부 1단", "tn2": "상부 2단", "bn1": "하부 1단", "bn2": "하부 2단", "sn": "측면철근",
          "vl": "띠철근 다리", "vs": "띠철근 간격", "mn": "상부 모멘트", "mp": "하부 모멘트", "vu": "전단", "tu": "비틀림"}

OKC, NGC, DIM = T.OK, T.NG, "#9CA3AF"
CELL, HEAD, ROWH, LINE = "white", T.NAVY_2, "#EEF2F8", "#C9D1DE"


def _safe(x):
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return 0.0


def _num(vals, key, label=None):
    s = str(vals.get(key, "")).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        raise B.BeamInputError(f"'{label or LABELS.get(key, key)}' 값이 숫자가 아닙니다: \"{s}\"") from None


def n_sections(vals):
    try:
        return max(1, min(3, int(vals.get("n_sec", 1))))
    except (TypeError, ValueError):
        return 1


def sec_labels(vals):
    n = n_sections(vals)
    labels = list(B.SEC_LABELS[n])
    if n == 3:
        labels[2] = vals.get("end3") if vals.get("end3") in (END_DISC, END_CONT) else END_DISC
    return labels


def effective_bars(vals, k):
    """옵션을 반영한 실제 철근 (tb, tb2, bb, bb2) — 기본: 모두 상부 1단 직경, '다른 철근 사용' 이면 각각"""
    def g(key):
        return vals.get(f"{k}_{key}", SEC_DEFAULT[key])
    if str(vals.get("opt_diff", "0")) == "1":
        return g("tb"), g("tb2"), g("bb"), g("bb2")
    tb = g("tb")
    return tb, tb, tb, tb


def max_in_layer(vals, bar, vb):
    """1단 최대 개수: 입력값(>0) 또는 순간격 max(25, db) 로 들어가는 개수"""
    try:
        n = int(float(vals.get("n1max", 0)))
    except (TypeError, ValueError):
        n = 0
    if n > 0:
        return n
    try:
        b, cc = float(vals.get("b")), float(vals.get("cc"))
    except (TypeError, ValueError):
        return 99
    db, ds = B.BARS.get(bar, B.BARS["D22"])[0], B.BARS.get(vb, B.BARS["D10"])[0]
    clear = max(25.0, db)
    return max(int((b - 2 * (cc + ds) + clear) // (db + clear)), 2)


def inputs_from_values(vals):
    inp = {"name": str(vals.get("name", "")).strip(), "kcr": S.EXPOSURES.get(vals.get("expo"), 210.0)}
    for k in ("b", "h", "cc", "fck", "fy", "fys", "phi_f", "phi_v"):
        inp[k] = _num(vals, k)
    n = n_sections(vals)
    labels = sec_labels(vals)
    inp["labels"] = labels
    inp["sections"] = []
    for k in range(1, n + 1):
        sec = {}
        for key in SEC_KEYS:
            if key in ("tb", "tb2", "bb", "bb2", "sb", "vb"):
                continue
            v = vals.get(f"{k}_{key}", SEC_DEFAULT[key])
            if str(v).strip() in ("", "-"):
                v = "0"
            sec[key] = _num({key: v}, key, f"[{labels[k - 1]}] {LABELS[key]}")
        sec["tb"], sec["tb2"], sec["bb"], sec["bb2"] = effective_bars(vals, k)
        sec["sb"] = vals.get(f"{k}_sb", "D13")
        sec["vb"] = vals.get(f"{k}_vb", "D10")
        inp["sections"].append(sec)
    return inp


class BeamLiteWindow(MemberWindow):
    TITLE = "RC Beam"
    BADGE = "Lite"
    SUBTITLE = "직사각형 보 단면 검토 · 단면 1~3개"
    MODULE = "rc_beam_lite"
    FILE_EXT = ".beam"
    FILE_DESC = "Beam Lite 파일"
    DEFAULT_FILE = "beam_list"
    PRINT_HEADER = "RC BEAM DESIGN"
    FOOTER = "StrCAD  ·  Basic Design  │  RC Beam Lite"
    DEFAULTS = DEFAULTS
    InputError = B.BeamInputError
    INPUT_WIDTH = 610
    WIN_SIZE = "1800x950"

    # ── 입력 패널 ────────────────────────────────────────────
    def build_inputs(self, p):
        self.res_lbl = {}
        self._after = None
        self.f_s = (T.FAM, 8)
        self.f_sb = (T.FAM, 8, "bold")
        f = self.top_fields
        self._lbl(f, "Type :").grid(row=1, column=0, sticky="e", pady=2)
        self._cmb(f, "type", [TYPE_RECT], 13, "readonly").grid(row=1, column=1, sticky="w", padx=4)

        row = tk.Frame(p, bg=T.SURFACE)
        row.pack(fill="x", padx=10, pady=2)
        g = self._group(row, "보치수")
        g.pack(side="left", fill="y")
        self._field(g, 0, "B :", "b", "mm", width=6)
        self._field(g, 1, "H :", "h", "mm", width=6)
        self._field(g, 2, "순피복 Cc :", "cc", "mm", width=6)
        g = self._group(row, "재료강도")
        g.pack(side="left", fill="y", padx=(8, 0))
        self._field(g, 0, "fck :", "fck", "N/mm²", widget=self._cmb(g, "fck", ["21", "24", "27", "30", "35", "40"], 5))
        self._field(g, 1, "fy :", "fy", "N/mm²", widget=self._cmb(g, "fy", ["300", "400", "500", "600"], 5))
        self._field(g, 2, "fys :", "fys", "N/mm²", widget=self._cmb(g, "fys", ["300", "400", "500", "600"], 5))
        g = self._group(row, "강도감소계수 · 균열")
        g.pack(side="left", fill="y", padx=(8, 0))
        self._field(g, 0, "휨 φf :", "phi_f", "", width=6)
        self._field(g, 1, "전단 φv :", "phi_v", "", width=6)
        self._field(g, 2, "노출 :", "expo", "", widget=self._cmb(g, "expo", list(S.EXPOSURES), 13, "readonly"))
        # Simple / Detail 전환 (계산 버튼 옆)
        self.detail = False
        self.btn_detail = tk.Button(self.top_bar, text="Detail ▸", command=self.toggle_detail, font=(T.FAM, 9, "bold"),
                                    bg="white", fg=T.NAVY, relief="groove", cursor="hand2", padx=10, pady=6)
        self.btn_detail.pack(side="right", padx=(0, 6))

        g = self._group(p, "단면 구성")
        g.pack(fill="x", padx=10, pady=2)
        for n, txt in ((1, "1  전단면"), (2, "2  단부 · 중앙부"), (3, "3  연속단부 · 중앙부 · 불연속단부")):
            tk.Radiobutton(g, text=txt, value=str(n), variable=self.v["n_sec"], indicatoron=False, font=self.f_b,
                           bg="white", fg=T.INK, selectcolor=T.ORANGE, activebackground="#FDE7D0", relief="groove",
                           padx=8, pady=2, cursor="hand2", command=self._on_nsec).pack(side="left", padx=(0, 4))

        opt = tk.Frame(p, bg=T.SURFACE)
        opt.pack(fill="x", padx=10, pady=(4, 0))
        tk.Checkbutton(opt, text="다른 철근 사용 (단마다 직경 지정)", variable=self.v["opt_diff"], onvalue="1",
                       offvalue="0", font=self.f_b, bg=T.SURFACE, fg=T.NAVY, command=self._on_opt).pack(side="left")
        self._lbl(opt, "   1단 주근 최대").pack(side="left")
        self._ent(opt, "n1max", 3).pack(side="left", padx=3)
        self._lbl(opt, "개 (0=자동, + 버튼이 넘으면 2단)", fg=T.MUTED).pack(side="left")
        tip = tk.Frame(p, bg=T.SURFACE)
        tip.pack(fill="x", padx=10)
        self._lbl(tip, "방향키로 칸 이동 · 콤보는 Space 로 목록 · 3단면 마지막 머리글 클릭 = 연속/불연속 전환",
                  fg=T.MUTED).pack(side="left")

        self.g_grid = tk.Frame(p, bg=LINE)               # 1px 간격 = 표 선 (단면 열 폭 고정)
        self.g_grid.pack(anchor="nw", padx=10, pady=4)
        self.lbl_why = tk.Label(p, text="", font=self.f_s, bg=T.SURFACE, fg=NGC, justify="left", anchor="nw")
        self.lbl_why.pack(anchor="nw", fill="x", padx=12, pady=(0, 6))

        for k in ("b", "h", "cc", "fck", "fy", "fys", "phi_f", "phi_v", "expo"):
            self.v[k].trace_add("write", lambda *_: self._auto())
        for k in range(1, 4):
            for key in SEC_KEYS:
                self.v[f"{k}_{key}"].trace_add("write", lambda *_: self._auto())

    def _auto(self):
        """입력이 바뀌면 잠시 뒤 다시 계산 (결과 칸 즉시 갱신)"""
        if self._busy:
            return
        if self._after is not None:
            try:
                self.win.after_cancel(self._after)
            except tk.TclError:
                pass
        self._after = self.win.after(250, self._auto_run)

    def _auto_run(self):
        self._after = None
        self._sync_bars()
        self.calc(silent=True)

    # ── 입력 표 ──────────────────────────────────────────────
    def _cell(self, r, c, widget_fn=None, text="", cs=1, rs=1, bg=CELL, fg=T.INK, font=None, anchor="center", w=None):
        """표 칸 하나 (1px 간격으로 선 표현).  입력 위젯은 방향키 이동 목록에 등록"""
        fr = tk.Frame(self.g_grid, bg=bg)
        fr.grid(row=r, column=c, columnspan=cs, rowspan=rs, sticky="nsew", padx=(0, 1), pady=(0, 1))
        if widget_fn is not None:
            wdg = widget_fn(fr)
            wdg.pack(fill="both", expand=True, padx=1, pady=1)
            nav = getattr(wdg, "nav_target", wdg)
            if isinstance(nav, (tk.Entry, ttk.Combobox)):
                self.nav[(r, c)] = nav
                self.nav_span[(r, c)] = cs
                nav.bind("<Up>", lambda e, p=(r, c): self._nav(p, 0, -1, e))
                nav.bind("<Down>", lambda e, p=(r, c): self._nav(p, 0, 1, e))
                nav.bind("<Left>", lambda e, p=(r, c): self._nav(p, -1, 0, e))
                nav.bind("<Right>", lambda e, p=(r, c): self._nav(p, 1, 0, e))
            return wdg
        lb = tk.Label(fr, text=text, bg=bg, fg=fg, font=font or self.f_s, anchor=anchor, width=w)
        lb.pack(fill="both", expand=True, padx=2, pady=1)
        return lb

    def _nav(self, pos, dx, dy, e):
        """방향키로 다음 입력칸으로 (Entry 의 ←/→ 는 커서가 끝에 있거나 전체 선택일 때만)"""
        w = e.widget
        if isinstance(w, tk.Entry) and not isinstance(w, ttk.Combobox) and dx:
            try:
                sel = w.selection_present()
                i, n = w.index("insert"), len(w.get())
            except tk.TclError:
                sel, i, n = True, 0, 0
            if not sel and ((dx < 0 and i > 0) or (dx > 0 and i < n)):
                return None
        r0, c0 = pos
        a0, b0 = c0, c0 + self.nav_span.get(pos, 1) - 1          # 현재 칸이 차지하는 열 범위

        def gap(c, cs):
            a, b_ = c, c + cs - 1
            return max(a - b0, a0 - b_, 0)
        cands = []
        for (r, c), wd in self.nav.items():
            try:
                if not wd.winfo_exists() or str(wd.cget("state")) == "disabled":
                    continue
            except tk.TclError:
                continue
            cs = self.nav_span.get((r, c), 1)
            if dx and r == r0 and (c - c0) * dx > 0:
                cands.append((abs(c - c0), 0, wd))
            elif dy and (r - r0) * dy > 0:
                cands.append((gap(c, cs), abs(r - r0), wd))
        if not cands:
            return "break"
        cands.sort(key=lambda t: (t[0], t[1]) if dx else (t[0] > 1, t[1], t[0]))
        nxt = cands[0][2]
        nxt.focus_set()
        if isinstance(nxt, tk.Entry) and not isinstance(nxt, ttk.Combobox):
            nxt.select_range(0, "end")
            nxt.icursor("end")
        return "break"

    def _e(self, key, width, just="right"):
        def make(parent):
            e = tk.Entry(parent, textvariable=self.v[key], width=width, font=self.f_s, fg=T.INPUT_FG, bg="white",
                         relief="flat", bd=0, justify=just, highlightthickness=0)
            e.bind("<FocusIn>", lambda _: e.select_range(0, "end"))
            return e
        return make

    def _c(self, key, values, width):
        def make(parent):
            c = ttk.Combobox(parent, textvariable=self.v[key], values=values, width=width, state="readonly",
                             font=self.f_s)
            c.bind("<Alt-Down>", lambda _: c.tk.call("ttk::combobox::Post", c))
            c.bind("<space>", lambda _: c.tk.call("ttk::combobox::Post", c))
            return c
        return make

    def _pm(self, k, side, step):
        """+/− 버튼: + 는 1단부터 채우고 제한을 넘으면 2단,  − 는 2단부터 뺀다"""
        def make(parent):
            return tk.Button(parent, text="+" if step > 0 else "−", font=(T.FAM, 8, "bold"), width=2, bd=0,
                             relief="flat", bg="#E8EEF8" if step > 0 else "#F3F4F6", fg=T.NAVY, cursor="hand2",
                             activebackground="#FDE7D0", padx=0, pady=0, takefocus=0,
                             command=lambda: self.bar_step(k, side, step))
        return make

    def bar_step(self, k, side, step):
        vals = self.current_values()
        n1k, n2k = (f"{k}_tn1", f"{k}_tn2") if side == "top" else (f"{k}_bn1", f"{k}_bn2")
        n1, n2 = int(_safe(vals[n1k])), int(_safe(vals[n2k]))
        tb, tb2, bb, bb2 = effective_bars(vals, k)
        lim = max_in_layer(vals, tb if side == "top" else bb, vals.get(f"{k}_vb", "D10"))
        if step > 0:
            if n1 < lim:
                n1 += 1
            elif n2 < lim:
                n2 += 1
        else:
            if n2 > 0:
                n2 -= 1
            elif n1 > 0:
                n1 -= 1
        self._busy = True
        try:
            self.v[n1k].set(str(n1))
            self.v[n2k].set(str(n2))
        finally:
            self._busy = False
        self.calc(silent=True)

    def _build_grid(self):
        g = self.g_grid
        for w in g.winfo_children():
            w.destroy()
        self.res_lbl = {}
        self.nav, self.nav_span = {}, {}
        vals = self.current_values()
        n = n_sections(vals)
        labels = sec_labels(vals)
        diff = vals.get("opt_diff") == "1"

        def base(k):                     # 열: 0 행이름, 1 단 번호, 단면마다 5열 (± | 개수 | - | 철근 | 결과)
            return 2 + (k - 1) * 5
        r = 0
        self._cell(r, 0, text="", cs=2, bg=HEAD)
        for k in range(1, n + 1):
            lbl = self._cell(r, base(k), text=labels[k - 1], cs=5, bg=HEAD, fg="white", font=self.f_sb)
            if n == 3 and k == 3:
                lbl.config(cursor="hand2", text=f"{labels[2]}  ⇄")
                lbl.bind("<Button-1>", lambda _: self._toggle_end3())
        # 단면력 행
        r += 1
        for key, title, unit in (("mn", "상부 M", "kN·m"), ("mp", "하부 M", "kN·m"), ("vu", "전단 V", "kN"),
                                 ("tu", "비틀림 T", "kN·m")):
            self._cell(r, 0, text=f"{title} ({unit})", cs=2, bg=ROWH, anchor="w")
            for k in range(1, n + 1):
                self._cell(r, base(k), self._e(f"{k}_{key}", 6), cs=4)
                self.res_lbl[(k, key)] = self._cell(r, base(k) + 4, text="-", w=9)
            r += 1
        # 배근 행 (상부 1·2단, 하부 2·1단) — + 는 위 줄, − 는 아래 줄
        for side, key_side, rows in (("상부 배근", "top", (("tn1", "tb", "1"), ("tn2", "tb2", "2"))),
                                     ("하부 배근", "bot", (("bn2", "bb2", "2"), ("bn1", "bb", "1")))):
            self._cell(r, 0, text=side, rs=2, bg=ROWH, anchor="w")
            for i, (nk, bk, no) in enumerate(rows):
                self._cell(r + i, 1, text=no, bg=ROWH, w=2)
                for k in range(1, n + 1):
                    self._cell(r + i, base(k), self._pm(k, key_side, +1 if i == 0 else -1))
                    self._cell(r + i, base(k) + 1, self._e(f"{k}_{nk}", 3, "center"))
                    self._cell(r + i, base(k) + 2, text="-", w=1)
                    cmb = self._cell(r + i, base(k) + 3, self._c(f"{k}_{bk}", B.BAR_LIST, 4))
                    if bk != "tb" and not diff:
                        cmb.config(state="disabled")
            for k in range(1, n + 1):
                self.res_lbl[(k, key_side)] = self._cell(r, base(k) + 4, text="-", rs=2, w=9)
            r += 2
        # 측면철근
        self._cell(r, 0, text="측면근(한쪽)", cs=2, bg=ROWH, anchor="w")
        for k in range(1, n + 1):
            self._cell(r, base(k), text="", w=2)
            self._cell(r, base(k) + 1, self._e(f"{k}_sn", 3, "center"))
            self._cell(r, base(k) + 2, text="-", w=1)
            self._cell(r, base(k) + 3, self._c(f"{k}_sb", B.BAR_LIST, 4))
            self.res_lbl[(k, "side")] = self._cell(r, base(k) + 4, text="", w=9)
        r += 1
        # 띠철근
        self._cell(r, 0, text="띠철근 @0=자동", cs=2, bg=ROWH, anchor="w")
        for k in range(1, n + 1):
            self._cell(r, base(k), text="", w=2)
            self._cell(r, base(k) + 1, self._e(f"{k}_vl", 3, "center"))
            self._cell(r, base(k) + 2, text="-", w=1)
            self._cell(r, base(k) + 3, self._c(f"{k}_vb", B.STIRRUP_LIST, 4))

            def stir(parent, kk=k):
                f = tk.Frame(parent, bg=CELL)
                tk.Label(f, text="@", font=self.f_s, bg=CELL, fg=T.INK).pack(side="left")
                e = tk.Entry(f, textvariable=self.v[f"{kk}_vs"], width=5, font=self.f_s, fg=T.INPUT_FG, bg="white",
                             relief="flat", bd=0, justify="right", highlightthickness=0)
                e.bind("<FocusIn>", lambda _: e.select_range(0, "end"))
                e.pack(side="left", fill="x", expand=True)
                f.nav_target = e
                return f
            self._cell(r, base(k) + 4, stir)
        r += 1
        # 판정 행 — 칸은 짧게(폭 고정), 자세한 이유는 표 아래
        for key, title in (("sp_main", "주근 간격"), ("sp_stir", "띠철근 간격"), ("comment", "Comment")):
            self._cell(r, 0, text=title, cs=2, bg=ROWH, anchor="w")
            for k in range(1, n + 1):
                self.res_lbl[(k, key)] = self._cell(r, base(k), text="-", cs=5, w=1,
                                                    bg="#F3F4F6" if key != "comment" else "#ECFDF5")
            r += 1
        # 배근 복사: 상·하부 배근 변경 / 단부 배근 복사 (첫 단부는 변경만)
        self._cell(r, 0, text="배근 복사", cs=2, bg=ROWH, anchor="w")
        for k in range(1, n + 1):
            def btns(parent, kk=k):
                f = tk.Frame(parent, bg=CELL)
                tk.Button(f, text="상하부 변경", font=(T.FAM, 7), relief="groove", bg="white", cursor="hand2", padx=3,
                          pady=0, takefocus=0, command=lambda: self.copy_rebar(kk, kk, True)).pack(side="left", padx=1)
                if kk > 1:
                    tk.Button(f, text="단부 복사", font=(T.FAM, 7), relief="groove", bg="white", cursor="hand2", padx=3,
                              pady=0, takefocus=0, command=lambda: self.copy_rebar(1, kk, False)).pack(side="left", padx=1)
                return f
            self._cell(r, base(k), btns, cs=5)
        if self.result is not None:
            self.on_result(self.result)
        self.win.after(30, self.fit_input)

    # ── 동작 ─────────────────────────────────────────────────
    def copy_rebar(self, src, dst, swap):
        """배근 복사 (단면력 제외).  swap=True: 상·하부 바꿔서"""
        vals = {key: self.v[f"{src}_{key}"].get() for key in REBAR_KEYS}
        if swap:
            vals = {SWAP.get(key, key): v for key, v in vals.items()}
        self._busy = True
        try:
            for key, v in vals.items():
                self.v[f"{dst}_{key}"].set(v)
        finally:
            self._busy = False
        self._sync_bars()
        self.calc(silent=True)

    def _toggle_end3(self):
        self.v["end3"].set(END_CONT if self.v["end3"].get() == END_DISC else END_DISC)
        self._build_grid()
        self.calc(silent=True)

    def _on_opt(self):
        self._sync_bars()
        self._build_grid()
        self.calc(silent=True)

    def toggle_detail(self):
        """결과 보기 전환: Simple(표) ⇄ Detail(풀이)"""
        self.detail = not self.detail
        self.btn_detail.config(text="◂ Simple" if self.detail else "Detail ▸",
                               bg="#FDE7D0" if self.detail else "white")
        self.calc(silent=True)

    def _sync_bars(self):
        """옵션으로 잠긴 철근 칸에 실제 적용 철근을 표시"""
        vals = self.current_values()
        self._busy = True
        try:
            for k in range(1, 4):
                tb, tb2, bb, bb2 = effective_bars(vals, k)
                for key, v in (("tb2", tb2), ("bb", bb), ("bb2", bb2)):
                    if self.v[f"{k}_{key}"].get() != v:
                        self.v[f"{k}_{key}"].set(v)
        finally:
            self._busy = False

    def _on_nsec(self):
        if self._busy:
            return
        n = n_sections(self.current_values())
        old = getattr(self, "_shown_n", n)
        if n > old:
            # 새 단면: 1번 단면 철근 복사 (중앙부는 상·하부 바꿔서), 단면력은 위치에 맞게
            labels = B.SEC_LABELS[n]
            v = self.v
            m1 = max(_safe(v["1_mn"].get()), _safe(v["1_mp"].get()))
            self._busy = True
            try:
                for k in range(old + 1, n + 1):
                    mid = labels[k - 1] == "중앙부"
                    for key in REBAR_KEYS:
                        v[f"{k}_{key}"].set(v[f"1_{SWAP.get(key, key) if mid else key}"].get())
                    v[f"{k}_mn"].set("0" if mid else f"{m1:g}")
                    v[f"{k}_mp"].set(f"{m1:g}" if mid else "0")
                    v[f"{k}_vu"].set(v["1_vu"].get())
                    v[f"{k}_tu"].set(v["1_tu"].get())
                if old == 1 and _safe(v["1_mn"].get()) == 0:     # 전단면 → 단부: 하부 모멘트를 상부 모멘트로
                    v["1_mn"].set(v["1_mp"].get())
                    v["1_mp"].set("0")
            finally:
                self._busy = False
        self._shown_n = n
        self._build_grid()
        self.calc(silent=True)

    def after_load(self):
        self._shown_n = n_sections(self.current_values())
        self._sync_bars()
        self._build_grid()
        self.calc(silent=True)

    # ── 결과 칸 ──────────────────────────────────────────────
    def _set(self, k, key, text, ok=None):
        lb = self.res_lbl.get((k, key))
        if lb is None or not lb.winfo_exists():
            return
        lb.config(text=text, fg=DIM if ok is None else (OKC if ok else NGC))

    def on_result(self, res):
        if not getattr(self, "res_lbl", None):
            return
        if res is None:
            for (k, key) in list(self.res_lbl):
                self._set(k, key, "입력 오류" if key == "comment" else "-", False if key == "comment" else None)
            self.lbl_why.config(text="입력 오류 — 아래 상태줄의 내용을 확인하세요.")
            return
        b, h = res["b"], res["h"]
        self._why = {}
        for k, s in enumerate(res["sections"], 1):
            sec, sh = s["sec"], s["shear"]
            flex = {f["positive"]: f for f in s["flex"]}
            for key, pos in (("mn", False), ("mp", True)):
                f = flex.get(pos)
                if f is None:
                    self._set(k, key, "OK(0.000)", True)
                elif f["none"]:
                    self._set(k, key, "NG(철근 없음)", False)
                else:
                    ok_m = f["ok_eps"] and f["ok_str"] and f["min_ok"]       # 강도만 (균열 간격은 주철근 간격 행)
                    self._set(k, key, f"{'OK' if ok_m else 'NG'}({f['ratio']:.3f})", ok_m)
            ok_v = sh["ok"] and sh["phi_vn"] + 1e-9 >= sh["vu"]          # 강도만 (간격은 전단철근 간격 행)
            self._set(k, "vu", f"{'OK' if ok_v else 'NG'}({s['ratio_v']:.3f})", ok_v)
            tor = sh["tor"]
            if not tor:
                self._set(k, "tu", "-", None)
            elif not tor["need"]:
                self._set(k, "tu", "무시(≤Tth)", True)
            else:
                self._set(k, "tu", "설계 " + ("OK" if tor["sec_ok"] else "NG"), tor["sec_ok"])
            for side, upper in (("top", True), ("bot", False)):
                lay = [l_ for l_ in s["layers"] if l_[0].startswith("top" if upper else "bot")]
                if not lay:
                    self._set(k, side, "-", None)
                    continue
                as_ = sum(l_[2] for l_ in lay)
                yc = sum(l_[1] * l_[2] for l_ in lay) / as_
                d = (h - yc) if upper else yc
                fit = not any(w.startswith("상부" if upper else "하부") and "순간격" in w for w in s["warn"])
                self._set(k, side, f"{'OK' if fit else 'NG'}({as_ / (b * d) * 100:.3f}%)", fit)
            self._set(k, "side", f"{2 * sec['sn'] * B.BARS[sec['sb']][1]:.0f} mm²" if sec["sn"] else "", None)
            # 주철근 간격 (인장측 1단)
            sp = s["spacing"]
            parts, ok_all = [], True
            for f in s["flex"]:
                if f["none"]:
                    continue
                tag = "B" if f["positive"] else "T"
                if f["s"] is None:
                    parts.append(f"{tag}:1개")
                else:
                    parts.append(f"{tag}:{f['s']:.0f}({'OK' if f['crack_ok'] else 'NG'})")
                    ok_all &= f["crack_ok"]
            tail = f"  ≤{sp['smax']:.0f}"
            if parts:
                self._set(k, "sp_main", "  ".join(parts) + tail, ok_all)
            else:
                self._set(k, "sp_main", "-", None)
            # 전단철근 간격
            if sh.get("s_req") is None:
                self._set(k, "sp_stir", "S:배치불가(NG)", False)
            elif sec["vs"] > 0:
                self._set(k, "sp_stir", f"S:{sec['vs']:g}({'OK' if sh['s_ok'] else 'NG'})  소요{sh['s_req']}", sh["s_ok"])
            else:
                self._set(k, "sp_stir", f"S:{sh['s_req']}(자동)", True)
            why = []
            for f in s["flex"]:
                side = "하부" if f["positive"] else "상부"
                if f["none"]:
                    why.append(f"{side} 인장철근이 없습니다")
                    continue
                if not f["ok_str"]:
                    why.append(f"{side} 휨강도 부족 (Mu/φMn = {f['ratio']:.3f})")
                if not f["ok_eps"]:
                    why.append(f"{side} 과다 배근 (εt = {f['eps_t']:.4f} < {f['eps_min']:.4f})")
                if not f["min_ok"]:
                    why.append(f"{side} 최소 휨강도 미달 (φMn < 1.2Mcr, 4/3Mu)")
                if not f["crack_ok"] and f["s"] is not None:
                    why.append(f"{side} 주근 간격 {f['s']:.0f} > 균열제어 최대 {f['smax']:.0f} mm")
            if not ok_v:
                why.append(f"전단강도 부족 (Vu/φVn = {s['ratio_v']:.3f})")
            for w in s["warn"]:
                if w not in why and not any(x in w for x in ("휨강도", "과다")):
                    why.append(w)
            if why:
                self._why[k] = (s["label"], why)
                self._set(k, "comment", f"N.G. ({'①②③'[k - 1]} 아래 참조)" if not s["ok"] else f"주의 ({'①②③'[k - 1]})",
                          False if not s["ok"] else None)
            else:
                self._set(k, "comment", "O.K." if s["ok"] else "N.G.", s["ok"])
        self._show_why()

    def _show_why(self):
        lines = []
        for k in sorted(self._why):
            lbl, items = self._why[k]
            for i, w in enumerate(items):
                lines.append(f"{'①②③'[k - 1] if i == 0 else '   '} [{lbl}] {w}")
        try:
            self.lbl_why.config(text="\n".join(lines), wraplength=max(self.g_grid.winfo_reqwidth(), 300))
        except tk.TclError:
            pass

    # ── 계산 ─────────────────────────────────────────────────
    def kind_text(self, vals):
        return f"{n_sections(vals)}단면"

    def normalize_values(self, vals):
        merged = super().normalize_values(vals)
        for k in range(1, 4):                        # 이전 파일: 2단 철근이 없으면 1단과 같게
            if f"{k}_tb2" not in vals:
                merged[f"{k}_tb2"] = merged[f"{k}_tb"]
            if f"{k}_bb2" not in vals:
                merged[f"{k}_bb2"] = merged[f"{k}_bb"]
        if merged["end3"] not in (END_DISC, END_CONT):
            merged["end3"] = END_DISC
        if "opt_diff" not in vals:                   # 이전 파일: 단마다 직경이 다르면 '다른 철근 사용'
            for k in range(1, 4):
                if len({merged[f"{k}_{x}"] for x in ("tb", "tb2", "bb", "bb2")}) > 1:
                    merged["opt_diff"] = "1"
        return merged

    def compute(self, vals):
        res = B.calc_beam(inputs_from_values(vals))
        nm = res["name"] or "(이름 없음)"
        bad = [s["label"] for s in res["sections"] if not s["ok"]]
        status = (f"{nm}  ·  {res['b']:g} × {res['h']:g} mm  ·  단면 {len(res['sections'])}개  ─  "
                  + ("설계 결과 O.K." if not bad else f"N.G. : {', '.join(bad)} — 계산서의 빨간 항목을 확인하세요."))
        rep = B.build_report(res) if getattr(self, "detail", False) else B.build_simple(res)
        return {"report": rep, "sketch": B.sketch(res), "box": B.sketch_box(res), "ok": res["ok"],
                "status": status, "res": res}


def open_beam_lite(parent, username=""):
    return BeamLiteWindow(parent, username=username)
