"""섹터 질문 분류 시험 (TC-SQ) — 섹터 법령은 섹터 질문일 때만 근거 후보 (목표 기능 ① W8 · 설계서 5.3.7).

무엇을 지키나 —
1. **분류 낱말 맞추기** — 한글은 띄어쓰기 · 가운뎃점을 뺀 글에서, 로마자 낱말은 앞뒤가 로마자 · 숫자가 아닐 때만 맞는다
   (「ISA 계좌」 · 「ISA계좌」 는 맞고 「VISA」 는 아니다). 「알려 주세요」 · 「펀드 청약 철회」 같은 기존 질문 말에는 안 걸린다.
2. **낱말 표 만들기** — 정식 이름 · 법령 API 약칭 · 섹터 표 업 이름 세 출처 · 두 섹터에 있는 법은 두 섹터로 · 근거 문서에
   이미 있는 법(자본시장법 · 상법)은 건너뜀 · 한 글자 낱말은 버림.
3. **섹터 문서는 분류가 고를 때만 후보** — 낱말 · 벡터 모두. `sector=False` 는 분류 전 길이고, `docs` 로 콕 집은 섹터 문서는 든다.
   섹터 문서는 판이 없어도 `missing` 에 싣지 않는다(고르지 않은 문서다).
4. **낱말 색인을 따로** — 섹터 조각은 `kb_sector_fts` 에만 있어야 기존 질문의 bm25 가 그대로다. 같은 색인에 넣으면
   섹터 문서를 후보에서 빼도 점수가 바뀐다(2026-10-06 실측 — 기존 검색 50 R@5 0.940 → 0.900).
5. **기존 평가 질문에 헛걸림 0** — 섹터 표의 낱말이 근거 검색 50 · 근거답 20 질문에 걸리지 않는다.

네트워크 · 실제 kb.sqlite3 를 쓰지 않는다(5 는 저장소의 평가셋 · 섹터 표 파일을 읽는다).
"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import kb as kb_routes
from app.services import kb_search, kb_text
from collector import kb_law, kb_sector, kb_sector_link
from collector.kb_law import Article, DocSpec

ROOT = Path(__file__).resolve().parents[1]


def _v(no: str, prom: str, eff: str, law_type: str = "법률") -> kb_text.Version:
    return kb_text.Version(source_id=f"s{no}", promulgation_no=no, promulgated_at=prom, effective_at=eff,
                           status="", law_type=law_type)


def _store(conn, spec: DocSpec, v: kb_text.Version, arts: list[Article]) -> None:
    chunks = [c for a in arts for c in kb_law.chunk_article(spec.title, a)]
    sha = kb_text.text_sha256("\n\n".join(f"{a.label}\n{a.body}" for a in arts))
    kb_law.store_version(conn, spec, v, spec.title, "", chunks, len(arts), sha, "2026-10-05", "", "")


def _rows(words):
    """sector_route 가 읽는 행 모양 — (보이는 꼴, 문서, 섹터 코드, 섹터)."""
    return [{"word": kb_search.norm_word(w), "shown": w, "doc_id": d, "sector_code": c, "sector": n, "source": "업 이름"}
            for w, d, c, n in words]


COMMERCIAL = kb_law.DOC_BY_ID["commercial_act"]
FCPA = kb_law.DOC_BY_ID["fcpa_act"]
BANK = DocSpec("sec:은행법", "은행법", "law", 1)
HOUSING = DocSpec("sec:주택법", "주택법", "law", 1)
FUND_WITHDRAW = ("일반금융소비자는 투자성 상품에 관한 계약의 청약을 한 후 7일 이내에 청약을 철회할 수 있다. "
                 "청약 철회 기간은 계약서류를 받은 날부터 계산한다.")
# 주택법의 조합 가입 철회 — 2026-10-05 실험에서 펀드 청약 철회 질문의 1위를 빼앗은 조(낱말이 많이 겹친다)
HOUSING_WITHDRAW = ("주택조합의 조합원으로 가입하려는 자는 가입비등을 예치하고 가입 계약을 체결한 날부터 30일 이내에 "
                    "주택조합 가입에 관한 청약을 철회할 수 있다. 청약 철회를 서면으로 한다.")


def _base(conn) -> None:
    _store(conn, COMMERCIAL, _v("21044", "2025-03-04", "2026-09-10"), [
        Article("제464조의2", "이익배당의 지급시기", "제3편 회사",
                "회사는 이익배당을 주주총회나 이사회의 결의가 있은 날부터 1개월 내에 하여야 한다."),
    ])
    _store(conn, FCPA, _v("21065", "2025-12-30", "2026-01-02"), [
        Article("제46조", "청약의 철회", "제4장 금융소비자 보호", FUND_WITHDRAW),
        Article("제19조", "설명의무", "제4장 금융상품판매업자등의 영업행위 준수사항",
                "금융상품판매업자등은 일반금융소비자에게 계약 체결을 권유하는 경우 금융상품의 위험 등 중요한 사항을 "
                "설명하여야 한다."),
    ])


def _sector(conn) -> None:
    """섹터 문서 둘을 넣고 조각 색인을 섹터 색인으로 옮긴 뒤 분류 낱말 표를 채운다(kb_sector_link.build 와 같은 길)."""
    conn.executescript(kb_sector_link.WORD_SCHEMA)
    _store(conn, BANK, _v("20001", "2025-01-01", "2025-07-01"), [
        Article("제8조", "은행업의 인가", "제2장 은행업의 인가 등",
                "은행업을 경영하려는 자는 금융위원회의 인가를 받아야 한다. 은행업 인가를 받으려는 자는 자본금이 "
                "1천억원 이상일 것. 다만, 지방은행의 자본금은 250억원 이상으로 할 수 있다."),
    ])
    _store(conn, HOUSING, _v("20002", "2026-09-01", "2026-10-01"), [
        Article("제11조의6", "조합 가입 철회 및 가입비등의 반환", "제2장 주택의 건설 등", HOUSING_WITHDRAW),
    ])
    for spec in (BANK, HOUSING):
        rids = [r[0] for r in conn.execute("SELECT rid FROM kb_chunk WHERE doc_id=?", (spec.doc_id,))]
        kb_sector_link._move_to_sector_fts(conn, rids)
    conn.executemany("INSERT INTO kb_sector_word(word, shown, doc_id, sector_code, sector, source) VALUES (?,?,?,?,?,?)",
                     [("은행업", "은행업", "sec:은행법", "Fi", "금융", "업 이름"),
                      ("은행법", "은행법", "sec:은행법", "Fi", "금융", "정식 이름"),
                      ("주택조합", "주택조합", "sec:주택법", "Re", "부동산", "업 이름")])


@pytest.fixture()
def kb(tmp_path) -> Path:
    path = tmp_path / "kb.sqlite3"
    conn = kb_law.connect(path)
    _base(conn)
    _sector(conn)
    conn.close()
    return path


class FakeDense(kb_search.DenseBackend):
    """Qdrant · Ollama 대신 — 정해 둔 청크 ID 순서를 돌려주고, 물은 판 키를 적어 둔다."""

    def __init__(self, ids: list[str] | None = None):
        super().__init__(ollama_url="http://fake-ollama", qdrant_url="http://fake-qdrant")
        self.ids, self.calls = ids or [], []

    def embed(self, model, q):
        return [0.0] * model.dim

    def query(self, model, vec, keys, n):
        self.calls.append(sorted(keys))
        return [c for c in self.ids]


def _cid(path: Path, doc: str) -> str:
    c = sqlite3.connect(path)
    try:
        return c.execute("SELECT chunk_id FROM kb_chunk WHERE doc_id=?", (doc,)).fetchone()[0]
    finally:
        c.close()


# ==================================================
# 1. 분류 낱말 맞추기
# ==================================================
def test_sector_route_matching_rules():
    """TC-SQ-01 · 한글은 띄어쓰기를 뺀 글에서 · 로마자 낱말은 앞뒤가 로마자 · 숫자가 아닐 때만 · 겹친 문서 · 낱말은 한 번."""
    rows = _rows([("ISA", "sec:조세특례제한법", "IT", "정보기술"), ("반도체 특별법", "sec:반도체", "IT", "정보기술"),
                  ("은행업", "sec:은행법", "Fi", "금융"), ("은행", "sec:은행법", "Fi", "금융"),
                  ("대형마트", "sec:유통산업발전법", "CD", "임의소비재"), ("대형마트", "sec:유통산업발전법", "CS", "필수소비재")])
    assert kb_search.sector_route("ISA 계좌의 비과세 한도는?", rows)["docs"] == ["sec:조세특례제한법"]
    assert kb_search.sector_route("isa계좌 한도", rows)["words"] == ["ISA"]
    assert kb_search.sector_route("VISA 카드 수수료", rows)["docs"] == []          # 로마자 낱말 안의 isa 는 아니다
    assert kb_search.sector_route("반도체특별법 시행일", rows)["words"] == ["반도체 특별법"]  # 띄어쓰기 무시
    r = kb_search.sector_route("은행업 인가 자본금", rows)
    assert r["docs"] == ["sec:은행법"] and r["words"] == ["은행업", "은행"] and r["sectors"] == [{"code": "Fi", "name": "금융"}]
    two = kb_search.sector_route("대형마트 의무휴업", rows)
    assert [s["code"] for s in two["sectors"]] == ["CD", "CS"] and two["docs"] == ["sec:유통산업발전법"]
    for q in ("세율을 알려 주세요", "펀드 가입 뒤 청약을 철회할 수 있는 기간은?", ""):
        assert kb_search.sector_route(q, rows) == {"sectors": [], "docs": [], "words": []}


# ==================================================
# 2. 낱말 표 만들기
# ==================================================
def test_word_rows_sources_sectors_and_skips():
    """TC-SQ-02 · 정식 이름 · 약칭 · 업 이름 · 시행령까지 · 두 섹터 법은 두 섹터로 · 근거 문서와 겹치는 법 · 한 글자는 뺀다."""
    S = kb_sector.SectorLaw
    table = [S("Fi", "금융", "은행법", "업법", True, "", "은행업|은행|업"),
             S("CD", "임의소비재", "유통산업발전법", "업법", True, "", "대형마트"),
             S("CS", "필수소비재", "유통산업발전법", "관련", False, "", ""),
             S("Fi", "금융", "자본시장과 금융투자업에 관한 법률", "업법", True, "", "증권업"),
             S("Ma", "소재", "광업법", "업법", True, "", "광업권")]
    have = {"sec:은행법", "sec:은행법시행령", "sec:유통산업발전법"}          # 광업법은 근거 DB 에 없다
    rows = kb_sector_link.word_rows(table, {"은행법": "은행법", "유통산업발전법": "유통법"}, have,
                                    base_slugs={"자본시장과금융투자업에관한법률"})
    got = {(w, d, c, src) for w, _, d, c, _, src in rows}
    assert ("은행업", "sec:은행법", "Fi", "업 이름") in got and ("은행업", "sec:은행법시행령", "Fi", "업 이름") in got
    assert ("은행법", "sec:은행법", "Fi", "정식 이름") in got                    # 약칭이 정식 이름과 같으면 한 줄
    assert not any(w == "업" for w, *_ in rows)                              # 한 글자는 버린다
    assert ("대형마트", "sec:유통산업발전법", "CS", "업 이름") in got and ("대형마트", "sec:유통산업발전법", "CD", "업 이름") in got
    assert ("유통법", "sec:유통산업발전법", "CD", "약칭") in got
    assert not any("증권업" == w or d.startswith("sec:자본시장") for w, _, d, *_ in rows)
    assert not any(d.startswith("sec:광업법") for _, _, d, *_ in rows)


# ==================================================
# 3. 섹터 문서는 분류가 고를 때만 후보
# ==================================================
def test_sector_docs_only_when_routed(kb):
    """TC-SQ-03 · 섹터 질문이면 섹터 문서까지 · 아니면 지금 근거만 · sector=False 는 분류 전 길 · 벡터 거름도 같다."""
    bank = _cid(kb, "sec:은행법")
    fake = FakeDense([bank])
    r = kb_search.search("은행업 인가를 받으려면 자본금이 얼마인가요", 3, as_of="2026-10-06", path=kb, backend=fake)
    assert r["hits"][0]["doc_id"] == "sec:은행법"
    assert r["route"]["sectors"] == [{"code": "Fi", "name": "금융"}] and r["route"]["sector_docs"] == ["sec:은행법"]
    assert "fts5_sector" in r["retrieval"]["method"]
    assert any(k.startswith("sec:은행법@") for k in fake.calls[-1])          # 벡터도 그 섹터 문서를 묻는다
    assert not any(k.startswith("sec:주택법@") for k in fake.calls[-1])      # 걸리지 않은 섹터 문서는 묻지 않는다

    off = kb_search.search("은행업 인가를 받으려면 자본금이 얼마인가요", 3, as_of="2026-10-06", sector=False, path=kb,
                           backend=fake)
    assert all(not h["doc_id"].startswith("sec:") for h in off["hits"]) and off["route"]["sectors"] == []
    assert not any(k.startswith("sec:") for k in fake.calls[-1])

    plain = kb_search.search("금융상품 설명 의무", 3, as_of="2026-10-06", path=kb, backend=FakeDense([bank]))
    assert all(not h["doc_id"].startswith("sec:") for h in plain["hits"])   # 벡터가 섹터 조각을 내놓아도 후보 밖이면 버린다


def test_explicit_docs_and_missing(kb):
    """TC-SQ-04 · docs 로 콕 집은 섹터 문서는 분류와 상관없이 · 고르지 않은 섹터 문서는 판이 없어도 missing 에 없다."""
    r = kb_search.search("자본금", 3, as_of="2026-10-06", docs=["sec:은행법"], sector=False, mode="lexical", path=kb)
    assert [h["doc_id"] for h in r["hits"]] == ["sec:은행법"]
    early = kb_search.search("청약 철회 기간", 3, as_of="2026-09-30", mode="lexical", path=kb)   # 주택법 판은 10-01 부터
    assert early["missing"] == [] and early["hits"][0]["doc_id"] == "fcpa_act"
    routed = kb_search.search("주택조합 가입 청약 철회", 3, as_of="2026-09-30", mode="lexical", path=kb)
    assert [m["doc_id"] for m in routed["missing"]] == ["sec:주택법"]        # 분류가 고른 문서는 판이 없으면 알린다


# ==================================================
# 4. 낱말 색인을 따로 — 기존 질문의 bm25 가 그대로
# ==================================================
def _bm25(path: Path, q: str, table: str = "kb_chunk_fts") -> dict:
    c = sqlite3.connect(path)
    try:
        return {r[0]: round(r[1], 9) for r in c.execute(
            f"SELECT k.chunk_id, bm25({table}) FROM {table} f JOIN kb_chunk k ON k.rid=f.rowid WHERE {table} MATCH ?",
            (kb_text.fts_query(q),))}
    finally:
        c.close()


def test_separate_index_keeps_base_bm25(tmp_path):
    """TC-SQ-05 · 섹터 조각을 따로 된 색인에 두면 기존 문서의 bm25 가 그대로 · 같은 색인에 두면 바뀐다(대조)."""
    q = "펀드 가입 뒤 청약을 철회할 수 있는 기간은?"
    only = tmp_path / "base.sqlite3"
    conn = kb_law.connect(only)
    _base(conn)
    conn.close()
    before = _bm25(only, q)

    split = tmp_path / "split.sqlite3"
    conn = kb_law.connect(split)
    _base(conn)
    _sector(conn)                     # 섹터 조각은 kb_sector_fts 로 옮긴다
    conn.close()
    after = _bm25(split, q)
    assert after == before            # 같은 조각 · 같은 점수(섹터 조각은 기존 색인에 없다)
    assert _bm25(split, q, kb_sector_link.SECTOR_FTS)    # 섹터 색인에서는 섹터 조각이 찾아진다

    mixed = tmp_path / "mixed.sqlite3"
    conn = kb_law.connect(mixed)
    _base(conn)
    _store(conn, HOUSING, _v("20002", "2025-01-01", "2026-01-01"), [
        Article("제11조의6", "조합 가입 철회 및 가입비등의 반환", "제2장 주택의 건설 등", HOUSING_WITHDRAW)])
    conn.close()                      # 옮기지 않으면 — 섹터 조각이 기존 색인의 통계에 섞인다
    mixed_scores = _bm25(mixed, q)
    assert {k: v for k, v in mixed_scores.items() if k in before} != before


def test_sweep_and_remove(kb):
    """TC-SQ-06 · 기존 색인에 남은 섹터 조각은 옮기고 떠돌이 행은 지운다 · 문서를 지우면 두 색인에서 모두 빠진다."""
    conn = kb_law.connect(kb)
    conn.executescript(kb_sector_link.WORD_SCHEMA)
    rid = conn.execute("SELECT rid FROM kb_chunk WHERE doc_id='sec:은행법'").fetchone()[0]
    grams = conn.execute(f"SELECT grams FROM {kb_sector_link.SECTOR_FTS} WHERE rowid=?", (rid,)).fetchone()[0]
    conn.execute(f"DELETE FROM {kb_sector_link.SECTOR_FTS} WHERE rowid=?", (rid,))
    conn.execute("INSERT INTO kb_chunk_fts(rowid, grams) VALUES (?, ?)", (rid, grams))      # 기존 색인에 샌 행
    conn.execute(f"INSERT INTO {kb_sector_link.SECTOR_FTS}(rowid, grams) VALUES (999999, '떠돌이')")
    assert kb_sector_link.sweep_fts(conn) == (1, 1)
    assert conn.execute("SELECT COUNT(*) FROM kb_chunk_fts WHERE rowid=?", (rid,)).fetchone()[0] == 0
    assert conn.execute(f"SELECT COUNT(*) FROM {kb_sector_link.SECTOR_FTS} WHERE rowid=?", (rid,)).fetchone()[0] == 1

    kb_sector_link.remove_doc(conn, "sec:은행법")
    assert conn.execute("SELECT COUNT(*) FROM kb_chunk WHERE doc_id='sec:은행법'").fetchone()[0] == 0
    assert conn.execute(f"SELECT COUNT(*) FROM {kb_sector_link.SECTOR_FTS} WHERE rowid=?", (rid,)).fetchone()[0] == 0
    conn.close()


# ==================================================
# 5. 기존 평가 질문에 헛걸림 0 · 섹터 표 규칙 · API 인자
# ==================================================
def _questions(name: str) -> list[str]:
    with open(ROOT / "docs" / "시험" / name, encoding="utf-8", newline="") as f:
        return [r["질문"] for r in csv.DictReader(f, delimiter="\t")]


def test_sector_table_words_do_not_hit_base_questions():
    """TC-SQ-07 · 섹터 표의 업 이름이 기존 근거 질문(검색 50 · 근거답 20 의 법령 질문)에 걸리지 않는다 · 낱말 규칙."""
    table = kb_sector.load_map()
    words = [(w.strip(), s.title) for s in table for w in s.words.split("|") if w.strip()]
    assert len(words) >= 300 and sum(1 for s in table if s.words) >= 70
    rows = [{"word": kb_search.norm_word(w), "shown": w, "doc_id": t, "sector_code": "x", "sector": "x", "source": "업 이름"}
            for w, t in words]
    assert all(len(r["word"]) >= kb_sector_link.MIN_WORD for r in rows)
    # 기존 근거 질문의 말 · 다른 뜻이 흔한 짧은 말은 넣지 않는다(설계서 5.3.7 · 섹터 표 words 칸 규칙)
    banned = {"증권사", "예금", "청약", "펀드", "금융", "주세", "리스", "제약", "의원"}
    assert not [w for w, _ in words if kb_search.norm_word(w) in banned]
    qs = _questions("근거검색-평가셋_v1.tsv") + [q for q in _questions("근거답-평가셋_v2.tsv")]
    hits = {q: kb_search.sector_route(q, rows)["words"] for q in qs}
    # ISA(근거답 N02)만 섹터 질문이다 — 조세특례제한법 제91조의18 · 그 밖에는 하나도 걸리지 않는다
    assert {q: w for q, w in hits.items() if w} == {"ISA 계좌의 비과세 한도는 얼마인가요?": ["ISA"],
                                                      "지금 2차전지 종목을 사야 할까요?": ["2차전지"]}


def test_route_passes_sector_flag(monkeypatch):
    """TC-SQ-08 · GET /api/kb/search 의 sector 인자가 찾기까지 간다(기본 켬)."""
    seen = []
    monkeypatch.setattr(kb_search, "search", lambda *a, **kw: seen.append(kw) or {"hits": []})
    app = FastAPI()
    app.include_router(kb_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1"}
    c = TestClient(app)
    assert c.get("/api/kb/search", params={"q": "은행업 인가"}).status_code == 200
    assert c.get("/api/kb/search", params={"q": "은행업 인가", "sector": "false"}).status_code == 200
    assert [kw["sector"] for kw in seen] == [True, False]
