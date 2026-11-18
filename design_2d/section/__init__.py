"""
design_2d/section — 단면해석 (2D 프레임 해석)

    from design_2d.section import open_section_analysis
    open_section_analysis(parent, username)
"""

import tkinter as tk


def open_section_analysis(parent, username=""):
    from .panel import SectionAnalysisPanel
    win = tk.Toplevel(parent)
    win.geometry("1440x860")
    win.minsize(1000, 640)
    win.configure(bg="#0f1520")
    panel = SectionAnalysisPanel(win, username=username)
    win._panel = panel
    win.lift(); win.focus_force()
    return win
