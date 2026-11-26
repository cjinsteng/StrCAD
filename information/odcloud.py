"""
information/odcloud.py — 공공데이터포털 '파일데이터 OpenAPI'(api.odcloud.kr) 내려받기

    국토교통부_지반정보_* 자료는 파일(CSV)과 같은 내용을 REST 로도 준다.
    CSV 를 엑셀로 열고 저장하면서 잘린 경우(예: 표준관입시험 20만 행)에도 API 는 전체가 나온다.

    GET https://api.odcloud.kr/api/{경로}?page=1&perPage=N&serviceKey=KEY
      → {"page", "perPage", "totalCount", "currentCount", "matchCount", "data": [{열이름: 값, …}, …]}

    받은 행은 CSV(utf-8)로 이어 쓰고, 끝나면 BoreholeDB.import_csv 로 가져온다
    (열 이름이 CSV 와 같으므로 기존 열 판별을 그대로 씀).  중간에 끊기면 이어받기.
"""
import csv
import json
import time
import urllib.parse
import urllib.request

from pathlib import Path


BASE = "https://api.odcloud.kr/api"
DATASETS = {
    "표준관입시험정보": "/15148686/v1/uddi:a1ef4cc3-456c-4356-b93a-b932c9adf35f",
}


class ApiError(Exception):
    pass


def _get(path, key, page, per, timeout=60):
    q = urllib.parse.urlencode({"page": page, "perPage": per, "returnType": "JSON"})
    k = key.strip()
    # 일반 인증키(Decoding)를 그대로 쓰되, 이미 인코딩된 키(%2B 등)면 그대로 붙임
    kq = k if "%" in k else urllib.parse.quote(k, safe="")
    url = f"{BASE}{path}?{q}&serviceKey={kq}"
    req = urllib.request.Request(url, headers={"User-Agent": "StrCAD-Information/1.0",
                                               "Authorization": f"Infuser {k}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode("utf-8", "replace")
        raise ApiError(f"HTTP {e.code}: {body}") from e
    except Exception as e:                           # noqa: BLE001
        raise ApiError(f"연결 실패: {e}") from e
    try:
        js = json.loads(raw.decode("utf-8"))
    except Exception as e:                           # noqa: BLE001
        raise ApiError("응답이 JSON 이 아님: " + raw[:200].decode("utf-8", "replace")) from e
    if "data" not in js:
        raise ApiError(f"응답 오류: {str(js)[:300]}")
    return js


def probe(path, key):
    """키·경로 확인 — (전체 행 수, 열 이름들, 첫 행)."""
    js = _get(path, key, 1, 3, timeout=30)
    d = js.get("data") or []
    return int(js.get("totalCount") or js.get("matchCount") or 0), list(d[0].keys()) if d else [], (d[0] if d else {})


def download(path, key, out_csv, per=5000, progress=None, cancel=None, resume=True):
    """
    전 페이지를 받아 out_csv 에 쓴다.  진행 상황은 out_csv + '.state' 에 남겨 이어받기.
    progress(done_rows, total_rows, page, pages)
    반환: (받은 행 수, 전체 행 수)
    """
    state_p = Path(str(out_csv) + ".state")
    st = {}
    if resume and state_p.exists() and Path(out_csv).exists():
        try:
            st = json.loads(state_p.read_text(encoding="utf-8"))
        except Exception:                            # noqa: BLE001
            st = {}
    if st.get("path") != path:
        st = {}
    page = st.get("next_page", 1)
    per = st.get("per", per)
    cols = st.get("cols")
    done = st.get("done", 0)
    total = st.get("total")
    mode = "a" if page > 1 else "w"
    with open(out_csv, mode, encoding="utf-8-sig" if mode == "w" else "utf-8", newline="") as fp:
        wr = csv.writer(fp)
        while True:
            if cancel and cancel():
                break
            tries = 0
            while True:
                try:
                    js = _get(path, key, page, per)
                    break
                except ApiError as e:
                    tries += 1
                    if page == 1 and per > 1000 and tries == 1:
                        per = 1000                   # 페이지 크기 제한에 걸리면 줄여서 다시
                        continue
                    if tries >= 4:
                        raise
                    time.sleep(2 * tries)
                    if "HTTP 4" in str(e) and "429" not in str(e):
                        raise
            data = js.get("data") or []
            total = int(js.get("totalCount") or js.get("matchCount") or total or 0)
            if not data:
                break
            if cols is None:
                cols = list(data[0].keys())
                wr.writerow(cols)
            for rec in data:
                wr.writerow(["" if rec.get(c) is None else rec.get(c) for c in cols])
            done += len(data)
            pages = max(1, -(-total // per)) if total else 0
            fp.flush()
            state_p.write_text(json.dumps({"path": path, "next_page": page + 1, "per": per, "cols": cols,
                                           "done": done, "total": total}), encoding="utf-8")
            if progress:
                progress(done, total, page, pages)
            if len(data) < per or (total and done >= total):
                break
            page += 1
    finished = bool(total) and done >= total
    if finished:
        try:
            state_p.unlink()
        except OSError:
            pass
    return done, total or done, finished
