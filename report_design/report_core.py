# -*- coding: utf-8 -*-
"""
report_core.py — 보고서 작성 도우미의 핵심 로직 (UI 없음)

 - Report        : 여러 장(파일)을 묶은 보고서, 수정 대기(edits) 관리
 - 번호 검사      : 장/절 번호, (1)(2) 항목, ①② 항목, <그림/표 N.M> 캡션
 - 동일 내용 동기화: 수정한 문구가 다른 곳에도 있으면 함께 수정 제안
 - 유사 문단 불일치: 여러 곳에 반복되는 문단 중 내용이 조금 다른 것 찾기
 - 공통 항목      : 과업명·위치·연면적·준공연도·재료강도 등을 한곳에서 관리
 - AI 검토       : Claude API 로 절 단위 오타/표현/내용 검토
 - HwpApplier    : 한글(HWP) 자동화로 원본 파일에 반영 (백업 → 바꾸기 → 저장 → 검증)
"""
import datetime
import difflib
import json
import os
import re
import shutil
import urllib.error
import urllib.request

from hwp_reader import read_document, build_sections

# ====================================================================== 보고서

class Report:
    def __init__(self):
        self.docs = []                 # HwpDoc
        self.roots = {}                # doc.key -> [Section]
        self.paras = {}                # uid -> Para
        self.edits = {}                # uid -> 새 텍스트
        self.edit_src = {}             # uid -> 출처 설명
        self.common = []               # [[항목, 값], ...]
        self.new_refs = set()          # Word: 이번에 새로 넣은 요소(id) — 빈 문단도 화면에 표시
        self._index = None

    # ------------------------------------------------------------ 로드
    def add_file(self, path):
        path = os.path.abspath(path)
        for d in self.docs:
            if d.path == path:
                return d
        doc = read_document(path, key=path)
        self.docs.append(doc)
        self._register(doc)
        self.docs.sort(key=lambda d: _chapter_sort_key(self, d))
        return doc

    def _register(self, doc):
        self.roots[doc.key] = build_sections(doc)
        for p in doc.paras:
            self.paras[p.uid] = p
        self._index = None

    def reload(self, doc):
        """파일을 다시 읽는다. 원문이 그대로인 문단의 수정 대기는 유지"""
        old_edits = {p.seq: (p.orig, self.edits.pop(p.uid), self.edit_src.pop(p.uid, ""))
                     for p in doc.paras if p.uid in self.edits}
        for p in doc.paras:
            self.paras.pop(p.uid, None)
        new = read_document(doc.path, key=doc.key)
        i = self.docs.index(doc)
        self.docs[i] = new
        self._register(new)
        kept = 0
        for seq, (orig, txt, src) in old_edits.items():
            if seq >= len(new.paras):
                continue
            now = new.paras[seq].orig
            if now == txt:
                continue                      # 반영 완료
            if now == orig or ratio(now, txt) >= 0.8:   # 미반영 또는 일부만 반영
                self.edits[new.paras[seq].uid] = txt
                self.edit_src[new.paras[seq].uid] = src
                kept += 1
        return new, kept

    def remove_doc(self, doc):
        for p in doc.paras:
            self.paras.pop(p.uid, None)
            self.edits.pop(p.uid, None)
            self.edit_src.pop(p.uid, None)
        self.docs.remove(doc)
        self.roots.pop(doc.key, None)
        self._index = None

    # ------------------------------------------------------------ 텍스트/수정
    def text(self, p):
        return self.edits.get(p.uid, p.orig)

    def set_edit(self, p, new_text, src="직접 수정"):
        if new_text == p.orig:
            self.edits.pop(p.uid, None)
            self.edit_src.pop(p.uid, None)
        else:
            self.edits[p.uid] = new_text
            self.edit_src[p.uid] = src
        self._index = None

    def clear_edit(self, p):
        self.edits.pop(p.uid, None)
        self.edit_src.pop(p.uid, None)
        self._index = None

    def all_paras(self):
        for d in self.docs:
            yield from d.paras

    def all_sections(self, doc=None):
        docs = [doc] if doc else self.docs
        for d in docs:
            for r in self.roots.get(d.key, []):
                yield from r.iter()

    # ------------------------------------------------------------ 저장/복원
    def state_path(self):
        if not self.docs:
            return None
        # 한글 작업과 Word 작업은 따로 저장 (Word 는 새로 분석)
        name = "보고서도우미_작업상태_Word.json" if self.docs[0].fmt == "docx" else "보고서도우미_작업상태.json"
        return os.path.join(os.path.dirname(self.docs[0].path), name)

    def save_state(self):
        sp = self.state_path()
        if not sp:
            return
        data = {"common": self.common, "edits": {}}
        for uid, txt in self.edits.items():
            p = self.paras.get(uid)
            if p is None:
                continue
            data["edits"].setdefault(p.doc.path, {})[str(p.seq)] = {
                "orig": p.orig, "new": txt, "src": self.edit_src.get(uid, "")}
        data["files"] = [d.path for d in self.docs]
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    def load_state(self):
        """현재 폴더의 작업상태 파일을 읽어 수정 대기/공통 항목 복원. (복원 수, 원문이 바뀌어 버린 수)"""
        sp = self.state_path()
        if not sp or not os.path.exists(sp):
            return 0, 0
        with open(sp, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("common"):
            self.common = data["common"]
        ok = bad = 0
        bypath = {d.path: d for d in self.docs}
        for path, items in data.get("edits", {}).items():
            d = bypath.get(path)
            if not d:
                continue
            for seq, e in items.items():
                seq = int(seq)
                if seq < len(d.paras) and d.paras[seq].orig == e["orig"]:
                    self.set_edit(d.paras[seq], e["new"], e.get("src", "복원"))
                    ok += 1
                else:
                    bad += 1
        return ok, bad

    # ------------------------------------------------------------ 유사 문단 색인
    def index(self):
        if self._index is None:
            self._index = SimilarIndex(self)
        return self._index


def _chapter_sort_key(rep, doc):
    for s in rep.roots.get(doc.key, []):
        if s.level == 0 and s.number.isdigit():
            return (int(s.number), doc.path)
    m = re.search(r"(\d+)", os.path.basename(doc.path))
    return (int(m.group(1)) if m else 999, doc.path)


# ====================================================================== 표/절 텍스트

def table_rows(table):
    """표 → [[(r, c, cell)], ...] 행 단위"""
    rows = {}
    for (r, c), cell in table.cells.items():
        rows.setdefault(r, []).append((r, c, cell))
    return [sorted(rows[r], key=lambda x: x[1]) for r in sorted(rows)]


def table_col_widths(table):
    """열 너비(상대값). 셀 너비 정보가 없으면 글자 수로 추정"""
    n = max([table.cols] + [c + cell["cs"] for (r, c), cell in table.cells.items()])
    widths = [None] * n
    for (r, c), cell in table.cells.items():
        if cell["cs"] == 1 and cell.get("w") and c < n:
            widths[c] = max(widths[c] or 0, cell["w"])
    for (r, c), cell in table.cells.items():
        rng = range(c, min(n, c + cell["cs"]))
        unknown = [k for k in rng if widths[k] is None]
        if unknown and cell.get("w"):
            known = sum(widths[k] for k in rng if widths[k] is not None)
            for k in unknown:
                widths[k] = max(1, (cell["w"] - known) / len(unknown))
    if any(w is None for w in widths):
        lens = [4] * n
        for (r, c), cell in table.cells.items():
            if cell["cs"] == 1 and c < n:
                t = " ".join(p.orig for p in cell["paras"])
                lens[c] = max(lens[c], min(40, len(t)))
        widths = [w if w is not None else lens[k] * (sum(x for x in widths if x) / max(1, sum(lens)) or 1)
                  for k, w in enumerate(widths)]
    return widths


def add_table_row(rep, doc, table):
    """Word 표에 빈 행 추가"""
    tr = _dx().add_table_row(table.ref)
    rep.new_refs.add(id(table.ref))
    rebuild_docx(rep, doc)
    return tr


def section_blocks(sec, include_children=True):
    end = sec.end_idx if include_children else sec.own_end
    start = sec.block_idx
    if sec.title == "(표지·목차)":
        start, end = 0, sec.end_idx
    return sec.doc.blocks[start:end]


def section_for_ai(rep, sec, include_children=True, max_chars=24000):
    """AI 입력용 텍스트. 문단마다 [P번호] 표시. 길면 여러 덩어리로 나눔"""
    chunks, cur, idmap = [], [], {}
    size = 0

    def emit(line):
        nonlocal size
        if size + len(line) > max_chars and cur:
            chunks.append("\n".join(cur))
            cur.clear()
            size = 0
        cur.append(line)
        size += len(line) + 1

    for k, obj in section_blocks(sec, include_children):
        if k == "p":
            t = rep.text(obj)
            if not t.strip():
                continue
            tag = f"P{obj.seq}"
            idmap[tag] = obj
            emit(f"[{tag}] {t}")
        else:
            lines = [f"[표 {obj.tid + 1}] ({obj.rows}행 x {obj.cols}열, ^=위 셀과 병합, <=왼쪽 셀과 병합)"]
            nrows = max([obj.rows] + [r + cell["rs"] for (r, c), cell in obj.cells.items()])
            ncols = max([obj.cols] + [c + cell["cs"] for (r, c), cell in obj.cells.items()])
            grid = [[""] * ncols for _ in range(nrows)]
            for (r, c), cell in obj.cells.items():
                parts = []
                for p in cell["paras"]:
                    t = rep.text(p)
                    if t.strip():
                        idmap[f"P{p.seq}"] = p
                        parts.append(f"[P{p.seq}] {t.strip()}")
                for dr in range(cell["rs"]):
                    for dc in range(cell["cs"]):
                        if r + dr < nrows and c + dc < ncols:
                            grid[r + dr][c + dc] = "^" if dr else "<"
                grid[r][c] = " / ".join(parts)
            for row in grid:
                lines.append("| " + " | ".join(row) + " |")
            emit("\n".join(lines))
    if cur:
        chunks.append("\n".join(cur))
    return chunks, idmap


# ====================================================================== 번호 검사

class Issue:
    def __init__(self, kind, para, message, fix=None, severity="경고"):
        self.kind = kind
        self.para = para
        self.message = message
        self.fix = fix                # 제안하는 문단 전체 텍스트 (없으면 None)
        self.severity = severity


CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
RE_ITEM = re.compile(r"^(\s*)\((\d{1,2})\)")
RE_CIRC = re.compile(r"^(\s*)([①-⑳])")
RE_CAPTION = re.compile(r"<\s*(그림|표)\s*(\d+)\s*([.\-])\s*(\d+)")


def _replace_head_number(text, old, new):
    i = text.find(old)
    if i < 0:
        return None
    return text[:i] + new + text[i + len(old):]


def chapter_of(sec):
    """절이 속한 장(Section, level 0). 없으면 None"""
    while sec is not None and sec.level > 0:
        sec = sec.parent
    return sec if sec is not None and sec.level == 0 and sec.number else None


RE_CH_NUM = re.compile(r"(제\s*)(\d+)(\s*장)")


def check_numbering(rep, doc):
    issues = []
    roots = rep.roots.get(doc.key, [])

    # 1) 장 번호 순서 (같은 편 안에서 1,2,3… — 첫 장 번호부터 이어지는지)
    chap_exp = {}                     # 장 → 올바른 장 번호 (하위 절은 이 번호 기준으로 검사)

    def check_chapters(siblings):
        chaps = [c for c in siblings if c.level == 0 and c.number.isdigit()]
        if len(chaps) < 2:
            return
        start = int(chaps[0].number)
        for i, c in enumerate(chaps):
            exp = str(start + i)
            chap_exp[id(c)] = exp
            if c.number != exp:
                text = rep.text(c.para) if c.para else ""
                m = RE_CH_NUM.search(text)
                fix = text[:m.start(2)] + exp + text[m.end(2):] if m else None
                why = "번호 중복" if sum(1 for k in chaps if k.number == c.number) > 1 else "번호 순서"
                issues.append(Issue("장 번호", c.para, f"'{c.label}' — 순서상 제{exp}장 이어야 합니다 ({why})", fix, "오류"))
    check_chapters(roots)
    for r in roots:
        if r.level == -1:
            check_chapters(r.children)

    # 2) 절 번호 — 각 절이 속한 장 번호 기준
    def walk(sec):
        kids = [c for c in sec.children if c.level > 0]
        for i, c in enumerate(kids):
            ch = chapter_of(c)
            N = chap_exp.get(id(ch), ch.number) if ch else None
            base = N if sec.level == 0 else sec.number
            expected = f"{base}.{i + 1}" if (base and sec.level >= 0) else None
            cur = c.number
            text = rep.text(c.para) if c.para else ""
            if N and cur.split(".")[0] != N:
                fix_num = expected or (N + cur[cur.find("."):])
                issues.append(Issue("장 번호", c.para,
                                    f"'{cur} {c.title}' — 제{N}장인데 번호가 {cur.split('.')[0]}로 시작합니다 → {fix_num}",
                                    _replace_head_number(text, cur, fix_num), "오류"))
            elif expected and cur != expected:
                dup = [k for k in kids if k.number == cur]
                why = "번호 중복" if len(dup) > 1 else "번호 순서"
                issues.append(Issue(why, c.para,
                                    f"'{cur} {c.title}' — 순서상 {expected} 이어야 합니다 ({why})",
                                    _replace_head_number(text, cur, expected), "오류"))
        for c in sec.children:
            walk(c)
    for r in roots:
        walk(r)

    # 2) (1)(2) 항목, ①② 항목 — 각 절의 본문 안에서
    for sec in rep.all_sections(doc):
        if not sec.para:
            continue
        seq_item = 0
        seq_circ = 0
        for k, obj in doc.blocks[sec.block_idx + 1:sec.own_end]:
            if k != "p" or obj.kind != "body":
                continue
            t = rep.text(obj)
            m = RE_ITEM.match(t)
            if m:
                n = int(m.group(2))
                exp = seq_item + 1
                if n != exp:
                    fix = t[:m.start(2) - 1] + f"({exp})" + t[m.end(2) + 1:]
                    why = "중복" if n <= seq_item else "누락"
                    issues.append(Issue("항목 번호", obj,
                                        f"[{sec.label}] ({n}) — 앞 항목이 ({seq_item})이므로 ({exp}) 이어야 합니다 (번호 {why})",
                                        fix))
                seq_item = n if n == exp else exp
                seq_circ = 0
                continue
            m = RE_CIRC.match(t)
            if m:
                n = CIRCLED.index(m.group(2)) + 1
                exp = seq_circ + 1
                if n != exp and exp <= len(CIRCLED):
                    fix = t[:m.start(2)] + CIRCLED[exp - 1] + t[m.end(2):]
                    issues.append(Issue("항목 번호", obj,
                                        f"[{sec.label}] {m.group(2)} — {CIRCLED[exp - 1]} 이어야 합니다", fix))
                    seq_circ = exp
                else:
                    seq_circ = n

    # 3) <그림 N.M>, <표 N.M> — 문단이 속한 장 기준, 장이 바뀌면 번호 다시 시작
    last = {}
    cur_ch = None
    for p in doc.paras:
        ch = chapter_of(p.section)
        if ch is not cur_ch:
            cur_ch, last = ch, {}
        N = ch.number if ch else None
        t = rep.text(p)
        for m in RE_CAPTION.finditer(t):
            kind, chn, sep, no = m.group(1), m.group(2), m.group(3), int(m.group(4))
            label = m.group(0) + ">"
            if N and chn != N:
                fix = t[:m.start(2)] + N + t[m.end(2):]
                issues.append(Issue("캡션 번호", p, f"{label} — 제{N}장의 {kind}인데 장 번호가 {chn}입니다", fix, "오류"))
            prev = last.get(kind, 0)
            if no != prev + 1:
                why = "중복" if no <= prev else "건너뜀"
                issues.append(Issue("캡션 번호", p, f"{label} — 이전 {kind} 번호가 {prev}이므로 {prev + 1} 예상 ({why})"))
            last[kind] = max(prev, no)
    # 고칠 내용이 현재와 같은 항목(이미 맞음)은 보고하지 않음
    return [i for i in issues if not (i.fix is not None and i.para is not None and i.fix == rep.text(i.para))]


# ====================================================================== 문구 비교/전파

SEP = set(" \t\n,()[]{}<>\"'「」『』·;、。")


def _tok_bounds(s, a, b):
    """[a,b) 를 단어(구분자 사이) 경계까지 확장"""
    while a > 0 and s[a - 1] not in SEP:
        a -= 1
    while b < len(s) and s[b] not in SEP:
        b += 1
    if b - a < 2 or not s[a:b].strip():          # 너무 짧으면 이웃 단어 포함
        if a > 0:
            a -= 1
            while a > 0 and s[a - 1] not in SEP:
                a -= 1
        if b - a < 2 and b < len(s):
            b += 1
            while b < len(s) and s[b] not in SEP:
                b += 1
    return a, b


def change_spans(old, new):
    """old → new 의 바뀐 부분을 단어 단위 (옛 문구, 새 문구) 목록으로"""
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    ops = [op for op in sm.get_opcodes() if op[0] != "equal"]
    if not ops:
        return []
    ranges = []
    for tag, i1, i2, j1, j2 in ops:
        a, b = _tok_bounds(old, i1, i2)
        ranges.append([a, b])
    ranges.sort()
    merged = []
    for a, b in ranges:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])

    out = []
    for a, b in merged:
        na = _map(ops, a, left=True)
        nb = _map(ops, b, left=False)
        out.append((old[a:b], new[na:nb]))
    return out


def _map(ops, pos, left):
    """old 위치 → new 위치. left=True 는 구간 시작(삽입은 뒤쪽에 둠), False 는 끝(삽입 포함)"""
    delta = 0
    for tag, i1, i2, j1, j2 in ops:
        if i2 < pos or (i2 == pos and (i1 < i2 or not left)):
            delta += (j2 - j1) - (i2 - i1)
    return pos + delta


def _inner_spans(o, n):
    """'fck=24MPa'→'fck=27MPa' 처럼 단어 안의 숫자+단위만 바뀐 경우 '24MPa'→'27MPa' 도 찾기"""
    out = []
    sm = difflib.SequenceMatcher(None, o, n, autojunk=False)
    ops = [op for op in sm.get_opcodes() if op[0] != "equal"]
    if not ops:
        return out
    a, b = ops[0][1], ops[-1][2]
    c, d = ops[0][3], ops[-1][4]
    isw = lambda ch: ch.isalnum() or ch in ".%㎡㎜"
    while a > 0 and isw(o[a - 1]) and c > 0:
        a -= 1
        c -= 1
    while b < len(o) and isw(o[b]) and d < len(n):
        b += 1
        d += 1
    if (a, b) != (0, len(o)) and b - a >= 2 and re.search(r"\d", o[a:b]):
        out.append((o[a:b], n[c:d]))
    return out


def _span_regex(s):
    pre = r"(?<![0-9A-Za-z.])" if s[:1].isascii() and s[:1].isalnum() else ""
    post = r"(?![0-9A-Za-z])" if s[-1:].isascii() and s[-1:].isalnum() else ""
    return re.compile(pre + re.escape(s) + post)


def norm_ws(s):
    return re.sub(r"\s+", "", s)


def ratio(a, b):
    a, b = norm_ws(a), norm_ws(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


class Candidate:
    def __init__(self, para, old_text, new_text, reason, score, checked):
        self.para = para
        self.old_text = old_text
        self.new_text = new_text
        self.reason = reason
        self.score = score
        self.checked = checked


def propagation_candidates(rep, changes, limit=400):
    """changes: [(para, 옛 텍스트, 새 텍스트)] → 다른 곳의 수정 후보"""
    srcs = {p.uid for p, _, _ in changes}
    found = {}
    for p, old, new in changes:
        spans = [(o, n) for o, n in change_spans(old, new) if len(o.strip()) >= 2 and o != n]
        heavy = sum(len(o) for o, _ in spans) > 0.6 * max(1, len(old)) or len(spans) > 6
        if not heavy:
            inner = [x for o, n in spans for x in _inner_spans(o, n) if x not in spans]
            main_hits = set()
            for o, n in spans + inner:
                is_inner = (o, n) in inner
                rx = _span_regex(o)
                for q in rep.all_paras():
                    if q.uid in srcs or (is_inner and q.uid in main_hits):
                        continue
                    cur = found[q.uid].new_text if q.uid in found else rep.text(q)
                    if not rx.search(cur):
                        continue
                    newq = rx.sub(lambda m: n, cur)
                    if not is_inner:
                        main_hits.add(q.uid)
                    sim = ratio(rep.text(q), old) if len(norm_ws(rep.text(q))) >= 8 else 0
                    checked = (len(norm_ws(o)) >= 4 and not re.fullmatch(r"[\d.,]+\D{0,4}", o)) or sim >= 0.5
                    why = f"같은 문구 '{_short(o)}' → '{_short(n)}'"
                    if sim >= 0.5:
                        why += f" · 문단 유사도 {sim:.0%}"
                    if q.uid in found:
                        c = found[q.uid]
                        c.new_text = newq
                        c.reason += " / " + why
                        c.checked = c.checked or checked
                    else:
                        found[q.uid] = Candidate(q, rep.text(q), newq, why, max(sim, 0.3), checked)
        # 문단 전체가 비슷한데 바뀐 문구가 정확히 일치하지 않는 경우 → 문단 전체 교체 제안
        if len(norm_ws(old)) >= 15:
            for q, sim in rep.index().similar(old, min_ratio=0.75):
                if q.uid in srcs or q.uid in found:
                    continue
                found[q.uid] = Candidate(q, rep.text(q), new,
                                         f"유사 문단(유사도 {sim:.0%}) — 문단 전체를 같은 내용으로 교체",
                                         sim, sim >= 0.95)
        if len(found) > limit:
            break
    return sorted(found.values(), key=lambda c: (-c.checked, -c.score))[:limit]


def _short(s, n=24):
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[:n - 1] + "…"


# ====================================================================== 유사 문단 색인

class SimilarIndex:
    N = 3

    def __init__(self, rep, min_len=12):
        self.rep = rep
        self.items = {}
        self.inv = {}
        for p in rep.all_paras():
            t = norm_ws(rep.text(p))
            if len(t) < min_len or _mostly_numeric(t) or len(re.findall(r" {3,}", rep.text(p))) >= 3:
                continue
            grams = self._grams(t)
            self.items[p.uid] = (p, t, grams)
            for g in grams:
                self.inv.setdefault(g, set()).add(p.uid)

    def _grams(self, t):
        return {t[i:i + self.N] for i in range(len(t) - self.N + 1)}

    def similar(self, text, min_ratio=0.75, exclude=None, limit=50):
        t = norm_ws(text)
        if len(t) < 8:
            return []
        grams = self._grams(t)
        cnt = {}
        for g in grams:
            for uid in self.inv.get(g, ()):
                cnt[uid] = cnt.get(uid, 0) + 1
        out = []
        for uid, c in cnt.items():
            if uid == exclude:
                continue
            p, t2, g2 = self.items[uid]
            if c / max(len(grams), len(g2)) < min_ratio * 0.6:
                continue
            r = difflib.SequenceMatcher(None, t, t2, autojunk=False).ratio()
            if r >= min_ratio:
                out.append((p, r))
        out.sort(key=lambda x: -x[1])
        return out[:limit]

    def inconsistent_pairs(self, lo=0.82, min_len=25):
        """서로 다른 절에 있는, 거의 같지만 조금 다른 문단 쌍"""
        pairs = []
        seen = set()
        for uid, (p, t, g) in self.items.items():
            if len(t) < min_len or _hangul_ratio(t) < 0.3:
                continue
            for q, r in self.similar(t, min_ratio=lo, exclude=uid, limit=20):
                if r >= 0.9999:
                    continue
                key = tuple(sorted((t, self.items[q.uid][1])))
                if key in seen:
                    continue
                seen.add(key)
                if p.section is q.section:
                    continue
                if p.section and q.section and p.doc is q.doc and p.section.number == q.section.number:
                    continue
                pairs.append((p, q, r))
        pairs.sort(key=lambda x: -x[2])
        return pairs


def _hangul_ratio(t):
    return sum("가" <= ch <= "힣" for ch in t) / max(1, len(t))


def _mostly_numeric(t):
    digits = sum(ch.isdigit() or ch in ".,+-()/=" for ch in t)
    return digits > 0.6 * len(t)


# ====================================================================== 공통 항목

COMMON_KEYS = ["과업명", "용역명", "시설물명", "건물명", "위치", "소재지", "사용용도", "주용도", "용도",
               "규모", "구조형식", "구조", "연면적", "건축면적", "대지면적", "준공연도", "준공일", "사용승인일",
               "관리주체", "종별", "시설물종류", "층수", "높이"]
FACT_PATTERNS = [r"fck\s*=\s*\d+(?:\.\d+)?\s*MPa", r"fy\s*=\s*\d+(?:\.\d+)?\s*MPa"]


def extract_common(rep):
    found = []
    seen = set()
    keys = {k: k for k in COMMON_KEYS}
    for d in rep.docs:
        for t in d.tables:
            for (r, c), cell in t.cells.items():
                k = norm_ws(" ".join(rep.text(p) for p in cell["paras"]))
                if k not in keys or k in seen:
                    continue
                nxt = t.cells.get((r, c + cell["cs"]))
                if not nxt:
                    continue
                v = " ".join(rep.text(p) for p in nxt["paras"]).strip()
                if v and v != "-":
                    found.append([k, v])
                    seen.add(k)
    for pat in FACT_PATTERNS:
        for p in rep.all_paras():
            m = re.search(pat, rep.text(p))
            if m:
                name = m.group(0).split("=")[0].strip()
                if name not in seen:
                    found.append([name, m.group(0)])
                    seen.add(name)
                break
    return found


def value_occurrences(rep, value):
    """값의 사용처: (para, 일치문자열, 정확히일치?)"""
    value = value.strip()
    if not value:
        return []
    exact = _span_regex(value)
    if re.search(r"\d", value):
        parts = re.split(r"(\d+(?:[.,]\d+)*)", value)
        pat = "".join(r"\d+(?:[.,]\d+)*" if i % 2 else r"\s*".join(map(re.escape, norm_ws(x)))
                      for i, x in enumerate(parts) if x != "")
    else:
        pat = r"\s*".join(map(re.escape, norm_ws(value)))
    loose = re.compile(pat)
    out = []
    for p in rep.all_paras():
        t = rep.text(p)
        hits = set()
        for m in exact.finditer(t):
            hits.add(m.group(0))
            out.append((p, m.group(0), True))
        for m in loose.finditer(t):
            if m.group(0) not in hits and m.group(0) != value:
                out.append((p, m.group(0), False))
    return out


# ====================================================================== AI 검토

AI_SYSTEM = """당신은 한국의 건축물 정밀안전진단·구조안전성검토 보고서를 교정하는 숙련된 구조기술사입니다.
주어진 보고서의 한 절(節)을 읽고 오타, 맞춤법, 띄어쓰기, 어색한 표현, 기술적 내용 오류, 용어·수치 불일치, 번호 체계 오류, 표의 계산 오류를 찾아 수정안을 제시합니다.

규칙
- 문단은 [P123] 형식의 ID로 구분됩니다. 반드시 해당 ID를 사용하세요.
- "original"은 해당 문단에서 그대로 복사한 짧은 문구여야 합니다(띄어쓰기 포함 정확히). 문단 전체가 아니라 바꿀 부분과 최소한의 앞뒤 글자만 포함하세요.
- "suggestion"은 original을 대체할 문구입니다. 직접 바꿀 문구가 없는 지적(확인 요청 등)은 suggestion을 ""로 두고 reason에 설명하세요.
- 제목·표 머리글의 의도적인 자간 띄우기(예: '개 요', '과   업   명', '구  분')는 지적하지 마세요.
- 보고서 문체(~하였다, ~검토되었다, ~판단된다)는 유지하고, 의미가 같은데 취향만 다른 문장 다듬기는 하지 마세요.
- 단위·기호(kN/m2, MPa, fck, fy, DL, LL 등)와 구조 용어(내하력비, P-M 상관곡선 등)를 존중하세요.
- 장 번호가 주어지면 절 번호·그림/표 번호가 그 장 번호로 시작하는지 확인하세요.
- 표의 합계·하중조합(예: 1.4D+1.7L) 계산은 표에서 명확히 확인 가능한 경우에만 검산하여 지적하세요.
- 공통 항목(과업명, 연면적, 재료강도 등)이 주어지면 본문 수치와 일치하는지 확인하세요.
- 확실하지 않은 내용은 type을 "확인"으로 하고 suggestion은 ""로 두세요.

출력은 아래 JSON 하나만, 다른 말 없이:
{"summary": "이 절에 대한 한두 문장 총평",
 "suggestions": [{"id": "P123", "type": "오타|맞춤법|띄어쓰기|표현|내용|일관성|번호|계산|확인",
                  "original": "...", "suggestion": "...", "reason": "짧은 이유"}]}"""


class Suggestion:
    def __init__(self, para, typ, original, suggestion, reason, span):
        self.para = para
        self.type = typ
        self.original = original
        self.suggestion = suggestion
        self.reason = reason
        self.span = span              # (start, end) in current text, None 이면 자동 적용 불가
        self.state = "대기"            # 대기 | 적용 | 무시

    @property
    def applicable(self):
        return self.span is not None and self.suggestion != "" and self.suggestion != self.original

    def new_text(self, current):
        s, e = self.span
        return current[:s] + self.suggestion + current[e:]


def find_loose(text, original):
    """띄어쓰기 차이를 허용하여 original 위치 찾기"""
    if not original:
        return None
    i = text.find(original)
    if i >= 0:
        return (i, i + len(original))
    core = norm_ws(original)
    if not core:
        return None
    rx = re.compile(r"\s*".join(map(re.escape, core)))
    m = rx.search(text)
    return (m.start(), m.end()) if m else None


PROVIDERS = {                       # id → 표시 이름
    "claude": "Claude (Anthropic API, 유료)",
    "ollama": "Ollama (무료, 내 PC에서 실행)",
    "openai": "OpenAI 호환 서버 (LM Studio·vLLM 등)",
}
DEFAULT_URL = {"ollama": "http://localhost:11434", "openai": "http://localhost:1234/v1"}


def _is_local(url):
    return any(h in url for h in ("://localhost", "://127.0.0.1", "://[::1]", "://0.0.0.0"))


def _http_json(url, body=None, headers=None, timeout=60):
    """JSON 요청. 내 PC(localhost) 주소는 회사 프록시를 거치지 않게 한다."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers=dict({"content-type": "application/json"}, **(headers or {})))
    opener = (urllib.request.build_opener(urllib.request.ProxyHandler({})) if _is_local(url)
              else urllib.request.build_opener())
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def list_local_models(provider, base_url):
    """Ollama / OpenAI 호환 서버에 설치된 모델 이름 목록"""
    base = (base_url or DEFAULT_URL.get(provider, "")).rstrip("/")
    try:
        if provider == "ollama":
            return [m["name"] for m in _http_json(base + "/api/tags", timeout=10).get("models", [])]
        if provider == "openai":
            return [m["id"] for m in _http_json(base + "/models", timeout=10).get("data", [])]
    except urllib.error.URLError as e:
        raise RuntimeError(_conn_hint(provider, base, e))
    return []


def _conn_hint(provider, base, e):
    reason = getattr(e, "reason", e)
    if provider == "ollama":
        return (f"Ollama에 연결하지 못했습니다 ({base}): {reason}\n\n"
                "· Ollama 설치: https://ollama.com/download\n"
                "· 설치 후 Ollama 앱이 실행 중인지(작업표시줄 아이콘) 확인하세요.")
    if provider == "openai":
        return f"서버에 연결하지 못했습니다 ({base}): {reason}\nLM Studio 등에서 'Local Server'를 시작했는지 확인하세요."
    return f"네트워크 오류: {reason}"


class AIClient:
    """AI 검토 엔진. provider: claude | ollama | openai(호환)"""
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key="", model="claude-sonnet-5-5", timeout=None, provider="claude",
                 base_url=None, num_ctx=16384):
        self.provider = provider if provider in PROVIDERS else "claude"
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or DEFAULT_URL.get(self.provider, "")).rstrip("/")
        self.num_ctx = num_ctx
        self.timeout = timeout or (240 if self.provider == "claude" else 900)

    @property
    def local(self):
        return self.provider != "claude"

    @property
    def max_chars(self):
        """한 번에 보낼 본문 길이. 내 PC 모델은 문맥 길이가 짧아서 잘게 나눔"""
        return 24000 if self.provider == "claude" else max(4000, int(self.num_ctx * 0.45))

    def describe(self):
        return f"{PROVIDERS[self.provider].split(' (')[0]} · {self.model}"

    def complete(self, system, user, max_tokens=8000):
        try:
            if self.provider == "ollama":
                return self._ollama(system, user, max_tokens)
            if self.provider == "openai":
                return self._openai(system, user, max_tokens)
            return self._claude(system, user, max_tokens)
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")
            try:
                j = json.loads(msg)
                msg = j["error"]["message"] if isinstance(j.get("error"), dict) else j.get("error", msg)
            except Exception:
                pass
            if self.provider == "ollama" and e.code == 404:
                msg += f"\n\n모델이 설치되어 있지 않습니다. 명령 프롬프트에서:  ollama pull {self.model}"
            raise RuntimeError(f"API 오류 {e.code}: {msg}")
        except urllib.error.URLError as e:
            raise RuntimeError(_conn_hint(self.provider, self.base_url, e))
        except TimeoutError:
            raise RuntimeError("응답 시간이 초과되었습니다. 더 작은 모델을 쓰거나 '하위 절 포함'을 끄고 작은 절 단위로 검토하세요.")

    def _claude(self, system, user, max_tokens):
        data = _http_json(self.URL, {
            "model": self.model, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}]},
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}, self.timeout)
        return "".join(c.get("text", "") for c in data.get("content", []) if c.get("type") == "text")

    def _ollama(self, system, user, max_tokens):
        data = _http_json(self.base_url + "/api/chat", {
            "model": self.model, "stream": False, "format": "json",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": 0.2, "num_ctx": self.num_ctx,
                        "num_predict": min(max_tokens, self.num_ctx // 2)}},
            timeout=self.timeout)
        return (data.get("message") or {}).get("content", "")

    def _openai(self, system, user, max_tokens):
        hdr = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = _http_json(self.base_url + "/chat/completions", {
            "model": self.model, "temperature": 0.2, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
            hdr, self.timeout)
        return data["choices"][0]["message"]["content"]


def _parse_json(s):
    s = s.strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b < 0:
        raise ValueError("AI 응답에서 JSON을 찾지 못했습니다. 다시 시도하거나 더 큰 모델을 사용하세요.")
    try:
        return json.loads(s[a:b + 1])
    except json.JSONDecodeError:
        raise ValueError("AI 응답 형식(JSON)이 올바르지 않습니다. 다시 시도하거나 더 큰 모델을 사용하세요.")


def ai_review(rep, client, sec, include_children=True, progress=None):
    """→ (summary, [Suggestion])"""
    chunks, idmap = section_for_ai(rep, sec, include_children,
                                   max_chars=getattr(client, "max_chars", 24000))
    chap = sec
    while chap.parent:
        chap = chap.parent
    head = [f"검토 대상: {sec.label}"]
    if chap.level == 0 and chap.number:
        head.append(f"이 파일은 제{chap.number}장입니다.")
    if rep.common:
        head.append("공통 항목: " + "; ".join(f"{k}={v}" for k, v in rep.common))
    summaries, out = [], []
    for i, ch in enumerate(chunks):
        if progress:
            progress(f"AI 검토 중… ({i + 1}/{len(chunks)})")
        part = f" (전체 {len(chunks)}개 중 {i + 1}번째 부분)" if len(chunks) > 1 else ""
        user = "\n".join(head) + part + "\n\n----- 본문 -----\n" + ch
        data = _parse_json(client.complete(AI_SYSTEM, user))
        if isinstance(data, list):
            data = {"suggestions": data}
        if data.get("summary"):
            summaries.append(data["summary"])
        for s in data.get("suggestions", []):
            sid = str(s.get("id", "")).strip("[] ")
            if sid.isdigit():
                sid = "P" + sid
            p = idmap.get(sid)
            if p is None:
                continue
            orig = s.get("original", "") or ""
            sug = s.get("suggestion", "") or ""
            span = find_loose(rep.text(p), orig)
            out.append(Suggestion(p, s.get("type", ""), orig, sug, s.get("reason", ""), span))
    return " ".join(summaries), out


# ====================================================================== 한글 파일에 반영

class Replacement:
    def __init__(self, doc, paras, old, new):
        self.doc = doc
        self.paras = paras            # 이 바꾸기가 반영하는 문단들
        self.old = old
        self.new = new
        self.ok = None


class ManualItem:
    def __init__(self, para, new_text, why):
        self.para = para
        self.new_text = new_text
        self.why = why


MAX_ANCHOR = 250


def _hunks(old, new, gap=4):
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    ops = [op for op in sm.get_opcodes() if op[0] != "equal"]
    groups = []
    for op in ops:
        if groups and op[1] - groups[-1][-1][2] < gap:
            groups[-1].append(op)
        else:
            groups.append([op])
    return [(g[0][1], g[-1][2], g[0][3], g[-1][4]) for g in groups]


def _valid_anchor(p, a, b):
    for k in p.breaks:
        if a < k < b:
            return False
        if k == a and k < len(p.orig) and p.orig[k] in "\t\n" and a < b:
            return False
    seg = p.orig[a:b]
    return "\t" not in seg and "\n" not in seg


def plan_changes(rep, doc):
    """doc 의 수정 대기 → (바꾸기 목록, 수동 처리 목록)"""
    hay = doc.full_text()
    reps, manual = [], []
    for p in doc.paras:
        if p.uid not in rep.edits:
            continue
        new = rep.edits[p.uid]
        old = p.orig
        if "\t" in new or "\n" in new:
            if new.count("\t") != old.count("\t") or new.count("\n") != old.count("\n"):
                manual.append(ManualItem(p, new, "탭/줄바꿈이 추가·삭제됨"))
                continue
        hunks = _hunks(old, new)
        # 같은 문단의 hunk 들을 하나씩 anchor 로
        pieces = []
        ok = True
        for i1, i2, j1, j2 in hunks:
            a, b = i1, i2
            # 최소 길이 6 확보 + 고유해질 때까지 확장
            while True:
                if b - a >= 6 and _valid_anchor(p, a, b) and hay.count(old[a:b]) == 1:
                    break
                grew = False
                if b < len(old) and _valid_anchor(p, a, b + 1):
                    b += 1
                    grew = True
                if (b - a < 6 or hay.count(old[a:b]) != 1) and a > 0 and _valid_anchor(p, a - 1, b):
                    a -= 1
                    grew = True
                if not grew or b - a > MAX_ANCHOR:
                    ok = False
                    break
            if not ok:
                break
            pieces.append((a, b, i1, i2, j1, j2))
        if not ok or not pieces:
            why = "같은 문구가 문서에 여러 번 있거나 표/그림/탭 경계에 걸침"
            if hunks and any(i2 - i1 > MAX_ANCHOR or j2 - j1 > MAX_ANCHOR for i1, i2, j1, j2 in hunks):
                why = "바뀐 부분이 너무 김"
            manual.append(ManualItem(p, new, why))
            continue
        # 겹치는 anchor 합치기
        pieces.sort()
        merged = []
        for pc in pieces:
            if merged and pc[0] < merged[-1][1]:
                m = merged[-1]
                merged[-1] = (m[0], max(m[1], pc[1]), m[2], pc[3], m[4], pc[5])
            else:
                merged.append(pc)
        for a, b, i1, i2, j1, j2 in merged:
            old_anchor = old[a:b]
            new_anchor = old[a:i1] + new[j1:j2] + old[i2:b]
            if len(old_anchor) > MAX_ANCHOR or len(new_anchor) > MAX_ANCHOR:
                manual.append(ManualItem(p, new, "바뀐 부분이 너무 김"))
                break
            reps.append(Replacement(doc, [p], old_anchor, new_anchor))
    return reps, manual


class HwpApplier:
    """한글 자동화(COM)로 원본 파일 수정. Windows + 한글 + pywin32 필요"""

    @staticmethod
    def available():
        try:
            import win32com.client  # noqa
            return True
        except Exception:
            return False

    def __init__(self, visible=False):
        import win32com.client as win32
        try:
            self.hwp = win32.gencache.EnsureDispatch("HWPFrame.HwpObject")
        except Exception:
            self.hwp = win32.Dispatch("HWPFrame.HwpObject")
        try:
            self.hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        except Exception:
            pass
        try:
            self.hwp.XHwpWindows.Item(0).Visible = visible
        except Exception:
            pass

    def _all_replace(self, old, new):
        h = self.hwp
        ps = h.HParameterSet.HFindReplace
        h.HAction.GetDefault("AllReplace", ps.HSet)
        ps.FindString = old
        ps.ReplaceString = new
        for name, val in (("IgnoreMessage", 1), ("FindRegExp", 0), ("MatchCase", 1),
                          ("WholeWordOnly", 0), ("UseWildCards", 0), ("SeveralWords", 0),
                          ("AllWordForms", 0), ("FindJaso", 0), ("ReplaceMode", 1)):
            try:
                setattr(ps, name, val)
            except Exception:
                pass
        try:
            ps.Direction = h.FindDir("AllDoc")
        except Exception:
            pass
        return bool(h.HAction.Execute("AllReplace", ps.HSet))

    def apply(self, path, replacements, log=print):
        fmt = "HWPX" if path.lower().endswith(".hwpx") else "HWP"
        if not self.hwp.Open(path, fmt, "forceopen:true"):
            raise RuntimeError("한글에서 파일을 열지 못했습니다: " + path)
        try:
            for r in replacements:
                r.ok = self._all_replace(r.old, r.new)
                log(("  ✔ " if r.ok else "  ✖ ") + _short(r.old, 40) + " → " + _short(r.new, 40))
            self.hwp.SaveAs(path, fmt, "")
        finally:
            try:
                self.hwp.Clear(1)
            except Exception:
                pass

    def quit(self):
        try:
            self.hwp.Quit()
        except Exception:
            pass


def backup_file(path):
    d = os.path.join(os.path.dirname(path), "_백업")
    os.makedirs(d, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base, ext = os.path.splitext(os.path.basename(path))
    dst = os.path.join(d, f"{base}_{stamp}{ext}")
    shutil.copy2(path, dst)
    return dst


def verify_after_apply(rep, doc, expected):
    """다시 읽은 문서에서 기대한 문단 텍스트가 실제로 있는지 확인. expected: {seq: 새텍스트}"""
    texts = {norm_ws(p.orig) for p in doc.paras}
    ok, fail = [], []
    for seq, txt in expected.items():
        (ok if norm_ws(txt) in texts else fail).append(seq)
    return ok, fail


def export_changes_csv(rep, path, manual_only=None):
    import csv
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["파일", "위치(절)", "구분", "원문", "수정문", "출처", "비고"])
        items = manual_only if manual_only is not None else [
            ManualItem(rep.paras[uid], txt, "") for uid, txt in rep.edits.items() if uid in rep.paras]
        for m in items:
            p = m.para
            w.writerow([os.path.basename(p.doc.path), p.section.label if p.section else "",
                        {"body": "본문", "cell": "표", "box": "글상자"}.get(p.kind, p.kind),
                        p.orig, m.new_text, rep.edit_src.get(p.uid, ""), m.why])


# ====================================================================== Word: 구조 편집 (절·문단·표·사진 추가)

def _dx():
    import docx_doc
    return docx_doc


def rebuild_docx(rep, doc):
    """메모리의 Word 문서를 다시 분석 (구조 추가 후). 수정 대기는 문단 요소 기준으로 유지"""
    dx = _dx()
    keep = {}
    for p in doc.paras:
        if p.uid in rep.edits and p.ref is not None:
            keep[id(p.ref)] = (p.orig, rep.edits.pop(p.uid), rep.edit_src.pop(p.uid, ""))
    for p in doc.paras:
        rep.paras.pop(p.uid, None)
    new = dx.read_docx(doc.path, doc.key, document=doc.docx)
    new.dirty = True
    i = rep.docs.index(doc)
    rep.docs[i] = new
    rep._register(new)
    for p in new.paras:
        k = keep.get(id(p.ref))
        if k and p.orig == k[0]:
            rep.edits[p.uid] = k[1]
            rep.edit_src[p.uid] = k[2]
    return new


def _top_level(el):
    """표 안 문단이면 바깥 표 요소까지 올라감"""
    while el is not None and el.getparent() is not None:
        par = el.getparent()
        if par.tag in (_dx().qn("w:body"), _dx().W_SDTC):
            return el
        el = par
    return el


def _bump(num, delta=1):
    parts = num.split(".")
    parts[-1] = str(int(parts[-1]) + delta)
    return ".".join(parts)


RE_HEAD_NUM = re.compile(r"^(\s*)(\d+(?:\.\d+)*)(\.?\s+)")


def _heading_text_like(template_text, number, title, level):
    if level == 0:
        m = RE_CH_NUM.search(template_text)
        if m:
            pre = template_text[:m.start()]
            gap = re.match(r"^(\s*)", template_text[m.end():]).group(1) or "  "
            return f"{pre}{m.group(1)}{number}{m.group(3)}{gap}{title}"
        return f"제 {number} 장  {title}"
    m = RE_HEAD_NUM.match(template_text)
    if m:
        return f"{m.group(1)}{number}{m.group(3)}{title}"
    return f"{number} {title}"


def _renumber_sections(rep, secs, level_index, delta, src):
    """secs(형제 절들)와 하위 절의 번호 중 level_index 번째 자리를 delta 만큼 밀기"""
    n = 0
    for s in secs:
        for d in s.iter():
            if d.para is None:
                continue
            t = rep.text(d.para)
            if d.level == 0:
                m = RE_CH_NUM.search(t)
                if m and level_index == 0:
                    rep.set_edit(d.para, t[:m.start(2)] + str(int(m.group(2)) + delta) + t[m.end(2):], src)
                    n += 1
                continue
            m = RE_HEAD_NUM.match(t)
            if not m:
                continue
            parts = m.group(2).split(".")
            if level_index < len(parts):
                parts[level_index] = str(int(parts[level_index]) + delta)
                rep.set_edit(d.para, t[:m.start(2)] + ".".join(parts) + t[m.end(2):], src)
                n += 1
    return n


def add_section(rep, doc, sec, mode, title, body="", renumber=True):
    """mode: 'after' (같은 단계, 다음 번호) | 'child' (하위 절). → (새 제목 문단 요소, 밀린 번호 수)"""
    dx = _dx()
    if mode == "after":
        level = sec.level
        if level == 0:
            number = str(int(sec.number) + 1)
        else:
            number = _bump(sec.number)
        tmpl = sec.para.ref
        siblings = sec.parent.children if sec.parent else rep.roots[doc.key]
        later = [s for s in siblings if s.block_idx > sec.block_idx and s.level == level]
    else:
        level = sec.level + 1
        kids = [c for c in sec.children if c.level == level]
        if level == 0:
            number = str(int(kids[-1].number) + 1) if kids else "1"
        else:
            base = sec.number
            number = f"{base}.{len(kids) + 1}" if not kids else _bump(kids[-1].number)
        tmpl = dx.find_heading_template(rep, doc, level, prefer=kids[0] if kids else None)
        later = []
    if tmpl is None:
        raise ValueError("본뜰 제목 문단을 찾지 못했습니다.")
    anchor = _top_level(dx.end_anchor(doc, sec))
    head_txt = _heading_text_like("".join(dx.para_text(tmpl)[0]), number, title, level)
    head_el = dx.clone_para(tmpl, head_txt)
    body_tmpl = dx.find_body_template(doc, sec)
    body_el = dx.clone_para(body_tmpl, body) if body_tmpl is not None else dx._plain_p(body)
    # 밀린 번호 (새 절 뒤에 있던 같은 단계 절들)
    moved = 0
    if renumber and later:
        idx = 0 if level == 0 else len(sec.number.split(".")) - 1
        moved = _renumber_sections(rep, later, idx, 1, "번호 밀기 (절 추가)")
    anchor.addnext(head_el)
    head_el.addnext(body_el)
    rep.new_refs.update({id(head_el), id(body_el)})
    rebuild_docx(rep, doc)
    return head_el, body_el, moved


def insert_paragraphs_after(rep, doc, para, texts):
    """Enter 로 나눈 문단: para 바로 뒤에 같은 모양 문단들 (제목이면 본문 모양). → 새 요소 목록"""
    dx = _dx()
    tmpl = para.ref
    if para.kind == "body" and (heading_of_para(para) or para.pic):
        tmpl = dx.find_body_template(doc, para.section)
    prev = para.ref if para.kind == "cell" else _top_level(para.ref)
    els = []
    for t in texts:
        el = dx.clone_para(tmpl, t)
        prev.addnext(el)
        prev = el
        els.append(el)
        rep.new_refs.add(id(el))
    rebuild_docx(rep, doc)
    return els


def add_picture_in_cell(rep, doc, table, rc_key, image_path):
    cell = table.cells.get(rc_key)
    if cell is None or cell.get("ref") is None:
        raise ValueError("Word 표 칸을 찾지 못했습니다.")
    tc = cell["ref"]
    el = _dx().add_picture_to_cell(doc, tc, image_path)
    rep.new_refs.add(id(table.ref))
    rebuild_docx(rep, doc)
    return el


def set_cells_text(rep, doc, items):
    """표 편집 저장: items=[(칸의 글 문단 Para 목록, 새 문단 글 목록)].
    문단 수가 바뀌면 Word 문단을 늘리거나 줄이고, 글은 수정 대기로 → [(Para, 옛, 새)]"""
    dx = _dx()
    pend = []                     # (요소, 새 글)
    structural = False
    for paras, texts in items:
        if len(paras) != len(texts) and doc.fmt == "docx" and paras and paras[0].ref is not None:
            els = dx.set_cell_paragraphs([p.ref for p in paras], texts)
            structural = True
            for el, t in zip(els, texts):
                pend.append((el, t))
        else:
            for p, t in zip(paras, texts):
                pend.append((p.ref if p.ref is not None else p, t))
    if structural:
        rebuild_docx(rep, doc)
    by_ref = {}
    for d in rep.docs:
        for p in d.paras:
            if p.ref is not None:
                by_ref[id(p.ref)] = p
    out = []
    for key, t in pend:
        p = by_ref.get(id(key)) if not hasattr(key, "uid") else key
        if p is not None and rep.text(p) != t:
            out.append((p, rep.text(p), t))
    return out


def add_paragraph(rep, doc, para, text="", as_body=True):
    """para 아래에 같은 모양(제목이면 본문 모양)의 새 문단"""
    dx = _dx()
    tmpl = para.ref
    if as_body and (heading_of_para(para) or para.pic or para.kind != "body"):
        tmpl = dx.find_body_template(doc, para.section)
    el = dx.clone_para(tmpl, text)
    _top_level(para.ref).addnext(el)
    rep.new_refs.add(id(el))
    rebuild_docx(rep, doc)
    return el


def heading_of_para(p):
    from hwp_reader import heading_of
    return heading_of(p)


def _chapter_no(sec):
    ch = chapter_of(sec)
    return ch.number if ch else (sec.number.split(".")[0] if sec and sec.number else "1")


def _caption_plan(rep, doc, after_el, kind, sec):
    """새 캡션 번호와, 뒤로 밀어야 할 같은 장 캡션들"""
    dx = _dx()
    chap = _chapter_no(sec)
    body = list(doc.docx.element.body.iter(dx.W_P))
    pos = {id(e): i for i, e in enumerate(body)}
    after_i = max((pos.get(id(e), -1) for e in [after_el] + list(after_el.iter(dx.W_P))), default=-1)
    before, later = 0, []
    for p in doc.paras:
        m = dx.RE_CAP_ANY.match(rep.text(p))
        if not m or m.group(2) != chap:
            continue
        same = m.group(1) == kind or (kind == "그림" and m.group(1) == "사진")
        if not same:
            continue
        if pos.get(id(p.ref), -1) <= after_i:
            before = max(before, int(m.group(3)))
        else:
            later.append((p, m))
    return chap, before + 1, later


def _shift_captions(rep, later, src):
    for p, m in later:
        t = rep.text(p)
        rep.set_edit(p, t[:m.start(3)] + str(int(m.group(3)) + 1) + t[m.end(3):], src)
    return len(later)


def _anchor_for(doc, para, sec):
    if para is not None:
        return _top_level(para.ref)
    return _top_level(_dx().end_anchor(doc, sec))


def add_table(rep, doc, para, sec, rows, cols, header=None, caption="", caption_pos="above"):
    dx = _dx()
    anchor = _anchor_for(doc, para, sec)
    sec = (para.section if para is not None else sec) or sec
    # 본뜰 표: 삽입 위치 앞쪽에서 가장 가까운 2×2 이상 표
    body_children = list(anchor.getparent())
    a_idx = body_children.index(anchor) if anchor in body_children else len(body_children)
    cands = [t for t in doc.tables if t.ref is not None and t.rows >= 2 and t.cols >= 2
             and t.ref.getparent() is anchor.getparent()]
    before = [t for t in cands if body_children.index(t.ref) < a_idx]
    tmpl = (before[-1] if before else (cands[0] if cands else None))
    if tmpl is not None:
        tbl = dx.build_table_like(tmpl.ref, rows, cols, header)
    else:
        tbl = dx.simple_table(doc.docx, rows, cols, header)
    moved = 0
    cap_el = None
    if caption is not None and caption.strip():
        chap, no, later = _caption_plan(rep, doc, anchor, "표", sec)
        cref, sample = dx.find_caption_template(doc, "표")
        txt = dx.caption_text_like(sample, "표", chap, no, caption.strip())
        cap_el = dx.clone_para(cref, txt) if cref is not None else dx.clone_para(anchor if anchor.tag == dx.W_P else dx.find_body_template(doc), txt)
        moved = _shift_captions(rep, later, "캡션 번호 밀기 (표 추가)")
    if cap_el is not None and caption_pos == "above":
        anchor.addnext(cap_el)
        cap_el.addnext(tbl)
    else:
        anchor.addnext(tbl)
        if cap_el is not None:
            tbl.addnext(cap_el)
    # Word 는 붙어 있는 두 표를 하나로 합쳐 보이므로 사이에 빈 문단을 둔다
    for t_el in (tbl,):
        for nb in (t_el.getprevious(), t_el.getnext()):
            if nb is not None and nb.tag == dx.W_TBL:
                bt = dx.find_body_template(doc)
                gap = dx.clone_para(bt if bt is not None else anchor, "")
                if nb is t_el.getprevious():
                    t_el.addprevious(gap)
                else:
                    t_el.addnext(gap)
    rep.new_refs.add(id(tbl))
    if cap_el is not None:
        rep.new_refs.add(id(cap_el))
    rebuild_docx(rep, doc)
    return tbl, moved


def add_picture(rep, doc, para, sec, image_path, width_cm=None, caption=""):
    dx = _dx()
    anchor = _anchor_for(doc, para, sec)
    sec = (para.section if para is not None else sec) or sec
    pic_el = dx.picture_para(doc, image_path, width_cm)
    moved = 0
    cap_el = None
    if caption is not None and caption.strip():
        chap, no, later = _caption_plan(rep, doc, anchor, "그림", sec)
        cref, sample = dx.find_caption_template(doc, "그림")
        txt = dx.caption_text_like(sample, "그림", chap, no, caption.strip())
        cap_el = dx.clone_para(cref, txt) if cref is not None else dx.clone_para(pic_el, txt)
        moved = _shift_captions(rep, later, "캡션 번호 밀기 (사진 추가)")
    anchor.addnext(pic_el)
    if cap_el is not None:
        pic_el.addnext(cap_el)
        rep.new_refs.add(id(cap_el))
    rep.new_refs.add(id(pic_el))
    rebuild_docx(rep, doc)
    return pic_el, moved


def delete_block(rep, doc, para):
    """새로 넣은 문단/표/그림 지우기 (실수 되돌리기용)"""
    el = _top_level(para.ref)
    el.getparent().remove(el)
    rebuild_docx(rep, doc)


def save_word(rep, doc, backup=True):
    """Word 파일에 수정 대기 + 구조 변경 저장 → (반영 문단 수, 실패 문단 [Para])"""
    dx = _dx()
    if backup and os.path.exists(doc.path):
        backup_file(doc.path)
    fail = []
    ok = 0
    for p in doc.paras:
        if p.uid not in rep.edits:
            continue
        try:
            dx.set_para_text(p.ref, p.orig, rep.edits[p.uid])
            ok += 1
        except Exception:
            fail.append(p)
    try:
        dx.save_docx(doc)
    except PermissionError:
        raise RuntimeError("Word 파일에 저장할 수 없습니다. Word에서 이 파일을 닫고 다시 시도하세요.\n" + doc.path)
    for p in doc.paras:
        if p not in fail:
            rep.edits.pop(p.uid, None)
            rep.edit_src.pop(p.uid, None)
    new, kept = rep.reload(doc)
    new.dirty = False
    return ok, fail


def hwp_to_docx(applier, src, dst):
    """한글 자동화로 .hwp → .docx 변환 (한글의 '다른 이름으로 저장 → Word 문서')"""
    h = applier.hwp
    fmt_in = "HWPX" if src.lower().endswith(".hwpx") else "HWP"
    if not h.Open(src, fmt_in, "forceopen:true"):
        raise RuntimeError("한글에서 파일을 열지 못했습니다: " + src)
    try:
        last = None
        for fmt in ("OOXML", "DOCX", "MSWORD"):
            try:
                if h.SaveAs(dst, fmt, "") and os.path.exists(dst) and os.path.getsize(dst) > 0:
                    return dst
            except Exception as e:  # noqa: BLE001
                last = e
        raise RuntimeError(f"Word 형식으로 저장하지 못했습니다 ({last or '형식 미지원'}).\n"
                           "한글에서 '파일 → 다른 이름으로 저장 → Word 문서(*.docx)'로 직접 저장하세요.")
    finally:
        try:
            h.Clear(1)
        except Exception:
            pass



def resize_picture(rep, doc, para, cx, cy):
    """그림 크기 바꾸기 (EMU)"""
    dx = _dx()
    pics = dx.pictures_in(para.ref)
    if not pics:
        raise ValueError("그림이 없는 문단입니다.")
    dx.set_picture_size(pics[0]["inline"], cx, cy)
    rep.new_refs.add(id(_top_level(para.ref)))
    rebuild_docx(rep, doc)


def table_op(rep, doc, table, fn):
    """Word 표 레이아웃 작업: fn(TGrid) 실행 후 다시 분석"""
    from docx_table import TGrid
    g = TGrid(table.ref)
    fn(g)
    rep.new_refs.add(id(table.ref))
    rebuild_docx(rep, doc)
