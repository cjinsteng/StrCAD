"""
design_2d/section/panel.py — 단면해석 (2D 프레임 해석) 메인 화면
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ┌ 툴바 ────────────────────────────────────────────────────────┐
 │ 파일 · 실행취소 · 모드(선택/노드/부재/하중) · 프레임생성 · 해석 · 결과표시 │
 ├──────────────┬───────────────────────────────────────────────┤
 │ [트리][입력] │                                               │
 │ [하중][결과] │                캔버스                          │
 │              │                                               │
 ├──────────────┴───────────────────────────────────────────────┤
 │ 상태표시줄 (좌표 · 안내)                                       │
 └──────────────────────────────────────────────────────────────┘
 기능은 Mixin 으로 분리:
   draw.py        캔버스 그리기
   tree_tab.py    트리(Works) 탭 + 트리 → 캔버스 드래그 지정
   input_tab.py   입력(속성 편집) 탭
   load_tab.py    하중 탭
   result_tab.py  결과 탭
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import copy
import math
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from . import model as fm
from .solver import solve_all, FrameError
from .theme import *
from .draw import DrawMixin
from .tree_tab import TreeTabMixin
from .input_tab import InputTabMixin
from .load_tab import LoadTabMixin
from .result_tab import ResultTabMixin
from .dialogs import FrameGenDialog

UNDO_MAX = 100
SNAP_PX = 12
HIT_PX = 7

MODE_HINT = {
    "select": "선택: 클릭(Shift=추가) · 빈 곳 드래그=영역선택 · 우클릭=메뉴 · 휠=확대 · 가운데/우 드래그=이동",
    "node": "노드: 클릭한 위치(격자 스냅)에 노드 추가 · 부재 위 클릭 시 부재 분할",
    "elem": "부재: 시작점 클릭 → 끝점 클릭 (연속 입력) · Esc/우클릭=연속 입력 종료",
    "load": "하중: [하중] 탭에서 값을 정한 뒤 노드/부재를 클릭하면 하중이 입력됩니다",
}


class SectionAnalysisPanel(DrawMixin, TreeTabMixin, InputTabMixin,
                           LoadTabMixin, ResultTabMixin):

    def __init__(self, win, username=""):
        self.win = win
        self.username = username
        self.model = fm.new_model()
        self.file_path = None
        self.dirty = False
        self.undo_stack, self.redo_stack = [], []
        self.results = None

        self.sel_nodes, self.sel_elems = set(), set()
        self.edit_target = None          # ("MAT", id) 등 트리에서 고른 편집 대상
        self.mode = tk.StringVar(value="select")
        self.chain = None                # 부재 연속 입력 시작 노드
        self.hover = None                # ("node", id) / ("elem", id)
        self.drop_hover = None
        self.snap = None
        self.box = None                  # 영역선택 (x0, y0, x1, y1) canvas
        self.mouse_c = (0, 0)
        self._pan = None
        self._r_press = None
        self._tree_expected = None

        # 보기
        self.scale = 60.0                # px / m
        self.ox, self.oy = 120.0, 500.0
        self.show_ids = tk.BooleanVar(value=True)
        self.show_loads = tk.BooleanVar(value=True)
        self.show_grid = tk.BooleanVar(value=True)
        self.show_values = tk.BooleanVar(value=True)
        self.res_type = tk.StringVar(value="")
        self.res_scale = 1.0
        self.res_key = None
        self.active_case = 1

        setup_style(win)
        self._build()
        self._bind_keys()
        self.refresh_all()
        self._update_title()
        win.protocol("WM_DELETE_WINDOW", self._on_close)
        win.after(80, self.fit_view)

    # ════════════════════════════════════════════════════════
    #  UI 구성
    # ════════════════════════════════════════════════════════
    def _build(self):
        w = self.win
        w.configure(bg=BG)
        self._build_toolbar(w)
        tk.Frame(w, bg=BDR, height=1).pack(fill="x")

        body = tk.PanedWindow(w, orient="horizontal", bg=BDR, sashwidth=4,
                              bd=0, sashrelief="flat")
        body.pack(fill="both", expand=True)

        left = tk.Frame(body, bg=BG2, width=350)
        body.add(left, minsize=290, width=350)
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
        for text, var in (("번호", self.show_ids), ("하중", self.show_loads),
                          ("격자", self.show_grid), ("결과값", self.show_values)):
            check(vbar, text, var, command=self.redraw).pack(side="left", padx=3)
        tk.Label(vbar, text="  결과 크기", font=FONT_S, bg=BG2, fg=TX3).pack(side="left", padx=(10, 2))
        btn(vbar, "－", lambda: self._res_zoom(1 / 1.25), padx=6, pady=0).pack(side="left", padx=1)
        btn(vbar, "＋", lambda: self._res_zoom(1.25), padx=6, pady=0).pack(side="left", padx=1)
        self.st_mode = tk.Label(vbar, text="", font=FONT_S, bg=BG2, fg=C_SEL)
        self.st_mode.pack(side="right", padx=8)
        self.canvas = tk.Canvas(right, bg=CANV_BG, highlightthickness=0,
                                cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self._bind_canvas()

        sb = tk.Frame(w, bg=BG3, height=24)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)
        self.st_xy = tk.Label(sb, text="X: 0.000  Y: 0.000", font=FONT_M,
                              bg=BG3, fg=CYN, width=26, anchor="w")
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
            tk.Frame(row, bg=BDR, width=1, height=24).pack(side="left", padx=6)

        tk.Label(row, text="단면해석", font=FONT_H, bg=BG2, fg=ORANGE).pack(side="left", padx=(2, 8))
        btn(row, "📄 새로", self.new_file).pack(side="left", padx=1)
        btn(row, "📂 열기", self.open_file).pack(side="left", padx=1)
        btn(row, "💾 저장", self.save_file).pack(side="left", padx=1)
        sep()
        self.b_undo = btn(row, "↶", self.undo, font=("Malgun Gothic", 11), padx=6)
        self.b_undo.pack(side="left", padx=1)
        self.b_redo = btn(row, "↷", self.redo, font=("Malgun Gothic", 11), padx=6)
        self.b_redo.pack(side="left", padx=1)
        sep()
        self.mode_btns = {}
        for code, text in (("select", "⬚ 선택"), ("node", "● 노드"),
                           ("elem", "╱ 부재"), ("load", "⬇ 하중")):
            b = tk.Radiobutton(row, text=text, variable=self.mode, value=code,
                               indicatoron=0, command=self._on_mode,
                               bg=BG3, fg=TXT, selectcolor=ACC,
                               activebackground=BG5, activeforeground=WHI,
                               font=FONT_B, relief="flat", bd=0, padx=10, pady=4,
                               offrelief="flat", cursor="hand2",
                               highlightthickness=0)
            b.pack(side="left", padx=1)
            self.mode_btns[code] = b
        sep()
        btn(row, "▦ 프레임 생성", self.open_frame_gen).pack(side="left", padx=1)
        btn(row, "⤢ 맞춤", self.fit_view).pack(side="left", padx=1)
        sep()
        btn(row, "▶ 해석 실행 (F5)", self.run_analysis, bg=GRN, fg=WHI,
            font=FONT_B, padx=12).pack(side="left", padx=2)
        sep()
        tk.Label(row, text="결과", font=FONT_S, bg=BG2, fg=TX3).pack(side="left", padx=(0, 4))
        self.res_combo_var = tk.StringVar()
        self.res_combo = combo(row, self.res_combo_var, [], width=16)
        self.res_combo.pack(side="left", padx=2)
        self.res_combo.bind("<<ComboboxSelected>>", self._on_res_combo)
        self.res_btns = {}
        for code, text in (("M", "M"), ("V", "V"), ("N", "N"),
                           ("D", "변형"), ("R", "반력")):
            b = tk.Radiobutton(row, text=text, variable=self.res_type, value=code,
                               indicatoron=0, command=self._on_res_type,
                               bg=BG3, fg=TXT, selectcolor="#7c2d12",
                               activebackground=BG5, activeforeground=WHI,
                               font=FONT_B, relief="flat", bd=0, padx=8, pady=4,
                               offrelief="flat", cursor="hand2", highlightthickness=0)
            b.pack(side="left", padx=1)
            self.res_btns[code] = b

    def _bind_keys(self):
        w = self.win
        w.bind("<Escape>", self._on_escape)
        w.bind("<Delete>", lambda e: self._key_guard(e, self.delete_selected))
        w.bind("<Control-z>", lambda e: self._key_guard(e, self.undo))
        w.bind("<Control-y>", lambda e: self._key_guard(e, self.redo))
        w.bind("<Control-s>", lambda e: self.save_file())
        w.bind("<Control-o>", lambda e: self.open_file())
        w.bind("<F5>", lambda e: self.run_analysis())
        w.bind("<Control-a>", lambda e: self._key_guard(e, self.select_all))

    def _key_guard(self, e, fn):
        """Entry 에 입력 중일 때는 단축키 무시"""
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
        c.bind("<MouseWheel>", self._on_wheel)
        c.bind("<Button-4>", lambda e: self._zoom_at(e.x, e.y, 1.15))
        c.bind("<Button-5>", lambda e: self._zoom_at(e.x, e.y, 1 / 1.15))

    # ════════════════════════════════════════════════════════
    #  좌표 변환 · 스냅 · 히트테스트
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

    def _seg_dist(self, cx, cy, eid):
        e = self.model["elems"][eid]
        a, b = self.model["nodes"][e["ni"]], self.model["nodes"][e["nj"]]
        ax, ay = self.w2c(a["x"], a["y"])
        bx, by = self.w2c(b["x"], b["y"])
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 < 1e-9:
            return math.hypot(cx - ax, cy - ay), 0.0
        t = max(0.0, min(1.0, ((cx - ax) * dx + (cy - ay) * dy) / L2))
        return math.hypot(cx - (ax + t * dx), cy - (ay + t * dy)), t

    def hit_elem(self, cx, cy, tol=HIT_PX):
        best, bd = None, tol
        for eid in self.model["elems"]:
            d, _ = self._seg_dist(cx, cy, eid)
            if d <= bd:
                best, bd = eid, d
        return best

    def hit_any(self, cx, cy):
        n = self.hit_node(cx, cy, tol=9)
        if n is not None:
            return ("node", n)
        e = self.hit_elem(cx, cy)
        if e is not None:
            return ("elem", e)
        return None

    def snap_point(self, cx, cy):
        """('node', nid, x, y) | ('elem', eid, x, y, t) | ('grid', None, x, y)"""
        nid = self.hit_node(cx, cy)
        if nid is not None:
            n = self.model["nodes"][nid]
            return ("node", nid, n["x"], n["y"])
        g = float(self.model.get("grid", 0.5) or 0.5)
        wx, wy = self.c2w(cx, cy)
        gx, gy = round(wx / g) * g, round(wy / g) * g
        eid = self.hit_elem(cx, cy)
        if eid is not None:
            e = self.model["elems"][eid]
            a, b = self.model["nodes"][e["ni"]], self.model["nodes"][e["nj"]]
            dx, dy = b["x"] - a["x"], b["y"] - a["y"]
            L2 = dx * dx + dy * dy
            # 격자점이 부재 위에 있으면 격자점, 아니면 투영점
            tg = ((gx - a["x"]) * dx + (gy - a["y"]) * dy) / L2
            px, py = a["x"] + tg * dx, a["y"] + tg * dy
            if 0 < tg < 1 and math.hypot(px - gx, py - gy) < 1e-6 and \
                    math.hypot(*(v - w for v, w in zip(self.w2c(gx, gy), (cx, cy)))) < SNAP_PX * 1.5:
                return ("elem", eid, gx, gy, tg)
            t = ((wx - a["x"]) * dx + (wy - a["y"]) * dy) / L2
            if 0.001 < t < 0.999:
                x = round(a["x"] + t * dx, 3); y = round(a["y"] + t * dy, 3)
                return ("elem", eid, x, y, t)
        return ("grid", None, round(gx, 6), round(gy, 6))

    def _node_from_snap(self, sp):
        """스냅 결과로 노드 확보 (없으면 생성, 부재 위면 분할)"""
        if sp[0] == "node":
            return sp[1]
        if sp[0] == "elem":
            eid, x, y = sp[1], sp[2], sp[3]
            L = fm.elem_length(self.model, eid)
            e = self.model["elems"][eid]
            a = self.model["nodes"][e["ni"]]
            ratio = math.hypot(x - a["x"], y - a["y"]) / L
            return fm.split_elem(self.model, eid, ratio)
        return fm.add_node(self.model, sp[2], sp[3])

    # ════════════════════════════════════════════════════════
    #  캔버스 이벤트
    # ════════════════════════════════════════════════════════
    def _on_motion(self, e):
        self.mouse_c = (e.x, e.y)
        wx, wy = self.c2w(e.x, e.y)
        mode = self.mode.get()
        if mode in ("node", "elem"):
            self.snap = self.snap_point(e.x, e.y)
            sx, sy = self.snap[2], self.snap[3]
            txt = f"X: {sx:8.3f}  Y: {sy:8.3f}"
            if self.chain is not None:
                n0 = self.model["nodes"][self.chain]
                L = math.hypot(sx - n0["x"], sy - n0["y"])
                txt += f"   L={L:.3f}"
            self.st_xy.config(text=txt)
            self.redraw()
            return
        self.st_xy.config(text=f"X: {wx:8.3f}  Y: {wy:8.3f}")
        self._set_hover(self.hit_any(e.x, e.y))

    def _set_hover(self, h):
        if h != self.hover:
            self.hover = h
            self.redraw()
            if h:
                self.st_info.config(text=self._describe(h))
            else:
                self.st_info.config(text="")

    def _describe(self, h):
        kind, i = h
        m = self.model
        if kind == "node" and i in m["nodes"]:
            n = m["nodes"][i]
            s = f"N{i}  ({n['x']:.3f}, {n['y']:.3f})"
            if i in m["supports"]:
                st = m["sup_types"].get(m["supports"][i])
                if st:
                    s += f"  · 지점 {st['name']}"
            return s
        if kind == "elem" and i in m["elems"]:
            e = m["elems"][i]
            sec = m["sections"].get(e["sec"], {})
            mat = m["materials"].get(e["mat"], {})
            nm = e.get("name") or f"E{i}"
            return (f"{nm}  N{e['ni']}→N{e['nj']}  L={fm.elem_length(m, i):.3f} m  · "
                    f"{sec.get('name', '?')} ({fm.section_desc(sec)}) · {mat.get('name', '?')}")
        return ""

    def _on_b1(self, e):
        self.canvas.focus_set()
        mode = self.mode.get()
        shift = bool(e.state & 0x0001)
        if mode == "select":
            h = self.hit_any(e.x, e.y)
            if h is None:
                self.box = [e.x, e.y, e.x, e.y]
                if not shift:
                    self.sel_nodes.clear(); self.sel_elems.clear()
                    self._selection_changed()
                return
            kind, i = h
            target = self.sel_nodes if kind == "node" else self.sel_elems
            if shift:
                target.symmetric_difference_update({i})
            else:
                self.sel_nodes.clear(); self.sel_elems.clear()
                target.add(i)
            self._selection_changed()
        elif mode == "node":
            sp = self.snap_point(e.x, e.y)
            if sp[0] == "node":
                self.sel_nodes = {sp[1]}; self.sel_elems.clear()
                self._selection_changed()
                return
            self.push_undo()
            nid = self._node_from_snap(sp)
            self.sel_nodes = {nid}; self.sel_elems.clear()
            self.changed(f"노드 N{nid} 추가")
        elif mode == "elem":
            sp = self.snap_point(e.x, e.y)
            if self.chain is None:
                self.push_undo()
                self.chain = self._node_from_snap(sp)
                self._chain_undo_open = True
                self.changed(f"시작 노드 N{self.chain} — 끝점을 클릭하세요", keep_sel=True)
                return
            if not getattr(self, "_chain_undo_open", False):
                self.push_undo()
            nj = self._node_from_snap(sp)
            if nj == self.chain:
                return
            eid = fm.add_elem(self.model, self.chain, nj)
            self.chain = nj
            self._chain_undo_open = False
            self.sel_elems = {eid} if eid else set(); self.sel_nodes.clear()
            self.changed(f"부재 E{eid} 추가 — 계속 클릭하면 이어서 입력 (Esc 종료)")
        elif mode == "load":
            h = self.hit_any(e.x, e.y)
            if h:
                self.apply_load_to([h])

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
        crossing = x1 < x0      # 오른쪽→왼쪽 드래그 = 걸침 선택
        inside = lambda nid: (lx <= self.w2c(self.model["nodes"][nid]["x"], 0)[0] <= hx and
                              ly <= self.w2c(0, self.model["nodes"][nid]["y"])[1] <= hy)
        for nid in self.model["nodes"]:
            if inside(nid):
                self.sel_nodes.add(nid)
        for eid, el in self.model["elems"].items():
            a, b = inside(el["ni"]), inside(el["nj"])
            if (a and b) or (crossing and (a or b)):
                self.sel_elems.add(eid)
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
        self._context_menu(e)

    def _on_wheel(self, e):
        self._zoom_at(e.x, e.y, 1.15 if e.delta > 0 else 1 / 1.15)

    def _zoom_at(self, cx, cy, f):
        ns = max(2.0, min(5000.0, self.scale * f))
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
            self.scale = 60.0
            self.ox, self.oy = W * 0.15, H * 0.8
            self.redraw(); return
        xs = [n["x"] for n in nodes]; ys = [n["y"] for n in nodes]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        dx, dy = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
        self.scale = max(2.0, min((W - 160) / dx, (H - 160) / dy, 400))
        self.ox = W / 2 - (x0 + x1) / 2 * self.scale
        self.oy = H / 2 + (y0 + y1) / 2 * self.scale
        self.redraw()

    def _on_escape(self, e=None):
        if isinstance(getattr(e, "widget", None), (tk.Entry, ttk.Combobox)):
            return
        if self.chain is not None:
            self._end_chain(); return
        if self.mode.get() != "select":
            self.mode.set("select"); self._on_mode(); return
        self.sel_nodes.clear(); self.sel_elems.clear()
        self._selection_changed()

    def _end_chain(self):
        self.chain = None
        if getattr(self, "_chain_undo_open", False):
            # 시작 노드만 만들고 끝낸 경우: 고립 노드 정리
            self._chain_undo_open = False
        self.msg("연속 입력 종료")
        self.redraw()

    def _on_mode(self):
        self.chain = None
        self.snap = None
        self.box = None
        m = self.mode.get()
        self.msg(MODE_HINT.get(m, ""))
        self.st_mode.config(text={"node": "● 노드 입력 모드  (Esc: 선택 모드)",
                                  "elem": "╱ 부재 입력 모드  (Esc: 선택 모드)",
                                  "load": "⬇ 하중 입력 모드  (Esc: 선택 모드)"}.get(m, ""))
        if m == "load":
            self.nb.select(self.tab_load)
        self.redraw()

    # ── 우클릭 메뉴 ─────────────────────────────────────────
    def _context_menu(self, e):
        h = self.hit_any(e.x, e.y)
        menu = tk.Menu(self.win, tearoff=0, bg=BG3, fg=TXT, activebackground=ACC,
                       activeforeground=WHI, font=FONT, bd=0)
        m = self.model
        if h and h[0] == "node":
            nid = h[1]
            if nid not in self.sel_nodes:
                self.sel_nodes = {nid}; self.sel_elems.clear(); self._selection_changed()
            targets = sorted(self.sel_nodes)
            sub = tk.Menu(menu, tearoff=0, bg=BG3, fg=TXT, activebackground=ACC, font=FONT)
            for sid, st in m["sup_types"].items():
                sub.add_command(label=f"{st['name']}   ({fm.support_desc(st)})",
                                command=lambda s=sid: self.assign_support(targets, s))
            sub.add_separator()
            sub.add_command(label="지점 해제", command=lambda: self.assign_support(targets, None))
            menu.add_cascade(label=f"지점 지정 ({len(targets)}개 노드)", menu=sub)
            menu.add_command(label="절점하중 입력…", command=lambda: self._goto_load("node"))
            menu.add_separator()
            menu.add_command(label="삭제", command=self.delete_selected)
        elif h and h[0] == "elem":
            eid = h[1]
            if eid not in self.sel_elems:
                self.sel_elems = {eid}; self.sel_nodes.clear(); self._selection_changed()
            targets = sorted(self.sel_elems)
            sub = tk.Menu(menu, tearoff=0, bg=BG3, fg=TXT, activebackground=ACC, font=FONT)
            for sid, sec in m["sections"].items():
                sub.add_command(label=f"{sec['name']}   ({fm.section_desc(sec)})",
                                command=lambda s=sid: self.assign_elem(targets, sec=s))
            menu.add_cascade(label=f"단면 지정 ({len(targets)}개 부재)", menu=sub)
            sub2 = tk.Menu(menu, tearoff=0, bg=BG3, fg=TXT, activebackground=ACC, font=FONT)
            for mid, mat in m["materials"].items():
                sub2.add_command(label=mat["name"],
                                 command=lambda s=mid: self.assign_elem(targets, mat=s))
            menu.add_cascade(label="재료 지정", menu=sub2)
            sub3 = tk.Menu(menu, tearoff=0, bg=BG3, fg=TXT, activebackground=ACC, font=FONT)
            for rid, rt in m["rel_types"].items():
                sub3.add_command(label=f"{rt['name']}   ({fm.end_desc(rt['fi'], rt['fj'])})",
                                 command=lambda r=rid: self.assign_release(targets, r))
            menu.add_cascade(label="단부조건 (힌지·반강접)", menu=sub3)
            menu.add_command(label="부재하중 입력…", command=lambda: self._goto_load("dist"))
            menu.add_separator()
            menu.add_command(label="부재 2등분", command=lambda: self.split_selected(2))
            menu.add_command(label="부재 3등분", command=lambda: self.split_selected(3))
            menu.add_command(label="부재 방향 뒤집기 (i↔j)", command=self.flip_selected)
            menu.add_separator()
            menu.add_command(label="삭제", command=self.delete_selected)
        else:
            menu.add_command(label="맞춤 보기", command=self.fit_view)
            menu.add_command(label="전체 선택  (Ctrl+A)", command=self.select_all)
            menu.add_separator()
            menu.add_command(label="프레임 생성…", command=self.open_frame_gen)
        menu.tk_popup(e.x_root, e.y_root)

    def _goto_load(self, kind):
        self.load_kind.set(kind)
        self._on_load_kind()
        self.nb.select(self.tab_load)

    # ════════════════════════════════════════════════════════
    #  선택 / 변경 관리
    # ════════════════════════════════════════════════════════
    def select_all(self):
        self.sel_nodes = set(self.model["nodes"])
        self.sel_elems = set(self.model["elems"])
        self._selection_changed()

    def _selection_changed(self):
        self.edit_target = None
        self.redraw()
        self.show_editor()
        self.sync_tree_selection()
        self.refresh_result_detail()
        n, e = len(self.sel_nodes), len(self.sel_elems)
        if n or e:
            self.msg(f"선택: 노드 {n}개, 부재 {e}개")

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
        self.chain = None
        self._clean_selection()
        self.changed("실행 취소")

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(copy.deepcopy(self.model))
        self.model = self.redo_stack.pop()
        self._clean_selection()
        self.changed("다시 실행")

    def _refresh_undo_btns(self):
        self.b_undo.config(fg=TXT if self.undo_stack else DIS)
        self.b_redo.config(fg=TXT if self.redo_stack else DIS)

    def _clean_selection(self):
        self.sel_nodes &= set(self.model["nodes"])
        self.sel_elems &= set(self.model["elems"])
        if self.active_case not in self.model["cases"] and self.model["cases"]:
            self.active_case = min(self.model["cases"])
        if self.edit_target:
            k, i = self.edit_target
            d = {"MAT": "materials", "SEC": "sections", "ST": "sup_types",
                 "CASE": "cases", "CO": "combos", "RL": "rel_types"}.get(k)
            if d and i not in self.model[d]:
                self.edit_target = None

    def changed(self, msg="", keep_sel=False):
        """모델 변경 후 공통 처리"""
        self.dirty = True
        if self.results is not None:
            self.results = None
            self.res_type.set("")
            self.refresh_result_list()
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
        m = self.model
        self.st_info.config(text=f"노드 {len(m['nodes'])} · 부재 {len(m['elems'])} · "
                                 f"지점 {len(m['supports'])}")

    def msg(self, text, color=TX2):
        self.st_msg.config(text=text, fg=color)

    # ════════════════════════════════════════════════════════
    #  편집 명령
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
        name = self.model["sup_types"][sid]["name"] if sid else "해제"
        self.changed(f"지점 '{name}' → 노드 {len(nids)}개")

    def assign_elem(self, eids, sec=None, mat=None, name=None):
        eids = [i for i in eids if i in self.model["elems"]]
        if not eids:
            return
        self.push_undo()
        for i in eids:
            if sec is not None:
                self.model["elems"][i]["sec"] = sec
            if mat is not None:
                self.model["elems"][i]["mat"] = mat
            if name is not None:
                self.model["elems"][i]["name"] = name
        what = []
        if sec is not None:
            what.append(f"단면 '{self.model['sections'][sec]['name']}'")
        if mat is not None:
            what.append(f"재료 '{self.model['materials'][mat]['name']}'")
        self.changed(f"{', '.join(what) or '속성'} → 부재 {len(eids)}개")

    def assign_release(self, eids, rid):
        eids = [i for i in eids if i in self.model["elems"]]
        rt = self.model["rel_types"].get(rid)
        if not eids or not rt:
            return
        self.push_undo()
        for i in eids:
            fm.set_end_fix(self.model["elems"][i], rt["fi"], rt["fj"])
        self.changed(f"단부조건 '{rt['name']}' ({fm.end_desc(rt['fi'], rt['fj'])}) → 부재 {len(eids)}개")

    def copy_nodes_cmd(self, nids, dx, dy, times=1, elems=True, extras=False,
                       link=False, move=False):
        """노드 복사/이동 (입력 탭에서 호출)"""
        nids = [n for n in nids if n in self.model["nodes"]]
        if not nids:
            messagebox.showwarning("노드 복사", "대상 노드가 없습니다.", parent=self.win)
            return False
        if abs(dx) < 1e-12 and abs(dy) < 1e-12:
            messagebox.showwarning("노드 복사", "dx, dy 가 모두 0 입니다.", parent=self.win)
            return False
        self.push_undo()
        if move:
            err = fm.move_nodes(self.model, nids, dx, dy)
            if err:
                self.undo_stack.pop(); self._refresh_undo_btns()
                messagebox.showwarning("노드 이동", err, parent=self.win)
                return False
            self.sel_nodes = set(nids); self.sel_elems = set()
            self.changed(f"노드 {len(nids)}개 이동 ({dx:g}, {dy:g})")
        else:
            nn, ne = fm.copy_nodes(self.model, nids, dx, dy, times, elems, extras, link)
            self.sel_nodes, self.sel_elems = set(nn), set(ne)
            self.changed(f"노드 {len(nids)}개 × {times}회 복사 → 새 노드 {len(nn)}개, 새 부재 {len(ne)}개")
        self.redraw()
        return True

    def delete_selected(self):
        if not (self.sel_nodes or self.sel_elems):
            return
        self.push_undo()
        fm.delete_elems(self.model, self.sel_elems)
        fm.delete_nodes(self.model, self.sel_nodes)
        n, e = len(self.sel_nodes), len(self.sel_elems)
        self.sel_nodes.clear(); self.sel_elems.clear()
        self.changed(f"삭제: 노드 {n}개, 부재 {e}개")

    def split_selected(self, n):
        if not self.sel_elems:
            return
        self.push_undo()
        new_sel = set()
        for eid in sorted(self.sel_elems):
            cur = eid
            for k in range(n - 1, 0, -1):
                # 뒤에서부터 나누면 앞쪽 부재 id 가 유지된다
                fm.split_elem(self.model, cur, k / (k + 1))
            new_sel.add(cur)
        self.sel_elems = set()
        self.changed(f"부재 {len(new_sel)}개를 {n}등분")

    def flip_selected(self):
        if not self.sel_elems:
            return
        self.push_undo()
        for eid in self.sel_elems:
            e = self.model["elems"][eid]
            e["ni"], e["nj"] = e["nj"], e["ni"]
            fi, fj = fm.end_fix(e)
            fm.set_end_fix(e, fj, fi)
            L = fm.elem_length(self.model, eid)
            for ld in self.model["eloads"]:
                if ld["elem"] != eid:
                    continue
                f = 1.0 if ld.get("rel") else L
                if ld["kind"] == "point":
                    ld["a"] = f - ld["a"]
                else:
                    ld["a"], ld["b"] = f - ld["b"], f - ld["a"]
                    ld["w1"], ld["w2"] = ld["w2"], ld["w1"]
        self.changed("부재 방향 뒤집기")

    def open_frame_gen(self):
        dlg = FrameGenDialog(self.win, self.model)
        self.win.wait_window(dlg)
        if not dlg.result:
            return
        r = dlg.result
        self.push_undo()
        if r["clear"]:
            keep = {k: self.model[k] for k in ("materials", "sections", "sup_types",
                                               "cases", "combos", "defaults", "grid")}
            self.model = fm.new_model()
            self.model.update(keep)
        fm.generate_frame(self.model, r["spans"], r["heights"],
                          sec_beam=r["sec_beam"], sec_col=r["sec_col"],
                          mat=r["mat"], sup=r["sup"], x0=r["x0"], y0=r["y0"])
        self.sel_nodes.clear(); self.sel_elems.clear()
        self.changed(f"프레임 생성: {len(r['spans'])}경간 × {len(r['heights'])}층")
        self.fit_view()

    # ════════════════════════════════════════════════════════
    #  해석
    # ════════════════════════════════════════════════════════
    def run_analysis(self):
        self.chain = None
        try:
            res = solve_all(self.model)
        except FrameError as ex:
            messagebox.showerror("해석 오류", str(ex), parent=self.win)
            return
        except Exception as ex:      # 예상 못한 오류도 화면에 표시
            messagebox.showerror("해석 오류", f"{type(ex).__name__}: {ex}", parent=self.win)
            return
        self.results = res
        if self.res_key not in res:
            self.res_key = ("case", self.active_case) if ("case", self.active_case) in res \
                else next(iter(res))
        if not self.res_type.get():
            self.res_type.set("M")
        self.refresh_result_list()
        self.refresh_result_tables()
        self.redraw()
        auto = res[next(iter(res))].get("auto_fixed") or []
        txt = f"해석 완료 — 하중케이스 {len(self.model['cases'])}개, 조합 {len(self.model['combos'])}개"
        if auto:
            txt += f"  (회전강성 없는 노드 {len(auto)}개 회전 자동구속)"
        self.msg(txt, GRNH)
        self.nb.select(self.tab_result)

    def _on_res_type(self):
        if self.results is None:
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
        self.win.title(f"단면해석 — {name}{star}  ·  StrCAD 2D Design{user}")

    def _confirm_discard(self):
        if not self.dirty:
            return True
        ans = messagebox.askyesnocancel("저장", "변경 내용을 저장할까요?", parent=self.win)
        if ans is None:
            return False
        if ans:
            return self.save_file()
        return True

    def new_file(self):
        if not self._confirm_discard():
            return
        self.model = fm.new_model()
        self.file_path = None
        self.undo_stack.clear(); self.redo_stack.clear()
        self.sel_nodes.clear(); self.sel_elems.clear()
        self.results = None; self.res_type.set("")
        self.dirty = False
        self.refresh_all(); self._update_title(); self.fit_view()

    def open_file(self):
        if not self._confirm_discard():
            return
        p = filedialog.askopenfilename(
            parent=self.win, title="단면해석 파일 열기",
            filetypes=[("단면해석", "*" + fm.FILE_EXT), ("JSON", "*.json"), ("모든 파일", "*.*")])
        if not p:
            return
        try:
            with open(p, encoding="utf-8") as f:
                self.model = fm.from_json(f.read())
        except Exception as ex:
            messagebox.showerror("열기 실패", f"{ex}", parent=self.win)
            return
        self.file_path = p
        self.undo_stack.clear(); self.redo_stack.clear()
        self.sel_nodes.clear(); self.sel_elems.clear()
        self.results = None; self.res_type.set("")
        self.active_case = min(self.model["cases"]) if self.model["cases"] else 1
        self.dirty = False
        self.refresh_all(); self._update_title(); self.fit_view()
        self.msg(f"열기: {p}")

    def save_file(self, ask=False):
        p = self.file_path
        if ask or not p:
            p = filedialog.asksaveasfilename(
                parent=self.win, title="단면해석 저장", defaultextension=fm.FILE_EXT,
                filetypes=[("단면해석", "*" + fm.FILE_EXT)])
            if not p:
                return False
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(fm.to_json(self.model))
        except Exception as ex:
            messagebox.showerror("저장 실패", f"{ex}", parent=self.win)
            return False
        self.file_path = p
        self.dirty = False
        self._update_title()
        self.msg(f"저장: {p}", GRNH)
        return True

    def _on_close(self):
        if self._confirm_discard():
            self.win.destroy()

