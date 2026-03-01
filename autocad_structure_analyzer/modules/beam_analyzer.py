"""
보 스팬 계산 및 분석 모듈
- BEAM / GIRDER 레이어별 부재 종류 구분
- 평행 쌍선의 실제 중심선 기준으로 폭/이름 매칭 (개선)
- 이름별 목록표(name_schedule) 생성
"""

import math
from collections import defaultdict
from typing import List, Tuple, Dict, Optional
import config


def _layer_to_member_type(layer: str) -> str:
    lu = layer.upper()
    girder_layers = getattr(config, 'LAYER_NAMES', {}).get('girder', [])
    beam_layers   = getattr(config, 'LAYER_NAMES', {}).get('beam',   [])
    if layer in girder_layers or 'GIRDER' in lu: return 'GIRDER'
    if layer in beam_layers   or 'BEAM'   in lu: return 'BEAM'
    return 'BEAM'


class BeamAnalyzer:

    def __init__(self, beams, column_positions, dxf_reader=None):
        self.beams            = beams
        self.column_positions = column_positions
        self.dxf_reader       = dxf_reader
        self.beam_data        = []
        self.paired_beams     = []

    # ── 분석 ────────────────────────────────────────────────
    def analyze_spans(self) -> List[Dict]:
        results = []
        line_ents = self._extract_lines(self.beams)
        paired, singles = self._pair_parallel_lines(line_ents)
        self.paired_beams = paired

        candidates = []
        # paired: (cx1,cy1,cx2,cy2, width, layer, orig_line1, orig_line2)
        for item in paired:
            cx1,cy1,cx2,cy2,w,layer,l1,l2 = item
            candidates.append({
                'center_start': (cx1,cy1), 'center_end': (cx2,cy2),
                'width': w, 'layer': layer, 'source': 'paired',
                'line1': l1, 'line2': l2,
            })
        for s,e,layer in singles:
            candidates.append({
                'center_start': s, 'center_end': e,
                'width': 0, 'layer': layer, 'source': 'single',
                'line1': (s,e,layer), 'line2': None,
            })

        name_counter: Dict[str,int] = {}

        for i, cand in enumerate(candidates):
            bid   = f"B{i+1}"
            ps    = cand['center_start']
            pe    = cand['center_end']
            mtype = _layer_to_member_type(cand['layer'])

            # 이름 매칭: beam_layer 전달로 계열 우선 매칭
            raw = self._resolve_beam_name(
                ps[0], ps[1], pe[0], pe[1],
                beam_layer=cand['layer'],
                fallback=bid
            )
            name_counter[raw] = name_counter.get(raw, 0) + 1
            dname = raw if name_counter[raw] == 1 else f"{raw}-{name_counter[raw]}"

            base = {
                'beam_id':       bid,
                'beam_name':     dname,
                'beam_raw_name': raw,
                'member_type':   mtype,
                'beam_layer':    cand['layer'],
                'beam_width':    cand['width'],
                'memo':          '',
            }

            hits = self._find_intersecting_columns([ps, pe])
            if len(hits) >= 2:
                for si, span in enumerate(self._calculate_spans([ps,pe], hits)):
                    results.append({**base,
                        'beam_id':        f"{bid}-{si+1}",
                        'span_length':    span['length'],
                        'start_point':    span['start'],
                        'end_point':      span['end'],
                        'start_column':   span['start_column'],
                        'end_column':     span['end_column'],
                        'beam_direction': self._get_direction(span['start'], span['end']),
                    })
            else:
                L  = self._distance(ps, pe)
                mn = config.ANALYSIS_OPTIONS['min_span_length']
                mx = config.ANALYSIS_OPTIONS['max_span_length']
                if mn <= L <= mx:
                    results.append({**base,
                        'span_length':    L,
                        'start_point':    ps,
                        'end_point':      pe,
                        'start_column':   None,
                        'end_column':     None,
                        'beam_direction': self._get_direction(ps, pe),
                    })

        self.beam_data = results
        bc = sum(1 for r in results if r['member_type']=='BEAM')
        gc = sum(1 for r in results if r['member_type']=='GIRDER')
        nc = sum(1 for r in results if r['beam_name'] != r['beam_id'])
        print(f"✓ 부재 분석 완료: GIRDER {gc}개 / BEAM {bc}개  "
              f"(이름 매칭: {nc}개, 폭 인식: {len(paired)}개 쌍)")
        return results

    # ── 이름 목록표 ─────────────────────────────────────────
    def get_name_schedule(self) -> Dict:
        if not self.beam_data: self.analyze_spans()
        sch = {'BEAM': defaultdict(list), 'GIRDER': defaultdict(list)}
        for b in self.beam_data:
            sch[b['member_type']][b['beam_raw_name']].append(b)
        summary = {}
        for mt in ('BEAM','GIRDER'):
            names = sorted(sch[mt].keys())
            total = sum(len(v) for v in sch[mt].values())
            summary[mt] = {'total':total, 'unique_names':len(names), 'names':names}
        return {'BEAM':dict(sch['BEAM']), 'GIRDER':dict(sch['GIRDER']),
                'summary':summary}

    def print_name_schedule(self):
        sch = self.get_name_schedule()
        print("\n" + "="*62)
        print("  부재 이름 목록표")
        print("="*62)
        for mt in ('GIRDER','BEAM'):
            label = '거더 (GIRDER)' if mt=='GIRDER' else '보 (BEAM)'
            info  = sch['summary'][mt]
            print(f"\n▶ {label}  —  총 {info['total']}개 / {info['unique_names']}종")
            print(f"  {'이름':<10} {'개수':>5}  {'평균스팬':>10}  {'폭':>8}  스팬 범위")
            print(f"  {'-'*10} {'-'*5}  {'-'*10}  {'-'*8}  {'-'*20}")
            for name in sorted(sch[mt].keys()):
                ms  = sch[mt][name]
                sp  = [m['span_length'] for m in ms]
                ws  = [m['beam_width']  for m in ms if m.get('beam_width',0)>0]
                avg = sum(sp)/len(sp)/1000
                lo  = min(sp)/1000; hi = max(sp)/1000
                aw  = f"{sum(ws)/len(ws):.0f}mm" if ws else '-'
                rng = f"{lo:.2f}m" if lo==hi else f"{lo:.2f}~{hi:.2f}m"
                print(f"  {name:<10} {len(ms):>5}개  {avg:>8.2f}m  {aw:>8}  {rng}")
        print()

    # ── 이름 매칭 ────────────────────────────────────────────
    def _resolve_beam_name(self, x1, y1, x2, y2, beam_layer='', fallback=''):
        if not self.dxf_reader: return fallback
        try:
            n = self.dxf_reader.match_beam_name(x1,y1,x2,y2,
                                                 beam_layer=beam_layer)
            return n if n else fallback
        except Exception: return fallback

    # ── 평행 쌍선 그룹화 (중심선 정밀 계산) ─────────────────
    @staticmethod
    def _extract_lines(entities):
        lines = []
        for ent in entities:
            layer = ent.dxf.layer
            if ent.dxftype() == 'LINE':
                s = (ent.dxf.start.x, ent.dxf.start.y)
                e = (ent.dxf.end.x,   ent.dxf.end.y)
                if BeamAnalyzer._distance(s,e) > 1:
                    lines.append((s, e, layer))
            elif ent.dxftype() == 'LWPOLYLINE':
                pts = [(p[0],p[1]) for p in ent.get_points()]
                for i in range(len(pts)-1):
                    if BeamAnalyzer._distance(pts[i],pts[i+1]) > 1:
                        lines.append((pts[i], pts[i+1], layer))
        return lines

    def _pair_parallel_lines(self, lines):
        max_w   = getattr(config,'MAX_BEAM_WIDTH',2000)
        ang_tol = getattr(config,'PARALLEL_ANGLE_TOL',5.0)
        used    = [False]*len(lines)
        paired  = []
        singles = []

        def adeg(s,e):
            return math.degrees(math.atan2(e[1]-s[1], e[0]-s[0])) % 180

        for i,(s1,e1,l1) in enumerate(lines):
            if used[i]: continue
            a1=adeg(s1,e1); ln1=self._distance(s1,e1)
            bj,bd = -1,float('inf')

            for j,(s2,e2,l2) in enumerate(lines):
                if i==j or used[j]: continue
                df = abs(a1-adeg(s2,e2))
                if df>90: df=180-df
                if df>ang_tol: continue
                d = self._point_to_line_distance(s2,s1,e1)
                if d<1 or d>max_w: continue
                ln2 = self._distance(s2,e2)
                if min(ln1,ln2)/max(ln1,ln2) < 0.5: continue
                if not self._lines_overlap(s1,e1,s2,e2): continue
                if d<bd: bd=d; bj=j

            if bj >= 0:
                used[i] = used[bj] = True
                s2,e2,l2 = lines[bj]

                # ── 중심선 정밀 계산 ──
                # 두 선분의 방향 벡터 평균으로 정렬 후 수직 이등분 중심 계산
                cs, ce = self._calc_centerline(s1,e1,s2,e2)
                paired.append((cs[0],cs[1],ce[0],ce[1], bd, l1,
                               (s1,e1,l1),(s2,e2,l2)))
            else:
                singles.append((s1,e1,l1))

        for i,ln in enumerate(lines):
            if not used[i]: singles.append(ln)
        return paired, singles

    @staticmethod
    def _calc_centerline(s1, e1, s2, e2):
        """
        두 평행선의 정밀 중심선 계산.
        각 끝점에서 상대 선분으로 수선을 내려 중점 연결.
        """
        def proj_pt_on_seg(px,py,ax,ay,bx,by):
            dx,dy=bx-ax,by-ay; l2=dx*dx+dy*dy
            if l2==0: return ax,ay
            t=max(0.0,min(1.0,((px-ax)*dx+(py-ay)*dy)/l2))
            return ax+t*dx, ay+t*dy

        # s1 → 선2 수선 중점
        p1 = proj_pt_on_seg(s1[0],s1[1],s2[0],s2[1],e2[0],e2[1])
        # e1 → 선2 수선 중점
        p2 = proj_pt_on_seg(e1[0],e1[1],s2[0],s2[1],e2[0],e2[1])
        # s2 → 선1 수선 중점
        p3 = proj_pt_on_seg(s2[0],s2[1],s1[0],s1[1],e1[0],e1[1])
        # e2 → 선1 수선 중점
        p4 = proj_pt_on_seg(e2[0],e2[1],s1[0],s1[1],e1[0],e1[1])

        # 중심선 시작: s1과 대응점 p1의 중점, s2와 대응점 p3의 중점 평균
        csx = (s1[0]+p1[0])/2
        csy = (s1[1]+p1[1])/2
        cex = (e1[0]+p2[0])/2
        cey = (e1[1]+p2[1])/2
        return (csx,csy),(cex,cey)

    @staticmethod
    def _lines_overlap(s1,e1,s2,e2,min_r=0.3):
        dx=e1[0]-s1[0]; dy=e1[1]-s1[1]; l=math.hypot(dx,dy)
        if l==0: return False
        ts=((s2[0]-s1[0])*dx+(s2[1]-s1[1])*dy)/l**2
        te=((e2[0]-s1[0])*dx+(e2[1]-s1[1])*dy)/l**2
        return max(0,min(1,max(ts,te))-max(0,min(ts,te))) >= min_r

    # ── 기둥 교차 & 스팬 ─────────────────────────────────────
    def _find_intersecting_columns(self,bpts):
        tol=config.TOLERANCE['intersection']; hits=[]
        for idx,cp in enumerate(self.column_positions):
            for i in range(len(bpts)-1):
                if self._point_to_line_distance(cp,bpts[i],bpts[i+1])<=tol:
                    proj=self._project_point_to_line(cp,bpts[i],bpts[i+1])
                    if self._is_point_on_segment(proj,bpts[i],bpts[i+1]):
                        hits.append({'column_id':f"C{idx+1}",
                                     'position':cp,'projection':proj})
                        break
        if hits: hits.sort(key=lambda x:self._distance(bpts[0],x['projection']))
        return hits

    def _calculate_spans(self,bpts,cols):
        mn=config.ANALYSIS_OPTIONS['min_span_length']
        mx=config.ANALYSIS_OPTIONS['max_span_length']
        spans=[]
        for i in range(len(cols)-1):
            c1,c2=cols[i],cols[i+1]
            L=self._distance(c1['projection'],c2['projection'])
            if mn<=L<=mx:
                spans.append({'start':c1['projection'],'end':c2['projection'],
                              'start_column':c1['column_id'],
                              'end_column':c2['column_id'],'length':L})
        return spans

    # ── 유틸 ─────────────────────────────────────────────────
    @staticmethod
    def _distance(p1,p2): return math.hypot(p2[0]-p1[0],p2[1]-p1[1])

    @staticmethod
    def _point_to_line_distance(pt,a,b):
        x0,y0=pt;x1,y1=a;x2,y2=b
        l2=(x2-x1)**2+(y2-y1)**2
        if l2==0: return math.hypot(x0-x1,y0-y1)
        t=max(0,min(1,((x0-x1)*(x2-x1)+(y0-y1)*(y2-y1))/l2))
        return math.hypot(x0-(x1+t*(x2-x1)),y0-(y1+t*(y2-y1)))

    @staticmethod
    def _project_point_to_line(pt,a,b):
        x0,y0=pt;x1,y1=a;x2,y2=b
        l2=(x2-x1)**2+(y2-y1)**2
        if l2==0: return a
        t=max(0,min(1,((x0-x1)*(x2-x1)+(y0-y1)*(y2-y1))/l2))
        return (x1+t*(x2-x1),y1+t*(y2-y1))

    @staticmethod
    def _is_point_on_segment(pt,a,b,tol=1.0):
        x,y=pt;x1,y1=a;x2,y2=b
        return (min(x1,x2)-tol<=x<=max(x1,x2)+tol and
                min(y1,y2)-tol<=y<=max(y1,y2)+tol)

    @staticmethod
    def _get_direction(s,e):
        dx=abs(e[0]-s[0]);dy=abs(e[1]-s[1])
        if dx>dy*3: return 'X방향'
        if dy>dx*3: return 'Y방향'
        return '대각선'

    # ── 요약 ─────────────────────────────────────────────────
    def get_spans_by_direction(self):
        if not self.beam_data: self.analyze_spans()
        g={'X방향':[],'Y방향':[],'대각선':[]}
        for s in self.beam_data: g[s['beam_direction']].append(s)
        return g

    def get_spans_by_type(self):
        if not self.beam_data: self.analyze_spans()
        g={'BEAM':[],'GIRDER':[]}
        for s in self.beam_data: g[s['member_type']].append(s)
        return g

    def get_summary(self):
        if not self.beam_data: self.analyze_spans()
        bt=self.get_spans_by_type(); bd=self.get_spans_by_direction()
        ws=[s['beam_width'] for s in self.beam_data if s.get('beam_width',0)>0]
        nc=sum(1 for s in self.beam_data if s['beam_name']!=s['beam_id'])
        return {
            'total_spans':       len(self.beam_data),
            'beam_count':        len(bt['BEAM']),
            'girder_count':      len(bt['GIRDER']),
            'x_direction_spans': len(bd['X방향']),
            'y_direction_spans': len(bd['Y방향']),
            'diagonal_spans':    len(bd['대각선']),
            'avg_span_length':   (sum(s['span_length'] for s in self.beam_data)
                                  /len(self.beam_data) if self.beam_data else 0),
            'max_span_length':   max((s['span_length'] for s in self.beam_data),default=0),
            'min_span_length':   min((s['span_length'] for s in self.beam_data),default=0),
            'paired_beam_count': len(self.paired_beams),
            'avg_beam_width':    sum(ws)/len(ws) if ws else 0,
            'named_beam_count':  nc,
            'name_schedule':     self.get_name_schedule(),
        }
