r"""C204 정기 배치 — 그림 하나 (run-steps).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\batch-scheduling.py
출력  : public/learn/img/batch-scheduling/run-steps.svg

자료  : 실제 기록 — Qurious 일일 갱신 러너의 2026-11-03 12:30 회차(12:30:02 ~ 13:05:56) 단계별 소요 시간(초) 중 큰 아홉 개.
        파일은 data/collector/state/daily_update_last.json(이 PC · git 에 올리지 않음)이고 값은 거기서 옮겨 적었다.
        한 PC 의 한 회차일 뿐이라 일반화하지 않는다.
"""
from __future__ import annotations

import os
from pathlib import Path

from _style import COLORS, apply_style, caption, new_fig, save_svg

SLUG = "batch-scheduling"
STEPS = [("일봉 받기", 659.9), ("검색 색인", 514.2), ("벤치마크", 286.7), ("내보내기", 275.2), ("총수익", 190.0),
         ("언론사 기사", 151.1), ("수정주가", 143.0), ("일봉 올리기", 65.8), ("신호 전체", 64.3)]


def run_steps() -> None:
    apply_style()
    fig, ax = new_fig(figsize=(8.4, 4.6))
    ax.grid(axis="y", visible=False)
    names = [s[0] for s in STEPS][::-1]
    secs = [s[1] / 60 for s in STEPS][::-1]
    bars = ax.barh(names, secs, color=COLORS["blue"], height=0.6)
    ax.set_xlim(0, 13.5)
    ax.set_xlabel("걸린 시간 (분)")
    for b, v in zip(bars, secs):
        ax.text(v + 0.15, b.get_y() + b.get_height() / 2, f"{v:.1f}분", va="center", fontsize=10.5, color=COLORS["ink"])
    ax.set_title("한 회차 안에서도 단계마다 걸리는 시간이 크게 다릅니다")
    caption(fig, "실제 기록 · Qurious 일일 갱신 러너 2026-11-03 12:30 회차(시작~끝 약 36분)의 큰 단계 9개 · 한 PC 의 한 회차이므로 일반화하지 않음")
    preview = os.environ.get("LEARNFIG_PNG")
    if preview:
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(Path(preview) / f"{SLUG}-run-steps.png", dpi=110)
    save_svg(fig, SLUG, "run-steps")


if __name__ == "__main__":
    run_steps()
