"""지표 LEAN 대조 — 같은 일봉에서 우리 지표(`ta_utils`)와 QuantConnect LEAN 지표가 날짜마다 같은가.

3차 인디케이터 전략 설계서 4.1 의 근거를 만든다. 기준은 RTM `P02-①-1` 의 인수 기준
「같은 OHLCV 에서 우리 지표 값과 LEAN 지표 값이 정한 오차 안에서 같다」다. 「정한 오차」 는
설계서 8절 ③ 에서 정하는 중이라, 이 스크립트는 합격 · 불합격을 판정하지 않고 차이만 보인다.

무엇을 재나
-----------
같은 종목 · 같은 일봉(수집 DB · 앱의 일봉 다리 `collector_db` 와 같은 값)을
  (가) 우리 쪽 `ta_utils` 로 계산하고
  (나) LEAN 도커에 사용자 정의 일봉(시가 · 고가 · 저가 · 종가 · 거래량)으로 넣어 LEAN 지표로 계산해
날짜별로 맞댄다 — 값이 처음 나오는 날 · 한쪽에만 값이 있는 날 수 · 최대 절대 차 · 최대 상대 차.
DMI 는 고가 상승폭과 저가 하락폭이 같은 날(동률)의 규칙이 다르다 — TradingView 식은 둘 다 0, LEAN 은 +DM 에 넣는다.
우리 정의는 TradingView 쪽이라(설계서 4.1) 그런 날 수를 함께 보인다.

  RSI 14        ta_utils.rsi        ↔ RelativeStrengthIndex(14, WILDERS)
  ATR 14        ta_utils.atr        ↔ AverageTrueRange(14, WILDERS)
  볼린저 20 · 2  ta_utils.bollinger  ↔ BollingerBands(20, 2, SIMPLE) 가운데 · 위 · 아래
  DMI 14 · 14   ta_utils.dmi        ↔ AverageDirectionalIndex(14) +DI · −DI · ADX
  SMA 20        ta_utils.sma        ↔ SimpleMovingAverage(20)
  EMA 20        ta_utils.ema        ↔ ExponentialMovingAverage(20)
  MACD 12 · 26 · 9  ta_utils.macd   ↔ MovingAverageConvergenceDivergence(12, 26, 9, EXPONENTIAL) 선 · 시그널 · 히스토그램

LEAN 은 주문을 내지 않는 알고리즘을 돌려 날짜마다 지표 한 줄을 로그에 남기고, 그 줄만 읽는다.
이미지는 강민석 님이 #314 에 적은 판(digest)을 기본값으로 쓴다 — 판이 다르면 값이 달라질 수 있어서다.

봉인 구간(모의투자 검증용 · 가장 이른 시작 가능일 2026-09-01)은 읽지 않으므로 기본 기준일은 2026-08-31 이다.
일봉 · LEAN 입력 · 결과는 저장소 밖 자리(`data/local-run/indicator-lean/` · git 무시)에만 쓴다.

    python scripts/indicator_lean_scan.py
    python scripts/indicator_lean_scan.py --symbol 000660.KS --json data/local-run/indicator-lean/result.json

Docker 가 필요하다. WSL 에서 Windows 의 `docker.exe` 만 있으면 그것을 쓰고, 붙이는 경로는 `wslpath -w` 로 바꾼다.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import collector_db, ta_utils  # noqa: E402

LEAN_IMAGE = "quantconnect/lean@sha256:aa3e0248d8d20f891e9337e395045a1317e2612986413136bfd8e2fc25c709e6"
REFERENCE_DATA = ROOT / "app" / "services" / "lean_reference_data"
WORKDIR = ROOT / "data" / "local-run" / "indicator-lean"
ALGORITHM = "IndicatorDumpAlgorithm"

# 칸 이름 → (우리 쪽 계산, LEAN 쪽 지표 값 식). LEAN 식은 알고리즘 안에서 `self.ind` 사전을 읽는다.
INDICATORS: dict[str, tuple] = {
    "rsi14": (lambda d: ta_utils.rsi(d["close"], 14), "rsi"),
    "atr14": (lambda d: ta_utils.atr(d["high"], d["low"], d["close"], 14), "atr"),
    "bb_mid": (lambda d: ta_utils.bollinger(d["close"], 20, 2.0)[1], "bb.middle_band"),
    "bb_upper": (lambda d: ta_utils.bollinger(d["close"], 20, 2.0)[0], "bb.upper_band"),
    "bb_lower": (lambda d: ta_utils.bollinger(d["close"], 20, 2.0)[2], "bb.lower_band"),
    "plus_di14": (lambda d: ta_utils.dmi(d["high"], d["low"], d["close"], 14, 14)[0], "adx.positive_directional_index"),
    "minus_di14": (lambda d: ta_utils.dmi(d["high"], d["low"], d["close"], 14, 14)[1], "adx.negative_directional_index"),
    "adx14": (lambda d: ta_utils.dmi(d["high"], d["low"], d["close"], 14, 14)[2], "adx"),
    "sma20": (lambda d: ta_utils.sma(d["close"], 20), "sma"),
    "ema20": (lambda d: ta_utils.ema(d["close"], 20), "ema"),
    "macd": (lambda d: ta_utils.macd(d["close"], 12, 26, 9)[0], "macd"),
    "macd_signal": (lambda d: ta_utils.macd(d["close"], 12, 26, 9)[1], "macd.signal"),
    "macd_hist": (lambda d: ta_utils.macd(d["close"], 12, 26, 9)[2], "macd.histogram"),
}

LEAN_SETUP = """\
        self.ind = {
            "rsi": RelativeStrengthIndex(14, MovingAverageType.WILDERS),
            "atr": AverageTrueRange(14, MovingAverageType.WILDERS),
            "bb": BollingerBands(20, 2, MovingAverageType.SIMPLE),
            "adx": AverageDirectionalIndex(14),
            "sma": SimpleMovingAverage(20),
            "ema": ExponentialMovingAverage(20),
            "macd": MovingAverageConvergenceDivergence(12, 26, 9, MovingAverageType.EXPONENTIAL),
        }
"""


def load(symbol: str, period: str, as_of: date) -> pd.DataFrame:
    data = collector_db.read_daily_candles(symbol, period, today=as_of)
    if not data:
        raise SystemExit(f"수집 DB 에서 {symbol} 일봉을 읽지 못했다 — 기호는 「6자리.KS|KQ」 · scripts/hf_dataset.py restore 로 수집 DB 를 되살린 뒤 돌린다")
    df = pd.DataFrame(data["candles"])
    df["date"] = pd.to_datetime(df["time"].astype("int64"), unit="s").dt.strftime("%Y-%m-%d")
    for k in ("open", "high", "low", "close", "volume"):
        df[k] = df[k].astype(float)
    return df.reset_index(drop=True)


def algorithm_source(start: str, end: str) -> str:
    cols = ",".join(INDICATORS)
    exprs = ", ".join(f'_v(self.ind["{e.split(".")[0]}"]{"." + e.split(".", 1)[1] if "." in e else ""})'
                      for _, e in INDICATORS.values())
    y0, m0, d0 = (int(x) for x in start.split("-"))
    y1, m1, d1 = (int(x) for x in end.split("-"))
    return f'''from AlgorithmImports import *
from QuantConnect.Python import PythonData
from QuantConnect import Globals, SubscriptionTransportMedium
from QuantConnect.Data import SubscriptionDataSource
import os
from datetime import datetime, timedelta


class OhlcvBar(PythonData):
    def get_source(self, config, date, is_live):
        return SubscriptionDataSource(os.path.join(Globals.DataFolder, "prices.csv"), SubscriptionTransportMedium.LocalFile)

    def reader(self, config, line, date, is_live):
        if not line or line.startswith("date"):
            return None
        d, o, h, l, c, v = line.split(",")
        bar = OhlcvBar()
        bar.symbol = config.symbol
        bar.time = datetime.strptime(d, "%Y-%m-%d")
        bar.end_time = bar.time + timedelta(days=1)
        bar.value = float(c)
        bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"] = float(o), float(h), float(l), float(c), float(v)
        return bar


def _v(ind):
    return f"{{ind.current.value:.12f}}" if ind.is_ready else ""


class {ALGORITHM}(QCAlgorithm):
    def initialize(self):
        self.set_start_date({y0}, {m0}, {d0})
        self.set_end_date({y1}, {m1}, {d1})
        self.set_cash(100000000)
        self.sym = self.add_data(OhlcvBar, "BAR", Resolution.DAILY).symbol
{LEAN_SETUP}        self.log("IND,date,{cols}")

    def on_data(self, data):
        if not data.contains_key(self.sym):
            return
        b = data[self.sym]
        o, h, l, c, v = (float(b[k]) for k in ("open", "high", "low", "close", "volume"))
        bar = TradeBar(b.time, self.sym, o, h, l, c, v, timedelta(days=1))
        for ind in self.ind.values():
            ind.update(bar) if isinstance(ind, BarIndicator) else ind.update(b.time, c)
        self.log(",".join(["IND", b.time.strftime("%Y-%m-%d"), {exprs}]))
'''


def _docker() -> tuple[str, bool]:
    exe = shutil.which("docker") or shutil.which("docker.exe")
    if not exe:
        raise SystemExit("docker 를 찾지 못했다 — Docker Desktop 을 켜고 다시 돌린다")
    return exe, exe.endswith(".exe") and sys.platform.startswith("linux")


def run_lean(df: pd.DataFrame, image: str, timeout: int) -> pd.DataFrame:
    shutil.rmtree(WORKDIR, ignore_errors=True)
    (WORKDIR / "results").mkdir(parents=True, exist_ok=True)
    shutil.copytree(REFERENCE_DATA, WORKDIR / "data", dirs_exist_ok=True)
    df[["date", "open", "high", "low", "close", "volume"]].to_csv(WORKDIR / "data" / "prices.csv", index=False)
    (WORKDIR / "main.py").write_text(algorithm_source(df["date"].iloc[0], df["date"].iloc[-1]), encoding="utf-8")

    exe, wsl_to_windows = _docker()
    mount = subprocess.run(["wslpath", "-w", str(WORKDIR)], text=True, capture_output=True, check=True).stdout.strip() \
        if wsl_to_windows else str(WORKDIR)
    cmd = [exe, "run", "--rm", "-e", "PYTHONDONTWRITEBYTECODE=1", "-v", f"{mount}:/workspace", image,
           "--environment", "backtesting", "--algorithm-language", "Python",
           "--algorithm-type-name", ALGORITHM, "--algorithm-location", "/workspace/main.py",
           "--data-folder", "/workspace/data", "--results-destination-folder", "/workspace/results",
           "--backtest-name", "indicators"]
    out = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, encoding="utf-8", errors="replace")
    (WORKDIR / "lean-stdout.txt").write_text(out.stdout + "\n" + out.stderr, encoding="utf-8")
    log = WORKDIR / "results" / f"{ALGORITHM}-log.txt"
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else out.stdout
    rows = [ln.split("IND,", 1)[1].strip() for ln in text.splitlines() if "IND," in ln]
    if out.returncode != 0 or len(rows) < 2:
        raise SystemExit(f"LEAN 실행이 지표 줄을 남기지 못했다(종료 코드 {out.returncode}) — {WORKDIR / 'lean-stdout.txt'} 를 본다")
    header, *body = (r.split(",") for r in rows)
    lean = pd.DataFrame(body, columns=header)
    for k in INDICATORS:
        lean[k] = pd.to_numeric(lean[k], errors="coerce")
    return lean


def compare(df: pd.DataFrame, lean: pd.DataFrame) -> dict:
    ours = pd.DataFrame({"date": df["date"], **{k: f(df) for k, (f, _) in INDICATORS.items()}})
    m = ours.merge(lean, on="date", how="outer", suffixes=("_ours", "_lean"))
    res = {}
    for k in INDICATORS:
        a, b = m[f"{k}_ours"], m[f"{k}_lean"]
        both = a.notna() & b.notna()
        diff = (a[both] - b[both]).abs()
        res[k] = {
            "first_ours": m.loc[a.notna(), "date"].min(),
            "first_lean": m.loc[b.notna(), "date"].min(),
            "both": int(both.sum()),
            "one_side_only": int((a.notna() ^ b.notna()).sum()),
            "max_abs": float(diff.max()) if len(diff) else None,
            "max_rel": float((diff / b[both].abs()).max()) if len(diff) else None,
        }
    return res


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--symbol", default="005930.KS", help="6자리.KS|KQ (기본: 삼성전자)")
    p.add_argument("--period", default="2y", help="기준일에서 거슬러 올라갈 기간 (collector_db 의 기간 이름)")
    p.add_argument("--as-of", default="2026-08-31", help="기준일 YYYY-MM-DD (기본: 봉인 구간의 가장 이른 시작 가능일 전날)")
    p.add_argument("--image", default=os.environ.get("LEAN_INDICATOR_IMAGE", LEAN_IMAGE))
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--json", help="결과를 JSON 으로도 쓴다")
    a = p.parse_args(argv)

    df = load(a.symbol, a.period, date.fromisoformat(a.as_of))
    lean = run_lean(df, a.image, a.timeout)
    res = compare(df, lean)
    meta = {"symbol": a.symbol, "from": df["date"].iloc[0], "to": df["date"].iloc[-1], "bars": len(df),
            "definition": ta_utils.DEFINITION, "image": a.image}

    print(f"{meta['symbol']} · {meta['from']} ~ {meta['to']} · {meta['bars']}봉 · 지표 정의 {meta['definition']}\n")
    print("| 지표 | 처음 값 (우리 · LEAN) | 함께 값이 있는 날 | 한쪽만 값 | 최대 절대 차 | 최대 상대 차 |")
    print("|---|---|--:|--:|--:|--:|")
    for k, v in res.items():
        print(f"| {k} | {v['first_ours']} · {v['first_lean']} | {v['both']} | {v['one_side_only']} | "
              f"{v['max_abs']:.3e} | {v['max_rel']:.3e} |")
    up, down = df["high"].diff(), -df["low"].diff()
    ties = df.loc[(up == down) & (up > 0), "date"].tolist()
    print(f"\nDMI 참고 — 고가 상승폭 = 저가 하락폭 > 0 인 날 {len(ties)}일{(' (' + ' · '.join(ties) + ')') if ties else ''}: "
          "TradingView 식은 +DM · −DM 둘 다 0, LEAN 은 +DM 에 넣어 그날부터 +DI · ADX 가 갈렸다가 평활로 다시 가까워진다")
    meta["dmi_tie_days"] = ties
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps({"meta": meta, "result": res}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
