"""현장조사 — 번호 검측위치 + 용도별 입력 (부재검측 / 균열검토 / 사용자 추가 용도).

A record is a plain dict in AnalysisResult.surveys (saved with the analysis in the DB):
  id, no (1,2,3…), purpose ("부재검측"), member (id|None), t0, t1 (position along a linear
  member, 0..1; t1=None for a point), x, y (placed position), dx, dy (offset inside a column),
  bx, by (number-bubble offset from the point, mm), name (부재명), size_b, size_h (mm), length (m),
  rebar {"상부근|I단": "4-HD22", …}, exist ("존재"/"없음"/"상이"), fields {…}, photos [...], memo, date
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

# --------------------------------------------------------------------------- purposes
# name: {color, size, length, rebar, exist, fields: [(key, label, unit, choices)]}
DEFAULT_PURPOSES = {
    "부재검측": {"color": "#d62828", "size": True, "length": True, "rebar": True, "exist": True, "fields": []},
    "균열검토": {"color": "#ea580c", "size": False, "length": False, "rebar": False, "exist": False, "fields": [
        ["crack_w", "균열폭", "mm", None],
        ["crack_l", "균열길이", "m", None],
        ["shape", "균열형태", "", ["수직", "수평", "경사", "망상", "기타"]],
        ["face", "위치(면)", "", ["상면", "하면", "측면", "단부", "중앙"]],
        ["progress", "진행성", "", ["없음", "있음", "관찰필요"]]]},
}
EXTRA_COLORS = ("#2563eb", "#7c3aed", "#0f766e", "#ca8a04", "#db2777", "#0891b2", "#4d7c0f", "#6b7280")
EXIST = ("존재", "없음", "상이(도면과 다름)")


def purposes(cfg) -> dict:
    """Default purposes + user-added ones (settings)."""
    out = {k: dict(v) for k, v in DEFAULT_PURPOSES.items()}
    for name, p in (cfg.get("survey_purposes") or {}).items():
        out[name] = p
    return out


def add_purpose(cfg, name, field_labels, size=False, length=False, rebar=False, exist=False):
    cur = cfg.setdefault("survey_purposes", {})
    n = len(cur)
    fields = []
    for i, lab in enumerate([f.strip() for f in field_labels if f.strip()]):
        unit = ""
        if "(" in lab and lab.endswith(")"):
            lab, unit = lab[:lab.index("(")].strip(), lab[lab.index("(") + 1:-1]
        fields.append([f"f{i + 1}", lab, unit, None])
    cur[name] = {"color": EXTRA_COLORS[n % len(EXTRA_COLORS)], "size": size, "length": length,
                 "rebar": rebar, "exist": exist, "fields": fields}
    return cur[name]


# --------------------------------------------------------------------------- rebar grid
def rebar_layout(kind):
    if kind == "column":
        return ["주근", "띠철근"], ["단부", "중앙"]
    if kind == "wall":
        return ["배근"], ["수직근", "수평근"]
    return ["상부근", "하부근", "스터럽"], ["I단", "중앙", "J단"]


# --------------------------------------------------------------------------- records
def next_no(surveys):
    return max((int(s.get("no") or 0) for s in surveys), default=0) + 1


def member_name(m):
    if m is None:
        return ""
    return f"{KIND_KO[m.kind]} {m.name}".strip() if m.name else KIND_KO[m.kind]


def new_record(surveys, purpose, member, t0, t1, x, y, bubble=(0.0, 0.0)):
    sid = max((s["id"] for s in surveys), default=0) + 1
    return {"id": sid, "no": next_no(surveys), "purpose": purpose,
            "member": member.id if member else None, "t0": t0, "t1": t1, "x": x, "y": y,
            "bx": bubble[0], "by": bubble[1], "name": member_name(member),
            "size_b": "", "size_h": "", "length": "", "rebar": {}, "exist": "존재" if member else "",
            "fields": {}, "photos": [], "memo": "", "date": date.today().isoformat()}


def migrate(rec):
    """v2.3 records (type/label/data) → v2.4 format, in place."""
    if "purpose" in rec:
        return rec
    t = rec.get("type")
    d = rec.get("data", {})
    rec["purpose"] = {"size": "부재검측", "rebar": "부재검측", "damage": "균열검토"}.get(t, "부재검측")
    rec.setdefault("no", rec.get("id"))
    rec.setdefault("bx", 0.0)
    rec.setdefault("by", 0.0)
    rec.setdefault("name", "")
    rec["size_b"], rec["size_h"] = d.get("b", ""), d.get("h", "")
    rec.setdefault("length", "")
    rec["rebar"] = {}
    if t == "rebar":
        rec["rebar"] = {"상부근|중앙": d.get("main", ""), "스터럽|중앙": d.get("tie", "")}
    rec.setdefault("exist", "존재")
    rec["fields"] = {"crack_w": d.get("crack_w", ""), "crack_l": d.get("crack_l", "")} if t == "damage" else {}
    old = rec.get("memo", "")
    if t not in ("size", "rebar", "damage") and d:
        old = (old + "\n" if old else "") + ", ".join(f"{k}={v}" for k, v in d.items())
    rec["memo"] = old
    return rec


def _lin_pt(m, t):
    return (m.p1[0] + (m.p2[0] - m.p1[0]) * t, m.p1[1] + (m.p2[1] - m.p1[1]) * t)


def geometry(rec, byid):
    """("point", p) or ("span", a, b) — follows the member when it is edited."""
    m = byid.get(rec.get("member"))
    if m is not None and m.kind != "column" and not m.curved and rec.get("t0") is not None:
        a = _lin_pt(m, rec["t0"])
        if rec.get("t1") is not None:
            return ("span", a, _lin_pt(m, rec["t1"]))
        return ("point", a)
    if m is not None and m.kind == "column" and rec.get("dx") is not None:
        return ("point", (m.center[0] + rec["dx"], m.center[1] + rec["dy"]))
    return ("point", (rec["x"], rec["y"]))


def anchor(rec, byid):
    g = geometry(rec, byid)
    if g[0] == "span":
        return ((g[1][0] + g[2][0]) / 2, (g[1][1] + g[2][1]) / 2)
    return g[1]


def bubble(rec, byid):
    ax, ay = anchor(rec, byid)
    return ax + rec.get("bx", 0.0), ay + rec.get("by", 0.0)


def position_text(rec, byid):
    m = byid.get(rec.get("member"))
    if m is None:
        return "부재 미지정" if rec.get("member") is None else "(부재 삭제됨)"
    s = f"{KIND_KO[m.kind]} {m.display_name()} #{m.id}"
    if m.kind != "column" and rec.get("t0") is not None:
        a = rec["t0"] * m.length_cc
        if rec.get("t1") is not None:
            b = rec["t1"] * m.length_cc
            s += f" · i단 {min(a, b):,.0f}~{max(a, b):,.0f} mm"
        else:
            s += f" · i단에서 {a:,.0f} mm"
    return s


def drawing_text(rec, byid):
    m = byid.get(rec.get("member"))
    if m is None:
        return ""
    s = f"도면: {m.size_text()}"
    if m.kind != "column":
        s += f", L={m.length_cc / 1000:.2f} m"
    return s


def rebar_filled(rec):
    return any(v for v in rec.get("rebar", {}).values())


def summary(rec, P):
    p = P.get(rec["purpose"], {})
    parts = []
    if p.get("size") and (rec.get("size_b") or rec.get("size_h")):
        parts.append(f"{rec.get('size_b') or '?'}×{rec.get('size_h') or '?'}")
    if p.get("length") and rec.get("length"):
        parts.append(f"L={rec['length']}m")
    if p.get("rebar"):
        parts.append("철근 입력" if rebar_filled(rec) else "")
    if p.get("exist") and rec.get("exist") and rec["exist"] != "존재":
        parts.append(rec["exist"])
    for key, lab, unit, _ in p.get("fields", []):
        v = rec.get("fields", {}).get(key)
        if v:
            parts.append(f"{lab} {v}{unit}")
    return " · ".join(x for x in parts if x)


def member_summary(surveys, m, P):
    recs = sorted((s for s in surveys if s.get("member") == m.id), key=lambda s: s["no"])
    if not recs:
        return "-"
    return "\n".join(f"#{s['no']} {s['purpose']}: {summary(s, P) or '-'}" for s in recs[:6]) + \
        (f"\n… 외 {len(recs) - 6}건" if len(recs) > 6 else "")


def size_compare(rec, byid):
    m = byid.get(rec.get("member"))
    try:
        b = float(rec.get("size_b") or 0)
        h = float(rec.get("size_h") or 0)
    except ValueError:
        return ""
    if m is None or not b:
        return ""
    if m.kind == "column":
        return f"{b - m.b:+.0f}/{h - m.h:+.0f}" if h else f"{b - m.b:+.0f}"
    s = f"폭 {b - m.width:+.0f}"
    if h and m.depth:
        s += f", 춤 {h - m.depth:+.0f}"
    return s


def open_file(p):
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
#  popups used by the survey panel
# ============================================================================
class RebarDialog(tk.Toplevel):
    """철근 클릭 시 — I단/중앙/J단 × 상부근/하부근/스터럽 (부재 종류별 배치)."""

    def __init__(self, master, rec, kind, on_save):
        super().__init__(master)
        self.title(f"철근 — #{rec['no']} {rec.get('name', '')}")
        self.transient(master)
        self.resizable(False, False)
        self.configure(bg="#e5e7eb")
        rows, cols = rebar_layout(kind)
        cur = rec.get("rebar", {})
        f = tk.Frame(self, bg="#e5e7eb", padx=14, pady=12)
        f.pack()
        tk.Label(f, text="", bg="#e5e7eb").grid(row=0, column=0)
        for j, c in enumerate(cols):
            tk.Label(f, text=c, bg=BLUE, fg="white", font=("Malgun Gothic", 11, "bold"), width=10, pady=6).grid(
                row=0, column=j + 1, padx=4, pady=4)
        self.v = {}
        for i, r in enumerate(rows):
            tk.Label(f, text=r, bg=BLUE_D, fg="white", font=("Malgun Gothic", 10, "bold"), width=6, pady=8).grid(
                row=i + 1, column=0, padx=4, pady=4)
            for j, c in enumerate(cols):
                var = tk.StringVar(value=cur.get(f"{r}|{c}", ""))
                e = tk.Entry(f, textvariable=var, width=11, font=("Malgun Gothic", 11), justify="center",
                             bg=BLUE, fg="white", insertbackground="white", relief="flat")
                e.grid(row=i + 1, column=j + 1, padx=4, pady=4, ipady=6)
                self.v[f"{r}|{c}"] = var
        tk.Label(f, text="예) 상·하부근 4-HD22, 스터럽 HD10@200, 띠철근 HD10@300", bg="#e5e7eb", fg="#555",
                 font=FONT).grid(row=len(rows) + 1, column=0, columnspan=len(cols) + 1, sticky="w", pady=(6, 0))
        b = tk.Frame(f, bg="#e5e7eb")
        b.grid(row=len(rows) + 2, column=0, columnspan=len(cols) + 1, sticky="e", pady=(8, 0))
        ttk.Button(b, text="취소", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(b, text="확인", command=lambda: (on_save({k: v.get().strip() for k, v in self.v.items()
                                                           if v.get().strip()}), self.destroy())).pack(side="left")
        self.grab_set()


class PhotoDialog(tk.Toplevel):
    def __init__(self, master, rec, on_save):
        super().__init__(master)
        self.title(f"사진 — #{rec['no']}")
        self.transient(master)
        self.photos = list(rec.get("photos", []))
        f = ttk.Frame(self, padding=10)
        f.pack()
        self.lb = tk.Listbox(f, width=60, height=8, font=FONT)
        self.lb.grid(row=0, column=0, rowspan=4)
        self.lb.bind("<Double-1>", lambda e: self._open())
        ttk.Button(f, text="추가", command=self._add).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(f, text="열기", command=self._open).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Button(f, text="제거", command=self._del).grid(row=2, column=1, sticky="ew", padx=4)
        ttk.Button(f, text="확인", command=lambda: (on_save(self.photos), self.destroy())).grid(
            row=3, column=1, sticky="sew", padx=4)
        self._fill()
        self.grab_set()

    def _fill(self):
        self.lb.delete(0, "end")
        for p in self.photos:
            self.lb.insert("end", os.path.basename(p))

    def _add(self):
        for p in filedialog.askopenfilenames(parent=self, title="사진 선택",
                                             filetypes=[("이미지", "*.jpg *.jpeg *.png *.bmp *.heic"), ("모든 파일", "*.*")]):
            if p not in self.photos:
                self.photos.append(p)
        self._fill()

    def _sel(self):
        s = self.lb.curselection()
        return self.photos[s[0]] if s else None

    def _open(self):
        p = self._sel()
        if p:
            open_file(p)

    def _del(self):
        p = self._sel()
        if p:
            self.photos.remove(p)
            self._fill()


class MemoDialog(tk.Toplevel):
    def __init__(self, master, rec, on_save):
        super().__init__(master)
        self.title(f"추가사항 — #{rec['no']}")
        self.transient(master)
        f = ttk.Frame(self, padding=10)
        f.pack()
        self.t = tk.Text(f, width=56, height=10, font=("Malgun Gothic", 10))
        self.t.pack()
        self.t.insert("1.0", rec.get("memo", ""))
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(6, 0))
        ttk.Button(b, text="확인", command=lambda: (on_save(self.t.get("1.0", "end").strip()), self.destroy())).pack(
            side="right")
        ttk.Button(b, text="취소", command=self.destroy).pack(side="right", padx=4)
        self.t.focus_set()
        self.grab_set()


class PurposeDialog(tk.Toplevel):
    """용도 추가 — 이름, 입력 항목, 공통 항목 포함 여부."""

    def __init__(self, master, on_save):
        super().__init__(master)
        self.title("용도 추가")
        self.transient(master)
        self.resizable(False, False)
        f = ttk.Frame(self, padding=12)
        f.pack()
        ttk.Label(f, text="용도 이름").grid(row=0, column=0, sticky="w")
        self.name = tk.StringVar()
        ttk.Entry(f, textvariable=self.name, width=30).grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(f, text="입력 항목").grid(row=1, column=0, sticky="w")
        self.fields = tk.StringVar()
        ttk.Entry(f, textvariable=self.fields, width=44).grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(f, text="쉼표로 구분, 단위는 괄호 — 예) 반발도 평균, 추정강도(MPa), 타격방향", foreground="#666",
                  font=FONT).grid(row=2, column=1, sticky="w")
        self.flags = {k: tk.BooleanVar(value=False) for k in ("size", "length", "rebar", "exist")}
        cf = ttk.Frame(f)
        cf.grid(row=3, column=1, sticky="w", pady=4)
        for k, t in (("size", "치수"), ("length", "길이"), ("rebar", "철근"), ("exist", "부재유무")):
            ttk.Checkbutton(cf, text=t, variable=self.flags[k]).pack(side="left", padx=2)
        ttk.Label(f, text="공통 항목").grid(row=3, column=0, sticky="w")
        b = ttk.Frame(f)
        b.grid(row=4, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(b, text="취소", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(b, text="추가", command=self._ok).pack(side="left")
        self.on_save = on_save
        self.grab_set()

    def _ok(self):
        n = self.name.get().strip()
        if not n:
            return
        self.destroy()
        self.on_save(n, self.fields.get().split(","), **{k: v.get() for k, v in self.flags.items()})


BLUE = "#4a90d9"
BLUE_D = "#2f6db5"


# ============================================================================
def export_csv(path, surveys, byid, P, floor=""):
    extra = []
    for name, p in P.items():
        for key, lab, unit, _ in p.get("fields", []):
            col = f"{name}:{lab}" + (f"({unit})" if unit else "")
            extra.append((name, key, col))
    rebar_cols = []
    for kind in ("girder", "column", "wall"):
        rows, cols = rebar_layout(kind)
        for r in rows:
            for c in cols:
                if f"철근 {r}|{c}" not in rebar_cols:
                    rebar_cols.append(f"철근 {r}|{c}")
    out = []
    for s in sorted(surveys, key=lambda s: s["no"]):
        m = byid.get(s.get("member"))
        x, y = anchor(s, byid)
        row = {"층/도면": floor, "번호": s["no"], "용도": s["purpose"], "부재명": s.get("name", ""),
               "부재ID": m.id if m else "", "도면크기": m.size_text() if m else "",
               "도면길이(m)": round(m.length_cc / 1000, 2) if m and m.kind != "column" else "",
               "위치": position_text(s, byid), "X": round(x, 1), "Y": round(y, 1),
               "실측 b(mm)": s.get("size_b", ""), "실측 h(mm)": s.get("size_h", ""), "도면대비": size_compare(s, byid),
               "실측 길이(m)": s.get("length", ""), "부재유무": s.get("exist", "")}
        for col in rebar_cols:
            row[col] = s.get("rebar", {}).get(col[3:], "")
        for name, key, col in extra:
            row[col] = s.get("fields", {}).get(key, "") if s["purpose"] == name else ""
        row.update({"사진수": len(s.get("photos", [])), "사진": " | ".join(s.get("photos", [])),
                    "추가사항": s.get("memo", ""), "조사일": s.get("date", "")})
        out.append(row)
    if not out:
        return 0
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    return len(out)
