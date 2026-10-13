"""거시 신용 — 한국은행 ECOS 시장금리로 신용 스프레드 (API-RISK-02 · ④-2 재무 · 신용 위험 · 2026-10-13).

`GET /api/risk/macro` 가 부른다. 수집 DB 의 `ecos_series`(`collector/ecos.py` 가 매일 받는다)를 **읽기만** 한다.
앱 이미지에는 `collector/` 가 없어 항목 코드 표(`ITEMS`)를 여기에도 둔다 — 두 표가 같은지는 시험(TC-MC)이 지킨다.

신용 스프레드 — **같은 날** 두 금리의 차이(bp = 0.01%p). 한쪽만 있는 날은 쓰지 않는다(날을 맞추지 않으면 다른 날 금리를
빼게 된다).
  aa      회사채(3년, AA-) − 국고채(3년)   우량 회사가 3년 빌릴 때 나라보다 더 내는 이자
  bbb     회사채(3년, BBB-) − 국고채(3년)  투자 적격 가장 아래 등급 회사의 그 값
  cp_cd   CP(91일) − CD(91일)              회사가 석 달 빌리는 어음 금리와 은행이 석 달 빌리는 금리의 차이
위치는 지난 `STATS_YEARS` 년의 하루값 가운데 아래에서 몇 % 자리인가(같거나 낮은 날의 몫)로 보인다 — 높고 낮음의 기준을
우리가 정하지 않고 그 계열 자신의 과거와 견준다.

출처 표시 — ECOS 약관 제7조② 「ECOS 에서 제공된 정보임을 표시」 → `ATTRIBUTION` 을 응답에 늘 싣는다.
일반 사용자 응답에는 표 이름 · 명령을 싣지 않는다(관리자에게만 `admin_hint`).
"""
from __future__ import annotations

import sqlite3
from bisect import bisect_right
from datetime import date, timedelta
from statistics import median
from typing import Dict, List, Optional, Tuple

from app.services import collector_db

ATTRIBUTION = "한국은행 경제통계시스템(ECOS)"
#: 지역 칸 — 지금은 한국 시장금리(ECOS)만. 미국(회사채 스프레드 계열) 등을 붙일 자리(사용자 2026-10-13 「확장 가능성 고려」).
REGION = "KR"
STAT = "817Y002"
#: (열쇠, 항목 코드, 이름) — collector/ecos.py 의 SERIES 와 같아야 한다(TC-MC-01).
ITEMS: Tuple[Tuple[str, str, str], ...] = (
    ("treasury_3y", "010200000", "국고채(3년)"),
    ("corp_aa_3y", "010300000", "회사채(3년, AA-)"),
    ("corp_bbb_3y", "010320000", "회사채(3년, BBB-)"),
    ("cd_91d", "010502000", "CD(91일)"),
    ("cp_91d", "010503000", "CP(91일)"),
)
#: (열쇠, 이름, 앞 항목, 뒤 항목, 읽는 법 한 줄)
SPREADS: Tuple[Tuple[str, str, str, str, str], ...] = (
    ("aa", "회사채 AA- − 국고채 3년", "corp_aa_3y", "treasury_3y",
     "우량 회사(AA-)가 3년 동안 돈을 빌릴 때 나라보다 더 내는 이자입니다"),
    ("bbb", "회사채 BBB- − 국고채 3년", "corp_bbb_3y", "treasury_3y",
     "투자 적격 가운데 가장 아래 등급(BBB-) 회사가 3년 동안 빌릴 때 나라보다 더 내는 이자입니다"),
    ("cp_cd", "CP 91일 − CD 91일", "cp_91d", "cd_91d",
     "회사가 어음(CP)으로 석 달 빌리는 금리와 은행이 양도성예금증서(CD)로 석 달 빌리는 금리의 차이입니다"),
)
DEFAULT_YEARS = 3
MAX_YEARS = 10
STATS_YEARS = 10
CHANGE_DAYS = 20          # 한 달쯤 전(거래일 20)과 견준다

NOTICE = "시장 전체의 금리 차이입니다 — 어느 한 회사의 위험을 말하지 않습니다. 투자 권유가 아닙니다."


class MacroError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

    def detail(self) -> Dict:
        return {"code": self.code, "message": self.message}


def _unavailable(reason: str, admin: bool, hint: str) -> Dict:
    out = {"available": False, "region": REGION, "reason": reason, "source": ATTRIBUTION, "notice": NOTICE, "spreads": [],
           "rates": []}
    if admin:
        out["admin_hint"] = hint
    return out


def _load(path, since: str) -> Optional[Dict[str, Dict[str, float]]]:
    """{열쇠: {날짜: 값}} — 표가 없으면 None."""
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ecos_series'").fetchone():
            return None
        code_to_key = {code: key for key, code, _ in ITEMS}
        out: Dict[str, Dict[str, float]] = {key: {} for key, _c, _n in ITEMS}
        q = ("SELECT item_code, date, value FROM ecos_series WHERE stat_code = ? AND cycle = 'D' AND date >= ? "
             f"AND item_code IN ({','.join('?' * len(ITEMS))}) AND value IS NOT NULL")
        for code, d, v in conn.execute(q, (STAT, since, *code_to_key)):
            out[code_to_key[code]][d] = v
        return out
    finally:
        conn.close()


def spread_series(a: Dict[str, float], b: Dict[str, float]) -> List[Tuple[str, float]]:
    """같은 날 둘 다 있는 날만 (날짜, a − b 의 bp) — 날짜 순."""
    return [(d, round((a[d] - b[d]) * 100, 1)) for d in sorted(set(a) & set(b))]


def pct_rank(values: List[float], x: float) -> float:
    """values 가운데 x 와 같거나 낮은 값의 몫(%)."""
    s = sorted(values)
    return round(bisect_right(s, x) / len(s) * 100, 1) if s else 0.0


def read_macro(years: int = DEFAULT_YEARS, admin: bool = False, today: Optional[date] = None) -> Dict:
    if not (1 <= years <= MAX_YEARS):
        raise MacroError(422, "bad_years", f"years 는 1 ~ {MAX_YEARS} 입니다.")
    path = collector_db.db_path()
    if path is None:
        return _unavailable("시장금리 자료를 아직 받지 못했습니다.", admin, "수집 DB 가 없다 — 수집기를 먼저 돌린다")
    today = today or date.today()
    since = (today - timedelta(days=366 * max(years, STATS_YEARS) + 7)).isoformat()
    data = _load(path, since)
    if data is None or not data["treasury_3y"]:
        return _unavailable("시장금리 자료를 아직 받지 못했습니다.", admin,
                            "ecos_series 가 비었다 — python -m collector.ecos backfill (키는 .env 의 ECOS_API_KEY)")
    show_from = (today - timedelta(days=366 * years)).isoformat()
    rates = []
    for key, code, name in ITEMS:
        s = data[key]
        if s:
            d = max(s)
            rates.append({"key": key, "label": name, "date": d, "value": s[d], "unit": "연%"})
    spreads = []
    for key, label, k_a, k_b, meaning in SPREADS:
        series = spread_series(data[k_a], data[k_b])
        if not series:
            spreads.append({"key": key, "label": label, "latest": None, "history": [], "stats": None, "change": None,
                            "sentence": f"{label} — 두 금리가 함께 있는 날이 없어 셀 수 없습니다.", "points": []})
            continue
        d_last, bp = series[-1]
        values = [v for _d, v in series]
        stats = {"years": STATS_YEARS, "days": len(values), "from": series[0][0], "min": min(values),
                 "max": max(values), "median": round(median(values), 1), "pct_rank": pct_rank(values, bp)}
        prev = series[-1 - CHANGE_DAYS] if len(series) > CHANGE_DAYS else None
        change = {"days": CHANGE_DAYS, "from": prev[0], "bp": round(bp - prev[1], 1)} if prev else None
        moved = ""
        if change:
            moved = (f"한 달쯤 전({prev[0]})보다 {abs(change['bp']):.0f}bp " +
                     ("벌어졌습니다" if change["bp"] > 0 else "좁혀졌습니다" if change["bp"] < 0 else "그대로입니다"))
        spreads.append({
            "key": key, "label": label, "latest": {"date": d_last, "bp": bp},
            "history": [{"date": d, "bp": v} for d, v in series if d >= show_from],
            "stats": stats, "change": change,
            "sentence": (f"{label} 차이는 {bp:,.0f}bp({bp / 100:.2f}%p) — 지난 {STATS_YEARS}년 하루값 가운데 "
                         f"아래에서 {stats['pct_rank']:.0f}% 자리입니다."),
            "points": [
                meaning,
                f"재는 법: 같은 날 두 금리의 차이 · 1bp = 0.01%p · 지난 {STATS_YEARS}년 가장 낮았던 날 {stats['min']:,.0f}bp · "
                f"가장 높았던 날 {stats['max']:,.0f}bp · 가운데 {stats['median']:,.0f}bp",
                "차이가 벌어지면 돈을 빌려주는 쪽이 회사에 더 많은 이자를 요구한다는 뜻입니다 — 경기 · 신용 걱정이 커질 때 흔히 "
                "벌어지지만, 국고채 금리가 따로 크게 움직여도 벌어지거나 좁혀집니다",
                *([moved] if moved else []),
                f"출처: {ATTRIBUTION} · 마지막 날 {d_last}",
            ],
        })
    return {"available": True, "region": REGION, "as_of": max(data["treasury_3y"]), "years": years, "rates": rates,
            "spreads": spreads,
            "source": ATTRIBUTION, "notice": NOTICE}
