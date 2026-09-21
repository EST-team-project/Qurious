"""주문을 한 건도 내지 않고 증권사 수수료율을 역산한다.

왜 있는가
---------
우리 요율표(`app/services/trading_cost.py`)가 실제와 맞는지 확인할 방법이
지금까지 하나뿐이었다 — 주문을 내고 체결 내역의 제비용을 보는 것. 그런데
**모의투자 체결로는 요율표를 검증할 수 없다** (Issue #51 에서 확정. 모의 환경은
수수료·세금을 실전과 다르게 계산할 자유가 있고, 실제로 0원일 수 있다).

그래서 여기서는 주문 대신 **매수가능조회**(`inquire-psbl-order`)를 쓴다.
이 TR 은 "이 가격이면 몇 주까지 살 수 있나" 를 증권사가 계산해 돌려준다.
그 계산 안에 **수수료가 이미 들어가 있다.** 즉 답을 거꾸로 풀면 증권사가
쓰는 수수료율이 나온다 — 주문 0건, 체결 0건, 비용 0원으로.

어떻게 역산하는가
----------------
증권사는 대략 이렇게 계산한다.

    최대매수수량 = floor( 주문가능현금 / (주문단가 x (1 + 수수료율)) )

수량이 **내림**되므로 수수료율이 하나로 떨어지지는 않고 구간으로 나온다.

    C / (p x (q+1)) - 1  <  f  <=  C / (p x q) - 1
      (C=주문가능현금 · p=주문단가 · q=최대매수수량 · f=수수료율)

단가 p 를 바꿔 여러 번 물으면 구간이 겹쳐지며 좁아진다. 단가가 낮을수록
수량 q 가 커지고 구간이 좁다 — 그래서 저가 단가를 함께 넣는다.

읽는 법
-------
- 구간이 **0 을 품으면** 모의 수수료가 0원일 수 있다는 뜻이다.
- 구간이 0.00017693(실전 0.017693%) 을 품으면 실전과 같은 요율을 쓴다는 뜻이다.
- 두 값 모두 품지 못하면 제3의 요율이다.

쓰는 법
-------
    PYTHONPATH=. python scripts/probe_kis_fee_rate.py
    PYTHONPATH=. python scripts/probe_kis_fee_rate.py --symbol 005930 --raw

기본은 **모의계좌(KIS_MOCK_*)** 다. 실계좌(`--real`)는 승인 없이 쓰지 않는다.

🔴 이 스크립트는 조회만 한다. 주문 관련 TR 을 부르지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sync_fills import load_env, make_client     # noqa: E402

# 실전 위탁수수료율 (온라인 · 유관기관비 포함). 요율표의 근거값과 같은 수치다.
REAL_FEE_RATE = 0.00017693


async def inquire_psbl(client, account: str, symbol: str, price: int, raw: bool) -> dict | None:
    """매수가능조회 1회. 주문을 내지 않는다."""
    await client._ensure_token()
    cano, acnt_prdt = client._split_account(account)
    tr_id = "VTTC8908R" if client.paper else "TTTC8908R"
    params = {
        "CANO":                  cano,
        "ACNT_PRDT_CD":          acnt_prdt,
        "PDNO":                  symbol,
        "ORD_UNPR":              str(price),
        "ORD_DVSN":              "00",   # 00 지정가 — 단가를 우리가 정해야 역산이 된다
        "CMA_EVLU_AMT_ICLD_YN":  "N",    # CMA 평가금액 포함 안 함
        "OVRS_ICLD_YN":          "N",    # 해외 포함 안 함
    }
    async with httpx.AsyncClient(verify=False, timeout=15) as cli:
        r = await cli.get(
            f"{client.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order",
            headers=client._headers(tr_id),
            params=params,
        )
        r.raise_for_status()
        body = client._check(r.json(), "매수가능조회")
    out = body.get("output") or {}
    if isinstance(out, list):
        out = out[0] if out else {}
    if raw:
        print("    원문:", json.dumps(out, ensure_ascii=False))
    return out or None


def bracket(cash: float, price: int, qty: int) -> tuple[float, float] | None:
    """최대매수수량에서 수수료율 구간을 푼다.

    floor 를 되돌리는 것이라 한 점이 아니라 구간이 나온다. 수량이 0 이면
    (예수금이 단가보다 적으면) 아무것도 말할 수 없다.
    """
    if qty <= 0 or price <= 0 or cash <= 0:
        return None
    lo = cash / (price * (qty + 1)) - 1.0
    hi = cash / (price * qty) - 1.0
    return (max(lo, -1.0), hi)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="005930", help="종목코드 6자리 (기본 005930 삼성전자)")
    ap.add_argument("--raw", action="store_true", help="응답 원문도 출력")
    ap.add_argument("--real", action="store_true", help="⚠️ 실계좌로 조회 (기본은 모의)")
    args = ap.parse_args()

    load_env()
    paper = not args.real
    print(f"― KIS 수수료율 역산 ({'모의' if paper else '⚠️ 실계좌'}) · 주문 0건 ―")
    client, account = await make_client(paper)

    # 현재가를 먼저 본다. 지정가가 호가 범위를 크게 벗어나면 거부될 수 있다.
    price_info = await client.get_price(args.symbol)
    base = int(price_info.current)
    print(f"  {args.symbol} {price_info.name} 현재가 {base:,}원")
    await asyncio.sleep(3)   # KIS 유량 제한 — 호출 간격 3초

    # 단가를 여러 개 쓴다. 낮은 단가일수록 수량이 커서 구간이 좁다.
    #   - 현재가: 실제로 주문했을 때와 같은 조건
    #   - /10 ~ /1000: 구간을 좁히기 위한 관측점 (주문이 아니므로 체결되지 않는다)
    # 🟡 현재가의 1/1000 까지 낮춰야 0 과 실전요율(0.017693%)이 갈린다.
    #    예수금 995만 원 · 단가 269원이면 두 가정의 수량이 6주 차이 난다.
    #    조회 TR 은 호가 범위를 따지지 않아 거부되지 않는다 (같은 날 실측).
    candidates = [base, max(base // 10, 1), max(base // 100, 1), max(base // 1000, 1)]
    seen: set[int] = set()
    brackets: list[tuple[int, int, float, tuple[float, float]]] = []

    for price in candidates:
        if price in seen:
            continue
        seen.add(price)
        out = await inquire_psbl(client, account, args.symbol, price, args.raw)
        if not out:
            print(f"  단가 {price:>10,}원 → 🔴 output 이 비었습니다")
            await asyncio.sleep(3)
            continue
        cash = client._parse_num(out.get("ord_psbl_cash"))
        max_amt = client._parse_num(out.get("max_buy_amt"))
        max_qty = client._parse_num(out.get("max_buy_qty"), int)
        nrcvb_qty = client._parse_num(out.get("nrcvb_buy_qty"), int)
        print(f"  단가 {price:>10,}원 → 현금 {cash:>13,.0f} · "
              f"미수없는수량 {nrcvb_qty:>9,}주 · (미수포함 {max_qty:>9,}주 / {max_amt:>13,.0f}원)")

        # 🔴 역산에는 **미수 없는 수량**만 쓴다. `max_buy_qty` 는 신용·미수를
        #    포함한 한도라 `max_buy_amt`(50,000,000원 고정)를 단가로 나눈 값일
        #    뿐이고, 수수료가 아예 들어가지 않는다 — 2026-09-21 모의계좌 실측.
        br = bracket(cash, price, nrcvb_qty)
        if br:
            brackets.append((price, nrcvb_qty, cash, br))
            # 수수료가 0원이라면 수량이 정확히 floor(현금/단가) 여야 한다.
            zero_fee_qty = math.floor(cash / price)
            real_fee_qty = math.floor(cash / (price * (1 + REAL_FEE_RATE)))
            mark = "0원과 일치" if nrcvb_qty == zero_fee_qty else f"0원이면 {zero_fee_qty:,}주"
            if zero_fee_qty != real_fee_qty:
                mark += f" · 실전요율이면 {real_fee_qty:,}주 ← 두 가정이 갈린다"
            else:
                mark += " · 실전요율로도 같은 수량 → 이 단가로는 못 가린다"
            print(f"       ※ {mark}")
        await asyncio.sleep(3)

    if not brackets:
        print("\n  🔴 역산할 수 있는 응답을 못 받았습니다.")
        return 1

    # 구간들의 교집합. 겹치지 않으면 모형(수수료율 한 개) 자체가 틀렸다는 신호다.
    lo = max(b[3][0] for b in brackets)
    hi = min(b[3][1] for b in brackets)
    print("\n― 역산 결과 ―")
    for price, qty, cash, (blo, bhi) in brackets:
        print(f"  단가 {price:>10,} · {qty:>10,}주 → f ∈ ({blo:+.8f}, {bhi:+.8f}]")

    if lo >= hi:
        print(f"\n  🔴 구간이 겹치지 않습니다 (lo {lo:+.8f} >= hi {hi:+.8f}).")
        print("     → 증권사가 단순 비례 수수료율을 쓰지 않는다는 뜻입니다.")
        print("       최소수수료·정액 구간·미수 한도 같은 다른 규칙이 섞여 있습니다.")
        return 0

    print(f"\n  교집합: f ∈ ({lo:+.8f}, {hi:+.8f}]")
    print(f"    = ({lo * 100:+.6f}% , {hi * 100:+.6f}%]")

    has_zero = lo < 0.0 <= hi
    has_real = lo < REAL_FEE_RATE <= hi
    if has_zero and not has_real:
        print("\n  🟢 **모의 수수료는 0원입니다.** 구간이 0 만 품고 실전 요율은 배제됩니다.")
        print("     → 모의 체결로 요율표를 검증하는 것은 원리적으로 불가능합니다 (#51 확정).")
    elif has_real and not has_zero:
        print(f"\n  🟢 **실전과 같은 요율({REAL_FEE_RATE:.8f})을 씁니다.** 0 은 배제됩니다.")
    elif has_zero and has_real:
        print("\n  🟡 구간이 0 과 실전 요율을 **둘 다** 품습니다 — 아직 가릴 수 없습니다.")
        print("     → 더 낮은 단가(저가 종목)로 다시 재면 구간이 좁아집니다.")
    else:
        print("\n  🔴 0 도 실전 요율도 품지 않는 **제3의 요율**입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
