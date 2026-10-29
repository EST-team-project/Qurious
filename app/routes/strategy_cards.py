"""전략 카드 → Pine v6 `strategy()` 내려받기 — 카드 목록과 코드 생성 (2026-10-29 · 화면 벤치마킹 S3 · 이동원 직접).

- GET /api/strategy-cards                  카드 파일 목록 + 각 카드를 Pine 으로 만들 수 있는지(까닭)
- GET /api/strategy-cards/{id}/pine        카드 한 장 → Pine v6 코드 + TradingView Properties 에 맞출 실행 설정

이 파일은 **새 길만 연다.** 생성기 `app/services/pine_strategy.py`(신장환 님 코드)는 부르기만 하고 고치지 않는다 — 코드도 카드도 새로 짓지 않고
생성기가 준 값(`PineResult` · `read_back`)을 그대로 돌려준다. 카드 파일은 일지(`paper_journal.CARD_PATH`)와 같은 폴더의
`strategy-card-*.json` 이다(파일 이름의 stem 이 id). 사용자가 낸 id 는 목록에 있는 이름과 같을 때만 쓴다(경로를 만들지 않는다).
로그인한 사람만. 생성한 코드는 저장하지 않는다(파일 · 기록 없음).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from app.lib.session import get_current_user
from app.services import pine_strategy, strategy_card_store

router = APIRouter(prefix="/api/strategy-cards", tags=["strategy-cards"])

ROOT = Path(__file__).resolve().parents[2]
CARD_DIR = ROOT / "docs" / "phase-3" / "02-design" / "system" / "예시"
CARD_GLOB = "strategy-card-*.json"
_ID = re.compile(r"^strategy-card-[A-Za-z0-9._-]+$")


def _files(user_id: str | None = None) -> dict[str, Path]:
    """id(파일 이름의 stem) → 경로. 폴더가 없으면 빈 목록. `user_id` 를 주면 그 사용자가 기본 인디케이터 전략 화면(U6)에서
    저장한 카드도 붙인다(#392 · `strategy_card_store` — 사용자마다 따로 · 예시 id 가 먼저)."""
    out = {p.stem: p for p in sorted(CARD_DIR.glob(CARD_GLOB)) if _ID.match(p.stem)} if CARD_DIR.is_dir() else {}
    if user_id:
        try:
            for card_id, path in strategy_card_store.files(user_id).items():
                out.setdefault(card_id, path)
        except strategy_card_store.CardError:
            pass
    return out


def _uid(user) -> str | None:
    return str(user.get("id")) if isinstance(user, dict) and user.get("id") else None


def _load(card_id: str, user_id: str | None = None) -> tuple[dict, Path]:
    path = _files(user_id).get(card_id)
    if path is None:                                     # 목록에 없는 id 는 경로로 쓰지 않는다
        raise HTTPException(404, f"전략 카드 「{card_id}」 를 찾을 수 없습니다.")
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(422, f"전략 카드 「{card_id}」 파일을 읽을 수 없습니다: {exc}") from None
    if not isinstance(spec, dict):
        raise HTTPException(422, f"전략 카드 「{card_id}」 의 모양이 올바르지 않습니다(객체가 아님).")
    return spec, path


def _summary(card_id: str, spec: dict) -> dict:
    universe = [str(u) for u in (spec.get("universe") or [])]
    out = {"id": card_id, "card_id": spec.get("strategy_id") or spec.get("card_id") or card_id, "version": spec.get("version"),
           "timeframe": spec.get("timeframe") or "1d", "universe": universe, "generatable": False, "reason": ""}
    try:
        pine_strategy.generate(spec, symbol=universe[0] if len(universe) > 1 else None)
        out["generatable"] = True
    except pine_strategy.GenerationError as exc:
        out["reason"] = str(exc)
    return out


@router.get("", summary="전략 카드 목록 — 각 카드를 Pine 으로 만들 수 있는지와 까닭")
async def list_cards(_user=Depends(get_current_user)):
    cards = []
    for card_id in _files(_uid(_user)):
        try:
            spec, _ = _load(card_id, _uid(_user))
        except HTTPException as exc:
            cards.append({"id": card_id, "generatable": False, "reason": str(exc.detail), "universe": []})
            continue
        cards.append(_summary(card_id, spec))
    return {"cards": cards, "source": "docs/phase-3/02-design/system/예시/strategy-card-*.json",
            "note": "카드는 파일이다. 여기서 고르는 것은 읽기뿐이며 카드를 바꾸지 않는다."}


@router.get("/{card_id}/pine", summary="카드 한 장 → Pine v6 strategy() 코드 + TradingView Properties 에 맞출 설정")
async def card_pine(
    card_id: str,
    symbol: str | None = Query(None, max_length=20, description="카드 유니버스가 둘 이상일 때 만들 한 종목"),
    ref_price: float | None = Query(None, gt=0, le=100_000_000, description="슬리피지를 틱으로 바꿀 기준가(원)"),
    mintick: float | None = Query(None, gt=0, le=1_000_000, description="그 가격대의 호가 단위(원) — TradingView 심볼의 mintick"),
    fee_pct: float = Query(0.015, ge=0, le=5, description="수수료(%)"),
    sell_tax_pct: float = Query(0.18, ge=0, le=5, description="매도세(%)"),
    slippage_bp: float = Query(10, ge=0, le=1000, description="슬리피지(bp)"),
    capital: int = Query(10_000_000, ge=100_000, le=10_000_000_000, description="초기 자본(원)"),
    _user=Depends(get_current_user),
):
    spec, path = _load(card_id, _uid(_user))
    try:
        res = pine_strategy.generate(spec, symbol=symbol, ref_price=ref_price, mintick=mintick, fee_pct=str(fee_pct),
                                     sell_tax_pct=str(sell_tax_pct), slippage_bp=slippage_bp, initial_capital=capital)
    except pine_strategy.GenerationError as exc:
        raise HTTPException(422, str(exc)) from None
    ext = res.extracted
    return {
        "id": card_id, "file": path.name, "card_id": res.card_id, "version": res.version, "fingerprint": res.sha12,
        "symbol": res.symbol, "pine_version": ext.get("version"), "declaration": ext.get("declaration"),
        "code": res.code, "warnings": res.warnings, "skipped_v2": res.skipped_v2,
        # TradingView Properties 탭에 그대로 맞출 값 — 생성기가 코드에서 다시 읽은 값(read_back) + 비용 환산. 화면은 짓지 않고 보이기만 한다.
        "properties": {
            "initial_capital": ext.get("initial_capital"), "commission_type": ext.get("commission_type"),
            "commission_value": ext.get("commission_value"), "commission_one_way_pct": res.commission_one_way_pct,
            "commission_round_trip_pct": res.commission_round_trip_pct, "slippage_ticks": res.slippage_ticks,
            "slippage_effective_bp": res.slippage_effective_bp, "pyramiding": ext.get("pyramiding"),
            "process_orders_on_close": ext.get("process_orders_on_close"), "timeframe": "1d",
        },
        "extracted": ext,
        "note": "코드는 저장하지 않습니다. TradingView 에 붙인 뒤 Properties 의 값이 위 설정과 같은지 확인하세요 — 다르면 LEAN 과의 비교가 어긋날 수 있습니다.",
    }
