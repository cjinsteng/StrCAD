"""
STR Design & Check  —  런처 메인 화면
· 헤더: 타이틀 / 로그인 상태 / [로그인] 버튼
· 2×3 모듈 카드 그리드 (로그인 전 잠금)
· CAD Analysis → DXF 분석기 창 실행
· Report Design → 진단·검토 보고서 작성 도우미 (report_design/)
· 하단 ver. 1.0.0
기본 계정: 1234 / 1234   |   user1 / pass1234   ·   회원가입한 계정 (accounts.py, ~/.strcad/users.json)
"""

import sys, os, hashlib, threading, subprocess, webbrowser
from pathlib import Path

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS);  WORK_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent; WORK_DIR = Path(__file__).parent

sys.path.insert(0, str(BASE_DIR))
for _d in (BASE_DIR / "strcad_cad_analysis", WORK_DIR / "strcad_cad_analysis"):     # cad_analysis 패키지 (라이선스 포함)
    if (_d / "cad_analysis").exists() and str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:                                    # 라이선스 (사용기간 · 체험판 · PC 고정)
    from cad_analysis import licensing as LC
    from cad_analysis.licensing_ui import LicenseDialog
except Exception as _e:                 # noqa: BLE001  — 라이선스 모듈이 없으면 실행하지 않음
    LC = None; _LIC_ERR = _e

# ── 팔레트 ────────────────────────────────────────────────
BG  = "#0f1520"; BG2 = "#141d2e"; BG3 = "#1a2540"
BG4 = "#1f2d4a"; BG5 = "#263556"
BDR = "#2c3f62"; BDR2 = "#3a5280"
ACC = "#1a56db"; ACCH = "#2563eb"; ACCD = "#1e40af"
GRN = "#15803d"; GRNH = "#16a34a"
RED = "#dc2626"; ORG = "#d97706"; BLU = "#3b82f6"
TXT = "#dde4f0"; TX2 = "#8fa3c0"; TX3 = "#546887"
WHI = "#f0f5ff"; DIS = "#3d5070"
VER = "ver. 1.0.0"

import accounts as ACC_DB          # 회원가입 · 로그인 (accounts.py)
def _auth(u, p): return ACC_DB.authenticate(u, p)
def _dk(h, a=20): return "#{:02x}{:02x}{:02x}".format(
    max(0,int(h[1:3],16)-a), max(0,int(h[3:5],16)-a), max(0,int(h[5:7],16)-a))


# ── 로그인 다이얼로그 ─────────────────────────────────────
class LoginDlg(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent); self.result = None
        self.title("로그인"); self.configure(bg=BG2)
        self.resizable(False,False); self.transient(parent); self.grab_set()
        self._build()
        self.update_idletasks()
        px = parent.winfo_rootx()+parent.winfo_width()//2
        py = parent.winfo_rooty()+parent.winfo_height()//2
        self.geometry(f"360x370+{px-180}+{py-185}")
        self.bind("<Return>", lambda _: self._try())
        self.bind("<Escape>", lambda _: self.destroy())
        self.after(60, self._id.focus_set)

    def _build(self):
        hdr = tk.Frame(self, bg=ACCD, height=54); hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="🔐   로그인", font=("Malgun Gothic",14,"bold"),
                 bg=ACCD, fg=WHI).pack(expand=True)
        frm = tk.Frame(self, bg=BG2); frm.pack(fill="both", expand=True, padx=30, pady=20)
        def field(lbl, show=""):
            tk.Label(frm, text=lbl, font=("Malgun Gothic",9), bg=BG2, fg=TX2, anchor="w").pack(fill="x", pady=(10,3))
            e = tk.Entry(frm, font=("Malgun Gothic",11), bg=BG3, fg=TXT,
                         insertbackground=WHI, relief="flat", show=show,
                         highlightbackground=BDR, highlightthickness=1)
            e.pack(fill="x", ipady=8)
            e.bind("<FocusIn>",  lambda _: e.config(highlightbackground=ACCH))
            e.bind("<FocusOut>", lambda _: e.config(highlightbackground=BDR))
            return e
        self._id = field("아이디"); self._pw = field("비밀번호", "●")
        self._err = tk.StringVar(); self._ok = tk.StringVar()
        tk.Label(frm, textvariable=self._err, font=("Malgun Gothic",8), bg=BG2, fg=RED).pack(anchor="w", pady=(6,0))
        tk.Label(frm, textvariable=self._ok, font=("Malgun Gothic",8), bg=BG2, fg=GRNH).pack(anchor="w")
        br = tk.Frame(frm, bg=BG2); br.pack(fill="x", pady=(14,0))
        def mkb(p, t, cmd, bg_, fg_):
            b = tk.Button(p, text=t, command=cmd, font=("Malgun Gothic",10,"bold"),
                          bg=bg_, fg=fg_, relief="flat", cursor="hand2", pady=8)
            b.bind("<Enter>", lambda _: b.config(bg=_dk(bg_)))
            b.bind("<Leave>", lambda _: b.config(bg=bg_)); return b
        mkb(br,"취소",self.destroy,BG3,TX2).pack(side="left", fill="x", expand=True, padx=(0,6))
        mkb(br,"로그인",self._try,ACC,WHI).pack(side="right", fill="x", expand=True)
        sg = tk.Frame(frm, bg=BG2); sg.pack(fill="x", pady=(12,0))
        tk.Label(sg, text="계정이 없으신가요?", font=("Malgun Gothic",9), bg=BG2, fg=TX3).pack(side="left")
        lk = tk.Label(sg, text="회원가입", font=("Malgun Gothic",9,"bold","underline"), bg=BG2, fg=BLU, cursor="hand2")
        lk.pack(side="left", padx=6); lk.bind("<Button-1>", lambda _: self._signup())

    def _signup(self):
        self.grab_release()
        dlg = SignupDlg(self); self.wait_window(dlg)
        try: self.grab_set()
        except tk.TclError: pass
        if dlg.result:
            self._id.delete(0,"end"); self._id.insert(0, dlg.result)
            self._pw.delete(0,"end"); self._pw.focus_set()
            self._err.set("")
            self._ok.set("가입 완료! 비밀번호를 입력해 로그인하세요.")

    def _try(self):
        u = self._id.get().strip(); p = self._pw.get()
        if not u or not p: self._err.set("아이디와 비밀번호를 입력하세요."); return
        info = _auth(u, p)
        if info: self.result = info; self.destroy()
        else:
            self._err.set("아이디 또는 비밀번호가 틀렸습니다.")
            self._pw.delete(0,"end"); self._pw.focus_set()


# ── 회원가입 다이얼로그 ───────────────────────────────────
class SignupDlg(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent); self.result = None
        self.title("회원가입"); self.configure(bg=BG2)
        self.resizable(False,False); self.transient(parent); self.grab_set()
        hdr = tk.Frame(self, bg=ACCD, height=54); hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="📝   회원가입", font=("Malgun Gothic",14,"bold"), bg=ACCD, fg=WHI).pack(expand=True)
        frm = tk.Frame(self, bg=BG2); frm.pack(fill="both", expand=True, padx=30, pady=14)
        self.e = {}
        rows = [("id","아이디 *","영문·숫자 4~20자",""), ("pw","비밀번호 *","영문+숫자 8자 이상","●"),
                ("pw2","비밀번호 확인 *","","●"), ("name","이름 *","",""), ("company","회사","",""),
                ("email","이메일","",""), ("phone","연락처","","")]
        for k,lbl,hint,show in rows:
            r = tk.Frame(frm, bg=BG2); r.pack(fill="x", pady=(6,0))
            tk.Label(r, text=lbl, font=("Malgun Gothic",9), bg=BG2, fg=TX2, width=12, anchor="w").pack(side="left")
            e = tk.Entry(r, font=("Malgun Gothic",10), bg=BG3, fg=TXT, insertbackground=WHI, relief="flat",
                         show=show, highlightbackground=BDR, highlightthickness=1, width=24)
            e.pack(side="left", fill="x", expand=True, ipady=5)
            e.bind("<FocusIn>",  lambda _, w=e: w.config(highlightbackground=ACCH))
            e.bind("<FocusOut>", lambda _, w=e: w.config(highlightbackground=BDR))
            self.e[k] = e
            if hint:
                tk.Label(frm, text=hint, font=("Malgun Gothic",7), bg=BG2, fg=TX3, anchor="e").pack(fill="x")
        self.e["id"].bind("<FocusOut>", lambda _: self._check_id(), add="+")
        self._err = tk.StringVar()
        tk.Label(frm, textvariable=self._err, font=("Malgun Gothic",8), bg=BG2, fg=RED, wraplength=290,
                 justify="left").pack(anchor="w", pady=(8,0))
        tk.Label(frm, text="계정 정보는 이 PC에만 저장되며 비밀번호는 암호화(해시)되어 보관됩니다.",
                 font=("Malgun Gothic",7), bg=BG2, fg=TX3, wraplength=290, justify="left").pack(anchor="w")
        br = tk.Frame(frm, bg=BG2); br.pack(fill="x", pady=(10,0))
        for t,cmd,bg_,fg_,side in (("취소",self.destroy,BG3,TX2,"left"),("가입하기",self._ok,ACC,WHI,"right")):
            b = tk.Button(br, text=t, command=cmd, font=("Malgun Gothic",10,"bold"), bg=bg_, fg=fg_,
                          relief="flat", cursor="hand2", pady=8)
            b.pack(side=side, fill="x", expand=True, padx=(0,6) if side=="left" else 0)
        self.bind("<Return>", lambda _: self._ok()); self.bind("<Escape>", lambda _: self.destroy())
        self.update_idletasks()
        px = parent.winfo_rootx()+parent.winfo_width()//2; py = parent.winfo_rooty()+parent.winfo_height()//2
        w, h = 380, self.winfo_reqheight()
        self.geometry(f"{w}x{h}+{px-w//2}+{max(py-h//2,0)}")
        self.after(60, self.e["id"].focus_set)

    def _check_id(self):
        u = self.e["id"].get().strip()
        if u and ACC_DB.exists(u): self._err.set("이미 사용 중인 아이디입니다.")
        elif u and not ACC_DB.ID_RE.match(u): self._err.set("아이디는 영문·숫자·_ . - 로 4~20자입니다.")
        else: self._err.set("")

    def _ok(self):
        v = {k: e.get() for k,e in self.e.items()}
        if v["pw"] != v["pw2"]:
            self._err.set("비밀번호 확인이 일치하지 않습니다."); self.e["pw2"].delete(0,"end"); self.e["pw2"].focus_set(); return
        try:
            u = ACC_DB.register(v["id"], v["pw"], v["name"], v["company"], v["email"], v["phone"])
        except ACC_DB.AccountError as e:
            self._err.set(str(e)); return
        except OSError as e:
            self._err.set(f"저장하지 못했습니다: {e}"); return
        self.result = u["id"]; self.destroy()


# ── 모듈 카드 ─────────────────────────────────────────────
class ModCard(tk.Frame):
    def __init__(self, parent, title, subtitle, icon, badge=None, locked=True, on_click=None):
        super().__init__(parent)
        self._t=title; self._s=subtitle; self._i=icon
        self._badge=badge; self._locked=locked; self._cb=on_click; self._why=""
        self._draw()

    def _draw(self):
        for w in self.winfo_children(): w.destroy()
        lk = self._locked
        bg = BG3 if lk else BG4; bdr = BDR if lk else BDR2
        self.configure(bg=bg, highlightbackground=bdr, highlightthickness=1,
                       cursor="arrow" if lk else "hand2")
        inn = tk.Frame(self, bg=bg); inn.pack(fill="both", expand=True, padx=16, pady=14)
        top = tk.Frame(inn, bg=bg); top.pack(fill="x")
        tk.Label(top, text=self._i, font=("Segoe UI Emoji",26),
                 bg=bg, fg=ACCH if not lk else DIS).pack(side="left")
        if lk:
            tk.Label(top, text="🔒", font=("Segoe UI Emoji",13), bg=bg, fg=DIS).pack(side="right", anchor="n")
            if self._why:
                tk.Label(inn, text=self._why, font=("Malgun Gothic",8,"bold"), bg=bg, fg=ORG,
                         anchor="w").pack(fill="x", side="bottom")
        elif self._badge:
            tk.Label(top, text=f"  {self._badge}  ", font=("Malgun Gothic",7,"bold"),
                     bg=BLU, fg=WHI).pack(side="right", anchor="n")
        tk.Label(inn, text=self._t, font=("Malgun Gothic",12,"bold"),
                 bg=bg, fg=TXT if not lk else DIS, anchor="w").pack(fill="x", pady=(10,3))
        if self._s:
            tk.Label(inn, text=self._s, font=("Malgun Gothic",8),
                     bg=bg, fg=TX2 if not lk else DIS,
                     anchor="w", justify="left", wraplength=180).pack(fill="x")
        if not lk:
            tk.Frame(inn, bg=bg, height=6).pack()
            tk.Frame(inn, bg=ACC, height=2).pack(fill="x", side="bottom")
        ws = [self, inn] + inn.winfo_children()
        if not lk:
            for w in ws:
                w.bind("<Button-1>", self._click)
                w.bind("<Enter>",    self._hon)
                w.bind("<Leave>",    self._hoff)
        else:
            for w in ws: w.bind("<Button-1>", self._shake)

    def _click(self, _=None):
        if self._cb: self._cb()
    def _shake(self, _=None):
        orig = self.cget("highlightbackground")
        self.configure(highlightbackground=RED)
        self.after(180, lambda: self.configure(highlightbackground=orig))
    def _hon(self, _=None):
        self.configure(bg=BG5, highlightbackground=ACCH); self._tint(BG5)
    def _hoff(self, _=None):
        self.configure(bg=BG4, highlightbackground=BDR2); self._tint(BG4)
    def _tint(self, c):
        def rec(w):
            try:
                if not isinstance(w,(tk.Button,ttk.Widget)): w.configure(bg=c)
            except: pass
            for ch in w.winfo_children(): rec(ch)
        rec(self)
        for ch in self.winfo_children():
            for cc in ch.winfo_children():
                if isinstance(cc,tk.Frame) and cc.winfo_height()<=2:
                    try: cc.configure(bg=ACC)
                    except: pass
    def unlock(self): self._locked=False; self._why=""; self._draw()
    def lock(self, why=""): self._locked=True; self._why=why; self._draw()


# ── 메인 런처 ─────────────────────────────────────────────
class Launcher(tk.Tk):
    _MODS = [
        ("basic_design","Basic Design", "구조 기본 설계",     "📐",None,  0,0),
        ("2d_design",   "2D Design",    "2D 도면 작업",       "✏️","NEW", 0,1),
        ("3d_design",   "3D Design",    "3D 구조 모델링",     "🧱","NEW", 0,2),
        ("cad_analysis","CAD Analysis", "DXF 구조도면 분석",  "🔍",None,  1,0),
        ("auto_table",  "Auto Table",   "보·기둥·슬래브·벽\n배근표 자동 작성", "📊","NEW", 1,1),
        ("report_design","Report Design","진단·검토 보고서\n작성 도우미", "📝","NEW", 1,2),
    ]
    def __init__(self):
        super().__init__()
        self.title("STR Design & Check")
        self.geometry("920x590"); self.minsize(800,520)
        self.configure(bg=BG); self.resizable(True,True)
        self._user = ""; self._cards = {}; self._lic = None
        self._build(); self._center()
        try:
            from cad_analysis import theme as _TH; _TH.set_icon(self)
        except Exception: pass
        if LC is None:
            self.after(300, lambda: (messagebox.showerror("라이선스", f"라이선스 모듈을 불러오지 못했습니다.\n{_LIC_ERR}",
                                                          parent=self), self.destroy()))

    def _build(self):
        self._build_hdr()
        tk.Frame(self, bg=BDR, height=1).pack(fill="x")
        self._build_grid()
        tk.Frame(self, bg=BDR, height=1).pack(fill="x", side="bottom")
        self._build_ftr()

    def _build_hdr(self):
        hdr = tk.Frame(self, bg=BG2, height=76); hdr.pack(fill="x"); hdr.pack_propagate(False)
        lf = tk.Frame(hdr, bg=BG2); lf.pack(side="left", padx=32, pady=14)
        tk.Label(lf, text="STR Design & Check",
                 font=("Malgun Gothic",18,"bold"), bg=BG2, fg=WHI).pack(anchor="w")
        tk.Label(lf, text="Structural Design & Analysis Platform",
                 font=("Malgun Gothic",8), bg=BG2, fg=TX3).pack(anchor="w", pady=(2,0))
        rf = tk.Frame(hdr, bg=BG2); rf.pack(side="right", padx=28, pady=20)
        self._licb = tk.Button(rf, text="라이선스 확인 중…", font=("Malgun Gothic",9,"bold"), bg=BG4, fg=TX2,
                               relief="flat", cursor="hand2", padx=10, pady=4, command=self._license_dialog)
        self._sv = tk.StringVar(value="로그인 후 이용하세요")
        self._svl = tk.Label(rf, textvariable=self._sv, font=("Malgun Gothic",9), bg=BG2, fg=TX2)
        self._svl.pack(side="left", padx=(0,18))          # 라이선스 버튼은 로그인 후 이 앞에 표시
        self._lb = tk.Button(rf, text="  로그인  ",
                             font=("Malgun Gothic",10,"bold"),
                             bg=ACC, fg=WHI, relief="flat", cursor="hand2",
                             padx=18, pady=6, command=self._toggle)
        self._lb.pack(side="left")
        self._lb.bind("<Enter>", lambda _: self._lb.config(bg=ACCH))
        self._lb.bind("<Leave>", lambda _: self._lb.config(bg=GRNH if self._user else ACC))

    def _build_grid(self):
        outer = tk.Frame(self, bg=BG); outer.pack(fill="both", expand=True, padx=32, pady=24)
        for c in range(3): outer.columnconfigure(c, weight=1, uniform="c")
        for r in range(2): outer.rowconfigure(r, weight=1, uniform="r")
        for mid,title,sub,icon,badge,row,col in self._MODS:
            card = ModCard(outer, title=title or "─", subtitle=sub, icon=icon,
                           badge=badge, locked=True,
                           on_click=self._mkcb(mid))
            card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
            self._cards[mid] = card

    def _build_ftr(self):
        ftr = tk.Frame(self, bg=BG2, height=38); ftr.pack(fill="x", side="bottom"); ftr.pack_propagate(False)
        tk.Label(ftr, text=VER, font=("Consolas",10,"bold"), bg=BG2, fg=TX3).pack(side="right", padx=28)
        tk.Label(ftr, text="© 2025  STR Engineering", font=("Malgun Gothic",8), bg=BG2, fg=TX3).pack(side="left",padx=24)
        self._ftr_lic = tk.StringVar(value="")
        tk.Label(ftr, textvariable=self._ftr_lic, font=("Malgun Gothic",8), bg=BG2, fg=TX2).pack(side="left",padx=8)

    def _toggle(self):
        if self._user:
            if messagebox.askyesno("로그아웃", f"{self._user} 님\n로그아웃 하시겠습니까?", parent=self):
                self._logout()
        else:
            dlg = LoginDlg(self); self.wait_window(dlg)
            if dlg.result: self._login(dlg.result)

    def _login(self, info):
        if isinstance(info, str): info = {"id": info, "name": info}
        uid = info["id"]; self._user = uid; self._uinfo = info
        nm = info.get("name") or uid
        self._sv.set(f"👤  {nm} 님" + (f" · {info['company']}" if info.get("company") else ""))
        self._lb.config(text="  로그아웃  ", bg=GRNH)
        self._lb.bind("<Leave>", lambda _: self._lb.config(bg=GRNH))
        # 라이선스는 로그인 후에 확인·표시
        self._licb.pack(side="left", padx=(0,14), before=self._svl)
        self._lic = LC.status() if LC is not None else {}
        self._apply_license()
        st = self._lic or {}
        if st.get("ok"):
            msg = f"환영합니다, {nm} 님!\n\n라이선스: {st.get('message','')}"
            if LC.should_warn(st):
                msg += ("\n\n⚠ " + (f"체험판이 {st['days_left']}일 남았습니다." if st["state"] == "trial"
                                      else f"라이선스 만료까지 {st['days_left']}일 남았습니다.")
                        + "\n상단 라이선스 버튼에서 키를 등록·연장할 수 있습니다.")
            self.after(150, lambda: messagebox.showinfo("로그인 성공", msg, parent=self))
        else:
            self.after(150, lambda: (messagebox.showwarning("라이선스 필요",
                f"환영합니다, {nm} 님!\n\n{st.get('message','라이선스가 필요합니다.')}\n라이선스 키를 등록하세요.", parent=self),
                self._license_dialog()))

    # ── 라이선스 (로그인 후에만 표시) ───────────────────────
    def _apply_license(self):
        st = self._lic or {}
        if not self._user:
            self._ftr_lic.set("")
        elif LC is not None and st:
            ok = st.get("ok")
            self._licb.config(text=LC.short_text(st),
                              bg=(GRN if st.get("state") == "licensed" else ORG) if ok else RED, fg=WHI)
            self._ftr_lic.set(("라이선스: " + st.get("message","").replace("\n"," ")) if ok
                              else "라이선스 없음 — 상단 '라이선스'에서 등록")
        for mid, c in self._cards.items():
            if not self._user:
                c.lock(); continue
            if LC is not None and LC.allows(st, mid): c.unlock()
            else: c.lock("라이선스 필요" if not st.get("ok") else "라이선스 미포함")

    def _license_dialog(self):
        if LC is None: return
        dlg = LicenseDialog(self, self._lic)
        self.wait_window(dlg)
        self._lic = LC.status(); self._apply_license()

    def _module_ok(self, mid):
        self._lic = LC.status() if LC is not None else None       # 사용 중 만료도 확인
        self._apply_license()
        if LC is not None and LC.allows(self._lic, mid): return True
        self._license_dialog()
        return LC is not None and LC.allows(self._lic or {}, mid)

    def _logout(self):
        self._user = ""; self._lic = None
        self._licb.pack_forget()
        self._sv.set("로그인 후 이용하세요")
        self._lb.config(text="  로그인  ", bg=ACC)
        self._lb.bind("<Leave>", lambda _: self._lb.config(bg=ACC))
        self._apply_license()

    def _mkcb(self, mid):
        def _h():
            if not self._user: return
            if not self._module_ok(mid): return
            if   mid == "cad_analysis":  self._open_cad()
            elif mid == "basic_design":  messagebox.showinfo("준비 중","Basic Design\n모듈 준비 중입니다.", parent=self)
            elif mid == "2d_design":     self._open_2d()
            elif mid == "3d_design":     self._open_3d()
            elif mid == "auto_table":    self._open_auto_table()
            elif mid == "report_design": self._open_report()
            else:                        messagebox.showinfo("준비 중","해당 모듈 준비 중입니다.", parent=self)
        return _h

    def _open_cad(self):
        """CAD Analysis (strcad_cad_analysis/cad_analysis) 실행.
        필요한 패키지가 없으면 이유를 보여 주고 설치를 제안한다 (구버전으로 몰래 넘어가지 않음)."""
        pkg_dir = None
        for d in (BASE_DIR / "strcad_cad_analysis", WORK_DIR / "strcad_cad_analysis", BASE_DIR, WORK_DIR):
            if (d / "cad_analysis" / "app.py").exists():
                pkg_dir = d; break
        if pkg_dir is not None:
            if str(pkg_dir) in sys.path: sys.path.remove(str(pkg_dir))
            sys.path.insert(0, str(pkg_dir))              # 항상 이 폴더의 최신 cad_analysis 를 먼저 사용
        for attempt in (1, 2):
            try:
                import cad_analysis
                from cad_analysis.app import open_window
                break
            except ImportError as e:
                missing = getattr(e, "name", None) or str(e)
                if attempt == 1 and not getattr(sys, "frozen", False) and missing and "cad_analysis" not in missing:
                    if messagebox.askyesno("CAD Analysis — 패키지 필요",
                            f"CAD Analysis 실행에 필요한 파이썬 패키지가 없습니다: {missing}\n\n"
                            f"지금 설치할까요? (pip install -r requirements.txt)\n\n파이썬: {sys.executable}", parent=self):
                        if self._pip_install():
                            for k in [k for k in sys.modules if k == "cad_analysis" or k.startswith("cad_analysis.")]:
                                sys.modules.pop(k, None)
                            continue
                if messagebox.askyesno("CAD Analysis 실행 오류",
                        f"CAD Analysis를 불러오지 못했습니다.\n({e})\n\n"
                        f"폴더: {pkg_dir}\n파이썬: {sys.executable}\n\n"
                        "터미널에서  pip install -r requirements.txt  실행 후 다시 시도하세요.\n\n"
                        "구버전 DXF 분석기로 대신 열까요?", parent=self):
                    return self._open_cad_legacy()
                return
        try:
            from cad_analysis import __version__ as _cv
            app = open_window(self)                     # Toplevel로 열림
            win = app.root
            nm = (getattr(self, "_uinfo", None) or {}).get("name") or self._user
            win.title(f"StrCAD - CAD Analysis v{_cv}  ─  {nm}")
            win.minsize(1000, 640)
            win.lift(); win.focus_force()
        except Exception as e:
            import traceback
            messagebox.showerror("CAD Analysis 오류", f"{e}\n\n{traceback.format_exc()}", parent=self)

    def _pip_install(self):
        req = BASE_DIR / "requirements.txt"
        cmd = [sys.executable, "-m", "pip", "install"] + (["-r", str(req)] if req.exists()
                                                         else ["ezdxf", "pillow", "tkinterdnd2", "openpyxl", "numpy"])
        self.config(cursor="watch"); self.update()
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except Exception as e:
            messagebox.showerror("설치 실패", str(e), parent=self); return False
        finally:
            self.config(cursor="")
        if r.returncode != 0:
            messagebox.showerror("설치 실패", (r.stderr or r.stdout)[-1500:], parent=self); return False
        import importlib; importlib.invalidate_caches()
        return True

    def _open_cad_legacy(self):
        win = tk.Toplevel(self)
        win.title(f"CAD Analysis  ─  {self._user}")
        win.geometry("920x700"); win.minsize(740,560)
        win.configure(bg="#0d1117"); win.lift(); win.focus_force()
        CadPanel(win, username=self._user)

    def _open_report(self):
        """Report Design (report_design/report_assistant.py) — 한글 보고서 작성 도우미"""
        for d in (BASE_DIR / "report_design", WORK_DIR / "report_design"):
            if (d / "report_assistant.py").exists():
                if str(d) in sys.path: sys.path.remove(str(d))
                sys.path.insert(0, str(d)); break
        for attempt in (1, 2):
            try:
                from report_assistant import open_report_design
                break
            except ImportError as e:
                missing = getattr(e, "name", None) or str(e)
                if attempt == 1 and not getattr(sys, "frozen", False) and missing and "report_" not in missing:
                    if messagebox.askyesno("Report Design — 패키지 필요",
                            f"Report Design 실행에 필요한 파이썬 패키지가 없습니다: {missing}\n\n"
                            f"지금 설치할까요? (pip install -r requirements.txt)", parent=self):
                        if self._pip_install():
                            continue
                messagebox.showerror("Report Design 실행 오류",
                    f"Report Design을 불러오지 못했습니다.\n({e})\n\nreport_design 폴더와 "
                    "pip install python-docx olefile pywin32 를 확인하세요.", parent=self)
                return
        try:
            nm = (getattr(self, "_uinfo", None) or {}).get("name") or self._user
            app = open_report_design(self, username=nm)
            app.root.title(f"StrCAD - Report Design  ─  {nm}")
        except Exception as e:
            import traceback
            messagebox.showerror("Report Design 오류", f"{e}\n\n{traceback.format_exc()}", parent=self)

    def _open_3d(self):
        try:
            import sys, os
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "3ddesign"))
            from design_3d import open_3d_design
            open_3d_design(self, username=self._user)
        except ImportError as e:
            messagebox.showinfo("준비 중", f"3D Design 모듈 준비 중입니다.\n({e})", parent=self)

    def _open_auto_table(self):
        try:
            import sys, os
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "autotable"))
            from auto_table import open_auto_table
            open_auto_table(parent=self, username=self._user)
        except ImportError as e:
            messagebox.showerror("모듈 오류",
                f"autotable 폴더를 찾을 수 없습니다.\n{e}", parent=self)

    def _center(self):
        self.update_idletasks()
        sw=self.winfo_screenwidth(); sh=self.winfo_screenheight()
        w=self.winfo_width(); h=self.winfo_height()
        self.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")
    
    def _open_2d(self):
        try:
            from design_2d import open_2d_design
            open_2d_design(self, username=self._user)
        except ImportError as e:
            from tkinter import messagebox
            messagebox.showerror(
                "모듈 오류",
                f"design_2d 폴더를 찾을 수 없습니다.\\n{e}",
                parent=self)


# ── CAD Analysis 패널 ─────────────────────────────────────
class CadPanel:
    C = dict(BG="#0d1117",BG2="#161b22",BG3="#21262d",ACC="#238636",AC2="#2ea043",
             BLU="#1f6feb",RED="#da3633",ORG="#e3b341",TEA="#39d353",
             TXT="#c9d1d9",T2="#8b949e",BOR="#30363d",WHI="#f0f6fc")

    def __init__(self, win, username=""):
        self.win=win; self.user=username
        self.dxf=tk.StringVar(); self.opt_x=tk.BooleanVar(value=True)
        self.opt_p=tk.BooleanVar(value=True); self.opt_h=tk.BooleanVar(value=True)
        self.stat=tk.StringVar(value="대기 중..."); self.run=[False]
        self.outs=[]; self._pv=[None]; self._rb=[None]; self._lt=[None]; self._fl=[None]
        self._build()

    def _build(self):
        C=self.C; win=self.win
        hdr=tk.Frame(win,bg=C["BG2"],height=56); hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr,text="🔍  CAD Analysis",font=("Malgun Gothic",14,"bold"),bg=C["BG2"],fg=C["WHI"]).pack(side="left",padx=20)
        if self.user: tk.Label(hdr,text=f"  ({self.user})",font=("Malgun Gothic",9),bg=C["BG2"],fg=C["T2"]).pack(side="left")
        tk.Button(hdr,text="📂 프로젝트 관리",command=self._pm,
                  font=("Malgun Gothic",9),bg=C["BG3"],fg=C["TXT"],
                  relief="flat",padx=10,cursor="hand2").pack(side="right",padx=12,pady=10)
        tk.Frame(win,bg=C["BOR"],height=1).pack(fill="x")
        body=tk.Frame(win,bg=C["BG"]); body.pack(fill="both",expand=True,padx=24,pady=20)
        left=tk.Frame(body,bg=C["BG"]); left.pack(side="left",fill="both",expand=True)
        right=tk.Frame(body,bg=C["BG2"],highlightbackground=C["BOR"],highlightthickness=1)
        right.pack(side="right",fill="both",padx=(16,0),ipadx=12,ipady=12)
        right.pack_propagate(False); right.configure(width=240)
        self._left(left); self._right(right)

    def _left(self,p):
        C=self.C
        def sec(t): tk.Label(p,text=t,font=("Malgun Gothic",10,"bold"),bg=C["BG"],fg=C["TXT"]).pack(anchor="w")
        def sep(): tk.Frame(p,bg=C["BOR"],height=1).pack(fill="x",pady=14)
        def mkb(par,t,cmd,bg=None,fg=None,fs=10,py=6):
            bg=bg or C["BG3"]; fg=fg or C["TXT"]
            b=tk.Button(par,text=t,command=cmd,font=("Malgun Gothic",fs,"bold"),
                        bg=bg,fg=fg,activebackground=C["AC2"],activeforeground=C["WHI"],
                        relief="flat",cursor="hand2",pady=py)
            b.bind("<Enter>",lambda _:b.config(bg=C["AC2"] if bg==C["ACC"] else C["BG3"]))
            b.bind("<Leave>",lambda _:b.config(bg=bg)); return b
        sec("① DXF 파일 선택")
        fr=tk.Frame(p,bg=C["BG"]); fr.pack(fill="x",pady=(6,0))
        tk.Entry(fr,textvariable=self.dxf,font=("Consolas",10),bg=C["BG3"],fg=C["TXT"],
                 insertbackground=C["WHI"],relief="flat",
                 highlightbackground=C["BOR"],highlightthickness=1,
                 state="readonly").pack(side="left",fill="x",expand=True,ipady=8,padx=(0,8))
        mkb(fr,"파일 선택",self._sel).pack(side="left")
        tk.Label(p,text="또는 파일을 여기에 드래그하세요",font=("Malgun Gothic",9),bg=C["BG"],fg=C["T2"]).pack(anchor="w",pady=(4,0))
        sep()
        sec("② 출력 옵션")
        of=tk.Frame(p,bg=C["BG"]); of.pack(fill="x",pady=(6,0))
        for t,v in [("📊  Excel 리포트",self.opt_x),("🖼  보 평면도(PNG)",self.opt_p),("🖥  인터랙티브 뷰어",self.opt_h)]:
            f2=tk.Frame(of,bg=C["BG"]); f2.pack(anchor="w",pady=2)
            tk.Checkbutton(f2,text=t,variable=v,font=("Malgun Gothic",10),
                           bg=C["BG"],fg=C["TXT"],activebackground=C["BG"],
                           selectcolor=C["BG3"],relief="flat").pack(side="left")
        sep()
        sec("③ 분석 실행")
        rb=mkb(p,"▶  분석 시작",self._run_a,bg=C["ACC"],fg=C["WHI"],fs=12,py=10)
        rb.pack(fill="x",pady=(8,0)); self._rb[0]=rb
        style=ttk.Style()
        try: style.configure("CA.Horizontal.TProgressbar",background=C["TEA"],troughcolor=C["BG3"],bordercolor=C["BG3"],lightcolor=C["TEA"],darkcolor=C["TEA"])
        except: pass
        self.prog=ttk.Progressbar(p,style="CA.Horizontal.TProgressbar",mode="determinate",maximum=100)
        self.prog.pack(fill="x",pady=(10,4))
        tk.Label(p,textvariable=self.stat,font=("Malgun Gothic",9),bg=C["BG"],fg=C["T2"],anchor="w").pack(fill="x")
        sep()
        sec("실행 로그")
        lf=tk.Frame(p,bg=C["BG3"],highlightbackground=C["BOR"],highlightthickness=1)
        lf.pack(fill="both",expand=True,pady=(6,0))
        lt=tk.Text(lf,bg=C["BG3"],fg=C["TXT"],font=("Consolas",9),relief="flat",state="disabled",wrap="word",padx=8,pady=6)
        sc=tk.Scrollbar(lf,command=lt.yview,bg=C["BG3"],troughcolor=C["BG3"])
        lt.configure(yscrollcommand=sc.set); sc.pack(side="right",fill="y"); lt.pack(fill="both",expand=True)
        for tag,col,bold in [("ok",C["TEA"],False),("warn",C["ORG"],False),("err",C["RED"],False),("info",C["BLU"],False),("header",C["WHI"],True)]:
            lt.tag_config(tag,foreground=col,font=("Consolas",9,"bold" if bold else "normal"))
        self._lt[0]=lt

    def _right(self,p):
        C=self.C
        tk.Label(p,text="생성된 파일",font=("Malgun Gothic",10,"bold"),bg=C["BG2"],fg=C["WHI"]).pack(anchor="w",padx=12,pady=(12,6))
        tk.Frame(p,bg=C["BOR"],height=1).pack(fill="x",padx=12)
        fl=tk.Frame(p,bg=C["BG2"]); fl.pack(fill="both",expand=True,padx=12,pady=8)
        tk.Label(fl,text="분석 완료 후\n파일이 표시됩니다",font=("Malgun Gothic",9),bg=C["BG2"],fg=C["T2"],justify="center").pack(pady=24)
        self._fl[0]=fl
        tk.Frame(p,bg=C["BOR"],height=1).pack(fill="x",padx=12)
        tk.Button(p,text="📁  출력 폴더 열기",command=self._odir,
                  font=("Malgun Gothic",9,"bold"),bg=C["BG3"],fg=C["TXT"],
                  relief="flat",cursor="hand2",pady=6).pack(fill="x",padx=12,pady=10)

    def _sel(self):
        p=filedialog.askopenfilename(title="DXF 선택",parent=self.win,
                                     filetypes=[("DXF","*.dxf"),("모든","*.*")])
        if p: self.dxf.set(p); self._log(f"파일: {Path(p).name}","info")

    def _run_a(self):
        if self.run[0]: return
        p=self.dxf.get()
        if not p or not os.path.exists(p):
            messagebox.showwarning("파일 없음","DXF 파일을 먼저 선택하세요.",parent=self.win); return
        self.run[0]=True; rb=self._rb[0]
        if rb: rb.config(text="⏳  분석 중...",state="disabled",bg=self.C["BG3"])
        self.prog["value"]=0; self.outs.clear()
        fl=self._fl[0]
        if fl:
            for w in fl.winfo_children(): w.destroy()
            tk.Label(fl,text="분석 완료 후\n파일이 표시됩니다",font=("Malgun Gothic",9),
                     bg=self.C["BG2"],fg=self.C["T2"],justify="center").pack(pady=24)
        lt=self._lt[0]
        if lt: lt.config(state="normal"); lt and lt.delete("1.0","end"); lt and lt.config(state="disabled")
        threading.Thread(target=self._worker,args=(p,),daemon=True).start()

    def _worker(self,dxf):
        try:
            self._log("="*50,"header"); self._log("STRCAD 구조도면 분석 시작","header"); self._log("="*50,"header")
            out=Path(dxf).parent/"STRCAD_출력"; out.mkdir(exist_ok=True)
            from modules import DXFReader,ColumnAnalyzer,BeamAnalyzer,DiscontinuityChecker,ExcelExporter
            from modules.beam_visualizer import BeamVisualizer
            self._st("DXF 로드...",5); reader=DXFReader(dxf)
            if not reader.load(): self._log("✗ DXF 로드 실패","err"); return
            self._log("✓ DXF 로드 완료","ok")
            self._st("기둥 분석...",15); cols=reader.get_columns(); cp=[]; ca=None
            if cols:
                ca=ColumnAnalyzer(cols); cp=ca.extract_positions()
                xg=ca.find_grid_spacing('x'); yg=ca.find_grid_spacing('y')
                self._log(f"✓ 기둥 {len(cp)}개  X:{len(xg['gridlines'])} Y:{len(yg['gridlines'])} 그리드","ok")
            self._st("형상 파싱...",25)
            cs=reader.get_column_shapes(); ws=reader.get_wall_shapes(); cn=reader.get_column_nodes()
            self._log(f"✓ 기둥형상 {len(cs)}개/Node {len(cn)}개  벽체 {len(ws)}개","ok")
            self._st("보 분석...",40); beams=reader.get_beams(); ba=None
            if beams:
                ba=BeamAnalyzer(beams,cp,dxf_reader=reader); ba.analyze_spans(); sm=ba.get_summary()
                self._log(f"✓ 보 스팬 {sm['total_spans']}개  X:{sm['x_direction_spans']} Y:{sm['y_direction_spans']}","ok")
            if ba and cn:
                self._st("스냅...",48); ba.beam_data=reader.snap_beams_to_columns(ba.beam_data)
                self._log("✓ 기둥 스냅 완료","ok")
            self._st("불연속 검사...",55); disc=None; am=(beams or[])+reader.get_walls()
            if am:
                disc=DiscontinuityChecker(am); disc.find_discontinuities()
                self._log(f"✓ 불연속 {len(disc.discontinuities)}개","ok")
            if self.opt_x.get():
                self._st("Excel 생성...",65)
                import config as _c; _c.OUTPUT['folder']=str(out); ex=ExcelExporter()
                if ba and ba.beam_data: self._add(ex.export_beam_spans(ba.beam_data),"📊 보 스팬")
                if disc and disc.discontinuities: self._add(ex.export_discontinuities(disc.discontinuities),"📊 불연속")
                if ca: self._add(ex.export_column_spacing({'x_spacings':xg['spacings'],'y_spacings':yg['spacings']}),"📊 기둥 간격")
                self._log("✓ Excel 완료","ok")
            if self.opt_p.get() and ba and ba.beam_data:
                self._st("PNG 생성...",78)
                viz=BeamVisualizer(beam_data=ba.beam_data,column_positions=cp,title="구조 평면도")
                self._add(viz.save_image(str(out/"beam_plan.png")),"🖼 보 평면도"); self._log("✓ PNG 완료","ok")
            if self.opt_h.get() and ba and ba.beam_data:
                self._st("뷰어 준비...",90)
                self._pv[0]={'beam_data':ba.beam_data,'column_positions':cp,'column_shapes':cs,
                             'wall_shapes':ws,'column_nodes':cn,'project_name':Path(dxf).stem,
                             'dxf_path':dxf,'db_path':str(out/"strcad_data.db")}
                self.win.after(100,self._viewer); self._log(f"✓ 뷰어 준비 (기둥 {len(cn)}개)","ok")
            self._st("✅  완료!",100); self._log("="*50,"header"); self._log(f"✅ 완료! → {out}","ok"); self._log("="*50,"header")
        except Exception as e:
            import traceback; self._log(f"✗ {e}","err"); self._log(traceback.format_exc(),"err"); self._st("오류",0)
        finally:
            self.run[0]=False; rb=self._rb[0]
            if rb: self.win.after(0,lambda:rb.config(text="▶  분석 시작",state="normal",bg=self.C["ACC"]))

    def _viewer(self):
        v=self._pv[0]
        if not v: return
        self._pv[0]=None
        try:
            from modules.beam_editor import open_viewer
            open_viewer(self.win,beam_data=v['beam_data'],column_positions=v['column_positions'],
                        column_shapes=v.get('column_shapes',[]),wall_shapes=v.get('wall_shapes',[]),
                        column_nodes=v.get('column_nodes',[]),project_name=v['project_name'],
                        dxf_path=v['dxf_path'],db_path=v['db_path'])
        except Exception as e:
            import traceback; messagebox.showerror("뷰어 오류",f"{e}\n\n{traceback.format_exc()}",parent=self.win)

    def _pm(self):
        try:
            from modules.beam_editor import open_project_manager
            open_project_manager(self.win,str(WORK_DIR/"strcad_data.db"))
        except Exception as e: messagebox.showerror("오류",str(e),parent=self.win)

    def _odir(self):
        p=self.dxf.get()
        if p:
            out=Path(p).parent/"STRCAD_출력"; out.mkdir(exist_ok=True)
            if os.name=="nt": os.startfile(str(out))
            else: subprocess.Popen(["open",str(out)])
        else: messagebox.showinfo("안내","DXF 파일을 먼저 선택하세요.",parent=self.win)

    def _log(self,msg,tag=""):
        lt=self._lt[0]
        if not lt: return
        def d(): lt.config(state="normal"); lt.insert("end",msg+"\n",tag); lt.see("end"); lt.config(state="disabled")
        self.win.after(0,d)

    def _st(self,msg,pct):
        self.win.after(0,lambda:self.stat.set(msg))
        self.win.after(0,lambda:self.prog.config(value=pct))

    def _add(self,path,label):
        if not path: return
        self.outs.append((label,path))
        def d():
            fl=self._fl[0]
            if not fl: return
            for w in fl.winfo_children(): w.destroy()
            for lbl,p in self.outs:
                row=tk.Frame(fl,bg=self.C["BG2"]); row.pack(fill="x",pady=2)
                tk.Label(row,text=lbl,font=("Malgun Gothic",9),bg=self.C["BG2"],
                         fg=self.C["TXT"],anchor="w",wraplength=160).pack(side="left",fill="x",expand=True)
                tk.Button(row,text="열기",font=("Malgun Gothic",8),bg=self.C["BG3"],fg=self.C["TEA"],
                          relief="flat",cursor="hand2",command=lambda fp=p:self._of(fp)).pack(side="right")
        self.win.after(0,d)

    def _of(self,path):
        try:
            if path.endswith(".html"): webbrowser.open(f"file:///{path}")
            elif os.name=="nt": os.startfile(path)
            else: subprocess.Popen(["open",path])
        except Exception as e: messagebox.showerror("오류",str(e),parent=self.win)


def _selftest(out):
    """설치판 점검: python launcher.py --selftest result.txt"""
    lines = []
    try:
        import importlib
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_design"))
        for m in ("accounts", "cad_analysis.app", "cad_analysis.licensing", "cad_analysis.licensing_ui", "design_2d",
                  "olefile", "docx", "hwp_reader", "docx_doc", "docx_table", "hwp_to_word", "report_core", "report_assistant"):
            try: importlib.import_module(m); lines.append("OK " + m)
            except Exception as e: lines.append(f"FAIL {m} {e!r}")
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "autotable"))
        try: importlib.import_module("auto_table"); lines.append("OK auto_table")
        except Exception as e: lines.append(f"FAIL auto_table {e!r}")
        from cad_analysis import theme
        for rel in (("cad_analysis", "assets", "icon.ico"), ("mobile", "index.html"), ("mobile", "sketch.js")):
            p = theme.resource(*rel); lines.append(f"{'OK' if os.path.exists(p) else 'MISSING'} {'/'.join(rel)}")
        lines.append("license " + LC.status().get("state", "?") if LC else "FAIL license")
        try:                                     # 도면 사진 인식 (OpenCV + 글자 인식 모델)
            import numpy as np, cv2
            from cad_analysis import photo_plan as PP
            from rapidocr_onnxruntime import RapidOCR
            img = np.full((120, 320, 3), 255, np.uint8)
            cv2.putText(img, "G12", (20, 85), cv2.FONT_HERSHEY_SIMPLEX, 2.4, (0, 0, 0), 5)
            got = [t[1] for t in (RapidOCR()(img)[0] or [])]
            lines.append(("OK" if any("G12" in g for g in got) else "FAIL") + f" photo-ocr {got}")
        except Exception as e:
            lines.append(f"FAIL photo-ocr {e!r}")
    except Exception as e:
        import traceback; lines.append("FAIL " + traceback.format_exc())
    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── 진입점 ────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        _selftest(sys.argv[2]); sys.exit(0)
    app = Launcher()
    app.mainloop()
