"""근거 답 만들기 — 찾은 근거만 써서 답하고 문장마다 출처 번호를 단다 (목표 기능 ① W6 · 설계서 5.3.4).

- ``ask(q, …)`` : API-KB-03 ``POST /api/kb/ask``

흐름
----
1. **답하지 않는 질문** — 종목 매수 · 매도 권유나 가격 · 수익률 예측을 묻는 질문은 찾기 · 생성 없이 돌려보낸다
   (답변 정책 ④ · 조사서 「로컬 · 무료 LLM 과 AWS 를 퀀트에서 쓰는 법」 2절 — LLM 은 학습 때 읽은 결과를 기억해
   예측 성과를 부풀린다).
2. **찾기** — ``kb_search.search`` 로 기준일에 시행 중인 판만, 낱말 + 벡터 → RRF 상위 k. 판 고르기가 곧 시점 고정
   검색이다(기준일 뒤의 판은 근거에 들어오지 않는다).
3. **근거 없음** — 찾은 근거가 0 이면 LLM 을 부르지 않는다.
4. **프롬프트** — 근거마다 ``[출처 n]`` 머리(문서 · 조 · 판 · 시행일)와 본문(길이 상한)을 넣고 규칙(근거 밖 사실 금지 ·
   문장마다 출처 · 답할 수 없으면 정해진 한 문장 · 투자 권유 금지)을 준다.
5. **생성** — Ollama ``/api/chat`` · 온도 0 · 씨앗 고정 · 답 길이 · 시간 상한. 생각하는 모델(qwen3 등)은 생각을 끈다.
6. **검사** — 서버가 답의 출처 번호를 다시 본다. 근거 목록 밖의 번호는 지우고 ``check.invalid`` 에 싣는다.
   남은 출처가 하나도 없으면 LLM 글을 버리고 근거 발췌로 답한다(답변 정책 ① ② — 근거 없는 글을 보이지 않는다).
   모델이 정해진 「근거를 찾지 못했습니다.」 를 쓰면 ``no_evidence``.

LLM 에 닿지 못하면 근거 발췌로 답하고 ``llm.error`` 에 까닭을 싣는다 — 찾기의 「벡터가 꺼지면 낱말로」 와 같은 원칙이다.
같은 질문 · 같은 모델 · 온도 0 이어도 GPU 경로에서는 답이 달라질 수 있어(조사서 4.4절 실측) 모델 이름 · 넣은 근거의
청크 ID 를 응답에 남긴다.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from app.services import kb_search

#: 한 번에 넣을 근거 수 · 기본값 — 이 PC 의 CPU 로 질문 읽기가 초당 약 30토큰이라(조사서 4.4절) 넉넉히 넣지 않는다
MAX_ASK_K = 8
DEFAULT_ASK_K = 5
#: 근거 한 개 · 전체 글자 상한 — 조문이 길면 앞부분만(머리 + 본문 앞)
CHUNK_CHARS = 900
CONTEXT_CHARS = 4500
#: 답 길이(토큰) · 문맥 창 · 시간 상한
NUM_PREDICT = 400
NUM_CTX = 8192
SEED = 42
ENV_MODEL = "KB_ANSWER_MODEL"
#: 기본 답 모델 — 2026-10-03 근거답 평가셋 v0 으로 다섯을 견준 뒤 팀장 결정(정답 7 · 근거 밖 질문에 지어낸 답 0 ·
#: 문장마다 출처 94% · 내장 GPU 로 22초 · Apache 2.0). 채팅용 LLM_MODEL 과 따로 둔다 — 채팅은 다른 모델일 수 있다.
DEFAULT_ANSWER_MODEL = "qwen3:4b-instruct"
ENV_TIMEOUT = "KB_ANSWER_TIMEOUT"
DEFAULT_TIMEOUT = 240.0
#: 생각(추론 글)을 먼저 쓰는 모델 이름 머리 — Ollama 에 think=false 를 보낸다
THINKING_PREFIXES = ("qwen3", "deepseek-r1", "exaone-deep", "gpt-oss", "magistral")
ANSWER_MODES = ("llm", "extract")
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]{0,119}$")

NO_ANSWER = "근거를 찾지 못했습니다."
NOTICE = "법령 · 감독규정 원문을 근거로 한 정보 제공입니다. 투자 권유가 아니며 법률 자문을 대신하지 않습니다."

#: 답하지 않는 질문 — 가격 · 수익률 예측과 종목 매수 · 매도 권유. 넓게 잡지 않는다(「공매도」 같은 규정 질문은 지나가게).
_DECLINE = re.compile(
    r"(오를까|오를지|내릴까|내릴지|떨어질까|떨어질지|오르나요|내리나요|사야\s*(할까|하나|돼|되나)|팔아야\s*(할까|하나|돼|되나)"
    r"|매수할까|매도할까|살까요|팔까요|목표\s*주가|추천\s*종목|종목\s*추천|주가\s*예측|수익률\s*예측|얼마까지\s*오)"
)

SYSTEM_PROMPT = (
    "너는 한국 법령과 금융 감독규정의 원문만 근거로 질문에 답하는 도우미다. 다음 규칙을 반드시 지킨다.\n"
    "1. [근거]에 적힌 내용만 쓴다. 근거에 없는 사실 · 숫자 · 조문 번호를 지어내지 않는다.\n"
    "2. 모든 문장 끝에 그 문장의 근거 번호를 [출처 n] 꼴로 단다. 근거가 둘이면 [출처 1][출처 2] 처럼 붙인다.\n"
    f"3. 근거로 답할 수 없으면 다른 말 없이 \"{NO_ANSWER}\" 한 문장만 쓴다.\n"
    "4. 특정 종목의 매수 · 매도를 권하거나 가격 · 수익률을 예측하지 않는다.\n"
    "5. 한국어 세 문장 이내로, 법 이름과 조 번호를 밝혀 쉬운 말로 쓴다."
)


# ==================================================
# 1. 생성 길 — 시험에서는 가짜로 바꿔 끼운다
# ==================================================
def _http_json(method: str, url: str, body: Optional[dict], timeout: float) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


@dataclass
class LlmBackend:
    """Ollama ``/api/chat`` — 스트리밍 없이 한 번에 받는다."""

    ollama_url: str
    timeout: float = DEFAULT_TIMEOUT
    http: Callable[[str, str, Optional[dict], float], dict] = _http_json

    @classmethod
    def from_settings(cls) -> "LlmBackend":
        from app.config import settings  # 시험이 가짜 백엔드만 쓸 때 설정을 읽지 않게 늦게 가져온다

        timeout = float(os.environ.get(ENV_TIMEOUT) or DEFAULT_TIMEOUT)
        return cls(ollama_url=settings.OLLAMA_BASE_URL.rstrip("/"), timeout=timeout)

    def chat(self, model: str, messages: List[dict], options: dict) -> dict:
        body: dict = {"model": model, "messages": messages, "stream": False, "options": options}
        if model.lower().startswith(THINKING_PREFIXES):
            body["think"] = False
        return self.http("POST", f"{self.ollama_url}/api/chat", body, self.timeout)


def default_model() -> str:
    """환경 변수 KB_ANSWER_MODEL 이 있으면 그것, 없으면 DEFAULT_ANSWER_MODEL."""
    return os.environ.get(ENV_MODEL) or DEFAULT_ANSWER_MODEL


def _llm_error(e: Exception, model: str) -> str:
    """생성 실패를 한 줄로 — 주소를 싣지 않는다."""
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 404:
            return f"답 모델 {model} 이 이 PC 의 Ollama 에 없다 — ollama pull {model}"
        return f"답 모델 HTTP {e.code} — Ollama 로그를 본다"
    if isinstance(e, (TimeoutError,)) or "timed out" in str(e).lower():
        return f"답 모델이 시간 안에 끝내지 못했다({type(e).__name__}) — 근거 수(k)를 줄이거나 작은 모델로"
    if isinstance(e, (urllib.error.URLError, OSError)):
        return f"답 모델 서버에 닿지 못했다({type(e).__name__}) — Ollama 가 켜져 있는지"
    return f"답 만들기 실패 — {e}"


# ==================================================
# 2. 프롬프트
# ==================================================
def _trim(text: str, limit: int) -> str:
    text = re.sub(r"[ \t]+", " ", (text or "").strip())
    return text if len(text) <= limit else text[:limit].rstrip() + " …(뒤 생략)"


def citation_excerpt(text: str, limit: int = CHUNK_CHARS) -> str:
    """출처 카드에 보일 조문 글 — 답 모델이 받은 것과 같은 길이(`CHUNK_CHARS`)로 자르되 첫 줄의 제목 사슬은 뺀다.

    왜: 화면이 답 아래에서 근거 조문을 그 자리에서 보여야 사람이 「답이 조문과 맞나」 를 확인한다(화면 설계
    2026-10-04 · 안 A). 제목 · 조 번호는 카드 머리에 따로 나오므로 본문에서 되풀이하지 않는다.
    """
    body = (text or "").strip()
    first, sep, rest = body.partition("\n")
    if sep and " > " in first:          # 「증권거래세법 > 제8조(세율)」 꼴의 머리 줄
        body = rest
    return _trim(body, limit)


def source_label(h: dict) -> str:
    """「자본시장과 금융투자업에 관한 법률 시행령 제2조(정의) · 대통령령 제36729호 · 2026-10-01 시행」 — 판 이름
    (`kb_text.Version.label`)에 시행일이 이미 들어 있어 따로 붙이지 않는다."""
    art = h["article"] + (f"({h['article_title']})" if h.get("article_title") else "")
    label = h["version_label"]
    if h.get("effective_at") and h["effective_at"] not in label:
        label += f" · {h['effective_at']} 시행"
    return f"{h['title']} {art} · {label}"


def build_messages(q: str, as_of: str, hits: Sequence[dict], *, chunk_chars: int = CHUNK_CHARS,
                   context_chars: int = CONTEXT_CHARS) -> Tuple[List[dict], int]:
    """(메시지, 넣은 근거 수). 전체 글자 상한을 넘으면 뒤의 근거를 뺀다(순위가 낮은 것부터)."""
    blocks: List[str] = []
    used = 0
    for i, h in enumerate(hits, start=1):
        block = f"[출처 {i}] {source_label(h)}\n{_trim(h['text'], chunk_chars)}"
        if blocks and used + len(block) > context_chars:
            break
        blocks.append(block)
        used += len(block)
    user = (f"기준일: {as_of} (이날 시행 중인 판의 조문만 근거로 넣었다)\n\n[근거]\n" + "\n\n".join(blocks)
            + f"\n\n[질문]\n{q}")
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}], len(blocks)


# ==================================================
# 3. 출처 번호 검사
# ==================================================
_THINK = re.compile(r"<think>.*?</think>", re.S)
#: 생각 전용 판(예: Ollama 의 qwen3:4b = Qwen3-4B-Thinking-2507)은 think=false 를 받아도 생각을 쓰고, 여는 태그는
#: 템플릿이 넣어 답에는 닫는 태그만 남는다 — 그 앞을 모두 버린다(2026-10-03 근거답 평가에서 확인).
_THINK_TAIL = re.compile(r"^.*?</think>", re.S)


#: 끝 표시 토큰이 글자로 새는 모델(커뮤니티 GGUF 의 대화 틀이 멈춤 신호를 빠뜨린 경우 — 2026-10-03 Kanana 변환본)
_END_TOKEN = re.compile(r"<\|(?:eot_id|end_of_text|endoftext|im_end|end)\|>")
_SPECIAL_TOKEN = re.compile(r"<\|[A-Za-z_]{2,30}\|>")


def strip_thinking(text: str) -> str:
    """생각 글 · 끝 표시 토큰 뒤를 버린다 — 끝 토큰 뒤에 이어 쓴 글은 다음 차례를 지어낸 것이라 답이 아니다."""
    text = _THINK.sub("", text or "")
    text = _THINK_TAIL.sub("", text)
    m = _END_TOKEN.search(text)
    if m:
        text = text[:m.start()]
    return _SPECIAL_TOKEN.sub("", text).strip()
_CITE_GROUP = re.compile(r"[\[(（]\s*(?:출처|근거)\s*(\d+(?:\s*[,，·、]\s*(?:출처\s*)?\d+)*)\s*[\])）]")
_CITE_BARE = re.compile(r"\[(\d{1,2})\]")
_MARK = re.compile(r"\[출처 (\d+)\]")
_SENT = re.compile(r"(?<=[.!?。])\s+|\n+")


def normalize_citations(text: str, n_sources: int) -> Tuple[str, List[int], List[int]]:
    """답의 출처 표기를 「[출처 n]」 하나로 맞추고, 근거 목록 밖의 번호는 지운다 → (글, 맞는 번호, 지운 번호)."""

    def _group(m: re.Match) -> str:
        nums = [int(x) for x in re.findall(r"\d+", m.group(1))]
        return "".join(f"[출처 {n}]" for n in nums)

    text = _CITE_GROUP.sub(_group, text)
    # 「[1]」 처럼 번호만 쓴 꼴 — 근거 목록 안의 번호일 때만 출처로 본다
    text = _CITE_BARE.sub(lambda m: f"[출처 {m.group(1)}]" if 1 <= int(m.group(1)) <= n_sources else m.group(0), text)
    valid: List[int] = []
    invalid: List[int] = []

    def _keep(m: re.Match) -> str:
        n = int(m.group(1))
        if 1 <= n <= n_sources:
            if n not in valid:
                valid.append(n)
            return m.group(0)
        if n not in invalid:
            invalid.append(n)
        return ""

    text = _MARK.sub(_keep, text)
    text = re.sub(r"(\[출처 \d+\])(?:\s*\1)+", r"\1", text)      # 같은 번호를 잇달아 쓴 것은 하나로
    # 「…이다. [출처 1]」 → 「…이다 [출처 1].」 — 마침표 뒤에 단 번호를 그 문장 안으로(문장마다 출처를 세려고)
    text = re.sub(r"([.!?。])[ \t]*((?:\[출처 \d+\])+)", r" \2\1", text)
    text = re.sub(r"[ \t]+([.,!?])", r"\1", re.sub(r"[ \t]{2,}", " ", text)).strip()
    return text, sorted(valid), sorted(invalid)


def sentence_check(text: str) -> Tuple[int, int]:
    """(문장 수, 출처가 없는 문장 수) — 다섯 글자가 안 되는 조각은 세지 않는다."""
    sents = [s.strip() for s in _SENT.split(text) if len(s.strip()) >= 5]
    return len(sents), sum(1 for s in sents if not _MARK.search(s))


def mostly_not_korean(text: str) -> bool:
    """로마자가 한글보다 많으면 참 — 생각 전용 판의 영어 생각 글이 답 길이 상한에서 잘려 그대로 오는 경우를 잡는다
    (그 글 안에도 「[출처 1]」 이 들어 있어 출처 검사만으로는 걸러지지 않았다 · 2026-10-03 근거답 평가)."""
    hangul = len(re.findall(r"[가-힣]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return latin > hangul


def is_no_answer(text: str) -> bool:
    t = re.sub(r"\s+", "", text)
    return t.startswith(re.sub(r"\s+", "", NO_ANSWER)[:8]) and len(t) <= len(re.sub(r"\s+", "", NO_ANSWER)) + 12


def excerpt_answer(hits: Sequence[dict], limit: int = 3) -> str:
    """LLM 없이 — 찾은 조문의 앞부분을 출처 번호와 함께 보인다(통합본 「원문만 정리」 방식)."""
    lines = ["근거 문서에서 찾은 조문입니다. 원문을 함께 확인하세요."]
    for i, h in enumerate(hits[:limit], start=1):
        body = re.sub(r"\s+", " ", h["text"]).strip()
        lines.append(f"[출처 {i}] {h['title']} {h['article']} — {body[:200]}{'…' if len(body) > 200 else ''}")
    return "\n".join(lines)


# ==================================================
# 4. 답하기
# ==================================================
def _citation(n: int, h: dict, used: bool) -> dict:
    # excerpt = 화면의 출처 카드가 펼쳐 보이는 조문 글(답 모델에 넣은 것과 같은 길이 · 머리 줄 뺌)
    return {"n": n, "chunk_id": h["chunk_id"], "doc_id": h["doc_id"], "title": h["title"], "grade": h["grade"],
            "kind": h["kind"], "article": h["article"], "article_title": h["article_title"], "part": h["part"],
            "effective_at": h["effective_at"], "version_label": h["version_label"], "url": h["url"],
            "score": h["score"], "used": used, "excerpt": citation_excerpt(h.get("text", ""))}


def ask(q: str, k: int = DEFAULT_ASK_K, *, as_of: Optional[str] = None, kind: Optional[str] = None,
        docs: Optional[Sequence[str]] = None, mode: str = "hybrid", model: Optional[str] = None, route: bool = True,
        answer: str = "llm", llm: Optional[str] = None, path=None, backend: Optional[kb_search.DenseBackend] = None,
        llm_backend: Optional[LlmBackend] = None) -> dict:
    q = (q or "").strip()
    if not q:
        raise kb_search.KbError(422, "질문이 비었다")
    if not 1 <= k <= MAX_ASK_K:
        raise kb_search.KbError(422, f"k 는 1~{MAX_ASK_K} 다: {k}")
    if answer not in ANSWER_MODES:
        raise kb_search.KbError(422, f"answer 는 {' · '.join(ANSWER_MODES)} 가운데 하나다: {answer!r}")
    if llm is not None and not _MODEL_NAME.match(llm):
        raise kb_search.KbError(422, f"llm 모델 이름 모양이 틀렸다: {llm!r}")

    t0 = time.perf_counter()
    if _DECLINE.search(q):
        return _result(q, kb_search._as_of(as_of), "declined",
                       "투자 권유나 가격 · 수익률 예측은 하지 않습니다. 법 · 규정 근거를 묻는 질문으로 바꿔 주세요.",
                       reason="종목 매수 · 매도 권유나 가격 예측을 묻는 질문이다(답변 정책 ④)",
                       citations=[], check=None, llm_info={"model": None, "mode": answer, "error": None},
                       found=None, timing={"search_ms": 0, "llm_ms": 0, "total_ms": _ms(t0)})

    found = kb_search.search(q, k, as_of=as_of, kind=kind, docs=docs, mode=mode, model=model, route=route,
                             path=path, backend=backend)
    t_search = _ms(t0)
    hits = found["hits"]
    llm_name = llm or (default_model() if answer == "llm" else None)
    info = {"model": llm_name, "mode": answer, "error": None}

    if not hits:
        return _result(q, found["as_of"], "no_evidence", NO_ANSWER,
                       reason="근거 문서에서 관련 조문을 찾지 못했다", citations=[], check=None, llm_info=info,
                       found=found, timing={"search_ms": t_search, "llm_ms": 0, "total_ms": _ms(t0)})

    if answer == "extract":
        return _result(q, found["as_of"], "excerpt", excerpt_answer(hits), reason="LLM 없이 근거 발췌만 요청했다",
                       citations=[_citation(i, h, i <= 3) for i, h in enumerate(hits, start=1)], check=None,
                       llm_info=info, found=found, timing={"search_ms": t_search, "llm_ms": 0, "total_ms": _ms(t0)})

    messages, n_in = build_messages(q, found["as_of"], hits)
    hits = hits[:n_in]
    t1 = time.perf_counter()
    try:
        out = (llm_backend or LlmBackend.from_settings()).chat(
            llm_name, messages, {"temperature": 0, "seed": SEED, "num_predict": NUM_PREDICT, "num_ctx": NUM_CTX})
    except Exception as e:  # noqa: BLE001 — 생성이 안 돼도 근거는 보인다(위 머리말)
        info["error"] = _llm_error(e, llm_name)
        return _result(q, found["as_of"], "excerpt", excerpt_answer(hits), reason=info["error"],
                       citations=[_citation(i, h, i <= 3) for i, h in enumerate(hits, start=1)], check=None,
                       llm_info=info, found=found,
                       timing={"search_ms": t_search, "llm_ms": _ms(t1), "total_ms": _ms(t0)})
    llm_ms = _ms(t1)
    info.update({"prompt_tokens": out.get("prompt_eval_count"), "answer_tokens": out.get("eval_count"),
                 "done_reason": out.get("done_reason")})
    raw = strip_thinking((out.get("message") or {}).get("content") or "")
    timing = {"search_ms": t_search, "llm_ms": llm_ms, "total_ms": _ms(t0)}

    if is_no_answer(raw):
        return _result(q, found["as_of"], "no_evidence", NO_ANSWER,
                       reason="답 모델이 넣은 근거로는 답할 수 없다고 했다",
                       citations=[_citation(i, h, False) for i, h in enumerate(hits, start=1)],
                       check={"valid": [], "invalid": [], "sentences": 0, "uncited": 0}, llm_info=info, found=found,
                       timing=timing, raw=raw)

    text, valid, invalid = normalize_citations(raw, len(hits))
    sents, uncited = sentence_check(text)
    check = {"valid": valid, "invalid": invalid, "sentences": sents, "uncited": uncited}
    if mostly_not_korean(text):
        return _result(q, found["as_of"], "excerpt", excerpt_answer(hits),
                       reason="답 모델의 글이 한국어가 아니다(생각 글이 새었을 수 있다) — 근거 발췌로 바꿨다",
                       citations=[_citation(i, h, i <= 3) for i, h in enumerate(hits, start=1)], check=check,
                       llm_info=info, found=found, timing=timing, raw=raw)
    if not valid:
        return _result(q, found["as_of"], "excerpt", excerpt_answer(hits),
                       reason="답 모델의 글에 근거 목록 안의 출처 번호가 하나도 없어 근거 발췌로 바꿨다(답변 정책 ①②)",
                       citations=[_citation(i, h, i <= 3) for i, h in enumerate(hits, start=1)], check=check,
                       llm_info=info, found=found, timing=timing, raw=raw)
    return _result(q, found["as_of"], "answered", text, reason=None,
                   citations=[_citation(i, h, i in valid) for i, h in enumerate(hits, start=1)], check=check,
                   llm_info=info, found=found, timing=timing)


def _ms(t: float) -> int:
    return int((time.perf_counter() - t) * 1000)


def _result(q: str, as_of: str, status: str, text: str, *, reason: Optional[str], citations: List[dict],
            check: Optional[dict], llm_info: dict, found: Optional[dict], timing: Dict[str, int],
            raw: Optional[str] = None) -> dict:
    out = {
        "query": q, "as_of": as_of, "status": status, "answer": text, "reason": reason,
        "citations": citations, "check": check,
        "model": llm_info.get("model"), "llm": llm_info,
        "embed_model": (found or {}).get("model"),
        "retrieval": (found or {}).get("retrieval"), "route": (found or {}).get("route"),
        "missing": (found or {}).get("missing", []),
        "timing": timing, "source": kb_search.SOURCE, "notice": NOTICE,
    }
    if raw is not None:
        out["llm"]["raw"] = raw[:2000]   # 검사에서 버린 원문 — 화면은 보이지 않고 평가 · 감사에만 쓴다
    return out
