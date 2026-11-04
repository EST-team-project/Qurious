r"""C207 여러 시장의 데이터 — 그림 하나 (kst-day).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\multi-market-registry.py
출력  : public/learn/img/multi-market-registry/kst-day.svg

자료  : 공식 시간표를 한국 시각 축에 옮겨 그린 도식(시세가 아니다). 기준일 2026-11-03.
        - 한국 정규장 09:00~15:30 : KRX 규정 화면(직접 열람)
        - 미국 정규장 09:30~16:00(뉴욕) : NYSE 안내(직접 열람). 한국 시각은 서머타임(UTC-4) 중 22:30~05:00,
          표준시(UTC-5) 중 23:30~06:00 — 규칙(미국 서머타임 3월 둘째 일요일~11월 첫째 일요일)과 UTC 오프셋으로 계산
        - 코인(바이낸스 · 업비트) 24시간 : 일봉 경계는 UTC 00:00 = 한국 09:00 (업비트 문서에서 직접 확인, 바이낸스는 기본 시간대 UTC)
"""
from __future__ import annotations

import os
from pathlib import Path

from _style import COLORS, apply_style, caption, new_fig, save_svg

SLUG = "multi-market-registry"


def kst_day() -> None:
    apply_style()
    fig, ax = new_fig(figsize=(8.8, 4.1))
    ax.grid(axis="y", visible=False)
    rows = [  # (이름, [(시작시, 길이)], 색)
        ("한국 정규장", [(9.0, 6.5)], "blue"),
        ("미국 정규장\n(서머타임 중)", [(22.5, 1.5), (0.0, 5.0)], "orange"),
        ("미국 정규장\n(표준시 중)", [(23.5, 0.5), (0.0, 6.0)], "purple"),
        ("코인 24시간", [(0.0, 24.0)], "green"),
    ]
    for i, (name, spans, col) in enumerate(rows[::-1]):
        ax.broken_barh(spans, (i - 0.3, 0.6), facecolors=COLORS[col], edgecolor="white")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows[::-1]])
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 3))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 25, 3)])
    ax.axvline(9.0, color=COLORS["red"], linestyle="--", linewidth=1.4)
    ax.text(9.3, 4.4, "09:00 KST = UTC 00:00\n코인 일봉이 바뀌는 시각", fontsize=9.5, color=COLORS["red"], va="top")
    ax.set_ylim(-0.6, 4.5)
    ax.set_xlabel("한국 시각 (하루)")
    ax.set_title("같은 한국의 하루에 세 시장의 「하루」 가 걸쳐 있습니다")
    caption(fig, "공식 시간표를 한국 시각 축에 옮겨 그린 도식 · 기준일 2026-11-03 · 시세 데이터가 아님 · 미국 구간은 자정을 넘어 이어짐(왼쪽 끝과 오른쪽 끝)")
    preview = os.environ.get("LEARNFIG_PNG")
    if preview:
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(Path(preview) / f"{SLUG}-kst-day.png", dpi=110)
    save_svg(fig, SLUG, "kst-day")


if __name__ == "__main__":
    kst_day()
