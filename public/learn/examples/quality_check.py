"""데이터 품질 검사 — 다른 곳에서 받은 일봉 파일을 값 규칙과 기준 자료로 판정하는 예제.

실행    python quality_check.py       (표준 라이브러리만)
기준    카카오(035720) 2021-04-05 ~ 04-23 종가 — 원 가격과 수정 가격 두 줄
        출처 금융위원회 「주식시세정보」(공공데이터포털) — 몇 줄만 교육용으로 인용 · 수정 가격은 계수 0.2007168(2021-04-15 액면분할)로 계산
받은 파일  기준에서 만든 가짜 일곱 개 — 흔히 만나는 문제를 하나씩 담았다

판정 순서
    ① 값 규칙   가격 > 0 · 저가 ≤ 시가·종가 ≤ 고가 · 거래량 ≥ 0 · 같은 날짜 두 줄 없음 · 거래일이 아닌 날 없음
    ② 대조      겹치는 날의 종가가 기준과 같은 비율(차이 1원 이하 또는 0.01% 이하를 같다고 본다)
                원 가격 · 수정 가격 둘 다와 비교하고, 하루 앞 · 뒤로 옮겨서도, 1,000배 단위로도 비교한다
                끊김(분할) 전 구간에서 「받은 값 ÷ 기준 값」 이 한 숫자로 일정하면 수정 방식이 다른 것이다
    ③ 판정      규칙 위반 → 🔴 · 일치율 99% 이상 🟢 · 95~99% 🟡 · 수정 방식만 다름 🟡 · 그 밖 🔴(원인 후보를 함께 적는다)
"""
from __future__ import annotations

import json
from datetime import date
from statistics import median

FACTOR = 112000 / 558000                      # 2021-04-15 액면분할의 계수


def _d(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:]))


# 기준일 · 시가 · 고가 · 저가 · 종가 · 거래량 — 거래정지 사흘은 평평한 봉(직전 종가)으로 둔다
REF_RAW = [(_d(d), int(o), int(h), int(l), int(c), int(v)) for d, o, h, l, c, v in (x.split() for x in """
20210405 503000 505000 500000 502000   310400
20210406 506000 545000 505000 544000  1724958
20210407 544000 544000 526000 542000   820896
20210408 539000 561000 534000 548000   912514
20210409 554000 561000 551000 558000   788839
20210412 558000 558000 558000 558000        0
20210413 558000 558000 558000 558000        0
20210414 558000 558000 558000 558000        0
20210415 120500 132500 118000 120500 17115015
20210416 115500 120500 115500 119000 13709555
20210419 120000 122000 117500 119000  5441693
20210420 119000 121000 118000 119500  2952174
20210421 119500 119500 117000 118000  4461636
20210422 118000 119500 117500 117500  2279180
20210423 116500 118500 114500 117500  2473720
""".strip().splitlines())]
DAYS = [r[0] for r in REF_RAW]                 # 거래일 달력(이 구간)
SPLIT_DAY = _d("20210415")
REF_ADJ = [(d, *(round(x * FACTOR) if d < SPLIT_DAY else x for x in (o, h, l, c)), v) for d, o, h, l, c, v in REF_RAW]


def fakes() -> dict[str, list[tuple]]:
    """기준에서 가짜 파일 여섯을 만든다."""
    shifted = [(DAYS[i - 1], *r[1:]) for i, r in enumerate(REF_RAW) if i > 0]          # 날짜가 하루 앞당겨짐
    thousand = [(r[0], *(x / 1000 for x in r[1:5]), r[5]) for r in REF_RAW]            # 천 원 단위
    dup = REF_RAW[:8] + [(REF_RAW[7][0], 560000, 561000, 556000, 559000, 1000)] + REF_RAW[8:]
    broken = list(REF_RAW)
    broken[1] = (broken[1][0], 506000, 540000, 505000, 544000, 1724958)                # 고가 < 종가
    broken[10] = (broken[10][0], 120000, 122000, 117500, 119000, -5)                     # 거래량 음수
    by_ratio = [(d, *((x / 5 if d < SPLIT_DAY else x) for x in (o, h, l, c)), v) for d, o, h, l, c, v in REF_RAW]
    return {"정상(원 가격)": list(REF_RAW), "수정 가격": list(REF_ADJ), "하루 밀림": shifted,
            "천 원 단위": thousand, "같은 날 두 줄": dup, "규칙 위반": broken, "분할 비율로 고친 값": by_ratio}


def rule_problems(rows: list[tuple]) -> list[str]:
    found, seen = [], set()
    for d, o, h, l, c, v in rows:
        if min(o, h, l, c) <= 0:
            found.append(f"{d} 가격이 0 이하")
        elif not (l <= min(o, c) and max(o, c) <= h):
            found.append(f"{d} 저가 ≤ 시가·종가 ≤ 고가 를 어김")
        if v < 0:
            found.append(f"{d} 거래량이 음수")
        if d in seen:
            found.append(f"{d} 같은 날짜가 두 줄")
        if d not in DAYS:
            found.append(f"{d} 거래일이 아님")
        seen.add(d)
    return found


def same(a: float, b: float) -> bool:
    return abs(a - b) <= max(1.0, abs(b) * 0.0001)


def match_rate(rows: list[tuple], ref: list[tuple], shift: int = 0, scale: float = 1.0) -> float:
    """겹치는 날 중 종가가 같은 비율. shift=+1 이면 받은 날짜를 하루 뒤 거래일로 옮겨 비교한다."""
    ref_close = {r[0]: r[4] for r in ref}
    hits = total = 0
    for d, *_, c, _v in rows:
        if d not in DAYS:
            continue
        i = DAYS.index(d) + shift
        if 0 <= i < len(DAYS) and DAYS[i] in ref_close:
            total += 1
            hits += same(c * scale, ref_close[DAYS[i]])
    return hits / total if total else 0.0


def basis_ratio(rows: list[tuple]) -> float | None:
    """끊김 뒤는 기준과 같고, 끊김 전 구간의 「받은 값 ÷ 기준 수정 값」 이 한 숫자로 일정하면 그 숫자."""
    adj = {r[0]: r[4] for r in REF_ADJ}
    before = [r[4] / adj[r[0]] for r in rows if r[0] in adj and r[0] < SPLIT_DAY]
    after_ok = all(same(r[4], adj[r[0]]) for r in rows if r[0] in adj and r[0] >= SPLIT_DAY)
    if not before or not after_ok or max(before) / min(before) - 1 > 0.0005:
        return None
    k = median(before)
    return k if abs(k - 1) > 0.0001 else None


def judge(rows: list[tuple]) -> dict:
    report = {"rows": len(rows), "rule_problems": rule_problems(rows)}
    raw, adj = match_rate(rows, REF_RAW), match_rate(rows, REF_ADJ)
    report["match"] = {"raw": round(raw, 4), "adjusted": round(adj, 4)}
    best = max(raw, adj)
    report["price_basis"] = "원 가격" if raw >= adj else "수정 가격"
    hints = []
    if best < 0.95:
        for shift in (-1, 1):
            r = max(match_rate(rows, REF_RAW, shift), match_rate(rows, REF_ADJ, shift))
            if r >= 0.95:
                hints.append(f"날짜를 {'하루 뒤' if shift == 1 else '하루 앞'}로 옮기면 일치율 {r:.0%} — 날짜가 밀려 있음(시간대 의심)")
        ratios = [ref[4] / r[4] for r, ref in zip(sorted(rows), REF_RAW) if r[4] > 0]
        k = median(ratios) if ratios else 0
        if 900 <= k <= 1100:
            hints.append(f"기준 ÷ 받은 값의 가운데 값 {k:,.0f} — 천 원 단위로 보임")
        ratio = basis_ratio(rows)
        if ratio:
            implied = FACTOR * ratio
            hints.append(f"분할 전 구간에서 받은 값 ÷ 기준 수정 값 = {ratio:.5f} 로 일정 — 수정 방식이 다름 "
                         f"(받은 자료의 계수 {implied:.5f} = 1/{1 / implied:.3f})")
    report["hints"] = hints
    if report["rule_problems"]:
        report["verdict"] = "🔴 규칙 위반"
    elif best >= 0.99:
        report["verdict"] = f"🟢 일치 ({report['price_basis']})"
    elif best >= 0.95:
        report["verdict"] = "🟡 대부분 일치 — 원인 확인"
    elif any(h.startswith("분할 전 구간") for h in hints):
        report["verdict"] = "🟡 수정 방식만 다름"
    else:
        report["verdict"] = "🔴 기준과 다름"
    return report


def main() -> None:
    for name, rows in fakes().items():
        r = judge(rows)
        print(f"[{name}] {r['verdict']} · 원 가격 일치 {r['match']['raw']:.0%} · 수정 가격 일치 {r['match']['adjusted']:.0%}")
        for p in r["rule_problems"][:3]:
            print(f"    규칙: {p}")
        for h in r["hints"]:
            print(f"    단서: {h}")
    print("보고서 한 개의 모양 (하루 밀림)")
    print(json.dumps(judge(fakes()["하루 밀림"]), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
