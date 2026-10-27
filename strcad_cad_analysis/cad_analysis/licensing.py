"""StrCAD 라이선스 — 사용기간 · 체험판 · PC 고정 (오프라인, 서명 방식).

라이선스 키 = base64url(내용 JSON) + "." + base64url(Ed25519 서명)
  내용: {"v":1, "id":일련번호, "n":고객명, "m":기기코드|"*", "e":"YYYY-MM-DD"|null(영구), "ed":에디션,
         "mods":["*"] 또는 모듈 목록, "i":발급일}
  · 서명용 개인키는 발급 프로그램(tools/license_admin.py)에만 있고, 프로그램에는 공개키만 들어 있음
    → 키를 고치거나 새로 만들 수 없음.
  · 기기코드가 "*"가 아니면 그 PC에서만 동작.

체험판: 처음 실행한 날부터 TRIAL_DAYS일 (사용자 폴더 + Windows 레지스트리 두 곳에 기록, 이른 날짜 사용).
시계를 되돌리면(마지막 사용 시각보다 하루 넘게 과거) 사용을 막음.
외부 패키지 없음 (Ed25519 검증은 순수 파이썬, RFC 8032).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import platform
import sys
import uuid
from datetime import date, datetime, timedelta

PRODUCT = "StrCAD"
TRIAL_DAYS = 14
WARN_DAYS = 14                      # 만료 며칠 전부터 안내
SUPPORT = "구매·연장 문의: StrCAD (라이선스 담당)"
# 발급 프로그램에서 만든 공개키 (tools/license_admin.py → '키 쌍 만들기'). 개인키는 절대 배포하지 말 것.
PUBLIC_KEY_B64 = "lTuNINAM8Yq54VT_zS8aPvWVkcd4GW_17H8p9bq-T0E"

MODULES = {                          # 런처 모듈 id → 표시 이름
    "cad_analysis": "CAD Analysis",
    "2d_design": "2D Design",
    "3d_design": "3D Design",
    "auto_table": "Auto Table",
    "basic_design": "Basic Design",
    "detail_design": "Detail Design",
}
EDITIONS = {"trial": "체험판", "standard": "Standard", "pro": "Professional", "site": "사이트(다중 PC)"}

DIR = os.path.join(os.path.expanduser("~"), ".strcad")
LIC_PATH = os.path.join(DIR, "license.key")
STATE_PATH = os.path.join(DIR, ".state")
_REG_KEY = r"Software\StrCAD"
_SALT = b"strcad-lic-v1\x00\x7f"


# =============================================================================
#  Ed25519 (RFC 8032 reference, pure python — verify ~10 ms)
# =============================================================================
_p = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_d = -121665 * pow(121666, _p - 2, _p) % _p
_I = pow(2, (_p - 1) // 4, _p)


def _inv(x):
    return pow(x, _p - 2, _p)


def _xrecover(y):
    xx = (y * y - 1) * _inv(_d * y * y + 1)
    x = pow(xx, (_p + 3) // 8, _p)
    if (x * x - xx) % _p != 0:
        x = (x * _I) % _p
    if x % 2 != 0:
        x = _p - x
    return x


_By = 4 * _inv(5) % _p
_Bx = _xrecover(_By)
_B = (_Bx, _By, 1, _Bx * _By % _p)        # extended coordinates


def _add(P, Q):
    x1, y1, z1, t1 = P
    x2, y2, z2, t2 = Q
    a = (y1 - x1) * (y2 - x2) % _p
    b = (y1 + x1) * (y2 + x2) % _p
    c = t1 * 2 * _d * t2 % _p
    dd = z1 * 2 * z2 % _p
    e, f, g, h = b - a, dd - c, dd + c, b + a
    return (e * f % _p, g * h % _p, f * g % _p, e * h % _p)


def _mul(s, P):
    Q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            Q = _add(Q, P)
        P = _add(P, P)
        s >>= 1
    return Q


def _enc(P):
    x, y, z, _t = P
    zi = _inv(z)
    x, y = x * zi % _p, y * zi % _p
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _dec(s):
    if len(s) != 32:
        raise ValueError("bad point")
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= _p:
        raise ValueError("bad point")
    x = _xrecover(y)
    if (x * x * -1 + y * y - 1 - _d * x * x * y * y) % _p != 0:
        raise ValueError("bad point")
    if (x & 1) != sign:
        x = _p - x
    return (x, y, 1, x * y % _p)


def _eq(P, Q):
    x1, y1, z1, _ = P
    x2, y2, z2, _ = Q
    return (x1 * z2 - x2 * z1) % _p == 0 and (y1 * z2 - y2 * z1) % _p == 0


def _H(m):
    return int.from_bytes(hashlib.sha512(m).digest(), "little")


def ed25519_public(seed: bytes) -> bytes:
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return _enc(_mul(a, _B))


def ed25519_sign(seed: bytes, msg: bytes) -> bytes:
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    A = _enc(_mul(a, _B))
    r = _H(h[32:] + msg) % _L
    R = _enc(_mul(r, _B))
    S = (r + _H(R + A + msg) * a) % _L
    return R + int.to_bytes(S, 32, "little")


def ed25519_verify(pub: bytes, msg: bytes, sig: bytes) -> bool:
    try:
        if len(sig) != 64:
            return False
        A = _dec(pub)
        R = _dec(sig[:32])
        S = int.from_bytes(sig[32:], "little")
        if S >= _L:
            return False
        h = _H(sig[:32] + pub + msg) % _L
        return _eq(_mul(S, _B), _add(R, _mul(h, A)))
    except (ValueError, TypeError):
        return False


# =============================================================================
#  helpers
# =============================================================================
def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    s = s.strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _today() -> date:
    return date.today()


def _raw_machine() -> str:
    """이 PC 고유값 (Windows MachineGuid → /etc/machine-id → MAC)."""
    if sys.platform.startswith("win"):
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                               winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0))
            v, _ = winreg.QueryValueEx(k, "MachineGuid")
            return "win:" + str(v)
        except OSError:
            pass
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(p, encoding="ascii") as f:
                v = f.read().strip()
            if v:
                return "lx:" + v
        except OSError:
            pass
    if sys.platform == "darwin":
        try:
            import subprocess
            out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True,
                                 text=True, timeout=5).stdout
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    return "mac:" + line.split('"')[-2]
        except Exception:  # noqa: BLE001
            pass
    return "node:%012x:%s" % (uuid.getnode(), platform.node())


def machine_code() -> str:
    """사용자에게 보여 주는 기기 코드 XXXX-XXXX-XXXX-XXXX."""
    h = hashlib.sha256(("strcad|" + _raw_machine()).encode()).hexdigest()[:16].upper()
    return "-".join(h[i:i + 4] for i in range(0, 16, 4))


def _norm_code(c: str) -> str:
    return "".join(ch for ch in (c or "").upper() if ch.isalnum())


# =============================================================================
#  license key
# =============================================================================
class LicenseError(ValueError):
    pass


def make_key(seed: bytes, payload: dict) -> str:
    """발급 프로그램 전용 — 개인키(seed 32바이트)로 서명한 라이선스 키."""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _b64e(body) + "." + _b64e(ed25519_sign(seed, body))


def clean_key(text: str) -> str:
    """붙여넣은 글/파일에서 키 부분만 (줄바꿈·공백·머리말 제거)."""
    lines = [ln for ln in (text or "").splitlines() if not ln.strip().startswith("#")]
    t = "".join("".join(lines).split())
    for pre in ("STRCAD-LICENSE:", "STRCAD:", "LICENSE:"):
        if t.upper().startswith(pre):
            t = t[len(pre):]
    return t


def parse_key(key: str, pub_b64: str | None = None) -> dict:
    """서명 확인 후 내용 dict. 잘못된 키면 LicenseError."""
    key = clean_key(key)
    if key.count(".") != 1:
        raise LicenseError("라이선스 키 형식이 아닙니다.")
    a, b = key.split(".")
    try:
        body, sig = _b64d(a), _b64d(b)
        pub = _b64d(pub_b64 or PUBLIC_KEY_B64)
    except (ValueError, TypeError):
        raise LicenseError("라이선스 키를 읽을 수 없습니다.") from None
    if len(pub) != 32 or not ed25519_verify(pub, body, sig):
        raise LicenseError("올바른 StrCAD 라이선스 키가 아닙니다. (서명 불일치)")
    try:
        d = json.loads(body.decode("utf-8"))
    except ValueError:
        raise LicenseError("라이선스 내용이 손상되었습니다.") from None
    if d.get("p", PRODUCT) != PRODUCT:
        raise LicenseError("다른 제품의 라이선스입니다.")
    return d


def check_payload(d: dict, code: str | None = None, today: date | None = None) -> tuple[bool, str]:
    """이 PC · 오늘 기준으로 쓸 수 있는지."""
    code = code or machine_code()
    today = today or _today()
    m = d.get("m", "*")
    if m != "*" and _norm_code(m) != _norm_code(code):
        return False, f"다른 PC용 라이선스입니다.\n(라이선스 기기코드 {m} / 이 PC {code})"
    if d.get("s"):
        try:
            if today < date.fromisoformat(d["s"]):
                return False, f"{d['s']}부터 사용할 수 있는 라이선스입니다."
        except ValueError:
            pass
    if d.get("e"):
        try:
            if today > date.fromisoformat(d["e"]):
                return False, f"사용 기간이 끝났습니다 ({d['e']})."
        except ValueError:
            return False, "만료일 형식 오류"
    return True, ""


# =============================================================================
#  local state (trial start, last seen) — tamper-evident
# =============================================================================
def _sig(d: dict) -> str:
    k = hashlib.sha256(_SALT + _raw_machine().encode()).digest()
    msg = json.dumps({k2: d[k2] for k2 in sorted(d) if k2 != "h"}, separators=(",", ":")).encode()
    return hmac.new(k, msg, hashlib.sha256).hexdigest()[:32]


def _read_file_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("h") == _sig(d):
            return d
        return {"tampered": 1}
    except (OSError, ValueError):
        return None


def _write_file_state(d):
    try:
        os.makedirs(DIR, exist_ok=True)
        d = {k: v for k, v in d.items() if k != "h"}
        d["h"] = _sig(d)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f)
        if sys.platform.startswith("win"):
            try:
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(STATE_PATH, 0x02)   # hidden
            except Exception:  # noqa: BLE001
                pass
    except OSError:
        pass


def _reg_get():
    if not sys.platform.startswith("win"):
        return None
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY)
        v, _ = winreg.QueryValueEx(k, "ts")
        return json.loads(v)
    except (OSError, ValueError):
        return None


def _reg_set(d):
    if not sys.platform.startswith("win"):
        return
    try:
        import winreg
        k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, _REG_KEY)
        winreg.SetValueEx(k, "ts", 0, winreg.REG_SZ, json.dumps(d))
    except OSError:
        pass


def _state(now: datetime | None = None):
    """{'trial_start': 'YYYY-MM-DD', 'last': iso, 'clock_back': bool, 'tampered': bool}"""
    now = now or datetime.now()
    fs = _read_file_state() or {}
    rg = _reg_get() or {}
    tampered = bool(fs.get("tampered"))
    starts = [s for s in (fs.get("t0"), rg.get("t0")) if s]
    lasts = [s for s in (fs.get("ls"), rg.get("ls")) if s]
    t0 = min(starts) if starts else now.date().isoformat()
    last = max(lasts) if lasts else now.isoformat(timespec="seconds")
    clock_back = False
    try:
        clock_back = now < datetime.fromisoformat(last) - timedelta(days=1)
    except ValueError:
        pass
    if tampered and not rg.get("t0"):
        t0 = "2000-01-01"                 # 기록 파일을 고친 흔적 → 체험판 끝난 것으로
    if not clock_back:
        new_last = max(last, now.isoformat(timespec="seconds"))
        d = {"t0": t0, "ls": new_last}
        _write_file_state(d)
        _reg_set(d)
    return {"trial_start": t0, "last": last, "clock_back": clock_back, "tampered": tampered}


# =============================================================================
#  public API
# =============================================================================
def load_key() -> str:
    try:
        with open(LIC_PATH, encoding="utf-8") as f:
            return clean_key(f.read())
    except OSError:
        return ""


def save_key(key: str):
    os.makedirs(DIR, exist_ok=True)
    with open(LIC_PATH, "w", encoding="utf-8") as f:
        f.write(clean_key(key) + "\n")


def remove_key():
    try:
        os.remove(LIC_PATH)
    except OSError:
        pass


def activate(key: str) -> dict:
    """키 확인 후 저장. 성공하면 status() 반환, 실패하면 LicenseError."""
    d = parse_key(key)
    ok, why = check_payload(d)
    if not ok:
        raise LicenseError(why)
    save_key(key)
    d0 = _read_file_state() or {}
    rg = _reg_get() or {}
    st = {"t0": min([x for x in (d0.get("t0"), rg.get("t0")) if x] or [date.today().isoformat()]),
          "ls": datetime.now().isoformat(timespec="seconds")}      # 새 키 등록 = 시계 기준 재설정
    _write_file_state(st)
    _reg_set(st)
    return status()


def status(now: datetime | None = None) -> dict:
    """현재 사용 가능 여부.
    state: licensed | trial | expired | trial_expired | invalid | clock
    ok: 사용 가능, days_left: 남은 일수(None=영구), modules: 허용 모듈 집합('*' 포함 가능)"""
    now = now or datetime.now()
    today = now.date()
    st = _state(now)
    code = machine_code()
    base = {"code": code, "ok": False, "days_left": 0, "customer": "", "expiry": None, "edition": "",
            "modules": set(), "message": "", "serial": "", "trial_days": TRIAL_DAYS}
    if st["clock_back"]:
        base.update(state="clock", message="PC 날짜가 마지막 사용일보다 이전으로 되어 있습니다.\n"
                                           "Windows 날짜·시간을 올바르게 맞춘 뒤 다시 실행하세요.")
        return base
    key = load_key()
    if key:
        try:
            d = parse_key(key)
            ok, why = check_payload(d, code, today)
            exp = d.get("e")
            left = (date.fromisoformat(exp) - today).days if exp else None
            base.update(customer=d.get("n", ""), expiry=exp, edition=EDITIONS.get(d.get("ed"), d.get("ed", "")),
                        modules=set(d.get("mods") or ["*"]), serial=str(d.get("id", "")), payload=d)
            if ok:
                base.update(state="licensed", ok=True, days_left=left,
                            message=f"{base['customer']} · " + (f"{exp}까지 ({left}일 남음)" if exp else "영구 라이선스"))
                return base
            base.update(state="expired" if "기간" in why else "invalid", message=why)
            return base
        except LicenseError as e:
            base.update(state="invalid", message=str(e))
            return base
    # trial
    try:
        t0 = date.fromisoformat(st["trial_start"])
    except ValueError:
        t0 = date(2000, 1, 1)
    end = t0 + timedelta(days=TRIAL_DAYS)
    left = (end - today).days
    base.update(edition=EDITIONS["trial"], expiry=end.isoformat(), modules={"*"})
    if left > 0:
        base.update(state="trial", ok=True, days_left=left,
                    message=f"체험판 · {left}일 남음 ({end.isoformat()}까지)")
    else:
        base.update(state="trial_expired", message=f"체험 기간({TRIAL_DAYS}일)이 끝났습니다. 라이선스 키를 등록하세요.")
    return base


def allows(st: dict, module: str) -> bool:
    return bool(st.get("ok")) and ("*" in st.get("modules", ()) or module in st.get("modules", ()))


def should_warn(st: dict) -> bool:
    """시작할 때 남은 기간 안내를 띄울지 (정품 14일 이하, 체험판 3일 이하)."""
    dl = st.get("days_left")
    if not st.get("ok") or dl is None:
        return False
    return dl <= (WARN_DAYS if st.get("state") == "licensed" else 3)


def short_text(st: dict) -> str:
    """헤더용 한 줄."""
    s = st.get("state")
    if s == "licensed":
        dl = st.get("days_left")
        return f"🔑 {st['customer']} · " + ("영구" if dl is None else f"{st['expiry']}까지 ({dl}일)")
    if s == "trial":
        return f"⏳ 체험판 {st['days_left']}일 남음"
    return "⛔ 라이선스 필요"
