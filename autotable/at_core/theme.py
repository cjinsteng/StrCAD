"""theme.py — Auto Table 팔레트 (StrCAD: 남색 + 주황 포인트, 밝은 작업 화면)"""
import sys

FAM = "Malgun Gothic" if sys.platform.startswith("win") else "Noto Sans CJK KR"
MONO = "Consolas" if sys.platform.startswith("win") else "DejaVu Sans Mono"

NAVY = "#1E2A44"; NAVY_2 = "#2B3B5C"; NAVY_3 = "#3A4D73"
ORANGE = "#F28C28"; ORANGE_D = "#D9741A"; ORANGE_L = "#FDE7CF"
SURFACE = "#F4F6FA"; PANEL = "#FFFFFF"; LINE = "#D6DCE6"; LINE2 = "#C3CBD9"
INK = "#1F2937"; MUTED = "#6B7280"; FAINT = "#9AA3B2"
HDR = "#E7ECF4"; HDR2 = "#DCE3EF"
SEL = "#DCE8FC"; SEL_BD = "#2563EB"
ALT = "#FAFBFD"; DIS = "#ECEEF2"; DIS_TX = "#B4BBC7"
NG = "#DC2626"; OK = "#15803D"; BLUE = "#1D4ED8"

F_CELL = (FAM, 10)
F_CELL_B = (FAM, 10, "bold")
F_HDR = (FAM, 9, "bold")
F_SMALL = (FAM, 8)
F_UI = (FAM, 9)
F_UI_B = (FAM, 9, "bold")
F_TITLE = (FAM, 13, "bold")


def set_icon(win):
    try:
        from cad_analysis import theme as _th
        _th.set_icon(win)
    except Exception:       # noqa: BLE001
        pass
