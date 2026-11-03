r"""F.2 배당 기준일 · 배당락일 · 지급일 — 그림 둘 (year-end-calendar · ex-date-concept).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\dividend-dates.py
출력  : public/learn/img/dividend-dates/year-end-calendar.svg · ex-date-concept.svg

자료  : year-end-calendar — 거래소 규정(12월 31일 휴장)과 T+2 결제 규칙을 달력에 적용한 계산 결과.
        휴장일은 12-25 · 12-31 · 2027-01-01 을 가정했다(실제는 거래소 공지).
        ex-date-concept — 합성 데이터(시드 42). 실제 종목이 아니라 개념 설명용이다.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter

from _style import COLORS, apply_style, caption, new_fig, save_svg

SLUG = "dividend-dates"
WEEKDAY = "월화수목금토일"


def save(fig, name: str) -> None:
    """SVG 로 저장한다. 환경변수 LEARNFIG_PNG 에 폴더를 주면 눈으로 볼 PNG 도 그 폴더에 남긴다(저장소 밖)."""
    preview = os.environ.get("LEARNFIG_PNG")
    if preview:
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(Path(preview) / f"{SLUG}-{name}.png", dpi=110)
    save_svg(fig, SLUG, name)


def year_end_calendar() -> None:
    holidays = {date(2026, 12, 25), date(2026, 12, 31), date(2027, 1, 1)}
    days = [date(2026, 12, 21) + timedelta(days=i) for i in range(15)]          # 12-21 ~ 2027-01-04
    fig, ax = new_fig(figsize=(8.4, 4.4))
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])
    cw, ch, y0 = 1.0, 1.25, 1.2
    special = {
        date(2026, 12, 28): (COLORS["blue"], "마지막\n매수일"),
        date(2026, 12, 29): (COLORS["orange"], "배당락일"),
        date(2026, 12, 30): (COLORS["green"], "마지막\n거래일"),
        date(2026, 12, 31): (COLORS["red"], "기준일\n(휴장)"),
    }
    for i, d in enumerate(days):
        x = i * cw
        weekend = d.weekday() >= 5
        closed = d in holidays
        if d in special:
            color, text = special[d]
            ax.add_patch(Rectangle((x + 0.04, y0), cw - 0.08, ch, facecolor=color if d != date(2026, 12, 31) else "white",
                                   edgecolor=color, linewidth=2.5))
            ax.text(x + cw / 2, y0 + ch * 0.38, text, ha="center", va="center", fontsize=8.5, fontweight="bold",
                    color="white" if d != date(2026, 12, 31) else color)
        else:
            face = "#f3f4f6" if weekend else "white"
            ax.add_patch(Rectangle((x + 0.04, y0), cw - 0.08, ch, facecolor=face, edgecolor=COLORS["gray"], linewidth=1,
                                   hatch="///" if closed else ""))
            if closed:
                ax.text(x + cw / 2, y0 + ch * 0.38, "휴장", ha="center", va="center", fontsize=8.5, color=COLORS["gray"], fontweight="bold")
            elif weekend:
                ax.text(x + cw / 2, y0 + ch * 0.38, "주말", ha="center", va="center", fontsize=8.5, color=COLORS["gray"])
        ax.text(x + cw / 2, y0 + ch * 0.80, f"{d.month}/{d.day}", ha="center", va="center", fontsize=9.5, color=COLORS["ink"] if d not in special else (COLORS["ink"]))
        ax.text(x + cw / 2, y0 + ch + 0.12, WEEKDAY[d.weekday()], ha="center", va="bottom", fontsize=9, color=COLORS["gray"])
    idx = {d: i for i, d in enumerate(days)}
    top = y0 + ch + 0.55

    def arc(src: date, dst: date, text: str, color: str, rad: float, ty: float) -> None:
        xa, xb = idx[src] * cw + cw / 2, idx[dst] * cw + cw / 2
        ax.annotate("", xy=(xb, y0 - 0.02), xytext=(xa, y0 - 0.02),
                    arrowprops=dict(arrowstyle="-|>", color=color, lw=2, connectionstyle=f"arc3,rad={rad}"))
        ax.text((xa + xb) / 2, ty, text, ha="center", va="center", fontsize=9, color=color, fontweight="bold")

    arc(date(2026, 12, 28), date(2026, 12, 30), "12-28 매수 → 결제 12-30\n기준일 이하 → 명부에 오름", COLORS["blue"], 0.45, -0.12)
    arc(date(2026, 12, 29), date(2027, 1, 4), "12-29 매수 → 결제 1-4\n기준일 뒤 → 이번 배당 못 받음", COLORS["orange"], 0.28, -0.62)
    ax.set_xlim(-0.2, len(days) * cw + 0.2)
    ax.set_ylim(-0.95, top + 0.35)
    ax.set_title("기준일이 12월 31일(휴장)인 해의 배당 일정 (2026)")
    caption(fig, "규칙 적용 결과 · 휴장일은 12-25 · 12-31 · 1-1 가정 · 보통거래 T+2 · 2026-11-03 기준 · 바뀔 수 있음")
    save(fig, "year-end-calendar")


def ex_date_concept() -> None:
    rng = np.random.default_rng(42)
    n, ex = 12, 6                                     # 12거래일 · 일곱 번째 날이 배당락일
    div, p = 300.0, 10_000.0
    price = [p]
    for i in range(1, n):
        change = rng.normal(0, 0.004) * price[-1]
        if i == ex:
            change -= div                             # 설명용으로 배당금만큼 낮아진 채 시작하게 만들었다
        price.append(price[-1] + change)
    price = np.array(price)
    total = price + np.where(np.arange(n) >= ex, div, 0.0)       # 받은 배당을 더한 값
    x = np.arange(n)
    fig, ax = new_fig(figsize=(8.4, 4.4))
    ax.plot(x, price, color=COLORS["blue"], marker="o", label="종가")
    ax.plot(x, total, color=COLORS["orange"], linestyle="--", marker="s", markersize=5, label="종가 + 받은 배당(총수익 흐름)")
    ax.axvline(ex, color=COLORS["gray"], linestyle=":")
    ax.text(ex + 0.1, price.max(), "배당락일", color=COLORS["gray"], fontsize=9.5, ha="left")
    ax.annotate("", xy=(ex, price[ex]), xytext=(ex, price[ex - 1]),
                arrowprops=dict(arrowstyle="<->", color=COLORS["red"], lw=1.8))
    ax.text(ex + 0.3, (price[ex] + price[ex - 1]) / 2 - 40, "배당금 수준의\n가격 하락(설명용)", color=COLORS["red"], fontsize=9, ha="left", va="center")
    ax.set_xticks(x, [f"{i - ex:+d}" if i != ex else "0" for i in x])
    ax.set_xlabel("배당락일 기준 거래일 수")
    ax.set_ylabel("가격 (원, 가상)")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.legend(loc="lower left")
    ax.set_title("배당락일에 가격은 끊기고, 받은 배당을 더한 흐름은 이어집니다")
    caption(fig, "합성 데이터(시드 42) · 실제 종목이 아님 · 실제 배당락일의 하락 폭이 배당금과 꼭 같다는 뜻이 아님")
    save(fig, "ex-date-concept")


if __name__ == "__main__":
    apply_style()
    year_end_calendar()
    ex_date_concept()
    print("완료: public/learn/img/dividend-dates/year-end-calendar.svg · ex-date-concept.svg")
