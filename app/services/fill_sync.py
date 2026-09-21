"""증권사 체결 내역을 `orders` · `order_fills` 로 들여온다.

왜 필요한가
-----------
실전 주문 경로(`app/routes/stocks.py` 의 증권사 주문 · `app/services/auto_trade.py`)는
증권사에 주문만 내고 **DB 에는 아무것도 남기지 않는다.** 그래서 실제로 체결된 주문은
우리 쪽에 기록이 없다. 이 모듈이 그 구멍을 메운다 — 증권사가 가진 체결을 가져와
`orders` 에 채워 넣는다.

무엇을 검증하는가
-----------------
`trading_cost.py` 의 요율표로 계산한 비용은 지금까지 전부 **추정값**이었다
(`cost_basis="estimated"`). KIS 체결 조회는 `prsm_tlex_smtl`(추정제비용합계)를 함께
주므로, 우리 계산과 **증권사가 실제로 뗀 금액을 처음으로 맞대어 볼 수 있다.**

합계가 맞을 때만 `cost_basis="broker"` 를 붙인다. 어긋나면 `estimated` 로 두고
차액을 그대로 보고한다 — 틀린 값을 "증권사가 준 값" 이라고 부르면 검증이 무의미해진다.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading import Order, OrderFill
from app.services import trading_cost
from app.services.brokers.base import BrokerClient, FillInfo

logger = logging.getLogger(__name__)

# 증권사 제비용 합계와 우리 추정의 허용 오차(원).
# 🟡 증권사 정산이 세목마다 원 단위 절사를 하는지 아직 확인하지 못했다(#40 열린 질문).
#    절사한다면 세목 4개에서 최대 4원까지 어긋날 수 있다. 그래도 기본값을 1원으로
#    좁게 잡는다 — 이 모듈의 목적이 "맞는지 보는 것" 이지 "맞다고 넘기는 것" 이 아니다.
DEFAULT_TOLERANCE_WON = 1.0


#: ETF 판정은 `trading_cost` 로 옮겼다 — 요율표를 쓰는 쪽이 넷 더 있는데 이 모듈의
#: private 함수라 아무도 쓸 수 없었고, 그래서 **ETF 매도 정산이 0.20%p 과대 계상**되고
#: 있었다(2026-09-21 수정). 이 이름은 호출부 호환을 위해 남긴다.
_is_etf = trading_cost.is_etf_name


def _filled_at(fill: FillInfo) -> datetime:
    """체결시각으로 쓸 값.

    🟡 KIS 일별주문체결조회는 **주문시각(`ord_tmd`)만** 주고 체결시각은 주지 않는다.
       지정가 주문이 나중에 체결되면 둘은 다르다. 지금 얻을 수 있는 가장 가까운 값이
       주문시각이라 이것을 쓰되, 체결시각이 아니라는 사실을 여기 적어 둔다.
    """
    d = (fill.order_date or "").strip()
    t = (fill.order_time or "").strip().ljust(6, "0")[:6]
    if len(d) == 8 and d.isdigit():
        try:
            return datetime(
                int(d[:4]), int(d[4:6]), int(d[6:]),
                int(t[:2]), int(t[2:4]), int(t[4:6]), tzinfo=trading_cost.KST,
            )
        except ValueError:
            pass
    return trading_cost.now_kst()


def _order_updates(fill: FillInfo, cost: trading_cost.OrderCost, net: float) -> dict[str, Any]:
    """`Order` 에 넣을 칸. `trading_cost.order_fields` 와 달리 체결가·체결수량이
    주문가·주문수량과 다를 수 있다 — 증권사가 실제 값을 알려주기 때문이다."""
    return {
        "order_price":     fill.order_price,
        "avg_fill_price":  fill.avg_fill_price,
        "filled_quantity": fill.filled_quantity,
        "commission":      cost.commission,
        "tax_transfer":    cost.tax_transfer,
        "tax_rural":       cost.tax_rural,
        "fee_clearing":    cost.fee_clearing,
        "net_amount":      net,
        "cost_basis":      cost.cost_basis,
        "filled_at":       _filled_at(fill),
    }


async def sync_daily_fills(
    db: AsyncSession,
    user_id: str | uuid.UUID,
    client: BrokerClient,
    account_no: str,
    start: str,
    end: str,
    *,
    broker: str = "kis",
    symbol: str | None = None,
    tolerance_won: float = DEFAULT_TOLERANCE_WON,
    commit: bool = True,
) -> dict[str, Any]:
    """기간 내 체결을 가져와 `orders` · `order_fills` 에 반영한다.

    같은 주문을 여러 번 동기화해도 행이 늘지 않는다 — 증권사 주문번호
    (`broker_order_id`)로 찾아 갱신한다.

    돌려주는 값의 `mismatched` 가 이 함수의 결론이다. 비어 있으면 우리 요율표가
    증권사 정산과 일치한다는 뜻이고, 차 있으면 어디가 얼마나 어긋나는지가 들어 있다.
    """
    fills = await client.get_daily_fills(account_no, start, end, symbol)

    stats: dict[str, Any] = {
        "broker": broker, "period": {"start": start, "end": end},
        "fetched": len(fills),
        "skipped_cancelled": 0, "skipped_unfilled": 0,
        "created": 0, "updated": 0,
        "verified": 0, "no_fee_info": 0,
        "mismatched": [],
    }

    for fill in fills:
        if fill.cancelled:
            stats["skipped_cancelled"] += 1
            continue
        if fill.filled_quantity <= 0:
            stats["skipped_unfilled"] += 1
            continue

        # 🟡 KIS 는 종목코드를 접미사 없이(`005930`) 주므로 시장을 알 수 없다.
        #    코스피와 코스닥은 세목 구성만 다르고 합계가 같아 값은 맞지만, 코넥스는
        #    합계 자체가 낮아 어긋난다. 코넥스 종목을 다루게 되면 여기를 고쳐야 한다.
        market = trading_cost.market_of(fill.symbol)
        when = fill.order_date or trading_cost.today_kst()
        estimated = trading_cost.order_costs(
            side=fill.side,
            price=fill.avg_fill_price,
            quantity=fill.filled_quantity,
            when=when,
            market=market,
            is_etf=_is_etf(fill.name),
        )

        cost = estimated
        net = estimated.net_amount
        if fill.total_fees is None:
            stats["no_fee_info"] += 1
        else:
            diff = fill.total_fees - estimated.total_cost
            if abs(diff) <= tolerance_won:
                # 합계가 맞았다 — 세목은 요율표 값을 그대로 두되, 정산금액만 증권사
                # 합계로 맞춘다. 원 단위 차이는 증권사 쪽이 정답이다.
                net = (fill.gross_amount + fill.total_fees) if fill.side == "buy" \
                    else (fill.gross_amount - fill.total_fees)
                cost = trading_cost.OrderCost(
                    side=estimated.side, gross_amount=estimated.gross_amount,
                    commission=estimated.commission, fee_clearing=estimated.fee_clearing,
                    tax_transfer=estimated.tax_transfer, tax_rural=estimated.tax_rural,
                    net_amount=net, cost_basis="broker",
                )
                stats["verified"] += 1
            else:
                # 어긋났을 때 증권사 합계를 `net_amount` 에 쓰지 않는다.
                # 쓰면 현금 증감은 맞지만 `net = 체결금액 ± 세목합` 이라는 불변식이
                # 깨져, 어느 세목이 틀렸는지 영영 알 수 없게 된다. 대신 추정값으로
                # 정합성을 지키고 차액을 `mismatched` 로 드러낸다 — 요율표를 고친 뒤
                # 다시 동기화하면 그때 `broker` 로 바뀐다.
                gross = fill.gross_amount or estimated.gross_amount
                stats["mismatched"].append({
                    "broker_order_id": fill.broker_order_id,
                    "symbol": fill.symbol, "name": fill.name,
                    "side": fill.side, "order_date": fill.order_date,
                    "quantity": fill.filled_quantity, "price": fill.avg_fill_price,
                    "gross_amount": round(gross, 2),
                    "broker_fees": round(fill.total_fees, 2),
                    "our_fees": round(estimated.total_cost, 2),
                    "diff": round(diff, 2),
                    "diff_bps": round(diff / gross * 10_000, 4) if gross else None,
                    "our_breakdown": {
                        "commission": round(estimated.commission, 2),
                        "fee_clearing": round(estimated.fee_clearing, 2),
                        "tax_transfer": round(estimated.tax_transfer, 2),
                        "tax_rural": round(estimated.tax_rural, 2),
                    },
                })
                logger.warning(
                    "체결 비용 불일치 odno=%s %s %s %d주 — 증권사 %.2f원 vs 우리 %.2f원 (차 %.2f원)",
                    fill.broker_order_id, fill.side, fill.symbol,
                    fill.filled_quantity, fill.total_fees, estimated.total_cost, diff,
                )

        row = (await db.execute(
            select(Order).where(
                Order.user_id == user_id,
                Order.broker_order_id == fill.broker_order_id,
            )
        )).scalar_one_or_none()

        if row is None:
            row = Order(
                user_id=user_id, symbol=fill.symbol, name=fill.name,
                order_type=fill.side, quantity=fill.order_quantity or fill.filled_quantity,
                price=fill.avg_fill_price, status="filled", broker=broker,
                source="OPENAPI", broker_order_id=fill.broker_order_id,
                **_order_updates(fill, cost, net),
            )
            db.add(row)
            await db.flush()
            stats["created"] += 1
        else:
            for key, value in _order_updates(fill, cost, net).items():
                setattr(row, key, value)
            row.status = "filled"
            stats["updated"] += 1

        # 체결 근거를 남긴다.
        # ⚠️ KIS 일별주문체결조회는 **주문 단위 집계**(총체결수량·체결평균가)를 준다.
        #    개별 부분체결 한 건씩이 아니다. 그래서 seq=1 집계 행 하나만 둔다.
        #    `broker_exec_id` 가 비어 있는 것이 "개별 체결 식별자가 없다" 는 표시다.
        exist = (await db.execute(
            select(OrderFill).where(OrderFill.order_id == row.id, OrderFill.seq == 1)
        )).scalar_one_or_none()
        values = {
            "fill_price": fill.avg_fill_price,
            "fill_quantity": fill.filled_quantity,
            "fill_at": row.filled_at or trading_cost.now_kst(),
            "commission": cost.commission,
            "tax_transfer": cost.tax_transfer,
            "tax_rural": cost.tax_rural,
            "fee_clearing": cost.fee_clearing,
        }
        if exist is None:
            db.add(OrderFill(order_id=row.id, seq=1, **values))
        else:
            for key, value in values.items():
                setattr(exist, key, value)

    if commit:
        await db.commit()

    stats["mismatch_count"] = len(stats["mismatched"])
    return stats
