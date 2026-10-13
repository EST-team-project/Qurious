"""대화 에이전트의 재무 · 신용 위험 도구 (④-2 · 2026-10-13) — `app/services/langgraph_agent.py`(강사님 파일)가 부른다.

왜 따로 두나 — 강사님 파일에는 갈림 몇 줄만 두고 새 기능은 새 파일에(S86 규칙 · 다음 3-way 반영 충돌을 줄인다).

무엇이 바뀌나
  옛 도구 둘(query_personal_cb · query_corporate_cb)은 개인 · 기업 CB 집계 표를 읽었는데, 그 표를 채우던 신용평가 CSV 적재는
  결정 ② A(2026-10-07)로 뺐다 — 표가 비어 에이전트가 같은 도구를 되풀이 불러 답이 약 2분 걸렸다(기능 완성도 점검표
  `agent-cb` −2). 새 도구 둘로 바꾼다:
    company_health  상장사 한 곳의 재무 건전성(우리 DART 주요계정 · `company_health.read_health`)
    credit_spread   시장 전체의 신용 스프레드(ECOS 시장금리 · `macro_credit.read_macro`)
  옛 이름으로 불러도 표를 읽지 않고 「자료 없음 — 새 도구를 쓰라」 한 줄로 끝낸다(모델이 옛 이름을 기억해도 되풀이하지 않게).

되풀이 막기(`is_repeat`) — 같은 도구 · 같은 인자를 다시 고르거나, 「자료 없음」 이 나온 도구를 또 고르면 바로 답으로 넘긴다.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

from app.services import company_health, macro_credit

OLD_TOOLS = ("query_personal_cb", "query_corporate_cb")
NEW_TOOLS = ("company_health", "credit_spread")
#: 도구 결과가 이 글을 담으면 「자료 없음」 — 같은 도구를 다시 부르지 않는다(강사님 도구의 빈 결과 글 · 우리 도구의 글).
NO_DATA_MARKERS = ("데이터가 없습니다", "상품이 없습니다", "자료가 없습니다")

#: 강사님 프롬프트의 옛 도구 두 줄(설명 + args) — 이 글을 찾아 바꾼다. 강사님이 글을 고치면 시험(TC-AGR-01)이 알린다.
_OLD_PROMPT = re.compile(
    r"1\. query_personal_cb .*?\n.*?\n2\. query_corporate_cb .*?\n.*?\n", re.S)
NEW_PROMPT_LINES = (
    "1. company_health    - 상장사 한 곳의 재무 건전성(유동비율 · 부채비율 · 자본잠식 · Altman Z'' · 점검) — 회사의 재무 위험을 물을 때\n"
    "   args: { \"symbol\": \"005930\"(6자리 종목코드 — 삼성전자 005930 · 카카오 035720) }\n"
    "2. credit_spread     - 시장 전체의 신용 스프레드(회사채 AA- · BBB- − 국고채 3년 · CP − CD) — 시장의 신용 위험을 물을 때\n"
    "   args: {}\n"
)


def swap_prompt(prompt: str) -> str:
    """강사님 시스템 프롬프트의 옛 CB 도구 두 줄을 새 도구 두 줄로 — 찾지 못하면 그대로 돌려준다(시험이 잡는다)."""
    return _OLD_PROMPT.sub(NEW_PROMPT_LINES, prompt, count=1)


def _num(v: Optional[float], unit: str = "%") -> str:
    return "—" if v is None else f"{v:,.0f}{unit}"


def health_text(out: Dict) -> str:
    """재무 건전성 응답 → 모델이 읽을 짧은 글(숫자 · 서버가 지은 문장 · 출처)."""
    lb = out.get("latest") or {}
    m = {x["key"]: x for x in out.get("metrics") or []}
    lines = [f"[재무 건전성 — {out.get('symbol')} · {lb.get('report')} {lb.get('period_end')} · 출처 {out.get('source')}]"]
    if out.get("fs_note"):
        lines.append(out["fs_note"])
    if out.get("kind_note"):
        lines.append(out["kind_note"])
    lines.append(" · ".join(f"{m[k]['label']} {_num(m[k]['value'])}" for k in
                            ("current_ratio", "debt_ratio", "equity_ratio", "impairment") if k in m))
    z = out.get("zscore") or {}
    lines.append(f"Altman Z'' {z['value']:.2f} — {z.get('zone_label')}" if z.get("value") is not None
                 else f"Altman Z'' — {z.get('reason') or '셀 수 없음'}")
    s = out.get("summary") or {}
    lines.append(f"점검 {s.get('total', 0)}개: 통과 {s.get('pass', 0)} · 실패 {s.get('fail', 0)} · 자료 없음 {s.get('unknown', 0)}")
    for c in out.get("checks") or []:
        if c["status"] == "fail":
            lines.append(f"- 실패: {c['label']} ({c['reason']})")
    for x in m.values():
        if x.get("sentence"):
            lines.append(f"- {x['sentence']}")
    lines.append(out.get("notice") or "")
    return "\n".join(ln for ln in lines if ln)


def spread_text(out: Dict) -> str:
    """신용 스프레드 응답 → 모델이 읽을 짧은 글."""
    if not out.get("available"):
        return f"신용 스프레드 자료가 없습니다 — {out.get('reason')}"
    lines = [f"[신용 스프레드 — 마지막 날 {out.get('as_of')} · 출처 {out.get('source')}]"]
    for s in out.get("spreads") or []:
        if s.get("latest"):
            lines.append(f"- {s['sentence']}")
            lines.extend(f"  · {p}" for p in s.get("points", [])[:2])
    lines.append(out.get("notice") or "")
    return "\n".join(ln for ln in lines if ln)


async def run(db: Any, act: str, args: Dict[str, Any]) -> Optional[str]:
    """이 파일이 맡는 도구면 결과 글, 아니면 None(강사님 도구로 넘긴다). 예외는 글로 바꿔 대화가 멈추지 않게 한다."""
    if act in OLD_TOOLS:
        return ("개인 · 기업 CB 통계 자료가 없습니다(이 서비스는 그 표를 쓰지 않습니다) — 회사의 재무 위험은 company_health, "
                "시장의 신용 위험은 credit_spread 를 쓰고, 그 밖의 질문은 final_answer 를 호출하라.")
    if act == "company_health":
        sym = str((args or {}).get("symbol") or "").strip()
        if not re.fullmatch(r"\d{6}", sym):
            return "6자리 종목코드가 필요합니다(예: 삼성전자 005930) — 코드를 모르면 final_answer 로 회사 이름을 되물어라."
        try:
            out = await asyncio.to_thread(company_health.read_health, sym)
        except company_health.HealthError as e:
            return f"{sym} 의 재무 자료가 없습니다 — {e.message}"
        return health_text(out)
    if act == "credit_spread":
        out = await asyncio.to_thread(macro_credit.read_macro, macro_credit.DEFAULT_YEARS, False)
        return spread_text(out)
    return None


def _same(a: Dict, b: Dict) -> bool:
    return a.get("action") == b.get("action") and \
        json.dumps(a.get("args") or {}, sort_keys=True, ensure_ascii=False) == \
        json.dumps(b.get("args") or {}, sort_keys=True, ensure_ascii=False)


def is_repeat(steps: List[Dict], observations: List[str], action: Dict) -> bool:
    """이번에 고른 행동이 되풀이인가 — 같은 도구 · 같은 인자를 이미 돌렸거나, 같은 도구가 이미 「자료 없음」 을 냈다.

    `steps[i]` 의 결과가 `observations[i]` 다(도구를 돈 걸음마다 하나씩 쌓인다 — final_answer · clarify 걸음은 결과가 없다).
    """
    if action.get("action") in ("final_answer", "clarify"):
        return False
    tool_steps = [s for s in steps if s.get("action") not in ("final_answer", "clarify")]
    for i, s in enumerate(tool_steps):
        if _same(s, action):
            return True
        obs = observations[i] if i < len(observations) else ""
        if s.get("action") == action.get("action") and any(m in obs for m in NO_DATA_MARKERS):
            return True
    return False
