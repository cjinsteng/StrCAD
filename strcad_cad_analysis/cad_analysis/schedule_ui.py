"""현장조사 › 부재리스트 패널 — 종류 탭(슬래브/거더/보/기둥/벽체/기타) × 부재 | 부재일람 | 현장검측 | 조사여부."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from . import schedule as SC
from . import theme as TH

SV_BG = TH.SURFACE
BLUE = TH.NAVY_3
BLUE_D = TH.NAVY
F9 = (TH.FAM, 9)
F10 = (TH.FAM, 10)
FB = (TH.FAM, 10, "bold")


class SizeDialog(tk.Toplevel):
    """b × h (슬래브·벽: 두께) 입력 — 빠른 선택 버튼 포함."""
    QUICK_B = ("200", "250", "300", "350", "400", "450", "500", "600", "700", "800", "900", "1000")
    QUICK_H = ("150", "200", "300", "400", "500", "600", "700", "800", "900", "1000", "1200")

    def __init__(self, master, title, b, h, on_ok, thickness=False, extra=None):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.resizable(False, False)
        self.configure(bg=SV_BG, padx=14, pady=12)
        self.on_ok = on_ok
        self.b = tk.StringVar(value=b or "")
        self.h = tk.StringVar(value=h or "")
        self.thick = thickness
        r = 0
        if extra:
            tk.Label(self, text=extra, bg=SV_BG, fg="#555", font=F9, justify="left").grid(row=r, column=0,
                                                                                        columnspan=3, sticky="w")
            r += 1
        tk.Label(self, text="두께 t" if thickness else "b (폭)", bg=SV_BG, font=FB).grid(row=r, column=0, sticky="w")
        eb = ttk.Entry(self, textvariable=self.b, width=10, font=(TH.FAM, 12))
        eb.grid(row=r, column=1, padx=6, pady=4)
        tk.Label(self, text="mm", bg=SV_BG).grid(row=r, column=2, sticky="w")
        r += 1
        self._quick(r, self.b, self.QUICK_B if not thickness else ("150", "180", "200", "210", "250", "300", "350",
                                                                    "400"))
        r += 1
        if not thickness:
            tk.Label(self, text="h (춤)", bg=SV_BG, font=FB).grid(row=r, column=0, sticky="w")
            ttk.Entry(self, textvariable=self.h, width=10, font=(TH.FAM, 12)).grid(row=r, column=1, padx=6,
                                                                                          pady=4)
            tk.Label(self, text="mm", bg=SV_BG).grid(row=r, column=2, sticky="w")
            r += 1
            self._quick(r, self.h, self.QUICK_H)
            r += 1
        bf = tk.Frame(self, bg=SV_BG)
        bf.grid(row=r, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(bf, text="지우기", command=lambda: self._ok(clear=True)).pack(side="left")
        ttk.Button(bf, text="취소", command=self.destroy).pack(side="left", padx=6)
        ttk.Button(bf, text="확인", command=self._ok).pack(side="left")
        eb.focus_set()
        self.bind("<Return>", lambda e: self._ok())

    def _quick(self, r, var, vals):
        f = tk.Frame(self, bg=SV_BG)
        f.grid(row=r, column=0, columnspan=3, sticky="w")
        for i, v in enumerate(vals):
            tk.Button(f, text=v, bg=BLUE, fg="white", relief="flat", width=5, font=F9,
                      command=lambda v=v: var.set(v)).grid(row=i // 6, column=i % 6, padx=1, pady=1)

    def _ok(self, clear=False):
        b = "" if clear else self.b.get().strip()
        h = "" if clear else self.h.get().strip()
        self.destroy()
        self.on_ok(b, h)


class SchedulePanel(tk.Frame):
    """app: CadAnalysisApp (res, log, _set_dirty, redraw, _sv_select, _pick_member)"""

    def __init__(self, parent, app, on_close):
        super().__init__(parent, bg=SV_BG)
        self.app = app
        self.kind = "girder"
        head = tk.Frame(self, bg=SV_BG)
        head.pack(fill="x", padx=8, pady=(8, 2))
        tk.Label(head, text="부재리스트", bg=SV_BG, font=(TH.FAM, 12, "bold")).pack(side="left")
        tk.Button(head, text="← 검측 입력", bg=BLUE_D, fg="white", relief="flat", font=FB,
                  command=on_close).pack(side="right")
        tools = tk.Frame(self, bg=SV_BG)
        tools.pack(fill="x", padx=8, pady=(2, 4))
        for t, cmd in (("＋ 부재 추가", self.add), ("⟳ 도면에서 추정", self.estimate),
                       ("⇩ 다른 층 리스트", self.import_other), ("삭제", self.delete)):
            ttk.Button(tools, text=t, command=cmd).pack(side="left", padx=(0, 4))
        tabs = tk.Frame(self, bg=SV_BG)
        tabs.pack(fill="x", padx=8)
        self.tab_btn = {}
        for k in SC.KINDS:
            b = tk.Button(tabs, text=SC.KIND_TAB[k], relief="solid", bd=1, font=FB, width=6,
                          command=lambda k=k: self.set_kind(k))
            b.pack(side="left")
            self.tab_btn[k] = b
        frm = tk.Frame(self, bg=SV_BG)
        frm.pack(fill="both", expand=True, padx=8, pady=6)
        st = ttk.Style(self)
        st.configure("Sch.Treeview", font=(TH.FAM, 10), rowheight=30)
        st.configure("Sch.Treeview.Heading", font=FB)
        self.tv = ttk.Treeview(frm, columns=("name", "design", "meas", "stat"), show="headings",
                               style="Sch.Treeview", selectmode="browse")
        for c, t, w in (("name", "부재", 70), ("design", "부재일람", 120), ("meas", "현장검측", 120),
                        ("stat", "조사여부", 80)):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=w, anchor="center")
        sb = ttk.Scrollbar(frm, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tv.pack(fill="both", expand=True)
        self.tv.tag_configure("done", background="#E3F6E9")
        self.tv.tag_configure("diff", background="#FDE4E4")
        self.tv.bind("<ButtonRelease-1>", self._click)
        self.tv.bind("<Double-1>", self._dbl)
        self.info = tk.Label(self, bg=SV_BG, fg="#555", font=F9, justify="left", anchor="w", wraplength=380, text=(
            "칸을 누르면 수정: 부재 = 이름 · 부재일람 = 설계 단면 · 현장검측 = 검측기록 보기/직접 입력 · "
            "조사여부 = 자동→조사됨→조사안됨.\n행 더블클릭 = 도면에서 그 부재 찾기.  "
            "검측 입력의 부재명(예: 기둥 C1)과 자동으로 연결됩니다.  초록 = 조사됨, 빨강 = 설계와 다름(±20mm 초과)"))
        self.info.pack(fill="x", padx=8, pady=(0, 8))
        self.set_kind("girder")

    # ------------------------------------------------------------------ data
    @property
    def sch(self):
        res = self.app.res
        if res is None:
            return []
        if not hasattr(res, "schedule") or res.schedule is None:
            res.schedule = []
        return res.schedule

    @property
    def surveys(self):
        return self.app.res.surveys if self.app.res else []

    def _changed(self, msg=None):
        self.app._set_dirty(True)
        if msg:
            self.app.log(msg)
        self.refresh()
        if getattr(self.app, "_sv_fill_form", None):
            self.app._sv_refresh_list(keep_sel=True)

    def set_kind(self, k):
        self.kind = k
        for kk, b in self.tab_btn.items():
            b.config(bg=BLUE_D if kk == k else "white", fg="white" if kk == k else "#111")
        self.refresh()

    def refresh(self):
        sel = self.tv.selection()
        self.tv.delete(*self.tv.get_children())
        for k, b in self.tab_btn.items():
            n = sum(1 for e in self.sch if e["kind"] == k)
            b.config(text=f"{SC.KIND_TAB[k]} {n}" if n else SC.KIND_TAB[k])
        rows = sorted((e for e in self.sch if e["kind"] == self.kind), key=lambda e: _natural(e["name"]))
        for e in rows:
            st = SC.status(e, self.surveys)
            cmp = SC.compare(e, self.surveys)
            tags = ("diff",) if cmp == "상이" else (("done",) if st == "조사됨" else ())
            n = len(SC.linked(e, self.surveys))
            self.tv.insert("", "end", iid=str(e["id"]), tags=tags,
                           values=(e["name"], SC.design_text(e), SC.meas_text(e, self.surveys),
                                   (st or "-") + (f" ({n})" if n else "")))
        for s in sel:
            if self.tv.exists(s):
                self.tv.selection_set(s)

    def _entry(self, iid):
        return next((e for e in self.sch if str(e["id"]) == str(iid)), None)

    # ------------------------------------------------------------------ actions
    def add(self):
        from tkinter import simpledialog
        if self.app.res is None:
            return
        nm = simpledialog.askstring("부재 추가", f"{SC.KIND_TAB[self.kind]} 부재 이름 (예: G1, C1, S1)",
                                    parent=self)
        if not nm:
            return
        nm = nm.strip()
        if SC.find(self.sch, self.kind, nm):
            messagebox.showinfo("부재 추가", "이미 있는 부재입니다.", parent=self)
            return
        e = {"id": SC.next_id(self.sch), "kind": self.kind, "name": nm, "b": "", "h": "", "src": "사용자",
             "meas_b": "", "meas_h": "", "status": "", "note": ""}
        self.sch.append(e)
        self._changed(f"부재리스트: {SC.full_name(e)} 추가")
        self.tv.selection_set(str(e["id"]))
        self._edit_design(e)

    def estimate(self):
        if self.app.res is None:
            return
        a, u = SC.merge_estimate(self.sch, self.app.res)
        self._changed(f"부재리스트: 도면에서 추정 — 새 부재 {a}개, 갱신 {u}개 (직접 고친 항목은 유지)")

    def import_other(self):
        from . import db
        app = self.app
        if not app.project:
            messagebox.showinfo("다른 층 리스트", "DB에 프로젝트로 저장된 도면에서만 가져올 수 있습니다.", parent=self)
            return
        sheets = [(i, n) for i, n in db.project_sheets(app.project) if i != app.db_id]
        if not sheets:
            messagebox.showinfo("다른 층 리스트", "같은 프로젝트의 다른 도면이 없습니다.", parent=self)
            return
        win = tk.Toplevel(self)
        win.title("부재리스트 가져오기")
        win.transient(self)
        tk.Label(win, text="가져올 층(도면)을 고르세요 — 같은 이름의 부재는 건너뜁니다.", font=F10).pack(padx=12, pady=8)
        lb = tk.Listbox(win, font=F10, height=min(12, len(sheets)), width=30)
        for _i, n in sheets:
            lb.insert("end", n)
        lb.pack(padx=12)

        def go():
            if not lb.curselection():
                return
            aid, src_name = sheets[lb.curselection()[0]]
            _n, other, _cs = db.load(aid)
            k = 0
            for e in getattr(other, "schedule", []) or []:
                if SC.find(self.sch, e["kind"], e["name"]):
                    continue
                ne = {key: e.get(key, "") for key in ("kind", "name", "b", "h", "src", "note")}
                ne.update(id=SC.next_id(self.sch), meas_b="", meas_h="", status="")
                self.sch.append(ne)
                k += 1
            win.destroy()
            self._changed(f"부재리스트: '{src_name}'에서 {k}개 가져옴")
        ttk.Button(win, text="가져오기", command=go).pack(pady=8)

    def delete(self):
        sel = self.tv.selection()
        e = self._entry(sel[0]) if sel else None
        if not e:
            return
        n = len(SC.linked(e, self.surveys))
        if not messagebox.askyesno("삭제", f"{SC.full_name(e)} 을(를) 리스트에서 지울까요?"
                                   + (f"\n(검측기록 {n}건은 그대로 남습니다)" if n else ""), parent=self):
            return
        self.sch.remove(e)
        self._changed(f"부재리스트: {SC.full_name(e)} 삭제")

    def _click(self, ev):
        iid = self.tv.identify_row(ev.y)
        col = self.tv.identify_column(ev.x)
        e = self._entry(iid) if iid else None
        if not e:
            return
        if col == "#1":
            self._rename(e)
        elif col == "#2":
            self._edit_design(e)
        elif col == "#3":
            self._meas(e, ev)
        elif col == "#4":
            order = ["", "조사됨", "조사안됨"]
            e["status"] = order[(order.index(e.get("status", "")) + 1) % 3]
            self._changed()

    def _dbl(self, ev):
        iid = self.tv.identify_row(ev.y)
        e = self._entry(iid) if iid else None
        if not e or self.app.res is None:
            return
        ms = [m for m in self.app.res.members if m.name == e["name"] and (m.kind == e["kind"])]
        if ms:
            self.app._pick_member(ms[0].id)
            self.app.status.config(text=f"{SC.full_name(e)}: 도면에 {len(ms)}개")

    def _rename(self, e):
        from tkinter import simpledialog
        nm = simpledialog.askstring("부재 이름", "새 이름", initialvalue=e["name"], parent=self)
        if not nm or nm.strip() == e["name"]:
            return
        nm = nm.strip()
        if SC.find(self.sch, e["kind"], nm):
            messagebox.showinfo("부재 이름", "같은 이름이 이미 있습니다.", parent=self)
            return
        old, n = SC.rename(self.sch, self.surveys, e, nm)
        self._changed(f"부재리스트: {old} → {SC.full_name(e)}" + (f" (검측기록 {n}건 부재명도 변경)" if n else ""))

    def _edit_design(self, e):
        def ok(b, h):
            e["b"], e["h"] = b, h
            e["src"] = "사용자"
            self._changed(f"부재리스트: {SC.full_name(e)} 부재일람 {SC.design_text(e)}")
        SizeDialog(self, f"부재일람 — {SC.full_name(e)}", e.get("b"), e.get("h"), ok,
                   thickness=e["kind"] in ("slab", "wall"),
                   extra=f"도면 추정값: {SC.design_text(e)}" if e.get("src") == "도면" else None)

    def _meas(self, e, ev):
        recs = SC.linked(e, self.surveys)
        menu = tk.Menu(self, tearoff=0)
        for r in sorted(recs, key=lambda r: int(r.get("no") or 0)):
            sz = f"{r.get('size_b') or '-'}×{r.get('size_h') or '-'}" if (r.get("size_b") or r.get("size_h")) else ""
            menu.add_command(label=f"검측 #{r.get('no')}  {r.get('purpose', '')}  {sz}",
                             command=lambda r=r: self.app._sv_open_record(r["id"]))
        if recs:
            menu.add_separator()

        def manual():
            def ok(b, h):
                e["meas_b"], e["meas_h"] = b, h
                self._changed(f"부재리스트: {SC.full_name(e)} 현장검측 직접 입력 {b}×{h}")
            b0, h0, _ = SC.measured(e, self.surveys)
            SizeDialog(self, f"현장검측 — {SC.full_name(e)}", b0, h0, ok, thickness=e["kind"] in ("slab", "wall"),
                       extra="검측기록과 따로 리스트에만 적는 값입니다. 지우면 검측기록 값으로 돌아갑니다.")
        menu.add_command(label="현장검측 직접 입력…", command=manual)
        menu.tk_popup(ev.x_root, ev.y_root)


def _natural(s):
    import re
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s or "")]
