"""
design_2d/dialogs.py
하중 입력 다이얼로그
"""

import tkinter as tk
from tkinter import messagebox
from .constants import *


class LoadInputDlg(tk.Toplevel):
    """
    fields : [("레이블", "기본값"), ...]
    result : [str, ...] or None
    """
    def __init__(self, parent, title="하중 입력", fields=None):
        super().__init__(parent)
        self.result = None
        self.title(title)
        self.configure(bg=BG2)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        fields = fields or [("값", "0")]
        self._entries = []

        # 헤더
        hdr = tk.Frame(self, bg=ACCD, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text=title, font=("Malgun Gothic", 11, "bold"),
                 bg=ACCD, fg=WHI).pack(expand=True)

        # 필드
        frm = tk.Frame(self, bg=BG2)
        frm.pack(fill="both", expand=True, padx=24, pady=16)
        for label, default in fields:
            tk.Label(frm, text=label, font=("Malgun Gothic", 9),
                     bg=BG2, fg=TX2).pack(anchor="w", pady=(8, 2))
            e = tk.Entry(frm, font=("Malgun Gothic", 11),
                         bg=BG3, fg=TXT, insertbackground=WHI,
                         relief="flat",
                         highlightbackground=BDR, highlightthickness=1)
            e.insert(0, default)
            e.pack(fill="x", ipady=7)
            e.bind("<FocusIn",  lambda _, w=e: w.config(highlightbackground=ACCH))
            e.bind("<FocusOut>", lambda _, w=e: w.config(highlightbackground=BDR))
            self._entries.append(e)

        # 버튼
        br = tk.Frame(frm, bg=BG2)
        br.pack(fill="x", pady=(16, 0))
        tk.Button(br, text="취소", command=self.destroy,
                  font=("Malgun Gothic", 9, "bold"),
                  bg=BG3, fg=TX2, relief="flat", cursor="hand2",
                  pady=7).pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(br, text="확인", command=self._ok,
                  font=("Malgun Gothic", 9, "bold"),
                  bg=ACC, fg=WHI, relief="flat", cursor="hand2",
                  pady=7).pack(side="right", fill="x", expand=True)

        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self.destroy())

        # 중앙 배치
        self.update_idletasks()
        pw = parent.winfo_rootx() + parent.winfo_width()  // 2
        ph = parent.winfo_rooty() + parent.winfo_height() // 2
        h  = 160 + len(fields) * 70
        self.geometry(f"300x{h}+{pw-150}+{ph-h//2}")
        self._entries[0].focus_set()

    def _ok(self):
        try:
            vals = [e.get().strip() for e in self._entries]
            for v in vals:
                float(v)             # 유효성 검사
            self.result = vals
            self.destroy()
        except ValueError:
            messagebox.showerror("오류", "숫자를 입력하세요.", parent=self)
