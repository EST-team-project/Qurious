"""그림자 일지 ↔ KIS 모의 전략 시험 체결 대사.

대상은 kis_trial_signal 뿐이다. 시험 준비 매수(kis_trial_setup), 다른 전략,
실전 계좌, 게이트웨이 주문은 비교하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import (
    BrokerSettings,
    LiveOrder,
    OrderIntent,
    PaperJournalDay,
    PaperJournalVersion,
    PaperKisReconciliation,
)
from app.services import kis_execution

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
JOURNAL_RULE_ID = "card_ma_cross_20_60"
JOURNAL_VERSION_NO = 1
KIS_STRATEGY_ID = "kis_ma20_60_trial"
KIS_STRATEGY_VERSION = 1
KIS_SOURCE = "kis_trial_signal"
KIS_BOOK = "KIS"
SYMBOL = "005930.KS"


def _action_side(action) -> str | None:
    value = str(action or "").strip()
    if value in ("매수", "강력 매수", "BUY"):
        return "BUY"
    if value in ("매도", "강력 매도", "SELL"):
        return "SELL"
    return None


def _decision_date(result: dict) -> date | None:
    """Intent 결과에 보존한 실제 판단 봉(bar_end_at)의 날짜."""
    basis = (result or {}).get("price_basis") or {}
    decision = basis.get("decision") or {}
    raw = decision.get("bar_end_at")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if value.tzinfo is None:
            return None
        return value.astimezone(KST).date()
    except (TypeError, ValueError):
        return None


def _adverse_bps(side: str, reference: float | None, actual: float | None) -> float | None:
    """양수 = 기준 가격보다 불리한 체결. BUY/SELL 방향을 각각 반영한다."""
    try:
        ref, got = float(reference), float(actual)
    except (TypeError, ValueError):
        return None
    if (side not in ("BUY", "SELL") or not math.isfinite(ref) or not math.isfinite(got)
            or ref <= 0 or got <= 0):
        return None
    raw = (got / ref - 1) if side == "BUY" else (ref / got - 1)
    return round(raw * 10_000, 4)


def _symbol_key(value) -> str:
    return str(value or "").replace(".KS", "").replace(".KQ", "")[:6]


def _one(rows: list[dict]) -> tuple[dict | None, bool]:
    if len(rows) == 1:
        return rows[0], False
    return None, len(rows) > 1


def _journal_matches(days: list, decision_date: date, side: str):
    day = next((r for r in days if r.trade_date == decision_date), None)
    if day is None:
        return day, None, None, None, None, "paper_day_missing"

    decision_rows = [
        x for x in (day.decisions or [])
        if _symbol_key(x.get("symbol")) == SYMBOL[:6]
    ]
    decision, decision_ambiguous = _one(decision_rows)
    if decision_ambiguous:
        return day, None, None, None, None, "paper_decision_ambiguous"
    if decision is None:
        return day, None, None, None, None, "paper_decision_missing"

    paper_side = _action_side(decision.get("action"))
    if paper_side != side:
        return day, decision, None, None, None, "signal_mismatch"

    order_rows = [
        x for x in (day.orders or [])
        if _symbol_key(x.get("symbol")) == SYMBOL[:6]
        and str(x.get("side") or "").upper() == side
    ]
    order, order_ambiguous = _one(order_rows)
    if order_ambiguous:
        return day, decision, None, None, None, "paper_order_ambiguous"
    if order is None:
        return day, decision, None, None, None, "paper_order_missing"

    fill_rows = []
    fill_day_for_row = {}
    for later in days:
        if later.trade_date <= decision_date:
            continue
        for fill in (later.fills or []):
            if (fill.get("decision_date") == decision_date.isoformat()
                    and _symbol_key(fill.get("symbol")) == SYMBOL[:6]
                    and str(fill.get("side") or "").upper() == side):
                fill_rows.append(fill)
                fill_day_for_row[id(fill)] = later.trade_date

    fill, fill_ambiguous = _one(fill_rows)
    if fill_ambiguous:
        return day, decision, order, None, None, "paper_fill_ambiguous"
    if fill is None:
        return day, decision, order, None, None, "paper_fill_pending"
    return day, decision, order, fill, fill_day_for_row[id(fill)], "paper_ready"


async def _live_order_for(db, intent: OrderIntent):
    result = intent.result if isinstance(intent.result, dict) else {}
    client_id = result.get("client_order_id") or ("intent:" + intent.intent_id[:57])
    rows = (await db.execute(select(LiveOrder).where(
        LiveOrder.user_id == intent.user_id,
        LiveOrder.client_order_id == client_id,
    ))).scalars().all()
    if len(rows) != 1:
        return client_id, None, len(rows) > 1
    return client_id, rows[0], False


async def _make_snapshot(db, intent, journal_version, journal_days, broker_row, now):
    result = intent.result if isinstance(intent.result, dict) else {}
    basis = result.get("price_basis") or {}
    kis_decision = basis.get("decision") or {}
    decision_date = _decision_date(result)

    # Intent가 잘못됐거나 기대한 시험 신호가 아니면 추정 날짜로 매칭하지 않는다.
    if (decision_date is None or kis_decision.get("strategy_id") != "ma_cross_20_60"
            or kis_decision.get("version") != 1
            or _symbol_key(kis_decision.get("symbol")) != SYMBOL[:6]
            or str(kis_decision.get("action") or "").upper() != intent.side.upper()
            or intent.side not in ("BUY", "SELL")):
        paper_day = paper_decision = paper_order = paper_fill = paper_fill_date = None
        paper_state = "invalid_kis_decision"
    elif journal_version is None:
        paper_day = paper_decision = paper_order = paper_fill = paper_fill_date = None
        paper_state = "paper_rule_not_registered"
    else:
        paper_day, paper_decision, paper_order, paper_fill, paper_fill_date, paper_state = (
            _journal_matches(journal_days, decision_date, intent.side.upper())
        )

    client_id, live_order, live_ambiguous = await _live_order_for(db, intent)
    proof = None
    proof_error = None
    live_state = "kis_order_missing"

    if live_ambiguous:
        live_state = "kis_order_ambiguous"
    elif live_order is not None:
        if broker_row is None or broker_row.broker != "kis":
            live_state = "kis_settings_missing"
        elif (live_order.account_ref != intent.account_ref
                or live_order.environment != "paper"
                or live_order.broker != "kis-direct"
                or live_order.strategy_id != intent.strategy_id
                or live_order.strategy_version != intent.strategy_version
                or live_order.symbol != intent.symbol
                or live_order.side.upper() != intent.side.upper()):
            live_state = "kis_order_identity_mismatch"
        else:
            try:
                # 이 함수는 ODNO·주문일·종목·방향·수량·계좌 fingerprint를 모두 확인한다.
                proof = await kis_execution.direct_status(live_order, broker_row)
                live_state = "kis_fill_confirmed" if proof is not None else "kis_fill_unconfirmed"
            except RuntimeError:
                proof_error = "account_or_credentials"
                live_state = "kis_account_or_credentials_error"
            except Exception as exc:
                proof_error = type(exc).__name__
                live_state = "kis_query_failed"
                logger.warning("Paper↔KIS 체결 조회 실패 intent=%s type=%s",
                               intent.intent_id[:12], type(exc).__name__)

    paper_side = _action_side(paper_decision.get("action")) if paper_decision else None
    signal_aligned = bool(paper_side == intent.side.upper()
                          and str(kis_decision.get("action") or "").upper() == intent.side.upper())

    paper_order_qty = int(paper_order["qty"]) if paper_order and paper_order.get("qty") is not None else None
    paper_fill_qty = int(paper_fill["qty_filled"]) if paper_fill and paper_fill.get("qty_filled") is not None else None
    paper_fill_price = paper_fill.get("fill_price") if paper_fill else None
    paper_fill_status = str(paper_fill.get("status")) if paper_fill else None

    # KIS 필드는 direct_status가 증권사 원장과 정확히 매칭한 경우에만 채운다.
    # LiveOrder 값은 우리 서버의 추적 기록이므로 별도 tracked_* 필드에 보존한다.
    kis_order_qty = int(proof["orderedQuantity"]) if proof else None
    kis_filled_qty = int(proof["filledQuantity"]) if proof else None
    kis_remaining = proof.get("remainingQuantity") if proof else None
    kis_cancelled = proof.get("cancelledQuantity") if proof else None
    evidence_complete = bool(proof["quantityEvidenceComplete"]) if proof else None
    kis_unfilled = (
        max(0, kis_order_qty - kis_filled_qty)
        if proof and evidence_complete and kis_order_qty is not None and kis_filled_qty is not None
        else None
    )
    kis_avg_price = float(proof["avgFilledPrice"]) if proof and kis_filled_qty else None
    kis_order_price = float(proof["orderPrice"]) if proof else None
    tracked_order_qty = int(live_order.quantity) if live_order is not None else None
    tracked_filled_qty = int(live_order.filled_quantity or 0) if live_order is not None else None
    submitted_order_price = float(live_order.price) if live_order is not None else None
    quantity_delta = (
        kis_filled_qty - paper_fill_qty
        if kis_filled_qty is not None and paper_fill_qty is not None else None
    )

    shadow_gap = _adverse_bps(intent.side.upper(), paper_fill_price, kis_avg_price)
    order_slippage = _adverse_bps(intent.side.upper(), kis_order_price, kis_avg_price)

    if paper_state != "paper_ready":
        overall = paper_state
    elif not signal_aligned:
        overall = "signal_mismatch"
    elif live_order is None:
        if live_ambiguous:
            overall = "kis_order_ambiguous"
        elif str(intent.status).lower() in ("submitted", "filled", "unknown", "pending"):
            overall = "kis_order_tracking_missing"
        else:
            overall = "kis_order_not_sent"
    elif live_state != "kis_fill_confirmed":
        overall = live_state
    elif paper_fill is None:
        overall = "paper_fill_pending"
    else:
        overall = "compared"

    try:
        execution_date = (
            datetime.strptime(proof["orderDate"], "%Y%m%d").date()
            if proof and proof.get("orderDate") else None
        )
    except (TypeError, ValueError):
        execution_date = None
    detail = {
        "paper_state": paper_state,
        "kis_state": live_state,
        "kis_query_error_type": proof_error,
        "kis_decision": {
            "strategy_id": kis_decision.get("strategy_id"),
            "version": kis_decision.get("version"),
            "bar_end_at": kis_decision.get("bar_end_at"),
            "action": kis_decision.get("action"),
            "input_hash": kis_decision.get("input_hash"),
            "source": kis_decision.get("source"),
        },
        "paper_decision": paper_decision,
        "paper_order": paper_order,
        "paper_fill": paper_fill,
        "paper_fill_date": paper_fill_date.isoformat() if paper_fill_date else None,
        "kis_execution_proof": ({
            "status": proof.get("status"),
            "order_price": proof.get("orderPrice"),
            "order_date": proof.get("orderDate"),
            "filled_quantity": proof.get("filledQuantity"),
            "avg_fill_price": proof.get("avgFilledPrice"),
            "remaining_quantity": proof.get("remainingQuantity"),
            "cancelled_quantity": proof.get("cancelledQuantity"),
            "quantity_evidence_complete": proof.get("quantityEvidenceComplete"),
        } if proof else None),
        "input_parity": "not_verified_different_sources",
        "quantity_comparison": "not_comparable_probe_order_cap",
        "quantity_delta_definition": "KIS 체결 수량 - 그림자 일지 가상 체결 수량",
        "slippage_definition": "양수는 해당 기준가격보다 불리한 체결",
    }

    version_id = journal_version.id if journal_version is not None else None
    version_no = journal_version.version_no if journal_version is not None else None
    values = {
        "intent_id": intent.intent_id,
        "user_id": intent.user_id,
        "account_ref": intent.account_ref,
        "journal_version_id": version_id,
        "journal_version_no": version_no,
        "decision_date": decision_date,
        "execution_date": execution_date,
        "symbol": intent.symbol,
        "side": intent.side.upper(),
        "status": overall,
        "client_order_id": client_id,
        "broker_order_no": live_order.order_no if live_order is not None else None,
        "tracked_order_status": live_order.status if live_order is not None else None,
        "tracked_order_quantity": tracked_order_qty,
        "tracked_filled_quantity": tracked_filled_qty,
        "submitted_order_price": submitted_order_price,
        "kis_order_status": proof.get("status") if proof else None,
        "kis_order_quantity": kis_order_qty,
        "kis_filled_quantity": kis_filled_qty,
        "kis_remaining_quantity": kis_remaining,
        "kis_cancelled_quantity": kis_cancelled,
        "kis_unfilled_quantity": kis_unfilled,
        "kis_order_price": kis_order_price,
        "kis_avg_fill_price": kis_avg_price,
        "quantity_evidence_complete": evidence_complete,
        "paper_decision_action": paper_decision.get("action") if paper_decision else None,
        "paper_order_quantity": paper_order_qty,
        "paper_fill_quantity": paper_fill_qty,
        "paper_fill_status": paper_fill_status,
        "paper_fill_date": paper_fill_date,
        "paper_fill_price": float(paper_fill_price) if paper_fill_price is not None else None,
        "signal_aligned": signal_aligned if paper_decision is not None else None,
        "quantity_delta": quantity_delta,
        "shadow_kis_adverse_bps": shadow_gap,
        "kis_order_adverse_bps": order_slippage,
        "detail": detail,
    }
    hash_source = json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                             default=str, allow_nan=False)
    values["snapshot_hash"] = hashlib.sha256(hash_source.encode("utf-8")).hexdigest()
    values["observed_at"] = now
    return values


async def run_daily(db, *, now: datetime | None = None, lookback_days: int = 30) -> dict:
    """최근 KIS 카드 시험 실행을 그림자 일지와 대조한다. 같은 결과는 중복 저장하지 않는다."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now에는 시간대가 필요합니다.")
    if type(lookback_days) is not int or not 1 <= lookback_days <= 180:
        raise ValueError("lookback_days는 1~180 사이 정수여야 합니다.")

    start = now - timedelta(days=lookback_days)
    intents = (await db.execute(select(OrderIntent).where(
        OrderIntent.book == KIS_BOOK,
        OrderIntent.strategy_id == KIS_STRATEGY_ID,
        OrderIntent.strategy_version == KIS_STRATEGY_VERSION,
        OrderIntent.source == KIS_SOURCE,
        OrderIntent.created_at >= start,
    ).order_by(OrderIntent.created_at))).scalars().all()

    report = {
        "checked_at": now.isoformat(),
        "lookback_days": lookback_days,
        "intents_found": len(intents),
        "inserted_snapshots": 0,
        "duplicate_snapshots": 0,
        "status_counts": {},
        "scope": "kis_trial_signal only; no order or cancel requests",
    }
    if not intents:
        return report

    version = (await db.execute(select(PaperJournalVersion).where(
        PaperJournalVersion.rule_id == JOURNAL_RULE_ID,
        PaperJournalVersion.version_no == JOURNAL_VERSION_NO,
    ))).scalar_one_or_none()

    journal_days = []
    if version is not None:
        journal_days = (await db.execute(select(PaperJournalDay).where(
            PaperJournalDay.version_id == version.id,
        ).order_by(PaperJournalDay.trade_date))).scalars().all()

    user_ids = {row.user_id for row in intents}
    broker_rows = (await db.execute(select(BrokerSettings).where(
        BrokerSettings.user_id.in_(user_ids)
    ))).scalars().all()
    brokers = {row.user_id: row for row in broker_rows}

    counts = Counter()
    for intent in intents:
        broker_row = brokers.get(intent.user_id)
        try:
            values = await _make_snapshot(db, intent, version, journal_days, broker_row, now)
        except Exception as exc:
            logger.exception("Paper↔KIS 대사 행 생성 실패 intent=%s", intent.intent_id[:12])
            counts["snapshot_error"] += 1
            continue

        status = values["status"]
        counts[status] += 1
        statement = pg_insert(PaperKisReconciliation).values(**values).on_conflict_do_nothing(
            index_elements=[PaperKisReconciliation.snapshot_hash]
        )
        result = await db.execute(statement)
        if result.rowcount:
            report["inserted_snapshots"] += 1
        else:
            report["duplicate_snapshots"] += 1

    await db.commit()
    report["status_counts"] = dict(counts)
    return report
