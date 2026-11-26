"""StrCAD 협업 서버 — 여러 검토자가 같은 현장조사를 함께 (실시간 공유 · 오프라인 후 공유).

· 개인 계정(아이디·비밀번호) + 처음 가입할 때 팀 코드. 처음 가입한 사람이 관리자.
· 관리자: 계정 추가 · 사용 중지 · 비밀번호 초기화 · 관리자 지정 · 팀 코드 변경 (휴대폰 앱 › 👥 협업 › 인원 관리)
· 기록(검측위치·균열·하중조사)·스케치·도면은 만든 사람만 고칠 수 있음 (서버가 거부). 다른 사람 것은 보기만.
· 동기화: POST /api/sync — 내가 바꾼 것(push)을 올리고, since(rev) 이후 바뀐 것을 받음. 번호가 겹치면 뒤에 올린 쪽을 다음 번호로.
· 프로젝트 올리기/받기는 휴대폰·PC 공용 .strsv 패키지 그대로 (POST /api/projects, GET /api/package).
· 표준 라이브러리만 사용 → 회사 PC·서버·클라우드 VM 어디서나 `python collab_server.py` 로 실행.
  밖(현장 모바일 데이터)에서 쓰려면 Cloudflare Tunnel(무료, 포트 개방 없이 https 주소) 또는 Tailscale 권장.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

FORMAT = "strcad-survey"
ITER = 200_000
TOKEN_DAYS = 120
ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,20}$")
CRACK_CODES = ("PB", "PC", "PW", "CR", "LK", "DM", "RB", "ET")


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _mobile_dir():
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "mobile")


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, login TEXT UNIQUE COLLATE NOCASE, name TEXT, salt TEXT, hash TEXT,
    role TEXT DEFAULT 'member', active INTEGER DEFAULT 1, created TEXT, last_seen TEXT);
CREATE TABLE IF NOT EXISTS tokens (th TEXT PRIMARY KEY, user_id INTEGER, created TEXT, last TEXT);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY, name TEXT, owner TEXT, created TEXT, meta TEXT, deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS sheets (project_id INTEGER, suid TEXT, seq INTEGER, name TEXT, origin TEXT, extents TEXT, members TEXT,
    background TEXT, grid TEXT, ext_kind TEXT, image BLOB, mime TEXT, iw INTEGER, ih INTEGER, rect TEXT, owner TEXT,
    updated TEXT, rev INTEGER, deleted INTEGER DEFAULT 0, PRIMARY KEY (project_id, suid));
CREATE TABLE IF NOT EXISTS records (project_id INTEGER, uid TEXT, suid TEXT, owner TEXT, updated TEXT, deleted INTEGER DEFAULT 0,
    rec TEXT, rev INTEGER, PRIMARY KEY (project_id, uid));
CREATE TABLE IF NOT EXISTS sketches (project_id INTEGER, uid TEXT, suid TEXT, owner TEXT, updated TEXT, deleted INTEGER DEFAULT 0,
    data TEXT, rev INTEGER, PRIMARY KEY (project_id, uid));
CREATE TABLE IF NOT EXISTS photos (project_id INTEGER, uid TEXT, survey_uid TEXT, owner TEXT, name TEXT, mime TEXT, data BLOB,
    created TEXT, rev INTEGER, PRIMARY KEY (project_id, uid));
CREATE INDEX IF NOT EXISTS rec_rev ON records (project_id, rev);
CREATE INDEX IF NOT EXISTS sk_rev ON sketches (project_id, rev);
CREATE INDEX IF NOT EXISTS sh_rev ON sheets (project_id, rev);
CREATE INDEX IF NOT EXISTS ph_rev ON photos (project_id, rev);
"""

PKG_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sheets (id INTEGER PRIMARY KEY, analysis_id INTEGER, seq INTEGER, name TEXT,
    origin TEXT, extents TEXT, members TEXT, background TEXT, grid TEXT);
CREATE TABLE IF NOT EXISTS surveys (uid TEXT PRIMARY KEY, sheet_id INTEGER, updated TEXT, deleted INTEGER DEFAULT 0, rec TEXT);
CREATE TABLE IF NOT EXISTS photos (uid TEXT PRIMARY KEY, survey_uid TEXT, name TEXT, mime TEXT, data BLOB, created TEXT);
CREATE TABLE IF NOT EXISTS sketches (uid TEXT PRIMARY KEY, sheet_id INTEGER, updated TEXT, deleted INTEGER DEFAULT 0, data TEXT);
CREATE TABLE IF NOT EXISTS sheet_ext (sheet_id INTEGER PRIMARY KEY, suid TEXT, kind TEXT, image BLOB, mime TEXT,
    iw INTEGER, ih INTEGER, rect TEXT);
CREATE TABLE IF NOT EXISTS sheet_uid (sheet_id INTEGER PRIMARY KEY, suid TEXT);
CREATE TABLE IF NOT EXISTS collab (key TEXT PRIMARY KEY, value TEXT);
"""


class CollabError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def _hash(pw: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, ITER).hex()


def _th(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    """서버 데이터 (SQLite 한 파일)."""

    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.lock = threading.RLock()
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        if "aid" not in {r[1] for r in self.con.execute("PRAGMA table_info(sheets)")}:
            self.con.execute("ALTER TABLE sheets ADD COLUMN aid INTEGER")        # PC 분석 번호 (PC 가져오기 때 같은 도면 찾기)
        if not self.kv("team_code"):
            self.set_kv("team_code", "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6)))
        self.con.commit()

    # ---------------------------------------------------------------- basics
    def q(self, sql, p=()):
        return self.con.execute(sql, p).fetchall()

    def one(self, sql, p=()):
        return self.con.execute(sql, p).fetchone()

    def kv(self, k, default=""):
        r = self.one("SELECT v FROM kv WHERE k=?", (k,))
        return r["v"] if r else default

    def set_kv(self, k, v):
        self.con.execute("INSERT OR REPLACE INTO kv (k, v) VALUES (?,?)", (k, str(v)))

    def next_rev(self):
        r = int(self.kv("rev", "0")) + 1
        self.set_kv("rev", r)
        return r

    # ---------------------------------------------------------------- accounts
    @staticmethod
    def public(u):
        return {"id": u["id"], "login": u["login"], "name": u["name"], "role": u["role"], "active": bool(u["active"]),
                "created": u["created"], "last_seen": u["last_seen"]}

    def _new_user(self, login, pw, name, role="member"):
        login, name = (login or "").strip(), (name or "").strip()
        if not ID_RE.match(login):
            raise CollabError("아이디는 영문·숫자·_ . - 로 3~20자입니다.")
        if len(pw or "") < 4:
            raise CollabError("비밀번호는 4자 이상이어야 합니다.")
        if not name:
            raise CollabError("이름을 입력하세요.")
        if self.one("SELECT 1 FROM users WHERE login=?", (login,)):
            raise CollabError("이미 있는 아이디입니다.")
        salt = secrets.token_bytes(16)
        cur = self.con.execute("INSERT INTO users (login, name, salt, hash, role, active, created) VALUES (?,?,?,?,?,1,?)",
                               (login, name, salt.hex(), _hash(pw, salt), role, now_iso()))
        return self.one("SELECT * FROM users WHERE id=?", (cur.lastrowid,))

    def signup(self, login, pw, name, team_code):
        with self.lock:
            first = not self.one("SELECT 1 FROM users")
            if not first and (team_code or "").strip().upper() != self.kv("team_code").upper():
                raise CollabError("팀 코드가 맞지 않습니다. 관리자에게 팀 코드를 받으세요.", 403)
            u = self._new_user(login, pw, name, "admin" if first else "member")
            self.con.commit()
            return self._issue(u)

    def login(self, login, pw):
        with self.lock:
            u = self.one("SELECT * FROM users WHERE login=?", ((login or "").strip(),))
            if not u or not hmac.compare_digest(u["hash"], _hash(pw or "", bytes.fromhex(u["salt"]))):
                time.sleep(0.6)
                raise CollabError("아이디 또는 비밀번호가 맞지 않습니다.", 401)
            if not u["active"]:
                raise CollabError("사용이 중지된 계정입니다. 관리자에게 문의하세요.", 403)
            return self._issue(u)

    def _issue(self, u):
        tok = secrets.token_urlsafe(32)
        self.con.execute("INSERT INTO tokens (th, user_id, created, last) VALUES (?,?,?,?)", (_th(tok), u["id"], now_iso(), now_iso()))
        self.con.commit()
        return {"token": tok, "user": self.public(u)}

    def auth(self, token):
        if not token:
            raise CollabError("로그인이 필요합니다.", 401)
        with self.lock:
            r = self.one("SELECT u.*, t.created AS tc FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.th=?", (_th(token),))
            if not r:
                raise CollabError("로그인이 만료되었습니다. 다시 로그인하세요.", 401)
            if not r["active"]:
                raise CollabError("사용이 중지된 계정입니다.", 403)
            try:
                if (datetime.now() - datetime.fromisoformat(r["tc"])).days > TOKEN_DAYS:
                    raise CollabError("로그인이 만료되었습니다. 다시 로그인하세요.", 401)
            except ValueError:
                pass
            self.con.execute("UPDATE users SET last_seen=? WHERE id=?", (now_iso(), r["id"]))
            self.con.commit()
            return r

    def logout(self, token):
        with self.lock:
            self.con.execute("DELETE FROM tokens WHERE th=?", (_th(token or ""),))
            self.con.commit()

    def users(self, me):
        self._admin(me)
        return [self.public(u) for u in self.q("SELECT * FROM users ORDER BY role='admin' DESC, name")]

    def _admin(self, me):
        if me["role"] != "admin":
            raise CollabError("관리자만 할 수 있습니다.", 403)

    def admin_user(self, me, body):
        """관리자: add / active / role / reset / delete"""
        self._admin(me)
        with self.lock:
            act = body.get("action")
            if act == "add":
                u = self._new_user(body.get("login"), body.get("password"), body.get("name"),
                                   "admin" if body.get("role") == "admin" else "member")
                self.con.commit()
                return self.public(u)
            u = self.one("SELECT * FROM users WHERE id=?", (int(body.get("id") or 0),))
            if not u:
                raise CollabError("없는 계정입니다.", 404)
            admins = self.one("SELECT COUNT(*) AS n FROM users WHERE role='admin' AND active=1")["n"]
            if act == "active":
                on = 1 if body.get("value") else 0
                if not on and u["role"] == "admin" and admins <= 1:
                    raise CollabError("마지막 관리자는 중지할 수 없습니다.")
                self.con.execute("UPDATE users SET active=? WHERE id=?", (on, u["id"]))
                if not on:
                    self.con.execute("DELETE FROM tokens WHERE user_id=?", (u["id"],))
            elif act == "role":
                role = "admin" if body.get("value") == "admin" else "member"
                if role == "member" and u["role"] == "admin" and admins <= 1:
                    raise CollabError("관리자가 한 명은 있어야 합니다.")
                self.con.execute("UPDATE users SET role=? WHERE id=?", (role, u["id"]))
            elif act == "reset":
                pw = body.get("password") or ""
                if len(pw) < 4:
                    raise CollabError("새 비밀번호는 4자 이상")
                salt = secrets.token_bytes(16)
                self.con.execute("UPDATE users SET salt=?, hash=? WHERE id=?", (salt.hex(), _hash(pw, salt), u["id"]))
                self.con.execute("DELETE FROM tokens WHERE user_id=?", (u["id"],))
            elif act == "name":
                if not (body.get("value") or "").strip():
                    raise CollabError("이름을 입력하세요.")
                self.con.execute("UPDATE users SET name=? WHERE id=?", (body["value"].strip(), u["id"]))
            else:
                raise CollabError("알 수 없는 작업")
            self.con.commit()
            return self.public(self.one("SELECT * FROM users WHERE id=?", (u["id"],)))

    def change_password(self, me, old, new):
        with self.lock:
            if not hmac.compare_digest(me["hash"], _hash(old or "", bytes.fromhex(me["salt"]))):
                raise CollabError("현재 비밀번호가 맞지 않습니다.", 403)
            if len(new or "") < 4:
                raise CollabError("새 비밀번호는 4자 이상")
            salt = secrets.token_bytes(16)
            self.con.execute("UPDATE users SET salt=?, hash=? WHERE id=?", (salt.hex(), _hash(new, salt), me["id"]))
            self.con.commit()

    def team_code(self, me, new=None):
        self._admin(me)
        with self.lock:
            if new is not None:
                new = re.sub(r"\s", "", new).upper()
                if len(new) < 4:
                    raise CollabError("팀 코드는 4자 이상")
                self.set_kv("team_code", new)
                self.con.commit()
            return self.kv("team_code")

    # ---------------------------------------------------------------- projects
    def projects(self, me):
        out = []
        for p in self.q("SELECT * FROM projects WHERE deleted=0 ORDER BY id DESC"):
            pid = p["id"]
            n = self.one("SELECT COUNT(*) AS n FROM records WHERE project_id=? AND deleted=0", (pid,))["n"]
            ns = self.one("SELECT COUNT(*) AS n FROM sheets WHERE project_id=? AND deleted=0", (pid,))["n"]
            who = [r["owner"] for r in self.q("SELECT DISTINCT owner FROM records WHERE project_id=? AND deleted=0", (pid,))]
            last = self.one("SELECT MAX(updated) AS u FROM records WHERE project_id=?", (pid,))["u"]
            out.append({"id": pid, "name": p["name"], "owner": p["owner"], "created": p["created"], "records": n,
                        "sheets": ns, "people": len(who), "updated": last or p["created"]})
        return out

    def delete_project(self, me, pid):
        with self.lock:
            p = self.one("SELECT * FROM projects WHERE id=?", (pid,))
            if not p:
                raise CollabError("없는 프로젝트", 404)
            if me["role"] != "admin" and p["owner"].lower() != me["login"].lower():
                raise CollabError("관리자나 프로젝트를 올린 사람만 지울 수 있습니다.", 403)
            self.con.execute("UPDATE projects SET deleted=1 WHERE id=?", (pid,))
            self.con.commit()

    def _project(self, pid):
        p = self.one("SELECT * FROM projects WHERE id=? AND deleted=0", (int(pid or 0),))
        if not p:
            raise CollabError("없는 프로젝트입니다.", 404)
        return p

    def import_package(self, me, data: bytes, name=None):
        """.strsv → 새 협업 프로젝트. 주인 없는 기록·스케치·도면은 올린 사람 것."""
        fd, tmp = tempfile.mkstemp(suffix=".strsv")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            src = sqlite3.connect(tmp)
            src.row_factory = sqlite3.Row
            meta = {r["key"]: r["value"] for r in src.execute("SELECT key, value FROM meta")}
            if meta.get("format") != FORMAT:
                raise CollabError("StrCAD 현장조사 파일(.strsv)이 아닙니다.")
            tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            me_login, me_name = me["login"], me["name"]
            with self.lock:
                pname = (name or meta.get("project") or "현장조사").strip()
                pm = {k: meta.get(k, "") for k in ("purposes", "picklists")}
                cur = self.con.execute("INSERT INTO projects (name, owner, created, meta) VALUES (?,?,?,?)",
                                       (pname, me_login, now_iso(), json.dumps(pm, ensure_ascii=False)))
                pid = cur.lastrowid
                rev = self.next_rev()
                sid2suid = {}
                ext = {}
                if "sheet_ext" in tables:
                    for r in src.execute("SELECT * FROM sheet_ext"):
                        ext[r["sheet_id"]] = r
                suids = {}
                if "sheet_uid" in tables:
                    suids = {r["sheet_id"]: r["suid"] for r in src.execute("SELECT * FROM sheet_uid")}
                for s in src.execute("SELECT * FROM sheets ORDER BY seq, id"):
                    e = ext.get(s["id"])
                    suid = suids.get(s["id"]) or (e["suid"] if e is not None and e["suid"] else "sh_" + secrets.token_hex(8))
                    sid2suid[s["id"]] = suid
                    self.con.execute(
                        "INSERT OR REPLACE INTO sheets (project_id, suid, seq, name, origin, extents, members, background, grid,"
                        " ext_kind, image, mime, iw, ih, rect, owner, updated, rev, aid) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (pid, suid, s["seq"], s["name"], s["origin"], s["extents"], s["members"], s["background"], s["grid"],
                         e["kind"] if e is not None else "", e["image"] if e is not None else None,
                         e["mime"] if e is not None else None, e["iw"] if e is not None else None,
                         e["ih"] if e is not None else None, e["rect"] if e is not None else None, me_login, now_iso(), rev,
                         s["analysis_id"]))
                for r in src.execute("SELECT * FROM surveys"):
                    if r["deleted"] or r["sheet_id"] not in sid2suid:
                        continue
                    rec = json.loads(r["rec"])
                    rec.setdefault("owner", me_login)
                    if not rec.get("inspector"):
                        rec["inspector"] = me_name
                    self.con.execute("INSERT OR REPLACE INTO records (project_id, uid, suid, owner, updated, deleted, rec, rev)"
                                     " VALUES (?,?,?,?,?,0,?,?)", (pid, r["uid"], sid2suid[r["sheet_id"]], rec["owner"],
                                                                   r["updated"] or now_iso(), json.dumps(rec, ensure_ascii=False), rev))
                if "sketches" in tables:
                    for r in src.execute("SELECT * FROM sketches"):
                        if r["deleted"] or r["sheet_id"] not in sid2suid:
                            continue
                        d = json.loads(r["data"])
                        d.setdefault("owner", me_login)
                        self.con.execute("INSERT OR REPLACE INTO sketches (project_id, uid, suid, owner, updated, deleted, data, rev)"
                                         " VALUES (?,?,?,?,?,0,?,?)", (pid, r["uid"], sid2suid[r["sheet_id"]], d["owner"],
                                                                       r["updated"] or now_iso(), json.dumps(d, ensure_ascii=False), rev))
                for r in src.execute("SELECT * FROM photos"):
                    self.con.execute("INSERT OR REPLACE INTO photos (project_id, uid, survey_uid, owner, name, mime, data, created, rev)"
                                     " VALUES (?,?,?,?,?,?,?,?,?)", (pid, r["uid"], r["survey_uid"], me_login, r["name"], r["mime"],
                                                                     r["data"], r["created"], rev))
                self.con.commit()
                return {"id": pid, "name": pname, "rev": rev}
        finally:
            try:
                src.close()
            except Exception:  # noqa: BLE001
                pass
            os.remove(tmp)

    def export_package(self, pid, server_url="") -> bytes:
        """협업 프로젝트 → .strsv (휴대폰 열기 · PC 가져오기 공용)."""
        p = self._project(pid)
        fd, tmp = tempfile.mkstemp(suffix=".strsv")
        os.close(fd)
        os.remove(tmp)
        try:
            con = sqlite3.connect(tmp)
            con.executescript(PKG_SCHEMA)
            pm = json.loads(p["meta"] or "{}")
            with self.lock:
                rev = int(self.kv("rev", "0"))
                meta = {"format": FORMAT, "version": "1", "project": p["name"], "exported": now_iso(),
                        "app": "StrCAD 협업 서버", "purposes": pm.get("purposes") or "{}", "picklists": pm.get("picklists") or "{}"}
                con.executemany("INSERT INTO meta VALUES (?,?)", list(meta.items()))
                con.executemany("INSERT INTO collab VALUES (?,?)", [("project_id", str(pid)), ("project", p["name"]),
                                                                     ("rev", str(rev)), ("server", server_url)])
                suid2id = {}
                for k, s in enumerate(self.q("SELECT * FROM sheets WHERE project_id=? AND deleted=0 ORDER BY seq, rowid", (pid,)), 1):
                    suid2id[s["suid"]] = k
                    con.execute("INSERT INTO sheets VALUES (?,?,?,?,?,?,?,?,?)", (k, s["aid"], s["seq"] or k, s["name"], s["origin"],
                                                                                  s["extents"], s["members"], s["background"], s["grid"]))
                    con.execute("INSERT INTO sheet_uid VALUES (?,?)", (k, s["suid"]))
                    if s["ext_kind"]:
                        con.execute("INSERT INTO sheet_ext VALUES (?,?,?,?,?,?,?,?)", (k, s["suid"], s["ext_kind"], s["image"], s["mime"],
                                                                                       s["iw"], s["ih"], s["rect"]))
                live = set()
                for r in self.q("SELECT * FROM records WHERE project_id=? AND deleted=0", (pid,)):
                    if r["suid"] in suid2id:
                        con.execute("INSERT INTO surveys VALUES (?,?,?,0,?)", (r["uid"], suid2id[r["suid"]], r["updated"], r["rec"]))
                        live.add(r["uid"])
                for r in self.q("SELECT * FROM sketches WHERE project_id=? AND deleted=0", (pid,)):
                    if r["suid"] in suid2id:
                        con.execute("INSERT INTO sketches VALUES (?,?,?,0,?)", (r["uid"], suid2id[r["suid"]], r["updated"], r["data"]))
                for r in self.q("SELECT * FROM photos WHERE project_id=?", (pid,)):
                    if r["survey_uid"] in live:
                        con.execute("INSERT INTO photos VALUES (?,?,?,?,?,?)", (r["uid"], r["survey_uid"], r["name"], r["mime"],
                                                                                r["data"], r["created"]))
            con.commit()
            con.close()
            with open(tmp, "rb") as f:
                return f.read()
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    # ---------------------------------------------------------------- sync
    def _owner_ok(self, me, owner):
        return not owner or owner.lower() == me["login"].lower()

    def _relabel(self, pid, rec, uid, owner, labmap):
        """균열번호(PW1 …)가 다른 검토자 것과 겹치면 다음 번호로 (같은 사람의 같은 번호 = 여러 위치, 그대로).
        검측 번호(no)는 겹쳐도 그대로 두고 '번호 정리'(검토자별 000·100·200번대)로 정리."""
        lab = rec.get("label") or ""
        m = re.match(r"^([A-Z]{2})(\d+)$", lab)
        if not m:
            return []
        if lab not in labmap:
            other = [json.loads(r["rec"]).get("label") for r in self.q(
                "SELECT rec FROM records WHERE project_id=? AND deleted=0 AND uid<>? AND lower(owner)<>lower(?)", (pid, uid, owner))]
            if lab in other:
                code = m.group(1)
                allrec = {json.loads(r["rec"]).get("label") for r in self.q("SELECT rec FROM records WHERE project_id=? AND deleted=0", (pid,))}
                allrec |= set(labmap.values())
                nums = [int(x[len(code):]) for x in allrec if x and re.match("^" + code + r"\d+$", x)]
                labmap[lab] = f"{code}{max(nums + [0]) + 1}"
            else:
                labmap[lab] = lab
        new = labmap[lab]
        if new == lab:
            return []
        rec["label"] = new
        return [("label", lab, new)]

    def renumber(self, me, pid):
        """번호 정리: 도면마다 검토자별로 000번대 · 100번대 · 200번대 … (사람이 많거나 100건 넘으면 1000번대 단위).
        사진 이름의 번호도 함께 바뀜 → 휴대폰은 받을 때 원본 사진 이름도 바꿈."""
        p = self._project(pid)
        if me["role"] != "admin" and (p["owner"] or "").lower() != me["login"].lower():
            raise CollabError("번호 정리는 관리자나 프로젝트를 올린 사람만 할 수 있습니다.", 403)
        with self.lock:
            rows = self.q("SELECT rowid, uid, suid, owner, rec FROM records WHERE project_id=? AND deleted=0 ORDER BY rowid", (pid,))
            order = []
            if p["owner"]:
                order.append(p["owner"].lower())
            for r in rows:
                o = (r["owner"] or "").lower()
                if o not in order:
                    order.append(o)
            groups = {}
            for r in rows:
                groups.setdefault((r["suid"], (r["owner"] or "").lower()), []).append(r)
            mx = max((len(v) for v in groups.values()), default=0)
            step = 100 if mx < 100 and len(order) <= 9 else 1000
            rev = self.next_rev()
            changed = 0
            names = {u["login"].lower(): u["name"] for u in self.q("SELECT login, name FROM users")}
            for (suid, owner), lst in groups.items():
                base = order.index(owner) * step
                lst.sort(key=lambda r: (int(json.loads(r["rec"]).get("no") or 0), r["rowid"]))
                for k, r in enumerate(lst, 1):
                    rec = json.loads(r["rec"])
                    old, new = int(rec.get("no") or 0), base + k
                    if old == new:
                        continue
                    rec["no"] = new
                    self.con.execute("UPDATE records SET rec=?, rev=? WHERE project_id=? AND uid=?",
                                     (json.dumps(rec, ensure_ascii=False), rev, pid, r["uid"]))
                    self._rename_photos(pid, r["uid"], [("no", old, new)])
                    self.con.execute("UPDATE photos SET rev=? WHERE project_id=? AND survey_uid=?", (rev, pid, r["uid"]))
                    changed += 1
            self.con.commit()
            return {"changed": changed, "step": step,
                    "bands": [{"login": o, "name": names.get(o, o), "start": i * step} for i, o in enumerate(order)]}

    def _rename_photos(self, pid, uid, changes):
        for kind, old, new in changes:
            for ph in self.q("SELECT uid, name FROM photos WHERE project_id=? AND survey_uid=?", (pid, uid)):
                nm = ph["name"] or ""
                if kind == "label":
                    nm2 = nm.replace(f"crack_{old}_", f"crack_{new}_")
                else:
                    nm2 = re.sub(rf"_{int(old):03d}_([A-Za-z]+)_(\d+)\.", lambda mm: f"_{int(new):03d}_{mm.group(1)}_{mm.group(2)}.", nm)
                if nm2 != nm:
                    self.con.execute("UPDATE photos SET name=? WHERE project_id=? AND uid=?", (nm2, pid, ph["uid"]))

    def sync(self, me, body):
        pid = int(body.get("project") or 0)
        self._project(pid)
        since = int(body.get("since") or 0)
        push = body.get("push") or {}
        rejected, renumbered = [], []
        labmap = {}
        login = me["login"]
        names = {u["login"].lower(): u["name"] for u in self.q("SELECT login, name FROM users")}
        nm = lambda lg: names.get((lg or "").lower(), lg)          # noqa: E731
        with self.lock:
            rev = self.next_rev()
            # sheets
            for s in push.get("sheets") or []:
                suid = s.get("suid")
                if not suid:
                    continue
                cur = self.one("SELECT owner, aid FROM sheets WHERE project_id=? AND suid=?", (pid, suid))
                if cur and not self._owner_ok(me, cur["owner"]):
                    rejected.append({"kind": "sheet", "uid": suid, "reason": f"{nm(cur['owner'])} 님의 도면은 고칠 수 없습니다"})
                    continue
                e = s.get("ext") or {}
                img = base64.b64decode(e["image_b64"]) if e.get("image_b64") else None
                if cur and img is None:
                    old = self.one("SELECT image FROM sheets WHERE project_id=? AND suid=?", (pid, suid))
                    img = old["image"] if old else None
                self.con.execute(
                    "INSERT OR REPLACE INTO sheets (project_id, suid, seq, name, origin, extents, members, background, grid, ext_kind,"
                    " image, mime, iw, ih, rect, owner, updated, rev, deleted, aid) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, suid, s.get("seq"), s.get("name"), s.get("origin"), s.get("extents"), s.get("members"), s.get("background"),
                     s.get("grid"), e.get("kind") or "", img, e.get("mime"), e.get("iw"), e.get("ih"), e.get("rect"),
                     cur["owner"] if cur else login, s.get("updated") or now_iso(), rev, 1 if s.get("deleted") else 0,
                     cur["aid"] if cur else s.get("aid")))
            # photos first (records refer to them)
            for ph in push.get("photos") or []:
                cur = self.one("SELECT owner FROM photos WHERE project_id=? AND uid=?", (pid, ph.get("uid")))
                if cur:
                    continue
                self.con.execute("INSERT INTO photos (project_id, uid, survey_uid, owner, name, mime, data, created, rev) VALUES (?,?,?,?,?,?,?,?,?)",
                                 (pid, ph["uid"], ph.get("survey_uid"), login, ph.get("name"), ph.get("mime") or "image/jpeg",
                                  base64.b64decode(ph.get("data_b64") or ""), ph.get("created") or now_iso(), rev))
            # records
            for r in push.get("records") or []:
                uid = r.get("uid")
                if not uid:
                    continue
                cur = self.one("SELECT owner, updated FROM records WHERE project_id=? AND uid=?", (pid, uid))
                if cur and not self._owner_ok(me, cur["owner"]):
                    rejected.append({"kind": "rec", "uid": uid, "reason": f"{nm(cur['owner'])} 님의 기록은 고칠 수 없습니다"})
                    continue
                rec = r.get("rec")
                rec = json.loads(rec) if isinstance(rec, str) else (rec or {})
                rec["owner"] = cur["owner"] if cur else login
                if not rec.get("inspector"):
                    rec["inspector"] = me["name"]
                if cur and (cur["updated"] or "") > (r.get("updated") or "") and not r.get("deleted"):
                    continue                                  # 같은 사람 다른 기기에서 더 새로 고친 것이 있음
                if not r.get("deleted"):
                    ch = self._relabel(pid, rec, uid, rec["owner"], labmap)
                    if ch:
                        renumbered.append({"uid": uid, "changes": ch})
                self.con.execute("INSERT OR REPLACE INTO records (project_id, uid, suid, owner, updated, deleted, rec, rev) VALUES (?,?,?,?,?,?,?,?)",
                                 (pid, uid, r.get("suid"), rec["owner"], r.get("updated") or now_iso(), 1 if r.get("deleted") else 0,
                                  json.dumps(rec, ensure_ascii=False), rev))
                if renumbered and renumbered[-1]["uid"] == uid:
                    self._rename_photos(pid, uid, renumbered[-1]["changes"])
                    self.con.execute("UPDATE photos SET rev=? WHERE project_id=? AND survey_uid=?", (rev, pid, uid))
            # sketches
            for r in push.get("sketches") or []:
                uid = r.get("uid")
                if not uid:
                    continue
                cur = self.one("SELECT owner, updated FROM sketches WHERE project_id=? AND uid=?", (pid, uid))
                if cur and not self._owner_ok(me, cur["owner"]):
                    rejected.append({"kind": "sk", "uid": uid, "reason": f"{nm(cur['owner'])} 님의 스케치는 고칠 수 없습니다"})
                    continue
                d = r.get("data")
                d = json.loads(d) if isinstance(d, str) else (d or {})
                d["owner"] = cur["owner"] if cur else login
                if cur and (cur["updated"] or "") > (r.get("updated") or "") and not r.get("deleted"):
                    continue
                self.con.execute("INSERT OR REPLACE INTO sketches (project_id, uid, suid, owner, updated, deleted, data, rev) VALUES (?,?,?,?,?,?,?,?)",
                                 (pid, uid, r.get("suid"), d["owner"], r.get("updated") or now_iso(), 1 if r.get("deleted") else 0,
                                  json.dumps(d, ensure_ascii=False), rev))
            self.con.commit()
            # 받기: since 이후 바뀐 것 (방금 올린 것도 포함 — 번호 변경 반영)
            out = {"rev": rev, "rejected": rejected, "renumbered": renumbered, "sheets": [], "records": [], "sketches": [], "photos": []}
            for s in self.q("SELECT project_id, suid, seq, name, origin, extents, members, background, grid, ext_kind, mime, iw, ih, rect, aid,"
                            " owner, updated, deleted, image IS NOT NULL AS has_img FROM sheets WHERE project_id=? AND rev>?", (pid, since)):
                out["sheets"].append({k: s[k] for k in s.keys() if k != "project_id"})
            for r in self.q("SELECT uid, suid, owner, updated, deleted, rec FROM records WHERE project_id=? AND rev>?", (pid, since)):
                out["records"].append(dict(r))
            for r in self.q("SELECT uid, suid, owner, updated, deleted, data FROM sketches WHERE project_id=? AND rev>?", (pid, since)):
                out["sketches"].append(dict(r))
            for r in self.q("SELECT uid, survey_uid, owner, name, mime, created FROM photos WHERE project_id=? AND rev>?", (pid, since)):
                out["photos"].append(dict(r))
            people = {}
            for r in self.q("SELECT owner, COUNT(*) AS n FROM records WHERE project_id=? AND deleted=0 GROUP BY owner", (pid,)):
                people[r["owner"]] = r["n"]
            out["people"] = [{"login": k, "name": names.get((k or "").lower(), k), "records": v} for k, v in people.items()]
            return out

    def photo(self, pid, uid):
        r = self.one("SELECT mime, data FROM photos WHERE project_id=? AND uid=?", (int(pid or 0), uid))
        if not r:
            raise CollabError("사진 없음", 404)
        return r["mime"] or "image/jpeg", r["data"]

    def sheet_image(self, pid, suid):
        r = self.one("SELECT mime, image FROM sheets WHERE project_id=? AND suid=?", (int(pid or 0), suid))
        if not r or r["image"] is None:
            raise CollabError("도면 이미지 없음", 404)
        return r["mime"] or "image/jpeg", r["image"]


# ============================================================================
#  HTTP
# ============================================================================
class CollabServer:
    def __init__(self, data_dir=None, port=8780, host="0.0.0.0", log=print):
        self.data_dir = data_dir or os.path.join(os.path.expanduser("~"), ".strcad", "collab")
        self.port, self.host, self.log = port, host, log
        self.store = Store(os.path.join(self.data_dir, "strcad_collab.db"))
        self.httpd = None
        self.thread = None

    def start(self, background=True):
        outer = self
        mobile = _mobile_dir()

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

            def _send(self, code, body: bytes, ctype="application/json; charset=utf-8", extra=None):
                self.send_response(code)
                self._cors()
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code, obj):
                self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def _me(self):
                h = self.headers.get("Authorization") or ""
                tok = h[7:] if h.startswith("Bearer ") else parse_qs(urlparse(self.path).query).get("t", [""])[0]
                return outer.store.auth(tok)

            def do_OPTIONS(self):
                self.send_response(204)
                self._cors()
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _base(self):
                proto = self.headers.get("X-Forwarded-Proto") or "http"
                return f"{proto}://{self.headers.get('Host', '')}/"

            def do_GET(self):
                u = urlparse(self.path)
                qs = parse_qs(u.query)
                g = lambda k: qs.get(k, [""])[0]         # noqa: E731
                try:
                    if u.path == "/api/ping":
                        return self._json(200, {"ok": True, "app": "StrCAD 협업 서버", "collab": True,
                                                "first": not outer.store.one("SELECT 1 FROM users")})
                    if u.path == "/api/me":
                        return self._json(200, {"user": outer.store.public(self._me())})
                    if u.path == "/api/projects":
                        return self._json(200, {"projects": outer.store.projects(self._me())})
                    if u.path == "/api/package":
                        self._me()
                        data = outer.store.export_package(int(g("project") or 0), self._base())
                        return self._send(200, data, "application/octet-stream")
                    if u.path == "/api/photo":
                        self._me()
                        mime, data = outer.store.photo(g("project"), g("uid"))
                        return self._send(200, data, mime, {"Cache-Control": "max-age=86400"})
                    if u.path == "/api/sheet_image":
                        self._me()
                        mime, data = outer.store.sheet_image(g("project"), g("suid"))
                        return self._send(200, data, mime)
                    if u.path == "/api/users":
                        return self._json(200, {"users": outer.store.users(self._me())})
                    if u.path == "/api/team_code":
                        return self._json(200, {"team_code": outer.store.team_code(self._me())})
                    if u.path.startswith("/api/"):
                        return self._json(404, {"error": "not found"})
                    return self._static(u.path)
                except CollabError as e:
                    return self._json(e.code, {"error": str(e)})
                except Exception as e:  # noqa: BLE001
                    outer.log(f"협업 서버 오류: {e}")
                    return self._json(500, {"error": str(e)})

            def do_POST(self):
                u = urlparse(self.path)
                try:
                    raw = self._body()
                    if u.path == "/api/projects":            # .strsv 올리기 → 새 협업 프로젝트
                        me = self._me()
                        name = unquote(parse_qs(u.query).get("name", [""])[0]) or None
                        r = outer.store.import_package(me, raw, name)
                        outer.log(f"협업: {me['name']} 님이 프로젝트 '{r['name']}' 올림")
                        return self._json(200, r)
                    body = json.loads(raw.decode("utf-8") or "{}") if raw else {}
                    if u.path == "/api/signup":
                        r = outer.store.signup(body.get("login"), body.get("password"), body.get("name"), body.get("team_code"))
                        outer.log(f"협업: 새 계정 {r['user']['name']} ({r['user']['login']}, {r['user']['role']})")
                        return self._json(200, r)
                    if u.path == "/api/login":
                        return self._json(200, outer.store.login(body.get("login"), body.get("password")))
                    if u.path == "/api/logout":
                        h = self.headers.get("Authorization") or ""
                        outer.store.logout(h[7:] if h.startswith("Bearer ") else "")
                        return self._json(200, {"ok": True})
                    me = self._me()
                    if u.path == "/api/sync":
                        return self._json(200, outer.store.sync(me, body))
                    if u.path == "/api/users":
                        return self._json(200, {"user": outer.store.admin_user(me, body)})
                    if u.path == "/api/team_code":
                        return self._json(200, {"team_code": outer.store.team_code(me, body.get("team_code"))})
                    if u.path == "/api/password":
                        outer.store.change_password(me, body.get("old"), body.get("new"))
                        return self._json(200, {"ok": True})
                    if u.path == "/api/renumber":
                        r = outer.store.renumber(me, int(body.get("project") or 0))
                        outer.log(f"협업: {me['name']} 님이 번호 정리 ({r['changed']}건)")
                        return self._json(200, r)
                    if u.path == "/api/project_delete":
                        outer.store.delete_project(me, int(body.get("project") or 0))
                        return self._json(200, {"ok": True})
                    return self._json(404, {"error": "not found"})
                except CollabError as e:
                    return self._json(e.code, {"error": str(e)})
                except Exception as e:  # noqa: BLE001
                    outer.log(f"협업 서버 오류: {e}")
                    return self._json(500, {"error": str(e)})

            def _static(self, path):
                """휴대폰 앱(웹)도 같은 주소에서 — 브라우저로 열어도 됨"""
                rel = unquote(path).lstrip("/") or "index.html"
                full = os.path.normpath(os.path.join(mobile, rel))
                if not full.startswith(os.path.normpath(mobile)) or not os.path.isfile(full):
                    return self._send(404, b"not found", "text/plain")
                with open(full, "rb") as f:
                    data = f.read()
                ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
                if full.endswith(".wasm"):
                    ctype = "application/wasm"
                if full.endswith(".webmanifest"):
                    ctype = "application/manifest+json"
                return self._send(200, data, ctype)

        self.httpd = ThreadingHTTPServer((self.host, self.port), H)
        self.httpd.daemon_threads = True
        if background:
            self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.thread.start()
        else:
            self.httpd.serve_forever()
        return self

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    @property
    def team_code(self):
        return self.store.kv("team_code")

    def urls(self):
        from socket import socket, AF_INET, SOCK_DGRAM
        s = socket(AF_INET, SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        except OSError:
            ip = "127.0.0.1"
        finally:
            s.close()
        return [f"http://{ip}:{self.port}/", f"http://localhost:{self.port}/"]
