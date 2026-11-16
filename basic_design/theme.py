"""
basic_design/theme.py
Basic Design 공통 팔레트 · 글꼴
  · 선택 창(허브)  : 런처와 같은 어두운 남색
  · 설계 창(Lite) : 밝은 입력 패널 + 흰색 계산서 (남색 + 주황 포인트)
"""
import sys

FAM = "Malgun Gothic" if sys.platform.startswith("win") else "Noto Sans CJK KR"
MONO = "Consolas" if sys.platform.startswith("win") else "DejaVu Sans Mono"

# ── 어두운 팔레트 (launcher.py 통일) ───────────────────────
BG = "#0f1520"; BG2 = "#141d2e"; BG3 = "#1a2540"; BG4 = "#1f2d4a"; BG5 = "#263556"
BDR = "#2c3f62"; BDR2 = "#3a5280"
ACC = "#1a56db"; ACCH = "#2563eb"; ACCD = "#1e40af"
GRN = "#16a34a"; RED = "#dc2626"; ORG = "#d97706"; BLU = "#3b82f6"; CYN = "#06b6d4"
TXT = "#dde4f0"; TX2 = "#8fa3c0"; TX3 = "#546887"; WHI = "#f0f5ff"; DIS = "#3d5070"

# ── 밝은 팔레트 (설계 창) ──────────────────────────────────
NAVY = "#1E2A44"; NAVY_2 = "#2B3B5C"
ORANGE = "#F28C28"; ORANGE_D = "#D9741A"
SURFACE = "#F4F6FA"; PANEL = "#FFFFFF"; LINE = "#D6DCE6"
INK = "#1F2937"; MUTED = "#6B7280"
INPUT_FG = "#1d4ed8"          # 입력값(파란 글자)
OK = "#1d4ed8"; NG = "#DC2626"; WARN = "#B45309"


def set_icon(win):
    """StrCAD 아이콘 (cad_analysis 테마가 있으면 사용)"""
    try:
        from cad_analysis import theme as _th
        _th.set_icon(win)
    except Exception:       # noqa: BLE001
        pass
