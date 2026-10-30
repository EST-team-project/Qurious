"""
퀀트 ML 파이프라인: OHLCV → 전처리 → 피처 → ML/DL → 시그널 → 백테스트 → Alpaca
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Any

from app.services import ta_utils as ta
from app.services import trading_cost as tcost

try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False

try:
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


# ── 1. 전처리 ─────────────────────────────────────────────────────────

def preprocess(candles: list[dict]) -> pd.DataFrame:
    """원시 OHLCV → 정제된 DataFrame.

    - Unix timestamp → DatetimeIndex
    - 결측치: forward/backward fill
    - 이상치: 종가 0 이하 제거
    """
    df = pd.DataFrame(candles)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time").sort_index()
    df = df[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    df = df.ffill().bfill()
    df = df[df["close"] > 0]
    return df


# ── 2. 피처 엔지니어링 ────────────────────────────────────────────────

FEATURE_COLS = [
    "ret_1", "ret_5", "ret_20",
    "ma5_ratio", "ma20_ratio",
    "rsi", "macd", "macd_hist",
    "bb_width", "bb_pos",
    "vol_ratio", "atr",
]


def feature_engineer(df: pd.DataFrame) -> pd.DataFrame:
    """피처 엔지니어링: 수익률, 이동평균, RSI, MACD, 볼린저밴드, 거래량, ATR."""
    out = df.copy()
    c = out["close"].astype(float)
    v = out["volume"].astype(float)

    # 수익률
    out["ret_1"]  = c.pct_change(1)
    out["ret_5"]  = c.pct_change(5)
    out["ret_20"] = c.pct_change(20)

    # 이동평균 비율
    ma5  = c.rolling(5).mean()
    ma20 = c.rolling(20).mean()
    out["ma5_ratio"]  = c / ma5.replace(0, np.nan)
    out["ma20_ratio"] = c / ma20.replace(0, np.nan)

    # RSI (14)
    out["rsi"] = ta.rsi(c, 14)

    # MACD (12/26/9)
    macd_line, _macd_sig, macd_hist = ta.macd(c, 12, 26, 9)
    out["macd"]      = macd_line
    out["macd_hist"] = macd_hist

    # 볼린저밴드 (20, 2σ)
    bb_upper, bb_mid, bb_lower = ta.bollinger(c, 20, 2.0)
    bb_range = (bb_upper - bb_lower).replace(0, np.nan)
    out["bb_width"] = bb_range / bb_mid.replace(0, np.nan)
    out["bb_pos"]   = (c - bb_lower) / bb_range

    # 거래량 비율
    vol_ma20 = v.rolling(20).mean()
    out["vol_ratio"] = v / vol_ma20.replace(0, np.nan)

    # ATR (14)
    out["atr"] = ta.atr(out["high"].astype(float), out["low"].astype(float), c, 14)

    # 타깃: 5일 후 수익률 → 3-class 레이블 (1=매수, 0=관망, -1=매도)
    fut = c.pct_change(5).shift(-5)
    out["target"] = 0
    out.loc[fut >  0.02, "target"] =  1
    out.loc[fut < -0.02, "target"] = -1

    return out.dropna()


# ── 3. LightGBM (ML 방향성 분류) ──────────────────────────────────────

def train_lgb(df: pd.DataFrame) -> tuple[Any, dict]:
    """LightGBM 방향성 분류 모델 (매도/관망/매수 3-class).

    Returns: (model, metrics)
    """
    if not HAS_LGB:
        raise RuntimeError("lightgbm이 설치되지 않았습니다: pip install lightgbm")

    X = df[FEATURE_COLS].values
    y = (df["target"].values + 1).astype(int)   # -1,0,1 → 0,1,2

    split = int(len(X) * 0.8)
    X_tr, X_va = X[:split], X[split:]
    y_tr, y_va = y[:split], y[split:]

    d_tr = lgb.Dataset(X_tr, label=y_tr)
    d_va = lgb.Dataset(X_va, label=y_va, reference=d_tr)

    params = {
        "objective": "multiclass",
        "num_class": 3,
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "verbosity": -1,
        "random_state": 42,
    }
    model = lgb.train(
        params, d_tr,
        num_boost_round=200,
        valid_sets=[d_va],
        callbacks=[lgb.early_stopping(20, verbose=False), lgb.log_evaluation(-1)],
    )

    # 검증 정확도
    preds = np.argmax(model.predict(X_va), axis=1)
    acc = float((preds == y_va).mean())

    # 피처 중요도
    importance = dict(zip(FEATURE_COLS, model.feature_importance("gain").tolist()))

    return model, {"val_accuracy": round(acc, 4), "feature_importance": importance}


def predict_lgb(model: Any, df: pd.DataFrame) -> pd.Series:
    """LightGBM 예측 → 시그널 Series (-1/0/+1)."""
    probs = model.predict(df[FEATURE_COLS].values)   # (N, 3)
    pred = np.argmax(probs, axis=1) - 1              # 0,1,2 → -1,0,+1
    return pd.Series(pred, index=df.index, name="ml_signal")


# ── 4. MLP Neural Net (DL 대안: sklearn MLPClassifier) ───────────────

def train_mlp(df: pd.DataFrame) -> tuple[Any, Any, dict]:
    """MLP 신경망 학습 (64→32→출력).

    sklearn MLPClassifier = 경량 DL 모델 (PyTorch/TF 없이 동작).
    Returns: (model, scaler, metrics)
    """
    if not HAS_SKLEARN:
        raise RuntimeError("scikit-learn이 설치되지 않았습니다: pip install scikit-learn")

    X = df[FEATURE_COLS].values
    y = df["target"].values   # -1, 0, 1

    split = int(len(X) * 0.8)
    X_tr, X_va = X[:split], X[split:]
    y_tr, y_va = y[:split], y[split:]

    scaler = StandardScaler()
    X_tr_s = scaler.fit_transform(X_tr)
    X_va_s = scaler.transform(X_va)

    model = MLPClassifier(
        hidden_layer_sizes=(64, 32),
        activation="relu",
        solver="adam",
        learning_rate_init=0.001,
        max_iter=300,
        early_stopping=True,
        validation_fraction=0.1,
        random_state=42,
        verbose=False,
    )
    model.fit(X_tr_s, y_tr)

    acc = float(model.score(X_va_s, y_va))
    return model, scaler, {"val_accuracy": round(acc, 4)}


def predict_mlp(model: Any, scaler: Any, df: pd.DataFrame) -> pd.Series:
    """MLP 예측 → 시그널 Series (-1/0/+1)."""
    X_s = scaler.transform(df[FEATURE_COLS].values)
    pred = model.predict(X_s)
    return pd.Series(pred, index=df.index, name="ml_signal")


# ── 5. 규칙 기반 시그널 (ML 불가 시 fallback) ────────────────────────

def rule_based_signals(df: pd.DataFrame) -> pd.Series:
    """RSI + MACD + 볼린저 점수 합산 → 시그널."""
    score = pd.Series(0.0, index=df.index)

    # RSI
    score += (df["rsi"] < 30).astype(float) * 2
    score -= (df["rsi"] > 70).astype(float) * 2

    # MACD 히스토그램 방향
    score += (df["macd_hist"] > 0).astype(float)
    score -= (df["macd_hist"] < 0).astype(float)

    # 볼린저 위치
    score += (df["bb_pos"] < 0.1).astype(float)
    score -= (df["bb_pos"] > 0.9).astype(float)

    # 이동평균 추세
    score += (df["ma5_ratio"] > df["ma20_ratio"]).astype(float)
    score -= (df["ma5_ratio"] < df["ma20_ratio"]).astype(float)

    sig = pd.Series(0, index=df.index, name="ml_signal")
    sig[score >= 3] = 1
    sig[score <= -3] = -1
    return sig


# ── 6. 백테스트 ───────────────────────────────────────────────────────

# 손절 · 익절을 무엇으로 판정하나 — apply_stops 는 그날 종가로 본다(전략 카드 판 2 `stops.judge` 와 같은 낱말 · #161 A3).
STOP_JUDGE = "close"


def apply_stops(
    close: pd.Series,
    held: pd.Series,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    return_exits: bool = False,
    *,
    atr_values: pd.Series | None = None,
    atr_mult: float | None = None,
    take_rr: float | None = None,
    entry_mode: str = "close",
    open_: pd.Series | None = None,
):
    """종가 기준 손절·익절. ATR은 진입 당시 값으로 고정한다."""
    if entry_mode not in ("close", "open"):
        raise ValueError("entry_mode must be close or open")
    if atr_mult is not None and atr_mult <= 0:
        raise ValueError("atr_mult must be positive")
    if take_rr is not None and take_rr <= 0:
        raise ValueError("take_rr must be positive")

    # 손절·익절 설정이 없으면 기존 동작과 동일하게 입력 보유 신호를 보존한다.
    if (
        stop_loss_pct is None
        and take_profit_pct is None
        and atr_mult is None
    ):
        unchanged = held.reindex(close.index).fillna(0).astype(float).copy()
        if return_exits:
            return unchanged, []
        return unchanged, 0, 0

    c = close.astype(float).to_numpy()
    h = held.reindex(close.index).fillna(0).astype(float).to_numpy()
    o = open_.reindex(close.index).astype(float).to_numpy() if open_ is not None else None
    a = atr_values.reindex(close.index).astype(float).to_numpy() if atr_values is not None else None

    out = h.copy()
    active = False
    blocked = False
    entry_price = stop_price = take_price = None
    exits = []
    n_sl = n_tp = 0

    for i in range(len(c)):
        if h[i] != 1:
            active = blocked = False
            entry_price = stop_price = take_price = None
            out[i] = 0
            continue

        if not active:
            if blocked:
                out[i] = 0
                continue

            entry_price = (
                o[i] if entry_mode == "open" and o is not None
                else c[i - 1] if i > 0 else c[i]
            )
            if not np.isfinite(entry_price) or entry_price <= 0:
                out[i] = 0
                continue

            atr_entry = a[i - 1] if a is not None and i > 0 else np.nan
            if atr_mult is not None:
                if not np.isfinite(atr_entry) or atr_entry <= 0:
                    raise ValueError("ATR 진입 기준값이 없어 손절가를 계산할 수 없습니다.")
                distance = float(atr_entry) * atr_mult
                stop_price = entry_price - distance
                take_price = (
                    entry_price + distance * take_rr
                    if take_rr is not None else None
                )
            else:
                stop_price = (
                    entry_price * (1 - stop_loss_pct / 100)
                    if stop_loss_pct is not None else None
                )
                take_price = (
                    entry_price * (1 + take_profit_pct / 100)
                    if take_profit_pct is not None else None
                )
            active = True

        out[i] = 1
        hit_stop = stop_price is not None and c[i] <= stop_price
        hit_take = take_price is not None and c[i] >= take_price
        if not (hit_stop or hit_take):
            continue

        # 같은 종가에서 양쪽 기준을 모두 넘으면 보수적으로 손절 우선
        is_stop = bool(hit_stop)
        target = stop_price if is_stop else take_price
        if atr_mult is None:
            planned_pct = (
                -float(stop_loss_pct) if is_stop
                else float(take_profit_pct)
            )
        else:
            planned_pct = (target / entry_price - 1) * 100
        actual_pct = (c[i] / entry_price - 1) * 100
        exits.append({
            "type": "stop" if is_stop else "take",
            "planned_pct": float(planned_pct),
            "actual_pct": float(actual_pct),
            "gap": bool(actual_pct < planned_pct - 1e-9) if is_stop
                   else bool(actual_pct > planned_pct + 1e-9),
            "entry_price": float(entry_price),
            "trigger_price": float(c[i]),
            "stop_price": float(stop_price) if stop_price is not None else None,
            "take_price": float(take_price) if take_price is not None else None,
        })
        n_sl += int(is_stop)
        n_tp += int(not is_stop)
        active = False
        blocked = True

    adjusted = pd.Series(out, index=close.index, dtype=float)
    if return_exits:
        return adjusted, exits
    return adjusted, n_sl, n_tp


def _side_rates(cost: Any | None, index: pd.Index) -> tuple[np.ndarray, np.ndarray]:
    """날짜별 (매수율, 매도율) — 비용 모델의 공개 함수 `turnover_cost` 만으로 뽑는다.

    보유를 1 · 0 으로 번갈아 놓으면 하루에 한쪽(매수 또는 매도)만 일어나므로, 엇갈린 두 줄로
    모든 날의 매수율 · 매도율을 얻는다. 첫날 매도율은 쓰지 않는다(첫날에는 팔 것이 없다).
    """
    n = len(index)
    if cost is None or n == 0:
        return np.zeros(n), np.zeros(n)
    even = np.arange(n) % 2 == 0
    a = cost.turnover_cost(pd.Series(even.astype(float), index=index)).to_numpy()
    b = cost.turnover_cost(pd.Series((~even).astype(float), index=index)).to_numpy()
    buy = np.where(even, a, b)
    sell = np.where(even, b, a)
    sell[0] = sell[1] if n > 1 else 0.0
    return buy, sell


def size_positions(df: pd.DataFrame, held: pd.Series, *, risk_pct: float, initial_capital: float = 10_000_000.0,
                   max_position_pct: float = 30.0, cost: Any | None = None, entry_mode: str = "close",
                   exit_mode: str = "close", atr_values: pd.Series | None = None, atr_mult: float | None = None,
                   stop_loss_pct: float | None = None) -> dict:
    """보유 신호(`apply_stops` 뒤)를 주 수로 바꿔 현금 · 평가액을 날마다 따라간다 — 전략 카드 판 2 의 수량 칸.

    - 수량은 신호를 판단한 날(진입 전날) 종가 · ATR · 평가액으로 낸다 — 판단 시점까지의 자료만(#314 2026-10-27 4번).
      계산은 오준영 님 `execution_policy.risk_quantity` 한 곳(위험 1% ÷ 비용 포함 1주 손실 · 현금 · 종목 비중 상한).
    - 체결은 카드의 `entry_mode` · `exit_mode`(엔진과 같은 가격) · 체결 때 현금이 모자라면 살 수 있는 만큼만.
    - 첫 진입만 하고(더 사지 않음) 청산은 보유 전량(설계서 4.3 판 2 ⑤).
    - 수량의 1주 손실은 국내 실제 요율로 잰다(`risk_quantity`) · 평가액에서 떼는 비용은 넘긴 비용 모델 그대로.
    """
    from app.services.execution_policy import risk_quantity

    if atr_mult is None and stop_loss_pct is None:
        raise ValueError("위험 % 수량에는 손절 거리(ATR 또는 %)가 필요합니다.")
    if initial_capital <= 0:
        raise ValueError("initial_capital 은 0 보다 커야 합니다.")
    close = df["close"].astype(float).to_numpy()
    open_ = df["open"].astype(float).to_numpy() if "open" in df.columns else close
    h = held.reindex(df.index).fillna(0).astype(float).to_numpy()
    atr = atr_values.reindex(df.index).astype(float).to_numpy() if atr_values is not None else None
    buy_rate, sell_rate = _side_rates(cost, df.index)
    slip = float(getattr(cost, "slippage_bps", 0.0) or 0.0)
    market = getattr(cost, "market", "KOSPI")
    is_etf = bool(getattr(cost, "is_etf", False))

    n = len(close)
    net_eq, gross_eq, cost_frac = np.empty(n), np.empty(n), np.zeros(n)
    cash = gross_cash = float(initial_capital)
    qty = 0
    trades: list[dict] = []
    for i in range(n):
        prev_eq = net_eq[i - 1] if i else float(initial_capital)
        was = h[i - 1] if i else 0.0
        if h[i] == 1 and was == 0:                       # 진입 — 판단은 i-1 종가
            px = open_[i] if entry_mode == "open" else close[i - 1] if i else close[i]
            ref = close[i - 1] if i else close[i]
            dist = atr[i - 1] * atr_mult if atr_mult is not None else ref * stop_loss_pct / 100
            q = risk_quantity(equity=cash, cash=cash, price=ref, stop_price=ref - dist, budget=cash, existing_value=0,
                              position_cap_pct=max_position_pct, risk_pct=risk_pct, slippage_bps=slip,
                              when=df.index[i - 1 if i else i], market=market, is_etf=is_etf)
            qty = min(q["quantity"], int(cash // (px * (1 + buy_rate[i])))) if px > 0 else 0
            paid = qty * px * buy_rate[i]
            cash -= qty * px + paid
            gross_cash -= qty * px
            cost_frac[i] = paid / prev_eq
            trades.append({"entry_date": df.index[i].isoformat(), "quantity": qty, "entry_price": float(px),
                           "decision_price": float(ref), "stop_distance": float(dist),
                           "risk_budget": q["risk_budget"], "estimated_loss": q["estimated_loss"],
                           "weight_pct": round(float(qty * px / prev_eq * 100), 4), "exit_date": None, "pnl": None})
            trades[-1]["_cash_out"] = qty * px + paid
        elif h[i] == 0 and was == 1:                     # 청산 — 보유 전량
            px = open_[i] if exit_mode == "open" else close[i - 1]
            paid = qty * px * sell_rate[i]
            cash += qty * px - paid
            gross_cash += qty * px
            cost_frac[i] = paid / prev_eq
            t = trades[-1]
            t.update(exit_date=df.index[i].isoformat(), exit_price=float(px), pnl=round(float(qty * px - paid - t.pop("_cash_out")), 2))
            qty = 0
        net_eq[i] = cash + qty * close[i]
        gross_eq[i] = gross_cash + qty * close[i]
    if trades and trades[-1]["exit_date"] is None:   # 끝날까지 들고 있던 거래 — 마지막 종가로 평가(매도 비용 없음)
        t = trades[-1]
        t["pnl"] = round(float(qty * close[-1] - t.pop("_cash_out")), 2)

    idx = df.index
    net_eq_s, gross_eq_s = pd.Series(net_eq, index=idx), pd.Series(gross_eq, index=idx)
    return {
        "net_ret": net_eq_s.pct_change().fillna(net_eq_s.iloc[0] / initial_capital - 1),
        "gross_ret": gross_eq_s.pct_change().fillna(gross_eq_s.iloc[0] / initial_capital - 1),
        "cost": pd.Series(cost_frac, index=idx),
        "equity": net_eq_s,
        "trades": trades,
    }


def backtest(df: pd.DataFrame, signals: pd.Series, commission_bps: float = 0.0, slippage_bps: float = 0.0,
             stop_loss_pct: float | None = None, take_profit_pct: float | None = None,
             cost: Any | None = None,
             entry_mode: str = "close",
             exit_mode: str = "close",
             atr_period: int | None = None,
             atr_mult: float | None = None,
             take_rr: float | None = None,
             risk_pct: float | None = None,
             initial_capital: float = 10_000_000.0,
             max_position_pct: float = 30.0) -> dict:
    """
    벡터화 백테스트: 롱 전략 (signal=+1 보유, 그 외 현금).

    cost: 매매비용 모델 (`app.services.trading_cost`). 주면 이것을 쓴다 — 슬리피지도 모델이 담으므로
          아래 commission_bps · slippage_bps 는 쓰지 않는다. 비용을 넣으면 전략과 매수후보유
          **양쪽**에서 뗀다 (같은 잣대로 비교).
    commission_bps / slippage_bps : cost 를 안 넘겼을 때만 — 포지션이 바뀔 때(진입·청산) 회전금액에
          비례해 차감 (1bp = 0.01% · 강사님 원본 동작 = `trading_cost.FlatCostModel`). 둘 다 0 이면
          비용을 떼지 않는다 — 그 경우 응답의 `cost.model` 이 "none" 으로 나가므로 무비용임을 숨길 수 없다.
    stop_loss_pct / take_profit_pct : 진입가 대비 손절·익절 규칙 (apply_stops · 강사님 원본)
    인자 순서: 강사님 원본의 위치 인자 호출(`formula.py`)이 그대로 돌도록 cost 를 맨 뒤 키워드로 둔다.

    Returns: 수익률, 샤프지수, MDD, 승률, 누적수익 시계열, 비용 내역

    entry_mode / exit_mode : 체결 시점 — "close"(그날 종가 · 기본) | "open"(다음 봉 시가 · TradingView 기본)
    - "close": 신호가 난 날 그 종가에 체결 (지금 동작 · 1차 Alpha_Stack 은 "종가 매수 가정"을 금지)
    - "open" : 신호가 난 다음 봉 시가에 체결

    risk_pct : 주면 전략 카드 판 2 의 위험 % 수량(`size_positions`) — 시작 자금 `initial_capital`(자동매매 가상계좌와
          같은 1,000만 원) · 종목 비중 상한 `max_position_pct` 로 주 수를 내고 평가액으로 수익을 잰다. 손절 거리
          (`atr_mult` 또는 `stop_loss_pct`)가 있어야 한다. 안 주면(None) 지금처럼 보유일에 전액이 들어간다.
    """

    if entry_mode not in ("close", "open"):
        raise ValueError(f"entry_mode 는 close | open 만: {entry_mode}")
    if exit_mode not in ("close", "open"):
        raise ValueError(f"exit_mode 는 close | open 만: {exit_mode}")

    ret = df["close"].pct_change().fillna(0)
    # 전날 시그널로 오늘 포지션 (룩어헤드 방지)
    pos = signals.shift(1).fillna(0).reindex(ret.index, fill_value=0)

    held = (pos == 1).astype(float)
    # 손절 · 익절이 보유 상태를 먼저 바꾼다 — 비용 · 승률 · 매매 횟수는 바뀐 보유 상태로 센다
    atr_values = None
    if atr_period is not None and atr_mult is not None:
        if not {"high", "low", "close"}.issubset(df.columns):
            raise ValueError("ATR 손절에는 high, low, close 컬럼이 필요합니다.")
        atr_values = ta.atr(
            df["high"].astype(float), df["low"].astype(float),
            df["close"].astype(float), atr_period,
        )
    held, _exits = apply_stops(
        df["close"].astype(float), held, stop_loss_pct, take_profit_pct,
        return_exits=True, atr_values=atr_values, atr_mult=atr_mult,
        take_rr=take_rr, entry_mode=entry_mode,
        open_=df["open"].astype(float) if "open" in df.columns else None,
    )
    n_sl = sum(1 for e in _exits if e["type"] == "stop")
    n_tp = sum(1 for e in _exits if e["type"] == "take")
    if cost is None and (commission_bps or slippage_bps):
        cost = tcost.FlatCostModel(cost_bps=commission_bps, slippage_bps=slippage_bps)

    sized = None
    if risk_pct is not None:
        sized = size_positions(df, held, risk_pct=risk_pct, initial_capital=initial_capital,
                               max_position_pct=max_position_pct, cost=cost, entry_mode=entry_mode,
                               exit_mode=exit_mode, atr_values=atr_values, atr_mult=atr_mult,
                               stop_loss_pct=stop_loss_pct)
        gross_ret = sized["gross_ret"]
    # ── 체결 시점 반영 (entry_mode · exit_mode) ──────────────────
    elif entry_mode == "close" and exit_mode == "close":
        gross_ret = ret * held
    else:
        close = df["close"].astype(float)
        open_ = df["open"].astype(float)
        day_ret = (close / open_ - 1)                      # 시가 → 종가
        gap_ret = (open_ / close.shift(1) - 1)             # 전일 종가 → 시가

        entry_days = (held == 1) & (held.shift(1, fill_value=0) == 0)   # 0→1 진입일
        normal_held = (held == 1) & ~entry_days                         # 보유 중 (진입일 제외)
        exit_days = (held == 0) & (held.shift(1, fill_value=0) == 1)    # 1→0 청산일

        gross_ret = pd.Series(0.0, index=ret.index)
        # 진입일
        if entry_mode == "open":
            gross_ret[entry_days] = day_ret[entry_days]
        else:
            gross_ret[entry_days] = ret[entry_days]
        # 보통 보유일
        gross_ret[normal_held] = ret[normal_held]
        # 청산일
        if exit_mode == "open":
            gross_ret[exit_days] = gap_ret[exit_days]
        # exit_mode == "close" 면 청산일은 0    
    strat_ret = gross_ret

    bh_ret    = ret
    cost_series = pd.Series(0.0, index=ret.index)

    if sized is not None:
        # 수량을 넣으면 비용은 평가액에서 이미 뗐다 — 하루 비용은 전날 평가액에 대한 비율
        strat_ret = sized["net_ret"]
        cost_series = sized["cost"]
        if cost is not None:
            bh_ret = bh_ret - cost.buy_hold_cost(ret.index)
    elif cost is not None:
        # 전략: 포지션이 바뀌는 날에만 방향별(매수/매도) 비용을 뗀다.
        cost_series = cost.turnover_cost(held)
        strat_ret = strat_ret - cost_series
        # 매수후보유: 첫날 매수 1회 + 마지막날 매도 1회.
        bh_ret    = bh_ret - cost.buy_hold_cost(ret.index)

    cum_strat = (1 + strat_ret).cumprod()
    cum_bh    = (1 + bh_ret).cumprod()
    cum_gross = (1 + gross_ret).cumprod()

    total_strat = float(cum_strat.iloc[-1] - 1) * 100
    total_bh    = float(cum_bh.iloc[-1] - 1)    * 100
    total_gross = float(cum_gross.iloc[-1] - 1) * 100

    sharpe = ta.sharpe_ratio(strat_ret)
    mdd    = ta.max_drawdown(cum_strat) * 100

    # 승률 (보유 구간만) — 비용을 뗀 뒤의 수익률로 센다 · 손절 · 익절 뒤의 보유 상태 기준
    held_rets = strat_ret[held == 1]
    win_rate  = float((held_rets > 0).sum() / max(len(held_rets), 1)) * 100
    cost_desc = tcost.describe(cost)

    # ── B2 성과 지표 (계획 vs 실제 손절, 손익비, 기대값) ────────────
    def _avg(vals):
        return round(float(np.mean(vals)), 4) if vals else None

    stop_exits = [e for e in _exits if e["type"] == "stop"]
    take_exits = [e for e in _exits if e["type"] == "take"]
    stop_avg_planned = _avg([e["planned_pct"] for e in stop_exits])
    stop_avg_actual = _avg([e["actual_pct"] for e in stop_exits])
    take_avg_actual = _avg([e["actual_pct"] for e in take_exits])
    # 갭으로 손절가를 건너뛴 횟수 — 실제가 계획보다 더 나쁨 (예: 계획 -2%, 실제 -3%)
    stop_gap_count = sum(1 for e in stop_exits if e["actual_pct"] < e["planned_pct"] - 1e-9)
    # 실현 손익비 = 평균 익절 / |평균 손절|
    if stop_avg_actual and take_avg_actual and stop_avg_actual < 0:
        realized_rr = round(take_avg_actual / abs(stop_avg_actual), 4)
    else:
        realized_rr = None
    # 기대값 = 승률 × 손익비 − (1 − 승률), 손실 1단위 기준
    if realized_rr is not None:
        p = win_rate / 100.0
        expectancy = round(p * realized_rr - (1 - p), 4)
    else:
        expectancy = None

    # 매매 횟수 — 비용을 세는 기준(held)과 같게 맞춘다.
    # 예전에는 pos 를 썼는데, signals 가 -1 을 내는 전략에서는 0→-1 처럼
    # 실제 매매가 없는 변화까지 세어 비용 차감 횟수와 어긋났다.
    trade_count = int((held.diff().abs().fillna(held.abs()) > 0).sum())

    # 최근 252 거래일 시계열
    idx = df.index[-252:]
    times      = [t.isoformat() for t in idx]
    cum_series = [round(float(v) * 100 - 100, 2) for v in cum_strat.reindex(idx).values]
    bh_series  = [round(float(v) * 100 - 100, 2) for v in cum_bh.reindex(idx).values]

    out = {
        "total_return_pct":     round(total_strat, 2),
        "cost_pct":             round(float(cost_series.sum()) * 100, 3),  # 비용 합(단순 합 · 복리 `cost_drag_pct` 와 다르다)
        "commission_bps":       float(commission_bps),          # 넘긴 값 (비용 모델을 넘긴 호출은 쓰지 않는다)
        "slippage_bps":         float(cost_desc.get("slippage_bps", 0.0)),  # 실제로 뗀 슬리피지
        "stop_loss_pct":        stop_loss_pct,
        "take_profit_pct":      take_profit_pct,
        "stop_loss_exits":      n_sl,
        "take_profit_exits":    n_tp,
        "buy_hold_return_pct":  round(total_bh, 2),
        "sharpe_ratio":         round(sharpe, 3),
        "mdd_pct":              round(mdd, 2),
        "trade_count":          trade_count,
        "win_rate_pct":         round(win_rate, 2),
        "times":                times,
        "cum_returns":          cum_series,
        "bh_returns":           bh_series,
        # 비용을 떼기 전 수익률과 그 차이를 함께 돌려준다 — 비용이 얼마나 깎았는지
        # 응답만 보고 알 수 있어야, 화면이 "반영했다"고만 적고 넘어가지 못한다.
        "gross_return_pct":     round(total_gross, 2),          # 비용 차감 전
        "cost_drag_pct":        round(total_gross - total_strat, 2),
        "cost":                 cost_desc,
        "stop_avg_planned_pct": stop_avg_planned,
        "stop_avg_actual_pct":  stop_avg_actual,
        "stop_gap_count":       stop_gap_count,
        "take_avg_actual_pct":  take_avg_actual,
        "realized_rr":          realized_rr,
        "expectancy":           expectancy,
        "entry_mode":           entry_mode,
        "exit_mode":            exit_mode,
        "judge":                STOP_JUDGE,
    }
    if sized is not None:
        out["sizing"] = {
            "size_kind": "risk_pct", "risk_pct": float(risk_pct), "max_position_pct": float(max_position_pct),
            "initial_capital": float(initial_capital), "final_equity": round(float(sized["equity"].iloc[-1]), 2),
            "trades": sized["trades"],
        }
    return out


# ── 7. Alpaca API (Paper Trading Mockup) ─────────────────────────────

async def alpaca_execute(
    symbol: str,
    signal: int,
    quantity: int = 1,
    api_key: str = "",
    secret_key: str = "",
) -> dict:
    """Alpaca Markets Paper Trading 주문 실행.

    실제 연동: ALPACA_API_KEY + ALPACA_SECRET_KEY 환경변수 필요.
    현재는 Mockup (구조만 실제 API 스펙 준수).
    """
    action_map = {1: "buy", -1: "sell", 0: "hold"}
    action = action_map.get(signal, "hold")

    if action == "hold":
        return {"symbol": symbol, "action": "hold", "status": "skipped"}

    # 실제 Alpaca REST 요청 구조 (paper-api.alpaca.markets)
    order_payload = {
        "symbol":        symbol,
        "qty":           str(quantity),
        "side":          action,
        "type":          "market",
        "time_in_force": "day",
    }

    if api_key and secret_key:
        import httpx
        url = "https://paper-api.alpaca.markets/v2/orders"
        headers = {
            "APCA-API-KEY-ID":     api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Content-Type":        "application/json",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(url, json=order_payload, headers=headers)
                resp.raise_for_status()
                return {"symbol": symbol, "action": action, "status": "submitted", "response": resp.json()}
            except Exception as e:
                return {"symbol": symbol, "action": action, "status": "error", "error": str(e)}

    # Mockup 응답 (API 키 없을 때)
    return {
        "symbol":   symbol,
        "action":   action,
        "qty":      quantity,
        "type":     "market",
        "status":   "mockup_submitted",
        "order_id": f"mock-{symbol}-{action}",
        "note":     "실제 실행: ALPACA_API_KEY / ALPACA_SECRET_KEY 환경변수 설정",
    }


# ── 8. 전체 파이프라인 진입점 ─────────────────────────────────────────

async def run_pipeline(
    symbol: str,
    candles: list[dict],
    model_type: str = "lgb",
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    cost: Any | None = None,
) -> dict:
    """
    OHLCV → 전처리 → 피처 → ML/DL 학습 → 시그널 → 백테스트 순서로 실행.

    model_type: 'lgb' | 'mlp' | 'rule'
    cost: 매매비용 모델. ML 이 낸 시그널도 매매이므로 같은 비용을 뗀다.
    """
    if len(candles) < 80:
        return {"symbol": symbol, "error": f"데이터 부족: {len(candles)}개 (최소 80개 필요)"}

    # 1) 전처리
    df = preprocess(candles)

    # 2) 피처 엔지니어링
    df = feature_engineer(df)

    if len(df) < 60:
        return {"symbol": symbol, "error": f"피처 계산 후 데이터 부족: {len(df)}행"}

    # 3) 모델 학습 + 예측
    metrics: dict = {}
    explanation: dict | None = None
    if model_type == "lgb" and HAS_LGB:
        model, metrics = train_lgb(df)
        signals = predict_lgb(model, df)
        used_model = "LightGBM"
        try:
            from app.services.xai import explain_signal
            x_last = df[FEATURE_COLS].iloc[-1]
            probs = model.predict(x_last.values.reshape(1, -1))[0]
            explanation = explain_signal(model, x_last.values, FEATURE_COLS, x_last.to_dict(), probs)
        except Exception:
            explanation = None
    elif model_type == "mlp" and HAS_SKLEARN:
        model, scaler, metrics = train_mlp(df)
        signals = predict_mlp(model, scaler, df)
        used_model = "MLP Neural Net"
    else:
        signals = rule_based_signals(df)
        used_model = "Rule-Based (RSI+MACD+BB)"
        metrics = {"note": "ML 라이브러리 미설치 — 규칙 기반 대체"}

    # 4) 백테스트 (비용 모델 또는 수수료·슬리피지 · 손절·익절 반영)
    bt = backtest(df, signals, commission_bps, slippage_bps, stop_loss_pct, take_profit_pct, cost=cost)

    # 5) 최신 시그널 + Alpaca 주문 (mockup)
    latest_signal  = int(signals.iloc[-1])
    alpaca_result  = await alpaca_execute(symbol, latest_signal)

    # 6) 최근 50 시그널 요약
    recent = signals.iloc[-50:]
    signal_counts = {
        "buy":  int((recent == 1).sum()),
        "hold": int((recent == 0).sum()),
        "sell": int((recent == -1).sum()),
    }

    return {
        "symbol":         symbol,
        "model":          used_model,
        "model_metrics":  metrics,
        "latest_signal":  latest_signal,
        "signal_label":   {1: "매수", 0: "관망", -1: "매도"}.get(latest_signal, "불명"),
        "signal_counts":  signal_counts,
        "backtest":       bt,
        "alpaca":         alpaca_result,
        "data_rows":      len(df),
        "explanation":    explanation,   # XAI (LightGBM일 때 SHAP 기여도)
    }


def backtest_custom_indicator(
    candles: list[dict],
    base: str = "rsi_ma",
    short_window: int = 5,
    mid_window: int = 20,
    rsi_period: int = 14,
    buy_threshold: float = 35.0,
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    cost: Any | None = None,
    entry_mode: str = "close",
    exit_mode: str = "close",
) -> dict:
    """사용자 지정 인디케이터 전략 백테스트 (수수료·슬리피지·손절·익절 반영 가능).

    base: rsi_ma | macd_bb | volume_rsi | triple_ma
    cost: 매매비용 모델. 예전에는 이 경로에 비용을 넣을 방법이 아예 없어서,
          같은 API 를 쓰는 두 화면이 서로 다른 비용 가정으로 답하고 있었다.
    """
    if len(candles) < 80:
        return {"error": f"데이터 부족: {len(candles)}개 (최소 80개 필요)"}

    short_window = max(2, int(short_window))
    mid_window = max(short_window + 1, int(mid_window))
    rsi_period = max(5, int(rsi_period))
    buy_threshold = float(max(5, min(50, buy_threshold)))
    sell_threshold = float(100 - buy_threshold)

    df = preprocess(candles)
    close = df["close"].astype(float)

    ma_short = ta.sma(close, short_window)
    ma_mid = ta.sma(close, mid_window)
    rsi = ta.rsi(close, rsi_period)

    golden_cross = (ma_short > ma_mid) & (ma_short.shift(1) <= ma_mid.shift(1))
    dead_cross = (ma_short < ma_mid) & (ma_short.shift(1) >= ma_mid.shift(1))
    base = base if base in ("rsi_ma", "macd_bb", "volume_rsi", "triple_ma") else "rsi_ma"
    if base == "macd_bb":
        macd_line, macd_signal, _ = ta.macd(close, 12, 26, 9)
        bb_upper, bb_mid, _bb_lower = ta.bollinger(close, mid_window, 2.0)
        buy_cond = (macd_line > macd_signal) & (macd_line.shift(1) <= macd_signal.shift(1)) & (close < bb_mid)
        sell_cond = (macd_line < macd_signal) & (macd_line.shift(1) >= macd_signal.shift(1)) | (close > bb_upper)
    elif base == "volume_rsi":
        volume_ma = df["volume"].astype(float).rolling(mid_window).mean()
        buy_cond = (rsi < buy_threshold) & (df["volume"] > volume_ma)
        sell_cond = rsi > sell_threshold
    elif base == "triple_ma":
        long_ma = close.rolling(max(mid_window * 2, mid_window + 1)).mean()
        buy_cond = golden_cross & (ma_mid > long_ma)
        sell_cond = dead_cross | (ma_mid < long_ma)
    else:
        buy_cond = golden_cross & (rsi < buy_threshold)
        sell_cond = dead_cross | (rsi > sell_threshold)

    regime = pd.Series(np.nan, index=df.index)
    regime.loc[buy_cond] = 1.0
    regime.loc[sell_cond] = 0.0
    position = regime.ffill().fillna(0.0).rename("ml_signal")

    bt = backtest(df, position, commission_bps, slippage_bps, stop_loss_pct, take_profit_pct, cost=cost,
                  entry_mode=entry_mode, exit_mode=exit_mode)
    return {
        "costs": {k: bt[k] for k in ("gross_return_pct", "cost_pct", "commission_bps", "slippage_bps",
                                     "stop_loss_pct", "take_profit_pct", "stop_loss_exits", "take_profit_exits",
                                     "entry_mode", "exit_mode", "judge")},
        "strategy": {
            "name": f"custom_{base}",
            "base": base,
            "short_window": short_window,
            "mid_window": mid_window,
            "rsi_period": rsi_period,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
        },
        "return_total": round(bt["total_return_pct"] / 100.0, 4),
        "return_buy_hold": round(bt["buy_hold_return_pct"] / 100.0, 4),
        "sharpe": bt["sharpe_ratio"],
        "mdd": round(bt["mdd_pct"] / 100.0, 4),
        "trade_count": bt["trade_count"],
        "win_rate_pct": bt["win_rate_pct"],
        "times": bt["times"],
        "cum_returns": bt["cum_returns"],
        "bh_returns": bt["bh_returns"],
        "return_gross": round(bt["gross_return_pct"] / 100.0, 4),
        "cost_drag_pct": bt["cost_drag_pct"],
        "cost": bt["cost"],
    }
