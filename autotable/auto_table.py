"""
Auto Table v2 — 보·기둥·벽·슬래브 배근 일람표 (launcher.py 에서 open_auto_table() 호출)
본체는 at_core/ 패키지:
  model.py      열 정의 · 철근 표기 정리 · 프로젝트(.atbl)
  grid.py       엑셀처럼 쓰는 입력표 (방향키 이동, 복사/붙여넣기, 되돌리기)
  dxf_read.py   CAD 일람표 가져오기          parse_layout.py  글자 위치로 표 읽기 (CAD·PDF·사진 공통)
  dxf_write.py  CAD 일람표 내보내기 (시트 양식 templates/schedule_form.dxf)
  table_io.py   엑셀 · TXT · MIDAS Gen        image_io.py  PDF · 사진 (글자 인식)
  app.py        메인 창                       design.py    보 단면 설계 (v1.3 그대로)
이전 버전: old/auto_table_v13.py
"""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from at_core.app import AutoTableApp, open_auto_table  # noqa: E402,F401

if __name__ == "__main__":
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    win = AutoTableApp(parent=root, username="test")
    win.protocol("WM_DELETE_WINDOW", lambda: (win.destroy(), root.destroy()))
    root.mainloop()
