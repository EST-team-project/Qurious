"""리밸런싱용 원주가. 차트의 거래정지 봉 보정이나 외부 현재가 대체를 쓰지 않는다."""
from __future__ import annotations

from contextlib import closing
import math
import re
import sqlite3
from datetime import date, timedelta

from app.services import collector_db, rebalance_schedule as schedule


class PriceUnavailable(ValueError):
    pass


class OpenNotTradable(PriceUnavailable):
    """완료된 거래일에 체결할 원시 시가가 없다는 근거가 확인됨."""


def collection_complete(conn, code, day):
    # 기존 종목은 실제 저장 표로 출처를 확인한다. 미상 종목은 양쪽 완료가 필요하다.
    sources = [source for table, source in [('price_daily', 'portal'), ('etf_daily', 'portal_etf')]
               if conn.execute(f'SELECT 1 FROM {table} WHERE srtn_cd=? LIMIT 1', (code,)).fetchone()]
    sources = sources or ['portal', 'portal_etf']
    return all(conn.execute("SELECT 1 FROM ingest_day WHERE source=? AND bas_dt=? AND status='done'",
                            (source, day.strftime('%Y%m%d'))).fetchone() for source in sources)


def next_trading_day(after: date) -> date:
    # Stop at the first verified day; do not require next year's entire calendar.
    for offset in range(1, 32):
        day = after + timedelta(days=offset)
        try:
            if schedule.days(day, day)[0]['is_trading_day']:
                return day
        except (schedule.market_calendar.CalendarUnavailable, sqlite3.Error) as exc:
            raise PriceUnavailable('다음 거래일 달력 확인 대기') from exc
    raise PriceUnavailable('다음 거래일을 찾지 못했습니다.')


def read_prices(symbols, day: date, field: str = 'close') -> dict:
    """지정한 날짜 전체 종목을 한 SQLite 읽기 트랜잭션으로 확인한다."""
    if field not in ('close', 'open'):
        raise ValueError('지원하지 않는 가격 기준')
    path = collector_db.db_path()
    if path is None:
        raise PriceUnavailable('수집 DB가 없어 가격 확인을 기다립니다.')
    result = {}
    try:
        with closing(sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True, timeout=5)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('BEGIN')
            for symbol in sorted(set(symbols)):
                match = re.fullmatch(r'([0-9A-Z]{6})(?:\.(?:KS|KQ|KN))?', symbol)
                if not match:
                    raise PriceUnavailable(f'{symbol}: 수집 DB 국내 주식·ETF 가격만 지원합니다.')
                code = match.group(1)
                row = conn.execute('SELECT *, 0 AS is_etf FROM price_daily WHERE srtn_cd=? AND bas_dt=?',
                                   (code, day.strftime('%Y%m%d'))).fetchone()
                if row is None:
                    row = conn.execute("SELECT *, 1 AS is_etf, 'KOSPI' AS mrkt_ctg FROM etf_daily WHERE srtn_cd=? AND bas_dt=?",
                                       (code, day.strftime('%Y%m%d'))).fetchone()
                if row is None:
                    if field == 'open' and collection_complete(conn, code, day):
                        raise OpenNotTradable(f'{symbol}: {day} 수집 완료 후 가격 행 없음 — 미체결')
                    raise PriceUnavailable(f'{symbol}: {day} 가격 수집 대기')
                if field == 'open' and (row['halted'] or row['trqu'] == 0):
                    if collection_complete(conn, code, day):
                        raise OpenNotTradable(f'{symbol}: {day} 거래정지·무거래 확인 — 미체결')
                    raise PriceUnavailable(f'{symbol}: {day} 거래정지·무거래 수집 확정 대기')
                price = row['clpr' if field == 'close' else 'mkp']
                if price is None or not math.isfinite(float(price)) or price <= 0:
                    raise PriceUnavailable(f'{symbol}: {day} 유효한 {field} 가격이 없습니다.')
                if field == 'open' and (row['halted'] or not row['trqu'] or row['trqu'] <= 0):
                    raise PriceUnavailable(f'{symbol}: {day} 거래정지·무거래로 시가 체결 대기')
                result[symbol] = dict(symbol=symbol, name=row['itms_nm'] or symbol, price=float(price),
                                      market=row['mrkt_ctg'], is_etf=bool(row['is_etf']),
                                      price_date=day.isoformat(), price_basis=f'raw_{field}')
    except (sqlite3.Error, OSError) as exc:
        raise PriceUnavailable('수집 DB 가격을 읽을 수 없어 대기합니다.') from exc
    return result
