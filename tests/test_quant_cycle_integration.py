"""_run_quant_cycle 통합: 매수 시그널 → 가상 체결 → 게이트웨이 실주문 → live_orders 기록 (live) / 게이트웨이 미호출 (paper).

DB 는 select 대상 엔티티별로 응답하는 가짜 AsyncSession, 지표·가상체결·알림·Redis 는 패치, 게이트웨이는 MockTransport.
"""
import asyncio
import os
import uuid
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BooleanClauseList, BinaryExpression

from app.config import settings
from app.models import BrokerSettings, LiveOrder, Portfolio, QuantVirtualAccount, LIVE_ORDER_OPEN_STATUSES
from app.services import auto_trade
from app.services.brokers import stock_coin_trade_gateway as gw

UID = uuid.UUID("0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0")
STOCKS = [{"symbol": "005930.KS", "name": "삼성전자"}, {"symbol": "000660.KS", "name": "SK하이닉스"}]


def broker(mode="live", **over):
    base = dict(quant_mode=mode, paper=(mode == "paper"), broker="kis", app_key="", app_secret="", account_no="",
                quant_symbol_source="manual", quant_selected_symbols=["005930.KS"], quant_ai_top_n=1,
                quant_per_trade_budget=300_000.0, quant_buy_ratio=1.0, quant_sell_ratio=0.5,
                risk_daily_loss_limit_pct=3.0, risk_max_position_pct=30.0, risk_max_orders_per_day=20, risk_cooldown_min=30,
                risk_kill_switch=False, risk_halt_reason="", quant_auto_enabled=True, quant_strategy_id="", quant_strategy_version=0)
    base.update(over)
    return SimpleNamespace(**base)


class Result:
    def __init__(self, one=None, many=()): self._one, self._many = one, list(many)
    def scalar_one_or_none(self): return self._one
    def scalars(self): return self
    def all(self): return self._many


class FakeDb:
    def __init__(self, broker_row, live_rows=(), positions=()):
        self.broker_row, self.live_rows, self.added, self.commits = broker_row, list(live_rows), [], 0
        self.positions = list(positions)
    def add(self, obj): self.added.append(obj)
    async def commit(self): self.commits += 1
    async def execute(self, stmt, *_a, **_k):
        entity = stmt.column_descriptions[0]["entity"]
        if entity is QuantVirtualAccount:
            return Result(one=SimpleNamespace(cash_balance=10_000_000.0, initial_capital=10_000_000.0))
        if entity is BrokerSettings:
            return Result(one=self.broker_row)
        if entity is Portfolio:
            return Result(one=None, many=self.positions)
        if entity is LiveOrder:
            # 노출 조회(BUY)와 주문 보류 조회(같은 종목, 양방향)의 WHERE를 모두 반영한다.
            return Result(many=[row for row in self.live_rows if matches(stmt.whereclause, row)])
        raise AssertionError(f"unexpected select: {entity}")


def matches(clause, row):
    """이 시험의 단순 WHERE만 평가한다. 미지원 SQL은 무시하지 않고 실패시킨다."""
    if isinstance(clause, BooleanClauseList) and clause.operator is operators.and_:
        return all(matches(part, row) for part in clause.clauses)
    if isinstance(clause, BinaryExpression):
        value, expected = getattr(row, clause.left.key), clause.right.value
        if clause.operator is operators.eq:
            return value == expected
        if clause.operator is operators.in_op:
            return value in expected
    raise AssertionError(f"unsupported predicate: {clause}")


class Factory:
    def __init__(self, db): self.db = db
    def __call__(self): return self
    async def __aenter__(self): return self.db
    async def __aexit__(self, *a): return False


def fake_gateway(*, cash=10_000_000, rejected=False, holdings=()):
    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        calls.append((request.method, request.url.path, body))
        if request.url.path.endswith("/balance"):
            return httpx.Response(200, json={"ok": True, "balance": {"totalEvalAmount": 10_000_000, "cashBalance": cash, "holdings": list(holdings)}})
        if request.url.path.endswith("/order-approval"):
            return httpx.Response(200, json={"ok": True, "approvalToken": "t", "expiresIn": 60})
        if request.url.path.endswith("/kis/orders") and request.method == "POST":
            if rejected:
                return httpx.Response(403, json={"ok": False, "error": "KIS_TOKEN_UNAVAILABLE", "message": "token rejected"})
            return httpx.Response(200, json={"ok": True, "duplicate": False, "order": {"orderNo": "0000031000", "status": "ACCEPTED", "message": "ok"}})
        return httpx.Response(404, json={"ok": False, "error": "NOT_FOUND", "message": request.url.path})
    gw.set_transport(httpx.MockTransport(handler))
    return calls


async def indicators(symbol, period="2y"):
    if symbol == "005930.KS":
        return {"signal": {"action": "매수", "score": 3, "reasons": ["골든크로스"]}, "current_price": 70_000.0,
                "as_of": "2026-10-16"}
    return {"signal": {"action": "관망", "score": 0, "reasons": []}, "current_price": 200_000.0}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr(settings, "QUANT_AGGRESSIVE_MODE", False)
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_BASE_URL", "https://sct.test")
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_API_KEY", "key")
    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_KIS_ENVIRONMENT", "paper")
    yield
    gw.set_transport(None)


def run_cycle(broker_row, live_rows=(), quote_price=70_000, positions=()):
    db = FakeDb(broker_row, live_rows, positions)
    persisted = {}
    async def persist(uid, log): persisted.update(log)
    async def virtual_trade(db_, uid, symbol, name, action, price, qty, reason):
        assert broker_row.quant_mode == "paper", "KIS 주문은 가상 장부를 변경하면 안 된다"
        return {"status": "filled", "symbol": symbol, "action": action, "quantity": qty, "price": price}
    async def quoted(symbol, **kwargs):
        return {"price": quote_price, "source": "kis_user", "as_of": "2026-10-27 14:00",
                "fetched_at": "2026-10-27 14:00:00", "label": "증권사 조회 · 14:00:00", "fallback": []}
    with patch.object(auto_trade.quant_valuation.quote_now, "quote_now", quoted), \
         patch.object(auto_trade, "get_session_factory", return_value=Factory(db)), \
         patch.object(auto_trade, "QUANT_STOCKS", STOCKS), \
         patch.object(auto_trade, "get_quant_indicators", indicators), \
         patch.object(auto_trade, "_execute_virtual_trade", virtual_trade), \
         patch.object(auto_trade, "_persist_cycle", persist), \
         patch.object(auto_trade.risk_guard, "day_start_equity", AsyncMock(return_value=10_000_000.0)), \
         patch.object(auto_trade.risk_guard, "orders_today", AsyncMock(return_value=0)), \
         patch.object(auto_trade.risk_guard, "acquire_order_slot", AsyncMock(return_value=True)), \
         patch.object(auto_trade.risk_guard, "increment_orders_today", AsyncMock(return_value=1)), \
         patch.object(auto_trade.risk_guard, "release_order_slot", AsyncMock()), \
         patch.object(auto_trade.risk_guard, "_redis", return_value=object()), \
         patch.object(auto_trade.notification, "notify_auto_trade_executed", AsyncMock()) as virtual_alert, \
         patch.object(auto_trade.notification, "notify_order_placed", AsyncMock()), \
         patch.object(auto_trade.notification, "notify_order_error", AsyncMock()), \
         patch.object(auto_trade.notification, "notify_risk_skip", AsyncMock()), \
         patch.object(gw, "is_krx_market_open", return_value=True):
        asyncio.run(auto_trade._run_quant_cycle(str(UID)))
        if broker_row.quant_mode == "live":
            virtual_alert.assert_not_awaited()
    return db, persisted


def test_live_mode_routes_buy_signal_through_gateway_and_tracks_live_order():
    calls = fake_gateway()
    db, log = run_cycle(broker("live"))
    trades = [t for t in log["trades"] if t.get("type") == "auto"]
    assert len(trades) == 1 and trades[0]["quantity"] == 4           # 300,000 / 70,000 → 4주
    live = trades[0]["live_order"]
    assert live["status"] == "submitted" and live["order_no"] == "0000031000" and live["environment"] == "paper"
    paths = [p for _, p, _ in calls]
    assert paths == ["/openapi/v1/kis/balance", "/openapi/v1/kis/order-approval", "/openapi/v1/kis/orders"]
    rows = [a for a in db.added if isinstance(a, LiveOrder)]
    assert len(rows) == 1 and rows[0].status == "ACCEPTED" and rows[0].quantity == 4 and rows[0].symbol == "005930.KS"
    assert log["risk"]["live"]["breached"] is False and log["settings"]["mode"] == "live"
    assert trades[0]['status'] == 'submitted' and trades[0]['virtual_status'] == 'not_recorded'


def test_selected_card_load_failure_never_uses_default_buy(monkeypatch):
    calls = fake_gateway()
    monkeypatch.setattr(auto_trade.strategy_loader, "get_strategy", AsyncMock(return_value=None))
    db, log = run_cycle(broker("live", quant_strategy_id="missing", quant_strategy_version=1))
    assert calls == [] and db.added == []
    assert "조회 실패" in log["note"]


def test_budget_less_than_one_share_never_sends_order():
    calls = fake_gateway()
    db, log = run_cycle(broker("live", quant_per_trade_budget=10_000))
    assert not any(path.endswith("/orders") for _, path, _ in calls)
    assert not any(isinstance(row, LiveOrder) for row in db.added)
    assert any("1회 예산" in t.get("reason", "") for t in log["trades"])


def test_card_with_insufficient_bars_never_uses_indicator_buy(monkeypatch):
    import json
    from pathlib import Path
    spec = json.loads(Path("docs/phase-3/02-design/system/예시/strategy-card-ma-cross-v1.json").read_text(encoding="utf-8"))
    calls = fake_gateway()
    monkeypatch.setattr(auto_trade.strategy_loader, "get_strategy", AsyncMock(return_value=spec))
    db, log = run_cycle(broker("live", quant_strategy_id=spec["strategy_id"], quant_strategy_version=1))
    assert not any(path.endswith("/orders") for _, path, _ in calls)
    assert any("종가" in s.get("error", "") for s in log["signals"])


def test_live_rejection_keeps_virtual_book_and_order_counter_unchanged():
    fake_gateway(rejected=True)
    db, log = run_cycle(broker('live'))
    assert log['trades'][0]['status'] == 'error'
    assert log['trades'][0]['virtual_status'] == 'not_recorded'
    assert log['risk']['orders_today'] == 0
    assert log['account']['ledger'] == 'kis_account' and log['account']['cash_balance'] == 10_000_000
    assert all(isinstance(row, LiveOrder) for row in db.added)


def test_live_uses_broker_cash_even_if_virtual_account_has_ten_million():
    calls = fake_gateway(cash=0)
    _, log = run_cycle(broker('live'))
    assert log['trades'][0]['type'] == 'risk'
    assert all(method != 'POST' for method, _, _ in calls)


def test_live_sell_uses_broker_holding_not_empty_virtual_portfolio(monkeypatch):
    fake_gateway(holdings=[{'symbol': '005930', 'quantity': 3, 'avgPrice': 65000, 'evalAmount': 210000}])
    async def sell(*args):
        return {'current_price': 70000, 'signal': {'action': '매도', 'score': -3, 'reasons': ['시험']}}
    monkeypatch.setattr(sys.modules[__name__], 'indicators', sell)
    db, log = run_cycle(broker('live'))
    trade = log['trades'][0]
    assert trade['action'] == 'sell' and trade['quantity'] == 1 and trade['status'] == 'submitted'
    assert all(isinstance(row, LiveOrder) for row in db.added)


def test_paper_mode_never_calls_gateway():
    calls = fake_gateway()
    db, log = run_cycle(broker("paper"))
    trades = [t for t in log["trades"] if t.get("type") == "auto"]
    assert len(trades) == 1 and "live_order" not in trades[0]
    assert calls == [] and not any(isinstance(a, LiveOrder) for a in db.added)
    assert log["signals"][0]["basis"] == {"as_of": "2026-10-16", "interval": "1d", "normalized_score": None}


@pytest.mark.parametrize("status", LIVE_ORDER_OPEN_STATUSES)
@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_open_same_symbol_order_blocks_new_order_even_with_position_cap_room(status, side):
    calls = fake_gateway()
    # 280만 원 노출이면 한도상 2주 여유가 있어도, 같은 종목 열린 주문은 먼저 보류한다.
    open_row = LiveOrder(user_id=UID, client_order_id="c0", environment="paper", symbol="005930.KS", name="삼성전자", side=side,
                         order_type="LIMIT", quantity=40, price=70_000.0, status=status, filled_quantity=0)
    db, log = run_cycle(broker("live"), live_rows=[open_row])
    assert log["risk"].get("open_live_exposure", {}) == ({"005930.KS": 2_800_000.0} if side == "BUY" else {})
    trades = [t for t in log["trades"] if t.get("type") == "auto"]
    assert trades == []
    assert log["risk"]["skipped"] == [{"symbol": "005930.KS", "name": "삼성전자", "side": "buy",
        "reason": "같은 종목의 접수·체결 미확인 주문이 있어 새 주문을 보류합니다."}]
    assert not any(isinstance(row, LiveOrder) for row in db.added)
    assert not any(method == "POST" for method, _, _ in calls)


@pytest.mark.parametrize("status", ["FILLED", "CANCELLED", "REJECTED", "ERROR"])
def test_terminal_order_does_not_block_new_order_or_count_as_open_exposure(status):
    fake_gateway()
    row = LiveOrder(user_id=UID, symbol="005930.KS", side="BUY", quantity=40, price=70000,
                    status=status, filled_quantity=0)
    db, log = run_cycle(broker("live"), live_rows=[row])
    assert not log["risk"].get("open_live_exposure")
    trades = [t for t in log["trades"] if t.get("type") == "auto"]
    assert len(trades) == 1 and trades[0]["quantity"] == 4
    assert len([r for r in db.added if isinstance(r, LiveOrder)]) == 1


@pytest.mark.parametrize("other", ["symbol", "owner"])
def test_unrelated_open_order_does_not_block_selected_symbol(other):
    fake_gateway()
    row = LiveOrder(user_id=uuid.uuid4() if other == "owner" else UID,
                    symbol="000660.KS" if other == "symbol" else "005930.KS", side="BUY",
                    quantity=40, price=70000, status="ACCEPTED", filled_quantity=0)
    _, log = run_cycle(broker("live"), live_rows=[row])
    trades = [t for t in log["trades"] if t.get("type") == "auto"]
    assert len(trades) == 1 and trades[0]["quantity"] == 4
    assert log["risk"].get("open_live_exposure", {}) == ({"000660.KS": 2800000} if other == "symbol" else {})


@pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PG 필요")
@pytest.mark.usefixtures("rebalance_db_schema")
def test_open_buy_exposure_and_position_cap_with_real_database():
    """주문 허용 여부와 분리해, 원 시험의 같은 종목 노출·비중 계산 근거를 보존한다."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.models import User

    async def go():
        engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"])
        factory = async_sessionmaker(engine, expire_on_commit=False)
        uid, other = uuid.uuid4(), uuid.uuid4()
        try:
            async with factory() as db:
                db.add_all([User(id=u, name="exposure test", email=f"{u}@example.com",
                                 client_id=u.hex, password_hash="test") for u in (uid, other)])
                await db.flush()
                def order(**changes):
                    data = dict(user_id=uid, client_order_id=uuid.uuid4().hex, environment="paper",
                                symbol="005930.KS", side="BUY", order_type="LIMIT", quantity=40,
                                price=70000, status="ACCEPTED", filled_quantity=0)
                    return LiveOrder(**(data | changes))
                parent = order()
                db.add_all([parent, order(symbol="000660.KS", quantity=3, price=200000),
                            order(user_id=other), order(side="SELL"),
                            *[order(status=s) for s in ("FILLED", "CANCELLED", "REJECTED", "ERROR")]])
                await db.commit()
                for filled, expected_exposure, expected_qty in ((0, 2800000, 2), (10, 2100000, 12), (40, 0, 42)):
                    parent.filled_quantity = filled
                    parent.status = "PARTIALLY_FILLED" if filled else "ACCEPTED"
                    await db.commit()
                    exposure = await auto_trade.open_live_order_exposure(db, uid)
                    assert exposure == ({"005930.KS": expected_exposure, "000660.KS": 600000}
                                        if expected_exposure else {"000660.KS": 600000})
                    allowed, _ = auto_trade.risk_guard.cap_buy_quantity(50, 70000, exposure.get("005930.KS", 0), 10000000, 30)
                    assert allowed == expected_qty
                # 같은 종목의 여러 주문은 잔량을 합산하고 실제 보유 평가액도 상한에서 차감한다.
                parent.filled_quantity = 10
                db.add(order(quantity=5))
                await db.commit()
                exposure = await auto_trade.open_live_order_exposure(db, uid)
                assert exposure["005930.KS"] == 2450000
                assert auto_trade.risk_guard.cap_buy_quantity(50, 70000, 350000 + exposure["005930.KS"], 10000000, 30)[0] == 2
                assert auto_trade.risk_guard.cap_buy_quantity(50, 70000, 550000 + exposure["005930.KS"], 10000000, 30)[0] == 0
        finally:
            await engine.dispose()
    asyncio.run(go())


def test_kill_switch_blocks_cycle_without_orders():
    calls = fake_gateway()
    with patch.object(auto_trade, "set_enabled", AsyncMock()):
        db, log = run_cycle(broker("live", risk_kill_switch=True, risk_halt_reason="수동 정지"))
    assert log["risk"]["halted"] is True and log.get("trades") == [] and calls == []


def test_virtual_execution_uses_refreshed_price_for_quantity_and_keeps_signal_basis():
    calls = fake_gateway()
    _, log = run_cycle(broker("paper"), quote_price=100_000)
    trade = next(t for t in log["trades"] if t.get("type") == "auto")
    assert trade["price"] == 100_000 and trade["quantity"] == 3
    assert log["signals"][0]["price"] == 70_000
    assert trade["price_basis"]["signal_price"] == 70_000
    assert trade["price_basis"]["quote"]["source"] == "kis_user"
    assert calls == []


@pytest.mark.parametrize("price", [None, 0, -1, float("nan"), float("inf")])
def test_virtual_missing_or_invalid_execution_quote_never_trades(price):
    calls = fake_gateway()
    db, log = run_cycle(broker("paper"), quote_price=price)
    assert not any(t.get("type") == "auto" for t in log["trades"])
    assert any("가격·출처" in t.get("reason", "") for t in log["trades"])
    assert db.added == [] and calls == []


def test_unpriced_holding_blocks_entire_cycle_before_risk_baseline_or_orders():
    _, log = run_cycle(broker("paper"), quote_price=None,
                       positions=[SimpleNamespace(symbol="035720.KS", quantity=2, avg_price=50_000)])
    assert log["trades"] == [] and "주문 보류" in log["note"]
    assert log["risk"]["valuation"]["missing"] == ["035720.KS"]
    assert log["risk"]["day_pnl_pct"] is None
