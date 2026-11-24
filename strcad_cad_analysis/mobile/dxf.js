// StrCAD 현장조사 — 검측점 · 스케치를 DXF로 (AutoCAD R12 ASCII, 도면 절대좌표 mm)
//  레이어: 검측 SV-SEC / SV-CRACK-<종류> / SV-LOAD / SV-ETC (+ -TXT 내용 글자)
//          스케치 SK-<종류>-<색> (SK-BEAM-BLUE, SK-COLUMN-RED …), SK-AXIS-GAP, SK-SIGN(작성자)
//          바탕 BASE-GRID / BASE-LINE / BASE-WALL / BASE-GIRDER / BASE-BEAM / BASE-COLUMN / BASE-NAME / BASE-FRAME
//  한글은 \U+XXXX 로 넣음 (AutoCAD·ZWCAD 등에서 한글로 보임)
"use strict";

const DXF = (() => {
  // ACI 색 (가까운 색으로)
  const ACI = [[1, 255, 0, 0], [2, 255, 255, 0], [3, 0, 255, 0], [4, 0, 255, 255], [5, 0, 0, 255], [6, 255, 0, 255], [7, 255, 255, 255],
    [8, 128, 128, 128], [9, 192, 192, 192], [30, 255, 127, 0], [40, 255, 191, 0], [150, 0, 127, 255], [170, 0, 63, 255], [190, 127, 0, 255],
    [210, 255, 0, 255], [221, 255, 127, 191], [94, 0, 127, 0], [134, 0, 127, 127], [250, 51, 51, 51], [12, 189, 0, 0]];
  const COLOR_NAME = { "#e11d48": "RED", "#f28c28": "ORANGE", "#eab308": "YELLOW", "#16a34a": "GREEN", "#2563eb": "BLUE",
    "#7c3aed": "PURPLE", "#111827": "BLACK", "#ec4899": "PINK" };
  const COLOR_ACI = { RED: 1, ORANGE: 30, YELLOW: 2, GREEN: 3, BLUE: 5, PURPLE: 190, BLACK: 7, PINK: 221 };
  const SK_KIND = { beam: "BEAM", column: "COLUMN", wall: "WALL", axis: "AXIS", free: "FREE", dim: "DIM", text: "TEXT" };
  const SV_CODE = { "부재검측": "SEC", "균열검토": "CRACK", "하중조사": "LOAD", "기타": "ETC" };

  function aci(hex) {
    const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || ""); if (!m) return 7;
    const [r, g, b] = [1, 2, 3].map((i) => parseInt(m[i], 16));
    if (r < 40 && g < 40 && b < 60) return 7;
    let best = 7, bd = 1e9;
    for (const [n, R, G, B] of ACI) { const d = (R - r) ** 2 + (G - g) ** 2 + (B - b) ** 2; if (d < bd) { bd = d; best = n; } }
    return best;
  }
  const colorName = (hex) => COLOR_NAME[String(hex || "").toLowerCase()] || String(hex || "COLOR").replace("#", "C").toUpperCase();
  // 한글·기호 → \U+XXXX, 그림문자는 뺌
  function enc(t) {
    let o = "";
    for (const ch of String(t ?? "").replace(/[\r\n]+/g, " ")) {
      const c = ch.codePointAt(0);
      if (c < 128) o += ch; else if (c <= 0xffff && !(c >= 0x2600 && c <= 0x27bf) && !(c >= 0xfe00 && c <= 0xfe0f)) o += "\\U+" + c.toString(16).toUpperCase().padStart(4, "0");
    }
    return o.trim();
  }

  function Writer() {
    const ents = [], layers = new Map();
    const n = (v) => (Math.round(v * 1000) / 1000).toString();
    const layer = (name, color, lt = "CONTINUOUS") => { if (!layers.has(name)) layers.set(name, { color, lt }); return name; };
    const g = (...pairs) => { for (let i = 0; i < pairs.length; i += 2) ents.push(String(pairs[i]), String(pairs[i + 1])); };
    return {
      layer,
      line(L, a, b) { g(0, "LINE", 8, L, 10, n(a[0]), 20, n(a[1]), 30, 0, 11, n(b[0]), 21, n(b[1]), 31, 0); },
      circle(L, c, r) { g(0, "CIRCLE", 8, L, 10, n(c[0]), 20, n(c[1]), 30, 0, 40, n(r)); },
      text(L, p, h, t, rot = 0, align = "mc") {
        const s = enc(t); if (!s) return;
        const ha = { l: 0, c: 1, r: 2 }[align[1]] ?? 1, va = { b: 1, m: 2, t: 3 }[align[0]] ?? 2;
        g(0, "TEXT", 8, L, 10, n(p[0]), 20, n(p[1]), 30, 0, 40, n(h), 1, s, 50, n(rot), 72, ha, 11, n(p[0]), 21, n(p[1]), 31, 0, 73, va);
      },
      poly(L, pts, closed) {
        if (pts.length < 2) return;
        g(0, "POLYLINE", 8, L, 66, 1, 10, 0, 20, 0, 30, 0, 70, closed ? 1 : 0);
        for (const p of pts) g(0, "VERTEX", 8, L, 10, n(p[0]), 20, n(p[1]), 30, 0);
        g(0, "SEQEND", 8, L);
      },
      out(ext) {
        const h = [];
        const p = (...pairs) => { for (let i = 0; i < pairs.length; i += 2) h.push(String(pairs[i]), String(pairs[i + 1])); };
        p(0, "SECTION", 2, "HEADER", 9, "$ACADVER", 1, "AC1009", 9, "$DWGCODEPAGE", 3, "ANSI_949", 9, "$INSBASE", 10, 0, 20, 0, 30, 0,
          9, "$EXTMIN", 10, n(ext[0]), 20, n(ext[1]), 30, 0, 9, "$EXTMAX", 10, n(ext[2]), 20, n(ext[3]), 30, 0, 9, "$LTSCALE", 40, 1, 0, "ENDSEC");
        p(0, "SECTION", 2, "TABLES");
        p(0, "TABLE", 2, "LTYPE", 70, 3);
        p(0, "LTYPE", 2, "CONTINUOUS", 70, 0, 3, "Solid line", 72, 65, 73, 0, 40, 0);
        p(0, "LTYPE", 2, "CENTER", 70, 0, 3, "Center ____ _ ____ _", 72, 65, 73, 4, 40, 2000, 49, 1250, 49, -250, 49, 250, 49, -250);
        p(0, "LTYPE", 2, "DASHED", 70, 0, 3, "Dashed __ __ __", 72, 65, 73, 2, 40, 600, 49, 400, 49, -200);
        p(0, "ENDTAB");
        p(0, "TABLE", 2, "LAYER", 70, layers.size + 1);
        p(0, "LAYER", 2, "0", 70, 0, 62, 7, 6, "CONTINUOUS");
        for (const [name, v] of layers) p(0, "LAYER", 2, name, 70, 0, 62, v.color, 6, v.lt);
        p(0, "ENDTAB", 0, "ENDSEC");
        p(0, "SECTION", 2, "ENTITIES"); h.push(...ents); p(0, "ENDSEC", 0, "EOF");
        return h.join("\r\n") + "\r\n";
      },
    };
  }

  // 현재 도면 → DXF 문자열
  function build() {
    const sh = S.sheet, W = Writer();
    const x = sh.ext || {}, e = Array.isArray(x) ? x : [x.x0 ?? 0, x.y0 ?? 0, x.w ?? x.x1 ?? 1000, x.h ?? x.y1 ?? 1000];
    const span = Math.max(Math.abs((e[2] ?? 1) - (e[0] ?? 0)), Math.abs((e[3] ?? 1) - (e[1] ?? 0)), 1000);
    const H = Math.min(500, Math.max(120, span / 200));               // 글자 높이 (mm) — 도면 크기에 맞춤
    const ab = (x, y) => A(x, y);
    // ---- 바탕 도면
    const Lg = W.layer("BASE-GRID", 8, "CENTER"), Lb = W.layer("BASE-LINE", 9);
    for (let i = 0; i + 3 < sh.grid.length; i += 4) W.line(Lg, ab(sh.grid[i], sh.grid[i + 1]), ab(sh.grid[i + 2], sh.grid[i + 3]));
    for (let i = 0; i + 3 < sh.bg.length; i += 4) W.line(Lb, ab(sh.bg[i], sh.bg[i + 1]), ab(sh.bg[i + 2], sh.bg[i + 3]));
    const KL = { w: ["BASE-WALL", 8], g: ["BASE-GIRDER", 4], b: ["BASE-BEAM", 3], c: ["BASE-COLUMN", 1] };
    for (const m of sh.members) {
      const [nm, col] = KL[m.k] || ["BASE-ETC", 8]; const L = W.layer(nm, col);
      if (m.k === "c") {
        if (m.p && m.p.length >= 6) { const pts = []; for (let i = 0; i + 1 < m.p.length; i += 2) pts.push(ab(m.p[i], m.p[i + 1])); W.poly(L, pts, true); }
        else W.circle(L, ab(...m.c), Math.max(100, (m.b || 400) / 2));
      } else if (m.l && m.l.length >= 4) { const pts = []; for (let i = 0; i + 1 < m.l.length; i += 2) pts.push(ab(m.l[i], m.l[i + 1])); W.poly(L, pts, false); }
      if (m.n) { const Ln = W.layer("BASE-NAME", 8); const c = m.k === "c" ? m.c : [(m.l[0] + m.l[m.l.length - 2]) / 2, (m.l[1] + m.l[m.l.length - 1]) / 2];
        W.text(Ln, ab(c[0], c[1] + H * 0.7), H * 0.6, m.n); }
    }
    if (sh.imgRect || sh.extKind) {                  // 사진·빈 도면: 테두리 + 그림 위치 안내
      const Lf = W.layer("BASE-FRAME", 8), r = sh.imgRect || e;
      W.poly(Lf, [ab(r[0], r[1]), ab(r[2], r[1]), ab(r[2], r[3]), ab(r[0], r[3])], true);
      if (sh.imgRect) W.text(Lf, ab(r[0], r[3] + H * 1.5), H * 0.6,
        `배경 그림: 같은 폴더의 그림 파일을 IMAGE로 삽입 — 삽입점 (${Math.round(A(r[0], r[1])[0])}, ${Math.round(A(r[0], r[1])[1])}), 폭 ${Math.round(r[2] - r[0])} mm`, 0, "bl");
    }
    // ---- 검측점 (용도별 레이어, 균열은 종류별)
    const custom = {}; let cu = 0;
    const svLayer = (rec) => {
      const P = S.purposes[rec.purpose] || {};
      let code = SV_CODE[rec.purpose] || (custom[rec.purpose] || (custom[rec.purpose] = "U" + (++cu)));
      if (P.crack && (rec.fields || {}).ctype && CRACK_BY[rec.fields.ctype]) code += "-" + CRACK_BY[rec.fields.ctype].code;
      const c = aci(purposeColor(rec.purpose));
      return [W.layer("SV-" + code, c), W.layer("SV-" + code + "-TXT", c)];
    };
    for (const rec of S.recs) {
      if (!isPlaced(rec)) continue;
      const g = geom(rec), [L, Lt] = svLayer(rec), Rb = H * 1.1;
      if (g.type === "area") {
        if (g.poly) { const pts = []; for (let i = 0; i + 1 < g.poly.length; i += 2) pts.push(ab(g.poly[i], g.poly[i + 1])); W.poly(L, pts, true); }
        else W.poly(L, [ab(g.r[0], g.r[1]), ab(g.r[2], g.r[1]), ab(g.r[2], g.r[3]), ab(g.r[0], g.r[3])], true);
        const fl = rec.fields || {}, lines = [rec.name, fl.use, [fl.fin, fl.fin_t ? fl.fin_t + "mm" : ""].filter(Boolean).join(" "), fl.ceil,
          `${areaOf(rec).toFixed(1)} m²`, loadText(fl)].filter(Boolean);
        const c = ab(...g.p);
        lines.forEach((t, i) => W.text(Lt, [c[0], c[1] + (lines.length / 2 - i - 0.5) * H * 1.4], H * 0.8, t));
      } else if (g.type === "span") {
        W.line(L, ab(...g.a), ab(...g.b));
        for (const p of [g.a, g.b]) W.circle(L, ab(...p), H * 0.25);
      } else {
        const p = ab(...g.p); W.circle(L, p, H * 0.3); W.line(L, [p[0] - H * 0.5, p[1]], [p[0] + H * 0.5, p[1]]); W.line(L, [p[0], p[1] - H * 0.5], [p[0], p[1] + H * 0.5]);
      }
      const an = ab(...anchor(rec)), bb = ab(...bubble(rec)), d = Math.hypot(bb[0] - an[0], bb[1] - an[1]);
      if (d > Rb) W.line(L, an, [bb[0] - (bb[0] - an[0]) / d * Rb, bb[1] - (bb[1] - an[1]) / d * Rb]);
      W.circle(L, bb, Rb);
      const label = String(rec.label || rec.no);
      W.text(L, bb, label.length > 2 ? H * 0.65 : H * 0.85, label);
      const sm = summary(rec).replace(/📍미배치/g, "");
      if (sm) W.text(Lt, [bb[0] + Rb * 1.3, bb[1]], H * 0.6, sm, 0, "ml");
      if (rec.name && g.type !== "area") W.text(Lt, [bb[0] + Rb * 1.3, bb[1] + H * 0.9], H * 0.6, rec.name, 0, "ml");
    }
    // ---- 스케치 (종류·색별 레이어)
    if (window.SK) {
      const Ls = W.layer("SK-SIGN", 8);
      for (const sk of SK.list) {
        const kind = SK_KIND[sk.kind] || "ETC", cn = colorName(sk.color), col = COLOR_ACI[cn] || aci(sk.color);
        const L = W.layer(`SK-${kind}-${cn}`, col, sk.kind === "axis" ? "CENTER" : "CONTINUOUS");
        const p = sk.pts, P0 = ab(p[0], p[1]), P1 = p.length >= 4 ? ab(p[2], p[3]) : P0;
        const ang = Math.atan2(P1[1] - P0[1], P1[0] - P0[0]) * 180 / Math.PI, up = ang > 90 || ang < -90 ? ang + 180 : ang;
        const mid = [(P0[0] + P1[0]) / 2, (P0[1] + P1[1]) / 2], Lx = Math.hypot(P1[0] - P0[0], P1[1] - P0[1]) || 1;
        const nx = -(P1[1] - P0[1]) / Lx, ny = (P1[0] - P0[0]) / Lx;
        if (sk.kind === "beam" || sk.kind === "wall") {
          const t = sk.kind === "wall" ? (sk.t || 200) : (sk.w || 400);
          const q = [[P0[0] + nx * t / 2, P0[1] + ny * t / 2], [P1[0] + nx * t / 2, P1[1] + ny * t / 2], [P1[0] - nx * t / 2, P1[1] - ny * t / 2], [P0[0] - nx * t / 2, P0[1] - ny * t / 2]];
          if (sk.kind === "wall") W.poly(L, q, true);
          else if (sk.dbl) { W.line(L, q[0], q[1]); W.line(L, q[3], q[2]); W.line(W.layer(`SK-BEAM-${cn}-CL`, col, "DASHED"), P0, P1); }
          else W.line(L, P0, P1);
          if (sk.name) W.text(L, [mid[0] + nx * (t / 2 + H * 0.7), mid[1] + ny * (t / 2 + H * 0.7)], H * 0.8, sk.name, up);
        } else if (sk.kind === "column") {
          const [x0, y0] = P0, [x1, y1] = P1;
          W.poly(L, [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], true);
          W.text(L, [(x0 + x1) / 2, Math.max(y0, y1) + H * 0.7], H * 0.7, (sk.name ? sk.name + " " : "") + `${Math.round(sk.b || Math.abs(x1 - x0))}x${Math.round(sk.h || Math.abs(y1 - y0))}`);
        } else if (sk.kind === "axis") {
          const ux = (P1[0] - P0[0]) / Lx, uy = (P1[1] - P0[1]) / Lx, R = H * 1.2;
          W.line(L, P0, P1);
          const Lb2 = W.layer(`SK-AXIS-${cn}-BUBBLE`, col);
          for (const [v, sgn] of [[P0, -1], [P1, 1]]) { const c = [v[0] + ux * R * sgn, v[1] + uy * R * sgn]; W.circle(Lb2, c, R); W.text(Lb2, c, H, sk.text || ""); }
        } else if (sk.kind === "free") {
          const pts = []; for (let i = 0; i + 1 < p.length; i += 2) pts.push(ab(p[i], p[i + 1])); W.poly(L, pts, false);
        } else if (sk.kind === "dim") {
          W.line(L, P0, P1);
          const ux = (P1[0] - P0[0]) / Lx, uy = (P1[1] - P0[1]) / Lx, k = H * 0.4;
          for (const v of [P0, P1]) { W.line(L, [v[0] - (ux + nx) * k, v[1] - (uy + ny) * k], [v[0] + (ux + nx) * k, v[1] + (uy + ny) * k]);
            W.line(L, [v[0] + nx * k * 1.5, v[1] + ny * k * 1.5], [v[0] - nx * k * 1.5, v[1] - ny * k * 1.5]); }
          const sg = up === ang ? 1 : -1;
          W.text(L, [mid[0] + nx * H * 0.7 * sg, mid[1] + ny * H * 0.7 * sg], H * 0.8, Math.round(sk.val || Lx).toLocaleString("en-US"), up);
        } else if (sk.kind === "text") {
          W.text(L, P0, H, sk.text || "");
        }
        if (sk.inspector && sk.kind !== "axis" && sk.kind !== "dim") {           // 작성자
          const at = sk.kind === "column" ? [(P0[0] + P1[0]) / 2, Math.min(P0[1], P1[1]) - H * 0.6] : sk.kind === "text" ? [P0[0], P0[1] - H * 1.0] : ab(p[p.length - 2], p[p.length - 1]);
          W.text(Ls, [at[0], at[1] - (sk.kind === "column" || sk.kind === "text" ? 0 : H * 0.6)], H * 0.45, `(${sk.inspector})`);
        }
      }
      const Lgap = W.layer("SK-AXIS-GAP", 8);
      for (const { p1, p2, d } of SK.axisGaps(H * 3.2)) {
        const a = ab(...p1), b = ab(...p2); W.line(Lgap, a, b);
        for (const v of [a, b]) W.circle(Lgap, v, H * 0.12);
        const ang = Math.atan2(b[1] - a[1], b[0] - a[0]) * 180 / Math.PI, up = ang > 90 || ang < -90 ? ang + 180 : ang;
        const L2 = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, nx2 = -(b[1] - a[1]) / L2, ny2 = (b[0] - a[0]) / L2, sg = up === ang ? 1 : -1;
        W.text(Lgap, [(a[0] + b[0]) / 2 + nx2 * H * 0.6 * sg, (a[1] + b[1]) / 2 + ny2 * H * 0.6 * sg], H * 0.7, Math.round(d).toLocaleString("en-US"), up);
      }
    }
    const lo = A(e[0] ?? 0, e[1] ?? 0), hi = A(e[2] ?? 1, e[3] ?? 1);
    return W.out([lo[0], lo[1], hi[0], hi[1]]);
  }

  async function saveOne(text, fname) {
    const bytes = new TextEncoder().encode(text);
    if (NATIVE) { const r = await saveToDevice(`StrCAD/${fname}`, bytes); return r; }
    const a = el("a", { href: URL.createObjectURL(new Blob([bytes], { type: "application/dxf" })), download: fname });
    document.body.append(a); a.click(); setTimeout(() => a.remove(), 1000); return null;
  }
  async function saveImage(fname) {
    try {
      const row = q("SELECT image, mime FROM sheet_ext WHERE sheet_id=?", [S.sheet.id])[0];
      if (!row || !row.image) return null;
      const ext = /png/.test(row.mime || "") ? "png" : "jpg", nm = fname.replace(/\.dxf$/i, "") + "_배경." + ext;
      if (NATIVE) await saveToDevice(`StrCAD/${nm}`, row.image);
      else { const a = el("a", { href: URL.createObjectURL(new Blob([row.image], { type: row.mime || "image/jpeg" })), download: nm }); document.body.append(a); a.click(); setTimeout(() => a.remove(), 1000); }
      return nm;
    } catch (e) { return null; }
  }

  async function exportDialog() {
    if (!S.db || !S.sheet) return;
    if (!guardEdit()) return;
    sheet((b) => {
      const go = async (all) => {
        $("#modal").classList.remove("show");
        const keep = S.sheetIdx, view = { ...S.view }, files = [];
        try {
          await withBusy("DXF 만드는 중…", async (bz) => {
            const idxs = all ? S.sheets.map((_, i) => i) : [S.sheetIdx];
            let last = null;
            for (const i of idxs) {
              if (i !== S.sheetIdx) loadSheet(i);
              bz.set("DXF 만드는 중…", `${S.sheet.name} (${files.length + 1}/${idxs.length})`); await paint();
              const fname = `${safeName(S.meta.project || "현장조사")}_${safeName(S.sheet.name)}_검측스케치_${today()}.dxf`;
              last = await saveOne(build(), fname); files.push(fname);
              const img = await saveImage(fname); if (img) files.push(img);
            }
            if (S.sheetIdx !== keep) { loadSheet(keep); S.view = view; draw(); }
            if (last) savedSheet(last, files[0], files.length > 1 ? `파일 ${files.length}개: ${files.join(", ")}` : "");
            else toast(`DXF ${files.filter((f) => f.endsWith(".dxf")).length}개 저장`);
          });
        } catch (e) { alert("DXF 저장 실패: " + (e.message || e)); }
      };
      b.append(el("h3", {}, "📐 DXF로 내보내기"),
        el("p", { class: "small" }, "검측점은 용도별(SV-SEC · SV-CRACK-종류 · SV-LOAD · SV-ETC, 내용 글자는 -TXT), 스케치는 종류·색깔별(SK-BEAM-BLUE · SK-COLUMN-RED …) 레이어로 나눠 저장합니다. 원래 도면 좌표(mm) 그대로라 원본 DXF에 겹쳐 쓸 수 있습니다. 사진 도면은 배경 그림 파일도 함께 저장합니다."),
        el("button", { class: "bigbtn", onclick: () => go(false) }, `지금 도면 (${S.sheet.name})`),
        S.sheets.length > 1 ? el("button", { class: "bigbtn ghost", onclick: () => go(true) }, `모든 도면 ${S.sheets.length}장 (도면마다 파일)`) : "",
        el("div", { class: "btns" }, el("span", { class: "sp" }), el("button", { class: "b gray", onclick: () => $("#modal").classList.remove("show") }, "취소")));
    });
  }

  $("#miDxf").onclick = () => { $("#menu").classList.remove("show"); exportDialog(); };
  return { build, exportDialog, enc };
})();
window.DXF = DXF;
