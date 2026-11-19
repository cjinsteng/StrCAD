# StrCAD — STR Design & Check

구조도면 기준 부재검토·설계·분석 프로그램 모음. `launcher.py` 로 실행하면 메인 메뉴(로그인 → 모듈 카드)가 열립니다.

| 모듈 | 폴더 | 내용 |
|---|---|---|
| CAD Analysis | `strcad_cad_analysis/` | DXF 구조·건축 평면 분석, 부재리스트, 현장조사(휴대폰·태블릿 앱 연동), 간이 휨·전단 검토, 현장 스케치 |
| Basic Design | `basic_design/` | 재료(RC/Steel/Other) → 부재 → 설계 방식 선택. 현재 **RC Slab Lite** (1방향·2방향 단일 슬래브, 등분포하중 · 부재 목록 저장(.slab) · A4 PDF 출력), **RC Slab Table** (두께·철근·간격별 φMn 일람표), **RC Slab Pro** (유한요소 해석 · 사각형/다각형 · 집중/라인/면 하중 · 개구부 · 뚫림전단 · 2D/3D 결과), **RC Beam Lite** (직사각형 보 · 단면 1~3개 · 휨/균열/전단/비틀림), **RC Beam Pro** (깊은보 · 스트럿-타이 모델 KDS 14 20 24 · 타이/복부철근 자동 배근 · 절점영역 검토) |
| 2D Design | `design_2d/` | 단면해석(2D 프레임: M·V·N·반력) / 평면해석(슬래브+보 FEM: Mx·My·Qx·Qy·처짐, 보 M·V, 반력) |
| Auto Table | `autotable/` | 보·기둥·벽·슬래브 배근 일람표 — 엑셀처럼 방향키로 입력, 가져오기(CAD DXF·MIDAS Gen txt·엑셀·PDF·사진), 내보내기(CAD DXF 원본 양식·엑셀·TXT). 사용법: [autotable/README.md](autotable/README.md) |
| Information | `information/` | 건물정보 분석 — 주소·시설물 종류·건물높이 입력 → **풍하중**(기본풍속 지도, 지표면조도, DEM 지형단면 지형계수 Kzt, 설계풍속·높이별 속도압), **지진하중**(지진구역·S, 국토지반정보 시추공 반경검색 → 공별 기반암 깊이·Vs,soil·지반분류, Fa·Fv·SDS·SD1·내진설계범주), **설하중**(지상설하중 → 지붕설하중). KDS 지도는 `⚙ 설정 › 지도 보정`에서 한 번 맞춰 두면 자동 조회. 점검: `python -m information.selftest` |
| Report Design | `report_design/` | 진단·검토 보고서(한글 .hwp) 작성 도우미 — 반복 내용 동기화, 절 단위 AI 검토(Claude / Ollama 무료), 번호 검사, 한글 파일 반영 |
| (구버전) | `autocad_structure_analyzer/`, `modules/` | 이전 DXF 분석기 |

## 실행
```
pip install -r requirements.txt
python launcher.py
```
VS Code: 이 폴더를 열고 F5 → 'StrCAD 런처' / 'CAD Analysis 단독 실행' / '라이선스 발급' 선택
```
```

## 라이선스 (판매용)
- 처음 실행부터 14일 체험판 → 이후 라이선스 키 필요 (기기 코드 고정 · 만료일 · 모듈별)
- 발급: `python strcad_cad_analysis/tools/license_admin.py` (판매자 개인키 필요 — **저장소에 올리지 말 것**)
- 자세한 절차: [라이선스_운영_안내.md](라이선스_운영_안내.md)

## 설치 파일
- GitHub Actions `build-suite.yml` 이 main에 push할 때마다 `StrCAD_Setup_<버전>.exe` 를 만들어 릴리스 **win-latest** 에 올립니다.
- 로컬에서 만들 때: Windows에서 `build_windows.bat 1.0.0` (Python 3.12, Inno Setup 6 필요)
- 휴대폰 앱(APK): `build-apk.yml` 이 `strcad_cad_analysis/mobile`·`android-app` 이 바뀌면 빌드해 릴리스 **apk-latest** 에 올립니다.
- (예전 `cjinsteng/cad_analysis` 저장소는 이 저장소의 `strcad_cad_analysis/` 로 합쳐졌습니다.)

## 계정
- 로그인 창의 **회원가입**: 아이디(영문·숫자 4~20자), 비밀번호(영문+숫자 8자 이상), 이름 필수 · 회사/이메일/연락처 선택
- 계정은 그 PC의 `%USERPROFILE%\.strcad\users.json` 에 저장(비밀번호는 PBKDF2 해시). 기본 계정 1234/1234, user1/pass1234
- 라이선스 상태(체험판·만료일)는 **로그인 후** 상단 버튼과 하단에 표시
