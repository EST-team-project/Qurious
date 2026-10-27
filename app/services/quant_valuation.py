"""QUANT 장부의 공통 시세·평가 기준 (#284). 판단 일봉과 체결/평가 가격은 별개다."""
from __future__ import annotations

import math
from sqlalchemy import select
from app.models import Portfolio, QuantVirtualAccount, PORTFOLIO_BOOK_QUANT
from app.services import quote_now


async def quote(db, user_id, symbol: str, *, fresh: bool = False) -> dict:
    try:
        q = await quote_now.quote_now(symbol, db=db, user_id=user_id, fresh=fresh)
        price = float(q['price'])
        if isinstance(q['price'], bool) or not math.isfinite(price) or price <= 0:
            raise ValueError
        if q.get('source') not in ('kis_user', 'kis_gateway', 'delayed', 'collector'):
            raise ValueError
        if not q.get('as_of') or not q.get('label'):
            raise ValueError
    except Exception:
        raise ValueError(f'{symbol} 가격·출처·기준 시각을 확인하지 못했습니다.') from None
    return {k: q.get(k) for k in ('source', 'as_of', 'fetched_at', 'label', 'fallback')} | {'price': price}


async def snapshot(db, user_id) -> dict:
    """사이클·위험 상태·대시보드가 같은 계정별 조회 순서를 사용한다. 누락은 평가 불가."""
    acc = (await db.execute(select(QuantVirtualAccount).where(QuantVirtualAccount.user_id == user_id))).scalar_one_or_none()
    out = {'has_account': acc is not None, 'complete': True, 'cash': float(acc.cash_balance) if acc else 0.0,
           'initial': float(acc.initial_capital) if acc else 0.0, 'quotes': {}, 'values': {},
           'positions': 0, 'missing': [], 'label': '보유 없음 · 현금 기준'}
    if acc:
        rows = (await db.execute(select(Portfolio).where(
            Portfolio.user_id == user_id, Portfolio.book == PORTFOLIO_BOOK_QUANT))).scalars().all()
        for p in rows:
            if p.quantity <= 0:
                continue
            out['positions'] += 1
            try:
                q = await quote(db, user_id, p.symbol)
            except ValueError:
                out['missing'].append(p.symbol)
                continue
            out['quotes'][p.symbol] = q
            out['values'][p.symbol] = p.quantity * q['price']
    out['complete'] = not out['missing']
    out['equity'] = out['cash'] + sum(out['values'].values()) if out['complete'] else None
    if out['missing']:
        out['label'] = '평가 보류 · 가격 확인 불가: ' + ', '.join(out['missing'])
    elif out['quotes']:
        out['label'] = '평가 기준: ' + ' / '.join(dict.fromkeys(q['label'] for q in out['quotes'].values()))
    return out


def basis(snap: dict) -> dict:
    return {'complete': snap['complete'], 'label': snap['label'], 'missing': snap['missing'],
            'quotes': {s: {k: q[k] for k in ('source', 'as_of', 'fetched_at', 'label')}
                       for s, q in snap['quotes'].items()}}
