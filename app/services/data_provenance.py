"""응답 숫자의 자료 출처 · 기준일 — 한 곳 (#134 후보 A · 2026-10-16).

왜 필요한가
-----------
지표 백테스트처럼 일봉으로 계산한 응답이 **어느 자료**(수집 DB 수정주가 · 증권사 · 외부 시세)로 계산했고
**마지막 봉이 언제**인지 말하지 않으면, 같은 종목 · 같은 날 두 사람의 숫자가 왜 다른지 알 수 없다.
#134 검수에서 마지막 봉이 이 PC 의 종가보다 0.37% 낮았는데(외부 시세의 장중 봉으로 보임) 응답에 출처 칸이
없어 확인하지 못했다. `stock.get_candles` 는 이미 `source` · `as_of` 를 돌려주는데 라우트가 버리고 있었다.

무엇을 돌려주나 — 응답 칸 셋
    source       "collector" | "kis" | 그 밖 원천 이름 | None (모르면 지어내지 않는다)
                 — 이름은 강사님 판(th06 `2852210` 라우트의 `result["source"]`)과 같게 둔다. 다음 기초 코드 반영 때
                   같은 뜻 칸이 둘(`source` · `data_source`)이 되지 않게(우리 모델 비교의 `data_source` 는 그대로).
    data_from    첫 봉 날짜 "YYYY-MM-DD" | None — 「10년」 을 불러도 수집 DB 는 2020-01-02 부터라 실제 기간이 짧다
                 (DF-15 D-1). 강사님 판의 `data_start` 는 지표 준비 기간을 뺀 평가 시작이라 뜻이 달라 이름을 나눴다.
    data_as_of   마지막 봉 날짜 "YYYY-MM-DD" | None (봉 없음)
    data_note    화면에 그대로 보일 한 줄 — 글은 **서버 한 곳**(여기)에만 둔다. 화면 코드에 같은 글을 두면 두 벌이 된다.
                 예) 「수집 DB 일봉(수정주가) · 2020-01-02 ~ 2026-10-15 종가」

- 수집 DB 는 공공데이터포털이 다음 날 낮에 주는 확정 값만 담아 오늘 봉이 없다 → 늘 「…종가까지」.
- 그 밖 길(증권사 · 외부 시세)의 **오늘 봉은 장중 값일 수 있다** → 날짜가 오늘이면 그 사실을 글로 붙인다.
- 봉 시각은 유닉스 초(그날 00:00 UTC = 09:00 KST — 수집 DB · 증권사 · 외부 시세 모두 이 꼴로 맞춘다)라
  UTC 날짜가 그 봉의 날짜다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

SOURCE_LABELS = {
    "collector": "수집 DB 일봉(수정주가)",
    "kis": "증권사(KIS) 일봉",
}
UNKNOWN_NOTE = "자료 출처를 알 수 없습니다"
INTRADAY_NOTE = "오늘 봉은 장중 값일 수 있음"


def source_label(source: str | None) -> str | None:
    """원천 이름 → 사람이 읽는 이름. 표에 없는 원천은 이름을 그대로 보인다(바꿔 부르지 않는다)."""
    if not source:
        return None
    return SOURCE_LABELS.get(source) or f"외부 시세 일봉({source})"


def last_bar_date(candles) -> str | None:
    """마지막 봉의 날짜(YYYY-MM-DD). 봉이 없거나 시각을 읽지 못하면 None."""
    return _bar_date(candles[-1]) if candles else None


def first_bar_date(candles) -> str | None:
    """첫 봉의 날짜(YYYY-MM-DD). 봉이 없거나 시각을 읽지 못하면 None."""
    return _bar_date(candles[0]) if candles else None


def _bar_date(bar: dict) -> str | None:
    t = bar.get("time")
    if isinstance(t, (int, float)) and not isinstance(t, bool):
        return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
    if isinstance(t, str):
        s = t.strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:]}"
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            return s[:10]
    return None


def candle_provenance(candle_data: dict | None, *, today: date | None = None) -> dict:
    """`get_candles` 결과 → {"source", "data_from", "data_as_of", "data_note"}.

    today: 「오늘 봉」 판정의 기준일(시험이 시계를 고정할 때) — 비우면 지금 KST 날짜.
    """
    data = candle_data or {}
    candles = data.get("candles") or []
    source = data.get("source") or None
    as_of = data.get("as_of") or last_bar_date(candles)
    first = first_bar_date(candles)
    span = as_of if first in (None, as_of) else f"{first} ~ {as_of}"
    label = source_label(source)
    if label is None:
        note = UNKNOWN_NOTE if as_of is None else f"{UNKNOWN_NOTE} · {span}"
    elif as_of is None:
        note = f"{label} · 봉 없음"
    elif source != "collector" and as_of == (today or datetime.now(KST).date()).isoformat():
        note = f"{label} · {span}({INTRADAY_NOTE})"
    else:
        note = f"{label} · {span} 종가"
    return {"source": source, "data_from": first, "data_as_of": as_of, "data_note": note}
