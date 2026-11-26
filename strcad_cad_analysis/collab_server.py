"""StrCAD 협업 서버 실행

  python collab_server.py                     # 포트 8780, 데이터 ~/.strcad/collab
  python collab_server.py --port 8780 --data D:\\StrCAD협업

· 처음 가입한 사람이 관리자가 됩니다 (휴대폰 앱 › 메뉴 › 👥 협업 › 가입).
· 다른 사람은 가입할 때 팀 코드가 필요합니다 (아래에 표시, 관리자가 앱에서 바꿀 수 있음).
· 현장(모바일 데이터)에서 쓰려면: cloudflared tunnel --url http://localhost:8780   → 나온 https 주소를 앱에 입력
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cad_analysis.collab import CollabServer  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="StrCAD 협업 서버")
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--data", default=None, help="데이터 폴더 (기본: ~/.strcad/collab)")
    a = ap.parse_args()
    srv = CollabServer(a.data, a.port, a.host)
    print("StrCAD 협업 서버")
    print("  데이터:", srv.store.path)
    for u in srv.urls():
        print("  주소  :", u)
    print("  팀 코드:", srv.team_code, "(가입할 때 필요 — 처음 가입한 사람은 관리자, 코드 없이 가입)")
    print("  종료: Ctrl+C")
    try:
        srv.start(background=False)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
