"""근거 답 평가 — 답 모델마다 같은 질문으로 출처 번호 · 정답 조 인용 · 근거 없음 · 걸린 시간을 잰다 (목표 기능 ① W6 · 설계서 5.3.5).

    python -m collector.kb_answer_eval                                   기본 모델 넷(아래 MODELS) 전부
    python -m collector.kb_answer_eval --models qwen3:4b llama3.1        고른 모델만
    python -m collector.kb_answer_eval --save                            결과를 data/collector/state/kb_answer_eval-<날짜>.json 에도
    python -m collector.kb_answer_eval --models qwen3:4b-instruct --synonyms off --links off   고치기 전 길(DF-59 전)과 견주기

평가셋 — ``docs/시험/근거답-평가셋_v1.tsv`` (질문 20 · 2026-10-04 · v0 15 + 위임 조 · 법령 말 · 바뀐 법 값 5)
--------------------------------------------------------------------------------------------------------
- ``answer``   근거 문서에 답이 있는 질문 15(v0 의 10 + 위임 조에 값이 있는 것 3 · 법령 말이 다른 것 1 · 검색이
               놓치는 것 1). 정답은 「문서:조」. A11 은 2026.7.28 개정으로 값이 바뀐 조(30억원)라 옛 지식(10억원)을
               지어내는지도 본다.
- ``abstain``  근거 문서 밖 질문 3 — 답하지 않아야 맞다(``no_evidence``). 근거 발췌(``excerpt``)는 「안전한 실패」 로 따로 센다.
- ``declined`` 가격 예측 · 매수 권유 2 — 모델과 상관없이 서버가 돌려보내는지만 본다.

지표(모델마다)
--------------
- 답함        answer 질문 가운데 ``answered`` 비율
- 정답 조 인용 answer 질문 가운데 쓰인 출처(used)에 정답 조가 있는 비율
- 번호 맞음    답한 것 가운데 목록 밖 번호(invalid)가 없는 비율
- 문장 출처    답한 것의 「출처가 달린 문장 ÷ 문장」 평균
- 근거 없음    abstain 질문 가운데 ``no_evidence`` 비율(답해 버리면 지어낸 것으로 본다)
- 시간        생성 걸린 시간 중앙값 · 넣은 · 쓴 토큰 평균

답의 옳고 그름(근거 밖 문장)은 사람이 읽어 판정한다 — 이 도구는 답 글을 모두 결과 파일에 남기고 ``--show`` 로 찍는다.
같은 Ollama 에서 모델을 차례로 돌리고, 모델을 바꿀 때 앞 모델을 내린다(메모리 · 시간 측정을 섞지 않으려고).
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from collector import config
from collector.console import utf8_stdio
from collector import kb_index

sys.path.insert(0, str(config.ROOT))
from app.services import kb_answer, kb_search  # noqa: E402

EVAL_SET = config.ROOT / "docs" / "시험" / "근거답-평가셋_v1.tsv"
# 2026-10-03 에 견준 다섯 가운데 넷 — Ollama 의 `qwen3:4b` 는 생각 전용 판(Thinking-2507)이라 빼고 생각 없는 판을 넣었다.
# 맨 앞이 기본 답 모델(app.services.kb_answer.DEFAULT_ANSWER_MODEL)이다.
MODELS = ["qwen3:4b-instruct", "exaone3.5:2.4b", "hf.co/Mungert/kanana-1.5-8b-instruct-2505-GGUF:Q4_K_M", "llama3.1"]


def load(path: Path = EVAL_SET) -> List[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for r in rows:
        # 마지막 콜론에서 나눈다 — 문서 ID 에 콜론이 있을 수 있다(섹터 법령 실험 `sec:은행법` · kb_eval.load 와 같은 규칙)
        r["gold"] = [] if r["정답"] == "없음" else [tuple(g.strip().rsplit(":", 1)) for g in r["정답"].split(";")
                                                  if g.strip()]
        if r["기대"] not in ("answer", "abstain", "declined"):
            raise SystemExit(f"기대 칸이 틀렸다 — {r['id']}: {r['기대']!r}")
    return rows


def unload(model: str) -> None:
    """모델을 메모리에서 내린다(keep_alive 0) — 다음 모델의 시간 측정에 섞이지 않게."""
    try:
        kb_answer._http_json("POST", f"{kb_index.OLLAMA_URL}/api/generate", {"model": model, "keep_alive": 0}, 60)
    except Exception:  # noqa: BLE001 — 내리기 실패는 평가를 막지 않는다
        pass


def run_model(model: str, rows: List[dict], k: int, *, synonyms: bool = True, links: bool = True) -> dict:
    dense = kb_search.DenseBackend(ollama_url=kb_index.OLLAMA_URL, qdrant_url=kb_index.QDRANT_URL)
    llm = kb_answer.LlmBackend(ollama_url=kb_index.OLLAMA_URL, timeout=900)
    per = []
    for r in rows:
        out = kb_answer.ask(r["질문"], k, llm=model, synonyms=synonyms, links=links, backend=dense, llm_backend=llm)
        gold = {(d, a) for d, a in r["gold"]}
        used = [(c["doc_id"], c["article"]) for c in out["citations"] if c["used"]]
        per.append({
            "id": r["id"], "expect": r["기대"], "status": out["status"], "answer": out["answer"],
            "reason": out["reason"], "check": out["check"], "gold_cited": bool(gold & set(used)),
            "gold_in_context": bool(gold & {(c["doc_id"], c["article"]) for c in out["citations"]}),
            "used": [f"{d}:{a}" for d, a in used], "llm_ms": out["timing"]["llm_ms"],
            "prompt_tokens": out["llm"].get("prompt_tokens"), "answer_tokens": out["llm"].get("answer_tokens"),
            "error": out["llm"].get("error"), "raw": out["llm"].get("raw"),
        })
        print(f"  {r['id']} {out['status']:<11} {out['timing']['llm_ms']/1000:6.1f}s  {out['answer'][:70]!r}", flush=True)
    unload(model)
    return {"model": model, "synonyms": synonyms, "links": links, "per": per, "summary": summarize(per)}


def _ratio(xs: List[bool]) -> Optional[float]:
    return round(sum(xs) / len(xs), 3) if xs else None


def summarize(per: List[dict]) -> dict:
    ans = [p for p in per if p["expect"] == "answer"]
    answered = [p for p in ans if p["status"] == "answered"]
    abst = [p for p in per if p["expect"] == "abstain"]
    dec = [p for p in per if p["expect"] == "declined"]
    gen = [p["llm_ms"] for p in per if p["llm_ms"]]
    cited = [1 - p["check"]["uncited"] / p["check"]["sentences"] for p in answered
             if p["check"] and p["check"]["sentences"]]
    return {
        "answered": _ratio([p["status"] == "answered" for p in ans]),
        "gold_cited": _ratio([p["gold_cited"] for p in ans]),
        "gold_in_context": _ratio([p["gold_in_context"] for p in ans]),
        "no_invalid": _ratio([not p["check"]["invalid"] for p in answered if p["check"]]),
        "sentence_cited": round(statistics.mean(cited), 3) if cited else None,
        "abstain_ok": _ratio([p["status"] == "no_evidence" for p in abst]),
        "abstain_safe": _ratio([p["status"] in ("no_evidence", "excerpt") for p in abst]),
        "declined_ok": _ratio([p["status"] == "declined" for p in dec]),
        "llm_median_s": round(statistics.median(gen) / 1000, 1) if gen else None,
        "prompt_tokens_avg": round(statistics.mean([p["prompt_tokens"] for p in per if p["prompt_tokens"]]))
        if any(p["prompt_tokens"] for p in per) else None,
        "answer_tokens_avg": round(statistics.mean([p["answer_tokens"] for p in per if p["answer_tokens"]]))
        if any(p["answer_tokens"] for p in per) else None,
        "errors": sum(1 for p in per if p["error"]),
    }


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.kb_answer_eval", description="근거 답 평가 — 답 모델 비교")
    p.add_argument("--models", nargs="+", default=MODELS)
    p.add_argument("--k", type=int, default=kb_answer.DEFAULT_ASK_K)
    p.add_argument("--save", action="store_true", help="결과 JSON 을 data/collector/state 에")
    p.add_argument("--show", action="store_true", help="답 글을 모두 찍는다")
    p.add_argument("--set", default=str(EVAL_SET), help="평가셋 TSV")
    p.add_argument("--synonyms", choices=("on", "off"), default="on", help="질문 말 → 법령 말(kb_synonyms)")
    p.add_argument("--links", choices=("on", "off"), default="on", help="위임 조 함께 넣기(kb_links)")
    a = p.parse_args(argv)
    rows = load(Path(a.set))
    syn, links = a.synonyms == "on", a.links == "on"
    print(f"― 근거 답 평가 · {Path(a.set).name} · 질문 {len(rows)} · 모델 {len(a.models)} · k={a.k} · "
          f"동의어 {a.synonyms} · 위임 조 {a.links} ―", flush=True)
    results = []
    out = _new_path()
    for m in a.models:
        print(f"[{m}]", flush=True)
        t0 = time.time()
        res = run_model(m, rows, a.k, synonyms=syn, links=links)
        res["secs"] = round(time.time() - t0, 1)
        results.append(res)
        if a.save:   # 모델 하나가 끝날 때마다 — 긴 평가가 중간에 멈춰도 앞 모델 결과는 남는다
            _save(out, a.k, results, Path(a.set).name)
    head = f"{'모델':<58}{'답함':>6}{'정답조':>7}{'번호맞음':>9}{'문장출처':>9}{'근거없음':>9}{'거절':>6}{'중앙(초)':>9}{'넣은토큰':>9}"
    print("\n" + head)
    for res in results:
        s = res["summary"]
        print(f"{res['model']:<58}{s['answered']!s:>6}{s['gold_cited']!s:>7}{s['no_invalid']!s:>9}"
              f"{s['sentence_cited']!s:>9}{s['abstain_ok']!s:>9}{s['declined_ok']!s:>6}{s['llm_median_s']!s:>9}"
              f"{s['prompt_tokens_avg']!s:>9}")
    if a.show:
        for res in results:
            print(f"\n[{res['model']}]")
            for x in res["per"]:
                print(f"- {x['id']} {x['status']}: {x['answer']}")
    if a.save:
        print(f"\n저장: {out}")
    return 0


def _new_path() -> Path:
    """겹치지 않는 결과 파일 이름 — 초까지 넣고, 그래도 있으면 번호를 붙인다.
    (2026-10-03: 분 단위 이름이라 같은 분에 시작한 두 평가가 한 파일을 덮어써 앞 평가의 답 원문을 잃었다)"""
    base = f"kb_answer_eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        out = config.STATE_DIR / (f"{base}.json" if n == 1 else f"{base}-{n}.json")
        try:
            out.touch(exist_ok=False)   # 이름을 먼저 차지한다 — 같은 초에 시작한 다른 평가와도 겹치지 않게
            return out
        except FileExistsError:
            n += 1


def _save(out: Path, k: int, results: List[dict], set_name: str = EVAL_SET.name) -> None:
    out.write_text(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "set": set_name,
                               "k": k, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
