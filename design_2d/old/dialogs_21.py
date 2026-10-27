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

        # ── 헤더 ─────────────────────────────────────────
        hdr = tk.Frame(self, bg=ACCD, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text=title,
                 font=("Malgun Gothic", 11, "bold"),
                 bg=ACCD, fg=WHI).pack(expand=True)

        # ── 필드 ─────────────────────────────────────────
        frm = tk.Frame(self, bg=BG2)
        frm.pack(fill="both", expand=True, padx=24, pady=16)

        for label, default in fields:
            tk.Label(frm, text=label,
                     font=("Malgun Gothic", 9),
                     bg=BG2, fg=TX2).pack(anchor="w", pady=(8, 2))
            e = tk.Entry(frm,
                         font=("Malgun Gothic", 11),
                         bg=BG3, fg=TXT,
                         insertbackground=WHI,
                         relief="flat",
                         highlightbackground=BDR,
                         highlightthickness=1)
            e.insert(0, default)
            e.pack(fill="x", ipady=7)
            # "<FocusIn>" — 닫는 > 를 포함해야 정상 바인딩됨
            e.bind("<FocusIn>",  lambda _, w=e: w.config(highlightbackground=ACCH))
            e.bind("<FocusOut>", lambda _, w=e: w.config(highlightbackground=BDR))
            self._entries.append(e)

        # ── 버튼 행 ───────────────────────────────────────
        br = tk.Frame(frm, bg=BG2)
        br.pack(fill="x", pady=(20, 4))

        tk.Button(br, text="취소",
                  command=self.destroy,
                  font=("Malgun Gothic", 10, "bold"),
                  bg=BG3, fg=TX2,
                  relief="flat", cursor="hand2",
                  pady=9).pack(side="left", fill="x", expand=True, padx=(0, 6))

        tk.Button(br, text="확인",
                  command=self._ok,
                  font=("Malgun Gothic", 10, "bold"),
                  bg=ACC, fg=WHI,
                  relief="flat", cursor="hand2",
                  pady=9).pack(side="right", fill="x", expand=True)

        # ── 키 바인딩 ─────────────────────────────────────
        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self.destroy())
        self.bind("<Return>",  lambda _: self._apply())

        # ── 창 크기 & 위치 ────────────────────────────────
        self.update_idletasks()
        n_fields = len(fields)
        # 헤더44 + 필드당90 + 버튼행70 + 여백30
        h = 44 + n_fields * 90 + 70 + 30
        w = 320
        px = parent.winfo_rootx() + parent.winfo_width()  // 2 - w // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - h // 2
        self.geometry(f"{w}x{h}+{px}+{py}")

        # 첫 번째 입력창에 포커스 + 전체 선택
        self._entries[0].focus_set()
        self._entries[0].select_range(0, tk.END)

    def _ok(self):
        try:
            vals = [e.get().strip() for e in self._entries]
            for v in vals:
                float(v)        # 숫자 유효성 검사
            self.result = vals
            self.destroy()
        except ValueError:
            messagebox.showerror("입력 오류", "숫자를 입력하세요.", parent=self)


class MemberPropWindow(tk.Toplevel):
    """
    부재(Line) 더블클릭 → 재료/단면 설정 팝업

    line     : dict  {"id", "material", "E", "I", "A", ...}
    on_apply : callable(line_id, material, E, I, A)
    """

    # 직사각형 단면 I 계산
    @staticmethod
    def _rect_I(b, h): return b * h**3 / 12.0
    @staticmethod
    def _rect_A(b, h): return b * h

    def __init__(self, parent, line, on_apply):
        super().__init__(parent)
        self.line     = line
        self.on_apply = on_apply
        self.title("부재 단면 / 재료 설정")
        self.configure(bg=BG2)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # ── 현재 값 읽기 ────────────────────────────────────
        mat  = line.get("material", "RC")
        E_now = line.get("E") or RC_E_DEFAULT
        I_now = line.get("I") or RC_I_DEFAULT
        A_now = line.get("A") or RC_A_DEFAULT

        # ── 내부 변수 ────────────────────────────────────────
        self._mat  = tk.StringVar(value=mat)
        self._fck  = tk.DoubleVar(value=24.0)
        self._b    = tk.DoubleVar(value=RC_B_DEFAULT)
        self._h    = tk.DoubleVar(value=RC_H_DEFAULT)
        self._E_v  = tk.StringVar(value=f"{E_now:.1f}")
        self._I_v  = tk.StringVar(value=f"{I_now:.0f}")
        self._A_v  = tk.StringVar(value=f"{A_now:.1f}")

        # ── 헤더 ─────────────────────────────────────────────
        hdr = tk.Frame(self, bg=ACCD, height=46)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr,
                 text=f"📐  부재 L{line['id']}  —  단면 / 재료 설정",
                 font=("Malgun Gothic", 11, "bold"),
                 bg=ACCD, fg=WHI).pack(expand=True)

        body = tk.Frame(self, bg=BG2)
        body.pack(fill="both", expand=True, padx=20, pady=12)

        # ── ① 재료 선택 ─────────────────────────────────────
        self._section_lbl(body, "■ 재료 종류")
        mat_row = tk.Frame(body, bg=BG2)
        mat_row.pack(fill="x", pady=(4, 10))

        for code, label, color in [("RC", "철근콘크리트 (RC)", RC_COLOR),
                                   ("STEEL", "철골 (Steel)",   STEEL_COLOR)]:
            rb = tk.Radiobutton(mat_row, text=label,
                                variable=self._mat, value=code,
                                font=("Malgun Gothic", 10, "bold"),
                                bg=BG2, fg=color,
                                selectcolor=BG4,
                                activebackground=BG2,
                                activeforeground=WHI,
                                command=self._on_mat_change)
            rb.pack(side="left", padx=(0, 16))

        # ── ② RC 설정 ───────────────────────────────────────
        self._rc_frame = tk.Frame(body, bg=BG3,
                                  highlightbackground=BDR,
                                  highlightthickness=1)
        self._rc_frame.pack(fill="x", pady=4)
        self._section_lbl(self._rc_frame, "■ 콘크리트 강도 / 단면 치수", sub=True)

        def _inp(parent, label, var, unit=""):
            row = tk.Frame(parent, bg=BG3)
            row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=label, width=12, anchor="w",
                     font=("Malgun Gothic", 9), bg=BG3, fg=TX2).pack(side="left")
            e = tk.Entry(row, textvariable=var, width=12,
                         font=("Malgun Gothic", 10, "bold"),
                         bg=BG4, fg=YEL, insertbackground=WHI,
                         relief="flat",
                         highlightbackground=BDR, highlightthickness=1)
            e.pack(side="left", ipady=5, padx=(4, 2))
            e.bind("<FocusIn>",  lambda _, w=e: w.config(highlightbackground=ACCH))
            e.bind("<FocusOut>", lambda _, w=e: w.config(highlightbackground=BDR))
            e.bind("<Return>",   lambda _: self._recalc())
            e.bind("<FocusOut>", lambda _: self._recalc())
            if unit:
                tk.Label(row, text=unit, font=("Malgun Gothic", 9),
                         bg=BG3, fg=TX3).pack(side="left")
            return e

        _inp(self._rc_frame, "fck",   self._fck, "MPa")
        _inp(self._rc_frame, "폭 b",  self._b,   "mm")
        _inp(self._rc_frame, "높이 h", self._h,  "mm")

        # ── ③ 직접 E / I / A 입력 ──────────────────────────
        self._section_lbl(body, "■ 단면 상수 (직접 입력 가능)")
        eframe = tk.Frame(body, bg=BG3,
                          highlightbackground=BDR, highlightthickness=1)
        eframe.pack(fill="x", pady=4)
        self._eia_frame = eframe
        self._parent_ref = parent

        for lbl, var, unit in [
            ("E (탄성계수)", self._E_v, "MPa"),
            ("I (단면2차모멘트)", self._I_v, "mm⁴"),
            ("A (단면적)", self._A_v, "mm²"),
        ]:
            row = tk.Frame(eframe, bg=BG3)
            row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=lbl, width=14, anchor="w",
                     font=("Malgun Gothic", 9), bg=BG3, fg=TX2).pack(side="left")
            e = tk.Entry(row, textvariable=var, width=16,
                         font=("Malgun Gothic", 10, "bold"),
                         bg=BG4, fg=CYN, insertbackground=WHI,
                         relief="flat",
                         highlightbackground=BDR, highlightthickness=1)
            e.pack(side="left", ipady=5, padx=(4, 2))
            e.bind("<FocusIn>",  lambda _, w=e: w.config(highlightbackground=ACCH))
            e.bind("<FocusOut>", lambda _, w=e: w.config(highlightbackground=BDR))
            if unit:
                tk.Label(row, text=unit, font=("Malgun Gothic", 9),
                         bg=BG3, fg=TX3).pack(side="left")

        # ── ④ 자동계산 버튼 ─────────────────────────────────
        tk.Button(body, text="↻  RC 단면 자동 계산 (fck / b / h → E, I, A)",
                  command=self._recalc,
                  font=("Malgun Gothic", 9),
                  bg=BG4, fg=GRN,
                  relief="flat", cursor="hand2",
                  pady=6).pack(fill="x", pady=(6, 2))

        # ── ⑤ 버튼 행 ──────────────────────────────────────
        br = tk.Frame(body, bg=BG2)
        br.pack(fill="x", pady=(12, 4))
        self._btn_row = br
        tk.Button(br, text="취소",
                  command=self.destroy,
                  font=("Malgun Gothic", 10, "bold"),
                  bg=BG3, fg=TX2,
                  relief="flat", cursor="hand2",
                  pady=9).pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(br, text="✔  적용",
                  command=self._apply,
                  font=("Malgun Gothic", 10, "bold"),
                  bg=ACC, fg=WHI,
                  relief="flat", cursor="hand2",
                  pady=9).pack(side="right", fill="x", expand=True)

        self.bind("<Escape>", lambda _: self.destroy())
        self.bind("<Return>",  lambda _: self._apply())

        # ── 초기 UI 상태 ─────────────────────────────────────
        self._on_mat_change()

        # ── 창 크기 & 위치 (초기: _on_mat_change에서 동적 설정) ──
        self.update_idletasks()

    def _section_lbl(self, parent, text, sub=False):
        tk.Label(parent, text=text,
                 font=("Malgun Gothic", 9, "bold"),
                 bg=BG3 if sub else BG2,
                 fg=ACC if not sub else TX2,
                 padx=8 if sub else 0,
                 pady=4).pack(anchor="w", pady=(8 if not sub else 4, 0))

    def _on_mat_change(self):
        mat = self._mat.get()
        if mat == "RC":
            self._rc_frame.pack(fill="x", pady=4, before=self._eia_frame)
            self._recalc()
            h = 560
        else:
            self._rc_frame.pack_forget()
            # 철골 기본값 세팅
            self._E_v.set(f"{STEEL_E_DEFAULT:.0f}")
            self._I_v.set(f"{STEEL_I_DEFAULT:.0f}")
            self._A_v.set(f"{STEEL_A_DEFAULT:.1f}")
            h = 420
        # 창 높이 동적 조정 (버튼 행이 항상 보이도록)
        if hasattr(self, "_parent_ref"):
            w = 460
            px = self._parent_ref.winfo_rootx() + self._parent_ref.winfo_width()//2 - w//2
            py = self._parent_ref.winfo_rooty() + self._parent_ref.winfo_height()//2 - h//2
            self.geometry(f"{w}x{h}+{px}+{py}")

    def _recalc(self):
        """fck / b / h → E, I, A 자동 계산"""
        try:
            fck = self._fck.get()
            b   = self._b.get()
            h   = self._h.get()
            E   = 8500 * (fck + 4) ** (1/3)
            I   = b * h**3 / 12.0
            A   = b * h
            self._E_v.set(f"{E:.1f}")
            self._I_v.set(f"{I:.0f}")
            self._A_v.set(f"{A:.0f}")
        except Exception:
            pass

    def _apply(self):
        try:
            E = float(self._E_v.get())
            I = float(self._I_v.get())
            A = float(self._A_v.get())
        except ValueError:
            messagebox.showerror("입력 오류", "E, I, A 값을 숫자로 입력하세요.", parent=self)
            return
        if E <= 0 or I <= 0 or A <= 0:
            messagebox.showerror("입력 오류", "E, I, A 는 0보다 커야 합니다.", parent=self)
            return
        self.on_apply(self.line["id"], self._mat.get(), E, I, A)
        self.destroy()
