"""해외 종목 주문의 길 가르기 — 한 곳 (2026-10-16 모의투자 점검 🔴).

왜 필요한가
-----------
모의 장부(`PaperAccount` 현금 · `Portfolio` book=PAPER)는 **원화 하나**다. 미국주식 › 주문/매매가 달러 시세를
원화 가상 매매(`POST /api/orders` · broker virtual)로 보내자, 서버가 그 값을 원화 현금에서 그대로 빼고(포드 1주
$12.31 → 현금 12.31원) 국내 매도세까지 매겼다 — 다른 화면은 같은 보유를 원화 환산가로 평가해 손익이 +133,658% 로
보였다. 해외 종목은 환율을 곱하는 모의 주문 길(`/api/paper/stocks/orders` · `paper_trading.resolve_stock`)로만 간다.

무엇을 두나
- `is_domestic(symbol)` — 국내 종목인가(`.KS` · `.KQ` · `.KN` 접미사 · 6자리 숫자 · 숫자가 섞인 6자리 영숫자 새 코드).
  모르면 국내가 아니다(해외로 보아 원화 가상 매매에 넣지 않는다 — 말없이 잘못 적는 것보다 막는 쪽).
- `VIRTUAL_REFUSAL` — 원화 가상 매매가 해외 종목을 받지 않을 때의 까닭 글(서버 한 곳).

남은 것 — 해외 종목의 비용(증권사 해외 수수료 · 매도 SEC 수수료)은 비용 모듈(`trading_cost` · 강민석 님 몫 C3)이
아직 국내 셋만 안다. 그래서 모의 주문 길도 해외 매도에서 멈추고(시장 이름 오류), 매수는 국내 수수료로 셈한다 — 이슈로 넘김.
"""
from __future__ import annotations

import re

_KRX_SUFFIX = (".KS", ".KQ", ".KN")

VIRTUAL_REFUSAL = ("해외 종목은 원화 가상 매매 장부에 바로 넣지 않습니다 — 달러 금액이 원화로 잘못 들어갑니다. "
                   "미국주식 › 주문/매매(환율을 곱하는 모의 주문)를 쓰세요.")


def is_domestic(symbol: str | None) -> bool:
    """국내(KRX) 종목인가 — 접미사가 있거나 6자리 코드(숫자 · 숫자가 섞인 새 코드)면 국내."""
    s = (symbol or "").strip().upper()
    if not s:
        return False
    if s.endswith(_KRX_SUFFIX):
        return True
    return bool(re.fullmatch(r"\d{6}", s) or (re.fullmatch(r"[0-9A-Z]{6}", s) and re.search(r"\d", s)))
