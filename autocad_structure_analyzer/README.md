# AutoCAD 구조도면 분석 프로그램

건축구조기술사를 위한 AutoCAD 도면 자동 분석 도구

## 주요 기능

1. **보 스팬 자동 측정**: 기둥 위치를 기반으로 보의 스팬 자동 계산
2. **부재 불연속 구간 찾기**: 연결되지 않은 부재 끝점 검출
3. **기둥 간격 정리**: 기둥 간 거리 자동 계산 및 정리
4. **Excel 리포트 생성**: 분석 결과를 Excel 파일로 출력

## 설치 방법

### 1. Python 설치
Python 3.9 이상이 필요합니다.

### 2. 필요한 라이브러리 설치
```bash
pip install -r requirements.txt
```

### 3. AutoCAD 도면 준비
- AutoCAD에서 도면을 DXF 형식으로 저장
- 명령어: `DXFOUT` 또는 "다른 이름으로 저장" → DXF 선택

## 사용 방법

### 기본 사용
```bash
python main.py
```

### 예제 실행
```bash
python examples/example_usage.py
```

## 레이어 명명 규칙

프로그램이 올바르게 작동하려면 다음 레이어 명명 규칙을 따르세요:

- 기둥: `S-COL`, `기둥`, `COLUMN`
- 보: `S-BEAM`, `보`, `BEAM`
- 슬래브: `S-SLAB`, `슬라브`, `SLAB`
- 벽: `S-WALL`, `벽체`, `WALL`

## 프로젝트 구조

```
autocad_structure_analyzer/
├── main.py                 # 메인 실행 파일
├── config.py              # 설정 파일
├── requirements.txt       # 필요한 라이브러리 목록
├── README.md             # 프로젝트 설명서
├── modules/              # 핵심 모듈
│   ├── __init__.py
│   ├── dxf_reader.py    # DXF 파일 읽기
│   ├── column_analyzer.py   # 기둥 분석
│   ├── beam_analyzer.py     # 보 분석
│   ├── discontinuity_checker.py  # 불연속 구간 체크
│   └── excel_exporter.py    # Excel 출력
├── examples/             # 예제 파일
│   └── example_usage.py
└── output/              # 출력 파일 저장 폴더
```

## 출력 결과

분석 결과는 `output/` 폴더에 저장됩니다:
- `스팬정리_YYYYMMDD_HHMMSS.xlsx`: 보 스팬 정보
- `불연속구간_YYYYMMDD_HHMMSS.xlsx`: 부재 불연속 구간
- `기둥간격_YYYYMMDD_HHMMSS.xlsx`: 기둥 간격 정보

## 문의사항

문제가 발생하거나 기능 추가 요청이 있으면 이슈를 등록해주세요.
