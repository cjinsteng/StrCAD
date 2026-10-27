/* 간이 부재 검토 — PC cad_analysis/check.py 와 같은 계산 (현장 판단 참고용).
   단위: mm, kN, kN·m, MPa (부재길이 L 은 m). */
"use strict";
const CK = (() => {
  const BAR_AREA = { 6: 31.67, 10: 71.33, 13: 126.7, 16: 198.6, 19: 286.5, 22: 387.1, 25: 506.7, 29: 642.4, 32: 794.2, 35: 956.6, 38: 1140.0, 41: 1340.0, 51: 2027.0 };
  const FY_PREFIX = { D: 400, SD: 400, HD: 400, SHD: 500, UHD: 600 };
  const FIX = { Pin: 0.0, SemiFix: 0.5, Fix: 1.0 };
  const SUPPORT_KO = { Pin: "핀", SemiFix: "반고정", Fix: "고정" };
  const ES = 200000.0, E_STEEL = 210000.0;
  const H_SECTIONS = {
    "H-150x150x7x10": [150, 150, 7, 10, 11], "H-194x150x6x9": [194, 150, 6, 9, 13], "H-200x100x5.5x8": [200, 100, 5.5, 8, 11],
    "H-200x200x8x12": [200, 200, 8, 12, 13], "H-244x175x7x11": [244, 175, 7, 11, 16], "H-250x125x6x9": [250, 125, 6, 9, 12],
    "H-250x250x9x14": [250, 250, 9, 14, 16], "H-294x200x8x12": [294, 200, 8, 12, 18], "H-300x150x6.5x9": [300, 150, 6.5, 9, 13],
    "H-300x300x10x15": [300, 300, 10, 15, 18], "H-340x250x9x14": [340, 250, 9, 14, 20], "H-350x175x7x11": [350, 175, 7, 11, 14],
    "H-350x350x12x19": [350, 350, 12, 19, 20], "H-390x300x10x16": [390, 300, 10, 16, 22], "H-400x200x8x13": [400, 200, 8, 13, 16],
    "H-400x400x13x21": [400, 400, 13, 21, 22], "H-440x300x11x18": [440, 300, 11, 18, 24], "H-450x200x9x14": [450, 200, 9, 14, 18],
    "H-488x300x11x18": [488, 300, 11, 18, 26], "H-500x200x10x16": [500, 200, 10, 16, 20], "H-582x300x12x17": [582, 300, 12, 17, 28],
    "H-588x300x12x20": [588, 300, 12, 20, 28], "H-600x200x11x17": [600, 200, 11, 17, 22], "H-700x300x13x24": [700, 300, 13, 24, 28],
    "H-800x300x14x26": [800, 300, 14, 26, 28], "H-900x300x16x28": [900, 300, 16, 28, 28],
  };
  const STEEL_GRADES = { SS275: 275, SM275: 275, SM355: 355, SHN275: 275, SHN355: 355, SM420: 420, SM460: 460 };
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  function parseBar(s) {
    const m = String(s || "").replace(/\s/g, "").toUpperCase().match(/^(?:(\d+)-)?([A-Z]*)(\d+)(?:@(\d+))?$/);
    if (!m) return null;
    return [m[1] ? +m[1] : null, m[2] || "D", +m[3], m[4] ? +m[4] : null];
  }
  const barArea = (d) => BAR_AREA[d] || Math.PI * d * d / 4;
  function asOf(s) {
    const p = parseBar(s);
    if (!p || !p[0]) return [0, 0, 0, 400];
    return [p[0] * barArea(p[2]), p[0], p[2], FY_PREFIX[p[1]] || 400];
  }
  function stirrupOf(s, legs = 2) {
    const p = parseBar(s);
    if (!p || !p[3]) return [0, 0, 0, 400];
    return [legs * barArea(p[2]), p[3], p[2], FY_PREFIX[p[1]] || 400];
  }
  function stressBlock(fck) {
    const tab = [[40, 0.0033, 1.00, 0.80], [50, 0.0032, 0.97, 0.80], [60, 0.0031, 0.95, 0.76], [70, 0.0030, 0.91, 0.74], [80, 0.0029, 0.87, 0.72], [90, 0.0028, 0.84, 0.70]];
    if (fck <= 40) return tab[0].slice(1);
    for (let i = 0; i + 1 < tab.length; i++) {
      const [f0, e0, n0, b0] = tab[i], [f1, e1, n1, b1] = tab[i + 1];
      if (fck <= f1) { const t = (fck - f0) / (f1 - f0); return [e0 + (e1 - e0) * t, n0 + (n1 - n0) * t, b0 + (b1 - b0) * t]; }
    }
    return tab[tab.length - 1].slice(1);
  }
  function phiFlex(et, fy) {
    const ey = fy / ES, etl = fy <= 400 ? 0.005 : 2.5 * ey;
    if (et >= etl) return 0.85;
    if (et <= ey) return 0.65;
    return 0.65 + 0.20 * (et - ey) / (etl - ey);
  }
  function beamForces(w, L, si = "Fix", sj = "Fix") {
    const r1 = FIX[si] ?? 1, r2 = FIX[sj] ?? 1, fem = w * L * L / 12, den = 4 - r1 * r2;
    const Mi = fem * 3 * r1 * (2 - r2) / den, Mj = fem * 3 * r2 * (2 - r1) / den;
    const Vi = w * L / 2 + (Mi - Mj) / L, Vj = w * L - Vi, x0 = w > 0 ? Vi / w : L / 2;
    return { Mi, Mj, Mpos: Vi * x0 - w * x0 * x0 / 2 - Mi, Vi, Vj, x0 };
  }
  const factoredW = (D, Lv) => Math.max(1.4 * D, 1.2 * D + 1.6 * Lv);

  function rcFlexure(b, h, bars, fck, cover = 40, sd = 10) {
    if (!Array.isArray(bars)) bars = [bars];
    const layers = []; let d1 = null, db1 = null;
    for (let i = 0; i < Math.min(2, bars.length); i++) {
      const [As, n, db, fy] = asOf(bars[i]);
      if (As <= 0) { if (i === 0) break; continue; }
      let d;
      if (i === 0) { d = h - cover - sd - db / 2; d1 = d; db1 = db; } else d = d1 - (db1 / 2 + Math.max(25, db1) + db / 2);
      layers.push({ As, n, db, fy, d });
    }
    if (!layers.length) return { As: 0, phiMn: 0, d: h - cover - sd - 11, eps_t: 0, phi: 0, fy: 400, n: 0, layers: [] };
    const [ecu, eta, b1] = stressBlock(fck), k = eta * 0.85 * fck * b * b1;
    const net = (c) => k * c - layers.reduce((s, L) => s + L.As * clamp(ES * ecu * (L.d - c) / c, -L.fy, L.fy), 0);
    let lo = 1e-3, hi = h;
    for (let i = 0; i < 80; i++) { const mid = (lo + hi) / 2; if (net(mid) > 0) hi = mid; else lo = mid; }
    const c = (lo + hi) / 2, a = b1 * c;
    let Mn = 0;
    for (const L of layers) { L.fs = clamp(ES * ecu * (L.d - c) / c, -L.fy, L.fy); Mn += L.As * L.fs * (L.d - a / 2); }
    Mn /= 1e6;
    const dt = layers[0].d, eps_t = ecu * (dt - c) / c, fy = layers[0].fy, phi = phiFlex(eps_t, fy);
    const As = layers.reduce((s, L) => s + L.As, 0), dc = layers.reduce((s, L) => s + L.As * L.d, 0) / As;
    return { As, d: dc, dt, a, c, eps_t, phi, Mn, phiMn: phi * Mn, fy, n: layers.reduce((s, L) => s + L.n, 0), db: layers[0].db, layers };
  }
  function rcShear(b, d, stirrup, fck, lam = 1, Nu = 0, Ag = null) {
    const sq = Math.min(Math.sqrt(fck), 8.4);
    let Vc = sq * lam * b * d / 6;
    if (Nu && Ag) Vc *= 1 + Nu * 1000 / (14 * Ag);
    let [Av, s, , fyt] = stirrupOf(stirrup); fyt = Math.min(fyt, 500);
    let Vs = s > 0 ? Av * fyt * d / s : 0;
    const Vsmax = 2 / 3 * sq * b * d, note = [];
    if (Vs > Vsmax) { note.push("Vs 상한(2/3√fck·bw·d) 적용"); Vs = Vsmax; }
    let smax = Math.min(d / 2, 600);
    if (Vs > sq * b * d / 3) smax /= 2;
    if (s && s > smax + 1e-6) note.push(`스터럽 간격 ${s.toFixed(0)} > 최대 ${smax.toFixed(0)}`);
    return { Vc: Vc / 1000, Vs: Vs / 1000, phiVn: 0.75 * (Vc + Vs) / 1000, s, smax, Av, note };
  }
  const ratio = (u, c) => (c > 0 ? u / c : Infinity);

  function rcBeamCheck(b, h, L, w, si, sj, rebar, fck = 24, cover = 40) {
    const F = beamForces(w, L, si, sj), lines = [];
    let sd = 10;
    for (const k of ["스터럽|I단", "스터럽|중앙", "스터럽|J단"]) { const p = parseBar(rebar[k] || ""); if (p) { sd = p[2]; break; } }
    const Mcr = 0.63 * Math.sqrt(fck) * b * h * h / 6 / 1e6;
    const flex = (label, Mu, bars) => {
      const r = rcFlexure(b, h, bars, fck, cover, sd);
      let ok = r.phiMn >= Mu - 1e-9, extra = "";
      if ((r.layers || []).length > 1) label = label.replace("근)", " 1+2단)");
      if (r.As > 0) {
        extra = `As=${r.As.toFixed(0)}mm², φ=${r.phi.toFixed(2)}, εt=${r.eps_t.toFixed(4)}`;
        if (r.layers.length > 1) extra += `, d=${r.d.toFixed(0)}(2단 d=${r.layers[1].d.toFixed(0)})`;
        const emin = r.fy <= 400 ? 0.004 : 2 * r.fy / ES;
        if (r.eps_t < emin) { extra += ` (최소허용변형률 ${emin.toFixed(4)} 미만)`; ok = false; }
        if (r.phiMn < 1.2 * Mcr && r.phiMn < 4 / 3 * Mu) extra += " · 최소철근 φMn<1.2Mcr";
      } else if (Mu > 0.5) extra = "철근 미입력";
      lines.push([label, Mu, r.phiMn, ratio(Mu, r.phiMn), ok, extra]);
      return r;
    };
    const two = (row, col) => [rebar[`${row}|${col}`] || "", rebar[`${row}2|${col}`] || ""];
    const ri = flex("휨 I단 −M (상부근)", F.Mi, two("상부근", "I단"));
    flex("휨 중앙 +M (하부근)", F.Mpos, two("하부근", "중앙"));
    const rj = flex("휨 J단 −M (상부근)", F.Mj, two("상부근", "J단"));
    const di = ri.d || (h - cover - sd - 11), dj = rj.d || di;
    for (const [label, Vu, key, d] of [["전단 I단", F.Vi, "스터럽|I단", di], ["전단 J단", F.Vj, "스터럽|J단", dj]]) {
      const st = rebar[key] || rebar["스터럽|중앙"] || "";
      const r = rcShear(b, d, st, fck);
      let ok = r.phiVn >= Vu - 1e-9, extra = `φVc=${(0.75 * r.Vc).toFixed(1)}, Vs=${r.Vs.toFixed(1)}`;
      if (!st) extra += " · 스터럽 미입력";
      if (Vu > 0.5 * 0.75 * r.Vc && !st) extra += " · 최소전단철근 필요";
      if (r.note.length) { extra += " · " + r.note.join(", "); if (r.note.some((n) => n.includes("간격"))) ok = false; }
      lines.push([label, Vu, r.phiVn, ratio(Vu, r.phiVn), ok, extra]);
    }
    return [lines, F];
  }

  function colLayouts(n) {
    const out = [];
    if (n < 4 || n % 2) return out;
    for (let nx = 2; nx <= n / 2; nx++) { const ny = (n + 4) / 2 - nx; if (ny >= 2) out.push([nx, ny]); }
    return out;
  }
  function parseLayout(s) { const m = String(s || "").match(/^\s*(\d+)\s*[xX×*]\s*(\d+)\s*$/); return m ? [+m[1], +m[2]] : null; }
  function defaultLayout(n, b = 1, h = 1) {
    const o = colLayouts(n); if (!o.length) return null;
    return o.reduce((best, x) => (Math.abs((x[0] - 1) / Math.max(x[1] - 1, 1) - b / Math.max(h, 1)) <
      Math.abs((best[0] - 1) / Math.max(best[1] - 1, 1) - b / Math.max(h, 1)) ? x : best));
  }
  function colBarPositions(b, h, n, lay, edge) {
    const [nx, ny] = lay;
    const xs = [...Array(nx)].map((_, i) => edge + (b - 2 * edge) * i / (nx - 1));
    const ys = [...Array(ny)].map((_, j) => edge + (h - 2 * edge) * j / (ny - 1));
    const pts = xs.map((x) => [x, ys[0]]).concat(xs.map((x) => [x, ys[ny - 1]]));
    for (const y of ys.slice(1, -1)) pts.push([xs[0], y], [xs[nx - 1], y]);
    return pts;
  }
  function rcColumnCheck(b, h, Pu, Mu, Vu, main, tie, fck = 24, cover = 40, layout = null) {
    const [Ast, n, db, fy] = asOf(main), tp = parseBar(tie), td = tp ? tp[2] : 10;
    const [ecu, eta, b1] = stressBlock(fck), Ag = b * h;
    const lay = layout && 2 * layout[0] + 2 * layout[1] - 4 === n ? layout : defaultLayout(n, b, h);
    const edge = cover + td + db / 2, ab = db ? barArea(db) : 0;
    let layers;
    if (lay) {
      const rows = new Map();
      for (const [, y] of colBarPositions(b, h, n, lay, edge)) { const k = Math.round(y * 1000) / 1000; rows.set(k, (rows.get(k) || 0) + 1); }
      layers = [...rows.entries()].map(([y, k]) => [y, k * ab]).sort((p, q) => p[0] - q[0]);
    } else layers = [[edge, Ast / 2], [h - edge, Ast / 2]];
    const d = Math.max(...layers.map((l) => l[0]));
    const P0 = (0.85 * eta * fck * (Ag - Ast) + fy * Ast) / 1000, phiPmax = 0.80 * 0.65 * P0;
    const point = (c) => {
      const a = Math.min(b1 * c, h), Cc = 0.85 * eta * fck * a * b;
      let Pn = Cc, Mn = Cc * (h / 2 - a / 2);
      for (const [y, As] of layers) {
        let fs = clamp(ES * ecu * (c - y) / c, -fy, fy);
        if (y < a && fs > 0) fs -= 0.85 * eta * fck;
        Pn += As * fs; Mn += As * fs * (h / 2 - y);
      }
      return [Pn / 1000, Mn / 1e6, phiFlex(ecu * (d - c) / c, fy)];
    };
    const pts = [];
    for (let i = 1; i < 400; i++) { const [Pn, Mn, phi] = point(h * 3 * i / 400); pts.push([Math.min(phi * Pn, phiPmax), phi * Mn]); }
    pts.push([phiPmax, 0]); pts.sort((p, q) => p[0] - q[0] || p[1] - q[1]);
    let phiMnAt = 0;
    for (let i = 0; i + 1 < pts.length; i++) {
      const [p0, m0] = pts[i], [p1, m1] = pts[i + 1];
      if (p0 <= Pu && Pu <= p1 && p1 > p0) phiMnAt = Math.max(phiMnAt, m0 + (m1 - m0) * (Pu - p0) / (p1 - p0));
    }
    const lines = [["축력 φPn,max", Pu, phiPmax, ratio(Pu, phiPmax), Pu <= phiPmax, `Ast=${Ast.toFixed(0)}mm² (ρ=${(Ast / Ag * 100).toFixed(2)}%)`]];
    const rho = Ast / Ag;
    let note = lay ? `배치 가로${lay[0]}×세로${lay[1]}` : "둘레 배치 불가 → 양면 반씩 가정";
    if (rho < 0.01 || rho > 0.08) note += ` · 철근비 ${(rho * 100).toFixed(2)}% (1~8% 범위 밖)`;
    if (lay) {
      const sx = (b - 2 * edge) / (lay[0] - 1) - db, sy = (h - 2 * edge) / (lay[1] - 1) - db, smin = Math.max(40, 1.5 * db);
      if (Math.min(sx, sy) < smin) note += ` · 주근 순간격 ${Math.min(sx, sy).toFixed(0)} < ${smin.toFixed(0)}mm`;
    }
    lines.push(["P-M 상관 (Pu에서 φMn)", Mu, phiMnAt, ratio(Mu, phiMnAt), Pu <= phiPmax && Mu <= phiMnAt, note]);
    if (Vu) {
      const r = rcShear(b, d, tie, fck, 1, Pu, Ag);
      lines.push(["전단 (띠철근)", Vu, r.phiVn, ratio(Vu, r.phiVn), r.phiVn >= Vu, `φVc=${(0.75 * r.Vc).toFixed(1)}`]);
    }
    return [lines, { phiPmax, layout: lay }];
  }

  function hProps(name) {
    const [H, B, tw, tf, r] = H_SECTIONS[name], hw = H - 2 * tf;
    const A = 2 * B * tf + hw * tw + (4 - Math.PI) * r * r;
    const Ix = (B * H ** 3 - (B - tw) * hw ** 3) / 12, Iy = (2 * tf * B ** 3 + hw * tw ** 3) / 12;
    const Zx = B * tf * (H - tf) + tw * hw * hw / 4, Sx = Ix / (H / 2), J = (2 * B * tf ** 3 + (H - tf) * tw ** 3) / 3, h0 = H - tf;
    return { H, B, tw, tf, A, Ix, Iy, Zx, Sx, J, Cw: Iy * h0 * h0 / 4, rx: Math.sqrt(Ix / A), ry: Math.sqrt(Iy / A), h0 };
  }
  function steelBeamCheck(sec, Fy, L, w, si, sj, Lb = null) {
    const p = hProps(sec), F = beamForces(w, L, si, sj), E = E_STEEL;
    const Mu = Math.max(F.Mi, F.Mj, F.Mpos), Vu = Math.max(F.Vi, F.Vj), Mp = Fy * p.Zx / 1e6;
    const note = [], lf = p.B / (2 * p.tf), lpf = 0.38 * Math.sqrt(E / Fy);
    if (lf > lpf) note.push(`플랜지 비조밀 (b/t=${lf.toFixed(1)} > ${lpf.toFixed(1)}) — 국부좌굴 미반영`);
    const Lbmm = (Lb || L) * 1000, Lp = 1.76 * p.ry * Math.sqrt(E / Fy);
    const rts = Math.sqrt(Math.sqrt(p.Iy * p.Cw) / p.Sx), Jc = p.J / (p.Sx * p.h0);
    const Lr = 1.95 * rts * E / (0.7 * Fy) * Math.sqrt(Jc + Math.sqrt(Jc ** 2 + 6.76 * (0.7 * Fy / E) ** 2));
    let Mn, lt;
    if (Lbmm <= Lp) { Mn = Mp; lt = "소성 (Lb≤Lp)"; }
    else if (Lbmm <= Lr) { Mn = Math.min(Mp, Mp - (Mp - 0.7 * Fy * p.Sx / 1e6) * (Lbmm - Lp) / (Lr - Lp)); lt = "비탄성 횡좌굴"; }
    else { const Fcr = Math.PI ** 2 * E / (Lbmm / rts) ** 2 * Math.sqrt(1 + 0.078 * Jc * (Lbmm / rts) ** 2); Mn = Math.min(Mp, Fcr * p.Sx / 1e6); lt = "탄성 횡좌굴"; }
    const phiMn = 0.9 * Mn, phiVn = 0.6 * Fy * p.H * p.tw / 1000;
    return [[["휨 (최대 |M|)", Mu, phiMn, Mu / phiMn, Mu <= phiMn, `${lt}, Lb=${(Lbmm / 1000).toFixed(2)}m, Lp=${(Lp / 1000).toFixed(2)}m, Lr=${(Lr / 1000).toFixed(2)}m, Cb=1` + (note.length ? " · " + note.join("; ") : "")],
      ["전단", Vu, phiVn, Vu / phiVn, Vu <= phiVn, "φv=1.0, 0.6Fy·d·tw"]], F];
  }
  function steelColumnCheck(sec, Fy, L, K, Pu, Mu) {
    const p = hProps(sec), E = E_STEEL, sl = K * L * 1000 / p.ry, Fe = Math.PI ** 2 * E / sl ** 2;
    const Fcr = sl <= 4.71 * Math.sqrt(E / Fy) ? 0.658 ** (Fy / Fe) * Fy : 0.877 * Fe;
    const phiPn = 0.9 * Fcr * p.A / 1000, phiMn = 0.9 * Fy * p.Zx / 1e6;
    const pr = ratio(Pu, phiPn), mr = ratio(Mu, phiMn), inter = pr >= 0.2 ? pr + 8 / 9 * mr : pr / 2 + mr;
    return [["축압축 φPn (약축)", Pu, phiPn, pr, pr <= 1, `KL/r=${sl.toFixed(0)}, Fcr=${Fcr.toFixed(0)}MPa`],
      ["휨 φMn (소성 가정)", Mu, phiMn, mr, mr <= 1, "횡좌굴 미반영"],
      ["축력+휨 상관", inter, 1.0, inter, inter <= 1.0, "Pr/Pc≥0.2: Pr/Pc+8/9·Mr/Mc"]];
  }
  function summarize(lines) {
    const groups = new Map();
    for (const l of lines) {
      const nm = l[0];
      const g = nm.startsWith("휨") ? "휨" : nm.startsWith("전단") ? "전단" : nm.includes("P-M") ? "P-M" : nm.includes("상관") ? "축력+휨" : nm.includes("축") ? "축력" : nm;
      groups.set(g, (groups.has(g) ? groups.get(g) : true) && l[4]);
    }
    const ok = [...groups.values()].every(Boolean);
    return [ok, [...groups.entries()].map(([g, v]) => `${g} ${v ? "O.K" : "N.G"}`).join(" · ")];
  }
  return { parseBar, asOf, beamForces, factoredW, rcFlexure, rcShear, rcBeamCheck, rcColumnCheck, colLayouts, parseLayout, defaultLayout,
    colBarPositions, steelBeamCheck, steelColumnCheck, summarize, H_SECTIONS, STEEL_GRADES, SUPPORT_KO, hProps };
})();
if (typeof module !== "undefined") module.exports = CK;
