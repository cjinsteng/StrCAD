"""Dialogs: layer mapping, coordinate system, DB browser."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from . import db
from .model import LAYER_ROLES, LAYER_ROLE_KO, CoordSystem
from . import theme as TH

FONT = TH.FONT


# ============================================================================
class LayerDialog(tk.Toplevel):
    """Review / edit layer roles before geometry analysis."""

    def __init__(self, master, summaries, roles, on_ok, on_reclassify=None):
        super().__init__(master)
        self.title("레이어 매핑 확인")
        self.geometry("900x540")
        self.transient(master)
        self.summaries = {s["name"]: s for s in summaries}
        self.roles = dict(roles)            # name -> (role, source)
        self.on_ok = on_ok
        self.on_reclassify = on_reclassify

        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text="각 레이어의 역할을 확인하세요. 행 선택(Ctrl/Shift 다중) → 아래에서 역할 변경 → [적용].\n"
                            "레이어가 정리되지 않은 도면은 '형상 자동판별'로 두면 모양으로 기둥/보/벽을 구분합니다.",
                  font=FONT).pack(side="left")
        self.show_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="무시 레이어도 표시", variable=self.show_all,
                        command=self._fill).pack(side="right")

        cols = ("role", "src", "ents", "texts")
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=6)
        self.tv = ttk.Treeview(frm, columns=cols, show="tree headings", selectmode="extended")
        for c, t, w in (("#0", "레이어", 210), ("role", "역할", 120), ("src", "판정", 60),
                        ("ents", "엔티티", 230), ("texts", "텍스트 예시", 220)):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=w, anchor="center" if c == "src" else "w")
        sb = ttk.Scrollbar(frm, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tv.pack(side="left", fill="both", expand=True)

        bot = ttk.Frame(self, padding=6)
        bot.pack(fill="x")
        ttk.Label(bot, text="역할:").pack(side="left")
        self.role_var = tk.StringVar()
        self.cb = ttk.Combobox(bot, textvariable=self.role_var, state="readonly", width=16,
                               values=[LAYER_ROLE_KO[r] for r in LAYER_ROLES])
        self.cb.pack(side="left", padx=4)
        ttk.Button(bot, text="적용", command=self._apply).pack(side="left")
        if on_reclassify:
            ttk.Button(bot, text="AI 재분류", command=self._reclassify).pack(side="left", padx=12)
        ttk.Button(bot, text="취소", command=self.destroy).pack(side="right")
        ttk.Button(bot, text="확인 후 분석 ▶", command=self._ok).pack(side="right", padx=6)
        self._fill()
        self.grab_set()

    def _fill(self):
        self.tv.delete(*self.tv.get_children())
        order = {r: i for i, r in enumerate(LAYER_ROLES)}
        for name in sorted(self.roles, key=lambda n: (order.get(self.roles[n][0], 99), n)):
            role, src = self.roles[name]
            if role == "ignore" and not self.show_all.get():
                continue
            s = self.summaries.get(name, {})
            ents = ", ".join(f"{k} {v}" for k, v in sorted(s.get("entities", {}).items(), key=lambda x: -x[1])[:4])
            self.tv.insert("", "end", iid=name, text=name,
                           values=(LAYER_ROLE_KO[role], src, ents, " ".join(s.get("sample_texts", [])[:5])))

    def _apply(self):
        ko = self.role_var.get()
        role = next((r for r, k in LAYER_ROLE_KO.items() if k == ko), None)
        if not role:
            return
        for iid in self.tv.selection():
            self.roles[iid] = (role, "수정")
        self._fill()

    def _reclassify(self):
        self.destroy()
        self.on_reclassify()

    def _ok(self):
        roles = {k: v[0] for k, v in self.roles.items()}
        edited = {k: v[0] for k, v in self.roles.items() if v[1] == "수정"}
        self.destroy()
        self.on_ok(roles, edited)


# ============================================================================
class CoordDialog(tk.Toplevel):
    def __init__(self, master, cs: CoordSystem, on_ok, on_pick, auto_rot):
        super().__init__(master)
        self.title("좌표계 (X, Y 축 정의)")
        self.transient(master)
        self.resizable(False, False)
        f = ttk.Frame(self, padding=10)
        f.pack()
        self.vx = tk.StringVar(value=f"{cs.x0:.1f}")
        self.vy = tk.StringVar(value=f"{cs.y0:.1f}")
        self.vr = tk.StringVar(value=f"{cs.rot:.4f}")
        for r, (lab, var) in enumerate((("원점 X", self.vx), ("원점 Y", self.vy), ("X축 회전각(°)", self.vr))):
            ttk.Label(f, text=lab).grid(row=r, column=0, sticky="w", pady=2)
            ttk.Entry(f, textvariable=var, width=18).grid(row=r, column=1, pady=2)
        ttk.Button(f, text="기둥/점 클릭으로 원점 지정", command=lambda: (self.destroy(), on_pick())).grid(
            row=0, column=2, rowspan=2, padx=6)
        ttk.Button(f, text="도면 주방향 자동", command=lambda: self.vr.set(f"{auto_rot():.4f}")).grid(
            row=2, column=2, padx=6)
        ttk.Label(f, text="국부좌표: 원점 기준, X축을 회전각만큼 돌린 축.\n(전역 DXF 좌표는 항상 함께 표시됩니다)",
                  foreground="#666").grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        b = ttk.Frame(f)
        b.grid(row=4, column=0, columnspan=3, pady=(8, 0), sticky="e")
        ttk.Button(b, text="초기화", command=lambda: (self.vx.set("0"), self.vy.set("0"), self.vr.set("0"))).pack(
            side="left")
        ttk.Button(b, text="확인", command=self._ok).pack(side="left", padx=4)
        self.on_ok = on_ok

    def _ok(self):
        try:
            cs = CoordSystem(float(self.vx.get()), float(self.vy.get()), float(self.vr.get()))
        except ValueError:
            messagebox.showerror("좌표계", "숫자를 입력하세요.", parent=self)
            return
        self.destroy()
        self.on_ok(cs)


# ============================================================================
class DbDialog(tk.Toplevel):
    """도면 LIST — saved analyses grouped by project (건물/과업), ordered by sheet order."""

    def __init__(self, master, on_open, db_path=None, project=None):
        super().__init__(master)
        self.title("도면 LIST (저장된 분석)")
        self.geometry("900x440")
        self.transient(master)
        self.on_open = on_open
        self.db_path = db_path or db.DB_PATH
        top = ttk.Frame(self, padding=(6, 4))
        top.pack(fill="x")
        ttk.Label(top, text="프로젝트").pack(side="left")
        self.proj = tk.StringVar(value=project if project is not None else "(전체)")
        self.pcb = ttk.Combobox(top, textvariable=self.proj, state="readonly", width=30)
        self.pcb.pack(side="left", padx=4)
        self.pcb.bind("<<ComboboxSelected>>", lambda e: self._fill())
        ttk.Label(top, text=f"DB: {self.db_path}", foreground="#666").pack(side="right")
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=6)
        cols = ("proj", "seq", "name", "file", "cnt", "date")
        self.tv = ttk.Treeview(frm, columns=cols, show="headings", selectmode="browse")
        for c, t, w in (("proj", "프로젝트", 150), ("seq", "순서", 45), ("name", "도면(층)", 150),
                        ("file", "DXF 파일", 220), ("cnt", "기둥/거더/보/벽", 120), ("date", "수정일", 140)):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=w, anchor="center" if c == "seq" else "w")
        sb = ttk.Scrollbar(frm, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tv.pack(side="left", fill="both", expand=True)
        self.tv.bind("<Double-1>", lambda e: self._open())
        b = ttk.Frame(self, padding=6)
        b.pack(fill="x")
        ttk.Button(b, text="열기", command=self._open).pack(side="left")
        ttk.Button(b, text="도면명 변경", command=self._rename).pack(side="left", padx=4)
        ttk.Button(b, text="▲", width=3, command=lambda: self._move(-1)).pack(side="left")
        ttk.Button(b, text="▼", width=3, command=lambda: self._move(1)).pack(side="left", padx=2)
        ttk.Button(b, text="삭제", command=self._delete).pack(side="left", padx=8)
        ttk.Button(b, text="닫기", command=self.destroy).pack(side="right")
        self._fill()
        self.grab_set()

    def _fill(self):
        self.pcb["values"] = ["(전체)"] + db.projects(self.db_path)
        self.tv.delete(*self.tv.get_children())
        pj = self.proj.get()
        for (aid, name, path, upd, nc, ng, nb, nw, proj, seq) in db.list_analyses(self.db_path):
            if pj != "(전체)" and (proj or "") != pj:
                continue
            self.tv.insert("", "end", iid=str(aid), values=(proj or "", seq or "", name, os.path.basename(path or ""),
                                                            f"{nc}/{ng}/{nb}/{nw}", (upd or "").replace("T", " ")))

    def _sel(self):
        s = self.tv.selection()
        return int(s[0]) if s else None

    def _open(self):
        aid = self._sel()
        if aid is None:
            return
        self.destroy()
        self.on_open(aid)

    def _rename(self):
        aid = self._sel()
        if aid is None:
            return
        old = self.tv.item(str(aid), "values")[2]
        new = simpledialog.askstring("도면명 변경", "도면(층) 이름:", initialvalue=old, parent=self)
        if new:
            db.rename(aid, new.strip(), self.db_path)
            self._fill()

    def _move(self, d):
        aid = self._sel()
        if aid is None:
            return
        name, proj, seq = db.meta(aid, self.db_path)
        sheets = db.project_sheets(proj or "", self.db_path)
        ids = [i for i, _ in sheets]
        k = ids.index(aid)
        j = k + d
        if not (0 <= j < len(ids)):
            return
        ids[k], ids[j] = ids[j], ids[k]
        db.reorder(ids, self.db_path)
        self._fill()
        self.tv.selection_set(str(aid))

    def _delete(self):
        aid = self._sel()
        if aid is None:
            return
        name = self.tv.item(str(aid), "values")[2]
        if messagebox.askyesno("삭제", f"'{name}' 분석을 DB에서 삭제할까요?", parent=self):
            db.delete(aid, self.db_path)
            self._fill()


class SaveDialog(tk.Toplevel):
    """DB 저장 — 프로젝트(건물) + 도면(층) 이름."""

    def __init__(self, master, project, name, on_ok):
        super().__init__(master)
        self.title("DB 저장")
        self.transient(master)
        self.resizable(False, False)
        f = ttk.Frame(self, padding=12)
        f.pack()
        ttk.Label(f, text="프로젝트(건물·과업)").grid(row=0, column=0, sticky="w", pady=2)
        self.p = tk.StringVar(value=project)
        cb = ttk.Combobox(f, textvariable=self.p, values=db.projects(), width=28)
        cb.grid(row=0, column=1, pady=2)
        ttk.Label(f, text="도면(층) 이름").grid(row=1, column=0, sticky="w", pady=2)
        self.n = tk.StringVar(value=name)
        e = ttk.Entry(f, textvariable=self.n, width=30)
        e.grid(row=1, column=1, pady=2)
        ttk.Label(f, text="같은 프로젝트의 도면은 현장조사 탭에서 ‹ n/N › 로 넘겨 봅니다.", foreground="#666",
                  font=FONT).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        b = ttk.Frame(f)
        b.grid(row=3, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(b, text="취소", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(b, text="저장", command=self._ok).pack(side="left")
        self.on_ok = on_ok
        e.focus_set()
        self.bind("<Return>", lambda ev: self._ok())
        self.grab_set()

    def _ok(self):
        if not self.n.get().strip():
            return
        p, n = self.p.get().strip(), self.n.get().strip()
        self.destroy()
        self.on_ok(p, n)


# ============================================================================
class ReviewDialog(tk.Toplevel):
    """AI/규칙 검토 제안 목록 — 체크한 항목만 적용."""

    def __init__(self, master, cands, on_apply, on_focus):
        from . import review as RV
        super().__init__(master)
        self.title("AI 2차 검토 결과")
        self.geometry("1120x520")
        self.transient(master)
        self.cands = {c["id"]: c for c in cands}
        self.on_apply, self.on_focus = on_apply, on_focus
        n_ai = sum(1 for c in cands if c["source"] == "AI")
        n_lay = sum(1 for c in cands if c["type"] == "layer" and c["action"] != "keep")
        ttk.Label(self, padding=(6, 6, 6, 0), font=FONT, text=(
            f"검토 {len(cands)}건 (AI 판단 {n_ai}, 규칙 판단 {len(cands) - n_ai}). 변경 제안은 기본 체크되어 있습니다. "
            "행 클릭 = 도면에서 위치 보기, ☑ 칸 클릭 = 적용 여부 전환.")).pack(fill="x")
        if n_lay:
            ttk.Label(self, padding=(6, 0, 6, 4), font=FONT, foreground="#b45309", text=(
                "레이어 역할 변경을 적용하면 바뀐 레이어로 1차 분석을 다시 하고, 부재 검토(절점·기둥)를 새 결과로 "
                "다시 보여줍니다.")).pack(fill="x")
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=6)
        cols = ("chk", "type", "member", "act", "src", "reason", "info")
        self.tv = ttk.Treeview(frm, columns=cols, show="headings", selectmode="browse")
        for c, t, w in (("chk", "적용", 46), ("type", "유형", 110), ("member", "대상", 200), ("act", "제안", 170),
                        ("src", "판정", 50), ("reason", "근거", 280), ("info", "수치", 340)):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=w, anchor="center" if c in ("chk", "src") else "w")
        sb = ttk.Scrollbar(frm, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tv.pack(fill="both", expand=True)
        self.tv.tag_configure("keep", foreground="#888")
        self.tv.tag_configure("layer", background="#fff7e6")
        self.chk = {}
        prio = {"layer": 0, "add_col": 1, "joint": 2, "col_wall": 3}
        self.order = sorted(cands, key=lambda c: (c["action"] == "keep", prio.get(c["type"], 9), c["id"]))
        for c in self.order:
            self.chk[c["id"]] = c["action"] != "keep" and not c.get("weak")
        self.RV = RV
        self.show_keep = tk.BooleanVar(value=False)
        self._fill()
        self.tv.bind("<ButtonRelease-1>", self._click)
        b = ttk.Frame(self, padding=6)
        b.pack(fill="x")
        n_keep = sum(1 for c in cands if c["action"] == "keep")
        ttk.Checkbutton(b, text=f"'유지' 판정도 보기 ({n_keep}건)", variable=self.show_keep,
                        command=self._fill).pack(side="left", padx=(0, 10))
        ttk.Button(b, text="변경 제안 모두 선택", command=lambda: self._all(True)).pack(side="left")
        ttk.Button(b, text="모두 해제", command=lambda: self._all(False)).pack(side="left", padx=4)
        ttk.Button(b, text="닫기", command=self.destroy).pack(side="right")
        ttk.Button(b, text="체크한 항목 적용 ▶", command=self._apply).pack(side="right", padx=6)

    def _fill(self):
        RV = self.RV
        self.tv.delete(*self.tv.get_children())
        for c in self.order:
            if c["action"] == "keep" and not self.show_keep.get():
                continue
            mem, act, info = RV.describe(c)
            tags = ("keep",) if c["action"] == "keep" else (("layer",) if c["type"] == "layer" else ())
            self.tv.insert("", "end", iid=c["id"], tags=tags,
                           values=("☑" if self.chk[c["id"]] else "☐", RV.TYPE_KO[c["type"]], mem,
                                   act, c["source"], c["reason"], info))

    def _set(self, iid, v):
        c = self.cands[iid]
        if c["action"] == "keep":
            v = False
        self.chk[iid] = v
        if self.tv.exists(iid):
            self.tv.set(iid, "chk", "☑" if v else "☐")

    def _all(self, v):
        for iid in self.chk:
            self._set(iid, v)

    def _click(self, e):
        iid = self.tv.identify_row(e.y)
        if not iid:
            return
        if self.tv.identify_column(e.x) == "#1":
            self._set(iid, not self.chk[iid])
        self.on_focus(self.cands[iid])

    def _apply(self):
        sel = [self.cands[i] for i, v in self.chk.items() if v]
        if not sel:
            return
        self.destroy()
        self.on_apply(sel)


# ============================================================================
class TextWindow(tk.Toplevel):
    def __init__(self, master, title, text, size="760x620"):
        super().__init__(master)
        self.title(title)
        self.geometry(size)
        self.transient(master)
        t = tk.Text(self, wrap="word", font=(TH.FAM, 10), padx=12, pady=10)
        sb = ttk.Scrollbar(self, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(fill="both", expand=True)
        t.insert("1.0", text)
        t.config(state="disabled")


# ============================================================================
class AboutDialog(tk.Toplevel):
    """정보 — 제품명·버전·경로·오픈소스 고지."""
    NOTICES = (("ezdxf", "MIT"), ("Pillow", "MIT-CMU"), ("tkinterdnd2", "MIT"), ("sql.js", "MIT"),
               ("Capacitor", "MIT"), ("LibreDWG / ODA File Converter", "DWG 변환 시 사용자 설치 프로그램 사용"))

    def __init__(self, master, rows=()):
        from . import __version__
        super().__init__(master)
        self.title(f"{TH.APP_NAME} 정보")
        self.configure(bg=TH.PANEL)
        self.transient(master)
        self.resizable(False, False)
        hd = tk.Frame(self, bg=TH.NAVY, padx=22, pady=16)
        hd.pack(fill="x")
        logo = TH.image("icon_64.png")
        if logo is not None:
            tk.Label(hd, image=logo, bg=TH.NAVY).pack(side="left", padx=(0, 14))
        tt = tk.Frame(hd, bg=TH.NAVY)
        tt.pack(side="left")
        tk.Label(tt, text=f"{TH.APP_NAME} {TH.APP_SUB}", bg=TH.NAVY, fg="white", font=TH.FONT_XL).pack(anchor="w")
        tk.Label(tt, text=f"버전 {__version__}", bg=TH.NAVY, fg=TH.ORANGE, font=TH.FONT_B).pack(anchor="w")
        body = tk.Frame(self, bg=TH.PANEL, padx=22, pady=14)
        body.pack(fill="both")
        tk.Label(body, bg=TH.PANEL, fg=TH.INK, font=TH.FONT_M, justify="left", text=(
            "구조·건축 평면도(DXF/DWG)에서 기둥·거더·보·벽을 찾아 중심선과 절점으로 정리하고,\n"
            "부재리스트와 현장조사(휴대폰·패드 연동), 간이 휨·전단 검토를 지원합니다.\n"
            "좌표·길이·크기는 도면 형상에서 직접 계산하며, AI(Ollama)는 레이어·부재명 해석과 검토에만 씁니다.")
                 ).pack(anchor="w")
        tk.Label(body, bg=TH.PANEL, fg=TH.WARN, font=TH.FONT_S, justify="left", text=(
            "간이 검토 결과는 현장 판단을 돕는 참고값이며 구조설계 검토를 대신하지 않습니다.")).pack(anchor="w", pady=(6, 0))
        if rows:
            g = tk.Frame(body, bg=TH.PANEL)
            g.pack(anchor="w", pady=(12, 0))
            for i, (k, v) in enumerate(rows):
                tk.Label(g, text=k, bg=TH.PANEL, fg=TH.MUTED, font=TH.FONT).grid(row=i, column=0, sticky="w", padx=(0, 12))
                tk.Label(g, text=v, bg=TH.PANEL, fg=TH.INK, font=TH.FONT).grid(row=i, column=1, sticky="w")
        tk.Label(body, text="오픈소스 구성요소", bg=TH.PANEL, fg=TH.NAVY, font=TH.FONT_B).pack(anchor="w", pady=(14, 2))
        tk.Label(body, bg=TH.PANEL, fg=TH.MUTED, font=TH.FONT_S, justify="left",
                 text="\n".join(f"· {n} — {lic}" for n, lic in self.NOTICES)).pack(anchor="w")
        bf = tk.Frame(self, bg=TH.PANEL, padx=22, pady=12)
        bf.pack(fill="x")
        tk.Label(bf, text=TH.COPYRIGHT, bg=TH.PANEL, fg=TH.NAVY_L, font=TH.FONT_S).pack(side="left")
        ttk.Button(bf, text="닫기", style="Navy.TButton", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
