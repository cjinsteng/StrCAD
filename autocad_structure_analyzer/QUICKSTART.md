# 빠른 시작 가이드 (Quick Start Guide)

## 1단계: 설치

### Python 설치 확인
```bash
python --version
# 또는
python3 --version
```
Python 3.9 이상이 필요합니다.

### 라이브러리 설치
프로젝트 폴더에서 다음 명령 실행:
```bash
pip install -r requirements.txt
```

또는 개별 설치:
```bash
pip install ezdxf openpyxl matplotlib numpy
```

## 2단계: AutoCAD 도면 준비

### DXF 파일로 저장
1. AutoCAD에서 도면 열기
2. 명령어 입력: `DXFOUT` 또는 `SAVEAS`
3. 파일 형식: DXF (*.dxf) 선택
4. 저장 위치 기억하기

### 레이어 이름 확인
프로그램이 인식하는 레이어 이름:
- **기둥**: S-COL, 기둥, COLUMN, COL
- **보**: S-BEAM, 보, BEAM
- **슬래브**: S-SLAB, 슬라브, SLAB
- **벽**: S-WALL, 벽체, WALL

레이어 이름이 다르면 `config.py`에서 수정하세요.

## 3단계: 프로그램 실행

### 방법 1: 인터랙티브 실행
```bash
python main.py
```
실행 후 DXF 파일 경로 입력

### 방법 2: 명령줄 실행
```bash
python main.py "C:\Projects\구조평면도.dxf"
```

### 방법 3: VS Code에서 실행
1. VS Code에서 프로젝트 폴더 열기
2. `main.py` 파일 열기
3. F5 누르거나 실행 버튼 클릭

## 4단계: 결과 확인

분석 완료 후 `output/` 폴더에 Excel 파일 생성:
- `스팬정리_YYYYMMDD_HHMMSS.xlsx`: 보 스팬 정보
- `불연속구간_YYYYMMDD_HHMMSS.xlsx`: 부재 불연속 구간
- `기둥간격_YYYYMMDD_HHMMSS.xlsx`: 기둥 간격 정보
- `분석요약_YYYYMMDD_HHMMSS.xlsx`: 전체 요약

## 설정 변경

`config.py` 파일에서 설정 변경 가능:

### 레이어 이름 추가
```python
LAYER_NAMES = {
    'column': ['S-COL', '기둥', 'COLUMN', 'COL', '내레이어명'],
    'beam': ['S-BEAM', '보', 'BEAM', '내레이어명'],
    # ...
}
```

### 허용 오차 조정
```python
TOLERANCE = {
    'connection': 1.0,      # 부재 연결 판단 (mm)
    'intersection': 0.5,    # 교차점 판단 (mm)
}
```

### 스팬 범위 설정
```python
ANALYSIS_OPTIONS = {
    'min_span_length': 1000,    # 최소 스팬 (mm)
    'max_span_length': 20000,   # 최대 스팬 (mm)
}
```

## 문제 해결

### 기둥/보를 찾을 수 없다고 나올 때
1. AutoCAD에서 레이어 이름 확인
2. `config.py`에 해당 레이어 이름 추가
3. 프로그램 다시 실행

### 스팬이 너무 많이/적게 나올 때
1. `config.py`에서 `min_span_length`, `max_span_length` 조정
2. `TOLERANCE['intersection']` 값 조정

### 불연속 구간이 너무 많이 나올 때
1. `config.py`에서 `TOLERANCE['connection']` 값 증가
2. 도면의 실제 끊김 여부 확인

## 다음 단계

더 자세한 사용법은 다음 문서 참조:
- `README.md`: 전체 프로젝트 설명
- `examples/example_usage.py`: 코드 예제
- `config.py`: 설정 옵션

## 지원

문제가 있거나 기능 추가 요청이 있으면 이슈를 등록하세요.
