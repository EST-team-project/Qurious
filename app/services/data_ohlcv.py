"""OHLCV 규격 자료 읽기 — `GET /api/data/ohlcv` (목표 기능 ① W4 · 설계서 7절 · 규격 `ohlcv-v1` 5.1.1).

이 파일이 답하는 질문: **"HF `krx-ohlcv` 와 같은 모양의 봉을, 한 종목 · 한 기간만 주소 하나로 받으려면."**

누가 쓰나 (설계서 9절 표 11)
  신장환 님(② 패턴 예측) — 일봉 · 주봉 · 분봉 / 오준영 님(③ 자산배분) — ETF · 지수 일봉 / 강민석 님(④) — 지수 일봉
  (벤치마크 대조). 파케이를 통째로 받지 않고 화면 · 노트북에서 한 종목만 볼 때 쓴다. 줄 모양이 HF 파일과 같아
  `pd.DataFrame(rows)` 로 바로 섞인다.

무엇을 주나 — 종류 × 주기 × 수정 방식
  주식  1d · 1w   adj_base(기준가 계수로 고친 값 · 기본) · raw(원 가격)
  ETF   1d · 1w   raw
  지수  1d · 1w   raw — 기호는 「시리즈:이름」(예 `KOSPI:코스피 200` · 시리즈 KOSPI · KOSDAQ · KRX · THEME)
  분봉  60m · 5m  adj_split(야후 · 분할 비율만 반영) — 분봉 유니버스 종목만 · 09:00~15:00 · 1m 은 아직 모으지 않는다

규칙은 수집기의 내보내기와 같다 — 앱 이미지에 `collector` 패키지가 들어가지 않아(collector_db 머리말) 같은 규칙을
여기 따로 두고, 시험(TC-OA)이 같은 작은 DB 로 `collector.ohlcv_export` · `collector.ohlcv.weekly` 와 줄마다 대조한다.
  · 거래가 없던 날(시가 0)은 평평한 봉 — 시가 = 고가 = 저가 = 종가
  · 수정 거래량 = 원 거래량 ÷ 계수(반올림 · 오늘 주식 수 기준)
  · 주봉 = 그 주 거래가 있던 날로 범위(+ 마지막 날 종가) · 날짜는 그 주의 마지막 거래일 · 진행 중인 주는 partial
  · 분봉의 시장 = 그 종목이 든 가장 최근 유니버스 판의 값(DF-43)

`fetched_at` — **우리가 그 원문을 받은 시각**이다. 같은 날을 두 번 받으면 정규화 줄은 마지막 것을 쓴다(2026-10-02 실측 —
  4,968 날 전부) → 원문 표의 (출처, 대상) 인덱스만 읽어 찾는다(10ms 안팎). 지문 칸은 원문(BLOB) 뒤에 있어 그 칸으로 찾으면
  2.8초였다.
  ⚠️ 시장이 그 값을 안 시각이 아니다 — 2020 ~ 2026-09 자료는 2026-09-19 뒤에 다시 받았다. 백테스트의 「언제 알 수
     있었나」 는 거래일 다음 날 낮(포털이 주는 때)으로 잡는다.

캐시를 두지 않는다 — 12:30 갱신 뒤 곧바로 새 봉이 보여야 한다(DF-17 의 교훈). 한 종목 · 한 기간 읽기는 수십 ms 다.
DB 는 읽기 전용으로만 연다 — 앱은 수집 DB 에 쓰지 않는다.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.services import collector_db

KST = timezone(timedelta(hours=9))
CONTRACT = "ohlcv-v1"

#: `collector/ohlcv.py` COLUMNS 와 같은 칸 · 같은 차례(TC-OA-01 이 대조한다)
COLUMNS = (
    "symbol", "market", "timeframe", "trade_date", "bar_start",
    "open", "high", "low", "close", "volume", "value",
    "adjusted", "price_basis", "adj_factor", "session",
    "source", "fetched_at", "contract",
)
TIMEFRAMES = ("1d", "1w", "60m", "5m")
INTRADAY = ("60m", "5m")

#: `collector/ohlcv_export.INDEX_PREFIX` 와 같다 — 지수 기호 = 접두사:이름
INDEX_PREFIX = {"KOSPI시리즈": "KOSPI", "KOSDAQ시리즈": "KOSDAQ", "KRX시리즈": "KRX", "테마지수": "THEME"}
_SERIES = {v: k for k, v in INDEX_PREFIX.items()}

#: 종류마다 받는 수정 방식 — 첫째가 기본값
BASES = {
    "stock": ("adj_base", "raw"),
    "etf": ("raw",),
    "index": ("raw",),
    "intraday": ("adj_split",),
}

DEFAULT_LIMIT = 10_000
MAX_LIMIT = 50_000
#: 기간을 안 주면 — 끝은 오늘, 처음은 이만큼 앞(주기마다 한 화면에 볼 만한 양)
DEFAULT_DAYS = {"1d": 365, "1w": 365 * 3, "60m": 30, "5m": 7}

NOTE = ("fetched_at 은 우리가 원문을 받은 시각이다 — 시장이 그 값을 안 시각이 아니다. "
        "백테스트에서는 거래일 다음 날 낮(포털이 주는 때)부터 알 수 있었다고 본다.")

_CODE = re.compile(r"^[0-9A-Z]{6}$")
_INDEX = re.compile(r"^([A-Z]+):(.+)$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class OhlcvError(Exception):
    """호출자에게 그대로 보여 줄 오류 — `status` 는 HTTP 상태(404 없음 · 422 요청 모양 · 503 DB 없음)."""

    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra

    def detail(self) -> dict:
        return {"message": self.message, **self.extra}


# ── 요청 읽기 ───────────────────────────────────────────────────────────────
def parse_symbol(raw: str) -> tuple[str, str]:
    """→ ("code", "005930") 또는 ("index", "KOSPI:코스피 200"). 뒤의 .KS · .KQ(옛 표기)는 뗀다."""
    s = (raw or "").strip()
    m = _INDEX.match(s)
    if m:
        prefix, name = m.group(1), m.group(2).strip()
        if prefix not in _SERIES and prefix != "ETC":
            raise OhlcvError(422, f"지수 시리즈를 모른다: {prefix} — {' · '.join(_SERIES)} 가운데 하나",
                             hint="예: KOSPI:코스피 200")
        return "index", f"{prefix}:{name}"
    code = re.sub(r"\.(KS|KQ)$", "", s.upper())
    if not _CODE.match(code):
        raise OhlcvError(422, f"기호 모양이 아니다: {raw!r} — 주식 · ETF 는 단축코드 6자리(005930 · 0000D0), "
                              "지수는 「시리즈:이름」(KOSPI:코스피 200)")
    return "code", code


def _day(v: str | None, name: str) -> date | None:
    if v is None or v == "":
        return None
    if not _DAY.match(v):
        raise OhlcvError(422, f"{name} 는 YYYY-MM-DD 다: {v!r}")
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise OhlcvError(422, f"{name} 는 없는 날짜다: {v!r}") from None


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _iso(bas_dt: str) -> str:
    return f"{bas_dt[:4]}-{bas_dt[4:6]}-{bas_dt[6:8]}"


def _row(**kw) -> dict:
    return {c: kw.get(c) for c in COLUMNS}


# ── DB ──────────────────────────────────────────────────────────────────────
def _connect(path: Path | None) -> sqlite3.Connection:
    path = path or collector_db.db_path()
    if path is None:
        raise OhlcvError(503, "수집 DB 가 없다 — 이 PC 에서 수집기를 돌린 적이 없거나 경로가 다르다",
                         hint="COLLECTOR_DB_PATH 또는 data/collector/market.sqlite3")
    try:
        return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as e:
        raise OhlcvError(503, f"수집 DB 를 열지 못했다: {e}") from None


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _fetched(conn: sqlite3.Connection, kind: str, days: list[str]) -> dict[str, str]:
    """{bas_dt: 그날 원문을 마지막으로 받은 시각} — 원문 표의 (출처, 대상) 인덱스만 읽는다(머리말 fetched_at)."""
    if not days or not _has_table(conn, "raw_response"):
        return {}
    rows = conn.execute(
        "SELECT target, MAX(fetched_at) FROM raw_response WHERE source='portal' AND target >= ? AND target <= ? "
        "GROUP BY target", (f"{kind}/{min(days)}", f"{kind}/{max(days)}"))
    return {t.split("/", 1)[1]: fa for t, fa in rows}


def _stock_market(conn: sqlite3.Connection, code: str) -> str | None:
    r = conn.execute("SELECT mrkt_ctg FROM price_daily WHERE srtn_cd=? ORDER BY bas_dt DESC LIMIT 1", (code,)).fetchone()
    return r[0] if r else None


def _is_etf(conn: sqlite3.Connection, code: str) -> bool:
    return _has_table(conn, "etf_daily") and \
        conn.execute("SELECT 1 FROM etf_daily WHERE srtn_cd=? LIMIT 1", (code,)).fetchone() is not None


def _universe_market(conn: sqlite3.Connection, code: str) -> str | None:
    """그 종목이 든 가장 최근 유니버스 판의 시장(DF-43 — 수집기 `universe_market` 과 같은 규칙)."""
    if not _has_table(conn, "intraday_universe"):
        return None
    r = conn.execute("SELECT market FROM intraday_universe WHERE symbol=? ORDER BY version DESC LIMIT 1",
                     (code,)).fetchone()
    return r[0] if r else None


def index_names(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[str]:
    """이름에 `query` 가 든 지수 기호(띄어쓰기는 보지 않는다 — 「코스피200」 도 「코스피 200」 을 찾는다).
    없는 지수를 물었을 때 고를 수 있게 보여 준다."""
    if not _has_table(conn, "index_daily"):
        return []
    rows = conn.execute("SELECT DISTINCT idx_csf, idx_nm FROM index_daily "
                        "WHERE REPLACE(idx_nm, ' ', '') LIKE '%' || REPLACE(?, ' ', '') || '%' "
                        "ORDER BY LENGTH(idx_nm), idx_csf, idx_nm LIMIT ?", (query, limit)).fetchall()
    return [f"{INDEX_PREFIX.get(c, 'ETC')}:{n}" for c, n in rows]


def _series_sql(prefix: str) -> tuple[str, tuple]:
    if prefix == "ETC":                                 # 접두사 표에 없는 시리즈(지금은 없다 — 수집기 내보내기와 같은 꼴)
        return "idx_csf NOT IN (?, ?, ?, ?)", tuple(INDEX_PREFIX)
    return "idx_csf = ?", (_SERIES[prefix],)


def _table_last(conn: sqlite3.Connection, table: str) -> str | None:
    """그 표의 마지막 날(YYYYMMDD) — 주봉의 「진행 중」 을 그 종목이 아니라 표 전체 기준으로 가른다(수집기 내보내기와 같다)."""
    r = conn.execute(f"SELECT MAX(bas_dt) FROM {table}").fetchone()
    return r[0] if r else None


# ── 일봉 — 수집기 `ohlcv_export.stock_daily` · `etf_daily` · `index_daily` 와 같은 규칙 ────────────────
_STOCK_SQL = """
SELECT p.bas_dt, p.mrkt_ctg, p.mkp, p.hipr, p.lopr, p.clpr, p.trqu, p.tr_prc,
       a.adj_mkp, a.adj_hipr, a.adj_lopr, a.adj_clpr, a.cum_factor
  FROM price_daily p LEFT JOIN price_adjusted a ON a.bas_dt = p.bas_dt AND a.srtn_cd = p.srtn_cd
 WHERE p.srtn_cd = ? AND p.clpr > 0 AND p.bas_dt >= ? AND p.bas_dt <= ?
 ORDER BY p.bas_dt
"""


def stock_daily(conn: sqlite3.Connection, code: str, lo: str, hi: str, basis: str) -> list[dict]:
    rows = conn.execute(_STOCK_SQL, (code, lo, hi)).fetchall()
    fmap = _fetched(conn, "price", [r[0] for r in rows])
    out = []
    for bas_dt, mkt, mkp, hipr, lopr, clpr, trqu, tr_prc, amkp, ahipr, alopr, aclpr, factor in rows:
        no_price = (mkp or 0) <= 0                      # 거래정지 등 — 평평한 봉으로
        common = dict(symbol=code, market=mkt, timeframe="1d", trade_date=_iso(bas_dt), value=tr_prc,
                      source="portal", fetched_at=fmap.get(bas_dt), contract=CONTRACT)
        if basis == "raw":
            c = float(clpr)
            out.append(_row(**common, open=c if no_price else float(mkp), high=c if no_price else float(hipr),
                            low=c if no_price else float(lopr), close=c, volume=int(trqu or 0),
                            adjusted=False, price_basis="raw", adj_factor=factor))
        else:
            f = factor if factor is not None else 1.0
            ac = aclpr if aclpr is not None else clpr * f
            out.append(_row(**common,
                            open=ac if (no_price or amkp is None) else amkp,
                            high=ac if (no_price or ahipr is None) else ahipr,
                            low=ac if (no_price or alopr is None) else alopr,
                            close=ac,
                            # 거래량도 오늘 주식 수로(collector_db 의 차트 다리와 같다) · 반올림은 짝수 쪽(파이썬 · 판다스 같음)
                            volume=int(round((trqu or 0) / f)),
                            adjusted=True, price_basis="adj_base", adj_factor=f))
    return out


def etf_daily(conn: sqlite3.Connection, code: str, lo: str, hi: str) -> list[dict]:
    rows = conn.execute("SELECT bas_dt, mkp, hipr, lopr, clpr, trqu, tr_prc FROM etf_daily "
                        "WHERE srtn_cd=? AND clpr > 0 AND bas_dt >= ? AND bas_dt <= ? ORDER BY bas_dt",
                        (code, lo, hi)).fetchall()
    fmap = _fetched(conn, "etf", [r[0] for r in rows])
    out = []
    for bas_dt, mkp, hipr, lopr, clpr, trqu, tr_prc in rows:
        no_price = (mkp or 0) <= 0
        c = float(clpr)
        out.append(_row(symbol=code, market="ETF", timeframe="1d", trade_date=_iso(bas_dt),
                        open=c if no_price else float(mkp), high=c if no_price else float(hipr),
                        low=c if no_price else float(lopr), close=c, volume=int(trqu or 0), value=tr_prc,
                        adjusted=False, price_basis="raw", source="portal", fetched_at=fmap.get(bas_dt),
                        contract=CONTRACT))
    return out


def index_daily(conn: sqlite3.Connection, symbol: str, lo: str, hi: str) -> list[dict]:
    prefix, name = symbol.split(":", 1)
    series_sql, params = _series_sql(prefix)
    rows = conn.execute(f"SELECT bas_dt, mkp, hipr, lopr, clpr, trqu, tr_prc FROM index_daily "
                        f"WHERE idx_nm = ? AND {series_sql} AND clpr > 0 AND bas_dt >= ? AND bas_dt <= ? ORDER BY bas_dt",
                        (name, *params, lo, hi)).fetchall()
    fmap = _fetched(conn, "index", [r[0] for r in rows])
    out = []
    for bas_dt, mkp, hipr, lopr, clpr, trqu, tr_prc in rows:
        no_price = (mkp or 0) <= 0
        out.append(_row(symbol=symbol, market="INDEX", timeframe="1d", trade_date=_iso(bas_dt),
                        open=clpr if no_price else mkp, high=clpr if no_price else hipr,
                        low=clpr if no_price else lopr, close=clpr, volume=int(trqu or 0), value=tr_prc,
                        adjusted=False, price_basis="raw", source="portal", fetched_at=fmap.get(bas_dt),
                        contract=CONTRACT))
    return out


def intraday(conn: sqlite3.Connection, code: str, timeframe: str, lo_iso: str, hi_iso: str,
             market: str | None) -> list[dict]:
    rows = conn.execute("SELECT bar_start, trade_date, open, high, low, close, volume, session, source, price_basis, "
                        "fetched_at FROM price_intraday WHERE symbol=? AND timeframe=? AND trade_date >= ? "
                        "AND trade_date <= ? ORDER BY bar_start", (code, timeframe, lo_iso, hi_iso)).fetchall()
    return [_row(symbol=code, market=market, timeframe=timeframe, trade_date=td, bar_start=bs, open=o, high=h,
                 low=low, close=c, volume=v, value=None, adjusted=True, price_basis=pb, adj_factor=None,
                 session=se, source=src, fetched_at=fa, contract=CONTRACT)
            for bs, td, o, h, low, c, v, se, src, pb, fa in rows]


# ── 주봉 — 수집기 `ohlcv.weekly` 와 같은 규칙(TC-OA 가 대조) ─────────────────────────────────────────────
def weekly(daily: list[dict], as_of: str | None) -> tuple[list[dict], bool]:
    """일봉(같은 종목 · 같은 수정 방식 · 날짜 차례) → 주봉 · 마지막 주가 진행 중인가.

    시가 = 거래가 있던(거래량 > 0) 첫날의 시가 · 고가 · 저가 = 거래가 있던 날의 최고 · 최저를 **마지막 날 종가까지** 넓힌다
    (거래가 없던 마지막 날의 종가는 거래소가 정한 기준가라 범위 밖일 수 있다) · 종가 = 마지막 날 종가 · 거래량 · 거래대금 = 합
    · 나머지 칸 = 마지막 날의 값 · 날짜 = 그 주 마지막 거래일. `as_of` 가 그 주 안이고 금요일 전이면 진행 중(partial).
    """
    groups: dict[tuple, list[dict]] = {}
    for r in daily:
        y, w, _ = date.fromisoformat(r["trade_date"]).isocalendar()
        groups.setdefault((y, w), []).append(r)
    out = []
    for key in sorted(groups):
        g = groups[key]
        last = g[-1]
        traded = [r for r in g if (r["volume"] or 0) > 0]
        close = float(last["close"])
        hi = max((float(r["high"]) for r in traded), default=close)
        lo = min((float(r["low"]) for r in traded), default=close)
        vals = [r["value"] for r in g if r["value"] is not None]
        out.append({**last, "timeframe": "1w",
                    "open": traded[0]["open"] if traded else last["close"],
                    "high": max(hi, close), "low": min(lo, close),
                    "volume": sum(int(r["volume"] or 0) for r in g),
                    "value": sum(vals) if vals else None})
    partial = False
    if out and as_of:
        a = date.fromisoformat(as_of)
        y, w, _ = a.isocalendar()
        last_key = sorted(groups)[-1]
        partial = last_key == (y, w) and a.weekday() < 4      # 금요일 전이면 아직 진행 중일 수 있다
    return out, partial


# ── 모으기 ──────────────────────────────────────────────────────────────────
def read_ohlcv(symbol: str, timeframe: str = "1d", start: str | None = None, end: str | None = None,
               basis: str | None = None, limit: int = DEFAULT_LIMIT, *, today: date | None = None,
               path: Path | None = None) -> dict:
    """한 종목 · 한 주기 · 한 기간의 `ohlcv-v1` 줄. 고칠 수 있는 잘못은 `OhlcvError`(상태 · 할 일)로 알린다."""
    if timeframe == "1m":
        raise OhlcvError(422, "1분봉은 아직 모으지 않는다 — 60m · 5m 를 쓴다(설계서 표 7 · 💬 ①)")
    if timeframe not in TIMEFRAMES:
        raise OhlcvError(422, f"주기를 모른다: {timeframe!r} — {' · '.join(TIMEFRAMES)}")
    if not 1 <= limit <= MAX_LIMIT:
        raise OhlcvError(422, f"limit 은 1 ~ {MAX_LIMIT:,} 이다")
    kind_in, sym = parse_symbol(symbol)
    today = today or datetime.now(KST).date()
    hi_day = _day(end, "to") or today
    lo_day = _day(start, "from") or hi_day - timedelta(days=DEFAULT_DAYS[timeframe])
    if lo_day > hi_day:
        raise OhlcvError(422, f"from({lo_day}) 이 to({hi_day}) 보다 뒤다")

    conn = _connect(path)
    try:
        # 종류 정하기 — 지수는 기호 모양으로, 단축코드는 주식 표 → ETF 표 차례로(둘이 겹치는 코드는 없다 · 2026-10-02 실측)
        if timeframe in INTRADAY:
            if kind_in == "index":
                raise OhlcvError(422, "지수 분봉은 모으지 않는다 — 지수는 1d · 1w")
            kind = "intraday"
            if not _has_table(conn, "price_intraday") or conn.execute(
                    "SELECT 1 FROM price_intraday WHERE symbol=? AND timeframe=? LIMIT 1", (sym, timeframe)).fetchone() is None:
                raise OhlcvError(404, f"{sym} 의 {timeframe} 분봉이 없다 — 분봉은 유니버스 종목만 모은다",
                                 hint="유니버스 명단은 HF krx-ohlcv 의 meta/universe.csv")
            market = _universe_market(conn, sym) or _stock_market(conn, sym) or ("ETF" if _is_etf(conn, sym) else None)
        elif kind_in == "index":
            kind, market = "index", "INDEX"
            prefix, name = sym.split(":", 1)
            series_sql, params = _series_sql(prefix)
            if not _has_table(conn, "index_daily") or conn.execute(
                    f"SELECT 1 FROM index_daily WHERE idx_nm = ? AND {series_sql} LIMIT 1", (name, *params)).fetchone() is None:
                raise OhlcvError(404, f"지수 {sym} 가 없다 — 같은 이름도 시리즈마다 따로 있다(KOSPI · KOSDAQ 의 「IT 서비스」)",
                                 candidates=index_names(conn, name))
        else:
            market = _stock_market(conn, sym)
            if market:
                kind = "stock"
            elif _is_etf(conn, sym):
                kind, market = "etf", "ETF"
            else:
                raise OhlcvError(404, f"수집 DB 에 {sym} 이 없다 — 주식 · ETF 단축코드를 확인한다")

        allowed = BASES[kind]
        basis = basis or allowed[0]
        if basis not in allowed:
            raise OhlcvError(422, f"{market} {timeframe} 의 수정 방식은 {' · '.join(allowed)} 만 있다 — {basis!r} 는 없다",
                             allowed=list(allowed))

        # 주봉은 첫 주를 온전히 만들려고 그 주 월요일부터 일봉을 읽는다 — 끝은 `to` 에서 자른다(뒤 날은 보지 않는다)
        q_lo = lo_day - timedelta(days=lo_day.weekday()) if timeframe == "1w" else lo_day
        table_last = None
        if kind == "intraday":
            rows = intraday(conn, sym, timeframe, q_lo.isoformat(), hi_day.isoformat(), market)
        elif kind == "index":
            rows = index_daily(conn, sym, _ymd(q_lo), _ymd(hi_day))
            table_last = _table_last(conn, "index_daily")
        elif kind == "etf":
            rows = etf_daily(conn, sym, _ymd(q_lo), _ymd(hi_day))
            table_last = _table_last(conn, "etf_daily")
        else:
            rows = stock_daily(conn, sym, _ymd(q_lo), _ymd(hi_day), basis)
            table_last = _table_last(conn, "price_daily")
    except sqlite3.Error as e:
        raise OhlcvError(503, f"수집 DB 를 읽지 못했다: {e}") from None
    finally:
        conn.close()

    partial = False
    if timeframe == "1w":
        # 「진행 중인 주」 의 기준일 = 표 전체의 마지막 날과 `to` 가운데 이른 쪽 — 그 종목의 마지막 날이 아니다
        # (상장폐지 종목의 마지막 주가 진행 중으로 읽히지 않게 · 수집기 내보내기는 표 전체 기준일을 쓴다)
        as_of = min(_iso(table_last), hi_day.isoformat()) if table_last else hi_day.isoformat()
        rows, partial = weekly(rows, as_of)
        rows = [r for r in rows if r["trade_date"] >= lo_day.isoformat()]
    if len(rows) > limit:
        raise OhlcvError(422, f"줄이 {len(rows):,}개라 limit({limit:,})을 넘는다 — 기간을 줄이거나 limit 을 늘린다"
                              f"(최대 {MAX_LIMIT:,})", rows=len(rows))
    out = {
        "contract": CONTRACT,
        "symbol": sym, "market": market, "timeframe": timeframe, "basis": basis,
        "from": lo_day.isoformat(), "to": hi_day.isoformat(),
        "count": len(rows),
        "as_of": rows[-1]["trade_date"] if rows else None,
        "partial": partial,
        "columns": list(COLUMNS),
        "rows": rows,
        "source": "collector",
        "note": NOTE,
    }
    # 분봉의 마지막 날을 장이 끝나기 전에 받았으면 그날은 덜 찼다(12:30 갱신은 장 중이다) — 다음 갱신이 최근 5일을
    # 다시 받아 채운다. 학습 · 패턴 통계에 덜 찬 날이 섞이지 않게 날짜를 알린다.
    if kind == "intraday" and rows:
        day = rows[-1]["trade_date"]
        got = max((r["fetched_at"] or "") for r in rows if r["trade_date"] == day)
        if got < f"{day}T15:30:00+09:00":
            out["incomplete_day"] = day
            out["incomplete_note"] = f"{day} 봉은 {got[11:16] or '?'} 에 받아 장 마감(15:30)까지 다 있지 않다 — 다음 갱신이 다시 받는다"
    return out
