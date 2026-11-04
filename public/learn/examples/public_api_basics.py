"""공식 API 다루기 — 인증키 인코딩 · 응답 판정 · 한도 셈 · 재시도 · 쪽 넘기기를 네트워크 없이 보이는 예제.

실행    python public_api_basics.py        (표준 라이브러리만 · 네트워크 없음 · 실제 time.sleep 없음)
자료    모두 합성 — 키 `AbC%2B…` 는 가짜 값이고, 응답은 손으로 정한 것이다(실제 응답이 아니다)
흐름    ① 이미 인코딩된 키를 또 인코딩하면 다른 문자열이 된다
        ② 응답은 HTTP 상태와 본문 결과 코드를 함께 보고 가른다(0건의 뜻도 출처마다 다르다)
        ③ 하루 한도 안에서 며칠이 걸리는지 호출 방식에 따라 센다
        ④ 일시 오류만 기다렸다 다시 부른다 — 영구 오류와 한도 초과는 다시 부르지 않는다
        ⑤ 하루치가 한 번에 안 들어오면 조용히 자르지 않고 멈춘다
"""
from __future__ import annotations

import math
import random
import urllib.parse

# ── ① 인증키: Encoding 키를 params 에 그대로 넣으면 한 번 더 인코딩된다 ───────────────────────
ENCODED_KEY = "AbC%2Bdef%2FGhi%3D%3D"          # 포털이 주는 Encoding 키 꼴(가짜 값)


def key_demo() -> None:
    decoded = urllib.parse.unquote(ENCODED_KEY)       # 먼저 한 번 풀고
    print("① 풀어서 넣으면:", urllib.parse.urlencode({"serviceKey": decoded}))
    print("  그대로 넣으면:", urllib.parse.urlencode({"serviceKey": ENCODED_KEY}))


# ── ② 응답 판정: 상태 코드만 보면 틀린다 ────────────────────────────────────────────────
def judge(source: str, http: int, code: str, total: int | None = None) -> str:
    """합성 응답 한 건을 판정한다. code 는 본문 결과 코드(출처마다 이름이 다르다)."""
    if source == "포털":
        if code != "00":
            return "실패 — 결과 코드가 00 이 아님"
        return "정상 0건 — 휴장일이거나 아직 안 올라온 날(구분 안 됨)" if total == 0 else f"정상 {total}건"
    if source == "ECOS":                       # 오류도 HTTP 200 으로 온다
        if code == "INFO-200":
            return "데이터 없음 — 짧은 창이면 정상, 거래일이 든 긴 창이면 실패로 센다"
        if code.startswith(("INFO-100", "ERROR")):
            return f"실패 — HTTP {http} 인데 본문 {code}"
        return "정상"
    if source == "DART":
        if code == "000":
            return "정상"
        if code == "013":
            return "조회된 데이터 없음 — 정상 답"
        if code == "020":
            return "한도 초과 — 재시도하지 않고 오늘은 멈춤"
        return f"실패 — {code}"
    return "모르는 출처"


def judge_demo() -> None:
    rows = [("포털", 200, "00", 0), ("포털", 200, "00", 2870), ("포털", 200, "30", None),
            ("ECOS", 200, "INFO-100", None), ("ECOS", 200, "INFO-200", None),
            ("DART", 200, "013", None), ("DART", 200, "020", None)]
    print("② 응답 판정")
    for src, http, code, total in rows:
        extra = "" if total is None else f" totalCount={total}"
        print(f"  {src:3} HTTP {http} 결과코드 {code}{extra} → {judge(src, http, code, total)}")


# ── ③ 한도 셈: 같은 한도라도 호출 설계에 따라 하루와 일 년이 갈린다 ─────────────────────────────
def days_needed(calls: int, daily_limit: int) -> int:
    return math.ceil(calls / daily_limit)


def budget_demo() -> None:
    trading_days, stocks, limit = 1648, 2870, 10_000      # 거래일 수 · 하루치 행 수는 collector 주석의 실측값
    by_day = trading_days                                  # 하루치 전종목을 날짜당 1회
    by_stock = trading_days * stocks                       # 종목마다 날짜당 1회(가정)
    print("③ 한도 셈 (하루 한도", f"{limit:,})")
    print(f"  날짜별 1회  : {by_day:,} 호출 = 한도의 {by_day / limit:.1%} → {days_needed(by_day, limit)}일")
    print(f"  종목·날짜별 : {by_stock:,} 호출 → {days_needed(by_stock, limit)}일")


# ── ④ 재시도: 일시 오류만, 상한 안에서 ──────────────────────────────────────────────────
TRANSIENT = {408, 429, 500, 502, 503, 504}


def retry_fixed(statuses: list[int], waits: tuple[int, ...] = (20, 60, 120, 300)) -> str:
    """고정 기다림 표 방식(Qurious 포털 수집 방식) — 표가 바닥나면 포기한다."""
    waited = 0
    for i, st in enumerate(statuses):
        if st == 200:
            return f"성공 (시도 {i + 1}회, 기다림 합 {waited}초)"
        if st not in TRANSIENT:
            return f"영구 오류 {st} — 재시도하지 않음 (시도 {i + 1}회)"
        if i >= len(waits):
            return f"포기 — 기다림 합 {waited}초 후 error 로 기록"
        waited += waits[i]
    return f"포기 — 기다림 합 {waited}초 후 error 로 기록"


def retry_full_jitter(statuses: list[int], base: float = 1.0, cap: float = 30.0, tries: int = 5,
                      seed: int = 7) -> str:
    """지수 백오프 + Full Jitter(기다림 = 0 ~ min(cap, base×2^시도) 사이 무작위)."""
    rng = random.Random(seed)
    waited = 0.0
    for i, st in enumerate(statuses[:tries]):
        if st == 200:
            return f"성공 (시도 {i + 1}회, 기다림 합 {waited:.1f}초)"
        if st not in TRANSIENT:
            return f"영구 오류 {st} — 재시도하지 않음 (시도 {i + 1}회)"
        waited += rng.uniform(0, min(cap, base * 2 ** i))
    return f"포기 — 기다림 합 {waited:.1f}초"


def retry_demo() -> None:
    cases = {"일시 오류 뒤 성공": [504, 504, 200], "키 오류": [401], "계속 실패": [504] * 6}
    print("④ 재시도 — 고정 기다림 표(20·60·120·300초)")
    for name, seq in cases.items():
        print(f"  {name}: {retry_fixed(seq)}")
    print("④ 재시도 — 지수 백오프 + Full Jitter(시드 7)")
    for name, seq in {"일시 오류 뒤 성공": [503, 503, 429, 200], "키 오류": [401], "계속 실패": [504] * 5}.items():
        print(f"  {name}: {retry_full_jitter(seq)}")


# ── ⑤ 쪽 넘기기: 안 들어오면 조용히 자르지 않는다 ────────────────────────────────────────
def take_day(total_count: int, num_rows: int = 3000) -> str:
    if total_count > num_rows:
        return f"멈춤 — totalCount {total_count:,} > numOfRows {num_rows:,}: 이 날은 수집된 것으로 표시하지 않음"
    return f"한 번에 들어옴 — {total_count:,}행"


def page_demo() -> None:
    print("⑤ 쪽 넘기기")
    for n in (2870, 3001):
        print(f"  하루치 {n:,}행 → {take_day(n)}")


if __name__ == "__main__":
    key_demo()
    judge_demo()
    budget_demo()
    retry_demo()
    page_demo()
