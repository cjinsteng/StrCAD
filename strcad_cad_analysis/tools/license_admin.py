"""StrCAD 라이선스 발급 프로그램 (판매자 전용 — 고객에게 배포하지 마세요).

    python tools/license_admin.py

· 개인키 파일(StrCAD_private.key)로 라이선스 키를 서명해 만듭니다.
· 고객이 보낸 '기기 코드' + 사용 기간 + 모듈을 고르면 키가 나오고, .strlic 파일로도 저장됩니다.
· 발급 내역은 개인키 옆 issued_licenses.csv 에 쌓입니다.
· '키 확인' 탭: 고객이 보낸 키 내용을 확인.
· 처음 한 번 '새 키 쌍 만들기' → 나오는 공개키를 cad_analysis/licensing.py 의 PUBLIC_KEY_B64 에 넣고 다시 빌드.
  (키 쌍을 바꾸면 그 전에 발급한 라이선스는 모두 무효가 됩니다.)
"""
from __future__ import annotations

import csv
import json
import os
import secrets
import sys
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cad_analysis import licensing as LC  # noqa: E402

CFG = os.path.join(os.path.expanduser("~"), ".strcad_admin.json")
PERIODS = [("체험 30일", 30), ("1개월", 31), ("3개월", 92), ("6개월", 183), ("1년", 366), ("2년", 731),
           ("영구", None), ("직접 입력", "custom")]


def load_cfg():
    try:
        with open(CFG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_cfg(c):
    try:
        with open(CFG, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def read_private(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    seed = LC._b64d(d["seed"])
    if len(seed) != 32:
        raise ValueError("개인키 형식 오류")
    return seed, LC._b64e(LC.ed25519_public(seed))


class Admin(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("StrCAD 라이선스 발급 (판매자용)")
        self.geometry("760x680")
        self.cfg = load_cfg()
        self.seed = None
        self.pub = ""
        self._build()
        if self.cfg.get("private") and os.path.exists(self.cfg["private"]):
            self._load_private(self.cfg["private"], quiet=True)

    # ------------------------------------------------------------------ UI
    def _build(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="개인키:").pack(side="left")
        self.pk_var = tk.StringVar(value="(불러오지 않음)")
        ttk.Label(top, textvariable=self.pk_var, foreground="#1E2A44").pack(side="left", padx=6)
        ttk.Button(top, text="새 키 쌍 만들기", command=self._new_pair).pack(side="right")
        ttk.Button(top, text="개인키 열기…", command=self._open_private).pack(side="right", padx=6)
        self.warn = ttk.Label(self, foreground="#DC2626")
        self.warn.pack(fill="x", padx=12)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=8)
        nb.add(self._issue_tab(nb), text="  라이선스 발급  ")
        nb.add(self._check_tab(nb), text="  키 확인  ")

    def _issue_tab(self, nb):
        f = ttk.Frame(nb, padding=12)
        r = 0

        def row(label, w):
            nonlocal r
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="nw", pady=4)
            w.grid(row=r, column=1, sticky="we", pady=4)
            r += 1
            return w
        f.columnconfigure(1, weight=1)
        self.cust = row("고객명(회사/이름)", ttk.Entry(f))
        mf = ttk.Frame(f)
        self.code = ttk.Entry(mf, width=26, font=("Consolas", 11))
        self.code.pack(side="left")
        self.any_pc = tk.BooleanVar(value=False)
        ttk.Checkbutton(mf, text="모든 PC (기기 고정 안 함)", variable=self.any_pc,
                        command=lambda: self.code.configure(state="disabled" if self.any_pc.get() else "normal")
                        ).pack(side="left", padx=10)
        row("기기 코드", mf)
        pf = ttk.Frame(f)
        self.period = tk.StringVar(value="1년")
        for i, (t, _) in enumerate(PERIODS):
            ttk.Radiobutton(pf, text=t, value=t, variable=self.period, command=self._period_changed).grid(
                row=i // 4, column=i % 4, sticky="w", padx=(0, 10))
        row("사용 기간", pf)
        df = ttk.Frame(f)
        ttk.Label(df, text="시작").pack(side="left")
        self.start = ttk.Entry(df, width=12)
        self.start.insert(0, date.today().isoformat())
        self.start.pack(side="left", padx=4)
        ttk.Label(df, text="만료").pack(side="left", padx=(10, 0))
        self.end = ttk.Entry(df, width=12)
        self.end.pack(side="left", padx=4)
        ttk.Label(df, text="(YYYY-MM-DD, 비우면 영구)", foreground="#6B7280").pack(side="left", padx=6)
        row("날짜", df)
        self.ed = tk.StringVar(value="standard")
        ef = ttk.Frame(f)
        for k, t in LC.EDITIONS.items():
            ttk.Radiobutton(ef, text=t, value=k, variable=self.ed).pack(side="left", padx=(0, 10))
        row("에디션", ef)
        modf = ttk.Frame(f)
        self.all_mods = tk.BooleanVar(value=True)
        ttk.Checkbutton(modf, text="전체 모듈", variable=self.all_mods, command=self._mods_changed).grid(
            row=0, column=0, sticky="w")
        self.mod_vars = {}
        for i, (k, t) in enumerate(LC.MODULES.items(), 1):
            v = tk.BooleanVar(value=True)
            cb = ttk.Checkbutton(modf, text=t, variable=v, state="disabled")
            cb.grid(row=i // 4, column=i % 4, sticky="w", padx=(0, 10))
            self.mod_vars[k] = (v, cb)
        row("모듈", modf)
        self.memo = row("메모(내부용)", ttk.Entry(f))
        bf = ttk.Frame(f)
        ttk.Button(bf, text="🔑 라이선스 키 만들기", command=self._issue).pack(side="left")
        ttk.Button(bf, text="복사", command=self._copy).pack(side="left", padx=6)
        ttk.Button(bf, text=".strlic 파일로 저장", command=self._save_file).pack(side="left")
        row("", bf)
        self.out = tk.Text(f, height=7, font=("Consolas", 9), wrap="char")
        self.out.grid(row=r, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        f.rowconfigure(r, weight=1)
        r += 1
        self.info = ttk.Label(f, foreground="#16A34A", justify="left")
        self.info.grid(row=r, column=0, columnspan=2, sticky="w", pady=4)
        self._period_changed()
        return f

    def _check_tab(self, nb):
        f = ttk.Frame(nb, padding=12)
        ttk.Label(f, text="확인할 라이선스 키를 붙여 넣으세요").pack(anchor="w")
        self.chk = tk.Text(f, height=6, font=("Consolas", 9), wrap="char")
        self.chk.pack(fill="x", pady=4)
        ttk.Button(f, text="확인", command=self._check).pack(anchor="w")
        self.chk_out = tk.Text(f, height=14, font=("Consolas", 10), state="disabled", background="#F4F6FA")
        self.chk_out.pack(fill="both", expand=True, pady=6)
        return f

    # ------------------------------------------------------------------ helpers
    def _period_changed(self):
        days = dict(PERIODS)[self.period.get()]
        self.end.configure(state="normal")
        self.end.delete(0, "end")
        if days == "custom":
            return
        if days is not None:
            try:
                s = date.fromisoformat(self.start.get().strip())
            except ValueError:
                s = date.today()
            self.end.insert(0, (s + timedelta(days=days - 1)).isoformat())
            if self.period.get() == "체험 30일":
                self.ed.set("trial")

    def _mods_changed(self):
        for v, cb in self.mod_vars.values():
            cb.configure(state="disabled" if self.all_mods.get() else "normal")

    def _open_private(self):
        p = filedialog.askopenfilename(title="개인키 파일", filetypes=[("StrCAD 개인키", "*.key"), ("모든 파일", "*.*")])
        if p:
            self._load_private(p)

    def _load_private(self, p, quiet=False):
        try:
            self.seed, self.pub = read_private(p)
        except (OSError, ValueError, KeyError) as e:
            if not quiet:
                messagebox.showerror("개인키", f"개인키를 읽을 수 없습니다.\n{e}")
            return
        self.cfg["private"] = p
        save_cfg(self.cfg)
        self.pk_var.set(p)
        if self.pub != LC.PUBLIC_KEY_B64:
            self.warn.config(text="⚠ 이 개인키는 현재 프로그램(licensing.py)의 공개키와 다릅니다. 발급한 키가 동작하지 않습니다.\n"
                                  f"   licensing.py PUBLIC_KEY_B64 = \"{self.pub}\" 로 바꾸고 다시 빌드하세요.")
        else:
            self.warn.config(text="")

    def _new_pair(self):
        if self.seed and not messagebox.askyesno(
                "새 키 쌍", "새 키 쌍을 만들면 지금까지 발급한 라이선스가 새 버전에서 모두 무효가 됩니다.\n계속할까요?"):
            return
        p = filedialog.asksaveasfilename(title="개인키 저장", defaultextension=".key", initialfile="StrCAD_private.key",
                                         filetypes=[("StrCAD 개인키", "*.key")])
        if not p:
            return
        seed = secrets.token_bytes(32)
        pub = LC._b64e(LC.ed25519_public(seed))
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"product": LC.PRODUCT, "seed": LC._b64e(seed), "public": pub,
                       "created": datetime.now().isoformat(timespec="seconds"),
                       "note": "StrCAD 라이선스 발급용 개인키 — 절대 배포/공유/깃허브 업로드 금지"}, f, ensure_ascii=False, indent=1)
        self._load_private(p)
        self.clipboard_clear()
        self.clipboard_append(pub)
        messagebox.showinfo("새 키 쌍", f"개인키를 저장했습니다:\n{p}\n\n공개키(클립보드에 복사됨):\n{pub}\n\n"
                                       "cad_analysis/licensing.py 의 PUBLIC_KEY_B64 에 넣고 다시 빌드하세요.")

    def _issue(self):
        if not self.seed:
            messagebox.showwarning("발급", "먼저 개인키를 여세요.")
            return
        name = self.cust.get().strip()
        if not name:
            messagebox.showwarning("발급", "고객명을 입력하세요.")
            return
        code = "*" if self.any_pc.get() else self.code.get().strip().upper()
        if code != "*" and len(LC._norm_code(code)) != 16:
            messagebox.showwarning("발급", "기기 코드는 XXXX-XXXX-XXXX-XXXX 형식(16자리)입니다.\n"
                                          "고객 PC의 StrCAD › 라이선스 창에 표시됩니다.")
            return
        if code != "*":
            n = LC._norm_code(code)
            code = "-".join(n[i:i + 4] for i in range(0, 16, 4))
        end = self.end.get().strip() or None
        start = self.start.get().strip() or None
        try:
            if end:
                date.fromisoformat(end)
            if start:
                date.fromisoformat(start)
        except ValueError:
            messagebox.showwarning("발급", "날짜는 YYYY-MM-DD 형식으로 입력하세요.")
            return
        mods = ["*"] if self.all_mods.get() else [k for k, (v, _) in self.mod_vars.items() if v.get()]
        if not mods:
            messagebox.showwarning("발급", "모듈을 하나 이상 고르세요.")
            return
        serial = datetime.now().strftime("%y%m%d") + "-" + secrets.token_hex(3).upper()
        payload = {"v": 1, "p": LC.PRODUCT, "id": serial, "n": name, "m": code, "e": end, "ed": self.ed.get(),
                   "mods": mods, "i": date.today().isoformat()}
        if start and start != date.today().isoformat():
            payload["s"] = start
        key = LC.make_key(self.seed, payload)
        assert LC.parse_key(key, self.pub)["id"] == serial
        self.out.delete("1.0", "end")
        self.out.insert("1.0", key)
        self.last = (key, payload)
        self.info.config(text=f"발급 완료 · 일련번호 {serial} · {name} · 기기 {code} · "
                              f"{('~' + end) if end else '영구'} · 모듈 {'전체' if mods == ['*'] else ', '.join(mods)}")
        self._ledger(payload, key)

    def _ledger(self, payload, key):
        p = os.path.join(os.path.dirname(self.cfg.get("private", CFG)), "issued_licenses.csv")
        new = not os.path.exists(p)
        try:
            with open(p, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["발급일시", "일련번호", "고객", "기기코드", "시작", "만료", "에디션", "모듈", "메모", "키"])
                w.writerow([datetime.now().isoformat(timespec="seconds"), payload["id"], payload["n"], payload["m"],
                            payload.get("s", payload["i"]), payload["e"] or "영구", payload["ed"],
                            " ".join(payload["mods"]), self.memo.get(), key])
        except OSError as e:
            messagebox.showwarning("발급 내역", f"발급 내역(csv)을 저장하지 못했습니다.\n{e}")

    def _copy(self):
        k = self.out.get("1.0", "end").strip()
        if k:
            self.clipboard_clear()
            self.clipboard_append(k)

    def _save_file(self):
        if not getattr(self, "last", None):
            return
        key, pl = self.last
        p = filedialog.asksaveasfilename(defaultextension=".strlic", initialfile=f"StrCAD_{pl['n']}_{pl['id']}.strlic",
                                         filetypes=[("StrCAD 라이선스", "*.strlic")])
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"# StrCAD 라이선스 — {pl['n']} · {pl['id']} · {pl['e'] or '영구'}\n"
                        "# StrCAD › 도움말 › 라이선스 › '키 파일 열기'로 등록하세요.\n")
                f.write("STRCAD-LICENSE:" + key + "\n")

    def _check(self):
        k = self.chk.get("1.0", "end")
        lines = [l for l in k.splitlines() if not l.strip().startswith("#")]
        try:
            d = LC.parse_key("".join(lines), self.pub or None)
            ok, why = LC.check_payload(d, code=d.get("m") if d.get("m") != "*" else "ANY")
            txt = json.dumps(d, ensure_ascii=False, indent=1) + "\n\n" + ("✔ 서명 확인 · 기간 유효" if ok else "⚠ " + why)
        except LC.LicenseError as e:
            txt = "✘ " + str(e)
        self.chk_out.configure(state="normal")
        self.chk_out.delete("1.0", "end")
        self.chk_out.insert("1.0", txt)
        self.chk_out.configure(state="disabled")


if __name__ == "__main__":
    Admin().mainloop()
