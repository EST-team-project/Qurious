"""전략 신호와 분리한 삼성전자 1주 KIS 모의 매수 점검. 기본은 조회만 한다."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.postgres import connect_postgres, close_postgres
from app.lib.redis_cache import connect_redis, close_redis
from app.services.kis_connection_probe import run
from app.services.execution_control import Rejected


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True, type=uuid.UUID)
    parser.add_argument("--max-price", required=True, type=int, help="1주 지정가 상한(원)")
    parser.add_argument("--execute", action="store_true", help="실제 KIS 모의 지정가 매수 최대 1주 전송")
    args = parser.parse_args()
    await connect_postgres()
    try:
        await connect_redis()
        try:
            result = await run(args.user_id, max_price=args.max_price, execute=args.execute)
        except Rejected as exc:
            result = {"status": "BLOCKED", "code": exc.code, "reason": str(exc)}
        print(json.dumps(result, ensure_ascii=False))
    finally:
        await close_redis()
        await close_postgres()


if __name__ == "__main__":
    asyncio.run(main())
