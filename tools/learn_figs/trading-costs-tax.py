r"""F.3 매매 비용과 증권거래세 — 그림 둘 (sell-tax-by-year · cost-breakdown).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\trading-costs-tax.py
출력  : public/learn/img/trading-costs-tax/sell-tax-by-year.svg · cost-breakdown.svg

자료  : Qurious 비용 모델(app/services/trading_cost.py)의 시행일별 세율표와 요율 상수를 옮겨 적었다.
        법령에서 확인한 값은 2026-01-01 이후(증권거래세법 시행령 제5조 · 농어촌특별세법 제5조, 2026-11-03 열람)와
        2019-06-03 거래세(시행령 개정이유)이고, 2023~2025 는 해설 자료와 맞춰 본 앱의 값이다(2021~2022 는 2차 자료라 연하게 그린다).
        cost-breakdown 의 금액은 거래대금 100만 원에 위 요율을 곱한 계산 결과이며 슬리피지는 가정이다.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from _style import COLORS, apply_style, caption, new_fig, save_svg

SLUG = "trading-costs-tax"


def save(fig, name: str) -> None:
    """SVG 로 저장한다. 환경변수 LEARNFIG_PNG 에 폴더를 주면 눈으로 볼 PNG 도 그 폴더에 남긴다(저장소 밖)."""
    preview = os.environ.get("LEARNFIG_PNG")
    if preview:
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.savefig(Path(preview) / f"{SLUG}-{name}.png", dpi=110)
    save_svg(fig, SLUG, name)


def sell_tax_by_year() -> None:
    periods = ["2019.6~", "2021~", "2023~", "2024~", "2025~", "2026~"]
    kospi_transfer = [0.10, 0.08, 0.05, 0.03, 0.00, 0.05]          # 코스피 증권거래세(%)
    rural = 0.15                                                   # 농어촌특별세(%) — 코스피만
    kosdaq_transfer = [0.25, 0.23, 0.20, 0.18, 0.15, 0.20]         # 코스닥 증권거래세(%) — 농특세 없음
    fig, ax = new_fig(figsize=(8.4, 4.6))
    x = np.arange(len(periods))
    w = 0.36
    for i in range(len(periods)):
        faint = i == 1                                              # 2021~ 은 2차 자료
        a = 0.45 if faint else 1.0
        ax.bar(x[i] - w / 2 - 0.01, kospi_transfer[i], w, color=COLORS["blue"], alpha=a, label="증권거래세" if i == 0 else None)
        ax.bar(x[i] - w / 2 - 0.01, rural, w, bottom=kospi_transfer[i], color="white", edgecolor=COLORS["orange"],
               hatch="///", linewidth=1.4, alpha=a, label="농어촌특별세(코스피만)" if i == 0 else None)
        ax.bar(x[i] + w / 2 + 0.01, kosdaq_transfer[i], w, color=COLORS["blue"], alpha=a)
        total = kospi_transfer[i] + rural
        ax.text(x[i] - w / 2 - 0.01, total + 0.008, f"{total:.2f}", ha="center", va="bottom", fontsize=9, color=COLORS["ink"])
        ax.text(x[i] + w / 2 + 0.01, kosdaq_transfer[i] + 0.008, f"{kosdaq_transfer[i]:.2f}", ha="center", va="bottom", fontsize=9, color=COLORS["ink"])
        ax.text(x[i] - w / 2 - 0.01, -0.006, "코스피", ha="center", va="top", fontsize=8, color=COLORS["gray"])
        ax.text(x[i] + w / 2 + 0.01, -0.006, "코스닥", ha="center", va="top", fontsize=8, color=COLORS["gray"])
    ax.text(x[4] - w / 2 - 0.01, 0.02, "거래세 0%", ha="center", fontsize=8.5, color=COLORS["blue"],
            bbox=dict(facecolor="white", edgecolor="none", pad=1.5))
    ax.set_xticks(x, periods, fontsize=10)
    ax.tick_params(axis="x", pad=22)
    ax.set_ylim(0, 0.31)
    ax.set_ylabel("매도 세금 합계 (%)")
    ax.legend(loc="upper right", ncol=2)
    ax.set_title("매도할 때 내는 세금: 칸은 달라도 합계는 같습니다")
    caption(fig, "Qurious 세율표 값 · 법령 확인: 2019.6~ 거래세 · 2026~ / 해설 자료: 2023~2025 / 연한 2021~ 은 2차 자료")
    save(fig, "sell-tax-by-year")


def cost_breakdown() -> None:
    amount = 1_000_000
    fee, clearing = amount * 0.000140527, amount * 0.000036396
    slip = amount * 0.0010                                          # 슬리피지 편도 10bp(가정)
    cols = [  # (이름, 거래세, 농특세)
        ("매수", 0.0, 0.0),
        ("매도\n코스피 2025", 0.0, amount * 0.0015),
        ("매도\n코스피 2026", amount * 0.0005, amount * 0.0015),
        ("매도\n코스닥 2026", amount * 0.0020, 0.0),
        ("매도\n코넥스 2026", amount * 0.0010, 0.0),
    ]
    fig, ax = new_fig(figsize=(8.4, 4.6))
    x = np.arange(len(cols))
    base = np.zeros(len(cols))
    parts = [
        ("위탁수수료(한 증권사 예)", [fee] * len(cols), COLORS["blue"], ""),
        ("유관기관 제비용", [clearing] * len(cols), COLORS["gray"], ""),
        ("증권거래세", [c[1] for c in cols], COLORS["orange"], ""),
        ("농어촌특별세", [c[2] for c in cols], COLORS["purple"], ""),
    ]
    for name, vals, color, hatch in parts:
        ax.bar(x, vals, 0.55, bottom=base, color=color, label=name, hatch=hatch)
        base += np.array(vals)
    for i, t in enumerate(base):
        ax.text(x[i], t + 40, f"{t:,.1f}원", ha="center", va="bottom", fontsize=9.5, fontweight="bold", color=COLORS["ink"])
        ax.bar(x[i], slip, 0.55, bottom=t + 330, fill=False, edgecolor=COLORS["red"], linestyle="--", linewidth=1.4,
               label="슬리피지 10bp 가정(편도)" if i == 0 else None)
    ax.set_xticks(x, [c[0] for c in cols], fontsize=9.5)
    ax.set_ylim(0, 4_700)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")
    ax.set_ylabel("거래대금 100만 원당 비용 (원)")
    ax.legend(loc="upper center", fontsize=8.5, ncol=3)
    ax.set_title("100만 원어치를 사고팔 때: 매도 비용의 대부분은 세금")
    caption(fig, "계산 결과 · 요율은 Qurious 비용 모델 값 · 수수료는 한 증권사 예 · 빨간 점선은 가정(측정값 아님) · 슬리피지는 합계에 넣지 않음")
    save(fig, "cost-breakdown")


if __name__ == "__main__":
    apply_style()
    sell_tax_by_year()
    cost_breakdown()
    print("완료: public/learn/img/trading-costs-tax/sell-tax-by-year.svg · cost-breakdown.svg")
