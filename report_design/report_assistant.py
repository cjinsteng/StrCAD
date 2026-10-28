# -*- coding: utf-8 -*-
"""
보고서 작성 도우미 (진단·검토 보고서용)

  python report_assistant.py

기능
  1) 동일 내용 동기화 : 한 곳을 수정하면 다른 장·절의 같은/비슷한 내용을 찾아 함께 수정할지 제안
  2) 절 단위 AI 검토  : 트리에서 5.4.1 같은 절을 선택 → AI 오타·표현·내용 검토 → 제안 적용
  3) 번호 검사        : 장/절 번호, (1)(2)·①② 항목, <그림/표 N.M> 번호 오류 찾기 + 자동 수정 제안
  4) 공통 항목        : 과업명·위치·연면적·준공연도·fck 등 사용처 확인, 값 일괄 변경
  5) 한글 파일에 반영  : 백업 후 한글 자동화로 원본(.hwp/.hwpx)에 찾아 바꾸기, 결과 검증
"""
import bisect
import difflib
import json
import os
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox, simpledialog

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report_core as rc  # noqa: E402
from hwp_reader import heading_of  # noqa: E402

APP_VERSION = "1.0.0"


def _load_theme():
    """StrCAD 공용 디자인(cad_analysis/theme.py: 남색 + 주황 포인트). 없으면 같은 색의 간이 테마"""
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.path.join(here, "..", "strcad_cad_analysis"), getattr(sys, "_MEIPASS", "")):
        if d and os.path.isdir(os.path.join(d, "cad_analysis")) and d not in sys.path:
            sys.path.append(d)
    try:
        from cad_analysis import theme as th
        return th
    except Exception:
        return _MiniTheme


class _MiniTheme:
    """단독 실행(StrCAD 폴더 밖)용 — cad_analysis/theme.py 와 같은 색"""
    NAVY, NAVY_2, NAVY_3, NAVY_L = "#1E2A44", "#2B3B5C", "#3E5580", "#8C9BB8"
    ORANGE, ORANGE_D, ORANGE_L = "#F28C28", "#D9741A", "#FDEBD8"
    SURFACE, PANEL, LINE, INK, MUTED = "#F4F6FA", "#FFFFFF", "#D6DCE6", "#1F2937", "#6B7280"
    OK, NG, WARN = "#16A34A", "#DC2626", "#B45309"
    APP_NAME = "StrCAD"
    FAM = "Malgun Gothic" if sys.platform.startswith("win") else "Noto Sans CJK KR"
    _done = False

    @classmethod
    def image(cls, name):
        return None

    @classmethod
    def set_icon(cls, win):
        pass

    @classmethod
    def ensure(cls, w):
        if not cls._done:
            cls.apply(w.winfo_toplevel())

    @classmethod
    def apply(cls, root):
        cls._done = True
        c = cls
        st = ttk.Style(root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        f, fb = (c.FAM, 9), (c.FAM, 10, "bold")
        root.option_add("*Background", c.SURFACE)
        st.configure(".", background=c.SURFACE, foreground=c.INK, font=f, bordercolor=c.LINE,
                     lightcolor=c.PANEL, darkcolor=c.LINE, troughcolor="#E8ECF2", focuscolor=c.ORANGE)
        st.configure("TLabelframe", background=c.PANEL, bordercolor=c.LINE, relief="solid", borderwidth=1)
        st.configure("TLabelframe.Label", background=c.PANEL, foreground=c.NAVY, font=fb)
        st.configure("TNotebook", background=c.NAVY, borderwidth=0, tabmargins=(8, 6, 8, 0))
        st.configure("TNotebook.Tab", background=c.NAVY_2, foreground="#C9D3E4", padding=(14, 6), font=fb)
        st.map("TNotebook.Tab", background=[("selected", c.SURFACE), ("active", c.NAVY_3)],
               foreground=[("selected", c.NAVY), ("active", "#FFFFFF")])
        st.configure("TButton", background=c.PANEL, bordercolor=c.LINE, padding=(8, 4), relief="flat")
        st.map("TButton", background=[("pressed", "#E3E8F0"), ("active", "#EEF2F8")])
        st.configure("Accent.TButton", background=c.ORANGE, foreground="#FFFFFF", bordercolor=c.ORANGE_D, font=fb)
        st.map("Accent.TButton", background=[("pressed", c.ORANGE_D), ("active", "#F59C45")])
        st.configure("Ribbon.TButton", background=c.PANEL, bordercolor=c.PANEL, padding=(6, 3), justify="center")
        st.map("Ribbon.TButton", background=[("pressed", c.ORANGE_L), ("active", "#EEF2F8")])
        st.configure("RibbonAccent.TButton", background=c.ORANGE, foreground="#FFFFFF", bordercolor=c.ORANGE,
                     padding=(6, 3), font=fb, justify="center")
        st.map("RibbonAccent.TButton", background=[("pressed", c.ORANGE_D), ("active", "#F59C45")])
        st.configure("TCheckbutton", background=c.SURFACE)
        st.map("TCheckbutton", indicatorcolor=[("selected", c.ORANGE), ("!selected", c.PANEL)])
        st.configure("Treeview", background=c.PANEL, fieldbackground=c.PANEL, rowheight=24, bordercolor=c.LINE)
        st.map("Treeview", background=[("selected", c.ORANGE_L)], foreground=[("selected", c.INK)])
        st.configure("Treeview.Heading", background=c.NAVY, foreground="#FFFFFF", font=fb, relief="flat",
                     padding=(4, 4))
        st.map("Treeview.Heading", background=[("active", c.NAVY_2)])
        st.configure("TScrollbar", background="#D3DAE5", troughcolor=c.SURFACE, bordercolor=c.SURFACE,
                     arrowcolor=c.NAVY)
        st.configure("Status.TLabel", background=c.NAVY, foreground="#E5EAF3", padding=(10, 3))


TH = _load_theme()

APP_TITLE = "보고서 작성 도우미"
SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".report_assistant_settings.json")
MODELS = ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"]
# 내 PC(Ollama)용 추천 모델 — 한국어 성능 위주. 'ollama pull 이름' 으로 설치
OLLAMA_SUGGEST = ["exaone3.5:7.8b", "qwen2.5:14b", "gemma3:12b", "exaone3.5:32b", "qwen2.5:7b"]
KIND_KO = {"body": "본문", "cell": "표", "box": "글상자"}


def load_settings():
    s = {"api_key": "", "model": MODELS[0], "hwp_visible": False,
         "provider": "claude", "ollama_url": rc.DEFAULT_URL["ollama"], "ollama_model": OLLAMA_SUGGEST[0],
         "openai_url": rc.DEFAULT_URL["openai"], "openai_model": "", "openai_key": "", "num_ctx": 16384}
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            s.update(json.load(f))
    except Exception:
        pass
    if not s.get("api_key"):
        s["api_key"] = os.environ.get("ANTHROPIC_API_KEY", "")
    return s


def save_settings(s):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def short(s, n=40):
    s = (s or "").replace("\n", " ").replace("\t", " ")
    return s if len(s) <= n else s[:n - 1] + "…"


def loc_of(p):
    sec = p.section.label if p.section else "(위치 미상)"
    return f"{os.path.basename(p.doc.path)} › {sec}"


def pick_font():
    fams = set(tkfont.families())
    for f in ("맑은 고딕", "Malgun Gothic", "NanumGothic", "Noto Sans CJK KR", "Noto Sans KR", "UnDotum"):
        if f in fams:
            return f
    return "TkDefaultFont"


def render_diff(txt, old, new):
    """Text 위젯에 old→new 비교 표시 (삭제: 빨강 취소선, 추가: 초록)"""
    txt.config(state="normal")
    txt.delete("1.0", "end")
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            txt.insert("end", old[i1:i2])
        else:
            if i2 > i1:
                txt.insert("end", old[i1:i2], "del")
            if j2 > j1:
                txt.insert("end", new[j1:j2], "ins")
    txt.config(state="disabled")


def make_diff_text(parent, font, height=6):
    t = tk.Text(parent, height=height, wrap="word", font=(font, 10), relief="solid",
                padx=6, pady=4, bg=TH.PANEL, fg=TH.INK, highlightthickness=0, borderwidth=1)
    t.tag_configure("del", foreground=TH.NG, overstrike=1, background="#fde7e7")
    t.tag_configure("ins", foreground="#1b5e20", background="#dff5e1")
    t.config(state="disabled")
    return t


# ====================================================================== 동기화 대화상자

class PropagationDialog(tk.Toplevel):
    """다른 곳의 같은/비슷한 내용 수정 후보를 보여주고 선택하게 함"""

    def __init__(self, app, candidates, title="다른 곳도 함께 수정할까요?",
                 note="같은 문구나 비슷한 문단이 다른 곳에도 있습니다. 함께 수정할 항목을 선택하세요.",
                 src="동기화"):
        super().__init__(app.root)
        self.app = app
        self.cands = candidates
        self.src = src
        self.result = 0
        self.title(title)
        self.geometry("980x620")
        self.transient(app.root)
        f = app.font
        ttk.Label(self, text=note, font=(f, 10, "bold"), wraplength=900).pack(anchor="w", padx=10, pady=(10, 4))
        ttk.Label(self, text="체크 표시를 클릭해 선택/해제 · 아래에서 바뀔 내용을 미리 볼 수 있습니다.",
                  style="Hint.TLabel").pack(anchor="w", padx=10)
        bf = ttk.Frame(self)
        bf.pack(side="bottom", fill="x", padx=10, pady=8)
        ttk.Button(bf, text="모두 선택", command=lambda: self._all(True)).pack(side="left")
        ttk.Button(bf, text="모두 해제", command=lambda: self._all(False)).pack(side="left", padx=4)
        ttk.Button(bf, text="위치로 이동", command=self._goto).pack(side="left", padx=12)
        ttk.Button(bf, text="건너뛰기", command=self.destroy).pack(side="right")
        ttk.Button(bf, text="선택 항목 함께 수정", style="Accent.TButton", command=self._apply).pack(side="right", padx=6)
        self.diff = make_diff_text(self, f, 6)
        self.diff.pack(side="bottom", fill="x", padx=10)
        ttk.Label(self, text="미리보기 (빨강=삭제, 초록=추가)").pack(side="bottom", anchor="w", padx=10)
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=10, pady=6)
        cols = ("chk", "loc", "kind", "why")
        self.tv = ttk.Treeview(frm, columns=cols, show="headings", selectmode="browse", style="RD.Treeview")
        for c, w, t in (("chk", 46, "선택"), ("loc", 330, "위치"), ("kind", 50, "구분"), ("why", 480, "이유")):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=w, stretch=(c == "why"), anchor="center" if c in ("chk", "kind") else "w")
        sb = ttk.Scrollbar(frm, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        self.tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for i, c in enumerate(candidates):
            self.tv.insert("", "end", iid=str(i), values=self._vals(c))
        self.tv.bind("<Button-1>", self._click)
        self.tv.bind("<<TreeviewSelect>>", self._sel)
        if candidates:
            self.tv.selection_set("0")
        self.grab_set()
        self.wait_window(self)

    def _vals(self, c):
        return ("☑" if c.checked else "☐", loc_of(c.para), KIND_KO.get(c.para.kind, ""), c.reason)

    def _click(self, e):
        if self.tv.identify_column(e.x) == "#1":
            iid = self.tv.identify_row(e.y)
            if iid:
                c = self.cands[int(iid)]
                c.checked = not c.checked
                self.tv.item(iid, values=self._vals(c))

    def _sel(self, _=None):
        s = self.tv.selection()
        if s:
            c = self.cands[int(s[0])]
            render_diff(self.diff, c.old_text, c.new_text)

    def _all(self, v):
        for i, c in enumerate(self.cands):
            c.checked = v
            self.tv.item(str(i), values=self._vals(c))

    def _goto(self):
        s = self.tv.selection()
        if s:
            self.app.goto_para(self.cands[int(s[0])].para)

    def _apply(self):
        n = 0
        for c in self.cands:
            if c.checked:
                self.app.rep.set_edit(c.para, c.new_text, self.src)
                n += 1
        self.result = n
        self.destroy()


# ====================================================================== 문단 편집 대화상자

class EditDialog(tk.Toplevel):
    def __init__(self, app, para):
        super().__init__(app.root)
        self.app, self.p = app, para
        self.saved = None
        self.title("문단 수정 — " + loc_of(para))
        self.geometry("820x420")
        self.minsize(560, 300)
        self.transient(app.root)
        f = app.font
        ttk.Label(self, text=loc_of(para) + f"   [{KIND_KO.get(para.kind, '')}]",
                  font=(f, 10, "bold")).pack(anchor="w", padx=10, pady=(10, 2))
        if para.uid in app.rep.edits:
            ttk.Label(self, text="원문(파일): " + short(para.orig, 120), style="Hint.TLabel").pack(anchor="w", padx=10)
        # 버튼 줄을 먼저 아래에 붙여야 화면 배율(125%·150%)에서도 잘리지 않는다
        bf = ttk.Frame(self)
        bf.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        ttk.Label(bf, text="Ctrl+Enter: 저장  ·  저장 후 '파일에 반영·저장'(Ctrl+S)을 눌러야 파일에 들어갑니다",
                  style="Hint.TLabel").pack(side="left")
        ttk.Button(bf, text="취소", command=self.destroy).pack(side="right")
        ttk.Button(bf, text="저장", style="Accent.TButton", command=self._save).pack(side="right", padx=6)
        self.txt = tk.Text(self, wrap="word", font=(f, 11), undo=True, padx=6, pady=6, height=8)
        self.txt.pack(fill="both", expand=True, padx=10, pady=6)
        self.txt.insert("1.0", app.rep.text(para))
        self.txt.focus_set()
        if para.uid in app.rep.edits:
            ttk.Button(bf, text="원문으로 되돌리기", command=self._revert).pack(side="right", padx=6)
        self.bind("<Control-Return>", lambda e: (self._save(), "break"))
        self.grab_set()
        self.wait_window(self)

    def _save(self):
        new = self.txt.get("1.0", "end-1c")
        self.saved = new
        self.destroy()

    def _revert(self):
        self.saved = self.p.orig
        self.destroy()


# ====================================================================== 설정

def _tbl_ref(t):
    return getattr(t, "ref", None)


class FormDialog(tk.Toplevel):
    """간단한 입력 창. fields: [(키, 라벨, 종류, 기본값, 설명)] 종류: entry|text|int|float|check|combo:a/b"""

    def __init__(self, app, title, fields, note=""):
        super().__init__(app.root)
        self.title(title)
        self.transient(app.root)
        self.resizable(False, False)
        self.result = None
        frm = ttk.Frame(self, padding=14)
        frm.pack(fill="both")
        if note:
            ttk.Label(frm, text=note, style="Hint.TLabel", wraplength=460, justify="left").grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.vars, self.texts = {}, {}
        r = 1
        first = None
        for key, label, kind, default, hint in fields:
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="nw", padx=(0, 10), pady=4)
            if kind == "text":
                w = tk.Text(frm, width=50, height=4, wrap="word", font=(app.font, 10), relief="solid", bd=1)
                w.insert("1.0", default or "")
                self.texts[key] = w
            elif kind == "check":
                v = tk.BooleanVar(value=bool(default))
                w = ttk.Checkbutton(frm, text=hint or "", variable=v)
                self.vars[key] = v
                hint = None
            elif kind.startswith("combo:"):
                v = tk.StringVar(value=default)
                w = ttk.Combobox(frm, textvariable=v, values=kind[6:].split("/"), state="readonly", width=12)
                self.vars[key] = v
            else:
                v = tk.StringVar(value="" if default is None else str(default))
                w = ttk.Entry(frm, textvariable=v, width=12 if kind in ("int", "float") else 52)
                self.vars[key] = v
            w.grid(row=r, column=1, sticky="w", pady=4)
            first = first or w
            r += 1
            if hint:
                ttk.Label(frm, text=hint, style="Hint.TLabel", wraplength=400, justify="left").grid(
                    row=r, column=1, sticky="w")
                r += 1
        self.kinds = {f[0]: f[2] for f in fields}
        bf = ttk.Frame(frm)
        bf.grid(row=r, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(bf, text="취소", command=self.destroy).pack(side="right")
        ttk.Button(bf, text="추가", style="Accent.TButton", command=self._ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda e: self._ok() if not isinstance(e.widget, tk.Text) else None)
        if first is not None:
            first.focus_set()
        self.grab_set()
        self.wait_window(self)

    def _ok(self):
        out = {}
        try:
            for k, v in self.vars.items():
                val = v.get()
                kind = self.kinds[k]
                if kind == "int":
                    val = int(val)
                elif kind == "float":
                    val = float(val) if str(val).strip() else None
                out[k] = val
        except ValueError:
            messagebox.showwarning(APP_TITLE, "숫자 칸을 확인하세요.", parent=self)
            return
        for k, w in self.texts.items():
            out[k] = w.get("1.0", "end-1c").strip()
        self.result = out
        self.destroy()


class TableEditor(tk.Toplevel):
    """표 편집 — 칸 모양 그대로 입력 + Word [표 레이아웃]과 같은 도구
    칸 클릭=선택, Shift+클릭/끌기=여러 칸 선택, Tab 다음 칸, Enter 아래 칸"""

    def __init__(self, app, table, keep=None):
        super().__init__(app.root)
        self.app, self.t = app, table
        self.doc = next((d for d in app.rep.docs if table in d.tables), None)
        self.word = self.doc is not None and self.doc.fmt == "docx" and table.ref is not None
        self.title(f"표 편집 — [표 {table.tid + 1}]")
        self.transient(app.root)
        self.configure(bg=TH.SURFACE)
        self.anchor = self.cur = (0, 0)
        if keep:
            self.anchor, self.cur = keep.get("sel", ((0, 0), (0, 0)))
        self._build_ribbon()
        bf = ttk.Frame(self, padding=(10, 8))
        bf.pack(side="bottom", fill="x")
        ttk.Label(bf, text="칸 클릭=선택 · Shift+클릭/끌기=여러 칸 · Tab 다음 칸 · Enter 아래 칸 · 노란 칸=고친 칸",
                  style="Hint.TLabel").pack(side="left")
        ttk.Button(bf, text="닫기", command=self._close).pack(side="right")
        ttk.Button(bf, text="저장", style="Accent.TButton", command=self._save).pack(side="right", padx=6)
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(wrap, bg=TH.SURFACE, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        sbx = ttk.Scrollbar(wrap, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=sb.set, xscrollcommand=sbx.set)
        sbx.pack(side="bottom", fill="x")
        sb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)
        self.body = body = tk.Frame(canvas, bg="#9AA5B8", padx=1, pady=1)
        canvas.create_window((10, 6), window=body, anchor="nw")
        widths = rc.table_col_widths(table)
        total = sum(widths) or 1
        avail = 900
        px = [max(56, int(avail * w / total)) for w in widths]
        for k, w in enumerate(px):
            body.grid_columnconfigure(k, minsize=w)
        self.entries = {}       # (r,c) origin -> (Entry, Para, 원래 글, StringVar, rs, cs)
        for (r, c), cell in sorted(table.cells.items()):
            ps = cell["paras"]
            p = next((q for q in ps if app.rep.text(q).strip()), ps[0] if ps else None)
            if p is None:
                continue
            cur = app.rep.text(p)
            var = tk.StringVar(value=cur)
            w = sum(px[c:c + cell["cs"]])
            e = tk.Entry(body, textvariable=var, font=(app.font, 10), relief="flat", justify="center",
                         bg="#FFF3B0" if p.uid in app.rep.edits else TH.PANEL, disabledbackground="#EEF1F6",
                         width=max(4, w // 8), highlightthickness=2, highlightbackground=TH.PANEL,
                         highlightcolor=TH.ORANGE)
            if "\t" in cur or "\n" in cur or p.pic or len([q for q in ps if app.rep.text(q).strip()]) > 1:
                e.config(state="disabled")              # 여러 줄·그림 칸은 본문에서 더블클릭해서 수정
            e.grid(row=r, column=c, rowspan=cell["rs"], columnspan=cell["cs"], sticky="nsew",
                   padx=(0, 1), pady=(0, 1), ipady=5)
            var.trace_add("write", lambda *a, e=e, p=p, v=var: e.config(
                bg="#FFF3B0" if v.get() != app.rep.text(p) else TH.PANEL))
            self.entries[(r, c)] = (e, p, cur, var, cell["rs"], cell["cs"])
            e.bind("<Return>", lambda ev, r=r, c=c: self._move(r, c, 1))
            e.bind("<Up>", lambda ev, r=r, c=c: self._move(r, c, -1))
            e.bind("<Down>", lambda ev, r=r, c=c: self._move(r, c, 1))
            e.bind("<Button-1>", lambda ev, r=r, c=c: self._click(r, c, ev))
            e.bind("<B1-Motion>", self._drag)
            e.bind("<FocusIn>", lambda ev, r=r, c=c: self._focus(r, c))
        body.update_idletasks()
        canvas.configure(scrollregion=(0, 0, body.winfo_reqwidth() + 20, body.winfo_reqheight() + 12))
        W = min(1400, max(980, body.winfo_reqwidth() + 60))
        H = min(820, body.winfo_reqheight() + 260)
        self.geometry(keep.get("geom") if keep and keep.get("geom") else f"{W}x{max(380, H)}")
        self._paint_sel()
        k = self.entries.get(self.cur) or next(iter(self.entries.values()), None)
        if k is not None and str(k[0].cget("state")) != "disabled":
            k[0].focus_set()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.grab_set()

    # ------------------------------------------------------------ 리본
    def _build_ribbon(self):
        rb = tk.Frame(self, bg=TH.PANEL, highlightthickness=1, highlightbackground=TH.LINE)
        rb.pack(fill="x", padx=6, pady=(6, 0))
        tk.Label(rb, text="표 레이아웃", bg=TH.NAVY, fg="white", font=(self.app.font, 9, "bold"),
                 padx=8).pack(side="left", fill="y")
        st = "normal" if self.word else "disabled"

        def grp(title):
            g = ttk.LabelFrame(rb, text=title, padding=(4, 0))
            g.pack(side="left", fill="y", padx=3, pady=2)
            return g

        def btn(g, text, cmd, w=7):
            b = ttk.Button(g, text=text, command=cmd, width=w, style="Ribbon.TButton", state=st)
            b.pack(side="left", padx=1, pady=1, fill="y")
            return b
        g = grp("행 및 열")
        mb = ttk.Menubutton(g, text="✖\n삭제", width=6, style="Ribbon.TButton", state=st)
        m = tk.Menu(mb, tearoff=0, font=(self.app.font, 10))
        m.add_command(label="셀 내용 지우기", command=self.clear_cells)
        m.add_command(label="행 삭제", command=lambda: self.op("delete_rows"))
        m.add_command(label="열 삭제", command=lambda: self.op("delete_cols"))
        m.add_command(label="표 삭제", command=self.delete_table)
        mb["menu"] = m
        mb.pack(side="left", padx=1, pady=1, fill="y")
        btn(g, "▲\n위에 행\n삽입", lambda: self.op("row_above"))
        btn(g, "▼\n아래에 행\n삽입", lambda: self.op("row_below"))
        btn(g, "◀\n왼쪽에 열\n삽입", lambda: self.op("col_left"))
        btn(g, "▶\n오른쪽에\n열 삽입", lambda: self.op("col_right"))
        g = grp("병합")
        btn(g, "⊞\n셀 병합", lambda: self.op("merge"), 6)
        btn(g, "⊟\n셀 분할", self.split_dialog, 6)
        g = grp("셀 크기")
        mb = ttk.Menubutton(g, text="⇔\n자동\n맞춤", width=6, style="Ribbon.TButton", state=st)
        m = tk.Menu(mb, tearoff=0, font=(self.app.font, 10))
        m.add_command(label="내용에 자동 맞춤", command=lambda: self.op("fit_content"))
        m.add_command(label="창(본문 폭)에 자동 맞춤", command=lambda: self.op("fit_window"))
        m.add_command(label="열 너비 고정", command=lambda: self.op("fit_fixed"))
        mb["menu"] = m
        mb.pack(side="left", padx=1, pady=1, fill="y")
        sz = ttk.Frame(g)
        sz.pack(side="left", padx=4)
        self.h_var, self.w_var = tk.StringVar(), tk.StringVar()
        ttk.Label(sz, text="높이(cm)").grid(row=0, column=0, sticky="w")
        e1 = ttk.Spinbox(sz, textvariable=self.h_var, from_=0.3, to=30, increment=0.1, width=6, state=st)
        e1.grid(row=0, column=1, pady=1)
        ttk.Label(sz, text="너비(cm)").grid(row=1, column=0, sticky="w")
        e2 = ttk.Spinbox(sz, textvariable=self.w_var, from_=0.5, to=30, increment=0.1, width=6, state=st)
        e2.grid(row=1, column=1, pady=1)
        ttk.Button(sz, text="적용", width=4, state=st, command=lambda: self.op("size")).grid(
            row=0, column=2, rowspan=2, padx=2, sticky="ns")
        ss = ttk.Frame(g)
        ss.pack(side="left", padx=2)
        ttk.Button(ss, text="☰ 행 높이를 같게", state=st, command=lambda: self.op("eq_rows")).pack(fill="x", pady=1)
        ttk.Button(ss, text="▥ 열 너비를 같게", state=st, command=lambda: self.op("eq_cols")).pack(fill="x", pady=1)
        g = grp("맞춤")
        al = ttk.Frame(g)
        al.pack(side="left")
        sym = [["↖", "↑", "↗"], ["←", "•", "→"], ["↙", "↓", "↘"]]
        for i, v in enumerate(("top", "center", "bottom")):
            for j, h in enumerate(("left", "center", "right")):
                ttk.Button(al, text=sym[i][j], width=2, state=st,
                           command=lambda v=v, h=h: self.op("align", v, h)).grid(row=i, column=j, padx=0, pady=0)
        g = grp("데이터")
        btn(g, "⇈\n머리글 행\n반복", lambda: self.op("header"), 8)

    # ------------------------------------------------------------ 선택
    def _origin(self, r, c):
        for (rr, cc), v in self.entries.items():
            if rr <= r < rr + v[4] and cc <= c < cc + v[5]:
                return rr, cc
        return r, c

    def _click(self, r, c, ev):
        if ev.state & 1:                                 # Shift
            self.cur = (r, c)
        else:
            self.anchor = self.cur = (r, c)
        self._paint_sel()

    def _focus(self, r, c):
        if not getattr(self, "_dragging", False) and (r, c) != self.cur and (r, c) not in self.sel_cells():
            self.anchor = self.cur = (r, c)
            self._paint_sel()

    def _drag(self, ev):
        w = self.winfo_containing(ev.x_root, ev.y_root)
        for k, v in self.entries.items():
            if v[0] is w and k != self.cur:
                self._dragging = True
                self.cur = k
                self._paint_sel()
                self.after(50, lambda: setattr(self, "_dragging", False))
                break

    def sel_rect(self):
        (r1, c1), (r2, c2) = self.anchor, self.cur
        e1, e2 = self.entries.get(self.anchor), self.entries.get(self.cur)
        r2e = r2 + (e2[4] - 1 if e2 else 0)
        c2e = c2 + (e2[5] - 1 if e2 else 0)
        r1e = r1 + (e1[4] - 1 if e1 else 0)
        c1e = c1 + (e1[5] - 1 if e1 else 0)
        return min(r1, r2), min(c1, c2), max(r1e, r2e), max(c1e, c2e)

    def sel_cells(self):
        a, b, c, d = self.sel_rect()
        return [k for k, v in self.entries.items()
                if not (k[0] + v[4] - 1 < a or k[0] > c or k[1] + v[5] - 1 < b or k[1] > d)]

    def _paint_sel(self):
        sel = set(self.sel_cells())
        for k, v in self.entries.items():
            v[0].config(highlightbackground=TH.ORANGE if k in sel else TH.PANEL)
        if self.word:
            try:
                from docx_table import TGrid
                g = TGrid(self.t.ref)
                a, b, c, d = self.sel_rect()
                h = g.row_height(a)
                self.h_var.set(f"{h:.2f}" if h else "")
                self.w_var.set(f"{sum(g.widths()[b:d + 1]) / (1440 / 2.54):.2f}")
            except Exception:
                pass

    def _move(self, r, c, d):
        rr = r + d
        rows = max(k[0] for k in self.entries) if self.entries else 0
        while 0 <= rr <= rows:
            o = self._origin(rr, c)
            if o in self.entries and o != (r, c):
                self.entries[o][0].focus_set()
                self.anchor = self.cur = o
                self._paint_sel()
                return "break"
            rr += d
        return "break"

    # ------------------------------------------------------------ 저장 / 작업
    def _changes(self):
        return [(p, cur, var.get()) for (e, p, cur, var, rs, cs) in self.entries.values() if var.get() != cur]

    def _save(self):
        ch = self._changes()
        self.destroy()
        if ch:
            self.app.commit_changes(ch, "표 편집")

    def _close(self):
        if self._changes() and messagebox.askyesno(APP_TITLE, "입력한 내용을 저장할까요?", parent=self):
            return self._save()
        self.destroy()

    def clear_cells(self):
        for k in self.sel_cells():
            e = self.entries[k]
            if str(e[0].cget("state")) != "disabled":
                e[3].set("")

    def delete_table(self):
        if not messagebox.askyesno(APP_TITLE, "이 표를 지울까요? (캡션 문단은 남습니다)", parent=self):
            return
        tbl = self.t.ref
        tbl.getparent().remove(tbl)
        self.destroy()
        rc.rebuild_docx(self.app.rep, self.doc)
        self.app._after_structure(None, "표 삭제")

    def split_dialog(self):
        if not self.word:
            return
        d = tk.Toplevel(self)
        d.title("셀 분할")
        d.transient(self)
        f = ttk.Frame(d, padding=14)
        f.pack()
        rv, cv = tk.StringVar(value="1"), tk.StringVar(value="2")
        ttk.Label(f, text="열 개수").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(f, textvariable=cv, from_=1, to=20, width=6).grid(row=0, column=1, pady=3)
        ttk.Label(f, text="행 개수").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(f, textvariable=rv, from_=1, to=50, width=6).grid(row=1, column=1, pady=3)

        def ok():
            try:
                nr, nc = int(rv.get()), int(cv.get())
            except ValueError:
                return
            d.destroy()
            self.op("split", nr, nc)
        ttk.Button(f, text="확인", style="Accent.TButton", command=ok).grid(row=2, column=0, columnspan=2, pady=(10, 0))
        d.grab_set()

    def op(self, name, *args):
        if not self.word:
            return
        import docx_table as dtb
        for p, cur, new in self._changes():             # 입력한 글은 먼저 수정 대기로
            self.app.rep.set_edit(p, new, "표 편집")
        a, b, c, d = self.sel_rect()
        rows, cols = list(range(a, c + 1)), list(range(b, d + 1))
        cells = self.sel_cells()
        doc, ref = self.doc, self.t.ref
        tw = dtb.section_text_width(doc.docx)
        new_sel = ((a, b), (a, b))

        def fn(g):
            nonlocal new_sel
            if name == "row_above":
                g.insert_row(a, below=False)
            elif name == "row_below":
                g.insert_row(c, below=True)
                new_sel = ((c + 1, b), (c + 1, b))
            elif name == "col_left":
                g.insert_col(b, right=False)
            elif name == "col_right":
                g.insert_col(d, right=True)
                new_sel = ((a, d + 1), (a, d + 1))
            elif name == "delete_rows":
                g.delete_rows(rows)
                new_sel = ((max(0, a - 1), 0), (max(0, a - 1), 0))
            elif name == "delete_cols":
                g.delete_cols(cols)
                new_sel = ((a, max(0, b - 1)), (a, max(0, b - 1)))
            elif name == "merge":
                g.merge(a, b, c, d)
            elif name == "split":
                g.split(a, b, args[0], args[1])
            elif name == "fit_content":
                g.autofit("content")
            elif name == "fit_window":
                g.autofit("window", tw)
            elif name == "fit_fixed":
                g.autofit("fixed")
            elif name == "size":
                try:
                    if self.h_var.get().strip():
                        g.set_row_height(rows, float(self.h_var.get()))
                    if self.w_var.get().strip():
                        w = float(self.w_var.get())
                        g.set_col_width(cols, w / len(cols))
                except ValueError:
                    pass
            elif name == "eq_rows":
                g.equal_rows(rows)
            elif name == "eq_cols":
                g.equal_cols(cols)
            elif name == "align":
                g.align(cells, args[0], args[1])
            elif name == "header":
                g.header_repeat(rows, not g.is_header(a))
        if name == "delete_rows" and len(rows) >= len(set(k[0] for k in self.entries)):
            return self.delete_table()
        try:
            rc.table_op(self.app.rep, doc, self.t, fn)
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"표 작업 실패: {e}", parent=self)
            return
        geom = self.geometry()
        self.destroy()
        self.app._after_structure(None, "표 레이아웃 변경")
        for dd in self.app.rep.docs:
            for t in dd.tables:
                if t.ref is ref:
                    TableEditor(self.app, t, keep={"sel": new_sel, "geom": geom})
                    return


class SettingsDialog(tk.Toplevel):
    """AI 엔진 선택: Claude(유료) / Ollama(무료, 내 PC) / OpenAI 호환 서버"""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("설정 — AI 검토 엔진")
        self.transient(app.root)
        self.resizable(False, False)
        s = app.settings
        frm = ttk.Frame(self, padding=14)
        frm.pack(fill="both")
        self.prov_names = list(rc.PROVIDERS.values())
        self.prov_ids = list(rc.PROVIDERS.keys())
        ttk.Label(frm, text="AI 엔진", font=(app.font, 10, "bold")).grid(row=0, column=0, sticky="w")
        self.prov = tk.StringVar(value=rc.PROVIDERS.get(s.get("provider", "claude"), self.prov_names[0]))
        cb = ttk.Combobox(frm, textvariable=self.prov, values=self.prov_names, state="readonly", width=44)
        cb.grid(row=0, column=1, sticky="w", pady=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self._switch())

        self.vars = {
            "claude": {"key": tk.StringVar(value=s.get("api_key", "")), "model": tk.StringVar(value=s.get("model", MODELS[0]))},
            "ollama": {"url": tk.StringVar(value=s.get("ollama_url", rc.DEFAULT_URL["ollama"])),
                       "model": tk.StringVar(value=s.get("ollama_model", OLLAMA_SUGGEST[0])),
                       "ctx": tk.StringVar(value=str(s.get("num_ctx", 16384)))},
            "openai": {"url": tk.StringVar(value=s.get("openai_url", rc.DEFAULT_URL["openai"])),
                       "model": tk.StringVar(value=s.get("openai_model", "")),
                       "key": tk.StringVar(value=s.get("openai_key", ""))},
        }
        self.box = ttk.Frame(frm)
        self.box.grid(row=1, column=0, columnspan=2, sticky="we", pady=(8, 0))
        self.vis = tk.BooleanVar(value=s.get("hwp_visible", False))
        ttk.Checkbutton(frm, text="한글에 반영할 때 한글 창 보이기", variable=self.vis).grid(
            row=2, column=1, sticky="w", pady=(12, 0))
        bf = ttk.Frame(frm)
        bf.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(bf, text="취소", command=self.destroy).pack(side="right")
        ttk.Button(bf, text="저장", command=self._ok).pack(side="right", padx=6)
        ttk.Button(bf, text="연결 시험", command=self._test).pack(side="left")
        self._switch()
        self.grab_set()

    def _pid(self):
        return self.prov_ids[self.prov_names.index(self.prov.get())]

    def _row(self, r, label, widget, note=None):
        ttk.Label(self.box, text=label).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=3)
        widget.grid(row=r, column=1, sticky="w", pady=3)
        if note:
            ttk.Label(self.box, text=note, style="Hint.TLabel", wraplength=480, justify="left").grid(
                row=r + 1, column=1, sticky="w")

    def _switch(self):
        for w in self.box.winfo_children():
            w.destroy()
        pid = self._pid()
        v = self.vars[pid]
        if pid == "claude":
            self._row(0, "API 키", ttk.Entry(self.box, textvariable=v["key"], width=50, show="•"),
                      "console.anthropic.com 에서 발급 · 이 PC에만 저장됩니다")
            self._row(2, "모델", ttk.Combobox(self.box, textvariable=v["model"], values=MODELS, width=30))
        else:
            self._row(0, "서버 주소", ttk.Entry(self.box, textvariable=v["url"], width=50))
            mf = ttk.Frame(self.box)
            self.model_cb = ttk.Combobox(mf, textvariable=v["model"], width=32,
                                         values=OLLAMA_SUGGEST if pid == "ollama" else [])
            self.model_cb.pack(side="left")
            ttk.Button(mf, text="설치된 모델 불러오기", command=self._load_models).pack(side="left", padx=6)
            if pid == "ollama":
                self._row(1, "모델", mf,
                          "무료 · 인터넷 없이 내 PC에서 실행 (보고서 내용이 외부로 나가지 않음)\n"
                          "1) https://ollama.com/download 에서 설치\n"
                          "2) 명령 프롬프트:  ollama pull exaone3.5:7.8b   (한국어 우수, 약 5GB)\n"
                          "   그래픽카드 메모리 16GB 이상이면 qwen2.5:14b, gemma3:12b 도 추천\n"
                          "※ 내 PC 모델은 Claude보다 느리고 내용 검토는 약합니다 (오타·띄어쓰기 위주로 활용)")
                self._row(3, "문맥 길이", ttk.Combobox(self.box, textvariable=v["ctx"], width=10,
                                                      values=["8192", "16384", "32768"]),
                          "클수록 긴 절을 한 번에 검토하지만 메모리를 더 씁니다 (기본 16384)")
            else:
                self._row(1, "모델", mf, "LM Studio: 'Developer → Start Server' 후 기본 주소 http://localhost:1234/v1")
                self._row(3, "API 키", ttk.Entry(self.box, textvariable=v["key"], width=50, show="•"),
                          "필요 없는 서버는 비워 두세요")

    def _load_models(self):
        pid = self._pid()
        try:
            names = rc.list_local_models(pid, self.vars[pid]["url"].get().strip())
        except Exception as e:
            messagebox.showerror(APP_TITLE, str(e), parent=self)
            return
        if not names:
            messagebox.showinfo(APP_TITLE, "설치된 모델이 없습니다.\n명령 프롬프트에서  ollama pull exaone3.5:7.8b  를 실행하세요.",
                                parent=self)
            return
        self.model_cb.config(values=names)
        if self.vars[pid]["model"].get() not in names:
            self.vars[pid]["model"].set(names[0])
        messagebox.showinfo(APP_TITLE, f"모델 {len(names)}개:\n" + "\n".join(names[:20]), parent=self)

    def _collect(self):
        s = dict(self.app.settings)
        s["provider"] = self._pid()
        c, o, a = self.vars["claude"], self.vars["ollama"], self.vars["openai"]
        s["api_key"] = c["key"].get().strip()
        s["model"] = c["model"].get().strip() or MODELS[0]
        s["ollama_url"] = o["url"].get().strip() or rc.DEFAULT_URL["ollama"]
        s["ollama_model"] = o["model"].get().strip()
        try:
            s["num_ctx"] = max(2048, int(o["ctx"].get()))
        except ValueError:
            s["num_ctx"] = 16384
        s["openai_url"] = a["url"].get().strip() or rc.DEFAULT_URL["openai"]
        s["openai_model"] = a["model"].get().strip()
        s["openai_key"] = a["key"].get().strip()
        s["hwp_visible"] = bool(self.vis.get())
        return s

    def _test(self):
        s = self._collect()
        err = check_ai_settings(s)
        if err:
            messagebox.showwarning(APP_TITLE, err, parent=self)
            return
        cl = make_client(s)
        self.config(cursor="watch")
        self.update()
        try:
            out = cl.complete('JSON으로만 답하세요.', '{"ok": true} 를 그대로 출력하세요.', max_tokens=50)
            messagebox.showinfo(APP_TITLE, f"연결 성공 — {cl.describe()}\n\n응답: {out[:200]}", parent=self)
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"연결 실패 — {cl.describe()}\n\n{e}", parent=self)
        finally:
            self.config(cursor="")

    def _ok(self):
        self.app.settings.update(self._collect())
        save_settings(self.app.settings)
        self.app.update_engine_label()
        self.destroy()


def check_ai_settings(s):
    p = s.get("provider", "claude")
    if p == "claude" and not s.get("api_key"):
        return "Claude API 키를 입력하세요. (무료로 쓰려면 AI 엔진을 'Ollama'로 바꾸세요)"
    if p == "ollama" and not s.get("ollama_model"):
        return "Ollama 모델을 선택하세요. ('설치된 모델 불러오기')"
    if p == "openai" and not s.get("openai_model"):
        return "모델 이름을 입력하세요. ('설치된 모델 불러오기')"
    return None


def make_client(s):
    p = s.get("provider", "claude")
    if p == "ollama":
        return rc.AIClient(provider="ollama", model=s.get("ollama_model"), base_url=s.get("ollama_url"),
                           num_ctx=int(s.get("num_ctx", 16384)))
    if p == "openai":
        return rc.AIClient(provider="openai", model=s.get("openai_model"), base_url=s.get("openai_url"),
                           api_key=s.get("openai_key", ""), num_ctx=int(s.get("num_ctx", 16384)))
    return rc.AIClient(api_key=s.get("api_key", ""), model=s.get("model", MODELS[0]))


# ====================================================================== 메인 앱

class App:
    def __init__(self, root, embedded=False, username=""):
        self.root = root
        self.embedded = embedded
        self.rep = rc.Report()
        self.settings = load_settings()
        self.font = pick_font()
        self.cur_sec = None
        self.sel_para = None
        self.sec_by_iid = {}
        self.ranges = []            # 뷰어: [(start_off, end_off, para)]
        self.range_starts = []
        self.para_pos = {}          # uid -> (start_off, end_off)
        self.issues = []
        self.issue_paras = set()
        self.ai_results = {}        # sec.sid -> (summary, [Suggestion])
        self.ai_busy = False
        self.check_items = []       # 검사 탭 항목
        self.occ_items = []
        self.list_items = []
        self.sim_items = []
        self._quiet = False
        self.mode = None

        root.title(APP_TITLE + (f"  ─  {username}" if username else ""))
        root.geometry("1500x900")
        style = ttk.Style()
        if embedded:
            TH.ensure(root)                # 런처 안: CAD Analysis 와 같은 공용 테마 (이미 적용됐으면 그대로)
        else:
            TH.apply(root)
        try:
            TH.set_icon(root)
        except Exception:
            pass
        try:
            root.configure(bg=TH.SURFACE)
        except Exception:
            pass
        style.configure("RD.Treeview", font=(self.font, 10), rowheight=25)
        style.configure("RD.Treeview.Heading", font=(self.font, 9, "bold"))
        style.configure("Panel.TLabel", background=TH.SURFACE, foreground=TH.NAVY, font=(self.font, 10, "bold"))
        style.configure("Hint.TLabel", background=TH.SURFACE, foreground=TH.MUTED, font=(self.font, 9))
        style.configure("Info.TLabel", background=TH.SURFACE, foreground=TH.NAVY_3, font=(self.font, 9, "bold"))

        self._build_header()
        self._build_toolbar()
        self._build_body()
        self.status = tk.StringVar(value="'한글 열기'(분석·검토) 또는 'Word 열기'(작성·추가)로 보고서 장(章) 파일 폴더를 여세요.")
        ttk.Label(root, textvariable=self.status, anchor="w", style="Status.TLabel").pack(fill="x", side="bottom")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Control-s>", lambda e: self.apply_to_hwp())
        root.bind("<Control-v>", self.paste_image)
        root.bind("<Control-V>", self.paste_image)

    # ------------------------------------------------------------ 레이아웃
    def _build_header(self):
        hd = tk.Frame(self.root, bg=TH.NAVY, height=46)
        hd.pack(fill="x")
        hd.pack_propagate(False)
        logo = TH.image("icon_32.png")
        if logo is not None:
            tk.Label(hd, image=logo, bg=TH.NAVY).pack(side="left", padx=(14, 8))
        else:
            tk.Frame(hd, bg=TH.NAVY, width=14).pack(side="left")
        tk.Label(hd, text="StrCAD", bg=TH.NAVY, fg="white", font=(self.font, 15, "bold")).pack(side="left")
        tk.Label(hd, text="Report Design", bg=TH.NAVY, fg=TH.ORANGE, font=(self.font, 10, "bold")).pack(
            side="left", padx=(8, 0), pady=(5, 0))
        tk.Frame(hd, bg=TH.NAVY_3, width=1).pack(side="left", fill="y", padx=16, pady=11)
        self.hd_mode = tk.Label(hd, text="", bg=TH.NAVY_3, fg="white", font=(self.font, 9, "bold"), padx=6)
        self.hd_doc = tk.Label(hd, text="'한글 열기' 또는 'Word 열기'로 보고서 폴더를 여세요", bg=TH.NAVY,
                               fg="#C9D3E4", font=(self.font, 10))
        self.hd_doc.pack(side="left")
        tk.Label(hd, text=f"v{APP_VERSION}", bg=TH.NAVY, fg=TH.NAVY_L, font=(self.font, 8)).pack(side="right", padx=(6, 14))
        self.hd_ai = tk.Label(hd, text="", bg=TH.NAVY, fg=TH.NAVY_L, font=(self.font, 9), cursor="hand2")
        self.hd_ai.pack(side="right", padx=8)
        self.hd_ai.bind("<Button-1>", lambda e: SettingsDialog(self))

    @staticmethod
    def _grp(parent, title):
        g = ttk.LabelFrame(parent, text=title, padding=(6, 2))
        g.pack(side="left", fill="y", padx=3)
        return g

    @staticmethod
    def _big(parent, text, cmd, w=9, accent=False):
        b = ttk.Button(parent, text=text, command=cmd, width=w,
                       style="RibbonAccent.TButton" if accent else "Ribbon.TButton")
        b.pack(side="left", padx=2, pady=2, fill="y")
        return b

    def _build_toolbar(self):
        """CAD Analysis 와 같은 리본 메뉴"""
        rb = ttk.Notebook(self.root)
        rb.pack(fill="x")
        home = ttk.Frame(rb, padding=(6, 6))
        rb.add(home, text="  홈  ")
        g = self._grp(home, "보고서 열기")
        self.btn_open_hwp = self._big(g, "📂\n한글 열기", lambda: self.open_folder("hwp"))
        self.btn_open_word = self._big(g, "📂\nWord 열기", lambda: self.open_folder("word"))
        self._big(g, "＋\n파일 추가", self.add_files)
        self._big(g, "⟳\n다시 읽기", self.reload_all)
        self.btn_convert = self._big(g, "⇄\n한글→Word\n새로 만들기", self.convert_hwp_to_word, 10)
        g = self._grp(home, "추가 (Word)")
        self.word_btns = [
            self._big(g, "§\n새 절", lambda: self.ui_add_section(self._target_sec(), "after")),
            self._big(g, "§›\n하위 절", lambda: self.ui_add_section(self._target_sec(), "child")),
            self._big(g, "▦\n표", lambda: self.ui_add_table(self._target_para(), self._target_sec())),
            self._big(g, "🖼\n사진", lambda: self.ui_add_picture(self._target_para(), self._target_sec())),
            self._big(g, "📋\n그림 붙여\n넣기", self.paste_image)]
        g = self._grp(home, "검사")
        self._big(g, "#\n번호 검사", self.run_numbering)
        self._big(g, "≒\n반복 문단\n불일치", self.run_inconsistency, 10)
        g = self._grp(home, "AI 검토")
        self._big(g, "✦\n선택 절\nAI 검토", lambda: (self.nb.select(self.tab_ai), self.run_ai()))
        self._big(g, "⚙\n엔진 설정", lambda: SettingsDialog(self))
        g = self._grp(home, "반영")
        self.btn_changes = self._big(g, "☰\n변경 목록\n(0)", lambda: self.nb.select(self.tab_list))
        self._big(g, "✔\n파일에\n반영·저장", self.apply_to_hwp, 10, accent=True)

    def _build_body(self):
        pw = ttk.PanedWindow(self.root, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=4)

        # 왼쪽: 장/절 트리
        lf = ttk.Frame(pw)
        ttk.Label(lf, text="장 / 절", style="Panel.TLabel").pack(anchor="w", padx=6, pady=(6, 3))
        self.tree = ttk.Treeview(lf, show="tree", selectmode="browse", style="RD.Treeview")
        tsb = ttk.Scrollbar(lf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tsb.pack(side="right", fill="y")
        self.tree.tag_configure("doc", font=(self.font, 10, "bold"), foreground=TH.NAVY)
        self.tree.tag_configure("issue", foreground=TH.NG)
        self.tree.tag_configure("edited", background="#fff6cc")
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Button-3>", self.on_tree_menu)
        pw.add(lf, weight=1)

        # 가운데: 본문 보기
        cf = ttk.Frame(pw)
        hdr = ttk.Frame(cf)
        hdr.pack(fill="x")
        self.sec_title = tk.StringVar(value="")
        ttk.Label(hdr, textvariable=self.sec_title, style="Panel.TLabel").pack(side="left", padx=6, pady=(6, 3))
        ttk.Label(hdr, text="더블클릭: 수정 · 우클릭: 메뉴", style="Hint.TLabel").pack(side="right", padx=6)
        self.view = tk.Text(cf, wrap="word", font=(self.font, 10), padx=14, pady=10, cursor="arrow",
                            spacing1=2, spacing3=2, bg=TH.PANEL, fg=TH.INK, relief="flat",
                            highlightthickness=1, highlightbackground=TH.LINE, highlightcolor=TH.LINE)
        vsb = ttk.Scrollbar(cf, orient="vertical", command=self.view.yview)
        self.view.configure(yscrollcommand=vsb.set)
        self.view.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        f = self.font
        self.view.tag_configure("h0", font=(f, 15, "bold"), foreground=TH.NAVY, spacing1=12, spacing3=8)
        self.view.tag_configure("h1", font=(f, 13, "bold"), foreground=TH.NAVY, spacing1=10, spacing3=4)
        self.view.tag_configure("h2", font=(f, 11, "bold"), foreground=TH.NAVY, spacing1=8, spacing3=2)
        self.view.tag_configure("h3", font=(f, 10, "bold"), foreground=TH.NAVY_2, spacing1=6)
        self.view.tag_configure("tbl", font=(f, 9), background=TH.SURFACE, lmargin1=10, lmargin2=10)
        self.view.tag_configure("tblhdr", font=(f, 9, "bold"), foreground=TH.NAVY_3)
        self.view.tag_configure("bar", foreground=TH.NAVY_L)
        self.view.tag_configure("box", foreground="#455a64", font=(f, 9, "italic"))
        self.view.tag_configure("edited", background="#fff3b0")
        self.view.tag_configure("picline", foreground=TH.NAVY_3, font=(f, 9, "bold"), justify="center",
                                spacing1=6, spacing3=6)
        self.view.tag_configure("piccenter", justify="center", spacing1=6, spacing3=4)
        self.view.tag_configure("newempty", foreground=TH.MUTED, font=(f, 9, "italic"), background=TH.ORANGE_L)
        self.view.tag_configure("origline", foreground="#9e9e9e", overstrike=1, font=(f, 9))
        self.view.tag_configure("issue", underline=1, foreground=TH.NG)
        self.view.tag_configure("aispan", background="#ffd8a8")
        self.view.tag_configure("sel_para", background=TH.ORANGE_L)
        self.view.tag_configure("flash", background="#FBC98E")
        self.view.tag_raise("sel_para")
        self.view.tag_raise("flash")
        self.view.bind("<Button-1>", self.on_view_click)
        self.view.bind("<Double-Button-1>", self.on_view_double)
        self.view.bind("<Button-3>", self.on_view_menu)
        self.view.bind("<Key>", lambda e: None if (e.state & 4 and e.keysym.lower() in ("c", "a", "v", "s")) else "break")
        pw.add(cf, weight=4)

        # 오른쪽: 탭
        rf = ttk.Frame(pw)
        self.nb = ttk.Notebook(rf)
        self.nb.pack(fill="both", expand=True)
        self.tab_ai = ttk.Frame(self.nb, padding=6)
        self.tab_sim = ttk.Frame(self.nb, padding=6)
        self.tab_check = ttk.Frame(self.nb, padding=6)
        self.tab_common = ttk.Frame(self.nb, padding=6)
        self.tab_list = ttk.Frame(self.nb, padding=6)
        self.nb.add(self.tab_ai, text="AI 검토")
        self.nb.add(self.tab_sim, text="동일 내용")
        self.nb.add(self.tab_check, text="검사")
        self.nb.add(self.tab_common, text="공통 항목")
        self.nb.add(self.tab_list, text="변경 목록")
        self._build_ai_tab()
        self._build_sim_tab()
        self._build_check_tab()
        self._build_common_tab()
        self._build_list_tab()
        pw.add(rf, weight=2)
        self._pw = pw
        self.root.after(80, self._init_sash)

    def _init_sash(self, tries=0):
        """창 크기가 정해진 뒤 패널 폭 설정 (트리 300, 오른쪽 탭 약 480)"""
        w = self._pw.winfo_width()
        if w < 900 and tries < 30:
            self.root.after(100, lambda: self._init_sash(tries + 1))
            return
        try:
            self._pw.sashpos(0, 300)
            self._pw.sashpos(1, max(700, w - 500))
        except Exception:
            pass

    def _tv(self, parent, cols, height=12):
        frm = ttk.Frame(parent)
        tv = ttk.Treeview(frm, columns=[c[0] for c in cols], show="headings", height=height, selectmode="extended", style="RD.Treeview")
        for key, title, w in cols:
            tv.heading(key, text=title)
            tv.column(key, width=w, stretch=(w >= 150), anchor="w")
        sb = ttk.Scrollbar(frm, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return frm, tv

    # ---- AI 탭
    def _build_ai_tab(self):
        t = self.tab_ai
        top = ttk.Frame(t)
        top.pack(fill="x")
        self.ai_sec_lbl = tk.StringVar(value="왼쪽에서 절을 선택하세요")
        ttk.Label(top, textvariable=self.ai_sec_lbl, font=(self.font, 10, "bold"), wraplength=420).pack(anchor="w")
        row = ttk.Frame(t)
        row.pack(fill="x", pady=4)
        self.ai_children = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="하위 절 포함", variable=self.ai_children).pack(side="left")
        self.ai_btn = ttk.Button(row, text="▶ 이 절 AI 검토", style="Accent.TButton", command=self.run_ai)
        self.ai_btn.pack(side="right")
        eng = ttk.Frame(t)
        eng.pack(fill="x")
        self.engine_lbl = tk.StringVar(value="")
        ttk.Label(eng, textvariable=self.engine_lbl, style="Hint.TLabel").pack(side="left")
        ttk.Button(eng, text="엔진 변경", command=lambda: SettingsDialog(self)).pack(side="right")
        self.update_engine_label()
        self.ai_status = tk.StringVar(value="")
        ttk.Label(t, textvariable=self.ai_status, style="Info.TLabel").pack(anchor="w")
        self.ai_summary = tk.StringVar(value="")
        ttk.Label(t, textvariable=self.ai_summary, wraplength=430, foreground="#333").pack(anchor="w", pady=(2, 4))
        frm, self.ai_tv = self._tv(t, [("st", "상태", 50), ("type", "유형", 60), ("orig", "원문", 150),
                                       ("sug", "제안", 150)], height=12)
        frm.pack(fill="both", expand=True)
        self.ai_tv.tag_configure("적용", foreground=TH.OK)
        self.ai_tv.tag_configure("무시", foreground="#9e9e9e")
        self.ai_tv.tag_configure("comment", foreground="#6a1b9a")
        self.ai_tv.bind("<<TreeviewSelect>>", self.on_ai_select)
        self.ai_tv.bind("<Double-Button-1>", lambda e: self.ai_apply())
        self.ai_reason = tk.StringVar(value="")
        ttk.Label(t, textvariable=self.ai_reason, wraplength=430, style="Hint.TLabel").pack(anchor="w", pady=(4, 2))
        self.ai_diff = make_diff_text(t, self.font, 5)
        self.ai_diff.pack(fill="x")
        bf = ttk.Frame(t)
        bf.pack(fill="x", pady=6)
        ttk.Button(bf, text="선택 적용", command=self.ai_apply).pack(side="left")
        ttk.Button(bf, text="선택 무시", command=self.ai_ignore).pack(side="left", padx=4)
        ttk.Button(bf, text="대기 항목 모두 적용", command=self.ai_apply_all).pack(side="right")

    # ---- 동일 내용 탭
    def _build_sim_tab(self):
        t = self.tab_sim
        ttk.Label(t, text="본문에서 문단을 클릭하면, 보고서의 다른 곳에 있는 같은/비슷한 문단을 보여줍니다.",
                  wraplength=430, style="Hint.TLabel").pack(anchor="w")
        self.sim_lbl = tk.StringVar(value="")
        ttk.Label(t, textvariable=self.sim_lbl, font=(self.font, 10, "bold"), wraplength=430).pack(anchor="w", pady=4)
        frm, self.sim_tv = self._tv(t, [("r", "유사도", 60), ("loc", "위치", 260), ("kind", "구분", 50)], 14)
        frm.pack(fill="both", expand=True)
        self.sim_tv.bind("<<TreeviewSelect>>", self.on_sim_select)
        self.sim_tv.bind("<Double-Button-1>", lambda e: self._goto_sel(self.sim_tv, self.sim_items, key=0))
        ttk.Label(t, text="선택한 문단 → 현재 문단과 비교 (빨강=선택 문단에만, 초록=현재 문단에만)",
                  style="Hint.TLabel").pack(anchor="w", pady=(4, 0))
        self.sim_diff = make_diff_text(t, self.font, 6)
        self.sim_diff.pack(fill="x")
        bf = ttk.Frame(t)
        bf.pack(fill="x", pady=6)
        ttk.Button(bf, text="선택 문단을 현재 문단 내용으로 맞추기", command=self.sim_sync).pack(side="left")
        ttk.Button(bf, text="위치로 이동", command=lambda: self._goto_sel(self.sim_tv, self.sim_items, key=0)).pack(side="right")

    # ---- 검사 탭
    def _build_check_tab(self):
        t = self.tab_check
        row = ttk.Frame(t)
        row.pack(fill="x")
        ttk.Button(row, text="번호 검사", command=self.run_numbering).pack(side="left")
        ttk.Button(row, text="반복 문단 불일치", command=self.run_inconsistency).pack(side="left", padx=4)
        self.chk_lbl = tk.StringVar(value="")
        ttk.Label(t, textvariable=self.chk_lbl, style="Info.TLabel").pack(anchor="w", pady=4)
        frm, self.chk_tv = self._tv(t, [("kind", "구분", 80), ("loc", "위치", 150), ("msg", "내용", 260)], 14)
        frm.pack(fill="both", expand=True)
        self.chk_tv.tag_configure("오류", foreground=TH.NG)
        self.chk_tv.tag_configure("done", foreground="#9e9e9e")
        self.chk_tv.bind("<<TreeviewSelect>>", self.on_chk_select)
        self.chk_tv.bind("<Double-Button-1>", lambda e: self._goto_sel(self.chk_tv, self.check_items, key="para"))
        self.chk_msg = tk.StringVar(value="")
        ttk.Label(t, textvariable=self.chk_msg, wraplength=430, foreground="#333").pack(anchor="w", pady=(4, 0))
        self.chk_diff = make_diff_text(t, self.font, 5)
        self.chk_diff.pack(fill="x", pady=(4, 0))
        bf = ttk.Frame(t)
        bf.pack(fill="x", pady=6)
        ttk.Button(bf, text="선택 항목 제안대로 수정", command=self.chk_fix).pack(side="left")
        self.btn_pair_rev = ttk.Button(bf, text="반대 방향으로 맞추기", command=lambda: self.chk_fix(reverse=True))
        self.btn_pair_rev.pack(side="left", padx=4)
        ttk.Button(bf, text="위치로 이동", command=lambda: self._goto_sel(self.chk_tv, self.check_items, key="para")).pack(side="right")

    # ---- 공통 항목 탭
    def _build_common_tab(self):
        t = self.tab_common
        ttk.Label(t, text="여러 장에 반복되는 기본 정보(과업명, 위치, 연면적, 준공연도, 재료강도 등)를 관리합니다.\n"
                          "값을 바꾸면 보고서 전체의 사용처를 찾아 함께 바꿀 수 있습니다.",
                  wraplength=430, style="Hint.TLabel").pack(anchor="w")
        frm, self.cm_tv = self._tv(t, [("k", "항목", 90), ("v", "값", 230), ("n", "사용처", 70)], 9)
        frm.pack(fill="both", expand=True, pady=4)
        self.cm_tv.tag_configure("warn", foreground=TH.NG)
        self.cm_tv.bind("<<TreeviewSelect>>", self.on_common_select)
        self.cm_tv.bind("<Double-Button-1>", lambda e: self.common_change())
        bf = ttk.Frame(t)
        bf.pack(fill="x")
        ttk.Button(bf, text="자동 추출", command=self.common_extract).pack(side="left")
        ttk.Button(bf, text="추가", command=self.common_add).pack(side="left", padx=2)
        ttk.Button(bf, text="삭제", command=self.common_del).pack(side="left")
        ttk.Button(bf, text="값 변경…", style="Accent.TButton", command=self.common_change).pack(side="right")
        ttk.Label(t, text="사용처 (빨강 = 값이 조금 다른 곳: 불일치 의심)", style="Hint.TLabel").pack(anchor="w", pady=(8, 0))
        frm2, self.occ_tv = self._tv(t, [("loc", "위치", 200), ("txt", "표기", 200)], 9)
        frm2.pack(fill="both", expand=True)
        self.occ_tv.tag_configure("warn", foreground=TH.NG)
        self.occ_tv.bind("<Double-Button-1>", lambda e: self._goto_sel(self.occ_tv, self.occ_items, key=0))

    # ---- 변경 목록 탭
    def _build_list_tab(self):
        t = self.tab_list
        ttk.Label(t, text="아직 한글 파일에 반영되지 않은 수정 사항입니다. '한글 파일에 반영'을 누르면 원본을 백업한 뒤 적용합니다.",
                  wraplength=430, style="Hint.TLabel").pack(anchor="w")
        frm, self.ls_tv = self._tv(t, [("loc", "위치", 170), ("new", "수정문", 200), ("src", "출처", 90)], 16)
        frm.pack(fill="both", expand=True, pady=4)
        self.ls_tv.bind("<<TreeviewSelect>>", self.on_list_select)
        self.ls_tv.bind("<Double-Button-1>", lambda e: self._goto_sel(self.ls_tv, self.list_items, key=None))
        self.ls_diff = make_diff_text(t, self.font, 6)
        self.ls_diff.pack(fill="x")
        bf = ttk.Frame(t)
        bf.pack(fill="x", pady=6)
        ttk.Button(bf, text="선택 수정 취소", command=self.list_undo).pack(side="left")
        ttk.Button(bf, text="CSV 내보내기", command=self.list_export).pack(side="left", padx=4)
        ttk.Button(bf, text="✔ 한글 파일에 반영", style="Accent.TButton", command=self.apply_to_hwp).pack(side="right")

    # ------------------------------------------------------------ 파일
    MODE_EXT = {"hwp": (".hwp", ".hwpx"), "word": (".docx",)}
    MODE_NAME = {"hwp": "한글", "word": "Word"}

    def open_folder(self, mode="word"):
        """한글 열기 / Word 열기 — 작업을 형식별로 나눔 (한 번에 한 형식만)"""
        name = self.MODE_NAME[mode]
        d = filedialog.askdirectory(title=f"{name} 보고서 장 파일들이 있는 폴더")
        if not d:
            return
        files = [os.path.join(d, nm) for nm in sorted(os.listdir(d))
                 if not nm.startswith(("~", ".")) and nm.lower().endswith(self.MODE_EXT[mode])]
        if not files:
            other = "hwp" if mode == "word" else "word"
            n_other = sum(1 for nm in os.listdir(d) if nm.lower().endswith(self.MODE_EXT[other]))
            messagebox.showinfo(APP_TITLE, f"이 폴더에 {name} 파일이 없습니다."
                                + (f"\n({self.MODE_NAME[other]} 파일 {n_other}개는 '{self.MODE_NAME[other]} 열기'로 여세요)"
                                   if n_other else ""))
            return
        self.open_files(mode, files)

    def open_files(self, mode, files):
        if not self._confirm_leave():
            return
        self._save_state_quiet()
        self.rep = rc.Report()
        self.ai_results.clear()
        self.issues, self.issue_paras, self.check_items = [], set(), []
        self.cur_sec = self.sel_para = None
        self.set_mode(mode)
        self._load(files)

    def _confirm_leave(self):
        dirty = self._dirty_word()
        if dirty:
            a = messagebox.askyesnocancel(APP_TITLE, "지금 Word 파일에 저장하지 않은 추가 내용(절·표·사진)이 있습니다.\n"
                                          "저장하고 넘어갈까요? (아니오 = 버리기)")
            if a is None:
                return False
            if a:
                self.apply_to_hwp(only_word=True)
                if self._dirty_word():
                    return False
        return True

    def set_mode(self, mode):
        self.mode = mode
        word = mode == "word"
        for b in getattr(self, "word_btns", []):
            b.state(["!disabled"] if word else ["disabled"])
        self.btn_open_word.configure(style="RibbonAccent.TButton" if word else "Ribbon.TButton")
        self.btn_open_hwp.configure(style="RibbonAccent.TButton" if mode == "hwp" else "Ribbon.TButton")
        self.hd_mode.config(text=f" {self.MODE_NAME[mode]} 작업 ", bg=TH.ORANGE if word else TH.NAVY_3)
        self.hd_mode.pack(side="left", padx=(0, 10), before=self.hd_doc)

    def add_files(self):
        mode = getattr(self, "mode", None) or "word"
        ext = self.MODE_EXT[mode]
        fs = filedialog.askopenfilenames(title=f"{self.MODE_NAME[mode]} 장 파일 추가", filetypes=[
            (f"{self.MODE_NAME[mode]} 문서", " ".join("*" + e for e in ext))])
        fs = [f for f in fs if f.lower().endswith(ext)]
        if fs:
            if not self.rep.docs:
                self.set_mode(mode)
            self._load(list(fs))

    def _load(self, files):
        if files and self.mode is None:
            self.set_mode("word" if files[0].lower().endswith(".docx") else "hwp")
        skipped = [f for f in files if not f.lower().endswith(self.MODE_EXT[self.mode])]
        files = [f for f in files if f.lower().endswith(self.MODE_EXT[self.mode])]
        if skipped:
            messagebox.showinfo(APP_TITLE, f"지금은 {self.MODE_NAME[self.mode]} 작업이라 다른 형식 파일 {len(skipped)}개는 열지 않았습니다.\n"
                                           "다른 형식은 '한글 열기' / 'Word 열기'로 따로 여세요.")
        errs = []
        self.root.config(cursor="watch")
        self.root.update()
        for f in files:
            try:
                self.status.set("읽는 중: " + os.path.basename(f))
                self.root.update_idletasks()
                self.rep.add_file(f)
            except Exception as e:
                errs.append(f"{os.path.basename(f)}: {e}")
        self.root.config(cursor="")
        ok, bad = self.rep.load_state()
        if not self.rep.common:
            self.rep.common = rc.extract_common(self.rep)
        self.refresh_all()
        msg = f"{len(self.rep.docs)}개 파일, 문단 {len(self.rep.paras):,}개"
        if ok:
            msg += f" · 이전 작업의 수정 대기 {ok}건 복원"
        if bad:
            msg += f" · {bad}건은 원문이 바뀌어 복원하지 않음"
        self.status.set(msg)
        if errs:
            messagebox.showwarning(APP_TITLE, "일부 파일을 읽지 못했습니다:\n\n" + "\n".join(errs))
        first = self.tree.get_children()
        if first:
            kids = [k for k in self.tree.get_children(first[0])
                    if k in self.sec_by_iid and self.sec_by_iid[k].title != "(표지·목차)"] or \
                list(self.tree.get_children(first[0]))
            self.tree.selection_set(kids[0] if kids else first[0])

    def reload_all(self):
        if not self.rep.docs:
            return
        if self._dirty_word() and not messagebox.askyesno(
                APP_TITLE, "저장하지 않은 Word 추가 내용(절·표·사진)이 사라집니다. 다시 읽을까요?"):
            return
        for d in list(self.rep.docs):
            try:
                self.rep.reload(d)
            except Exception as e:
                messagebox.showwarning(APP_TITLE, f"{os.path.basename(d.path)}: {e}")
        self.ai_results.clear()
        self.refresh_all()
        self.status.set("다시 읽었습니다.")

    def _save_state_quiet(self):
        try:
            self.rep.save_state()
        except Exception:
            pass

    def _dirty_word(self):
        return [d for d in self.rep.docs if d.fmt == "docx" and d.dirty]

    def on_close(self):
        dirty = self._dirty_word()
        if dirty:
            a = messagebox.askyesnocancel(APP_TITLE, "Word 파일에 저장하지 않은 추가 내용(절·표·사진)이 있습니다.\n\n"
                                          + "\n".join(os.path.basename(d.path) for d in dirty)
                                          + "\n\n지금 저장할까요? (아니오 = 버리고 닫기)")
            if a is None:
                return
            if a:
                self.apply_to_hwp(only_word=True)
                if self._dirty_word():
                    return
        self._save_state_quiet()
        self.root.destroy()

    # ------------------------------------------------------------ 갱신
    def refresh_all(self, keep_view=False):
        sel = self.cur_sec.sid if self.cur_sec else None
        y = self.view.yview()[0]
        self._fill_tree()
        if sel and self.tree.exists(sel):
            self._quiet = True
            self.tree.selection_set(sel)
            self.root.update_idletasks()
            self._quiet = False
            self.tree.see(sel)
            self.cur_sec = self.sec_by_iid[sel]
            self.render_section(self.cur_sec)
            if keep_view:
                self.view.yview_moveto(y)
        self._fill_list()
        self._fill_common()
        self.btn_changes.config(text=f"☰\n변경 목록\n({len(self.rep.edits)})")
        if self.rep.docs:
            folder = os.path.basename(os.path.dirname(self.rep.docs[0].path))
            self.hd_doc.config(text=f"{folder}  ·  {len(self.rep.docs)}개 파일")
        self._save_state_quiet()

    def _fill_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.sec_by_iid.clear()
        edited_secs = {}
        for uid in self.rep.edits:
            p = self.rep.paras.get(uid)
            if p and p.section:
                edited_secs[p.section.sid] = edited_secs.get(p.section.sid, 0) + 1
        issue_secs = {p.section.sid for p in self.issue_paras if p.section}
        for d in self.rep.docs:
            did = "doc:" + d.key
            self.tree.insert("", "end", iid=did, text="📄 " + os.path.basename(d.path), open=True, tags=("doc",))

            def add(parent, s):
                n = edited_secs.get(s.sid, 0)
                txt = s.label + (f"   ✎{n}" if n else "") + ("  ⚠" if s.sid in issue_secs else "")
                tags = []
                if s.sid in issue_secs:
                    tags.append("issue")
                if n:
                    tags.append("edited")
                self.tree.insert(parent, "end", iid=s.sid, text=txt, open=(s.level < 1), tags=tags)
                self.sec_by_iid[s.sid] = s
                for c in s.children:
                    add(s.sid, c)
            for r in self.rep.roots.get(d.key, []):
                add(did, r)

    def on_tree_select(self, _=None):
        s = self.tree.selection()
        if not s:
            return
        if self._quiet:
            return
        sec = self.sec_by_iid.get(s[0])
        if sec is None:
            kids = [k for k in self.tree.get_children(s[0]) if self.sec_by_iid[k].title != "(표지·목차)"]
            kids = kids or list(self.tree.get_children(s[0]))
            if kids:
                self.tree.selection_set(kids[0])
            return
        self.cur_sec = sec
        self.render_section(sec)
        self._show_ai_for(sec)

    # ------------------------------------------------------------ 본문 보기
    def render_section(self, sec):
        v = self.view
        v.config(state="normal")
        v.delete("1.0", "end")
        for w in getattr(self, "_embedded", []):
            try:
                w.destroy()
            except tk.TclError:
                pass
        self._embedded = []
        self.cell_labels = {}
        self.ranges = []
        self.para_pos = {}
        self.sec_title.set(f"{os.path.basename(sec.doc.path)}  ›  {sec.label}")
        off = 0
        ai = self.ai_results.get(sec.sid)
        ai_spans = {}
        if ai:
            for sg in ai[1]:
                if sg.state == "대기" and sg.span:
                    ai_spans.setdefault(sg.para.uid, []).append(sg)

        def put(s, *tags):
            nonlocal off
            v.insert("end", s, tags)
            off += len(s)

        def put_para(p, base_tags=(), prefix=""):
            nonlocal off
            t = self.rep.text(p)
            if prefix:
                put(prefix, "bar")
            start = off
            tags = list(base_tags)
            if p.uid in self.rep.edits:
                tags.append("edited")
            if p in self.issue_paras:
                tags.append("issue")
            put(t if t else " ", *tags)
            self.ranges.append((start, off, p))
            self.para_pos[p.uid] = (start, off)
            for sg in ai_spans.get(p.uid, []):
                sp = rc.find_loose(t, sg.original)
                if sp:
                    v.tag_add("aispan", f"1.0+{start + sp[0]}c", f"1.0+{start + sp[1]}c")

        for k, obj in rc.section_blocks(sec, True):
            if k == "p":
                p = obj
                t = self.rep.text(p)
                h = None
                if p.kind == "body":
                    h = heading_of(p)
                is_new = p.ref is not None and id(p.ref) in self.rep.new_refs
                if p.pic:
                    w = self._pic_widget(p)
                    if w is not None:
                        start = off
                        v.window_create("end", window=w)
                        self._embedded.append(w)
                        off += 1
                        v.tag_add("piccenter", f"1.0+{start}c", f"1.0+{off}c")
                        self.ranges.append((start, off, p))
                        self.para_pos[p.uid] = (start, off)
                        put("\n", "piccenter")
                        if t.strip():
                            put(t + "\n", "picline")
                    else:
                        put("🖼 [그림]" + (" " + t if t.strip() else "") + "\n", "picline")
                        self.ranges.append((off - 1, off - 1, p))
                    continue
                if not t.strip() and p.uid not in self.rep.edits and not is_new:
                    continue
                tags = (f"h{min(h[2], 3)}",) if h else (("box",) if p.kind == "box" else ())
                if not t.strip() and is_new:
                    start = off
                    put("⟨새 문단 — 더블클릭해서 입력⟩", "newempty")
                    self.ranges.append((start, off, p))
                    self.para_pos[p.uid] = (start, off)
                    put("\n")
                    continue
                put_para(p, tags)
                put("\n")
                if p.uid in self.rep.edits:
                    put("    원문: " + p.orig + "\n", "origline")
            else:
                put(f"[표 {obj.tid + 1}]  {obj.rows}×{obj.cols}   ", "tblhdr")
                btn = tk.Label(v, text="✎ 표 편집", fg="white", bg=TH.NAVY_3, font=(self.font, 8, "bold"),
                               padx=6, cursor="hand2")
                btn.bind("<Button-1>", lambda e, t=obj: self.open_table_editor(t))
                v.window_create("end", window=btn)
                self._embedded.append(btn)
                off += 1
                put("\n", "tblhdr")
                grid = self._table_grid(obj)
                if grid is not None:
                    start = off
                    v.window_create("end", window=grid, padx=10, pady=2)
                    self._embedded.append(grid)
                    off += 1
                    for cell in obj.cells.values():
                        for p in cell["paras"]:
                            self.para_pos[p.uid] = (start, off)
                    put("\n")
                else:
                    self._table_text(obj, put, put_para, lambda: off, self._add_range)
                put("\n")
        self.range_starts = [r[0] for r in self.ranges]
        v.config(state="normal")
        if self.sel_para and self.sel_para.uid in self.para_pos:
            self._mark_sel(self.sel_para)

    def _add_range(self, start, end, p):
        self.ranges.append((start, end, p))
        self.para_pos[p.uid] = (start, end)

    MAX_GRID_CELLS = 700

    def _table_grid(self, t):
        """표를 실제 칸 모양으로 (Label 격자). 너무 큰 표는 None → 글자 표시"""
        if len(t.cells) > self.MAX_GRID_CELLS:
            return None
        widths = rc.table_col_widths(t)
        total = sum(widths) or 1
        avail = max(400, self.view.winfo_width() - 70)
        px = [max(36, int(avail * w / total)) for w in widths]
        fr = tk.Frame(self.view, bg="#9AA5B8", bd=0, padx=1, pady=1)
        for k, w in enumerate(px):
            fr.grid_columnconfigure(k, minsize=w)
        new_tbl = getattr(t, "ref", None) is not None and id(t.ref) in self.rep.new_refs
        for (r, c), cell in sorted(t.cells.items()):
            ps = cell["paras"]
            texts = [self.rep.text(p) for p in ps]
            txt = "\n".join(x for x in texts if x.strip())
            p0 = next((p for p in ps if self.rep.text(p).strip()), ps[0] if ps else None)
            edited = any(p.uid in self.rep.edits for p in ps)
            issue = any(p in self.issue_paras for p in ps)
            pic = any(p.pic for p in ps)
            if pic and not txt:
                txt = "🖼 [그림]"
            bg = "#FFF3B0" if edited else (TH.ORANGE_L if (new_tbl and not txt) else TH.PANEL)
            w = sum(px[c:c + cell["cs"]])
            photo = None
            if pic:
                pp = next((q for q in ps if q.pic), None)
                photo = self._thumb(pp, max(40, w - 12)) if pp is not None else None
                if photo is not None and txt == "🖼 [그림]":
                    txt = ""
            lb = tk.Label(fr, text=txt, bg=bg, fg=TH.NG if issue else TH.INK, font=(self.font, 9),
                          justify="center" if len(txt) < 30 else "left", wraplength=max(30, w - 10),
                          anchor="center", padx=4, pady=2, cursor="hand2",
                          image=photo if photo is not None else "", compound="top")
            lb.grid(row=r, column=c, rowspan=cell["rs"], columnspan=cell["cs"], sticky="nsew",
                    padx=(0, 1), pady=(0, 1))
            if p0 is not None:
                lb.bind("<Button-1>", lambda e, p=p0, l=lb: self._cell_click(p, l))
                lb.bind("<Double-Button-1>", lambda e, p=p0: self.edit_para(p))
                lb.bind("<Button-3>", lambda e, p=p0: self._para_menu(p, e))
                for p in ps:
                    self.cell_labels[p.uid] = lb
        return fr

    def _cell_click(self, p, lb):
        self.sel_para = p
        self._mark_sel(p)
        for l in getattr(self, "_sel_cells", []):
            try:
                l.config(highlightthickness=0)
            except tk.TclError:
                pass
        lb.config(highlightthickness=2, highlightbackground=TH.ORANGE, highlightcolor=TH.ORANGE)
        self._sel_cells = [lb]
        self.show_similar(p)

    def _table_text(self, obj, put, put_para, get_off, add_range):
        """아주 큰 표는 글자로 (예전 방식)"""
        for row in rc.table_rows(obj):
            put("│ ", "tbl", "bar")
            for r, c, cell in row:
                ps = [p for p in cell["paras"] if self.rep.text(p).strip() or p.uid in self.rep.edits]
                for i, p in enumerate(ps):
                    if i:
                        put(" / ", "tbl", "bar")
                    put_para(p, ("tbl",))
                if not ps:
                    put(" ", "tbl")
                put(" │ ", "tbl", "bar")
            put("\n", "tbl")

    def open_table_editor(self, t):
        TableEditor(self, t)

    def _para_at(self, event):
        idx = self.view.index(f"@{event.x},{event.y}")
        off = self.view.count("1.0", idx, "chars")
        off = off[0] if off else 0
        i = bisect.bisect_right(self.range_starts, off) - 1
        if 0 <= i < len(self.ranges):
            s, e, p = self.ranges[i]
            if s <= off <= e:
                return p
        return None

    def _mark_sel(self, p):
        self.view.tag_remove("sel_para", "1.0", "end")
        pos = self.para_pos.get(p.uid)
        if pos:
            self.view.tag_add("sel_para", f"1.0+{pos[0]}c", f"1.0+{pos[1]}c")

    def on_view_click(self, e):
        p = self._para_at(e)
        if p:
            self.sel_para = p
            self._mark_sel(p)
            self.show_similar(p)

    def on_view_double(self, e):
        p = self._para_at(e)
        if p:
            self.edit_para(p)
        return "break"

    def on_view_menu(self, e):
        p = self._para_at(e)
        if not p:
            return
        self._para_menu(p, e)

    def _para_menu(self, p, e):
        self.sel_para = p
        self._mark_sel(p)
        m = tk.Menu(self.root, tearoff=0, font=(self.font, 10))
        m.add_command(label="문단 수정…", command=lambda: self.edit_para(p))
        m.add_command(label="같은/비슷한 내용 보기", command=lambda: (self.show_similar(p), self.nb.select(self.tab_sim)))
        if p.uid in self.rep.edits:
            m.add_command(label="수정 취소 (원문으로)", command=lambda: (self.rep.clear_edit(p), self.refresh_all(True)))
        m.add_separator()
        word = p.doc.fmt == "docx"
        st = "normal" if word else "disabled"
        m.add_command(label="아래에 문단 추가…", state=st, command=lambda: self.ui_add_paragraph(p))
        m.add_command(label="아래에 표 추가…", state=st, command=lambda: self.ui_add_table(p, None))
        m.add_command(label="아래에 사진 추가…", state=st, command=lambda: self.ui_add_picture(p, None))
        m.add_command(label="클립보드 그림 붙여넣기 (Ctrl+V)", state=st, command=self.paste_image)
        if word and p.pic:
            m.add_separator()
            m.add_command(label="그림 크기…", command=lambda: self.ui_resize_picture(p))
            m.add_command(label="그림을 본문 폭에 맞추기", command=lambda: self.ui_resize_picture(p, fit=True))
        if word and p.ref is not None and id(rc._top_level(p.ref)) in self.rep.new_refs:
            m.add_command(label="새로 넣은 이 문단/표/그림 삭제", command=lambda: self.ui_delete_new(p))
        if not word:
            m.add_command(label="(추가 기능은 Word 파일에서 — 한글→Word 변환)", state="disabled")
        m.add_separator()
        m.add_command(label="텍스트 복사", command=lambda: (self.root.clipboard_clear(),
                                                        self.root.clipboard_append(self.rep.text(p))))
        m.tk_popup(e.x_root, e.y_root)

    def on_tree_menu(self, e):
        iid = self.tree.identify_row(e.y)
        sec = self.sec_by_iid.get(iid)
        if sec is None or not sec.number:
            return
        self.tree.selection_set(iid)
        word = sec.doc.fmt == "docx"
        st = "normal" if word else "disabled"
        m = tk.Menu(self.root, tearoff=0, font=(self.font, 10))
        nxt, child = self._next_numbers(sec)
        m.add_command(label=f"이 절 뒤에 새 절 추가 ({nxt})…", state=st, command=lambda: self.ui_add_section(sec, "after"))
        m.add_command(label=f"하위 절 추가 ({child})…", state=st, command=lambda: self.ui_add_section(sec, "child"))
        m.add_separator()
        m.add_command(label="이 절 끝에 표 추가…", state=st, command=lambda: self.ui_add_table(None, sec))
        m.add_command(label="이 절 끝에 사진 추가…", state=st, command=lambda: self.ui_add_picture(None, sec))
        if not word:
            m.add_separator()
            m.add_command(label="한글 파일은 읽기·검토·수정만 됩니다. 추가는 Word로 변환 후",
                          state="disabled")
        m.tk_popup(e.x_root, e.y_root)

    def goto_para(self, p):
        sec = p.section
        if sec is None:
            return
        target = sec
        if self.cur_sec is not None:   # 현재 보고 있는 절 안에 있으면 그대로
            a = self.cur_sec
            if a.doc is p.doc and any(s is sec for s in a.iter()):
                target = a
        if self.cur_sec is not target:
            self._quiet = True
            self.tree.selection_set(target.sid)
            self.root.update_idletasks()
            self._quiet = False
            self._show_ai_for(target) if not self.ai_busy and target.sid in self.ai_results else None
            self.tree.see(target.sid)
            self.cur_sec = target
            self.render_section(target)
        pos = self.para_pos.get(p.uid)
        lb = getattr(self, "cell_labels", {}).get(p.uid)
        if lb is not None and pos:
            self.view.see(f"1.0+{pos[0]}c")
            old = lb.cget("bg")
            lb.config(bg="#FBC98E")
            self.root.after(1500, lambda: lb.winfo_exists() and lb.config(bg=old))
            self.sel_para = p
            return
        if pos:
            a, b = f"1.0+{pos[0]}c", f"1.0+{pos[1]}c"
            self.view.see(b)
            self.view.see(a)
            self.view.tag_remove("flash", "1.0", "end")
            self.view.tag_add("flash", a, b)
            self.root.after(1500, lambda: self.view.tag_remove("flash", "1.0", "end"))
            self.sel_para = p
            self._mark_sel(p)

    def _goto_sel(self, tv, items, key):
        s = tv.selection()
        if not s:
            return
        it = items[int(s[0])]
        if key is None:
            p = it
        elif isinstance(key, int):
            p = it[key]
        else:
            p = getattr(it, key)
        if p is not None:
            self.goto_para(p)

    # ------------------------------------------------------------ Word: 절·문단·표·사진 추가
    def _target_sec(self):
        if self.sel_para is not None and self.sel_para.section is not None and \
                self.cur_sec is not None and self.sel_para.doc is self.cur_sec.doc:
            return self.sel_para.section
        return self.cur_sec

    def _target_para(self):
        p = self.sel_para
        if p is not None and self.cur_sec is not None and p.doc is self.cur_sec.doc:
            return p
        return None

    def _word_ok(self, sec_or_para):
        if sec_or_para is None:
            messagebox.showinfo(APP_TITLE, "왼쪽 트리에서 절을 선택하거나 본문에서 문단을 클릭하세요.")
            return False
        doc = sec_or_para.doc
        if doc.fmt != "docx":
            messagebox.showinfo(APP_TITLE, "절·표·사진 추가는 Word(.docx) 파일에서 됩니다.\n\n"
                                           "한글 파일은 '한글→Word 변환'으로 Word 파일을 만든 뒤 사용하세요.\n"
                                           "(한글 파일은 지금처럼 읽기·검사·AI 검토·수정 반영은 됩니다)")
            return False
        return True

    def _next_numbers(self, sec):
        kids = [c for c in sec.children if c.level == sec.level + 1]
        if sec.level == -1:
            after = f"제{sec.number}편 다음"
            child = f"제{int(kids[-1].number) + 1 if kids else 1}장"
        elif sec.level == 0:
            after = f"제{int(sec.number) + 1}장"
            child = f"{sec.number}.{len(kids) + 1}" if not kids else rc._bump(kids[-1].number)
        else:
            after = rc._bump(sec.number)
            child = f"{sec.number}.{len(kids) + 1}" if not kids else rc._bump(kids[-1].number)
        return after, child

    def _after_structure(self, new_el, msg):
        self.ai_results.clear()
        self.issues, self.issue_paras, self.check_items = [], set(), []
        self._fill_check()
        self.refresh_all()
        target = None
        for d in ([] if new_el is None else self.rep.docs):
            for p in d.paras:
                if p.ref is new_el:
                    target = p
                    break
        if target is not None:
            self.goto_para(target)
        self.status.set(msg + " — '파일에 반영·저장'을 눌러야 Word 파일에 저장됩니다.")

    def ui_add_section(self, sec, mode):
        if not self._word_ok(sec):
            return
        if not sec.number or sec.level == -1 and mode == "after":
            messagebox.showinfo(APP_TITLE, "장 또는 절을 선택하세요.")
            return
        nxt, child = self._next_numbers(sec)
        num = nxt if mode == "after" else child
        later = []
        if mode == "after":
            sibs = sec.parent.children if sec.parent else self.rep.roots[sec.doc.key]
            later = [x for x in sibs if x.block_idx > sec.block_idx and x.level == sec.level]
        fields = [("title", "제목", "entry", "", f"번호 {num} 은(는) 자동으로 붙습니다"),
                  ("body", "첫 문단", "text", "", "비워 두면 빈 문단이 생깁니다 (나중에 더블클릭해서 입력)")]
        if later:
            fields.append(("renumber", "번호 밀기", "check", True,
                           f"뒤에 있는 {', '.join(x.number for x in later[:4])}{'…' if len(later) > 4 else ''} 의 번호를 하나씩 뒤로"))
        where = f"'{sec.label}' 뒤" if mode == "after" else f"'{sec.label}' 의 맨 끝"
        dlg = FormDialog(self, f"새 절 추가 — {num}", fields,
                         note=f"{where}에 {num} 절을 넣습니다. 제목·본문 글씨체와 문단 모양은 같은 단계의 기존 제목/본문을 그대로 따릅니다.")
        if not dlg.result:
            return
        if not dlg.result["title"].strip():
            messagebox.showinfo(APP_TITLE, "제목을 입력하세요.")
            return
        try:
            head, body, moved = rc.add_section(self.rep, sec.doc, sec, mode, dlg.result["title"].strip(),
                                               dlg.result.get("body", ""), dlg.result.get("renumber", True))
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"절 추가 실패: {e}")
            return
        self._after_structure(head, f"{num} 절 추가" + (f" · 뒤 절 번호 {moved}개 밀림(변경 목록)" if moved else ""))

    def ui_add_paragraph(self, p):
        if not self._word_ok(p):
            return
        dlg = FormDialog(self, "문단 추가", [("text", "내용", "text", "", "비워 두면 빈 문단")],
                         note="선택한 문단 아래에 같은 모양의 본문 문단을 넣습니다.")
        if not dlg.result:
            return
        el = rc.add_paragraph(self.rep, p.doc, p, dlg.result["text"])
        self._after_structure(el, "문단 추가")

    def ui_add_table(self, p, sec):
        target = p or sec
        if not self._word_ok(target):
            return
        dlg = FormDialog(self, "표 추가", [
            ("rows", "행 수", "int", 4, "머리글 행 포함"),
            ("cols", "열 수", "int", 3, None),
            ("header", "머리글", "entry", "", "쉼표로 구분 (예: 구 분, 검토결과, 비 고) — 비워도 됨"),
            ("caption", "표 제목", "entry", "", "번호는 자동 (예: <표 5.3 지붕 검토 결과>). 비우면 제목 없이"),
            ("pos", "제목 위치", "combo:표 위/표 아래", "표 위", None)],
            note=("선택한 문단 아래" if p else f"'{sec.label}' 끝") + "에 표를 넣습니다. 테두리·글씨는 보고서의 기존 표를 본뜹니다.")
        if not dlg.result:
            return
        r = dlg.result
        if not (1 <= r["rows"] <= 200 and 1 <= r["cols"] <= 30):
            messagebox.showinfo(APP_TITLE, "행 1~200, 열 1~30 사이로 입력하세요.")
            return
        header = [h.strip() for h in r["header"].split(",")] if r["header"].strip() else None
        try:
            tbl, moved = rc.add_table(self.rep, target.doc, p, sec, r["rows"], r["cols"], header, r["caption"],
                                      "above" if r["pos"] == "표 위" else "below")
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"표 추가 실패: {e}")
            return
        first = None
        for d in self.rep.docs:
            for t in d.tables:
                if t.ref is tbl:
                    cells = [c for k, c in sorted(t.cells.items())]
                    first = cells[0]["paras"][0].ref if cells and cells[0]["paras"] else None
        self._after_structure(first if first is not None else tbl,
                              "표 추가 — 표 편집 창에서 칸을 채우세요"
                              + (f" · 뒤 표 번호 {moved}개 밀림" if moved else ""))
        for d in self.rep.docs:
            for t in d.tables:
                if t.ref is tbl:
                    self.open_table_editor(t)
                    return

    IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")

    def _thumb(self, p, max_w, scale_to_page=False):
        """Word 문단의 그림 미리보기 (PhotoImage, 캐시)"""
        if p is None or p.ref is None or p.doc.fmt != "docx":
            return None
        try:
            import io
            import docx_doc as dxd
            from PIL import Image, ImageTk
            pics = dxd.pictures_in(p.ref)
            if not pics or not pics[0]["rid"]:
                return None
            info = pics[0]
            tw, th = dxd.text_area_emu(p.doc.docx)
            w = max_w
            if scale_to_page:                            # 본문 폭 대비 실제 비율로
                w = int(max_w * min(1.0, info["cx"] / max(1, tw)))
            h = int(w * info["cy"] / max(1, info["cx"]))
            key = (p.doc.key, info["rid"], w, h)
            cache = self.__dict__.setdefault("_img_cache", {})
            if key not in cache:
                blob = dxd.image_blob(p.doc.docx, info["rid"])
                if not blob:
                    return None
                im = Image.open(io.BytesIO(blob))
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGB")
                im = im.resize((max(1, w), max(1, h)))
                cache[key] = ImageTk.PhotoImage(im, master=self.root)
            return cache[key]
        except Exception:
            return None

    def _pic_widget(self, p):
        if p.doc.fmt != "docx":
            return None
        import docx_doc as dxd
        pics = dxd.pictures_in(p.ref) if p.ref is not None else []
        avail = max(300, self.view.winfo_width() - 80)
        photo = self._thumb(p, avail, scale_to_page=True)
        if photo is None:
            return None
        cx, cy = (pics[0]["cx"], pics[0]["cy"]) if pics else (0, 0)
        tw, _ = dxd.text_area_emu(p.doc.docx)
        lb = tk.Label(self.view, image=photo, text=f"{cx / 360000:.1f} × {cy / 360000:.1f} cm  (본문 폭의 {cx / max(1, tw):.0%})",
                      compound="top", font=(self.font, 8), fg=TH.MUTED, bg=TH.PANEL, bd=1, relief="solid",
                      cursor="hand2", padx=2, pady=2)
        lb.bind("<Button-1>", lambda e: (setattr(self, "sel_para", p), self._mark_sel(p)))
        lb.bind("<Double-Button-1>", lambda e: self.ui_resize_picture(p))
        lb.bind("<Button-3>", lambda e: self._para_menu(p, e))
        return lb

    def ui_resize_picture(self, p, fit=False):
        import docx_doc as dxd
        pics = dxd.pictures_in(p.ref)
        if not pics:
            return
        cx, cy = pics[0]["cx"], pics[0]["cy"]
        tw, th = dxd.text_area_emu(p.doc.docx)
        if fit:
            ncx = tw
        else:
            dlg = FormDialog(self, "그림 크기", [
                ("width", "폭 (cm)", "float", f"{cx / 360000:.1f}", f"본문 폭 {tw / 360000:.1f} cm · 비율은 그대로 유지"),
                ("pct", "또는 본문 폭의 %", "float", "", "예: 80 (입력하면 이 값 우선)")],
                note=f"현재 {cx / 360000:.1f} × {cy / 360000:.1f} cm")
            if not dlg.result:
                return
            if dlg.result.get("pct"):
                ncx = tw * dlg.result["pct"] / 100.0
            elif dlg.result.get("width"):
                ncx = dlg.result["width"] * 360000
            else:
                return
        ncy = ncx * cy / max(1, cx)
        if ncy > th * 0.9:                               # 쪽 높이를 넘지 않게
            ncy = th * 0.9
            ncx = ncy * cx / max(1, cy)
        rc.resize_picture(self.rep, p.doc, p, ncx, ncy)
        self._after_structure(p.ref, f"그림 크기 {ncx / 360000:.1f} × {ncy / 360000:.1f} cm")

    def paste_image(self, event=None):
        """Ctrl+V: 클립보드의 그림(캡처·복사한 이미지) 또는 복사한 그림 파일을 넣기"""
        if self.mode != "word":
            self.status.set("그림 붙여넣기는 Word 작업에서 됩니다.")
            return "break"
        files = []
        try:
            from PIL import ImageGrab
            data = ImageGrab.grabclipboard()
        except Exception:
            data = None
        if isinstance(data, list):
            files = [f for f in data if str(f).lower().endswith(self.IMG_EXT)]
        elif data is not None:
            import tempfile
            import time
            tmp = os.path.join(tempfile.gettempdir(), f"보고서도우미_붙여넣기_{int(time.time() * 1000)}.png")
            try:
                if data.mode not in ("RGB", "RGBA"):
                    data = data.convert("RGB")
                data.save(tmp, "PNG")
                files = [tmp]
            except Exception:
                files = []
        if not files:
            self.status.set("클립보드에 그림이 없습니다. (화면 캡처나 그림 복사 후 Ctrl+V)")
            return "break"
        self.ui_add_picture(self._target_para(), self._target_sec(), files=files)
        return "break"

    def ui_add_picture(self, p, sec, files=None):
        target = p or sec
        if not self._word_ok(target):
            return
        files = files or filedialog.askopenfilenames(title="넣을 사진 선택", filetypes=[
            ("그림", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff"), ("모든 파일", "*.*")])
        if not files:
            return
        dlg = FormDialog(self, "사진 추가", [
            ("caption", "그림 제목", "entry", "", "번호는 자동 (예: <그림 5.2 지붕 전경>). 여러 장이면 제목 뒤에 (1), (2)…"),
            ("width", "폭 (cm)", "float", "", "비우면 보고서에 이미 있는 그림과 같은 폭 (본문 폭·쪽 높이를 넘지 않게 자동 조정)")],
            note=f"사진 {len(files)}장을 " + ("선택한 문단 아래" if p else f"'{sec.label}' 끝") + "에 넣습니다.")
        if not dlg.result:
            return
        cap = dlg.result["caption"]
        anchor_para, last_el, moved = p, None, 0
        for i, f in enumerate(files):
            title = (f"{cap} ({i + 1})" if cap and len(files) > 1 else cap)
            try:
                el, mv = rc.add_picture(self.rep, target.doc if anchor_para is None else anchor_para.doc,
                                        anchor_para, sec, f, dlg.result["width"], title)
            except Exception as e:
                messagebox.showerror(APP_TITLE, f"사진 추가 실패 ({os.path.basename(f)}): {e}")
                break
            moved += mv
            last_el = el
            # 다음 사진은 방금 넣은 사진(캡션) 뒤에
            nxt = el.getnext() if cap else el
            anchor_para = next((q for d in self.rep.docs for q in d.paras if q.ref is nxt), None)
            sec = None if anchor_para is not None else sec
        if last_el is not None:
            self._after_structure(last_el, f"사진 {len(files)}장 추가" + (f" · 뒤 그림 번호 {moved}개 밀림" if moved else ""))

    def ui_delete_new(self, p):
        if messagebox.askyesno(APP_TITLE, "새로 넣은 이 문단/표/그림을 지울까요?"):
            rc.delete_block(self.rep, p.doc, p)
            self.sel_para = None
            self._after_structure(None, "삭제")

    def convert_hwp_to_word(self):
        """한글 원본을 읽어 깔끔한 Word 를 새로 만든다 (한글 프로그램 필요 없음)"""
        import hwp_to_word
        paths = [d.path for d in self.rep.docs if d.fmt == "hwp"]
        if not paths:
            paths = list(filedialog.askopenfilenames(title="Word로 만들 한글 파일 (.hwp)",
                                                     filetypes=[("한글 문서", "*.hwp")]))
        if not paths:
            return
        if not messagebox.askyesno(APP_TITLE, f"한글 파일 {len(paths)}개를 읽어 Word 파일을 새로 만듭니다.\n\n"
                                              "· 쪽 크기·여백·쪽 나누기, 글꼴·크기, 문단 간격, 표 테두리, 그림, 머리말/꼬리말을 원본대로\n"
                                              "· 원본 한글 파일은 그대로 둡니다\n"
                                              "· 한글에서 하던 수정 대기·AI 결과는 가져가지 않습니다 (Word에서 새로 분석)\n\n진행할까요?"):
            return
        done, errs = [], []
        self.root.config(cursor="watch")
        try:
            for src in paths:
                dst = os.path.splitext(src)[0] + ".docx"
                if os.path.exists(dst):
                    a = messagebox.askyesnocancel(APP_TITLE, f"같은 이름의 Word 파일이 이미 있습니다.\n{os.path.basename(dst)}\n\n"
                                                  "덮어쓸까요?  (아니오 = '_정리.docx'로 따로 저장)")
                    if a is None:
                        continue
                    if not a:
                        dst = os.path.splitext(src)[0] + "_정리.docx"
                try:
                    self.status.set("Word 만드는 중: " + os.path.basename(src))
                    self.root.update()
                    hwp_to_word.build_docx(src, dst)
                    done.append(dst)
                except PermissionError:
                    errs.append(f"{os.path.basename(dst)}: Word에서 열려 있어 저장할 수 없습니다 (닫고 다시)")
                except Exception as e:
                    errs.append(f"{os.path.basename(src)}: {e}")
        finally:
            self.root.config(cursor="")
        if errs:
            messagebox.showwarning(APP_TITLE, "일부 실패:\n\n" + "\n".join(errs))
        if done and messagebox.askyesno(APP_TITLE, f"Word 파일 {len(done)}개를 만들었습니다.\n\n"
                                                   + "\n".join(os.path.basename(x) for x in done)
                                                   + "\n\n지금 Word 작업으로 열까요?"):
            self.open_files("word", done)

    # ------------------------------------------------------------ 수정 + 동기화
    def edit_para(self, p):
        old = self.rep.text(p)
        dlg = EditDialog(self, p)
        if dlg.saved is None or dlg.saved == old:
            return
        self.commit_changes([(p, old, dlg.saved)], "직접 수정")

    def commit_changes(self, changes, src):
        """changes: [(para, 옛 텍스트, 새 텍스트)] 적용 후 다른 곳 동기화 제안"""
        for p, old, new in changes:
            self.rep.set_edit(p, new, src)
        self.refresh_all(keep_view=True)
        try:
            cands = rc.propagation_candidates(self.rep, changes)
        except Exception as e:
            cands = []
            self.status.set(f"동기화 후보 찾기 실패: {e}")
        if cands:
            first = changes[0][0]
            dlg = PropagationDialog(self, cands, src=f"동기화 ← {short(first.section.label if first.section else '', 24)}")
            if dlg.result:
                self.refresh_all(keep_view=True)
                self.status.set(f"{len(changes)}곳 수정 + 다른 곳 {dlg.result}곳 함께 수정 (변경 목록에 대기)")
                return
        self.status.set(f"{len(changes)}곳 수정 → 변경 목록에 대기 중. '파일에 반영·저장'(Ctrl+S)을 누르면 파일에 들어갑니다.")

    # ------------------------------------------------------------ 동일 내용 탭
    def show_similar(self, p):
        t = self.rep.text(p)
        self.sim_lbl.set(f"현재 문단: {loc_of(p)}\n“{short(t, 90)}”")
        self.sim_tv.delete(*self.sim_tv.get_children())
        self.sim_items = []
        render_diff(self.sim_diff, "", "")
        if len(rc.norm_ws(t)) < 8:
            return
        for q, r in self.rep.index().similar(t, min_ratio=0.6, exclude=p.uid, limit=60):
            self.sim_items.append((q, r))
            self.sim_tv.insert("", "end", iid=str(len(self.sim_items) - 1),
                               values=("동일" if r > 0.999 else f"{r:.0%}", loc_of(q), KIND_KO.get(q.kind, "")))
        if self.sim_items:
            n_diff = sum(1 for _, r in self.sim_items if r < 0.999)
            self.sim_lbl.set(self.sim_lbl.get() + f"\n→ 비슷한 문단 {len(self.sim_items)}곳 (내용 다름 {n_diff}곳)")

    def on_sim_select(self, _=None):
        s = self.sim_tv.selection()
        if s and self.sel_para:
            q, r = self.sim_items[int(s[0])]
            render_diff(self.sim_diff, self.rep.text(q), self.rep.text(self.sel_para))

    def sim_sync(self):
        if not self.sel_para:
            return
        sel = self.sim_tv.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "맞출 문단을 목록에서 선택하세요 (Ctrl/Shift로 여러 개).")
            return
        new = self.rep.text(self.sel_para)
        n = 0
        for iid in sel:
            q, r = self.sim_items[int(iid)]
            if self.rep.text(q) != new:
                self.rep.set_edit(q, new, f"내용 맞춤 ← {short(self.sel_para.section.label if self.sel_para.section else '', 24)}")
                n += 1
        self.refresh_all(keep_view=True)
        self.show_similar(self.sel_para)
        self.status.set(f"{n}곳을 현재 문단과 같은 내용으로 맞췄습니다 (변경 목록에 대기)")

    # ------------------------------------------------------------ AI
    def _show_ai_for(self, sec):
        self.ai_sec_lbl.set(f"{os.path.basename(sec.doc.path)} › {sec.label}")
        self.ai_tv.delete(*self.ai_tv.get_children())
        self.ai_reason.set("")
        render_diff(self.ai_diff, "", "")
        res = self.ai_results.get(sec.sid)
        if not res:
            self.ai_summary.set("")
            return
        summary, sugs = res
        self.ai_summary.set(summary)
        for i, sg in enumerate(sugs):
            tags = [sg.state] if sg.state != "대기" else ([] if sg.applicable else ["comment"])
            st = sg.state if sg.applicable or sg.state != "대기" else "의견"
            self.ai_tv.insert("", "end", iid=str(i), tags=tags,
                              values=(st, sg.type, short(sg.original, 30), short(sg.suggestion, 30) or "—"))

    def update_engine_label(self):
        if hasattr(self, "engine_lbl"):
            try:
                d = make_client(self.settings).describe()
                self.engine_lbl.set("AI 엔진: " + d)
                if hasattr(self, "hd_ai"):
                    self.hd_ai.config(text="● AI " + d, fg=TH.ORANGE if self.settings.get("provider", "claude") != "claude"
                                      else "#9FD7B0")
            except Exception:
                self.engine_lbl.set("AI 엔진: (설정 필요)")

    def run_ai(self):
        sec = self.cur_sec
        if sec is None:
            messagebox.showinfo(APP_TITLE, "왼쪽 트리에서 검토할 절을 먼저 선택하세요.")
            return
        if self.ai_busy:
            return
        err = check_ai_settings(self.settings)
        if err:
            messagebox.showinfo(APP_TITLE, err)
            SettingsDialog(self)
            return
        client = make_client(self.settings)
        inc = bool(self.ai_children.get())
        self.ai_busy = True
        self.ai_btn.config(state="disabled")
        self.ai_status.set(f"AI 검토 중… ({client.describe()})" + (" — 내 PC 모델은 몇 분 걸릴 수 있습니다" if client.local else ""))

        def prog(msg):
            self.root.after(0, lambda: self.ai_status.set(msg))

        def work():
            try:
                res = rc.ai_review(self.rep, client, sec, inc, progress=prog)
                self.root.after(0, lambda: self._ai_done(sec, res, None))
            except Exception as e:
                err = str(e)
                self.root.after(0, lambda: self._ai_done(sec, None, err))
        threading.Thread(target=work, daemon=True).start()

    def _ai_done(self, sec, res, err):
        self.ai_busy = False
        self.ai_btn.config(state="normal")
        if err:
            self.ai_status.set("")
            messagebox.showerror(APP_TITLE, "AI 검토 실패\n\n" + err)
            return
        summary, sugs = res
        self.ai_results[sec.sid] = (summary, sugs)
        n_app = sum(1 for s in sugs if s.applicable)
        self.ai_status.set(f"제안 {len(sugs)}건 (바로 적용 가능 {n_app}건, 의견 {len(sugs) - n_app}건)")
        if self.cur_sec is sec:
            self._show_ai_for(sec)
            self.render_section(sec)

    def _ai_cur(self):
        if not self.cur_sec or self.cur_sec.sid not in self.ai_results:
            return None, []
        sugs = self.ai_results[self.cur_sec.sid][1]
        return sugs, [sugs[int(i)] for i in self.ai_tv.selection()]

    def on_ai_select(self, _=None):
        sugs, sel = self._ai_cur()
        if not sel:
            return
        sg = sel[0]
        self.ai_reason.set(f"[{sg.type}] {sg.reason}")
        cur = self.rep.text(sg.para)
        sp = rc.find_loose(cur, sg.original)
        if sp and sg.suggestion:
            render_diff(self.ai_diff, cur, cur[:sp[0]] + sg.suggestion + cur[sp[1]:])
        else:
            render_diff(self.ai_diff, cur, cur)
        self.goto_para(sg.para)

    def _ai_apply_list(self, sel):
        changes = {}
        skipped = 0
        for sg in sel:
            if sg.state != "대기" or not sg.applicable:
                continue
            p = sg.para
            base = changes[p.uid][2] if p.uid in changes else self.rep.text(p)
            sp = rc.find_loose(base, sg.original)
            if not sp:
                skipped += 1
                continue
            new = base[:sp[0]] + sg.suggestion + base[sp[1]:]
            old = changes[p.uid][1] if p.uid in changes else self.rep.text(p)
            changes[p.uid] = (p, old, new)
            sg.state = "적용"
        if changes:
            self.commit_changes(list(changes.values()), "AI 제안")
        if self.cur_sec:
            self._show_ai_for(self.cur_sec)
        if skipped:
            messagebox.showinfo(APP_TITLE, f"{skipped}건은 원문 위치를 찾지 못해 적용하지 않았습니다 (이미 수정된 문단일 수 있음).")

    def ai_apply(self):
        sugs, sel = self._ai_cur()
        if sel:
            self._ai_apply_list(sel)

    def ai_apply_all(self):
        sugs, _ = self._ai_cur()
        if sugs:
            n = sum(1 for s in sugs if s.state == "대기" and s.applicable)
            if n and messagebox.askyesno(APP_TITLE, f"대기 중인 제안 {n}건을 모두 적용할까요?"):
                self._ai_apply_list(sugs)

    def ai_ignore(self):
        sugs, sel = self._ai_cur()
        for sg in sel:
            if sg.state == "대기":
                sg.state = "무시"
        if self.cur_sec:
            self._show_ai_for(self.cur_sec)
            self.render_section(self.cur_sec)

    # ------------------------------------------------------------ 검사
    def run_numbering(self):
        if not self.rep.docs:
            return
        self.issues = []
        for d in self.rep.docs:
            self.issues += rc.check_numbering(self.rep, d)
        self.issue_paras = {i.para for i in self.issues if i.para}
        self.check_items = self.issues
        self._fill_check()
        n_err = sum(1 for i in self.issues if i.severity == "오류")
        self.chk_lbl.set(f"번호 검사: {len(self.issues)}건 (오류 {n_err}, 경고 {len(self.issues) - n_err}) · "
                         f"더블클릭=위치 이동")
        self.nb.select(self.tab_check)
        self.refresh_all(keep_view=True)

    def run_inconsistency(self):
        if not self.rep.docs:
            return
        self.root.config(cursor="watch")
        self.root.update()
        pairs = self.rep.index().inconsistent_pairs()
        self.root.config(cursor="")
        self.check_items = []
        for a, b, r in pairs:
            it = rc.Issue("반복 불일치", a, f"{r:.0%} 유사 — {loc_of(b)} 와(과) 조금 다름",
                          fix=self.rep.text(b))
            it.other = b
            self.check_items.append(it)
        self._fill_check()
        self.chk_lbl.set(f"반복 문단 불일치: {len(pairs)}쌍 · 위=선택 문단, 미리보기에서 차이 확인")
        self.nb.select(self.tab_check)

    def _fill_check(self):
        self.chk_tv.delete(*self.chk_tv.get_children())
        for i, it in enumerate(self.check_items):
            loc = it.para.section.label if it.para and it.para.section else ""
            if it.para and len(self.rep.docs) > 1:
                loc = os.path.basename(it.para.doc.path)[:12] + " › " + loc
            self.chk_tv.insert("", "end", iid=str(i), values=(it.kind, loc, it.message), tags=(it.severity,))

    def on_chk_select(self, _=None):
        s = self.chk_tv.selection()
        if not s:
            return
        it = self.check_items[int(s[0])]
        self.chk_msg.set(it.message)
        cur = self.rep.text(it.para)
        other = getattr(it, "other", None)
        if other is not None:
            render_diff(self.chk_diff, cur, self.rep.text(other))
            self.btn_pair_rev.state(["!disabled"])
        else:
            render_diff(self.chk_diff, cur, it.fix if it.fix else cur)
            self.btn_pair_rev.state(["disabled"])
        self.goto_para(it.para)

    def chk_fix(self, reverse=False):
        sel = [self.check_items[int(i)] for i in self.chk_tv.selection()]
        changes = []
        for it in sel:
            other = getattr(it, "other", None)
            if other is not None:
                a, b = (other, it.para) if reverse else (it.para, other)
                # a 를 b 내용으로
                changes.append((a, self.rep.text(a), self.rep.text(b)))
            elif it.fix and it.fix != self.rep.text(it.para):
                changes.append((it.para, self.rep.text(it.para), it.fix))
        if not sel:
            messagebox.showinfo(APP_TITLE, "목록에서 고칠 항목을 먼저 선택하세요 (Ctrl/Shift로 여러 개).")
            return
        if not changes:
            messagebox.showinfo(APP_TITLE, "선택한 항목은 이미 수정했거나, 자동으로 고칠 수 있는 제안이 없는 항목입니다.\n"
                                           "(캡션 번호 '건너뜀/중복' 등은 위치로 이동해 직접 수정하세요)")
            return
        self.commit_changes(changes, "검사 결과 수정")
        for i in self.chk_tv.selection():
            self.chk_tv.item(i, tags=("done",))

    # ------------------------------------------------------------ 공통 항목
    def _fill_common(self):
        self.cm_tv.delete(*self.cm_tv.get_children())
        for i, (k, v) in enumerate(self.rep.common):
            occ = rc.value_occurrences(self.rep, v)
            ex = sum(1 for o in occ if o[2])
            bad = len(occ) - ex
            self.cm_tv.insert("", "end", iid=str(i), values=(k, v, f"{ex}" + (f" / ⚠{bad}" if bad else "")),
                              tags=("warn",) if bad else ())

    def on_common_select(self, _=None):
        s = self.cm_tv.selection()
        self.occ_tv.delete(*self.occ_tv.get_children())
        self.occ_items = []
        if not s:
            return
        k, v = self.rep.common[int(s[0])]
        for p, m, exact in rc.value_occurrences(self.rep, v):
            self.occ_items.append((p, m, exact))
            self.occ_tv.insert("", "end", iid=str(len(self.occ_items) - 1), values=(loc_of(p), m),
                               tags=() if exact else ("warn",))

    def common_extract(self):
        found = rc.extract_common(self.rep)
        have = {k for k, _ in self.rep.common}
        add = [kv for kv in found if kv[0] not in have]
        self.rep.common += add
        self._fill_common()
        self._save_state_quiet()
        self.status.set(f"공통 항목 {len(add)}개 추가")

    def common_add(self):
        k = simpledialog.askstring(APP_TITLE, "항목 이름 (예: 준공연도)", parent=self.root)
        if not k:
            return
        v = simpledialog.askstring(APP_TITLE, f"'{k}' 값 (보고서에 쓰인 그대로)", parent=self.root)
        if v:
            self.rep.common.append([k.strip(), v.strip()])
            self._fill_common()
            self._save_state_quiet()

    def common_del(self):
        s = self.cm_tv.selection()
        for i in sorted((int(x) for x in s), reverse=True):
            del self.rep.common[i]
        self._fill_common()
        self._save_state_quiet()

    def common_change(self):
        s = self.cm_tv.selection()
        if not s:
            messagebox.showinfo(APP_TITLE, "바꿀 항목을 선택하세요.")
            return
        i = int(s[0])
        k, v = self.rep.common[i]
        new = simpledialog.askstring(APP_TITLE, f"'{k}' 새 값\n(현재: {v})", initialvalue=v, parent=self.root)
        if not new or new == v:
            return
        cands = {}
        for p, m, exact in rc.value_occurrences(self.rep, v):
            cur = cands[p.uid].new_text if p.uid in cands else self.rep.text(p)
            nt = cur.replace(m, new)
            why = ("정확히 일치" if exact else f"비슷한 표기 '{m}' (확인 필요)") + f" → '{new}'"
            if p.uid in cands:
                cands[p.uid].new_text = nt
                cands[p.uid].reason += " / " + why
            else:
                cands[p.uid] = rc.Candidate(p, self.rep.text(p), nt, why, 1.0 if exact else 0.5, exact)
        self.rep.common[i] = [k, new]
        if cands:
            dlg = PropagationDialog(self, list(cands.values()), title=f"공통 항목 변경: {k}",
                                    note=f"'{v}' → '{new}'  사용처 {len(cands)}곳. 바꿀 곳을 선택하세요.",
                                    src=f"공통 항목({k})")
            self.status.set(f"'{k}' 값 변경 — {dlg.result}곳 수정 (변경 목록에 대기)")
        self.refresh_all(keep_view=True)

    # ------------------------------------------------------------ 변경 목록
    def _fill_list(self):
        self.ls_tv.delete(*self.ls_tv.get_children())
        self.list_items = []
        order = {d.key: i for i, d in enumerate(self.rep.docs)}
        items = [self.rep.paras[u] for u in self.rep.edits if u in self.rep.paras]
        items.sort(key=lambda p: (order.get(p.doc.key, 0), p.seq))
        for p in items:
            self.list_items.append(p)
            self.ls_tv.insert("", "end", iid=str(len(self.list_items) - 1),
                              values=(loc_of(p), short(self.rep.text(p), 60), self.rep.edit_src.get(p.uid, "")))

    def on_list_select(self, _=None):
        s = self.ls_tv.selection()
        if s:
            p = self.list_items[int(s[0])]
            render_diff(self.ls_diff, p.orig, self.rep.text(p))

    def list_undo(self):
        for i in self.ls_tv.selection():
            self.rep.clear_edit(self.list_items[int(i)])
        self.refresh_all(keep_view=True)

    def list_export(self):
        if not self.rep.edits:
            return
        f = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV (엑셀)", "*.csv")],
                                         initialfile="보고서_변경목록.csv")
        if f:
            rc.export_changes_csv(self.rep, f)
            self.status.set("저장: " + f)

    # ------------------------------------------------------------ 한글 반영
    def apply_to_hwp(self, only_word=False):
        """Word 파일은 바로 저장, 한글 파일은 한글 자동화로 반영"""
        has_edit = lambda d: any(p.uid in self.rep.edits for p in d.paras)
        words = [d for d in self.rep.docs if d.fmt == "docx" and (d.dirty or has_edit(d))]
        hwps = [] if only_word else [d for d in self.rep.docs if d.fmt != "docx" and has_edit(d)]
        if not words and not hwps:
            messagebox.showinfo(APP_TITLE, "반영할 수정 사항이 없습니다.")
            return
        log, ok_total, fail_total = [], 0, 0
        if words:
            if not messagebox.askyesno(APP_TITLE, f"Word 파일 {len(words)}개를 저장합니다.\n"
                                       "원본은 '_백업' 폴더에 복사한 뒤 저장합니다.\n"
                                       "Word에서 열려 있으면 먼저 닫아 주세요.\n\n진행할까요?"):
                return
            for d in words:
                try:
                    ok, fail = rc.save_word(self.rep, d)
                    ok_total += ok
                    fail_total += len(fail)
                    log.append(f"■ {os.path.basename(d.path)} — 저장 완료 (문단 수정 {ok}개"
                               + (f", 실패 {len(fail)}개" if fail else "") + ")")
                except Exception as e:
                    log.append(f"■ {os.path.basename(d.path)} — 저장 실패: {e}")
                    messagebox.showerror(APP_TITLE, str(e))
            self.rep.new_refs.clear()
            if not hwps:
                self.ai_results.clear()
                self.refresh_all()
                self._show_result(ok_total, fail_total, [], log)
                return
        self._apply_hwp_docs(hwps, log, ok_total, fail_total)

    def _apply_hwp_docs(self, hwps, log, ok_total, fail_total):
        if not rc.HwpApplier.available():
            if messagebox.askyesno(APP_TITLE, "이 PC에서는 한글 자동화를 사용할 수 없습니다.\n"
                                              "(Windows + 한글 설치 + 'pip install pywin32' 필요)\n\n"
                                              "대신 변경 목록을 CSV로 내보낼까요?"):
                self.list_export()
            return
        plans = []
        n_auto = n_man = 0
        for d in hwps:
            reps, man = rc.plan_changes(self.rep, d)
            plans.append((d, reps, man))
            n_auto += len({id(p) for r in reps for p in r.paras})
            n_man += len(man)
        msg = (f"한글 파일 {len(plans)}개에 반영합니다.\n\n"
               f" · 자동 반영: 문단 {n_auto}개\n"
               f" · 수동 확인 필요: 문단 {n_man}개 (같은 문구가 여러 번 있거나 표·탭 경계에 걸친 경우)\n\n"
               f"원본은 각 폴더의 '_백업'에 복사한 뒤 수정합니다.\n"
               f"반영할 파일이 한글에서 열려 있다면 먼저 닫아주세요.\n\n진행할까요?")
        if not messagebox.askyesno(APP_TITLE, msg):
            return
        manual_all = []
        self.root.config(cursor="watch")
        self.root.update()
        app = None
        try:
            app = rc.HwpApplier(visible=self.settings.get("hwp_visible", False))
            for d, reps, man in plans:
                manual_all += man
                if not reps:
                    continue
                expected = {}
                for r in reps:
                    for p in r.paras:
                        expected[p.seq] = self.rep.edits.get(p.uid, "")
                bk = rc.backup_file(d.path)
                log.append(f"■ {os.path.basename(d.path)}  (백업: {os.path.basename(bk)})")
                self.status.set("반영 중: " + os.path.basename(d.path))
                self.root.update()
                app.apply(d.path, reps, log=log.append)
                newdoc, kept = self.rep.reload(d)
                ok, fail = rc.verify_after_apply(self.rep, newdoc, expected)
                ok_total += len(ok)
                fail_total += len(fail)
                if fail:
                    log.append(f"  ⚠ 확인 실패 문단 {len(fail)}개 — 변경 목록에 남아 있습니다")
        except Exception as e:
            log.append("오류: " + str(e))
            messagebox.showerror(APP_TITLE, "한글 반영 중 오류:\n\n" + str(e))
        finally:
            if app:
                app.quit()
            self.root.config(cursor="")
        self.ai_results.clear()
        self.refresh_all()
        self._show_result(ok_total, fail_total, manual_all, log)

    def _show_result(self, ok, fail, manual, log):
        w = tk.Toplevel(self.root)
        w.title("반영 결과")
        w.geometry("820x520")
        ttk.Label(w, text=f"반영 완료 {ok}개 · 확인 실패 {fail}개 · 수동 처리 {len(manual)}개",
                  font=(self.font, 11, "bold")).pack(anchor="w", padx=10, pady=8)
        bf = ttk.Frame(w)
        bf.pack(side="bottom", fill="x", padx=10, pady=8)
        t = tk.Text(w, wrap="word", font=(self.font, 10), height=10)
        t.pack(fill="both", expand=True, padx=10)
        t.insert("end", "\n".join(log))
        if manual:
            t.insert("end", "\n\n■ 수동으로 고쳐야 하는 문단 (변경 목록에 남아 있음)\n")
            for m in manual:
                t.insert("end", f"\n[{loc_of(m.para)}] ({m.why})\n  원문: {m.para.orig}\n  수정: {self.rep.text(m.para)}\n")
        ttk.Button(bf, text="닫기", command=w.destroy).pack(side="right")
        if manual:
            def exp():
                f = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="수동처리_목록.csv",
                                                 filetypes=[("CSV (엑셀)", "*.csv")])
                if f:
                    rc.export_changes_csv(self.rep, f, manual_only=manual)
            ttk.Button(bf, text="수동 처리 목록 CSV", command=exp).pack(side="right", padx=6)


def open_report_design(parent=None, username=""):
    """StrCAD 런처 등 다른 프로그램에서 창으로 열기. → App"""
    win = tk.Toplevel(parent) if parent is not None else tk.Tk()
    app = App(win, embedded=parent is not None, username=username)
    try:
        win.lift()
        win.focus_force()
    except Exception:
        pass
    return app


def main():
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    app = App(root)
    files = [f for f in sys.argv[1:] if f.lower().endswith((".hwp", ".hwpx", ".docx"))]
    if files:
        mode = "word" if files[0].lower().endswith(".docx") else "hwp"
        root.after(100, lambda: app.open_files(mode, files))
    root.mainloop()


if __name__ == "__main__":
    main()
