"""국내주식 매매비용 — 위탁수수료 · 유관기관 제비용 · 증권거래세 · 농어촌특별세 · 슬리피지.

왜 이 파일이 따로 있는가
-----------------------
백테스트가 네 갈래(커스텀 인디케이터 · ML 파이프라인 · 전략 백테스트 · LEAN)인데
비용을 세는 곳이 하나뿐이었고, 그 하나마저 "왕복 10bp 대칭" 이라는 가정이었다.
국내주식 비용은 대칭이 아니다 — **매도에만 세금이 붙고, 그 세율이 해마다 바뀐다.**
그래서 요율표를 한 곳에 모으고, 비율(백테스트)과 금액(주문) 양쪽이 같은 표를 쓰게 한다.

비용의 세 층 (섞으면 안 된다)
--------------------------
1. **확정 비용** — 위탁수수료 · 유관기관 제비용 · 증권거래세 · 농어촌특별세.
   요율이 공표돼 있어 계산하면 실제 정산액과 맞아야 한다.
2. **추정 비용** — 슬리피지. 호가 데이터가 없으면 직접 측정할 수 없다. 가정이다.
3. **미반영** — 양도소득세 · 배당소득세 · 신용이자 · 환전. 이 파일 범위 밖.

`cost_basis` 라는 말을 쓰는 이유가 여기 있다: 같은 수익률이 "요율표로 추정한 것"인지
"증권사가 준 실제 금액"인지 구분하지 못하면, 나중에 어느 쪽도 검증할 수 없다.

근거
----
- 위탁수수료: 한국투자증권 수수료안내 (뱅키스 온라인 KRX 0.0140527%, 페이지 기준일 2025-10-27)
- 유관기관 제비용: KRX 주권 유관기관 제비용 원가 0.0036396% (증권사 8곳 고지 일치)
- 증권거래세·농어촌특별세: 증권거래세법 시행령 연도별 개정 (2026년분은 대통령령 제36001호)
- 상세 조사와 확실도 표시는 Issue #40.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

import numpy as np
import pandas as pd

# ── 1. 요율 상수 ──────────────────────────────────────────────────────

#: 위탁수수료 (편도). 뱅키스 온라인(HTS·MTS·API) KRX 기준. 🟢
#: API 주문에 별도 요율이 없다 — "매매수수료: HTS 사용수수료와 동일" (KIS Open API 안내).
#: 즉 요율을 정하는 것은 주문 수단이 아니라 **계좌 종류**다.
#:   영업점계좌 0.147% · ARS 0.2471487% · 오프라인 0.491% — 10배 이상 차이가 난다.
FEE_ONLINE_KRX = 0.000140527
#: 넥스트레이드(NXT)는 요율이 다르다. 주문 시 거래소를 못 박지 않으면 이 둘이 갈린다.
FEE_ONLINE_NXT = 0.000130527
#: 영업점계좌 (참고용 — 우리 계좌가 아니면 이 값을 써야 한다)
FEE_BRANCH_KRX = 0.00147

#: 유관기관 제비용 (편도, **매수·매도 양쪽**). KRX 주권 원가. 🟢
#: 🟡 한국투자증권 고지값은 0.00368330% 로 원가보다 0.0000437%p 높다.
#: 🔴 상수로 두면 안 된다 — 2025-12-15~2026-02-13 한시 인하 구간이 실제로 있었고
#:    (Maker 0.00134% / Taker 0.00182%), KRX 가 연장·재시행을 검토 중이라는 보도가 있다.
#:    지금은 구간을 넣을 만큼 값이 확정되지 않아 상수로 두고, 여기 적어 둔다.
FEE_CLEARING = 0.000036396

#: 농어촌특별세 — **유가증권시장(코스피)에만** 붙는다. 🟢
#: 농어촌특별세법 제5조 제1항 제5호 + 시행령이 과세대상을 유가증권시장으로 한정한다.
#: 코스닥은 이 세목이 없는 대신 증권거래세율이 그만큼 높아 **합계는 같다.**
#: 그래서 합계만 쓰면 시장 구분이 필요 없지만, 한 칸에 합치면 나중에 검증이 불가능해진다.
RURAL_TAX = 0.0015

#: 증권거래세 — 시행일별 (코스피, 코스닥, 코넥스). **매도에만** 붙는다. 매수는 0원. 🟢
#: 코스피 합계 = 이 값 + RURAL_TAX. 코스닥·코넥스 합계 = 이 값 (농특세 없음).
#:
#: | 시행일 | 코스피 | 농특세 | 코스피 합계 | 코스닥 합계 |
#: |---|---|---|---|---|
#: | 2019-06-03 | 0.10% | 0.15% | 0.25% | 0.25% |
#: | 2021-01-01 | 0.08% | 0.15% | 0.23% | 0.23% |
#: | 2023-01-01 | 0.05% | 0.15% | 0.20% | 0.20% |
#: | 2024-01-01 | 0.03% | 0.15% | 0.18% | 0.18% |
#: | 2025-01-01 | 0%    | 0.15% | 0.15% | 0.15% |
#: | 2026-01-01 | 0.05% | 0.15% | 0.20% | 0.20% |
#:
#: 🔴 2025년 구간에 0.20% 를 쓰면 매도 비용을 33% 과대계상하고,
#:    2026년에 0.15% 를 쓰면 과소계상한다. 연도를 무시할 수 없다.
#: 🟡 첫 줄(2019-06-03) 이전 구간은 화면 기본값 period="10y" 이면 **실제로 쓰인다.**
#:    2019-05-31 이전 세율(코스피 0.15%+농특세 0.15%, 코스닥 0.30%)은 Issue #40 조사
#:    범위 밖이라 1차 출처로 재확인하지 않았다. 확실도를 낮게 보고 써야 한다.
TAX_SCHEDULE: tuple[tuple[date, float, float, float], ...] = (
    (date(1900, 1, 1), 0.0015, 0.0030, 0.0010),  # 🟡 2019-06-02 까지 — 재확인 필요
    (date(2019, 6, 3), 0.0010, 0.0025, 0.0010),  # 대통령령 제29788호
    (date(2021, 1, 1), 0.0008, 0.0023, 0.0010),  # 대통령령 제31290호
    (date(2023, 1, 1), 0.0005, 0.0020, 0.0010),  # 대통령령 제33209호
    (date(2024, 1, 1), 0.0003, 0.0018, 0.0010),  # 같은 영 단서
    (date(2025, 1, 1), 0.0000, 0.0015, 0.0010),  # 금투세 전제 인하
    (date(2026, 1, 1), 0.0005, 0.0020, 0.0010),  # 대통령령 제36001호 (2025-12-31 공포)
)

MARKETS = ("KOSPI", "KOSDAQ", "KONEX")
_MARKET_COL = {"KOSPI": 1, "KOSDAQ": 2, "KONEX": 3}

#: 슬리피지 기본값 (편도 bp). 🟡 **가정이다.**
#: 호가단위가 만드는 구조적 하한이 반스프레드 2.5~12.5bp, 실증 추정치가 대형주 11.21bp ·
#: 소형주 21.27bp 이므로 10bp 는 "대형주에 낙관적인 편"이다. 종목 규모로 바꿔 써야 한다.
DEFAULT_SLIPPAGE_BPS = 10.0


# ── 2. 요율 조회 ──────────────────────────────────────────────────────

def as_date(value: Any) -> date:
    """date · datetime · pandas Timestamp · 'YYYY-MM-DD' · 'YYYYMMDD' · 20260920 을 date 로."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().date()
    if isinstance(value, (int, np.integer)):
        value = str(int(value))
    if isinstance(value, str):
        raw = value.strip()
        if len(raw) == 8 and raw.isdigit():
            return date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
        return datetime.fromisoformat(raw[:19]).date()
    raise TypeError(f"날짜로 해석할 수 없다: {value!r}")


def _market(market: str) -> str:
    key = (market or "KOSPI").upper()
    if key in ("KS", "코스피"):
        key = "KOSPI"
    elif key in ("KQ", "코스닥"):
        key = "KOSDAQ"
    elif key in ("KN", "코넥스"):
        key = "KONEX"
    if key not in MARKETS:
        raise ValueError(f"시장 구분은 {MARKETS} 중 하나여야 한다: {market!r}")
    return key


def tax_rates(when: Any, market: str = "KOSPI", is_etf: bool = False) -> tuple[float, float]:
    """(증권거래세율, 농어촌특별세율). 매도에만 쓴다.

    ETF 는 증권거래세가 면제된다 — 조세특례제한법 제117조 제1항 제21호(기한 제한 없음).
    농특세는 증권거래세에 부가되는 세목이므로 면제되면 함께 사라진다.
    """
    if is_etf:
        return 0.0, 0.0
    key = _market(market)
    day = as_date(when)
    col = _MARKET_COL[key]
    rate = TAX_SCHEDULE[0][col]
    for row in TAX_SCHEDULE:
        if day >= row[0]:
            rate = row[col]
        else:
            break
    return rate, (RURAL_TAX if key == "KOSPI" else 0.0)


def cost_rate(
    side: str,
    when: Any,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    market: str = "KOSPI",
    is_etf: bool = False,
    fee_rate: float = FEE_ONLINE_KRX,
    clearing_rate: float = FEE_CLEARING,
) -> float:
    """**편도** 비용률. side: buy | sell.

    매수 = 수수료 + 유관기관비 + 슬리피지
    매도 = 매수 + 증권거래세 + 농어촌특별세
    """
    s = (side or "").lower()
    if s not in ("buy", "sell"):
        raise ValueError(f"side 는 buy 또는 sell 이어야 한다: {side!r}")
    base = fee_rate + clearing_rate + max(0.0, float(slippage_bps)) / 10_000.0
    if s == "buy":
        return base
    transfer, rural = tax_rates(when, market, is_etf)
    return base + transfer + rural


def round_trip_rate(when: Any, **kwargs) -> float:
    """왕복 비용률. 현행 `cost_bps` 대칭 가정과 대조할 때 쓴다."""
    return cost_rate("buy", when, **kwargs) + cost_rate("sell", when, **kwargs)


# ── 3. 주문 금액 — 세목을 쪼개서 계산한다 ────────────────────────────

@dataclass(frozen=True)
class OrderCost:
    """한 주문의 비용 내역과 정산금액.

    `net_amount` 가 이 모듈의 결론이다 — 현금 증감은 `가격 × 수량` 이 아니라 이 값이다.
    """
    side: str
    gross_amount: float      # 체결가 × 체결수량
    commission: float        # 위탁수수료
    fee_clearing: float      # 유관기관 제비용
    tax_transfer: float      # 증권거래세
    tax_rural: float         # 농어촌특별세
    net_amount: float        # 정산금액 (매수: 나가는 현금 / 매도: 들어오는 현금)
    cost_basis: str = "estimated"

    @property
    def total_cost(self) -> float:
        return self.commission + self.fee_clearing + self.tax_transfer + self.tax_rural

    @property
    def cost_pct(self) -> float:
        return (self.total_cost / self.gross_amount * 100.0) if self.gross_amount else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "gross_amount": round(self.gross_amount, 2),
            "commission": round(self.commission, 2),
            "fee_clearing": round(self.fee_clearing, 2),
            "tax_transfer": round(self.tax_transfer, 2),
            "tax_rural": round(self.tax_rural, 2),
            "total_cost": round(self.total_cost, 2),
            "cost_pct": round(self.cost_pct, 4),
            "net_amount": round(self.net_amount, 2),
            "cost_basis": self.cost_basis,
        }


def order_costs(
    side: str,
    price: float,
    quantity: int,
    when: Any,
    market: str = "KOSPI",
    is_etf: bool = False,
    fee_rate: float = FEE_ONLINE_KRX,
    clearing_rate: float = FEE_CLEARING,
    round_to_won: bool = False,
    cost_basis: str = "estimated",
) -> OrderCost:
    """한 주문의 비용을 세목별로 계산한다. 슬리피지는 넣지 않는다 —
    체결가(`price`)가 이미 슬리피지를 포함한 실제 체결 결과이기 때문이다.

    매수: net = 체결금액 + 수수료 + 유관기관비
    매도: net = 체결금액 − 수수료 − 유관기관비 − 증권거래세 − 농어촌특별세

    🟡 `round_to_won`: 증권사 정산은 원 단위 절사로 알려져 있으나 규정 원문을 확인하지
       않았다. 기본은 절사하지 않는다 — 확인되지 않은 규칙을 조용히 적용하면 실제
       정산액과 어긋날 때 원인을 찾을 수 없다.
    """
    s = (side or "").lower()
    if s not in ("buy", "sell"):
        raise ValueError(f"side 는 buy 또는 sell 이어야 한다: {side!r}")
    gross = float(price) * int(quantity)

    def cut(x: float) -> float:
        return float(np.floor(x)) if round_to_won else x

    commission = cut(gross * fee_rate)
    clearing = cut(gross * clearing_rate)
    if s == "buy":
        transfer = rural = 0.0
        net = gross + commission + clearing
    else:
        t_rate, r_rate = tax_rates(when, market, is_etf)
        transfer = cut(gross * t_rate)
        rural = cut(gross * r_rate)
        net = gross - commission - clearing - transfer - rural

    return OrderCost(
        side=s, gross_amount=gross, commission=commission, fee_clearing=clearing,
        tax_transfer=transfer, tax_rural=rural, net_amount=net, cost_basis=cost_basis,
    )


# ── 4. 백테스트용 비용 모델 ───────────────────────────────────────────

class CostModel(Protocol):
    """백테스트가 비용을 묻는 창구. 두 구현을 같은 방식으로 쓰게 한다."""

    def turnover_cost(self, held: pd.Series) -> pd.Series:
        """보유비중 시계열 → 날짜별로 차감할 비용률 시계열."""
        ...

    def buy_hold_cost(self, index: pd.Index) -> pd.Series:
        """매수후보유(벤치마크)의 비용 — 첫날 매수 1회 + 마지막날 매도 1회."""
        ...

    def describe(self) -> dict[str, Any]:
        """무엇을 어떻게 뗐는지. 응답에 실어 화면이 숨기지 못하게 한다."""
        ...


def position_delta(held: pd.Series) -> tuple[pd.Series, pd.Series]:
    """보유비중 변화를 매수분·매도분으로 가른다. 첫날 값은 그 자체가 진입이다."""
    held = held.astype(float).fillna(0.0)
    delta = held.diff()
    if len(delta):
        delta.iloc[0] = held.iloc[0]
    buy = delta.clip(lower=0.0)
    sell = (-delta).clip(lower=0.0)
    return buy, sell


@dataclass(frozen=True)
class KrxCostModel:
    """국내주식 실제 요율 — 매도에만 세금, 세율은 날짜로 정해진다.

    한 방향씩 따로 세는 것이 핵심이다. 왕복을 대칭으로 보면
    매매가 잦은 전략에서 세금이 절반만 반영된다.
    """
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS
    market: str = "KOSPI"
    is_etf: bool = False
    fee_rate: float = FEE_ONLINE_KRX
    clearing_rate: float = FEE_CLEARING
    include_tax: bool = True

    def _rates(self, index: pd.Index) -> tuple[np.ndarray, np.ndarray]:
        """날짜별 (매수율, 매도율). 구간 경계로 한 번에 갈라 종목·일자 수에 견디게 한다."""
        base = self.fee_rate + self.clearing_rate + max(0.0, float(self.slippage_bps)) / 10_000.0
        n = len(index)
        buy = np.full(n, base, dtype=float)
        if not self.include_tax:
            return buy, buy.copy()

        key = _market(self.market)
        if self.is_etf:
            return buy, buy.copy()

        days = np.array([as_date(x).toordinal() for x in index], dtype=np.int64)
        bounds = np.array([row[0].toordinal() for row in TAX_SCHEDULE], dtype=np.int64)
        col = _MARKET_COL[key]
        rates = np.array([row[col] for row in TAX_SCHEDULE], dtype=float)
        # 각 날짜가 속한 구간 = 시행일이 그 날짜를 넘지 않는 마지막 구간
        slot = np.clip(np.searchsorted(bounds, days, side="right") - 1, 0, len(bounds) - 1)
        transfer = rates[slot]
        rural = RURAL_TAX if key == "KOSPI" else 0.0
        return buy, base + transfer + rural

    def turnover_cost(self, held: pd.Series) -> pd.Series:
        buy_turn, sell_turn = position_delta(held)
        buy_rate, sell_rate = self._rates(held.index)
        return pd.Series(buy_turn.values * buy_rate + sell_turn.values * sell_rate,
                         index=held.index, name="cost")

    def buy_hold_cost(self, index: pd.Index) -> pd.Series:
        out = pd.Series(0.0, index=index, name="cost")
        if not len(index):
            return out
        buy_rate, sell_rate = self._rates(index)
        out.iloc[0] = buy_rate[0]
        out.iloc[-1] = out.iloc[-1] + sell_rate[-1]
        return out

    def describe(self) -> dict[str, Any]:
        first = self.market if not self.is_etf else f"{self.market} (ETF · 거래세 면제)"
        return {
            "model": "krx_real",
            "label": "국내주식 실제 요율 (연도별 매도세 + 수수료 + 유관기관비 + 슬리피지)",
            "market": first,
            "slippage_bps": round(float(self.slippage_bps), 3),
            "fee_rate_pct": round(self.fee_rate * 100, 7),
            "clearing_rate_pct": round(self.clearing_rate * 100, 7),
            "include_tax": self.include_tax,
            "cost_basis": "estimated",
            "note": "슬리피지는 가정이다 — 호가 데이터가 없어 직접 측정하지 못했다.",
        }


@dataclass(frozen=True)
class FlatCostModel:
    """왕복 대칭 `cost_bps` — 예전 동작을 재현하기 위해 남긴다.

    실제 국내주식 비용이 아니다. 비교·회귀 확인용으로만 쓴다.
    """
    cost_bps: float = 10.0

    @property
    def _rate(self) -> float:
        return max(0.0, float(self.cost_bps)) / 10_000.0

    def turnover_cost(self, held: pd.Series) -> pd.Series:
        buy_turn, sell_turn = position_delta(held)
        return ((buy_turn + sell_turn) * self._rate).rename("cost")

    def buy_hold_cost(self, index: pd.Index) -> pd.Series:
        out = pd.Series(0.0, index=index, name="cost")
        if not len(index):
            return out
        out.iloc[0] = self._rate
        out.iloc[-1] = out.iloc[-1] + self._rate
        return out

    def describe(self) -> dict[str, Any]:
        return {
            "model": "flat",
            "label": f"왕복 대칭 {self.cost_bps:g}bp (실제 국내주식 비용이 아니다)",
            "cost_bps": float(self.cost_bps),
            "cost_basis": "estimated",
            "note": "매도 세금을 따로 세지 않는다. 예전 동작 재현용.",
        }


@dataclass(frozen=True)
class NoCostModel:
    """비용을 떼지 않는다. 무비용이 얼마나 낙관적인지 대조할 때만 쓴다.

    `None` 을 쓰지 않고 객체로 둔 이유: 호출하는 쪽에서 `None` 은 "안 넘겼다"와
    "없다고 정했다" 둘로 읽혀, 무비용을 고를 수 없게 만든 적이 있다.
    """

    def turnover_cost(self, held: pd.Series) -> pd.Series:
        return pd.Series(0.0, index=held.index, name="cost")

    def buy_hold_cost(self, index: pd.Index) -> pd.Series:
        return pd.Series(0.0, index=index, name="cost")

    def describe(self) -> dict[str, Any]:
        return {
            "model": "none",
            "label": "비용 미반영 — 실제 성과보다 낙관적이다",
            "cost_basis": "none",
            "note": "수수료·세금·슬리피지를 전혀 빼지 않은 값이다.",
        }


def build(
    model: str = "real",
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    cost_bps: float = 10.0,
    market: str = "KOSPI",
    is_etf: bool = False,
) -> CostModel:
    """라우트가 문자열 하나로 비용 모델을 고르게 한다. **None 을 돌려주지 않는다.**

    real — 연도별 실제 요율 (기본)
    flat — 왕복 대칭 cost_bps (예전 동작)
    none — 비용 없음 (무비용이 얼마나 낙관적인지 대조할 때만)
    """
    key = (model or "real").lower()
    if key in ("none", "off", "zero"):
        return NoCostModel()
    if key == "flat":
        return FlatCostModel(cost_bps=cost_bps)
    if key in ("real", "krx", "krx_real"):
        return KrxCostModel(slippage_bps=slippage_bps, market=market, is_etf=is_etf)
    raise ValueError(f"cost_model 은 real | flat | none 중 하나여야 한다: {model!r}")


def describe(cost: CostModel | None) -> dict[str, Any]:
    """비용 모델이 없을 때도 응답에 무엇을 안 뗐는지 남긴다.

    `backtest(df, signals)` 처럼 비용 인자를 생략한 호출도 응답에 "none" 을 실어야,
    무비용인 수치가 아무 표시 없이 화면에 나가지 않는다.
    """
    if cost is None:
        return NoCostModel().describe()
    return cost.describe()
