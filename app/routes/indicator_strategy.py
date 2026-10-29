"""기본 인디케이터 전략 화면(W7 `indicator-strategy`)의 `U6` 전략 설정 · `U7` 지표 차트(#392 · 설계서 4.6)

- GET    /api/indicator-strategy/chart?symbol=&period=&short=&long= : 가격 차트에 그릴 봉 · 지표 · 카드 조건 표식(`indicator_chart`)
- GET    /api/indicator-strategy/cards : 내가 저장한 카드 + 화면이 처음 채울 판 2 예시 값
- POST   /api/indicator-strategy/cards : 카드 저장(사용자마다 따로 · `strategy_card_store`) — 카드 → Pine 내려받기 목록에 같이 나온다
- DELETE /api/indicator-strategy/cards/{card_id}

로그인한 사람만. 지표 값은 정의 한 벌(`ta_utils`)이고 화면은 짓지 않고 그리기만 한다.
"""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.lib.session import get_current_user
from app.routes import strategy_cards
from app.services import data_provenance, indicator_chart, strategy_card_store
from app.services.stock import get_candles

router = APIRouter(prefix="/api/indicator-strategy", tags=["indicator-strategy"])


@router.get("/chart", summary="U7 지표 차트 — 봉 · 지표 · 카드 조건(이동평균 교차) 표식")
async def chart(
    symbol: str = Query(..., min_length=1, max_length=20),
    period: Literal["3mo", "6mo", "1y", "2y"] = Query("1y"),
    short: int = Query(5, ge=2, le=250, description="카드 조건의 단기 이동평균"),
    long: int = Query(20, ge=3, le=250, description="카드 조건의 장기 이동평균"),
    _user=Depends(get_current_user),
):
    if short >= long:
        raise HTTPException(422, "단기 이동평균은 장기보다 짧아야 합니다.")
    data = await get_candles(symbol, period=indicator_chart.FETCH_PERIOD[period])
    bench = indicator_chart.benchmark_for(symbol)
    bench_candles = None
    if bench:
        try:
            bench_candles = (await get_candles(bench[0], period=indicator_chart.FETCH_PERIOD[period])).get("candles")
        except Exception:                                   # 기준선을 못 받아도 차트는 그린다(상대 강도만 비움 · rs_note)
            bench_candles = None
    out = indicator_chart.build(data.get("candles") or [], period, short, long, bench_candles, bench)
    if out.get("error"):
        raise HTTPException(422, f"{symbol}: {out['error']}")
    return {"symbol": symbol, "period": period, "as_of": data.get("as_of"), "source": data.get("source"),
            "data_note": data_provenance.candle_provenance(data)["data_note"], "definition": indicator_chart.ta_utils.DEFINITION,
            **out}


@router.get("/cards", summary="U6 — 내가 저장한 전략 카드 · 처음 채울 판 2 예시 값")
async def my_cards(user=Depends(get_current_user)):
    try:
        found = strategy_card_store.files(user.get("id"))
    except strategy_card_store.CardError as exc:
        raise HTTPException(401, str(exc)) from None
    cards = []
    for card_id, path in found.items():
        try:
            cards.append({"id": card_id, "card": json.loads(path.read_text(encoding="utf-8"))})
        except (OSError, ValueError) as exc:
            cards.append({"id": card_id, "card": None, "reason": f"카드 파일을 읽을 수 없습니다: {exc}"})
    return {"cards": cards, "template": strategy_card_store.template()}


@router.post("/cards", summary="U6 — 전략 카드 저장(판 2 꼴 · 카드 → Pine 내려받기 목록에 같이 나온다)")
async def save_card(form: dict = Body(...), user=Depends(get_current_user)):
    try:
        card_id, card = strategy_card_store.save(user.get("id"), form, set(strategy_cards._files()))
    except strategy_card_store.CardError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"id": card_id, "card": card}


@router.delete("/cards/{card_id}", summary="U6 — 내가 저장한 카드 지우기(예시 카드는 못 지운다)")
async def delete_card(card_id: str, user=Depends(get_current_user)):
    try:
        gone = strategy_card_store.delete(user.get("id"), card_id)
    except strategy_card_store.CardError as exc:
        raise HTTPException(401, str(exc)) from None
    if not gone:
        raise HTTPException(404, f"내 카드 「{card_id}」 를 찾을 수 없습니다.")
    return {"id": card_id, "deleted": True}
