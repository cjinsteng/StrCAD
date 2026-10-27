"""
DXF 파일 읽기 및 기본 처리 모듈
- 보 이름 텍스트 정밀 매칭: 레이어 계열 우선 + 중점 거리 가중치
- 기둥: LWPOLYLINE 폴리곤 + 형태 추론(4각형·비율) 지원
- 벽:   LINE + LWPOLYLINE 모두 지원, 마감 레이어 포함
- 기둥 Node: 폴리곤 중심점 + 치수(W×H) 반환
- 보-기둥 스냅: 보 끝점을 기둥 중심점으로 스냅
"""

import math
import ezdxf
from typing import List, Dict, Any, Tuple, Optional
import config


# 레이어 → BEAM/GIRDER 계열 판별
def _layer_family(layer: str) -> str:
    lu = layer.upper()
    if 'GIRDER' in lu: return 'GIRDER'
    if 'BEAM'   in lu: return 'BEAM'
    return ''


class DXFReader:

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.doc  = None
        self.msp  = None
        self._beam_name_texts: List[Dict] = []
        # 기둥·벽 원시 데이터 캐시 (dict 형태)
        self._column_shapes: List[Dict] = []
        self._wall_shapes:   List[Dict] = []
        # 기둥 Node 리스트: [{id, cx, cy, width, height, layer, source, name}]
        self._column_nodes: List[Dict] = []
        # 기둥 이름 텍스트 캐시
        self._column_name_texts: List[Dict] = []
        # 보 평행쌍 (beam_width, center_line)
        self._beam_line_pairs: List[Dict] = []
        # 이름 매칭 사용 인덱스 (1:1 대응용)
        self._beam_name_used: set = set()

    def load(self):
        try:
            self.doc = ezdxf.readfile(self.filepath)
            self.msp = self.doc.modelspace()
            print(f"✓ DXF 파일 로드 성공: {self.filepath}")
            self._beam_name_texts = self._parse_beam_name_texts()
            print(f"  보/거더 이름 텍스트: {len(self._beam_name_texts)}개 인식")
            # 기둥·벽 형상 미리 파싱
            self._column_shapes, self._wall_shapes = self._parse_column_wall_shapes()
            # 기둥 이름 텍스트 파싱
            self._column_name_texts = self._parse_column_name_texts()
            # 기둥 Node 생성 (폴리곤 + LINE 그룹 중심점 + 이름 매칭)
            self._column_nodes = self._build_column_nodes()
            # 보/거더 LINE 평행쌍 두께·중심선 계산
            self._beam_line_pairs = self._compute_beam_line_pairs()
            n_exp  = sum(1 for n in self._column_nodes if n['source']=='explicit')
            n_inf  = sum(1 for n in self._column_nodes if n['source']=='shape_inferred')
            n_named= sum(1 for n in self._column_nodes if n.get('name'))
            n_poly = sum(1 for s in self._column_shapes if s['type']=='polygon')
            n_line = sum(1 for s in self._column_shapes if s['type']=='line')
            t_set  = set(s.get('thickness',0) for s in self._wall_shapes if s.get('thickness',0)>0)
            n_paired = sum(1 for p in self._beam_line_pairs if p.get('beam_width',0)>0)
            print(f"  기둥 형상: {len(self._column_shapes)}개 (폴리곤 {n_poly}, 선분 {n_line}) / 벽 요소: {len(self._wall_shapes)}개 인식")
            print(f"  기둥 Node: {len(self._column_nodes)}개 (명시 {n_exp}, 추론 {n_inf}, 이름 {n_named}개)")
            print(f"  벽체 두께 그룹: {sorted(t_set)}")
            print(f"  보 평행쌍: {n_paired}개 두께 인식")
            return True
        except IOError:
            print(f"✗ 파일을 찾을 수 없습니다: {self.filepath}")
            return False
        except ezdxf.DXFStructureError:
            print(f"✗ 잘못된 DXF 파일 형식: {self.filepath}")
            return False

    # ════════════════════════════════════════════════════════
    #  기둥 · 벽 형상 파싱  (ezdxf 기반)
    # ════════════════════════════════════════════════════════
    def _parse_column_wall_shapes(self):
        """
        기둥: LWPOLYLINE (명시 레이어 + 형태 추론) + LINE 그룹
        벽:   LINE + LWPOLYLINE, 병렬 선분 쌍으로 두께(thickness) 계산
        """
        col_layers    = set(config.LAYER_NAMES.get('column', []))
        wall_layers   = set(config.LAYER_NAMES.get('wall', []))
        finish_layers = set(config.LAYER_NAMES.get('column_finishes', []))

        col_shapes  = []
        wall_shapes_raw = []   # 두께 계산 전 raw

        shape_cfg = getattr(config, 'COLUMN_SHAPE', {})
        max_vert  = shape_cfg.get('max_vertices',    8)
        max_ratio = shape_cfg.get('max_aspect_ratio', 5.0)
        min_size  = shape_cfg.get('min_size',        100)

        for ent in self.msp:
            layer = ent.dxf.layer

            # ── LWPOLYLINE ──────────────────────────────────
            if ent.dxftype() == 'LWPOLYLINE':
                try:
                    pts = [(p[0], p[1]) for p in ent.get_points()]
                except Exception:
                    continue
                if len(pts) < 2:
                    continue
                closed = bool(ent.dxf.flags & 1) if ent.dxf.hasattr('flags') else False
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                w  = max(xs) - min(xs);   h  = max(ys) - min(ys)
                ratio = max(w, h) / min(w, h) if min(w, h) > 0 else 999

                if layer in col_layers:
                    col_shapes.append({'type':'polygon','coords':pts,'closed':closed,
                                       'layer':layer,'source':'explicit'})
                elif layer in wall_layers:
                    wall_shapes_raw.append({'type':'polygon','coords':pts,'closed':closed,
                                            'layer':layer,'source':'explicit','thickness':0})
                elif layer in finish_layers:
                    if len(pts) <= max_vert and ratio <= max_ratio and max(w,h) >= min_size:
                        col_shapes.append({'type':'polygon','coords':pts,'closed':closed,
                                           'layer':layer,'source':'shape_inferred'})
                    else:
                        wall_shapes_raw.append({'type':'polygon','coords':pts,'closed':closed,
                                                'layer':layer,'source':'shape_inferred','thickness':0})

            # ── LINE ────────────────────────────────────────
            elif ent.dxftype() == 'LINE':
                try:
                    x1,y1 = ent.dxf.start.x, ent.dxf.start.y
                    x2,y2 = ent.dxf.end.x,   ent.dxf.end.y
                except Exception:
                    continue
                if layer in wall_layers:
                    wall_shapes_raw.append({'type':'line',
                                            'coords':[(x1,y1),(x2,y2)],
                                            'layer':layer,'source':'explicit','thickness':0})
                elif layer in col_layers:
                    if math.hypot(x2-x1,y2-y1) >= min_size:
                        col_shapes.append({'type':'line','coords':[(x1,y1),(x2,y2)],
                                           'layer':layer,'source':'explicit'})

        # ── 벽체 두께 계산 (병렬 선분 쌍 매칭) ─────────────
        wall_shapes = self._compute_wall_thickness(wall_shapes_raw)
        return col_shapes, wall_shapes

    @staticmethod
    def _pt_seg_dist_static(px, py, x1, y1, x2, y2) -> float:
        dx,dy = x2-x1, y2-y1; l2=dx*dx+dy*dy
        if l2==0: return math.hypot(px-x1,py-y1)
        t=max(0.0,min(1.0,((px-x1)*dx+(py-y1)*dy)/l2))
        return math.hypot(px-(x1+t*dx), py-(y1+t*dy))

    def _compute_wall_thickness(self, raw: List[Dict]) -> List[Dict]:
        """
        병렬 LINE 쌍을 찾아 두께(thickness) 계산.
        두께 그룹 키: 10mm 단위 반올림 후 'thickness' 필드에 저장.
        """
        lines_only = [s for s in raw if s['type']=='line']
        other      = [s for s in raw if s['type']!='line']

        used = [False]*len(lines_only)
        result = list(other)

        for i, s1 in enumerate(lines_only):
            if used[i]:
                continue
            c1 = s1['coords']
            x1a,y1a = c1[0]; x1b,y1b = c1[1]
            dx1,dy1 = x1b-x1a, y1b-y1a
            len1 = math.hypot(dx1,dy1)
            if len1 < 50:
                used[i]=True
                result.append({**s1,'thickness':0})
                continue
            ang1 = math.atan2(dy1,dx1) % math.pi

            # 짝 선분 탐색 (방향 같고, 수직거리 50~600mm, 길이 비슷)
            best_j = -1; best_d = float('inf')
            for j in range(i+1, len(lines_only)):
                if used[j]: continue
                c2 = lines_only[j]['coords']
                x2a,y2a = c2[0]; x2b,y2b = c2[1]
                dx2,dy2 = x2b-x2a, y2b-y2a
                ang2 = math.atan2(dy2,dx2) % math.pi
                # 방향 차 < 5도
                da = abs(ang1-ang2); da = min(da, math.pi-da)
                if da > 0.09: continue  # ~5°
                # 수직 거리
                mx,my = (x1a+x1b)/2, (y1a+y1b)/2
                d = self._pt_seg_dist_static(mx,my,x2a,y2a,x2b,y2b)
                if 30 < d < 700 and d < best_d:
                    best_d=d; best_j=j

            thickness = round(best_d/10)*10 if best_j>=0 else 0
            used[i]=True
            result.append({**s1,'thickness':thickness})
            if best_j >= 0:
                used[best_j]=True
                result.append({**lines_only[best_j],'thickness':thickness})

        # 매칭 못 된 나머지
        for i,s in enumerate(lines_only):
            if not used[i]:
                result.append({**s,'thickness':0})

        return result

    # ── 외부 접근용 ──────────────────────────────────────────
    def get_column_shapes(self) -> List[Dict]:
        """기둥 형상 리스트 반환 (dict: type/coords/layer/source)"""
        return self._column_shapes

    def get_wall_shapes(self) -> List[Dict]:
        """벽체 형상 리스트 반환 (dict: type/coords/layer/source)"""
        return self._wall_shapes

    def get_column_nodes(self) -> List[Dict]:
        """
        기둥 Node 리스트 반환
        각 항목: {
            'id'     : 'C001' 형식 노드 번호,
            'cx'     : 중심 X 좌표 (mm),
            'cy'     : 중심 Y 좌표 (mm),
            'width'  : 가로 치수 (mm),
            'height' : 세로 치수 (mm),
            'layer'  : 레이어명,
            'source' : 'explicit' | 'shape_inferred',
        }
        """
        return self._column_nodes

    def _build_column_nodes(self) -> List[Dict]:
        """
        기둥 형상(polygon + LINE 그룹)에서 Node 목록 생성.
        - polygon: 좌표 직접 bounding box → 중심점
        - LINE:    끝점 근접(tol=5mm) 그룹화 → bounding box → 중심점
        중복 중심점 50mm 이내는 하나로 병합.
        """
        candidates = []   # (cx, cy, w, h, angle_deg, layer, source, coords_or_None)

        # ── 1. polygon 타입 (LWPOLYLINE) ──────────────────────
        for sh in self._column_shapes:
            if sh.get('type') != 'polygon':
                continue
            coords = sh.get('coords', [])
            if len(coords) < 2:
                continue
            xs = [p[0] for p in coords]
            ys = [p[1] for p in coords]
            # 중심점: bbox 중심
            cx = (max(xs) + min(xs)) / 2
            cy = (max(ys) + min(ys)) / 2
            # 축정렬 bounding box 치수
            w  = max(xs) - min(xs)
            h  = max(ys) - min(ys)
            if max(w, h) < 50:   # 노이즈 제거
                continue
            # 기울기: 가장 긴 엣지의 방향
            best_angle = 0.0
            best_len   = 0.0
            n_pts = len(coords)
            for k in range(n_pts):
                p0 = coords[k]; p1 = coords[(k + 1) % n_pts]
                edge_len = math.hypot(p1[0]-p0[0], p1[1]-p0[1])
                if edge_len > best_len:
                    best_len  = edge_len
                    best_angle = math.degrees(math.atan2(p1[1]-p0[1], p1[0]-p0[0]))
            # 0~90도 범위로 정규화 (방향 부호 제거)
            ang = best_angle % 180
            if ang > 90:
                ang -= 180
            candidates.append((cx, cy, w, h, ang,
                                sh.get('layer', ''), sh.get('source', 'explicit'), coords))

        # ── 2. line 타입 (LINE 선분) → 끝점 그룹화 ───────────
        line_shapes = [sh for sh in self._column_shapes if sh.get('type') == 'line']
        if line_shapes:
            used  = [False] * len(line_shapes)
            tol_ep = 5.0

            for i, sh_i in enumerate(line_shapes):
                if used[i]:
                    continue
                grp   = [i]
                used[i] = True
                queue = [i]

                while queue:
                    cur = queue.pop()
                    c   = line_shapes[cur]['coords']
                    eps_cur = [c[0], c[-1]]
                    for j, sh_j in enumerate(line_shapes):
                        if used[j]:
                            continue
                        d = line_shapes[j]['coords']
                        eps_j = [d[0], d[-1]]
                        if any(math.hypot(a[0]-b[0], a[1]-b[1]) < tol_ep
                               for a in eps_cur for b in eps_j):
                            used[j] = True
                            grp.append(j)
                            queue.append(j)

                all_x, all_y = [], []
                for gi in grp:
                    for pt in line_shapes[gi]['coords']:
                        all_x.append(pt[0]); all_y.append(pt[1])

                w  = max(all_x) - min(all_x)
                h  = max(all_y) - min(all_y)

                if max(w, h) < 100:
                    continue
                ratio = max(w, h) / min(w, h) if min(w, h) > 0 else 999
                if ratio > 8:
                    continue

                cx = (max(all_x) + min(all_x)) / 2
                cy = (max(all_y) + min(all_y)) / 2

                # 그룹에서 가장 긴 선분의 각도
                best_angle = 0.0; best_len = 0.0
                for gi in grp:
                    c = line_shapes[gi]['coords']
                    edge_len = math.hypot(c[1][0]-c[0][0], c[1][1]-c[0][1])
                    if edge_len > best_len:
                        best_len  = edge_len
                        best_angle = math.degrees(math.atan2(c[1][1]-c[0][1], c[1][0]-c[0][0]))
                ang = best_angle % 180
                if ang > 90: ang -= 180

                layer = line_shapes[grp[0]].get('layer', '')
                candidates.append((cx, cy, w, h, ang, layer, 'explicit', None))

        # ── 3. 중복 제거 + Node 생성 + 이름 매칭 ──────────────
        nodes = []
        seen_pts: List[Tuple[float, float]] = []

        for cx, cy, w, h, angle, layer, source, coords in candidates:
            dup = any(math.hypot(cx-sx, cy-sy) < 50 for sx, sy in seen_pts)
            if dup:
                continue
            seen_pts.append((cx, cy))
            name = self._match_column_name(cx, cy, max(w, h) * 1.5)
            # 기울어진 기둥의 실제 치수: 긴 방향이 'width'
            if coords and len(coords) >= 3:
                # 두 인접 엣지 길이로 실제 가로/세로 계산
                pts = coords
                n_pts = len(pts)
                edge_lens = []
                for k in range(n_pts):
                    p0 = pts[k]; p1 = pts[(k+1) % n_pts]
                    edge_lens.append(math.hypot(p1[0]-p0[0], p1[1]-p0[1]))
                if len(edge_lens) >= 2:
                    # 사각형: 첫 번째 엣지 = 긴쪽, 두 번째 엣지 = 짧은쪽
                    col_w = max(edge_lens[0], edge_lens[1])
                    col_h = min(edge_lens[0], edge_lens[1])
                    # bounding box w/h가 더 큰 경우 bbox 사용
                    if max(w, h) > max(col_w, col_h) * 1.5:
                        pass  # 이상한 shape → bbox 유지
                    else:
                        w, h = col_w, col_h
            idx = len(nodes) + 1
            nodes.append({
                'id'     : f'C{idx:03d}',
                'cx'     : round(cx, 1),
                'cy'     : round(cy, 1),
                'width'  : round(w, 1),
                'height' : round(h, 1),
                'angle'  : round(angle, 1),   # 기울기 (도, -90~90)
                'layer'  : layer,
                'source' : source,
                'name'   : name or '',
                'coords' : coords,             # 원본 좌표 (렌더링용)
            })
        return nodes

    # ── 기둥 이름 텍스트 파싱 ────────────────────────────────
    _COL_NAME_PREFIXES = ('C', 'SC', 'SRC', 'TC', 'RC', 'S', 'G')

    def _parse_column_name_texts(self) -> List[Dict]:
        """!!0-COLUMN-N 레이어 TEXT/MTEXT → 기둥 이름 목록"""
        import re
        name_layers = set(config.LAYER_NAMES.get(
            'column_name', ['!!0-COLUMN-N', '!!0-COLUMN_N', 'S-COL-N']))
        result = []
        for ent in self.msp:
            if ent.dxf.layer not in name_layers:
                continue
            if ent.dxftype() not in ('TEXT', 'MTEXT'):
                continue
            try:
                if ent.dxftype() == 'TEXT':
                    text = ent.dxf.text.strip()
                    x, y = ent.dxf.insert.x, ent.dxf.insert.y
                else:
                    text = ent.plain_mtext().strip()
                    x, y = ent.dxf.insert.x, ent.dxf.insert.y
                # 제어코드 제거
                text = re.sub(r'\\[A-Za-z][^;]*;|[{}]', '', text).strip()
                if not text:
                    continue
                # 기둥 이름 패턴 확인 (C1, SC1, SRC2B 등)
                upper = text.upper()
                is_col_name = any(upper.startswith(p) for p in self._COL_NAME_PREFIXES)
                if is_col_name:
                    result.append({'text': text, 'x': x, 'y': y})
            except Exception:
                continue
        return result

    def _match_column_name(self, cx: float, cy: float, radius: float) -> str:
        """기둥 중심점 (cx,cy)에서 radius 이내 가장 가까운 이름 텍스트 반환"""
        best_name = ''; best_d = float('inf')
        for t in self._column_name_texts:
            d = math.hypot(t['x']-cx, t['y']-cy)
            if d < radius and d < best_d:
                best_d = d; best_name = t['text']
        return best_name

    def snap_beams_to_columns(self,
                               beam_data: List[Dict],
                               snap_tolerance: float = None) -> List[Dict]:
        """
        보 끝점을 가장 가까운 기둥 중심점으로 스냅.

        snap_tolerance: None 이면 각 기둥의 max(width, height) * 0.8 을 사용.
                        고정값 지정 시 해당 거리 이내의 기둥으로만 스냅.

        반환: 스냅된 beam_data (start_point / end_point 수정본, 원본은 변경 없음)
        """
        if not self._column_nodes:
            return beam_data

        result = []
        for b in beam_data:
            b2 = dict(b)
            sx, sy = b['start_point']
            ex, ey = b['end_point']

            snapped_s = self._nearest_column_snap(sx, sy, snap_tolerance)
            snapped_e = self._nearest_column_snap(ex, ey, snap_tolerance)

            if snapped_s:
                b2['start_point']  = (snapped_s['cx'], snapped_s['cy'])
                b2['start_column'] = snapped_s['id']
            if snapped_e:
                b2['end_point']  = (snapped_e['cx'], snapped_e['cy'])
                b2['end_column'] = snapped_e['id']

            # 스냅 후 스팬 길이 재계산
            p1, p2 = b2['start_point'], b2['end_point']
            b2['span_length'] = math.hypot(p2[0]-p1[0], p2[1]-p1[1])
            result.append(b2)
        return result

    def _nearest_column_snap(self,
                              x: float, y: float,
                              fixed_tol: float = None) -> Optional[Dict]:
        """점 (x,y)에서 가장 가까운 기둥 노드 반환. 없으면 None."""
        best     = None
        best_dist = float('inf')

        for col in self._column_nodes:
            d = math.hypot(x - col['cx'], y - col['cy'])
            # tolerance: 고정값 또는 기둥 크기 기반
            tol = fixed_tol if fixed_tol is not None else (
                max(col['width'], col['height']) * 0.8
            )
            if d < tol and d < best_dist:
                best_dist = d
                best      = col
        return best

    # ════════════════════════════════════════════════════════
    #  이름 텍스트 파싱
    # ════════════════════════════════════════════════════════
    def _parse_beam_name_texts(self) -> List[Dict]:
        name_layers = getattr(config, 'LAYER_NAMES', {}).get(
            'beam_name', ['!!0-BEAM-N', '!!0-GIRDER-N'])
        result = []
        for ent in self.msp:
            if ent.dxf.layer not in name_layers:
                continue
            if ent.dxftype() not in ('TEXT', 'MTEXT'):
                continue
            try:
                if ent.dxftype() == 'TEXT':
                    text = ent.dxf.text.strip()
                    x, y = ent.dxf.insert.x, ent.dxf.insert.y
                else:
                    text = ent.plain_mtext().strip()
                    x, y = ent.dxf.insert.x, ent.dxf.insert.y
                if text:
                    result.append({
                        'text':   text,
                        'x':      x,
                        'y':      y,
                        'layer':  ent.dxf.layer,
                        'family': _layer_family(ent.dxf.layer),
                    })
            except Exception:
                continue
        return result

    # ════════════════════════════════════════════════════════
    #  정밀 이름 매칭
    # ════════════════════════════════════════════════════════
    def match_beam_name(self,
                        x1: float, y1: float,
                        x2: float, y2: float,
                        beam_layer: str = '',
                        max_dist: float = None,
                        beam_index: int = -1) -> Optional[str]:
        """
        보 LINE에 가장 가까운 이름 텍스트를 1:1 매칭.
        이미 다른 보에 매칭된 텍스트는 재사용하지 않음.
        매칭 없으면 None 반환 → 호출측에서 임의명명.
        """
        if not self._beam_name_texts:
            return None

        max_d = max_dist or getattr(config, 'BEAM_NAME_MATCH_DIST', 3000)
        my_family = _layer_family(beam_layer)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2

        best_name  = None
        best_score = float('inf')
        best_idx   = -1

        for idx, t in enumerate(self._beam_name_texts):
            if idx in self._beam_name_used:
                continue   # 1:1: 이미 다른 보에 할당됨
            d_seg = self._pt_to_seg_dist(t['x'], t['y'], x1, y1, x2, y2)
            if d_seg > max_d:
                continue
            d_mid = math.hypot(t['x'] - mx, t['y'] - my)
            family_penalty = 0
            if my_family and t['family'] and t['family'] != my_family:
                family_penalty = max_d * 0.8
            score = d_seg + d_mid * 0.3 + family_penalty
            if score < best_score:
                best_score = score
                best_name  = t['text']
                best_idx   = idx

        if best_idx >= 0:
            self._beam_name_used.add(best_idx)  # 1:1 사용 표시

        return best_name

    def _compute_beam_line_pairs(self) -> List[Dict]:
        """
        보/거더 레이어의 LINE 쌍에서 beam_width 계산.
        두 평행선의 중간 선분을 중심선으로 사용.
        반환: [{layer, start, end, beam_width, member_type}, ...]
        """
        beam_layers  = set(config.LAYER_NAMES.get('beam', []))
        girder_layers= set(l for l in beam_layers if 'GIRDER' in l.upper())
        beam_only    = set(l for l in beam_layers if 'GIRDER' not in l.upper())

        # 레이어별로 LINE 수집
        raw: List[Dict] = []
        for ent in self.msp:
            if ent.dxftype() != 'LINE': continue
            layer = ent.dxf.layer
            if layer not in beam_layers: continue
            try:
                x1,y1 = ent.dxf.start.x, ent.dxf.start.y
                x2,y2 = ent.dxf.end.x,   ent.dxf.end.y
            except Exception: continue
            length = math.hypot(x2-x1, y2-y1)
            if length < 200: continue
            mt = 'GIRDER' if layer in girder_layers else 'BEAM'
            raw.append({'layer':layer,'start':(x1,y1),'end':(x2,y2),
                        'length':length,'mt':mt})

        if not raw:
            return []

        used   = [False]*len(raw)
        result = []
        ang_tol = math.radians(getattr(config,'PARALLEL_ANGLE_TOL',5.0))
        max_w   = getattr(config,'MAX_BEAM_WIDTH',2000)

        for i, s1 in enumerate(raw):
            if used[i]: continue
            x1a,y1a = s1['start']; x1b,y1b = s1['end']
            dx1,dy1 = x1b-x1a, y1b-y1a
            ang1 = math.atan2(dy1,dx1) % math.pi

            best_j=-1; best_d=float('inf')
            for j in range(i+1,len(raw)):
                if used[j]: continue
                if raw[j]['layer'] != s1['layer']: continue
                x2a,y2a = raw[j]['start']; x2b,y2b = raw[j]['end']
                dx2,dy2 = x2b-x2a, y2b-y2a
                ang2 = math.atan2(dy2,dx2) % math.pi
                da = abs(ang1-ang2); da=min(da,math.pi-da)
                if da > ang_tol: continue
                # 중간점 수직거리
                mx,my=(x1a+x1b)/2,(y1a+y1b)/2
                d = self._pt_seg_dist_static(mx,my,x2a,y2a,x2b,y2b)
                if 20 < d < max_w and d < best_d:
                    best_d=d; best_j=j

            if best_j >= 0:
                used[i]=True; used[best_j]=True
                # 중심선: 두 선분 끝점의 평균
                s2 = raw[best_j]
                cx1 = (s1['start'][0]+s2['start'][0])/2
                cy1 = (s1['start'][1]+s2['start'][1])/2
                cx2 = (s1['end'][0]+s2['end'][0])/2
                cy2 = (s1['end'][1]+s2['end'][1])/2
                bw  = round(best_d/10)*10
                result.append({'layer':s1['layer'],'mt':s1['mt'],
                               'start':(cx1,cy1),'end':(cx2,cy2),
                               'beam_width':bw})
            else:
                used[i]=True
                result.append({'layer':s1['layer'],'mt':s1['mt'],
                               'start':s1['start'],'end':s1['end'],
                               'beam_width':0})
        return result

    def get_beam_line_pairs(self) -> List[Dict]:
        """보 평행쌍 중심선 + beam_width 리스트"""
        return self._beam_line_pairs

    def apply_beam_widths(self, beam_data: List[Dict],
                          snap_tol: float = 500) -> List[Dict]:
        """
        beam_data의 각 보에 beam_width를 _beam_line_pairs에서 가져와 설정.
        보 중심선과 쌍 중심선의 거리가 snap_tol 이내이면 매칭.
        """
        if not self._beam_line_pairs:
            return beam_data
        used_pairs = [False]*len(self._beam_line_pairs)
        result = []
        for b in beam_data:
            bx1,by1 = b['start_point']; bx2,by2 = b['end_point']
            bmx,bmy = (bx1+bx2)/2,(by1+by2)/2
            best_j=-1; best_d=float('inf')
            for j,p in enumerate(self._beam_line_pairs):
                if used_pairs[j]: continue
                if p.get('beam_width',0) <= 0: continue
                px1,py1=p['start']; px2,py2=p['end']
                d = self._pt_seg_dist_static(bmx,bmy,px1,py1,px2,py2)
                if d < snap_tol and d < best_d:
                    best_d=d; best_j=j
            b2 = dict(b)
            if best_j >= 0:
                used_pairs[best_j]=True
                b2['beam_width'] = self._beam_line_pairs[best_j]['beam_width']
            result.append(b2)
        return result

    # ── 1:1 이름 매칭 리셋 ───────────────────────────────────
    def reset_beam_name_matching(self):
        """이름 매칭 사용 인덱스 초기화 (새 DXF 로드 시 호출)"""
        self._beam_name_used = set()

    # ════════════════════════════════════════════════════════
    #  기존 메서드 (빔/기둥 엔티티 리스트 — 분석 모듈용)
    # ════════════════════════════════════════════════════════
    def get_entities_by_layer(self, layer_names, entity_type=None):
        entities = []
        for layer_name in layer_names:
            q = (f'{entity_type}[layer=="{layer_name}"]' if entity_type
                 else f'*[layer=="{layer_name}"]')
            entities.extend(self.msp.query(q))
        return entities

    def get_all_layers(self):
        return [layer.dxf.name for layer in self.doc.layers]

    def get_layer_info(self):
        info = {}
        for ent in self.msp:
            info[ent.dxf.layer] = info.get(ent.dxf.layer, 0) + 1
        return info

    def print_layer_summary(self):
        print("\n=== 도면 레이어 정보 ===")
        for layer, count in sorted(self.get_layer_info().items()):
            print(f"  {layer}: {count}개 객체")

    def get_columns(self):
        layers = config.LAYER_NAMES['column']
        return (self.get_entities_by_layer(layers, 'CIRCLE') +
                self.get_entities_by_layer(layers, 'INSERT'))

    def get_beams(self):
        layers = (config.LAYER_NAMES.get('girder', []) +
                  config.LAYER_NAMES.get('beam',   []))
        return (self.get_entities_by_layer(layers, 'LINE') +
                self.get_entities_by_layer(layers, 'LWPOLYLINE'))

    def get_walls(self):
        layers = config.LAYER_NAMES['wall']
        return (self.get_entities_by_layer(layers, 'LINE') +
                self.get_entities_by_layer(layers, 'LWPOLYLINE'))

    # ── 유틸 ─────────────────────────────────────────────────
    @staticmethod
    def _pt_to_seg_dist(px, py, x1, y1, x2, y2):
        dx, dy = x2-x1, y2-y1
        l2 = dx*dx + dy*dy
        if l2 == 0:
            return math.hypot(px-x1, py-y1)
        t = max(0.0, min(1.0, ((px-x1)*dx + (py-y1)*dy) / l2))
        return math.hypot(px-(x1+t*dx), py-(y1+t*dy))
