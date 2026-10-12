"""신호 설명 층 1 — T2 한 줄을 쉬운 말 한두 문장과 근거 표로 (목표 기능 ② 설계서 5.4.1 · 5.4.3 · `P01-①-5`).

이 파일이 답하는 질문: **"그날 이 종목이 왜 매수 · 매도 · 관망 쪽인가."**

입력은 T2 `signal_snapshots` 한 줄(또는 `mtf_signals.signal_at` 의 결과)이다. 주기마다 남아 있는 근거 문장
(`patterns.timeframe_score` 의 `reasons`)을 규칙 표(`RULES`)로 되읽어 점수를 다시 매기므로, **근거 표의 점수를
더하면 주기 점수가 되고, 가중 기여도를 더하면 종합 점수가 된다**(설명 기준 「충분」 — 근거가 점수를 모두 설명한다).
새 계산을 하지 않으니 이미 쌓인 T2 줄도 그대로 설명할 수 있다.

문장 틀(설계서 5.4.1): 「{주기} 기준으로 {큰 근거 둘}이라 {신호} 쪽입니다. 다만 {반대 근거 하나}입니다.」
쓰지 않는 말: 규칙 합산을 「AI」 라 부르기 · 「오를 것」 같은 단정 · 확률처럼 읽히는 신뢰도 · 「강력」.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

KIND = "signal"
METHOD = "rule"

#: 주기 → (이동평균 단위 · 문장에 쓰는 이름)
UNITS = {"60m": "봉", "1d": "일", "1w": "주"}

#: 근거 문장에 쓰지 않는 말(설계서 5.4.1) — `DISCLAIMER` 는 확률이 「아니라」 고 말하므로 검사에서 뺀다
FORBIDDEN = ("AI", "인공지능", "확률", "강력", "반드시", "보장", "추천", "오를 것", "내릴 것")

DISCLAIMER = ("지표 규칙의 점수를 합친 결과입니다. 신뢰도는 주기들이 얼마나 같은 방향인지를 나타낼 뿐 확률이 아니며, "
              "투자 권유가 아닙니다.")


@dataclass(frozen=True)
class Rule:
    key: str
    pattern: str        # `timeframe_score` 근거 문장과 맞추는 정규식
    points: int         # 그 근거가 주기 점수에 더하는 값
    rule: str           # 규칙 — {u} 는 이동평균 단위
    phrase: str         # 문장 조각 — {u} 단위 · {v} 관측값


#: `patterns.timeframe_score` 의 근거 문장 열한 가지 — 순서는 그 함수가 근거를 붙이는 순서
RULES = (
    Rule("rsi_low", r"RSI (\S+) 과매도", +2, "RSI(14) 30 미만", "RSI 가 30 아래인 {v}까지 떨어진 상태"),
    Rule("rsi_high", r"RSI (\S+) 과매수", -2, "RSI(14) 70 초과", "RSI 가 70 위인 {v}까지 오른 상태"),
    Rule("rsi_mid", r"RSI (\S+) 중립", 0, "RSI(14) 30 ~ 70", "RSI 가 30 ~ 70 사이인 {v}"),
    Rule("ma_up", r"MA5 > MA20 상승 배열", +1, "5{u} 평균 > 20{u} 평균", "5{u}선이 20{u}선 위"),
    Rule("ma_down", r"MA5 < MA20 하락 배열", -1, "5{u} 평균 ≤ 20{u} 평균", "5{u}선이 20{u}선 아래"),
    Rule("macd_up", r"MACD > 시그널", +1, "MACD(12 · 26) > 신호선(9)", "MACD 가 신호선 위"),
    Rule("macd_down", r"MACD < 시그널", -1, "MACD(12 · 26) ≤ 신호선(9)", "MACD 가 신호선 아래"),
    Rule("bb_upper", r"볼린저 상단 돌파", -1, "종가 > 볼린저 상단(20 · 2σ)", "종가가 볼린저 상단을 넘어 과열된 상태"),
    Rule("bb_lower", r"볼린저 하단 이탈", +1, "종가 < 볼린저 하단(20 · 2σ)", "종가가 볼린저 하단 아래로 내려간 상태"),
    Rule("mid_up", r"20MA 위 \(추세 우호\)", +1, "종가 > 20{u} 평균", "종가가 20{u}선 위"),
    Rule("mid_down", r"20MA 아래 \(추세 비우호\)", -1, "종가 ≤ 20{u} 평균", "종가가 20{u}선 아래"),
)
#: RSI 값을 문장에 쓰지 못할 때(값 없음 · 반올림 경계)의 조각
_NO_VALUE = {"rsi_low": "RSI 가 30 아래로 떨어진 상태", "rsi_high": "RSI 가 70 위로 오른 상태", "rsi_mid": "RSI 가 30 ~ 70 사이"}
_COMPILED = [(r, re.compile(rf"^{r.pattern}$")) for r in RULES]
_COUNT = {1: "하나", 2: "둘", 3: "셋"}
_DET = {1: "한", 2: "두", 3: "세"}


class UnknownReason(ValueError):
    """규칙 표에 없는 근거 문장 — `timeframe_score` 가 바뀌었는데 이 표를 고치지 않았다."""


def match_rule(text: str) -> tuple[Rule, str | None]:
    """근거 문장 → (규칙, 문장에서 읽은 값). RSI 만 값이 있다."""
    for rule, rx in _COMPILED:
        m = rx.match(text)
        if m:
            return rule, (m.group(1) if m.groups() else None)
    raise UnknownReason(text)


# ── 낱말 ──────────────────────────────────────────────────────────────────

def _has_batchim(word: str) -> bool:
    # 「분봉(60분)」 처럼 괄호로 끝나면 괄호 앞 낱말로 고른다
    ch = re.sub(r"\s*\([^)]*\)$", "", word.rstrip())[-1]
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    return ch in "013678"       # 영 · 일 · 삼 · 육 · 칠 · 팔


def _and(word: str) -> str:
    return word + ("이고" if _has_batchim(word) else "고")


def _because(word: str) -> str:
    return word + ("이라" if _has_batchim(word) else "라")


def _topic(word: str) -> str:
    return word + ("은" if _has_batchim(word) else "는")


def _subject(word: str) -> str:
    return word + ("이" if _has_batchim(word) else "가")


# ── 근거 표 ───────────────────────────────────────────────────────────────

def _rsi_text(rule: Rule, rsi: float | None) -> str:
    """RSI 를 문장에 쓸 꼴 — T2 는 소수 첫째 자리로 반올림해 두므로 경계(29.96 → 30.0)에서 규칙과 어긋나 보이면 숫자를 뺀다."""
    if rsi is None or rsi != rsi:     # NaN
        return ""
    if (rule.key == "rsi_low" and rsi >= 30) or (rule.key == "rsi_high" and rsi <= 70):
        return ""
    return f"{rsi:.1f}"


def _num(x: float) -> str:
    """가격 · 지표 값을 읽기 쉬운 꼴로 — 100 이상은 천 단위 쉼표 · 정수, 그보다 작으면 소수 둘째 자리."""
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:,.2f}"


#: 규칙마다 근거 표에 보일 값(T2 `timeframes` 의 칸 · 이름표) — 그 규칙이 실제로 비교한 두 값
_OBSERVED = {
    "ma_up": (("ma5", "5{u}선"), ("ma20", "20{u}선")), "ma_down": (("ma5", "5{u}선"), ("ma20", "20{u}선")),
    "macd_up": (("macd", "MACD"), ("macd_signal", "신호선")), "macd_down": (("macd", "MACD"), ("macd_signal", "신호선")),
    "bb_upper": (("last", "종가"), ("bb_upper", "상단")), "bb_lower": (("last", "종가"), ("bb_lower", "하단")),
    "mid_up": (("last", "종가"), ("ma20", "20{u}선")), "mid_down": (("last", "종가"), ("ma20", "20{u}선")),
}


def _observed(rule: Rule, t: dict, unit: str) -> tuple[str | None, dict]:
    """근거 한 줄의 관측값 — (보일 글, 값). 값을 저장하지 않던 옛 T2 줄(2026-10-12 전)은 RSI 밖의 규칙에서 (None, {})."""
    if rule.key.startswith("rsi"):
        v = _rsi_text(rule, t.get("rsi"))
        return (f"RSI {v}" if v else None), ({"rsi": t["rsi"]} if v else {})
    pairs = _OBSERVED.get(rule.key, ())
    if not pairs or any(t.get(k) is None for k, _ in pairs):
        return None, {}
    return " · ".join(f"{name.format(u=unit)} {_num(t[k])}" for k, name in pairs), {k: t[k] for k, _ in pairs}


def evidence(snapshot: dict) -> list[dict]:
    """주기마다 근거 → 근거 표 한 줄씩. 기여도 = 점수 × 주기 가중치 ÷ 시세 있는 주기 가중치 합 (모두 더하면 종합 점수)."""
    tfs = snapshot.get("timeframes") or []
    valid = [t for t in tfs if "score" in t]
    wsum = sum(t["weight"] for t in valid) or 1.0
    rows = []
    for t in valid:
        unit = UNITS.get(t["timeframe"], "봉")
        for text in t.get("reasons", []):
            rule, _v = match_rule(text)
            value = _rsi_text(rule, t.get("rsi")) if rule.key.startswith("rsi") else ""
            phrase = rule.phrase.format(u=unit, v=value) if value else _NO_VALUE.get(rule.key, rule.phrase).format(u=unit)
            observed, values = _observed(rule, t, unit)
            rows.append({
                "timeframe": t["timeframe"], "label": t["label"], "key": rule.key,
                "rule": rule.rule.format(u=unit),
                "observed": observed, "values": values,
                "points": rule.points,
                "contribution": rule.points * t["weight"] / wsum,
                "text": phrase,
            })
    return rows


def _direction(signal: str, composite: float) -> int:
    if signal == "매수":
        return 1
    if signal == "매도":
        return -1
    return 1 if composite > 0 else -1 if composite < 0 else 0


def _order(rows: list[dict]) -> list[dict]:
    # 기여도가 큰 순 — 같으면 가중치가 큰 주기(일 · 주 · 60분) · 규칙 표 순서
    tf_rank = {"1d": 0, "1w": 1, "60m": 2}
    key_rank = {r.key: i for i, r in enumerate(RULES)}
    return sorted(rows, key=lambda r: (-abs(r["contribution"]), tf_rank.get(r["timeframe"], 9), key_rank[r["key"]]))


# ── 문장 ──────────────────────────────────────────────────────────────────

def _confidence_text(snapshot: dict, sign: int) -> str:
    """신뢰도를 숫자 대신 말로 — 「주기 셋 중 둘이 매수 쪽」 (설계서 5.4.1)."""
    valid = [t for t in snapshot.get("timeframes") or [] if "score" in t]
    n = len(valid)
    if n == 0:
        return "시세가 있는 주기가 없습니다."
    buy = sum(1 for t in valid if t["score"] > 0)
    sell = sum(1 for t in valid if t["score"] < 0)
    if sign == 0 or snapshot["signal"] == "관망":
        parts = [f"매수 쪽 {_COUNT.get(buy, buy)}" if buy else "", f"매도 쪽 {_COUNT.get(sell, sell)}" if sell else "",
                 f"0점 {_COUNT.get(n - buy - sell, n - buy - sell)}" if n - buy - sell else ""]
        return f"주기 {_COUNT.get(n, n)} — " + " · ".join(p for p in parts if p)
    same = buy if sign > 0 else sell
    side = "매수" if sign > 0 else "매도"
    if same == n:
        head = f"주기 {_COUNT.get(n, n)} 모두 {side} 쪽"
    else:
        head = f"주기 {_COUNT.get(n, n)} 중 {_subject(_COUNT.get(same, str(same)))} {side} 쪽"
    return f"{head} · 기운 정도 {'큼' if snapshot.get('strength') == '강' else '보통'}"


def _summary(snapshot: dict, rows: list[dict], sign: int) -> str:
    valid = [t for t in snapshot.get("timeframes") or [] if "score" in t]
    signal = snapshot["signal"]
    if not valid:
        return "시세가 없어 판단하지 않았습니다(관망)."
    composite = round(float(snapshot["composite"]), 1)
    if signal == "관망":
        n = _DET.get(len(valid), str(len(valid)))
        shown = f"{composite:+.1f}" if composite else "0.0"      # 0 에는 부호를 붙이지 않는다
        head = (f"{n} 주기를 합친 점수({shown})가 매수 · 매도 기준(±1)에 닿지 않아 관망입니다."
                if len(valid) > 1 else f"점수({shown})가 매수 · 매도 기준(±1)에 닿지 않아 관망입니다.")
        buy = next((r for r in rows if r["points"] > 0), None)
        sell = next((r for r in rows if r["points"] < 0), None)
        if buy and sell:
            head += f" {buy['label']} {buy['text']}인 쪽과 {sell['label']} {sell['text']}인 쪽이 엇갈립니다."
        return head
    # 매수 · 매도 — 가장 크게 민 주기를 앞에, 그 주기의 같은 방향 근거 둘
    lead = max(valid, key=lambda t: t["score"] * t["weight"] * sign)
    lead_rows = [r for r in rows if r["timeframe"] == lead["timeframe"] and r["points"] * sign > 0][:2]
    if not lead_rows:                       # 가장 크게 민 주기에 같은 방향 근거가 없을 수 없다 — 방어
        lead_rows = [r for r in rows if r["points"] * sign > 0][:2]
    words = [r["text"] for r in lead_rows]
    reason = _because(words[0]) if len(words) == 1 else f"{_and(words[0])} {_because(words[1])}"
    tail = "쪽으로 크게 기울었습니다" if snapshot.get("strength") == "강" else "쪽입니다"
    out = f"{lead['label']} 기준으로 {reason} {signal} {tail}."
    counter = next((r for r in rows if r["points"] * sign < 0), None)
    if counter:
        where = f"같은 {lead['label']}에서" if counter["timeframe"] == lead["timeframe"] else _topic(counter["label"])
        out += f" 다만 {where} {counter['text']}입니다."
    return out


def _notes(snapshot: dict) -> list[str]:
    notes = []
    for t in snapshot.get("timeframes") or []:
        if "score" not in t:
            notes.append(f"{_topic(t['label'])} {t.get('error', '시세 없음')} — 나머지 주기로만 셈했습니다.")
        elif t["timeframe"] == "1w" and t.get("partial"):
            notes.append(f"주봉은 이번 주가 끝나지 않아 {t.get('last_bar', '그날')} 까지의 일봉으로 만든 봉입니다.")
    as_of = str(snapshot["as_of"])
    names = [p["name"] for p in snapshot.get("patterns") or [] if str(p.get("date")) == as_of]
    if names:
        notes.append(f"그날 일봉에서 찾은 패턴: {' · '.join(dict.fromkeys(names))} — 패턴 이름만으로 5거래일 뒤 방향이 "
                     "갈린다는 근거는 없습니다(전 종목 통계 · 설계서 3.5).")
    return notes


def explain(snapshot: dict) -> dict:
    """T2 한 줄(dict) → 설명. 같은 입력이면 같은 문장이다(설명 기준 「정확」)."""
    rows = _order(evidence(snapshot))
    sign = _direction(snapshot["signal"], float(snapshot["composite"]))
    as_of = snapshot["as_of"]
    return {
        "kind": KIND, "method": METHOD,
        "symbol": snapshot["symbol"], "as_of": as_of.isoformat() if isinstance(as_of, date) else str(as_of),
        "definition": snapshot["definition"],
        "signal": snapshot["signal"], "strength": snapshot.get("strength"),
        "confidence": round(float(snapshot["confidence"]), 4),
        "composite": round(float(snapshot["composite"]), 4),
        "summary": _summary(snapshot, rows, sign),
        "confidence_text": _confidence_text(snapshot, sign),
        "reasons": [r for r in rows if sign and r["points"] * sign > 0],
        "counter_reasons": [r for r in rows if sign and r["points"] * sign < 0],
        "evidence": rows,
        "notes": _notes(snapshot),
        "disclaimer": DISCLAIMER,
    }


# ── T2 읽기 ───────────────────────────────────────────────────────────────

def normalize_symbol(symbol: str) -> str:
    """화면의 `005930.KS` · `035720.KQ` 도 받는다 — T2 는 단축코드로 적는다."""
    s = symbol.strip().upper()
    return re.sub(r"\.(KS|KQ)$", "", s)


async def load_snapshot(session, symbol: str, on: date | None = None) -> dict | None:
    """지금 정의 판에서 `on` 이전(포함)의 가장 최근 T2 줄. 없으면 None."""
    from sqlalchemy import select

    from app.models.signal import SignalSnapshot
    from app.services.ta_utils import DEFINITION

    stmt = select(SignalSnapshot).where(SignalSnapshot.symbol == normalize_symbol(symbol),
                                        SignalSnapshot.definition == DEFINITION)
    if on is not None:
        stmt = stmt.where(SignalSnapshot.as_of <= on)
    row = (await session.execute(stmt.order_by(SignalSnapshot.as_of.desc()).limit(1))).scalar_one_or_none()
    if row is None:
        return None
    return {c.name: getattr(row, c.name) for c in SignalSnapshot.__table__.columns}
