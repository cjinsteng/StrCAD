"""
launcher.py 에 2D Design 모듈을 연결하는 패치
아래 내용을 launcher.py 의 _mkcb 메서드에 적용하세요.
"""

# ── 변경 전 (launcher.py line ~249) ──────────────────────
# elif mid == "2d_design":    messagebox.showinfo("준비 중","2D Design\n모듈 준비 중입니다.",   parent=self)

# ── 변경 후 ───────────────────────────────────────────────
# elif mid == "2d_design":    self._open_2d()

# ── _open_2d 메서드 추가 (Launcher 클래스 내부) ──────────
"""
def _open_2d(self):
    try:
        from design2d import open_2d_design
        open_2d_design(self, username=self._user)
    except ImportError as e:
        messagebox.showerror("모듈 오류", f"design2d.py 파일을 찾을 수 없습니다.\n{e}", parent=self)
"""

# ── 적용 방법 ─────────────────────────────────────────────
# 1. design2d.py 를 launcher.py 와 같은 폴더에 넣기
# 2. launcher.py 의 _mkcb 메서드에서 위 변경사항 적용
# 3. Launcher 클래스에 _open_2d 메서드 추가
