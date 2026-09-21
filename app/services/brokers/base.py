"""증권사 Open API 추상 베이스."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class TokenInfo:
    access_token: str
    expires_in: int  # seconds
    token_type: str = "Bearer"


@dataclass
class PriceInfo:
    symbol: str
    name: str
    current: float
    open: float
    high: float
    low: float
    volume: int
    change: float
    change_pct: float


@dataclass
class BalanceItem:
    symbol: str
    name: str
    quantity: int
    avg_price: float
    current_price: float
    eval_amount: float
    gain_loss: float
    gain_pct: float


@dataclass
class AccountBalance:
    total_eval: float
    total_buy: float
    total_gain: float
    holdings: list[BalanceItem]
    cash: float = 0.0  # 예수금 (주문 가능 현금)


@dataclass
class FillInfo:
    """증권사가 알려준 체결 1건.

    우리가 계산한 비용이 아니라 **증권사가 실제로 뗀 금액**을 담는 그릇이다.
    `total_fees` 가 이 자료형의 존재 이유다 — 우리 요율표(`trading_cost.py`)가
    맞는지 대조할 수 있는 유일한 값이다.

    `total_fees` 가 `None` 이면 그 증권사가 제비용을 알려주지 않는다는 뜻이고,
    0.0 이면 "0원을 뗐다" 는 뜻이다. 둘을 섞으면 검증이 조용히 무너진다.
    """

    broker_order_id: str          # 증권사 주문번호 (KIS: ODNO)
    symbol: str
    name: str
    side: str                     # buy | sell
    order_date: str               # YYYYMMDD
    order_time: str               # HHMMSS ("" 가능)
    order_quantity: int
    order_price: float
    filled_quantity: int          # 총체결수량 (0 이면 미체결)
    avg_fill_price: float         # 체결평균가
    gross_amount: float           # 총체결금액 (증권사 계산)
    total_fees: float | None = None   # 추정제비용합계 — 없으면 None
    cancelled: bool = False
    exchange: str | None = None   # KRX | NXT | SOR ...
    raw: dict[str, Any] | None = None  # 원문 보존 (칸 해석이 틀려도 되돌릴 수 있게)


@dataclass
class FillSummary:
    """체결 조회의 **요약 한 줄**. 주문 1건의 값이 아니다.

    왜 따로 있는가
    --------------
    KIS 체결조회(`inquire-daily-ccld`)는 응답을 두 칸으로 나눠 준다.
    `output1` 이 주문별 목록이고, `output2` 가 조회 범위 전체의 합계다.
    **제비용 칸(`prsm_tlex_smtl`)은 `output2` 에만 있다.** 주문별 목록에는
    없으므로, `output1` 만 모으면 우리 요율표와 대조할 값이 영영 오지 않는다.
    (2026-09-20 까지 `get_daily_fills` 가 그랬다 — 체결이 있어도 "제비용 미제공"
    만 나왔을 것이다.)

    🔴 **주문별 값이 아니라는 점이 이 자료형의 전부다.** 기간에 체결이 여러 건이면
       `total_fees` 는 그 전부의 합이다. 한 건의 제비용을 알고 싶으면 조회할 때
       종목·주문번호를 좁혀 **그 한 건만 걸리게** 해야 한다.
    """

    total_order_quantity: int         # 총주문수량
    total_filled_quantity: int        # 총체결수량
    avg_buy_price: float              # 매입평균가격
    gross_amount: float               # 총체결금액
    total_fees: float | None = None   # 추정제비용합계 — 칸이 비면 None
    raw: dict[str, Any] | None = None

    @property
    def has_fee_info(self) -> bool:
        """증권사가 제비용을 알려줬는가. 0.0(0원을 뗌)과 None(안 알려줌)을 가른다."""
        return self.total_fees is not None


class BrokerClient(ABC):
    """모든 증권사 클라이언트의 공통 인터페이스."""

    @abstractmethod
    async def get_token(self) -> TokenInfo: ...

    @abstractmethod
    async def get_price(self, symbol: str) -> PriceInfo: ...

    @abstractmethod
    async def get_balance(self, account_no: str) -> AccountBalance: ...

    @abstractmethod
    async def place_order(
        self, account_no: str, symbol: str, side: str, quantity: int, price: float
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def get_daily_ohlcv(
        self, symbol: str, start: str, end: str
    ) -> list[dict]: ...

    @abstractmethod
    async def get_daily_fills(
        self, account_no: str, start: str, end: str, symbol: str | None = None
    ) -> list[FillInfo]:
        """기간 내 주문·체결 내역. start/end: YYYYMMDD

        구현하지 않는 증권사는 `NotImplementedError` 를 던진다. 빈 리스트를
        돌려주면 "체결이 없다" 와 "조회할 수 없다" 가 구분되지 않아, 비용 검증이
        조용히 건너뛰어진다.
        """
        ...
