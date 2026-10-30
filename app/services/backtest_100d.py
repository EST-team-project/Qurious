"""100일 historical replay 백테스트 — PAPER 계좌와 격리."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.postgres import get_session_factory
from app.models import Order
from app.services import backtest_ledger as ledger
from app.services.stock import (
    get_candles,
    _generate_signal,
    _calc_rsi,
    _calc_sma,
    _calc_bollinger,
)
from app.services.auto_trade import QUANT_STOCKS


logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")

BACKTEST_START = date(2026, 7, 13)
BACKTEST_END = date(2026, 10, 20)
BUDGET_PER_TRADE = 5_000_000

UNIVERSE = [
    (s.get("symbol") if isinstance(s, dict) else s)
    for s in QUANT_STOCKS
][:10]

_JOBS: dict[str, dict] = {}
_JOB_OWNERS: dict[str, str] = {}
_ACTIVE_USERS: set[str] = set()


def start_job(user_id: uuid.UUID, task_id: str) -> bool:
    """사용자별 백테스트 중복 실행 방지 및 작업 소유권 등록."""
    uid = str(user_id)

    if uid in _ACTIVE_USERS:
        return False

    _ACTIVE_USERS.add(uid)
    _JOB_OWNERS[task_id] = uid
    _JOBS[task_id] = {
        "status": "running",
        "phase": "시작",
        "progress": 0,
    }
    return True


def is_running(user_id: uuid.UUID) -> bool:
    return str(user_id) in _ACTIVE_USERS


def get_job(task_id: str, user_id: uuid.UUID) -> dict | None:
    """작업 소유자만 상태 조회 가능."""
    if _JOB_OWNERS.get(task_id) != str(user_id):
        return None

    return _JOBS.get(task_id)


def _progress(task_id: str, **kw) -> None:
    _JOBS.setdefault(task_id, {}).update(kw)

    if kw.get("status") in ("done", "error"):
        owner = _JOB_OWNERS.get(task_id)
        if owner:
            _ACTIVE_USERS.discard(owner)


def _to_date_str(key) -> str | None:
    if key is None:
        return None

    if isinstance(key, (int, float)):
        ts = key / 1000 if key > 1e11 else key
        return datetime.fromtimestamp(
            ts, tz=timezone.utc
        ).strftime("%Y-%m-%d")

    value = str(key)

    if value.isdigit():
        ts = int(value) / 1000 if len(value) > 10 else int(value)
        return datetime.fromtimestamp(
            ts, tz=timezone.utc
        ).strftime("%Y-%m-%d")

    return value[:10]


async def _load_candles(symbol: str) -> dict:
    candles = (
        await get_candles(
            symbol,
            period="1y",
            interval="1d",
        )
    ).get("candles", [])

    result = {}

    for candle in candles:
        date_str = _to_date_str(
            candle.get("date") or candle.get("time")
        )
        if date_str:
            result[date_str] = candle

    date_range = (
        f"{min(result)}~{max(result)}"
        if result
        else "빈 범위"
    )

    print(
        f"[BT-load] {symbol}: 봉 {len(result)}개, "
        f"범위 {date_range}"
    )

    return result


_SIGNAL_MAP = {
    "매수": "BUY",
    "매도": "SELL",
    "관망": "HOLD",
    "BUY": "BUY",
    "SELL": "SELL",
    "HOLD": "HOLD",
    "buy": "BUY",
    "sell": "SELL",
    "hold": "HOLD",
}


def _signal_upto(past: list[dict]) -> tuple[str, dict]:
    closes = [float(c["close"]) for c in past]

    rsi = _calc_rsi(closes)
    ma5 = _calc_sma(closes, 5)
    ma20 = _calc_sma(closes, 20)
    ma60 = _calc_sma(closes, 60)

    bb_upper, _bb_mid, bb_lower = _calc_bollinger(closes)

    signal = _generate_signal(
        closes=closes,
        rsi=rsi,
        ma5=ma5,
        ma20=ma20,
        ma60=ma60,
        bb_upper=bb_upper,
        bb_lower=bb_lower,
    ) or {}

    raw = signal.get("action") or signal.get("signal") or "HOLD"
    action = (
        _SIGNAL_MAP.get(raw, "HOLD")
        if isinstance(raw, str)
        else "HOLD"
    )

    return action, signal


async def run_backtest(
    user_id: uuid.UUID,
    task_id: str,
) -> None:
    """백그라운드 실행."""

    try:
        factory = get_session_factory()
    except RuntimeError as exc:
        _progress(
            task_id,
            status="error",
            phase=f"DB 미연결: {exc}",
            finished=datetime.now(KST).isoformat(timespec="seconds"),
        )
        return

    async with factory() as db:
        try:
            _progress(
                task_id,
                status="running",
                phase="백테스트 전용 계좌 초기화",
                progress=0,
            )

            # PAPER와 무관한 백테스트 자료만 초기화
            await ledger.reset_backtest(db, user_id)
            await db.commit()

            _progress(task_id, phase="과거 시세 로딩 중")

            histories = {
                symbol: await _load_candles(symbol)
                for symbol in UNIVERSE
            }

            print(f"[BT] 로드 완료 · {len(histories)}종목")

            current_date = BACKTEST_START
            total = (BACKTEST_END - BACKTEST_START).days + 1
            done = 0
            trades = 0

            signals_seen = {
                "BUY": 0,
                "SELL": 0,
                "HOLD": 0,
            }

            skips = {
                "no_bar": 0,
                "short_history": 0,
                "sell_no_pos": 0,
                "fill_error": 0,
            }

            # 각 종목의 마지막 확인 종가
            last_prices: dict[str, float] = {}

            while current_date <= BACKTEST_END:
                date_key = current_date.isoformat()

                if current_date.weekday() < 5:
                    for symbol in UNIVERSE:
                        history = histories[symbol]

                        if date_key not in history:
                            skips["no_bar"] += 1
                            continue

                        past = [
                            candle
                            for day, candle in sorted(history.items())
                            if day <= date_key
                        ]

                        if len(past) < 60:
                            skips["short_history"] += 1
                            continue

                        close = float(history[date_key]["close"])

                        if close <= 0:
                            skips["no_bar"] += 1
                            continue

                        last_prices[symbol] = close

                        action, signal = _signal_upto(past)
                        signals_seen[action] = (
                            signals_seen.get(action, 0) + 1
                        )

                        if action not in ("BUY", "SELL"):
                            continue

                        filled_at = datetime(
                            current_date.year,
                            current_date.month,
                            current_date.day,
                            15,
                            30,
                            tzinfo=KST,
                        )

                        info = {
                            "symbol": symbol,
                            "price": close,
                            "currency": "KRW",
                            "market": "KOSPI",
                            "name": symbol,
                        }

                        try:
                            if action == "BUY":
                                quantity = int(
                                    BUDGET_PER_TRADE // close
                                )

                                if quantity <= 0:
                                    continue

                                await ledger.fill_stock_order(
                                    db,
                                    user_id,
                                    info,
                                    "BUY",
                                    quantity,
                                    filled_at=filled_at,
                                )

                                trades += 1

                                print(
                                    f"[BT-fill] {current_date} "
                                    f"BUY {symbol} {quantity}@{close:,.0f}"
                                )

                            else:
                                position = await ledger.get_position(
                                    db,
                                    user_id,
                                    symbol,
                                )

                                if (
                                    position is None
                                    or position.quantity <= 0
                                ):
                                    skips["sell_no_pos"] += 1
                                    continue

                                quantity = position.quantity

                                await ledger.fill_stock_order(
                                    db,
                                    user_id,
                                    info,
                                    "SELL",
                                    quantity,
                                    filled_at=filled_at,
                                )

                                trades += 1

                                print(
                                    f"[BT-fill] {current_date} "
                                    f"SELL {symbol} {quantity}@{close:,.0f}"
                                )

                        except ledger.BacktestTradeError as exc:
                            skips["fill_error"] += 1
                            print(
                                f"[BT-skip] {current_date} "
                                f"{action} {symbol}: {exc}"
                            )

                        except Exception as exc:
                            skips["fill_error"] += 1
                            logger.exception(
                                "[BT-error] %s %s %s",
                                current_date,
                                action,
                                symbol,
                            )

                    # 백테스트 전용 장부로만 일별 평가
                    await ledger.save_snapshot(
                        db,
                        user_id,
                        current_date,
                        last_prices,
                    )

                    await db.commit()

                current_date += timedelta(days=1)
                done += 1

                if done % 5 == 0 or done == total:
                    _progress(
                        task_id,
                        phase=f"{done}/{total}일 · 거래 {trades}건",
                        progress=round(done / total * 100),
                    )

            summary = (
                f"\n[BT-summary] 거래 {trades}건 · "
                f"신호 {signals_seen} · skip {skips}\n"
                f"[BT-summary] 완료 {done}/{total}일\n"
            )

            print(summary)

            _progress(
                task_id,
                status="done",
                phase=f"완료 · {done}일 · 거래 {trades}건",
                progress=100,
                trades=trades,
                signals=signals_seen,
                skips=skips,
                finished=datetime.now(KST).isoformat(timespec="seconds"),
            )

        except Exception as exc:
            await db.rollback()
            logger.exception("backtest_100d 실패")

            _progress(
                task_id,
                status="error",
                phase=f"실패: {exc}",
                error=str(exc),
                finished=datetime.now(KST).isoformat(timespec="seconds"),
            )


async def delete_backtest(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict:
    """백테스트 데이터만 삭제하고 전용 계좌만 초기화."""

    await ledger.reset_backtest(db, user_id)
    await db.commit()

    return {
        "status": "ok",
        "deleted": True,
        "scope": "BACKTEST_ONLY",
    }