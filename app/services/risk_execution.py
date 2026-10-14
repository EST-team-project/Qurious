"""현재 자동매매 설정 설명과 기존 비용 모델의 손익비 예시. 주문 정책은 바꾸지 않는다."""
import math

from app.config import settings
from app.services import trading_cost as costs


def exit_cost_example(take_profit_pct, stop_loss_pct, when, slippage_bps=0.0):
    """동일 매입금액으로 익절/손절 한 번씩 체결했다고 가정한 비율 비교.

    비용 모듈의 편도 비율을 사용한다. 슬리피지는 편도 비용 가정이며
    주수/원 단위 절사, 갭·체결 실패·실제 계좌 수수료는 포함하지 않는다.
    """
    tp, sl, slip = map(float, (take_profit_pct, stop_loss_pct, slippage_bps))
    if not all(math.isfinite(x) for x in (tp, sl, slip)) or tp <= 0 or not 0 < sl < 100 or slip < 0:
        raise ValueError("익절·손절·슬리피지 가정을 확인하세요.")
    buy = costs.cost_rate("buy", when, slippage_bps=slip, market="KOSPI", is_etf=False)
    sell = costs.cost_rate("sell", when, slippage_bps=slip, market="KOSPI", is_etf=False)
    win = ((1 + tp / 100) * (1 - sell) / (1 + buy) - 1) * 100
    loss = -((1 - sl / 100) * (1 - sell) / (1 + buy) - 1) * 100
    profitable = win > 0 and loss > 0
    return {
        "slippage_bps_per_side": slip,
        "net_take_profit_pct": round(win, 4),
        "net_stop_loss_pct": round(-loss, 4),
        "reward_risk_ratio": round(win / loss, 4) if profitable else None,
        "break_even_win_rate_pct": round(loss / (win + loss) * 100, 4) if profitable else None,
    }


def execution_guidance():
    day = costs.today_kst()
    tp, sl = settings.QUANT_AGGRESSIVE_TAKE_PROFIT_PCT, settings.QUANT_AGGRESSIVE_STOP_LOSS_PCT
    try:
        examples = [exit_cost_example(tp, sl, day, slip) for slip in (0, costs.DEFAULT_SLIPPAGE_BPS)]
    except ValueError:
        examples = []
    return {
        "cycle_seconds": settings.QUANT_CYCLE_SEC,
        "aggressive_enabled": bool(settings.QUANT_AGGRESSIVE_MODE),
        "take_profit_pct": tp,
        "stop_loss_pct": sl,
        "cancel_open_after_min": settings.STOCK_COIN_TRADE_CANCEL_OPEN_AFTER_MIN,
        "cost_example": {
            "as_of": day.isoformat(), "market": "KOSPI", "is_etf": False,
            "basis": "기존 비용 모듈의 일반 코스피 주식·온라인 수수료 가정. 실제 계좌 비용·체결 결과가 아닙니다.",
            "scenarios": examples,
        },
    }
