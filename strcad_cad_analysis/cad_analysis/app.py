"""StrCAD — CAD Analysis window (Tkinter).

Flow: DXF 열기 → 전체 도면 미리보기 → 평면(영역) 선택(표시만) → [구조도면/건축도면 분석] ▶ 분석 시작
      → 레이어 분류(Ollama/규칙) → 매핑 확인 → 1차 형상 분석 + 절점 공유
      → 2차 AI 검토(레이어 역할 · 거더 끝 기둥 · 절점 · 기둥/벽) → 클릭/편집 → DB 저장
"""
from __future__ import annotations

import copy
import math
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from . import settings as S
from . import db
from . import topology as T
from .analyzer import analyze
from .arch import classify_arch_layers, analyze_arch, ARCH_DEFAULTS
from .classifier import classify_layers, fallback_auto
from .dialogs import LayerDialog, CoordDialog, DbDialog, ReviewDialog, TextWindow, SaveDialog
from .osnap import OSnap, MODES as OS_MODES, MODE_KO, RANK
from .postprocess import remove_wall_girders
from . import review as RV
from . import survey as SV
from . import survey_ui as SU
from . import schedule as SC
from .schedule_ui import SchedulePanel
from .detail_ui import DetailDialog
from .dxf_loader import load_drawing
from .exporter import export_csv, export_json, export_dxf
from .geometry import dist_point_seg, point_in_poly
from .model import KIND_KO, LAYER_ROLES, LAYER_ROLE_KO, SRC_KO, SRC_LABEL, SRC_USER, CoordSystem
from .ollama_client import OllamaClient, OllamaError
from .region import detect_plans, crop, robust_extents
from . import theme as TH
from . import sheets as SH

IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".heic")
COLORS = {"column": "#d62828", "girder": "#1d4ed8", "beam": "#15803d", "wall": "#374151"}
SEL = TH.ORANGE
BG = "#ffffff"
FONT = TH.FONT
FONT_B = TH.FONT_B
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


SV_BG = TH.SURFACE
SV_BLUE = TH.NAVY_3
SV_BLUE_D = TH.NAVY

SV_HELP = {
    "select": "번호 원을 클릭 = 선택(오른쪽에 조사 내용) · 번호 원을 끌면 표시 위치 이동 · 다른 곳 클릭 = 부재 선택",
    "point": "검측위치를 클릭하면 번호가 붙고 오른쪽 입력란에 조사 내용을 적습니다.\n"
             "보·벽은 축선 위로, 기둥은 단면 안 위치로 붙습니다. 번호 원은 끌어서 옮길 수 있습니다.\n"
             "용도가 '하중조사'면 두 모서리를 클릭해 영역(사각형)을 그립니다.",
    "span": "보·거더·벽 위에서 구간 시작점 클릭 → 끝점 클릭 (같은 부재 위로 고정, Esc 취소)",
    "delete": "삭제할 검측위치(번호 원)를 클릭 (Ctrl+Z로 되돌리기)",
}

HELP_USAGE = """[하중조사 · 용도별 표시]
· 현장조사 › 새 검측 용도 '하중조사' → 검측점 도구로 영역의 두 모서리를 클릭 (휴대폰은 손가락으로 끌기)
  - 실 용도 · 바닥 마감 · 마감 두께 · 천장 · 천장고 · 칸막이 · 설비를 고르면
    면적과 하중 참고값(마감+천장 DL, KDS 41 12 00 표 3.2-1 활하중 LL, 경량칸막이 +1.0)이 나옵니다
· 👁 표시할 조사 ▾: 부재검측 / 균열검토 / 하중조사를 따로 또는 같이 보기 (휴대폰은 👁 버튼)

[DXF가 없을 때]
· 시작 화면 '📷 도면 없이 조사' 또는 현장조사 › 📷 새 조사 도면
  - 빈 도면(격자): 가로·세로(m)를 정하면 1 m 격자 위에 검측위치·스케치를 기록
  - 사진·이미지를 배경으로: 도면 사진/스캔/캡처를 깔고 그 위에 기록 (비스듬히 찍었으면 네 모서리를 맞춰 반듯하게)
  - 종이 도면 사진 → 부재 인식: 기둥(사각형)·보/벽(평행선)·부재명(G1, B1, C1 …)을 찾아 후보로 만듦.
    결과는 사진을 배경으로 띄운 채 편집 탭에서 고치세요. (파일 › DXF 열기에서 사진을 골라도 같음)
· 📏 축척 맞추기: 길이를 아는 두 점(그리드 간격 등)을 클릭하고 실제 길이(m)를 넣으면 전체 축척이 맞춰집니다.
· 휴대폰에서도 '＋ 새 조사 (DXF 없이)'로 바로 시작할 수 있고, PC로 가져오면 새 도면으로 추가됩니다.
· Ctrl+S = 저장 (입력 중인 현장조사 항목도 함께 저장)

[기본 흐름]
1. 파일 › DXF 열기 → 전체 도면이 보이고 평면 후보가 파란 점선 박스로 표시됩니다.
2. 분석할 평면을 클릭하면 주황색으로 '선택' 표시만 됩니다(바로 분석하지 않음).
   드래그 = 영역 직접 지정, 박스 밖 빈 곳 더블클릭 = 도면 전체 선택. 다른 박스를 누르면 선택이 바뀝니다.
3. 도면 종류에 맞는 탭에서 ▶ 분석 시작을 누릅니다 (선택 영역 옆에 뜨는 버튼도 같음).
   - 구조도면 분석: 구조평면도(기둥·거더·보·벽 + 부재표기 C1/G1/B1)
   - 건축도면 분석: 구조도면이 없을 때 건축평면도에서 기둥·콘크리트 벽을 찾습니다.
4. 레이어 매핑 창에서 역할을 확인합니다. 레이어가 정리되지 않은 도면은 '형상 자동판별'로 지정합니다.
5. 1차 분석이 끝나면 2차 AI 검토가 자동으로 실행되어 오류 후보를 보여줍니다(체크한 것만 적용).
6. 기둥은 점, 거더·보·벽은 중심선으로 표시되고 만나는 부재는 절점을 공유합니다.
   부재를 클릭하면 오른쪽에 이름·크기·길이·좌표·절점이 나옵니다.

[형상 우선 — 레이어보다 모양으로 판단]
- 닫힌 외곽선/선 묶음이 작고 뭉툭하면(긴변/짧은변 ≤ 2.5) 기둥(크기 b×h), 길쭉하거나 꺾인 모양이면 벽(두께)으로 봅니다.
  레이어가 '기둥'으로 잘못 잡혀 있어도 벽 모양은 벽으로 그려지고, 벽선에 붙어 그려진 기둥은 따로 떼어 기둥으로 잡습니다.
- 벽선 사이에 그려진, 벽보다 확실히 두꺼운 사각형은 기둥으로 봅니다(샤프트·덕트처럼 안쪽이 빈 칸은 제외).
- 꺾이는 벽은 꺾이는 곳마다 절점으로 나뉘어 각각의 벽 부재가 되고 모서리 절점을 공유합니다.
- 벽이 먼저 인식되므로, 벽 위에 겹쳐 그려진(벽보다 두꺼운) 거더선은 WallGirder로 지워지고 벽만 남습니다.

[구조도면 분석 탭 — 2차 AI 검토]
- 레이어 역할 검증: 레이어 이름이 틀린 경우가 많아, 각 레이어의 실제 내용으로 다시 확인합니다.
  · 부재표기(C1, G1, B1, W1)가 어느 레이어 선에 가장 가까운지, 1차 분석에서 부재를 못 찾은 표기는 어디 있는지
  · 평행선 쌍(보·벽) / 작은 사각형(기둥) 비율, 1차 분석에서 그 레이어로 만들어진 부재 수
  → '거더 레이어인데 실제로는 보' / '무시된 레이어에 벽이 있음' 같은 제안. 적용하면 자동으로 다시 분석합니다.
- 거더 끝 기둥 추정: 거더는 보통 기둥과 기둥 사이에 걸리므로, 기둥 없이 끝나는 거더 끝을 찾아
  다른 레이어의 기둥 외곽선 · 근처 C표기 · 그리드 교점 · 모이는 거더 수를 근거로 기둥 추가를 제안합니다.
  (다른 거더 옆면이나 벽에 걸린 끝은 제외)
- 미연결 절점, 기둥으로 잡혔지만 벽으로 보이는 부재 검토.
- 결과 목록에서 체크한 항목만 적용되며 Ctrl+Z 한 번으로 모두 되돌릴 수 있습니다.
- WallGirder 정리: 벽 위에 겹쳐 그려진 보/거더를 지우고 벽으로 표현합니다(보 이름은 벽 비고에 기록).

[건축도면 분석 탭]
- AI(또는 이름 규칙)가 기둥·콘크리트벽·조적/경량 칸막이·문·창·가구·마감 레이어를 구분합니다.
- 기둥: 기둥 레이어 외곽선, 해치(채움)된 사각형, 그리드 교점의 사각형.
- 벽: 평행선 쌍. '비내력벽 포함'을 끄면 두께 기준(기본 150) 미만은 칸막이로 보고 뺍니다.
- 그리드 번호(X1, Y3 …)를 읽어 기둥 이름을 'X2-Y3'처럼 붙입니다.
- '기둥열 사이 거더 추정'을 켜면 같은 그리드선 위 이웃 기둥 사이에 거더를 추정해서 넣습니다(확인 필요).

[편집 탭]
- 도구: 선택 / 이동 / 기둥 추가 / 선부재 추가 / 삭제 (편집 탭이 열려 있을 때만 동작)
- 객체 스냅(F3): 절점·끝점·중간점·교차점·수직·근접·그리드·부재 위. 원도면 선의 점에 스냅됩니다.
- 절점 위에 다른 절점을 놓으면 합쳐지고(공유), 부재 위에 놓으면 T접합이 됩니다.

[현장조사 탭]
- 새 검측 용도(부재검측·균열검토·직접 추가한 용도)를 고르고 도면에서 검측위치를 클릭합니다.
  번호(1, 2, 3 …)가 붙은 원이 생기고, 오른쪽 입력란에 번호·부재명·용도·치수·길이·철근·부재유무·
  사진·추가사항을 적습니다. 철근 버튼 → I단/중앙/J단 × 상부근/하부근/스터럽 표.
- 검측구간: 같은 부재 위에서 시작점·끝점 클릭. 번호 원은 끌어서 보기 좋은 곳으로 옮길 수 있습니다.
- 아래 '조사 목록'은 용도별로 걸러 보고, 행을 누르면 도면에서 그 위치로 이동합니다.
- ‹ n/N › : 같은 프로젝트로 DB에 저장된 도면(층)끼리 넘겨 봅니다. 도면 LIST에서 순서 변경.
- '＋ 용도 추가'로 새 용도를 만들면 입력 항목(쉼표 구분)과 치수/길이/철근/부재유무 포함 여부를 정합니다.
- 📋 부재리스트: 오른쪽이 부재리스트로 바뀝니다(슬래브/거더/보/기둥/벽체/기타 탭).
  부재일람은 도면에서 먼저 추정해서 채우고(⟳ 도면에서 추정), 칸을 누르면 고칠 수 있습니다.
  부재 = 이름 변경(연결된 검측기록 부재명도 같이 바뀜) · 부재일람 = 설계 단면 · 현장검측 = 검측기록 보기/직접 입력
  · 조사여부 = 자동→조사됨→조사안됨. 검측 입력의 부재명 목록에 '부재리스트'가 나오고, 새 부재명으로 저장하면
  리스트에 자동 추가됩니다. 설계와 ±20mm 넘게 다르면 빨간 줄, 조사된 부재는 초록 줄.
- INPUT: 검측 입력창의 INPUT을 누르면 상세 부재입력 창이 열립니다.
  철근콘크리트/철골/합성부재 × 수직(기둥)/수평(보), 지점(Pin·SemiFix·Fix) 클릭 전환, 하중 D·L, B·H·L,
  I단/중앙/J단 상·하·스터럽 배근 → [계산] = 휨·전단(기둥은 축력·P-M) O.K / N.G, [입력] = 검측기록에 반영.

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
  Ctrl+S    저장 (현장조사 입력 중이면 입력 내용도 함께 저장)
  Ctrl+Shift+S  다른 이름으로 저장
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
        self.region_label = ""
        self.analysis_kind = "struct"   # struct 구조도면 / arch 건축도면
        self._review_next = None        # stages of the review to run after the next analysis
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
        self.sel_sv = None        # selected survey record id
        self.project = ""         # 프로젝트(건물) — groups drawings for the ‹ n/N › pager
        self._sv_drag = None
        self._sv_start = None     # (member, t0, (x, y)) while placing a section
        self._sv_area0 = None     # (x, y) — 하중조사 영역 첫 모서리

        root.title(f"{TH.APP_NAME} {TH.APP_SUB}")
        try:
            root.geometry("1440x880")
            root.minsize(1100, 680)
        except tk.TclError:
            pass
        TH.apply(root)
        TH.set_icon(root)
        self._build()
        self._poll()
        self.root.after(200, self._refresh_models)
        if isinstance(root, (tk.Tk, tk.Toplevel)):
            root.protocol("WM_DELETE_WINDOW", self._on_close)
        for seq, fn in (("<Escape>", self._esc), ("<Delete>", lambda e: self.delete_selected()),
                        ("<Control-z>", lambda e: self.undo()), ("<Control-y>", lambda e: self.redo()),
                        ("<F3>", self._toggle_osnap),
                        ("<Control-s>", self._ctrl_s), ("<Control-S>", self._ctrl_s),
                        ("<Control-Shift-s>", lambda e: self._ctrl_s(e, as_new=True)),
                        ("<Control-Shift-S>", lambda e: self._ctrl_s(e, as_new=True))):
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
        self.show_sketch = tk.BooleanVar(value=True)
        self.show_photo = tk.BooleanVar(value=True)
        self._bgimg = SH.BgImage()
        self._calib = None
        self.sv_tool = tk.StringVar(value="point")
        self.P = SV.purposes(self.cfg)
        self.sv_purpose = tk.StringVar(value="부재검측")
        self.sv_hidden = set(self.cfg.get("survey_hidden") or [])      # 도면에 안 그릴 용도
        self.infer = tk.BooleanVar(value=self.cfg["infer_names"])
        self.wg_var = tk.BooleanVar(value=self.cfg.get("wall_girder", True))
        self.use_ai = tk.BooleanVar(value=self.cfg["use_ollama"])
        self.auto_review = tk.BooleanVar(value=self.cfg.get("auto_review", True))
        self.rv_layers = tk.BooleanVar(value=self.cfg.get("review_layers", True))
        self.rv_cols = tk.BooleanVar(value=self.cfg.get("review_columns", True))
        ao = dict(ARCH_DEFAULTS, **self.cfg.get("arch", {}))
        self.ar_part = tk.BooleanVar(value=ao["include_partitions"])
        self.ar_minw = tk.IntVar(value=int(ao["min_wall"]))
        self.ar_grid = tk.BooleanVar(value=ao["grid_names"])
        self.ar_girder = tk.BooleanVar(value=ao["infer_girders"])
        self.ar_gw = tk.IntVar(value=int(ao["girder_width"]))
        self.host = tk.StringVar(value=self.cfg["ollama_host"])
        self.model = tk.StringVar(value=self.cfg["ollama_model"])
        osc = self.cfg.get("osnap", {})
        self.os_on = tk.BooleanVar(value=osc.get("on", True))
        self.os_modes = {k: tk.BooleanVar(value=osc.get(k, d)) for k, d in
                         (("node", True), ("end", True), ("mid", True), ("int", True), ("per", True),
                          ("nea", False), ("grid", True), ("member", True))}
        self.snap_px = tk.IntVar(value=osc.get("px", 10))

        self._build_header()
        self.rb = ttk.Notebook(self.root)
        self.rb.pack(fill="x", padx=0, pady=(0, 0))
        tabs = {}
        for key, title in (("file", "파일"), ("view", "보기"), ("edit", "편집"), ("struct", "구조도면 분석"),
                           ("arch", "건축도면 분석"), ("survey", "현장조사"), ("help", "도움말")):
            f = ttk.Frame(self.rb, padding=(6, 6))
            self.rb.add(f, text=f"  {title}  ")
            tabs[key] = f
        self.tabs = tabs
        self.rb.bind("<<NotebookTabChanged>>", self._tab_changed)
        self._rib_file(tabs["file"])
        self._rib_view(tabs["view"])
        self._rib_edit(tabs["edit"])
        self._rib_struct(tabs["struct"])
        self._rib_arch(tabs["arch"])
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

        self.info_box = ttk.Frame(right)
        self.info_box.pack(fill="both", expand=True)
        self._build_info(self.info_box)
        self._build_sv_panel(right)
        self._build_sv_strip(left)

        lf = tk.Frame(self.root, bg=TH.LINE)
        lf.pack(fill="x")
        self.log_txt = tk.Text(lf, height=4, font=("Consolas", 9), bg=TH.PANEL, fg="#4B5563", relief="flat",
                               padx=10, pady=4, highlightthickness=0)
        self.log_txt.pack(fill="x", side="left", expand=True, pady=(1, 0))
        self.status = ttk.Label(self.root, text="DXF 평면도를 열거나 DB에서 불러오세요.", anchor="w",
                                style="Status.TLabel")
        self.status.pack(fill="x")

    def _build_header(self):
        from . import __version__
        hd = tk.Frame(self.root, bg=TH.NAVY, height=46)
        hd.pack(fill="x")
        hd.pack_propagate(False)
        logo = TH.image("icon_32.png")
        if logo is not None:
            tk.Label(hd, image=logo, bg=TH.NAVY).pack(side="left", padx=(14, 8))
        tk.Label(hd, text=TH.APP_NAME, bg=TH.NAVY, fg="white", font=(TH.FAM, 15, "bold")).pack(side="left")
        tk.Label(hd, text=TH.APP_SUB, bg=TH.NAVY, fg=TH.ORANGE, font=(TH.FAM, 10, "bold")).pack(side="left",
                                                                                         padx=(8, 0), pady=(5, 0))
        tk.Frame(hd, bg=TH.NAVY_3, width=1).pack(side="left", fill="y", padx=16, pady=11)
        self.hd_doc = tk.Label(hd, text="도면을 열거나 DB에서 불러오세요", bg=TH.NAVY, fg="#C9D3E4", font=TH.FONT_M)
        self.hd_doc.pack(side="left")
        tk.Label(hd, text=f"v{__version__}", bg=TH.NAVY, fg=TH.NAVY_L, font=TH.FONT_S).pack(side="right", padx=(6, 14))
        self.hd_ai = tk.Label(hd, text="● AI 확인 중", bg=TH.NAVY, fg=TH.NAVY_L, font=TH.FONT)
        self.hd_ai.pack(side="right", padx=6)
        self.hd_lic = tk.Label(hd, text="", bg=TH.NAVY, fg=TH.NAVY_L, font=TH.FONT, cursor="hand2")
        self.hd_lic.pack(side="right", padx=10)
        self.hd_lic.bind("<Button-1>", lambda e: self.help_license())
        self.root.after(200, self._show_license)

    # ---------------------------------------------------------------- ribbon helpers
    @staticmethod
    def _grp(parent, title):
        g = ttk.LabelFrame(parent, text=title, padding=(6, 2))
        g.pack(side="left", fill="y", padx=3)
        return g

    @staticmethod
    def _big(parent, text, cmd, w=9, accent=False):
        b = ttk.Button(parent, text=text, command=cmd, width=w,
                       style="RibbonAccent.TButton" if accent else "Ribbon.TButton")
        b.pack(side="left", padx=2, pady=2, fill="y")
        return b

    def _rib_file(self, p):
        g = self._grp(p, "도면")
        self._big(g, "📂\nDXF 열기", self.open_file, accent=True)
        self._big(g, "⬚\n영역 선택", self.back_to_preview)
        self._big(g, "▶\n구조도면\n분석 시작", lambda: self.start_analysis("struct"), 9)
        self._big(g, "▶\n건축도면\n분석 시작", lambda: self.start_analysis("arch"), 9)
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
                 ("부재명", self.show_names), ("절점", self.show_nodes), ("검측위치", self.show_survey),
                 ("스케치", self.show_sketch), ("배경 사진", self.show_photo))
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
                                   justify="left", font=(TH.FAM, 8))
        self.tool_help.pack()

    def _rib_struct(self, p):
        g = self._grp(p, "1. 영역 → 분석")
        self._big(g, "⬚\n영역 선택", self.back_to_preview, 8)
        self._big(g, "▶\n분석 시작", lambda: self.start_analysis("struct"), 9, accent=True)
        self._big(g, "🗂\n레이어\n매핑", self.show_layers, 7)
        self._big(g, "↻\n다시 분석", self.reanalyze, 8)
        opt = ttk.Frame(g)
        opt.pack(side="left", padx=4)
        ttk.Checkbutton(opt, text="미표기 이름 추정", variable=self.infer, command=self._save_cfg).pack(anchor="w")
        ttk.Checkbutton(opt, text="WallGirder 자동 정리", variable=self.wg_var, command=self._save_cfg).pack(anchor="w")
        g = self._grp(p, "2. AI 2차 검토")
        self._big(g, "🤖\n2차 검토\n실행", self.ai_review, 9)
        opt = ttk.Frame(g)
        opt.pack(side="left", padx=4)
        ttk.Checkbutton(opt, text="분석 후 자동 실행", variable=self.auto_review, command=self._save_cfg).pack(anchor="w")
        ttk.Checkbutton(opt, text="레이어 역할 검증", variable=self.rv_layers, command=self._save_cfg).pack(anchor="w")
        ttk.Checkbutton(opt, text="거더 끝 기둥 추정", variable=self.rv_cols, command=self._save_cfg).pack(anchor="w")
        g = self._grp(p, "후처리")
        self._big(g, "▤\nWallGirder\n정리", self.wall_girder_cleanup, 10)
        self._big(g, "⛓\n절점 다시\n연결", self.rebuild_nodes, 9)
        self._ollama_group(p)

    def _rib_arch(self, p):
        g = self._grp(p, "1. 영역 → 분석")
        self._big(g, "⬚\n영역 선택", self.back_to_preview, 8)
        self._big(g, "▶\n분석 시작", lambda: self.start_analysis("arch"), 9, accent=True)
        self._big(g, "🗂\n레이어\n매핑", self.show_layers, 7)
        self._big(g, "↻\n다시 분석", self.reanalyze, 8)
        g = self._grp(p, "건축도면 → 구조부재")
        ttk.Checkbutton(g, text="비내력벽(조적·경량) 포함", variable=self.ar_part, command=self._save_cfg).grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(g, text="벽 최소 두께").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(g, from_=80, to=400, increment=10, textvariable=self.ar_minw, width=5,
                    command=self._save_cfg).grid(row=1, column=1, sticky="w")
        ttk.Label(g, text="mm 미만 제외").grid(row=1, column=2, sticky="w")
        ttk.Checkbutton(g, text="그리드 이름으로 기둥 명명 (X2-Y3)", variable=self.ar_grid,
                        command=self._save_cfg).grid(row=0, column=3, columnspan=3, sticky="w", padx=(10, 0))
        ttk.Checkbutton(g, text="기둥열 사이 거더 추정, 폭", variable=self.ar_girder,
                        command=self._save_cfg).grid(row=1, column=3, sticky="w", padx=(10, 0))
        ttk.Spinbox(g, from_=200, to=1200, increment=50, textvariable=self.ar_gw, width=5,
                    command=self._save_cfg).grid(row=1, column=4, sticky="w")
        g = self._grp(p, "2. AI 2차 검토")
        self._big(g, "🤖\n2차 검토\n실행", self.ai_review, 9)
        ttk.Checkbutton(g, text="분석 후\n자동 실행", variable=self.auto_review, command=self._save_cfg).pack(
            side="left", padx=4)
        self._ollama_group(p)

    def _ollama_group(self, p):
        if not hasattr(self, "model_cbs"):
            self.model_cbs, self.ai_states = [], []
        g = self._grp(p, "Ollama")
        ttk.Checkbutton(g, text="사용", variable=self.use_ai, command=self._save_cfg).grid(row=0, column=0, sticky="w")
        st = ttk.Label(g, text="●", foreground="#999")
        st.grid(row=0, column=1, sticky="w")
        self.ai_states.append(st)
        ttk.Entry(g, textvariable=self.host, width=24).grid(row=0, column=2, columnspan=2, sticky="w")
        ttk.Label(g, text="모델").grid(row=1, column=0, sticky="w")
        cb = ttk.Combobox(g, textvariable=self.model, width=20)
        cb.grid(row=1, column=1, columnspan=2, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self._save_cfg())
        self.model_cbs.append(cb)
        ttk.Button(g, text="⟳", width=3, command=self._refresh_models).grid(row=1, column=3, sticky="w")

    def _rib_survey(self, p):
        g = self._grp(p, "검측 도구")
        for i, (k, t) in enumerate((("select", "선택"), ("point", "검측점"), ("span", "검측구간"),
                                    ("delete", "삭제"))):
            ttk.Radiobutton(g, text=t, value=k, variable=self.sv_tool, command=self._sv_tool_changed,
                            style="Toolbutton").grid(row=i // 2, column=i % 2, sticky="ew", padx=1, pady=1)
        g = self._grp(p, "새 검측 용도")
        self.sv_purpose_cb = ttk.Combobox(g, textvariable=self.sv_purpose, values=list(self.P), state="readonly",
                                          width=14, font=(TH.FAM, 10))
        self.sv_purpose_cb.pack(anchor="w")
        ttk.Button(g, text="＋ 용도 추가", command=self._sv_add_purpose).pack(anchor="w", pady=(4, 0))
        g = self._grp(p, "도면 없이")
        self._big(g, "📷\n새 조사\n도면", self.new_field_sheet, 7)
        self._big(g, "📏\n축척\n맞추기", self.calibrate_scale, 7)
        g = self._grp(p, "기록")
        self._big(g, "📤\n조사표 CSV", self.survey_export, 10)
        self._big(g, "📑\n도면 LIST", self._sv_sheet_list, 9)
        ttk.Checkbutton(g, text="검측위치\n표시", variable=self.show_survey, command=self.redraw).pack(side="left", padx=4)
        self.sv_vis_mb = ttk.Menubutton(g, text="👁 표시할\n조사 ▾", direction="below")
        self.sv_vis_menu = tk.Menu(self.sv_vis_mb, tearoff=0, postcommand=self._sv_vis_build)
        self.sv_vis_mb["menu"] = self.sv_vis_menu
        self.sv_vis_mb.pack(side="left", padx=4)
        ttk.Checkbutton(g, text="현장\n스케치", variable=self.show_sketch, command=self.redraw).pack(side="left", padx=4)
        g = self._grp(p, "부재")
        self.sched_btn = self._big(g, "📋\n부재\n리스트", lambda: self.toggle_schedule(), 8)
        g = self._grp(p, "휴대폰·패드")
        self._big(g, "📱\n모바일로\n내보내기", self.mobile_export, 9)
        self._big(g, "📥\n모바일 DB\n가져오기", self.mobile_import, 9)
        self.wifi_btn = self._big(g, "📶\nWi-Fi\n연결", self.mobile_wifi, 7)
        g = self._grp(p, "안내")
        self.sv_help = ttk.Label(g, font=(TH.FAM, 8), foreground="#555", justify="left", wraplength=360,
                                 text=SV_HELP["point"])
        self.sv_help.pack()

    def _rib_help(self, p):
        g = self._grp(p, "도움말")
        self._big(g, "📖\n사용법", self.help_usage)
        self._big(g, "⌨\n단축키", self.help_keys)
        self._big(g, "🔑\n라이선스", self.help_license)
        self._big(g, "ℹ\n정보", self.help_about)

    def _build_info(self, parent):
        info = ttk.LabelFrame(parent, text="부재 정보", padding=8)
        info.pack(fill="x", padx=2, pady=(4, 2))
        nm = ttk.Frame(info)
        nm.pack(fill="x")
        self.name_var = tk.StringVar(value="-")
        self.name_lbl = ttk.Label(nm, textvariable=self.name_var, font=(TH.FAM, 14, "bold"))
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
                        wall_girder=self.wg_var.get(), auto_review=self.auto_review.get(),
                        review_layers=self.rv_layers.get(), review_columns=self.rv_cols.get(),
                        analysis_kind=self.analysis_kind, arch=self._arch_opts())
        S.save(self.cfg)

    def _arch_opts(self):
        def iv(v, d):
            try:
                return int(v.get())
            except (tk.TclError, ValueError):
                return d
        return {"include_partitions": self.ar_part.get(), "min_wall": iv(self.ar_minw, 150),
                "grid_names": self.ar_grid.get(), "infer_girders": self.ar_girder.get(),
                "girder_width": iv(self.ar_gw, 400)}

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
                    for w in self.ai_states:
                        w.config(foreground=TH.NG)
                    self.hd_ai.config(text="● AI 꺼짐 (규칙 사용)", fg="#F3A3A3")
                    self.log(f"Ollama 미연결 — 규칙 기반으로 동작합니다. ({host})")
                    return
                for cb in self.model_cbs:
                    cb["values"] = ms
                if ms and self.model.get() not in ms:
                    self.model.set(ms[0])
                for w in self.ai_states:
                    w.config(foreground=TH.OK if ms else TH.ORANGE)
                self.hd_ai.config(text=f"● AI {self.model.get() or '모델 없음'}", fg="#7EE0A1" if ms else TH.ORANGE)
                self.log(f"Ollama 연결됨: 모델 {len(ms)}개" + ("" if ms else " (ollama pull 로 모델 설치 필요)"))
                self._save_cfg()
            self.q.put(("call", fin))
        threading.Thread(target=work, daemon=True).start()

    def _set_dirty(self, v=True):
        self.dirty = v
        base = f"{TH.APP_NAME} {TH.APP_SUB}"
        name = self.db_name or (os.path.basename(self.res.source_file) if self.res else "")
        self.root.title(f"{base} — {name}{' *' if v else ''}" if name else base)
        if hasattr(self, "hd_doc"):
            kind = {"arch": "건축도면", "struct": "구조도면"}.get(getattr(self.res, "kind", ""), "") if self.res else ""
            parts = [p for p in (self.project, name, kind) if p]
            self.hd_doc.config(text=("  ·  ".join(parts) + ("   ● 저장 안 됨" if v else "")) if parts
                               else "도면을 열거나 DB에서 불러오세요")

    def _confirm_discard(self):
        if hasattr(self, "_sv_edit") and not self._sv_guard():
            return False
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
            filetypes=[("DXF / DWG / 도면 사진", "*.dxf *.dwg *.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp"),
                       ("DXF", "*.dxf"), ("도면 사진·이미지", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp"),
                       ("모든 파일", "*.*")])
        if not path:
            return
        self.cfg["last_dir"] = os.path.dirname(path)
        self._save_cfg()
        if os.path.splitext(path)[1].lower() in IMG_EXT:
            self.new_field_sheet(path=path, mode="recognize", confirmed=True)
            return
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
            self.region, self.region_label, self.sub = None, "", None
            self.undo_stack.clear(); self.redo_stack.clear()
            self._set_dirty(False)
            self._fill_tree(); self._show_info(None)
            self.mode = "preview"
            n = len(self.plans)
            if n == 1:
                self.select_region(self.plans[0], "평면 1", quiet=True)
            self.fit()
            self.log(f"평면 후보 {n}개 — 분석할 평면을 클릭해서 선택한 뒤, [구조도면 분석] 또는 [건축도면 분석] 탭의 "
                     f"▶ 분석 시작을 누르세요. (드래그 = 영역 지정, 빈 곳 더블클릭 = 전체)")
            if self._tab_key() not in ("struct", "arch"):
                self.rb.select(self.tabs["arch" if self.analysis_kind == "arch" else "struct"])
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
        self.log("분석할 평면을 클릭(또는 드래그)해서 선택한 뒤 ▶ 분석 시작을 누르세요."
                 + (f" 현재 선택: {self.region_label}" if self.region else ""))

    def select_region(self, rect, label="", quiet=False):
        """Mark the area to analyse (nothing is analysed until ▶ 분석 시작)."""
        x0, y0, x1, y1 = rect
        self.region = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        w, h = (self.region[2] - self.region[0]) / 1000, (self.region[3] - self.region[1]) / 1000
        self.region_label = f"{label or '지정 영역'} ({w:,.1f} × {h:,.1f} m)"
        self.sub = None
        if self.mode == "preview":
            self.redraw()
        msg = f"선택: {self.region_label} → ▶ 분석 시작 (구조도면 / 건축도면)"
        self.status.config(text=msg)
        if not quiet:
            self.log(msg)

    def _mem_key(self, kind=None):
        return "layer_memory_arch" if (kind or self.analysis_kind) == "arch" else "layer_memory"

    def start_analysis(self, kind):
        if self.busy:
            return
        if self.dd is None:
            path = self.res.source_file if self.res else ""
            if path and os.path.exists(path):
                messagebox.showinfo("분석 시작", "원본 DXF를 다시 읽은 뒤 영역을 선택하고 ▶ 분석 시작을 누르세요.",
                                    parent=self.root)
                if self._confirm_discard():
                    self.load_path(path)
            else:
                messagebox.showinfo("분석 시작", "먼저 파일 › DXF 열기로 도면을 여세요.", parent=self.root)
            return
        if self.region is None:
            if len(self.plans) == 1:
                self.select_region(self.plans[0], "평면 1", quiet=True)
            elif messagebox.askyesno("분석 시작", "분석할 평면이 선택되지 않았습니다.\n도면 전체를 분석할까요?\n"
                                     "(아니오 → 평면을 클릭해서 선택한 뒤 다시 누르세요)", parent=self.root):
                self.select_region(self.dd.extents, "도면 전체", quiet=True)
            else:
                if self.mode != "preview":
                    self.back_to_preview()
                return
        if self.res is not None and self.dirty and self.undo_stack and not messagebox.askyesno(
                "분석 시작", "현재 분석의 편집 내용이 사라집니다. 계속할까요?", parent=self.root):
            return
        self.analysis_kind = kind
        self._review_next = None
        self._save_cfg()
        self.rb.select(self.tabs[kind])
        self.sub = crop(self.dd, self.region)
        n = sum(len(l.segments) for l in self.sub.layers.values())
        ko = "건축도면" if kind == "arch" else "구조도면"
        self.log(f"[{ko} 분석] {self.region_label}: 선 {n:,}개 · 레이어 {len(self.sub.layers)}개")
        client = self._client()
        sub = self.sub
        part = self.ar_part.get()
        mem = self.cfg.get(self._mem_key(kind), {})

        def work():
            self.log(f"{'Ollama(' + client.model + ')' if client else '규칙'}로 레이어 분류 중…")
            sums = sub.layer_summaries()
            if kind == "arch":
                roles = classify_arch_layers(sums, client, part, log=self.log)
            else:
                roles = classify_layers(sums, client, log=self.log)
            for k in roles:
                if k in mem and mem[k] in LAYER_ROLES:
                    roles[k] = (mem[k], "저장됨")
            if kind == "arch":
                return roles
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
            self.cfg.setdefault(self._mem_key(), {}).update(edited)
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

    def _run_analysis(self, roles, review=("layer", "member")):
        client, sub, infer, wg = self._client(), self.sub, self.infer.get(), self.wg_var.get()
        kind, aopts = self.analysis_kind, self._arch_opts()
        from_review = self._review_next is not None
        keep = (self.db_id, self.db_name) if from_review else (None, "")

        def work():
            if kind == "arch":
                return analyze_arch(sub, roles, client=client, opts=aopts, log=self.log)
            return analyze(sub, roles, client=client, infer_names=infer, wall_girder=wg, log=self.log)

        def done(res):
            res.region = self.region
            res.source_file = self.dd.path if self.dd else sub.path
            res.kind = kind
            self._set_result(res, keep_cs=True)
            self.db_id, self.db_name = keep
            self._set_dirty(True)
            stages, self._review_next = (self._review_next or review), None
            if (self.auto_review.get() or from_review) and stages:
                self.log("1차 분석 완료 → 2차 AI 검토를 시작합니다.")
                self.root.after(50, lambda: self.ai_review(stages=stages, auto=True))
        self._run_bg(work, done, ("건축도면" if kind == "arch" else "구조도면") + " 1차 분석 중…")

    def _set_result(self, res, keep_cs=False):
        self.res = res
        self.analysis_kind = getattr(res, "kind", "struct") or "struct"
        if not getattr(res, "schedule", None):
            res.schedule = []
            SC.merge_estimate(res.schedule, res)
        if hasattr(self, "sched_box") and self.sched_box.winfo_ismapped():
            self.sched_box.refresh()
        self.members = res.members
        self.sel = None
        self.mode = "result"
        self.undo_stack.clear(); self.redo_stack.clear()
        self._grid_intersections()
        self.osnap = OSnap(res.background + res.grid)
        for r in res.surveys:
            SV.migrate(r)
        self.sel_sv = None
        self._sv_edit = None
        if hasattr(self, "sv_tv"):
            self._sv_refresh_list()
            self._sv_fill_form()
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

    # ======================================================================= 도면 없이 현장조사
    def new_field_sheet(self, path="", mode="blank", confirmed=False):
        """빈 도면 / 사진 배경 / 종이 도면 사진 인식으로 조사 도면 만들기."""
        if self.busy or (not confirmed and not self._confirm_discard()):
            return
        if confirmed and not self._confirm_discard():
            return
        from .dialogs import NewSheetDialog
        NewSheetDialog(self.root, self.project, self._ns_go, mode=mode, path=path)

    def _ns_go(self, o):
        if o["mode"] == "blank":
            res = SH.new_blank(o["w"], o["h"])
            self._ns_finish(res, o, f"빈 도면 {o['w']:g}×{o['h']:g} m")
            return
        from . import photo_plan as PP
        ok, why = PP.available()
        if not ok and (o["mode"] == "recognize" or o.get("warp")):
            if o["mode"] == "recognize":
                messagebox.showerror("도면 사진 인식", why + "\n\n터미널에서:  pip install -r requirements.txt\n"
                                     f"(지금 파이썬: {sys.executable})", parent=self.root)
                return
            o["warp"] = False
        corners = None
        if o.get("warp") and ok:
            try:
                img = PP.read_image(o["path"])
                corners = PP.detect_corners(img)
                o["k_mm"] = PP.paper_k(corners, o["paper"], o["scale"])    # 용지 기준 축척 (영역을 잘라도 유지)
                from PIL import Image
                import cv2
                pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            except Exception as e:      # noqa: BLE001
                messagebox.showerror("사진 열기", str(e), parent=self.root)
                return
            from .dialogs import CornerDialog
            CornerDialog(self.root, pil, corners, lambda pts: self._ns_photo(o, pts))
            return
        self._ns_photo(o, None)

    def _ns_photo(self, o, corners):
        from . import photo_plan as PP
        path = o["path"]

        def work():
            if o["mode"] == "recognize":
                flat, res, k, _t = PP.recognize_photo(path, corners=corners, k_mm=o.get("k_mm"), paper=o["paper"],
                                                      scale=o["scale"], log=self.log)
                import cv2
                from PIL import Image
                pil = Image.fromarray(cv2.cvtColor(flat, cv2.COLOR_BGR2RGB))
                p, _iw, _ih = SH.store_image(None, img=pil)
                res.bg_image, res.bg_rect, res.sheet_uid = p, tuple(res.extents), SH.new_uid()   # 펴진 사진 전체 = 도면 범위
                res.source_file = path
                return res
            if corners:
                import cv2
                from PIL import Image
                flat = PP.warp(PP.read_image(path), corners)
                pil = Image.fromarray(cv2.cvtColor(flat, cv2.COLOR_BGR2RGB))
                w = pil.size[0]
            else:
                from PIL import Image, ImageOps
                pil = ImageOps.exif_transpose(Image.open(path))
                w = pil.size[0]
            k = o.get("k_mm") or PP.mm_per_px(w, o["paper"], o["scale"], pil.size[0] >= pil.size[1])
            return SH.new_image(path, mm_per_px=k, img=pil)

        def done(res):
            what = "종이 도면 사진 인식" if o["mode"] == "recognize" else "사진 배경"
            self._ns_finish(res, o, what)
        self._run_bg(work, done, "도면 사진 처리 중…" if o["mode"] == "recognize" else "사진 준비 중…")

    def _ns_finish(self, res, o, what):
        self.dd, self.sub, self.plans = None, None, []
        self.region, self.region_label = None, ""
        self.cs = CoordSystem()
        self.analysis_kind = "struct"
        self._set_result(res)
        self.db_id, self.db_name, self.project = None, o["name"], o["project"]
        try:
            self.db_id = db.save(res, None, o["name"], None, project=o["project"])
            self._set_dirty(False)
        except Exception as e:      # noqa: BLE001
            self._set_dirty(True)
            self.log(f"DB 저장 실패: {e}")
        self._sv_refresh_pager()
        self.rb.select(self.tabs["struct" if o["mode"] == "recognize" else "survey"])
        self.log(f"새 조사 도면: [{o['project'] or '-'}] '{o['name']}' — {what}"
                 + ("  · 인식 결과는 후보입니다. 사진을 배경으로 편집 탭에서 고치세요." if o["mode"] == "recognize" else
                    "  · 현장조사 탭에서 검측위치를 찍으세요."))
        if o["mode"] != "blank":
            self.log("축척이 다르면 현장조사 › 📏 축척 맞추기로 아는 길이 두 점을 찍어 맞추세요.")

    def calibrate_scale(self):
        if not self.res:
            messagebox.showinfo("축척 맞추기", "먼저 조사 도면을 여세요.", parent=self.root)
            return
        if getattr(self.res, "kind", "") not in ("photo", "blank"):
            if not messagebox.askyesno("축척 맞추기", "DXF에서 분석한 도면은 이미 실제 치수입니다.\n그래도 축척을 바꿀까요?",
                                       parent=self.root):
                return
        self._calib = []
        self.status.config(text="📏 축척 맞추기: 길이를 아는 두 점(예: 그리드 간격·기둥 중심)을 차례로 클릭하세요. (Esc 취소)")
        self.log("축척 맞추기: 두 점을 클릭하세요.")

    def _calib_click(self, x, y):
        self._calib.append((x, y))
        r = 6
        sx, sy = self.w2s(x, y)
        self.cv.create_oval(sx - r, sy - r, sx + r, sy + r, outline=TH.ORANGE, width=3, tags="calib")
        if len(self._calib) < 2:
            return
        (ax, ay), (bx, by) = self._calib
        self._calib = None
        self.cv.create_line(*self.w2s(ax, ay), *self.w2s(bx, by), fill=TH.ORANGE, width=3, tags="calib")
        cur = math.hypot(bx - ax, by - ay)
        if cur < 1e-6:
            self.redraw()
            return
        v = simpledialog.askfloat("축척 맞추기", f"두 점 사이 실제 길이 (m)\n(지금 도면상 {cur / 1000:.3f} m)",
                                  parent=self.root, minvalue=0.001)
        if not v:
            self.redraw()
            self.status.config(text="축척 맞추기 취소")
            return
        f = v * 1000 / cur
        SH.rescale(self.res, f, ax, ay)
        self.osnap = OSnap(self.res.background + self.res.grid)
        self._grid_intersections()
        self._set_dirty(True)
        self.s /= f
        self.ox, self.oy = ax - (ax - self.ox) * f, ay - (ay - self.oy) * f
        self.redraw()
        self.undo_stack.clear(); self.redo_stack.clear()
        self.log(f"축척 맞춤: ×{f:.4f} (두 점 = {v:g} m). 저장하려면 Ctrl+S · 되돌리려면 다시 축척 맞추기")
        self.status.config(text=f"축척을 맞췄습니다 (×{f:.3f}).")

    # ======================================================================= DB
    def _ctrl_s(self, event=None, as_new=False):
        """Ctrl+S — 입력 중인 현장조사 항목을 먼저 확정하고 DB에 저장."""
        if self.busy:
            return "break"
        if getattr(self, "_sv_edit", None) is not None:
            try:
                self._sv_save_edit()
            except Exception as e:      # noqa: BLE001
                self.log(f"현장조사 입력 저장 실패: {e}")
        if self.res is None:
            self.status.config(text="저장할 분석이 없습니다.")
            return "break"
        if self.save_db(as_new=as_new):
            self._flash_saved()
        return "break"

    def _flash_saved(self):
        try:
            self.hd_doc.config(text="✔ 저장했습니다  (Ctrl+S)", fg=TH.ORANGE)
            self.root.after(1500, lambda: (self.hd_doc.config(fg="#C9D3E4"), self._set_dirty(False)))
        except (tk.TclError, AttributeError):
            pass

    def save_db(self, as_new=False):
        if not self.res:
            messagebox.showinfo("저장", "저장할 분석이 없습니다.", parent=self.root)
            return False
        aid = None if as_new else self.db_id
        project, name = self.project, self.db_name
        if aid is None:
            base = os.path.splitext(os.path.basename(self.res.source_file or "분석"))[0]
            out = {}
            dlg = SaveDialog(self.root, project, self.db_name or base,
                             lambda p, n: out.update(p=p, n=n))
            self.root.wait_window(dlg)
            if not out:
                return False
            project, name = out["p"], out["n"]
        cs = None if self.cs.is_identity() else self.cs
        try:
            self.db_id = db.save(self.res, cs, name, aid, project=project)
        except Exception as e:      # noqa: BLE001
            messagebox.showerror("DB 저장", str(e), parent=self.root)
            return False
        self.project, self.db_name = project, name
        self._set_dirty(False)
        self._sv_refresh_pager()
        self.log(f"DB 저장: [{project or '-'}] '{name}' (id {self.db_id}) → {db.DB_PATH}")
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
        mt = db.meta(aid)
        self.project = (mt[1] or "") if mt else ""
        self._set_dirty(False)
        self._sv_refresh_pager()
        self.log(f"DB 불러오기: [{self.project or '-'}] '{name}' — 부재 {len(res.members)}개, "
                 f"절점 {len(res.nodes)}개, 검측위치 {len(res.surveys)}개")

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
        if self.mode is None:
            self._draw_welcome()
            return
        if self.cv.cget("bg") != BG:
            self.cv.configure(bg=BG)
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
            if self.region and all(abs(u - v) < 1e-6 for u, v in zip(p, self.region)):
                continue
            cv.create_rectangle(*a, *b, outline="#2563eb", dash=(6, 4), width=2, tags=("plan", f"plan{i}"))
            cv.create_text(a[0] + 6, a[1] + 6, anchor="nw", text=f"평면 {i}", fill="#2563eb",
                           font=(TH.FAM, 12, "bold"))
        W = self.cv.winfo_width()
        if self.region:
            a = self.w2s(self.region[0], self.region[3])
            b = self.w2s(self.region[2], self.region[1])
            cv.create_rectangle(*a, *b, outline="", fill="#f59e0b", stipple="gray12")
            cv.create_rectangle(*a, *b, outline="#f59e0b", width=4)
            tx, ty = max(a[0], 8), max(a[1], 34)
            cv.create_text(tx + 8, ty + 8, anchor="nw", text="✔ 선택됨: " + self.region_label, fill="#b45309",
                           font=(TH.FAM, 12, "bold"))
            cv.create_window(min(tx + 8, max(W - 330, 8)), ty + 36, anchor="nw", window=self._start_bar())
            hint = "선택한 영역을 확인하고 ▶ 분석 시작을 누르세요 · 다른 평면 클릭 = 선택 변경 · 드래그 = 영역 직접 지정"
        else:
            hint = "① 분석할 평면(파란 박스)을 클릭  ② 또는 드래그로 영역 지정  ③ 빈 곳 더블클릭 = 도면 전체 선택"
        cv.create_rectangle(0, 0, W, 28, fill="#fff7e6", outline="")
        cv.create_text(10, 14, anchor="w", fill="#111", font=(TH.FAM, 10, "bold"), text=hint)

    def _start_bar(self):
        if getattr(self, "_sbar", None) is None:
            f = tk.Frame(self.cv, bg="#ffffff", highlightthickness=1, highlightbackground="#f59e0b")
            ttk.Button(f, text="▶ 구조도면 분석 시작", style="Accent.TButton",
                       command=lambda: self.start_analysis("struct")).pack(side="left", padx=3, pady=3)
            ttk.Button(f, text="▶ 건축도면 분석 시작", style="Accent.TButton",
                       command=lambda: self.start_analysis("arch")).pack(side="left", padx=3, pady=3)
            self._sbar = f
        return self._sbar

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
        if getattr(self.res, "bg_image", "") and self.show_photo.get():
            self._bgimg.draw(cv, self.res, self.w2s, (x0, y0, x1, y1), cv.winfo_width(), cv.winfo_height())

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
                    if name_ok and (m.name or m.layer != "사진"):        # 사진 인식의 이름 없는 부재는 글자 생략
                        cv.create_text(sx + 7, sy - 6, text=m.display_name(), anchor="sw",
                                       fill=col, font=(TH.FAM, 8), tags=(tag,))
                    continue
                pts = m.polyline()
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                if not vis(min(xs), min(ys), max(xs), max(ys)):
                    continue
                flat = [c for p in pts for c in self.w2s(*p)]
                cv.create_line(*flat, fill=col, width=2 if kind != "wall" else 3, dash=dash, tags=(tag,))
                if name_ok and m.length_cc * self.s > 40 and (m.name or m.layer != "사진"):
                    if m.curved:
                        mx, my = self.w2s(*pts[len(pts) // 2]); ang = 0
                    else:
                        mx, my = self.w2s((pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2)
                        ang = m.angle if m.angle <= 90 else m.angle - 180
                    txt = m.display_name() if kind != "wall" else (m.name or f"W{m.width:.0f}")
                    if m.auto:
                        txt = "◆" + txt
                    try:
                        cv.create_text(mx, my - 7, text=txt, angle=ang, fill=col, font=(TH.FAM, 8),
                                       tags=(tag,))
                    except tk.TclError:
                        cv.create_text(mx, my - 7, text=txt, fill=col, font=(TH.FAM, 8), tags=(tag,))
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
        # 현장 스케치 (휴대폰에서 그린 보·기둥·벽·자유선·글자)
        if self.show_sketch.get() and getattr(self.res, "sketches", None):
            self._draw_sketches()
        # survey points / sections
        if self.show_survey.get() and self.res.surveys:
            byid = self.res.by_id()
            for rec in self.res.surveys:
                if rec.get("purpose") not in self.sv_hidden:
                    self._draw_survey(rec, byid)
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

    def _draw_sketches(self):
        """휴대폰 현장 스케치 표시 (절점 연동 없음, 도면 좌표 그대로)."""
        cv = self.cv
        for sk in self.res.sketches:
            if sk.get("deleted"):
                continue
            p = sk.get("pts") or []
            col = sk.get("color") or "#e11d48"
            kind = sk.get("kind")
            tag = ("sketch",)
            try:
                if kind in ("beam", "wall") and len(p) >= 4:
                    a, b = self.w2s(p[0], p[1]), self.w2s(p[2], p[3])
                    cv.create_line(*a, *b, fill=col, width=9 if kind == "wall" else 4, capstyle="round",
                                   stipple="gray75" if kind == "wall" else "", tags=tag)
                    if kind == "beam":
                        for q in (a, b):
                            cv.create_oval(q[0] - 3, q[1] - 3, q[0] + 3, q[1] + 3, fill=col, outline="", tags=tag)
                elif kind == "column" and len(p) >= 4:
                    a, b = self.w2s(p[0], p[1]), self.w2s(p[2], p[3])
                    cv.create_rectangle(*a, *b, outline=col, width=2, fill=col, stipple="gray25", tags=tag)
                    cv.create_line(*a, *b, fill=col, tags=tag)
                    cv.create_line(a[0], b[1], b[0], a[1], fill=col, tags=tag)
                    w, h = abs(p[2] - p[0]), abs(p[3] - p[1])
                    if abs(b[0] - a[0]) > 30:
                        cv.create_text((a[0] + b[0]) / 2, min(a[1], b[1]) - 3, anchor="s", text=f"{w:.0f}×{h:.0f}",
                                       fill=col, font=(TH.FAM, 8, "bold"), tags=tag)
                elif kind == "free" and len(p) >= 4:
                    cv.create_line(*[c for i in range(0, len(p) - 1, 2) for c in self.w2s(p[i], p[i + 1])],
                                   fill=col, width=2.5, capstyle="round", joinstyle="round", smooth=True, tags=tag)
                elif kind == "axis" and len(p) >= 4:          # X·Y 축(그리드) + 양 끝 버블
                    a, b = self.w2s(p[0], p[1]), self.w2s(p[2], p[3])
                    cv.create_line(*a, *b, fill=col, width=1.5, dash=(12, 4, 2, 4), tags=tag)
                    L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
                    ux, uy, R = (b[0] - a[0]) / L, (b[1] - a[1]) / L, 12
                    for q, sg in ((a, -1), (b, 1)):
                        cx, cy = q[0] + ux * R * sg, q[1] + uy * R * sg
                        cv.create_oval(cx - R, cy - R, cx + R, cy + R, outline=col, fill="white", width=2, tags=tag)
                        cv.create_text(cx, cy, text=sk.get("text", ""), fill=col, font=(TH.FAM, 9, "bold"), tags=tag)
                elif kind == "text" and len(p) >= 2:
                    x, y = self.w2s(p[0], p[1])
                    cv.create_text(x, y, text=sk.get("text", ""), fill=col, font=(TH.FAM, 10, "bold"), tags=tag)
            except tk.TclError:
                pass

    def _draw_survey(self, rec, byid, hl=False):
        cv = self.cv
        col = self.P.get(rec.get("purpose"), {}).get("color", "#d62828")
        g = SV.geometry(rec, byid)
        tag = ("survey", f"sv{rec['id']}") + (("sel",) if hl else ())
        if g[0] == "area":
            x0, y0, x1, y1 = g[1]
            a, b = self.w2s(x0, y1), self.w2s(x1, y0)
            cv.create_rectangle(*a, *b, fill=col, stipple="gray25" if hl else "gray12", outline="", tags=tag)
            cv.create_rectangle(*a, *b, outline=col, width=3 if hl else 2, dash=(10, 5), tags=tag)
            fl = rec.get("fields") or {}
            w, h = b[0] - a[0], b[1] - a[1]
            if w > 80 and h > 24:
                lines = [x for x in (rec.get("name") or "", fl.get("use"),
                                     " ".join(x for x in (fl.get("fin"), f"{fl['fin_t']}mm" if fl.get("fin_t") else "") if x),
                                     fl.get("ceil"), SV.load_text(fl)) if x]
                lines = lines[:max(1, int(h // 16))]
                cy = (a[1] + b[1]) / 2 - (len(lines) - 1) * 8
                for i, t in enumerate(lines):
                    cv.create_text((a[0] + b[0]) / 2, cy + i * 16, text=t, fill=col, width=w - 8,
                                   font=(TH.FAM, 9, "bold"), tags=tag)
            px, py = a
        elif g[0] == "span":
            a, b = self.w2s(*g[1]), self.w2s(*g[2])
            cv.create_line(*a, *b, fill=col, width=7 if not hl else 11, capstyle="butt", tags=tag)
            for q in (a, b):
                cv.create_line(q[0] - 1, q[1] - 1, q[0] + 1, q[1] + 1, fill=col, width=12, capstyle="round", tags=tag)
            px, py = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        else:
            px, py = self.w2s(*g[1])
            cv.create_oval(px - 3, py - 3, px + 3, py + 3, fill=col, outline=col, tags=tag)
        bx, by = self.w2s(*SV.bubble(rec, byid))
        r = 11 if not hl else 13
        # leader from the bubble edge to the point
        d = math.hypot(px - bx, py - by)
        if d > r:
            cv.create_line(bx + (px - bx) * r / d, by + (py - by) * r / d, px, py, fill=col, width=2, tags=tag)
        cv.create_oval(bx - r, by - r, bx + r, by + r, fill="white", outline=col, width=3 if not hl else 4, tags=tag)
        if hl:
            cv.create_oval(bx - r - 4, by - r - 4, bx + r + 4, by + r + 4, outline=SEL, width=3, tags=tag)
        cv.create_text(bx, by, text=str(rec.get("no", "")), fill=col, font=(TH.FAM, 9, "bold"), tags=tag)

    def _draw_selection(self):
        self.cv.delete("sel")
        if self.sel_sv is not None and self.res and self.mode == "result":
            rec = next((r for r in self.res.surveys if r["id"] == self.sel_sv), None)
            if rec:
                self._draw_survey(rec, self.res.by_id(), hl=True)
        m = self.sel
        if not m or self.mode != "result":
            self.cv.tag_raise("survey")
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
        self.cv.tag_raise("survey")

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
                       font=(TH.FAM, 8, "bold"), tags="snap")

    # ======================================================================= mouse
    def _tab_key(self):
        try:
            cur = self.rb.select()
        except tk.TclError:
            return None
        return next((k for k, f in getattr(self, "tabs", {}).items() if str(f) == cur), None)

    def _edit_tab(self):
        return self._tab_key() == "edit"

    def _survey_tab(self):
        return self._tab_key() == "survey"

    def _active_tool(self):
        return self.tool.get() if self._edit_tab() else "select"

    def _tab_changed(self, _e=None):
        if not hasattr(self, "cv") or not hasattr(self, "tool_help"):
            return
        self._line_start = None
        self._snap = None
        self._tool_changed()
        self._sv_start = None
        self._sv_area0 = None
        if self._survey_tab():
            self.status.config(text=SV_HELP[self.sv_tool.get()].split("\n")[0])
            if not (self.sv_box.winfo_ismapped() or self.sched_box.winfo_ismapped()):
                self.info_box.pack_forget()
                self.sv_strip.pack(fill="x", side="bottom", before=self.cv)
            self._show_sv_right()
            self._sv_refresh_pager()
            self._sv_refresh_list()
            self._sv_fill_form()
        elif self.sv_box.winfo_ismapped() or self.sched_box.winfo_ismapped():
            self._sv_guard()
            self.sv_box.pack_forget()
            self.sched_box.pack_forget()
            self.sv_strip.pack_forget()
            self.info_box.pack(fill="both", expand=True)
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
        self._sv_drag = None
        if self.mode == "result" and self._survey_tab() and self.sv_tool.get() != "delete" and not self._sv_start:
            rec = self._sv_bubble_hit(*self.s2w(e.x, e.y))
            if rec:
                self._sv_drag = {"rec": rec, "pushed": False}
                return
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
        if self._sv_drag:
            if not self._sv_drag["pushed"]:
                self._push_undo()
                self._sv_drag["pushed"] = True
            rec = self._sv_drag["rec"]
            rec = next((r for r in self.res.surveys if r["id"] == rec["id"]), rec)
            self._sv_drag["rec"] = rec
            ax, ay = SV.anchor(rec, self.res.by_id())
            x, y = self.s2w(e.x, e.y)
            rec["bx"], rec["by"] = x - ax, y - ay
            self.redraw()
            return
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
        if self._sv_drag:
            dr, self._sv_drag = self._sv_drag, None
            if dr["pushed"]:
                self._set_dirty(True)
            self._sv_select(dr["rec"]["id"])
            return
        if self.mode == "preview":
            self.cv.delete("rubber")
            if p and p[4]:
                a = self.s2w(p[0], p[1])
                b = self.s2w(e.x, e.y)
                if abs(e.x - p[0]) > 10 and abs(e.y - p[1]) > 10:
                    self.select_region((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])),
                                       "드래그 영역")
                else:
                    self.redraw()
            else:
                x, y = self.s2w(e.x, e.y)
                hits = [r for r in self.plans if r[0] <= x <= r[2] and r[1] <= y <= r[3]]
                if hits:
                    r = min(hits, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
                    self.select_region(r, f"평면 {self.plans.index(r) + 1}")
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
            return
        if self.mode != "preview" or not self.dd:
            return
        x, y = self.s2w(e.x, e.y)
        if not any(r[0] <= x <= r[2] and r[1] <= y <= r[3] for r in self.plans):
            self.select_region(self.dd.extents, "도면 전체")

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
        if self.mode == "result" and self._survey_tab() and self.sv_tool.get() in ("point", "span") and \
                self.P.get(self.sv_purpose.get(), {}).get("area"):
            self._snap = None
            self._draw_snap()
            if self._sv_area0:
                a, b = self.w2s(*self._sv_area0), self.w2s(x, y)
                col = self.P[self.sv_purpose.get()].get("color", "#0f766e")
                self.cv.create_rectangle(*a, *b, outline=col, width=2, dash=(6, 4), tags="snap")
                w, h = abs(x - self._sv_area0[0]) / 1000, abs(y - self._sv_area0[1]) / 1000
                self.cv.create_text(min(a[0], b[0]) + 4, min(a[1], b[1]) - 8, anchor="w", fill=col,
                                    font=(TH.FAM, 9, "bold"), text=f"{w:.2f} × {h:.2f} m · {w * h:.1f} m²", tags="snap")
            return
        if self.mode == "result" and self._survey_tab() and self.sv_tool.get() in ("point", "span"):
            p = self._sv_locate(x, y, self._sv_start[0] if self._sv_start else None)
            self._snap = ("member", None, p[3]) if p[0] is not None else None
            self._draw_snap()
            if self._sv_start:
                a = self.w2s(*self._sv_start[2])
                b = self.w2s(*p[3])
                self.cv.create_line(*a, *b, fill=self.P.get(self.sv_purpose.get(), {}).get("color", "#d62828"),
                                    width=7, tags="snap")
            return
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
        if self._calib is not None:
            self._calib_click(x, y)
            return
        if self._survey_tab() and not self.pick_origin:
            self._survey_click(x, y)
            return
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
        if self._calib is not None:
            self._calib = None
            self.cv.delete("calib")
            self.status.config(text="축척 맞추기 취소")
        if self._sv_start or self._sv_area0:
            self._sv_start = None
            self._sv_area0 = None
            self._snap = None
            self._draw_snap()
        if self._line_start or self._snap:
            self._line_start = None
            self._snap = None
            self._draw_snap()
            self.status.config(text="취소")

    # ======================================================================= editing infra
    def _push_undo(self):
        if not self.res:
            return
        self.undo_stack.append(self._snapshot())
        if len(self.undo_stack) > 60:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _snapshot(self):
        return (copy.deepcopy(self.res.members), copy.deepcopy(self.res.nodes), copy.deepcopy(self.res.surveys),
                copy.deepcopy(getattr(self.res, "schedule", []) or []))

    def _restore(self, snap):
        self._sv_edit = None
        sel_id = self.sel.id if self.sel else None
        self.res.members, self.res.nodes, self.res.surveys = snap[:3]
        if len(snap) > 3:
            self.res.schedule = snap[3]
        if self.sched_box.winfo_ismapped():
            self.sched_box.refresh()
        self.members = self.res.members
        self.sel = next((m for m in self.members if m.id == sel_id), None)
        self._after_edit(select=self.sel, push=False)

    def undo(self):
        if not self.undo_stack or not self.res:
            return
        self.redo_stack.append(self._snapshot())
        self._restore(self.undo_stack.pop())
        self.log("되돌리기")

    def redo(self):
        if not self.redo_stack or not self.res:
            return
        self.undo_stack.append(self._snapshot())
        self._restore(self.redo_stack.pop())
        self.log("다시실행")

    def _after_edit(self, select=None, push=True):
        self.members = self.res.members
        if self.sel_sv is not None and not any(r["id"] == self.sel_sv for r in self.res.surveys):
            self.sel_sv = None
        if self._survey_tab():
            self._sv_fill_form()
            self._sv_refresh_list()
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
        R["현장조사"].set(SV.member_summary(self.res.surveys, m, self.P))
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

    def ai_review(self, stages=("layer", "member"), auto=False):
        """2차 검토: 1차 분석 결과를 다시 보고 오류 후보를 찾는다 (레이어 역할 · 거더 끝 기둥 · 절점 · 기둥/벽)."""
        if not self.res or self.busy:
            if not self.res and not auto:
                messagebox.showinfo("AI 검토", "먼저 도면을 분석하세요.", parent=self.root)
            return
        client, res, sub = self._client(), self.res, self.sub
        roles = {k: v[0] for k, v in self._roles.items()} if sub is not None else {}
        do_layers = "layer" in stages and sub is not None and self.rv_layers.get()
        do_cols = "member" in stages and self.rv_cols.get() and getattr(res, "kind", "struct") == "struct"
        do_members = "member" in stages

        def work():
            labels = RV.collect_labels(sub) if sub is not None else []
            cands = []
            if do_layers:
                cands += RV.find_layer_candidates(sub, roles, res, labels, log=self.log)
            if do_members:
                cands += RV.find_candidates(res)
            if do_cols:
                cands += RV.find_missing_columns(res, sub, labels)
            n = {t: sum(c["type"] == t for c in cands) for t in RV.TYPE_KO}
            self.log("2차 검토 대상: " + ", ".join(f"{RV.TYPE_KO[t]} {v}" for t, v in n.items() if v)
                     + (f" · Ollama({client.model}) 판단 중…" if client else " · Ollama 꺼짐 → 규칙 판단"))
            return RV.decide(cands, client, log=self.log)

        def done(cands):
            todo = [c for c in cands if c["action"] != "keep"]
            if not todo:
                self.log("2차 검토: 수정할 항목이 없습니다.")
                if not auto:
                    messagebox.showinfo("AI 2차 검토", "수정할 항목이 없습니다.", parent=self.root)
                return
            n = {RV.TYPE_KO[t]: sum(c["type"] == t for c in todo) for t in RV.TYPE_KO}
            self.log("2차 검토 제안: " + ", ".join(f"{k} {v}" for k, v in n.items() if v))
            ReviewDialog(self.root, cands, self._review_apply, self._review_focus)
        self._run_bg(work, done, "AI 2차 검토 중…")

    def _review_focus(self, c):
        self._review_mark = c
        (x0, y0), (x1, y1) = c["where"], c["to"]
        W, H = self.cv.winfo_width(), self.cv.winfo_height()
        if c["type"] == "layer":
            self.s = 0.9 * min(W / max(x1 - x0, 1000), H / max(y1 - y0, 1000))
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            self.ox, self.oy = cx - W / 2 / self.s, cy + H / 2 / self.s
            self.redraw()
            ld = self.sub.layers.get(c["layer"]) if self.sub is not None else None
            if ld is not None:
                for g in ld.segments[:8000]:
                    self.cv.create_line(*self.w2s(g.x1, g.y1), *self.w2s(g.x2, g.y2), fill="#db2777", width=2,
                                        tags="rv")
                for t in ld.texts[:2000]:
                    self.cv.create_text(*self.w2s(t.x, t.y), text=t.text, fill="#db2777", tags="rv",
                                        font=(TH.FAM, 8, "bold"))
            self.status.config(text=f"분홍색 = 레이어 '{c['layer']}'의 선/글자")
            return
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
        if c["type"] == "add_col":
            pl = c["place"]
            if pl.get("polygon"):
                pts = [v for q in pl["polygon"] for v in self.w2s(*q)]
            else:
                pts = [v for q in T._rect(pl["x"], pl["y"], pl["b"], pl["h"], pl["angle"]) for v in self.w2s(*q)]
            self.cv.create_polygon(*pts, outline="#db2777", fill="", width=3, dash=(4, 2), tags="rv")

    def _review_apply(self, sel):
        lay = [c for c in sel if c["type"] == "layer" and c.get("new_role")]
        if lay:
            # layer roles changed → the first pass must run again; member suggestions are re-checked afterwards
            mem = self.cfg.setdefault(self._mem_key(), {})
            for c in lay:
                self._roles[c["layer"]] = (c["new_role"], "검토")
                mem[c["layer"]] = c["new_role"]
                self.log(f"레이어 '{c['layer']}': {LAYER_ROLE_KO.get(c['features']['current_role'])} → "
                         f"{LAYER_ROLE_KO.get(c['new_role'])}")
            self._save_cfg()
            if self.sub is None:
                return
            other = len(sel) - len(lay)
            self.log(f"레이어 {len(lay)}개 역할 변경 → 다시 분석합니다."
                     + (f" (나머지 {other}건은 새 결과로 다시 검토)" if other else ""))
            self._review_next = ("member",)
            self._run_analysis({k: v[0] for k, v in self._roles.items()})
            return
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
    def _sv_tool_changed(self):
        self._sv_start = None
        self._sv_area0 = None
        self._snap = None
        self.sv_help.config(text=SV_HELP[self.sv_tool.get()])
        self.status.config(text=SV_HELP[self.sv_tool.get()].split("\n")[0])
        self._draw_snap()

    def _sv_current(self):
        if self.sel_sv is None or not self.res:
            return None
        return next((r for r in self.res.surveys if r["id"] == self.sel_sv), None)

    def _sv_hit(self, x, y):
        """Record whose number bubble (or point / section) is under the cursor."""
        if not self.show_survey.get() or not self.res:
            return None
        byid = self.res.by_id()
        best = None
        for rec in self.res.surveys:
            if rec.get("purpose") in self.sv_hidden:
                continue
            bx, by = SV.bubble(rec, byid)
            d = math.hypot(x - bx, y - by) * self.s - 12          # px outside the bubble
            g = SV.geometry(rec, byid)
            if g[0] == "area":                                     # 테두리 근처만 (안쪽은 다른 검측점 찍기)
                x0, y0, x1, y1 = g[1]
                d2 = min(dist_point_seg(x, y, *q)[0] for q in ((x0, y0, x1, y0), (x1, y0, x1, y1),
                                                               (x1, y1, x0, y1), (x0, y1, x0, y0))) * self.s - 5
            elif g[0] == "span":
                d2 = dist_point_seg(x, y, *g[1], *g[2])[0] * self.s - 5
            else:
                d2 = math.hypot(x - g[1][0], y - g[1][1]) * self.s - 5
            d = min(d, d2)
            if d <= 2 and (best is None or d < best[0]):
                best = (d, rec)
        return best[1] if best else None

    def _sv_bubble_hit(self, x, y):
        if not self.show_survey.get() or not self.res:
            return None
        byid = self.res.by_id()
        for rec in reversed(self.res.surveys):
            if rec.get("purpose") in self.sv_hidden:
                continue
            bx, by = SV.bubble(rec, byid)
            if math.hypot(x - bx, y - by) * self.s <= 13:
                return rec
        return None

    def _sv_locate(self, x, y, only=None):
        """Where a click lands: (member, t, (dx, dy) for columns, point on member axis)."""
        tol = 15 / self.s
        if only is not None:                    # 2nd click of a section: project on the same member
            d, t = dist_point_seg(x, y, *only.p1, *only.p2)
            t = min(1.0, max(0.0, t))
            return (only, t, None, (only.p1[0] + (only.p2[0] - only.p1[0]) * t,
                                    only.p1[1] + (only.p2[1] - only.p1[1]) * t))
        best = None          # (distance, member, t)
        for m in self.members:
            if not self.show[m.kind].get():
                continue
            if m.kind == "column":
                if m.polygon and point_in_poly(x, y, m.polygon):
                    return (m, None, (x - m.center[0], y - m.center[1]), (x, y))
                d = math.dist((x, y), m.center)
                if d <= tol and (best is None or d < best[0]):
                    best = (d, m, None)
                continue
            if m.curved:
                continue
            d, t = dist_point_seg(x, y, *m.p1, *m.p2)
            if d <= max(tol, m.width / 2) and (best is None or d < best[0]):
                best = (d, m, min(1.0, max(0.0, t)))
        if best:
            _, m, t = best
            if m.kind == "column":
                return (m, None, (0.0, 0.0), m.center)
            return (m, t, None, (m.p1[0] + (m.p2[0] - m.p1[0]) * t, m.p1[1] + (m.p2[1] - m.p1[1]) * t))
        return (None, None, None, (x, y))

    def _sv_new(self, m, t0, t1, p, dxy=None):
        if not self._sv_guard():
            return
        purpose = self.sv_purpose.get()
        if purpose not in self.P:
            purpose = "부재검측"
        rec = SV.new_record(self.res.surveys, purpose, m, t0, t1, p[0], p[1], bubble=(20 / self.s, 24 / self.s))
        rec["inspector"] = self.cfg.get("inspector", "")
        if dxy:
            rec["dx"], rec["dy"] = dxy
        self._push_undo()
        self.res.surveys.append(rec)
        self.log(f"검측위치 #{rec['no']} 추가 ({purpose}) — {SV.position_text(rec, self.res.by_id())}")
        if m is None:
            self.status.config(text="부재가 없는 위치입니다 — 좌표만 기록합니다.")
        self._set_dirty(True)
        self._sv_select(rec["id"])
        self._sv_begin_edit()             # new location → straight into editing

    def _sv_new_area(self, r):
        if not self._sv_guard():
            return
        purpose = self.sv_purpose.get()
        rec = SV.new_record(self.res.surveys, purpose, None, None, None, (r[0] + r[2]) / 2, (r[1] + r[3]) / 2,
                            bubble=(-14 / self.s, 14 / self.s))
        rec["area"] = [round(v, 1) for v in r]
        rec["inspector"] = self.cfg.get("inspector", "")
        self._push_undo()
        self.res.surveys.append(rec)
        self.log(f"하중조사 영역 #{rec['no']} 추가 — {SV.position_text(rec, {})}")
        self._set_dirty(True)
        self._sv_select(rec["id"])
        self._sv_begin_edit()

    def _sv_vis_build(self):
        """리본 › 👁 표시할 조사 — 용도별로 도면에 보이기/숨기기 (따로 또는 같이)."""
        mn = self.sv_vis_menu
        mn.delete(0, "end")
        cnt = {}
        for r in (self.res.surveys if self.res else []):
            cnt[r.get("purpose")] = cnt.get(r.get("purpose"), 0) + 1
        for name in self.P:
            v = tk.BooleanVar(value=name not in self.sv_hidden)
            mn.add_checkbutton(label=f"{name}  ({cnt.get(name, 0)}건)", variable=v, onvalue=True, offvalue=False,
                               command=lambda n=name, v=v: self._sv_set_visible(n, v.get()))
            mn._vars = getattr(mn, "_vars", []) + [v]
        mn.add_separator()
        mn.add_command(label="모두 보기", command=lambda: self._sv_set_visible(None, True))
        for name in self.P:
            mn.add_command(label=f"{name}만 보기", command=lambda n=name: self._sv_only(n))

    def _sv_set_visible(self, name, on):
        if name is None:
            self.sv_hidden.clear()
        elif on:
            self.sv_hidden.discard(name)
        else:
            self.sv_hidden.add(name)
        self.cfg["survey_hidden"] = sorted(self.sv_hidden)
        S.save(self.cfg)
        self.redraw()

    def _sv_only(self, name):
        self.sv_hidden = {n for n in self.P if n != name}
        self._sv_set_visible(name, True)

    def _survey_click(self, x, y):
        tool = self.sv_tool.get()
        hit = self._sv_hit(x, y)
        if tool == "delete":
            if hit:
                self._sv_delete(hit)
            return
        if hit and not self._sv_start and not self._sv_area0:
            self._sv_select(hit["id"])
            return
        if tool == "select":
            self.sel_sv = None
            self.select(self._hit(x, y))
            self._sv_fill_form()
            self._sv_refresh_list()
            return
        if tool in ("point", "span") and self.P.get(self.sv_purpose.get(), {}).get("area"):
            if self._sv_area0 is None:
                self._sv_area0 = (x, y)
                self.status.config(text="영역의 반대쪽 모서리를 클릭하세요 (Esc 취소)")
                return
            (x0, y0), self._sv_area0 = self._sv_area0, None
            self._snap = None
            self._draw_snap()
            if abs(x - x0) * self.s < 8 or abs(y - y0) * self.s < 8:
                self.status.config(text="영역이 너무 작습니다.")
                return
            self._sv_new_area((min(x0, x), min(y0, y), max(x0, x), max(y0, y)))
            return
        if tool == "point":
            m, t, dxy, p = self._sv_locate(x, y)
            self._sv_new(m, t, None, p, dxy)
            return
        # section: two clicks on one linear member
        if self._sv_start is None:
            m, t, _dxy, p = self._sv_locate(x, y)
            if m is None or m.kind == "column":
                self.status.config(text="검측구간은 보·거더·벽 위에서 시작하세요.")
                return
            self._sv_start = (m, t, p)
            self.select(m)
            self.status.config(text=f"{m.display_name()} #{m.id} 위에서 구간 끝점을 클릭하세요 (Esc 취소)")
            return
        m, t0, p0 = self._sv_start
        self._sv_start = None
        self._snap = None
        _m, t1, _dxy, p1 = self._sv_locate(x, y, only=m)
        if abs(t1 - t0) * m.length_cc < 50:
            self.status.config(text="구간이 너무 짧습니다.")
            self._draw_snap()
            return
        a, b = sorted((t0, t1))
        self._sv_new(m, a, b, ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2))

    def _sv_select(self, sid, center=False):
        if getattr(self, "_sched_on", False):
            self._sched_on = False
            self._show_sv_right()
        if sid != self.sel_sv and not self._sv_guard():
            return
        self.sel_sv = sid
        rec = self._sv_current()
        if rec is None:
            return
        m = self.res.by_id().get(rec.get("member"))
        self.sel = m
        self._show_info(m)
        if center:
            x, y = SV.anchor(rec, self.res.by_id())
            W, H = self.cv.winfo_width(), self.cv.winfo_height()
            sx, sy = self.w2s(x, y)
            if not (60 < sx < W - 60 and 60 < sy < H - 60):
                self.ox, self.oy = x - W / 2 / self.s, y + H / 2 / self.s
                self.redraw()
        self._draw_selection()
        self._sv_fill_form()
        self._sv_refresh_list()

    def _sv_delete(self, rec):
        if rec is None:
            return
        if self._sv_edit is not None and self._sv_edit.get("id") == rec["id"]:
            self._sv_edit = None
        self._push_undo()
        self.res.surveys = [s for s in self.res.surveys if s["id"] != rec["id"]]
        if self.sel_sv == rec["id"]:
            self.sel_sv = None
        self.log(f"검측위치 #{rec['no']} 삭제")
        self._after_edit(select=self.sel)

    # ---------------------------------------------------------------- right panel (form)
    def _build_sv_panel(self, parent):
        box = tk.Frame(parent, bg=SV_BG)
        self.sv_box = box
        head = tk.Frame(box, bg=SV_BG)
        head.pack(fill="x", padx=8, pady=(8, 2))
        tk.Label(head, text="현장조사", bg=SV_BG, font=(TH.FAM, 12, "bold")).pack(side="left")
        self.sv_mode_lbl = tk.Label(head, text="", bg=SV_BG, fg=TH.ORANGE_D, font=(TH.FAM, 9, "bold"))
        self.sv_mode_lbl.pack(side="right")
        self.sv_pos_lbl = tk.Label(box, text="", bg=SV_BG, fg="#555", font=FONT, justify="left", wraplength=360,
                                   anchor="w")
        self.sv_pos_lbl.pack(fill="x", padx=8)
        self.sv_form = tk.Frame(box, bg=SV_BG)
        self.sv_form.pack(fill="both", expand=True, padx=8, pady=4)
        self._sv_edit = None          # working copy while editing
        self._sv_fill_form()
        self._sched_on = False
        self.sched_box = SchedulePanel(parent, self, on_close=lambda: self.toggle_schedule(False))

    # ---- 부재리스트 (right panel, 현장조사 tab)
    def toggle_schedule(self, on=None):
        on = (not self._sched_on) if on is None else on
        if on and self.res is None:
            messagebox.showinfo("부재리스트", "먼저 도면을 분석하거나 DB에서 불러오세요.", parent=self.root)
            return
        if on and not self._sv_guard():
            return
        self._sched_on = on
        if not self._survey_tab():
            self.rb.select(self.tabs["survey"])
            return                        # _tab_changed shows the right panel
        self._show_sv_right()

    def _show_sv_right(self):
        if self._sched_on:
            self.sv_box.pack_forget()
            if not self.sched_box.winfo_ismapped():
                self.sched_box.pack(fill="both", expand=True)
            if self.res is not None and not getattr(self.res, "schedule", None):
                self.res.schedule = []
                a, _u = SC.merge_estimate(self.res.schedule, self.res)
                if a:
                    self.log(f"부재리스트: 도면에서 {a}개 부재 추정")
            self.sched_box.refresh()
        else:
            self.sched_box.pack_forget()
            if not self.sv_box.winfo_ismapped():
                self.sv_box.pack(fill="both", expand=True)
        try:
            self.sched_btn.configure(text="✎\n검측\n입력" if self._sched_on else "📋\n부재\n리스트")
        except tk.TclError:
            pass

    def _sv_open_record(self, sid):
        self.toggle_schedule(False)
        self._sv_select(sid, center=True)

    def _sched_entry(self, rec):
        sch = getattr(self.res, "schedule", None) or []
        k, n = SC.split_name(rec.get("name", ""))
        return SC.find(sch, k, n) if n else None

    def _sv_detail(self):
        if not self._sv_begin_edit():
            return
        e = self._sv_edit
        m = self.res.by_id().get(e.get("member"))

        def save(upd):
            if self._sv_edit is not e:
                return
            e.update(upd)
            r = (upd.get("calc") or {}).get("result")
            self.log(f"검측위치 #{e['no']} 상세입력" + (f" — {r['summary']}" if r else "") + " (저장을 누르면 확정)")
            self._sv_fill_form()
        DetailDialog(self.root, e, m, self._sched_entry(e), save)

    def _pill(self, parent, text, r, cmd=None):
        lb = tk.Label(parent, text=text, bg=SV_BLUE_D, fg="white", font=(TH.FAM, 9, "bold"), width=6,
                      height=2, wraplength=48, cursor="hand2" if cmd else "")
        lb.grid(row=r, column=0, sticky="nsew", padx=(0, 4), pady=3)
        if cmd:
            lb.bind("<Button-1>", lambda e: cmd())
        return lb

    def _sv_button(self, parent, text, cmd, dim=False):
        if dim:   # 보기 모드: 흰 칸 + 남색 글자
            return tk.Button(parent, text=text, command=cmd, bg=TH.PANEL, fg=TH.NAVY, relief="flat",
                             activebackground=TH.ORANGE_L, activeforeground=TH.NAVY, highlightthickness=1,
                             highlightbackground=TH.LINE, bd=0, font=(TH.FAM, 12), cursor="hand2")
        return tk.Button(parent, text=text, command=cmd, bg=SV_BLUE, fg="white",
                         activebackground=SV_BLUE_D, activeforeground="white", relief="flat",
                         font=(TH.FAM, 12), cursor="hand2")

    def _sv_rec(self):
        """Record shown in the form: the edit buffer while editing, else the stored record."""
        return self._sv_edit if self._sv_edit is not None else self._sv_current()

    def _sv_fill_form(self):
        f = getattr(self, "sv_form", None)
        if f is None:
            return
        for w in f.winfo_children():
            w.destroy()
        rec = self._sv_rec()
        f.columnconfigure(1, weight=1)
        f.columnconfigure(3, weight=1)
        editing = self._sv_edit is not None
        self.sv_mode_lbl.config(text="✎ 편집 중 — 저장을 누르세요" if editing else "")
        if rec is None:
            self.sv_pos_lbl.config(text="")
            tk.Label(f, bg=SV_BG, fg="#555", font=(TH.FAM, 10), justify="left",
                     text="도면에서 검측위치를 클릭하면\n여기에 조사 내용을 입력합니다.\n\n"
                          "· 검측점: 부재 위 한 번 클릭\n· 검측구간: 같은 부재 위 두 번 클릭\n"
                          "· 번호 원을 클릭하면 선택, 끌면 위치 이동\n"
                          "· 항목(번호·부재명·치수…)을 누르면 선택 목록이 열립니다").grid(row=0, column=0, sticky="w",
                                                                         pady=20)
            return
        byid = self.res.by_id()
        m = byid.get(rec.get("member"))
        P = self.P.get(rec["purpose"], SV.DEFAULT_PURPOSES["부재검측"])
        ent = self._sched_entry(rec)
        self.sv_pos_lbl.config(text=SV.position_text(rec, byid) + ("\n" + SV.drawing_text(rec, byid)
                                                                   if SV.drawing_text(rec, byid) else "")
                               + (f"\n부재일람 {SC.full_name(ent)}: {SC.design_text(ent)}" if ent else ""))
        r = 0

        def val_btn(key, row, col=1, span=3, field=False, choices=None):
            v = (rec.get("fields", {}) if field else rec).get(key, "")
            unit = SV.FIELD_UNIT.get(key, "")
            txt = f"{v}{unit if v and unit else ''}" if str(v) else "선택"
            b = self._sv_button(f, txt, lambda: self._sv_pick(key, field, choices), dim=not editing)
            b.grid(row=row, column=col, columnspan=span, sticky="nsew", pady=3)
            return b

        self._pill(f, "번호", r, lambda: self._sv_pick("no"))
        val_btn("no", r)
        r += 1
        area = bool(P.get("area"))
        nch = SV.AREA_NAMES if area else None
        self._pill(f, "구역명" if area else "부재명", r, lambda: self._sv_pick("name", choices=nch))
        val_btn("name", r, choices=nch)
        r += 1
        self._pill(f, "용도", r, lambda: self._sv_pick("purpose", choices=list(self.P)))
        val_btn("purpose", r, choices=list(self.P))
        r += 1
        insp = [self.cfg["inspector"]] if self.cfg.get("inspector") else []
        self._pill(f, "검토자", r, lambda: self._sv_pick("inspector", choices=insp))
        val_btn("inspector", r, choices=insp)
        r += 1
        calc = (rec.get("calc") or {}).get("result")
        it = "INPUT" + (f"\n{'✔' if calc.get('ok') else '✘'} {calc.get('summary', '')}" if calc else
                        "\n상세 입력 · 휨/전단 검토")
        ib = tk.Button(f, text=it, bg="white", fg=("#16a34a" if calc and calc.get("ok") else
                                                  "#dc2626" if calc else "#111"),
                       font=(TH.FAM, 13 if not calc else 11, "bold"), relief="flat", height=2,
                       cursor="hand2", command=self._sv_detail)
        if not area:
            ib.grid(row=r, column=0, columnspan=4, sticky="nsew", pady=4)
            r += 1
        if P.get("size"):
            self._pill(f, "치수", r, lambda: self._sv_pick("size_b"))
            val_btn("size_b", r, 1, 1)
            tk.Label(f, text="X", bg=SV_BG, font=(TH.FAM, 12)).grid(row=r, column=2, padx=4)
            val_btn("size_h", r, 3, 1)
            r += 1
        if P.get("length"):
            self._pill(f, "길이", r, lambda: self._sv_pick("length"))
            val_btn("length", r)
            r += 1
        if P.get("rebar"):
            self._pill(f, "철근", r, self._sv_rebar)
            self._sv_button(f, "입력됨." if SV.rebar_filled(rec) else "선택", self._sv_rebar, dim=not editing).grid(
                row=r, column=1, columnspan=3, sticky="nsew", pady=3)
            r += 1
        if P.get("exist"):
            self._pill(f, "부재\n유무", r, lambda: self._sv_pick("exist"))
            val_btn("exist", r)
            r += 1
        for key, lab, unit, choices in P.get("fields", []):
            self._pill(f, lab, r, lambda k=key, c=choices: self._sv_pick(k, True, c))
            v = rec.get("fields", {}).get(key, "")
            b = self._sv_button(f, f"{v}{unit if v and unit else ''}" if v else "선택",
                                lambda k=key, c=choices: self._sv_pick(k, True, c), dim=not editing)
            b.grid(row=r, column=1, columnspan=3, sticky="nsew", pady=3)
            r += 1
        if area:
            lt = SV.load_text(rec.get("fields")) or "용도·마감·천장을 고르면 하중 참고값이 나옵니다"
            tk.Label(f, text=f"하중 참고  ·  면적 {SV.area_m2(rec):.1f} m²\n{lt}\n"
                             "활하중 = KDS 41 12 00 표 3.2-1 · 마감·천장 = 일반 단위중량 참고값",
                     bg="#ecfdf5", fg="#0f766e", font=(TH.FAM, 9, "bold"), justify="left", anchor="w",
                     padx=8, pady=6, wraplength=360).grid(row=r, column=0, columnspan=4, sticky="ew", pady=(6, 2))
            r += 1
        n_ph = len(rec.get("photos", []))
        pb = self._sv_button(f, (f"사진등록 ({n_ph})" if n_ph else "사진등록") + "   ⇩ 끌어다 놓기", self._sv_photos)
        pb.grid(row=r, column=0, columnspan=4, sticky="nsew", pady=(8, 3))
        SU.add_drop(pb, self._sv_drop_photos)
        r += 1
        memo = rec.get("memo", "")
        self._sv_button(f, "추가사항" + (" ✓" if memo else ""), self._sv_memo).grid(
            row=r, column=0, columnspan=4, sticky="nsew", pady=3)
        r += 1
        if memo:
            tk.Label(f, text=memo[:120], bg=SV_BG, fg="#444", font=FONT, wraplength=340, justify="left").grid(
                row=r, column=0, columnspan=4, sticky="w")
            r += 1
        dr = tk.Frame(f, bg=SV_BG)
        dr.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        tk.Label(dr, text="조사일", bg=SV_BG, font=FONT).pack(side="left")
        tk.Button(dr, text=rec.get("date", "") or "-", relief="flat", bg="white",
                  command=lambda: self._sv_pick("date", choices=[SV.date.today().isoformat()])).pack(side="left", padx=4)
        r += 1
        bf = tk.Frame(f, bg=SV_BG)
        bf.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        ttk.Button(bf, text="위치 삭제", command=lambda: self._sv_delete(self._sv_current())).pack(side="left")
        if editing:
            tk.Button(bf, text="💾 저장", bg=TH.ORANGE, fg="white", activebackground=TH.ORANGE_D, relief="flat", font=(TH.FAM, 11, "bold"),
                      padx=14, command=self._sv_save_edit).pack(side="right")
            ttk.Button(bf, text="취소", command=self._sv_cancel_edit).pack(side="right", padx=6)
        else:
            tk.Button(bf, text="✎ 편집", bg=SV_BLUE_D, fg="white", relief="flat", font=(TH.FAM, 11, "bold"),
                      padx=14, command=self._sv_begin_edit).pack(side="right")

    # ---- edit buffer
    def _sv_begin_edit(self):
        rec = self._sv_current()
        if rec is None:
            return False
        if self._sv_edit is None or self._sv_edit.get("id") != rec["id"]:
            self._sv_edit = copy.deepcopy(rec)
        self._sv_fill_form()
        return True

    def _sv_save_edit(self):
        e = self._sv_edit
        if e is None:
            return
        self._push_undo()
        e["updated"] = SV.now_iso()
        if not e.get("inspector"):
            e["inspector"] = self.cfg.get("inspector", "")
        for i, s in enumerate(self.res.surveys):
            if s["id"] == e["id"]:
                self.res.surveys[i] = e
        self._sv_edit = None
        self._set_dirty(True)
        self.log(f"검측위치 #{e['no']} 저장 — {SV.summary(e, self.P) or '-'}")
        if not hasattr(self.res, "schedule") or self.res.schedule is None:
            self.res.schedule = []
        ne = SC.ensure_from_record(self.res.schedule, e)
        if ne:
            self.log(f"부재리스트에 {SC.full_name(ne)} 추가 (검측 부재명)")
        if self.sched_box.winfo_ismapped():
            self.sched_box.refresh()
        self.redraw()
        self._sv_fill_form()
        self._sv_refresh_list(keep_sel=True)
        self._show_info(self.sel)

    def _sv_cancel_edit(self):
        self._sv_edit = None
        self._sv_fill_form()

    def _sv_guard(self):
        """Unsaved edit buffer → ask before leaving it. Returns False if the user cancels."""
        if self._sv_edit is None:
            return True
        cur = self._sv_current()
        if cur is not None and cur == self._sv_edit:
            self._sv_edit = None
            return True
        r = messagebox.askyesnocancel("현장조사", f"#{self._sv_edit['no']} 편집 내용을 저장할까요?", parent=self.root)
        if r is None:
            return False
        if r:
            self._sv_save_edit()
        else:
            self._sv_edit = None
        return True

    def _sv_pick(self, key, field=False, choices=None):
        if not self._sv_begin_edit():
            return
        e = self._sv_edit
        m = self.res.by_id().get(e.get("member"))
        P = self.P.get(e["purpose"], {})
        unit = SV.FIELD_UNIT.get(key, "")
        title = SV.FIELD_LABEL.get(key, key)
        if field:
            for k, lab, u, ch in P.get("fields", []):
                if k == key:
                    title, unit, choices = lab, u, choices or ch
        others = [s for s in self.res.surveys if s["id"] != e["id"]]
        groups = SV.pick_groups(key, m, others, self.cfg, choices, field)
        if key == "name" and getattr(self.res, "schedule", None):
            names = SC.names_for_pick(self.res.schedule, m.kind if m is not None else None)
            groups.insert(1 if groups and groups[0][0] == "도면값" else 0, ("부재리스트", names[:60], False))
        cur = str((e.get("fields", {}) if field else e).get(key, ""))
        pkey = f"{e['purpose']}.{key}" if field else key

        def done(v):
            if key == "no":
                if not v.strip().isdigit():
                    return
                v = int(v)
            if field:
                e.setdefault("fields", {})[key] = v
            else:
                e[key] = v
            self._sv_fill_form()
            if key == "size_b" and P.get("size") and not e.get("size_h"):
                self.root.after(50, lambda: self._sv_pick("size_h"))

        def add(v):
            SV.add_pick(self.cfg, pkey, v)
            S.save(self.cfg)

        def rem(v):
            SV.remove_pick(self.cfg, pkey, v)
            S.save(self.cfg)
        if key in ("purpose",):
            add = rem = None
        groups = SV.pick_groups(pkey if field else key, m, others, self.cfg, choices, field) if field else groups
        if field:     # recent values for custom fields are stored under the plain key
            rec_vals = SV.recent_values([s for s in others if s["purpose"] == e["purpose"]], key, True)
            groups = [g for g in groups if g[0] != "최근 입력"]
            if rec_vals:
                groups.insert(0, ("최근 입력", rec_vals, False))
        SU.PickDialog(self.root, title, groups, cur, done, add, rem, unit=unit)

    def _sv_rebar(self):
        if not self._sv_begin_edit():
            return
        e = self._sv_edit
        m = self.res.by_id().get(e.get("member"))
        rows, cols = SV.rebar_layout(m.kind if m else "beam")

        def save(d):
            e["rebar"] = d
            self._sv_fill_form()
        SU.RebarDialog(self.root, f"#{e['no']} {e.get('name', '')}", rows, cols, e.get("rebar", {}), save)

    def _sv_photo_add(self, files):
        e = self._sv_rec()
        folder = SV.photo_folder(self.cfg, self.project, self.db_name or "미저장")
        return SU.copy_photos(files, folder, prefix=f"{e['no']:03d}_" if e else "")

    def _sv_drop_photos(self, files):
        if not self._sv_begin_edit():
            return
        new = self._sv_photo_add(files)
        added = 0
        for p in new:
            if p not in self._sv_edit["photos"]:
                self._sv_edit["photos"].append(p)
                added += 1
        self.status.config(text=f"사진 {added}장 추가 — 저장을 누르세요" if added else "추가할 사진(이미지 파일)이 없습니다")
        self._sv_fill_form()

    def _sv_photos(self):
        if not self._sv_begin_edit():
            return
        e = self._sv_edit

        def save(ps):
            e["photos"] = ps
            self._sv_fill_form()
        SU.PhotoDialog(self.root, f"사진 — #{e['no']} {e.get('name', '')}", e.get("photos", []), save,
                       self._sv_photo_add)

    def _sv_memo(self):
        if not self._sv_begin_edit():
            return
        e = self._sv_edit

        def save(t):
            e["memo"] = t
            self._sv_fill_form()
        SV.MemoDialog(self.root, e, save)

    # kept for compatibility with older calls
    def _sv_set(self, key, val):
        if self._sv_begin_edit():
            self._sv_edit[key] = val

    def _sv_set_field(self, key, val):
        if self._sv_begin_edit():
            self._sv_edit.setdefault("fields", {})[key] = val

    def _sv_add_purpose(self):
        def save(name, fields, **flags):
            if name in self.P:
                messagebox.showinfo("용도 추가", "이미 있는 용도입니다.", parent=self.root)
                return
            SV.add_purpose(self.cfg, name, fields, **flags)
            S.save(self.cfg)
            self.P = SV.purposes(self.cfg)
            self.sv_purpose_cb["values"] = list(self.P)
            self.sv_purpose.set(name)
            self._sv_build_filters()
            self._sv_fill_form()
            self.log(f"용도 추가: {name}")
        SV.PurposeDialog(self.root, save)

    # ---------------------------------------------------------------- bottom strip (pager + list)
    def _build_sv_strip(self, parent):
        st = ttk.Frame(parent)
        self.sv_strip = st
        pg = ttk.Frame(st)
        pg.pack(fill="x", pady=(2, 2))
        ttk.Button(pg, text="‹", width=3, command=lambda: self._sv_page(-1)).pack(side="left", padx=(4, 0))
        self.sv_page_lbl = ttk.Label(pg, text="-/-", width=7, anchor="center")
        self.sv_page_lbl.pack(side="left")
        ttk.Button(pg, text="›", width=3, command=lambda: self._sv_page(1)).pack(side="left")
        self.sv_floor_btn = tk.Button(pg, text="(저장 안 됨)", bg=SV_BLUE, fg="white", relief="flat",
                                      font=(TH.FAM, 11, "bold"), width=22, command=self._sv_floor_rename)
        self.sv_floor_btn.pack(side="left", padx=12)
        self.sv_proj_lbl = ttk.Label(pg, text="", foreground="#666")
        self.sv_proj_lbl.pack(side="left")
        self.sv_insp = tk.StringVar(value=self.cfg.get("inspector", ""))
        ie = ttk.Entry(pg, textvariable=self.sv_insp, width=10, font=(TH.FAM, 11))
        ie.pack(side="right", padx=(0, 6))
        ttk.Label(pg, text="👤 검토자").pack(side="right", padx=(10, 2))

        def _insp(*_):
            self.cfg["inspector"] = self.sv_insp.get().strip()
            S.save(self.cfg)
        self.sv_insp.trace_add("write", _insp)
        tk.Button(pg, text="도면LIST", bg=SV_BLUE, fg="white", relief="flat", font=(TH.FAM, 11),
                  width=10, command=self._sv_sheet_list).pack(side="right", padx=4)
        lf = ttk.Frame(st)
        lf.pack(fill="x")
        top = ttk.Frame(lf)
        top.pack(fill="x")
        ttk.Label(top, text="조사 목록", font=(TH.FAM, 10, "bold")).pack(side="left", padx=(4, 8))
        self.sv_count = ttk.Label(top, text="", foreground="#b91c1c")
        self.sv_count.pack(side="left", padx=(0, 6))
        self.sv_filters = ttk.Frame(top)
        self.sv_filters.pack(side="left")
        self.sv_filter = tk.StringVar(value="전체")
        self._sv_build_filters()
        cols = ("no", "purpose", "name", "summary", "ph")
        self.sv_tv = ttk.Treeview(lf, columns=cols, show="headings", height=5, selectmode="browse")
        for c, t, w in (("no", "번호", 50), ("purpose", "용도", 80), ("name", "부재명", 110),
                        ("summary", "내용", 360), ("ph", "사진", 45)):
            self.sv_tv.heading(c, text=t)
            self.sv_tv.column(c, width=w, anchor="center" if c in ("no", "ph") else "w")
        self.sv_tv.pack(fill="x", padx=4, pady=(2, 4))
        self.sv_tv.bind("<<TreeviewSelect>>", self._sv_list_pick)

    def _sv_build_filters(self):
        for w in self.sv_filters.winfo_children():
            w.destroy()
        for name in ["전체"] + list(self.P):
            col = self.P.get(name, {}).get("color", "#475569")
            on = self.sv_filter.get() == name
            tk.Button(self.sv_filters, text=name, relief="flat", font=(TH.FAM, 10),
                      bg=col if on else SV_BLUE, fg="white", padx=8,
                      command=lambda n=name: (self.sv_filter.set(n), self._sv_build_filters(),
                                              self._sv_refresh_list())).pack(side="left", padx=2)
        tk.Button(self.sv_filters, text="＋ 용도 추가", relief="flat", font=(TH.FAM, 10), bg=TH.NAVY_L,
                  fg="white", padx=8, command=self._sv_add_purpose).pack(side="left", padx=(8, 2))

    def _sv_refresh_list(self, keep_sel=False):
        if not hasattr(self, "sv_tv"):
            return
        tv = self.sv_tv
        tv.delete(*tv.get_children())
        if not self.res:
            self.sv_count.config(text="")
            return
        flt = self.sv_filter.get()
        recs = [r for r in self.res.surveys if flt == "전체" or r["purpose"] == flt]
        self.sv_count.config(text=f"{len(recs)}건")
        SV.P_CACHE = self.P
        cols = SV.list_columns(flt, self.P)
        if tuple(tv["columns"]) != tuple(c[0] for c in cols):
            tv["columns"] = [c[0] for c in cols]
            for key, title, w in cols:
                tv.heading(key, text=title)
                tv.column(key, width=w, anchor="center" if w <= 70 else "w", stretch=key in ("summary", "rebar"))
        for r in sorted(recs, key=lambda r: r["no"]):
            tv.insert("", "end", iid=str(r["id"]), values=[SV.list_value(r, c[0]) for c in cols])
        if self.sel_sv is not None and tv.exists(str(self.sel_sv)):
            self._sv_list_lock = True
            tv.selection_set(str(self.sel_sv))
            tv.see(str(self.sel_sv))
            self._sv_list_lock = False

    def _sv_list_pick(self, _e=None):
        if getattr(self, "_sv_list_lock", False):
            return
        s = self.sv_tv.selection()
        if s and int(s[0]) != self.sel_sv:
            self._sv_select(int(s[0]), center=True)

    def _sv_refresh_pager(self):
        if not hasattr(self, "sv_page_lbl"):
            return
        if self.db_id is None:
            self.sv_page_lbl.config(text="-/-")
            self.sv_floor_btn.config(text=self.db_name or "(저장 안 됨)")
            self.sv_proj_lbl.config(text=self.project or "")
            return
        sheets = db.project_sheets(self.project)
        ids = [i for i, _ in sheets]
        k = ids.index(self.db_id) + 1 if self.db_id in ids else 0
        self.sv_page_lbl.config(text=f"{k}/{len(ids)}")
        self.sv_floor_btn.config(text=self.db_name or "-")
        self.sv_proj_lbl.config(text=self.project or "(프로젝트 없음)")

    def _sv_page(self, d):
        if self.db_id is None:
            messagebox.showinfo("도면 이동", "먼저 DB에 저장하세요. (같은 프로젝트로 저장된 도면끼리 넘겨 봅니다)",
                                parent=self.root)
            return
        ids = [i for i, _ in db.project_sheets(self.project)]
        if self.db_id not in ids:
            return
        j = ids.index(self.db_id) + d
        if not (0 <= j < len(ids)) or not self._confirm_discard():
            return
        self._open_db_id(ids[j])

    def _sv_floor_rename(self):
        new = simpledialog.askstring("도면(층) 이름", "도면(층) 이름:", initialvalue=self.db_name, parent=self.root)
        if not new:
            return
        self.db_name = new.strip()
        if self.db_id is not None:
            db.rename(self.db_id, self.db_name)
        self._set_dirty(self.dirty)
        self._sv_refresh_pager()

    def _sv_sheet_list(self):
        if self.busy or not self._confirm_discard():
            return
        DbDialog(self.root, self._open_db_id, project=self.project if self.db_id is not None else None)

    # ---------------------------------------------------------------- 휴대폰·패드 연동
    def _mobile_ready(self):
        if not self.res or self.db_id is None:
            messagebox.showinfo("모바일", "먼저 DB에 저장하세요.\n(같은 프로젝트로 저장된 도면이 모두 휴대폰으로 갑니다)",
                                parent=self.root)
            return False
        if not self._confirm_discard():
            return False
        if self.dirty:
            return False
        return True

    def mobile_export(self):
        if not self._mobile_ready():
            return
        from . import sync
        n = len(db.project_sheets(self.project))
        fname = f"{self.project or '현장조사'}_현장조사.strsv"
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".strsv", initialfile=fname,
                                            filetypes=[("현장조사 파일", "*.strsv")],
                                            title=f"모바일로 내보내기 — 도면 {n}장")
        if not path:
            return
        try:
            rep = sync.export_package(path, self.project, self.cfg, log=self.log)
        except Exception as e:      # noqa: BLE001
            messagebox.showerror("모바일로 내보내기", str(e), parent=self.root)
            return
        messagebox.showinfo("모바일로 내보내기",
                            f"도면 {rep['sheets']}장 · 검측위치 {rep['records']}개 · 사진 {rep['photos']}장\n\n{path}\n\n"
                            "이 파일을 휴대폰/패드로 옮겨(카카오톡·메일·드라이브·USB) 현장조사 앱에서 여세요.",
                            parent=self.root)

    def mobile_import(self):
        if not self._confirm_discard():
            return
        from . import sync
        path = filedialog.askopenfilename(parent=self.root, title="모바일 DB 가져오기",
                                          filetypes=[("현장조사 파일", "*.strsv"), ("모든 파일", "*.*")])
        if not path:
            return
        try:
            rep = sync.import_package(path, self.cfg, log=self.log)
        except Exception as e:      # noqa: BLE001
            messagebox.showerror("모바일 DB 가져오기", str(e), parent=self.root)
            return
        self._after_mobile_import(rep)
        messagebox.showinfo("모바일 DB 가져오기",
                            f"추가 {rep['added']} · 수정 {rep['updated']} · 삭제 {rep['deleted']} · 그대로 {rep['kept']}\n"
                            f"사진 {rep['photos']}장" + (f"\n번호 겹침으로 바뀐 번호 {rep['renumbered']}건 (추가사항에 기록)"
                                                       if rep["renumbered"] else "")
                            + (f"\n휴대폰에서 새로 만든 도면 {rep['new_sheets']}장 추가 (DB에서 불러오기로 여세요)"
                               if rep.get("new_sheets") else "")
                            + (f"\n스케치 {rep['sketches']}건" if rep.get("sketches") else "")
                            + (f"\n\nPC DB에 없는 도면: {', '.join(rep['missing'])}" if rep["missing"] else ""),
                            parent=self.root)

    def _after_mobile_import(self, rep):
        S.save(self.cfg)
        self.P = SV.purposes(self.cfg)
        if hasattr(self, "sv_purpose_cb"):
            self.sv_purpose_cb["values"] = list(self.P)
            self._sv_build_filters()
        if self.db_id is not None and not self.dirty:
            keep = (self.s, self.ox, self.oy)
            self._open_db_id(self.db_id)
            self.s, self.ox, self.oy = keep
            self.redraw()

    def mobile_wifi(self):
        from . import sync
        if getattr(self, "_link", None):
            self._link.stop()
            self._link = None
            self.wifi_btn.config(text="📶\nWi-Fi\n연결")
            self.log("Wi-Fi 연결 종료")
            return
        if not os.path.isdir(sync.MOBILE_DIR):
            messagebox.showerror("Wi-Fi 연결", f"모바일 앱 폴더가 없습니다:\n{sync.MOBILE_DIR}", parent=self.root)
            return
        link = sync.LinkServer(self.cfg, port=int(self.cfg.get("link_port", 8765)), log=self.log,
                               on_imported=lambda rep: self.q.put(("call", lambda: (
                                   self._after_mobile_import(rep),
                                   self.log(f"휴대폰에서 받음: 추가 {rep['added']}, 수정 {rep['updated']}, "
                                            f"삭제 {rep['deleted']}, 사진 {rep['photos']}")))))
        try:
            url = link.start()
        except OSError as e:
            messagebox.showerror("Wi-Fi 연결", f"포트를 열 수 없습니다: {e}", parent=self.root)
            return
        self._link = link
        self.wifi_btn.config(text="📶\n연결 중\n(끄기)")
        self.log(f"Wi-Fi 연결: 휴대폰 브라우저에서 {url} 접속")
        TextWindow(self.root, "휴대폰 연결 (같은 Wi-Fi)",
                   f"휴대폰·패드 브라우저 주소창에 입력하세요:\n\n    {url}\n\n"
                   "· 앱 화면의 'PC에서 받기' → 이 PC에 저장된 프로젝트를 바로 엽니다.\n"
                   "· 조사 후 메뉴 › 'PC로 보내기' → 이 PC의 DB에 바로 합쳐집니다.\n"
                   "· 현장(인터넷 없음)에서 쓰려면 앱을 https 주소(예: GitHub Pages)에 올려 홈 화면에 설치하고,\n"
                   "  파일(.strsv)로 주고받으세요. (README 참고)\n\n"
                   "Windows 방화벽이 묻으면 '개인 네트워크' 허용을 눌러 주세요.", "620x330")

    # ---------------------------------------------------------------- compat / misc
    def survey_edit(self, sid):
        self._sv_select(sid, center=True)

    def survey_input(self):
        if self.sel_sv is not None:
            self._sv_select(self.sel_sv, center=True)

    def survey_list(self):
        self.rb.select(self.tabs["survey"])

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
        if not self.res or not self.res.surveys:
            messagebox.showinfo("조사표", "검측위치가 없습니다.", parent=self.root)
            return
        base = (self.db_name or os.path.splitext(os.path.basename(self.res.source_file))[0]) + "_현장조사.csv"
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".csv", initialfile=base,
                                            filetypes=[("CSV", "*.csv")])
        if path:
            n = SV.export_csv(path, self.res.surveys, self.res.by_id(), self.P, floor=self.db_name)
            self.log(f"조사표 저장: 검측위치 {n}개 → {path}")

    # ======================================================================= 도움말
    def help_usage(self):
        TextWindow(self.root, "사용법", HELP_USAGE)

    def help_keys(self):
        TextWindow(self.root, "단축키", HELP_KEYS, "520x420")

    def help_about(self):
        from .dialogs import AboutDialog
        from . import licensing as LC
        st = LC.status()
        AboutDialog(self.root, [("라이선스", st.get("message", "")), ("기기 코드", st.get("code", "")),
                                ("DB", db.DB_PATH), ("설정", S.PATH),
                                ("Ollama", f"{self.host.get()}  ·  모델 {self.model.get() or '-'}")])

    def help_license(self):
        from .licensing_ui import LicenseDialog
        dlg = LicenseDialog(self.root)
        self.root.wait_window(dlg)
        self._show_license()

    def _show_license(self):
        from . import licensing as LC
        try:
            st = LC.status()
        except Exception:  # noqa: BLE001
            return
        col = "#7EE0A1" if st.get("state") == "licensed" else TH.ORANGE if st.get("ok") else "#F3A3A3"
        self.hd_lic.config(text=LC.short_text(st), fg=col)

    # ======================================================================= 시작 화면
    def _draw_welcome(self):
        W, H = self.cv.winfo_width(), self.cv.winfo_height()
        self.cv.configure(bg=TH.SURFACE)
        if getattr(self, "_welcome", None) is None:
            self._welcome = self._build_welcome()
        self.cv.create_window(W / 2, H / 2, window=self._welcome, anchor="center")

    def _build_welcome(self):
        from . import __version__
        f = tk.Frame(self.cv, bg=TH.PANEL, highlightthickness=1, highlightbackground=TH.LINE, padx=36, pady=28)
        top = tk.Frame(f, bg=TH.PANEL)
        top.pack(fill="x")
        logo = TH.image("icon_64.png")
        if logo is not None:
            tk.Label(top, image=logo, bg=TH.PANEL).pack(side="left", padx=(0, 14))
        tt = tk.Frame(top, bg=TH.PANEL)
        tt.pack(side="left")
        tk.Label(tt, text=f"{TH.APP_NAME} {TH.APP_SUB}", bg=TH.PANEL, fg=TH.NAVY, font=TH.FONT_XL).pack(anchor="w")
        tk.Label(tt, text="구조·건축 평면도 분석  ·  부재리스트  ·  현장조사(휴대폰 연동)  ·  간이 검토", bg=TH.PANEL,
                 fg=TH.MUTED, font=TH.FONT_M).pack(anchor="w")
        tk.Frame(f, bg=TH.LINE, height=1).pack(fill="x", pady=16)
        acts = tk.Frame(f, bg=TH.PANEL)
        acts.pack(fill="x")
        for i, (t, d, cmd, acc) in enumerate((
                ("📂  DXF / DWG 열기", "평면도를 열고 분석할 영역을 고릅니다", self.open_file, True),
                ("📷  도면 없이 조사", "빈 도면·사진 배경·종이 도면 사진 인식", self.new_field_sheet, False),
                ("📁  DB에서 불러오기", "저장한 분석·현장조사를 이어서 합니다", self.open_db, False),
                ("📖  사용법", "처음 쓰신다면 흐름을 확인하세요", self.help_usage, False))):
            c = tk.Frame(acts, bg=TH.PANEL)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            ttk.Button(c, text=t, command=cmd, style="Accent.TButton" if acc else "TButton", width=20).pack(
                fill="x", ipady=6)
            tk.Label(c, text=d, bg=TH.PANEL, fg=TH.MUTED, font=TH.FONT_S).pack(anchor="w", pady=(4, 0))
        rec = []
        try:
            rec = db.list_analyses()[:6]
        except Exception:       # noqa: BLE001
            rec = []
        if rec:
            tk.Label(f, text="최근 분석", bg=TH.PANEL, fg=TH.NAVY, font=TH.FONT_B).pack(anchor="w", pady=(18, 4))
            for r in rec:
                aid, name, _p, upd, nc, ng, nb, nw, project, _seq = r[:10]
                row = tk.Frame(f, bg=TH.PANEL, cursor="hand2")
                row.pack(fill="x")
                l1 = tk.Label(row, text=f"{project + '  ·  ' if project else ''}{name}", bg=TH.PANEL, fg=TH.INK,
                              font=TH.FONT_M, anchor="w", cursor="hand2")
                l1.pack(side="left", fill="x", expand=True, pady=3)
                l2 = tk.Label(row, text=f"기둥 {nc} · 보 {ng + nb} · 벽 {nw}    {str(upd)[:16]}", bg=TH.PANEL,
                              fg=TH.MUTED, font=TH.FONT_S, cursor="hand2")
                l2.pack(side="right")
                for w in (row, l1, l2):
                    w.bind("<Button-1>", lambda e, a=aid: self._open_recent(a))
                    w.bind("<Enter>", lambda e, rw=row, ws=(l1, l2): [x.configure(bg=TH.ORANGE_L) for x in (rw,) + ws])
                    w.bind("<Leave>", lambda e, rw=row, ws=(l1, l2): [x.configure(bg=TH.PANEL) for x in (rw,) + ws])
        smp = TH.resource("samples")
        if os.path.isdir(smp) and any(n.lower().endswith(".dxf") for n in os.listdir(smp)):
            tk.Label(f, text="예제 도면 열어 보기", bg=TH.PANEL, fg=TH.NAVY, font=TH.FONT_B).pack(anchor="w", pady=(16, 4))
            ex = tk.Frame(f, bg=TH.PANEL)
            ex.pack(anchor="w")
            for n in sorted(os.listdir(smp)):
                if n.lower().endswith(".dxf"):
                    ttk.Button(ex, text=os.path.splitext(n)[0],
                               command=lambda p=os.path.join(smp, n): self.load_path(p)).pack(side="left", padx=(0, 6))
        tk.Label(f, text=f"v{__version__}   {TH.COPYRIGHT}", bg=TH.PANEL, fg=TH.NAVY_L, font=TH.FONT_S).pack(
            anchor="e", pady=(18, 0))
        return f

    def _open_recent(self, aid):
        if self.busy or not self._confirm_discard():
            return
        self._open_db_id(aid)

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
        root.withdraw()
        TH.apply(root)
        TH.set_icon(root)
        from .licensing_ui import ensure_license
        if ensure_license(root, "cad_analysis") is None:      # 체험 종료·만료 → 키 등록 전에는 실행 안 함
            root.destroy()
            return None
        root.deiconify()
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
