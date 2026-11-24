// StrCAD 현장조사 — 현장 스케치
//  도구: 부재(보·기둥·벽체, 자동네임) · 축 · 자유선 · 치수 · 글자
//  아래 줄: 색깔 · 이동 · 지우기 · 되돌리기 · 직교 · 스냅
//  한 손가락: 그리기 · 두 손가락: 이동/확대 · 그린 것을 꾹 누른 채 끌면 복사, 꾹 눌렀다 떼면 수정
//  저장은 도면 절대좌표(검측위치 rec.x/y와 같음) → PC 가져오기 시 같은 위치에 표시.
//  기둥 b·h, 벽 두께 t, 보 폭 w, 치수값 val 은 mm 로 따로 저장 → 축척을 바꿔도 그전에 그린 값은 그대로.
"use strict";

const SK = (() => {
  const COLORS = ["#e11d48", "#F28C28", "#eab308", "#16a34a", "#2563eb", "#7c3aed", "#111827", "#ec4899"];
  const TEXT_PRESETS = ["G1", "B1", "C1", "W1", "추가", "철거", "개구부", "도면과 다름"];
  const PREFIX = { beam: "G", column: "C", wall: "W" };
  const KIND_NM = { beam: "보", column: "기둥", wall: "벽체", axis: "축", dim: "치수", text: "글자", free: "자유선" };
  const DEF = { tool: "member", mem: "beam", dbl: false, beamW: 400, colB: 500, colH: 500, colStep: 10, wallT: 200,
    autoName: true, ortho: true, snap: true, color: COLORS[0] };
  const st = Object.assign({ list: [], op: null, cur: null, pend: null, undo: [], sel: null, snapMark: null, ghost: null }, DEF);
  try { Object.assign(st, JSON.parse(localStorage.getItem("skOpts") || "{}")); } catch (e) { /* ignore */ }
  st.op = null;
  const saveOpts = () => { try { localStorage.setItem("skOpts", JSON.stringify(Object.fromEntries(Object.keys(DEF).map((k) => [k, st[k]])))); } catch (e) { /* ignore */ } };
  const clone = (o) => JSON.parse(JSON.stringify(o));

  // ------------------------------------------------------------------ storage
  const conv = (pts, f) => { const o = []; for (let i = 0; i + 1 < pts.length; i += 2) o.push(...f(pts[i], pts[i + 1])); return o; };
  function load() {
    st.list = []; st.undo = []; st.cur = null; st.sel = null; st.pend = null;
    if (!S.db || !S.sheet) return;
    try {
      st.list = q("SELECT data FROM sketches WHERE sheet_id=? AND deleted=0", [S.sheet.id]).map((r) => {
        const sk = JSON.parse(r.data); sk.pts = conv(sk.pts || [], P); return sk; });
    } catch (e) { st.list = []; }
  }
  function write(sk, deleted) {
    sk.updated = nowIso();
    const out = Object.assign({}, sk, { pts: conv(sk.pts, A).map((v) => Math.round(v)) });
    run("INSERT OR REPLACE INTO sketches (uid, sheet_id, updated, deleted, data) VALUES (?,?,?,?,?)",
      [sk.uid, S.sheet.id, sk.updated, deleted ? 1 : 0, JSON.stringify(out)]);
    if (window.CO) CO.mark("sk", sk.uid);
    persistSoon();
  }
  function add(sk, record = true) {
    sk.uid = sk.uid || uid(); sk.inspector = inspector(); sk.date = today(); delete sk.owner; if (window.CO) CO.stamp(sk);
    sk.pts = sk.pts.map((v) => Math.round(v));
    write(sk, false); st.list.push(sk); if (record) st.undo.push({ t: "add", sk }); draw(); renderList();
    return sk;
  }
  const mineSk = (sk) => !window.CO || CO.mine(sk);
  const roToast = (sk) => toast(`👁 ${CO.ownerName(sk)} 님 스케치 — 보기만 가능 (꾹 눌러 끌면 내 것으로 복사)`);
  function remove(sk, record = true) {
    if (!mineSk(sk)) { roToast(sk); return; }
    write(sk, true); st.list = st.list.filter((x) => x.uid !== sk.uid);
    if (st.sel === sk.uid) st.sel = null;
    if (record) st.undo.push({ t: "del", sk }); draw(); renderList();
  }
  function modify(sk, prev) {                    // prev: 고치기 전 복사본 (되돌리기용)
    sk.pts = sk.pts.map((v) => Math.round(v));
    write(sk, false); st.undo.push({ t: "mod", sk, prev }); draw(); renderList();
  }
  function undo() {
    const a = st.undo.pop();
    if (!a) { toast("되돌릴 스케치가 없습니다"); return; }
    if (a.t === "add") remove(a.sk, false);
    else if (a.t === "del") { write(a.sk, false); st.list.push(a.sk); draw(); renderList(); }
    else if (a.t === "mod") { const i = st.list.findIndex((x) => x.uid === a.sk.uid); const back = clone(a.prev);
      if (i >= 0) st.list[i] = back; write(back, false); draw(); renderList(); }
    else if (a.t === "multi") { for (const sk of a.list) remove(sk, false); }
  }

  // ------------------------------------------------------------------ geometry
  const scr = (x, y) => w2s(x, y);
  const tolW = (px = 16) => px / S.view.s;
  function distSeg2(px, py, x1, y1, x2, y2) {
    const vx = x2 - x1, vy = y2 - y1, L = vx * vx + vy * vy;
    const t = L ? Math.max(0, Math.min(1, ((px - x1) * vx + (py - y1) * vy) / L)) : 0;
    return Math.hypot(px - (x1 + t * vx), py - (y1 + t * vy));
  }
  function footLine(px, py, x1, y1, x2, y2) {     // 무한 직선 위 수선의 발
    const vx = x2 - x1, vy = y2 - y1, L = vx * vx + vy * vy || 1, t = ((px - x1) * vx + (py - y1) * vy) / L;
    return [x1 + t * vx, y1 + t * vy, t];
  }
  function interLines(a, b) {                     // 두 직선 교점 (평행이면 null)
    const [x1, y1, x2, y2] = a, [x3, y3, x4, y4] = b;
    const d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4);
    if (Math.abs(d) < 1e-9) return null;
    const t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d;
    return [x1 + t * (x2 - x1), y1 + t * (y2 - y1)];
  }
  const colCenter = (sk) => [(sk.pts[0] + sk.pts[2]) / 2, (sk.pts[1] + sk.pts[3]) / 2];
  function colPts(cx, cy, b, h) { return [cx - b / 2, cy - h / 2, cx + b / 2, cy + h / 2]; }
  const isLine = (sk) => sk.kind === "beam" || sk.kind === "wall" || sk.kind === "axis" || sk.kind === "dim";

  // ---- 스냅: 끝점 · 기둥 중심/모서리 · 축 교점 > (직교 꺼짐일 때) 축·보 선 위
  function snapPoint(x, y, exclude) {
    if (!st.snap) return null;
    const lim = tolW(16); let best = null, bd = lim;
    const tryP = (px, py, type) => { const d = Math.hypot(px - x, py - y); if (d < bd) { bd = d; best = { p: [px, py], type }; } };
    const axes = [];
    for (const sk of st.list) {
      if (sk.uid === exclude) continue;
      const p = sk.pts;
      if (sk.kind === "axis") axes.push(p);
      if (isLine(sk)) { tryP(p[0], p[1], "end"); tryP(p[2], p[3], "end"); }
      else if (sk.kind === "column") { const c = colCenter(sk); tryP(c[0], c[1], "mid");
        tryP(p[0], p[1], "end"); tryP(p[2], p[3], "end"); tryP(p[0], p[3], "end"); tryP(p[2], p[1], "end"); }
    }
    for (let i = 0; i < axes.length; i++) for (let j = i + 1; j < axes.length; j++) { const c = interLines(axes[i], axes[j]); if (c) tryP(c[0], c[1], "int"); }
    for (const m of S.sheet.members) if (m.k === "c") tryP(m.c[0], m.c[1], "mid");
    else { const [p1, p2] = memEnds(m); tryP(...p1, "end"); tryP(...p2, "end"); }
    if (best) return best;
    // 선 위 (수선의 발)
    bd = tolW(12);
    for (const sk of st.list) {
      if (sk.uid === exclude || !(sk.kind === "axis" || sk.kind === "beam" || sk.kind === "wall")) continue;
      const p = sk.pts, [fx, fy, t] = footLine(x, y, ...p);
      if (sk.kind !== "axis" && (t < 0 || t > 1)) continue;
      const d = Math.hypot(fx - x, fy - y); if (d < bd) { bd = d; best = { p: [fx, fy], type: "on" }; }
    }
    return best;
  }
  function orthoPt(x0, y0, x, y) {                // 직교: 수평 또는 수직으로
    return Math.abs(x - x0) >= Math.abs(y - y0) ? [x, y0] : [x0, y];
  }
  // 시작점 기준 끝점: 스냅(점) > 직교 > 스냅(선)
  function endPoint(x0, y0, x, y, exclude) {
    const s = snapPoint(x, y, exclude);
    if (s && s.type !== "on") { st.snapMark = s; return s.p; }
    if (st.ortho) {
      let q = orthoPt(x0, y0, x, y);
      if (st.snap) {                              // 직교 방향 그대로 축·보 선과 만나는 점에 붙임
        const ray = q[0] === x0 && q[1] !== y0 ? [x0, y0, x0, y0 + 1] : [x0, y0, x0 + 1, y0];
        let bd = tolW(12), hitp = null;
        for (const sk of st.list) if (sk.uid !== exclude && (sk.kind === "axis" || sk.kind === "beam" || sk.kind === "wall")) {
          const c = interLines(ray, sk.pts); if (c && Math.hypot(c[0] - q[0], c[1] - q[1]) < bd) { bd = Math.hypot(c[0] - q[0], c[1] - q[1]); hitp = c; }
        }
        if (hitp) { st.snapMark = { p: hitp, type: "on" }; return hitp; }
      }
      st.snapMark = null; return q;
    }
    st.snapMark = s; return s ? s.p : [x, y];
  }
  function startPoint(x, y) { const s = snapPoint(x, y); st.snapMark = s; return s ? s.p : [x, y]; }

  // ---- 누른 곳의 스케치 (화면 16px)
  function hitItem(x, y, kinds) {
    const lim = tolW(16);
    for (let i = st.list.length - 1; i >= 0; i--) {
      const sk = st.list[i], p = sk.pts;
      if (kinds && !kinds.includes(sk.kind)) continue;
      if (sk.kind === "column") {
        const [x0, x1] = [Math.min(p[0], p[2]), Math.max(p[0], p[2])], [y0, y1] = [Math.min(p[1], p[3]), Math.max(p[1], p[3])];
        if (x >= x0 - lim && x <= x1 + lim && y >= y0 - lim && y <= y1 + lim) return sk;
      } else if (sk.kind === "text") {
        if (Math.abs(x - p[0]) < (sk.text.length * 9 + 10) / S.view.s && Math.abs(y - p[1]) < lim) return sk;
      } else if (sk.kind === "wall") {
        if (distSeg2(x, y, ...p) < Math.max(lim, (sk.t || 200) / 2)) return sk;
      } else if (sk.kind === "axis") {
        if (distSeg2(x, y, ...p) < lim) return sk;
        const L = Math.hypot(p[2] - p[0], p[3] - p[1]) || 1, ux = (p[2] - p[0]) / L, uy = (p[3] - p[1]) / L, R = 13 / S.view.s;   // 버블
        if (Math.hypot(x - (p[0] - ux * R), y - (p[1] - uy * R)) < R * 1.3 || Math.hypot(x - (p[2] + ux * R), y - (p[3] + uy * R)) < R * 1.3) return sk;
      } else {
        for (let k = 0; k + 3 < p.length; k += 2) if (distSeg2(x, y, p[k], p[k + 1], p[k + 2], p[k + 3]) < lim) return sk;
      }
    }
    return null;
  }

  // ------------------------------------------------------------------ 자동네임 (보 G1~ · 기둥 C1~ · 벽 W1~)
  function sizeKey(sk) {
    if (sk.kind === "column") return `${Math.round(sk.b)}x${Math.round(sk.h)}`;
    if (sk.kind === "wall") return `${Math.round(sk.t)}`;
    if (sk.kind === "beam") return `${Math.round(sk.w)}`;
    return "";
  }
  function sizeText(sk) {
    if (sk.kind === "column") return `${Math.round(sk.b)}×${Math.round(sk.h)}`;
    if (sk.kind === "wall") return `THK ${Math.round(sk.t)}`;
    if (sk.kind === "beam") return `${sk.dbl ? "복선" : "단선"} B${Math.round(sk.w)}`;
    if (sk.kind === "dim") return `${Math.round(sk.val)} mm`;
    if (sk.kind === "axis") return "";
    return "";
  }
  function autoNameFor(sk) {
    const pre = PREFIX[sk.kind]; if (!pre) return "";
    const key = sizeKey(sk), same = st.list.find((o) => o.uid !== sk.uid && o.kind === sk.kind && o.auto && o.name && sizeKey(o) === key);
    if (same) return same.name;
    const re = new RegExp("^" + pre + "(\\d+)$");
    const used = st.list.filter((o) => o.uid !== sk.uid && o.kind === sk.kind).map((o) => (re.exec(o.name || "") || [])[1]).filter(Boolean).map(Number);
    return pre + (Math.max(0, ...used) + 1);
  }
  function applyAuto(sk) { if (st.autoName && PREFIX[sk.kind]) { sk.auto = true; sk.name = autoNameFor(sk); } }

  // ------------------------------------------------------------------ pointer (app.js 에서 호출)
  function down(sx, sy) {
    const [x, y] = s2w(sx, sy);
    const p = st.pend = { sx, sy, x, y, hit: st.op === "erase" ? hitItem(x, y) : hitItem(x, y), moved: false, mode: null };
    clearTimeout(st.lpT);
    if (st.op === "erase") return;
    if (st.op === "move") { if (p.hit && !mineSk(p.hit)) { roToast(p.hit); p.hit = null; return; } if (p.hit) { p.mode = "move"; p.orig = clone(p.hit); p.ref = refPoint(p.hit, x, y); st.sel = p.hit.uid; draw(); } return; }
    if (p.hit && p.hit.kind !== "free") st.lpT = setTimeout(() => {
      if (st.pend !== p || p.moved) return;
      p.mode = "copy"; p.orig = clone(p.hit); p.ref = refPoint(p.hit, x, y); st.sel = p.hit.uid;
      try { navigator.vibrate && navigator.vibrate(30); } catch (e) { /* ignore */ }
      hint(p.hit.kind === "axis" ? "끌어서 평행 복사 (간격 표시) · 그대로 떼면 수정" : "끌어서 복사 · 그대로 떼면 수정"); draw();
    }, 450);
  }
  function move(sx, sy) {
    const p = st.pend; if (!p) return;
    if (!p.moved && Math.hypot(sx - p.sx, sy - p.sy) < 8) return;
    if (!p.moved) { p.moved = true; clearTimeout(st.lpT); if (!p.mode && st.op !== "erase") { p.mode = "draw"; beginDraw(p); } }
    const [x, y] = s2w(sx, sy);
    if (p.mode === "draw") updDraw(x, y);
    else if (p.mode === "move" || p.mode === "copy") updDrag(p, x, y);
    draw();
  }
  function up(sx, sy, cancelled) {
    const p = st.pend; st.pend = null; clearTimeout(st.lpT);
    const fin = () => { st.cur = null; st.ghost = null; st.snapMark = null; hint(""); draw(); };
    if (!p || cancelled) { if (p && p.mode === "move") restore(p); fin(); return; }
    if (!p.moved) { fin(); tapAt(p); return; }
    if (p.mode === "draw") finishDraw();
    else if (p.mode === "move") finishMove(p);
    else if (p.mode === "copy") finishCopy(p);
    fin();
  }
  function cancel() { const p = st.pend; st.pend = null; clearTimeout(st.lpT); if (p && p.mode === "move") restore(p); st.cur = null; st.ghost = null; st.snapMark = null; draw(); }
  function restore(p) { const i = st.list.findIndex((o) => o.uid === p.orig.uid); if (i >= 0) st.list[i] = clone(p.orig); }

  function tapAt(p) {
    const { x, y, hit } = p;
    if (p.mode === "copy") { editItem(hit); return; }                 // 꾹 눌렀다 뗌 → 수정
    if (st.op === "erase") { if (hit) { remove(hit); toast(`${KIND_NM[hit.kind]} 삭제 — ↶ 되돌리기 가능`); } else hint("지울 스케치를 누르세요"); return; }
    if (st.op === "move") { if (hit) editItem(hit); else hint("옮길 스케치를 끌거나, 눌러서 수정하세요"); return; }
    if (st.tool === "text") { if (hit && hit.kind === "text") editItem(hit); else askText([x, y]); return; }
    if (st.tool === "member" && st.mem === "column") {
      if (hit && hit.kind === "column") { editItem(hit); return; }
      const [cx, cy] = startPoint(x, y); st.snapMark = null;
      const sk = { kind: "column", color: st.color, b: st.colB, h: st.colH, pts: colPts(cx, cy, st.colB, st.colH) };
      applyAuto(sk); add(sk); toast(`기둥 ${sk.name ? sk.name + " " : ""}${st.colB}×${st.colH}`); return;
    }
    if (hit) { editItem(hit); return; }
    hint({ dim: "길이를 잴 두 점을 끌어서 이으세요", axis: "끌어서 축선을 그리세요", free: "끌어서 그리세요" }[st.tool] || "끌어서 그리세요");
    setTimeout(() => hint(""), 1400);
  }

  // ---- 새로 그리기
  function beginDraw(p) {
    const kind = st.tool === "member" ? st.mem : st.tool;
    const s = kind === "free" ? [p.x, p.y] : startPoint(p.x, p.y);
    st.cur = { kind, color: st.color, pts: [s[0], s[1], s[0], s[1]] };
  }
  function updDraw(x, y) {
    const c = st.cur; if (!c) return;
    if (c.kind === "free") { const n = c.pts.length; if (Math.hypot(x - c.pts[n - 2], y - c.pts[n - 1]) * S.view.s >= 3) c.pts.push(x, y); return; }
    if (c.kind === "column") {                     // 시작 모서리에서 끌기 — 크기는 5/10/50 단위
      const stp = st.colStep || 10, x0 = c.pts[0], y0 = c.pts[1];
      const b = Math.max(stp, Math.round(Math.abs(x - x0) / stp) * stp), h = Math.max(stp, Math.round(Math.abs(y - y0) / stp) * stp);
      c.pts[2] = x0 + Math.sign(x - x0 || 1) * b; c.pts[3] = y0 + Math.sign(y - y0 || 1) * h; c.b = b; c.h = h; return;
    }
    const q = endPoint(c.pts[0], c.pts[1], x, y);
    c.pts[2] = q[0]; c.pts[3] = q[1];
  }
  function finishDraw() {
    const c = st.cur; st.cur = null; if (!c) return;
    const L = Math.hypot(c.pts[2] - c.pts[0], c.pts[3] - c.pts[1]);
    if (c.kind === "free") { if (c.pts.length < 6) c.pts.push(c.pts[0] + 1 / S.view.s, c.pts[1]); c.pts = c.pts.slice(2); add(c); return; }
    if (c.kind === "column") {
      const [cx, cy] = colCenter(c); Object.assign(c, { pts: colPts(cx, cy, c.b, c.h) });
      st.colB = c.b; st.colH = c.h; saveOpts(); buildSub(); applyAuto(c); add(c); toast(`기둥 ${c.name ? c.name + " " : ""}${c.b}×${c.h}`); return;
    }
    if (L * S.view.s < 10) { hint("끌어서 그리세요"); setTimeout(() => hint(""), 1200); return; }
    if (c.kind === "beam") { c.w = st.beamW; c.dbl = !!st.dbl; applyAuto(c); add(c); return; }
    if (c.kind === "wall") { c.t = st.wallT; applyAuto(c); add(c); return; }
    if (c.kind === "dim") { c.val = Math.round(L); add(c); toast(`치수 ${c.val.toLocaleString()} mm`); return; }
    if (c.kind === "axis") { askAxis(c); return; }
  }

  // ---- 옮기기 · 복사 (꾹 눌러 끌기)
  function refPoint(sk, x, y) {                   // 끌 때 기준점: 누른 곳에서 가까운 끝점/중심
    const p = sk.pts; let best = [x, y], bd = tolW(24);
    const tryP = (px, py) => { const d = Math.hypot(px - x, py - y); if (d < bd) { bd = d; best = [px, py]; } };
    if (sk.kind === "column") tryP(...colCenter(sk)); else if (isLine(sk)) { tryP(p[0], p[1]); tryP(p[2], p[3]); }
    if (sk.kind === "column" && best[0] === x) best = colCenter(sk);
    return best;
  }
  function dragDelta(p, x, y) {
    let [tx, ty] = [x, y];
    const s = snapPoint(x, y, p.mode === "move" ? p.orig.uid : null);
    if (s && s.type !== "on" && p.orig.kind !== "axis") { tx = s.p[0]; ty = s.p[1]; st.snapMark = s; } else st.snapMark = null;
    let dx = tx - p.ref[0], dy = ty - p.ref[1];
    if (p.orig.kind === "axis") {                  // 축: 직각 방향으로만 (평행 이동) · 10mm 단위
      const q = p.orig.pts, L = Math.hypot(q[2] - q[0], q[3] - q[1]) || 1, nx = -(q[3] - q[1]) / L, ny = (q[2] - q[0]) / L;
      let d = dx * nx + dy * ny;
      // 다른 축 위치에 붙임
      let snapped = false;
      if (st.snap) for (const o of st.list) if (o.kind === "axis" && o.uid !== p.orig.uid) {
        const [fx, fy] = footLine(q[0] + nx * d, q[1] + ny * d, ...o.pts); const od = (fx - q[0]) * nx + (fy - q[1]) * ny;
        const par = Math.abs((o.pts[2] - o.pts[0]) * ny - (o.pts[3] - o.pts[1]) * nx) / (Math.hypot(o.pts[2] - o.pts[0], o.pts[3] - o.pts[1]) || 1) < 0.02;
        if (par && Math.abs(od - d) * S.view.s < 10) { d = od; snapped = true; break; }
      }
      if (!snapped) d = Math.round(d / 10) * 10;
      return [nx * d, ny * d, d];
    }
    if (st.ortho && !st.snapMark) { if (Math.abs(dx) >= Math.abs(dy)) dy = 0; else dx = 0; }
    return [dx, dy, Math.hypot(dx, dy)];
  }
  function shifted(o, dx, dy) { const n = clone(o); n.pts = n.pts.map((v, i) => v + (i % 2 ? dy : dx)); return n; }
  function updDrag(p, x, y) {
    const [dx, dy, d] = dragDelta(p, x, y);
    if (p.mode === "move") { const i = st.list.findIndex((o) => o.uid === p.orig.uid); if (i >= 0) st.list[i] = Object.assign(shifted(p.orig, dx, dy), { uid: p.orig.uid }); }
    else st.ghost = shifted(p.orig, dx, dy);
    p.d = d;
    hint(`${p.mode === "move" ? "이동" : "복사"} ${Math.round(Math.abs(d)).toLocaleString()} mm`);
  }
  function finishMove(p) {
    const sk = st.list.find((o) => o.uid === p.orig.uid); if (!sk) return;
    if (!p.d) { restore(p); return; }
    modify(sk, p.orig);
  }
  function finishCopy(p) {
    const g = st.ghost; st.ghost = null; if (!g || !p.d) return;
    delete g.uid; delete g.updated;
    if (g.kind === "axis") g.text = nextAxisName(p.orig.text);
    else if (g.auto) g.name = p.orig.name;           // 같은 크기 → 같은 이름
    delete g.owner; delete g.inspector;
    add(g); toast(`${KIND_NM[g.kind]} 복사${g.kind === "axis" ? ` — 간격 ${Math.round(Math.abs(p.d)).toLocaleString()} mm` : ""}`);
  }

  // ------------------------------------------------------------------ 축 이름
  function nextAxisName(t) {
    const used = new Set(st.list.filter((a) => a.kind === "axis").map((a) => a.text));
    let n = String(t || "");
    for (let k = 0; k < 200; k++) {
      let m;
      if ((m = /^(.*?)(\d+)$/.exec(n))) n = m[1] + (+m[2] + 1);
      else if ((m = /^(.*?)([A-Z])$/.exec(n))) n = m[1] + (m[2] === "Z" ? "AA" : String.fromCharCode(m[2].charCodeAt(0) + 1));
      else n = n + "'";
      if (!used.has(n)) return n;
    }
    return n;
  }
  function nextAxisNames(sk) {
    const p = sk.pts, horiz = Math.abs(p[2] - p[0]) >= Math.abs(p[3] - p[1]);
    const used = st.list.filter((a) => a.kind === "axis").map((a) => a.text);
    const nums = used.map((t) => /^\d+$/.test(t) ? +t : 0), lets = used.filter((t) => /^[A-Z]$/.test(t));
    const xn = (pre) => { let n = 1; while (used.includes(pre + n)) n++; return pre + n; };
    const num = String(Math.max(0, ...nums) + 1);
    const let_ = lets.length ? String.fromCharCode(Math.max(...lets.map((t) => t.charCodeAt(0))) + 1) : "A";
    return horiz ? [xn("Y"), let_, xn("X"), num] : [xn("X"), num, xn("Y"), let_];
  }
  function askAxis(sk) {
    let inp;
    const sug = nextAxisNames(sk);
    sheet((b) => {
      inp = el("input", { type: "text", class: "sk-input", value: sug[0], placeholder: "예: X1, Y2, 1, A" });
      const done = () => { const t = inp.value.trim(); $("#modal").classList.remove("show");
        add(Object.assign(sk, { text: t || sug[0] })); hint("축을 꾹 눌러 끌면 평행 복사 — 축 간격이 표시됩니다"); setTimeout(() => hint(""), 2600); };
      inp.addEventListener("keydown", (e) => { if (e.key === "Enter") done(); });
      b.append(el("h3", {}, "축(그리드) 이름"), inp,
        el("div", { class: "sk-presets" }, sug.map((t) => el("button", { onclick: () => { inp.value = t; } }, t))),
        el("p", { class: "small" }, "축 하나를 그린 뒤 꾹 눌러 끌면 복사되고, 축 사이 간격이 자동으로 표시됩니다. 축 교점·축선에 스냅됩니다."),
        el("div", { class: "btns" }, el("button", { class: "b gray", onclick: () => { $("#modal").classList.remove("show"); draw(); } }, "취소"),
          el("span", { class: "sp" }), el("button", { class: "b ok", onclick: done }, "넣기")));
    });
    setTimeout(() => { if (inp) { inp.focus(); inp.select(); } }, 50);
  }
  function askText(at, sk0) {
    let inp;
    sheet((b) => {
      inp = el("input", { type: "text", class: "sk-input", placeholder: "예: G1 400×700, 기둥 추가, 철거됨", value: sk0 ? sk0.text : "" });
      const done = () => { const t = inp.value.trim(); $("#modal").classList.remove("show"); if (!t) return;
        if (sk0) { const prev = clone(sk0); sk0.text = t; modify(sk0, prev); }
        else add({ kind: "text", color: st.color, pts: [Math.round(at[0]), Math.round(at[1])], text: t }); };
      inp.addEventListener("keydown", (e) => { if (e.key === "Enter") done(); });
      b.append(el("h3", {}, sk0 ? "글자 고치기" : "글자 넣기"), inp,
        el("div", { class: "sk-presets" }, TEXT_PRESETS.map((t) => el("button", { onclick: () => { inp.value = inp.value ? inp.value + " " + t : t; inp.focus(); } }, t))),
        el("div", { class: "btns" }, sk0 ? el("button", { class: "b danger", onclick: () => { $("#modal").classList.remove("show"); remove(sk0); } }, "삭제") : "",
          el("button", { class: "b gray", onclick: () => $("#modal").classList.remove("show") }, "취소"),
          el("span", { class: "sp" }), el("button", { class: "b ok", onclick: done }, sk0 ? "저장" : "넣기")));
    });
    setTimeout(() => inp && inp.focus(), 50);
  }

  // ------------------------------------------------------------------ 수정 창
  function numRow(label, val, step, chips, onChange) {
    const inp = el("input", { type: "number", class: "sk-num", value: Math.round(val), inputmode: "numeric", step: String(step) });
    const set = (v) => { inp.value = Math.max(step, Math.round(v / step) * step); onChange(+inp.value); };
    inp.oninput = () => { if (+inp.value > 0) onChange(+inp.value); };
    return el("div", { class: "sk-numrow" }, el("span", { class: "sk-lab" }, label),
      el("button", { class: "b gray", onclick: () => set((+inp.value || 0) - step) }, `−${step}`), inp,
      el("button", { class: "b gray", onclick: () => set((+inp.value || 0) + step) }, `+${step}`),
      el("div", { class: "sk-chips" }, chips.map((c) => el("button", { onclick: () => { inp.value = c; onChange(c); } }, String(c)))));
  }
  function editItem(sk) {
    if (!sk) return;
    if (!mineSk(sk)) { st.sel = sk.uid; draw(); roToast(sk); return; }
    st.sel = sk.uid; draw(); renderList();
    if (sk.kind === "text") { askText(null, sk); return; }
    const prev = clone(sk), w = clone(sk);
    const close = () => { $("#modal").classList.remove("show"); };
    sheet((b) => {
      b.append(el("h3", {}, `${KIND_NM[sk.kind]} 수정` + (sk.name ? ` — ${sk.name}` : sk.text ? ` — ${sk.text}` : "")));
      let nameInp = null;
      if (PREFIX[sk.kind]) {
        nameInp = el("input", { type: "text", class: "sk-input", value: w.name || "", placeholder: `예: ${PREFIX[sk.kind]}1` });
        b.append(el("div", { class: "sk-numrow" }, el("span", { class: "sk-lab" }, "이름"), nameInp,
          el("button", { class: "b gray", onclick: () => { w.auto = true; nameInp.value = autoNameFor(w); } }, "자동")));
      }
      if (sk.kind === "beam") {
        const seg = el("div", { class: "seg sk-seg" });
        const rs = () => { seg.innerHTML = ""; for (const [v, t] of [[false, "━ 단선"], [true, "═ 복선"]]) seg.append(el("button", { class: !!w.dbl === v ? "on" : "", onclick: () => { w.dbl = v; rs(); } }, t)); };
        rs(); b.append(el("div", { class: "sk-numrow" }, el("span", { class: "sk-lab" }, "형태"), seg));
        b.append(numRow("폭 b", w.w || 400, 10, [200, 250, 300, 350, 400, 450, 500, 600], (v) => { w.w = v; }));
        b.append(el("p", { class: "small" }, `길이 ${(Math.hypot(sk.pts[2] - sk.pts[0], sk.pts[3] - sk.pts[1]) / 1000).toFixed(2)} m`));
      } else if (sk.kind === "column") {
        const stp = st.colStep || 10;
        b.append(numRow("b (가로)", w.b || Math.abs(sk.pts[2] - sk.pts[0]), stp, [300, 400, 500, 600, 700, 800], (v) => { w.b = v; }));
        b.append(numRow("h (세로)", w.h || Math.abs(sk.pts[3] - sk.pts[1]), stp, [300, 400, 500, 600, 700, 800], (v) => { w.h = v; }));
      } else if (sk.kind === "wall") {
        b.append(numRow("두께 t", w.t || 200, 10, [150, 180, 200, 250, 300, 350, 400], (v) => { w.t = v; }));
        b.append(el("p", { class: "small" }, `길이 ${(Math.hypot(sk.pts[2] - sk.pts[0], sk.pts[3] - sk.pts[1]) / 1000).toFixed(2)} m`));
      } else if (sk.kind === "axis") {
        const ti = el("input", { type: "text", class: "sk-input", value: w.text || "" });
        ti.oninput = () => { w.text = ti.value.trim(); };
        b.append(el("div", { class: "sk-numrow" }, el("span", { class: "sk-lab" }, "축 이름"), ti));
        let gap = 6000, cnt = 1, dir = 1;
        b.append(el("div", { class: "grp" }, "평행 복사 (간격을 알 때)"),
          numRow("간격", gap, 100, [3000, 4000, 5000, 6000, 7000, 8000, 9000], (v) => { gap = v; }),
          numRow("개수", cnt, 1, [1, 2, 3, 4, 5, 6], (v) => { cnt = v; }),
          el("div", { class: "btns" }, el("button", { class: "b gray", onclick: () => { dir = -1; doCopy(); } }, "◀/▼ 쪽으로 복사"),
            el("span", { class: "sp" }), el("button", { class: "b edit", onclick: () => { dir = 1; doCopy(); } }, "▶/▲ 쪽으로 복사")));
        function doCopy() {
          const q = sk.pts, L = Math.hypot(q[2] - q[0], q[3] - q[1]) || 1;
          let nx = -(q[3] - q[1]) / L, ny = (q[2] - q[0]) / L; if (nx < -1e-9 || (Math.abs(nx) < 1e-9 && ny < 0)) { nx = -nx; ny = -ny; }   // +x / +y 쪽
          const made = []; let src = sk;
          for (let k = 1; k <= cnt; k++) { const g = shifted(sk, nx * gap * k * dir, ny * gap * k * dir); delete g.uid; delete g.updated; g.text = nextAxisName(src.text);
            src = add(g, false); made.push(src); }
          st.undo.push({ t: "multi", list: made }); close(); toast(`축 ${cnt}개 복사 (간격 ${gap.toLocaleString()} mm)`);
        }
      } else if (sk.kind === "dim") {
        const geomL = Math.round(Math.hypot(sk.pts[2] - sk.pts[0], sk.pts[3] - sk.pts[1]));
        b.append(numRow("치수값 (mm)", w.val || geomL, 10, [], (v) => { w.val = v; }));
        b.append(el("p", { class: "small" }, `지금 축척으로 잰 길이 ${geomL.toLocaleString()} mm`));
        if (S.sheet.extKind && !S.sheet.members.length) b.append(el("button", { class: "val wide", onclick: () => { close(); calibrateWith(sk); } },
          el("b", {}, "📏 이 치수로 축척 맞추기"), el("small", {}, "실제 길이를 넣으면 도면 축척을 바꿉니다 (그전에 그린 부재 크기·치수값은 그대로)")));
      }
      b.append(el("div", { class: "grp" }, "색깔"));
      const cs = el("div", { class: "sk-colors-pick" });
      const rc = () => { cs.innerHTML = ""; for (const c of COLORS) cs.append(el("button", { class: "sw" + (c === w.color ? " on" : ""), style: `--c:${c}`, onclick: () => { w.color = c; rc(); } })); };
      rc(); b.append(cs);
      b.append(el("div", { class: "btns" },
        el("button", { class: "b danger", onclick: () => { close(); remove(sk); toast(`${KIND_NM[sk.kind]} 삭제 — ↶ 되돌리기 가능`); } }, "삭제"),
        el("span", { class: "sp" }), el("button", { class: "b gray", onclick: close }, "취소"),
        el("button", { class: "b ok", onclick: () => {
          if (nameInp) { const nv = nameInp.value.trim(); if (nv !== (prev.name || "") && !(w.auto && nv === autoNameFor(w))) w.auto = false; w.name = nv; }
          if (sk.kind === "column") { const [cx, cy] = colCenter(sk); w.pts = colPts(cx, cy, w.b, w.h); }
          if (w.auto && PREFIX[sk.kind] && sizeKey(w) !== sizeKey(prev) && (!nameInp || nameInp.value.trim() === (prev.name || ""))) w.name = autoNameFor(w);
          Object.assign(sk, w); modify(sk, prev); close();
        } }, "저장")));
    });
  }

  // ---- 치수로 축척 맞추기: 그 치수만 새 값, 나머지 부재 크기·치수값은 그대로
  function calibrateWith(sk) {
    const geomL = Math.hypot(sk.pts[2] - sk.pts[0], sk.pts[3] - sk.pts[1]);
    if (geomL < 1) return;
    const v = parseFloat(prompt(`이 치수의 실제 길이 (mm)\n(지금 축척으로 ${Math.round(geomL).toLocaleString()} mm)`, String(Math.round(sk.val || geomL))));
    if (!(v > 0)) return;
    const prev = clone(sk); sk.val = Math.round(v); write(sk, false); st.undo.push({ t: "mod", sk, prev });
    if (window.NS && NS.rescale) NS.rescale(v / geomL, sk.pts[0], sk.pts[1]);
  }
  function dimAt(x, y) { return hitItem(x, y, ["dim"]); }

  // ------------------------------------------------------------------ drawing
  function label(t, x, y, col, size = 12, align = "center") {
    ctx.font = `bold ${size}px sans-serif`; ctx.textAlign = align; ctx.textBaseline = "middle";
    ctx.lineWidth = 3.5; ctx.strokeStyle = "#fff"; ctx.strokeText(t, x, y); ctx.fillStyle = col; ctx.fillText(t, x, y);
  }
  function band(p, half) {                        // 두께 있는 선 (벽·복선 보) → 화면 다각형 네 점
    const L = Math.hypot(p[2] - p[0], p[3] - p[1]) || 1, nx = -(p[3] - p[1]) / L * half, ny = (p[2] - p[0]) / L * half;
    return [scr(p[0] + nx, p[1] + ny), scr(p[2] + nx, p[3] + ny), scr(p[2] - nx, p[3] - ny), scr(p[0] - nx, p[1] - ny)];
  }
  function drawOne(sk, live, sel) {
    const p = sk.pts, col = sk.color || COLORS[0];
    ctx.save(); ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineCap = "round"; ctx.lineJoin = "round";
    if (live) ctx.setLineDash([8, 5]);
    const halo = (fn) => { if (!sel) return; ctx.save(); ctx.setLineDash([]); ctx.strokeStyle = "#f59e0bcc"; ctx.lineWidth = 9; ctx.lineCap = "round"; fn(); ctx.restore(); };
    if (sk.kind === "beam" || sk.kind === "wall") {
      const a = scr(p[0], p[1]), b = scr(p[2], p[3]);
      const thick = sk.kind === "wall" ? (sk.t || st.wallT) : (sk.w || st.beamW);
      const wpx = thick * S.view.s;
      halo(() => { ctx.lineWidth = Math.max(12, wpx + 8); ctx.beginPath(); segTo(a, b); ctx.stroke(); });
      if (sk.kind === "wall") {
        if (wpx >= 5) { const q = band(p, thick / 2); ctx.globalAlpha = 0.45; ctx.beginPath(); q.forEach((v, i) => i ? ctx.lineTo(...v) : ctx.moveTo(...v)); ctx.closePath(); ctx.fill();
          ctx.globalAlpha = 1; ctx.lineWidth = 1.5; ctx.stroke(); }
        else { ctx.lineWidth = 6; ctx.globalAlpha = 0.75; ctx.beginPath(); segTo(a, b); ctx.stroke(); ctx.globalAlpha = 1; }
      } else if ((sk.dbl ?? (live && st.dbl)) && wpx >= 3) {
        const q = band(p, thick / 2); ctx.lineWidth = 2;
        ctx.beginPath(); segTo(q[0], q[1]); segTo(q[3], q[2]); ctx.stroke();
        ctx.lineWidth = 1; ctx.setLineDash([6, 3]); ctx.globalAlpha = 0.6; ctx.beginPath(); segTo(a, b); ctx.stroke(); ctx.globalAlpha = 1; if (!live) ctx.setLineDash([]);
      } else {
        ctx.lineWidth = 4.5; ctx.beginPath(); segTo(a, b); ctx.stroke();
        ctx.setLineDash([]); for (const v of [a, b]) { ctx.beginPath(); ctx.arc(v[0], v[1], 3.5, 0, 7); ctx.fill(); }
      }
      const L = Math.hypot(p[2] - p[0], p[3] - p[1]), mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
      ctx.setLineDash([]);
      if (live) label(`${(L / 1000).toFixed(2)} m`, mx, my - 12, col);
      else if (sk.name && Math.hypot(b[0] - a[0], b[1] - a[1]) > 30) label(sk.name, mx, my - Math.max(10, wpx / 2 + 8), col, 12);
    } else if (sk.kind === "column") {
      const a = scr(p[0], p[1]), b = scr(p[2], p[3]);
      const x = Math.min(a[0], b[0]), y = Math.min(a[1], b[1]), w = Math.max(Math.abs(b[0] - a[0]), 4), h = Math.max(Math.abs(b[1] - a[1]), 4);
      halo(() => { ctx.lineWidth = 6; ctx.strokeRect(x - 3, y - 3, w + 6, h + 6); });
      ctx.globalAlpha = 0.35; ctx.fillRect(x, y, w, h); ctx.globalAlpha = 1; ctx.lineWidth = 2.5; ctx.strokeRect(x, y, w, h);
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + w, y + h); ctx.moveTo(x + w, y); ctx.lineTo(x, y + h); ctx.lineWidth = 1; ctx.stroke();
      ctx.setLineDash([]);
      const bw = sk.b || Math.abs(p[2] - p[0]), bh = sk.h || Math.abs(p[3] - p[1]);
      if (live || w > 26) label((sk.name ? sk.name + " " : "") + `${Math.round(bw)}×${Math.round(bh)}`, x + w / 2, y - 9, col, 11);
    } else if (sk.kind === "free") {
      halo(() => { ctx.beginPath(); for (let i = 0; i < p.length; i += 2) { const v = scr(p[i], p[i + 1]); i ? ctx.lineTo(...v) : ctx.moveTo(...v); } ctx.stroke(); });
      ctx.lineWidth = 3; ctx.beginPath();
      for (let i = 0; i < p.length; i += 2) { const v = scr(p[i], p[i + 1]); i ? ctx.lineTo(v[0], v[1]) : ctx.moveTo(v[0], v[1]); }
      ctx.stroke();
    } else if (sk.kind === "axis") {
      const a = scr(p[0], p[1]), b = scr(p[2], p[3]), L = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
      const ux = (b[0] - a[0]) / L, uy = (b[1] - a[1]) / L, R = 13;
      halo(() => { ctx.lineWidth = 7; ctx.beginPath(); segTo(a, b); ctx.stroke(); });
      ctx.lineWidth = 1.5; ctx.setLineDash([14, 4, 3, 4]);
      ctx.beginPath(); segTo(a, b); ctx.stroke(); ctx.setLineDash([]);
      if (sk.text || live) for (const [v, sgn] of [[a, -1], [b, 1]]) {
        const cx = v[0] + ux * R * sgn, cy = v[1] + uy * R * sgn;
        if (cx < -40 || cy < -40 || cx > VW + 40 || cy > VH + 40) continue;
        ctx.fillStyle = "#fff"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(cx, cy, R, 0, 7); ctx.fill(); ctx.stroke();
        ctx.fillStyle = col; ctx.font = `bold ${(sk.text || "").length > 2 ? 10 : 12}px sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillText(sk.text || "?", cx, cy + 0.5);
      }
    } else if (sk.kind === "dim") {
      const a = scr(p[0], p[1]), b = scr(p[2], p[3]), L = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
      const ux = (b[0] - a[0]) / L, uy = (b[1] - a[1]) / L;
      halo(() => { ctx.lineWidth = 8; ctx.beginPath(); segTo(a, b); ctx.stroke(); });
      ctx.lineWidth = 1.6; ctx.beginPath(); segTo(a, b); ctx.stroke(); ctx.setLineDash([]);
      ctx.lineWidth = 2;
      for (const v of [a, b]) { ctx.beginPath(); ctx.moveTo(v[0] - (ux + uy) * 6, v[1] - (uy - ux) * 6); ctx.lineTo(v[0] + (ux + uy) * 6, v[1] + (uy - ux) * 6); ctx.stroke();      // 사선 틱
        ctx.beginPath(); ctx.moveTo(v[0] + uy * 9, v[1] - ux * 9); ctx.lineTo(v[0] - uy * 9, v[1] + ux * 9); ctx.lineWidth = 1; ctx.stroke(); ctx.lineWidth = 2; }
      const val = live ? Math.hypot(p[2] - p[0], p[3] - p[1]) : sk.val;
      const ang = Math.atan2(b[1] - a[1], b[0] - a[0]), up = ang > Math.PI / 2 || ang < -Math.PI / 2 ? ang + Math.PI : ang;
      ctx.save(); ctx.translate((a[0] + b[0]) / 2, (a[1] + b[1]) / 2); ctx.rotate(up);
      label(Math.round(val).toLocaleString(), 0, -10, col, 12); ctx.restore();
    } else if (sk.kind === "text") {
      const v = scr(p[0], p[1]);
      halo(() => { ctx.lineWidth = 3; ctx.strokeRect(v[0] - sk.text.length * 8 - 4, v[1] - 12, sk.text.length * 16 + 8, 24); });
      ctx.setLineDash([]); label(sk.text, v[0], v[1], col, 15);
    }
    ctx.restore();
  }
  // 평행한 축 사이 간격 자동 표시
  function drawAxisGaps() {
    const ax = st.list.filter((a) => a.kind === "axis");
    if (ax.length < 2) return;
    const groups = [];
    for (const a of ax) {
      const p = a.pts, L = Math.hypot(p[2] - p[0], p[3] - p[1]); if (L < 1) continue;
      let ux = (p[2] - p[0]) / L, uy = (p[3] - p[1]) / L; if (ux < -1e-9 || (Math.abs(ux) < 1e-9 && uy < 0)) { ux = -ux; uy = -uy; }
      let g = groups.find((G) => Math.abs(G.ux * uy - G.uy * ux) < 0.02);
      if (!g) groups.push(g = { ux, uy, items: [] });
      g.items.push(a);
    }
    ctx.save();
    for (const g of groups) {
      if (g.items.length < 2) continue;
      const nx = -g.uy, ny = g.ux;
      const rows = g.items.map((a) => { const p = a.pts, s0 = p[0] * g.ux + p[1] * g.uy, s1 = p[2] * g.ux + p[3] * g.uy;
        return { a, off: p[0] * nx + p[1] * ny, smax: Math.max(s0, s1), smin: Math.min(s0, s1) }; }).sort((A1, B1) => A1.off - B1.off);
      const top = Math.max(...rows.map((r) => r.smax)) + 46 / S.view.s;          // 버블 바깥쪽에 간격 표시
      for (let i = 0; i + 1 < rows.length; i++) {
        const d = rows[i + 1].off - rows[i].off; if (d * S.view.s < 14) continue;
        const P1 = [g.ux * top + nx * rows[i].off, g.uy * top + ny * rows[i].off], P2 = [g.ux * top + nx * rows[i + 1].off, g.uy * top + ny * rows[i + 1].off];
        const a = scr(...P1), b = scr(...P2);
        ctx.strokeStyle = "#475569"; ctx.lineWidth = 1.2; ctx.beginPath(); segTo(a, b); ctx.stroke();
        for (const v of [a, b]) { ctx.beginPath(); ctx.arc(v[0], v[1], 2.5, 0, 7); ctx.fillStyle = "#475569"; ctx.fill(); }
        const ang = Math.atan2(b[1] - a[1], b[0] - a[0]), upA = ang > Math.PI / 2 || ang < -Math.PI / 2 ? ang + Math.PI : ang;
        ctx.save(); ctx.translate((a[0] + b[0]) / 2, (a[1] + b[1]) / 2); ctx.rotate(upA); label(Math.round(d).toLocaleString(), 0, -9, "#334155", 11); ctx.restore();
      }
    }
    ctx.restore();
  }
  function drawSnap() {
    const m = st.snapMark; if (!m || !(st.cur || st.pend)) return;
    const [x, y] = scr(...m.p); ctx.save(); ctx.strokeStyle = "#16a34a"; ctx.lineWidth = 2;
    if (m.type === "int") { ctx.beginPath(); ctx.moveTo(x - 7, y - 7); ctx.lineTo(x + 7, y + 7); ctx.moveTo(x + 7, y - 7); ctx.lineTo(x - 7, y + 7); ctx.stroke(); }
    else if (m.type === "on") { ctx.beginPath(); ctx.moveTo(x, y - 8); ctx.lineTo(x + 7, y + 5); ctx.lineTo(x - 7, y + 5); ctx.closePath(); ctx.stroke(); }
    else if (m.type === "mid") { ctx.beginPath(); ctx.arc(x, y, 7, 0, 7); ctx.stroke(); }
    else ctx.strokeRect(x - 6, y - 6, 12, 12);
    ctx.restore();
  }
  function drawAll() {
    if (!S.sheet || (hidden() && S.mode !== "sketch")) return;
    drawAxisGaps();
    for (const sk of st.list) drawOne(sk, false, S.mode === "sketch" && sk.uid === st.sel);
    if (st.ghost) { ctx.save(); ctx.globalAlpha = 0.6; drawOne(st.ghost, true); ctx.restore(); }
    if (st.cur) drawOne(st.cur, true);
    drawSnap();
  }

  // ------------------------------------------------------------------ 부재 목록 (조사 목록 자리에 표시)
  function members() {
    const ord = { beam: 0, column: 1, wall: 2, axis: 3, dim: 4 };
    return st.list.filter((s) => ord[s.kind] != null).sort((a, b) => ord[a.kind] - ord[b.kind] ||
      String(a.name || a.text || "").localeCompare(String(b.name || b.text || ""), "ko", { numeric: true }));
  }
  function renderList() {
    if (S.mode !== "sketch" || typeof $ !== "function" || !$("#lt-b")) return;
    const ms = members();
    $("#listCount").textContent = `스케치 ${ms.length}개`;
    $("#lt-h").innerHTML = ""; $("#lt-h").append(el("tr", {}, ["이름", "종류", "크기", "길이(m)"].map((t) => el("th", {}, t))));
    const tb = $("#lt-b"); tb.innerHTML = "";
    if (!ms.length) { tb.append(el("tr", {}, el("td", { colspan: "4", class: "empty" }, "부재·축·치수를 그리면 여기에 목록이 나옵니다 (자동네임: 보 G1~ · 기둥 C1~ · 벽 W1~)"))); return; }
    for (const sk of ms) {
      const L = isLine(sk) ? (Math.hypot(sk.pts[2] - sk.pts[0], sk.pts[3] - sk.pts[1]) / 1000).toFixed(2) : "";
      tb.append(el("tr", { class: sk.uid === st.sel ? "sel" : "", onclick: () => { focus(sk); editItem(sk); } },
        el("td", {}, el("b", { style: `color:${sk.color || COLORS[0]}` }, sk.name || sk.text || "-")), el("td", {}, KIND_NM[sk.kind]), el("td", {}, sizeText(sk)), el("td", {}, L)));
    }
  }
  function focus(sk) {
    st.sel = sk.uid;
    const c = sk.kind === "column" ? colCenter(sk) : [(sk.pts[0] + sk.pts[2]) / 2, (sk.pts[1] + sk.pts[3]) / 2];
    const [sx, sy] = w2s(...c), r = $("#cv").getBoundingClientRect();
    if (sx < 40 || sy < 40 || sx > r.width - 40 || sy > r.height - 40) { S.view.ox = c[0] - r.width / 2 / S.view.s; S.view.oy = c[1] + r.height / 2 / S.view.s; }
    draw();
  }

  // ------------------------------------------------------------------ toolbar
  function hintFor() {
    if (st.op === "move") return "끌어서 옮기기 · 누르면 수정";
    if (st.op === "erase") return "지울 스케치를 누르세요";
    return { member: { beam: `끌어서 보 그리기 (${st.dbl ? "복선" : "단선"} B${st.beamW})`, column: `누르면 ${st.colB}×${st.colH} 기둥 · 끌면 ${st.colStep}단위 크기`,
      wall: `끌어서 벽 그리기 (두께 ${st.wallT})` }[st.mem],
      axis: "끌어서 축선 → 이름 · 꾹 눌러 끌면 평행 복사(간격 표시)", free: "자유롭게 그리기", dim: "끌어서 거리 재기 · 치수를 누르면 수정/축척 맞추기",
      text: "글자 넣을 곳을 누르세요" }[st.tool];
  }
  function chip(text, on, fn, cls = "") { return el("button", { class: (on ? "on " : "") + cls, onclick: fn }, text); }
  function pickNum(title, cur, chips, cb) {
    sheet((b) => {
      const inp = el("input", { type: "number", class: "sk-input", value: cur, inputmode: "numeric" });
      const done = (v) => { if (v > 0) { cb(Math.round(v)); $("#modal").classList.remove("show"); } };
      inp.addEventListener("keydown", (e) => { if (e.key === "Enter") done(+inp.value); });
      b.append(el("h3", {}, title), el("div", { class: "sk-presets" }, chips.map((c) => el("button", { class: c === cur ? "on" : "", onclick: () => done(c) }, String(c)))),
        inp, el("div", { class: "btns" }, el("span", { class: "sp" }), el("button", { class: "b gray", onclick: () => $("#modal").classList.remove("show") }, "취소"),
          el("button", { class: "b ok", onclick: () => done(+inp.value) }, "확인")));
    });
  }
  function buildSub() {
    const box = $("#skSub"); if (!box) return; box.innerHTML = "";
    box.classList.toggle("hidden", st.tool !== "member");
    if (st.tool !== "member") return;
    const set = (k, v) => { st[k] = v; saveOpts(); buildSub(); hint(hintFor()); setTimeout(() => hint(""), 1600); };
    box.append(chip("━ 보", st.mem === "beam", () => set("mem", "beam")), chip("■ 기둥", st.mem === "column", () => set("mem", "column")),
      chip("▬ 벽체", st.mem === "wall", () => set("mem", "wall")), el("i", { class: "sk-sep" }));
    if (st.mem === "beam") box.append(chip("단선", !st.dbl, () => set("dbl", false)), chip("복선", !!st.dbl, () => set("dbl", true)),
      chip(`폭 ${st.beamW}`, false, () => pickNum("보 폭 (mm)", st.beamW, [200, 250, 300, 350, 400, 450, 500, 600, 700], (v) => set("beamW", v)), "val"));
    if (st.mem === "column") box.append(...[5, 10, 50].map((n) => chip(`${n}단위`, st.colStep === n, () => set("colStep", n))),
      chip(`기본 ${st.colB}×${st.colH}`, false, () => pickNum("기본 기둥 크기 (정사각, mm)", st.colB, [300, 400, 450, 500, 600, 700, 800], (v) => { st.colH = v; set("colB", v); }), "val"));
    if (st.mem === "wall") box.append(chip(`두께 ${st.wallT}`, false, () => pickNum("벽 두께 (mm)", st.wallT, [150, 180, 200, 250, 300, 350, 400, 500], (v) => set("wallT", v)), "val"));
    box.append(el("i", { class: "sk-sep" }), chip(`자동네임 ${st.autoName ? "유" : "무"}`, st.autoName, () => set("autoName", !st.autoName)));
  }
  function buildOps() {
    const box = $("#skOps"); if (!box) return; box.innerHTML = "";
    box.append(el("button", { onclick: pickColor }, el("i", { class: "sk-dot", style: `background:${st.color}` }), "색깔"),
      chip("✥ 이동", st.op === "move", () => { st.op = st.op === "move" ? null : "move"; buildOps(); hint(hintFor()); setTimeout(() => hint(""), 1600); }),
      chip("⌫ 지우기", st.op === "erase", () => { st.op = st.op === "erase" ? null : "erase"; buildOps(); hint(hintFor()); setTimeout(() => hint(""), 1600); }),
      el("button", { onclick: undo }, "↶ 되돌리기"),
      chip(`⊾ 직교 ${st.ortho ? "켬" : "끔"}`, st.ortho, () => { st.ortho = !st.ortho; saveOpts(); buildOps(); }),
      chip(`🧲 스냅 ${st.snap ? "켬" : "끔"}`, st.snap, () => { st.snap = !st.snap; saveOpts(); buildOps(); }));
  }
  function pickColor() {
    sheet((b) => {
      const cs = el("div", { class: "sk-colors-pick big" });
      for (const c of COLORS) cs.append(el("button", { class: "sw" + (c === st.color ? " on" : ""), style: `--c:${c}`,
        onclick: () => { st.color = c; saveOpts(); buildOps(); $("#modal").classList.remove("show"); } }));
      b.append(el("h3", {}, "스케치 색깔"), cs, el("p", { class: "small" }, "도면과 다른 부분을 색으로 나눠 그리세요 (예: 빨강 = 추가, 파랑 = 철거)."));
    });
  }
  $("#skTools").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return; st.tool = b.dataset.tool; st.op = null; saveOpts();
    for (const x of $("#skTools").children) x.classList.toggle("on", x === b);
    buildSub(); buildOps(); hint(hintFor()); setTimeout(() => hint(""), 1800);
  });
  for (const x of $("#skTools").children) x.classList.toggle("on", x.dataset.tool === st.tool);
  buildSub(); buildOps();

  function hidden() { try { return localStorage.getItem("skHide") === "1"; } catch (e) { return false; } }
  function setHidden(h) { try { localStorage.setItem("skHide", h ? "1" : "0"); } catch (e) { /* ignore */ } draw(); }
  function toggleHidden() { const h = !hidden(); setHidden(h); toast(h ? "스케치 숨김" : "스케치 표시"); return h; }
  function mode(on) {
    $("#sketchBar").classList.toggle("hidden", !on);
    if (on) { hint("한 손가락: 그리기 · 두 손가락: 이동/확대 · 꾹 눌러 끌면 복사"); setTimeout(() => hint(""), 2400); }
    st.cur = null; st.pend = null; if (!on) st.sel = null;
  }

  return { load, draw: drawAll, toggleHidden, setHidden, hidden, down, move, up, cancel, mode, undo, renderList, dimAt, calibrateWith, snapPoint,
    get list() { return st.list; }, get busy() { return !!(st.pend || st.cur); }, COLORS };
})();
window.SK = SK;
if (S.db && S.sheet) { SK.load(); draw(); }
