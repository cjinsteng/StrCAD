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

  // ---------------------------------------------------------------- dialog
  function dialog(newProject) {
    let kind = "blank", file = null;
    const inp = (ph, val, type = "text") => el("input", { type, class: "ns-in", placeholder: ph, value: val });
    const proj = inp("프로젝트(건물) 이름", newProject ? "" : (S.meta.project || ""));
    const name = inp("도면(층) 이름 예: 1F", newProject ? "1F" : `${S.sheets.length + 1}F`);
    const bw = inp("가로 (m)", "30", "number"), bh = inp("세로 (m)", "20", "number");
    const pw = inp("사진 가로 실제 길이 (m) — 모르면 그대로", "40", "number");
    const prev = el("div", { class: "ns-prev" }, "사진 없음");
    const fileIn = el("input", { type: "file", accept: "image/*", hidden: "" });
    const camIn = el("input", { type: "file", accept: "image/*", capture: "environment", hidden: "" });
    const onFile = (e) => { const f = e.target.files[0]; if (!f) return; file = f; const u = URL.createObjectURL(f);
      prev.innerHTML = ""; prev.append(el("img", { src: u })); };
    fileIn.onchange = onFile; camIn.onchange = onFile;
    const blankBox = el("div", { class: "ns-box" }, lab("크기 (가로 × 세로)"), el("div", { class: "ns-row" }, bw, el("span", {}, "×"), bh, el("span", {}, "m")),
      el("p", { class: "small" }, "격자(1 m) 위에 검측위치·스케치를 기록합니다."));
    const photoBox = el("div", { class: "ns-box hidden" },
      el("div", { class: "ns-row" }, el("button", { class: "b edit", onclick: () => camIn.click() }, "📷 촬영"),
        el("button", { class: "b gray", onclick: () => fileIn.click() }, "🖼 사진 선택")), prev, lab("사진 가로 실제 길이 (m)"), pw,
      el("p", { class: "small" }, "도면 사진·스캔·캡처를 배경으로 깝니다. 축척은 나중에 메뉴 › 📏 축척 맞추기로 아는 길이 두 점을 찍어 맞출 수 있습니다."),
      fileIn, camIn);
    const seg = el("div", { class: "dt-seg" },
      el("button", { class: "on", onclick: (e) => pick(e, "blank") }, "빈 도면 (격자)"),
      el("button", { onclick: (e) => pick(e, "photo") }, "사진·이미지 배경"));
    function pick(e, k) { kind = k; for (const b of seg.children) b.classList.toggle("on", b === e.target);
      blankBox.classList.toggle("hidden", k !== "blank"); photoBox.classList.toggle("hidden", k !== "photo"); }
    const lab = (t) => el("div", { class: "ns-lab" }, t);
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
          else { if (!file) { toast("사진을 촬영하거나 고르세요"); return; } o.file = file; o.widthM = +pw.value || 40; }
          $("#modal").classList.remove("show");
          try {
            if (newProject) await createProject(pj, o);
            else { await addSheet(S.db, o); S.sheets = q("SELECT id, analysis_id, seq, name FROM sheets ORDER BY seq, id"); loadSheet(S.sheets.length - 1); persistSoon(); }
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
