"""그림자 일지 ↔ KIS 모의 체결 대사 — 읽기 전용 조회 + 별도 대사 스냅샷 추가."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys


async def _daily(lookback_days: int) -> dict:
    from app.database.postgres import close_postgres, connect_postgres, get_session_factory
    from app.services.paper_kis_reconciliation import run_daily

    await connect_postgres()
    try:
        async with get_session_factory()() as db:
            return await run_daily(db, lookback_days=lookback_days)
    finally:
        await close_postgres()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    daily = sub.add_parser("daily", help="최근 KIS 시험 실행 대사")
    daily.add_argument("--lookback-days", type=int, default=30)
    daily.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    try:
        result = asyncio.run(_daily(args.lookback_days))
    except Exception as exc:
        print(f"Paper↔KIS 대사 실패: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
