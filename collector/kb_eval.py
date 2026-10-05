"""근거 검색 평가 — 평가셋으로 Recall@5 · MRR@10 을 잰다 (목표 기능 ① W5 · 설계서 5.3.5).

    python -m collector.kb_eval                                   낱말 · 벡터 · 섞어 찾기 × 모델 둘 × 가중 켬/끔
    python -m collector.kb_eval --modes hybrid --models bge-m3    한 가지만
    python -m collector.kb_eval --save                            결과를 data/collector/state/kb_eval-<날짜-시각초>.json 에도
    python -m collector.kb_eval --misses                          놓친 질문마다 상위 3 을 보인다
    python -m collector.kb_eval --synonyms both                   법령 말 넓히기(kb_synonyms) 끔 · 켬 둘 다
    python -m collector.kb_eval --set docs/시험/근거검색-평가셋_v1.tsv --ids N    새로 더한 질문(N…)만

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
- 「답 근거」 Recall — 답 모델이 실제로 받는 목록(상위 5 + 그 위임 조 · ``kb_links.expand``)에 정답 조가 있는
  비율. 위임 조가 정답(시행령 · 감독규정)인 질문에서 Recall@5 와 차이가 난다. 끼운 위임 조가 6위 이하를 밀어내도
  답 모델은 상위 5 의 근거를 모두 받으므로 「위임 조를 끼운 목록의 앞 5개」 로 세지 않는다.

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
from app.services import kb_links, kb_search, kb_text  # noqa: E402

EVAL_SET = config.ROOT / "docs" / "시험" / "근거검색-평가셋_v0.tsv"
DOMAIN_NAMES = {"tax": "세금", "company": "회사", "regulation": "투자 규제"}


def load(path: Path = EVAL_SET) -> List[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for r in rows:
        # 마지막 콜론에서 나눈다 — 조 이름(제8조)에는 콜론이 없지만 문서 ID 에는 있을 수 있다(섹터 법령 실험 `sec:은행법` ·
        # 2026-10-05 첫 콜론에서 나눠 정답 18개가 모두 「놓침」 으로 잘못 셌다)
        r["gold"] = [tuple(g.strip().rsplit(":", 1)) for g in r["정답"].split(";") if g.strip()]
        if not r["gold"] or any(len(g) != 2 for g in r["gold"]):
            raise SystemExit(f"정답 칸 모양이 틀렸다 — {r['id']}: {r['정답']!r} (문서:조;문서:조)")
    return rows


def first_hit(hits: Sequence[dict], gold: Sequence[tuple]) -> Optional[int]:
    """정답 조가 처음 나온 순위(1부터) — 없으면 None. 순위는 목록 안 자리다(위임 조를 끼운 목록도 같은 셈)."""
    want = {(d, a) for d, a in gold}
    for i, h in enumerate(hits, start=1):
        if (h["doc_id"], h["article"]) in want:
            return i
    return None


def evaluate(rows: List[dict], mode: str, model: str, route: bool, backend: kb_search.DenseBackend,
             k: int = 10, synonyms: bool = True) -> dict:
    per = []
    t0 = time.time()
    for r in rows:
        res = kb_search.search(r["질문"], k, mode=mode, model=model, route=route, synonyms=synonyms,
                               backend=backend)
        rank = first_hit(res["hits"], r["gold"])
        # 답 모델이 받는 근거 = 상위 5 + 그 위임 조 — 그 안에 있으면 1(자리와 상관없이 「받았다」)
        linked = 1 if first_hit(kb_links.expand(res["hits"][:5]), r["gold"]) else None
        per.append({"id": r["id"], "rank": rank, "linked_rank": linked, "domain": r["의도_묶음"],
                    "mix": bool(r["섞임_낱말"]), "routed": res["route"]["domains"],
                    "synonyms": [s["from"] for s in res.get("synonyms", [])],
                    "dense_error": res["retrieval"].get("dense_error"),
                    "top3": [f"{h['doc_id']}:{h['article']}" for h in res["hits"][:3]]})
    secs = time.time() - t0

    def score(items: List[dict], key: str = "rank") -> dict:
        if not items:
            return {"n": 0, "recall5": None, "mrr10": None}
        return {"n": len(items),
                "recall5": round(sum(1 for p in items if p[key] and p[key] <= 5) / len(items), 3),
                "mrr10": round(sum(1 / p[key] for p in items if p[key] and p[key] <= 10) / len(items), 3)}

    return {"mode": mode, "model": model if mode != "lexical" else None, "route": route, "synonyms": synonyms,
            "all": score(per), "linked": score(per, "linked_rank"),
            "domains": {d: score([p for p in per if p["domain"] == d]) for d in DOMAIN_NAMES},
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
    p.add_argument("--synonyms", choices=("both", "on", "off"), default="on",
                   help="질문 말 → 법령 말 넓히기(kb_synonyms) — 기본 켬(앱과 같음)")
    p.add_argument("--set", default=str(EVAL_SET), help="평가셋 TSV")
    p.add_argument("--ids", default="", help="이 머리로 시작하는 id 만(예: N — 새로 더한 질문)")
    p.add_argument("--save", action="store_true", help="결과 JSON 을 data/collector/state 에")
    p.add_argument("--misses", action="store_true", help="놓친 질문의 상위 3")
    a = p.parse_args(argv)

    rows = load(Path(a.set))
    if a.ids:
        rows = [r for r in rows if r["id"].startswith(a.ids)]
    backend = kb_search.DenseBackend(ollama_url=kb_index.OLLAMA_URL, qdrant_url=kb_index.QDRANT_URL)
    cov = vector_coverage()
    print(f"― 근거 검색 평가 · {Path(a.set).name} · 질문 {len(rows)} · 벡터 "
          + " · ".join(f"{m} {c}" for m, c in cov.items()) + " ―")
    routes = {"both": (False, True), "on": (True,), "off": (False,)}[a.route]
    syns = {"both": (False, True), "on": (True,), "off": (False,)}[a.synonyms]
    results = []
    for mode in [m.strip() for m in a.modes.split(",") if m.strip()]:
        models = [None] if mode == "lexical" else [m.strip() for m in a.models.split(",") if m.strip()]
        for model in models:
            for syn in syns:
                for route in routes:
                    r = evaluate(rows, mode, model or kb_text.DEFAULT_EMBED_MODEL, route, backend, synonyms=syn)
                    results.append(r)
                    dom = " · ".join(f"{DOMAIN_NAMES[d]} {v['recall5']:.2f}" for d, v in r["domains"].items() if v["n"])
                    mix = f"{r['mix']['recall5']:.2f}" if r["mix"]["n"] else "-"
                    print(f"  {mode:<7} {(model or '-'):<17} 동의어 {'켬' if syn else '끔'} 가중 {'켬' if route else '끔'}  "
                          f"R@5 {r['all']['recall5']:.3f} · MRR@10 {r['all']['mrr10']:.3f} · 답 근거 R "
                          f"{r['linked']['recall5']:.3f} · 섞임 R@5 {mix} · [{dom}] · 분류 맞음 {r['route_accuracy']:.2f} · "
                          f"{r['seconds']}초" + (f" · ⚠ 벡터 오류 {r['dense_errors']}" if r["dense_errors"] else ""))
                    if a.misses:
                        for q in r["per"]:
                            if not q["rank"] or q["rank"] > 5:
                                print(f"      놓침 {q['id']} (순위 {q['rank'] or '-'} · 답 근거 {'있음' if q['linked_rank'] else '없음'}) "
                                      f"상위 3: {', '.join(q['top3'])}")
    if a.save:
        # 이름은 초까지 — 같은 분에 시작한 평가가 앞 결과를 덮어쓰지 않게(DF-58 과 같은 결함 · 근거답 평가는 S85 에 고침)
        out = config.STATE_DIR / f"kb_eval-{datetime.now(kb_law.KST).strftime('%Y%m%d-%H%M%S')}.json"
        out.write_text(json.dumps({"at": kb_law.now_kst(), "set": Path(a.set).name, "questions": len(rows),
                                   "vectors": cov, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  저장 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
