"""현재 active 키로 저장 자격증명을 재암호화한다. 기존 키를 함께 둔 키 파일이 필요하다."""
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database.postgres import connect_postgres, close_postgres, get_session_factory
from app.lib.broker_secrets import reencrypt


async def main():
    await connect_postgres()
    try:
        async with get_session_factory()() as db:
            async with db.begin():
                connection = await db.connection()
                result = await connection.run_sync(reencrypt)
        print(json.dumps(result))
    finally:
        await close_postgres()


if __name__ == "__main__":
    asyncio.run(main())
