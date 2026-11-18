"""
design_2d/plan — 평면해석 (슬래브 판요소 + 격자보 유한요소해석)

    from design_2d.plan import open_plan_analysis
    open_plan_analysis(parent, username)
"""

import tkinter as tk


def open_plan_analysis(parent, username=""):
    from .panel import PlanAnalysisPanel
    win = tk.Toplevel(parent)
    win.geometry("1500x900")
    win.minsize(1050, 660)
    win.configure(bg="#0f1520")
    panel = PlanAnalysisPanel(win, username=username)
    win._panel = panel
    win.lift(); win.focus_force()
    return win
