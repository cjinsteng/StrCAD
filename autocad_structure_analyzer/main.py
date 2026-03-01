"""
AutoCAD 구조도면 분석 프로그램 - 메인 실행 파일
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from modules import (DXFReader, ColumnAnalyzer, BeamAnalyzer, DiscontinuityChecker, ExcelExporter, BeamViewerExporter)
from modules.beam_visualizer import BeamVisualizer   # ← 추가

def analyze_structure_drawing(dxf_filepath: str):
    """
    구조도면 분석 메인 함수
    
    Args:
        dxf_filepath: DXF 파일 경로
    """
    print("="*60)
    print("AutoCAD 구조도면 분석 프로그램")
    print("="*60)
    print()
    
    # 1. DXF 파일 로드
    print("1단계: DXF 파일 로드 중...")
    reader = DXFReader(dxf_filepath)
    
    if not reader.load():
        print("프로그램을 종료합니다.")
        return
    
    # 레이어 정보 출력
    reader.print_layer_summary()
    
    # 2. 기둥 분석
    print("\n2단계: 기둥 분석 중...")
    columns = reader.get_columns()
    
    if not columns:
        print("⚠ 기둥을 찾을 수 없습니다. 레이어 이름을 확인하세요.")
        print("   설정된 기둥 레이어: S-COL, 기둥, COLUMN, COL")
    else:
        column_analyzer = ColumnAnalyzer(columns)
        column_positions = column_analyzer.extract_positions()
        
        # 기둥 간격 분석
        x_grid = column_analyzer.find_grid_spacing('x')
        y_grid = column_analyzer.find_grid_spacing('y')
        
        print(f"   X축 그리드라인: {len(x_grid['gridlines'])}개")
        print(f"   Y축 그리드라인: {len(y_grid['gridlines'])}개")
    
    # 3. 보 스팬 분석
    print("\n3단계: 보 스팬 분석 중...")
    beams = reader.get_beams()
    
    if not beams:
        print("⚠ 보를 찾을 수 없습니다. 레이어 이름을 확인하세요.")
        print("   설정된 보 레이어: S-BEAM, 보, BEAM")
        beam_analyzer = None
    else:
        if not columns:
            print("⚠ 기둥 정보가 없어 스팬 계산이 제한됩니다.")
            column_positions = []
        
        beam_analyzer = BeamAnalyzer(beams, column_positions, dxf_reader=reader)
        span_data = beam_analyzer.analyze_spans()
        
        if span_data:
            beam_summary = beam_analyzer.get_summary()
            print(f"   평균 스팬: {beam_summary['avg_span_length']:.0f}mm")
            print(f"   최대 스팬: {beam_summary['max_span_length']:.0f}mm")
            print(f"   최소 스팬: {beam_summary['min_span_length']:.0f}mm")
    
    # 4. 불연속 구간 검사
    print("\n4단계: 부재 불연속 구간 검사 중...")
    all_members = beams + reader.get_walls()
    
    if not all_members:
        print("⚠ 검사할 부재가 없습니다.")
        disc_checker = None
    else:
        disc_checker = DiscontinuityChecker(all_members)
        discontinuities = disc_checker.find_discontinuities()
        
        if discontinuities:
            disc_summary = disc_checker.get_summary()
            print(f"   레이어별 불연속 구간:")
            for layer, count in disc_summary['discontinuities_by_layer'].items():
                print(f"     - {layer}: {count}개")
    
    # 5. Excel 리포트 생성
    print("\n5단계: Excel 리포트 생성 중...")
    exporter = ExcelExporter()
    
    generated_files = []
    
    # 보 스팬 리포트
    if beam_analyzer and beam_analyzer.beam_data:
        span_file = exporter.export_beam_spans(beam_analyzer.beam_data)
        generated_files.append(span_file)
    
    # 불연속 구간 리포트
    if disc_checker and disc_checker.discontinuities:
        disc_file = exporter.export_discontinuities(disc_checker.discontinuities)
        generated_files.append(disc_file)
    
    # 기둥 간격 리포트
    if columns:
        spacing_data = {
            'x_spacings': x_grid['spacings'],
            'y_spacings': y_grid['spacings']
        }
        spacing_file = exporter.export_column_spacing(spacing_data)
        generated_files.append(spacing_file)
    
    # 전체 요약 리포트
    summary_data = {}
    
    if columns:
        summary_data['column_summary'] = column_analyzer.get_summary()
    
    if beam_analyzer and beam_analyzer.beam_data:
        summary_data['beam_summary'] = beam_analyzer.get_summary()
    
    if disc_checker and disc_checker.discontinuities:
        summary_data['discontinuity_summary'] = disc_checker.get_summary()
    
    if summary_data:
        summary_file = exporter.export_summary(summary_data)
        generated_files.append(summary_file)
    
    # ── 6단계: 보 평면도 시각화 ──────────────────────────────────
    print("\n6단계: 보 평면도 이미지 생성 중...")
    if beam_analyzer and beam_analyzer.beam_data:
        col_pos = column_positions if columns else []
        visualizer = BeamVisualizer(
            beam_data=beam_analyzer.beam_data,
            column_positions=col_pos,
            title="구조 평면도 - 보 스팬 분석"
        )
        img_path = visualizer.save_image("beam_plan.png")
        if img_path:
            generated_files.append(img_path)
    else:
        print("⚠ 시각화할 보 데이터가 없습니다.")

    # ── 7단계: 인터랙티브 HTML 뷰어 생성 ─────────────────────────
    print("\n7단계: 인터랙티브 HTML 뷰어 생성 중...")
    if beam_analyzer and beam_analyzer.beam_data:
        col_pos = column_positions if columns else []
        viewer = BeamViewerExporter(
            beam_data=beam_analyzer.beam_data,
            column_positions=col_pos,
            title="구조 평면도 - 보 스팬 분석"
        )
        html_path = viewer.export("beam_viewer.html")
        generated_files.append(html_path)
        print(f"   → 브라우저에서 열기: {html_path}")
    else:
        print("⚠ HTML 뷰어 생성할 보 데이터가 없습니다.")

    
    # 완료 메시지
    print("\n" + "="*60)
    print("분석 완료!")
    print("="*60)
    print(f"\n생성된 파일 ({len(generated_files)}개):")
    for filepath in generated_files:
        print(f"  • {filepath}")
    print()


def main():
    """메인 함수"""
    # 명령행 인자로 파일 경로 받기
    if len(sys.argv) > 1:
        dxf_filepath = sys.argv[1]
    else:
        # 인터랙티브 모드
        print("AutoCAD 구조도면 분석 프로그램")
        print("-" * 40)
        dxf_filepath = input("DXF 파일 경로를 입력하세요: ").strip()
        
        # 따옴표 제거
        dxf_filepath = dxf_filepath.strip('"').strip("'")
    
    # 파일 존재 확인
    if not os.path.exists(dxf_filepath):
        print(f"\n✗ 파일을 찾을 수 없습니다: {dxf_filepath}")
        print("\n사용 방법:")
        print("  1. 명령행: python main.py <DXF파일경로>")
        print("  2. 인터랙티브: python main.py (실행 후 경로 입력)")
        return
    
    # 분석 실행
    analyze_structure_drawing(dxf_filepath)
    
    # 종료 대기
    input("\n아무 키나 눌러 종료...")


if __name__ == "__main__":
    main()
