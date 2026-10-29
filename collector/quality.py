"""데이터 품질 검사 — 결측 · 중복 · 정합성 (할 일 ①-12 `SCH-DQ` · 2026-10-29 착수).

    python -m collector.quality                  최근 20 거래일 검사 — 읽기만(수집 DB 를 읽기 전용으로 연다)
    python -m collector.quality --days 60 --json
    python -m collector.quality --write          결과를 state/data_quality_last.json 에 쓴다(러너 단계 · 데이터 관제가 읽을 자리)
    python -m collector.quality --strict         경고가 하나라도 있으면 종료코드 1(기본은 경고만 — 항상 0)

**처음엔 경고만 한다**(할 일 문서의 결정). 러너에 단계로 붙일 때도 `fatal=False` — 이 검사가 회차를 막지 않는다.
검사 하나가 예외를 내도 그 검사만 `error` 로 적고 나머지는 계속한다(품질 검사 때문에 12:30 회차가 깨지면 안 된다).

검사(시세가 있는 최근 N 거래일 창 · 시세가 정본이라 「최근 N 거래일」 은 price_daily 의 날짜로 센다)
  결측  PD-GAP     평일인데 시세가 없는 날 — 달력(market_calendar)이 휴장 사유를 모르는 날만(설날 · 추석 같은 사유가 있으면 정상)
        PD-THIN    그날 행 수가 창 중앙값의 90% 미만(일부만 들어온 날)
        ETF-GAP    시세가 있는 날인데 ETF 시세 · 지수 시세가 없는 날(IDX-GAP)
        ADJ-COVER  시세는 있는데 수정주가 행이 없는 것 · TR-COVER 는 총수익 지수
  중복  PD-DUP     같은 (날짜 · 종목) 이 두 번 이상(기본키가 막아 보통 0 — 표를 다시 만들다 깨졌는지 보는 안전망)
  정합  PD-OHLC    고가 < max(종가 · 시가 · 저가) 또는 저가 > min(종가 · 시가 · 고가) — 네 값이 모두 양수인 행만
        PD-NONPOS  종가가 0 이하 · 비었거나 거래량이 음수 · 빈 행
        INGEST     포털 적재 기록이 done · holiday 가 아닌 날(가장 최근 날은 아직 안 올라왔을 수 있어 뺀다)
  참고  PD-NOOPEN  시가가 0 인 행 — 거래정지 · 시가 미형성에서 흔해 경고가 아니라 알림(info)

상태: ok(0건) · warn(1건 이상) · info(참고) · error(검사가 예외를 냄).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

if __package__ in (None, ""):                 # python collector/quality.py 로 불러도 collector 가 보이게
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):           # git bash(cp949)에서 줄표 · 그림 글자로 죽지 않게
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

_KST = timezone(timedelta(hours=9))
#: 행 수가 창 중앙값의 이 비율 미만이면 「일부만 들어온 날」
THIN_RATIO = 0.9
#: 표본으로 보여 줄 최대 개수
SAMPLE_N = 5
#: 이 포털 적재 출처는 거래일마다 done 이어야 한다
PORTAL_SOURCES = ("portal", "portal_etf", "portal_index")

LABELS = {
    "PD-GAP": "시세 없는 평일(휴장 사유 모름)",
    "PD-THIN": "행 수가 적은 날",
    "ETF-GAP": "ETF 시세 없는 거래일",
    "IDX-GAP": "지수 시세 없는 거래일",
    "ADJ-COVER": "수정주가 빠진 시세 행",
    "TR-COVER": "총수익 지수 빠진 시세 행",
    "PD-DUP": "(날짜 · 종목) 중복",
    "PD-OHLC": "고가 · 저가 관계 위반",
    "PD-NONPOS": "종가 0 이하 · 빈 값 · 음수 거래량",
    "INGEST": "포털 적재가 done 이 아닌 날",
    "PD-NOOPEN": "시가 0 행(참고)",
}


def _window(conn: sqlite3.Connection, days: int) -> list[str]:
    """시세가 있는 최근 N 날짜(YYYYMMDD · 오름차순)."""
    rows = conn.execute("select distinct bas_dt from price_daily order by bas_dt desc limit ?", (days,)).fetchall()
    return sorted(r[0] for r in rows)


def _iso(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def _result(check: str, count: int, sample: list, detail: str = "", info: bool = False) -> dict:
    status = "ok" if count == 0 else ("info" if info else "warn")
    return {"check": check, "label": LABELS[check], "status": status, "count": count,
            "sample": [str(s) for s in sample[:SAMPLE_N]], "detail": detail}


def _pd_gap(conn, win: list[str]) -> dict:
    have = set(win)
    first, last = win[0], win[-1]
    cal = {r[0]: (r[1], r[2] or "") for r in conn.execute(
        "select replace(cal_date,'-',''), is_trading_day, reason from market_calendar where cal_date between ? and ?",
        (_iso(first), _iso(last)))}
    bad, d = [], datetime.strptime(first, "%Y%m%d").date()
    end = datetime.strptime(last, "%Y%m%d").date()
    while d <= end:
        key = d.strftime("%Y%m%d")
        if d.weekday() < 5 and key not in have:
            trading, reason = cal.get(key, (None, ""))
            if not reason:                      # 달력이 사유(공휴일 이름)를 모르는 평일 휴장 · 달력에 행이 없는 날
                bad.append(key)
        d += timedelta(days=1)
    return _result("PD-GAP", len(bad), bad, "평일인데 시세가 없고 달력도 사유를 모른다 — 수집이 빠졌거나 달력이 낡았다")


def _pd_thin(conn, win: list[str]) -> dict:
    counts = dict(conn.execute("select bas_dt, count(*) from price_daily where bas_dt >= ? group by bas_dt", (win[0],)).fetchall())
    med = statistics.median(counts.get(d, 0) for d in win)
    bad = [f"{d}:{counts.get(d, 0)}행" for d in win if counts.get(d, 0) < med * THIN_RATIO]
    return _result("PD-THIN", len(bad), bad, f"창 중앙값 {med:g}행의 {int(THIN_RATIO * 100)}% 미만")


def _gap_in(table: str, check: str):
    def run(conn, win):
        have = {r[0] for r in conn.execute(f"select distinct bas_dt from {table} where bas_dt >= ?", (win[0],))}
        bad = [d for d in win if d not in have]
        return _result(check, len(bad), bad, f"시세가 있는 날인데 {table} 행이 0")
    return run


def _coverage(table: str, check: str):
    def run(conn, win):
        n, = conn.execute(
            f"select count(*) from price_daily p left join {table} a on a.bas_dt=p.bas_dt and a.srtn_cd=p.srtn_cd "
            "where p.bas_dt >= ? and a.srtn_cd is null", (win[0],)).fetchone()
        s = [f"{d}:{c}" for d, c in conn.execute(
            f"select p.bas_dt, count(*) from price_daily p left join {table} a on a.bas_dt=p.bas_dt and a.srtn_cd=p.srtn_cd "
            "where p.bas_dt >= ? and a.srtn_cd is null group by p.bas_dt order by p.bas_dt desc limit ?", (win[0], SAMPLE_N))]
        return _result(check, n, s, f"price_daily 행 가운데 {table} 에 짝이 없는 것(날짜:행 수)")
    return run


def _pd_dup(conn, win):
    rows = conn.execute("select bas_dt, srtn_cd, count(*) from price_daily where bas_dt >= ? group by bas_dt, srtn_cd having count(*) > 1", (win[0],)).fetchall()
    return _result("PD-DUP", len(rows), [f"{d}/{c}×{n}" for d, c, n in rows], "같은 날짜 · 종목이 둘 이상")


def _pd_ohlc(conn, win):
    where = ("bas_dt >= ? and clpr > 0 and mkp > 0 and hipr > 0 and lopr > 0 "
             "and (hipr < max(clpr, mkp, lopr) or lopr > min(clpr, mkp, hipr))")
    n, = conn.execute(f"select count(*) from price_daily where {where}", (win[0],)).fetchone()
    s = [f"{d}/{c}" for d, c in conn.execute(f"select bas_dt, srtn_cd from price_daily where {where} limit ?", (win[0], SAMPLE_N))]
    return _result("PD-OHLC", n, s, "네 가격이 모두 양수인 행만 본다")


def _pd_nonpos(conn, win):
    where = "bas_dt >= ? and (clpr is null or clpr <= 0 or trqu is null or trqu < 0)"
    n, = conn.execute(f"select count(*) from price_daily where {where}", (win[0],)).fetchone()
    s = [f"{d}/{c}" for d, c in conn.execute(f"select bas_dt, srtn_cd from price_daily where {where} limit ?", (win[0], SAMPLE_N))]
    return _result("PD-NONPOS", n, s)


def _pd_noopen(conn, win):
    n, = conn.execute("select count(*) from price_daily where bas_dt >= ? and (mkp is null or mkp <= 0)", (win[0],)).fetchone()
    total, = conn.execute("select count(*) from price_daily where bas_dt >= ?", (win[0],)).fetchone()
    return _result("PD-NOOPEN", n, [], f"창 {total}행 중 {n}행({(n / total * 100 if total else 0):.1f}%) — 거래정지 · 시가 미형성에서 흔하다", info=True)


def _ingest(conn, win):
    marks = ",".join("?" * len(PORTAL_SOURCES))
    # **시세가 있는 날만** 본다 — 시세가 없는 날의 `empty` 는 휴장일(2020 총선 · 대체공휴일 등 실측 41일)이라 정상이다.
    # 그래서 가장 최근 시세 날짜 뒤의 날(아직 안 올라온 날)도 저절로 빠진다. 휴장 사유를 모르는 공백은 PD-GAP 이 본다.
    rows = conn.execute(
        f"select source, bas_dt, status from ingest_day where source in ({marks}) and bas_dt >= ? and bas_dt <= ? "
        "and status not in ('done', 'holiday') "
        "and bas_dt in (select distinct bas_dt from price_daily where bas_dt >= ?) order by bas_dt desc",
        (*PORTAL_SOURCES, win[0], win[-1], win[0])).fetchall()
    return _result("INGEST", len(rows), [f"{s}/{d}={st}" for s, d, st in rows], "시세가 있는 날인데 적재 기록이 done · holiday 가 아니다")


CHECKS: list[tuple[str, Callable]] = [
    ("PD-GAP", _pd_gap), ("PD-THIN", _pd_thin),
    ("ETF-GAP", _gap_in("etf_daily", "ETF-GAP")), ("IDX-GAP", _gap_in("index_daily", "IDX-GAP")),
    ("ADJ-COVER", _coverage("price_adjusted", "ADJ-COVER")), ("TR-COVER", _coverage("price_total_return", "TR-COVER")),
    ("PD-DUP", _pd_dup), ("PD-OHLC", _pd_ohlc), ("PD-NONPOS", _pd_nonpos), ("INGEST", _ingest), ("PD-NOOPEN", _pd_noopen),
]


def run(conn: sqlite3.Connection, days: int = 20) -> dict:
    """검사를 모두 돌려 결과 사전을 돌려준다 — 검사 하나가 예외를 내도 그 검사만 error 로 적는다. 시세가 없으면 빈 결과."""
    out: dict = {"at": datetime.now(_KST).isoformat(timespec="seconds"), "days": days, "checks": []}
    try:
        win = _window(conn, days)
    except sqlite3.Error as exc:
        out.update(window=None, warn=0, error=1, note=f"창을 정하지 못했다({type(exc).__name__}: {exc})")
        return out
    if not win:
        out.update(window=None, warn=0, error=0, note="price_daily 에 시세가 없다")
        return out
    out["window"] = [win[0], win[-1]]
    out["window_days"] = len(win)
    for check, fn in CHECKS:
        try:
            out["checks"].append(fn(conn, win))
        except Exception as exc:                  # 품질 검사 때문에 회차가 깨지면 안 된다
            out["checks"].append({"check": check, "label": LABELS[check], "status": "error", "count": 0, "sample": [],
                                  "detail": f"검사가 예외를 냈다({type(exc).__name__}: {exc})"})
    out["warn"] = sum(1 for c in out["checks"] if c["status"] == "warn")
    out["error"] = sum(1 for c in out["checks"] if c["status"] == "error")
    return out


def render(result: dict) -> str:
    lines = []
    if result.get("window"):
        a, b = result["window"]
        lines.append(f"― 데이터 품질 · 시세 {a}~{b}({result['window_days']} 거래일) · 경고 {result['warn']} · 오류 {result['error']}")
    else:
        lines.append(f"― 데이터 품질 · {result.get('note', '창 없음')}")
    mark = {"ok": "✅", "warn": "🟡", "info": "ℹ️ ", "error": "🔴"}
    for c in result["checks"]:
        extra = f" · 예 {', '.join(c['sample'])}" if c["sample"] else ""
        lines.append(f"  {mark[c['status']]} {c['check']:<9} {c['label']} — {c['count']}건{extra}")
        if c["status"] in ("warn", "error", "info") and c["detail"]:
            lines.append(f"       {c['detail']}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    from collector import config

    ap = argparse.ArgumentParser(description="데이터 품질 검사(결측 · 중복 · 정합성) — 경고만")
    ap.add_argument("--days", type=int, default=20, help="검사할 최근 거래일 수(기본 20)")
    ap.add_argument("--json", action="store_true", help="JSON 으로 출력")
    ap.add_argument("--write", action="store_true", help="state/data_quality_last.json 에 결과를 쓴다")
    ap.add_argument("--strict", action="store_true", help="경고 · 오류가 있으면 종료코드 1")
    ap.add_argument("--db", type=Path, default=config.DB_PATH, help="수집 DB(기본 data/collector/market.sqlite3)")
    a = ap.parse_args(argv)

    conn = sqlite3.connect(f"file:{a.db.as_posix()}?mode=ro", uri=True, timeout=30)   # 읽기 전용 — 이 검사는 DB 를 바꾸지 않는다
    try:
        result = run(conn, a.days)
    finally:
        conn.close()
    print(json.dumps(result, ensure_ascii=False, indent=1) if a.json else render(result))
    if a.write:
        path = config.STATE_DIR / "data_quality_last.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
        print(f"  → {path}")
    return 1 if a.strict and (result.get("warn") or result.get("error")) else 0


if __name__ == "__main__":
    sys.exit(main())
