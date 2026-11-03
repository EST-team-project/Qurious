"""자산군 대용 ETF 일봉을 수집 DB에서 읽는다. 외부 조회는 호출자가 결정한다."""
from datetime import datetime, timedelta, timezone
from contextlib import closing
from pathlib import Path
import sqlite3

from app.services import collector_db
from app.services.allocation_models import ASSET_PROXIES


def read_proxy_candles(symbol: str, *, path: Path | None = None, today=None) -> dict | None:
    if symbol not in {p["symbol"] for p in ASSET_PROXIES.values()}:
        raise ValueError("지원하지 않는 자산군 대용 종목입니다.")
    path = path or collector_db.db_path()
    if path is None:
        return None
    today = today or datetime.now(collector_db.KST).date()
    since = (today - timedelta(days=3 * 366)).strftime("%Y%m%d")
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
            rows = db.execute("SELECT bas_dt,clpr,mkp,hipr,lopr,trqu FROM etf_daily "
                              "WHERE srtn_cd=? AND bas_dt>=? AND bas_dt<=? ORDER BY bas_dt",
                              (symbol.split(".")[0], since, today.strftime("%Y%m%d"))).fetchall()
    except sqlite3.Error:
        return None
    if not rows:
        return None
    return {"symbol": symbol, "source": "collector_etf", "candles": [
        {"time": int(datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()),
         "close": close, "open": op, "high": high, "low": low, "volume": volume}
        for day, close, op, high, low, volume in rows]}
