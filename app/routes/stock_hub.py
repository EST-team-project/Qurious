"""종목 허브 API — /api/stock-hub (2026-10-17 · 결정 D95 「서버 둘 + Figma 세 안 · 화면은 3차」 의 허브 자료 묶음)

- GET /api/stock-hub?symbol=&sections= : 종목 하나의 근거 칸 묶음 — 종목 · 마지막 종가 · 다중 주기 신호 · 재무 건전성 ·
  최근 공시 · 최근 기사 · 앞으로의 일정 · 섹터(준비 중). 칸마다 상태 · 기준일 · 출처 · 그 화면(`app/services/stock_hub.py`)
- GET /api/stock-hub/mentions?q=      : 질문에 이름이 그대로 든 종목(최대 둘) — AI 투자 상담이 앱 판단 카드를 붙일 때 쓴다
- GET /api/stock-hub/signal-rank      : 신호 기록 순위 — 종목마다 그날(또는 그날 이전 가장 가까운) 기록 한 줄을 종합 점수 순으로 ·
  줄마다 기준일 · 근거 개수(매수 쪽 · 중립 · 매도 쪽). 새 계산 없음(할 일 ②-19 · #197)

새로 계산하지 않는다 — 다른 화면이 쓰는 함수를 그대로 부르고, 칸을 합친 한 줄 결론을 만들지 않는다.
로그인한 사람만. 칸이 실패했을 때의 할 일(hint)은 관리자 답에만 싣는다.
"""
from __future__ import annotations

import asyncio
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database.postgres import get_pg_session
from app.lib.session import get_current_user
from app.services import stock_hub

router = APIRouter(prefix="/api/stock-hub", tags=["stock-hub"])


@router.get("", summary="종목 허브 — 한 종목의 근거 칸 묶음(새 계산 없음 · 칸마다 기준일 · 출처)")
async def hub(
    symbol: str = Query(..., min_length=1, max_length=16, description="종목 코드 6자리 — 005930 · 005930.KS · ETF 0000D0 모두 받음"),
    sections: str | None = Query(None, max_length=120,
                                 description="쉼표로 고른 칸만(종목 칸은 늘 넣음) — identity · price · signal · financials · "
                                             "disclosures · news · schedule · sector · 비우면 전부"),
    db=Depends(get_pg_session),
    user=Depends(get_current_user),
):
    try:
        return await stock_hub.bundle(db, symbol, sections=sections, admin="admin" in user.get("roles", []))
    except stock_hub.HubError as e:
        raise HTTPException(status_code=e.status, detail=e.detail()) from None


@router.get("/signal-rank", summary="신호 기록 순위 — 종목마다 그날(또는 그날 이전 가장 가까운) 기록을 종합 점수 순으로(새 계산 없음 · 줄마다 기준일)")
async def signal_rank(
    on: date | None = Query(None, description="기준일 — 종목마다 이 날 이전(포함) 가장 최근 기록 · 비우면 가장 최근"),
    symbols: str | None = Query(None, max_length=1200,
                                description="쉼표로 고른 종목 코드(최대 100) — 비우면 기록이 있는 모든 종목 · 기록이 없는 종목은 missing 에 까닭과 함께"),
    limit: int = Query(stock_hub.SIGNAL_RANK_DEFAULT, ge=1, le=stock_hub.SIGNAL_RANK_MAX, description="돌려줄 줄 수(순위 위에서부터)"),
    components: bool = Query(False, description="참이면 줄마다 근거별 점수(components)도 싣는다"),
    db=Depends(get_pg_session),
    _user=Depends(get_current_user),
):
    codes = None
    if symbols is not None:
        try:
            codes = [stock_hub.normalize(s) for s in symbols.split(",") if s.strip()]
        except stock_hub.HubError as e:
            raise HTTPException(status_code=e.status, detail=e.detail()) from None
        if not codes or len(codes) > stock_hub.SIGNAL_RANK_SYMBOLS_MAX:
            raise HTTPException(status_code=422, detail={"code": "bad_symbols",
                                                         "message": f"종목 코드는 1 ~ {stock_hub.SIGNAL_RANK_SYMBOLS_MAX}개를 쉼표로 적어 주세요."})
    return await stock_hub.signal_rank(db, on, codes, limit, components)


@router.get("/mentions", summary="질문 속 종목 — 이름이 그대로 든 종목(최대 둘)")
async def mentions(
    q: str = Query(..., min_length=1, max_length=stock_hub.MAX_TEXT, description="질문 글(AI 투자 상담 입력과 같은 300자 상한)"),
    _user=Depends(get_current_user),
):
    items = await asyncio.to_thread(stock_hub.mentions, q)
    return {
        "items": items,
        "rule": ("회사 이름이 질문에 그대로 있을 때만 그 종목으로 읽습니다 — 비슷한 이름은 고르지 않습니다. 두 글자 이하 이름은 "
                 "앞뒤가 낱말 경계일 때만 · 흔한 낱말과 같은 이름은 빼고, 겹치면 긴 이름이 이깁니다."),
        "note": "무엇을 종목으로 읽었는지(matched)를 화면에 밝혀 잘못 읽었을 때 사용자가 알 수 있게 합니다.",
    }
