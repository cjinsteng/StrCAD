"""
AutoCAD 구조도면 분석 프로그램 - 사용 예제
"""

import sys
import os

# 상위 디렉토리의 모듈을 import하기 위한 경로 추가
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modules import DXFReader, ColumnAnalyzer, BeamAnalyzer, DiscontinuityChecker, ExcelExporter


def example_1_basic_analysis():
    """예제 1: 기본 분석"""
    print("="*60)
    print("예제 1: 기본 DXF 파일 분석")
    print("="*60)
    
    # DXF 파일 경로 (실제 파일로 변경 필요)
    dxf_file = "sample_structure.dxf"
    
    # DXF 파일 로드
    reader = DXFReader(dxf_file)
    if not reader.load():
        print("샘플 DXF 파일이 없습니다.")
        print("실제 프로젝트 DXF 파일을 사용하세요.")
        return
    
    # 레이어 정보 확인
    reader.print_layer_summary()
    
    # 기둥 추출
    columns = reader.get_columns()
    print(f"기둥: {len(columns)}개")
    
    # 보 추출
    beams = reader.get_beams()
    print(f"보: {len(beams)}개")


def example_2_column_analysis():
    """예제 2: 기둥 분석"""
    print("\n" + "="*60)
    print("예제 2: 기둥 상세 분석")
    print("="*60)
    
    dxf_file = "sample_structure.dxf"
    reader = DXFReader(dxf_file)
    
    if not reader.load():
        print("DXF 파일을 로드할 수 없습니다.")
        return
    
    columns = reader.get_columns()
    if not columns:
        print("기둥을 찾을 수 없습니다.")
        return
    
    # 기둥 분석기 생성
    analyzer = ColumnAnalyzer(columns)
    
    # 기둥 위치 추출
    positions = analyzer.extract_positions()
    print(f"\n기둥 위치 ({len(positions)}개):")
    for i, pos in enumerate(positions[:5], 1):  # 처음 5개만 출력
        print(f"  C{i}: X={pos[0]:.1f}, Y={pos[1]:.1f}")
    
    # X축 그리드 간격
    x_grid = analyzer.find_grid_spacing('x')
    print(f"\nX축 그리드 간격:")
    for spacing in x_grid['spacings'][:3]:  # 처음 3개만 출력
        print(f"  {spacing['grid_from']} ~ {spacing['grid_to']}: {spacing['spacing']:.0f}mm")
    
    # Y축 그리드 간격
    y_grid = analyzer.find_grid_spacing('y')
    print(f"\nY축 그리드 간격:")
    for spacing in y_grid['spacings'][:3]:  # 처음 3개만 출력
        print(f"  {spacing['grid_from']} ~ {spacing['grid_to']}: {spacing['spacing']:.0f}mm")


def example_3_beam_span_analysis():
    """예제 3: 보 스팬 분석"""
    print("\n" + "="*60)
    print("예제 3: 보 스팬 분석")
    print("="*60)
    
    dxf_file = "sample_structure.dxf"
    reader = DXFReader(dxf_file)
    
    if not reader.load():
        return
    
    # 기둥과 보 추출
    columns = reader.get_columns()
    beams = reader.get_beams()
    
    if not columns or not beams:
        print("기둥 또는 보를 찾을 수 없습니다.")
        return
    
    # 기둥 위치 추출
    column_analyzer = ColumnAnalyzer(columns)
    column_positions = column_analyzer.extract_positions()
    
    # 보 스팬 분석
    beam_analyzer = BeamAnalyzer(beams, column_positions)
    spans = beam_analyzer.analyze_spans()
    
    print(f"\n보 스팬 분석 결과 ({len(spans)}개):")
    for span in spans[:5]:  # 처음 5개만 출력
        print(f"  {span['beam_id']}: {span['span_length']:.0f}mm ({span['beam_direction']})")
    
    # 요약 정보
    summary = beam_analyzer.get_summary()
    print(f"\n스팬 통계:")
    print(f"  평균: {summary['avg_span_length']:.0f}mm")
    print(f"  최대: {summary['max_span_length']:.0f}mm")
    print(f"  최소: {summary['min_span_length']:.0f}mm")


def example_4_discontinuity_check():
    """예제 4: 불연속 구간 검사"""
    print("\n" + "="*60)
    print("예제 4: 부재 불연속 구간 검사")
    print("="*60)
    
    dxf_file = "sample_structure.dxf"
    reader = DXFReader(dxf_file)
    
    if not reader.load():
        return
    
    # 모든 부재 수집
    beams = reader.get_beams()
    walls = reader.get_walls()
    all_members = beams + walls
    
    if not all_members:
        print("검사할 부재가 없습니다.")
        return
    
    # 불연속 구간 검사
    checker = DiscontinuityChecker(all_members)
    discontinuities = checker.find_discontinuities()
    
    print(f"\n불연속 구간 ({len(discontinuities)}개):")
    for disc in discontinuities[:5]:  # 처음 5개만 출력
        print(f"  {disc['entity_id']} ({disc['layer']}): X={disc['x']:.1f}, Y={disc['y']:.1f}")
    
    # 레이어별 그룹화
    by_layer = checker.group_by_layer()
    print(f"\n레이어별 불연속 구간:")
    for layer, discs in by_layer.items():
        print(f"  {layer}: {len(discs)}개")


def example_5_excel_export():
    """예제 5: Excel 리포트 생성"""
    print("\n" + "="*60)
    print("예제 5: Excel 리포트 생성")
    print("="*60)
    
    dxf_file = "sample_structure.dxf"
    reader = DXFReader(dxf_file)
    
    if not reader.load():
        return
    
    # 데이터 수집
    columns = reader.get_columns()
    beams = reader.get_beams()
    
    if not columns or not beams:
        print("기둥 또는 보를 찾을 수 없습니다.")
        return
    
    # 분석
    column_analyzer = ColumnAnalyzer(columns)
    column_positions = column_analyzer.extract_positions()
    
    beam_analyzer = BeamAnalyzer(beams, column_positions)
    spans = beam_analyzer.analyze_spans()
    
    # Excel 출력
    exporter = ExcelExporter()
    
    # 보 스팬 리포트
    span_file = exporter.export_beam_spans(spans, "예제_보스팬.xlsx")
    print(f"\n생성된 파일: {span_file}")
    
    # 기둥 간격 리포트
    x_grid = column_analyzer.find_grid_spacing('x')
    y_grid = column_analyzer.find_grid_spacing('y')
    
    spacing_data = {
        'x_spacings': x_grid['spacings'],
        'y_spacings': y_grid['spacings']
    }
    spacing_file = exporter.export_column_spacing(spacing_data, "예제_기둥간격.xlsx")
    print(f"생성된 파일: {spacing_file}")


def example_6_custom_analysis():
    """예제 6: 커스텀 분석"""
    print("\n" + "="*60)
    print("예제 6: 특정 조건 필터링")
    print("="*60)
    
    dxf_file = "sample_structure.dxf"
    reader = DXFReader(dxf_file)
    
    if not reader.load():
        return
    
    columns = reader.get_columns()
    beams = reader.get_beams()
    
    if not columns or not beams:
        return
    
    column_analyzer = ColumnAnalyzer(columns)
    column_positions = column_analyzer.extract_positions()
    
    beam_analyzer = BeamAnalyzer(beams, column_positions)
    spans = beam_analyzer.analyze_spans()
    
    # 예: 6m 이상 스팬만 필터링
    long_spans = [s for s in spans if s['span_length'] >= 6000]
    print(f"\n6m 이상 스팬: {len(long_spans)}개")
    for span in long_spans:
        print(f"  {span['beam_id']}: {span['span_length']:.0f}mm")
    
    # 예: X방향 보만 필터링
    x_direction_beams = [s for s in spans if s['beam_direction'] == 'X방향']
    print(f"\nX방향 보: {len(x_direction_beams)}개")


def main():
    """예제 실행"""
    print("\n")
    print("╔" + "="*58 + "╗")
    print("║" + " "*15 + "사용 예제 모음" + " "*28 + "║")
    print("╚" + "="*58 + "╝")
    print()
    
    # 실제로 실행할 예제를 선택하세요
    # (샘플 DXF 파일이 있어야 실행됩니다)
    
    print("주의: 예제를 실행하려면 'sample_structure.dxf' 파일이 필요합니다.")
    print("실제 프로젝트 DXF 파일 경로로 변경하여 사용하세요.\n")
    
    # example_1_basic_analysis()
    # example_2_column_analysis()
    # example_3_beam_span_analysis()
    # example_4_discontinuity_check()
    # example_5_excel_export()
    # example_6_custom_analysis()
    
    print("\n각 예제 함수의 주석을 해제하여 실행할 수 있습니다.")


if __name__ == "__main__":
    main()
