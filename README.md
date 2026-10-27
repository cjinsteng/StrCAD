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
