"""
보 스팬 계산 및 분석 모듈
"""

import math
from typing import List, Tuple, Dict
import config


class BeamAnalyzer:
    """보의 스팬을 계산하고 분석하는 클래스"""
    
    def __init__(self, beams: List, column_positions: List[Tuple[float, float]]):
        """
        Args:
            beams: DXF에서 추출한 보 엔티티 리스트
            column_positions: 기둥 중심점 좌표 리스트
        """
        self.beams = beams
        self.column_positions = column_positions
        self.beam_data = []
        
    def analyze_spans(self) -> List[Dict]:
        """모든 보의 스팬 분석"""
        results = []
        
        for i, beam in enumerate(self.beams):
            beam_id = f"B{i+1}"
            
            # 보의 시작점과 끝점 추출
            if beam.dxftype() == 'LINE':
                start = (beam.dxf.start.x, beam.dxf.start.y)
                end = (beam.dxf.end.x, beam.dxf.end.y)
                beam_points = [start, end]
            elif beam.dxftype() == 'LWPOLYLINE':
                beam_points = [(p[0], p[1]) for p in beam.get_points()]
            else:
                continue
            
            # 보와 교차하는 기둥 찾기
            intersecting_columns = self._find_intersecting_columns(beam_points)
            
            if len(intersecting_columns) >= 2:
                # 스팬 계산
                spans = self._calculate_spans(beam_points, intersecting_columns)
                
                for span_idx, span in enumerate(spans):
                    results.append({
                        'beam_id': f"{beam_id}-{span_idx+1}",
                        'beam_layer': beam.dxf.layer,
                        'span_length': span['length'],
                        'start_point': span['start'],
                        'end_point': span['end'],
                        'start_column': span['start_column'],
                        'end_column': span['end_column'],
                        'beam_direction': self._get_direction(span['start'], span['end'])
                    })
            else:
                # 연속 보 (중간 기둥 없음)
                total_length = self._polyline_length(beam_points)
                
                if config.ANALYSIS_OPTIONS['min_span_length'] <= total_length <= config.ANALYSIS_OPTIONS['max_span_length']:
                    results.append({
                        'beam_id': beam_id,
                        'beam_layer': beam.dxf.layer,
                        'span_length': total_length,
                        'start_point': beam_points[0],
                        'end_point': beam_points[-1],
                        'start_column': None,
                        'end_column': None,
                        'beam_direction': self._get_direction(beam_points[0], beam_points[-1])
                    })
        
        self.beam_data = results
        print(f"✓ 보 스팬 {len(results)}개 분석 완료")
        return results
    
    def _find_intersecting_columns(self, beam_points: List[Tuple[float, float]]) -> List[Dict]:
        """보와 교차하는 기둥 찾기"""
        intersections = []
        tolerance = config.TOLERANCE['intersection']
        
        for col_idx, col_pos in enumerate(self.column_positions):
            # 보의 각 세그먼트와 기둥의 교차 확인
            for i in range(len(beam_points) - 1):
                p1 = beam_points[i]
                p2 = beam_points[i + 1]
                
                # 점과 선분 사이의 거리 계산
                dist = self._point_to_line_distance(col_pos, p1, p2)
                
                if dist <= tolerance:
                    # 교차점이 선분 범위 내에 있는지 확인
                    proj = self._project_point_to_line(col_pos, p1, p2)
                    if self._is_point_on_segment(proj, p1, p2):
                        intersections.append({
                            'column_id': f"C{col_idx+1}",
                            'position': col_pos,
                            'projection': proj
                        })
                        break  # 같은 기둥은 한 번만
        
        # 보의 진행 방향으로 정렬
        if intersections:
            intersections.sort(key=lambda x: self._distance(beam_points[0], x['projection']))
        
        return intersections
    
    def _calculate_spans(self, beam_points: List[Tuple[float, float]], 
                        columns: List[Dict]) -> List[Dict]:
        """교차하는 기둥들 사이의 스팬 계산"""
        spans = []
        
        for i in range(len(columns) - 1):
            col1 = columns[i]
            col2 = columns[i + 1]
            
            span_length = self._distance(col1['projection'], col2['projection'])
            
            # 최소/최대 스팬 길이 필터링
            min_span = config.ANALYSIS_OPTIONS['min_span_length']
            max_span = config.ANALYSIS_OPTIONS['max_span_length']
            
            if min_span <= span_length <= max_span:
                spans.append({
                    'start': col1['projection'],
                    'end': col2['projection'],
                    'start_column': col1['column_id'],
                    'end_column': col2['column_id'],
                    'length': span_length
                })
        
        return spans
    
    @staticmethod
    def _distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        """두 점 사이의 거리"""
        return math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
    
    @staticmethod
    def _polyline_length(points: List[Tuple[float, float]]) -> float:
        """폴리라인 총 길이 계산"""
        total = 0
        for i in range(len(points) - 1):
            total += BeamAnalyzer._distance(points[i], points[i+1])
        return total
    
    @staticmethod
    def _point_to_line_distance(point: Tuple[float, float], 
                                line_start: Tuple[float, float], 
                                line_end: Tuple[float, float]) -> float:
        """점과 직선 사이의 최단 거리"""
        x0, y0 = point
        x1, y1 = line_start
        x2, y2 = line_end
        
        # 직선의 길이가 0이면 점과 점 사이의 거리
        line_length_sq = (x2 - x1)**2 + (y2 - y1)**2
        if line_length_sq == 0:
            return math.sqrt((x0 - x1)**2 + (y0 - y1)**2)
        
        # 투영 계산
        t = ((x0 - x1) * (x2 - x1) + (y0 - y1) * (y2 - y1)) / line_length_sq
        t = max(0, min(1, t))
        
        proj_x = x1 + t * (x2 - x1)
        proj_y = y1 + t * (y2 - y1)
        
        return math.sqrt((x0 - proj_x)**2 + (y0 - proj_y)**2)
    
    @staticmethod
    def _project_point_to_line(point: Tuple[float, float],
                               line_start: Tuple[float, float],
                               line_end: Tuple[float, float]) -> Tuple[float, float]:
        """점을 직선에 투영"""
        x0, y0 = point
        x1, y1 = line_start
        x2, y2 = line_end
        
        line_length_sq = (x2 - x1)**2 + (y2 - y1)**2
        if line_length_sq == 0:
            return line_start
        
        t = ((x0 - x1) * (x2 - x1) + (y0 - y1) * (y2 - y1)) / line_length_sq
        t = max(0, min(1, t))
        
        proj_x = x1 + t * (x2 - x1)
        proj_y = y1 + t * (y2 - y1)
        
        return (proj_x, proj_y)
    
    @staticmethod
    def _is_point_on_segment(point: Tuple[float, float],
                            seg_start: Tuple[float, float],
                            seg_end: Tuple[float, float],
                            tolerance: float = 1.0) -> bool:
        """점이 선분 위에 있는지 확인"""
        x, y = point
        x1, y1 = seg_start
        x2, y2 = seg_end
        
        min_x = min(x1, x2) - tolerance
        max_x = max(x1, x2) + tolerance
        min_y = min(y1, y2) - tolerance
        max_y = max(y1, y2) + tolerance
        
        return min_x <= x <= max_x and min_y <= y <= max_y
    
    @staticmethod
    def _get_direction(start: Tuple[float, float], end: Tuple[float, float]) -> str:
        """보의 방향 결정 (X축, Y축, 대각선)"""
        dx = abs(end[0] - start[0])
        dy = abs(end[1] - start[1])
        
        if dx > dy * 3:  # X축 방향이 지배적
            return 'X방향'
        elif dy > dx * 3:  # Y축 방향이 지배적
            return 'Y방향'
        else:
            return '대각선'
    
    def get_spans_by_direction(self) -> Dict[str, List[Dict]]:
        """방향별 스팬 그룹화"""
        if not self.beam_data:
            self.analyze_spans()
        
        grouped = {'X방향': [], 'Y방향': [], '대각선': []}
        
        for span in self.beam_data:
            direction = span['beam_direction']
            grouped[direction].append(span)
        
        return grouped
    
    def get_summary(self) -> Dict:
        """보 스팬 분석 요약"""
        if not self.beam_data:
            self.analyze_spans()
        
        spans_by_direction = self.get_spans_by_direction()
        
        return {
            'total_spans': len(self.beam_data),
            'x_direction_spans': len(spans_by_direction['X방향']),
            'y_direction_spans': len(spans_by_direction['Y방향']),
            'diagonal_spans': len(spans_by_direction['대각선']),
            'avg_span_length': sum(s['span_length'] for s in self.beam_data) / len(self.beam_data) if self.beam_data else 0,
            'max_span_length': max((s['span_length'] for s in self.beam_data), default=0),
            'min_span_length': min((s['span_length'] for s in self.beam_data), default=0)
        }
