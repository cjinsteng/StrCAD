"""
보 평면도 인터랙티브 HTML 뷰어 생성 모듈
- DXF 분석 결과를 브라우저에서 클릭 가능한 HTML로 내보내기
"""

import json
import math
import os
from typing import List, Dict, Optional


class BeamViewerExporter:
    """분석된 보 데이터를 인터랙티브 HTML 뷰어로 내보내는 클래스"""

    def __init__(self, beam_data: List[Dict],
                 column_positions: Optional[List] = None,
                 title: str = "구조 평면도 - 보 스팬 분석"):
        self.beam_data = beam_data
        self.column_positions = column_positions or []
        self.title = title

    def export(self, output_path: str = "beam_viewer.html") -> str:
        """HTML 파일 생성 및 저장"""
        beams_json   = self._prepare_beam_json()
        columns_json = self._prepare_column_json()
        bounds       = self._calc_bounds()

        html = self._build_html(beams_json, columns_json, bounds)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"✓ 인터랙티브 뷰어 저장: {output_path}")
        return output_path

    # ------------------------------------------------------------------ #
    #  데이터 준비
    # ------------------------------------------------------------------ #

    def _prepare_beam_json(self) -> str:
        beams = []
        for s in self.beam_data:
            beams.append({
                'id':         s['beam_id'],
                'layer':      s.get('beam_layer', ''),
                'x1':         s['start_point'][0],
                'y1':         s['start_point'][1],
                'x2':         s['end_point'][0],
                'y2':         s['end_point'][1],
                'span':       round(s['span_length'], 1),
                'span_m':     round(s['span_length'] / 1000, 3),
                'width':      round(s.get('beam_width', 0), 1),
                'direction':  s['beam_direction'],
                'col_start':  s.get('start_column') or '-',
                'col_end':    s.get('end_column')   or '-',
            })
        return json.dumps(beams, ensure_ascii=False)

    def _prepare_column_json(self) -> str:
        cols = [{'x': p[0], 'y': p[1]} for p in self.column_positions]
        return json.dumps(cols, ensure_ascii=False)

    def _calc_bounds(self) -> dict:
        pts = (
            [s['start_point'] for s in self.beam_data] +
            [s['end_point']   for s in self.beam_data] +
            list(self.column_positions)
        )
        if not pts:
            return {'xmin': 0, 'xmax': 1000, 'ymin': 0, 'ymax': 1000}
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        pad = max((max(xs)-min(xs)) * 0.05, (max(ys)-min(ys)) * 0.05, 500)
        return {
            'xmin': min(xs) - pad,
            'xmax': max(xs) + pad,
            'ymin': min(ys) - pad,
            'ymax': max(ys) + pad,
        }

    # ------------------------------------------------------------------ #
    #  HTML 빌드
    # ------------------------------------------------------------------ #

    def _build_html(self, beams_json: str, columns_json: str, bounds: dict) -> str:
        title = self.title
        total = len(self.beam_data)
        paired = sum(1 for s in self.beam_data if s.get('beam_width', 0) > 0)
        avg_span = (sum(s['span_length'] for s in self.beam_data) / total / 1000
                    if total else 0)

        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', 'Malgun Gothic', sans-serif;
          background: #1a1a2e; color: #e0e0e0; height: 100vh;
          display: flex; flex-direction: column; overflow: hidden; }}

  /* ── 헤더 ── */
  header {{ background: #16213e; padding: 10px 20px;
            display: flex; align-items: center; justify-content: space-between;
            border-bottom: 2px solid #0f3460; flex-shrink: 0; }}
  header h1 {{ font-size: 16px; color: #e94560; letter-spacing: 1px; }}
  .stats {{ display: flex; gap: 20px; }}
  .stat {{ text-align: center; }}
  .stat .val {{ font-size: 20px; font-weight: 700; color: #4ecca3; }}
  .stat .lbl {{ font-size: 10px; color: #888; }}

  /* ── 메인 레이아웃 ── */
  .main {{ display: flex; flex: 1; overflow: hidden; }}

  /* ── 캔버스 영역 ── */
  .canvas-wrap {{ flex: 1; position: relative; overflow: hidden; cursor: grab; }}
  .canvas-wrap:active {{ cursor: grabbing; }}
  canvas {{ display: block; }}

  /* ── 범례 ── */
  .legend {{ position: absolute; top: 12px; left: 12px;
             background: rgba(22,33,62,0.92); border: 1px solid #0f3460;
             border-radius: 8px; padding: 10px 14px; font-size: 12px; }}
  .legend-item {{ display: flex; align-items: center; gap: 8px; margin-bottom: 5px; }}
  .legend-dot {{ width: 20px; height: 4px; border-radius: 2px; }}

  /* ── 줌 버튼 ── */
  .zoom-btns {{ position: absolute; bottom: 20px; right: 20px;
                display: flex; flex-direction: column; gap: 6px; }}
  .zoom-btns button {{
    width: 36px; height: 36px; border-radius: 50%;
    border: none; background: #0f3460; color: #fff;
    font-size: 18px; cursor: pointer; transition: background .2s;
    display: flex; align-items: center; justify-content: center; }}
  .zoom-btns button:hover {{ background: #e94560; }}

  /* ── 사이드패널 ── */
  .side {{ width: 280px; background: #16213e; border-left: 2px solid #0f3460;
           display: flex; flex-direction: column; flex-shrink: 0; }}

  /* 검색/필터 */
  .filter-box {{ padding: 12px; border-bottom: 1px solid #0f3460; }}
  .filter-box input {{
    width: 100%; padding: 7px 10px; background: #1a1a2e;
    border: 1px solid #0f3460; border-radius: 6px; color: #e0e0e0;
    font-size: 13px; outline: none; }}
  .filter-box input:focus {{ border-color: #4ecca3; }}
  .dir-btns {{ display: flex; gap: 6px; margin-top: 8px; }}
  .dir-btn {{
    flex: 1; padding: 5px 0; border-radius: 5px; border: none;
    font-size: 11px; cursor: pointer; font-weight: 600; opacity: 0.5;
    transition: opacity .2s; }}
  .dir-btn.active {{ opacity: 1; }}
  .dir-btn.x {{ background: #2196F3; color: #fff; }}
  .dir-btn.y {{ background: #F44336; color: #fff; }}
  .dir-btn.d {{ background: #FF9800; color: #fff; }}
  .dir-btn.all {{ background: #555; color: #fff; }}

  /* 목록 */
  .beam-list {{ flex: 1; overflow-y: auto; padding: 8px; }}
  .beam-list::-webkit-scrollbar {{ width: 5px; }}
  .beam-list::-webkit-scrollbar-thumb {{ background: #0f3460; border-radius: 3px; }}
  .beam-item {{
    padding: 9px 11px; margin-bottom: 5px; border-radius: 7px;
    cursor: pointer; border-left: 3px solid transparent;
    background: #1a1a2e; transition: all .15s; font-size: 12px; }}
  .beam-item:hover {{ background: #0f3460; }}
  .beam-item.selected {{ background: #0f3460; border-left-color: #4ecca3; }}
  .beam-item .bid {{ font-weight: 700; font-size: 13px; }}
  .beam-item .binfo {{ color: #888; margin-top: 2px; }}

  /* 상세패널 */
  .detail {{ padding: 14px; border-top: 2px solid #0f3460;
             background: #0f3460; min-height: 180px; }}
  .detail h3 {{ font-size: 14px; color: #4ecca3; margin-bottom: 10px; }}
  .detail-empty {{ color: #555; font-size: 13px; text-align: center;
                   padding: 30px 0; }}
  .info-row {{ display: flex; justify-content: space-between;
               padding: 5px 0; border-bottom: 1px solid rgba(255,255,255,0.05);
               font-size: 12px; }}
  .info-row .key {{ color: #aaa; }}
  .info-row .val {{ color: #fff; font-weight: 600; }}
  .dir-badge {{
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 11px; font-weight: 700; }}
  .dir-x {{ background: #1565C0; color: #90CAF9; }}
  .dir-y {{ background: #B71C1C; color: #FFCDD2; }}
  .dir-d {{ background: #E65100; color: #FFE0B2; }}
</style>
</head>
<body>

<header>
  <h1>🏗 {title}</h1>
  <div class="stats">
    <div class="stat"><div class="val">{total}</div><div class="lbl">총 보 스팬</div></div>
    <div class="stat"><div class="val">{paired}</div><div class="lbl">폭 인식</div></div>
    <div class="stat"><div class="val">{avg_span:.2f}m</div><div class="lbl">평균 스팬</div></div>
    <div class="stat"><div class="val" id="col-cnt">-</div><div class="lbl">기둥</div></div>
  </div>
</header>

<div class="main">
  <!-- 캔버스 -->
  <div class="canvas-wrap" id="canvasWrap">
    <canvas id="cv"></canvas>

    <div class="legend">
      <div class="legend-item"><div class="legend-dot" style="background:#2196F3"></div>X방향 보</div>
      <div class="legend-item"><div class="legend-dot" style="background:#F44336"></div>Y방향 보</div>
      <div class="legend-item"><div class="legend-dot" style="background:#FF9800"></div>대각선 보</div>
      <div class="legend-item"><div class="legend-dot" style="background:#4CAF50;height:10px;width:10px;border-radius:2px"></div>기둥</div>
    </div>

    <div class="zoom-btns">
      <button onclick="zoom(1.2)">+</button>
      <button onclick="zoom(1/1.2)">−</button>
      <button onclick="resetView()" style="font-size:12px">⟳</button>
    </div>
  </div>

  <!-- 사이드패널 -->
  <div class="side">
    <div class="filter-box">
      <input id="search" placeholder="🔍 보 ID 검색..." oninput="filterList()">
      <div class="dir-btns">
        <button class="dir-btn all active" onclick="setDirFilter('all',this)">전체</button>
        <button class="dir-btn x" onclick="setDirFilter('X방향',this)">X방향</button>
        <button class="dir-btn y" onclick="setDirFilter('Y방향',this)">Y방향</button>
        <button class="dir-btn d" onclick="setDirFilter('대각선',this)">대각선</button>
      </div>
    </div>
    <div class="beam-list" id="beamList"></div>
    <div class="detail" id="detail">
      <div class="detail-empty">보를 클릭하면<br>상세 정보가 표시됩니다</div>
    </div>
  </div>
</div>

<script>
// ── 데이터 ──────────────────────────────────────────────────
const BEAMS   = {beams_json};
const COLUMNS = {columns_json};
const BOUNDS  = {json.dumps(bounds)};

// ── 상태 ────────────────────────────────────────────────────
let selected = null;
let dirFilter = 'all';
let pan = {{ x: 0, y: 0 }};
let scale = 1;
let isPanning = false, panStart = null, panOrigin = null;

// ── 색상 ────────────────────────────────────────────────────
const COLOR = {{ 'X방향':'#2196F3','Y방향':'#F44336','대각선':'#FF9800' }};

// ── 캔버스 초기화 ──────────────────────────────────────────
const wrap = document.getElementById('canvasWrap');
const cv   = document.getElementById('cv');
const ctx  = cv.getContext('2d');
document.getElementById('col-cnt').textContent = COLUMNS.length;

function resize() {{
  cv.width  = wrap.clientWidth;
  cv.height = wrap.clientHeight;
  draw();
}}
window.addEventListener('resize', resize);

// ── 좌표 변환 ──────────────────────────────────────────────
function toScreen(wx, wy) {{
  const W = cv.width, H = cv.height;
  const bw = BOUNDS.xmax - BOUNDS.xmin;
  const bh = BOUNDS.ymax - BOUNDS.ymin;
  const base = Math.min(W/bw, H/bh) * scale;
  const ox = (W - bw*base)/2 + pan.x;
  const oy = (H - bh*base)/2 + pan.y;
  return {{ x: ox + (wx - BOUNDS.xmin)*base,
            y: oy + (BOUNDS.ymax - wy)*base }};
}}
function toWorld(sx, sy) {{
  const W = cv.width, H = cv.height;
  const bw = BOUNDS.xmax - BOUNDS.xmin;
  const bh = BOUNDS.ymax - BOUNDS.ymin;
  const base = Math.min(W/bw, H/bh) * scale;
  const ox = (W - bw*base)/2 + pan.x;
  const oy = (H - bh*base)/2 + pan.y;
  return {{ x: (sx - ox)/base + BOUNDS.xmin,
            y: BOUNDS.ymax - (sy - oy)/base }};
}}

// ── 그리기 ──────────────────────────────────────────────────
function draw() {{
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.fillStyle = '#1a1a2e';
  ctx.fillRect(0, 0, cv.width, cv.height);

  // 기둥
  COLUMNS.forEach(c => {{
    const p = toScreen(c.x, c.y);
    const sz = Math.max(6, 300 * scale * Math.min(cv.width/(BOUNDS.xmax-BOUNDS.xmin), cv.height/(BOUNDS.ymax-BOUNDS.ymin)));
    ctx.fillStyle = '#4CAF50';
    ctx.globalAlpha = 0.8;
    ctx.fillRect(p.x - sz/2, p.y - sz/2, sz, sz);
    ctx.globalAlpha = 1;
  }});

  // 보
  const visible = BEAMS.filter(b =>
    (dirFilter === 'all' || b.direction === dirFilter) &&
    (document.getElementById('search').value === '' ||
     b.id.toLowerCase().includes(document.getElementById('search').value.toLowerCase()))
  );

  visible.forEach(b => {{
    const p1 = toScreen(b.x1, b.y1);
    const p2 = toScreen(b.x2, b.y2);
    const col = COLOR[b.direction] || '#aaa';
    const isSel = selected && selected.id === b.id;

    // 폭 영역 (반투명)
    if (b.width > 0) {{
      const dx = p2.x - p1.x, dy = p2.y - p1.y;
      const len = Math.hypot(dx, dy) || 1;
      const bw = BOUNDS.xmax - BOUNDS.xmin;
      const base = Math.min(cv.width/bw, cv.height/(BOUNDS.ymax-BOUNDS.ymin)) * scale;
      const hw = b.width * base / 2;
      const nx = -dy/len, ny = dx/len;
      ctx.beginPath();
      ctx.moveTo(p1.x + nx*hw, p1.y + ny*hw);
      ctx.lineTo(p2.x + nx*hw, p2.y + ny*hw);
      ctx.lineTo(p2.x - nx*hw, p2.y - ny*hw);
      ctx.lineTo(p1.x - nx*hw, p1.y - ny*hw);
      ctx.closePath();
      ctx.fillStyle = col;
      ctx.globalAlpha = isSel ? 0.35 : 0.12;
      ctx.fill();
      ctx.globalAlpha = 1;
    }}

    // 중심선
    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p2.x, p2.y);
    ctx.strokeStyle = isSel ? '#4ecca3' : col;
    ctx.lineWidth   = isSel ? 5 : (b.width > 0 ? 3.5 : 2);
    ctx.globalAlpha = isSel ? 1 : 0.85;
    ctx.lineCap = 'round';
    ctx.stroke();
    ctx.globalAlpha = 1;

    // 라벨 (충분히 길 때만)
    const screenLen = Math.hypot(p2.x-p1.x, p2.y-p1.y);
    if (screenLen > 40) {{
      const mx = (p1.x+p2.x)/2, my = (p1.y+p2.y)/2;
      ctx.font = isSel ? 'bold 12px sans-serif' : '10px sans-serif';
      ctx.fillStyle = isSel ? '#4ecca3' : '#fff';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      const label = b.id + '  ' + b.span_m + 'm' + (b.width > 0 ? '  W'+b.width : '');
      ctx.fillText(label, mx, my - 6);
    }}
  }});
}}

// ── 마우스 이벤트 ───────────────────────────────────────────
function hitTest(mx, my) {{
  const w = toWorld(mx, my);
  let best = null, bestD = 15; // px 허용 오차
  BEAMS.forEach(b => {{
    const p1 = toScreen(b.x1, b.y1);
    const p2 = toScreen(b.x2, b.y2);
    const d = pointToSegDist(mx, my, p1.x, p1.y, p2.x, p2.y);
    if (d < bestD) {{ bestD = d; best = b; }}
  }});
  return best;
}}

function pointToSegDist(px,py,x1,y1,x2,y2) {{
  const dx=x2-x1, dy=y2-y1, len2=dx*dx+dy*dy;
  if (!len2) return Math.hypot(px-x1,py-y1);
  let t=((px-x1)*dx+(py-y1)*dy)/len2;
  t=Math.max(0,Math.min(1,t));
  return Math.hypot(px-(x1+t*dx), py-(y1+t*dy));
}}

cv.addEventListener('mousedown', e => {{
  isPanning = true;
  panStart  = {{ x: e.clientX, y: e.clientY }};
  panOrigin = {{ ...pan }};
}});
cv.addEventListener('mousemove', e => {{
  if (!isPanning) return;
  pan.x = panOrigin.x + e.clientX - panStart.x;
  pan.y = panOrigin.y + e.clientY - panStart.y;
  draw();
}});
cv.addEventListener('mouseup', e => {{
  const moved = Math.hypot(e.clientX - panStart.x, e.clientY - panStart.y);
  isPanning = false;
  if (moved < 4) {{
    const rect = cv.getBoundingClientRect();
    const b = hitTest(e.clientX - rect.left, e.clientY - rect.top);
    selectBeam(b);
  }}
}});
cv.addEventListener('wheel', e => {{
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.12 : 1/1.12;
  const rect = cv.getBoundingClientRect();
  const mx = e.clientX - rect.left, my = e.clientY - rect.top;
  pan.x = mx + (pan.x - mx) * factor;
  pan.y = my + (pan.y - my) * factor;
  scale *= factor;
  draw();
}}, {{ passive: false }});

// 터치 지원
let lastTouch = null;
cv.addEventListener('touchstart', e => {{
  if (e.touches.length === 1) {{
    isPanning = true;
    panStart  = {{ x: e.touches[0].clientX, y: e.touches[0].clientY }};
    panOrigin = {{ ...pan }};
    lastTouch = {{ x: e.touches[0].clientX, y: e.touches[0].clientY }};
  }}
}}, {{ passive: true }});
cv.addEventListener('touchmove', e => {{
  if (e.touches.length === 1 && isPanning) {{
    pan.x = panOrigin.x + e.touches[0].clientX - panStart.x;
    pan.y = panOrigin.y + e.touches[0].clientY - panStart.y;
    draw();
  }}
}}, {{ passive: true }});
cv.addEventListener('touchend', e => {{
  if (lastTouch) {{
    const t = e.changedTouches[0];
    const moved = Math.hypot(t.clientX - lastTouch.x, t.clientY - lastTouch.y);
    isPanning = false;
    if (moved < 6) {{
      const rect = cv.getBoundingClientRect();
      const b = hitTest(t.clientX - rect.left, t.clientY - rect.top);
      selectBeam(b);
    }}
    lastTouch = null;
  }}
}});

// ── 선택 & 상세정보 ─────────────────────────────────────────
function selectBeam(b) {{
  selected = b;
  draw();
  renderDetail(b);
  if (b) highlightList(b.id);
}}

function renderDetail(b) {{
  const el = document.getElementById('detail');
  if (!b) {{
    el.innerHTML = '<div class="detail-empty">보를 클릭하면<br>상세 정보가 표시됩니다</div>';
    return;
  }}
  const dirClass = b.direction === 'X방향' ? 'dir-x' : b.direction === 'Y방향' ? 'dir-y' : 'dir-d';
  el.innerHTML = `
    <h3>📌 ${{b.id}}</h3>
    <div class="info-row"><span class="key">레이어</span><span class="val">${{b.layer}}</span></div>
    <div class="info-row"><span class="key">방향</span>
      <span class="val"><span class="dir-badge ${{dirClass}}">${{b.direction}}</span></span></div>
    <div class="info-row"><span class="key">스팬 길이</span>
      <span class="val">${{b.span_m}} m  <small style="color:#888">(${{b.span.toLocaleString()}} mm)</small></span></div>
    <div class="info-row"><span class="key">보 폭 (width)</span>
      <span class="val">${{b.width > 0 ? b.width + ' mm' : '미인식'}}</span></div>
    <div class="info-row"><span class="key">시작 기둥</span><span class="val">${{b.col_start}}</span></div>
    <div class="info-row"><span class="key">끝 기둥</span><span class="val">${{b.col_end}}</span></div>
    <div class="info-row"><span class="key">시작점 (X, Y)</span>
      <span class="val" style="font-size:11px">${{Math.round(b.x1)}}, ${{Math.round(b.y1)}}</span></div>
    <div class="info-row"><span class="key">끝점 (X, Y)</span>
      <span class="val" style="font-size:11px">${{Math.round(b.x2)}}, ${{Math.round(b.y2)}}</span></div>
  `;
}}

// ── 목록 렌더 ───────────────────────────────────────────────
function renderList() {{
  const search = document.getElementById('search').value.toLowerCase();
  const list   = document.getElementById('beamList');
  list.innerHTML = '';
  BEAMS.filter(b =>
    (dirFilter === 'all' || b.direction === dirFilter) &&
    (!search || b.id.toLowerCase().includes(search))
  ).forEach(b => {{
    const col = COLOR[b.direction] || '#aaa';
    const div = document.createElement('div');
    div.className = 'beam-item' + (selected && selected.id === b.id ? ' selected' : '');
    div.id = 'li-' + b.id.replace(/[^a-z0-9]/gi,'_');
    div.innerHTML = `
      <div class="bid" style="color:${{col}}">${{b.id}}</div>
      <div class="binfo">${{b.direction}} · ${{b.span_m}}m${{b.width>0?' · W'+b.width+'mm':''}}</div>`;
    div.onclick = () => selectBeam(b);
    list.appendChild(div);
  }});
}}

function highlightList(id) {{
  document.querySelectorAll('.beam-item').forEach(el => el.classList.remove('selected'));
  const el = document.getElementById('li-' + id.replace(/[^a-z0-9]/gi,'_'));
  if (el) {{ el.classList.add('selected'); el.scrollIntoView({{block:'nearest'}}); }}
}}

function filterList() {{ renderList(); draw(); }}
function setDirFilter(v, btn) {{
  dirFilter = v;
  document.querySelectorAll('.dir-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderList(); draw();
}}

// ── 줌 ──────────────────────────────────────────────────────
function zoom(f) {{
  const cx = cv.width/2, cy = cv.height/2;
  pan.x = cx + (pan.x - cx) * f;
  pan.y = cy + (pan.y - cy) * f;
  scale *= f;
  draw();
}}
function resetView() {{ pan = {{x:0,y:0}}; scale = 1; draw(); }}

// ── 초기화 ──────────────────────────────────────────────────
resize();
renderList();
</script>
</body>
</html>"""
