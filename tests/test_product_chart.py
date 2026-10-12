"""TC-PCH — 상품 상세 창(app/services/product_chart.py · GET /api/products/etfs/{code}/chart) · 2026-10-12

무엇을 지키나
- 머리 숫자는 목록 줄과 **같은 값**이다 — 1년 창 이음의 끝 값 · 최대 낙폭이 목록 1년 수익률 · 최대 낙폭과 같다(SSoT).
- 하루 규칙은 목록과 같다(`chain_return` — 종가 ÷ (종가 − 전일 대비)). 전일 대비가 많이 비면 이음 값 · 낙폭은 빈칸이고
  가격으로 메우지 않는다(말없는 fallback 금지).
- 분배락 근사 — 기준가가 직전 종가보다 낮은 날만 분배로 센다. 기준가가 3원 높은 날(시세 자료의 꼴)은 세지 않고,
  10% 를 넘는 차이(분할 등)는 분배가 아닌 「다른 조정」 이다.
- 「왜 n배가 아닌가」 세 값: 단순 계산 = 배수 × 지수 수익률 · 날마다 다시 맞춘 값 = Π(1 + 배수 × 지수 하루 수익률) ·
  실제 = 분배 되돌린 이음. 기초지수가 같은 날 움직이지 않거나(해외 · 하루 늦음) 이름이 바뀌면 세 값을 내지 않고 까닭을 낸다.
- 문장: 부호는 낱말(「올랐습니다 · 내렸습니다」) · 문장의 숫자 = 요약 칸 숫자 · 단순 계산이 −100% 아래면 「나올 수 없다」 ·
  좋은 결과만 보이지 않게 늘 반대 예 하나 · 권유 낱말 없음 · 캡션에 기간 · 세전 · 과거 수익률 고지.
- 파생형 고정 띠와 요건 한 줄은 요건 상수표 한 곳에서 온다.
- 기간 칩은 그 종목이 창 첫날 전부터 있었을 때만 열린다(우리 자료가 짧으면 그 까닭).
- 수집 DB 는 `mode=ro` 로만 열고, 한 종목은 색인(`ix_etf_srtn`)으로 읽는다.
"""
from __future__ import annotations

import math
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import products as pr
from app.services import etp_requirements as etp
from app.services import product_chart as pc
from app.services import product_etfs as pe
from collector.db import SCHEMA  # 수집기의 실제 스키마

LAST = date(2026, 10, 7)
N_DAYS = 800                 # 평일 800일 ≈ 3.07년 — 3년 창이 열린다
DIST_EVERY = 63              # 분배락 — 63 거래일마다
DIST_AMT = 120               # 1좌당 분배금(원)
QUIRK_EVERY = 50             # 기준가가 직전 종가보다 3원 높은 날(분배 아님)
SPLIT_AT = 600               # 이날 2:1 분할(기준가 · 종가가 반으로) — 「다른 조정」


def _weekdays(n: int, end: date) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


DAYS = _weekdays(N_DAYS, LAST)


def _idx_ret(t: int) -> float:
    """기초지수 하루 수익률 — 오르는 흐름(하루 +0.2%) 위에 오르내림(±1.5%)."""
    return 0.002 + 0.015 * math.sin(0.9 * t)


def _idx_ret_flat(t: int) -> float:
    """오르내림만 있는 지수(흐름 없음 · ±2%) — 날마다 다시 맞추면 단순 계산보다 낮아지는 쪽."""
    return 0.02 * math.sin(0.9 * t)


def _path(ret) -> list[float]:
    out = [100.0]
    for t in range(1, N_DAYS):
        out.append(out[-1] * (1.0 + ret(t)))
    return out


IDX = _path(_idx_ret)
IDX_FLAT = _path(_idx_ret_flat)


def _bas(d: date) -> str:
    return d.strftime("%Y%m%d")


def _insert(conn, d, code, name, idx_name, close, vs, idx_close=None, nav=None):
    conn.execute(
        "INSERT INTO etf_daily(bas_dt, srtn_cd, itms_nm, clpr, vs, nav, mkp, hipr, lopr, trqu, tr_prc, bss_idx_nm, "
        "bss_idx_clpr, npt_tot_amt, halted) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
        (_bas(d), code, name, close, vs, nav if nav is not None else float(close), close, close, close, 1000, 1_000_000,
         idx_name, idx_close, 1_000_000_000),
    )


def _geared(m: int, lag: int = 0, start: int = 0, ret=_idx_ret) -> list[int]:
    """배수 m 으로 날마다 다시 맞춘 값(1,000,000 에서) — lag=1 이면 하루 늦은 지수를 따른다(해외 지수 꼴)."""
    v, out = 1_000_000.0, []
    for t in range(start, N_DAYS):
        if t > start:
            k = t - lag
            v *= 1.0 + m * (ret(k) if k >= 1 else 0.0)
        out.append(round(v))
    return out


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    # 1) KODEX 200 — 지수를 그대로 따르고, 63일마다 분배락 · 50일마다 기준가 +3원 꼴 · 600일째 2:1 분할
    prev = None
    for t, d in enumerate(DAYS):
        close = round(IDX[t] * (50 if t >= SPLIT_AT else 100))
        base = close if prev is None else prev
        if t == SPLIT_AT:                     # 분할을 먼저 — 600 은 50 의 배수라 뒤 갈래에 먹히지 않게
            base = prev // 2
        elif t > 0 and t % DIST_EVERY == 0:
            base = prev - DIST_AMT
        elif t > 0 and t % QUIRK_EVERY == 0:
            base = prev + 3
        _insert(conn, d, "069500", "KODEX 200", "코스피 200", close, close - base, idx_close=IDX[t] * 3)
        prev = close
    # 2) 같은 날 지수를 따르는 2배 · −2배 · 해외(하루 늦음) 2배 · 기초지수 이름이 바뀌는 2배
    for code, name, idx_name, m, lag in (
        ("122630", "KODEX 레버리지", "코스피 200", 2, 0),
        ("252670", "KODEX 200선물인버스2X", "코스피 200 선물지수", -2, 0),
        ("418660", "TIGER 미국나스닥100레버리지(합성)", "NASDAQ 100", 2, 1),
        ("0099L0", "KODEX 가짜지수레버리지", None, 2, 0),
    ):
        prices = _geared(m, lag)
        for t, d in enumerate(DAYS):
            nm = idx_name or ("가짜지수 TR" if t < N_DAYS - 120 else "가짜지수")
            vs = 0 if t == 0 else prices[t] - prices[t - 1]
            _insert(conn, d, code, name, nm, prices[t], vs, idx_close=IDX[t] * 7)
    # 3) 새 상장(100 거래일) · 전일 대비가 빈 옛 자료 · 1년 창 안에서 −20% 뒤 회복
    for t, d in enumerate(DAYS[-100:]):
        _insert(conn, d, "0000N0", "KODEX 새상장", "코스피 200", 10_000 + t, 0 if t == 0 else 1, idx_close=300.0)
    flat = _geared(2, ret=_idx_ret_flat)
    for t, d in enumerate(DAYS):
        _insert(conn, d, "0098C0", "KODEX 횡보지수레버리지", "횡보지수", flat[t], 0 if t == 0 else flat[t] - flat[t - 1],
                idx_close=IDX_FLAT[t])
    for t, d in enumerate(DAYS):
        _insert(conn, d, "777770", "옛 자료 채권 ETF", "KAP 국고채 지수", 10_000 + t, None, idx_close=100.0)
    year_i0 = next(i for i, d in enumerate(DAYS) if d >= LAST - timedelta(days=365))
    prev = None
    for t, d in enumerate(DAYS):
        # 비율이 이진수로 정확히 떨어지는 값(2 의 거듭제곱) — 이어 곱한 값이 고점과 「정확히 같은」 날이 생기게.
        # 10,000 → 8,000 처럼 끊으면 곱셈 오차로 1.0000000000000002 가 되어 회복 판정 >= 와 > 를 가르지 못했다(깨 보기 M18)
        k = t - year_i0
        if k < 20:
            close = 8_192
        elif k < 40:
            close = 4_096                            # 하루에 −50%
        elif k < 60:
            close = 8_192                            # 고점과 같은 값으로 되돌아옴 — 이날이 회복
        else:
            close = 16_384
        _insert(conn, d, "091170", "KODEX 자동차", "KRX 자동차", close, 0 if prev is None else close - prev,
                idx_close=500.0)
        prev = close
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "market.sqlite3"
    _make_db(p)
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(p))
    pe.clear_cache()
    pc.clear_cache()
    yield p
    pe.clear_cache()
    pc.clear_cache()


def _row(code: str) -> dict:
    return next(x for x in pe.list_etfs(limit=200)["items"] if x["code"] == code)


def _year_i0() -> int:
    return next(i for i, d in enumerate(DAYS) if d >= LAST - timedelta(days=365))


def _explain(r: dict, chip: str) -> dict:
    return next(e for e in r["explain"] if e["chip"] == chip)


def _text(e: dict) -> str:
    """한 줄 요약 + 근거 줄 — 화면이 보이는 글 전부."""
    return " ".join([e["sentence"], *e["points"]])


# ── 머리 숫자 = 목록 줄 (SSoT) ──────────────────────────────────────────────

def test_head_numbers_equal_list_row(db):
    for code in ("069500", "122630", "252670", "091170"):
        r = pc.chart(code, "1y")
        row = _row(code)
        assert r["status"] == "ok" and r["item"] == row
        assert r["stats"]["return"]["tr_pct"] == pytest.approx(row["return_1y_pct"], abs=1e-9), code
        assert r["stats"]["drawdown"]["depth_pct"] == pytest.approx(row["mdd_1y_pct"], abs=1e-9), code
        assert r["stats"]["return"]["px_pct"] == pytest.approx(row["price_return_1y_pct"], abs=1e-9), code
        assert r["stats"]["volatility"]["annual_pct"] == pytest.approx(row["vol_1y_pct"], abs=1e-9), code


def test_chain_rule_is_the_list_rule():
    assert pe.chain_return(10_100, 100) == pytest.approx(0.01)
    assert pe.chain_return(10_000, -120) == pytest.approx(10_000 / 10_120 - 1)
    assert pe.chain_return(10_000, None) is None             # 기준가를 못 만들면 빈 날
    assert pe.chain_return(10_000, 10_000) is None           # 기준가 0 이하 — 나누지 않는다


def test_series_columns_same_length(db):
    r = pc.chart("069500", "1y")
    s = r["series"]
    n = r["window"]["trading_days"]
    assert n == len(DAYS) - _year_i0()
    assert all(len(v) == n for v in s.values())
    assert s["tr"][0] == 100.0 and s["px"][0] == 100.0 and s["drawdown_pct"][0] == 0.0
    assert "lev_naive" not in s                                # 1배 상품에는 배수 계열이 없다
    assert r["stats"]["leverage"] is None and r["band"] is None and r["default_chip"] == "return"


# ── 분배 · 다른 조정 ────────────────────────────────────────────────────────

def test_distributions_detected_quirk_ignored(db):
    r = pc.chart("069500", "3y")
    i0 = next(i for i, d in enumerate(DAYS) if d >= LAST - timedelta(days=1095))
    want = [DAYS[t].isoformat() for t in range(i0 + 1, N_DAYS) if t % DIST_EVERY == 0]
    got = r["events"]["distributions"]
    assert [e["date"] for e in got] == want                    # 기준가 +3원인 날은 분배가 아니다
    assert all(e["amount"] == DIST_AMT for e in got)
    assert r["stats"]["return"]["dist_count"] == len(want)
    assert r["stats"]["return"]["dist_sum"] == DIST_AMT * len(want)
    quirk = [DAYS[t].isoformat() for t in range(i0 + 1, N_DAYS)
             if t % QUIRK_EVERY == 0 and t % DIST_EVERY and t != SPLIT_AT]
    assert quirk and not set(quirk) & {e["date"] for e in got}


def test_big_gap_is_adjustment_not_distribution(db):
    r = pc.chart("069500", "3y")
    adj = r["events"]["adjustments"]
    assert [e["date"] for e in adj] == [DAYS[SPLIT_AT].isoformat()]
    assert adj[0]["pct"] > pc.DIST_MAX_PCT
    assert DAYS[SPLIT_AT].isoformat() not in {e["date"] for e in r["events"]["distributions"]}


# ── 왜 n배가 아닌가 ─────────────────────────────────────────────────────────

def _expected_three(m: int) -> tuple[float, float, float]:
    i0 = _year_i0()
    idx_pct = (IDX[-1] / IDX[i0] - 1) * 100
    reset = 1.0
    for t in range(i0 + 1, N_DAYS):
        reset *= 1 + m * (IDX[t] / IDX[t - 1] - 1)
    return idx_pct, m * idx_pct, (reset - 1) * 100


def test_leverage_three_values(db):
    r = pc.chart("122630", "1y")
    lv = r["stats"]["leverage"]
    assert lv["comparable"] is True and lv["reason"] is None and lv["fit_corr"] > 0.99
    idx_pct, naive, reset = _expected_three(2)
    assert lv["index_pct"] == pytest.approx(idx_pct, abs=1e-9)
    assert lv["naive_pct"] == pytest.approx(naive, abs=1e-9)                      # 단순 계산 = 배수 × 지수 수익률
    assert lv["reset_pct"] == pytest.approx(reset, abs=1e-9)                      # 날마다 다시 맞춘 값
    assert lv["actual_pct"] == pytest.approx(reset, abs=0.05)                     # 고정물은 보수가 없다 — 정수 종가 반올림만
    assert lv["path_effect_pctp"] == pytest.approx(lv["reset_pct"] - lv["naive_pct"], abs=1e-9)
    assert lv["cost_effect_pctp"] == pytest.approx(lv["actual_pct"] - lv["reset_pct"], abs=1e-9)
    s = r["series"]
    assert s["lev_naive"][0] == 100.0 and s["lev_reset"][0] == 100.0
    assert s["lev_reset"][-1] == pytest.approx(100 + reset, abs=1e-3)
    assert r["default_chip"] == "leverage"


def test_inverse_naive_below_minus_100_says_impossible(db):
    r = pc.chart("252670", "1y")
    lv = r["stats"]["leverage"]
    assert lv["comparable"] is True and lv["fit_corr"] < -0.99
    assert lv["naive_pct"] < -100                               # 지수가 50% 넘게 올라 −2배 단순 계산은 −100% 아래
    sent = _text(_explain(r, "leverage"))
    assert "원금보다 더 잃는 값이라 실제로는 나올 수 없습니다" in sent
    assert lv["reset_pct"] > -100 and lv["actual_pct"] > -100   # 날마다 다시 맞추면 −100% 아래로 가지 않는다


def test_overseas_lagged_index_not_compared(db):
    r = pc.chart("418660", "1y")
    lv = r["stats"]["leverage"]
    assert lv["comparable"] is False and "같은 날 움직임이 맞지 않습니다" in lv["reason"]
    assert "index_pct" not in lv and "lev_naive" not in r["series"]          # 숫자를 만들어 내지 않는다
    assert r["default_chip"] == "return"                                     # 빈 비교로 열지 않는다
    e = _explain(r, "leverage")
    assert "세 값" in e["sentence"] and "내지 않습니다" in e["sentence"] and lv["reason"] in _text(e)


def test_index_name_change_not_compared(db):
    lv = pc.chart("0099L0", "1y")["stats"]["leverage"]
    assert lv["comparable"] is False and "기초지수가 바뀌었습니다(가짜지수 TR → 가짜지수)" in lv["reason"]
    assert pc.chart("0099L0", "1m")["stats"]["leverage"]["comparable"] is True   # 바뀐 뒤 구간만 보면 견줄 수 있다


def test_opposite_example_always_present(db):
    seen = set()
    for code in ("122630", "252670", "0098C0"):
        sent = _text(_explain(pc.chart(code, "1y"), "leverage"))
        lv = pc.chart(code, "1y")["stats"]["leverage"]
        p = round(lv["path_effect_pctp"], 1)
        if p > 0:
            assert "오르내림이 잦으면 반대가 됩니다" in sent and "하루 20% 내렸다가" in sent, code
        elif p < 0:
            assert "반대로 높아질 수 있습니다" in sent and "이틀 연속 10% 오르면" in sent, code
        else:
            assert "하루 20% 내렸다가" in sent and "이틀 연속 10% 오르면" in sent, code
        seen.add((p > 0) - (p < 0))
    assert {1, -1} <= seen                     # 높아진 기간 · 낮아진 기간 두 갈래를 모두 본다


def test_example_numbers():
    assert pc._example(2, (-0.2, 0.2)) == pytest.approx((-4.0, -8.0, -16.0))
    assert pc._example(2, (0.1, 0.1)) == pytest.approx((21.0, 42.0, 44.0))
    assert pc._example(-1, (-0.2, 0.2)) == pytest.approx((-4.0, 4.0, -4.0))
    assert pc._example(-2, (0.1, 0.1)) == pytest.approx((21.0, -42.0, -36.0))


# ── 문장 ────────────────────────────────────────────────────────────────────

SIGNED_PCT = re.compile(r"[−+-]\s?\d[\d,]*(\.\d+)?\s?%")


def test_sentences_use_words_not_signs(db):
    for code in ("069500", "122630", "252670", "418660", "091170", "777770"):
        for e in pc.chart(code, "1y")["explain"]:
            for line in [e["sentence"], *e["points"]]:
                assert not SIGNED_PCT.search(line), (code, e["chip"], line)


def test_summary_is_short_and_points_carry_the_why(db):
    for code in ("069500", "122630", "252670", "418660", "091170"):
        for e in pc.chart(code, "1y")["explain"]:
            assert isinstance(e["points"], list)
            assert len(e["sentence"]) <= 140, (code, e["chip"], len(e["sentence"]))   # 그림 위 한 줄 — 길면 나눈다
            assert all(p.endswith(".") for p in e["points"]), (code, e["chip"])
    lev = _explain(pc.chart("122630", "1y"), "leverage")
    assert any("날마다 2배로 다시 맞춘 값은" in p for p in lev["points"])            # 까닭은 근거 줄에


def test_direction_words_follow_sign(db):
    up = pc.chart("122630", "1y")
    lv = up["stats"]["leverage"]
    assert lv["index_pct"] > 0 and lv["actual_pct"] > 0
    sent = _explain(up, "leverage")["sentence"]
    assert f"기초지수는 {abs(round(lv['index_pct'], 1)):,.1f}% 올랐습니다" in sent
    assert f"실제 ETF 는 {abs(round(lv['actual_pct'], 1)):,.1f}% 올랐습니다" in sent
    down = pc.chart("252670", "1y")
    lv = down["stats"]["leverage"]
    assert lv["actual_pct"] < 0
    sent = _explain(down, "leverage")["sentence"]
    assert f"{abs(round(lv['naive_pct'], 1)):,.1f}% 내린다고 생각하기 쉽지만" in sent
    assert f"실제 ETF 는 {abs(round(lv['actual_pct'], 1)):,.1f}% 내렸습니다" in sent


def test_sentence_numbers_match_stats(db):
    r = pc.chart("069500", "1y")
    sr = r["stats"]["return"]
    sent = _text(_explain(r, "return"))
    assert f"{int(round(sr['tr_value'])):,}원" in sent and f"{int(round(sr['px_value'])):,}원" in sent
    assert f"{sr['dist_count']}번" in sent and f"{sr['dist_sum']:,}원" in sent
    r = pc.chart("122630", "1y")
    lv = r["stats"]["leverage"]
    sent = _text(_explain(r, "leverage"))
    for k in ("index_pct", "naive_pct", "reset_pct", "actual_pct"):
        assert f"{abs(round(lv[k], 1)):,.1f}%" in sent, k
    for k in ("path_effect_pctp", "cost_effect_pctp"):
        if round(lv[k], 1) == 0:                                          # 0 이면 숫자 대신 「거의 없었습니다」
            assert "거의 없었습니다" in sent, k
        else:
            assert f"{abs(round(lv[k], 1)):,.1f}%p" in sent, k


def test_drawdown_peak_trough_recovery(db):
    r = pc.chart("091170", "1y")
    dd = r["stats"]["drawdown"]
    i0 = _year_i0()
    assert dd["depth_pct"] == -50.0
    assert dd["peak_date"] == DAYS[i0].isoformat()                    # 처음 고점(그 뒤 같은 값이면 옮기지 않음)
    assert dd["trough_date"] == DAYS[i0 + 20].isoformat()
    assert dd["recovered"] is True and dd["recovered_date"] == DAYS[i0 + 40].isoformat()   # 같은 값으로 돌아온 날이 회복
    assert dd["days_underwater"] == 40
    assert dd["need_to_recover_pct"] == pytest.approx(100.0)          # −50% 를 메우려면 +100%
    sent = _text(_explain(r, "drawdown"))
    assert "50.0% 줄었습니다" in sent and "100만 원 → 500,000원" in sent and "100.0% 올라야" in sent
    assert "되찾았습니다" in sent


def test_no_drawdown_sentence(db):
    r = pc.chart("0000N0", "1m")                                        # 오르기만 했다
    assert r["stats"]["drawdown"]["depth_pct"] == 0.0
    assert "내려간 적이 거의 없습니다" in _explain(r, "drawdown")["sentence"]


def test_missing_vs_is_blank_not_price(db):
    r = pc.chart("777770", "1y")
    st = r["stats"]
    assert st["return"]["tr_pct"] is None and st["drawdown"] is None
    assert st["return"]["px_pct"] is not None and st["return"]["px_pct"] > 0
    assert all(v is None for v in r["series"]["tr"]) and r["series"]["px"][-1] > 100
    assert "전일 대비 칸이 빈 날이 많아" in _explain(r, "return")["sentence"]
    assert "가장 크게 내린 폭을 내지 않습니다" in _explain(r, "drawdown")["sentence"]


def test_no_banned_words(db):
    banned = ("추천", "최적", "유망", "베스트", "안전한", "매수 신호", "매도 신호", "사세요", "유리합니다")
    for code in ("069500", "122630", "252670", "418660"):
        r = pc.chart(code, "1y")
        texts = [r["caption"], *r["notes"], r["band"] or "", r["requirement_note"] or ""]
        texts += [e[k] for e in r["explain"] for k in ("title", "sentence", "how", "limits")]
        texts += [p for e in r["explain"] for p in e["points"]]
        for text in texts:
            for w in banned:
                assert w not in text, (code, w, text)


def test_caption_and_notes(db):
    r = pc.chart("069500", "1y")
    cap = r["caption"]
    w = r["window"]
    assert f"기간 {w['from']} ~ {w['to']}(거래일 {w['trading_days']}일)" in cap
    assert "세전" in cap and "과거 수익률은 미래 수익을 보장하지 않습니다" in cap and pe.SOURCE["name"] in cap
    notes = " ".join(r["notes"])
    assert "공공누리 제4유형" in notes and "내려받을 수 없습니다" in notes
    assert pe.NOTE_NOT_OFFICIAL in r["notes"] and pe.NOTE_NO_TER in r["notes"]    # 목록과 같은 글


def test_band_and_requirement_from_one_table(db, monkeypatch):
    r = pc.chart("122630", "1y")
    assert r["band"] == etp.risk_note(2) and "단기 투자용" in r["band"] and "2배" in r["band"]
    assert r["requirement_note"] == etp.need("leveraged_2x") and "1,000만 원" in r["requirement_note"]
    monkeypatch.setitem(etp.REQUIREMENTS["leveraged_2x"], "deposit_krw", 20_000_000)
    pc.clear_cache()
    assert "2,000만 원" in pc.chart("122630", "1y")["requirement_note"]           # 숫자는 표 한 곳에서만
    assert pc.chart("252670", "1y")["band"] == etp.risk_note(-2)
    assert etp.notes()[0] == etp.risk_note()                                     # 목록 머리 글도 같은 함수


# ── 기간 ────────────────────────────────────────────────────────────────────

def test_periods_and_short_history(db):
    r = pc.chart("0000N0", "1y")
    assert r["status"] == "short" and "처음 거래돼" in r["reason"] and "1년이 지나지 않았습니다" in r["reason"]
    avail = {p["key"]: p["available"] for p in r["periods"]}
    assert avail == {"1m": True, "6m": False, "1y": False, "3y": False}
    assert pc.chart("0000N0", "1m")["status"] == "ok"
    assert all(p["available"] for p in pc.chart("069500", "1y")["periods"])


def test_period_reason_when_our_data_is_short():
    ps = {p["key"]: p for p in pc._periods("20261007", first="20250102", data_from="20250102")}
    assert ps["1y"]["available"] is True
    assert ps["3y"]["available"] is False and "우리 자료가 2025-01-02부터라 3년 그림은 낼 수 없습니다" in ps["3y"]["reason"]


def test_period_windows(db):
    for key, (days, label) in pc.PERIODS.items():
        r = pc.chart("069500", key)
        assert r["status"] == "ok" and r["window"]["label"] == label
        assert r["window"]["from"] >= (LAST - timedelta(days=days)).isoformat()
        assert r["window"]["to"] == LAST.isoformat()
    assert pc.PERIODS["1y"][0] == pe._YEAR_DAYS                                   # 1년은 목록과 같은 날 수


def test_bad_args():
    with pytest.raises(ValueError):
        pc.chart("abc", "1y")
    with pytest.raises(ValueError):
        pc.chart("069500", "5y")


def test_unknown_code_and_no_db(db, tmp_path, monkeypatch):
    assert pc.chart("ZZZZZZ", "1y")["status"] == "not_found"
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없음.sqlite3"))
    pe.clear_cache()
    pc.clear_cache()
    assert pc.chart("069500", "1y")["status"] == "no_data"


# ── 읽기 · 캐시 ─────────────────────────────────────────────────────────────

def test_opens_read_only(db, monkeypatch):
    seen = []
    real = sqlite3.connect

    def spy(target, *a, **k):
        seen.append(str(target))
        return real(target, *a, **k)

    monkeypatch.setattr(pe.sqlite3, "connect", spy)
    pc.chart("069500", "1y")
    assert seen and all("mode=ro" in s for s in seen)


def test_one_code_read_uses_index(db):
    conn = sqlite3.connect(db)
    plan = conn.execute("EXPLAIN QUERY PLAN " + pc.ROWS_SQL, ("069500", "20251007", "20261007")).fetchall()
    conn.close()
    assert any("USING INDEX ix_etf_srtn" in str(row) for row in plan), plan


def test_new_trading_day_moves_window(db):
    assert pc.chart("069500", "1y")["window"]["to"] == "2026-10-07"
    conn = sqlite3.connect(db)
    d = date(2026, 10, 8)
    for code in ("069500", "122630"):
        _insert(conn, d, code, "x", "코스피 200", 1, 0, idx_close=1.0)
    conn.commit()
    conn.close()
    r = pc.chart("069500", "1y")
    assert r["as_of"] == "2026-10-08" and r["window"]["to"] == "2026-10-08"     # 옛 계산을 붙들지 않는다


# ── 라우트 ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(pr.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "email": "t@t", "roles": []}
    return TestClient(app)


def test_route_ok_and_short(client):
    r = client.get("/api/products/etfs/122630/chart?period=1y")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["stats"]["leverage"]["comparable"]
    r = client.get("/api/products/etfs/069500/chart")                            # 기본 1년
    assert r.status_code == 200 and r.json()["period"] == "1y"
    r = client.get("/api/products/etfs/0000N0/chart?period=3y")
    assert r.status_code == 200 and r.json()["status"] == "short"


def test_route_rejects_bad_params(client):
    assert client.get("/api/products/etfs/abc123/chart").status_code == 422        # 소문자
    assert client.get("/api/products/etfs/12345/chart").status_code == 422         # 5자리
    assert client.get("/api/products/etfs/069500/chart?period=5y").status_code == 422
    assert client.get("/api/products/etfs/ZZZZZZ/chart").status_code == 404        # 그날 목록에 없음


def test_route_needs_login(db):
    app = FastAPI()
    app.include_router(pr.router)
    assert TestClient(app).get("/api/products/etfs/069500/chart").status_code == 401
