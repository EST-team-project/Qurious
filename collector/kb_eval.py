"""근거 검색 평가 — 평가셋으로 Recall@5 · MRR@10 을 잰다 (목표 기능 ① W5 · 설계서 5.3.5).

    python -m collector.kb_eval                                   낱말 · 벡터 · 섞어 찾기 × 모델 둘 × 가중 켬/끔
    python -m collector.kb_eval --modes hybrid --models bge-m3    한 가지만
    python -m collector.kb_eval --save                            결과를 data/collector/state/kb_eval-<날짜>.json 에도
    python -m collector.kb_eval --misses                          놓친 질문마다 상위 3 을 보인다

평가셋 — ``docs/시험/근거검색-평가셋_v0.tsv`` (질문 38 · 2026-10-03)
--------------------------------------------------------------------
정답은 청크가 아니라 **「문서:조」** 로 적는다(정답이 여럿이면 하나라도 맞으면 맞힌 것). 청크 머리 · 순번을 바꾸는
실험에서 청크 단위 정답은 판정을 흔든다 — 제목 사슬 머리를 뺀 판에서는 사람 판정의 일치도가 무너졌다는 보고가 있다
(arXiv 2608.00824 · 「측정 함정」). 조는 쪼개기 규칙과 상관없이 같다.

지표
----
- Recall@5 — 상위 5 안에 정답 조가 하나라도 있는 질문의 비율
- MRR@10  — 첫 정답 조 순위의 역수 평균(10 밖이면 0)
- 묶음별(세금 · 회사 · 투자 규제)과 「섞임 낱말」 이 있는 질문만 따로 — 같은 낱말이 다른 편에 있는 질문
  (보험편 「고지」 · 상행위편 「배당」 · 선하증권의 「증권」)에서 가중 · 머리 경로가 실제로 듣는지 본다.

벡터 쪽은 이 PC 의 Qdrant(16333) · Ollama(11434) 를 쓴다(색인과 같은 주소 · ``kb_index``). 벡터가 다 들어가기 전에
돌리면 벡터 쪽 점수는 넣은 만큼만 의미가 있다 — 첫 줄에 모델별 「넣은 벡터 / 청크」 를 찍는다.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from collector import config
from collector.console import utf8_stdio
from collector import kb_index, kb_law

sys.path.insert(0, str(config.ROOT))
from app.services import kb_search, kb_text  # noqa: E402

EVAL_SET = config.ROOT / "docs" / "시험" / "근거검색-평가셋_v0.tsv"
DOMAIN_NAMES = {"tax": "세금", "company": "회사", "regulation": "투자 규제"}


def load(path: Path = EVAL_SET) -> List[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for r in rows:
        r["gold"] = [tuple(g.split(":", 1)) for g in r["정답"].split(";") if g.strip()]
        if not r["gold"] or any(len(g) != 2 for g in r["gold"]):
            raise SystemExit(f"정답 칸 모양이 틀렸다 — {r['id']}: {r['정답']!r} (문서:조;문서:조)")
    return rows


def first_hit(hits: Sequence[dict], gold: Sequence[tuple]) -> Optional[int]:
    """정답 조가 처음 나온 순위(1부터) — 없으면 None."""
    want = {(d, a) for d, a in gold}
    for h in hits:
        if (h["doc_id"], h["article"]) in want:
            return h["rank"]
    return None


def evaluate(rows: List[dict], mode: str, model: str, route: bool, backend: kb_search.DenseBackend,
             k: int = 10) -> dict:
    per = []
    t0 = time.time()
    for r in rows:
        res = kb_search.search(r["질문"], k, mode=mode, model=model, route=route, backend=backend)
        rank = first_hit(res["hits"], r["gold"])
        per.append({"id": r["id"], "rank": rank, "domain": r["의도_묶음"], "mix": bool(r["섞임_낱말"]),
                    "routed": res["route"]["domains"], "dense_error": res["retrieval"].get("dense_error"),
                    "top3": [f"{h['doc_id']}:{h['article']}" for h in res["hits"][:3]]})
    secs = time.time() - t0

    def score(items: List[dict]) -> dict:
        if not items:
            return {"n": 0, "recall5": None, "mrr10": None}
        return {"n": len(items),
                "recall5": round(sum(1 for p in items if p["rank"] and p["rank"] <= 5) / len(items), 3),
                "mrr10": round(sum(1 / p["rank"] for p in items if p["rank"] and p["rank"] <= 10) / len(items), 3)}

    return {"mode": mode, "model": model if mode != "lexical" else None, "route": route,
            "all": score(per), "domains": {d: score([p for p in per if p["domain"] == d]) for d in DOMAIN_NAMES},
            "mix": score([p for p in per if p["mix"]]),
            "route_accuracy": round(sum(1 for p in per if p["domain"] in p["routed"]) / len(per), 3),
            "seconds": round(secs, 1), "dense_errors": sum(1 for p in per if p["dense_error"]), "per": per}


def vector_coverage() -> Dict[str, str]:
    conn = kb_law.connect()
    n = conn.execute("SELECT COUNT(*) FROM kb_chunk").fetchone()[0]
    out = {}
    for name in kb_text.EMBED_MODELS:
        v = conn.execute("SELECT COUNT(*) FROM kb_vector v JOIN kb_chunk c ON c.chunk_id=v.chunk_id"
                         " AND c.text_sha256=v.text_sha256 WHERE v.model=?", (name,)).fetchone()[0]
        out[name] = f"{v:,}/{n:,}"
    return out


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.kb_eval", description="근거 검색 평가 — Recall@5 · MRR@10")
    p.add_argument("--modes", default="lexical,dense,hybrid")
    p.add_argument("--models", default=",".join(kb_text.EMBED_MODELS))
    p.add_argument("--route", choices=("both", "on", "off"), default="both")
    p.add_argument("--set", default=str(EVAL_SET), help="평가셋 TSV")
    p.add_argument("--save", action="store_true", help="결과 JSON 을 data/collector/state 에")
    p.add_argument("--misses", action="store_true", help="놓친 질문의 상위 3")
    a = p.parse_args(argv)

    rows = load(Path(a.set))
    backend = kb_search.DenseBackend(ollama_url=kb_index.OLLAMA_URL, qdrant_url=kb_index.QDRANT_URL)
    cov = vector_coverage()
    print(f"― 근거 검색 평가 · 질문 {len(rows)} · 벡터 " + " · ".join(f"{m} {c}" for m, c in cov.items()) + " ―")
    routes = {"both": (False, True), "on": (True,), "off": (False,)}[a.route]
    results = []
    for mode in [m.strip() for m in a.modes.split(",") if m.strip()]:
        models = [None] if mode == "lexical" else [m.strip() for m in a.models.split(",") if m.strip()]
        for model in models:
            for route in routes:
                r = evaluate(rows, mode, model or kb_text.DEFAULT_EMBED_MODEL, route, backend)
                results.append(r)
                dom = " · ".join(f"{DOMAIN_NAMES[d]} {v['recall5']:.2f}" for d, v in r["domains"].items() if v["n"])
                print(f"  {mode:<7} {(model or '-'):<17} 가중 {'켬' if route else '끔'}  R@5 {r['all']['recall5']:.3f} · "
                      f"MRR@10 {r['all']['mrr10']:.3f} · 섞임 R@5 {r['mix']['recall5']:.2f} · [{dom}] · "
                      f"분류 맞음 {r['route_accuracy']:.2f} · {r['seconds']}초" + (f" · ⚠ 벡터 오류 {r['dense_errors']}" if r["dense_errors"] else ""))
                if a.misses:
                    for q in r["per"]:
                        if not q["rank"] or q["rank"] > 5:
                            print(f"      놓침 {q['id']} (순위 {q['rank'] or '-'}) 상위 3: {', '.join(q['top3'])}")
    if a.save:
        out = config.STATE_DIR / f"kb_eval-{datetime.now(kb_law.KST).strftime('%Y%m%d-%H%M')}.json"
        out.write_text(json.dumps({"at": kb_law.now_kst(), "set": Path(a.set).name, "questions": len(rows),
                                   "vectors": cov, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  저장 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
