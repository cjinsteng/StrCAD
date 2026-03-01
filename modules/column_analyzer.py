"""
기둥 위치 및 간격 분석 모듈
"""

import math
from typing import List, Tuple, Dict
import autocad_structure_analyzer.config as config


class ColumnAnalyzer:
    """기둥 위치 및 간격을 분석하는 클래스"""
    
    def __init__(self, columns: List):
        """
        Args:
            columns: DXF에서 추출한 기둥 엔티티 리스트
        """
        self.columns = columns
        self.column_positions = []
        
    def extract_positions(self) -> List[Tuple[float, float]]:
        """기둥 중심점 좌표 추출"""
        positions = []
        
        for col in self.columns:
            if col.dxftype() == 'CIRCLE':
                center = (col.dxf.center.x, col.dxf.center.y)
                positions.append(center)
            elif col.dxftype() == 'INSERT':
                center = (col.dxf.insert.x, col.dxf.insert.y)
                positions.append(center)
        
        self.column_positions = positions
        print(f"✓ 기둥 {len(positions)}개 발견")
        return positions
    
    def calculate_distances(self) -> List[Dict]:
        """기둥 간 거리 계산"""
        if not self.column_positions:
            self.extract_positions()
        
        distances = []
        n = len(self.column_positions)
        
        for i in range(n):
            for j in range(i + 1, n):
                p1 = self.column_positions[i]
                p2 = self.column_positions[j]
                
                dist = self._distance(p1, p2)
                
                distances.append({
                    'column1': f"C{i+1}",
                    'column2': f"C{j+1}",
                    'position1': p1,
                    'position2': p2,
                    'distance': dist,
                    'distance_x': abs(p2[0] - p1[0]),
                    'distance_y': abs(p2[1] - p1[1])
                })
        
        return distances
    
    def find_grid_spacing(self, axis='x') -> Dict:
        """
        그리드 간격 찾기 (X축 또는 Y축)
        
        Args:
            axis: 'x' 또는 'y'
        
        Returns:
            그리드 간격 정보
        """
        if not self.column_positions:
            self.extract_positions()
        
        if axis.lower() == 'x':
            coords = sorted([pos[0] for pos in self.column_positions])
        else:
            coords = sorted([pos[1] for pos in self.column_positions])
        
        # 중복 제거 (같은 그리드라인)
        unique_coords = []
        tolerance = config.TOLERANCE['connection']
        
        for coord in coords:
            if not unique_coords or abs(coord - unique_coords[-1]) > tolerance:
                unique_coords.append(coord)
        
        # 간격 계산
        spacings = []
        for i in range(len(unique_coords) - 1):
            spacing = unique_coords[i+1] - unique_coords[i]
            spacings.append({
                'grid_from': f"{axis.upper()}{i+1}",
                'grid_to': f"{axis.upper()}{i+2}",
                'coordinate_from': unique_coords[i],
                'coordinate_to': unique_coords[i+1],
                'spacing': spacing
            })
        
        return {
            'axis': axis.upper(),
            'gridlines': unique_coords,
            'spacings': spacings
        }
    
    def get_closest_columns(self, point: Tuple[float, float], max_distance: float = None) -> List[Dict]:
        """
        특정 점에서 가장 가까운 기둥들 찾기
        
        Args:
            point: 기준 점 좌표 (x, y)
            max_distance: 최대 거리 (None이면 모든 기둥)
        
        Returns:
            거리순으로 정렬된 기둥 정보
        """
        if not self.column_positions:
            self.extract_positions()
        
        results = []
        for i, col_pos in enumerate(self.column_positions):
            dist = self._distance(point, col_pos)
            
            if max_distance is None or dist <= max_distance:
                results.append({
                    'column_id': f"C{i+1}",
                    'position': col_pos,
                    'distance': dist
                })
        
        # 거리순 정렬
        results.sort(key=lambda x: x['distance'])
        return results
    
    @staticmethod
    def _distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        """두 점 사이의 거리 계산"""
        return math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
    
    def get_summary(self) -> Dict:
        """기둥 분석 요약 정보"""
        if not self.column_positions:
            self.extract_positions()
        
        x_grid = self.find_grid_spacing('x')
        y_grid = self.find_grid_spacing('y')
        
        return {
            'total_columns': len(self.column_positions),
            'x_gridlines': len(x_grid['gridlines']),
            'y_gridlines': len(y_grid['gridlines']),
            'x_spacings': x_grid['spacings'],
            'y_spacings': y_grid['spacings']
        }
