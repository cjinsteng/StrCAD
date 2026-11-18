"""
design_2d/section/dialogs.py — 프레임 생성 대화상자
"""

import tkinter as tk
from tkinter import messagebox

from .theme import *


def parse_list(text):
    """'6, 6, 6' / '3@6' / '2@6, 7.5' → [6, 6, 6] ..."""
    out = []
    for tok in text.replace(" ", "").replace(";", ",").split(","):
        if not tok:
            continue
        if "@" in tok:
            n, v = tok.split("@", 1)
            out += [float(v)] * int(n)
        else:
            out.append(float(tok))
    if any(v <= 0 for v in out):
        raise ValueError
    return out


class FrameGenDialog(tk.Toplevel):
    def __init__(self, parent, model):
        super().__init__(parent)
        self.model = model
        self.result = None
        self.title("프레임 생성")
        self.configure(bg=BG2)
        self.resizable(False, False)
        self.transient(parent)
        self._build()
        self.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width() // 2 - self.winfo_reqwidth() // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_reqheight() // 2
        self.geometry(f"+{max(px, 0)}+{max(py, 0)}")
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._ok())

    def _build(self):
        hdr = tk.Frame(self, bg="#0f1a30")
        hdr.pack(fill="x")
        tk.Label(hdr, text="▦  라멘 프레임 생성", font=FONT_H, bg="#0f1a30", fg=WHI,
                 padx=14, pady=10).pack(side="left")
        body = tk.Frame(self, bg=BG2)
        body.pack(fill="both", padx=16, pady=10)
        m = self.model
        names = lambda key: [f"{i}: {v['name']}" for i, v in m[key].items()]
        pick = lambda key, i: next((f"{k}: {v['name']}" for k, v in m[key].items() if k == i),
                                   names(key)[0] if m[key] else "")
        self.v_spans = tk.StringVar(value="6, 6, 6")
        self.v_heights = tk.StringVar(value="4, 3.5")
        self.v_x0 = tk.StringVar(value="0"); self.v_y0 = tk.StringVar(value="0")
        secs = names("sections")
        beam_def = next((s for s in secs if "G" in s.split(":")[1]), secs[0] if secs else "")
        col_def = next((s for s in secs if "C" in s.split(":")[1]), secs[0] if secs else "")
        self.v_beam = tk.StringVar(value=beam_def)
        self.v_col = tk.StringVar(value=col_def)
        self.v_mat = tk.StringVar(value=pick("materials", m["defaults"].get("mat")))
        self.v_sup = tk.StringVar(value=pick("sup_types", 1))
        self.v_clear = tk.BooleanVar(value=not m["nodes"])

        f = Form(body, lw=13)
        f.row("경간 (m)", lambda p: entry(p, self.v_spans, 22))
        f.row("층고 (m)", lambda p: entry(p, self.v_heights, 22))
        tk.Label(body, text="쉼표로 구분, 반복은 '3@6' 처럼 입력 (아래층부터)",
                 font=FONT_S, bg=BG2, fg=TX3).pack(anchor="w", pady=(0, 6))
        f2 = Form(body, lw=13)
        f2.row("기준점 X", lambda p: entry(p, self.v_x0, 8), "m")
        f2.row("기준점 Y", lambda p: entry(p, self.v_y0, 8), "m")
        f2.row("보 단면", lambda p: combo(p, self.v_beam, secs, 18))
        f2.row("기둥 단면", lambda p: combo(p, self.v_col, secs, 18))
        f2.row("재료", lambda p: combo(p, self.v_mat, names("materials"), 18))
        f2.row("하단 지점", lambda p: combo(p, self.v_sup, ["없음"] + names("sup_types"), 18))
        check(body, "기존 노드·부재·하중 지우고 새로 만들기", self.v_clear).pack(anchor="w", pady=(8, 0))

        bf = tk.Frame(self, bg=BG2)
        bf.pack(fill="x", padx=16, pady=(0, 14))
        btn(bf, "생성", self._ok, bg=ACC, fg=WHI, font=FONT_B, padx=18, pady=5).pack(side="right")
        btn(bf, "취소", self.destroy, padx=14, pady=5).pack(side="right", padx=6)

    def _ok(self):
        idof = lambda s: int(s.split(":")[0]) if s and s[0].isdigit() else None
        try:
            spans = parse_list(self.v_spans.get())
            heights = parse_list(self.v_heights.get())
            x0 = float(self.v_x0.get()); y0 = float(self.v_y0.get())
        except Exception:
            messagebox.showwarning("입력", "경간/층고/기준점 값을 확인하세요.", parent=self)
            return
        if not spans or not heights:
            messagebox.showwarning("입력", "경간과 층고를 1개 이상 입력하세요.", parent=self)
            return
        if len(spans) * len(heights) > 400:
            messagebox.showwarning("입력", "너무 큰 프레임입니다.", parent=self)
            return
        self.result = dict(spans=spans, heights=heights, x0=x0, y0=y0,
                           sec_beam=idof(self.v_beam.get()), sec_col=idof(self.v_col.get()),
                           mat=idof(self.v_mat.get()), sup=idof(self.v_sup.get()),
                           clear=bool(self.v_clear.get()))
        self.destroy()
