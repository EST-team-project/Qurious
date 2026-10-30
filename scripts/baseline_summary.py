"""기준 전략 시험 결과 요약 — 시험 결과 파일(trials.json) → 화면이 읽는 작은 파일 `public/js/baseline-result.json` (2026-10-30 · ①-18).

왜 만드나
- 전략 분석 · 성과 검증 화면의 「기준 전략」 카드는 숫자를 화면 코드에 적지 않고 이 요약 파일에서 읽는다(결과를 다시 돌리면 낡는다).
- 요약은 원본(신장환 님이 낸 `docs/phase-3/04-testing/기준전략-시도-<날짜>/trials.json`)에서 **계산만** 한다 — 새 판정을 하지 않는다.
  합격선 · 「가장 가까운 시도」 규칙은 `scripts/baseline_trials.py` 가 실행 전에 정한 것을 그대로 따른다(결과를 본 뒤 고치지 않는다).
- 시험 TC-BNC-01 이 요약 파일이 원본과 같은지 대조한다 — 결과를 다시 돌리고 이 스크립트를 안 돌리면 시험이 실패한다.

쓰는 법
  python scripts/baseline_summary.py            # 가장 새 결과 폴더로 요약 파일을 다시 쓴다
  python scripts/baseline_summary.py --check    # 쓰지 않고 지금 파일이 원본과 같은지만 본다(다르면 종료 코드 1)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT_DIR = ROOT / "docs" / "phase-3" / "04-testing"
OUT = ROOT / "public" / "js" / "baseline-result.json"

# 시험 종목 이름 — 결과 문서의 종목 순위 표와 같다. 모르는 기호가 나오면 지어내지 않고 멈춘다.
NAMES = {
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "035420.KS": "NAVER", "207940.KS": "삼성바이오로직스",
    "005380.KS": "현대차", "012330.KS": "현대모비스", "068270.KS": "셀트리온", "051910.KS": "LG화학",
    "005490.KS": "POSCO", "028260.KS": "삼성물산",
}
FAMILY = "이동평균 교차"


def latest_trials() -> Path:
    """결과 폴더 가운데 날짜가 가장 늦은 `기준전략-시도-YYYY-MM-DD/trials.json`."""
    found = sorted(p for p in RESULT_DIR.glob("기준전략-시도-????-??-??/trials.json"))
    if not found:
        raise SystemExit("기준전략-시도-<날짜>/trials.json 을 찾지 못했다")
    return found[-1]


def _met(row: dict, line: dict) -> dict[str, bool]:
    pf = row["profit_factor"]
    return {
        "profit_factor": bool(pf is not None and pf > line["profit_factor"]),
        "mdd_pct": bool(row["mdd_pct"] > line["mdd_pct"]),
        "sharpe_ratio": bool(row["sharpe_ratio"] > line["sharpe_ratio"]),
    }


def _row(r: dict) -> dict:
    return {"symbol": r["symbol"], "name": NAMES[r["symbol"]], "short": r["short"], "long": r["long"],
            "profit_factor": r["profit_factor"], "mdd_pct": r["mdd_pct"], "sharpe_ratio": r["sharpe_ratio"]}


def build_summary(trials: dict, result_date: str) -> dict:
    """원본에서 화면에 필요한 것만 뽑는다 — 시도 수 · 합격 수 · 기준별 넘은 수 · 가장 가까운 시도 · 합격한 시도."""
    line = trials["pass_line"]
    rows = trials["trials"]
    unknown = sorted({r["symbol"] for r in rows} - set(NAMES))
    if unknown:
        raise SystemExit(f"종목 이름을 모른다(NAMES 에 더할 것): {unknown}")
    counts = {k: sum(_met(r, line)[k] for r in rows) for k in ("profit_factor", "mdd_pct", "sharpe_ratio")}
    period = {"start": min(s["start"] for s in trials["symbols"]), "end": max(s["end"] for s in trials["symbols"])}
    sealed = (date.fromisoformat(period["end"]) + timedelta(days=1)).isoformat()
    near = None
    if trials["nearest"]:
        n = trials["nearest"]
        row = next(r for r in rows if (r["symbol"], r["short"], r["long"]) == (n["symbol"], n["short"], n["long"]))
        met = _met(row, line)
        near = {**_row(row), "missed": [k for k, ok in met.items() if not ok]}
    passed = [_row(r) for r in rows if r["pass"]]
    passed.sort(key=lambda x: -x["sharpe_ratio"])
    return {
        "version": 1,
        "result_date": result_date,
        "family": FAMILY,
        "n_trials": trials["n_trials"],
        "n_symbols": len(trials["symbols"]),
        "n_combos": trials["n_trials"] // len(trials["symbols"]),
        "passed": trials["passed"],
        "pass_line": line,
        "counts": counts,
        "period": {**period, "sealed_from": sealed},
        "nearest": near,
        "passed_trials": passed[:5],
    }


def render(summary: dict) -> str:
    return json.dumps(summary, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="쓰지 않고 지금 요약 파일이 원본과 같은지만 본다")
    args = ap.parse_args()
    src = latest_trials()
    day = re.search(r"(\d{4}-\d{2}-\d{2})", src.parent.name).group(1)
    text = render(build_summary(json.loads(src.read_text(encoding="utf-8")), day))
    if args.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print(("✅ 같다" if same else "❌ 다르다 — python scripts/baseline_summary.py 로 다시 쓴다") + f" · 원본 {src.relative_to(ROOT)}")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"썼다: {OUT.relative_to(ROOT)} · 원본 {src.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
