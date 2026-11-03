r"""F.13 손절 · 익절 · 포지션 크기 — 그림 셋 (2026-11-03).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\stop-loss-take-profit.py
출력  : public/learn/img/stop-loss-take-profit/{stop-touch-probability,position-size-by-stop,kelly-growth}.svg

계산은 장의 예제 public/learn/examples/position_sizing.py 의 함수를 그대로 불러 쓴다(장의 출력과 그림이 같은 코드에서 나온다).
그림 1 · 3(오른쪽)은 합성 데이터(시드 42), 그림 2 는 손으로 정한 계좌 숫자, 그림 3(왼쪽)은 계산식 그림이다.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _style import COLORS, ROOT, apply_style, caption, new_fig, save_svg  # noqa: E402

SLUG = "stop-loss-take-profit"


def load_example():
    path = ROOT / "public" / "learn" / "examples" / "position_sizing.py"
    spec = importlib.util.spec_from_file_location("position_sizing", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["position_sizing"] = mod
    spec.loader.exec_module(mod)
    return mod


def fig_stop_touch(ps) -> None:
    pcts = (1, 2, 4, 6, 8)
    prob = ps.stop_touch_probability(pcts)
    fig, ax = new_fig(figsize=(8.4, 4.4))
    xs = np.arange(len(pcts))
    vals = [prob[float(x)] * 100 for x in pcts]
    ax.set_axisbelow(True)
    bars = ax.bar(xs, vals, color=COLORS["blue"], width=0.62)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 1.5, f"{v:.1f}%", ha="center", fontsize=10.5, fontweight="bold", color=COLORS["ink"])
    ax.set_xticks(xs, [f"-{x}%" for x in pcts])
    ax.set_xlabel("손절 폭 (진입가 대비 · 일 표준편차는 2%)")
    ax.set_ylabel("20일 안에 종가가 닿은 경로의 비율 (%)")
    ax.set_ylim(0, 100)
    ax.set_title("손절 폭이 좁을수록 평범한 흔들림에도 자주 걸립니다")
    ax.axvspan(-0.5, 1.5, color=COLORS["orange"], alpha=0.10)
    ax.text(0.5, 92, "하루 흔들림(2%)\n이하의 폭", ha="center", va="top", fontsize=9.5, color=COLORS["orange"], fontweight="bold")
    caption(fig, "합성 데이터 · 일 수익률 평균 0 · 표준편차 2% · 경로 10,000개 · 20거래일 · 종가 기준 · 시드 42 · 실제 종목의 값이 아님")
    save_svg(fig, SLUG, "stop-touch-probability")


def fig_position_size(ps) -> None:
    equity, entry = 10_000_000, 50_000
    dists = (1_000, 2_000, 4_000, 8_000)
    risk_qty = [equity // 100 // d for d in dists]
    capped = [ps.quantity_limits(equity, equity, equity, 1, entry, entry - d)["수량"] for d in dists]
    cap_qty = int(equity * 0.30 // entry)
    fig, ax = new_fig(figsize=(8.4, 4.6))
    xs = np.arange(len(dists))
    w = 0.36
    ax.set_axisbelow(True)
    b1 = ax.bar(xs - w / 2, risk_qty, w, color=COLORS["blue"], label="위험 1% 로 구한 수량")
    b2 = ax.bar(xs + w / 2, capped, w, color=COLORS["green"], hatch="//", edgecolor="white", label="종목 비중 상한 30% 를 넣은 수량")
    for b, v in list(zip(b1, risk_qty)) + list(zip(b2, capped)):
        ax.text(b.get_x() + b.get_width() / 2, v + 2, f"{v}주", ha="center", fontsize=10, fontweight="bold", color=COLORS["ink"])
    ax.axhline(cap_qty, color=COLORS["red"], lw=1.2, ls="--")
    ax.text(3.45, cap_qty + 2, f"비중 상한 {cap_qty}주 (자산의 30%)", ha="right", fontsize=9.5, color=COLORS["red"])
    ax.set_xticks(xs, [f"{d:,}원\n({d / entry * 100:.0f}%)" for d in dists])
    ax.set_xlabel("손절 폭 = 진입가 50,000원 - 손절가")
    ax.set_ylabel("살 수 있는 수량 (주)")
    ax.set_ylim(0, 118)
    ax.set_title("같은 위험(자산의 1% = 100,000원)이면 손절 폭이 넓을수록 적게 삽니다")
    ax.legend(loc="upper right", bbox_to_anchor=(1.0, 0.9))
    caption(fig, "손으로 정한 예 · 자산 10,000,000원 · 위험 1% · 진입 50,000원 · 비용 · 슬리피지 제외 · 손절에 걸리면 어느 막대든 잃는 돈은 약 100,000원")
    save_svg(fig, SLUG, "position-size-by-stop")


def fig_kelly(ps) -> None:
    p = 0.53
    fstar = ps.kelly_fraction(p)
    fig, (ax1, ax2) = new_fig(figsize=(8.8, 4.6), ncols=2, gridspec_kw={"width_ratios": [3, 2]})
    f = np.linspace(0.0, 0.14, 300)
    g = np.array([ps.log_growth(x, p) for x in f]) * 1000
    ax1.plot(f * 100, g, color=COLORS["gray"], lw=2)
    ax1.axhline(0, color=COLORS["ink"], lw=0.8)
    marks = (("0.5배", 0.5, COLORS["green"], "o", (10, -22)), ("1배(f*)", 1.0, COLORS["blue"], "s", (-4, 12)), ("2배", 2.0, COLORS["red"], "D", (-70, 16)))
    for label, m, color, marker, off in marks:
        x = m * fstar
        y = ps.log_growth(x, p) * 1000
        ax1.scatter([x * 100], [y], s=70, color=color, marker=marker, zorder=3)
        ax1.annotate(f"{label}  f={x * 100:.0f}%\n성장 {y:+.2f}", (x * 100, y), textcoords="offset points", xytext=off,
                     color=color, fontsize=9.5, fontweight="bold")
    ax1.set_xlabel("걸 비율 f (자본의 %)")
    ax1.set_ylabel("한 번당 평균 로그 성장률 (×0.001)")
    ax1.set_title("이길 확률 53% 동전: 성장률 g(f)")
    ax1.set_ylim(-0.7, 2.4)

    rows = ps.kelly_simulation(p, [m * fstar for m in (0.5, 1.0, 2.0)])
    labels = ["0.5배", "1배", "2배"]
    colors = [COLORS["green"], COLORS["blue"], COLORS["red"]]
    vals = [r["MDD 중앙값"] * 100 for r in rows]
    ax2.set_axisbelow(True)
    bars = ax2.bar(labels, vals, color=colors, width=0.6)
    for b, v in zip(bars, vals):
        ax2.text(b.get_x() + b.get_width() / 2, v + 1.5, f"{v:.1f}%", ha="center", fontsize=10.5, fontweight="bold", color=COLORS["ink"])
    ax2.set_ylim(0, 112)
    ax2.set_ylabel("고점 대비 최대 낙폭의 중앙값 (%)")
    ax2.set_title("1,000번 걸었을 때의 낙폭")
    caption(fig, "왼쪽: 계산식 그림. 오른쪽: 합성 데이터 · 동전 1,000번 × 2,000번 반복 · 같은 던지기를 세 비율에 적용 · 시드 42 · 켈리 배수 = f* 의 몇 배를 거는가")
    save_svg(fig, SLUG, "kelly-growth")


def main() -> None:
    apply_style()
    ps = load_example()
    fig_stop_touch(ps)
    fig_position_size(ps)
    fig_kelly(ps)
    for p in sorted((ROOT / "public" / "learn" / "img" / SLUG).glob("*.svg")):
        print(p.relative_to(ROOT), p.stat().st_size)


if __name__ == "__main__":
    main()
