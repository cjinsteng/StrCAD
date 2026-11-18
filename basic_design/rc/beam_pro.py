"""
basic_design/rc/beam_pro.py
RC Beam — Pro : 깊은보(Deep Beam) 스트럿-타이 모델 설계 창

  · 단순지지 깊은보 하나(전단면) — KDS 14 20 22 4.7 · KDS 14 20 24
  · 입력: 단면 · 재료 · 경간 · 받침폭 · 집중하중(최대 3개, 위치 · 재하판 폭) · 등분포하중 · 자중
  · 배근: 하현 타이 철근 직경(개수 0 = 자동), 수직 · 수평 전단철근 직경(간격 0 = 자동)
  · 결과: Simple(표 · STM 그림 · 배근도, 기본) / Detail(풀이)
  (부재 목록 · 저장 · A4 출력은 공통 틀 member_app.MemberWindow)
"""
import tkinter as tk

from .. import theme as T
from ..member_app import MemberWindow
from . import beam_calc as B
from . import beam_stm as M

N_LOADS = 3
DEFAULTS = {"name": "DB1", "b": "400", "h": "1500", "cc": "40", "fck": "30", "fy": "400", "fyv": "400",
            "L": "4000", "lb1": "400", "lb2": "400", "wu": "0", "selfw": "1",
            "tie_bar": "D25", "tie_n": "0", "v_bar": "D13", "v_legs": "2", "v_s": "0", "h_bar": "D13", "h_s": "0",
            "p1": "1200", "x1": "2000", "lp1": "400", "p2": "0", "x2": "0", "lp2": "300", "p3": "0", "x3": "0",
            "lp3": "300"}
LABELS = {"b": "b", "h": "h", "cc": "순피복", "fck": "fck", "fy": "fy", "fyv": "fyv", "L": "경간 L",
          "lb1": "좌측 받침폭", "lb2": "우측 받침폭", "wu": "등분포하중 wu", "tie_n": "타이 개수",
          "v_legs": "수직철근 다리 수", "v_s": "수직철근 간격", "h_s": "수평철근 간격"}


def _num(vals, key, label=None):
    s = str(vals.get(key, "")).strip().replace(",", "")
    if s == "":
        s = "0"
    try:
        return float(s)
    except ValueError:
        raise M.DeepBeamInputError(f"'{label or LABELS.get(key, key)}' 값이 숫자가 아닙니다: \"{s}\"") from None


def inputs_from_values(vals):
    inp = {"name": vals.get("name", "")}
    for k in ("b", "h", "cc", "fck", "fy", "fyv", "L", "lb1", "lb2", "wu", "tie_n", "v_legs", "v_s", "h_s"):
        inp[k] = _num(vals, k)
    inp["selfw"] = str(vals.get("selfw", "1")) == "1"
    for k, lst in (("tie_bar", B.BAR_LIST), ("v_bar", M.WEB_BARS), ("h_bar", M.WEB_BARS)):
        v = vals.get(k, DEFAULTS[k])
        if v not in lst:
            raise M.DeepBeamInputError(f"철근 '{v}' 을(를) 목록에서 고르세요.")
        inp[k] = v
    inp["loads"] = []
    for i in range(1, N_LOADS + 1):
        P = _num(vals, f"p{i}", f"집중하중 P{i}")
        if P > 0:
            inp["loads"].append((P, _num(vals, f"x{i}", f"P{i} 위치 x"), _num(vals, f"lp{i}", f"P{i} 재하판 폭")))
        elif P < 0:
            raise M.DeepBeamInputError(f"집중하중 P{i} 는 0 이상이어야 합니다.")
    if inp["wu"] < 0:
        raise M.DeepBeamInputError("등분포하중은 0 이상이어야 합니다.")
    return inp


class BeamProWindow(MemberWindow):
    TITLE = "RC Beam"
    BADGE = "Pro"
    SUBTITLE = "깊은보 · 스트럿-타이 모델 설계 (KDS 14 20 24)"
    MODULE = "rc_beam_pro"
    FILE_EXT = ".dbeam"
    FILE_DESC = "Beam Pro(깊은보) 파일"
    DEFAULT_FILE = "deep_beam_list"
    PRINT_HEADER = "RC DEEP BEAM DESIGN"
    FOOTER = "StrCAD  ·  Basic Design  │  RC Beam Pro"
    DEFAULTS = DEFAULTS
    InputError = M.DeepBeamInputError
    INPUT_WIDTH = 470
    WIN_SIZE = "1700x950"

    # ── 입력 패널 ────────────────────────────────────────────
    def build_inputs(self, p):
        self._after = None
        self.f_s = (T.FAM, 8)
        self.detail = False
        self.btn_detail = tk.Button(self.top_bar, text="Detail ▸", command=self.toggle_detail, font=(T.FAM, 9, "bold"),
                                    bg="white", fg=T.NAVY, relief="groove", cursor="hand2", padx=10, pady=6)
        self.btn_detail.pack(side="right", padx=(0, 6))

        row = tk.Frame(p, bg=T.SURFACE)
        row.pack(fill="x", padx=10, pady=2)
        g = self._group(row, "단면")
        g.pack(side="left", fill="y")
        self._field(g, 0, "b :", "b", "mm", width=6)
        self._field(g, 1, "h :", "h", "mm", width=6)
        self._field(g, 2, "순피복 :", "cc", "mm", width=6)
        g = self._group(row, "재료강도 (N/mm²)")
        g.pack(side="left", fill="y", padx=(8, 0))
        self._field(g, 0, "fck :", "fck", "", widget=self._cmb(g, "fck", ["24", "27", "30", "35", "40", "50"], 5))
        self._field(g, 1, "fy 타이 :", "fy", "", widget=self._cmb(g, "fy", ["400", "500", "600"], 5))
        self._field(g, 2, "fyv 복부 :", "fyv", "", widget=self._cmb(g, "fyv", ["400", "500", "600"], 5))

        g = self._group(p, "경간 · 받침  (받침 중심 간 거리)")
        g.pack(fill="x", padx=10, pady=2)
        self._lbl(g, "L :").grid(row=0, column=0, sticky="e")
        self._ent(g, "L", 7).grid(row=0, column=1, padx=3)
        self._lbl(g, "mm    받침폭  좌 :").grid(row=0, column=2, sticky="e")
        self._ent(g, "lb1", 5).grid(row=0, column=3, padx=3)
        self._lbl(g, "우 :").grid(row=0, column=4, sticky="e")
        self._ent(g, "lb2", 5).grid(row=0, column=5, padx=3)
        self._lbl(g, "mm").grid(row=0, column=6, sticky="w")

        g = self._group(p, "계수하중  (상면 재하, x = 좌측 받침 중심에서)")
        g.pack(fill="x", padx=10, pady=2)
        for c, txt in enumerate(("", "Pu (kN)", "x (mm)", "재하판 폭 (mm)")):
            self._lbl(g, txt, fg=T.MUTED).grid(row=0, column=c, padx=3)
        self._load_entries = []
        for i in range(1, N_LOADS + 1):
            self._lbl(g, f"P{i}").grid(row=i, column=0, sticky="e", padx=(0, 3))
            row_e = []
            for c, key in enumerate((f"p{i}", f"x{i}", f"lp{i}"), 1):
                e = self._ent(g, key, 8)
                e.grid(row=i, column=c, padx=3, pady=1)
                row_e.append(e)
            self._load_entries.append(row_e)
        f2 = tk.Frame(g, bg=T.SURFACE)
        f2.grid(row=N_LOADS + 1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        self._lbl(f2, "등분포 wu :").pack(side="left")
        self._ent(f2, "wu", 6).pack(side="left", padx=3)
        self._lbl(f2, "kN/m").pack(side="left")
        tk.Checkbutton(f2, text="자중 포함 (1.2D)", variable=self.v["selfw"], onvalue="1", offvalue="0",
                       font=self.f_n, bg=T.SURFACE, command=self._auto).pack(side="left", padx=(12, 0))
        self._lbl(g, "Pu = 0 인 줄은 무시 · 집중하중이 없으면 등분포를 L/4 · 3L/4 두 절점으로", fg=T.MUTED).grid(
            row=N_LOADS + 2, column=0, columnspan=4, sticky="w")

        g = self._group(p, "배근  (0 = 자동 설계)")
        g.pack(fill="x", padx=10, pady=2)
        self._lbl(g, "하현 타이 :").grid(row=0, column=0, sticky="e", pady=2)
        self._cmb(g, "tie_bar", B.BAR_LIST[2:], 5, "readonly").grid(row=0, column=1, sticky="w", padx=3)
        self._lbl(g, "개수").grid(row=0, column=2, sticky="e")
        self._ent(g, "tie_n", 4).grid(row=0, column=3, sticky="w", padx=3)
        self._lbl(g, "수직 전단철근 :").grid(row=1, column=0, sticky="e", pady=2)
        self._cmb(g, "v_bar", M.WEB_BARS, 5, "readonly").grid(row=1, column=1, sticky="w", padx=3)
        self._lbl(g, "간격").grid(row=1, column=2, sticky="e")
        self._ent(g, "v_s", 4).grid(row=1, column=3, sticky="w", padx=3)
        self._lbl(g, "다리").grid(row=1, column=4, sticky="e")
        self._ent(g, "v_legs", 3).grid(row=1, column=5, sticky="w", padx=3)
        self._lbl(g, "수평 전단철근 :").grid(row=2, column=0, sticky="e", pady=2)
        self._cmb(g, "h_bar", M.WEB_BARS, 5, "readonly").grid(row=2, column=1, sticky="w", padx=3)
        self._lbl(g, "간격").grid(row=2, column=2, sticky="e")
        self._ent(g, "h_s", 4).grid(row=2, column=3, sticky="w", padx=3)
        self._lbl(g, "(양면)", fg=T.MUTED).grid(row=2, column=4, columnspan=2, sticky="w")

        g = self._group(p, "설계 결과")
        g.pack(fill="x", padx=10, pady=(6, 2))
        self.res_rows = {}
        for r_, (key, txt) in enumerate((("deep", "판정"), ("tie", "하현 타이"), ("vert", "수직철근"),
                                         ("horz", "수평철근"), ("ratio", "최대 비율*"))):
            self._lbl(g, txt + " :", fg=T.MUTED).grid(row=r_, column=0, sticky="e", pady=1)
            lb = tk.Label(g, text="-", font=self.f_b, bg=T.SURFACE, fg=T.INK, anchor="w", width=34)
            lb.grid(row=r_, column=1, sticky="w", padx=4)
            self.res_rows[key] = lb
        self.lbl_why = tk.Label(p, text="", font=self.f_s, bg=T.SURFACE, fg=T.NG, justify="left", anchor="nw",
                                wraplength=420)
        self.lbl_why.pack(anchor="nw", fill="x", padx=12, pady=(2, 6))

        for k in DEFAULTS:
            if k not in ("name", "selfw"):
                self.v[k].trace_add("write", lambda *_: self._auto())
        self._nav_bind()

    def _nav_bind(self):
        """하중 표: 방향키로 칸 이동"""
        grid = self._load_entries
        for i, row in enumerate(grid):
            for j, e in enumerate(row):
                def mv(_e, di, dj, i=i, j=j):
                    ii, jj = i + di, j + dj
                    if 0 <= ii < len(grid) and 0 <= jj < len(grid[0]):
                        grid[ii][jj].focus_set()
                        return "break"
                e.bind("<Up>", lambda ev, f=mv: f(ev, -1, 0))
                e.bind("<Down>", lambda ev, f=mv: f(ev, 1, 0))
                e.bind("<Left>", lambda ev, f=mv, e=e: f(ev, 0, -1) if e.index("insert") == 0 else None)
                e.bind("<Right>", lambda ev, f=mv, e=e: f(ev, 0, 1) if e.index("insert") == len(e.get()) else None)

    def _auto(self):
        if self._busy:
            return
        if self._after is not None:
            try:
                self.win.after_cancel(self._after)
            except tk.TclError:
                pass
        self._after = self.win.after(350, self._auto_run)

    def _auto_run(self):
        self._after = None
        self.calc(silent=True)

    def toggle_detail(self):
        self.detail = not self.detail
        self.btn_detail.config(text="◂ Simple" if self.detail else "Detail ▸",
                               bg="#FDE7D0" if self.detail else "white")
        self.calc(silent=True)

    # ── 결과 ─────────────────────────────────────────────────
    def on_result(self, res):
        if not getattr(self, "res_rows", None):
            return
        if res is None:
            for lb in self.res_rows.values():
                lb.config(text="-", fg=T.MUTED)
            self.lbl_why.config(text="")
            return
        rb = M.rebar_text(res)
        self.res_rows["deep"].config(text=("깊은보 · " if res["is_deep"] else "깊은보 아님 · ")
                                     + ("O.K." if res["ok"] else "N.G."),
                                     fg=T.OK if res["ok"] else T.NG)
        self.res_rows["tie"].config(text=rb["tie"] + ("" if res["auto_tie"] else "  (입력)"), fg=T.INK)
        self.res_rows["vert"].config(text=rb["vert"], fg=T.INK if res["web"]["v_ok"] else T.NG)
        self.res_rows["horz"].config(text=rb["horz"], fg=T.INK if res["web"]["h_ok"] else T.NG)
        pool = [c for c in res["checks"] if c["kind"] != "상현 스트럿"] + \
               [c for c in res["ncheck"] if c["face"] != "상현면"]          # 상현 ws 는 소요폭으로 정함(비율 1.0)
        worst = max(pool or res["checks"], key=lambda c: c["ratio"])
        nm = worst.get("name") or f"{worst['node']} {worst['face']}"
        self.res_rows["ratio"].config(text=f"{worst['ratio']:.3f}  ({nm})", fg=T.OK if worst["ok"] else T.NG)
        marks = "①②③④⑤⑥⑦⑧⑨⑩"
        lines = [f"{marks[i] if i < 10 else '·'} {w}" for i, w in enumerate(res["why"])]
        if not res["is_deep"]:
            lines.append("※ 깊은보 조건(ln ≤ 4h 또는 하중이 받침에서 2h 이내)이 아닙니다.")
        lines.append("* 상현 스트럿 폭 ws 는 소요폭으로 정하므로(비율 1.0) 최대 비율에서 제외")
        self.lbl_why.config(text="\n".join(lines))

    # ── 계산 ─────────────────────────────────────────────────
    def kind_text(self, vals):
        return "깊은보 STM"

    def compute(self, vals):
        res = M.calc_deep(inputs_from_values(vals))
        nm = res["name"] or "(이름 없음)"
        status = (f"{nm}  ·  {res['b']:g} × {res['h']:g} mm  ·  L = {res['L']:,.0f} mm  ─  "
                  + ("설계 결과 O.K." if res["ok"] else "N.G. — 입력창 아래 사유와 계산서의 빨간 항목을 확인하세요."))
        rep = M.build_report(res) if self.detail else M.build_simple(res)
        return {"report": rep, "sketch": None, "box": (0, 0, 0, 0), "ok": res["ok"], "status": status, "res": res}


def open_beam_pro(parent, username=""):
    return BeamProWindow(parent, username=username)
