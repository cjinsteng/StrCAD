// StrCAD 현장조사 — DXF 없이 조사 시작 (빈 도면 · 사진/이미지 배경), 도면 추가, 축척 맞추기
"use strict";

const NS = (() => {
  const SCHEMA = `
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sheets (id INTEGER PRIMARY KEY, analysis_id INTEGER, seq INTEGER, name TEXT,
    origin TEXT, extents TEXT, members TEXT, background TEXT, grid TEXT);
CREATE TABLE IF NOT EXISTS surveys (uid TEXT PRIMARY KEY, sheet_id INTEGER, updated TEXT, deleted INTEGER DEFAULT 0, rec TEXT);
CREATE TABLE IF NOT EXISTS photos (uid TEXT PRIMARY KEY, survey_uid TEXT, name TEXT, mime TEXT, data BLOB, created TEXT);
CREATE TABLE IF NOT EXISTS sketches (uid TEXT PRIMARY KEY, sheet_id INTEGER, updated TEXT, deleted INTEGER DEFAULT 0, data TEXT);
CREATE TABLE IF NOT EXISTS sheet_ext (sheet_id INTEGER PRIMARY KEY, suid TEXT, kind TEXT, image BLOB, mime TEXT,
    iw INTEGER, ih INTEGER, rect TEXT);`;

  function gridFlat(w, h) {               // 연한 격자 1 m (넓으면 5 m) + 테두리, 도면 상대좌표 [x1,y1,x2,y2,...]
    const step = Math.max(w, h) <= 60000 ? 1000 : 5000, out = [];
    for (let x = 0; x <= w + 1; x += step) out.push(x, 0, x, h);
    for (let y = 0; y <= h + 1; y += step) out.push(0, y, w, y);
    return out.map((v) => Math.round(v));
  }
  function imageSize(blob) {
    return new Promise((res, rej) => { const u = URL.createObjectURL(blob), im = new Image();
      im.onload = () => { res([im.naturalWidth, im.naturalHeight]); URL.revokeObjectURL(u); };
      im.onerror = () => { URL.revokeObjectURL(u); rej(new Error("이미지를 읽을 수 없습니다")); }; im.src = u; });
  }

  // db: sql.js Database. opts: {name, kind:'blank'|'photo', w, h (m), file, widthM}
  async function addSheet(db, opts) {
    const qq = (sql, p = []) => { const st = db.prepare(sql); st.bind(p); const o = []; while (st.step()) o.push(st.getAsObject()); st.free(); return o; };
    const id = (qq("SELECT MAX(id) AS m FROM sheets")[0].m || 0) + 1;
    const seq = (qq("SELECT MAX(seq) AS m FROM sheets")[0].m || 0) + 1;
    const suid = "sh_" + uid().slice(0, 16);
    let w, h, img = null, iw = 0, ih = 0, bg = [];
    if (opts.kind === "blank") {
      w = Math.round(opts.w * 1000); h = Math.round(opts.h * 1000); bg = gridFlat(w, h);
    } else {
      const blob = await shrinkImage(opts.file, 2400, 0.85);
      [iw, ih] = await imageSize(blob);
      w = Math.round((opts.widthM || 40) * 1000); h = Math.round(w * ih / iw);
      img = new Uint8Array(await blob.arrayBuffer());
    }
    db.run("INSERT INTO sheets (id, analysis_id, seq, name, origin, extents, members, background, grid) VALUES (?,?,?,?,?,?,?,?,?)",
      [id, null, seq, opts.name, JSON.stringify({ ox: 0, oy: 0 }), JSON.stringify({ w, h }), "[]", JSON.stringify(bg), "[]"]);
    db.run("INSERT INTO sheet_ext (sheet_id, suid, kind, image, mime, iw, ih, rect) VALUES (?,?,?,?,?,?,?,?)",
      [id, suid, opts.kind, img, img ? "image/jpeg" : null, iw, ih, JSON.stringify([0, 0, w, h])]);
    return id;
  }

  async function createProject(project, sheetOpts) {
    await loadSQL();
    const db = new S.SQL.Database();
    db.exec(SCHEMA);
    const meta = { format: FORMAT, version: "1", project, exported: nowIso(), app: "StrCAD 현장조사(휴대폰에서 만듦)",
      purposes: "{}", picklists: "{}" };
    for (const [k, v] of Object.entries(meta)) db.run("INSERT INTO meta (key, value) VALUES (?,?)", [k, v]);
    await addSheet(db, sheetOpts);
    const bytes = db.export(); db.close();
    await openBytes(bytes, `${safeName(project)}_현장조사.strsv`);
  }

  // ---------------------------------------------------------------- 사진 원근 보정 (네 모서리 → 반듯한 직사각형)
  function solve8(A, b) {                    // 가우스 소거
    const n = 8;
    for (let i = 0; i < n; i++) {
      let mx = i; for (let r = i + 1; r < n; r++) if (Math.abs(A[r][i]) > Math.abs(A[mx][i])) mx = r;
      [A[i], A[mx]] = [A[mx], A[i]]; [b[i], b[mx]] = [b[mx], b[i]];
      for (let r = i + 1; r < n; r++) { const f = A[r][i] / A[i][i]; for (let c = i; c < n; c++) A[r][c] -= f * A[i][c]; b[r] -= f * b[i]; }
    }
    const x = new Array(n).fill(0);
    for (let i = n - 1; i >= 0; i--) { let v = b[i]; for (let c = i + 1; c < n; c++) v -= A[i][c] * x[c]; x[i] = v / A[i][i]; }
    return x;
  }
  function homography(src, dst) {           // dst(u,v) → src(x,y)
    const A = [], b = [];
    for (let i = 0; i < 4; i++) {
      const [u, v] = dst[i], [x, y] = src[i];
      A.push([u, v, 1, 0, 0, 0, -u * x, -v * x]); b.push(x);
      A.push([0, 0, 0, u, v, 1, -u * y, -v * y]); b.push(y);
    }
    return solve8(A, b);
  }
  function loadImg(blob) { return new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = URL.createObjectURL(blob); }); }
  async function cornerEditor(file) {
    const small = await shrinkImage(file, 2400, 0.92);
    const im = await loadImg(small), iw = im.naturalWidth, ih = im.naturalHeight;
    return new Promise((resolve) => {
      const ov = el("div", { class: "ce-ov" });
      const cv2 = el("canvas", { class: "ce-cv" });
      const done = (v) => { ov.remove(); resolve(v); };
      const bar = el("div", { class: "ce-bar" },
        el("span", {}, "주황 점 네 개를 용지(도면) 모서리로 끌어 놓으세요"),
        el("button", { class: "b gray", onclick: () => done(null) }, "취소"),
        el("button", { class: "b ok", onclick: async () => { const v = await withBusy("사진 펴는 중…", () => warp(), "잠시만 기다려 주세요"); done(v); } }, "펴기"));
      ov.append(cv2, bar); document.body.append(ov);
      const g = cv2.getContext("2d");
      let k = 1, ox = 0, oy = 0;
      const pts = [[iw * 0.05, ih * 0.05], [iw * 0.95, ih * 0.05], [iw * 0.95, ih * 0.95], [iw * 0.05, ih * 0.95]];
      function layout() {
        const r = cv2.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
        cv2.width = r.width * dpr; cv2.height = r.height * dpr; g.setTransform(dpr, 0, 0, dpr, 0, 0);
        k = Math.min((r.width - 40) / iw, (r.height - 40) / ih); ox = (r.width - iw * k) / 2; oy = (r.height - ih * k) / 2; paint();
      }
      function paint() {
        const r = cv2.getBoundingClientRect(); g.clearRect(0, 0, r.width, r.height);
        g.drawImage(im, ox, oy, iw * k, ih * k);
        g.strokeStyle = "#F28C28"; g.lineWidth = 3; g.beginPath();
        pts.forEach((p, i) => { const x = ox + p[0] * k, y = oy + p[1] * k; i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.closePath(); g.stroke();
        pts.forEach((p, i) => { const x = ox + p[0] * k, y = oy + p[1] * k; g.fillStyle = "#F28C28"; g.beginPath(); g.arc(x, y, 12, 0, 7); g.fill();
          g.fillStyle = "#fff"; g.font = "bold 12px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(String(i + 1), x, y); });
      }
      let drag = -1;
      cv2.addEventListener("pointerdown", (e) => { const r = cv2.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
        let best = -1, bd = 40; pts.forEach((p, i) => { const d = Math.hypot(ox + p[0] * k - x, oy + p[1] * k - y); if (d < bd) { bd = d; best = i; } });
        drag = best; if (drag >= 0) cv2.setPointerCapture(e.pointerId); });
      cv2.addEventListener("pointermove", (e) => { if (drag < 0) return; const r = cv2.getBoundingClientRect();
        pts[drag] = [Math.min(iw, Math.max(0, (e.clientX - r.left - ox) / k)), Math.min(ih, Math.max(0, (e.clientY - r.top - oy) / k))]; paint(); });
      cv2.addEventListener("pointerup", () => { drag = -1; });
      function warp() {
        const d = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
        let W = Math.max(d(pts[0], pts[1]), d(pts[3], pts[2])), H = Math.max(d(pts[0], pts[3]), d(pts[1], pts[2]));
        const s = Math.min(1, 2400 / Math.max(W, H)); W = Math.round(W * s); H = Math.round(H * s);
        const h = homography(pts, [[0, 0], [W, 0], [W, H], [0, H]]);
        const sc = document.createElement("canvas"); sc.width = iw; sc.height = ih; const sg = sc.getContext("2d"); sg.drawImage(im, 0, 0);
        const src = sg.getImageData(0, 0, iw, ih).data;
        const oc = document.createElement("canvas"); oc.width = W; oc.height = H; const og = oc.getContext("2d");
        const out = og.createImageData(W, H), od = out.data;
        for (let v = 0; v < H; v++) for (let u = 0; u < W; u++) {
          const den = h[6] * u + h[7] * v + 1, x = (h[0] * u + h[1] * v + h[2]) / den, y = (h[3] * u + h[4] * v + h[5]) / den;
          const xi = x | 0, yi = y | 0, o = (v * W + u) * 4;
          if (xi < 0 || yi < 0 || xi >= iw || yi >= ih) { od[o] = od[o + 1] = od[o + 2] = 255; od[o + 3] = 255; continue; }
          const si = (yi * iw + xi) * 4; od[o] = src[si]; od[o + 1] = src[si + 1]; od[o + 2] = src[si + 2]; od[o + 3] = 255;
        }
        og.putImageData(out, 0, 0);
        return new Promise((res) => oc.toBlob((b) => res(b), "image/jpeg", 0.9));
      }
      setTimeout(layout, 0); window.addEventListener("resize", layout, { once: true });
    }).then((v) => v);
  }

  // ---------------------------------------------------------------- PDF 도면 (pdf.js, 처음 쓸 때만 불러옴)
  let pdfjsP = null;
  function pdfjs() {
    if (!pdfjsP) pdfjsP = new Promise((res, rej) => {
      if (window.pdfjsLib) { res(window.pdfjsLib); return; }
      const sc = document.createElement("script"); sc.src = "vendor/pdfjs/pdf.min.js";
      sc.onload = () => { window.pdfjsLib.GlobalWorkerOptions.workerSrc = "vendor/pdfjs/pdf.worker.min.js"; res(window.pdfjsLib); };
      sc.onerror = () => { pdfjsP = null; rej(new Error("PDF 모듈을 불러오지 못했습니다")); };
      document.head.append(sc);
    });
    return pdfjsP;
  }
  const PT_MM = 25.4 / 72;
  async function pdfOpen(file) {
    const lib = await pdfjs();
    const doc = await lib.getDocument({ data: new Uint8Array(await file.arrayBuffer()), cMapUrl: "vendor/pdfjs/cmaps/", cMapPacked: true,
      standardFontDataUrl: "vendor/pdfjs/standard_fonts/" }).promise;
    return doc;
  }
  function paperName(w, h) {
    const [a, b] = [Math.min(w, h), Math.max(w, h)];
    for (const [n, x, y] of [["A0", 841, 1189], ["A1", 594, 841], ["A2", 420, 594], ["A3", 297, 420], ["A4", 210, 297]])
      if (Math.abs(a - x) < 8 && Math.abs(b - y) < 8) return n;
    return `${Math.round(w)}×${Math.round(h)}mm`;
  }
  async function pdfPageInfo(doc, n) { const pg = await doc.getPage(n); const v = pg.getViewport({ scale: 1 }); return { pg, wmm: v.width * PT_MM, hmm: v.height * PT_MM, v }; }
  async function pdfRender(doc, n, longPx = 4000) {      // → JPEG blob (휴대폰 메모리 고려해 긴 변 4000px)
    const { pg, v } = await pdfPageInfo(doc, n);
    const k = longPx / Math.max(v.width, v.height), vp = pg.getViewport({ scale: k });
    const c = document.createElement("canvas"); c.width = Math.round(vp.width); c.height = Math.round(vp.height);
    const g = c.getContext("2d"); g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
    await pg.render({ canvasContext: g, viewport: vp }).promise;
    return new Promise((res) => c.toBlob((b) => res(b), "image/jpeg", 0.9));
  }

  // ---------------------------------------------------------------- dialog
  function dialog(newProject) {
    const lab = (t) => el("div", { class: "ns-lab" }, t);
    let kind = "blank", file = null;
    const inp = (ph, val, type = "text") => el("input", { type, class: "ns-in", placeholder: ph, value: val });
    const proj = inp("프로젝트(건물) 이름", newProject ? "" : (S.meta.project || ""));
    const name = inp("도면(층) 이름 예: 1F", newProject ? "1F" : `${S.sheets.length + 1}F`);
    const bw = inp("가로 (m)", "30", "number"), bh = inp("세로 (m)", "20", "number");
    const pw = inp("사진 가로 실제 길이 (m) — 모르면 그대로", "40", "number");
    const prev = el("div", { class: "ns-prev" }, "사진 없음");
    const fileIn = el("input", { type: "file", accept: "image/*", hidden: "" });
    const pdfIn = el("input", { type: "file", accept: "application/pdf,.pdf", hidden: "" });
    let pdf = null;                    // { doc, n, wmm, hmm }
    const pgIn = inp("쪽", "1", "number"), scIn = el("select", { class: "ns-in" }, ["50", "100", "150", "200", "300", "500"].map((v) => el("option", { value: v }, "1/" + v)));
    scIn.value = "100";
    const pdfInfo = el("p", { class: "small" }, "");
    const pdfBox = el("div", { class: "ns-box hidden" }, el("div", { class: "ns-row" }, lab("PDF 쪽"), pgIn, lab("축척"), scIn), pdfInfo);
    const pdfWidth = () => { if (!pdf) return; pw.value = (pdf.wmm * (+scIn.value || 100) / 1000).toFixed(2);
      pdfInfo.textContent = `${pdf.n}쪽 중 ${pgIn.value}쪽 · 용지 ${paperName(pdf.wmm, pdf.hmm)} (PDF에서 자동) → 가로 ${pw.value} m`; };
    const pdfShow = async () => {
      const n = Math.min(Math.max(parseInt(pgIn.value) || 1, 1), pdf.n); pgIn.value = n;
      await withBusy("PDF 올리는 중…", async () => {
        const inf = await pdfPageInfo(pdf.doc, n); pdf.wmm = inf.wmm; pdf.hmm = inf.hmm; pdfWidth();
        file = await pdfRender(pdf.doc, n); showPrev(file); warpBtn.classList.add("hidden");
      }, `${n}쪽 그리는 중`);
    };
    pgIn.onchange = () => pdf && pdfShow().catch((e) => toast("PDF: " + (e.message || e)));
    scIn.onchange = pdfWidth;
    pdfIn.onchange = async (e) => {
      const f = e.target.files[0]; if (!f) return;
      try {
        const doc = await withBusy("PDF 올리는 중…", () => pdfOpen(f), f.name); pdf = { doc, n: doc.numPages }; pgIn.value = 1; pdfBox.classList.remove("hidden");
        if (name.value === "1F" || !name.value.trim()) name.value = f.name.replace(/\.pdf$/i, "").slice(0, 30);
        await pdfShow();
      } catch (er) { pdf = null; pdfBox.classList.add("hidden"); prev.textContent = "PDF를 열 수 없습니다"; toast("PDF: " + (er.message || er), 4000); }
    };
    const camIn = el("input", { type: "file", accept: "image/*", capture: "environment", hidden: "" });
    const showPrev = (blob) => { prev.innerHTML = ""; prev.append(el("img", { src: URL.createObjectURL(blob) })); };
    const onFile = async (e) => { const f = e.target.files[0]; if (!f) return; file = f; pdf = null; pdfBox.classList.add("hidden");
      await withBusy("사진 올리는 중…", async () => { showPrev(f); const im = prev.querySelector("img"); if (im) await new Promise((r) => { im.onload = im.onerror = r; }); }, f.name || "");
      warpBtn.classList.remove("hidden"); };
    const warpBtn = el("button", { class: "b gray hidden", onclick: async () => {
      const out = await cornerEditor(file); if (out) { file = out; showPrev(out); toast("반듯하게 폈습니다"); } } }, "📐 모서리 맞춰 펴기");
    fileIn.onchange = onFile; camIn.onchange = onFile;
    const blankBox = el("div", { class: "ns-box" }, lab("크기 (가로 × 세로)"), el("div", { class: "ns-row" }, bw, el("span", {}, "×"), bh, el("span", {}, "m")),
      el("p", { class: "small" }, "격자(1 m) 위에 검측위치·스케치를 기록합니다."));
    const photoBox = el("div", { class: "ns-box hidden" },
      el("div", { class: "ns-row" }, el("button", { class: "b edit", onclick: () => camIn.click() }, "📷 촬영"),
        el("button", { class: "b gray", onclick: () => fileIn.click() }, "🖼 사진 선택"),
        el("button", { class: "b gray", onclick: () => pdfIn.click() }, "📄 PDF")), prev, warpBtn, pdfBox, lab("도면 가로 실제 길이 (m)"), pw,
      el("p", { class: "small" }, "도면 사진·스캔·캡처·PDF를 배경으로 깝니다. PDF는 축척만 고르면 실제 치수가 맞습니다. 사진은 나중에 메뉴 › 📏 축척 맞추기로 아는 길이 두 점을 찍어 맞출 수 있습니다."),
      fileIn, camIn, pdfIn);
    const seg = el("div", { class: "dt-seg" },
      el("button", { class: "on", onclick: (e) => pick(e, "blank") }, "빈 도면 (격자)"),
      el("button", { onclick: (e) => pick(e, "photo") }, "사진·PDF 배경"));
    function pick(e, k) { kind = k; for (const b of seg.children) b.classList.toggle("on", b === e.target);
      blankBox.classList.toggle("hidden", k !== "blank"); photoBox.classList.toggle("hidden", k !== "photo"); }
    sheet((b) => b.append(el("h3", {}, newProject ? "새 조사 (DXF 없이)" : "도면 추가"),
      ...(newProject ? [lab("프로젝트(건물)"), proj] : [el("p", { class: "small" }, `프로젝트: ${S.meta.project || "-"}`)]),
      lab("도면(층) 이름"), name, lab("배경"), seg, blankBox, photoBox,
      el("div", { class: "btns" }, el("button", { class: "b gray", onclick: () => $("#modal").classList.remove("show") }, "취소"),
        el("span", { class: "sp" }),
        el("button", { class: "b ok", onclick: async () => {
          const nm = name.value.trim(); const pj = (newProject ? proj.value : S.meta.project || "").trim();
          if (!nm) { toast("도면 이름을 입력하세요"); return; }
          if (newProject && !pj) { toast("프로젝트 이름을 입력하세요"); return; }
          const o = { name: nm, kind };
          if (kind === "blank") { o.w = +bw.value || 30; o.h = +bh.value || 20; }
          else { if (!file) { toast("사진·PDF를 고르세요"); return; } o.file = file; o.widthM = +pw.value || 40; if (pdf) o.pdf = true; }
          $("#modal").classList.remove("show");
          try {
            await withBusy(kind === "blank" ? "도면 만드는 중…" : "도면 올리는 중…", async () => {
              if (newProject) await createProject(pj, o);
              else { await addSheet(S.db, o); S.sheets = q("SELECT id, analysis_id, seq, name FROM sheets ORDER BY seq, id"); loadSheet(S.sheets.length - 1); persistSoon(); }
            }, nm);
            toast(`'${nm}' 도면을 만들었습니다 — 검측점을 찍으세요`);
          } catch (e) { toast("만들지 못했습니다: " + (e.message || e), 4000); }
        } }, "만들기"))));
  }

  // ---------------------------------------------------------------- 축척 맞추기 (두 점 + 실제 길이)
  let calib = null;
  function startCalib() {
    if (!S.sheet) return;
    if (!S.sheet.extKind || S.sheet.members.length) { toast("DXF에서 만든 도면은 이미 실제 치수입니다"); return; }
    calib = []; hint("📏 길이를 아는 두 점을 차례로 누르세요"); draw();
  }
  function tapCalib(x, y) {                 // returns true if handled
    if (!calib) return false;
    calib.push([x, y]); draw();
    if (calib.length < 2) return true;
    const [[ax, ay], [bx, by]] = calib; calib = null; hint("");
    const cur = Math.hypot(bx - ax, by - ay);
    if (cur < 1) { draw(); return true; }
    const v = parseFloat(prompt(`두 점 사이 실제 길이 (m)\n(지금 도면상 ${(cur / 1000).toFixed(3)} m)`, ""));
    if (!(v > 0)) { draw(); return true; }
    rescale(v * 1000 / cur, ax, ay);
    return true;
  }
  function drawCalib() {
    if (!calib) return;
    ctx.save(); ctx.strokeStyle = "#F28C28"; ctx.lineWidth = 3;
    for (const p of calib) { const [sx, sy] = w2s(...p); ctx.beginPath(); ctx.arc(sx, sy, 8, 0, 7); ctx.stroke(); }
    ctx.restore();
  }
  function rescale(f, ax, ay) {              // 도면 상대좌표 기준 (ax, ay) 중심으로 × f
    const sh = S.sheet, ox = sh.origin.ox, oy = sh.origin.oy;
    const R = (x, y) => [ax + (x - ax) * f, ay + (y - ay) * f];
    const RA = (x, y) => { const [rx, ry] = R(x - ox, y - oy); return [rx + ox, ry + oy]; };   // 절대좌표용
    // 도면 크기: 원점(0,0)과 (w,h) 모두 변환 → 새 원점 이동
    const [nx0, ny0] = R(0, 0), [nx1, ny1] = R(sh.ext.w, sh.ext.h);
    const ext = { w: Math.round(nx1 - nx0), h: Math.round(ny1 - ny0) };
    const shift = (flat) => { const o = []; for (let i = 0; i + 1 < flat.length; i += 2) { const [x, y] = R(flat[i], flat[i + 1]); o.push(Math.round(x - nx0), Math.round(y - ny0)); } return o; };
    const bg = shift(sh.bg);
    run("UPDATE sheets SET extents=?, background=? WHERE id=?", [JSON.stringify(ext), JSON.stringify(bg), sh.id]);
    if (sh.imgRect) {
      const [a, b] = R(sh.imgRect[0], sh.imgRect[1]), [c, d] = R(sh.imgRect[2], sh.imgRect[3]);
      run("UPDATE sheet_ext SET rect=? WHERE sheet_id=?", [JSON.stringify([a - nx0 + ox, b - ny0 + oy, c - nx0 + ox, d - ny0 + oy]), sh.id]);
    }
    for (const r of q("SELECT uid, rec, deleted FROM surveys WHERE sheet_id=?", [sh.id])) {
      const rec = JSON.parse(r.rec);
      if (rec.x != null) { const [x, y] = RA(rec.x, rec.y); rec.x = x - nx0; rec.y = y - ny0; }
      if (rec.area && rec.area.length === 4) { const [a0, a1] = RA(rec.area[0], rec.area[1]), [a2, a3] = RA(rec.area[2], rec.area[3]); rec.area = [a0 - nx0, a1 - ny0, a2 - nx0, a3 - ny0]; }
      for (const k of ["bx", "by", "dx", "dy"]) if (typeof rec[k] === "number") rec[k] *= f;
      rec.updated = nowIso();
      run("UPDATE surveys SET rec=?, updated=? WHERE uid=?", [JSON.stringify(rec), rec.updated, r.uid]);
    }
    for (const r of q("SELECT uid, data, deleted FROM sketches WHERE sheet_id=?", [sh.id])) {
      const d = JSON.parse(r.data), o = [];
      for (let i = 0; i + 1 < d.pts.length; i += 2) { const [x, y] = RA(d.pts[i], d.pts[i + 1]); o.push(Math.round(x - nx0), Math.round(y - ny0)); }
      d.pts = o; d.updated = nowIso();
      run("UPDATE sketches SET data=?, updated=? WHERE uid=?", [JSON.stringify(d), d.updated, r.uid]);
    }
    persistSoon(); loadSheet(S.sheetIdx);
    toast(`축척을 맞췄습니다 (×${f.toFixed(3)})`);
  }

  // ---------------------------------------------------------------- buttons
  $("#btnNew").onclick = () => dialog(true);
  $("#miNew").onclick = () => { $("#menu").classList.remove("show"); dialog(!S.db); };
  $("#miCalib").onclick = () => { $("#menu").classList.remove("show"); startCalib(); };

  return { dialog, addSheet, createProject, startCalib, tapCalib, drawCalib, get calibrating() { return !!calib; } };
})();
window.NS = NS;
