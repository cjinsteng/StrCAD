"""
basic_design/rc/beam_lite.py
RC Beam — Lite : 직사각형 보 단면 검토 창 (단면 1~3개: 전단면 / 단부·중앙부 / 연속단부·중앙부·불연속단부)
  (부재 목록 · 저장 · A4 출력은 공통 틀 member_app.MemberWindow)
"""
import tkinter as tk

from .. import theme as T
from ..member_app import MemberWindow
from . import beam_calc as B
from . import slab_calc as S

TYPE_RECT = "사각 보"
SEC_KEYS = ["tn1", "tn2", "tb", "bn1", "bn2", "bb", "sn", "sb", "vl", "vb", "vs", "mn", "mp", "vu", "tu"]
SEC_DEFAULT = {"tn1": "3", "tn2": "0", "tb": "D22", "bn1": "3", "bn2": "0", "bb": "D22", "sn": "0", "sb": "D13",
               "vl": "2", "vb": "D10", "vs": "0", "mn": "0", "mp": "100", "vu": "100", "tu": "0"}
DEFAULTS = {"name": "B1", "type": TYPE_RECT, "b": "400", "h": "600", "cc": "40", "fck": "24", "fy": "400", "fys": "400",
            "phi_f": "0.85", "phi_v": "0.75", "expo": "그 외 환경 (κcr=210)", "n_sec": "1"}
for _k in (1, 2, 3):
    for _key, _v in SEC_DEFAULT.items():
        DEFAULTS[f"{_k}_{_key}"] = _v
LABELS = {"b": "B", "h": "H", "cc": "순피복 Cc", "fck": "fck", "fy": "fy", "fys": "fys", "phi_f": "휨 φf", "phi_v": "전단 φv",
          "tn1": "상부근 1단", "tn2": "상부근 2단", "bn1": "하부근 1단", "bn2": "하부근 2단", "sn": "측면철근",
          "vl": "스터럽 다리", "vs": "스터럽 간격", "mn": "Mu(-)", "mp": "Mu(+)", "vu": "Vu", "tu": "Tu"}
# 입력 표: (행 이름, [(key, 종류, 폭)])  종류: n 숫자칸, bar 주근, stb 스터럽
GRID = [
    ("상부근 1단 · 2단", [("tn1", "n", 3), ("tn2", "n", 3)]),
    ("상부근 직경", [("tb", "bar", 5)]),
    ("하부근 1단 · 2단", [("bn1", "n", 3), ("bn2", "n", 3)]),
    ("하부근 직경", [("bb", "bar", 5)]),
    ("측면철근 (한쪽)", [("sn", "n", 3), ("sb", "bar", 5)]),
    ("스터럽 다리 · 직경", [("vl", "n", 3), ("vb", "stb", 5)]),
    ("스터럽 간격 (0=자동)", [("vs", "n", 5)]),
    ("Mu(-) (상부인장) kN·m", [("mn", "n", 7)]),
    ("Mu(+) (하부인장) kN·m", [("mp", "n", 7)]),
    ("Vu  kN", [("vu", "n", 7)]),
    ("Tu  kN·m", [("tu", "n", 7)]),
]


def _num(vals, key, label=None):
    s = str(vals.get(key, "")).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        raise B.BeamInputError(f"'{label or LABELS.get(key, key)}' 값이 숫자가 아닙니다: \"{s}\"") from None


def _safe(x):
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return 0.0


def n_sections(vals):
    try:
        return max(1, min(3, int(vals.get("n_sec", 1))))
    except (TypeError, ValueError):
        return 1


def inputs_from_values(vals):
    inp = {"name": str(vals.get("name", "")).strip(), "kcr": S.EXPOSURES.get(vals.get("expo"), 210.0)}
    for k in ("b", "h", "cc", "fck", "fy", "fys", "phi_f", "phi_v"):
        inp[k] = _num(vals, k)
    n = n_sections(vals)
    labels = B.SEC_LABELS[n]
    inp["sections"] = []
    for k in range(1, n + 1):
        sec = {}
        for key in SEC_KEYS:
            v = vals.get(f"{k}_{key}", SEC_DEFAULT[key])
            if key in ("tb", "bb", "sb", "vb"):
                sec[key] = v if v in B.BARS else SEC_DEFAULT[key]
            else:
                sec[key] = _num({key: v}, key, f"[{labels[k - 1]}] {LABELS[key]}")
        inp["sections"].append(sec)
    return inp


class BeamLiteWindow(MemberWindow):
    TITLE = "RC Beam"
    BADGE = "Lite"
    SUBTITLE = "직사각형 보 단면 검토 · 단면 1~3개 (전단면 / 단부·중앙부 / 연속단부·중앙부·불연속단부)"
    MODULE = "rc_beam_lite"
    FILE_EXT = ".beam"
    FILE_DESC = "Beam Lite 파일"
    DEFAULT_FILE = "beam_list"
    PRINT_HEADER = "RC BEAM DESIGN"
    FOOTER = "StrCAD  ·  Basic Design  │  RC Beam Lite"
    DEFAULTS = DEFAULTS
    InputError = B.BeamInputError
    INPUT_WIDTH = 470
    WIN_SIZE = "1640x930"

    # ── 입력 패널 ────────────────────────────────────────────
    def build_inputs(self, p):
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

        g = self._group(p, "단면 구성")
        g.pack(fill="x", padx=10, pady=2)
        for n, txt in ((1, "1  전단면"), (2, "2  단부 · 중앙부"), (3, "3  연속단부 · 중앙부 · 불연속단부")):
            tk.Radiobutton(g, text=txt, value=str(n), variable=self.v["n_sec"], indicatoron=False, font=self.f_b,
                           bg="white", fg=T.INK, selectcolor=T.ORANGE, activebackground="#FDE7D0", relief="groove",
                           padx=8, pady=2, cursor="hand2", command=self._on_nsec).pack(side="left", padx=(0, 4))

        self.g_grid = self._group(p, "단면별 철근 · 단면력")
        self.g_grid.pack(fill="x", padx=10, pady=2)

        row = tk.Frame(p, bg=T.SURFACE)
        row.pack(fill="x", padx=10, pady=2)
        g = self._group(row, "강도감소계수 · 균열")
        g.pack(side="left", fill="y")
        self._lbl(g, "φf").grid(row=0, column=0, sticky="e")
        self._ent(g, "phi_f", 5).grid(row=0, column=1, padx=(3, 10))
        self._lbl(g, "φv").grid(row=0, column=2, sticky="e")
        self._ent(g, "phi_v", 5).grid(row=0, column=3, padx=3)
        self._lbl(g, "노출환경 :").grid(row=1, column=0, columnspan=2, sticky="e", pady=(3, 0))
        self._cmb(g, "expo", list(S.EXPOSURES), 19, "readonly").grid(row=1, column=2, columnspan=3, sticky="w", pady=(3, 0))
        for k in ("fck", "fy", "fys", "expo"):
            self.v[k].trace_add("write", lambda *_: self._auto())

    def _auto(self):
        if not self._busy:
            self.win.after_idle(lambda: self.calc(silent=True))

    def _build_grid(self):
        g = self.g_grid
        for w in g.winfo_children():
            w.destroy()
        n = n_sections(self.current_values())
        labels = B.SEC_LABELS[n]
        self._lbl(g, "").grid(row=0, column=0)
        for k in range(1, n + 1):
            hf = tk.Frame(g, bg=T.SURFACE)
            hf.grid(row=0, column=k, padx=3, pady=(0, 3))
            tk.Label(hf, text=f"{k}. {labels[k - 1]}", font=self.f_b, bg=T.NAVY_2, fg="white", padx=6).pack(side="left")
        for r, (lbl, cells) in enumerate(GRID, 1):
            self._lbl(g, lbl, anchor="e").grid(row=r, column=0, sticky="e", pady=1, padx=(0, 4))
            for k in range(1, n + 1):
                cf = tk.Frame(g, bg=T.SURFACE)
                cf.grid(row=r, column=k, sticky="w", padx=3, pady=1)
                for key, kind, wd in cells:
                    var = f"{k}_{key}"
                    if kind == "n":
                        self._ent(cf, var, wd).pack(side="left", padx=(0, 2))
                    else:
                        vals = B.STIRRUP_LIST if kind == "stb" else B.BAR_LIST
                        self._cmb(cf, var, vals, wd, "readonly").pack(side="left", padx=(0, 2))
                        self.v[var].trace_add("write", lambda *_: self._auto())
        if n > 1:
            r = len(GRID) + 1
            self._lbl(g, "철근 복사", fg=T.MUTED, anchor="e").grid(row=r, column=0, sticky="e", pady=(4, 0), padx=(0, 4))
            for k in range(2, n + 1):
                tk.Button(g, text=f"← {k - 1}번 철근", font=(T.FAM, 8), relief="groove", bg="white", cursor="hand2", padx=4,
                          pady=0, command=lambda kk=k: self._copy_from_prev(kk)).grid(row=r, column=k, sticky="w", padx=3,
                                                                                      pady=(4, 0))

    def _copy_from_prev(self, k):
        """앞 단면의 철근(단면력 제외)을 복사"""
        self._busy = True
        try:
            for key in SEC_KEYS:
                if key in ("mn", "mp", "vu", "tu"):
                    continue
                self.v[f"{k}_{key}"].set(self.v[f"{k - 1}_{key}"].get())
        finally:
            self._busy = False
        self.calc(silent=True)

    def _on_nsec(self):
        if self._busy:
            return
        n = n_sections(self.current_values())
        # 새로 생긴 단면은 1번 단면 철근으로 채우고, 단면력은 위치에 맞게 1번 단면 값을 옮긴다
        #   중앙부 → Mu(+),  단부 → Mu(-)  (크기 = 1번 단면의 큰 휨모멘트)
        old = getattr(self, "_shown_n", n)
        if n > old:
            labels = B.SEC_LABELS[n]
            v = self.v
            m1 = max(_safe(v["1_mn"].get()), _safe(v["1_mp"].get()))
            self._busy = True
            try:
                for k in range(old + 1, n + 1):
                    for key in SEC_KEYS:
                        if key not in ("mn", "mp", "vu", "tu"):
                            v[f"{k}_{key}"].set(v[f"1_{key}"].get())
                    mid = labels[k - 1] == "중앙부"
                    v[f"{k}_mn"].set("0" if mid else f"{m1:g}")
                    v[f"{k}_mp"].set(f"{m1:g}" if mid else "0")
                    v[f"{k}_vu"].set(v["1_vu"].get())
                    v[f"{k}_tu"].set(v["1_tu"].get())
                if old == 1 and _safe(v["1_mn"].get()) == 0:     # 전단면 → 단부: 정모멘트를 부모멘트로
                    v["1_mn"].set(v["1_mp"].get())
                    v["1_mp"].set("0")
            finally:
                self._busy = False
        self._shown_n = n
        self._build_grid()
        self.calc(silent=True)

    def after_load(self):
        self._shown_n = n_sections(self.current_values())
        self._build_grid()
        self.calc(silent=True)

    # ── 계산 ─────────────────────────────────────────────────
    def kind_text(self, vals):
        return f"{n_sections(vals)}단면"

    def compute(self, vals):
        res = B.calc_beam(inputs_from_values(vals))
        nm = res["name"] or "(이름 없음)"
        bad = [s["label"] for s in res["sections"] if not s["ok"]]
        status = (f"{nm}  ·  {res['b']:g} × {res['h']:g} mm  ·  단면 {len(res['sections'])}개  ─  "
                  + ("설계 결과 O.K." if not bad else f"N.G. : {', '.join(bad)} — 계산서의 빨간 항목을 확인하세요."))
        return {"report": B.build_report(res), "sketch": B.sketch(res), "box": B.sketch_box(res), "ok": res["ok"],
                "status": status, "res": res}


def open_beam_lite(parent, username=""):
    return BeamLiteWindow(parent, username=username)
