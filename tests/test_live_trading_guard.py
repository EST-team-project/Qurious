"""실거래 주문 차단 관문 인수시험 (rfp-2 §4.2 · ADR-0001).

무엇을 지키는 시험인가 —
발주 요구사항의 제외 범위 첫 줄이 "실제 증권 계좌를 통한 실거래 자동 주문 실행"이다.
이 파일은 **승인 없이는 실계좌에 닿는 클라이언트가 만들어지지 않는다**는 것을
경로별로 확인한다. 코드가 아니라 요구사항을 지키는 시험이라, 리팩터링으로
구현이 바뀌어도 이 시험은 그대로 남아야 한다.

왜 `place_order` 를 부르지 않는가 —
실주문을 내지 않고 차단을 확인하는 것이 목적이다. 그래서 **어느 서버를 보고 있는지**
(`base_url`·`tr_id`)와 **어떤 클라이언트가 나왔는지**(타입)만 본다. 네트워크는 타지 않는다.
"""
import asyncio
import inspect
import json
from types import SimpleNamespace

import httpx
import pytest

from app.services.brokers import factory
from app.services.brokers.ebest import EBestClient
from app.services.brokers.kis import KISClient, PAPER_URL, REAL_URL
from app.services.brokers.mock import MockBrokerClient

# 이 시험에서 쓰는 가짜 자격증명. 비어 있으면 팩토리가 Mock 을 돌려주므로
# **차단이 아니라 자격증명 부재로** 통과해 버린다 — 그런 통과는 의미가 없다.
KEY = "dummy-app-key"
SECRET = "dummy-app-secret"


# ── 1. 관문 자체 ─────────────────────────────────────────────────────

def test_기본값은_실거래_미승인이다():
    """환경변수를 건드리지 않은 상태가 '막힌' 상태여야 한다."""
    assert factory.live_trading_allowed() is False


@pytest.mark.parametrize("값", ["1", "true", "TRUE", "yes", "on", " 1 "])
def test_승인값으로_읽는_문자열(monkeypatch, 값):
    monkeypatch.setenv(factory.LIVE_TRADING_ENV, 값)
    assert factory.live_trading_allowed() is True


@pytest.mark.parametrize("값", ["", "0", "false", "no", "off", "아니오", "2"])
def test_승인값이_아닌_문자열(monkeypatch, 값):
    """애매한 값은 전부 '막힘'으로 읽는다. 여는 쪽이 명시적이어야 한다."""
    monkeypatch.setenv(factory.LIVE_TRADING_ENV, 값)
    assert factory.live_trading_allowed() is False


# ── 2. paper 플래그로 막히는 브로커 (KIS) ────────────────────────────

def test_미승인이면_KIS의_paper_False_요청이_모의투자로_강등된다():
    """자동매매가 쓰던 경로다 — 예전에는 여기서 실전 URL 로 나갔다."""
    client = factory.get_broker_client("kis", KEY, SECRET, paper=False)
    assert isinstance(client, KISClient)
    assert client.paper is True
    assert client.base_url == PAPER_URL, "실전 URL 을 보고 있으면 차단이 새는 것이다"


def test_승인하면_KIS가_실전_URL을_본다(allow_live_trading):
    """차단이 '항상 막힘'이 아니라 '승인 시에만 열림'임을 확인한다.

    이 시험이 없으면, 관문이 아니라 기능이 죽어 있어도 위 시험은 통과한다.
    """
    client = factory.get_broker_client("kis", KEY, SECRET, paper=False)
    assert client.paper is False
    assert client.base_url == REAL_URL


def test_미승인이어도_paper_True_요청은_그대로다():
    """모의투자는 제외 범위가 아니다 — 막으면 프로젝트 목표(모의투자)가 죽는다."""
    client = factory.get_broker_client("kis", KEY, SECRET, paper=True)
    assert client.base_url == PAPER_URL


# ── 3. paper 플래그로 막을 수 없는 브로커 (ebest) ────────────────────

def test_미승인이면_ebest는_Mock으로_대체된다():
    """LS증권은 모의·실전이 같은 도메인이라 paper=True 로도 실서버에 닿는다.

    그래서 플래그가 아니라 **클라이언트 자체를** 갈아 끼워야 한다.
    """
    client = factory.get_broker_client("ebest", KEY, SECRET, paper=True)
    assert isinstance(client, MockBrokerClient)
    assert not isinstance(client, EBestClient)


def test_승인하면_ebest_실클라이언트가_나온다(allow_live_trading):
    client = factory.get_broker_client("ebest", KEY, SECRET, paper=False)
    assert isinstance(client, EBestClient)


# ── 4. 우회 경로 봉인 ────────────────────────────────────────────────

def test_자동매매는_팩토리를_거쳐서만_클라이언트를_만든다():
    """호출부가 클라이언트를 직접 생성하면 관문이 통째로 무력해진다.

    `auto_trade` 가 `KISClient(...)` 를 직접 부르는 순간 이 시험이 깨진다.
    """
    from app.services import auto_trade

    소스 = inspect.getsource(auto_trade)
    for 금지 in ("KISClient(", "EBestClient(", "KBClient("):
        assert 금지 not in 소스, f"auto_trade 가 {금지} 로 팩토리를 건너뛴다"


def test_저장소_어디에도_paper_False_하드코딩이_남아있지_않다():
    """`paper=False` 를 코드에 박아 두면, 관문을 지나더라도 의도가 남는다.

    팩토리가 강등하므로 당장 사고가 나지는 않는다. 그러나 다음 사람이
    관문을 손볼 때 이 코드를 '실계좌를 원하는 코드'로 읽는다 — 그 오해가 비싸다.

    관문 파일 자신(`factory.py`)은 제외한다. 무엇을 막는지 설명하려면
    그 문자열을 써야 하고, 거기서 쓰는 것은 하드코딩이 아니라 정의다.
    """
    from pathlib import Path

    루트 = Path(__file__).resolve().parents[1]
    관문 = 루트 / "app" / "services" / "brokers" / "factory.py"
    발견: list[str] = []
    for 파일 in (루트 / "app").rglob("*.py"):
        if "__pycache__" in 파일.parts or 파일 == 관문:
            continue
        for 번호, 줄 in enumerate(파일.read_text(encoding="utf-8").splitlines(), 1):
            if "paper=False" in 줄.replace(" ", "") and not 줄.lstrip().startswith("#"):
                발견.append(f"{파일.relative_to(루트).as_posix()}:{번호}")
    assert not 발견, "paper=False 하드코딩: " + ", ".join(발견)


# ── 5. 두 번째 출구 — stock-coin-trade 게이트웨이 (강사님 9478811) ─────
#
# 강사님 기초 코드 9478811 이 실주문의 길을 하나 더 냈다. 자동매매가 KIS 주문을 팩토리를 거치지 않고
# stock-coin-trade 서버(HTTP)로 보내고, 실전 · 모의는 환경값 한 줄(STOCK_COIN_TRADE_KIS_ENVIRONMENT)이
# 정한다. 3-way 병합에서 충돌 표시 없이 들어오는 길이라, 팩토리와 같은 승인 변수를 그 길에도 걸었다.
# 주문 · 잔고 · 주문 조회 · 취소가 모두 같은 환경 판정을 지나는지 서버 흉내(MockTransport)로 본다.


@pytest.fixture
def 게이트웨이(monkeypatch):
    """환경값을 일부러 real 로 둔 게이트웨이. 보낸 요청은 `요청들` 에 쌓인다(네트워크는 타지 않는다)."""
    from app.config import settings
    from app.services.brokers import stock_coin_trade_gateway as gw

    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_BASE_URL", "https://gateway.test")
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_API_KEY", "dummy-gateway-key")
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_KIS_ENVIRONMENT", "real")
    요청들: list[httpx.Request] = []

    def 서버(request: httpx.Request) -> httpx.Response:
        요청들.append(request)
        path = request.url.path
        if path == "/openapi/v1/kis/order-approval":
            return httpx.Response(200, json={"ok": True, "approvalToken": "tok-1"})
        if path == "/openapi/v1/kis/orders" and request.method == "POST":
            return httpx.Response(200, json={"ok": True, "order": {"orderNo": "1", "status": "ACCEPTED"}})
        if path == "/openapi/v1/kis/orders":
            return httpx.Response(200, json={"ok": True, "orders": []})
        if path == "/openapi/v1/kis/balance":
            return httpx.Response(200, json={"ok": True, "balance": {"cashBalance": 0, "holdings": []}})
        return httpx.Response(200, json={"ok": True, "order": {"orderNo": "1", "status": "CANCELLED"}})

    gw.set_transport(httpx.MockTransport(서버))
    yield gw, 요청들
    gw.set_transport(None)


def test_미승인이면_게이트웨이_환경이_real이어도_paper로_강등된다(게이트웨이):
    gw, _ = 게이트웨이
    assert gw.environment() == "paper"


def test_승인하면_게이트웨이가_real을_그대로_쓴다(게이트웨이, allow_live_trading):
    """관문이 '항상 막힘'이 아니라 '승인 시에만 열림'인지 — 2절과 같은 이유로 둔다."""
    gw, _ = 게이트웨이
    assert gw.environment() == "real"


def test_미승인이면_주문에_real을_직접_넘겨도_paper로_나간다(게이트웨이):
    """`env=` 인자는 환경값을 건너뛰는 옆문이다 — 옆문도 같은 관문을 지나야 한다."""
    gw, 요청들 = 게이트웨이
    asyncio.run(gw.place_order("005930", "buy", 1, 70_000, client_order_id="u1:005930:B:1", env="real"))
    본문들 = [json.loads(r.content) for r in 요청들 if r.method == "POST"]
    assert len(본문들) == 2, "승인 토큰 · 주문 두 번을 보낸다"
    assert [b["environment"] for b in 본문들] == ["paper", "paper"]


def test_미승인이면_잔고_조회_취소도_paper로_묻는다(게이트웨이):
    gw, 요청들 = 게이트웨이
    asyncio.run(gw.get_balance(env="real"))
    asyncio.run(gw.get_order_status("1", env="real"))
    asyncio.run(gw.list_today_orders(env="real"))
    asyncio.run(gw.cancel_order("1", env="real"))
    assert [r.url.params["environment"] for r in 요청들] == ["paper"] * 4


# ── 6. KIS 키는 사용자마다 (2026-10-03 결정) ─────────────────────────
#
# 강사님 판은 KIS 계좌 하나를 서버가 관리하고(Secrets Manager → .env) KIS 를 고른 모든 사용자가 같이 쓴다.
# Qurious 는 여러 사람이 쓰는 모의투자 플랫폼이라 포지션 · 잔고가 섞이므로 사용자마다 자기 키를 쓴다.
# 그 키의 환경(모의 · 실전)도 승인 변수가 정한다 — 키를 넣었다고 실전이 되지 않는다.


def test_KIS는_서버가_관리하지_않는다():
    from app.services import kis_credentials

    assert kis_credentials.is_managed("kis") is False
    assert kis_credentials.MANAGED_BROKERS == frozenset()


def test_미승인이면_사용자_KIS_키도_모의_환경이다():
    from app.services import kis_credentials

    행 = SimpleNamespace(broker="kis", app_key=KEY, app_secret=SECRET, account_no="5012345601")
    creds = kis_credentials.for_user(행)
    assert creds is not None and creds.paper is True and creds.environment == "paper"


def test_승인하면_사용자_KIS_키가_실전_환경이다(allow_live_trading):
    from app.services import kis_credentials

    행 = SimpleNamespace(broker="kis", app_key=KEY, app_secret=SECRET, account_no="5012345601")
    assert kis_credentials.for_user(행).environment == "real"


# ── 7. 자동매매 실주문 — 합친 `_place_live_order` ───────────────────
#
# 3-way 병합의 충돌 줄이다. 우리 판은 `paper=not live_trading_allowed()`, 강사님 판은 자격증명이 정한
# `paper=paper` 였다. 둘을 합친 줄이 승인 없이는 모의를, 승인하면 실전을 요청하는지 본다.


def _실주문_요청(monkeypatch) -> dict:
    from app.services import auto_trade

    받은: dict = {}

    class 가짜_증권사:
        async def place_order(self, *a, **k):
            return {"ok": True}

    def 가짜_팩토리(broker, app_key="", app_secret="", paper=True):
        받은.update(broker=broker, paper=paper)
        return 가짜_증권사()

    async def 조용히(**_):
        return None

    monkeypatch.setattr(auto_trade, "get_broker_client", 가짜_팩토리)
    monkeypatch.setattr(auto_trade.notification, "notify_order_placed", 조용히)
    행 = SimpleNamespace(quant_mode="live", broker="kis", app_key=KEY, app_secret=SECRET, account_no="5012345601")
    결과 = asyncio.run(auto_trade._place_live_order(행, "005930", "삼성전자", "buy", 1, 70_000.0, "user-1"))
    assert 결과 and 결과["status"] == "submitted"
    return 받은


def test_미승인이면_자동매매_실주문이_모의로_요청된다(monkeypatch):
    assert _실주문_요청(monkeypatch) == {"broker": "kis", "paper": True}


def test_승인하면_자동매매_실주문이_실전을_요청한다(monkeypatch, allow_live_trading):
    assert _실주문_요청(monkeypatch) == {"broker": "kis", "paper": False}


# ── 8. 표시 — 공개 헬스의 KIS 환경 (강사님 10-07 · e815be3) ──────────
#
# 강사님 판 `/api/health`(로그인 없이 열림)는 환경값 글자(STOCK_COIN_TRADE_KIS_ENVIRONMENT)를 그대로 보인다.
# 주문은 5절의 관문이 막아도, 승인 없이 real 을 적어 두면 공개 화면에는 「실전」 으로 보인다 —
# 10-03 에 화면 쪽 `_live_gateway_info` 를 고친 것과 같게, 표시도 관문을 지난 값(`gateway.environment()`)을 쓴다.


def test_미승인이면_헬스가_real_설정을_paper로_보인다(게이트웨이):
    from app.routes.health import health

    assert asyncio.run(health())["quant"]["kis_environment"] == "paper"


def test_승인하면_헬스가_real을_그대로_보인다(게이트웨이, allow_live_trading):
    from app.routes.health import health

    assert asyncio.run(health())["quant"]["kis_environment"] == "real"
