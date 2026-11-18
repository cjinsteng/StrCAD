"""
design_2d/plan_view.py
Plan View 2D Design — 평면도 기반 구조 설계 모듈
(Line View와 별도 — 슬래브/기둥 배치 중심)
"""

import tkinter as tk
from tkinter import messagebox
from .constants import (
    BG, BG2, BG3, BG4, BG5, BDR, BDR2,
    ACC, ACCH, GRN, RED, YEL, CYN, BLU, PRP,
    TXT, TX2, TX3, WHI, DIS,
    CANV_BG, GRID_COLOR, NODE_COLOR, LINE_COLOR,
    RC_COLOR, STEEL_COLOR,
)

TITLE_FONT = ("Malgun Gothic", 13, "bold")
LBL_FONT   = ("Malgun Gothic", 9)
BTN_FONT   = ("Malgun Gothic", 9, "bold")


class PlanViewPanel:
    """
    Plan View 2D Design Panel
    ─────────────────────────
    평면도(Top View) 기반 구조 설계 모듈.
    - XY 평면에 기둥·보·슬래브 배치
    - 스팬 자동 분할 및 면하중 → 선하중 환산
    - Line View(panel.py)와 별도 저장 포맷 (.2dp)
    """

    def __init__(self, win, username=""):
        self.win      = win
        self.username = username

        # ── 상태 ──────────────────────────────────────────
        self.nodes   = []   # {"id":int, "x":float, "y":float, "cx":int, "cy":int}
        self.columns = []   # {"id":int, "nid":int, "b":float, "h":float}
        self.beams   = []   # {"id":int, "n1":int, "n2":int, "material":str}
        self.slabs   = []   # {"id":int, "nodes":[nid,...], "t":float}
        self.loads   = []   # {"type":"area"/"line"/"point", ...}

        self.node_id_seq = 0
        self.col_id_seq  = 0
        self.beam_id_seq = 0

        self.scale  = 1.0    # px/mm 환산
        self.offset = [80, 80]

        self.mode = tk.StringVar(value="none")

        self._build()

    # ════════════════════════════════════════════════════════
    #  UI 빌드
    # ════════════════════════════════════════════════════════
    def _build(self):
        win = self.win

        # ── 헤더 ────────────────────────────────────────────
        hdr = tk.Frame(win, bg=BG2, height=48)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="🏗  Plan View  —  2D Structural Design",
                 font=TITLE_FONT, bg=BG2, fg=WHI).pack(side="left", padx=18)
        tk.Label(hdr, text=f"User: {self.username}" if self.username else "",
                 font=LBL_FONT, bg=BG2, fg=TX3).pack(side="right", padx=18)
        tk.Frame(win, bg=BDR, height=1).pack(fill="x")

        # ── 툴바 ────────────────────────────────────────────
        tb = tk.Frame(win, bg=BG3, height=42)
        tb.pack(fill="x"); tb.pack_propagate(False)

        def tb_btn(text, cmd, fg=TXT, **kw):
            b = tk.Button(tb, text=text, command=cmd,
                          font=("Malgun Gothic", 8, "bold"),
                          bg=BG3, fg=fg, relief="flat", cursor="hand2",
                          padx=10, pady=5, **kw)
            b.pack(side="left", padx=2, pady=4)
            b.bind("<Enter>", lambda _, w=b: w.config(bg=BG5))
            b.bind("<Leave>", lambda _, w=b: w.config(bg=BG3))
            return b

        def sep():
            tk.Frame(tb, bg=BDR, width=1).pack(
                side="left", fill="y", padx=4, pady=6)

        tb_btn("Grid",    self._toggle_grid,  fg=TX2)
        sep()
        tb_btn("Column",  self._mode_column,  fg=RC_COLOR)
        tb_btn("Beam",    self._mode_beam,    fg=STEEL_COLOR)
        tb_btn("Slab",    self._mode_slab,    fg=CYN)
        sep()
        tb_btn("Load",    self._mode_load,    fg=YEL)
        sep()
        tb_btn("▶ Analysis", self._run_analysis, fg=GRN)
        sep()
        tb_btn("💾 저장",  self._save_file,  fg=WHI)
        tb_btn("📂 열기",  self._load_file,  fg=TX2)

        # ── 모드 레이블 ──────────────────────────────────────
        self.mode_label = tk.Label(win,
            text="모드: 선택없음",
            font=("Malgun Gothic", 8), bg=BG4, fg=TX2,
            anchor="w", padx=12, pady=3)
        self.mode_label.pack(fill="x")
        tk.Frame(win, bg=BDR, height=1).pack(fill="x")

        # ── 메인 영역: 캔버스 + 우측 속성 패널 ─────────────
        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True)

        # 캔버스
        self.canvas = tk.Canvas(body, bg=CANV_BG,
                                highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)

        # 우측 속성 패널
        rp = tk.Frame(body, bg=BG2, width=260)
        rp.pack(side="right", fill="y"); rp.pack_propagate(False)
        tk.Frame(body, bg=BDR, width=1).pack(side="right", fill="y")
        self._build_prop_panel(rp)

        # ── 캔버스 이벤트 ────────────────────────────────────
        self.canvas.bind("<Configure>",    lambda _: self._redraw())
        self.canvas.bind("<Button-1>",     self._on_click)
        self.canvas.bind("<Button-3>",     self._on_rclick)
        self.canvas.bind("<MouseWheel>",   self._on_wheel)
        self.canvas.bind("<B2-Motion>",    self._on_pan)
        self.canvas.bind("<ButtonPress-2>",self._pan_start)

        self._pan_origin = None
        self._show_grid  = True

        self._redraw()

    def _build_prop_panel(self, parent):
        """우측 속성 패널 (선택 요소 속성 편집)"""
        tk.Label(parent, text="■ 속성",
                 font=("Malgun Gothic", 9, "bold"),
                 bg=BG2, fg=ACC, padx=12, pady=8).pack(fill="x")
        tk.Frame(parent, bg=BDR, height=1).pack(fill="x")

        self._prop_lbl = tk.Label(parent,
            text="요소를 클릭하면\n속성이 표시됩니다.",
            font=LBL_FONT, bg=BG2, fg=TX3,
            justify="center", pady=20)
        self._prop_lbl.pack(fill="x")

        tk.Frame(parent, bg=BDR, height=1).pack(fill="x", pady=(20, 0))
        tk.Label(parent, text="■ 범례",
                 font=("Malgun Gothic", 9, "bold"),
                 bg=BG2, fg=ACC, padx=12, pady=6).pack(fill="x")

        for color, label in [(RC_COLOR,    "기둥 (Column) RC"),
                              (STEEL_COLOR, "보  (Beam) Steel"),
                              (CYN,         "슬래브 (Slab)"),
                              (YEL,         "하중 (Load)")]:
            f = tk.Frame(parent, bg=BG2)
            f.pack(fill="x", padx=14, pady=2)
            tk.Canvas(f, bg=BG2, width=16, height=16,
                      highlightthickness=0).pack(side="left")
            tk.Label(f, text="●", font=("Malgun Gothic", 10),
                     bg=BG2, fg=color).pack(side="left")
            tk.Label(f, text=label, font=("Malgun Gothic", 8),
                     bg=BG2, fg=TX2).pack(side="left", padx=4)

        # ── 안내 ─────────────────────────────────────────────
        tk.Frame(parent, bg=BDR, height=1).pack(fill="x", pady=(20, 0))
        info = (
            "■ 사용법\n\n"
            "Column: 기둥 배치\n"
            "Beam: 보 연결\n"
            "Slab: 슬래브 영역\n"
            "Load: 면하중 입력\n\n"
            "휠: 줌  |  미들드래그: 이동\n"
            "우클릭: 모드 해제"
        )
        tk.Label(parent, text=info,
                 font=("Malgun Gothic", 8), bg=BG2, fg=TX3,
                 justify="left", padx=14, pady=8).pack(fill="x")

    # ════════════════════════════════════════════════════════
    #  모드 전환
    # ════════════════════════════════════════════════════════
    def _mode_column(self):
        self.mode.set("column")
        self.mode_label.config(text="모드: Column 배치  ─  캔버스 클릭으로 기둥 추가")

    def _mode_beam(self):
        self.mode.set("beam")
        self._beam_start = None
        self.mode_label.config(text="모드: Beam 연결  ─  첫 번째 기둥 클릭 → 두 번째 기둥 클릭")

    def _mode_slab(self):
        self.mode.set("slab")
        self.mode_label.config(text="모드: Slab  ─  기둥 3개 이상 클릭 → 우클릭으로 완성")

    def _mode_load(self):
        self.mode.set("load")
        self.mode_label.config(text="모드: Load  ─  슬래브 영역 클릭으로 면하중 입력")

    def _toggle_grid(self):
        self._show_grid = not self._show_grid
        self._redraw()

    # ════════════════════════════════════════════════════════
    #  캔버스 이벤트
    # ════════════════════════════════════════════════════════
    def _on_click(self, e):
        mode = self.mode.get()
        if mode == "column":
            self._add_column(e.x, e.y)
        elif mode == "beam":
            self._handle_beam(e.x, e.y)
        elif mode == "slab":
            self._handle_slab(e.x, e.y)

    def _on_rclick(self, e):
        self.mode.set("none")
        self._beam_start = None
        self.mode_label.config(text="모드: 선택없음")
        self._redraw()

    def _on_wheel(self, e):
        factor = 1.1 if e.delta > 0 else 0.9
        self.scale = max(0.05, min(20.0, self.scale * factor))
        self._redraw()

    def _pan_start(self, e):
        self._pan_origin = (e.x, e.y)

    def _on_pan(self, e):
        if self._pan_origin:
            dx = e.x - self._pan_origin[0]
            dy = e.y - self._pan_origin[1]
            self.offset[0] += dx
            self.offset[1] += dy
            self._pan_origin = (e.x, e.y)
            self._redraw()

    # ════════════════════════════════════════════════════════
    #  좌표 변환
    # ════════════════════════════════════════════════════════
    def _w2c(self, wx, wy):
        """월드(mm) → 캔버스(px)"""
        return (int(wx * self.scale + self.offset[0]),
                int(-wy * self.scale + self.offset[1]))

    def _c2w(self, cx, cy):
        """캔버스(px) → 월드(mm) (그리드 스냅 포함)"""
        wx = (cx - self.offset[0]) / self.scale
        wy = -(cy - self.offset[1]) / self.scale
        snap = 500  # 500mm 그리드 스냅
        wx = round(wx / snap) * snap
        wy = round(wy / snap) * snap
        return wx, wy

    # ════════════════════════════════════════════════════════
    #  요소 추가
    # ════════════════════════════════════════════════════════
    def _add_column(self, cx, cy):
        wx, wy = self._c2w(cx, cy)
        # 같은 위치 중복 방지
        for n in self.nodes:
            if abs(n["x"] - wx) < 250 and abs(n["y"] - wy) < 250:
                return
        self.node_id_seq += 1
        self.col_id_seq  += 1
        nid = self.node_id_seq
        self.nodes.append({"id": nid, "x": wx, "y": wy})
        self.columns.append({"id": self.col_id_seq, "nid": nid,
                              "b": 500, "h": 500})
        self._redraw()

    def _handle_beam(self, cx, cy):
        nid = self._snap_node(cx, cy)
        if nid is None:
            messagebox.showinfo("안내", "기둥 위를 클릭하세요.", parent=self.win)
            return
        if not hasattr(self, "_beam_start") or self._beam_start is None:
            self._beam_start = nid
            self.mode_label.config(
                text=f"모드: Beam 연결  ─  두 번째 기둥 클릭 (시작 N{nid})")
        else:
            if self._beam_start != nid:
                self.beam_id_seq += 1
                self.beams.append({"id": self.beam_id_seq,
                                   "n1": self._beam_start, "n2": nid,
                                   "material": "RC"})
            self._beam_start = None
            self.mode_label.config(
                text="모드: Beam 연결  ─  첫 번째 기둥 클릭")
        self._redraw()

    def _handle_slab(self, cx, cy):
        pass  # TODO: polygon slab selection

    def _snap_node(self, cx, cy, tol=20):
        """캔버스 좌표 근처의 노드 ID 반환"""
        for n in self.nodes:
            px, py = self._w2c(n["x"], n["y"])
            if abs(cx - px) <= tol and abs(cy - py) <= tol:
                return n["id"]
        return None

    # ════════════════════════════════════════════════════════
    #  그리기
    # ════════════════════════════════════════════════════════
    def _redraw(self):
        c = self.canvas
        c.delete("all")
        W = c.winfo_width()  or 900
        H = c.winfo_height() or 600

        # 배경
        c.create_rectangle(0, 0, W, H, fill=CANV_BG, outline="")

        # 그리드 (500mm 간격)
        if self._show_grid:
            self._draw_grid(c, W, H)

        # 좌표축
        ox, oy = self.offset
        c.create_line(ox, 0, ox, H, fill="#1e3050", width=1)
        c.create_line(0, oy, W, oy, fill="#1e3050", width=1)
        c.create_text(ox + 8, oy - 8, text="0", fill=TX3,
                      font=("Malgun Gothic", 7))

        # 보 (Beam)
        for bm in self.beams:
            n1 = next((n for n in self.nodes if n["id"] == bm["n1"]), None)
            n2 = next((n for n in self.nodes if n["id"] == bm["n2"]), None)
            if not n1 or not n2: continue
            x1, y1 = self._w2c(n1["x"], n1["y"])
            x2, y2 = self._w2c(n2["x"], n2["y"])
            color = STEEL_COLOR if bm.get("material") == "STEEL" else RC_COLOR
            c.create_line(x1, y1, x2, y2, fill=color, width=3)

        # 기둥 (Column)
        col_size = max(6, int(500 * self.scale / 1000 * 12))
        for col in self.columns:
            n = next((nd for nd in self.nodes if nd["id"] == col["nid"]), None)
            if not n: continue
            cx2, cy2 = self._w2c(n["x"], n["y"])
            s = col_size
            c.create_rectangle(cx2-s, cy2-s, cx2+s, cy2+s,
                                fill=RC_COLOR, outline=WHI, width=1)
            c.create_text(cx2, cy2+s+10,
                          text=f"N{n['id']}",
                          fill=TX2, font=("Malgun Gothic", 7))

        # Beam 시작점 표시
        if hasattr(self, "_beam_start") and self._beam_start:
            n = next((nd for nd in self.nodes if nd["id"] == self._beam_start), None)
            if n:
                px, py = self._w2c(n["x"], n["y"])
                c.create_oval(px-12, py-12, px+12, py+12,
                              outline=YEL, width=2)

        # 스케일 표시
        c.create_text(W - 10, H - 10,
                      text=f"Scale: 1:{int(1000/max(self.scale,0.01)):.0f}  |  Plan View",
                      fill=TX3, font=("Malgun Gothic", 7), anchor="se")

    def _draw_grid(self, c, W, H):
        GRID_MM = 1000  # 1m 그리드
        px_step = GRID_MM * self.scale
        if px_step < 8:
            return
        # 세로선
        x0 = self.offset[0] % px_step
        while x0 < W:
            c.create_line(x0, 0, x0, H, fill=GRID_COLOR, width=1)
            x0 += px_step
        # 가로선
        y0 = self.offset[1] % px_step
        while y0 < H:
            c.create_line(0, y0, W, y0, fill=GRID_COLOR, width=1)
            y0 += px_step

    # ════════════════════════════════════════════════════════
    #  해석 / 저장 / 열기 (스텁)
    # ════════════════════════════════════════════════════════
    def _run_analysis(self):
        messagebox.showinfo(
            "Plan View 해석",
            "Plan View 해석 기능은 현재 개발 중입니다.\n\n"
            "보 → 선하중 환산 → Line View 연계 해석 예정.",
            parent=self.win)

    def _save_file(self):
        import json
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            parent=self.win,
            title="Plan View 저장 (.2dp)",
            defaultextension=".2dp",
            filetypes=[("2D Plan File", "*.2dp"), ("모든 파일", "*.*")],
        )
        if not path: return
        data = {
            "version":  "1.0",
            "view":     "plan",
            "nodes":    self.nodes,
            "columns":  self.columns,
            "beams":    self.beams,
            "slabs":    self.slabs,
            "loads":    self.loads,
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("저장 완료", f"저장됨: {path}", parent=self.win)
        except Exception as ex:
            messagebox.showerror("저장 오류", str(ex), parent=self.win)

    def _load_file(self):
        import json
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            parent=self.win,
            title="Plan View 열기 (.2dp)",
            filetypes=[("2D Plan File", "*.2dp"), ("모든 파일", "*.*")],
        )
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.nodes   = data.get("nodes",   [])
            self.columns = data.get("columns", [])
            self.beams   = data.get("beams",   [])
            self.slabs   = data.get("slabs",   [])
            self.loads   = data.get("loads",   [])
            # ID 시퀀스 재설정
            self.node_id_seq = max((n["id"] for n in self.nodes), default=0)
            self.col_id_seq  = max((c["id"] for c in self.columns), default=0)
            self.beam_id_seq = max((b["id"] for b in self.beams), default=0)
            self._redraw()
            messagebox.showinfo("열기 완료", f"로드됨: {path}", parent=self.win)
        except Exception as ex:
            messagebox.showerror("열기 오류", str(ex), parent=self.win)
