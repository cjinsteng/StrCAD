"""
STRCAD 부재 뷰어 - tkinter 캔버스 기반
- 보 클릭 → 정보 표시
- 정보 수정 → SQLite 저장
- 프로젝트 단위 관리
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sqlite3
import json
import math
import os
from pathlib import Path
from datetime import datetime

# ── 색상 ────────────────────────────────────────────────────
BG      = "#0d1117"
BG2     = "#161b22"
BG3     = "#21262d"
ACCENT  = "#238636"
ACCENT2 = "#2ea043"
BLUE    = "#1f6feb"
RED     = "#da3633"
ORANGE  = "#e3b341"
TEXT    = "#c9d1d9"
TEXT2   = "#8b949e"
BORDER  = "#30363d"
WHITE   = "#f0f6fc"
TEAL    = "#39d353"
PURPLE  = "#8957e5"

COLOR_MAP = {"X방향": "#2196F3", "Y방향": "#F44336", "대각선": "#FF9800"}


# ════════════════════════════════════════════════════════════
#  DB 매니저
# ════════════════════════════════════════════════════════════
class BeamDB:
    """SQLite 기반 보 데이터 저장/불러오기"""

    def __init__(self, db_path: str = "strcad_data.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    name      TEXT NOT NULL,
                    dxf_path  TEXT,
                    created   TEXT,
                    updated   TEXT
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS beams (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id   INTEGER NOT NULL,
                    beam_id      TEXT,
                    beam_layer   TEXT,
                    beam_name    TEXT,
                    span_length  REAL,
                    beam_width   REAL,
                    direction    TEXT,
                    x1 REAL, y1 REAL,
                    x2 REAL, y2 REAL,
                    col_start    TEXT,
                    col_end      TEXT,
                    memo         TEXT DEFAULT '',
                    modified     INTEGER DEFAULT 0,
                    updated      TEXT,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS columns (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    x REAL, y REAL
                )
            """)

    def _conn(self):
        return sqlite3.connect(self.db_path)

    # ── 프로젝트 ──
    def create_project(self, name: str, dxf_path: str = "") -> int:
        now = datetime.now().isoformat()
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO projects (name, dxf_path, created, updated) VALUES (?,?,?,?)",
                (name, dxf_path, now, now)
            )
            return cur.lastrowid

    def list_projects(self):
        with self._conn() as c:
            return c.execute(
                "SELECT id, name, dxf_path, created FROM projects ORDER BY id DESC"
            ).fetchall()

    def delete_project(self, pid: int):
        with self._conn() as c:
            c.execute("DELETE FROM beams   WHERE project_id=?", (pid,))
            c.execute("DELETE FROM columns WHERE project_id=?", (pid,))
            c.execute("DELETE FROM projects WHERE id=?",        (pid,))

    # ── 보 저장 ──
    def save_beams(self, project_id: int, beam_data: list, column_positions: list):
        now = datetime.now().isoformat()
        with self._conn() as c:
            c.execute("DELETE FROM beams   WHERE project_id=?", (project_id,))
            c.execute("DELETE FROM columns WHERE project_id=?", (project_id,))
            for b in beam_data:
                c.execute("""
                    INSERT INTO beams
                    (project_id,beam_id,beam_layer,beam_name,span_length,
                     beam_width,direction,x1,y1,x2,y2,col_start,col_end,memo,updated)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    project_id,
                    b.get("beam_id",""),
                    b.get("beam_layer",""),
                    b.get("beam_name", b.get("beam_id","")),
                    b.get("span_length", 0),
                    b.get("beam_width", 0),
                    b.get("beam_direction",""),
                    b["start_point"][0], b["start_point"][1],
                    b["end_point"][0],   b["end_point"][1],
                    b.get("start_column","") or "",
                    b.get("end_column","")   or "",
                    b.get("memo",""),
                    now
                ))
            for cp in column_positions:
                c.execute("INSERT INTO columns (project_id,x,y) VALUES (?,?,?)",
                          (project_id, cp[0], cp[1]))
        c_upd = sqlite3.connect(self.db_path)
        c_upd.execute("UPDATE projects SET updated=? WHERE id=?", (now, project_id))
        c_upd.commit(); c_upd.close()

    def load_beams(self, project_id: int):
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM beams WHERE project_id=? ORDER BY id", (project_id,)
            ).fetchall()
            cols = c.execute(
                "SELECT x,y FROM columns WHERE project_id=?", (project_id,)
            ).fetchall()
        beams = []
        for r in rows:
            beams.append({
                "db_id": r[0], "project_id": r[1],
                "beam_id": r[2], "beam_layer": r[3], "beam_name": r[4],
                "span_length": r[5], "beam_width": r[6], "beam_direction": r[7],
                "start_point": (r[8], r[9]), "end_point": (r[10], r[11]),
                "start_column": r[12], "end_column": r[13],
                "memo": r[14] or "", "modified": r[15],
            })
        return beams, [(r[0], r[1]) for r in cols]

    def update_beam(self, db_id: int, fields: dict):
        now = datetime.now().isoformat()
        allowed = ["beam_name","span_length","beam_width","direction","memo"]
        sets  = ", ".join(f"{k}=?" for k in fields if k in allowed)
        vals  = [v for k,v in fields.items() if k in allowed]
        if not sets:
            return
        vals += [now, 1, db_id]
        with self._conn() as c:
            c.execute(f"UPDATE beams SET {sets}, updated=?, modified=? WHERE id=?", vals)


# ════════════════════════════════════════════════════════════
#  캔버스 뷰어 창
# ════════════════════════════════════════════════════════════
class BeamViewer(tk.Toplevel):
    """보 평면도 뷰어 + 수정 패널"""

    def __init__(self, parent, project_id: int, project_name: str, db: BeamDB):
        super().__init__(parent)
        self.title(f"STRCAD 뷰어  |  {project_name}")
        self.geometry("1200x720")
        self.minsize(900, 580)
        self.configure(bg=BG)

        self.project_id   = project_id
        self.project_name = project_name
        self.db           = db

        self.beam_data, self.col_positions = db.load_beams(project_id)
        self.selected  = None
        self.scale     = 1.0
        self.pan       = [0.0, 0.0]
        self._drag_start = None
        self._drag_origin = None
        self._bounds   = self._calc_bounds()

        self._build_ui()
        self._draw()

    # ── UI 구성 ──────────────────────────────────────────────
    def _build_ui(self):
        # 툴바
        tb = tk.Frame(self, bg=BG2, height=44)
        tb.pack(fill="x")
        tb.pack_propagate(False)
        tk.Label(tb, text=f"🏗  {self.project_name}",
                 font=("Consolas", 12, "bold"), bg=BG2, fg=WHITE).pack(side="left", padx=16, pady=8)

        for txt, cmd in [("🔍+", lambda: self._zoom(1.2)),
                         ("🔍−", lambda: self._zoom(1/1.2)),
                         ("⟳ 초기화", self._reset_view)]:
            tk.Button(tb, text=txt, command=cmd,
                      font=("Malgun Gothic", 9), bg=BG3, fg=TEXT,
                      relief="flat", padx=8, cursor="hand2").pack(side="left", padx=2, pady=8)

        tk.Button(tb, text="💾  저장 완료", command=self._save_all,
                  font=("Malgun Gothic", 9, "bold"), bg=ACCENT, fg=WHITE,
                  relief="flat", padx=12, cursor="hand2").pack(side="right", padx=12, pady=8)

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # 메인
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True)

        # 캔버스
        cv_frame = tk.Frame(main, bg=BG)
        cv_frame.pack(side="left", fill="both", expand=True)

        self.canvas = tk.Canvas(cv_frame, bg="#0d1117", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

        # 마우스 이벤트
        self.canvas.bind("<ButtonPress-1>",   self._on_click)
        self.canvas.bind("<B1-Motion>",        self._on_drag)
        self.canvas.bind("<ButtonRelease-1>",  self._on_release)
        self.canvas.bind("<MouseWheel>",       self._on_wheel)
        self.canvas.bind("<Configure>",        lambda e: self._draw())

        # 우측 패널
        self._build_side(main)

    def _build_side(self, parent):
        side = tk.Frame(parent, bg=BG2, width=280,
                        highlightbackground=BORDER, highlightthickness=1)
        side.pack(side="right", fill="y")
        side.pack_propagate(False)

        # 검색
        tk.Label(side, text="보 목록", font=("Malgun Gothic", 10, "bold"),
                 bg=BG2, fg=WHITE).pack(anchor="w", padx=12, pady=(12,4))

        self.search_var = tk.StringVar()
        self.search_var.trace("w", lambda *a: self._refresh_list())
        entry = tk.Entry(side, textvariable=self.search_var,
                         font=("Consolas", 10), bg=BG3, fg=TEXT,
                         insertbackground=WHITE, relief="flat",
                         highlightbackground=BORDER, highlightthickness=1)
        entry.pack(fill="x", padx=12, pady=(0,6), ipady=6)

        # 방향 필터
        self.dir_filter = tk.StringVar(value="전체")
        f_row = tk.Frame(side, bg=BG2)
        f_row.pack(fill="x", padx=12, pady=(0,8))
        for lbl, val, col in [("전체","전체","#555"),("X","X방향","#2196F3"),
                               ("Y","Y방향","#F44336"),("사선","대각선","#FF9800")]:
            b = tk.Radiobutton(f_row, text=lbl, variable=self.dir_filter, value=val,
                               command=self._refresh_list,
                               font=("Malgun Gothic", 9), bg=BG2, fg=col,
                               selectcolor=BG3, activebackground=BG2,
                               relief="flat", indicatoron=False, padx=6, pady=3)
            b.pack(side="left", padx=2)

        tk.Frame(side, bg=BORDER, height=1).pack(fill="x", padx=12)

        # 목록 리스트박스
        list_frame = tk.Frame(side, bg=BG2)
        list_frame.pack(fill="both", expand=True, padx=12, pady=8)

        scroll = tk.Scrollbar(list_frame, bg=BG3)
        scroll.pack(side="right", fill="y")

        self.listbox = tk.Listbox(list_frame, bg=BG3, fg=TEXT,
                                  font=("Consolas", 9), relief="flat",
                                  selectbackground=BLUE, selectforeground=WHITE,
                                  yscrollcommand=scroll.set, activestyle="none",
                                  borderwidth=0)
        self.listbox.pack(fill="both", expand=True)
        scroll.config(command=self.listbox.yview)
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)
        self._refresh_list()

        tk.Frame(side, bg=BORDER, height=1).pack(fill="x", padx=12)

        # 상세 / 수정 패널
        tk.Label(side, text="부재 정보 수정", font=("Malgun Gothic", 10, "bold"),
                 bg=BG2, fg=WHITE).pack(anchor="w", padx=12, pady=(10,6))

        self.detail_frame = tk.Frame(side, bg=BG2)
        self.detail_frame.pack(fill="x", padx=12, pady=(0,8))
        self._show_empty_detail()

    # ── 리스트 갱신 ─────────────────────────────────────────
    def _refresh_list(self):
        self.listbox.delete(0, "end")
        self._filtered = []
        search = self.search_var.get().lower()
        dfilter = self.dir_filter.get()
        for b in self.beam_data:
            if dfilter != "전체" and b["beam_direction"] != dfilter:
                continue
            name = b["beam_name"] or b["beam_id"]
            if search and search not in name.lower() and search not in b["beam_id"].lower():
                continue
            self._filtered.append(b)
            mod_mark = " ✏" if b.get("modified") else ""
            self.listbox.insert("end",
                f"{name}  {b['span_length']/1000:.2f}m{mod_mark}")

    # ── 상세 패널 ────────────────────────────────────────────
    def _show_empty_detail(self):
        for w in self.detail_frame.winfo_children():
            w.destroy()
        tk.Label(self.detail_frame, text="보를 클릭하거나\n목록에서 선택하세요",
                 font=("Malgun Gothic", 9), bg=BG2, fg=TEXT2,
                 justify="center").pack(pady=20)

    def _show_detail(self, beam: dict):
        for w in self.detail_frame.winfo_children():
            w.destroy()

        col = COLOR_MAP.get(beam["beam_direction"], "#aaa")

        # 필드 정의: (라벨, dict키, 편집가능여부, 단위)
        fields = [
            ("보 ID",    "beam_id",        False, ""),
            ("이름",     "beam_name",      True,  ""),
            ("방향",     "beam_direction", False, ""),
            ("스팬 길이","span_length",    True,  "mm"),
            ("보 폭",    "beam_width",     True,  "mm"),
            ("레이어",   "beam_layer",     False, ""),
            ("시작 기둥","start_column",   False, ""),
            ("끝 기둥",  "end_column",     False, ""),
        ]

        self.edit_vars = {}

        for lbl, key, editable, unit in fields:
            row = tk.Frame(self.detail_frame, bg=BG2)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=lbl, font=("Malgun Gothic", 8),
                     bg=BG2, fg=TEXT2, width=8, anchor="w").pack(side="left")
            val = beam.get(key, "") or ""
            if key == "span_length":
                val = f"{float(val):.1f}" if val else "0"
            elif key == "beam_width":
                val = f"{float(val):.1f}" if val else "0"
            var = tk.StringVar(value=str(val))
            self.edit_vars[key] = var
            if editable:
                e = tk.Entry(row, textvariable=var,
                             font=("Consolas", 9), bg=BG3, fg=WHITE,
                             insertbackground=WHITE, relief="flat",
                             highlightbackground=col, highlightthickness=1)
                e.pack(side="left", fill="x", expand=True, ipady=3)
                if unit:
                    tk.Label(row, text=unit, font=("Malgun Gothic", 8),
                             bg=BG2, fg=TEXT2).pack(side="left", padx=2)
            else:
                tk.Label(row, textvariable=var,
                         font=("Consolas", 9), bg=BG2,
                         fg=col if key=="beam_direction" else TEXT).pack(side="left")

        # 메모
        tk.Label(self.detail_frame, text="메모",
                 font=("Malgun Gothic", 8), bg=BG2, fg=TEXT2,
                 anchor="w").pack(fill="x", pady=(6,2))
        memo_txt = tk.Text(self.detail_frame, height=3,
                           font=("Malgun Gothic", 9), bg=BG3, fg=TEXT,
                           insertbackground=WHITE, relief="flat",
                           highlightbackground=BORDER, highlightthickness=1)
        memo_txt.insert("1.0", beam.get("memo",""))
        memo_txt.pack(fill="x")
        self.memo_widget = memo_txt

        # 저장 버튼
        def _save_beam():
            updates = {}
            for key in ["beam_name","span_length","beam_width"]:
                if key in self.edit_vars:
                    v = self.edit_vars[key].get().strip()
                    updates[key] = float(v) if key in ["span_length","beam_width"] else v
            updates["memo"] = memo_txt.get("1.0","end-1c")

            # 메모리 업데이트
            beam.update(updates)
            beam["modified"] = 1

            # DB 저장
            if beam.get("db_id"):
                self.db.update_beam(beam["db_id"], updates)

            self._refresh_list()
            self._draw()
            messagebox.showinfo("저장", f"'{beam['beam_name']}' 저장 완료!", parent=self)

        tk.Button(self.detail_frame, text="💾  이 부재 저장",
                  command=_save_beam,
                  font=("Malgun Gothic", 9, "bold"),
                  bg=ACCENT, fg=WHITE, relief="flat",
                  cursor="hand2", pady=5).pack(fill="x", pady=(10,0))

    # ── 캔버스 그리기 ────────────────────────────────────────
    def _calc_bounds(self):
        pts = ([b["start_point"] for b in self.beam_data] +
               [b["end_point"]   for b in self.beam_data] +
               list(self.col_positions))
        if not pts:
            return {"xmin":0,"xmax":1000,"ymin":0,"ymax":1000}
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        pad = max((max(xs)-min(xs))*0.06, (max(ys)-min(ys))*0.06, 500)
        return {"xmin":min(xs)-pad,"xmax":max(xs)+pad,
                "ymin":min(ys)-pad,"ymax":max(ys)+pad}

    def _to_screen(self, wx, wy):
        W = self.canvas.winfo_width() or 800
        H = self.canvas.winfo_height() or 600
        bw = self._bounds["xmax"] - self._bounds["xmin"]
        bh = self._bounds["ymax"] - self._bounds["ymin"]
        base = min(W/bw, H/bh) * self.scale
        ox = (W - bw*base)/2 + self.pan[0]
        oy = (H - bh*base)/2 + self.pan[1]
        return (ox + (wx - self._bounds["xmin"]) * base,
                oy + (self._bounds["ymax"] - wy) * base)

    def _draw(self):
        self.canvas.delete("all")
        W = self.canvas.winfo_width() or 800
        H = self.canvas.winfo_height() or 600
        bw = self._bounds["xmax"] - self._bounds["xmin"]
        bh = self._bounds["ymax"] - self._bounds["ymin"]
        base = min(W/bw, H/bh) * self.scale
        col_sz = max(6, int(300 * base))

        # 기둥
        for cp in self.col_positions:
            sx, sy = self._to_screen(cp[0], cp[1])
            hs = col_sz // 2
            self.canvas.create_rectangle(
                sx-hs, sy-hs, sx+hs, sy+hs,
                fill="#2d5a27", outline="#4CAF50", width=1
            )

        # 보
        for b in self.beam_data:
            sx1, sy1 = self._to_screen(*b["start_point"])
            sx2, sy2 = self._to_screen(*b["end_point"])
            col   = COLOR_MAP.get(b["beam_direction"], "#aaa")
            is_sel = self.selected and self.selected.get("db_id") == b.get("db_id")
            is_mod = b.get("modified", 0)
            lw    = 5 if is_sel else 3

            # 폭 영역
            if b.get("beam_width", 0) > 0:
                dx = sx2-sx1; dy = sy2-sy1
                ln = math.hypot(dx,dy) or 1
                hw = b["beam_width"] * base / 2
                nx, ny = -dy/ln, dx/ln
                pts_poly = [
                    sx1+nx*hw, sy1+ny*hw, sx2+nx*hw, sy2+ny*hw,
                    sx2-nx*hw, sy2-ny*hw, sx1-nx*hw, sy1-ny*hw
                ]
                self.canvas.create_polygon(
                    pts_poly, fill=col,
                    stipple="gray25" if not is_sel else "gray50",
                    outline=col, width=0
                )

            # 선
            dash = (4,3) if is_mod else None
            self.canvas.create_line(
                sx1, sy1, sx2, sy2,
                fill="#4ecca3" if is_sel else col,
                width=lw, capstyle="round",
                dash=dash
            )

            # 라벨
            screen_len = math.hypot(sx2-sx1, sy2-sy1)
            if screen_len > 35:
                mx, my = (sx1+sx2)/2, (sy1+sy2)/2
                name = b.get("beam_name") or b["beam_id"]
                lbl  = f"{name}  {b['span_length']/1000:.2f}m"
                if b.get("beam_width",0) > 0:
                    lbl += f"\nW={b['beam_width']:.0f}"
                self.canvas.create_text(
                    mx, my-6, text=lbl,
                    fill="#4ecca3" if is_sel else WHITE,
                    font=("Consolas", 8 if not is_sel else 9),
                    anchor="center"
                )

        # 범례
        legend = [("X방향","#2196F3"),("Y방향","#F44336"),("대각선","#FF9800"),("기둥","#4CAF50")]
        lx, ly = 14, 14
        for txt, col in legend:
            self.canvas.create_rectangle(lx, ly, lx+18, ly+10, fill=col, outline="")
            self.canvas.create_text(lx+24, ly+5, text=txt, fill=TEXT,
                                    font=("Malgun Gothic", 8), anchor="w")
            ly += 18

        # 수정 표시 범례
        total = len(self.beam_data)
        mod   = sum(1 for b in self.beam_data if b.get("modified"))
        self.canvas.create_text(
            W-10, H-10,
            text=f"총 {total}개  수정됨: {mod}개",
            fill=TEXT2, font=("Malgun Gothic", 8), anchor="se"
        )

    # ── 이벤트 ──────────────────────────────────────────────
    def _on_click(self, e):
        self._drag_start  = (e.x, e.y)
        self._drag_origin = list(self.pan)

    def _on_drag(self, e):
        if self._drag_start:
            self.pan[0] = self._drag_origin[0] + e.x - self._drag_start[0]
            self.pan[1] = self._drag_origin[1] + e.y - self._drag_start[1]
            self._draw()

    def _on_release(self, e):
        if self._drag_start:
            moved = math.hypot(e.x - self._drag_start[0],
                               e.y - self._drag_start[1])
            if moved < 5:
                self._hit_test(e.x, e.y)
        self._drag_start = None

    def _on_wheel(self, e):
        f = 1.15 if e.delta > 0 else 1/1.15
        W = self.canvas.winfo_width()
        H = self.canvas.winfo_height()
        self.pan[0] = e.x + (self.pan[0]-e.x)*f
        self.pan[1] = e.y + (self.pan[1]-e.y)*f
        self.scale *= f
        self._draw()

    def _hit_test(self, mx, my):
        best, best_d = None, 12
        for b in self.beam_data:
            sx1,sy1 = self._to_screen(*b["start_point"])
            sx2,sy2 = self._to_screen(*b["end_point"])
            d = self._pt_seg_dist(mx,my,sx1,sy1,sx2,sy2)
            if d < best_d:
                best_d = d; best = b
        self.selected = best
        self._draw()
        if best:
            self._show_detail(best)
            # 리스트 동기화
            for i, fb in enumerate(self._filtered):
                if fb.get("db_id") == best.get("db_id"):
                    self.listbox.selection_clear(0,"end")
                    self.listbox.selection_set(i)
                    self.listbox.see(i)
                    break
        else:
            self._show_empty_detail()

    def _on_list_select(self, e):
        sel = self.listbox.curselection()
        if not sel:
            return
        b = self._filtered[sel[0]]
        self.selected = b
        self._draw()
        self._show_detail(b)

    def _zoom(self, f):
        W = self.canvas.winfo_width() or 800
        H = self.canvas.winfo_height() or 600
        cx, cy = W/2, H/2
        self.pan[0] = cx + (self.pan[0]-cx)*f
        self.pan[1] = cy + (self.pan[1]-cy)*f
        self.scale *= f
        self._draw()

    def _reset_view(self):
        self.pan = [0.0, 0.0]
        self.scale = 1.0
        self._draw()

    def _save_all(self):
        mod = sum(1 for b in self.beam_data if b.get("modified"))
        messagebox.showinfo("저장 완료",
                            f"총 {len(self.beam_data)}개 보  |  수정 {mod}개 저장 완료",
                            parent=self)

    @staticmethod
    def _pt_seg_dist(px,py,x1,y1,x2,y2):
        dx,dy = x2-x1, y2-y1
        l2 = dx*dx+dy*dy
        if l2==0: return math.hypot(px-x1,py-y1)
        t = max(0,min(1,((px-x1)*dx+(py-y1)*dy)/l2))
        return math.hypot(px-(x1+t*dx), py-(y1+t*dy))


# ════════════════════════════════════════════════════════════
#  프로젝트 매니저 창 (메인)
# ════════════════════════════════════════════════════════════
class ProjectManager(tk.Toplevel):
    """프로젝트 목록 관리 창"""

    def __init__(self, parent, db: BeamDB):
        super().__init__(parent)
        self.title("STRCAD  |  프로젝트 관리")
        self.geometry("560x420")
        self.configure(bg=BG)
        self.db = db
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        tk.Label(self, text="📂  프로젝트 목록",
                 font=("Malgun Gothic", 13, "bold"),
                 bg=BG, fg=WHITE).pack(anchor="w", padx=20, pady=(16,8))

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # 목록
        frame = tk.Frame(self, bg=BG)
        frame.pack(fill="both", expand=True, padx=16, pady=12)

        cols = ("이름", "DXF 파일", "생성일")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings",
                                 style="Custom.Treeview")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Custom.Treeview",
                        background=BG3, foreground=TEXT,
                        fieldbackground=BG3, rowheight=28,
                        font=("Malgun Gothic", 9))
        style.configure("Custom.Treeview.Heading",
                        background=BG2, foreground=WHITE,
                        font=("Malgun Gothic", 9, "bold"))
        style.map("Custom.Treeview", background=[("selected", BLUE)])

        for c, w in zip(cols, [160,240,130]):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w)

        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._open_project())

        # 버튼 행
        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(fill="x", padx=16, pady=(0,16))

        for txt, cmd, col in [
            ("▶  열기",    self._open_project,   BLUE),
            ("🗑  삭제",   self._delete_project,  RED),
        ]:
            tk.Button(btn_row, text=txt, command=cmd,
                      font=("Malgun Gothic", 9, "bold"),
                      bg=col, fg=WHITE, relief="flat",
                      padx=12, pady=6, cursor="hand2").pack(side="left", padx=4)

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        self._projects = self.db.list_projects()
        for pid, name, dxf_path, created in self._projects:
            fname = Path(dxf_path).name if dxf_path else "-"
            date  = created[:10] if created else "-"
            self.tree.insert("", "end", iid=str(pid),
                             values=(name, fname, date))

    def _open_project(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("선택 없음", "프로젝트를 선택하세요.", parent=self)
            return
        pid  = int(sel[0])
        name = next(p[1] for p in self._projects if p[0]==pid)
        BeamViewer(self, pid, name, self.db)

    def _delete_project(self):
        sel = self.tree.selection()
        if not sel:
            return
        pid  = int(sel[0])
        name = next(p[1] for p in self._projects if p[0]==pid)
        if messagebox.askyesno("삭제 확인", f"'{name}' 프로젝트를 삭제할까요?", parent=self):
            self.db.delete_project(pid)
            self._refresh()


# ════════════════════════════════════════════════════════════
#  외부 호출용 함수 (strcad_gui.py에서 import해서 사용)
# ════════════════════════════════════════════════════════════
def open_viewer(parent, beam_data: list, column_positions: list,
                project_name: str = None, dxf_path: str = "",
                db_path: str = "strcad_data.db"):
    """
    분석 완료 후 바로 뷰어 열기
    strcad_gui.py의 _analysis_worker에서 호출
    """
    db = BeamDB(db_path)
    name = project_name or f"프로젝트_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    pid  = db.create_project(name, dxf_path)
    db.save_beams(pid, beam_data, column_positions)
    BeamViewer(parent, pid, name, db)
    return pid


def open_project_manager(parent, db_path: str = "strcad_data.db"):
    """저장된 프로젝트 목록 열기"""
    db = BeamDB(db_path)
    ProjectManager(parent, db)


# 단독 실행 테스트
if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    open_project_manager(root)
    root.mainloop()
