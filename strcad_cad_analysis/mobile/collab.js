// StrCAD 현장조사 — 검토자 협업 (StrCAD 협업 서버)
//  · 개인 계정 로그인 (처음 가입 때 팀 코드) · 관리자: 인원 관리
//  · 오프라인에서 작업 → 연결되면 [🔄 공유] (연결 중에는 자동으로 주고받음)
//  · 다른 검토자의 기록·스케치는 보기만 (서버도 거부)
"use strict";

const CO = (() => {
  const st = { auth: null, project: null, name: "", rev: 0, timer: null, busy: false, last: null, people: [], err: "", pending: 0 };
  try { st.auth = JSON.parse(localStorage.getItem("collabAuth") || "null"); } catch (e) { st.auth = null; }
  const saveAuth = () => { try { localStorage.setItem("collabAuth", JSON.stringify(st.auth)); } catch (e) { /* ignore */ } };
  const base = () => (st.auth && st.auth.url) || "";
  const me = () => (st.auth && st.auth.user) || null;
  const active = () => !!(st.project && me() && S.db);

  // ------------------------------------------------------------------ http
  async function api(path, opts = {}) {
    const h = Object.assign({}, opts.headers || {});
    if (st.auth && st.auth.token) h.Authorization = "Bearer " + st.auth.token;
    let body = opts.body;
    if (body && !(body instanceof Uint8Array) && !(body instanceof ArrayBuffer) && typeof body !== "string") { body = JSON.stringify(body); h["Content-Type"] = "application/json"; }
    const ctl = new AbortController(), tm = setTimeout(() => ctl.abort(), opts.timeout || 30000);
    try {
      const r = await fetch((opts.url || base()) + path, { method: opts.method || (body ? "POST" : "GET"), headers: h, body, cache: "no-store", signal: ctl.signal });
      if (opts.binary) { if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status); return new Uint8Array(await r.arrayBuffer()); }
      const j = await r.json().catch(() => ({}));
      if (!r.ok) { const e = new Error(j.error || `서버 오류 ${r.status}`); e.status = r.status; throw e; }
      return j;
    } finally { clearTimeout(tm); }
  }
  const normUrl = (v) => { v = (v || "").trim(); if (!v) return ""; if (!/^https?:\/\//.test(v)) v = "http://" + v; return v.replace(/\/?$/, "/"); };

  // ------------------------------------------------------------------ local tables
  function ensureTables() {
    run("CREATE TABLE IF NOT EXISTS collab (key TEXT PRIMARY KEY, value TEXT)");
    run("CREATE TABLE IF NOT EXISTS collab_dirty (kind TEXT, uid TEXT, PRIMARY KEY (kind, uid))");
    run("CREATE TABLE IF NOT EXISTS sheet_uid (sheet_id INTEGER PRIMARY KEY, suid TEXT)");
  }
  const getK = (k) => { try { const r = q("SELECT value FROM collab WHERE key=?", [k])[0]; return r ? r.value : ""; } catch (e) { return ""; } };
  const setK = (k, v) => run("INSERT OR REPLACE INTO collab (key, value) VALUES (?,?)", [k, String(v)]);
  function mark(kind, id) { if (!S.db || !st.project) return; try { run("INSERT OR IGNORE INTO collab_dirty (kind, uid) VALUES (?,?)", [kind, String(id)]); } catch (e) { /* ignore */ } updatePill(); }
  function pendingCount() { try { return q("SELECT COUNT(*) AS n FROM collab_dirty")[0].n; } catch (e) { return 0; } }
  function suidOf(sheetId, create) {
    const r = q("SELECT suid FROM sheet_uid WHERE sheet_id=?", [sheetId])[0];
    if (r) return r.suid;
    if (!create) return null;
    let s = null; try { const e = q("SELECT suid FROM sheet_ext WHERE sheet_id=?", [sheetId])[0]; s = e && e.suid; } catch (e) { /* ignore */ }
    s = s || "sh_" + uid().slice(0, 16);
    run("INSERT OR REPLACE INTO sheet_uid (sheet_id, suid) VALUES (?,?)", [sheetId, s]); return s;
  }
  const sheetIdOf = (suid) => { const r = q("SELECT sheet_id FROM sheet_uid WHERE suid=?", [suid])[0]; return r ? r.sheet_id : null; };

  // 열린 파일이 협업 프로젝트인지
  function onOpen() {
    stopAuto(); st.project = null; st.rev = 0; st.people = [];
    if (!S.db) return;
    ensureTables();
    const pid = +getK("project_id");
    if (pid) {
      st.project = pid; st.name = getK("project"); st.rev = +getK("rev") || 0;
      const srv = getK("server");
      if (!base() && srv) st.auth = Object.assign({}, st.auth || {}, { url: srv });
      if (me() && me().name) { try { localStorage.setItem("inspector", me().name); } catch (e) { /* ignore */ } if (window.showInspector) showInspector(); }
      startAuto();
      setTimeout(() => sync(true), 300);
    }
    updatePill();
  }

  // ------------------------------------------------------------------ 내 것 / 남의 것
  function mine(o) {
    if (!o || !active()) return true;
    return !o.owner || String(o.owner).toLowerCase() === String(me().login).toLowerCase();
  }
  function ownerName(o) {
    if (!o) return "";
    const p = st.people.find((x) => String(x.login).toLowerCase() === String(o.owner || "").toLowerCase());
    return o.inspector || (p && p.name) || o.owner || "다른 검토자";
  }
  function stamp(o) { if (active() && me()) o.owner = me().login; return o; }

  // ------------------------------------------------------------------ sync
  function b64(bytes) { let s = ""; const CH = 0x8000; for (let i = 0; i < bytes.length; i += CH) s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH)); return btoa(s); }
  function collectPush(limitPhotos = 20) {
    const push = { sheets: [], records: [], sketches: [], photos: [] }, taken = [];
    const dirty = q("SELECT kind, uid FROM collab_dirty");
    let nph = 0;
    for (const d of dirty) {
      if (d.kind === "sheet") {
        const s = q("SELECT * FROM sheets WHERE id=?", [+d.uid])[0]; if (!s) { taken.push([d, null]); continue; }
        const isNew = !q("SELECT 1 FROM sheet_uid WHERE sheet_id=?", [s.id]).length;
        const suid = suidOf(s.id, true);
        let ext = null; try { ext = q("SELECT * FROM sheet_ext WHERE sheet_id=?", [s.id])[0]; } catch (e) { ext = null; }
        push.sheets.push({ suid, aid: s.analysis_id, seq: s.seq, name: s.name, origin: s.origin, extents: s.extents, members: s.members, background: s.background, grid: s.grid,
          updated: nowIso(), ext: ext ? { kind: ext.kind, mime: ext.mime, iw: ext.iw, ih: ext.ih, rect: ext.rect, image_b64: (isNew || d.img) && ext.image ? b64(ext.image) : null } : null });
        taken.push([d, "sheet:" + s.id]);
      } else if (d.kind === "rec") {
        const r = q("SELECT * FROM surveys WHERE uid=?", [d.uid])[0]; if (!r) { taken.push([d, null]); continue; }
        push.records.push({ uid: r.uid, suid: suidOf(r.sheet_id, true), updated: r.updated, deleted: r.deleted, rec: r.rec });
        taken.push([d, r.updated]);
      } else if (d.kind === "sk") {
        const r = q("SELECT * FROM sketches WHERE uid=?", [d.uid])[0]; if (!r) { taken.push([d, null]); continue; }
        push.sketches.push({ uid: r.uid, suid: suidOf(r.sheet_id, true), updated: r.updated, deleted: r.deleted, data: r.data });
        taken.push([d, r.updated]);
      } else if (d.kind === "ph") {
        if (nph >= limitPhotos) continue;
        const r = q("SELECT * FROM photos WHERE uid=?", [d.uid])[0]; if (!r) { taken.push([d, null]); continue; }
        push.photos.push({ uid: r.uid, survey_uid: r.survey_uid, name: r.name, mime: r.mime, created: r.created, data_b64: b64(r.data) }); nph++;
        taken.push([d, "ph"]);
      }
    }
    // 도면이 아직 서버에 없는데 기록만 올리는 경우 → 도면도 함께
    for (const r of push.records.concat(push.sketches)) if (!push.sheets.some((s) => s.suid === r.suid)) {
      const sid = sheetIdOf(r.suid);
      if (sid != null && !getK("sheet_sent:" + r.suid)) { const s = q("SELECT * FROM sheets WHERE id=?", [sid])[0]; let ext = null;
        try { ext = q("SELECT * FROM sheet_ext WHERE sheet_id=?", [sid])[0]; } catch (e) { ext = null; }
        push.sheets.push({ suid: r.suid, seq: s.seq, name: s.name, origin: s.origin, extents: s.extents, members: s.members, background: s.background, grid: s.grid,
          updated: nowIso(), ext: ext ? { kind: ext.kind, mime: ext.mime, iw: ext.iw, ih: ext.ih, rect: ext.rect, image_b64: ext.image ? b64(ext.image) : null } : null }); }
    }
    return { push, taken, more: dirty.some((d) => d.kind === "ph") && nph >= limitPhotos };
  }
  function stillSame(d, ver) {          // 올리는 사이에 또 고쳤으면 dirty 유지
    if (ver == null || d.kind === "ph" || d.kind === "sheet") return true;
    const tb = d.kind === "rec" ? "surveys" : "sketches", r = q(`SELECT updated FROM ${tb} WHERE uid=?`, [d.uid])[0];
    return !r || r.updated === ver;
  }

  async function sync(quiet) {
    if (!active() || st.busy) return null;
    if (!navigator.onLine) { st.err = "오프라인"; updatePill(); if (!quiet) toast("오프라인 — 연결되면 [🔄 공유]를 다시 누르세요"); return null; }
    st.busy = true; updatePill();
    let bz = quiet ? null : busy("공유하는 중…");
    const summary = { up: 0, down: 0, rejected: [], renum: [] };
    try {
      for (let round = 0; round < 20; round++) {
        const { push, taken, more } = collectPush();
        if (bz) bz.set("공유하는 중…", `올리기 ${push.records.length + push.sketches.length + push.sheets.length}건 · 사진 ${push.photos.length}장`);
        const res = await api("api/sync", { body: { project: st.project, since: st.rev, push }, timeout: 90000 });
        const rej = new Set(res.rejected.map((r) => r.kind + ":" + r.uid));
        for (const [d, ver] of taken) if (!rej.has(d.kind + ":" + d.uid) && stillSame(d, ver)) run("DELETE FROM collab_dirty WHERE kind=? AND uid=?", [d.kind, d.uid]);
        for (const s of push.sheets) setK("sheet_sent:" + s.suid, "1");
        summary.up += push.records.length + push.sketches.length + push.photos.length;
        summary.rejected.push(...res.rejected); summary.renum.push(...res.renumbered);
        summary.down += await apply(res, bz);
        st.rev = res.rev; setK("rev", st.rev); st.people = res.people || st.people;
        if (res.rejected.length) { st.rev = 0; setK("rev", 0); }          // 거부된 것은 서버 내용으로 다시 받기
        if (!more && !res.rejected.length) break;
      }
      st.last = new Date(); st.err = ""; persistSoon();
      if (!quiet) {
        const t = [`공유 완료 — 올림 ${summary.up}, 받음 ${summary.down}`];
        if (summary.renum.length) t.push(`번호 겹침 ${summary.renum.length}건 자동 변경`);
        if (summary.rejected.length) t.push(`다른 검토자 것 ${summary.rejected.length}건은 고칠 수 없어 되돌림`);
        toast(t.join(" · "), 3500);
      } else if (summary.renum.length) toast(`번호가 겹쳐 ${summary.renum.map((r) => r.changes.map((c) => `${c[1]}→${c[2]}`).join(",")).join(" · ")} 로 바뀜`, 4000);
      return summary;
    } catch (e) {
      st.err = e.status === 401 ? "로그인 필요" : "연결 안 됨";
      if (e.status === 401 || e.status === 403) { if (!quiet) alert(e.message); }
      else if (!quiet) toast("공유 실패: " + (e.message || e) + " — 연결되면 다시 누르세요", 4000);
      return null;
    } finally { st.busy = false; if (bz) bz.close(); updatePill(); }
  }

  // 받은 변경을 내 파일에 반영
  async function apply(res, bz) {
    let n = 0, curChanged = false, sheetsChanged = false;
    const dirtySet = new Set(q("SELECT kind, uid FROM collab_dirty").map((d) => d.kind + ":" + d.uid));
    for (const s of res.sheets) {
      let sid = sheetIdOf(s.suid);
      if (s.deleted) continue;
      if (sid == null) {
        sid = (q("SELECT MAX(id) AS m FROM sheets")[0].m || 0) + 1;
        run("INSERT INTO sheets (id, analysis_id, seq, name, origin, extents, members, background, grid) VALUES (?,?,?,?,?,?,?,?,?)",
          [sid, s.aid ?? null, s.seq || sid, s.name, s.origin, s.extents, s.members, s.background, s.grid]);
        run("INSERT OR REPLACE INTO sheet_uid (sheet_id, suid) VALUES (?,?)", [sid, s.suid]); sheetsChanged = true;
      } else {
        if (dirtySet.has("sheet:" + sid)) continue;
        run("UPDATE sheets SET seq=?, name=?, origin=?, extents=?, members=?, background=?, grid=? WHERE id=?",
          [s.seq || sid, s.name, s.origin, s.extents, s.members, s.background, s.grid, sid]);
      }
      setK("sheet_sent:" + s.suid, "1");
      if (s.ext_kind) {
        const have = q("SELECT image IS NOT NULL AS h FROM sheet_ext WHERE sheet_id=?", [sid])[0];
        let img = null;
        if (s.has_img && !(have && have.h)) { if (bz) bz.set("공유하는 중…", `도면 그림 받는 중: ${s.name}`); img = await api(`api/sheet_image?project=${st.project}&suid=${encodeURIComponent(s.suid)}`, { binary: true }); }
        if (have) run("UPDATE sheet_ext SET suid=?, kind=?, mime=?, iw=?, ih=?, rect=?" + (img ? ", image=?" : "") + " WHERE sheet_id=?",
          [s.suid, s.ext_kind, s.mime, s.iw, s.ih, s.rect, ...(img ? [img] : []), sid]);
        else run("INSERT INTO sheet_ext (sheet_id, suid, kind, image, mime, iw, ih, rect) VALUES (?,?,?,?,?,?,?,?)", [sid, s.suid, s.ext_kind, img, s.mime, s.iw, s.ih, s.rect]);
      }
      if (S.sheet && S.sheet.id === sid) curChanged = true;
      n++;
    }
    for (const r of res.records) {
      const sid = sheetIdOf(r.suid); if (sid == null) continue;
      if (dirtySet.has("rec:" + r.uid)) continue;                    // 올리는 사이에 또 고친 내 것
      run("INSERT OR REPLACE INTO surveys (uid, sheet_id, updated, deleted, rec) VALUES (?,?,?,?,?)", [r.uid, sid, r.updated, r.deleted ? 1 : 0, r.rec]);
      n++;
    }
    for (const r of res.sketches) {
      const sid = sheetIdOf(r.suid); if (sid == null) continue;
      if (dirtySet.has("sk:" + r.uid)) continue;
      run("INSERT OR REPLACE INTO sketches (uid, sheet_id, updated, deleted, data) VALUES (?,?,?,?,?)", [r.uid, sid, r.updated, r.deleted ? 1 : 0, r.data]);
      n++;
    }
    let k = 0;
    for (const p of res.photos) {
      const have = q("SELECT name FROM photos WHERE uid=?", [p.uid])[0];
      if (have) { if (have.name !== p.name) { run("UPDATE photos SET name=? WHERE uid=?", [p.name, p.uid]); await renameOriginal(p.uid, p.name); } continue; }
      k++; if (bz) bz.set("공유하는 중…", `사진 받는 중 ${k}장`);
      try { const data = await api(`api/photo?project=${st.project}&uid=${encodeURIComponent(p.uid)}`, { binary: true });
        run("INSERT OR REPLACE INTO photos (uid, survey_uid, name, mime, data, created) VALUES (?,?,?,?,?,?)", [p.uid, p.survey_uid, p.name, p.mime, data, p.created]); n++; }
      catch (e) { /* 다음에 다시 */ }
    }
    if (n) refresh(curChanged, sheetsChanged);
    return n;
  }
  // 번호 정리·번호 변경으로 사진 이름이 바뀌면 휴대폰의 원본 사진 파일 이름도 같이
  async function renameOriginal(phUid, newName) {
    let o = null; try { o = q("SELECT path, dir FROM orig WHERE uid=?", [phUid])[0]; } catch (e) { o = null; }
    if (!o || !NATIVE) return;
    const dir = o.path.replace(/[^/]*$/, ""), ext = (o.path.match(/\.[^./]+$/) || [".jpg"])[0];
    const to = dir + newName.replace(/\.[^.]+$/, "") + ext;
    if (to === o.path) return;
    try { await window.Capacitor.Plugins.Filesystem.rename({ from: o.path, to, directory: o.dir, toDirectory: o.dir });
      run("UPDATE orig SET path=? WHERE uid=?", [to, phUid]); } catch (e) { console.warn("원본 이름 변경 실패", e); }
  }
  async function renumber() {
    if (!active()) return;
    if (!confirm("번호 정리: 도면마다 검토자별로 번호를 다시 매깁니다.\n(첫 번째 검토자 1~99, 두 번째 101~199, 세 번째 201~ …)\n사진 이름과 휴대폰 원본 사진 이름도 같이 바뀝니다. 진행할까요?")) return;
    closeModal();
    try {
      await sync(true);                                // 내 것 먼저 올리고
      const r = await withBusy("번호 정리 중…", () => api("api/renumber", { body: { project: st.project } }));
      await sync(true);                                // 바뀐 번호·사진 이름 받기
      toast(`번호 정리 ${r.changed}건 — ` + r.bands.map((b) => `${b.name} ${b.start ? b.start + 1 : 1}~`).join(" · "), 5000);
    } catch (e) { alert("번호 정리 실패: " + (e.message || e)); }
  }
  function refresh(curChanged, sheetsChanged) {
    if (sheetsChanged) { S.sheets = q("SELECT id, analysis_id, seq, name FROM sheets ORDER BY seq, id"); $("#pgLbl").textContent = `${S.sheetIdx + 1}/${S.sheets.length}`; }
    if (!S.sheet) return;
    const keepView = { ...S.view }, selU = S.sel && S.sel.uid, editing = S.edit;
    if (curChanged && !editing) { loadSheet(S.sheetIdx); S.view = keepView; }
    else { loadRecs(); if (window.SK && !SK.busy) SK.load(); }
    if (selU) S.sel = S.recs.find((r) => r.uid === selU) || null;
    if (S.sel && !$("#panel").classList.contains("hidden") && !S.edit) renderForm();
    renderList(); draw();
  }

  // ------------------------------------------------------------------ auto (연결 중 실시간)
  function startAuto() {
    stopAuto();
    st.timer = setInterval(() => {
      if (!active() || document.hidden || !navigator.onLine || S.edit || st.busy) return;
      if ($("#modal").classList.contains("show") || (window.SK && SK.busy) || document.querySelector("#busy.show")) return;
      sync(true);
    }, 10000);
  }
  function stopAuto() { if (st.timer) clearInterval(st.timer); st.timer = null; }
  window.addEventListener("online", () => { updatePill(); if (active()) sync(true); });
  window.addEventListener("offline", updatePill);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && active()) sync(true); });

  function updatePill() {
    const b = $("#btnShare"); if (!b) return;
    b.classList.toggle("hidden", !st.project);
    if (!st.project) return;
    const n = S.db ? pendingCount() : 0; st.pending = n;
    const off = !navigator.onLine || !!st.err;
    b.className = "pill share" + (st.busy ? " busy" : off ? " off" : n ? " wait" : " ok");
    b.innerHTML = "";
    b.append(st.busy ? "⟳ 공유 중" : off ? `⚠ ${navigator.onLine ? st.err : "오프라인"}` : "🔄 공유", n ? el("i", { class: "badge" }, String(n)) : "");
    b.title = st.last ? `마지막 공유 ${st.last.toLocaleTimeString()}` : "";
  }

  // ------------------------------------------------------------------ UI
  function closeModal() { $("#modal").classList.remove("show"); }
  function loginSheet(after) {
    let mode = "login";
    sheet((b) => {
      const url = el("input", { type: "url", class: "sk-input", placeholder: "서버 주소 (예: https://strcad.회사.com 또는 http://192.168.0.10:8780)", value: base() || localStorage.getItem("collabUrlHint") || "" });
      const id = el("input", { type: "text", class: "sk-input", placeholder: "아이디", autocapitalize: "off" });
      const pw = el("input", { type: "password", class: "sk-input", placeholder: "비밀번호" });
      const nm = el("input", { type: "text", class: "sk-input", placeholder: "이름 (검토자로 표시)" });
      const code = el("input", { type: "text", class: "sk-input", placeholder: "팀 코드 (관리자에게 받기)", autocapitalize: "characters" });
      const msg = el("p", { class: "small" }, "");
      const tabs = el("div", { class: "seg sk-seg" });
      const render = () => {
        tabs.innerHTML = "";
        for (const [m, t] of [["login", "로그인"], ["signup", "가입"]]) tabs.append(el("button", { class: mode === m ? "on" : "", onclick: () => { mode = m; render(); } }, t));
        form.innerHTML = "";
        form.append(url, id, pw);
        if (mode === "signup") form.append(nm, code, el("p", { class: "small" }, "처음 가입하는 사람은 관리자가 되고 팀 코드 없이 가입됩니다."));
      };
      const form = el("div", { class: "co-form" });
      const go = async () => {
        const u = normUrl(url.value); if (!u) { msg.textContent = "서버 주소를 넣으세요"; return; }
        msg.textContent = "연결 중…";
        try {
          const ping = await api("api/ping", { url: u, timeout: 8000 });
          if (!ping.collab) throw new Error("StrCAD 협업 서버가 아닙니다 (PC Wi-Fi 연결 주소와 다름)");
          const r = mode === "login" ? await api("api/login", { url: u, body: { login: id.value.trim(), password: pw.value } })
            : await api("api/signup", { url: u, body: { login: id.value.trim(), password: pw.value, name: nm.value.trim(), team_code: code.value.trim() } });
          st.auth = { url: u, token: r.token, user: r.user }; saveAuth();
          try { localStorage.setItem("inspector", r.user.name); localStorage.setItem("collabUrlHint", u); } catch (e) { /* ignore */ }
          if (window.showInspector) showInspector();
          closeModal(); toast(`${r.user.name} 님 로그인${r.user.role === "admin" ? " (관리자)" : ""}`);
          if (after) after(); else hub();
        } catch (e) { msg.textContent = (e.name === "AbortError" ? "서버에 연결할 수 없습니다" : e.message) + ""; }
      };
      pw.addEventListener("keydown", (e) => { if (e.key === "Enter" && mode === "login") go(); });
      b.append(el("h3", {}, "👥 협업 — 로그인"), tabs, form, msg,
        el("div", { class: "btns" }, el("span", { class: "sp" }), el("button", { class: "b gray", onclick: closeModal }, "취소"),
          el("button", { class: "b ok", onclick: go }, "확인")));
      render();
    });
  }

  async function hub() {
    if (!me()) { loginSheet(); return; }
    let projects = null, err = "";
    try { projects = (await withBusy("서버 확인 중…", () => api("api/projects"))).projects; }
    catch (e) { err = e.message || String(e); if (e.status === 401) { st.auth.token = null; st.auth.user = null; saveAuth(); loginSheet(); return; } }
    sheet((b) => {
      const u = me();
      b.append(el("h3", {}, "👥 검토자 협업"),
        el("div", { class: "co-me" }, el("b", {}, `${u.name}`), ` (${u.login}${u.role === "admin" ? " · 관리자" : ""})`, el("small", {}, base())));
      if (active()) {
        b.append(el("div", { class: "grp" }, `지금 프로젝트: ${st.name}`),
          el("div", { class: "co-people" }, st.people.length ? st.people.map((p) => el("span", { class: String(p.login).toLowerCase() === u.login.toLowerCase() ? "me" : "" }, `${p.name} ${p.records}건`)) : "아직 공유 기록 없음"),
          el("p", { class: "small" }, `대기 ${pendingCount()}건 · ${st.last ? "마지막 공유 " + st.last.toLocaleTimeString() : "아직 공유 안 함"} · 연결되어 있으면 10초마다 자동으로 주고받습니다. 다른 검토자 기록은 보기만 됩니다.`),
          el("button", { class: "bigbtn", onclick: () => { closeModal(); sync(false); } }, "🔄 지금 공유"),
          el("button", { class: "bigbtn ghost", onclick: renumber }, "🔢 번호 정리 (검토자별 000·100·200번대)"),
          el("p", { class: "small" }, "각자 같은 번호로 조사해도 됩니다. 정리하면 검토자마다 번호대가 나뉘고 사진·원본 사진 이름도 바뀝니다 (관리자·프로젝트를 올린 사람)."));
      } else if (S.db) {
        b.append(el("button", { class: "bigbtn navy", onclick: () => upload() }, `⬆ 지금 조사(${S.meta.project || ""})를 협업 프로젝트로 올리기`));
      }
      b.append(el("div", { class: "grp" }, "서버의 협업 프로젝트"));
      if (err) b.append(el("p", { class: "small", style: "color:#b91c1c" }, "서버 연결 실패: " + err));
      const list = el("div", { class: "sheets-list" });
      for (const p of projects || []) list.append(el("button", { class: active() && st.project === p.id ? "cur" : "", onclick: () => join(p) },
        el("span", {}, `${p.name}`), el("span", {}, `${p.records}건 · ${p.people}명`)));
      if (projects && !projects.length) list.append(el("p", { class: "small" }, "아직 없습니다. 조사 파일을 열고 '협업 프로젝트로 올리기'를 누르세요."));
      b.append(list);
      const row = el("div", { class: "btns co-btns" });
      if (u.role === "admin") row.append(el("button", { class: "b edit", onclick: () => people() }, "👥 인원 관리"));
      row.append(el("button", { class: "b gray", onclick: () => changePw() }, "비밀번호 변경"),
        el("button", { class: "b gray", onclick: () => { api("api/logout", { body: {} }).catch(() => {}); st.auth = { url: base() }; saveAuth(); stopAuto(); st.project = null; updatePill(); closeModal(); toast("로그아웃"); } }, "로그아웃"));
      if (active()) row.append(el("button", { class: "b gray", onclick: () => { if (!confirm("이 파일의 협업 연결을 끊을까요? (내 휴대폰의 파일은 그대로, 더 이상 공유하지 않음)")) return;
        run("DELETE FROM collab"); run("DELETE FROM collab_dirty"); onOpen(); closeModal(); toast("협업 연결 끊음"); } }, "연결 끊기"));
      b.append(row, el("div", { class: "btns" }, el("span", { class: "sp" }), el("button", { class: "b ok", onclick: closeModal }, "닫기")));
    });
  }

  async function openPackage(bytes, name, pid, pname) {
    const old = S.db ? (() => { try { return q("SELECT * FROM orig"); } catch (e) { return []; } })() : [];
    await openBytes(bytes, name);
    ensureTables();
    setK("project_id", pid); setK("project", pname); setK("server", base());
    for (const o of old) { try { run("INSERT OR IGNORE INTO orig (uid, path, dir, size, sent) VALUES (?,?,?,?,?)", [o.uid, o.path, o.dir, o.size, o.sent]); } catch (e) { /* ignore */ } }
    persistSoon(); onOpen();
  }
  async function join(p) {
    if (S.db && pendingCount() && active() && st.project !== p.id && !confirm("공유하지 않은 내용이 있습니다. 그래도 다른 프로젝트를 열까요?")) return;
    if (S.db && !active() && !confirm(`'${p.name}' 협업 프로젝트를 열까요?\n(지금 열린 파일은 닫힙니다. 필요하면 먼저 저장하세요)`)) return;
    closeModal();
    try {
      await withBusy("프로젝트 받는 중…", async () => {
        const bytes = await api(`api/package?project=${p.id}`, { binary: true, timeout: 180000 });
        await openPackage(bytes, `${safeName(p.name)}_협업.strsv`, p.id, p.name);
      }, p.name);
      toast(`협업: ${p.name} — 다른 검토자 기록은 보기만 됩니다`, 3500);
    } catch (e) { alert("받기 실패: " + (e.message || e)); }
  }
  async function upload() {
    if (!S.db || !guardEdit()) return;
    const name = prompt("협업 프로젝트 이름", S.meta.project || "현장조사"); if (!name) return;
    closeModal();
    try {
      await withBusy("서버에 올리는 중…", async (bz) => {
        saveMeta("mobile_saved", nowIso());
        const r = await api(`api/projects?name=${encodeURIComponent(name)}`, { body: S.db.export(), headers: { "Content-Type": "application/octet-stream" }, timeout: 300000 });
        bz.set("서버에 올리는 중…", "협업 프로젝트로 다시 여는 중");
        const bytes = await api(`api/package?project=${r.id}`, { binary: true, timeout: 180000 });
        await openPackage(bytes, `${safeName(r.name)}_협업.strsv`, r.id, r.name);
      }, name);
      toast(`협업 프로젝트 '${name}' 만들었습니다 — 다른 검토자는 👥 협업에서 열면 됩니다`, 4000);
    } catch (e) { alert("올리기 실패: " + (e.message || e)); }
  }

  function changePw() {
    sheet((b) => {
      const o = el("input", { type: "password", class: "sk-input", placeholder: "현재 비밀번호" }), n = el("input", { type: "password", class: "sk-input", placeholder: "새 비밀번호 (4자 이상)" });
      b.append(el("h3", {}, "비밀번호 변경"), o, n, el("div", { class: "btns" }, el("span", { class: "sp" }), el("button", { class: "b gray", onclick: closeModal }, "취소"),
        el("button", { class: "b ok", onclick: async () => { try { await api("api/password", { body: { old: o.value, new: n.value } }); closeModal(); toast("비밀번호를 바꿨습니다"); } catch (e) { alert(e.message); } } }, "변경")));
    });
  }

  // ---- 관리자: 인원 관리
  async function people() {
    let users = [], code = "";
    try { [users, code] = await withBusy("불러오는 중…", async () => [(await api("api/users")).users, (await api("api/team_code")).team_code]); }
    catch (e) { alert(e.message); return; }
    const act = async (body, ok) => { try { await api("api/users", { body }); toast(ok); people(); } catch (e) { alert(e.message); } };
    sheet((b) => {
      b.append(el("h3", {}, "👥 인원 관리 (관리자)"),
        el("div", { class: "co-code" }, "팀 코드 ", el("b", {}, code), el("button", { class: "b gray", onclick: async () => {
          const v = prompt("새 팀 코드 (4자 이상, 가입할 때 필요)", code); if (!v) return;
          try { await api("api/team_code", { body: { team_code: v } }); people(); } catch (e) { alert(e.message); } } }, "바꾸기")),
        el("p", { class: "small" }, "새 검토자는 앱 › 👥 협업 › 가입에서 이 팀 코드로 가입하거나, 아래 ＋ 계정 추가로 만들어 줄 수 있습니다."));
      const tb = el("div", { class: "co-users" });
      for (const u of users) {
        tb.append(el("div", { class: "co-user" + (u.active ? "" : " off") },
          el("div", {}, el("b", {}, u.name), ` ${u.login}`, u.role === "admin" ? el("span", { class: "tag" }, "관리자") : "", u.active ? "" : el("span", { class: "tag off" }, "중지"),
            el("small", {}, u.last_seen ? `최근 ${u.last_seen.replace("T", " ").slice(0, 16)}` : "접속 기록 없음")),
          el("div", { class: "co-acts" },
            el("button", { onclick: () => act({ action: "active", id: u.id, value: !u.active }, u.active ? `${u.name} 사용 중지` : `${u.name} 사용 재개`) }, u.active ? "중지" : "재개"),
            el("button", { onclick: () => act({ action: "role", id: u.id, value: u.role === "admin" ? "member" : "admin" }, "권한 변경") }, u.role === "admin" ? "일반으로" : "관리자로"),
            el("button", { onclick: () => { const p = prompt(`${u.name} 님의 새 비밀번호 (4자 이상)`); if (p) act({ action: "reset", id: u.id, password: p }, "비밀번호 초기화"); } }, "비번 초기화"),
            el("button", { onclick: () => { const v = prompt("이름", u.name); if (v) act({ action: "name", id: u.id, value: v }, "이름 변경"); } }, "이름"))));
      }
      b.append(tb, el("div", { class: "btns" },
        el("button", { class: "b edit", onclick: () => {
          const login = prompt("새 계정 아이디 (영문·숫자 3~20자)"); if (!login) return;
          const name = prompt("이름"); if (!name) return;
          const pw = prompt("처음 비밀번호 (4자 이상, 본인이 나중에 변경)"); if (!pw) return;
          act({ action: "add", login, name, password: pw }, `${name} 계정을 만들었습니다`); } }, "＋ 계정 추가"),
        el("span", { class: "sp" }), el("button", { class: "b gray", onclick: () => hub() }, "‹ 협업"), el("button", { class: "b ok", onclick: closeModal }, "닫기")));
    });
  }

  // 서버에서 앱을 연 경우(브라우저) 주소 미리 채우기
  (async () => { if (base() || NATIVE) return; try { const r = await fetch("api/ping", { cache: "no-store" }); const j = await r.json(); if (j.collab) localStorage.setItem("collabUrlHint", location.origin + location.pathname.replace(/[^/]*$/, "")); } catch (e) { /* no server */ } })();

  $("#miCollab").onclick = () => { $("#menu").classList.remove("show"); hub(); };
  $("#btnCollab").onclick = () => hub();
  $("#btnShare").onclick = () => sync(false);
  return { onOpen, mark, mine, ownerName, stamp, sync, hub, active, me, suidOf, renumber, get people() { return st.people; } };
})();
window.CO = CO;
