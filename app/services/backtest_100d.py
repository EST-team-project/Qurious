"""100일 historical replay 백테스트 — UI 실행용 서비스.

- auto_trade.py 의 실시간 신호 함수(_calc_rsi·_calc_sma·_calc_bollinger·_generate_signal)를 그대로 재생.
- 체결은 paper_trading._fill_stock_order(..., filled_at=과거) — 그날의 수수료·세율로 정산.
- source="SIM" — 실시간 PAPER 이력과 분리.

⚠️ 백테스트이며 실 거래가 아니다.
⚠️ 진행 상태는 프로세스 메모리(_JOBS)에 저장 — uvicorn 단일 worker 환경 전제.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database.postgres import get_session_factory
from app.models import (
    Order, PaperAccountSnapshot, Portfolio,
    PORTFOLIO_BOOK_PAPER,
)
from app.services import paper_trading as pt
from app.services.stock import (
    get_candles, _generate_signal,
    _calc_rsi, _calc_sma, _calc_bollinger,
)
from app.services.auto_trade import QUANT_STOCKS

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
SOURCE = "SIM"
BACKTEST_START = date(2026, 7, 13)
BACKTEST_END = date(2026, 10, 20)
BUDGET_PER_TRADE = 5_000_000

UNIVERSE = [
    (s.get("symbol") if isinstance(s, dict) else s)
    for s in QUANT_STOCKS
][:10]

_JOBS: dict[str, dict] = {}


def get_job(task_id: str) -> dict | None:
    return _JOBS.get(task_id)


def _progress(task_id: str, **kw) -> None:
    _JOBS.setdefault(task_id, {}).update(kw)


def _to_date_str(key) -> str | None:
    """date 문자열 · ISO · 유닉스 초/ms 어느 것이든 'YYYY-MM-DD' 로."""
    if key is None:
        return None
    if isinstance(key, (int, float)):
        ts = key / 1000 if key > 1e11 else key   # ms vs s
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    s = str(key)
    if s.isdigit():
        ts = int(s) / 1000 if len(s) > 10 else int(s)
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    return s[:10]   # '2026-10-20' or '2026-10-20T15:30:00'


def _to_date_str(key) -> str | None:
    """date 문자열 · ISO · 유닉스 초/ms 어느 것이든 'YYYY-MM-DD' 로."""
    if key is None:
        return None
    if isinstance(key, (int, float)):
        ts = key / 1000 if key > 1e11 else key   # ms vs s
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    s = str(key)
    if s.isdigit():
        ts = int(s) / 1000 if len(s) > 10 else int(s)
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    return s[:10]   # '2026-10-20' or '2026-10-20T15:30:00'


async def _load_candles(symbol: str) -> dict:
    candles = (await get_candles(symbol, period="1y", interval="1d")).get("candles", [])
    out: dict[str, dict] = {}
    for c in candles:
        ds = _to_date_str(c.get("date") or c.get("time"))
        if ds:
            out[ds] = c
    rng = f"{min(out)}~{max(out)}" if out else "빈 범위"
    print(f"[BT-load] {symbol}: 봉 {len(out)}개, 범위 {rng}")
    return out


_SIGNAL_MAP = {
    "매수": "BUY", "매도": "SELL", "관망": "HOLD",
    "BUY": "BUY", "SELL": "SELL", "HOLD": "HOLD",
    "buy": "BUY", "sell": "SELL", "hold": "HOLD",
}


def _signal_upto(past: list[dict]) -> tuple[str, dict]:
    closes = [float(c["close"]) for c in past]
    rsi = _calc_rsi(closes)
    ma5 = _calc_sma(closes, 5)
    ma20 = _calc_sma(closes, 20)
    ma60 = _calc_sma(closes, 60)
    bb_upper, _bb_mid, bb_lower = _calc_bollinger(closes)
    sig = _generate_signal(
        closes=closes, rsi=rsi, ma5=ma5, ma20=ma20, ma60=ma60,
        bb_upper=bb_upper, bb_lower=bb_lower,
    ) or {}
    raw = sig.get("action") or sig.get("signal") or "HOLD"
    action = _SIGNAL_MAP.get(raw, "HOLD") if isinstance(raw, str) else "HOLD"
    return action, sig


async def run_backtest(user_id: uuid.UUID, task_id: str) -> None:
    """백그라운드 실행 — 진행률을 _JOBS 에 기록."""
    try:
        factory = get_session_factory()
    except RuntimeError as e:
        _progress(task_id, status="error", phase=f"DB 미연결: {e}",
                  finished=datetime.now(KST).isoformat(timespec="seconds"))
        return

    async with factory() as db:
        try:
            _progress(task_id, status="running", phase="계좌 초기화", progress=0)

            # 이전 SIM 데이터 정리
            await db.execute(delete(Order).where(
                Order.user_id == user_id, Order.source == SOURCE))
            await db.execute(delete(PaperAccountSnapshot).where(
                PaperAccountSnapshot.user_id == user_id))
            await pt.reset_account(db, user_id)
            await db.commit()

            _progress(task_id, phase="과거 시세 로딩 중")
            histories = {s: await _load_candles(s) for s in UNIVERSE}
            print(f"[BT] 로드 완료 · {len(histories)}종목")

            d = BACKTEST_START
            total = (BACKTEST_END - BACKTEST_START).days + 1
            done = 0
            trades = 0
            signals_seen = {"BUY": 0, "SELL": 0, "HOLD": 0}
            skips = {"no_bar": 0, "short_history": 0, "sell_no_pos": 0, "fill_error": 0}

            while d <= BACKTEST_END:
                if d.weekday() < 5:
                    for sym in UNIVERSE:
                        hist = histories[sym]
                        if d.isoformat() not in hist:
                            skips["no_bar"] += 1
                            continue
                        past = [c for dt, c in sorted(hist.items()) if dt <= d.isoformat()]
                        if len(past) < 60:
                            skips["short_history"] += 1
                            continue

                        action, sig = _signal_upto(past)
                        signals_seen[action] = signals_seen.get(action, 0) + 1

                        if action not in ("BUY", "SELL"):
                            continue

                        close = float(hist[d.isoformat()]["close"])
                        filled_at = datetime(d.year, d.month, d.day, 15, 30, tzinfo=KST)
                        info = {"symbol": sym, "price": close, "currency": "KRW",
                                "market": "KOSPI", "name": sym}

                        try:
                            if action == "BUY":
                                qty = int(BUDGET_PER_TRADE // close)
                                if qty <= 0:
                                    continue
                                await pt._fill_stock_order(
                                    db, user_id, info, "BUY", qty,
                                    source=SOURCE, filled_at=filled_at)
                                trades += 1
                                print(f"[BT-fill] {d} BUY {sym} {qty}@{close:,.0f}")
                            else:  # SELL
                                pos = await pt._stock_position(db, user_id, sym)
                                if not pos or pos.quantity <= 0:
                                    skips["sell_no_pos"] += 1
                                    continue
                                await pt._fill_stock_order(
                                    db, user_id, info, "SELL", pos.quantity,
                                    source=SOURCE, filled_at=filled_at)
                                trades += 1
                                print(f"[BT-fill] {d} SELL {sym} {pos.quantity}@{close:,.0f}")
                        except pt.PaperTradeError as e:
                            skips["fill_error"] += 1
                            print(f"[BT-skip] {d} {action} {sym}: {e}")
                        except Exception as e:
                            skips["fill_error"] += 1
                            logger.warning("[BT-error] %s %s %s: %s", d, action, sym, e)

                    # 스냅샷 — 그날 날짜로 직접 insert
                    try:
                        snap_data = await pt.account_snapshot(db, user_id)
                        cur_equity = float(snap_data.get("totalAsset") or 0)
                        prev_row = (await db.execute(
                            select(PaperAccountSnapshot)
                            .where(PaperAccountSnapshot.user_id == user_id)
                            .where(PaperAccountSnapshot.snap_date < d)
                            .order_by(PaperAccountSnapshot.snap_date.desc())
                            .limit(1)
                        )).scalar_one_or_none()
                        prev_eq = float(prev_row.total_equity) if prev_row else None
                        daily = (cur_equity / prev_eq - 1) if prev_eq else 0.0

                        snap_vals = dict(
                            id=uuid.uuid4(),
                            user_id=user_id,
                            snap_date=d,
                            cash=float(snap_data.get("cash") or 0),
                            position_value=cur_equity - float(snap_data.get("cash") or 0),
                            total_equity=cur_equity,
                            daily_return=daily,
                            position_count=sum(int(v or 0) for v in (snap_data.get("counts") or {}).values()),
                            stock_value=float(snap_data.get("stockEval") or 0),
                            crypto_value=float(snap_data.get("cryptoEval") or 0),
                            alt_value=float(snap_data.get("alternativeEval") or 0),
                        )
                        stmt = pg_insert(PaperAccountSnapshot).values(**snap_vals).on_conflict_do_update(
                            index_elements=["user_id", "snap_date"],
                            set_={k: snap_vals[k] for k in (
                                "cash", "position_value", "total_equity", "daily_return",
                                "position_count", "stock_value", "crypto_value", "alt_value",
                            )},
                        )
                        await db.execute(stmt)
                    except Exception as e:
                        logger.warning("snapshot %s 실패: %s", d, e)
                    await db.commit()

                d += timedelta(days=1)
                done += 1
                if done % 5 == 0 or done == total:
                    _progress(task_id,
                              phase=f"{done}/{total}일 · 거래 {trades}건",
                              progress=round(done / total * 100))

            # 최종 요약 로그
            summary = (
                f"\n[BT-summary] 거래 {trades}건 · 신호 {signals_seen} · skip {skips}\n"
                f"[BT-summary] 완료 {done}/{total}일\n"
            )
            print(summary)

            _progress(task_id, status="done",
                      phase=f"완료 · {done}일 · 거래 {trades}건",
                      progress=100, trades=trades,
                      signals=signals_seen, skips=skips,
                      finished=datetime.now(KST).isoformat(timespec="seconds"))
        except Exception as e:
            logger.exception("backtest_100d 실패")
            _progress(task_id, status="error", phase=f"실패: {e}",
                      error=str(e),
                      finished=datetime.now(KST).isoformat(timespec="seconds"))


async def delete_backtest(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """SIM 주문 + 스냅샷 + 포지션 삭제 · 계좌 1억 초기화."""
    await db.execute(delete(Order).where(
        Order.user_id == user_id, Order.source == SOURCE))
    await db.execute(delete(PaperAccountSnapshot).where(
        PaperAccountSnapshot.user_id == user_id))
    await db.execute(delete(Portfolio).where(
        Portfolio.user_id == user_id, Portfolio.book == PORTFOLIO_BOOK_PAPER))
    await pt.reset_account(db, user_id)
    await db.commit()
    return {"status": "ok", "deleted": True}