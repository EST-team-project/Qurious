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
# 2026-09-28 S57: stock.py 20 → 18 — 국내 주식 일봉이 수집 DB 로 옮겨 가며(DF-08) 설명 두 줄이 바뀌었다.
#   ⚠️ 이 시험은 '줄'을 센다. 실제로 줄어든 것은 **호출**이다 — get_candles 를 부르는 14곳 가운데
#   국내 주식 일봉 요청은 이제 외부로 나가지 않는다(tests/test_collector_candles_df08.py).
BASELINE: dict[str, int] = {
    # 2026-10-08 th06 e815be3 반영: 18 → 24 — 강사님이 국내 시세를 KIS(st 게이트웨이) 먼저 · 실패하면 야후로 돌리는
    #   갈래를 더했다(아래 「2026-10-08」 묶음과 같은 까닭). 새 줄 여섯은 설명 둘 · 로그 문구 둘 · 폴백 설정 확인 둘이고
    #   야후 주소를 새로 부르는 줄은 없다(호출은 그대로 `_yahoo_chart` 하나). 국내 일봉은 여전히 수집 DB 가 먼저다.
    "app/services/stock.py": 24,
    "app/services/lean_backtest.py": 19,
    "app/services/paper_trading.py": 10,
    "app/services/sync_scheduler.py": 7,
    "app/routes/macro.py": 7,
    "app/routes/stocks.py": 5,   # 2026-10-08: 4 → 5 — 스크리닝이 빈 캔들 종목을 건너뛰는 줄의 주석(호출 0 · 강사님 d3206b8)
    "app/services/krx_companies.py": 3,
    "app/services/data_cache.py": 2,
    # 2026-09-29 S63: API 명세 스캐너가 라우트마다 「야후에 닿는가」를 표시하려고 호스트 글자 조각을
    #   한 줄에 둔다(`HOST_SYSTEMS`). 부르는 코드가 아니라 **찾는** 코드다 — 호출은 0.
    #   봉인을 푸는 것이 아니라 봉인선을 재는 자를 들인 것이라 1줄만 연다.
    "scripts/api_scan.py": 1,
    # 2026-09-30: 강사님 원본 lumina-invest(b055ab0)를 기초 코드로 받으며 들어온 세 파일. 우리가 새로 쓴 코드가
    #   아니라 받은 코드라 봉인을 연다 — 바꿀지는 팀 논의 거리다(강사님 최신 반영 논의 · 데이터 파트).
    #   fx.py = 환율을 야후 통화쌍(KRW=X)으로 조회(실제 호출) · patterns.py = 여러 주기(60분봉) 탐지의 봉 간격
    #   (실제 호출 · 수집 DB 는 일봉뿐) · tradingview.py = 두 도구 차이를 설명하는 글자(호출 0).
    "app/services/fx.py": 1,
    "app/services/patterns.py": 1,
    "app/services/tradingview.py": 1,
    # 2026-09-30: 통합본 반입 폴더(rag-lab/) 스캐너가 통합본 API 마다 「야후에 닿는가」 를 표시하려고
    #   찾는 글자를 한 줄에 둔다(`TOUCH_PATTERNS`). api_scan 과 같은 까닭 — 부르는 코드가 아니라 **찾는** 코드다.
    #   ⚠️ rag-lab/ 자체는 이 시험이 훑지 않는다(SCAN_DIRS 밖). 그 폴더는 앱과 이어지지 않은 사본이고,
    #      기능을 app/ 으로 옮길 때 이 시험이 그 코드를 본다.
    "scripts/raglab_scan.py": 1,
    # 2026-10-01: OHLCV 규격 자료(목표 기능 ① 상세 설계서 5.1 · 11절). 팀 결정(2026-10-01 「비공개 저장이면
    #   출처를 가리지 않는다」)으로 **분봉 출처를 야후**로 정했다 — 한국 종목 분봉을 계좌 · 토큰 없이 과거까지 주는
    #   곳이 야후뿐이다. 앱이 야후를 부르는 줄이 아니라 **수집기**가 받아 수집 DB(price_intraday)에 쌓는 줄이다.
    #   yahoo_intraday = 분봉 받기(실제 호출 · 정규화) · ohlcv_load = 분봉 · 일봉 대조(crosscheck — 포털 일봉을 야후와
    #   견줌, 실제 호출) · db = 표 설명 주석 2 · ohlcv_export = 출처 칸 이름 · intake = 팀원이 yfinance 로 저장한
    #   CSV 모양을 읽는 설명(호출 0).
    "collector/sources/yahoo_intraday.py": 4,
    "collector/ohlcv_load.py": 6,
    "collector/db.py": 2,
    "collector/ohlcv_export.py": 1,
    "collector/intake.py": 1,
    # 2026-10-01: 금융 강의(「금융 필수 지식」 › 강의실 · 주제 화면). 통합본 강의 본문의 시세 그림이 부르던 주소 일곱을
    #   옮겼다(app/routes/lectures.py). 국내 지수 · 국고채 ETF · 종목은 **수집 DB 를 먼저** 읽고, 야후는 수집 DB 에 없는
    #   해외 지수(S&P 500 · EURO STOXX 50 · Nikkei 225) · 오늘의 1분봉 · 수집 DB 가 없는 PC 의 대체로만 부른다.
    #   **화면 표시만 하고 저장하지 않는다** — 사용자 결정(2026-09-30 「야후 · 네이버 시세는 적재하지 않되 화면 표시는
    #   괜찮다」). 통합본이 야후 값을 표에 넣던 주소(period-return/extend)는 넣지 않게 바꿨다.
    "app/services/lecture_market.py": 19,
    # 2026-10-08: 강사님 기초 코드 th06(9478811 → e815be3)를 받으며 들어온 세 파일 — 우리가 새로 쓴 코드가 아니라 받은
    #   코드라 09-30 선례대로 봉인을 연다. 셋 다 **야후 주소를 새로 부르지 않는다**: config = 시세 출처 설정 이름 ·
    #   설명(KIS ↔ 야후 폴백 · 공격 모드 분봉 간격) · aggressive_mode = 5분봉을 기존 get_candles 의 야후 길로 받는
    #   설명 · 로그 · 출처 이름표(공격 모드 기본 꺼짐 · 수집 DB 에는 분봉이 없다) · kis_market_data = 머리 설명 한 줄.
    #   KIS 시세는 게이트웨이 주소가 있을 때만 켜지므로 Qurious 에서는 잠들어 있다 — 바꿀지는 팀 논의 거리다.
    "app/config.py": 5,
    "app/services/aggressive_mode.py": 4,
    "app/services/kis_market_data.py": 1,
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
