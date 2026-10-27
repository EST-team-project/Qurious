"""자동매매를 켜지 않고 판 1 고정 카드의 KIS 모의 경로를 한 번 점검한다."""
import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.postgres import connect_postgres, close_postgres, get_session_factory
from app.services.kis_strategy_probe import run


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True, type=uuid.UUID)
    parser.add_argument("--card", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="판단 기록과 최대 1주 모의 주문. 기본은 조회만.")
    args = parser.parse_args()
    spec = json.loads(args.card.read_text(encoding="utf-8"))
    await connect_postgres()
    try:
        async with get_session_factory()() as db:
            result = await run(db, args.user_id, spec, execute=args.execute)
    finally:
        await close_postgres()
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())
