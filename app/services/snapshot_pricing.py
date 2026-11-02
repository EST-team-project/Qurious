"""일일 평가 가격의 출처와 시각. 조회 시각을 시세 시각으로 대신하지 않는다."""
import math
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.services import market_calendar

KST = ZoneInfo("Asia/Seoul")


def positive(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def instant(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else None
    except (ValueError, TypeError):
        return None


def stock_quote_time(value, source):
    # stock.get_quote의 delayed 시각은 공급자의 regularMarketTime을 KST 분으로
    # 표시한 값이다. 이 경로의 알려진 시간대만 복원하고 수신 시각은 쓰지 않는다.
    if source == "delayed" and isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=KST).isoformat()
        except ValueError:
            pass
    return value


def evidence(kind, symbol, price, source, as_of, *, fallback=None, now=None):
    now = now or datetime.now(KST)
    stamp = instant(as_of)
    reasons = list(fallback or [])
    if not positive(price):
        reasons.append("invalid_price")
    if not source or source in ("unknown", "교육용 기준 시세"):
        reasons.append("unverified_source")
    if kind == "crypto":
        if stamp is None or not 0 <= (now - stamp).total_seconds() <= 300:
            reasons.append("quote_older_than_5m_or_missing")
    elif not as_of:
        reasons.append("missing_quote_time")
    return {"asset": kind, "symbol": symbol, "price": price, "source": source or "unknown",
            "as_of": as_of, "fetched_at": now.isoformat(), "fallback": reasons, "complete": not reasons}


def daily_complete(item, day, *, at=None):
    if not item.get("complete") or item.get("fallback"):
        return False
    stamp = instant(item.get("as_of"))
    if item["asset"] == "crypto":
        return (stamp is not None and stamp.astimezone(KST).date() == day
                and (at is None or 0 <= (at - stamp).total_seconds() <= 300))
    if item["asset"] == "stock":
        if item.get("source") == "collector_close":
            return item.get("as_of") == day.isoformat()
        return (item.get("source") == "delayed" and stamp is not None and stamp.astimezone(KST).date() == day
                and stamp.astimezone(KST).time() == time(15, 30)
                and (at is None or stamp <= at))
    return str(item.get("as_of", ""))[:10] == day.isoformat()


def consecutive(previous, current):
    if current <= previous:
        return False
    if current == previous + timedelta(days=1):
        return True
    try:
        cal = market_calendar.trading_days(previous, current)
        days = cal.get("days", [])
        return (not cal.get("partial") and len(days) == (current - previous).days + 1
                and [d["date"] for d in days if d["is_trading_day"]]
                == [previous.isoformat(), current.isoformat()])
    except Exception:
        return False
