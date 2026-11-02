"""국내 ETF 식별·거래 시간 주의. 일별 종가/NAV를 장중 iNAV로 쓰지 않는다.

근거: KRX ETF 매매절차 및 LP 제도 안내. 2026-11-02 확인.
https://regulation.krx.co.kr/contents/RGL/03/03060101/RGL03060101.jsp
https://regulation.krx.co.kr/contents/RGL/03/03060103/RGL03060103.jsp
"""
import math
import re
import sqlite3
from contextlib import closing
from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.services import collector_db

KST = ZoneInfo("Asia/Seoul")


def describe(symbol, *, now=None):
    result = {"is_etf": False, "classification": "unverified", "warnings": []}
    code = str(symbol).split('.')[0]
    path = collector_db.db_path()
    if not re.fullmatch(r"[0-9A-Z]{6}", code) or path is None:
        return result
    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=2)) as db:
            row = db.execute("SELECT bas_dt,clpr,nav FROM etf_daily WHERE srtn_cd=? ORDER BY bas_dt DESC LIMIT 1", (code,)).fetchone()
    except (sqlite3.Error, OSError):
        return result
    if row is None:
        return result
    day, close, nav = row
    day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    result.update(is_etf=True, classification="collector_etf", as_of=day)
    current = (now or datetime.now(KST)).astimezone(KST).time()
    if time(9) <= current < time(9, 5) or time(15, 20) <= current < time(15, 30):
        result["warnings"].append("ETF LP 호가 의무 면제 구간입니다. 시장가·다음 시가 체결은 순자산가치와 차이가 커질 수 있습니다.")
    if all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (close, nav)):
        result.update(close_nav_premium_pct=round((close / nav - 1) * 100, 4), premium_as_of=day)
    return result
