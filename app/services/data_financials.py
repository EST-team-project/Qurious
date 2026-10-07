"""재무제표 주요계정 — 기준일에 알 수 있었던 값만 (API-DATA-04 · 목표 기능 ① W7 · 설계서 5.1.5).

`GET /api/data/financials` 가 부른다. 수집 DB 의 `financial_statement`(`collector/financials.py`)를 **읽기만** 한다.

★ 미래 참조를 막는 두 방식 — `pit`
-----------------------------------
DART 재무 API 는 가장 최근 정정본만 준다. 그래서 행마다 날짜가 둘이다(`collector/financials.py` 머리말).

    known_at        이 값이 실린 보고서의 접수일
    first_known_at  그 기간 원본 보고서의 접수일(정정 전)

    pit=strict  기준일 **전날까지** 접수된 판의 값만 쓴다(known_at < as_of). 그 기간에 그런 판이 없으면 그 기간은 뺀다.
                미래 값이 섞이지 않지만, 뒤에 정정된 기간은 정정일 전까지 비어 보인다(과거분은 정정본 값만 받았기 때문).
    pit=first   그 기간 원본이 기준일 전에 나왔으면(first_known_at < as_of) 쓴다. 기준일 전에 접수된 판이 있으면 그 판,
                없으면 가진 판 가운데 가장 이른 것을 쓰고 `values_revised_after_as_of: true` 로 알린다(값에는 기준일 뒤의
                정정이 섞였을 수 있다).

as_of 를 비우면 거르지 않는다(가장 최근 판 · 화면의 「지금 재무」).

기본이 strict 인 까닭 — 현업 방식(조사서 `docs/조사/지난판/공시-재무-뉴스-이용조건-조사_v0.1.md` 4절)
  - Sharadar 의 As Reported(AR) 는 「excludes restatements」 · 「time-indexed to the date the … filing was submitted」 다.
  - Compustat 은 처음 보고값(HIST_STD · Snapshot)과 정정값(RST_STD)을 따로 두고, 시점 연구는 앞의 것을 쓴다(WRDS 안내).
  - 1차 Alpha_Stack(`supply/financial.py`)도 정정일을 그대로 쓰고 **접수일 다음 거래일**부터 보이게 했다 — 「원본 날짜에 정정
    숫자를 붙이면 재작성 누수」. 여기 `available_from` 칸이 그 규칙이고, `amended` 는 그 판 **자기 제목**의 정정 표시다
    (공시 목록의 비고 「정」 은 나중에 붙는 표시라 쓰지 않는다 — 그 자체가 미래 참조).
  - 「가장 최근」 은 알게 된 순서가 아니라 **결산 순서**다(정정본이 옛 해를 늦게 드러내도 최근 해를 밀어내지 않는다 — 1차 규칙).
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta

from app.services import collector_db

PIT_MODES = ("strict", "first")
FS_DIVS = ("CFS", "OFS")
DEFAULT_PERIODS = 8
MAX_PERIODS = 40

REPORT_NAMES = {"11013": "1분기보고서", "11012": "반기보고서", "11014": "3분기보고서", "11011": "사업보고서"}
_SYMBOL = re.compile(r"^\d{6}$|^[0-9A-Z]{6}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: 요약 칸 — (이름, 재무제표, 같은 뜻의 계정 이름들)
KEY = (
    ("revenue", "IS", ("매출액", "수익(매출액)", "영업수익")),
    ("operating_income", "IS", ("영업이익", "영업이익(손실)")),
    ("net_income", "IS", ("당기순이익(손실)", "당기순이익")),
    ("assets", "BS", ("자산총계",)),
    ("liabilities", "BS", ("부채총계",)),
    ("equity", "BS", ("자본총계",)),
)

DART_VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


class FinancialsError(Exception):
    def __init__(self, status: int, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.status, self.code, self.message, self.hint = status, code, message, hint

    def detail(self) -> dict:
        d = {"code": self.code, "message": self.message}
        if self.hint:
            d["hint"] = self.hint
        return d


def _yyyymmdd(iso: str) -> str:
    return iso.replace("-", "")


def _iso(v: str | None) -> str | None:
    s = str(v or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else None


def next_trading_day(conn: sqlite3.Connection, yyyymmdd: str) -> tuple[str | None, bool]:
    """접수일 다음 거래일(YYYY-MM-DD) · 달력이 없거나 끝을 넘으면 다음 평일로 어림하고 True(어림)."""
    iso = _iso(yyyymmdd)
    if not iso:
        return None, False
    try:
        row = conn.execute("SELECT cal_date FROM market_calendar WHERE cal_date > ? AND is_trading_day = 1 "
                           "ORDER BY cal_date LIMIT 1", (iso,)).fetchone()
    except sqlite3.OperationalError:
        row = None
    if row:
        return row[0], False
    d = date.fromisoformat(iso) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat(), True


def _revision(conn: sqlite3.Connection, rcept_no: str) -> str | None:
    """그 판 자기 제목의 머리 [..] — 공시 목록에 없으면 None(모름)."""
    try:
        row = conn.execute("SELECT revision FROM disclosure WHERE rcept_no = ?", (rcept_no,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return None if row is None else (row[0] or "")


def choose_version(versions: list[dict], as_of: str | None, pit: str) -> tuple[dict | None, bool]:
    """한 기간의 판들(known_at · first_known_at) → (고른 판, 값이 기준일 뒤에 고쳐졌을 수 있나).

    시험(TC-DQ)이 이 함수를 직접 부른다 — 화면 · 백테스트가 같은 규칙을 쓰게 한 곳에 둔다.
    """
    if not versions:
        return None, False
    vs = sorted(versions, key=lambda v: (v["known_at"], v["rcept_no"]))
    if not as_of:
        return vs[-1], False
    cut = _yyyymmdd(as_of)
    known = [v for v in vs if v["known_at"] < cut]
    if known:
        return known[-1], False
    if pit == "first":
        first = min((v.get("first_known_at") or v["known_at"]) for v in vs)
        if first < cut:
            return vs[0], True
    return None, False


def read_financials(symbol: str, as_of: str | None = None, pit: str = "strict", fs: str = "CFS",
                    periods: int = DEFAULT_PERIODS) -> dict:
    symbol = (symbol or "").strip().upper()
    if not _SYMBOL.match(symbol):
        raise FinancialsError(422, "bad_symbol", f"symbol 은 단축코드 6자리입니다: {symbol!r}")
    if pit not in PIT_MODES:
        raise FinancialsError(422, "bad_pit", f"pit 는 {' · '.join(PIT_MODES)} 가운데 하나입니다: {pit!r}")
    fs = (fs or "CFS").upper()
    if fs not in FS_DIVS:
        raise FinancialsError(422, "bad_fs", f"fs 는 CFS(연결) · OFS(별도) 가운데 하나입니다: {fs!r}")
    if not (1 <= periods <= MAX_PERIODS):
        raise FinancialsError(422, "bad_periods", f"periods 는 1~{MAX_PERIODS} 입니다.")
    if as_of:
        if not _DAY.match(as_of):
            raise FinancialsError(422, "bad_date", f"as_of 는 YYYY-MM-DD 꼴이어야 합니다: {as_of!r}")
        try:
            date.fromisoformat(as_of)
        except ValueError:
            raise FinancialsError(422, "bad_date", f"as_of 가 없는 날짜입니다: {as_of!r}") from None

    path = collector_db.db_path()
    if path is None:
        raise FinancialsError(503, "no_db", "수집 DB 가 없습니다.", "python -m collector.financials backfill 을 먼저 돌린다")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='financial_statement'").fetchone():
            raise FinancialsError(503, "no_table", "재무 표가 아직 없습니다.", "python -m collector.financials backfill")
        vers = [dict(r) for r in conn.execute(
            "SELECT DISTINCT corp_code, bsns_year, reprt_code, rcept_no, known_at, first_known_at, period_end "
            "  FROM financial_statement WHERE stock_code = ? AND fs_div = ? AND scope = 'major'",
            (symbol, fs))]
        if not vers:
            other = conn.execute("SELECT 1 FROM financial_statement WHERE stock_code = ? LIMIT 1", (symbol,)).fetchone()
            hint = ("다른 fs(별도 OFS · 연결 CFS)로 다시 물어본다 — 연결 대상이 없는 회사는 별도만 있다" if other
                    else "상장사 재무가 아니거나(ETF · 스팩 · 리츠 일부) 아직 받지 않았다")
            raise FinancialsError(404, "no_financials", f"{symbol} 의 {fs} 재무가 없습니다.", hint)
        groups: dict[tuple, list[dict]] = {}
        for v in vers:
            groups.setdefault((v["bsns_year"], v["reprt_code"], v["period_end"]), []).append(v)
        chosen = []
        for (y, rc, pe), vs in groups.items():
            v, revised = choose_version(vs, as_of, pit)
            if v is not None:
                chosen.append((pe, y, rc, v, revised, len(vs)))
        chosen.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
        out_periods = []
        for pe, y, rc, v, revised, n_versions in chosen[:periods]:
            rows = conn.execute(
                "SELECT sj_div, ord, account_nm, thstrm_amount, thstrm_add_amount, frmtrm_amount, currency "
                "  FROM financial_statement WHERE corp_code = ? AND bsns_year = ? AND reprt_code = ? AND fs_div = ? "
                "   AND rcept_no = ? ORDER BY sj_div, ord", (v["corp_code"], y, rc, fs, v["rcept_no"])).fetchall()
            accounts = [{"statement": r["sj_div"], "name": r["account_nm"], "amount": r["thstrm_amount"],
                         "cumulative": r["thstrm_add_amount"], "previous": r["frmtrm_amount"]} for r in rows]
            key = {}
            for name, sj, names in KEY:
                hit = next((a for nm in names for a in accounts if a["statement"] == sj and a["name"] == nm), None)
                key[name] = hit["amount"] if hit else None
            avail, approx = next_trading_day(conn, v["known_at"])
            rev = _revision(conn, v["rcept_no"])
            out_periods.append({
                "bsns_year": y, "reprt_code": rc, "report": REPORT_NAMES.get(rc, rc), "period_end": pe,
                "rcept_no": v["rcept_no"], "url": DART_VIEWER.format(rcept_no=v["rcept_no"]),
                "known_at": _iso(v["known_at"]), "first_known_at": _iso(v["first_known_at"]),
                "available_from": avail, "available_from_approx": approx,
                "amended": None if rev is None else bool(rev), "revision": rev,
                "restated": bool(v["first_known_at"] and v["first_known_at"] < v["known_at"]),
                "values_revised_after_as_of": revised, "versions": n_versions,
                "currency": rows[0]["currency"] if rows else "KRW", "key": key, "accounts": accounts,
            })
        corp = vers[0]["corp_code"]
    finally:
        conn.close()
    return {
        "symbol": symbol, "corp_code": corp, "fs": fs, "pit": pit, "as_of": as_of,
        "periods": out_periods,
        "source": "전자공시(DART) 다중회사 주요계정(fnlttMultiAcnt)",
        "rule": ("strict = 기준일 전날까지 접수된 판의 값만(처음 보고값 기준 시점 자료 — Sharadar AR · Compustat Snapshot 과 "
                 "같은 뜻) · 판은 접수일 다음 거래일(available_from)부터 쓴다 · 기간은 결산 순서로 늘어놓는다"),
        "note": ("손익계산서 amount 는 분기 · 반기 보고서면 그 3개월 값이고 cumulative 가 누적이다. "
                 "known_at = 값이 실린 보고서 접수일 · first_known_at = 그 기간 원본 접수일 · "
                 "2026-10-04 전 기간은 DART 가 최신 정정본만 줘서 정정된 기간은 정정본 값뿐이다(그 뒤로는 매일 판을 쌓는다)."),
    }
