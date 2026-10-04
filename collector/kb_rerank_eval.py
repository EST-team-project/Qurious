"""재순위 실측 — 검색 상위 N 을 교차 인코더(bge-reranker-v2-m3)로 다시 매겨 품질 · 이 PC CPU 속도를 잰다 (목표 기능 ① W5 · 설계서 5.3.3).

    python -m collector.kb_rerank_eval                      평가셋 v1(50) · 후보 20 · 재순위 전후 Recall@5 · MRR@10 · 질문당 초
    python -m collector.kb_rerank_eval --top 10 30          후보 수를 바꿔 가며
    python -m collector.kb_rerank_eval --ids QN --save      표본 밖 질문만 · 결과 JSON 저장(이름은 초까지)

왜 재는가
---------
설계서 5.3.3 은 같은 낱말로 다른 편의 조가 섞이는 것을 셋째 단계 「재순위」 로 막는다고 적었다. 재순위는 질문과
조문을 한 번에 읽는 교차 인코더라 벡터 검색보다 정확하지만 후보마다 모델을 한 번씩 돌려 느리다. 그래서 붙이기
전에 이 PC(CPU)에서 질문당 몇 초인지, 품질이 얼마나 오르는지 먼저 잰다(2026-10-04 세션 범위 「이 PC CPU 속도부터」).

무엇이 필요한가
---------------
호스트 파이썬의 ``sentence-transformers`` · ``torch``(앱 이미지에는 없다 — 앱에 붙일지는 이 실측을 본 뒤 정한다).
모델은 Hugging Face ``BAAI/bge-reranker-v2-m3``(Apache-2.0 · 약 2.27GB · 캐시 ``~/.cache/huggingface``).
검색은 앱과 같은 길(``kb_search.search`` · 낱말 + bge-m3 벡터 · 동의어 켬)을 쓴다 — Qdrant · Ollama 가 켜져 있어야 한다.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from collector import config, kb_eval, kb_index
from collector.console import utf8_stdio

sys.path.insert(0, str(config.ROOT))
from app.services import kb_answer, kb_search  # noqa: E402

MODEL = "BAAI/bge-reranker-v2-m3"
#: 교차 인코더 한 쌍의 글자 상한(토큰) — 조문 청크는 대개 이 안이다(넘으면 뒤가 잘린다)
MAX_LENGTH = 512


def load_model(threads: int):
    try:
        import torch
        from sentence_transformers import CrossEncoder
    except ImportError as e:      # 막다른 길로 끝내지 않게 할 일을 함께 찍는다
        raise SystemExit(f"재순위 실측에는 호스트 파이썬의 sentence-transformers · torch 가 필요하다({e}) — "
                         "pip install sentence-transformers (앱 이미지에는 넣지 않는다)") from None
    if threads:
        torch.set_num_threads(threads)
    t0 = time.perf_counter()
    model = CrossEncoder(MODEL, max_length=MAX_LENGTH, device="cpu")
    return model, time.perf_counter() - t0, torch.get_num_threads(), torch.__version__


def rerank(model, q: str, hits: List[dict]) -> List[dict]:
    """후보를 (질문, 조문 본문) 쌍으로 점수 매겨 높은 순 — 제목 사슬 머리는 빼고 본문만(답 카드와 같은 글)."""
    pairs = [(q, kb_answer.citation_excerpt(h["text"], 2000)) for h in hits]
    scores = model.predict(pairs, batch_size=16, show_progress_bar=False)
    order = sorted(range(len(hits)), key=lambda i: -float(scores[i]))
    return [hits[i] for i in order]


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.kb_rerank_eval", description="재순위 실측 — 품질 · CPU 속도")
    p.add_argument("--set", default=str(config.ROOT / "docs" / "시험" / "근거검색-평가셋_v1.tsv"))
    p.add_argument("--ids", default="", help="이 머리로 시작하는 id 만(예: QN)")
    p.add_argument("--top", type=int, nargs="+", default=[20], help="재순위에 넣을 검색 후보 수")
    p.add_argument("--threads", type=int, default=0, help="torch CPU 스레드(0 = 기본)")
    p.add_argument("--save", action="store_true")
    a = p.parse_args(argv)

    rows = kb_eval.load(Path(a.set))
    if a.ids:
        rows = [r for r in rows if r["id"].startswith(a.ids)]
    model, load_s, threads, torch_v = load_model(a.threads)
    print(f"― 재순위 실측 · {Path(a.set).name} · 질문 {len(rows)} · {MODEL} · 불러오기 {load_s:.1f}초 · "
          f"torch {torch_v} · CPU 스레드 {threads}/{os.cpu_count()} ―", flush=True)
    backend = kb_search.DenseBackend(ollama_url=kb_index.OLLAMA_URL, qdrant_url=kb_index.QDRANT_URL)
    model.predict([("예열", "예열")], show_progress_bar=False)   # 첫 호출의 준비 시간을 재기에서 뺀다

    results = []
    for top in a.top:
        per = []
        for r in rows:
            res = kb_search.search(r["질문"], top, backend=backend)
            hits = res["hits"]
            t0 = time.perf_counter()
            ranked = rerank(model, r["질문"], hits)
            secs = time.perf_counter() - t0
            per.append({"id": r["id"], "before": kb_eval.first_hit(hits, r["gold"]),
                        "after": kb_eval.first_hit(ranked, r["gold"]), "secs": round(secs, 3), "n": len(hits),
                        "top3_after": [f"{h['doc_id']}:{h['article']}" for h in ranked[:3]]})

        def score(key: str) -> dict:
            return {"recall5": round(sum(1 for x in per if x[key] and x[key] <= 5) / len(per), 3),
                    "mrr10": round(sum(1 / x[key] for x in per if x[key] and x[key] <= 10) / len(per), 3)}

        secs = [x["secs"] for x in per]
        out = {"top": top, "before": score("before"), "after": score("after"),
               "secs_median": round(statistics.median(secs), 2),
               "secs_p90": round(sorted(secs)[max(0, int(len(secs) * 0.9) - 1)], 2), "per": per}
        results.append(out)
        print(f"  후보 {top:>2}  전 R@5 {out['before']['recall5']:.3f} · MRR@10 {out['before']['mrr10']:.3f}  →  "
              f"후 R@5 {out['after']['recall5']:.3f} · MRR@10 {out['after']['mrr10']:.3f}  · 질문당 중앙 "
              f"{out['secs_median']}초 · 90% {out['secs_p90']}초", flush=True)
        for x in per:
            if x["before"] != x["after"] and ((x["before"] or 99) <= 5) != ((x["after"] or 99) <= 5):
                # flush — 다음 후보 수를 재는 동안 멈춰도 이 줄은 남게(2026-10-04 · 후보 20 을 멈추며 잃었다)
                print(f"      {x['id']}: {x['before'] or '-'}위 → {x['after'] or '-'}위 · 위 3 {', '.join(x['top3_after'])}",
                      flush=True)
    if a.save:
        path = config.STATE_DIR / f"kb_rerank_eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        path.write_text(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "model": MODEL,
                                    "load_s": round(load_s, 1), "threads": threads, "cpu": os.cpu_count(),
                                    "torch": torch_v, "set": Path(a.set).name, "results": results},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  저장 {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
