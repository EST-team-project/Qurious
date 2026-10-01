"""TC-CT — 받은 시세 파일 검사(contrib)(`collector/intake.py`) · 가짜 파일로 판정 보기.

설계서 8절의 가짜 6종(설계서는 이 묶음을 TC-IN 이라 불렀지만 그 이름은 기능 설계서가 먼저 「지표 정의」 묶음에 붙였다 — 겹치지 않게 TC-CT)(정상 · 수정주가 · 하루 밀림 · 천 원 단위 · 중복 · 값 규칙 위반)에, 2026-10-01 실측으로
더한 경우 — 야후 ``Close``(분할 비율로 고친 값) · yfinance 가 기본으로 저장하는 세 줄 머리 CSV · 값까지 같은 중복 ·
포털식 정지일 0 · 배당까지 고친 값(``Adj Close``).

기준 DB 는 카카오 2021-04-05 ~ 04-23 (원 가격 · 기준가 계수 0.2007168 로 만든 수정 가격 · 04-15 분할)로 만든다 —
개념 학습 1.4 장 예제와 같은 자료다. 네트워크 · 실제 수집 DB 는 쓰지 않는다.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from collector import intake
from collector.db import SCHEMA

ROWS = [  # 기준일 · 시가 · 고가 · 저가 · 종가 · 거래량 (원자료 — 정지 사흘은 시가 · 고가 · 저가 0)
    ("20210405", 503000, 505000, 500000, 502000, 310400), ("20210406", 506000, 545000, 505000, 544000, 1724958),
    ("20210407", 544000, 544000, 526000, 542000, 820896), ("20210408", 539000, 561000, 534000, 548000, 912514),
    ("20210409", 554000, 561000, 551000, 558000, 788839), ("20210412", 0, 0, 0, 558000, 0),
    ("20210413", 0, 0, 0, 558000, 0), ("20210414", 0, 0, 0, 558000, 0),
    ("20210415", 120500, 132500, 118000, 120500, 17115015), ("20210416", 115500, 120500, 115500, 119000, 13709555),
    ("20210419", 120000, 122000, 117500, 119000, 5441693), ("20210420", 119000, 121000, 118000, 119500, 2952174),
    ("20210421", 119500, 119500, 117000, 118000, 4461636), ("20210422", 118000, 119500, 117500, 117500, 2279180),
    ("20210423", 116500, 118500, 114500, 117500, 2473720),
]
FACTOR = 112000 / 558000
SPLIT = "20210415"


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "ref.sqlite3")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    for d, o, h, l, cl, v in ROWS:
        c.execute("INSERT INTO price_daily (bas_dt,srtn_cd,mrkt_ctg,clpr,mkp,hipr,lopr,trqu,halted) "
                  "VALUES (?,?,?,?,?,?,?,?,?)", (d, "035720", "KOSPI", cl, o, h, l, v, int(o == 0)))
        f = FACTOR if d < SPLIT else 1.0
        c.execute("INSERT INTO price_adjusted VALUES (?,?,?,?,?,?,?)",
                  (d, "035720", cl * f, (o * f) or None, (h * f) or None, (l * f) or None, f))
    c.execute("INSERT INTO corporate_action (bas_dt,srtn_cd,itms_nm,prev_clpr,base_price,factor,kind) "
              "VALUES (?,?,?,?,?,?,?)", (SPLIT, "035720", "카카오", 558000, 112000, FACTOR, "split"))
    c.commit()
    return c


def _iso(d):
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def _csv(tmp_path, name, rows, header="날짜,시가,고가,저가,종가,거래량"):
    p = tmp_path / name
    p.write_text(header + "\n" + "\n".join(",".join(str(x) for x in r) for r in rows) + "\n", encoding="utf-8")
    return p


def _flat(rows):
    """정지일 0 을 평평한 봉으로 — 대부분의 출처(야후 등)가 주는 모양."""
    return [(d, o or c, h or c, l or c, c, v) for d, o, h, l, c, v in rows]


def _run(conn, tmp_path, path, **kw):
    return intake.run(path, "janghwan-god", conn=conn, out_dir=tmp_path / "out", today="2026-10-01",
                      symbol=kw.pop("symbol", "035720"), **kw)


# ── 설계서의 여섯 ──────────────────────────────────────────────────────

def test_normal_raw_file_is_green_and_cleaned(conn, tmp_path):
    """TC-CT-01 · 정상(원 가격 · 한글 칸 이름 · 종목 칸 없음 → --symbol) → 🟢 · 원 가격 · 정제본과 보고서가 생긴다."""
    rep = _run(conn, tmp_path, _csv(tmp_path, "normal.csv", [(_iso(d), *r) for d, *r in _flat(ROWS)]))
    s = rep["symbols"]["035720"]
    assert rep["verdict"] == "🟢 일치" and s["price_basis"] == "raw" and s["match"]["raw"] == 1.0
    assert s["match"]["adj_base"] == round(7 / 15, 4)            # 분할 뒤 일곱 날만 두 기준이 같다
    out = tmp_path / "out" / "janghwan-god" / "2026-10-01"
    assert (out / "normal.parquet").exists() and json.loads((out / "normal.report.json").read_text(encoding="utf-8"))


def test_adjusted_file_is_green_with_adj_basis(conn, tmp_path):
    """TC-CT-02 · 수정 가격(기준가 계수) 파일 → 🟢 · 수정 방식 adj_base."""
    rows = [(_iso(d), *[round(x * (FACTOR if d < SPLIT else 1), 1) for x in (o or c, h or c, l or c, c)], v)
            for d, o, h, l, c, v in ROWS]
    rep = _run(conn, tmp_path, _csv(tmp_path, "adj.csv", rows))
    assert rep["verdict"] == "🟢 일치" and rep["symbols"]["035720"]["price_basis"] == "adj_base"


def test_one_day_shift_is_red_with_hint(conn, tmp_path):
    """TC-CT-03 · 하루 밀림(날짜가 거래일 한 칸 앞당겨짐) → 🔴 · 단서 「한 칸 뒤로 옮기면 100%」 · 정제본 없음.
    정지 사흘의 같은 종가 때문에 그대로도 36% 가 맞는다 — 일치율만 보면 놓친다."""
    flat = _flat(ROWS)
    rows = [(_iso(flat[i - 1][0]), *flat[i][1:]) for i in range(1, len(flat))]
    rep = _run(conn, tmp_path, _csv(tmp_path, "shift.csv", rows))
    s = rep["symbols"]["035720"]
    assert rep["verdict"] == "🔴 기준과 다름" and rep["output"] is None
    assert s["match"]["raw"] == round(5 / 14, 4)
    assert any("한 칸 뒤" in h and "100%" in h for h in s["hints"])


def test_thousand_won_unit_is_red_with_hint(conn, tmp_path):
    """TC-CT-04 · 천 원 단위 → 🔴 · 단서 「천 원 단위로 보인다(맞춰 보면 100%)」."""
    rows = [(_iso(d), *[x / 1000 for x in (o, h, l, c)], v) for d, o, h, l, c, v in _flat(ROWS)]
    s = _run(conn, tmp_path, _csv(tmp_path, "unit.csv", rows))["symbols"]["035720"]
    assert s["verdict"] == "🔴 기준과 다름" and any("천 원 단위" in h and "100%" in h for h in s["hints"])


def test_conflicting_duplicate_is_rule_violation(conn, tmp_path):
    """TC-CT-05 · 같은 날 값이 다른 두 줄 → 🔴 규칙 위반(어느 쪽이 맞는지 모른다)."""
    rows = [(_iso(d), *r) for d, *r in _flat(ROWS)] + [("2021-04-14", 560000, 561000, 556000, 559000, 1000)]
    rep = _run(conn, tmp_path, _csv(tmp_path, "dup.csv", rows))
    assert rep["verdict"] == "🔴 규칙 위반" and rep["rule_problems"] == {"duplicate_key": 2}


def test_value_rule_violation(conn, tmp_path):
    """TC-CT-06 · 고가 < 종가 · 거래량 음수 → 🔴 규칙 위반 · 정제본 없음."""
    rows = [(_iso(d), *r) for d, *r in _flat(ROWS)]
    rows[1] = ("2021-04-06", 506000, 540000, 505000, 544000, 1724958)
    rows[10] = ("2021-04-19", 120000, 122000, 117500, 119000, -5)
    rep = _run(conn, tmp_path, _csv(tmp_path, "broken.csv", rows))
    assert rep["verdict"] == "🔴 규칙 위반" and rep["output"] is None
    assert rep["rule_problems"] == {"ohlc_order": 1, "volume_negative": 1}


# ── 실측으로 더한 경우 ─────────────────────────────────────────────────

def test_split_ratio_file_is_yellow_adj_split(conn, tmp_path):
    """TC-CT-07 · 분할 비율(1/5)로 고친 값(야후 Close) → 원 · 수정 둘 다 47% 지만 🟡 수정 방식만 다름 · adj_split."""
    rows = [(_iso(d), *[x / 5 if d < SPLIT else x for x in (o, h, l, c)], v) for d, o, h, l, c, v in _flat(ROWS)]
    s = _run(conn, tmp_path, _csv(tmp_path, "ratio.csv", rows))["symbols"]["035720"]
    assert s["verdict"] == "🟡 수정 방식만 다름" and s["price_basis"] == "adj_split"
    assert any("0.996429" in h for h in s["hints"])            # 111,600 ÷ 112,000


def test_yfinance_three_line_header_csv(conn, tmp_path):
    """TC-CT-08 · yfinance 기본 저장 모양(머리 「Price / Ticker / Date」 세 줄)을 읽고, Ticker 줄에서 종목을 얻는다."""
    p = tmp_path / "yf.csv"
    lines = ["Price,Close,High,Low,Open,Volume", "Ticker,035720.KS,035720.KS,035720.KS,035720.KS,035720.KS", "Date,,,,,"]
    for d, o, h, l, c, v in _flat(ROWS):
        f = 0.2 if d < SPLIT else 1
        lines.append(f"{_iso(d)},{c * f},{h * f},{l * f},{o * f},{v}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rep = intake.run(p, "janghwan-god", conn=conn, out_dir=tmp_path / "out", today="2026-10-01")
    assert list(rep["symbols"]) == ["035720"] and rep["symbols"]["035720"]["price_basis"] == "adj_split"


def test_exact_duplicates_and_portal_zeros_are_cleaned_not_failed(conn, tmp_path):
    """TC-CT-09 · 값까지 같은 중복 줄 · 포털식 정지일(시가 0)은 위반이 아니다 — 정제에서 하나로 · 평평한 봉으로."""
    rows = [(_iso(d), *r) for d, *r in ROWS] + [(_iso(ROWS[0][0]), *ROWS[0][1:])]
    rep = _run(conn, tmp_path, _csv(tmp_path, "zeros.csv", rows))
    assert rep["verdict"] == "🟢 일치" and rep["rule_problems"] == {}
    assert any("값까지 같은 중복 1줄" in x for x in rep["cleaning"])
    assert any("시가 0 인 날 3줄" in x for x in rep["cleaning"]) and rep["output_rows"] == 15


def test_dividend_adjusted_drift_hint(tmp_path):
    """TC-CT-10 · 배당까지 고친 값(비율이 과거로 갈수록 조금씩 작아짐) → 🟡 수정 방식만 다름 · adj_total.
    실제 사례: FinanceDataReader 의 KODEX 200(069500) 2025-01-02 ~ 2026-09-30 — 비율 0.9706 → 1(분배금)."""
    c = sqlite3.connect(tmp_path / "r.sqlite3")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    days = [f"202509{d:02d}" for d in range(1, 31) if __import__("datetime").date(2025, 9, d).weekday() < 5]
    for i, d in enumerate(days):
        c.execute("INSERT INTO price_daily (bas_dt,srtn_cd,mrkt_ctg,clpr,mkp,hipr,lopr,trqu) VALUES (?,?,?,?,?,?,?,?)",
                  (d, "005930", "KOSPI", 80000 + i * 100, 80000, 90000, 70000, 1))
    c.commit()
    rows = []
    for i, d in enumerate(days):
        k = 0.98 if i < 8 else (0.99 if i < 16 else 1.0)         # 배당락 두 번
        cl = (80000 + i * 100) * k
        rows.append((_iso(d), cl, cl, cl, cl, 1))
    s = intake.run(_csv(tmp_path, "adjclose.csv", rows), "janghwan-god", conn=c, symbol="005930",
                   out_dir=tmp_path / "out", today="2026-10-01")["symbols"]["005930"]
    assert s["verdict"] == "🟡 수정 방식만 다름" and s["price_basis"] == "adj_total"
    assert any("배당 · 분배금까지 고친 값" in h for h in s["hints"])


def test_contributor_id_is_validated(conn, tmp_path):
    """TC-CT-11 · 출력 폴더 이름이 되는 기여자 아이디는 깃허브 아이디 모양만 받는다(경로 조작 방지)."""
    p = _csv(tmp_path, "x.csv", [(_iso(d), *r) for d, *r in _flat(ROWS)])
    with pytest.raises(ValueError):
        intake.run(p, "../etc", conn=conn, symbol="035720", out_dir=tmp_path / "out")


def test_report_lists_mismatch_examples(conn, tmp_path):
    """TC-CT-12 · 보고서는 일치율과 함께 최대 차이 · 어긋난 날 예시를 싣는다(설계서 표 8) — 판정이 무엇이든 어느 날이
    달랐는지 보인다. 실제 사례: 야후 삼성전자 2025-10-02 종가 89,750 · 원자료 89,000(423일 중 4일)."""
    rows = [(_iso(d), *r) for d, *r in _flat(ROWS)]
    rows[4] = ("2021-04-09", 554000, 561000, 551000, 559000, 788839)        # 하루만 1,000원 다르게
    s = _run(conn, tmp_path, _csv(tmp_path, "one.csv", rows))["symbols"]["035720"]
    assert s["match"]["raw"] == round(14 / 15, 4) and s["verdict"] == "🔴 기준과 다름"   # 93.3% < 95%
    assert s["examples"] == [{"date": "2021-04-09", "received": 559000.0, "raw": 558000.0, "adj_base": 112000.0}]
    assert s["max_rel_diff"] == round(1000 / 558000, 6)
