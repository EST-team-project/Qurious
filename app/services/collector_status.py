"""종목 · 날짜별 수집 상태 — 사실만 주는 함수 (#124 계약 · 리밸런싱 예약 체결 판정이 읽는다 · 2026-10-15)

왜 필요한가
-----------
리밸런싱은 예약한 날의 시가로 체결한다. 그날 가격 행이 없을 때 **「수집이 아직 안 끝나 기다린다」** 와
**「수집은 끝났는데 그날 체결할 수 없어 미체결로 끝낸다」** 를 갈라야 하는데, 지금은 리밸런싱 코드가 수집 기록
(`ingest_day`)을 직접 읽어 가른다(`app/services/rebalance_prices.py` 의 `collection_complete`). 수집 기록의 뜻(출처 · 상태 값)은
데이터 파트가 정하므로, 그 사실을 **한 곳에서** 읽어 주는 함수를 둔다 — 판정(기다림 · 미체결 종료)은 지금처럼 리밸런싱 쪽이 내린다
(같은 판정이 두 곳에 생기지 않게).

무엇을 돌려주나 — `symbol_day_status(symbols, day) -> {넣은 기호: 상태}`
    {"symbol": "005930", "day": "2026-10-13",
     "kind": "stock" | "etf" | "mixed" | "unknown",
     "collected": {"portal": "done" | "empty" | "holiday" | "error" | None, ...},
     "row": True | False,
     "halted": True | False | None, "volume_zero": True | False | None,
     "notes": ["모름 · 빈칸의 까닭", ...]}

- `kind` — 수집 DB 에서 그 종목을 **본 적 있는 표**로 가른다: 주식 일봉(`price_daily`) → stock · ETF 일봉(`etf_daily`) → etf ·
  둘 다 → mixed · 어디에도 없음 → unknown. 날짜와 상관없이 본 적이 있나만 본다(`collection_complete` 와 같은 규칙).
- `collected` — 그날 출처별 수집 기록의 상태 **그대로**(수집기 `collector/sources/portal.py` 가 쓰는 값):
  done = 받았고 행이 있음 · empty = 응답이 0행(공개 전이거나 휴장) · holiday = 휴장으로 고쳐 적음 · error = 통신 · 응답 실패 ·
  None = 기록 없음(그날은 아직 받지 않음). kind 가 stock 이면 `portal` 만 · etf 면 `portal_etf` 만 ·
  mixed · unknown 이면 **두 출처 모두** 싣는다 — 「모르면 둘 다 완료여야 함」 규칙을 그대로 옮길 수 있게.
- `row` — 그날 가격 행이 있나(주식 표 → ETF 표 차례 · `read_prices` 와 같은 차례).
- `halted` · `volume_zero` — 행이 있을 때만 참 · 거짓, 없으면 None. 행은 있는데 거래량 칸이 비었으면 `volume_zero` 는 None
  (모름 · notes 에 까닭) — `read_prices` 는 이때 「미체결 종료」 가 아니라 「기다림」 으로 다룬다(0 과 다르게).
- 가격(원시 시가 · 종가)은 이 함수가 주지 않는다 — 지금처럼 `read_prices` 가 읽는다.

수집 DB 는 읽기 전용(`mode=ro`) 한 트랜잭션으로만 연다. DB 가 없거나 읽지 못하면 `CollectorStatusUnavailable` —
종목마다 「모름」 을 꾸며 내지 않는다(말없는 대체 금지). 기호 꼴이 틀리면 ValueError(부르는 쪽 실수).
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from app.services import collector_db

#: 국내 주식 · ETF 단축코드(ETF 는 영문이 섞인다 — 예 0000D0) · 접미사는 꼴 맞춤일 뿐 — `read_prices` 와 같은 규칙
SYMBOL_RE = re.compile(r"([0-9A-Z]{6})(?:\.(?:KS|KQ|KN))?")
#: (가격 표, 그 표를 채우는 수집 출처) — 차례가 곧 `row` 를 찾는 차례
SOURCES = (("price_daily", "portal"), ("etf_daily", "portal_etf"))
KIND_BY_SOURCES = {("portal",): "stock", ("portal_etf",): "etf", ("portal", "portal_etf"): "mixed", (): "unknown"}
#: 수집 기록 상태 값(수집기가 쓰는 값) — 이 밖의 값이 오면 그대로 싣고 notes 에 적는다
KNOWN_STATUS = ("done", "empty", "holiday", "error")


class CollectorStatusUnavailable(RuntimeError):
    """수집 DB 가 없거나 읽지 못함 — 종목별 사실을 줄 수 없다(부르는 쪽은 「기다림」 으로 다룬다)."""


def _day(day) -> date:
    if isinstance(day, datetime):
        return day.date()
    if isinstance(day, date):
        return day
    s = str(day).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"날짜 꼴이 틀렸습니다: {day!r} (YYYY-MM-DD · YYYYMMDD · date)")


def _code(symbol: str) -> str:
    m = SYMBOL_RE.fullmatch((symbol or "").strip().upper())
    if not m:
        raise ValueError(f"{symbol!r}: 국내 주식 · ETF 단축코드(6자리)만 받습니다")
    return m.group(1)


def _status_one(conn: sqlite3.Connection, code: str, bas_dt: str) -> Dict:
    seen = tuple(src for table, src in SOURCES
                 if conn.execute(f"SELECT 1 FROM {table} WHERE srtn_cd=? LIMIT 1", (code,)).fetchone())
    kind = KIND_BY_SOURCES[seen]
    sources = seen if kind in ("stock", "etf") else tuple(src for _, src in SOURCES)
    notes: List[str] = []
    if kind == "unknown":
        notes.append("주식 · ETF 일봉 어디에도 없는 종목 — 두 출처의 수집 기록을 모두 싣는다")
    elif kind == "mixed":
        notes.append("주식 · ETF 일봉 두 표 모두에 있는 종목 — 두 출처의 수집 기록을 모두 싣는다")

    collected: Dict[str, Optional[str]] = {}
    for src in sources:
        r = conn.execute("SELECT status FROM ingest_day WHERE source=? AND bas_dt=?", (src, bas_dt)).fetchone()
        st = None if r is None else r[0]
        collected[src] = st
        if st is None:
            notes.append(f"{src}: 그날 수집 기록 없음 — 아직 받지 않은 날")
        elif st not in KNOWN_STATUS:
            notes.append(f"{src}: 수집기가 모르는 상태 값 {st!r} — 그대로 싣는다")

    row = None
    for table, _ in SOURCES:
        row = conn.execute(f"SELECT halted, trqu FROM {table} WHERE srtn_cd=? AND bas_dt=?", (code, bas_dt)).fetchone()
        if row is not None:
            break
    if row is None:
        halted = volume_zero = None
    else:
        halted = bool(row[0])
        if row[1] is None:
            volume_zero = None    # 0 으로 꾸미지 않는다 — `read_prices` 는 이 경우를 「미체결 종료」 가 아니라 「기다림」 으로 다룬다
            notes.append("거래량 칸이 비어 있음 — 0 인지 모름")
        else:
            volume_zero = row[1] <= 0
    return {"kind": kind, "collected": collected, "row": row is not None,
            "halted": halted, "volume_zero": volume_zero, "notes": notes}


def symbol_day_status(symbols: Iterable[str], day, *, path: Optional[Path] = None) -> Dict[str, Dict]:
    """종목들의 그날 수집 사실 — 넣은 기호를 열쇠로. 판정은 하지 않는다(머리말).

    한 번의 읽기 전용 트랜잭션에서 모든 종목을 본다(종목마다 다른 순간의 DB 를 보지 않게 — `read_prices` 와 같음).
    """
    d = _day(day)
    syms = list(dict.fromkeys(symbols))                    # 넣은 차례 그대로 · 같은 기호는 한 번
    codes = {s: _code(s) for s in syms}                    # 꼴이 틀린 기호가 있으면 DB 를 열기 전에 멈춘다
    path = path or collector_db.db_path()
    if path is None:
        raise CollectorStatusUnavailable("수집 DB 가 없어 종목별 수집 상태를 알 수 없습니다")
    bas_dt = d.strftime("%Y%m%d")
    out: Dict[str, Dict] = {}
    try:
        with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=5)) as conn:
            conn.execute("BEGIN")
            for s in syms:
                out[s] = {"symbol": codes[s], "day": d.isoformat(), **_status_one(conn, codes[s], bas_dt)}
    except (sqlite3.Error, OSError) as exc:
        raise CollectorStatusUnavailable("수집 DB 를 읽지 못해 종목별 수집 상태를 알 수 없습니다") from exc
    return out
