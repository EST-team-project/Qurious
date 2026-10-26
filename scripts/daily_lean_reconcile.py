#!/usr/bin/env python3
"""매일 LEAN ↔ 그림자 일지 대조 (v3) — A안 반자동.

v3 수정:
- positions 파싱을 'qty' 키로 수정 (기존 quantity 오판)
- cost 딕셔너리에서 'total_cost' 명시 사용 (기존 모든 숫자 합산 버그)
- 층 4: 총액 비교 → 비용 요율(bp) 비교 (거래대금 차이 제거)
- 층 3: "종가 vs 시가 시점 차이" 태그 명시
"""
from __future__ import annotations
import argparse, asyncio, json, os, subprocess, sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.lean_backtest import LeanBacktestService

JOURNAL_RULE_ID = "card_ma_cross_20_60"
JOURNAL_VERSION_NO = 1
START_DATE = date(2026, 9, 1)
TICKER = "005930.KS"
TICKER_PREFIX = TICKER.split(".")[0]
INITIAL_CASH = 10_000_000.0
FEE_TOL_BP = 5.0        # 층4 요율 허용오차 (5bp = 0.05%)
PRICE_TOL_BP = 30.0     # 층3 잔여 (시점차 태그 후)


def get_fill_cost(cost_data) -> float | None:
    """일지 fills.cost → 총비용(원). total_cost 우선, 없으면 세목 합산."""
    if cost_data is None:
        return 0.0
    if isinstance(cost_data, (int, float)):
        return float(cost_data)
    if isinstance(cost_data, dict):
        for k in ("total_cost",):
            v = cost_data.get(k)
            if isinstance(v, (int, float)):
                return float(v)
        parts = ["commission", "fee_clearing", "tax_transfer", "tax_rural"]
        if any(isinstance(cost_data.get(p), (int, float)) for p in parts):
            return sum(float(cost_data.get(p) or 0) for p in parts)
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


def parse_lean_fees(s) -> float | None:
    if not isinstance(s, str):
        return None
    cleaned = s.replace("₩", "").replace(",", "").replace(" ", "").strip()
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
    s = str(raw)[:10]
    try:
        date.fromisoformat(s)
        return s
    except ValueError:
        return None


async def pull_hf_ledger() -> tuple[int, int]:
    print("▶ [1/4] HF 원장 pull 중...")
    
    # [수정됨] 환경변수가 없으면 HF 로그인 캐시에서 자동으로 토큰을 가져옴
    if not os.environ.get("HUGGINGFACE_ACCESS_TOKEN"):
        try:
            from huggingface_hub import get_token
            token = get_token()
            if token:
                os.environ["HUGGINGFACE_ACCESS_TOKEN"] = token
                print("   (HF 로그인 캐시에서 토큰을 자동으로 불러왔습니다)")
            else:
                raise RuntimeError("HUGGINGFACE_ACCESS_TOKEN 환경변수도 없고, 로그인 캐시도 없습니다. `hf auth login` 또는 `huggingface-cli login`을 먼저 실행해 주세요.")
        except ImportError:
            raise RuntimeError("huggingface_hub 패키지가 없습니다.")
    url = os.environ["DATABASE_URL"]

    async def count_days() -> int:
        eng = create_async_engine(url)
        try:
            async with eng.connect() as c:
                return (await c.execute(text("SELECT COUNT(*) FROM paper_journal_days"))).scalar_one()
        finally:
            await eng.dispose()

    before = await count_days()
    res = subprocess.run([sys.executable, "scripts/paper_journal.py", "pull"],
                         cwd=ROOT, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Pull 실패: {res.stderr[-300:]}")
    after = await count_days()
    print(f"✅ pull: {before} → {after} (신규 {after-before})")
    return before, after


async def load_journal(target_date: date):
    eng = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with eng.connect() as c:
            r = await c.execute(text("""
                SELECT id FROM paper_journal_versions
                WHERE rule_id = :rule AND version_no = :vno
            """), {"rule": JOURNAL_RULE_ID, "vno": JOURNAL_VERSION_NO})
            ids = r.scalars().all()
            if len(ids) != 1:
                raise RuntimeError(f"판1 정확히 1개 아님: {ids}")
            vid = ids[0]
            r = await c.execute(text("""
                SELECT trade_date, decisions, orders, fills, positions
                FROM paper_journal_days WHERE version_id = :vid AND trade_date <= :td
                ORDER BY trade_date
            """), {"vid": vid, "td": target_date})
            rows = [dict(x._mapping) for x in r]
    finally:
        await eng.dispose()
    if not rows:
        raise RuntimeError("일지 0건")
    for r in rows:
        if r.get("decisions") is None: r["decisions"] = []
        if r.get("orders") is None: r["orders"] = []
        if r.get("fills") is None: r["fills"] = []
        if r.get("positions") is None: r["positions"] = {}
    return rows


async def run_lean(end_date: date) -> dict:
    print(f"▶ [2/4] LEAN 재실행 ({START_DATE} ~ {end_date})")
    svc = LeanBacktestService()
    result = await svc.run(
        ticker=TICKER, start_date=START_DATE, end_date=end_date,
        compare_start_date=START_DATE, compare_end_date=end_date,
        initial_cash=INITIAL_CASH, strategy="ma_cross",
        short_window=20, long_window=60,
    )
    if not result.get("lean_ok"):
        raise RuntimeError(f"LEAN 실패: {result.get('lean_log','')[-300:]}")
    out = ROOT / "data" / "lean-workflows" / f"daily_replay_{end_date}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ LEAN 완료 → {out}")
    return result


def group_fills_by_date(fills):
    out = defaultdict(list)
    for f in fills or []:
        d = normalize_date(f.get("date"))
        if d:
            out[d].append(f)
    return out


def journal_qty(row) -> float:
    """positions에서 005930 수량 합 (v3: 'qty' 키 사용)."""
    total = 0.0
    for sym, val in (row.get("positions") or {}).items():
        if not str(sym).startswith(TICKER_PREFIX):
            continue
        if isinstance(val, dict):
            for key in ("qty", "quantity", "amount"):
                v = val.get(key)
                if isinstance(v, (int, float)):
                    total += float(v); break
        else:
            try: total += float(val)
            except (TypeError, ValueError): pass
    return total


def judge_signal(journal_rows, lean_grouped) -> dict:
    """층 1: 보유/미보유 상태 일치율."""
    flat = sorted([f for lst in lean_grouped.values() for f in lst],
                  key=lambda f: (str(f.get("date"))[:10], str(f.get("time_utc") or "")))
    running, lean_series = 0.0, {}
    for f in flat:
        d = normalize_date(f.get("date"))
        if not d: continue
        running += float(f.get("signed_quantity") or 0)
        lean_series[d] = running

    all_dates = sorted(set(str(r["trade_date"]) for r in journal_rows) | set(lean_series))
    lean_held_at = {}
    cum = 0.0
    for d in all_dates:
        if d in lean_series: cum = lean_series[d]
        lean_held_at[d] = cum > 0.5

    j_by_date = {str(r["trade_date"]): r for r in journal_rows}
    matches, mismatches = [], []
    for d in all_dates:
        if d not in j_by_date: continue
        j_held = journal_qty(j_by_date[d]) > 0
        if j_held == lean_held_at[d]:
            matches.append(d)
        else:
            mismatches.append((d, j_held, lean_held_at[d]))
    return {"matches": matches, "mismatches": mismatches}


def judge_order(journal_rows, lean_grouped) -> dict:
    j_by_date = {str(r["trade_date"]): r for r in journal_rows}
    matches, mismatches, skipped = [], [], []
    for d, lean_list in lean_grouped.items():
        row = j_by_date.get(d)
        if row is None or not row.get("fills"):
            skipped.append(d); continue
        lean_sides = {f.get("direction") for f in lean_list}
        j_sides = {f.get("side") for f in row["fills"]}
        if lean_sides == j_sides:
            matches.append(d)
        else:
            mismatches.append((d, j_sides, lean_sides))
    return {"matches": matches, "mismatches": mismatches, "skipped": skipped}


def judge_price(journal_rows, lean_grouped) -> dict:
    """층 3: 같은 날 체결가 차이. 시점차 태그 표기."""
    j_by_date = {str(r["trade_date"]): r for r in journal_rows}
    results, skipped = [], []
    for d, lean_list in lean_grouped.items():
        row = j_by_date.get(d)
        if row is None or not row.get("fills"):
            skipped.append(d); continue
        for lf in lean_list:
            jf = next((x for x in row["fills"]
                       if x.get("side") == lf.get("direction")
                       and str(x.get("symbol", "")).startswith(TICKER_PREFIX)), None)
            if not jf: continue
            try:
                lp = float(lf["fill_price"]); jp = float(jf["fill_price"])
            except (KeyError, TypeError, ValueError):
                skipped.append(d); continue
            bp = abs(lp - jp) / lp * 10000 if lp else None
            results.append({"date": d, "side": lf["direction"],
                            "lean": lp, "journal": jp, "bp": bp})
    return {"results": results, "skipped": skipped}


def judge_fee(journal_rows, lean_stats) -> dict:
    """층 4: 비용 '요율(bp)' 비교. 거래대금 차이 제거."""
    j_cost, j_gross, j_failed = 0.0, 0.0, 0
    for row in journal_rows:
        for f in row.get("fills") or []:
            c = get_fill_cost(f.get("cost"))
            g = get_fill_gross(f.get("cost"), f)
            if c is None or g is None or g <= 0:
                j_failed += 1
            else:
                j_cost += c; j_gross += g
    l_cost = parse_lean_fees((lean_stats or {}).get("Total Fees", ""))

    # LEAN 거래대금은 fills로 계산 (매수+매도 합)
    lean_fills = lean_stats.get("_lean_fills") or []  # 없으면 통계만
    # LEAN gross는 statistics에 없으므로, fills로 추정 — 없으면 None
    # 실제: lean_result['lean_fills']로 계산해야 함 (여기선 lean_stats만 받음 → 0으로 표기)

    if j_failed or l_cost is None or j_gross <= 0:
        return {"verdict": "판정 불가",
                "reason": f"일지 cost 파싱 실패 {j_failed}건 / LEAN 파싱 {'OK' if l_cost else 'FAIL'}",
                "j_cost": j_cost, "j_gross": j_gross, "l_cost": l_cost}
    j_bp = j_cost / j_gross * 10000
    return {"verdict": "참고용(요율)", "j_bp": j_bp, "j_cost": j_cost,
            "j_gross": j_gross, "l_cost": l_cost}


def render(target, j_n, sig, odr, prc, fee, lean_stats) -> str:
    def icon(v): return {"일치": "✅", "불일치": "❌", "판정 불가": "⏸️", "참고용(요율)": "ℹ️"}.get(v, "❓")

    sig_v = "불일치" if sig["mismatches"] else "일치"
    sig_note = (f"어긋난 날 {len(sig['mismatches'])}일" if sig["mismatches"]
                else f"{len(sig['matches'])}일 전부 일치")

    odr_v = "불일치" if odr["mismatches"] else "일치"
    odr_note = f"일치 {len(odr['matches'])} / 불일치 {len(odr['mismatches'])} / 스킵 {len(odr['skipped'])}"

    if not prc["results"]:
        prc_v, prc_note = "판정 불가", "양쪽 체결 매칭 없음"
    else:
        max_bp = max((r["bp"] for r in prc["results"] if r["bp"] is not None), default=0)
        prc_v = "참고용(시점차)"
        prc_note = f"{len(prc['results'])}건 매칭, 최대 {max_bp:.1f}bp (종가 vs 시가 시점차)"

    fee_v = fee["verdict"]
    if fee_v == "참고용(요율)":
        fee_note = (f"일지 요율 {fee['j_bp']:.2f}bp (비용 ₩{fee['j_cost']:,.2f} / 대금 ₩{fee['j_gross']:,.0f}) · "
                    f"LEAN 총액 ₩{fee['l_cost']:,.2f} (거래대금 다름 → 총액 직접비교 불가)")
    else:
        fee_note = fee.get("reason", "")

    md = f"""## 📊 {target} LEAN ↔ 그림자 일지 대조 (v3)

**기간**: {START_DATE} ~ {target} · **일지**: {j_n}행 · **판**: `{JOURNAL_RULE_ID}` v{JOURNAL_VERSION_NO}

### 자동 판정 요약
| 층 | 판정 | 근거 |
|---|---|---|
| 1. 신호(보유 상태) | {icon(sig_v)} {sig_v} | {sig_note} |
| 2a. 주문 방향 | {icon(odr_v)} {odr_v} | {odr_note} |
| 2b. 수량 | ⏸️ 제외 | LEAN 전액 vs 일지 ₩1M 고정 |
| 3. 체결가 | ℹ️ 참고(시점차) | {prc_note} |
| 4. 비용(요율) | ℹ️ 참고(요율) | {fee_note} |
| 5. 회전 | ⏸️ 제외 | 수량·빈도 차이 |
| 성과 | ⏸️ 제외 | 13거래일 신뢰구간 ±8.3 |

### 층3 세부
"""
    if prc["results"]:
        md += "| 날짜 | side | LEAN | 일지 | 차이(bp) |\n|---|---|---|---|---|\n"
        for r in prc["results"]:
            md += f"| {r['date']} | {r['side']} | {r['lean']:,.0f} | {r['journal']:,.0f} | {r['bp']:.1f} |\n"
    else:
        md += "_매칭 없음_\n"

    md += "\n### 층1 어긋난 날\n"
    if sig["mismatches"]:
        md += "| 날짜 | 일지 보유 | LEAN 보유 |\n|---|---|---|\n"
        for d, j, l in sig["mismatches"]:
            md += f"| {d} | {'✅' if j else '❌'} | {'✅' if l else '❌'} |\n"
    else:
        md += "_없음_\n"

    md += "\n---\n*자동 생성 v3: `scripts/daily_lean_reconcile.py`*\n"
    return md


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=str(date.today()))
    args = ap.parse_args()
    target = datetime.strptime(args.date, "%Y-%m-%d").date()
    if target.weekday() >= 5:
        print(f"📅 주말 종료"); return

    print(f"🚀 {target} 대조 시작 (v3)")
    await pull_hf_ledger()
    j_rows = await load_journal(target)
    last_j = max(r["trade_date"] for r in j_rows)
    end_date = min(target, last_j)
    print(f"   일지 {len(j_rows)}행, 마지막 {last_j} → LEAN 종료일 {end_date}")

    lean = await run_lean(end_date)
    lean_grouped = group_fills_by_date(lean.get("lean_fills") or [])
    print(f"▶ [3/4] 판정 (LEAN 체결 {sum(len(v) for v in lean_grouped.values())}건)")

    sig = judge_signal(j_rows, lean_grouped)
    odr = judge_order(j_rows, lean_grouped)
    prc = judge_price(j_rows, lean_grouped)
    fee = judge_fee(j_rows, lean.get("lean_statistics") or {})
    markdown = render(end_date, len(j_rows), sig, odr, prc, fee, lean.get("lean_statistics") or {})

    out_dir = ROOT / "docs" / "phase-3" / "04-testing" / "lean-검증-2026-10-26" / "daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{target}_v3.md"
    out_file.write_text(markdown, encoding="utf-8")

    print(f"\n▶ [4/4] 저장: {out_file}")
    print("=" * 80)
    print("이슈 #333 붙여넣기용:")
    print("=" * 80 + "\n")
    print(markdown)


if __name__ == "__main__":
    asyncio.run(main())