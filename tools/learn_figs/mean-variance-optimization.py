r"""11.5 평균-분산 최적화와 제약 — 그림 둘 (S196 · 2026-11-03).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\mean-variance-optimization.py
출력  : public/learn/img/mean-variance-optimization/{efficient-frontier,input-sensitivity}.svg

계산은 장의 예제 public/learn/examples/mean_variance.py 의 함수를 그대로 불러 쓴다(장의 출력과 그림이 같은 코드에서 나온다).
두 그림 모두 합성 데이터다: 세 자산 A · B · C 의 변동성 8 · 18 · 25% · 기대수익 3 · 7 · 9% · 상관은 손으로 정한 값(난수 아님).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _style import COLORS, ROOT, apply_style, caption, new_fig, save_svg  # noqa: E402

SLUG = "mean-variance-optimization"


def load_example():
    path = ROOT / "public" / "learn" / "examples" / "mean_variance.py"
    spec = importlib.util.spec_from_file_location("mean_variance", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mean_variance"] = mod
    spec.loader.exec_module(mod)
    return mod


def fig_frontier(mv) -> None:
    lo = mv.stats(mv.min_variance_closed())[0]
    free = mv.frontier(np.linspace(lo, mv.MU.max() - 1e-4, 40))
    # 한 자산 최대 40% 로 막으면: 가능한 기대수익은 (기대수익 큰 순으로 채운) 0.4·9% + 0.4·7% + 0.2·3% = 7% 까지
    w_cap = mv.min_variance_slsqp(mv.COV, 0.4)
    lo_cap = mv.stats(w_cap)[0]
    capped = mv.frontier(np.linspace(lo_cap, 0.07 - 1e-4, 40), cap=0.4)

    fig, ax = new_fig(figsize=(8.4, 4.8))
    ax.plot([p[2] * 100 for p in free], [p[0] * 100 for p in free], color=COLORS["blue"], lw=2.4, label="효율적 투자선 (합 1 · 공매도 없음)")
    ax.plot([p[2] * 100 for p in capped], [p[0] * 100 for p in capped], color=COLORS["orange"], lw=2.6, ls=(0, (4, 3)), zorder=3, label="한 자산 최대 40% 로 막으면")
    for i, name in enumerate(mv.NAMES):               # 자산 하나만 가진 점
        ax.scatter(mv.VOL[i] * 100, mv.MU[i] * 100, s=60, color=COLORS["gray"], zorder=3)
        ax.annotate(f"자산 {name}만", (mv.VOL[i] * 100, mv.MU[i] * 100), xytext=(6, -12), textcoords="offset points", fontsize=10, color=COLORS["gray"])
    wg = mv.min_variance_closed(); rg, vg = mv.stats(wg)
    ax.scatter(vg * 100, rg * 100, marker="D", s=80, color=COLORS["red"], zorder=4)
    ax.annotate("전역 최소분산", (vg * 100, rg * 100), xytext=(8, 8), textcoords="offset points", fontsize=10, fontweight="bold", color=COLORS["red"])
    wu = mv.best(); ru, vu = mv.stats(wu)
    ax.scatter(vu * 100, ru * 100, marker="*", s=200, color=COLORS["purple"], zorder=4)
    ax.annotate("효용 최대(δ=3)", (vu * 100, ru * 100), xytext=(10, -4), textcoords="offset points", fontsize=10, fontweight="bold", color=COLORS["purple"])
    wc = mv.best(cap=0.4); rc, vc = mv.stats(wc)
    ax.scatter(vc * 100, rc * 100, marker="*", s=200, facecolor="white", edgecolor=COLORS["orange"], linewidth=1.8, zorder=5)
    ax.annotate("한도 40% 에서 효용 최대", (vc * 100, rc * 100), xytext=(-150, 14), textcoords="offset points", fontsize=10, fontweight="bold", color=COLORS["orange"],
                arrowprops=dict(arrowstyle="-", color=COLORS["orange"], lw=1))
    we = np.ones(3) / 3; re_, ve = mv.stats(we)
    ax.scatter(ve * 100, re_ * 100, marker="s", s=60, color=COLORS["green"], zorder=4)
    ax.annotate("똑같이 1/3씩", (ve * 100, re_ * 100), xytext=(12, -22), textcoords="offset points", fontsize=10, color=COLORS["green"])
    ax.set_xlabel("변동성 (연 %)"); ax.set_ylabel("기대수익 (연 %)")
    ax.set_title("같은 기대수익에서 변동성이 가장 작은 포트폴리오를 이은 선")
    ax.set_xlim(5, 28); ax.set_ylim(2, 10)
    ax.legend(loc="lower right")
    caption(fig, "합성 데이터 · 세 자산(변동성 8·18·25% · 기대수익 3·7·9% · 상관 0.2/0.1/0.6) · 난수 아님, 손으로 정한 입력 · SciPy SLSQP 로 계산 · 점선은 한 자산 최대 40%")
    save_svg(fig, SLUG, "efficient-frontier")


def fig_sensitivity(mv) -> None:
    deltas = np.arange(-2.0, 2.01, 0.5)
    ws = np.array([mv.best(mv.MU + np.array([0, d / 100, 0])) for d in deltas])
    fig, ax = new_fig(figsize=(8.4, 4.4))
    bottom = np.zeros(len(deltas))
    colors = (COLORS["blue"], COLORS["orange"], COLORS["green"])
    for i, name in enumerate(mv.NAMES):
        ax.bar(range(len(deltas)), ws[:, i] * 100, bottom=bottom, color=colors[i], alpha=0.88, width=0.72, label=f"자산 {name}")
        for k, v in enumerate(ws[:, i] * 100):
            if v >= 6:
                ax.text(k, bottom[k] + v / 2, f"{v:.0f}", ha="center", va="center", fontsize=9, color="white", fontweight="bold")
        bottom += ws[:, i] * 100
    ax.set_xticks(range(len(deltas)), [f"{d:+.1f}" if d else "0" for d in deltas])
    ax.set_xlabel("자산 B 의 기대수익을 바꾼 크기 (%p · 원래 7%)")
    ax.set_ylabel("비중 (%)")
    ax.set_title("기대수익을 1%p 만 바꿔도 비중이 크게 움직입니다")
    ax.legend(loc="upper center", ncols=3, bbox_to_anchor=(0.5, -0.17))
    ax.grid(axis="x", visible=False)
    caption(fig, "합성 데이터 · 효용 최대화(δ=3 · 합 1 · 공매도 없음) · 자산 B 기대수익만 바꾸고 나머지 입력은 그대로 · 막대 안 숫자는 %")
    save_svg(fig, SLUG, "input-sensitivity")


def main() -> None:
    apply_style()
    mv = load_example()
    fig_frontier(mv)
    fig_sensitivity(mv)
    for p in sorted((ROOT / "public" / "learn" / "img" / SLUG).glob("*.svg")):
        print(p.relative_to(ROOT), p.stat().st_size)


if __name__ == "__main__":
    main()
