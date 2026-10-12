"""설명 API — /api/explain (목표 기능 ② 설계서 7절 <표 13> · `P01-①-5`)

- GET /api/explain?kind=signal&symbol=&date= : T2 `signal_snapshots` 의 그날(없으면 그 앞 가장 가까운 거래일) 한 줄을
  쉬운 말 한두 문장 · 근거 표 · 신뢰도 풀이로 (`app/services/signal_explain.py` · 설명 층 1 · 규칙)

`kind` 는 다른 설명 대상(배분 · 종목 선정)을 위해 비워 둔 자리다 — 지금은 `signal` 하나.
로그인한 사람만(`API-STK-35` 다중 주기 신호와 같다).
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database.postgres import get_pg_session
from app.lib.session import get_current_user
from app.services import signal_explain

router = APIRouter(prefix="/api", tags=["explain"])


@router.get("/explain", summary="신호 설명(규칙)")
async def explain(
    kind: Literal["signal"] = Query("signal", description="설명 대상 — 지금은 signal(다중 주기 신호 T2) 하나"),
    symbol: str = Query(..., min_length=1, max_length=16, description="종목 코드 — 005930 · 005930.KS 모두 받음"),
    on: date | None = Query(None, alias="date", description="기준일 YYYY-MM-DD — 비우면 가장 최근 기록"),
    db=Depends(get_pg_session),
    _user=Depends(get_current_user),
):
    snapshot = await signal_explain.load_snapshot(db, symbol, on)
    if snapshot is None:
        when = f"{on.isoformat()} 이전" if on else "지금까지"
        raise HTTPException(404, f"신호 기록 없음: {signal_explain.normalize_symbol(symbol)} · {when}")
    return signal_explain.explain(snapshot)
