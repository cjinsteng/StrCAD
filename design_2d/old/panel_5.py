"""
design_2d/panel.py
메인 2D Design 패널

추가/수정:
1. 치수 클릭 → 길이 직접 수정
2. 하중 입력 버그 수정 (단위 변환 올바르게)
3. 저장(.2dd) / 불러오기 기능
"""

import tkinter as tk
from tkinter import messagebox, filedialog, simpledialog
import math
import copy
import json
import os

from .constants import *
from .dialogs       import LoadInputDlg
from .result_window import ResultWindow
from .analyzer      import BeamAnalyzer


# ── 유틸 ────────────────────────────────────────────────────
def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])

def _pt_on_seg(px, py, ax, ay, bx, by, tol=8):
    return (_dist((px,py),(ax,ay)) + _dist((px,py),(bx,by))
            - _dist((ax,ay),(bx,by))) < tol

def _lerp(a, b, t):
    return a + (b - a) * t


# ════════════════════════════════════════════════════════════
class Design2DPanel:

    def __init__(self, win, username=""):
        self.win  = win
        self.user = username

        self.samples    = []
        self.sel_sample = tk.IntVar(value=-1)

        self.nodes    = []
        self.lines    = []
        self.supports = {}
        self.loads    = []
        self.node_id_seq = 0
        self.line_id_seq = 0

        # Undo / Redo
        self._undo_stack = []
        self._redo_stack = []

        self.mode          = tk.StringVar(value="none")
        self.node_sub_mode = tk.StringVar(value="point")
        self.support_type  = tk.StringVar(value="pin")
        self._load_sub     = "point"

        self.pending_line_start = None
        self.load_src_node      = None

        # 드래그
        self._drag_node = None

        self.view_type       = tk.StringVar(value="line")
        self.result_type     = tk.StringVar(value="none")
        self.analysis_result = None

        self.scale  = 0.12
        self.offset = [400, 300]
        self._pan_origin       = None
        self._pan_offset_start = None
        self._mouse_cx = 0
        self._mouse_cy = 0

        self._build()
        self._bind_canvas()

    # ════════════════════════════════════════════════════════
    #  Undo / Redo
    # ════════════════════════════════════════════════════════
    def _snapshot(self):
        state = {
            "nodes":    copy.deepcopy(self.nodes),
            "lines":    copy.deepcopy(self.lines),
            "supports": copy.deepcopy(self.supports),
            "loads":    copy.deepcopy(self.loads),
            "node_seq": self.node_id_seq,
            "line_seq": self.line_id_seq,
        }
        self._undo_stack.append(state)
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._refresh_undo_btns()

    def _restore(self, state):
        self.nodes       = copy.deepcopy(state["nodes"])
        self.lines       = copy.deepcopy(state["lines"])
        self.supports    = copy.deepcopy(state["supports"])
        self.loads       = copy.deepcopy(state["loads"])
        self.node_id_seq = state["node_seq"]
        self.line_id_seq = state["line_seq"]
        self.pending_line_start = None
        self.analysis_result    = None
        self._redraw()

    def undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(self._cur_state())
        self._restore(self._undo_stack.pop())
        self._refresh_undo_btns()

    def redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(self._cur_state())
        self._restore(self._redo_stack.pop())
        self._refresh_undo_btns()

    def _cur_state(self):
        return {
            "nodes":    copy.deepcopy(self.nodes),
            "lines":    copy.deepcopy(self.lines),
            "supports": copy.deepcopy(self.supports),
            "loads":    copy.deepcopy(self.loads),
            "node_seq": self.node_id_seq,
            "line_seq": self.line_id_seq,
        }

    def _refresh_undo_btns(self):
        if not hasattr(self, "btn_undo"):
            return
        self.btn_undo.config(
            state="normal" if self._undo_stack else "disabled",
            fg=TXT if self._undo_stack else DIS)
        self.btn_redo.config(
            state="normal" if self._redo_stack else "disabled",
            fg=TXT if self._redo_stack else DIS)

    # ════════════════════════════════════════════════════════
    #  저장 / 불러오기  (.2dd = JSON)
    # ════════════════════════════════════════════════════════
    def save_file(self):
        """현재 모든 샘플을 .2dd 파일로 저장"""
        # 현재 편집 중인 샘플 먼저 저장
        cur = self.sel_sample.get()
        if 0 <= cur < len(self.samples):
            self._save_to_sample(cur)

        if not self.samples:
            messagebox.showinfo("안내", "저장할 내용이 없습니다.", parent=self.win)
            return

        path = filedialog.asksaveasfilename(
            parent=self.win,
            title="저장",
            defaultextension=".2dd",
            filetypes=[("2D Design File", "*.2dd"), ("모든 파일", "*.*")],
        )
        if not path:
            return

        data = {
            "version":    "1.0",
            "username":   self.user,
            "samples":    self.samples,
            "sel_sample": self.sel_sample.get(),
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("저장 완료",
                                f"저장되었습니다.\n{os.path.basename(path)}",
                                parent=self.win)
        except Exception as e:
            messagebox.showerror("저장 오류", str(e), parent=self.win)

    def load_file(self):
        """저장된 .2dd 파일 불러오기"""
        path = filedialog.askopenfilename(
            parent=self.win,
            title="불러오기",
            filetypes=[("2D Design File", "*.2dd"), ("모든 파일", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("불러오기 오류", str(e), parent=self.win)
            return

        self.samples = data.get("samples", [])
        sel          = data.get("sel_sample", 0)

        # 기존 캔버스 초기화
        self._clear_canvas_data()
        self.sel_sample.set(-1)
        self._refresh_list()

        if self.samples:
            self._on_select_sample(max(0, min(sel, len(self.samples)-1)))

        messagebox.showinfo("불러오기 완료",
                            f"불러왔습니다.\n{os.path.basename(path)}",
                            parent=self.win)

    # ════════════════════════════════════════════════════════
    #  UI 구성
    # ════════════════════════════════════════════════════════
    def _build(self):
        win = self.win
        hdr = tk.Frame(win, bg=BG2, height=52)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="✏️  2D Design",
                 font=("Malgun Gothic", 14, "bold"),
                 bg=BG2, fg=WHI).pack(side="left", padx=20)
        if self.user:
            tk.Label(hdr, text=f"  ({self.user})",
                     font=("Malgun Gothic", 9),
                     bg=BG2, fg=TX2).pack(side="left")

        # ── 저장 / 불러오기 버튼 (헤더 오른쪽) ──
        tk.Button(hdr, text="💾 저장", command=self.save_file,
                  font=("Malgun Gothic", 9, "bold"),
                  bg=GRN, fg=WHI, relief="flat", cursor="hand2",
                  padx=12, pady=4).pack(side="right", padx=6, pady=10)
        tk.Button(hdr, text="📂 불러오기", command=self.load_file,
                  font=("Malgun Gothic", 9, "bold"),
                  bg=BG3, fg=TXT, relief="flat", cursor="hand2",
                  padx=12, pady=4).pack(side="right", padx=2, pady=10)

        tk.Frame(win, bg=BDR, height=1).pack(fill="x")

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True)
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        self._build_toolbar(left)
        self._build_canvas(left)
        self._build_status(left)
        self._build_list_panel(body)

    def _build_toolbar(self, parent):
        bar = tk.Frame(parent, bg=BG3, height=50)
        bar.pack(fill="x"); bar.pack_propagate(False)

        def tb_btn(text, cmd, bg=BG3, fg=TXT, state="normal"):
            b = tk.Button(bar, text=text, command=cmd,
                          font=("Malgun Gothic", 9, "bold"),
                          bg=bg, fg=fg, relief="flat",
                          cursor="hand2", padx=10, pady=6,
                          state=state, disabledforeground=DIS)
            b.pack(side="left", padx=(4, 0), pady=6)
            _bg = bg
            b.bind("<Enter>", lambda _, w=b: w.config(bg=BG5)
                              if str(w["state"]) == "normal" else None)
            b.bind("<Leave>", lambda _, w=b, bg_=_bg: w.config(bg=bg_)
                              if str(w["state"]) == "normal" else None)
            return b

        def sep():
            tk.Frame(bar, bg=BDR, width=1).pack(
                side="left", fill="y", padx=5, pady=8)

        self.btn_node    = tb_btn("Node",    self._toggle_node_popup)
        self.btn_support = tb_btn("Support", self._toggle_support_popup)
        self.btn_load    = tb_btn("Load",    self._toggle_load_popup)
        sep()
        self.btn_undo = tb_btn("◀ 이전",    self.undo,
                               state="disabled", fg=DIS)
        self.btn_redo = tb_btn("▶ 앞으로",  self.redo,
                               state="disabled", fg=DIS)
        sep()

        btn_ana = tk.Button(bar, text="  Analysis  ",
                            command=self._run_analysis,
                            font=("Malgun Gothic", 10, "bold"),
                            bg=YEL, fg="#1a1a00",
                            relief="flat", cursor="hand2", pady=6)
        btn_ana.pack(side="left", padx=6, pady=8)
        btn_ana.bind("<Enter>", lambda _: btn_ana.config(bg="#fcd34d"))
        btn_ana.bind("<Leave>", lambda _: btn_ana.config(bg=YEL))
        sep()

        tk.Label(bar, text="View:", font=("Malgun Gothic", 8),
                 bg=BG3, fg=TX2).pack(side="left")
        self.btn_line_view = tk.Button(
            bar, text="Line View",
            command=lambda: self._set_view("line"),
            font=("Malgun Gothic", 8, "bold"),
            bg=ACC, fg=WHI, relief="flat", cursor="hand2",
            padx=8, pady=6)
        self.btn_line_view.pack(side="left", padx=(4, 0), pady=8)
        self.btn_plan_view = tk.Button(
            bar, text="Plan View",
            command=lambda: messagebox.showinfo(
                "준비 중", "Plan View는 다음 버전에 추가됩니다.", parent=self.win),
            font=("Malgun Gothic", 8), state="disabled",
            bg=BG4, fg=DIS, relief="flat", padx=8, pady=6)
        self.btn_plan_view.pack(side="left", padx=(4, 0), pady=8)
        sep()

        tk.Label(bar, text="Result:", font=("Malgun Gothic", 8),
                 bg=BG3, fg=TX2).pack(side="left")
        for code, label, color in [("none", "원형", TXT),
                                   ("M",    "Moment",     MOM_COLOR),
                                   ("V",    "Shear",      SHEAR_COLOR),
                                   ("D",    "Deflection", DEFL_COLOR)]:
            b = tk.Button(bar, text=label,
                          command=lambda c=code: self._set_result(c),
                          font=("Malgun Gothic", 8),
                          bg=BG4, fg=color,
                          relief="flat", cursor="hand2", padx=8, pady=6)
            b.pack(side="left", padx=(2, 0), pady=8)
            b.bind("<Enter>", lambda _, w=b: w.config(bg=BG5))
            b.bind("<Leave>", lambda _, w=b: w.config(bg=BG4))

        self.mode_label = tk.Label(bar, text="모드: 선택없음",
                                   font=("Malgun Gothic", 8),
                                   bg=BG3, fg=CYN)
        self.mode_label.pack(side="right", padx=14)

        self._mode_buttons = {
            "node":    self.btn_node,
            "support": self.btn_support,
            "load":    self.btn_load,
        }

    def _build_canvas(self, parent):
        cf = tk.Frame(parent, bg=CANV_BG)
        cf.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(cf, bg=CANV_BG,
                                highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

    def _build_status(self, parent):
        sf = tk.Frame(parent, bg=BG2, height=28)
        sf.pack(fill="x"); sf.pack_propagate(False)
        self.coord_var = tk.StringVar(value="X: 0.0,  Y: 0.0")
        tk.Label(sf, textvariable=self.coord_var,
                 font=("Consolas", 9), bg=BG2, fg=TX2).pack(side="left", padx=14)
        tk.Label(sf, text="Unit : mm ,  kN   |   치수 클릭 → 길이 수정   |   하중 더블클릭 → 값 수정",
                 font=("Consolas", 8), bg=BG2, fg=TX3).pack(side="right", padx=14)

    def _build_list_panel(self, parent):
        rp = tk.Frame(parent, bg=BG2, width=200)
        rp.pack(side="right", fill="y"); rp.pack_propagate(False)
        tk.Frame(rp, bg=BDR, width=1).pack(side="left", fill="y")
        inner = tk.Frame(rp, bg=BG2)
        inner.pack(fill="both", expand=True, padx=1)

        hdr = tk.Frame(inner, bg=BG3); hdr.pack(fill="x")
        tk.Label(hdr, text="List", font=("Malgun Gothic", 9, "bold"),
                 bg=BG3, fg=TXT, width=8).pack(side="left", pady=8)
        tk.Button(hdr, text="ADD", command=self._add_sample,
                  font=("Malgun Gothic", 9, "bold"),
                  bg=ACC, fg=WHI, relief="flat",
                  cursor="hand2", padx=10, pady=4).pack(side="right", padx=6, pady=4)

        ch = tk.Frame(inner, bg=BG3); ch.pack(fill="x")
        tk.Label(ch, text="Name", font=("Malgun Gothic", 8),
                 bg=BG3, fg=TX2, width=8).pack(side="left",  padx=6)
        tk.Label(ch, text="View", font=("Malgun Gothic", 8),
                 bg=BG3, fg=TX2, width=6).pack(side="right", padx=6)
        tk.Frame(inner, bg=BDR, height=1).pack(fill="x")

        self.list_container = tk.Frame(inner, bg=BG2)
        self.list_container.pack(fill="both", expand=True)

        tk.Frame(inner, bg=BDR, height=1).pack(fill="x", side="bottom")
        tk.Button(inner, text="삭제", command=self._del_sample,
                  font=("Malgun Gothic", 8), bg=BG3, fg=RED,
                  relief="flat", cursor="hand2",
                  pady=4).pack(fill="x", side="bottom", padx=6, pady=4)

    # ════════════════════════════════════════════════════════
    #  샘플 관리
    # ════════════════════════════════════════════════════════
    def _add_sample(self):
        idx  = len(self.samples)
        name = f"Sample{idx + 1}"
        init_nodes = [{"id": 1, "x": 0.0, "y": 0.0, "cx": 0.0, "cy": 0.0}]
        self.samples.append({
            "name":     name,
            "view":     "Line",
            "nodes":    init_nodes,
            "lines":    [],
            "supports": {},
            "loads":    [],
            "node_seq": 1,
            "line_seq": 0,
        })
        self._refresh_list()
        self._on_select_sample(idx)

    def _del_sample(self):
        idx = self.sel_sample.get()
        if 0 <= idx < len(self.samples):
            self.samples.pop(idx)
            self._clear_canvas_data()
            self.sel_sample.set(-1)
            self._refresh_list()
            self._redraw()

    def _refresh_list(self):
        for w in self.list_container.winfo_children():
            w.destroy()
        for i, s in enumerate(self.samples):
            sel    = (self.sel_sample.get() == i)
            row_bg = BG4 if sel else BG2
            row = tk.Frame(self.list_container, bg=row_bg, cursor="hand2")
            row.pack(fill="x")
            tk.Label(row, text=s["name"], font=("Malgun Gothic", 9),
                     bg=row_bg, fg=WHI if sel else TXT,
                     width=8, anchor="w").pack(side="left", padx=6, pady=5)
            tk.Label(row, text=s["view"], font=("Malgun Gothic", 8),
                     bg=row_bg, fg=CYN, width=6).pack(side="right", padx=6)
            row.bind("<Button-1>", lambda _, i=i: self._on_select_sample(i))
            for ch in row.winfo_children():
                ch.bind("<Button-1>", lambda _, i=i: self._on_select_sample(i))

    def _on_select_sample(self, idx):
        cur = self.sel_sample.get()
        if 0 <= cur < len(self.samples):
            self._save_to_sample(cur)
        self.sel_sample.set(idx)
        self._refresh_list()
        self._load_from_sample(idx)

    def _save_to_sample(self, idx):
        s = self.samples[idx]
        s["nodes"]    = copy.deepcopy(self.nodes)
        s["lines"]    = copy.deepcopy(self.lines)
        s["supports"] = copy.deepcopy(self.supports)
        s["loads"]    = copy.deepcopy(self.loads)
        s["node_seq"] = self.node_id_seq
        s["line_seq"] = self.line_id_seq

    def _load_from_sample(self, idx):
        s = self.samples[idx]
        self.nodes       = copy.deepcopy(s["nodes"])
        self.lines       = copy.deepcopy(s["lines"])
        self.supports    = copy.deepcopy(s["supports"])
        self.loads       = copy.deepcopy(s["loads"])
        self.node_id_seq = s["node_seq"]
        self.line_id_seq = s["line_seq"]
        self.pending_line_start = None
        self.load_src_node      = None
        self.analysis_result    = None
        self.result_type.set("none")
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._refresh_undo_btns()
        self._redraw()

    def _clear_canvas_data(self):
        self.nodes       = []
        self.lines       = []
        self.supports    = {}
        self.loads       = []
        self.node_id_seq = 0
        self.line_id_seq = 0
        self.pending_line_start = None
        self.load_src_node      = None
        self.analysis_result    = None
        self._undo_stack.clear()
        self._redo_stack.clear()

    # ════════════════════════════════════════════════════════
    #  캔버스 바인딩
    # ════════════════════════════════════════════════════════
    def _bind_canvas(self):
        c = self.canvas
        c.bind("<Configure>",       self._on_resize)
        c.bind("<Motion>",          self._on_motion)
        c.bind("<Button-1>",        self._on_click)
        c.bind("<B1-Motion>",       self._on_b1_motion)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<Double-Button-1>", self._on_dbl_click)
        c.bind("<Button-3>",        self._on_rclick)
        c.bind("<MouseWheel>",      self._on_wheel)
        c.bind("<Button-4>",        self._on_wheel)
        c.bind("<Button-5>",        self._on_wheel)
        c.bind("<ButtonPress-2>",   self._pan_start)
        c.bind("<B2-Motion>",       self._pan_move)
        self.win.bind("<Control-z>", lambda _: self.undo())
        self.win.bind("<Control-y>", lambda _: self.redo())

    def _pan_start(self, e):
        self._pan_origin       = (e.x, e.y)
        self._pan_offset_start = list(self.offset)

    def _pan_move(self, e):
        if self._pan_origin:
            self.offset[0] = self._pan_offset_start[0] + (e.x - self._pan_origin[0])
            self.offset[1] = self._pan_offset_start[1] + (e.y - self._pan_origin[1])
            self._redraw()

    def _on_wheel(self, e):
        factor = 1.1 if (e.delta > 0 or e.num == 4) else 0.9
        self.scale = max(0.01, min(self.scale * factor, 5.0))
        self._redraw()

    def _on_resize(self, _):
        self._redraw()

    def _on_motion(self, e):
        self._mouse_cx = e.x
        self._mouse_cy = e.y
        wx, wy = self._c2w(e.x, e.y)
        self.coord_var.set(f"X: {wx:.1f},  Y: {wy:.1f}")

        if self._drag_node is not None:
            return

        if (self.mode.get() == "node"
                and self.node_sub_mode.get() == "line"
                and self.pending_line_start):
            self._redraw()
            snap = self._snap_node(e.x, e.y,
                                   exclude=self.pending_line_start["id"])
            tx, ty = (snap["cx"], snap["cy"]) if snap else (e.x, e.y)
            self.canvas.create_line(
                self.pending_line_start["cx"],
                self.pending_line_start["cy"],
                tx, ty,
                fill=LINE_COLOR, width=2, dash=(6, 3), tags="preview")
            # 실시간 치수
            wx2 = snap["x"] if snap else round(((e.x - self.offset[0]) / self.scale) / 10) * 10
            wx1 = self.pending_line_start["x"]
            L   = abs(wx2 - wx1)
            mx2 = (self.pending_line_start["cx"] + tx) / 2
            my2 = (self.pending_line_start["cy"] + ty) / 2 - 20
            self.canvas.create_text(
                mx2, my2, text=f"{L:.0f} mm",
                fill=YEL, font=("Malgun Gothic", 9, "bold"),
                tags="preview")

    # ── 드래그 ──────────────────────────────────────────────
    def _on_b1_motion(self, e):
        if self._drag_node is not None:
            wx = round(((e.x - self.offset[0]) / self.scale) / 10) * 10
            self._drag_node["x"]  = wx
            self._drag_node["cx"] = e.x
            self._drag_node["cy"] = e.y
            self._redraw()

    def _on_release(self, e):
        if self._drag_node is not None:
            wx = round(((e.x - self.offset[0]) / self.scale) / 10) * 10
            self._drag_node["x"] = wx
            self._update_node_canvas_coords()
            self.analysis_result = None
            self.result_type.set("none")
            self._snapshot()
            self._redraw()
        self._drag_node = None

    # ── 클릭 ────────────────────────────────────────────────
    def _on_click(self, e):
        if self.sel_sample.get() < 0:
            messagebox.showinfo("안내",
                "먼저 오른쪽 ADD 버튼으로 항목을 추가하세요.",
                parent=self.win)
            return

        mode = self.mode.get()

        if mode == "none":
            # ① 치수 클릭 감지
            for l in self.lines:
                dpos = self._dim_label_pos(l)
                if dpos and _dist((e.x, e.y), dpos) < 20:
                    self._edit_dim(l)
                    return
            # 노드 드래그
            snap = self._snap_node(e.x, e.y)
            if snap:
                self._drag_node = snap
            return

        if   mode == "node":    self._handle_node(e)
        elif mode == "support": self._handle_support(e)
        elif mode == "load":    self._handle_load(e)

    # ── 더블클릭: 하중값 수정 ───────────────────────────────
    def _on_dbl_click(self, e):
        for idx, ld in enumerate(self.loads):
            lx, ly = self._load_label_pos(ld)
            if lx is None:
                continue
            if _dist((e.x, e.y), (lx, ly)) < 26:
                self._edit_load(idx)
                return

    def _on_rclick(self, _):
        self.pending_line_start = None
        self.load_src_node      = None
        self.mode.set("none")
        self._update_mode_ui()
        self._redraw()

    # ════════════════════════════════════════════════════════
    #  ① 치수 편집
    # ════════════════════════════════════════════════════════
    def _dim_label_pos(self, line):
        """선의 치수 레이블 캔버스 위치 반환"""
        n1 = next((n for n in self.nodes if n["id"] == line["n1"]), None)
        n2 = next((n for n in self.nodes if n["id"] == line["n2"]), None)
        if not n1 or not n2:
            return None
        mx = (n1["cx"] + n2["cx"]) / 2
        my = (n1["cy"] + n2["cy"]) / 2 - 18
        return mx, my

    def _edit_dim(self, line):
        """치수 클릭 → 길이 입력 → n2 노드 x 갱신"""
        n1 = next((n for n in self.nodes if n["id"] == line["n1"]), None)
        n2 = next((n for n in self.nodes if n["id"] == line["n2"]), None)
        if not n1 or not n2:
            return
        cur_L = abs(n2["x"] - n1["x"])
        new_L = simpledialog.askfloat(
            "치수 수정",
            f"현재 길이: {cur_L:.0f} mm\n새 길이 입력 (mm):",
            initialvalue=cur_L,
            minvalue=1.0,
            parent=self.win)
        if new_L is None:
            return
        self._snapshot()
        # n1 기준으로 n2 위치 재설정
        direction = 1 if n2["x"] >= n1["x"] else -1
        n2["x"] = n1["x"] + direction * new_L
        self.analysis_result = None
        self.result_type.set("none")
        self._redraw()

    # ════════════════════════════════════════════════════════
    #  팝업 메뉴
    # ════════════════════════════════════════════════════════
    def _make_popup(self, anchor_btn):
        popup = tk.Toplevel(self.win)
        popup.overrideredirect(True)
        popup.configure(bg=BG3)
        x = anchor_btn.winfo_rootx()
        y = anchor_btn.winfo_rooty() + anchor_btn.winfo_height()
        popup.geometry(f"+{x}+{y}")
        popup.bind("<FocusOut>", lambda _: popup.destroy())
        popup.focus_set()
        return popup

    def _toggle_node_popup(self):
        popup = self._make_popup(self.btn_node)
        for sub, label, ok in [("point","Point",True),
                                ("line", "Line",  True),
                                ("plan", "Plan",  False)]:
            b = tk.Button(popup, text=label,
                          command=lambda s=sub, p=popup: self._pick_node(s, p),
                          font=("Malgun Gothic", 9),
                          bg=BG3, fg=TXT if ok else DIS,
                          relief="flat",
                          cursor="hand2" if ok else "arrow",
                          state="normal" if ok else "disabled",
                          width=10, pady=6)
            b.pack(fill="x", padx=2, pady=1)
            b.bind("<Enter>", lambda _, w=b:
                w.config(bg=BG5) if str(w["state"]) == "normal" else None)
            b.bind("<Leave>", lambda _, w=b:
                w.config(bg=BG3) if str(w["state"]) == "normal" else None)

    def _pick_node(self, sub, popup):
        popup.destroy()
        self.mode.set("node")
        self.node_sub_mode.set(sub)
        self.pending_line_start = None
        self._update_mode_ui()

    def _toggle_support_popup(self):
        popup = self._make_popup(self.btn_support)
        for stype, label in [("fix","Fix"),("pin","Pin"),("semi","SemiFix")]:
            b = tk.Button(popup, text=label,
                          command=lambda s=stype, p=popup: self._pick_support(s, p),
                          font=("Malgun Gothic", 9),
                          bg=BG3, fg=TXT,
                          relief="flat", cursor="hand2",
                          width=10, pady=6)
            b.pack(fill="x", padx=2, pady=1)
            b.bind("<Enter>", lambda _, w=b: w.config(bg=BG5))
            b.bind("<Leave>", lambda _, w=b: w.config(bg=BG3))

    def _pick_support(self, stype, popup):
        popup.destroy()
        if stype == "semi":
            # 고정율 입력 (0.0 ~ 1.0)
            from tkinter import simpledialog
            ratio = simpledialog.askfloat(
                "SemiFix 고정율",
                "회전 고정율을 입력하세요\n"
                "  0.0 = 핀(자유 회전)\n"
                "  1.0 = 완전 고정\n"
                "  예) 0.5 = 50% 고정",
                initialvalue=0.5,
                minvalue=0.0,
                maxvalue=1.0,
                parent=self.win)
            if ratio is None:
                return
            self._semi_ratio = round(ratio, 3)
        self.mode.set("support")
        self.support_type.set(stype)
        self._update_mode_ui()

    def _toggle_load_popup(self):
        popup = self._make_popup(self.btn_load)
        for ltype, label in [("point", "집중하중 (Node)"),
                              ("dist",  "분포하중 (Dist)")]:
            b = tk.Button(popup, text=label,
                          command=lambda t=ltype, p=popup: self._pick_load(t, p),
                          font=("Malgun Gothic", 9),
                          bg=BG3, fg=LOAD_COLOR,
                          relief="flat", cursor="hand2",
                          width=18, pady=6)
            b.pack(fill="x", padx=2, pady=1)
            b.bind("<Enter>", lambda _, w=b: w.config(bg=BG5))
            b.bind("<Leave>", lambda _, w=b: w.config(bg=BG3))

    def _pick_load(self, ltype, popup):
        popup.destroy()
        self._load_sub = ltype
        self.mode.set("load")
        self._update_mode_ui()

    # ── 모드 UI ──────────────────────────────────────────────
    def _set_view(self, vtype):
        self.view_type.set(vtype)
        self._redraw()

    def _set_result(self, code):
        self.result_type.set(code)
        self._redraw()

    def _update_mode_ui(self):
        mode  = self.mode.get()
        sub   = self.node_sub_mode.get()
        stype = self.support_type.get()
        lsub  = getattr(self, "_load_sub", "point")
        labels = {
            "none":    "모드: 선택없음  ·  드래그=노드이동  ·  치수클릭=길이수정",
            "node":    f"모드: Node ({sub})",
            "support": f"모드: Support ({stype})",
            "load":    f"모드: Load ({'집중(Node)' if lsub=='point' else '분포(Dist)'})  · 하중 더블클릭=값수정",
        }
        self.mode_label.config(text=labels.get(mode, ""))
        for m, btn in self._mode_buttons.items():
            btn.config(bg=ACC if m == mode else BG3,
                       fg=WHI if m == mode else TXT)

    # ════════════════════════════════════════════════════════
    #  클릭 핸들러
    # ════════════════════════════════════════════════════════
    def _handle_node(self, e):
        sub = self.node_sub_mode.get()
        if sub == "point":
            snap = self._snap_node(e.x, e.y)
            if snap:
                return   # 이미 노드 있음 → 무시
            wx = round(((e.x - self.offset[0]) / self.scale) / 10) * 10
            # ── 선 위에 클릭했는지 확인 → 선 분리 ──────────
            hit_line = self._snap_line(e.x, e.y, tol=12)
            self._snapshot()
            nid = self._new_node(wx, 0)
            new_node = next(n for n in self.nodes if n["id"] == nid)
            if hit_line:
                # 기존 선(n1-n2) 제거 후 n1-new, new-n2 두 선으로 분리
                orig_n1 = hit_line["n1"]
                orig_n2 = hit_line["n2"]
                self.lines = [l for l in self.lines if l["id"] != hit_line["id"]]
                # 분리된 하중도 새 선 ID 에 맞게 유지 (line id 는 새로 발급)
                self.line_id_seq += 1
                self.lines.append({"id": self.line_id_seq,
                                   "n1": orig_n1, "n2": nid})
                self.line_id_seq += 1
                self.lines.append({"id": self.line_id_seq,
                                   "n1": nid, "n2": orig_n2})
            self._redraw()

        elif sub == "line":
            snap = self._snap_node(e.x, e.y)
            if snap is None:
                wx = round(((e.x - self.offset[0]) / self.scale) / 10) * 10
                if self.pending_line_start is None:
                    self._snapshot()
                nid  = self._new_node(wx, 0)
                snap = next(n for n in self.nodes if n["id"] == nid)

            if self.pending_line_start is None:
                self.pending_line_start = snap
            else:
                n1 = self.pending_line_start
                n2 = snap
                if n1["id"] != n2["id"]:
                    exists = any(
                        (l["n1"] == n1["id"] and l["n2"] == n2["id"]) or
                        (l["n1"] == n2["id"] and l["n2"] == n1["id"])
                        for l in self.lines)
                    if not exists:
                        self._snapshot()
                        self.line_id_seq += 1
                        self.lines.append({"id": self.line_id_seq,
                                           "n1": n1["id"], "n2": n2["id"]})
                self.pending_line_start = snap
            self._redraw()

    def _handle_support(self, e):
        snap = self._snap_node(e.x, e.y)
        if snap is None:
            messagebox.showinfo("안내", "노드 위를 클릭하세요.", parent=self.win)
            return
        self._snapshot()
        stype = self.support_type.get()
        if stype == "semi":
            ratio = getattr(self, "_semi_ratio", 0.5)
            self.supports[snap["id"]] = {"type": "semi", "ratio": ratio}
        else:
            self.supports[snap["id"]] = stype
        self._redraw()

    def _handle_load(self, e):
        lsub = getattr(self, "_load_sub", "point")
        if lsub == "point":
            snap = self._snap_node(e.x, e.y)
            if snap is None:
                messagebox.showinfo("안내", "노드 위를 클릭하세요.", parent=self.win)
                return
            # 같은 노드에 이미 집중하중이 있으면 수정 모드로 전환
            existing_idx = next(
                (i for i, ld in enumerate(self.loads)
                 if ld["type"] == "point" and ld["nid"] == snap["id"]),
                None)
            if existing_idx is not None:
                self._edit_load(existing_idx)
                return
            dlg = LoadInputDlg(self.win, title="집중하중 입력",
                               fields=[("Fy (kN,  ↑양수 / ↓음수)", "10"),
                                       ("Mz (kN·m, ↺양수)", "0")])
            self.win.wait_window(dlg)
            if dlg.result:
                self._snapshot()
                self.loads.append({
                    "type": "point",
                    "nid":  snap["id"],
                    "Fy":   float(dlg.result[0]),   # kN
                    "Mz":   float(dlg.result[1]),   # kN·m
                })
                self._redraw()
        else:
            line = self._snap_line(e.x, e.y)
            if line is None:
                messagebox.showinfo("안내", "선(부재) 위를 클릭하세요.", parent=self.win)
                return
            dlg = LoadInputDlg(self.win, title="분포하중 입력",
                               fields=[("w (kN/m,  ↓양수)", "10")])
            self.win.wait_window(dlg)
            if dlg.result:
                self._snapshot()
                self.loads.append({
                    "type": "dist",
                    "lid":  line["id"],
                    "w":    float(dlg.result[0]),   # kN/m
                })
                self._redraw()

    # ── 하중 레이블 위치 + 수정 ─────────────────────────────
    def _load_label_pos(self, ld):
        """하중 레이블의 실제 캔버스 위치 반환 (더블클릭 감지용)"""
        if ld["type"] == "point":
            node = next((n for n in self.nodes if n["id"] == ld["nid"]), None)
            if not node:
                return None, None
            Fy = ld["Fy"]
            # Fy >= 0: 위쪽 화살표 → 레이블은 노드 위
            # Fy <  0: 아래쪽 화살표 → 레이블은 노드 아래
            # _draw_loads 와 반드시 동일한 수식 사용
            sign = 1 if Fy >= 0 else -1
            return node["cx"] + 8, node["cy"] - 24 * sign
        elif ld["type"] == "dist":
            line = next((l for l in self.lines if l["id"] == ld["lid"]), None)
            if not line:
                return None, None
            n1 = next((n for n in self.nodes if n["id"] == line["n1"]), None)
            n2 = next((n for n in self.nodes if n["id"] == line["n2"]), None)
            if not n1 or not n2:
                return None, None
            return (n1["cx"]+n2["cx"])/2, (n1["cy"]+n2["cy"])/2 - 50
        return None, None

    def _edit_load(self, idx):
        ld = self.loads[idx]
        if ld["type"] == "point":
            dlg = LoadInputDlg(self.win, title="집중하중 수정",
                               fields=[("Fy (kN)", str(ld["Fy"])),
                                       ("Mz (kN·m)", str(ld.get("Mz", 0)))])
            self.win.wait_window(dlg)
            if dlg.result:
                self._snapshot()
                ld["Fy"] = float(dlg.result[0])
                ld["Mz"] = float(dlg.result[1])
                self._redraw()
        else:
            dlg = LoadInputDlg(self.win, title="분포하중 수정",
                               fields=[("w (kN/m)", str(ld["w"]))])
            self.win.wait_window(dlg)
            if dlg.result:
                self._snapshot()
                ld["w"] = float(dlg.result[0])
                self._redraw()

    # ════════════════════════════════════════════════════════
    #  노드 헬퍼
    # ════════════════════════════════════════════════════════
    def _new_node(self, wx, wy):
        self.node_id_seq += 1
        nid = self.node_id_seq
        cx, cy = self._w2c(wx, wy)
        self.nodes.append({"id": nid, "x": float(wx), "y": float(wy),
                           "cx": cx, "cy": cy})
        return nid

    def _snap_node(self, cx, cy, tol=SNAP_DIST, exclude=None):
        best, bd = None, tol
        for n in self.nodes:
            if exclude is not None and n["id"] == exclude:
                continue
            d = _dist((cx, cy), (n["cx"], n["cy"]))
            if d < bd:
                bd = d; best = n
        return best

    def _snap_line(self, cx, cy, tol=10):
        for l in self.lines:
            n1 = next((n for n in self.nodes if n["id"] == l["n1"]), None)
            n2 = next((n for n in self.nodes if n["id"] == l["n2"]), None)
            if n1 and n2 and _pt_on_seg(cx, cy,
                                         n1["cx"], n1["cy"],
                                         n2["cx"], n2["cy"], tol):
                return l
        return None

    def _w2c(self, wx, wy):
        return (wx * self.scale + self.offset[0],
                -wy * self.scale + self.offset[1])

    def _c2w(self, cx, cy):
        return ((cx - self.offset[0]) / self.scale,
                -(cy - self.offset[1]) / self.scale)

    def _update_node_canvas_coords(self):
        for n in self.nodes:
            n["cx"], n["cy"] = self._w2c(n["x"], n["y"])

    # ════════════════════════════════════════════════════════
    #  ② Analysis — 단위 변환 수정
    # ════════════════════════════════════════════════════════
    def _run_analysis(self):
        if not self.nodes:
            messagebox.showwarning("경고", "노드가 없습니다.", parent=self.win); return
        if not self.lines:
            messagebox.showwarning("경고", "선(부재)이 없습니다.", parent=self.win); return
        if not self.supports:
            messagebox.showwarning("경고", "Support를 최소 1개 이상 입력하세요.",
                                   parent=self.win); return

        # 기본 단면: H250×125, A36
        E = 205000.0   # MPa (= N/mm²)
        I = 4050e4     # mm⁴
        A = 6340.0     # mm²

        node_list = [(n["id"], float(n["x"])) for n in self.nodes]
        elem_list = [(l["id"], l["n1"], l["n2"], E, I, A) for l in self.lines]

        load_list = []
        for ld in self.loads:
            if ld["type"] == "point":
                Fy_N    = float(ld["Fy"]) * 1000.0        # kN → N
                Mz_Nmm  = float(ld.get("Mz", 0)) * 1e6   # kN·m → N·mm
                load_list.append(("point", ld["nid"], Fy_N, Mz_Nmm))
            elif ld["type"] == "dist":
                load_list.append(("dist", ld["lid"], float(ld["w"])))  # kN/m 그대로

        # supports 정규화: semi 는 {"type","ratio"} → analyzer 에 ratio 전달
        supports_norm = {}
        for nid, sval in self.supports.items():
            if isinstance(sval, dict):
                supports_norm[nid] = sval
            else:
                supports_norm[nid] = sval
        analyzer = BeamAnalyzer(node_list, elem_list, supports_norm, load_list)
        result   = analyzer.solve()
        if result is None:
            messagebox.showerror(
                "해석 오류",
                "구조 해석에 실패했습니다.\n\n"
                "- Support 조건을 확인하세요 (최소 1개의 수직 구속 필요)\n"
                "- 모든 노드가 연결되어 있는지 확인하세요",
                parent=self.win)
            return

        self.analysis_result = result
        self.result_type.set("M")
        self._redraw()
        ResultWindow(self.win, result, self.nodes, self.lines)

    # ════════════════════════════════════════════════════════
    #  그리기
    # ════════════════════════════════════════════════════════
    def _redraw(self):
        self._update_node_canvas_coords()
        c = self.canvas
        c.delete("all")
        self._draw_grid()
        self._draw_lines()
        self._draw_supports()
        self._draw_loads()
        self._draw_result_diagram()
        self._draw_nodes()
        self._draw_dimensions()

    def _draw_grid(self):
        c   = self.canvas
        W   = c.winfo_width()  or 800
        H   = c.winfo_height() or 600
        gmm = 1000
        xs  = int((0 - self.offset[0]) / (self.scale * gmm)) - 1
        xe  = int((W - self.offset[0]) / (self.scale * gmm)) + 2
        for ix in range(xs, xe + 1):
            px = ix * gmm * self.scale + self.offset[0]
            c.create_line(px, 0, px, H, fill=GRID_COLOR, width=1)
        ys = int((self.offset[1] - H) / (self.scale * gmm)) - 1
        ye = int(self.offset[1]       / (self.scale * gmm)) + 2
        for iy in range(ys, ye + 1):
            py = -iy * gmm * self.scale + self.offset[1]
            c.create_line(0, py, W, py, fill=GRID_COLOR, width=1)
        ox, oy = self._w2c(0, 0)
        c.create_line(0,  oy, W, oy, fill="#2a3550", width=1)
        c.create_line(ox, 0,  ox, H,  fill="#2a3550", width=1)

    def _draw_lines(self):
        for l in self.lines:
            n1 = next((n for n in self.nodes if n["id"] == l["n1"]), None)
            n2 = next((n for n in self.nodes if n["id"] == l["n2"]), None)
            if n1 and n2:
                self.canvas.create_line(
                    n1["cx"], n1["cy"], n2["cx"], n2["cy"],
                    fill=LINE_COLOR, width=3, tags="line")

    def _draw_nodes(self):
        r = 6
        for n in self.nodes:
            cx, cy = n["cx"], n["cy"]
            col = SEL_COLOR if n["id"] in self.supports else NODE_COLOR
            self.canvas.create_oval(cx-r, cy-r, cx+r, cy+r,
                                    fill=col, outline=WHI, width=1)
            self.canvas.create_text(cx + 10, cy - 10,
                                    text=f"N{n['id']}",
                                    fill=TX2, font=("Consolas", 8))

    def _draw_supports(self):
        for nid, sval in self.supports.items():
            node = next((n for n in self.nodes if n["id"] == nid), None)
            if not node: continue
            cx, cy = node["cx"], node["cy"]
            stype  = sval["type"] if isinstance(sval, dict) else sval
            if   stype == "pin":  self._draw_pin(cx, cy)
            elif stype == "fix":  self._draw_fix(cx, cy)
            elif stype == "semi":
                ratio = sval["ratio"] if isinstance(sval, dict) else 0.5
                self._draw_semi(cx, cy, ratio)

    def _draw_pin(self, cx, cy):
        s = 14
        pts = [cx, cy+2, cx-s, cy+s*1.5, cx+s, cy+s*1.5]
        self.canvas.create_polygon(pts, fill=PIN_COLOR, outline=WHI, width=1)
        self.canvas.create_line(cx-s-3, cy+s*1.5, cx+s+3, cy+s*1.5,
                                fill=PIN_COLOR, width=2)

    def _draw_fix(self, cx, cy):
        s = 14
        self.canvas.create_rectangle(cx-s, cy+2, cx+s, cy+s*2,
                                     fill=FIX_COLOR, outline=WHI, width=1)
        for i in range(-2, 4):
            self.canvas.create_line(cx-s+i*6, cy+s*2,
                                    cx-s+i*6-6, cy+s*2+8,
                                    fill=FIX_COLOR, width=1)

    def _draw_semi(self, cx, cy, ratio=0.5):
        s = 14
        pts = [cx, cy+2, cx-s, cy+s*1.5, cx+s, cy+s*1.5]
        self.canvas.create_polygon(pts, fill=SEMI_COLOR, outline=WHI, width=1)
        self.canvas.create_arc(cx-s, cy+s*1.5-4, cx+s, cy+s*1.5+4,
                               start=0, extent=180,
                               style="arc", outline=WHI, width=1)
        # 고정율 레이블
        self.canvas.create_text(cx, cy + s*1.5 + 10,
                                text=f"η={ratio:.2f}",
                                fill=SEMI_COLOR,
                                font=("Malgun Gothic", 7, "bold"))

    def _draw_loads(self):
        c = self.canvas
        for ld in self.loads:
            if ld["type"] == "point":
                node = next((n for n in self.nodes if n["id"] == ld["nid"]), None)
                if not node: continue
                cx, cy = node["cx"], node["cy"]
                Fy   = ld["Fy"]
                sign = 1 if Fy >= 0 else -1
                # 화살표
                c.create_line(cx, cy - 42*sign, cx, cy - 8*sign,
                              fill=LOAD_COLOR, width=2,
                              arrow="last", arrowshape=(10, 12, 4))
                lx, ly = cx + 8, cy - 24 * sign
                c.create_text(lx, ly,
                              text=f"{abs(Fy):.1f} kN",
                              fill=LOAD_COLOR,
                              font=("Malgun Gothic", 8, "bold"),
                              anchor="w", tags="load_label")
                c.create_text(lx, ly + 13,
                              text="✎",
                              fill=TX3, font=("Malgun Gothic", 8),
                              anchor="w", tags="load_hint")

            elif ld["type"] == "dist":
                line = next((l for l in self.lines if l["id"] == ld["lid"]), None)
                if not line: continue
                n1 = next((n for n in self.nodes if n["id"] == line["n1"]), None)
                n2 = next((n for n in self.nodes if n["id"] == line["n2"]), None)
                if not n1 or not n2: continue
                total_px = _dist((n1["cx"], n1["cy"]),
                                  (n2["cx"], n2["cy"]))
                n_arr = max(2, int(total_px // 40))
                for k in range(n_arr + 1):
                    t  = k / n_arr
                    ax = _lerp(n1["cx"], n2["cx"], t)
                    ay = _lerp(n1["cy"], n2["cy"], t)
                    c.create_line(ax, ay-36, ax, ay-2,
                                  fill=LOAD_COLOR, width=1,
                                  arrow="last", arrowshape=(8, 10, 3))
                c.create_line(n1["cx"], n1["cy"]-36,
                              n2["cx"], n2["cy"]-36,
                              fill=LOAD_COLOR, width=2)
                lx, ly = (n1["cx"]+n2["cx"])/2, (n1["cy"]+n2["cy"])/2 - 50
                c.create_text(lx, ly,
                              text=f"{ld['w']:.1f} kN/m",
                              fill=LOAD_COLOR,
                              font=("Malgun Gothic", 8, "bold"),
                              tags="load_label")
                c.create_text(lx, ly + 13,
                              text="✎",
                              fill=TX3, font=("Malgun Gothic", 8),
                              tags="load_hint")

    def _draw_result_diagram(self):
        rtype = self.result_type.get()
        if rtype == "none" or self.analysis_result is None:
            return
        c      = self.canvas
        colors = {"M": MOM_COLOR, "V": SHEAR_COLOR, "D": DEFL_COLOR}
        color  = colors[rtype]

        # ── 전체 최대값으로 공통 스케일 산출 ──────────────────
        global_max = max(
            (max(abs(v) for v in res[rtype]) if res[rtype] else 0)
            for res in self.analysis_result.values()
        )
        if global_max < 1e-9:
            return
        # 다이어그램 최대 높이 px (부재 방향 수직)
        DIAG_PX   = 70
        auto_scale = DIAG_PX / global_max

        for eid, res in self.analysis_result.items():
            line = next((l for l in self.lines if l["id"] == eid), None)
            if not line: continue
            n1 = next((n for n in self.nodes if n["id"] == line["n1"]), None)
            n2 = next((n for n in self.nodes if n["id"] == line["n2"]), None)
            if not n1 or not n2: continue

            vals = res[rtype]
            xs_m = res["x"]
            L_mm = res["L"]
            if not vals or L_mm < 1e-9:
                continue

            # 부재 수직 방향 단위 벡터 (위쪽)
            dx = n2["cx"] - n1["cx"]
            dy = n2["cy"] - n1["cy"]
            ln = _dist((dx, dy), (0, 0)) or 1
            nx, ny = -dy / ln, dx / ln   # 수직 방향 (좌표계 위쪽)

            # 기준선(부재) 위 꼭짓점 목록
            poly_top  = []
            base_pts  = []
            for k, v in enumerate(vals):
                t  = xs_m[k] / L_mm
                bx = _lerp(n1["cx"], n2["cx"], t)
                by = _lerp(n1["cy"], n2["cy"], t)
                base_pts.extend([bx, by])
                poly_top.extend([bx + nx * v * auto_scale,
                                  by + ny * v * auto_scale])

            # 닫힌 폴리곤: 상단 경로 + 기준선 역방향
            fill_pts = poly_top + list(reversed(base_pts))
            if len(fill_pts) >= 6:
                c.create_polygon(fill_pts, fill=color,
                                 stipple="gray25", outline="",
                                 tags="result")
                c.create_line(*poly_top, fill=color, width=2,
                              smooth=True, tags="result")
                # 양 끝 수직선 (baseline과 연결)
                c.create_line(base_pts[0], base_pts[1],
                              poly_top[0], poly_top[1],
                              fill=color, width=1, tags="result")
                c.create_line(base_pts[-2], base_pts[-1],
                              poly_top[-2], poly_top[-1],
                              fill=color, width=1, tags="result")

            # 최대값 레이블 (부재 위 수직 방향으로 오프셋)
            mi  = max(range(len(vals)), key=lambda i: abs(vals[i]))
            t   = xs_m[mi] / L_mm
            bx  = _lerp(n1["cx"], n2["cx"], t)
            by  = _lerp(n1["cy"], n2["cy"], t)
            # 레이블은 다이어그램 꼭대기 바깥쪽
            offset_px = auto_scale * abs(vals[mi]) + 14
            lx = bx + nx * offset_px * (1 if vals[mi] >= 0 else -1)
            ly = by + ny * offset_px * (1 if vals[mi] >= 0 else -1)
            unit = "kN·m" if rtype == "M" else ("kN" if rtype == "V" else "mm")
            c.create_text(lx, ly,
                          text=f"{vals[mi]:.2f} {unit}",
                          fill=color, font=("Malgun Gothic", 8, "bold"),
                          tags="result")

    def _draw_dimensions(self):
        """치수 표시 — 클릭 가능하도록 강조"""
        c = self.canvas
        for l in self.lines:
            n1 = next((n for n in self.nodes if n["id"] == l["n1"]), None)
            n2 = next((n for n in self.nodes if n["id"] == l["n2"]), None)
            if not n1 or not n2: continue
            L_mm = abs(n2["x"] - n1["x"])
            if L_mm < 1: continue
            mx = (n1["cx"] + n2["cx"]) / 2
            my = (n1["cy"] + n2["cy"]) / 2 - 18

            # 클릭 유도 배경 박스
            c.create_rectangle(mx - 26, my - 9, mx + 26, my + 9,
                                fill="#1e293b", outline=YEL,
                                width=1, tags="dim_box")
            c.create_text(mx, my,
                          text=str(int(L_mm)),
                          fill=YEL, font=("Malgun Gothic", 8, "bold"),
                          tags="dim_text")
            # 치수선
            c.create_line(n1["cx"], n1["cy"]-14, n2["cx"], n2["cy"]-14,
                          fill=TX3, width=1)
            c.create_line(n1["cx"], n1["cy"]-10, n1["cx"], n1["cy"]-18,
                          fill=TX3, width=1)
            c.create_line(n2["cx"], n2["cy"]-10, n2["cx"], n2["cy"]-18,
                          fill=TX3, width=1)
