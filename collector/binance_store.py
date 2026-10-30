"""코인 봉 저장 — 월별 정제 파일(raw/) → 연 · 종목 단위 적재 파일(ohlcv/) (할 일 ①-13 · 2026-10-30 · 받기 → 정제 → 적재 분리의 「적재」 몫).

네트워크 없음. `binance_vision.to_v2_rows` 가 만든 `ohlcv-v2` 줄(+코인 확장 칸)을 parquet 으로 쓰고 합친다.

레이아웃(루트 아래)
  raw/<주기>/<종목>/<YYYY-MM>.parquet        — 달마다 정제한 줄(다시 받아도 덮어쓰기 — 멱등)
  ohlcv/timeframe=<주기>/market=BINANCE_SPOT_USDT/[year=<해>/]symbol=<종목>.parquet
                                              — 적재 파일: 잘게(1 ~ 30분)는 해 폴더 · 거친 주기(1시간 이상)는 종목당 하나(`binance_vision.partition_path`)
적재는 달 파일들을 읽어 합치고 키(`markets.KEY`) 중복을 검사한 뒤 통째로 다시 쓴다 — 달을 더 받으면 적재만 다시 돌리면 된다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector import binance_vision, crypto_v2, markets

COLUMNS: List[str] = list(markets.COLUMNS) + list(crypto_v2.EXT_COLUMNS)


def month_path(root: Path, interval: str, symbol: str, year: int, month: int) -> Path:
    if interval not in binance_vision.INTERVALS:
        raise ValueError(f"받지 않는 주기: {interval!r}")
    return Path(root) / "raw" / interval / symbol / f"{year:04d}-{month:02d}.parquet"


def _frame(rows: List[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"v2 줄에 칸이 없다: {missing}")
    return df[COLUMNS]


def write_month(root: Path, interval: str, symbol: str, year: int, month: int, rows: List[dict]) -> Path:
    """한 달치 v2 줄을 월별 정제 파일로(덮어쓰기). 줄이 없으면 `ValueError`."""
    if not rows:
        raise ValueError(f"{symbol} {interval} {year}-{month:02d}: 쓸 줄이 없다")
    p = month_path(root, interval, symbol, year, month)
    p.parent.mkdir(parents=True, exist_ok=True)
    _frame(rows).to_parquet(p, compression="zstd", index=False)
    return p


def compile_partition(root: Path, out_root: Path, interval: str, symbol: str, year: Optional[int] = None) -> Optional[dict]:
    """월별 파일을 합쳐 적재 파일 하나로. 거친 주기는 `year` 를 무시하고 모든 달을 합친다. 달 파일이 없으면 None.
    키 중복이 있으면 숨기지 않고 `ValueError`(같은 달을 두 번 받아도 달 파일은 덮어써서 중복이 안 생긴다 — 중복은 서로 다른 달이 겹칠 때뿐)."""
    d = Path(root) / "raw" / interval / symbol
    files = sorted(d.glob("*.parquet")) if d.exists() else []
    if interval not in binance_vision.COARSE:
        if year is None:
            raise ValueError("잘게 쪼갠 주기는 해(`year`)가 필요하다")
        files = [f for f in files if f.stem.startswith(f"{year:04d}-")]
    if not files:
        return None
    frames, dropped = [], 0
    for f in files:
        part = pd.read_parquet(f)
        # 원천 CSV 가 같은 달 안에서 한 줄을 두 번 싣는 경우(AVAXUSDT 4h 2026-05 · 2026-10-30)가 있다.
        # 모든 칸이 같은 줄만 한 달 파일 안에서 지우고 개수를 남긴다 — 달끼리 겹치거나 값이 다른 중복은 아래에서 막는다.
        unique = part.drop_duplicates()
        dropped += len(part) - len(unique)
        frames.append(unique)
    df = pd.concat(frames, ignore_index=True)
    sort_key = df["bar_start"].fillna(df["trade_date"])
    df = df.assign(_k=sort_key).sort_values("_k", kind="stable").drop(columns="_k").reset_index(drop=True)
    key = [c for c in markets.KEY if c in df.columns]
    if df.duplicated(subset=key).any():
        raise ValueError(f"{symbol} {interval}: 키 {key} 가 겹치는 줄이 있다")
    out = binance_vision.partition_path(out_root, interval, year or 0, symbol)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, compression="zstd", index=False)
    return {"path": out, "rows": int(len(df)), "bytes": out.stat().st_size, "first": str(df.iloc[0]["trade_date"]), "last": str(df.iloc[-1]["trade_date"]),
            "dropped_exact_dups": dropped}


def summarize(out_root: Path) -> Dict[str, dict]:
    """적재 루트의 주기별 파일 수 · 용량 — 용량 외삽에 쓴다."""
    res: Dict[str, dict] = {}
    for f in Path(out_root).glob("ohlcv/timeframe=*/**/*.parquet"):
        tf = f.parts[f.parts.index("ohlcv") + 1].split("=", 1)[1]
        r = res.setdefault(tf, {"files": 0, "bytes": 0})
        r["files"] += 1
        r["bytes"] += f.stat().st_size
    return res
