"""리스크 패리티(위험 기여 균등)와 최소분산 — 비중과 위험 기여는 다르다 (합성 데이터).

실행    python risk_parity.py      (numpy 와 scipy 만 · 외부 접속 없음)
자료    변동성 · 상관을 손으로 정한 값이다. 실제 자산이 아니다.
        ② 는 Qian(2005) PanAgora 백서가 60/40 예에 쓴 입력(주식 변동성 15.1% · 채권 4.6% · 상관 0.2)이다.
        ③ 은 Maillard · Roncalli · Teiletche(2009.5 작업논문 판) 4.1절의 표본 예와 같은 입력(변동성 10 · 20 · 30 · 40%, 상관 모두 같음)이다.
        ④ ~ ⑨ 는 앱의 네 자산군(국내주식 · 해외주식 · 국내채권 · 대체자산)을 닮은 가상의 네 자산이다.
        앱의 app/services/allocation_models.py 와 같은 목적함수(위험 기여 비율 − 1/n 의 제곱합)와 제약(합 1 · 비중 한도)을
        SciPy SLSQP 로 푼다. 수렴 허용치(ftol · maxiter)만 이 예제가 더 엄격하다.

함수
    risk_shares(w, cov)        위험 기여 비율 = wᵢ(Σw)ᵢ / (wᵀΣw)  (합 1)
    solve_erc(cov, lo, hi)     위험 기여를 균등하게 맞추는 비중 (합 1 · 공매도 없음 · 비중 lo~hi)
    solve_minvar(cov, lo, hi)  변동성이 가장 작은 비중 (합 1 · 공매도 없음 · 비중 lo~hi)

그림 만드는 코드(tools/learn_figs/risk-parity-min-variance.py)도 이 파일의 함수를 그대로 불러 쓴다.
"""
from __future__ import annotations

import unicodedata

import numpy as np
from scipy.optimize import minimize

NAMES = ("국내주식", "해외주식", "국내채권", "대체자산")
VOL4 = np.array([0.18, 0.16, 0.05, 0.14])
CORR4 = np.array([[1, .7, .1, .2], [.7, 1, .0, .2], [.1, .0, 1, .1], [.2, .2, .1, 1]])
COV4 = np.outer(VOL4, VOL4) * CORR4


def risk_shares(w, cov):
    return w * (cov @ w) / (w @ cov @ w)


def _solve(objective, cov, lo, hi, start):
    n = len(cov)
    res = minimize(objective, start, method="SLSQP", bounds=[(lo, hi)] * n,
                   constraints={"type": "eq", "fun": lambda w: w.sum() - 1}, options={"maxiter": 2000, "ftol": 1e-14})
    return res.x


def solve_erc(cov, lo=0.01, hi=0.95):
    n = len(cov)
    start = 1 / np.sqrt(np.diag(cov)); start /= start.sum()      # 시작점일 뿐 정답이 아니다
    return _solve(lambda w: float(np.sum((risk_shares(w, cov) - 1 / n) ** 2)), cov, lo, hi, start)


def solve_minvar(cov, lo=0.01, hi=0.95):
    n = len(cov)
    return _solve(lambda w: float(w @ cov @ w), cov, lo, hi, np.ones(n) / n)


def vol_of(w, cov) -> float:
    return float(np.sqrt(w @ cov @ w))


def eq_corr_cov(vols, rho):
    c = np.full((len(vols), len(vols)), rho); np.fill_diagonal(c, 1)
    return np.outer(vols, vols) * c


def pad(text: str, width: int) -> str:
    """한글을 두 칸으로 세어 오른쪽을 공백으로 채운다(표 열이 맞게)."""
    cols = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(0, width - cols)


def pct(w) -> str:
    return "[" + " ".join(f"{x * 100:5.1f}" for x in w) + "]"


def main() -> None:
    print("① 손으로 풀 수 있는 예 — 변동성 10% · 30%, 상관 0 (합성)")
    cov2 = np.diag([0.10 ** 2, 0.30 ** 2])
    half = np.array([0.5, 0.5]); inv = (1 / np.array([0.1, 0.3])); inv /= inv.sum()
    print(f"  50:50  위험 기여 {pct(risk_shares(half, cov2))}%  변동성 {vol_of(half, cov2) * 100:.2f}%")
    print(f"  75:25  위험 기여 {pct(risk_shares(inv, cov2))}%  변동성 {vol_of(inv, cov2) * 100:.2f}%")
    cov2_high = np.outer([0.10, 0.30], [0.10, 0.30]) * np.array([[1, 0.8], [0.8, 1]])
    print(f"  75:25  상관 0.8 이어도 위험 기여 {pct(risk_shares(inv, cov2_high))}%  변동성 {vol_of(inv, cov2_high) * 100:.2f}%")

    print("② 60/40 의 위험 기여 — Qian(2005) 백서의 입력 (주식 변동성 15.1% · 채권 4.6% · 상관 0.2)")
    vols_q = np.array([0.151, 0.046])
    cov_q = eq_corr_cov(vols_q, 0.2)
    w_q = np.array([0.6, 0.4])
    inv_q = (1 / vols_q) / (1 / vols_q).sum()
    print(f"  60:40            비중 {pct(w_q)}%  위험 기여 {pct(risk_shares(w_q, cov_q))}%  변동성 {vol_of(w_q, cov_q) * 100:.2f}%")
    print(f"  위험 기여 균등   비중 {pct(inv_q)}%  위험 기여 {pct(risk_shares(inv_q, cov_q))}%  변동성 {vol_of(inv_q, cov_q) * 100:.2f}%")

    print("③ 변동성 10 · 20 · 30 · 40%, 상관 모두 0.5 (합성 · 논문의 표본 예와 같은 입력)")
    vols = np.array([0.10, 0.20, 0.30, 0.40])
    cov = eq_corr_cov(vols, 0.5)
    inv = (1 / vols) / (1 / vols).sum()
    for label, w in (("1/n", np.ones(4) / 4), ("1/변동성 비중", inv), ("위험 기여 균등(비중 0~100%)", solve_erc(cov, 0.0, 1.0)),
                     ("위험 기여 균등(1~95%)", solve_erc(cov)), ("최소분산(0~100%)", solve_minvar(cov, 0.0, 1.0)),
                     ("최소분산(1~95%)", solve_minvar(cov))):
        w = np.where(np.abs(w) < 5e-5, 0, w)
        print(f"  {pad(label, 30)}비중 {pct(w)}%  변동성 {vol_of(w, cov) * 100:5.2f}%  위험 기여 {pct(risk_shares(w, cov))}%")
    w30 = solve_minvar(eq_corr_cov(vols, 0.3), 0.0, 1.0)
    print(f"  상관 0.3 이면 최소분산(0~100%) {pct(np.where(w30 < 5e-5, 0, w30))}%")

    print("④ 네 자산(합성): 변동성 18 · 16 · 5 · 14%, 주식끼리 상관 0.7 — 비중과 위험 기여 (비중 한도 1~95%)")
    ports = {"1/n": np.ones(4) / 4, "위험 기여 균등": solve_erc(COV4), "최소분산": solve_minvar(COV4)}
    for label, w in ports.items():
        print(f"  {pad(label, 16)}비중 {pct(w)}%  위험 기여 {pct(risk_shares(w, COV4))}%  변동성 {vol_of(w, COV4) * 100:5.2f}%")

    print("⑤ 상관이 제각각이면 1/변동성 비중은 위험 기여를 균등하게 만들지 못한다 (같은 네 자산)")
    inv4 = (1 / VOL4) / (1 / VOL4).sum()
    print(f"  1/변동성 비중 {pct(inv4)}%  위험 기여 {pct(risk_shares(inv4, COV4))}%")

    print("⑥ 한 자산의 변동성이 0.2% 이면(예: 짧은 만기 상품) 한도 95% 가 균등을 막는다")
    vol_x = VOL4.copy(); vol_x[2] = 0.002
    cov_x = np.outer(vol_x, vol_x) * CORR4
    for label, lo, hi in (("한도 없음(0~100%)", 0.0, 1.0), ("앱 한도(1~95%)", 0.01, 0.95)):
        w = solve_erc(cov_x, lo, hi); s = risk_shares(w, cov_x)
        print(f"  {pad(label, 18)}비중 {pct(w)}%  위험 기여 {pct(s)}%  가장 많이 어긋난 값 {np.max(np.abs(s - 0.25)) * 100:.1f}%p")

    print("⑦ 표시를 반올림하면 위험 기여가 조금 달라진다 (④ 의 위험 기여 균등 비중)")
    w = solve_erc(COV4)
    for label, unit in (("0.1% 단위", 1000), ("1% 단위", 100)):
        r = np.round(w * unit) / unit
        r = r / r.sum()
        print(f"  {label}  비중 {pct(r)}%  위험 기여 {pct(risk_shares(r, COV4))}%  가장 많이 어긋난 값 {np.max(np.abs(risk_shares(r, COV4) - 0.25)) * 100:.2f}%p")

    print("⑧ 최소분산: 합 1 만 지키는 닫힌 식은 음수 비중을 낼 수 있다 (④ 와 같은 네 자산)")
    closed = np.linalg.solve(COV4, np.ones(4)); closed /= closed.sum()
    for label, w in (("닫힌 식(합 1 만)", closed), ("공매도 없음(0~100%)", solve_minvar(COV4, 0.0, 1.0)),
                     ("앱 한도(1~95%)", solve_minvar(COV4))):
        w = np.where(np.abs(w) < 5e-5, 0, w)
        print(f"  {pad(label, 20)}비중 {pct(w)}%  변동성 {vol_of(w, COV4) * 100:5.2f}%")

    print("⑨ 무엇을 같게 맞추나 — 한계 기여(비중을 조금 늘릴 때 변동성이 느는 정도)와 총 기여(비중 × 한계 기여) (④ 와 같은 네 자산 · 한도 없음)")
    for label, w in (("1/n", np.ones(4) / 4), ("위험 기여 균등", solve_erc(COV4, 0.0, 1.0)), ("최소분산", solve_minvar(COV4, 0.0, 1.0))):
        w = np.where(np.abs(w) < 5e-5, 0, w)
        marginal = (COV4 @ w) / vol_of(w, COV4)
        print(f"  {pad(label, 16)}한계 기여 {pct(marginal)}%  총 기여 {pct(w * marginal)}%  (합 = 변동성 {vol_of(w, COV4) * 100:.2f}%)")


if __name__ == "__main__":
    main()
