"""dialogs.py — 가져오기 확인 · 열 매핑 · DXF 출력 설정 · 진행 창 · 도움말"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from . import model as M
from . import table_io as TI
from . import theme as T


def _btn(parent, text, cmd, primary=False):
    b = tk.Button(parent, text=text, command=cmd, font=T.F_UI_B, relief="flat", cursor="hand2", padx=14, pady=4,
                  bg=T.ORANGE if primary else T.NAVY_2, fg="white", activebackground=T.ORANGE_D, activeforeground="white")
    return b


class _Modal(tk.Toplevel):
    def __init__(self, parent, title, size="720x520"):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=T.SURFACE)
        self.geometry(size)
        self.transient(parent)
        self.result = None
        T.set_icon(self)
        self.bind("<Escape>", lambda e: self.destroy())

    def run(self):
        self.update_idletasks()
        p = self.master
        try:
            x = p.winfo_rootx() + (p.winfo_width() - self.winfo_width()) // 2
            y = p.winfo_rooty() + (p.winfo_height() - self.winfo_height()) // 3
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except tk.TclError:
            pass
        self.grab_set()
        self.focus_set()
        self.wait_window()
        return self.result

    def footer(self, ok_text="확인"):
        f = tk.Frame(self, bg=T.SURFACE)
        f.pack(side="bottom", fill="x", padx=12, pady=10)
        _btn(f, ok_text, self.ok, True).pack(side="right")
        _btn(f, "취소", self.destroy).pack(side="right", padx=6)
        return f

    def ok(self):
        self.destroy()


# ═══════════════════════════════════════════════════════════════════
#  진행 창 (오래 걸리는 작업을 스레드로)
# ═══════════════════════════════════════════════════════════════════
def run_task(parent, title, fn):
    """fn(log) 을 백그라운드에서 실행 → 결과 반환 (예외는 다시 발생)."""
    q = queue.Queue()
    box = {}
    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(bg=T.PANEL)
    win.geometry("460x170")
    win.transient(parent)
    win.resizable(False, False)
    T.set_icon(win)
    tk.Label(win, text=title, font=T.F_UI_B, bg=T.PANEL, fg=T.NAVY).pack(anchor="w", padx=14, pady=(12, 4))
    pb = ttk.Progressbar(win, mode="indeterminate", length=420)
    pb.pack(padx=14, pady=4)
    pb.start(12)
    msg = tk.Label(win, text="", font=T.F_SMALL, bg=T.PANEL, fg=T.MUTED, anchor="w", justify="left", wraplength=420)
    msg.pack(fill="x", padx=14, pady=4)
    win.protocol("WM_DELETE_WINDOW", lambda: None)

    def work():
        try:
            box["res"] = fn(lambda s: q.put(str(s)))
        except Exception as e:                        # noqa: BLE001
            box["err"] = e
        q.put(None)

    th = threading.Thread(target=work, daemon=True)
    th.start()
    done = {"v": False}

    def poll():
        try:
            while True:
                s = q.get_nowait()
                if s is None:
                    done["v"] = True
                    win.destroy()
                    return
                msg.config(text=s.strip())
        except queue.Empty:
            pass
        win.after(120, poll)

    win.after(120, poll)
    win.grab_set()
    parent.wait_window(win)
    if "err" in box:
        raise box["err"]
    return box.get("res")


# ═══════════════════════════════════════════════════════════════════
#  가져오기 옵션 (부재 종류 · PDF 쪽 · 원근 보정)
# ═══════════════════════════════════════════════════════════════════
class ImportOptions(_Modal):
    def __init__(self, parent, kind, pages=1):
        super().__init__(parent, f"가져오기 — {kind}", "420x260")
        body = tk.Frame(self, bg=T.SURFACE)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        tk.Label(body, text="부재 종류", font=T.F_UI_B, bg=T.SURFACE).grid(row=0, column=0, sticky="w", pady=6)
        self.want = tk.StringVar(value="자동 판별")
        ttk.Combobox(body, textvariable=self.want, state="readonly", width=16,
                     values=["자동 판별"] + [M.TYPES[t]["title"] for t in M.TYPES]).grid(row=0, column=1, sticky="w")
        self.page = tk.IntVar(value=1)
        self.flat = tk.BooleanVar(value=True)
        r = 1
        if pages > 1:
            tk.Label(body, text=f"PDF 쪽 (1~{pages})", font=T.F_UI_B, bg=T.SURFACE).grid(row=r, column=0, sticky="w", pady=6)
            tk.Spinbox(body, from_=1, to=pages, textvariable=self.page, width=6).grid(row=r, column=1, sticky="w")
            r += 1
        if kind == "사진":
            tk.Checkbutton(body, text="용지 모서리 찾아 원근 보정", variable=self.flat, bg=T.SURFACE,
                           font=T.F_UI).grid(row=r, column=0, columnspan=2, sticky="w", pady=6)
            r += 1
            tk.Label(body, text="· 표가 반듯하게, 글자가 선명하게 찍힌 사진일수록 잘 읽습니다.\n"
                                "· 한글(양단부·상부근 등)은 읽지 못해 칸 위치로 판단합니다.\n· 가져온 뒤 값을 꼭 확인하세요.",
                     font=T.F_SMALL, bg=T.SURFACE, fg=T.MUTED, justify="left").grid(row=r, column=0, columnspan=2, sticky="w")
        self.footer("가져오기")

    def ok(self):
        w = self.want.get()
        self.result = {"want": next((t for t in M.TYPES if M.TYPES[t]["title"] == w), "auto"),
                       "page": max(0, self.page.get() - 1), "flatten": self.flat.get()}
        self.destroy()


# ═══════════════════════════════════════════════════════════════════
#  가져온 결과 확인
# ═══════════════════════════════════════════════════════════════════
class ImportResult(_Modal):
    def __init__(self, parent, res, warn, source, existing):
        super().__init__(parent, "가져오기 결과 확인", "860x560")
        self.res = res
        top = tk.Frame(self, bg=T.SURFACE)
        top.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(top, text=source, font=T.F_UI_B, bg=T.SURFACE, fg=T.NAVY).pack(side="left")
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=4)
        self.use = {}
        for t, rows in res.items():
            f = tk.Frame(nb, bg=T.PANEL)
            nb.add(f, text=f" {M.TYPES[t]['title']}  {len(rows)}개 ")
            self.use[t] = tk.BooleanVar(value=True)
            cs = [c for c in M.cols(t) if c.key != "note"]
            tv = ttk.Treeview(f, columns=[c.key for c in cs], show="headings", height=14)
            for c in cs:
                tv.heading(c.key, text=c.full_title)
                tv.column(c.key, width=max(52, int(c.width * 0.9)), anchor="center", stretch=False)
            for r in rows:
                tv.insert("", "end", values=[("" if M.disabled(t, r, c.key) else r.get(c.key, "")) for c in cs])
            sb = ttk.Scrollbar(f, orient="horizontal", command=tv.xview)
            tv.configure(xscrollcommand=sb.set)
            sb.pack(side="bottom", fill="x")
            tv.pack(fill="both", expand=True)
        if warn:
            wf = tk.Frame(self, bg=T.SURFACE)
            wf.pack(fill="x", padx=12)
            tk.Label(wf, text="확인할 점", font=T.F_UI_B, bg=T.SURFACE, fg=T.ORANGE_D).pack(anchor="w")
            txt = tk.Text(wf, height=min(5, len(warn) + 1), font=T.F_SMALL, bg="#FFF8EE", relief="flat")
            txt.insert("1.0", "\n".join("· " + w for w in warn[:60]))
            txt.config(state="disabled")
            txt.pack(fill="x")
        opt = tk.Frame(self, bg=T.SURFACE)
        opt.pack(fill="x", padx=12, pady=6)
        self.mode = tk.StringVar(value="replace" if not any(existing.get(t) for t in res) else "append")
        tk.Label(opt, text="넣는 방법:", font=T.F_UI_B, bg=T.SURFACE).pack(side="left")
        tk.Radiobutton(opt, text="기존 목록 뒤에 추가", value="append", variable=self.mode, bg=T.SURFACE, font=T.F_UI).pack(side="left", padx=6)
        tk.Radiobutton(opt, text="기존 목록 바꾸기", value="replace", variable=self.mode, bg=T.SURFACE, font=T.F_UI).pack(side="left")
        if len(res) > 1:
            for t in res:
                tk.Checkbutton(opt, text=M.TYPES[t]["title"], variable=self.use[t], bg=T.SURFACE, font=T.F_UI).pack(side="right")
        self.footer("넣기")

    def ok(self):
        self.result = {"types": [t for t, v in self.use.items() if v.get()], "mode": self.mode.get()}
        self.destroy()


# ═══════════════════════════════════════════════════════════════════
#  엑셀 / TXT 열 매핑
# ═══════════════════════════════════════════════════════════════════
class MappingDialog(_Modal):
    NONE = "(없음)"

    def __init__(self, parent, grids, mtype="beam", pfx="D", title="표 가져오기"):
        super().__init__(parent, title, "1060x640")
        self.grids = grids
        self.pfx = pfx
        top = tk.Frame(self, bg=T.SURFACE)
        top.pack(fill="x", padx=12, pady=8)
        tk.Label(top, text="시트", font=T.F_UI_B, bg=T.SURFACE).pack(side="left")
        self.sheet = tk.StringVar(value=list(grids)[0])
        cb = ttk.Combobox(top, textvariable=self.sheet, values=list(grids), state="readonly", width=22)
        cb.pack(side="left", padx=(4, 14))
        cb.bind("<<ComboboxSelected>>", lambda e: self._auto())
        tk.Label(top, text="부재 종류", font=T.F_UI_B, bg=T.SURFACE).pack(side="left")
        self.mtype = tk.StringVar(value=M.TYPES[mtype]["title"])
        cb2 = ttk.Combobox(top, textvariable=self.mtype, values=[M.TYPES[t]["title"] for t in M.TYPES], state="readonly", width=8)
        cb2.pack(side="left", padx=(4, 14))
        cb2.bind("<<ComboboxSelected>>", lambda e: self._auto())
        tk.Label(top, text="머리글 줄", font=T.F_UI_B, bg=T.SURFACE).pack(side="left")
        self.hrow = tk.IntVar(value=1)
        sp = tk.Spinbox(top, from_=1, to=200, textvariable=self.hrow, width=5, command=self._manual_header)
        sp.pack(side="left", padx=(4, 14))
        sp.bind("<Return>", lambda e: self._manual_header())
        self.long = tk.BooleanVar(value=False)
        tk.Checkbutton(top, text="MIDAS 형 (위치 I/M/J 열 → 한 부재 여러 줄)", variable=self.long, bg=T.SURFACE,
                       font=T.F_UI, command=self._rebuild_map).pack(side="left")
        tk.Label(self, text="위: 파일 미리보기 (주황 = 머리글 줄)   아래: 각 항목에 쓸 열을 고르세요 — 자동으로 고른 것을 확인만 하면 됩니다.",
                 font=T.F_SMALL, bg=T.SURFACE, fg=T.MUTED).pack(anchor="w", padx=12)
        pv = tk.Frame(self, bg=T.PANEL)
        pv.pack(fill="both", expand=True, padx=12, pady=4)
        self.tv = ttk.Treeview(pv, show="headings", height=12)
        xs = ttk.Scrollbar(pv, orient="horizontal", command=self.tv.xview)
        ys = ttk.Scrollbar(pv, orient="vertical", command=self.tv.yview)
        self.tv.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
        xs.pack(side="bottom", fill="x")
        ys.pack(side="right", fill="y")
        self.tv.pack(fill="both", expand=True)
        self.tv.tag_configure("hdr", background=T.ORANGE_L)
        self.mapf = tk.Frame(self, bg=T.SURFACE)
        self.mapf.pack(fill="x", padx=12, pady=4)
        self.vars = {}
        self.footer("가져오기")
        self._auto()

    def _grid(self):
        return self.grids[self.sheet.get()]

    def _t(self):
        return next(t for t in M.TYPES if M.TYPES[t]["title"] == self.mtype.get())

    def _auto(self):
        g = self._grid()
        h, hdr, mp, lf = TI.detect_header(g, self._t(), None if self._t() == "beam" else False)
        self.long.set(lf)
        self.hrow.set(max(1, h + 1))
        self._fill_preview()
        self._rebuild_map(mp)

    def _manual_header(self):
        g = self._grid()
        h = max(0, self.hrow.get() - 1)
        idx = TI._alias_index(self._t(), self.long.get())
        mp = {}
        for hdr in (g[h] if h < len(g) else [], TI._combine(g, h) if h < len(g) else []):
            for i, v in enumerate(hdr):
                k = idx.get(TI.hkey(v))
                if k and k not in mp:
                    mp[k] = i
        self._fill_preview()
        self._rebuild_map(mp)

    def _labels(self):
        g = self._grid()
        h = max(0, self.hrow.get() - 1)
        hdr = TI._combine(g, h) if h < len(g) else []
        n = max((len(r) for r in g[:300]), default=0)
        return [self.NONE] + [f"{_col(i)}: {hdr[i] if i < len(hdr) else ''}" for i in range(n)]

    def _fill_preview(self):
        g = self._grid()
        n = max((len(r) for r in g[:300]), default=0)
        self.tv.delete(*self.tv.get_children())
        cols = [f"c{i}" for i in range(n)]
        self.tv["columns"] = cols
        for i, c in enumerate(cols):
            self.tv.heading(c, text=_col(i))
            self.tv.column(c, width=92, stretch=False, anchor="center")
        h = max(0, self.hrow.get() - 1)
        for ri, row in enumerate(g[:200]):
            self.tv.insert("", "end", values=row + [""] * (n - len(row)), tags=("hdr",) if ri == h else ())

    def _rebuild_map(self, mp=None):
        if mp is None:
            mp = {k: self._idx(v.get()) for k, v in self.vars.items()}
        for w in self.mapf.winfo_children():
            w.destroy()
        self.vars = {}
        labels = self._labels()
        targets = [(c.key, c.full_title) for c in M.cols(self._t())]
        if self.long.get() and self._t() == "beam":
            targets = [(k, t) for k, t in targets if not k[:2] in ("e_", "m_", "j_") and k != "kind"]
            targets += [("@loc", "위치(I/M/J)"), ("@top", "상부근"), ("@bot", "하부근"), ("@stir", "늑근")]
        for i, (k, title) in enumerate(targets):
            r, c = divmod(i, 5)
            f = tk.Frame(self.mapf, bg=T.SURFACE)
            f.grid(row=r, column=c, sticky="w", padx=4, pady=2)
            tk.Label(f, text=title, font=T.F_SMALL, bg=T.SURFACE, width=16, anchor="w").pack(side="left")
            v = tk.StringVar(value=labels[mp[k] + 1] if mp.get(k) is not None and mp[k] + 1 < len(labels) else self.NONE)
            ttk.Combobox(f, textvariable=v, values=labels, state="readonly", width=16).pack(side="left")
            self.vars[k] = v

    def _idx(self, label):
        if not label or label == self.NONE:
            return None
        s = label.split(":")[0]
        n = 0
        for ch in s:
            n = n * 26 + (ord(ch) - 64)
        return n - 1

    def ok(self):
        mp = {k: self._idx(v.get()) for k, v in self.vars.items()}
        if mp.get("name") is None:
            from tkinter import messagebox
            messagebox.showwarning("가져오기", "'부호' 열을 골라 주세요.", parent=self)
            return
        rows = TI.apply_mapping(self._grid(), max(0, self.hrow.get() - 1), mp, self._t(), self.long.get(), self.pfx)
        self.result = (self._t(), rows)
        self.destroy()


def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


# ═══════════════════════════════════════════════════════════════════
#  DXF 출력 설정
# ═══════════════════════════════════════════════════════════════════
class ExportDxfDialog(_Modal):
    def __init__(self, parent, project, mtype, default_tpl):
        super().__init__(parent, "CAD(DXF) 내보내기", "620x560")
        self.project = project
        meta = project.meta
        body = tk.Frame(self, bg=T.SURFACE)
        body.pack(fill="both", expand=True, padx=16, pady=10)
        row = 0

        def lab(t):
            nonlocal row
            tk.Label(body, text=t, font=T.F_UI_B, bg=T.SURFACE).grid(row=row, column=0, sticky="nw", pady=5)

        lab("내보낼 부재")
        self.types = {}
        tf = tk.Frame(body, bg=T.SURFACE)
        tf.grid(row=row, column=1, sticky="w")
        for t in M.TYPES:
            n = project.count(t)
            v = tk.BooleanVar(value=(t == mtype and n > 0))
            self.types[t] = v
            tk.Checkbutton(tf, text=f"{M.TYPES[t]['title']} ({n})", variable=v, bg=T.SURFACE, font=T.F_UI,
                           state="normal" if n else "disabled").pack(side="left")
        row += 1
        lab("시트 양식")
        self.tpl = tk.StringVar()
        opts = []
        if meta.get("template"):
            opts.append(("원본 도면 양식 (가져온 DXF)", meta["template"]))
        opts.append(("기본 양식 (A3 보 일람표)", default_tpl))
        self._tpl_opts = opts
        self.tpl.set(opts[0][0])
        tf2 = tk.Frame(body, bg=T.SURFACE)
        tf2.grid(row=row, column=1, sticky="w")
        self.tpl_cb = ttk.Combobox(tf2, textvariable=self.tpl, values=[o[0] for o in opts] + ["다른 DXF 파일…"],
                                   state="readonly", width=34)
        self.tpl_cb.pack(side="left")
        self.tpl_cb.bind("<<ComboboxSelected>>", self._pick_tpl)
        row += 1
        lab("도면 번호 (첫 장)")
        self.dno = tk.StringVar(value=meta.get("drawing_no", "") or "S-101")
        tk.Entry(body, textvariable=self.dno, width=14, font=T.F_UI).grid(row=row, column=1, sticky="w")
        row += 1
        lab("프로젝트명\n(비우면 양식 그대로)")
        pj = (meta.get("project") or ["", ""]) + ["", ""]
        self.p1 = tk.StringVar(value=pj[0])
        self.p2 = tk.StringVar(value=pj[1])
        pf = tk.Frame(body, bg=T.SURFACE)
        pf.grid(row=row, column=1, sticky="w")
        tk.Entry(pf, textvariable=self.p1, width=40, font=T.F_UI).pack(anchor="w")
        tk.Entry(pf, textvariable=self.p2, width=40, font=T.F_UI).pack(anchor="w", pady=2)
        row += 1
        lab("NOTE")
        self.notes = tk.Text(body, width=46, height=7, font=T.F_UI)
        self.notes.insert("1.0", "\n".join(meta.get("notes") or []))
        self.notes.grid(row=row, column=1, sticky="w")
        row += 1
        tk.Label(body, text="· 보 4단×3부재 = 시트당 12개, 기둥 시트당 27개, 벽·슬래브는 표 형식\n"
                            "· 큰 단면은 칸에 맞게 줄여 그리고 치수 글자는 실제 값으로 씁니다.\n"
                            "· 여러 종류를 고르면 종류별로 파일을 따로 저장합니다 (이름_보.dxf …).",
                 font=T.F_SMALL, bg=T.SURFACE, fg=T.MUTED, justify="left").grid(row=row, column=0, columnspan=2, sticky="w", pady=8)
        self.footer("저장 위치 고르기…")

    def _pick_tpl(self, e=None):
        if self.tpl.get() == "다른 DXF 파일…":
            p = filedialog.askopenfilename(parent=self, title="양식으로 쓸 DXF", filetypes=[("DXF", "*.dxf")])
            if p:
                import os
                name = f"파일: {os.path.basename(p)}"
                self._tpl_opts.append((name, p))
                self.tpl_cb["values"] = [o[0] for o in self._tpl_opts] + ["다른 DXF 파일…"]
                self.tpl.set(name)
            else:
                self.tpl.set(self._tpl_opts[0][0])

    def ok(self):
        types = [t for t, v in self.types.items() if v.get()]
        if not types:
            return
        tpl = next((p for n, p in self._tpl_opts if n == self.tpl.get()), self._tpl_opts[-1][1])
        notes = [ln for ln in self.notes.get("1.0", "end").rstrip("\n").split("\n")]
        notes = [] if not any(n.strip() for n in notes) else notes
        self.result = {"types": types, "template": tpl, "drawing_no": self.dno.get().strip(),
                       "project": [self.p1.get().strip(), self.p2.get().strip()], "notes": notes}
        self.destroy()


HELP = """키 조작 (엑셀과 같음)

  ←↑→↓            칸 이동 — 값을 치는 중에도 방향키로 바로 다음 칸
  Shift+방향키     범위 선택           Ctrl+방향키   자료 끝으로
  Enter / Tab      확정 후 아래 / 오른쪽     Shift+Tab  왼쪽
  Shift+Enter      이 값을 아래 칸에 복사하고 내려감
  Alt+Enter        행 복제 (부호 번호 +1: B1 → B2)
  F2 / 더블클릭     칸 안에서 고치기 (←→ 로 글자 사이 이동)
  Esc              입력 취소
  Delete           선택 범위 지우기
  Ctrl+C / X / V   복사 / 잘라내기 / 붙여넣기 — 엑셀 표를 통째로 붙여넣을 수 있음
  Ctrl+D / Ctrl+R  아래로 / 오른쪽으로 채우기
  Ctrl+Z / Ctrl+Y  되돌리기 / 다시
  Ctrl+ +  /  -    행 삽입 / 선택 행 삭제        Alt+↑ / ↓   행 옮기기
  F4               선택 칸 강종 바꾸기 (D → HD → SHD → UHD → SD)
  마지막 '＋ 새 부재' 줄에 쓰면 윗 행을 이어받은 새 행이 생깁니다.

빠르게 쓰기
  · 철근은 숫자만:  3-22 → 3-D22,   5/2-22 → 5/2-D22 (2단),   10@200 → D10@200
    (붙는 기호는 위 '강종' 선택값)
  · '구분'·'형태' 칸은 숫자키 1/2/3 또는 Space 로 고름
  · 보 '구분'이 전단면이면 중앙부·내단부 칸은 회색(출력 안 함)
  · '-' 는 '확인 불가/없음' 표시로 그대로 출력됩니다.
  · Ctrl+S 저장 · Ctrl+O 열기 · Ctrl+N 새로
"""


class HelpDialog(_Modal):
    def __init__(self, parent):
        super().__init__(parent, "Auto Table 도움말", "620x600")
        t = tk.Text(self, font=(T.MONO, 10), bg=T.PANEL, relief="flat", padx=14, pady=10)
        t.insert("1.0", HELP)
        t.config(state="disabled")
        t.pack(fill="both", expand=True, padx=8, pady=8)
        f = tk.Frame(self, bg=T.SURFACE)
        f.pack(fill="x", padx=12, pady=8)
        _btn(f, "닫기", self.destroy, True).pack(side="right")
