"""지금 값을 한 곳에서(quote_now) — 「현재가」 칸 · 모의 주문 체결 직전 확인이 함께 쓴다 (2026-10-19).

까닭(사용자 10-19): 투자 인디케이터의 삼성전자 「현재가」 가 210,000 인데 실제는 217,000 이었다. 화면이 수집 DB 의
마지막 종가(공공데이터는 다음 영업일에 공개)를 「현재가」 로 보였기 때문이다. 판단 · 백테스트 · 학습은 같은 자료로 다시
돌릴 수 있어야 해서 저장 자료를 그대로 쓰고, **실행 직전 확인과 화면 표시만** 지금 값을 쓴다
(조사서 docs/조사/실시간시세-지연표기-조사.md v1.0 — 7절 「기능별 두 갈래」 · 0절 결정).

값 찾는 차례(사용자 결정 2026-10-19)
    ① 로그인한 사람의 KIS 키로 KIS 현재가 조회        → 「증권사 조회 · 14:02:31」
       이용 조건상 실시간 시세는 자기 키 · 자기 화면까지다(코스콤 정보이용정책 · KIS 약관 제5조 ③) — 남의 화면에 쓰지 않는다
    ② stock.get_quote — 강사님 게이트웨이(공용 키 성격) → 「증권사 연계 조회 · 14:02」
                        또는 야후(국내 약 20분 지연)      → 「지연 시세(약 20분) · 13:40 체결」 · 해외는 「야후 시세 · 05:00 체결」
    ③ 수집 DB 마지막 종가(국내만)                      → 「10월 16일 종가」
「실시간」 이라는 낱말은 쓰지 않는다(거래소 계약이 있는 서비스만 쓰는 말 — 조사서 2절). 국내 장이 닫혀 있으면 「장 마감 · 」 을 붙인다
(해외 종목은 국내 장 시간으로 판정하지 않는다 — 시각만 밝힌다).
실시간 값은 저장하지 않는다 — 사람 · 종목별 10초 메모리 저장본만 둔다(HF · DB · 파일에 쓰지 않음 — 조사서 3.4).
글은 이 파일 한 곳에서만 짓는다(화면은 이스케이프해 보이기만).
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.services import collector_db, data_provenance, kis_credentials, kis_market_data, stock
from app.services.brokers.factory import get_broker_client

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))
CACHE_TTL_SEC = 10                      # KIS 모의는 초당 2건 — 화면 여러 개가 같은 값을 나눠 쓴다
CACHE_MAX = 2000                        # 넘으면 지난 것부터 비운다(사람 × 종목이라 하루에도 크지 않다)
_cache: dict[tuple[str, str], tuple[float, dict]] = {}
OPEN, CLOSE = dtime(9, 0), dtime(15, 30)
SOURCE_NAMES = {
    "kis_user": "증권사 조회(내 키)",
    "kis_gateway": "증권사 연계 조회",
    "delayed": "지연 시세(야후 · 약 20분)",
    "collector": "공공데이터 종가",
}
FOREIGN_QUOTE_NAME = "야후 시세"         # 해외 종목은 지연 시간을 단정하지 않는다(거래소마다 다르다)
# 출처 이름 「delayed」 = 강사님 시세 함수(stock.get_quote)가 게이트웨이가 아닌 길(야후)로 준 값 — 증권사 조회가 아니라는 뜻


def _now() -> datetime:
    return datetime.now(KST)


def market_state(now: datetime | None = None) -> str:
    """국내 정규장 「open」 · 「closed」 — 요일과 시각(09:00 ~ 15:30 KST)으로만 판정한다.

    공휴일 휴장은 보지 않는다: 수집기 거래일 달력을 여기서 열면 시험 · 이 PC 에서 수집 DB 를 여는 길이 생긴다
    (읽기 전용으로 붙은 SQLite 의 보조 파일이 지워져 앱이 멈춘 DF-81 꼴). 공휴일 표기는 3차 실시간 구조에서 달력과 함께.
    """
    now = (now or _now()).astimezone(KST)
    if now.weekday() >= 5 or not (OPEN <= now.time() < CLOSE):
        return "closed"
    return "open"


def _md(d: str | None) -> str:
    """「2026-10-16」 → 「10월 16일」. 모르면 빈 글(지어내지 않는다)."""
    try:
        x = date.fromisoformat((d or "")[:10])
    except ValueError:
        return ""
    return f"{x.month}월 {x.day}일"


def _when(as_of: str | None, fetched: datetime) -> str:
    """체결 시각 글 — 오늘 값이면 「15:19」, 다른 날 값이면 「10월 17일 05:00」(지난 날 값을 오늘 값처럼 보이지 않게)."""
    t = (as_of or "")[11:16]
    if not t:
        return ""
    d = (as_of or "")[:10]
    return t if d == fetched.strftime("%Y-%m-%d") else f"{_md(d)} {t}".strip()


def _label(source: str | None, *, as_of: str | None, fetched: datetime, state: str, domestic: bool = True) -> str:
    """화면에 그대로 보일 한 줄."""
    closed = "장 마감 · " if domestic and state == "closed" else ""
    if source == "kis_user":
        return f"{closed}증권사 조회 · {fetched:%H:%M:%S}"
    if source == "kis_gateway":
        return f"{closed}증권사 연계 조회 · {fetched:%H:%M}"
    if source == "delayed":
        when = _when(as_of, fetched)
        head = "지연 시세(약 20분)" if domestic else FOREIGN_QUOTE_NAME
        return f"{closed}{head}" + (f" · {when} 체결" if when else "")
    if source == "collector":
        return f"{_md(as_of)} 종가" if _md(as_of) else "종가(날짜 모름)"
    return "출처 모름"


def label_for(source: str | None, as_of: str | None = None, *, symbol: str | None = None,
              now: datetime | None = None) -> str:
    """다른 모듈(모의 주문 시세)이 같은 글을 쓰게 — 지금 시각 · 장 상태로 짓는다. 종목을 주면 국내 · 해외를 가른다."""
    fetched = (now or _now()).astimezone(KST)
    domestic = kis_market_data.is_krx(symbol) if symbol else True
    return _label(source, as_of=as_of, fetched=fetched, state=market_state(fetched), domestic=domestic)


def _result(symbol: str, source: str, price: float, *, change_pct: float | None, as_of: str | None,
            fetched: datetime, state: str, fallback: list[str], domestic: bool, name: str | None = None) -> dict:
    source_name = FOREIGN_QUOTE_NAME if source == "delayed" and not domestic else SOURCE_NAMES[source]
    return {
        "symbol": symbol, "name": name, "price": float(price), "change_pct": change_pct,
        "source": source, "source_name": source_name, "as_of": as_of,
        "fetched_at": fetched.strftime("%Y-%m-%d %H:%M:%S"), "market_state": state,
        "label": _label(source, as_of=as_of, fetched=fetched, state=state, domestic=domestic), "fallback": fallback,
    }


async def _user_creds(db, user_id) -> Any:
    """그 사람의 KIS 키 — 없으면 None(서버 공용 키로 대신하지 않는다 — kis_credentials.for_user). 키 값은 찍지 않는다."""
    if db is None or user_id is None:
        return None
    from app.models import BrokerSettings
    row = (await db.execute(select(BrokerSettings).where(BrokerSettings.user_id == user_id))).scalar_one_or_none()
    return kis_credentials.for_user(row)


async def _from_user_key(symbol: str, creds) -> dict | None:
    client = get_broker_client("kis", creds.app_key, creds.app_secret, paper=creds.paper)
    p = await client.get_price(symbol)          # 토큰은 키별로 나눠 쓴다(brokers/kis_token.shared_token — 1분 1회 발급 한도)
    if not p or not getattr(p, "current", 0):
        return None
    pct = getattr(p, "change_pct", None)
    return {"price": float(p.current), "change_pct": float(pct) if pct is not None else None,
            "name": getattr(p, "name", None) or None}


async def _last_close(symbol: str) -> dict | None:
    data = await collector_db.get_daily_candles(symbol, "1mo", "1d")
    candles = (data or {}).get("candles") or []
    if not candles or not candles[-1].get("close"):
        return None
    prov = data_provenance.candle_provenance(data)
    close = float(candles[-1]["close"])
    prev = candles[-2].get("close") if len(candles) > 1 else None
    pct = round((close / float(prev) - 1) * 100, 2) if prev else None
    return {"price": close, "change_pct": pct, "as_of": prov.get("data_as_of")}


def _remember(key: tuple[str, str], out: dict) -> None:
    now = time.monotonic()
    if len(_cache) >= CACHE_MAX:
        for k in [k for k, (t, _) in _cache.items() if now - t >= CACHE_TTL_SEC]:
            _cache.pop(k, None)
    _cache[key] = (now, out)


async def quote_now(symbol: str, *, db=None, user_id=None, fresh: bool = False, now: datetime | None = None) -> dict:
    """지금 값 하나와 그 값의 출처 · 시각 · 한 줄 글. 셋 다 못 받으면 price=None 과 까닭(fallback)."""
    symbol = (symbol or "").strip().upper()
    key = (str(user_id or "-"), symbol)
    hit = _cache.get(key)
    if hit and not fresh and time.monotonic() - hit[0] < CACHE_TTL_SEC:
        return hit[1]
    fetched = (now or _now()).astimezone(KST)
    domestic = kis_market_data.is_krx(symbol)
    state = market_state(fetched) if domestic else "unknown"   # 해외 장 상태는 여기서 판정하지 않는다
    fallback: list[str] = []
    out: dict | None = None

    if domestic:  # ① 내 키
        try:
            creds = await _user_creds(db, user_id)
            if creds is None:
                fallback.append("증권사 키 없음")
            else:
                got = await _from_user_key(symbol, creds)
                if got:
                    out = _result(symbol, "kis_user", got["price"], change_pct=got["change_pct"],
                                  as_of=fetched.strftime("%Y-%m-%d %H:%M"), fetched=fetched, state=state,
                                  fallback=fallback, domestic=True, name=got["name"])
                else:
                    fallback.append("증권사 조회 값 없음")
        except Exception as exc:  # noqa: BLE001 — 다음 길로 넘기되 까닭은 응답에 남긴다(오류 본문 · 키는 찍지 않는다)
            fallback.append(f"증권사 조회 실패({type(exc).__name__})")

    if out is None:  # ② 게이트웨이 · 야후
        try:
            q = await stock.get_quote(symbol)
            if q.get("price"):
                src = "kis_gateway" if q.get("source") == "kis" else "delayed"
                as_of = q.get("as_of") if src == "delayed" else fetched.strftime("%Y-%m-%d %H:%M")
                out = _result(symbol, src, q["price"], change_pct=q.get("change_pct"), as_of=as_of,
                              fetched=fetched, state=state, fallback=fallback, domestic=domestic, name=q.get("name"))
            else:
                fallback.append("지연 시세 없음")
        except Exception as exc:  # noqa: BLE001
            fallback.append(f"지연 시세 실패({type(exc).__name__})")

    if out is None and domestic:  # ③ 지난 종가
        try:
            lc = await _last_close(symbol)
            if lc:
                out = _result(symbol, "collector", lc["price"], change_pct=lc["change_pct"], as_of=lc["as_of"],
                              fetched=fetched, state=state, fallback=fallback, domestic=True)
            else:
                fallback.append("수집 DB 종가 없음")
        except Exception as exc:  # noqa: BLE001
            fallback.append(f"수집 DB 실패({type(exc).__name__})")

    if out is None:
        out = {"symbol": symbol, "name": None, "price": None, "change_pct": None, "source": None, "source_name": None,
               "as_of": None, "fetched_at": fetched.strftime("%Y-%m-%d %H:%M:%S"), "market_state": state,
               "label": "지금 가격을 받지 못했습니다", "fallback": fallback}
    _remember(key, out)
    return out


async def confirm_for_order(db, user_id, info: dict, *, fresh: bool = True) -> dict:
    """모의 주문 체결 직전 확인(사용자 결정 2026-10-19 「모의 주문은 체결 직전 실시간 확인까지」).

    info = paper_trading.resolve_stock(...) 의 결과(받아 둔 사전은 고치지 않고 사본을 돌려준다). 그 사람의 KIS 키가 있으면
    다시 받은 현재가로 바꾸고, 없으면 받아 둔 값(게이트웨이 · 야후)에 출처 · 시각만 붙인다. 국내 원화 종목만 바꾼다(해외는 환율 길이 따로).
    키가 없는 사람(대부분 · 시험 계정)은 네트워크를 더 타지 않는다. fresh=False 는 10초 저장본을 허용한다(미리보기 · 손절 · 익절 점검).
    """
    out = dict(info)
    if not out.get("quote_label") and out.get("quote_source"):
        out["quote_label"] = label_for(out["quote_source"], out.get("quote_as_of"), symbol=out.get("symbol"))
    sym = out.get("symbol") or ""
    if (out.get("currency") or "KRW").upper() != "KRW" or not kis_market_data.is_krx(sym):
        return out
    try:
        creds = await _user_creds(db, user_id)
    except Exception as exc:  # noqa: BLE001 — 키를 못 읽으면 받아 둔 값으로(까닭을 남긴다)
        out["quote_fallback"] = f"증권사 키 확인 실패({type(exc).__name__})"
        return out
    if creds is None:
        return out
    q = await quote_now(sym, db=db, user_id=user_id, fresh=fresh)
    if q.get("source") == "kis_user" and q.get("price"):
        out.update(price=q["price"], price_local=q["price"], quote_source="kis_user",
                   quote_as_of=q["as_of"], quote_label=q["label"])
    else:
        out["quote_fallback"] = " · ".join(q.get("fallback") or []) or None
    return out
