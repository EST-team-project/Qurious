"""작은 RAG — 개념 학습 3.1 「RAG — 찾아서 답하는 언어 모델」 의 예제.

    python rag_mini.py                     # 1~4단계: 표준 라이브러리만 (낱말 검색 · 프롬프트 · 출처 검사)
    python rag_mini.py --ollama            # + 뜻 검색(bge-m3) · 순위 합치기(RRF) · 답 만들기(llama3.1)
    python rag_mini.py --ollama --expand   # + 검색어 넓히기(작은 용어 사전) — 일상어를 법령 용어로

준비(--ollama 일 때만): Ollama 를 켜고 `ollama pull bge-m3` · `ollama pull llama3.1`.
필요한 것: Python 3.10+ (SQLite 3.34+ — trigram 토크나이저). 다른 라이브러리는 쓰지 않는다.

문서는 법령 원문 넷과 설명 문장 셋이다. 법령은 국가법령정보센터 Open API 로 2026-10-01 에 받은 그대로이고
(법령은 저작권 보호 대상이 아니다 — 저작권법 제7조), 설명 문장은 이 예제를 위해 쓴 것이다.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import urllib.request

# ── 1단계: 문서를 조각(청크)으로 — 조문 하나가 한 조각, 머리에 「법령명 제○조(제목)」 ──────────────
CHUNKS = [
    {"title": "증권거래세법 시행령 제5조 제1호", "effective": "2026-01-01", "version": "대통령령 제36001호",
     "text": "증권거래세법 시행령 제5조(탄력세율) 유가증권시장에서 양도되는 주권: 1만분의 5"},
    {"title": "증권거래세법 시행령 제5조 제2호", "effective": "2026-01-01", "version": "대통령령 제36001호",
     "text": "증권거래세법 시행령 제5조(탄력세율) 코넥스시장에서 양도되는 주권: 1만분의 10"},
    {"title": "증권거래세법 시행령 제5조 제3호", "effective": "2026-01-01", "version": "대통령령 제36001호",
     "text": "증권거래세법 시행령 제5조(탄력세율) 코스닥시장에서 양도되는 주권 등: 1만분의 20"},
    {"title": "농어촌특별세법 제5조 제1항 표 제5호", "effective": "2026-05-12", "version": "법률 제21611호",
     "text": "농어촌특별세법 제5조(과세표준과 세율) 자본시장과 금융투자업에 관한 법률에 따른 증권시장으로서 "
             "대통령령으로 정하는 증권시장에서 거래된 증권의 양도가액: 1만분의 15"},
    {"title": "설명 · 수수료", "effective": "", "version": "예제 문장",
     "text": "주식을 살 때와 팔 때 모두 증권사 위탁수수료가 붙습니다."},
    {"title": "설명 · 배당", "effective": "", "version": "예제 문장",
     "text": "배당기준일에 주식을 가진 주주가 배당을 받습니다."},
    {"title": "설명 · 옵션 만기", "effective": "", "version": "예제 문장",
     "text": "코스피200 옵션의 최종거래일은 매월 둘째 목요일입니다."},
]
QUESTION = "2026년 현재 코스피 시장에서 주식을 팔 때 내는 세금은 몇 %인가요?"

# 작은 용어 사전 — 사람이 쓰는 말 → 법령이 쓰는 말. Qurious 용어사전(목표 기능 ①-1)이 이 역할을 크게 맡는다.
SYNONYMS = {
    "코스피": ["유가증권시장"],
    "세금": ["증권거래세", "농어촌특별세", "세율"],
    "팔 때": ["양도"],
}


def expand(question: str) -> str:
    """검색에만 쓰는 질문 — 사전에 있는 말을 만나면 법령 용어를 덧붙인다(LLM 에 보내는 질문은 그대로)."""
    extra = [w for key, words in SYNONYMS.items() if key in question for w in words]
    return question + (" " + " ".join(extra) if extra else "")


# ── 2단계: 색인 — SQLite 전문 검색(FTS5 · trigram)에 넣는다 ─────────────────────────────────
def build_index() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    # trigram: 글자 세 개씩 잘라 색인한다 → 한국어 조사(「시장에서」 의 「에서」)가 붙어도 부분이 맞으면 찾는다
    db.execute("CREATE VIRTUAL TABLE kb USING fts5(text, tokenize='trigram')")
    db.executemany("INSERT INTO kb(rowid, text) VALUES (?, ?)", [(i, c["text"]) for i, c in enumerate(CHUNKS)])
    return db


# ── 3단계: 찾기 — 낱말 검색(BM25 점수) ─────────────────────────────────────────────────────
def keyword_search(db: sqlite3.Connection, question: str, k: int = 5) -> list[int]:
    words = [w for w in re.findall(r"[0-9A-Za-z가-힣]+", question) if len(w) >= 3]   # trigram 은 세 글자 이상만 찾는다
    if not words:
        return []
    query = " OR ".join(f'"{w}"' for w in words)
    rows = db.execute("SELECT rowid, bm25(kb) FROM kb WHERE kb MATCH ? ORDER BY bm25(kb) LIMIT ?", (query, k))
    return [rowid for rowid, _ in rows]          # bm25() 는 작을수록(음수 쪽) 더 맞는 문서다


# ── 4단계: 프롬프트 — 근거에 번호를 달고, 근거 밖의 말을 하지 말라고 적는다 ───────────────────────
def build_prompt(question: str, ids: list[int]) -> str:
    sources = "\n".join(
        f"[출처 {n}] {CHUNKS[i]['title']} ({CHUNKS[i]['version']}, 시행 {CHUNKS[i]['effective'] or '-'})\n{CHUNKS[i]['text']}"
        for n, i in enumerate(ids, start=1))
    return ("아래 출처만 근거로 한국어로 답하세요. 문장마다 [출처 n] 을 다세요.\n"
            "출처에 없는 내용은 말하지 말고, 근거가 없으면 「근거를 찾지 못했습니다」 라고 답하세요.\n\n"
            f"{sources}\n\n질문: {question}\n답:")


def check_citations(answer: str, n_sources: int) -> list[int]:
    """답 속 [출처 n] 이 실제로 넘긴 출처 번호 안에 있나 — 없는 번호를 돌려준다(비면 통과)."""
    cited = {int(n) for n in re.findall(r"\[출처\s*(\d+)\]", answer)}
    return sorted(n for n in cited if not 1 <= n <= n_sources)


def unsupported_numbers(answer: str, ids: list[int]) -> list[str]:
    """답에 나온 숫자 가운데 넘긴 출처 어디에도 글자 그대로 없는 것 — 「근거 밖 숫자」 를 거칠게 잡는다.

    번호 검사는 「[출처 2] 가 있는 번호인가」 만 본다. 문장이 그 출처와 맞는지는 못 본다.
    숫자는 금융 답에서 가장 위험한 곳이라, 근거에 없는 숫자가 나오면 사람이 보게 표시한다.
    """
    haystack = " ".join(f"{CHUNKS[i]['title']} {CHUNKS[i]['version']} {CHUNKS[i]['effective']} {CHUNKS[i]['text']}" for i in ids)
    found = dict.fromkeys(re.findall(r"\d+(?:\.\d+)?%?", answer))
    return [n for n in found if n not in haystack and n.rstrip("%") not in haystack]


# ── (--ollama) 뜻 검색 · 순위 합치기 · 답 만들기 ──────────────────────────────────────────
def ollama(path: str, body: dict) -> dict:
    req = urllib.request.Request(f"http://localhost:11434{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=600))


def dense_search(question: str, k: int = 5) -> list[int]:
    vecs = ollama("/api/embed", {"model": "bge-m3", "input": [question] + [c["text"] for c in CHUNKS]})["embeddings"]
    q, docs = vecs[0], vecs[1:]
    scores = [sum(a * b for a, b in zip(q, d)) for d in docs]      # 길이 1 벡터라 내적 = 코사인 유사도
    return sorted(range(len(CHUNKS)), key=lambda i: -scores[i])[:k]


def rrf(rankings: list[list[int]], k: int = 60) -> list[int]:
    """Reciprocal Rank Fusion — 문서마다 Σ 1/(k + 순위). 점수의 크기가 다른 검색 둘을 순위만으로 합친다."""
    score: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking, start=1):
            score[doc] = score.get(doc, 0.0) + 1.0 / (k + rank)
    return sorted(score, key=lambda d: -score[d])


def main() -> None:
    db = build_index()
    search_q = expand(QUESTION) if "--expand" in sys.argv else QUESTION
    kw = keyword_search(db, search_q)
    print("질문:", QUESTION)
    if search_q != QUESTION:
        print("검색어:", search_q)
    print("\n[낱말 검색] 순위:", [CHUNKS[i]["title"] for i in kw])
    ids = kw[:4]
    if "--ollama" in sys.argv:
        dense = dense_search(search_q)
        print("[뜻 검색]   순위:", [CHUNKS[i]["title"] for i in dense])
        ids = rrf([kw, dense])[:4]
        print("[RRF 합침]  상위 4:", [CHUNKS[i]["title"] for i in ids])
    prompt = build_prompt(QUESTION, ids)
    print("\n── 프롬프트 ──\n" + prompt)
    if "--ollama" in sys.argv:
        answer = ollama("/api/generate", {"model": "llama3.1", "prompt": prompt, "stream": False,
                                          "options": {"temperature": 0, "seed": 42, "num_predict": 200}})["response"].strip()
        print("\n── 답(llama3.1) ──\n" + answer)
        bad = check_citations(answer, len(ids))
        print("\n출처 번호 검사:", "통과" if not bad else f"없는 번호 {bad}")
        odd = unsupported_numbers(answer, ids)
        print("근거 밖 숫자 :", "없음" if not odd else ", ".join(odd))


if __name__ == "__main__":
    main()
