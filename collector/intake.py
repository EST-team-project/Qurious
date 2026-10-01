"""받은 시세 파일 검사 — 칸 맞추기 · 값 규칙 · 수집 DB 대조 · 정제 · 보고서.

    python -m collector.intake <파일> --contributor <깃허브 아이디> [--symbol 005930] [--market KOSPI]
                                      [--out data/collector/contrib] [--upload]

이 파일이 답하는 질문: **"팀원(또는 다른 출처)이 모은 OHLCV 파일을 믿고 같이 써도 되나."**

판정 순서 (설계서 5.1.4 그림 2 · 개념 학습 1.4 장)
--------------------------------------------------
1. 칸 맞추기 — ``Date`` · ``날짜`` · ``시가`` · ``Open`` … 를 ``ohlcv-v1`` 이름으로.
2. 값 규칙 — ``collector/ohlcv.check``. 같은 키에 **값이 다른** 줄이 둘 이상이면 🔴 (어느 쪽이 맞는지
   모른다). 값까지 같은 중복은 정제에서 하나만 남긴다.
3. 대조 — 겹치는 종목 · 날짜의 종가를 수집 DB 의 원 가격 · 수정 가격(기준가 계수)과 견준다.
   「같다」 = 차이 1원 이하 또는 0.01% 이하. 일치율 99% 이상 🟢 · 95~99% 🟡 · 그 밖은 원인을 찾는다.
4. 원인 찾기 — 날짜를 거래일 한 칸 앞 · 뒤로(하루 밀림) · 1,000배(단위) · 끊김 사이 구간의 비율이
   한 숫자로 일정한가(수정 방식 다름 — 야후 ``Close`` 는 분할 비율로 고친 값이다).
5. 정제 — 종목코드 6자리 · KST 날짜 · 값이 같은 중복 제거 · 거래일 밖 몇 줄 제거 · 시가 0 인 날은
   평평한 봉. 원래 자료(수집 DB)와 **합치지 않고** ``source=contrib:<아이디>`` 로 따로 둔다(💬 ②).
6. 보고서 — ``report.json`` 에 판정과 근거 숫자를 남긴다. 🔴 인 파일은 정제본을 만들지 않는다.

출력은 ``data/collector/contrib/<아이디>/<YYYY-MM-DD>/`` (git 에서 빠지는 곳). ``--upload`` 를 주면
HF ``qurious-quant/krx-ohlcv`` 의 ``contrib/<아이디>/<날짜>/`` 에 올린다(공개 범위 확인 뒤).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional, Sequence

from collector import config
from collector import ohlcv as oh
from collector.console import utf8_stdio

OUT_DIR = config.DATA_DIR / "contrib"
MATCH_OK, MATCH_WARN = 0.99, 0.95
MAX_DROP_NON_TRADING = 0.01        # 거래일 밖 줄이 이 비율 이하면 지우고, 넘으면 밀림을 의심한다

#: 칸 이름 맞추기 — 소문자로 견준다. 「Adj Close」 는 종가로 쓰지 않는다(배당까지 고친 값).
ALIASES: Dict[str, Sequence[str]] = {
    "symbol": ("symbol", "code", "ticker", "종목코드", "단축코드", "srtn_cd", "srtncd"),
    "trade_date": ("trade_date", "date", "datetime", "날짜", "일자", "기준일", "기준일자", "bas_dt", "basdt"),
    "open": ("open", "시가", "mkp"),
    "high": ("high", "고가", "hipr"),
    "low": ("low", "저가", "lopr"),
    "close": ("close", "종가", "clpr"),
    "volume": ("volume", "거래량", "trqu"),
    "value": ("value", "거래대금", "tr_prc", "trprc"),
    "market": ("market", "시장", "mrkt_ctg"),
}


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= max(1.0, abs(b) * 0.0001)


# ==================================================
# 1. 읽기 · 칸 맞추기
# ==================================================
def load_file(path, symbol: Optional[str] = None, market: Optional[str] = None):
    """csv · parquet · xlsx 를 읽어 ``ohlcv-v1`` 칸 이름으로 바꾼다. 맞춘 내역도 돌려준다."""
    import pandas as pd

    p = Path(path)
    suf = p.suffix.lower()
    if suf == ".parquet":
        df = pd.read_parquet(p)
    elif suf in (".xlsx", ".xls"):
        df = pd.read_excel(p)
    else:
        raw = p.read_bytes()
        for enc in ("utf-8-sig", "cp949"):
            try:
                raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        df = pd.read_csv(p, encoding=enc, dtype={"symbol": str, "code": str, "종목코드": str, "단축코드": str})
        # yfinance(0.2.51~)가 기본으로 저장하는 모양 — 머리 세 줄 「Price … / Ticker … / Date ,,,」
        if len(df) >= 2 and str(df.columns[0]).strip() == "Price" and str(df.iloc[0, 0]).strip() == "Ticker":
            tick = str(df.iloc[0, 1]).strip()
            df = df.iloc[2:].rename(columns={df.columns[0]: "Date"}).reset_index(drop=True)
            for c in df.columns[1:]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            if symbol is None and tick and tick.lower() != "nan":
                symbol = tick
    if df.index.name and df.index.name.lower() in ("date", "datetime", "날짜"):
        df = df.reset_index()
    mapping: Dict[str, str] = {}
    lower = {str(c).strip().lower(): c for c in df.columns}
    for target, names in ALIASES.items():
        for n in names:
            if n in lower and target not in mapping.values():
                mapping[lower[n]] = target
                break
    df = df.rename(columns=mapping)
    notes = [f"{src} → {dst}" for src, dst in mapping.items() if src != dst]
    if "adj close" in lower:
        notes.append("「Adj Close」 칸은 쓰지 않았다(배당까지 고친 값) — 종가는 「Close」")
    if "symbol" not in df.columns:
        if not symbol:
            raise ValueError("파일에 종목 칸이 없다 — `--symbol 005930` 처럼 알려 준다")
        df["symbol"] = symbol
        notes.append(f"종목 칸이 없어 --symbol {symbol} 을 넣었다")
    df["symbol"] = df["symbol"].astype(str).str.replace(r"\.(KS|KQ)$", "", regex=True).str.strip().str.zfill(6)
    if "market" not in df.columns:
        df["market"] = market or "KOSPI"
    df["trade_date"] = df["trade_date"].map(_kst_date)
    df["timeframe"] = "1d"
    return df, notes


def _kst_date(v) -> Optional[str]:
    """날짜 값 → KST 날짜 문자열. 시간대가 붙은 시각은 KST 로 바꾼 뒤 날짜를 잡는다(하루 밀림 방지)."""
    import pandas as pd

    if v is None or (isinstance(v, float) and v != v):
        return None
    s = str(v).strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    ts = pd.Timestamp(v)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("Asia/Seoul")
    return ts.date().isoformat()


# ==================================================
# 2. 기준 자료(수집 DB)
# ==================================================
def reference(conn, symbols: Sequence[str], start: str, end: str) -> Dict:
    """종목마다 원 가격 · 수정 가격 종가와 끊긴 날(분할 · 권리락)을 모은다. ETF 는 원 가격만."""
    s0, e0 = start.replace("-", ""), end.replace("-", "")
    days = [f"{r[0][:4]}-{r[0][4:6]}-{r[0][6:]}" for r in conn.execute(
        "SELECT DISTINCT bas_dt FROM price_daily WHERE bas_dt BETWEEN ? AND ? ORDER BY bas_dt",
        (_shift_str(s0, -10), _shift_str(e0, 10)))]
    out = {"days": days, "symbols": {}}
    iso = lambda s: f"{s[:4]}-{s[4:6]}-{s[6:]}"
    for sym in symbols:
        rows = conn.execute(
            "SELECT p.bas_dt, p.clpr, a.adj_clpr FROM price_daily p LEFT JOIN price_adjusted a USING (bas_dt, srtn_cd) "
            "WHERE p.srtn_cd=? AND p.bas_dt BETWEEN ? AND ? AND p.clpr > 0", (sym, s0, e0)).fetchall()
        kind = "stock"
        if not rows:
            try:
                rows = conn.execute("SELECT bas_dt, clpr, NULL FROM etf_daily WHERE srtn_cd=? AND bas_dt BETWEEN ? AND ? "
                                    "AND clpr > 0", (sym, s0, e0)).fetchall()
                kind = "etf"
            except Exception:
                rows = []
        if not rows:
            continue
        events = [iso(r[0]) for r in conn.execute(
            "SELECT bas_dt FROM corporate_action WHERE srtn_cd=? AND bas_dt BETWEEN ? AND ?", (sym, s0, e0))] \
            if kind == "stock" else []
        out["symbols"][sym] = {
            "kind": kind,
            "raw": {iso(r[0]): float(r[1]) for r in rows},
            "adj": {iso(r[0]): float(r[2] if r[2] is not None else r[1]) for r in rows},
            "events": sorted(events),
        }
    return out


def _shift_str(yyyymmdd: str, days: int) -> str:
    from datetime import timedelta
    d = date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:])) + timedelta(days=days)
    return d.strftime("%Y%m%d")


# ==================================================
# 3. 대조 · 원인 찾기
# ==================================================
def match_rate(closes: Dict[str, float], ref: Dict[str, float], days: List[str],
               shift: int = 0, scale: float = 1.0) -> Optional[float]:
    pos = {d: i for i, d in enumerate(days)}
    hits = total = 0
    for d, c in closes.items():
        if d not in pos:
            continue
        j = pos[d] + shift
        if 0 <= j < len(days) and days[j] in ref:
            total += 1
            hits += _same(c * scale, ref[days[j]])
    return hits / total if total else None


def basis_ratio(closes: Dict[str, float], ref_adj: Dict[str, float], events: List[str]) -> Optional[Dict]:
    """끊긴 날로 나눈 구간마다 「받은 값 ÷ 기준 수정 값」 이 한 숫자로 일정한가.

    마지막 구간(가장 최근)은 같아야 하고, 그 앞 구간들이 각각 일정한 비율이면 수정 방식만 다른 것이다.
    """
    if not events:
        return None
    bounds = sorted(events)
    segs: Dict[int, List[float]] = {}
    for d, c in closes.items():
        if d in ref_adj and ref_adj[d] > 0:
            k = sum(1 for e in bounds if d >= e)          # 이 날 앞에 끊긴 날이 몇 번 있었나
            segs.setdefault(k, []).append(c / ref_adj[d])
    last = max(segs) if segs else None
    if last is None or last != len(bounds):
        return None
    if any(abs(x - 1) > 0.0001 for x in segs[last]):
        return None
    ratios = {}
    for k, xs in segs.items():
        if k == last:
            continue
        if max(xs) / min(xs) - 1 > 0.0005:
            return None
        ratios[k] = median(xs)
    if not ratios or all(abs(r - 1) <= 0.0001 for r in ratios.values()):
        return None
    return {"segments": {bounds[k] if k < len(bounds) else "끝": round(r, 6) for k, r in ratios.items()}}


def _mismatches(closes: Dict[str, float], ref: Dict, basis: str, n: int = 5) -> Dict:
    """설계서 표 8 — 일치율과 함께 최대 차이 · 어긋난 날 예시 n 줄."""
    base = ref["raw"] if basis == "raw" else ref["adj"]
    diffs = [(d, c, base[d]) for d, c in sorted(closes.items()) if d in base and not _same(c, base[d])]
    worst = max((abs(c - b) / b for _, c, b in diffs if b), default=0.0)
    return {"max_rel_diff": round(worst, 6),
            "examples": [{"date": d, "received": c, "raw": ref["raw"].get(d), "adj_base": ref["adj"].get(d)}
                         for d, c, _ in diffs[:n]]}


def judge_symbol(closes: Dict[str, float], ref: Dict, days: List[str]) -> Dict:
    raw, adj = match_rate(closes, ref["raw"], days), match_rate(closes, ref["adj"], days)
    res = {"overlap": sum(1 for d in closes if d in ref["raw"]),
           "match": {"raw": _r(raw), "adj_base": _r(adj)}, "hints": []}
    best = max(raw or 0, adj or 0)
    res["price_basis"] = "raw" if (raw or 0) >= (adj or 0) else "adj_base"
    res.update(_mismatches(closes, ref, res["price_basis"]))
    if res["overlap"] == 0:
        res["verdict"], res["price_basis"] = "🟡 대조 불가", "unknown"
        res["hints"].append("수집 DB 와 겹치는 날이 없다 — 값 규칙만 봤다")
        return res
    if best >= MATCH_OK:
        res["verdict"] = "🟢 일치"
        return res
    if best >= MATCH_WARN:
        res["verdict"] = "🟡 대부분 일치 — 원인 확인"
        return res
    for shift in (-1, 1):
        r = max(match_rate(closes, ref["raw"], days, shift) or 0, match_rate(closes, ref["adj"], days, shift) or 0)
        if r >= MATCH_WARN:
            res["hints"].append(f"날짜를 거래일 {'한 칸 뒤' if shift == 1 else '한 칸 앞'}로 옮기면 일치율 {r:.0%} — "
                                "날짜가 밀려 있다(시간대 · 자정 표기 의심)")
    ratios = [ref["raw"][d] / c for d, c in closes.items() if d in ref["raw"] and c > 0]
    k = median(ratios) if ratios else 0
    for unit, label in ((1000, "천 원 단위"), (0.001, "1/1000 단위")):
        if k and abs(k / unit - 1) < 0.01:
            r = match_rate(closes, ref["raw"], days, 0, unit)
            res["hints"].append(f"기준 ÷ 받은 값의 가운데 값 {k:,.4g} — {label}로 보인다(맞춰 보면 일치율 {r:.0%})")
    drift = _dividend_drift(closes, ref["raw"])
    if drift:
        res["hints"].append(drift)
        res["verdict"], res["price_basis"] = "🟡 수정 방식만 다름", "adj_total"
        return res
    br = basis_ratio(closes, ref["adj"], ref["events"])
    if br:
        res["hints"].append(f"끊긴 날 앞 구간의 비율이 일정하다 {br['segments']} — 수정 방식이 다르다"
                            "(분할 비율로 고친 값 · 야후 Close 일 가능성)")
        res["verdict"], res["price_basis"] = "🟡 수정 방식만 다름", "adj_split"
        return res
    res["verdict"] = "🔴 기준과 다름"
    return res


def _dividend_drift(closes: Dict[str, float], ref_raw: Dict[str, float]) -> Optional[str]:
    """「받은 값 ÷ 원 가격」 이 최근엔 1 이고 과거로 갈수록 조금씩 작아지면 배당까지 고친 값이다.

    배당락일마다 그 앞 구간 전체에 (1 − 배당 ÷ 직전 종가)를 곱하므로, 날짜 순으로 보면 비율이
    계단처럼 조금씩 커져 마지막에 1 이 된다(야후 ``Adj Close`` · ``auto_adjust=True``).
    """
    pts = [(d, c / ref_raw[d]) for d, c in sorted(closes.items()) if d in ref_raw and ref_raw[d] > 0]
    if len(pts) < 20:
        return None
    rs = [r for _, r in pts]
    if abs(rs[-1] - 1) > 0.0001 or rs[0] > 0.9995 or rs[0] < 0.5:
        return None
    if any(b < a - 0.0005 for a, b in zip(rs, rs[1:])):          # 날짜 순으로 줄어드는 곳이 있으면 아니다
        return None
    return (f"「받은 값 ÷ 원 가격」 이 {rs[0]:.4f} 에서 1 로 계단처럼 커진다 — 배당 · 분배금까지 고친 값으로 보인다"
            "(야후 Adj Close · auto_adjust=True · FinanceDataReader 의 ETF 가격)")


def _r(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(x, 4)


# ==================================================
# 4. 정제
# ==================================================
def clean(df, days: List[str]):
    """정제본과 정제 내역. 값이 다른 중복이 있으면 정제하지 않는다(🔴 — 어느 쪽이 맞는지 모른다)."""
    log: List[str] = []
    d = df.copy()
    before = len(d)
    d = d.drop_duplicates(subset=["symbol", "trade_date", "open", "high", "low", "close", "volume"])
    if len(d) < before:
        log.append(f"값까지 같은 중복 {before - len(d)}줄을 하나로")
    dset = set(days)
    off = ~d["trade_date"].isin(dset)
    if off.any():
        if off.mean() <= MAX_DROP_NON_TRADING:
            log.append(f"거래일이 아닌 날 {int(off.sum())}줄 제거: {', '.join(sorted(d.loc[off, 'trade_date'])[:5])}")
            d = d[~off]
        else:
            log.append(f"거래일이 아닌 날이 {int(off.sum())}줄({off.mean():.0%}) — 날짜가 밀렸을 수 있어 지우지 않았다")
    zero = d["open"].fillna(0) <= 0
    if zero.any():
        for c in ("open", "high", "low"):
            d.loc[zero, c] = d.loc[zero, "close"]
        log.append(f"시가 0 인 날 {int(zero.sum())}줄을 평평한 봉으로(거래정지 표기)")
    return d.sort_values(["symbol", "trade_date"]).reset_index(drop=True), log


# ==================================================
# 5. 전체
# ==================================================
def run(path, contributor: str, conn=None, symbol: Optional[str] = None, market: Optional[str] = None,
        out_dir: Optional[Path] = None, today: Optional[str] = None) -> Dict:
    from collector import db

    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", contributor or ""):
        raise ValueError("--contributor 는 깃허브 아이디(영문 · 숫자 · -)로 준다")
    conn = conn or db.connect()
    df, notes = load_file(path, symbol, market)
    today = today or datetime.now(oh.KST).date().isoformat()
    report: Dict = {"file": Path(path).name, "contributor": contributor, "checked_at": today,
                    "rows": int(len(df)), "column_mapping": notes, "contract": oh.CONTRACT}

    work = df.copy()
    work["price_basis"], work["adjusted"] = "raw", False
    work["source"] = f"contrib:{contributor}"
    work = oh.finalize(work, source=f"contrib:{contributor}")
    zero = work["open"].fillna(0) <= 0          # 거래정지 표기(시가 0)는 규칙 위반으로 세지 않는다
    rules = oh.check(work.loc[~zero])
    dup_conflict = work.duplicated(subset=["symbol", "trade_date"], keep=False) & \
        ~work.duplicated(subset=["symbol", "trade_date", "open", "high", "low", "close", "volume"], keep=False)
    if dup_conflict.any():
        rules["problems"]["duplicate_key"] = int(dup_conflict.sum())
    else:
        rules["problems"].pop("duplicate_key", None)       # 값까지 같은 중복은 정제에서 지운다
    report["rule_problems"] = rules["problems"]
    report["rule_examples"] = {k: v for k, v in rules["examples"].items() if k in rules["problems"]}

    start, end = str(work["trade_date"].min()), str(work["trade_date"].max())
    ref = reference(conn, sorted(work["symbol"].unique()), start, end)
    per = {}
    for sym, g in work.groupby("symbol"):
        closes = {str(d): float(c) for d, c in zip(g["trade_date"], g["close"]) if c and c > 0}
        if sym in ref["symbols"]:
            per[sym] = judge_symbol(closes, ref["symbols"][sym], ref["days"])
        else:
            per[sym] = {"verdict": "🟡 대조 불가", "price_basis": "unknown", "overlap": 0,
                        "hints": ["수집 DB 에 없는 종목 — 값 규칙만 봤다"]}
    report["symbols"] = per

    verdicts = [v["verdict"] for v in per.values()]
    if report["rule_problems"]:
        report["verdict"] = "🔴 규칙 위반"
    elif any(v.startswith("🔴") for v in verdicts):
        report["verdict"] = "🔴 기준과 다름"
    elif all(v.startswith("🟢") for v in verdicts):
        report["verdict"] = "🟢 일치"
    else:
        report["verdict"] = "🟡 확인 필요"

    out = Path(out_dir or OUT_DIR) / contributor / today
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(path).stem
    if not report["verdict"].startswith("🔴"):
        cleaned, log = clean(work, ref["days"])
        for sym, info in per.items():
            cleaned.loc[cleaned["symbol"] == sym, "price_basis"] = info["price_basis"]
            cleaned.loc[cleaned["symbol"] == sym, "adjusted"] = info["price_basis"] not in ("raw", "unknown")
        report["cleaning"] = log
        target = out / f"{stem}.parquet"
        oh.finalize(cleaned, source=f"contrib:{contributor}").to_parquet(target, index=False)
        report["output"] = target.name
        report["output_rows"] = int(len(cleaned))
    else:
        report["output"] = None
    (out / f"{stem}.report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(out / f"{stem}.report.json")
    return report


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="python -m collector.intake", description="받은 시세 파일 검사 · 정제 · 보고서")
    ap.add_argument("file")
    ap.add_argument("--contributor", required=True, help="깃허브 아이디 — 출력 폴더 · source 칸 이름")
    ap.add_argument("--symbol", help="파일에 종목 칸이 없을 때")
    ap.add_argument("--market", help="파일에 시장 칸이 없을 때(기본 KOSPI)")
    ap.add_argument("--out", help=f"출력 폴더(기본 {OUT_DIR})")
    a = ap.parse_args(argv)
    rep = run(a.file, a.contributor, symbol=a.symbol, market=a.market, out_dir=a.out)
    print(f"[{rep['file']}] {rep['verdict']} · {rep['rows']:,}줄")
    for k, v in rep["rule_problems"].items():
        print(f"  규칙 {oh.RULES.get(k, k)}: {v}")
    for sym, info in list(rep["symbols"].items())[:20]:
        m = info.get("match", {})
        print(f"  {sym} {info['verdict']} · 원 {m.get('raw')} · 수정 {m.get('adj_base')} · 수정 방식 {info['price_basis']}")
        for h in info.get("hints", []):
            print(f"      단서: {h}")
    for line in rep.get("cleaning", []):
        print(f"  정제: {line}")
    print(f"  보고서 {rep['report_path']}")
    return 0 if not rep["verdict"].startswith("🔴") else 1


if __name__ == "__main__":
    sys.exit(main())
