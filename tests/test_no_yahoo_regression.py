"""야후 파이낸스 의존 봉인 시험 (#61 P1-1 · #62 §5.0).

왜 '금지'가 아니라 '봉인'인가 —
지금 야후를 참조하는 줄이 **8파일 72줄** 남아 있다. 전부 지우는 일(get_candles →
수집 DB 어댑터)은 별도 작업이고, 그때까지 시간이 걸린다. 그 사이에 야후 참조가
**늘어나는 것만은** 막아야 한다. 그래서 이 시험은 "0이어야 한다"가 아니라
"아래 적힌 수보다 많아지면 안 된다"를 확인한다.

줄면 어떻게 되는가 —
줄어도 **실패한다.** 일부러 그렇게 했다. 줄었다는 것은 치우는 작업이 진행됐다는
뜻이니, 그때 이 표를 함께 낮춰야 다음 회귀를 다시 잡을 수 있다. 표를 낮추지 않으면
봉인선이 헐거워져 나중에 도로 늘어도 눈치채지 못한다.

기준선을 고치는 절차 —
`python -m tests.test_no_yahoo_regression` 로 현재 수를 찍어 아래 표에 옮긴다.
**줄어든 경우에만** 고친다. 늘어서 고치는 것은 봉인을 푸는 일이라 PR 설명에
왜 필요한지 적어야 한다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 훑는 범위. `tests/` 는 제외한다 — 이 파일 자신이 걸린다.
SCAN_DIRS = ("app", "collector", "scripts")

# 야후를 가리키는 표시. 호스트명·패키지명·브랜드명을 모두 본다.
PATTERN = re.compile(r"yahoo|yfinance|query[12]\.finance", re.IGNORECASE)

# ── 기준선 (2026-09-21 실측 · 줄 단위) ──────────────────────────────
# 한 줄에 여러 번 나와도 1 로 센다.
BASELINE: dict[str, int] = {
    "app/services/stock.py": 20,
    "app/services/lean_backtest.py": 19,
    "app/services/paper_trading.py": 10,
    "app/services/sync_scheduler.py": 7,
    "app/routes/macro.py": 7,
    "app/routes/stocks.py": 4,
    "app/services/krx_companies.py": 3,
    "app/services/data_cache.py": 2,
}


def 현재_참조수() -> dict[str, int]:
    """야후를 참조하는 파일별 줄 수를 센다."""
    결과: dict[str, int] = {}
    for 디렉터리 in SCAN_DIRS:
        뿌리 = ROOT / 디렉터리
        if not 뿌리.exists():
            continue
        for 파일 in 뿌리.rglob("*.py"):
            if "__pycache__" in 파일.parts:
                continue
            본문 = 파일.read_text(encoding="utf-8", errors="replace")
            수 = sum(1 for 줄 in 본문.splitlines() if PATTERN.search(줄))
            if 수:
                결과[파일.relative_to(ROOT).as_posix()] = 수
    return 결과


def test_야후_참조가_기준선과_같다():
    현재 = 현재_참조수()

    늘어남 = {
        경로: (현재[경로], BASELINE.get(경로, 0))
        for 경로 in 현재
        if 현재[경로] > BASELINE.get(경로, 0)
    }
    줄어듦 = {
        경로: (현재.get(경로, 0), BASELINE[경로])
        for 경로 in BASELINE
        if 현재.get(경로, 0) < BASELINE[경로]
    }

    if 늘어남:
        상세 = "\n".join(f"    {p}: {a}줄 (기준선 {b})" for p, (a, b) in 늘어남.items())
        raise AssertionError(
            "야후 파이낸스 참조가 늘었다. 새 코드는 수집 DB 를 쓴다 (#61 P1-1):\n" + 상세
        )
    if 줄어듦:
        상세 = "\n".join(f"    {p}: {a}줄 (기준선 {b})" for p, (a, b) in 줄어듦.items())
        raise AssertionError(
            "야후 참조가 줄었다 — 좋은 일이다. BASELINE 을 아래 값으로 낮춰\n"
            "봉인선을 다시 조여 달라:\n" + 상세
        )


def test_기준선에_없는_파일이_야후를_쓰지_않는다():
    """새 파일이 야후를 들고 들어오는 경우를 따로 잡는다.

    위 시험에도 걸리지만, 실패 메시지가 '늘었다'라 원인이 흐려진다.
    """
    새로 = sorted(set(현재_참조수()) - set(BASELINE))
    assert not 새로, "야후를 참조하는 새 파일: " + ", ".join(새로)


if __name__ == "__main__":  # 기준선을 갱신할 때 쓴다
    for 경로, 수 in sorted(현재_참조수().items(), key=lambda x: -x[1]):
        print(f'    "{경로}": {수},')
