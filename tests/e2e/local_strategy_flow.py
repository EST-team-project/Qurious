"""실제 설정 화면 → 카드 저장/선택 API → 고유 PostgreSQL schema. 외부 시세·인증 없이 확인.

운영 계정/장부는 읽거나 쓰지 않는다. 시험 schema와 카드 폴더는 종료 시 제거한다.
"""
import argparse
from contextlib import asynccontextmanager
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://x:x@localhost/x')
os.environ.setdefault('REDIS_URL', 'redis://localhost:6379/0')

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import postgres  # noqa: E402
from app.lib.session import get_current_user  # noqa: E402
from app.models import Base, BrokerSettings, User  # noqa: E402
from app.routes import indicator_strategy, stocks  # noqa: E402
from app.services import local_strategy  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--chrome', required=True)
parser.add_argument('--profile', required=True)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--port', type=int, default=18964)
parser.add_argument('--browser-host', default='localhost')
parser.add_argument('--bind', default='127.0.0.1')
args = parser.parse_args()
url = os.environ['QURIOUS_TEST_DATABASE_URL']
assert 'test' in url and ':55439/' in url, '격리 시험 DB만 허용'
uid = uuid.uuid4()
schema = 'local_flow_' + uid.hex
user = {'id': str(uid), 'client_id': uid.hex, 'role': 'user'}
factory = None
settings.STRATEGY_SPEC_SOURCE = 'remote'
settings.DOMAIN_RAG_LAB_BASE_URL = ''
settings.DOMAIN_RAG_LAB_API_KEY = ''
local_strategy.market_for = lambda code: 'KOSPI'  # 시세 저장소만 대체; 실제 장부 시험은 pytest


@asynccontextmanager
async def lifespan(app):
    global factory
    engine = create_async_engine(url, execution_options={'schema_translate_map': {None: schema}})
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA {schema}'))
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add(User(id=uid, name='local-flow', email=f'{uid}@test.local', password_hash='x', client_id=uid.hex))
        await db.commit()
    with tempfile.TemporaryDirectory(prefix='qurious-local-cards-') as cards:
        os.environ['STRATEGY_CARD_DIR'] = cards
        try:
            yield
        finally:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            await engine.dispose()


async def session():
    async with factory() as db:
        yield db


async def no_audit(*args, **kwargs):
    pass


stocks.audit = no_audit
app = FastAPI(lifespan=lifespan)
app.dependency_overrides[postgres.get_pg_session] = session
app.dependency_overrides[get_current_user] = lambda: user
app.include_router(indicator_strategy.router)
app.include_router(stocks.router)


@app.get('/local-flow-test')
async def page():
    source = (ROOT / 'public/app.html').read_text()
    source = re.sub(r'<script\b[^>]*>.*?</script>', '', source, flags=re.S)
    source = source.replace('</head>', '<meta http-equiv="Content-Security-Policy" content="default-src \'self\' \'unsafe-inline\' data:; connect-src \'self\';"></head>')
    source = source.replace('</body>', '<script type="module">' + (ROOT / 'tests/e2e/local_strategy_flow.js').read_text() + '</script></body>')
    return HTMLResponse(source)


@app.get('/api/auto-trade/status')
async def status():
    async with factory() as db:
        enabled = await db.scalar(select(BrokerSettings.quant_auto_enabled).where(BrokerSettings.user_id == uid))
    return {'running': bool(enabled), 'log': [], 'interval_sec': 600}


app.mount('/', StaticFiles(directory=ROOT / 'public'))
server = uvicorn.Server(uvicorn.Config(app, host=args.bind, port=args.port, log_level='error'))
thread = threading.Thread(target=server.run, daemon=True)
thread.start()
try:
    for _ in range(100):
        if server.started:
            break
        time.sleep(.1)
    assert server.started
    args.out.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([args.chrome, '--headless=new', '--disable-gpu', '--no-first-run',
        '--no-default-browser-check', '--user-data-dir=' + args.profile,
        '--virtual-time-budget=25000', '--dump-dom',
        f'http://{args.browser_host}:{args.port}/local-flow-test'], capture_output=True, timeout=55)
    (args.out / 'browser-dom.html').write_bytes(proc.stdout)
    (args.out / 'browser-stderr.log').write_bytes(proc.stderr)
    match = re.search(r'<pre id="local-flow-result">(.*?)</pre>', proc.stdout.decode(errors='replace'), re.S)
    assert match, '브라우저 결과 없음; evidence 확인'
    result = json.loads(html.unescape(match[1]))
    (args.out / 'browser-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))
    assert result['ok']
finally:
    server.should_exit = True
    thread.join(timeout=10)
