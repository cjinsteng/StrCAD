"""
information/boringlog.py — 시추공 한 공의 시추주상도 (조사보고서 양식과 비슷한 그림)

    머리말 : 조사명 · 위치 · 시추번호 · 좌표(GRS80 TM 중부원점) · 표고 · 굴진심도 · 지하수위
    본문   : 심도 · 표고 · 층후 · 주상도(무늬) · 지반명 · 현장관찰기록 · 시험심도 · 타격수(BLOWS/cm)
             · 표준관입시험 N 그래프(0~50) · Vs
"""
import math

from . import geo
from .composite import CLS_COLOR, CLS_KO, _font


def _wrap(d, txt, font, width):
    out = []
    for para in txt.split("\n"):
        line = ""
        for ch in para:
            if d.textlength(line + ch, font=font) > width:
                out.append(line)
                line = "  " + ch if out and para.startswith("-") else ch
            else:
                line += ch
        out.append(line)
    return out


def _obs(descr):
    """설명 문장 → '- 항목' 줄들."""
    t = (descr or "").replace("\r", " ").replace("\n", " ").strip()
    if not t:
        return ""
    parts = [p.strip(" -·") for p in (t.split(",") if "," in t else t.split(" - "))]
    return "\n".join("- " + p for p in parts if p)


def _pattern(d, box, cls):
    x0, y0, x1, y1 = box
    if cls in ("sand", "soil_weathered", "sediment"):
        for yy in range(int(y0) + 4, int(y1) - 1, 6):
            for xx in range(int(x0) + 4 + (yy // 6 % 2) * 3, int(x1) - 2, 7):
                d.ellipse((xx - 1, yy - 1, xx + 1, yy + 1), fill=(40, 40, 40))
    elif cls == "gravel":
        for yy in range(int(y0) + 6, int(y1) - 3, 11):
            for xx in range(int(x0) + 6 + (yy // 11 % 2) * 5, int(x1) - 5, 11):
                d.ellipse((xx - 3, yy - 2, xx + 3, yy + 2), outline=(40, 40, 40))
    elif cls == "clay":
        for yy in range(int(y0) + 4, int(y1), 5):
            d.line((x0 + 2, yy, x1 - 2, yy), fill=(60, 60, 60))
    elif cls == "fill":
        for yy in range(int(y0) + 5, int(y1) - 2, 9):
            for xx in range(int(x0) + 4, int(x1) - 6, 10):
                d.line((xx, yy, xx + 5, yy + 3), fill=(60, 60, 60))
    elif cls in ("rock_weathered", "rock_soft", "rock_hard"):
        gap = {"rock_weathered": 12, "rock_soft": 8, "rock_hard": 5}[cls]
        h = y1 - y0
        for c0 in range(-int(h), int(x1 - x0), gap):
            ax, ay, bx, by = x0 + c0, y0, x0 + c0 + h, y1
            if ax < x0:
                ay += x0 - ax
                ax = x0
            if bx > x1:
                by -= bx - x1
                bx = x1
            if bx > ax:
                d.line((ax, ay, bx, by), fill=(50, 50, 50))


def render(hole, layers, spts, vs=None, cls_of=None, px_m=34, width=1240):
    """hole: holes 행 dict, layers: [{top,bot,name,uscs,descr}], spts: [{depth,blows,pen,n}]"""
    from PIL import Image, ImageDraw
    from . import boreholes as BH
    cls_of = cls_of or (lambda q: BH.classify_layer(q["name"], q.get("uscs", ""), q.get("descr", "")))
    vs = vs or []
    depth = max([hole.get("depth") or 0] + [q["bot"] for q in layers] + [s["depth"] for s in spts] + [3.0])
    hdr_h, col_h, top_pad = 190, 46, 8
    H = int(hdr_h + col_h + depth * px_m + 40)
    im = Image.new("RGB", (width, H), "white")
    d = ImageDraw.Draw(im)
    ft, fb, f, fs = _font(26, True), _font(13, True), _font(12), _font(11)
    K_ = (0, 0, 0)
    G_ = (232, 236, 242)
    # 제목
    d.text((width / 2 - d.textlength("시 추 주 상 도", font=ft) / 2, 8), "시 추 주 상 도", fill=K_, font=ft)
    d.text((width - 300, 18), "GRS80 TM 중부원점(60만, 20만)", fill=(60, 60, 60), font=fs)
    # 머리말 표
    la, lo = hole.get("lat"), hole.get("lon")
    xy = ("", "")
    if la is not None and lo is not None:
        try:
            X, Y = geo.tm_forward(la, lo, geo.CRS["EPSG:5186"])
            xy = (f"X(E): {X:,.3f}", f"Y(N): {Y:,.3f}")
        except Exception:                            # noqa: BLE001
            xy = (f"위도 {la:.6f}", f"경도 {lo:.6f}")
    gw = hole.get("gwl")
    gtxt = "—" if gw in (None, 0) else f"{abs(gw):.2f}"
    rows = [
        (("조사명", hole.get("project") or "—", 3), ("자료", hole.get("source") or "—", 1), ("시추번호", hole["code"], 1)),
        (("위치", hole.get("name") or "—", 3), ("좌표 (m)", xy[0] + "\n" + xy[1], 1),
         ("표고 (m)", "—" if hole.get("elev") in (None, 0) else f"{hole['elev']:.2f}", 1)),
        (("굴진심도\n(GL,-m)", f"{depth:.1f}", 1), ("위경도", "" if la is None else f"{la:.6f}, {lo:.6f}", 2),
         ("지하수위\n(GL,-m)", gtxt, 1), ("표준관입", f"{len(spts)}회", 1)),
    ]
    y = 50
    x_label_w = 92
    rh = 44
    for row in rows:
        x = 10
        tot = sum(c[2] for c in row)
        avail = width - 20 - x_label_w * len(row)
        for lab, val, span in row:
            w = avail * span / tot
            d.rectangle((x, y, x + x_label_w, y + rh), fill=G_, outline=K_)
            for i, ln in enumerate(lab.split("\n")):
                d.text((x + x_label_w / 2 - d.textlength(ln, font=fb) / 2, y + rh / 2 - 8 * len(lab.split("\n")) + 16 * i),
                       ln, fill=K_, font=fb)
            d.rectangle((x + x_label_w, y, x + x_label_w + w, y + rh), outline=K_)
            lines = _wrap(d, str(val), f, w - 10)[:3]
            for i, ln in enumerate(lines):
                d.text((x + x_label_w + 6, y + rh / 2 - 8 * len(lines) + 16 * i), ln, fill=K_, font=f)
            x += x_label_w + w
        y += rh
    # 본문 열
    cols = [("심도\n(-m)", 52), ("표고\n(m)", 56), ("층후\n(m)", 48), ("주상도", 70), ("지반명", 92),
            ("현장관찰기록", 410), ("시험\n심도", 52), ("BLOWS\n/cm", 70), ("표준관입시험 N", 250), ("Vs\n(m/s)", 60)]
    X0 = 10
    xs = [X0]
    for _, w in cols:
        xs.append(xs[-1] + w)
    yb = hdr_h
    for (lab, _), a, b in zip(cols, xs, xs[1:]):
        d.rectangle((a, yb, b, yb + col_h), fill=G_, outline=K_)
        ls = lab.split("\n")
        for i, ln in enumerate(ls):
            d.text(((a + b) / 2 - d.textlength(ln, font=fb) / 2, yb + col_h / 2 - 8 * len(ls) + 16 * i), ln,
                   fill=K_, font=fb)
    yt = yb + col_h
    Yz = lambda z: yt + top_pad + z * px_m      # noqa: E731
    ybot = Yz(depth) + 6
    for a in xs:
        d.line((a, yt, a, ybot), fill=K_)
    d.line((X0, ybot, xs[-1], ybot), fill=K_)
    # N 그래프 눈금
    na, nb = xs[8] + 8, xs[9] - 10
    for v in range(0, 51, 10):
        x = na + (nb - na) * v / 50
        d.line((x, yt, x, ybot), fill=(225, 225, 225))
        d.text((x - 6, yt + 1), str(v), fill=(90, 90, 90), font=fs)
    elev = hole.get("elev") if hole.get("elev") not in (None, 0) else None
    # 지층
    for q in sorted(layers, key=lambda t: t["top"]):
        c = cls_of(q)
        y0, y1 = Yz(q["top"]), Yz(q["bot"])
        d.line((X0, y1, xs[6], y1), fill=K_)
        d.text((xs[0] + 4, y1 - 15), f"{q['bot']:.1f}", fill=K_, font=f)
        if elev is not None:
            d.text((xs[1] + 4, y1 - 15), f"{elev - q['bot']:.2f}", fill=K_, font=f)
        d.text((xs[2] + 4, y1 - 15), f"{q['bot'] - q['top']:.1f}", fill=K_, font=f)
        d.rectangle((xs[3] + 1, y0, xs[4] - 1, y1), fill=tuple(min(255, v + 40) for v in CLS_COLOR[c]))
        _pattern(d, (xs[3] + 1, y0, xs[4] - 1, y1), c)
        nm = q["name"] or CLS_KO[c]
        nl = _wrap(d, nm + (f"\n({q['uscs']})" if q.get("uscs") else ""), fb, cols[4][1] - 8)
        for i, ln in enumerate(nl[: max(1, int((y1 - y0 - 4) // 16))]):
            d.text((xs[4] + 4, y0 + 4 + 16 * i), ln, fill=(120, 60, 20), font=fb)
        ob = _wrap(d, _obs(q.get("descr", "")), f, cols[5][1] - 12)
        for i, ln in enumerate(ob[: max(1, int((y1 - y0 - 4) // 15))]):
            d.text((xs[5] + 6, y0 + 4 + 15 * i), ln, fill=K_, font=f)
    # 지하수위
    if gw not in (None, 0):
        yw = Yz(abs(gw))
        d.polygon([(xs[3] + 8, yw - 9), (xs[3] + 20, yw - 9), (xs[3] + 14, yw)], fill=(20, 90, 230))
        d.line((xs[3] + 2, yw, xs[4] - 2, yw), fill=(20, 90, 230), width=2)
    # 표준관입
    pts = []
    for s in sorted(spts, key=lambda t: t["depth"]):
        yy = Yz(s["depth"])
        d.text((xs[6] + 6, yy - 7), f"{s['depth']:.1f}", fill=K_, font=f)
        b, p = s.get("blows"), s.get("pen")
        txt = (f"{b:.0f}/{p:.0f}" if b is not None and p else f"N={s['n']:.0f}" if s.get("n") is not None else "")
        d.text((xs[7] + 6, yy - 7), txt, fill=K_, font=f)
        d.line((xs[7] + 2, yy + 8, xs[8] - 2, yy + 8), fill=(200, 200, 200))
        if s.get("n") is not None:
            x = na + (nb - na) * min(s["n"], 50) / 50
            pts.append((x, yy))
    if len(pts) > 1:
        d.line(pts, fill=(70, 110, 160), width=2)
    for x, yy in pts:
        d.rectangle((x - 5, yy - 5, x + 5, yy + 5), fill=(130, 175, 225), outline=(40, 70, 120))
    # Vs
    for v in vs:
        y0, y1 = Yz(v["top"]), Yz(v["bot"])
        d.line((xs[9] + 4, (y0 + y1) / 2, xs[10] - 4, (y0 + y1) / 2), fill=(20, 150, 80))
        d.text((xs[9] + 6, (y0 + y1) / 2 - 15), f"{v['vs']:.0f}", fill=(20, 120, 60), font=fs)
    # 심도 눈금 (1m)
    for z in range(0, int(math.ceil(depth)) + 1):
        d.line((xs[0], Yz(z), xs[0] + (8 if z % 5 == 0 else 4), Yz(z)), fill=K_)
    d.text((X0, H - 22), "※ 국토지반정보·조사보고서 자료로 다시 그린 주상도입니다 (원 주상도와 세부 표기가 다를 수 있음).",
           fill=(110, 110, 110), font=fs)
    return im
