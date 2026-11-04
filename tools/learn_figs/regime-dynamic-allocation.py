r"""C905 시장 국면과 동적 자산배분 — 그림 하나 (regime-shift).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\regime-dynamic-allocation.py
출력  : public/learn/img/regime-dynamic-allocation/regime-shift.svg

자료  : 합성 예시 — 기준 비중(국내주식 30 · 해외주식 30 · 국내채권 25 · 대체자산 10 · 현금 5)은 손으로 정한 값이다.
        국면 배수(1.1 / 0.5)와 자금 이동 규칙(줄일 때 채권 70% · 현금 30%)은 Qurious 앱의 명시적 규칙을 손으로 푼 것이며
        연구가 정해 준 값이 아니다. 실제 시세 · 실제 계좌가 아니다.
"""
from __future__ import annotations

import os
from pathlib import Path

from _style import COLORS, apply_style, caption, new_fig, save_svg

SLUG = "regime-dynamic-allocation"
ASSETS = ["국내주식", "해외주식", "국내채권", "대체자산", "현금"]
BARS = {
    "기준": [30, 30, 25, 10, 5],
    "상승 · 저변동\n(주식 ×1.1)": [33, 33, 20, 10, 4],
    "하락 · 고변동\n(주식 ×0.5)": [15, 15, 46, 10, 14],
}
STYLE = [("blue", None), ("blue", "//"), ("green", None), ("orange", None), ("gray", None)]   # 색 + 빗금(색에만 의존하지 않음)


def regime_shift() -> None:
    assert all(abs(sum(v) - 100) < 1e-9 for v in BARS.values())
    apply_style()
    fig, ax = new_fig(figsize=(8.4, 4.4))
    ax.grid(axis="x", visible=False)
    names = list(BARS)
    bottoms = [0.0] * len(names)
    for i, asset in enumerate(ASSETS):
        col, hatch = STYLE[i]
        vals = [BARS[n][i] for n in names]
        ax.bar(names, vals, bottom=bottoms, color=COLORS[col], hatch=hatch, edgecolor="white", width=0.55, label=asset)
        for j, v in enumerate(vals):
            ax.text(j, bottoms[j] + v / 2, f"{v:g}", ha="center", va="center", color="white", fontsize=10, fontweight="bold")
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    ax.set_ylim(0, 100)
    ax.set_ylabel("비중 (%)")
    ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5))
    ax.set_title("국면이 바뀌면 주식 비중이 줄어든 만큼 채권 · 현금이 늘어납니다")
    caption(fig, "합성 예시 · 기준 비중은 손으로 정한 값 · 배수와 이동 규칙은 Qurious 앱의 명시적 규칙을 손으로 푼 것(연구가 정한 값 아님) · 실제 계좌 아님")
    preview = os.environ.get("LEARNFIG_PNG")
    if preview:
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(Path(preview) / f"{SLUG}-regime-shift.png", dpi=110, bbox_inches="tight")
    save_svg(fig, SLUG, "regime-shift")


if __name__ == "__main__":
    regime_shift()
