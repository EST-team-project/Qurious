"""저장된 자산군 비중을 국내 상장 ETF 편집안으로 연결한다. 저장·주문은 하지 않는다."""
import math
import re
from datetime import datetime, timedelta, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.services import asset_allocation, product_etfs, rebalance_schedule

POLICY = "domestic_listed_etf_liquidity_v1"
KST = ZoneInfo("Asia/Seoul")


def confirmed_day(now=None):
    now = (now or datetime.now(KST)).astimezone(KST)
    through = now.date() if now.time() >= time(15, 30) else now.date() - timedelta(days=1)
    days = rebalance_schedule.days(through - timedelta(days=20), through)
    valid = [d["date"] for d in days if d["is_trading_day"]]
    if not valid:
        raise ValueError("확정 거래일을 확인하지 못했습니다.")
    return valid[-1]


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def eligible(item):
    return (bool(re.fullmatch(r"[0-9A-Z]{6}", str(item.get("code", ""))))
            and item.get("halted") is False and item.get("multiple") == 1
            and not item.get("single_stock") and not item.get("derivative_group")
            and not set(item.get("flags", [])) & {"leverage", "inverse", "futures", "synthetic", "option_income"}
            and item.get("trade_days_20d", 0) == 20
            and all(positive(item.get(k)) for k in ("close", "aum", "trade_value_20d")))


def build_draft(result, catalog, expected_day):
    allocations = result["allocations"]
    amounts = [Decimal(str(allocations[k])) for k in ("국내주식", "해외주식", "국내채권", "대체자산", "현금")]
    if any(not v.is_finite() or v < 0 for v in amounts) or sum(amounts) != 100:
        raise ValueError("저장 배분의 자산군 비중 합계가 100%가 아닙니다.")
    if catalog.get("status") != "ok" or catalog.get("as_of") != expected_day:
        raise ValueError("마지막 확정 거래일까지의 ETF 자료를 확인하지 못했습니다. 기존 목표는 유지합니다.")
    draft = asset_allocation.rebalance_draft(result)
    targets = {r["symbol"]: dict(r) for r in draft["targets"]}
    selected, unavailable = [], {}
    for group, weight in draft["unapplied_allocations"].items():
        if not weight:
            continue
        candidates = [x for x in catalog["items"] if x.get("asset_class") == group and eligible(x)]
        # 단일 종목을 임의 취향으로 고르지 않는다. 유동성, 순자산, 코드의 고정 순서다.
        candidates.sort(key=lambda x: (-x["trade_value_20d"], -x["aum"], x["code"]))
        if not candidates:
            unavailable[group] = weight
            continue
        item = candidates[0]
        symbol = item["code"] + ".KS"
        target = targets.setdefault(symbol, {"symbol": symbol, "name": item["name"], "weight_pct": 0})
        target["weight_pct"] = float(Decimal(str(target["weight_pct"])) + Decimal(str(weight)))
        selected.append({"asset_class": group, "symbol": symbol, "name": item["name"], "weight_pct": weight,
                         "as_of": expected_day, "trade_value_20d": item["trade_value_20d"], "aum": item["aum"],
                         "reason": "거래 가능·20거래일 자료·단순 구조 후보 중 20일 평균 거래대금, 순자산, 코드 순"})
    total = sum(Decimal(str(r["weight_pct"])) for r in targets.values())
    return {**draft, "policy": POLICY, "targets": list(targets.values()),
            "cash_weight_pct": float(100 - total), "unapplied_allocations": unavailable,
            "selected_etfs": selected, "etf_weight_pct": sum(x["weight_pct"] for x in selected),
            "as_of": expected_day, "status": "partial" if unavailable else "complete",
            "message": "저장된 자산군 비중을 국내 상장 ETF 후보로 연결한 편집안입니다. 분류는 상품명·기초지수 규칙이며 상품 적합성이나 성과 추천이 아닙니다. 후보가 없는 자산군은 현금으로 남습니다. 선정 근거·목표를 확인한 뒤 저장하세요."}


def preview(result):
    return build_draft(result, product_etfs.selection_catalog(), confirmed_day())
