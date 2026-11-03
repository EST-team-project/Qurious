r"""F.12 백테스트 결과를 믿어도 될까 — 그림 둘 (S196 · 2026-11-03).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\can-you-trust-a-backtest.py
출력  : public/learn/img/can-you-trust-a-backtest/{best-sharpe-by-trials,in-sample-out-of-sample}.svg

계산은 장의 예제 public/learn/examples/backtest_trust.py 의 함수를 그대로 불러 쓴다(장의 출력과 그림이 같은 코드에서 나온다).
두 그림 모두 합성 데이터다: 평균 0 · 일 표준편차 1% 정규분포 난수(시드 42).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _style import COLORS, ROOT, apply_style, caption, new_fig, save_svg  # noqa: E402

SLUG = "can-you-trust-a-backtest"


def load_example():
    path = ROOT / "public" / "learn" / "examples" / "backtest_trust.py"
    spec = importlib.util.spec_from_file_location("backtest_trust", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backtest_trust"] = mod
    spec.loader.exec_module(mod)
    return mod


def fig_best_sharpe(bt) -> None:
    best = bt.best_sharpe_by_trials()
    ns = list(best)
    fig, ax = new_fig()
    xs = np.arange(len(ns))
    bars = ax.bar(xs, [best[n] for n in ns], width=0.55, color=COLORS["blue"], alpha=0.85, label="시뮬레이션(200번 평균)")
    ax.scatter(xs, [bt.expected_max_sharpe(n) for n in ns], marker="D", s=60, color=COLORS["orange"], zorder=3,
               label="논문의 기대 최댓값 식")
    for b, n in zip(bars, ns):
        v = best[n]
        ax.annotate(f"{v:+.2f}", (b.get_x() + b.get_width() / 2, max(v, bt.expected_max_sharpe(n), 0)), textcoords="offset points",
                    xytext=(0, 9), ha="center", fontsize=11, fontweight="bold", color=COLORS["ink"])
    ax.axhline(0, color=COLORS["gray"], lw=1)
    ax.set_xticks(xs, [f"{n:,}개" for n in ns])
    ax.set_xlabel("시험한 난수 전략의 수 N (모두 실력 0)")
    ax.set_ylabel("그중 가장 높은 연환산 샤프")
    ax.set_title("실력이 없어도 많이 시험할수록 높은 샤프가 나옵니다")
    ax.set_ylim(-0.3, 2.4)
    ax.legend(loc="upper left")
    caption(fig, "합성 데이터 · 평균 0 · 일 표준편차 1% · 3년(756일) · 200번 평균 · 시드 42 · 샤프는 무위험 0 · ×√252")
    save_svg(fig, SLUG, "best-sharpe-by-trials")


def fig_in_out(bt) -> None:
    days = bt.DAYS_3Y
    ins, outs, se = bt.in_sample_vs_out()
    # 시드 42 의 첫 반복 — 고르지 않고 첫 번째를 그대로 그린다
    s_in_best, s_out, cum = bt.first_repetition()

    fig, (ax, bx) = new_fig(figsize=(8.4, 4.4), ncols=2, gridspec_kw={"width_ratios": [3, 2]})
    x = np.arange(2 * days + 1)
    ax.axvspan(0, days, color=COLORS["blue"], alpha=0.07)
    ax.axvspan(days, 2 * days, color=COLORS["orange"], alpha=0.07)
    ax.plot(x[: days + 1], cum[: days + 1], color=COLORS["blue"])
    ax.plot(x[days:], cum[days:], color=COLORS["orange"], ls="--")
    top = ax.get_ylim()[1]
    ax.text(days / 2, top, f"표본 안 (고르는 구간)\n샤프 {s_in_best:+.2f}", ha="center", va="top", color=COLORS["blue"], fontsize=10, fontweight="bold")
    ax.text(days * 1.5, top, f"표본 밖 (그대로 씀)\n샤프 {s_out:+.2f}", ha="center", va="top", color=COLORS["orange"], fontsize=10, fontweight="bold")
    ax.set_xticks([0, days, 2 * days], ["0", "3년", "6년"])
    ax.set_ylabel("누적 가치 (시작 = 1)")
    ax.set_title("100개 중 앞 3년 1등의 6년")

    ax2 = bx
    ax2.bar([0, 1], [ins, outs], width=0.55, color=[COLORS["blue"], COLORS["orange"]], alpha=0.85)
    ax2.errorbar([1], [outs], yerr=[1.96 * se], color=COLORS["ink"], capsize=5, lw=1.5)
    for xi, v in ((0, ins), (1, outs)):
        ax2.annotate(f"{v:+.2f}", (xi, max(v, 0)), textcoords="offset points", xytext=(0, 8 if xi == 0 else 16),
                     ha="center", fontsize=11, fontweight="bold", color=COLORS["ink"])
    ax2.axhline(0, color=COLORS["gray"], lw=1)
    ax2.set_xticks([0, 1], ["표본 안", "표본 밖"])
    ax2.set_ylim(-0.4, 1.9)
    ax2.set_title("300번 평균 연환산 샤프")
    caption(fig, "합성 데이터 · 난수 전략 100개 · 평균 0 · 일 표준편차 1% · 시드 42 · 왼쪽은 시드 42의 첫 반복(고르지 않음) · 막대의 선은 95% 오차 범위")
    save_svg(fig, SLUG, "in-sample-out-of-sample")


def main() -> None:
    apply_style()
    bt = load_example()
    fig_best_sharpe(bt)
    fig_in_out(bt)
    for p in sorted((ROOT / "public" / "learn" / "img" / SLUG).glob("*.svg")):
        print(p.relative_to(ROOT), p.stat().st_size)


if __name__ == "__main__":
    main()
