"""상장사 재무 건전성 — 우리 DART 주요계정으로 (API-RISK-01 · ④-2 재무 · 신용 위험 · 2026-10-13).

`GET /api/risk/company` 가 부른다. 재무 숫자는 `data_financials.read_financials`(판 고르기 · 시점 고정을 한 곳에서 — SSoT)
에서만 받는다. 여기서는 그 숫자로 비율 · 점검 · 모형 점수 · 쉬운 말을 짓고, 수집 DB 를 따로 열지 않는다.

무엇을 보이나 — 재는 법은 아래 `_metric_*` 함수 한 곳(화면은 이 응답의 글 · 숫자를 그대로 그린다)
  유동비율        유동자산 ÷ 유동부채 × 100                    (분기 · 반기 · 사업보고서마다 — 그림의 선)
  부채비율        부채총계 ÷ 자본총계 × 100                    (한국 관행 — 이자 붙는 빚만이 아니라 부채 전부)
  자기자본비율    자본총계 ÷ 자산총계 × 100
  자본잠식률      (자본금 − 자본총계) ÷ 자본금 × 100           (자본총계가 자본금보다 작을 때만 · 0 이하는 완전자본잠식)
  Altman Z''      6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4         (사업보고서 · 해마다)
                  X1 운전자본 ÷ 자산 · X2 이익잉여금 ÷ 자산 · X3 영업이익 ÷ 자산 · X4 자본 ÷ 부채
                  경계 1.10 · 2.60 — Altman · Hartzell · Peck(1995 · 신흥국 회사채 점수 모형) · Altman(2005 Emerging Markets
                  Review)의 비제조 · 신흥국판. 신흥국판의 상수 3.25(신용등급 꼴로 옮길 때)는 더하지 않는다. 영업이익을 EBIT
                  대신 쓴다(주요계정에 이자비용이 없다). 계수 · 경계는 이차 출처 여럿이 같다(확실도 중간 ~ 높음 · 조사서).
  점검 일곱       Simply Wall St 「Balance Sheet Health」 의 점검 여섯을 우리 자료에 맞춰 옮기고(단기 · 장기 부채 대비 유동자산 ·
                  부채 추세 · 영업현금흐름 · 이자보상) 한국 상장 규정의 자본잠식 · 영업이익 흑자를 더했다.

숨기지 않는 것(사용자 2026-10-13 D67 「지금은 자료 없음 · 수집은 3차」)
  이자보상배율 · 영업현금흐름 ÷ 부채 — 주요계정에 이자비용 · 현금흐름표가 없다 → 점검 · `unavailable` 에 까닭과 함께 싣는다.
  금융회사(은행 · 보험 · 증권 · 금융지주) — 유동 · 비유동 구분이 없고 예금 · 보험 부채가 장사 밑천이다. 위 비율 · 모형으로
  견줄 수 없으므로 값 대신 까닭을 싣는다(실측 2026-10-13: 주요계정 회사 3,041 가운데 유동자산이 있는 곳 2,951).
  정정된 기간 — 2026-10-04 전 기간은 DART 가 정정본만 줘서 처음 보고값이 없다(D66 「되살리지 않음 · 표시만」).

문장 규칙(S108 · S109 와 같다) — 문장은 서버 한 곳에서 짓는다 · 투자 권유 낱말을 쓰지 않는다 · 좋은 쪽만 말하지 않고
반대로 읽을 수 있는 경우를 늘 한 줄 · 업종마다 다르다는 한계를 적는다.
"""
from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional, Tuple

from app.services import collector_db
from app.services import data_financials as F

ANNUAL = "11011"
#: 시장 칸 — 지금은 국내 상장사(DART)만. 미국(SEC EDGAR 재무 후보) · 코인(재무제표 없음 → 「해당 없음」)을 붙일 자리
#: (사용자 2026-10-13 「확장 가능성 고려」 · 시장 범위 조사서 6절 레지스트리).
MARKET = "KR"
#: 유동 · 비유동 구분이 없을 때 금융업 꼴로 보는 계정(2026-10-13 실측 — 예수부채 58 · 보험계약부채 22 · 순이자손익 51 곳 …)
FIN_MARKERS = ("예수부채", "보험계약부채", "보험계약자산", "투자계약부채", "순이자손익", "순수수료손익", "이자수익")

#: (열쇠, 재무제표, 같은 뜻의 계정 이름들) — 2026-10-13 주요계정 계정 이름 실측(결손은 음수 이익잉여금으로 온다)
ACCOUNTS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("current_assets", "BS", ("유동자산",)),
    ("current_liabilities", "BS", ("유동부채",)),
    ("noncurrent_liabilities", "BS", ("비유동부채",)),
    ("assets", "BS", ("자산총계",)),
    ("liabilities", "BS", ("부채총계",)),
    ("capital_stock", "BS", ("자본금",)),
    ("retained_earnings", "BS", ("이익잉여금",)),
    ("equity", "BS", ("자본총계",)),
    ("revenue", "IS", ("매출액", "수익(매출액)", "영업수익")),
    ("operating_income", "IS", ("영업이익", "영업이익(손실)")),
)
LABELS = {"current_assets": "유동자산", "current_liabilities": "유동부채", "noncurrent_liabilities": "비유동부채",
          "assets": "자산총계", "liabilities": "부채총계", "capital_stock": "자본금", "retained_earnings": "이익잉여금",
          "equity": "자본총계", "revenue": "매출액", "operating_income": "영업이익"}

Z_LOW, Z_HIGH = 1.10, 2.60
Z_COEF = (6.56, 3.26, 6.72, 1.05)
ZONES = {"high": f"높은 구간({Z_HIGH:.2f} 초과)", "middle": f"가운데 구간({Z_LOW:.2f} ~ {Z_HIGH:.2f})",
         "low": f"낮은 구간({Z_LOW:.2f} 미만)"}
#: 부채 추세를 견주는 햇수(사업보고서) — 해외 서비스의 「5년 사이 줄었나」 를 따랐다.
TREND_YEARS = 5

NOTICE = ("투자 권유가 아닙니다. 지난 재무제표로 계산한 값이며 앞날을 맞히지 않습니다. 출처: 전자공시(DART) 주요계정 · "
          "같은 업종의 회사끼리 견줘야 뜻이 있습니다.")
SOURCE = "전자공시(DART) 다중회사 주요계정 — 접수일 다음 거래일부터 쓴 판"


class HealthError(Exception):
    """재무를 읽지 못했다 — 라우트가 상태 번호 · 글을 그대로 돌려준다."""

    def __init__(self, status: int, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.status, self.code, self.message, self.hint = status, code, message, hint

    def detail(self, admin: bool = False) -> Dict:
        """힌트는 4xx(다시 묻는 법)면 누구에게나 · 5xx(수집 · 설정 — 명령이 든다)면 관리자에게만(일반 사용자 답에 명령을 싣지 않는다)."""
        show = bool(self.hint) and (admin or self.status < 500)
        return {"code": self.code, "message": self.message, **({"hint": self.hint} if show else {})}


# ==================================================
# 1. 계정 읽기
# ==================================================
def accounts_of(period: Dict) -> Dict[str, Optional[int]]:
    """한 기간의 요약 계정 — 같은 뜻의 이름 가운데 처음 나온 값(없으면 None)."""
    out: Dict[str, Optional[int]] = {}
    for key, sj, names in ACCOUNTS:
        hit = next((a for nm in names for a in period.get("accounts") or []
                    if a.get("statement") == sj and a.get("name") == nm), None)
        out[key] = hit.get("amount") if hit else None
    return out


def kind_of(period: Dict) -> str:
    """general(유동 · 비유동이 있음) · financial(구분 없음 + 금융업 계정) · no_split(구분 없음)."""
    names = {a.get("name") for a in period.get("accounts") or []}
    if "유동자산" in names and "유동부채" in names:
        return "general"
    if any(m in names for m in FIN_MARKERS):
        return "financial"
    return "no_split"


def _ratio(num: Optional[int], den: Optional[int]) -> Optional[float]:
    if num is None or den is None or den == 0:
        return None
    return num / den * 100


def zone_of(z: float) -> str:
    """Altman Z'' 구간 — 2.60 초과 high · 1.10 ~ 2.60 middle · 1.10 미만 low(경계 값은 가운데)."""
    if z > Z_HIGH:
        return "high"
    if z < Z_LOW:
        return "low"
    return "middle"


#: 경계에서 이만큼 안이면 「경계에 붙어 있다」 고 따로 알린다 — 카카오 2025년 2.61(경계 2.60)처럼 한 해 숫자로 구간이
#: 갈리는 회사가 있다(2026-10-13 실측 · 해마다 2.20 ~ 2.88 을 오감).
NEAR_EDGE = 0.10


def _near_edge(z: float) -> List[str]:
    for edge in (Z_HIGH, Z_LOW):
        if abs(z - edge) < NEAR_EDGE:
            return [f"경계({edge:.2f})와 {abs(z - edge):.2f} 차이입니다 — 한 해 숫자만으로 구간을 단정하지 말고 해마다의 흐름을 보세요"]
    return []


def z_score(a: Dict[str, Optional[int]]) -> Tuple[Optional[float], Optional[Dict[str, float]], str]:
    """(점수, X1 ~ X4, 못 셀 때 까닭)."""
    need = ("current_assets", "current_liabilities", "assets", "retained_earnings", "operating_income", "equity",
            "liabilities")
    miss = [LABELS[k] for k in need if a.get(k) is None]
    if miss:
        return None, None, f"{' · '.join(miss)} 칸이 없어 셀 수 없습니다"
    if not a["assets"] or not a["liabilities"]:
        return None, None, "자산총계나 부채총계가 0 이라 셀 수 없습니다"
    x = {"x1": (a["current_assets"] - a["current_liabilities"]) / a["assets"],
         "x2": a["retained_earnings"] / a["assets"],
         "x3": a["operating_income"] / a["assets"],
         "x4": a["equity"] / a["liabilities"]}
    z = sum(c * x[k] for c, k in zip(Z_COEF, ("x1", "x2", "x3", "x4")))
    return z, x, ""


# ==================================================
# 2. 문장 — 서버 한 곳에서 짓는다
# ==================================================
def _basis(p: Dict) -> Dict:
    return {"period_end": p.get("period_end"), "report": p.get("report"), "bsns_year": p.get("bsns_year"),
            "url": p.get("url"), "restated": bool(p.get("restated")), "available_from": p.get("available_from")}


def _restated_point(p: Dict) -> List[str]:
    if p.get("restated"):
        return [f"{p.get('report')}({p.get('period_end')})는 정정 공시로 값이 바뀐 기간입니다 — 처음 보고된 값은 남아 있지 않습니다"]
    return []


def _metric(key: str, label: str, value: Optional[float], unit: str, basis: Dict, formula: str, inputs: Dict,
            sentence: str, points: List[str], reason: str = "") -> Dict:
    return {"key": key, "label": label, "value": None if value is None else round(value, 1), "unit": unit,
            "basis": basis, "formula": formula, "inputs": inputs, "sentence": sentence if value is not None else reason,
            "points": points, "reason": reason if value is None else ""}


def _history(periods_asc: List[Dict], fn) -> List[Dict]:
    out = []
    for p in periods_asc:
        v = fn(accounts_of(p))
        if v is not None:
            out.append({"period_end": p.get("period_end"), "report": p.get("report"), "value": round(v, 1)})
    return out


# ==================================================
# 3. 한 회사
# ==================================================
#: 이름 · 시장 — 시세 표의 마지막 줄(색인 ix_price_srtn(srtn_cd, bas_dt) · 질의 계획은 시험 TC-FH-15). 재무 API 에는 이름이 없고,
#: 화면이 바깥 종목 검색(야후)에 이름을 기대지 않게 한다. 못 읽으면 빈칸(이름은 꾸밈이라 응답을 막지 않는다).
NAME_SQL = "SELECT itms_nm, mrkt_ctg FROM price_daily WHERE srtn_cd = ? ORDER BY bas_dt DESC LIMIT 1"


def name_of(symbol: str) -> Tuple[str, str]:
    path = collector_db.db_path()
    if path is None:
        return "", ""
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            row = conn.execute(NAME_SQL, (symbol,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return "", ""
    return (row[0] or "", row[1] or "") if row else ("", "")


def _read(symbol: str, as_of: Optional[str], fs: str) -> Tuple[Dict, Optional[str]]:
    """재무 읽기 — 연결(CFS)이 없으면 별도(OFS)로 다시 읽고 그 사실을 글로 남긴다(말없이 바꾸지 않는다)."""
    try:
        return F.read_financials(symbol, as_of, "strict", fs, F.MAX_PERIODS), None
    except F.FinancialsError as e:
        if e.code == "no_financials" and fs == "CFS":
            try:
                return (F.read_financials(symbol, as_of, "strict", "OFS", F.MAX_PERIODS),
                        "연결 재무제표가 없는 회사라 별도 재무제표로 봤습니다")
            except F.FinancialsError:
                pass
        raise HealthError(e.status, e.code, e.message, e.hint) from None


def read_health(symbol: str, as_of: Optional[str] = None, fs: str = "CFS") -> Dict:
    data, fs_note = _read(symbol, as_of, (fs or "CFS").upper())
    name, exchange = name_of(data.get("symbol") or symbol)
    periods: List[Dict] = data.get("periods") or []
    if not periods:
        raise HealthError(404, "no_periods", f"{symbol} 의 재무 기간이 없습니다.",
                          "기준일(as_of)을 비우거나 더 늦은 날로 다시 묻는다")
    asc = sorted(periods, key=lambda p: (p.get("period_end") or "", p.get("bsns_year") or ""))
    latest = periods[0]
    annual = [p for p in periods if p.get("reprt_code") == ANNUAL]
    annual_asc = sorted(annual, key=lambda p: p.get("period_end") or "")
    kind = kind_of(latest)
    a = accounts_of(latest)
    lb = _basis(latest)
    restated = _restated_point(latest)
    fin_reason = ("금융회사는 예금 · 보험 같은 부채가 장사 밑천이고 유동 · 비유동 구분이 없어 이 비율로 견줄 수 없습니다"
                  if kind == "financial" else "유동 · 비유동 구분이 없는 재무제표라 셀 수 없습니다")

    metrics: List[Dict] = []
    # 유동비율
    cr = _ratio(a["current_assets"], a["current_liabilities"]) if kind == "general" else None
    metrics.append(_metric(
        "current_ratio", "유동비율", cr, "%", lb, "유동자산 ÷ 유동부채 × 100",
        {"유동자산": a["current_assets"], "유동부채": a["current_liabilities"]},
        f"유동비율은 {cr:,.0f}% — 1년 안에 돈이 되는 자산이 1년 안에 갚을 빚의 {cr / 100:.1f}배입니다." if cr is not None else "",
        ["재는 법: 유동자산 ÷ 유동부채 × 100",
         "100% 아래면 1년 안에 갚을 빚이 1년 안에 돈이 되는 자산보다 많다는 뜻입니다",
         "높다고 늘 좋지는 않습니다 — 쓰지 않고 쌓아 둔 재고 · 현금이 많다는 뜻일 수도 있습니다",
         "업종마다 보통 수준이 다릅니다 — 같은 업종의 회사끼리 견주세요", *restated],
        reason="" if kind == "general" else fin_reason))
    metrics[-1]["history"] = _history(asc, lambda x: _ratio(x["current_assets"], x["current_liabilities"])) \
        if kind == "general" else []

    # 부채비율
    eq = a["equity"]
    if eq is not None and eq <= 0:
        dr, dr_reason = None, "자본총계가 0 이하(완전자본잠식)라 부채비율이 뜻을 잃습니다"
    elif kind == "financial":
        dr, dr_reason = None, fin_reason
    else:
        dr = _ratio(a["liabilities"], eq)
        dr_reason = "" if dr is not None else "부채총계 · 자본총계 칸이 없어 셀 수 없습니다"
    trend = [h for h in _history(annual_asc, lambda x: _ratio(x["liabilities"], x["equity"])
                                 if (x["equity"] or 0) > 0 else None)][-(TREND_YEARS + 1):]
    trend_point = []
    if len(trend) >= 2:
        trend_point = [f"사업보고서 기준 {trend[0]['period_end'][:4]}년 {trend[0]['value']:,.0f}% → "
                       f"{trend[-1]['period_end'][:4]}년 {trend[-1]['value']:,.0f}%"]
    metrics.append(_metric(
        "debt_ratio", "부채비율", dr, "%", lb, "부채총계 ÷ 자본총계 × 100",
        {"부채총계": a["liabilities"], "자본총계": eq},
        f"부채비율은 {dr:,.0f}% — 자본 1원마다 부채가 {dr / 100:,.2f}원입니다." if dr is not None else "",
        ["재는 법: 부채총계 ÷ 자본총계 × 100 — 이자가 붙는 빚만이 아니라 미리 받은 돈 · 갚을 외상까지 모두 셉니다",
         "업종마다 크게 다릅니다 — 설비가 큰 업종은 높게 나오기 쉬워 같은 업종끼리 견줘야 뜻이 있습니다",
         "낮다고 늘 좋지는 않습니다 — 빚을 거의 쓰지 않아 자본이 남아도는 경우도 있습니다", *trend_point, *restated],
        reason=dr_reason))
    metrics[-1]["history"] = [] if kind == "financial" else _history(
        asc, lambda x: _ratio(x["liabilities"], x["equity"]) if (x["equity"] or 0) > 0 else None)

    # 자기자본비율
    er = _ratio(eq, a["assets"])
    metrics.append(_metric(
        "equity_ratio", "자기자본비율", er, "%", lb, "자본총계 ÷ 자산총계 × 100",
        {"자본총계": eq, "자산총계": a["assets"]},
        f"자기자본비율은 {er:,.0f}% — 자산 100원 가운데 {er:,.0f}원이 빚이 아닌 몫입니다." if er is not None else "",
        ["재는 법: 자본총계 ÷ 자산총계 × 100",
         "금융회사는 예금 · 보험 부채가 커서 일반 회사보다 아주 낮게 나옵니다 — 업종이 다른 회사와 견주지 마세요",
         *restated],
        reason="" if er is not None else "자본총계 · 자산총계 칸이 없어 셀 수 없습니다"))
    metrics[-1]["history"] = _history(asc, lambda x: _ratio(x["equity"], x["assets"]))

    # 자본잠식률
    cs = a["capital_stock"]
    if cs is None or eq is None or cs <= 0:
        imp, imp_sentence, imp_reason = None, "", "자본금 · 자본총계 칸이 없어 셀 수 없습니다"
    elif eq <= 0:
        imp, imp_sentence, imp_reason = 100.0, "완전자본잠식 — 자본총계가 0 이하입니다(부채가 자산보다 많습니다).", ""
    elif eq < cs:
        imp = (cs - eq) / cs * 100
        imp_sentence, imp_reason = f"자본잠식률 {imp:,.0f}% — 쌓인 손실이 자본금의 {imp:,.0f}%를 깎았습니다.", ""
    else:
        imp, imp_sentence, imp_reason = 0.0, "자본잠식이 없습니다 — 자본총계가 자본금보다 큽니다.", ""
    metrics.append(_metric(
        "impairment", "자본잠식률", imp, "%", lb, "(자본금 − 자본총계) ÷ 자본금 × 100 · 자본총계가 자본금보다 클 때 0",
        {"자본금": cs, "자본총계": eq}, imp_sentence,
        ["재는 법: (자본금 − 자본총계) ÷ 자본금 × 100",
         "거래소는 자본잠식을 관리종목 지정 · 상장폐지 심사 기준 가운데 하나로 씁니다(시장 · 시기마다 세부 기준이 다릅니다)",
         "자본잠식이 없어도 손실이 이어지면 줄어들 수 있습니다 — 영업이익 줄을 함께 보세요", *restated],
        reason=imp_reason))

    # 영업이익 — 사업보고서 해마다(그림의 막대)
    ops = [{"bsns_year": p.get("bsns_year"), "period_end": p.get("period_end"), **{
        k: accounts_of(p)[k] for k in ("revenue", "operating_income")}} for p in annual_asc]
    streak = 0
    for o in reversed(ops):
        if o["operating_income"] is not None and o["operating_income"] < 0:
            streak += 1
        else:
            break

    # Altman Z'' — 사업보고서 해마다 · 가장 최근 해가 머리 숫자
    z_hist = []
    for p in annual_asc:
        if kind_of(p) != "general":
            continue
        z, _x, _r = z_score(accounts_of(p))
        if z is not None:
            z_hist.append({"period_end": p.get("period_end"), "bsns_year": p.get("bsns_year"), "value": round(z, 2),
                           "zone": zone_of(z)})
    zinfo: Dict = {"value": None, "zone": None, "zone_label": None, "x": None, "basis": None, "history": z_hist,
                   "formula": "6.56 × X1 + 3.26 × X2 + 6.72 × X3 + 1.05 × X4",
                   "thresholds": {"low": Z_LOW, "high": Z_HIGH}}
    if not annual:
        zinfo["reason"] = "사업보고서 기간이 없어 셀 수 없습니다"
    elif kind != "general":
        zinfo["reason"] = fin_reason
    else:
        za = accounts_of(annual[0])
        z, x, why = z_score(za)
        if z is None:
            zinfo["reason"] = why
        else:
            zone = zone_of(z)
            zinfo.update({
                "value": round(z, 2), "zone": zone, "zone_label": ZONES[zone],
                "x": {k: round(v, 4) for k, v in x.items()}, "basis": _basis(annual[0]), "reason": "",
                "sentence": f"Altman Z'' 점수는 {z:.2f} — 모형이 정한 {ZONES[zone]}입니다({annual[0].get('bsns_year')}년 사업보고서).",
                "points": [
                    "재는 법: 6.56 × (운전자본 ÷ 자산) + 3.26 × (이익잉여금 ÷ 자산) + 6.72 × (영업이익 ÷ 자산) + 1.05 × (자본 ÷ 부채)",
                    f"이 모형을 만든 표본(미국 · 신흥국의 제조업이 아닌 회사)에서 부실로 간 회사는 주로 {Z_LOW:.2f} 아래에 있었습니다 — "
                    "이 회사의 앞날을 맞히는 값이 아닙니다",
                    *_near_edge(z),
                    "높은 구간이어도 업황 · 차입 조건이 바뀌면 달라집니다 — 해마다의 흐름을 함께 보세요",
                    "영업이익을 이자 · 세금 전 이익(EBIT) 대신 씁니다 — 우리 자료에 이자비용이 없습니다",
                    *_restated_point(annual[0])],
            })

    checks = _checks(kind, a, annual_asc, ops, streak, fin_reason)
    unavailable = [
        {"key": "interest_coverage", "label": "이자보상배율",
         "reason": "영업이익으로 이자를 몇 번 갚을 수 있는지 보는 값인데, 우리 주요계정 자료에 이자비용이 없습니다"},
        {"key": "ocf_to_debt", "label": "영업현금흐름 ÷ 부채",
         "reason": "장사로 번 현금으로 빚을 얼마나 덮는지 보는 값인데, 우리 주요계정 자료에 현금흐름표가 없습니다"},
    ]
    return {
        "market": MARKET, "symbol": data.get("symbol"), "name": name, "exchange": exchange,
        "corp_code": data.get("corp_code"), "fs": data.get("fs"), "fs_note": fs_note,
        "as_of": as_of, "kind": kind, "kind_note": "" if kind == "general" else fin_reason,
        "latest": lb, "metrics": metrics, "zscore": zinfo, "operating": {"history": ops, "loss_streak": streak},
        "checks": checks, "unavailable": unavailable,
        "summary": {"pass": sum(c["status"] == "pass" for c in checks), "fail": sum(c["status"] == "fail" for c in checks),
                    "unknown": sum(c["status"] == "unknown" for c in checks), "total": len(checks)},
        "source": SOURCE, "notice": NOTICE,
    }


def won(v: Optional[int]) -> str:
    """원 → 읽는 꼴(조원 · 억원) — 점검 까닭 글에 날숫자(379,711,982,000,000)를 쓰지 않는다(2026-10-13 화면 확인)."""
    if v is None:
        return "—"
    a = abs(v)
    if a >= 10 ** 12:
        return f"{v / 10 ** 12:,.1f}조원"
    if a >= 10 ** 8:
        return f"{v / 10 ** 8:,.0f}억원"
    return f"{v:,}원"


def _check(key: str, label: str, status: str, reason: str) -> Dict:
    return {"key": key, "label": label, "status": status, "reason": reason}


def _checks(kind: str, a: Dict, annual_asc: List[Dict], ops: List[Dict], streak: int, fin_reason: str) -> List[Dict]:
    out = []
    ca, cl, ncl = a["current_assets"], a["current_liabilities"], a["noncurrent_liabilities"]
    if kind != "general" or ca is None or cl is None:
        out.append(_check("short_term", "1년 안에 갚을 빚을 1년 안에 돈이 되는 자산으로 덮나", "unknown", fin_reason))
    else:
        out.append(_check("short_term", "1년 안에 갚을 빚을 1년 안에 돈이 되는 자산으로 덮나", "pass" if ca >= cl else "fail",
                          f"유동자산 {won(ca)} {'≥' if ca >= cl else '<'} 유동부채 {won(cl)}"))
    if kind != "general" or ca is None or ncl is None:
        out.append(_check("long_term", "1년 넘어 갚을 빚도 유동자산으로 덮나", "unknown", fin_reason))
    else:
        out.append(_check("long_term", "1년 넘어 갚을 빚도 유동자산으로 덮나", "pass" if ca >= ncl else "fail",
                          f"유동자산 {won(ca)} {'≥' if ca >= ncl else '<'} 비유동부채 {won(ncl)}"))
    dr = [(p.get("period_end", "")[:4], _ratio(accounts_of(p)["liabilities"], accounts_of(p)["equity"]))
          for p in annual_asc if (accounts_of(p)["equity"] or 0) > 0]
    dr = [x for x in dr if x[1] is not None][-(TREND_YEARS + 1):]
    if kind == "financial" or len(dr) < 2:
        out.append(_check("debt_trend", f"부채비율이 {TREND_YEARS}년 전보다 줄었나", "unknown",
                          fin_reason if kind == "financial" else "사업보고서가 두 해 이상 있어야 견줄 수 있습니다"))
    else:
        (y0, d0), (y1, d1) = dr[0], dr[-1]
        out.append(_check("debt_trend", f"부채비율이 {TREND_YEARS}년 전보다 줄었나", "pass" if d1 < d0 else "fail",
                          f"{y0}년 {d0:,.0f}% → {y1}년 {d1:,.0f}%"))
    cs, eq = a["capital_stock"], a["equity"]
    if cs is None or eq is None:
        out.append(_check("no_impairment", "자본잠식이 없나", "unknown", "자본금 · 자본총계 칸이 없습니다"))
    else:
        out.append(_check("no_impairment", "자본잠식이 없나", "pass" if eq >= cs else "fail",
                          f"자본총계 {won(eq)} {'≥' if eq >= cs else '<'} 자본금 {won(cs)}"))
    last = ops[-1] if ops else None
    if not last or last["operating_income"] is None:
        out.append(_check("operating_profit", "가장 최근 사업연도에 영업이익을 냈나", "unknown", "사업보고서의 영업이익 칸이 없습니다"))
    else:
        oi = last["operating_income"]
        why = f"{last['bsns_year']}년 영업이익 {won(oi)}"
        if streak >= 2:
            why += f" · {streak}년 이어 영업손실"
        out.append(_check("operating_profit", "가장 최근 사업연도에 영업이익을 냈나", "pass" if oi > 0 else "fail", why))
    out.append(_check("interest_coverage", "영업이익으로 이자를 넉넉히 갚나", "unknown",
                      "우리 주요계정 자료에 이자비용이 없습니다(전체 재무제표 수집 뒤 계산)"))
    out.append(_check("ocf_coverage", "장사로 번 현금으로 빚을 덮나", "unknown",
                      "우리 주요계정 자료에 현금흐름표가 없습니다(전체 재무제표 수집 뒤 계산)"))
    return out
