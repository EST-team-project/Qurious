"""거시경제 현황 — 한국은행 ECOS 계열의 최근 값 (할 일 ①-10 거시 · 2026-10-29).

`GET /api/macro/ecos` 가 부른다. 수집 DB 의 `ecos_series`(`collector/ecos.py` 가 매일 받는다)를 **읽기만** 한다.
앱 이미지에는 `collector/` 가 없어 항목표(`GROUPS`)를 여기에도 둔다 — 두 표가 같은지는 시험(TC-MK-01)이 지킨다.

옛 거시 화면은 야후 시세로 미국 10년물 · 유가 같은 것을 그렸다(한국 거시가 아니었다). 이 길은 우리가 받은 한국은행 통계
— 기준금리 · 시장금리 · 주가지수 · 원/달러 환율 · 소비자물가 — 를 **값 · 기준일 · 이전 값 · 출처**와 함께 그대로 준다.

규칙
  - 값은 수집 DB 에 있는 것만. 없는 계열은 줄을 빼지 않고 `value: null` 과 까닭을 준다(화면이 줄표로 보인다).
  - 변화는 서버가 한 곳에서 셈한다 — 금리는 직전 관측값과의 차이(%p), 지수 · 환율은 직전 관측값 대비 %, 물가는 전월 대비 %와
    전년 같은 달 대비 %. 화면은 셈하지 않는다.
  - 「직전」 은 **그 계열의 직전 관측일**이다(주말 · 휴일은 건너뛴다) — 어제가 아니다. 응답에 직전 날짜를 함께 싣는다.
  - 출처 표시 — ECOS 약관 제7조② 「ECOS 에서 제공된 정보임을 표시」 → `ATTRIBUTION` 을 늘 싣고, 계열마다 작성기관(`origin`)을
    붙인다(환율은 서울외국환중개 — 영리 목적 복제 · 배포를 막는 약관이 있어 출처를 숨기지 않는다).
  - 일반 사용자 응답에는 표 이름 · 명령을 싣지 않는다(관리자에게만 `admin_hint`).
"""
from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional, Tuple

from app.services import collector_db

ATTRIBUTION = "한국은행 경제통계시스템(ECOS)"
REGION = "KR"
NOTICE = ("한국은행이 집계 · 고시한 통계를 수집한 값입니다 — 거래소 실시간 시세가 아니며, 기준일은 값마다 다릅니다. "
          "투자 권유가 아닙니다.")

#: 변화를 말하는 법 — pp(금리: 직전 관측값과의 차이 %p) · pct(지수 · 환율: 직전 관측값 대비 %) · cpi(전월 대비 % + 전년 같은 달 대비 %)
#: (열쇠, 항목 코드, 이름, 단위, 변화 종류)
Item = Tuple[str, str, str, str, str]
#: (묶음 열쇠, 묶음 이름, 통계표, 주기, 작성기관, 항목들) — collector/ecos.py 의 GROUPS · SERIES · ORIGIN 과 같아야 한다(TC-MK-01).
GROUPS: Tuple[Tuple[str, str, str, str, str, Tuple[Item, ...]], ...] = (
    ("policy", "기준금리", "722Y001", "D", "한국은행", (
        ("base_rate", "0101000", "한국은행 기준금리", "연%", "pp"),
    )),
    ("market_rates", "시장금리", "817Y002", "D", "한국은행", (
        ("treasury_3y", "010200000", "국고채(3년)", "연%", "pp"),
        ("treasury_10y", "010210000", "국고채(10년)", "연%", "pp"),
        ("corp_aa_3y", "010300000", "회사채(3년, AA-)", "연%", "pp"),
        ("corp_bbb_3y", "010320000", "회사채(3년, BBB-)", "연%", "pp"),
        ("cd_91d", "010502000", "CD(91일)", "연%", "pp"),
        ("cp_91d", "010503000", "CP(91일)", "연%", "pp"),
    )),
    ("index", "주가지수", "802Y001", "D", "한국은행", (
        ("kospi", "0001000", "KOSPI지수", "포인트", "pct"),
        ("kosdaq", "0089000", "KOSDAQ지수", "포인트", "pct"),
    )),
    ("fx", "환율", "731Y001", "D", "서울외국환중개", (
        ("usd_krw", "0000001", "원/미국달러(매매기준율)", "원", "pct"),
    )),
    ("price", "물가", "901Y009", "M", "국가데이터처", (
        ("cpi_total", "0", "소비자물가지수 총지수", "지수", "cpi"),
    )),
)
#: 월 계열은 전년 같은 달까지 보려면 열세 줄이면 된다 · 일 계열은 직전 관측값까지 둘이면 된다
_ROWS = {"D": 2, "M": 13}


def _unavailable(reason: str, admin: bool, hint: str) -> Dict:
    out = {"available": False, "region": REGION, "reason": reason, "source": ATTRIBUTION, "notice": NOTICE,
           "groups": [], "updated_at": None}
    if admin:
        out["admin_hint"] = hint
    return out


def _tail(conn: sqlite3.Connection, stat: str, code: str, cycle: str) -> List[Tuple[str, float, str]]:
    """(날짜, 값, 받은 시각) — 최근 것부터. 값이 빈 줄은 쓰지 않는다."""
    rows = conn.execute(
        "SELECT date, value, updated_at FROM ecos_series WHERE stat_code = ? AND item_code = ? AND cycle = ? "
        "AND value IS NOT NULL ORDER BY date DESC LIMIT ?", (stat, code, cycle, _ROWS[cycle])).fetchall()
    return [(d, v, u) for d, v, u in rows]


def _same_month_last_year(month: str) -> str:
    y, m = month.split("-")
    return f"{int(y) - 1:04d}-{m}"


def _pct(now: float, before: float) -> Optional[float]:
    return round((now / before - 1) * 100, 2) if before else None


def _item(conn: sqlite3.Connection, stat: str, cycle: str, origin: str, spec: Item) -> Dict:
    key, code, label, unit, kind = spec
    out: Dict = {"key": key, "label": label, "unit": unit, "origin": origin, "cycle": cycle, "kind": kind,
                 "date": None, "value": None, "prev": None, "change": None, "yoy_pct": None, "updated_at": None,
                 "reason": "아직 받은 값이 없습니다."}
    rows = _tail(conn, stat, code, cycle)
    if not rows:
        return out
    d, v, upd = rows[0]
    out.update(date=d, value=v, updated_at=upd, reason="")
    if len(rows) > 1:
        pd_, pv, _u = rows[1]
        out["prev"] = {"date": pd_, "value": pv}
        if kind == "pp":
            out["change"] = {"unit": "%p", "value": round(v - pv, 2)}
        else:                      # pct · cpi — 직전 관측값 대비 %
            pct = _pct(v, pv)
            out["change"] = {"unit": "%", "value": pct} if pct is not None else None
    if kind == "cpi":
        last_year = _same_month_last_year(d)
        base = next((val for dd, val, _u in rows if dd == last_year), None)
        out["yoy_pct"] = _pct(v, base) if base is not None else None
    return out


def read_ecos(admin: bool = False) -> Dict:
    path = collector_db.db_path()
    if path is None:
        return _unavailable("한국은행 통계를 아직 받지 못했습니다.", admin, "수집 DB 가 없다 — 수집기를 먼저 돌린다")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ecos_series'").fetchone():
            return _unavailable("한국은행 통계를 아직 받지 못했습니다.", admin,
                                "ecos_series 표가 없다 — python -m collector.ecos backfill (키는 .env 의 ECOS_API_KEY)")
        groups = []
        for gkey, glabel, stat, cycle, origin, specs in GROUPS:
            groups.append({"key": gkey, "label": glabel, "origin": origin, "cycle": cycle,
                           "items": [_item(conn, stat, cycle, origin, s) for s in specs]})
    finally:
        conn.close()
    items = [i for g in groups for i in g["items"]]
    if not any(i["value"] is not None for i in items):
        return _unavailable("한국은행 통계를 아직 받지 못했습니다.", admin,
                            "ecos_series 가 비었다 — python -m collector.ecos backfill (키는 .env 의 ECOS_API_KEY)")
    stamps = [i["updated_at"] for i in items if i["updated_at"]]
    return {"available": True, "region": REGION, "source": ATTRIBUTION, "notice": NOTICE, "groups": groups,
            "updated_at": max(stamps) if stamps else None}
