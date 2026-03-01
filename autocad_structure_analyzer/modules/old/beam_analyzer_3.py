"""
보 스팬 계산 및 분석 모듈
- 평면도에서 두 개의 평행선으로 표현된 보의 폭(width) 인식
- DXF 텍스트에서 보 이름 자동 매칭
"""

import math
from typing import List, Tuple, Dict, Optional
import config


class BeamAnalyzer:
    """보의 스팬을 계산하고 분석하는 클래스"""

    def __init__(self, beams: List,
                 column_positions: List[Tuple[float, float]],
                 dxf_reader=None):
        """
        Args:
            beams            : DXF에서 추출한 보 엔티티 리스트
            column_positions : 기둥 중심점 좌표 리스트
            dxf_reader       : DXFReader 인스턴스 (보 이름 매칭용, 선택)
        """
        self.beams            = beams
        self.column_positions = column_positions
        self.dxf_reader       = dxf_reader   # ← 이름 매칭에 사용
        self.beam_data        = []
        self.paired_beams     = []

    # ────────────────────────────────────────────────────────
    #  PUBLIC
    # ────────────────────────────────────────────────────────
    def analyze_spans(self) -> List[Dict]:
        """모든 보의 스팬 분석 (폭 + 이름 포함)"""
        results = []

        line_entities = self._extract_lines(self.beams)
        paired, singles = self._pair_parallel_lines(line_entities)
        self.paired_beams = paired

        beam_candidates = []
        for pair in paired:
            cx, cy, cex, cey, width, layer = pair
            beam_candidates.append({
                'center_start': (cx, cy),
                'center_end':   (cex, cey),
                'width': width,
                'layer': layer,
                'source': 'paired'
            })
        for line in singles:
            s, e, layer = line
            beam_candidates.append({
                'center_start': s,
                'center_end':   e,
                'width': 0,
                'layer': layer,
                'source': 'single'
            })

        # 이름 카운터 (중복 이름 처리용)
        name_counter: Dict[str, int] = {}

        for i, cand in enumerate(beam_candidates):
            beam_id   = f"B{i+1}"
            p_start   = cand['center_start']
            p_end     = cand['center_end']
            beam_points = [p_start, p_end]

            # ── 보 이름 매칭 ──────────────────────────────
            beam_name = self._resolve_beam_name(
                p_start[0], p_start[1],
                p_end[0],   p_end[1],
                beam_id
            )

            # 같은 이름이 여러 개일 때 구분 (G1, G1-2, G1-3 …)
            if beam_name in name_counter:
                name_counter[beam_name] += 1
                display_name = f"{beam_name}-{name_counter[beam_name]}"
            else:
                name_counter[beam_name] = 1
                display_name = beam_name

            intersecting_columns = self._find_intersecting_columns(beam_points)

            if len(intersecting_columns) >= 2:
                spans = self._calculate_spans(beam_points, intersecting_columns)
                for span_idx, span in enumerate(spans):
                    results.append({
                        'beam_id':        f"{beam_id}-{span_idx+1}",
                        'beam_name':      display_name,
                        'beam_layer':     cand['layer'],
                        'span_length':    span['length'],
                        'start_point':    span['start'],
                        'end_point':      span['end'],
                        'start_column':   span['start_column'],
                        'end_column':     span['end_column'],
                        'beam_direction': self._get_direction(span['start'], span['end']),
                        'beam_width':     cand['width'],
                    })
            else:
                total_length = self._distance(p_start, p_end)
                min_span = config.ANALYSIS_OPTIONS['min_span_length']
                max_span = config.ANALYSIS_OPTIONS['max_span_length']
                if min_span <= total_length <= max_span:
                    results.append({
                        'beam_id':        beam_id,
                        'beam_name':      display_name,
                        'beam_layer':     cand['layer'],
                        'span_length':    total_length,
                        'start_point':    p_start,
                        'end_point':      p_end,
                        'start_column':   None,
                        'end_column':     None,
                        'beam_direction': self._get_direction(p_start, p_end),
                        'beam_width':     cand['width'],
                    })

        self.beam_data = results
        named = sum(1 for r in results if r['beam_name'] != r['beam_id'])
        print(f"✓ 보 스팬 {len(results)}개 분석 완료 "
              f"(이름 매칭: {named}개, 폭 인식: {len(paired)}개 쌍)")
        return results

    # ────────────────────────────────────────────────────────
    #  이름 매칭
    # ────────────────────────────────────────────────────────
    def _resolve_beam_name(self, x1, y1, x2, y2, fallback: str) -> str:
        """
        DXFReader의 match_beam_name()으로 이름 조회.
        reader가 없거나 매칭 실패 시 fallback(beam_id) 반환.
        """
        if self.dxf_reader is None:
            return fallback
        try:
            name = self.dxf_reader.match_beam_name(x1, y1, x2, y2)
            return name if name else fallback
        except Exception:
            return fallback

    # ────────────────────────────────────────────────────────
    #  평행선 쌍 그룹화
    # ────────────────────────────────────────────────────────
    @staticmethod
    def _extract_lines(entities) -> List[Tuple]:
        lines = []
        for ent in entities:
            layer = ent.dxf.layer
            if ent.dxftype() == 'LINE':
                s = (ent.dxf.start.x, ent.dxf.start.y)
                e = (ent.dxf.end.x,   ent.dxf.end.y)
                if BeamAnalyzer._distance(s, e) > 1:
                    lines.append((s, e, layer))
            elif ent.dxftype() == 'LWPOLYLINE':
                pts = [(p[0], p[1]) for p in ent.get_points()]
                for i in range(len(pts) - 1):
                    if BeamAnalyzer._distance(pts[i], pts[i+1]) > 1:
                        lines.append((pts[i], pts[i+1], layer))
        return lines

    def _pair_parallel_lines(self, lines: List[Tuple]):
        max_beam_width = getattr(config, 'MAX_BEAM_WIDTH',     2000)
        angle_tol      = getattr(config, 'PARALLEL_ANGLE_TOL', 5.0)
        used   = [False] * len(lines)
        paired = []
        singles = []

        def angle_deg(s, e):
            return math.degrees(math.atan2(e[1]-s[1], e[0]-s[0])) % 180

        for i, (s1, e1, l1) in enumerate(lines):
            if used[i]:
                continue
            a1   = angle_deg(s1, e1)
            len1 = self._distance(s1, e1)
            best_j, best_dist = -1, float('inf')

            for j, (s2, e2, l2) in enumerate(lines):
                if i == j or used[j]:
                    continue
                a2   = angle_deg(s2, e2)
                diff = abs(a1 - a2)
                if diff > 90: diff = 180 - diff
                if diff > angle_tol: continue

                dist = self._point_to_line_distance(s2, s1, e1)
                if dist < 1 or dist > max_beam_width: continue

                len2 = self._distance(s2, e2)
                if min(len1, len2) / max(len1, len2) < 0.5: continue
                if not self._lines_overlap(s1, e1, s2, e2):  continue

                if dist < best_dist:
                    best_dist = dist
                    best_j    = j

            if best_j >= 0:
                used[i] = used[best_j] = True
                s2, e2, l2 = lines[best_j]
                cs = ((s1[0]+s2[0])/2, (s1[1]+s2[1])/2)
                ce = ((e1[0]+e2[0])/2, (e1[1]+e2[1])/2)
                paired.append((cs[0], cs[1], ce[0], ce[1], best_dist, l1))
            else:
                singles.append((s1, e1, l1))

        for i, line in enumerate(lines):
            if not used[i]:
                singles.append(line)
        return paired, singles

    @staticmethod
    def _lines_overlap(s1, e1, s2, e2, min_ratio=0.3) -> bool:
        dx  = e1[0] - s1[0]; dy = e1[1] - s1[1]
        len1 = math.hypot(dx, dy)
        if len1 == 0: return False
        t_s2 = ((s2[0]-s1[0])*dx + (s2[1]-s1[1])*dy) / (len1**2)
        t_e2 = ((e2[0]-s1[0])*dx + (e2[1]-s1[1])*dy) / (len1**2)
        overlap = max(0, min(1, max(t_s2,t_e2)) - max(0, min(t_s2,t_e2)))
        return overlap >= min_ratio

    # ────────────────────────────────────────────────────────
    #  기둥 교차 & 스팬
    # ────────────────────────────────────────────────────────
    def _find_intersecting_columns(self, beam_points):
        intersections = []
        tolerance = config.TOLERANCE['intersection']
        for col_idx, col_pos in enumerate(self.column_positions):
            for i in range(len(beam_points)-1):
                p1, p2 = beam_points[i], beam_points[i+1]
                dist = self._point_to_line_distance(col_pos, p1, p2)
                if dist <= tolerance:
                    proj = self._project_point_to_line(col_pos, p1, p2)
                    if self._is_point_on_segment(proj, p1, p2):
                        intersections.append({
                            'column_id':  f"C{col_idx+1}",
                            'position':   col_pos,
                            'projection': proj
                        })
                        break
        if intersections:
            intersections.sort(
                key=lambda x: self._distance(beam_points[0], x['projection']))
        return intersections

    def _calculate_spans(self, beam_points, columns):
        spans = []
        min_span = config.ANALYSIS_OPTIONS['min_span_length']
        max_span = config.ANALYSIS_OPTIONS['max_span_length']
        for i in range(len(columns)-1):
            col1, col2 = columns[i], columns[i+1]
            span_length = self._distance(col1['projection'], col2['projection'])
            if min_span <= span_length <= max_span:
                spans.append({
                    'start':        col1['projection'],
                    'end':          col2['projection'],
                    'start_column': col1['column_id'],
                    'end_column':   col2['column_id'],
                    'length':       span_length
                })
        return spans

    # ────────────────────────────────────────────────────────
    #  정적 유틸
    # ────────────────────────────────────────────────────────
    @staticmethod
    def _distance(p1, p2):
        return math.sqrt((p2[0]-p1[0])**2 + (p2[1]-p1[1])**2)

    @staticmethod
    def _point_to_line_distance(point, line_start, line_end):
        x0,y0 = point; x1,y1 = line_start; x2,y2 = line_end
        lsq = (x2-x1)**2 + (y2-y1)**2
        if lsq == 0: return math.sqrt((x0-x1)**2+(y0-y1)**2)
        t = max(0,min(1,((x0-x1)*(x2-x1)+(y0-y1)*(y2-y1))/lsq))
        return math.sqrt((x0-(x1+t*(x2-x1)))**2+(y0-(y1+t*(y2-y1)))**2)

    @staticmethod
    def _project_point_to_line(point, line_start, line_end):
        x0,y0 = point; x1,y1 = line_start; x2,y2 = line_end
        lsq = (x2-x1)**2+(y2-y1)**2
        if lsq == 0: return line_start
        t = max(0,min(1,((x0-x1)*(x2-x1)+(y0-y1)*(y2-y1))/lsq))
        return (x1+t*(x2-x1), y1+t*(y2-y1))

    @staticmethod
    def _is_point_on_segment(point, seg_start, seg_end, tolerance=1.0):
        x,y = point; x1,y1 = seg_start; x2,y2 = seg_end
        return (min(x1,x2)-tolerance <= x <= max(x1,x2)+tolerance and
                min(y1,y2)-tolerance <= y <= max(y1,y2)+tolerance)

    @staticmethod
    def _get_direction(start, end):
        dx = abs(end[0]-start[0]); dy = abs(end[1]-start[1])
        if dx > dy*3:  return 'X방향'
        if dy > dx*3:  return 'Y방향'
        return '대각선'

    # ────────────────────────────────────────────────────────
    #  요약
    # ────────────────────────────────────────────────────────
    def get_spans_by_direction(self):
        if not self.beam_data: self.analyze_spans()
        grouped = {'X방향':[], 'Y방향':[], '대각선':[]}
        for s in self.beam_data:
            grouped[s['beam_direction']].append(s)
        return grouped

    def get_summary(self):
        if not self.beam_data: self.analyze_spans()
        by_dir  = self.get_spans_by_direction()
        widths  = [s['beam_width'] for s in self.beam_data if s.get('beam_width',0)>0]
        named   = sum(1 for s in self.beam_data if s['beam_name'] != s['beam_id'])
        return {
            'total_spans':        len(self.beam_data),
            'x_direction_spans':  len(by_dir['X방향']),
            'y_direction_spans':  len(by_dir['Y방향']),
            'diagonal_spans':     len(by_dir['대각선']),
            'avg_span_length':    sum(s['span_length'] for s in self.beam_data)/len(self.beam_data) if self.beam_data else 0,
            'max_span_length':    max((s['span_length'] for s in self.beam_data), default=0),
            'min_span_length':    min((s['span_length'] for s in self.beam_data), default=0),
            'paired_beam_count':  len(self.paired_beams),
            'avg_beam_width':     sum(widths)/len(widths) if widths else 0,
            'max_beam_width':     max(widths, default=0),
            'min_beam_width':     min(widths, default=0),
            'named_beam_count':   named,
        }
