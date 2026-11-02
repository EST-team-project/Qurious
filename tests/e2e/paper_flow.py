"""실제 HTML/JS→FastAPI→격리 PostgreSQL→알림 기록. 시세와 외부 전달만 합성.

QURIOUS_TEST_DATABASE_URL=... python tests/e2e/paper_flow.py --chrome ... --profile ... --out ...
고유 시험 schema를 만들고 제거한다. 운영 계정/주문/알림 채널을 사용하지 않는다.
"""
import argparse
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://x:x@localhost/x')
os.environ.setdefault('REDIS_URL', 'redis://localhost:6379/0')

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from app.database import postgres  # noqa: E402
from app.lib.jwt_auth import get_current_user_any  # noqa: E402
from app.lib.session import get_current_user  # noqa: E402
from app.models import Base, PaperAccount, User  # noqa: E402
from app.routes import paper, notification as notification_route  # noqa: E402
from app.services import paper_trading as pt, notification, paper_fill_notifications  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--chrome', required=True)
parser.add_argument('--profile', required=True)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--port', type=int, default=18962)
parser.add_argument('--browser-host', default='localhost')
parser.add_argument('--bind', default='127.0.0.1')
args = parser.parse_args()
url = os.environ['QURIOUS_TEST_DATABASE_URL']
assert 'test' in url and ':55439/' in url, '격리 시험 DB만 허용'
uid = uuid.uuid4()
schema = 'paper_flow_' + uid.hex
user = {'id': str(uid), 'client_id': uid.hex, 'role': 'user'}
factory = None
deliveries = []


@asynccontextmanager
async def lifespan(app):
    global factory
    engine = create_async_engine(url, execution_options={'schema_translate_map': {None: schema}})
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA {schema}'))
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    postgres.get_session_factory = lambda: factory
    paper_fill_notifications.get_session_factory = lambda: factory
    async with factory() as db:
        db.add(User(id=uid, name='flow', email=f'{uid}@test.local', password_hash='x', client_id=uid.hex))
        await db.flush()
        db.add(PaperAccount(user_id=uid, cash=1_000_000, initial_cash=1_000_000))
        await db.commit()
    try:
        yield
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        await engine.dispose()


async def session():
    async with factory() as db:
        yield db


async def quote(symbol):
    return {'symbol': '005930.KS', 'name': '시험', 'market': 'KOSPI', 'price': 10000,
            'currency': 'KRW', 'is_etf': False, 'market_open': True, 'quote_label': '합성 시험 시세'}


async def confirm(db, uid, info, **kwargs):
    return info


async def no_audit(*args, **kwargs):
    pass


async def settings(uid):
    return {'channels': ['discord']}


async def deliver(ev, cfg, channels, **kwargs):
    deliveries.append(ev.ref)
    return ['discord'], [True], [1]


pt.resolve_stock = pt.get_quote = quote
pt._confirm_quote = confirm
paper.audit = no_audit
notification._load_user_settings = settings
notification._deliver = deliver
app = FastAPI(lifespan=lifespan)
app.dependency_overrides[postgres.get_pg_session] = session
app.dependency_overrides[get_current_user_any] = lambda: user
app.dependency_overrides[get_current_user] = lambda: user
app.include_router(paper.router)
app.include_router(notification_route.router)


@app.get('/api/stock-hub')
async def hub(symbol: str):
    return {'symbol': '005930', 'name': '시험', 'sections': {}}


@app.get('/paper-flow-test')
async def page():
    source = (ROOT / 'public/app.html').read_text()
    source = re.sub(r'<script\b[^>]*>.*?</script>', '', source, flags=re.S)
    source = source.replace('</head>', '<meta http-equiv="Content-Security-Policy" content="default-src \'self\' \'unsafe-inline\' data:; connect-src \'self\';"><style>.view{display:none!important}[data-view="paper-stock"]{display:block!important}</style></head>')
    source = source.replace('</body>', '<script type="module">' + (ROOT / 'tests/e2e/paper_flow.js').read_text() + '</script></body>')
    return HTMLResponse(source)


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
                           f'http://{args.browser_host}:{args.port}/paper-flow-test'], capture_output=True, timeout=55)
    (args.out / 'browser-dom.html').write_bytes(proc.stdout)
    (args.out / 'browser-stderr.log').write_bytes(proc.stderr)
    match = re.search(r'<pre id="paper-flow-result">(.*?)</pre>', proc.stdout.decode('utf-8', errors='replace'), re.S)
    assert match, '브라우저 결과 없음; evidence 확인'
    result = json.loads(html.unescape(match[1]))
    result['synthetic_deliveries'] = len(deliveries)
    (args.out / 'browser-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))
    assert result['ok'] and len(deliveries) == 1
finally:
    server.should_exit = True
    thread.join(timeout=10)
