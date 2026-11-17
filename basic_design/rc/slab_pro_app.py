"""
basic_design/rc/slab_pro_app.py
RC Slab — Pro : 유한요소 해석 슬래브 설계 창
  · Type: 사각형(4변 지지 입력) / 다각형(꼭짓점 좌표 + 변마다 지지 조건)
  · 등분포 + 집중/라인/면 하중, 개구부, 집중하중 뚫림전단(재하면적 입력 시)
  · 계산서: 휨 배근표 · 전단 · 뚫림전단 · 처짐 · 보 부재력 (표 먼저)
  · FEM 결과 보기: Mxx / Myy / Mxy / Vxx / Vyy / 처짐 버튼 → 2D 등고선 · 3D 형상 창
  (부재 목록 · 저장 · A4 출력은 공통 틀 member_app.MemberWindow)
"""
import json
import tkinter as tk
from tkinter import ttk, messagebox

from .. import theme as T
from ..member_app import MemberWindow
from . import slab_calc as S
from . import slab_fem as FEM
from . import slab_pro as P
from .slab_pro_view import ResultViewer

SHAPE_RECT, SHAPE_POLY = "사각형", "다각형"
EDGE_DISP = {v[0]: k for k, v in FEM.EDGE_TYPES.items()}          # 표시 → key
EDGE_NAMES = [v[0] for v in FEM.EDGE_TYPES.values()]
DEFAULT_POLY = [{"x": x, "y": y, "fix": True, "kind": "beam_c", "b": 400, "h": 600}
                for x, y in ((0, 0), (6, 0), (6, 3), (3, 3), (3, 6), (0, 6))]            # ㄱ자

DEFAULTS = {
    "name": "PS1", "shape": SHAPE_RECT, "lx": "4", "ly": "6", "t": "150", "cc": "20",
    "fck": "24", "fy13": "400", "fy16": "500", "wd": "5", "wl": "3", "bar": "D10",
    "phi_f": "0.85", "phi_v": "0.75", "mesh": "16", "wa": "1",
    "months": "60", "lim_live": "360", "lim_long": "480", "sus_live": "50",
    "c_lt": "1", "c_lb": "1", "c_rt": "1", "c_rb": "1", "loads": "[]",
    "poly": json.dumps(DEFAULT_POLY),
}
for _e in FEM.EDGE_KEYS:
    DEFAULTS[f"e_{_e}"] = FEM.EDGE_TYPES["beam_c"][0]
    DEFAULTS[f"b_{_e}"] = "400"
    DEFAULTS[f"h_{_e}"] = "600"
LABELS = {"lx": "Lx", "ly": "Ly", "t": "두께 T", "cc": "피복 Cc", "fck": "fck", "fy13": "fy(D13↓)", "fy16": "fy(D16↑)",
          "wd": "고정하중 Wd", "wl": "활하중 Wl", "phi_f": "휨 φf", "phi_v": "전단 φv", "months": "재하기간",
          "lim_live": "활하중 처짐제한", "lim_long": "장기처짐제한", "sus_live": "지속 활하중 비율", "mesh": "요소 분할"}
for _e in FEM.EDGE_KEYS:
    LABELS[f"b_{_e}"] = f"{P.EDGE_LABEL[_e]} 보 폭"
    LABELS[f"h_{_e}"] = f"{P.EDGE_LABEL[_e]} 보 춤"


def _num(vals, key):
    s = str(vals.get(key, "")).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        raise P.ProInputError(f"'{LABELS.get(key, key)}' 값이 숫자가 아닙니다: \"{s}\"") from None


def parse_loads(text):
    try:
        data = json.loads(text or "[]")
        return [dict(ld) for ld in data if isinstance(ld, dict) and ld.get("type") in ("P", "L", "A", "O")]
    except (ValueError, TypeError):
        return []


def parse_poly(text):
    """꼭짓점 목록 [{x, y, fix, kind, b, h}]"""
    try:
        out = []
        for v in json.loads(text or "[]"):
            kind = v.get("kind", "beam_c")
            out.append({"x": float(v["x"]), "y": float(v["y"]), "fix": bool(v.get("fix", True)),
                        "kind": kind if kind in FEM.EDGE_TYPES else "beam_c",
                        "b": float(v.get("b", 400)), "h": float(v.get("h", 600))})
        return out
    except (ValueError, TypeError, KeyError, AttributeError):
        return []


def inputs_from_values(vals):
    inp = {"name": str(vals.get("name", "")).strip(), "bar": str(vals.get("bar", "")).strip() or "D10"}
    for k in ("t", "cc", "fck", "fy13", "fy16", "wd", "wl", "phi_f", "phi_v"):
        inp[k] = _num(vals, k)
    if vals.get("shape") == SHAPE_POLY:
        inp["shape"] = "poly"
        inp["verts"] = []
        for i, v in enumerate(parse_poly(vals.get("poly", "[]")), 1):
            beam = FEM.EDGE_TYPES[v["kind"]][1]
            if beam and (v["b"] <= 0 or v["h"] <= inp["t"]):
                raise P.ProInputError(f"변 {i} 지지보 치수를 확인하세요 (폭 > 0, 춤 > 슬래브 두께).")
            inp["verts"].append({"x": v["x"], "y": v["y"], "fix": v["fix"], "kind": v["kind"],
                                 "bw": v["b"] if beam else 0.0, "bh": v["h"] if beam else 0.0})
    else:
        inp["shape"] = "rect"
        inp["lx"], inp["ly"] = _num(vals, "lx"), _num(vals, "ly")
        inp["edges"] = {}
        for e in FEM.EDGE_KEYS:
            kind = EDGE_DISP.get(vals.get(f"e_{e}"), "beam_c")
            bw, bh = (_num(vals, f"b_{e}"), _num(vals, f"h_{e}")) if FEM.EDGE_TYPES[kind][1] else (0.0, 0.0)
            if FEM.EDGE_TYPES[kind][1] and (bw <= 0 or bh <= inp["t"]):
                raise P.ProInputError(f"{P.EDGE_LABEL[e]} 지지보 치수를 확인하세요 (폭 > 0, 춤 > 슬래브 두께).")
            inp["edges"][e] = (kind, bw, bh)
        inp["corners"] = {k: str(vals.get(f"c_{k}", "1")) == "1" for k, _, _, _ in P.CORNERS}
    inp["loads"] = parse_loads(vals.get("loads", "[]"))
    inp["mesh"] = int(_num(vals, "mesh"))
    inp["wood_armer"] = str(vals.get("wa", "1")) == "1"
    m = _num(vals, "months")
    if not 1 <= m <= 60:
        raise P.ProInputError("재하기간은 1 ~ 60 개월로 입력하세요.")
    ll, lg = _num(vals, "lim_live"), _num(vals, "lim_long")
    if not (1 <= ll <= 360 and 1 <= lg <= 480):
        raise P.ProInputError("처짐제한은 활하중 L/1 ~ L/360, 장기 L/1 ~ L/480 범위로 입력하세요.")
    sl = _num(vals, "sus_live")
    if not 0 <= sl <= 100:
        raise P.ProInputError("지속 활하중 비율은 0 ~ 100 % 로 입력하세요.")
    inp.update(months=m, lim_live=ll, lim_long=lg, sus_live=sl / 100.0)
    return inp


# ── 입력 창 (하중 · 개구부 · 꼭짓점) ─────────────────────────
class _Dialog(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.result = None
        self.title(title)
        self.configure(bg=T.SURFACE)
        self.resizable(False, False)
        self.transient(parent)
        self.f_n = (T.FAM, 9)
        self.frm = tk.Frame(self, bg=T.SURFACE)
        self.frm.pack(padx=16, pady=12)
        self.e = {}
        self._row = 0
        self.err = tk.Label(self, text="", font=(T.FAM, 8), bg=T.SURFACE, fg=T.NG)
        bf = tk.Frame(self, bg=T.SURFACE)
        bf.pack(side="bottom", fill="x", padx=16, pady=(0, 12))
        tk.Button(bf, text="확인", width=8, font=self.f_n, bg=T.ORANGE, fg="white", relief="flat", command=self._ok).pack(side="right")
        tk.Button(bf, text="취소", width=8, font=self.f_n, relief="groove", bg="white", command=self.destroy).pack(side="right", padx=6)
        self.err.pack(side="bottom", anchor="w", padx=16)
        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self.destroy())

    def note(self, text):
        tk.Label(self.frm, text=text, font=(T.FAM, 8), bg=T.SURFACE, fg=T.MUTED, justify="left").grid(
            row=self._row, column=0, columnspan=3, sticky="w", pady=(2, 4))
        self._row += 1

    def field(self, key, label, value):
        tk.Label(self.frm, text=label + " :", font=self.f_n, bg=T.SURFACE, fg=T.INK).grid(row=self._row, column=0, sticky="e", pady=2)
        en = tk.Entry(self.frm, width=10, font=self.f_n, fg=T.INPUT_FG, relief="solid", bd=1)
        en.insert(0, f"{value:g}")
        en.grid(row=self._row, column=1, padx=6, pady=2, sticky="w")
        self.e[key] = en
        self._row += 1
        return en

    def place(self, parent):
        self.update_idletasks()
        self.geometry(f"+{parent.winfo_rootx() + 260}+{parent.winfo_rooty() + 200}")
        try:
            self.grab_set()
        except tk.TclError:
            pass
        if self.e:
            list(self.e.values())[0].focus_set()

    def numbers(self):
        out = {}
        for k, en in self.e.items():
            out[k] = float(en.get().strip().replace(",", ""))
        return out

    def _ok(self):
        raise NotImplementedError


LOAD_KINDS = {"P": ("집중하중", [("x", "x (m)"), ("y", "y (m)")], "kN"),
              "L": ("라인하중", [("x1", "x1 (m)"), ("y1", "y1 (m)"), ("x2", "x2 (m)"), ("y2", "y2 (m)")], "kN/m"),
              "A": ("면하중 (사각형)", [("x1", "x1 (m)"), ("y1", "y1 (m)"), ("x2", "x2 (m)"), ("y2", "y2 (m)")], "kN/m²"),
              "O": ("개구부 (사각형)", [("x1", "x1 (m)"), ("y1", "y1 (m)"), ("x2", "x2 (m)"), ("y2", "y2 (m)")], "")}


class LoadDialog(_Dialog):
    """집중·라인·면 하중 / 개구부 입력.  box = (x0, y0, x1, y1) 슬래브 외곽 범위"""

    def __init__(self, parent, kind, box, load=None):
        title, coords, unit = LOAD_KINDS[kind]
        super().__init__(parent, title + (" 수정" if load else " 추가"))
        self.kind, self.box = kind, box
        x0, y0, x1, y1 = box
        self.note(f"슬래브 범위  x: {x0:g} ~ {x1:g} m,  y: {y0:g} ~ {y1:g} m")
        cx, cy, wx, wy = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0
        dflt = load or ({"x": cx, "y": cy} if kind == "P" else
                        {"x1": x0 + wx / 4, "y1": cy, "x2": x1 - wx / 4, "y2": cy} if kind == "L" else
                        {"x1": x0 + wx / 4, "y1": y0 + wy / 4, "x2": x1 - wx / 4, "y2": y1 - wy / 4} if kind == "A" else
                        {"x1": cx - wx / 10, "y1": cy - wy / 10, "x2": cx + wx / 10, "y2": cy + wy / 10})
        for k, lbl in coords:
            self.field(k, lbl, dflt.get(k, 0))
        if kind != "O":
            self.field("d", f"고정 D ({unit})", dflt.get("d", 0))
            self.field("l", f"활 L ({unit})", dflt.get("l", 0))
        if kind == "P":
            self.note("뚫림전단 재하면적 (0 이면 뚫림전단 검토 안 함)")
            self.field("c1", "c1 — x 방향 (mm)", dflt.get("c1", 0))
            self.field("c2", "c2 — y 방향 (mm)", dflt.get("c2", 0))
        if kind == "O":
            self.note("개구부 둘레는 자유단으로 해석합니다.")
        self.place(parent)

    def _ok(self):
        try:
            out = {"type": self.kind, **self.numbers()}
        except ValueError:
            self.err.config(text="숫자를 입력하세요.")
            return
        x0, y0, x1, y1 = self.box
        xs = [out[k] for k in out if k.startswith("x")]
        ys = [out[k] for k in out if k.startswith("y")]
        if not all(x0 - 1e-9 <= x <= x1 + 1e-9 for x in xs) or not all(y0 - 1e-9 <= y <= y1 + 1e-9 for y in ys):
            self.err.config(text="위치가 슬래브 범위를 벗어났습니다.")
            return
        if self.kind == "L" and out["x1"] == out["x2"] and out["y1"] == out["y2"]:
            self.err.config(text="시작점과 끝점이 같습니다.")
            return
        if self.kind in ("A", "O") and (out["x1"] == out["x2"] or out["y1"] == out["y2"]):
            self.err.config(text="면적이 0 입니다.")
            return
        if self.kind != "O" and out["d"] == 0 and out["l"] == 0:
            self.err.config(text="하중 크기를 입력하세요.")
            return
        if self.kind == "P" and (out["c1"] < 0 or out["c2"] < 0 or (out["c1"] > 0) != (out["c2"] > 0)):
            self.err.config(text="재하면적 c1, c2 는 둘 다 입력하거나 둘 다 0 으로 두세요.")
            return
        self.result = out
        self.destroy()


class VertexDialog(_Dialog):
    """다각형 꼭짓점 + (이 점 → 다음 점) 변의 지지 조건"""

    def __init__(self, parent, no, vert, is_new):
        super().__init__(parent, f"꼭짓점 {no} " + ("추가" if is_new else "수정"))
        self.field("x", "x (m)", vert["x"])
        self.field("y", "y (m)", vert["y"])
        self.fix = tk.BooleanVar(self, value=vert["fix"])
        tk.Checkbutton(self.frm, text="이 꼭짓점에 수직 지지 (기둥)", variable=self.fix, font=self.f_n, bg=T.SURFACE).grid(
            row=self._row, column=0, columnspan=3, sticky="w", pady=(2, 6))
        self._row += 1
        self.note(f"변 {no}  (이 점 → 다음 점) 의 지지")
        tk.Label(self.frm, text="지지 :", font=self.f_n, bg=T.SURFACE, fg=T.INK).grid(row=self._row, column=0, sticky="e")
        self.kind = tk.StringVar(self, value=FEM.EDGE_TYPES[vert["kind"]][0])
        ttk.Combobox(self.frm, textvariable=self.kind, values=EDGE_NAMES, width=13, state="readonly", font=self.f_n).grid(
            row=self._row, column=1, padx=6, pady=2, sticky="w")
        self._row += 1
        self.field("b", "보 폭 b (mm)", vert["b"])
        self.field("h", "보 춤 h (mm)", vert["h"])
        self.place(parent)

    def _ok(self):
        try:
            n = self.numbers()
        except ValueError:
            self.err.config(text="숫자를 입력하세요.")
            return
        self.result = {"x": n["x"], "y": n["y"], "fix": bool(self.fix.get()), "kind": EDGE_DISP[self.kind.get()],
                       "b": n["b"], "h": n["h"]}
        self.destroy()


class SlabProWindow(MemberWindow):
    TITLE = "RC Slab"
    BADGE = "Pro"
    SUBTITLE = "유한요소 해석 · 사각형/다각형 · 집중/라인/면 하중 · 개구부"
    MODULE = "rc_slab_pro"
    FILE_EXT = ".slabp"
    FILE_DESC = "Slab Pro 파일"
    DEFAULT_FILE = "slab_pro"
    PRINT_HEADER = "RC SLAB DESIGN (FEM)"
    FOOTER = "StrCAD  ·  Basic Design  │  RC Slab Pro"
    DEFAULTS = DEFAULTS
    InputError = P.ProInputError
    INPUT_WIDTH = 436
    WIN_SIZE = "1620x960"

    # ── 입력 패널 ────────────────────────────────────────────
    def build_inputs(self, p):
        self.viewer = None
        f = self.top_fields
        self._lbl(f, "Type :").grid(row=1, column=0, sticky="e", pady=2)
        self._cmb(f, "shape", [SHAPE_RECT, SHAPE_POLY], 13, "readonly").grid(row=1, column=1, sticky="w", padx=4)

        row = tk.Frame(p, bg=T.SURFACE)
        row.pack(fill="x", padx=10, pady=2)
        self.g_dim = self._group(row, "슬래브 치수")
        self.g_dim.pack(side="left", fill="y")
        g = self._group(row, "재료강도 · 등분포 하중")
        g.pack(side="left", fill="y", padx=(8, 0))
        self._field(g, 0, "fck :", "fck", "N/mm²", widget=self._cmb(g, "fck", ["21", "24", "27", "30", "35", "40"], 5))
        self._field(g, 1, "fy(D13↓) :", "fy13", "N/mm²", widget=self._cmb(g, "fy13", ["300", "400", "500", "600"], 5))
        self._field(g, 2, "fy(D16↑) :", "fy16", "N/mm²", widget=self._cmb(g, "fy16", ["300", "400", "500", "600"], 5))
        self._field(g, 3, "Wd :", "wd", "kN/m²", width=6)
        self._field(g, 4, "Wl :", "wl", "kN/m²", width=6)

        self.f_geo = tk.Frame(p, bg=T.SURFACE)          # Type 에 따라 바뀌는 부분 (지지 조건)
        self.f_geo.pack(fill="x")

        g = self._group(p, "추가 하중 · 개구부  (단위 m)")
        g.pack(fill="x", padx=10, pady=2)
        st = ttk.Style(self.win)
        st.configure("BDL.Treeview", font=(T.FAM, 8), rowheight=18)
        st.configure("BDL.Treeview.Heading", font=(T.FAM, 8))
        self.ltree = lt = ttk.Treeview(g, columns=("no", "kind", "pos", "d", "l"), show="headings", height=4,
                                       selectmode="browse", style="BDL.Treeview")
        for cid, txt, w_, anc in (("no", "No", 28, "center"), ("kind", "종류", 48, "center"), ("pos", "위치", 196, "w"),
                                  ("d", "D", 48, "e"), ("l", "L", 48, "e")):
            lt.heading(cid, text=txt)
            lt.column(cid, width=w_, minwidth=w_, anchor=anc, stretch=(cid == "pos"))
        lt.pack(fill="x")
        lt.bind("<Double-1>", lambda _: self._load_edit())
        bf = tk.Frame(g, bg=T.SURFACE)
        bf.pack(fill="x", pady=(4, 0))
        for txt, cmd in (("+ 집중", lambda: self._load_add("P")), ("+ 라인", lambda: self._load_add("L")),
                         ("+ 면", lambda: self._load_add("A")), ("+ 개구부", lambda: self._load_add("O")),
                         ("수정", self._load_edit), ("삭제", self._load_del)):
            tk.Button(bf, text=txt, font=(T.FAM, 8), bg="white", relief="groove", cursor="hand2", padx=5, pady=0,
                      command=cmd).pack(side="left", padx=(0, 4))

        g = self._group(p, "해석 · 처짐 설정")
        g.pack(fill="x", padx=10, pady=2)
        f = tk.Frame(g, bg=T.SURFACE)
        f.pack(fill="x")
        self._lbl(f, "요소 분할(단변) :").pack(side="left")
        self._cmb(f, "mesh", ["12", "16", "20", "24"], 4, "readonly").pack(side="left", padx=4)
        tk.Checkbutton(f, text="Wood–Armer (Mxy 반영)", variable=self.v["wa"], onvalue="1", offvalue="0", font=self.f_n,
                       bg=T.SURFACE, command=lambda: self.calc(silent=True)).pack(side="left", padx=8)
        f = tk.Frame(g, bg=T.SURFACE)
        f.pack(fill="x", pady=(3, 0))
        self._lbl(f, "재하기간").pack(side="left")
        self._ent(f, "months", 4).pack(side="left", padx=(3, 2))
        self._lbl(f, "개월   활하중 L/").pack(side="left")
        self._ent(f, "lim_live", 4).pack(side="left", padx=2)
        self._lbl(f, "  장기 L/").pack(side="left")
        self._ent(f, "lim_long", 4).pack(side="left", padx=2)
        self._lbl(f, "  지속 L").pack(side="left")
        self._ent(f, "sus_live", 4).pack(side="left", padx=2)
        self._lbl(f, "%").pack(side="left")

        g = self._group(p, "FEM 결과 보기  (클릭 → 등고선 / 3D)")
        g.pack(fill="x", padx=10, pady=2)
        f = tk.Frame(g, bg=T.SURFACE)
        f.pack(fill="x")
        for key, lbl, _, _ in P.FIELDS:
            tk.Button(f, text=lbl, font=(T.FAM, 8, "bold"), bg=T.NAVY_2, fg="white", relief="flat", cursor="hand2",
                      activebackground=T.ORANGE, activeforeground="white", padx=5, pady=2,
                      command=lambda k=key: self.open_viewer(k, None)).pack(side="left", padx=(0, 3))
        tk.Button(f, text="3D", font=(T.FAM, 8, "bold"), bg=T.ORANGE_D, fg="white", relief="flat", cursor="hand2", padx=8,
                  pady=2, command=lambda: self.open_viewer(None, "3d")).pack(side="left", padx=(3, 0))
        for k in [f"e_{e}" for e in FEM.EDGE_KEYS] + ["bar", "mesh"]:
            self.v[k].trace_add("write", lambda *_: self._auto())
        self.v["shape"].trace_add("write", lambda *_: self._on_shape())

    def _auto(self):
        if not self._busy:
            self.win.after_idle(lambda: self.calc(silent=True))

    def _on_shape(self):
        if not self._busy:
            self._build_geo()
            self.calc(silent=True)

    def _is_poly(self):
        return self.v["shape"].get() == SHAPE_POLY

    def _build_geo(self):
        """Type(사각형/다각형)에 따라 치수·지지 입력을 다시 만든다"""
        for fr in (self.g_dim, self.f_geo):
            for w in fr.winfo_children():
                w.destroy()
        g = self.g_dim
        r = 0
        if not self._is_poly():
            self._field(g, 0, "Lx :", "lx", "m", width=6)
            self._field(g, 1, "Ly :", "ly", "m", width=6)
            r = 2
        self._field(g, r, "T :", "t", "mm", width=6)
        self._field(g, r + 1, "Cc :", "cc", "mm", width=6)
        if self._is_poly():
            self._lbl(g, "형상은 아래\n꼭짓점 표로 입력", fg=T.MUTED, justify="left").grid(row=r + 2, column=0, columnspan=3,
                                                                                 sticky="w", pady=(4, 0))
        p = self.f_geo
        row = tk.Frame(p, bg=T.SURFACE)
        if self._is_poly():
            g = self._group(p, "다각형 꼭짓점 · 변 지지  (변 n = 점 n → 다음 점)")
            g.pack(fill="x", padx=10, pady=2)
            self.vtree = vt = ttk.Treeview(g, columns=("no", "x", "y", "fix", "kind", "bh"), show="headings", height=6,
                                           selectmode="browse", style="BDL.Treeview")
            for cid, txt, w_, anc in (("no", "No", 28, "center"), ("x", "x (m)", 52, "e"), ("y", "y (m)", 52, "e"),
                                      ("fix", "지지", 36, "center"), ("kind", "변 지지", 96, "center"),
                                      ("bh", "보 b×h", 80, "center")):
                vt.heading(cid, text=txt)
                vt.column(cid, width=w_, minwidth=w_, anchor=anc, stretch=(cid == "kind"))
            vt.pack(fill="x")
            vt.bind("<Double-1>", lambda _: self._vert_edit())
            bf = tk.Frame(g, bg=T.SURFACE)
            bf.pack(fill="x", pady=(4, 0))
            for txt, cmd in (("+ 점 추가", self._vert_add), ("수정", self._vert_edit), ("삭제", self._vert_del),
                             ("▲", lambda: self._vert_move(-1)), ("▼", lambda: self._vert_move(1))):
                tk.Button(bf, text=txt, font=(T.FAM, 8), bg="white", relief="groove", cursor="hand2", padx=5, pady=0,
                          command=cmd).pack(side="left", padx=(0, 4))
            self._lbl(bf, "더블클릭 = 수정", fg=T.MUTED).pack(side="left", padx=4)
            self._fill_verts()
        else:
            g = self._group(p, "슬래브 연단 지지 · 지지보 (b × h mm)")
            g.pack(fill="x", padx=10, pady=2)
            for i, e in enumerate(FEM.EDGE_KEYS):
                self._lbl(g, P.EDGE_LABEL[e] + " :").grid(row=i, column=0, sticky="e", pady=1)
                self._cmb(g, f"e_{e}", EDGE_NAMES, 12, "readonly").grid(row=i, column=1, padx=(4, 8))
                self._ent(g, f"b_{e}", 5).grid(row=i, column=2)
                self._lbl(g, "×").grid(row=i, column=3, padx=2)
                self._ent(g, f"h_{e}", 5).grid(row=i, column=4)
                if i:
                    tk.Button(g, text="↑", font=(T.FAM, 7), width=2, relief="groove", bg="white", cursor="hand2",
                              command=lambda k=i: self._copy_edge(k)).grid(row=i, column=5, padx=4)
            g = self._group(row, "모서리 수직 지지")
            g.pack(side="left", fill="y", padx=(0, 8))
            for n, (k, lbl, _, _) in enumerate(P.CORNERS):
                tk.Checkbutton(g, text=lbl, variable=self.v[f"c_{k}"], onvalue="1", offvalue="0", font=self.f_n,
                               bg=T.SURFACE, command=lambda: self.calc(silent=True)).grid(row=n // 2, column=n % 2, sticky="w")
        row.pack(fill="x", padx=10, pady=2)
        g = self._group(row, "사용 철근 · 강도감소계수")
        g.pack(side="left", fill="y")
        self._lbl(g, "철근 :").grid(row=0, column=0, sticky="e")
        self._cmb(g, "bar", S.BAR_ORDER, 5, "readonly").grid(row=0, column=1, padx=4, sticky="w")
        f = tk.Frame(g, bg=T.SURFACE)
        f.grid(row=0 if self._is_poly() else 1, column=2 if self._is_poly() else 0, columnspan=3, sticky="w",
               pady=(0 if self._is_poly() else 3, 0), padx=(10 if self._is_poly() else 0, 0))
        self._lbl(f, "φf").pack(side="left")
        self._ent(f, "phi_f", 5).pack(side="left", padx=(3, 8))
        self._lbl(f, "φv").pack(side="left")
        self._ent(f, "phi_v", 5).pack(side="left", padx=3)

    def _copy_edge(self, i):
        a, b = FEM.EDGE_KEYS[i - 1], FEM.EDGE_KEYS[i]
        self._busy = True
        try:
            for pre in ("e_", "b_", "h_"):
                self.v[pre + b].set(self.v[pre + a].get())
        finally:
            self._busy = False
        self.calc(silent=True)

    # ── 다각형 꼭짓점 ────────────────────────────────────────
    def _verts(self):
        return parse_poly(self.v["poly"].get())

    def _set_verts(self, verts, select=None):
        self.v["poly"].set(json.dumps(verts, ensure_ascii=False))
        self._fill_verts(select)
        self.calc(silent=True)

    def _fill_verts(self, select=None):
        vt = getattr(self, "vtree", None)
        if vt is None or not vt.winfo_exists():
            return
        vt.delete(*vt.get_children())
        for n, v in enumerate(self._verts(), 1):
            beam = FEM.EDGE_TYPES[v["kind"]][1]
            vt.insert("", "end", iid=str(n - 1), values=(n, f"{v['x']:g}", f"{v['y']:g}", "●" if v["fix"] else "–",
                                                         FEM.EDGE_TYPES[v["kind"]][0],
                                                         f"{v['b']:g}×{v['h']:g}" if beam else "-"))
        if select is not None and vt.exists(str(select)):
            vt.selection_set(str(select))

    def _vsel(self):
        sel = self.vtree.selection()
        return int(sel[0]) if sel else None

    def _vert_add(self):
        verts = self._verts()
        i = self._vsel()
        i = len(verts) - 1 if i is None else i
        base = dict(verts[i]) if verts else dict(DEFAULT_POLY[0])
        if len(verts) >= 2:                               # 선택한 점과 다음 점의 중간을 기본값으로
            nxt = verts[(i + 1) % len(verts)]
            base["x"], base["y"] = round((base["x"] + nxt["x"]) / 2, 3), round((base["y"] + nxt["y"]) / 2, 3)
        dlg = VertexDialog(self.win, i + 2, base, True)
        self.win.wait_window(dlg)
        if dlg.result:
            verts.insert(i + 1, dlg.result)
            self._set_verts(verts, i + 1)

    def _vert_edit(self):
        i = self._vsel()
        if i is None:
            return
        verts = self._verts()
        dlg = VertexDialog(self.win, i + 1, verts[i], False)
        self.win.wait_window(dlg)
        if dlg.result:
            verts[i] = dlg.result
            self._set_verts(verts, i)

    def _vert_del(self):
        i = self._vsel()
        verts = self._verts()
        if i is None:
            return
        if len(verts) <= 3:
            messagebox.showinfo("꼭짓점", "꼭짓점은 3개 이상 있어야 합니다.", parent=self.win)
            return
        verts.pop(i)
        self._set_verts(verts, min(i, len(verts) - 1))

    def _vert_move(self, step):
        i = self._vsel()
        verts = self._verts()
        if i is None or not 0 <= i + step < len(verts):
            return
        verts[i], verts[i + step] = verts[i + step], verts[i]
        self._set_verts(verts, i + step)

    # ── 추가 하중 · 개구부 ───────────────────────────────────
    def _loads(self):
        return parse_loads(self.v["loads"].get())

    def _set_loads(self, loads):
        self.v["loads"].set(json.dumps(loads, ensure_ascii=False))
        self._fill_loads()
        self.calc(silent=True)

    def _fill_loads(self):
        lt = self.ltree
        lt.delete(*lt.get_children())
        for n, ld in enumerate(self._loads(), 1):
            kind, pos, _ = P._load_text(ld)
            is_op = ld["type"] == "O"
            lt.insert("", "end", iid=str(n - 1), values=(n, kind, pos, "-" if is_op else f"{ld.get('d', 0):g}",
                                                         "-" if is_op else f"{ld.get('l', 0):g}"))

    def _box(self):
        """슬래브 외곽 범위 (x0, y0, x1, y1)"""
        try:
            if self._is_poly():
                vs = self._verts()
                if len(vs) < 3:
                    raise ValueError
                return (min(v["x"] for v in vs), min(v["y"] for v in vs), max(v["x"] for v in vs), max(v["y"] for v in vs))
            return 0.0, 0.0, float(self.v["lx"].get()), float(self.v["ly"].get())
        except ValueError:
            messagebox.showwarning("입력 확인", "슬래브 형상(치수 또는 꼭짓점)을 먼저 입력하세요.", parent=self.win)
            return None

    def _load_add(self, kind):
        box = self._box()
        if not box:
            return
        dlg = LoadDialog(self.win, kind, box)
        self.win.wait_window(dlg)
        if dlg.result:
            self._set_loads(self._loads() + [dlg.result])

    def _load_edit(self):
        sel = self.ltree.selection()
        box = self._box()
        if not sel or not box:
            return
        loads = self._loads()
        i = int(sel[0])
        dlg = LoadDialog(self.win, loads[i]["type"], box, load=loads[i])
        self.win.wait_window(dlg)
        if dlg.result:
            loads[i] = dlg.result
            self._set_loads(loads)

    def _load_del(self):
        sel = self.ltree.selection()
        if not sel:
            return
        loads = self._loads()
        loads.pop(int(sel[0]))
        self._set_loads(loads)

    # ── 결과 보기 ────────────────────────────────────────────
    def open_viewer(self, field=None, mode=None):
        res = self.calc()
        if res is None:
            return
        title = f"StrCAD - RC Slab Pro │ FEM 결과  ─  {res['name']}"
        if self.viewer is None or not self.viewer.alive():
            self.viewer = ResultViewer(self.win, res, field or "mx", mode or "2d", title)
        else:
            self.viewer.win.title(title)
            self.viewer.show(res, field, mode)

    def on_result(self, res):
        v = getattr(self, "viewer", None)
        if v is not None and v.alive() and res is not None:
            v.win.title(f"StrCAD - RC Slab Pro │ FEM 결과  ─  {res['name']}")
            v.set_result(res)

    def after_load(self):
        self._build_geo()
        self._fill_loads()
        self.calc(silent=True)

    # ── 계산 ─────────────────────────────────────────────────
    def kind_text(self, vals):
        return "다각" if vals.get("shape") == SHAPE_POLY else "사각"

    def normalize_values(self, vals):
        merged = super().normalize_values(vals)
        if merged["shape"] not in (SHAPE_RECT, SHAPE_POLY):
            merged["shape"] = SHAPE_RECT
        return merged

    def _out(self, vals, figures):
        res = P.calc_pro(inputs_from_values(vals))
        nm = res["name"] or "(이름 없음)"
        geo = (f"다각형 {len(res['verts'])}점 ({res['area']:.1f} m²)" if res["shape"] == "poly"
               else f"{res['lx']:g} × {res['ly']:g} m")
        status = (f"{nm}  ·  {geo},  T = {res['t']:g} mm  ·  요소 {res['n_elem']}개  ─  "
                  + ("설계 결과 O.K." if res["ok"] else "N.G. 항목이 있습니다 — 계산서의 빨간 항목을 확인하세요."))
        return {"report": P.build_report(res, figures=figures), "sketch": P.sketch(res), "box": P.SKETCH_BOX,
                "ok": res["ok"], "status": status, "res": res}

    def compute(self, vals):
        return self._out(vals, False)

    def compute_print(self, vals):
        return self._out(vals, True)             # 출력에는 등고선 그림 포함


def open_slab_pro(parent, username=""):
    return SlabProWindow(parent, username=username)
