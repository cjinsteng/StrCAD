/* StrCAD 현장조사 — mobile / tablet app
 * Opens a .strsv package (SQLite) exported by the PC (CAD Analysis › 현장조사 › 모바일로 내보내기),
 * lets you tap inspection locations on the plan and record 부재검측 / 균열검토 / custom 용도,
 * takes photos, and saves the same file back for the PC to import.
 * Data stays on the device (IndexedDB autosave) until you save/share the file.
 */
"use strict";

const FORMAT = "strcad-survey";
const KIND_KO = { c: "기둥", g: "거더", b: "보", w: "벽체" };
const KIND_COL = { c: "#d62828", g: "#1d4ed8", b: "#15803d", w: "#374151" };
const EXIST = ["존재", "없음", "상이(도면과 다름)"];
const DEFAULT_PURPOSES = {
  "부재검측": { color: "#d62828", size: true, length: true, rebar: true, exist: true, fields: [] },
  "균열검토": { color: "#ea580c", size: false, length: false, rebar: false, exist: false, fields: [
    ["crack_w", "균열폭", "mm", null], ["crack_l", "균열길이", "m", null],
    ["shape", "균열형태", "", ["수직", "수평", "경사", "망상", "기타"]],
    ["face", "위치(면)", "", ["상면", "하면", "측면", "단부", "중앙"]],
    ["progress", "진행성", "", ["없음", "있음", "관찰필요"]]] },
  "하중조사": { color: "#0f766e", area: true, size: false, length: false, rebar: false, exist: false, fields: [
    ["use", "실 용도", "", null], ["fin", "바닥 마감", "", null], ["fin_t", "마감 두께", "mm", null],
    ["ceil", "천장", "", null], ["ceil_h", "천장고", "m", null], ["part", "칸막이", "", ["없음", "가동 경량칸막이", "조적·고정벽"]],
    ["equip", "설비·장비", "", ["없음", "있음(경량)", "있음(중량)"]]] },
};
// ---- 하중조사 참고값: 활하중 = KDS 41 12 00 표 3.2-1 기본등분포활하중 (kN/m²)
const LL_KDS = {
  "주거(거실)": 2.0, "공동주택 공용실": 5.0, "병실": 2.0, "병원 수술실·실험실": 3.0, "호텔 객실": 2.0, "숙박 공용실": 5.0,
  "일반 사무실": 2.5, "특수용도 사무실": 5.0, "문서보관실": 5.0, "교실": 3.0, "학교 실험실": 3.0, "중량물 실험실": 5.0,
  "상점·백화점(1층)": 5.0, "상점·백화점(2층 이상)": 4.0, "창고형 매장": 6.0, "식당": 5.0, "주방": 7.0, "무대": 7.0,
  "집회장(고정 좌석)": 4.0, "집회장(이동 좌석)": 5.0, "연회장·무도장": 5.0, "체육관": 5.0, "도서관 열람실": 3.0, "서고": 7.5,
  "주차장(30kN 이하·옥내)": 3.0, "주차장(30kN 이하·옥외)": 5.0, "주차장(30~90kN)": 6.0, "경량품 창고": 6.0, "중량품 창고": 12.0,
  "경공업 공장": 6.0, "중공업 공장": 12.0, "기계실·전기실·공조실": 5.0, "로비·1층 복도": 5.0, "복도(1층 외)": 4.0,
  "계단": 5.0, "계단(단독주택)": 2.0, "옥외광장": 12.0, "지붕(점유 안 함)": 1.0, "지붕(산책로)": 3.0, "지붕(정원·집회)": 5.0,
};
// 마감 단위중량 (kN/m³) · 천장 (kN/m²) — 일반 설계 참고값, 현장 확인 후 조정
const FIN_GAMMA = { "시멘트 모르타르": 20.0, "타일+모르타르": 21.0, "석재(화강석)": 26.0, "무근콘크리트(누름)": 23.0,
  "경량기포콘크리트(온돌층)": 5.0, "온돌(기포+모르타르)": 13.0, "목재 마루": 8.0, "아스팔트 방수+보호콘크리트": 22.0,
  "에폭시·도장": 0, "비닐타일·장판": 0, "카펫": 0, "노출(마감 없음)": 0 };
const CEIL_KN = { "석고보드(경량철골)": 0.2, "텍스(T-bar)": 0.15, "금속 천장": 0.15, "목재 천장": 0.2, "노출(천장 없음)": 0, "기타": 0 };
function loadCalc(fl) {
  fl = fl || {};
  const g = FIN_GAMMA[fl.fin], t = parseFloat(fl.fin_t) || 0;
  const fin = g != null ? (g ? g * t / 1000 : (fl.fin ? 0.1 : 0)) : 0;
  const ceil = CEIL_KN[fl.ceil] || 0;
  let ll = LL_KDS[fl.use];
  const partAdd = fl.part === "가동 경량칸막이" && ll != null && ll < 4.0 ? 1.0 : 0;
  return { fin, ceil, dl: fin + ceil, ll: ll != null ? ll + partAdd : null, partAdd };
}
function loadText(fl) {
  const c = loadCalc(fl), parts = [];
  if (c.dl) parts.push(`마감·천장 DL ${c.dl.toFixed(2)}`);
  if (c.ll != null) parts.push(`LL ${c.ll.toFixed(1)}${c.partAdd ? "(칸막이+1.0)" : ""}`);
  return parts.length ? parts.join(" · ") + " kN/m²" : "";
}
const EXTRA_COLORS = ["#2563eb", "#7c3aed", "#0f766e", "#ca8a04", "#db2777", "#0891b2", "#4d7c0f", "#6b7280"];
const NAME_KINDS = ["보", "거더", "기둥", "벽체", "슬래브", "계단", "기초", "기타"];
const PICK_DEFAULT = {
  size_b: ["150","200","250","300","350","400","450","500","550","600","700","800","900","1000","1200"],
  size_h: ["150","200","250","300","400","450","500","550","600","650","700","750","800","900","1000","1200","1500"],
  length: ["0.5","1","1.5","2","2.5","3","4","5","6","7","8","9","10","12"],
  exist: EXIST,
  crack_w: ["0.1","0.2","0.3","0.4","0.5","0.7","1.0","2.0"],
  crack_l: ["0.2","0.5","1.0","1.5","2.0","3.0","5.0"],
};
const FIELD_LABEL = { inspector: "검토자", no: "번호", name: "부재명", purpose: "용도", size_b: "치수 b(폭)", size_h: "치수 h(춤)", length: "길이", exist: "부재유무", date: "조사일" };
const FIELD_UNIT = { size_b: "mm", size_h: "mm", length: "m" };
const BAR_PREFIX = ["D", "HD", "SHD", "UHD"];
const BAR_DIA = [10, 13, 16, 19, 22, 25, 29, 32, 35];
const BAR_COUNT = [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 20];
const BAR_SPACING = [100, 125, 150, 175, 200, 250, 300, 400];

const NATIVE = !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform());
const $ = (s) => document.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "style") e.style.cssText = v;
    else e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null) e.append(k.nodeType ? k : document.createTextNode(String(k)));
  return e;
};
const nowIso = () => { const d = new Date(); const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`; };
const today = () => nowIso().slice(0, 10);
const uid = () => (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "") : Math.random().toString(16).slice(2) + Date.now().toString(16));
const fmtNum = (v) => (Math.abs(v - Math.round(v)) < 1e-6 ? String(Math.round(v)) : String(+v.toFixed(2)));

// ======================================================================= state
const S = {
  SQL: null, db: null, fileName: "", meta: {}, purposes: {}, picklists: {},
  sheets: [], sheetIdx: 0, sheet: null, recs: [], sel: null, edit: null,
  mode: "point", purpose: "부재검측", filter: "전체", spanStart: null,
  view: { s: 1, ox: 0, oy: 0 }, pc: false, dirtyPersist: null, photoURL: new Map(),
};

function toast(msg, ms = 2200) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), ms); }
function hint(msg) { const h = $("#hint"); h.textContent = msg || ""; h.classList.toggle("show", !!msg); }

// ======================================================================= IndexedDB autosave
const IDB = {
  open() { return new Promise((res, rej) => { const r = indexedDB.open("strcad-survey", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("files"); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); }); },
  async put(key, val) { const db = await this.open(); return new Promise((res, rej) => { const tx = db.transaction("files", "readwrite");
    tx.objectStore("files").put(val, key); tx.oncomplete = () => res(); tx.onerror = () => rej(tx.error); }); },
  async get(key) { const db = await this.open(); return new Promise((res, rej) => { const tx = db.transaction("files", "readonly");
    const r = tx.objectStore("files").get(key); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); }); },
};
function persistSoon() {
  clearTimeout(S.dirtyPersist);
  S.dirtyPersist = setTimeout(async () => {
    try { await IDB.put("current", { bytes: S.db.export(), name: S.fileName, saved: nowIso() }); } catch (e) { console.warn(e); }
  }, 600);
}

// ======================================================================= package (sqlite)
function q(sql, params = []) { const st = S.db.prepare(sql); st.bind(params); const out = []; while (st.step()) out.push(st.getAsObject()); st.free(); return out; }
function run(sql, params = []) { S.db.run(sql, params); }

async function loadSQL() {
  if (!S.SQL) S.SQL = await initSqlJs({ locateFile: (f) => "vendor/" + f });
}

async function openBytes(bytes, name) {
  await loadSQL();
  const db = new S.SQL.Database(new Uint8Array(bytes));
  let meta;
  try { meta = Object.fromEntries(db.exec("SELECT key, value FROM meta")[0].values); } catch (e) { meta = {}; }
  if (meta.format !== FORMAT) { db.close(); throw new Error("StrCAD 현장조사 파일(.strsv)이 아닙니다."); }
  if (S.db) S.db.close();
  S.db = db; S.meta = meta; S.fileName = name || meta.project + ".strsv";
  S.purposes = Object.assign({}, DEFAULT_PURPOSES, JSON.parse(meta.purposes || "{}"));
  for (const k of Object.keys(DEFAULT_PURPOSES)) if (DEFAULT_PURPOSES[k].area) S.purposes[k] = Object.assign({}, S.purposes[k], { area: true });
  S.picklists = JSON.parse(meta.picklists || "{}");
  S.sheets = q("SELECT id, analysis_id, seq, name FROM sheets ORDER BY seq, id");
  run("CREATE TABLE IF NOT EXISTS orig (uid TEXT PRIMARY KEY, path TEXT, dir TEXT, size INTEGER, sent INTEGER DEFAULT 0)");
  run("CREATE TABLE IF NOT EXISTS sketches (uid TEXT PRIMARY KEY, sheet_id INTEGER, updated TEXT, deleted INTEGER DEFAULT 0, data TEXT)");
  run("CREATE TABLE IF NOT EXISTS sheet_ext (sheet_id INTEGER PRIMARY KEY, suid TEXT, kind TEXT, image BLOB, mime TEXT, iw INTEGER, ih INTEGER, rect TEXT)");
  S.photoURL.forEach((u) => URL.revokeObjectURL(u)); S.photoURL.clear();
  $("#proj").textContent = meta.project || "(프로젝트)";
  $("#welcome").classList.remove("show");
  if (!S.purposes[S.purpose]) S.purpose = Object.keys(S.purposes)[0];
  buildPurposeSeg(); buildFilters();
  loadSheet(0);
  persistSoon();
  toast(`${meta.project || ""} — 도면 ${S.sheets.length}장`);
}

// ---- DXF 없이 만든 도면(빈 도면·사진): 배경 이미지
function loadSheetImage(sh) {
  sh.extKind = ""; sh.img = null;
  let r = null;
  try { r = q("SELECT suid, kind, image, mime, rect FROM sheet_ext WHERE sheet_id=?", [sh.id])[0]; } catch (e) { r = null; }
  if (!r) return;
  sh.extKind = r.kind || "photo"; sh.suid = r.suid;
  if (!r.image) return;
  const rect = r.rect ? JSON.parse(r.rect) : [sh.origin.ox, sh.origin.oy, sh.origin.ox + sh.ext.w, sh.origin.oy + sh.ext.h];
  sh.imgRect = [rect[0] - sh.origin.ox, rect[1] - sh.origin.oy, rect[2] - sh.origin.ox, rect[3] - sh.origin.oy];
  const url = URL.createObjectURL(new Blob([r.image], { type: r.mime || "image/jpeg" }));
  const im = new Image();
  im.onload = () => { if (S.sheet === sh) { sh.img = im; draw(); } };
  im.src = url;
}
function drawSheetImage(sh) {
  const im = sh.img; if (!im) return;
  const [x0, y0, x1, y1] = sh.imgRect, iw = im.naturalWidth, ih = im.naturalHeight;
  const a = w2s(x0, y1), b = w2s(x1, y0);             // 화면에서 이미지 왼쪽위 · 오른쪽아래
  const kx = iw / (b[0] - a[0]), ky = ih / (b[1] - a[1]);
  const vx0 = Math.max(0, a[0]), vy0 = Math.max(0, a[1]), vx1 = Math.min(VW, b[0]), vy1 = Math.min(VH, b[1]);
  if (vx1 <= vx0 || vy1 <= vy0) return;
  ctx.save(); ctx.globalAlpha = 0.9;
  ctx.drawImage(im, (vx0 - a[0]) * kx, (vy0 - a[1]) * ky, (vx1 - vx0) * kx, (vy1 - vy0) * ky, vx0, vy0, vx1 - vx0, vy1 - vy0);
  ctx.restore();
}

function loadSheet(i) {
  if (!guardEdit()) return;
  S.sheetIdx = Math.max(0, Math.min(S.sheets.length - 1, i));
  const row = q("SELECT * FROM sheets WHERE id=?", [S.sheets[S.sheetIdx].id])[0];
  const sh = { id: row.id, name: row.name, origin: JSON.parse(row.origin), ext: JSON.parse(row.extents),
    members: JSON.parse(row.members), bg: JSON.parse(row.background), grid: JSON.parse(row.grid) };
  sh.byId = new Map(sh.members.map((m) => [m.i, m]));
  S.sheet = sh; S.sel = null; S.edit = null; S.spanStart = null;
  loadSheetImage(sh);
  loadRecs();
  if (window.SK) SK.load();
  $("#pgLbl").textContent = `${S.sheetIdx + 1}/${S.sheets.length}`;
  $("#floorBtn").textContent = sh.name;
  closePanel(); fit(); renderList();
}

function loadRecs() {
  S.recs = q("SELECT uid, rec, deleted FROM surveys WHERE sheet_id=?", [S.sheet.id])
    .filter((r) => !r.deleted).map((r) => JSON.parse(r.rec));
}

function saveRec(rec) {
  rec.updated = nowIso();
  run("INSERT OR REPLACE INTO surveys (uid, sheet_id, updated, deleted, rec) VALUES (?,?,?,0,?)",
    [rec.uid, S.sheet.id, rec.updated, JSON.stringify(rec)]);
  const i = S.recs.findIndex((r) => r.uid === rec.uid);
  if (i >= 0) S.recs[i] = rec; else S.recs.push(rec);
  persistSoon();
}

function deleteRec(rec) {
  run("UPDATE surveys SET deleted=1, updated=? WHERE uid=?", [nowIso(), rec.uid]);
  S.recs = S.recs.filter((r) => r.uid !== rec.uid);
  persistSoon();
}

function saveMeta(key, value) { run("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", [key, value]); S.meta[key] = value; persistSoon(); }

function photoURL(id) {
  if (S.photoURL.has(id)) return S.photoURL.get(id);
  const r = q("SELECT data, mime FROM photos WHERE uid=?", [id])[0];
  if (!r) return null;
  const u = URL.createObjectURL(new Blob([r.data], { type: r.mime || "image/jpeg" }));
  S.photoURL.set(id, u); return u;
}

// ---- 사진 파일 이름: 프로젝트_도면_찍은날짜_검측번호_용도코드_순번 (예: 현장A_2F_20261030_003_sec_01.jpg)
const PURPOSE_CODE = { "부재검측": "sec", "균열검토": "cra", "하중조사": "load" };
function purposeCode(p) { const P = S.purposes[p] || {}; return P.code || PURPOSE_CODE[p] || namePart(p || "etc"); }
function namePart(t) { return String(t || "").replace(/[\\/:*?"<>|\r\n\t]/g, "_").trim().split(/\s+/).join("-") || "미지정"; }
function ymd(d) { return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`; }
function photoBase(rec, f) {
  const taken = new Date(f && f.lastModified ? f.lastModified : Date.now());
  return [namePart(S.meta.project || "프로젝트"), namePart(S.sheet ? S.sheet.name : "도면"), ymd(taken),
    String(rec.no).padStart(3, "0"), purposeCode(rec.purpose)].join("_");
}
function nextPhotoName(base) {
  const used = new Set(q("SELECT name FROM photos WHERE name LIKE ?", [base + "_%"]).map((r) => r.name.replace(/\.[^.]+$/, "")));
  let k = 1; while (used.has(`${base}_${String(k).padStart(2, "0")}`)) k++;
  return `${base}_${String(k).padStart(2, "0")}`;
}

// ---- 진행 표시 (사진·PDF 올리기, 파일 열기·저장, PC 전송 …) — 화면을 덮고 "올리는 중…" + 진행
let busyN = 0;
function busy(text, sub = "") {
  let ov = $("#busy");
  if (!ov) { ov = el("div", { id: "busy" }, el("div", { class: "bz-card" }, el("div", { class: "bz-spin" }), el("b", { class: "bz-t" }), el("small", { class: "bz-s" }),
    el("div", { class: "bz-bar" }, el("i")))); document.body.append(ov); }
  busyN++; ov.classList.add("show");
  const set = (t, sb = "", frac = null) => { ov.querySelector(".bz-t").textContent = t; ov.querySelector(".bz-s").textContent = sb;
    const bar = ov.querySelector(".bz-bar"); bar.classList.toggle("on", frac != null); if (frac != null) bar.firstChild.style.width = Math.round(Math.max(0, Math.min(1, frac)) * 100) + "%"; };
  set(text, sub);
  let closed = false;
  return { set, close() { if (closed) return; closed = true; busyN = Math.max(0, busyN - 1); if (!busyN) ov.classList.remove("show"); } };
}
const paint = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));     // 표시가 먼저 그려지게
async function withBusy(text, fn, sub = "") { const b = busy(text, sub); await paint(); try { return await fn(b); } finally { b.close(); } }
window.withBusy = withBusy; window.busy = busy; window.paint = paint;

async function addPhotoFiles(files, rec) {
  const imgs = [...files].filter((f) => f.type.startsWith("image/"));
  if (!imgs.length) return [];
  return withBusy("사진 올리는 중…", async (b) => {
  const ids = [];
  for (const [i, f] of imgs.entries()) {
    b.set("사진 올리는 중…", `${i + 1} / ${imgs.length}장`, i / imgs.length); await paint();
    const id = "ph_" + uid().slice(0, 16);
    const no3 = String(rec.no).padStart(3, "0");
    const ext = ((f.name || "").match(/\.([A-Za-z0-9]{2,5})$/) || [, f.type === "image/png" ? "png" : "jpg"])[1].toLowerCase();
    const base = photoBase(rec, f), nm = nextPhotoName(base);          // 프로젝트_도면_날짜_번호_용도_순번
    // 원본은 휴대폰 저장소에 그대로, DB에는 화면 표시용 축소본 (원본은 PC로 보낼 때 따로 전송)
    let origOk = false;
    if (NATIVE) {
      try {
        const rel = `StrCAD/사진/${safeName(S.meta.project)}/${nm}.${ext}`;
        const r = await saveToDevice(rel, new Uint8Array(await f.arrayBuffer()));
        run("INSERT OR REPLACE INTO orig (uid, path, dir, size, sent) VALUES (?,?,?,?,0)", [id, rel, r.dir, f.size]);
        origOk = true;
      } catch (e) { toast("원본 저장 실패 — 축소본만 저장: " + (e.message || e), 4000); }
    }
    const blob = await shrinkImage(f, 1600, 0.82);
    const data = new Uint8Array(await blob.arrayBuffer());
    run("INSERT INTO photos (uid, survey_uid, name, mime, data, created) VALUES (?,?,?,?,?,?)", [id, rec.uid, `${nm}.jpg`, "image/jpeg", data, nowIso()]);
    if (origOk) S.origSaved = (S.origSaved || 0) + 1;
    ids.push(id);
  }
  b.set("사진 올리는 중…", `${imgs.length} / ${imgs.length}장`, 1);
  persistSoon();
  return ids;
  });
}

function shrinkImage(file, maxSide, quality) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, maxSide / Math.max(img.naturalWidth, img.naturalHeight));
      const c = document.createElement("canvas");
      c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      c.toBlob((b) => resolve(b || file), "image/jpeg", quality);
    };
    img.onerror = () => { URL.revokeObjectURL(url); resolve(file); };
    img.src = url;
  });
}

// ---------------------------------------------------------------- 휴대폰 저장소 (내 파일 › Documents › StrCAD)
const FSP = () => window.Capacitor.Plugins.Filesystem;
const safeName = (t) => String(t || "미지정").replace(/[\\/:*?"<>|]/g, "_").trim() || "미지정";
async function ensureStorage() {
  try { const p = await FSP().checkPermissions(); if (p.publicStorage !== "granted") await FSP().requestPermissions(); } catch (e) { /* Android 11+: not needed */ }
}
async function writeBytesNative(path, bytes, directory) {
  const CH = 3 * 262144;                       // multiple of 3 → base64 pieces can be appended
  for (let i = 0; i === 0 || i < bytes.length; i += CH) {
    const part = b64(bytes.subarray(i, Math.min(bytes.length, i + CH)));
    if (i === 0) await FSP().writeFile({ path, data: part, directory, recursive: true });
    else await FSP().appendFile({ path, data: part, directory });
    if (!bytes.length) break;
  }
  return (await FSP().getUri({ path, directory })).uri;
}
async function saveToDevice(rel, bytes) {
  await ensureStorage();
  let last;
  for (const [dir, label] of [["DOCUMENTS", "내 파일 › Documents › "], ["EXTERNAL", "내 파일 › Android › data › kr.strcad.survey › files › "]]) {
    try { const uri = await writeBytesNative(rel, bytes, dir); return { uri, dir, where: label + rel.split("/").join(" › ") }; }
    catch (e) { last = e; }
  }
  throw last;
}
function shareUri(uri, title) {
  return window.Capacitor.Plugins.Share.share({ title, dialogTitle: title, url: uri })
    .catch((e) => { if (!/cancel/i.test(String(e && e.message))) alert("공유 실패: " + (e.message || e) + "\n파일은 저장되어 있으니 내 파일 앱에서 보내세요."); });
}
function savedSheet(r, fname, extra) {
  const close = sheet((b) => b.append(el("h3", {}, "✔ 저장 완료"),
    el("div", { class: "saved-path" }, r.where),
    extra ? el("div", { class: "small" }, extra) : "",
    el("p", { class: "small" }, "카카오톡·메일로 보내려면 [공유하기]를 누르거나, 내 파일 앱에서 위 위치의 파일을 직접 보내세요. PC에는 USB·드라이브로 옮겨도 됩니다."),
    el("div", { class: "btns" }, el("div", { class: "sp" }), el("button", { class: "b gray", onclick: () => close() }, "닫기"),
      el("button", { class: "b ok", onclick: () => shareUri(r.uri, fname) }, "공유하기"))));
}

function b64(bytes) {
  let s = ""; const CH = 0x8000;
  for (let i = 0; i < bytes.length; i += CH) s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
  return btoa(s);
}
async function nativeShare(bytes, fname, title) {
  const { Filesystem, Share } = window.Capacitor.Plugins;
  const w = await Filesystem.writeFile({ path: fname, data: b64(bytes), directory: "CACHE" });
  await Share.share({ title, dialogTitle: title, files: [w.uri] });
}

async function saveFile() {
  if (!S.db) return;
  if (!guardEdit()) return;
  saveMeta("mobile_saved", nowIso());
  const bytes = S.db.export();
  const fname = `${(S.meta.project || "현장조사").replace(/[\\/:*?"<>|]/g, "_")}_현장조사_${today()}.strsv`;
  if (NATIVE) {
    try {
      const r = await withBusy("저장하는 중…", () => saveToDevice(`StrCAD/${fname}`, bytes), fname);
      const no = q("SELECT COUNT(*) AS n FROM orig")[0].n;
      savedSheet(r, fname, no ? `원본 사진 ${no}장: ${r.where.split(" › StrCAD")[0]} › StrCAD › 사진 › ${safeName(S.meta.project)} — PC로 옮길 때 이 '사진' 폴더도 함께 옮기면 PC가 원본으로 바꿉니다. (Wi-Fi 'PC로 보내기'는 원본을 자동 전송)` : "");
    } catch (e) { alert("저장 실패: " + (e.message || e)); }
    return;
  }
  const file = new File([bytes], fname, { type: "application/octet-stream" });
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try { await navigator.share({ files: [file], title: fname }); toast("공유했습니다"); return; }
    catch (e) { if (e.name === "AbortError") return; }
  }
  const a = el("a", { href: URL.createObjectURL(file), download: fname });
  document.body.append(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
  toast(`저장: ${fname}`);
}

// ======================================================================= geometry
function P(x, y) { return [x - S.sheet.origin.ox, y - S.sheet.origin.oy]; }      // absolute → sheet-relative
function A(x, y) { return [x + S.sheet.origin.ox, y + S.sheet.origin.oy]; }      // sheet-relative → absolute
function memEnds(m) { const l = m.l; return [[l[0], l[1]], [l[l.length - 2], l[l.length - 1]]]; }
const FIELD_CHOICES = { use: Object.keys(LL_KDS), fin: Object.keys(FIN_GAMMA), ceil: Object.keys(CEIL_KN) };
function areaRect(rec) { if (!rec.area) return null; const [x0, y0] = P(rec.area[0], rec.area[1]), [x1, y1] = P(rec.area[2], rec.area[3]);
  return [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)]; }
function areaOf(rec) { const r = areaRect(rec); return r ? (r[2] - r[0]) * (r[3] - r[1]) / 1e6 : 0; }
function geom(rec) {             // → {type:'point', p} | {type:'span', a, b} in sheet-relative coords
  const ar = areaRect(rec);
  if (ar) return { type: "area", r: ar, p: [(ar[0] + ar[2]) / 2, (ar[1] + ar[3]) / 2] };
  const m = S.sheet.byId.get(rec.member);
  if (m && m.k !== "c" && !m.cv && rec.t0 != null) {
    const [p1, p2] = memEnds(m);
    const at = (t) => [p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t];
    if (rec.t1 != null) return { type: "span", a: at(rec.t0), b: at(rec.t1) };
    return { type: "point", p: at(rec.t0) };
  }
  if (m && m.k === "c" && rec.dx != null) return { type: "point", p: [m.c[0] + rec.dx, m.c[1] + rec.dy] };
  return { type: "point", p: P(rec.x, rec.y) };
}
function anchor(rec) { const g = geom(rec); return g.type === "span" ? [(g.a[0] + g.b[0]) / 2, (g.a[1] + g.b[1]) / 2] : g.type === "area" ? [g.r[0], g.r[3]] : g.p; }
function bubble(rec) { const a = anchor(rec); return [a[0] + (rec.bx || 0), a[1] + (rec.by || 0)]; }
function distSeg(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1, L2 = dx * dx + dy * dy;
  if (L2 < 1e-9) return [Math.hypot(px - x1, py - y1), 0];
  const t = ((px - x1) * dx + (py - y1) * dy) / L2, tc = Math.max(0, Math.min(1, t));
  return [Math.hypot(px - (x1 + tc * dx), py - (y1 + tc * dy)), t];
}
function inPoly(x, y, flat) {
  let inside = false;
  for (let i = 0, n = flat.length / 2, j = n - 1; i < n; j = i++) {
    const xi = flat[2 * i], yi = flat[2 * i + 1], xj = flat[2 * j], yj = flat[2 * j + 1];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi) inside = !inside;
  }
  return inside;
}
function locate(x, y, only) {     // sheet-relative point → {m, t, dxy, p}
  const tol = 22 / S.view.s;
  if (only) { const [p1, p2] = memEnds(only); let [, t] = distSeg(x, y, ...p1, ...p2); t = Math.max(0, Math.min(1, t));
    return { m: only, t, p: [p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t] }; }
  let best = null;
  for (const m of S.sheet.members) {
    if (m.k === "c") {
      if (m.p.length && inPoly(x, y, m.p)) return { m, dxy: [x - m.c[0], y - m.c[1]], p: [x, y] };
      const d = Math.hypot(x - m.c[0], y - m.c[1]);
      if (d <= tol && (!best || d < best.d)) best = { d, m };
      continue;
    }
    if (m.cv) continue;
    const [p1, p2] = memEnds(m);
    const [d, t] = distSeg(x, y, ...p1, ...p2);
    if (d <= Math.max(tol, m.w / 2) && (!best || d < best.d)) best = { d, m, t: Math.max(0, Math.min(1, t)) };
  }
  if (!best) return { m: null, p: [x, y] };
  if (best.m.k === "c") return { m: best.m, dxy: [0, 0], p: best.m.c };
  const [p1, p2] = memEnds(best.m);
  return { m: best.m, t: best.t, p: [p1[0] + (p2[0] - p1[0]) * best.t, p1[1] + (p2[1] - p1[1]) * best.t] };
}
function memberName(m) { if (!m) return ""; return m.n ? `${KIND_KO[m.k]} ${m.n}` : KIND_KO[m.k]; }
function memberSize(m) { return m ? m.s : ""; }
function nextNo() { return S.recs.reduce((a, r) => Math.max(a, +r.no || 0), 0) + 1; }

// ======================================================================= drawing
const cv = $("#cv"); const ctx = cv.getContext("2d");
function resize() { const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); draw(); }
function w2s(x, y) { const v = S.view; return [(x - v.ox) * v.s, (v.oy - y) * v.s]; }
function s2w(sx, sy) { const v = S.view; return [sx / v.s + v.ox, v.oy - sy / v.s]; }
function fit() {
  if (!S.sheet) return;
  const r = cv.getBoundingClientRect(), e = S.sheet.ext;
  const s = 0.92 * Math.min(r.width / Math.max(e.w, 1), (r.height - 50) / Math.max(e.h, 1));
  S.fitS = s; S.view = { s, ox: e.w / 2 - r.width / 2 / s, oy: e.h / 2 + (r.height + 40) / 2 / s };
  draw();
}
// Android WebView drops whole paths whose coordinates are huge (deep zoom), so every segment is
// clipped to the visible rectangle (+margin) before it reaches the canvas.
let VW = 0, VH = 0; const VM = 40;
function clipSeg(x0, y0, x1, y1) {                 // Liang–Barsky against [-VM, VW+VM] × [-VM, VH+VM]
  let t0 = 0, t1 = 1; const dx = x1 - x0, dy = y1 - y0;
  const P = [-dx, dx, -dy, dy], Q = [x0 + VM, VW + VM - x0, y0 + VM, VH + VM - y0];
  for (let k = 0; k < 4; k++) {
    if (P[k] === 0) { if (Q[k] < 0) return null; continue; }
    const t = Q[k] / P[k];
    if (P[k] < 0) { if (t > t1) return null; if (t > t0) t0 = t; } else { if (t < t0) return null; if (t < t1) t1 = t; }
  }
  return [x0 + t0 * dx, y0 + t0 * dy, x0 + t1 * dx, y0 + t1 * dy];
}
function segTo(a, b) { const c = clipSeg(a[0], a[1], b[0], b[1]); if (c) { ctx.moveTo(c[0], c[1]); ctx.lineTo(c[2], c[3]); } }
function line(flat, i) { segTo(w2s(flat[i], flat[i + 1]), w2s(flat[i + 2], flat[i + 3])); }
function onScreen(x, y, m = VM) { return x > -m && y > -m && x < VW + m && y < VH + m; }
function clampS(s) { const f = S.fitS || s; return Math.min(Math.max(s, f / 8), f * 200); }   // zoom range 1/8 … 200×
function setView(s, ox, oy) { if (isFinite(s) && isFinite(ox) && isFinite(oy) && s > 0) S.view = { s, ox, oy }; }
function purposeColor(p) { return (S.purposes[p] || {}).color || "#d62828"; }

function draw() {
  const r = cv.getBoundingClientRect(); VW = r.width; VH = r.height;
  ctx.clearRect(0, 0, r.width, r.height);
  if (!S.sheet) return;
  const sh = S.sheet;
  drawSheetImage(sh);
  ctx.lineWidth = 1;
  ctx.strokeStyle = "#a5d8e6"; ctx.setLineDash([6, 3]); ctx.beginPath();
  for (let i = 0; i < sh.grid.length; i += 4) line(sh.grid, i);
  ctx.stroke(); ctx.setLineDash([]);
  ctx.strokeStyle = "#dcdcdc"; ctx.beginPath();
  for (let i = 0; i < sh.bg.length; i += 4) line(sh.bg, i);
  ctx.stroke();
  for (const k of ["w", "g", "b"]) {
    ctx.strokeStyle = KIND_COL[k]; ctx.lineWidth = k === "w" ? 3 : 2; ctx.beginPath();
    for (const m of sh.members) if (m.k === k) {
      for (let i = 0; i + 3 < m.l.length; i += 2) line(m.l, i);
    }
    ctx.stroke();
  }
  ctx.fillStyle = KIND_COL.c;
  for (const m of sh.members) if (m.k === "c") {
    const [x, y] = w2s(...m.c);
    if (!onScreen(x, y, VM + m.b * S.view.s)) continue;
    if (m.p.length && m.b * S.view.s > 6) { ctx.strokeStyle = "#f4a3a3"; ctx.lineWidth = 1; ctx.beginPath();
      for (let i = 0; i < m.p.length; i += 2) { const q = w2s(m.p[i], m.p[i + 1]); i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1]); }
      ctx.closePath(); ctx.stroke(); }
    ctx.beginPath(); ctx.arc(x, y, 3.5, 0, 7); ctx.fill();
  }
  // member names when zoomed in
  if (S.view.s * 300 > 6) {
    ctx.font = "11px sans-serif"; ctx.textAlign = "center";
    for (const m of sh.members) if (m.k !== "c" && m.n && m.L * S.view.s > 60) {
      const [p1, p2] = memEnds(m); const c = clipSeg(...w2s(...p1), ...w2s(...p2)); if (!c) continue;
      const a = [c[0], c[1]], b = [c[2], c[3]];
      ctx.fillStyle = KIND_COL[m.k]; ctx.fillText(m.n, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 6);
    }
  }
  // selected member
  const cur = S.edit || S.sel;
  if (cur) { const m = sh.byId.get(cur.member); if (m && m.k !== "c") { ctx.strokeStyle = "#f59e0bcc"; ctx.lineWidth = 7; ctx.beginPath();
    for (let i = 0; i + 3 < m.l.length; i += 2) line(m.l, i); ctx.stroke(); } }
  if (window.SK) SK.draw();
  // survey bubbles
  for (const rec of S.recs) if (purposeVisible(rec.purpose)) drawRec(rec, cur && rec.uid === cur.uid ? (S.edit || rec) : rec, cur && rec.uid === cur.uid);
  if (S.areaDraft) { const [x0, y0, x1, y1] = S.areaDraft, a = w2s(Math.min(x0, x1), Math.max(y0, y1)), b = w2s(Math.max(x0, x1), Math.min(y0, y1));
    ctx.save(); ctx.strokeStyle = purposeColor(S.purpose); ctx.lineWidth = 2; ctx.setLineDash([6, 4]); ctx.strokeRect(a[0], a[1], b[0] - a[0], b[1] - a[1]);
    const A = Math.abs((x1 - x0) * (y1 - y0)) / 1e6; ctx.setLineDash([]); ctx.font = "bold 12px sans-serif"; ctx.fillStyle = purposeColor(S.purpose);
    ctx.fillText(`${(Math.abs(x1 - x0) / 1000).toFixed(2)} × ${(Math.abs(y1 - y0) / 1000).toFixed(2)} m · ${A.toFixed(1)} m²`, a[0] + 4, a[1] - 6); ctx.restore(); }
  if (S.edit && !S.recs.some((r) => r.uid === S.edit.uid)) drawRec(S.edit, S.edit, true);
  if (S.spanStart) { const a = w2s(...S.spanStart.p); ctx.fillStyle = purposeColor(S.purpose); ctx.beginPath(); ctx.arc(a[0], a[1], 7, 0, 7); ctx.fill(); }
  if (window.NS) NS.drawCalib();
}
function drawRec(_r, rec, hl) {
  const col = purposeColor(rec.purpose), g = geom(rec);
  let px, py;
  ctx.strokeStyle = col; ctx.fillStyle = col;
  const [bx, by] = w2s(...bubble(rec)), R = hl ? 15 : 13;
  if (g.type === "area") {
    const a = w2s(g.r[0], g.r[3]), b = w2s(g.r[2], g.r[1]);
    ctx.save(); ctx.globalAlpha = hl ? 0.22 : 0.12; ctx.fillRect(a[0], a[1], b[0] - a[0], b[1] - a[1]); ctx.globalAlpha = 1;
    ctx.lineWidth = hl ? 3 : 2; ctx.setLineDash([10, 5]); ctx.strokeRect(a[0], a[1], b[0] - a[0], b[1] - a[1]); ctx.setLineDash([]);
    const fl = rec.fields || {}, w = b[0] - a[0];
    if (w > 70) { const lines = [fl.use, [fl.fin, fl.fin_t ? fl.fin_t + "mm" : ""].filter(Boolean).join(" "), fl.ceil, loadText(fl)].filter(Boolean);
      ctx.font = "bold 12px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      const cx = (a[0] + b[0]) / 2, cy = (a[1] + b[1]) / 2 - (lines.length - 1) * 8;
      lines.slice(0, Math.max(1, Math.floor((b[1] - a[1]) / 16))).forEach((t, i) => { ctx.lineWidth = 3; ctx.strokeStyle = "#fff"; ctx.strokeText(t, cx, cy + i * 16, w - 8); ctx.fillStyle = col; ctx.fillText(t, cx, cy + i * 16, w - 8); }); }
    ctx.restore(); ctx.strokeStyle = col; ctx.fillStyle = col; [px, py] = a;
  } else if (g.type === "span") { const a = w2s(...g.a), b = w2s(...g.b); ctx.lineWidth = hl ? 11 : 7; ctx.lineCap = "round";
    ctx.beginPath(); segTo(a, b); ctx.stroke(); ctx.lineCap = "butt"; px = (a[0] + b[0]) / 2; py = (a[1] + b[1]) / 2; }
  else { [px, py] = w2s(...g.p); if (onScreen(px, py)) { ctx.beginPath(); ctx.arc(px, py, 3.5, 0, 7); ctx.fill(); } }
  if (!onScreen(bx, by) && !onScreen(px, py)) return;
  const d = Math.hypot(px - bx, py - by);
  if (d > R) { ctx.lineWidth = 2; ctx.beginPath(); segTo([bx + (px - bx) * R / d, by + (py - by) * R / d], [px, py]); ctx.stroke(); }
  ctx.fillStyle = "#fff"; ctx.lineWidth = hl ? 4 : 3; ctx.beginPath(); ctx.arc(bx, by, R, 0, 7); ctx.fill(); ctx.stroke();
  if (hl) { ctx.strokeStyle = "#f59e0b"; ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(bx, by, R + 5, 0, 7); ctx.stroke(); }
  ctx.fillStyle = col; ctx.font = "bold 12px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(String(rec.no), bx, by + 0.5); ctx.textBaseline = "alphabetic";
}

// ======================================================================= touch / mouse
const ptrs = new Map(); let gesture = null;
cv.addEventListener("pointerdown", (e) => {
  cv.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, [e.offsetX, e.offsetY]);
  if (ptrs.size === 1 && S.mode === "sketch" && window.SK) { gesture = { type: "sketch", view: { ...S.view } }; SK.down(e.offsetX, e.offsetY); return; }
  if (ptrs.size === 2 && gesture && gesture.type === "sketch") SK.cancel();
  if (ptrs.size === 2 && gesture && gesture.type === "area") { S.areaDraft = null; }
  if (ptrs.size === 1 && (S.mode === "point" || S.mode === "span") && (S.purposes[S.purpose] || {}).area) {
    const [x, y] = s2w(e.offsetX, e.offsetY);
    const hit = bubbleHit(x, y);
    if (!hit) { gesture = { type: "area", x0: e.offsetX, y0: e.offsetY, w0: [x, y], moved: false }; return; }
  }
  if (ptrs.size === 1) {
    const [x, y] = s2w(e.offsetX, e.offsetY);
    const hit = bubbleHit(x, y);
    gesture = { type: "tap", x0: e.offsetX, y0: e.offsetY, moved: false, bubble: hit, view: { ...S.view } };
  } else if (ptrs.size === 2) {
    const [a, b] = [...ptrs.values()];
    gesture = { type: "pinch", d0: Math.hypot(a[0] - b[0], a[1] - b[1]), c0: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], view: { ...S.view } };
  }
});
cv.addEventListener("pointermove", (e) => {
  if (!ptrs.has(e.pointerId) || !gesture) return;
  ptrs.set(e.pointerId, [e.offsetX, e.offsetY]);
  if (gesture.type === "pinch" && ptrs.size === 2) {
    const [a, b] = [...ptrs.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]), c = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const v0 = gesture.view, k = d / Math.max(gesture.d0, 1), s = clampS(v0.s * k);
    const wx = gesture.c0[0] / v0.s + v0.ox, wy = v0.oy - gesture.c0[1] / v0.s;
    setView(s, wx - c[0] / s, wy + c[1] / s); draw(); return;
  }
  if (gesture.type === "sketch") { SK.move(e.offsetX, e.offsetY); return; }
  if (gesture.type === "area") {
    if (!gesture.moved && Math.hypot(e.offsetX - gesture.x0, e.offsetY - gesture.y0) < 8) return;
    gesture.moved = true; const [x, y] = s2w(e.offsetX, e.offsetY); S.areaDraft = [...gesture.w0, x, y]; draw(); return;
  }
  const dx = e.offsetX - gesture.x0, dy = e.offsetY - gesture.y0;
  if (!gesture.moved && Math.hypot(dx, dy) < 8) return;
  gesture.moved = true;
  if (gesture.bubble) {                         // drag a number bubble
    const rec = editTarget(gesture.bubble); const a = anchor(rec); const [x, y] = s2w(e.offsetX, e.offsetY);
    rec.bx = x - a[0]; rec.by = y - a[1]; gesture.bubbleRec = rec; draw(); return;
  }
  const v0 = gesture.view; setView(v0.s, v0.ox - dx / v0.s, v0.oy + dy / v0.s); draw();
});
function endPtr(e) {
  if (!ptrs.has(e.pointerId)) return;
  ptrs.delete(e.pointerId);
  if (!gesture) return;
  if (gesture.type === "pinch") { if (ptrs.size === 0) gesture = null; return; }
  if (gesture.type === "sketch") { gesture = null; SK.up(e.offsetX, e.offsetY, e.type === "pointercancel"); return; }
  if (gesture.type === "area") {
    const g = gesture; gesture = null; const d = S.areaDraft; S.areaDraft = null;
    if (!g.moved || !d || e.type === "pointercancel") { draw(); hint("하중조사: 끌어서 영역(사각형)을 그리세요"); setTimeout(() => hint(""), 1800); return; }
    if (Math.abs(d[2] - d[0]) * S.view.s < 12 || Math.abs(d[3] - d[1]) * S.view.s < 12) { draw(); return; }
    newAreaRec(d); return;
  }
  const g = gesture; gesture = null;
  if (g.bubble && g.moved) { const rec = g.bubbleRec; if (rec && !S.edit) saveRec(rec); selectRec(rec.uid, true); return; }
  if (!g.moved) tap(...s2w(e.offsetX, e.offsetY));
}
cv.addEventListener("pointerup", endPtr); cv.addEventListener("pointercancel", endPtr);
cv.addEventListener("wheel", (e) => { e.preventDefault(); const k = e.deltaY < 0 ? 1.2 : 1 / 1.2; const [wx, wy] = s2w(e.offsetX, e.offsetY);
  const s = clampS(S.view.s * k); setView(s, wx - e.offsetX / s, wy + e.offsetY / s); draw(); }, { passive: false });

function bubbleHit(x, y) {
  for (let i = S.recs.length - 1; i >= 0; i--) {
    const r = S.edit && S.edit.uid === S.recs[i].uid ? S.edit : S.recs[i];
    if (!purposeVisible(r.purpose)) continue;
    const [bx, by] = bubble(r);
    if (Math.hypot(x - bx, y - by) * S.view.s <= 18) return S.recs[i];
  }
  return null;
}
function editTarget(rec) { return S.edit && S.edit.uid === rec.uid ? S.edit : rec; }

function tap(x, y) {
  if (!S.sheet) return;
  if (window.NS && NS.tapCalib(x, y)) return;
  const hit = bubbleHit(x, y);
  if (hit && !S.spanStart) { selectRec(hit.uid); return; }
  if (S.mode === "view") { if (!guardEdit()) return; S.sel = null; closePanel(); draw(); renderList(); return; }
  if (S.mode === "point") { const L = locate(x, y); newRec(L.m, L.t ?? null, null, L.p, L.dxy); return; }
  if (!S.spanStart) {
    const L = locate(x, y);
    if (!L.m || L.m.k === "c") { hint("구간은 보·거더·벽 위에서 시작하세요"); setTimeout(() => hint(""), 1800); return; }
    S.spanStart = { m: L.m, t: L.t, p: L.p }; hint(`${memberName(L.m)} 위에서 끝점을 누르세요`); draw(); return;
  }
  const st = S.spanStart; S.spanStart = null; hint("");
  const L = locate(x, y, st.m);
  if (Math.abs(L.t - st.t) * st.m.L < 50) { toast("구간이 너무 짧습니다"); draw(); return; }
  const [a, b] = [Math.min(st.t, L.t), Math.max(st.t, L.t)];
  newRec(st.m, a, b, [(st.p[0] + L.p[0]) / 2, (st.p[1] + L.p[1]) / 2]);
}

function newAreaRec(d) {
  if (!guardEdit()) return;
  if (!inspector() && !S.askedInsp) { S.askedInsp = true; askInspector(); }
  const [x0, y0] = A(Math.min(d[0], d[2]), Math.min(d[1], d[3])), [x1, y1] = A(Math.max(d[0], d[2]), Math.max(d[1], d[3]));
  const rec = { id: S.recs.reduce((a, r) => Math.max(a, r.id || 0), 0) + 1, uid: uid(), updated: nowIso(), no: nextNo(),
    purpose: S.purpose, member: null, t0: null, t1: null, x: (x0 + x1) / 2, y: (y0 + y1) / 2, area: [x0, y0, x1, y1],
    bx: -14 / S.view.s, by: 14 / S.view.s, name: "", size_b: "", size_h: "", length: "", rebar: {}, exist: "", fields: {},
    photos: [], memo: "", date: today(), mobile: true, inspector: inspector() };
  saveRec(rec);
  S.sel = rec; S.edit = JSON.parse(JSON.stringify(rec));
  openPanel(); renderForm(); renderList(); draw();
}

// ---- 용도별 도면 표시 (부재검측 / 균열검토 / 하중조사 … 따로 또는 같이)
function hiddenPurposes() { try { return new Set(JSON.parse(localStorage.getItem("hidePurposes") || "[]")); } catch (e) { return new Set(); } }
function purposeVisible(p) { return !hiddenPurposes().has(p); }
function showLayers() {
  sheet((b) => {
    const hid = hiddenPurposes();
    const render = () => {
      box.innerHTML = "";
      for (const p of Object.keys(S.purposes)) {
        const on = !hid.has(p), n = S.recs.filter((r) => r.purpose === p).length;
        box.append(el("button", { class: "lay" + (on ? " on" : ""), style: `--c:${purposeColor(p)}`, onclick: () => {
          on ? hid.add(p) : hid.delete(p); try { localStorage.setItem("hidePurposes", JSON.stringify([...hid])); } catch (e) { /* ignore */ }
          render(); draw(); } }, el("i"), `${p}`, el("small", {}, `${n}건`)));
      }
    };
    const box = el("div", { class: "lay-box" });
    b.append(el("h3", {}, "도면에 표시할 조사"), box,
      el("div", { class: "btns" },
        el("button", { class: "b gray", onclick: () => { hid.clear(); try { localStorage.setItem("hidePurposes", "[]"); } catch (e) { /* ignore */ } render(); draw(); } }, "모두 보기"),
        el("span", { class: "sp" }), el("button", { class: "b ok", onclick: () => $("#modal").classList.remove("show") }, "닫기")));
    render();
  });
}

function newRec(m, t0, t1, p, dxy) {
  if (!guardEdit()) return;
  if (!inspector() && !S.askedInsp) { S.askedInsp = true; askInspector(); }
  const [ax, ay] = A(...p);
  const rec = { id: S.recs.reduce((a, r) => Math.max(a, r.id || 0), 0) + 1, uid: uid(), updated: nowIso(), no: nextNo(),
    purpose: S.purpose, member: m ? m.i : null, t0, t1, x: ax, y: ay, bx: 26 / S.view.s, by: 30 / S.view.s,
    name: memberName(m), size_b: "", size_h: "", length: "", rebar: {}, exist: m ? "존재" : "", fields: {},
    photos: [], memo: "", date: today(), mobile: true, inspector: inspector() };
  if (dxy) { rec.dx = dxy[0]; rec.dy = dxy[1]; }
  saveRec(rec);
  S.sel = rec; S.edit = JSON.parse(JSON.stringify(rec));
  openPanel(); renderForm(); renderList(); draw();
  if (!m && S.sheet.members.length) toast("부재가 없는 위치 — 좌표만 기록합니다");
}

// ======================================================================= selection / panel
function selectRec(u, center) {
  if (S.edit && S.edit.uid !== u && !guardEdit()) return;
  S.sel = S.recs.find((r) => r.uid === u) || null;
  if (!S.sel) return;
  if (center) { const a = anchor(S.sel), [sx, sy] = w2s(...a), r = cv.getBoundingClientRect();
    if (sx < 40 || sy < 40 || sx > r.width - 40 || sy > r.height - 40) { S.view.ox = a[0] - r.width / 2 / S.view.s; S.view.oy = a[1] + r.height / 2 / S.view.s; } }
  openPanel(); renderForm(); renderList(); draw();
}
const narrow = () => window.matchMedia("(max-width: 820px)").matches;
function openPanel() {
  $("#panel").classList.remove("hidden");
  if (narrow() && listDock() === "bottom" && !$("#list").classList.contains("collapsed")) { $("#list").classList.add("collapsed", "auto"); toggleIcon(); }
  setTimeout(resize, 0);
}
function closePanel() {
  $("#panel").classList.add("hidden");
  if ($("#list").classList.contains("auto")) { $("#list").classList.remove("collapsed", "auto"); toggleIcon(); }
  setTimeout(resize, 0);
}
$("#panelClose").onclick = () => { if (!guardEdit()) return; S.sel = null; closePanel(); renderList(); draw(); };

function guardEdit() {
  if (!S.edit) return true;
  const orig = S.recs.find((r) => r.uid === S.edit.uid);
  if (orig && JSON.stringify(orig) === JSON.stringify(S.edit)) { S.edit = null; return true; }
  if (confirm(`#${S.edit.no} 편집 내용을 저장할까요?\n(취소 = 저장하지 않음)`)) saveEdit(); else S.edit = null;
  return true;
}
function beginEdit() { if (!S.sel) return false; if (!S.edit || S.edit.uid !== S.sel.uid) S.edit = JSON.parse(JSON.stringify(S.sel)); return true; }
function inspector() { try { return localStorage.getItem("inspector") || ""; } catch (e) { return ""; } }
function showInspector() { const b = $("#btnInsp"), n = inspector(); b.textContent = n ? `👤 ${n}` : "👤 검토자"; b.classList.toggle("none", !n); }
function askInspector() {
  const v = prompt("검토자 성함 (검측위치에 함께 기록됩니다)", inspector());
  if (v == null) return; try { localStorage.setItem("inspector", v.trim()); } catch (e) { /* private */ }
  showInspector(); toast(v.trim() ? `검토자: ${v.trim()}` : "검토자 지움");
}
function saveEdit() { if (!S.edit) return; if (!S.edit.inspector) S.edit.inspector = inspector(); saveRec(S.edit); S.sel = S.edit; S.edit = null; toast(`#${S.sel.no} 저장`); renderForm(); renderList(); draw(); }
function cancelEdit() { S.edit = null; renderForm(); draw(); }

function summary(r) {
  const p = S.purposes[r.purpose] || {}; const parts = [];
  if (p.size && (r.size_b || r.size_h)) parts.push(`${r.size_b || "?"}×${r.size_h || "?"}`);
  if (p.length && r.length) parts.push(`L=${r.length}m`);
  if (p.rebar && Object.values(r.rebar || {}).some(Boolean)) parts.push("철근 입력");
  if (p.exist && r.exist && r.exist !== "존재") parts.push(r.exist);
  for (const [k, lab, unit] of p.fields || []) { const v = (r.fields || {})[k]; if (v) parts.push(p.area && k !== "fin_t" ? `${v}` : `${lab} ${v}${unit}`); }
  if (p.area) { const t = loadText(r.fields), A = areaOf(r); if (A) parts.unshift(`${A.toFixed(1)}m²`); if (t) parts.push(t); }
  const cr = (r.calc || {}).result;
  if (cr && cr.summary && !cr.error) parts.push((cr.ok ? "✔ " : "✘ ") + cr.summary);
  return parts.join(" · ");
}
function positionText(r) {
  const m = S.sheet.byId.get(r.member);
  if (r.area) { const [a, b, c, d] = r.area; return `영역 ${((c - a) / 1000).toFixed(2)} × ${((d - b) / 1000).toFixed(2)} m · ${areaOf(r).toFixed(1)} m²`; }
  if (!m) return r.member == null ? "부재 미지정" : "(부재 없음)";
  let s = `${KIND_KO[m.k]} ${m.n || "(미표기)"} #${m.i}`;
  if (m.k !== "c" && r.t0 != null) {
    const a = r.t0 * m.L;
    s += r.t1 != null ? ` · i단 ${Math.round(Math.min(a, r.t1 * m.L)).toLocaleString()}~${Math.round(Math.max(a, r.t1 * m.L)).toLocaleString()} mm`
      : ` · i단에서 ${Math.round(a).toLocaleString()} mm`;
  }
  s += `\n도면: ${m.s}` + (m.k !== "c" ? `, L=${(m.L / 1000).toFixed(2)} m` : "");
  return s;
}

function renderForm() {
  const f = $("#form"); f.innerHTML = "";
  const rec = S.edit || S.sel; const editing = !!S.edit;
  $("#editFlag").textContent = editing ? "✎ 편집 중 — 저장을 누르세요" : "";
  if (!rec) { $("#pos").textContent = ""; f.append(el("div", { class: "empty" }, "도면에서 검측위치를 누르면 번호가 붙고 여기에서 입력합니다.")); return; }
  $("#pos").textContent = positionText(rec);
  const P = S.purposes[rec.purpose] || DEFAULT_PURPOSES["부재검측"];
  const valTxt = (v, unit) => (v !== "" && v != null ? `${v}${unit && v ? unit : ""}` : "선택");
  const row = (label, ...vals) => f.append(el("div", { class: vals.length > 1 ? "row two" : "row" }, el("div", { class: "lab" }, label), ...vals));
  const vbtn = (key, opts = {}) => el("button", { class: "val" + (editing ? "" : " dim"), onclick: () => pick(key, opts) },
    valTxt(opts.field ? (rec.fields || {})[key] : rec[key], opts.unit ?? FIELD_UNIT[key]));
  row("번호", vbtn("no"));
  row(P.area ? "구역명" : "부재명", vbtn("name", P.area ? { choices: ["사무실", "회의실", "복도", "화장실", "계단실", "기계실", "창고", "주거", "옥상"] } : {}));
  row("용도", vbtn("purpose", { choices: Object.keys(S.purposes) }));
  row("검토자", vbtn("inspector", { choices: inspector() ? [inspector()] : [] }));
  const cres = (rec.calc || {}).result;
  if (!P.area) f.append(el("button", { class: "val wide input-btn" + (cres ? (cres.ok ? " ok" : " ng") : ""), onclick: () => openDetail() },
    el("b", {}, "INPUT"), el("small", {}, cres ? `${cres.ok ? "✔" : "✘"} ${cres.summary}` : "상세 입력 · 휨/전단 검토")));
  if (P.size) row("치수", vbtn("size_b"), el("div", { class: "x" }, "X"), vbtn("size_h"));
  if (P.length) row("길이", vbtn("length"));
  if (P.rebar) row("철근", el("button", { class: "val" + (editing ? "" : " dim"), onclick: rebarGrid }, Object.values(rec.rebar || {}).some(Boolean) ? "입력됨." : "선택"));
  if (P.exist) row("부재<br>유무".replace("<br>", "\n"), vbtn("exist"));
  for (const [k, lab, unit, ch] of P.fields || []) row(lab, vbtn(k, { field: true, unit, choices: ch || FIELD_CHOICES[k] }));
  if (P.area) {
    const t = loadText(rec.fields), A = areaOf(rec);
    f.append(el("div", { class: "load-box" }, el("b", {}, "하중 참고"), el("span", {}, (A ? `면적 ${A.toFixed(1)} m² · ` : "") + (t || "실 용도·마감·천장을 고르면 계산됩니다")),
      el("small", {}, "활하중 = KDS 41 12 00 표 3.2-1 · 마감·천장 = 일반 단위중량 참고값")));
  }
  // photos
  const ph = el("div", { class: "photos" });
  for (const id of rec.photos || []) {
    const u = photoURL(id);
    ph.append(el("div", { class: "ph" }, u ? el("img", { src: u, onclick: () => showPhoto(u) }) : "?",
      el("button", { class: "del", onclick: () => { if (!beginEdit()) return; S.edit.photos = S.edit.photos.filter((x) => x !== id); renderForm(); } }, "✕")));
  }
  const cam = el("input", { type: "file", accept: "image/*", capture: "environment", hidden: "" });
  const gal = el("input", { type: "file", accept: "image/*", multiple: "", hidden: "" });
  const onFiles = async (ev) => { if (!beginEdit()) return; const ids = await addPhotoFiles([...ev.target.files], S.edit);
    S.edit.photos.push(...ids); ev.target.value = ""; renderForm(); toast(`사진 ${ids.length}장 — 저장을 누르세요`); };
  cam.onchange = onFiles; gal.onchange = onFiles;
  f.append(el("div", { class: "row two" }, el("div", { class: "lab" }, "사진"),
    el("button", { class: "val", onclick: () => cam.click() }, "📷 촬영"), el("div"), el("button", { class: "val", onclick: () => gal.click() }, "🖼 앨범")), cam, gal, ph);
  f.append(el("button", { class: "val wide", onclick: memoSheet }, "추가사항" + (rec.memo ? " ✓" : "")));
  if (rec.memo) f.append(el("div", { class: "memo" }, rec.memo));
  f.append(el("div", { class: "row", style: "margin-top:10px" }, el("div", { class: "lab" }, "조사일"), vbtn("date", { choices: [today()] })));
  const btns = el("div", { class: "btns" }, el("button", { class: "b danger", onclick: delCurrent }, "위치 삭제"), el("div", { class: "sp" }));
  if (editing) btns.append(el("button", { class: "b gray", onclick: cancelEdit }, "취소"), el("button", { class: "b ok", onclick: saveEdit }, "💾 저장"));
  else btns.append(el("button", { class: "b edit", onclick: () => { beginEdit(); renderForm(); } }, "✎ 편집"));
  f.append(btns);
}
function delCurrent() {
  const r = S.sel; if (!r) return;
  if (!confirm(`#${r.no} 검측위치를 삭제할까요?`)) return;
  S.edit = null; deleteRec(r); S.sel = null; closePanel(); renderList(); draw(); toast(`#${r.no} 삭제`);
}

// ======================================================================= pickers
function sheet(build) {
  const m = $("#modal"), b = $("#modalBody"); b.innerHTML = ""; build(b); m.classList.add("show");
  return () => m.classList.remove("show");
}
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") $("#modal").classList.remove("show"); });
function drawingValues(key, m) {
  if (!m) return [];
  if (key === "name") return m.n ? [`${KIND_KO[m.k]} ${m.n}`, m.n, KIND_KO[m.k]] : [KIND_KO[m.k]];
  if (key === "size_b") return [String(m.k === "c" ? m.b : m.w)];
  if (key === "size_h") return m.k === "c" ? [String(m.h)] : (m.d ? [String(m.d)] : []);
  if (key === "length" && m.k !== "c") return [...new Set([fmtNum(m.L / 1000), fmtNum(m.ln / 1000)])];
  return [];
}
function recentValues(key, field, purpose) {
  const out = [];
  for (const r of [...S.recs].sort((a, b) => (b.updated || "").localeCompare(a.updated || ""))) {
    if (purpose && r.purpose !== purpose) continue;
    const v = field ? (r.fields || {})[key] : r[key];
    if (v !== "" && v != null && !out.includes(String(v))) out.push(String(v));
    if (out.length >= 10) break;
  }
  return out;
}
function pick(key, opts = {}) {
  if (!beginEdit()) return;
  const e = S.edit, m = S.sheet.byId.get(e.member);
  const field = !!opts.field, pkey = field ? `${e.purpose}.${key}` : key;
  let title = FIELD_LABEL[key] || key, unit = opts.unit ?? FIELD_UNIT[key] ?? "";
  if (field) for (const [k, lab, u] of (S.purposes[e.purpose] || {}).fields || []) if (k === key) { title = lab; unit = u; }
  const cur = String((field ? (e.fields || {})[key] : e[key]) ?? "");
  const groups = [];
  const dv = drawingValues(key, m); if (dv.length) groups.push(["도면값", dv, false]);
  if (key === "no") {
    const used = new Set(S.recs.filter((r) => r.uid !== e.uid).map((r) => +r.no)), nx = Math.max(0, ...used) + 1;
    groups.push(["다음 번호", [String(nx)], false]);
    const gaps = []; for (let i = 1; i < nx && gaps.length < 15; i++) if (!used.has(i)) gaps.push(String(i));
    if (gaps.length) groups.push(["빈 번호", gaps, false]);
  } else {
    const rv = recentValues(key, field, field ? e.purpose : null); if (rv.length) groups.push(["최근 입력", rv, false]);
    const base = opts.choices || (key === "name" ? NAME_KINDS : PICK_DEFAULT[key] || []);
    if (base.length) groups.push(["기본 목록", base.filter(Boolean).map(String), false]);
    if (key !== "purpose") groups.push(["내 목록", [...(S.picklists[pkey] || [])], true]);
  }
  let manage = false;
  const close = sheet((b) => {
    const render = () => {
      b.innerHTML = "";
      const head = el("div", { style: "display:flex;align-items:center;gap:8px" }, el("h3", { style: "flex:1" }, title + (unit ? ` (${unit})` : "")));
      if (key !== "purpose" && key !== "no") head.append(el("button", { class: "b gray", onclick: () => { manage = !manage; render(); } }, manage ? "정리 끝" : "목록 정리"));
      b.append(head);
      for (const [gt, vals, mine] of groups) {
        if (!vals.length) continue;
        b.append(el("div", { class: "grp" }, gt));
        const g = el("div", { class: "grid" });
        for (const v of vals) {
          if (manage && mine) g.append(el("button", { class: "opt rm", onclick: () => { vals.splice(vals.indexOf(v), 1); S.picklists[pkey] = vals.slice(); saveMeta("picklists", JSON.stringify(S.picklists)); render(); } }, "✕ " + v));
          else g.append(el("button", { class: "opt" + (v === cur ? " on" : ""), onclick: () => done(v) }, v));
        }
        b.append(g);
      }
      const inp = el("input", { type: key === "no" ? "number" : "text", value: cur, inputmode: ["no", "size_b", "size_h", "length"].includes(key) || /mm|m|MPa/.test(unit) ? "decimal" : "text" });
      inp.addEventListener("keydown", (ev) => { if (ev.key === "Enter") done(inp.value.trim()); });
      const row = el("div", { class: "inrow" }, inp, el("button", { class: "b edit", onclick: () => done(inp.value.trim()) }, "확인"));
      if (key !== "purpose" && key !== "no") row.append(el("button", { class: "b gray", onclick: () => { const v = inp.value.trim(); if (!v) return;
        const mine = groups.find((g) => g[2]); if (!mine[1].includes(v)) mine[1].push(v); S.picklists[pkey] = mine[1].slice(); saveMeta("picklists", JSON.stringify(S.picklists)); render(); } }, "목록에 추가"));
      row.append(el("button", { class: "b gray", onclick: () => done("") }, "지우기"));
      b.append(row);
    };
    render();
  });
  function done(v) {
    if (key === "no") { if (!/^\d+$/.test(v)) return; v = +v; }
    if (field) { e.fields = e.fields || {}; e.fields[key] = v; } else e[key] = v;
    close(); renderForm(); draw();
    if (key === "size_b" && (S.purposes[e.purpose] || {}).size && !e.size_h) setTimeout(() => pick("size_h"), 80);
  }
}

function rebarLayout(k) {
  if (k === "c") return [["주근", "띠철근"], ["단부", "중앙"]];
  if (k === "w") return [["배근"], ["수직근", "수평근"]];
  return [["상부근", "상부근2", "하부근", "하부근2", "스터럽"], ["I단", "중앙", "J단"]];
}
function parseBar(s) {
  const m = String(s || "").replace(/\s/g, "").toUpperCase().match(/^(?:(\d+)-)?([A-Z]*)(\d+)(?:@(\d+))?$/);
  if (!m) return { n: null, pre: "HD", d: null, sp: null };
  return { n: m[1] ? +m[1] : null, pre: m[2] || "D", d: +m[3], sp: m[4] ? +m[4] : null };
}
const fmtBar = (n, pre, d, sp) => (d ? `${n ? n + "-" : ""}${pre}${d}${sp ? "@" + sp : ""}` : "");
function rebarGrid() {
  if (!beginEdit()) return;
  const e = S.edit, m = S.sheet.byId.get(e.member), [rows, cols] = rebarLayout(m ? m.k : "b");
  const val = Object.assign({}, e.rebar || {});
  const close = sheet((b) => {
    const render = () => {
      b.innerHTML = ""; b.append(el("h3", {}, `철근 — #${e.no} ${e.name || ""}`));
      const g = el("div", { class: "rb-grid", style: `grid-template-columns: 56px repeat(${cols.length}, 1fr)` });
      g.append(el("div"));
      for (const c of cols) g.append(el("div", { class: "h" }, c));
      for (const r of rows) {
        g.append(el("div", { class: "r" }, ({ 상부근: "상부 1단", 상부근2: "상부 2단", 하부근: "하부 1단", 하부근2: "하부 2단" })[r] || r));
        for (const c of cols) g.append(el("button", { onclick: () => barPick(`${r} · ${c}`, val[`${r}|${c}`], /스터럽|띠철근|배근/.test(r) ? "spacing" : "count",
          (v) => { val[`${r}|${c}`] = v; render(); }) }, val[`${r}|${c}`] || "선택"));
      }
      b.append(g);
      b.append(el("div", { class: "btns" },
        el("button", { class: "b gray", onclick: () => { const mid = cols.includes("중앙") ? "중앙" : cols[0];
          const a0 = cols[0], z = cols[cols.length - 1]; for (const r of rows.concat(["주근배치"])) { const v = val[`${r}|${a0}`]; if (v) val[`${r}|${z}`] = v; } render(); } }, `${cols[0]} → ${cols[cols.length - 1]} 복사`),
        el("div", { class: "sp" }), el("button", { class: "b gray", onclick: () => close() }, "취소"),
        el("button", { class: "b ok", onclick: () => { e.rebar = Object.fromEntries(Object.entries(val).filter(([, v]) => v)); close(); renderForm(); } }, "확인")));
    };
    render();
  });
}
function barPick(title, cur, mode, cb) {
  const p = parseBar(cur);
  let n = p.n || (mode === "count" ? 4 : 0), pre = BAR_PREFIX.includes(p.pre) ? p.pre : "HD", d = p.d || (mode === "count" ? 22 : 10), sp = p.sp || (mode === "count" ? 0 : 200);
  const host = el("div", { class: "modal show", style: "z-index:30" }), box = el("div", { class: "sheet" }); host.append(box); document.body.append(host);
  const close = () => host.remove();
  host.addEventListener("click", (ev) => { if (ev.target === host) close(); });
  const value = () => fmtBar(mode === "count" ? n : null, pre, d, mode === "spacing" ? sp : null);
  const render = () => {
    box.innerHTML = ""; box.append(el("h3", {}, title), el("div", { class: "preview" }, value() || "-"));
    const grp = (lab, arr, cur, fmt, set) => { box.append(el("div", { class: "grp" }, lab)); const g = el("div", { class: "grid" });
      for (const v of arr) g.append(el("button", { class: "opt" + (v === cur ? " on" : ""), onclick: () => { set(v); render(); } }, fmt(v))); box.append(g); };
    if (mode === "count") grp("개수", BAR_COUNT, n, (v) => v + "개", (v) => (n = v));
    grp("규격", BAR_PREFIX, pre, String, (v) => (pre = v));
    grp("직경", BAR_DIA, d, (v) => "D" + v, (v) => (d = v));
    if (mode === "spacing") grp("간격", BAR_SPACING, sp, (v) => "@" + v, (v) => (sp = v));
    box.append(el("div", { class: "btns" }, el("button", { class: "b gray", onclick: () => { cb(""); close(); } }, "지우기"), el("div", { class: "sp" }),
      el("button", { class: "b gray", onclick: close }, "취소"), el("button", { class: "b ok", onclick: () => { cb(value()); close(); } }, "확인")));
  };
  render();
}
function memoSheet() {
  if (!beginEdit()) return;
  const e = S.edit;
  const close = sheet((b) => { const t = el("textarea", {}); t.value = e.memo || "";
    b.append(el("h3", {}, `추가사항 — #${e.no}`), t, el("div", { class: "btns" }, el("div", { class: "sp" }),
      el("button", { class: "b gray", onclick: () => close() }, "취소"), el("button", { class: "b ok", onclick: () => { e.memo = t.value.trim(); close(); renderForm(); } }, "확인")));
    setTimeout(() => t.focus(), 50); });
}
function showPhoto(u) { sheet((b) => b.append(el("img", { src: u, style: "width:100%;border-radius:8px" }), el("button", { class: "bigbtn ghost", onclick: () => $("#modal").classList.remove("show") }, "닫기"))); }

// ======================================================================= list / filters / purposes
function buildPurposeSeg() {
  const seg = $("#purposeSeg"); seg.innerHTML = "";
  for (const p of Object.keys(S.purposes)) seg.append(el("button", { class: p === S.purpose ? "on" : "", style: p === S.purpose ? `background:${purposeColor(p)}` : "",
    onclick: () => { S.purpose = p; buildPurposeSeg(); } }, p));
}
function buildFilters() {
  const f = $("#filters"); f.innerHTML = "";
  for (const p of ["전체", ...Object.keys(S.purposes)]) f.append(el("button", { style: `background:${p === S.filter ? (p === "전체" ? "#475569" : purposeColor(p)) : "#3E5580"}`,
    onclick: () => { S.filter = p; buildFilters(); renderList(); } }, p));
}
function listColumns() {
  if (!$("#list").classList.contains("dock-bottom")) return [["no", "번호"], ["name", "부재명"], ["summary", "내용"]];
  const P = S.purposes[S.filter];
  if (!P) return [["no", "번호"], ["purpose", "용도"], ["name", "부재명"], ["summary", "내용"], ["inspector", "검토자"], ["ph", "사진"]];
  const c = [["no", "번호"], ["name", P.area ? "구역" : "부재명"]];
  if (P.area) c.push(["areaM2", "면적(m²)"]);
  if (P.size) c.push(["size", "치수"]); if (P.length) c.push(["length", "길이(m)"]); if (P.rebar) c.push(["rebar", "철근"]); if (P.exist) c.push(["exist", "부재유무"]);
  for (const [k, lab, unit] of P.fields || []) c.push(["f:" + k, lab + (unit ? `(${unit})` : "")]);
  if (P.area) c.push(["dl", "마감+천장 DL(kN/m²)"], ["ll", "활하중 LL(kN/m²)"]);
  c.push(["inspector", "검토자"], ["ph", "사진"]); return c;
}
function rebarText(r) { const rb = r.rebar || {}; const cols = ["I단", "단부", "중앙", "J단", "수직근", "수평근"].filter((c) => Object.keys(rb).some((k) => k.endsWith("|" + c)));
  return cols.map((c) => `[${c}] ` + Object.entries(rb).filter(([k, v]) => k.endsWith("|" + c) && v).map(([k, v]) => (k.startsWith("주근배치") ? "배치" : k.split("|")[0].endsWith("2") ? k[0] + "2" : k[0]) + ":" + v).join(" ")).join(" "); }
function listValue(r, k) {
  if (k === "summary") return summary(r); if (k === "ph") return (r.photos || []).length || "";
  if (k === "size") return r.size_b || r.size_h ? `${r.size_b || "?"}×${r.size_h || "?"}` : ""; if (k === "rebar") return rebarText(r);
  if (k === "areaM2") return r.area ? areaOf(r).toFixed(1) : "";
  if (k === "dl" || k === "ll") { if (!r.area) return ""; const L = loadCalc(r.fields || {}); const v = k === "dl" ? L.dl : L.ll; return v == null ? "" : (+v).toFixed(2); }
  if (k.startsWith("f:")) return (r.fields || {})[k.slice(2)] || ""; return r[k] ?? "";
}
function renderList() {
  const recs = S.recs.filter((r) => S.filter === "전체" || r.purpose === S.filter).sort((a, b) => a.no - b.no);
  $("#listCount").textContent = `${recs.length}건`;
  const cols = listColumns();
  $("#lt-h").innerHTML = ""; $("#lt-h").append(el("tr", {}, cols.map(([, t]) => el("th", {}, t))));
  const tb = $("#lt-b"); tb.innerHTML = "";
  const cur = S.edit || S.sel;
  for (const r of recs) tb.append(el("tr", { class: cur && cur.uid === r.uid ? "sel" : "", onclick: () => selectRec(r.uid, true) }, cols.map(([k]) => el("td", {}, String(listValue(r, k))))));
}
function toggleIcon() {
  const L = $("#list"), c = L.classList.contains("collapsed"), d = listDock();
  $("#listToggle").textContent = d === "left" ? (c ? "›" : "‹") : d === "right" ? (c ? "‹" : "›") : (c ? "▴" : "▾");
}
$("#listToggle").onclick = () => { $("#list").classList.remove("auto"); $("#list").classList.toggle("collapsed"); toggleIcon(); setTimeout(resize, 0); };

// ---- list dock: bottom / left / right (tablet: side is handier)
const DOCKS = { bottom: "아래", left: "왼쪽", right: "오른쪽" };
function listDock() { try { const d = localStorage.getItem("listDock"); return DOCKS[d] ? d : "bottom"; } catch (e) { return "bottom"; } }
function applyDock(d) {
  const L = $("#list");
  if (d === "bottom") { $("#app").append(L); } else { $("#main").append(L); }
  L.classList.remove("dock-bottom", "dock-left", "dock-right"); L.classList.add("dock-" + d);
  toggleIcon(); renderList(); setTimeout(resize, 0);
}
function setDock(d) { try { localStorage.setItem("listDock", d); } catch (e) { /* ignore */ } $("#list").classList.remove("collapsed", "auto"); applyDock(d); }
$("#listDock").onclick = () => sheet((b) => {
  const cur = listDock();
  b.append(el("h3", {}, "조사 목록 위치"),
    el("div", { class: "dock-pick" }, Object.entries(DOCKS).map(([k, t]) => el("button", { class: "dock-opt" + (k === cur ? " on" : ""),
      onclick: () => { $("#modal").classList.remove("show"); setDock(k); } }, el("i", { class: "dk dk-" + k }), t))),
    el("p", { class: "small" }, "태블릿은 옆에 두면 도면과 목록을 같이 보기 편합니다."),
    el("button", { class: "bigbtn ghost", onclick: () => $("#modal").classList.remove("show") }, "닫기"));
});
applyDock(listDock());

function addPurpose() {
  const close = sheet((b) => {
    const name = el("input", { type: "text", placeholder: "용도 이름 (예: 반발경도)" });
    const fields = el("input", { type: "text", placeholder: "입력 항목, 쉼표 구분 (예: 반발도 평균, 추정강도(MPa))" });
    const flags = {}; const fl = el("div", { class: "inrow" });
    for (const [k, t] of [["size", "치수"], ["length", "길이"], ["rebar", "철근"], ["exist", "부재유무"]]) { const c = el("input", { type: "checkbox" }); flags[k] = c; fl.append(el("label", {}, c, " " + t)); }
    b.append(el("h3", {}, "용도 추가"), name, el("div", { style: "height:8px" }), fields, fl, el("div", { class: "btns" }, el("div", { class: "sp" }),
      el("button", { class: "b gray", onclick: () => close() }, "취소"),
      el("button", { class: "b ok", onclick: () => {
        const n = name.value.trim(); if (!n || S.purposes[n]) return;
        const fs = fields.value.split(",").map((s) => s.trim()).filter(Boolean).map((lab, i) => {
          const m = lab.match(/^(.*)\(([^)]*)\)$/); return [`f${i + 1}`, m ? m[1].trim() : lab, m ? m[2] : "", null]; });
        const extra = Object.keys(S.purposes).filter((k) => !DEFAULT_PURPOSES[k]).length;
        S.purposes[n] = { color: EXTRA_COLORS[extra % EXTRA_COLORS.length], size: flags.size.checked, length: flags.length.checked,
          rebar: flags.rebar.checked, exist: flags.exist.checked, fields: fs };
        saveMeta("purposes", JSON.stringify(S.purposes)); S.purpose = n; buildPurposeSeg(); buildFilters(); close(); toast(`용도 추가: ${n}`);
      } }, "추가")));
  });
}

function exportCsv() {
  const cols = [["sheet", "층/도면"], ["no", "번호"], ["purpose", "용도"], ["name", "부재명"], ["size", "치수"], ["length", "길이(m)"], ["rebar", "철근"],
    ["exist", "부재유무"], ["summary", "내용"], ["ph", "사진"], ["memo", "추가사항"], ["inspector", "검토자"], ["date", "조사일"]];
  const rows = [cols.map((c) => c[1])];
  for (const sh of S.sheets) for (const r of q("SELECT rec FROM surveys WHERE sheet_id=? AND deleted=0", [sh.id]).map((x) => JSON.parse(x.rec)).sort((a, b) => a.no - b.no))
    rows.push(cols.map(([k]) => (k === "sheet" ? sh.name : k === "memo" ? r.memo || "" : k === "date" ? r.date || "" : listValue(r, k))));
  const csv = "﻿" + rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\r\n");
  if (NATIVE) { const fn = `${safeName(S.meta.project || "현장조사")}_조사표_${today()}.csv`;
    saveToDevice(`StrCAD/${fn}`, new TextEncoder().encode(csv)).then((r) => savedSheet(r, fn)).catch((e) => alert("저장 실패: " + (e.message || e))); return; }
  const a = el("a", { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: `${S.meta.project || "현장조사"}_조사표.csv` });
  document.body.append(a); a.click(); setTimeout(() => a.remove(), 1000);
}

// ======================================================================= sheets / menu / PC link
$("#pgPrev").onclick = () => S.db && loadSheet(S.sheetIdx - 1);
$("#pgNext").onclick = () => S.db && loadSheet(S.sheetIdx + 1);
$("#btnSheets").onclick = $("#floorBtn").onclick = () => {
  if (!S.db) return;
  const close = sheet((b) => { b.append(el("h3", {}, "도면 LIST")); const l = el("div", { class: "sheets-list" });
    S.sheets.forEach((s, i) => { const n = q("SELECT COUNT(*) AS n FROM surveys WHERE sheet_id=? AND deleted=0", [s.id])[0].n;
      l.append(el("button", { class: i === S.sheetIdx ? "cur" : "", onclick: () => { close(); loadSheet(i); } }, el("span", {}, `${i + 1}. ${s.name}`), el("span", {}, `${n}건`))); });
    b.append(l); });
};
$("#btnFit").onclick = fit;
$("#modeSeg").addEventListener("click", (e) => { const m = e.target.dataset.mode; if (!m) return; S.mode = m; S.spanStart = null; hint("");
  for (const b of $("#modeSeg").children) b.classList.toggle("on", b.dataset.mode === m);
  document.body.classList.toggle("sketching", m === "sketch"); if (window.SK) SK.mode(m === "sketch"); draw(); });
$("#btnMenu").onclick = () => { $("#menuInfo").textContent = S.db ? `${S.fileName} · 내보낸 날짜 ${S.meta.exported || "-"}` : ""; $("#menu").classList.add("show"); };
$("#menu").addEventListener("click", (e) => { if (e.target.id === "menu" || e.target.hasAttribute("data-close")) $("#menu").classList.remove("show"); });
$("#miSave").onclick = () => { $("#menu").classList.remove("show"); saveFile(); };
$("#miPurpose").onclick = () => { $("#menu").classList.remove("show"); if (S.db) addPurpose(); };
$("#miCsv").onclick = () => { $("#menu").classList.remove("show"); if (S.db) exportCsv(); };
$("#btnLayers").onclick = () => showLayers();
$("#miSketch").onclick = () => { $("#menu").classList.remove("show"); if (window.SK) SK.toggleHidden(); };
for (const id of ["#fileOpen", "#fileOpen2"]) $(id).onchange = async (e) => {
  const f = e.target.files[0]; e.target.value = ""; $("#menu").classList.remove("show"); if (!f) return;
  if (S.db && !confirm("지금 열린 조사를 닫고 새 파일을 열까요?\n(저장 안 한 내용은 '저장/공유'로 먼저 내보내세요)")) return;
  try { await withBusy("파일 여는 중…", async () => openBytes(await f.arrayBuffer(), f.name), f.name); } catch (err) { alert(err.message); }
};
$("#btnResume").onclick = async () => { const c = await IDB.get("current"); if (c) { await withBusy("불러오는 중…", () => openBytes(c.bytes, c.name), c.name); toast(`이어서 하기 (${c.saved})`); } };

function pcBase() { return NATIVE ? (localStorage.getItem("pcBase") || "") : ""; }
async function askPcAddress() {
  const cur = localStorage.getItem("pcBase") || "http://192.168.0.";
  const v = prompt("PC 주소 (PC 프로그램 › 현장조사 › Wi-Fi 연결 에 표시된 주소)\n예) http://192.168.0.12:8765", cur);
  if (!v) return false;
  const base = (/^https?:\/\//.test(v) ? v : "http://" + v).replace(/\/?$/, "/");
  try { const r = await fetch(base + "api/ping", { cache: "no-store" }); if (!r.ok) throw new Error(r.status); }
  catch (e) { alert("PC에 연결할 수 없습니다. 같은 Wi-Fi인지, PC에서 Wi-Fi 연결을 켰는지 확인하세요.\n" + base); return false; }
  localStorage.setItem("pcBase", base); toast("PC 연결: " + base); return true;
}
async function pcGet() {
  $("#menu").classList.remove("show");
  try {
    if (NATIVE && !pcBase() && !(await askPcAddress())) return;
    const pj = await (await fetch(pcBase() + "api/projects")).json();
    const project = pj.length === 1 ? pj[0] : prompt("PC의 프로젝트 이름:\n" + pj.join("\n"), pj[0] || "");
    if (project == null) return;
    await withBusy("PC에서 받는 중…", async (b) => {
      const r = await fetch(pcBase() + "api/package?project=" + encodeURIComponent(project));
      if (!r.ok) throw new Error(await r.text());
      b.set("PC에서 받는 중…", "도면·조사 내용 여는 중");
      await openBytes(await r.arrayBuffer(), project + ".strsv");
    }, project);
  } catch (e) { alert("PC에서 받기 실패: " + e.message); }
}
async function pcPut() {
  $("#menu").classList.remove("show");
  if (!S.db || !guardEdit()) return;
  if (NATIVE && !pcBase() && !(await askPcAddress())) return;
  try {
    saveMeta("mobile_saved", nowIso());
    const j = await withBusy("PC로 올리는 중…", async () => {
      const r = await fetch(pcBase() + "api/upload", { method: "POST", body: S.db.export(), headers: { "Content-Type": "application/octet-stream" } });
      const jj = await r.json(); if (!r.ok) throw new Error(jj.error || r.status); return jj; }, "조사 내용 · 사진 축소본");
    toast(`PC 반영: 추가 ${j.added}, 수정 ${j.updated}, 삭제 ${j.deleted}, 사진 ${j.photos}`, 4000);
    if (NATIVE) await sendOriginals();
  } catch (e) { alert("PC로 보내기 실패: " + e.message); }
}
async function sendOriginals() {
  const rows = q("SELECT uid, path, dir FROM orig WHERE sent=0");
  if (!rows.length) return;
  let ok = 0, fail = 0;
  const bz = busy("원본 사진 PC로 올리는 중…");
  for (const [i, r] of rows.entries()) {
    bz.set("원본 사진 PC로 올리는 중…", `${i + 1} / ${rows.length}장`, i / rows.length);
    try {
      const f = await FSP().readFile({ path: r.path, directory: r.dir });
      const bin = atob(f.data), bytes = new Uint8Array(bin.length);
      for (let k = 0; k < bin.length; k++) bytes[k] = bin.charCodeAt(k);
      const resp = await fetch(pcBase() + `api/photo?uid=${encodeURIComponent(r.uid)}&project=${encodeURIComponent(S.meta.project || "")}&name=${encodeURIComponent(r.path.split("/").pop())}`,
        { method: "POST", body: bytes, headers: { "Content-Type": "application/octet-stream" } });
      if (!resp.ok) throw new Error((await resp.json()).error || resp.status);
      run("UPDATE orig SET sent=1 WHERE uid=?", [r.uid]); ok++;
    } catch (e) { fail++; }
  }
  bz.close(); persistSoon();
  toast(`원본 사진 ${ok}장 PC 전송` + (fail ? ` · 실패 ${fail}장 (다음에 다시 보냄)` : ""), 4000);
}
$("#btnInsp").onclick = askInspector;
$("#btnPcGet").onclick = pcGet; $("#miPcGet").onclick = pcGet; $("#miPcPut").onclick = pcPut;
$("#miPcAddr").onclick = () => { $("#menu").classList.remove("show"); askPcAddress(); };

// ======================================================================= start
window.addEventListener("resize", resize);
window.addEventListener("beforeunload", (e) => { if (S.edit) { e.preventDefault(); e.returnValue = ""; } });
(async function start() {
  resize();
  try { const c = await IDB.get("current"); if (c) { $("#btnResume").classList.remove("hidden"); $("#welcomeNote").textContent = `마지막 작업: ${c.name} (${c.saved})`; } } catch (e) { /* private mode */ }
  if (NATIVE) {                                  // APK: PC sync over Wi-Fi with an address entered once
    for (const b of document.querySelectorAll(".pc, #btnPcGet, #miPcAddr")) b.classList.remove("hidden");
  } else {
    try { const r = await fetch("api/ping", { cache: "no-store" }); if (r.ok) { S.pc = true; for (const b of document.querySelectorAll(".pc, #btnPcGet")) b.classList.remove("hidden"); } } catch (e) { /* not served by the PC */ }
    if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("sw.js").catch(() => {});
  }
  loadSQL().catch((e) => toast("SQLite 엔진을 불러오지 못했습니다: " + e.message, 5000));
  showInspector();
})();
