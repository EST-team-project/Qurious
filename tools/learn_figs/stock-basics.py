r"""F.1 주식 · 시장 · 주문의 기본 — 그림 둘 (day-timeline · tick-ratio).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\stock_basics.py
출력  : public/learn/img/stock-basics/day-timeline.svg · tick-ratio.svg

자료  : day-timeline — 한국거래소 KRX 규정/제도 「매매거래제도일반」 거래시간표와 특례 시간(2026-11-03 열람),
        NXT 홈페이지 표기(2026-11-03). KRX 애프터마켓 시작일(2026-09-14)은 보도 기준이라 그림에 표시한다.
        tick-ratio — KRX 호가가격단위 표(2026-11-03 열람)로 직접 계산. 난수 · 외부 자료 없음.
"""
from __future__ import annotations

import numpy as np
from matplotlib.patches import Rectangle

import os
from pathlib import Path

from _style import COLORS, apply_style, caption, new_fig, save_svg

SLUG = "stock-basics"


def save(fig, name: str) -> None:
    """SVG 로 저장한다. 환경변수 LEARNFIG_PNG 에 폴더를 주면 눈으로 볼 PNG 도 그 폴더에 남긴다(저장소 밖)."""
    preview = os.environ.get("LEARNFIG_PNG")
    if preview:
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(Path(preview) / f"{SLUG}-{name}.png", dpi=110)
    save_svg(fig, SLUG, name)


def hm(h: int, m: int, s: int = 0) -> float:
    return h + m / 60 + s / 3600


def day_timeline() -> None:
    fig, ax = new_fig(figsize=(8.4, 4.3))
    ax.grid(False)
    ax.set_axisbelow(True)
    # (줄 이름, [(시작, 끝, 안쪽 글, 색, 무늬)])
    rows = [
        ("NXT", [
            (hm(8, 0), hm(8, 50), "프리", COLORS["purple"], ""),
            (hm(9, 0, 30), hm(15, 20), "메인", COLORS["purple"], ""),
            (hm(15, 40), hm(20, 0), "애프터", COLORS["purple"], ""),
        ]),
        ("KRX 애프터마켓*", [(hm(16, 0), hm(20, 0), "접속매매 16:00~20:00", COLORS["orange"], "")]),
        ("KRX 시간외종가", [
            (hm(8, 30), hm(8, 40), "", COLORS["green"], ""),
            (hm(15, 40), hm(16, 0), "", COLORS["green"], ""),
        ]),
        ("KRX 정규장", [
            (hm(8, 30), hm(9, 0), "", COLORS["gray"], "///"),
            (hm(9, 0), hm(15, 20), "접속매매 09:00~15:30", COLORS["blue"], ""),
            (hm(15, 20), hm(15, 30), "", COLORS["red"], ""),
        ]),
    ]
    h = 0.52
    for i, (name, bars) in enumerate(rows):
        y = i
        for a, b, text, color, hatch in bars:
            ax.add_patch(Rectangle((a, y - h / 2), b - a, h, facecolor=color if not hatch else "white",
                                   edgecolor=color, hatch=hatch, linewidth=1.2, alpha=0.95))
            if text:
                ax.text((a + b) / 2, y, text, ha="center", va="center", color="white", fontsize=9.5, fontweight="bold")
    # 좁은 막대는 위에 시간을 적는다
    ax.text(hm(8, 30) + 0.04, 2 + h / 2 + 0.07, "08:30~08:40", fontsize=8.5, color=COLORS["green"], ha="left")
    ax.text(hm(15, 40) - 0.05, 2 + h / 2 + 0.07, "15:40~16:00", fontsize=8.5, color=COLORS["green"], ha="center")
    ax.text(hm(8, 30), 3 + h / 2 + 0.07, "시가 동시호가 08:30~09:00", fontsize=8.5, color=COLORS["gray"], ha="left")
    ax.text(hm(15, 30) + 0.02, 3 + h / 2 + 0.07, "종가 단일가 15:20~15:30", fontsize=8.5, color=COLORS["red"], ha="right")
    ax.text(hm(8, 25), 0 + h / 2 + 0.07, "프리 08:00~08:50", fontsize=8.5, color=COLORS["purple"], ha="left")
    ax.text(hm(18, 0), 0 + h / 2 + 0.07, "애프터 15:40~20:00", fontsize=8.5, color=COLORS["purple"], ha="center")
    ax.text(hm(12, 30), 0 + h / 2 + 0.07, "메인 09:00:30~15:20", fontsize=8.5, color=COLORS["purple"], ha="center")
    ax.set_xlim(7.8, 20.2)
    ax.set_ylim(-0.6, 3.95)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows])
    ax.set_xticks(range(8, 21), [f"{x}시" for x in range(8, 21)])
    ax.tick_params(axis="x", labelsize=9)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.set_title("하루 안의 거래 시간 (평일 · 한국 시간)")
    caption(fig, "출처 KRX 규정 · NXT 홈페이지 표기(2026-11-03 열람) · *애프터마켓 시작일(2026-09-14)은 보도 기준 · 사선 = 호가만 받는 동시호가")
    save(fig, "day-timeline")


# 주권 호가가격단위 — (가격대 시작, 끝, 단위)
BANDS = [(1_000, 2_000, 1), (2_000, 5_000, 5), (5_000, 20_000, 10), (20_000, 50_000, 50),
         (50_000, 200_000, 100), (200_000, 500_000, 500), (500_000, 1_000_000, 1_000)]


def tick_ratio() -> None:
    fig, ax = new_fig(figsize=(8.4, 4.4))
    for lo, hi, tick in BANDS:
        p = np.unique(np.round(np.geomspace(lo, hi - tick, 260) / tick) * tick)
        ax.plot(p, tick / p * 100, color=COLORS["blue"], linewidth=2)
        mid = np.sqrt(lo * hi)
        ax.text(mid, 0.285, f"{tick:,}원", ha="center", va="bottom", fontsize=9.5, color=COLORS["ink"])
        if lo > 1_000:
            ax.axvline(lo, color=COLORS["gray"], linestyle=":", linewidth=1)
    ax.set_xscale("log")
    ax.set_xlim(1_000, 1_000_000)
    ax.set_ylim(0, 0.32)
    ticks = [1_000, 2_000, 5_000, 20_000, 50_000, 200_000, 500_000, 1_000_000]
    ax.set_xticks(ticks, [f"{t:,}" for t in ticks], fontsize=8.5)
    ax.minorticks_off()
    ax.set_xlabel("주가 (원, 로그 눈금)")
    ax.set_ylabel("호가단위 ÷ 가격 (%)")
    ax.set_title("가격이 구간 경계를 넘으면 한 칸의 크기가 갑자기 커집니다")
    ax.text(5_600, 0.012, "예) 1,999원 → 2,000원: 호가단위 1원 → 5원, 비율 0.050% → 0.250%", fontsize=9, color=COLORS["ink"])
    caption(fig, "출처 KRX 호가가격단위 표(2026-11-03 열람)로 직접 계산 · 위쪽 숫자는 구간별 호가단위 · 실제 시세 아님")
    save(fig, "tick-ratio")


if __name__ == "__main__":
    apply_style()
    day_timeline()
    tick_ratio()
    print("완료: public/learn/img/stock-basics/day-timeline.svg · tick-ratio.svg")
