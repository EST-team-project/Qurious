"""판 2 QUANT 가상 실행. 기본은 읽기만, --execute는 판단과 가상 장부를 기록한다."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database.postgres import connect_postgres, close_postgres
from app.lib.redis_cache import connect_redis, close_redis
from app.services.strategy_v2_execution import run


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', required=True, type=uuid.UUID)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    await connect_postgres()
    await connect_redis()
    try:
        result = await run(args.user_id, execute=args.execute)
        print(json.dumps(result, ensure_ascii=False, default=str))
    finally:
        await close_redis()
        await close_postgres()


if __name__ == '__main__':
    asyncio.run(main())
