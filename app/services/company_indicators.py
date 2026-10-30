"""기업 지표 — 우리 전자공시 · 공공데이터 종가로 읽는 한 종목의 PER · PBR · ROE · EPS · 영업이익률 · 배당 (할 일 ①-16 · 2026-10-30).

`GET /api/indicators/company` 가 부른다. 수집 DB 를 **읽기만** 한다.
  price_daily             공공데이터포털 주식시세정보 — 종가 · 시가총액(보통주만) · 상장주식수
  financial_statement_full 전자공시 전체 재무제표 — 지배기업 소유주 몫 순이익 · 자본 · 보고된 기본주당이익
  financial_statement     전자공시 주요계정 — 매출액 · 영업이익(영업이익률)
  dividend                배당 결정 공시 — 주당배당금 · 기준일

옛 화면(지표 대시보드)은 야후 파이낸스 재무 요약을 그대로 보여, 같은 삼성전자가 EPS · BPS · PBR · 영업이익은 N/A 이고 PER 3.11 ·
ROE 30.79 처럼 우리 전자공시 값(PER 35.1 · ROE 10.4)과 크게 다른 숫자를 냈다. 이 서비스는 숫자마다 식 · 기준 기간 · 공시 접수일 ·
종가 날짜를 함께 돌려주고(`company_health` 와 같은 모양), 화면은 응답을 그대로 그린다.

규칙 — 판 고르기는 `data_financials.choose_version` 한 곳(시점 고정 · 정정본)
  - PER = 종가 ÷ **보고된 기본주당이익**. 시가총액 ÷ 순이익으로 내지 않는다 — 시가총액은 보통주만인데 순이익에는 우선주 몫이 들어 있어
    삼성전자는 30.6 으로 어긋난다(보고 EPS 로는 35.1). 보고된 EPS 가 없으면 줄표 + 까닭. 적자면 「적자라 계산하지 않음」.
  - PBR = 시가총액 ÷ 지배지분 자본. 같은 이유로 우선주가 상장된 회사는 `approx: true`(낮게 나올 수 있음). 자본잠식이면 줄표.
  - ROE = 지배주주 순이익 ÷ 지배지분 자본(연말 자본 · 평균 아님). 연결 재무에 지배 몫 계정이 없고 비지배지분 계정도 없으면 당기순이익 ·
    자본총계를 그대로 쓴다(그 사실을 글로). 둘 다 아니면 줄표 — 총액과 지배 몫을 섞지 않는다.
  - 영업이익률 = 영업이익 ÷ 매출액(주요계정). 금융회사처럼 항목이 달라 없으면 줄표 + 까닭.
  - 배당 = 종가 날짜 앞 12개월 안 기준일의 현금배당 주당배당금 합 · 배당수익률 = 그 합 ÷ 종가. 배당 결정 공시를 센 값이라 실제 지급과 다를 수 있다.
  - 재무는 가장 최근 **사업보고서**(연 1회)의 값만 쓴다 — 분기 값을 이어 붙여 만드는 12개월 값(TTM)은 쓰지 않는다.
  - 연결(CFS)을 먼저 보고 없으면 별도(OFS)로 바꾸며 그 사실을 `fs_note` 에 적는다.

문장 규칙(S108 · S109 와 같다) — 투자 권유 낱말을 쓰지 않는다 · 좋은 쪽만 말하지 않고 한계를 한 줄 · 서버 한 곳에서 문장을 짓는다.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from app.services import collector_db
from app.services import data_financials as F

MARKET = "KR"
ANNUAL = "11011"
SOURCE = "전자공시(DART) 전체 재무제표 · 주요계정 · 공공데이터포털 주식시세정보"
NOTICE = "투자 권유가 아닙니다. 과거 공시와 종가로 계산한 값이며 업종마다 기준이 다릅니다."

ACC_NI = "ifrs-full_ProfitLossAttributableToOwnersOfParent"
ACC_EQ = "ifrs-full_EquityAttributableToOwnersOfParent"
ACC_NI_TOTAL = "ifrs-full_ProfitLoss"
ACC_EQ_TOTAL = "ifrs-full_Equity"
ACC_NCI = ("ifrs-full_NoncontrollingInterests", "ifrs-full_ProfitLossAttributableToNoncontrollingInterests")
ACC_EPS = ("ifrs-full_BasicEarningsLossPerShare", "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations")
_SYMBOL = re.compile(r"^\d{6}$|^[0-9A-Z]{6}$")


class IndicatorsError(Exception):
    def __init__(self, status: int, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.status, self.code, self.message, self.hint = status, code, message, hint

    def detail(self, admin: bool = False) -> dict:
        d = {"code": self.code, "message": self.message}
        if self.hint and admin:
            d["hint"] = self.hint
        return d


def _iso(yyyymmdd: Optional[str]) -> Optional[str]:
    s = str(yyyymmdd or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else None


def _won(n: float) -> str:
    """원 → 「44.26조 원」 · 「3,389억 원」 — 값을 바꾸지 않고 단위 글만."""
    a = abs(n)
    if a >= 1e12:
        return f"{n / 1e12:.2f}조 원"
    if a >= 1e8:
        return f"{round(n / 1e8):,}억 원"
    return f"{round(n):,}원"


def _metric(key: str, label: str, value, unit: str, sentence: str, formula: str, basis: str, *,
            reason: str = "", approx: bool = False) -> dict:
    m = {"key": key, "label": label, "value": value, "unit": unit, "sentence": sentence, "formula": formula, "basis": basis}
    if value is None and reason:
        m["reason"] = reason
    if approx:
        m["approx"] = True
    return m


def _row_value(conn: sqlite3.Connection, code: str, year: str, rcept: str, fs: str, ids: Tuple[str, ...]) -> Optional[float]:
    for acc in ids:
        r = conn.execute(
            "SELECT thstrm_amount FROM financial_statement_full WHERE stock_code=? AND bsns_year=? AND reprt_code=? "
            "AND fs_div=? AND rcept_no=? AND account_id=? AND thstrm_amount IS NOT NULL ORDER BY sj_div, ord LIMIT 1",
            (code, year, ANNUAL, fs, rcept, acc)).fetchone()
        if r is not None:
            return r[0]
    return None


def _has_any(conn: sqlite3.Connection, code: str, year: str, rcept: str, fs: str, ids: Tuple[str, ...]) -> bool:
    q = ",".join("?" * len(ids))
    return conn.execute(
        f"SELECT 1 FROM financial_statement_full WHERE stock_code=? AND bsns_year=? AND reprt_code=? AND fs_div=? "
        f"AND rcept_no=? AND account_id IN ({q}) LIMIT 1", (code, year, ANNUAL, fs, rcept, *ids)).fetchone() is not None


def _pick_report(conn: sqlite3.Connection, code: str, as_of: Optional[str], pit: str) -> Tuple[Optional[dict], str, str]:
    """가장 최근 사업보고서의 고른 판 · 쓴 재무(CFS · OFS) · 연결이 없어 별도로 바꿨다는 글. 없으면 (None, "", "")."""
    for fs in ("CFS", "OFS"):
        vers = [dict(zip(("bsns_year", "rcept_no", "known_at", "first_known_at"), r)) for r in conn.execute(
            "SELECT DISTINCT bsns_year, rcept_no, known_at, first_known_at FROM financial_statement_full "
            "WHERE stock_code=? AND reprt_code=? AND fs_div=?", (code, ANNUAL, fs))]
        by_year: Dict[str, List[dict]] = {}
        for v in vers:
            by_year.setdefault(v["bsns_year"], []).append(v)
        for year in sorted(by_year, reverse=True):
            chosen, _ = F.choose_version(by_year[year], as_of, pit)
            if chosen is not None:
                note = "" if fs == "CFS" else "연결재무제표가 없어 별도재무제표로 계산했습니다."
                return chosen, fs, note
    return None, "", ""


def _owner_values(conn: sqlite3.Connection, code: str, year: str, rcept: str, fs: str) -> Tuple[Optional[float], Optional[float], Optional[float], str]:
    """(지배주주 순이익, 지배지분 자본, 보고된 기본주당이익, 총액을 그대로 썼다는 글) — 한 판 안에서 총액과 지배 몫을 섞지 않는다."""
    ni = eq = None
    note = ""
    if fs == "CFS":
        ni = _row_value(conn, code, year, rcept, fs, (ACC_NI,))
        eq = _row_value(conn, code, year, rcept, fs, (ACC_EQ,))
        if (ni is None or eq is None) and not _has_any(conn, code, year, rcept, fs, ACC_NCI):
            ni_t = _row_value(conn, code, year, rcept, fs, (ACC_NI_TOTAL,))
            eq_t = _row_value(conn, code, year, rcept, fs, (ACC_EQ_TOTAL,))
            if ni is None and ni_t is not None:
                ni, note = ni_t, "비지배지분이 없는 회사라 당기순이익 · 자본총계를 그대로 썼습니다."
            if eq is None and eq_t is not None:
                eq, note = eq_t, "비지배지분이 없는 회사라 당기순이익 · 자본총계를 그대로 썼습니다."
    else:
        ni = _row_value(conn, code, year, rcept, fs, (ACC_NI_TOTAL,))
        eq = _row_value(conn, code, year, rcept, fs, (ACC_EQ_TOTAL,))
    return ni, eq, _row_value(conn, code, year, rcept, fs, ACC_EPS), note


def _price(conn: sqlite3.Connection, code: str, as_of: Optional[str]) -> Optional[tuple]:
    cut = (as_of or "9999-12-31").replace("-", "")
    return conn.execute(
        "SELECT bas_dt, clpr, lstg_st_cnt, mrkt_tot_amt, itms_nm FROM price_daily WHERE srtn_cd=? AND bas_dt<=? "
        "ORDER BY bas_dt DESC LIMIT 1", (code, cut)).fetchone()


def _has_preferred(conn: sqlite3.Connection, code: str, name: str, bas_dt: str) -> bool:
    if not name:
        return False
    esc = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return conn.execute(
        "SELECT 1 FROM price_daily WHERE bas_dt=? AND srtn_cd<>? AND itms_nm LIKE ? ESCAPE '\\' LIMIT 1",
        (bas_dt, code, esc + "우%")).fetchone() is not None


def _dividend_12m(conn: sqlite3.Connection, code: str, bas_dt: str) -> Optional[float]:
    d = date(int(bas_dt[:4]), int(bas_dt[4:6]), int(bas_dt[6:8]))
    lo = (d - timedelta(days=365)).strftime("%Y%m%d")
    try:
        rows = conn.execute(
            "SELECT record_dt, MAX(dps) FROM dividend WHERE srtn_cd=? AND record_dt>? AND record_dt<=? AND dps>0 "
            "AND div_type='현금배당' AND COALESCE(needs_review,0)=0 GROUP BY record_dt", (code, lo, bas_dt)).fetchall()
    except sqlite3.OperationalError:
        return None
    return float(sum(r[1] for r in rows)) if rows else 0.0


def read_universe() -> dict:
    """지표를 볼 수 있는 종목 — 수집 대상(전자공시 기업개황에 든 상장사). 지표 비교의 「종목 추가」 가 이 안에서만 고른다."""
    path = collector_db.db_path()
    if path is None:
        raise IndicatorsError(503, "no_db", "기업 지표 자료를 아직 받지 못했습니다.", "수집 DB 가 없다 — 수집기를 먼저 돌린다")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        rows = conn.execute(
            "SELECT d.stock_code, d.stock_name FROM dart_company d WHERE d.stock_code <> '' AND d.last_seen_at = "
            "(SELECT MAX(x.last_seen_at) FROM dart_company x WHERE x.corp_code = d.corp_code) ORDER BY d.stock_name").fetchall()
    finally:
        conn.close()
    return {"count": len(rows), "companies": [{"code": c, "name": n or ""} for c, n in rows], "source": SOURCE,
            "note": "수집 대상(분봉 유니버스) 상장사입니다 — 이 밖의 종목은 지표를 계산하지 않습니다."}


_SECTOR_TTL = 300.0           # 업종 묶음은 351곳을 훑어 계산하므로 5분 저장(수집은 하루 한 번이라 값이 바뀌지 않는다)
_SECTOR_CACHE: Dict[str, object] = {"at": 0.0, "key": None, "val": None}
SECTOR_THIN = 3               # 이보다 적은 종목의 업종은 「적은 종목」 표시(산업 화면과 같다)
SECTOR_TOP = 3


def read_sector_valuation() -> dict:
    """업종(통계청 한국표준산업분류 중분류)별 PER · PBR 중앙값 — 수집 대상 상장사 전부를 같은 규칙으로 계산해 묶는다(할 일 ①-16 · 결정 ③ 안 C).

    종목마다 `read_indicators` 와 같은 값(종가 ÷ 보고 EPS · 시가총액 ÷ 지배지분 자본)을 쓴다. PER 은 보고 EPS 가 흑자인 종목만, PBR 은 자본이 있는 종목만 센다 —
    그래서 업종마다 「몇 곳으로 낸 중앙값인가」 를 함께 싣는다. 업종 전체 지수가 아니다(수집 대상 몇 곳만의 값).
    """
    import time
    from statistics import median
    from app.services import macro_industry as MI
    path = collector_db.db_path()
    if path is None:
        raise IndicatorsError(503, "no_db", "업종별 자료를 아직 받지 못했습니다.", "수집 DB 가 없다 — 수집기를 먼저 돌린다")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        as_of = conn.execute("SELECT MAX(bas_dt) FROM price_daily").fetchone()[0]
        now = time.monotonic()
        if _SECTOR_CACHE["val"] is not None and _SECTOR_CACHE["key"] == (str(path), as_of) and now - float(_SECTOR_CACHE["at"]) < _SECTOR_TTL:
            return _SECTOR_CACHE["val"]  # type: ignore[return-value]
        companies = conn.execute(
            "SELECT d.stock_code, d.stock_name, d.induty_code FROM dart_company d WHERE d.stock_code <> '' AND d.last_seen_at = "
            "(SELECT MAX(x.last_seen_at) FROM dart_company x WHERE x.corp_code = d.corp_code)").fetchall()
        names = {c: (n, p) for c, n, p in conn.execute(
            "SELECT code, name, parent_code FROM ksic_code WHERE level = '중분류' AND revision = ?", (MI.KSIC_REVISION,))}
        sections = dict(conn.execute("SELECT code, name FROM ksic_code WHERE level = '대분류' AND revision = ?", (MI.KSIC_REVISION,)).fetchall())
        buckets: Dict[str, list] = {}
        for code, name, induty in companies:
            prefix = (induty or "")[:2]
            px = _price(conn, code, None)
            picked, fs, _ = _pick_report(conn, code, None, "strict")
            per = pbr = None
            if px is not None and picked is not None:
                _ni, eq, eps, _note = _owner_values(conn, code, picked["bsns_year"], picked["rcept_no"], fs)
                if eps is not None and eps > 0 and px[1]:
                    per = px[1] / eps
                if eq is not None and eq > 0 and px[3]:
                    pbr = px[3] / eq
            buckets.setdefault(prefix if prefix in names else "", []).append((code, name, per, pbr, px[3] if px else None))
    finally:
        conn.close()
    groups = []
    for prefix, rows in buckets.items():
        pers, pbrs = [r[2] for r in rows if r[2] is not None], [r[3] for r in rows if r[3] is not None]
        top = sorted((r for r in rows if r[4] is not None), key=lambda r: r[4], reverse=True)[:SECTOR_TOP]
        if prefix:
            nm, parent = names[prefix]
            section = {"code": parent, "name": sections.get(parent, "")}
        else:
            nm, section = "분류 못 찾음", {"code": "", "name": ""}
        groups.append({"code": prefix, "name": nm, "section": section, "n": len(rows), "thin": len(rows) < SECTOR_THIN,
                       "per": {"median": round(median(pers), 1) if pers else None, "n": len(pers)},
                       "pbr": {"median": round(median(pbrs), 2) if pbrs else None, "n": len(pbrs)},
                       "top": [{"code": r[0], "name": r[1]} for r in top]})
    groups.sort(key=lambda g: (-g["n"], g["code"]))
    universe = len(companies)
    out = {"available": True, "as_of": _iso(as_of), "universe": universe, "source": SOURCE, "groups": groups,
           "formula": {"per": "종목별 종가 ÷ 보고된 기본주당이익의 중앙값(흑자 종목만)", "pbr": "종목별 시가총액 ÷ 지배지분 자본의 중앙값(자본이 있는 종목만)"},
           "notice": (f"수집 대상 {universe}곳만의 업종별 중앙값입니다 — 업종 전체 지수가 아니고, 종목이 적은 업종은 한두 종목이 값을 좌우합니다. "
                      "재무는 가장 최근 사업보고서 기준이며 투자 권유가 아닙니다.")}
    _SECTOR_CACHE.update({"at": time.monotonic(), "key": (str(path), as_of), "val": out})
    return out


def read_indicators(symbol: str, as_of: Optional[str] = None, pit: str = "strict") -> dict:
    symbol = (symbol or "").strip().upper()
    if not _SYMBOL.match(symbol):
        raise IndicatorsError(422, "bad_symbol", f"symbol 은 단축코드 6자리입니다: {symbol!r}")
    if pit not in F.PIT_MODES:
        raise IndicatorsError(422, "bad_pit", f"pit 는 {' · '.join(F.PIT_MODES)} 가운데 하나입니다: {pit!r}")
    if as_of is not None:
        try:
            date.fromisoformat(as_of)
        except ValueError:
            raise IndicatorsError(422, "bad_date", f"as_of 는 YYYY-MM-DD 꼴이어야 합니다: {as_of!r}") from None
    path = collector_db.db_path()
    if path is None:
        raise IndicatorsError(503, "no_db", "기업 지표 자료를 아직 받지 못했습니다.", "수집 DB 가 없다 — 수집기를 먼저 돌린다")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        px = _price(conn, symbol, as_of)
        picked, fs, fs_note = _pick_report(conn, symbol, as_of, pit)
        if px is None and picked is None:
            raise IndicatorsError(404, "no_data", f"{symbol} 의 종가 · 재무 자료가 없습니다.",
                                  "상장사가 아니거나(ETF · 스팩 일부) 수집 대상(분봉 유니버스)이 아니다")
        name = ""
        r = conn.execute("SELECT stock_name FROM dart_company WHERE stock_code=? LIMIT 1", (symbol,)).fetchone()
        if r:
            name = r[0] or ""
        bas_dt, close, shares, mcap, px_name = (px if px else (None, None, None, None, ""))
        out: dict = {"symbol": symbol, "name": name or px_name or "", "market": MARKET, "source": SOURCE, "notice": NOTICE,
                     "as_of": as_of, "pit": pit}
        out["price"] = ({"close": close, "trade_date": _iso(bas_dt), "market_cap": mcap,
                         "note": f"{_iso(bas_dt)} 마지막 종가 · 지금 가격이 아닙니다"} if px else None)
        metrics: List[dict] = []
        year = rcept = ""
        if picked is not None:
            year, rcept = picked["bsns_year"], picked["rcept_no"]
            out["report"] = {"bsns_year": year, "report": F.REPORT_NAMES[ANNUAL], "fs": fs, "rcept_no": rcept,
                             "known_at": _iso(picked["known_at"]), "url": F.DART_VIEWER.format(rcept_no=rcept)}
            out["fs_note"] = fs_note or ("연결재무제표 기준" if fs == "CFS" else "")
        basis_report = (f"{year} 사업보고서({'연결' if fs == 'CFS' else '별도'}) · 공시 접수 {_iso(picked['known_at'])}"
                        if picked is not None else "재무 자료 없음")
        basis_px = f"종가 {_iso(bas_dt)}" if px else "종가 없음"

        # ── 재무 값 읽기(같은 판 · 총액과 지배 몫을 섞지 않는다)
        ni = eq = eps = None
        owner_note = ""
        if picked is not None:
            ni, eq, eps, owner_note = _owner_values(conn, symbol, year, rcept, fs)

        # EPS
        if eps is not None:
            metrics.append(_metric("eps", "주당이익(EPS)", eps, "원", f"{year} 사업보고서에 보고된 보통주 기본주당이익은 {eps:,.0f}원입니다.",
                                   "보고된 값(계산하지 않음)", basis_report))
        else:
            metrics.append(_metric("eps", "주당이익(EPS)", None, "원", "이 회사의 보고서에서 기본주당이익을 찾지 못했습니다.",
                                   "보고된 값(계산하지 않음)", basis_report, reason="보고서에 기본주당이익 계정이 없습니다."))
        # PER
        per_formula = "종가 ÷ 보고된 기본주당이익"
        if close is None:
            metrics.append(_metric("per", "PER", None, "배", "종가가 없어 계산하지 않았습니다.", per_formula, basis_report, reason="종가가 없습니다."))
        elif eps is None:
            metrics.append(_metric("per", "PER", None, "배", "보고된 기본주당이익이 없어 계산하지 않았습니다.", per_formula,
                                   f"{basis_px} · {basis_report}", reason="보고된 기본주당이익이 없습니다."))
        elif eps <= 0:
            metrics.append(_metric("per", "PER", None, "배", "적자라 계산하지 않았습니다. 이익이 없으면 주가가 이익의 몇 배인지를 말할 수 없습니다.",
                                   per_formula, f"{basis_px} · {basis_report}", reason="적자라 계산하지 않음"))
        else:
            v = round(close / eps, 1)
            metrics.append(_metric("per", "PER", v, "배", f"종가 {close:,.0f}원은 보고된 주당이익 {eps:,.0f}원의 {v}배입니다. 업종마다 보통 수준이 다릅니다.",
                                   per_formula, f"{basis_px} · {basis_report}"))
        # PBR
        pbr_formula = "시가총액 ÷ 지배지분 자본"
        pref = bool(px) and _has_preferred(conn, symbol, name or px_name or "", bas_dt)
        if mcap is None:
            metrics.append(_metric("pbr", "PBR", None, "배", "시가총액이 없어 계산하지 않았습니다.", pbr_formula, basis_report, reason="시가총액이 없습니다."))
        elif eq is None:
            metrics.append(_metric("pbr", "PBR", None, "배", "지배지분 자본을 찾지 못해 계산하지 않았습니다. 총액과 지배 몫을 섞지 않습니다.",
                                   pbr_formula, f"{basis_px} · {basis_report}", reason="지배지분 자본 계정이 없습니다."))
        elif eq <= 0:
            metrics.append(_metric("pbr", "PBR", None, "배", "자본이 0 이하(자본잠식)라 계산하지 않았습니다.", pbr_formula,
                                   f"{basis_px} · {basis_report}", reason="자본잠식이라 계산하지 않음"))
        else:
            v = round(mcap / eq, 2)
            extra = " 우선주가 상장된 회사라 시가총액(보통주만)이 실제보다 작아 낮게 나올 수 있습니다." if pref else ""
            metrics.append(_metric("pbr", "PBR", v, "배", f"시가총액 {_won(mcap)}은 지배지분 자본 {_won(eq)}의 {v}배입니다.{extra}",
                                   pbr_formula, f"{basis_px} · {basis_report}" + (f" · {owner_note}" if owner_note else ""), approx=pref))
        # ROE
        roe_formula = "지배주주 순이익 ÷ 지배지분 자본 × 100(연말 자본)"
        if ni is None or eq is None:
            metrics.append(_metric("roe", "ROE", None, "%", "지배 몫 순이익 또는 자본을 찾지 못해 계산하지 않았습니다.", roe_formula, basis_report,
                                   reason="지배 몫 순이익 · 자본 계정이 없습니다."))
        elif eq <= 0:
            metrics.append(_metric("roe", "ROE", None, "%", "자본이 0 이하(자본잠식)라 계산하지 않았습니다.", roe_formula, basis_report, reason="자본잠식이라 계산하지 않음"))
        else:
            v = round(ni / eq * 100, 1)
            metrics.append(_metric("roe", "ROE", v, "%", f"지배주주 순이익 {_won(ni)}을 지배지분 자본 {_won(eq)}으로 나눈 값입니다. 연말 자본 기준이라 평균 자본으로 구한 값과 다를 수 있습니다.",
                                   roe_formula, basis_report + (f" · {owner_note}" if owner_note else "")))
        # 영업이익률(주요계정)
        om_formula = "영업이익 ÷ 매출액 × 100"
        rev = opi = None
        if picked is not None:
            for nm, tgt in (("rev", ("매출액", "수익(매출액)", "영업수익")), ("op", ("영업이익", "영업이익(손실)"))):
                for a in tgt:
                    row = conn.execute(
                        "SELECT thstrm_amount FROM financial_statement WHERE stock_code=? AND bsns_year=? AND reprt_code=? AND fs_div=? "
                        "AND rcept_no=? AND scope='major' AND sj_div='IS' AND account_nm=? AND thstrm_amount IS NOT NULL LIMIT 1",
                        (symbol, year, ANNUAL, fs, rcept, a)).fetchone()
                    if row is not None:
                        if nm == "rev":
                            rev = row[0]
                        else:
                            opi = row[0]
                        break
        if rev is None or opi is None or rev == 0:
            metrics.append(_metric("operating_margin", "영업이익률", None, "%", "이 회사는 매출액 또는 영업이익 항목이 없거나 달라 계산하지 않았습니다(금융회사 등).",
                                   om_formula, basis_report, reason="매출액 · 영업이익 항목이 없습니다."))
        else:
            v = round(opi / rev * 100, 1)
            metrics.append(_metric("operating_margin", "영업이익률", v, "%", f"영업이익 {_won(opi)}을 매출액 {_won(rev)}으로 나눈 값입니다.", om_formula, basis_report))
        # 배당
        if px is not None:
            dps = _dividend_12m(conn, symbol, bas_dt)
            div_formula = "최근 12개월 안 기준일의 현금배당 주당배당금 합 ÷ 종가 × 100"
            div_basis = f"{basis_px} · 배당 결정 공시의 기준일 · 실제 지급과 다를 수 있음"
            if dps is None:
                metrics.append(_metric("dividend_yield", "배당수익률", None, "%", "배당 자료를 읽지 못했습니다.", div_formula, div_basis, reason="배당 표가 없습니다."))
            elif dps == 0:
                metrics.append(_metric("dividend_yield", "배당수익률", 0.0, "%", "최근 12개월 안에 현금배당 결정이 없습니다.", div_formula, div_basis))
            else:
                v = round(dps / close * 100, 2)
                metrics.append(_metric("dividend_yield", "배당수익률", v, "%", f"최근 12개월 주당배당금 합 {dps:,.0f}원을 종가 {close:,.0f}원으로 나눈 값입니다.", div_formula, div_basis))
        out["metrics"] = metrics
        return out
    finally:
        conn.close()
