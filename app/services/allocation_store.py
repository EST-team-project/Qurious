"""서버에서 계산한 결과만 저장한다. 사용자별 한 건, 완료 시 최신 결과로 교체."""
import json
import uuid
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from app.models.allocation import AllocationResult


async def save_result(db, user_id, result):
    # JSON에 NaN/Infinity가 섞인 계산 결과를 저장하지 않는다.
    clean = json.loads(json.dumps(result, allow_nan=False))
    rid = uuid.uuid4()
    stmt = insert(AllocationResult).values(user_id=uuid.UUID(str(user_id)), result_id=rid, result=clean)
    stmt = stmt.on_conflict_do_update(index_elements=[AllocationResult.user_id],
                                     set_={"result_id": rid, "result": clean, "updated_at": func.now()})
    stamp = (await db.execute(stmt.returning(AllocationResult.updated_at))).scalar_one()
    return {"id": str(rid), "saved_at": stamp.isoformat()}


async def load_result(db, user_id):
    row = await db.get(AllocationResult, uuid.UUID(str(user_id)), populate_existing=True)
    if row is None:
        return None
    return {"id": str(row.result_id), "saved_at": row.updated_at.isoformat(), "result": row.result}
