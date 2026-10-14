"""계절성 분석 시험 (TC-SE) — `app/services/seasonality.py` (API-SEAS-01 · 금융 필수 지식 › 계절성 · 2026-10-14).

여기서 지키는 것 —
1. 시장 지수의 항목 표는 수집기(`collector/ecos.py` INDEX_SERIES)와 같다 — 앱 이미지에 collector/ 가 없어 두 곳에 있다(SSoT 를 시험으로).
2. 달 수익률 = 그달 마지막 거래일 값 ÷ 앞달 마지막 거래일 값 − 1 · 첫 달(앞달이 없음) · 아직 끝나지 않은 달 · 앞달이 비는 달은 세지 않는다.
3. 12달 · 5요일을 한꺼번에 견주므로 p 값은 홀름 보정 — 「뚜렷한 달」 은 보정한 값으로만 가른다.
4. 산타 랠리 창 = 12월 마지막 5거래일 + 이듬해 1월 첫 2거래일(창 앞 거래일 종가 → 1월 둘째 거래일 종가) · 견줄 기준 = 아무 7거래일.
5. 응답 — 숫자 · 표 · 문장(서버 한 곳) · 기준값(alpha · 보정 방법) · 출처 · 고지 · 시장은 가격 지수뿐이라 총수익을 달라 해도 그 사실을 글로.
6. 수집 DB 는 읽기 전용(mode=ro)으로만 · 일반 사용자 답에는 표 이름 · 명령이 없고 관리자에게만 할 일.

실제 수집 DB 를 쓰지 않는다 — 임시 SQLite 를 COLLECTOR_DB_PATH 로 가리키고, 그 밖의 시험은 없는 경로를 가리킨다(autouse).
"""
from __future__ import annotations

import asyncio
import math
import sqlite3
from datetime import date, timedelta

import pytest

from app.services import seasonality as S
from collector import db as CDB
from collector import ecos as E


@pytest.fixture(autouse=True)
def _no_real_db(tmp_path, monkeypatch):
    """이 PC 의 실제 수집 DB 를 열지 않는다 — 시험마다 없는 경로가 기본(TC-FH 꼴)."""
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없는-수집DB.sqlite3"))


@pytest.fixture()
def dbfile(tmp_path, monkeypatch):
    p = tmp_path / "market.sqlite3"
    c = sqlite3.connect(p)
    c.executescript(CDB.SCHEMA)
    c.close()
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(p))
    return p


def _weekdays(start: date, end: date):
    d, out = start, []
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _fill_index(p, item: str, series):
    c = sqlite3.connect(p)
    c.executemany("INSERT INTO ecos_series (stat_code, item_code, cycle, date, value, unit, item_name, fetched_at, updated_at) "
                  "VALUES (?, ?, 'D', ?, ?, '1980.01.04=100', '', 't', 't')",
                  [(S.INDEX_STAT, item, d, v) for d, v in series])
    c.commit()
    c.close()


def _fill_stock(p, code: str, name: str, rows):
    """rows = [(YYYYMMDD, tr_index, pr_index)]"""
    c = sqlite3.connect(p)
    c.executemany("INSERT INTO price_total_return (bas_dt, srtn_cd, tr_index, tr_index_net, pr_index, div_factor) "
                  "VALUES (?, ?, ?, ?, ?, 1.0)", [(d, code, tr, tr, pr) for d, tr, pr in rows])
    c.executemany("INSERT INTO price_daily (bas_dt, srtn_cd, itms_nm, mrkt_ctg, clpr) VALUES (?, ?, ?, 'KOSPI', 1000)",
                  [(d, code, name) for d, _t, _p in rows])
    c.commit()
    c.close()


# ── 1. 항목 표 = 수집기 ─────────────────────────────────────────────────

def test_market_items_match_the_collector():
    """TC-SE-01 · 시장 지수 항목(열쇠 · 코드 · 이름) · 통계표 코드 · 출처 표시가 수집기와 같다."""
    assert [(k, c) for k, c, _n in S.MARKETS] == [(k.upper(), c) for k, c, _n, _f in E.INDEX_SERIES]
    assert S.INDEX_STAT == E.INDEX_STAT and S.ATTRIBUTION_ECOS == E.ATTRIBUTION


# ── 2. 달 수익률 ──────────────────────────────────────────────────────

def test_month_return_is_month_end_to_month_end_and_skips_first_open_and_gap_months():
    """TC-SE-02 · 달 끝 → 달 끝 · 첫 달 · 끝나지 않은 달 · 앞달이 빈 달은 None · 끝난 달은 다음 달이 되면 센다."""
    s = [("2020-01-02", 100.0), ("2020-01-31", 110.0),           # 첫 달 — 앞달이 없어 세지 않는다
         ("2020-02-03", 105.0), ("2020-02-28", 99.0),            # 2월 = 99 / 110 − 1
         ("2020-03-31", 108.9),                                   # 3월 = 108.9 / 99 − 1 = +10%
         ("2020-05-29", 120.0),                                   # 4월이 비어 5월은 세지 않는다(앞달 없음)
         ("2020-06-30", 132.0),                                   # 6월 = 132 / 120 − 1 = +10%
         ("2020-07-15", 140.0)]                                   # 7월 — 오늘이 7월이면 아직 끝나지 않았다
    m = S.monthly_matrix(s, today=date(2020, 7, 20))
    row = m["rows"][2020]
    assert row[0] is None and row[3] is None and row[4] is None and row[6] is None
    assert math.isclose(row[1], 99 / 110 - 1) and math.isclose(row[2], 0.1) and math.isclose(row[5], 0.1)
    assert m["months"] == 3 and m["first"] == "2020-02" and m["last"] == "2020-06"
    m2 = S.monthly_matrix(s, today=date(2020, 8, 1))           # 8월이 되면 7월은 끝난 달
    assert math.isclose(m2["rows"][2020][6], 140 / 132 - 1) and m2["months"] == 4 and m2["last"] == "2020-07"


# ── 3. 달 통계 · 홀름 보정 ────────────────────────────────────────────

def test_holm_adjustment_known_values_monotone_and_capped():
    """TC-SE-03 · 홀름 — 작은 p 부터 (남은 수)배 · 앞 값보다 작아지지 않게 · 1 을 넘지 않게 · None 은 그대로."""
    assert S.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert S.holm([0.5, None, 0.9]) == [pytest.approx(1.0), None, pytest.approx(1.0)]
    assert S.holm([]) == []


def _month_end_series(years, ret_of):
    """해마다 열두 달 — 달마다 마지막 평일 하나 · ret_of(year, month) 로 그달 수익률."""
    out, v = [("1999-12-31", 100.0)], 100.0
    for y in years:
        for mth in range(1, 13):
            last = date(y + (mth == 12), (mth % 12) + 1, 1) - timedelta(days=1)
            while last.weekday() > 4:
                last -= timedelta(days=1)
            v *= 1 + ret_of(y, mth)
            out.append((last.isoformat(), v))
    return out


def test_month_stats_find_a_strong_month_and_not_noise():
    """TC-SE-04 · 달 잡음 4% 위에 1월만 +6% 인 자료는 1월만 뚜렷 · 잡음만 있는 자료는 뚜렷한 달 0 · 오른 해 · 최고 · 최저.

    잡음은 고정 씨앗(random.Random)이라 해마다 같은 자료다 — 「한 달 vs 나머지 달」 의 웰치 t 검정 + 홀름 보정.
    """
    import random
    years = list(range(2000, 2030))
    rng = random.Random(20261014)
    noise_tbl = {(y, m): rng.gauss(0.0, 0.04) for y in years for m in range(1, 13)}
    strong = S.month_stats(S.monthly_matrix(
        _month_end_series(years, lambda y, m: noise_tbl[(y, m)] + (0.06 if m == 1 else 0)), today=date(2030, 2, 1))["rows"])
    jan = strong[0]
    assert jan["month"] == 1 and jan["label"] == "1월" and jan["n"] == 30
    assert jan["distinct"] is True and jan["p_adjusted"] < S.ALPHA
    assert [m["month"] for m in strong if m["distinct"]] == [1]
    assert jan["up"] + jan["down"] == 30 and jan["hit_rate"] == round(jan["up"] / 30 * 100, 1)
    assert jan["best"]["year"] in years and jan["worst"]["ret"] <= jan["median"] <= jan["best"]["ret"]
    noise = S.month_stats(S.monthly_matrix(_month_end_series(years, lambda y, m: noise_tbl[(y, m)]),
                                           today=date(2030, 2, 1))["rows"])
    assert not any(m["distinct"] for m in noise)
    assert all(m["p_adjusted"] >= m["p_value"] for m in noise if m["p_value"] is not None)


def _weekday_series(monday: float, seed: int):
    import random
    rng = random.Random(seed)
    days = _weekdays(date(2015, 1, 5), date(2019, 12, 31))
    v, s = 100.0, []
    for i, d in enumerate(days):
        if i:
            v *= 1 + (monday if d.weekday() == 0 else 0.0005) + rng.gauss(0.0, 0.01)
        s.append((d.isoformat(), v))
    return days, s


def test_weekday_stats_monday_effect_and_counts():
    """TC-SE-05 · 하루 잡음 1% 위에 월요일만 −0.3%(나머지 +0.05%) → 월요일이 뚜렷하고 보정 p 가 가장 작다 · 요일마다 관측 수.

    「한 요일 vs 나머지」 검정이라 월요일이 크게 낮으면 다른 요일의 「나머지」 평균도 끌려 내려가 그 요일이 뚜렷해 보일 수 있다
    (씨앗 일곱 중 다섯 — 2026-10-14 실측). 그래서 「월요일만」 이 아니라 「월요일이 가장 뚜렷」 을 본다 · 잡음만 있으면 0 요일.
    """
    days, s = _weekday_series(-0.003, 5)
    w = S.weekday_stats(s)
    assert [x["label"] for x in w] == ["월", "화", "수", "목", "금"]
    assert sum(x["n"] for x in w) == len(days) - 1
    assert w[0]["distinct"] is True and w[0]["p_adjusted"] == min(x["p_adjusted"] for x in w)
    assert w[0]["mean"] < 0 < w[2]["mean"]
    _days, flat = _weekday_series(0.0005, 5)                            # 잡음만 — 월요일도 다른 날과 같다
    assert not any(x["distinct"] for x in S.weekday_stats(flat))


# ── 4. 산타 랠리 창 ───────────────────────────────────────────────────

def test_santa_window_definition_and_baseline():
    """TC-SE-06 · 12월 마지막 5거래일 + 1월 첫 2거래일 — 창 앞 거래일 종가 → 1월 둘째 거래일 종가 · 끝나지 않은 해는 빼고 · 기준은 아무 7거래일."""
    days = _weekdays(date(2018, 11, 1), date(2021, 1, 5))
    s = [(d.isoformat(), 100.0 + i) for i, d in enumerate(days)]       # 하루 +1 씩
    val = dict(s)
    out = S.santa_windows(s)
    assert S.SANTA_DEC_DAYS == 5 and S.SANTA_JAN_DAYS == 2
    by_year = {r["year"]: r for r in out["years"]}
    assert set(by_year) == {2018, 2019, 2020}                           # 2020-12 → 2021-01 둘째 거래일(01-05)까지 있다
    dec18 = [d for d in days if d.year == 2018 and d.month == 12]
    jan19 = [d for d in days if d.year == 2019 and d.month == 1]
    r = by_year[2018]
    assert r["from"] == dec18[-6].isoformat() and r["to"] == jan19[1].isoformat()
    assert math.isclose(r["ret"], val[jan19[1].isoformat()] / val[dec18[-6].isoformat()] - 1)
    assert out["stats"]["n"] == 3 and out["stats"]["up"] == 3
    assert out["baseline"]["days"] == 7 and out["baseline"]["n"] == len(days) - 7
    # 1월 둘째 거래일이 아직 없으면 그 해는 세지 않는다(가짜 달력에선 2021-01-01 이 첫 거래일)
    assert {r["year"] for r in S.santa_windows([x for x in s if x[0] <= "2021-01-01"])["years"]} == {2018, 2019}


# ── 5. 응답 — 시장 · 종목 ──────────────────────────────────────────────

def _market_days(start, end):
    days = _weekdays(start, end)
    return [(d.isoformat(), 100.0 * (1.0004 ** i) * (1 + 0.03 * math.sin(i / 9))) for i, d in enumerate(days)]


def test_read_market_long_series_fields_sentences_and_attribution(dbfile):
    """TC-SE-07 · 코스피 — 가격 지수(총수익을 달라 해도 글로 알림) · 범위 · 표 · 달 · 요일 · 창 · 문장 · 기준값 · 출처 · 고지."""
    _fill_index(dbfile, "0001000", _market_days(date(1995, 1, 3), date(2026, 10, 13)))
    out = S.read_seasonality("kospi", "tr", admin=False, today=date(2026, 10, 14))
    assert out["available"] is True and out["target"] == {"kind": "market", "code": "KOSPI", "name": "코스피", "market": "KOSPI"}
    assert out["basis"] == "pr" and out["basis_note"] and out["source"] == S.ATTRIBUTION_ECOS
    assert out["span"]["first"] == "1995-02" and out["span"]["last"] == "2026-09" and out["as_of"] == "2026-10-13"
    assert len(out["by_month"]) == 12 and len(out["weekday"]) == 5 and out["matrix"][0]["year"] == 1995
    assert out["matrix"][0]["months"][0] is None and out["matrix"][-1]["months"][9] is None   # 1995-01 · 2026-10
    assert out["thresholds"] == {"alpha": S.ALPHA, "method": "holm", "short_years": S.SHORT_YEARS,
                                 "min_test_n": S.MIN_TEST_N}
    assert all(m["distinct"] is not None for m in out["by_month"])       # 31해면 열두 달 모두 판정한다
    assert out["definitions"]["santa"] and out["windows"]["santa"]["stats"]["n"] >= 30
    text = " ".join(out["sentences"])
    assert "31" in text and "홀름" in text and "산타 랠리" in text and "신호가 아닙니다" in text
    assert "표본" not in text                                            # 31년이면 「표본이 작다」 문장은 없다
    assert out["notice"] and "admin_hint" not in out


def test_read_stock_tr_vs_pr_and_short_sample_sentence(dbfile):
    """TC-SE-08 · 종목 — 총수익(tr_index) · 가격(pr_index)을 고른 대로 · 2020 년부터라 「표본이 작다」 문장 · 이름 · 시장."""
    days = _weekdays(date(2020, 1, 2), date(2026, 10, 13))
    rows, tr, pr = [], 1.0, 1.0
    for i, d in enumerate(days):
        if i:
            step = 1 + 0.0005 + 0.01 * math.sin(i / 7)
            pr *= step
            tr *= step * (1.02 if (d.month == 4 and d.day <= 7 and d.weekday() == 0) else 1.0)   # 4월 첫 월요일 배당
        rows.append((d.strftime("%Y%m%d"), tr, pr))
    _fill_stock(dbfile, "005930", "삼성전자", rows)
    t = S.read_seasonality("005930.KS", "tr", today=date(2026, 10, 14))
    p = S.read_seasonality("005930", "pr", today=date(2026, 10, 14))
    assert t["target"] == {"kind": "stock", "code": "005930", "name": "삼성전자", "market": "KOSPI"}
    assert t["basis"] == "tr" and p["basis"] == "pr" and t["basis_note"] is None
    apr_t = t["by_month"][3]["mean"]
    apr_p = p["by_month"][3]["mean"]
    assert apr_t > apr_p                                                 # 배당이 든 4월은 총수익이 크다
    assert any("표본" in x for x in t["sentences"]) and t["span"]["first"] == "2020-02"
    # 관측이 MIN_TEST_N 해보다 적은 달은 판정하지 않는다 — 뚜렷함 None · p 없음 · 그 사실을 문장으로(2026-10-14 실측: 삼성전자 8월 7해)
    assert all(m["distinct"] is None and m["p_adjusted"] is None for m in t["by_month"])
    assert any("판정하지 않았습니다" in x for x in t["sentences"]) and t["thresholds"]["min_test_n"] == S.MIN_TEST_N
    assert all(w["distinct"] is not None for w in t["weekday"])         # 요일은 관측이 많아 판정한다


# ── 6. 오류 · 비었을 때 · 관리자 힌트 ─────────────────────────────────

def test_errors_unknown_target_missing_stock_and_missing_db(dbfile, tmp_path, monkeypatch):
    """TC-SE-09 · 모르는 대상 422 · 없는 종목 404 · DB 없음 503 — 할 일(명령)은 관리자에게만."""
    with pytest.raises(S.SeasonalityError) as e:
        S.read_seasonality("삼성전자", "tr")
    assert e.value.status == 422
    with pytest.raises(S.SeasonalityError) as e:
        S.read_seasonality("999999", "tr")
    assert e.value.status == 404
    with pytest.raises(S.SeasonalityError) as e:
        S.read_seasonality("KOSPI", "xx")                                # 모르는 기준
    assert e.value.status == 422
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없음.sqlite3"))
    with pytest.raises(S.SeasonalityError) as e:
        S.read_seasonality("KOSPI", "pr")
    assert e.value.status == 503
    user, admin = e.value.detail(False), e.value.detail(True)
    assert "admin_hint" not in user and "sqlite" not in str(user).lower() and "python" not in str(user)
    assert "admin_hint" in admin


def test_market_not_fetched_yet_is_200_with_reason_and_admin_hint_only_for_admin(dbfile):
    """TC-SE-10 · 지수를 아직 받지 않았으면 available False(200) · 까닭 글 · 관리자만 받기 명령."""
    out = S.read_seasonality("KOSDAQ", "pr", admin=False)
    assert out["available"] is False and out["reason"] and "admin_hint" not in out
    assert "ecos_series" not in str(out) and "python" not in str(out)
    adm = S.read_seasonality("KOSDAQ", "pr", admin=True)
    assert "collector.ecos" in adm["admin_hint"]


def test_opens_collector_db_read_only(dbfile, monkeypatch):
    """TC-SE-11 · 수집 DB 는 mode=ro 로만 연다."""
    _fill_index(dbfile, "0001000", _market_days(date(2024, 1, 2), date(2026, 10, 13)))
    seen = []
    real = sqlite3.connect

    def spy(target, *a, **k):
        seen.append(str(target))
        return real(target, *a, **k)

    monkeypatch.setattr(S.sqlite3, "connect", spy)
    S.read_seasonality("KOSPI", "pr", today=date(2026, 10, 14))
    assert seen and all("mode=ro" in t for t in seen)


def test_route_passes_admin_flag_and_maps_errors(monkeypatch):
    """TC-SE-12 · 라우트 — 로그인 사용자 · 관리자 여부를 서비스에 넘기고 서비스 오류를 그 상태 코드로."""
    from fastapi import HTTPException
    from app.routes import seasonality as R

    got = {}

    def fake(target, basis, admin=False, today=None):
        got.update(target=target, basis=basis, admin=admin)
        return {"available": True}

    monkeypatch.setattr(R.seasonality, "read_seasonality", fake)
    assert asyncio.run(R.seasonality_route(target="KOSPI", basis="pr", user={"roles": ["admin"]})) == {"available": True}
    assert got == {"target": "KOSPI", "basis": "pr", "admin": True}

    def boom(*a, **k):
        raise S.SeasonalityError(404, "없는 종목", "hint")

    monkeypatch.setattr(R.seasonality, "read_seasonality", boom)
    with pytest.raises(HTTPException) as e:
        asyncio.run(R.seasonality_route(target="123456", basis="tr", user={"roles": []}))
    assert e.value.status_code == 404 and "admin_hint" not in e.value.detail


# ── 7. 반년 비교 · 한 해 흐름 · 화면이 읽는 칸(2026-10-14 화면 결정 「A + B + C 탭」 뒤) ─────────

def _rows_from(values_by_year):
    """{해: [12칸 소수 또는 None]} 그대로 — 순수 함수 시험용."""
    return dict(sorted(values_by_year.items()))


def test_halves_split_winter_summer_and_judge_text_threshold():
    """TC-SE-13 · 반년 비교 = 11 ~ 4월 vs 5 ~ 10월 달 평균 · 웰치 p · 판정 글은 ALPHA 한 곳에서."""
    rnd = __import__("random").Random(20261014)
    rows = {y: [rnd.gauss(0.02 if m in S.WINTER_MONTHS else -0.01, 0.03) for m in range(12)] for y in range(1995, 2026)}
    hv = S.halves(_rows_from(rows))
    assert hv["n_winter"] == 31 * 6 and hv["n_summer"] == 31 * 6
    assert hv["winter_mean"] > 0.01 > -0.005 > hv["summer_mean"] and math.isclose(hv["diff"], hv["winter_mean"] - hv["summer_mean"])
    assert hv["p_value"] < S.ALPHA and S.judge_text(hv["p_value"]) == "우연으로 보기 어려운 차이"
    flat = S.halves(_rows_from({y: [rnd.gauss(0.0, 0.03) for _ in range(12)] for y in range(1995, 2026)}))
    assert flat["p_value"] > S.ALPHA and S.judge_text(flat["p_value"]) == "우연으로도 생길 만한 차이"
    assert S.judge_text(S.ALPHA) == "우연으로도 생길 만한 차이"            # 경계 — 「작으면」 이다
    assert S.judge_text(None) == "견줄 관측이 모자랍니다"
    assert set(S.WINTER_MONTHS) | set(S.SUMMER_MONTHS) == set(range(12)) and not set(S.WINTER_MONTHS) & set(S.SUMMER_MONTHS)


def test_year_paths_compound_break_on_gap_and_mean_only_january_years():
    """TC-SE-14 · 한 해 흐름 — 1월부터 곱해 쌓고 · 시작한 뒤 빈 달에서 끊고 · 평균은 1월 값이 있는 해만."""
    rows = _rows_from({
        2019: [None, 0.10, 0.10] + [None] * 9,                  # 첫 해(2월부터) — 선은 그리되 평균에서 뺀다
        2020: [0.10, 0.10, None, 0.50] + [0.0] * 8,             # 3월이 비면 거기서 끊는다(4월 +50% 를 잇지 않는다)
        2021: [0.10, -0.10] + [0.0] * 10,
    })
    yp = S.year_paths(rows)
    by = {r["year"]: r for r in yp["years"]}
    assert by[2019]["from_jan"] is False and by[2019]["path"][0] is None and math.isclose(by[2019]["path"][2], 1.1 * 1.1 - 1)
    assert math.isclose(by[2020]["path"][1], 0.21) and by[2020]["path"][2] is None and by[2020]["path"][3] is None
    assert all(v is None for v in by[2020]["path"][2:])
    assert math.isclose(by[2021]["path"][1], 1.1 * 0.9 - 1)
    assert yp["n"][0] == 2 and yp["n"][1] == 2 and yp["n"][2] == 1          # 2019 는 평균에 들지 않는다 · 2020 은 3월부터 빠진다
    assert math.isclose(yp["mean"][1], (0.21 + (1.1 * 0.9 - 1)) / 2) and math.isclose(yp["mean"][2], 1.1 * 0.9 - 1)


def test_response_has_choices_curves_halves_and_screen_texts(dbfile):
    """TC-SE-15 · 화면이 읽는 칸 — choices(시장 = MARKETS · 값 = BASIS_CHOICES) · curves · 반년 · 판정 글 · 비었을 때도 choices."""
    _fill_index(dbfile, "0001000", _market_days(date(1995, 1, 3), date(2026, 10, 13)))
    out = S.read_seasonality("KOSPI", "tr", today=date(2026, 10, 14))
    ch = out["choices"]
    assert [m["key"] for m in ch["markets"]] == [k for k, _i, _n in S.MARKETS]
    assert [b["key"] for b in ch["bases"]] == [k for k, _l in S.BASIS_CHOICES] and set(S.BASES) == {k for k, _l in S.BASIS_CHOICES}
    assert ch["stock"]["label"] and ch["stock"]["placeholder"]
    cv = out["curves"]
    assert cv["current_year"] == 2026 and len(cv["mean"]) == 12 and len(cv["n"]) == 12
    assert cv["years"][0]["year"] == 1995 and cv["years"][0]["from_jan"] is False and cv["n"][0] == 31   # 1996 ~ 2026
    assert cv["years"][-1]["path"][8] is not None and cv["years"][-1]["path"][9] is None                 # 2026 은 9월까지
    hv = out["windows"]["halves"]
    assert {"winter_mean", "summer_mean", "diff", "p_value", "judge_text", "n_winter", "n_summer"} <= set(hv)
    assert out["windows"]["year_end"]["judge_text"] in {"우연으로 보기 어려운 차이", "우연으로도 생길 만한 차이"}
    assert all(m["distinct_text"] == S.DISTINCT_TEXT[m["distinct"]] for m in out["by_month"] + out["weekday"])
    assert out["definitions"]["halves"] and out["definitions"]["curve"] and out["definitions"]["judge"]
    assert any("5월에 팔고 떠나라" in s for s in out["sentences"])
    empty = S.read_seasonality("KOSDAQ", "pr")
    assert empty["available"] is False and empty["choices"] == S.choices()
