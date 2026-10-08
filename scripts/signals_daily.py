"""다중 주기 신호를 거래일마다 T2 `signal_snapshots` 에 기록한다 (목표 기능 ② 설계서 5.3 · 6절 · `P01-②-3`).

규칙 · 정의는 [`app/services/mtf_signals.py`](../app/services/mtf_signals.py) 에 있다. 이 파일은 대상 401종목(분봉 유니버스
`u2-20260930`) × 거래일을 돌며 계산하고 앱 DB(`.env` 의 `DATABASE_URL`)에 쓴다. 같은 날 · 같은 정의 판을 다시 돌리면
그 줄을 새 값으로 바꾼다(여러 번 돌려도 안전하다).

    python scripts/signals_daily.py                                  # 수집 DB 의 마지막 거래일 하루
    python scripts/signals_daily.py --date 2026-08-31                 # 그날 하루
    python scripts/signals_daily.py --from 2026-08-03 --to 2026-08-31 # 기간(지난날 채우기)
    python scripts/signals_daily.py --date 2026-08-31 --dry-run       # DB 에 쓰지 않고 요약만

일일 러너에 단계로 붙이는 일은 러너 담당(목표 기능 ① · 일봉 · 분봉 갱신 단계 뒤)이 한다. 앱 DB 가 꺼져 있으면 종료코드 3.
날짜를 주지 않으면 그날의 운영 기록이다. 기록을 분석 · 검증에 쓸 때는 봉인 구간(2026-09-01 ~ · 설계서 3.2)을 빼고 읽는다.
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


def _one(args: tuple[str, list[str]]) -> tuple[str, list[dict], str | None]:
    symbol, days = args
    try:
        bars = ms.load_bars(symbol, days[0], days[-1])
        return symbol, [r for d in days if (r := ms.signal_at(bars, d)) is not None], None
    except Exception as e:  # 한 종목이 실패해도 나머지는 기록한다
        return symbol, [], f"{type(e).__name__}: {str(e)[:120]}"


async def _write(records: list[dict], batch: int = 500) -> int:
    from app.database.postgres import close_postgres, connect_postgres, get_session_factory

    await connect_postgres()
    try:
        n = 0
        async with get_session_factory()() as session:
            for i in range(0, len(records), batch):
                n += await ms.write_snapshots(session, records[i:i + batch])
        return n
    finally:
        await close_postgres()


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
    ap.add_argument("--dry-run", action="store_true", help="DB 에 쓰지 않는다")
    ap.add_argument("--json", type=Path, help="요약을 JSON 으로도 쓴다")
    a = ap.parse_args(argv)

    if a.start or a.end:
        if not (a.start and a.end):
            print("--from 과 --to 를 함께 준다")
            return 2
        days = ms.trading_days(a.start, a.end)
    else:
        d = a.date or date.today().isoformat()
        days = ms.trading_days((date.fromisoformat(d) - timedelta(days=14)).isoformat(), d)
        days = days[-1:] if not a.date else [x for x in days if x == d]
    if not days:
        print("그 기간에 거래일(시세가 있는 날)이 없다")
        return 2
    symbols = ms.universe()
    if a.limit:
        symbols = symbols[:a.limit]

    t0 = time.time()
    records, errors = [], {}
    with ProcessPoolExecutor(a.workers) as ex:
        for symbol, recs, err in ex.map(_one, ((s, days) for s in symbols)):
            records.extend(recs)
            if err:
                errors[symbol] = err
    by_day = Counter(r["as_of"].isoformat() for r in records)
    sig = Counter(r["signal"] for r in records)
    print(f"계산 — {days[0]} ~ {days[-1]} 거래일 {len(days)} · 종목 {len(symbols)} · 줄 {len(records):,} · "
          f"오류 {len(errors)} · {time.time() - t0:.0f}초")
    print(f"  신호 — {' · '.join(f'{k} {v:,}' for k, v in sig.most_common())} · 정의 판 {ms.DEFINITION}")
    short = {d: len(symbols) - by_day.get(d, 0) for d in days if by_day.get(d, 0) < len(symbols)}
    if short:
        print(f"  그날 시세가 없어 빠진 종목(상장 전 · 거래정지 등) — " + " · ".join(f"{d} {n}" for d, n in short.items()))
    for s, e in list(errors.items())[:5]:
        print(f"  [오류] {s} {e}")

    written = 0
    if not a.dry_run:
        try:
            written = asyncio.run(_write(records))
        except (OSError, ConnectionError) as e:
            print(f"[실패] 앱 DB 에 연결하지 못했다 — 앱 DB(PostgreSQL)가 떠 있는지 본다 ({type(e).__name__})")
            return 3
        print(f"  기록 — signal_snapshots {written:,}줄(같은 날 · 같은 판은 새 값으로 바꿈)")
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps({"days": days, "symbols": len(symbols), "rows": len(records), "written": written,
                                      "by_day": by_day, "signals": sig, "errors": errors,
                                      "definition": ms.DEFINITION}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if errors and not records else 0


if __name__ == "__main__":
    raise SystemExit(main())
