r"""11.2 리밸런싱 세 방식 — 그림 둘 (S196 · 2026-11-03).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\rebalancing-methods.py
출력  : public/learn/img/rebalancing-methods/{rule-timeline,rule-comparison}.svg

계산은 장의 예제 public/learn/examples/rebalance_rules.py 의 함수를 그대로 불러 쓴다(장의 출력과 그림이 같은 코드에서 나온다).
두 그림 모두 합성 데이터다: 주식 연 7% · 변동성 16%, 채권 연 3% · 변동성 5%, 서로 독립한 월 수익률(시드 11).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _style import COLORS, ROOT, apply_style, caption, new_fig, save_svg  # noqa: E402

SLUG = "rebalancing-methods"


def load_example():
    path = ROOT / "public" / "learn" / "examples" / "rebalance_rules.py"
    spec = importlib.util.spec_from_file_location("rebalance_rules", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rebalance_rules"] = mod
    spec.loader.exec_module(mod)
    return mod


def fig_timeline(rb) -> None:
    rs, rbd = rb.make_returns()
    path = 0                                  # 시드 11 의 첫 경로 — 고르지 않고 그대로
    panels = [
        ("시간: 12개월마다", "시간 12개월", COLORS["blue"]),
        ("이탈률: 월 점검, 5%p 이상이면", "이탈률 5%p(월 점검)", COLORS["orange"]),
        ("현금흐름: 매달 입금 1 을 모자란 쪽에 (매도 없음)", "현금흐름만(매달 입금 1)", COLORS["green"]),
    ]
    _, never, _ = rb.simulate(None, rs, rbd, keep_path=path)
    years = (np.arange(rb.MONTHS) + 1) / 12
    fig, axes = new_fig(figsize=(8.4, 6.6), nrows=3, sharex=True)
    for ax, (title, rule, color) in zip(axes, panels):
        _, w, fired = rb.simulate(rb.RULES[rule], rs, rbd, keep_path=path)
        ax.axhspan((rb.TARGET - 0.05) * 100, (rb.TARGET + 0.05) * 100, color=COLORS["gray"], alpha=0.10, lw=0)
        ax.axhline(rb.TARGET * 100, color=COLORS["gray"], lw=1, ls="--")
        ax.plot(years, never * 100, color=COLORS["gray"], lw=1.2, alpha=0.7, label="안 함")
        ax.plot(years, w * 100, color=color, lw=2, label=title.split(":")[0])
        hit = np.where(fired)[0]
        if hit.size:
            ax.scatter(years[hit], w[hit] * 100, marker="v", s=46, color=COLORS["red"], zorder=4)
        n = int(fired.sum())
        note = f"되돌린 횟수 {n}회" if rule != "현금흐름만(매달 입금 1)" else "되돌린 횟수 0회 (입금만)"
        ax.set_title(f"{title}  ·  {note}", loc="left", fontsize=11)
        ax.set_ylabel("주식 비중 %")
        ax.set_ylim(48, 90)
        ax.legend(loc="upper left", ncols=2, fontsize=9)
    axes[-1].set_xlabel("년")
    axes[0].text(0.995, 0.06, "회색 띠 = 목표 60% ± 5%p · ▼ = 되돌린 달(되돌리기 직전 비중)", transform=axes[0].transAxes, ha="right", fontsize=8.5, color=COLORS["gray"])
    caption(fig, "합성 데이터 · 주식 연 7% 변동성 16% · 채권 연 3% 변동성 5% · 서로 독립 · 목표 60/40 · 20년 · 시드 11 의 첫 경로 · 비용 없음")
    save_svg(fig, SLUG, "rule-timeline")


def fig_comparison(rb) -> None:
    rs, rbd = rb.make_returns()
    names, res = list(rb.RULES), []
    for name in names:
        res.append(rb.simulate(rb.RULES[name], rs, rbd))
    fig, (ax, bx) = new_fig(figsize=(9.0, 4.6), ncols=2, sharey=True)
    ys = np.arange(len(names))[::-1]
    ev = [r["events"] for r in res]; wt = [r["worst"] for r in res]
    ax.barh(ys, ev, color=COLORS["blue"], alpha=0.85)
    bx.barh(ys, wt, color=COLORS["orange"], alpha=0.85)
    for y, v in zip(ys, ev):
        ax.annotate(f"{v:.1f}", (v, y), xytext=(4, 0), textcoords="offset points", va="center", fontsize=10, fontweight="bold")
    for y, v in zip(ys, wt):
        bx.annotate(f"{v:.1f}", (v, y), xytext=(4, 0), textcoords="offset points", va="center", fontsize=10, fontweight="bold")
    ax.set_yticks(ys, names)
    ax.set_xlim(0, 100); bx.set_xlim(0, 26)
    ax.set_title("20년 동안 되돌린 횟수"); bx.set_title("가장 크게 벗어난 값 (%p)")
    bx.axvline(5, color=COLORS["red"], lw=1.2, ls=":")
    bx.text(5.3, ys[0] + 0.45, "5%p", color=COLORS["red"], fontsize=9)
    ax.grid(axis="y", visible=False); bx.grid(axis="y", visible=False)
    caption(fig, "합성 데이터 · 1,000경로 평균 · 주식 연 7% 변동성 16% · 채권 연 3% 변동성 5% · 목표 60/40 · 20년 · 시드 11 · 비용 없음")
    save_svg(fig, SLUG, "rule-comparison")


def main() -> None:
    apply_style()
    rb = load_example()
    fig_timeline(rb)
    fig_comparison(rb)
    for p in sorted((ROOT / "public" / "learn" / "img" / SLUG).glob("*.svg")):
        print(p.relative_to(ROOT), p.stat().st_size)


if __name__ == "__main__":
    main()
