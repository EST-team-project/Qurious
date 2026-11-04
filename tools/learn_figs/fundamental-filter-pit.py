r"""C907 재무 필터와 공시일 기준 — 그림 하나 (visible-eps).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\fundamental-filter-pit.py
출력  : public/learn/img/fundamental-filter-pit/visible-eps.svg

자료  : 합성 데이터 — 결산일 · 접수일 · EPS 는 손으로 정한 값이다(실제 종목 · 실제 공시 아님). `public/learn/examples/pit_financials.py` 와 같은 규칙으로 계산했다.
        2023 결산 EPS 1000(2024-03-20 접수) → 800(2024-04-10 정정), 2024 결산 EPS 1200(2025-03-19 접수).
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from _style import COLORS, apply_style, caption, new_fig, save_svg

SLUG = "fundamental-filter-pit"
D = dt.date.fromisoformat
FILINGS = [(D("2023-12-31"), D("2024-03-20"), 1000), (D("2023-12-31"), D("2024-04-10"), 800), (D("2024-12-31"), D("2025-03-19"), 1200)]


def visible(a: dt.date):
    seen = {}
    for p, k, e in sorted(FILINGS, key=lambda x: x[1]):
        if k < a:
            seen[p] = e
    return seen[max(seen)] if seen else None


def leaky(a: dt.date):
    ok = [f for f in FILINGS if f[0] < a]
    if not ok:
        return None
    p = max(f[0] for f in ok)
    return sorted((f for f in ok if f[0] == p), key=lambda x: x[1])[-1][2]


def visible_eps() -> None:
    days = [D("2024-01-01") + dt.timedelta(days=i) for i in range(0, 540)]
    a = [visible(d) for d in days]
    b = [leaky(d) for d in days]

    apply_style()
    fig, ax = new_fig(figsize=(8.8, 4.4))
    nan = float("nan")
    ax.step(days, [nan if v is None else v for v in b], where="post", color=COLORS["red"], linestyle="--", linewidth=2, label="결산일을 공시일로 착각한 값(잘못)")
    ax.step(days, [nan if v is None else v for v in a], where="post", color=COLORS["blue"], linewidth=2.4, label="그날까지 접수된 판만 쓴 값(맞음)")
    for d, txt, ha, y in [(D("2024-03-20"), "원본 접수\nEPS 1000 ", "right", 1330), (D("2024-04-10"), " 정정 접수\nEPS 800", "left", 1260),
                          (D("2025-03-19"), "2024 결산 접수\nEPS 1200", "center", 1330)]:
        ax.axvline(d, color=COLORS["gray"], linestyle=":", linewidth=1.1)
        ax.text(d, y, txt, fontsize=9, color=COLORS["gray"], ha=ha, va="bottom")
    ax.set_ylim(650, 1450)
    ax.set_ylabel("그날 보이는 결산 EPS (합성)")
    ax.legend(loc="lower right")
    ax.set_title("같은 결산기도 날짜에 따라 보이는 값이 달라집니다")
    caption(fig, "합성 데이터 · 결산일 · 접수일 · EPS 는 손으로 정한 값이며 실제 종목 · 실제 공시가 아님 · 접수 당일은 쓰지 않고 다음 날부터 반영")
    preview = os.environ.get("LEARNFIG_PNG")
    if preview:
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(Path(preview) / f"{SLUG}-visible-eps.png", dpi=110)
    save_svg(fig, SLUG, "visible-eps")


if __name__ == "__main__":
    visible_eps()
