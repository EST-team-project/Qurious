r"""C208 「현재가」는 언제 값인가 — 그림 하나 (delay-gap).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\quote-now-realtime.py
출력  : public/learn/img/quote-now-realtime/delay-gap.svg

자료  : 합성 데이터 — 시드 11 의 난수 걸음으로 만든 가상 가격(실제 종목 · 실제 시세가 아니다). 실제 시세는 재배포 제한이 있어 쓰지 않는다.
        같은 선을 20분 늦춰 그려 「지연 시세」 가 화면에서 어떻게 보이는지 보인다.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from _style import COLORS, apply_style, caption, new_fig, save_svg

SLUG = "quote-now-realtime"
SEED, DELAY_MIN = 11, 20


def delay_gap() -> None:
    rng = np.random.default_rng(SEED)
    minutes = np.arange(0, 181)                                   # 09:00 ~ 12:00, 1분 간격
    price = 100 + np.cumsum(rng.normal(0, 0.35, minutes.size))    # 가상 가격
    delayed = np.concatenate([np.full(DELAY_MIN, np.nan), price[:-DELAY_MIN]])

    # 지연 때문에 격차가 가장 큰 분을 찾는다
    gap = np.abs(price - delayed)
    k = int(np.nanargmax(gap))

    apply_style()
    fig, ax = new_fig(figsize=(8.6, 4.3))
    ax.plot(minutes, price, color=COLORS["blue"], label="그 순간의 값(합성)")
    ax.plot(minutes, delayed, color=COLORS["orange"], linestyle="--", label=f"{DELAY_MIN}분 지연 시세로 보이는 값")
    ax.annotate("", xy=(k, price[k]), xytext=(k, delayed[k]), arrowprops=dict(arrowstyle="<->", color=COLORS["red"], lw=1.6))
    ax.text(k + 3, (price[k] + delayed[k]) / 2, f"가장 벌어진 곳\n{gap[k]:.1f} 차이", color=COLORS["red"], fontsize=10, va="center")
    ax.set_xticks(range(0, 181, 30))
    ax.set_xticklabels([f"{9 + m // 60:02d}:{m % 60:02d}" for m in range(0, 181, 30)])
    ax.set_xlabel("시각 (합성)")
    ax.set_ylabel("가격 (가상)")
    ax.legend(loc="upper left")
    ax.set_title("지연 시세는 같은 선을 20분 늦게 보는 것입니다")
    caption(fig, f"합성 데이터 · 시드 {SEED} · 난수 걸음으로 만든 가상 가격이며 실제 종목 · 시세가 아님 · 주황 점선 = 파랑 선을 {DELAY_MIN}분 늦춘 것")
    preview = os.environ.get("LEARNFIG_PNG")
    if preview:
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(Path(preview) / f"{SLUG}-delay-gap.png", dpi=110)
    save_svg(fig, SLUG, "delay-gap")


if __name__ == "__main__":
    delay_gap()
