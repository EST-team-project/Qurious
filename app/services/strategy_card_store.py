"""U6 전략 설정 — 기본 인디케이터 전략 화면(W7 `indicator-strategy`)에서 사용자가 저장한 전략 카드(#392 · 설계서 4.6).

예시 카드(`docs/…/예시` · 판 1 은 그림자 일지가 지문을 잰다)는 읽기만 하고, 화면에서 저장한 카드는 **사용자마다** 앱 데이터
폴더(`settings.DATA_DIR`/strategy-cards/<사용자 id>/ · 도커는 /app/data = app_data 볼륨)에 둔다. 카드 → Pine 내려받기
(`app/routes/strategy_cards.py`)가 예시 카드와 그 사용자의 카드를 함께 읽는다. #392 이동원 님 조건 셋:
1. 사용자마다 따로 저장 · 읽기 — 다른 사람 카드는 목록에 안 나온다.
2. 카드 id 는 `strategy_cards._ID` 규칙 · 이름 칸은 영문 소문자 · 숫자 · `-` 만(경로 문자 거부) · 예시 카드 id 로 덮어쓰지 않는다.
3. 시험 — 저장 → 목록 → Pine 내려받기 · 사용자 둘이 서로 못 본다(TC-SCU).

카드 꼴은 판 2 예시(`strategy-card-ma-cross-v2.json`)를 바탕으로 화면이 고치는 칸만 바꾼다 — 칸 이름 · 자리는 그대로라 Pine 생성기 ·
백테스트가 같은 카드를 읽는다(설계서 4.3). 값 범위는 4.3 에서 합의한 값과 입력 상한이고, 마지막으로 Pine 생성기가 만들 수 있는지 본다.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from app.config import settings
from app.services import pine_strategy

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "docs" / "phase-3" / "02-design" / "system" / "예시" / "strategy-card-ma-cross-v2.json"
ID_PREFIX = "strategy-card-"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_USER = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_SYMBOL = re.compile(r"^[0-9A-Z]{1,12}$")

#: 화면이 고치는 칸 → (허용 값 또는 (최소, 최대)) — 4.3 표의 합의 값 · 입력 상한
CHOICES = {"entry_mode": ("open", "close"), "exit_mode": ("open", "close"), "judge": ("close", "next_open", "intrabar")}
RANGES = {"short_window": (2, 250), "long_window": (3, 250), "atr_period": (2, 100), "atr_mult": (0.5, 10.0),
          "take_rr": (1.5, 3.0), "risk_pct": (0.1, 5.0), "max_position_pct": (1.0, 100.0), "max_symbols": (1, 20)}


class CardError(ValueError):
    """화면에 그대로 보일 까닭(한국어)."""


def base_dir() -> Path:
    return Path(os.getenv("STRATEGY_CARD_DIR") or Path(settings.DATA_DIR) / "strategy-cards")


def user_dir(user_id: str) -> Path:
    if not _USER.match(str(user_id or "")):
        raise CardError("사용자를 알 수 없습니다.")
    return base_dir() / str(user_id)


#: 판 2 예시 파일과 같은 값 — 앱 이미지에 `docs/` 가 없을 때(#392) 쓴다. TC-SCU 가 파일과 맞대어 갈리지 않게 한다.
TEMPLATE_V2 = {
    "strategy_id": "ma_cross_20_60", "version": 2, "name": "이동평균 교차 20 · 60 — 판 2(손절 · 익절 · 수량 · 체결 시점)",
    "universe": ["005930"], "timeframe": "1d",
    "entry": {"indicator": "ma_cross", "params": {"short_window": 20, "long_window": 60}, "condition": "short_above_long"},
    "exit": {"indicator": "ma_cross", "params": {"short_window": 20, "long_window": 60}, "condition": "short_below_long"},
    "signal_weights": {"technical": 1.0, "lightgbm": 0.0, "buy_threshold": 0.6, "sell_threshold": -0.6},
    "position_sizing": {"max_position_pct": 30.0, "max_symbols": 5, "size_kind": "risk_pct", "risk_pct": 1.0},
    "entry_mode": "open", "exit_mode": "open",
    "stops": {"stop_kind": "atr", "atr_period": 14, "atr_mult": 2.0, "take_kind": "rr", "take_rr": 2.0, "judge": "close", "lock": "entry"},
    "reentry": "new_signal", "warmup_bars": 60, "price_basis": "adj_base",
}


def template() -> dict:
    if TEMPLATE.is_file():
        return json.loads(TEMPLATE.read_text(encoding="utf-8"))
    return json.loads(json.dumps(TEMPLATE_V2))


def files(user_id: str) -> dict[str, Path]:
    """그 사용자의 카드 id → 경로. 폴더가 없으면 빈 목록."""
    d = user_dir(user_id)
    if not d.is_dir():
        return {}
    return {p.stem: p for p in sorted(d.glob(f"{ID_PREFIX}*.json")) if _SLUG.match(p.stem[len(ID_PREFIX):])}


def _num(form: dict, key: str, kind=float):
    lo, hi = RANGES[key]
    try:
        v = kind(form[key])
    except (KeyError, TypeError, ValueError):
        raise CardError(f"「{key}」 값이 없거나 숫자가 아닙니다.") from None
    if not (lo <= v <= hi) or (kind is float and v != v):
        raise CardError(f"「{key}」 는 {lo} ~ {hi} 사이여야 합니다(받은 값 {v}).")
    return v


def build_card(form: dict) -> dict:
    """화면 입력 → 판 2 꼴 카드. 고치지 않는 칸(손절 방식 ATR · 익절 손익비 · ATR 고정 · 다시 진입 · 가격 기준 · 수량 방식)은 예시 그대로."""
    slug = str(form.get("slug") or "")
    if not _SLUG.match(slug):
        raise CardError("카드 이름은 영문 소문자 · 숫자 · - 로 1 ~ 40자여야 합니다(예: ma-cross-10-60).")
    symbol = str(form.get("symbol") or "").upper().split(".")[0]
    if not _SYMBOL.match(symbol):
        raise CardError("종목 코드를 알 수 없습니다(예: 005930).")
    short, long = _num(form, "short_window", int), _num(form, "long_window", int)
    if short >= long:
        raise CardError("단기 이동평균은 장기보다 짧아야 합니다.")
    atr_period = _num(form, "atr_period", int)
    card = template()
    for k in CHOICES:
        v = form.get(k, (card.get(k) if k != "judge" else card["stops"]["judge"]))
        if v not in CHOICES[k]:
            raise CardError(f"「{k}」 는 {' · '.join(CHOICES[k])} 가운데 하나여야 합니다.")
        if k == "judge":
            card["stops"]["judge"] = v
        else:
            card[k] = v
    params = {"short_window": short, "long_window": long}
    card.update({
        "strategy_id": slug, "version": 2, "name": str(form.get("name") or slug)[:80], "universe": [symbol],
        "entry": {"indicator": "ma_cross", "params": dict(params), "condition": "short_above_long"},
        "exit": {"indicator": "ma_cross", "params": dict(params), "condition": "short_below_long"},
        # 가장 긴 지표가 첫 값을 내는 봉(4.3 ④) — 장기 이동평균 · ATR(period + 1번째 봉)
        "warmup_bars": max(long, atr_period + 1),
    })
    card["stops"].update({"atr_period": atr_period, "atr_mult": _num(form, "atr_mult"), "take_rr": _num(form, "take_rr")})
    card["position_sizing"].update({"risk_pct": _num(form, "risk_pct"), "max_position_pct": _num(form, "max_position_pct"),
                                    "max_symbols": _num(form, "max_symbols", int)})
    try:
        pine_strategy.generate(card)
    except pine_strategy.GenerationError as exc:
        raise CardError(f"Pine 으로 옮길 수 없는 카드입니다: {exc}") from None
    return card


def save(user_id: str, form: dict, example_ids: set[str]) -> tuple[str, dict]:
    card = build_card(form)
    card_id = ID_PREFIX + card["strategy_id"]
    if card_id in example_ids:
        raise CardError(f"예시 카드와 같은 이름(「{card_id}」)으로는 저장할 수 없습니다.")
    d = user_dir(user_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{card_id}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return card_id, card


def delete(user_id: str, card_id: str) -> bool:
    path = files(user_id).get(card_id)
    if path is None:
        return False
    path.unlink()
    return True
