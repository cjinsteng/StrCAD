"""
design_2d/panel.py
메인 2D Design 패널 — 캔버스 드로잉 + 툴바
"""

import tkinter as tk
from tkinter import messagebox
import math

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
    """
    외부에서 호출:
        from design_2d.panel import Design2DPanel
        Design2DPanel(win, username="admin")
    """

    def __init__(self, win, username=""):
        self.win  = win
        self.user = username

        # ── 샘플 목록 ────────────────────────────────────
        self.samples    = []           # [{"name", "view", "nodes","lines","supports","loads"}]
        self.sel_sample = tk.IntVar(value=-1)

        # ── 현재 캔버스 상태 ─────────────────────────────
        self.nodes    = []   # [{"id","x","y","cx","cy"}]
        self.lines    = []   # [{"id","n1","n2"}]
        self.supports = {}   # {node_id: "pin"|"fix"|"semi"}
        self.loads    = []   # [{"type","nid"/"lid","Fy"/"w",...}]

        self.node_id_seq = 0
        self.line_id_seq = 0

        # ── 모드 ─────────────────────────────────────────
        self.mode          = tk.StringVar(value="none")
        self.node_sub_mode = tk.StringVar(value="point")
        self.support_type  = tk.StringVar(value="pin")
        self._load_sub     = "point"

        self.pending_line_start = None   # Line 그리기 임시 시작 노드
        self.load_src_node      = None   # Load 첫 번째 노드

        # ── 뷰 / 결과 ────────────────────────────────────
        self.view_type      = tk.StringVar(value="line")
        self.result_type    = tk.StringVar(value="none")
        self.analysis_result = None

        # ── 캔버스 변환 ──────────────────────────────────
        self.scale  = 0.12      # mm → px
        self.offset = [400, 300]

        # 팬
        self._pan_origin       = None
        self._pan_offset_start = None

        self._build()
        self._bind_canvas()

    # ════════════════════════════════════════════════════════
    #  UI 구성
    # ════════════════════════════════════════════════════════
    def _build(self):
        win = self.win

        # 헤더
        hdr = tk.Frame(win, bg=BG2, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="✏️  2D Design",
                 font=("Malgun Gothic", 14, "bold"),
                 bg=BG2, fg=WHI).pack(side="left", padx=20)
        if self.user:
            tk.Label(hdr, text=f"  ({self.user})",
                     font=("Malgun Gothic", 9),
                     bg=BG2, fg=TX2).pack(side="left")
        tk.Frame(win, bg=BDR, height=1).pack(fill="x")

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True)

        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        self._build_toolbar(left)
        self._build_canvas(left)
        self._build_status(left)
        self._build_list_panel(body)

    # ── 툴바 ────────────────────────────────────────────────
    def _build_toolbar(self, parent):
        bar = tk.Frame(parent, bg=BG3, height=50)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        def tb_btn(text, cmd, bg=BG3, fg=TXT):
            b = tk.Button(bar, text=text, command=cmd,
                          font=("Malgun Gothic", 9, "bold"),
                          bg=bg, fg=fg, relief="flat",
                          cursor="hand2", padx=12, pady=6)
            b.pack(side="left", padx=(6, 0), pady=6)
            b.bind("<Enter>", lambda _: b.config(bg=BG5))
            b.bind("<Leave>", lambda _: b.config(bg=bg))
            return b

        def sep():
            tk.Frame(bar, bg=BDR, width=1).pack(
                side="left", fill="y", padx=8, pady=8)

        self.btn_node    = tb_btn("Node",    self._toggle_node_popup)
        self.btn_support = tb_btn("Support", self._toggle_support_popup)
        self.btn_load    = tb_btn("Load",    self._toggle_load_popup)
        sep()

        # Analysis 버튼
        btn_ana = tk.Button(bar, text="  Analysis  ",
                            command=self._run_analysis,
                            font=("Malgun Gothic", 10, "bold"),
                            bg=YEL, fg="#1a1a00",
                            relief="flat", cursor="hand2", pady=6)
        btn_ana.pack(side="left", padx=6, pady=8)
        btn_ana.bind("<Enter>", lambda _: btn_ana.config(bg="#fcd34d"))
        btn_ana.bind("<Leave>", lambda _: btn_ana.config(bg=YEL))
        sep()

        # View 토글
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

        # Result 탭 버튼
        tk.Label(bar, text="Result:", font=("Malgun Gothic", 8),
                 bg=BG3, fg=TX2).pack(side="left")
        for code, label, color in [("none", "원형", TXT),
                                   ("M",    "Moment",    MOM_COLOR),
                                   ("V",    "Shear",     SHEAR_COLOR),
                                   ("D",    "Deflection",DEFL_COLOR)]:
            b = tk.Button(bar, text=label,
                          command=lambda c=code: self._set_result(c),
                          font=("Malgun Gothic", 8),
                          bg=BG4, fg=color,
                          relief="flat", cursor="hand2", padx=8, pady=6)
            b.pack(side="left", padx=(2, 0), pady=8)
            b.bind("<Enter>", lambda _, btn=b: btn.config(bg=BG5))
            b.bind("<Leave>", lambda _, btn=b: btn.config(bg=BG4))

        # 모드 표시
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
        sf.pack(fill="x")
        sf.pack_propagate(False)
        self.coord_var = tk.StringVar(value="X: 0.0,  Y: 0.0")
        tk.Label(sf, textvariable=self.coord_var,
                 font=("Consolas", 9), bg=BG2, fg=TX2).pack(side="left", padx=14)
        tk.Label(sf, text="Unit : mm ,  kN",
                 font=("Consolas", 9), bg=BG2, fg=TX2).pack(side="right", padx=14)

    # ── 오른쪽 리스트 패널 ───────────────────────────────────
    def _build_list_panel(self, parent):
        rp = tk.Frame(parent, bg=BG2, width=200)
        rp.pack(side="right", fill="y")
        rp.pack_propagate(False)
        tk.Frame(rp, bg=BDR, width=1).pack(side="left", fill="y")

        inner = tk.Frame(rp, bg=BG2)
        inner.pack(fill="both", expand=True, padx=1)

        # 헤더 행
        hdr = tk.Frame(inner, bg=BG3)
        hdr.pack(fill="x")
        tk.Label(hdr, text="List", font=("Malgun Gothic", 9, "bold"),
                 bg=BG3, fg=TXT, width=8).pack(side="left", pady=8)
        tk.Button(hdr, text="ADD", command=self._add_sample,
                  font=("Malgun Gothic", 9, "bold"),
                  bg=ACC, fg=WHI, relief="flat",
                  cursor="hand2", padx=10, pady=4).pack(side="right", padx=6, pady=4)

        # 컬럼 헤더
        ch = tk.Frame(inner, bg=BG3)
        ch.pack(fill="x")
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
    #  샘플 목록 관리
    # ════════════════════════════════════════════════════════
    def _add_sample(self):
        idx  = len(self.samples)
        name = f"Sample{idx + 1}"
        self.samples.append({
            "name": name, "view": "Line",
            "nodes": [], "lines": [],
            "supports": {}, "loads": [],
            "node_seq": 0, "line_seq": 0,
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
            sel   = (self.sel_sample.get() == i)
            row_bg = BG4 if sel else BG2
            row = tk.Frame(self.list_container, bg=row_bg, cursor="hand2")
            row.pack(fill="x")
            tk.Label(row, text=s["name"], font=("Malgun Gothic", 9),
                     bg=row_bg, fg=WHI if sel else TXT,
                     width=8, anchor="w").pack(side="left", padx=6, pady=5)
            tk.Label(row, text=s["view"], font=("Malgun Gothic", 8),
                     bg=row_bg, fg=CYN,
                     width=6).pack(side="right", padx=6)
            row.bind("<Button-1>", lambda _, idx=i: self._on_select_sample(idx))
            for ch in row.winfo_children():
                ch.bind("<Button-1>", lambda _, idx=i: self._on_select_sample(idx))

    def _on_select_sample(self, idx):
        # 현재 편집 내용 저장
        cur = self.sel_sample.get()
        if 0 <= cur < len(self.samples):
            self._save_to_sample(cur)
        self.sel_sample.set(idx)
        self._refresh_list()
        self._load_from_sample(idx)

    def _save_to_sample(self, idx):
        s = self.samples[idx]
        s["nodes"]    = list(self.nodes)
        s["lines"]    = list(self.lines)
        s["supports"] = dict(self.supports)
        s["loads"]    = list(self.loads)
        s["node_seq"] = self.node_id_seq
        s["line_seq"] = self.line_id_seq

    def _load_from_sample(self, idx):
        s = self.samples[idx]
        self.nodes        = list(s["nodes"])
        self.lines        = list(s["lines"])
        self.supports     = dict(s["supports"])
        self.loads        = list(s["loads"])
        self.node_id_seq  = s["node_seq"]
        self.line_id_seq  = s["line_seq"]
        self.pending_line_start = None
        self.load_src_node      = None
        self.analysis_result    = None
        self.result_type.set("none")
        self._redraw()

    def _clear_canvas_data(self):
        self.nodes        = []
        self.lines        = []
        self.supports     = {}
        self.loads        = []
        self.node_id_seq  = 0
        self.line_id_seq  = 0
        self.pending_line_start = None
        self.load_src_node      = None
        self.analysis_result    = None

    # ════════════════════════════════════════════════════════
    #  캔버스 이벤트 바인딩
    # ════════════════════════════════════════════════════════
    def _bind_canvas(self):
        c = self.canvas
        c.bind("<Configure>",    self._on_resize)
        c.bind("<Motion>",       self._on_motion)
        c.bind("<Button-1>",     self._on_click)
        c.bind("<Button-3>",     self._on_rclick)
        c.bind("<MouseWheel>",   self._on_wheel)
        c.bind("<Button-4>",     self._on_wheel)
        c.bind("<Button-5>",     self._on_wheel)
        c.bind("<ButtonPress-2>",   self._pan_start)
        c.bind("<B2-Motion>",       self._pan_move)

    def _pan_start(self, e):
        self._pan_origin       = (e.x, e.y)
        self._pan_offset_start = list(self.offset)

    def _pan_move(self, e):
        if self._pan_origin:
            dx = e.x - self._pan_origin[0]
            dy = e.y - self._pan_origin[1]
            self.offset[0] = self._pan_offset_start[0] + dx
            self.offset[1] = self._pan_offset_start[1] + dy
            self._redraw()

    def _on_wheel(self, e):
        factor = 1.1 if (e.delta > 0 or e.num == 4) else 0.9
        self.scale = max(0.01, min(self.scale * factor, 5.0))
        self._redraw()

    def _on_resize(self, _):
        self._redraw()

    def _on_motion(self, e):
        wx, wy = self._c2w(e.x, e.y)
        self.coord_var.set(f"X: {wx:.1f},  Y: {wy:.1f}")
        # Line 미리보기
        if (self.mode.get() == "node"
                and self.node_sub_mode.get() == "line"
                and self.pending_line_start):
            self._redraw()
            snap = self._snap_node(e.x, e.y)
            tx, ty = (snap["cx"], snap["cy"]) if snap else (e.x, e.y)
            self.canvas.create_line(
                self.pending_line_start["cx"],
                self.pending_line_start["cy"],
                tx, ty,
                fill=LINE_COLOR, width=2, dash=(6, 3), tags="preview")

    def _on_click(self, e):
        if self.sel_sample.get() < 0:
            messagebox.showinfo("안내",
                "먼저 오른쪽 ADD 버튼으로 항목을 추가하세요.",
                parent=self.win)
            return
        mode = self.mode.get()
        if   mode == "node":    self._handle_node(e)
        elif mode == "support": self._handle_support(e)
        elif mode == "load":    self._handle_load(e)

    def _on_rclick(self, _):
        self.pending_line_start = None
        self.load_src_node      = None
        self.mode.set("none")
        self._update_mode_ui()
        self._redraw()

    # ════════════════════════════════════════════════════════
    #  팝업 메뉴 (Node / Support / Load)
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
            b.bind("<Enter>", lambda _, btn=b:
                btn.config(bg=BG5) if str(btn["state"]) == "normal" else None)
            b.bind("<Leave>", lambda _, btn=b:
                btn.config(bg=BG3) if str(btn["state"]) == "normal" else None)

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
            b.bind("<Enter>", lambda _, btn=b: btn.config(bg=BG5))
            b.bind("<Leave>", lambda _, btn=b: btn.config(bg=BG3))

    def _pick_support(self, stype, popup):
        popup.destroy()
        self.mode.set("support")
        self.support_type.set(stype)
        self._update_mode_ui()

    def _toggle_load_popup(self):
        popup = self._make_popup(self.btn_load)
        for ltype, label in [("point","집중하중 (Point)"),
                              ("dist", "분포하중 (Dist)")]:
            b = tk.Button(popup, text=label,
                          command=lambda t=ltype, p=popup: self._pick_load(t, p),
                          font=("Malgun Gothic", 9),
                          bg=BG3, fg=LOAD_COLOR,
                          relief="flat", cursor="hand2",
                          width=18, pady=6)
            b.pack(fill="x", padx=2, pady=1)
            b.bind("<Enter>", lambda _, btn=b: btn.config(bg=BG5))
            b.bind("<Leave>", lambda _, btn=b: btn.config(bg=BG3))

    def _pick_load(self, ltype, popup):
        popup.destroy()
        self._load_sub = ltype
        self.mode.set("load")
        self._update_mode_ui()

    # ── 모드 UI 업데이트 ─────────────────────────────────────
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
            "none":    "모드: 선택없음",
            "node":    f"모드: Node ({sub})",
            "support": f"모드: Support ({stype})",
            "load":    f"모드: Load ({'집중' if lsub=='point' else '분포'}하중)",
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
                return      # 이미 노드 있음
            wx, _ = self._c2w(e.x, e.y)
            wx = round(wx / 10) * 10
            self._new_node(wx, 0)
            self._redraw()

        elif sub == "line":
            snap = self._snap_node(e.x, e.y)
            if snap is None:
                wx, _ = self._c2w(e.x, e.y)
                wx = round(wx / 10) * 10
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
                        self.line_id_seq += 1
                        self.lines.append({"id": self.line_id_seq,
                                           "n1": n1["id"], "n2": n2["id"]})
                self.pending_line_start = snap   # 연속 그리기
            self._redraw()

    def _handle_support(self, e):
        snap = self._snap_node(e.x, e.y)
        if snap is None:
            messagebox.showinfo("안내", "노드 위를 클릭하세요.", parent=self.win)
            return
        self.supports[snap["id"]] = self.support_type.get()
        self._redraw()

    def _handle_load(self, e):
        lsub = getattr(self, "_load_sub", "point")
        if lsub == "point":
            snap = self._snap_node(e.x, e.y)
            if snap is None:
                messagebox.showinfo("안내", "노드 위를 클릭하세요.", parent=self.win)
                return
            dlg = LoadInputDlg(self.win, title="집중하중 입력",
                               fields=[("Fy (kN, ↑+)", "10"),
                                       ("Mz (kN·m, ↺+)", "0")])
            self.win.wait_window(dlg)
            if dlg.result:
                self.loads.append({
                    "type": "point",
                    "nid":  snap["id"],
                    "Fy":   float(dlg.result[0]),
                    "Mz":   float(dlg.result[1]),
                })
                self._redraw()
        else:   # dist
            line = self._snap_line(e.x, e.y)
            if line is None:
                messagebox.showinfo("안내", "선(부재) 위를 클릭하세요.", parent=self.win)
                return
            dlg = LoadInputDlg(self.win, title="분포하중 입력",
                               fields=[("w (kN/m, ↓+)", "10")])
            self.win.wait_window(dlg)
            if dlg.result:
                self.loads.append({
                    "type": "dist",
                    "lid":  line["id"],
                    "w":    float(dlg.result[0]),
                })
                self._redraw()

    # ════════════════════════════════════════════════════════
    #  노드 / 선 헬퍼
    # ════════════════════════════════════════════════════════
    def _new_node(self, wx, wy):
        self.node_id_seq += 1
        nid = self.node_id_seq
        cx, cy = self._w2c(wx, wy)
        self.nodes.append({"id": nid, "x": wx, "y": wy, "cx": cx, "cy": cy})
        return nid

    def _snap_node(self, cx, cy, tol=SNAP_DIST):
        best, bd = None, tol
        for n in self.nodes:
            d = _dist((cx, cy), (n["cx"], n["cy"]))
            if d < bd:
                bd = d; best = n
        return best

    def _snap_line(self, cx, cy, tol=10):
        for l in self.lines:
            n1 = next(n for n in self.nodes if n["id"] == l["n1"])
            n2 = next(n for n in self.nodes if n["id"] == l["n2"])
            if _pt_on_seg(cx, cy,
                          n1["cx"], n1["cy"],
                          n2["cx"], n2["cy"], tol):
                return l
        return None

    # ── 좌표 변환 ────────────────────────────────────────────
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
    #  Analysis 실행
    # ════════════════════════════════════════════════════════
    def _run_analysis(self):
        if not self.nodes:
            messagebox.showwarning("경고", "노드가 없습니다.", parent=self.win); return
        if not self.lines:
            messagebox.showwarning("경고", "선(부재)이 없습니다.", parent=self.win); return
        if not self.supports:
            messagebox.showwarning("경고", "Support를 최소 1개 이상 입력하세요.", parent=self.win); return

        # 기본 단면: H250×125, A36
        E = 205000   # MPa
        I = 4050e4   # mm⁴
        A = 6340     # mm²

        node_list = [(n["id"], n["x"]) for n in self.nodes]
        elem_list = [(l["id"], l["n1"], l["n2"], E, I, A) for l in self.lines]
        load_list = []
        for ld in self.loads:
            if ld["type"] == "point":
                load_list.append(
                    ("point", ld["nid"], ld["Fy"] * 1e3, ld.get("Mz", 0) * 1e6))
            elif ld["type"] == "dist":
                load_list.append(("dist", ld["lid"], ld["w"]))

        analyzer = BeamAnalyzer(node_list, elem_list, self.supports, load_list)
        result   = analyzer.solve()
        if result is None:
            messagebox.showerror(
                "오류", "구조 해석 실패.\nSupport 조건을 확인하세요.",
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
        ye = int(self.offset[1]      / (self.scale * gmm)) + 2
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
        for nid, stype in self.supports.items():
            node = next((n for n in self.nodes if n["id"] == nid), None)
            if not node:
                continue
            cx, cy = node["cx"], node["cy"]
            if   stype == "pin":  self._draw_pin(cx, cy)
            elif stype == "fix":  self._draw_fix(cx, cy)
            elif stype == "semi": self._draw_semi(cx, cy)

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

    def _draw_semi(self, cx, cy):
        s = 14
        pts = [cx, cy+2, cx-s, cy+s*1.5, cx+s, cy+s*1.5]
        self.canvas.create_polygon(pts, fill=SEMI_COLOR, outline=WHI, width=1)
        self.canvas.create_arc(cx-s, cy+s*1.5-4, cx+s, cy+s*1.5+4,
                               start=0, extent=180,
                               style="arc", outline=WHI, width=1)

    def _draw_loads(self):
        c = self.canvas
        for ld in self.loads:
            if ld["type"] == "point":
                node = next((n for n in self.nodes if n["id"] == ld["nid"]), None)
                if not node: continue
                cx, cy = node["cx"], node["cy"]
                Fy = ld["Fy"]
                sign = 1 if Fy >= 0 else -1
                c.create_line(cx, cy - 40*sign, cx, cy,
                              fill=LOAD_COLOR, width=2,
                              arrow="last", arrowshape=(10, 12, 4))
                c.create_text(cx + 6, cy - 20*sign,
                              text=f"{abs(Fy):.1f}kN",
                              fill=LOAD_COLOR, font=("Malgun Gothic", 8))
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
                    c.create_line(ax, ay-35, ax, ay,
                                  fill=LOAD_COLOR, width=1,
                                  arrow="last", arrowshape=(8, 10, 3))
                c.create_line(n1["cx"], n1["cy"]-35,
                              n2["cx"], n2["cy"]-35,
                              fill=LOAD_COLOR, width=1)
                mid_x = (n1["cx"] + n2["cx"]) / 2
                mid_y = (n1["cy"] + n2["cy"]) / 2
                c.create_text(mid_x, mid_y - 46,
                              text=f"{ld['w']:.1f}kN/m",
                              fill=LOAD_COLOR,
                              font=("Malgun Gothic", 8))

    def _draw_result_diagram(self):
        rtype = self.result_type.get()
        if rtype == "none" or self.analysis_result is None:
            return
        c      = self.canvas
        colors = {"M": MOM_COLOR, "V": SHEAR_COLOR, "D": DEFL_COLOR}
        color  = colors[rtype]

        for eid, res in self.analysis_result.items():
            line = next((l for l in self.lines if l["id"] == eid), None)
            if not line: continue
            n1 = next((n for n in self.nodes if n["id"] == line["n1"]), None)
            n2 = next((n for n in self.nodes if n["id"] == line["n2"]), None)
            if not n1 or not n2: continue

            vals  = res[rtype]
            xs_m  = res["x"]
            L_mm  = res["L"]
            max_v = max(abs(v) for v in vals) if vals else 0
            if max_v < 1e-9: continue

            diag_px   = 60
            auto_scale = diag_px / max_v
            dx = n2["cx"] - n1["cx"]
            dy = n2["cy"] - n1["cy"]
            length = _dist((dx, dy), (0, 0)) or 1
            nx, ny = -dy / length, dx / length   # 수직 벡터 (위쪽)

            poly_top = []
            for k, v in enumerate(vals):
                t  = xs_m[k] / L_mm
                lx = _lerp(n1["cx"], n2["cx"], t)
                ly = _lerp(n1["cy"], n2["cy"], t)
                poly_top.extend([lx + nx*v*auto_scale,
                                  ly + ny*v*auto_scale])

            base_pts = []
            for k in range(len(xs_m)):
                t  = xs_m[k] / L_mm
                lx = _lerp(n1["cx"], n2["cx"], t)
                ly = _lerp(n1["cy"], n2["cy"], t)
                base_pts.extend([lx, ly])

            fill_pts = poly_top + list(reversed(base_pts))
            if len(fill_pts) >= 6:
                c.create_polygon(fill_pts, fill=color,
                                 stipple="gray25", outline="", tags="result")
                c.create_line(*poly_top, fill=color, width=2,
                              smooth=True, tags="result")

            # 최대값 표시
            mi  = max(range(len(vals)), key=lambda i: abs(vals[i]))
            t   = xs_m[mi] / L_mm
            lx  = _lerp(n1["cx"], n2["cx"], t)
            ly  = _lerp(n1["cy"], n2["cy"], t)
            unit = "kN·m" if rtype == "M" else ("kN" if rtype == "V" else "mm")
            c.create_text(lx, ly - 72,
                          text=f"{vals[mi]:.2f} {unit}",
                          fill=color, font=("Malgun Gothic", 8, "bold"),
                          tags="result")

    def _draw_dimensions(self):
        c = self.canvas
        for l in self.lines:
            n1 = next((n for n in self.nodes if n["id"] == l["n1"]), None)
            n2 = next((n for n in self.nodes if n["id"] == l["n2"]), None)
            if not n1 or not n2: continue
            L_mm = abs(n2["x"] - n1["x"])
            if L_mm < 1: continue
            mx = (n1["cx"] + n2["cx"]) / 2
            my = (n1["cy"] + n2["cy"]) / 2 - 18
            c.create_text(mx, my, text=str(int(L_mm)),
                          fill=TXT, font=("Malgun Gothic", 8))
            c.create_line(n1["cx"], n1["cy"]-14, n2["cx"], n2["cy"]-14,
                          fill=TX3, width=1)
            c.create_line(n1["cx"], n1["cy"]-10, n1["cx"], n1["cy"]-18,
                          fill=TX3, width=1)
            c.create_line(n2["cx"], n2["cy"]-10, n2["cx"], n2["cy"]-18,
                          fill=TX3, width=1)
