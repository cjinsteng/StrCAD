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
  "균열검토": { color: "#ea580c", crack: true, size: false, length: false, rebar: false, exist: false, fields: [
    ["ctype", "손상종류", "", null], ["cmem", "부재", "", null], ["crack_w", "균열폭", "mm", null], ["crack_l", "균열길이", "m", null],
    ["leak_w", "누수폭", "m", null], ["leak_l", "누수길이", "m", null], ["ar_b", "범위 가로", "m", null], ["ar_l", "범위 세로", "m", null],
    ["dmg_b", "범위 B", "mm", null], ["dmg_d", "범위 D", "mm", null], ["gap_w", "이격폭", "mm", null], ["gap_l", "이격길이", "m", null],
    ["rebar_l", "노출길이", "mm", null],
    ["shape", "균열형태", "", ["수직", "수평", "경사", "망상", "기타"]],
    ["progress", "진행성", "", ["없음", "있음", "관찰필요"]]] },
  "하중조사": { color: "#0f766e", area: true, size: false, length: false, rebar: false, exist: false, fields: [
    ["use", "실 용도", "", null], ["fin", "바닥 마감", "", null], ["fin_t", "마감 두께", "mm", null],
    ["ceil", "천장", "", null], ["ceil_h", "천장고", "m", null], ["part", "칸막이", "", ["없음", "가동 경량칸막이", "조적·고정벽"]],
    ["equip", "설비·장비", "", ["없음", "있음(경량)", "있음(중량)"]]] },
  "기타": { color: "#64748b", size: false, length: false, rebar: false, exist: false, fields: [
    ["item", "구분", "", ["외관", "마감", "설비", "누수흔적", "변형", "기타"]], ["desc", "내용", "", null]] },
};
// ---- 균열검토: 종류별 번호 (CR1, LK1 …) · 입력 항목
const CRACK_TYPES = [               // 손상종류 8개 (버튼 순서)
  { k: "균열", code: "CR", f: ["crack_w", "crack_l"] }, { k: "누수", code: "LK", f: ["leak_w", "leak_l"] },
  { k: "백화", code: "EF", f: ["ar_b", "ar_l"] }, { k: "철근노출", code: "RB", f: ["rebar_l"] },
  { k: "박리/박락", code: "SP", f: ["dmg_b", "dmg_d"] }, { k: "열화", code: "DT", f: ["ar_b", "ar_l"] },
  { k: "이질재이격", code: "SG", f: ["gap_w", "gap_l"] }, { k: "기타", code: "ET", f: [] }];
const CRACK_LEGACY = [              // 예전 기록 표시용 (버튼에는 없음)
  { k: "보 미장균열", code: "PB", f: ["crack_w", "crack_l"] }, { k: "기둥 미장균열", code: "PC", f: ["crack_w", "crack_l"] },
  { k: "벽 미장균열", code: "PW", f: ["crack_w", "crack_l"] }, { k: "파손", code: "DM", f: ["dmg_b", "dmg_d"] }];
const CRACK_BY = Object.fromEntries([...CRACK_TYPES, ...CRACK_LEGACY].map((t) => [t.k, t]));
const CRACK_MEMBERS = ["기둥", "큰보", "작은보", "슬래브", "바닥", "내력벽", "조적벽", "기타"];
const CRACK_CHIPS = { crack_w: [0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0, 2.0], crack_l: [0.2, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0],
  leak_w: [0.1, 0.2, 0.3, 0.5, 1.0], leak_l: [0.3, 0.5, 1.0, 2.0, 3.0], dmg_b: [50, 100, 150, 200, 300, 500], dmg_d: [20, 30, 50, 100, 150],
  ar_b: [0.3, 0.5, 1.0, 2.0, 3.0], ar_l: [0.3, 0.5, 1.0, 2.0, 3.0], gap_w: [1, 2, 3, 5, 10], gap_l: [0.5, 1.0, 2.0, 3.0, 5.0],
  rebar_l: [100, 200, 300, 500, 1000] };
function crackSize(fl) {
  const t = CRACK_BY[(fl || {}).ctype]; if (!t) return "";
  const v = (k) => (fl[k] !== "" && fl[k] != null ? fl[k] : "?");
  if (t.f[0] === "crack_w") return `${v("crack_w")}mm × ${v("crack_l")}m`;
  if (t.f[0] === "leak_w") return `${v("leak_w")}m × ${v("leak_l")}m`;
  if (t.f[0] === "ar_b") return `${v("ar_b")}m × ${v("ar_l")}m`;
  if (t.f[0] === "gap_w") return `${v("gap_w")}mm × ${v("gap_l")}m`;
  if (t.f[0] === "dmg_b") return `${v("dmg_b")} × ${v("dmg_d")}mm`;
  if (t.f[0] === "rebar_l") return `L=${v("rebar_l")}mm`;
  return "";
}
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
  for (const k of Object.keys(DEFAULT_PURPOSES)) S.purposes[k] = Object.assign({}, DEFAULT_PURPOSES[k], { color: (S.purposes[k] || {}).color || DEFAULT_PURPOSES[k].color });   // 기본 용도는 최신 입력 항목
  for (const k of Object.keys(DEFAULT_PURPOSES)) S.purposes[k] = Object.assign({}, S.purposes[k], { fields: DEFAULT_PURPOSES[k].fields,
    area: !!DEFAULT_PURPOSES[k].area, crack: !!DEFAULT_PURPOSES[k].crack });
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
  loadSheet(0); setMode(S.mode === "sketch" ? "sketch" : "point");
  persistSoon();
  toast(`${meta.project || ""} — 도면 ${S.sheets.length}장`);
  if (window.CO) CO.onOpen();
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
  if (window.CO) CO.mark("rec", rec.uid);
  const i = S.recs.findIndex((r) => r.uid === rec.uid);
  if (i >= 0) S.recs[i] = rec; else S.recs.push(rec);
  persistSoon();
}

function deleteRec(rec) {
  run("UPDATE surveys SET deleted=1, updated=? WHERE uid=?", [nowIso(), rec.uid]);
  if (window.CO) CO.mark("rec", rec.uid);
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
  if (rec.label && (S.purposes[rec.purpose] || {}).crack) return `crack_${namePart(rec.label)}`;      // crack_CR1_01
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
        run("INSERT OR REPLACE INTO orig (uid, path, dir, size, sent) VALUES (?,?,?,?,0)", [id, r.rel || rel, r.dir, f.size]);
        origOk = true;
      } catch (e) { toast("원본 저장 실패 — 축소본만 저장: " + (e.message || e), 4000); }
    }
    const blob = await shrinkImage(f, 1600, 0.82);
    const data = new Uint8Array(await blob.arrayBuffer());
    run("INSERT INTO photos (uid, survey_uid, name, mime, data, created) VALUES (?,?,?,?,?,?)", [id, rec.uid, `${nm}.jpg`, "image/jpeg", data, nowIso()]);
    if (window.CO) CO.mark("ph", id);
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
// 저장은 항상 내 파일 › Documents › StrCAD.
// 앱을 지우고 다시 설치하면 예전 앱이 만든 같은 이름 파일은 덮어쓸 수 없음(안드로이드 저장소 규칙) → 이름 뒤에 시각을 붙여 Documents에 저장.
// Documents 자체에 못 쓸 때만 앱 전용 폴더로.
async function saveToDevice(rel, bytes) {
  await ensureStorage();
  const DOC = "내 파일 › Documents › ", where = (r) => DOC + r.split("/").join(" › ");
  const stamp = () => { const d = new Date(); return `${String(d.getHours()).padStart(2, "0")}${String(d.getMinutes()).padStart(2, "0")}${String(d.getSeconds()).padStart(2, "0")}`; };
  const alt = rel.replace(/(\.[^./]+)?$/, (ext) => `_${stamp()}${ext || ""}`);
  let last;
  for (const r of [rel, alt]) {
    try { const uri = await writeBytesNative(r, bytes, "DOCUMENTS"); return { uri, dir: "DOCUMENTS", rel: r, where: where(r) }; }
    catch (e) { last = e; console.warn("Documents 저장 실패", r, e); }
  }
  try { const uri = await writeBytesNative(rel, bytes, "EXTERNAL"); return { uri, dir: "EXTERNAL", rel, where: "내 파일 › Android › data › kr.strcad.survey › files › " + rel.split("/").join(" › ") + "  (Documents에 저장할 수 없어 앱 폴더에 저장)" }; }
  catch (e) { throw last || e; }
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

async function saveFile(opt) {
  if (!S.db) return;
  if (!guardEdit()) return;
  saveMeta("mobile_saved", nowIso());
  const bytes = opt && opt.keys ? filteredBytes(opt.keys) : S.db.export();
  const fname = `${(S.meta.project || "현장조사").replace(/[\\/:*?"<>|]/g, "_")}_현장조사${opt && opt.suffix ? "_" + opt.suffix.replace(/[\\/:*?"<>|\s]/g, "_") : ""}_${today()}.strsv`;
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
function isPlaced(rec) { return !(rec.x == null && !rec.area && !rec.poly && rec.member == null); }
function polyRel(rec) { if (!rec.poly || rec.poly.length < 6) return null; const o = []; for (let i = 0; i + 1 < rec.poly.length; i += 2) o.push(...P(rec.poly[i], rec.poly[i + 1])); return o; }
function polyArea(flat) { let a = 0; for (let i = 0, n = flat.length / 2; i < n; i++) { const j = (i + 1) % n; a += flat[2 * i] * flat[2 * j + 1] - flat[2 * j] * flat[2 * i + 1]; } return Math.abs(a) / 2; }
function areaRect(rec) { const pl = polyRel(rec); if (pl) { const xs = pl.filter((_, i) => i % 2 === 0), ys = pl.filter((_, i) => i % 2); return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]; }
  if (!rec.area) return null; const [x0, y0] = P(rec.area[0], rec.area[1]), [x1, y1] = P(rec.area[2], rec.area[3]);
  return [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)]; }
function areaOf(rec) { const pl = polyRel(rec); if (pl) return polyArea(pl) / 1e6; const r = areaRect(rec); return r ? (r[2] - r[0]) * (r[3] - r[1]) / 1e6 : 0; }
function geom(rec) {             // → {type:'point', p} | {type:'span', a, b} in sheet-relative coords
  const ar = areaRect(rec);
  if (ar) return { type: "area", r: ar, poly: polyRel(rec), p: [(ar[0] + ar[2]) / 2, (ar[1] + ar[3]) / 2] };
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
function anchor(rec) { const g = geom(rec); if (g.type === "span") return [(g.a[0] + g.b[0]) / 2, (g.a[1] + g.b[1]) / 2];
  if (g.type === "area") { if (g.poly) { let bi = 0; for (let i = 0; i < g.poly.length; i += 2) if (g.poly[i + 1] - g.poly[i] > g.poly[bi + 1] - g.poly[bi]) bi = i; return [g.poly[bi], g.poly[bi + 1]]; } return [g.r[0], g.r[3]]; }
  return g.p; }
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
function locate(x, y, only) {     // sheet-relative point → {m, t, dxy, p, sk}
  const tol = 22 / S.view.s;
  if (!only && window.SK && SK.memberAt) {         // 스케치로 그린 보·기둥·벽체도 부재로
    const h = SK.memberAt(x, y);
    if (h) return { m: null, sk: SK.memberInfo(h.sk), p: h.p };
  }
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
function nextNo() {
  const own = window.CO && CO.active() ? S.recs.filter((r) => CO.mine(r)) : S.recs;
  return own.reduce((a, r) => Math.max(a, +r.no || 0), 0) + 1;
}

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
  for (const rec of S.recs) if (purposeVisible(rec.purpose) && ownerVisible(rec) && isPlaced(cur && rec.uid === cur.uid ? (S.edit || rec) : rec)) drawRec(rec, cur && rec.uid === cur.uid ? (S.edit || rec) : rec, cur && rec.uid === cur.uid);
  drawLeadDraft();
  if (S.areaDraft) { const [x0, y0, x1, y1] = S.areaDraft, a = w2s(Math.min(x0, x1), Math.max(y0, y1)), b = w2s(Math.max(x0, x1), Math.min(y0, y1));
    ctx.save(); ctx.strokeStyle = purposeColor(S.purpose); ctx.lineWidth = 2; ctx.setLineDash([6, 4]); ctx.strokeRect(a[0], a[1], b[0] - a[0], b[1] - a[1]);
    const A = Math.abs((x1 - x0) * (y1 - y0)) / 1e6; ctx.setLineDash([]); ctx.font = "bold 12px sans-serif"; ctx.fillStyle = purposeColor(S.purpose);
    ctx.fillText(`${(Math.abs(x1 - x0) / 1000).toFixed(2)} × ${(Math.abs(y1 - y0) / 1000).toFixed(2)} m · ${A.toFixed(1)} m²`, a[0] + 4, a[1] - 6); ctx.restore(); }
  if (S.edit && !S.recs.some((r) => r.uid === S.edit.uid) && isPlaced(S.edit)) drawRec(S.edit, S.edit, true);
  if (S.polyDraft && S.polyDraft.length) { const col = purposeColor(S.purpose), pts = S.polyDraft.map((p) => w2s(...p));
    ctx.save(); ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 2; ctx.setLineDash([6, 4]); ctx.beginPath();
    pts.forEach((v, i) => (i ? ctx.lineTo(...v) : ctx.moveTo(...v))); if (pts.length > 2) { ctx.closePath(); ctx.globalAlpha = 0.12; ctx.fill(); ctx.globalAlpha = 1; } ctx.stroke(); ctx.setLineDash([]);
    pts.forEach((v, i) => { ctx.beginPath(); ctx.arc(v[0], v[1], i ? 5 : 9, 0, 7); i ? ctx.fill() : ctx.stroke(); });
    if (S.polyDraft.length > 2) { const fl = S.polyDraft.flat(); ctx.font = "bold 12px sans-serif"; ctx.fillText(`${(polyArea(fl) / 1e6).toFixed(1)} m²`, pts[0][0] + 12, pts[0][1] - 10); }
    ctx.restore(); }
  if (S.spanStart) { const a = w2s(...S.spanStart.p); ctx.fillStyle = purposeColor(S.purpose); ctx.beginPath(); ctx.arc(a[0], a[1], 7, 0, 7); ctx.fill(); }
  if (window.NS) NS.drawCalib();
}
function arrowHead(px, py, ux, uy, L = 13, W = 5.5) {
  ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(px - ux * L - uy * W, py - uy * L + ux * W); ctx.lineTo(px - ux * L + uy * W, py - uy * L - ux * W); ctx.closePath(); ctx.fill();
}
// 지시선 미리보기 (검측점 새로 놓기 · 이동 · 복사)
function drawLeadDraft() {
  const d = S.leadDraft && S.leadDraft.b ? S.leadDraft : (S.leadPick && $("#modal").classList.contains("show") ? S.leadPick : null);
  if (!d) return;
  const [ax, ay] = w2s(...d.a), [bx, by] = d.b ? w2s(...d.b) : [ax + 26, ay - 30];
  const col = S.leadAct || d.rec ? "#f28c28" : "#334155", R = 14, L = Math.hypot(ax - bx, ay - by);
  ctx.save(); ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
  if (L > R) { ctx.beginPath(); ctx.moveTo(bx + (ax - bx) * R / L, by + (ay - by) * R / L); ctx.lineTo(ax, ay); ctx.stroke(); }
  ctx.setLineDash([]);
  if (S.leadPick && S.leadPick.mark === "arrow" && L > R) arrowHead(ax, ay, (ax - bx) / L, (ay - by) / L); else { ctx.beginPath(); ctx.arc(ax, ay, 4, 0, 7); ctx.fill(); }
  ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(bx, by, R, 0, 7); ctx.fill(); ctx.setLineDash([4, 3]); ctx.stroke(); ctx.setLineDash([]);
  ctx.fillStyle = col; ctx.font = "bold 13px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  const lr = d.rec || (S.leadAct && S.leadAct.rec);
  ctx.fillText(lr ? String(lr.label || lr.no) : "?", bx, by + 0.5); ctx.restore();
}
function drawRec(_r, rec, hl) {
  const sel = S.edit || S.sel;
  if (!hl && sel && rec.label && sel.label === rec.label && String(sel.owner || "") === String(rec.owner || "")) hl = "sib";
  const col = purposeColor(rec.purpose), g = geom(rec);
  let px, py;
  ctx.strokeStyle = col; ctx.fillStyle = col;
  const [bx, by] = w2s(...bubble(rec)), R = hl ? 15 : 13;
  if (g.type === "area") {
    const a = w2s(g.r[0], g.r[3]), b = w2s(g.r[2], g.r[1]);
    ctx.save(); ctx.beginPath();
    if (g.poly) { for (let i = 0; i < g.poly.length; i += 2) { const v = w2s(g.poly[i], g.poly[i + 1]); i ? ctx.lineTo(...v) : ctx.moveTo(...v); } ctx.closePath(); }
    else ctx.rect(a[0], a[1], b[0] - a[0], b[1] - a[1]);
    ctx.globalAlpha = hl ? 0.22 : 0.12; ctx.fill(); ctx.globalAlpha = 1;
    ctx.lineWidth = hl ? 3 : 2; ctx.setLineDash([10, 5]); ctx.stroke(); ctx.setLineDash([]);
    const fl = rec.fields || {}, w = b[0] - a[0];
    if (w > 70) { const lines = [fl.use, [fl.fin, fl.fin_t ? fl.fin_t + "mm" : ""].filter(Boolean).join(" "), fl.ceil, loadText(fl)].filter(Boolean);
      ctx.font = "bold 12px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      const cx = (a[0] + b[0]) / 2, cy = (a[1] + b[1]) / 2 - (lines.length - 1) * 8;
      lines.slice(0, Math.max(1, Math.floor((b[1] - a[1]) / 16))).forEach((t, i) => { ctx.lineWidth = 3; ctx.strokeStyle = "#fff"; ctx.strokeText(t, cx, cy + i * 16, w - 8); ctx.fillStyle = col; ctx.fillText(t, cx, cy + i * 16, w - 8); }); }
    ctx.restore(); ctx.strokeStyle = col; ctx.fillStyle = col; [px, py] = w2s(...anchor(rec));
  } else if (g.type === "span") { const a = w2s(...g.a), b = w2s(...g.b); ctx.lineWidth = hl ? 11 : 7; ctx.lineCap = "round";
    ctx.beginPath(); segTo(a, b); ctx.stroke(); ctx.lineCap = "butt"; px = (a[0] + b[0]) / 2; py = (a[1] + b[1]) / 2; }
  else { [px, py] = w2s(...g.p); if (onScreen(px, py) && rec.mark !== "arrow") { ctx.beginPath(); ctx.arc(px, py, 3.5, 0, 7); ctx.fill(); } }
  if (!onScreen(bx, by) && !onScreen(px, py)) return;
  const d = Math.hypot(px - bx, py - by);
  if (d > R) { ctx.lineWidth = 2; ctx.beginPath(); segTo([bx + (px - bx) * R / d, by + (py - by) * R / d], [px, py]); ctx.stroke();
    if (rec.mark === "arrow") arrowHead(px, py, (px - bx) / d, (py - by) / d); }
  const txt = String(rec.label || rec.no);
  ctx.font = "bold 12px sans-serif"; const hw = Math.max(R, ctx.measureText(txt).width / 2 + 8);
  const shape = (pad) => { ctx.beginPath(); if (hw > R) { const r = R + pad, w = hw + pad; ctx.moveTo(bx - w + r, by - r); ctx.lineTo(bx + w - r, by - r); ctx.arc(bx + w - r, by, r, -Math.PI / 2, Math.PI / 2);
    ctx.lineTo(bx - w + r, by + r); ctx.arc(bx - w + r, by, r, Math.PI / 2, Math.PI * 1.5); ctx.closePath(); } else ctx.arc(bx, by, R + pad, 0, 7); };
  ctx.fillStyle = "#fff"; ctx.lineWidth = hl ? 4 : 3; shape(0); ctx.fill(); ctx.stroke();
  if (hl) { ctx.strokeStyle = hl === "sib" ? "#fbbf24" : "#f59e0b"; ctx.lineWidth = 3; if (hl === "sib") ctx.setLineDash([4, 3]); shape(5); ctx.stroke(); ctx.setLineDash([]); }
  ctx.fillStyle = col; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(txt, bx, by + 0.5); ctx.textBaseline = "alphabetic";
}

// ======================================================================= touch / mouse
const ptrs = new Map(), ptrType = new Map(); let gesture = null;
// ---- 편집/뷰어 · 펜 전용 (손가락은 이동·확대만)
S.viewOnly = (() => { try { return localStorage.getItem("viewOnly") === "1"; } catch (e) { return false; } })();
S.penOnly = (() => { try { return localStorage.getItem("penOnly") !== "0"; } catch (e) { return true; } })();
function syncInputBtns() {
  const m = $("#btnEditMode"), p = $("#btnPen");
  const lab = (ic, tx) => [el("span", {}, ic), el("span", { class: "tx" }, " " + tx)];
  if (m) { m.replaceChildren(...lab(S.viewOnly ? "👁" : "✎", S.viewOnly ? "뷰어" : "편집")); m.classList.toggle("viewing", S.viewOnly); }
  if (p) { p.replaceChildren(...lab(S.penOnly ? "🖊" : "☝", S.penOnly ? "펜" : "손")); p.classList.toggle("hand", !S.penOnly); p.title = S.penOnly ? "펜 전용 — 손가락은 이동·확대만" : "손으로도 입력"; }
  document.body.classList.toggle("viewonly", S.viewOnly);
}
function setViewOnly(v) { S.viewOnly = v; try { localStorage.setItem("viewOnly", v ? "1" : "0"); } catch (e) { /* ignore */ }
  if (v) { if (S.edit && !guardEdit()) { S.viewOnly = false; return; } S.placing = null; S.spanStart = null; S.polyDraft = null; closePanel(); if (window.SK) SK.cancel(); }
  syncInputBtns(); hint(v ? "👁 뷰어 — 눌러도 입력되지 않습니다 (보기·이동·확대만)" : "✎ 편집 — 입력할 수 있습니다"); setTimeout(() => hint(""), 2200); draw(); }
function setPenOnly(v) { S.penOnly = v; try { localStorage.setItem("penOnly", v ? "1" : "0"); } catch (e) { /* ignore */ }
  syncInputBtns(); toast(v ? "🖊 펜 전용 — 손가락은 이동·확대만 (입력 안 됨)" : "☝ 손 입력 켬 — 손가락으로도 찍고 그립니다", 2600); }
let penHintAt = 0;
function penHint() { if (Date.now() - penHintAt < 4000) return; penHintAt = Date.now();
  toast("🖊 펜 전용 — 손가락은 이동·확대만. 손으로 입력하려면 위쪽 🖊 버튼을 눌러 ☝ 손으로 바꾸세요", 3000); }
cv.addEventListener("pointerdown", (e) => {
  const touch = e.pointerType === "touch";
  if (S.penOnly && touch && [...ptrType.values()].includes("pen")) return;          // 펜으로 쓰는 중 손바닥 무시
  if (S.penOnly && e.pointerType === "pen") {                                        // 펜이 닿으면 손가락 제스처는 버림
    for (const [id, t] of [...ptrType]) if (t === "touch") { ptrs.delete(id); ptrType.delete(id); }
    if (gesture && gesture.type !== "sketch") gesture = null;
  }
  cv.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, [e.offsetX, e.offsetY]); ptrType.set(e.pointerId, e.pointerType);
  const noInput = S.viewOnly || (S.penOnly && touch);
  if (ptrs.size === 1 && !noInput && S.mode === "sketch" && window.SK && !(window.NS && NS.calibrating)) { gesture = { type: "sketch", view: { ...S.view } }; SK.down(e.offsetX, e.offsetY); return; }
  if (ptrs.size === 2 && gesture && gesture.type === "sketch") SK.cancel();
  if (ptrs.size === 2 && gesture && gesture.type === "area") { S.areaDraft = null; }
  if (ptrs.size === 1 && !noInput && S.mode === "point" && S.areaPending && areaShape() === "rect" && !S.placing && !(window.NS && NS.calibrating)) {
    const [x, y] = s2w(e.offsetX, e.offsetY);
    const hit = bubbleHit(x, y);
    if (!hit) { gesture = { type: "area", x0: e.offsetX, y0: e.offsetY, w0: [x, y], moved: false }; return; }
  }
  if (ptrs.size === 1 && !noInput && S.mode === "point" && !S.placing && !S.areaPending && !S.polyDraft && !(window.NS && NS.calibrating)) {
    const [x, y] = s2w(e.offsetX, e.offsetY);           // 검측점: 누른 곳 = 점, 끌어서 놓은 곳 = 번호(지시선)
    const bh = bubbleHit(x, y);
    if (bh && S.lastBubTap && S.lastBubTap.uid === bh.uid && Date.now() - S.lastBubTap.t < 500 && isMine(bh)) {   // 두 번째 터치 + 끌기 = 지시선(번호) 옮기기
      S.lastBubTap = null; gesture = { type: "bubdrag", rec: bh, x0: e.offsetX, y0: e.offsetY, moved: false }; S.leadDraft = { a: anchor(bh), b: [x, y], rec: bh }; return;
    }
    if (S.leadAct && S.leadAct.kind === "bubble") { gesture = { type: "lead", x0: e.offsetX, y0: e.offsetY, moved: true }; S.leadDraft = { a: anchor(S.leadAct.rec), b: [x, y] }; draw(); return; }
    if (S.leadAct || !bubbleHit(x, y)) { gesture = { type: "lead", x0: e.offsetX, y0: e.offsetY, moved: false }; S.leadDraft = { a: [x, y], b: null }; return; }
  }
  if (ptrs.size === 1) {
    const [x, y] = s2w(e.offsetX, e.offsetY);
    const hit = bubbleHit(x, y);
    const g = gesture = { type: "tap", x0: e.offsetX, y0: e.offsetY, moved: false, bubble: hit && isMine(hit) && !noInput && S.mode !== "point" ? hit : null, view: { ...S.view }, noTap: S.penOnly && touch && !S.viewOnly };
    if (hit && !noInput && S.mode === "point") g.lp = setTimeout(() => {      // 번호 길게 누르기 → 이동·복사·수정
      if (gesture !== g || g.moved) return; g.longed = true; try { navigator.vibrate && navigator.vibrate(30); } catch (er) { /* ignore */ } recActions(hit); }, 500);
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
  if (gesture.type === "bubdrag") {
    if (!gesture.moved && Math.hypot(e.offsetX - gesture.x0, e.offsetY - gesture.y0) < 6) return;
    gesture.moved = true; S.leadDraft.b = s2w(e.offsetX, e.offsetY); draw(); return;
  }
  if (gesture.type === "lead") {
    if (!gesture.moved && Math.hypot(e.offsetX - gesture.x0, e.offsetY - gesture.y0) < 10) return;
    gesture.moved = true; S.leadDraft.b = s2w(e.offsetX, e.offsetY); draw(); return;
  }
  if (gesture.type === "area") {
    if (!gesture.moved && Math.hypot(e.offsetX - gesture.x0, e.offsetY - gesture.y0) < 8) return;
    gesture.moved = true; const [x, y] = s2w(e.offsetX, e.offsetY); S.areaDraft = [...gesture.w0, x, y]; draw(); return;
  }
  const dx = e.offsetX - gesture.x0, dy = e.offsetY - gesture.y0;
  if (!gesture.moved && Math.hypot(dx, dy) < 8) return;
  gesture.moved = true; clearTimeout(gesture.lp);
  if (gesture.bubble) {                         // drag a number bubble
    const rec = editTarget(gesture.bubble); const a = anchor(rec); const [x, y] = s2w(e.offsetX, e.offsetY);
    rec.bx = x - a[0]; rec.by = y - a[1]; gesture.bubbleRec = rec; draw(); return;
  }
  const v0 = gesture.view; setView(v0.s, v0.ox - dx / v0.s, v0.oy + dy / v0.s); draw();
});
function endPtr(e) {
  if (!ptrs.has(e.pointerId)) return;
  ptrs.delete(e.pointerId); ptrType.delete(e.pointerId);
  if (!gesture) return;
  if (gesture.type === "pinch") { if (ptrs.size === 0) gesture = null; return; }
  if (gesture.type === "sketch") { gesture = null; SK.up(e.offsetX, e.offsetY, e.type === "pointercancel"); return; }
  if (gesture.type === "bubdrag") {
    const g = gesture; gesture = null; const d = S.leadDraft; S.leadDraft = null;
    if (g.moved && d && e.type !== "pointercancel") {
      const rec = JSON.parse(JSON.stringify(S.recs.find((x) => x.uid === g.rec.uid) || g.rec));
      applyLead(rec, { bub: d.b }); rec.updated = nowIso(); saveRec(rec);
      if (S.sel && S.sel.uid === rec.uid && !S.edit) { S.sel = null; closePanel(); }      // 옮긴 뒤 선택 표시 없앰
      renderList();
    }
    draw(); return;
  }
  if (gesture.type === "lead") {
    const g = gesture; gesture = null; const d = S.leadDraft; S.leadDraft = null;
    if (!d || e.type === "pointercancel") { draw(); return; }
    if (!g.moved && !S.leadAct) { draw(); hint("검측점: 점을 누른 채 끌어서 번호(지시선) 위치에 놓으세요"); setTimeout(() => hint(""), 2200); return; }
    leadFinish(d.a, g.moved ? d.b : null); return;
  }
  if (gesture.type === "area") {
    const g = gesture; gesture = null; const d = S.areaDraft; S.areaDraft = null;
    if (!g.moved || !d || e.type === "pointercancel") { draw(); hint("하중조사: 끌어서 영역(사각형)을 그리세요"); setTimeout(() => hint(""), 1800); return; }
    if (Math.abs(d[2] - d[0]) * S.view.s < 12 || Math.abs(d[3] - d[1]) * S.view.s < 12) { draw(); return; }
    newAreaRec(d); return;
  }
  const g = gesture; gesture = null; clearTimeout(g.lp);
  if (g.longed) return;
  if (g.bubble && g.moved) {                     // 번호 옮기기: 저장만 하고 현장조사 창은 열지 않음
    const rec = g.bubbleRec; if (rec && !(S.edit && S.edit.uid === rec.uid)) saveRec(rec); draw(); return; }
  if (!g.moved) { if (g.noTap) { if (S.sheet && !S.placing) penHint(); else if (S.placing) tap(...s2w(e.offsetX, e.offsetY)); return; } tap(...s2w(e.offsetX, e.offsetY)); }
}
cv.addEventListener("pointerup", endPtr); cv.addEventListener("pointercancel", endPtr);
cv.addEventListener("wheel", (e) => { e.preventDefault(); const k = e.deltaY < 0 ? 1.2 : 1 / 1.2; const [wx, wy] = s2w(e.offsetX, e.offsetY);
  const s = clampS(S.view.s * k); setView(s, wx - e.offsetX / s, wy + e.offsetY / s); draw(); }, { passive: false });

function bubbleHit(x, y) {
  for (let i = S.recs.length - 1; i >= 0; i--) {
    const r = S.edit && S.edit.uid === S.recs[i].uid ? S.edit : S.recs[i];
    if (!purposeVisible(r.purpose) || !ownerVisible(r) || !isPlaced(r)) continue;
    const [bx, by] = bubble(r);
    if (Math.hypot(x - bx, y - by) * S.view.s <= 18) return S.recs[i];
  }
  return null;
}
function editTarget(rec) { return S.edit && S.edit.uid === rec.uid ? S.edit : rec; }

function tap(x, y) {
  if (!S.sheet) return;
  if (window.NS && NS.tapCalib(x, y)) return;
  if (S.placing) { placeRec(x, y); return; }
  if (S.viewOnly) {                               // 뷰어: 번호를 누르면 위치·내용만, 입력 없음
    const h = bubbleHit(x, y);
    if (h) { showRec(h.uid, true); hint(`${h.label || "#" + h.no} ${listValue(h, "summary")}`.slice(0, 60)); setTimeout(() => hint(""), 2500); }
    else if (S.sel) { S.sel = null; draw(); renderList(); }
    return;
  }
  const PP = S.purposes[S.purpose] || {};
  if (S.mode === "point" && S.areaPending && areaShape() === "poly") {
    const h0 = !S.polyDraft && bubbleHit(x, y); if (h0) { selectRec(h0.uid); return; }
    polyTap(x, y); return; }
  const hit = bubbleHit(x, y);
  if (hit && !S.spanStart && S.mode === "point") {   // 번호: 한 번 = 반응 없음, 두 번(더블) = 지시선(번호 위치) 옮기기, 길게 = 이동·복사·수정
    const now = Date.now();
    S.lastBubTap = { uid: hit.uid, t: now };      // 다음 터치를 끌면 지시선 이동 (pointerdown 'bubdrag')
    return;
  }
  if (hit && !S.spanStart) { selectRec(hit.uid); return; }
  if (S.mode === "view") { if (!guardEdit()) return; S.sel = null; closePanel(); draw(); renderList(); return; }
  if (S.mode === "point") { if (S.sel) { S.sel = null; closePanel(); renderList(); draw(); } return; }   // 새 검측점은 끌어서 (leadFinish)
  if (PP.crack || PP.area || S.purpose === "기타") { const L = locate(x, y); newRec(L.m, L.t ?? null, null, L.p, L.dxy); return; }
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

// ---- 검측점 새로 놓기: 끌어서 번호 위치 → 점/화살표 → 용도
function skSurvey(sk, info) {       // 목록의 '검측 안됨' 부재 길게 누르기 → 그 부재에 검측점 추가
  if (!guardEdit()) return;
  sheet((b) => {
    const close = () => $("#modal").classList.remove("show");
    b.append(el("h3", {}, `${info.label} (스케치)`), el("p", { class: "small" }, `크기 ${info.b || "?"}${info.h ? "×" + info.h : ""} · 아직 검측하지 않은 부재입니다.`),
      el("div", { class: "btns" }, el("button", { class: "b gray", onclick: () => { close(); SK.focusUid(sk.uid); } }, "위치 보기"), el("span", { class: "sp" }),
        el("button", { class: "b ok", onclick: () => { close();
          const c = SK.centerOf(sk), pu = Object.keys(S.purposes).find((k) => S.purposes[k].size) || "부재검측"; S.purpose = pu;
          newRec(null, null, null, c, null, { sk: info, bub: [c[0] + 30 / S.view.s, c[1] + 36 / S.view.s], mark: "dot" }); } }, "📍 여기 검측 추가")));
  });
}
function startBubbleMove(r) {
  if (!isMine(r)) { notMineToast(r); return; }
  S.leadAct = { kind: "bubble", rec: r }; S.sel = r; buildPointOpts(); renderList(); draw();
  hint("번호를 놓을 곳을 누르거나 끌어서 놓으세요"); try { navigator.vibrate && navigator.vibrate(20); } catch (e) { /* ignore */ }
}
function leadFinish(a, b) {
  const act = S.leadAct;
  if (act) { S.leadAct = null; buildPointOpts();
    if (act.kind === "bubble") { const rec = JSON.parse(JSON.stringify(S.recs.find((x) => x.uid === act.rec.uid) || act.rec)); applyLead(rec, { bub: b || a }); rec.updated = nowIso(); saveRec(rec); hint(""); draw(); toast(`${listNo(rec)} 번호 위치 이동`); return; }
    (act.kind === "move" ? moveRecTo : copyRecTo)(act.rec, a, b); return; }
  if (!guardEdit()) { draw(); return; }
  S.leadPick = { a, b, mark: (() => { try { return localStorage.getItem("leadMark") || "dot"; } catch (e) { return "dot"; } })() };
  askLead();
}
function askLead() {
  const pk = S.leadPick; if (!pk) return;
  let step = 1;
  const close = () => { $("#modal").classList.remove("show"); S.leadPick = null; draw(); };
  sheet((b) => {
    const render = () => {
      b.innerHTML = "";
      if (step === 1) {
        b.append(el("h3", {}, "지시선 끝 모양"),
          el("div", { class: "lead-marks" }, [["dot", "●", "점"], ["arrow", "➤", "화살표"]].map(([k, ic, t]) => el("button", { class: "lead-mk" + (pk.mark === k ? " on" : ""),
            onclick: () => { pk.mark = k; try { localStorage.setItem("leadMark", k); } catch (e) { /* ignore */ } step = 2; render(); draw(); } }, el("b", {}, ic), t))),
          el("div", { class: "btns" }, el("span", { class: "sp" }), el("button", { class: "b gray", onclick: close }, "취소")));
        return;
      }
      b.append(el("h3", {}, "어떤 조사인가요?"),
        el("div", { class: "lead-purp" }, Object.keys(S.purposes).map((p) => el("button", { style: `--c:${purposeColor(p)}`, onclick: () => { $("#modal").classList.remove("show"); leadCreate(p); } }, p))),
        el("div", { class: "btns" }, el("button", { class: "b gray", onclick: () => { step = 1; render(); } }, "‹ 끝 모양"), el("span", { class: "sp" }), el("button", { class: "b gray", onclick: close }, "취소")));
    };
    render();
  });
  draw();
}
function leadCreate(purpose) {
  const pk = S.leadPick; S.leadPick = null; if (!pk) return;
  const P = S.purposes[purpose] || {}, lead = { bub: pk.b || null, mark: pk.mark };
  if (!lead.bub) { lead.bub = [pk.a[0] + 26 / S.view.s, pk.a[1] + 30 / S.view.s]; }
  S.purpose = purpose;
  if (P.area) {                                    // 하중조사: 이어서 영역을 그림 (번호는 끌어 놓은 곳)
    S.areaPending = Object.assign({ purpose }, lead); buildPointOpts(); draw();
    hint(areaShape() === "poly" ? "하중 영역: 꼭짓점을 차례로 누르고 ✔ 완료" : "하중 영역: 끌어서 사각형을 그리세요"); setTimeout(() => hint(""), 2600); return;
  }
  const L = locate(pk.a[0], pk.a[1]);
  if (P.crack) { crackAdd(Object.assign({}, L, { lead })); return; }
  newRec(L.m, L.t ?? null, null, L.p, L.dxy, Object.assign(lead, { sk: L.sk }));
}
// ---- 번호 길게 누르기: 이동 · 복사 · 수정
function recActions(r) {
  const mine = isMine(r), close = () => $("#modal").classList.remove("show");
  S.sel = r; renderList(); draw();
  sheet((b) => {
    b.append(el("h3", {}, `${listNo(r)} ${r.purpose}` + (r.name ? ` · ${r.name}` : "")), el("p", { class: "small" }, summary(r) || ""));
    if (!mine) { b.append(el("p", { class: "small" }, `👁 ${window.CO ? CO.ownerName(r) : r.inspector} 님 기록 — 보기만 가능합니다`),
      el("div", { class: "btns" }, el("span", { class: "sp" }), el("button", { class: "b gray", onclick: close }, "닫기"), el("button", { class: "b ok", onclick: () => { close(); selectRec(r.uid, true); } }, "👁 보기"))); return; }
    const big = (ic, t, sub, fn) => el("button", { class: "act-btn", onclick: () => { close(); fn(); } }, el("b", {}, ic), el("span", {}, t), el("small", {}, sub));
    b.append(el("div", { class: "act-row" },
      big("✥", "이동", "누른 곳으로 옮김", () => { S.leadAct = { kind: "move", rec: r }; buildPointOpts(); hint("옮길 위치를 누르세요 (끌면 번호 위치도 새로)"); }),
      big("⧉", "복사", "같은 번호·내용으로 하나 더", () => { S.leadAct = { kind: "copy", rec: r }; buildPointOpts(); hint("복사할 위치를 누르고 끌어서 번호를 놓으세요"); }),
      big("✎", "수정", "조사 내용 고치기", () => { selectRec(r.uid, true); beginEdit(); renderForm(); })),
      el("div", { class: "btns" }, el("button", { class: "b danger", onclick: () => { close(); S.sel = r; delCurrent(); } }, "삭제"), el("span", { class: "sp" }), el("button", { class: "b gray", onclick: close }, "닫기")));
  });
}
function placeAtPoint(rec, a, b, keepBubble) {     // 점 위치(+번호 위치)로 rec 옮기기 — 사본에도 씀
  const g0 = geom(rec), an0 = anchor(rec), off = [rec.bx || 0, rec.by || 0];
  if (g0.type === "area") {
    const dx = a[0] - an0[0], dy = a[1] - an0[1];
    if (rec.area) rec.area = [rec.area[0] + dx, rec.area[1] + dy, rec.area[2] + dx, rec.area[3] + dy];
    if (rec.poly) rec.poly = rec.poly.map((v, i) => Math.round(v + (i % 2 ? dy : dx)));
    rec.x = (rec.x || 0) + dx; rec.y = (rec.y || 0) + dy;
  } else {
    const L = locate(a[0], a[1]), [ax, ay] = A(...L.p), oldM = S.sheet.byId.get(rec.member);
    const autoName = !rec.name || (oldM && rec.name === memberName(oldM));
    Object.assign(rec, { member: L.m ? L.m.i : null, t0: L.t ?? null, t1: null, x: ax, y: ay });
    if (L.dxy) { rec.dx = L.dxy[0]; rec.dy = L.dxy[1]; } else { delete rec.dx; delete rec.dy; }
    if (autoName && L.m) rec.name = memberName(L.m);
    if (L.sk) applySk(rec, L.sk); else delete rec.skm;
  }
  if (b) applyLead(rec, { bub: b }); else if (keepBubble) { rec.bx = off[0]; rec.by = off[1]; }
}
function moveRecTo(r, a, b) {
  if (!isMine(r)) { notMineToast(r); return; }
  const rec = JSON.parse(JSON.stringify(S.recs.find((x) => x.uid === r.uid) || r));
  if (geom(rec).type === "span") { toast("구간 기록은 이동할 수 없습니다 — 삭제 후 다시 그리세요"); return; }
  placeAtPoint(rec, a, b, true); rec.updated = nowIso();
  saveRec(rec); S.sel = rec; renderList(); draw(); toast(`${listNo(rec)} 이동`);
}
function copyRecTo(r, a, b) {
  if ((S.purposes[r.purpose] || {}).crack && r.label) {       // 균열: 같은 번호 위치 추가 (개소 집계)
    S.placing = r.uid; S.placingRec = r; S.placingAdd = true; placeRec(a[0], a[1], b ? { bub: b } : null); return; }
  const src = S.recs.find((x) => x.uid === r.uid) || r;
  if (geom(src).type === "span") { toast("구간 기록은 복사할 수 없습니다"); return; }
  const root = src.copyOf || src.uid;
  const sub = Math.max(0, ...S.recs.filter((x) => x.copyOf === root).map((x) => +x.sub || 0)) + 1;
  const rec = JSON.parse(JSON.stringify(src));
  Object.assign(rec, { id: S.recs.reduce((m, x) => Math.max(m, x.id || 0), 0) + 1, uid: uid(), updated: nowIso(), copyOf: root, sub,
    photos: [], date: today(), inspector: inspector(), mobile: true });
  delete rec.owner; delete rec.calc; if (window.CO) CO.stamp(rec);
  placeAtPoint(rec, a, b, true);
  saveRec(rec); S.sel = rec; renderList(); draw(); toast(`${listNo(rec)} 복사 — 도면에는 같은 번호 ${rec.no}`);
}
// 목록 번호: 복사본은 번호-01, -02 … (원본은 번호-00), 도면에는 같은 번호
function listNo(r) {
  const pad = (n) => String(n).padStart(2, "0");
  if (r.copyOf) return `${r.no}-${pad(r.sub || 1)}`;
  if (S.recs.some((x) => x.copyOf === r.uid)) return `${r.no}-00`;
  return r.label || String(r.no);
}

// ---- 하중조사 영역 모양: 사각형(끌기) / 다각형(점 찍기)
function areaShape() { try { return localStorage.getItem("areaShape") === "poly" ? "poly" : "rect"; } catch (e) { return "rect"; } }
function setAreaShape(v) { try { localStorage.setItem("areaShape", v); } catch (e) { /* ignore */ } S.polyDraft = null; buildPointOpts(); draw();
  hint(v === "poly" ? "다각형: 꼭짓점을 차례로 누르고, 첫 점을 누르거나 ✔ 완료" : "사각형: 끌어서 영역을 그리세요"); setTimeout(() => hint(""), 2200); }
function polyTap(x, y) {
  const d = S.polyDraft || (S.polyDraft = []);
  let p = [x, y];
  if (window.SK && SK.snapPoint) { const sp = SK.snapPoint(x, y); if (sp) p = sp.p; }
  if (d.length >= 3 && Math.hypot(p[0] - d[0][0], p[1] - d[0][1]) * S.view.s < 16) { polyFinish(); return; }
  d.push(p); buildPointOpts(); draw();
  hint(d.length < 3 ? `꼭짓점 ${d.length}개 — 계속 누르세요` : `꼭짓점 ${d.length}개 — 첫 점을 누르거나 ✔ 완료`);
}
function polyFinish() {
  const d = S.polyDraft; if (!d || d.length < 3) { toast("꼭짓점을 3개 이상 찍으세요"); return; }
  S.polyDraft = null; hint(""); buildPointOpts();
  if (polyArea(d.flat()) * S.view.s * S.view.s < 150) { draw(); toast("영역이 너무 작습니다"); return; }
  newAreaRec(null, d);
}
// 위치(locate 결과)에 바로 놓기 — 도면을 눌러 연 균열 창에서 기존 번호 고를 때
function placeAt(L) { placeRec(L.p[0], L.p[1]); }
// ---- 균열 목록에서 만든 번호를 도면에 놓기
function placeRec(x, y, lead) {
  const src = S.recs.find((r) => r.uid === S.placing) || S.placingRec; S.placing = null; S.placingRec = null; hint("");
  if (!src) { draw(); return; }
  let rec = src;
  if (S.placingAdd && isPlaced(src)) {            // 같은 균열번호를 다른 위치에 하나 더 (개수 집계)
    rec = JSON.parse(JSON.stringify(src));
    Object.assign(rec, { id: S.recs.reduce((a, r) => Math.max(a, r.id || 0), 0) + 1, uid: uid(), no: nextNo(), name: "", date: today(), inspector: inspector(), photos: [] });
    delete rec.calc;
    if (window.CO) CO.stamp(rec);
  }
  S.placingAdd = false;
  const L = locate(x, y), [ax, ay] = A(...L.p);
  Object.assign(rec, { member: L.m ? L.m.i : null, t0: L.t ?? null, t1: null, x: ax, y: ay, bx: 26 / S.view.s, by: 30 / S.view.s });
  if (L.dxy) { rec.dx = L.dxy[0]; rec.dy = L.dxy[1]; } else { delete rec.dx; delete rec.dy; }
  if (!rec.name && L.m) rec.name = memberName(L.m);
  applyLead(rec, lead);
  saveRec(rec); if (S.edit && S.edit.uid === rec.uid) S.edit = JSON.parse(JSON.stringify(rec));
  const added = rec !== src;
  renderList(); draw();
  if (added) { selectRec(rec.uid); toast(`${rec.label} 위치 추가 — 지금 ${crackCount(rec.label, rec.owner)}곳 · 이 위치 사진을 찍으세요`, 3000); return; }
  toast(rec.label ? `${rec.label} 배치 — 지금 ${crackCount(rec.label, rec.owner)}곳` : `#${rec.no} 배치 완료`);
}
// 같은 균열번호(같은 검토자)의 모든 위치 — 도면 전체
function crackSiblings(label, owner) {
  const out = [];
  for (const r of q("SELECT sheet_id, rec FROM surveys WHERE deleted=0")) {
    let o; try { o = JSON.parse(r.rec); } catch (e) { continue; }
    if (o.label === label && String(o.owner || "") === String(owner || "")) { o._sheet = r.sheet_id; out.push(o); }
  }
  return out;
}
function crackCount(label, owner) { return crackSiblings(label, owner).filter(isPlaced).length; }
// 크기·형태·메모를 고치면 같은 번호의 다른 위치에도 똑같이 (사진은 위치마다 따로)
function syncCrackSiblings(rec) {
  if (!rec.label || !(S.purposes[rec.purpose] || {}).crack) return;
  for (const o of crackSiblings(rec.label, rec.owner)) {
    if (o.uid === rec.uid) continue;
    const sh = o._sheet; delete o._sheet;
    Object.assign(o, { fields: JSON.parse(JSON.stringify(rec.fields || {})), memo: rec.memo, updated: nowIso() });
    run("UPDATE surveys SET rec=?, updated=? WHERE uid=?", [JSON.stringify(o), o.updated, o.uid]);
    if (window.CO) CO.mark("rec", o.uid);
    const i = S.recs.findIndex((r) => r.uid === o.uid); if (i >= 0 && S.sheet && S.sheet.id === sh) S.recs[i] = o;
  }
}
function startPlacing(rec, add) {
  if (!guardEdit()) return;
  if (!isMine(rec)) { notMineToast(rec); return; }
  if (S.mode === "sketch") $("#modeSeg").querySelector('[data-mode="point"]').click();
  S.placing = rec.uid; S.placingRec = rec; S.placingAdd = !!add; closePanel(); draw();
  if (add && rec.label) { hint(`도면에서 ${rec.label} 위치를 하나 더 누르세요 (지금 ${crackCount(rec.label, rec.owner)}곳)`); return; }
  hint(`도면에서 ${rec.label || "#" + rec.no} 위치를 누르세요`);
}
function crackNextNo(code) {
  let mx = 0;
  for (const r of q("SELECT rec FROM surveys WHERE deleted=0")) { try { const o = JSON.parse(r.rec); const m = new RegExp("^" + code + "(\\d+)$").exec(o.label || ""); if (m) mx = Math.max(mx, +m[1]); } catch (e) { /* ignore */ } }
  for (const r of S.recs) { const m = new RegExp("^" + code + "(\\d+)$").exec(r.label || ""); if (m) mx = Math.max(mx, +m[1]); }
  return mx + 1;
}
// 균열·누수·파손·철근노출 추가: 종류 → 크기 → 사진(여러 장, crack_번호_00) → 저장 / 도면에 배치
function crackAdd(at) {
  if (!guardEdit()) return;
  if (!inspector() && !S.askedInsp) { S.askedInsp = true; askInspector(); }
  const purpose = Object.keys(S.purposes).find((k) => S.purposes[k].crack) || "균열검토";
  const rec = { id: S.recs.reduce((a, r) => Math.max(a, r.id || 0), 0) + 1, uid: uid(), updated: nowIso(), no: nextNo(),
    purpose, member: null, t0: null, t1: null, x: null, y: null, bx: 26 / S.view.s, by: 30 / S.view.s,
    name: "", size_b: "", size_h: "", length: "", rebar: {}, exist: "", fields: {}, photos: [], memo: "", date: today(), mobile: true, inspector: inspector() };
  if (window.CO) CO.stamp(rec);
  let type = null;
  const close = () => $("#modal").classList.remove("show");
  const drop = () => { for (const id of rec.photos) { run("DELETE FROM photos WHERE uid=?", [id]); run("DELETE FROM orig WHERE uid=?", [id]); } };
  sheet((b) => {
    const render = () => {
      b.innerHTML = "";
      if (!type) {
        const mineLabels = [...new Map(S.recs.filter((r) => r.label && isMine(r) && (S.purposes[r.purpose] || {}).crack).map((r) => [r.label, r])).values()];
        if (at && mineLabels.length) b.append(el("h3", {}, "기존 번호를 여기에 하나 더"), el("div", { class: "sk-chips crack-exist" }, mineLabels.map((r) => el("button", { onclick: () => {
          close(); S.placing = r.uid; S.placingRec = r; S.placingAdd = isPlaced(r); placeRec(at.p[0], at.p[1], at.lead); } }, `${r.label} ${r.fields.ctype || ""} · ${crackCount(r.label, r.owner)}곳`))));
        b.append(el("h3", {}, mineLabels.length && at ? "새 번호 만들기" : "균열·손상 종류"), el("div", { class: "grid crack-types" }, CRACK_TYPES.map((t) => el("button", { class: "opt",
          onclick: () => { type = t; rec.fields.ctype = t.k; rec.label = t.code + crackNextNo(t.code); render(); } }, el("b", {}, t.k), el("small", {}, t.code + crackNextNo(t.code))))),
          el("div", { class: "btns" }, el("span", { class: "sp" }), el("button", { class: "b gray", onclick: close }, "취소")));
        return;
      }
      b.append(el("h3", {}, `${rec.label} · ${type.k}`), el("div", { class: "lab8" }, "부재"),
        el("div", { class: "btn8" }, CRACK_MEMBERS.map((t) => el("button", { class: rec.fields.cmem === t ? "on" : "", onclick: () => { rec.fields.cmem = rec.fields.cmem === t ? "" : t; render(); } }, t))));
      for (const k of type.f) {
        const def = DEFAULT_PURPOSES["균열검토"].fields.find((f) => f[0] === k) || [k, k, ""];
        const inp = el("input", { type: "number", class: "sk-num", inputmode: "decimal", step: "any", value: rec.fields[k] ?? "" });
        inp.oninput = () => { rec.fields[k] = inp.value; };
        b.append(el("div", { class: "sk-numrow" }, el("span", { class: "sk-lab" }, `${def[1]} (${def[2]})`), inp,
          el("div", { class: "sk-chips" }, (CRACK_CHIPS[k] || []).map((c) => el("button", { class: String(c) === String(rec.fields[k]) ? "on" : "", onclick: () => { rec.fields[k] = String(c); render(); } }, String(c))))));
      }
      if (type.f[0] === "crack_w") {
        const sh = el("div", { class: "sk-chips" }, ["수직", "수평", "경사", "망상", "기타"].map((c) => el("button", { class: rec.fields.shape === c ? "on" : "", onclick: () => { rec.fields.shape = rec.fields.shape === c ? "" : c; render(); } }, c)));
        b.append(el("div", { class: "sk-numrow" }, el("span", { class: "sk-lab" }, "형태"), sh));
      }
      const ph = el("div", { class: "photos" });
      for (const id of rec.photos) { const u = photoURL(id); ph.append(el("div", { class: "ph" }, u ? el("img", { src: u }) : "?",
        el("button", { class: "del", onclick: () => { rec.photos = rec.photos.filter((x) => x !== id); run("DELETE FROM photos WHERE uid=?", [id]); render(); } }, "✕"))); }
      const cam = el("input", { type: "file", accept: "image/*", capture: "environment", hidden: "" });
      const gal = el("input", { type: "file", accept: "image/*", multiple: "", hidden: "" });
      const onFiles = async (ev) => { const ids = await addPhotoFiles([...ev.target.files], rec); rec.photos.push(...ids); ev.target.value = ""; render(); };
      cam.onchange = onFiles; gal.onchange = onFiles;
      b.append(el("div", { class: "row two" }, el("div", { class: "lab" }, `사진 ${rec.photos.length}장`),
        el("button", { class: "val", onclick: () => cam.click() }, "📷 촬영"), el("div"), el("button", { class: "val", onclick: () => gal.click() }, "🖼 앨범")),
        el("p", { class: "small" }, `사진 이름: crack_${rec.label}_01, _02 …`), cam, gal, ph, notesBox(rec, true, () => rec, render));
      const save = (place) => {
        if (at) { const [ax, ay] = A(...at.p); Object.assign(rec, { member: at.m ? at.m.i : null, t0: at.t ?? null, x: ax, y: ay, name: at.m ? memberName(at.m) : "" }); if (at.dxy) { rec.dx = at.dxy[0]; rec.dy = at.dxy[1]; } applyLead(rec, at.lead); if (at.sk) applySk(rec, at.sk); }
        saveRec(rec); close(); renderList(); draw();
        toast(`${rec.label} ${type.k} ${crackSize(rec.fields)} 저장` + (rec.photos.length ? ` · 사진 ${rec.photos.length}장` : ""));
        if (place) startPlacing(rec);
      };
      b.append(el("div", { class: "btns" },
        el("button", { class: "b gray", onclick: () => { type = null; delete rec.label; render(); } }, "‹ 종류"),
        el("span", { class: "sp" }), el("button", { class: "b gray", onclick: () => { drop(); close(); } }, "취소"),
        at ? el("button", { class: "b ok", onclick: () => save(false) }, "💾 저장") :
          [el("button", { class: "b edit", onclick: () => save(false) }, "저장"), el("button", { class: "b ok", onclick: () => save(true) }, "저장 후 도면에 배치")]));
    };
    render();
  });
}

function newAreaRec(d, poly) {
  if (!guardEdit()) return;
  if (!inspector() && !S.askedInsp) { S.askedInsp = true; askInspector(); }
  if (poly) { const xs = poly.map((p) => p[0]), ys = poly.map((p) => p[1]); d = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]; }
  const [x0, y0] = A(Math.min(d[0], d[2]), Math.min(d[1], d[3])), [x1, y1] = A(Math.max(d[0], d[2]), Math.max(d[1], d[3]));
  const rec = { id: S.recs.reduce((a, r) => Math.max(a, r.id || 0), 0) + 1, uid: uid(), updated: nowIso(), no: nextNo(),
    purpose: S.purpose, member: null, t0: null, t1: null, x: (x0 + x1) / 2, y: (y0 + y1) / 2, area: [x0, y0, x1, y1],
    bx: -14 / S.view.s, by: 14 / S.view.s, name: "", size_b: "", size_h: "", length: "", rebar: {}, exist: "", fields: {},
    photos: [], memo: "", date: today(), mobile: true, inspector: inspector() };
  if (window.CO) CO.stamp(rec);
  if (poly) { rec.poly = poly.flatMap((p) => A(...p)).map((v) => Math.round(v)); const c = poly.reduce((a, p) => [a[0] + p[0] / poly.length, a[1] + p[1] / poly.length], [0, 0]); [rec.x, rec.y] = A(...c); }
  if (S.areaPending) { applyLead(rec, S.areaPending); S.areaPending = null; buildPointOpts(); }
  saveRec(rec);
  S.sel = rec; S.edit = JSON.parse(JSON.stringify(rec));
  openPanel(); renderForm(); renderList(); draw();
}

// ---- 용도별 도면 표시 (부재검측 / 균열검토 / 하중조사 … 따로 또는 같이)
function hiddenPurposes() { try { return new Set(JSON.parse(localStorage.getItem("hidePurposes") || "[]")); } catch (e) { return new Set(); } }
function purposeVisible(p) { return !hiddenPurposes().has(p); }
// ---- 검토자별 보기 켬/끔 (👤 버튼)
function ownerKey(o) { return o.owner ? "@" + o.owner : "~" + (o.inspector || ""); }
let _hidOwn = null;
function hiddenOwners() { if (_hidOwn) return _hidOwn; try { _hidOwn = new Set(JSON.parse(localStorage.getItem("hideOwners") || "[]")); } catch (e) { _hidOwn = new Set(); } return _hidOwn; }
function ownerVisible(o) { const h = hiddenOwners(); return !h.size || !h.has(ownerKey(o)); }
function setHiddenOwners(set) { _hidOwn = set; try { localStorage.setItem("hideOwners", JSON.stringify([...set])); } catch (e) { /* ignore */ }
  if (S.sel && !ownerVisible(S.sel)) { S.sel = null; closePanel(); } draw(); renderList(); }
function showInspectors() {
  const meKey = window.CO && CO.me() ? "@" + CO.me().login : "~" + inspector();
  const people = new Map();
  const add = (o, t) => { const k = ownerKey(o); if (!people.has(k)) people.set(k, { k, name: (o.owner && window.CO ? CO.ownerName(o) : o.inspector) || o.inspector || "(이름 없음)", rec: 0, sk: 0 }); if (t) people.get(k)[t]++; };
  add(window.CO && CO.me() ? { owner: CO.me().login, inspector: CO.me().name } : { inspector: inspector() });
  for (const r of S.recs) add(r, "rec");
  if (window.SK) for (const k of SK.list) add(k, "sk");
  const pal = ["#2563eb", "#e11d48", "#16a34a", "#f28c28", "#7c3aed", "#0891b2", "#ca8a04", "#db2777"];
  sheet((b) => {
    const render = () => {
      b.innerHTML = ""; const hid = hiddenOwners();
      const list = [...people.values()].sort((a, c) => (c.k === meKey) - (a.k === meKey) || a.name.localeCompare(c.name));
      const box = el("div", { class: "lay-box" });
      list.forEach((p, i) => { const on = !hid.has(p.k);
        box.append(el("button", { class: "lay" + (on ? " on" : ""), style: `--c:${pal[i % pal.length]}`, onclick: () => { const h = new Set(hiddenOwners()); if (on) h.add(p.k); else h.delete(p.k); setHiddenOwners(h); render(); } },
          el("i"), `👤 ${p.name}${p.k === meKey ? " (나)" : ""}`, el("small", {}, `검측 ${p.rec} · 스케치 ${p.sk}`))); });
      const co = window.CO && CO.me();
      b.append(el("h3", {}, "👥 검토자 — 도면에 보기 켬/끔"),
        el("p", { class: "small" }, co ? `${CO.me().name} 님 로그인${CO.active() ? " · 협업 중" : ""} — 끄면 그 사람의 검측점·스케치가 도면과 목록에서 숨겨집니다.` : "끄면 그 사람의 검측점·스케치가 도면과 목록에서 숨겨집니다."),
        box,
        el("div", { class: "btns" },
          el("button", { class: "b gray", onclick: () => { setHiddenOwners(new Set()); render(); } }, "모두 보기"),
          el("button", { class: "b gray", onclick: () => { setHiddenOwners(new Set(list.map((p) => p.k).filter((k) => k !== meKey))); render(); } }, "나만 보기"),
          el("span", { class: "sp" }),
          co ? el("button", { class: "b edit", onclick: () => { $("#modal").classList.remove("show"); CO.hub(); } }, "👥 협업 창") :
            el("button", { class: "b edit", onclick: () => { $("#modal").classList.remove("show"); askInspector(); } }, "이름 변경"),
          el("button", { class: "b ok", onclick: () => $("#modal").classList.remove("show") }, "닫기")));
    };
    render();
  });
}
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
      if (window.SK) { const on = !SK.hidden();
        box.append(el("button", { class: "lay" + (on ? " on" : ""), style: "--c:#e11d48", onclick: () => { SK.setHidden(on); render(); } },
          el("i"), "✎ 스케치 전체", el("small", {}, `${SK.list.length}개`)));
        const ls = SK.layerStats();
        if (ls.kinds.length) box.append(el("div", { class: "lay-sec" }, "스케치 — 종류별"), el("div", { class: "lay-grid" + (on ? "" : " dim") },
          ls.kinds.map((k) => el("button", { class: "lay sm" + (k.on ? " on" : ""), style: "--c:#2563eb", onclick: () => { SK.setLayer("kind", k.key, !k.on); render(); } },
            el("i"), k.name, el("small", {}, String(k.n))))));
        if (ls.colors.length) box.append(el("div", { class: "lay-sec" }, "스케치 — 색깔별"), el("div", { class: "lay-grid" + (on ? "" : " dim") },
          ls.colors.map((c) => el("button", { class: "lay sm" + (c.on ? " on" : ""), style: `--c:${c.key}`, onclick: () => { SK.setLayer("color", c.key, !c.on); render(); } },
            el("i"), ({ "#e11d48": "빨강", "#f28c28": "주황", "#eab308": "노랑", "#16a34a": "초록", "#2563eb": "파랑", "#7c3aed": "보라", "#111827": "검정", "#ec4899": "분홍" })[c.key] || "",
            el("small", {}, String(c.n))))));
      }
    };
    const box = el("div", { class: "lay-box" });
    b.append(el("h3", {}, "도면에 표시할 조사"), box,
      el("div", { class: "btns" },
        el("button", { class: "b gray", onclick: () => { hid.clear(); try { localStorage.setItem("hidePurposes", "[]"); } catch (e) { /* ignore */ } if (window.SK) { SK.setHidden(false); SK.showAllLayers(); } render(); draw(); } }, "모두 보기"),
        el("span", { class: "sp" }), el("button", { class: "b ok", onclick: () => $("#modal").classList.remove("show") }, "닫기")));
    render();
  });
}

function applySk(rec, info) {      // 스케치 부재 연결: 이름·크기 공유
  if (!info) { delete rec.skm; return; }
  rec.skm = info.uid; rec.name = info.label; rec.exist = rec.exist || "존재";
  if ((S.purposes[rec.purpose] || {}).size) { rec.size_b = info.b; if (info.kind === "column") rec.size_h = info.h; }
}
function applyLead(rec, o) {      // 끌어서 정한 번호 위치(sheet-relative) · 점/화살표
  if (!o) return;
  if (o.bub) { const an = anchor(rec); rec.bx = o.bub[0] - an[0]; rec.by = o.bub[1] - an[1]; }
  if (o.mark) rec.mark = o.mark;
}
function newRec(m, t0, t1, p, dxy, lead) {
  if (!guardEdit()) return;
  if (!inspector() && !S.askedInsp) { S.askedInsp = true; askInspector(); }
  const [ax, ay] = A(...p);
  const rec = { id: S.recs.reduce((a, r) => Math.max(a, r.id || 0), 0) + 1, uid: uid(), updated: nowIso(), no: nextNo(),
    purpose: S.purpose, member: m ? m.i : null, t0, t1, x: ax, y: ay, bx: 26 / S.view.s, by: 30 / S.view.s,
    name: memberName(m), size_b: "", size_h: "", length: "", rebar: {}, exist: m || (S.purposes[S.purpose] || {}).exist ? "존재" : "", fields: {},
    photos: [], memo: "", date: today(), mobile: true, inspector: inspector() };
  if (window.CO) CO.stamp(rec);
  if (dxy) { rec.dx = dxy[0]; rec.dy = dxy[1]; }
  applyLead(rec, lead);
  if (lead && lead.sk) applySk(rec, lead.sk);
  saveRec(rec);
  S.sel = rec; S.edit = JSON.parse(JSON.stringify(rec));
  openPanel(); renderForm(); renderList(); draw();
  if (!m && !rec.skm && (S.sheet.members.length || (window.SK && SK.list.length))) toast("부재가 없는 위치 — 좌표만 기록합니다");
}

// ======================================================================= selection / panel
// ---- 목록 줄: 누르면 위치만 표시(한 번 더 누르면 해제), 길게 누르면 수정·삭제 버튼
function rowGestures(tr, onTap, onLong) {
  let t = null, longed = false;
  tr.addEventListener("pointerdown", () => { longed = false; clearTimeout(t); t = setTimeout(() => { longed = true; try { navigator.vibrate && navigator.vibrate(25); } catch (e) { /* ignore */ } onLong(); }, 500); });
  for (const ev of ["pointerup", "pointerleave", "pointercancel"]) tr.addEventListener(ev, () => clearTimeout(t));
  tr.addEventListener("contextmenu", (e) => e.preventDefault());
  tr.addEventListener("click", (e) => { if (longed || e.target.closest("button")) return; onTap(); });
}
function showRec(u, keep) {              // 창을 열지 않고 위치만 (선택 표시)
  if (S.edit && !guardEdit()) return;
  if (!keep && S.sel && S.sel.uid === u && $("#panel").classList.contains("hidden")) { S.sel = null; S.rowMenu = null; renderList(); draw(); return; }
  S.sel = S.recs.find((r) => r.uid === u) || null; S.rowMenu = null;
  if (S.sel && isPlaced(S.sel)) { const a = anchor(S.sel), [sx, sy] = w2s(...a), r = cv.getBoundingClientRect();
    if (sx < 40 || sy < 40 || sx > r.width - 40 || sy > r.height - 40) { S.view.ox = a[0] - r.width / 2 / S.view.s; S.view.oy = a[1] + r.height / 2 / S.view.s; } }
  closePanel(); renderList(); draw();
}
function rowMenuRow(r, ncol, extra) {
  const mine = isMine(r);
  return el("tr", { class: "sk-rowmenu" }, el("td", { colspan: String(ncol) },
    mine ? el("button", { class: "b edit", onclick: () => { S.rowMenu = null; selectRec(r.uid, true); beginEdit(); renderForm(); } }, "✎ 수정") :
      el("button", { class: "b gray", onclick: () => { S.rowMenu = null; selectRec(r.uid, true); } }, "👁 보기"),
    mine ? el("button", { class: "b danger", onclick: () => { S.rowMenu = null; S.sel = r; delCurrent(); } }, "삭제") : "",
    extra || "",
    el("button", { class: "b gray", onclick: () => { S.rowMenu = null; renderList(); } }, "닫기"),
    el("small", {}, `${r.inspector || ""}${r.date ? " · " + r.date : ""}`)));
}
function selectRec(u, center) {
  if (S.edit && S.edit.uid !== u && !guardEdit()) return;
  S.sel = S.recs.find((r) => r.uid === u) || null;
  if (!S.sel) return;
  if (center && isPlaced(S.sel)) { const a = anchor(S.sel), [sx, sy] = w2s(...a), r = cv.getBoundingClientRect();
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
  if (confirm(`#${S.edit.no} 편집 내용을 저장할까요?\n(취소 = 저장하지 않음)`)) { saveEdit(); return !S.edit; }   // 스케치 크기 확인 창이 뜨면 대기
  S.edit = null;
  return true;
}
function isMine(r) { return !window.CO || CO.mine(r); }
function notMineToast(r) { toast(`👁 ${window.CO ? CO.ownerName(r) : ""} 님 기록 — 보기만 가능합니다`); }
function beginEdit() { if (!S.sel) return false; if (!isMine(S.sel)) { notMineToast(S.sel); return false; } if (!S.edit || S.edit.uid !== S.sel.uid) S.edit = JSON.parse(JSON.stringify(S.sel)); return true; }
function inspector() { try { return localStorage.getItem("inspector") || ""; } catch (e) { return ""; } }
function showInspector() { const b = $("#btnInsp"), n = inspector(); b.textContent = n ? `👤 ${n}` : "👤 검토자"; b.classList.toggle("none", !n); }
function askInspector() {
  const v = prompt("검토자 성함 (검측위치에 함께 기록됩니다)", inspector());
  if (v == null) return; try { localStorage.setItem("inspector", v.trim()); } catch (e) { /* private */ }
  showInspector(); toast(v.trim() ? `검토자: ${v.trim()}` : "검토자 지움");
}
function skMismatch(e) {
  if (!e || !e.skm || !window.SK || !(S.purposes[e.purpose] || {}).size) return null;
  const sk = SK.get(e.skm), info = SK.memberInfo(sk); if (!info) return null;
  const bOk = !e.size_b || String(e.size_b) === info.b, hOk = info.kind !== "column" || !e.size_h || String(e.size_h) === info.h;
  return bOk && hOk ? null : { sk, info };
}
function saveEdit() {
  const mm = skMismatch(S.edit);
  if (mm) { askSkSize(mm.sk, mm.info); return; }
  saveEdit0();
}
function askSkSize(sk, info) {      // 검측 크기 ≠ 스케치 부재 크기 → 같은 이름 전체 반영 / 이 부재만(이름 변경)
  const e = S.edit, same = SK.sameName(sk), szTxt = (b, h) => info.kind === "column" ? `${b || "?"}×${h || "?"}` : `${b || "?"}`;
  const newSz = szTxt(e.size_b, e.size_h), oldSz = szTxt(info.b, info.h);
  if (same.length <= 1) { SK.setMemberSize(sk.uid, e.size_b, e.size_h, {}); toast(`스케치 ${info.label} 크기 ${oldSz} → ${newSz}`); saveEdit0(); return; }
  let step = 1;
  sheet((b) => {
    const close = () => $("#modal").classList.remove("show");
    const render = () => {
      b.innerHTML = "";
      if (step === 1) {
        b.append(el("h3", {}, "스케치 부재와 크기가 다릅니다"),
          el("p", {}, `${info.label}: 스케치 ${oldSz} → 입력 ${newSz} mm`),
          el("button", { class: "bigbtn navy", onclick: () => { close(); SK.setMemberSize(sk.uid, e.size_b, e.size_h, { all: true }); toast(`${info.label} ${same.length}개 모두 ${newSz}`); saveEdit0(); } },
            `같은 이름 ${info.label} 전체 반영`, el("small", {}, ` (${same.length}개)`)),
          el("button", { class: "bigbtn", onclick: () => { step = 2; render(); } }, "이 부재만 바꾸기", el("small", {}, " — 이름도 바꿔야 함")),
          el("div", { class: "btns" }, el("span", { class: "sp" }), el("button", { class: "b gray", onclick: () => { close(); e.size_b = info.b; if (info.kind === "column") e.size_h = info.h; renderForm(); toast("스케치 크기로 되돌림"); } }, "취소 (되돌리기)")));
        return;
      }
      const inp = el("input", { type: "text", class: "sk-input", value: SK.nextMemberName(info.kind) });
      b.append(el("h3", {}, "이 부재만 — 새 이름"),
        el("p", { class: "small" }, `같은 이름(${info.name})은 같은 크기여야 하므로, 크기를 ${newSz}로 바꾸는 이 부재는 이름을 바꿔야 합니다.`),
        el("div", { class: "sk-numrow" }, el("span", { class: "sk-lab" }, `${info.ko} 이름`), inp),
        el("div", { class: "btns" }, el("button", { class: "b gray", onclick: () => { step = 1; render(); } }, "‹ 뒤로"), el("span", { class: "sp" }),
          el("button", { class: "b ok", onclick: () => {
            const nm = inp.value.trim(); if (!nm || nm === info.name) { toast("다른 이름을 넣으세요"); return; }
            close(); SK.setMemberSize(sk.uid, e.size_b, e.size_h, { name: nm }); e.name = `${info.ko} ${nm}`; toast(`${info.ko} ${nm} ${newSz}`); saveEdit0();
          } }, "바꾸기")));
      setTimeout(() => inp.focus(), 50);
    };
    render();
  });
}
// 스케치 부재가 바뀌면 (이름·크기) 연결된 검측 기록도 같이
window.onSkMembers = (list) => {
  if (!S.db || !list.length) return;
  const by = new Map(list.map((sk) => [sk.uid, SK.memberInfo(sk)]));
  let n = 0;
  for (const r of S.recs) {
    const info = r.skm && by.get(r.skm); if (!info) continue;
    const rec = JSON.parse(JSON.stringify(r)); applySk(rec, info);
    if (JSON.stringify(rec) === JSON.stringify(r)) continue;
    rec.updated = nowIso(); saveRec(rec); n++;
    if (S.edit && S.edit.uid === rec.uid) { applySk(S.edit, info); renderForm(); }
  }
  if (n) { renderList(); draw(); }
};
function saveEdit0() { if (!S.edit) return; if (!S.edit.inspector) S.edit.inspector = inspector(); saveRec(S.edit); syncCrackSiblings(S.edit); S.sel = S.edit; S.edit = null; toast(`#${S.sel.no} 저장`); renderForm(); renderList(); draw(); }
function cancelEdit() { S.edit = null; renderForm(); draw(); }

function summary(r) {
  const p = S.purposes[r.purpose] || {}; const parts = [];
  if (p.crack && (r.fields || {}).ctype) {
    const fl = r.fields; parts.push(`${fl.ctype} ${crackSize(fl)}`); if (fl.shape) parts.push(fl.shape); if (fl.progress) parts.push(`진행성 ${fl.progress}`);
    if (!isPlaced(r)) parts.push("📍미배치"); return parts.join(" · ");
  }
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
  if (r.poly) return `다각형 영역 · 꼭짓점 ${r.poly.length / 2}개 · ${areaOf(r).toFixed(1)} m²`;
  if (r.area) { const [a, b, c, d] = r.area; return `영역 ${((c - a) / 1000).toFixed(2)} × ${((d - b) / 1000).toFixed(2)} m · ${areaOf(r).toFixed(1)} m²`; }
  if (!isPlaced(r)) return "📍 아직 도면에 배치하지 않음 — 아래 '도면에 배치'를 누르세요";
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
  const ro = !isMine(rec);
  if (ro) f.append(el("div", { class: "ro-box" }, `👁 ${CO.ownerName(rec)} 님 기록 — 보기만 가능 (고칠 수 없음)`));
  const P = S.purposes[rec.purpose] || DEFAULT_PURPOSES["부재검측"];
  const valTxt = (v, unit) => (v !== "" && v != null ? `${v}${unit && v ? unit : ""}` : "선택");
  const row = (label, ...vals) => f.append(el("div", { class: vals.length > 1 ? "row two" : "row" }, el("div", { class: "lab" }, label), ...vals));
  const vbtn = (key, opts = {}) => el("button", { class: "val" + (editing ? "" : " dim"), onclick: () => pick(key, opts) },
    valTxt(opts.field ? (rec.fields || {})[key] : rec[key], opts.unit ?? FIELD_UNIT[key]));
  // 순서: 용도 · 번호 · 부재명(종류/이름) · 치수 · 길이 · 철근 · 부재유무 · (용도별 항목) · 사진 · 추가사항 · 조사일
  row("용도", vbtn("purpose", { choices: Object.keys(S.purposes) }));
  if (P.crack && rec.label) row("균열번호", el("div", { class: "val dim" }, rec.label));
  else row("번호", vbtn("no"));
  if (P.crack) {                                   // 균열검토: 손상종류 8 · 부재 8 버튼
    const fl = rec.fields || {};
    const grid8 = (key, items) => el("div", { class: "btn8" }, items.map((t) => el("button", { class: (fl[key] === t ? "on" : "") + (editing ? "" : " dim"),
      onclick: () => { if (!beginEdit()) return; const e = S.edit; e.fields = e.fields || {}; e.fields[key] = e.fields[key] === t && key === "cmem" ? "" : t;
        if (key === "ctype" && !e.label) e.label = CRACK_BY[t].code + crackNextNo(CRACK_BY[t].code); renderForm(); draw(); } }, t)));
    f.append(el("div", { class: "lab8" }, "손상종류" + (fl.ctype && !CRACK_TYPES.some((t) => t.k === fl.ctype) ? ` (예전: ${fl.ctype})` : "")), grid8("ctype", CRACK_TYPES.map((t) => t.k)),
      el("div", { class: "lab8" }, "부재"), grid8("cmem", CRACK_MEMBERS));
  } else if (P.area) row("구역명", vbtn("name", { choices: ["사무실", "회의실", "복도", "화장실", "계단실", "기계실", "창고", "주거", "옥상"] }));
  else { const [mk, mn] = nameParts(rec);
    row("부재명", el("button", { class: "val" + (editing ? "" : " dim"), onclick: () => pick("mkind", { choices: MEMBER_KINDS }) }, mk || "종류"),
      el("div", { class: "x" }, ""), el("button", { class: "val" + (editing ? "" : " dim"), onclick: () => pick("mname", {}) }, mn || "이름 (G1·C1…)")); }
  if (P.size) row("치수", vbtn("size_b"), el("div", { class: "x" }, "X"), vbtn("size_h"));
  if (P.length) row("길이", vbtn("length"));
  if (P.rebar) row("철근", el("button", { class: "val" + (editing ? "" : " dim"), onclick: rebarGrid }, Object.values(rec.rebar || {}).some(Boolean) ? "입력됨." : "선택"));
  if (P.exist) row("부재\n유무", vbtn("exist"));
  const ctT = P.crack ? CRACK_BY[(rec.fields || {}).ctype] : null;
  for (const [k, lab, unit, ch] of P.fields || []) {
    if (P.crack && (k === "ctype" || k === "cmem")) continue;
    if (P.crack && (!ctT || (!ctT.f.includes(k) && !(ctT.f[0] === "crack_w" && (k === "shape" || k === "progress"))))) continue;
    row(lab, vbtn(k, { field: true, unit, choices: ch || FIELD_CHOICES[k] || (CRACK_CHIPS[k] && CRACK_CHIPS[k].map(String)) }));
  }
  if (P.crack && rec.label) f.append(el("div", { class: "load-box" }, el("b", {}, `${rec.label} — 지금 ${crackCount(rec.label, rec.owner)}곳`),
    el("small", {}, "같은 번호를 여러 곳에 표시하면 개수가 집계됩니다 (크기·형태는 모든 위치 공통, 사진은 위치마다 따로 — 이 위치 사진만 여기에)")));
  if (P.crack && !ro) {
    if (isPlaced(rec)) f.append(el("div", { class: "btn-pair" }, el("button", { class: "val", onclick: () => startPlacing(rec, true) }, "📍＋ 같은 번호 위치 추가"),
      el("button", { class: "val", onclick: () => startPlacing(rec) }, "↻ 이 위치 다시 지정")));
    else f.append(el("button", { class: "val wide", onclick: () => startPlacing(rec) }, "📍 도면에 배치"));
  }
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
  if (!ro) f.append(el("div", { class: "row two" }, el("div", { class: "lab" }, "사진"),
    el("button", { class: "val", onclick: () => cam.click() }, "📷 촬영"), el("div"), el("button", { class: "val", onclick: () => gal.click() }, "🖼 앨범")), cam, gal);
  f.append(ph);
  f.append(notesBox(rec, !ro, () => { if (!beginEdit()) return null; return S.edit; }, () => renderForm()));
  f.append(el("div", { class: "row", style: "margin-top:10px" }, el("div", { class: "lab" }, "조사일"), vbtn("date", { choices: [today()] })));
  const cres = (rec.calc || {}).result;
  if (P.size) f.append(el("button", { class: "val wide input-btn" + (cres ? (cres.ok ? " ok" : " ng") : ""), onclick: () => openDetail() },
    el("b", {}, "INPUT"), el("small", {}, cres ? `${cres.ok ? "✔" : "✘"} ${cres.summary}` : "상세 입력 · 휨/전단 검토")));
  const btns = el("div", { class: "btns" }, ro ? "" : el("button", { class: "b danger", onclick: delCurrent }, "위치 삭제"), el("div", { class: "sp" }));
  if (ro) btns.append(el("button", { class: "b gray", onclick: () => { S.sel = null; closePanel(); renderList(); draw(); } }, "닫기"));
  else if (editing) btns.append(el("button", { class: "b gray", onclick: cancelEdit }, "취소"), el("button", { class: "b ok", onclick: saveEdit }, "💾 저장"));
  else btns.append(el("button", { class: "b edit", onclick: () => { beginEdit(); renderForm(); } }, "✎ 편집"));
  f.append(btns);
}
const MEMBER_KINDS = ["기둥", "거더", "보", "작은보", "벽체", "슬래브", "기초", "계단", "기타"];
function nameParts(r) {             // 부재명 → [종류, 이름]  (보 G1 → 보 / G1)
  if (r.mkind != null || r.mname != null) return [r.mkind || "", r.mname || ""];
  const n = String(r.name || "").trim(); if (!n) return ["", ""];
  const kinds = [...MEMBER_KINDS, ...Object.values(KIND_KO)].sort((a, b) => b.length - a.length);
  const k = kinds.find((x) => n === x || n.startsWith(x + " "));
  return k ? [k, n.slice(k.length).trim()] : ["", n];
}
// ---- 추가사항: 타이핑 · 스케치를 여러 개 (rec.notes) — rec.memo 에는 글만 모아 둠 (PC 호환)
function notesOf(r) { return Array.isArray(r.notes) ? r.notes : (r.memo ? [{ t: "text", text: r.memo }] : []); }
function syncMemo(r) { r.memo = (r.notes || []).filter((n) => n.t === "text" && n.text).map((n) => n.text).join("\n"); }
function notesBox(rec, canEdit, getTarget, after) {
  const box = el("div", { class: "notes" });
  const list = notesOf(rec);
  box.append(el("div", { class: "notes-head" }, el("b", {}, `추가사항${list.length ? ` ${list.length}` : ""}`),
    canEdit ? el("button", { class: "b gray", onclick: () => { const t = getTarget(); if (!t) return; typeNote(t, null, after); } }, "＋ 타이핑") : "",
    canEdit ? el("button", { class: "b gray", onclick: () => { const t = getTarget(); if (!t) return; sketchNote(t, after); } }, "＋ 스케치") : ""));
  list.forEach((n, i) => {
    const del = canEdit ? el("button", { class: "del", onclick: () => { const t = getTarget(); if (!t) return; t.notes = notesOf(t).slice(); t.notes.splice(i, 1); syncMemo(t); after(); } }, "✕") : "";
    if (n.t === "sketch") box.append(el("div", { class: "note sk" }, el("img", { src: n.img, onclick: () => showPhoto(n.img) }), del));
    else box.append(el("div", { class: "note", onclick: () => { if (!canEdit) return; const t = getTarget(); if (t) typeNote(t, i, after); } }, el("span", {}, n.text), del));
  });
  return box;
}
function overlay(build) {           // #modal 위에 겹치는 창 (균열 입력 창 안에서도 쓰려고)
  const o = el("div", { class: "modal show ov2" }), body = el("div", { class: "sheet" });
  o.append(body); document.body.append(o);
  const close = () => o.remove();
  o.addEventListener("click", (e) => { if (e.target === o) close(); });
  build(body, close); return close;
}
function typeNote(t, idx, after) {
  const cur = idx != null ? notesOf(t)[idx] : null;
  overlay((b, close) => {
    const ta = el("textarea", {}); ta.value = cur ? cur.text : "";
    b.append(el("h3", {}, "추가사항 — 타이핑"), ta, el("div", { class: "btns" }, el("span", { class: "sp" }), el("button", { class: "b gray", onclick: close }, "취소"),
      el("button", { class: "b ok", onclick: () => { const v = ta.value.trim(); t.notes = notesOf(t).slice();
        if (idx != null) { if (v) t.notes[idx] = { t: "text", text: v, d: today() }; else t.notes.splice(idx, 1); } else if (v) t.notes.push({ t: "text", text: v, d: today() });
        syncMemo(t); close(); after(); } }, "확인")));
    setTimeout(() => ta.focus(), 50);
  });
}
function sketchNote(t, after) {
  overlay((b, close) => {
    const W = Math.min(620, window.innerWidth - 48), H = Math.round(W * 0.62);
    const c = el("canvas", { width: W, height: H, class: "note-pad" }), g = c.getContext("2d");
    const strokes = []; let col = "#111827", cur = null;
    const paint = () => { g.fillStyle = "#fff"; g.fillRect(0, 0, W, H); g.lineCap = "round"; g.lineJoin = "round";
      for (const s0 of strokes) { g.strokeStyle = s0.c; g.lineWidth = s0.w; g.beginPath(); s0.p.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.stroke(); } };
    const pos = (e) => { const r = c.getBoundingClientRect(); return [(e.clientX - r.left) * W / r.width, (e.clientY - r.top) * H / r.height]; };
    c.addEventListener("pointerdown", (e) => { c.setPointerCapture(e.pointerId); cur = { c: col, w: e.pointerType === "pen" ? 2.5 : 3, p: [pos(e)] }; strokes.push(cur); paint(); });
    c.addEventListener("pointermove", (e) => { if (!cur) return; cur.p.push(pos(e)); paint(); });
    for (const ev of ["pointerup", "pointercancel"]) c.addEventListener(ev, () => { cur = null; });
    const cols = el("div", { class: "sk-chips" });
    const drawCols = () => { cols.innerHTML = ""; for (const [cc, nm] of [["#111827", "검정"], ["#e11d48", "빨강"], ["#2563eb", "파랑"]]) cols.append(el("button", { class: col === cc ? "on" : "", onclick: () => { col = cc; drawCols(); } }, el("i", { class: "sk-dot", style: `background:${cc}` }), nm)); };
    drawCols(); paint();
    b.append(el("h3", {}, "추가사항 — 스케치"), c, el("div", { class: "note-tools" }, cols,
      el("button", { class: "b gray", onclick: () => { strokes.pop(); paint(); } }, "↶"), el("button", { class: "b gray", onclick: () => { strokes.length = 0; paint(); } }, "지우기")),
      el("div", { class: "btns" }, el("span", { class: "sp" }), el("button", { class: "b gray", onclick: close }, "취소"),
        el("button", { class: "b ok", onclick: () => { if (!strokes.length) { close(); return; } t.notes = notesOf(t).slice(); t.notes.push({ t: "sketch", img: c.toDataURL("image/png"), d: today() }); syncMemo(t); close(); after(); } }, "확인")));
  });
}
function delCurrent() {
  const r = S.sel; if (!r) return;
  if (!isMine(r)) { notMineToast(r); return; }
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
  if (key === "mkind") return [KIND_KO[m.k]].filter(Boolean);
  if (key === "mname") return m.n ? [m.n] : [];
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
  const cur = String((key === "mkind" ? nameParts(e)[0] : key === "mname" ? nameParts(e)[1] : field ? (e.fields || {})[key] : e[key]) ?? "");
  const groups = [];
  const ski = e.skm && window.SK ? SK.memberInfo(SK.get(e.skm)) : null;
  const dv = ski ? ({ name: [ski.label, ski.name].filter(Boolean), mkind: [ski.ko], mname: [ski.name].filter(Boolean), size_b: [ski.b].filter(Boolean), size_h: [ski.h].filter(Boolean) }[key] || []) : drawingValues(key, m);
  if (dv.length) groups.push([ski ? "스케치 부재" : "도면값", dv, false]);
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
    if (key === "mkind" || key === "mname") { const [k0, n0] = nameParts(e); e.mkind = key === "mkind" ? v : k0; e.mname = key === "mname" ? v : n0; e.name = [e.mkind, e.mname].filter(Boolean).join(" "); }
    else if (field) { e.fields = e.fields || {}; e.fields[key] = v; } else e[key] = v;
    if (field && key === "ctype" && CRACK_BY[v] && !(e.label || "").startsWith(CRACK_BY[v].code)) e.label = CRACK_BY[v].code + crackNextNo(CRACK_BY[v].code);
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
    onclick: () => { S.purpose = p; S.polyDraft = null; if (S.mode === "span" && !(S.purposes[p] || {}).size) setMode("point"); buildPurposeSeg(); draw(); } }, p));
  buildPointOpts();
}
// 용도별 보조 버튼: 부재검측 = 구간 / 균열검토 = ＋추가 / 하중조사 = 사각형·다각형(+완료)
function buildPointOpts() {
  const box = $("#pointOpts"); if (!box) return; box.innerHTML = "";
  if (S.mode === "sketch" || !S.db) { box.classList.add("hidden"); return; }
  if (S.leadAct) {
    box.append(el("span", { class: "po-lab" }, `${({ move: "✥ 이동", copy: "⧉ 복사", bubble: "↗ 지시선" })[S.leadAct.kind]} ${listNo(S.leadAct.rec)} — ${S.leadAct.kind === "bubble" ? "번호 놓을 곳을" : "위치를"} 누르세요`),
      el("button", { onclick: () => { S.leadAct = null; hint(""); buildPointOpts(); draw(); } }, "✕ 취소"));
  } else if (S.areaPending) {
    const sh = areaShape();
    box.append(el("span", { class: "po-lab" }, `${S.areaPending.purpose} 영역`),
      el("button", { class: sh === "rect" ? "on" : "", onclick: () => setAreaShape("rect") }, "▭ 사각형"),
      el("button", { class: sh === "poly" ? "on" : "", onclick: () => setAreaShape("poly") }, "⬠ 다각형"));
    if (sh === "poly" && S.polyDraft && S.polyDraft.length) box.append(
      el("button", { class: "go", onclick: polyFinish }, "✔ 완료"),
      el("button", { onclick: () => { S.polyDraft.pop(); if (!S.polyDraft.length) S.polyDraft = null; buildPointOpts(); draw(); } }, "↶"));
    box.append(el("button", { onclick: () => { S.areaPending = null; S.polyDraft = null; hint(""); buildPointOpts(); draw(); } }, "✕ 취소"));
  } else {
    const sp = Object.keys(S.purposes).find((k) => S.purposes[k].size);
    if (sp) box.append(el("button", { class: S.mode === "span" ? "on" : "", onclick: () => { S.purpose = sp; setMode(S.mode === "span" ? "point" : "span"); } }, S.mode === "span" ? "↔ 구간 끝" : `↔ 구간 (${sp})`));
  }
  box.classList.toggle("hidden", !box.children.length);
}
function setMode(m) {
  S.mode = m; S.spanStart = null; S.polyDraft = null; S.placing = null; hint("");
  if (m === "span") S.areaPending = null;
  const top = m === "sketch" ? "sketch" : "point";
  for (const b of $("#modeSeg").children) b.classList.toggle("on", b.dataset.mode === top);
  document.body.classList.toggle("sketching", m === "sketch");
  $("#purposeSeg").classList.add("hidden"); $("#filters").classList.toggle("hidden", m === "sketch");   // 용도는 검측점을 놓은 뒤 고름
  if (m === "sketch") { S.leadAct = null; S.areaPending = null; }
  $("#listTitle").textContent = m === "sketch" ? "스케치 목록" : "조사 목록";
  if (window.SK) SK.mode(m === "sketch");
  if (m === "span") { hint("구간: 보·거더·벽 위 시작점과 끝점을 누르세요"); setTimeout(() => hint(""), 2000); }
  buildPointOpts(); renderList(); draw();
}
function buildFilters() {
  const f = $("#filters"); f.innerHTML = "";
  for (const p of ["전체", ...Object.keys(S.purposes)]) f.append(el("button", { style: `background:${p === S.filter ? (p === "전체" ? "#475569" : purposeColor(p)) : "#3E5580"}`,
    onclick: () => { S.filter = p; buildFilters(); renderList(); } }, p));
}
function listColumns() {
  const P = S.purposes[S.filter];
  if (P && P.size) return [["no", "번호"], ["name", "부재명"], ["memc", "내용"], ["chk", "검측"]];   // 부재검측: 번호·부재명·내용·검측 유무
  if (!$("#list").classList.contains("dock-bottom")) return [["label", "번호"], ["name", "부재명"], ["summary", "내용"]];
  if (!P) return [["no", "번호"], ["purpose", "용도"], ["name", "부재명"], ["summary", "내용"], ["inspector", "검토자"], ["ph", "사진"]];
  if (P.crack) return [["label", "번호"], ["ctm", "부재·종류"], ["csize", "크기"], ["count", "개수"], ["f:shape", "형태"], ["inspector", "검토자"], ["ph", "사진"], ["add", ""]];
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
  if (k === "no") return r.label && !r.copyOf ? r.label : listNo(r);
  if (k === "count") return r.label ? `${crackCount(r.label, r.owner)}곳` : "";
  if (k === "ctm") { const fl = r.fields || {}; return [fl.cmem, fl.ctype].filter(Boolean).join(" "); }
  if (k === "memc") return r.sketchOnly ? "" : `치수 ${r.size_b || r.size_h ? "유" : "무"} · 철근 ${Object.values(r.rebar || {}).some(Boolean) ? "유" : "무"}`;
  if (k === "chk") return r.sketchOnly ? "검측 안됨" : "검측";
  if (k === "label") return r.label || r.no; if (k === "csize") return crackSize(r.fields); if (k === "placed") return isPlaced(r) ? "배치" : "📍미배치";
  if (k === "summary") return summary(r); if (k === "ph") return (r.photos || []).length || "";
  if (k === "size") return r.size_b || r.size_h ? `${r.size_b || "?"}×${r.size_h || "?"}` : ""; if (k === "rebar") return rebarText(r);
  if (k === "areaM2") return r.area ? areaOf(r).toFixed(1) : "";
  if (k === "dl" || k === "ll") { if (!r.area) return ""; const L = loadCalc(r.fields || {}); const v = k === "dl" ? L.dl : L.ll; return v == null ? "" : (+v).toFixed(2); }
  if (k.startsWith("f:")) return (r.fields || {})[k.slice(2)] || ""; return r[k] ?? "";
}
function renderList() {
  if (S.mode === "sketch" && window.SK) { SK.renderList(); return; }
  if ((S.purposes[S.filter] || {}).crack) { renderCrackList(); return; }
  const recs = S.recs.filter((r) => (S.filter === "전체" || r.purpose === S.filter) && ownerVisible(r)).sort((a, b) => (isPlaced(a) - isPlaced(b)) || a.no - b.no);
  $("#listCount").textContent = `${recs.length}건`;
  const cols = listColumns();
  $("#lt-h").innerHTML = ""; $("#lt-h").append(el("tr", {}, cols.map(([, t]) => el("th", {}, t))));
  const tb = $("#lt-b"); tb.innerHTML = "";
  const cur = S.edit || S.sel;
  const rowOf = (r, sub) => {
    const tr = el("tr", { class: (sub ? "sub" : "") + (cur && cur.uid === r.uid ? " sel" : "") + (isPlaced(r) ? "" : " unplaced") + (isMine(r) ? "" : " others") },
      cols.map(([k]) => el("td", {}, k === "chk" ? el("span", { class: "chk-ok" }, "검측") : k === "no" && sub && r.label ? r.label : String(listValue(r, k)))));
    rowGestures(tr, () => (isPlaced(r) || !isMine(r) ? showRec(r.uid) : startPlacing(r)), () => { showRec(r.uid, true); S.rowMenu = r.uid; renderList(); });
    tb.append(tr);
    if (S.rowMenu === r.uid) tb.append(rowMenuRow(r, cols.length));
  };
  if (S.filter === "전체" && recs.length) {        // 전체: 용도별(부재검측·균열검토 …) 묶음 — 누르면 하위 목록
    S.allOpen = S.allOpen || new Set();
    if (cur && S.allOpenAuto !== cur.uid) { S.allOpen.add(cur.purpose); S.allOpenAuto = cur.uid; }
    const order = [...Object.keys(S.purposes), ...new Set(recs.map((r) => r.purpose))].filter((v, i, a) => a.indexOf(v) === i);
    for (const pu of order) {
      const its = recs.filter((r) => r.purpose === pu); if (!its.length) continue;
      const open = S.allOpen.has(pu), P = S.purposes[pu] || {};
      const nUn = its.filter((r) => !isPlaced(r)).length;
      const extra = P.crack ? `${new Set(its.map((r) => r.label || r.uid)).size}종 · ${its.filter(isPlaced).length}곳` : `${its.length}건`;
      const hr = el("tr", { class: "kgrp" + (open ? " open" : "") }, el("td", { colspan: String(cols.length) },
        `${open ? "▾" : "▸"} ${pu}`, el("small", {}, extra + (nUn ? ` · 미배치 ${nUn}` : ""))));
      hr.addEventListener("click", () => { if (open) S.allOpen.delete(pu); else S.allOpen.add(pu); S.rowMenu = null; renderList(); });
      tb.append(hr);
      if (open) its.forEach((r) => rowOf(r, true));
    }
  } else for (const r of recs) rowOf(r);
  const PF = S.purposes[S.filter] || {};
  $("#listBody").classList.toggle("memtbl", !!PF.size);
  if (PF.size && window.SK && SK.memberInfo) {      // 스케치로 그린 부재 중 아직 검측하지 않은 것 → '검측 안됨'
    const done = new Set(S.recs.filter((r) => r.skm).map((r) => r.skm));
    const ms = SK.list.filter((k) => ["column", "beam", "wall"].includes(k.kind) && !done.has(k.uid) && SK.shown(k));
    for (const sk of ms) {
      const info = SK.memberInfo(sk);
      const tr = el("tr", { class: "skonly" + (SK.selected() === sk.uid ? " sel" : "") }, cols.map(([k]) => el("td", {},
        k === "no" ? "-" : k === "name" ? info.label : k === "chk" ? el("span", { class: "chk-no" }, "검측 안됨") : k === "memc" ? `${info.b || "?"}${info.h ? "×" + info.h : ""} (스케치)` : "")));
      rowGestures(tr, () => SK.focusUid(sk.uid), () => skSurvey(sk, info));
      tb.append(tr);
    }
    $("#listCount").textContent = `${recs.length}건 · 검측 안됨 ${ms.length}`;
  }
  const P = S.purposes[S.filter] || S.purposes[S.purpose] || {};
  if (P.crack && (S.filter === "전체" ? S.purpose : S.filter) && S.db) tb.append(el("tr", { class: "add-row" },
    el("td", { colspan: String(cols.length) }, el("button", { class: "b ok", onclick: (ev) => { ev.stopPropagation(); crackAdd(null); } }, "＋ 균열·손상 추가 (종류 → 크기 → 사진)"))));
}
// 균열 목록: 번호(PW1 …)마다 한 줄 + 개수, 맨 아래 종류별 합계
function renderCrackList() {
  const groups = new Map();
  for (const r of S.recs.filter((x) => x.purpose === S.filter && ownerVisible(x)).sort((a, b) => a.no - b.no)) {
    const key = r.label ? `${r.owner || ""}|${r.label}` : r.uid;
    if (!groups.has(key)) groups.set(key, []); groups.get(key).push(r);
  }
  const cols = listColumns();
  $("#listCount").textContent = `${groups.size}종 · ${S.recs.filter((x) => x.purpose === S.filter && isPlaced(x)).length}곳`;
  $("#lt-h").innerHTML = ""; $("#lt-h").append(el("tr", {}, cols.map(([, t]) => el("th", {}, t))));
  const tb = $("#lt-b"); tb.innerHTML = "";
  const cur = S.edit || S.sel;
  const sorted = [...groups.values()].sort((a, b) => String(a[0].label).localeCompare(String(b[0].label), "ko", { numeric: true }));
  S.crackOpen = S.crackOpen || new Set();
  for (const lst of sorted) {
    const r = lst.find(isPlaced) || lst[0], placed = lst.some(isPlaced), mine = isMine(r);
    const pl = lst.filter(isPlaced), key = `${r.owner || ""}|${r.label || r.uid}`, multi = pl.length > 1, open = multi && S.crackOpen.has(key);
    const curIn = cur && lst.find((x) => x.uid === cur.uid);
    const tr = el("tr", { class: (curIn && !open ? "sel" : "") + (placed ? "" : " unplaced") + (mine ? "" : " others") + (multi ? " grp" : "") + (open ? " open" : "") },
      cols.map(([k]) => el("td", {}, k === "add" ? (mine && placed ? el("button", { class: "mini-add", onclick: (ev) => { ev.stopPropagation(); startPlacing(r, true); } }, "📍＋") : "")
        : k === "count" ? (placed ? `${crackCount(r.label, r.owner)}곳` : "📍미배치")
        : k === "ph" ? String(lst.reduce((a, x) => a + (x.photos || []).length, 0) || "")
        : (k === "label" || (k === "no" && !cols.some((c) => c[0] === "label"))) && multi ? `${open ? "▾" : "▸"} ${listValue(r, k)}` : String(listValue(r, k)))));
    rowGestures(tr, () => {
      if (!placed && mine) { startPlacing(r); return; }
      if (multi) {                                 // 같은 번호 여러 곳 — 누르면 펼치기, 다시 누르면 합치기
        if (open) S.crackOpen.delete(key); else S.crackOpen.add(key);
        S.rowMenu = null; renderList(); return;
      }
      showRec(r.uid);
    }, () => { showRec((curIn || r).uid, true); S.rowMenu = (curIn || r).uid; renderList(); });
    tb.append(tr);
    const menuFor = (x) => rowMenuRow(x, cols.length,
      mine && placed ? el("button", { class: "b ok", onclick: () => { S.rowMenu = null; startPlacing(r, true); } }, "📍＋ 위치 추가") : "");
    if (!open) {
      if (S.rowMenu && lst.some((x) => x.uid === S.rowMenu)) tb.append(menuFor(lst.find((x) => x.uid === S.rowMenu)));
      continue;
    }
    if (S.rowMenu && S.rowMenu === (curIn || r).uid && !pl.some((x) => x.uid === S.rowMenu)) tb.append(menuFor(curIn || r));
    pl.forEach((x, i) => {                         // 펼친 하위 줄 — 위치마다 (누르면 위치 보기, 길게 누르면 수정·삭제)
      const ctr = el("tr", { class: "sub" + (cur && cur.uid === x.uid ? " sel" : "") + (isMine(x) ? "" : " others") },
        cols.map(([k]) => el("td", {}, k === "label" || (k === "no" && !cols.some((c) => c[0] === "label")) ? `└ ${x.label || x.no}-${i + 1}`
          : k === "count" || k === "add" ? "" : k === "ph" ? String(listValue(x, k)) : k === "inspector" ? String(listValue(x, k))
          : k === "summary" || k === "name" ? String(listValue(x, k)) : "")));
      rowGestures(ctr, () => showRec(x.uid), () => { showRec(x.uid, true); S.rowMenu = x.uid; renderList(); });
      tb.append(ctr);
      if (S.rowMenu === x.uid) tb.append(menuFor(x));
    });
  }
  // 종류별 합계 (추후 균열 면적·개수 집계용)
  const tot = {};
  for (const r of S.recs.filter((x) => x.purpose === S.filter && isPlaced(x))) { const t = (r.fields || {}).ctype || "기타"; tot[t] = (tot[t] || 0) + 1; }
  if (Object.keys(tot).length) tb.append(el("tr", { class: "tot-row" }, el("td", { colspan: String(cols.length) },
    "합계 — " + Object.entries(tot).map(([t, n]) => `${t} ${n}곳`).join(" · "))));
  if (S.db) tb.append(el("tr", { class: "add-row" }, el("td", { colspan: String(cols.length) },
    el("button", { class: "b ok", onclick: (ev) => { ev.stopPropagation(); crackAdd(null); } }, "＋ 균열·손상 추가 (종류 → 크기 → 사진)"))));
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
// ---- 도면 LIST — 분류(미정·평면도(건축)·평면도(구조)·입면도·기타) 탭, 이름 변경·분류 지정
const SHEET_CATS = ["미정", "평면도(건축)", "평면도(구조)", "입면도", "기타"];
function sheetCat(id) { try { return JSON.parse(q("SELECT origin FROM sheets WHERE id=?", [id])[0].origin).cat || "미정"; } catch (e) { return "미정"; } }
function setSheetMeta(id, { name, cat }) {
  const row = q("SELECT name, origin FROM sheets WHERE id=?", [id])[0]; if (!row) return;
  let o; try { o = JSON.parse(row.origin) || {}; } catch (e) { o = { ox: 0, oy: 0 }; }
  if (cat != null) { if (cat === "미정") delete o.cat; else o.cat = cat; }
  run("UPDATE sheets SET name=?, origin=? WHERE id=?", [name != null ? name : row.name, JSON.stringify(o), id]);
  if (window.CO) CO.mark("sheet", id);
  S.sheets = q("SELECT id, analysis_id, seq, name FROM sheets ORDER BY seq, id");
  if (S.sheet && S.sheet.id === id && name != null) { S.sheet.name = name; $("#floorBtn").textContent = name; }
  persistSoon();
}
function showSheets() {
  if (!S.db) return;
  let tab = localStorage.getItem("sheetTab") || "전체", menuFor = null;
  const close = sheet((b) => {
    const render = () => {
      b.innerHTML = "";
      const cats = S.sheets.map((s) => sheetCat(s.id));
      const tabs = el("div", { class: "sh-tabs" }, ["전체", ...SHEET_CATS].map((t) => {
        const n = t === "전체" ? S.sheets.length : cats.filter((c) => c === t).length;
        return el("button", { class: (tab === t ? "on" : "") + (n ? "" : " empty"), onclick: () => { tab = t; try { localStorage.setItem("sheetTab", t); } catch (e) { /* ignore */ } menuFor = null; render(); } }, t, el("small", {}, String(n)));
      }));
      const l = el("div", { class: "sheets-list" });
      S.sheets.forEach((s, i) => {
        const c = cats[i]; if (tab !== "전체" && c !== tab) return;
        const n = q("SELECT COUNT(*) AS n FROM surveys WHERE sheet_id=? AND deleted=0", [s.id])[0].n;
        const row = el("div", { class: "sh-row" },
          el("button", { class: "sh-main" + (i === S.sheetIdx ? " cur" : ""), onclick: () => { close(); loadSheet(i); } },
            el("span", {}, `${i + 1}. ${s.name}`), el("span", {}, el("em", { class: "sh-cat" + (c === "미정" ? " none" : "") }, c), ` ${n}건`)),
          el("button", { class: "sh-more", onclick: () => { menuFor = menuFor === s.id ? null : s.id; render(); } }, "⋯"));
        l.append(row);
        if (menuFor === s.id) {
          const inp = el("input", { type: "text", class: "sk-input", value: s.name });
          l.append(el("div", { class: "sh-edit" },
            el("div", { class: "sk-numrow" }, el("span", { class: "sk-lab" }, "이름"), inp,
              el("button", { class: "b ok", onclick: () => { const v = inp.value.trim(); if (!v) return; setSheetMeta(s.id, { name: v }); toast(`도면 이름: ${v}`); render(); } }, "변경")),
            el("div", { class: "sk-numrow" }, el("span", { class: "sk-lab" }, "분류"),
              el("div", { class: "sk-chips" }, SHEET_CATS.map((t) => el("button", { class: t === c ? "on" : "", onclick: () => { setSheetMeta(s.id, { cat: t }); toast(`${s.name} → ${t}`); render(); } }, t))))));
        }
      });
      if (!l.children.length) l.append(el("p", { class: "small" }, `'${tab}' 도면이 없습니다. 다른 도면의 ⋯ 에서 분류를 지정하세요.`));
      b.append(el("h3", {}, "도면 LIST"), tabs, l,
        el("p", { class: "small" }, "⋯ 를 눌러 도면 이름·분류(평면도(건축)/평면도(구조)/입면도 …)를 정합니다. PDF로 여러 장 올리면 처음엔 '미정'."),
        el("div", { class: "btns" }, el("button", { class: "b edit", onclick: () => { close(); NS.dialog(false); } }, "＋ 도면 추가 (PDF 여러 장 가능)"),
          el("span", { class: "sp" }), el("button", { class: "b ok", onclick: () => close() }, "닫기")));
    };
    render();
  });
}
$("#btnSheets").onclick = $("#floorBtn").onclick = () => showSheets();
$("#btnFit").onclick = fit;
$("#modeSeg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; setMode(b.dataset.mode); });
$("#btnMenu").onclick = () => { $("#menuInfo").textContent = S.db ? `${S.fileName} · 내보낸 날짜 ${S.meta.exported || "-"}` : ""; $("#menu").classList.add("show"); };
$("#menu").addEventListener("click", (e) => { if (e.target.id === "menu" || e.target.hasAttribute("data-close")) $("#menu").classList.remove("show"); });
$("#miSave").onclick = () => { $("#menu").classList.remove("show"); if (!S.db || !guardEdit()) return; saveMenu(); };
function peopleList() {             // 이 조사 파일의 검토자 (검측·스케치 수)
  const meKey = window.CO && CO.me() ? "@" + CO.me().login : "~" + inspector();
  const people = new Map();
  const add = (o, t) => { const k = ownerKey(o); if (!people.has(k)) people.set(k, { k, name: (o.owner && window.CO ? CO.ownerName(o) : o.inspector) || o.inspector || "(이름 없음)", rec: 0, sk: 0 }); if (t) people.get(k)[t]++; };
  add(window.CO && CO.me() ? { owner: CO.me().login, inspector: CO.me().name } : { inspector: inspector() });
  for (const r of q("SELECT rec FROM surveys WHERE deleted=0")) { try { add(JSON.parse(r.rec), "rec"); } catch (e) { /* skip */ } }
  for (const r of q("SELECT data FROM sketches WHERE deleted=0")) { try { add(JSON.parse(r.data), "sk"); } catch (e) { /* skip */ } }
  const list = [...people.values()].sort((a, c) => (c.k === meKey) - (a.k === meKey) || a.name.localeCompare(c.name));
  return { list, meKey };
}
function saveMenu() {
  const { list, meKey } = peopleList(), pick = new Set([meKey]);
  let step = 1;
  sheet((b) => {
    const render = () => {
      b.innerHTML = "";
      if (step === 1) {
        b.append(el("h3", {}, "💾 저장하기"),
          el("button", { class: "bigbtn navy", onclick: () => { $("#modal").classList.remove("show"); saveFile(); } }, "💾 전체 저장", el("small", {}, " 모든 검토자 · 도면 · 사진")),
          el("button", { class: "bigbtn", onclick: () => { step = 2; render(); } }, "👤 작업자 선택 저장", el("small", {}, " 고른 사람 것만")),
          el("div", { class: "btns" }, el("span", { class: "sp" }), el("button", { class: "b gray", onclick: () => $("#modal").classList.remove("show") }, "닫기")));
        return;
      }
      const box = el("div", { class: "lay-box" });
      list.forEach((p) => { const on = pick.has(p.k);
        box.append(el("button", { class: "lay" + (on ? " on" : ""), style: "--c:#2563eb", onclick: () => { if (on) pick.delete(p.k); else pick.add(p.k); render(); } },
          el("i"), `👤 ${p.name}${p.k === meKey ? " (나)" : ""}`, el("small", {}, `검측 ${p.rec} · 스케치 ${p.sk}`))); });
      b.append(el("h3", {}, "👤 작업자 선택 저장"), el("p", { class: "small" }, "고른 사람의 검측·스케치·사진만 담은 .strsv를 만듭니다 (도면은 모두 포함). 지금 작업 내용은 그대로입니다."), box,
        el("div", { class: "btns" }, el("button", { class: "b gray", onclick: () => { step = 1; render(); } }, "‹ 뒤로"), el("span", { class: "sp" }),
          el("button", { class: "b ok", onclick: () => {
            if (!pick.size) { toast("저장할 작업자를 고르세요"); return; }
            const names = list.filter((p) => pick.has(p.k)).map((p) => p.name);
            $("#modal").classList.remove("show"); saveFile({ keys: pick, suffix: names.length > 2 ? `${names[0]}외${names.length - 1}명` : names.join("_") });
          } }, "저장")));
    };
    render();
  });
}
function filteredBytes(keys) {      // 작업자 선택 저장: 고른 사람의 기록·스케치·사진만
  const db2 = new S.SQL.Database(S.db.export());
  const rows = (db2.exec("SELECT uid, rec FROM surveys")[0] || { values: [] }).values;
  for (const [u, rj] of rows) { let o = null; try { o = JSON.parse(rj); } catch (e) { /* drop */ } if (!o || !keys.has(ownerKey(o))) db2.run("DELETE FROM surveys WHERE uid=?", [u]); }
  const sk = (db2.exec("SELECT uid, data FROM sketches")[0] || { values: [] }).values;
  for (const [u, dj] of sk) { let o = null; try { o = JSON.parse(dj); } catch (e) { /* drop */ } if (!o || !keys.has(ownerKey(o))) db2.run("DELETE FROM sketches WHERE uid=?", [u]); }
  db2.run("DELETE FROM photos WHERE survey_uid IS NULL OR survey_uid NOT IN (SELECT uid FROM surveys)");
  try { db2.run("DELETE FROM orig WHERE uid NOT IN (SELECT uid FROM photos)"); } catch (e) { /* no table */ }
  try { db2.run("DELETE FROM collab_dirty"); } catch (e) { /* no table */ }
  const out = db2.export(); db2.close(); return out;
}
$("#miPurpose").onclick = () => { $("#menu").classList.remove("show"); if (S.db) addPurpose(); };
$("#miSettings").onclick = () => { $("#menu").classList.remove("show"); if (window.SK) SK.settings(); };
$("#miCsv").onclick = () => { $("#menu").classList.remove("show"); if (S.db) exportCsv(); };
$("#btnLayers").onclick = () => showLayers();
$("#miSketch").onclick = () => { $("#menu").classList.remove("show"); if (window.SK) SK.toggleHidden(); };
for (const id of ["#fileOpen", "#fileOpen2"]) $(id).onchange = async (e) => {
  const f = e.target.files[0]; e.target.value = ""; $("#menu").classList.remove("show"); if (!f) return;
  if (S.db && !confirm("지금 열린 조사를 닫고 새 파일을 열까요?\n(저장 안 한 내용은 '저장/공유'로 먼저 내보내세요)")) return;
  try { await withBusy("파일 여는 중…", async () => openBytes(await f.arrayBuffer(), f.name), f.name); } catch (err) { alert(err.message); }
};
$("#btnResume").onclick = async () => { let c = null; try { c = await IDB.get("current"); } catch (e) { /* ignore */ }
  if (!c) { toast("이어서 할 조사가 없습니다 — ＋ 새 조사로 시작하세요", 2600); return; }
  await withBusy("불러오는 중…", () => openBytes(c.bytes, c.name), c.name); toast(`이어서 하기 (${c.saved})`); };
$("#btnNewSurvey").onclick = () => {
  const o = $("#newOpts"), open = o.classList.toggle("hidden") === false;
  $("#btnNewSurvey").classList.toggle("open", open);
  $("#btnCollab").classList.toggle("hidden", !(window.CO && CO.me()));
};

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
$("#btnInsp").onclick = () => (S.db ? showInspectors() : (window.CO && CO.me() ? CO.hub() : askInspector()));
$("#btnEditMode").onclick = () => setViewOnly(!S.viewOnly);
$("#btnPen").onclick = () => setPenOnly(!S.penOnly);
syncInputBtns();
$("#btnPcGet").onclick = pcGet; $("#miPcGet").onclick = pcGet; $("#miPcPut").onclick = pcPut;
$("#miPcAddr").onclick = () => { $("#menu").classList.remove("show"); askPcAddress(); };

// ======================================================================= start
window.addEventListener("resize", resize);
window.addEventListener("beforeunload", (e) => { if (S.edit) { e.preventDefault(); e.returnValue = ""; } });
(async function start() {
  resize();
  try { const c = await IDB.get("current"); if (c) $("#welcomeNote").textContent = `마지막 작업: ${c.name} (${c.saved})`; else $("#btnResume").classList.add("dim"); } catch (e) { /* private mode */ }
  if (NATIVE) {                                  // APK: PC sync over Wi-Fi with an address entered once
    for (const b of document.querySelectorAll(".pc, #btnPcGet, #miPcAddr")) b.classList.remove("hidden");
  } else {
    try { const r = await fetch("api/ping", { cache: "no-store" }); if (r.ok) { S.pc = true; for (const b of document.querySelectorAll(".pc, #btnPcGet")) b.classList.remove("hidden"); } } catch (e) { /* not served by the PC */ }
    if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("sw.js").catch(() => {});
  }
  loadSQL().catch((e) => toast("SQLite 엔진을 불러오지 못했습니다: " + e.message, 5000));
  showInspector();
})();
