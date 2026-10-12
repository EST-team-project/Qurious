"""상품 안내 — ETF 목록 · 지표 (수집 DB `etf_daily` 를 읽기만 한다 · 2026-10-12 · 화면 키 `agent-products`)

무엇을 돌려주나
---------------
- `overview(per_group)` — 마지막 거래일의 ETF **전부**를 자산군 → 묶음으로 나누고(`etf_classify`), 묶음마다
  전체 개수와 순자산 큰 순 몇 개를 돌려준다.
- `list_etfs(...)` — 한 자산군 · 묶음의 전체 목록(정렬 · 쪽 나눔 · 이름 찾기).
- 레버리지 · 인버스는 자산군 탭이 아니라 맨 위 칸 `derivatives` 하나에 모은다(사용자 결정 2026-10-12 · 화면 안 A 의
  맨 끝 탭). 묶음은 배수 · 단일종목으로 나누고(주식 지수 2배 · −1배 · −2배 · 단일종목 · 주식 밖 자산), 「실제로
  사려면」 요건은 `etp_requirements` 상수표에서만 가져온다. 자산군 칸에는 그 자산군에서 빠져나간 개수
  (`derivatives_count`)만 남긴다 — 자산군 칸 수 + 파생형 칸 수 = 그날 전체.

지키는 것
---------
- **숨기지 않는다** — 묶음 개수를 모두 더하면 그날 전체 수와 같다. 레버리지 · 인버스 · 거래 정지 · 분류 못 함도
  목록에 남고 표시만 붙는다(사용자 2026-10-12 · 시험 TC-PG).
- 정렬 기준을 글로 싣는다 — 순서가 「추천」 이 아니라 정해진 기준(기본: 순자산총액 큰 순)이라는 것을 화면이
  그대로 보일 수 있게. 「추천 · 최적 · 유망」 같은 낱말을 우리 글에 쓰지 않는다(투자 권유로 읽히지 않게).
- 지표는 우리 자료로 잰 값이고 재는 법을 응답에 싣는다 — 1년 수익률 · 1년 최대 낙폭은 거래소 기준가로 이은 값
  (분배금을 다시 넣은 근사), 가격만 본 1년 수익률도 함께, 변동성은 기준가 이음 일간 수익률의 연율. 이력이 모자라면
  빈칸(None)이지 0 이 아니다(말없는 fallback 금지). 변동성 · 최대 낙폭은 공식 투자위험등급이 아니라고 글로 싣는다.
- 총보수(TER) · 추적오차는 우리 자료에 없다 — 만들어 내지 않는다(빈칸 그대로 · 화면은 운용사 공시를 보라고 안내).
- 수집 DB 는 `mode=ro` 로만 연다. 위치는 `collector_db.db_path()` 한 곳에서 찾는다(SSoT).
- 계산 결과는 (DB 파일 · 수정 시각 · 마지막 거래일)이 같을 때만 다시 쓴다 — 새 거래일이 들어오면 바로 새로 잰다
  (DF-17 「다리 앞 캐시가 12:30 뒤에도 옛 기준일을 낸다」 를 되풀이하지 않게). 이 자료는 우리가 모은 공공 자료라
  메모리에 두어도 된다(금감원 실시간 자료와 다르다 — `fss_products` 는 아무것도 두지 않는다).

출처 · 이용 조건 — 공공데이터포털 「금융위원회_증권상품시세정보」(데이터 15094806 · 2026-10-12 쪽 원문 확인):
공공누리 제4유형(출처표시 + 상업적 이용금지 + 변경금지) · 제3자 무단 제공 · 재배포 금지 → 이 서비스 안에서
보기만 하고 내려받기는 두지 않는다(자료 안내 출처 대장 `fsc` 줄과 같은 규칙).
"""
from __future__ import annotations

import logging
import math
import sqlite3
import threading
from datetime import date, timedelta
from pathlib import Path

from app.services import collector_db
from app.services import etf_classify as ec
from app.services import etp_requirements as etp

logger = logging.getLogger(__name__)

SOURCE = {
    "name": "금융위원회 증권상품시세정보(공공데이터포털)",
    "url": "https://www.data.go.kr/data/15094806/openapi.do",
    "license": "공공누리 제4유형 — 출처 표시 · 상업적 이용 금지 · 변경 금지 · 제3자 제공 · 재배포 금지",
}
SORT_KEYS = {
    "aum": ("aum", "순자산총액"),
    "trade_value": ("trade_value_20d", "20일 평균 거래대금"),
    "return_1y": ("return_1y_pct", "1년 수익률(분배금 포함 근사)"),
    "vol_1y": ("vol_1y_pct", "1년 변동성"),
    "name": ("name", "이름"),
}
NOTES = (
    "순서는 정해진 기준(기본 순자산총액 큰 순)에 따른 것이며 상품의 좋고 나쁨을 뜻하지 않습니다.",
    "1년 수익률은 거래소 기준가로 날마다 이은 값입니다 — 분배락일에 낮춘 기준가를 되돌려 분배금을 다시 넣었다고 본 "
    "근사값이며 세금 · 매매 비용은 빠져 있습니다. 가격만 본 수익률도 함께 싣습니다.",
    "변동성은 최근 1년 일간 수익률(분배락으로 내린 몫은 뺀 값)의 표준편차를 연 환산한 값입니다.",
    "최대 낙폭은 최근 1년 동안 직전 최고점에서 가장 크게 내려간 비율입니다 — 1년 수익률과 같은 기준가 이음 값으로 "
    "잽니다.",
    "변동성 · 최대 낙폭은 우리가 모은 자료로 잰 숫자이며, 금융회사가 매기는 공식 투자위험등급이 아닙니다.",
    "총보수와 추적오차는 이 자료에 없습니다 — 운용사 공시에서 확인해 주세요.",
)

# 레버리지 · 인버스 칸의 묶음 — 차례가 화면 차례다. 요건은 묶음마다 하나로 정해지고, 주식 밖 자산은 종목마다
# 배수가 달라 줄의 `requirement` 칸을 본다.
DERIVATIVE_GROUPS = (
    ("index_plus2", "주식 지수 2배", "leveraged_2x"),
    ("index_minus1", "주식 지수 −1배(인버스)", "inverse_1x"),
    ("index_minus2", "주식 지수 −2배", "leveraged_2x"),
    ("single_stock", "단일종목 레버리지 · 인버스", "single_stock"),
    ("other_assets", "채권 · 원자재 · 통화 레버리지 · 인버스", None),
)
DERIVATIVE_GROUP_LABELS = {k: label for k, label, _ in DERIVATIVE_GROUPS}
_EQUITY_CLASSES = ("국내주식", "해외주식")
_EQUITY_BY_MULTIPLE = {2: "index_plus2", -1: "index_minus1", -2: "index_minus2"}

_HISTORY_DAYS = 400          # 1년 + 여유 — 1년 전 값 · 1년 변동성에 쓰는 창
_YEAR_DAYS = 365
_LISTED_GRACE_DAYS = 14      # 창 첫날에서 이만큼 안에 첫 줄이 있으면 「창보다 오래전부터 있었다」 로 본다(연휴 여유)
_MIN_VOL_RETURNS = 60        # 일간 수익률이 이만큼 안 되면 변동성을 내지 않는다
_MAX_MISSING_VS = 0.05       # 전일 대비 칸이 빈 날이 이 비율을 넘으면 분배 포함 수익률을 내지 않는다
_TRADE_WINDOW = 20

_cache: dict = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)


def _iso(bas_dt: str | None) -> str | None:
    if not bas_dt or len(bas_dt) != 8:
        return None
    return f"{bas_dt[:4]}-{bas_dt[4:6]}-{bas_dt[6:]}"


def _day(bas_dt: str) -> date:
    return date(int(bas_dt[:4]), int(bas_dt[4:6]), int(bas_dt[6:]))


def _derivative_group(cls: ec.EtfClass) -> str | None:
    """분류 결과 → 레버리지 · 인버스 칸의 묶음(아니면 None)."""
    if cls.group != "leveraged_inverse":
        return None
    if cls.single_stock:
        return "single_stock"
    if cls.asset_class in _EQUITY_CLASSES:
        # 분류는 배수를 ±1 · ±2 로만 내므로 늘 셋 가운데 하나다 — 그래도 모르는 배수가 오면 숨기지 않고 주식 밖 묶음에 둔다
        return _EQUITY_BY_MULTIPLE.get(cls.multiple, "other_assets")
    return "other_assets"


def _metrics(hist: list[tuple[str, int | None, int | None, int | None]], year_ago: str, listed_after: str) -> dict:
    """한 종목의 (날짜 · 종가 · 전일 대비 · 거래대금) — 날짜 오름차순 — 에서 지표를 잰다.

    공공데이터의 「전일 대비」(vs)는 거래소 기준가로 잰 값이다 — 분배락일에는 기준가를 분배금만큼 낮추므로
    `종가 ÷ (종가 − 전일 대비)` 를 날마다 이으면 분배락 하락을 되돌린 수익률이 된다(우리 수집기가 주식 조정계수를
    vs 로 만드는 것과 같은 식 · 2026-10-12 실측: KODEX CD금리액티브 가격 0.01% → 기준가 이음 2.84% · 매달 기준가 조정 12번).
    날짜는 YYYYMMDD 글자 그대로 견준다(글자 차례 = 날짜 차례).
    """
    out = {"return_1y_pct": None, "price_return_1y_pct": None, "vol_1y_pct": None, "mdd_1y_pct": None,
           "trade_value_20d": None, "history_from": None}
    trades = [t for _, _, _, t in hist if t is not None]
    if trades:
        tail = trades[-_TRADE_WINDOW:]
        out["trade_value_20d"] = int(round(sum(tail) / len(tail)))
    rows = [(d, c, v) for d, c, v, _ in hist if c and c > 0]
    if not rows:
        return out
    first = rows[0][0]
    if first > listed_after:
        out["history_from"] = _iso(first)        # 창 안에서 처음 나타났다 = 그날 상장(우리 자료 기준)
    in_year = [i for i, (d, _, _) in enumerate(rows) if d >= year_ago]
    if not in_year:
        return out
    i0 = in_year[0]
    # 1년 기준가 이음 · 일간 수익률(변동성용)
    daily, missing = [], 0
    for d, c, v in rows[i0 + 1:]:
        base = c - v if v is not None else None
        if base is None or base <= 0:
            missing += 1
            continue
        daily.append(c / base - 1.0)
    if first <= year_ago:                           # 1년 넘게 있었던 것만 1년 수익률을 낸다(짧으면 빈칸)
        out["price_return_1y_pct"] = (rows[-1][1] / rows[i0][1] - 1.0) * 100.0
        n_days = len(rows) - i0 - 1
        if n_days > 0 and missing <= _MAX_MISSING_VS * n_days:
            # 같은 이음 값으로 최대 낙폭도 잰다 — 분배락으로 내린 가격은 낙폭에 넣지 않는다(투자자가 잃은 것이 아니다)
            tr, peak, mdd = 1.0, 1.0, 0.0
            for r in daily:
                tr *= 1.0 + r
                peak = max(peak, tr)
                mdd = min(mdd, tr / peak - 1.0)
            out["return_1y_pct"] = (tr - 1.0) * 100.0
            out["mdd_1y_pct"] = mdd * 100.0
    if len(daily) >= _MIN_VOL_RETURNS:
        m = sum(daily) / len(daily)
        var = sum((r - m) ** 2 for r in daily) / (len(daily) - 1)
        out["vol_1y_pct"] = math.sqrt(var) * math.sqrt(252) * 100.0
    return out


def _compute(path: Path, last_bas_dt: str) -> dict:
    last = _day(last_bas_dt)
    window_start = (last - timedelta(days=_HISTORY_DAYS)).strftime("%Y%m%d")
    year_ago = (last - timedelta(days=_YEAR_DAYS)).strftime("%Y%m%d")
    listed_after = (last - timedelta(days=_HISTORY_DAYS - _LISTED_GRACE_DAYS)).strftime("%Y%m%d")
    conn = _connect(path)
    try:
        latest = conn.execute(
            "SELECT srtn_cd, itms_nm, bss_idx_nm, clpr, nav, npt_tot_amt, tr_prc, halted "
            "FROM etf_daily WHERE bas_dt = ?", (last_bas_dt,)).fetchall()
        # 기본키(bas_dt, srtn_cd) 범위로 읽고 차례는 파이썬에서 맞춘다 — 121만 행 전체를 훑거나 DB 에서 다시 정렬하지 않게
        hist_rows = conn.execute(
            "SELECT srtn_cd, bas_dt, clpr, vs, tr_prc FROM etf_daily WHERE bas_dt >= ? AND bas_dt <= ?",
            (window_start, last_bas_dt)).fetchall()
        data_from = conn.execute("SELECT MIN(bas_dt) FROM etf_daily").fetchone()[0]
    finally:
        conn.close()
    hist: dict[str, list] = {}
    for code, d, c, v, t in hist_rows:
        hist.setdefault(code, []).append((d, c, v, t))
    for lst in hist.values():
        lst.sort(key=lambda r: r[0])
    items = []
    for code, name, idx, close, nav, aum, trp, halted in latest:
        cls = ec.classify(name, idx)
        dgroup = _derivative_group(cls)
        m = _metrics(hist.get(code, []), year_ago, listed_after)
        items.append({
            "code": code,
            "name": name,
            "index_name": idx,
            "asset_class": cls.asset_class,
            "group": cls.group,
            "flags": list(cls.flags),
            "multiple": cls.multiple,
            "single_stock": cls.single_stock,
            "derivative_group": dgroup,
            "requirement": etp.requirement_key(cls.multiple, cls.single_stock),
            "aum": aum,
            "close": close,
            "nav": nav,
            "premium_pct": (close / nav - 1.0) * 100.0 if (close and nav) else None,
            "trade_value_20d": m["trade_value_20d"],
            "return_1y_pct": m["return_1y_pct"],
            "price_return_1y_pct": m["price_return_1y_pct"],
            "return_basis": "base_price_chain",
            "vol_1y_pct": m["vol_1y_pct"],
            "mdd_1y_pct": m["mdd_1y_pct"],
            "history_from": m["history_from"],
            "halted": bool(halted),
        })
    return {"as_of": _iso(last_bas_dt), "data_from": _iso(data_from), "window_from": _iso(window_start), "items": items}


def _load() -> dict:
    """마지막 거래일의 계산 결과 — 없으면 {"status": "no_data"} · 읽기 실패는 {"status": "error"}."""
    path = collector_db.db_path()
    if path is None or not Path(path).exists():
        return {"status": "no_data"}
    path = Path(path)
    try:
        conn = _connect(path)
        try:
            last = conn.execute("SELECT MAX(bas_dt) FROM etf_daily").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.warning("상품 안내 — 수집 DB 를 읽지 못함: %s", type(e).__name__)
        return {"status": "error"}
    if not last:
        return {"status": "no_data"}
    key = (str(path.resolve()), path.stat().st_mtime_ns, last)
    with _lock:
        hit = _cache.get("v")
        if hit and hit[0] == key:
            return hit[1]
    try:
        data = {"status": "ok", **_compute(path, last)}
    except sqlite3.Error as e:
        logger.warning("상품 안내 — ETF 지표 계산 중 DB 오류: %s", type(e).__name__)
        return {"status": "error"}
    with _lock:
        _cache["v"] = (key, data)
    return data


def _common(data: dict) -> dict:
    return {
        "status": data["status"],
        "as_of": data.get("as_of"),
        "data_from": data.get("data_from"),
        "window_from": data.get("window_from"),
        "source": SOURCE,
        "notes": list(NOTES),
        "flag_labels": dict(ec.FLAG_LABELS),
        "flag_notes": dict(ec.FLAG_NOTES),
        "group_labels": dict(ec.GROUP_LABELS),
        "derivative_group_labels": dict(DERIVATIVE_GROUP_LABELS),
        "requirements": etp.public(),
    }


def _sort_items(items: list[dict], sort: str, order: str) -> list[dict]:
    field = SORT_KEYS[sort][0]
    have = [x for x in items if x.get(field) is not None]
    missing = [x for x in items if x.get(field) is None]          # 값이 없는 것은 늘 뒤에 — 숨기지 않는다
    have.sort(key=lambda x: (x[field], x["code"]), reverse=(order == "desc"))
    return have + sorted(missing, key=lambda x: x["code"])


def overview(per_group: int = 3) -> dict:
    data = _load()
    out = _common(data)
    out["sort"] = {"key": "aum", "label": "순자산총액 큰 순 — 상품의 좋고 나쁨을 뜻하지 않습니다"}
    derivatives = {"key": "derivatives", "label": ec.GROUP_LABELS["leveraged_inverse"], "notes": etp.notes()}
    if data["status"] != "ok":
        out.update({"total": 0, "classes": [], "derivatives": {**derivatives, "count": 0, "aum": 0, "groups": []}})
        return out
    items = data["items"]
    classes = []
    for c in ec.ASSET_CLASSES:
        mine = [x for x in items if x["asset_class"] == c.key and x["derivative_group"] is None]
        moved = sum(1 for x in items if x["asset_class"] == c.key and x["derivative_group"] is not None)
        groups = []
        for g in c.groups:
            if g == "leveraged_inverse":
                continue        # 파생형은 맨 위 칸으로 — 자산군 칸에는 개수(derivatives_count)만 남긴다
            gi = _sort_items([x for x in mine if x["group"] == g], "aum", "desc")
            groups.append({"key": g, "label": ec.GROUP_LABELS[g], "count": len(gi), "items": gi[:per_group]})
        classes.append({"key": c.key, "label": c.label, "count": len(mine), "derivatives_count": moved,
                        "aum": sum(x["aum"] or 0 for x in mine), "groups": groups})
    deriv = [x for x in items if x["derivative_group"] is not None]
    dgroups = []
    for key, label, req in DERIVATIVE_GROUPS:
        gi = _sort_items([x for x in deriv if x["derivative_group"] == key], "aum", "desc")
        dgroups.append({"key": key, "label": label, "requirement": req, "count": len(gi), "items": gi[:per_group]})
    derivatives.update({"count": len(deriv), "aum": sum(x["aum"] or 0 for x in deriv), "groups": dgroups})
    out.update({"total": len(items), "classes": classes, "derivatives": derivatives})
    return out


def list_etfs(asset_class: str | None = None, group: str | None = None, q: str | None = None,
              sort: str = "aum", order: str = "desc", offset: int = 0, limit: int = 50) -> dict:
    if sort not in SORT_KEYS:
        raise ValueError(f"정렬 기준은 {', '.join(SORT_KEYS)} 가운데 하나입니다")
    if order not in ("desc", "asc"):
        raise ValueError("순서는 desc · asc 가운데 하나입니다")
    if asset_class is not None and asset_class not in ec.CLASS_BY_KEY:
        raise ValueError(f"자산군은 {', '.join(ec.CLASS_BY_KEY)} 가운데 하나입니다")
    if group is not None and group not in ec.GROUP_LABELS and group not in DERIVATIVE_GROUP_LABELS:
        raise ValueError(f"묶음은 {', '.join([*ec.GROUP_LABELS, *DERIVATIVE_GROUP_LABELS])} 가운데 하나입니다")
    data = _load()
    out = _common(data)
    out["sort"] = {"key": sort, "order": order, "label": SORT_KEYS[sort][1]}
    if data["status"] != "ok":
        out.update({"total": 0, "offset": offset, "limit": limit, "items": []})
        return out
    items = data["items"]
    if asset_class is not None:
        items = [x for x in items if x["asset_class"] == asset_class]
    if group in DERIVATIVE_GROUP_LABELS:
        items = [x for x in items if x["derivative_group"] == group]     # 파생형 묶음(배수 · 단일종목)
    elif group is not None:
        items = [x for x in items if x["group"] == group]
    if q:
        needle = q.strip().lower()
        items = [x for x in items if needle in (x["name"] or "").lower() or needle in (x["index_name"] or "").lower()
                 or needle == x["code"].lower()]
    items = _sort_items(items, sort, order)
    out.update({"total": len(items), "offset": offset, "limit": limit, "items": items[offset:offset + limit]})
    return out

