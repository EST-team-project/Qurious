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
    "   args: { \"name\": \"삼성전자\" }(질문에 나온 회사 이름 그대로 — 서버가 코드를 찾는다 · 코드를 짐작하지 않는다) "
    "또는 { \"symbol\": \"005930\" }(질문에 6자리 코드가 있을 때)\n"
    "2. credit_spread     - 시장 전체의 신용 스프레드(회사채 AA- · BBB- − 국고채 3년 · CP − CD) — 시장의 신용 위험을 물을 때\n"
    "   args: {}\n"
)


def swap_prompt(prompt: str) -> str:
    """강사님 시스템 프롬프트의 옛 CB 도구 두 줄을 새 도구 두 줄로 — 찾지 못하면 그대로 돌려준다(시험이 잡는다)."""
    return _OLD_PROMPT.sub(NEW_PROMPT_LINES, prompt, count=1)


#: 셀 수 없는 지표의 값 글 — 「—」 나 0 이 아니다(DF-124 — 모델이 「—」 를 빈 숫자로 읽고 채웠다).
CANNOT = "셀 수 없음"
HEALTH_HEAD = "[재무 건전성 — "
HEALTH_KEYS = ("current_ratio", "debt_ratio", "equity_ratio", "impairment")
#: 도구 글의 지표 줄 — `health_text` 가 쓰고 `server_values` 가 읽는다(같은 파일 · 꼴을 바꾸면 TC-AGR-07 이 알린다).
_METRIC_LINE = re.compile(r"^- (?P<label>[^:\n]{2,12}): (?P<value>셀 수 없음|-?[\d,]+(?:\.\d+)?%) — (?P<why>[^\n]*)$", re.M)
#: 값이 빈 괄호(「(비율: )」) — 첫 바퀴 점검(10-16)의 답에 남은 꼴. 값이 든 괄호는 건드리지 않는다.
_EMPTY_PAREN = re.compile(r"[ \t]*\([^()\n]{1,12}:\s*\)")
#: 답에서 지표 이름에 바로 붙은 숫자(「유동비율은 136%」 · 「부채비율: 0%」) — 이름 + 「은 · 는 · 이 · 가 · :」 + 숫자 %.
#: 기준 문장(「부채비율이 200% 이상이면」)은 그 회사 값을 말한 것이 아니라 건너뛴다(10-16 실측 답에 「100% 이상인 경우」 가 섞였다).
_NUM_AFTER = (r"\s*(?:은|는|이|가|:|：)\s*(?:약\s*)?(-?\d[\d,]*(?:\.\d+)?)\s*%"
              r"(?!\s*(?:이상|이하|미만|초과|넘|보다|을 넘|를 넘))")
#: 도구 글 머리의 회사 — 「신한지주(055550) · …」
_WHO = re.compile(r"^(?P<name>.*?)\((?P<code>\d{6})\)")


def _num(v: Optional[float], unit: str = "%") -> str:
    return CANNOT if v is None else f"{v:,.0f}{unit}"


def health_text(out: Dict) -> str:
    """재무 건전성 응답 → 모델이 읽을 짧은 글(숫자 · 서버가 지은 문장 · 출처).

    지표마다 「- 이름: 값 — 문장」 한 줄(DF-124 · 2026-10-16). 옛 꼴은 값 줄(「유동비율 — · 부채비율 — · …」)과 문장 줄이
    따로였고, 값이 없으면 「—」 만 있었다 — 10-16 실측에서 모델이 그 자리를 지어낸 숫자(136% · 130%) · 0% · 빈 칸
    「(비율: )」 으로 채웠다. 그래서 「셀 수 없음」 을 글로 쓰고, 이 목록에 없는 숫자를 만들지 말라는 줄을 둔다.
    모델이 그래도 지어낼 수 있어 답 끝에 서버 값을 붙이는 지킴(`guard_answer`)이 따로 있다.
    """
    lb = out.get("latest") or {}
    m = {x["key"]: x for x in out.get("metrics") or []}
    who = f"{out['name']}({out.get('symbol')})" if out.get("name") else f"{out.get('symbol')}"
    lines = [f"{HEALTH_HEAD}{who} · {lb.get('report')} {lb.get('period_end')} · 출처 {out.get('source')}]"]
    if out.get("fs_note"):
        lines.append(out["fs_note"])
    if out.get("kind_note"):
        lines.append(out["kind_note"])
    lines.append(f"지표 — 서버가 계산한 값이다. 「{CANNOT}」 은 0 이 아니라 이 회사에 맞지 않거나 자료가 없는 지표라는 뜻이다."
                 " 이 목록에 없는 숫자를 만들어 쓰지 않는다.")
    for k in HEALTH_KEYS:
        if k in m:
            x = m[k]
            lines.append(f"- {x['label']}: {_num(x['value'])} — {x.get('sentence') or x.get('reason') or '설명 없음'}")
    z = out.get("zscore") or {}
    lines.append(f"Altman Z'' {z['value']:.2f} — {z.get('zone_label')}" if z.get("value") is not None
                 else f"Altman Z'': {CANNOT} — {z.get('reason') or '자료가 모자랍니다'}")
    s = out.get("summary") or {}
    lines.append(f"점검 {s.get('total', 0)}개: 통과 {s.get('pass', 0)} · 실패 {s.get('fail', 0)} · 자료 없음 {s.get('unknown', 0)}")
    for c in out.get("checks") or []:
        if c["status"] == "fail":
            lines.append(f"- 실패: {c['label']} ({c['reason']})")
    lines.append(out.get("notice") or "")
    return "\n".join(ln for ln in lines if ln)


def server_values(obs: str) -> Dict[str, str]:
    """`health_text` 글 → {지표 이름: 값 글}(「7%」 · 「셀 수 없음」). 그 꼴이 아니면 빈 dict."""
    return {mm.group("label"): mm.group("value") for mm in _METRIC_LINE.finditer(obs or "")}


def _differs(answer: str, label: str, value: str) -> bool:
    """답이 그 지표에 서버와 다른 숫자를 붙였나 — 서버가 「셀 수 없음」 이면 숫자가 붙기만 해도 다르다 · 값이면 0.5 넘게 다를 때."""
    for mm in re.finditer(re.escape(label) + _NUM_AFTER, answer):
        said = float(mm.group(1).replace(",", ""))
        if value == CANNOT or abs(said - float(value.rstrip("%").replace(",", ""))) > 0.5:
            return True
    return False


def guard_answer(answer: Any, observations: List[str], question: str = "") -> Any:
    """재무 건전성 도구를 쓴 답의 끝에 서버가 계산한 값을 붙이고, 답의 숫자가 그와 다르면 경고 한 줄(DF-124 · 2026-10-16).

    - 모델 글은 지우거나 고치지 않는다 — 다만 값이 빈 괄호(「(비율: )」)만 지운다(아무 정보가 없는 찌꺼기).
    - 그 도구를 쓰지 않은 답은 한 글자도 바꾸지 않는다(다른 도구 답의 괄호 뜻은 모른다).
    - 숫자는 서버 한 곳(`company_health`)에서 — 모델이 옮겨 쓴 숫자를 믿지 않고 원래 값을 함께 보인다(S118 「숫자의 출처」).
    - 서버가 본 회사의 이름 · 코드가 질문에 없으면 그것도 알린다 — 모델이 코드를 짐작해 다른 회사를 본 적이 있다
      (10-16 실측 6회 중 2회 · 「신한지주」 → 051910 LG화학 · 그 값을 「신한지주의 유동비율은 136%」 로 씀).
    """
    if not isinstance(answer, str):
        return answer
    obs = next((o for o in reversed(observations or []) if isinstance(o, str) and o.startswith(HEALTH_HEAD)), None)
    vals = server_values(obs) if obs else {}
    if not vals:
        return answer
    head = obs.splitlines()[0][len(HEALTH_HEAD):].rstrip("]")
    text = _EMPTY_PAREN.sub("", answer).rstrip()
    wrong = [label for label, value in vals.items() if _differs(text, label, value)]
    lines = [text, ""]
    who = _WHO.match(head)
    if who and question and who.group("code") not in question and (not who.group("name") or who.group("name") not in question):
        lines.append(f"⚠️ 서버가 본 회사는 {who.group('name')}({who.group('code')})입니다 — 질문에 이 회사 이름 · 코드가 없습니다. "
                     "다른 회사를 물으셨다면 회사 이름을 넣어 다시 물어 주세요.")
    if wrong:
        lines.append(f"⚠️ 위 답의 {' · '.join(wrong)} 숫자는 서버가 계산한 값과 다릅니다 — 아래 값이 맞습니다.")
    lines.append(f"서버가 계산한 값 — {head}")
    lines.append(" · ".join(f"{label} {value}" for label, value in vals.items()))
    why = next((mm.group("why") for mm in _METRIC_LINE.finditer(obs) if mm.group("value") == CANNOT), "")
    if why:
        lines.append(f"「{CANNOT}」 은 0 이 아닙니다 — {why.rstrip('.')}.")
    return "\n".join(lines)


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
        name = str((args or {}).get("name") or "").strip()
        if sym and not re.fullmatch(r"\d{6}", sym) and not name:
            name, sym = sym, ""            # 코드 칸에 이름을 넣은 경우(「삼성전자」)
        if name:
            # 이름이 있으면 이름이 이긴다 — 모델이 짐작한 코드는 쓰지 않는다(DF-124 · 10-16 실측: 「신한지주」 를 051910(LG화학)으로)
            code = await asyncio.to_thread(company_health.code_of, name)
            if not code:
                return (f"「{name}」 을 상장사 이름에서 찾지 못했습니다 — 정확한 회사 이름이나 6자리 종목코드를 "
                        "final_answer 로 되물어라.")
            sym = code
        if not re.fullmatch(r"\d{6}", sym):
            return "회사 이름이나 6자리 종목코드가 필요합니다(예: 삼성전자 · 005930) — 모르면 final_answer 로 회사 이름을 되물어라."
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
