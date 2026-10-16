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


@pytest.fixture(autouse=True)
def _no_real_collector_db(monkeypatch, tmp_path):
    """이 PC 의 실제 수집 DB 를 열지 않는다(S110 규칙) — 회사 이름 찾기(`company_health.code_of`)가 수집 DB 를 읽는다.
    2026-10-16 이 장치가 없을 때 TC-AGR-03 이 실제 DB 를 한 번 열었다(뒤에 데이터 점검 16/16 정상 확인)."""
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없는-수집DB.sqlite3"))


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
    for part in ("005930", "- 유동비율: 283% — ", "- 부채비율: 31% — ", "Altman Z'' 7.97", "점검 7개", "DART", "투자 권유가 아닙니다"):
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


# ── DF-124 · 재무 숫자 지킴(2026-10-16) ─────────────────────────────────────────────
# 10-16 20:3x 실측(앱 컨테이너 · Local Ollama 길 · 「신한지주 지금 사도 될까요? 우리 앱의 신호와 근거를 같이」 세 번):
# 서버는 금융회사라 유동비율 · 부채비율을 「—」(셀 수 없음)로 줬는데 모델이 136% · 130% · 44% 를 지어내거나(1회),
# 「부채비율 73.6%」(2회) · 「유동비율: 0%」 · 「부채비율: 0%」(3회)로 적었다. 첫 바퀴 점검(10-16 낮)은 「(비율: )」 빈 칸이었다.
# 답 지침(강사님 ANSWER_PROMPT)의 「DB 데이터가 … 없으면 전문 지식으로 답변한다」 가 빈 숫자를 채우게 한다.

_FIN = {"symbol": "055550", "name": "신한지주", "source": "전자공시(DART)", "fs_note": None,
        "kind_note": "금융회사는 예금 · 보험 같은 부채가 장사 밑천이고 유동 · 비유동 구분이 없어 이 비율로 견줄 수 없습니다",
        "latest": {"report": "사업보고서", "period_end": "2025-12-31"},
        "metrics": [
            {"key": "current_ratio", "label": "유동비율", "value": None,
             "sentence": "금융회사는 예금 · 보험 같은 부채가 장사 밑천이고 유동 · 비유동 구분이 없어 이 비율로 견줄 수 없습니다"},
            {"key": "debt_ratio", "label": "부채비율", "value": None,
             "sentence": "금융회사는 예금 · 보험 같은 부채가 장사 밑천이고 유동 · 비유동 구분이 없어 이 비율로 견줄 수 없습니다"},
            {"key": "equity_ratio", "label": "자기자본비율", "value": 7.3,
             "sentence": "자산 100원 가운데 7원이 빚이 아닌 몫입니다."},
            {"key": "impairment", "label": "자본잠식률", "value": 0.0,
             "sentence": "자본잠식이 없습니다 — 자본총계가 자본금보다 큽니다."}],
        "zscore": {"value": None, "reason": "금융회사는 … 견줄 수 없습니다"},
        "summary": {"total": 7, "pass": 2, "fail": 0, "unknown": 5}, "checks": [], "notice": "투자 권유가 아닙니다."}

# 실측 답에서 옮긴 줄(앞뒤 생략) — 1회 · 2회 · 3회 · 첫 바퀴
_ANS_INVENTED = "신한지주의 재무 건전성은 여러 지표를 통해 평가할 수 있습니다. 유동비율은 136%, 부채비율은 130%, 자기자본비율은 44%로 나타납니다."
_ANS_ZERO = ("*   유동비율: 0% (금융회사의 … 견줄 수 없습니다)\n"
             "*   부채비율: 0%\n"
             "*   자기자본비율: 7% (자산 100원 가운데 7원이 빚이 아닌 몫입니다)\n"
             "*   자본잠식률: 0% (자본총계가 자본금보다 큽니다)")
_ANS_BLANK = ("*   유동비율: 금융회사의 … 견줄 수 없습니다. (비율: )\n"
              "*   자기자본비율: 자산 100원 가운데 7원이 빚이 아닌 몫입니다. (비율: 7%)\n"
              "*   자본잠식률: 자본총계가 자본금보다 큽니다. (비율: )")
_ANS_RIGHT = "신한지주는 금융회사라 유동비율 · 부채비율로 견줄 수 없습니다. 자기자본비율은 7%이고 자본잠식은 없습니다(0%)."


def _health_obs(monkeypatch):
    monkeypatch.setattr(R.company_health, "read_health", lambda sym: _FIN)
    return asyncio.run(R.run(None, "company_health", {"symbol": "055550"}))


def test_health_text_says_cannot_compute_instead_of_dash(monkeypatch):
    """TC-AGR-07 · 지표 넷을 「- 이름: 값 — 문장」 한 줄씩 · 값이 없으면 「셀 수 없음」(「—」 · 0 이 아니다) · 지어내지 말라는 줄 · 회사 이름."""
    out = _health_obs(monkeypatch)
    for line in ("- 유동비율: 셀 수 없음 — 금융회사는", "- 부채비율: 셀 수 없음 — 금융회사는",
                 "- 자기자본비율: 7% — 자산 100원", "- 자본잠식률: 0% — 자본잠식이 없습니다"):
        assert line in out, line
    assert "유동비율 —" not in out and "부채비율 —" not in out
    assert "셀 수 없음」 은 0 이 아니" in out and "만들어 쓰지 않는다" in out
    assert "신한지주(055550)" in out
    assert R.server_values(out) == {"유동비율": "셀 수 없음", "부채비율": "셀 수 없음", "자기자본비율": "7%", "자본잠식률": "0%"}


@pytest.mark.parametrize("answer,wrong", [
    (_ANS_INVENTED, ["유동비율", "부채비율", "자기자본비율"]),
    (_ANS_ZERO, ["유동비율", "부채비율"]),
    (_ANS_BLANK, []),
    (_ANS_RIGHT, []),
])
def test_guard_answer_flags_numbers_that_differ_from_server(monkeypatch, answer, wrong):
    """TC-AGR-08 · 답에 서버 값과 다른 비율이 있으면 그 이름을 짚는 경고 한 줄 · 서버가 계산한 값 블록은 늘 덧붙임 ·
    빈 괄호 「(비율: )」 만 지운다(값이 든 괄호 · 나머지 글은 그대로)."""
    obs = _health_obs(monkeypatch)
    out = R.guard_answer(answer, ["다른 도구 글", obs])
    assert "서버가 계산한 값 — 신한지주(055550) · 사업보고서 2025-12-31 · 출처 전자공시(DART)" in out
    assert "유동비율 셀 수 없음 · 부채비율 셀 수 없음 · 자기자본비율 7% · 자본잠식률 0%" in out
    warn = [ln for ln in out.splitlines() if ln.startswith("⚠️ 위 답의")]
    if wrong:
        assert len(warn) == 1 and all(w in warn[0] for w in wrong), warn
        assert not [w for w in ("유동비율", "부채비율", "자기자본비율", "자본잠식률") if w not in wrong and w in warn[0]]
    else:
        assert warn == []
    assert "(비율: )" not in out and ("(비율: 7%)" in out) == ("(비율: 7%)" in answer)
    assert out.startswith(answer.replace(" (비율: )", "").replace("(비율: )", "").rstrip()[:30])


def test_guard_answer_leaves_other_answers_alone():
    """TC-AGR-09 · 재무 건전성 도구를 쓰지 않은 답은 한 글자도 바꾸지 않는다(빈 괄호도 그대로 — 다른 도구 답의 뜻을 모른다)."""
    for ans in ("답", "금리는 (기준: ) 입니다", ""):
        assert R.guard_answer(ans, ["펀드 3건 …"]) == ans
        assert R.guard_answer(ans, []) == ans
    assert R.guard_answer(None, []) is None


class _FakeHealthOllama:
    """추론 1번째는 company_health · 2번째는 final_answer · 답은 숫자를 지어낸 실측 답."""

    def __init__(self):
        self.reason_calls = 0

    async def chat(self, model, messages, options=None):
        if messages and messages[0]["content"] == L.SYSTEM_PROMPT:
            self.reason_calls += 1
            act = "company_health" if self.reason_calls == 1 else "final_answer"
            args = {"symbol": "055550"} if act == "company_health" else {}
            return json.dumps({"thought": "재무를 본다", "action": act, "args": args}, ensure_ascii=False)
        return _ANS_INVENTED


def test_graph_answer_carries_server_values(monkeypatch):
    """TC-AGR-10 · 그래프 답 노드가 지킴을 거친다 — 지어낸 답이 나가도 경고 + 서버가 계산한 값이 붙는다(강사님 파일 갈림 한 줄)."""
    monkeypatch.setattr(R.company_health, "read_health", lambda sym: _FIN)
    out = asyncio.run(L.run_agent(None, _FakeHealthOllama(), "m", "신한지주 지금 사도 될까요?", []))
    assert out["answer"].startswith(_ANS_INVENTED)
    assert "⚠️ 위 답의 유동비율 · 부채비율 · 자기자본비율" in out["answer"]
    assert "자기자본비율 7%" in out["answer"].split("서버가 계산한 값 — ")[1]
    assert "⚠️ 서버가 본 회사는" not in out["answer"]   # 질문에 「신한지주」 가 있다


def test_company_health_takes_name_and_name_wins(monkeypatch):
    """TC-AGR-11 · 회사 이름을 받으면 서버가 코드를 찾는다(`company_health.code_of`) · 이름과 코드가 함께 오면 이름이 이긴다 ·
    코드 칸에 이름이 와도 이름으로 · 못 찾으면 되물으라는 한 줄(지어낸 코드로 다른 회사를 보지 않게)."""
    seen = []
    monkeypatch.setattr(R.company_health, "code_of", lambda name: {"신한지주": "055550"}.get(name, ""))
    monkeypatch.setattr(R.company_health, "read_health", lambda sym: seen.append(sym) or dict(_FIN, symbol=sym))
    asyncio.run(R.run(None, "company_health", {"name": "신한지주"}))
    asyncio.run(R.run(None, "company_health", {"name": "신한지주", "symbol": "051910"}))
    asyncio.run(R.run(None, "company_health", {"symbol": "신한지주"}))
    asyncio.run(R.run(None, "company_health", {"symbol": "005930"}))
    assert seen == ["055550", "055550", "055550", "005930"]
    out = asyncio.run(R.run(None, "company_health", {"name": "없는회사"}))
    assert "찾지 못했습니다" in out and "6자리 종목코드" in out and len(seen) == 4
    assert "회사 이름이나 6자리 종목코드" in asyncio.run(R.run(None, "company_health", {}))
    assert '"name": "삼성전자"' in L.SYSTEM_PROMPT and "코드를 짐작하지 않는다" in L.SYSTEM_PROMPT


def test_guard_answer_flags_other_company_and_skips_thresholds(monkeypatch):
    """TC-AGR-12 · 서버가 본 회사가 질문에 없으면(이름 · 코드 모두) 그 회사를 짚는 경고 · 질문에 이름이나 코드가 있으면 없음 ·
    「부채비율이 200% 이상이면」 같은 기준 문장은 그 회사 값이 아니라 숫자 경고를 내지 않는다(10-16 실측 답의 꼴)."""
    lg = dict(_FIN, symbol="051910", name="LG화학",
              metrics=[dict(m, value=v, sentence=f"{m['label']} {v}%") for m, v in zip(_FIN["metrics"], (136.0, 130.0, 44.0, 0.0))])
    monkeypatch.setattr(R.company_health, "read_health", lambda sym: lg)
    obs = asyncio.run(R.run(None, "company_health", {"symbol": "051910"}))
    ans = "신한지주의 유동비율은 136%, 부채비율은 130% 입니다. 일반적으로 부채비율이 200% 이상이면 위험하다고 봅니다."
    out = R.guard_answer(ans, [obs], "신한지주 지금 사도 될까요?")
    assert "⚠️ 서버가 본 회사는 LG화학(051910)입니다" in out
    assert "⚠️ 위 답의" not in out                       # 숫자는 서버 값과 같고 200% 는 기준 문장
    for q in ("LG화학 재무는?", "051910 은 어때?", ""):
        assert "⚠️ 서버가 본 회사는" not in R.guard_answer(ans, [obs], q)
