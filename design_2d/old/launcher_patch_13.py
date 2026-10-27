"""
launcher_patch.py
launcher.py 에서 2D Design 모듈(design_2d 폴더) 연결 방법
======================================================================

[1] launcher.py 와 같은 디렉터리에 design_2d 폴더(패키지)를 복사

[2] Launcher 클래스의 _mkcb 메서드 수정
    변경 전:
        elif mid == "2d_design":  messagebox.showinfo(...)
    변경 후:
        elif mid == "2d_design":  self._open_2d()

[3] Launcher 클래스에 아래 메서드 추가:
"""

# ── _open_2d 메서드 (Launcher 클래스 내부에 붙여넣기) ──────
ADD_TO_LAUNCHER = """
    def _open_2d(self):
        try:
            from design_2d import open_2d_design
            open_2d_design(self, username=self._user)
        except ImportError as e:
            from tkinter import messagebox
            messagebox.showerror(
                "모듈 오류",
                f"design_2d 폴더를 찾을 수 없습니다.\\n{e}",
                parent=self)
"""
