"""공시 · 뉴스 수집의 작은 규칙들 — 정정 말머리 떼기 · 「쓸 수 있는 첫날」 · 공공누리 유형으로 본문 저장 가르기 · 코드 종류 알아보기.

실행    python disclosure_basics.py        (표준 라이브러리만 · 네트워크 없음)
자료    공시 제목 · 날짜는 손으로 정한 합성 값이고, ④ 의 코드는 형식을 보이려는 예시 값이다(검증자리 계산은 하지 않는다).
        실제 수집기(collector/disclosure.py · policy_news.py)의
        규칙을 아주 줄여 옮긴 것이라 실제 코드와 같지 않다. 휴장일 집합도 예시용(2026-10-05 · 10-09)이다.
흐름    ① 제목에서 [정정 말머리]와 (YYYY.MM) 기간 떼어 내기
        ② 접수일 → 다음 거래일(「쓸 수 있는 첫날」 — 공식 규정이 아니라 보수적 관행)
        ③ 기사마다 오는 공공누리 유형이 「1」 일 때만 본문을 둔다
        ④ 8자리 고유번호 · 6자리 종목코드 · 12자리 표준코드를 형식으로 구별한다
"""
from __future__ import annotations

import datetime as dt
import re

_PERIOD = re.compile(r"\((\d{4})\.(\d{2})\)\s*$")
_REVISION = re.compile(r"^\s*((?:\[[^\]]*\]\s*)+)")


def split_title(title: str) -> tuple[str, str, str]:
    """공시 제목 → (이름, 정정 말머리, 기간). 말머리가 여럿이면 ' · ' 로 잇는다."""
    revision = ""
    m = _REVISION.match(title)
    if m:
        revision = " · ".join(re.findall(r"\[([^\]]*)\]", m.group(1)))
        title = title[m.end():]
    period = ""
    p = _PERIOD.search(title)
    if p:
        period = f"{p.group(1)}-{p.group(2)}"
        title = title[:p.start()]
    return title.strip(), revision, period


HOLIDAYS = {dt.date(2026, 10, 5), dt.date(2026, 10, 9)}        # 예시용 — 실제 휴장일 표가 아니다


def next_trading_day(d: dt.date) -> dt.date:
    cur = d + dt.timedelta(days=1)
    while cur.weekday() >= 5 or cur in HOLIDAYS:
        cur += dt.timedelta(days=1)
    return cur


def available_from(rcept_dt: str) -> str:
    """접수일(YYYYMMDD) → 쓸 수 있는 첫날. 응답에 접수 시각이 없어 장 중인지 가릴 수 없으므로 다음 거래일로 둔다."""
    d = dt.datetime.strptime(rcept_dt, "%Y%m%d").date()
    return next_trading_day(d).isoformat()


def keeps_body(kogl_type: str) -> bool:
    """공공누리 제1유형(출처 표시만 하면 되는 유형)일 때만 본문을 둔다. 3 · 빈칸이면 제목 · 주소만."""
    return kogl_type == "1"


def code_kind(code: str) -> str:
    if re.fullmatch(r"\d{8}", code):
        return "고유번호(corp_code · 비상장 포함)"
    if re.fullmatch(r"[0-9A-Z]{6}", code):
        return "종목코드(stock_code · 상장사)"
    if re.fullmatch(r"[A-Z]{2}[0-9A-Z]{9}\d", code):
        return "표준코드(ISIN 꼴 · 12자리)"
    return "알 수 없음"


def main() -> None:
    print("① 제목 나누기")
    for t in ["사업보고서 (2025.12)", "[기재정정]사업보고서 (2025.12)", "[첨부추가][기재정정]반기보고서 (2026.06)",
              "주요사항보고서(유상증자결정)"]:
        print(f"   {t!r} -> {split_title(t)}")
    print("② 접수일 -> 쓸 수 있는 첫날(다음 거래일)")
    for d in ["20261002", "20261008", "20261012"]:
        print(f"   접수 {d} -> {available_from(d)}")
    print("③ 공공누리 유형 -> 본문 저장:", {k: keeps_body(k) for k in ["1", "3", ""]})
    print("④ 코드 종류:")
    for c in ["00126380", "005930", "A00593", "KR7005930003"]:
        print(f"   {c} -> {code_kind(c)}")


if __name__ == "__main__":
    main()
