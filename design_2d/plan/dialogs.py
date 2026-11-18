"""
design_2d/plan/dialogs.py — 격자 생성 대화상자
"""

import tkinter as tk
from tkinter import messagebox

from ..section.theme import *
from ..section.dialogs import parse_list


class GridGenDialog(tk.Toplevel):
    def __init__(self, parent, model):
        super().__init__(parent)
        self.model = model
        self.result = None
        self.title("격자 생성")
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
        hdr = tk.Frame(self, bg="#0f1a30"); hdr.pack(fill="x")
        tk.Label(hdr, text="▦  평면 격자 생성", font=FONT_H, bg="#0f1a30", fg=WHI, padx=14, pady=10).pack(side="left")
        body = tk.Frame(self, bg=BG2); body.pack(fill="both", padx=16, pady=10)
        m = self.model
        names = lambda key: [f"{i}: {v['name']}" for i, v in m[key].items()]
        pick = lambda key, i: next((f"{k}: {v['name']}" for k, v in m[key].items() if k == i),
                                   names(key)[0] if m[key] else "")
        self.v_x = tk.StringVar(value="3@6"); self.v_y = tk.StringVar(value="2@7")
        self.v_x0 = tk.StringVar(value="0"); self.v_y0 = tk.StringVar(value="0")
        self.v_sec = tk.StringVar(value=pick("sections", m["defaults"].get("sec")))
        self.v_slab = tk.StringVar(value=pick("slabs", m["defaults"].get("slab")))
        self.v_sup = tk.StringVar(value=pick("sup_types", 3 if 3 in m["sup_types"] else 1))
        self.v_beams = tk.BooleanVar(value=True); self.v_slabs = tk.BooleanVar(value=True)
        self.v_clear = tk.BooleanVar(value=not m["nodes"])
        f = Form(body, lw=13)
        f.row("X 방향 경간", lambda p: entry(p, self.v_x, 22), "m")
        f.row("Y 방향 경간", lambda p: entry(p, self.v_y, 22), "m")
        tk.Label(body, text="쉼표로 구분, 반복은 '3@6' (예: 6, 7.5, 6)", font=FONT_S, bg=BG2, fg=TX3).pack(anchor="w")
        f2 = Form(body, lw=13)
        f2.row("기준점 X", lambda p: entry(p, self.v_x0, 8), "m")
        f2.row("기준점 Y", lambda p: entry(p, self.v_y0, 8), "m")
        f2.row("보 단면", lambda p: combo(p, self.v_sec, names("sections"), 18))
        f2.row("슬래브", lambda p: combo(p, self.v_slab, names("slabs"), 18))
        f2.row("교점 지점", lambda p: combo(p, self.v_sup, ["없음"] + names("sup_types"), 18))
        cf = tk.Frame(body, bg=BG2); cf.pack(fill="x", pady=(6, 0))
        check(cf, "격자선을 보로 적용", self.v_beams).pack(anchor="w")
        check(cf, "격자 칸을 슬래브로 적용", self.v_slabs).pack(anchor="w")
        check(cf, "기존 모델 지우고 새로 만들기", self.v_clear).pack(anchor="w")
        bf = tk.Frame(self, bg=BG2); bf.pack(fill="x", padx=16, pady=(0, 14))
        btn(bf, "생성", self._ok, bg=ACC, fg=WHI, font=FONT_B, padx=18, pady=5).pack(side="right")
        btn(bf, "취소", self.destroy, padx=14, pady=5).pack(side="right", padx=6)

    def _ok(self):
        idof = lambda s: int(s.split(":")[0]) if s and s[0].isdigit() else None
        try:
            xs = parse_list(self.v_x.get()); ys = parse_list(self.v_y.get())
            x0 = float(self.v_x0.get()); y0 = float(self.v_y0.get())
        except Exception:
            messagebox.showwarning("입력", "경간/기준점 값을 확인하세요.", parent=self); return
        if not xs or not ys or len(xs) * len(ys) > 400:
            messagebox.showwarning("입력", "경간을 확인하세요 (최대 400칸).", parent=self); return
        self.result = dict(xs=xs, ys=ys, x0=x0, y0=y0, sec=idof(self.v_sec.get()), slab=idof(self.v_slab.get()),
                           sup=idof(self.v_sup.get()), beams=self.v_beams.get(), slabs=self.v_slabs.get(),
                           clear=self.v_clear.get())
        self.destroy()
