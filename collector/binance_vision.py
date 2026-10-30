"""Binance Vision 월 묶음(zip) → `ohlcv-v2` 줄 — **받기와 정제를 나눈 순수 함수**(네트워크 없음) (할 일 ①-13 · 2026-10-30).

수집 파이프라인 설계 P6(받기 → 정제 → 적재 분리)을 처음부터 지킨다 — 이 파일은 「정제」 몫이다. zip 을 받는 일(네트워크 ·
간격 · 재시도)과 parquet 으로 쓰는 일(적재)은 따로 둔다. 받은 zip 바이트만 있으면 어디서든 같은 줄이 나온다.

사용자 결정(10-30): 주기도 종목도 **가능한 한 전부** — 원본 주기를 그대로 받는다(1초봉만 제외 · 계약 문서 3.3절).
원본 CSV 열(헤더 없음): open_time · open · high · low · close · volume · close_time · quote_volume · trades ·
taker_buy_base · taker_buy_quote · ignore. 2025-01 부터 현물 시각이 마이크로초라 밀리초로 맞춘다(`crypto_v2._to_ms`).

이용 조건: Binance Vision 데이터 = CC BY-NC-SA 4.0(비상업 · 파생물도 같은 조건) — 개인 프로젝트로 이어 가도 비상업 · 학습 · 연구 안에서만.
"""
from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector import bars_v2, crypto_v2

BASE = "https://data.binance.vision/data/spot/monthly/klines"
#: 받는 원본 주기 — 1초봉(`1s`)만 뺀다(1분봉의 약 60배 용량)
INTERVALS: Tuple[str, ...] = tuple(crypto_v2.TIMEFRAME)
#: 거친 주기(1시간 이상)는 **해로 쪼개지 않는다** — 종목당 파일 하나(10년치도 0.1 MB 안팎). 15 주기 × 종목 757 × 해 10 = 11만 개로 쪼개면
#: HF 저장소당 파일 수 권장(10만 개 미만)을 넘는다. 잘게(1 ~ 30분)만 해로 쪼갠다 — 해 폴더 안 종목 파일 ≤ 757.
COARSE: Tuple[str, ...] = tuple(iv for iv in INTERVALS
                                if crypto_v2.TIMEFRAME[iv] in bars_v2.DAILY_PLUS or bars_v2.MINUTES[crypto_v2.TIMEFRAME[iv]] >= 60)
FINE: Tuple[str, ...] = tuple(iv for iv in INTERVALS if iv not in COARSE)
CSV_COLUMNS = ("open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades",
               "taker_buy_base", "taker_buy_quote", "ignore")


def zip_url(symbol: str, interval: str, year: int, month: int) -> str:
    if interval not in INTERVALS:
        raise ValueError(f"받지 않는 주기: {interval!r} — {', '.join(INTERVALS)} 중 하나(1s 는 제외)")
    ym = f"{year:04d}-{month:02d}"
    return f"{BASE}/{symbol}/{interval}/{symbol}-{interval}-{ym}.zip"


def checksum_url(symbol: str, interval: str, year: int, month: int) -> str:
    return zip_url(symbol, interval, year, month) + ".CHECKSUM"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_checksum(text: str) -> str:
    """`.CHECKSUM` 파일 글(「해시  파일이름」) → 해시. 모양이 다르면 `ValueError`."""
    tok = text.strip().split()
    if not tok or len(tok[0]) != 64 or any(c not in "0123456789abcdefABCDEF" for c in tok[0]):
        raise ValueError(f"체크섬 글을 읽지 못했다: {text[:60]!r}")
    return tok[0].lower()


def parse_zip(data: bytes, symbol: str, *, expected_sha256: Optional[str] = None) -> List[dict]:
    """zip 바이트 → 원본 줄들(`crypto_v2.to_v2` 가 읽는 칸 이름). `expected_sha256` 을 주면 지문이 다를 때 `ValueError`.
    헤더 줄이 있으면 건너뛰고, 빈 zip · 칸 수가 다른 줄은 숨기지 않고 알린다."""
    if expected_sha256 is not None and sha256_hex(data) != expected_sha256.lower():
        raise ValueError(f"{symbol}: zip 지문이 체크섬과 다르다 — 받다가 깨졌거나 바뀐 파일")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        if len(names) != 1:
            raise ValueError(f"{symbol}: zip 안 파일이 {len(names)}개다(하나여야 한다): {names[:3]}")
        text = z.read(names[0]).decode("utf-8")
    out: List[dict] = []
    for i, cells in enumerate(csv.reader(io.StringIO(text))):
        if not cells:
            continue
        if i == 0 and not cells[0].strip().lstrip("-").isdigit():        # 헤더가 있는 판
            continue
        if len(cells) != len(CSV_COLUMNS):
            raise ValueError(f"{symbol}: {i + 1}번째 줄 칸 수 {len(cells)} (12여야 한다)")
        d = dict(zip(CSV_COLUMNS, cells))
        out.append({"symbol": symbol, "open_time_ms": crypto_v2._to_ms(d["open_time"]), "open": d["open"], "high": d["high"],
                    "low": d["low"], "close": d["close"], "volume": d["volume"], "quote_volume": d["quote_volume"],
                    "trades": d["trades"], "taker_buy_base": d["taker_buy_base"], "taker_buy_quote": d["taker_buy_quote"]})
    if not out:
        raise ValueError(f"{symbol}: zip 안에 봉이 없다")
    return out


def to_v2_rows(data: bytes, symbol: str, interval: str, *, expected_sha256: Optional[str] = None,
               fetched_at: Optional[str] = None) -> Dict:
    """zip → `{"rows": [v2 줄], "problems": {규칙: 개수}, "bad_rows": n}`(`crypto_v2.convert` 와 같은 꼴). 위반 줄도 지우지 않는다."""
    return crypto_v2.convert(parse_zip(data, symbol, expected_sha256=expected_sha256), interval, fetched_at)


def partition_path(root: Path, interval: str, year: int, symbol: str) -> Path:
    """적재 경로 — 잘게(1 ~ 30분): `ohlcv/timeframe=<주기>/market=BINANCE_SPOT_USDT/year=<해>/symbol=<종목>.parquet` ·
    거친 주기(1시간 이상): `ohlcv/timeframe=<주기>/market=BINANCE_SPOT_USDT/symbol=<종목>.parquet`(해 폴더 없음 · `year` 는 무시).
    파일 수 = 잘게 5 × 종목 × 해 + 거칠게 10 × 종목 — 어떤 폴더도 종목 수(757) 안팎이라 HF 폴더당 1만 · 저장소당 10만 개 아래(계약 3.3절)."""
    if interval not in INTERVALS:
        raise ValueError(f"받지 않는 주기: {interval!r}")
    base = Path(root) / "ohlcv" / f"timeframe={interval}" / f"market={crypto_v2.VENUE}"
    if interval in COARSE:
        return base / f"symbol={symbol}.parquet"
    return base / f"year={year:04d}" / f"symbol={symbol}.parquet"


def month_range(first: Tuple[int, int], last: Tuple[int, int]) -> List[Tuple[int, int]]:
    """(해, 달) 첫 달 ~ 끝 달(포함) 목록 — 처음이 끝보다 뒤면 `ValueError`."""
    (y, m), (ly, lm) = first, last
    if (y, m) > (ly, lm):
        raise ValueError(f"기간이 거꾸로다: {first} > {last}")
    out = []
    while (y, m) <= (ly, lm):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out
