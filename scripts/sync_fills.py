"""KIS 체결 내역을 받아 우리 요율표와 대조한다.

왜 있는가
---------
`app/services/trading_cost.py` 의 비용은 전부 **추정값**이다. 증권사가 실제로 뗀
금액과 맞대어 본 적이 없다. 이 스크립트가 그 첫 대조를 한다.

쓰는 법
-------
    # 조회만 (DB 를 건드리지 않는다)
    PYTHONPATH=. python scripts/sync_fills.py --days 90

    # 특정 기간
    PYTHONPATH=. python scripts/sync_fills.py --start 20260918 --end 20260919

    # 원문까지 보기
    PYTHONPATH=. python scripts/sync_fills.py --days 90 --raw

기본은 **모의계좌(KIS_MOCK_*)** 다. 실계좌(`--real`)는 승인 없이 쓰지 않는다.

토큰
----
KIS 는 토큰 발급에 간격 제한을 둔다. 받은 토큰을 `.kis_token_mock.json` 에 캐시해
재사용한다 (gitignore 대상 — 아래 `TOKEN_CACHE` 참고).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import trading_cost                      # noqa: E402
from app.services.brokers.kis import KISClient             # noqa: E402
from app.services.fill_sync import _is_etf                 # noqa: E402

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    """.env 를 읽는다 (python-dotenv 없이도 되게)."""
    path = ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def token_cache_path(paper: bool) -> Path:
    return ROOT / (".kis_token_mock.json" if paper else ".kis_token_real.json")


async def make_client(paper: bool) -> tuple[KISClient, str]:
    prefix = "KIS_MOCK_" if paper else "KIS_"
    app_key = os.getenv(f"{prefix}APP_KEY")
    app_secret = os.getenv(f"{prefix}APP_SECRET")
    account = os.getenv(f"{prefix}ACCOUNT_NO")
    if not (app_key and app_secret and account):
        raise SystemExit(
            f"{prefix}APP_KEY · {prefix}APP_SECRET · {prefix}ACCOUNT_NO 가 .env 에 있어야 합니다.\n"
            "  → 모의투자는 KIS 개발자센터에서 모의계좌를 먼저 개설해야 키가 나옵니다."
        )
    client = KISClient(app_key, app_secret, paper=paper)

    # 토큰 캐시: KIS 는 재발급 간격을 제한한다 (1분에 1회).
    cache = token_cache_path(paper)
    if cache.is_file():
        try:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            if datetime.fromisoformat(saved["expires_at"]) > datetime.now(timezone.utc):
                client._token = saved["access_token"]
                print(f"  토큰: 캐시 재사용 (만료 {saved['expires_at'][:19]})")
                return client, account.replace("-", "")
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    info = await client.get_token()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(info.expires_in - 600, 60))
    cache.write_text(json.dumps({
        "access_token": info.access_token,
        "expires_at": expires_at.isoformat(),
    }), encoding="utf-8")
    print(f"  토큰: 새로 발급 (캐시 {cache.name})")
    return client, account.replace("-", "")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90, help="오늘로부터 며칠 전까지 (기본 90)")
    ap.add_argument("--start", help="YYYYMMDD (주면 --days 를 무시한다)")
    ap.add_argument("--end", help="YYYYMMDD")
    ap.add_argument("--symbol", help="종목코드 6자리 (생략하면 전체)")
    ap.add_argument("--raw", action="store_true", help="응답 원문도 출력")
    ap.add_argument("--real", action="store_true", help="⚠️ 실계좌로 조회 (기본은 모의)")
    args = ap.parse_args()

    load_env()
    paper = not args.real
    today = datetime.now(KST).date()
    end = args.end or today.strftime("%Y%m%d")
    start = args.start or (today - timedelta(days=args.days)).strftime("%Y%m%d")

    print(f"― KIS 체결 조회 ({'모의' if paper else '⚠️ 실계좌'}) ―")
    print(f"  기간 {start} ~ {end}" + (f" · 종목 {args.symbol}" if args.symbol else ""))
    client, account = await make_client(paper)

    fills = await client.get_daily_fills(account, start, end, args.symbol)
    print(f"  받은 행 {len(fills)}건\n")
    if not fills:
        print("  체결 내역이 없습니다.")
        print("  → 조회 경로 자체는 동작했습니다 (rt_cd=0). 주문을 낸 뒤 다시 실행하세요.")
        print("  ※ 국내주식 장은 평일 09:00~15:30 (KST) 입니다.")
        return 0

    print(f"{'주문번호':>10s} {'종목':>8s} {'구분':>4s} {'수량':>6s} {'체결가':>10s} "
          f"{'체결금액':>12s} {'증권사제비용':>12s} {'우리추정':>12s} {'차이':>10s}")
    print("─" * 100)

    matched = mismatched = no_info = 0
    for f in fills:
        if f.cancelled or f.filled_quantity <= 0:
            continue
        est = trading_cost.order_costs(
            side=f.side, price=f.avg_fill_price, quantity=f.filled_quantity,
            when=f.order_date or today, market=trading_cost.market_of(f.symbol),
            is_etf=_is_etf(f.name),
        )
        if f.total_fees is None:
            no_info += 1
            shown, diff_s = "없음", "-"
        else:
            diff = f.total_fees - est.total_cost
            if abs(diff) <= 1.0:
                matched += 1
            else:
                mismatched += 1
            shown, diff_s = f"{f.total_fees:,.2f}", f"{diff:+,.2f}"
        print(f"{f.broker_order_id:>10s} {f.symbol:>8s} {f.side:>4s} {f.filled_quantity:>6d} "
              f"{f.avg_fill_price:>10,.0f} {f.gross_amount:>12,.0f} {shown:>12s} "
              f"{est.total_cost:>12,.2f} {diff_s:>10s}")
        if args.raw:
            print("    원문:", json.dumps(f.raw, ensure_ascii=False))

    print("─" * 100)
    print(f"  일치 {matched}건 · 불일치 {mismatched}건 · 제비용 미제공 {no_info}건")
    if mismatched:
        print("  🔴 불일치가 있습니다 — 요율표(app/services/trading_cost.py)를 다시 봐야 합니다.")
    elif matched:
        print("  🟢 우리 요율표가 증권사 정산과 일치합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
