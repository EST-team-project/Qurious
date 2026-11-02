"""신호 전체 종목 기록(`signals_all`)의 대상 목록 — 배치 스크립트와 앱이 같은 규칙을 쓰도록 `app/services` 에 둔다.

이 파일은 `scripts/signals_all.py` 에 있던 `targets` 를 옮긴 것이다(신장환 님 #487 부탁 — 신호 순위·허브가
「기록이 없는 종목이 지금 대상에 드는가」 를 날짜가 아니라 이 목록으로 가르게). 규칙은 그대로다:

    대상 = 그날(들) `price_daily` 의 KOSPI · KOSDAQ 종목(우선주 포함 · KONEX 제외) + `etf_daily` 의 ETF − 분봉 유니버스

수집 DB 는 읽기 전용(`mode=ro`)으로만 연다. 앱 DB 는 보지 않는다.
"""
from __future__ import annotations

from pathlib import Path

from app.services import mtf_signals as ms

MARKETS = ("KOSPI", "KOSDAQ")          # KONEX 는 뺀다(거래가 적어 순위 비교가 의미 없다)


def targets(days: list[str], *, path: Path | None = None) -> list[str]:
    """`days` 가운데 하루라도 시세가 있는 KOSPI · KOSDAQ 종목과 ETF 에서 분봉 유니버스를 뺀 코드 — 주식 먼저, 코드 차례."""
    ymds = [d.replace("-", "") for d in days]
    conn = ms._connect(path)               # 읽기 전용 연결(mode=ro) — 다른 수집 읽기 함수와 같은 규칙
    try:
        day_marks = ",".join("?" * len(ymds))
        mk_marks = ",".join("?" * len(MARKETS))
        stocks = [r[0] for r in conn.execute(
            f"SELECT DISTINCT srtn_cd FROM price_daily WHERE bas_dt IN ({day_marks}) AND clpr > 0 "
            f"AND mrkt_ctg IN ({mk_marks}) ORDER BY srtn_cd", (*ymds, *MARKETS))]
        has_etf = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='etf_daily'").fetchone()
        etfs = [r[0] for r in conn.execute(
            f"SELECT DISTINCT srtn_cd FROM etf_daily WHERE bas_dt IN ({day_marks}) AND clpr > 0 ORDER BY srtn_cd",
            tuple(ymds))] if has_etf else []
    finally:
        conn.close()
    inside = set(ms.universe(path=path))
    out, seen = [], set()
    for code in stocks + etfs:                       # 같은 코드가 둘이면 주식을 먼저 본다
        if code not in inside and code not in seen:
            seen.add(code)
            out.append(code)
    return out
