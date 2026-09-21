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
import inspect

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
