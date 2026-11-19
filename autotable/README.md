# Auto Table v2 — 배근 일람표

보 · 기둥 · 벽 · 슬래브 배근 일람표를 **엑셀처럼 입력**하고, 기존 자료를 **가져와서 고친 뒤** CAD·엑셀·TXT 로 **내보내는** 모듈입니다.
런처의 *Auto Table* 카드, 또는 `python autotable/auto_table.py` 로 실행합니다.

## 입력 (방향키로 자유롭게)
| 키 | 동작 |
|---|---|
| ←↑→↓ | 칸 이동 — 값을 치는 중에도 방향키로 확정하고 바로 다음 칸 |
| Enter / Tab / Shift+Tab | 확정 후 아래 / 오른쪽 / 왼쪽 |
| Shift+Enter | 이 값을 아래 칸에 복사하고 내려감 |
| Alt+Enter | 행 복제 (부호 번호 +1: RG9 → RG10) |
| F2 · 더블클릭 | 칸 안에서 고치기 (←→ 로 글자 이동) |
| Shift+방향키 · 마우스 끌기 | 범위 선택 |
| Ctrl+C / X / V | 복사·붙여넣기 — 엑셀 표를 통째로 붙여넣기 가능 |
| Ctrl+D / Ctrl+R | 아래로 / 오른쪽으로 채우기 |
| Ctrl+Z / Ctrl+Y | 되돌리기 / 다시 |
| Ctrl++ / Ctrl+- / Alt+↑↓ | 행 삽입 / 삭제 / 옮기기 |
| F4 | 선택 칸 강종 바꾸기 D → HD → SHD → UHD → SD |

* 철근은 숫자만: `3-22` → `3-D22`, `5/2-22` → `5/2-D22`(2단), `10@200` → `D10@200` (붙는 기호 = 위 *강종* 선택)
* 보 *구분*: `양단/중앙` · `전단면` · `외단/중앙/내단` (숫자키 1/2/3). 안 쓰는 구역 칸은 회색, 출력 안 함
* 마지막 `＋ 새 부재` 줄에 쓰면 윗 행을 이어받은 새 행이 생김
* 오른쪽 미리보기: 단면 그림 + 철근량(As), 기둥 철근비

## 가져오기
| 형식 | 방법 |
|---|---|
| **CAD (DXF)** | 글자 위치로 일람표를 읽음. 보는 `부호 → 양단부/중앙부/전단면 → 상부근/하부근/늑근`, B·H 는 치수(DIMENSION), 슬래브 두께는 단면선. 도곽 블록(S_FORM 등)·NOTE·도면번호도 읽어 두었다가 내보낼 때 같은 양식으로 씀 |
| **MIDAS Gen (txt)** | 탭·쉼표·공백 정렬 표. 머리글 자동 인식, 한 부재가 위치(I/M/J)별 여러 줄이면 단부/중앙부로 합침. 못 맞춘 열은 매핑 창에서 고름 |
| **엑셀 / TXT / CSV** | 같은 매핑 창. 이 프로그램이 내보낸 엑셀·TXT 는 바로 읽음 |
| **PDF** | CAD 에서 출력한 PDF 는 안의 글자를 그대로, 스캔 PDF 는 글자 인식 |
| **사진** | 용지 원근 보정 → 글자 인식(RapidOCR). 한글은 못 읽어서 부호·철근값·치수의 **위치**로 판단 — 가져온 뒤 꼭 확인 |

가져온 결과는 확인 창에서 보고 *추가* 또는 *바꾸기* 를 고릅니다. DWG 는 CAD 에서 DXF 로 저장해서 가져오세요.

## 내보내기
* **CAD (DXF)** — 예제 *보 일람표* 양식 그대로: 도곽(S_FORM) · 레이어(T/ML/ELE/TEXT/bar2/dim) · 늑근 갈고리 · 철근(도넛) · S_30 치수.
  보 4단×3부재(시트당 12개), 기둥 9×3(27개), 벽·슬래브는 표. 큰 단면은 칸에 맞게 줄이고 치수 글자는 실제 값.
  시트 양식은 *가져온 원본 DXF* 또는 기본 `templates/schedule_form.dxf`(또는 다른 DXF). 도면번호는 시트마다 +1, 제목 `보 일람표-1, -2 …`, NOTE·프로젝트명 지정 가능.
* **엑셀** — 종류별 시트, 2단 머리글. 고친 뒤 다시 가져오기 가능
* **TXT** — 탭 구분 (`[beam]` 구역별). 다시 가져오기 가능
* 작업 파일은 `.atbl` (Ctrl+S)

## 구성
```
auto_table.py        진입점 (open_auto_table)
at_core/
  model.py           열 정의 · 철근 표기 정리 · 프로젝트
  grid.py            입력표 (Canvas)
  parse_layout.py    글자 위치 → 일람표 (CAD·PDF·사진 공통)
  dxf_read.py        DXF 가져오기          dxf_write.py   DXF 내보내기 · 템플릿
  table_io.py        엑셀·TXT·MIDAS         image_io.py    PDF·사진 (cad_analysis 의 OCR 재사용)
  sections.py        단면 그림 요소          preview.py     미리보기
  dialogs.py · app.py · design.py(보 단면 설계, v1.3 그대로)
templates/schedule_form.dxf   기본 시트 양식
tests/test_autotable.py       python autotable/tests/test_autotable.py
old/auto_table_v13.py         이전 버전
```
