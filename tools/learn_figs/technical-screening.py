r"""C908 기술적 스크리닝 — 그림 하나 (alignment).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\technical-screening.py
출력  : public/learn/img/technical-screening/alignment.svg

자료  : 합성 데이터 — 시드 3 의 난수 걸음으로 만든 300일 가상 가격(`public/learn/examples/technical_screening.py` 와 같은 경로).
        실제 종목 · 실제 시세가 아니며, 음영은 「5일 > 20일 > 60일 > 120일」 순서로 놓인 날이다(정배열의 기간 조합은 규정이 아니라 관행).
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from _style import COLORS, apply_style, caption, new_fig, save_svg

SLUG = "technical-screening"


def sma(c: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(c), np.nan)
    cs = np.cumsum(np.insert(c, 0, 0.0))
    out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def alignment() -> None:
    rng = np.random.default_rng(3)
    c = 100 * np.cumprod(1 + rng.normal(0.0008, 0.012, 300))
    x = np.arange(300)
    ma = {k: sma(c, k) for k in (5, 20, 60, 120)}
    ok = (ma[5] > ma[20]) & (ma[20] > ma[60]) & (ma[60] > ma[120])
    assert int(ok.sum()) == 106                                    # 예제 출력과 같다

    apply_style()
    fig, ax = new_fig(figsize=(8.8, 4.4))
    # 정배열인 날을 연속 구간으로 묶어 음영
    start = None
    for i, v in enumerate(list(ok) + [False]):
        if v and start is None:
            start = i
        if not v and start is not None:
            ax.axvspan(start - 0.5, i - 0.5, color=COLORS["green"], alpha=0.14, lw=0)
            start = None
    ax.plot(x, c, color=COLORS["ink"], linewidth=1.2, label="가상 종가")
    for k, col, ls in [(5, "blue", "-"), (20, "orange", "--"), (60, "purple", "-."), (120, "gray", ":")]:
        ax.plot(x, ma[k], color=COLORS[col], linestyle=ls, linewidth=1.8, label=f"{k}일 이동평균")
    ax.set_xlabel("거래일 (합성, 1~300번째 날)")
    ax.set_ylabel("가격 (가상)")
    ax.legend(loc="upper left", ncol=3, fontsize=9.5)
    ax.set_title("연한 초록 음영 = 정배열(5 > 20 > 60 > 120)인 날")
    caption(fig, "합성 데이터 · 시드 3 · 가상 가격이며 실제 종목 · 시세가 아님 · 정배열의 기간 조합은 규정이 아니라 관행 · 음영은 106일 / 판정 가능 181일")
    preview = os.environ.get("LEARNFIG_PNG")
    if preview:
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(Path(preview) / f"{SLUG}-alignment.png", dpi=110)
    save_svg(fig, SLUG, "alignment")


if __name__ == "__main__":
    alignment()
