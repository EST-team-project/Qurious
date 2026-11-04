r"""11.7 블랙–리터만 — 그림 둘 (S196 · 2026-11-04).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\black-litterman.py
출력  : public/learn/img/black-litterman/{view-confidence,weights-by-confidence}.svg

계산은 장의 예제 public/learn/examples/black_litterman.py 의 함수를 그대로 불러 쓴다(장의 출력과 그림이 같은 코드에서 나온다).
두 그림 모두 합성 데이터다: 네 가상 자산군의 변동성 · 상관 · 기준 비중을 손으로 정한 값이고 난수는 쓰지 않는다.
뷰 하나 — 「국내주식이 해외주식보다 연 3%p 더」 — 의 신뢰도 c 만 0 에서 99% 까지 바꾼다.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _style import COLORS, ROOT, apply_style, caption, new_fig, save_svg  # noqa: E402

SLUG = "black-litterman"


def load_example():
    path = ROOT / "public" / "learn" / "examples" / "black_litterman.py"
    spec = importlib.util.spec_from_file_location("black_litterman", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["black_litterman"] = mod
    spec.loader.exec_module(mod)
    return mod


def fig_view_confidence(bl) -> None:
    """신뢰도 c → 사후 상대수익(국내주식 − 해외주식). 사전에서 전망 쪽으로 c 만큼 가는 직선."""
    pi = bl.prior()
    prior_rel = (pi[0] - pi[1]) * 100
    cs = np.linspace(0.01, 0.99, 50)
    rel = [(bl.posterior(c)[0] - bl.posterior(c)[1]) * 100 for c in cs]
    fig, ax = new_fig(figsize=(8.4, 4.6))
    ax.axhline(bl.Q * 100, color=COLORS["orange"], lw=1.8, ls=(0, (5, 3)))
    ax.axhline(prior_rel, color=COLORS["gray"], lw=1.8, ls=(0, (5, 3)))
    ax.plot(np.r_[0, cs] * 100, np.r_[prior_rel, rel], color=COLORS["blue"], lw=2.6)
    ax.text(1, bl.Q * 100 + 0.07, f"내 전망: 연 {bl.Q * 100:.0f}%p", color=COLORS["orange"], fontsize=10.5, fontweight="bold", va="bottom")
    ax.text(99, prior_rel - 0.08, f"사전(기준 비중의 내재 수익률): {prior_rel:.3f}%p", color=COLORS["gray"], fontsize=10.5, fontweight="bold", va="top", ha="right")
    for c, dy, ha in ((0.25, 0.30, "center"), (0.5, 0.30, "center"), (0.9, 0.30, "center")):
        post = bl.posterior(c)
        y = (post[0] - post[1]) * 100
        ax.scatter(c * 100, y, s=70, color=COLORS["blue"], zorder=4)
        ax.annotate(f"신뢰도 {c * 100:.0f}% → {y:.3f}%p", (c * 100, y), xytext=(0, -26), textcoords="offset points",
                    ha=ha, fontsize=10, color=COLORS["blue"], fontweight="bold")
    ax.scatter(0, prior_rel, s=70, color=COLORS["gray"], zorder=4)
    ax.set_xlim(-2, 101)
    ax.set_ylim(0, 3.7)
    ax.set_xlabel("전망에 대한 신뢰도 c (%)")
    ax.set_ylabel("기대수익 차이: 국내주식 - 해외주식 (연 %p)")
    ax.set_title("신뢰도 c 만큼 사전에서 전망 쪽으로 이동합니다")
    caption(fig, "합성 데이터 · 난수 없음 · 손으로 정한 네 자산군(변동성 18·16·5·14%) · 전망 하나: 국내주식이 해외주식보다 연 3%p 더 · δ=3 · τ=0.05")
    save_svg(fig, SLUG, "view-confidence")


def fig_weights(bl) -> None:
    """신뢰도 c → 최적 비중. 한도 없음(직선)과 앱 한도 1~95%(꺾임)를 같은 그림에 둔다."""
    cs = np.linspace(0.01, 0.99, 99)
    free = np.array([bl.BASE] + [bl.weights(bl.posterior(c), None) for c in cs]) * 100
    capped = np.array([bl.BASE] + [bl.weights(bl.posterior(c)) for c in cs]) * 100
    x = np.r_[0, cs] * 100
    move100 = (bl.weights(bl.posterior(1.0), None) - bl.BASE)
    c_floor = (0.01 - bl.BASE[1]) / move100[1]          # 해외주식이 앱 하한 1% 에 닿는 신뢰도
    colors = (COLORS["blue"], COLORS["orange"], COLORS["green"], COLORS["purple"])

    fig, ax = new_fig(figsize=(8.4, 4.9))
    ax.axhspan(-20, 0, color=COLORS["red"], alpha=0.07, lw=0)
    ax.axhline(0, color=COLORS["red"], lw=1.1, alpha=0.7)
    ax.axhline(1, color=COLORS["gray"], lw=1.0, ls=":")
    for i in (0, 1):          # 한도 없음 — 직선(비중 이동 = c × 확신 100% 이동)
        ax.plot(x, free[:, i], color=colors[i], lw=1.7, alpha=0.9)
    for i in range(4):        # 앱 한도 1~95%
        ax.plot(x, capped[:, i], color=colors[i], lw=2.8, ls=(0, (4, 2.5)), zorder=3)
    for i, name in enumerate(bl.NAMES):
        ax.text(100.5, capped[-1, i] + {0: 0.0, 1: 3.2, 2: 0.0, 3: 1.2}[i], name, color=colors[i], fontsize=10.5, fontweight="bold", va="center")
    ax.text(100.5, free[-1, 1], "해외주식 (한도 없음)", color=colors[1], fontsize=9, va="center")
    ax.text(3, -10.5, "비중이 0 아래(공매도) — 앱은 허용하지 않음", color=COLORS["red"], fontsize=9.5, va="center")
    ax.text(3, 3.3, "앱 하한 1%", color=COLORS["gray"], fontsize=9, va="bottom")
    ax.axvline(c_floor * 100, color=COLORS["gray"], lw=0.9, ls="--")
    ax.text(c_floor * 100 + 1, 82, f"신뢰도 약 {c_floor * 100:.0f}% 부터 해외주식이 하한 1% 에 닿고\n전망에 없던 자산의 비중도 움직이기 시작", fontsize=9.5, color=COLORS["ink"], va="top")
    ax.text(3, 66, "굵은 점선 = 앱 한도 1~95%   가는 실선 = 한도 없음", fontsize=9.5, color=COLORS["gray"])
    ax.set_xlim(0, 127)
    ax.set_ylim(-20, 85)
    ax.set_xticks(range(0, 101, 20))
    ax.set_xlabel("전망에 대한 신뢰도 c (%)")
    ax.set_ylabel("최적 비중 (%)")
    ax.set_title("전망 하나 · 한도 없음이면 비중이 신뢰도에 정비례해 움직입니다")
    caption(fig, "합성 데이터 · 난수 없음 · 기준 비중 31.6/26.3/31.6/10.5% · 전망 하나: 국내주식이 해외주식보다 연 3%p 더 · δ=3 · τ=0.05 · 점선 = 앱 한도")
    save_svg(fig, SLUG, "weights-by-confidence")
    print(f"해외주식이 하한 1% 에 닿는 신뢰도 {c_floor * 100:.1f}% · 확신 100% 때 이동 {np.round(move100 * 100, 2)}")


def main() -> None:
    apply_style()
    bl = load_example()
    fig_view_confidence(bl)
    fig_weights(bl)
    for p in sorted((ROOT / "public" / "learn" / "img" / SLUG).glob("*.svg")):
        print(p.relative_to(ROOT), p.stat().st_size)


if __name__ == "__main__":
    main()
