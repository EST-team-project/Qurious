"""데이터 상태 — 「데이터가 언제 것인가 · 매일 갱신이 돌았나」 를 한 번에 (목표 기능 ① W4 · 설계서 5.2.2).

`GET /api/data/status` 가 부른다. 지금의 `GET /api/system/sync-status` 는 **외부 시세 캐시**의 신선도라
그대로 두고, 화면의 「데이터 기준일」 은 이것을 본다(설계서 5.2.2).

읽는 것 — 전부 읽기 전용(앱은 수집 DB 에 쓰지 않는다)
  - 러너 기록   data/collector/state/daily_update_last.json · daily_update_history.jsonl · daily_update.lock
  - 수집 DB     표별 행 수 · 마지막 날짜(`collector_db.db_path()` — 도커에서는 /app/data/csv/collector)
  - 거래일 달력 market_calendar — 「몇 거래일 늦었나」 를 세는 자. 없으면 평일로 어림하고 `approx` 를 켠다
  - HF 기록     data/hf_export/meta/manifest.json(krx-daily-market) · data/collector/ohlcv_export/manifest.json(krx-ohlcv)

늦음 판정 — 포털은 그날 시세를 **다음 날 낮**에 준다(collector/README §7)
  표의 마지막 날 뒤 · 오늘 앞에 있는 거래일 수(n)로 가른다.
    n = 0 최신 · 1 정상(12:30 갱신 전이면 보통 하루 밀려 있다) · 2 늦음 · 3 이상 멈춤
  계산 표(수정주가 · TR · 자체 지수)는 주식 일봉과 같은 날이어야 정상이다.

러너가 도는지는 컨테이너에서 PID 로 확인할 수 없다 — 잠금 파일이 있고 4시간 안이면 「도는 중」 으로 본다
(러너의 LOCK_STALE_HOURS 와 같은 값).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.services import collector_db

KST = timezone(timedelta(hours=9))

#: 러너가 매일 도는 시각(scripts/daily_update.py DEFAULT_TIME). 다른 PC 는 작업 스케줄러에 등록해야 돈다.
SCHEDULE_HM = (12, 30)
LOCK_STALE_HOURS = 4
HISTORY_N = 7
CACHE_SECONDS = 30

#: 러너 단계 — 이름 · 실패하면 뒤를 멈추는가(scripts/daily_update.py STEPS 와 같은 차례)
STEPS = {
    "price": ("주식 시세", True),
    "dividend": ("배당 공시", False),
    "disclosure": ("공시 목록", False),
    "financial": ("재무 주요계정", False),
    "search": ("검색 색인", False),
    "calendar": ("거래일 달력 · 일정", False),
    "adjusted": ("수정주가", True),
    "total_return": ("총수익(TR)", True),
    "benchmark": ("자체 지수", True),
    "ohlcv": ("ETF · 지수 · 분봉", False),
    "manifest": ("지문", False),
    "export": ("HF 내보내기", True),
    "verify": ("HF 검증", True),
    "upload": ("HF 올리기 · 일봉", True),
    "ohlcv_upload": ("HF 올리기 · OHLCV", False),
}

#: (키, 표, 이름, 묶음, 출처, 판정 방식, 마지막 날짜 SQL, 행 수 SQL)
TABLES = [
    ("price_daily", "price_daily", "주식 일봉(원 가격)", "시세", "공공데이터포털 주식시세정보", "portal",
     "SELECT MAX(bas_dt) FROM price_daily", "SELECT COUNT(*) FROM price_daily"),
    ("etf_daily", "etf_daily", "ETF 일봉", "시세", "공공데이터포털 증권상품시세정보", "portal",
     "SELECT MAX(bas_dt) FROM etf_daily", "SELECT COUNT(*) FROM etf_daily"),
    ("index_daily", "index_daily", "지수 일봉", "시세", "공공데이터포털 지수시세정보", "portal",
     "SELECT MAX(bas_dt) FROM index_daily", "SELECT COUNT(*) FROM index_daily"),
    ("price_adjusted", "price_adjusted", "수정주가", "계산", "주식 일봉에서 계산", "derived",
     "SELECT MAX(bas_dt) FROM price_adjusted", "SELECT COUNT(*) FROM price_adjusted"),
    ("price_total_return", "price_total_return", "총수익(TR)", "계산", "수정주가 + 배당에서 계산", "derived",
     "SELECT MAX(bas_dt) FROM price_total_return", "SELECT COUNT(*) FROM price_total_return"),
    ("benchmark_index", "benchmark_index", "자체 재현 지수", "계산", "수정주가 · TR 에서 계산", "derived",
     "SELECT MAX(bas_dt) FROM benchmark_index", "SELECT COUNT(*) FROM benchmark_index"),
    ("dividend", "dividend", "배당 공시", "공시", "전자공시(DART) — 마지막 공시 접수일", "info",
     "SELECT MAX(substr(rcept_no, 1, 8)) FROM dividend", "SELECT COUNT(*) FROM dividend"),
    ("disclosure", "disclosure", "공시 목록", "공시", "전자공시(DART) 상장사 공시 — 마지막 접수일", "info",
     "SELECT MAX(rcept_dt) FROM disclosure", "SELECT COUNT(*) FROM disclosure"),
    ("financial_statement", "financial_statement", "재무 주요계정", "공시",
     "전자공시(DART) 다중회사 주요계정 — 마지막으로 값이 실린 보고서 접수일", "info",
     "SELECT MAX(known_at) FROM financial_statement", "SELECT COUNT(*) FROM financial_statement"),
    ("intraday_60m", "price_intraday", "60분봉", "분봉", "야후 파이낸스(09:00~15:00)", "intraday",
     "SELECT MAX(trade_date) FROM price_intraday WHERE timeframe = '60m'",
     "SELECT COUNT(*) FROM price_intraday WHERE timeframe = '60m'"),
    ("intraday_5m", "price_intraday", "5분봉", "분봉", "야후 파이낸스(09:00~15:00)", "intraday",
     "SELECT MAX(trade_date) FROM price_intraday WHERE timeframe = '5m'",
     "SELECT COUNT(*) FROM price_intraday WHERE timeframe = '5m'"),
    ("market_calendar", "market_calendar", "거래일 달력", "일정", "특일 정보(한국천문연구원) + 거래소 규칙", "calendar",
     "SELECT MAX(cal_date) FROM market_calendar", "SELECT COUNT(*) FROM market_calendar"),
    ("market_event", "market_event", "금융 일정", "일정", "휴장 · 파생 만기 · 배당", "info",
     "SELECT MAX(event_date) FROM market_event", "SELECT COUNT(*) FROM market_event"),
]

VERDICT_LABEL = {"fresh": "최신", "ok": "정상", "late": "늦음", "stale": "멈춤", "missing": "없음", "info": "참고"}
_RANK = {"fresh": 0, "ok": 0, "info": 0, "late": 1, "missing": 1, "stale": 2}

_cache: dict = {}

#: 표별 행 수 — **뒤에서 센다**(2026-10-02 · W4). 앱이 다시 켜진 뒤 첫 호출에서 컨테이너가 큰 표 다섯의 COUNT(*) 에
#: 14.8초를 썼다(바인드 마운트 · 실측 — 마지막 날 찾기는 모두 수 ms · 점검 스크립트에서 21초). 그동안 화면이 멈추지 않게
#: 응답은 곧바로 지난 값(없으면 「세는 중」 · 줄 수 None)으로 주고, 세기는 스레드 하나가 맡는다.
#: DB 파일(본 파일 + WAL)의 크기 · 시각이 그대로면 다시 세지 않고, 러너가 큰 표를 다시 쓰는 동안은(파일이 몇 초마다
#: 바뀐다 · 그때 COUNT(*) 가 16초까지) 지난 값을 쓴다.
_counts: dict = {"sig": None, "rows": {}, "at": None}
_count_lock = threading.Lock()
_count_job: dict = {"thread": None, "error": None}


def _now() -> datetime:
    return datetime.now(KST)


def _iso_day(v: str | None) -> str | None:
    """YYYYMMDD · YYYY-MM-DD 둘 다 YYYY-MM-DD 로."""
    if not v:
        return None
    v = str(v)
    return f"{v[:4]}-{v[4:6]}-{v[6:8]}" if len(v) == 8 and v.isdigit() else v[:10]


def collector_dir() -> Path | None:
    """수집기 자료 폴더 — 로컬은 data/collector, 도커는 data/csv/collector."""
    p = collector_db.db_path()
    if p is not None:
        return p.parent
    for cand in collector_db._DEFAULT_CANDIDATES:  # noqa: SLF001 — 같은 후보를 쓴다(DB 파일만 없을 때)
        if cand.parent.is_dir():
            return cand.parent
    return None


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _parse_ts(v: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(v) if v else None
    except ValueError:
        return None


# ── 러너 ──────────────────────────────────────────────────────────────────
def _step_view(rec: dict) -> dict:
    name = rec.get("name", "")
    label, fatal = STEPS.get(name, (name, False))
    rc = rec.get("rc")
    if rc is None:
        status = "skipped"
    elif rc == 0:
        status = "ok"
    else:
        status = "failed" if fatal else "warning"
    return {"name": name, "label": label, "status": status, "rc": rc,
            "seconds": rec.get("seconds") or 0, "note": rec.get("note") or ""}


def runner_state(state_dir: Path | None, now: datetime) -> dict:
    hh, mm = SCHEDULE_HM
    today_run = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    nxt = today_run if now < today_run else today_run + timedelta(days=1)
    out: dict = {"schedule": f"매일 {hh:02d}:{mm:02d}", "next_expected": nxt.isoformat(timespec="minutes"),
                 "schedule_note": "이 PC 의 작업 스케줄러 설정 기준 — 다른 PC 는 등록해야 돈다(scripts/daily_update.py install)",
                 "running": False, "last": None, "history": []}
    if state_dir is None or not state_dir.is_dir():
        out.update(state="missing", label="기록 없음", detail="러너 기록 폴더가 없다 — 이 PC 에서 일일 갱신을 돌린 적이 없다")
        return out

    lock = _read_json(state_dir / "daily_update.lock")
    since = _parse_ts((lock or {}).get("started_at"))
    if since and (now - since) < timedelta(hours=LOCK_STALE_HOURS):
        out["running"] = True
        out["running_since"] = since.isoformat(timespec="seconds")

    last = _read_json(state_dir / "daily_update_last.json")
    if last:
        steps = [_step_view(s) for s in last.get("steps") or []]
        started, finished = _parse_ts(last.get("started_at")), _parse_ts(last.get("finished_at"))
        out["last"] = {
            "started_at": last.get("started_at"),
            "finished_at": last.get("finished_at"),
            "minutes": round((finished - started).total_seconds() / 60, 1) if started and finished else None,
            "ok": bool(last.get("ok")),
            "upload": bool(last.get("upload")),
            "stopped": last.get("stopped"),
            "derived": last.get("derived"),
            "steps": steps,
            "price_max": _iso_day((last.get("after") or {}).get("price_max")),
        }

    hist_path = state_dir / "daily_update_history.jsonl"
    try:
        lines = hist_path.read_text(encoding="utf-8").splitlines()[-HISTORY_N:]
    except OSError:
        lines = []
    for ln in reversed(lines):
        try:
            h = json.loads(ln)
        except ValueError:
            continue
        s, f = _parse_ts(h.get("started_at")), _parse_ts(h.get("finished_at"))
        out["history"].append({
            "started_at": h.get("started_at"),
            "ok": h.get("ok") if "skipped" not in h else None,
            "skipped": h.get("skipped"),
            "stopped": h.get("stopped"),
            "minutes": round((f - s).total_seconds() / 60, 1) if s and f else None,
            "price_max": _iso_day(h.get("price_max")),
        })

    # 판정 — 도는 중 > 실패 > 오늘 회차 없음 > 일부 실패 > 성공
    lr = out["last"]
    ran_today = bool(lr and (lr["started_at"] or "")[:10] == now.date().isoformat())
    out["ran_today"] = ran_today
    if out["running"]:
        out.update(state="running", label="도는 중", detail=f"{out['running_since'][11:16]} 에 시작했다")
    elif not lr:
        out.update(state="missing", label="기록 없음", detail="일일 갱신이 끝난 기록이 없다")
    elif not lr["ok"] and lr["stopped"]:
        out.update(state="failed", label="실패", detail=f"멈춘 단계: {lr['stopped']}")
    elif not ran_today and now >= today_run + timedelta(hours=1):
        out.update(state="late", label="오늘 회차 없음",
                   detail="12:30 회차 기록이 아직 없다 — PC 가 꺼져 있었으면 켜진 뒤 돈다(작업 스케줄러 StartWhenAvailable)")
    elif any(s["status"] in ("failed", "warning") for s in lr["steps"]):
        bad = [s["label"] for s in lr["steps"] if s["status"] in ("failed", "warning")]
        out.update(state="warning", label="일부 실패", detail="실패한 단계: " + " · ".join(bad))
    else:
        out.update(state="ok", label="성공", detail=f"{(lr['finished_at'] or '')[:16].replace('T', ' ')} 에 끝났다")
    return out


# ── 표 ────────────────────────────────────────────────────────────────────
def _connect_ro() -> sqlite3.Connection | None:
    path = collector_db.db_path()
    if path is None:
        return None
    try:
        return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _trading_after(conn: sqlite3.Connection, has_cal: bool, after: str, before: str) -> tuple[list[str], bool]:
    """`after` 뒤 · `before` 앞의 거래일. 달력이 없으면 평일로 어림한다(두 번째 값 = 어림)."""
    if has_cal:
        rows = conn.execute("SELECT cal_date FROM market_calendar WHERE is_trading_day = 1 "
                            "AND cal_date > ? AND cal_date < ? ORDER BY cal_date", (after, before)).fetchall()
        # 달력이 그 구간을 덮지 못하면(끝을 넘김) 평일로 어림한다
        end = conn.execute("SELECT MAX(cal_date) FROM market_calendar").fetchone()[0] or ""
        if end >= before:
            return [r[0] for r in rows], False
    out, d = [], date.fromisoformat(after) + timedelta(days=1)
    stop = date.fromisoformat(before)
    while d < stop:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out, True


def _verdict_portal(n: int) -> str:
    return "fresh" if n == 0 else "ok" if n == 1 else "late" if n == 2 else "stale"


def _db_sig(path: Path | None):
    if path is None:
        return None
    out = []
    for f in (path, path.with_name(path.name + "-wal")):
        try:
            st = f.stat()
        except OSError:
            out.append(None)
            continue
        # 0바이트 WAL 은 「쓴 것 없음」 — 읽기 전용 연결이 처음 읽을 때 빈 WAL 을 만든다(없는 것과 같게 친다)
        out.append(None if f.name.endswith("-wal") and st.st_size == 0 else (st.st_mtime_ns, st.st_size))
    return tuple(out)


def _count_rows(path: Path, sig) -> None:
    """(스레드) 표마다 행 수를 세어 `_counts` 에 둔다. 다 세면 30초 응답 캐시를 비워 다음 호출이 새 값을 보게 한다.
    세기를 시작할 때의 파일 지문을 함께 적는다 — 세는 사이에 파일이 바뀌었으면 다음 호출이 다시 센다."""
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            rows = {key: conn.execute(count_sql).fetchone()[0]
                    for key, table, *_rest, count_sql in TABLES if _has_table(conn, table)}
        finally:
            conn.close()
        with _count_lock:
            _counts.update(sig=sig, rows=rows, at=_now().isoformat(timespec="seconds"))
            _count_job["error"] = None
        _cache.clear()
    except sqlite3.Error as e:            # 세지 못하면 지난 값을 두고 까닭만 남긴다(다음 호출이 다시 시도)
        with _count_lock:
            _count_job["error"] = str(e)


def start_count(*, wait: bool = False) -> bool:
    """행 수 세기를 뒤에서 시작한다 — 이미 도는 중이면 그대로 둔다(스레드는 하나). 새로 시작했으면 참.
    `wait` 는 시험 · 명령 줄에서 끝날 때까지 기다릴 때만 쓴다(화면 요청은 기다리지 않는다)."""
    path = collector_db.db_path()
    if path is None:
        return False
    with _count_lock:
        t = _count_job["thread"]
        started = not (t is not None and t.is_alive())
        if started:
            t = threading.Thread(target=_count_rows, args=(path, _db_sig(path)), name="data-status-count", daemon=True)
            _count_job["thread"] = t
            t.start()
    if wait:
        t.join()
    return started


def counts_view(*, running: bool) -> tuple[dict, str]:
    """지금 쓸 행 수와 그 상태.

    fresh   파일이 마지막으로 센 뒤 그대로다 — 그 값
    old     파일이 바뀌었다 — 지난 값을 주고 뒤에서 다시 센다(러너가 쓰는 중이면 끝날 때까지 다시 세지 않는다)
    pending 아직 한 번도 못 셌다(앱을 켠 뒤 처음) — 뒤에서 세기 시작하고 빈 값을 준다
    """
    sig = _db_sig(collector_db.db_path())
    with _count_lock:
        same = sig is not None and sig == _counts["sig"]
        rows = dict(_counts["rows"])
    if same:
        return rows, "fresh"
    # 러너가 쓰는 동안은 파일이 몇 초마다 바뀐다 — 지난 값이 있으면 새로 세지 않는다(세는 사이에 또 낡는다)
    if not (running and rows):
        start_count()
    return rows, ("old" if rows else "pending")


def table_states(conn: sqlite3.Connection | None, today: date, rows_map: dict | None = None) -> tuple[list[dict], dict]:
    """표마다 기준일 · 늦음 판정 · 행 수. `rows_map` 을 주면 행 수는 그 값(없는 표는 None = 세는 중)이고, 안 주면
    그 자리에서 센다(시험 · 명령 줄 — 큰 DB 에서는 느리다)."""
    if conn is None:
        return [{"key": k, "table": t, "label": lab, "group": g, "source": src, "verdict": "missing",
                 "verdict_label": VERDICT_LABEL["missing"], "rows": 0, "last_date": None,
                 "detail": "수집 DB 가 없다"} for k, t, lab, g, src, *_ in TABLES], {}
    has_cal = _has_table(conn, "market_calendar") and \
        conn.execute("SELECT 1 FROM market_calendar LIMIT 1").fetchone() is not None
    out: list[dict] = []
    price_last = None
    tiso = today.isoformat()
    for key, table, label, group, source, mode, last_sql, count_sql in TABLES:
        row = {"key": key, "table": table, "label": label, "group": group, "source": source}
        if not _has_table(conn, table):
            row.update(verdict="missing", verdict_label=VERDICT_LABEL["missing"], rows=0, last_date=None,
                       detail="표가 아직 없다")
            out.append(row)
            continue
        last = _iso_day(conn.execute(last_sql).fetchone()[0])
        rows = rows_map.get(key) if rows_map is not None else conn.execute(count_sql).fetchone()[0]
        row.update(rows=rows, last_date=last)
        if key == "price_daily":
            price_last = last
        if not last:
            row.update(verdict="missing", detail="행이 없다")
        elif mode in ("portal", "intraday"):
            behind, approx = _trading_after(conn, has_cal, last, tiso)
            v = _verdict_portal(len(behind))
            row.update(verdict=v, behind_trading_days=len(behind), behind_dates=behind[:10], approx=approx,
                       detail=("오늘 앞 마지막 거래일까지 있다" if not behind else
                               f"그 뒤 거래일 {len(behind)}일이 아직 없다({', '.join(behind[:3])}"
                               + (" …" if len(behind) > 3 else "") + ")"
                               + (" — 포털은 다음 날 낮에 준다" if v == "ok" else "")))
        elif mode == "derived":
            if price_last and last < price_last:
                lag, _ = _trading_after(conn, has_cal, last, (date.fromisoformat(price_last) + timedelta(days=1)).isoformat())
                row.update(verdict="late", behind_trading_days=len(lag),
                           detail=f"주식 일봉({price_last})보다 {len(lag)}거래일 뒤처졌다 — 다음 갱신이 다시 만든다")
            else:
                row.update(verdict="ok", detail="주식 일봉과 같은 날까지 있다")
        elif mode == "calendar":
            left = (date.fromisoformat(last) - today).days
            upd = conn.execute("SELECT MAX(updated_at) FROM market_calendar").fetchone()[0]
            row["updated_at"] = upd
            if left < 60:
                row.update(verdict="late", detail=f"달력 끝이 {left}일 남았다 — 내년 공휴일이 발표되면 늘어난다")
            else:
                row.update(verdict="ok", detail=f"{last} 까지 있다 · 만든 시각 {(upd or '')[:16].replace('T', ' ')}")
        else:
            row.update(verdict="info", detail="")
        row["verdict_label"] = VERDICT_LABEL[row["verdict"]]
        out.append(row)

    cal: dict = {}
    if has_cal:
        nxt = conn.execute("SELECT cal_date FROM market_calendar WHERE is_trading_day = 1 AND cal_date >= ? "
                           "ORDER BY cal_date LIMIT 1", (tiso,)).fetchone()
        prev = conn.execute("SELECT cal_date FROM market_calendar WHERE is_trading_day = 1 AND cal_date < ? "
                            "ORDER BY cal_date DESC LIMIT 1", (tiso,)).fetchone()
        today_row = conn.execute("SELECT is_trading_day, reason FROM market_calendar WHERE cal_date = ?",
                                 (tiso,)).fetchone()
        cal = {
            "today_is_trading_day": bool(today_row[0]) if today_row else None,
            "today_reason": today_row[1] if today_row else "",
            "next_trading_day": nxt[0] if nxt else None,
            "previous_trading_day": prev[0] if prev else None,
        }
    return out, cal


# ── HF ────────────────────────────────────────────────────────────────────
def hf_state(cdir: Path | None) -> list[dict]:
    if cdir is None:
        return []
    out = []
    man = _read_json(cdir.parent / "hf_export" / "meta" / "manifest.json")
    if man:
        up = man.get("uploaded") or {}
        out.append({"repo": up.get("repo_id") or man.get("repo_id") or "qurious-quant/krx-daily-market",
                    "what": "일봉 · 수정주가 · TR · 배당(원자료 공유)",
                    "tag": up.get("tag"), "uploaded_at": up.get("at"), "exported_at": man.get("generated_at")})
    oman = _read_json(cdir / "ohlcv_export" / "manifest.json")
    if oman:
        # 업로드 기록은 상태 폴더(scripts/hf_ohlcv.py 가 올린 뒤 씀) — 없으면 매니페스트의 uploaded 칸
        up = _read_json(cdir / "state" / "hf_ohlcv_last.json") or oman.get("uploaded") or {}
        out.append({"repo": "qurious-quant/krx-ohlcv", "what": "OHLCV 규격 자료(ohlcv-v1)",
                    "tag": up.get("tag"), "uploaded_at": up.get("at"), "exported_at": oman.get("built_at"),
                    "as_of": oman.get("as_of"), "rows": oman.get("rows")})
    return out


# ── 모으기 ────────────────────────────────────────────────────────────────
def get_status(now: datetime | None = None, *, use_cache: bool = True) -> dict:
    """화면이 30초마다 불러도 DB 를 매번 세지 않게 30초 동안 같은 답을 준다."""
    if use_cache and now is None and _cache.get("value") and time.monotonic() - _cache["at"] < CACHE_SECONDS:
        return _cache["value"]
    now = now or _now()
    cdir = collector_dir()
    runner = runner_state(cdir / "state" if cdir else None, now)
    conn = _connect_ro()
    rows_state, rows_note = "fresh", ""
    try:
        rows_map = None
        if conn is not None:
            rows_map, rows_state = counts_view(running=runner["running"])
        tables, cal = table_states(conn, now.date(), rows_map)
        if rows_state == "old":
            rows_note = ("일일 갱신이 도는 중이라 행 수는 지난번에 센 값이다" if runner["running"] else
                         "DB 가 바뀌어 행 수를 다시 세는 중이다 — 지금 보이는 것은 지난번 값")
        elif rows_state == "pending":
            rows_note = "행 수를 세는 중이다(앱을 켠 뒤 처음 한 번 · 컨테이너에서 15 ~ 20초) — 기준일 · 판정은 그대로 맞다"
    finally:
        if conn is not None:
            conn.close()
    worst = max((_RANK.get(t["verdict"], 0) for t in tables), default=1)
    if runner["state"] in ("failed",):
        worst = 2
    elif runner["state"] in ("late", "warning", "missing"):
        worst = max(worst, 1)
    verdict = ["ok", "warning", "error"][worst]
    price = next((t for t in tables if t["key"] == "price_daily"), {})
    value = {
        "checked_at": now.isoformat(timespec="seconds"),
        "verdict": verdict,
        "verdict_label": {"ok": "정상", "warning": "확인 필요", "error": "멈춤"}[verdict],
        "as_of": price.get("last_date"),
        "summary": f"주식 시세 기준일 {price.get('last_date') or '없음'} · 일일 갱신 {runner['label']}",
        "runner": runner,
        "tables": tables,
        "calendar": cal,
        "hf": hf_state(cdir),
        "source": "collector",
        "rows_state": rows_state,
        "rows_counted_at": _counts.get("at"),
    }
    if rows_note:
        value["rows_note"] = rows_note
    if use_cache:
        _cache.update(at=time.monotonic(), value=value)
    return value
