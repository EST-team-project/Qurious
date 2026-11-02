"""확정된 실행 기록의 값만 알림 항목으로 옮긴다. 계좌번호·키·원문 응답은 넣지 않는다."""
import math


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def fill_details(trade):
    details = []
    cost = trade.get("cost") or {}
    for key, label in (("commission", "위탁수수료"), ("fee_clearing", "유관기관 비용"),
                       ("tax_transfer", "거래세"), ("tax_rural", "농어촌특별세"), ("net_amount", "정산금액")):
        if number(cost.get(key)):
            details.append((label, f"{cost[key]:,.2f}원"))
    if number(trade.get("cash_balance")):
        details.append(("체결 후 가상 현금", f"{trade['cash_balance']:,.2f}원"))
    if cost.get("cost_basis"):
        details.append(("비용 기준", "모형 추정 비용" if cost["cost_basis"] == "estimated" else "장부 기록 비용"))
    return details


def risk_details(risk, limits):
    details = []
    pnl = risk.get("day_pnl_pct")
    if number(pnl):
        details.append(("회차 기준 당일 손익", f"{pnl:+.2f}%"))
    count = risk.get("orders_today")
    if number(count):
        cap = limits.max_orders_per_day if limits.max_orders_per_day > 0 else "제한 없음"
        details.append(("당일 주문 수 / 상한", f"{count} / {cap}"))
    return details
