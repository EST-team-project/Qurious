r"""C205 거래일 달력 — 그림 하나 (holidays-by-month).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\trading-calendar.py
출력  : public/learn/img/trading-calendar/holidays-by-month.svg

자료  : 공식 표 — 한국거래소(KRX) 「증시일정 > 휴장일」 화면의 2026 · 2027 평일 휴장일(2026-11-03 열람)을 월별로 센 것.
        시세 데이터가 아니다. 휴장일은 거래소가 바꿀 수 있으니 실제로는 공식 화면을 확인한다.
"""
from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import numpy as np

from _style import COLORS, apply_style, caption, new_fig, save_svg

SLUG = "trading-calendar"

# (월, 일) — 평일 휴장일만. 2026: 17일 · 2027: 16일 (KRX 표 2026-11-03 열람)
H2026 = [(1, 1), (2, 16), (2, 17), (2, 18), (3, 2), (5, 1), (5, 5), (5, 25), (6, 3), (7, 17), (8, 17), (9, 24), (9, 25),
         (10, 5), (10, 9), (12, 25), (12, 31)]
H2027 = [(1, 1), (2, 8), (2, 9), (3, 1), (5, 3), (5, 5), (5, 13), (7, 19), (8, 16), (9, 14), (9, 15), (9, 16), (10, 4),
         (10, 11), (12, 27), (12, 31)]


def holidays_by_month() -> None:
    assert len(H2026) == 17 and len(H2027) == 16
    c26 = Counter(m for m, _ in H2026)
    c27 = Counter(m for m, _ in H2027)
    months = np.arange(1, 13)
    v26 = [c26.get(m, 0) for m in months]
    v27 = [c27.get(m, 0) for m in months]

    apply_style()
    fig, ax = new_fig(figsize=(8.4, 4.2))
    w = 0.38
    b1 = ax.bar(months - w / 2, v26, w, color=COLORS["blue"], label="2026년 (17일)")
    b2 = ax.bar(months + w / 2, v27, w, color=COLORS["orange"], hatch="//", edgecolor="white", label="2027년 (16일)")
    ax.set_xticks(months)
    ax.set_xticklabels([f"{m}월" for m in months])
    ax.set_yticks(range(0, 4))
    ax.set_ylim(0, 3.9)
    ax.set_ylabel("평일 휴장일 수")
    ax.grid(axis="x", visible=False)
    for bars in (b1, b2):
        for b in bars:
            if b.get_height() > 0:
                ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.05, f"{int(b.get_height())}", ha="center",
                        fontsize=9.5, color=COLORS["ink"])
    ax.legend(loc="upper right")
    ax.set_title("달마다 쉬는 날 수가 다릅니다 — 휴장일은 매년 달라집니다")
    caption(fig, "공식 표 · 한국거래소 증시일정>휴장일 2026-11-03 열람 · 평일 휴장일만(토·일 제외) · 연도별 막대 모양을 달리해 색에만 의존하지 않음")
    preview = os.environ.get("LEARNFIG_PNG")
    if preview:
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(Path(preview) / f"{SLUG}-holidays-by-month.png", dpi=110)
    save_svg(fig, SLUG, "holidays-by-month")


if __name__ == "__main__":
    holidays_by_month()
