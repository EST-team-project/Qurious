"""OHLCV 적재 명령 — ETF · 지수 일봉 백필 · 분봉 유니버스 · 분봉 받기 · 출처 대조 · 상태.

    python -m collector.ohlcv_load status
    python -m collector.ohlcv_load etf   [--start 20200102] [--end 20260929] [--limit N]
    python -m collector.ohlcv_load index [--start 20200102] [--end 20260929] [--limit N]
    python -m collector.ohlcv_load universe [--as-of 20260929]
    python -m collector.ohlcv_load intraday --timeframe 60m|5m (--first | --recent)
    python -m collector.ohlcv_load crosscheck [--n 20]
    python -m collector.ohlcv_load daily              매일 12:30 러너의 ohlcv 단계 — 아래 넷을 차례로
                                                      (ETF · 지수 최근 14일 빈 날 · 분봉 60m/5m 최근 5일 · 내보내기)

순서가 있다: ``etf`` 를 먼저 받아야 ``universe`` 가 ETF 거래대금 순위를 고를 수 있고,
``universe`` 가 있어야 ``intraday`` 가 받을 종목을 안다.

멈췄다 다시 돌려도 된다 — 일봉은 ``ingest_day`` 에 done 인 날을 건너뛰고, 분봉은 같은 봉을
새 값으로 바꿔 넣는다(INSERT OR REPLACE).

⚠️ 매일 12:30 러너(`scripts/daily_update.py`)가 같은 DB 에 쓰는 동안에는 돌리지 않는다.
   SQLite 는 쓰는 쪽이 하나라, 러너가 오래 잡는 단계(수정주가 · TR)와 겹치면 기다리다
   60초 뒤 실패한다. `python scripts/daily_update.py status` 로 먼저 확인한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from collector import config, db
from collector.console import utf8_stdio
from collector.ratelimit import BudgetExhausted, RateLimiter
from collector.sources import portal_products as pp
from collector.sources import yahoo_intraday as yi

FIRST_PERIOD = {"60m": "730d", "5m": "60d", "1m": "7d"}   # 첫 적재 — 받을 수 있는 창 전체(거래일)
RECENT_PERIOD = {"60m": "5d", "5m": "5d", "1m": "5d"}     # 매일 — 최근 며칠을 다시 받아 덮는다
#: 빠진 종목 다시 받기 — 날짜로 요청할 때의 한도(달력 날짜)보다 하루 안쪽.
#: 2023~24년에 상장한 종목은 `period="730d"` 를 야후가 상장일부터로 바꿔 「730일 밖」 오류를 낸다
#: (2026-10-01 첫 적재 60분봉 24종목). 날짜로 요청하면 받는다.
RETRY_DAYS = {"60m": 729, "5m": 59, "1m": 29}
STATE_FILE = config.STATE_DIR / "ohlcv_last.json"


def _limiter(kind: str) -> RateLimiter:
    return RateLimiter(config.PORTAL_SLEEP, reserve=config.PORTAL_RESERVE, name=f"portal_{kind}")


def cmd_daily(kind: str, start: str, end: str, limit: Optional[int]) -> int:
    conn = db.connect()
    days = pp.pending(conn, kind, pp.trading_days(conn, start, end))
    if limit:
        days = days[:limit]
    print(f"― {kind} 일봉 · 받을 날 {len(days):,}일 ({start} ~ {end}, 받은 날은 건너뜀) ―")
    lim = _limiter(kind)
    stat = {"done": 0, "empty": 0, "error": 0}
    rows = 0
    try:
        for i, d in enumerate(days, 1):
            res = pp.fetch_day(conn, lim, kind, d)
            stat[res.status] = stat.get(res.status, 0) + 1
            rows += res.rows
            if res.status == "error" or i % 100 == 0 or i == len(days):
                print(f"  {i:>5}/{len(days)}  {d}  {res.status:<5} {res.rows:>5}행"
                      + (f"  ⚠️ {res.message}" if res.message else "") + f"  {lim.report()}", flush=True)
    except BudgetExhausted as exc:
        print(f"  ⏸️ {exc}")
    print(f"  끝 — done {stat['done']} · empty {stat['empty']} · error {stat['error']} · {rows:,}행")
    return 0 if not stat["error"] else 1


def cmd_universe(as_of: Optional[str], kospi200: Optional[str] = None, kosdaq150: Optional[str] = None) -> int:
    conn = db.connect()
    as_of = as_of or conn.execute("SELECT MAX(bas_dt) FROM price_daily").fetchone()[0]
    if kospi200 and kosdaq150:
        members = yi.universe_from_krx(conn, kospi200, kosdaq150, as_of)
        version = f"u2-{as_of}"                    # u2 = KRX 공식 구성종목 파일
    else:
        members = yi.build_universe(conn, as_of)
        version = yi.now_version(as_of)            # u1 = 시가총액 순위 근사
    if not members:
        print("고를 종목이 없다 — price_daily 가 비었다")
        return 1
    n = yi.save_universe(conn, version, members)
    by = {}
    for m in members:
        by[m["market"]] = by.get(m["market"], 0) + 1
    print(f"― 분봉 유니버스 {version} · {n}종목 · " + " · ".join(f"{k} {v}" for k, v in by.items()) + " ―")
    if by.get("ETF", 0) == 0:
        print("  ⚠️ ETF 가 0 — etf_daily 가 비어 있다. `etf` 를 먼저 돌린 뒤 다시 고른다.")
    for m in members[:3] + [x for x in members if x["market"] == "KOSDAQ"][:2] + [x for x in members if x["market"] == "ETF"][:2]:
        print(f"  {m['market']:<6} {m['symbol']} {m['itms_nm']}  — {m['reason']}")
    return 0


def cmd_intraday(timeframe: str, first: bool, limit: Optional[int], only_missing: bool = False) -> int:
    conn = db.connect()
    members = yi.latest_universe(conn)
    if not members:
        print("유니버스가 없다 — `python -m collector.ohlcv_load universe` 를 먼저 돌린다.")
        return 1
    if only_missing:                                # 명단이 바뀐 뒤 — 아직 한 봉도 없는 종목만
        have = {r[0] for r in conn.execute("SELECT DISTINCT symbol FROM price_intraday WHERE timeframe=?",
                                           (timeframe,))}
        members = [m for m in members if m["symbol"] not in have]
        if not members:
            print(f"  {timeframe} — 새로 받을 종목이 없다(명단 전부 이미 있음)")
            return 0
    if limit:
        members = members[:limit]
    period = (FIRST_PERIOD if first else RECENT_PERIOD)[timeframe]
    start = None
    if only_missing and first:                       # 빠진 종목은 날짜로 — period 는 상장일 탓에 거절될 수 있다
        from datetime import timedelta
        start = (yi.kst_now().date() - timedelta(days=RETRY_DAYS[timeframe])).isoformat()
        period = None
    print(f"― 분봉 {timeframe} · {'첫 적재' if first else '최근 다시 받기'} "
          f"{'start=' + start if start else 'period=' + str(period)} · "
          f"{len(members)}종목 · 유니버스 {members[0]['version']} ―", flush=True)
    total = 0
    for rows in yi.fetch(members, timeframe, period=period, start=start):
        total += yi.upsert(conn, rows)
    n, d0, d1 = conn.execute("SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM price_intraday WHERE timeframe=?",
                             (timeframe,)).fetchone()
    print(f"  끝 — 이번에 넣은 봉 {total:,} · 표 전체 {timeframe} {n:,}봉 · {d0} ~ {d1}")
    _save_state({f"intraday_{timeframe}": {"rows_written": total, "table_rows": n, "from": d0, "to": d1,
                                          "first": first, "at": yi.kst_now().isoformat(timespec="seconds")}})
    return 0


def _save_state(patch: dict) -> None:
    config.ensure_dirs()
    cur = {}
    if STATE_FILE.exists():
        try:
            cur = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except ValueError:
            cur = {}
    cur.update(patch)
    STATE_FILE.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_status() -> int:
    conn = db.connect()
    print("― OHLCV 적재 상태 ―")
    for kind, k in pp.KINDS.items():
        st = dict(conn.execute("SELECT status, COUNT(*) FROM ingest_day WHERE source=? GROUP BY status",
                               (k.source,)).fetchall())
        table = "etf_daily" if kind == "etf" else "index_daily"
        n, d0, d1 = conn.execute(f"SELECT COUNT(*), MIN(bas_dt), MAX(bas_dt) FROM {table}").fetchone()
        print(f"  {kind:<6} 날짜 상태 {st or '-'} · 표 {n:,}행 · {d0} ~ {d1}")
    for tf in ("60m", "5m", "1m"):
        n, s, d0, d1 = conn.execute("SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(trade_date), MAX(trade_date) "
                                    "FROM price_intraday WHERE timeframe=?", (tf,)).fetchone()
        if n:
            print(f"  분봉 {tf:<4} {n:,}봉 · {s}종목 · {d0} ~ {d1}")
    u = yi.latest_universe(conn)
    print(f"  유니버스 {u[0]['version'] if u else '없음'} · {len(u)}종목")
    return 0


def cmd_crosscheck(n: int) -> int:
    """포털 일봉을 FinanceDataReader · 야후와 대조한다 — 거래대금 상위 ETF n 개 · 주요 지수.

    결과는 상태 폴더의 JSON 으로 남긴다(표로 쌓지 않는다 — 대조 출처는 정본이 아니다).
    """
    import FinanceDataReader as fdr
    import yfinance as yf

    conn = db.connect()
    day = conn.execute("SELECT MAX(bas_dt) FROM etf_daily").fetchone()[0]
    if not day:
        print("etf_daily 가 비었다 — `etf` 를 먼저 돌린다.")
        return 1
    start = conn.execute("SELECT MIN(bas_dt) FROM etf_daily WHERE bas_dt >= '20250101'").fetchone()[0]
    etfs = conn.execute("SELECT srtn_cd, itms_nm FROM etf_daily WHERE bas_dt=? ORDER BY tr_prc DESC LIMIT ?",
                        (day, n)).fetchall()
    iso = lambda s: f"{s[:4]}-{s[4:6]}-{s[6:]}"
    report = {"as_of": day, "from": start, "etf": [], "index": []}

    def compare(ref: dict, other) -> dict:
        hits = total = 0
        worst = 0.0
        for d, c in ref.items():
            v = other.get(d)
            if v is None:
                continue
            total += 1
            diff = abs(v - c)
            hits += diff <= max(1.0, abs(c) * 0.0001)
            worst = max(worst, diff / c if c else 0)
        return {"overlap": total, "match": round(hits / total, 4) if total else None, "max_rel_diff": round(worst, 6)}

    for code, name in etfs:
        ref = {iso(r[0]): float(r[1]) for r in conn.execute(
            "SELECT bas_dt, clpr FROM etf_daily WHERE srtn_cd=? AND bas_dt>=? AND clpr>0", (code, start))}
        row = {"symbol": code, "name": name}
        try:
            f = fdr.DataReader(code, iso(start), iso(day))
            row["fdr"] = compare(ref, {d.strftime("%Y-%m-%d"): float(v) for d, v in f["Close"].items()})
        except Exception as exc:
            row["fdr"] = {"error": type(exc).__name__}
        try:
            y = yf.download(code + ".KS", start=iso(start), interval="1d", progress=False, auto_adjust=False,
                            multi_level_index=False)
            row["yahoo"] = compare(ref, {d.strftime("%Y-%m-%d"): float(v) for d, v in y["Close"].items()})
        except Exception as exc:
            row["yahoo"] = {"error": type(exc).__name__}
        report["etf"].append(row)
        print(f"  ETF {code} {name[:18]:<18} FDR {row['fdr']}  야후 {row['yahoo']}", flush=True)

    for csf, nm, ytk, ftk in (("KOSPI시리즈", "코스피", "^KS11", "KS11"), ("KOSDAQ시리즈", "코스닥", "^KQ11", "KQ11"),
                              ("KOSPI시리즈", "코스피 200", "^KS200", "KS200")):
        ref = {iso(r[0]): float(r[1]) for r in conn.execute(
            "SELECT bas_dt, clpr FROM index_daily WHERE idx_csf=? AND idx_nm=? AND bas_dt>=?", (csf, nm, start))}
        row = {"index": f"{csf}:{nm}", "rows": len(ref)}
        for label, fn in (("fdr", lambda: fdr.DataReader(ftk, iso(start), iso(day))["Close"]),
                          ("yahoo", lambda: yf.download(ytk, start=iso(start), interval="1d", progress=False,
                                                        auto_adjust=False, multi_level_index=False)["Close"])):
            try:
                s = fn()
                # 지수는 소수 둘째 자리 — 같다의 기준을 0.01 포인트 · 0.01% 로 본다
                other = {d.strftime("%Y-%m-%d"): float(v) for d, v in s.items()}
                hits = sum(1 for d, c in ref.items() if d in other and abs(other[d] - c) <= max(0.011, abs(c) * 0.0001))
                tot = sum(1 for d in ref if d in other)
                row[label] = {"overlap": tot, "match": round(hits / tot, 4) if tot else None}
            except Exception as exc:
                row[label] = {"error": type(exc).__name__}
        report["index"].append(row)
        print(f"  지수 {row['index']:<18} {row}", flush=True)

    out = config.STATE_DIR / f"ohlcv_crosscheck_{day}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  보고서 {out}")
    return 0


def cmd_daily_update() -> int:
    """러너 단계 하나로 — 하나가 실패해도 나머지는 돈다(종료코드는 실패를 알린다)."""
    from datetime import timedelta
    from collector import ohlcv_export
    today = yi.kst_now().date()
    start = (today - timedelta(days=14)).strftime("%Y%m%d")
    rc = 0
    for kind in ("etf", "index"):
        rc = cmd_daily(kind, start, today.strftime("%Y%m%d"), None) or rc
    for tf in ("60m", "5m"):
        try:
            rc = cmd_intraday(tf, first=False, limit=None) or rc
        except Exception as exc:                  # 야후가 막혀도 일봉 · 내보내기는 계속
            print(f"  🔴 분봉 {tf} 실패: {type(exc).__name__}: {exc}")
            rc = rc or 1
    man = ohlcv_export.export()
    print(f"  내보내기 기준 {man['as_of']} · 행 {man['rows']}")
    return rc


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="python -m collector.ohlcv_load",
                                 description="OHLCV 적재 — ETF · 지수 일봉 · 분봉 유니버스 · 분봉 · 대조 · 상태")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="적재 상태")
    for kind in ("etf", "index"):
        p = sub.add_parser(kind, help=f"{kind} 일봉 백필(받은 날은 건너뜀)")
        p.add_argument("--start", default="20200102")
        p.add_argument("--end", default="20991231")
        p.add_argument("--limit", type=int)
    p = sub.add_parser("universe", help="분봉 대상 고르기 — 기본은 시가총액 순위 근사(u1), "
                                        "KRX 구성종목 파일 둘을 주면 공식 명단(u2)")
    p.add_argument("--as-of")
    p.add_argument("--kospi200", help="KRX 「지수구성종목」 코스피 200 CSV (data/collector/krx_manual/)")
    p.add_argument("--kosdaq150", help="KRX 「지수구성종목」 코스닥 150 CSV")
    p = sub.add_parser("intraday", help="분봉 받기")
    p.add_argument("--timeframe", choices=("60m", "5m", "1m"), required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--first", action="store_true", help="받을 수 있는 창 전체")
    g.add_argument("--recent", action="store_true", help="최근 며칠(매일)")
    p.add_argument("--limit", type=int, help="앞에서 N 종목만(시험용)")
    p.add_argument("--only-missing", action="store_true", help="명단에 새로 든 종목(봉이 하나도 없는 것)만")
    sub.add_parser("daily", help="매일 러너 단계 — ETF · 지수 최근 · 분봉 최근 · 내보내기")
    p = sub.add_parser("crosscheck", help="포털 일봉을 FDR · 야후와 대조")
    p.add_argument("--n", type=int, default=20)
    a = ap.parse_args(argv)

    if a.cmd == "status":
        return cmd_status()
    if a.cmd in ("etf", "index"):
        return cmd_daily(a.cmd, a.start, a.end, a.limit)
    if a.cmd == "universe":
        return cmd_universe(a.as_of, a.kospi200, a.kosdaq150)
    if a.cmd == "intraday":
        return cmd_intraday(a.timeframe, a.first, a.limit, a.only_missing)
    if a.cmd == "crosscheck":
        return cmd_crosscheck(a.n)
    if a.cmd == "daily":
        return cmd_daily_update()
    return 2


if __name__ == "__main__":
    sys.exit(main())
