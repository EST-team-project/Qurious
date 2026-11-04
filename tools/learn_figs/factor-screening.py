r"""C906 팩터 스크리닝 — 그림 하나 (survivorship).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\factor-screening.py
출력  : public/learn/img/factor-screening/survivorship.svg

자료  : 합성 데이터 — 시드 5 의 난수로 만든 200개 가상 종목 · 750일(일 수익률 정규, 평균 0.0003 · 표준편차 0.02). 누적 −50% 에 닿으면 폐지로 보고 폐지 시점의 값에서 멈춘다.
        실제 종목 · 실제 시세가 아니며, 같은 규칙을 `public/learn/examples/factor_screening.py` 가 출력으로 보인다.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from _style import COLORS, apply_style, caption, new_fig, save_svg

SLUG = "factor-screening"


def survivorship() -> None:
    rng = np.random.default_rng(5)
    n, days = 200, 750
    path = np.cumprod(1 + rng.normal(0.0003, 0.02, (days, n)), axis=0)
    hit = path <= 0.5
    delisted = hit.any(axis=0)
    first = np.where(delisted, hit.argmax(axis=0), days - 1)
    final = path[first, np.arange(n)]
    all_mean, surv_mean, n_del = float(final.mean()), float(final[~delisted].mean()), int(delisted.sum())

    apply_style()
    fig, ax = new_fig(figsize=(8.0, 4.2))
    ax.grid(axis="x", visible=False)
    labels = [f"폐지 종목까지 포함\n(200종목)", f"살아남은 종목만\n({n - n_del}종목)"]
    bars = ax.bar(labels, [all_mean, surv_mean], color=[COLORS["blue"], COLORS["orange"]], width=0.5)
    bars[1].set_hatch("//")
    bars[1].set_edgecolor("white")
    ax.axhline(1.0, color=COLORS["gray"], linestyle="--", linewidth=1.2)
    ax.text(1.42, 1.01, "시작 = 1", color=COLORS["gray"], fontsize=9.5, ha="right", va="bottom")
    for b, v in zip(bars, [all_mean, surv_mean]):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.01, f"{v:.3f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.set_ylim(0.9, 1.6)
    ax.set_ylabel("평균 최종 배수 (시작 = 1)")
    ax.set_title("폐지된 종목을 빼면 평균이 부풀려 보입니다")
    caption(fig, f"합성 데이터 · 시드 5 · 200개 가상 종목 750일 · 누적 -50% 에 닿으면 폐지(이 실험에서 {n_del}종목) · 실제 종목 · 시세가 아님")
    preview = os.environ.get("LEARNFIG_PNG")
    if preview:
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(Path(preview) / f"{SLUG}-survivorship.png", dpi=110)
    save_svg(fig, SLUG, "survivorship")


if __name__ == "__main__":
    survivorship()
