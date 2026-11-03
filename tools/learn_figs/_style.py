r"""학습 장 그림 공통 스타일 — matplotlib SVG (S196 · 2026-11-03).

쓰는 법 (장마다 스크립트에서):
    from _style import apply_style, new_fig, save_svg, COLORS, caption
    apply_style()
    fig, ax = new_fig()
    ...
    save_svg(fig, "slug", "이름")      # → public/learn/img/slug/이름.svg

실행: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\<slug>.py
(matplotlib 은 시험용 가상환경이 아니라 별도 가상환경 learnfig 에만 있다 — 잠금 파일 밖 패키지가 시험 환경을 흐리지 않게.)

같은 입력이면 같은 바이트가 나오게 한다(글자는 도형으로 · 날짜 메타 없음 · 해시 소금 고정).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[2]
IMG_DIR = ROOT / "public" / "learn" / "img"

#: 색각 이상에 안전한 팔레트 — 색에만 기대지 않고 선 모양 · 직접 라벨을 함께 쓴다.
COLORS = {
    "blue": "#2563eb", "orange": "#d97706", "green": "#059669", "purple": "#7c3aed",
    "gray": "#6b7280", "red": "#dc2626", "ink": "#111827", "grid": "#e5e7eb",
}


def _pick_font() -> str:
    names = {f.name for f in font_manager.fontManager.ttflist}
    for cand in ("Malgun Gothic", "Noto Sans KR", "NanumGothic", "Gulim"):
        if cand in names:
            return cand
    return "DejaVu Sans"        # 한글이 네모로 나온다 — 결과 보고에 적을 것


def apply_style() -> None:
    plt.rcParams.update({
        "font.family": _pick_font(),
        "axes.unicode_minus": False,
        "svg.fonttype": "path",                 # 글자를 도형으로 — 어느 PC 에서나 같게 보인다
        "svg.hashsalt": "qurious-learn-figs",   # 같은 입력 → 같은 바이트
        "figure.facecolor": "white", "axes.facecolor": "white",
        "axes.edgecolor": COLORS["gray"], "axes.labelcolor": COLORS["ink"],
        "xtick.color": COLORS["ink"], "ytick.color": COLORS["ink"],
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": COLORS["grid"], "grid.linewidth": 0.8,
        "lines.linewidth": 2, "font.size": 11, "axes.titlesize": 13, "axes.titleweight": "bold",
        "legend.frameon": False,
    })


def new_fig(figsize=(8.4, 4.4), **kw):
    fig, ax = plt.subplots(figsize=figsize, **kw)
    return fig, ax


def caption(fig, text: str) -> None:
    """그림 아래 작은 글씨 — 데이터 출처 · 기준일 · 「합성 데이터」 표시를 그림 안에 남긴다."""
    fig.text(0.01, 0.005, text, ha="left", va="bottom", fontsize=8.5, color=COLORS["gray"])


def save_svg(fig, slug: str, name: str) -> Path:
    out_dir = IMG_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.svg"
    fig.tight_layout(rect=(0, 0.04, 1, 1))     # 맨 아래 캡션 자리를 남긴다
    fig.savefig(path, format="svg", metadata={"Date": None})
    plt.close(fig)
    return path
