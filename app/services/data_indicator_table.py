"""지표 비교 표 — 수집 대상 상장사 전부의 PER · PBR · ROE · EPS · 영업이익률 · 배당수익률을 한 표로 (D11 · 2026-11-04).

`GET /api/data/indicators/table` 이 부른다. 수집 DB 를 **읽기만** 한다.

왜 만들었나 — 지표 비교 화면은 종목 칩 + 종목 추가로 최대 8개만 견줄 수 있었다. 강사님 lumina-invest 는 전체 종목을 표(시장 · 업종 필터 ·
30종목 페이지 · 열 정렬)로 보여 준다. 우리는 그 꼴을 가져오되 값은 우리 수집 자료(전자공시 사업보고서 + 공공데이터포털 종가)만 쓴다 —
강사님은 종목마다 외부 재무 요약을 부르지만 우리는 그 길을 쓰지 않는다(수집 DB 만 읽는다).

값은 `company_indicators.read_indicators` 한 곳의 결과를 그대로 모은다
  - 종목마다 식을 다시 쓰지 않는다 — 지표 대시보드(`/api/data/indicators`)와 이 표의 숫자가 어긋날 수 없다(TC-IT 가 모든 행을 견준다).
  - 서버가 정렬 · 필터 · 쪽 자르기까지 한다. 화면은 받은 줄을 그릴 뿐 값을 셈하지 않는다.

비용 — 수집 대상 약 351곳을 한 번 훑는 데 몇 초가 걸린다. 그래서 전체 줄(필터 · 정렬 전)을 (수집 DB 경로, 가장 최근 종가 날짜) 키로
5분 저장하고, 처음 요청이 만드는 동안 다른 요청은 기다렸다가 같은 결과를 받는다(`/api/data/indicators/sectors` 와 같은 방식).
읽기는 종목 8개씩 나란히 한다(도커의 수집 DB 에서 차례로 읽으면 약 20초 → 약 4.6초).

시장 · 업종 — 수집 DB 에 든 칸만 쓴다.
  시장 = 전자공시 기업개황의 법인구분(`dart_company.corp_cls` · Y 유가증권 = 코스피 · K 코스닥 · N 코넥스). 그 칸이 없으면 비운다.
  업종 = 같은 기업개황의 업종코드 앞 2자리를 통계청 한국표준산업분류 11차 중분류 이름표(`ksic_code`)에 댄 것 — `/indicators/sectors` 와 같은 분류.
  이름표에 없는 코드는 「분류 못 찾음」(필터 값 `none`).

값이 없을 때 — 값은 null 이고 `reason` 이 까닭이다(0 이나 N/A 로 채우지 않는다). 줄마다 상태(`status`)와 풀이(`notes`)를 함께 준다.
정렬에서 값이 없는 줄은 오름 · 내림 어느 쪽이든 맨 뒤로 보낸다.

문장 규칙(TC-CIN 과 같다) — 투자 권유 낱말을 쓰지 않는다 · 한계를 글로 함께 준다.
"""
from __future__ import annotations

import math
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from app.services import collector_db
from app.services import company_indicators as CI
from app.services.company_indicators import IndicatorsError

# 지표 칸(표의 가로 순서). formula 는 `read_indicators` 가 같은 지표에 붙이는 식과 같아야 한다(TC-IT 가 견준다).
COLUMNS: List[dict] = [
    {"key": "per", "label": "PER", "unit": "배", "digits": 1, "formula": "종가 ÷ 보고된 기본주당이익"},
    {"key": "pbr", "label": "PBR", "unit": "배", "digits": 2, "formula": "시가총액 ÷ 지배지분 자본"},
    {"key": "roe", "label": "ROE", "unit": "%", "digits": 1, "formula": "지배주주 순이익 ÷ 지배지분 자본 × 100(연말 자본)"},
    {"key": "eps", "label": "EPS", "unit": "원", "digits": 0, "formula": "보고된 값(계산하지 않음)"},
    {"key": "operating_margin", "label": "영업이익률", "unit": "%", "digits": 1, "formula": "영업이익 ÷ 매출액 × 100"},
    {"key": "dividend_yield", "label": "배당수익률", "unit": "%", "digits": 2,
     "formula": "최근 12개월 안 기준일의 현금배당 주당배당금 합 ÷ 종가 × 100"},
]
METRIC_KEYS = tuple(c["key"] for c in COLUMNS)
TEXT_SORT_KEYS = ("name", "code", "market", "sector")
SORT_KEYS = TEXT_SORT_KEYS + METRIC_KEYS

CLS_TO_MARKET = {"Y": "KOSPI", "K": "KOSDAQ", "N": "KONEX"}
MARKET_NAMES = {"KOSPI": "코스피", "KOSDAQ": "코스닥", "KONEX": "코넥스"}
NO_SECTOR = "none"
NO_SECTOR_NAME = "분류 못 찾음"

DEFAULT_SIZE = 30
MIN_SIZE, MAX_SIZE = 10, 100
MAX_QUERY = 40
TTL = 300.0                                        # 수집은 하루 한 번이라 값이 바뀌지 않는다 — 5분 저장(업종 묶음과 같다)
# 종목마다 읽는 시간은 대부분 디스크를 기다리는 시간이다(도커의 수집 DB 마운트에서 종목당 약 50ms · 351곳을 차례로 읽으면 약 20초).
# 읽기 전용 연결을 종목마다 따로 열어 나란히 읽으면 같은 일이 약 4.6초(8개 · 도커 실측 2026-11-04)로 줄어든다.
WORKERS = 8

APPROX_NOTE = "우선주가 상장돼 시가총액(보통주만)이 작게 잡혀 낮게 나올 수 있습니다."
FS_NOTE = "연결재무제표가 없어 별도재무제표로 계산했습니다."
LIMITS = [
    "수집 대상 상장사만의 표입니다 — 코스피 · 코스닥 전체 종목이 아닙니다.",
    "재무는 종목마다 가장 최근 사업보고서(연 1회) 기준이고 종가 날짜도 종목마다 다를 수 있습니다. 기준은 줄마다 적었습니다.",
    "시장 · 업종은 전자공시 기업개황의 법인구분 · 업종코드(통계청 한국표준산업분류 11차 중분류)이며, 업종마다 보통 수준이 달라 같은 업종끼리 견주어야 뜻이 있습니다.",
    "값이 없는 칸은 줄표(—)이고 까닭을 조회 상태에 적었습니다. 정렬에서는 값이 없는 종목이 항상 맨 뒤입니다.",
]

_SECTOR = re.compile(r"^\d{2}$")
_LOCK = threading.Lock()
_CACHE: Dict[str, object] = {"at": 0.0, "key": None, "val": None}


def clear_cache() -> None:
    """저장해 둔 전체 줄을 비운다(시험 · 수집 직후)."""
    with _LOCK:
        _CACHE.update({"at": 0.0, "key": None, "val": None})


def _connect(path):
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)


def _basis(report: Optional[dict], price: Optional[dict]) -> str:
    """줄 하나의 기준 한 줄 — 재무 기준(보고서 · 접수일)과 종가 날짜. 서버가 한 번 지어 준다."""
    if report:
        fin = f"{report['bsns_year']} 사업보고서({'연결' if report['fs'] == 'CFS' else '별도'}) · 공시 접수 {report['known_at'] or '—'}"
    else:
        fin = "재무 자료 없음"
    px = f"종가 {price['trade_date']}" if price and price.get("trade_date") else "종가 없음"
    return f"{fin} · {px}"


def _row(code: str, name: str, cls: str, induty: str, sectors: Dict[str, str], ind: Optional[dict], err: str) -> dict:
    market = CLS_TO_MARKET.get((cls or "").strip().upper())
    prefix = (induty or "")[:2]
    sector = ({"code": prefix, "name": sectors[prefix]} if prefix in sectors else {"code": NO_SECTOR, "name": NO_SECTOR_NAME})
    metrics: Dict[str, dict] = {}
    notes: List[str] = []
    report = price = None
    if ind is None:
        for c in COLUMNS:
            metrics[c["key"]] = {"value": None, "reason": err}
    else:
        by_key = {m["key"]: m for m in ind.get("metrics", [])}
        for c in COLUMNS:
            m = by_key.get(c["key"])
            if m is None:                              # 배당수익률은 종가가 없으면 지표 자체가 안 온다
                metrics[c["key"]] = {"value": None, "reason": "종가가 없어 계산하지 않았습니다."}
            elif m.get("value") is None:
                metrics[c["key"]] = {"value": None, "reason": m.get("reason") or "계산하지 않았습니다."}
            else:
                metrics[c["key"]] = {"value": m["value"], **({"approx": True} if m.get("approx") else {})}
        r, p = ind.get("report"), ind.get("price")
        if r:
            report = {"bsns_year": r["bsns_year"], "fs": r["fs"], "known_at": r.get("known_at")}
        if p:
            price = {"close": p.get("close"), "trade_date": p.get("trade_date")}
        if report and report["fs"] != "CFS":
            notes.append(FS_NOTE)
    label = {c["key"]: c["label"] for c in COLUMNS}
    for c in COLUMNS:
        m = metrics[c["key"]]
        if m["value"] is None:
            notes.append(f"{label[c['key']]} — {m['reason']}")
        elif m.get("approx"):
            notes.append(f"{label[c['key']]} 근사 — {APPROX_NOTE}")
    missing = sum(1 for m in metrics.values() if m["value"] is None)
    if ind is None or missing == len(COLUMNS):
        status = {"code": "none", "text": "자료 없음", "missing": missing}
    elif missing:
        status = {"code": "partial", "text": "일부 값 없음", "missing": missing}
    else:
        status = {"code": "ok", "text": "완료", "missing": 0}
    return {"code": code, "name": name, "market": market, "sector": sector, "close": price["close"] if price else None,
            "trade_date": price["trade_date"] if price else None, "report": report, "basis": _basis(report, price),
            "metrics": metrics, "status": status, "notes": notes}


def _read_one(code: str):
    """종목 하나의 지표 — (응답, 까닭). 종가도 재무도 없는 종목(404)은 줄은 남기고 까닭을 적는다. 그 밖의 오류는 위로."""
    try:
        return CI.read_indicators(code), ""
    except IndicatorsError as e:
        if e.status != 404:
            raise
        return None, e.message


def _build(path) -> dict:
    """수집 대상 전부를 한 번 훑어 줄을 만든다 — 필터 · 정렬 · 쪽 자르기 전의 모습."""
    from app.services import macro_industry as MI
    conn = _connect(path)
    try:
        as_of = conn.execute("SELECT MAX(bas_dt) FROM price_daily").fetchone()[0]
        have = {r[1] for r in conn.execute("PRAGMA table_info(dart_company)")}
        cls_col = "d.corp_cls" if "corp_cls" in have else "''"
        ind_col = "d.induty_code" if "induty_code" in have else "''"
        companies = conn.execute(
            f"SELECT d.stock_code, d.stock_name, {cls_col}, {ind_col} FROM dart_company d WHERE d.stock_code <> '' AND d.last_seen_at = "
            "(SELECT MAX(x.last_seen_at) FROM dart_company x WHERE x.corp_code = d.corp_code) ORDER BY d.stock_code").fetchall()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        sectors = ({code: name for code, name in conn.execute(
            "SELECT code, name FROM ksic_code WHERE level = '중분류' AND revision = ?", (MI.KSIC_REVISION,))} if "ksic_code" in tables else {})
    finally:
        conn.close()
    uniq: Dict[str, tuple] = {}
    for code, name, cls, induty in companies:
        uniq.setdefault(code, (name, cls, induty))
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:           # 순서는 그대로 · 한 종목의 DB 오류는 여기서 위로 올라간다
        got = list(pool.map(_read_one, uniq))
    rows: List[dict] = []
    for code, (ind, err) in zip(uniq, got):
        name, cls, induty = uniq[code]
        rows.append(_row(code, name or (ind or {}).get("name") or "", cls, induty, sectors, ind, err))
    markets: Dict[str, int] = {}
    secs: Dict[str, dict] = {}
    for r in rows:
        if r["market"]:
            markets[r["market"]] = markets.get(r["market"], 0) + 1
        s = secs.setdefault(r["sector"]["code"], {"code": r["sector"]["code"], "name": r["sector"]["name"], "n": 0})
        s["n"] += 1
    return {"as_of": CI._iso(as_of), "rows": rows,
            "markets": [{"code": k, "name": MARKET_NAMES[k], "n": markets[k]} for k in ("KOSPI", "KOSDAQ", "KONEX") if k in markets],
            "sectors": sorted(secs.values(), key=lambda s: (s["code"] == NO_SECTOR, s["code"]))}


def _all_rows() -> dict:
    path = collector_db.db_path()
    if path is None:
        raise IndicatorsError(503, "no_db", "지표 비교 표 자료를 아직 받지 못했습니다.", "수집 DB 가 없다 — 수집기를 먼저 돌린다")
    try:
        conn = _connect(path)
        try:
            key = (str(path), conn.execute("SELECT MAX(bas_dt) FROM price_daily").fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error:
        raise IndicatorsError(503, "no_data", "지표 비교 표 자료를 읽지 못했습니다.", "수집 DB 에 종가 표(price_daily)가 없거나 열리지 않는다") from None
    with _LOCK:                                         # 처음 요청이 만드는 동안 다른 요청은 기다렸다가 같은 결과를 받는다
        if _CACHE["val"] is not None and _CACHE["key"] == key and time.monotonic() - float(_CACHE["at"]) < TTL:
            return _CACHE["val"]                        # type: ignore[return-value]
        try:
            built = _build(path)
        except sqlite3.Error:
            raise IndicatorsError(503, "read_failed", "지표 비교 표를 만들다 수집 DB 를 읽지 못했습니다. 잠시 뒤 다시 시도하세요.",
                                  "수집 DB 가 잠겼거나 표 모양이 다르다") from None
        _CACHE.update({"at": time.monotonic(), "key": key, "val": built})
        return built


def _validate(market: str, sector: str, q: str, sort: str, order: str, page: int, size: int) -> None:
    if market and market not in MARKET_NAMES:
        raise IndicatorsError(422, "bad_market", f"market 은 {' · '.join(MARKET_NAMES)} 가운데 하나이거나 비워 둡니다: {market!r}")
    if sector and sector != NO_SECTOR and not _SECTOR.match(sector):
        raise IndicatorsError(422, "bad_sector", f"sector 는 업종 중분류 2자리 코드이거나 {NO_SECTOR} 입니다: {sector!r}")
    if len(q) > MAX_QUERY:
        raise IndicatorsError(422, "bad_q", f"q 는 {MAX_QUERY}자까지입니다.")
    if sort not in SORT_KEYS:
        raise IndicatorsError(422, "bad_sort", f"sort 는 {' · '.join(SORT_KEYS)} 가운데 하나입니다: {sort!r}")
    if order not in ("asc", "desc"):
        raise IndicatorsError(422, "bad_order", f"order 는 asc · desc 입니다: {order!r}")
    if page < 1:
        raise IndicatorsError(422, "bad_page", f"page 는 1 이상입니다: {page}")
    if not MIN_SIZE <= size <= MAX_SIZE:
        raise IndicatorsError(422, "bad_size", f"size 는 {MIN_SIZE}~{MAX_SIZE} 입니다: {size}")


def _sorted(rows: List[dict], sort: str, order: str) -> List[dict]:
    """정렬 — 값이 없는 줄은 오름 · 내림과 상관없이 맨 뒤. 같은 값은 종목코드 오름차순(쪽을 넘겨도 순서가 흔들리지 않게)."""
    rev = order == "desc"
    base = sorted(rows, key=lambda r: r["code"])

    def key_of(r: dict):
        if sort == "name":
            return r["name"].casefold()
        if sort == "code":
            return r["code"]
        if sort == "market":
            return r["market"]
        if sort == "sector":
            return r["sector"]["name"]
        return r["metrics"][sort]["value"]

    have = [r for r in base if key_of(r) not in (None, "")]
    lack = [r for r in base if key_of(r) in (None, "")]
    have.sort(key=key_of, reverse=rev)                  # 파이썬 정렬은 안정적이라 reverse 여도 같은 값은 코드 오름차순
    return have + lack


def read_table(market: str = "", sector: str = "", q: str = "", sort: str = "name", order: str = "asc",
               page: int = 1, size: int = DEFAULT_SIZE) -> dict:
    """한 쪽 분량의 표 — 필터 → 정렬 → 쪽. 쪽이 끝을 넘으면 마지막 쪽으로 맞춘다(응답의 `page` 가 실제 쪽)."""
    market, sector, q = (market or "").strip().upper(), (sector or "").strip().lower(), (q or "").strip()
    _validate(market, sector, q, sort, order, page, size)
    data = _all_rows()
    rows = data["rows"]
    if market:
        rows = [r for r in rows if r["market"] == market]
    if sector:
        rows = [r for r in rows if r["sector"]["code"] == sector]
    if q:
        ql = q.casefold()
        rows = [r for r in rows if ql in r["name"].casefold() or q.upper() in r["code"]]
    rows = _sorted(rows, sort, order)
    total = len(rows)
    pages = max(1, math.ceil(total / size))
    page = min(page, pages)
    lo = (page - 1) * size
    chunk = rows[lo:lo + size]
    return {"available": True, "as_of": data["as_of"], "universe": len(data["rows"]), "total": total,
            "page": page, "pages": pages, "size": size, "start": lo + 1 if chunk else 0, "end": lo + len(chunk),
            "sort": sort, "order": order, "market": market, "sector": sector, "q": q,
            "columns": COLUMNS, "sort_keys": list(SORT_KEYS),
            "filters": {"markets": data["markets"], "sectors": data["sectors"]},
            "rows": chunk, "source": CI.SOURCE, "notice": CI.NOTICE, "limits": LIMITS}
