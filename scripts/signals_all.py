"""분봉 유니버스 밖 전체 종목(KOSPI · KOSDAQ · ETF)의 다중 주기 신호를 거래일마다 T2 `signal_snapshots` 에 기록한다
(할 일 `②-32` · 설계 `docs/phase-3/02-design/system/신호-전체종목-기록-설계.md`).

기존 `scripts/signals_daily.py`(분봉 유니버스 401종목)는 그대로 두고, 이 파일이 **그 밖의 종목**만 맡는다. 계산 · 기록 함수는
신호 배치(`mtf_signals` · `signals_daily`)의 것을 부르기만 한다 — 지표 정의(`tv-2026`)도 같다.

    python scripts/signals_all.py                                  # 수집 DB 의 마지막 거래일 하루
    python scripts/signals_all.py --date 2026-10-30                 # 그날 하루
    python scripts/signals_all.py --from 2026-10-27 --to 2026-10-30 # 기간(5거래일까지)
    python scripts/signals_all.py --date 2026-10-30 --dry-run       # DB 에 쓰지 않고 요약만

대상: 그날 `price_daily` 의 KOSPI · KOSDAQ 종목(우선주 포함 · KONEX 제외) + 그날 `etf_daily` 의 ETF − 분봉 유니버스.
분봉이 없는 종목은 일봉 · 주봉만으로 계산한다(`combine` 이 쓸 수 있는 주기의 가중치로 다시 나눈다) — 그 사실은 `timeframes` 의
60분 항목 `error` 로 남는다(새 칸 없음).

지난날 채우기는 하지 않는다(기록은 그날의 운영 기록). 기간은 5거래일까지만 받는다.
보존: 이 종목들의 줄은 최근 `--keep-days`(기본 120)거래일만 둔다 — 끝에서 오래된 줄을 지운다(0 = 지우지 않음).
앱 DB 에 닿지 못하면 계산하기 전에 멈추고 종료코드 3. `--dry-run` 은 DB 를 보지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import mtf_signals as ms  # noqa: E402
from app.services.signal_targets import targets  # noqa: E402  (대상 목록은 앱과 같은 규칙 — 2026-11-02 #487 로 app/services 로 옮김)
from scripts import signals_daily as sd  # noqa: E402

KEEP_DAYS = 120                        # 분봉 유니버스 밖 종목의 보존 거래일 수
MAX_DAYS = 5                           # 한 번에 받는 기간 — 3,500종목 × 여러 날이 제한 시간을 넘기지 않게


def without_intraday(records: list[dict]) -> int:
    """60분 주기가 비어(분봉 없음) 일봉 · 주봉만으로 계산된 줄 수."""
    return sum(1 for r in records
               if any(t.get("timeframe") == "60m" and "error" in t for t in r.get("timeframes") or []))


def cutoff_day(last_day: str, keep_days: int, *, path: Path | None = None) -> str | None:
    """보존할 가장 오래된 거래일 — 이보다 앞 줄을 지운다. 거래일이 `keep_days` 보다 적으면 None(지우지 않는다)."""
    if keep_days <= 0:
        return None
    start = (date.fromisoformat(last_day) - timedelta(days=int(keep_days * 1.6) + 10)).isoformat()
    all_days = ms.trading_days(start, last_day, path=path)
    return all_days[-keep_days] if len(all_days) >= keep_days else None


async def _prune(cutoff: str, inside: list[str]) -> int:
    from sqlalchemy import delete

    from app.database.postgres import close_postgres, connect_postgres, get_session_factory
    from app.models.signal import SignalSnapshot as S
    from app.services.ta_utils import DEFINITION

    await connect_postgres()
    try:
        async with get_session_factory()() as session:
            res = await session.execute(delete(S).where(
                S.definition == DEFINITION, S.as_of < date.fromisoformat(cutoff), S.symbol.notin_(inside)))
            await session.commit()
            return res.rowcount or 0
    finally:
        await close_postgres()


def _days(a: argparse.Namespace) -> list[str]:
    if a.start or a.end:
        return ms.trading_days(a.start, a.end)
    d = a.date or date.today().isoformat()
    days = ms.trading_days((date.fromisoformat(d) - timedelta(days=14)).isoformat(), d)
    return days[-1:] if not a.date else [x for x in days if x == d]


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", help="그날 하루(YYYY-MM-DD) — 없으면 수집 DB 의 마지막 거래일")
    ap.add_argument("--from", dest="start", help="기간 시작(YYYY-MM-DD)")
    ap.add_argument("--to", dest="end", help="기간 끝(YYYY-MM-DD · 포함)")
    ap.add_argument("--limit", type=int, help="앞에서부터 이만큼 종목만")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--keep-days", type=int, default=KEEP_DAYS, help="이 종목들의 보존 거래일 수(0 = 지우지 않음)")
    ap.add_argument("--dry-run", action="store_true", help="DB 에 쓰지도 지우지도 않는다")
    ap.add_argument("--json", type=Path, help="요약을 JSON 으로도 쓴다")
    a = ap.parse_args(argv)

    if a.start or a.end:
        if not (a.start and a.end):
            print("--from 과 --to 를 함께 준다")
            return 2
    days = _days(a)
    if not days:
        print("그 기간에 거래일(시세가 있는 날)이 없다")
        return 2
    if len(days) > MAX_DAYS:
        print(f"기간이 {len(days)}거래일이다 — 한 번에 {MAX_DAYS}거래일까지만 받는다(제한 시간 · 지난날 채우기는 하지 않는다)")
        return 2
    symbols = targets(days)
    if a.limit:
        symbols = symbols[:a.limit]
    if not symbols:
        print("대상 종목이 없다(그날 KOSPI · KOSDAQ 시세 · ETF 일봉이 비었다)")
        return 2
    if not a.dry_run:
        try:
            asyncio.run(sd._check_db())
        except (OSError, ConnectionError) as e:
            return sd._db_down(e)

    t0 = time.time()
    records, errors = [], {}
    with ProcessPoolExecutor(a.workers) as ex:
        for symbol, recs, err in ex.map(sd._one, ((s, days) for s in symbols)):
            records.extend(recs)
            if err:
                errors[symbol] = err
    elapsed = time.time() - t0
    by_day = Counter(r["as_of"].isoformat() for r in records)
    sig = Counter(r["signal"] for r in records)
    no60 = without_intraday(records)
    print(f"계산 — {days[0]} ~ {days[-1]} 거래일 {len(days)} · 종목 {len(symbols):,} · 줄 {len(records):,} · "
          f"오류 {len(errors)} · {elapsed:.0f}초")
    print(f"  신호 — {' · '.join(f'{k} {v:,}' for k, v in sig.most_common())} · 정의 판 {ms.DEFINITION}")
    print(f"  분봉 없이 계산(일봉 · 주봉만) — {no60:,}줄 / {len(records):,}줄")
    short = {d: len(symbols) - by_day.get(d, 0) for d in days if by_day.get(d, 0) < len(symbols)}
    if short:
        print("  그날 시세가 없어 빠진 종목(상장 전 · 거래정지 · ETF 일봉이 아직 안 들어옴 등) — "
              + " · ".join(f"{d} {n:,}" for d, n in short.items()))
    for s, e in list(errors.items())[:5]:
        print(f"  [오류] {s} {e}")

    written = pruned = 0
    if not a.dry_run:
        try:
            written = asyncio.run(sd._write(records))
        except (OSError, ConnectionError) as e:  # 확인 뒤 계산하는 사이에 꺼진 경우
            return sd._db_down(e)
        print(f"  기록 — signal_snapshots {written:,}줄(같은 날 · 같은 판은 새 값으로 바꿈)")
        inside = ms.universe()
        cut = cutoff_day(days[-1], a.keep_days) if inside else None
        if cut:
            try:
                pruned = asyncio.run(_prune(cut, inside))
            except (OSError, ConnectionError) as e:
                return sd._db_down(e)
            print(f"  보존 — 분봉 유니버스 밖 종목은 {cut} 부터만 둔다(오래된 {pruned:,}줄 지움 · 보존 {a.keep_days}거래일)")
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps({"days": days, "symbols": len(symbols), "rows": len(records), "written": written,
                                      "pruned": pruned, "no_intraday": no60, "seconds": round(elapsed, 1),
                                      "by_day": by_day, "signals": sig, "errors": errors,
                                      "definition": ms.DEFINITION}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if errors and not records else 0


if __name__ == "__main__":
    raise SystemExit(main())
