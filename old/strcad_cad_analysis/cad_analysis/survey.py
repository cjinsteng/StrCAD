"""현장조사 (field survey) records per member — for 구조안전성검토 / 내진성능평가.

Stored on Member.survey (dict) so it is saved with the analysis in the DB.
"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
import tkinter as tk
from datetime import date
from tkinter import ttk, filedialog, messagebox

from .model import KIND_KO

FONT = ("Malgun Gothic", 9)
GRADES = ("", "A", "B", "C", "D", "E")
GRADE_COLOR = {"A": "#16a34a", "B": "#65a30d", "C": "#eab308", "D": "#f97316", "E": "#dc2626"}
DAMAGE = (("crack", "균열"), ("spall", "박리·박락"), ("rebar", "철근노출"), ("efflor", "백화"),
          ("leak", "누수"), ("deflect", "처짐·변형"))


def summary(sv: dict) -> str:
    if not sv:
        return "-"
    parts = []
    if sv.get("grade"):
        parts.append(f"등급 {sv['grade']}")
    if sv.get("fc_rebound") or sv.get("fc_core"):
        parts.append("fc " + "/".join(str(v) for v in (sv.get("fc_rebound"), sv.get("fc_core")) if v) + " MPa")
    d = [k for key, k in DAMAGE if sv.get(key)]
    if d:
        parts.append(",".join(d) + (f"(균열폭 {sv['crack_w']}mm)" if sv.get("crack") and sv.get("crack_w") else ""))
    if sv.get("photos"):
        parts.append(f"사진 {len(sv['photos'])}")
    return " · ".join(parts) or "기록 있음"


def size_diff(m, sv) -> str:
    """Measured vs drawing size."""
    try:
        a = float(sv.get("meas_b") or 0)
        b = float(sv.get("meas_h") or 0)
    except ValueError:
        return ""
    if not a:
        return ""
    if m.kind == "column":
        da, db = a - m.b, (b - m.h) if b else 0
        return f"실측 {a:.0f}×{b:.0f} (도면 대비 {da:+.0f}/{db:+.0f})" if b else f"실측 {a:.0f} ({da:+.0f})"
    dw = a - m.width
    s = f"실측 폭 {a:.0f} ({dw:+.0f})"
    if b:
        s += f", 춤 {b:.0f}" + (f" ({b - m.depth:+.0f})" if m.depth else "")
    return s


def _open_file(p):
    try:
        if os.name == "nt":
            os.startfile(p)          # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except Exception as e:           # noqa: BLE001
        messagebox.showerror("열기", str(e))


# ============================================================================
class SurveyDialog(tk.Toplevel):
    def __init__(self, master, member, on_save):
        super().__init__(master)
        self.m = member
        self.on_save = on_save
        sv = dict(member.survey or {})
        self.title(f"현장조사 — {KIND_KO[member.kind]} {member.display_name()} #{member.id}")
        self.transient(master)
        self.resizable(False, False)
        f = ttk.Frame(self, padding=10)
        f.pack(fill="both")
        self.v = {}

        def ent(key, label, r, c, w=12, default=""):
            ttk.Label(f, text=label, font=FONT).grid(row=r, column=c, sticky="w", padx=(0 if c == 0 else 10, 4), pady=2)
            var = tk.StringVar(value=str(sv.get(key, default) or ""))
            ttk.Entry(f, textvariable=var, width=w).grid(row=r, column=c + 1, sticky="w", pady=2)
            self.v[key] = var

        ttk.Label(f, text=f"도면: {member.size_text()}" + (f"  L={member.length_cc:,.0f}" if member.kind != "column" else ""),
                  foreground="#555", font=FONT).grid(row=0, column=0, columnspan=4, sticky="w")
        ent("date", "조사일", 1, 0, default=date.today().isoformat())
        ent("inspector", "조사자", 1, 2)
        ent("location", "위치/층", 2, 0)
        lb = ("실측 b", "실측 h") if member.kind == "column" else (("실측 두께", "-") if member.kind == "wall"
                                                                 else ("실측 폭 B", "실측 춤 D"))
        ent("meas_b", lb[0] + " (mm)", 3, 0, 8)
        if lb[1] != "-":
            ent("meas_h", lb[1] + " (mm)", 3, 2, 8)

        sep = ttk.Separator(f)
        sep.grid(row=4, column=0, columnspan=4, sticky="ew", pady=6)
        ent("fc_rebound", "반발경도 추정강도 (MPa)", 5, 0, 8)
        ent("fc_core", "코어 압축강도 (MPa)", 5, 2, 8)
        ent("carbonation", "탄산화 깊이 (mm)", 6, 0, 8)
        ent("cover", "피복두께 (mm)", 6, 2, 8)
        ent("rebar_main", "주근 (탐사)", 7, 0)
        ent("rebar_tie", "띠철근/스터럽 간격", 7, 2)

        ttk.Separator(f).grid(row=8, column=0, columnspan=4, sticky="ew", pady=6)
        dmg = ttk.Frame(f)
        dmg.grid(row=9, column=0, columnspan=4, sticky="w")
        ttk.Label(dmg, text="손상", font=FONT).pack(side="left", padx=(0, 6))
        self.b = {}
        for key, ko in DAMAGE:
            var = tk.BooleanVar(value=bool(sv.get(key)))
            ttk.Checkbutton(dmg, text=ko, variable=var).pack(side="left", padx=2)
            self.b[key] = var
        ent("crack_w", "최대 균열폭 (mm)", 10, 0, 8)
        ent("crack_l", "균열 길이 (m)", 10, 2, 8)
        ttk.Label(f, text="상태등급", font=FONT).grid(row=11, column=0, sticky="w", pady=2)
        self.grade = tk.StringVar(value=sv.get("grade", ""))
        ttk.Combobox(f, textvariable=self.grade, values=GRADES, state="readonly", width=5).grid(
            row=11, column=1, sticky="w")

        ttk.Label(f, text="사진", font=FONT).grid(row=12, column=0, sticky="nw", pady=(6, 0))
        pf = ttk.Frame(f)
        pf.grid(row=12, column=1, columnspan=3, sticky="w", pady=(6, 0))
        self.photos = list(sv.get("photos", []))
        self.ph_list = tk.Listbox(pf, height=4, width=46, font=FONT)
        self.ph_list.pack(side="left")
        self.ph_list.bind("<Double-1>", lambda e: self._open_photo())
        pb = ttk.Frame(pf)
        pb.pack(side="left", padx=4)
        ttk.Button(pb, text="추가", command=self._add_photo).pack(fill="x")
        ttk.Button(pb, text="열기", command=self._open_photo).pack(fill="x", pady=2)
        ttk.Button(pb, text="제거", command=self._del_photo).pack(fill="x")
        self._fill_photos()

        ttk.Label(f, text="메모", font=FONT).grid(row=13, column=0, sticky="nw", pady=(6, 0))
        self.memo = tk.Text(f, width=52, height=4, font=FONT)
        self.memo.grid(row=13, column=1, columnspan=3, sticky="w", pady=(6, 0))
        self.memo.insert("1.0", sv.get("memo", ""))

        bf = ttk.Frame(f)
        bf.grid(row=14, column=0, columnspan=4, sticky="e", pady=(10, 0))
        ttk.Button(bf, text="기록 삭제", command=self._clear).pack(side="left", padx=4)
        ttk.Button(bf, text="취소", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(bf, text="저장", command=self._save).pack(side="left")
        self.grab_set()

    def _fill_photos(self):
        self.ph_list.delete(0, "end")
        for p in self.photos:
            self.ph_list.insert("end", os.path.basename(p))

    def _add_photo(self):
        ps = filedialog.askopenfilenames(parent=self, title="사진 선택",
                                         filetypes=[("이미지", "*.jpg *.jpeg *.png *.bmp *.heic"), ("모든 파일", "*.*")])
        for p in ps:
            if p not in self.photos:
                self.photos.append(p)
        self._fill_photos()

    def _sel_photo(self):
        s = self.ph_list.curselection()
        return self.photos[s[0]] if s else None

    def _open_photo(self):
        p = self._sel_photo()
        if p:
            _open_file(p)

    def _del_photo(self):
        p = self._sel_photo()
        if p:
            self.photos.remove(p)
            self._fill_photos()

    def _clear(self):
        if messagebox.askyesno("현장조사", "이 부재의 조사 기록을 삭제할까요?", parent=self):
            self.destroy()
            self.on_save(self.m, {})

    def _save(self):
        sv = {k: v.get().strip() for k, v in self.v.items() if v.get().strip()}
        for k, v in self.b.items():
            if v.get():
                sv[k] = True
        if self.grade.get():
            sv["grade"] = self.grade.get()
        memo = self.memo.get("1.0", "end").strip()
        if memo:
            sv["memo"] = memo
        if self.photos:
            sv["photos"] = list(self.photos)
        self.destroy()
        self.on_save(self.m, sv)


# ============================================================================
class SurveyListDialog(tk.Toplevel):
    def __init__(self, master, members, on_pick):
        super().__init__(master)
        self.title("현장조사 현황")
        self.geometry("980x420")
        self.transient(master)
        self.on_pick = on_pick
        done = [m for m in members if m.survey]
        tot = {k: sum(1 for m in members if m.kind == k) for k in KIND_KO}
        cnt = {k: sum(1 for m in done if m.kind == k) for k in KIND_KO}
        ttk.Label(self, padding=6, font=FONT, text="조사 부재: " + " · ".join(
            f"{KIND_KO[k]} {cnt[k]}/{tot[k]}" for k in KIND_KO)).pack(fill="x")
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=6)
        cols = ("kind", "name", "size", "grade", "fc", "dmg", "diff", "date")
        tv = ttk.Treeview(frm, columns=cols, show="headings")
        for c, t, w in (("kind", "종류", 60), ("name", "부재", 90), ("size", "도면 크기", 90), ("grade", "등급", 50),
                        ("fc", "강도(반발/코어)", 110), ("dmg", "손상", 200), ("diff", "실측 비교", 220),
                        ("date", "조사일", 90)):
            tv.heading(c, text=t)
            tv.column(c, width=w)
        sb = ttk.Scrollbar(frm, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tv.pack(fill="both", expand=True)
        for m in sorted(done, key=lambda x: (x.kind, x.name, x.id)):
            sv = m.survey
            tv.insert("", "end", iid=str(m.id), values=(
                KIND_KO[m.kind], f"{m.display_name()} #{m.id}", m.size_text(), sv.get("grade", ""),
                "/".join(str(sv.get(k, "-")) for k in ("fc_rebound", "fc_core")),
                ", ".join(ko for key, ko in DAMAGE if sv.get(key)), size_diff(m, sv), sv.get("date", "")))
        tv.bind("<Double-1>", lambda e: tv.selection() and self.on_pick(int(tv.selection()[0])))
        ttk.Label(self, text="더블클릭: 도면에서 해당 부재로 이동", foreground="#666", padding=4).pack(anchor="w")


def export_csv(path, members):
    rows = []
    for m in members:
        if not m.survey:
            continue
        sv = m.survey
        rows.append({
            "ID": m.id, "종류": KIND_KO[m.kind], "부재명": m.name, "도면크기": m.size_text(),
            "L(mm)": round(m.length_cc) if m.kind != "column" else "",
            "조사일": sv.get("date", ""), "조사자": sv.get("inspector", ""), "위치": sv.get("location", ""),
            "실측1": sv.get("meas_b", ""), "실측2": sv.get("meas_h", ""), "실측비교": size_diff(m, sv),
            "반발경도강도(MPa)": sv.get("fc_rebound", ""), "코어강도(MPa)": sv.get("fc_core", ""),
            "탄산화(mm)": sv.get("carbonation", ""), "피복(mm)": sv.get("cover", ""),
            "주근": sv.get("rebar_main", ""), "띠철근/스터럽": sv.get("rebar_tie", ""),
            **{ko: ("O" if sv.get(k) else "") for k, ko in DAMAGE},
            "균열폭(mm)": sv.get("crack_w", ""), "균열길이(m)": sv.get("crack_l", ""),
            "상태등급": sv.get("grade", ""), "사진수": len(sv.get("photos", [])), "메모": sv.get("memo", ""),
        })
    if not rows:
        return 0
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return len(rows)
