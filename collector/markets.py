"""시장 레지스트리와 `ohlcv-v2` 규칙 — 국내 · 미국 · 코인을 한 규격으로 (할 일 ①-06 · 2026-10-30).

이 파일이 답하는 질문: **"시장이 늘어도 규격 파일을 고치지 않으려면 — 시장마다 다른 값(시간대 · 통화 · 달력 ·
하루 경계)을 어디 한 곳에 두나."**  설계 근거: `docs/phase-2/01-analysis/research/시장범위-미국코인-거래기준-조사.md`
6.2 · 6.4절 단계 1 · 계약 문서 `docs/phase-3/02-design/system/시장-데이터-계약.md`.

원칙
----
- **국내 표 · `ohlcv-v1` · HF `krx-ohlcv` 는 그대로다.** 이 파일은 새 파일이고 수집기 러너가 부르지 않는다 —
  국내는 레지스트리의 한 줄(`XKRX`)일 뿐이다.
- `ohlcv-v2` = `ohlcv-v1` 의 모든 칸 + **`venue` · `currency` · `tz` 세 칸**. v1 의 `market` 은 그대로 「게시판」
  (KOSPI · KOSDAQ · ETF …)이고, 어느 거래소(시장)인지는 새 칸 `venue` 가 맡는다 — 이름을 뒤집으면 HF `krx-ohlcv` 의
  기존 파일 · 받는 쪽 코드가 한꺼번에 깨진다(하위 호환).
- `trade_date` 는 **거래소 현지 날짜**다. 미국 봉을 KST 로 바꿔 저장하면 날짜가 하루 밀린다(조사서 <표 6> 5행).
  `bar_start` 는 시간대가 붙은 시각이고, 현지 날짜는 `local_trade_date` 가 `tz` 로 센다(서머타임 포함).
- 값은 조사서 <표 6>(조회 2026-10-10) 그대로이며, **추정 값은 `None`** 으로 둔다 — 모르는 것을 숫자로 꾸미지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

try:                                   # `python collector/markets.py` 로 불러도 ohlcv 가 보이게(quality.py 와 같은 꼴)
    from collector import ohlcv as _v1
except ImportError:                    # pragma: no cover
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from collector import ohlcv as _v1

CONTRACT = "ohlcv-v2"
#: v1 에 더하는 칸 — `contract` 앞(끝)에 붙인다. v1 파일을 위치로 읽는 코드가 있어도 앞 열일곱 칸(`contract` 전)이 그대로여야 한다
EXTRA_COLUMNS: Tuple[str, ...] = ("venue", "currency", "tz")
COLUMNS: Tuple[str, ...] = tuple(c for c in _v1.COLUMNS if c != "contract") + EXTRA_COLUMNS + ("contract",)
REQUIRED: Tuple[str, ...] = tuple(_v1.REQUIRED) + EXTRA_COLUMNS
#: 기본 키 — 같은 종목 코드가 다른 시장에 있을 수 있어(예: 국내 `005930` · 미국 티커) `venue` 가 키에 든다
KEY: Tuple[str, ...] = ("venue",) + tuple(_v1.KEY)

#: 상태 — live(수집기가 매일 돈다) · stored(HF 비공개에 일회 수집본이 있다) · planned(아직 안 받는다) · local_only(팀에 안 나누고 각자 PC)
STATUSES = ("live", "stored", "planned", "local_only")
KINDS = ("equity", "crypto")
#: 하루 경계 — exchange_local_date(거래소 현지 날짜) · utc_00(UTC 00:00 경계 · 코인 일 캔들)
DAY_BOUNDARIES = ("exchange_local_date", "utc_00")


@dataclass(frozen=True)
class Market:
    venue: str                       # 시장 코드(거래소 ISO 10383 MIC · 코인은 MIC 가 없어 거래소 · 마켓 이름)
    name: str
    kind: str
    currency: str                    # 값의 통화(ISO 4217 · 코인은 견적 자산 — USDT 는 ISO 4217 이 아니다)
    tz: str                          # IANA 시간대
    calendar: str                    # `market_calendar`(우리 달력) · exchange_calendars 이름 · `24x7`
    day_boundary: str
    regular_session: Optional[Tuple[time, time]]   # 현지 시각 · 24시간 시장은 None
    ex_date_rule: Optional[str]      # 배당락 규칙 — 날짜 계산식이 아니라 칸(자료에 ex_date 가 오면 자료가 우선)
    annualization_days: Optional[int]  # 연환산 일수 — None 이면 달력에서 센다(주식 거래일 · 연 250~252 안팎)
    hf_dataset: str                  # HF 비공개 데이터셋 이름(스크립트에 이름을 박지 않는다 · D8)
    status: str
    source: str
    use_note: str                    # 쓰임의 한계(이용 조건에서 온 것)
    boards: Tuple[str, ...] = ()     # `market`(게시판) 값 — 국내는 v1 의 목록 그대로, 그 밖은 이 시장이 쓰는 값


MARKETS: Dict[str, Market] = {m.venue: m for m in (
    Market("XKRX", "한국거래소(국내 주식 · ETF · 지수)", "equity", "KRW", "Asia/Seoul", "market_calendar", "exchange_local_date",
           (time(9, 0), time(15, 30)), "record_minus_1_trading_day", None, "krx-ohlcv", "live",
           "공공데이터포털(공공누리) · KRX · DART",
           "정규장 09:00~15:30 KST · 배당락은 기준일 한 거래일 전(T+2 전제 — 결제 주기가 바뀌면 이 칸만 고친다)",
           boards=tuple(_v1.MARKETS)),
    Market("XNYS", "뉴욕증권거래소(미국 주식)", "equity", "USD", "America/New_York", "XNYS", "exchange_local_date",
           (time(9, 30), time(16, 0)), "record_date", None, "us-ohlcv", "planned",
           "HF Data Library(IEX HIST 1분봉 · CC BY 4.0) — 결정 2026-10-22",
           "학습 · 연구 백테스트 · 개념 학습 화면용 — 「not for trading」 · IEX 체결만(참고용) · Alpaca 는 표시 · 각자 로컬",
           boards=("EQUITY", "ETF")),
    Market("XNAS", "나스닥(미국 주식)", "equity", "USD", "America/New_York", "XNAS", "exchange_local_date",
           (time(9, 30), time(16, 0)), "record_date", None, "us-ohlcv", "planned",
           "HF Data Library(IEX HIST 1분봉 · CC BY 4.0) — 결정 2026-10-22",
           "XNYS 와 같다", boards=("EQUITY", "ETF")),
    Market("BINANCE_SPOT_USDT", "바이낸스 현물 USDT 마켓(코인)", "crypto", "USDT", "UTC", "24x7", "utc_00",
           None, None, 365, "crypto-ohlcv", "stored",
           "Binance Vision(CC BY-NC-SA 4.0 · 비상업) — HF `crypto-ohlcv` 일회 수집본 2026-10-22",
           "파생물도 같은 라이선스(ShareAlike) · 카드에 라이선스 · 약관 해시 · 원본은 data.binance.vision",
           boards=("SPOT",)),
    Market("UPBIT", "업비트 원화 마켓(코인)", "crypto", "KRW", "UTC", "24x7", "utc_00",
           None, None, 365, "", "local_only",
           "업비트 시세 API(IP 당 초당 10회 · 캔들 묶음 공유)",
           "각자 로컬 · 표시만 — 팀 저장소 · HF 에 쌓지 않는다(조사 D12 · C4)",
           boards=("SPOT",)),
)}


def get(venue: str) -> Market:
    """시장 한 줄 — 모르는 코드는 조용히 넘기지 않고 알린다."""
    try:
        return MARKETS[venue]
    except KeyError:
        raise KeyError(f"시장 레지스트리에 없는 코드: {venue!r} — {', '.join(MARKETS)} 중 하나") from None


def venues(status: Optional[str] = None, kind: Optional[str] = None) -> List[str]:
    return [m.venue for m in MARKETS.values()
            if (status is None or m.status == status) and (kind is None or m.kind == kind)]


def hf_datasets() -> List[str]:
    """HF 에 두는(또는 둘) 데이터셋 이름 — `local_only` 는 뺀다."""
    out: List[str] = []
    for m in MARKETS.values():
        if m.status != "local_only" and m.hf_dataset and m.hf_dataset not in out:
            out.append(m.hf_dataset)
    return out


def validate_registry() -> List[str]:
    """레지스트리 자체의 앞뒤가 맞는지 — 문제 목록(빈 목록이면 통과)."""
    bad: List[str] = []
    for m in MARKETS.values():
        if m.status not in STATUSES:
            bad.append(f"{m.venue}: 상태 {m.status!r} 가 {STATUSES} 가 아니다")
        if m.kind not in KINDS:
            bad.append(f"{m.venue}: 종류 {m.kind!r} 가 {KINDS} 가 아니다")
        if m.day_boundary not in DAY_BOUNDARIES:
            bad.append(f"{m.venue}: 하루 경계 {m.day_boundary!r} 가 {DAY_BOUNDARIES} 가 아니다")
        try:
            ZoneInfo(m.tz)
        except Exception:                                   # noqa: BLE001 — 시간대 이름이 틀린 것만 알면 된다
            bad.append(f"{m.venue}: 시간대 {m.tz!r} 를 모른다")
        if m.kind == "crypto" and (m.regular_session is not None or m.calendar != "24x7"):
            bad.append(f"{m.venue}: 코인은 24시간 시장이라 정규장이 없고 달력은 24x7 이어야 한다")
        if m.kind == "equity" and m.regular_session is None:
            bad.append(f"{m.venue}: 주식은 정규장이 있어야 한다")
        if m.kind == "crypto" and not m.annualization_days:
            bad.append(f"{m.venue}: 코인은 연환산 일수(365)를 적는다")
        if not m.boards:
            bad.append(f"{m.venue}: 게시판(`market`) 값 목록이 비었다")
        if m.status != "local_only" and not m.hf_dataset:
            bad.append(f"{m.venue}: HF 에 두는 시장인데 데이터셋 이름이 없다")
    return bad


# ==================================================
# 시간 — 거래소 현지 날짜
# ==================================================
def local_trade_date(venue: str, ts) -> date:
    """봉 시작 시각 → 그 시장의 `trade_date`.

    - 주식(`exchange_local_date`) : 거래소 시간대의 날짜(미국은 뉴욕 날짜 — 서머타임을 `tz` 가 알아서 센다)
    - 코인 일 캔들(`utc_00`) : UTC 날짜
    시간대 표시가 없는 시각은 받지 않는다(`ohlcv.to_kst` 와 같은 규칙 — 어느 나라 시각인지 모르는 값을 짐작하지 않는다).
    """
    m = get(venue)
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if getattr(ts, "tzinfo", None) is None:
        raise ValueError(f"시간대 표시가 없는 시각이다: {ts!r} — 어느 시간대인지 먼저 밝힌다")
    zone = ZoneInfo("UTC") if m.day_boundary == "utc_00" else ZoneInfo(m.tz)
    return ts.astimezone(zone).date()


# ==================================================
# ohlcv-v2 — 줄 만들기 · 검사
# ==================================================
def to_v2(row: dict, venue: str) -> dict:
    """`ohlcv-v1` 줄 → `ohlcv-v2` 줄 — 칸을 더하고 계약 이름만 바꾼다(값은 건드리지 않는다)."""
    m = get(venue)
    out = {c: row.get(c) for c in _v1.COLUMNS if c != "contract"}
    out.update(venue=m.venue, currency=m.currency, tz=m.tz, contract=CONTRACT)
    return {c: out.get(c) for c in COLUMNS}


#: v2 가 v1 규칙에 더하는 규칙 이름 → 설명(보고서 · 시험이 같은 이름을 쓴다)
RULES_V2: Dict[str, str] = {
    "bad_venue": "시장 코드가 레지스트리에 없다",
    "currency_mismatch": "통화가 그 시장의 레지스트리 값과 다르다",
    "tz_mismatch": "시간대가 그 시장의 레지스트리 값과 다르다",
    "bad_board": "market(게시판) 값이 그 시장이 쓰는 목록에 없다",
    "bar_start_naive": "분봉 시각에 시간대 표시가 없다",
    "trade_date_mismatch": "trade_date 가 봉 시작의 거래소 현지 날짜와 다르다(날짜 밀림)",
}


def check_v2(row: dict) -> List[str]:
    """줄 하나의 v2 규칙 위반 이름 목록(빈 목록이면 통과). v1 값 규칙(OHLC 순서 등)은 `collector.ohlcv` 가 따로 본다."""
    bad: List[str] = []
    venue = row.get("venue")
    if venue not in MARKETS:
        return ["bad_venue"]
    m = MARKETS[venue]
    if row.get("currency") != m.currency:
        bad.append("currency_mismatch")
    if row.get("tz") != m.tz:
        bad.append("tz_mismatch")
    if row.get("market") not in m.boards:
        bad.append("bad_board")
    bs = row.get("bar_start")
    if bs:
        try:
            expected = local_trade_date(venue, bs)
        except ValueError:
            bad.append("bar_start_naive")
        else:
            td = row.get("trade_date")
            td = date.fromisoformat(td) if isinstance(td, str) else td
            if td != expected:
                bad.append("trade_date_mismatch")
    return bad


if __name__ == "__main__":             # pragma: no cover — 사람이 한 번 훑어볼 때
    from collector.console import utf8_stdio
    utf8_stdio()                       # git bash(cp949)에서 ✅ · ⚠️ 로 죽지 않게
    problems = validate_registry()
    for v, m in MARKETS.items():
        print(f"{v:18} {m.status:10} {m.currency:5} {m.tz:17} {m.calendar:15} HF {m.hf_dataset or '-'}")
    print("✅ 레지스트리 앞뒤가 맞는다" if not problems else "⚠️ " + " / ".join(problems))
