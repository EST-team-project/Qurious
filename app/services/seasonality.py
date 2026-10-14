"""계절성 분석 — 달 · 요일 · 연말 창의 과거 수익률을 숫자 · 표 · 쉬운 말로 (API-SEAS-01 · 금융 필수 지식 › 계절성 · 2026-10-14).

왜 새로 쓰나
-----------
강사님 화면(`app/services/ml_models.py` 의 `seasonality_analysis`)은 **일간 수익률을 달별로 평균**만 냈다. 그래서
① 「1월 +0.08%」 가 하루 평균인지 한 달 수익률인지 헷갈리고 ② 해마다 몇 번 그랬는지(일관성)가 없고 ③ 12달을 한꺼번에
견줄 때 우연히 두드러지는 달을 거르지 않았고 ④ 「과거 패턴은 예측이 아니다」 가 없었다. 여기서는 **달 수익률(달 끝 → 달 끝)**
을 해마다 표로 두고, 달마다 오른 해 · 평균 · 가운데 값 · 나머지 달과의 차이 · 보정한 p 값을 계산해 **문장까지 서버 한 곳**에서
만든다(화면은 다시 계산하지 않는다 — 기준값도 응답 `thresholds` · `definitions` 에서 읽는다).

대상과 자료
-----------
- 시장 — 코스피(1995-01-03 ~) · 코스닥(2003-01-02 ~): 한국은행 ECOS 「1.5.1.1. 주식시장(일)」(802Y001) **가격 지수**.
  수집기 `collector/ecos.py` 의 `INDEX_SERIES` 가 매일 받는다(항목 표는 TC-SE-01 이 수집기와 맞춘다 — 앱 이미지엔 collector/ 가 없다).
  배당이 빠진 지수라 총수익을 달라 해도 가격으로 계산하고 그 사실을 `basis_note` 글로 알린다(말없이 바꾸지 않는다).
- 종목 — 수집 시세로 우리가 만든 지수(`price_total_return` — `tr_index` 총수익 · 세전 배당 재투자 / `pr_index` 가격).
  2020-01-02 부터라 달마다 관측이 6 ~ 7개뿐 → 「표본이 작다」 문장을 붙인다(`SHORT_YEARS`).

정의(응답 `definitions` 와 같은 글)
----------------------------------
- 달 수익률 = 그달 마지막 거래일 값 ÷ 앞달 마지막 거래일 값 − 1. 첫 달(앞달 없음) · 아직 끝나지 않은 달 · 앞달이 빈 달은 세지 않는다
  (강사님 교재 「거시경제와 주식시장 읽기」 의 「완료된 달만」 과 같은 규칙 — 우리 자료로 다시 계산).
- 요일 수익률 = 그날 값 ÷ 앞 거래일 값 − 1 (월요일은 주말을 건넌다).
- 「뚜렷한 달(요일)」 = 그 달과 나머지 달의 평균 차이를 **웰치 t 검정**으로 본 p 값을 12달(요일은 5요일) **홀름 보정**한 값이
  `ALPHA` 미만. 보정하는 까닭 — 여럿을 한꺼번에 견주면 우연히 하나쯤은 「유의」 해 보인다(Sullivan · Timmermann · White,
  calendar effects 의 데이터 마이닝 함정). 홀름은 가장 작은 p 부터 (남은 비교 수)배 하고 앞 값보다 작아지지 않게 한다.
  한계 — 「하나 vs 나머지」 라 한 달(요일)이 아주 크게 다르면 다른 달의 「나머지」 평균도 끌려 그 달까지 뚜렷해 보일 수 있다
  (가짜 자료 실측: 하루 잡음 1% 위 월요일 −0.3% 면 씨앗 일곱 중 다섯에서 다른 요일 하나가 함께 잡힘 · TC-SE-05). 실제 시장
  자료는 달 · 요일 차이가 잡음보다 훨씬 작아 드물다 — 화면 「읽는 법」 이 「나머지와 견준 것」 이라고 말한다.
- 산타 랠리 창 = 12월 마지막 5거래일 + 이듬해 1월 첫 2거래일 — 창 앞 거래일 종가에서 1월 둘째 거래일 종가까지(7거래일 ·
  정의는 강사님 교재 「산타 랠리」 절). 견줄 기준 = 같은 길이의 모든 7거래일 구간(겹침이 있어 검정 없이 기술 통계로만 견준다).
- 연말 두 달 = 11 · 12월 달 수익률 평균 vs 나머지 열 달 평균(강사님 화면의 「연말 효과」 를 달 수익률로 다시).
- 반년 비교 = 11 ~ 4월(겨울 반년) vs 5 ~ 10월(여름 반년) 달 수익률 평균 — 강사님 화면 카드의 「Sell in May(5월에 팔고 떠나라)」
  를 말로만 두지 않고 우리 자료로 견준다(Bouman · Jacobsen 2002 「핼러윈 효과」 와 같은 나눔). 연말 두 달과 함께 **미리 정해 둔
  한 번의 비교**라 보정하지 않지만, 여러 계절 규칙을 찾아본 가운데 하나라는 점을 문장이 함께 말한다.
- 한 해 흐름(곡선) = 해마다 1월부터 그달까지 쌓은 수익률. 평균 선은 1월 값이 있는 해만의 평균(첫 해처럼 2월부터인 해는 출발점이
  달라 선만 그리고 평균에서 뺀다).

화면(`public/js/seasonal.js`)은 고르기 값(`choices`) · 판정 글(`distinct_text` · `judge_text`)도 응답에서 읽는다 — 화면 코드에
값을 따로 적지 않는다(TC-SES 화면 시험이 지킨다).

읽기만 한다 — 수집 DB 는 `?mode=ro` 로 연다(TC-SE-11). 일반 사용자 답에는 표 이름 · 명령을 싣지 않고 관리자에게만 할 일을 준다.
"""
from __future__ import annotations

import math
import re
import sqlite3
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from app.services import collector_db

KST = timezone(timedelta(hours=9))

#: 한국은행 ECOS 통계표 「1.5.1.1. 주식시장(일)」 — 수집기 `collector.ecos.INDEX_STAT` 와 같다(TC-SE-01).
INDEX_STAT = "802Y001"
#: 이용약관 제7조② 「ECOS 에서 제공된 정보임을 표시」 — 수집기 `ATTRIBUTION` 과 같은 글.
ATTRIBUTION_ECOS = "한국은행 경제통계시스템(ECOS)"
ATTRIBUTION_STOCK = "공공데이터포털 주식시세정보(금융위원회) · 총수익 지수는 배당 공시로 우리가 계산"
#: (열쇠, ECOS 항목 코드, 화면 이름) — 수집기 `INDEX_SERIES` 의 열쇠(대문자) · 코드와 같다.
MARKETS: Tuple[Tuple[str, str, str], ...] = (
    ("KOSPI", "0001000", "코스피"),
    ("KOSDAQ", "0089000", "코스닥"),
)
ALPHA = 0.05
#: 자료가 이 햇수보다 짧으면 「표본이 작다」 문장을 붙인다.
SHORT_YEARS = 10
#: 관측이 이보다 적은 달(요일)은 「뚜렷한가」 를 판정하지 않는다(distinct = None · 홀름 비교 수에서도 뺀다).
#: 2026-10-14 실측 — 삼성전자 8월은 7해 모두 내려 홀름 보정 p 0.0065 였다. 관측 7개의 t 검정은 정규성 가정에 기대는데
#: 같은 응답이 「표본이 작다」 고 말하면 서로 어긋난다 → 판정을 미루고 그 사실을 문장으로 알린다(말없는 판단 금지).
MIN_TEST_N = 10
SANTA_DEC_DAYS = 5
SANTA_JAN_DAYS = 2
MONTH_LABELS = [f"{m}월" for m in range(1, 13)]
WEEKDAY_LABELS = ["월", "화", "수", "목", "금"]
BASES = {"tr": "총수익(배당 재투자 · 세전)", "pr": "가격(배당 제외)"}
#: 화면 단추 글(짧게) — 차례가 곧 단추 차례
BASIS_CHOICES: Tuple[Tuple[str, str], ...] = (("tr", "배당 포함"), ("pr", "가격만"))
#: 「뚜렷한가」 세 갈래의 화면 글 — None 은 관측이 MIN_TEST_N 보다 적어 판정하지 않은 칸
DISTINCT_TEXT = {True: "뚜렷", False: "뚜렷하지 않음", None: "판정 안 함"}
#: 반년 비교의 달 칸(0 = 1월) — 겨울 반년 11 ~ 4월 · 여름 반년 5 ~ 10월
WINTER_MONTHS = (10, 11, 0, 1, 2, 3)
SUMMER_MONTHS = (4, 5, 6, 7, 8, 9)
NOTICE = "과거 수익률은 앞으로의 수익을 보장하지 않습니다. 투자 권유가 아닙니다."
DEFINITIONS = {
    "month_return": "그달 마지막 거래일 값 ÷ 앞달 마지막 거래일 값 − 1 (끝난 달만 셉니다)",
    "weekday_return": "그날 값 ÷ 앞 거래일 값 − 1 (월요일은 주말을 건넙니다)",
    "distinct": "그 달(요일)과 나머지의 평균 차이를 웰치 t 검정으로 보고, 12달(5요일)을 한꺼번에 견준 만큼 "
                f"홀름 방식으로 기준을 엄격하게 한 값이 유의수준보다 작을 때 — 관측이 {MIN_TEST_N}개보다 적으면 판정하지 않습니다",
    "santa": f"12월 마지막 {SANTA_DEC_DAYS}거래일 + 이듬해 1월 첫 {SANTA_JAN_DAYS}거래일 — "
             f"창 앞 거래일 종가에서 1월 {SANTA_JAN_DAYS}번째 거래일 종가까지",
    "baseline": f"같은 길이({SANTA_DEC_DAYS + SANTA_JAN_DAYS}거래일)의 모든 구간 — 겹치는 구간이라 검정 없이 견줍니다",
    "year_end": "11 · 12월 달 수익률 평균 vs 나머지 열 달 평균",
    "halves": "11 ~ 4월(겨울 반년) 달 수익률 평균 vs 5 ~ 10월(여름 반년) — 「5월에 팔고 떠나라」 를 달 수익률로 견줍니다",
    "curve": "해마다 1월부터 그달까지 쌓은 수익률 — 평균 선은 1월 값이 있는 해만의 평균입니다",
    "judge": f"웰치 t 검정 p 값이 유의수준({ALPHA * 100:.0f}%)보다 작으면 「우연으로 보기 어려운 차이」 — 미리 정한 비교 한 번이라 보정하지 않습니다",
}

_CODE = re.compile(r"^(\d{6})(?:\.(?:KS|KQ))?$")
_USER_DB_DOWN = "시세 자료를 지금 읽을 수 없습니다. 잠시 뒤 다시 시도해 주세요."


class SeasonalityError(Exception):
    """상태 코드 + 사람에게 보일 글 + 관리자에게만 줄 할 일."""

    def __init__(self, status: int, message: str, hint: str = ""):
        super().__init__(message)
        self.status = status
        self.message = message
        self.hint = hint

    def detail(self, admin: bool) -> Dict:
        out: Dict = {"message": self.message}
        if admin and self.hint:
            out["admin_hint"] = self.hint
        return out


# ══════════════════════════════════════════════════════════════════
# 1. 계산 — DB 없는 순수 함수(시험이 직접 부른다)
# ══════════════════════════════════════════════════════════════════

def _prev_ym(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def monthly_matrix(series: Sequence[Tuple[str, float]], today: Optional[date] = None) -> Dict:
    """해마다 열두 칸의 달 수익률(소수 — 0.05 = +5%). 정렬된 (YYYY-MM-DD, 값) 을 받는다.

    첫 달 · 아직 끝나지 않은 달(마지막 값의 달이 오늘의 달과 같거나 뒤) · 앞달이 빈 달은 None.
    """
    today = today or datetime.now(KST).date()
    ends: Dict[str, float] = {}
    for d, v in series:
        ends[d[:7]] = v                      # 정렬된 입력 — 그달의 마지막 값이 남는다
    months = sorted(ends)
    open_month = series[-1][0][:7] if series and series[-1][0][:7] >= today.strftime("%Y-%m") else None
    rows: Dict[int, List[Optional[float]]] = {}
    done: List[str] = []
    for ym in months[1:]:
        prev = _prev_ym(ym)
        if ym == open_month or prev not in ends:
            continue
        rows.setdefault(int(ym[:4]), [None] * 12)[int(ym[5:7]) - 1] = ends[ym] / ends[prev] - 1
        done.append(ym)
    if series:                               # 값이 하나도 없는 해도 표에 줄로 보이게(첫 해 1월 등)
        for y in range(int(series[0][0][:4]), int(series[-1][0][:4]) + 1):
            rows.setdefault(y, [None] * 12)
    return {"rows": dict(sorted(rows.items())), "months": len(done),
            "first": done[0] if done else None, "last": done[-1] if done else None}


def holm(ps: Sequence[Optional[float]]) -> List[Optional[float]]:
    """홀름 보정 — 작은 p 부터 (남은 비교 수)배 · 앞 값보다 작아지지 않게 · 1 을 넘지 않게. None 은 그대로(셀 수 없는 칸)."""
    idx = [i for i, p in enumerate(ps) if p is not None]
    m = len(idx)
    out: List[Optional[float]] = [None] * len(ps)
    running = 0.0
    for rank, i in enumerate(sorted(idx, key=lambda k: ps[k])):  # type: ignore[arg-type, return-value]
        running = max(running, min(1.0, (m - rank) * ps[i]))     # type: ignore[operator]
        out[i] = running
    return out


def _welch_p(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    """두 묶음의 평균 차이 — 웰치 t 검정 p 값(분산이 달라도 됨). 셀 수 없으면 None."""
    if len(a) < 2 or len(b) < 2:
        return None
    from scipy import stats  # 무거운 import 는 쓸 때만

    p = float(stats.ttest_ind(list(a), list(b), equal_var=False).pvalue)
    return None if math.isnan(p) else p


def _group_stats(groups: List[List[Tuple[int, float]]], labels: List[str], key: str) -> List[Dict]:
    """묶음(달 · 요일)마다 n · 평균 · 가운데 · 표준편차 · 오른/내린 수 · 나머지와의 차이 · p · 홀름 보정 p · 뚜렷함."""
    out: List[Dict] = []
    ps: List[Optional[float]] = []
    for i, g in enumerate(groups):
        vals = [v for _t, v in g]
        others = [v for k, gg in enumerate(groups) if k != i for _t, v in gg]
        p = _welch_p(vals, others) if len(vals) >= MIN_TEST_N else None   # 판정하지 않는 칸은 홀름 비교 수에서도 빠진다
        ps.append(p)
        row: Dict = {key: i + 1, "label": labels[i], "n": len(vals), "mean": None, "median": None, "std": None,
                     "up": 0, "down": 0, "hit_rate": None, "diff_vs_others": None, "best": None, "worst": None,
                     "p_value": p}
        if vals:
            up = sum(1 for v in vals if v > 0)
            best = max(g, key=lambda t: t[1])
            worst = min(g, key=lambda t: t[1])
            row.update(mean=statistics.fmean(vals), median=statistics.median(vals),
                       std=statistics.stdev(vals) if len(vals) > 1 else None, up=up,
                       down=sum(1 for v in vals if v < 0), hit_rate=round(up / len(vals) * 100, 1),
                       diff_vs_others=statistics.fmean(vals) - statistics.fmean(others) if others else None,
                       best={"year": best[0], "ret": best[1]}, worst={"year": worst[0], "ret": worst[1]})
        out.append(row)
    for row, adj in zip(out, holm(ps)):
        row["p_adjusted"] = adj
        row["distinct"] = None if adj is None else adj < ALPHA          # None = 판정하지 않음(관측 부족)
    return out


def month_stats(rows: Dict[int, List[Optional[float]]]) -> List[Dict]:
    """열두 달 — 달마다 해(年)별 값으로 통계(best · worst 의 year 는 그 해)."""
    groups = [[(y, r[m]) for y, r in rows.items() if r[m] is not None] for m in range(12)]
    return _group_stats(groups, MONTH_LABELS, "month")  # type: ignore[arg-type]


def daily_returns(series: Sequence[Tuple[str, float]]) -> List[Tuple[str, float]]:
    return [(d, v / pv - 1) for (_pd, pv), (d, v) in zip(series, series[1:])]


def weekday_stats(series: Sequence[Tuple[str, float]]) -> List[Dict]:
    """다섯 요일 — 그날 값 ÷ 앞 거래일 값 − 1. best · worst 의 year 칸에는 그 날의 순번(0 부터)이 든다(화면은 쓰지 않는다)."""
    groups: List[List[Tuple[int, float]]] = [[] for _ in range(5)]
    for i, (d, r) in enumerate(daily_returns(series)):
        wd = date.fromisoformat(d).weekday()
        if wd < 5:
            groups[wd].append((i, r))
    return _group_stats(groups, WEEKDAY_LABELS, "weekday")


def santa_windows(series: Sequence[Tuple[str, float]]) -> Dict:
    """산타 랠리 창 — 해마다 (창 앞 거래일 → 1월 둘째 거래일) 수익률 · 요약 · 같은 길이 아무 구간(기준)."""
    val = dict(series)
    by_ym: Dict[str, List[str]] = {}
    for d, _v in series:
        by_ym.setdefault(d[:7], []).append(d)
    years: List[Dict] = []
    for ym, dec in sorted(by_ym.items()):
        if ym[5:] != "12":
            continue
        y = int(ym[:4])
        jan = by_ym.get(f"{y + 1}-01", [])
        if len(dec) < SANTA_DEC_DAYS + 1 or len(jan) < SANTA_JAN_DAYS:
            continue                          # 창 앞 거래일이 12월 안에 없거나 1월 둘째 거래일이 아직 없다
        start, end = dec[-(SANTA_DEC_DAYS + 1)], jan[SANTA_JAN_DAYS - 1]
        years.append({"year": y, "from": start, "to": end, "ret": val[end] / val[start] - 1})
    rets = [r["ret"] for r in years]
    span = SANTA_DEC_DAYS + SANTA_JAN_DAYS
    base = [series[i + span][1] / series[i][1] - 1 for i in range(len(series) - span)]
    return {
        "years": years,
        "stats": {"n": len(rets), "up": sum(1 for r in rets if r > 0),
                  "mean": statistics.fmean(rets) if rets else None,
                  "median": statistics.median(rets) if rets else None,
                  "hit_rate": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1) if rets else None},
        "baseline": {"days": span, "n": len(base), "mean": statistics.fmean(base) if base else None,
                     "hit_rate": round(sum(1 for r in base if r > 0) / len(base) * 100, 1) if base else None},
    }


def year_end(rows: Dict[int, List[Optional[float]]]) -> Dict:
    """11 · 12월 달 수익률 평균 vs 나머지 열 달 — 웰치 p(두 묶음 하나의 비교라 보정 없음)."""
    ye = [r[m] for r in rows.values() for m in (10, 11) if r[m] is not None]
    other = [r[m] for r in rows.values() for m in range(10) if r[m] is not None]
    return {"n_months": len(ye), "mean": statistics.fmean(ye) if ye else None,
            "other_mean": statistics.fmean(other) if other else None,
            "diff": statistics.fmean(ye) - statistics.fmean(other) if ye and other else None,
            "p_value": _welch_p(ye, other)}


def halves(rows: Dict[int, List[Optional[float]]]) -> Dict:
    """11 ~ 4월(겨울 반년) vs 5 ~ 10월(여름 반년) 달 수익률 평균 — 웰치 p(미리 정한 한 번의 비교라 보정 없음)."""
    win = [r[m] for r in rows.values() for m in WINTER_MONTHS if r[m] is not None]
    summer = [r[m] for r in rows.values() for m in SUMMER_MONTHS if r[m] is not None]
    return {"n_winter": len(win), "n_summer": len(summer),
            "winter_mean": statistics.fmean(win) if win else None,
            "summer_mean": statistics.fmean(summer) if summer else None,
            "diff": statistics.fmean(win) - statistics.fmean(summer) if win and summer else None,
            "p_value": _welch_p(win, summer)}


def year_paths(rows: Dict[int, List[Optional[float]]]) -> Dict:
    """해마다 1월부터 쌓은 수익률 경로(소수) · 달마다 평균 · 그 평균에 든 해 수.

    그해 첫 값부터 쌓고, 시작한 뒤 빈 달을 만나면 거기서 끊는다(끊긴 뒤를 이어 쌓으면 빠진 달이 0% 로 숨는다).
    평균은 1월 값이 있는 해만 — 2월부터 시작한 해(자료의 첫 해)는 출발점이 달라 선만 그린다.
    """
    years: List[Dict] = []
    for y, r in rows.items():
        path: List[Optional[float]] = []
        c, started, broken = 1.0, False, False
        for v in r:
            if v is None:
                broken = broken or started
                path.append(None)
                continue
            if broken:
                path.append(None)
                continue
            started = True
            c *= 1 + v
            path.append(c - 1)
        if started:
            years.append({"year": y, "path": path, "from_jan": r[0] is not None})
    mean: List[Optional[float]] = []
    n: List[int] = []
    for m in range(12):
        vals = [yy["path"][m] for yy in years if yy["from_jan"] and yy["path"][m] is not None]
        n.append(len(vals))
        mean.append(statistics.fmean(vals) if vals else None)
    return {"years": years, "mean": mean, "n": n}


def judge_text(p: Optional[float]) -> str:
    """미리 정한 한 번의 비교(연말 두 달 · 반년)의 화면 글 — 판정 기준은 ALPHA 한 곳."""
    if p is None:
        return "견줄 관측이 모자랍니다"
    return "우연으로 보기 어려운 차이" if p < ALPHA else "우연으로도 생길 만한 차이"


def choices() -> Dict:
    """화면의 고르기 값 — 화면 코드에 값을 따로 적지 않는다(TC-SES 화면 시험). 기본은 각 목록의 첫 칸."""
    return {"markets": [{"key": k, "label": n} for k, _item, n in MARKETS],
            "stock": {"label": "종목", "placeholder": "종목 이름 · 6자리 코드"},
            "bases": [{"key": k, "label": label} for k, label in BASIS_CHOICES]}


# ══════════════════════════════════════════════════════════════════
# 2. 문장 — 서버 한 곳(화면은 그대로 보인다)
# ══════════════════════════════════════════════════════════════════

def _span_text(months: int) -> str:
    y, m = divmod(months, 12)
    return f"{y}년 {m}개월" if y and m else (f"{y}년" if y else f"{m}개월")


def sentences(name: str, basis: str, mm: Dict, months: List[Dict], santa: Dict, hv: Optional[Dict] = None) -> List[str]:
    out: List[str] = []
    fy, fm = mm["first"].split("-")
    ly, lm = mm["last"].split("-")
    out.append(f"{name} · {int(fy)}년 {int(fm)}월 ~ {int(ly)}년 {int(lm)}월의 끝난 달 {mm['months']}개"
               f"({_span_text(mm['months'])})를 {BASES[basis]} 기준으로 셌습니다.")
    seen = [m for m in months if m["n"]]
    if seen:
        best = max(seen, key=lambda m: m["mean"])
        worst = min(seen, key=lambda m: m["mean"])
        out.append(f"평균으로는 {best['label']}이 가장 높고({best['mean'] * 100:+.2f}%) "
                   f"{worst['label']}이 가장 낮습니다({worst['mean'] * 100:+.2f}%).")
        if best["down"]:
            out.append(f"하지만 {best['label']}에도 {best['n']}해 가운데 {best['down']}해는 내렸습니다"
                       f"(오른 해 {best['up']}번 · {best['hit_rate']:.0f}%).")
        else:
            out.append(f"{best['label']}은 {best['n']}해 모두 올랐지만, 다음 해도 그렇다는 보장은 없습니다.")
    distinct = [m for m in months if m["distinct"]]
    if any(m["distinct"] is not None for m in months):
        out.append("12달을 한꺼번에 견주면 우연히 한두 달은 두드러져 보입니다. 이를 감안한 기준"
                   f"(홀름 보정 · 유의수준 {ALPHA * 100:.0f}%)으로 다른 달과 뚜렷이 다른 달은 "
                   + (f"{len(distinct)}개({', '.join(m['label'] for m in distinct)})입니다." if distinct else "없습니다."))
    else:
        out.append(f"달마다 관측이 {MIN_TEST_N}해보다 적어 「다른 달과 뚜렷이 다른가」 는 판정하지 않았습니다 — "
                   "평균과 오른 해 수만 보세요.")
    st, bl = santa["stats"], santa["baseline"]
    if st["n"]:
        out.append(f"산타 랠리 창(12월 마지막 {SANTA_DEC_DAYS}거래일 + 이듬해 1월 첫 {SANTA_JAN_DAYS}거래일)은 "
                   f"{st['n']}번 가운데 {st['up']}번 올랐고 평균 {st['mean'] * 100:+.2f}%입니다. "
                   f"아무 때나 고른 {bl['days']}거래일은 평균 {bl['mean'] * 100:+.2f}% · 오른 비율 {bl['hit_rate']:.0f}%였습니다.")
    if hv and hv["winter_mean"] is not None and hv["summer_mean"] is not None:
        tail = ("한 번만 견준 차이로는 우연으로 보기 어렵지만, 여러 계절 규칙을 찾아본 가운데 하나라는 점을 감안해야 합니다."
                if hv["p_value"] is not None and hv["p_value"] < ALPHA else "우연으로도 생길 만한 차이입니다.")
        out.append(f"「5월에 팔고 떠나라」 를 견주면 11 ~ 4월의 달 평균은 {hv['winter_mean'] * 100:+.2f}%, "
                   f"5 ~ 10월은 {hv['summer_mean'] * 100:+.2f}%입니다 — {tail}")
    if mm["months"] < SHORT_YEARS * 12 and seen:
        ns = [m["n"] for m in seen]
        out.append(f"자료가 {_span_text(mm['months'])}뿐이라 달마다 관측이 {min(ns)} ~ {max(ns)}개입니다 — "
                   "이 정도 표본으로는 우연과 구별하기 어렵습니다.")
    out.append("과거에 그랬다는 관찰일 뿐 앞으로도 그렇다는 신호가 아닙니다. "
               "계절보다 그때의 금리 · 실적 · 수급 같은 변수가 값을 더 크게 움직입니다.")
    return out


# ══════════════════════════════════════════════════════════════════
# 3. 읽기 — 수집 DB(읽기 전용) → 응답
# ══════════════════════════════════════════════════════════════════

def parse_target(raw: str) -> Tuple[str, str]:
    t = (raw or "").strip().upper()
    for key, _item, _name in MARKETS:
        if t == key:
            return "market", key
    m = _CODE.match(t)
    if m:
        return "stock", m.group(1)
    raise SeasonalityError(422, "대상은 코스피 · 코스닥 또는 종목 단축코드 6자리입니다.")


def _open() -> sqlite3.Connection:
    path = collector_db.db_path()
    if path is None:
        raise SeasonalityError(503, _USER_DB_DOWN, "수집 DB 가 없다 — COLLECTOR_DB_PATH 또는 data/collector/market.sqlite3 "
                                                   "(python scripts/daily_update.py status)")
    try:
        return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as e:
        raise SeasonalityError(503, _USER_DB_DOWN, f"수집 DB 를 열지 못했다: {e}") from None


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _market_series(conn: sqlite3.Connection, item: str) -> List[Tuple[str, float]]:
    if not _has_table(conn, "ecos_series"):
        return []
    rows = conn.execute("SELECT date, value FROM ecos_series WHERE stat_code=? AND item_code=? AND cycle='D' "
                        "AND value > 0 ORDER BY date", (INDEX_STAT, item)).fetchall()
    return [(d, float(v)) for d, v in rows]


_STOCK_COL = {"tr": "tr_index", "pr": "pr_index"}


def _stock_series(conn: sqlite3.Connection, code: str, basis: str):
    if not _has_table(conn, "price_total_return"):
        raise SeasonalityError(503, _USER_DB_DOWN, "price_total_return 표가 없다 — "
                                                   "python scripts/daily_update.py run --only total_return")
    col = _STOCK_COL[basis]                   # 고정된 두 칸 중 하나 — 사용자 글이 SQL 에 들어가지 않는다
    rows = conn.execute(f"SELECT bas_dt, {col} FROM price_total_return WHERE srtn_cd=? AND {col} > 0 ORDER BY bas_dt",
                        (code,)).fetchall()
    meta = None
    if _has_table(conn, "price_daily"):
        meta = conn.execute("SELECT itms_nm, mrkt_ctg FROM price_daily WHERE srtn_cd=? ORDER BY bas_dt DESC LIMIT 1",
                            (code,)).fetchone()
    return meta, [(f"{d[:4]}-{d[4:6]}-{d[6:8]}", float(v)) for d, v in rows]


def _pct(v: Optional[float], nd: int = 2) -> Optional[float]:
    return None if v is None else round(v * 100, nd)


def _pct_row(row: Dict) -> Dict:
    out = dict(row)
    for k in ("mean", "median", "std", "diff_vs_others"):
        out[k] = _pct(row[k])
    for k in ("best", "worst"):
        if row[k]:
            out[k] = {"year": row[k]["year"], "ret": _pct(row[k]["ret"])}
    for k in ("p_value", "p_adjusted"):
        out[k] = None if row.get(k) is None else round(row[k], 4)
    out["distinct_text"] = DISTINCT_TEXT[row.get("distinct")]
    return out


def _compare_out(d: Dict, keys: Tuple[str, ...]) -> Dict:
    """연말 두 달 · 반년 비교 — 평균은 % 로 · p 는 넷째 자리 · 화면 글(judge_text) 붙임."""
    out = dict(d)
    for k in keys:
        out[k] = _pct(d[k])
    out["p_value"] = None if d["p_value"] is None else round(d["p_value"], 4)
    out["judge_text"] = judge_text(d["p_value"])
    return out


def _unavailable(tgt: Dict, reason: str, source: str, admin: bool, hint: str) -> Dict:
    out = {"available": False, "target": tgt, "reason": reason, "source": source, "notice": NOTICE,
           "choices": choices()}
    if admin:
        out["admin_hint"] = hint
    return out


def read_seasonality(target: str, basis: str = "tr", admin: bool = False, today: Optional[date] = None) -> Dict:
    """`GET /api/seasonality` — 시장 지수(코스피 · 코스닥) 또는 종목의 달 · 요일 · 연말 창 계절성."""
    if basis not in BASES:
        raise SeasonalityError(422, "기준은 tr(총수익) 또는 pr(가격)입니다.")
    kind, code = parse_target(target)
    today = today or datetime.now(KST).date()
    conn = _open()
    try:
        if kind == "market":
            key, item, name = next(m for m in MARKETS if m[0] == code)
            tgt = {"kind": "market", "code": key, "name": name, "market": key}
            used = "pr"
            note = "시장 지수는 한국은행이 주는 가격 지수뿐이라 배당을 뺀 값입니다." if basis == "tr" else None
            source = ATTRIBUTION_ECOS
            series = _market_series(conn, item)
            if not series:
                return _unavailable(tgt, f"{name} 지수를 아직 받지 않았습니다. 다음 정기 수집 뒤에 다시 보세요.", source,
                                    admin, "python scripts/daily_update.py run --only ecos  (또는 python -m collector.ecos "
                                           "backfill — 키는 .env 의 ECOS_API_KEY)")
        else:
            meta, series = _stock_series(conn, code, basis)
            if not series:
                raise SeasonalityError(404, "수집 시세에 없는 종목입니다. 단축코드를 확인해 주세요.")
            tgt = {"kind": "stock", "code": code, "name": (meta[0] if meta and meta[0] else code),
                   "market": (meta[1] if meta and meta[1] else "")}
            used, note, source = basis, None, ATTRIBUTION_STOCK
    finally:
        conn.close()

    mm = monthly_matrix(series, today)
    if not mm["months"]:
        return _unavailable(tgt, "끝난 달이 아직 없어 계절성을 셀 수 없습니다.", source, admin,
                            "끝난 달이 0개 — 상장 직후이거나 자료가 한 달 안쪽이다")
    months = month_stats(mm["rows"])
    santa = santa_windows(series)
    ye = year_end(mm["rows"])
    hv = halves(mm["rows"])
    yp = year_paths(mm["rows"])
    return {
        "available": True,
        "target": tgt,
        "basis": used,
        "basis_label": BASES[used],
        "basis_note": note,
        "source": source,
        "as_of": series[-1][0],
        "span": {"first": mm["first"], "last": mm["last"], "months": mm["months"], "text": _span_text(mm["months"])},
        "definitions": DEFINITIONS,
        "thresholds": {"alpha": ALPHA, "method": "holm", "short_years": SHORT_YEARS, "min_test_n": MIN_TEST_N},
        "choices": choices(),
        "matrix": [{"year": y, "months": [_pct(v) for v in r]} for y, r in mm["rows"].items()],
        "by_month": [_pct_row(m) for m in months],
        "weekday": [_pct_row(w) for w in weekday_stats(series)],
        "curves": {
            "years": [{"year": r["year"], "from_jan": r["from_jan"], "path": [_pct(v) for v in r["path"]]} for r in yp["years"]],
            "mean": [_pct(v) for v in yp["mean"]],
            "n": yp["n"],
            "current_year": int(mm["last"][:4]),
        },
        "windows": {
            "santa": {
                "years": [{**r, "ret": _pct(r["ret"])} for r in santa["years"]],
                "stats": {**santa["stats"], "mean": _pct(santa["stats"]["mean"]), "median": _pct(santa["stats"]["median"])},
                "baseline": {**santa["baseline"], "mean": _pct(santa["baseline"]["mean"])},
            },
            "year_end": _compare_out(ye, ("mean", "other_mean", "diff")),
            "halves": _compare_out(hv, ("winter_mean", "summer_mean", "diff")),
        },
        "sentences": sentences(tgt["name"], used, mm, months, santa, hv),
        "notice": NOTICE,
    }
