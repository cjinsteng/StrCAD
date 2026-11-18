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
    """2D Design 진입 시 단면해석 / 평면해석 선택"""

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
        tk.Label(hdr, text="📐  2D Design  —  해석 종류 선택",
                 font=("Malgun Gothic", 12, "bold"),
                 bg="#0f1a30", fg=WHI).pack(expand=True)
        tk.Frame(self, bg=BDR, height=1).pack(fill="x")

        body = tk.Frame(self, bg=BG2)
        body.pack(fill="both", expand=True, padx=28, pady=20)

        tk.Label(body, text="해석 종류를 선택하세요.",
                 font=("Malgun Gothic", 10), bg=BG2, fg=TX2).pack(pady=(0, 16))

        cards = tk.Frame(body, bg=BG2)
        cards.pack(fill="x")

        items = [
            ("section", "📏", "단면해석",
             "노드·부재로 골조 단면 모델링\n"
             "지점·구속률·단부해제, 집중/분포하중\n"
             "→ 모멘트·전단·축력·반력 (.2df)", CYN),
            ("plan", "🏗", "평면해석",
             "노드·선·면을 그리고 보·슬래브·지점 적용\n"
             "집중·선·면하중 → 슬래브+보 유한요소해석\n"
             "→ 슬래브 Mx·My·Qx·Qy·처짐, 보 M·V (.2dp)", YEL),
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

    if dlg.result == "section":
        return _open_section_view(parent, username)
    elif dlg.result == "plan":
        return _open_plan_view(parent, username)
    return None


def _open_section_view(parent, username=""):
    from .section import open_section_analysis
    return open_section_analysis(parent, username)


def _open_plan_view(parent, username=""):
    from .plan import open_plan_analysis
    return open_plan_analysis(parent, username)
