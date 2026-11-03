r"""F.11 성과 지표 읽는 법 — 그림 둘 (S196 · 2026-11-03).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\reading-performance-metrics.py
출력  : public/learn/img/reading-performance-metrics/{same-return-different-mdd,breakeven-win-rate}.svg

계산은 장의 예제 public/learn/examples/reading_metrics.py 의 함수를 그대로 불러 쓴다(장의 출력과 그림이 같은 코드에서 나온다).
그림 1 은 합성 데이터(시드 3 · 섞기 시드 2026), 그림 2 는 계산식 그림이라 데이터가 없다.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _style import COLORS, ROOT, apply_style, caption, new_fig, save_svg  # noqa: E402

SLUG = "reading-performance-metrics"


def load_example():
    path = ROOT / "public" / "learn" / "examples" / "reading_metrics.py"
    spec = importlib.util.spec_from_file_location("reading_metrics", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reading_metrics"] = mod
    spec.loader.exec_module(mod)
    return mod


def fig_same_return_different_mdd(rm) -> None:
    base = np.random.default_rng(3).normal(0.0008, 0.01, 252)
    shallow, deep, median = rm.extreme_orders(base)
    fig, (ax1, ax2) = new_fig(figsize=(8.4, 5.6), nrows=2, sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    x = np.arange(253)
    series = (("A", shallow, COLORS["blue"], "-"), ("B", deep, COLORS["orange"], "--"))
    for name, r, color, ls in series:
        cum = np.concatenate([[1.0], np.cumprod(1 + r)])
        dd = cum / np.maximum.accumulate(cum) - 1
        ax1.plot(x, cum, color=color, ls=ls, label=name)
        ax2.plot(x, dd * 100, color=color, ls=ls)
        ax2.fill_between(x, dd * 100, 0, color=color, alpha=0.10)
        k = int(dd.argmin())
        ax2.annotate(f"{name} 의 MDD {dd.min() * 100:.1f}%", (k, dd.min() * 100), color=color, fontsize=10, fontweight="bold",
                     textcoords="data", xytext=(k + 10, dd.min() * 100 - 4.0) if name == "B" else (k + 18, -11.5),
                     arrowprops={"arrowstyle": "-", "color": color, "lw": 1})
    final = float(np.prod(1 + shallow))
    ax1.axhline(final, color=COLORS["gray"], lw=1, ls=":")
    ax1.annotate(f"두 곡선 모두 끝은 {final:.3f} (+{(final - 1) * 100:.1f}%)", (252, final), textcoords="data",
                 xytext=(70, final + 0.07), color=COLORS["ink"], fontsize=10, ha="left",
                 arrowprops={"arrowstyle": "->", "color": COLORS["gray"], "lw": 1})
    ax1.set_ylim(0.85, 1.36)
    ax1.set_ylabel("누적 가치 (시작 = 1)")
    ax1.set_title("같은 수익률 252개, 순서만 다른 두 길")
    ax1.legend(loc="lower left", ncol=2)
    ax2.set_ylabel("고점 대비 낙폭 (%)")
    ax2.set_xlabel("거래일")
    ax2.set_ylim(min(dd.min() * 100 - 4, -30), 3)
    caption(fig, f"합성 데이터 · 평균 0.08% · 표준편차 1% · 시드 3 · 2,000번 섞어(시드 2026) 가장 얕은 순서 A · 가장 깊은 순서 B · 섞은 MDD 중앙값 {median * 100:.1f}%")
    save_svg(fig, SLUG, "same-return-different-mdd")


def fig_breakeven(rm) -> None:
    fig, ax = new_fig(figsize=(8.4, 4.6))
    rr = np.linspace(0.3, 3.2, 200)
    ax.plot(rr, 100 / (1 + rr), color=COLORS["gray"], lw=2)
    ax.annotate("본전 승률 = 1 ÷ (1 + 손익비)", (2.0, 100 / 3), textcoords="offset points", xytext=(6, 14),
                color=COLORS["gray"], fontsize=10)
    pts = []
    pre = 1.5 / 1.0
    pts.append((pre, 100 / (1 + pre), "비용 전  +1.5% / -1.0%", COLORS["green"], "o", (10, 10)))
    x0 = rm.exit_cost_example(1.5, 1.0, 0)
    pts.append((x0["손익비"], x0["본전 승률(%)"], f"비용 뒤 · 슬리피지 0bp  손익비 {x0['손익비']:.2f}", COLORS["blue"], "s", (10, 10)))
    x10 = rm.exit_cost_example(1.5, 1.0, 10)
    pts.append((x10["손익비"], x10["본전 승률(%)"], f"비용 뒤 · 슬리피지 10bp(가정)  손익비 {x10['손익비']:.2f}", COLORS["orange"], "D", (12, 6)))
    for x, y, label, color, marker, off in pts:
        ax.scatter([x], [y], s=70, color=color, marker=marker, zorder=3)
        ax.annotate(f"{label}\n본전 승률 {y:.1f}%", (x, y), textcoords="offset points", xytext=off, color=color,
                    fontsize=9.5, fontweight="bold")
    ax.set_xlabel("손익비 (평균 이익 ÷ 평균 손실)")
    ax.set_ylabel("이 승률을 넘어야 기대값이 0 이상 (%)")
    ax.set_title("같은 익절 · 손절도 비용을 넣으면 본전 승률이 올라갑니다")
    ax.set_xlim(0.3, 3.2)
    ax.set_ylim(20, 80)
    caption(fig, "계산식 그림 · 합성 데이터 아님 · 비용 점은 2026-11-03 앱 비용 모델(코스피 · 온라인 계좌 · 슬리피지 편도 0 / 10bp 가정) · 거래 한 건 단위")
    save_svg(fig, SLUG, "breakeven-win-rate")


def main() -> None:
    apply_style()
    rm = load_example()
    fig_same_return_different_mdd(rm)
    fig_breakeven(rm)
    for p in sorted((ROOT / "public" / "learn" / "img" / SLUG).glob("*.svg")):
        print(p.relative_to(ROOT), p.stat().st_size)


if __name__ == "__main__":
    main()
