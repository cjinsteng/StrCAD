"""
basic_design/rc/slab_table_app.py
RC Slab — Table : 두께 · 철근 · 간격별 설계휨강도 일람표 창
  (부재 목록 · 저장 · A4 출력은 Slab Lite 와 같은 공통 틀 — member_app.MemberWindow)
"""
import tkinter as tk

from .. import theme as T
from ..member_app import MemberWindow
from . import slab_calc as S
from . import slab_table as TB

THK_DEFAULT = ["120", "150", "180", "200", "250", "300"]
SP_DEFAULT = ["100", "120", "125", "150", "200", "250", "300"]

DEFAULTS = {
    "name": "TS1", "fck": "24", "fy13": "400", "fy16": "500", "cc": "20", "bar": "D13",
    "expo": "그 외 환경 (κcr=210)", "phi_f": "0.85", "phi_v": "0.75", "t_n": "2",
}
DEFAULTS.update({f"t{i + 1}": v for i, v in enumerate(THK_DEFAULT)})
DEFAULTS.update({f"s{i + 1}": v for i, v in enumerate(SP_DEFAULT)})
LABELS = {"fck": "fck", "fy13": "fy(D13↓)", "fy16": "fy(D16↑)", "cc": "피복 Cc",
          "phi_f": "휨 강도감소계수 φf", "phi_v": "전단 강도감소계수 φv"}
LABELS.update({f"t{i}": f"두께 T{i}" for i in range(1, 7)})
LABELS.update({f"s{i}": f"간격 S{i}" for i in range(1, 8)})


def _num(vals, key):
    s = str(vals.get(key, "")).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        raise TB.TableInputError(f"'{LABELS.get(key, key)}' 값이 숫자가 아닙니다: \"{s}\"") from None


def _t_count(vals):
    try:
        return max(1, min(TB.MAX_THK, int(vals.get("t_n", 2))))
    except (TypeError, ValueError):
        return 2


def inputs_from_values(vals):
    inp = {"name": str(vals.get("name", "")).strip(), "bar": str(vals.get("bar", "")).strip() or "D13",
           "kcr": S.EXPOSURES.get(vals.get("expo"), 210.0)}
    for k in ("fck", "fy13", "fy16", "cc", "phi_f", "phi_v"):
        inp[k] = _num(vals, k)
    inp["thks"] = [_num(vals, f"t{i}") for i in range(1, _t_count(vals) + 1)]
    inp["spacings"] = [_num(vals, f"s{i}") for i in range(1, TB.MAX_SP + 1) if str(vals.get(f"s{i}", "")).strip()]
    return inp


class SlabTableWindow(MemberWindow):
    TITLE = "RC Slab"
    BADGE = "Table"
    SUBTITLE = "두께 · 철근 · 간격별 설계휨강도(φMn) 일람표"
    MODULE = "rc_slab_table"
    FILE_EXT = ".slabt"
    FILE_DESC = "Slab Table 파일"
    DEFAULT_FILE = "slab_table"
    PRINT_HEADER = "RC SLAB TABLE"
    FOOTER = "StrCAD  ·  Basic Design  │  RC Slab Table"
    DEFAULTS = DEFAULTS
    InputError = TB.TableInputError

    # ── 입력 패널 ────────────────────────────────────────────
    def build_inputs(self, p):
        g = self._group(p, "재료강도")
        g.pack(fill="x", padx=10, pady=4)
        self._field(g, 0, "fck :", "fck", "N/mm²", widget=self._cmb(g, "fck", ["21", "24", "27", "30", "35", "40"], 5))
        self._field(g, 1, "fy(D13↓) :", "fy13", "N/mm²", widget=self._cmb(g, "fy13", ["300", "400", "500", "600"], 5))
        self._field(g, 2, "fy(D16↑) :", "fy16", "N/mm²", widget=self._cmb(g, "fy16", ["300", "400", "500", "600"], 5))

        row = tk.Frame(p, bg=T.SURFACE)
        row.pack(fill="x", padx=10, pady=4)
        col1 = tk.Frame(row, bg=T.SURFACE)
        col1.pack(side="left", fill="y", anchor="n")
        self.g_thk = self._group(col1, "슬래브 두께")
        self.g_thk.pack(fill="x")
        gb = self._group(col1, "사용 철근")
        gb.pack(fill="x", pady=(8, 0))
        self._field(gb, 0, "철근 :", "bar", "", widget=self._cmb(gb, "bar", S.BAR_ORDER, 6, "readonly"))
        self._lbl(gb, "= 표의 첫 행", fg=T.MUTED).grid(row=1, column=0, columnspan=3, sticky="w")

        gs = self._group(row, "철근 간격")
        gs.pack(side="left", fill="y", anchor="n", padx=(8, 0))
        for i in range(1, TB.MAX_SP + 1):
            self._field(gs, i - 1, f"S{i} :", f"s{i}", "mm", width=6)
        self._lbl(gs, "(빈칸은 생략)", fg=T.MUTED).grid(row=TB.MAX_SP, column=0, columnspan=3, sticky="w", pady=(2, 0))

        row2 = tk.Frame(p, bg=T.SURFACE)
        row2.pack(fill="x", padx=10, pady=4)
        g = self._group(row2, "강도감소계수 · 균열제어")
        g.pack(fill="x")
        self._field(g, 0, "휨 φf :", "phi_f", "(인장지배)", width=6)
        self._field(g, 1, "전단 φv :", "phi_v", "", width=6)
        self._field(g, 2, "노출환경 :", "expo", "", widget=self._cmb(g, "expo", list(S.EXPOSURES), 19, "readonly"))

        lg = self._group(p, "표시 안내")
        lg.pack(fill="x", padx=10, pady=4)
        items = [("---", None, T.NG, "과다 배근 (εt < εt,min) — 사용 불가"),
                 ("12.3", "#FEF3C7", "#854D0E", "간격 > min(2t, 300)"),
                 ("12.3", "#FFEDD5", "#9A3412", "수축·온도철근 미달"),
                 ("@250", "#FDBA74", T.INK, "균열제어 간격 초과 (주방향)"),
                 ("12.3*", None, T.INK, "변화구간 (φ 감소)")]
        for r, (txt, bg, fg, desc) in enumerate(items):
            tk.Label(lg, text=txt, width=6, font=self.f_b, bg=bg or T.SURFACE, fg=fg).grid(row=r, column=0, pady=1)
            self._lbl(lg, desc).grid(row=r, column=1, sticky="w", padx=6)
        self._lbl(lg, "칸에 마우스를 올리면 계산값과 사유가 보입니다.", fg=T.MUTED).grid(
            row=len(items), column=0, columnspan=2, sticky="w", pady=(4, 0))

    def _build_thk(self):
        g = self.g_thk
        for w in g.winfo_children():
            w.destroy()
        n = _t_count(self.current_values())
        for i in range(1, n + 1):
            self._field(g, i - 1, f"T{i} :", f"t{i}", "mm", width=6)
        self._field(g, n, "Cc :", "cc", "mm", width=6)
        bf = tk.Frame(g, bg=T.SURFACE)
        bf.grid(row=n + 1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        for txt, step, ok in (("+ 추가", 1, n < TB.MAX_THK), ("− 삭제", -1, n > 1)):
            tk.Button(bf, text=txt, font=(T.FAM, 8), bg="white", fg=T.INK if ok else T.MUTED, relief="groove",
                      cursor="hand2" if ok else "arrow", state="normal" if ok else "disabled", padx=6, pady=0,
                      command=lambda k=step: self._thk_step(k)).pack(side="left", padx=(0, 4))
        self._lbl(bf, f"{n} / {TB.MAX_THK}", fg=T.MUTED).pack(side="left", padx=4)

    def _thk_step(self, k):
        n = _t_count(self.current_values()) + k
        if 1 <= n <= TB.MAX_THK:
            self.v["t_n"].set(str(n))
            self._build_thk()
            self.calc(silent=True)

    def after_load(self):
        self._build_thk()
        self.calc(silent=True)

    # ── 계산 ─────────────────────────────────────────────────
    def kind_text(self, vals):
        return f"T×{_t_count(vals)}"

    def compute(self, vals):
        res = TB.calc_table(inputs_from_values(vals))
        ok = TB.overall_ok(res)
        nm = res["name"] or "(이름 없음)"
        thk = ", ".join(f"{b['t']:g}" for b in res["blocks"])
        status = (f"{nm}  ·  T = {thk} mm  ·  간격 {len(res['spacings'])}개  ·  {res['labels'][0]} 기준  ─  "
                  + ("칸에 마우스를 올리면 계산값과 판정 사유가 표시됩니다." if ok
                     else f"사용 철근({res['labels'][0]}) 행에 과다 배근('---') 칸이 있습니다 — 마우스를 올려 사유 확인"))
        return {"report": TB.build_report(res), "sketch": None, "box": (590, 18, 290, 330), "ok": ok,
                "status": status, "res": res}


def open_slab_table(parent, username=""):
    return SlabTableWindow(parent, username=username)
