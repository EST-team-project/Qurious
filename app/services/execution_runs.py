"""정기/즉시 실행의 같은 시간 칸을 한 번 선점한다. 중단된 회차는 자동 재실행하지 않는다."""
import asyncio
from contextvars import ContextVar
from datetime import datetime, timezone

from sqlalchemy import select
from app.database.postgres import get_session_factory
from app.models import BrokerSettings, ExecutionRun
from app.services import execution_control as control, notification

cycle_result = ContextVar("quant_cycle_result", default=None)


async def run(uid, interval, operation, *, source="scheduled", now=None):
    now = now or datetime.now(timezone.utc)
    slot = int(now.timestamp()) // max(1, interval) * max(1, interval)
    run_id = control.digest([str(uid), "quant", slot])
    async with get_session_factory()() as db:
        async with control.account_lock(db, "quant-run:" + str(uid)) as acquired:
            if not acquired:
                return {"status": "busy", "run_id": run_id}
            # 사용자 실행 잠금을 얻었으므로 이전 RUNNING 회차의 실행자는 더 이상 없다.
            orphans = (await db.scalars(select(ExecutionRun).where(
                ExecutionRun.user_id == uid, ExecutionRun.status == "RUNNING"))).all()
            for orphan in orphans:
                orphan.status, orphan.detail = "INTERRUPTED", {"code": "PROCESS_INTERRUPTED"}
                orphan.finished_at = datetime.now(timezone.utc)
            if orphans:
                await db.commit()
                for orphan in orphans:
                    try:
                        await notification.dispatch("자동매매 실행이 중단됐습니다. 주문 접수 여부를 확인해 주세요.",
                            user_id=str(uid), kind="quant_run_failed", ref=orphan.run_id)
                    except Exception:
                        orphan.detail = {**orphan.detail, "notification": "unconfirmed"}
                await db.commit()
            previous = await db.get(ExecutionRun, run_id)
            if previous:
                return {"status": previous.status, "duplicate": True, "run_id": run_id}
            broker = (await db.execute(select(BrokerSettings).where(BrokerSettings.user_id == uid))).scalar_one_or_none()
            if broker is None or not broker.quant_auto_enabled or broker.risk_kill_switch:
                return {"status": "disabled", "run_id": run_id}
            row = ExecutionRun(run_id=run_id, user_id=uid, source=source, status="RUNNING",
                               scheduled_for=datetime.fromtimestamp(slot, timezone.utc), detail={})
            db.add(row)
            await db.commit()
            summary = {}
            token = cycle_result.set(summary)
            try:
                await control.coordination_ready()
                outcome = await operation()
                row.status = summary.get("status", "COMPLETED")
                row.detail = summary or ({"outcome": outcome} if isinstance(outcome, str) else {})
            except asyncio.CancelledError:
                row.status, row.detail = "INTERRUPTED", {"code": "EXECUTION_INTERRUPTED"}
                row.finished_at = datetime.now(timezone.utc)
                await db.commit()
                raise
            except Exception as exc:
                row.status = "FAILED"
                row.detail = {"code": getattr(exc, "code", "EXECUTION_FAILED")}
            finally:
                cycle_result.reset(token)
            row.finished_at = datetime.now(timezone.utc)
            await db.commit()
            if row.status == "FAILED":
                try:
                    await notification.dispatch("자동매매 실행이 실패했습니다. 실행 기록을 확인해 주세요.",
                        subject="[자동매매] 실행 실패", user_id=str(uid), kind="quant_run_failed", ref=run_id)
                except Exception:
                    # 주문/회차 결과를 알림 장애 때문에 다시 실행하지 않는다.
                    row.detail = {**row.detail, "notification": "unconfirmed"}
                    await db.commit()
            return {"status": row.status, "run_id": run_id}
