"""통합 대시보드 「KIS 모의투자 시작」 원클릭.

버튼 한 번으로 종목 선정 화면의 설정(증권사 KIS · 실행 모드 live · AI 추천 종목 · Testbed 권장 한도)을
저장하고 자동매매를 켠다. 자격증명은 서버(Secrets Manager)가 관리하므로 사용자 입력이 없다.
→ Qurious(2026-10-03 · 사용자마다 자기 키): 이 사용자가 「종목 선정」 화면에 넣어 둔 KIS 키로 시작하고,
  시작할 때 그 키를 지우지 않는다(kis_credentials 머리말). 키가 없으면 409(연동 안 됨).

안전장치
  - 실주문이 KIS **모의투자(Testbed)** 로만 나가는 경우에만 시작한다. 경로가 실전(real)이면 409.
  - 게이트웨이(stock-coin-trade)도, 이 사용자의 KIS 키도 없으면 409 (연동 안 됨).
  - 비상 정지(kill switch) 상태면 409.
Testbed 권장값은 todo.md 7절 L1 (쿨다운 30분 · 1회 30만 원 · 종목 비중 20% · 일 주문 10건 · 일손실 3%).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BrokerSettings
from app.services import auto_trade, kis_credentials
from app.services.audit import audit
from app.services.brokers import stock_coin_trade_gateway as gateway

logger = logging.getLogger(__name__)

TESTBED_DEFAULTS = {
    "quant_mode": "live",             # live 여야 가상 체결 외에 실제 KIS(Testbed) 주문이 나간다
    "paper": False,
    "broker": "kis",
    "quant_symbol_source": "ai",      # AI 추천 종목
    "quant_ai_top_n": 3,
    "quant_per_trade_budget": 300_000.0,
    "quant_buy_ratio": 1.0,
    "quant_sell_ratio": 0.5,
    "risk_daily_loss_limit_pct": 3.0,
    "risk_max_position_pct": 20.0,
    "risk_max_orders_per_day": 10,
    "risk_cooldown_min": 30,
}


class QuickstartBlocked(Exception):
    """시작할 수 없는 상태. message 는 사용자에게 그대로 보여 준다."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class Route:
    via: str            # "stock-coin-trade" | "kis-direct" | None
    environment: str    # "paper" | "real"
    configured: bool
    detail: str


async def resolve_route(row: BrokerSettings | None = None) -> Route:
    """live 주문이 어디로, 어느 환경으로 나가는지. auto_trade._place_live_order 와 같은 우선순위.

    Qurious: 서버 계좌 대신 그 사용자의 KIS 키(`row`)를 본다 — 환경은 실거래 승인이 정한다.
    """
    if gateway.is_configured():
        env = gateway.environment()
        return Route("stock-coin-trade", env, True, f"stock-coin-trade 게이트웨이 → KIS {'모의(Testbed)' if env == 'paper' else '실전'}")
    creds = kis_credentials.for_user(row)
    if creds is not None:
        return Route("kis-direct", creds.environment, True,
                     f"KIS 직접 호출(내 키) → {'모의(Testbed)' if creds.paper else '실전'}")
    return Route(None, "paper", False,
                 "KIS 키가 없습니다 — 「종목 선정」 화면에서 증권사 KIS 를 고르고 내 모의투자 App Key · Secret · 계좌번호를 넣으세요")


async def _row(db: AsyncSession, uid: uuid.UUID) -> BrokerSettings | None:
    return (await db.execute(select(BrokerSettings).where(BrokerSettings.user_id == uid))).scalar_one_or_none()


async def readiness(db: AsyncSession, uid: uuid.UUID) -> dict:
    """대시보드 패널 표시용: 시작 가능 여부와 현재 상태."""
    row = await _row(db, uid)
    route = await resolve_route(row)
    running = bool(row and row.quant_auto_enabled)
    kill = bool(row and row.risk_kill_switch)
    mode = row.quant_mode if row and row.quant_mode in ("paper", "live") else "paper"
    broker = (row.broker if row and row.broker else "mock")
    if not route.configured:
        ready, reason = False, "not_connected"
    elif route.environment != "paper":
        ready, reason = False, "real_environment"
    elif kill:
        ready, reason = False, "kill_switch"
    else:
        ready, reason = True, ""
    already = running and mode == "live" and broker == "kis"
    return {
        "ready": ready, "reason": reason, "route": route.via, "environment": route.environment,
        "route_detail": route.detail, "connected": route.configured,
        "running": running, "already_started": already, "mode": mode, "broker": broker,
        "kill_switch": kill, "kill_reason": (row.risk_halt_reason if row else "") or "",
        "defaults": {k: v for k, v in TESTBED_DEFAULTS.items() if k not in ("paper",)},
    }


async def start(db: AsyncSession, user_id: str) -> dict:
    uid = uuid.UUID(user_id)
    row = await _row(db, uid)
    route = await resolve_route(row)
    if not route.configured:
        raise QuickstartBlocked("not_connected", route.detail)
    if route.environment != "paper":
        raise QuickstartBlocked("real_environment", "현재 KIS 경로가 실전(real)으로 설정되어 있어 원클릭 모의투자를 시작하지 않습니다. 종목 선정 화면에서 직접 설정하세요.")

    if row is None:   # 키가 없으면 위에서 409 — 남은 경우는 게이트웨이 길
        row = BrokerSettings(user_id=uid)
        db.add(row)
    if row.risk_kill_switch:
        raise QuickstartBlocked("kill_switch", f"비상 정지 상태입니다. 해제 후 시작하세요. (사유: {row.risk_halt_reason or '수동 정지'})")

    for key, value in TESTBED_DEFAULTS.items():
        setattr(row, key, value)
    row.quant_selected_symbols = []
    # 강사님 판은 여기서 사용자 키를 지운다(서버 관리) — 우리 판은 그 키로 주문하므로 그대로 둔다.
    await db.commit()

    started = await auto_trade.start_auto_trade(db, user_id)
    await audit(user_id, "", "quant.kis_quickstart", {"route": route.via, "environment": route.environment, "started": started})
    logger.info("KIS 모의투자 원클릭 시작 user=%s route=%s started=%s", user_id, route.via, started)
    return {
        "ok": True, "started": started, "already_running": not started,
        "route": route.via, "environment": route.environment, "route_detail": route.detail,
        "settings": {
            "mode": "live", "broker": "kis", "symbol_source": "ai", "ai_top_n": TESTBED_DEFAULTS["quant_ai_top_n"],
            "per_trade_budget": TESTBED_DEFAULTS["quant_per_trade_budget"],
            "risk": {"daily_loss_limit_pct": 3.0, "max_position_pct": 20.0, "max_orders_per_day": 10, "cooldown_min": 30},
        },
        "interval_min": 10,
    }
