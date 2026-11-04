r"""C203 데이터셋 판과 공유 — 그림 하나 (upload-steps).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\dataset-versioning-hf.py
출력  : public/learn/img/dataset-versioning-hf/upload-steps.svg

자료  : 실제 기록 — Qurious 일일 갱신 러너가 2026-11-03 12:30 회차에 남긴 단계별 소요 시간(초).
        파일은 data/collector/state/daily_update_last.json(이 PC · git 에 올리지 않음)이고, 아래 값은 거기서
        옮겨 적은 것이다. 한 PC 의 한 회차일 뿐이라 일반화하지 않는다.
"""
from __future__ import annotations

import os
from pathlib import Path

from _style import COLORS, apply_style, caption, new_fig, save_svg

SLUG = "dataset-versioning-hf"
STEPS = [("내보내기\n(바뀐 표 → 파케이)", 275.2, "gray"), ("대조\n(행 수 · 지문 · 값)", 46.2, "gray"),
         ("올리기\n(시세, 바뀐 조각만)", 23.6, "blue"), ("일봉 올리기", 65.8, "blue"), ("일지 올리기\n(새 파일만)", 8.3, "blue")]


def upload_steps() -> None:
    apply_style()
    fig, ax = new_fig(figsize=(8.4, 4.0))
    ax.grid(axis="y", visible=False)
    names = [s[0] for s in STEPS][::-1]
    vals = [s[1] for s in STEPS][::-1]
    cols = [COLORS[s[2]] for s in STEPS][::-1]
    bars = ax.barh(names, vals, color=cols, height=0.55)
    ax.set_xlim(0, 360)
    ax.set_xlabel("걸린 시간 (초)")
    for b, v in zip(bars, vals):
        ax.text(v + 4, b.get_y() + b.get_height() / 2, f"{v:g}초", va="center", fontsize=10.5, color=COLORS["ink"])
    ax.set_title("한 회차에서 올리기보다 내보내기가 더 오래 걸렸습니다")
    caption(fig, "실제 기록 · Qurious 일일 갱신 러너 2026-11-03 12:30 회차 · 한 PC 의 한 회차이므로 일반화하지 않음 · 파란 막대 = 올리기, 회색 = 준비")
    preview = os.environ.get("LEARNFIG_PNG")
    if preview:
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(Path(preview) / f"{SLUG}-upload-steps.png", dpi=110)
    save_svg(fig, SLUG, "upload-steps")


if __name__ == "__main__":
    upload_steps()
