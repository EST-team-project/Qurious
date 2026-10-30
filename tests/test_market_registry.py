"""TC-MKT — 시장 레지스트리와 `ohlcv-v2` 규칙 (collector/markets.py · 할 일 ①-06 · 2026-10-30)

1. 레지스트리 앞뒤가 맞고(상태 · 종류 · 시간대 · 코인 24x7) 국내는 지금 값 그대로 한 줄이다. (TC-MKT-01)
2. v2 = v1 모든 칸 + venue · currency · tz — 앞 열일곱 칸 · 차례는 그대로, 키에 venue 가 든다. (TC-MKT-02)
3. 거래소 현지 날짜 — 미국 서머타임 끝(2026-11-01) 앞뒤 · KST 로 바꾸면 날짜가 밀리는 경우 · 코인 UTC 경계. (TC-MKT-03)
4. v1 → v2 변환은 값을 안 건드리고, 줄 검사가 날짜 밀림 · 통화 · 시간대 · 시간대 없는 시각을 잡는다. (TC-MKT-04)
5. 새 파일이 수집기 러너 · 기존 규격에 닿지 않는다(국내 표 · v1 그대로 — 12:30 회차를 안 건드림). (TC-MKT-05)
"""
from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import markets, ohlcv  # noqa: E402

KST = timezone(timedelta(hours=9))


def test_registry_is_consistent_and_domestic_is_one_line():
    """TC-MKT-01 · 레지스트리 앞뒤 · 국내는 지금 값 한 줄(정규장 09:00~15:30 · KST · KRW · 우리 달력)."""
    assert markets.validate_registry() == []
    k = markets.get("XKRX")
    assert (k.currency, k.tz, k.calendar, k.hf_dataset, k.status) == ("KRW", "Asia/Seoul", "market_calendar", "krx-ohlcv", "live")
    assert k.regular_session == (time(9, 0), time(15, 30)), "collector/ohlcv.py 의 정규장과 같아야 한다"
    assert (ohlcv.REGULAR_OPEN, ohlcv.REGULAR_CLOSE) == k.regular_session
    for v in ("XNYS", "XNAS"):
        m = markets.get(v)
        assert (m.currency, m.tz, m.kind) == ("USD", "America/New_York", "equity") and m.regular_session == (time(9, 30), time(16, 0))
    c = markets.get("BINANCE_SPOT_USDT")
    assert c.kind == "crypto" and c.calendar == "24x7" and c.annualization_days == 365 and c.hf_dataset == "crypto-ohlcv"
    # 이미 HF 에 올라간 코인 시장 이름(2026-10-22 일회 수집 · market=BINANCE_SPOT_USDT 경로)을 바꾸지 않았다
    assert markets.venues(status="stored") == ["BINANCE_SPOT_USDT"]
    # 팀에 안 나누는 시장은 HF 목록에서 빠진다
    assert markets.get("UPBIT").status == "local_only" and "" not in markets.hf_datasets()
    assert markets.hf_datasets() == ["krx-ohlcv", "us-ohlcv", "crypto-ohlcv"]
    with pytest.raises(KeyError, match="레지스트리에 없는 코드"):
        markets.get("XXXX")


def test_registry_validation_catches_a_broken_entry(monkeypatch):
    """TC-MKT-01b · 일부러 깬 항목을 잡는다(늘 통과하는 검사는 고장을 못 가린다)."""
    from dataclasses import replace
    broken = dict(markets.MARKETS)
    broken["XNYS"] = replace(markets.MARKETS["XNYS"], tz="Mars/Olympus", status="maybe")
    broken["BINANCE_SPOT_USDT"] = replace(markets.MARKETS["BINANCE_SPOT_USDT"], calendar="XNYS", annualization_days=None)
    monkeypatch.setattr(markets, "MARKETS", broken)
    bad = " | ".join(markets.validate_registry())
    assert "Mars/Olympus" in bad and "maybe" in bad and "24x7" in bad and "365" in bad


def test_v2_is_v1_plus_three_columns_in_the_same_order():
    """TC-MKT-02 · v2 = v1 + venue · currency · tz — 앞 열일곱 칸이 그대로이고 contract 는 마지막, 키에 venue."""
    v1 = list(ohlcv.COLUMNS)
    v2 = list(markets.COLUMNS)
    assert v2[:len(v1) - 1] == v1[:-1], "v1 을 위치로 읽는 코드를 깨지 않는다"
    assert v2[-4:] == ["venue", "currency", "tz", "contract"] and len(v2) == len(v1) + 3
    assert set(markets.REQUIRED) == set(ohlcv.REQUIRED) | {"venue", "currency", "tz"}
    assert markets.KEY == ("venue",) + tuple(ohlcv.KEY)
    assert markets.CONTRACT == "ohlcv-v2" and ohlcv.CONTRACT == "ohlcv-v1", "v1 은 그대로 v1 이다"


def test_trade_date_is_exchange_local_across_us_dst_end():
    """TC-MKT-03 · 2026-11-01 02:00 에 미국 서머타임이 끝난다(한국 시각이 1시간 밀림) — 앞뒤 모두 뉴욕 날짜로 센다."""
    utc = timezone.utc
    # 서머타임 중(EDT = UTC−4): 금요일 15:59 ET = 19:59Z → 같은 날
    assert markets.local_trade_date("XNYS", datetime(2026, 10, 30, 19, 59, tzinfo=utc)) == date(2026, 10, 30)
    # 일요일(11-01) 새벽: 05:30Z = 01:30 EDT(첫 번째 1시 30분) · 06:30Z = 01:30 EST(두 번째) — 둘 다 11-01
    assert markets.local_trade_date("XNYS", datetime(2026, 11, 1, 5, 30, tzinfo=utc)) == date(2026, 11, 1)
    assert markets.local_trade_date("XNYS", datetime(2026, 11, 1, 6, 30, tzinfo=utc)) == date(2026, 11, 1)
    # 표준시(EST = UTC−5): 월요일 장 시작 09:30 ET = 14:30Z · 장 마감 16:00 ET = 21:00Z → 11-02
    assert markets.local_trade_date("XNYS", datetime(2026, 11, 2, 14, 30, tzinfo=utc)) == date(2026, 11, 2)
    assert markets.local_trade_date("XNYS", datetime(2026, 11, 2, 21, 0, tzinfo=utc)) == date(2026, 11, 2)
    # 같은 마감 봉을 KST 로 바꾸면 날짜가 하루 밀린다 — 그래서 trade_date 를 KST 로 두면 안 된다(조사서 <표 6> 5행)
    close_kst = datetime(2026, 11, 2, 21, 0, tzinfo=utc).astimezone(KST)
    assert close_kst.date() == date(2026, 11, 3) and markets.local_trade_date("XNYS", close_kst) == date(2026, 11, 2)
    # 서머타임 중 마감 봉도 마찬가지(16:00 EDT = 20:00Z = 다음 날 05:00 KST)
    assert datetime(2026, 10, 30, 20, 0, tzinfo=utc).astimezone(KST).date() == date(2026, 10, 31)
    assert markets.local_trade_date("XNYS", "2026-10-30T20:00:00Z") == date(2026, 10, 30)
    # 국내는 KST 날짜 그대로
    assert markets.local_trade_date("XKRX", datetime(2026, 10, 30, 15, 30, tzinfo=KST)) == date(2026, 10, 30)
    # 코인 일 캔들은 UTC 00:00 경계 — 한국 시각 09:00 이 하루의 시작
    assert markets.local_trade_date("BINANCE_SPOT_USDT", datetime(2026, 10, 30, 9, 0, tzinfo=KST)) == date(2026, 10, 30)
    assert markets.local_trade_date("BINANCE_SPOT_USDT", datetime(2026, 10, 30, 8, 59, tzinfo=KST)) == date(2026, 10, 29)
    with pytest.raises(ValueError, match="시간대 표시가 없는"):
        markets.local_trade_date("XNYS", datetime(2026, 11, 2, 14, 30))


def _v1_row(**kw):
    row = {"symbol": "005930", "market": "KOSPI", "timeframe": "1d", "trade_date": "2026-10-29", "bar_start": None,
           "open": 70000, "high": 71000, "low": 69500, "close": 70500, "volume": 100, "value": 7050000,
           "adjusted": True, "price_basis": "adj_base", "adj_factor": 1.0, "session": None,
           "source": "portal", "fetched_at": "2026-10-30T12:50:00+09:00", "contract": "ohlcv-v1"}
    row.update(kw)
    return row


def test_v1_to_v2_keeps_values_and_checks_catch_drift():
    """TC-MKT-04 · v1 → v2 는 값을 안 건드리고, 검사가 날짜 밀림 · 통화 · 시간대 · 시간대 없는 시각 · 모르는 시장을 잡는다."""
    v1 = _v1_row()
    v2 = markets.to_v2(v1, "XKRX")
    assert list(v2) == list(markets.COLUMNS)
    assert (v2["venue"], v2["currency"], v2["tz"], v2["contract"]) == ("XKRX", "KRW", "Asia/Seoul", "ohlcv-v2")
    assert v2["market"] == "KOSPI", "v1 의 market(게시판)은 그대로다"
    assert all(v2[c] == v1[c] for c in ohlcv.COLUMNS if c != "contract"), "값을 건드리지 않았다"
    assert markets.check_v2(v2) == []
    # 미국 분봉: 서머타임 끝난 월요일 09:30 ET 봉 — 정상은 trade_date 11-02
    us = markets.to_v2(_v1_row(symbol="SPY", market="ETF", timeframe="5m", trade_date="2026-11-02",
                               bar_start="2026-11-02T09:30:00-05:00"), "XNAS")
    assert markets.check_v2(us) == []
    # KST 날짜로 잘못 적으면(마감 봉 16:00 ET = KST 다음 날) 날짜 밀림으로 잡힌다
    shifted = dict(us, bar_start="2026-11-02T15:55:00-05:00", trade_date="2026-11-03")
    assert markets.check_v2(shifted) == ["trade_date_mismatch"]
    assert markets.check_v2(dict(v2, currency="USD")) == ["currency_mismatch"]
    assert markets.check_v2(dict(v2, tz="UTC")) == ["tz_mismatch"]
    assert markets.check_v2(dict(us, bar_start="2026-11-02T09:30:00")) == ["bar_start_naive"]
    assert markets.check_v2(dict(v2, venue="XSHG")) == ["bad_venue"]
    assert set(markets.RULES_V2) == {"bad_venue", "currency_mismatch", "tz_mismatch", "bad_board", "bar_start_naive", "trade_date_mismatch"}
    with pytest.raises(KeyError):
        markets.to_v2(v1, "XSHG")


def test_new_file_does_not_touch_the_runner_or_v1_contract():
    """TC-MKT-05 · 12:30 회차를 안 건드린다 — 러너 · 내보내기 · v1 규격 파일이 레지스트리를 부르지 않고, v1 상수는 그대로."""
    for rel in ("scripts/daily_update.py", "collector/ohlcv.py", "collector/ohlcv_export.py", "collector/db.py", "collector/quality.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "collector.markets" not in src and "from collector import markets" not in src, f"{rel} 이 레지스트리를 부른다"
    assert ohlcv.MARKETS == ("KOSPI", "KOSDAQ", "KONEX", "ETF", "ETN", "INDEX"), "v1 의 market(게시판) 목록은 그대로"
    assert ohlcv.KEY == ("symbol", "timeframe", "price_basis", "trade_date", "bar_start")


def test_contract_doc_matches_registry_and_v2_columns():
    """TC-MKT-06 · 계약 문서가 코드와 어긋나지 않는다 — 시장 코드마다 표에 줄이 있고 시간대 · 통화 · HF 이름이 같으며,
    v2 가 더하는 칸 · 검사 규칙이 모두 문서에 적혀 있다(정본은 코드)."""
    doc = (ROOT / "docs" / "phase-3" / "02-design" / "system" / "시장-데이터-계약.md").read_text(encoding="utf-8")
    rows = {ln.split("|")[1].strip().strip("`"): ln for ln in doc.splitlines() if ln.startswith("| `")}
    for venue, m in markets.MARKETS.items():
        assert venue in rows, f"계약 문서 2절에 {venue} 줄이 없다"
        line = rows[venue]
        assert m.currency in line and f"`{m.tz}`" in line and m.status in line, f"{venue} 줄이 코드와 다르다"
        assert (m.hf_dataset == "" and "| — |" in line) or f"`{m.hf_dataset}`" in line, f"{venue} 의 HF 이름이 다르다"
    for col in markets.EXTRA_COLUMNS:
        assert f"`{col}`" in doc, f"계약 문서 3절에 {col} 칸이 없다"
    for rule in markets.RULES_V2:
        assert f"`{rule}`" in doc, f"계약 문서 3.1절에 {rule} 규칙이 없다"
    assert markets.CONTRACT in doc


# ── 코인 → ohlcv-v2 (collector/crypto_v2.py · ①-13 의 네트워크 없는 부분) ──────────────────────────────
from collector import crypto_v2  # noqa: E402


def _raw(ts_ms, **kw):
    row = {"symbol": "BTCUSDT", "open_time_ms": ts_ms, "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0,
           "volume": 12.5, "quote_volume": 1300.0, "close_time_ms": ts_ms + 86_399_999, "trades": 10}
    row.update(kw)
    return row


def test_crypto_daily_row_becomes_v2_with_utc_trade_date():
    """TC-MKT-07 · 일봉 — 하루 경계는 UTC 00:00 · 일봉은 봉 시각이 없고 · 통화 USDT · 시간대 UTC · 값은 그대로."""
    ms = int(datetime(2026, 10, 29, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)    # KST 10-29 09:00
    r = crypto_v2.to_v2(_raw(ms), "1d", fetched_at="2026-10-30T12:50:00+09:00")
    assert list(r)[:len(markets.COLUMNS)] == list(markets.COLUMNS) and r["contract"] == "ohlcv-v2", "핵심 칸 · 차례는 그대로"
    assert list(r)[len(markets.COLUMNS):] == list(crypto_v2.EXT_COLUMNS) and r["trades"] == 10, "코인 확장 칸은 핵심 칸 뒤"
    assert (r["venue"], r["market"], r["currency"], r["tz"]) == ("BINANCE_SPOT_USDT", "SPOT", "USDT", "UTC")
    assert r["timeframe"] == "1d" and r["trade_date"] == "2026-10-29" and r["bar_start"] is None
    assert (r["open"], r["high"], r["low"], r["close"], r["volume"], r["value"]) == (100.0, 110.0, 90.0, 105.0, 12.5, 1300.0)
    assert (r["price_basis"], r["adjusted"], r["source"]) == ("raw", False, "binance_vision")
    assert crypto_v2.check_values(r) == [] and markets.check_v2(r) == []
    # 마이크로초(2025-01 이후 원본)가 섞여 와도 같은 날로 맞춘다
    assert crypto_v2.to_v2(_raw(ms * 1000), "1d")["trade_date"] == "2026-10-29"


def test_crypto_hourly_row_keeps_utc_bar_start_and_date_across_kst_midnight():
    """TC-MKT-07b · 1h → 60m — 봉 시각에 시간대(+00:00)가 붙고, KST 로는 다음 날인 UTC 15:00~23:00 봉도 UTC 날짜로 센다."""
    ms = int(datetime(2026, 10, 29, 16, 0, tzinfo=timezone.utc).timestamp() * 1000)   # KST 10-30 01:00
    r = crypto_v2.to_v2(_raw(ms), "1h")
    assert r["timeframe"] == "60m" and r["bar_start"] == "2026-10-29T16:00:00+00:00" and r["trade_date"] == "2026-10-29"
    assert markets.check_v2(r) == [] and crypto_v2.check_values(r) == []
    with pytest.raises(ValueError, match="모르는 주기"):
        crypto_v2.to_v2(_raw(ms), "7h")                       # 바이낸스에 없는 주기


def test_crypto_value_rules_catch_bad_rows_and_never_drop_them():
    """TC-MKT-07c · 값 규칙(가격 0 이하 · 고저 순서 · 음수 거래량 · 중복)을 줄마다 잡고, 위반 줄도 지우지 않고 돌려준다."""
    ms = int(datetime(2026, 10, 29, tzinfo=timezone.utc).timestamp() * 1000)
    day = 86_400_000
    raws = [_raw(ms), _raw(ms + day, low=0.0), _raw(ms + 2 * day, high=100.0, low=90.0, open=100.0, close=105.0),
            _raw(ms + 3 * day, volume=-1.0), _raw(ms)]                                    # 마지막은 첫 줄과 같은 날(중복)
    out = crypto_v2.convert(raws, "1d")
    assert len(out["rows"]) == 5, "위반 줄을 조용히 버리지 않는다"
    assert out["problems"] == {"price_nonpositive": 1, "ohlc_order": 1, "volume_negative": 1, "duplicate_key": 1}
    assert out["bad_rows"] == 3
    assert crypto_v2.check_values(dict(out["rows"][0], timeframe="7h")) == ["bad_timeframe"]
    assert set(crypto_v2.RULES) == {"bad_timeframe", "price_nonpositive", "ohlc_order", "volume_negative"}


def test_board_rule_and_registry_boards():
    """TC-MKT-04b · 게시판(market) 값은 그 시장이 쓰는 목록 안에 있어야 한다 — 국내는 v1 목록 그대로, 코인은 SPOT."""
    assert markets.get("XKRX").boards == tuple(ohlcv.MARKETS) and markets.get("BINANCE_SPOT_USDT").boards == ("SPOT",)
    v2 = markets.to_v2(_v1_row(), "XKRX")
    assert markets.check_v2(v2) == []
    assert markets.check_v2(dict(v2, market="SPOT")) == ["bad_board"], "국내 줄에 코인 게시판 값이 들어오면 잡는다"
    assert markets.check_v2(dict(v2, venue="BINANCE_SPOT_USDT", currency="USDT", tz="UTC")) == ["bad_board"]


# ── 분봉 합성 (collector/bars_v2.py · 사용자 피드백 10-30 — 시간봉을 다양하게) ─────────────────────────
from collector import bars_v2  # noqa: E402


def _bars(venue, symbol, tf, start_iso, n, step_min, *, tz_start=None, price0=100.0):
    """합성 분봉 n 개 — 값이 봉마다 달라 합친 결과(시가 첫 · 고가 최대 · 저가 최소 · 종가 끝 · 거래량 합)를 가릴 수 있다."""
    m = markets.get(venue)
    start = datetime.fromisoformat(start_iso)
    rows = []
    for i in range(n):
        t = start + timedelta(minutes=step_min * i)
        o = price0 + i
        r = {"symbol": symbol, "market": m.boards[0], "timeframe": tf, "trade_date": "x", "bar_start": t.isoformat(),
             "open": o, "high": o + 2 + (i % 3), "low": o - 1 - (i % 2), "close": o + 0.5, "volume": 10.0 + i, "value": 100.0 + i,
             "adjusted": False, "price_basis": "raw", "adj_factor": None, "session": None,
             "source": "t", "fetched_at": f"2026-10-30T12:{i % 60:02d}:00+09:00", "contract": "ohlcv-v2",
             "venue": venue, "currency": m.currency, "tz": m.tz}
        rows.append(r)
    return rows


def test_resample_one_minute_to_ten_minutes_for_crypto_and_flags_missing_children():
    """TC-MKT-08 · 코인 1분 → 10분 — 시가 첫 · 고가 최대 · 저가 최소 · 종가 끝 · 거래량 합 · UTC 00:00 정렬 · 빠진 봉은 incomplete."""
    rows = _bars("BINANCE_SPOT_USDT", "BTCUSDT", "1m", "2026-10-29T23:55:00+00:00", 20, 1)     # 23:55 ~ 00:14
    out = bars_v2.resample(rows, "10m")
    starts = [r["bar_start"] for r in out["rows"]]
    assert starts == ["2026-10-29T23:50:00+00:00", "2026-10-30T00:00:00+00:00", "2026-10-30T00:10:00+00:00"]
    mid = out["rows"][1]                                    # 00:00 ~ 00:09 = 원본 5 ~ 14 번째(i=5..14)
    kids = rows[5:15]
    assert (mid["open"], mid["close"]) == (kids[0]["open"], kids[-1]["close"])
    assert mid["high"] == max(k["high"] for k in kids) and mid["low"] == min(k["low"] for k in kids)
    assert mid["volume"] == sum(k["volume"] for k in kids) and mid["value"] == sum(k["value"] for k in kids)
    assert mid["timeframe"] == "10m" and mid["trade_date"] == "2026-10-30" and out["rows"][0]["trade_date"] == "2026-10-29", "UTC 날짜로 센다"
    assert out["incomplete"] == ["2026-10-29T23:50:00+00:00", "2026-10-30T00:10:00+00:00"], "첫 칸(5개) · 끝 칸(5개)은 덜 찼다"
    assert all(markets.check_v2(r) == [] for r in out["rows"]) and all(crypto_v2.check_values(r) == [] for r in out["rows"])


def test_resample_us_bars_align_to_session_open_across_dst_end():
    """TC-MKT-09 · 미국 5분 → 30분 · 60분 — 정규장 시작(09:30 ET)에 맞춘다. 서머타임 앞(EDT −04:00) · 뒤(EST −05:00) 모두 같은 현지 시각."""
    for day, off in (("2026-10-30", "-04:00"), ("2026-11-02", "-05:00")):
        rows = _bars("XNAS", "SPY", "5m", f"{day}T09:30:00{off}", 78, 5)                 # 09:30 ~ 15:55 = 78 개
        for target, first_n, last_start, count in (("30m", 6, "15:30", 13), ("60m", 12, "15:30", 7)):
            out = bars_v2.resample(rows, target)
            assert len(out["rows"]) == count and out["incomplete"] == [], (day, target)
            assert out["rows"][0]["bar_start"] == f"{day}T09:30:00{off}"
            assert out["rows"][-1]["bar_start"] == f"{day}T{last_start}:00{off}"
            assert {r["trade_date"] for r in out["rows"]} == {day} and all(markets.check_v2(r) == [] for r in out["rows"])
        assert out["rows"][1]["bar_start"] == f"{day}T10:30:00{off}", "60분봉은 09:30 · 10:30 … (09:00 이 아니다)"
    # 장 시작 앞(프리마켓) 봉은 시작점 앞 칸으로 가고 「덜 찼다」 로 세지 않는다
    pre = bars_v2.resample(_bars("XNAS", "SPY", "5m", "2026-10-30T09:25:00-04:00", 2, 5), "30m")
    assert [r["bar_start"] for r in pre["rows"]] == ["2026-10-30T09:00:00-04:00", "2026-10-30T09:30:00-04:00"]
    assert "2026-10-30T09:00:00-04:00" not in pre["incomplete"]
    assert pre["incomplete"] == ["2026-10-30T09:30:00-04:00"], "장 안 칸은 6개여야 하는데 1개뿐"


def test_resample_korean_session_and_chain_consistency_and_guards():
    """TC-MKT-10 · 국내는 09:00 정렬 · 1분→5분→30분이 1분→30분과 같다 · 나눠 떨어지지 않거나 더 잘은 목표 · 섞인 입력은 막는다."""
    rows = _bars("XKRX", "005930", "1m", "2026-10-30T09:00:00+09:00", 60, 1)
    direct = bars_v2.resample(rows, "30m")
    assert [r["bar_start"][11:16] for r in direct["rows"]] == ["09:00", "09:30"] and direct["incomplete"] == []
    chained = bars_v2.resample(bars_v2.resample(rows, "5m")["rows"], "30m")
    keep = ("bar_start", "open", "high", "low", "close", "volume", "value")
    assert [{k: r[k] for k in keep} for r in direct["rows"]] == [{k: r[k] for k in keep} for r in chained["rows"]], "합치는 순서가 값을 바꾸지 않는다"
    with pytest.raises(ValueError, match="만들 수 없다"):
        bars_v2.resample(rows, "1m")                       # 원본과 같은 주기
    with pytest.raises(ValueError, match="분봉 주기가 아니다"):
        bars_v2.resample(rows, "7m")
    with pytest.raises(ValueError, match="만들 수 없다"):
        bars_v2.resample(_bars("XKRX", "005930", "10m", "2026-10-30T09:00:00+09:00", 3, 10), "15m")
    with pytest.raises(ValueError, match="섞여 있다"):
        bars_v2.resample(rows[:2] + _bars("XKRX", "000660", "1m", "2026-10-30T09:02:00+09:00", 1, 1), "5m")
    with pytest.raises(ValueError, match="같은 봉 시각"):
        bars_v2.resample(rows[:2] + rows[:1], "5m")
    naive = dict(rows[0], bar_start="2026-10-30T09:00:00")
    with pytest.raises(ValueError, match="시간대 표시가 없는"):
        bars_v2.resample([naive], "5m")
    assert bars_v2.resample([], "5m") == {"rows": [], "incomplete": []}
    # 코인 변환기도 바이낸스가 직접 주는 분봉 주기를 받는다
    assert {"1m", "5m", "15m", "30m"} <= set(crypto_v2.TIMEFRAME) and crypto_v2.TIMEFRAME["1h"] == "60m"
    assert set(bars_v2.MINUTES) == {"1m", "3m", "5m", "10m", "15m", "30m", "60m", "120m", "240m", "360m", "480m", "720m"}
    assert bars_v2.DAILY_PLUS == ("1d", "3d", "1w", "1mo")
    # 사용자 결정(10-30 「다양하게 전부」) — 바이낸스 원본 주기를 모두 받는다(1초봉만 제외)
    assert set(crypto_v2.TIMEFRAME) == {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1mo"}
    assert all(v in bars_v2.TIMEFRAMES for v in crypto_v2.TIMEFRAME.values()), "변환 결과 주기가 v2 주기 목록 안에 있다"
