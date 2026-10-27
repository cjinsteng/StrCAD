"""Dialogs: layer mapping, coordinate system, DB browser."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from . import db
from .model import LAYER_ROLES, LAYER_ROLE_KO, CoordSystem

FONT = ("Malgun Gothic", 9)


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
    """Saved analyses: open / rename / delete."""

    def __init__(self, master, on_open, db_path=None):
        super().__init__(master)
        self.title("저장된 분석 불러오기")
        self.geometry("860x420")
        self.transient(master)
        self.on_open = on_open
        self.db_path = db_path or db.DB_PATH   # resolved at open time
        ttk.Label(self, text=f"DB: {self.db_path}", foreground="#666", padding=(6, 4)).pack(fill="x")
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=6)
        cols = ("name", "file", "cnt", "date")
        self.tv = ttk.Treeview(frm, columns=cols, show="headings", selectmode="browse")
        for c, t, w in (("name", "이름", 220), ("file", "도면 파일", 260), ("cnt", "기둥/거더/보/벽", 140),
                        ("date", "수정일", 150)):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=w)
        sb = ttk.Scrollbar(frm, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tv.pack(side="left", fill="both", expand=True)
        self.tv.bind("<Double-1>", lambda e: self._open())
        b = ttk.Frame(self, padding=6)
        b.pack(fill="x")
        ttk.Button(b, text="열기", command=self._open).pack(side="left")
        ttk.Button(b, text="이름 변경", command=self._rename).pack(side="left", padx=4)
        ttk.Button(b, text="삭제", command=self._delete).pack(side="left")
        ttk.Button(b, text="닫기", command=self.destroy).pack(side="right")
        self._fill()
        self.grab_set()

    def _fill(self):
        self.tv.delete(*self.tv.get_children())
        for (aid, name, path, upd, nc, ng, nb, nw) in db.list_analyses(self.db_path):
            self.tv.insert("", "end", iid=str(aid),
                           values=(name, os.path.basename(path or ""), f"{nc}/{ng}/{nb}/{nw}", upd.replace("T", " ")))

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
        old = self.tv.item(str(aid), "values")[0]
        new = simpledialog.askstring("이름 변경", "새 이름:", initialvalue=old, parent=self)
        if new:
            db.rename(aid, new.strip(), self.db_path)
            self._fill()

    def _delete(self):
        aid = self._sel()
        if aid is None:
            return
        name = self.tv.item(str(aid), "values")[0]
        if messagebox.askyesno("삭제", f"'{name}' 분석을 DB에서 삭제할까요?", parent=self):
            db.delete(aid, self.db_path)
            self._fill()


# ============================================================================
class ReviewDialog(tk.Toplevel):
    """AI/규칙 검토 제안 목록 — 체크한 항목만 적용."""
    ACT_KO = {"merge": "연결(절점 합침)", "keep": "유지", "to_wall": "벽으로 변경"}
    TYPE_KO = {"joint": "미연결 절점", "col_wall": "기둥→벽 의심"}

    def __init__(self, master, cands, on_apply, on_focus):
        super().__init__(master)
        self.title("AI 검토 결과")
        self.geometry("980x460")
        self.transient(master)
        self.cands = {c["id"]: c for c in cands}
        self.on_apply, self.on_focus = on_apply, on_focus
        n_ai = sum(1 for c in cands if c["source"] == "AI")
        ttk.Label(self, padding=6, font=FONT, text=(
            f"검토 대상 {len(cands)}건 (AI 판단 {n_ai}, 규칙 판단 {len(cands) - n_ai}). "
            "변경 제안은 기본 체크되어 있습니다. 행 클릭 = 도면에서 위치 보기, ☑ 칸 클릭 = 적용 여부 전환."
        )).pack(fill="x")
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=6)
        cols = ("chk", "type", "member", "act", "src", "reason", "info")
        self.tv = ttk.Treeview(frm, columns=cols, show="headings", selectmode="browse")
        for c, t, w in (("chk", "적용", 46), ("type", "유형", 100), ("member", "부재", 190), ("act", "제안", 110),
                        ("src", "판정", 50), ("reason", "근거", 220), ("info", "수치", 240)):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=w, anchor="center" if c in ("chk", "src") else "w")
        sb = ttk.Scrollbar(frm, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tv.pack(fill="both", expand=True)
        self.tv.tag_configure("keep", foreground="#888")
        self.chk = {}
        order = sorted(cands, key=lambda c: (c["action"] == "keep", c["type"], c["id"]))
        for c in order:
            self.chk[c["id"]] = c["action"] != "keep"
            f = c["features"]
            if c["type"] == "joint":
                mem, info = f["member"], f"간격 {f['gap_mm']} · 축방향 {f['ahead_along_axis_mm']} · 옆 {f['sideways_offset_mm']} → {f['target']}"
            else:
                mem = f["column"]
                info = f"비 {f['aspect']} · 일직선 벽 {f['walls_continuing_in_line']} · C표기 {'O' if f['has_column_mark'] else 'X'}"
            self.tv.insert("", "end", iid=c["id"], tags=("keep",) if c["action"] == "keep" else (),
                           values=("☑" if self.chk[c["id"]] else "☐", self.TYPE_KO[c["type"]], mem,
                                   self.ACT_KO[c["action"]], c["source"], c["reason"], info))
        self.tv.bind("<ButtonRelease-1>", self._click)
        b = ttk.Frame(self, padding=6)
        b.pack(fill="x")
        ttk.Button(b, text="변경 제안 모두 선택", command=lambda: self._all(True)).pack(side="left")
        ttk.Button(b, text="모두 해제", command=lambda: self._all(False)).pack(side="left", padx=4)
        ttk.Button(b, text="닫기", command=self.destroy).pack(side="right")
        ttk.Button(b, text="체크한 항목 적용 ▶", command=self._apply).pack(side="right", padx=6)

    def _set(self, iid, v):
        c = self.cands[iid]
        if c["action"] == "keep":
            v = False
        self.chk[iid] = v
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
        t = tk.Text(self, wrap="word", font=("Malgun Gothic", 10), padx=12, pady=10)
        sb = ttk.Scrollbar(self, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(fill="both", expand=True)
        t.insert("1.0", text)
        t.config(state="disabled")
