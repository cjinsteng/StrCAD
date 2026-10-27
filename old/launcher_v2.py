"""
STR Design & Check  —  런처 메인 화면
· 헤더: 타이틀 / 로그인 상태 / [로그인] 버튼
· 2×3 모듈 카드 그리드 (로그인 전 잠금)
· CAD Analysis → DXF 분석기 창 실행
· 하단 ver. 1.0.0
기본 계정: admin / admin1234   |   user1 / pass1234
"""

import sys, os, hashlib, threading, subprocess, webbrowser
from pathlib import Path

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS);  WORK_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent; WORK_DIR = Path(__file__).parent

sys.path.insert(0, str(BASE_DIR))

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

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

_USERS = {
    "1234": hashlib.sha256(b"1234").hexdigest(),
    "user1": hashlib.sha256(b"pass1234").hexdigest(),
}
def _auth(u, p): return _USERS.get(u.strip()) == hashlib.sha256(p.encode()).hexdigest()
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
        self.geometry(f"360x330+{px-180}+{py-165}")
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
        self._err = tk.StringVar()
        tk.Label(frm, textvariable=self._err, font=("Malgun Gothic",8), bg=BG2, fg=RED).pack(anchor="w", pady=(6,0))
        br = tk.Frame(frm, bg=BG2); br.pack(fill="x", pady=(14,0))
        def mkb(p, t, cmd, bg_, fg_):
            b = tk.Button(p, text=t, command=cmd, font=("Malgun Gothic",10,"bold"),
                          bg=bg_, fg=fg_, relief="flat", cursor="hand2", pady=8)
            b.bind("<Enter>", lambda _: b.config(bg=_dk(bg_)))
            b.bind("<Leave>", lambda _: b.config(bg=bg_)); return b
        mkb(br,"취소",self.destroy,BG3,TX2).pack(side="left", fill="x", expand=True, padx=(0,6))
        mkb(br,"로그인",self._try,ACC,WHI).pack(side="right", fill="x", expand=True)

    def _try(self):
        u = self._id.get().strip(); p = self._pw.get()
        if not u or not p: self._err.set("아이디와 비밀번호를 입력하세요."); return
        if _auth(u, p): self.result = u; self.destroy()
        else:
            self._err.set("아이디 또는 비밀번호가 틀렸습니다.")
            self._pw.delete(0,"end"); self._pw.focus_set()


# ── 모듈 카드 ─────────────────────────────────────────────
class ModCard(tk.Frame):
    def __init__(self, parent, title, subtitle, icon, badge=None, locked=True, on_click=None):
        super().__init__(parent)
        self._t=title; self._s=subtitle; self._i=icon
        self._badge=badge; self._locked=locked; self._cb=on_click
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
        elif self._badge:
            tk.Label(top, text=f"  {self._badge}  ", font=("Malgun Gothic",7,"bold"),
                     bg=BLU, fg=WHI).pack(side="right", anchor="n")
        tk.Label(inn, text=self._t, font=("Malgun Gothic",12,"bold"),
                 bg=bg, fg=TXT if not lk else DIS, anchor="w").pack(fill="x", pady=(10,3))
        if self._s:
            tk.Label(inn, text=self._s, font=("Malgun Gothic",8),
                     bg=bg, fg=TX2 if not lk else DIS,
                     anchor="w", wraplength=180).pack(fill="x")
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
    def unlock(self): self._locked=False; self._draw()
    def lock(self):   self._locked=True;  self._draw()


# ── 메인 런처 ─────────────────────────────────────────────
class Launcher(tk.Tk):
    _MODS = [
        ("basic_design","Basic Design", "구조 기본 설계",     "📐",None,  0,0),
        ("2d_design",   "2D Design",    "2D 도면 작업",       "✏️","NEW", 0,1),
        ("3d_design",   "3D Design",    "3D 구조 모델링",     "🧱","NEW", 0,2),
        ("cad_analysis","CAD Analysis", "DXF 구조도면 분석",  "🔍",None,  1,0),
        ("auto_table",  "Auto Table",   "보·기둥·슬래브·벽\n배근표 자동 작성", "📊","NEW", 1,1),
        ("detail_design","Detail Design","상세 구조 설계",    "📋",None,  1,2),
    ]
    def __init__(self):
        super().__init__()
        self.title("STR Design & Check")
        self.geometry("920x590"); self.minsize(800,520)
        self.configure(bg=BG); self.resizable(True,True)
        self._user = ""; self._cards = {}
        self._build(); self._center()

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
        self._sv = tk.StringVar(value="로그인 후 이용하세요")
        tk.Label(rf, textvariable=self._sv, font=("Malgun Gothic",9),
                 bg=BG2, fg=TX2).pack(side="left", padx=(0,18))
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

    def _toggle(self):
        if self._user:
            if messagebox.askyesno("로그아웃", f"{self._user} 님\n로그아웃 하시겠습니까?", parent=self):
                self._logout()
        else:
            dlg = LoginDlg(self); self.wait_window(dlg)
            if dlg.result: self._login(dlg.result)

    def _login(self, uid):
        self._user = uid
        self._sv.set(f"👤  {uid} 님 환영합니다")
        self._lb.config(text="  로그아웃  ", bg=GRNH)
        self._lb.bind("<Leave>", lambda _: self._lb.config(bg=GRNH))
        for c in self._cards.values(): c.unlock()
        self.after(150, lambda: messagebox.showinfo("로그인 성공",
            f"환영합니다, {uid} 님!\n모든 모듈이 활성화되었습니다.", parent=self))

    def _logout(self):
        self._user = ""
        self._sv.set("로그인 후 이용하세요")
        self._lb.config(text="  로그인  ", bg=ACC)
        self._lb.bind("<Leave>", lambda _: self._lb.config(bg=ACC))
        for c in self._cards.values(): c.lock()

    def _mkcb(self, mid):
        def _h():
            if not self._user: return
            if   mid == "cad_analysis":  self._open_cad()
            elif mid == "basic_design":  messagebox.showinfo("준비 중","Basic Design\n모듈 준비 중입니다.", parent=self)
            elif mid == "2d_design":     self._open_2d()
            elif mid == "3d_design":     self._open_3d()
            elif mid == "auto_table":    self._open_auto_table()
            elif mid == "detail_design": messagebox.showinfo("준비 중","Detail Design\n모듈 준비 중입니다.", parent=self)
            else:                        messagebox.showinfo("준비 중","해당 모듈 준비 중입니다.", parent=self)
        return _h

    def _open_cad(self):
        win = tk.Toplevel(self)
        win.title(f"CAD Analysis  ─  {self._user}")
        win.geometry("920x700"); win.minsize(740,560)
        win.configure(bg="#0d1117"); win.lift(); win.focus_force()
        CadPanel(win, username=self._user)

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


# ── 진입점 ────────────────────────────────────────────────
if __name__ == "__main__":
    app = Launcher()
    app.mainloop()
