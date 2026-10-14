"""상품 상세 창 — ETF 한 종목의 기간 그림 자료 · 요약 · 쉬운 말 문장 (수집 DB `etf_daily` 를 읽기만 · 2026-10-12 · 화면 키 `agent-products`)

왜 따로 두나
------------
목록(`product_etfs`)은 마지막 거래일의 1,172 종목을 한 번에 재고, 상세 창은 한 종목의 날짜별 계열을 기간마다 다시 잰다 —
읽는 범위(그날 전부 ↔ 한 종목 기간)와 캐시 열쇠가 달라 파일을 나눴다(SRP). 하루 수익률 규칙과 머리 숫자는 목록 것을
그대로 쓴다(SSoT — 아래 「지키는 것」).

무엇을 돌려주나
---------------
`chart(code, period)` — 기간(1개월 · 6개월 · 1년 · 3년) 동안의
- 날짜별 계열: 분배금을 되돌린 이음(`tr`) · 가격만(`px`) · 그날까지의 최고점(`peak`) · 낙폭 · NAV · 괴리율 · 기초지수
  (이음 값은 모두 시작 100) — 칩(얼마나 벌었나 · 가장 크게 잃은 때 · 왜 2배가 아닌가 …)이 같은 계열을 나눠 쓴다.
- 사건: 분배락(금액 근사) · 최대 낙폭의 고점 · 바닥 · 회복 · 가장 크게 오른 날 · 내린 날.
- 칩마다 요약 숫자와 **서버가 만든 글**(`explain` — 한 줄 요약 `sentence` + 근거 줄 `points`) — 부호는 낱말
  (「올랐습니다 · 내렸습니다」)로, 낼 수 없는 숫자는 빈칸 + 까닭으로. 글의 숫자는 요약 칸 숫자를 같은 자리에서 반올림한
  것이다(시험 TC-PCH).
- 레버리지 · 인버스는 세 값(기초지수 × 배수 · 날마다 배수로 다시 맞춘 값 · 실제 ETF)과 구조 · 비용 몫, 그리고
  요건 상수표의 위험 한 줄(고정 띠).

지키는 것
---------
- 머리 숫자(1년 수익률 · 1년 변동성 · 1년 최대 낙폭 · 괴리율)는 목록 줄과 **같은 값** — 목록 계산 결과의 그 종목 줄을
  그대로 싣는다(`product_etfs.find_item`). 기간 계열도 목록과 같은 하루 규칙(`product_etfs.chain_return`)으로 이어,
  1년 창이면 끝 값이 목록 1년 수익률 · 최대 낙폭과 같다(시험).
- 기초지수 비교는 같은 날 · 같은 통화일 때만 — 2026-10-12 실측(1년): 국내 지수 칸은 NAV 와 같은 날 상관 1.000
  (KODEX 200 기울기 0.999 · KODEX 레버리지 1.989 · 200선물인버스2X −2.001 — 기초지수는 1배 지수)이지만, 해외 지수 칸은
  하루 늦은 달러 값이다(TIGER 미국S&P500 같은 날 0.003 · 하루 밀면 0.608 · 나스닥100 0.855). 같은 날 상관이 문턱 아래이거나,
  기초지수 이름이 기간 중 바뀌거나(KODEX 미국S&P500 — TR 지수에서 가격지수로), 지수 종가가 빈 날이 있으면 세 값을 내지
  않고 까닭을 낸다(말없는 fallback 금지).
- 분배금은 근사 — 「직전 종가 − 그날 기준가(종가 − 전일 대비)」 가 0 보다 큰 날의 그 값이다. 기준가는 호가 단위로
  끊기므로 공시와 몇 원 다르다(2026-10-12 KODEX 200: 공시 446원 · 183원 ↔ 근사 445원 · 180원). 기준가가 직전 종가보다
  높은 날은 분배가 아니다(2024-09 뒤 258종목 511번 · 모두 정확히 3원 — 시세 자료의 꼴). 10% 를 넘는 차이는 분배가 아니라
  「다른 조정」(분할 등)으로 따로 센다(2024-09 뒤 가장 큰 분배 차이 7.68%).
- 하지 않는 것: 앞날 범위 · 목표 수익률 · 등급 · 매매 신호 문장 · 원자료 내려받기(공공누리 제4유형 — 목록과 같은 규칙).
- 수집 DB 는 `mode=ro` 로 한 종목만 색인(`ix_etf_srtn`)으로 읽는다(3년 733행 · 0.15 ~ 0.19초 실측).
"""
from __future__ import annotations

import logging
import math
import re
import sqlite3
import threading
from collections import OrderedDict
from datetime import timedelta
from pathlib import Path

from app.services import collector_db
from app.services import etp_requirements as etp
from app.services import product_etfs as pe

logger = logging.getLogger(__name__)

CODE_RE = re.compile(r"^[0-9A-Z]{6}$")
# 기간 키 → (기준일부터 거슬러 갈 날 수, 화면 이름) — 1년은 목록과 같은 날 수라야 끝 값이 목록 1년 수익률과 같다
PERIODS: dict[str, tuple[int, str]] = {
    "1m": (30, "1개월"),
    "6m": (182, "6개월"),
    "1y": (pe._YEAR_DAYS, "1년"),
    "3y": (1095, "3년"),
}
EXAMPLE_KRW = 1_000_000      # 예시 금액 — 「100만 원을 넣었다면」
DIST_MAX_PCT = 10.0          # 이보다 큰 기준가 차이는 분배가 아니라 다른 조정(분할 등)으로 센다
FIT_MIN_CORR = 0.95          # ETF 하루 수익률과 기초지수 하루 수익률의 같은 날 상관 — 이 아래면 세 값을 내지 않는다
FIT_MIN_DAYS = 20            # 상관을 잴 날이 이만큼 안 되면 세 값을 내지 않는다
PREMIUM_DAY_PCT = 1.0        # 「괴리율이 ±1% 를 넘은 날」 셈의 문턱
_CACHE_MAX = 32

# 한 종목 · 기간 — 색인 ix_etf_srtn(srtn_cd, bas_dt)으로 그 범위만 읽는다(시험이 질의 계획을 본다)
ROWS_SQL = ("SELECT bas_dt, clpr, vs, nav, bss_idx_nm, bss_idx_clpr, halted FROM etf_daily "
            "WHERE srtn_cd = ? AND bas_dt >= ? AND bas_dt <= ? ORDER BY bas_dt")
_cache: OrderedDict = OrderedDict()
_lock = threading.Lock()

NOTES = (
    "그림과 숫자는 원자료(공공누리 제4유형 — 출처 표시 · 상업적 이용 금지 · 변경 금지)로 우리가 계산한 값입니다 — "
    "원자료는 내려받을 수 없습니다.",
    pe.NOTE_NOT_OFFICIAL,     # 목록과 같은 글 — 변동성 · 최대 낙폭은 공식 투자위험등급이 아니다
    "분배금은 기준가 차이로 잡은 근사입니다 — 운용사 공시와 몇 원 다를 수 있고, 지급일은 운용사 공시를 확인해 주세요.",
    pe.NOTE_NO_TER,           # 목록과 같은 글 — 총보수 · 추적오차는 이 자료에 없다
)


def clear_cache() -> None:
    with _lock:
        _cache.clear()


# ── 글 만들기 — 부호는 낱말로 ───────────────────────────────────────────────

def _r1(x: float) -> float:
    """문장과 요약 칸이 같은 자리에서 반올림하게 — 소수 한 자리."""
    return round(x, 1)


def _moved(x: float, up: str = "올랐습니다", down: str = "내렸습니다", flat: str = "거의 움직이지 않았습니다") -> str:
    """수익률 → 낱말 문장 조각. −3.2 → 「3.2% 내렸습니다」 (부호를 숫자에 붙이지 않는다)."""
    r = _r1(x)
    if r == 0:
        return flat
    return f"{abs(r):,.1f}% {up if r > 0 else down}"


def _won(v: float) -> str:
    return f"{int(round(v)):,}원"


def _signed(x: float, digits: int = 2) -> str:
    """상관 · 기울기처럼 부호가 뜻인 숫자 — 화면 글과 같은 빼기 기호(−)로."""
    return f"{x:.{digits}f}".replace("-", "−")


def _higher(x: float, hi: str, lo: str, same: str) -> str:
    r = _r1(x)
    return same if r == 0 else (hi if r > 0 else lo)


# ── 읽기 ────────────────────────────────────────────────────────────────────

def _read(path: Path, code: str, start: str, last: str) -> tuple[list, str | None]:
    conn = pe._connect(path)     # 목록과 같은 연결 규칙(mode=ro)
    try:
        rows = conn.execute(ROWS_SQL, (code, start, last)).fetchall()
        first = conn.execute("SELECT MIN(bas_dt) FROM etf_daily WHERE srtn_cd = ?", (code,)).fetchone()[0]
    finally:
        conn.close()
    return rows, first


def _periods(last_bas_dt: str, first: str | None, data_from: str | None) -> list[dict]:
    """기간 칩 넷의 열림 여부 — 그 종목이 창 첫날 전부터 있었을 때만 연다(목록 1년 수익률과 같은 규칙)."""
    last = pe._day(last_bas_dt)
    out = []
    for key, (days, label) in PERIODS.items():
        start = (last - timedelta(days=days)).strftime("%Y%m%d")
        reason = None
        if data_from and data_from > start:
            reason = f"우리 자료가 {pe._iso(data_from)}부터라 {label} 그림은 낼 수 없습니다."
        elif not first or first > start:
            reason = f"{pe._iso(first) or '—'}에 처음 거래돼(우리 자료 기준) 아직 {label}이 지나지 않았습니다."
        out.append({"key": key, "label": label, "from": pe._iso(start), "available": reason is None, "reason": reason})
    return out


# ── 계산 ────────────────────────────────────────────────────────────────────

def _drawdown(points: list[tuple[str, float]]) -> dict:
    """(날짜, 이음 값) → 가장 깊은 낙폭과 그 고점 · 바닥 · 회복."""
    peak_v, peak_i = points[0][1], 0
    worst, w_peak, w_trough = 0.0, 0, 0
    for i, (_, v) in enumerate(points):
        if v > peak_v:
            peak_v, peak_i = v, i
        dd = v / peak_v - 1.0
        if dd < worst:
            worst, w_peak, w_trough = dd, peak_i, i
    if worst == 0.0:
        return {"depth_pct": 0.0, "peak_date": None, "trough_date": None, "recovered_date": None,
                "recovered": None, "days_underwater": 0, "need_to_recover_pct": 0.0}
    target = points[w_peak][1]
    rec = next((i for i in range(w_trough + 1, len(points)) if points[i][1] >= target), None)
    return {
        "depth_pct": worst * 100.0,
        "peak_date": pe._iso(points[w_peak][0]),
        "trough_date": pe._iso(points[w_trough][0]),
        "recovered_date": pe._iso(points[rec][0]) if rec is not None else None,
        "recovered": rec is not None,
        "days_underwater": (rec if rec is not None else len(points) - 1) - w_peak,
        # 되돌아가려면 몇 % 올라야 하나 — −20% → +25% · −50% → +100%
        "need_to_recover_pct": (1.0 / (1.0 + worst) - 1.0) * 100.0,
    }


def _corr_beta(pairs: list[tuple[float, float]]) -> tuple[float | None, float | None]:
    n = len(pairs)
    if n < 2:
        return None, None
    mx = sum(a for a, _ in pairs) / n
    my = sum(b for _, b in pairs) / n
    sxy = sum((a - mx) * (b - my) for a, b in pairs)
    sxx = sum((a - mx) ** 2 for a, _ in pairs)
    syy = sum((b - my) ** 2 for _, b in pairs)
    if sxx == 0 or syy == 0:
        return None, None
    return sxy / math.sqrt(sxx * syy), sxy / syy


def _example(m: int, moves: tuple[float, ...]) -> tuple[float, float, float]:
    """지수 하루 수익률 차례 → (지수 누적 · 단순 계산 · 날마다 다시 맞춘 값) % — 「반대 예」 문장용."""
    idx, prod = 1.0, 1.0
    for r in moves:
        idx *= 1.0 + r
        prod *= 1.0 + m * r
    return (idx - 1.0) * 100.0, m * (idx - 1.0) * 100.0, (prod - 1.0) * 100.0


def _compute(path: Path, item: dict, last_bas_dt: str, data_from: str | None, period: str) -> dict:
    days, label = PERIODS[period]
    start = (pe._day(last_bas_dt) - timedelta(days=days)).strftime("%Y%m%d")
    raw, first = _read(path, item["code"], start, last_bas_dt)
    periods = _periods(last_bas_dt, first, data_from)
    me = next(p for p in periods if p["key"] == period)
    out = {"period": period, "period_label": label, "periods": periods}
    if not me["available"]:
        return {**out, "status": "short", "reason": me["reason"]}
    rows = [r for r in raw if r[1] and r[1] > 0]
    if len(rows) < 2:
        return {**out, "status": "short", "reason": f"{label} 동안 거래된 날이 모자라 그림을 낼 수 없습니다."}

    m = item["multiple"]
    c0, idx0 = rows[0][1], rows[0][5]
    tr = peak = 1.0
    series, points, daily, pairs = [], [], [], []
    raw_idx, raw_ir = [], []         # 반올림 전 값 — 배수 세 값은 이것으로 잇는다(반올림한 하루 값을 243번 곱하지 않게)
    dists, adjusts = [], []
    missing, idx_missing = 0, 0
    idx_names: list[str] = []
    prev_c, prev_idx = None, None
    for i, (d, c, v, nav, idx_nm, idx_c, halted) in enumerate(rows):
        if idx_nm not in idx_names:
            idx_names.append(idx_nm)
        r = ir = None
        if i > 0:
            r = pe.chain_return(c, v)
            if r is None:
                missing += 1                     # 그날은 이음에서 빠진다(목록과 같은 규칙)
            else:
                tr *= 1.0 + r
                daily.append((d, r))
            if v is not None:
                gap = prev_c - (c - v)           # 직전 종가 − 그날 기준가
                if gap > 0:
                    pct = gap / prev_c * 100.0
                    ev = {"date": pe._iso(d), "amount": gap, "pct": round(pct, 3)}
                    (dists if pct <= DIST_MAX_PCT else adjusts).append(ev)
            if idx_c and prev_idx:
                ir = idx_c / prev_idx - 1.0
            if r is not None and ir is not None:
                pairs.append((r, ir))
        if not idx_c:
            idx_missing += 1
        raw_idx.append(idx_c / idx0 if (idx_c and idx0) else None)
        raw_ir.append(ir)
        peak = max(peak, tr)
        points.append((d, tr))
        series.append({
            "date": pe._iso(d),
            "close": c,
            "nav": nav,
            "index_close": idx_c,
            "tr": round(tr * 100.0, 3),
            "px": round(c / c0 * 100.0, 3),
            "peak": round(peak * 100.0, 3),
            "drawdown_pct": round((tr / peak - 1.0) * 100.0, 3),
            "ret_d_pct": round(r * 100.0, 3) if r is not None else None,
            "idx": round(idx_c / idx0 * 100.0, 3) if (idx_c and idx0) else None,
            "idx_ret_d_pct": round(ir * 100.0, 3) if ir is not None else None,
            "premium_pct": round((c / nav - 1.0) * 100.0, 3) if nav else None,
            "halted": bool(halted),
        })
        prev_c, prev_idx = c, idx_c

    n_days = len(rows) - 1
    tr_ok = missing <= pe._MAX_MISSING_VS * n_days       # 목록과 같은 문턱 — 넘으면 이음 값을 내지 않는다
    if not tr_ok:
        for s in series:
            s["tr"] = s["peak"] = s["drawdown_pct"] = None
    window = {"from": series[0]["date"], "to": series[-1]["date"], "trading_days": len(series), "label": label}

    # 얼마나 벌었나
    px_pct = (rows[-1][1] / c0 - 1.0) * 100.0
    tr_pct = (tr - 1.0) * 100.0 if tr_ok else None
    st_return = {
        "tr_pct": tr_pct, "px_pct": px_pct, "example_krw": EXAMPLE_KRW,
        "tr_value": EXAMPLE_KRW * (1.0 + tr_pct / 100.0) if tr_pct is not None else None,
        "px_value": EXAMPLE_KRW * (1.0 + px_pct / 100.0),
        "dist_count": len(dists), "dist_sum": sum(e["amount"] for e in dists),
        "dist_pct_sum": round(sum(e["pct"] for e in dists), 3),
        "missing_vs_days": missing,
    }
    # 가장 크게 잃은 때
    st_dd = _drawdown(points) if tr_ok else None
    # 얼마나 흔들렸나(기간 안)
    rs = [x for _, x in daily]
    st_vol = None
    if len(rs) >= pe._MIN_VOL_RETURNS:
        mean = sum(rs) / len(rs)
        sd = math.sqrt(sum((x - mean) ** 2 for x in rs) / (len(rs) - 1))
        st_vol = {"annual_pct": sd * math.sqrt(252) * 100.0, "daily_typical_pct": sd * 100.0,
                  "days_within": sum(1 for x in rs if abs(x) <= sd), "days_total": len(rs)}
    extremes = None
    if daily:
        best = max(daily, key=lambda t: t[1])
        worst = min(daily, key=lambda t: t[1])
        extremes = {"best": {"date": pe._iso(best[0]), "pct": best[1] * 100.0},
                    "worst": {"date": pe._iso(worst[0]), "pct": worst[1] * 100.0}}
    # 제값에 거래됐나
    prem = [(s["date"], s["premium_pct"]) for s in series if s["premium_pct"] is not None]
    st_prem = None
    if prem:
        mx = max(prem, key=lambda t: abs(t[1]))
        st_prem = {"last_pct": prem[-1][1], "mean_abs_pct": sum(abs(p) for _, p in prem) / len(prem),
                   "max_abs": {"date": mx[0], "pct": mx[1]},
                   "days_over": sum(1 for _, p in prem if abs(p) > PREMIUM_DAY_PCT), "days_total": len(prem),
                   "threshold_pct": PREMIUM_DAY_PCT}
    # 왜 n배가 아닌가 — 파생형만
    st_lev = None
    if m != 1:
        corr, beta = _corr_beta(pairs)
        reasons = []
        if len(idx_names) > 1:
            reasons.append(f"기간 중 기초지수가 바뀌었습니다({' → '.join(n or '이름 없음' for n in idx_names)})")
        if idx_missing:
            reasons.append(f"기초지수 종가가 빈 날이 {idx_missing}일 있습니다")
        if len(pairs) < FIT_MIN_DAYS:
            reasons.append(f"견줄 날이 {len(pairs)}일뿐입니다")
        elif corr is None or abs(corr) < FIT_MIN_CORR:
            reasons.append("ETF 와 기초지수의 같은 날 움직임이 맞지 않습니다("
                           + (f"상관 {_signed(corr)} · " if corr is not None else "")
                           + "해외 지수처럼 마감 시각 · 통화가 다른 지수일 수 있습니다)")
        if not tr_ok:
            reasons.append("전일 대비 칸이 빈 날이 많아 실제 ETF 이음 값을 만들 수 없습니다")
        st_lev = {"multiple": m, "comparable": not reasons, "reason": " · ".join(reasons) or None,
                  "fit_corr": corr, "fit_beta": beta, "fit_days": len(pairs)}
        if not reasons:
            reset = 1.0
            for k, s in enumerate(series):
                if k > 0:
                    reset *= 1.0 + m * raw_ir[k]
                s["lev_naive"] = round((1.0 + m * (raw_idx[k] - 1.0)) * 100.0, 3)
                s["lev_reset"] = round(reset * 100.0, 3)
            index_pct = (raw_idx[-1] - 1.0) * 100.0
            naive_pct = m * index_pct
            reset_pct = (reset - 1.0) * 100.0
            st_lev.update({
                "index_pct": index_pct, "naive_pct": naive_pct, "reset_pct": reset_pct, "actual_pct": tr_pct,
                "path_effect_pctp": reset_pct - naive_pct, "cost_effect_pctp": tr_pct - reset_pct,
            })

    # 계열은 칸마다 배열(길이 = 거래일 수) — 칸 이름을 날마다 되풀이하지 않아 3년도 응답이 가볍다(행 꼴의 약 40%)
    keys = ["date", "close", "nav", "index_close", "tr", "px", "peak", "drawdown_pct", "ret_d_pct", "idx", "idx_ret_d_pct",
            "premium_pct", "halted"]
    if st_lev and st_lev["comparable"]:
        keys += ["lev_naive", "lev_reset"]
    columns = {k: [s[k] for s in series] for k in keys}
    stats = {"return": st_return, "drawdown": st_dd, "volatility": st_vol, "premium": st_prem, "leverage": st_lev}
    events = {"distributions": dists, "adjustments": adjusts, "drawdown": st_dd, "extremes": extremes,
              "missing_vs_days": missing, "index_names": idx_names}
    caption = (f"기간 {window['from']} ~ {window['to']}(거래일 {window['trading_days']}일) · 세전 · 매매 비용 · 세금 빠짐 · "
               f"분배금을 다시 넣은 근사 · 출처 {pe.SOURCE['name']} · 우리가 계산한 값이며 운용사 공시와 다를 수 있습니다 · "
               "과거 수익률은 미래 수익을 보장하지 않습니다")
    return {**out, "status": "ok", "window": window, "series": columns, "events": events, "stats": stats,
            "explain": _explain(item, window, stats), "caption": caption,
            # 견줄 수 없는 파생형(해외 지수 · 지수 바뀜)은 빈 비교로 열지 않게 「얼마나 벌었나」 부터
            "default_chip": "leverage" if (st_lev and st_lev["comparable"]) else "return"}


# ── 칩마다 한 줄 문장 + 근거 줄 ─────────────────────────────────────────────
# 화면은 `sentence`(그림 위 한 줄 요약)를 먼저, `points`(까닭 · 반대 예 — 한 줄에 하나)를 그 아래에 보인다. 처음 목업에서
# 다섯 문장을 한 덩어리로 보였더니 비전공자가 한 번에 읽기 어려웠다(2026-10-12 · Figma 03-2 목업) — 요약과 근거를 나눈다.

def _explain(item: dict, window: dict, stats: dict) -> list[dict]:
    out = []
    n = window["trading_days"]
    sr = stats["return"]
    if sr["tr_pct"] is None:
        sentence = (f"전일 대비 칸이 빈 날이 많아(거래일 {n}일 중 {sr['missing_vs_days']}일) 분배금을 되돌린 수익률은 "
                    "내지 않습니다.")
        points = [f"가격만 보면 {_moved(sr['px_pct'])}."]
    elif not sr["dist_count"] and _won(sr["tr_value"]) == _won(sr["px_value"]):
        sentence = f"{window['from']}에 100만 원을 넣었다면 {window['to']}에는 {_won(sr['px_value'])}이 됐습니다."
        points = ["이 기간에는 분배금이 없어, 분배금을 다시 넣은 값과 가격만 본 값이 같습니다."]
    else:
        sentence = (f"{window['from']}에 100만 원을 넣었다면 {window['to']}에는 {_won(sr['tr_value'])}이 됐습니다"
                    "(분배금을 다시 넣었다고 본 값).")
        diff = _won(abs(sr["tr_value"] - sr["px_value"]))
        points = [f"가격만 보면 {_won(sr['px_value'])}입니다."]
        if sr["dist_count"]:
            points.append(f"그사이 분배금이 {sr['dist_count']}번 있었고(1좌당 합계 약 {sr['dist_sum']:,}원), 두 값의 차이 "
                          f"{diff}은 주로 그 분배금 몫입니다.")
        else:
            points.append(f"이 기간에는 분배금이 없었습니다 — 두 값의 작은 차이 {diff}은 거래소 기준가 조정 때문입니다.")
    out.append({
        "chip": "return", "title": "얼마나 벌었나", "sentence": sentence, "points": points,
        "how": (f"분배금 포함 = 날마다 종가 ÷ (종가 − 전일 대비)를 곱해 이은 값(분배락일에 낮아진 기준가를 되돌림) · "
                f"가격만 = 끝 종가 ÷ 첫 종가 · 거래일 {n}일"),
        "limits": ("세금 · 매매 비용은 빠져 있습니다 · 분배금은 기준가 차이로 잡은 근사라 운용사 공시와 몇 원 다를 수 있습니다 · "
                   "과거 수익률은 미래 수익을 보장하지 않습니다"),
    })

    dd = stats["drawdown"]
    points = []
    if dd is None:
        sentence = "전일 대비 칸이 빈 날이 많아 분배금을 되돌린 이음 값을 만들 수 없어 가장 크게 내린 폭을 내지 않습니다."
    elif _r1(dd["depth_pct"]) == 0:
        sentence = "이 기간에는 그날까지의 최고점보다 내려간 적이 거의 없습니다."
    else:
        sentence = (f"이 기간 가장 높았던 {dd['peak_date']}에 넣었다면 가장 낮았던 {dd['trough_date']}까지 "
                    f"{abs(_r1(dd['depth_pct'])):,.1f}% 줄었습니다(100만 원 → "
                    f"{_won(EXAMPLE_KRW * (1.0 + dd['depth_pct'] / 100.0))}).")
        if dd["recovered"]:
            points.append(f"그 뒤 {dd['recovered_date']}에 그 고점을 되찾았습니다(고점에서 {dd['days_underwater']}거래일).")
        else:
            points.append(f"기준일까지 그 고점을 아직 되찾지 못했습니다(고점에서 {dd['days_underwater']}거래일째).")
        points.append(f"그 바닥에서 원래 값으로 돌아가려면 {_r1(dd['need_to_recover_pct']):,.1f}% 올라야 합니다 — 줄어든 비율보다 "
                      "더 많이 올라야 원래 값이 됩니다.")
    out.append({
        "chip": "drawdown", "title": "가장 크게 잃은 때", "sentence": sentence, "points": points,
        "how": "분배금을 다시 넣은 이음 값이 그날까지의 최고점보다 얼마나 낮은지(그날 값 ÷ 그날까지 최고 − 1) 가운데 가장 낮은 값",
        "limits": "지난 기간 안에서 본 값이며 앞으로 잃을 수 있는 한도가 아닙니다 · 기간을 바꾸면 크게 달라집니다",
    })

    lv = stats["leverage"]
    if lv is not None:
        ml = etp.multiple_label(lv["multiple"])
        title = f"왜 {ml}가 아닌가"
        if not lv["comparable"]:
            sentence = ("이 상품은 기초지수 종가를 같은 날 · 같은 기준으로 견줄 수 없어 세 값(단순 계산 · 날마다 다시 맞춘 값 · "
                        "실제)을 내지 않습니다.")
            points = [f"{lv['reason']}."]
            how = "기초지수 종가와 ETF 종가가 같은 날 · 같은 통화일 때만 셉니다(같은 날 상관 0.95 이상 · 기간 중 지수가 같음)"
        else:
            sentence = (f"이 기간 기초지수는 {_moved(lv['index_pct'])}. ‘{ml}’라면 "
                        f"{_moved(lv['naive_pct'], '오른다고', '내린다고', '제자리라고')} 생각하기 쉽지만, 실제 ETF 는 "
                        f"{_moved(lv['actual_pct'])}.")
            path = _r1(lv["path_effect_pctp"])
            points = [
                f"날마다 {ml}로 다시 맞춘 값은 {_moved(lv['reset_pct'])} — 이 구조 때문에 단순 계산보다 "
                + (f"{abs(path):,.1f}%p {'높았습니다' if path > 0 else '낮았습니다'}." if path else "차이가 거의 없었습니다."),
                (f"실제 ETF 는 그 값보다 {abs(_r1(lv['cost_effect_pctp'])):,.1f}%p "
                 f"{_higher(lv['cost_effect_pctp'], '높았습니다', '낮았습니다', '')}(보수 · 비용 · 추적 차이)."
                 if _r1(lv["cost_effect_pctp"]) else "실제 ETF 와 그 값의 차이는 거의 없었습니다(보수 · 비용 · 추적 차이)."),
            ]
            if lv["naive_pct"] < -100.0:
                points.append(f"단순 계산의 {abs(_r1(lv['naive_pct'])):,.1f}% 하락은 원금보다 더 잃는 값이라 실제로는 나올 수 없습니다.")
            # 좋은 결과만 보이지 않게 늘 「반대 예」 하나를 붙인다(조사서 4.5 — 2배를 넘은 기간에도 낮아지는 예를 함께)
            m = lv["multiple"]
            ci, cn, cr = _example(m, (-0.2, 0.2))       # 오르내림 — 단순 계산보다 낮아지는 예
            choppy = (f"기초지수가 하루 20% 내렸다가 다음 날 20% 오르면 지수는 {_moved(ci, '오르지만', '내리지만')} "
                      f"{ml} 상품은 {_moved(cr, '오릅니다', '내립니다', '제자리입니다')}"
                      f"(단순 계산으로는 {_moved(cn, '오름', '내림', '제자리')})")
            ti, tn, tr_ = _example(m, (0.1, 0.1))       # 한 방향 — 단순 계산보다 높아지는 예
            trend = (f"기초지수가 이틀 연속 10% 오르면 지수는 {_moved(ti, '오르고', '내리고')} {ml} 상품은 "
                     f"{_moved(tr_, '오릅니다', '내립니다', '제자리입니다')}(단순 계산으로는 {_moved(tn, '오름', '내림', '제자리')})")
            if path > 0:
                points.append(f"이 기간처럼 한 방향으로 크게 움직이면 단순 계산보다 높아지지만, 오르내림이 잦으면 반대가 됩니다 — "
                              f"{choppy}.")
            elif path < 0:
                points.append(f"이 기간처럼 오르내림이 잦으면 단순 계산보다 낮아지지만, 한 방향으로 크게 움직이면 반대로 높아질 수 "
                              f"있습니다 — {trend}.")
            else:
                points.append(f"오르내림이 잦으면 단순 계산보다 낮아지고({choppy}), 한 방향으로 크게 움직이면 높아집니다({trend}).")
            how = (f"① 기초지수 × {ml} — 기간 처음과 끝만 본 단순 계산 ② 날마다 기초지수 하루 수익률에 {ml}를 곱해 이은 값 "
                   f"③ 실제 ETF 종가를 분배금 되돌려 이은 값 · 구조 몫 = ② − ① · 비용 · 추적 몫 = ③ − ② · "
                   f"ETF 와 기초지수의 같은 날 상관 {_signed(lv['fit_corr'], 3)}")
        out.append({
            "chip": "leverage", "title": title, "sentence": sentence, "points": points, "how": how,
            "limits": "보수 · 거래 비용 · 금리는 ③ 에만 들어 있고 세금은 빠져 있습니다 · 지난 기간의 값이며 다른 기간에는 크게 다를 수 있습니다",
        })
    return out


# ── 바깥에서 부르는 것 ──────────────────────────────────────────────────────

def chart(code: str, period: str = "1y") -> dict:
    """한 종목의 상세 창 자료. 종목 · 기간이 틀리면 ValueError(→ 422)."""
    if not CODE_RE.match(code or ""):
        raise ValueError("종목코드는 영문 대문자 · 숫자 6자리입니다")
    if period not in PERIODS:
        raise ValueError(f"기간은 {', '.join(PERIODS)} 가운데 하나입니다")
    data, item = pe.find_item(code)
    base = {"code": code, "source": pe.SOURCE, "notes": list(NOTES), "as_of": data.get("as_of")}
    if data["status"] != "ok":
        return {**base, "status": data["status"]}
    if item is None:
        return {**base, "status": "not_found"}
    base.update({"item": item, "band": etp.risk_note(item["multiple"]) if item["multiple"] != 1 else None,
                 "requirement_note": etp.need(item["requirement"])})
    path = Path(collector_db.db_path())
    last_bas_dt = data["as_of"].replace("-", "")
    data_from = (data.get("data_from") or "").replace("-", "") or None
    key = (str(path.resolve()), path.stat().st_mtime_ns, last_bas_dt, code, period)
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return {**base, **hit}
    try:
        body = _compute(path, item, last_bas_dt, data_from, period)
    except sqlite3.Error as e:
        logger.warning("상품 상세 — 수집 DB 를 읽지 못함: %s", type(e).__name__)
        return {**base, "status": "error"}
    with _lock:
        _cache[key] = body
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return {**base, **body}
