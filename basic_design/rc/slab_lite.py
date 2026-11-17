"""
basic_design/rc/slab_lite.py
RC Slab — Lite : 1방향 / 2방향 단일 슬래브(등분포하중) 설계 창

  왼쪽   부재 목록 (Memb List) — 추가 · 복제 · 삭제 · 순서 이동, 파일(.slab) 한 개에 모두 저장
  가운데 입력 패널 (Name · Type · 치수 · 재료 · 하중 · 지지 형식 · 사용 철근)
  오른쪽 계산서 (Design Conditions / Min. Thk. / Flexure / Summary / Shear)
  출력   A4 PDF (머릿말 "RC SLAB DESIGN") — 현재 부재 / 전체 부재
"""
import tkinter as tk

from .. import theme as T
from ..member_app import MemberWindow, safe_name  # noqa: F401  (safe_name: 이전 이름 호환)
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
    "phi_f": "0.85", "phi_v": "0.75",
    "months": "60", "lim_live": "360", "lim_long": "480", "sus_live": "50",
}
LABELS = {
    "phi_f": "휨 강도감소계수 φf", "phi_v": "전단 강도감소계수 φv", "months": "재하기간",
    "lim_live": "활하중 처짐제한 L/", "lim_long": "장기처짐제한 L/", "sus_live": "지속 활하중 비율",
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
    for k in ("t", "cc", "fck", "fy13", "fy16", "wd", "wl", "phi_f", "phi_v"):
        inp[k] = _num(vals, k)
    if one:
        m = _num(vals, "months")
        if not 1 <= m <= 60:
            raise S.SlabInputError("재하기간은 1 ~ 60 개월로 입력하세요.")
        ll, lg = _num(vals, "lim_live"), _num(vals, "lim_long")
        if not (1 <= ll <= 360 and 1 <= lg <= 480):
            raise S.SlabInputError("처짐제한은 활하중 L/1 ~ L/360, 장기 L/1 ~ L/480 범위로 입력하세요.")
        sl = _num(vals, "sus_live")
        if not 0 <= sl <= 100:
            raise S.SlabInputError("지속 활하중 비율은 0 ~ 100 % 로 입력하세요.")
        inp.update(months=m, lim_live=ll, lim_long=lg, sus_live=sl / 100.0)
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


class SlabLiteWindow(MemberWindow):
    TITLE = "RC Slab"
    BADGE = "Lite"
    SUBTITLE = "단일 슬래브 · 등분포하중 · 1방향 / 2방향"
    MODULE = "rc_slab_lite"
    FILE_EXT = ".slab"
    FILE_DESC = "Slab Lite 파일"
    DEFAULT_FILE = "slab_list"
    PRINT_HEADER = PRINT_HEADER
    FOOTER = "StrCAD  ·  Basic Design  │  RC Slab Lite"
    DEFAULTS = DEFAULTS
    InputError = S.SlabInputError

    # ── 입력 패널 ────────────────────────────────────────────
    def build_inputs(self, p):
        f = self.top_fields
        self._lbl(f, "Type :").grid(row=1, column=0, sticky="e", pady=2)
        self._cmb(f, "type", [TYPE_1WAY, TYPE_2WAY], 13, "readonly").grid(row=1, column=1, sticky="w", padx=4)
        self.v["type"].trace_add("write", lambda *_: self._on_type())
        self.v["case"].trace_add("write", lambda *_: self._draw_case())

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

        row5 = tk.Frame(p, bg=T.SURFACE)
        row5.pack(fill="x", padx=10, pady=4)
        g = self._group(row5, "강도감소계수")
        g.pack(side="left", fill="y")
        self._field(g, 0, "휨 φf :", "phi_f", "(인장지배)", width=6)
        self._field(g, 1, "전단 φv :", "phi_v", "", width=6)

        # 처짐 검토 설정 — 1방향 슬래브가 최소두께 N.G. 일 때만 표시
        self.row_defl = tk.Frame(p, bg=T.SURFACE, height=1)
        self.row_defl.pack(fill="x", padx=10, pady=(4, 0))
        g = self.g_defl = self._group(self.row_defl, "처짐 검토  (최소두께 N.G.)")
        self._lbl(g, "재하기간 :", anchor="e").grid(row=0, column=0, sticky="e", pady=2)
        tk.Spinbox(g, from_=1, to=60, increment=1, textvariable=self.v["months"], width=5, font=self.f_n,
                   fg=T.INPUT_FG, relief="solid", bd=1, command=self.calc).grid(row=0, column=1, sticky="w", padx=4)
        self.lbl_xi = self._lbl(g, "")
        self.lbl_xi.grid(row=0, column=2, columnspan=2, sticky="w")
        self._lbl(g, "활하중 순간처짐 :", anchor="e").grid(row=1, column=0, sticky="e", pady=2)
        f = tk.Frame(g, bg=T.SURFACE)
        f.grid(row=1, column=1, columnspan=3, sticky="w", padx=4)
        self._lbl(f, "L /").pack(side="left")
        self._cmb(f, "lim_live", ["180", "240", "360"], 5).pack(side="left", padx=3)
        self._lbl(f, "(1 ~ 360)", fg=T.MUTED).pack(side="left")
        self._lbl(g, "장기처짐 :", anchor="e").grid(row=2, column=0, sticky="e", pady=2)
        f = tk.Frame(g, bg=T.SURFACE)
        f.grid(row=2, column=1, columnspan=3, sticky="w", padx=4)
        self._lbl(f, "L /").pack(side="left")
        self._cmb(f, "lim_long", ["240", "360", "480"], 5).pack(side="left", padx=3)
        self._lbl(f, "(1 ~ 480)", fg=T.MUTED).pack(side="left")
        self._lbl(g, "지속 활하중 :", anchor="e").grid(row=3, column=0, sticky="e", pady=2)
        f = tk.Frame(g, bg=T.SURFACE)
        f.grid(row=3, column=1, columnspan=3, sticky="w", padx=4)
        self._ent(f, "sus_live", 5).pack(side="left")
        self._lbl(f, "%  (지속하중 = D + 비율 × L)", fg=T.MUTED).pack(side="left", padx=3)
        self.v["months"].trace_add("write", lambda *_: self._show_xi())
        self._show_xi()

    # ── Type 에 따라 달라지는 입력 ───────────────────────────
    def after_load(self):
        self._on_type()

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

    def _show_xi(self):
        try:
            m = float(self.v["months"].get())
            self.lbl_xi.config(text=f"개월   →  ξ = {S.xi_of(m):.2f}")
        except (ValueError, tk.TclError):
            self.lbl_xi.config(text="개월")

    def on_result(self, res):
        """1방향 · 최소두께 N.G. 일 때만 처짐 설정을 보여 준다"""
        shown = getattr(self, "_defl_shown", False)
        if res is None:                                 # 입력 오류 중에는 1방향이면 그대로 둔다
            need = shown and self.v["type"].get() == TYPE_1WAY
        else:
            need = res["type"] == "1way" and not res["h_ok"]
        if need and not shown:
            self.g_defl.pack(side="left", fill="y")
        elif not need and shown:
            self.g_defl.pack_forget()
            self.row_defl.configure(height=1)
        self._defl_shown = need

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
    # ── 계산 ─────────────────────────────────────────────────
    def collect(self):
        return inputs_from_values(self.current_values())

    def kind_text(self, vals):
        return "1W" if vals.get("type") == TYPE_1WAY else "2W"

    def new_member_values(self):
        vals = dict(DEFAULTS)
        if hasattr(self, "v"):
            vals["type"] = self.v["type"].get()
        return vals

    def normalize_values(self, vals):
        merged = super().normalize_values(vals)
        if merged["type"] not in (TYPE_1WAY, TYPE_2WAY):
            merged["type"] = TYPE_2WAY
        return merged

    def compute(self, vals):
        res = S.calculate(inputs_from_values(vals))
        nm = res["name"] or "(이름 없음)"
        kind = "1방향" if res["type"] == "1way" else "2방향"
        status = (f"{nm}  ·  {kind} 슬래브  ·  T = {res['t']:g} mm  ─  "
                  + ("설계 결과 O.K." if res["ok"] else "N.G. 항목이 있습니다 — 계산서의 빨간 항목을 확인하세요."))
        return {"report": R.build(res), "sketch": R.sketch(res), "box": R.sketch_box(res), "ok": res["ok"],
                "status": status, "res": res}


def open_slab_lite(parent, username=""):
    return SlabLiteWindow(parent, username=username)
