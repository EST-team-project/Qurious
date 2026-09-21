"""pytest 공통 설정.

이 저장소의 첫 테스트 묶음이다. 여기서 하는 일은 둘뿐이다.

1. 저장소 루트를 ``sys.path`` 에 얹어 ``app`` · ``collector`` 를 임포트할 수 있게 한다.
   (루트에서 ``pytest`` 를 돌리면 대개 되지만, CI 의 작업 디렉터리에 기대지 않는다.)
2. **실거래 승인 환경변수를 테스트마다 지운다.** 개발자 셸에
   ``QURIOUS_ALLOW_LIVE_TRADING=1`` 이 남아 있으면 차단 테스트가 조용히 통과해 버린다.
   그런 통과는 통과가 아니다.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.brokers.factory import LIVE_TRADING_ENV  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_live_trading_env(monkeypatch):
    """모든 테스트를 '실거래 미승인' 상태에서 시작한다."""
    monkeypatch.delenv(LIVE_TRADING_ENV, raising=False)


@pytest.fixture
def allow_live_trading(monkeypatch):
    """실거래를 승인한 상태를 만든다. 이 픽스처를 **요청한** 테스트에서만 열린다."""
    monkeypatch.setenv(LIVE_TRADING_ENV, "1")
    return LIVE_TRADING_ENV
