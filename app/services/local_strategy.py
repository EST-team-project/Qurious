"""내가 저장한 카드의 명시적 가상 실행 선택. 합격 판정이나 외부 주문 권한이 아니다."""
from copy import deepcopy
import json
import sqlite3

from sqlalchemy import select, text

from app.models import Portfolio, StrategyRuntime, OrderIntent
from app.services import collector_db, strategy_card_store, strategy_v2
from app.services.execution_control import digest


def load(user_id, card_id):
    path = strategy_card_store.files(str(user_id)).get(card_id)
    if path is None:
        raise ValueError("내가 저장한 전략 카드를 찾을 수 없습니다.")
    try:
        card = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError("저장한 전략 카드를 읽을 수 없습니다.") from exc
    strategy_v2.validate_card(card)
    return card


def market_for(code):
    path = collector_db.db_path()
    if path is None:
        raise ValueError("종목의 시장과 원주가 자료를 확인하지 못했습니다.")
    try:
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True) as db:
            row = db.execute('SELECT mrkt_ctg FROM price_daily WHERE srtn_cd=? ORDER BY bas_dt DESC LIMIT 1', (code,)).fetchone()
    except sqlite3.Error as exc:
        raise ValueError('종목의 시장과 원주가 자료를 읽지 못했습니다.') from exc
    if not row or row[0] not in ('KOSPI', 'KOSDAQ'):
        raise ValueError("가상 실행은 수집 원주가가 있는 국내 주식만 지원합니다.")
    return row[0]


def snapshot(user_id, card_id):
    card = load(user_id, card_id)
    market = market_for(card['universe'][0])
    original_hash = strategy_v2.validate_card(card)
    spec = deepcopy(card)
    # 카드 판 2는 형식의 판이다. 내용별 실행 ID를 별도로 고정해 같은 판 덮어쓰기를 막는다.
    spec['strategy_id'] = 'local_' + original_hash[:32]
    return dict(card_id=card_id, owner=str(user_id), original_hash=original_hash,
                spec=spec, spec_hash=strategy_v2.validate_card(spec), test_only=True,
                symbol=card['universe'][0]+('.KQ' if market == 'KOSDAQ' else '.KS'))


def selected(row, user_id):
    saved = getattr(row, 'quant_local_strategy', None)
    if not saved:
        return None
    if (not isinstance(saved, dict) or saved.get('owner') != str(user_id) or saved.get('test_only') is not True
            or not isinstance(saved.get('spec'), dict)):
        raise ValueError("선택한 개인 전략의 소유자를 확인하지 못했습니다.")
    spec = saved['spec']
    if (saved.get('spec_hash') != strategy_v2.validate_card(spec)
            or (row.quant_strategy_id, row.quant_strategy_version) != (spec['strategy_id'], spec['version'])
            or saved.get('symbol') not in (spec['universe'][0]+'.KS', spec['universe'][0]+'.KQ')):
        raise ValueError("선택한 개인 전략의 고정 내용이 변경됐습니다.")
    return deepcopy(saved)


def summaries(user_id):
    result = []
    for card_id in strategy_card_store.files(str(user_id)):
        try:
            card = load(user_id, card_id)
            result.append(dict(card_id=card_id, name=card.get('name') or card_id, version=card['version'],
                               executable=True, test_only=True, fingerprint=strategy_v2.validate_card(card)))
        except ValueError as exc:
            result.append(dict(card_id=card_id, name=card_id, executable=False, test_only=True, reason=str(exc)))
    return result


async def ensure_switchable(db, row, user_id, next_spec):
    old = getattr(row, 'quant_local_strategy', None)
    if digest(old) == digest(next_spec):
        return
    ref = digest([str(user_id), 'QUANT'])
    key = int.from_bytes(bytes.fromhex(ref[:16]), 'big', signed=True)
    if not await db.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'), {'key': key}):
        raise ValueError("계좌 실행 중입니다. 끝난 뒤 전략을 바꾸세요.")
    await db.refresh(row)
    if digest(getattr(row, 'quant_local_strategy', None)) != digest(old):
        raise ValueError("전략 설정이 다른 요청에서 변경됐습니다. 다시 확인하세요.")
    if getattr(row, 'quant_auto_enabled', False):
        raise ValueError("자동 실행을 중지한 뒤 전략을 바꾸세요.")
    held = await db.scalar(select(Portfolio.id).where(Portfolio.user_id == user_id, Portfolio.book == 'QUANT', Portfolio.quantity > 0).limit(1))
    runtimes = (await db.scalars(select(StrategyRuntime).where(StrategyRuntime.user_id == user_id, StrategyRuntime.book == 'V2_VIRTUAL'))).all()
    outstanding = await db.scalar(select(OrderIntent.intent_id).where(OrderIntent.user_id == user_id,
        OrderIntent.book == 'QUANT', OrderIntent.status.not_in(('filled', 'skipped', 'error', 'cancelled', 'rejected'))).limit(1))
    if held or outstanding or any(r.state.get('quantity') or r.state.get('pending') for r in runtimes):
        raise ValueError("기존 QUANT 보유·예약·미확정 주문을 정리한 뒤 전략을 바꾸세요.")
