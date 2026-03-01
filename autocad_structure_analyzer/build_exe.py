"""
STRCAD exe 빌드 스크립트
실행: python build_exe.py
"""

import subprocess
import sys
import os
from pathlib import Path

def main():
    print("=" * 55)
    print("  STRCAD exe 빌드 시작")
    print("=" * 55)

    # PyInstaller 설치 확인
    try:
        import PyInstaller
        print(f"✓ PyInstaller {PyInstaller.__version__} 확인")
    except ImportError:
        print("PyInstaller 설치 중...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("✓ PyInstaller 설치 완료")

    # 필수 패키지 확인
    required = ["ezdxf", "openpyxl", "matplotlib"]
    for pkg in required:
        try:
            __import__(pkg)
            print(f"✓ {pkg} 확인")
        except ImportError:
            print(f"  {pkg} 설치 중...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
            print(f"✓ {pkg} 설치 완료")

    print()
    print("exe 빌드 중... (수 분 소요될 수 있습니다)")
    print()

    # PyInstaller 옵션
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                        # 단일 exe 파일
        "--windowed",                       # 콘솔 창 숨기기 (GUI 앱)
        "--name", "STRCAD",                 # exe 이름
        "--icon", "icon.ico",               # 아이콘 (있으면)
        # 필수 모듈 강제 포함
        "--hidden-import", "ezdxf",
        "--hidden-import", "ezdxf.addons",
        "--hidden-import", "openpyxl",
        "--hidden-import", "matplotlib",
        "--hidden-import", "matplotlib.backends.backend_agg",
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.ttk",
        "--hidden-import", "tkinter.filedialog",
        # modules 패키지 포함
        "--add-data", f"modules{os.pathsep}modules",
        "--add-data", f"config.py{os.pathsep}.",
        # 불필요한 것 제외 (파일 크기 줄이기)
        "--exclude-module", "test",
        "--exclude-module", "pytest",
        "--exclude-module", "IPython",
        "--exclude-module", "jupyter",
        "strcad_gui.py",                    # 메인 파일
    ]

    # icon.ico 없으면 제거
    if not Path("icon.ico").exists():
        cmd = [c for c in cmd if c not in ["--icon", "icon.ico"]]

    try:
        subprocess.check_call(cmd)
        print()
        print("=" * 55)
        print("  ✅ 빌드 성공!")
        print("=" * 55)
        print()

        exe_path = Path("dist") / "STRCAD.exe"
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024*1024)
            print(f"  📦 파일: {exe_path.resolve()}")
            print(f"  📏 크기: {size_mb:.1f} MB")
            print()
            print("  ▶ dist\\STRCAD.exe 를 실행하세요!")
        else:
            print("  dist/ 폴더를 확인하세요.")

    except subprocess.CalledProcessError as e:
        print()
        print("=" * 55)
        print("  ✗ 빌드 실패")
        print("=" * 55)
        print(f"  오류: {e}")
        print()
        print("  해결 방법:")
        print("  1. pip install pyinstaller --upgrade")
        print("  2. 백신 프로그램 일시 비활성화 후 재시도")
        print("  3. 관리자 권한으로 실행")


if __name__ == "__main__":
    main()
