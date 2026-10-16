"""T2 신호를 Yahoo 시세로 즉석 계산 — market.sqlite3 없이 돌리는 임시판.

배경:
- signals_daily.py 는 SQLite(data/collector/market.sqlite3) 를 읽는데, 이 파일이 없는 환경이 있다.
- 이 스크립트는 자동매매와 같은 소스(Yahoo via stock.get_candles) 로 봉을 받아
  patterns.timeframe_score + mtf_signals.combine 으로 신호를 계산해 signal_snapshots 에 넣는다.
- 대상은 자동매매 유니버스(QUANT_STOCKS 31종목) 뿐이다. 401종목 전체는 정식 경로(#142)를 쓴다.

사용:
    python scripts/signals_yahoo.py                    # 오늘 · 31종목
    python scripts/signals_yahoo.py --date 2026-10-14  # 특정일
    python scripts/signals_yahoo.py --symbols 005930.KS,035420.KS
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import postgres as pg
from app.models.signal import SignalSnapshot
from app.services import opinion as opinion_svc
from app.services import mtf_signals as ms
from app.services import stock
from app.services.data_ohlcv import weekly as build_weekly
from app.services.patterns import timeframe_score
from app.services.ta_utils import DEFINITION


def _to_weekly_input(candles: list[dict]) -> list[dict]:
    """야후 원본(time 유닉스초) → weekly()가 원하는 꼴(trade_date 추가)."""
    out = []
    for c in candles:
        t = c.get("time") or c.get("timestamp") or c.get("t")
        if t is None:
            continue
        try:
            ts = float(t)
        except (TypeError, ValueError):
            continue
        if ts > 10_000_000_000:
            ts /= 1000.0
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        out.append({
            "trade_date": d,
            "open": c.get("open"),
            "high": c.get("high"),
            "low": c.get("low"),
            "close": c.get("close"),
            "volume": c.get("volume") or 0,
            "value": c.get("value"),
            "timeframe": "1d",
        })
    out.sort(key=lambda r: r["trade_date"])
    return out


async def compute_one(sym: str, as_of: date) -> dict | None:
    """한 종목 → T2 한 줄. 실패는 {'error': ...} 로."""
    try:
        daily_raw = (await stock.get_candles(sym, period="1y", interval="1d")).get("candles", [])
    except Exception as e:
        return {"error": f"daily fetch: {e}"}
    try:
        intra_raw = (await stock.get_candles(sym, period="1mo", interval="60m")).get("candles", [])
    except Exception as e:
        intra_raw = []
        print(f"  60분봉 실패(무시): {e}")

    if len(daily_raw) < 35:
        return {"error": f"일봉 부족({len(daily_raw)})"}

    # daily_raw 는 야후 원본 그대로 (time 유닉스초) — timeframe_score 에 그대로 넣는다
    weekly_input = _to_weekly_input(daily_raw)  # weekly() 용
    weekly_bars, _partial = build_weekly(weekly_input, as_of.isoformat())

    # ★ weekly() 결과에 time(유닉스초) 필드 추가 — preprocess 가 요구함
    for bar in weekly_bars:
        d = date.fromisoformat(bar["trade_date"])
        bar["time"] = int(
            datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()
        )

    r_60m = timeframe_score(intra_raw) if len(intra_raw) >= 35 else {"error": f"60분봉 부족({len(intra_raw)})"}
    r_1d = timeframe_score(daily_raw)
    r_1w = timeframe_score(weekly_bars)

    results = []
    for tf, label, weight, r in (
        ("60m", "분봉(60분)", 0.2, r_60m),
        ("1d", "일봉", 0.5, r_1d),
        ("1w", "주봉", 0.3, r_1w),
    ):
        item = {"timeframe": tf, "label": label, "weight": weight}
        if "score" in r:
            item.update(r)
        else:
            item["error"] = r.get("error", "계산 실패")
        results.append(item)

    combo = ms.combine(results)

    reasons: list[str] = []
    for r in results:
        reasons.extend(r.get("reasons") or [])

    # P01-④-2 — opinion · opinion_rule (미보유 가정 · 이슈 #199)
    op, op_rule = opinion_svc.decide(
        combo["signal"],
        float(combo["confidence"]),
        held=False,
        risk_gate=False,
    )
    return {
        "as_of": as_of,
        "symbol": sym.replace(".KS", "").replace(".KQ", ""),
        "definition": DEFINITION,
        "signal": combo["signal"],
        "strength": combo.get("strength"),
        "confidence": float(combo["confidence"]),
        "composite": float(combo["composite"]),
        "agreement": float(combo.get("agreement", 0.0)),
        "timeframes": results,
        "pattern_bias": None,
        "patterns": None,
        "reasons": reasons,
        "opinion": op,
        "opinion_rule": op_rule,
        "computed_at": datetime.now(timezone.utc),
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (기본 오늘)")
    ap.add_argument("--symbols", default=None, help="쉼표 구분, 기본 QUANT_STOCKS 31종목")
    args = ap.parse_args()

    as_of = date.fromisoformat(args.date) if args.date else date.today()
    if args.symbols:
        targets = [(s.strip(), s.strip()) for s in args.symbols.split(",") if s.strip()]
    else:
        targets = [(s["symbol"], s["name"]) for s in stock.QUANT_STOCKS]

    # ★ DB 연결 초기화 (이게 빠져 있었음)
    await pg.connect_postgres()

    factory = pg.get_session_factory()
    ok = err = 0
    async with factory() as db:
        for sym, name in targets:
            result = await compute_one(sym, as_of)
            if result is None:
                continue
            if "error" in result:
                print(f"[SKIP] {sym} {name}: {result['error']}")
                err += 1
                continue

            stmt = pg_insert(SignalSnapshot).values(**result)
            stmt = stmt.on_conflict_do_update(
                index_elements=["as_of", "symbol", "definition"],
                set_={
                    k: getattr(stmt.excluded, k) for k in (
                        "signal", "strength", "confidence", "composite", "agreement",
                        "timeframes", "pattern_bias", "patterns", "reasons",
                        "opinion", "opinion_rule",
                        "computed_at",
                    )
                },
            )
            await db.execute(stmt)
            await db.commit()
            print(f"[OK] {sym} {name}: {result['signal']} {result['strength'] or ''} "
                  f"composite={result['composite']:+.2f} conf={result['confidence']:.2f}")
            ok += 1

    await pg.close_postgres()
    print(f"\n완료: ok={ok} skip={err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))