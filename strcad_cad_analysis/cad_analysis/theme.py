"""StrCAD 디자인 — 색상·글꼴·ttk 스타일 (남색 + 주황 포인트)."""
from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import ttk

APP_NAME = "StrCAD"
APP_SUB = "CAD Analysis"
COPYRIGHT = "© 2026 StrCAD"

NAVY = "#1E2A44"        # 기본(헤더·탭·강조 글자)
NAVY_2 = "#2B3B5C"      # 보조 남색(버튼·선택 칸)
NAVY_3 = "#3E5580"      # 값 버튼
NAVY_L = "#8C9BB8"      # 비활성 값
ORANGE = "#F28C28"      # 포인트(주요 실행 버튼·선택 표시)
ORANGE_D = "#D9741A"
ORANGE_L = "#FDEBD8"
SURFACE = "#F4F6FA"     # 앱 바탕
PANEL = "#FFFFFF"
LINE = "#D6DCE6"
INK = "#1F2937"
MUTED = "#6B7280"
OK = "#16A34A"
NG = "#DC2626"
WARN = "#B45309"
INPUT = "#FFF4E5"       # 입력 칸(연주황)

FAM = "Malgun Gothic" if sys.platform.startswith("win") else "Noto Sans CJK KR"
FONT = (FAM, 9)
FONT_S = (FAM, 8)
FONT_M = (FAM, 10)
FONT_B = (FAM, 10, "bold")
FONT_L = (FAM, 12, "bold")
FONT_XL = (FAM, 18, "bold")

# 설치판(PyInstaller)에서는 _MEIPASS 아래에 같은 구조로 풀림
ROOT = getattr(sys, "_MEIPASS", None) if getattr(sys, "frozen", False) else None
ROOT = ROOT or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "cad_analysis", "assets")


def resource(*parts):
    """mobile/, samples/ 등 프로그램과 함께 배포되는 폴더."""
    return os.path.join(ROOT, *parts)


def asset(name):
    return os.path.join(ASSETS, name)


_img_cache = {}


def image(name):
    """PhotoImage (cached, keeps a reference)."""
    if name not in _img_cache:
        try:
            _img_cache[name] = tk.PhotoImage(file=asset(name))
        except tk.TclError:
            _img_cache[name] = None
    return _img_cache[name]


def set_icon(win):
    try:
        if sys.platform.startswith("win") and os.path.exists(asset("icon.ico")):
            win.iconbitmap(default=asset("icon.ico"))
        im = image("icon_64.png")
        if im is not None:
            win.iconphoto(True, im)
    except tk.TclError:
        pass


_applied = False


def ensure(widget):
    """다른 화면(런처 등)에서 StrCAD 창을 띄울 때 스타일이 없으면 적용."""
    if not _applied:
        apply(widget.winfo_toplevel())


def apply(root):
    """ttk 전체 스타일 (clam 기반)."""
    global _applied
    _applied = True
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    root.option_add("*Font", FONT)
    root.option_add("*Background", SURFACE)
    root.option_add("*selectBackground", ORANGE_L)
    root.option_add("*selectForeground", INK)
    try:
        root.configure(bg=SURFACE)
    except tk.TclError:
        pass
    st.configure(".", background=SURFACE, foreground=INK, font=FONT, bordercolor=LINE, lightcolor=PANEL,
                 darkcolor=LINE, troughcolor="#E8ECF2", focuscolor=ORANGE, selectbackground=ORANGE_L,
                 selectforeground=INK, insertcolor=INK)
    st.configure("TFrame", background=SURFACE)
    st.configure("Card.TFrame", background=PANEL)
    st.configure("TLabel", background=SURFACE, foreground=INK)
    st.configure("Muted.TLabel", foreground=MUTED)
    st.configure("Card.TLabel", background=PANEL)
    st.configure("TLabelframe", background=PANEL, bordercolor=LINE, relief="solid", borderwidth=1)
    st.configure("TLabelframe.Label", background=PANEL, foreground=NAVY, font=FONT_B)
    # ribbon tabs
    st.configure("TNotebook", background=NAVY, borderwidth=0, tabmargins=(8, 6, 8, 0))
    st.configure("TNotebook.Tab", background=NAVY_2, foreground="#C9D3E4", padding=(14, 6), borderwidth=0,
                 font=FONT_B)
    st.map("TNotebook.Tab", background=[("selected", SURFACE), ("active", NAVY_3)],
           foreground=[("selected", NAVY), ("active", "#FFFFFF")], expand=[("selected", (0, 2, 0, 0))])
    # buttons
    st.configure("TButton", background=PANEL, foreground=INK, bordercolor=LINE, focusthickness=0, padding=(8, 4),
                 relief="flat")
    st.map("TButton", background=[("pressed", "#E3E8F0"), ("active", "#EEF2F8")],
           bordercolor=[("active", NAVY_L)])
    st.configure("Accent.TButton", background=ORANGE, foreground="#FFFFFF", bordercolor=ORANGE_D, font=FONT_B)
    st.map("Accent.TButton", background=[("pressed", ORANGE_D), ("active", "#F59C45")],
           foreground=[("disabled", "#FFE3C6")])
    st.configure("Navy.TButton", background=NAVY, foreground="#FFFFFF", bordercolor=NAVY, font=FONT_B)
    st.map("Navy.TButton", background=[("pressed", NAVY), ("active", NAVY_2)])
    st.configure("Ribbon.TButton", background=PANEL, bordercolor=PANEL, padding=(6, 3), justify="center")
    st.map("Ribbon.TButton", background=[("pressed", ORANGE_L), ("active", "#EEF2F8")],
           bordercolor=[("active", LINE)])
    st.configure("RibbonAccent.TButton", background=ORANGE, foreground="#FFFFFF", bordercolor=ORANGE,
                 padding=(6, 3), font=FONT_B, justify="center")
    st.map("RibbonAccent.TButton", background=[("pressed", ORANGE_D), ("active", "#F59C45")])
    st.configure("Toolbutton", background=PANEL, padding=(8, 4), anchor="center")
    st.map("Toolbutton", background=[("selected", NAVY), ("active", "#EEF2F8")],
           foreground=[("selected", "#FFFFFF")])
    st.configure("TCheckbutton", background=PANEL)
    st.map("TCheckbutton", indicatorcolor=[("selected", ORANGE), ("!selected", PANEL)],
           background=[("active", PANEL)])
    st.configure("TRadiobutton", background=PANEL)
    st.map("TRadiobutton", indicatorcolor=[("selected", ORANGE), ("!selected", PANEL)])
    st.configure("TEntry", fieldbackground=PANEL, bordercolor=LINE, padding=3)
    st.map("TEntry", bordercolor=[("focus", ORANGE)])
    st.configure("TCombobox", fieldbackground=PANEL, bordercolor=LINE, arrowcolor=NAVY, padding=2)
    st.map("TCombobox", bordercolor=[("focus", ORANGE)], fieldbackground=[("readonly", PANEL)])
    st.configure("TSpinbox", fieldbackground=PANEL, bordercolor=LINE, arrowcolor=NAVY)
    st.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=INK, rowheight=24, font=FONT,
                 bordercolor=LINE)
    st.map("Treeview", background=[("selected", ORANGE_L)], foreground=[("selected", INK)])
    st.configure("Treeview.Heading", background=NAVY, foreground="#FFFFFF", font=FONT_B, relief="flat",
                 padding=(4, 4))
    st.map("Treeview.Heading", background=[("active", NAVY_2)])
    st.configure("TScrollbar", background="#D3DAE5", troughcolor=SURFACE, bordercolor=SURFACE, arrowcolor=NAVY)
    st.configure("TPanedwindow", background=LINE)
    st.configure("Status.TLabel", background=NAVY, foreground="#E5EAF3", padding=(10, 3))
    return st
