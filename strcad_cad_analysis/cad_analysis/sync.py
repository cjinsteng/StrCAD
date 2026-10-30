"""PC ↔ 휴대폰/패드 현장조사 교환 파일 (.strsv = SQLite).

Package layout
  meta(key, value)              format/version/project/exported/purposes/picklists
  sheets(id, analysis_id, seq, name, origin, extents, members, background, grid)   — drawings (JSON text)
  surveys(uid, sheet_id, updated, deleted, rec)  — one row per 검측위치, rec = full record JSON
  photos(uid, survey_uid, name, mime, data, created) — photo files as BLOBs
  sketches(uid, sheet_id, updated, deleted, data) — 현장 스케치 (보·기둥·자유선·글자), data = JSON (도면 절대좌표)
  sheet_ext(sheet_id, suid, kind, image, mime, iw, ih, rect) — DXF 없이 만든 도면(빈 도면·사진): 배경 이미지와 고유값

The PC exports a project (all saved floors), the phone app edits the same file
(adds/edits/deletes records, takes photos) and the PC imports it back:
newer `updated` wins per record uid, tombstones (deleted=1) remove records,
photos are written into the project photo folder.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import re
import mimetypes
import os
import sqlite3
from datetime import datetime

from . import db
from . import survey as SV

FORMAT = "strcad-survey"
VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sheets (id INTEGER PRIMARY KEY, analysis_id INTEGER, seq INTEGER, name TEXT,
    origin TEXT, extents TEXT, members TEXT, background TEXT, grid TEXT);
CREATE TABLE IF NOT EXISTS surveys (uid TEXT PRIMARY KEY, sheet_id INTEGER, updated TEXT, deleted INTEGER DEFAULT 0,
    rec TEXT);
CREATE TABLE IF NOT EXISTS photos (uid TEXT PRIMARY KEY, survey_uid TEXT, name TEXT, mime TEXT, data BLOB,
    created TEXT);
CREATE TABLE IF NOT EXISTS sketches (uid TEXT PRIMARY KEY, sheet_id INTEGER, updated TEXT, deleted INTEGER DEFAULT 0,
    data TEXT);
CREATE TABLE IF NOT EXISTS sheet_ext (sheet_id INTEGER PRIMARY KEY, suid TEXT, kind TEXT, image BLOB, mime TEXT,
    iw INTEGER, ih INTEGER, rect TEXT);
"""
KIND_CODE = {"column": "c", "girder": "g", "beam": "b", "wall": "w"}


def photo_uid(path):
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            h.update(f.read(1 << 20))
        h.update(str(os.path.getsize(path)).encode())
    except OSError:
        h.update(path.encode("utf-8"))
    return "ph_" + h.hexdigest()[:16]


def _sheet_geometry(res):
    x0, y0, x1, y1 = res.extents
    ox, oy = round(x0), round(y0)

    def P(x, y):
        return [round(x - ox), round(y - oy)]
    mem = []
    for m in res.members:
        d = {"i": m.id, "k": KIND_CODE[m.kind], "n": m.name or "", "s": m.size_text()}
        if m.kind == "column":
            d["c"] = P(*m.center)
            d["p"] = [v for q in m.polygon for v in P(*q)] if m.polygon else []
            d["b"], d["h"] = round(m.b), round(m.h)
        else:
            pts = m.polyline(12)
            d["l"] = [v for q in pts for v in P(*q)]
            d["L"] = round(m.length_cc)
            d["ln"] = round(m.length_clear)
            d["w"] = round(m.width)
            if m.depth:
                d["d"] = round(m.depth)
            if m.curved:
                d["cv"] = 1
        mem.append(d)
    bg = [v for s in res.background for v in (*P(s.x1, s.y1), *P(s.x2, s.y2))]
    gr = [v for s in res.grid for v in (*P(s.x1, s.y1), *P(s.x2, s.y2))]
    return {"ox": ox, "oy": oy}, {"w": round(x1 - x0), "h": round(y1 - y0)}, mem, bg, gr


def _write_sheet_ext(con, k, res):
    """빈 도면·사진 도면이면 배경 이미지(축소본)와 고유값을 함께 보냄."""
    kind = getattr(res, "kind", "")
    if kind not in ("photo", "blank") and not getattr(res, "bg_image", ""):
        return
    if not getattr(res, "sheet_uid", ""):
        from .sheets import new_uid
        res.sheet_uid = new_uid()
    blob, iw, ih = None, 0, 0
    p = getattr(res, "bg_image", "")
    if p and os.path.exists(p):
        try:
            import io
            from PIL import Image
            im = Image.open(p).convert("RGB")
            iw, ih = im.size
            kk = min(1.0, 2400 / max(iw, ih))
            if kk < 1:
                im = im.resize((round(iw * kk), round(ih * kk)), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=82)
            blob = buf.getvalue()
            iw, ih = im.size
        except Exception:  # noqa: BLE001
            blob = None
    con.execute("INSERT OR REPLACE INTO sheet_ext VALUES (?,?,?,?,?,?,?,?)",
                (k, res.sheet_uid, kind or "photo", blob, "image/jpeg" if blob else None, iw, ih,
                 json.dumps(list(res.bg_rect)) if getattr(res, "bg_rect", None) else None))


def _sheet_from_package(con, sid, row, project, log):
    """휴대폰에서 만든 도면(빈 도면·사진) → PC 분석으로 새로 만들거나 이미 있는 것(같은 고유값)을 찾음. → aid"""
    from .model import AnalysisResult, Segment
    from .sheets import SHEET_DIR
    try:
        ext = con.execute("SELECT suid, kind, image, rect FROM sheet_ext WHERE sheet_id=?", (sid,)).fetchone()
    except sqlite3.OperationalError:
        ext = None
    if not ext:
        return None, False
    suid, kind, image, rect = ext
    for r in db.list_analyses():
        try:
            _n, res0, _cs = db.load(r[0])
        except Exception:  # noqa: BLE001
            continue
        if getattr(res0, "sheet_uid", "") == suid:
            return r[0], False
    name, origin, extents, bg, grid = row
    o = json.loads(origin or '{"ox":0,"oy":0}')
    e = json.loads(extents or '{"w":30000,"h":20000}')
    ox, oy = o.get("ox", 0), o.get("oy", 0)
    res = AnalysisResult(extents=(ox, oy, ox + e["w"], oy + e["h"]), kind=kind or "photo", source_file="")

    def segs(flat, layer):
        flat = json.loads(flat or "[]")
        return [Segment(flat[i] + ox, flat[i + 1] + oy, flat[i + 2] + ox, flat[i + 3] + oy, layer)
                for i in range(0, len(flat) - 3, 4)]
    res.background = segs(bg, "blank")
    res.grid = segs(grid, "grid")
    res.sheet_uid = suid
    if image:
        os.makedirs(SHEET_DIR, exist_ok=True)
        p = os.path.join(SHEET_DIR, f"{suid}.jpg")
        with open(p, "wb") as f:
            f.write(image)
        res.bg_image = p
        r = json.loads(rect) if rect else [0, 0, e["w"], e["h"]]
        res.bg_rect = tuple(r)
    aid = db.save(res, None, name, None, project=project)
    log(f"휴대폰에서 만든 도면 '{name}'을(를) 새 분석으로 추가 (id {aid})")
    return aid, True


def export_package(path, project, cfg, sheet_ids=None, log=print):
    """Write all saved floors of `project` (or the given analysis ids) to a .strsv file."""
    if sheet_ids is None:
        sheet_ids = [i for i, _ in db.project_sheets(project)]
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    P = SV.purposes(cfg)
    meta = {"format": FORMAT, "version": str(VERSION), "project": project,
            "exported": datetime.now().isoformat(timespec="seconds"), "app": "StrCAD CAD Analysis",
            "purposes": json.dumps(P, ensure_ascii=False),
            "picklists": json.dumps(cfg.get("picklists", {}), ensure_ascii=False)}
    con.executemany("INSERT INTO meta VALUES (?,?)", list(meta.items()))
    n_rec = n_ph = n_sk = 0
    for k, aid in enumerate(sheet_ids, 1):
        name, res, cs = db.load(aid)
        mt = db.meta(aid)
        origin, ext, mem, bg, gr = _sheet_geometry(res)
        con.execute("INSERT INTO sheets VALUES (?,?,?,?,?,?,?,?,?)",
                    (k, aid, mt[2] if mt else k, name, json.dumps(origin), json.dumps(ext),
                     json.dumps(mem, ensure_ascii=False, separators=(",", ":")),
                     json.dumps(bg, separators=(",", ":")), json.dumps(gr, separators=(",", ":"))))
        _write_sheet_ext(con, k, res)
        stamped = False
        for r in res.surveys:
            if "uid" not in r or "updated" not in r:
                stamped = True
            SV.migrate(r)
        if stamped:      # keep the uids just given to older records, or the phone's edits would look new
            db.save(res, cs if not cs.is_identity() else None, name, aid,
                    project=mt[1] if mt else project, seq=mt[2] if mt else None)
        for r in res.surveys:
            rec = dict(r)
            uids = []
            for p in r.get("photos", []):
                if not os.path.exists(p):
                    continue
                u = photo_uid(p)
                uids.append(u)
                if not con.execute("SELECT 1 FROM photos WHERE uid=?", (u,)).fetchone():
                    with open(p, "rb") as f:
                        data = f.read()
                    con.execute("INSERT INTO photos VALUES (?,?,?,?,?,?)",
                                (u, r["uid"], os.path.basename(p), mimetypes.guess_type(p)[0] or "image/jpeg",
                                 data, r.get("updated", "")))
                    n_ph += 1
            rec["photos"] = uids
            con.execute("INSERT INTO surveys VALUES (?,?,?,?,?)",
                        (r["uid"], k, r.get("updated", ""), 0, json.dumps(rec, ensure_ascii=False)))
            n_rec += 1
        for sk in getattr(res, "sketches", []):
            con.execute("INSERT OR REPLACE INTO sketches VALUES (?,?,?,?,?)",
                        (sk["uid"], k, sk.get("updated", ""), 1 if sk.get("deleted") else 0,
                         json.dumps(sk, ensure_ascii=False, separators=(",", ":"))))
            n_sk += 0 if sk.get("deleted") else 1
    con.commit()
    con.close()
    log(f"모바일 내보내기: 도면 {len(sheet_ids)}장, 검측위치 {n_rec}개, 사진 {n_ph}장"
        + (f", 스케치 {n_sk}개" if n_sk else "") + f" → {path}")
    return {"sheets": len(sheet_ids), "records": n_rec, "photos": n_ph, "sketches": n_sk}


def read_meta(path):
    con = sqlite3.connect(path)
    try:
        return dict(con.execute("SELECT key, value FROM meta").fetchall())
    finally:
        con.close()


PH_RE = re.compile(r"ph_[0-9a-f]{16}")


def originals_index(base, depth=4):
    """휴대폰 원본 사진(파일명에 ph_<id>) 찾기 → {uid: path}. .strsv 옆에 'StrCAD/사진/…' 폴더째 옮긴 경우."""
    out = {}
    if not base or not os.path.isdir(base):
        return out
    base_depth = base.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(base):
        if root.count(os.sep) - base_depth >= depth:
            dirs[:] = []
        for fn in files:
            if not fn.lower().endswith((".jpg", ".jpeg", ".png", ".heic", ".webp")):
                continue
            m = PH_RE.search(fn)
            key = m.group(0) if m else "name:" + os.path.splitext(fn)[0]      # 새 이름 규칙은 파일 이름으로 찾음
            p = os.path.join(root, fn)
            if key not in out or os.path.getsize(p) > os.path.getsize(out[key]):
                out[key] = p
    return out


def find_photo_file(cfg, project, uid, name=None):
    """프로젝트 사진 폴더에서 이름에 uid가 들어간 파일 — 새 이름 규칙(프로젝트_도면_날짜_번호_용도_순번)은 이름으로."""
    base = os.path.dirname(SV.photo_folder(cfg, project, "x"))
    stem = os.path.splitext(os.path.basename(name))[0] if name else None
    for root, _d, files in os.walk(base):
        for fn in files:
            if uid in fn or (stem and os.path.splitext(fn)[0] == stem):
                return os.path.join(root, fn)
    return None


def _repoint_photo(project, old, new):
    """확장자가 바뀐 원본: DB 검측기록의 사진 경로 갱신"""
    for aid, _name in db.project_sheets(project):
        nm, res, cs = db.load(aid)
        hit = False
        for r in res.surveys:
            if old in r.get("photos", []):
                r["photos"] = [new if p == old else p for p in r["photos"]]
                hit = True
        if hit:
            mt = db.meta(aid)
            db.save(res, cs if not cs.is_identity() else None, nm, aid, project=mt[1] if mt else project,
                    seq=mt[2] if mt else None)


def merge_sketches(con, sid, res, report):
    """휴대폰 스케치를 PC 도면에 합침 (uid별 최신 updated 우선, 삭제는 표시만 남김)."""
    try:
        rows = con.execute("SELECT uid, updated, deleted, data FROM sketches WHERE sheet_id=?", (sid,)).fetchall()
    except sqlite3.OperationalError:        # 스케치 기능 이전 파일
        return False
    if not hasattr(res, "sketches") or res.sketches is None:
        res.sketches = []
    have = {s.get("uid"): i for i, s in enumerate(res.sketches)}
    changed = False
    for uid, updated, deleted, data in rows:
        i = have.get(uid)
        if i is not None and (res.sketches[i].get("updated") or "") >= (updated or ""):
            continue
        try:
            sk = json.loads(data)
        except ValueError:
            continue
        sk["uid"] = uid
        sk["updated"] = updated
        if deleted:
            sk["deleted"] = 1
        if i is None:
            have[uid] = len(res.sketches)
            res.sketches.append(sk)
        else:
            res.sketches[i] = sk
        report["sketches"] += 1
        changed = True
    return changed


def import_package(path, cfg, log=print, originals_dir="auto"):
    """Merge a .strsv edited on the phone back into the local DB. Returns a report dict.
    originals_dir: 휴대폰 원본 사진을 찾을 폴더 ('auto' = .strsv 가 있는 폴더, None = 찾지 않음)"""
    originals = originals_index(os.path.dirname(os.path.abspath(path)) if originals_dir == "auto" else originals_dir)
    con = sqlite3.connect(path)
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    if meta.get("format") != FORMAT:
        con.close()
        raise ValueError("StrCAD 현장조사 파일(.strsv)이 아닙니다.")
    project = meta.get("project", "")
    # purposes / pick lists added on the phone → keep them on the PC too
    try:
        for name, p in json.loads(meta.get("purposes", "{}")).items():
            if name not in SV.DEFAULT_PURPOSES:
                cfg.setdefault("survey_purposes", {}).setdefault(name, p)
        for k, vals in json.loads(meta.get("picklists", "{}")).items():
            for v in vals:
                SV.add_pick(cfg, k, v)
    except ValueError:
        pass
    report = {"sheets": 0, "added": 0, "updated": 0, "deleted": 0, "kept": 0, "photos": 0, "renumbered": 0,
              "missing": [], "originals": 0, "sketches": 0}
    photos = {u: (n, d) for u, n, d in con.execute("SELECT uid, name, data FROM photos")}
    rows = con.execute("SELECT id, analysis_id, name, origin, extents, background, grid FROM sheets ORDER BY seq").fetchall()
    for sid, aid, name, origin, extents, bgj, gridj in rows:
        lname = None
        if aid is not None:
            try:
                lname, res, cs = db.load(aid)
            except KeyError:
                lname = None
        if lname is None:
            aid, created = _sheet_from_package(con, sid, (name, origin, extents, bgj, gridj), project, log)
            if aid is None:
                report["missing"].append(name)
                continue
            if created:
                report["new_sheets"] = report.get("new_sheets", 0) + 1
            lname, res, cs = db.load(aid)
        mt = db.meta(aid)
        folder = SV.photo_folder(cfg, mt[1] if mt else project, lname)
        local = {}
        for r in res.surveys:
            SV.migrate(r)
            local[r["uid"]] = r
        known_paths = {}
        for r in res.surveys:
            for p in r.get("photos", []):
                if os.path.exists(p):
                    known_paths[photo_uid(p)] = p
        changed = False
        for uid, updated, deleted, rj in con.execute(
                "SELECT uid, updated, deleted, rec FROM surveys WHERE sheet_id=?", (sid,)).fetchall():
            cur = local.get(uid)
            if cur is not None and (cur.get("updated") or "") >= (updated or ""):
                report["kept"] += 1
                continue
            if deleted:
                if cur is not None:
                    res.surveys.remove(cur)
                    report["deleted"] += 1
                    changed = True
                continue
            rec = json.loads(rj)
            if cur is None and any(int(x.get("no") or 0) == int(rec.get("no") or 0) for x in res.surveys):
                old = rec.get("no")
                rec["no"] = SV.next_no(res.surveys)
                rec["memo"] = (rec.get("memo", "") + f"\n(가져오기 시 번호 {old}→{rec['no']} 변경)").strip()
                report["renumbered"] += 1
            # photo uids → files in the project photo folder
            paths = []
            for u in rec.get("photos", []):
                if u in known_paths:
                    paths.append(known_paths[u])
                elif u in photos and PH_RE.fullmatch(u or ""):
                    # 휴대폰 사진: 파일 이름에 uid → 같은 사진은 한 파일, 원본이 있으면 원본으로
                    pname, data = photos[u]
                    pre = f"{int(rec.get('no') or 0):03d}_"
                    if not pname.startswith("ph_"):
                        pre = ""                          # 새 이름 규칙(프로젝트_도면_날짜_번호_용도_순번)은 그대로
                    orig = originals.get(u) or originals.get("name:" + os.path.splitext(pname)[0])
                    if orig:
                        pname = os.path.splitext(pname)[0] + os.path.splitext(orig)[1].lower()
                    os.makedirs(folder, exist_ok=True)
                    dst = find_photo_file(cfg, mt[1] if mt else project, u, None if PH_RE.search(pname) else pname) or \
                        os.path.join(folder, pname if pname.startswith(pre) else pre + pname)
                    if orig and os.path.splitext(dst)[1].lower() != os.path.splitext(orig)[1].lower():
                        dst = os.path.splitext(dst)[0] + os.path.splitext(orig)[1].lower()
                    if orig and (not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(orig)):
                        shutil.copyfile(orig, dst)
                        report["originals"] += 1
                        report["photos"] += 1
                    elif not os.path.exists(dst):
                        with open(dst, "wb") as f:
                            f.write(data)
                        report["photos"] += 1
                    known_paths[u] = dst
                    paths.append(dst)
                elif u in photos:
                    pname, data = photos[u]
                    os.makedirs(folder, exist_ok=True)
                    pre = f"{int(rec.get('no') or 0):03d}_"
                    dst = os.path.join(folder, pname if pname.startswith(pre) else pre + pname)
                    k = 1
                    while os.path.exists(dst) and photo_uid(dst) != u:
                        stem, ext = os.path.splitext(dst)
                        dst = f"{stem}_{k}{ext}"
                        k += 1
                    if not os.path.exists(dst):
                        with open(dst, "wb") as f:
                            f.write(data)
                        report["photos"] += 1
                    known_paths[u] = dst
                    paths.append(dst)
            rec["photos"] = paths
            if cur is not None:
                rec["id"] = cur["id"]
                res.surveys[res.surveys.index(cur)] = rec
                report["updated"] += 1
            else:
                rec["id"] = max((s["id"] for s in res.surveys), default=0) + 1
                res.surveys.append(rec)
                report["added"] += 1
            local[uid] = rec
            changed = True
        if merge_sketches(con, sid, res, report):
            changed = True
        if changed:
            db.save(res, cs if not cs.is_identity() else None, lname, aid,
                    project=mt[1] if mt else project, seq=mt[2] if mt else None)
        report["sheets"] += 1
    con.close()
    log(f"모바일 가져오기: 추가 {report['added']}, 수정 {report['updated']}, 삭제 {report['deleted']}, "
        f"변경 없음 {report['kept']}, 사진 {report['photos']}장"
        + (f" (원본 {report['originals']}장)" if report["originals"] else "")
        + (f", 번호 변경 {report['renumbered']}" if report["renumbered"] else "")
        + (f", 스케치 {report['sketches']}건 반영" if report["sketches"] else "")
        + (f" · DB에 없는 도면: {', '.join(report['missing'])}" if report["missing"] else ""))
    return report


# ============================================================================
#  Wi-Fi link: the PC serves the mobile app and the package to phones on the same network
# ============================================================================
import socket
import tempfile
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from .theme import resource as _resource  # noqa: E402
MOBILE_DIR = _resource("mobile")


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class LinkServer:
    """http://<PC IP>:<port>/  → mobile app (PC에서 받기 / PC로 보내기 enabled)."""

    def __init__(self, cfg, port=8765, on_imported=None, log=print):
        self.cfg, self.port, self.on_imported, self.log = cfg, port, on_imported, log
        self.httpd = None
        self.lock = threading.Lock()

    @property
    def url(self):
        return f"http://{local_ip()}:{self.port}/"

    def start(self):
        outer = self

        class H(SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=MOBILE_DIR, **k)

            def log_message(self, *a):
                pass

            def end_headers(self):
                # the Android app (APK) calls from its own origin → allow cross-origin requests on the LAN
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                super().end_headers()

            def do_OPTIONS(self):
                self.send_response(204)
                self.end_headers()

            def _photo(self, qs):
                """휴대폰 원본 사진 1장: 가져오기로 만든 축소본(이름에 uid)을 원본으로 교체"""
                uid = qs.get("uid", [""])[0]
                project = qs.get("project", [""])[0]
                name = os.path.basename(qs.get("name", [""])[0]) or f"{uid}.jpg"
                n = int(self.headers.get("Content-Length") or 0)
                data = self.rfile.read(n)
                if not PH_RE.fullmatch(uid) or not data:
                    return self._json(400, {"error": "bad photo"})
                with outer.lock:
                    cur = find_photo_file(outer.cfg, project, uid, name if not PH_RE.search(name) else None)
                    ext = os.path.splitext(name)[1].lower() or ".jpg"
                    if cur is None:
                        folder = os.path.join(os.path.dirname(SV.photo_folder(outer.cfg, project, "x")), "_원본(미연결)")
                        os.makedirs(folder, exist_ok=True)
                        dst = os.path.join(folder, name)
                    else:
                        dst = os.path.splitext(cur)[0] + ext
                    with open(dst, "wb") as f:
                        f.write(data)
                    if cur is not None and dst != cur:
                        _repoint_photo(project, cur, dst)
                        try:
                            os.remove(cur)
                        except OSError:
                            pass
                outer.log(f"원본 사진 수신: {os.path.basename(dst)} ({len(data) / 1e6:.1f} MB)")
                return self._json(200, {"ok": True, "path": dst})

            def _json(self, code, obj):
                b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                u = urlparse(self.path)
                if u.path == "/api/ping":
                    return self._json(200, {"app": "strcad", "ok": True})
                if u.path == "/api/projects":
                    return self._json(200, [p for p in db.projects() if p is not None])
                if u.path == "/api/package":
                    project = parse_qs(u.query).get("project", [""])[0]
                    if not db.project_sheets(project):
                        return self._json(404, {"error": f"프로젝트 '{project}' 에 저장된 도면이 없습니다."})
                    fd, tmp = tempfile.mkstemp(suffix=".strsv")
                    os.close(fd)
                    try:
                        with outer.lock:
                            export_package(tmp, project, outer.cfg, log=outer.log)
                        with open(tmp, "rb") as f:
                            data = f.read()
                    finally:
                        os.remove(tmp)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if u.path in ("", "/"):
                    self.path = "/index.html"
                return super().do_GET()

            def do_POST(self):
                u = urlparse(self.path)
                if u.path == "/api/photo":
                    return self._photo(parse_qs(u.query))
                if u.path != "/api/upload":
                    return self._json(404, {"error": "not found"})
                n = int(self.headers.get("Content-Length") or 0)
                data = self.rfile.read(n)
                fd, tmp = tempfile.mkstemp(suffix=".strsv")
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                try:
                    with outer.lock:
                        rep = import_package(tmp, outer.cfg, log=outer.log, originals_dir=None)
                    if outer.on_imported:
                        outer.on_imported(rep)
                    return self._json(200, rep)
                except Exception as e:      # noqa: BLE001
                    return self._json(400, {"error": str(e)})
                finally:
                    os.remove(tmp)

        H.extensions_map = dict(SimpleHTTPRequestHandler.extensions_map, **{
            ".wasm": "application/wasm", ".webmanifest": "application/manifest+json", ".js": "text/javascript"})
        self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self.url

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
