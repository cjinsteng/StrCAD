"""라이선스 창 (기기 코드 확인 · 키 등록 · 체험판 안내) + 실행 전 확인 ensure_license()."""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import licensing as LC
from . import theme as TH

STATE_COLOR = {"licensed": TH.OK, "trial": TH.ORANGE_D, "expired": TH.NG, "trial_expired": TH.NG,
               "invalid": TH.NG, "clock": TH.NG}
STATE_TITLE = {"licensed": "정품 라이선스", "trial": "체험판 사용 중", "expired": "사용 기간 만료",
               "trial_expired": "체험 기간 종료", "invalid": "라이선스 확인 필요", "clock": "PC 날짜 오류"}


class LicenseDialog(tk.Toplevel):
    """modal. self.status = 닫을 때의 최신 status()."""

    def __init__(self, parent, st=None, module=None, blocking=False):
        super().__init__(parent)
        TH.ensure(parent)
        self.status = st or LC.status()
        self.module = module
        self.blocking = blocking
        self.title(f"{LC.PRODUCT} 라이선스")
        self.configure(bg=TH.PANEL)
        self.resizable(False, False)
        try:
            TH.set_icon(self)
        except tk.TclError:
            pass
        self.transient(parent)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda e: self._close())
        self.update_idletasks()
        try:
            px = parent.winfo_rootx() + parent.winfo_width() // 2
            py = parent.winfo_rooty() + parent.winfo_height() // 2
            if parent.winfo_width() < 50:
                raise tk.TclError
        except tk.TclError:
            px, py = self.winfo_screenwidth() // 2, self.winfo_screenheight() // 2
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"+{max(px - w // 2, 0)}+{max(py - h // 2, 0)}")
        self.grab_set()
        self.focus_force()

    # ------------------------------------------------------------------ UI
    def _build(self):
        hd = tk.Frame(self, bg=TH.NAVY)
        hd.pack(fill="x")
        logo = TH.image("icon_64.png")
        if logo is not None:
            tk.Label(hd, image=logo, bg=TH.NAVY).pack(side="left", padx=(16, 10), pady=12)
        t = tk.Frame(hd, bg=TH.NAVY)
        t.pack(side="left", pady=12)
        tk.Label(t, text=f"{LC.PRODUCT} 라이선스", bg=TH.NAVY, fg="white", font=TH.FONT_XL).pack(anchor="w")
        tk.Label(t, text="사용 기간 · 기기 등록", bg=TH.NAVY, fg=TH.ORANGE, font=TH.FONT_B).pack(anchor="w")

        body = tk.Frame(self, bg=TH.PANEL)
        body.pack(fill="both", padx=22, pady=(14, 8))
        # status card
        self.card = tk.Frame(body, bg=TH.SURFACE, highlightthickness=1, highlightbackground=TH.LINE)
        self.card.pack(fill="x")
        self.st_title = tk.Label(self.card, bg=TH.SURFACE, font=(TH.FAM, 13, "bold"), anchor="w")
        self.st_title.pack(fill="x", padx=12, pady=(10, 0))
        self.st_msg = tk.Label(self.card, bg=TH.SURFACE, fg=TH.INK, font=TH.FONT_M, anchor="w", justify="left",
                               wraplength=470)
        self.st_msg.pack(fill="x", padx=12, pady=(2, 4))
        self.st_rows = tk.Frame(self.card, bg=TH.SURFACE)
        self.st_rows.pack(fill="x", padx=12, pady=(0, 10))

        # machine code
        tk.Label(body, text="이 PC의 기기 코드", bg=TH.PANEL, fg=TH.NAVY, font=TH.FONT_B).pack(anchor="w", pady=(14, 2))
        r = tk.Frame(body, bg=TH.PANEL)
        r.pack(fill="x")
        code = tk.Entry(r, font=("Consolas", 15, "bold"), fg=TH.NAVY, relief="flat", justify="center",
                        readonlybackground=TH.INPUT, highlightthickness=1, highlightbackground=TH.LINE, width=22)
        code.insert(0, self.status["code"])
        code.configure(state="readonly")
        code.pack(side="left", ipady=6)
        ttk.Button(r, text="복사", command=self._copy_code).pack(side="left", padx=8)
        tk.Label(body, text="라이선스를 구매·연장할 때 이 코드를 알려 주세요. 코드에 맞춘 키를 보내 드립니다.",
                 bg=TH.PANEL, fg=TH.MUTED, font=TH.FONT_S).pack(anchor="w", pady=(3, 0))

        # key entry
        tk.Label(body, text="라이선스 키", bg=TH.PANEL, fg=TH.NAVY, font=TH.FONT_B).pack(anchor="w", pady=(14, 2))
        self.key = tk.Text(body, height=4, width=60, font=("Consolas", 9), relief="flat", wrap="char",
                           highlightthickness=1, highlightbackground=TH.LINE, highlightcolor=TH.ORANGE)
        self.key.pack(fill="x")
        cur = LC.load_key()
        if cur:
            self.key.insert("1.0", cur)
        kb = tk.Frame(body, bg=TH.PANEL)
        kb.pack(fill="x", pady=(6, 0))
        ttk.Button(kb, text="붙여넣기", command=self._paste).pack(side="left")
        ttk.Button(kb, text="키 파일 열기…", command=self._open_file).pack(side="left", padx=6)
        if cur:
            ttk.Button(kb, text="등록 해제", command=self._remove).pack(side="left")
        ttk.Button(kb, text="✔ 등록", style="Accent.TButton", command=self._activate).pack(side="right")

        tk.Label(body, text=LC.SUPPORT, bg=TH.PANEL, fg=TH.MUTED, font=TH.FONT_S).pack(anchor="w", pady=(12, 0))

        foot = tk.Frame(self, bg=TH.SURFACE)
        foot.pack(fill="x", side="bottom")
        self.btn_close = ttk.Button(foot, style="Navy.TButton", command=self._close)
        self.btn_close.pack(side="right", padx=16, pady=10)
        if self.blocking:
            ttk.Button(foot, text="종료", command=self._quit).pack(side="right", pady=10)
        self._show()

    def _show(self):
        st = self.status
        s = st.get("state")
        self.st_title.config(text=("✔ " if st.get("ok") else "⚠ ") + STATE_TITLE.get(s, s), fg=STATE_COLOR.get(s, TH.INK))
        self.st_msg.config(text=st.get("message", ""))
        for w in self.st_rows.winfo_children():
            w.destroy()
        rows = []
        if s in ("licensed", "expired", "invalid") and st.get("customer"):
            rows += [("사용자", st["customer"]), ("에디션", st.get("edition", "")),
                     ("사용 기간", (st["expiry"] + "까지") if st.get("expiry") else "영구"),
                     ("일련번호", st.get("serial", ""))]
            mods = st.get("modules") or set()
            if mods and "*" not in mods:
                rows.append(("사용 모듈", ", ".join(LC.MODULES.get(m, m) for m in sorted(mods))))
        elif s in ("trial", "trial_expired"):
            rows += [("체험 기간", f"{st.get('trial_days')}일 · {st.get('expiry')}까지")]
        for i, (k, v) in enumerate(rows):
            tk.Label(self.st_rows, text=k, bg=TH.SURFACE, fg=TH.MUTED, font=TH.FONT).grid(row=i, column=0, sticky="w")
            tk.Label(self.st_rows, text=v, bg=TH.SURFACE, fg=TH.INK, font=TH.FONT).grid(row=i, column=1, sticky="w",
                                                                                      padx=12)
        ok = st.get("ok") and (self.module is None or LC.allows(st, self.module))
        self.btn_close.config(text="계속" if ok else ("닫기" if not self.blocking else "나중에"))
        if self.blocking and not ok:
            self.btn_close.config(state="disabled")
        else:
            self.btn_close.config(state="normal")

    # ------------------------------------------------------------------ actions
    def _copy_code(self):
        self.clipboard_clear()
        self.clipboard_append(self.status["code"])
        messagebox.showinfo("기기 코드", f"기기 코드를 복사했습니다.\n{self.status['code']}", parent=self)

    def _paste(self):
        try:
            t = self.clipboard_get()
        except tk.TclError:
            return
        self.key.delete("1.0", "end")
        self.key.insert("1.0", LC.clean_key(t))

    def _open_file(self):
        p = filedialog.askopenfilename(parent=self, title="라이선스 키 파일",
                                       filetypes=[("StrCAD 라이선스", "*.strlic *.key *.txt"), ("모든 파일", "*.*")])
        if not p:
            return
        try:
            with open(p, encoding="utf-8") as f:
                t = f.read()
        except (OSError, UnicodeDecodeError) as e:
            messagebox.showerror("라이선스", f"파일을 읽을 수 없습니다.\n{e}", parent=self)
            return
        self.key.delete("1.0", "end")
        self.key.insert("1.0", LC.clean_key(t))
        self._activate()

    def _activate(self):
        k = self.key.get("1.0", "end").strip()
        if not k:
            messagebox.showwarning("라이선스", "라이선스 키를 붙여 넣으세요.", parent=self)
            return
        try:
            self.status = LC.activate(k)
        except LC.LicenseError as e:
            messagebox.showerror("라이선스 등록 실패", str(e), parent=self)
            return
        self._show()
        messagebox.showinfo("라이선스 등록", "라이선스가 등록되었습니다.\n" + self.status.get("message", ""), parent=self)

    def _remove(self):
        if not messagebox.askyesno("등록 해제", "이 PC에서 라이선스 키를 지울까요?\n(다른 PC로 옮길 때 사용)", parent=self):
            return
        LC.remove_key()
        self.key.delete("1.0", "end")
        self.status = LC.status()
        self._show()

    def _close(self):
        if self.blocking and not (self.status.get("ok") and (self.module is None or LC.allows(self.status, self.module))):
            self._quit()
            return
        self.grab_release()
        self.destroy()

    def _quit(self):
        self.status = dict(self.status, ok=False)
        self.grab_release()
        self.destroy()


def ensure_license(parent, module=None, blocking=True, warn=True):
    """실행 전 확인. 사용 가능하면 status dict, 아니면 None (창에서 키 등록 기회를 줌)."""
    st = LC.status()
    good = st.get("ok") and (module is None or LC.allows(st, module))
    if good:
        dl = st.get("days_left")
        if warn and LC.should_warn(st):
            msg = (f"체험판이 {dl}일 남았습니다." if st["state"] == "trial" else f"라이선스 만료까지 {dl}일 남았습니다 ({st['expiry']}).")
            messagebox.showinfo(f"{LC.PRODUCT} 라이선스", msg + "\n\n도움말 › 라이선스에서 키를 등록·연장할 수 있습니다.",
                                parent=parent)
        return st
    if st.get("ok") and module and not LC.allows(st, module):
        st = dict(st, message=f"현재 라이선스에는 '{LC.MODULES.get(module, module)}' 모듈이 포함되어 있지 않습니다.")
    dlg = LicenseDialog(parent, st, module=module, blocking=blocking)
    parent.wait_window(dlg)
    st = dlg.status
    return st if st.get("ok") and (module is None or LC.allows(st, module)) else None
