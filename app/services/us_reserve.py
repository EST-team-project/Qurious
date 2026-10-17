"""미국주식 예약 주문(모의투자) — 장이 닫힌 때 받아 두고 **다음 정규장 시작가**로 체결한다 (L10 · 2026-10-17).

왜 필요한가
-----------
장이 닫힌 토요일에 미국주식 시장가 모의 주문을 내면 안내 없이 금요일 마감 값으로 바로 체결됐다
(모의투자 점검 셋째 바퀴 끊긴 곳 30 · 이슈 #256 의 미국 쪽). 실제 증권사는 장이 닫히면 예약 주문으로 받아
다음 정규장에 체결한다 → 모의도 그렇게 한다(사용자 결정 「C — 장 닫힌 날은 예약 주문」 · Figma 「미국주식 주문 화면」).

어떻게 — 모의 장부(주인 강민석)는 그대로 두고 장부의 함수를 부르기만 한다
-------------------------------------------------------------------------------
- 예약 = 주문 표(`orders`)의 한 줄 — `order_kind="reserved"` · `status="pending"` · `source="RESERVED"`.
  스탑 주문(`order_kind="stop"`)과 같은 꼴이라 새 표 · 이전(migration) · 탈퇴 처리가 따로 필요 없다.
  `source` 가 RESERVED 라 모의투자 주문 내역(WEB · PAPER · PINE 만 읽음 · #219)에 섞이지 않는다.
- 체결 = 예약한 뒤 **처음 열린 정규장의 시가**(그날 일봉의 open) × **체결 처리 때 받은 환율** ·
  체결 시각 = 그 정규장 시작(09:30 ET). 장부 정산은 `paper_trading._fill_stock_order`(가격 · 시각을 받는 체결 함수)
  로 하고, 그 함수가 내역 줄(PAPER)을 따로 남긴다 — 스탑 주문 발동(`check_stop_orders`)과 같은 길.
- 체결 처리는 예약 목록을 읽을 때 한다. 언제 읽어도 「그 정규장의 시가」 라 결과가 같다(멱등) —
  시가를 아직 못 받았으면 지어내지 않고 기다린다(다른 날 값으로 메우지 않는다 · 말없는 fallback 금지).
- 장 시간은 뉴욕 시각 09:30 ~ 16:00 · 휴장일 · 조기 마감은 NYSE 공지 표(아래). **표 밖의 해는 판정하지 않는다**(None).
- 한계(모의라서): 실제 시가 체결 · 호가 · 부분 체결은 흉내 내지 않는다. 환율은 시가 시각의 환율이 아니라 체결
  처리 때 받은 값이다 — 응답 · 화면 글이 그렇게 말한다.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order
from app.services import overseas_orders, paper_trading, stock

ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")
OPEN_T = time(9, 30)
CLOSE_T = time(16, 0)

#: NYSE 휴장일 — 「Holidays & Trading Hours」(https://www.nyse.com/markets/hours-calendars · 2026-10-17 확인).
#: 크리스마스 줄은 검색 발췌에서 잘려 NYSE 관례(토요일이면 금요일 · 일요일이면 월요일)로 채웠다(확실도 중간).
#: 2028-01-01(토)은 NYSE 표에 「—」(앞 금요일로 옮기지 않음).
NYSE_HOLIDAYS = frozenset({
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25),
    date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26), date(2027, 5, 31),
    date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6), date(2027, 11, 25), date(2027, 12, 24),
    date(2028, 1, 17), date(2028, 2, 21), date(2028, 4, 14), date(2028, 5, 29), date(2028, 6, 19),
    date(2028, 7, 4), date(2028, 9, 4), date(2028, 11, 23), date(2028, 12, 25),
})
#: 추수감사절 다음 날 13:00 ET 조기 마감(같은 공지 · 확인한 것만).
EARLY_CLOSE = {date(2026, 11, 27): time(13, 0), date(2027, 11, 26): time(13, 0), date(2028, 11, 24): time(13, 0)}
CALENDAR_YEARS = frozenset({2026, 2027, 2028})
CALENDAR_SOURCE = "NYSE 휴장일 공지(2026 ~ 2028)"

KIND = "reserved"
SOURCE = "RESERVED"
FILL_SOURCE = "PAPER"        # 체결 내역 줄은 모의투자 주문 내역에 보이게
MAX_PENDING = 20             # 한 사람의 대기 예약 상한 — 화면 실수로 줄이 쌓이지 않게
WEEKDAYS = "월화수목금토일"
NOTE = "다음 정규장 시작가(그날 첫 거래 값)로 체결됩니다 · 환율은 체결 처리 때 받은 값 · 모의투자이며 실제 주문이 나가지 않습니다"


class ReserveError(paper_trading.PaperTradeError):
    """예약을 받지 않는 까닭 — 라우트가 400 으로 돌려준다."""


class MarketOpenError(ReserveError):
    """정규장이 열려 있어 예약할 까닭이 없음 — 라우트가 409 로 돌려준다(바로 주문하면 된다)."""


# ── 장 시간 ─────────────────────────────────────────────────────────────────

def trading_day(d: date) -> bool | None:
    """그날 정규장이 서나. 휴장일 표 밖의 해면 None — 모르는 날을 「연다」 고 짐작하지 않는다."""
    if d.year not in CALENDAR_YEARS:
        return None
    return d.weekday() < 5 and d not in NYSE_HOLIDAYS


def session_bounds(d: date) -> tuple[datetime, datetime]:
    """그날 정규장 시작 · 끝(뉴욕 시각 · 서머타임은 시간대가 맞춘다)."""
    return (datetime.combine(d, OPEN_T, tzinfo=ET), datetime.combine(d, EARLY_CLOSE.get(d, CLOSE_T), tzinfo=ET))


def _aware(t: datetime) -> datetime:
    """시간대 없는 시각은 UTC 로 읽는다(DB 의 timestamptz 는 시간대가 붙어 오지만, 시험 · 옛 줄이 다를 수 있어 한 곳에서)."""
    return t if t.tzinfo is not None else t.replace(tzinfo=timezone.utc)


def next_open_after(t: datetime) -> datetime | None:
    """`t` 뒤에 처음 시작하는 정규장의 시작 시각(뉴욕). 표 밖으로 나가면 None."""
    t = _aware(t)
    d = t.astimezone(ET).date()
    for _ in range(15):                       # 가장 긴 연휴도 열흘을 넘지 않는다
        td = trading_day(d)
        if td is None:
            return None
        if td:
            start, _end = session_bounds(d)
            if start > t:
                return start
        d += timedelta(days=1)
    return None


def kst_label(dt: datetime | None) -> str | None:
    """「10-19(월) 22:30」 — 화면이 그대로 보이는 한국 시각 글."""
    if dt is None:
        return None
    k = _aware(dt).astimezone(KST)
    return f"{k:%m-%d}({WEEKDAYS[k.weekday()]}) {k:%H:%M}"


def market_state(now: datetime | None = None) -> dict:
    """미국 정규장 상태 한 곳(SSoT) — 화면은 `label` 을 그대로 보인다."""
    now = _aware(now or datetime.now(timezone.utc))
    d = now.astimezone(ET).date()
    td = trading_day(d)
    if td is None:
        return {"open": None, "next_open_kst": None, "close_kst": None, "source": CALENDAR_SOURCE,
                "label": "휴장일 표에 없는 해라 미국 정규장 상태를 판정하지 않습니다"}
    if td:
        start, end = session_bounds(d)
        if start <= now < end:
            return {"open": True, "next_open_kst": None, "close_kst": kst_label(end), "source": CALENDAR_SOURCE,
                    "label": f"미국 정규장 열림 · {kst_label(end)}(KST) 마감"}
    nxt = next_open_after(now)
    return {"open": False, "next_open_kst": kst_label(nxt), "close_kst": None, "source": CALENDAR_SOURCE,
            "label": f"미국 정규장 닫힘 · 다음 정규장 {kst_label(nxt)}(KST)" if nxt
                     else "미국 정규장 닫힘 · 다음 정규장은 휴장일 표 밖이라 모름"}


# ── 예약 받기 · 취소 ──────────────────────────────────────────────────────────

async def place(db: AsyncSession, user_id: uuid.UUID, symbol: str, quantity: int, *, now: datetime | None = None) -> dict:
    """장이 닫힌 때 미국주식 매수 예약 한 줄. 매도 예약은 받지 않는다(해외 매도 비용이 준비될 때까지 — 화면과 같은 까닭)."""
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ReserveError("수량은 1 이상의 정수여야 합니다.")
    if overseas_orders.is_domestic(symbol):
        raise ReserveError("국내 종목은 예약을 받지 않습니다 — 국내주식 모의주문을 쓰세요.")
    state = market_state(now)
    if state["open"] is None:
        raise ReserveError(state["label"])
    if state["open"]:
        raise MarketOpenError("지금은 미국 정규장이 열려 있습니다 — 예약 말고 바로 주문하세요.")
    pending = (await db.execute(select(func.count()).select_from(Order).where(
        Order.user_id == user_id, Order.order_kind == KIND, Order.status == "pending"))).scalar_one()
    if pending >= MAX_PENDING:
        raise ReserveError(f"대기 중인 예약이 {MAX_PENDING}건이라 더 받지 않습니다 — 먼저 취소하거나 체결을 기다리세요.")
    info = await paper_trading.resolve_stock(symbol)
    if (info.get("currency") or "KRW").upper() == "KRW":
        raise ReserveError("원화 종목은 예약을 받지 않습니다 — 국내주식 모의주문을 쓰세요.")
    order = Order(
        user_id=user_id, symbol=info["symbol"], name=(info.get("name") or info["symbol"])[:100],
        order_type="buy", quantity=quantity,
        # price 는 예약할 때 본 원화 환산 시세(참고) — 체결가는 avg_fill_price 에 따로 남는다
        price=float(info["price"]), status="pending", broker="virtual", source=SOURCE, order_kind=KIND,
    )
    db.add(order)
    await db.flush()
    return {"status": "pending", "order_id": str(order.id), "symbol": order.symbol, "name": order.name,
            "quantity": quantity, "next_open_kst": state["next_open_kst"], "note": NOTE}


async def cancel(db: AsyncSession, user_id: uuid.UUID, order_id: str) -> dict:
    try:
        oid = uuid.UUID(str(order_id))
    except ValueError:
        raise ReserveError("유효하지 않은 예약 번호입니다.") from None
    order = (await db.execute(select(Order).where(
        Order.id == oid, Order.user_id == user_id, Order.order_kind == KIND, Order.status == "pending",
    ))).scalar_one_or_none()
    if order is None:
        raise ReserveError("취소할 대기 예약을 찾지 못했습니다(이미 체결 · 취소됐을 수 있습니다).")
    order.status = "cancelled"
    return {"status": "cancelled", "order_id": str(order.id)}


# ── 체결 처리 ─────────────────────────────────────────────────────────────────

async def session_open_price(symbol: str, session_day: date, now: datetime) -> float | None:
    """그 정규장 날의 시가(현지 통화). 일봉 `time` 은 공급자 그대로(09:30 ET)이거나 그날 00:00 UTC 라
    **UTC 날짜**로 맞추면 둘 다 그날이다. 못 찾으면 None — 다른 날 값으로 메우지 않는다."""
    days = (now.astimezone(ET).date() - session_day).days
    period = "5d" if days <= 3 else "1mo" if days <= 25 else "6mo" if days <= 170 else "2y"
    data = await stock.get_candles(symbol, period=period, interval="1d", max_age_hours=0)
    for c in data.get("candles") or []:
        ts, op = c.get("time"), c.get("open")
        if isinstance(ts, (int, float)) and op and datetime.fromtimestamp(ts, timezone.utc).date() == session_day:
            return float(op)
    return None


async def fill_due(db: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None) -> list[dict]:
    """정규장이 이미 열린 대기 예약을 그 정규장의 시가로 체결한다. 같은 줄을 두 번 체결하지 않게 줄을 잠근다."""
    now = _aware(now or datetime.now(timezone.utc))
    rows = (await db.execute(select(Order).where(
        Order.user_id == user_id, Order.order_kind == KIND, Order.status == "pending",
    ).order_by(Order.created_at).with_for_update(skip_locked=True))).scalars().all()
    out = []
    for o in rows:
        first = next_open_after(o.created_at)
        if first is None or first > now:
            continue
        open_local = await session_open_price(o.symbol, first.astimezone(ET).date(), now)
        if open_local is None:
            out.append({"order_id": str(o.id), "symbol": o.symbol, "status": "waiting",
                        "reason": f"{kst_label(first)} 정규장의 시가를 아직 받지 못했습니다 — 다음에 다시 봅니다"})
            continue
        info = dict(await paper_trading.resolve_stock(o.symbol))
        rate = info.get("fx_rate")
        if not rate:
            out.append({"order_id": str(o.id), "symbol": o.symbol, "status": "waiting",
                        "reason": "환율을 받지 못해 체결을 미룹니다"})
            continue
        info["price"] = open_local * float(rate)
        o.triggered_at = now
        try:
            fill = await paper_trading._fill_stock_order(
                db, user_id, info, "BUY", o.quantity, source=FILL_SOURCE, filled_at=first)
        except paper_trading.PaperTradeError as exc:
            o.status = "skipped"
            out.append({"order_id": str(o.id), "symbol": o.symbol, "status": "skipped", "reason": str(exc)})
            continue
        o.status = "filled"
        o.avg_fill_price = fill["price"]
        o.filled_quantity = fill["quantity"]
        o.filled_at = first
        o.net_amount = fill["net_amount"]
        out.append({"order_id": str(o.id), "symbol": o.symbol, "status": "filled",
                    "fill_price": fill["price"], "open_local": open_local, "currency": info.get("currency"),
                    "fx_note": info.get("fx_note"), "filled_at_kst": kst_label(first)})
    return out


async def list_reservations(db: AsyncSession, user_id: uuid.UUID, *, limit: int = 20) -> list[dict]:
    rows = (await db.execute(select(Order).where(Order.user_id == user_id, Order.order_kind == KIND)
                             .order_by(Order.created_at.desc()).limit(limit))).scalars().all()
    return [{
        "order_id": str(o.id), "symbol": o.symbol, "name": o.name, "quantity": o.quantity, "status": o.status,
        "created_at_kst": kst_label(o.created_at),
        "next_open_kst": kst_label(next_open_after(o.created_at)) if o.status == "pending" else None,
        "filled_at_kst": kst_label(o.filled_at) if o.status == "filled" else None,
        "fill_price": o.avg_fill_price if o.status == "filled" else None,
        "net_amount": o.net_amount if o.status == "filled" else None,
    } for o in rows]
