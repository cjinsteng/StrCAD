// StrCAD 현장조사 — 현장 스케치 (도면과 다른 보·기둥·벽을 간단히 그림)
// 한 손가락: 그리기 · 두 손가락: 이동/확대. 도면 절대좌표로 저장 → PC 가져오기 시 같은 위치에 표시.
"use strict";

const SK = (() => {
  const COLORS = ["#e11d48", "#F28C28", "#eab308", "#16a34a", "#2563eb", "#7c3aed", "#111827", "#ec4899"];
  const TEXT_PRESETS = ["G1", "B1", "C1", "W1", "추가", "철거", "개구부", "도면과 다름"];
  const st = { list: [], tool: "beam", color: COLORS[0], cur: null, undo: [] };
  try { const c = localStorage.getItem("skColor"); if (COLORS.includes(c)) st.color = c; } catch (e) { /* ignore */ }

  // ------------------------------------------------------------------ storage
  // 화면·메모리 = 도면 상대좌표(members와 같음), 저장 = 도면 절대좌표(검측위치 rec.x/y와 같음 → PC에 그대로)
  const conv = (pts, f) => { const o = []; for (let i = 0; i + 1 < pts.length; i += 2) o.push(...f(pts[i], pts[i + 1])); return o; };
  function load() {
    st.list = []; st.undo = []; st.cur = null;
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
    persistSoon();
  }
  function add(sk) {
    sk.uid = sk.uid || uid(); sk.inspector = inspector(); sk.date = today();
    write(sk, false); st.list.push(sk); st.undo.push({ t: "add", sk }); draw();
  }
  function remove(sk, record = true) {
    write(sk, true); st.list = st.list.filter((x) => x.uid !== sk.uid);
    if (record) st.undo.push({ t: "del", sk }); draw();
  }
  function undo() {
    const a = st.undo.pop();
    if (!a) { toast("되돌릴 스케치가 없습니다"); return; }
    if (a.t === "add") remove(a.sk, false);
    else { write(a.sk, false); st.list.push(a.sk); draw(); }
  }

  // ------------------------------------------------------------------ geometry helpers
  const scr = (x, y) => w2s(x, y);
  function snapPoint(x, y, skipLast) {          // 근처 스케치 끝점 · 기둥 중심 (14px)
    const lim = 14 / S.view.s; let best = null, bd = lim;
    const tryP = (px, py) => { const d = Math.hypot(px - x, py - y); if (d < bd) { bd = d; best = [px, py]; } };
    for (const sk of st.list) if (sk.kind === "beam" || sk.kind === "wall" || sk.kind === "axis") { tryP(sk.pts[0], sk.pts[1]); tryP(sk.pts[2], sk.pts[3]); }
    else if (sk.kind === "column") tryP((sk.pts[0] + sk.pts[2]) / 2, (sk.pts[1] + sk.pts[3]) / 2);
    for (const m of S.sheet.members) if (m.k === "c") tryP(m.c[0], m.c[1]);
    else if (!skipLast) { const [p1, p2] = memEnds(m); tryP(...p1); tryP(...p2); }
    return best || [x, y];
  }
  function ortho(x0, y0, x, y) {                // 수평·수직 6° 이내면 맞춤
    const dx = x - x0, dy = y - y0, a = Math.abs(Math.atan2(dy, dx)) * 180 / Math.PI;
    if (a < 6 || a > 174) return [x, y0];
    if (Math.abs(a - 90) < 6) return [x0, y];
    return [x, y];
  }
  function distSeg2(px, py, x1, y1, x2, y2) {
    const vx = x2 - x1, vy = y2 - y1, L = vx * vx + vy * vy;
    const t = L ? Math.max(0, Math.min(1, ((px - x1) * vx + (py - y1) * vy) / L)) : 0;
    return Math.hypot(px - (x1 + t * vx), py - (y1 + t * vy));
  }
  function hit(x, y) {                          // 지우기용: 화면 16px 이내
    const lim = 16 / S.view.s;
    for (let i = st.list.length - 1; i >= 0; i--) {
      const sk = st.list[i], p = sk.pts;
      if (sk.kind === "column") {
        const [x0, x1] = [Math.min(p[0], p[2]), Math.max(p[0], p[2])], [y0, y1] = [Math.min(p[1], p[3]), Math.max(p[1], p[3])];
        if (x >= x0 - lim && x <= x1 + lim && y >= y0 - lim && y <= y1 + lim) return sk;
      } else if (sk.kind === "text") {
        if (Math.abs(x - p[0]) < (sk.text.length * 9 + 10) / S.view.s && Math.abs(y - p[1]) < lim) return sk;
      } else {
        for (let k = 0; k + 3 < p.length; k += 2) if (distSeg2(x, y, p[k], p[k + 1], p[k + 2], p[k + 3]) < lim) return sk;
      }
    }
    return null;
  }

  // ------------------------------------------------------------------ pointer (called from app.js)
  function down(sx, sy) {
    const [x, y] = s2w(sx, sy);
    if (st.tool === "erase" || st.tool === "text") { st.cur = { kind: st.tool, at: [x, y], sx, sy }; return; }
    const p = st.tool === "free" ? [x, y] : snapPoint(x, y);
    st.cur = { kind: st.tool, color: st.color, pts: [p[0], p[1], p[0], p[1]], sx, sy };
    draw();
  }
  function move(sx, sy) {
    const c = st.cur; if (!c || !c.pts) return;
    let [x, y] = s2w(sx, sy);
    if (c.kind === "free") { const n = c.pts.length; if (Math.hypot(x - c.pts[n - 2], y - c.pts[n - 1]) * S.view.s >= 3) c.pts.push(x, y); }
    else {
      if (c.kind === "beam" || c.kind === "wall" || c.kind === "axis") { [x, y] = snapPoint(x, y); if (x === s2w(sx, sy)[0] && y === s2w(sx, sy)[1]) [x, y] = ortho(c.pts[0], c.pts[1], x, y); }
      c.pts[2] = x; c.pts[3] = y;
    }
    draw();
  }
  function up(sx, sy, cancelled) {
    const c = st.cur; st.cur = null;
    if (!c || cancelled) { draw(); return; }
    const moved = Math.hypot(sx - c.sx, sy - c.sy);
    if (c.kind === "erase") { const h = hit(...c.at); if (h) { remove(h); toast("스케치 삭제 — ↶ 되돌리기 가능"); } return; }
    if (c.kind === "text") { askText(c.at); return; }
    if (c.kind === "column" && moved < 10) {        // 짧게 누르면 기본 500×500 기둥
      const [x, y] = snapPoint(...s2w(sx, sy), true), h = 250;
      c.pts = [x - h, y - h, x + h, y + h];
    } else if (c.kind === "free") { if (c.pts.length < 6) c.pts.push(c.pts[0] + 1 / S.view.s, c.pts[1]); }
    else if (moved < 10) { draw(); hint("끌어서 그리세요"); setTimeout(() => hint(""), 1400); return; }
    const sk = { kind: c.kind, color: c.color, pts: c.pts.map((v) => Math.round(v)) };
    if (c.kind === "free") sk.pts = sk.pts.slice(2);   // 시작점 중복 제거
    if (c.kind === "axis") { askAxis(sk); return; }
    add(sk);
  }
  function cancel() { st.cur = null; draw(); }

  // ---- X·Y 축(그리드) 버블: 선 방향으로 X/Y 판단, 다음 번호 자동 제안
  function nextAxisNames(sk) {
    const p = sk.pts, horiz = Math.abs(p[2] - p[0]) >= Math.abs(p[3] - p[1]);
    const used = st.list.filter((a) => a.kind === "axis").map((a) => a.text);
    const nums = used.map((t) => /^\d+$/.test(t) ? +t : 0), lets = used.filter((t) => /^[A-Z]$/.test(t));
    const xn = (pre) => { let n = 1; while (used.includes(pre + n)) n++; return pre + n; };
    const num = String(Math.max(0, ...nums) + 1);
    const let_ = lets.length ? String.fromCharCode(Math.max(...lets.map((t) => t.charCodeAt(0))) + 1) : "A";
    // 세로선(위아래) = X축 번호 1,2,3 / 가로선 = Y축 A,B,C (구조도면 관례)
    return horiz ? [xn("Y"), let_, xn("X"), num] : [xn("X"), num, xn("Y"), let_];
  }
  function askAxis(sk) {
    let inp;
    const sug = nextAxisNames(sk);
    sheet((b) => {
      inp = el("input", { type: "text", class: "sk-input", value: sug[0], placeholder: "예: X1, Y2, 1, A" });
      const done = () => { const t = inp.value.trim(); $("#modal").classList.remove("show");
        if (t) add(Object.assign(sk, { text: t })); else draw(); };
      inp.addEventListener("keydown", (e) => { if (e.key === "Enter") done(); });
      b.append(el("h3", {}, "축(그리드) 이름"), inp,
        el("div", { class: "sk-presets" }, sug.map((t) => el("button", { onclick: () => { inp.value = t; } }, t))),
        el("p", { class: "small" }, "양 끝에 버블(원)이 붙습니다. 현장 위치를 'X3–Y2 교차부'처럼 찾을 때 씁니다."),
        el("div", { class: "btns" }, el("button", { class: "b gray", onclick: () => { $("#modal").classList.remove("show"); draw(); } }, "취소"),
          el("span", { class: "sp" }), el("button", { class: "b ok", onclick: done }, "넣기")));
    });
    setTimeout(() => { if (inp) { inp.focus(); inp.select(); } }, 50);
  }

  function askText(at) {
    let inp;
    sheet((b) => {
      inp = el("input", { type: "text", class: "sk-input", placeholder: "예: G1 400×700, 기둥 추가, 철거됨" });
      const done = () => { const t = inp.value.trim(); $("#modal").classList.remove("show");
        if (t) add({ kind: "text", color: st.color, pts: [Math.round(at[0]), Math.round(at[1])], text: t }); };
      inp.addEventListener("keydown", (e) => { if (e.key === "Enter") done(); });
      b.append(el("h3", {}, "글자 넣기"), inp,
        el("div", { class: "sk-presets" }, TEXT_PRESETS.map((t) => el("button", { onclick: () => { inp.value = inp.value ? inp.value + " " + t : t; inp.focus(); } }, t))),
        el("div", { class: "btns" }, el("button", { class: "b gray", onclick: () => $("#modal").classList.remove("show") }, "취소"),
          el("span", { class: "sp" }), el("button", { class: "b ok", onclick: done }, "넣기")));
    });
    setTimeout(() => inp && inp.focus(), 50);
  }

  // ------------------------------------------------------------------ drawing
  function drawOne(sk, live) {
    const p = sk.pts, col = sk.color || COLORS[0];
    ctx.save(); ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineCap = "round"; ctx.lineJoin = "round";
    if (live) ctx.setLineDash([8, 5]);
    if (sk.kind === "beam" || sk.kind === "wall") {
      const a = scr(p[0], p[1]), b = scr(p[2], p[3]);
      ctx.lineWidth = sk.kind === "wall" ? 10 : 5; ctx.globalAlpha = sk.kind === "wall" ? 0.75 : 0.95;
      ctx.beginPath(); segTo(a, b); ctx.stroke();
      if (sk.kind === "beam") { ctx.globalAlpha = 1; ctx.setLineDash([]); for (const q of [a, b]) { ctx.beginPath(); ctx.arc(q[0], q[1], 3.5, 0, 7); ctx.fill(); } }
      if (live) { const L = Math.hypot(p[2] - p[0], p[3] - p[1]); ctx.globalAlpha = 1; ctx.setLineDash([]);
        ctx.font = "bold 12px sans-serif"; ctx.textAlign = "center"; ctx.lineWidth = 4; ctx.strokeStyle = "#fff";
        const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2 - 10; const t = `${(L / 1000).toFixed(2)} m`;
        ctx.strokeText(t, mx, my); ctx.fillText(t, mx, my); }
    } else if (sk.kind === "column") {
      const a = scr(p[0], p[1]), b = scr(p[2], p[3]);
      const x = Math.min(a[0], b[0]), y = Math.min(a[1], b[1]), w = Math.max(Math.abs(b[0] - a[0]), 4), h = Math.max(Math.abs(b[1] - a[1]), 4);
      ctx.globalAlpha = 0.35; ctx.fillRect(x, y, w, h); ctx.globalAlpha = 1; ctx.lineWidth = 2.5; ctx.strokeRect(x, y, w, h);
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + w, y + h); ctx.moveTo(x + w, y); ctx.lineTo(x, y + h); ctx.lineWidth = 1; ctx.stroke();
      if (live || w > 40) { const bw = Math.abs(p[2] - p[0]), bh = Math.abs(p[3] - p[1]); ctx.font = "bold 11px sans-serif"; ctx.textAlign = "center";
        ctx.lineWidth = 3; ctx.strokeStyle = "#fff"; const t = `${Math.round(bw)}×${Math.round(bh)}`; ctx.strokeText(t, x + w / 2, y - 4); ctx.fillText(t, x + w / 2, y - 4); }
    } else if (sk.kind === "free") {
      ctx.lineWidth = 3; ctx.beginPath();
      for (let i = 0; i < p.length; i += 2) { const q = scr(p[i], p[i + 1]); i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1]); }
      ctx.stroke();
    } else if (sk.kind === "axis") {
      const a = scr(p[0], p[1]), b = scr(p[2], p[3]), L = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
      const ux = (b[0] - a[0]) / L, uy = (b[1] - a[1]) / L, R = 13;
      ctx.lineWidth = 1.5; ctx.setLineDash([14, 4, 3, 4]);           // 일점쇄선
      ctx.beginPath(); segTo(a, b); ctx.stroke(); ctx.setLineDash([]);
      if (sk.text || live) for (const [q, sgn] of [[a, -1], [b, 1]]) {
        const cx = q[0] + ux * R * sgn, cy = q[1] + uy * R * sgn;
        if (cx < -40 || cy < -40 || cx > VW + 40 || cy > VH + 40) continue;
        ctx.fillStyle = "#fff"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(cx, cy, R, 0, 7); ctx.fill(); ctx.stroke();
        ctx.fillStyle = col; ctx.font = `bold ${(sk.text || "").length > 2 ? 10 : 12}px sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillText(sk.text || "?", cx, cy + 0.5);
      }
    } else if (sk.kind === "text") {
      const q = scr(p[0], p[1]); ctx.font = "bold 15px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.lineWidth = 4; ctx.strokeStyle = "#fff"; ctx.strokeText(sk.text, q[0], q[1]); ctx.fillText(sk.text, q[0], q[1]);
    }
    ctx.restore();
  }
  function drawAll() {
    if (!S.sheet || (hidden() && S.mode !== "sketch")) return;
    for (const sk of st.list) drawOne(sk, false);
    if (st.cur && st.cur.pts) drawOne(st.cur, true);
  }

  // ------------------------------------------------------------------ toolbar
  function buildColors() {
    const box = $("#skColors"); box.innerHTML = "";
    for (const c of COLORS) box.append(el("button", { class: "sw" + (c === st.color ? " on" : ""), style: `--c:${c}`, title: c,
      onclick: () => { st.color = c; try { localStorage.setItem("skColor", c); } catch (e) { /* ignore */ } buildColors(); } }));
  }
  $("#skTools").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return; st.tool = b.dataset.tool;
    for (const x of $("#skTools").children) x.classList.toggle("on", x === b);
    hint({ beam: "끌어서 보 그리기 (끝점·기둥에 붙음)", column: "끌어서 기둥 크기 · 짧게 누르면 500×500", wall: "끌어서 벽 그리기",
      free: "자유롭게 그리기", text: "글자 넣을 곳을 누르세요", erase: "지울 스케치를 누르세요",
      axis: "끌어서 축(그리드)선 그리기 → 이름(X1·Y1…) 입력, 양 끝에 버블" }[st.tool]); setTimeout(() => hint(""), 1800);
  });
  $("#skUndo").onclick = undo;
  buildColors();

  function hidden() { try { return localStorage.getItem("skHide") === "1"; } catch (e) { return false; } }
  function toggleHidden() { const h = !hidden(); try { localStorage.setItem("skHide", h ? "1" : "0"); } catch (e) { /* ignore */ }
    toast(h ? "스케치 숨김" : "스케치 표시"); draw(); return h; }
  function mode(on) {
    $("#sketchBar").classList.toggle("hidden", !on); $("#purposeSeg").classList.toggle("hidden", on);
    if (on) { hint("한 손가락: 그리기 · 두 손가락: 이동/확대"); setTimeout(() => hint(""), 2200); }
    st.cur = null;
  }

  return { load, draw: drawAll, toggleHidden, hidden, down, move, up, cancel, mode, undo, get list() { return st.list; }, COLORS };
})();
window.SK = SK;
if (S.db && S.sheet) { SK.load(); draw(); }
