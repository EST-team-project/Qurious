"""근거 문서 받기 시험 (TC-LW) — 판 고르기 · 판 점검 · 조문 쪼개기 · 청크 머리 · 청크 ID · 키 지우기 · 다시 쪼개기
(목표 기능 ① W5 · 설계서 5.3.2 · 8절 「TC-LW」).

무엇을 지키나 —
1. **판 고르기** — 기준일에 시행 중인 판 = 시행일 ≤ 기준일 가운데 시행일이 가장 늦은 판(eflaw 시행일 판).
   증권거래세법 시행령은 제35947호(12-30 공포 · 01-02 시행)를 고르고, 하루 뒤 공포된 제36001호(01-01 시행)의
   새 세율이 그 본문에 담겼는지 조마다 대조한 기록을 남긴다(2026-10-02 실측 · 설계서 v0.1 의 「공포일 순」 은 틀렸다).
2. **같은 날 공포 · 다른 시행일**(자본시장법 시행령 제36728호 10-02 · 제36729호 10-01) — 기준일마다 맞는 판.
3. **청크 머리 = 제목 사슬** — 첫 줄이 「문서 > 편 > 장 > … > 제○조(제목)」 이고(<개정 …> 꼬리표 없음),
   본문 첫머리에 같은 조 머리가 되풀이되지 않는다(2026-10-03 사용자 결정 「경로를 넣는다」).
4. **청크 ID 는 자리로** — 두 번 받아도 같은 ID(sha256(문서 · 판 · 조 · 순번)) · 내용이 바뀌어도 자리가 같으면 같은 ID.
5. **감독규정 한 줄 본문** — 머리를 「다음 번호답게」 이어지는 것만 받아 조가 순서대로 나온다.
6. **키 지우기** — 응답에 실려 온 `OC=…` 는 저장 전에 지우고, 오류 문장에 주소 · 키를 넣지 않는다.
7. **다시 쪼개기(rechunk)** — 쪼개기 규칙만 바꿨을 때 받아 둔 원문(kb_raw)으로 같은 길을 네트워크 없이 다시 돈다.

고정값은 `tests/fixtures/kb_law/*.json.gz` — 2026-10-02 에 받은 법령 API 응답(키는 ``OC=***`` 로 지워져 있고,
행정규칙 기본정보의 담당자 이름 · 전화번호와 법령 연락부서 전화는 비웠다). 네트워크를 쓰지 않는다.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import sqlite3
import urllib.error
from pathlib import Path

import pytest

from app.services import kb_text
from collector import kb_law

FIX = Path(__file__).resolve().parent / "fixtures" / "kb_law"


def load(name: str) -> dict:
    return json.loads(gzip.decompress((FIX / f"{name}.json.gz").read_bytes()).decode("utf-8"))


class Replay:
    """법령 API 대신 — 저장해 둔 응답을 target 이름으로 돌려준다."""

    def __init__(self, *names: str):
        self.data = {}
        for n in names:
            self.data.update(load(n))
        self.calls = 0
        self.targets: list[str] = []

    def get(self, path, params, target):
        self.calls += 1
        self.targets.append(target)
        if target not in self.data:
            raise kb_law.LawApiError(f"고정값에 없는 응답 — {target}")
        return self.data[target]


def run(tmp_path: Path, doc: str, as_of: str = "2026-10-02", name: str = "kb.sqlite3"):
    conn = kb_law.connect(tmp_path / name)
    rp = Replay(doc)
    res = kb_law.fetch_doc(rp, conn, kb_law.DOC_BY_ID[doc], as_of)
    return conn, res, rp


def chunks(conn, doc: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM kb_chunk WHERE doc_id=? ORDER BY article_key, seq", (doc,)).fetchall()


# ── 1 · 2 판 고르기 ───────────────────────────────────────────────────────────
def test_select_version_stt_decree_from_saved_list():
    """TC-LW-01 · 증권거래세법 시행령 — 10-02 는 제35947호(01-02 시행) · 01-01 은 제36001호 · 그 전날은 더 옛 판."""
    class R:
        def get(self, path, params, target):
            return load("stt_decree")[target]

    vs = kb_law.law_versions(R(), "증권거래세법 시행령")
    assert vs and all(v.effective_at for v in vs)
    assert kb_text.select_version(vs, "2026-10-02").label == "대통령령 제35947호 · 2026-01-02 시행"
    assert kb_text.select_version(vs, "2026-01-01").label == "대통령령 제36001호 · 2026-01-01 시행"
    before = kb_text.select_version(vs, "2025-12-31")
    assert before.effective_at <= "2025-12-31"
    assert before.effective_at == max(v.effective_at for v in vs if v.effective_at <= "2025-12-31")
    # 목록 41줄 = 이름이 같은 판 40(띄어쓰기만 다른 옛 이름 · 1960년대 「각령」 포함) + 이름이 비슷한 다른 법령 1
    # (「…시행령중개정령의시행일에관한규칙」 · 재무부령) — 그 하나만 빠진다
    assert len(vs) == 40 and "재무부령" not in {v.law_type for v in vs}
    assert {v.law_type for v in vs} == {"대통령령", "각령"}


def test_select_version_same_day_promulgation_different_effective_dates():
    """TC-LW-02 · 같은 날 공포된 두 판(자본시장법 시행령 모양) — 시행일로 고른다 · 같은 시행일이면 공포일 → 공포번호."""
    a = kb_text.Version("s1", "36728", "2026-09-29", "2026-10-02", law_type="대통령령")
    b = kb_text.Version("s2", "36729", "2026-09-29", "2026-10-01", law_type="대통령령")
    assert kb_text.select_version([a, b], "2026-10-02") == a      # 공포번호가 큰 b 가 아니다
    assert kb_text.select_version([a, b], "2026-10-01") == b
    assert kb_text.select_version([a, b], "2026-09-30") is None
    c = kb_text.Version("s3", "36730", "2026-09-30", "2026-10-02", law_type="대통령령")
    d = kb_text.Version("s4", "36731", "2026-09-30", "2026-10-02", law_type="대통령령")
    assert kb_text.select_version([a, c], "2026-10-03") == c       # 같은 시행일 → 늦게 공포된 판
    assert kb_text.select_version([c, d], "2026-10-03") == d       # 공포일도 같으면 → 공포번호가 큰 판


def test_fetch_doc_checks_later_version_and_keeps_new_rate(tmp_path):
    """TC-LW-03 · 고른 판(제35947호) 본문이 하루 뒤 공포된 제36001호 개정을 담았는지 대조한 기록 · 제5조는 새 세율."""
    conn, res, rp = run(tmp_path, "stt_decree")
    assert res["label"] == "대통령령 제35947호 · 2026-01-02 시행"
    assert res["notes"] == ["판 점검: 대통령령 제36001호 · 2026-01-01 시행 개정은 고른 판에 담겨 있다"]
    assert rp.calls == 4                                            # 목록 · 고른 판 · 뒤 판 · 그 앞 판
    art5 = [r for r in chunks(conn, "stt_decree") if r["article"] == "제5조"]
    assert len(art5) == 1
    assert "유가증권시장" in art5[0]["text"] and "1만분의 5" in art5[0]["text"]
    assert "1만분의 15" not in art5[0]["text"]                      # 공포 때 본문(target=law)의 옛 세율이 아니다
    doc = conn.execute("SELECT * FROM kb_document WHERE doc_id='stt_decree'").fetchone()
    assert doc["selected_for"] == "2026-10-02" and doc["chunks"] == len(chunks(conn, "stt_decree"))
    assert "OC" not in doc["source_url"] and doc["source_url"].startswith("https://www.law.go.kr/LSW/")


# ── 3 청크 머리 ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("doc", ["stt_decree", "fcp_reg_rule"])
def test_chunk_header_is_title_chain_without_repeated_heading(tmp_path, doc):
    """TC-LW-04 · 첫 줄 = chunk_header(문서 · 경로 · 조) · 경로에 꼬리표 없음 · 본문 첫머리에 같은 조 머리를 되풀이하지 않음."""
    conn, res, _ = run(tmp_path, doc)
    title = kb_law.DOC_BY_ID[doc].title
    rows = chunks(conn, doc)
    assert rows
    for r in rows:
        first, _, rest = r["text"].partition("\n")
        assert first == kb_text.chunk_header(title, r["part"], r["article"], r["article_title"])
        assert "<" not in first
        heading = kb_text.article_heading(r["article"], r["article_title"]).replace(" ", "")
        assert not rest.replace(" ", "").startswith(heading), f"{r['article']} 머리가 본문에 되풀이됐다"
        assert r["chars"] == len(r["text"]) and r["text_sha256"] == kb_text.text_sha256(r["text"])


def test_chunk_header_keeps_part_path_for_law_with_parts(tmp_path):
    """TC-LW-04b · 편 · 장이 있는 법은 경로가 머리에 들어간다(꼬리표만 빠지고 이름은 남는다)."""
    art = kb_law.Article(label="제462조", title="이익의 배당",
                         part="제3편 회사 > 제4장 주식회사 > 제7절 회사의 회계 <개정 2011.4.14>",
                         head="제462조(이익의 배당) 회사는 대차대조표의 순자산액으로부터 …")
    (c,) = kb_law.chunk_article("상법", art)
    assert c.text.splitlines() == ["상법 > 제3편 회사 > 제4장 주식회사 > 제7절 회사의 회계 > 제462조(이익의 배당)",
                                   "회사는 대차대조표의 순자산액으로부터 …"]
    # 다른 조를 가리키는 첫머리는 남긴다
    other = kb_law.Article(label="제2조", title="", head="제2조에 따른 신고를 한 자는 …")
    assert kb_law.chunk_article("어떤 법", other)[0].text.splitlines()[1] == "제2조에 따른 신고를 한 자는 …"


def test_long_article_split_repeats_header(tmp_path):
    """TC-LW-04c · 긴 조는 항 단위로 나뉘고 조각마다 같은 머리 · 순번이 0, 1, 2 …."""
    paras = [(f"{'①②③④⑤⑥'[i]}", f"{'①②③④⑤⑥'[i]} " + "가" * 500) for i in range(6)]
    art = kb_law.Article(label="제17조", title="배당소득", part="제2장 거주자 > 제2절 과세표준", paras=paras)
    cs = kb_law.chunk_article("소득세법", art)
    assert len(cs) >= 3 and [c.seq for c in cs] == list(range(len(cs)))
    head = "소득세법 > 제2장 거주자 > 제2절 과세표준 > 제17조(배당소득)"
    assert all(c.text.splitlines()[0] == head and len(c.text) <= kb_law.MAX_CHARS + 1 for c in cs)
    assert "".join(c.paras for c in cs) == "①②③④⑤⑥"


# ── 4 청크 ID ─────────────────────────────────────────────────────────────────
def test_chunk_ids_are_positional_and_repeatable(tmp_path):
    """TC-LW-05 · 두 번 받아도 같은 (ID, 지문) · ID = sha256(문서 \\x1f 판 \\x1f 조 \\x1f 순번) 앞 32자."""
    c1, _, _ = run(tmp_path, "stt_decree", name="a.sqlite3")
    c2, _, _ = run(tmp_path, "stt_decree", name="b.sqlite3")
    a = [(r["chunk_id"], r["text_sha256"]) for r in chunks(c1, "stt_decree")]
    b = [(r["chunk_id"], r["text_sha256"]) for r in chunks(c2, "stt_decree")]
    assert a == b and len(set(x for x, _ in a)) == len(a)
    r = chunks(c1, "stt_decree")[0]
    raw = "\x1f".join(("stt_decree", r["version_label"], r["article"], str(r["seq"])))
    assert r["chunk_id"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    assert kb_text.point_id(r["chunk_id"]).count("-") == 4      # Qdrant 가 받는 UUID 꼴


# ── 5 감독규정 ────────────────────────────────────────────────────────────────
def test_admrul_one_line_body_articles_in_order(tmp_path):
    """TC-LW-06 · 금융소비자 보호에 관한 감독규정 시행세칙 — 한 줄 본문에서 조 13개가 번호 순서대로(본문 속 인용을 머리로 잡지 않음)."""
    conn, res, _ = run(tmp_path, "fcp_reg_rule")
    labels = list(dict.fromkeys(r["article"] for r in chunks(conn, "fcp_reg_rule")))
    assert labels == [f"제{i}조" for i in range(1, 14)]
    assert res["articles"] == 13
    assert all(r["kind"] == "admrul" and r["grade"] == 2 for r in chunks(conn, "fcp_reg_rule"))


# ── 6 키 지우기 ───────────────────────────────────────────────────────────────
class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_redact_key_before_storing_and_in_errors(tmp_path):
    """TC-LW-07 · 목록 응답에 실려 온 OC 값은 kb_raw 에 저장하기 전에 지우고 · HTTP 오류 문장에 키 · 주소가 없다."""
    secret = "my-oc-key-123"
    body = json.dumps({"LawSearch": {"law": [{"법령상세링크": f"/DRF/lawService.do?OC={secret}&target=eflaw&MST=1"}]}},
                      ensure_ascii=False).encode("utf-8")
    conn = kb_law.connect(tmp_path / "kb.sqlite3")
    client = kb_law.LawClient(oc=secret, conn=conn, opener=lambda req, timeout: _Resp(body), sleep=0)
    data = client.get("lawSearch.do", {"target": "eflaw"}, "eflaw/search/시험")
    assert secret not in json.dumps(data, ensure_ascii=False)
    stored = gzip.decompress(conn.execute("SELECT body FROM kb_raw").fetchone()[0])
    assert secret.encode() not in stored and b"OC=***" in stored

    def boom(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 500, "err", {}, None)

    bad = kb_law.LawClient(oc=secret, conn=None, opener=boom, sleep=0)
    with pytest.raises(kb_law.LawApiError) as e:
        bad.get("lawService.do", {"target": "eflaw"}, "eflaw/1/2026-01-01")
    assert secret not in str(e.value) and "http" not in str(e.value).lower().replace("http 500", "")


# ── 7 다시 쪼개기 ─────────────────────────────────────────────────────────────
def test_rechunk_replays_stored_raw_without_network(tmp_path):
    """TC-LW-08 · 받아 둔 원문(kb_raw)으로 같은 길을 다시 돈다 — 키 · 네트워크 없이 같은 판 · 같은 청크."""
    conn, res, _ = run(tmp_path, "stt_decree")
    before = [(r["chunk_id"], r["text_sha256"]) for r in chunks(conn, "stt_decree")]
    # 수집 때의 kb_raw 는 Replay 가 쓰지 않으므로 고정값을 원문 표에 넣어 둔다(실제 fetch 가 남기는 모양)
    for target, payload in load("stt_decree").items():
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        conn.execute("INSERT INTO kb_raw(source, target, fetched_at, body, sha256, bytes) VALUES (?,?,?,?,?,?)",
                     ("law.go.kr", target, "2026-10-02T16:53:00+09:00", gzip.compress(raw),
                      hashlib.sha256(raw).hexdigest(), len(raw)))
    conn.execute("DELETE FROM kb_chunk")
    conn.execute("DELETE FROM kb_chunk_fts")
    out = kb_law.rechunk(conn, ["stt_decree"])
    assert out["stt_decree"]["label"] == res["label"] and out["stt_decree"]["calls"] == 4
    assert [(r["chunk_id"], r["text_sha256"]) for r in chunks(conn, "stt_decree")] == before
    assert conn.execute("SELECT COUNT(*) FROM kb_chunk_fts").fetchone()[0] == len(before)
    with pytest.raises(kb_law.LawApiError):
        kb_law.rechunk(conn, ["fcp_reg_rule"])                   # 받아 둔 원문이 없으면 멈춘다(받으러 가지 않는다)
