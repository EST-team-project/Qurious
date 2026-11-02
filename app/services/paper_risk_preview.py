"""PAPER 장부 전용 신규 매수 수량 계산. 주문·스탑 등록·QUANT 설정 변경은 하지 않는다."""
from typing import Literal
from pydantic import ConfigDict, Field

from app.services import paper_trading as pt, risk_stops, trading_cost
from app.services.execution_policy import ExecutionPolicy, risk_quantity


class RiskPreviewBody(ExecutionPolicy):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    size_kind: Literal["risk_pct"] = "risk_pct"
    symbol: str = Field(min_length=1, max_length=20)
    budget: float = Field(1_000_000, gt=0)
    position_cap_pct: float = Field(30, gt=0, le=100)


async def preview(db, uid, body: RiskPreviewBody):
    info = await pt.resolve_stock(body.symbol)
    pt._ensure_supported_market(info)
    info = await pt._confirm_quote(db, uid, info)
    position = await pt._stock_position(db, uid, info["symbol"])
    if position is not None and position.quantity > 0:
        raise pt.PaperTradeError("신규 매수용 계산입니다. 이미 보유한 종목의 추가 매수 수량은 직접 검토하세요.")
    snapshot = await pt.account_snapshot(db, uid)
    if not snapshot["price_complete"]:
        raise pt.PaperTradeError("PAPER 보유자산 평가 가격이 불완전하여 위험 수량을 계산할 수 없습니다.")
    try:
        basis = await risk_stops.entry_basis(info["symbol"], info["price"], body)
        sizing = risk_quantity(
            equity=snapshot["totalAsset"], cash=snapshot["cash"], price=info["price"],
            stop_price=basis["stop_price"], budget=body.budget, existing_value=0,
            position_cap_pct=body.position_cap_pct, risk_pct=body.risk_pct,
            slippage_bps=body.slippage_bps, when=trading_cost.today_kst(),
            market=info["market"], is_etf=info.get("is_etf", trading_cost.is_etf_name(info["name"])),
        )
    except ValueError as exc:
        raise pt.PaperTradeError(str(exc)) from exc
    return {**sizing, "book": "PAPER", "symbol": info["symbol"], "price": info["price"],
            "cash": snapshot["cash"], "equity": snapshot["totalAsset"], "basis": basis,
            "quote_label": info.get("quote_label"), "quote_as_of": info.get("quote_as_of"),
            "assumptions": body.model_dump(exclude={"symbol"}),
            "note": "신규 매수 수량 계산용입니다. 주문이나 스탑을 자동 등록하지 않습니다. 체결 전 가격·현금을 다시 확인합니다."}
