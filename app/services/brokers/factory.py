"""증권사 클라이언트 팩토리.

★ 실거래 차단 관문 (rfp-2 §4.2)

발주 요구사항의 제외 범위 첫 줄이 **"실제 증권 계좌를 통한 실거래 자동 주문 실행"**이다.
그래서 이 팩토리는 기본적으로 **실계좌에 닿는 클라이언트를 만들지 않는다.**
환경변수 ``QURIOUS_ALLOW_LIVE_TRADING`` 이 명시적으로 켜져 있을 때만 호출자가 요청한
``paper=False`` 를 그대로 존중한다.

왜 호출 지점이 아니라 팩토리에 두는가 —
실주문 경로가 하나가 아니기 때문이다.

* ``app/services/auto_trade.py`` (자동매매) 는 ``paper=False`` 를 **코드에 박아** 넘긴다.
* ``app/routes/stocks.py`` (수동 주문) 는 DB 칸 ``broker_settings.paper`` 를 **그대로** 넘긴다.
  칸이 False 로 저장돼 있으면 코드를 한 줄도 고치지 않고 실계좌로 나간다.

호출 지점마다 막으면 세 번째 경로가 생길 때 또 빠진다. 팩토리는 두 경로가 반드시
지나는 유일한 목이라, 여기 한 번 걸면 앞으로 생길 경로까지 같이 걸린다.

`paper` 플래그로 막을 수 있는 브로커와 없는 브로커 —
KIS 는 모의투자 서버(``openapivts``)가 따로 있어 ``paper=True`` 면 실계좌에 닿지 않는다.
반면 LS증권(ebest)은 모의·실전이 **같은 도메인**이라 플래그를 줘도 실서버로 나간다.
플래그로 못 막는 브로커는 승인 전까지 ``MockBrokerClient`` 로 갈아 끼운다.
"""
import logging
import os

from .base import BrokerClient
from .kis import KISClient
from .ebest import EBestClient
from .kb import KBClient
from .kiwoom import KiwoomClient
from .daishin import DaishinClient
from .meritz import MeritzClient
from .shinhan import ShinhanClient
from .mock import MockBrokerClient

logger = logging.getLogger(__name__)

# 실거래 승인 환경변수. 이 이름은 테스트와 CI·문서가 함께 참조하므로 상수로 노출한다.
LIVE_TRADING_ENV = "QURIOUS_ALLOW_LIVE_TRADING"

# 참으로 읽는 값. "false"·"0"·빈 문자열·미설정은 모두 거짓이다.
_TRUTHY = frozenset({"1", "true", "yes", "on"})

# 모의투자 서버가 따로 없어 paper 플래그가 실효가 없는 브로커.
# 승인 전에는 Mock 으로 강등한다 — paper=True 로는 막히지 않기 때문이다.
LIVE_ONLY_BROKERS = frozenset({"ebest"})


def live_trading_allowed() -> bool:
    """실거래 주문 경로를 열어도 되는가.

    기본값은 거짓이다. rfp-2 §4.2 가 실거래를 제외 범위로 두었으므로,
    **켜는 쪽이 명시적인 행동**이어야 한다.
    """
    return os.getenv(LIVE_TRADING_ENV, "").strip().lower() in _TRUTHY


def get_broker_client(
    broker: str,
    app_key: str = "",
    app_secret: str = "",
    paper: bool = True,
) -> BrokerClient:
    """
    broker: "kis" | "kb" | "kiwoom" | "daishin" | "meritz" | "shinhan" | "ebest" | "mock"
    key/secret이 없으면 자동으로 MockBrokerClient 반환.

    ``paper=False`` 는 **요청**일 뿐이며, 실거래가 승인되지 않은 동안에는
    받아들여지지 않는다 (위 모듈 설명 참조).
    """
    broker = (broker or "mock").lower()
    if not app_key or not app_secret:
        return MockBrokerClient()

    # ── 실거래 차단 관문 ─────────────────────────────────────────────
    if not live_trading_allowed():
        if broker in LIVE_ONLY_BROKERS:
            logger.warning(
                "[실거래 차단] %s 는 모의투자 서버가 따로 없어 paper 플래그로 막을 수 없다. "
                "Mock 으로 대체한다. 실거래를 열려면 %s=1 (rfp-2 §4.2 제외 범위).",
                broker, LIVE_TRADING_ENV,
            )
            return MockBrokerClient()
        if not paper:
            logger.warning(
                "[실거래 차단] paper=False 요청을 모의투자로 강등한다 (broker=%s). "
                "실거래를 열려면 %s=1 (rfp-2 §4.2 제외 범위).",
                broker, LIVE_TRADING_ENV,
            )
            paper = True

    if broker == "kis":
        return KISClient(app_key, app_secret, paper=paper)
    if broker == "kb":
        return KBClient(app_key, app_secret, paper=paper)
    if broker == "kiwoom":
        return KiwoomClient(app_key, app_secret)
    if broker == "daishin":
        return DaishinClient(app_key, app_secret)
    if broker == "meritz":
        return MeritzClient(app_key, app_secret)
    if broker == "shinhan":
        return ShinhanClient(app_key, app_secret)
    if broker == "ebest":
        return EBestClient(app_key, app_secret)
    return MockBrokerClient()
