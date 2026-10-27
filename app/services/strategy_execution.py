"""주문 경로의 카드 검증. 그림자 일지가 쓰는 공통 판단 함수는 변경하지 않는다."""
from __future__ import annotations

import math
import re
import sqlite3

from app.services import collector_db


def card_symbols(spec: dict, known_symbols: list[str]) -> list[str]:
    """카드 전체 universe를 사용한다. 모르는 시장을 KOSPI로 추정하지 않는다."""
    universe = spec.get("universe")
    if not isinstance(universe, list) or not universe:
        raise ValueError("전략 카드의 종목 목록이 비어 있습니다.")
    sizing = spec.get("position_sizing") or {}
    if not isinstance(sizing, dict):
        raise ValueError("전략 카드 수량 설정이 잘못되었습니다.")
    if "max_symbols" in sizing and (type(sizing["max_symbols"]) is not int or sizing["max_symbols"] < 1):
        raise ValueError("카드 보유 종목 수 상한은 양의 정수여야 합니다.")
    if "max_position_pct" in sizing:
        cap = float(sizing["max_position_pct"])
        if not math.isfinite(cap) or not 0 < cap <= 100:
            raise ValueError("카드 비중 상한은 0보다 크고 100 이하여야 합니다.")
    known = {s[:6]: s for s in known_symbols}
    symbols = []
    for raw in universe:
        code = str(raw).strip().upper()
        if not re.fullmatch(r"\d{6}(?:\.(?:KS|KQ))?", code):
            raise ValueError("전략 카드의 국내주식 종목 코드가 잘못되었습니다.")
        if "." not in code:
            symbol = known.get(code)
            if symbol is None:
                path = collector_db.db_path()
                if path is None:
                    raise ValueError(f"전략 종목 {code}의 시장을 확인할 수 없습니다.")
                with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as conn:
                    row = conn.execute(
                        "SELECT mrkt_ctg FROM price_daily WHERE srtn_cd = ? ORDER BY bas_dt DESC LIMIT 1",
                        (code,),
                    ).fetchone()
                if not row or row[0] not in ("KOSPI", "KOSDAQ"):
                    raise ValueError(f"전략 종목 {code}의 시장을 확인할 수 없습니다.")
                symbol = code + (".KS" if row[0] == "KOSPI" else ".KQ")
        else:
            symbol = code
        if symbol not in symbols:
            symbols.append(symbol)
    # max_symbols는 보유 종목 수 상한이다. 평가 대상을 잘라 청산 신호를 버리지 않는다.
    return symbols


def validate_rule_input(spec: dict, indicators: dict) -> None:
    """규칙 일부의 평가 실패·자료 부족을 점수 매매로 대체하지 않는다."""
    unsupported = {"entry_mode", "exit_mode", "stops", "judge", "lock", "reentry", "warmup_bars", "price_basis"} & spec.keys()
    sizing = spec.get("position_sizing") or {}
    if not isinstance(sizing, dict):
        raise ValueError("카드 수량 설정이 잘못되었습니다.")
    unsupported |= {"size_kind", "risk_pct"} & sizing.keys()
    if unsupported:
        raise ValueError("아직 지원하지 않는 카드 실행 규칙입니다: " + ", ".join(sorted(unsupported)))
    if spec.get("timeframe", "1d") != "1d":
        raise ValueError("현재 카드 주문은 일봉만 지원합니다.")
    closes = indicators.get("closes")
    if not isinstance(closes, list) or not closes:
        raise ValueError("카드 판단에 필요한 종가가 없습니다.")
    if any(isinstance(c, bool) or not isinstance(c, (float, int)) or not math.isfinite(c) or c <= 0 for c in closes):
        raise ValueError("카드 판단 종가에 누락 또는 잘못된 값이 있습니다.")
    for side in ("entry", "exit"):
        rule = spec.get(side)
        if not isinstance(rule, dict):
            raise ValueError(f"카드 {side} 규칙이 없습니다.")
        condition, indicator = rule.get("condition"), rule.get("indicator")
        params = rule.get("params") or {}
        if condition in ("always", "never"):
            continue
        if indicator == "ma_cross" and condition in ("short_above_long", "short_below_long"):
            short, long = params.get("short_window", 5), params.get("long_window", 20)
            if type(short) is not int or type(long) is not int or not 0 < short < long:
                raise ValueError("이동평균 기간이 잘못되었습니다.")
            needed = long
        elif indicator == "momentum" and condition in ("breakout_high", "breakdown_low"):
            window = params.get("breakout_window", 20)
            if type(window) is not int or window <= 0:
                raise ValueError("돌파 기간이 잘못되었습니다.")
            needed = window + 1
        else:
            raise ValueError(f"지원하지 않는 카드 {side} 규칙입니다.")
        if len(closes) < needed:
            raise ValueError(f"카드 판단에 {needed}개 종가가 필요합니다(현재 {len(closes)}개).")
