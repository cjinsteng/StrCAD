/* 상세 부재입력 (INPUT) — 휴대폰/패드. PC detail_ui.py 와 같은 입력·저장 형식(rec.calc) */
"use strict";
const DT_MATS = [["RC", "철근콘크리트"], ["S", "철골"], ["SRC", "합성부재"]];
const DT_DIRS = [["V", "수직 (기둥)"], ["H", "수평 (보)"]];
const DT_SUPS = ["Pin", "SemiFix", "Fix"];
const DT_ROWLAB = { 상부근: "상 1단", 상부근2: "상 2단", 하부근: "하 1단", 하부근2: "하 2단", 스터럽: "스트럽", 주근: "주근", 띠철근: "띠철근" };
const num = (v, d = 0) => { const x = parseFloat(String(v ?? "").replace(/,/g, "")); return isFinite(x) ? x : d; };

function openDetail() {
  if (!beginEdit()) return;
  const e = S.edit, m = S.sheet.byId.get(e.member) || null;
  const calc = e.calc || {}, inp = calc.inputs || {};
  const kindOf = m ? m.k : ((e.name || "").startsWith("기둥") ? "c" : "b");
  const st = {
    mat: calc.mat || "RC", dir: calc.dir || (kindOf === "c" || kindOf === "w" ? "V" : "H"),
    sup: [inp.sup_i || "Fix", inp.sup_j || "Fix"], rebar: Object.assign({}, e.rebar || {}), result: calc.result || null,
    v: {
      b: e.size_b || (m ? (m.k === "c" ? m.b : m.w) || "" : ""), h: e.size_h || (m ? (m.k === "c" ? m.h : m.d) || "" : ""),
      L: e.length || (m && m.k !== "c" && m.L ? (m.L / 1000).toFixed(2) : inp.L || ""),
      D: inp.D ?? "20", Lv: inp.Lv ?? "10", fck: inp.fck ?? "24", cover: inp.cover ?? "40", Pu: inp.Pu ?? "", Mu: inp.Mu ?? "", Vu: inp.Vu ?? "",
      K: inp.K ?? "1.0", sec: inp.sec || "H-400x200x8x13", grade: inp.grade || "SS275", Lb: inp.Lb ?? "",
    },
  };
  const rowsCols = () => (st.dir === "V" ? [["주근", "띠철근"], ["단부", "중앙"]] : [["상부근", "상부근2", "하부근", "하부근2", "스터럽"], ["I단", "중앙", "J단"]]);
  const nMain = (c) => { const p = CK.parseBar(st.rebar[`주근|${c}`]); return p && p[0] ? p[0] : 0; };
  const layoutOf = (c) => {
    const n = nMain(c), lay = CK.parseLayout(st.rebar[`주근배치|${c}`]);
    if (lay && 2 * lay[0] + 2 * lay[1] - 4 === n) return lay;
    return n ? CK.defaultLayout(n, num(st.v.b, 1), num(st.v.h, 1)) : null;
  };

  let root;
  const close = sheet((b) => { root = b; b.classList.add("dt"); render(); });

  function render() {
    root.innerHTML = "";
    root.append(el("div", { class: "dt-head" }, el("b", {}, `INPUT — #${e.no} ${e.name || ""}`), el("button", { class: "icon", onclick: () => close() }, "✕")));
    const seg = (items, cur, set) => el("div", { class: "dt-seg" }, ...items.map(([k, t]) => el("button", { class: k === cur ? "on" : "", onclick: () => { set(k); st.result = null; render(); } }, t)));
    root.append(seg(DT_MATS, st.mat, (k) => (st.mat = k)), seg(DT_DIRS, st.dir, (k) => (st.dir = k)));
    if (st.mat === "SRC") root.append(el("div", { class: "dt-note" }, "합성부재: 철골 단면으로 보수적 검토 (슬래브 합성효과 미반영)"));
    // diagram
    const cvs = el("canvas", { class: "dt-cv" });
    root.append(cvs);
    requestAnimationFrame(() => drawDiagram(cvs));
    cvs.onclick = (ev) => {
      if (st.dir !== "H") return;
      const r = cvs.getBoundingClientRect(), x = ev.clientX - r.left;
      if (x < r.width * 0.2) st.sup[0] = DT_SUPS[(DT_SUPS.indexOf(st.sup[0]) + 1) % 3];
      else if (x > r.width * 0.8) st.sup[1] = DT_SUPS[(DT_SUPS.indexOf(st.sup[1]) + 1) % 3];
      else return;
      st.result = null; render();
    };
    // inputs
    const g = el("div", { class: "dt-inp" });
    const field = (lab, key, unit) => {
      const inpEl = el("input", { type: "text", inputmode: "decimal", value: st.v[key] ?? "" });
      inpEl.oninput = () => { st.v[key] = inpEl.value; drawDiagram(cvs); drawSections(); };
      g.append(el("label", {}, el("span", {}, lab), inpEl, el("small", {}, unit)));
    };
    const select = (lab, key, opts) => {
      const s = el("select", {}); for (const o of opts) { const op = el("option", { value: o }, o); if (o === String(st.v[key])) op.selected = true; s.append(op); }
      s.onchange = () => { st.v[key] = s.value; drawDiagram(cvs); };
      g.append(el("label", { class: "wide2" }, el("span", {}, lab), s));
    };
    if (st.mat === "RC") { field("B", "b", "mm 폭"); field("H", "h", "mm 춤"); }
    else { select("단면", "sec", Object.keys(CK.H_SECTIONS)); select("강종", "grade", Object.keys(CK.STEEL_GRADES)); }
    field("L", "L", "m 길이");
    if (st.dir === "H") { field("고정 D", "D", "kN/m"); field("활 L", "Lv", "kN/m"); if (st.mat !== "RC") field("Lb", "Lb", "m 횡지지"); }
    else { field("Pu", "Pu", "kN"); field("Mu", "Mu", "kN·m"); if (st.mat === "RC") field("Vu", "Vu", "kN"); else field("K", "K", "유효길이"); }
    if (st.mat === "RC") { select("fck", "fck", ["21", "24", "27", "30", "35", "40", "50"]); field("피복", "cover", "mm"); }
    root.append(g);
    // sections + rebar
    const secWrap = el("div", { class: "dt-secs" });
    root.append(secWrap);
    if (st.mat === "RC") {
      const [rows, cols] = rowsCols();
      for (const c of cols) {
        const card = el("div", { class: "dt-sec" }, el("div", { class: "dt-sec-h" }, c), el("canvas", { "data-col": c }));
        for (const r of rows) {
          const k = `${r}|${c}`;
          card.append(el("div", { class: "dt-bar" + (r.endsWith("2") ? " l2" : "") }, el("span", {}, DT_ROWLAB[r] || r),
            el("button", { onclick: () => barPick(`${DT_ROWLAB[r] || r} · ${c}`, st.rebar[k], /스터럽|띠철근/.test(r) ? "spacing" : "count", (v) => {
              if (v) st.rebar[k] = v; else delete st.rebar[k];
              if (r === "주근") { const n = nMain(c), lay = CK.parseLayout(st.rebar[`주근배치|${c}`]);
                if (!(lay && 2 * lay[0] + 2 * lay[1] - 4 === n)) { const d = n ? CK.defaultLayout(n, num(st.v.b, 1), num(st.v.h, 1)) : null;
                  if (d) st.rebar[`주근배치|${c}`] = `${d[0]}x${d[1]}`; else delete st.rebar[`주근배치|${c}`]; } }
              st.result = null; render(); }) }, st.rebar[k] || "선택")));
        }
        if (st.dir === "V") {
          const n = nMain(c), lay = layoutOf(c);
          const set = (dx) => { if (!lay) return; const nx = lay[0] + dx, ny = (n + 4) / 2 - nx; if (nx >= 2 && ny >= 2) { st.rebar[`주근배치|${c}`] = `${nx}x${ny}`; st.result = null; render(); } };
          card.append(el("div", { class: "dt-bar lay" }, el("span", {}, "배치"),
            el("div", { class: "dt-step" }, el("button", { onclick: () => set(-1) }, "−"), el("b", {}, lay ? `가로 ${lay[0]}` : "-"), el("button", { onclick: () => set(1) }, "+"),
              el("small", {}, !n ? "주근 먼저" : lay ? `× 세로 ${lay[1]} = ${n}개` : `${n}개 둘레배치 불가`))));
        }
        secWrap.append(card);
      }
      const [, cols2] = rowsCols();
      secWrap.append(el("div", { class: "dt-copy" }, el("button", { class: "b gray", onclick: () => {
        const a0 = cols2[0], z = cols2[cols2.length - 1];
        for (const r of rowsCols()[0].concat(["주근배치"])) { const v = st.rebar[`${r}|${a0}`]; if (v) st.rebar[`${r}|${z}`] = v; }
        st.result = null; render(); } }, `${cols2[0]} → ${cols2[cols2.length - 1]} 복사`)));
    } else secWrap.append(el("div", { class: "dt-note" }, "철골 단면은 위에서 규격을 선택합니다 (배근 입력 없음)."));
    requestAnimationFrame(drawSections);
    // buttons + result
    root.append(el("div", { class: "btns dt-btns" }, el("button", { class: "b gray", onclick: () => close() }, "닫기"), el("div", { class: "sp" }),
      el("button", { class: "b edit", onclick: () => { calcNow(); render(); } }, "계산"),
      el("button", { class: "b ok", onclick: save }, "입력")));
    const res = el("div", { class: "dt-res" });
    root.append(res);
    if (st.result) showResult(res, st.result);
  }

  function inputs() { return Object.assign({}, st.v, { sup_i: st.sup[0], sup_j: st.sup[1] }); }
  function run() {
    const i = inputs(), L = num(i.L);
    if (L <= 0) throw new Error("길이 L(m)을 입력하세요.");
    let lines, head;
    if (st.dir === "H") {
      const w = CK.factoredW(num(i.D), num(i.Lv)); let F;
      if (st.mat === "RC") {
        const b = num(i.b), h = num(i.h); if (b <= 0 || h <= 0) throw new Error("B, H를 입력하세요.");
        [lines, F] = CK.rcBeamCheck(b, h, L, w, st.sup[0], st.sup[1], st.rebar, num(i.fck, 24), num(i.cover, 40));
      } else [lines, F] = CK.steelBeamCheck(i.sec, CK.STEEL_GRADES[i.grade], L, w, st.sup[0], st.sup[1], num(i.Lb) || null);
      head = `wu ${w.toFixed(1)} kN/m · M(I) ${F.Mi.toFixed(1)} · M(+) ${F.Mpos.toFixed(1)} · M(J) ${F.Mj.toFixed(1)} kN·m · V ${F.Vi.toFixed(1)}/${F.Vj.toFixed(1)} kN`;
    } else {
      if (kindOf === "w") throw new Error("벽체는 상세 검토를 지원하지 않습니다.");
      const Pu = num(i.Pu), Mu = num(i.Mu);
      if (st.mat === "RC") {
        const col = st.rebar["주근|단부"] ? "단부" : "중앙", main = st.rebar[`주근|${col}`] || "";
        const tie = st.rebar["띠철근|단부"] || st.rebar["띠철근|중앙"] || "";
        if (!main) throw new Error("주근(예: 8-HD22)을 입력하세요.");
        [lines] = CK.rcColumnCheck(num(i.b), num(i.h), Pu, Mu, num(i.Vu), main, tie, num(i.fck, 24), num(i.cover, 40), layoutOf(col));
      } else lines = CK.steelColumnCheck(i.sec, CK.STEEL_GRADES[i.grade], L, num(i.K, 1), Pu, Mu);
      head = `Pu ${Pu.toFixed(1)} kN · Mu ${Mu.toFixed(1)} kN·m`;
    }
    const [ok, summ] = CK.summarize(lines);
    const rows = lines.map((l) => [l[0], +l[1].toFixed(1), +l[2].toFixed(1), isFinite(l[3]) ? +l[3].toFixed(2) : "∞", l[4] ? "O.K" : "N.G", l[5]]);
    return { ok, summary: summ, head, rows };
  }
  function calcNow() {
    try { st.result = run(); return st.result; } catch (err) { st.result = { ok: false, summary: "입력 확인: " + err.message, head: "", rows: [], error: true }; return null; }
  }
  function showResult(box, r) {
    box.append(el("div", { class: "dt-sum " + (r.ok ? "ok" : "ng") }, (r.error ? "" : r.ok ? "✔ " : "✘ ") + r.summary));
    if (r.head) box.append(el("div", { class: "dt-headl" }, r.head));
    for (const row of r.rows || []) {
      const ok = row[4] === "O.K", ratio = typeof row[3] === "number" ? row[3] : 9;
      box.append(el("div", { class: "dt-line " + (ok ? "ok" : "ng") },
        el("div", { class: "t" }, el("b", {}, row[0]), el("span", { class: "j" }, row[4])),
        el("div", { class: "bar" }, el("i", { style: `width:${Math.min(100, ratio * 100).toFixed(0)}%` })),
        el("div", { class: "n" }, `소요 ${row[1]} / 강도 ${row[2]}  (비 ${row[3]})`),
        row[5] ? el("div", { class: "x" }, row[5]) : ""));
    }
  }
  function save() {
    if (st.dir === "V") for (const c of rowsCols()[1]) { const lay = layoutOf(c); if (lay && nMain(c)) st.rebar[`주근배치|${c}`] = `${lay[0]}x${lay[1]}`; }
    const r = calcNow(), i = inputs();
    const keep = new Set(rowsCols()[0].concat(["주근배치"]));     // 현재 방향(보/기둥)의 배근만 저장
    e.rebar = Object.fromEntries(Object.entries(st.rebar).filter(([k, v]) => v && (st.mat !== "RC" || keep.has(k.split("|")[0]))));
    e.length = i.L;
    if (st.mat === "RC") { e.size_b = String(i.b); e.size_h = String(i.h); }
    else { const s = CK.H_SECTIONS[i.sec]; e.size_b = String(s[1]); e.size_h = String(s[0]); }
    e.calc = { mat: st.mat, dir: st.dir, inputs: i, result: r || st.result };
    close(); renderForm();
    toast(r ? `${r.ok ? "✔" : "✘"} ${r.summary} — 저장을 누르세요` : "입력 반영 — 저장을 누르세요", 3200);
  }

  // ---------------------------------------------------------------- drawing
  function prep(cv, hpx) {
    const w = cv.clientWidth || 300, dpr = window.devicePixelRatio || 1;
    cv.width = w * dpr; cv.height = hpx * dpr; cv.style.height = hpx + "px";
    const c = cv.getContext("2d"); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, w, hpx); return [c, w];
  }
  function drawDiagram(cv) {
    const [c, W] = prep(cv, 170), Y = 90;
    c.font = "12px sans-serif"; c.textAlign = "center"; c.lineWidth = 2; c.strokeStyle = "#111";
    if (st.dir === "H") {
      const x0 = W * 0.1, x1 = W * 0.9;
      c.strokeRect(x0 + 18, Y - 7, x1 - x0 - 36, 14);
      for (const [i, x] of [[0, x0], [1, x1]]) {
        c.fillStyle = "#fde68a"; c.fillRect(x - 18, Y - 26, 36, 52); c.strokeStyle = "#f59e0b"; c.strokeRect(x - 18, Y - 26, 36, 52); c.strokeStyle = "#111";
        const s = st.sup[i]; c.beginPath();
        if (s === "Pin") { c.moveTo(x, Y - 4); c.lineTo(x - 10, Y + 12); c.lineTo(x + 10, Y + 12); c.closePath(); }
        else if (s === "Fix") { c.moveTo(x, Y - 22); c.lineTo(x, Y + 22); for (let k = -20; k <= 20; k += 8) { c.moveTo(x - 5, Y + k); c.lineTo(x + 5, Y + k - 7); } }
        else { c.arc(x, Y, 8, 0, 7); }
        c.stroke(); c.fillStyle = "#111"; c.fillText(`${s} (${CK.SUPPORT_KO[s]})`, x, Y + 42);
      }
      c.fillStyle = "#fde68a"; c.fillRect(W / 2 - 95, 6, 190, 22); c.strokeStyle = "#f59e0b"; c.strokeRect(W / 2 - 95, 6, 190, 22);
      c.fillStyle = "#111"; c.fillText(`하중 D=${st.v.D} L=${st.v.Lv} kN/m`, W / 2, 21);
      c.strokeStyle = "#dc2626"; c.lineWidth = 1; c.beginPath(); c.moveTo(x0 + 18, 38); c.lineTo(x1 - 18, 38);
      for (let k = 0; k <= 8; k++) { const x = x0 + 22 + k * (x1 - x0 - 44) / 8; c.moveTo(x, 38); c.lineTo(x, Y - 10); c.moveTo(x - 3, Y - 15); c.lineTo(x, Y - 10); c.lineTo(x + 3, Y - 15); }
      c.stroke(); c.fillStyle = "#555"; c.fillText(`L = ${st.v.L || "?"} m  ·  양끝 지점을 누르면 Pin→SemiFix→Fix`, W / 2, 162);
    } else {
      const x = W * 0.3;
      c.strokeRect(x - 10, 36, 20, 90); c.beginPath(); c.moveTo(x - 30, 128); c.lineTo(x + 30, 128); c.stroke();
      c.fillStyle = "#fde68a"; c.fillRect(x - 80, 4, 160, 22); c.fillStyle = "#111"; c.fillText(`Pu=${st.v.Pu || "?"}  Mu=${st.v.Mu || "?"}`, x, 19);
      c.textAlign = "left"; c.fillText(`L = ${st.v.L || "?"} m`, x + 24, 84);
      c.fillText(st.mat === "RC" ? `b ${st.v.b || "?"} × h ${st.v.h || "?"} (h = 휨방향)` : `${st.v.sec} ${st.v.grade}`, W * 0.5, 60);
      if (kindOf === "w") { c.fillStyle = "#dc2626"; c.fillText("벽체는 검토 미지원 (기록만)", W * 0.5, 100); }
    }
  }
  function drawSections() {
    if (!root) return;
    for (const cv of root.querySelectorAll(".dt-sec canvas")) {
      const col = cv.getAttribute("data-col"), [c, W] = prep(cv, 110);
      const b = num(st.v.b, 400), h = num(st.v.h, 600); if (b <= 0 || h <= 0) continue;
      const k = Math.min((W - 20) / b, 96 / h), w = b * k, hh = h * k, x0 = (W - w) / 2, y0 = (110 - hh) / 2;
      c.fillStyle = "#f3f4f6"; c.fillRect(x0, y0, w, hh); c.strokeStyle = "#111"; c.lineWidth = 2; c.strokeRect(x0, y0, w, hh);
      const ed = Math.max(40 * k + 4, 6); c.fillStyle = "#111";
      const dot = (x, y) => { c.beginPath(); c.arc(x, y, 3.2, 0, 7); c.fill(); };
      const row = (n, y) => { for (let i = 0; i < n; i++) dot(x0 + ed + (w - 2 * ed) * (n > 1 ? i / (n - 1) : 0.5), y); };
      if (st.dir === "H") {
        for (const [r, y, sg] of [["상부근", y0 + ed, 1], ["하부근", y0 + hh - ed, -1]]) {
          const p1 = CK.parseBar(st.rebar[`${r}|${col}`]); if (p1 && p1[0]) row(Math.min(p1[0], 12), y);
          const p2 = CK.parseBar(st.rebar[`${r}2|${col}`]);
          if (p2 && p2[0] && p1 && p1[0]) row(Math.min(p2[0], 12), y + sg * Math.max((p1[2] / 2 + Math.max(25, p1[2]) + p2[2] / 2) * k, 7));
        }
      } else {
        const n = nMain(col), lay = layoutOf(col);
        if (lay) for (const [x, y] of CK.colBarPositions(w, hh, n, lay, ed)) dot(x0 + x, y0 + y);
      }
    }
  }
}
