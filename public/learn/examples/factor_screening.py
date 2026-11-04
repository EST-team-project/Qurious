"""팩터 점수를 합쳐 순위 매기기, 그리고 생존편향이 평균을 어떻게 부풀리는지 — 합성 데이터 예제.

실행    python factor_screening.py        (numpy 만 · 네트워크 없음)
자료    모두 합성 — 종목 이름 A~H 와 가격은 시드가 고정된 난수로 만든 가상 값이다(의미 있는 종목이 아니다). 특정 팩터가 앞으로 돈이 된다는 뜻이 아니다.
흐름    ① 모멘텀 12-1(최근 21거래일은 건너뜀)과 60일 변동성을 구한다
        ② 횡단면 z점수(평균 0 · 표준편차 1)로 맞추고, 변동성은 낮을수록 +가 되게 부호를 뒤집는다
        ③ 미리 정한 가중치(0.5 · 0.5)로 합쳐 복합 점수와 순위를 만든다
        ④ 생존편향 장난감 실험 — 누적 −50% 에 닿은 종목을 폐지로 보고, 살아남은 종목만 평균을 내면 어떻게 되는가
"""
from __future__ import annotations

import numpy as np


def zscore(x: np.ndarray) -> np.ndarray:
    return (x - x.mean()) / x.std(ddof=1)


def composite() -> None:
    rng = np.random.default_rng(11)
    names = list("ABCDEFGH")
    px = 100 * np.cumprod(1 + rng.normal(0.0004, 0.015, (300, 8)), axis=0)       # 300일 × 8종목 가상 가격
    mom = px[-1 - 21] / px[-1 - 252] - 1                                          # 12-1 : 21거래일 전 가격 ÷ 252거래일 전 가격 − 1
    ret = px[1:] / px[:-1] - 1
    vol = ret[-60:].std(axis=0, ddof=1) * np.sqrt(252)                            # 최근 60일 연환산 변동성
    score = 0.5 * zscore(mom) + 0.5 * zscore(-vol)                                # 변동성은 낮을수록 + (사전에 정한 가중치)
    order = np.argsort(-score)
    print("① ~ ③ 복합 점수 (합성 8종목, 가중치 0.5 · 0.5)")
    print("   종목  모멘텀12-1  변동성  복합점수")
    for i in order:
        print(f"   {names[i]:>3}  {mom[i]:>9.3f}  {vol[i]:>6.3f}  {score[i]:>7.2f}")


def survivorship() -> None:
    rng = np.random.default_rng(5)
    n, days = 200, 750
    path = np.cumprod(1 + rng.normal(0.0003, 0.02, (days, n)), axis=0)           # 200종목 × 750일 가상 가격(시작=1)
    hit = (path <= 0.5)
    delisted = hit.any(axis=0)                                                    # 한 번이라도 −50% 에 닿으면 폐지
    first = np.where(delisted, hit.argmax(axis=0), days - 1)                      # 폐지일(없으면 마지막 날)
    final = path[first, np.arange(n)]                                             # 폐지 종목은 폐지 시점 값에서 멈춘다
    print("④ 생존편향 장난감 실험 (합성 200종목 · 750일)")
    print(f"   폐지된 종목 수            : {int(delisted.sum())} / {n}")
    print(f"   폐지 포함 평균 최종 배수  : {final.mean():.3f}")
    print(f"   살아남은 종목만 평균 배수 : {final[~delisted].mean():.3f}")


if __name__ == "__main__":
    composite()
    survivorship()
