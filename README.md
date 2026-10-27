# StrCAD — STR Design & Check

구조도면 기준 부재검토·설계·분석 프로그램 모음. `launcher.py` 로 실행하면 메인 메뉴(로그인 → 모듈 카드)가 열립니다.

| 모듈 | 폴더 | 내용 |
|---|---|---|
| CAD Analysis | `strcad_cad_analysis/` | DXF 구조·건축 평면 분석, 부재리스트, 현장조사(휴대폰·태블릿 앱 연동), 간이 휨·전단 검토, 현장 스케치 |
| 2D Design | `design_2d/` | 2D 도면 작업 |
| Auto Table | `autotable/` | 보·기둥·슬래브·벽 배근표 자동 작성 |
| (구버전) | `autocad_structure_analyzer/`, `modules/` | 이전 DXF 분석기 |

## 실행
```
pip install ezdxf pillow tkinterdnd2 openpyxl numpy
python launcher.py
```

## 라이선스 (판매용)
- 처음 실행부터 14일 체험판 → 이후 라이선스 키 필요 (기기 코드 고정 · 만료일 · 모듈별)
- 발급: `python strcad_cad_analysis/tools/license_admin.py` (판매자 개인키 필요 — **저장소에 올리지 말 것**)
- 자세한 절차: [라이선스_운영_안내.md](라이선스_운영_안내.md)

## 설치 파일
- GitHub Actions `build-suite.yml` 이 main에 push할 때마다 `StrCAD_Setup_<버전>.exe` 를 만들어 릴리스 **win-latest** 에 올립니다.
- 로컬에서 만들 때: Windows에서 `build_windows.bat 1.0.0` (Python 3.12, Inno Setup 6 필요)
- 휴대폰 앱(APK)·CAD Analysis 단독 설치판은 `cjinsteng/cad_analysis` 저장소에서 빌드됩니다.
