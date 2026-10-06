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
from app.lib.session import COOKIE_NAME, SessionCookieRefreshMiddleware
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
        # 용어사전(2026-09-30) — 넣을 내용(용어 파일 · 검색용 칸)이 마지막 적재와 다를 때만 표에 다시 넣는다.
        # 실패해도 앱은 켠다: 용어 API 만 빈다. 화면의 용어 설명창은 자바스크립트 상수(js/core.js 의 TERMS)를 쓰므로 그대로 뜬다.
        from app.services.glossary import ensure_loaded_on_startup
        info = await ensure_loaded_on_startup()
        print(f"[fin-agent] 용어사전 {info['status']} — 용어 {info['terms']} · 이름 {info['aliases']} · 판 {info['checksum'][:12]}")
    except Exception as e:
        print(f"[WARN] 용어사전 적재 실패 (용어 API 가 빈다): {e}")
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

# 세션 슬라이딩 만료: 서버 TTL 이 연장된 요청의 응답에 세션 쿠키를 다시 실어 브라우저 쿠키 만료도 연장한다.
app.add_middleware(SessionCookieRefreshMiddleware)


class StaticNoCacheMiddleware:
    """프런트 정적 파일(/js, /css, *.html)에 Cache-Control: no-cache 를 붙이는 순수 ASGI 미들웨어.

    StaticFiles 는 Cache-Control 을 보내지 않아 브라우저가 휴리스틱 캐시로 옛 common.js 를 재사용하고,
    새 HTML 이 옛 모듈을 import 해 "does not provide an export named ..." SyntaxError 가 난다.
    no-cache 는 매번 ETag 로 재검증(304)하므로 배포 직후에도 새 파일을 받는다.
    """

    _PREFIXES = ("/js/", "/css/")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not (path.startswith(self._PREFIXES) or path.endswith(".html") or path == "/"):
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                headers.append((b"cache-control", b"no-cache"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


app.add_middleware(StaticNoCacheMiddleware)

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
# 통합 대시보드 — 투자 사이트별 현재 투자액 탭
from app.routes import dashboard as dashboard_routes  # noqa: E402
app.include_router(dashboard_routes.router)
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
# 용어사전 (검색 · 분류 · 용어 한 건 — 로그인 없이 읽는다)
from app.routes import glossary as glossary_routes  # noqa: E402
app.include_router(glossary_routes.router)
# 개념 학습 (기본 교재는 로그인 없이 · 팀 자료는 HF 비공개 데이터셋 — docs/설계/개념학습-설계_v0.1.md)
from app.routes import learn as learn_routes  # noqa: E402
app.include_router(learn_routes.router)

# 금융 강의 (「금융 필수 지식」 › 강의실 · 주제 화면) — 강의 본문의 시세 그림이 부르는 주소. 저장 없이 보여 주기만 한다
from app.routes import lectures as lectures_routes  # noqa: E402
app.include_router(lectures_routes.router)

# 데이터 상태 · 거래일 달력 (목표 기능 ① W4) — 수집 DB 를 읽기만 한다. 달력 · 일정은 로그인 없이, 상태는 로그인 뒤
from app.routes import data as data_routes  # noqa: E402
app.include_router(data_routes.router)
from app.routes import calendar as calendar_routes  # noqa: E402
app.include_router(calendar_routes.router)
# 근거 문서 (목표 기능 ① W5) — 법령 · 감독규정 판 목록은 로그인 없이, 찾기(임베딩 호출)는 로그인 뒤
from app.routes import kb as kb_routes  # noqa: E402
app.include_router(kb_routes.router)

# 정적 파일 (프론트엔드)
_public = os.path.join(os.path.dirname(__file__), "..", "public")
if os.path.isdir(_public):
    # js · css 의 「바뀌었는지 매번 묻기」(no-cache)는 위 StaticNoCacheMiddleware 가 맡는다(강사님 기초 코드 289bfb5).
    # 2026-10-01 에 우리가 같은 일을 StaticFiles 덧씌우기(_Revalidate)로 했다가 같은 날 강사님 판이 나와 그쪽으로 합쳤다(DF-34).
    app.mount("/js", StaticFiles(directory=os.path.join(_public, "js")), name="js")
    app.mount("/css", StaticFiles(directory=os.path.join(_public, "css")), name="css")
    # 개념 학습 사이트 — app.html 과 다른 별도 HTML(/learn/). 기본 교재 읽기는 로그인 없이 된다(글 목록 · 본문은 /api/learn).
    # check_dir=False — 폴더가 앱보다 늦게 생겨도(개발 모드에서 파일을 막 만든 경우) 다시 켜지 않고 바로 열린다.
    class _RevalidateHtml(StaticFiles):
        """HTML 은 「바뀌었는지 매번 묻기」(no-cache) — 캐시 지시가 없으면 브라우저가 어림짐작으로 옛 화면을 보여 준다
        (2026-10-01 학습 사이트에서 확인). 바뀌지 않았으면 304 라 비용이 거의 없다. js · css 는 index.html 의 ?v= 로 바꾼다.
        StaticNoCacheMiddleware 는 「.html 로 끝나는 주소」 만 보므로 폴더 주소(/learn/)의 첫 화면은 여기서 맡는다."""

        async def get_response(self, path, scope):
            resp = await super().get_response(path, scope)
            if resp.headers.get("content-type", "").startswith("text/html"):
                resp.headers["Cache-Control"] = "no-cache"
            return resp

    app.mount("/learn", _RevalidateHtml(directory=os.path.join(_public, "learn"), html=True, check_dir=False), name="learn")
    # 금융 강의 본문 — 「금융 필수 지식」 의 주제 화면이 iframe 으로 싣는다. 파일은 scripts/lectures_build.py 가
    # 통합본 사본(rag-lab/)에서 만들어 둔다(손으로 고치지 않는다 — 빌드가 덮어쓴다).
    app.mount("/lectures", _RevalidateHtml(directory=os.path.join(_public, "lectures"), html=True, check_dir=False), name="lectures")
    # API 문서(2026-10-06 · 시스템관리 서랍) — /openapi.json 을 앱 디자인으로 그리고 Swagger UI 로 시험 호출하는 별도 HTML.
    # FastAPI 기본 /docs 와 같은 명세를 읽으므로 공개 범위도 같다(로그인 없이 열림 · 시험 호출은 그 사람의 쿠키로).
    app.mount("/api-docs", _RevalidateHtml(directory=os.path.join(_public, "api-docs"), html=True, check_dir=False), name="api-docs")

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
    async def index(fin_session: str | None = Cookie(default=None, alias=COOKIE_NAME)):
        return RedirectResponse(url="/app.html" if await _logged_in(fin_session) else "/login.html")

    @app.get("/login.html", include_in_schema=False)
    async def login_page(fin_session: str | None = Cookie(default=None, alias=COOKIE_NAME)):
        if await _logged_in(fin_session):
            return RedirectResponse(url="/app.html")
        return FileResponse(os.path.join(_public, "login.html"))

    @app.get("/register.html", include_in_schema=False)
    async def register_page(fin_session: str | None = Cookie(default=None, alias=COOKIE_NAME)):
        if await _logged_in(fin_session):
            return RedirectResponse(url="/app.html")
        return FileResponse(os.path.join(_public, "register.html"))

    @app.get("/app.html", include_in_schema=False)
    async def app_page(fin_session: str | None = Cookie(default=None, alias=COOKIE_NAME)):
        # 로그인 안 한 사람은 앱 화면을 받기 전에 로그인 화면으로 — 앱을 그렸다가 튕기는 깜빡임을 없앤다.
        if not await _logged_in(fin_session):
            return RedirectResponse(url="/login.html")
        return FileResponse(os.path.join(_public, "app.html"))
