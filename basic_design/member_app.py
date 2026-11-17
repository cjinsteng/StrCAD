"""
basic_design/member_app.py
Basic Design 부재 설계 창의 공통 틀

  상단   제목 · 새 파일 / 열기 / 저장 / 다른 이름으로 / 출력(A4)
  왼쪽   부재 목록 (Memb List) — 추가 · 복제 · 삭제 · 순서 이동, 경계를 끌어 폭 조절
  가운데 입력 패널  (하위 클래스가 build_inputs 로 만든다)
  오른쪽 계산서     (report.render)
  출력   A4 PDF (pdf_out)

하위 클래스가 정할 것
  TITLE, BADGE, SUBTITLE, MODULE, FILE_EXT, FILE_DESC, DEFAULT_FILE, PRINT_HEADER, FOOTER, DEFAULTS
  InputError                     입력 오류 예외 클래스
  build_inputs(parent)           입력 위젯 (self.v[key] StringVar 사용)
  after_load()                   부재 값을 화면에 올린 뒤 (Type 별 화면 전환 등) — 마지막에 self.calc(silent=True)
  compute(vals) -> dict          {"report", "sketch", "box", "ok", "status", "res"}  (오류는 InputError)
  kind_text(vals) -> str         목록 '형식' 칸 (짧게)
  on_result(res | None)          (선택) 계산 결과에 따라 입력 화면 갱신
"""
import datetime
import json
import os
import re
import tempfile
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox

from . import theme as T
from .report import render, fonts


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", s).strip("_") or "member"


class MemberWindow:
    TITLE = "Member"
    BADGE = "Lite"
    SUBTITLE = ""
    MODULE = "member"
    FILE_EXT = ".dat"
    FILE_DESC = "파일"
    DEFAULT_FILE = "members"
    PRINT_HEADER = "DESIGN"
    FOOTER = "StrCAD  ·  Basic Design"
    DEFAULTS = {"name": "M1"}
    InputError = ValueError
    INPUT_WIDTH = 392
    WIN_SIZE = "1560x880"

    def __init__(self, parent, username=""):
        self.user = username
        self.path = None
        self.result = None
        self.report = None
        self.members = [{"values": dict(self.DEFAULTS), "ok": None}]
        self.cur = 0
        self._busy = False
        self.win = win = tk.Toplevel(parent)
        win.geometry(self.WIN_SIZE)
        win.minsize(1200, 620)
        win.configure(bg=T.SURFACE)
        T.set_icon(win)
        self.v = {k: tk.StringVar(win, value=val) for k, val in self.DEFAULTS.items()}
        self.f_n = (T.FAM, 9)
        self.f_b = (T.FAM, 9, "bold")
        self._build()
        self.v["name"].trace_add("write", lambda *_: self._on_name())
        win.bind("<Return>", lambda _: self.calc())
        win.bind("<F5>", lambda _: self.calc())
        win.bind("<Control-s>", lambda _: self.save())
        win.bind("<Control-o>", lambda _: self.open())
        win.bind("<Control-p>", lambda _: self.print_pdf(False))
        self._update_title()
        self.after_load()
        self._refresh_list()
        win.lift()
        win.focus_force()

    # ── 하위 클래스 훅 ───────────────────────────────────────
    def build_inputs(self, parent):
        raise NotImplementedError

    def after_load(self):
        self.calc(silent=True)

    def compute(self, vals):
        raise NotImplementedError

    def compute_print(self, vals):
        """출력용 계산 (기본: 화면과 같음) — 출력에만 그림을 더 넣을 때 재정의"""
        return self.compute(vals)

    def kind_text(self, vals):
        return ""

    def on_result(self, res):
        pass

    # ── 화면 구성 ────────────────────────────────────────────
    def _build(self):
        win = self.win
        bar = tk.Frame(win, bg=T.NAVY, height=44)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, text=self.TITLE, font=(T.FAM, 13, "bold"), bg=T.NAVY, fg="white").pack(side="left", padx=(16, 6))
        tk.Label(bar, text=f" {self.BADGE} ", font=(T.FAM, 8, "bold"), bg=T.ORANGE, fg="white").pack(side="left")
        tk.Label(bar, text=self.SUBTITLE, font=(T.FAM, 9), bg=T.NAVY, fg="#B9C4DA").pack(side="left", padx=14)

        def tbtn(txt, cmd, bg=T.NAVY_2):
            b = tk.Button(bar, text=txt, command=cmd, font=self.f_n, bg=bg, fg="white", relief="flat",
                          activebackground=T.ORANGE, activeforeground="white", cursor="hand2", padx=10, pady=3)
            b.pack(side="right", padx=(0, 6), pady=8)
            return b
        self.btn_print = tbtn("출력 (A4) ▾", self._print_menu, bg=T.ORANGE_D)
        tbtn("다른 이름으로", self.save_as)
        tbtn("저장", self.save)
        tbtn("열기", self.open)
        tbtn("새 파일", self.new)
        self.menu_print = m = tk.Menu(win, tearoff=0, font=self.f_n)
        m.add_command(label="현재 부재 출력 (A4)          Ctrl+P", command=lambda: self.print_pdf(False))
        m.add_command(label="전체 부재 출력 (A4)", command=lambda: self.print_pdf(True))
        m.add_separator()
        m.add_command(label="PDF로 저장 — 현재 부재…", command=lambda: self.print_pdf(False, ask=True))
        m.add_command(label="PDF로 저장 — 전체 부재…", command=lambda: self.print_pdf(True, ask=True))
        m.add_separator()
        m.add_command(label="계산서 텍스트 저장…", command=self.save_report)
        m.add_command(label="계산서 복사 (클립보드)", command=self.copy_report)

        self.status = tk.Label(win, text="", anchor="w", font=self.f_n, bg="#E5E9F0", fg=T.INK, padx=12, pady=4)
        self.status.pack(fill="x", side="bottom")

        # 부재 목록 | 입력·계산서  — 경계(sash)를 끌어 목록 폭 조절
        self.pane = pane = tk.PanedWindow(win, orient="horizontal", sashwidth=6, sashrelief="flat", bd=0,
                                          bg=T.LINE, opaqueresize=True)
        pane.pack(fill="both", expand=True)
        lst = tk.Frame(pane, bg=T.SURFACE)
        self._build_list(lst)
        main = tk.Frame(pane, bg=T.SURFACE)
        pane.add(lst, minsize=150, width=self._list_width)
        pane.add(main, minsize=760, stretch="always")
        try:
            pane.paneconfigure(lst, stretch="never")
        except tk.TclError:
            pass

        left = tk.Frame(main, bg=T.SURFACE, width=self.INPUT_WIDTH)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Frame(main, bg=T.LINE, width=1).pack(side="left", fill="y")
        self._build_left_common(left)

        right = tk.Frame(main, bg=T.PANEL)
        right.pack(side="left", fill="both", expand=True)
        self.cv = cv = tk.Canvas(right, bg=T.PANEL, highlightthickness=0)
        vs = ttk.Scrollbar(right, orient="vertical", command=cv.yview)
        hs = ttk.Scrollbar(right, orient="horizontal", command=cv.xview)
        cv.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        vs.pack(side="right", fill="y")
        hs.pack(side="bottom", fill="x")
        cv.pack(fill="both", expand=True)
        cv.bind("<MouseWheel>", lambda e: cv.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        cv.bind("<Button-4>", lambda _: cv.yview_scroll(-1, "units"))
        cv.bind("<Button-5>", lambda _: cv.yview_scroll(1, "units"))
        cv.tip_rects = []                      # report.render 가 셀 설명(툴팁) 영역을 담는다
        cv.bind("<Motion>", self._on_motion)
        cv.bind("<Leave>", lambda _: self._hide_tip())
        self._tip = None

    def _build_left_common(self, p):
        top = tk.Frame(p, bg=T.SURFACE)
        top.pack(fill="x", padx=10, pady=(12, 6))
        self.top_fields = f = tk.Frame(top, bg=T.SURFACE)
        f.pack(side="left")
        self._lbl(f, "Name :").grid(row=0, column=0, sticky="e", pady=2)
        self._ent(f, "name", 15).grid(row=0, column=1, sticky="w", padx=4)
        b = tk.Button(top, text="계   산", command=self.calc, font=(T.FAM, 11, "bold"), bg=T.ORANGE, fg="white",
                      activebackground=T.ORANGE_D, activeforeground="white", relief="flat", cursor="hand2",
                      padx=20, pady=8)
        b.pack(side="right")
        body = tk.Frame(p, bg=T.SURFACE)
        body.pack(fill="both", expand=True)
        tk.Label(p, text="Enter / F5 : 계산    Ctrl+S : 저장    Ctrl+O : 열기    Ctrl+P : 출력", font=(T.FAM, 8),
                 bg=T.SURFACE, fg=T.MUTED).pack(side="bottom", pady=8)
        self.build_inputs(body)

    # ── 공용 위젯 도우미 ─────────────────────────────────────
    def _group(self, parent, title):
        return tk.LabelFrame(parent, text=title, font=self.f_b, bg=T.SURFACE, fg=T.NAVY, bd=1, relief="groove",
                             padx=8, pady=6)

    def _lbl(self, parent, text, **kw):
        kw.setdefault("fg", T.INK)
        return tk.Label(parent, text=text, font=self.f_n, bg=T.SURFACE, **kw)

    def _ent(self, parent, key, width=7):
        e = tk.Entry(parent, textvariable=self.v[key], width=width, font=self.f_n, fg=T.INPUT_FG, bg="white",
                     relief="solid", bd=1, highlightthickness=0)
        e.bind("<FocusIn>", lambda _: e.select_range(0, "end"))
        return e

    def _cmb(self, parent, key, values, width=7, state="normal"):
        return ttk.Combobox(parent, textvariable=self.v[key], values=values, width=width, state=state, font=self.f_n)

    def _field(self, parent, row, label, key, unit, width=7, widget=None):
        self._lbl(parent, label, anchor="e").grid(row=row, column=0, sticky="e", pady=2)
        w = widget or self._ent(parent, key, width)
        w.grid(row=row, column=1, sticky="w", padx=(4, 4), pady=2)
        if unit:
            self._lbl(parent, unit).grid(row=row, column=2, sticky="w")
        return w

    # ── 계산서 셀 툴팁 ───────────────────────────────────────
    def _on_motion(self, e):
        x, y = self.cv.canvasx(e.x), self.cv.canvasy(e.y)
        for x1, y1, x2, y2, tip in reversed(self.cv.tip_rects):
            if x1 <= x <= x2 and y1 <= y <= y2:
                self._show_tip(tip, e.x_root, e.y_root)
                return
        self._hide_tip()

    def _show_tip(self, text, xr, yr):
        if self._tip is None:
            self._tip = tw = tk.Toplevel(self.win)
            tw.overrideredirect(True)
            try:
                tw.attributes("-topmost", True)
            except tk.TclError:
                pass
            self._tip_lbl = tk.Label(tw, justify="left", font=self.f_n, bg="#FFFBEA", fg=T.INK, relief="solid",
                                     bd=1, padx=8, pady=6)
            self._tip_lbl.pack()
        if self._tip_lbl.cget("text") != text:
            self._tip_lbl.config(text=text)
        self._tip.geometry(f"+{xr + 16}+{yr + 14}")
        self._tip.deiconify()

    def _hide_tip(self):
        if self._tip is not None:
            self._tip.withdraw()

    # ── 부재 목록 ────────────────────────────────────────────
    def _build_list(self, p):
        hd = tk.Frame(p, bg=T.NAVY_2, height=26)
        hd.pack(fill="x")
        hd.pack_propagate(False)
        tk.Label(hd, text="Memb List", font=self.f_b, bg=T.NAVY_2, fg="white").pack(side="left", padx=10)
        self.lbl_cnt = tk.Label(hd, text="", font=(T.FAM, 8), bg=T.NAVY_2, fg="#B9C4DA")
        self.lbl_cnt.pack(side="right", padx=8)

        tb = tk.Frame(p, bg=T.SURFACE)
        tb.pack(fill="x", padx=6, pady=6)
        tk.Label(p, text="↔ 오른쪽 경계를 끌어 폭 조절", font=(T.FAM, 7), bg=T.SURFACE, fg=T.MUTED).pack(
            side="bottom", anchor="w", padx=8, pady=(0, 4))
        for txt, cmd in (("추가", self.member_add), ("복제", self.member_copy), ("삭제", self.member_delete),
                         ("▲", lambda: self.member_move(-1)), ("▼", lambda: self.member_move(1))):
            b = tk.Button(tb, text=txt, command=cmd, font=(T.FAM, 8), bg="white", fg=T.INK, relief="groove",
                          cursor="hand2", padx=5 if len(txt) > 1 else 4, pady=1)
            b.pack(side="left", padx=(0, 3))

        # 글꼴 크기(Windows 배율 포함)로 열 폭·행 높이를 정해 글자가 잘리지 않게
        fn = tkfont.Font(self.win, font=self.f_n)
        fb = tkfont.Font(self.win, font=self.f_b)
        pad = fn.measure("0") * 2 + 6
        widths = {"no": max(fb.measure("No"), fn.measure("999")) + pad,
                  "name": max(fn.measure("1RaS21-W"), fb.measure("Name")) + pad,
                  "type": max(fb.measure("형식"), fn.measure("T×6")) + pad,
                  "res": max(fb.measure("결과"), fn.measure("NG")) + pad}
        self._list_width = sum(widths.values()) + 18 + 14
        st = ttk.Style(self.win)
        st.configure("BD.Treeview", font=self.f_n, rowheight=fn.metrics("linespace") + 8)
        st.configure("BD.Treeview.Heading", font=self.f_b)
        box = tk.Frame(p, bg=T.SURFACE)
        box.pack(fill="both", expand=True, padx=(6, 2), pady=(0, 2))
        self.tree = tr = ttk.Treeview(box, columns=("no", "name", "type", "res"), show="headings",
                                      selectmode="browse", style="BD.Treeview")
        for cid, txt, anc in (("no", "No", "center"), ("name", "Name", "w"), ("type", "형식", "center"),
                              ("res", "결과", "center")):
            tr.heading(cid, text=txt, anchor="w" if cid == "name" else "center")
            tr.column(cid, width=widths[cid], minwidth=widths[cid], anchor=anc, stretch=(cid == "name"))
        tr.tag_configure("ng", foreground=T.NG)
        tr.tag_configure("odd", background="#EEF2F8")
        sb = ttk.Scrollbar(box, orient="vertical", command=tr.yview)
        tr.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tr.pack(fill="both", expand=True)
        tr.bind("<<TreeviewSelect>>", self._on_tree_select)

    def _row_values(self, i):
        m = self.members[i]
        vals = m["values"]
        res = "" if m["ok"] is None else ("OK" if m["ok"] else "NG")
        return (i + 1, vals.get("name", ""), self.kind_text(vals), res)

    def _row_tags(self, i):
        tags = ["odd"] if i % 2 else []
        if self.members[i]["ok"] is False:
            tags.append("ng")
        return tags

    def _refresh_list(self):
        self._busy = True
        try:
            tr = self.tree
            tr.delete(*tr.get_children())
            for i in range(len(self.members)):
                tr.insert("", "end", iid=str(i), values=self._row_values(i), tags=self._row_tags(i))
            tr.selection_set(str(self.cur))
            tr.see(str(self.cur))
            self.lbl_cnt.config(text=f"{len(self.members)}개")
            self.win.update_idletasks()
        finally:
            self._busy = False

    def _refresh_row(self, i=None):
        i = self.cur if i is None else i
        if self.tree.exists(str(i)):
            self.tree.item(str(i), values=self._row_values(i), tags=self._row_tags(i))

    def current_values(self):
        return {k: var.get() for k, var in self.v.items()}

    def _sync_current(self):
        self.members[self.cur]["values"] = self.current_values()

    def _load_member(self, i):
        self.cur = i
        vals = self.members[i]["values"]
        self._busy = True
        try:
            for k, var in self.v.items():
                var.set(str(vals.get(k, self.DEFAULTS[k])))
        finally:
            self._busy = False
        self.after_load()

    def _on_tree_select(self, _=None):
        if self._busy:
            return
        sel = self.tree.selection()
        if not sel:
            return
        i = int(sel[0])
        if i == self.cur or i >= len(self.members):
            return
        self._sync_current()
        self._load_member(i)

    def _on_name(self):
        if self._busy:
            return
        self.members[self.cur]["values"]["name"] = self.v["name"].get()
        self._refresh_row()

    def _unique_name(self, base):
        names = {m["values"].get("name", "") for m in self.members}
        if base not in names:
            return base
        m = re.match(r"^(.*?)(\d+)$", base)
        stem, n = (m.group(1), int(m.group(2))) if m else (base + "-", 1)
        while f"{stem}{n}" in names:
            n += 1
        return f"{stem}{n}"

    def new_member_values(self):
        """'추가' 로 만드는 새 부재의 값"""
        return dict(self.DEFAULTS)

    def member_add(self):
        self._sync_current()
        vals = self.new_member_values()
        vals["name"] = self._unique_name(self.DEFAULTS["name"])
        self.members.insert(self.cur + 1, {"values": vals, "ok": None})
        self._load_member(self.cur + 1)
        self._refresh_list()

    def member_copy(self):
        self._sync_current()
        vals = dict(self.members[self.cur]["values"])
        vals["name"] = self._unique_name(vals.get("name") or self.DEFAULTS["name"])
        self.members.insert(self.cur + 1, {"values": vals, "ok": None})
        self._load_member(self.cur + 1)
        self._refresh_list()

    def member_delete(self):
        nm = self.v["name"].get() or "(이름 없음)"
        if not messagebox.askyesno("부재 삭제", f"'{nm}' 부재를 목록에서 삭제할까요?", parent=self.win):
            return
        if len(self.members) == 1:
            self.members = [{"values": self.new_member_values(), "ok": None}]
            self._load_member(0)
        else:
            self.members.pop(self.cur)
            self._load_member(min(self.cur, len(self.members) - 1))
        self._refresh_list()

    def member_move(self, step):
        j = self.cur + step
        if not 0 <= j < len(self.members):
            return
        self._sync_current()
        self.members[self.cur], self.members[j] = self.members[j], self.members[self.cur]
        self.cur = j
        self._refresh_list()

    # ── 계산 ─────────────────────────────────────────────────
    def calc(self, silent=False):
        self._sync_current()
        self._hide_tip()
        try:
            out = self.compute(self.current_values())
        except self.InputError as e:
            self.result = self.report = None
            self.members[self.cur]["ok"] = None
            self._refresh_row()
            self.cv.delete("all")
            self.cv.tip_rects = []
            self.on_result(None)
            self._set_status(f"입력 오류 — {str(e).splitlines()[0]}", ok=False)
            if not silent:
                messagebox.showwarning("입력 확인", str(e), parent=self.win)
            return None
        res = out["res"]
        self.result = res
        self.on_result(res)
        self.report = out["report"]
        fonts(self.win)
        self.cv.tip_rects = []
        render(self.cv, self.report, sketch=out["sketch"], sketch_box=out["box"])
        self.cv.yview_moveto(0)
        self.members[self.cur]["ok"] = out["ok"]
        self._refresh_row()
        self._set_status(out["status"], ok=out["ok"])
        return res

    def _calc_all(self):
        for m in self.members:
            try:
                m["ok"] = self.compute(m["values"])["ok"]
            except self.InputError:
                m["ok"] = None

    def _set_status(self, text, ok=True):
        self.status.config(text=text, fg=T.OK if ok else T.NG)

    def _update_title(self):
        f = os.path.basename(self.path) if self.path else "제목 없음"
        self.win.title(f"StrCAD - Basic Design │ {self.TITLE} {self.BADGE}  ─  {f}"
                       + (f"  ─  {self.user}" if self.user else ""))

    # ── 파일 (부재 목록 전체를 한 파일에) ────────────────────
    def new(self):
        if len(self.members) > 1 and not messagebox.askyesno(
                "새 파일", "현재 부재 목록을 모두 비우고 새로 시작할까요?\n(저장하지 않은 내용은 사라집니다)", parent=self.win):
            return
        self.members = [{"values": self.new_member_values(), "ok": None}]
        self.path = None
        self._update_title()
        self._load_member(0)
        self._refresh_list()

    def _write(self, path):
        self._sync_current()
        data = {"app": "StrCAD Basic Design", "module": self.MODULE, "version": 2, "current": self.cur,
                "members": [m["values"] for m in self.members]}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            messagebox.showerror("저장 실패", str(e), parent=self.win)
            return False
        self.path = path
        self._update_title()
        self._set_status(f"저장했습니다 (부재 {len(self.members)}개): {path}")
        return True

    def save(self):
        if self.path:
            return self._write(self.path)
        return self.save_as()

    def save_as(self):
        init = os.path.basename(self.path) if self.path else self.DEFAULT_FILE + self.FILE_EXT
        path = filedialog.asksaveasfilename(parent=self.win, title="부재 목록 저장", defaultextension=self.FILE_EXT,
                                            filetypes=[(self.FILE_DESC, "*" + self.FILE_EXT), ("모든 파일", "*.*")],
                                            initialfile=init)
        return self._write(path) if path else False

    def normalize_values(self, vals):
        """파일에서 읽은 부재 값 → 기본값과 합친 문자열 dict (하위 클래스에서 보정 가능)"""
        merged = dict(self.DEFAULTS)
        merged.update({k: str(val) for k, val in vals.items() if k in self.DEFAULTS})
        return merged

    def open(self):
        path = filedialog.askopenfilename(parent=self.win, title="부재 목록 열기",
                                          filetypes=[(self.FILE_DESC, "*" + self.FILE_EXT), ("모든 파일", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            mod = data.get("module")
            if mod and mod != self.MODULE:
                raise ValueError(f"다른 모듈의 파일입니다 ({mod}).")
            if isinstance(data.get("members"), list) and data["members"]:
                raw = data["members"]
            else:
                raw = [data["values"]]                    # version 1: 부재 한 개
            members = [{"values": self.normalize_values(vals), "ok": None} for vals in raw]
            cur = int(data.get("current", 0))
        except (OSError, ValueError, KeyError, AttributeError, TypeError) as e:
            messagebox.showerror("열기 실패", f"파일을 읽지 못했습니다.\n{e}", parent=self.win)
            return
        self.members = members
        self.path = path
        self._calc_all()
        self._update_title()
        self._load_member(cur if 0 <= cur < len(members) else 0)
        self._refresh_list()
        self._set_status(f"열었습니다 (부재 {len(members)}개): {path}")

    # ── 출력 ─────────────────────────────────────────────────
    def _print_menu(self):
        b = self.btn_print
        self.menu_print.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def _print_items(self, all_members):
        """[(report, sketch, sketch_box, name)], 건너뛴 부재 이름"""
        self._sync_current()
        targets = self.members if all_members else [self.members[self.cur]]
        items, skipped = [], []
        for m in targets:
            try:
                out = self.compute_print(m["values"])
            except self.InputError:
                skipped.append(m["values"].get("name", "?"))
                continue
            items.append((out["report"], out["sketch"], out["box"], m["values"].get("name", "")))
        return items, skipped

    def print_pdf(self, all_members=False, ask=False):
        """A4 PDF 를 만들어 PDF 뷰어로 연다(뷰어에서 인쇄).  ask=True 면 저장 위치를 묻고 열지는 않는다."""
        from . import pdf_out
        items, skipped = self._print_items(all_members)
        if not items:
            messagebox.showwarning("출력", "출력할 수 있는 부재가 없습니다.\n입력값을 확인하세요.", parent=self.win)
            return None
        prefix = safe_name(self.PRINT_HEADER.title().replace(" ", "_")).upper().replace("_DESIGN", "")
        if not all_members:
            base = f"{prefix}_{safe_name(items[0][3])}"
        elif self.path:
            base = f"{prefix}_{safe_name(os.path.splitext(os.path.basename(self.path))[0])}"
        else:
            base = f"{prefix}_전체"
        if ask:
            path = filedialog.asksaveasfilename(parent=self.win, title="PDF로 저장", defaultextension=".pdf",
                                                filetypes=[("PDF", "*.pdf")], initialfile=base + ".pdf")
            if not path:
                return None
        else:
            folder = os.path.join(tempfile.gettempdir(), "StrCAD_print")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"{base}_{datetime.datetime.now():%H%M%S}.pdf")
        self.win.config(cursor="watch")
        self._set_status("출력용 PDF 를 만드는 중…")
        self.win.update_idletasks()
        try:
            n = pdf_out.export_pdf(path, items, header=self.PRINT_HEADER, footer=self.FOOTER)
        except (pdf_out.PdfExportError, OSError) as e:
            messagebox.showerror("출력 실패", str(e), parent=self.win)
            self._set_status("출력 실패", ok=False)
            return None
        finally:
            self.win.config(cursor="")
        msg = f"A4 {n}쪽 PDF 를 만들었습니다: {path}"
        if skipped:
            msg += f"   (입력 오류로 제외: {', '.join(skipped)})"
        self._set_status(msg)
        if not ask:
            try:
                pdf_out.open_file(path)
            except OSError as e:
                messagebox.showinfo("출력", f"PDF 를 만들었지만 자동으로 열지 못했습니다.\n{path}\n\n{e}", parent=self.win)
        return path

    def save_report(self):
        if self.calc() is None:
            return
        path = filedialog.asksaveasfilename(parent=self.win, title="계산서 저장", defaultextension=".txt",
                                            filetypes=[("텍스트", "*.txt")],
                                            initialfile=safe_name(self.v["name"].get()) + "_계산서.txt")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write(self.report.to_text())
        except OSError as e:
            messagebox.showerror("저장 실패", str(e), parent=self.win)
            return
        self._set_status(f"계산서를 저장했습니다: {path}")

    def copy_report(self):
        if self.calc() is None:
            return
        self.win.clipboard_clear()
        self.win.clipboard_append(self.report.to_text())
        self._set_status("계산서를 클립보드에 복사했습니다.")
