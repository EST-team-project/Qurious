"""수집 DB → ``ohlcv-v1`` 파케이 + 매니페스트 (HF ``qurious-quant/krx-ohlcv`` 에 올릴 모양).

    python -m collector.ohlcv_export [--only 1d,1w,60m,5m] [--out data/collector/ohlcv_export]

``krx-daily-market``(수집 DB 를 통째로 되살리는 백업)과 목적이 다르다 — 이쪽은 **분석하는 사람이
바로 읽는** 규격 자료다. 그래서 칸 이름 · 단위 · 수정 방식이 모든 파일에서 같다(설계서 5.1.2).

파일 배치 ::

    ohlcv/timeframe=1d/basis=raw/market=KOSPI/year=2026/part-0.parquet
    ohlcv/timeframe=1d/basis=adj_base/market=KOSPI/year=2026/part-0.parquet
    ohlcv/timeframe=1w/basis=adj_base/market=KOSDAQ/year=2026/part-0.parquet
    ohlcv/timeframe=1d/basis=raw/market=ETF/year=2026/part-0.parquet
    ohlcv/timeframe=1d/basis=raw/market=INDEX/year=2026/part-0.parquet
    ohlcv/timeframe=60m/basis=adj_split/year=2026/month=09/part-0.parquet
    meta/universe.csv · manifest.json · README.md

⚠️ 수정 가격(``adj_base``)은 그 뒤에 일어난 분할 · 권리락을 반영한 값이다. **그날 알 수 있던 가격이
   아니라** 수익률을 이어 붙이기 위한 값이므로, 「그날의 가격 수준」 이 필요한 계산(호가 단위 · 가격대
   필터)은 ``raw`` 를 쓴다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from collector import config, db
from collector import ohlcv as oh
from collector.console import utf8_stdio

OUT_DIR = config.DATA_DIR / "ohlcv_export"
INDEX_PREFIX = {"KOSPI시리즈": "KOSPI", "KOSDAQ시리즈": "KOSDAQ", "KRX시리즈": "KRX", "테마지수": "THEME"}

#: 데이터 카드에 싣는 사실 — 출처마다 실측한 한계(2026-10-01).
NOTES = [
    "주식 · ETF · 지수 일봉: 금융위원회 주식시세정보 · 증권상품시세정보 · 지수시세정보(공공데이터포털). "
    "이용 조건 출처 표시 · 비영리 · 변경 금지 · 제3자 재배포 금지 — 그래서 이 저장소는 private 이다.",
    "수정 가격(adj_base)은 기준가 계수((종가 − 전일대비) ÷ 직전 종가)로 고친 값이다. 야후 Close(분할 비율) · "
    "Adj Close(배당 포함)와 분할일 앞 구간에서 다르다(카카오 2021-04-09: 112,000 · 111,600 · 110,981.9).",
    "분봉: 야후 파이낸스. 09:00~15:00 만 있다(15:00~15:30 종가 단일가 없음) — 분봉 거래량 합은 일봉의 68~77%. "
    "일봉을 분봉에서 만들지 않는다. 가격은 분할 비율로 고친 값(adj_split).",
    "분봉 유니버스는 시가총액 · 거래대금 순위로 고른 근사 명단일 수 있다 — meta/universe.csv 의 reason 칸.",
    "주봉: 일봉에서 계산. 시가 · 고가 · 저가는 거래가 있던 날로만, 날짜는 그 주의 마지막 거래일. "
    "진행 중인 주는 manifest 의 partial_weeks 에 적는다.",
    "거래정지일: 지우지 않고 평평한 봉(시가 = 고가 = 저가 = 종가 = 직전 종가 · 거래량 0)으로 둔다.",
]


def _iso(s: str) -> str:
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def _fetched_map(conn) -> Dict[str, str]:
    """원문 지문 → 받은 시각. 정규화 표의 줄마다 「언제부터 알 수 있었나」 를 붙이려고."""
    return {r[0]: r[1] for r in conn.execute("SELECT sha256, fetched_at FROM raw_response WHERE source='portal'")}


def stock_daily(conn):
    """주식 일봉 — 원 가격(raw)과 수정 가격(adj_base) 두 계열."""
    import pandas as pd

    q = ("SELECT p.bas_dt, p.srtn_cd, p.mrkt_ctg, p.mkp, p.hipr, p.lopr, p.clpr, p.trqu, p.tr_prc, "
         "       p.raw_sha256, a.adj_mkp, a.adj_hipr, a.adj_lopr, a.adj_clpr, a.cum_factor "
         "FROM price_daily p LEFT JOIN price_adjusted a USING (bas_dt, srtn_cd) WHERE p.clpr > 0")
    d = pd.read_sql_query(q, conn)
    fmap = _fetched_map(conn)
    base = pd.DataFrame({
        "symbol": d["srtn_cd"], "market": d["mrkt_ctg"], "timeframe": "1d",
        "trade_date": d["bas_dt"].map(_iso), "bar_start": None,
        "value": d["tr_prc"], "source": "portal", "fetched_at": d["raw_sha256"].map(fmap),
    })
    no_price = d["mkp"].fillna(0) <= 0                     # 거래정지 등 — 평평한 봉으로
    raw = base.assign(
        open=d["mkp"].where(~no_price, d["clpr"]).astype(float), high=d["hipr"].where(~no_price, d["clpr"]).astype(float),
        low=d["lopr"].where(~no_price, d["clpr"]).astype(float), close=d["clpr"].astype(float),
        volume=d["trqu"].fillna(0).astype("int64"), adjusted=False, price_basis="raw", adj_factor=d["cum_factor"])
    f = d["cum_factor"].fillna(1.0)
    ac = d["adj_clpr"].fillna(d["clpr"] * f)
    adj = base.assign(
        open=d["adj_mkp"].where(~no_price & d["adj_mkp"].notna(), ac), high=d["adj_hipr"].where(~no_price & d["adj_hipr"].notna(), ac),
        low=d["adj_lopr"].where(~no_price & d["adj_lopr"].notna(), ac), close=ac,
        volume=(d["trqu"].fillna(0) / f).round().astype("int64"),   # 거래량도 오늘 주식 단위로(앱 어댑터와 같다)
        adjusted=True, price_basis="adj_base", adj_factor=f)
    return pd.concat([raw, adj], ignore_index=True)


def etf_daily(conn):
    import pandas as pd

    d = pd.read_sql_query("SELECT bas_dt, srtn_cd, mkp, hipr, lopr, clpr, trqu, tr_prc, raw_sha256 "
                          "FROM etf_daily WHERE clpr > 0", conn)
    fmap = _fetched_map(conn)
    no_price = d["mkp"].fillna(0) <= 0
    return pd.DataFrame({
        "symbol": d["srtn_cd"], "market": "ETF", "timeframe": "1d", "trade_date": d["bas_dt"].map(_iso),
        "bar_start": None, "open": d["mkp"].where(~no_price, d["clpr"]).astype(float),
        "high": d["hipr"].where(~no_price, d["clpr"]).astype(float), "low": d["lopr"].where(~no_price, d["clpr"]).astype(float),
        "close": d["clpr"].astype(float), "volume": d["trqu"].fillna(0).astype("int64"), "value": d["tr_prc"],
        "adjusted": False, "price_basis": "raw", "adj_factor": None, "source": "portal",
        "fetched_at": d["raw_sha256"].map(fmap)})


def index_daily(conn):
    import pandas as pd

    d = pd.read_sql_query("SELECT bas_dt, idx_csf, idx_nm, mkp, hipr, lopr, clpr, trqu, tr_prc, raw_sha256 "
                          "FROM index_daily WHERE clpr > 0", conn)
    fmap = _fetched_map(conn)
    no_price = d["mkp"].fillna(0) <= 0
    return pd.DataFrame({
        "symbol": d["idx_csf"].map(INDEX_PREFIX).fillna("ETC").astype(str) + ":" + d["idx_nm"].astype(str),
        "market": "INDEX",
        "timeframe": "1d", "trade_date": d["bas_dt"].map(_iso), "bar_start": None,
        "open": d["mkp"].where(~no_price, d["clpr"]), "high": d["hipr"].where(~no_price, d["clpr"]),
        "low": d["lopr"].where(~no_price, d["clpr"]), "close": d["clpr"], "volume": d["trqu"].fillna(0).astype("int64"),
        "value": d["tr_prc"], "adjusted": False, "price_basis": "raw", "adj_factor": None, "source": "portal",
        "fetched_at": d["raw_sha256"].map(fmap)})


def universe_market(conn) -> Dict[str, str]:
    """종목 → 시장. 그 종목이 든 **가장 최근 판**의 값이다(판 이름 차례 — 다른 곳의 `MAX(version)` 과 같은 차례).

    ⚠️ DF-43(2026-10-02) — 예전에는 최신 판(u2)에만 물어 없으면 「KOSPI」 로 채웠다. u2 에서 빠진 71종목 가운데
       **코스닥 38종목의 분봉 304,710줄이 KOSPI 로** 나갔다. 빠진 종목도 옛 판(u1)이 시장을 알고 있다.
    """
    out: Dict[str, str] = {}
    for sym, mkt in conn.execute("SELECT symbol, market FROM intraday_universe ORDER BY version"):
        out[sym] = mkt                          # 뒤 판이 앞 판을 덮는다
    return out


def intraday(conn, timeframe: str):
    import pandas as pd

    d = pd.read_sql_query("SELECT * FROM price_intraday WHERE timeframe=?", conn, params=(timeframe,))
    d["market"] = d["symbol"].map(universe_market(conn))
    # 어느 판에도 없는 종목은 지어내지 않는다 — 빈 칸이면 값 규칙 검사(bad_market)가 보고서에 남긴다
    d["adjusted"] = True
    d["value"] = None
    d["adj_factor"] = None
    return d


def _write(df, path: Path) -> Dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    df.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": path.relative_to(OUT_DIR).as_posix(), "rows": int(len(df)), "bytes": path.stat().st_size,
            "sha256": h, "first": str(df["trade_date"].min()), "last": str(df["trade_date"].max())}


def _daily_and_weekly(frame, files: List[Dict], checks: Dict, as_of: str, partial: set, only: set) -> None:
    for (basis, market), g in frame.groupby(["price_basis", "market"], sort=True):
        g = oh.finalize(g, source="portal")
        if "1d" in only:
            checks[f"1d/{basis}/{market}"] = oh.check(g)["problems"]
            for year, gy in g.groupby(g["trade_date"].str[:4]):
                files.append(_write(gy, OUT_DIR / f"ohlcv/timeframe=1d/basis={basis}/market={market}/year={year}/part-0.parquet"))
        if "1w" in only:
            w = oh.weekly(g, as_of=_iso(as_of))
            partial.update(w.loc[w["partial"], "trade_date"].astype(str))
            w = oh.finalize(w.drop(columns=["partial"]), source="portal")
            checks[f"1w/{basis}/{market}"] = oh.check(w)["problems"]
            for year, gy in w.groupby(w["trade_date"].str[:4]):
                files.append(_write(gy, OUT_DIR / f"ohlcv/timeframe=1w/basis={basis}/market={market}/year={year}/part-0.parquet"))


def export(only: Optional[List[str]] = None, out: Optional[Path] = None) -> Dict:
    global OUT_DIR
    if out:
        OUT_DIR = Path(out)
    only_set = set(only or ["1d", "1w", "60m", "5m"])
    conn = db.connect()
    as_of = conn.execute("SELECT MAX(bas_dt) FROM price_daily").fetchone()[0]
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR / "ohlcv", ignore_errors=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files: List[Dict] = []
    checks: Dict = {}
    partial: set = set()

    print(f"― ohlcv-v1 내보내기 · 기준 {as_of} · {sorted(only_set)} → {OUT_DIR} ―", flush=True)
    if only_set & {"1d", "1w"}:
        for name, fn in (("주식", stock_daily), ("ETF", etf_daily), ("지수", index_daily)):
            fr = fn(conn)
            print(f"  {name} 일봉 {len(fr):,}줄", flush=True)
            if len(fr):
                _daily_and_weekly(fr, files, checks, as_of, partial, only_set)
    for tf in ("60m", "5m", "1m"):
        if tf not in only_set:
            continue
        fr = intraday(conn, tf)
        if not len(fr):
            continue
        fr = oh.finalize(fr, source="yahoo")
        checks[f"{tf}/adj_split"] = oh.check(fr)["problems"]
        print(f"  분봉 {tf} {len(fr):,}봉", flush=True)
        for (y, m), g in fr.groupby([fr["trade_date"].str[:4], fr["trade_date"].str[5:7]]):
            files.append(_write(g, OUT_DIR / f"ohlcv/timeframe={tf}/basis=adj_split/year={y}/month={m}/part-0.parquet"))

    uni = [dict(r) for r in conn.execute(
        "SELECT version, symbol, itms_nm, market, reason, rank FROM intraday_universe "
        "WHERE version=(SELECT MAX(version) FROM intraday_universe) ORDER BY market, rank")]
    if uni:
        import csv
        (OUT_DIR / "meta").mkdir(exist_ok=True)
        with open(OUT_DIR / "meta" / "universe.csv", "w", encoding="utf-8", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(uni[0]))
            wr.writeheader()
            wr.writerows(uni)

    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=config.ROOT, capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except Exception:
        head = "?"
    man = {
        "contract": oh.CONTRACT, "columns": list(oh.COLUMNS), "key": list(oh.KEY),
        "as_of": _iso(as_of), "built_at": datetime.now(oh.KST).isoformat(timespec="seconds"),
        "collector_commit": head, "partial_weeks": sorted(partial),
        "universe_version": uni[0]["version"] if uni else None,
        "rows": {k: sum(f["rows"] for f in files if f["path"].startswith(f"ohlcv/timeframe={k}/"))
                 for k in ("1d", "1w", "60m", "5m", "1m")},
        "checks": checks, "notes": NOTES, "files": files,
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    bad = {k: v for k, v in checks.items() if v}
    print(f"  파일 {len(files):,}개 · {sum(f['bytes'] for f in files) / 1e6:,.1f} MB · 행 {man['rows']}")
    print(f"  값 규칙 {'✅ 위반 0' if not bad else '⚠️ ' + json.dumps(bad, ensure_ascii=False)[:400]}")
    return man


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="python -m collector.ohlcv_export", description="수집 DB → ohlcv-v1 파케이")
    ap.add_argument("--only", help="쉼표로 — 1d,1w,60m,5m,1m (기본 1d,1w,60m,5m)")
    ap.add_argument("--out", help=f"내보낼 폴더 (기본 {OUT_DIR})")
    a = ap.parse_args(argv)
    export(a.only.split(",") if a.only else None, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
