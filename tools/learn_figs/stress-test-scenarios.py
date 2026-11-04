r"""C910 스트레스 검증 — 그림 하나 (bond-curve).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\stress-test-scenarios.py
출력  : public/learn/img/stress-test-scenarios/bond-curve.svg

자료  : 합성 계산 — 듀레이션 5 · 볼록성 40 은 예시로 정한 값이다(실제 채권이 아니다). 근사식 ΔP/P ≈ -D·Δy + ½·C·(Δy)² 로 금리 변화 -2%p ~ +3%p 구간을 그렸다.
        근사식은 채권 교재의 표준식이며 이번 조사에서 교재 원문은 열람하지 않았다.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from _style import COLORS, apply_style, caption, new_fig, save_svg

SLUG = "stress-test-scenarios"
D, C = 5.0, 40.0


def bond_curve() -> None:
    dy = np.linspace(-0.02, 0.03, 201)
    dur_only = -D * dy
    dur_conv = -D * dy + 0.5 * C * dy ** 2

    apply_style()
    fig, ax = new_fig(figsize=(8.4, 4.4))
    ax.plot(dy * 100, dur_only * 100, color=COLORS["gray"], linestyle="--", label="듀레이션만 쓴 직선 근사")
    ax.plot(dy * 100, dur_conv * 100, color=COLORS["blue"], label="듀레이션 + 볼록성 근사")
    ax.axhline(0, color=COLORS["gray"], linewidth=0.8)
    ax.axvline(0, color=COLORS["gray"], linewidth=0.8)
    for x, txt, dyv, off in [(1.0, "금리 +1%p\n-4.80%", 0.01, (-30, -42)), (3.0, "금리 +3%p\n-13.20%", 0.03, (-14, 22))]:
        y = (-D * dyv + 0.5 * C * dyv ** 2) * 100
        ax.plot([x], [y], "o", color=COLORS["red"])
        ax.annotate(txt, (x, y), textcoords="offset points", xytext=off, fontsize=9.5, color=COLORS["red"],
                    arrowprops=dict(arrowstyle="-", color=COLORS["red"], lw=0.8))
    ax.set_xlim(-2.3, 3.4)
    ax.set_xlabel("금리 변화 (%p)")
    ax.set_ylabel("채권 가격 변화 (%)")
    ax.legend(loc="upper right")
    ax.set_title("금리가 오르면 듀레이션만큼 가격이 떨어지고, 볼록성이 그 폭을 조금 줄입니다")
    caption(fig, "합성 계산 · 듀레이션 5 · 볼록성 40 은 예시 값 · 근사식 ΔP/P = -D·Δy + ½·C·(Δy)² (근사) · 실제 채권이 아님")
    preview = os.environ.get("LEARNFIG_PNG")
    if preview:
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(Path(preview) / f"{SLUG}-bond-curve.png", dpi=110)
    save_svg(fig, SLUG, "bond-curve")


if __name__ == "__main__":
    bond_curve()
