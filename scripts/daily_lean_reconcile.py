#!/usr/bin/env python3
"""매일 LEAN ↔ 그림자 일지 대조 (v4) — A안 반자동.

v4:
- 진입·청산 신호 비교와 보유 상태 비교를 분리
- 기존 주문 방향·체결가·비용 요율 비교 유지
- 신호 비교 불가를 일치로 오판하지 않음
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import tradingview as tv
from app.services.lean_backtest import LeanBacktestService

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

JOURNAL_RULE_ID = "card_ma_cross_20_60"
JOURNAL_VERSION_NO = 1
START_DATE = date(2026, 9, 1)
TICKER = "005930.KS"
TICKER_PREFIX = TICKER.split(".")[0]
INITIAL_CASH = 10_000_000.0
FEE_TOL_BP = 5.0
PRICE_TOL_BP = 30.0


def pull_failure_text(res) -> str:
    """원장 pull 하위 프로세스가 실패했을 때 보여 줄 글 — 예외 메시지가 stdout 에 찍히는 경로도 있어(#377) stderr 와 stdout 끝을 함께 싣는다."""
    parts = []
    for name, text_ in (("stderr", res.stderr), ("stdout", res.stdout)):
        tail = (text_ or "").strip()[-300:]
        if tail:
            parts.append(f"[{name}] {tail}")
    return f"Pull 실패(종료코드 {res.returncode}): " + (" ".join(parts) if parts else "출력 없음")


def get_fill_cost(cost_data) -> float | None:
    """일지 fills.cost → 총비용(원). total_cost 우선, 없으면 세목 합산."""
    if cost_data is None:
        return 0.0
    if isinstance(cost_data, (int, float)):
        return float(cost_data)
    if isinstance(cost_data, dict):
        v = cost_data.get("total_cost")
        if isinstance(v, (int, float)):
            return float(v)
        parts = ["commission", "fee_clearing", "tax_transfer", "tax_rural"]
        if any(isinstance(cost_data.get(k), (int, float)) for k in parts):
            return sum(float(cost_data.get(k) or 0) for k in parts)
        return None
    return None


def get_fill_gross(cost_data, fill) -> float | None:
    """일지 fills의 거래대금(gross_amount). 요율 계산용."""
    if isinstance(cost_data, dict):
        g = cost_data.get("gross_amount")
        if isinstance(g, (int, float)):
            return float(g)
    try:
        return float(fill["fill_price"]) * float(fill["qty_filled"])
    except (KeyError, TypeError, ValueError):
        return None


def parse_lean_fees(value) -> float | None:
    if not isinstance(value, str):
        return None
    cleaned = value.replace("₩", "").replace(",", "").replace(" ", "").strip()
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def normalize_date(raw) -> str | None:
    if isinstance(raw, (date, datetime)):
        d = raw.date() if isinstance(raw, datetime) else raw
        return d.isoformat()
    if raw is None:
        return None
    match = re.search(r"\d{4}[-/]\d{2}[-/]\d{2}", str(raw))
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(0).replace("/", "-")).isoformat()
    except ValueError:
        return None


async def pull_hf_ledger() -> tuple[int, int]:
    print("▶ [1/4] HF 원장 pull 중...")

    if not os.environ.get("HUGGINGFACE_ACCESS_TOKEN"):
        try:
            from huggingface_hub import get_token
            token = get_token()
            if token:
                os.environ["HUGGINGFACE_ACCESS_TOKEN"] = token
                print("   (HF 로그인 캐시에서 토큰을 자동으로 불러왔습니다)")
            else:
                raise RuntimeError(
                    "HUGGINGFACE_ACCESS_TOKEN 환경변수도 없고 로그인 캐시도 없습니다. "
                    "`hf auth login`을 먼저 실행해 주세요."
                )
        except ImportError as exc:
            raise RuntimeError("huggingface_hub 패키지가 없습니다.") from exc

    url = os.environ["DATABASE_URL"]

    async def count_days() -> int:
        eng = create_async_engine(url)
        try:
            async with eng.connect() as conn:
                return (await conn.execute(
                    text("SELECT COUNT(*) FROM paper_journal_days")
                )).scalar_one()
        finally:
            await eng.dispose()

    before = await count_days()
    res = subprocess.run([sys.executable, "scripts/paper_journal.py", "pull"],
                         cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError(pull_failure_text(res))
    after = await count_days()
    print(f"✅ pull: {before} → {after} (신규 {after-before})")
    return before, after


async def load_journal(target_date: date):
    eng = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with eng.connect() as conn:
            result = await conn.execute(text("""
                SELECT id FROM paper_journal_versions
                WHERE rule_id = :rule AND version_no = :vno
            """), {"rule": JOURNAL_RULE_ID, "vno": JOURNAL_VERSION_NO})
            ids = result.scalars().all()
            if len(ids) != 1:
                raise RuntimeError(f"판1 정확히 1개 아님: {ids}")
            version_id = ids[0]
            result = await conn.execute(text("""
                SELECT trade_date, decisions, orders, fills, positions
                FROM paper_journal_days
                WHERE version_id = :vid AND trade_date <= :td
                ORDER BY trade_date
            """), {"vid": version_id, "td": target_date})
            rows = [dict(row._mapping) for row in result]
    finally:
        await eng.dispose()

    if not rows:
        raise RuntimeError("일지 0건")
    for row in rows:
        row["decisions"] = row.get("decisions") or []
        row["orders"] = row.get("orders") or []
        row["fills"] = row.get("fills") or []
        row["positions"] = row.get("positions") or {}
    return rows


async def run_lean(end_date: date) -> dict:
    print(f"▶ [2/4] LEAN 재실행 ({START_DATE} ~ {end_date})")
    svc = LeanBacktestService()
    result = await svc.run(
        ticker=TICKER,
        start_date=START_DATE,
        end_date=end_date,
        compare_start_date=START_DATE,
        compare_end_date=end_date,
        initial_cash=INITIAL_CASH,
        strategy="ma_cross",
        short_window=20,
        long_window=60,
    )
    if not result.get("lean_ok"):
        raise RuntimeError(f"LEAN 실패: {result.get('lean_log', '')[-300:]}")
    out = ROOT / "data" / "lean-workflows" / f"daily_replay_{end_date}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, default=str, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ LEAN 완료 → {out}")
    return result


def group_fills_by_date(fills):
    out = defaultdict(list)
    for fill in fills or []:
        d = normalize_date(fill.get("date"))
        if d:
            out[d].append(fill)
    return out


def journal_qty(row) -> float:
    """positions에서 005930 수량 합."""
    total = 0.0
    for symbol, value in (row.get("positions") or {}).items():
        if not str(symbol).startswith(TICKER_PREFIX):
            continue
        if isinstance(value, dict):
            for key in ("qty", "quantity", "amount"):
                qty = value.get(key)
                if isinstance(qty, (int, float)):
                    total += float(qty)
                    break
        else:
            try:
                total += float(value)
            except (TypeError, ValueError):
                pass
    return total


def extract_journal_signals(journal_rows) -> list[dict]:
    """일지의 전략 규칙 설명에서 날짜별 진입·청산 상태를 추출한다."""
    pattern = re.compile(r"진입=(True|False)\s+청산=(True|False)")
    by_date = {}

    for row in journal_rows:
        row_date = normalize_date(row.get("trade_date"))
        if not row_date:
            continue

        for decision in row.get("decisions") or []:
            symbol = str(decision.get("symbol") or "")
            if not symbol.startswith(TICKER_PREFIX):
                continue

            for reason in decision.get("reasons") or []:
                match = pattern.search(str(reason))
                if not match:
                    continue

                signal_date = normalize_date(decision.get("as_of") or row_date)
                if signal_date:
                    by_date[signal_date] = {
                        "date": signal_date,
                        "entry_state": match.group(1) == "True",
                        "exit_state": match.group(2) == "True",
                    }
                break

    return [by_date[d] for d in sorted(by_date)]


def judge_holding_state(journal_rows, lean_grouped) -> dict:
    """일지와 LEAN의 보유/미보유 상태 비교. 신호 비교와 별개다."""
    flat = sorted(
        [fill for values in lean_grouped.values() for fill in values],
        key=lambda fill: (
            str(fill.get("date"))[:10],
            str(fill.get("time_utc") or ""),
        ),
    )
    running = 0.0
    lean_series = {}
    for fill in flat:
        d = normalize_date(fill.get("date"))
        if not d:
            continue
        running += float(fill.get("signed_quantity") or 0)
        lean_series[d] = running

    journal_dates = {
        normalize_date(row.get("trade_date"))
        for row in journal_rows
        if normalize_date(row.get("trade_date"))
    }
    all_dates = sorted(journal_dates | set(lean_series))

    lean_held_at = {}
    cumulative = 0.0
    for d in all_dates:
        if d in lean_series:
            cumulative = lean_series[d]
        lean_held_at[d] = cumulative > 0.5

    journal_by_date = {
        normalize_date(row.get("trade_date")): row
        for row in journal_rows
        if normalize_date(row.get("trade_date"))
    }
    matches, mismatches = [], []
    for d in all_dates:
        if d not in journal_by_date:
            continue
        journal_held = journal_qty(journal_by_date[d]) > 0
        lean_held = lean_held_at[d]
        if journal_held == lean_held:
            matches.append(d)
        else:
            mismatches.append((d, journal_held, lean_held))
    return {"matches": matches, "mismatches": mismatches}


def judge_order(journal_rows, lean_grouped) -> dict:
    journal_by_date = {
        normalize_date(row.get("trade_date")): row
        for row in journal_rows if normalize_date(row.get("trade_date"))
    }
    matches, mismatches, skipped = [], [], []
    for d, lean_list in lean_grouped.items():
        row = journal_by_date.get(d)
        if row is None or not row.get("fills"):
            skipped.append(d)
            continue
        lean_sides = {fill.get("direction") for fill in lean_list}
        journal_sides = {fill.get("side") for fill in row["fills"]}
        if lean_sides == journal_sides:
            matches.append(d)
        else:
            mismatches.append((d, journal_sides, lean_sides))
    return {"matches": matches, "mismatches": mismatches, "skipped": skipped}


def judge_price(journal_rows, lean_grouped) -> dict:
    """같은 날 체결가 차이. 체결 시점 차이를 감안한 참고값."""
    journal_by_date = {
        normalize_date(row.get("trade_date")): row
        for row in journal_rows if normalize_date(row.get("trade_date"))
    }
    results, skipped = [], []
    for d, lean_list in lean_grouped.items():
        row = journal_by_date.get(d)
        if row is None or not row.get("fills"):
            skipped.append(d)
            continue
        for lean_fill in lean_list:
            journal_fill = next(
                (
                    fill for fill in row["fills"]
                    if fill.get("side") == lean_fill.get("direction")
                    and str(fill.get("symbol", "")).startswith(TICKER_PREFIX)
                ),
                None,
            )
            if not journal_fill:
                continue
            try:
                lean_price = float(lean_fill["fill_price"])
                journal_price = float(journal_fill["fill_price"])
            except (KeyError, TypeError, ValueError):
                skipped.append(d)
                continue
            bp = abs(lean_price - journal_price) / lean_price * 10000 if lean_price else None
            results.append({
                "date": d,
                "side": lean_fill["direction"],
                "lean": lean_price,
                "journal": journal_price,
                "bp": bp,
            })
    return {"results": results, "skipped": skipped}


def judge_fee(journal_rows, lean_stats, lean_fills) -> dict:
    """일지와 LEAN의 거래대금 대비 비용 요율(bp)을 비교."""
    journal_cost, journal_gross, journal_failed = 0.0, 0.0, 0

    for row in journal_rows:
        for fill in row.get("fills") or []:
            cost = get_fill_cost(fill.get("cost"))
            gross = get_fill_gross(fill.get("cost"), fill)
            if cost is None or gross is None or gross <= 0:
                journal_failed += 1
            else:
                journal_cost += cost
                journal_gross += gross

    lean_stats = lean_stats if isinstance(lean_stats, dict) else {}
    lean_cost = parse_lean_fees(lean_stats.get("Total Fees", ""))
    lean_fills = lean_fills if isinstance(lean_fills, list) else []
    lean_gross, lean_failed = 0.0, 0

    for fill in lean_fills:
        if not isinstance(fill, dict):
            lean_failed += 1
            continue
        try:
            quantity = abs(float(fill.get("quantity", fill.get("signed_quantity"))))
            price = float(fill.get("fill_price"))
        except (TypeError, ValueError):
            lean_failed += 1
            continue
        if quantity <= 0 or price <= 0:
            lean_failed += 1
            continue
        lean_gross += quantity * price

    reasons = []
    if journal_failed:
        reasons.append(f"일지 비용/거래대금 파싱 실패 {journal_failed}건")
    if not lean_fills:
        reasons.append("LEAN 체결 목록 없음")
    if lean_failed:
        reasons.append(f"LEAN 체결 파싱 실패 {lean_failed}건")
    if lean_cost is None:
        reasons.append("LEAN 총 수수료 파싱 실패")
    if journal_gross <= 0:
        reasons.append("일지 거래대금 없음")
    if lean_gross <= 0:
        reasons.append("LEAN 거래대금 없음")

    if reasons:
        return {
            "verdict": "판정 불가",
            "reason": " / ".join(reasons),
            "j_cost": journal_cost,
            "j_gross": journal_gross,
            "l_cost": lean_cost,
            "l_gross": lean_gross,
        }

    journal_bp = journal_cost / journal_gross * 10000
    lean_bp = lean_cost / lean_gross * 10000
    return {
        "verdict": "참고용(요율)",
        "j_bp": journal_bp,
        "l_bp": lean_bp,
        "delta_bp": lean_bp - journal_bp,
        "j_cost": journal_cost,
        "j_gross": journal_gross,
        "l_cost": lean_cost,
        "l_gross": lean_gross,
    }


def render(target, journal_count, signal_cmp, holding, order, price, fee, lean_stats) -> str:
    def icon(verdict):
        return {
            "일치": "✅",
            "불일치": "❌",
            "판정 불가": "⏸️",
            "참고용(요율)": "ℹ️",
            "참고용(시점차)": "ℹ️",
        }.get(verdict, "❓")

    if signal_cmp.get("status") != "compared":
        signal_verdict = "판정 불가"
        signal_note = signal_cmp.get("reason", "비교 가능한 신호 없음")
    else:
        signal_verdict = (
            "불일치" if signal_cmp.get("mismatch_date_count", 0) else "일치"
        )
        signal_note = (
            f"공통 날짜 {signal_cmp['matched_date_count']}일 · "
            f"진입 {signal_cmp['entry_match_count']}/"
            f"{signal_cmp['entry_compared_count']} "
            f"({signal_cmp['entry_match_rate_pct']}%) · "
            f"청산 {signal_cmp['exit_match_count']}/"
            f"{signal_cmp['exit_compared_count']} "
            f"({signal_cmp['exit_match_rate_pct']}%) · "
            f"일지에만 {signal_cmp['tradingview_only_date_count']}일 · "
            f"LEAN에만 {signal_cmp['lean_only_date_count']}일"
        )

    holding_verdict = "불일치" if holding["mismatches"] else "일치"
    holding_note = (
        f"일치 {len(holding['matches'])}일 · "
        f"불일치 {len(holding['mismatches'])}일"
    )

    order_verdict = "불일치" if order["mismatches"] else "일치"
    order_note = (
        f"일치 {len(order['matches'])} / "
        f"불일치 {len(order['mismatches'])} / "
        f"스킵 {len(order['skipped'])}"
    )

    if not price["results"]:
        price_verdict = "판정 불가"
        price_note = "양쪽 체결 매칭 없음"
    else:
        valid_bp = [item["bp"] for item in price["results"] if item["bp"] is not None]
        max_bp = max(valid_bp, default=0)
        price_verdict = "참고용(시점차)"
        price_note = f"{len(price['results'])}건 매칭, 최대 {max_bp:.1f}bp (체결 시점 차이 포함)"

    if fee["verdict"] == "참고용(요율)":
        fee_note = (
            f"일지 {fee['j_bp']:.2f}bp "
            f"(비용 ₩{fee['j_cost']:,.2f} / 대금 ₩{fee['j_gross']:,.0f}) · "
            f"LEAN {fee['l_bp']:.2f}bp "
            f"(비용 ₩{fee['l_cost']:,.2f} / 대금 ₩{fee['l_gross']:,.0f}) · "
            f"차이(LEAN−일지) {fee['delta_bp']:+.2f}bp"
        )
    else:
        fee_note = fee.get("reason", "")

    md = f"""## 📊 {target} LEAN ↔ 그림자 일지 대조 (v4)

**기간**: {START_DATE} ~ {target} · **일지**: {journal_count}행 · **판**: `{JOURNAL_RULE_ID}` v{JOURNAL_VERSION_NO}

### 자동 판정 요약

| 층 | 판정 | 근거 |
|---|---|---|
| 1. 진입·청산 신호 | {icon(signal_verdict)} {signal_verdict} | {signal_note} |
| 2. 보유 상태 | {icon(holding_verdict)} {holding_verdict} | {holding_note} |
| 3. 주문 방향 | {icon(order_verdict)} {order_verdict} | {order_note} |
| 4. 체결가 | {icon(price_verdict)} {price_verdict} | {price_note} |
| 5. 비용(요율) | {icon(fee['verdict'])} {fee['verdict']} | {fee_note} |
| 수량 | ⏸️ 제외 | LEAN 전액 배분과 일지 주문 규모가 다름 |
| 회전·성과 | ⏸️ 제외 | 체결 수량·빈도 차이 및 비교 표본 한계 |

### 층 1 세부: 진입·청산 신호 불일치

"""
    if signal_cmp.get("status") == "compared" and signal_cmp.get("mismatch_dates"):
        md += (
            "| 날짜 | 일지 진입 | LEAN 진입 | 진입 일치 | "
            "일지 청산 | LEAN 청산 | 청산 일치 |\n"
            "|---|---|---|---|---|---|---|\n"
        )
        for item in signal_cmp["mismatch_dates"]:
            def fmt(value):
                return "—" if value is None else ("True" if value else "False")
            md += (
                f"| {item['date']} | {fmt(item['tradingview_entry_state'])} "
                f"| {fmt(item['lean_entry_state'])} | {fmt(item['entry_match'])} "
                f"| {fmt(item['tradingview_exit_state'])} "
                f"| {fmt(item['lean_exit_state'])} | {fmt(item['exit_match'])} |\n"
            )
    elif signal_cmp.get("status") == "compared":
        md += "_공통 날짜에서 진입·청산 상태 불일치 없음_\n"
    else:
        md += f"_비교 불가: {signal_cmp.get('reason', '원인 미상')}_\n"

    md += "\n### 층 2 세부: 보유 상태 불일치\n"
    if holding["mismatches"]:
        md += "| 날짜 | 일지 보유 | LEAN 보유 |\n|---|---|---|\n"
        for d, journal_held, lean_held in holding["mismatches"]:
            md += f"| {d} | {'보유' if journal_held else '미보유'} | {'보유' if lean_held else '미보유'} |\n"
    else:
        md += "_없음_\n"

    md += "\n### 층 4 세부: 체결 가격\n"
    if price["results"]:
        md += "| 날짜 | 방향 | LEAN 가격 | 일지 가격 | 차이(bp) |\n|---|---|---:|---:|---:|\n"
        for item in price["results"]:
            bp = "—" if item["bp"] is None else f"{item['bp']:.1f}"
            md += (
                f"| {item['date']} | {item['side']} | {item['lean']:,.2f} "
                f"| {item['journal']:,.2f} | {bp} |\n"
            )
    else:
        md += "_매칭 없음_\n"

    md += (
        "\n---\n"
        "*자동 생성 v4: `scripts/daily_lean_reconcile.py`*\n"
        "*주의: 이 보고서는 일지 규칙 상태와 LEAN 신호의 비교이며, "
        "실제 TradingView CSV와의 교차검증을 의미하지 않습니다.*\n"
    )
    return md


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=str(date.today()))
    args = parser.parse_args()
    target = datetime.strptime(args.date, "%Y-%m-%d").date()
    if target.weekday() >= 5:
        print("📅 주말 종료")
        return

    print(f"🚀 {target} 대조 시작 (v4)")
    await pull_hf_ledger()
    journal_rows = await load_journal(target)
    last_journal_date = max(
        normalize_date(row["trade_date"]) for row in journal_rows
        if normalize_date(row.get("trade_date"))
    )
    end_date = min(target, date.fromisoformat(last_journal_date))
    print(f"   일지 {len(journal_rows)}행, 마지막 {last_journal_date} → LEAN 종료일 {end_date}")

    lean = await run_lean(end_date)
    lean_fills = lean.get("lean_fills") or []
    lean_grouped = group_fills_by_date(lean_fills)
    print(f"▶ [3/4] 판정 (LEAN 체결 {sum(len(values) for values in lean_grouped.values())}건)")

    journal_signals = extract_journal_signals(journal_rows)
    lean_signals = lean.get("lean_signals") or []
    signal_cmp = tv.compare_signals(journal_signals, lean_signals)
    holding = judge_holding_state(journal_rows, lean_grouped)
    order = judge_order(journal_rows, lean_grouped)
    price = judge_price(journal_rows, lean_grouped)
    fee = judge_fee(journal_rows, lean.get("lean_statistics") or {}, lean_fills)

    print(
        f"   신호: 일지 {len(journal_signals)}일 / LEAN {len(lean_signals)}일 / "
        f"상태 {signal_cmp.get('status')}"
    )

    markdown = render(
        end_date,
        len(journal_rows),
        signal_cmp,
        holding,
        order,
        price,
        fee,
        lean.get("lean_statistics") or {},
    )

    out_dir = (
        ROOT / "docs" / "phase-3" / "04-testing"
        / "lean-검증-2026-10-26" / "daily"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{target}_v4.md"
    out_file.write_text(markdown, encoding="utf-8")

    print(f"\n▶ [4/4] 저장: {out_file}")
    print("=" * 80)
    print("이슈 #333 붙여넣기용:")
    print("=" * 80 + "\n")
    print(markdown)


if __name__ == "__main__":
    asyncio.run(main())
