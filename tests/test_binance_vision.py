"""TC-BV — Binance Vision 월 묶음 → ohlcv-v2 (collector/binance_vision.py · 할 일 ①-13 · 2026-10-30 · 네트워크 없음)

사용자 결정(10-30 「다양하게 전부」): 원본 주기 15종(1초봉만 제외)을 그대로. 받기와 정제를 나눈 순수 함수라 합성 zip 으로 확인한다.
1. 주소 · 지문 — 주기마다 주소가 맞고(1s 는 거부) 체크섬 글을 읽고 지문이 다르면 막는다. (TC-BV-01)
2. zip 읽기 — 12칸 · 마이크로초 → 밀리초 · 헤더 줄 건너뜀 · 빈 zip · 칸 수 틀림 · 파일이 둘인 zip 을 숨기지 않고 알린다. (TC-BV-02)
3. v2 줄 — UTC 날짜 · 코인 확장 칸 · 값 규칙 위반을 지우지 않고 센다. (TC-BV-03)
4. 적재 경로 · 달 목록 — HF 한도(폴더당 · 저장소당 파일 수) 안에서 종목 × 해 단위 파일. (TC-BV-04)
"""
from __future__ import annotations

import io
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import binance_vision as bv  # noqa: E402
from collector import crypto_v2, markets  # noqa: E402


def _ms(y, m, d, h=0, mi=0):
    return int(datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)


def _csv_line(t, o=100.0, h=110.0, l=90.0, c=105.0, v=12.5, qv=1300.0, trades=10):
    return f"{t},{o},{h},{l},{c},{v},{t + 59_999},{qv},{trades},5.5,600.0,0"


def _zip(lines, name="BTCUSDT-1m-2026-09.csv", extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, "\n".join(lines) + "\n")
        if extra:
            z.writestr(extra, "x")
    return buf.getvalue()


def test_urls_cover_every_interval_except_one_second_and_checksums_are_verified():
    """TC-BV-01 · 주소 꼴 · 15 주기 · 1s 거부 · 체크섬 글 읽기 · 지문이 다르면 막는다."""
    assert len(bv.INTERVALS) == 15 and "1s" not in bv.INTERVALS
    assert bv.zip_url("BTCUSDT", "1h", 2026, 9) == "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2026-09.zip"
    assert bv.checksum_url("ETHUSDT", "1mo", 2024, 1).endswith("/ETHUSDT/1mo/ETHUSDT-1mo-2024-01.zip.CHECKSUM")
    for iv in bv.INTERVALS:
        assert f"/{iv}/" in bv.zip_url("X", iv, 2026, 1)
    with pytest.raises(ValueError, match="받지 않는 주기"):
        bv.zip_url("BTCUSDT", "1s", 2026, 9)
    data = _zip([_csv_line(_ms(2026, 9, 1))])
    good = bv.sha256_hex(data)
    assert bv.parse_checksum(f"{good}  BTCUSDT-1m-2026-09.zip\n") == good
    with pytest.raises(ValueError, match="체크섬 글"):
        bv.parse_checksum("not a checksum")
    assert len(bv.parse_zip(data, "BTCUSDT", expected_sha256=good)) == 1
    with pytest.raises(ValueError, match="지문이 체크섬과 다르다"):
        bv.parse_zip(data, "BTCUSDT", expected_sha256="0" * 64)


def test_parse_zip_normalises_time_and_reports_bad_files():
    """TC-BV-02 · 마이크로초 → 밀리초 · 헤더 줄 · 빈 zip · 칸 수 · 파일 둘."""
    t = _ms(2026, 9, 1)
    rows = bv.parse_zip(_zip([_csv_line(t * 1000), _csv_line(t + 60_000)]), "BTCUSDT")
    assert [r["open_time_ms"] for r in rows] == [t, t + 60_000], "2025-01 이후 마이크로초를 밀리초로 맞춘다"
    assert rows[0]["symbol"] == "BTCUSDT" and rows[0]["trades"] == "10" and rows[0]["taker_buy_base"] == "5.5"
    header = "open_time,open,high,low,close,volume,close_time,quote_volume,trades,taker_buy_base,taker_buy_quote,ignore"
    assert len(bv.parse_zip(_zip([header, _csv_line(t)]), "BTCUSDT")) == 1
    with pytest.raises(ValueError, match="봉이 없다"):
        bv.parse_zip(_zip([]), "BTCUSDT")
    with pytest.raises(ValueError, match="칸 수 3"):
        bv.parse_zip(_zip([_csv_line(t), "1,2,3"]), "BTCUSDT")
    with pytest.raises(ValueError, match="파일이 2개"):
        bv.parse_zip(_zip([_csv_line(t)], extra="b.csv"), "BTCUSDT")


def test_to_v2_rows_keeps_extras_and_counts_bad_rows_without_dropping():
    """TC-BV-03 · v2 줄(UTC 날짜 · 확장 칸) + 값 규칙 위반을 지우지 않고 센다 · 모든 주기 이름이 v2 주기가 된다."""
    t = _ms(2026, 9, 1)
    day = 86_400_000
    lines = [_csv_line(t), _csv_line(t + day, l=0.0), _csv_line(t + 2 * day, v=-1.0), _csv_line(t + 3 * day)]
    out = bv.to_v2_rows(_zip(lines), "BTCUSDT", "1d", fetched_at="2026-10-30T12:50:00+09:00")
    assert len(out["rows"]) == 4 and out["problems"] == {"price_nonpositive": 1, "volume_negative": 1} and out["bad_rows"] == 2
    r = out["rows"][0]
    assert r["trade_date"] == "2026-09-01" and r["bar_start"] is None and r["venue"] == "BINANCE_SPOT_USDT"
    assert (r["trades"], r["taker_buy_base"], r["taker_buy_quote"]) == (10, 5.5, 600.0) and r["value"] == 1300.0
    for iv in bv.INTERVALS:                                     # 15 주기 모두 변환되고 v2 주기 이름이 된다
        row = bv.to_v2_rows(_zip([_csv_line(t)]), "BTCUSDT", iv)["rows"][0]
        assert row["timeframe"] in __import__("collector.bars_v2", fromlist=["x"]).TIMEFRAMES
        assert (row["bar_start"] is None) == (iv in ("1d", "3d", "1w", "1mo")) and markets.check_v2(row) == []
    hourly = bv.to_v2_rows(_zip([_csv_line(_ms(2026, 9, 1, 15))]), "BTCUSDT", "4h")["rows"][0]
    assert hourly["timeframe"] == "240m" and hourly["bar_start"] == "2026-09-01T15:00:00+00:00"
    assert crypto_v2.TIMEFRAME["1h"] == "60m" and crypto_v2.TIMEFRAME["12h"] == "720m"


def test_partition_path_and_month_range():
    """TC-BV-04 · 적재 경로 꼴(HF 한도 안) · 달 목록(해 넘김 · 거꾸로 기간은 거부)."""
    p = bv.partition_path(Path("data/crypto"), "1m", 2026, "BTCUSDT")
    assert p.as_posix() == "data/crypto/ohlcv/timeframe=1m/market=BINANCE_SPOT_USDT/year=2026/symbol=BTCUSDT.parquet"
    assert bv.partition_path(Path("data/crypto"), "4h", 2026, "BTCUSDT").as_posix() == \
        "data/crypto/ohlcv/timeframe=4h/market=BINANCE_SPOT_USDT/symbol=BTCUSDT.parquet", "거친 주기는 해 폴더가 없다"
    assert bv.FINE == ("1m", "3m", "5m", "15m", "30m") and len(bv.COARSE) == 10 and "1h" in bv.COARSE and "1mo" in bv.COARSE
    with pytest.raises(ValueError):
        bv.partition_path(Path("x"), "1s", 2026, "BTCUSDT")
    # 파일 수 어림 — 모두 해로 쪼개면 15 × 757 × 10 = 113,550 개로 HF 저장소당 10만 개 권장을 넘는다. 거친 주기를 종목당 하나로 묶으면 그 아래다
    assert 15 * 757 * 10 > 100_000
    files = len(bv.FINE) * 757 * 10 + len(bv.COARSE) * 757
    assert files == 45_420 < 100_000, "설계 파일 수(해 10 · 종목 757 가정)가 HF 권장 안"
    assert 757 < 10_000, "어느 폴더든 종목 수 안팎(HF 폴더당 1만 개 권장 아래)"
    assert bv.month_range((2025, 11), (2026, 2)) == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]
    assert bv.month_range((2026, 9), (2026, 9)) == [(2026, 9)]
    with pytest.raises(ValueError, match="거꾸로"):
        bv.month_range((2026, 9), (2026, 1))
