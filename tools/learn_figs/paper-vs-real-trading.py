r"""F.9 모의투자와 실거래는 무엇이 다른가 — 그림 둘 (2026-11-03).

사용법: & C:\workspace\venvs\learnfig\Scripts\python.exe -X utf8 tools\learn_figs\paper-vs-real-trading.py
출력  : public/learn/img/paper-vs-real-trading/{order-book-sweep,who-trades-when}.svg

그림 1 은 합성 데이터(손으로 정한 매도 호가창)이고 계산은 장의 예제 public/learn/examples/paper_vs_real.py 의 함수를 그대로 불러 쓴다.
그림 2 는 시간표 그림이다 — 실거래(KRX) 칸은 KRX 규정(2026-11-03 열람)과 같은 시각, 증권사 모의 칸은 한국투자증권 모의투자 대회규정(같은 날 열람),
Qurious 칸은 앱 코드를 읽은 결과다. 애프터마켓 시작일은 보도 기준이라 빗금으로 구분한다.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
from matplotlib.patches import Patch, Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _style import COLORS, ROOT, apply_style, caption, new_fig, save_svg  # noqa: E402

SLUG = "paper-vs-real-trading"


def load_example():
    path = ROOT / "public" / "learn" / "examples" / "paper_vs_real.py"
    spec = importlib.util.spec_from_file_location("paper_vs_real", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["paper_vs_real"] = mod
    spec.loader.exec_module(mod)
    return mod


def fig_order_book(pv) -> None:
    asks = pv.ASKS
    ref = asks[0][0]
    qty_big = 5_000
    fig, (ax1, ax2) = new_fig(figsize=(9.0, 4.8), ncols=2, gridspec_kw={"width_ratios": [5, 4]})

    # 왼쪽: 5,000주 시장가가 호가를 쓸어 가는 모습
    ax1.set_axisbelow(True)
    left = qty_big
    ys = np.arange(len(asks))
    for i, (price, size) in enumerate(asks):
        take = min(size, left)
        left -= take
        ax1.barh(i, size, color="#e5e7eb", edgecolor=COLORS["gray"], height=0.62)
        if take:
            ax1.barh(i, take, color=COLORS["orange"], height=0.62, hatch="//", edgecolor="white")
        ax1.text(size + 90, i, f"{size:,}주" + (f"  (내 주문 {take:,}주 체결)" if take else ""), va="center", fontsize=9.5,
                 color=COLORS["orange"] if take else COLORS["ink"], fontweight="bold" if take else "normal")
    ax1.set_yticks(ys, [f"{p:,}원" for p, _ in asks])
    ax1.set_xlim(0, 9_800)
    ax1.set_xlabel("매도 호가 잔량 (주)")
    ax1.set_title(f"시장가 {qty_big:,}주 매수는 호가 5단계를 씁니다")
    ax1.legend(handles=[Patch(facecolor="#e5e7eb", edgecolor=COLORS["gray"], label="호가창의 잔량"),
                        Patch(facecolor=COLORS["orange"], hatch="//", edgecolor="white", label="내 주문이 가져간 몫")],
               loc="lower right", fontsize=9)

    # 오른쪽: 주문 수량별 평균 체결가가 기준가에서 밀린 정도
    orders = (100, 1_000, 5_000, 10_000)
    bps = [pv.slippage_bp(pv.sweep_book(asks, q)["평균가"], ref) for q in orders]
    ax2.set_axisbelow(True)
    xs = np.arange(len(orders))
    bars = ax2.bar(xs, bps, color=COLORS["orange"], width=0.6)
    for b, v, q in zip(bars, bps, orders):
        rest = pv.sweep_book(asks, q)["미체결"]
        label = f"{v:.1f}bp" + (f"\n(미체결 {rest:,}주)" if rest else "")
        ax2.text(b.get_x() + b.get_width() / 2, v + 1.5, label, ha="center", fontsize=9.5, fontweight="bold", color=COLORS["ink"])
    ax2.axhline(0, color=COLORS["blue"], lw=2.2, label="우리 앱의 모의 체결: 어느 수량이든 0bp")
    ax2.legend(loc="upper left", fontsize=9)
    ax2.set_xticks(xs, [f"{q:,}주" for q in orders])
    ax2.set_ylim(-4, 92)
    ax2.set_xlabel("시장가 매수 주문 수량")
    ax2.set_ylabel("평균 체결가가 불리해진 정도 (bp)")
    ax2.set_title("주문이 클수록 평균가가 밀립니다")
    caption(fig, "합성 데이터 · 손으로 정한 매도 호가창(실제 시세 아님) · 최우선 매도호가 10,000원을 기준으로 함 · 1bp = 0.01%")
    save_svg(fig, SLUG, "order-book-sweep")


def fig_who_trades_when() -> None:
    def t(h, m=0):
        return h + m / 60

    fig, ax = new_fig(figsize=(9.0, 5.2))
    rows = ["실거래\n(한국거래소)", "증권사 모의\n(한국투자증권)", "Qurious\n일반 모의 주문", "Qurious\n스탑 발동"]
    y = {name: len(rows) - 1 - i for i, name in enumerate(rows)}
    h = 0.58
    boxed = {"facecolor": "white", "alpha": 0.9, "edgecolor": "none", "pad": 1.6}

    def bar(row, a, b, color, label=None, hatch=None, alpha=1.0, fontcolor="white", box=False):
        ax.add_patch(Rectangle((a, y[row] - h / 2), b - a, h, facecolor=color, edgecolor="white" if hatch else color,
                               hatch=hatch, alpha=alpha, lw=0.6))
        if label:
            ax.text((a + b) / 2, y[row], label, ha="center", va="center", fontsize=9, color=fontcolor, fontweight="bold",
                    bbox=boxed if box else None)

    call = COLORS["gray"]          # 동시호가(주문을 모아 한 가격으로)
    cont = COLORS["blue"]          # 접속매매(들어오는 대로 체결)
    # 실거래 — 08:30 시가 동시호가 · 09:00~15:20 접속매매 · 15:20~15:30 종가 동시호가 · 15:40~16:00 시간외종가 · 16:00~20:00 애프터마켓(시작일 보도 기준)
    bar(rows[0], t(8, 30), t(9), call)
    bar(rows[0], t(9), t(15, 20), cont, "정규장 접속매매 09:00~15:20")
    bar(rows[0], t(15, 20), t(15, 30), call)
    bar(rows[0], t(15, 40), t(16), COLORS["purple"])
    bar(rows[0], t(16), t(20), COLORS["green"], "애프터마켓 16:00~20:00", hatch="//", fontcolor=COLORS["ink"], box=True)
    # 증권사 모의 — 동시호가 08:30~09:00 / 15:20~15:30, 정규시장 09:00~15:30, 시간외매매 불가, 익일 예약주문 접수 15:40~07:30
    bar(rows[1], t(8, 30), t(9), call)
    bar(rows[1], t(9), t(15, 20), cont, "정규시장 09:00~15:30")
    bar(rows[1], t(15, 20), t(15, 30), call)
    bar(rows[1], t(7), t(7, 30), call, hatch="..", alpha=0.45)
    bar(rows[1], t(15, 40), t(20), call, "시간외 불가 · 예약주문만", hatch="..", alpha=0.45, fontcolor=COLORS["ink"], box=True)
    # Qurious 일반 모의 주문 — 시간 검사 없음(코드 읽기)
    bar(rows[2], t(7), t(20), COLORS["orange"], "시간 검사 없음 · 화면에는 '장 닫힘' 표시만 · 체결가는 확인한 시세",
        hatch="//", alpha=0.85, fontcolor=COLORS["ink"], box=True)
    # Qurious 스탑 — 정규장 + 확정 거래일
    bar(rows[3], t(9), t(15, 30), cont, "정규장(09:00~15:30)에만 발동")

    ax.set_xlim(7, 20)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_yticks([y[r] for r in rows], rows)
    ax.set_xticks(range(7, 21, 1), [f"{x:02d}" for x in range(7, 21)])
    ax.set_xlabel("시각 (KST, 시)")
    ax.grid(axis="y", visible=False)
    ax.set_title("같은 시각에 주문하면 어디서 체결될까요")
    ax.legend(handles=[
        Patch(facecolor=call, label="동시호가(주문을 모아 한 가격으로)"),
        Patch(facecolor=cont, label="접속매매(들어오는 대로 체결)"),
        Patch(facecolor=COLORS["purple"], label="시간외종가 15:40~16:00"),
        Patch(facecolor=COLORS["green"], hatch="//", edgecolor="white", label="애프터마켓(시작일은 보도 기준)"),
        Patch(facecolor=call, alpha=0.45, hatch="..", edgecolor="white", label="체결 없음 · 예약주문 접수만"),
        Patch(facecolor=COLORS["orange"], hatch="//", edgecolor="white", label="앱: 시간을 막지 않음"),
    ], loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3, fontsize=8.5)
    caption(fig, "시간표 그림 · 실거래: 한국거래소 규정(2026-11-03 열람 · 08:30~08:40 시간외종가 생략) · 증권사 모의: 한국투자증권 대회규정 · Qurious: 코드 읽기")
    save_svg(fig, SLUG, "who-trades-when")


def main() -> None:
    apply_style()
    pv = load_example()
    fig_order_book(pv)
    fig_who_trades_when()
    for p in sorted((ROOT / "public" / "learn" / "img" / SLUG).glob("*.svg")):
        print(p.relative_to(ROOT), p.stat().st_size)


if __name__ == "__main__":
    main()
