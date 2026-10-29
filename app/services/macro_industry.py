"""국내 산업별 하루 등락 — KSIC 중분류별 (할 일 ①-10 산업 · 2026-10-29).

`GET /api/macro/industry-kr` 가 부른다. 수집 DB 를 **읽기만** 한다 —
  dart_company  전자공시(DART) 기업개황의 업종코드(수집기 `company` 단계 · 지금 판 = 회사마다 last_seen_at 이 가장 늦은 줄)
  ksic_code     통계청 한국표준산업분류(KSIC) 이름 표 — 중분류(2자리) 이름과 대분류(알파벳). **제11차**만 쓴다(아래)
  price_daily   공공데이터포털 주식시세정보 — 그날 등락률(`flt_rt` %) · 시가총액

옛 산업 화면은 미국 섹터 ETF 의 지연 시세를 그렸다(한국 산업이 아니었다). 이 길은 우리가 모은 한국 종목을 업종 중분류로 묶어
하루 등락의 **중앙값 · 오른 종목 수 · 종목 수**를 보인다.

규칙
  - 업종코드는 3 ~ 5자리(소 · 세 · 세세분류)다 — 앞 두 자리가 중분류다. KSIC 표에 없는 두 자리는 버리지 않고 「분류 못 찾음」 한 묶음으로.
  - 등락률이 없는 종목(그날 시세 행이 없음)은 중앙값 · 오른 종목 수에서 빼고 `priced` 로 몇 곳이 들어갔는지 밝힌다.
  - **업종 전체의 지수가 아니다** — 수집 대상(분봉 유니버스) 몇 곳만의 값이라 응답에 곳 수를 싣고 말로도 밝힌다. 종목이 셋보다 적은 묶음은
    `thin` 으로 표시한다(한두 종목의 움직임을 업종의 움직임으로 읽지 않게).
  - 일반 사용자 응답에는 표 이름 · 명령을 싣지 않는다(관리자에게만 `admin_hint`).
"""
from __future__ import annotations

import sqlite3
from statistics import median
from typing import Dict, List, Optional

from app.services import collector_db

REGION = "KR"
SOURCE = "전자공시(DART) 기업개황 업종코드 · 통계청 한국표준산업분류(KSIC) 제11차 · 공공데이터포털 주식시세정보"
#: 이름 표(ksic_code)에는 10차와 11차가 함께 있다. 개정판을 안 가르면 같은 코드에 이름이 둘이라 어느 쪽이 나올지 정해지지 않는다
#: (중분류는 60 · 65 두 곳의 이름이 다르다). 우리 회사 351곳의 업종코드는 **모두 11차 표에 있고** 10차에는 349곳뿐이라(2026-10-29 확인 —
#: 21100 · 21212 는 11차에만 있다) 11차를 쓴다.
KSIC_REVISION = "11"
THIN = 3          # 이보다 적은 종목의 묶음은 「적은 종목」 표시
TOP = 3           # 묶음마다 시가총액이 큰 종목 이름 몇 개


def _notice(universe: int) -> str:
    return (f"수집 대상 {universe}곳만의 업종별 하루 등락입니다 — 업종 전체 지수가 아니고, 종목이 적은 업종은 한두 종목이 값을 좌우합니다. "
            "투자 권유가 아닙니다.")


def _unavailable(reason: str, admin: bool, hint: str) -> Dict:
    out = {"available": False, "region": REGION, "reason": reason, "source": SOURCE, "notice": _notice(0), "as_of": None,
           "universe": 0, "priced": 0, "groups": []}
    if admin:
        out["admin_hint"] = hint
    return out


def _date(bas_dt: str) -> str:
    return f"{bas_dt[:4]}-{bas_dt[4:6]}-{bas_dt[6:8]}" if len(bas_dt or "") == 8 else (bas_dt or "")


def _tables(conn: sqlite3.Connection) -> set:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def read_industry(admin: bool = False) -> Dict:
    path = collector_db.db_path()
    if path is None:
        return _unavailable("업종별 자료를 아직 받지 못했습니다.", admin, "수집 DB 가 없다 — 수집기를 먼저 돌린다")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        have = _tables(conn)
        missing = [t for t in ("dart_company", "ksic_code", "price_daily") if t not in have]
        if missing:
            return _unavailable("업종별 자료를 아직 받지 못했습니다.", admin,
                                f"표가 없다: {', '.join(missing)} — 수집기 company · 시세 단계를 먼저 돌린다")
        as_of = conn.execute("SELECT MAX(bas_dt) FROM price_daily").fetchone()[0]
        if not as_of:
            return _unavailable("업종별 자료를 아직 받지 못했습니다.", admin, "price_daily 가 비었다")
        companies = conn.execute(
            "SELECT d.stock_code, d.stock_name, d.induty_code, p.flt_rt, p.mrkt_tot_amt FROM dart_company d "
            "LEFT JOIN price_daily p ON p.srtn_cd = d.stock_code AND p.bas_dt = ? "
            "WHERE d.stock_code <> '' AND d.last_seen_at = (SELECT MAX(x.last_seen_at) FROM dart_company x WHERE x.corp_code = d.corp_code)",
            (as_of,)).fetchall()
        names = {code: (name, parent) for code, name, parent in conn.execute(
            "SELECT code, name, parent_code FROM ksic_code WHERE level = '중분류' AND revision = ?", (KSIC_REVISION,))}
        sections = {code: name for code, name in conn.execute(
            "SELECT code, name FROM ksic_code WHERE level = '대분류' AND revision = ?", (KSIC_REVISION,))}
    finally:
        conn.close()
    if not companies:
        return _unavailable("업종별 자료를 아직 받지 못했습니다.", admin, "dart_company 가 비었다 — python -m collector.dart_company")

    buckets: Dict[str, List[tuple]] = {}
    for row in companies:
        prefix = (row[2] or "")[:2]
        buckets.setdefault(prefix if prefix in names else "", []).append(row)

    groups = []
    for code, rows in buckets.items():
        changes = [r[3] for r in rows if r[3] is not None]
        top = sorted((r for r in rows if r[4] is not None), key=lambda r: r[4], reverse=True)[:TOP]
        if code:
            name, parent = names[code]
            section = {"code": parent, "name": sections.get(parent, "")}
        else:
            name, section = "분류 못 찾음", {"code": "", "name": ""}
        groups.append({
            "code": code, "name": name, "section": section, "n": len(rows), "priced": len(changes),
            "change_median": round(median(changes), 2) if changes else None,
            "up": sum(1 for c in changes if c > 0), "down": sum(1 for c in changes if c < 0),
            "flat": sum(1 for c in changes if c == 0), "thin": len(rows) < THIN,
            "top": [{"code": r[0], "name": r[1]} for r in top],
        })
    # 등락 중앙값이 큰 순 — 모르는 묶음은 맨 뒤 · 같으면 종목 많은 쪽 먼저
    groups.sort(key=lambda g: (g["change_median"] is None, -(g["change_median"] or 0), -g["n"], g["code"]))
    universe = len(companies)
    return {"available": True, "region": REGION, "source": SOURCE, "notice": _notice(universe), "as_of": _date(as_of),
            "universe": universe, "priced": sum(g["priced"] for g in groups), "groups": groups}
