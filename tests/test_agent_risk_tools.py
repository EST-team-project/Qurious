"""대화 에이전트의 재무 · 신용 위험 도구 시험 (TC-AGR) — `app/lib/risk_tools.py` · `app/services/langgraph_agent.py` 갈림 넷.

여기서 지키는 것 —
1. 강사님 프롬프트의 옛 CB 도구 두 줄이 새 도구 둘로 바뀐다(강사님이 그 글을 고치면 이 시험이 알린다).
2. 옛 이름으로 불러도 CB 표를 읽지 않고 「자료 없음 — 새 도구를 쓰라」 한 줄.
3. 새 도구 — company_health(6자리 코드만 · 서버 문장 · 출처) · credit_spread(ECOS · 없으면 자료 없음).
4. **되풀이 막기** — 같은 도구 · 같은 인자 · 「자료 없음」 이 나온 도구를 또 고르면 답으로. 가짜 모델이 옛 도구만 계속 골라도
   두 번째 추론에서 끝난다(옛 코드는 MAX_STEPS 6 까지 돌며 약 2분).

네트워크 · DB · 실제 모델을 쓰지 않는다.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.lib import risk_tools as R
from app.services import langgraph_agent as L


def test_prompt_swap_replaces_old_cb_tools():
    """TC-AGR-01 · 옛 두 줄(설명 · args)이 새 두 줄로 — 나머지 도구 · 원칙 글은 그대로."""
    assert "query_personal_cb" not in L.SYSTEM_PROMPT and "query_corporate_cb" not in L.SYSTEM_PROMPT
    assert "1. company_health" in L.SYSTEM_PROMPT and "2. credit_spread" in L.SYSTEM_PROMPT
    assert "3. search_bank_products" in L.SYSTEM_PROMPT and "final_answer" in L.SYSTEM_PROMPT
    assert R.swap_prompt("바꿀 줄이 없는 글") == "바꿀 줄이 없는 글"


def test_old_tool_names_answer_no_data_without_reading_tables(monkeypatch):
    """TC-AGR-02 · 옛 이름 → 「자료 없음 · 새 도구」 한 줄 · CB 표를 읽는 함수를 부르지 않는다 · 은행 · 펀드 도구는 그대로 넘김."""
    for act in R.OLD_TOOLS:
        out = asyncio.run(R.run(None, act, {"period": "202212"}))
        assert "자료가 없습니다" in out and "company_health" in out and "credit_spread" in out
    assert asyncio.run(R.run(None, "search_funds", {})) is None


def test_company_health_tool_text_and_bad_symbol(monkeypatch):
    """TC-AGR-03 · 6자리 코드면 재무 건전성 글(숫자 · 문장 · 출처 · 고지) · 코드가 아니면 되물으라는 한 줄 · 재무 없음은 글로."""
    fake = {"symbol": "005930", "source": "전자공시(DART)", "fs_note": None, "kind_note": "",
            "latest": {"report": "반기보고서", "period_end": "2026-06-30"},
            "metrics": [{"key": "current_ratio", "label": "유동비율", "value": 283.0, "sentence": "유동비율은 283% — …"},
                        {"key": "debt_ratio", "label": "부채비율", "value": 31.1, "sentence": "부채비율은 31% — …"}],
            "zscore": {"value": 7.97, "zone_label": "높은 구간(2.60 초과)"},
            "summary": {"total": 7, "pass": 5, "fail": 0, "unknown": 2}, "checks": [],
            "notice": "투자 권유가 아닙니다."}
    monkeypatch.setattr(R.company_health, "read_health", lambda sym: fake)
    out = asyncio.run(R.run(None, "company_health", {"symbol": "005930"}))
    for part in ("005930", "유동비율 283%", "부채비율 31%", "Altman Z'' 7.97", "점검 7개", "DART", "투자 권유가 아닙니다"):
        assert part in out
    assert "6자리 종목코드" in asyncio.run(R.run(None, "company_health", {"symbol": "삼성전자"}))

    def missing(sym):
        raise R.company_health.HealthError(404, "no_financials", "재무가 없습니다.")
    monkeypatch.setattr(R.company_health, "read_health", missing)
    assert "자료가 없습니다" in asyncio.run(R.run(None, "company_health", {"symbol": "999999"}))


def test_credit_spread_tool_text(monkeypatch):
    """TC-AGR-04 · 신용 스프레드 글(문장 · 출처) · 자료가 없으면 「자료가 없습니다」(되풀이 막기 표시)."""
    monkeypatch.setattr(R.macro_credit, "read_macro", lambda years, admin: {
        "available": True, "as_of": "2026-10-12", "source": "한국은행 경제통계시스템(ECOS)", "notice": "투자 권유가 아닙니다.",
        "spreads": [{"latest": {"bp": 68.1}, "sentence": "회사채 AA- − 국고채 3년 차이는 68bp …", "points": ["뜻", "재는 법"]}]})
    out = asyncio.run(R.run(None, "credit_spread", {}))
    assert "68bp" in out and "ECOS" in out
    monkeypatch.setattr(R.macro_credit, "read_macro", lambda years, admin: {"available": False, "reason": "아직 받지 못했습니다."})
    assert "자료가 없습니다" in asyncio.run(R.run(None, "credit_spread", {}))


def test_is_repeat_rules():
    """TC-AGR-05 · 같은 도구 · 같은 인자 → 되풀이 · 인자가 달라도 그 도구가 「자료 없음」 을 냈으면 되풀이 · 답 고르기는 아님."""
    steps = [{"action": "search_funds", "args": {"main_type": "국내주식"}}]
    assert R.is_repeat(steps, ["펀드 3건 …"], {"action": "search_funds", "args": {"main_type": "국내주식"}})
    assert not R.is_repeat(steps, ["펀드 3건 …"], {"action": "search_funds", "args": {"main_type": "해외주식"}})
    assert R.is_repeat(steps, ["조건에 맞는 펀드 상품이 없습니다."], {"action": "search_funds", "args": {"limit": 5}})
    assert not R.is_repeat(steps, ["조건에 맞는 펀드 상품이 없습니다."], {"action": "final_answer", "args": {}})


class _FakeOllama:
    """추론에는 늘 같은 옛 도구를 고르고(옛 꼴의 되풀이), 답 쪽에는 「답」."""

    def __init__(self, action="query_personal_cb", vary=False):
        self.reason_calls, self.answer_calls, self.action, self.vary = 0, 0, action, vary

    async def chat(self, model, messages, options=None):
        if messages and messages[0]["content"] == L.SYSTEM_PROMPT:
            self.reason_calls += 1
            args = {"period": f"20221{self.reason_calls}"} if self.vary else {"period": "202212"}
            return json.dumps({"thought": "CB 를 본다", "action": self.action, "args": args}, ensure_ascii=False)
        self.answer_calls += 1
        return "답"


@pytest.mark.parametrize("vary", [False, True])
def test_graph_stops_repeating_a_no_data_tool(monkeypatch, vary):
    """TC-AGR-06 · 모델이 옛 CB 도구만 계속 골라도 두 번째 추론에서 답으로 — 같은 인자든(되풀이) 다른 인자든(자료 없음).
    옛 코드는 MAX_STEPS(6) 까지 돌았다. CB 표를 읽는 강사님 함수는 한 번도 불리지 않는다."""
    async def boom(db, args):
        raise AssertionError("CB 표를 읽었다")
    monkeypatch.setattr(L, "query_personal_cb", boom)
    fake = _FakeOllama(vary=vary)
    out = asyncio.run(L.run_agent(None, fake, "m", "요즘 개인 신용 점수 평균이 어때?", []))
    assert out["answer"] == "답" and fake.answer_calls == 1
    assert fake.reason_calls == 2 and len(out["steps"]) == 1
