"""
Auto Table 점검:  python autotable/tests/test_autotable.py   (또는 pytest)
  · 철근 표기 정리
  · 보/기둥/벽/슬래브 DXF 내보내기 → 다시 가져오기 = 같은 값
  · 엑셀/TXT 내보내기 → 다시 가져오기
  · MIDAS 형(위치 I/M/J) 텍스트 표
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from at_core import model as M  # noqa: E402
from at_core import table_io as TI  # noqa: E402
from at_core.dxf_read import import_dxf  # noqa: E402
from at_core.dxf_write import default_template, export_dxf  # noqa: E402

BEAMS = [
    dict(name="-1G1", b="350", h="650", slab="200", kind="양단/중앙", e_top="-", e_bot="2-D19", e_stir="D10@250",
         m_top="-", m_bot="4-D19", m_stir="D10@300"),
    dict(name="-1G6", b="450", h="700", slab="200", kind="전단면", e_top="3-D22", e_bot="8-D19", e_stir="D10@200"),
    dict(name="RG12", b="450", h="2550", slab="200", kind="양단/중앙", e_top="-", e_bot="2-D19", e_stir="D10@150",
         m_top="-", m_bot="3-D19", m_stir="D10@200"),
    dict(name="2G3", b="500", h="800", slab="150", kind="외단/중앙/내단", e_top="5/2-HD22", e_bot="3-HD22", e_stir="HD10@150",
         m_top="3-HD22", m_bot="5-HD22", m_stir="HD10@200", j_top="6/2-HD22", j_bot="3-HD22", j_stir="HD10@150"),
] + [dict(name=f"B{i}", b="300", h="600", slab="150", kind="양단/중앙", e_top="3-D19", e_bot="3-D19", e_stir="D10@200",
          m_top="2-D19", m_bot="4-D19", m_stir="D10@250") for i in range(1, 13)]


def _full(mtype, rows):
    out = []
    for r in rows:
        x = M.new_row(mtype)
        x.update(r)
        out.append(x)
    return out


def test_normalize():
    assert M.norm_rebar("3-22") == "3-D22"
    assert M.norm_rebar("4d19", "HD") == "4-D19"
    assert M.norm_rebar("5/2-22", "UHD") == "5/2-UHD22"
    assert M.norm_rebar("D22-4") == "4-D22"
    assert M.norm_stir("10@200", "SHD") == "SHD10@200"
    assert M.norm_stir("2-10-150") == "2-D10@150"
    assert M.norm_spacing("10,13@300") == "D10,D13@300"
    assert M.swap_prefix("4-D19", "rebar", "UHD") == "4-UHD19"
    assert M.next_name("RG9") == "RG10"


def _cmp(mtype, a, b, skip=()):
    assert len(a) == len(b), (len(a), len(b))
    for x, y in zip(a, b):
        for c in M.cols(mtype):
            if c.key in skip or M.disabled(mtype, x, c.key):
                continue
            assert (x.get(c.key) or "") == (y.get(c.key) or ""), (x["name"], c.key, x.get(c.key), y.get(c.key))


def test_beam_dxf_roundtrip():
    assert os.path.isfile(default_template())
    rows = _full("beam", BEAMS)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "b.dxf")
        n = export_dxf(p, "beam", rows, opts={"drawing_no": "S-201", "notes": ["1. 테스트"]}, log=lambda *a: None)
        assert n == 2
        res, warn, meta = import_dxf(p, log=lambda *a: None)
        _cmp("beam", rows, res["beam"], skip=("note",))
        assert meta["drawing_no"] == "S-201"
        assert meta["notes"] == ["1. 테스트"]


def test_column_dxf_roundtrip():
    rows = _full("column", [dict(name=f"C{i}", floor="", b="600", h="700", shape="사각", main="12-D22", hoop_e="D10@150",
                                 hoop_m="D10@300") for i in range(1, 6)])
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "c.dxf")
        export_dxf(p, "column", rows, log=lambda *a: None)
        res, _, _ = import_dxf(p, "column", log=lambda *a: None)
        got = res["column"]
        assert [r["name"] for r in got] == [r["name"] for r in rows]
        assert all(r["main"] == "12-D22" and r["b"] == "600" and r["h"] == "700" for r in got)


def test_table_dxf_export():
    walls = _full("wall", [dict(name=f"W{i}", t="250", vert="D13@200", horz="D10@250") for i in range(1, 4)])
    slabs = _full("slab", [dict(name=f"S{i}", t="150", x_te="D10@200", y_bm="D10@300") for i in range(1, 4)])
    with tempfile.TemporaryDirectory() as d:
        for t, r in (("wall", walls), ("slab", slabs)):
            p = os.path.join(d, t + ".dxf")
            export_dxf(p, t, r, log=lambda *a: None)
            res, _, _ = import_dxf(p, t, log=lambda *a: None)
            assert [x["name"] for x in res[t]] == [x["name"] for x in r], res


def test_excel_txt_roundtrip():
    P = M.Project()
    P.rows["beam"] = _full("beam", BEAMS)
    P.rows["slab"] = _full("slab", [dict(name="S1", t="150", kind="2방향", x_te="D10@200")])
    with tempfile.TemporaryDirectory() as d:
        for f, fn in (("p.xlsx", TI.export_excel), ("p.txt", TI.export_txt)):
            p = os.path.join(d, f)
            fn(p, P)
            own = TI.own_format(TI.read_grids(p))
            _cmp("beam", P.rows["beam"], own["beam"])
            assert own["slab"][0]["x_te"] == "D10@200"


def test_midas_long():
    txt = ("  MEMB   SECT   Bc     Hc    POS     TOP REBAR    BOT REBAR    STIRRUPS\n"
           "  101    2G1    400    700   I       4-D22        3-D22        2-D10 @150\n"
           "  101    2G1    400    700   MID     3-D22        4-D22        2-D10 @200\n"
           "  101    2G1    400    700   J       4-D22        3-D22        2-D10 @150\n"
           "  102    2G2    350    600   I       3-D19        3-D19        2-D10 @200\n")
    g = TI.split_text(txt)
    h, hdr, mp, lf = TI.detect_header(g, "beam")
    assert lf and mp["name"] == 1
    rows = TI.apply_mapping(g, h, mp, "beam", lf)
    assert rows[0]["kind"] == "양단/중앙" and rows[0]["m_bot"] == "4-D22" and rows[0]["e_stir"] == "2-D10@150"
    assert rows[1]["kind"] == "전단면"


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("OK", k)
