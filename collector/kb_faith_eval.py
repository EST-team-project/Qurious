"""근거 답 충실도 자동 평가 — 심판 LLM 지표를 사람 판정과 맞춘다 (목표 기능 ① W8 · 조사서 「근거충실도-자동지표」).

    python -m collector.kb_faith_eval run --answers <kb_answer_eval-….json> … --judges llama3.1 exaone3.5:2.4b
    python -m collector.kb_faith_eval report <kb_faith_eval-….json>          사람 판정과 맞춘 표 · 어긋난 답

무엇을 재나
-----------
- ``faithfulness`` — Ragas 0.4.3 ``ragas.metrics.collections.Faithfulness`` 그대로(답을 주장으로 쪼갠다 → 주장마다
  근거로 바로 추론되나 0 · 1 → 비율). 심판은 **답 모델(qwen3:4b-instruct)과 다른 계열의 로컬 모델**이다.
- ``numbers`` — LLM 없이, 답의 숫자 표현(「1만분의 5」 · 「30억원」 · 「2주」)이 넣은 근거 글에 그대로 있나(조사서 3.3).

어떻게
------
1. 답 평가 결과 파일(``kb_answer_eval``)의 답마다 **답 모델이 받은 근거 문맥을 같은 검색 길로 다시 만든다**
   (``kb_answer.ask`` 의 찾기 → 위임 조 끼우기 → 자리 맞추기 → 프롬프트와 같은 순서 · 같은 인자). 결과 파일에 남은 근거
   목록(``cited``)과 다시 만든 목록이 다르면 그 답은 재지 않고 ``rebuild_mismatch`` 로 센다 — 다른 문맥으로 잰 점수는
   그 답의 점수가 아니다. 결과 파일은 근거 글을 담지 않으므로(조 번호만) 이 길이 유일하다.
2. 심판 호출은 Ollama ``/api/chat`` 에 JSON 스키마(``format``)를 주고 온도 0 · 씨앗 42 · ``num_ctx`` 8192 로 한다.
   Ragas 가 기본으로 쓰는 OpenAI 호환 주소는 ``num_ctx`` 를 넘길 수 없어(Ollama 문서) 긴 근거가 잘릴 수 있다.
3. Ragas 의 예시(few-shot)는 영어다. 작은 심판은 영어 예시를 따라 주장을 영어로 옮기다 숫자를 틀리게 번역했다
   (2026-10-06 실측 — 「1만분의 5」 → 「one thousand five hundredths」 → 0점). Ragas 가 다른 언어용으로 주는
   ``adapt()``(예시만 그 언어로 · 지시문은 그대로)와 같은 일을 **손으로 옮긴 고정 예시**로 한다 — 번역을 심판에게
   맡기지 않아 재현된다(``korean_prompts``).
4. 두 길(분류 길 · 지금 길)의 답이 글자까지 같고 근거 목록도 같으면 한 번만 잰다(``same_as``).

사람 판정과 맞추기
------------------
정답지는 ``docs/시험/근거충실도-사람판정_v1.tsv``(2026-10-06 판정 46). 충실도는 「근거에 있는 말만 했나」 이지
「맞는 답인가」 가 아니다 — 근거에 있는 다른 값(같은 조의 다른 항)을 고른 답, 빗나간 조를 충실하게 옮긴 답은
충실도가 높게 나올 수 있다. 그래서 오답을 종류별로 나눠 「잡아야 하는 것」 과 「이 지표로는 못 잡는 것」 을 따로 센다.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import hashlib
import json
import re
import statistics
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from collector import config
from collector.console import utf8_stdio
from collector import kb_index

sys.path.insert(0, str(config.ROOT))
from app.services import kb_answer, kb_links, kb_search, kb_synonyms  # noqa: E402

LABELS = config.ROOT / "docs" / "시험" / "근거충실도-사람판정_v1.tsv"
SETS = ("근거답-평가셋_v2.tsv", "섹터법령-평가셋_v1.tsv", "섹터법령-표본밖_v1.tsv", "근거답-평가셋_v1.tsv")
JUDGES = ["llama3.1", "exaone3.5:2.4b"]
#: 심판 호출 옵션 — num_batch 는 한 번에 GPU 에 넘기는 토큰 묶음. 기본 512 보다 줄여 내장 GPU 의 긴 계산 한 번을
#: 짧게 쪼갠다(DF-65 「device lost」 를 줄여 보려는 것 · 효과는 아직 재지 않음)
JUDGE_OPTIONS = {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 1536, "num_batch": 256}


# ==================================================
# 1. 근거 문맥 다시 만들기 — kb_answer.ask 와 같은 순서 · 같은 인자
# ==================================================
def rebuild_context(q: str, k: int, *, synonyms: bool = True, links: bool = True, sector: bool = True,
                    backend=None, path=None, as_of: Optional[str] = None, mode: str = "hybrid") -> Optional[dict]:
    """답 모델이 받은 [근거] 덩어리를 다시 만든다. 찾은 근거가 없으면 None. ``as_of`` · ``mode`` 는 시험용
    (평가 결과 파일은 기준일을 비우고 hybrid 로 돌았다 — ``kb_answer_eval.run_model``)."""
    found = kb_search.search(q, k, as_of=as_of, kind=None, docs=None, mode=mode, model=None, route=True,
                             links=links, synonyms=synonyms, sector=sector, path=path, backend=backend)
    hits = kb_links.expand(found["hits"], limit=k + kb_answer.LINK_EXTRA)
    if not hits:
        return None
    q_ctx = kb_synonyms.annotate(q, kb_synonyms.match(q)) if synonyms else q
    hits = kb_answer.fit_evidence(hits, [h["chunk_id"] for h in found["hits"]])
    messages, n_in = kb_answer.build_messages(q_ctx, found["as_of"], hits,
                                              context_chars=kb_answer.CONTEXT_CHARS + kb_answer.LINK_CHARS + 1000)
    hits = hits[:n_in]
    return {"cited": [f"{h['doc_id']}:{h['article']}" for h in hits], "contexts": split_blocks(messages[1]["content"]),
            "as_of": found["as_of"], "q_ctx": q_ctx}


def split_blocks(user: str) -> List[str]:
    """프롬프트의 [근거] 부분을 「[출처 n] …」 덩어리로 나눈다(위임 조 알림 줄은 그 덩어리에 붙은 채로)."""
    ev = user.split("[근거]\n", 1)[1].rsplit("\n\n[질문]\n", 1)[0]
    return re.split(r"\n\n(?=\[출처 \d+\] )", ev)


# ==================================================
# 2. 숫자 근거 확인 — LLM 없음
# ==================================================
_UNIT = r"(?:퍼센트|%|억원|만원|천원|원|개월|개|일|년|주|배|명|회|시간|세|킬로리터|리터|평방미터|제곱미터)"
#: 「1만분의 5」 · 「30억원」 · 「88만5700원」 · 「5만 7천원」 — 만 · 억 같은 자릿수 뒤에 숫자가 이어지는 꼴도 한 덩어리로.
#: 「제8조」 · 「8조 1항」 처럼 조 · 항 · 호 · 목 번호는 값이 아니라 뺀다(앞의 「제」 · 뒤의 조항호목).
_NUM = re.compile(r"(?<![제\d])(\d[\d,]*(?:\.\d+)?(?:\s*(?:조|천억|백억|십억|억|천만|백만|십만|만|천|백)"
                  r"(?:\s*\d[\d,]*(?:\.\d+)?)?)*(?:\s*분의\s*\d[\d,]*(?:\.\d+)?)?\s*" + _UNIT
                  + r"?)(?!\s*[조항호목](?![가-힣]))")
_CITE = re.compile(r"\[출처 \d+\]")


def _norm(s: str) -> str:
    return re.sub(r"[\s,]", "", s)


def number_phrases(answer: str) -> List[str]:
    """답의 숫자 표현 — 출처 표시 · 조 · 항 · 호 번호(「제8조」 · 「8조」 · 「제1항」)는 값이 아니라 뺀다."""
    text = _CITE.sub(" ", answer)
    out = []
    for m in _NUM.finditer(text):
        p = m.group(1).strip()
        if not re.search(r"\d", p) or re.fullmatch(r"\d", p):   # 한 자리 맨숫자(「1.」 같은 목록 번호)는 뺀다
            continue
        if p not in out:
            out.append(p)
    return out


def number_check(answer: str, contexts: Sequence[str], question: str = "") -> dict:
    """{"found": […], "missing": […], "echo": […]} — 공백 · 쉼표를 지운 글자로 근거 글 안에 있나 본다.
    질문에 이미 있는 숫자(「2026년에 …」)는 답이 되풀이한 전제라 따지지 않고 ``echo`` 로 둔다."""
    ev, qn = _norm("\n".join(contexts)), _norm(question)
    found, missing, echo = [], [], []
    for p in number_phrases(answer):
        if qn and _norm(p) in qn:
            echo.append(p)
        else:
            (found if _norm(p) in ev else missing).append(p)
    return {"found": found, "missing": missing, "echo": echo}


# ==================================================
# 3. 심판 — Ragas Faithfulness · Ollama
# ==================================================
def _ragas():
    """Ragas 를 늦게 가져온다 — 앱 이미지에는 없고(조사서 4절) 시험은 이 함수 없이 돈다."""
    from ragas.llms.base import InstructorBaseRagasLLM
    from ragas.metrics.collections import Faithfulness
    from ragas.metrics.collections.faithfulness import util
    return InstructorBaseRagasLLM, Faithfulness, util


def make_judge(model: str, url: str = kb_index.OLLAMA_URL, timeout: float = 900, http=None, seed: int = 42):
    base, _, _ = _ragas()

    class OllamaJudge(base):
        """Ragas 의 심판 자리(``InstructorBaseRagasLLM``)에 끼우는 Ollama 심판 — 호출마다 시간 · 토큰을 남긴다."""

        def __init__(self):
            self.model, self.seed, self.calls = model, seed, []

        def generate(self, prompt, response_model):
            body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False,
                    "format": response_model.model_json_schema(), "options": dict(JUDGE_OPTIONS, seed=seed)}
            if model.lower().startswith(kb_answer.THINKING_PREFIXES):
                body["think"] = False
            t0 = time.time()
            out = (http or _post)(f"{url}/api/chat", body, timeout)
            content = (out.get("message") or {}).get("content") or ""
            self.calls.append({"secs": round(time.time() - t0, 1), "prompt_tokens": out.get("prompt_eval_count"),
                               "out_tokens": out.get("eval_count")})
            return response_model.model_validate_json(content)

        async def agenerate(self, prompt, response_model):
            return await asyncio.to_thread(self.generate, prompt, response_model)

    return OllamaJudge()


def _post(url: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def korean_prompts(metric):
    """Ragas ``BasePrompt.adapt("korean")`` 와 같은 일 — 예시(few-shot)만 한국어로, 지시문은 영어 그대로.

    원래 예시(아인슈타인 · 존)를 뜻 그대로 옮겼다. 번역을 심판에게 맡기지 않는 까닭은 머리말 3.
    """
    _, _, u = _ragas()
    sg = copy.deepcopy(metric.statement_generator_prompt)
    sg.examples = [(
        u.StatementGeneratorInput(
            question="알베르트 아인슈타인은 누구이며 무엇으로 가장 잘 알려져 있나요?",
            answer="그는 독일 태생의 이론물리학자로, 역사상 가장 위대하고 영향력 있는 물리학자 가운데 한 사람으로 널리 "
                   "인정받는다. 그는 상대성 이론을 발전시킨 것으로 가장 잘 알려져 있으며, 양자역학 이론의 발전에도 중요한 "
                   "기여를 했다."),
        u.StatementGeneratorOutput(statements=[
            "알베르트 아인슈타인은 독일 태생의 이론물리학자이다.",
            "알베르트 아인슈타인은 역사상 가장 위대하고 영향력 있는 물리학자 가운데 한 사람으로 인정받는다.",
            "알베르트 아인슈타인은 상대성 이론을 발전시킨 것으로 가장 잘 알려져 있다.",
            "알베르트 아인슈타인은 양자역학 이론의 발전에 중요한 기여를 했다."]))]
    sg.language = "korean"
    nli = copy.deepcopy(metric.nli_statement_prompt)
    nli.examples = [(
        u.NLIStatementInput(
            context="존은 XYZ 대학교의 학생이다. 그는 컴퓨터공학 학위 과정을 밟고 있다. 그는 이번 학기에 자료구조, "
                    "알고리즘, 데이터베이스 관리를 포함해 여러 과목을 듣고 있다. 존은 성실한 학생이며 공부와 과제에 많은 "
                    "시간을 쓴다. 그는 프로젝트를 하느라 도서관에 늦게까지 남아 있곤 한다.",
            statements=["존은 생물학을 전공하고 있다.", "존은 인공지능 과목을 듣고 있다.", "존은 헌신적인 학생이다.",
                        "존은 아르바이트를 하고 있다."]),
        u.NLIStatementOutput(statements=[
            u.StatementFaithfulnessAnswer(statement="존은 생물학을 전공하고 있다.",
                                          reason="존의 전공은 생물학이 아니라 컴퓨터공학이라고 분명히 적혀 있다.",
                                          verdict=0),
            u.StatementFaithfulnessAnswer(statement="존은 인공지능 과목을 듣고 있다.",
                                          reason="문맥은 자료구조, 알고리즘, 데이터베이스 관리 과목을 말하지만 인공지능은 "
                                                 "말하지 않는다.", verdict=0),
            u.StatementFaithfulnessAnswer(statement="존은 헌신적인 학생이다.",
                                          reason="문맥은 존이 성실한 학생이며 공부와 과제에 많은 시간을 쓴다고 적고 있다.",
                                          verdict=1),
            u.StatementFaithfulnessAnswer(statement="존은 아르바이트를 하고 있다.",
                                          reason="문맥에 존의 아르바이트에 관한 내용이 없다.", verdict=0)]))]
    nli.language = "korean"
    metric.statement_generator_prompt = sg
    metric.nli_statement_prompt = nli
    return metric


async def _faithfulness(metric, q: str, answer: str, contexts: Sequence[str]) -> dict:
    """Ragas ``Faithfulness.ascore`` 와 같은 세 단계 — 주장 · 판정 글까지 남기려고 단계를 나눠 부른다."""
    resp = re.sub(r"\s*\[출처 \d+\]", "", answer).strip()
    stmts = await metric._create_statements(q, resp)
    if not stmts:
        return {"score": None, "statements": [], "verdicts": []}
    verdicts = await metric._create_verdicts(stmts, "\n".join(contexts))
    score = metric._compute_score(verdicts)
    return {"score": None if score != score else round(score, 4), "statements": stmts,   # NaN → None
            "verdicts": [{"statement": v.statement, "verdict": v.verdict, "reason": v.reason}
                         for v in verdicts.statements]}


def judge_answer(judge, q: str, answer: str, contexts: Sequence[str], retry_judge=None) -> dict:
    """한 답의 충실도. 심판이 깨진 JSON 을 내면(같은 글자를 되풀이하다 출력 상한에 걸림 · 2026-10-06 S01) 씨앗만 바꾼
    ``retry_judge`` 로 한 번 더 잰다 — 다시 재도 깨지면 점수 없음으로 남기고 센다(심판의 실패율도 품질이다)."""
    _, faith_cls, _ = _ragas()
    t0 = time.time()
    out = _one(faith_cls, judge, q, answer, contexts)
    calls = out.pop("_calls")
    if out["error"] and retry_judge is not None:
        first = out["error"]
        out = _one(faith_cls, retry_judge, q, answer, contexts)
        calls += out.pop("_calls")
        out["retried"] = {"seed": retry_judge.seed, "first_error": first}
    out["calls"] = calls
    out["secs"] = round(time.time() - t0, 1)
    return out


def _one(faith_cls, judge, q, answer, contexts) -> dict:
    metric = korean_prompts(faith_cls(llm=judge))
    n0 = len(judge.calls)
    try:
        out = asyncio.run(_faithfulness(metric, q, answer, contexts))
        out["error"] = None
    except Exception as e:  # noqa: BLE001 — 한 문항의 심판 실패가 평가 전체를 멈추지 않게 남기고 넘어간다
        out = {"score": None, "statements": [], "verdicts": [], "error": f"{type(e).__name__}: {str(e)[:300]}"}
    out["_calls"] = judge.calls[n0:]
    return out


# ==================================================
# 4. 실행
# ==================================================
def load_questions() -> Dict[str, str]:
    qs: Dict[str, str] = {}
    for name in SETS:
        p = config.ROOT / "docs" / "시험" / name
        if not p.exists():
            continue
        with p.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                qs.setdefault(r["id"], r["질문"])
    return qs


def load_labels(path: Path = LABELS) -> Dict[Tuple[str, str], dict]:
    """(결과 파일 이름, id) → 판정 줄."""
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    out = {}
    for r in rows:
        if r["판정"] not in ("정답", "부분", "오답"):
            raise SystemExit(f"판정 칸이 틀렸다 — {r['id']}: {r['판정']!r}")
        out[(r["결과파일"], r["id"])] = r
    return out


def tool_fingerprint() -> str:
    """이 파일의 sha256 앞 12자 — 결과 파일에 남겨 어느 판의 도구로 쟀는지 가린다(줄 끝은 접는다 · DF-68)."""
    b = Path(__file__).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(b).hexdigest()[:12]


def run(answer_files: Sequence[Path], judges: Sequence[str], *, ids: Sequence[str] = (), out: Path,
        rest_every: int = 15, rest_secs: int = 60, labels: Optional[Dict] = None) -> dict:
    qs = load_questions()
    dense = kb_search.DenseBackend(ollama_url=kb_index.OLLAMA_URL, qdrant_url=kb_index.QDRANT_URL)
    items: List[dict] = []
    seen: Dict[Tuple, str] = {}
    for f in answer_files:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for res in d["results"]:
            for p in res["per"]:
                if ids and not p["id"].startswith(tuple(ids)):
                    continue
                if p["status"] != "answered":
                    continue
                key = (qs.get(p["id"]), p["answer"], tuple(p.get("cited") or ()))
                item = {"file": Path(f).stem, "id": p["id"], "sector": res.get("sector", True),
                        "synonyms": res.get("synonyms", True), "links": res.get("links", True), "k": d["k"],
                        "model": res["model"], "question": qs.get(p["id"]), "answer": p["answer"],
                        "cited": p.get("cited"), "same_as": seen.get(key)}
                if labels is not None:
                    lab = labels.get((item["file"], item["id"]))
                    item["label"] = lab["판정"] if lab else None
                    item["label_kind"] = lab.get("오답_종류") if lab else None
                if item["same_as"] is None:
                    seen[key] = f"{item['file']}:{item['id']}"
                items.append(item)
    doc = {"at": datetime.now().isoformat(timespec="seconds"), "tool": tool_fingerprint(), "judges": list(judges),
           "options": JUDGE_OPTIONS, "ragas": _ragas_version(), "answers": [Path(f).name for f in answer_files],
           "items": items}
    _write(out, doc)
    print(f"― 충실도 평가 · 답 {len(items)}(중복 {sum(1 for i in items if i['same_as'])}) · 심판 {', '.join(judges)} ―",
          flush=True)
    build_contexts(items, dense)
    _write(out, doc)
    judge_all(doc, out, judges, rest_every=rest_every, rest_secs=rest_secs)
    return doc


def build_contexts(items: List[dict], dense) -> None:
    """문맥은 심판과 상관없이 한 번만 만든다(결정적) — 이어 재기에서는 이미 만든 것을 건너뛴다."""
    for it in items:
        if it["same_as"] or "contexts" in it:
            continue
        ctx = rebuild_context(it["question"], it["k"], synonyms=it["synonyms"], links=it["links"],
                              sector=it["sector"], backend=dense)
        it["rebuilt_same"] = bool(ctx) and ctx["cited"] == it["cited"]
        it["contexts"] = ctx["contexts"] if ctx else []
        it["context_chars"] = sum(len(c) for c in it["contexts"])
        it["numbers"] = number_check(it["answer"], it["contexts"], it["question"] or "") if it["rebuilt_same"] else None
        it["judges"] = {}


def judge_all(doc: dict, out: Path, judges: Sequence[str], *, rest_every: int = 15, rest_secs: int = 60) -> None:
    """심판마다 차례로 — 이미 점수가 있는 답은 건너뛴다(이어 재기). 깨진 JSON 은 씨앗 43 으로 한 번 더."""
    items = doc["items"]
    for jm in judges:
        if jm not in doc["judges"]:
            doc["judges"].append(jm)
        judge, retry = make_judge(jm), make_judge(jm, seed=43)
        n = 0
        for it in items:
            if it["same_as"] or not it.get("rebuilt_same"):
                continue
            prev = (it.get("judges") or {}).get(jm)
            if prev and prev.get("score") is not None:
                continue
            r = judge_answer(judge, it["question"], it["answer"], it["contexts"], retry_judge=retry)
            it.setdefault("judges", {})[jm] = r
            _write(out, doc)   # 문항마다 — 긴 평가가 중간에 멈춰도 앞 결과는 남는다
            n += 1
            print(f"  [{jm}] {it['file'][-6:]} {it['id']} {it.get('label') or '-':<3} score={r['score']} "
                  f"{r['secs']:5.1f}s {'(다시 잼) ' if r.get('retried') else ''}"
                  f"{('ERR ' + r['error'][:80]) if r['error'] else ''}", flush=True)
            if rest_every and n % rest_every == 0:
                print(f"  … {rest_secs}초 쉼(DF-65 — 내장 GPU 를 오래 이어 쓰지 않는다)", flush=True)
                time.sleep(rest_secs)
        _unload(jm)
    doc["done"] = datetime.now().isoformat(timespec="seconds")
    _write(out, doc)


def resume(path: Path, judges: Sequence[str], *, rest_every: int = 15, rest_secs: int = 60) -> dict:
    """멈춘 평가를 같은 결과 파일에 이어서 — 문맥이 빠진 답만 다시 만들고, 점수가 없는 답만 잰다."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.setdefault("resumed", []).append({"at": datetime.now().isoformat(timespec="seconds"),
                                          "tool": tool_fingerprint()})
    dense = kb_search.DenseBackend(ollama_url=kb_index.OLLAMA_URL, qdrant_url=kb_index.QDRANT_URL)
    build_contexts(doc["items"], dense)
    for it in doc["items"]:   # 숫자 확인은 LLM 없이 몇 밀리초 — 도구가 바뀌었을 수 있어 늘 다시 낸다
        if it.get("rebuilt_same") and it.get("contexts"):
            it["numbers"] = number_check(it["answer"], it["contexts"], it.get("question") or "")
    _write(path, doc)
    judge_all(doc, path, judges or doc["judges"], rest_every=rest_every, rest_secs=rest_secs)
    return doc


def _unload(model: str) -> None:
    try:
        _post(f"{kb_index.OLLAMA_URL}/api/generate", {"model": model, "keep_alive": 0}, 60)
    except Exception:  # noqa: BLE001
        pass


def _ragas_version() -> Optional[str]:
    try:
        import ragas
        return ragas.__version__
    except Exception:  # noqa: BLE001
        return None


def _write(out: Path, doc: dict) -> None:
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


def new_path(prefix: str = "kb_faith_eval") -> Path:
    """겹치지 않는 결과 파일 이름(초까지 · 같은 초면 번호) — kb_answer_eval 과 같은 규칙(DF-58)."""
    base = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        out = config.STATE_DIR / (f"{base}.json" if n == 1 else f"{base}-{n}.json")
        try:
            out.touch(exist_ok=False)
            return out
        except FileExistsError:
            n += 1


# ==================================================
# 5. 사람 판정과 맞추기
# ==================================================
def resolve(items: List[dict]) -> List[dict]:
    """``same_as`` 인 줄에 원래 줄의 문맥 · 숫자 · 심판 결과를 채운 사본."""
    by = {f"{i['file']}:{i['id']}": i for i in items}
    out = []
    for it in items:
        src = by.get(it["same_as"]) if it.get("same_as") else it
        x = dict(it)
        for k in ("rebuilt_same", "contexts", "numbers", "judges", "context_chars"):
            x[k] = (src or {}).get(k)
        out.append(x)
    return out


def summarize(items: List[dict], judge: str, thresholds: Sequence[float] = (1.0, 0.8, 0.5)) -> dict:
    """판정별 점수 분포와 문턱마다 「점수 < 문턱」 인 수. 같은 답(same_as)은 한 번만 센다."""
    rows = [i for i in items if not i.get("same_as") and i.get("label") and (i.get("judges") or {}).get(judge)]
    by: Dict[str, List[float]] = {}
    err = 0
    for i in rows:
        s = i["judges"][judge]["score"]
        if s is None:
            err += 1
            continue
        by.setdefault(i["label"], []).append(s)
    out = {"n": len(rows), "no_score": err, "labels": {}}
    for lab, xs in sorted(by.items()):
        out["labels"][lab] = {"n": len(xs), "mean": round(statistics.mean(xs), 3),
                              "below": {str(t): sum(1 for x in xs if x < t) for t in thresholds}}
    return out


def report(path: Path) -> int:
    utf8_stdio()
    doc = json.loads(path.read_text(encoding="utf-8"))
    items = resolve(doc["items"])
    print(f"― {path.name} · 도구 {doc['tool']} · Ragas {doc.get('ragas')} · 심판 {', '.join(doc['judges'])} ―")
    miss = [i for i in items if not i.get("same_as") and i.get("rebuilt_same") is False]
    print(f"문맥을 다시 만들지 못한 답 {len(miss)}: {[i['id'] for i in miss]}")
    for jm in doc["judges"]:
        s = summarize(items, jm)
        print(f"\n[{jm}] 잰 답 {s['n']} · 점수 없음 {s['no_score']}")
        print(f"  {'판정':<4}{'수':>4}{'평균':>7}{'<1.0':>6}{'<0.8':>6}{'<0.5':>6}")
        for lab, v in s["labels"].items():
            b = v["below"]
            print(f"  {lab:<4}{v['n']:>4}{v['mean']:>7}{b['1.0']:>6}{b['0.8']:>6}{b['0.5']:>6}")
    print("\n문항별(같은 답은 한 번):")
    for i in items:
        if i.get("same_as"):
            continue
        sc = " ".join(f"{(i.get('judges') or {}).get(j, {}).get('score')!s:>6}" for j in doc["judges"])
        nm = i.get("numbers") or {}
        print(f"  {i['file'][-6:]} {i['id']:<4} {i.get('label') or '-':<3} {sc}  근거에 없는 숫자 {nm.get('missing')}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.kb_faith_eval", description="근거 답 충실도 자동 평가")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="심판으로 재고 결과 JSON 을 data/collector/state 에")
    r.add_argument("--answers", nargs="+", help="kb_answer_eval 결과 JSON")
    r.add_argument("--resume", default="", help="멈춘 결과 JSON 에 이어서(--answers 대신)")
    r.add_argument("--judges", nargs="+", default=JUDGES)
    r.add_argument("--ids", default="", help="이 머리로 시작하는 id 만(쉼표로 여럿)")
    r.add_argument("--rest-every", type=int, default=15)
    r.add_argument("--rest-secs", type=int, default=60)
    r.add_argument("--labels", default=str(LABELS))
    rp = sub.add_parser("report", help="사람 판정과 맞춘 표")
    rp.add_argument("result")
    a = p.parse_args(argv)
    if a.cmd == "report":
        return report(Path(a.result))
    if a.resume:
        print(f"이어 재기: {a.resume}", flush=True)
        resume(Path(a.resume), a.judges, rest_every=a.rest_every, rest_secs=a.rest_secs)
        return report(Path(a.resume))
    if not a.answers:
        p.error("run 에는 --answers 또는 --resume 이 필요하다")
    labels = load_labels(Path(a.labels)) if a.labels else None
    out = new_path()
    print(f"결과: {out}", flush=True)
    ids = [h.strip() for h in a.ids.split(",") if h.strip()]
    run([Path(x) for x in a.answers], a.judges, ids=ids, out=out, rest_every=a.rest_every, rest_secs=a.rest_secs,
        labels=labels)
    return report(out)


if __name__ == "__main__":
    raise SystemExit(main())
