"""
design_2d/plan/panel.py — 평면해석 메인 화면
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 1) 노드 · 선 · 면을 그린다 (면: 닫힌 영역 클릭 또는 노드 순서 클릭)
 2) 선 → 보, 면 → 슬래브, 노드/선 → 지점 으로 '적용'
    (입력 탭, 우클릭 메뉴, 트리 항목 드래그)
 3) 하중: 노드(집중) · 선(선하중) · 면(면하중) — 부재로 적용하지 않은 곳도 가능
 4) ▶ 해석 → 슬래브 Mx·My·Qx·Qy·처짐 컨투어, 보 M·V, 반력
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import copy
import math
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from . import model as pm
from .mesh import find_face
from .solver import analyze, PlanError
from ..section.theme import *
from .draw import DrawMixin
from .tree_tab import TreeTabMixin
from .input_tab import InputTabMixin
from .load_tab import LoadTabMixin
from .result_tab import ResultTabMixin
from .dialogs import GridGenDialog

UNDO_MAX = 80
SNAP_PX = 12
HIT_PX = 7

MODE_HINT = {
    "select": "선택: 클릭(Shift=추가) · 빈 곳 드래그=영역선택 · 우클릭=메뉴 · 휠=확대 · 가운데/우 드래그=이동",
    "node": "노드: 클릭한 위치(격자 스냅)에 노드 추가 · 선 위를 클릭하면 선이 나뉩니다",
    "line": "선: 시작점 → 끝점 클릭 (연속 입력, 교차하면 자동 분할) · Esc/우클릭=종료",
    "area": "면: 선으로 닫힌 영역 안을 클릭 · 또는 노드를 차례로 클릭 후 첫 노드/우클릭으로 닫기",
    "load": "하중: [하중] 탭에서 값을 정한 뒤 노드/선/면을 클릭",
}
MODE_TAG = {"node": "● 노드 입력 모드", "line": "╱ 선 입력 모드", "area": "▱ 면 입력 모드",
            "load": "⬇ 하중 입력 모드"}


class PlanAnalysisPanel(DrawMixin, TreeTabMixin, InputTabMixin, LoadTabMixin, ResultTabMixin):

    def __init__(self, win, username=""):
        self.win = win
        self.username = username
        self.model = pm.new_model()
        self.file_path = None
        self.dirty = False
        self.undo_stack, self.redo_stack = [], []
        self.analysis = None              # analyze() 결과
        self.res_key = None
        self.sel = {"node": set(), "line": set(), "area": set()}
        self.edit_target = None
        self.mode = tk.StringVar(value="select")
        self.chain = None                 # 선 연속 입력 시작 노드
        self.poly = []                    # 면 노드 순서 입력
        self.hover = None
        self.drop_hover = None
        self.snap = None
        self.box = None
        self._pan = None
        self._r_press = None
        self._tree_expected = None

        self.scale = 40.0
        self.ox, self.oy = 120.0, 600.0
        self.show_ids = tk.BooleanVar(value=True)
        self.show_loads = tk.BooleanVar(value=True)
        self.show_grid = tk.BooleanVar(value=True)
        self.show_mesh = tk.BooleanVar(value=False)
        self.show_values = tk.BooleanVar(value=True)
        self.res_type = tk.StringVar(value="")
        self.res_scale = 1.0
        self.active_case = 1

        setup_style(win)
        self._build()
        self._bind_keys()
        self.refresh_all()
        self._update_title()
        win.protocol("WM_DELETE_WINDOW", self._on_close)
        win.after(80, self.fit_view)

    # 호환용 단축 속성
    @property
    def sel_nodes(self):
        return self.sel["node"]

    # ════════════════════════════════════════════════════════
    #  UI
    # ════════════════════════════════════════════════════════
    def _build(self):
        w = self.win
        w.configure(bg=BG)
        self._build_toolbar(w)
        tk.Frame(w, bg=BDR, height=1).pack(fill="x")
        body = tk.PanedWindow(w, orient="horizontal", bg=BDR, sashwidth=4, bd=0, sashrelief="flat")
        body.pack(fill="both", expand=True)
        left = tk.Frame(body, bg=BG2, width=360)
        body.add(left, minsize=300, width=360)
        self.nb = ttk.Notebook(left)
        self.nb.pack(fill="both", expand=True)
        self._build_tree_tab(self.nb)
        self._build_input_tab(self.nb)
        self._build_load_tab(self.nb)
        self._build_result_tab(self.nb)

        right = tk.Frame(body, bg=CANV_BG)
        body.add(right, minsize=400)
        vbar = tk.Frame(right, bg=BG2)
        vbar.pack(fill="x")
        tk.Label(vbar, text="보기", font=FONT_S, bg=BG2, fg=TX3).pack(side="left", padx=(8, 4))
        for text, var in (("번호", self.show_ids), ("하중", self.show_loads), ("격자", self.show_grid),
                          ("메시", self.show_mesh), ("결과값", self.show_values)):
            check(vbar, text, var, command=self.redraw).pack(side="left", padx=3)
        tk.Label(vbar, text="  결과 크기", font=FONT_S, bg=BG2, fg=TX3).pack(side="left", padx=(10, 2))
        btn(vbar, "－", lambda: self._res_zoom(1 / 1.25), padx=6, pady=0).pack(side="left", padx=1)
        btn(vbar, "＋", lambda: self._res_zoom(1.25), padx=6, pady=0).pack(side="left", padx=1)
        self.st_mode = tk.Label(vbar, text="", font=FONT_S, bg=BG2, fg=C_SEL)
        self.st_mode.pack(side="right", padx=8)
        self.canvas = tk.Canvas(right, bg=CANV_BG, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self._bind_canvas()

        sb = tk.Frame(w, bg=BG3, height=24)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)
        self.st_xy = tk.Label(sb, text="X: 0.000  Y: 0.000", font=FONT_M, bg=BG3, fg=CYN, width=34, anchor="w")
        self.st_xy.pack(side="left", padx=8)
        tk.Frame(sb, bg=BDR, width=1).pack(side="left", fill="y", pady=4)
        self.st_msg = tk.Label(sb, text="", font=FONT_S, bg=BG3, fg=TX2, anchor="w")
        self.st_msg.pack(side="left", padx=8, fill="x", expand=True)
        self.st_info = tk.Label(sb, text="", font=FONT_S, bg=BG3, fg=TX3, anchor="e")
        self.st_info.pack(side="right", padx=8)

    def _build_toolbar(self, parent):
        tb = tk.Frame(parent, bg=BG2)
        tb.pack(fill="x")
        row = tk.Frame(tb, bg=BG2)
        row.pack(fill="x", padx=6, pady=5)

        def sep():
            tk.Frame(row, bg=BDR, width=1, height=24).pack(side="left", padx=5)

        tk.Label(row, text="평면해석", font=FONT_H, bg=BG2, fg=ORANGE).pack(side="left", padx=(2, 6))
        btn(row, "📄", self.new_file, padx=6).pack(side="left", padx=1)
        btn(row, "📂", self.open_file, padx=6).pack(side="left", padx=1)
        btn(row, "💾", self.save_file, padx=6).pack(side="left", padx=1)
        sep()
        self.b_undo = btn(row, "↶", self.undo, font=("Malgun Gothic", 11), padx=5)
        self.b_undo.pack(side="left", padx=1)
        self.b_redo = btn(row, "↷", self.redo, font=("Malgun Gothic", 11), padx=5)
        self.b_redo.pack(side="left", padx=1)
        sep()
        for code, text in (("select", "⬚ 선택"), ("node", "● 노드"), ("line", "╱ 선"),
                           ("area", "▱ 면"), ("load", "⬇ 하중")):
            tk.Radiobutton(row, text=text, variable=self.mode, value=code, indicatoron=0,
                           command=self._on_mode, bg=BG3, fg=TXT, selectcolor=ACC,
                           activebackground=BG5, activeforeground=WHI, font=FONT_B,
                           relief="flat", bd=0, padx=9, pady=4, offrelief="flat",
                           cursor="hand2", highlightthickness=0).pack(side="left", padx=1)
        sep()
        btn(row, "▦ 격자 생성", self.open_grid_gen).pack(side="left", padx=1)
        btn(row, "⤢", self.fit_view, padx=6).pack(side="left", padx=1)
        sep()
        btn(row, "▶ 해석 (F5)", self.run_analysis, bg=GRN, fg=WHI, font=FONT_B,
            padx=10).pack(side="left", padx=2)
        sep()
        self.res_combo_var = tk.StringVar()
        self.res_combo = combo(row, self.res_combo_var, [], width=14)
        self.res_combo.pack(side="left", padx=2)
        self.res_combo.bind("<<ComboboxSelected>>", self._on_res_combo)
        groups = (("슬래브", (("Mx", "Mx"), ("My", "My"), ("Qx", "Qx"), ("Qy", "Qy"), ("D", "처짐"))),
                  ("보", (("BM", "M"), ("BV", "V"))),
                  ("", (("R", "반력"),)))
        for title, items in groups:
            if title:
                tk.Label(row, text=title, font=FONT_S, bg=BG2, fg=TX3).pack(side="left", padx=(6, 2))
            for code, text in items:
                tk.Radiobutton(row, text=text, variable=self.res_type, value=code, indicatoron=0,
                               command=self._on_res_type, bg=BG3, fg=TXT, selectcolor="#7c2d12",
                               activebackground=BG5, activeforeground=WHI, font=FONT_B,
                               relief="flat", bd=0, padx=6, pady=4, offrelief="flat",
                               cursor="hand2", highlightthickness=0).pack(side="left", padx=1)

    def _bind_keys(self):
        w = self.win
        w.bind("<Escape>", self._on_escape)
        w.bind("<Return>", lambda e: self._key_guard(e, self._close_poly))
        w.bind("<Delete>", lambda e: self._key_guard(e, self.delete_selected))
        w.bind("<Control-z>", lambda e: self._key_guard(e, self.undo))
        w.bind("<Control-y>", lambda e: self._key_guard(e, self.redo))
        w.bind("<Control-s>", lambda e: self.save_file())
        w.bind("<Control-o>", lambda e: self.open_file())
        w.bind("<F5>", lambda e: self.run_analysis())
        w.bind("<Control-a>", lambda e: self._key_guard(e, self.select_all))

    def _key_guard(self, e, fn):
        if isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text)):
            return
        fn()
        return "break"

    def _bind_canvas(self):
        c = self.canvas
        c.bind("<Configure>", lambda e: self.redraw())
        c.bind("<Motion>", self._on_motion)
        c.bind("<Leave>", lambda e: self._set_hover(None))
        c.bind("<ButtonPress-1>", self._on_b1)
        c.bind("<B1-Motion>", self._on_b1_motion)
        c.bind("<ButtonRelease-1>", self._on_b1_release)
        c.bind("<ButtonPress-2>", self._pan_start)
        c.bind("<B2-Motion>", self._pan_move)
        c.bind("<ButtonPress-3>", self._on_b3)
        c.bind("<B3-Motion>", self._on_b3_motion)
        c.bind("<ButtonRelease-3>", self._on_b3_release)
        c.bind("<MouseWheel>", lambda e: self._zoom_at(e.x, e.y, 1.15 if e.delta > 0 else 1 / 1.15))
        c.bind("<Button-4>", lambda e: self._zoom_at(e.x, e.y, 1.15))
        c.bind("<Button-5>", lambda e: self._zoom_at(e.x, e.y, 1 / 1.15))

    # ════════════════════════════════════════════════════════
    #  좌표 · 히트테스트 · 스냅
    # ════════════════════════════════════════════════════════
    def w2c(self, x, y):
        return self.ox + x * self.scale, self.oy - y * self.scale

    def c2w(self, cx, cy):
        return (cx - self.ox) / self.scale, (self.oy - cy) / self.scale

    def hit_node(self, cx, cy, tol=SNAP_PX):
        best, bd = None, tol
        for nid, n in self.model["nodes"].items():
            px, py = self.w2c(n["x"], n["y"])
            d = math.hypot(px - cx, py - cy)
            if d <= bd:
                best, bd = nid, d
        return best

    def _seg_dist_c(self, cx, cy, lid):
        ln = self.model["lines"][lid]
        a, b = self.model["nodes"][ln["ni"]], self.model["nodes"][ln["nj"]]
        ax, ay = self.w2c(a["x"], a["y"]); bx, by = self.w2c(b["x"], b["y"])
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 < 1e-9:
            return math.hypot(cx - ax, cy - ay)
        t = max(0.0, min(1.0, ((cx - ax) * dx + (cy - ay) * dy) / L2))
        return math.hypot(cx - (ax + t * dx), cy - (ay + t * dy))

    def hit_line(self, cx, cy, tol=HIT_PX):
        best, bd = None, tol
        for lid in self.model["lines"]:
            d = self._seg_dist_c(cx, cy, lid)
            if d <= bd:
                best, bd = lid, d
        return best

    def hit_area(self, cx, cy):
        x, y = self.c2w(cx, cy)
        best = None
        for aid, ar in self.model["areas"].items():
            pts = pm.poly_xy(self.model, ar["nodes"])
            if pm.point_in_poly(x, y, pts):
                A = abs(pm.poly_area(pts))
                if best is None or A < best[0]:
                    best = (A, aid)
        return best[1] if best else None

    def hit_any(self, cx, cy):
        n = self.hit_node(cx, cy, tol=9)
        if n is not None:
            return ("node", n)
        l = self.hit_line(cx, cy)
        if l is not None:
            return ("line", l)
        a = self.hit_area(cx, cy)
        if a is not None:
            return ("area", a)
        return None

    def snap_point(self, cx, cy):
        nid = self.hit_node(cx, cy)
        if nid is not None:
            n = self.model["nodes"][nid]
            return ("node", nid, n["x"], n["y"])
        g = float(self.model.get("grid", 0.5) or 0.5)
        wx, wy = self.c2w(cx, cy)
        gx, gy = round(wx / g) * g, round(wy / g) * g
        lid = self.hit_line(cx, cy)
        if lid is not None:
            ln = self.model["lines"][lid]
            a, b = self.model["nodes"][ln["ni"]], self.model["nodes"][ln["nj"]]
            dx, dy = b["x"] - a["x"], b["y"] - a["y"]
            L2 = dx * dx + dy * dy
            tg = ((gx - a["x"]) * dx + (gy - a["y"]) * dy) / L2
            px, py = a["x"] + tg * dx, a["y"] + tg * dy
            if 0 < tg < 1 and math.hypot(px - gx, py - gy) < 1e-6:
                return ("line", lid, round(gx, 6), round(gy, 6))
            t = ((wx - a["x"]) * dx + (wy - a["y"]) * dy) / L2
            if 0.001 < t < 0.999:
                return ("line", lid, round(a["x"] + t * dx, 3), round(a["y"] + t * dy, 3))
        return ("grid", None, round(gx, 6), round(gy, 6))

    def _node_from_snap(self, sp):
        if sp[0] == "node":
            return sp[1]
        return pm.add_node(self.model, sp[2], sp[3])     # 선 위면 자동 분할

    # ════════════════════════════════════════════════════════
    #  캔버스 이벤트
    # ════════════════════════════════════════════════════════
    def _on_motion(self, e):
        wx, wy = self.c2w(e.x, e.y)
        mode = self.mode.get()
        if mode in ("node", "line"):
            self.snap = self.snap_point(e.x, e.y)
            sx, sy = self.snap[2], self.snap[3]
            txt = f"X: {sx:8.3f}  Y: {sy:8.3f}"
            if self.chain is not None and self.chain in self.model["nodes"]:
                n0 = self.model["nodes"][self.chain]
                txt += f"  L={math.hypot(sx - n0['x'], sy - n0['y']):.3f}"
            self.st_xy.config(text=txt)
            self.redraw()
            return
        if mode == "area" and self.poly:
            self.snap = ("node", self.hit_node(e.x, e.y), *self.c2w(e.x, e.y))
            self.redraw()
        self.st_xy.config(text=f"X: {wx:8.3f}  Y: {wy:8.3f}" + self.probe_text(wx, wy))
        self._set_hover(self.hit_any(e.x, e.y))

    def _set_hover(self, h):
        if h != self.hover:
            self.hover = h
            self.redraw()
            self.st_info.config(text=self._describe(h) if h else "")

    def _describe(self, h):
        kind, i = h
        m = self.model
        if kind == "node" and i in m["nodes"]:
            n = m["nodes"][i]
            s = f"N{i} ({n['x']:.3f}, {n['y']:.3f})"
            if i in m["supports"]:
                st = m["sup_types"].get(m["supports"][i])
                s += f" · 지점 {st['name']}" if st else ""
            return s
        if kind == "line" and i in m["lines"]:
            ln = m["lines"][i]
            s = f"L{i} {ln.get('name', '')}  N{ln['ni']}→N{ln['nj']}  {pm.line_length(m, i):.3f} m"
            if ln["kind"] == "beam":
                sec = m["sections"].get(ln["sec"], {})
                s += f" · 보 {sec.get('name', '?')} ({pm.section_desc(sec)})"
            else:
                s += " · 비구조 선"
            if i in m["line_supports"]:
                s += f" · 선지점 {m['sup_types'].get(m['line_supports'][i], {}).get('name', '')}"
            return s
        if kind == "area" and i in m["areas"]:
            ar = m["areas"][i]
            s = f"A{i} {ar.get('name', '')}  {pm.area_of(m, i):.2f} m²"
            if ar["kind"] == "slab":
                sl = m["slabs"].get(ar["slab"], {})
                s += f" · 슬래브 {sl.get('name', '?')} t={sl.get('t', 0):g}"
            else:
                s += f" · 비구조 면 ({pm.AREA_DIST_LABEL.get(ar.get('dist', 'two'))} 전달)"
            return s
        return ""

    def _on_b1(self, e):
        self.canvas.focus_set()
        mode = self.mode.get()
        shift = bool(e.state & 0x0001)
        m = self.model
        if mode == "select":
            h = self.hit_any(e.x, e.y)
            if h is None:
                self.box = [e.x, e.y, e.x, e.y]
                if not shift:
                    self.clear_sel(); self._selection_changed()
                return
            kind, i = h
            if shift:
                self.sel[kind].symmetric_difference_update({i})
            else:
                self.clear_sel(); self.sel[kind].add(i)
            self._selection_changed()
        elif mode == "node":
            sp = self.snap_point(e.x, e.y)
            if sp[0] == "node":
                self.clear_sel(); self.sel["node"].add(sp[1]); self._selection_changed(); return
            self.push_undo()
            nid = self._node_from_snap(sp)
            self.clear_sel(); self.sel["node"].add(nid)
            self.changed(f"노드 N{nid} 추가")
        elif mode == "line":
            sp = self.snap_point(e.x, e.y)
            if self.chain is None:
                self.push_undo()
                self.chain = self._node_from_snap(sp)
                self._chain_first = True
                self.changed(f"시작 노드 N{self.chain} — 끝점을 클릭하세요")
                return
            if not getattr(self, "_chain_first", False):
                self.push_undo()
            self._chain_first = False
            nj = self._node_from_snap(sp)
            if nj == self.chain:
                return
            lids = pm.add_line(m, self.chain, nj)
            self.chain = nj
            self.clear_sel(); self.sel["line"].update(lids)
            self.changed(f"선 {len(lids)}개 추가 — 계속 클릭 (Esc 종료)")
        elif mode == "area":
            nid = self.hit_node(e.x, e.y)
            if self.poly:
                if nid is None:
                    return
                if nid == self.poly[0] and len(self.poly) >= 3:
                    self._close_poly(); return
                if nid not in self.poly:
                    self.poly.append(nid); self.redraw()
                    self.msg(f"면 꼭짓점 {len(self.poly)}개 — 첫 노드 클릭/우클릭/Enter 로 닫기")
                return
            if nid is not None:
                self.poly = [nid]; self.redraw()
                self.msg("면 꼭짓점 1개 — 다음 노드를 클릭하세요")
                return
            x, y = self.c2w(e.x, e.y)
            face = find_face(m, x, y)
            if not face:
                self.msg("선으로 닫힌 영역이 아닙니다. (또는 노드를 차례로 클릭해 면을 만드세요)", ORG)
                return
            exist = [a for a, ar in m["areas"].items() if set(ar["nodes"]) == set(face)]
            if exist:
                self.clear_sel(); self.sel["area"].add(exist[0]); self._selection_changed()
                self.msg(f"이미 있는 면 A{exist[0]}")
                return
            self.push_undo()
            aid = pm.add_area(m, face)
            self.clear_sel(); self.sel["area"].add(aid)
            self.changed(f"면 A{aid} 추가 ({pm.area_of(m, aid):.2f} m²) — 슬래브 적용은 입력 탭/우클릭")
        elif mode == "load":
            h = self.hit_any(e.x, e.y)
            if h:
                self.apply_load_to([h])

    def _close_poly(self):
        if self.mode.get() != "area" or len(self.poly) < 3:
            return
        self.push_undo()
        aid = pm.add_area(self.model, self.poly)
        self.poly = []
        if aid is None:
            self.undo_stack.pop(); self.msg("면을 만들 수 없습니다.", ORG); self.redraw(); return
        self.clear_sel(); self.sel["area"].add(aid)
        self.changed(f"면 A{aid} 추가")

    def _on_b1_motion(self, e):
        if self.box is not None:
            self.box[2], self.box[3] = e.x, e.y
            self.redraw()

    def _on_b1_release(self, e):
        if self.box is None:
            return
        x0, y0, x1, y1 = self.box
        self.box = None
        if abs(x1 - x0) < 4 and abs(y1 - y0) < 4:
            self.redraw(); return
        lx, hx = sorted((x0, x1)); ly, hy = sorted((y0, y1))
        crossing = x1 < x0
        m = self.model

        def inside(nid):
            cx, cy = self.w2c(m["nodes"][nid]["x"], m["nodes"][nid]["y"])
            return lx <= cx <= hx and ly <= cy <= hy
        ins = {n for n in m["nodes"] if inside(n)}
        self.sel["node"] |= ins
        for lid, ln in m["lines"].items():
            a, b = ln["ni"] in ins, ln["nj"] in ins
            if (a and b) or (crossing and (a or b)):
                self.sel["line"].add(lid)
        for aid, ar in m["areas"].items():
            k = sum(1 for n in ar["nodes"] if n in ins)
            if k == len(ar["nodes"]) or (crossing and k):
                self.sel["area"].add(aid)
        self._selection_changed()

    def _pan_start(self, e):
        self._pan = (e.x, e.y, self.ox, self.oy)

    def _pan_move(self, e):
        if self._pan:
            x0, y0, ox, oy = self._pan
            self.ox = ox + (e.x - x0); self.oy = oy + (e.y - y0)
            self.redraw()

    def _on_b3(self, e):
        self._r_press = (e.x, e.y, False)
        self._pan_start(e)

    def _on_b3_motion(self, e):
        if self._r_press:
            x0, y0, moved = self._r_press
            if moved or abs(e.x - x0) + abs(e.y - y0) > 4:
                self._r_press = (x0, y0, True)
                self.canvas.config(cursor="fleur")
                self._pan_move(e)

    def _on_b3_release(self, e):
        moved = self._r_press and self._r_press[2]
        self._r_press = None; self._pan = None
        self.canvas.config(cursor="crosshair")
        if moved:
            return
        if self.chain is not None:
            self._end_chain(); return
        if self.poly:
            if len(self.poly) >= 3:
                self._close_poly()
            else:
                self.poly = []; self.redraw()
            return
        self._context_menu(e)

    def _zoom_at(self, cx, cy, f):
        ns = max(1.0, min(5000.0, self.scale * f))
        f = ns / self.scale
        self.ox = cx - (cx - self.ox) * f
        self.oy = cy - (cy - self.oy) * f
        self.scale = ns
        self.redraw()

    def fit_view(self):
        c = self.canvas
        W, H = max(c.winfo_width(), 200), max(c.winfo_height(), 200)
        nodes = list(self.model["nodes"].values())
        if not nodes:
            self.scale = 40.0; self.ox, self.oy = W * 0.12, H * 0.85
            self.redraw(); return
        xs = [n["x"] for n in nodes]; ys = [n["y"] for n in nodes]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        dx, dy = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
        self.scale = max(1.0, min((W - 200) / dx, (H - 140) / dy, 400))
        self.ox = W / 2 - (x0 + x1) / 2 * self.scale - 30
        self.oy = H / 2 + (y0 + y1) / 2 * self.scale
        self.redraw()

    def _on_escape(self, e=None):
        if isinstance(getattr(e, "widget", None), (tk.Entry, ttk.Combobox)):
            return
        if self.chain is not None:
            self._end_chain(); return
        if self.poly:
            self.poly = []; self.redraw(); self.msg("면 입력 취소"); return
        if self.mode.get() != "select":
            self.mode.set("select"); self._on_mode(); return
        self.clear_sel(); self._selection_changed()

    def _end_chain(self):
        self.chain = None
        self.msg("연속 입력 종료")
        self.redraw()

    def _on_mode(self):
        self.chain = None; self.poly = []; self.snap = None; self.box = None
        m = self.mode.get()
        self.msg(MODE_HINT.get(m, ""))
        self.st_mode.config(text=(MODE_TAG[m] + "  (Esc: 선택 모드)") if m in MODE_TAG else "")
        if m == "load":
            self.nb.select(self.tab_load)
        self.redraw()

    # ── 우클릭 메뉴 ─────────────────────────────────────────
    def _menu(self, parent=None):
        return tk.Menu(parent or self.win, tearoff=0, bg=BG3, fg=TXT, activebackground=ACC,
                       activeforeground=WHI, font=FONT, bd=0)

    def _context_menu(self, e):
        h = self.hit_any(e.x, e.y)
        m = self.model
        menu = self._menu()
        if h:
            kind, i = h
            if i not in self.sel[kind]:
                self.clear_sel(); self.sel[kind].add(i); self._selection_changed()
        if h and h[0] == "node":
            tg = sorted(self.sel["node"])
            sub = self._menu(menu)
            for sid, st in m["sup_types"].items():
                sub.add_command(label=f"{st['name']}   ({pm.support_desc(st)})",
                                command=lambda s=sid: self.assign_support(tg, s))
            sub.add_separator()
            sub.add_command(label="지점 해제", command=lambda: self.assign_support(tg, None))
            menu.add_cascade(label=f"지점 지정 ({len(tg)}개 노드)", menu=sub)
            menu.add_command(label="집중하중 입력…", command=lambda: self._goto_load("node"))
        elif h and h[0] == "line":
            tg = sorted(self.sel["line"])
            sub = self._menu(menu)
            for sid, sec in m["sections"].items():
                sub.add_command(label=f"{sec['name']}   ({pm.section_desc(sec)})",
                                command=lambda s=sid: self.assign_beam(tg, sec=s))
            menu.add_cascade(label=f"보로 적용 ({len(tg)}개 선)", menu=sub)
            menu.add_command(label="비구조 선으로 (보 해제)", command=lambda: self.unassign("line", tg))
            sub2 = self._menu(menu)
            for sid, st in m["sup_types"].items():
                sub2.add_command(label=st["name"], command=lambda s=sid: self.assign_line_support(tg, s))
            sub2.add_separator()
            sub2.add_command(label="선 지점 해제", command=lambda: self.assign_line_support(tg, None))
            menu.add_cascade(label="선 지점 (벽체)", menu=sub2)
            menu.add_command(label="선하중 입력…", command=lambda: self._goto_load("line"))
        elif h and h[0] == "area":
            tg = sorted(self.sel["area"])
            sub = self._menu(menu)
            for sid, sl in m["slabs"].items():
                sub.add_command(label=f"{sl['name']}   (t={sl['t']:g})",
                                command=lambda s=sid: self.assign_slab(tg, s))
            menu.add_cascade(label=f"슬래브로 적용 ({len(tg)}개 면)", menu=sub)
            menu.add_command(label="비구조 면으로 (슬래브 해제)", command=lambda: self.unassign("area", tg))
            sub2 = self._menu(menu)
            for code, lbl in pm.AREA_DIST:
                sub2.add_command(label=lbl, command=lambda c=code: self.set_dist(tg, c))
            menu.add_cascade(label="비구조 면 하중 전달", menu=sub2)
            menu.add_command(label="면하중 입력…", command=lambda: self._goto_load("area"))
        if h:
            menu.add_separator()
            menu.add_command(label="삭제", command=self.delete_selected)
        else:
            menu.add_command(label="맞춤 보기", command=self.fit_view)
            menu.add_command(label="전체 선택 (Ctrl+A)", command=self.select_all)
            menu.add_command(label="격자 생성…", command=self.open_grid_gen)
        menu.tk_popup(e.x_root, e.y_root)

    def _goto_load(self, kind):
        self.load_kind.set(kind)
        self._on_load_kind()
        self.nb.select(self.tab_load)

    # ════════════════════════════════════════════════════════
    #  선택 · 변경 관리
    # ════════════════════════════════════════════════════════
    def clear_sel(self):
        for s in self.sel.values():
            s.clear()

    def select_all(self):
        self.sel["node"] = set(self.model["nodes"])
        self.sel["line"] = set(self.model["lines"])
        self.sel["area"] = set(self.model["areas"])
        self._selection_changed()

    def _selection_changed(self):
        self.edit_target = None
        self.redraw()
        self.show_editor()
        self.sync_tree_selection()
        self.refresh_result_detail()
        c = {k: len(v) for k, v in self.sel.items()}
        if any(c.values()):
            self.msg(f"선택: 노드 {c['node']} · 선 {c['line']} · 면 {c['area']}")

    def push_undo(self):
        self.undo_stack.append(copy.deepcopy(self.model))
        if len(self.undo_stack) > UNDO_MAX:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self._refresh_undo_btns()

    def undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(copy.deepcopy(self.model))
        self.model = self.undo_stack.pop()
        self.chain = None; self.poly = []
        self.changed("실행 취소")

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(copy.deepcopy(self.model))
        self.model = self.redo_stack.pop()
        self.changed("다시 실행")

    def _refresh_undo_btns(self):
        self.b_undo.config(fg=TXT if self.undo_stack else DIS)
        self.b_redo.config(fg=TXT if self.redo_stack else DIS)

    def _clean_selection(self):
        m = self.model
        self.sel["node"] &= set(m["nodes"]); self.sel["line"] &= set(m["lines"])
        self.sel["area"] &= set(m["areas"])
        if self.active_case not in m["cases"] and m["cases"]:
            self.active_case = min(m["cases"])
        if self.edit_target:
            k, i = self.edit_target
            d = {"MAT": "materials", "SEC": "sections", "SLB": "slabs", "ST": "sup_types",
                 "CASE": "cases", "CO": "combos"}.get(k)
            if d and i not in m[d]:
                self.edit_target = None

    def changed(self, msg=""):
        self.dirty = True
        self._ver = getattr(self, "_ver", 0) + 1
        if self.analysis is not None:
            self.analysis = None
            self.res_type.set("")
        self._clean_selection()
        self.refresh_all()
        self._update_title()
        if msg:
            self.msg(msg)

    def refresh_all(self):
        self._refresh_undo_btns()
        self.refresh_tree()
        self.show_editor()
        self.refresh_load_tab()
        self.refresh_result_list()
        self.redraw()

    def msg(self, text, color=TX2):
        self.st_msg.config(text=text, fg=color)

    # ════════════════════════════════════════════════════════
    #  부재 적용 명령
    # ════════════════════════════════════════════════════════
    def assign_support(self, nids, sid):
        nids = [n for n in nids if n in self.model["nodes"]]
        if not nids:
            return
        self.push_undo()
        for n in nids:
            if sid is None:
                self.model["supports"].pop(n, None)
            else:
                self.model["supports"][n] = sid
        nm = self.model["sup_types"][sid]["name"] if sid else "해제"
        self.changed(f"지점 '{nm}' → 노드 {len(nids)}개")

    def assign_line_support(self, lids, sid):
        lids = [l for l in lids if l in self.model["lines"]]
        if not lids:
            return
        self.push_undo()
        for l in lids:
            if sid is None:
                self.model["line_supports"].pop(l, None)
            else:
                self.model["line_supports"][l] = sid
        nm = self.model["sup_types"][sid]["name"] if sid else "해제"
        self.changed(f"선 지점 '{nm}' → 선 {len(lids)}개")

    def assign_beam(self, lids, sec=None, mat=None):
        lids = [l for l in lids if l in self.model["lines"]]
        if not lids:
            return
        self.push_undo()
        for l in lids:
            ln = self.model["lines"][l]
            ln["kind"] = "beam"
            if sec is not None:
                ln["sec"] = sec
            if mat is not None:
                ln["mat"] = mat
        what = f"단면 '{self.model['sections'][sec]['name']}'" if sec else (
            f"재료 '{self.model['materials'][mat]['name']}'" if mat else "보")
        self.changed(f"보 적용 ({what}) → 선 {len(lids)}개")

    def assign_slab(self, aids, slab):
        aids = [a for a in aids if a in self.model["areas"]]
        if not aids:
            return
        bad = []
        from .mesh import _corners
        for a in aids:
            if len(_corners(self.model, self.model["areas"][a]["nodes"])) != 4:
                bad.append(a)
        self.push_undo()
        for a in aids:
            self.model["areas"][a]["kind"] = "slab"
            self.model["areas"][a]["slab"] = slab
        self.changed(f"슬래브 '{self.model['slabs'][slab]['name']}' → 면 {len(aids)}개")
        if bad:
            messagebox.showwarning("슬래브", "꼭짓점이 4개가 아닌 면이 있습니다: "
                                   + ", ".join(f"A{a}" for a in bad)
                                   + "\n해석하려면 면을 사각형으로 나눠 주세요.", parent=self.win)

    def unassign(self, kind, ids):
        self.push_undo()
        key = "lines" if kind == "line" else "areas"
        for i in ids:
            if i in self.model[key]:
                self.model[key][i]["kind"] = "none"
        self.changed(f"{'선' if kind == 'line' else '면'} {len(ids)}개 → 비구조")

    def set_dist(self, aids, code):
        self.push_undo()
        for a in aids:
            if a in self.model["areas"]:
                self.model["areas"][a]["dist"] = code
        self.changed(f"하중 전달 '{pm.AREA_DIST_LABEL[code]}' → 면 {len(aids)}개")

    def delete_selected(self):
        s = self.sel
        if not any(s.values()):
            return
        self.push_undo()
        pm.delete_areas(self.model, s["area"])
        pm.delete_lines(self.model, s["line"])
        pm.delete_nodes(self.model, s["node"])
        c = {k: len(v) for k, v in s.items()}
        self.clear_sel()
        self.changed(f"삭제: 노드 {c['node']} · 선 {c['line']} · 면 {c['area']}")

    def copy_nodes_cmd(self, nids, dx, dy, times, lines, areas, extras, move=False):
        nids = [n for n in nids if n in self.model["nodes"]]
        if not nids:
            messagebox.showwarning("노드 복사", "대상 노드가 없습니다.", parent=self.win); return
        if abs(dx) < 1e-12 and abs(dy) < 1e-12:
            messagebox.showwarning("노드 복사", "dx, dy 가 모두 0 입니다.", parent=self.win); return
        self.push_undo()
        if move:
            err = pm.move_nodes(self.model, nids, dx, dy)
            if err:
                self.undo_stack.pop(); self._refresh_undo_btns()
                messagebox.showwarning("노드 이동", err, parent=self.win); return
            self.clear_sel(); self.sel["node"] |= set(nids)
            self.changed(f"노드 {len(nids)}개 이동")
        else:
            nn, nl, na = pm.copy_nodes(self.model, nids, dx, dy, times, lines, areas, extras)
            self.clear_sel()
            self.sel["node"] |= nn; self.sel["line"] |= nl; self.sel["area"] |= na
            self.changed(f"복사: 노드 {len(nn)} · 선 {len(nl)} · 면 {len(na)}")

    def open_grid_gen(self):
        dlg = GridGenDialog(self.win, self.model)
        self.win.wait_window(dlg)
        if not dlg.result:
            return
        r = dlg.result
        self.push_undo()
        if r["clear"]:
            keep = {k: self.model[k] for k in ("materials", "sections", "slabs", "sup_types",
                                               "cases", "combos", "defaults", "grid", "mesh_size",
                                               "torsion_factor")}
            self.model = pm.new_model(); self.model.update(keep)
        pm.generate_grid(self.model, r["xs"], r["ys"], beams=r["beams"], slabs=r["slabs"],
                         sec=r["sec"], slab=r["slab"], sup=r["sup"], x0=r["x0"], y0=r["y0"])
        self.clear_sel()
        self.changed(f"격자 생성: {len(r['xs'])}×{len(r['ys'])} 경간")
        self.fit_view()

    # ════════════════════════════════════════════════════════
    #  해석
    # ════════════════════════════════════════════════════════
    def run_analysis(self):
        self.chain = None; self.poly = []
        self.msg("해석 중…", C_SEL)
        self.win.config(cursor="watch"); self.win.update_idletasks()
        try:
            res = analyze(self.model)
        except PlanError as ex:
            messagebox.showerror("해석 오류", str(ex), parent=self.win)
            self.msg("해석 실패", RED)
            return
        except Exception as ex:
            messagebox.showerror("해석 오류", f"{type(ex).__name__}: {ex}", parent=self.win)
            self.msg("해석 실패", RED)
            return
        finally:
            self.win.config(cursor="")
        self.analysis = res
        if self.res_key not in res["results"]:
            self.res_key = ("case", self.active_case) if ("case", self.active_case) in res["results"] \
                else next(iter(res["results"]))
        if not self.res_type.get():
            self.res_type.set("Mx" if len(res["mesh"].plates) else "BM")
        self.refresh_result_list()
        self.refresh_result_tables()
        self.redraw()
        mesh = res["mesh"]
        txt = (f"해석 완료 — 절점 {len(mesh.xy)}, 슬래브 요소 {len(mesh.plates)}, "
               f"보 요소 {len(mesh.beams)}, 자유도 {res['nfree']}")
        self.msg(txt, GRNH)
        if res["warnings"]:
            messagebox.showwarning("해석 경고", "\n".join(res["warnings"]), parent=self.win)
        self.nb.select(self.tab_result)

    def _on_res_type(self):
        if self.analysis is None:
            self.res_type.set("")
            if messagebox.askyesno("안내", "해석 결과가 없습니다. 지금 해석할까요?", parent=self.win):
                self.run_analysis()
            return
        self.redraw()
        self.refresh_result_detail()

    def _res_zoom(self, f):
        self.res_scale = max(0.1, min(20.0, self.res_scale * f))
        self.redraw()

    # ════════════════════════════════════════════════════════
    #  파일
    # ════════════════════════════════════════════════════════
    def _update_title(self):
        name = os.path.basename(self.file_path) if self.file_path else "새 모델"
        star = " *" if self.dirty else ""
        user = f"  [{self.username}]" if self.username else ""
        self.win.title(f"평면해석 — {name}{star}  ·  StrCAD 2D Design{user}")

    def _confirm_discard(self):
        if not self.dirty:
            return True
        ans = messagebox.askyesnocancel("저장", "변경 내용을 저장할까요?", parent=self.win)
        if ans is None:
            return False
        return self.save_file() if ans else True

    def _reset_state(self):
        self.undo_stack.clear(); self.redo_stack.clear()
        self.clear_sel(); self.analysis = None; self.res_type.set("")
        self.edit_target = None
        self.active_case = min(self.model["cases"]) if self.model["cases"] else 1
        self.dirty = False
        self.refresh_all(); self._update_title(); self.fit_view()

    def new_file(self):
        if not self._confirm_discard():
            return
        self.model = pm.new_model(); self.file_path = None
        self._reset_state()

    def open_file(self):
        if not self._confirm_discard():
            return
        p = filedialog.askopenfilename(parent=self.win, title="평면해석 파일 열기",
                                       filetypes=[("평면해석", "*" + pm.FILE_EXT), ("모든 파일", "*.*")])
        if not p:
            return
        try:
            with open(p, encoding="utf-8") as f:
                self.model = pm.from_json(f.read())
        except Exception as ex:
            messagebox.showerror("열기 실패", str(ex), parent=self.win); return
        self.file_path = p
        self._reset_state()
        self.msg(f"열기: {p}")

    def save_file(self, ask=False):
        p = self.file_path
        if ask or not p:
            p = filedialog.asksaveasfilename(parent=self.win, title="평면해석 저장",
                                             defaultextension=pm.FILE_EXT,
                                             filetypes=[("평면해석", "*" + pm.FILE_EXT)])
            if not p:
                return False
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(pm.to_json(self.model))
        except Exception as ex:
            messagebox.showerror("저장 실패", str(ex), parent=self.win); return False
        self.file_path = p; self.dirty = False
        self._update_title(); self.msg(f"저장: {p}", GRNH)
        return True

    def _on_close(self):
        if self._confirm_discard():
            self.win.destroy()
