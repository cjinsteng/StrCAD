"""
design_2d/__init__.py
패키지 진입점 — launcher.py 에서 import 해서 사용
"""

import tkinter as tk
from .constants import (
    BG, BG2, BG3, BG4, BG5, BDR,
    ACC, ACCH, GRN, RED, YEL, CYN,
    TXT, TX2, TX3, WHI,
    RC_COLOR, STEEL_COLOR,
)


# ═══════════════════════════════════════════════════════════════
#  뷰 선택 팝업
# ═══════════════════════════════════════════════════════════════
class _ViewSelectDialog(tk.Toplevel):
    """2D Design 진입 시 Line View / Plan View 선택"""

    def __init__(self, parent, username=""):
        super().__init__(parent)
        self.result   = None
        self.username = username
        self.title("2D Design — 뷰 선택")
        self.configure(bg=BG2)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self._build()
        self.update_idletasks()
        pw = parent.winfo_rootx() + parent.winfo_width()  // 2
        ph = parent.winfo_rooty() + parent.winfo_height() // 2
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"+{pw - w//2}+{ph - h//2}")
        self.bind("<Escape>", lambda _: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build(self):
        hdr = tk.Frame(self, bg="#0f1a30", height=52)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📐  2D Design  —  뷰 타입 선택",
                 font=("Malgun Gothic", 12, "bold"),
                 bg="#0f1a30", fg=WHI).pack(expand=True)
        tk.Frame(self, bg=BDR, height=1).pack(fill="x")

        body = tk.Frame(self, bg=BG2)
        body.pack(fill="both", expand=True, padx=28, pady=20)

        tk.Label(body, text="설계할 뷰 타입을 선택하세요.",
                 font=("Malgun Gothic", 10), bg=BG2, fg=TX2).pack(pady=(0, 16))

        cards = tk.Frame(body, bg=BG2)
        cards.pack(fill="x")

        items = [
            ("line", "📏", "Line View",
             "보·기둥을 선(Line)으로 모델링\n"
             "단면력 계산 및 RC/Steel 부재 설계\n"
             "(.2dd 파일 형식)", CYN),
            ("plan", "🏗", "Plan View",
             "기둥·슬래브를 평면도로 배치\n"
             "면하중 → 선하중 환산 후 해석\n"
             "(.2dp 파일 형식)", YEL),
        ]
        for view, icon, title, desc, color in items:
            card = tk.Frame(cards, bg=BG3,
                            highlightbackground=BDR,
                            highlightthickness=1)
            card.pack(side="left", fill="both", expand=True,
                      padx=8, pady=4, ipadx=10, ipady=12)

            tk.Label(card, text=icon, font=("Malgun Gothic", 26),
                     bg=BG3, fg=color).pack(pady=(10, 4))
            tk.Label(card, text=title,
                     font=("Malgun Gothic", 11, "bold"),
                     bg=BG3, fg=color).pack()
            tk.Label(card, text=desc, font=("Malgun Gothic", 8),
                     bg=BG3, fg=TX3, justify="center").pack(pady=(6, 10))
            tk.Button(card, text=f"  {title} 열기  ",
                      command=lambda v=view: self._select(v),
                      font=("Malgun Gothic", 9, "bold"),
                      bg=color, fg="#0f1520",
                      relief="flat", cursor="hand2",
                      padx=12, pady=6).pack(pady=(0, 10))

            def _enter(_, c=card): c.config(bg=BG4, highlightbackground=ACCH)
            def _leave(_, c=card): c.config(bg=BG3, highlightbackground=BDR)
            card.bind("<Enter>", _enter)
            card.bind("<Leave>", _leave)

        tk.Frame(body, bg=BG2, height=8).pack()
        tk.Button(body, text="취소", command=self.destroy,
                  font=("Malgun Gothic", 9), bg=BG3, fg=TX2,
                  relief="flat", cursor="hand2",
                  padx=20, pady=7).pack()

    def _select(self, view):
        self.result = view
        self.destroy()


# ═══════════════════════════════════════════════════════════════
#  공개 진입점
# ═══════════════════════════════════════════════════════════════
def open_2d_design(parent, username=""):
    """
    launcher.py 에서 호출:
        from design_2d import open_2d_design
        open_2d_design(self, username=self._user)
    """
    dlg = _ViewSelectDialog(parent, username=username)
    parent.wait_window(dlg)

    if dlg.result == "line":
        return _open_line_view(parent, username)
    elif dlg.result == "plan":
        return _open_plan_view(parent, username)
    return None


def _open_line_view(parent, username=""):
    from .panel import Design2DPanel
    win = tk.Toplevel(parent)
    win.title("Line View  —  2D Design" + (f"  [{username}]" if username else ""))
    win.geometry("1280x760"); win.minsize(900, 600)
    win.configure(bg="#0f1520"); win.lift(); win.focus_force()
    Design2DPanel(win, username=username)
    return win


def _open_plan_view(parent, username=""):
    from .plan_view import PlanViewPanel
    win = tk.Toplevel(parent)
    win.title("Plan View  —  2D Design" + (f"  [{username}]" if username else ""))
    win.geometry("1280x760"); win.minsize(900, 600)
    win.configure(bg="#0f1520"); win.lift(); win.focus_force()
    PlanViewPanel(win, username=username)
    return win
