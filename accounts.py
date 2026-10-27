"""StrCAD 런처 계정 — 회원가입 · 로그인 (이 PC의 사용자 폴더에 저장).

저장: %USERPROFILE%\\.strcad\\users.json
  {"users": {"아이디": {"name", "company", "email", "phone", "salt", "hash", "created", "last_login"}}}
비밀번호는 저장하지 않고 PBKDF2-SHA256(20만 회) 해시만 저장.
기본 계정(_BUILTIN)은 코드에 해시로 들어 있음.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime

PATH = os.path.join(os.path.expanduser("~"), ".strcad", "users.json")
ITER = 200_000

# 기본 계정 (sha256, 이전 버전 호환)
_BUILTIN = {
    "1234": hashlib.sha256(b"1234").hexdigest(),
    "user1": hashlib.sha256(b"pass1234").hexdigest(),
}

ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{4,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountError(ValueError):
    pass


def _hash(pw: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, ITER).hex()


def _load() -> dict:
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("users"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"users": {}}


def _save(d: dict):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PATH)


def exists(uid: str) -> bool:
    uid = (uid or "").strip()
    return uid in _BUILTIN or uid.lower() in {k.lower() for k in _load()["users"]}


def check_password_rule(pw: str) -> str:
    """규칙에 맞으면 '' , 아니면 안내 문구."""
    if len(pw) < 8:
        return "비밀번호는 8자 이상이어야 합니다."
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"[0-9]", pw):
        return "비밀번호에 영문과 숫자를 함께 넣어 주세요."
    return ""


def register(uid: str, pw: str, name: str, company: str = "", email: str = "", phone: str = "") -> dict:
    uid = (uid or "").strip()
    name = (name or "").strip()
    email = (email or "").strip()
    if not ID_RE.match(uid):
        raise AccountError("아이디는 영문·숫자·_ . - 로 4~20자입니다.")
    if exists(uid):
        raise AccountError("이미 사용 중인 아이디입니다.")
    rule = check_password_rule(pw)
    if rule:
        raise AccountError(rule)
    if not name:
        raise AccountError("이름을 입력하세요.")
    if email and not EMAIL_RE.match(email):
        raise AccountError("이메일 형식이 올바르지 않습니다.")
    d = _load()
    salt = secrets.token_bytes(16)
    u = {"name": name, "company": (company or "").strip(), "email": email, "phone": (phone or "").strip(),
         "salt": salt.hex(), "hash": _hash(pw, salt), "created": datetime.now().isoformat(timespec="seconds"),
         "last_login": ""}
    d["users"][uid] = u
    _save(d)
    return public(uid, u)


def public(uid: str, u: dict | None) -> dict:
    u = u or {}
    return {"id": uid, "name": u.get("name") or uid, "company": u.get("company", ""), "email": u.get("email", ""),
            "phone": u.get("phone", ""), "created": u.get("created", ""), "builtin": uid in _BUILTIN}


def authenticate(uid: str, pw: str) -> dict | None:
    """성공하면 사용자 정보 dict, 실패하면 None."""
    uid = (uid or "").strip()
    if uid in _BUILTIN:
        ok = hmac.compare_digest(_BUILTIN[uid], hashlib.sha256(pw.encode("utf-8")).hexdigest())
        return public(uid, None) if ok else None
    d = _load()
    key = next((k for k in d["users"] if k.lower() == uid.lower()), None)
    if key is None:
        return None
    u = d["users"][key]
    try:
        ok = hmac.compare_digest(u["hash"], _hash(pw, bytes.fromhex(u["salt"])))
    except (KeyError, ValueError):
        return None
    if not ok:
        return None
    u["last_login"] = datetime.now().isoformat(timespec="seconds")
    try:
        _save(d)
    except OSError:
        pass
    return public(key, u)


def change_password(uid: str, old: str, new: str):
    if uid in _BUILTIN:
        raise AccountError("기본 계정은 비밀번호를 바꿀 수 없습니다.")
    if authenticate(uid, old) is None:
        raise AccountError("현재 비밀번호가 맞지 않습니다.")
    rule = check_password_rule(new)
    if rule:
        raise AccountError(rule)
    d = _load()
    key = next(k for k in d["users"] if k.lower() == uid.lower())
    salt = secrets.token_bytes(16)
    d["users"][key].update(salt=salt.hex(), hash=_hash(new, salt))
    _save(d)
