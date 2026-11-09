import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.services import paper_trading as pt


@pytest.mark.parametrize(
    "cache_age,quote_age,expected",
    [
        (0, 0, True),
        (30, 30, True),
        (30.01, 0, False),
        (0, 30.01, False),
        (None, 0, False),
        (0, None, False),
        (-1, 0, False),
        (0, -1, False),
    ],
)
def test_order_quote_requires_both_ages_within_30_seconds(
    monkeypatch, cache_age, quote_age, expected
):
    fixed_now = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr(pt, "datetime", FrozenDateTime)

    async def fake_tickers(codes, *, include_price_audits=False):
        assert codes == ["KRW-BTC"]
        assert include_price_audits is True
        as_of = (
            (fixed_now - timedelta(seconds=quote_age)).isoformat()
            if quote_age is not None else None
        )
        return [{
            "market": "KRW-BTC",
            "price": 100_000_000,
            "as_of": as_of,
            "_price_audit": {"cache_age_sec": cache_age},
        }]

    monkeypatch.setattr(pt, "upbit_tickers", fake_tickers)

    if expected:
        assert asyncio.run(pt.upbit_trade_price("KRW-BTC")) == 100_000_000
    else:
        with pytest.raises(pt.PaperTradeError):
            asyncio.run(pt.upbit_trade_price("KRW-BTC"))
