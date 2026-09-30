"""금융 AI Agent - FastAPI 메인 엔트리포인트."""
import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import Cookie, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig

from app.database.postgres import connect_postgres, close_postgres
from app.config import settings
from app.database.neo4j import connect_neo4j, close_neo4j, ensure_graph_schema
from app.lib.redis_cache import connect_redis, close_redis
from app.routes import auth, health, chat, stocks, library, admin, system, quant, ml, macro, documents, notification, graph, conversations, tasks, ingest, paper, openapi, lean
from app.services.graph_service import seed_graph
from app.services.sync_scheduler import start_sync_scheduler, stop_sync_scheduler


def _run_migrations() -> None:
    """PostgreSQL 스키마를 최신 Alembic revision으로 맞춘다 (Mongo ensure_indexes()의 후신)."""
    root = os.path.join(os.path.dirname(__file__), "..")
    cfg = AlembicConfig(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    alembic_command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작
    try:
        await connect_redis()
    except Exception as e:
        print(f"[WARN] Redis 연결 실패 (세션 비활성): {e}")
    try:
        # alembic의 command.upgrade()는 내부적으로 asyncio.run()을 새로 여는데,
        # 이미 실행 중인 uvicorn 이벤트 루프 안에서 그대로 부르면 충돌한다.
        # 별도 스레드에서 돌려 독립된 루프를 갖게 한다.
        if settings.RUN_MIGRATIONS_ON_STARTUP:
            await asyncio.get_event_loop().run_in_executor(None, _run_migrations)
        else:
            print("[fin-agent] RUN_MIGRATIONS_ON_STARTUP=false — 마이그레이션은 scripts/migrate.sh 로 별도 실행")
    except Exception as e:
        # 마이그레이션이 실패해도 DB 연결은 한다(2026-09-30). 예전에는 연결과 같은 try 안이라, 예컨대 다른 브랜치에서
        # 올린 revision 이 DB 에 있어 이 코드가 그 revision 을 모르면(「Can't locate revision」) 연결까지 건너뛰어
        # 로그인 · 주문이 모두 503 이 됐다. 스키마는 그대로 두고, 원인은 이 줄로 남긴다.
        print(f"[WARN] DB 마이그레이션 실패 — 스키마를 바꾸지 않고 연결만 한다: {e}")
    try:
        await connect_postgres()
    except Exception as e:
        print(f"[WARN] PostgreSQL 연결 실패 (인증 비활성): {e}")
    try:
        await connect_neo4j()
        await ensure_graph_schema()
        await seed_graph()
        print("[fin-agent] Neo4j 연결 및 그래프 시드 완료")
    except Exception as e:
        print(f"[WARN] Neo4j 연결 실패 (그래프 기능 비활성): {e}")
    start_sync_scheduler()
    print("[fin-agent] 서버 시작 완료. JWT + PostgreSQL + 대화이력 기능 활성화")
    yield
    # 종료
    stop_sync_scheduler()
    await close_redis()
    await close_postgres()
    await close_neo4j()


app = FastAPI(
    title="금융 AI Agent",
    description="개인/기업 CB 분석 · 금융상품 · 주가 · 퀀트 자동매매",
    version="1.0.0",
    lifespan=lifespan,
)

# 라우터 등록
# auth/ingest도 메인 앱에 함께 등록한다 (강사님 원본의 Lambda 분리 배포는 AWS 제거로 뺐다).
app.include_router(auth.router)
app.include_router(ingest.router)
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(stocks.router)
app.include_router(library.router)
app.include_router(admin.router)
app.include_router(system.router)
app.include_router(quant.router)
app.include_router(ml.router)
app.include_router(macro.router)
app.include_router(documents.router)
app.include_router(notification.router)
app.include_router(graph.router)
app.include_router(conversations.router)
app.include_router(tasks.router)
# 모의투자(주식·코인·대체자산) + Open API 키 — stock-coin-trade 이식
app.include_router(paper.router)
app.include_router(openapi.router)
# QuantConnect LEAN 백테스트 — domain-rag-lab 이식
app.include_router(lean.router)
# 리밸런싱 엔진 (시간·이탈률·현금흐름 트리거)
from app.routes import rebalance as rebalance_routes  # noqa: E402
app.include_router(rebalance_routes.router)
# TradingView Webhook 수신 + Strategy Tester↔LEAN 교차 검증
from app.routes import tradingview as tradingview_routes  # noqa: E402
app.include_router(tradingview_routes.router)
# 자유 산식 커스텀 지표 (DSL · 버전 · 결과 저장)
from app.routes import formula as formula_routes  # noqa: E402
app.include_router(formula_routes.router)

# 정적 파일 (프론트엔드)
_public = os.path.join(os.path.dirname(__file__), "..", "public")
if os.path.isdir(_public):
    app.mount("/js", StaticFiles(directory=os.path.join(_public, "js")), name="js")
    app.mount("/css", StaticFiles(directory=os.path.join(_public, "css")), name="css")

    async def _logged_in(fin_session: str | None) -> bool:
        """쿠키의 세션이 Redis 에 살아 있나 — 화면 주소를 고를 때만 쓴다(Redis 가 안 되면 로그인 안 됨으로)."""
        if not fin_session:
            return False
        try:
            from app.lib.session import get_session
            return bool(await get_session(fin_session))
        except Exception:
            return False

    # 첫 주소 · 로그인 · 가입 화면은 **로그인 상태를 보고** 갈 곳을 고른다. 예전에는 `/` 가 늘 로그인 화면으로
    # 보내서, 세션(7일)이 살아 있는데도 주소를 다시 열거나 뒤로가기를 하면 로그아웃된 것처럼 보였다.
    @app.get("/", include_in_schema=False)
    async def index(fin_session: str | None = Cookie(default=None)):
        return RedirectResponse(url="/app.html" if await _logged_in(fin_session) else "/login.html")

    @app.get("/login.html", include_in_schema=False)
    async def login_page(fin_session: str | None = Cookie(default=None)):
        if await _logged_in(fin_session):
            return RedirectResponse(url="/app.html")
        return FileResponse(os.path.join(_public, "login.html"))

    @app.get("/register.html", include_in_schema=False)
    async def register_page(fin_session: str | None = Cookie(default=None)):
        if await _logged_in(fin_session):
            return RedirectResponse(url="/app.html")
        return FileResponse(os.path.join(_public, "register.html"))

    @app.get("/app.html", include_in_schema=False)
    async def app_page(fin_session: str | None = Cookie(default=None)):
        # 로그인 안 한 사람은 앱 화면을 받기 전에 로그인 화면으로 — 앱을 그렸다가 튕기는 깜빡임을 없앤다.
        if not await _logged_in(fin_session):
            return RedirectResponse(url="/login.html")
        return FileResponse(os.path.join(_public, "app.html"))
