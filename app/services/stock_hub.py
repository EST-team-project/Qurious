"""종목 허브 자료 묶음 — 종목 하나에 대해 앱이 이미 아는 것을 칸마다 모은다 (2026-10-17).

이 파일이 답하는 질문: **"이 종목에 대해 우리 앱이 이미 아는 것은 무엇이고, 각각 언제 · 어디서 온 것인가."**

근거: 조사서 「순위 화면 · 종목 목록 · 종목 비교」 <표 8> R8 · <표 9> L-R8a(허브 데이터 묶음 — 이미 있는 API 묶기 ·
새 계산 없음 · 칸마다 기준일 · 출처) · 조사서 「개별 종목 · 투자 근거」 <표 17> L4(종목 근거 서랍) · 결정 D95(서버 둘 +
Figma 세 안 · 화면은 3차). 실사용자 피드백 「종목 하나를 기준으로 근거가 모이지 않는다」(#198)에 답하는 서버 쪽 몫이다.

칸 — 모두 이미 있는 함수를 부른다(읽기만 · 새 지표 없음)
  identity     이름 · 시장 · 다중 주기 신호 기록 대상인가   company_health.name_of · etf_daily · mtf_signals.universe
  price        마지막 종가 · 기준일 · 앞 거래일 대비          data_ohlcv.read_ohlcv(일봉 · 수정주가)
  signal       다중 주기 신호 — 쉬운 말 · 신뢰도 풀이 · 근거  signal_explain(앱 DB 의 하루 기록)
  financials   재무 건전성 — 기준 보고서 · 점검 요약 · 비율    company_health.read_health(연결 → 별도 바꿈 포함)
  disclosures  최근 공시                                       data_search.search(source=dart)
  news         최근 기사(제목 · 주소 · 출처 표시)              data_search.search(kind=news)
  schedule     앞으로의 일정(배당 · 실적 · 주주총회)           market_calendar.events
  sector       준비 중 — 섹터 분류 기준 · 자료 출처를 확인하는 동안 비워 둔다(정할 것 D117 · 2026-10-17 사용자)

지키는 것
  - 판단을 섞지 않는다 — 칸마다 그 화면의 값 · 글을 옮길 뿐 칸을 합친 한 줄 결론을 만들지 않는다. 같은 종목을 화면마다
    다르게 판단하는 일이 있고(모의투자 점검 15 · #213), 그 다름을 숨기지 않는 것이 이 묶음의 뜻이다.
  - 말없이 비우지 않는다 — 칸마다 status(ok · empty · error · pending)와 까닭. 칸 하나가 실패해도 묶음은 돌려준다.
  - 일반 사용자 답에는 표 이름 · 명령 · 예외 글을 싣지 않는다 — 할 일(hint)은 관리자에게만.
  - 수집 DB 는 읽기 전용으로만 연다(부르는 함수들이 그렇게 연다 · 이 파일의 두 질의도 `mode=ro`).

질문 속 종목 찾기(`mentions`) — AI 투자 상담이 질문에 든 종목의 앱 판단 카드를 붙일 때 쓴다(모의투자 점검 L2).
  회사 이름이 질문에 **그대로** 있을 때만 그 종목으로 읽는다(비슷한 이름 고르기 없음 — `company_health.code_of` 와 같은 원칙
  · DF-124). 세 글자 이상은 글자 그대로 찾고, 두 글자 이하는 앞뒤가 낱말 경계일 때만 · 흔한 낱말(「대상」 · 「태양」 …)은 빼고
  찾는다. 겹치면 긴 이름이 이긴다(「SK하이닉스」 안의 「SK」 는 따로 읽지 않는다 · 경계 · 겹침 규칙은 `text_match` 한 곳 —
  용어 찾기와 같은 규칙). 무엇을 종목으로 읽었는지는 응답이 글자로
  돌려줘 화면이 「질문의 ○○ 을 종목으로 읽었습니다」 라고 밝힌다.
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from app.services import (collector_db, company_health, data_ohlcv, data_search, market_calendar, mtf_signals,
                          signal_explain, text_match)

KST = timezone(timedelta(hours=9))

#: 응답 꼴 판 — 칸 이름 · 꼴을 바꾸면 올린다(화면 · 저장본 열쇠가 이 숫자를 본다)
VERSION = 1

SECTIONS = ("identity", "price", "signal", "financials", "disclosures", "news", "schedule", "sector")
OK, EMPTY, ERROR, PENDING = "ok", "empty", "error", "pending"

LABELS = {
    "identity": "종목", "price": "마지막 종가", "signal": "다중 주기 신호", "financials": "재무 건전성",
    "disclosures": "최근 공시", "news": "최근 기사", "schedule": "앞으로의 일정", "sector": "섹터",
}
#: 칸마다 「자세히」 로 가는 화면(화면 키 — `public/js/core.js` GNB_MENUS)
VIEWS = {
    "price": "trading-chart", "signal": "robo-patterns", "financials": "agent-cb",
    "disclosures": "agent-news", "news": "agent-news", "schedule": "market-calendar",
}
#: 이 종목을 더 볼 수 있는 화면 — 순서는 여정(차트 → 신호 → 재무 → 소식 → 일정 → 연습)
LINKS = (
    ("trading-chart", "주가 차트"), ("robo-patterns", "차트 패턴 · 다중 주기"), ("robo-screening", "종목 스크리닝"),
    ("agent-cb", "재무 · 신용 위험"), ("invest-fundamental", "재무제표 분석"), ("agent-news", "공시 · 기사 시간표"),
    ("market-calendar", "일정"), ("paper-stock", "모의 주문(연습)"),
)

NOTICE = ("정보를 모아 보여 드릴 뿐 투자 권유가 아닙니다. 칸마다 그 화면의 값을 옮겨 기준일 · 출처가 서로 다를 수 있고, "
          "지난 값은 앞날을 보장하지 않습니다.")
NOTE = "새로 계산하지 않고 앱의 다른 화면이 쓰는 값 · 글을 그대로 모았습니다 — 칸을 합친 한 줄 결론은 만들지 않습니다."

PRICE_LOOKBACK_DAYS = 20          # 연휴(설 · 추석)를 넘어도 앞 거래일이 잡히게
PRICE_SOURCE = "수집 시세 — 일봉 종가(수정주가) · 매 거래일 12:30 에 전 거래일분을 받음"
PRICE_NOTE = ("실시간이나 지연 시세가 아니라 마지막 거래일의 장 마감 종가입니다. 등락은 그 앞 거래일 종가와 견준 값이고, "
              "분할 · 병합이 있으면 수정주가로 맞춰 견줍니다.")
SIGNAL_SOURCE = "다중 주기 신호 — 60분 · 일 · 주봉 지표 규칙 점수의 합(매 거래일 12:30 기록)"
SIGNAL_NOT_UNIVERSE = ("이 종목은 다중 주기 신호를 매일 기록하는 종목(분봉을 모으는 401종목)에 들지 않습니다 — "
                       "차트 패턴 화면에서 그때그때 계산해 볼 수 있습니다.")
SIGNAL_NONE = "아직 이 종목의 다중 주기 신호 기록이 없습니다."
SECTOR_PENDING = "섹터 분류는 준비 중입니다 — 분류 기준과 자료 출처를 확인하고 있습니다."
NEWS_LIMIT = 5
DISCLOSURE_LIMIT = 5
SCHEDULE_DAYS = 60
SCHEDULE_LIMIT = 10
GENERIC_ERROR = "이 칸의 자료를 지금 읽지 못했습니다 — 잠시 뒤 다시 열어 보세요."

_SYMBOL = re.compile(r"^[0-9A-Z]{6}$")


class HubError(Exception):
    """묶음을 만들 수 없는 요청 — 라우트가 상태 번호 · 글을 그대로 돌려준다."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

    def detail(self) -> dict:
        return {"code": self.code, "message": self.message}


def normalize(symbol: str) -> str:
    """`005930` · `005930.KS` · ` 0000d0 ` 모두 받는다 — 단축코드 6자리(영문 섞임 ETF 포함)."""
    s = re.sub(r"\.(KS|KQ)$", "", (symbol or "").strip().upper())
    if not _SYMBOL.match(s):
        raise HubError(422, "bad_symbol", f"종목 코드는 6자리입니다(예: 005930): {symbol!r}")
    return s


def wanted(sections: str | None) -> tuple[str, ...]:
    """`sections=price,signal` → 그 칸만(종목 칸은 늘 넣는다 · 모르는 칸 이름은 422)."""
    if not sections:
        return SECTIONS
    names = [x.strip() for x in sections.split(",") if x.strip()]
    bad = [x for x in names if x not in SECTIONS]
    if bad:
        raise HubError(422, "bad_sections", f"모르는 칸입니다: {', '.join(bad)} — 쓸 수 있는 칸: {' · '.join(SECTIONS)}")
    return tuple(s for s in SECTIONS if s == "identity" or s in names)


def section(name: str, status: str, *, data=None, as_of: str | None = None, source: str = "", reason: str = "",
            note: str = "", hint: str = "", notice: str = "") -> dict:
    out = {"key": name, "label": LABELS[name], "status": status, "as_of": as_of, "source": source,
           "view": VIEWS.get(name, ""), "data": data, "reason": reason}
    if note:
        out["note"] = note
    if notice:
        out["notice"] = notice
    if hint:
        out["hint"] = hint      # 관리자에게만 실린다(_failed)
    return out


def _failed(name: str, e: BaseException, admin: bool) -> dict:
    """칸을 읽다 난 오류 → 그 칸의 상태. 404 는 「자료 없음」, 그 밖은 「읽지 못함」 — 일반 사용자에게는 예외 글을 싣지 않는다."""
    status = getattr(e, "status", None) or getattr(e, "status_code", None) or 500
    message = getattr(e, "message", None) or (e.detail if isinstance(getattr(e, "detail", None), str) else "")
    hint = getattr(e, "hint", "") or ""
    if status == 404:
        return section(name, EMPTY, reason=message or "이 종목의 자료가 없습니다.")
    admin_hint = " · ".join(x for x in (message, hint) if x) or f"{type(e).__name__}: {e}"
    return section(name, ERROR, reason=GENERIC_ERROR, hint=admin_hint if admin else "")


def _guard(name: str, fn: Callable[[], dict], admin: bool) -> dict:
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — 칸 하나의 실패가 묶음 전체를 막지 않게(상태 · 까닭은 칸에 남긴다)
        return _failed(name, e, admin)


# ── 수집 DB 두 질의(읽기 전용) — 이름표 · 유니버스 ────────────────────────────────────────────

def _open_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=5)


ETF_NAME_SQL = "SELECT itms_nm FROM etf_daily WHERE srtn_cd = ? ORDER BY bas_dt DESC LIMIT 1"


def _etf_name(symbol: str) -> str:
    path = collector_db.db_path()
    if path is None:
        return ""
    conn = _open_ro(path)
    try:
        row = conn.execute(ETF_NAME_SQL, (symbol,)).fetchone()
    finally:
        conn.close()
    return (row[0] or "") if row else ""


_UNIVERSE: dict = {"at": 0.0, "codes": frozenset()}
UNIVERSE_TTL = 600.0               # 유니버스는 판이 바뀔 때만 달라진다 — 10분이면 넉넉하다


def _universe() -> frozenset | None:
    """다중 주기 신호 기록 대상(분봉 유니버스) — 못 읽으면 None(「대상인지 모름」 · 말없이 「아님」 으로 읽지 않는다)."""
    now = time.monotonic()
    if _UNIVERSE["codes"] and now - _UNIVERSE["at"] < UNIVERSE_TTL:
        return _UNIVERSE["codes"]
    try:
        codes = frozenset(mtf_signals.universe())
    except (OSError, sqlite3.Error):
        return None
    if codes:
        _UNIVERSE.update(at=now, codes=codes)
    return codes or None


# ── 칸 ──────────────────────────────────────────────────────────────────────────────────

def identity(symbol: str) -> dict:
    if collector_db.db_path() is None:
        return section("identity", ERROR, data={"name": "", "market": "", "kind": "", "signal_universe": None},
                       reason="수집한 시세 자료를 찾지 못해 종목 이름을 확인하지 못했습니다.")
    name, market = company_health.name_of(symbol)
    kind = "stock" if name else ""
    if not name:
        name = _etf_name(symbol)
        market, kind = ("ETF", "etf") if name else ("", "")
    universe = _universe()
    data = {"name": name, "market": market, "kind": kind,
            "signal_universe": None if universe is None else symbol in universe}
    if not name:
        return section("identity", EMPTY, data=data, reason="수집한 국내 주식 · ETF 시세에서 이 코드를 찾지 못했습니다.")
    return section("identity", OK, data=data, source="수집 시세의 마지막 줄(종목 이름 · 시장)")


def price(symbol: str, today: date) -> dict:
    start = (today - timedelta(days=PRICE_LOOKBACK_DAYS)).isoformat()
    r = data_ohlcv.read_ohlcv(symbol, "1d", start, None, None, data_ohlcv.DEFAULT_LIMIT, today=today)
    rows = r.get("rows") or []
    if not rows:
        return section("price", EMPTY, reason=f"최근 {PRICE_LOOKBACK_DAYS}일 안에 일봉이 없습니다(거래정지 · 새로 상장 등).")
    last = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else None
    close, pc = last.get("close"), (prev or {}).get("close")
    change = round((close / pc - 1) * 100, 2) if close and pc else None
    data = {"close": close, "trade_date": last.get("trade_date"), "prev_close": pc,
            "prev_date": (prev or {}).get("trade_date"), "change_pct": change,
            "basis": r.get("basis"), "market": r.get("market")}
    return section("price", OK, data=data, as_of=last.get("trade_date"), source=PRICE_SOURCE, note=PRICE_NOTE)


async def signal(db, symbol: str, in_universe: bool | None) -> dict:
    snap = await signal_explain.load_snapshot(db, symbol)
    if snap is None:
        return section("signal", EMPTY, reason=SIGNAL_NOT_UNIVERSE if in_universe is False else SIGNAL_NONE)
    ex = signal_explain.explain(snap)
    keep = ("timeframe", "label", "text", "points")
    data = {"signal": ex["signal"], "strength": ex["strength"], "confidence": ex["confidence"],
            "summary": ex["summary"], "confidence_text": ex["confidence_text"], "definition": ex["definition"],
            "reasons": [{k: r.get(k) for k in keep} for r in ex["reasons"][:3]],
            "counter_reasons": [{k: r.get(k) for k in keep} for r in ex["counter_reasons"][:2]]}
    return section("signal", OK, data=data, as_of=ex["as_of"], source=SIGNAL_SOURCE, notice=ex["disclaimer"])


def financials(symbol: str) -> dict:
    h = company_health.read_health(symbol)
    latest = h.get("latest") or {}
    metrics = [{k: m.get(k) for k in ("key", "label", "value", "unit", "sentence")} for m in h.get("metrics") or []]
    z = h.get("zscore") or {}
    data = {"kind": h.get("kind"), "kind_note": h.get("kind_note"), "fs": h.get("fs"), "fs_note": h.get("fs_note"),
            "latest": latest, "summary": h.get("summary"), "metrics": metrics,
            "zscore": {"value": z.get("value"), "zone_label": z.get("zone_label"), "reason": z.get("reason", "")},
            "loss_streak": (h.get("operating") or {}).get("loss_streak")}
    return section("financials", OK, data=data, as_of=latest.get("available_from") or latest.get("period_end"),
                   source=h.get("source", ""), notice=h.get("notice", ""))


def _search_items(r: dict) -> list[dict]:
    out = []
    for it in r.get("items") or []:
        extra = it.get("extra") or {}
        out.append({"title": it.get("title"), "published": it.get("published"), "url": it.get("url"),
                    "source": it.get("source"), "source_label": data_search.SOURCE_LABELS.get(it.get("source"), ""),
                    "attribution": extra.get("attribution", ""), "topics": (it.get("tags") or {}).get("topic", [])})
    return out


def disclosures(symbol: str) -> dict:
    r = data_search.search("", None, symbol, None, None, None, None, None, "date", DISCLOSURE_LIMIT, 0, "dart", False)
    items = _search_items(r)
    data = {"items": items, "total": r.get("total", 0), "index_built_at": r.get("index_built_at")}
    if not items:
        return section("disclosures", EMPTY, data=data, reason="이 종목의 공시를 찾지 못했습니다.")
    return section("disclosures", OK, data=data, as_of=(items[0]["published"] or "")[:10] or None,
                   source="전자공시(DART) 공시 목록 — 수집기 검색 색인")


def news(symbol: str) -> dict:
    r = data_search.search("", "news", symbol, None, None, None, None, None, "date", NEWS_LIMIT, 0, None, False)
    items = _search_items(r)
    data = {"items": items, "total": r.get("total", 0), "index_built_at": r.get("index_built_at")}
    if not items:
        return section("news", EMPTY, data=data, reason="이 종목 이름이 붙은 기사를 찾지 못했습니다.")
    return section("news", OK, data=data, as_of=(items[0]["published"] or "")[:10] or None,
                   source="정책브리핑 정책뉴스 · 언론사 기사 제목(GDELT) — 본문은 원문 링크로",
                   note="종목 이름표는 규칙으로 붙였습니다 — 이름이 같은 다른 뜻의 기사가 섞일 수 있습니다.")


def schedule(symbol: str, today: date) -> dict:
    r = market_calendar.events(today, today + timedelta(days=SCHEDULE_DAYS), "all", symbol, SCHEDULE_LIMIT, 0, None, None)
    keep = ("date", "weekday", "time", "kind", "kind_label", "title", "confidence", "confidence_label")
    events = [{k: e.get(k) for k in keep} for e in r.get("events") or []]
    data = {"events": events, "days": SCHEDULE_DAYS}
    if not events:
        return section("schedule", EMPTY, data=data, reason=f"앞으로 {SCHEDULE_DAYS}일 안에 알려진 일정이 없습니다.")
    return section("schedule", OK, data=data, as_of=today.isoformat(),
                   source="금융 일정 — 공시 · 거래소 규칙에서 모은 배당 · 실적 · 주주총회 일정")


def sector() -> dict:
    return section("sector", PENDING, reason=SECTOR_PENDING)


# ── 묶음 ────────────────────────────────────────────────────────────────────────────────

async def bundle(db, symbol: str, *, sections: str | None = None, admin: bool = False,
                 today: date | None = None) -> dict:
    sym = normalize(symbol)
    want = wanted(sections)
    today = today or datetime.now(KST).date()
    ident = await asyncio.to_thread(_guard, "identity", lambda: identity(sym), admin)
    if ident["status"] == EMPTY:
        raise HubError(404, "no_symbol", f"{sym} — {ident['reason']}")
    in_universe = (ident.get("data") or {}).get("signal_universe")

    sync = {"price": lambda: price(sym, today), "financials": lambda: financials(sym),
            "disclosures": lambda: disclosures(sym), "news": lambda: news(sym),
            "schedule": lambda: schedule(sym, today), "sector": sector}
    names = [s for s in want if s != "identity"]

    async def one(name: str) -> dict:
        if name == "signal":
            try:
                return await signal(db, sym, in_universe)
            except Exception as e:  # noqa: BLE001 — 앱 DB 가 꺼져 있어도 다른 칸은 돌려준다
                return _failed("signal", e, admin)
        return await asyncio.to_thread(_guard, name, sync[name], admin)

    parts = await asyncio.gather(*(one(n) for n in names))
    secs = {"identity": ident, **dict(zip(names, parts))}
    data = ident.get("data") or {}
    return {
        "version": VERSION, "symbol": sym, "name": data.get("name", ""), "market": data.get("market", ""),
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "order": list(want), "sections": secs,
        "links": [{"view": v, "label": label} for v, label in LINKS],
        "notice": NOTICE, "note": NOTE,
    }


# ── 질문 속 종목 찾기 ──────────────────────────────────────────────────────────────────────

MAX_TEXT = 300                    # AI 투자 상담 입력 상한(kbchat.js MAX_Q · kb AskBody.q)과 같다
MENTION_LIMIT = 2
#: 두 글자 이하 이름 가운데 흔한 낱말 — 질문에 나와도 종목으로 읽지 않는다(2026-10-17 · 이름 202개를 읽고 고름)
COMMON_WORDS = frozenset({
    "대상", "동양", "태양", "나노", "레몬", "노을", "씨앗", "진도", "남성", "동방", "서원", "상보", "아하", "핑거", "레이",
    "캐리", "성우", "전방", "삼일", "동서", "광무", "무학", "백산", "우진", "유신", "서남", "대모", "하스", "알트", "꿈비",
    "화신", "신원", "우성", "선진", "진영", "대원", "대교", "서한", "덕성", "신흥", "세중", "서연", "삼진", "삼영", "대창",
    "대현", "배럴", "러셀", "포톤", "본느", "누보", "센코", "노타", "닷밀", "워트", "원림", "보락", "부방", "청보", "조흥",
    "TP", "CS", "EG", "KD", "YW", "SG", "LF", "KX", "3S", "E8", "E1",
})
_NAMES: dict = {"at": 0.0, "names": {}}
NAMES_TTL = 1800.0

NAMES_SQL = ("SELECT srtn_cd, itms_nm, mrkt_ctg FROM price_daily "
             "WHERE bas_dt = (SELECT MAX(bas_dt) FROM price_daily)")
ETF_NAMES_SQL = "SELECT srtn_cd, itms_nm FROM etf_daily WHERE bas_dt = (SELECT MAX(bas_dt) FROM etf_daily)"


def _load_names() -> dict:
    """이름 → (코드, 시장) — 수집 시세의 마지막 날(주식 · ETF). 못 읽으면 빈 사전."""
    path = collector_db.db_path()
    if path is None:
        return {}
    names: dict = {}
    conn = _open_ro(path)
    try:
        for code, name, market in conn.execute(NAMES_SQL):
            if name:
                names[name.strip()] = (code, market or "")
        try:
            for code, name in conn.execute(ETF_NAMES_SQL):
                if name:
                    names.setdefault(name.strip(), (code, "ETF"))
        except sqlite3.OperationalError:
            pass                      # ETF 표가 없는 DB(시험 · 옛 판) — 주식 이름만
    finally:
        conn.close()
    return names


def names() -> dict:
    now = time.monotonic()
    if _NAMES["names"] and now - _NAMES["at"] < NAMES_TTL:
        return _NAMES["names"]
    try:
        loaded = _load_names()
    except sqlite3.Error:
        loaded = {}
    if loaded:
        _NAMES.update(at=now, names=loaded)
    return loaded


def mentions(text: str, *, limit: int = MENTION_LIMIT, table: dict | None = None) -> list[dict]:
    """질문에 이름이 그대로 든 종목 — 질문에 나온 차례 · 최대 `limit` 개. 경계 · 겹침 규칙은 `text_match` 한 곳."""
    text = (text or "")[:MAX_TEXT]
    table = names() if table is None else table
    spans = []
    for name, (code, market) in table.items():
        if len(name) < 2 or name in COMMON_WORDS:
            continue
        at = text.find(name)
        while at != -1:
            if text_match.edges_ok(text, at, at + len(name), name):
                spans.append((at, at + len(name), name, code, market))
                break
            at = text.find(name, at + 1)
    out, seen = [], set()
    for at, _end, name, code, market in text_match.longest_first(spans):
        if code in seen:
            continue
        seen.add(code)
        out.append({"symbol": code, "name": name, "market": market, "matched": name, "at": at})
        if len(out) >= limit:
            break
    return out
