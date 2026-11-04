r"""C202 공식 API 다루기 — 그림 하나 (limit-days).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\public-api-basics.py
출력  : public/learn/img/public-api-basics/limit-days.svg

자료  : 합성 계산 — 거래일 1,648 · 하루치 2,870행은 collector/sources/portal.py 주석의 실측값이고,
        하루 한도 10,000 은 collector/config.py 의 PORTAL_DAILY_LIMIT(응답 헤더 실측, 2026-09-19)이다.
        호출 방식 두 가지(날짜별 1회 · 종목×날짜별 1회)로 필요한 일수를 올림해 셈한 것으로 시뮬레이션이 아니다.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

from _style import COLORS, apply_style, caption, new_fig, save_svg

SLUG = "public-api-basics"
TRADING_DAYS, STOCKS, DAILY_LIMIT = 1648, 2870, 10_000


def limit_days() -> None:
    by_day = TRADING_DAYS
    by_stock = TRADING_DAYS * STOCKS
    days = [math.ceil(by_day / DAILY_LIMIT), math.ceil(by_stock / DAILY_LIMIT)]       # 1, 473
    labels = [f"날짜별 1회 부르기\n({by_day:,} 호출)", f"종목 × 날짜별로 부르기\n({by_stock:,} 호출)"]

    apply_style()
    fig, ax = new_fig(figsize=(8.4, 3.6))
    ax.grid(axis="y", visible=False)
    bars = ax.barh([1, 0], days, color=[COLORS["green"], COLORS["red"]], height=0.5)
    ax.set_yticks([1, 0])
    ax.set_yticklabels(labels)
    ax.set_xlim(0, 700)
    ax.set_xlabel("필요한 일수 (하루 한도 10,000 호출 기준)")
    for bar, d, txt in zip(bars, days, ["하루면 끝 (막대가 거의 안 보임)", "1년 넘게 걸림"]):
        ax.text(bar.get_width() + 6, bar.get_y() + bar.get_height() / 2, f"{d:,}일 — {txt}",
                va="center", fontsize=11, color=COLORS["ink"])
    ax.set_title("같은 한도라도 호출 설계에 따라 하루와 일 년이 갈립니다")
    caption(fig, "합성 계산 · 거래일 1,648 · 하루치 2,870행 · 하루 한도 10,000 (collector 실측값) · 필요 일수 = 호출 수 ÷ 한도, 올림")
    preview = os.environ.get("LEARNFIG_PNG")          # 눈으로 볼 PNG 를 저장소 밖 폴더에 남긴다(선택)
    if preview:
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(Path(preview) / f"{SLUG}-limit-days.png", dpi=110)
    save_svg(fig, SLUG, "limit-days")


if __name__ == "__main__":
    limit_days()
