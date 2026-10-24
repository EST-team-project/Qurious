"""모의투자 그림자 일지 — 등록한 규칙 판으로 거래일마다 판단 1행 · 다음 거래일 시가 가상 체결 · 추가만 (할 일 ①-26).

설계: `docs/phase-3/02-design/system/모의투자-그림자일지-설계.md` — 이 파일은 그 2 · 3 · 4 · 6 · 7절이다.

한 행 = 한 판의 거래일 하루
--------------------------
행 D 는 D 의 봉이 수집 DB 에 들어온 뒤(포털이 다음 영업일 낮에 준다 → D+1 12:30 러너 뒤) 한 번 만들고 다시 고치지 않는다.

  ① 앞 행이 낸 주문을 **D 시가**(원주가) ± 슬리피지로 가상 체결 → ② D 종가로 평가 → ③ D 종가까지의 봉으로 판단 →
  ④ 다음 거래일 시가에 낼 주문 → ⑤ 표시(일손실 한도 · 조정 사건 · 참고 지문)

판단은 **앱의 함수를 그대로** 부른다(`stock.get_quant_indicators` · `auto_trade.apply_strategy_spec_to_signal`). 다만 앱의
일봉 함수(`stock.get_candles`)는 수집 DB 에 없으면 다른 출처(증권사 시세 · 해외 차트)로 넘어가고 늘 「오늘까지」 를 읽으므로, 일지는 그
함수를 잠깐 「수집 DB · D 까지」 로 바꿔 끼운다(`_candles_as_of`) — 판단에 D 뒤의 봉이 섞이지 않고, 남의 출처로 새지 않는다.

판 지문 (4절)
-------------
규칙을 이루는 함수 · 자료마다 SHA-256 을 내 묶은 값이다. 함수는 주석 · 문서 문자열 · 공백을 뺀 구문 나무(`ast.unparse`)로 잰다.
회차마다 다시 재서 등록 판과 다르면 **그 회차에 새 판을 등록한다**(시도 수 +1 · 10-24 결정 4) — 바뀐 코드가 옛 판 이름으로
기록되면 E2 판정 ②(판 안의 규칙 변경 0회)가 조용히 깨진다. 새 판은 새 계좌로 시작하고, 옛 판의 남은 날은 계산하지 않는다(옛 코드가 없다).

하지 않는 것 — 증권사 주문 · 고치기 · 지우기 · 놓친 날을 지금 가격으로 따라잡기 · 미국 · 코인.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import inspect
import json
import math
import platform
import sqlite3
import subprocess
import textwrap
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[2]

RULE_CARD = "card_ma_cross_20_60"
RULE_DEFAULT = "auto_default"
#: 등록하는 규칙 — 차례가 곧 처음 등록할 때의 시도 번호 차례다(카드 1 · 기본 2).
RULES = (RULE_CARD, RULE_DEFAULT)
#: 신장환 님 카드 판 1 — 연결 시험용 고정 입력이자 일지의 등록 규칙(승인 · 합격과 별개 · #314 04 와 같은 뜻).
CARD_PATH = ROOT / "docs" / "phase-3" / "02-design" / "system" / "예시" / "strategy-card-ma-cross-v1.json"
#: 사후 봉인 시험 첫날 — 1차 보고서 9.2절 「2026-09-01 이후 쌓이는 자료로 새 봉인 구간」 (결정 대장 2026-10-23).
POST_HOC_START = date(2026, 9, 1)
#: 정규장 마감 — 이 시각 전에 등록하면 그날 종가부터 봉인 판단이다.
MARKET_CLOSE = time(15, 30)
#: 지표 창 — 자동매매 회차와 같다(`_run_quant_cycle` 의 `get_quant_indicators(symbol, "2y")`).
PERIOD = "2y"
#: 판이 바뀌어 새 판을 등록한 회차의 종료코드 — 러너가 「경고」 로 센다(실패가 아니다).
EXIT_VERSION_CHANGED = 10

BUY_ACTIONS = ("강력 매수", "매수")
SELL_ACTIONS = ("강력 매도", "매도")

#: 판정 틀 — 10-23 결정(D7 ⑦ E2). 괴리 범위의 숫자(③)는 강민석 님이 결과를 보기 전에 메모(`judgment`)로 더한다 —
#: 여기 숫자를 넣으면 판 지문이 바뀌어 봉인이 처음부터 다시 간다.
JUDGMENT = {
    "framework": "D7 ⑦ E2 — 결정 대장 2026-10-23",
    "criteria": [
        "① 기록 누락 0일 — 늦게 계산한 행은 recomputed 로 표시",
        "② 판 안의 규칙 변경 0회 — 판 지문이 바뀌면 새 판(기계)",
        "③ 같은 기간 · 같은 규칙 · 같은 시작 자금 백테스트와의 괴리 — 범위는 강민석 님이 결과를 보기 전에 메모로",
    ],
    "reference": "QuantConnect 맞대기 — 수익 상관 0.8 이상 · DTW 0.2 미만(참고)",
    "performance": "기술 통계(누적 수익 · MDD · 샤프) + MinTRL — 판정에 쓰지 않는다",
    "owner": "사전등록 판정 · 성과 해석 = 강민석(④) · 실행기 · 자료 · 저장 = 이동원",
    "baselines": ["같은 종목 매수 후 보유", "같은 유니버스 동일가중", "KOSPI 자체 재현 지수"],
}


# ── 0. 작은 도구 ──────────────────────────────────────────────────────────

def canonical(value: Any) -> str:
    """정렬한 JSON — 내용 지문 · 자료 지문이 모두 이것으로 잰다."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    return tree


def code_digest(fn: Any) -> str:
    """함수의 구문 나무 지문 — 주석 · 문서 문자열 · 공백 · 줄바꿈을 바꾸면 그대로, 식을 바꾸면 달라진다."""
    src = textwrap.dedent(inspect.getsource(inspect.unwrap(fn)))
    return sha256(ast.unparse(_strip_docstrings(ast.parse(src))))


def data_digest(value: Any) -> str:
    return sha256(canonical(value))


def git_head() -> str:
    """지금 git HEAD 앞 12자(읽기만) — 일지 · 카드 · 앱 코드가 커밋 밖에서 바뀌어 있으면 `+dirty`. 모르면 빈 글."""
    try:
        head = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "app", "scripts/paper_journal.py",
                                "docs/phase-3/02-design/system/예시"], cwd=ROOT, capture_output=True,
                               text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return (head + ("+dirty" if dirty else ""))[:40]


def _round_money(x: float) -> float:
    return round(float(x), 2)


# ── 1. 규칙 명세 · 판 지문 ────────────────────────────────────────────────

def sizing_defaults() -> dict:
    """자동매매 기본값 — 모델 · 위험 한도의 기본값에서 읽는다(사본을 두지 않는다 · 기본값이 바뀌면 판 지문이 바뀐다)."""
    from app.models.trading import BrokerSettings
    from app.services import auto_trade
    from app.services.risk_guard import RiskLimits

    cols = BrokerSettings.__table__.c
    lim = RiskLimits()
    return {
        "initial_cash": float(auto_trade._INITIAL_CAPITAL),
        "per_trade_budget": float(cols.quant_per_trade_budget.default.arg),
        "buy_ratio": float(cols.quant_buy_ratio.default.arg),
        "sell_ratio": float(cols.quant_sell_ratio.default.arg),
        "top_n": int(cols.quant_ai_top_n.default.arg),
        "max_position_pct": float(lim.max_position_pct),
        "max_orders_per_day": int(lim.max_orders_per_day),
        "daily_loss_limit_pct": float(lim.daily_loss_limit_pct),
        "loss_limit_action": "flag_only",
        "source": "BrokerSettings · RiskLimits 기본값 · auto_trade._INITIAL_CAPITAL",
    }


def _card() -> tuple[dict, str]:
    raw = CARD_PATH.read_bytes()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def rule_spec(rule_id: str) -> dict:
    """판에 얼려 둘 명세 — 판단 · 크기 · 체결 · 비용 · 판정. 이 JSON 도 판 지문의 한 조각이다."""
    from app.services import stock, trading_cost

    names = {s["symbol"]: s["name"] for s in stock.QUANT_STOCKS}
    sizing = sizing_defaults()
    top_n = sizing.pop("top_n")
    spec: dict = {
        "rule_id": rule_id,
        "market": "KRX 국내 주식 · 일봉",
        "indicators": {"function": "app.services.stock.get_quant_indicators", "period": PERIOD,
                       "source": "수집 DB 수정주가(price_adjusted) — 판단일 종가까지"},
        "sizing": sizing,
        "fill": {"price": "다음 거래일 시가 · 원주가(price_daily.mkp)",
                 "slippage_bps": float(trading_cost.DEFAULT_SLIPPAGE_BPS),
                 "halted": "미체결 — 다음 날로 넘기지 않는다", "cash_short": "비용까지 살 수 있는 수량으로 줄인다"},
        "cost": {"function": "app.services.trading_cost.order_costs", "fee_rate": trading_cost.FEE_ONLINE_KRX,
                 "clearing_rate": trading_cost.FEE_CLEARING, "tax": "연도별 법령 세율표(trading_cost.TAX_SCHEDULE)"},
        "valuation": "그날 원주가 종가 · 배당 입금 없음 · 보유 중 조정 사건은 표시만",
        "judgment": JUDGMENT,
        "post_hoc_start": POST_HOC_START.isoformat(),
    }
    if rule_id == RULE_CARD:
        card, card_sha = _card()
        universe = [f"{c}.KS" for c in card["universe"]]
        spec.update({
            "title": "신장환 님 카드 판 1 — 이동평균 교차 20 · 60 일봉",
            "universe": universe, "names": {s: names.get(s, s[:6]) for s in universe},
            "selection": {"source": "card", "max_symbols": int(card["position_sizing"]["max_symbols"]),
                          "note": "카드에 적힌 종목만(10-24 결정 7)"},
            "decision": {"function": "app.services.auto_trade.apply_strategy_spec_to_signal",
                         "card_file": CARD_PATH.relative_to(ROOT).as_posix(), "card_sha256": card_sha},
            "card": card,
        })
        spec["sizing"]["max_position_pct"] = float(card["position_sizing"]["max_position_pct"])
    elif rule_id == RULE_DEFAULT:
        universe = [s["symbol"] for s in stock.QUANT_STOCKS]
        spec.update({
            "title": "지금 자동매매 기본 규칙(전략 카드 없이)",
            "universe": universe, "names": names,
            "selection": {"source": "ai_top_n", "top_n": top_n, "note": "그날 점수 상위 N(자동매매 symbol_source=ai)"},
            "decision": {"function": "app.services.stock._generate_signal — get_quant_indicators 의 signal"},
        })
    else:
        raise ValueError(f"모르는 규칙: {rule_id!r} — {RULES} 중 하나")
    return spec


def _code_parts(rule_id: str) -> dict[str, Any]:
    from app.services import auto_trade, collector_db, risk_guard, stock, ta_utils, trading_cost

    parts: dict[str, Any] = {
        "stock.get_quant_indicators": stock.get_quant_indicators,
        "stock._generate_signal": stock._generate_signal,
        "stock._calc_rsi": stock._calc_rsi,
        "stock._calc_sma": stock._calc_sma,
        "stock._calc_bollinger": stock._calc_bollinger,
        "stock._rounded": stock._rounded,
        "ta_utils.rma": ta_utils.rma,
        "ta_utils.rsi": ta_utils.rsi,
        "ta_utils.bollinger": ta_utils.bollinger,
        "collector_db.read_daily_candles": collector_db.read_daily_candles,
        "collector_db._candle": collector_db._candle,
        "risk_guard.cap_buy_quantity": risk_guard.cap_buy_quantity,
        "trading_cost.order_costs": trading_cost.order_costs,
        "trading_cost.cost_rate": trading_cost.cost_rate,
        "trading_cost.tax_rates": trading_cost.tax_rates,
        "trading_cost._market": trading_cost._market,
        "trading_cost.market_of": trading_cost.market_of,
        "trading_cost.is_etf_name": trading_cost.is_etf_name,
        "paper_journal.ready_days": ready_days,
        "paper_journal.raw_prices": raw_prices,
        "paper_journal._candles_as_of": _candles_as_of,
        "paper_journal._indicators": _indicators,
        "paper_journal.Book": Book,
        "paper_journal.decide": decide,
        "paper_journal.plan_orders": plan_orders,
        "paper_journal.fill_orders": fill_orders,
        "paper_journal.mark_book": mark_book,
        "paper_journal.compute_day": compute_day,
    }
    if rule_id == RULE_CARD:
        parts.update({
            "auto_trade.apply_strategy_spec_to_signal": auto_trade.apply_strategy_spec_to_signal,
            "auto_trade.evaluate_spec_rules": auto_trade.evaluate_spec_rules,
            "auto_trade._sma_last": auto_trade._sma_last,
            "paper_journal._card_decision": _card_decision,
        })
    else:
        parts.update({"paper_journal._rank": _rank, "paper_journal._default_decision": _default_decision})
    return parts


def _data_parts(rule_id: str, spec: dict) -> dict[str, Any]:
    from app.services import auto_trade, collector_db, trading_cost

    parts: dict[str, Any] = {
        "collector_db._QUERY": collector_db._QUERY,
        "trading_cost.TAX_SCHEDULE": trading_cost.TAX_SCHEDULE,
        "trading_cost.fees": [trading_cost.FEE_ONLINE_KRX, trading_cost.FEE_CLEARING, trading_cost.RURAL_TAX],
        "spec": spec,
    }
    if rule_id == RULE_CARD:
        parts["auto_trade._SIGNAL_SCORE_SCALE"] = auto_trade._SIGNAL_SCORE_SCALE
    return parts


def fingerprint_parts(rule_id: str, spec: dict | None = None) -> dict[str, str]:
    """조각 이름 → SHA-256(64자). 함수는 구문 나무로, 자료는 정렬한 JSON 으로."""
    spec = spec if spec is not None else rule_spec(rule_id)
    out = {name: code_digest(fn) for name, fn in _code_parts(rule_id).items()}
    out.update({name: data_digest(v) for name, v in _data_parts(rule_id, spec).items()})
    return dict(sorted(out.items()))


def fingerprint_of(parts: dict[str, str]) -> str:
    return data_digest(parts)


def watch_parts() -> dict[str, str]:
    """참고 지문 — 실제 자동매매 회차의 묶음 코드. 바뀌어도 판은 그대로 두고 행에 표시만 한다(일지가 옮겨 적은 몇 줄이 낡았을 수 있다)."""
    from app.services import auto_trade, stock

    fns = {
        "auto_trade._run_quant_cycle": auto_trade._run_quant_cycle,
        "auto_trade._execute_virtual_trade": auto_trade._execute_virtual_trade,
        "auto_trade.apply_strategy_spec_to_symbols": auto_trade.apply_strategy_spec_to_symbols,
        "stock.get_candles": stock.get_candles,
    }
    return {k: code_digest(v)[:12] for k, v in sorted(fns.items())}


def short_parts(parts: dict[str, str]) -> dict[str, str]:
    return {k: v[:12] for k, v in parts.items()}


def changed_parts(old: dict[str, str], new: dict[str, str]) -> list[str]:
    """앞 12자로 견준 다른 조각 이름 — 더해지거나 빠진 조각도 다른 것으로 센다."""
    names = sorted(set(old) | set(new))
    return [n for n in names if (old.get(n) or "")[:12] != (new.get(n) or "")[:12]]


# ── 2. 수집 DB 읽기(읽기 전용) · 거래일 ────────────────────────────────────

def _collector_path(path: Path | None = None) -> Path:
    from app.services import collector_db

    p = path or collector_db.db_path()
    if p is None:
        raise FileNotFoundError("수집 DB 를 찾지 못했다(COLLECTOR_DB_PATH 또는 data/collector/market.sqlite3)")
    return p


@contextlib.contextmanager
def _ro(path: Path | None = None):
    conn = sqlite3.connect(f"{_collector_path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=30)
    try:
        yield conn
    finally:
        conn.close()


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _from_ymd(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def ready_days(symbols: Iterable[str], start: date, end: date, *, path: Path | None = None) -> list[date]:
    """[start, end] 안에서 대상 종목의 원주가 · 수정주가가 **둘 다** 있는 날 — 수정주가 단계가 늦은 날은 아직 준비 안 됨."""
    codes = sorted({s[:6] for s in symbols})
    if not codes or start > end:
        return []
    q = (f"SELECT DISTINCT a.bas_dt FROM price_adjusted a JOIN price_daily d "
         f"ON d.bas_dt = a.bas_dt AND d.srtn_cd = a.srtn_cd "
         f"WHERE a.srtn_cd IN ({','.join('?' * len(codes))}) AND a.bas_dt >= ? AND a.bas_dt <= ? AND d.clpr > 0 "
         f"ORDER BY a.bas_dt")
    with _ro(path) as conn:
        rows = conn.execute(q, (*codes, _ymd(start), _ymd(end))).fetchall()
    return [_from_ymd(r[0]) for r in rows]


def raw_prices(symbols: Iterable[str], d: date, *, path: Path | None = None) -> dict[str, dict]:
    """그날 원주가 시가 · 종가 · 거래정지 · 누적 조정계수 — 종목 기호(`005930.KS`) → 값."""
    syms = sorted(set(symbols))
    by_code = {s[:6]: s for s in syms}
    if not syms:
        return {}
    q = (f"SELECT d.srtn_cd, d.mkp, d.clpr, d.halted, d.itms_nm, a.cum_factor FROM price_daily d "
         f"LEFT JOIN price_adjusted a ON a.bas_dt = d.bas_dt AND a.srtn_cd = d.srtn_cd "
         f"WHERE d.bas_dt = ? AND d.srtn_cd IN ({','.join('?' * len(by_code))})")
    with _ro(path) as conn:
        rows = conn.execute(q, (_ymd(d), *sorted(by_code))).fetchall()
    out = {}
    for code, mkp, clpr, halted, name, factor in rows:
        out[by_code[code]] = {"open": float(mkp or 0), "close": float(clpr or 0), "halted": bool(halted),
                              "name": name or "", "factor": float(factor) if factor is not None else None}
    return out


def _calendar(d_from: date, d_to: date, *, path: Path | None = None) -> dict[date, bool]:
    try:
        with _ro(path) as conn:
            rows = conn.execute("SELECT cal_date, is_trading_day FROM market_calendar WHERE cal_date >= ? AND cal_date <= ?",
                                (d_from.isoformat(), d_to.isoformat())).fetchall()
    except (sqlite3.Error, FileNotFoundError):
        return {}
    return {date.fromisoformat(c): bool(t) for c, t in rows}


def is_trading_day(d: date, cal: dict[date, bool]) -> bool:
    """거래일 달력 — 달력에 없으면(앞날 범위 밖 · 시험 DB) 평일로 본다."""
    return cal.get(d, d.weekday() < 5)


def next_trading_day(d: date, *, path: Path | None = None) -> date:
    cal = _calendar(d + timedelta(days=1), d + timedelta(days=21), path=path)
    x = d + timedelta(days=1)
    while not is_trading_day(x, cal):
        x += timedelta(days=1)
    return x


def prev_trading_day(d: date, *, path: Path | None = None) -> date:
    cal = _calendar(d - timedelta(days=21), d - timedelta(days=1), path=path)
    x = d - timedelta(days=1)
    while not is_trading_day(x, cal):
        x -= timedelta(days=1)
    return x


def seal_start_for(registered_at: datetime, *, path: Path | None = None) -> date:
    """봉인 시작일 — 등록 시각 뒤 처음 마감(15:30)하는 거래일. 거래일 15:30 전 등록이면 그날 · 아니면 다음 거래일."""
    t = registered_at.astimezone(KST)
    d = t.date()
    if is_trading_day(d, _calendar(d, d, path=path)) and t.time() < MARKET_CLOSE:
        return d
    return next_trading_day(d, path=path)


# ── 3. 판단 — 앱 함수를 그대로 · 기준일 고정 ───────────────────────────────

@contextlib.contextmanager
def _candles_as_of(d: date):
    """`stock.get_candles` 를 「수집 DB · d 까지」 로 잠깐 바꾼다.

    앱의 일봉 함수는 늘 오늘까지를 읽고, 수집 DB 에 없으면 증권사 시세 · 해외 차트로 넘어간다. 일지가 그대로 부르면 지난날 행에 그 뒤의
    봉이 섞이고(미래 참조) 남의 출처 값이 들어온다. 지표 · 판단 식(`get_quant_indicators` 안)은 손대지 않고 봉을 주는 곳만
    바꾼다 — 일지는 한 프로세스에서 차례로 돌아 다른 요청과 섞이지 않는다. 수집 DB 에 없으면 빈 봉(→ 「데이터 부족」).
    """
    from app.services import collector_db, stock

    orig = stock.get_candles

    async def fixed(symbol: str, period: str = "1y", interval: str = "1d", max_age_hours: float = 6) -> dict:
        got = collector_db.read_daily_candles(symbol, period, interval, today=d)
        return got if got is not None else {"symbol": symbol, "candles": [], "source": "none"}

    stock.get_candles = fixed
    try:
        yield
    finally:
        stock.get_candles = orig


async def _indicators(symbols: Iterable[str], d: date) -> dict[str, dict | None]:
    """종목마다 `get_quant_indicators` — 수집 DB 에서 왔고 마지막 봉이 d 인 것만 쓴다(아니면 None = 자료 없음)."""
    from app.services import stock

    out: dict[str, dict | None] = {}
    with _candles_as_of(d):
        for s in symbols:
            ind = await stock.get_quant_indicators(s, PERIOD)
            ok = not ind.get("error") and ind.get("source") == "collector" and ind.get("as_of") == d.isoformat()
            out[s] = ind if ok else None
    return out


def _missing(symbol: str, name: str) -> dict:
    return {"symbol": symbol, "name": name, "action": None, "missing": True, "reason": "자료 없음 — 그날 수집 DB 봉이 없다"}


def _default_decision(symbol: str, name: str, ind: dict | None) -> dict:
    if ind is None:
        return _missing(symbol, name)
    sig = ind.get("signal") or {}
    return {"symbol": symbol, "name": name, "score": sig.get("score", 0), "action": sig.get("action", "관망"),
            "rule_based": False, "reasons": [str(r) for r in (sig.get("reasons") or [])][:6],
            "close_adj": ind.get("current_price"), "as_of": ind.get("as_of")}


def _card_decision(symbol: str, name: str, ind: dict | None, card: dict) -> dict:
    from app.services import auto_trade

    if ind is None:
        return _missing(symbol, name)
    sig = auto_trade.apply_strategy_spec_to_signal(ind.get("signal") or {}, card, None, ind)
    return {"symbol": symbol, "name": name, "score": sig.get("score", 0), "action": sig.get("action", "관망"),
            "normalized_score": sig.get("normalized_score"), "rule_based": bool(sig.get("rule_based")),
            "reasons": [str(r) for r in (sig.get("reasons") or [])][:6],
            "close_adj": ind.get("current_price"), "as_of": ind.get("as_of")}


def _rank(universe: list[str], inds: dict[str, dict | None]) -> list[tuple[str, float]]:
    """자동매매 `symbol_source=ai` 와 같은 순위 — 점수 내림차순 · 같은 점수는 유니버스 차례(안정 정렬) · 자료 없는 종목은 0점."""
    ranked = [(s, ((inds.get(s) or {}).get("signal") or {}).get("score", 0)) for s in universe]
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked


async def decide(spec: dict, d: date) -> tuple[list[dict], list[dict]]:
    """(대상 종목 판단 — 크기 셈 차례, 31종목 점수 — 기본 규칙만)."""
    names = spec.get("names") or {}
    if spec["rule_id"] == RULE_CARD:
        targets = spec["universe"][: spec["selection"]["max_symbols"]]
        inds = await _indicators(targets, d)
        return [_card_decision(s, names.get(s, s), inds[s], spec["card"]) for s in targets], []
    universe = list(spec["universe"])
    inds = await _indicators(universe, d)
    ranked = _rank(universe, inds)
    top = [s for s, _ in ranked[: spec["selection"]["top_n"]]]
    return ([_default_decision(s, names.get(s, s), inds[s]) for s in top],
            [{"symbol": s, "score": sc, "missing": inds.get(s) is None} for s, sc in ranked])


# ── 4. 장부 · 크기 · 체결 · 평가 ──────────────────────────────────────────

@dataclass
class Book:
    """판 하나의 가상 계좌 — 앞 행의 끝 상태에서 이어 간다(새 판은 새 계좌)."""
    cash: float
    positions: dict[str, dict] = field(default_factory=dict)   # 기호 → {qty · avg_price · name}
    equity: float = 0.0

    @classmethod
    def start(cls, spec: dict) -> "Book":
        cash = float(spec["sizing"]["initial_cash"])
        return cls(cash=cash, positions={}, equity=cash)

    @classmethod
    def from_row(cls, row: dict) -> "Book":
        pos = {s: {"qty": int(p["qty"]), "avg_price": float(p["avg_price"]), "name": p.get("name", "")}
               for s, p in (row.get("positions") or {}).items() if int(p.get("qty", 0)) > 0}
        return cls(cash=float(row["cash"]), positions=pos, equity=float(row["equity"]))


def plan_orders(spec: dict, decisions: list[dict], book: Book, prices: dict[str, dict], d: date) -> tuple[list, list]:
    """판단 → 다음 거래일 시가 주문. 자동매매 `_run_quant_cycle` 의 크기 셈을 하루 한 번으로 옮겼다(설계 3절).

    매수 = `max(1, int(예산 ÷ 판단가))` → 하루 주문 수 한도 → 종목 비중 상한(`risk_guard.cap_buy_quantity`) ·
    매도 = 보유가 있을 때 `max(1, int(보유 × 매도 비율))`(비율 ≥ 1 이면 전부) → 하루 주문 수 한도. 판단가 = 그날 원주가 종가.
    """
    from app.services import risk_guard

    sz = spec["sizing"]
    budget = float(sz["per_trade_budget"]) * float(sz["buy_ratio"])
    sell_ratio = float(sz["sell_ratio"])
    max_orders = int(sz["max_orders_per_day"])
    orders: list[dict] = []
    skipped: list[dict] = []
    for dec in decisions:
        sym, action = dec["symbol"], dec.get("action")
        p = prices.get(sym) or {}
        price = p.get("close") or 0.0
        if dec.get("missing") or price <= 0 or action not in BUY_ACTIONS + SELL_ACTIONS:
            continue
        held = int((book.positions.get(sym) or {}).get("qty", 0))
        base = {"symbol": sym, "name": dec.get("name", ""), "decision_date": d.isoformat(), "decision_price": price,
                "action": action}
        if action in BUY_ACTIONS:
            qty = max(1, int(budget / price))
            if max_orders > 0 and len(orders) >= max_orders:
                skipped.append({**base, "side": "buy", "reason": f"일 주문 수 한도 {max_orders}건 도달"})
                continue
            qty, note = risk_guard.cap_buy_quantity(qty, price, held * price, book.equity, float(sz["max_position_pct"]))
            if qty <= 0:
                skipped.append({**base, "side": "buy", "reason": note or "비중 한도"})
                continue
            orders.append({**base, "side": "buy", "qty": int(qty), **({"note": note} if note else {})})
        else:
            if held <= 0:
                continue
            qty = held if sell_ratio >= 1.0 else max(1, int(held * sell_ratio))
            if max_orders > 0 and len(orders) >= max_orders:
                skipped.append({**base, "side": "sell", "reason": f"일 주문 수 한도 {max_orders}건 도달"})
                continue
            orders.append({**base, "side": "sell", "qty": int(qty)})
    return orders, skipped


def fill_orders(orders: list[dict], prices: dict[str, dict], book: Book, d: date, slippage_bps: float) -> list[dict]:
    """앞 행 주문을 그날 시가로 가상 체결 — 장부(`book`)를 바꾸고 체결 줄을 돌려준다(차례대로 · 매도 현금이 뒤 매수에 쓰인다).

    체결가 = 원주가 시가 × (1 ± 슬리피지) · 비용 = `trading_cost.order_costs`(슬리피지는 체결가에 들어 있어 비용에 다시 넣지 않는다).
    거래정지 · 시가 없음은 미체결(넘기지 않는다) · 현금이 모자라면 비용까지 살 수 있는 수량으로 줄인다(`_execute_virtual_trade` 와 같은 셈).
    """
    from app.services import trading_cost

    fills: list[dict] = []
    for o in orders:
        sym, side, want = o["symbol"], o["side"], int(o["qty"])
        p = prices.get(sym) or {}
        open_ = float(p.get("open") or 0.0)
        base = {"symbol": sym, "name": o.get("name", ""), "side": side, "qty_ordered": want,
                "decision_date": o.get("decision_date"), "decision_price": o.get("decision_price"), "open": open_ or None}
        if open_ <= 0 or p.get("halted"):
            fills.append({**base, "qty_filled": 0, "status": "unfilled", "reason": "거래정지 · 그날 시가 없음"})
            continue
        market = trading_cost.market_of(sym)
        is_etf = trading_cost.is_etf_name(o.get("name", ""))
        if side == "buy":
            px = open_ * (1 + slippage_bps / 10_000.0)

            def net(q: int) -> float:
                return trading_cost.order_costs(side="buy", price=px, quantity=q, when=d, market=market,
                                                is_etf=is_etf).net_amount

            qty = want
            if net(qty) > book.cash:
                rate = trading_cost.cost_rate("buy", d, slippage_bps=0.0, market=market)
                qty = int(book.cash // (px * (1 + rate))) if px > 0 else 0
                while qty > 0 and net(qty) > book.cash:
                    qty -= 1
            if qty <= 0:
                fills.append({**base, "qty_filled": 0, "status": "unfilled", "reason": "현금 부족"})
                continue
            oc = trading_cost.order_costs(side="buy", price=px, quantity=qty, when=d, market=market, is_etf=is_etf)
            held = book.positions.get(sym) or {"qty": 0, "avg_price": 0.0, "name": o.get("name", "")}
            new_qty = held["qty"] + qty
            held["avg_price"] = (held["avg_price"] * held["qty"] + px * qty) / new_qty
            held["qty"] = new_qty
            book.positions[sym] = held
            book.cash -= oc.net_amount
        else:
            held = book.positions.get(sym)
            if not held or held["qty"] <= 0:
                fills.append({**base, "qty_filled": 0, "status": "unfilled", "reason": "보유 없음"})
                continue
            qty = min(want, int(held["qty"]))
            px = open_ * (1 - slippage_bps / 10_000.0)
            oc = trading_cost.order_costs(side="sell", price=px, quantity=qty, when=d, market=market, is_etf=is_etf)
            held["qty"] -= qty
            if held["qty"] <= 0:
                book.positions.pop(sym, None)
            book.cash += oc.net_amount
        book.cash = _round_money(book.cash)
        fills.append({**base, "qty_filled": int(qty), "status": "filled" if qty == want else "partial",
                      "fill_price": round(px, 4), "slippage_bps": float(slippage_bps), "cost": oc.as_dict()})
    return fills


def mark_book(book: Book, prices: dict[str, dict]) -> tuple[dict, list[str]]:
    """그날 원주가 종가로 평가 — (보유 칸, 표시). 종가가 없는 보유는 평균 단가로 평가하고 표시를 남긴다."""
    flags: list[str] = []
    out: dict[str, dict] = {}
    total = book.cash
    for sym, h in sorted(book.positions.items()):
        close = float((prices.get(sym) or {}).get("close") or 0.0)
        if close <= 0:
            close = float(h["avg_price"])
            flags.append(f"종가 없음 — {sym} 평균 단가로 평가")
        value = h["qty"] * close
        total += value
        out[sym] = {"qty": int(h["qty"]), "avg_price": round(float(h["avg_price"]), 4), "name": h.get("name", ""),
                    "close": close, "value": _round_money(value)}
    book.equity = _round_money(total)
    return out, flags


async def compute_day(version: dict, prev: dict | None, d: date, *, now: datetime, commit: str,
                      fingerprint: str, watch_now: dict[str, str], path: Path | None = None) -> dict:
    """행 하나 — 앞 행(없으면 새 계좌)에서 이어 ①체결 ②평가 ③판단 ④주문 ⑤표시. 같은 입력이면 같은 행(계산 시각 · 커밋만 다름)."""
    spec = version["spec"]
    book = Book.from_row(prev) if prev else Book.start(spec)
    prev_equity = float(prev["equity"]) if prev else float(spec["sizing"]["initial_cash"])
    prev_orders = list(prev["orders"]) if prev else []
    need = set(spec["universe"]) | set(book.positions) | {o["symbol"] for o in prev_orders}
    prices = raw_prices(need, d, path=path)
    flags: list[str] = []

    # ⑤-1 보유 중 조정 사건 — 앞 거래일과 그날의 누적 조정계수 비가 1 이 아니면(분할 · 병합 · 권리락) 표시만
    if prev and book.positions:
        before = raw_prices(book.positions, date.fromisoformat(prev["trade_date"]), path=path)
        for sym in sorted(book.positions):
            f0, f1 = (before.get(sym) or {}).get("factor"), (prices.get(sym) or {}).get("factor")
            if f0 and f1 and abs(f0 / f1 - 1) > 1e-9:
                flags.append(f"조정 사건 — {sym} 계수 비 {f0 / f1:.6f} · 수량 · 단가는 그대로(배당 · 분할 미반영)")

    fills = fill_orders(prev_orders, prices, book, d, float(spec["fill"]["slippage_bps"]))
    positions, mark_flags = mark_book(book, prices)
    flags += mark_flags
    day_return = book.equity / prev_equity - 1 if prev_equity > 0 else 0.0
    limit = float(spec["sizing"]["daily_loss_limit_pct"])
    if limit > 0 and day_return * 100 <= -limit:
        flags.append(f"일손실 한도 {limit:g}% 넘음({day_return * 100:+.2f}%) — 실제 자동매매였다면 비상 정지 · 일지는 이어감")

    decisions, ranking = await decide(spec, d)
    orders, skipped = plan_orders(spec, decisions, book, prices, d)

    changed = changed_parts(version.get("watch_parts") or {}, watch_now)
    if changed:
        flags.append("참고 지문 바뀜 — " + " · ".join(changed) + "(실제 자동매매 회차가 일지와 달라졌을 수 있다)")

    seal = version["seal_start"] if isinstance(version["seal_start"], date) else date.fromisoformat(version["seal_start"])
    grade = "forward" if d >= seal else "post_hoc"
    recomputed = grade == "forward" and now.astimezone(KST).date() > next_trading_day(d, path=path)
    status = "partial" if any(x.get("missing") for x in decisions) else "ok"
    used = [x["as_of"] for x in decisions if x.get("as_of")]
    return {
        "trade_date": d.isoformat(), "grade": grade, "status": status,
        "computed_at": now.astimezone(KST).isoformat(timespec="seconds"), "recomputed": bool(recomputed),
        "data_as_of": max(used) if used else d.isoformat(), "code_commit": commit, "fingerprint": fingerprint,
        "fills": fills, "decisions": decisions, "ranking": ranking, "orders": orders, "skipped": skipped,
        "cash": _round_money(book.cash), "positions": positions, "equity": book.equity,
        "day_return": round(day_return, 8), "flags": flags,
    }


# ── 5. 앱 DB — 추가만 ─────────────────────────────────────────────────────

def version_dict(v: Any) -> dict:
    return {c: getattr(v, c) for c in ("id", "rule_id", "version_no", "attempt_no", "registered_at", "registered_by",
                                       "seal_start", "post_hoc_from", "post_hoc_to", "fingerprint", "fingerprint_parts",
                                       "watch_parts", "spec", "code_commit", "python", "supersedes_id", "change_parts")}


DAY_FIELDS = ("trade_date", "grade", "status", "computed_at", "recomputed", "data_as_of", "code_commit", "fingerprint",
              "fills", "decisions", "ranking", "orders", "skipped", "cash", "positions", "equity", "day_return", "flags")


def day_dict(r: Any) -> dict:
    out = {c: getattr(r, c) for c in DAY_FIELDS}
    out["trade_date"] = r.trade_date.isoformat()
    out["data_as_of"] = r.data_as_of.isoformat()
    out["computed_at"] = r.computed_at.astimezone(KST).isoformat(timespec="seconds")
    return out


async def latest_version(session, rule_id: str):
    from sqlalchemy import select

    from app.models.paper_journal import PaperJournalVersion

    return (await session.execute(select(PaperJournalVersion).where(PaperJournalVersion.rule_id == rule_id)
                                  .order_by(PaperJournalVersion.version_no.desc()).limit(1))).scalar_one_or_none()


async def last_day(session, version_id: int):
    from sqlalchemy import select

    from app.models.paper_journal import PaperJournalDay

    return (await session.execute(select(PaperJournalDay).where(PaperJournalDay.version_id == version_id)
                                  .order_by(PaperJournalDay.trade_date.desc()).limit(1))).scalar_one_or_none()


async def add_note(session, *, kind: str, text: str, author: str = "journal", version_id: int | None = None,
                   trade_date: date | None = None, now: datetime | None = None):
    from app.models.paper_journal import PaperJournalNote

    note = PaperJournalNote(version_id=version_id, trade_date=trade_date, kind=kind, author=author,
                            written_at=now or datetime.now(KST), text=text)
    session.add(note)
    await session.flush()
    return note


async def register(session, rule_id: str, *, now: datetime, by: str = "manual", prev=None,
                   commit: str | None = None, path: Path | None = None):
    """판 등록 — 판 1 은 사람(등록 명령) · 판 n+1 은 기계(지문이 바뀐 회차). 판 1 이면 사후 봉인 시험 구간을 연다(개봉 기록)."""
    from sqlalchemy import func, select

    from app.models.paper_journal import PaperJournalVersion

    latest = prev if prev is not None else await latest_version(session, rule_id)
    if by == "manual" and latest is not None:
        raise ValueError(f"{rule_id} 는 이미 판 {latest.version_no} 이 있다 — 판 바뀜은 지문이 바뀌면 기계가 등록한다")
    spec = rule_spec(rule_id)
    parts = fingerprint_parts(rule_id, spec)
    seal = seal_start_for(now, path=path)
    first = latest is None
    attempt = int(await session.scalar(select(func.count()).select_from(PaperJournalVersion)) or 0) + 1
    v = PaperJournalVersion(
        rule_id=rule_id, version_no=1 if first else latest.version_no + 1, attempt_no=attempt,
        registered_at=now, registered_by=by, seal_start=seal,
        post_hoc_from=POST_HOC_START if first else None,
        post_hoc_to=prev_trading_day(seal, path=path) if first else None,
        fingerprint=fingerprint_of(parts), fingerprint_parts=short_parts(parts), watch_parts=watch_parts(),
        spec=spec, code_commit=commit if commit is not None else git_head(), python=platform.python_version(),
        supersedes_id=None if first else latest.id,
        change_parts=[] if first else changed_parts(latest.fingerprint_parts or {}, parts),
    )
    session.add(v)
    await session.flush()
    if first:
        await add_note(session, kind="opening", version_id=v.id, now=now,
                       text=(f"사후 봉인 시험 구간 {v.post_hoc_from} ~ {v.post_hoc_to} 를 판 1 등록으로 연다 — 한 번만 계산하고 "
                             f"다시 계산하지 않는다 · 봉인 시작 {seal} · 누적 시도 {attempt}"))
    else:
        await add_note(session, kind="ops", version_id=v.id, now=now,
                       text=(f"판 바뀜 감지 — 바뀐 조각 {', '.join(v.change_parts) or '(없음)'} · 앞 판 {latest.version_no}"
                             f"(id {latest.id})의 남은 날은 계산하지 않는다(옛 코드가 없다) · 새 판 봉인 시작 {seal} · 새 계좌"))
    return v


async def run_daily(session, *, now: datetime, until: date | None = None, dry_run: bool = False,
                    path: Path | None = None) -> dict:
    """회차 하나 — 규칙마다 ① 지문 비교(다르면 새 판) ② 마지막 행 뒤 준비된 거래일을 차례로 계산해 더한다."""
    from sqlalchemy.dialects.postgresql import insert

    from app.models.paper_journal import PaperJournalDay

    commit = git_head()
    watch_now = watch_parts()
    summary: dict = {"at": now.astimezone(KST).isoformat(timespec="seconds"), "commit": commit, "rules": {},
                     "changed": [], "rows": 0, "dry_run": dry_run}
    for rule_id in RULES:
        ver = await latest_version(session, rule_id)
        if ver is None:
            summary["rules"][rule_id] = {"state": "unregistered"}
            continue
        spec_now = rule_spec(rule_id)
        parts_now = fingerprint_parts(rule_id, spec_now)
        fp_now = fingerprint_of(parts_now)
        if fp_now != ver.fingerprint:
            diff = changed_parts(ver.fingerprint_parts or {}, parts_now)
            summary["changed"].append({"rule_id": rule_id, "from_version": ver.version_no, "parts": diff})
            if dry_run:
                summary["rules"][rule_id] = {"state": "version_would_change", "version": ver.version_no, "parts": diff}
                continue
            ver = await register(session, rule_id, now=now, by="auto_fingerprint", prev=ver, commit=commit, path=path)
        vd = version_dict(ver)
        last = await last_day(session, ver.id)
        start = (last.trade_date + timedelta(days=1)) if last else (ver.post_hoc_from or ver.seal_start)
        end = until or now.astimezone(KST).date()
        days = ready_days(spec_now["universe"], start, end, path=path)
        info = {"version": ver.version_no, "version_id": ver.id, "days": [d.isoformat() for d in days],
                "last": last.trade_date.isoformat() if last else None, "written": 0}
        prev = day_dict(last) if last else None
        for d in days:
            if dry_run:
                continue
            row = await compute_day(vd, prev, d, now=now, commit=commit, fingerprint=fp_now, watch_now=watch_now,
                                    path=path)
            values = {**row, "version_id": ver.id, "trade_date": d, "data_as_of": date.fromisoformat(row["data_as_of"]),
                      "computed_at": now}
            res = await session.execute(insert(PaperJournalDay).values(**values)
                                        .on_conflict_do_nothing(constraint="uq_paper_journal_days_version_date"))
            if res.rowcount:
                info["written"] += 1
                info["last"] = row["trade_date"]
            prev = row
        summary["rules"][rule_id] = info
        summary["rows"] += info["written"]
    if not dry_run:
        await session.commit()
    return summary


async def load_all(session) -> tuple[list[dict], list[tuple[dict, dict]], list[dict]]:
    """내보내기용 — (판들, (판, 행)들, 메모들). 차례는 판 id · 거래일 · 메모 id."""
    from sqlalchemy import select

    from app.models.paper_journal import PaperJournalDay, PaperJournalNote, PaperJournalVersion

    vs = (await session.execute(select(PaperJournalVersion).order_by(PaperJournalVersion.id))).scalars().all()
    vmap = {v.id: version_dict(v) for v in vs}
    ds = (await session.execute(select(PaperJournalDay)
                                .order_by(PaperJournalDay.version_id, PaperJournalDay.trade_date))).scalars().all()
    ns = (await session.execute(select(PaperJournalNote).order_by(PaperJournalNote.id))).scalars().all()
    notes = [{c: getattr(n, c) for c in ("id", "version_id", "trade_date", "kind", "author", "written_at", "text")}
             for n in ns]
    return list(vmap.values()), [(vmap[d.version_id], day_dict(d)) for d in ds], notes


async def status(session) -> dict:
    """판 · 행 수 · 마지막 거래일 · 지금 지문이 판과 같은가 — 쓰지 않는다."""
    from sqlalchemy import func, select

    from app.models.paper_journal import PaperJournalDay, PaperJournalNote, PaperJournalVersion

    out: dict = {"rules": {}, "notes": int(await session.scalar(select(func.count()).select_from(PaperJournalNote)) or 0)}
    for rule_id in RULES:
        ver = await latest_version(session, rule_id)
        if ver is None:
            out["rules"][rule_id] = {"state": "unregistered"}
            continue
        n = await session.scalar(select(func.count()).select_from(PaperJournalDay).where(PaperJournalDay.version_id == ver.id))
        last = await last_day(session, ver.id)
        fp_now = fingerprint_of(fingerprint_parts(rule_id))
        out["rules"][rule_id] = {"version": ver.version_no, "attempt": ver.attempt_no, "seal_start": ver.seal_start.isoformat(),
                                 "rows": int(n or 0), "last": last.trade_date.isoformat() if last else None,
                                 "equity": last.equity if last else None, "fingerprint_same": fp_now == ver.fingerprint}
    return out


# ── 6. HF 원장 내보내기(파일 쓰기만 — 올리기는 scripts/paper_journal.py) ──

def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.astimezone(KST).isoformat(timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def export_rows(versions: list[dict], days: list[tuple[dict, dict]], notes: list[dict]) -> dict[str, dict]:
    """내보낼 파일 — 경로 → {"kind", "record"}. 기록은 JSON 으로 바꿀 수 있는 사전(같은 내용이면 같은 지문)."""
    files: dict[str, dict] = {}
    for v in versions:
        rec = {k: _jsonable(x) for k, x in v.items()}
        files[f"versions/{v['rule_id']}-v{v['version_no']}.json"] = {"kind": "version", "record": rec}
    for n in notes:
        rec = {k: _jsonable(x) for k, x in n.items()}
        files[f"notes/{int(n['id']):06d}.json"] = {"kind": "note", "record": rec}
    for v, r in days:
        rec = {"rule_id": v["rule_id"], "version_no": v["version_no"], **{k: _jsonable(x) for k, x in r.items()}}
        files[f"rows/{v['rule_id']}/v{v['version_no']}/{r['trade_date']}.parquet"] = {"kind": "day", "record": rec}
    return files


def content_sha(record: dict) -> str:
    return data_digest(record)


#: 묶음 칸 — parquet 에는 JSON 글자로 넣는다(행마다 모양이 달라도 한 표로 읽히게).
NESTED = ("fills", "decisions", "ranking", "orders", "skipped", "positions", "flags")


def write_export(files: dict[str, dict], out_dir: Path) -> dict:
    """파일을 쓰고 지문 목록(manifest)을 돌려준다 — 같은 내용이면 같은 내용 지문."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"schema": 1, "files": {}}
    for rel, item in sorted(files.items()):
        rec = item["record"]
        p = out_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".part")
        if rel.endswith(".parquet"):
            flat = {k: (canonical(v) if k in NESTED else v) for k, v in rec.items()}
            pq.write_table(pa.Table.from_pylist([flat]), tmp)
        else:
            tmp.write_text(json.dumps(rec, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
        tmp.replace(p)
        data = p.read_bytes()
        manifest["files"][rel] = {"kind": item["kind"], "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                                  "content_sha256": content_sha(rec)}
    kinds = [f["kind"] for f in manifest["files"].values()]
    manifest["counts"] = {k: kinds.count(k) for k in ("version", "day", "note")}
    return manifest


def immutability_problems(last: dict, now: dict) -> list[str]:
    """지난 지문 목록에 있던 파일이 지금 없거나 내용이 다르면 그 경로 — 하나라도 있으면 올리지 않는다(추가만)."""
    bad = []
    for rel, meta in sorted((last or {}).get("files", {}).items()):
        cur = (now.get("files") or {}).get(rel)
        if cur is None:
            bad.append(f"{rel} — 없어졌다")
        elif cur.get("content_sha256") != meta.get("content_sha256"):
            bad.append(f"{rel} — 내용이 바뀌었다")
    return bad
