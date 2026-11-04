r"""11.6 리스크 패리티와 최소분산 — 그림 둘 (S196 · 2026-11-03).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\risk-parity-min-variance.py
출력  : public/learn/img/risk-parity-min-variance/{weights-vs-risk,cap-effect}.svg

계산은 장의 예제 public/learn/examples/risk_parity.py 의 함수를 그대로 불러 쓴다(장의 출력과 그림이 같은 코드에서 나온다).
두 그림 모두 합성 데이터다: 네 가상 자산의 변동성 18 · 16 · 5 · 14% 와 손으로 정한 상관(난수 아님).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import matplotlib.pyplot as plt  # noqa: E402
from _style import COLORS, IMG_DIR, ROOT, apply_style, caption, new_fig  # noqa: E402

SLUG = "risk-parity-min-variance"
ASSET_COLORS = (COLORS["blue"], COLORS["orange"], COLORS["green"], COLORS["purple"])


def save_with_room(fig, name: str, bottom: float) -> None:
    """공통 save_svg 는 아래 여백이 고정(0.04)이라 그림 밖 범례 자리를 못 낸다 — 같은 저장 방식으로 여백만 달리 준다."""
    out_dir = IMG_DIR / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, bottom, 1, 1))
    fig.savefig(out_dir / f"{name}.svg", format="svg", metadata={"Date": None})
    plt.close(fig)


def load_example():
    path = ROOT / "public" / "learn" / "examples" / "risk_parity.py"
    spec = importlib.util.spec_from_file_location("risk_parity", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["risk_parity"] = mod
    spec.loader.exec_module(mod)
    return mod


def stacked(ax, rows, labels, vals, title):
    left = np.zeros(len(rows))
    ys = np.arange(len(rows))[::-1]
    for j, name in enumerate(labels):
        v = np.array([r[j] for r in vals]) * 100
        ax.barh(ys, v, left=left, color=ASSET_COLORS[j], alpha=0.9, height=0.62, label=name, edgecolor="white", linewidth=1)
        for y, l, x in zip(ys, left, v):
            if x >= 5:
                ax.text(l + x / 2, y, f"{x:.0f}", ha="center", va="center", color="white", fontsize=10, fontweight="bold")
        left += v
    ax.set_xlim(0, 100)
    ax.set_title(title)
    ax.grid(axis="y", visible=False)
    return ys


def fig_weights_vs_risk(rp) -> None:
    ports = [("똑같이 1/n", np.ones(4) / 4), ("위험 기여 균등", rp.solve_erc(rp.COV4)), ("최소분산", rp.solve_minvar(rp.COV4))]
    w = [p[1] for p in ports]
    shares = [rp.risk_shares(x, rp.COV4) for x in w]
    vols = [rp.vol_of(x, rp.COV4) * 100 for x in w]
    fig, (ax, bx) = new_fig(figsize=(9.0, 4.6), ncols=2, sharey=True)
    ys = stacked(ax, ports, rp.NAMES, w, "금액 비중 (%)")
    stacked(bx, ports, rp.NAMES, shares, "위험 기여 (%)")
    ax.set_yticks(ys, [f"{p[0]}\n변동성 {v:.2f}%" for p, v in zip(ports, vols)])
    bx.axvline(25, color=COLORS["ink"], lw=1.2, ls=":")
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncols=4, bbox_to_anchor=(0.5, 0.055), fontsize=10)
    caption(fig, "합성 데이터 · 가상 네 자산 변동성 18·16·5·14% · 주식끼리 상관 0.7 · 비중 한도 1~95% · 막대 안 숫자는 % (5% 미만은 생략) · 점선은 균등 25%")
    save_with_room(fig, "weights-vs-risk", 0.13)


def fig_cap_effect(rp) -> None:
    vol_x = rp.VOL4.copy(); vol_x[2] = 0.002
    cov_x = np.outer(vol_x, vol_x) * rp.CORR4
    cases = [("한도 없음 (0 ~ 100%)", rp.solve_erc(cov_x, 0.0, 1.0)), ("앱 한도 (1 ~ 95%)", rp.solve_erc(cov_x, 0.01, 0.95))]
    fig, axes = new_fig(figsize=(8.4, 4.4), ncols=2, sharey=True)
    for ax, (title, w) in zip(axes, cases):
        s = rp.risk_shares(w, cov_x) * 100
        x = np.arange(4)
        ax.bar(x, s, color=ASSET_COLORS, alpha=0.9, width=0.62)
        ax.axhline(25, color=COLORS["ink"], lw=1.2, ls=":")
        for xi, v, wi in zip(x, s, w):
            ax.text(xi, v + 0.9, f"{v:.1f}%", ha="center", fontsize=10, fontweight="bold")
            ax.text(xi, 1.2, f"비중\n{wi * 100:.1f}%", ha="center", va="bottom", fontsize=9, color="white", fontweight="bold", linespacing=1.15)
        ax.set_xticks(x, rp.NAMES)
        ax.set_title(title)
        ax.set_ylim(0, 36)
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("위험 기여 (%)")
    axes[1].text(2, 26.0, "균등 25%", ha="center", va="bottom", fontsize=9)
    caption(fig, "합성 데이터 · 국내채권의 변동성만 0.2% 로 바꾼 가상 네 자산 · 나머지 변동성 18·16·14% · 막대 아래 흰 숫자는 그 자산의 비중")
    save_with_room(fig, "cap-effect", 0.04)


def main() -> None:
    apply_style()
    rp = load_example()
    fig_weights_vs_risk(rp)
    fig_cap_effect(rp)
    for p in sorted((ROOT / "public" / "learn" / "img" / SLUG).glob("*.svg")):
        print(p.relative_to(ROOT), p.stat().st_size)


if __name__ == "__main__":
    main()
