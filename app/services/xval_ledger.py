"""TradingView ↔ LEAN 줄 단위 대사표 (할 일 ①-11 · 설계서 TradingView-교차검증-설계 3.4 · 3.5).

왜 `compare_fills` 를 고치지 않고 새 파일인가
---------------------------------------------
`compare_fills`(강민석 님 #329)는 날짜·방향 순서 정렬로 체결 한 건씩 견주는 진단용이다.
대사표는 그 위에서 (1) 진입·청산을 한 쌍의 **거래**로 묶어 수익률까지 맞대고, (2) 어긋난 줄마다
**원인 코드**를 달고, (3) 층(데이터 → 신호 → 체결 → 비용) 순서로 윗층이 어긋나면 아랫층을 무효로 본다.
응답 `fill_comparison` 은 그대로 두고 새 키 `reconcile_table` 로 붙인다.

세 가지 약속
------------
1. **허용 오차 숫자는 여기서 정하지 않는다.** 결과를 본 뒤 정한 범위는 사전등록이 아니다(논의결정대장 10-23 ·
   10-27). 호출하는 쪽이 `tolerance` 로 넘기고, 없으면 그 칸의 판정은 「기록만」이다.
2. **원인 코드는 호출하는 쪽이 선언한 설정 차이(`context`)가 실제로 그 어긋남을 설명할 때만 「설명됨」이다.**
   선언이 없거나 맞지 않으면 「미설명」 — 미설명은 결함으로 올린다.
3. 입력이 없는 층(종가 시계열 · TradingView 비용)은 값을 지어내지 않고 「unavailable」 로 둔다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.services import trading_cost

KST = timezone(timedelta(hours=9))

# 원인 코드 — 설계서 3.3 의 네 곳(data · judge · cost, 그리고 체결 시점 entry_mode · exit_mode) + 사이징 · 규칙 정의
CAUSE_CODES = ("data", "entry_mode", "exit_mode", "judge", "cost", "size", "rule_def")

LAYER_NAMES = {0: "데이터", 1: "신호", 2: "체결", 3: "비용"}

TIMEZONE_RULE = (
    "LEAN 체결 시각(UTC)은 KST 거래일로 바꿔 견준다. TradingView 날짜는 시간대가 없으면 "
    "차트 거래일로 본다 — 차트 시간대가 KST 가 아니면 날짜가 어긋날 수 있다."
)

# TradingView(Pine) 쪽에 넣기로 한 설정 — 강민석 님 #335 10-26 답. Pine 은 측정이 아니라 선언값이다.
TV_PINE_SETTINGS = {
    "initial_cash": 10_000_000.0,
    "currency": "KRW",
    "fee_pct": 0.015,
    "sell_tax_pct": 0.18,
    "slippage_bps": 10.0,
    "source": "강민석 님 #335 10-26 답(다음 봉 시가 · 수수료 0.015% · 매도세 0.18% · 슬리피지 10bp · 시작 1,000만 원)",
}

# 허용 오차 키 — 값이 None 이거나 없으면 그 항목은 「정하지 않음」
TOLERANCE_KEYS = (
    "layer0_close_bp",      # 층 0: 같은 날짜 종가 차(bp)
    "layer1_min_match_pct",  # 층 1: 신호 상태 일치율 하한(%)
    "layer2_date_days",     # 층 2: 체결 날짜 차(일)
    "layer2_price_bp",      # 층 2: 체결가 차(bp)
    "layer2_qty_pct",       # 층 2: 수량 차(%)
    "layer3_cost_bp",       # 층 3: 왕복 비용 차(bp)
)

_QTY_EPS = 1e-9


# ── 값 꺼내기 ───────────────────────────────────────────────────────────


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_of(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10].replace("/", "-"))
    except ValueError:
        return None


def _lean_kst_date(fill: dict) -> date | None:
    """LEAN 체결의 KST 거래일. time_utc 가 없으면 `date` 칸을 쓴다."""
    raw = fill.get("time_utc")
    if raw:
        try:
            dt = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(KST).date()
        except (TypeError, ValueError, OverflowError):
            pass
    return _date_of(fill.get("date"))


def _tv_date(fill: dict) -> date | None:
    raw = fill.get("time")
    if raw:
        try:
            dt = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                return dt.astimezone(KST).date()
            return dt.date()
        except (TypeError, ValueError, OverflowError):
            pass
    return _date_of(fill.get("date"))


# ── 체결 → 거래(진입에서 청산까지 한 묶음) ─────────────────────────────────


def _new_trade(direction: str, when: date | None, price: float | None, qty: float | None, fee: float) -> dict:
    return {
        "direction": direction,
        "entry_date": when, "entry_price_sum": 0.0, "entry_qty": 0.0, "entry_unweighted": [],
        "exit_date": None, "exit_price_sum": 0.0, "exit_qty": 0.0, "exit_unweighted": [],
        "exit_first_date": None,
        "fee": fee, "open": True,
    }


def _add_leg(trade: dict, leg: str, when: date | None, price: float | None, qty: float | None) -> None:
    """진입/청산 다리를 더한다. 수량이 없으면 가격만 단순 평균에 쓴다(수량 비교는 건너뜀)."""
    if price is None:
        return
    if qty is not None and qty > 0:
        trade[f"{leg}_price_sum"] += price * qty
        trade[f"{leg}_qty"] += qty
    else:
        trade[f"{leg}_unweighted"].append(price)
    if leg == "exit":
        if trade["exit_first_date"] is None:
            trade["exit_first_date"] = when
        trade["exit_date"] = when


def _finish(trade: dict) -> dict:
    """합산 칸을 평균가 칸으로 바꾸고 수익률을 계산한다."""
    def avg(leg: str) -> float | None:
        qty, total, loose = trade[f"{leg}_qty"], trade[f"{leg}_price_sum"], trade[f"{leg}_unweighted"]
        if qty > 0 and not loose:
            return total / qty
        if loose and qty == 0:
            return sum(loose) / len(loose)
        if qty > 0:  # 수량 있는 다리와 없는 다리가 섞였다 — 수량 있는 쪽만 쓴다
            return total / qty
        return None

    entry_price, exit_price = avg("entry"), avg("exit")
    sign = 1.0 if trade["direction"] == "long" else -1.0
    ret = None
    if entry_price and exit_price:
        ret = sign * (exit_price / entry_price - 1.0) * 100.0
    return {
        "direction": trade["direction"],
        "entry_date": trade["entry_date"],
        "entry_price": entry_price,
        "entry_qty": trade["entry_qty"] or None,
        "exit_date": trade["exit_date"],
        "exit_price": exit_price,
        "exit_qty": trade["exit_qty"] or None,
        "return_pct": ret,
        "fee": trade["fee"],
        "open": trade["open"],
    }


def tv_trades(tv_fills: list[dict]) -> list[dict]:
    """TradingView 거래 목록의 entry/exit 이벤트를 거래로 묶는다."""
    ordered = sorted(
        (f for f in (tv_fills or []) if isinstance(f, dict)),
        key=lambda f: (str(f.get("date") or ""), str(f.get("time") or "")),
    )
    trades: list[dict] = []
    cur: dict | None = None
    for f in ordered:
        side = str(f.get("side") or "").lower()
        event = str(f.get("event") or "").lower()
        when, price, qty = _tv_date(f), _num(f.get("price")), _num(f.get("quantity"))
        if event == "entry":
            direction = "long" if side == "buy" else "short"
            if cur is None:
                cur = _new_trade(direction, when, price, qty, 0.0)
            _add_leg(cur, "entry", when, price, qty)
        elif event == "exit" and cur is not None:
            _add_leg(cur, "exit", when, price, qty)
            cur["open"] = False
            trades.append(_finish(cur))
            cur = None
    if cur is not None:
        trades.append(_finish(cur))  # 끝까지 청산 안 된 거래
    return trades


def lean_trades(lean_fills: list[dict]) -> list[dict]:
    """LEAN 체결을 순포지션이 0 으로 돌아올 때까지 한 거래로 묶는다(분할 매수·매도 포함)."""
    ordered = sorted(
        (f for f in (lean_fills or []) if isinstance(f, dict)),
        key=lambda f: (str(f.get("time_utc") or f.get("date") or ""), int(f.get("order_id") or 0)),
    )
    trades: list[dict] = []
    cur: dict | None = None
    pos = 0.0
    for f in ordered:
        qty = _num(f.get("signed_quantity"))
        if qty is None:
            q = _num(f.get("quantity"))
            if q is None:
                continue
            qty = q if str(f.get("direction") or "").lower() == "buy" else -q
        price = _num(f.get("fill_price"))
        when = _lean_kst_date(f)
        fee = abs(_num(f.get("fee")) or 0.0)
        if abs(pos) <= _QTY_EPS:  # 새 거래의 시작
            cur = _new_trade("long" if qty > 0 else "short", when, price, abs(qty), fee)
            _add_leg(cur, "entry", when, price, abs(qty))
            pos = qty
            continue
        if cur is None:
            continue
        cur["fee"] += fee
        if (pos > 0) == (qty > 0):  # 같은 방향 — 추가 진입
            _add_leg(cur, "entry", when, price, abs(qty))
            pos += qty
            continue
        # 반대 방향 — 청산(일부 또는 전부). 보유보다 많이 팔면 남는 수량은 반대 방향 새 거래의 진입이다.
        closing = min(abs(qty), abs(pos))
        _add_leg(cur, "exit", when, price, closing)
        remainder = abs(qty) - closing
        pos += qty if remainder <= _QTY_EPS else (-pos)
        if abs(pos) <= _QTY_EPS:
            cur["open"] = False
            trades.append(_finish(cur))
            cur, pos = None, 0.0
            if remainder > _QTY_EPS:
                cur = _new_trade("long" if qty > 0 else "short", when, price, remainder, 0.0)
                _add_leg(cur, "entry", when, price, remainder)
                pos = remainder if qty > 0 else -remainder
    if cur is not None:
        trades.append(_finish(cur))
    return trades


# ── 짝짓기 ──────────────────────────────────────────────────────────────


def _align(tv: list[dict], lean: list[dict], window_days: int) -> list[tuple[dict | None, dict | None]]:
    """진입 날짜가 가까운 거래끼리 순서대로 짝짓는다. 창(window_days) 밖이거나 방향이 다르면 짝 없음.

    창은 허용 오차가 아니라 「같은 거래로 볼 수 있는 후보」의 범위다(짝 없는 거래는 표에 그대로 남는다).
    """
    n, m = len(tv), len(lean)
    gap = -2

    def score(a: dict, b: dict) -> int | None:
        if a["direction"] != b["direction"]:
            return None
        da, db = a.get("entry_date"), b.get("entry_date")
        if da is None or db is None:
            return None
        delta = abs((da - db).days)
        if delta > window_days:
            return None
        return 5 - min(delta, 4)

    dp = [[0] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0], back[i][0] = i * gap, "tv"
    for j in range(1, m + 1):
        dp[0][j], back[0][j] = j * gap, "lean"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            options = [(dp[i - 1][j] + gap, "tv"), (dp[i][j - 1] + gap, "lean")]
            s = score(tv[i - 1], lean[j - 1])
            if s is not None:
                options.append((dp[i - 1][j - 1] + s, "pair"))
            dp[i][j], back[i][j] = max(options, key=lambda o: (o[0], o[1] == "pair"))
    out: list[tuple[dict | None, dict | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        step = back[i][j]
        if step == "pair":
            out.append((tv[i - 1], lean[j - 1]))
            i, j = i - 1, j - 1
        elif step == "tv":
            out.append((tv[i - 1], None))
            i -= 1
        else:
            out.append((None, lean[j - 1]))
            j -= 1
    out.reverse()
    return out


# ── 허용 오차 · 원인 ───────────────────────────────────────────────────


def _tol(tolerance: dict | None, key: str) -> float | None:
    return _num((tolerance or {}).get(key))


def _bp(a: float | None, b: float | None) -> float | None:
    """b 가 a 보다 얼마나 큰가(bp). a 는 기준(TradingView)."""
    if a is None or b is None or a == 0:
        return None
    return (b / a - 1.0) * 10_000.0


def _declared(context: dict | None, engine: str, key: str) -> Any:
    return ((context or {}).get(engine) or {}).get(key)


def _differs(context: dict | None, key: str) -> bool:
    """두 엔진이 같은 항목을 선언했고 값이 다를 때만 True."""
    a, b = _declared(context, "tv", key), _declared(context, "lean", key)
    return a is not None and b is not None and a != b


def _cause_for_date(event: str, context: dict | None) -> list[str]:
    """날짜가 어긋난 이유로 선언된 설정 차이."""
    codes = []
    mode_key = "entry_mode" if event == "entry" else "exit_mode"
    if _differs(context, mode_key):
        codes.append(mode_key)
    if _differs(context, "judge"):
        codes.append("judge")
    return codes


def _cause_for_price(side: str, diff_bp: float, context: dict | None) -> list[str]:
    """같은 날 가격이 다른 이유. 슬리피지 선언 차이의 부호와 크기가 관찰과 맞을 때만 `cost`."""
    tv_slip = _num(_declared(context, "tv", "slippage_bp"))
    lean_slip = _num(_declared(context, "lean", "slippage_bp"))
    if tv_slip is None or lean_slip is None or tv_slip == lean_slip:
        return []
    expected = (lean_slip - tv_slip) * (1.0 if side == "buy" else -1.0)
    if (diff_bp > 0) == (expected > 0) and abs(diff_bp) <= abs(expected):
        return ["cost"]
    return []


# ── 줄 만들기 ───────────────────────────────────────────────────────────


def _event_row(seq: int, trade_seq: int, event: str, tv: dict | None, lean: dict | None,
               first_tv: bool, first_lean: bool, context: dict | None, tolerance: dict | None) -> dict:
    """진입 또는 청산 이벤트 한 줄(layer 2)."""
    d_key, p_key, q_key = f"{event}_date", f"{event}_price", f"{event}_qty"
    tv_date = tv.get(d_key) if tv else None
    lean_date = lean.get(d_key) if lean else None
    tv_price = tv.get(p_key) if tv else None
    lean_price = lean.get(p_key) if lean else None
    tv_qty = tv.get(q_key) if tv else None
    lean_qty = lean.get(q_key) if lean else None
    direction = (tv or lean or {}).get("direction", "long")
    side = ("buy" if event == "entry" else "sell") if direction == "long" else ("sell" if event == "entry" else "buy")

    row: dict[str, Any] = {
        "seq": seq, "trade_seq": trade_seq, "layer": 2, "event": event, "side": side,
        "tv_date": tv_date.isoformat() if tv_date else None,
        "tv_price": tv_price, "tv_qty": tv_qty,
        "lean_date": lean_date.isoformat() if lean_date else None,
        "lean_price": lean_price, "lean_qty": lean_qty,
        "diff_days": None, "diff_price_bp": None, "diff_qty": None, "diff_qty_pct": None, "diff_cost_bp": None,
        "cause": [], "explained": None, "verdict": None, "note": "",
    }

    if tv is None or lean is None:
        # 한쪽에만 있는 거래 — 첫 거래이고 규칙 정의 차이가 선언돼 있으면 rule_def
        only = "TradingView" if lean is None else "LEAN"
        first = first_tv if lean is None else first_lean
        if first and (context or {}).get("rule_def_first_bar_differs"):
            row["cause"] = ["rule_def"]
            row["explained"] = "설명됨"
            row["note"] = f"{only} 에만 있는 첫 거래 — 첫 봉 규칙 정의 차이(상태 판정 ↔ 교차 순간 진입)로 선언됨"
        else:
            row["explained"] = "미설명"
            row["note"] = f"{only} 에만 있는 거래 — 선언된 설정 차이로는 설명되지 않음"
        return row

    if (tv_date is None) != (lean_date is None):
        # 한쪽은 청산했는데 다른 쪽은 아직 보유 중 — 표에 남기고 설명은 사람이 한다
        row["explained"] = "미설명"
        row["verdict"] = "기록만(허용 오차 미정)"
        row["note"] = "한쪽만 이 이벤트가 있다(다른 쪽은 아직 보유 중) — 선언된 설정 차이로는 설명되지 않음"
        return row

    causes: list[str] = []
    unexplained = False
    if tv_date and lean_date:
        row["diff_days"] = (lean_date - tv_date).days
    row["diff_price_bp"] = _round(_bp(tv_price, lean_price), 2)
    if tv_qty is not None and lean_qty is not None:
        row["diff_qty"] = _round(lean_qty - tv_qty, 6)
        row["diff_qty_pct"] = _round((lean_qty / tv_qty - 1.0) * 100.0, 4) if tv_qty else None

    date_off = bool(row["diff_days"])
    if date_off:
        found = _cause_for_date(event, context)
        causes += found
        unexplained |= not found
    price_bp = row["diff_price_bp"]
    price_off = price_bp is not None and abs(price_bp) > 1e-6
    if price_off and not date_off:  # 날짜가 다르면 가격 차이는 그 날짜 차이를 따른 것으로 본다
        found = _cause_for_price(side, price_bp, context)
        causes += found
        unexplained |= not found
    qty_off = row["diff_qty"] is not None and abs(row["diff_qty"]) > 1e-9
    if qty_off:
        if _differs(context, "sizing"):
            causes.append("size")
        else:
            unexplained = True

    exact = not (date_off or price_off or qty_off)
    within = _within_event(row, tolerance)
    causes = list(dict.fromkeys(causes))
    row["cause"] = causes
    if exact or within is True:
        row["explained"] = "일치"
    elif unexplained or not causes:
        row["explained"] = "미설명"
    else:
        row["explained"] = "설명됨"
    if exact and within is None:
        row["verdict"] = "완전 일치"
    else:
        row["verdict"] = {True: "허용 오차 안", False: "허용 오차 밖", None: "기록만(허용 오차 미정)"}[within]
    row["note"] = _note(row)
    return row


def _within_event(row: dict, tolerance: dict | None) -> bool | None:
    """정해진 허용 오차 항목이 모두 안이면 True, 하나라도 밖이면 False, 정한 항목이 없으면 None."""
    checks = []
    days = _tol(tolerance, "layer2_date_days")
    if days is not None and row["diff_days"] is not None:
        checks.append(abs(row["diff_days"]) <= days)
    price = _tol(tolerance, "layer2_price_bp")
    if price is not None and row["diff_price_bp"] is not None:
        checks.append(abs(row["diff_price_bp"]) <= price)
    qty = _tol(tolerance, "layer2_qty_pct")
    if qty is not None and row["diff_qty_pct"] is not None:
        checks.append(abs(row["diff_qty_pct"]) <= qty)
    return all(checks) if checks else None


def _note(row: dict) -> str:
    if row["explained"] == "일치":
        return "두 엔진이 같다" if row["verdict"] == "완전 일치" else "허용 오차 안"
    bits = []
    if row["diff_days"]:
        bits.append(f"날짜 {row['diff_days']:+d}일")
    if row["diff_price_bp"] is not None and abs(row["diff_price_bp"]) > 1e-6:
        bits.append(f"가격 {row['diff_price_bp']:+.2f}bp")
    if row["diff_qty"]:
        bits.append(f"수량 {row['diff_qty']:+g}")
    label = ", ".join(bits)
    if row["explained"] == "설명됨":
        return f"{label} — 선언된 설정 차이({', '.join(row['cause'])})로 설명"
    return f"{label} — 선언된 설정 차이로는 설명되지 않음(결함 후보)"


def _round(value: float | None, nd: int) -> float | None:
    return None if value is None else round(value, nd)


def _cost_row(seq: int, trade_seq: int, tv: dict, lean: dict, context: dict | None, tolerance: dict | None) -> dict | None:
    """층 3 — LEAN 이 실제로 낸 왕복 비용 ↔ TradingView 가 선언한 왕복 비용."""
    declared = _num(_declared(context, "tv", "roundtrip_cost_bp"))
    fee, price, qty = lean.get("fee"), lean.get("entry_price"), lean.get("entry_qty")
    if declared is None or not fee or not price or not qty:
        return None
    measured = fee / (price * qty) * 10_000.0
    diff = measured - declared
    tol = _tol(tolerance, "layer3_cost_bp")
    within = None if tol is None else abs(diff) <= tol
    causes: list[str] = []
    if abs(diff) < 1e-6:
        explained = "일치"
    elif _declared(context, "tv", "cost_note"):
        # 층 3 은 수수료 · 세금만 견준다(슬리피지는 체결가에 실려 층 2 가 본다) — 근사 방식을 선언했을 때만 설명됨
        causes, explained = ["cost"], "설명됨"
    else:
        explained = "미설명"
    if within is True:
        explained = "일치"
    return {
        "seq": seq, "trade_seq": trade_seq, "layer": 3, "event": "cost", "side": None,
        "tv_date": None, "tv_price": None, "tv_qty": None,
        "lean_date": None, "lean_price": None, "lean_qty": None,
        "diff_days": None, "diff_price_bp": None, "diff_qty": None, "diff_qty_pct": None,
        "diff_cost_bp": round(diff, 2),
        "cause": causes, "explained": explained,
        "verdict": {True: "허용 오차 안", False: "허용 오차 밖", None: "기록만(허용 오차 미정)"}[within],
        "note": f"LEAN 왕복 비용 {measured:.2f}bp ↔ TradingView 선언 {declared:.2f}bp"
        + ("" if explained != "미설명" else " — 설명되지 않는 비용 차이"),
        "lean_cost_bp": round(measured, 2), "tv_cost_bp_declared": declared,
    }


# ── 층 요약 ────────────────────────────────────────────────────────────


def _layer0(closes: dict | None, tolerance: dict | None) -> dict:
    tv_c = (closes or {}).get("tv") or {}
    lean_c = (closes or {}).get("lean") or {}
    common = sorted(set(tv_c) & set(lean_c))
    if not common:
        return {"layer": 0, "name": LAYER_NAMES[0], "status": "unavailable",
                "summary": "두 엔진의 같은 날짜 종가 시계열이 없어 비교하지 않았다(값을 지어내지 않음)."}
    diffs = []
    for d in common:
        b = _bp(_num(tv_c[d]), _num(lean_c[d]))
        if b is not None:
            diffs.append(abs(b))
    if not diffs:
        return {"layer": 0, "name": LAYER_NAMES[0], "status": "unavailable", "summary": "비교 가능한 종가가 없다."}
    worst = max(diffs)
    tol = _tol(tolerance, "layer0_close_bp")
    status = "recorded" if tol is None else ("within" if worst <= tol else "outside")
    return {"layer": 0, "name": LAYER_NAMES[0], "status": status, "days_compared": len(diffs),
            "max_abs_close_diff_bp": round(worst, 2), "mean_abs_close_diff_bp": round(sum(diffs) / len(diffs), 2),
            "summary": f"{len(diffs)}일 종가 비교 — 최대 차 {worst:.2f}bp"}


def _layer1(signal_result: dict | None, tolerance: dict | None) -> dict:
    if not signal_result or signal_result.get("status") != "compared":
        reason = (signal_result or {}).get("reason") or "신호 CSV(SignalState_Entry/Exit)가 없어 비교하지 않았다."
        return {"layer": 1, "name": LAYER_NAMES[1], "status": "unavailable", "summary": reason}
    rates = [r for r in (signal_result.get("entry_match_rate_pct"), signal_result.get("exit_match_rate_pct")) if r is not None]
    worst = min(rates) if rates else None
    tol = _tol(tolerance, "layer1_min_match_pct")
    if tol is None or worst is None:
        status = "recorded"
    else:
        status = "within" if worst >= tol else "outside"
    return {"layer": 1, "name": LAYER_NAMES[1], "status": status, "min_match_rate_pct": worst,
            "mismatch_date_count": signal_result.get("mismatch_date_count"),
            "summary": f"신호 상태 일치율 최소 {worst}% · 어긋난 날 {signal_result.get('mismatch_date_count')}일"}


def _layer_from_rows(layer: int, rows: list[dict]) -> dict:
    mine = [r for r in rows if r["layer"] == layer]
    if not mine:
        return {"layer": layer, "name": LAYER_NAMES[layer], "status": "unavailable",
                "summary": "이 층의 줄이 없다." if layer == 2 else "비용 비교에 필요한 입력(LEAN 수수료 · TradingView 선언 비용)이 없다."}
    verdicts = [r["verdict"] for r in mine]
    bad = [r for r in mine if r["explained"] == "미설명"]
    if any(v == "허용 오차 밖" for v in verdicts):
        status = "outside"
    elif all(v in ("허용 오차 안", "완전 일치") for v in verdicts):
        status = "within"
    else:
        status = "recorded"
    return {"layer": layer, "name": LAYER_NAMES[layer], "status": status, "line_count": len(mine),
            "unexplained_count": len(bad), "summary": f"{len(mine)}줄 · 미설명 {len(bad)}줄"}


def _apply_invalidation(layers: list[dict], rows: list[dict]) -> None:
    """윗층이 허용 오차 밖이면 그 아래 층과 줄을 무효로 표시한다(설계서 3.4)."""
    broken_at = next((l["layer"] for l in layers if l["status"] == "outside"), None)
    if broken_at is None:
        return
    for l in layers:
        if l["layer"] > broken_at and l["status"] != "unavailable":  # 입력이 없는 층은 무효가 아니라 없는 채로 둔다
            l["status"] = "invalid"
            l["summary"] += f" — 층 {broken_at}({LAYER_NAMES[broken_at]})이 허용 오차 밖이라 무효"
    for r in rows:
        if r["layer"] > broken_at:
            r["verdict"] = "무효(윗층 어긋남)"


# ── 진입점 ─────────────────────────────────────────────────────────────


def build_ledger(
    tv_fills: list[dict],
    lean_fills: list[dict],
    *,
    signal_result: dict | None = None,
    closes: dict | None = None,
    tolerance: dict | None = None,
    context: dict | None = None,
    repro: dict | None = None,
    engine_settings: dict | None = None,
    pair_window_days: int = 5,
) -> dict:
    """줄 단위 대사표를 만든다.

    tv_fills        parse_trade_list_fills 의 결과(entry/exit 이벤트)
    lean_fills      LEAN 체결 목록(`lean_fills`)
    signal_result   compare_signals 의 결과(층 1)
    closes          {"tv": {날짜: 종가}, "lean": {날짜: 종가}} (층 0 · 없으면 unavailable)
    tolerance       TOLERANCE_KEYS 의 값. 없으면 그 칸은 「기록만」
    context         선언된 설정 차이 — {"tv": {...}, "lean": {...}, "rule_def_first_bar_differs": bool}
                    칸: entry_mode · exit_mode · judge · sizing · slippage_bp · roundtrip_cost_bp
    repro           대사표 머리 재현 기록(카드 sha256 · 데이터 기준일 · 코드 커밋 · LEAN 이미지 · TradingView 설정)
    """
    tv_list = tv_trades(tv_fills)
    lean_list = lean_trades(lean_fills)
    header = {
        "timezone_rule": TIMEZONE_RULE,
        "repro": repro or {},
        "tolerance": {k: _tol(tolerance, k) for k in TOLERANCE_KEYS},
        "tolerance_source": (tolerance or {}).get("source") or "허용 오차 미정 — 기록만 한다(사전등록 전에는 판정하지 않음)",
        "context": context or {},
        "engine_settings": engine_settings,
        "pair_window_days": pair_window_days,
        "caution": "실제 TradingView CSV 로 교차검증하기 전에는 「TradingView 와 일치」 로 쓰지 않는다.",
    }
    if not tv_list or not lean_list:
        return {
            "status": "unavailable",
            "reason": "TradingView 거래 목록 CSV 의 진입·청산과 LEAN 체결이 모두 있어야 대사표를 만들 수 있다.",
            "header": header, "layers": [], "trades": [], "rows": [], "summary": _summary([], 0, 0),
        }

    aligned = _align(tv_list, lean_list, pair_window_days)
    rows: list[dict] = []
    trades: list[dict] = []
    seq = 0
    first_tv = tv_list[0]
    first_lean = lean_list[0]
    for trade_seq, (t, l) in enumerate(aligned, start=1):
        base_tv = t is first_tv
        base_lean = l is first_lean
        for event in ("entry", "exit"):
            if event == "exit" and all(x is None or x.get("open") for x in (t, l)):
                continue  # 두 쪽 모두 아직 안 닫힌 거래의 청산 칸은 줄을 만들지 않는다
            seq += 1
            rows.append(_event_row(seq, trade_seq, event, t, l, base_tv, base_lean, context, tolerance))
        if t and l:
            cost = _cost_row(seq + 1, trade_seq, t, l, context, tolerance)
            if cost:
                seq += 1
                rows.append(cost)
        trades.append(_trade_line(trade_seq, t, l))

    layers = [_layer0(closes, tolerance), _layer1(signal_result, tolerance),
              _layer_from_rows(2, rows), _layer_from_rows(3, rows)]
    _apply_invalidation(layers, rows)
    paired = sum(1 for t, l in aligned if t and l)
    return {
        "status": "compared", "header": header, "layers": layers, "trades": trades, "rows": rows,
        "summary": _summary(rows, sum(1 for t, l in aligned if t and not l), sum(1 for t, l in aligned if l and not t),
                            paired=paired),
    }


def _trade_line(trade_seq: int, t: dict | None, l: dict | None) -> dict:
    """거래 한 쌍 단위의 수익률 대조(진입가 · 청산가 · 수익률)."""
    def side(x: dict | None) -> dict | None:
        if not x:
            return None
        return {
            "entry_date": x["entry_date"].isoformat() if x.get("entry_date") else None,
            "entry_price": x.get("entry_price"),
            "exit_date": x["exit_date"].isoformat() if x.get("exit_date") else None,
            "exit_price": x.get("exit_price"),
            "return_pct": _round(x.get("return_pct"), 4),
            "open": bool(x.get("open")),
        }
    tv_side, lean_side = side(t), side(l)
    diff = None
    if tv_side and lean_side and tv_side["return_pct"] is not None and lean_side["return_pct"] is not None:
        diff = round((lean_side["return_pct"] - tv_side["return_pct"]) * 100.0, 2)  # %p → bp
    return {"trade_seq": trade_seq, "tradingview": tv_side, "lean": lean_side,
            "return_diff_bp": diff,
            "status": "paired" if tv_side and lean_side else ("tradingview_only" if tv_side else "lean_only")}


def _summary(rows: list[dict], tv_only: int, lean_only: int, paired: int = 0) -> dict:
    by_explained: dict[str, int] = {"일치": 0, "설명됨": 0, "미설명": 0}
    by_cause: dict[str, int] = {}
    for r in rows:
        by_explained[r["explained"]] = by_explained.get(r["explained"], 0) + 1
        for c in r["cause"]:
            by_cause[c] = by_cause.get(c, 0) + 1
    return {
        "line_count": len(rows),
        "paired_trade_count": paired,
        "tradingview_only_trade_count": tv_only,
        "lean_only_trade_count": lean_only,
        "by_explained": by_explained,
        "by_cause": by_cause,
        "unexplained_count": by_explained.get("미설명", 0),
        "unexplained_is_defect": by_explained.get("미설명", 0) > 0,
    }


# ── 세 엔진 설정 한 값으로 ─────────────────────────────────────────────


def engine_settings_report(*, lean_initial_cash: float, paper_initial_cash: float | None = None,
                           when: Any = None, market: str = "KOSPI") -> dict:
    """TradingView · LEAN · 우리 모의의 시작 금액 · 통화 · 비용을 한 표로 맞대고 어긋남을 나열한다.

    비용은 「수수료 + 세금 왕복」(fee_tax_roundtrip_bp)과 「슬리피지 한쪽」(slippage_bps)을 따로 둔다 —
    LEAN 은 슬리피지를 체결가에, 수수료를 `fee` 에 싣기 때문에 층 3 은 앞의 것만 견준다.
    LEAN 과 모의는 같은 `trading_cost` 요율표를 읽는다. TradingView 는 Pine 에 넣기로 한 선언값이다.
    """
    when = when or date.today()
    fee_tax_bp = round(trading_cost.round_trip_rate(when, market=market, slippage_bps=0.0) * 10_000.0, 2)
    tv = TV_PINE_SETTINGS
    tv_fee_tax_bp = round((2 * tv["fee_pct"] + tv["sell_tax_pct"]) * 100.0, 2)
    slip = trading_cost.DEFAULT_SLIPPAGE_BPS
    engines = {
        "tradingview": {"initial_cash": tv["initial_cash"], "currency": tv["currency"],
                        "fee_tax_roundtrip_bp": tv_fee_tax_bp, "slippage_bps": tv["slippage_bps"],
                        "source": tv["source"]},
        "lean": {"initial_cash": float(lean_initial_cash), "currency": "KRW",
                 "fee_tax_roundtrip_bp": fee_tax_bp, "slippage_bps": slip,
                 "source": f"trading_cost 요율표(기준일 {when})"},
        "paper": {"initial_cash": paper_initial_cash, "currency": "KRW",
                  "fee_tax_roundtrip_bp": fee_tax_bp, "slippage_bps": slip,
                  "source": "paper_journal 이 쓰는 trading_cost 요율표와 같다"},
    }
    mismatches = []

    def spread(item: str, key: str, tolerance: float = 0.0, note: str = "") -> None:
        values = {k: v[key] for k, v in engines.items() if v[key] is not None}
        nums = [x for x in values.values() if isinstance(x, (int, float))]
        differs = (max(nums) - min(nums) > tolerance) if nums and len(nums) == len(values) else len(set(values.values())) > 1
        if differs:
            mismatches.append({"item": item, "values": values, **({"note": note} if note else {})})

    spread("initial_cash", "initial_cash")
    spread("currency", "currency")
    spread("fee_tax_roundtrip_bp", "fee_tax_roundtrip_bp", 1e-6,
           "TradingView 는 매도 전용 세금 칸이 없어 근사(편도 0.105%)이고, 거래대금이 달라 생기는 차이는 `cost` 원인 코드로 적는다")
    spread("slippage_bps", "slippage_bps", 1e-6)
    return {"engines": engines, "mismatches": mismatches, "all_same": not mismatches}
