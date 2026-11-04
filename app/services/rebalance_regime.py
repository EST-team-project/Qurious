"""명시적으로 연결한 국면 배분만 갱신한다. 종목 선정·주문 승인 정책은 고정."""
from __future__ import annotations

import asyncio
from contextlib import closing
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import sqlite3
import uuid

from sqlalchemy import select

from app.models.rebalance import RebalanceRun, RebalanceTargetChange
from app.services import allocation_models as models, allocation_store, asset_allocation
from app.services import collector_db, etf_allocation


class PlanConflict(ValueError):
    pass


def target_weights(targets):
    return {t["symbol"]: Decimal(str(t["weight_pct"])) for t in targets}


def view(plan):
    config = getattr(plan, "regime_config", None) or {}
    return {"enabled": bool(config), "source_id": config.get("source_id"),
            "source_saved_at": config.get("source_saved_at"),
            "include_etfs": config.get("include_etfs", False),
            "initial_regime": config.get("initial_regime"),
            "state": getattr(plan, "regime_state", None) or {},
            "unapplied_assets": config.get("unapplied_assets", []),
            "policy": "confirmed_constituents_v1"}


def check_revision(plan, data):
    expected = data.get("expected_updated_at")
    requested = data.get("regime_auto") or {}
    required = bool(plan.regime_config or requested.get("enabled"))
    if expected is None:
        if required:
            raise PlanConflict("플랜을 새로 불러온 뒤 국면 자동 변경 설정을 저장하세요.")
        return
    current = plan.updated_at
    if current is None or expected.astimezone(timezone.utc) != current.astimezone(timezone.utc):
        raise PlanConflict("다른 화면이나 자동 점검에서 플랜을 변경했습니다. 새로 불러온 뒤 다시 편집하세요.")


def mapped_targets(config, allocations):
    """확인한 국내 종목 상대 비중과 ETF 매핑 유지. 미연결 자산군은 현금."""
    from app.services import rebalance as rb
    source = {"allocations": allocations, "optimization": {"weights": config["stock_weights"]},
              "stock_picks": config["stock_picks"]}
    targets = asset_allocation.rebalance_draft(source)["targets"]
    for item in config["etfs"]:
        targets.append({"symbol": item["symbol"], "name": item["name"],
                        "weight_pct": allocations[item["asset_class"]]})
    return rb.normalize_targets(targets)


async def configure(db, uid, plan, data):
    """호출자가 플랜 잠금과 수정 버전을 검사한 뒤 호출. 저장만으로 실행하지 않는다."""
    from app.services import rebalance as rb
    request = data.get("regime_auto")
    old = plan.regime_config or {}
    if request is not None and not request["enabled"]:
        plan.regime_config, plan.regime_state = {}, {}
        return
    if request and request.get("allocation_id"):
        saved = await allocation_store.load_result(db, uid)
        if saved is None or saved["id"] != str(request["allocation_id"]):
            raise PlanConflict("가져온 배분이 최신 저장본과 다릅니다. 배분을 다시 가져오세요.")
        source = saved["result"]
        model = source.get("asset_model") or {}
        if source.get("allocation_model") != "regime" or model.get("model") != "regime":
            raise ValueError("시장 국면별 배분으로 계산한 저장본을 먼저 가져오세요.")
        if not model.get("regime", {}).get("key") or not model.get("reference_allocations"):
            raise ValueError("저장된 국면 배분의 기준 정보가 없습니다. 다시 계산하세요.")
        include_etfs = request.get("include_etfs", False)
        draft = (await asyncio.to_thread(etf_allocation.preview, source) if include_etfs
                 else asset_allocation.rebalance_draft(source))
        expected = rb.normalize_targets(draft["targets"])
        if target_weights(expected) != target_weights(plan.targets):
            raise PlanConflict("가져온 배분의 목표를 수정했습니다. 자동 변경을 끄거나 배분을 다시 가져오세요.")
        config = {
            "version": 1, "policy_id": str(uuid.uuid4()), "source_id": saved["id"],
            "source_saved_at": saved["saved_at"], "include_etfs": include_etfs,
            "baseline": model["reference_allocations"],
            "stock_weights": source["optimization"]["weights"],
            "stock_picks": [{"code": p["code"], "name": p["name"]} for p in source["stock_picks"]],
            "etfs": [{"asset_class": p["asset_class"], "symbol": p["symbol"], "name": p["name"]}
                     for p in draft.get("selected_etfs", [])],
            "unapplied_assets": list(draft["unapplied_allocations"]),
            "initial_regime": model["regime"]["key"],
        }
        if target_weights(mapped_targets(config, source["allocations"])) != target_weights(plan.targets):
            raise ValueError("확인한 자산군과 종목 비중이 일치하지 않습니다.")
        plan.regime_config = deepcopy(config)
        plan.regime_state = {"status": "enabled", "regime": model["regime"]["key"],
                             "data_as_of": model["as_of"], "targets": deepcopy(plan.targets),
                             "message": "다음 일별 점검부터 국면 변화를 확인합니다."}
    elif (request and request["enabled"]) or old:
        if not old:
            raise ValueError("시장 국면별 배분을 가져온 뒤 자동 변경을 켜세요.")
        state = plan.regime_state or {}
        if target_weights(plan.targets) != target_weights(state.get("targets", [])):
            raise PlanConflict("목표 종목·비중을 직접 수정하려면 국면 자동 변경을 끄세요.")


def calculate(config, as_of):
    """네 대용 ETF를 한 SQLite 읽기 트랜잭션에서 읽는다. 외부 대체값은 쓰지 않는다."""
    path = collector_db.db_path()
    if path is None:
        raise ValueError("국면 판단용 수집 DB를 확인할 수 없습니다.")
    since = (as_of - timedelta(days=3 * 366)).strftime("%Y%m%d")
    inputs = []
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
        conn.execute("BEGIN")
        for asset, proxy in models.ASSET_PROXIES.items():
            rows = conn.execute(
                "SELECT bas_dt,clpr FROM etf_daily WHERE srtn_cd=? AND bas_dt>=? AND bas_dt<=? ORDER BY bas_dt",
                (proxy["symbol"].split(".")[0], since, as_of.strftime("%Y%m%d"))).fetchall()
            if not rows or rows[-1][0] != as_of.strftime("%Y%m%d"):
                raise ValueError(f"{asset}: 전 거래일 ETF 종가가 없어 국면 변경을 기다립니다.")
            inputs.append({"symbol": asset, "candles": [
                {"time": int(datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()),
                 "close": close} for day, close in rows]})
    result = models.calculate_allocation("regime", inputs, config["baseline"], as_of=as_of.isoformat())
    if result["as_of"] != as_of.isoformat():
        raise ValueError("국면 판단 기준일이 전 거래일과 다릅니다.")
    return result


async def update_for_day(db, uid, plan, readiness):
    from app.services import rebalance as rb
    config = plan.regime_config or {}
    if not config:
        return {"status": "disabled"}
    state = plan.regime_state or {}
    day = date.fromisoformat(readiness["data_as_of"])
    if state.get("data_as_of") and day.isoformat() <= state["data_as_of"]:
        return {"status": "already_checked", "regime": state.get("regime")}

    def wait(message):
        plan.regime_state = {**state, "status": "waiting", "message": message,
                             "checked_at": rb.datetime.now(rb.KST).isoformat()}
        return {"status": "waiting", "message": message}

    if target_weights(plan.targets) != target_weights(state.get("targets", [])):
        return wait("목표가 수동 변경되어 국면 자동 변경을 보류합니다. 배분을 다시 연결하세요.")
    if await rb.settlement.pending(db, uid):
        return wait("기존 예약 처리 후 국면 변경을 확인합니다.")
    completed = await db.scalar(select(RebalanceRun.id).where(
        RebalanceRun.plan_id == plan.id, RebalanceRun.decision_date == rb.datetime.now(rb.KST).date(),
        RebalanceRun.trigger != "MANUAL", RebalanceRun.status.in_(("executed", "partial", "failed"))))
    if completed:
        return {"status": "deferred", "message": "오늘 처리한 리밸런싱이 있어 다음 거래일에 국면을 확인합니다."}
    try:
        result = await asyncio.to_thread(calculate, config, day)
        current = await asyncio.to_thread(rb.daily.readiness)
        proof_keys = ("ready", "decision_date", "data_as_of", "source_commit", "data_ready_at", "update_finished_at")
        if any(current.get(k) != readiness.get(k) for k in proof_keys):
            return wait("계산 중 수집 자료의 준비 상태가 바뀌어 다음 점검을 기다립니다.")
        targets = mapped_targets(config, result["allocations"])
    except (ValueError, KeyError, TypeError, sqlite3.Error, OSError) as exc:
        return wait(f"국면 자료 확인 대기: {exc}")
    regime = result["regime"]["key"]
    changed = regime != state.get("regime")
    change_id = None
    if changed:
        change = RebalanceTargetChange(
            user_id=uid, plan_id=plan.id, policy_id=uuid.UUID(config["policy_id"]), data_as_of=day,
            before_targets=deepcopy(plan.targets), after_targets=deepcopy(targets),
            evidence={"from_regime": state.get("regime"), "to_regime": regime,
                      "regime": result["regime"], "allocations": result["allocations"],
                      "baseline": config["baseline"], "input_sha256": result["input_sha256"],
                      "observations": result["observations"], "source_id": config["source_id"],
                      "source_commit": readiness.get("source_commit"),
                      "data_ready_at": readiness.get("data_ready_at"),
                      "decision_date": readiness["decision_date"],
                      "auto_execute": plan.auto_execute, "unapplied_assets": config["unapplied_assets"]})
        db.add(change)
        plan.targets = targets
        await db.flush()
        change_id = str(change.id)
    plan.regime_state = {
        "status": "changed" if changed else "unchanged", "regime": regime,
        "data_as_of": day.isoformat(), "targets": deepcopy(plan.targets),
        "checked_at": rb.datetime.now(rb.KST).isoformat(), "input_sha256": result["input_sha256"],
        "change_id": change_id,
        "message": "국면 변화로 목표 비중을 갱신했습니다." if changed else "같은 국면이므로 목표 비중을 유지합니다."}
    return {k: v for k, v in plan.regime_state.items() if k != "targets"}


async def history(db, uid, limit=20):
    rows = (await db.execute(select(RebalanceTargetChange).where(RebalanceTargetChange.user_id == uid)
                            .order_by(RebalanceTargetChange.created_at.desc(), RebalanceTargetChange.id)
                            .limit(limit))).scalars().all()
    return [{"id": str(r.id), "data_as_of": r.data_as_of.isoformat(),
             "created_at": r.created_at.isoformat(), "before_targets": r.before_targets,
             "after_targets": r.after_targets, "evidence": r.evidence} for r in rows]
