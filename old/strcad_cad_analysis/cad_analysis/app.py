"""StrCAD — CAD Analysis window (Tkinter).

Flow: DXF 열기 → 전체 도면 미리보기 → 평면(영역) 선택 → 레이어 분류(Ollama/규칙) → 매핑 확인
      → 형상 분석 + 절점 공유 → 클릭/편집 → DB 저장
"""
from __future__ import annotations

import copy
import math
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from . import settings as S
from . import db
from . import topology as T
from .analyzer import analyze
from .classifier import classify_layers, fallback_auto
from .dialogs import LayerDialog, CoordDialog, DbDialog, ReviewDialog, TextWindow
from .osnap import OSnap, MODES as OS_MODES, MODE_KO, RANK
from .postprocess import remove_wall_girders
from . import review as RV
from . import survey as SV
from .survey import GRADE_COLOR
from .dxf_loader import load_drawing
from .exporter import export_csv, export_json, export_dxf
from .geometry import dist_point_seg, point_in_poly
from .model import KIND_KO, LAYER_ROLES, SRC_KO, SRC_LABEL, SRC_USER, CoordSystem
from .ollama_client import OllamaClient, OllamaError
from .region import detect_plans, crop, robust_extents

COLORS = {"column": "#d62828", "girder": "#1d4ed8", "beam": "#15803d", "wall": "#374151"}
SEL = "#f59e0b"
BG = "#ffffff"
FONT = ("Malgun Gothic", 9)
FONT_B = ("Malgun Gothic", 10, "bold")
KO2KIND = {v: k for k, v in KIND_KO.items()}

TOOLS = (("select", "선택"), ("move", "이동"), ("add_col", "기둥 추가"), ("add_line", "선부재 추가"),
         ("delete", "삭제"))
TOOL_HELP = {
    "select": "클릭: 부재 선택 · 드래그: 화면 이동 · Delete: 선택 부재 삭제",
    "move": "절점(□)을 끌어 이동 → 다른 절점 위에 놓으면 합쳐짐(공유), 부재 위에 놓으면 T접합.\n"
            "부재 몸통을 끌면 부재 전체 이동(연결 부재는 따라 늘어남). 곡선부재 절점은 고정.",
    "add_col": "클릭한 위치(절점/그리드 교점/부재 위 스냅)에 기둥 추가. 크기는 아래 b×h, 방향은 좌표계 회전각.",
    "add_line": "시점 클릭 → 종점 클릭. 절점·그리드 교점·부재 위에 스냅되어 자동 연결. Shift: 좌표축 방향 고정, Esc: 취소",
    "delete": "클릭한 부재 삭제 (Ctrl+Z로 되돌리기)",
}


HELP_USAGE = """[기본 흐름]
1. 파일 › DXF 열기 → 전체 도면이 보이고 평면 후보가 파란 박스로 표시됩니다.
   박스 클릭 = 그 평면만 분석, 드래그 = 영역 직접 지정, 박스 밖 더블클릭 = 전체 분석.
2. 레이어 매핑 창에서 역할을 확인합니다. 레이어가 정리되지 않은 도면은 '형상 자동판별'로 지정합니다.
3. 분석이 끝나면 기둥은 점, 거더·보·벽은 중심선으로 표시되고 만나는 부재는 절점을 공유합니다.
4. 부재를 클릭하면 오른쪽에 이름·크기·길이·좌표·절점이 나옵니다.

[해석(분석) 탭]
- WallGirder 정리: 벽 위에 겹쳐 그려진 보/거더를 지우고 벽으로 표현합니다(보 이름은 벽 비고에 기록).
  '자동 정리'를 켜 두면 분석할 때 자동으로 처리됩니다.
- AI 검토: 연결되지 않은 절점, 기둥으로 잡혔지만 벽으로 보이는 부재를 찾아 Ollama가 판단합니다.
  결과 목록에서 체크한 항목만 적용되며 Ctrl+Z 한 번으로 모두 되돌릴 수 있습니다.

[편집 탭]
- 도구: 선택 / 이동 / 기둥 추가 / 선부재 추가 / 삭제 (편집 탭이 열려 있을 때만 동작)
- 객체 스냅(F3): 절점·끝점·중간점·교차점·수직·근접·그리드·부재 위. 원도면 선의 점에 스냅됩니다.
- 절점 위에 다른 절점을 놓으면 합쳐지고(공유), 부재 위에 놓으면 T접합이 됩니다.

[현장조사 탭]
- 부재를 더블클릭해 실측 크기·강도·탄산화·철근탐사·손상·상태등급·사진·메모를 기록합니다.
- 조사 현황에서 도면 대비 실측 차이를 확인하고, 조사표 CSV로 내보낼 수 있습니다.

[저장]
- 파일 › DB 저장: 분석·편집·현장조사 기록이 모두 저장되며 원본 DXF 없이도 다시 열립니다.
"""

HELP_KEYS = """마우스
  휠                 확대 / 축소
  드래그(선택 도구)   화면 이동
  가운데·오른쪽 드래그  화면 이동
  클릭               부재 선택
  더블클릭(현장조사 탭) 조사 입력

키보드
  F3        객체 스냅 켜기/끄기
  Shift     선부재 그릴 때 좌표축 방향 고정
  Esc       그리던 선 취소
  Delete    선택 부재 삭제
  Ctrl+Z    되돌리기
  Ctrl+Y    다시실행
"""


class CadAnalysisApp:
    def __init__(self, root: tk.Misc):
        self.root = root
        self.cfg = S.load()
        self.dd = None            # full drawing (preview)
        self.plans = []
        self.region = None
        self.sub = None           # cropped drawing used for the analysis
        self._roles = {}
        self.res = None
        self.members = []
        self.sel = None
        self.cs = CoordSystem()
        self.mode = None          # None / "preview" / "result"
        self.tool = tk.StringVar(value="select")
        self.db_id = None
        self.db_name = ""
        self.dirty = False
        self.undo_stack, self.redo_stack = [], []
        self.q = queue.Queue()
        self.busy = False
        self.pick_origin = False
        self.grid_pts = []
        # view
        self.s, self.ox, self.oy = 1.0, 0.0, 0.0
        self._press = None        # (sx, sy, last_sx, last_sy, moved)
        self._mv = None           # move-tool drag state
        self._line_start = None   # (snap info) for add_line
        self._region_drag = None
        self._snap = None
        self.osnap = None

        root.title("StrCAD - CAD Analysis (Ollama)")
        try:
            root.geometry("1440x880")
        except tk.TclError:
            pass
        try:
            ttk.Style(root).configure("Treeview", font=FONT, rowheight=20)
        except tk.TclError:
            pass
        self._build()
        self._poll()
        self.root.after(200, self._refresh_models)
        if isinstance(root, (tk.Tk, tk.Toplevel)):
            root.protocol("WM_DELETE_WINDOW", self._on_close)
        for seq, fn in (("<Escape>", self._esc), ("<Delete>", lambda e: self.delete_selected()),
                        ("<Control-z>", lambda e: self.undo()), ("<Control-y>", lambda e: self.redo()),
                        ("<F3>", self._toggle_osnap)):
            root.bind(seq, fn)

    # ======================================================================= UI
    def _build(self):
        self.show = {k: tk.BooleanVar(value=True) for k in ("column", "girder", "beam", "wall")}
        self.show_bg = tk.BooleanVar(value=True)
        self.show_grid = tk.BooleanVar(value=True)
        self.show_names = tk.BooleanVar(value=True)
        self.show_outline = tk.BooleanVar(value=True)
        self.show_nodes = tk.BooleanVar(value=False)
        self.show_survey = tk.BooleanVar(value=True)
        self.infer = tk.BooleanVar(value=self.cfg["infer_names"])
        self.wg_var = tk.BooleanVar(value=self.cfg.get("wall_girder", True))
        self.use_ai = tk.BooleanVar(value=self.cfg["use_ollama"])
        self.host = tk.StringVar(value=self.cfg["ollama_host"])
        self.model = tk.StringVar(value=self.cfg["ollama_model"])
        osc = self.cfg.get("osnap", {})
        self.os_on = tk.BooleanVar(value=osc.get("on", True))
        self.os_modes = {k: tk.BooleanVar(value=osc.get(k, d)) for k, d in
                         (("node", True), ("end", True), ("mid", True), ("int", True), ("per", True),
                          ("nea", False), ("grid", True), ("member", True))}
        self.snap_px = tk.IntVar(value=osc.get("px", 10))

        self.rb = ttk.Notebook(self.root)
        self.rb.pack(fill="x", padx=4, pady=(4, 0))
        tabs = {}
        for key, title in (("file", "파일"), ("view", "보기"), ("edit", "편집"), ("anal", "해석(분석)"),
                           ("survey", "현장조사"), ("help", "도움말")):
            f = ttk.Frame(self.rb, padding=(4, 4))
            self.rb.add(f, text=f"  {title}  ")
            tabs[key] = f
        self.rb.bind("<<NotebookTabChanged>>", self._tab_changed)
        self._rib_file(tabs["file"])
        self._rib_view(tabs["view"])
        self._rib_edit(tabs["edit"])
        self._rib_anal(tabs["anal"])
        self._rib_survey(tabs["survey"])
        self._rib_help(tabs["help"])

        pw = ttk.PanedWindow(self.root, orient="horizontal")
        pw.pack(fill="both", expand=True)
        left = ttk.Frame(pw)
        right = ttk.Frame(pw, width=430)
        pw.add(left, weight=4)
        pw.add(right, weight=1)

        self.cv = tk.Canvas(left, bg=BG, highlightthickness=0, cursor="crosshair")
        self.cv.pack(fill="both", expand=True)
        bar = ttk.Frame(left)
        bar.pack(fill="x")
        self.coord_lbl = ttk.Label(bar, text="", anchor="w", font=("Consolas", 9))
        self.coord_lbl.pack(side="left", fill="x", expand=True)
        self.os_lbl = ttk.Label(bar, text="", anchor="e", font=FONT)
        self.os_lbl.pack(side="right", padx=6)
        self._os_status()
        cv = self.cv
        cv.bind("<ButtonPress-1>", self._b1_down)
        cv.bind("<B1-Motion>", self._b1_move)
        cv.bind("<ButtonRelease-1>", self._b1_up)
        for b in ("<ButtonPress-2>", "<ButtonPress-3>"):
            cv.bind(b, self._pan_start)
        for b in ("<B2-Motion>", "<B3-Motion>"):
            cv.bind(b, self._pan_move)
        for b in ("<ButtonRelease-2>", "<ButtonRelease-3>"):
            cv.bind(b, lambda e: self.redraw())
        cv.bind("<Double-Button-1>", self._dbl)
        cv.bind("<MouseWheel>", self._wheel)
        cv.bind("<Button-4>", lambda e: self._zoom_at(e.x, e.y, 1.2))
        cv.bind("<Button-5>", lambda e: self._zoom_at(e.x, e.y, 1 / 1.2))
        cv.bind("<Motion>", self._motion)
        cv.bind("<Configure>", lambda e: self.redraw())

        self._build_info(right)

        lf = ttk.Frame(self.root)
        lf.pack(fill="x")
        self.log_txt = tk.Text(lf, height=4, font=("Consolas", 9), bg="#f7f7f7", relief="flat")
        self.log_txt.pack(fill="x", side="left", expand=True)
        self.status = ttk.Label(self.root, text="DXF 평면도를 열거나 DB에서 불러오세요.", anchor="w", padding=(6, 2))
        self.status.pack(fill="x")

    # ---------------------------------------------------------------- ribbon helpers
    @staticmethod
    def _grp(parent, title):
        g = ttk.LabelFrame(parent, text=title, padding=(6, 2))
        g.pack(side="left", fill="y", padx=3)
        return g

    @staticmethod
    def _big(parent, text, cmd, w=9):
        b = ttk.Button(parent, text=text, command=cmd, width=w)
        b.pack(side="left", padx=2, pady=2, fill="y")
        return b

    def _rib_file(self, p):
        g = self._grp(p, "도면")
        self._big(g, "📂\nDXF 열기", self.open_file)
        self._big(g, "⬚\n영역 선택", self.back_to_preview)
        g = self._grp(p, "DB")
        self._big(g, "💾\n저장", self.save_db)
        self._big(g, "💾\n다른 이름", lambda: self.save_db(as_new=True))
        self._big(g, "📁\n불러오기", self.open_db)
        g = self._grp(p, "내보내기")
        self._big(g, "📊\nCSV(엑셀)", lambda: self.export("csv"))
        self._big(g, "{ }\nJSON", lambda: self.export("json"))
        self._big(g, "📐\n중심선 DXF", lambda: self.export("dxf"), w=11)
        g = self._grp(p, "창")
        self._big(g, "✖\n닫기", self._on_close)

    def _rib_view(self, p):
        g = self._grp(p, "부재")
        for i, k in enumerate(("column", "girder", "beam", "wall")):
            ttk.Checkbutton(g, text=KIND_KO[k], variable=self.show[k], command=self.redraw).grid(
                row=i % 2, column=i // 2, sticky="w", padx=4)
        g = self._grp(p, "표시")
        items = (("원도면선", self.show_bg), ("그리드", self.show_grid), ("기둥외곽", self.show_outline),
                 ("부재명", self.show_names), ("절점", self.show_nodes), ("조사 표시", self.show_survey))
        for i, (t, v) in enumerate(items):
            ttk.Checkbutton(g, text=t, variable=v, command=self.redraw).grid(row=i % 2, column=i // 2, sticky="w",
                                                                           padx=4)
        g = self._grp(p, "화면")
        self._big(g, "⛶\n전체보기", self.fit)
        self._big(g, "＋\n확대", lambda: self._zoom_at(self.cv.winfo_width() / 2, self.cv.winfo_height() / 2, 1.5), 6)
        self._big(g, "－\n축소", lambda: self._zoom_at(self.cv.winfo_width() / 2, self.cv.winfo_height() / 2, 1 / 1.5),
                  6)
        g = self._grp(p, "좌표")
        self._big(g, "📐\n좌표계", self.coord_dialog)
        g = self._grp(p, "범례")
        ttk.Label(g, font=FONT, foreground="#555", justify="left",
                  text="실선 = 도면 표기 이름   점선 = 추정/미표기\n◆ = 형상판별   ■ 공유절점  ◇ T접합  □ 자유단").pack()

    def _rib_edit(self, p):
        g = self._grp(p, "도구")
        for i, (k, t) in enumerate(TOOLS):
            ttk.Radiobutton(g, text=t, value=k, variable=self.tool, command=self._tool_changed,
                            style="Toolbutton").grid(row=i // 3, column=i % 3, sticky="ew", padx=1, pady=1)
        g = self._grp(p, "새 부재")
        ttk.Label(g, text="선부재").grid(row=0, column=0, sticky="w")
        self.new_kind = tk.StringVar(value=KIND_KO["girder"])
        ttk.Combobox(g, textvariable=self.new_kind, state="readonly", width=6,
                     values=[KIND_KO[k] for k in ("girder", "beam", "wall")]).grid(row=0, column=1, sticky="w")
        ttk.Label(g, text="폭/두께").grid(row=0, column=2, sticky="w", padx=(6, 0))
        self.new_w = tk.StringVar(value="400")
        ttk.Entry(g, textvariable=self.new_w, width=6).grid(row=0, column=3, sticky="w")
        ttk.Label(g, text="기둥 b×h").grid(row=1, column=0, sticky="w")
        cf = ttk.Frame(g)
        cf.grid(row=1, column=1, columnspan=2, sticky="w")
        self.new_b = tk.StringVar(value="600")
        self.new_h = tk.StringVar(value="600")
        ttk.Entry(cf, textvariable=self.new_b, width=5).pack(side="left")
        ttk.Label(cf, text="×").pack(side="left")
        ttk.Entry(cf, textvariable=self.new_h, width=5).pack(side="left")
        ttk.Label(g, text="이름").grid(row=1, column=2, sticky="e", padx=(6, 0))
        self.new_name = tk.StringVar(value="")
        ttk.Entry(g, textvariable=self.new_name, width=6).grid(row=1, column=3, sticky="w")

        g = self._grp(p, "객체 스냅 (F3)")
        ttk.Checkbutton(g, text="사용", variable=self.os_on, command=self._os_changed).grid(row=0, column=0, sticky="w")
        labels = (("node", "절점"), ("end", "끝점"), ("mid", "중간점"), ("int", "교차점"),
                  ("per", "수직"), ("nea", "근접"), ("grid", "그리드"), ("member", "부재 위"))
        for i, (k, t) in enumerate(labels):
            ttk.Checkbutton(g, text=t, variable=self.os_modes[k], command=self._os_changed).grid(
                row=i % 2, column=1 + i // 2, sticky="w", padx=2)
        ttk.Label(g, text="감도(px)").grid(row=1, column=0, sticky="w")
        sp = ttk.Spinbox(g, from_=3, to=40, textvariable=self.snap_px, width=4, command=self._os_changed)
        sp.grid(row=1, column=0, sticky="e", padx=(52, 0))

        g = self._grp(p, "실행 취소")
        self._big(g, "↶\n되돌리기", self.undo, 7)
        self._big(g, "↷\n다시실행", self.redo, 7)
        g = self._grp(p, "도움말")
        self.tool_help = ttk.Label(g, text=TOOL_HELP["select"], foreground="#555", wraplength=250,
                                   justify="left", font=("Malgun Gothic", 8))
        self.tool_help.pack()

    def _rib_anal(self, p):
        g = self._grp(p, "분석")
        self._big(g, "🗂\n레이어 매핑", self.show_layers, 10)
        self._big(g, "▶\n다시 분석", self.reanalyze)
        opt = ttk.Frame(g)
        opt.pack(side="left", padx=4)
        ttk.Checkbutton(opt, text="미표기 이름 추정", variable=self.infer, command=self._save_cfg).pack(anchor="w")
        ttk.Checkbutton(opt, text="WallGirder 자동 정리", variable=self.wg_var, command=self._save_cfg).pack(anchor="w")
        g = self._grp(p, "후처리")
        self._big(g, "▤\nWallGirder\n정리", self.wall_girder_cleanup, 10)
        self._big(g, "⛓\n절점 다시\n연결", self.rebuild_nodes, 9)
        g = self._grp(p, "AI 검토")
        self._big(g, "🤖\n절점·기둥\n검토", self.ai_review, 10)
        g = self._grp(p, "Ollama")
        ttk.Checkbutton(g, text="사용", variable=self.use_ai, command=self._save_cfg).grid(row=0, column=0, sticky="w")
        self.ai_state = ttk.Label(g, text="●", foreground="#999")
        self.ai_state.grid(row=0, column=1, sticky="w")
        ttk.Entry(g, textvariable=self.host, width=24).grid(row=0, column=2, columnspan=2, sticky="w")
        ttk.Label(g, text="모델").grid(row=1, column=0, sticky="w")
        self.model_cb = ttk.Combobox(g, textvariable=self.model, width=20)
        self.model_cb.grid(row=1, column=1, columnspan=2, sticky="w")
        self.model_cb.bind("<<ComboboxSelected>>", lambda e: self._save_cfg())
        ttk.Button(g, text="⟳", width=3, command=self._refresh_models).grid(row=1, column=3, sticky="w")

    def _rib_survey(self, p):
        g = self._grp(p, "조사 기록")
        self._big(g, "📝\n조사 입력", self.survey_input)
        self._big(g, "📋\n조사 현황", self.survey_list)
        self._big(g, "📤\n조사표 CSV", self.survey_export, 10)
        g = self._grp(p, "표시")
        ttk.Checkbutton(g, text="조사 부재 표시 (등급 색)", variable=self.show_survey, command=self.redraw).pack(anchor="w")
        lg = ttk.Frame(g)
        lg.pack(anchor="w")
        for gr, col in GRADE_COLOR.items():
            tk.Label(lg, text=f" {gr} ", bg=col, fg="white", font=("Malgun Gothic", 8, "bold")).pack(side="left", padx=1)
        g = self._grp(p, "안내")
        ttk.Label(g, font=FONT, foreground="#555", justify="left",
                  text="이 탭에서 부재를 더블클릭하면 조사 입력 창이 열립니다.\n"
                       "실측 크기·반발경도/코어 강도·탄산화·철근탐사·손상·상태등급·사진을\n"
                       "부재별로 기록하고 분석과 함께 DB에 저장됩니다.").pack()

    def _rib_help(self, p):
        g = self._grp(p, "도움말")
        self._big(g, "📖\n사용법", self.help_usage)
        self._big(g, "⌨\n단축키", self.help_keys)
        self._big(g, "ℹ\n정보", self.help_about)

    def _build_info(self, parent):
        info = ttk.LabelFrame(parent, text="부재 정보", padding=8)
        info.pack(fill="x", padx=2, pady=(4, 2))
        nm = ttk.Frame(info)
        nm.pack(fill="x")
        self.name_var = tk.StringVar(value="-")
        self.name_lbl = ttk.Label(nm, textvariable=self.name_var, font=("Malgun Gothic", 14, "bold"))
        self.name_lbl.pack(side="left")
        self.edit_btn = ttk.Button(nm, text="✎", width=3, command=self._edit_name)
        self.edit_btn.pack(side="left", padx=6)
        self.name_edit = ttk.Frame(nm)
        self.name_entry = ttk.Entry(self.name_edit, width=12, font=FONT_B)
        self.name_entry.pack(side="left")
        ttk.Button(self.name_edit, text="✔", width=3, command=self._edit_ok).pack(side="left", padx=2)
        ttk.Button(self.name_edit, text="✖", width=3, command=self._edit_cancel).pack(side="left")
        self.name_entry.bind("<Return>", lambda e: self._edit_ok())
        self.name_entry.bind("<Escape>", lambda e: self._edit_cancel())

        kf = ttk.Frame(info)
        kf.pack(fill="x", pady=(6, 0))
        ttk.Label(kf, text="종류", foreground="#555", font=FONT, width=11).pack(side="left")
        self.kind_var = tk.StringVar()
        self.kind_cb = ttk.Combobox(kf, textvariable=self.kind_var, state="disabled", width=8,
                                    values=[KIND_KO[k] for k in ("column", "girder", "beam", "wall")])
        self.kind_cb.pack(side="left")
        self.kind_cb.bind("<<ComboboxSelected>>", self._kind_changed)
        self.kind_note = ttk.Label(kf, text="", foreground="#888", font=FONT)
        self.kind_note.pack(side="left", padx=6)

        self.info_rows = {}
        grid = ttk.Frame(info)
        grid.pack(fill="x", pady=(4, 0))
        for r, key in enumerate(("크기", "길이 L(중심)", "순경간 ln", "시점", "종점", "중심", "각도", "절점",
                                 "레이어", "이름 근거", "도면 표기", "현장조사", "비고")):
            ttk.Label(grid, text=key, foreground="#555", font=FONT, width=11).grid(row=r, column=0, sticky="nw")
            v = tk.StringVar(value="")
            ttk.Label(grid, textvariable=v, font=FONT, wraplength=300, justify="left").grid(
                row=r, column=1, sticky="w")
            self.info_rows[key] = v

        sf = ttk.Frame(info)
        sf.pack(fill="x", pady=(6, 0))
        self.sel_lbl = ttk.Label(sf, text="")      # kept for compatibility (not shown)
        ttk.Label(sf, text="폭/b", font=FONT).pack(side="left")
        self.ed_w = tk.StringVar()
        ttk.Entry(sf, textvariable=self.ed_w, width=6).pack(side="left", padx=2)
        ttk.Label(sf, text="춤/h", font=FONT).pack(side="left")
        self.ed_d = tk.StringVar()
        ttk.Entry(sf, textvariable=self.ed_d, width=6).pack(side="left", padx=2)
        ttk.Button(sf, text="크기 적용", command=self.apply_size).pack(side="left", padx=2)
        ttk.Button(sf, text="i분리", width=5, command=lambda: self.detach_end(1)).pack(side="left")
        ttk.Button(sf, text="j분리", width=5, command=lambda: self.detach_end(2)).pack(side="left", padx=2)
        ttk.Button(sf, text="삭제", width=5, command=self.delete_selected).pack(side="left")

        tf = ttk.LabelFrame(parent, text="부재 목록", padding=4)
        tf.pack(fill="both", expand=True, padx=2, pady=2)
        self.tv = ttk.Treeview(tf, columns=("size", "len", "src"), show="tree headings", selectmode="browse")
        for c, t, w in (("#0", "부재", 140), ("size", "크기", 90), ("len", "L / 개수", 70), ("src", "근거", 70)):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=w, anchor="e" if c == "len" else ("center" if c == "src" else "w"))
        vs = ttk.Scrollbar(tf, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.tv.pack(fill="both", expand=True)
        self.tv.bind("<<TreeviewSelect>>", self._tree_select)

    # ======================================================================= infra
    def log(self, msg):
        self.q.put(("log", str(msg)))

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log_txt.insert("end", payload + "\n")
                    self.log_txt.see("end")
                    self.status.config(text=payload)
                elif kind == "call":
                    payload()
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _run_bg(self, fn, done=None, busy_msg="처리 중…"):
        if self.busy:
            return
        self.busy = True
        self.status.config(text=busy_msg)
        self.root.config(cursor="watch")

        def work():
            try:
                r, err = fn(), None
            except Exception as e:      # noqa: BLE001 — show any failure to the user
                import traceback
                r, err = None, e
                self.log(traceback.format_exc())

            def fin():
                self.busy = False
                self.root.config(cursor="")
                if err:
                    messagebox.showerror("오류", str(err), parent=self.root)
                elif done:
                    done(r)
            self.q.put(("call", fin))
        threading.Thread(target=work, daemon=True).start()

    def _save_cfg(self):
        self.cfg.update(ollama_host=self.host.get().strip(), ollama_model=self.model.get().strip(),
                        use_ollama=self.use_ai.get(), infer_names=self.infer.get(),
                        wall_girder=self.wg_var.get())
        S.save(self.cfg)

    def _client(self):
        if not self.use_ai.get() or not self.model.get().strip():
            return None
        return OllamaClient(self.host.get().strip(), self.model.get().strip())

    def _refresh_models(self):
        host = self.host.get().strip()

        def work():
            try:
                ms = OllamaClient(host).list_models()
            except OllamaError as e:
                ms = e

            def fin():
                if isinstance(ms, Exception):
                    self.ai_state.config(foreground="#d62828")
                    self.log(f"Ollama 미연결 — 규칙 기반으로 동작합니다. ({host})")
                    return
                self.model_cb["values"] = ms
                if ms and self.model.get() not in ms:
                    self.model.set(ms[0])
                self.ai_state.config(foreground="#16a34a" if ms else "#f59e0b")
                self.log(f"Ollama 연결됨: 모델 {len(ms)}개" + ("" if ms else " (ollama pull 로 모델 설치 필요)"))
                self._save_cfg()
            self.q.put(("call", fin))
        threading.Thread(target=work, daemon=True).start()

    def _set_dirty(self, v=True):
        self.dirty = v
        base = "StrCAD - CAD Analysis"
        name = self.db_name or (os.path.basename(self.res.source_file) if self.res else "")
        self.root.title(f"{base} — {name}{' *' if v else ''}" if name else base)

    def _confirm_discard(self):
        if not self.dirty:
            return True
        r = messagebox.askyesnocancel("저장", "현재 분석(편집 포함)이 저장되지 않았습니다. DB에 저장할까요?",
                                      parent=self.root)
        if r is None:
            return False
        if r:
            return self.save_db()
        return True

    def _on_close(self):
        if self._confirm_discard():
            self.root.destroy()

    # ======================================================================= open / region / analyse
    def open_file(self):
        if self.busy or not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            parent=self.root, title="구조평면도 열기", initialdir=self.cfg.get("last_dir") or None,
            filetypes=[("DXF / DWG", "*.dxf *.dwg"), ("DXF", "*.dxf"), ("모든 파일", "*.*")])
        if not path:
            return
        self.cfg["last_dir"] = os.path.dirname(path)
        self._save_cfg()
        self.load_path(path)

    def load_path(self, path):
        self.log_txt.delete("1.0", "end")
        self.log(f"열기: {path}")

        def work():
            dd = load_drawing(path, progress=self.log)
            plans = detect_plans(dd)
            return dd, plans

        def done(r):
            self.dd, self.plans = r
            self.res, self.members, self.sel = None, [], None
            self.db_id, self.db_name = None, ""
            self.undo_stack.clear(); self.redo_stack.clear()
            self._set_dirty(False)
            self._fill_tree(); self._show_info(None)
            self.mode = "preview"
            self.fit()
            n = len(self.plans)
            self.log(f"평면 후보 {n}개 — 분석할 평면을 클릭하거나, 드래그로 영역을 지정하세요. "
                     f"(전체 분석: 바깥 빈 곳 더블클릭)")
        self._run_bg(work, done, "도면 읽는 중…")

    def back_to_preview(self):
        if self.mode == "preview":
            return
        if self.dd is None:
            path = self.res.source_file if self.res else ""
            if path and os.path.exists(path):
                if self._confirm_discard():
                    self.load_path(path)
            else:
                messagebox.showinfo("영역 선택", "원본 DXF를 먼저 여세요.", parent=self.root)
            return
        if not self._confirm_discard():
            return
        self.mode = "preview"
        self.sel = None
        self.fit()
        self.log("분석할 평면을 클릭하거나 드래그로 영역을 지정하세요.")

    def choose_region(self, rect):
        self.region = tuple(rect)
        self.sub = crop(self.dd, self.region)
        n = sum(len(l.segments) for l in self.sub.layers.values())
        self.log(f"선택 영역: 선 {n:,}개 · 레이어 {len(self.sub.layers)}개")
        client = self._client()
        sub = self.sub

        def work():
            self.log(f"{'Ollama(' + client.model + ')' if client else '규칙'}로 레이어 분류 중…")
            sums = sub.layer_summaries()
            roles = classify_layers(sums, client, log=self.log)
            mem = self.cfg.get("layer_memory", {})
            for k in roles:
                if k in mem and mem[k] in LAYER_ROLES:
                    roles[k] = (mem[k], "저장됨")
            roles2 = fallback_auto(sums, roles)
            if roles2 != roles:
                self.log("구조 레이어를 찾지 못해 선 레이어를 '형상 자동판별'로 지정했습니다.")
            return roles2

        def done(roles):
            self._roles = roles
            self.show_layers()
        self._run_bg(work, done, "레이어 분류 중…")

    def show_layers(self):
        if not self.sub:
            messagebox.showinfo("레이어 매핑", "DXF를 열고 영역을 선택하세요.", parent=self.root)
            return
        LayerDialog(self.root, self.sub.layer_summaries(), self._roles, self._layers_ok,
                    on_reclassify=self._reclassify if self._client() else None)

    def _reclassify(self):
        client, sub = self._client(), self.sub

        def work():
            return classify_layers(sub.layer_summaries(), client, log=self.log)

        def done(roles):
            self._roles = roles
            self.show_layers()
        self._run_bg(work, done, "Ollama 레이어 재분류 중…")

    def _layers_ok(self, roles, edited):
        self._roles = {k: (v, "저장됨" if k in edited else self._roles.get(k, (v, "규칙"))[1])
                       for k, v in roles.items()}
        if edited:
            self.cfg.setdefault("layer_memory", {}).update(edited)
            self._save_cfg()
        self._run_analysis(roles)

    def reanalyze(self):
        if not self.sub:
            messagebox.showinfo("다시 분석", "원본 DXF를 열고 영역을 선택해야 합니다.", parent=self.root)
            return
        if self.dirty and self.undo_stack and not messagebox.askyesno(
                "다시 분석", "편집 내용이 사라집니다. 계속할까요?", parent=self.root):
            return
        self._run_analysis({k: v[0] for k, v in self._roles.items()})

    def _run_analysis(self, roles):
        client, sub, infer, wg = self._client(), self.sub, self.infer.get(), self.wg_var.get()

        def work():
            return analyze(sub, roles, client=client, infer_names=infer, wall_girder=wg, log=self.log)

        def done(res):
            res.region = self.region
            res.source_file = self.dd.path if self.dd else sub.path
            self._set_result(res, keep_cs=True)
            self.db_id, self.db_name = None, ""
            self._set_dirty(True)
        self._run_bg(work, done, "부재 분석 중…")

    def _set_result(self, res, keep_cs=False):
        self.res = res
        self.members = res.members
        self.sel = None
        self.mode = "result"
        self.undo_stack.clear(); self.redo_stack.clear()
        self._grid_intersections()
        self.osnap = OSnap(res.background + res.grid)
        self._fill_tree()
        self.fit()
        self._show_info(None)

    def _grid_intersections(self):
        pts = []
        g = self.res.grid if self.res else []
        for i in range(len(g)):
            a = g[i]
            for j in range(i + 1, len(g)):
                b = g[j]
                d1x, d1y = a.x2 - a.x1, a.y2 - a.y1
                d2x, d2y = b.x2 - b.x1, b.y2 - b.y1
                den = d1x * d2y - d1y * d2x
                if abs(den) < 1e-9 * (a.length * b.length + 1):
                    continue
                t = ((b.x1 - a.x1) * d2y - (b.y1 - a.y1) * d2x) / den
                u = ((b.x1 - a.x1) * d1y - (b.y1 - a.y1) * d1x) / den
                if -0.02 <= t <= 1.02 and -0.02 <= u <= 1.02:
                    pts.append((a.x1 + d1x * t, a.y1 + d1y * t))
        self.grid_pts = pts

    # ======================================================================= DB
    def save_db(self, as_new=False):
        if not self.res:
            messagebox.showinfo("저장", "저장할 분석이 없습니다.", parent=self.root)
            return False
        aid = None if as_new else self.db_id
        if aid is not None:
            r = messagebox.askyesnocancel("DB 저장", f"'{self.db_name}' 에 덮어쓸까요?\n(아니오 = 새 이름으로 저장)",
                                          parent=self.root)
            if r is None:
                return False
            if not r:
                aid = None
        name = self.db_name
        if aid is None:
            base = os.path.splitext(os.path.basename(self.res.source_file or "분석"))[0]
            name = simpledialog.askstring("DB 저장", "분석 이름:", parent=self.root,
                                          initialvalue=self.db_name or base)
            if not name:
                return False
        cs = None if self.cs.is_identity() else self.cs
        try:
            self.db_id = db.save(self.res, cs, name.strip(), aid)
        except Exception as e:      # noqa: BLE001
            messagebox.showerror("DB 저장", str(e), parent=self.root)
            return False
        self.db_name = name.strip()
        self._set_dirty(False)
        self.log(f"DB 저장: '{self.db_name}' (id {self.db_id}) → {db.DB_PATH}")
        return True

    def open_db(self):
        if self.busy or not self._confirm_discard():
            return
        DbDialog(self.root, self._open_db_id)

    def _open_db_id(self, aid):
        try:
            name, res, cs = db.load(aid)
        except Exception as e:      # noqa: BLE001
            messagebox.showerror("불러오기", str(e), parent=self.root)
            return
        self.dd, self.sub, self.region = None, None, res.region
        self.cs = cs
        self._set_result(res)
        self.db_id, self.db_name = aid, name
        self._set_dirty(False)
        self.log(f"DB 불러오기: '{name}' — 부재 {len(res.members)}개, 절점 {len(res.nodes)}개")

    # ======================================================================= view
    def w2s(self, x, y):
        return (x - self.ox) * self.s, (self.oy - y) * self.s

    def s2w(self, sx, sy):
        return sx / self.s + self.ox, self.oy - sy / self.s

    def fit(self):
        if self.mode == "preview" and self.dd:
            if self.plans:
                xs = [p[0] for p in self.plans] + [p[2] for p in self.plans]
                ys = [p[1] for p in self.plans] + [p[3] for p in self.plans]
                ext = (min(xs), min(ys), max(xs), max(ys))
            else:
                ext = robust_extents(self.dd)
        elif self.res:
            ext = self.res.extents
        else:
            return
        x0, y0, x1, y1 = ext
        w = max(self.cv.winfo_width(), 200)
        h = max(self.cv.winfo_height(), 200)
        self.s = 0.92 * min(w / max(x1 - x0, 1), h / max(y1 - y0, 1))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.ox = cx - w / 2 / self.s
        self.oy = cy + h / 2 / self.s
        self.redraw()

    def _view_box(self):
        W, H = self.cv.winfo_width(), self.cv.winfo_height()
        x0, y1 = self.s2w(0, 0)
        x1, y0 = self.s2w(W, H)
        return x0, y0, x1, y1

    def redraw(self):
        self.cv.delete("all")
        if self.mode == "preview":
            self._draw_preview()
        elif self.mode == "result" and self.res:
            self._draw_result()

    def _draw_preview(self):
        cv = self.cv
        x0, y0, x1, y1 = self._view_box()
        minlen = 1.0 / self.s
        for ld in self.dd.layers.values():
            for g in ld.segments:
                if max(g.x1, g.x2) < x0 or min(g.x1, g.x2) > x1 or max(g.y1, g.y2) < y0 or min(g.y1, g.y2) > y1:
                    continue
                if abs(g.x2 - g.x1) + abs(g.y2 - g.y1) < minlen:
                    continue
                cv.create_line(*self.w2s(g.x1, g.y1), *self.w2s(g.x2, g.y2), fill="#9aa1a9")
        for i, p in enumerate(self.plans, 1):
            a = self.w2s(p[0], p[3])
            b = self.w2s(p[2], p[1])
            cv.create_rectangle(*a, *b, outline="#2563eb", dash=(6, 4), width=2, tags=("plan", f"plan{i}"))
            cv.create_text(a[0] + 6, a[1] + 6, anchor="nw", text=f"평면 {i}", fill="#2563eb",
                           font=("Malgun Gothic", 12, "bold"))
        if self.region:
            a = self.w2s(self.region[0], self.region[3])
            b = self.w2s(self.region[2], self.region[1])
            cv.create_rectangle(*a, *b, outline="#f59e0b", width=2)
        cv.create_text(10, 10, anchor="nw", fill="#111", font=("Malgun Gothic", 10, "bold"),
                       text="① 파란 평면 클릭  또는  ② 드래그로 영역 지정  또는  ③ 빈 곳 더블클릭 = 전체 분석")

    def _node_degree(self):
        deg = {}
        for m in self.members:
            for nid in (m.node, m.n1, m.n2):
                if nid is not None:
                    deg[nid] = deg.get(nid, 0) + 1
            for i in m.inner:
                deg[i[0]] = deg.get(i[0], 0) + 1
        return deg

    def _draw_result(self):
        cv = self.cv
        x0, y0, x1, y1 = self._view_box()

        def vis(xa, ya, xb, yb):
            return not (max(xa, xb) < x0 or min(xa, xb) > x1 or max(ya, yb) < y0 or min(ya, yb) > y1)

        if self.show_grid.get():
            for g in self.res.grid:
                if vis(g.x1, g.y1, g.x2, g.y2):
                    cv.create_line(*self.w2s(g.x1, g.y1), *self.w2s(g.x2, g.y2), fill="#a5d8e6", dash=(6, 3))
        if self.show_bg.get():
            for g in self.res.background:
                if vis(g.x1, g.y1, g.x2, g.y2):
                    cv.create_line(*self.w2s(g.x1, g.y1), *self.w2s(g.x2, g.y2), fill="#dcdcdc")
        name_ok = self.show_names.get() and self.s * 300 > 5
        for kind in ("wall", "girder", "beam", "column"):
            if not self.show[kind].get():
                continue
            col = COLORS[kind]
            for m in self.members:
                if m.kind != kind:
                    continue
                tag = f"m{m.id}"
                dash = () if m.name_source in (SRC_LABEL, SRC_USER) else (5, 3)
                if kind == "column":
                    cx, cy = m.center
                    if not vis(cx, cy, cx, cy):
                        continue
                    if self.show_outline.get() and m.polygon and self.s * m.b > 4:
                        pts = [c for p in m.polygon for c in self.w2s(*p)]
                        cv.create_polygon(*pts, outline="#f4a3a3", fill="", tags=(tag,))
                    sx, sy = self.w2s(cx, cy)
                    r = 4
                    if m.auto:
                        cv.create_polygon(sx, sy - 6, sx + 6, sy, sx, sy + 6, sx - 6, sy, outline=col,
                                          fill=BG if dash else col, width=2, tags=(tag,))
                    else:
                        cv.create_oval(sx - r, sy - r, sx + r, sy + r, fill=col if not dash else BG,
                                       outline=col, width=2, tags=(tag,))
                    if name_ok:
                        cv.create_text(sx + 7, sy - 6, text=m.display_name(), anchor="sw",
                                       fill=col, font=("Malgun Gothic", 8), tags=(tag,))
                    continue
                pts = m.polyline()
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                if not vis(min(xs), min(ys), max(xs), max(ys)):
                    continue
                flat = [c for p in pts for c in self.w2s(*p)]
                cv.create_line(*flat, fill=col, width=2 if kind != "wall" else 3, dash=dash, tags=(tag,))
                if name_ok and m.length_cc * self.s > 40:
                    if m.curved:
                        mx, my = self.w2s(*pts[len(pts) // 2]); ang = 0
                    else:
                        mx, my = self.w2s((pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2)
                        ang = m.angle if m.angle <= 90 else m.angle - 180
                    txt = m.display_name() if kind != "wall" else (m.name or f"W{m.width:.0f}")
                    if m.auto:
                        txt = "◆" + txt
                    try:
                        cv.create_text(mx, my - 7, text=txt, angle=ang, fill=col, font=("Malgun Gothic", 8),
                                       tags=(tag,))
                    except tk.TclError:
                        cv.create_text(mx, my - 7, text=txt, fill=col, font=("Malgun Gothic", 8), tags=(tag,))
        # nodes
        if self.show_nodes.get() or self._edit_tab():
            deg = self._node_degree()
            hosts = {i[0] for m in self.members for i in m.inner}
            for n in self.res.nodes.values():
                if not vis(n.x, n.y, n.x, n.y):
                    continue
                sx, sy = self.w2s(n.x, n.y)
                d = deg.get(n.id, 0)
                if n.id in hosts:
                    cv.create_polygon(sx, sy - 4, sx + 4, sy, sx, sy + 4, sx - 4, sy, fill="#7c3aed",
                                      outline="", tags=("node",))
                elif d >= 2:
                    cv.create_rectangle(sx - 3, sy - 3, sx + 3, sy + 3, fill="#7c3aed", outline="", tags=("node",))
                else:
                    cv.create_rectangle(sx - 3, sy - 3, sx + 3, sy + 3, outline="#f97316", width=1.5,
                                        tags=("node",))
        # survey markers (grade colour)
        if self.show_survey.get():
            for m in self.members:
                if not m.survey:
                    continue
                p = m.center if m.kind == "column" else ((m.p1[0] + m.p2[0]) / 2, (m.p1[1] + m.p2[1]) / 2)
                if not vis(p[0], p[1], p[0], p[1]):
                    continue
                sx, sy = self.w2s(*p)
                col = GRADE_COLOR.get(m.survey.get("grade"), "#0ea5e9")
                cv.create_oval(sx - 11, sy - 11, sx + 11, sy + 11, outline=col, width=3, tags=("survey",))
                if m.survey.get("grade"):
                    cv.create_text(sx + 13, sy + 9, text=m.survey["grade"], fill=col, anchor="nw",
                                   font=("Malgun Gothic", 9, "bold"), tags=("survey",))
        # origin marker
        if not self.cs.is_identity():
            sx, sy = self.w2s(self.cs.x0, self.cs.y0)
            r = math.radians(self.cs.rot)
            cv.create_line(sx, sy, sx + 40 * math.cos(r), sy - 40 * math.sin(r), fill="#e11d48", width=2,
                           arrow="last")
            cv.create_line(sx, sy, sx - 40 * math.sin(r), sy - 40 * math.cos(r), fill="#16a34a", width=2,
                           arrow="last")
            cv.create_text(sx + 46 * math.cos(r), sy - 46 * math.sin(r), text="X", fill="#e11d48")
            cv.create_text(sx - 46 * math.sin(r), sy - 46 * math.cos(r), text="Y", fill="#16a34a")
        self._draw_selection()
        self._draw_snap()

    def _draw_selection(self):
        self.cv.delete("sel")
        m = self.sel
        if not m or self.mode != "result":
            return
        if m.kind == "column":
            sx, sy = self.w2s(*m.center)
            self.cv.create_oval(sx - 9, sy - 9, sx + 9, sy + 9, outline=SEL, width=3, tags="sel")
            if m.polygon:
                pts = [c for p in m.polygon for c in self.w2s(*p)]
                self.cv.create_polygon(*pts, outline=SEL, fill="", width=2, tags="sel")
        else:
            flat = [c for p in m.polyline() for c in self.w2s(*p)]
            self.cv.create_line(*flat, fill=SEL, width=6, capstyle="round", tags="sel")
            for p in (m.p1, m.p2):
                sx, sy = self.w2s(*p)
                self.cv.create_oval(sx - 4, sy - 4, sx + 4, sy + 4, fill=SEL, outline="", tags="sel")
            if m.c1 and m.c2 and not m.curved:
                for p in (m.c1, m.c2):
                    sx, sy = self.w2s(*p)
                    self.cv.create_line(sx - 5, sy - 5, sx + 5, sy + 5, fill="#000", tags="sel")
                    self.cv.create_line(sx - 5, sy + 5, sx + 5, sy - 5, fill="#000", tags="sel")
            sx, sy = self.w2s(*m.p1)
            self.cv.create_text(sx, sy - 12, text="i", fill="#000", font=FONT_B, tags="sel")
            sx, sy = self.w2s(*m.p2)
            self.cv.create_text(sx, sy - 12, text="j", fill="#000", font=FONT_B, tags="sel")
        self.cv.tag_raise("sel")

    def _draw_snap(self):
        self.cv.delete("snap")
        sn = self._snap
        C = "#e11d48"
        if self._line_start:
            a = self.w2s(*self._line_start[2])
            if sn:
                b = self.w2s(*sn[2])
                self.cv.create_line(*a, *b, fill=C, dash=(4, 3), width=2, tags="snap")
        if not sn or sn[0] == "free":
            return
        x, y = self.w2s(*sn[2])
        k = sn[0]
        cv = self.cv
        if k == "node":
            cv.create_oval(x - 7, y - 7, x + 7, y + 7, outline=C, width=2, tags="snap")
            cv.create_line(x - 5, y - 5, x + 5, y + 5, fill=C, width=2, tags="snap")
            cv.create_line(x - 5, y + 5, x + 5, y - 5, fill=C, width=2, tags="snap")
        elif k == "end":
            cv.create_rectangle(x - 6, y - 6, x + 6, y + 6, outline=C, width=2, tags="snap")
        elif k == "mid":
            cv.create_polygon(x, y - 7, x + 7, y + 5, x - 7, y + 5, outline=C, fill="", width=2, tags="snap")
        elif k == "int":
            cv.create_line(x - 7, y - 7, x + 7, y + 7, fill=C, width=2, tags="snap")
            cv.create_line(x - 7, y + 7, x + 7, y - 7, fill=C, width=2, tags="snap")
        elif k == "per":
            cv.create_line(x - 7, y + 6, x + 7, y + 6, fill=C, width=2, tags="snap")
            cv.create_line(x, y + 6, x, y - 7, fill=C, width=2, tags="snap")
        elif k == "nea":
            cv.create_polygon(x - 6, y - 6, x + 6, y - 6, x - 6, y + 6, x + 6, y + 6, outline=C, fill="",
                              width=2, tags="snap")
        elif k == "grid":
            cv.create_line(x - 8, y, x + 8, y, fill=C, width=2, tags="snap")
            cv.create_line(x, y - 8, x, y + 8, fill=C, width=2, tags="snap")
        elif k == "member":
            cv.create_polygon(x, y - 7, x + 7, y, x, y + 7, x - 7, y, outline=C, fill="", width=2, tags="snap")
        cv.create_text(x + 10, y + 10, text=MODE_KO.get(k, ""), anchor="nw", fill=C,
                       font=("Malgun Gothic", 8, "bold"), tags="snap")

    # ======================================================================= mouse
    def _edit_tab(self):
        try:
            return self.rb.index(self.rb.select()) == 2
        except tk.TclError:
            return False

    def _survey_tab(self):
        try:
            return self.rb.index(self.rb.select()) == 4
        except tk.TclError:
            return False

    def _active_tool(self):
        return self.tool.get() if self._edit_tab() else "select"

    def _tab_changed(self, _e=None):
        if not hasattr(self, "cv") or not hasattr(self, "tool_help"):
            return
        self._line_start = None
        self._snap = None
        self._tool_changed()
        if self._survey_tab():
            self.status.config(text="현장조사: 부재를 더블클릭하면 조사 입력 창이 열립니다.")
        self.redraw()

    def _tool_changed(self):
        t = self._active_tool()
        self._line_start = None
        self.tool_help.config(text=TOOL_HELP[self.tool.get()])
        self.cv.config(cursor={"select": "crosshair", "move": "fleur", "add_col": "plus", "add_line": "pencil",
                               "delete": "X_cursor"}.get(t, "crosshair"))
        if self._edit_tab():
            self.status.config(text=TOOL_HELP[self.tool.get()].split("\n")[0])

    def _tol(self):
        return max(3, int(self.snap_px.get() or 10)) / self.s

    def _b1_down(self, e):
        self._press = [e.x, e.y, e.x, e.y, False]
        if self.mode == "preview":
            self._region_drag = (e.x, e.y)
            return
        if self.mode != "result":
            return
        if self._active_tool() == "move":
            x, y = self.s2w(e.x, e.y)
            nid = T.find_node(self.res, x, y, self._tol())
            if nid is not None:
                if T.locked_node(self.res, nid):
                    self.status.config(text="곡선부재의 절점은 이동할 수 없습니다.")
                    self._mv = None
                else:
                    self._mv = {"type": "node", "nid": nid, "pushed": False}
                return
            m = self._hit(x, y)
            if m is not None and not m.curved:
                self._mv = {"type": "member", "m": m, "last": (x, y), "pushed": False}
                self.select(m)
                return
            self._mv = None

    def _b1_move(self, e):
        p = self._press
        if not p:
            return
        if not p[4] and abs(e.x - p[0]) + abs(e.y - p[1]) < 5:
            return
        p[4] = True
        if self.mode == "preview":
            self.cv.delete("rubber")
            self.cv.create_rectangle(p[0], p[1], e.x, e.y, outline="#f59e0b", width=2, dash=(4, 2), tags="rubber")
            return
        if self._mv:
            x, y = self.s2w(e.x, e.y)
            if not self._mv["pushed"]:
                self._push_undo()
                self._mv["pushed"] = True
            if self._mv["type"] == "node":
                nid = self._mv["nid"]
                sn = self._snap_point(x, y, exclude_nodes={nid}, members=False)
                self._snap = sn if sn[0] not in ("free", "member") else None
                h, _ = T.host_of(self.res, nid)
                if h is not None:
                    d, _t = dist_point_seg(*sn[2], *h.p1, *h.p2)
                    if d > 3 * self._tol():          # pulled away from the host → free node
                        T.detach_node(self.res, nid)
                        self.status.config(text=f"T접합 해제 ({h.display_name()} #{h.id})")
                T.move_node(self.res, nid, *sn[2])
            else:
                lx, ly = self._mv["last"]
                T.translate_member(self.res, self._mv["m"], x - lx, y - ly)
                self._mv["last"] = (x, y)
            self.redraw()
            return
        # pan
        self.cv.move("all", e.x - p[2], e.y - p[3])
        self.ox -= (e.x - p[2]) / self.s
        self.oy += (e.y - p[3]) / self.s
        p[2], p[3] = e.x, e.y

    def _b1_up(self, e):
        p = self._press
        self._press = None
        if self.mode == "preview":
            self.cv.delete("rubber")
            if p and p[4]:
                a = self.s2w(p[0], p[1])
                b = self.s2w(e.x, e.y)
                self.choose_region((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])))
            else:
                x, y = self.s2w(e.x, e.y)
                hits = [r for r in self.plans if r[0] <= x <= r[2] and r[1] <= y <= r[3]]
                if hits:
                    self.choose_region(min(hits, key=lambda r: (r[2] - r[0]) * (r[3] - r[1])))
            return
        if self._mv:
            mv, self._mv = self._mv, None
            if mv["type"] == "node" and mv["pushed"]:
                self._finish_node_drop(mv["nid"])
            if mv["pushed"]:
                self._after_edit()
            return
        if p and p[4]:
            self.redraw()
            return
        self._click(e.x, e.y)

    def _dbl(self, e):
        if self.mode == "result" and self._survey_tab():
            m = self._hit(*self.s2w(e.x, e.y))
            if m:
                self.select(m)
                self.survey_input()
            return
        if self.mode != "preview" or not self.dd:
            return
        x, y = self.s2w(e.x, e.y)
        if not any(r[0] <= x <= r[2] and r[1] <= y <= r[3] for r in self.plans):
            self.choose_region(self.dd.extents)

    def _finish_node_drop(self, nid):
        res = self.res
        n = res.nodes.get(nid)
        if n is None:
            return
        tgt = T.find_node(res, n.x, n.y, self._tol(), exclude={nid})
        if tgt is not None:
            src_col = any(m.kind == "column" and m.node == nid for m in res.members)
            dst_col = any(m.kind == "column" and m.node == tgt for m in res.members)
            if src_col and dst_col:
                self.log("기둥 두 개를 한 절점에 합칠 수 없습니다.")
                return
            if src_col:
                tx, ty = res.nodes[tgt].xy
                T.merge_nodes(res, tgt, nid)
                T.move_node(res, nid, tx, ty)
            else:
                T.merge_nodes(res, nid, tgt)
            self.log("절점 합침 (부재 공유)")
            return
        own = {m.id for m in T.members_at(res, nid)}
        h, t = T.find_member_body(res, n.x, n.y, self._tol(), exclude=own)
        if h is not None:
            T.attach_node_to_member(res, nid, h, t)
            self.log(f"T접합: {h.display_name()} #{h.id} 위에 연결")

    def _pan_start(self, e):
        self._pan = (e.x, e.y)

    def _pan_move(self, e):
        lx, ly = self._pan
        self.cv.move("all", e.x - lx, e.y - ly)
        self.ox -= (e.x - lx) / self.s
        self.oy += (e.y - ly) / self.s
        self._pan = (e.x, e.y)

    def _wheel(self, e):
        self._zoom_at(e.x, e.y, 1.2 if e.delta > 0 else 1 / 1.2)

    def _zoom_at(self, sx, sy, f):
        wx, wy = self.s2w(sx, sy)
        self.s *= f
        self.ox = wx - sx / self.s
        self.oy = wy + sy / self.s
        self.redraw()

    def _motion(self, e):
        if not self.mode:
            return
        x, y = self.s2w(e.x, e.y)
        txt = f"X={x:,.1f}  Y={y:,.1f}"
        if not self.cs.is_identity():
            lx, ly = self.cs.to_local(x, y)
            txt += f"    (국부) x={lx:,.1f}  y={ly:,.1f}"
        self.coord_lbl.config(text=txt)
        t = self._active_tool()
        if self.mode == "result" and t in ("add_col", "add_line", "move") and not self._mv:
            ref = self._line_start[2] if (t == "add_line" and self._line_start) else None
            sn = self._snap_point(x, y, members=(t != "move"), ref=ref)
            if t == "add_line" and self._line_start and (e.state & 0x0001):
                sn = self._ortho(sn)
            self._snap = sn if (sn[0] != "free" or t == "add_line") else None
            if t == "move" and sn[0] != "node":
                self._snap = None
            self._draw_snap()

    def _ortho(self, sn):
        x0, y0 = self._line_start[2]
        x, y = sn[2]
        r = math.radians(self.cs.rot)
        ux, uy = math.cos(r), math.sin(r)
        a = (x - x0) * ux + (y - y0) * uy
        b = -(x - x0) * uy + (y - y0) * ux
        if abs(a) >= abs(b):
            p = (x0 + ux * a, y0 + uy * a)
        else:
            p = (x0 - uy * b, y0 + ux * b)
        return ("free", None, p)

    def _snap_point(self, x, y, exclude_nodes=(), members=True, ref=None):
        """→ (kind, ref, (x, y)); kind = node / end / mid / int / per / nea / grid / member / free.
        Object snap (F3) on: model points, plan-line points and grid points compete;
        the best-ranked one inside the aperture wins (절점·끝점·교차점 > 중간점·그리드 > 수직 > 부재위 > 근접)."""
        if not self.os_on.get() or not self.res:
            return ("free", None, (x, y))
        tol = self._tol()
        md = {k: v.get() for k, v in self.os_modes.items()}
        cands = []
        if md["node"]:
            nid = T.find_node(self.res, x, y, tol, exclude=exclude_nodes)
            if nid is not None:
                n = self.res.nodes[nid]
                cands.append((RANK["node"], math.hypot(n.x - x, n.y - y), "node", nid, n.xy))
        if md["grid"]:
            for p in self.grid_pts:
                d = math.hypot(p[0] - x, p[1] - y)
                if d <= tol:
                    cands.append((RANK["grid"], d, "grid", None, p))
        if self.osnap is not None:
            modes = {k for k in OS_MODES if md.get(k)}
            for rk, d, k, p in self.osnap.query(x, y, tol, modes, ref=ref)[:6]:
                cands.append((rk, d, k, None, p))
        if members and md["member"]:
            h, t = T.find_member_body(self.res, x, y, tol)
            if h is not None:
                p = (h.p1[0] + (h.p2[0] - h.p1[0]) * t, h.p1[1] + (h.p2[1] - h.p1[1]) * t)
                cands.append((RANK["member"], math.hypot(p[0] - x, p[1] - y), "member", (h, t), p))
        if not cands:
            return ("free", None, (x, y))
        rk, d, k, r, p = min(cands, key=lambda c: (c[0], c[1]))
        return (k, r, p)

    def _os_changed(self):
        self.cfg["osnap"] = {"on": self.os_on.get(), "px": int(self.snap_px.get() or 10),
                             **{k: v.get() for k, v in self.os_modes.items()}}
        S.save(self.cfg)
        self._os_status()

    def _os_status(self):
        if not self.os_on.get():
            self.os_lbl.config(text="스냅 OFF (F3)", foreground="#999")
            return
        on = [MODE_KO[k] for k, v in self.os_modes.items() if v.get()]
        self.os_lbl.config(text="스냅: " + " ".join(on), foreground="#e11d48")

    def _toggle_osnap(self, _e=None):
        self.os_on.set(not self.os_on.get())
        self._os_changed()
        self.status.config(text="객체 스냅 " + ("켜짐" if self.os_on.get() else "꺼짐"))
        if not self.os_on.get():
            self._snap = None
            self._draw_snap()

    def _node_from_snap(self, sn):
        res = self.res
        if sn[0] == "node":
            return sn[1]
        nid = T._new_node(res, *sn[2])
        if sn[0] == "member":
            h, t = sn[1]
        else:   # grid point / free point that happens to lie on a member axis
            h, t = T.find_member_body(res, *sn[2], max(2.0, 1.0 / self.s))
        if h is not None:
            T.attach_node_to_member(res, nid, h, t)
        return nid

    def _hit(self, x, y):
        tol = 8 / self.s
        best, bd = None, tol
        for m in self.members:
            if not self.show[m.kind].get():
                continue
            if m.kind == "column":
                d = math.dist(m.center, (x, y))
                if m.polygon and point_in_poly(x, y, m.polygon):
                    d = min(d, tol * 0.5)
                d *= 0.8
            else:
                pts = m.polyline()
                d = min(dist_point_seg(x, y, *pts[i], *pts[i + 1])[0] for i in range(len(pts) - 1))
            if d < bd:
                best, bd = m, d
        return best

    def _click(self, sx, sy):
        if self.mode != "result":
            return
        x, y = self.s2w(sx, sy)
        if self.pick_origin:
            self.pick_origin = False
            self._tool_changed()
            snap = min((m for m in self.members if m.kind == "column"),
                       key=lambda m: math.dist(m.center, (x, y)), default=None)
            if snap and math.dist(snap.center, (x, y)) < max(30 / self.s, snap.b):
                x, y = snap.center
            self.cs = CoordSystem(x, y, self.cs.rot)
            self.log(f"원점 지정: X={x:,.1f}, Y={y:,.1f}")
            self._set_dirty(True)
            self.redraw()
            self._show_info(self.sel)
            return
        t = self._active_tool()
        if t == "add_col":
            sn = self._snap_point(x, y)
            try:
                b, h = float(self.new_b.get()), float(self.new_h.get())
            except ValueError:
                messagebox.showerror("기둥 추가", "b, h에 숫자를 입력하세요.", parent=self.root)
                return
            if sn[0] == "node" and any(m.kind == "column" and m.node == sn[1] for m in self.members):
                self.status.config(text="이미 기둥이 있는 절점입니다.")
                return
            self._push_undo()
            nid = self._node_from_snap(sn)
            m = T.add_column(self.res, *self.res.nodes[nid].xy, b, h, self.cs.rot, 1.0,
                             name=self.new_name.get().strip())
            self._after_edit(select=m)
            return
        if t == "add_line":
            sn = self._snap_point(x, y, ref=self._line_start[2] if self._line_start else None)
            if self._line_start is None:
                self._line_start = sn
                self.status.config(text="종점을 클릭하세요 (Shift: 축방향, Esc: 취소)")
                return
            if self._snap and self._snap[0] == "free" and sn[0] == "free":
                sn = self._snap                       # keep ortho-constrained point
            try:
                w = float(self.new_w.get())
            except ValueError:
                messagebox.showerror("선부재 추가", "폭에 숫자를 입력하세요.", parent=self.root)
                return
            start, self._line_start = self._line_start, None
            if math.dist(start[2], sn[2]) < 1.0:
                return
            self._push_undo()
            n1 = self._node_from_snap(start)
            n2 = self._node_from_snap(sn)
            m = T.add_linear(self.res, KO2KIND[self.new_kind.get()], n1, n2, w, name=self.new_name.get().strip())
            self._snap = None
            self._after_edit(select=m)
            return
        m = self._hit(x, y)
        if t == "delete":
            if m:
                self._push_undo()
                T.delete_member(self.res, m)
                self.sel = None
                self._after_edit()
            return
        self.select(m)

    def _esc(self, _e=None):
        if self._line_start or self._snap:
            self._line_start = None
            self._snap = None
            self._draw_snap()
            self.status.config(text="취소")

    # ======================================================================= editing infra
    def _push_undo(self):
        if not self.res:
            return
        self.undo_stack.append((copy.deepcopy(self.res.members), copy.deepcopy(self.res.nodes)))
        if len(self.undo_stack) > 60:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _restore(self, snap):
        sel_id = self.sel.id if self.sel else None
        self.res.members, self.res.nodes = snap
        self.members = self.res.members
        self.sel = next((m for m in self.members if m.id == sel_id), None)
        self._after_edit(select=self.sel, push=False)

    def undo(self):
        if not self.undo_stack or not self.res:
            return
        self.redo_stack.append((copy.deepcopy(self.res.members), copy.deepcopy(self.res.nodes)))
        self._restore(self.undo_stack.pop())
        self.log("되돌리기")

    def redo(self):
        if not self.redo_stack or not self.res:
            return
        self.undo_stack.append((copy.deepcopy(self.res.members), copy.deepcopy(self.res.nodes)))
        self._restore(self.redo_stack.pop())
        self.log("다시실행")

    def _after_edit(self, select=None, push=True):
        self.members = self.res.members
        if select is not None:
            self.sel = select
        elif self.sel is not None and self.sel not in self.members:
            self.sel = next((m for m in self.members if m.id == self.sel.id), None)
        self._set_dirty(True)
        self._fill_tree()
        self.redraw()
        self._show_info(self.sel)
        if self.sel and self.tv.exists(f"DT_{self.sel.id}"):
            self.tv.selection_set(f"DT_{self.sel.id}")
            self.tv.see(f"DT_{self.sel.id}")

    def delete_selected(self):
        if self.sel and self.res and self.mode == "result":
            if isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry, ttk.Spinbox)):
                return
            self._push_undo()
            T.delete_member(self.res, self.sel)
            self.sel = None
            self._after_edit()

    def apply_size(self):
        m = self.sel
        if not m:
            return
        try:
            w = float(self.ed_w.get()) if self.ed_w.get().strip() else None
            d = float(self.ed_d.get()) if self.ed_d.get().strip() else None
        except ValueError:
            messagebox.showerror("크기", "숫자를 입력하세요.", parent=self.root)
            return
        self._push_undo()
        if m.kind == "column":
            if w and d:
                cx, cy = m.center
                m.b, m.h = max(w, d), min(w, d)
                m.polygon = T._rect(cx, cy, w, d, m.angle)
                m.shape = "rect"
        else:
            if w:
                m.width = w
            m.depth = d
        m.user = True
        m.notes.append("크기 수정 (사용자)")
        T.sync_all(self.res)
        self._after_edit(select=m)

    def detach_end(self, which):
        m = self.sel
        if not m or m.kind == "column":
            return
        nid = m.n1 if which == 1 else m.n2
        if len(T.members_at(self.res, nid)) <= 1:
            self.status.config(text="이미 다른 부재와 공유되지 않은 절점입니다.")
            return
        self._push_undo()
        new = T._new_node(self.res, *self.res.nodes[nid].xy)
        setattr(m, "n1" if which == 1 else "n2", new)
        T.sync_all(self.res)
        self.log(f"#{m.id} {'i' if which == 1 else 'j'}단 절점 분리 (이동 도구로 원하는 위치로 옮기세요)")
        self._after_edit(select=m)

    def rebuild_nodes(self):
        if not self.res:
            return
        if not messagebox.askyesno("절점 다시 연결", "현재 위치 기준으로 절점 공유를 처음부터 다시 계산합니다.\n"
                                                 "(수동으로 합치거나 분리한 연결은 초기화됩니다)", parent=self.root):
            return
        self._push_undo()
        T.build_topology(self.res, log=self.log)
        self._after_edit()

    def _kind_changed(self, _e=None):
        m = self.sel
        new = KO2KIND.get(self.kind_var.get())
        if not m or not new or new == m.kind:
            return
        self._push_undo()
        nm = T.change_kind(self.res, m, new)
        self.log(f"#{m.id} 종류 변경: {KIND_KO[m.kind]} → {KIND_KO[new]}")
        self._after_edit(select=nm)

    # ======================================================================= selection / info
    def select(self, m, from_tree=False):
        self.sel = m
        self._edit_cancel()
        self._draw_selection()
        self._show_info(m)
        if m and not from_tree:
            iid = f"DT_{m.id}"
            if self.tv.exists(iid):
                self.tv.selection_set(iid)
                self.tv.see(iid)

    def _fmt_pt(self, p):
        s = f"X={p[0]:,.1f}, Y={p[1]:,.1f}"
        if not self.cs.is_identity():
            lx, ly = self.cs.to_local(*p)
            s += f"\n(국부) x={lx:,.1f}, y={ly:,.1f}"
        return s

    def _node_txt(self, nid):
        if nid is None:
            return "-"
        others = [o for o in T.members_at(self.res, nid)]
        h, _ = T.host_of(self.res, nid)
        s = f"N{nid}"
        if h is not None:
            s += f" (T접합: {h.display_name()} #{h.id})"
        s += f" · 공유 {len(others)}"
        return s

    def _show_info(self, m):
        for v in self.info_rows.values():
            v.set("")
        if not m:
            self.name_var.set("-")
            self.kind_var.set("")
            self.kind_cb.config(state="disabled")
            self.kind_note.config(text="")
            self.sel_lbl.config(text="(없음)")
            self.ed_w.set(""); self.ed_d.set("")
            return
        self.name_var.set(m.display_name())
        self.kind_var.set(KIND_KO[m.kind])
        self.kind_cb.config(state="readonly")
        self.kind_note.config(text=f"#{m.id}" + ("  ◆형상판별" if m.auto else "") + ("  ✎사용자" if m.user else ""))
        self.sel_lbl.config(text=f"{KIND_KO[m.kind]} {m.display_name()}  #{m.id}  {m.size_text()}")
        R = self.info_rows
        if m.kind == "column":
            if m.shape == "round":
                R["크기"].set(f"원형 Ø{m.diameter:.0f}")
            else:
                R["크기"].set(f"{m.b:.0f} × {m.h:.0f} mm" + ("  (비정형, 외접사각형)" if m.shape == "polygon" else ""))
            R["중심"].set(self._fmt_pt(m.center))
            R["각도"].set(f"{m.angle:.2f}° (긴 변 방향)")
            R["절점"].set(self._node_txt(m.node))
            self.ed_w.set(f"{m.b:.0f}"); self.ed_d.set(f"{m.h:.0f}")
        else:
            if m.kind == "wall":
                R["크기"].set(f"두께 t = {m.width:.0f} mm")
            else:
                R["크기"].set(f"폭 B = {m.width:.0f} mm" + (f",  춤 D = {m.depth:.0f} mm" if m.depth else
                                                             "  (춤: 평면도에 없음)"))
            R["길이 L(중심)"].set(f"{m.length_cc:,.0f} mm  (절점 i–j)")
            R["순경간 ln"].set(f"{m.length_clear:,.0f} mm" + (f"  (지지면 i {m.off1:.0f} / j {m.off2:.0f})"
                                                            if m.off1 or m.off2 else ""))
            R["시점"].set("i: " + self._fmt_pt(m.p1))
            R["종점"].set("j: " + self._fmt_pt(m.p2))
            R["각도"].set(f"{m.angle:.2f}°" if not m.curved else f"곡선 R={m.arc['r']:,.0f}")
            inner = f"  · 중간 T접합 {len(m.inner)}" if m.inner else ""
            R["절점"].set(f"i {self._node_txt(m.n1)}\nj {self._node_txt(m.n2)}{inner}")
            self.ed_w.set(f"{m.width:.0f}"); self.ed_d.set(f"{m.depth:.0f}" if m.depth else "")
        R["레이어"].set(m.layer)
        R["이름 근거"].set(SRC_KO.get(m.name_source, ""))
        R["도면 표기"].set(", ".join(dict.fromkeys(m.labels)) or "-")
        R["현장조사"].set(SV.summary(m.survey) + (("\n" + SV.size_diff(m, m.survey)) if SV.size_diff(m, m.survey) else ""))
        R["비고"].set("\n".join(m.notes) or "-")

    def _edit_name(self):
        if not self.sel:
            return
        self.name_lbl.pack_forget()
        self.edit_btn.pack_forget()
        self.name_edit.pack(side="left")
        self.name_entry.delete(0, "end")
        self.name_entry.insert(0, self.sel.name)
        self.name_entry.focus_set()
        self.name_entry.select_range(0, "end")

    def _edit_ok(self):
        if self.sel:
            new = self.name_entry.get().strip()
            if new != self.sel.name:
                self._push_undo()
                self.sel.name = new
                self.sel.name_source = SRC_USER
                self.log(f"#{self.sel.id} 이름 변경 → {new or '(미표기)'}")
                self._edit_cancel()
                self._after_edit(select=self.sel)
                return
        self._edit_cancel()

    def _edit_cancel(self):
        if self.name_edit.winfo_ismapped():
            self.name_edit.pack_forget()
            self.name_lbl.pack(side="left")
            self.edit_btn.pack(side="left", padx=6)

    # ======================================================================= tree
    def _fill_tree(self):
        tv = self.tv
        opened = {i for i in self._all_items() if tv.item(i, "open")}
        tv.delete(*tv.get_children())
        for kind in ("column", "girder", "beam", "wall"):
            ms = [m for m in self.members if m.kind == kind]
            if not ms:
                continue
            g = f"GRP_{kind}"
            tv.insert("", "end", iid=g, text=f"{KIND_KO[kind]}", values=("", f"{len(ms)}개", ""),
                      open=g in opened)
            groups = {}
            for m in ms:
                groups.setdefault((m.name or "(미표기)", m.size_text()), []).append(m)
            for (name, size), lst in sorted(groups.items(), key=lambda kv: (kv[0][0] == "(미표기)", kv[0])):
                gid = f"GRP_{kind}_{name}_{size}"
                tv.insert(g, "end", iid=gid, text=name, values=(size, f"{len(lst)}개", ""), open=gid in opened)
                for m in sorted(lst, key=lambda x: x.id):
                    L = "" if kind == "column" else f"{m.length_cc:,.0f}"
                    tag = ("◆" if m.auto else "") + SRC_KO.get(m.name_source, "")[:6]
                    tv.insert(gid, "end", iid=f"DT_{m.id}", text=f"#{m.id}", values=(m.size_text(), L, tag))

    def _all_items(self, parent=""):
        out = []
        for i in self.tv.get_children(parent):
            out.append(i)
            out += self._all_items(i)
        return out

    def _tree_select(self, _e):
        sel = self.tv.selection()
        if not sel or not sel[0].startswith("DT_"):
            return
        mid = int(sel[0][3:])
        m = next((x for x in self.members if x.id == mid), None)
        if m is None or m is self.sel:
            return
        self.select(m, from_tree=True)
        p = m.center if m.kind == "column" else ((m.p1[0] + m.p2[0]) / 2, (m.p1[1] + m.p2[1]) / 2)
        sx, sy = self.w2s(*p)
        W, H = self.cv.winfo_width(), self.cv.winfo_height()
        if not (40 < sx < W - 40 and 40 < sy < H - 40):
            self.ox = p[0] - W / 2 / self.s
            self.oy = p[1] + H / 2 / self.s
            self.redraw()

    # ======================================================================= 해석: WallGirder / AI 검토
    def wall_girder_cleanup(self):
        if not self.res:
            return
        from .postprocess import find_wall_girders
        n = len(find_wall_girders(self.res))
        if not n:
            messagebox.showinfo("WallGirder", "벽과 겹친 보/거더가 없습니다.", parent=self.root)
            return
        if not messagebox.askyesno("WallGirder", f"벽과 겹친 보/거더 {n}개를 삭제하고 벽으로 표현할까요?\n"
                                                 "(보 이름·크기는 벽의 비고에 기록, Ctrl+Z로 되돌리기)", parent=self.root):
            return
        self._push_undo()
        remove_wall_girders(self.res, log=self.log)
        self._after_edit()

    def ai_review(self):
        if not self.res or self.busy:
            if not self.res:
                messagebox.showinfo("AI 검토", "먼저 도면을 분석하세요.", parent=self.root)
            return
        client, res = self._client(), self.res

        def work():
            cands = RV.find_candidates(res)
            self.log(f"검토 대상: 미연결 절점 {sum(c['type'] == 'joint' for c in cands)}건, "
                     f"기둥→벽 의심 {sum(c['type'] == 'col_wall' for c in cands)}건 · "
                     + (f"Ollama({client.model}) 판단 중…" if client else "Ollama 꺼짐 → 규칙 판단"))
            return RV.decide(cands, client, log=self.log)

        def done(cands):
            if not cands:
                messagebox.showinfo("AI 검토", "검토할 항목이 없습니다.", parent=self.root)
                return
            ReviewDialog(self.root, cands, self._review_apply, self._review_focus)
        self._run_bg(work, done, "AI 검토 중…")

    def _review_focus(self, c):
        self._review_mark = c
        (x0, y0), (x1, y1) = c["where"], c["to"]
        W, H = self.cv.winfo_width(), self.cv.winfo_height()
        span = max(abs(x1 - x0), abs(y1 - y0), 3000)
        self.s = min(W, H) / (span * 3)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.ox, self.oy = cx - W / 2 / self.s, cy + H / 2 / self.s
        m = self.res.by_id().get(c["member"])
        if m:
            self.select(m)
        self.redraw()
        a, b = self.w2s(x0, y0), self.w2s(x1, y1)
        self.cv.create_oval(a[0] - 14, a[1] - 14, a[0] + 14, a[1] + 14, outline="#db2777", width=3, tags="rv")
        if c["type"] == "joint":
            self.cv.create_line(*a, *b, fill="#db2777", width=2, dash=(4, 2), arrow="last", tags="rv")

    def _review_apply(self, sel):
        self._push_undo()
        done = []
        for c in sel:
            try:
                r = RV.apply(self.res, c)
            except Exception as e:     # noqa: BLE001
                r = None
                self.log(f"{c['id']} 적용 실패: {e}")
            if r:
                done.append(r)
        self.log(f"AI 검토 적용 {len(done)}/{len(sel)}건 (Ctrl+Z로 한 번에 되돌리기)")
        self._after_edit()

    # ======================================================================= 현장조사
    def survey_input(self):
        if not self.sel:
            messagebox.showinfo("현장조사", "조사할 부재를 먼저 선택하세요. (현장조사 탭에서 더블클릭)", parent=self.root)
            return
        SV.SurveyDialog(self.root, self.sel, self._survey_saved)

    def _survey_saved(self, m, sv):
        self._push_undo()
        m = next((x for x in self.members if x.id == m.id), m)
        m.survey = sv
        self.log(f"현장조사 {'저장' if sv else '삭제'}: {m.display_name()} #{m.id}")
        self._after_edit(select=m)

    def survey_list(self):
        if not self.res:
            return
        SV.SurveyListDialog(self.root, self.members, self._pick_member)

    def _pick_member(self, mid):
        m = self.res.by_id().get(mid)
        if not m:
            return
        self.select(m)
        p = m.center if m.kind == "column" else ((m.p1[0] + m.p2[0]) / 2, (m.p1[1] + m.p2[1]) / 2)
        W, H = self.cv.winfo_width(), self.cv.winfo_height()
        self.ox, self.oy = p[0] - W / 2 / self.s, p[1] + H / 2 / self.s
        self.redraw()

    def survey_export(self):
        if not self.res or not any(m.survey for m in self.members):
            messagebox.showinfo("조사표", "조사 기록이 없습니다.", parent=self.root)
            return
        base = (self.db_name or os.path.splitext(os.path.basename(self.res.source_file))[0]) + "_현장조사.csv"
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".csv", initialfile=base,
                                            filetypes=[("CSV", "*.csv")])
        if path:
            n = SV.export_csv(path, self.members)
            self.log(f"조사표 저장: {n}개 부재 → {path}")

    # ======================================================================= 도움말
    def help_usage(self):
        TextWindow(self.root, "사용법", HELP_USAGE)

    def help_keys(self):
        TextWindow(self.root, "단축키", HELP_KEYS, "520x420")

    def help_about(self):
        from . import __version__
        TextWindow(self.root, "정보", f"StrCAD — CAD Analysis  v{__version__}\n\n"
                   f"DB: {db.DB_PATH}\n설정: {S.PATH}\nOllama: {self.host.get()}  모델: {self.model.get() or '-'}\n\n"
                   "좌표·길이·크기는 도면 형상에서 직접 계산하고, Ollama는 레이어/부재명 해석과\n"
                   "검토(절점 연결·기둥/벽 판단)에만 사용합니다. Ollama가 꺼져 있으면 규칙으로 동작합니다.",
                   "560x300")

    # ======================================================================= coord / export
    def coord_dialog(self):
        CoordDialog(self.root, self.cs, self._set_cs, self._start_pick, self._auto_rot)

    def _set_cs(self, cs):
        self.cs = cs
        self._set_dirty(True)
        self.redraw()
        self._show_info(self.sel)

    def _start_pick(self):
        self.pick_origin = True
        self.cv.config(cursor="target")
        self.status.config(text="원점으로 쓸 기둥(또는 점)을 클릭하세요.")

    def _auto_rot(self):
        hist = {}
        for m in self.members:
            if m.kind in ("girder", "beam") and not m.curved:
                a = round(m.angle % 90, 1)
                hist[a] = hist.get(a, 0) + m.length_cc
        if not hist:
            return 0.0
        a = max(hist, key=hist.get)
        return a if a < 45 else a - 90

    def export(self, fmt):
        if not self.res:
            messagebox.showinfo("내보내기", "먼저 도면을 분석하세요.", parent=self.root)
            return
        base = (self.db_name or os.path.splitext(os.path.basename(self.res.source_file))[0]) + "_부재"
        ext = {"csv": ".csv", "json": ".json", "dxf": ".dxf"}[fmt]
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=ext, initialfile=base + ext,
                                            filetypes=[(fmt.upper(), "*" + ext)])
        if not path:
            return
        cs = None if self.cs.is_identity() else self.cs
        try:
            if fmt == "csv":
                export_csv(path, self.members, cs)
            elif fmt == "json":
                export_json(path, self.res, cs)
            else:
                export_dxf(path, self.members)
        except Exception as e:      # noqa: BLE001
            messagebox.showerror("내보내기", str(e), parent=self.root)
            return
        self.log(f"저장: {path}")


# ============================================================================
def open_window(master=None, path=None):
    """Launcher entry: open_window(root) → Toplevel; open_window() → standalone."""
    if master is None:
        root = tk.Tk()
        app = CadAnalysisApp(root)
        if path:
            root.after(300, lambda: app.load_path(path))
        root.mainloop()
        return app
    win = tk.Toplevel(master)
    app = CadAnalysisApp(win)
    if path:
        win.after(300, lambda: app.load_path(path))
    return app
