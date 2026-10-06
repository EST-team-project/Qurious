"""리밸런싱 엔진 — 모의투자 계좌(현금 + 주식 포지션)를 목표 비중으로 되돌린다.

트리거
  TIME     : plan.time_period(monthly/quarterly/yearly) 주기의 next_run_at 도래
  DRIFT    : |현재 비중 − 목표 비중| 최대값 ≥ plan.drift_threshold_pct (%p)
  CASHFLOW : 현금 초과/부족과 누적 미사용 재배분 예산 중 작은 금액 ≥ 기준
  MANUAL   : 사용자가 화면에서 직접 실행

흐름
  snapshot()  → 현재 비중·이탈률 계산
  propose()   → 목표 비중과의 차액을 주문(매도 먼저, 매수 나중)으로 변환
  execute()   → paper_trading.stock_order 로 모의 체결하고 RebalanceRun 기록
  check_due() → TIME/DRIFT/CASHFLOW 트리거 점검(스케줄러·API 공용)
"""
from __future__ import annotations

import asyncio
import calendar
import logging
import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CashflowEvent, RebalancePlan, RebalanceRun
from app.models.rebalance import CASHFLOW_KINDS, TIME_PERIODS
from app.services import paper_trading as pt
from app.services import rebalance_policy as policy
from app.services import rebalance_schedule as schedule
from app.services import rebalance_daily as daily
from app.services import rebalance_prices as prices, rebalance_settlement as settlement

logger = logging.getLogger(__name__)

ORDER_SOURCE = "REBALANCE"
KST = ZoneInfo("Asia/Seoul")


class RebalanceError(Exception):
    pass


async def lock_user(db: AsyncSession, user_id: uuid.UUID):
    # Transaction-scoped, shared by every rebalance mutation (including first plan creation).
    key = int.from_bytes(hashlib.sha256(("rebalance:" + str(user_id)).encode()).digest()[:8], "big", signed=True)
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def checked_number(value, name, minimum=0, maximum=None):
    try:
        return policy.number(value, name, minimum, maximum)
    except ValueError as exc:
        raise RebalanceError(str(exc)) from exc


# ── 플랜 ────────────────────────────────────────────────────────────────


async def get_plan(db: AsyncSession, user_id: uuid.UUID, create: bool = True) -> RebalancePlan | None:
    await lock_user(db, user_id)
    row = (await db.execute(select(RebalancePlan).where(RebalancePlan.user_id == user_id)
                           .execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None and create:
        row = RebalancePlan(user_id=user_id, targets=[])
        db.add(row)
        await db.flush()
    return row


def normalize_targets(raw: list[dict]) -> list[dict]:
    """[{symbol, name?, weight_pct}] 검증. 합계 100 초과 금지, 중복 심볼 병합."""
    merged: dict[str, dict] = {}
    for t in raw or []:
        symbol = pt.normalize_stock_symbol(str(t.get("symbol", "")))
        if not symbol:
            continue
        try:
            w = float(t.get("weight_pct", 0))
        except (TypeError, ValueError):
            raise RebalanceError(f"{symbol}: 비중은 숫자여야 합니다.")
        w = checked_number(w, "목표 비중", 0, 100)
        if w < 0 or w > 100:
            raise RebalanceError(f"{symbol}: 비중은 0~100 사이여야 합니다.")
        if symbol in merged:
            merged[symbol]["weight_pct"] += w
        else:
            merged[symbol] = {"symbol": symbol, "name": str(t.get("name") or symbol)[:100], "weight_pct": w}
    total = sum(t["weight_pct"] for t in merged.values())
    if total > 100.0001:
        raise RebalanceError(f"목표 비중 합계가 100%를 초과합니다 ({total:.1f}%). 잔여분은 현금으로 배분됩니다.")
    return [{**t, "weight_pct": round(t["weight_pct"], 2)} for t in merged.values()]


async def resolve_targets(raw: list[dict]) -> list[dict]:
    """입력 심볼을 모의투자 표준 심볼(005930 → 005930.KS)과 종목명으로 확정한다."""
    resolved = []
    for t in raw or []:
        sym = str(t.get("symbol", "")).strip()
        if not sym:
            continue
        try:
            info = await pt.resolve_stock(sym)
        except pt.PaperTradeError as exc:
            raise RebalanceError(str(exc))
        resolved.append({"symbol": info["symbol"], "name": info["name"], "weight_pct": t.get("weight_pct", 0)})
    return normalize_targets(resolved)


def _add_months(dt: datetime, months: int) -> datetime:
    month0 = dt.month - 1 + months
    year = dt.year + month0 // 12
    month = month0 % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def next_period_start(now: datetime, period: str) -> datetime | None:
    """다음 주기의 첫 거래일 09:00 KST. 달력 부족 시 CalendarUnavailable."""
    anchor = schedule.next_boundary(now, period)
    return schedule.first_trading_time(anchor, period) if anchor else None


async def refresh_time_schedule(plan, now=None):
    now = now or datetime.now(timezone.utc)
    state = await asyncio.to_thread(schedule.resolve, plan.time_period, plan.next_run_at, now)
    plan.next_run_at = state["next_run_at"]
    plan.time_schedule_error = state["error"]
    return state


async def advance_time_schedule(plan, now):
    # Keep the period anchor if next year's calendar is not ready; never roll back fills.
    plan.next_run_at = schedule.next_boundary(now, plan.time_period)
    await refresh_time_schedule(plan, now)


def apply_plan_update(plan: RebalancePlan, data: dict) -> RebalancePlan:
    if "name" in data and data["name"]:
        plan.name = str(data["name"])[:60]
    if "is_active" in data:
        plan.is_active = bool(data["is_active"])
    if "targets" in data:
        plan.targets = normalize_targets(data["targets"])
    if "time_period" in data:
        period = str(data["time_period"] or "none")
        if period not in TIME_PERIODS:
            raise RebalanceError(f"지원하지 않는 주기입니다: {period}")
        if period != plan.time_period or plan.next_run_at is None:
            plan.next_run_at = schedule.next_boundary(datetime.now(timezone.utc), period)
        plan.time_period = period
    if "drift_enabled" in data:
        plan.drift_enabled = bool(data["drift_enabled"])
    if "drift_threshold_pct" in data:
        v = checked_number(data["drift_threshold_pct"], "허용 이탈률", 0.5, 50)
        if v * 2 != int(v * 2):
            raise RebalanceError("허용 이탈률은 0.5%p 단위로 입력하세요.")
        if not 0.5 <= v <= 50:
            raise RebalanceError("허용 이탈률은 0.5~50%p 사이여야 합니다.")
        plan.drift_threshold_pct = v
    if "cashflow_enabled" in data:
        plan.cashflow_enabled = bool(data["cashflow_enabled"])
    if "cashflow_min_amount" in data:
        plan.cashflow_min_amount = checked_number(data["cashflow_min_amount"], "현금흐름 기준")
    if "auto_execute" in data:
        plan.auto_execute = bool(data["auto_execute"])
    if "min_order_amount" in data:
        plan.min_order_amount = checked_number(data["min_order_amount"], "최소 주문금액")
    if "drift_check_mode" in data:
        if data["drift_check_mode"] not in ("always", "scheduled"):
            raise RebalanceError("지원하지 않는 이탈 확인 시점입니다.")
        plan.drift_check_mode = data["drift_check_mode"]
    if "exclude_unplanned" in data:
        plan.exclude_unplanned = bool(data["exclude_unplanned"])
    if plan.drift_check_mode == "scheduled" and (plan.time_period == "none" or not plan.drift_enabled):
        raise RebalanceError("주기 도래 시에만 확인하려면 시간 주기와 이탈률을 모두 켜세요.")
    return plan


def plan_to_dict(plan: RebalancePlan) -> dict:
    stock_total = sum(float(t.get("weight_pct", 0)) for t in (plan.targets or []))
    return {
        "id": str(plan.id), "name": plan.name, "is_active": plan.is_active,
        "targets": plan.targets or [], "cash_weight_pct": round(100 - stock_total, 2),
        "time_period": plan.time_period,
        "drift_check_mode": plan.drift_check_mode, "exclude_unplanned": plan.exclude_unplanned,
        "next_run_at": (plan.next_run_at.isoformat() if plan.next_run_at
                        and not getattr(plan, "time_schedule_error", None) else None),
        "time_schedule_error": getattr(plan, "time_schedule_error", None),
        "drift_enabled": plan.drift_enabled, "drift_threshold_pct": plan.drift_threshold_pct,
        "cashflow_enabled": plan.cashflow_enabled, "cashflow_min_amount": plan.cashflow_min_amount,
        "auto_execute": plan.auto_execute, "min_order_amount": plan.min_order_amount,
        "last_run_at": plan.last_run_at.isoformat() if plan.last_run_at else None,
        "last_auto_check_date": plan.last_auto_check_date.isoformat() if plan.last_auto_check_date else None,
        "last_auto_check_at": plan.last_auto_check_at.isoformat() if plan.last_auto_check_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }


# ── 스냅샷(현재 비중·이탈률) ──────────────────────────────────────────────


async def snapshot(db: AsyncSession, user_id: uuid.UUID, plan: RebalancePlan) -> dict:
    """현금 + 주식 포지션 기준 현재 비중과 목표 대비 이탈률."""
    account = await pt.get_account(db, user_id)
    positions = await pt.stock_positions(db, user_id)
    # The shared position service silently falls back to average purchase price on quote failure.
    # Rebalancing must not interpret that fallback as a current market price.
    for position in positions:
        if plan.exclude_unplanned and position["symbol"] not in {t["symbol"] for t in plan.targets}:
            continue
        try:
            quote = await pt.resolve_stock(position["symbol"])
            price = checked_number(quote["price"], "시세", 0.000001)
        except (pt.PaperTradeError, KeyError, RebalanceError) as exc:
            raise RebalanceError(f"{position['symbol']}: 현재 시세를 확인할 수 없어 판정을 중단합니다.") from exc
        position["currentPrice"] = price
        position["evalAmount"] = price * position["quantity"]
    result = policy.weights(float(account.cash), positions, plan.targets or [], plan.drift_threshold_pct,
                            plan.drift_enabled, plan.exclude_unplanned)
    events = await pending_cashflows(db, user_id)
    result.update(policy.cashflow_signal(result["cash_excess"], sum(e.remaining_budget for e in events),
                                         plan.cashflow_min_amount))
    result["observed_at"] = datetime.now(timezone.utc).isoformat()
    result["price_basis"] = "current_quote"
    return result


def _weights_from_snapshot(snap: dict) -> dict:
    w = {r["symbol"]: r["current_weight_pct"] for r in snap["rows"]}
    w["CASH"] = snap["cash_weight_pct"]
    return w


# ── 주문 산출 ────────────────────────────────────────────────────────────


async def propose(db: AsyncSession, user_id: uuid.UUID, plan: RebalancePlan, snap: dict | None = None,
                  plan_kind: str = "full") -> dict:
    if not plan.targets:
        raise RebalanceError("목표 비중이 비어 있습니다. 먼저 종목과 비중을 저장하세요.")
    snap = snap or await snapshot(db, user_id, plan)
    if snap["total_asset"] <= 0:
        raise RebalanceError("평가 가능한 자산이 없습니다.")
    prices = {r["symbol"]: float(r["price"]) for r in snap["rows"] if r["price"]}
    for target in plan.targets:
        if target["symbol"] not in prices:
            try:
                prices[target["symbol"]] = float((await pt.resolve_stock(target["symbol"]))["price"])
            except pt.PaperTradeError as exc:
                raise RebalanceError(f"{target['symbol']}: 시세 조회 실패") from exc
    budget = snap["cashflow_available"] if plan_kind != "full" else None
    return policy.orders(snap, prices, plan.min_order_amount, plan_kind, budget)


# ── 실행 ────────────────────────────────────────────────────────────────


def fingerprint(plan):
    keys = ("targets", "time_period", "drift_enabled", "drift_threshold_pct", "drift_check_mode",
            "cashflow_enabled", "cashflow_min_amount", "exclude_unplanned", "min_order_amount")
    payload = {key: getattr(plan, key) for key in keys}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def proposal_context(plan, proposal):
    return {"settings_fingerprint": fingerprint(plan), "observed_at": proposal["snapshot"]["observed_at"],
            "price_basis": proposal["snapshot"]["price_basis"],
            **{k: proposal["snapshot"][k] for k in ("valuation_date", "account_stamp") if k in proposal["snapshot"]},
            "estimated_cost": proposal["estimated_cost"],
            "estimated_cash_after": proposal["estimated_cash_after"]}


async def pending_cashflows(db, user_id):
    return list((await db.execute(select(CashflowEvent).where(
        CashflowEvent.user_id == user_id, CashflowEvent.remaining_budget != 0
    ).order_by(CashflowEvent.created_at, CashflowEvent.id))).scalars().all())


async def consume_budget(db, user_id, run, executed):
    events = await pending_cashflows(db, user_id)
    filled = [o for o in executed if o["status"] == "filled"]
    if not filled:
        return
    clear_all = run.plan_kind == "full" and len(filled) == len(executed)
    spent = sum(o["net_amount"] * (1 if o["side"] == "BUY" else -1) for o in filled)
    for event in events:
        if clear_all:
            event.remaining_budget = 0
            event.rebalance_run_id = run.id
        elif event.remaining_budget * spent > 0:
            used = min(abs(event.remaining_budget), abs(spent)) * (1 if spent > 0 else -1)
            event.remaining_budget = round(event.remaining_budget - used, 8)
            spent -= used
            event.rebalance_run_id = run.id


async def record_proposal(db, user_id, plan, triggers, proposal, note="", existing=None):
    triggers = [triggers] if isinstance(triggers, str) else triggers
    run = existing or RebalanceRun(user_id=user_id, plan_id=plan.id)
    run.trigger, run.triggers = triggers[0], list(triggers)
    run.plan_kind = proposal["plan_kind"]
    run.decision_date = datetime.now(KST).date()
    run.status = "proposed"
    run.total_asset = proposal["snapshot"]["total_asset"]
    run.max_drift_pct = proposal["snapshot"]["max_drift_pct"]
    run.before_weights = _weights_from_snapshot(proposal["snapshot"])
    run.target_weights = {t["symbol"]: t["weight_pct"] for t in plan.targets}
    run.target_weights = {**run.target_weights, "CASH": proposal["snapshot"]["cash_target_pct"]}
    run.orders, run.context = proposal["orders"], proposal_context(plan, proposal)
    run.note = note[:300]
    if existing is None:
        db.add(run)
    await db.flush()
    return run


async def execute(db: AsyncSession, user_id: uuid.UUID, plan: RebalancePlan, trigger: str,
                  proposal: dict | None = None, note: str = "", existing=None) -> RebalanceRun:
    await lock_user(db, user_id)
    await pt.get_account(db, user_id, lock=True)
    proposal = proposal or await propose(db, user_id, plan)
    run = existing or await record_proposal(db, user_id, plan, [trigger], proposal, note)
    executed = []
    for order in proposal["orders"]:
        rec = dict(order)
        try:
            async with db.begin_nested():
                res = await pt.stock_order(db, user_id, order["symbol"], order["side"], int(order["quantity"]), source=ORDER_SOURCE)
            rec.update(status="filled", price=res["price"], amount=res["amount"],
                       net_amount=res["net_amount"], cost=res["cost"])
        except pt.PaperTradeError as exc:
            rec.update(status="failed", error=str(exc))
        executed.append(rec)
    count = sum(o["status"] == "filled" for o in executed)
    run.status = ("executed" if count == len(executed) else "partial") if count else ("failed" if executed else "skipped")
    run.orders = executed
    run.context = {**proposal_context(plan, proposal), "executed_at": datetime.now(timezone.utc).isoformat(),
                   "actual_cost": round(sum(o['cost']['total_cost'] for o in executed if o['status'] == 'filled'), 2)}
    await consume_budget(db, user_id, run, executed)
    try:
        run.after_weights = _weights_from_snapshot(await snapshot(db, user_id, plan))
    except RebalanceError:
        run.after_weights = {}
        run.context = {**run.context, "after_weights_unavailable": True}
    if count:
        plan.last_run_at = datetime.now(timezone.utc)
    if "TIME" in (run.triggers or [trigger]):
        await advance_time_schedule(plan, datetime.now(timezone.utc))
    await db.flush()
    return run


async def check_due(db: AsyncSession, user_id: uuid.UUID, plan: RebalancePlan, *, valuation_date=None) -> dict:
    await lock_user(db, user_id)
    await db.refresh(plan)
    result = dict(time_due=False, drift_due=False, cashflow_due=False, run_id=None, trigger=None, triggers=[])
    if not plan.is_active or not plan.targets:
        return result
    # Serialize against ordinary orders too, so a cashflow/approval cannot spend the same balance.
    await pt.get_account(db, user_id, lock=True)
    now = datetime.now(timezone.utc)
    reserved = await settlement.pending(db, user_id)
    if reserved:
        return {**result, "run_id": str(reserved.id), "status": "scheduled", "already_processed": True}
    timing = await refresh_time_schedule(plan, now)
    result["time_schedule_error"] = timing["error"]
    today = now.astimezone(KST).date()
    existing = (await db.execute(select(RebalanceRun).where(
        RebalanceRun.plan_id == plan.id, RebalanceRun.decision_date == today,
        RebalanceRun.trigger != "MANUAL").with_for_update())).scalar_one_or_none()
    if existing and existing.status in ("executed", "partial", "failed"):
        return {**result, "run_id": str(existing.id), "status": existing.status, "already_processed": True,
                "price_basis": existing.context.get("price_basis", "current_quote")}
    # Manual checks must not overwrite or immediately fill an automatic close proposal.
    if existing and existing.status == "proposed" and existing.context.get("price_basis") == "previous_close" and valuation_date is None:
        return {**result, "run_id": str(existing.id), "status": existing.status, "already_processed": True,
                "price_basis": existing.context.get("price_basis", "current_quote")}
    try:
        snap = (await settlement.close_snapshot(db, user_id, plan, valuation_date) if valuation_date
                else await snapshot(db, user_id, plan))
    except prices.PriceUnavailable as exc:
        raise RebalanceError(str(exc)) from exc
    # Creating a proposal advances next_run_at. Keep its due date effective until
    # today's proposal is handled; otherwise the next hourly check cancels it.
    pending_time = bool(existing and existing.status == "proposed" and "TIME" in existing.triggers
                        and existing.context.get("settings_fingerprint") == fingerprint(plan)
                        and timing["trading_today"] and now.astimezone(KST).hour >= 9)
    result.update(time_due=pending_time or timing["time_due"],
                  drift_due=snap["drift_exceeded"], cashflow_due=bool(plan.cashflow_enabled and snap["cashflow_due"]),
                  max_drift_pct=snap["max_drift_pct"])
    triggers = policy.choose_triggers(result["time_due"], result["drift_due"], plan.drift_check_mode,
                                      result["cashflow_due"], plan.drift_enabled)
    if not triggers:
        if existing and existing.status == "proposed":
            existing.status, existing.note = "skipped", "현재 조건 미충족 · 다시 점검하면 재산출"
        if result["time_due"]:
            await advance_time_schedule(plan, now)
        return result
    # Keep concurrent conditions on the same still-pending decision, unless settings changed.
    if existing and existing.status == "proposed" and existing.context.get("settings_fingerprint") == fingerprint(plan):
        triggers = [t for t in ("TIME", "DRIFT", "CASHFLOW") if t in triggers
                    or (t in existing.triggers and (t != "TIME" or result["time_due"])
                        and (t != "DRIFT" or plan.drift_check_mode != "scheduled" or result["time_due"]))]
    kind = "full" if any(t in triggers for t in ("TIME", "DRIFT")) else snap["plan_kind"]
    proposal = await propose(db, user_id, plan, snap, kind)
    run = await record_proposal(db, user_id, plan, triggers, proposal, "조건 충족 · 전 거래일 종가로 산출" if valuation_date else "조건 충족 · 현재 시세로 산출", existing)
    if not proposal["orders"]:
        run.status, run.note = "skipped", "최소 주문금액·정수 수량 또는 목표 비중 조건으로 주문 없음"
    elif plan.auto_execute and valuation_date:
        try:
            run = await settlement.reserve(db, user_id, plan, run)
        except prices.PriceUnavailable as exc:
            raise RebalanceError(str(exc)) from exc
    elif plan.auto_execute:
        run = await execute(db, user_id, plan, triggers[0], proposal, existing=run)
    if "TIME" in triggers:
        await advance_time_schedule(plan, now)
    result.update(run_id=str(run.id), trigger=triggers[0], triggers=triggers, status=run.status)
    await db.flush()
    return result


async def check_daily(db, user_id, plan):
    """성공한 정기 판정만 날짜를 저장한다. 잠금과 완료 기록은 주문과 같은 트랜잭션이다."""
    await lock_user(db, user_id)
    await db.refresh(plan)
    now = datetime.now(timezone.utc)
    today = now.astimezone(KST).date()
    if not plan.is_active or not plan.targets:
        return {"checked": False, "reason": "inactive"}
    if plan.last_auto_check_date == today:
        return {"checked": False, "reason": "already_checked"}
    # A new collector run may have started while another plan was being checked.
    readiness = await asyncio.to_thread(daily.readiness)
    if not readiness["ready"] or readiness["decision_date"] != today.isoformat():
        return {"checked": False, "reason": "data_waiting"}
    pending_run = await settlement.settle(db, user_id, plan, readiness)
    if pending_run and pending_run.status == "scheduled":
        return {"checked": False, "reason": "settlement_waiting", "run_id": str(pending_run.id)}
    result = await check_due(db, user_id, plan, valuation_date=date.fromisoformat(readiness["data_as_of"]))
    plan.last_auto_check_date = today
    plan.last_auto_check_at = datetime.now(timezone.utc)
    plan.last_auto_check_result = {
        "data_as_of": readiness["data_as_of"], "update_finished_at": readiness["update_finished_at"],
        "run_id": result.get("run_id"), "triggers": result.get("triggers", []),
        "status": result.get("status", "no_action"), "already_processed": result.get("already_processed", False),
        "price_basis": result.get("price_basis", "previous_close"),
    }
    await db.flush()
    return {**result, "checked": True}


async def check_all_due(session_factory) -> dict:
    """5분마다 갱신 완료 여부를 확인하고, 준비된 거래일에 플랜마다 한 번 판정한다."""
    readiness = await asyncio.to_thread(daily.readiness)
    checked = executed = proposed = skipped = errors = 0
    if not readiness["ready"]:
        return dict(checked=0, executed=0, proposed=0, skipped=0, errors=0, readiness=readiness)
    async with session_factory() as db:
        user_ids = (await db.execute(select(RebalancePlan.user_id))).scalars().all()
        for user_id in user_ids:
            try:
                plan = await get_plan(db, user_id, create=False)
                if plan is None:
                    continue
                settled = await settlement.settle(db, user_id, plan, await asyncio.to_thread(daily.readiness))
                # Commit settlement independently: a missing price for a new decision must not undo it.
                await db.commit()
                if settled and settled.status == "executed":
                    executed += 1
                r = await check_daily(db, user_id, plan)
                if not r["checked"]:
                    await db.commit()
                    skipped += 1
                    continue
                await db.commit()
                checked += 1
                if r.get("status") == "executed":
                    executed += 1
                elif r.get("status") == "proposed":
                    proposed += 1
            except Exception:
                errors += 1
                await db.rollback()
                # Rollback expires ORM objects; log the scalar ID and load each
                # next plan afresh so one quote failure cannot stop the batch.
                logger.exception("리밸런싱 점검 실패 user=%s", user_id)
    return dict(checked=checked, executed=executed, proposed=proposed, skipped=skipped, errors=errors,
                readiness=readiness)


# ── 현금흐름(입금·출금·배당) ────────────────────────────────────────────


async def record_cashflow(db: AsyncSession, user_id: uuid.UUID, kind: str, amount: float,
                          symbol: str = "", memo: str = "") -> dict:
    """현금흐름을 모의계좌에 반영하고, 플랜 조건 충족 시 CASHFLOW 리밸런싱을 실행/제안한다."""
    kind = (kind or "").upper()
    if kind not in CASHFLOW_KINDS:
        raise RebalanceError("kind는 DEPOSIT, WITHDRAW, DIVIDEND 중 하나여야 합니다.")
    amount = checked_number(amount, "이벤트 금액", 0.00000001)
    if amount <= 0:
        raise RebalanceError("금액은 0보다 커야 합니다.")

    plan = await get_plan(db, user_id)
    account = await pt.get_account(db, user_id, lock=True)
    if kind == "WITHDRAW":
        if amount > account.cash:
            raise RebalanceError(f"출금 가능 현금이 부족합니다 (보유 {account.cash:,.0f}원).")
        account.cash = float(account.cash - amount)
    else:
        account.cash = float(account.cash + amount)
    if kind == "DIVIDEND" and symbol:
        symbol = pt.normalize_stock_symbol(symbol)

    budget = amount * sum(t["weight_pct"] for t in plan.targets)/100
    budget *= -1 if kind == "WITHDRAW" else 1
    # Only external events enter this ledger; opposite events net out before sizing orders.
    for old in await pending_cashflows(db, user_id):
        if budget * old.remaining_budget < 0:
            cancelled = min(abs(budget), abs(old.remaining_budget)) * (1 if budget > 0 else -1)
            old.remaining_budget = round(old.remaining_budget + cancelled, 8)
            budget -= cancelled
    event = CashflowEvent(user_id=user_id, kind=kind, amount=amount, symbol=symbol or "", remaining_budget=budget,
                          memo=(memo or "")[:200], cash_after=account.cash)
    db.add(event)
    await db.flush()
    await db.refresh(event)

    try:
        result = await check_due(db, user_id, plan)
    except RebalanceError as exc:
        # The cash event is valid even when its market-price-dependent decision must wait.
        await db.flush()
        return {"event": cashflow_to_dict(event), "run": None, "check_error": str(exc)}
    run = await db.get(RebalanceRun, uuid.UUID(result["run_id"])) if result.get("run_id") else None
    if run and not result.get("already_processed"):
        event.rebalance_run_id = run.id
    await db.flush()
    return {"event": cashflow_to_dict(event), "run": run_to_dict(run) if run else None,
            "already_processed": result.get("already_processed", False)}


def cashflow_to_dict(e: CashflowEvent) -> dict:
    return {"id": str(e.id), "kind": e.kind, "amount": e.amount, "symbol": e.symbol, "memo": e.memo,
            "cash_after": e.cash_after, "remaining_budget": e.remaining_budget, "rebalance_run_id": str(e.rebalance_run_id) if e.rebalance_run_id else None,
            "created_at": e.created_at.isoformat() if e.created_at else None}


def run_to_dict(r: RebalanceRun) -> dict:
    return {"id": str(r.id), "trigger": r.trigger, "triggers": r.triggers or [r.trigger],
            "plan_kind": r.plan_kind, "decision_date": r.decision_date.isoformat() if r.decision_date else None,
            "context": r.context, "status": r.status, "total_asset": r.total_asset,
            "max_drift_pct": r.max_drift_pct, "before_weights": r.before_weights, "target_weights": r.target_weights,
            "after_weights": r.after_weights, "orders": r.orders, "note": r.note,
            "created_at": r.created_at.isoformat() if r.created_at else None}


async def list_runs(db: AsyncSession, user_id: uuid.UUID, limit: int = 30) -> list[dict]:
    rows = (await db.execute(select(RebalanceRun).where(RebalanceRun.user_id == user_id)
                             .order_by(RebalanceRun.created_at.desc()).limit(limit))).scalars().all()
    return [run_to_dict(r) for r in rows]


async def list_cashflows(db: AsyncSession, user_id: uuid.UUID, limit: int = 50) -> list[dict]:
    rows = (await db.execute(select(CashflowEvent).where(CashflowEvent.user_id == user_id)
                             .order_by(CashflowEvent.created_at.desc()).limit(limit))).scalars().all()
    return [cashflow_to_dict(e) for e in rows]


async def execute_proposal(db: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> RebalanceRun:
    """Approve once, retain order direction, recalculate current prices and budget."""
    plan = await get_plan(db, user_id)
    row = (await db.execute(select(RebalanceRun).where(RebalanceRun.id == run_id, RebalanceRun.user_id == user_id)
                           .with_for_update())).scalar_one_or_none()
    if row is None or row.status != "proposed":
        raise RebalanceError("제안이 없거나 이미 처리되었습니다.")
    if not plan.is_active:
        raise RebalanceError("플랜이 비활성화되었습니다.")
    if row.decision_date != datetime.now(KST).date():
        raise RebalanceError("지난 날짜의 제안입니다. 지금 점검으로 새 제안을 만드세요.")
    if row.context.get("settings_fingerprint") != fingerprint(plan):
        raise RebalanceError("설정이 바뀌었습니다. 지금 점검으로 제안을 다시 계산하세요.")
    if plan.last_run_at and row.created_at < plan.last_run_at:
        raise RebalanceError("이 제안 이후 체결이 발생했습니다. 지금 점검으로 다시 계산하세요.")
    if "TIME" in row.triggers:
        # A calendar correction must also be respected when approving an older proposal.
        timing = await refresh_time_schedule(plan)
        if not timing["trading_today"] or datetime.now(KST).hour < 9:
            raise RebalanceError("시간 제안 승인 대기: " + (timing["error"] or "거래일 오전 9시 이후에 승인할 수 있습니다."))
    if row.context.get("price_basis") == "previous_close":
        try:
            return await settlement.reserve(db, user_id, plan, row)
        except prices.PriceUnavailable as exc:
            raise RebalanceError(str(exc)) from exc
    await pt.get_account(db, user_id, lock=True)
    proposal = await propose(db, user_id, plan, plan_kind=row.plan_kind)
    return await execute(db, user_id, plan, row.trigger, proposal, existing=row)
