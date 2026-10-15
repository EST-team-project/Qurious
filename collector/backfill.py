"""백필과 일일 수집 — 중단을 전제로 만든다.

1,648 거래일을 받는 데 하루 한도의 17% 를 쓴다. 시간으로는 한 시간 안팎이고, 그 사이에
노트북이 잠들거나 네트워크가 끊기거나 사람이 Ctrl+C 를 누른다. **그것이 정상이다.**
그래서 "처음부터 다시" 가 없게 만든다.

재개가 기대는 것은 ``ingest_day`` 표 하나다. 그 표와 ``raw_response`` 와 ``price_daily``
가 **한 트랜잭션에 함께** 쓰이기 때문에(sources/portal.py) 셋은 절대 어긋나지 않는다.

두 가지 모드
------------
``backfill``  과거 구간 전체. 안 받은 날만 받는다. 몇 번을 돌려도 같은 결과가 된다.
``recent``    최근 며칠을 되돌아보며 빈 날을 채운다. **일일 수집은 이 모드다.**

왜 일일 수집이 "당일 받기" 가 아닌가
------------------------------------
포털은 당일 시세를 당일에 주지 않는다. 실측 2026-09-19(토) 11:00 KST 에 09-18(금)
시세가 **아직 없었다**. 당일 basDt 를 찍는 일정은 영원히 0건을 받는다.

되돌아보기 창을 쓰면 지연이 하루든 이틀이든 알아서 메워진다. 지연의 정확한 길이를
알아낼 필요가 없어지는 것이 이 설계의 요점이다 — **모르는 값에 기대지 않는다.**

휴장 확정 규칙
--------------
빈 응답은 휴장일일 수도 있고 아직 안 올라온 거래일일 수도 있는데, 포털은 둘을 구분해
주지 않는다. 시간이 구분해 준다: 충분히 지난 날이 여전히 비어 있으면 그것은 휴장이다.
``SETTLE_DAYS`` 가 그 "충분히" 다.

종료코드 (DF-92 · 2026-10-15)
----------------------------
``0`` 받을 날을 다 처리했다(빈 날 — 아직 안 올라옴 · 휴장 — 은 실패가 아니다) · ``69`` 다 받지 못했다(실패한 날이 있거나 한도
소진 · 하루치가 나뉘어 와 멈췄다 — 받은 날은 저장했고 다음 실행이 빈 날을 다시 받는다) · ``1`` 그 밖의 예외. 고치기 전에는 늘
0 이라 일일 러너에 「✅ 시세」 로 보였다. 러너는 시세 단계의 69 를 경고로 센다(뒤 단계를 막지 않는다 · ``scripts/daily_update.py``
단계 정의의 ``warn_codes``).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import requests

from collector import config, db
from collector.console import utf8_stdio
from collector.ratelimit import BudgetExhausted, RateLimiter
from collector.sources import portal

#: 기준일이 이만큼 지났는데도 비어 있으면 **휴장으로 확정**한다.
#:
#: 10 일은 넉넉하게 잡은 값이다. 관측된 지연은 하루 남짓이었고(09-18 시세가 09-19 오전에
#: 아직 없었다), 연휴가 길어도 열흘을 넘기지 않는다. 짧게 잡으면 거래일을 휴장으로
#: 잘못 확정하고, 그 손해가 훨씬 크다.
SETTLE_DAYS = 10

#: 되돌아보기 창(일). 일일 수집이 매번 확인하는 범위.
#: 연휴 뒤에도 빠진 날이 이 안에 들어오도록 넉넉히 잡았다.
RECENT_WINDOW = 14

#: 포털이 자료를 주기 시작하는 시점. **2026-09-19 실측값** — ``probe-start`` 이분 탐색
#: 34회로 확인했다. 2019-12-27 주는 0건, 2019-12-30 주부터 자료가 있다. 2019년 마지막
#: 거래일(12-30)까지 포함하도록 그 주 월요일을 시작으로 잡는다 — 12-31 은 휴장이라 0건이다.
DEFAULT_START = date(2019, 12, 30)

#: 다 받지 못했다 — 실패한 날이 있거나(통신 · 응답 오류) 받다가 멈췄다(한도 소진 · 하루치가 나뉘어 옴). sysexits 의
#: ``EX_UNAVAILABLE``(출처가 다 주지 못함). 75(``EX_TEMPFAIL``)를 쓰지 않는 까닭 — 75 는 러너 · PC 작업자의 「지금은 못 돈다」
#: 라서, 단계 결과로 쓰면 회차 종료코드가 75 가 되어 작업자가 화면 수집 요청을 다시 대기로 돌린다(되풀이 · 2026-10-10 종료코드 약속).
#: 러너의 같은 값(``scripts/daily_update.py`` ``EX_UNAVAILABLE``)과 맞는지는 시험이 본다(TC-BF-05).
EX_UNAVAILABLE = 69


# ==================================================
# 1. 무엇을 받을지 고르기
# ==================================================
def day_states(conn: sqlite3.Connection) -> Dict[str, sqlite3.Row]:
    return {r["bas_dt"]: r for r in conn.execute(
        "SELECT * FROM ingest_day WHERE source='portal'")}


def pick_targets(conn: sqlite3.Connection, days: List[str], *,
                 today: Optional[date] = None, refetch: bool = False) -> List[str]:
    """받아야 할 날만 남긴다.

    - ``done``     이미 있다. 건너뛴다.
    - ``holiday``  휴장으로 확정됐다. 건너뛴다.
    - ``empty``    충분히 지난 날이면 휴장으로 확정하고 건너뛴다. 아직 최근이면 다시 받는다.
    - ``error``    다시 받는다.
    - 기록 없음    받는다.

    ``refetch=True`` 는 이 판단을 전부 무시하고 다시 받는다 — 출처가 과거 값을 정정한
    경우에 쓴다. 평소에 켜면 유량만 태운다.
    """
    today = today or datetime.now().date()
    states = day_states(conn)
    settle_before = (today - timedelta(days=SETTLE_DAYS)).strftime("%Y%m%d")

    out: List[str] = []
    promote: List[str] = []
    for d in days:
        if refetch:
            out.append(d)
            continue
        row = states.get(d)
        if row is None:
            out.append(d)
            continue
        st = row["status"]
        if st in ("done", "holiday"):
            continue
        if st == "empty":
            if d < settle_before:
                promote.append(d)      # 충분히 지났는데 비었다 → 휴장 확정
            else:
                out.append(d)          # 아직 올라올 수 있다 → 다시 확인
            continue
        out.append(d)                  # error 등

    if promote:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.executemany(
                "UPDATE ingest_day SET status='holiday', updated_at=?, "
                "message='SETTLE_DAYS 경과 후에도 0건 — 휴장으로 확정' "
                "WHERE source='portal' AND bas_dt=?",
                [(datetime.now().isoformat(timespec="seconds"), d) for d in promote])
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        print(f"  · 휴장 확정 {len(promote)}일 (빈 응답이 {SETTLE_DAYS}일 넘게 유지됨)")
    return out


# ==================================================
# 2. 러너
# ==================================================
def run(start: date, end: date, *, limit: Optional[int] = None,
        refetch: bool = False, quiet: bool = False) -> Dict[str, object]:
    """구간을 받는다. 한도가 바닥나면 **깔끔히 멈추고** 지금까지를 보고한다.

    돌려주는 것 — 날 수(``done`` · ``empty`` · ``error`` · ``rows`` · ``skipped``)와 멈춘 까닭 한 줄(``stopped`` · 없으면 빈 글).
    다 받지 못했으면(실패한 날 · 멈춤) 마지막 줄에 「🟡 다 받지 못했다」 를 한 번 찍는다 — 러너가 그 줄을 단계 까닭으로 잡는다.
    """
    conn = db.connect()
    limiter = RateLimiter(config.PORTAL_SLEEP, reserve=config.PORTAL_RESERVE, name="포털")
    session = requests.Session()

    days = portal.weekdays(start, end)
    targets = pick_targets(conn, days, refetch=refetch)
    if limit:
        targets = targets[:limit]

    tally: Dict[str, object] = {"done": 0, "empty": 0, "error": 0, "rows": 0,
                                "skipped": len(days) - len(targets), "stopped": ""}
    if not targets:
        print(f"받을 날이 없다 — 주중 {len(days):,}일이 모두 처리돼 있다.")
        conn.close()
        return tally

    print(f"대상 {len(targets):,}일 (주중 {len(days):,}일 중 {tally['skipped']:,}일은 이미 처리됨)")
    stopped = ""
    for i, d in enumerate(targets, 1):
        try:
            res = portal.fetch_day(conn, limiter, d, session=session)
        except BudgetExhausted as exc:
            stopped = str(exc)
            break
        except portal.PortalError as exc:
            # 설계 전제가 깨진 경우다(하루치가 한 번에 안 들어옴). 조용히 넘기지 않는다.
            stopped = str(exc)
            break

        if res.status == "error":
            portal.mark_error(conn, res)
        tally[res.status] = tally.get(res.status, 0) + 1
        tally["rows"] += res.rows

        if not quiet and (i % 25 == 0 or i == len(targets) or res.status == "error"):
            rem = f" · 남은유량 {limiter.remaining:,}" if limiter.remaining is not None else ""
            print(f"  [{i:>5}/{len(targets):,}] {d} {res.status:<5} "
                  f"{res.rows:>5}행{rem}" + (f"  {res.message[:60]}" if res.message else ""))

    conn.close()
    print(f"\n적재 {tally['done']:,}일 · 빈응답 {tally['empty']:,}일 · "
          f"실패 {tally['error']:,}일 · 누적 {tally['rows']:,}행")
    print(limiter.report())
    if stopped:
        print(f"\n중단됨:\n{stopped}")
        tally["stopped"] = stopped.strip().splitlines()[0]   # 까닭의 첫 줄만(「할 일」 줄은 로그에)
    if exit_code(tally):
        # 마지막 줄 — 러너의 실패 까닭 한 줄(`failure_line`)이 🔴 · 실패 표시 줄을 뒤에서부터 찾는다
        print(f"\n🟡 다 받지 못했다 — 실패 {tally['error']:,}일"
              + (f" · 멈춤: {tally['stopped']}" if tally["stopped"] else "")
              + f" · 받은 날은 저장했고 다음 실행이 빈 날을 다시 받는다(종료코드 {EX_UNAVAILABLE})")
    return tally


def exit_code(tally: Dict[str, object]) -> int:
    """결과 → 종료코드. 실패한 날이 있거나 멈췄으면 ``EX_UNAVAILABLE``(69), 아니면 0 — 빈 날(아직 안 올라옴)은 실패가 아니다."""
    return EX_UNAVAILABLE if (tally.get("error") or tally.get("stopped")) else 0


def run_recent(*, window: int = RECENT_WINDOW, quiet: bool = False) -> Dict[str, object]:
    """일일 수집. 최근 창 안에서 **빠진 날만** 채운다."""
    today = datetime.now().date()
    return run(today - timedelta(days=window), today, quiet=quiet)


# ==================================================
# 3. 자료가 언제부터 있는지 찾기
# ==================================================
def probe_start(earliest: date = date(2010, 1, 1)) -> Optional[str]:
    """이분 탐색으로 **자료가 있는 가장 이른 날**을 찾는다.

    하루씩 훑으면 수천 호출이 들지만 이분 탐색은 20회 안쪽이다. 경계가 휴장일에 걸릴 수
    있어, 0건을 만나면 그 주의 다른 평일도 확인한다.
    """
    conn = db.connect()
    limiter = RateLimiter(config.PORTAL_SLEEP, reserve=config.PORTAL_RESERVE, name="포털")
    session = requests.Session()

    def has_data(d: date) -> bool:
        """그 주(월~금) 중 하루라도 자료가 있으면 True."""
        monday = d - timedelta(days=d.weekday())
        for k in range(5):
            day = (monday + timedelta(days=k)).strftime("%Y%m%d")
            limiter.check_budget()
            limiter.wait()
            r = session.get(config.PORTAL_PRICE_URL, timeout=60, params={
                "serviceKey": config.portal_key(), "numOfRows": 1, "pageNo": 1,
                "resultType": "json", "basDt": day})
            limiter.observe(r.headers)
            try:
                total, _ = portal.parse(r.content)
            except Exception:
                continue
            if total:
                return True
        return False

    lo, hi = earliest, datetime.now().date() - timedelta(days=SETTLE_DAYS)
    if not has_data(hi):
        print("최근 구간에도 자료가 없다 — 키나 API 승인 상태를 먼저 확인한다.")
        conn.close()
        return None
    while (hi - lo).days > 7:
        # timedelta 를 2 로 나누면 마이크로초까지 딸려 와 경계가 흔들린다. 일수로만 나눈다.
        mid = lo + timedelta(days=(hi - lo).days // 2)
        if has_data(mid):
            hi = mid
        else:
            lo = mid
        print(f"  탐색 중 … {lo} ~ {hi} ({(hi - lo).days}일)  {limiter.report()}")
    conn.close()
    print(f"\n자료가 시작되는 주: {hi.strftime('%Y-%m-%d')} 언저리")
    print(f"  → collector/backfill.py 의 DEFAULT_START 를 이 값으로 고친다.")
    return hi.strftime("%Y%m%d")


# ==================================================
# 4. CLI
# ==================================================
def _parse_day(s: str) -> date:
    s = s.replace("-", "")
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(
        prog="python -m collector.backfill",
        description="공공데이터포털 일별 시세 수집 (중단·재개 가능)")
    p.add_argument("mode", choices=["backfill", "recent", "probe-start", "status"],
                   help="backfill=과거 구간 / recent=최근 빈 날 채우기 / "
                        "probe-start=자료 시작일 탐색 / status=현황만 보기")
    p.add_argument("--from", dest="start", help="시작일 YYYYMMDD (backfill 기본: DEFAULT_START)")
    p.add_argument("--to", dest="end", help="종료일 YYYYMMDD (기본: 오늘)")
    p.add_argument("--limit", type=int, help="이번 실행에서 받을 최대 일수 — 시험 삼아 돌릴 때")
    p.add_argument("--window", type=int, default=RECENT_WINDOW, help="recent 모드 되돌아보기 일수")
    p.add_argument("--refetch", action="store_true",
                   help="이미 받은 날도 다시 받는다 (출처가 과거 값을 정정한 경우에만)")
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args(argv)

    if a.mode == "probe-start":
        probe_start()
        return 0
    if a.mode == "status":
        print_status()
        return 0
    if a.mode == "recent":
        return exit_code(run_recent(window=a.window, quiet=a.quiet))

    start = _parse_day(a.start) if a.start else DEFAULT_START
    end = _parse_day(a.end) if a.end else datetime.now().date()
    return exit_code(run(start, end, limit=a.limit, refetch=a.refetch, quiet=a.quiet))


def print_status() -> None:
    """지금까지 무엇이 쌓였는지. 숫자를 추측해서 보고하지 않으려고 둔다."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT status, COUNT(*) n, SUM(rows) r FROM ingest_day "
        "WHERE source='portal' GROUP BY status ORDER BY status").fetchall()
    print("― 수집 현황 (portal) ―")
    if not rows:
        print("  아직 아무것도 받지 않았다.")
    for r in rows:
        print(f"  {r['status']:<8} {r['n']:>6,}일  {(r['r'] or 0):>12,}행")
    span = conn.execute(
        "SELECT MIN(bas_dt) a, MAX(bas_dt) b, COUNT(DISTINCT bas_dt) d, COUNT(*) n "
        "FROM price_daily").fetchone()
    if span and span["n"]:
        print(f"\n― price_daily ―\n  {span['a']} ~ {span['b']}  "
              f"거래일 {span['d']:,}일 · {span['n']:,}행")
        mk = conn.execute(
            "SELECT mrkt_ctg, COUNT(DISTINCT srtn_cd) c FROM price_daily "
            "GROUP BY mrkt_ctg ORDER BY c DESC").fetchall()
        print("  시장별 종목수: " + " · ".join(f"{m['mrkt_ctg']} {m['c']:,}" for m in mk))
    from collector import raw_store
    st = raw_store.stats(conn)
    if st:
        print("\n― 원문 보존 ―")
        for src, s in st.items():
            print(f"  {src:<8} {s['responses']:>6,}건 · 원문 {s['raw_bytes']/1e6:>8.1f} MB "
                  f"→ 저장 {s['stored_bytes']/1e6:>7.1f} MB ({(s['ratio'] or 0)*100:.1f}%)")
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
