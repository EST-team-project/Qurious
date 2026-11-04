r"""C206 공시 · 뉴스 수집과 이름표 — 그림 하나 (day-timeline).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\news-disclosure-collection.py
출력  : public/learn/img/news-disclosure-collection/day-timeline.svg

자료  : 공식 시간표를 그린 도식(시세 · 공시 원자료가 아니다). 기준일 2026-11-03.
        - KRX 정규장 매매 09:00~15:30, 애프터마켓 16:00~20:00 : KRX 규정 화면(직접 열람)
        - 넥스트레이드 프리 08:00~08:50 · 메인 09:00:30~15:20 · 애프터 15:40~20:00 : 넥스트레이드 시장개요(직접 열람)
        - 거래소 공시 접수 07:30~18:00 : 언론이 전한 거래소 설명(2026-09 보도) — 공식 규정 문구는 확인하지 못해 빗금으로 표시
"""
from __future__ import annotations

import os
from pathlib import Path

from _style import COLORS, apply_style, caption, new_fig, save_svg

SLUG = "news-disclosure-collection"

# (이름, [(시작시, 끝시)...], 색, 빗금)
ROWS = [
    ("거래소 공시 접수(보도)", [(7.5, 18.0)], "gray", "//"),
    ("KRX 정규장 매매", [(9.0, 15.5)], "blue", None),
    ("KRX 애프터마켓", [(16.0, 20.0)], "blue", None),
    ("넥스트레이드", [(8.0, 8 + 50 / 60), (9 + 0.5 / 60, 15 + 20 / 60), (15 + 40 / 60, 20.0)], "green", None),
]


def day_timeline() -> None:
    apply_style()
    fig, ax = new_fig(figsize=(8.8, 3.9))
    ax.grid(axis="y", visible=False)
    for i, (name, spans, col, hatch) in enumerate(ROWS[::-1]):
        ax.broken_barh([(s, e - s) for s, e in spans], (i - 0.3, 0.6), facecolors=COLORS[col],
                       edgecolor="white" if hatch else COLORS[col], hatch=hatch, alpha=0.95 if not hatch else 0.55)
    ax.set_yticks(range(len(ROWS)))
    ax.set_yticklabels([r[0] for r in ROWS[::-1]])
    ax.set_xlim(6, 22)
    ax.set_xticks(range(6, 23, 2))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(6, 23, 2)])
    ax.axvline(18.0, color=COLORS["red"], linestyle="--", linewidth=1.4)
    ax.set_ylim(-0.6, 4.4)
    ax.text(18.1, 4.3, "18:00 이후 나온 공시도 저녁 거래\n가격에 반영될 수 있음(보도)", fontsize=9.5, color=COLORS["red"], va="top")
    ax.set_xlabel("한국 시각 (하루)")
    ax.set_title("공시가 접수되는 시간과 거래되는 시간은 다릅니다")
    caption(fig, "공식 시간표를 그린 도식 · 기준일 2026-11-03 · 거래소 공시 접수 시간은 언론 인용(빗금) · 시세 · 공시 원자료가 아님")
    preview = os.environ.get("LEARNFIG_PNG")
    if preview:
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(Path(preview) / f"{SLUG}-day-timeline.png", dpi=110)
    save_svg(fig, SLUG, "day-timeline")


if __name__ == "__main__":
    day_timeline()
