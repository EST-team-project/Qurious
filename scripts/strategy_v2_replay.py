"""판 2 다음 시가 가상 재현을 JSON으로 저장한다. 운영 DB·KIS 주문 호출 없음."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.strategy_v2 import load_bars
from app.services.strategy_v2_replay import replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--card", required=True, type=Path)
    parser.add_argument("--collector-db", required=True, type=Path)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--through", required=True, type=date.fromisoformat)
    parser.add_argument("--initial-cash", type=float, default=10_000_000)
    parser.add_argument("--budget", type=float, default=1_000_000)
    parser.add_argument("--slippage-bps", type=float, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.card.read_text(encoding="utf-8"))
    bars = load_bars("005930.KS", args.through, path=args.collector_db)
    result = replay(spec, bars, start=args.start, initial_cash=args.initial_cash,
                    budget=args.budget, slippage_bps=args.slippage_bps)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # 이 검증 결과는 새 파일에 쓴다. 이전 실행의 근거를 덮어쓰지 않는다.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"status": result["status"], "days": len(result["rows"]),
                      "fills": len(result["fills"]), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
