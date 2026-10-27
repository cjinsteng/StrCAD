"""
design_2d/__init__.py
패키지 진입점 — launcher.py 에서 import 해서 사용
"""

import tkinter as tk
from .panel import Design2DPanel


def open_2d_design(parent, username=""):
    """
    launcher.py 에서 호출:
        from design_2d import open_2d_design
        open_2d_design(self, username=self._user)
    """
    win = tk.Toplevel(parent)
    win.title(f"2D Design  ─  {username}" if username else "2D Design")
    win.geometry("1280x760")
    win.minsize(900, 600)
    win.configure(bg="#0f1520")
    win.lift()
    win.focus_force()
    Design2DPanel(win, username=username)
    return win
