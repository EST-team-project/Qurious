"""현재 active 키로 알림 설정의 비밀 9칸을 재암호화한다. 기존 키를 함께 둔 키 파일이 필요하다.

증권사 표(`scripts/rotate_broker_credentials.py`)와 **같은 키 파일**을 쓰므로 키를 교체할 때는 두 스크립트를 모두 돌린 뒤에
옛 키를 키 파일에서 지운다. 이 스크립트가 빠지면 옛 키를 지우는 순간 알림 칸이 모두 복호화되지 않아 발송이 멈춘다.
전체 변환·검증 성공 또는 전체 rollback이다(docs/phase-3/05-deployment/알림-비밀값-암호화-운영.md).
"""
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database.postgres import connect_postgres, close_postgres, get_session_factory
from app.lib.notification_secrets import reencrypt


async def main():
    for stream in (sys.stdout, sys.stderr):   # 윈도우 cp949 콘솔에서 안내 글의 줄표(—)가 깨지지 않게(시험 TC-CE · 다른 scripts 진입점과 같은 세 줄)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    await connect_postgres()
    try:
        async with get_session_factory()() as db:
            async with db.begin():
                connection = await db.connection()
                result = await connection.run_sync(reencrypt)
        print(json.dumps({"notification": result}))
        print("증권사 표도 같은 키를 쓴다 — scripts/rotate_broker_credentials.py 를 아직 돌리지 않았다면 옛 키를 지우기 전에 돌린다.", file=sys.stderr)
    finally:
        await close_postgres()


if __name__ == "__main__":
    asyncio.run(main())
