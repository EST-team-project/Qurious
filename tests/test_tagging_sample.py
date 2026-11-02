"""이름표 정밀도 표본 도구 시험 (TC-TGS) — `scripts/tagging_sample.py` (할 일 ①-23 C 조각 · 근거 답 품질 보고서 v0.2).

여기서 지키는 것 —
1. 같은 색인 · 같은 시드 · 같은 인자면 같은 표본이다(바이트까지) · 다른 시드면 다르다 · 이미 있는 표본 파일(사람 판정이 들어 있을 수
   있다)은 --force 없이 덮지 않는다.
2. 층화가 한 종류로 쏠리지 않는다 — 큰 층이 표본을 삼키지 않고 · 작은 층도 빠지지 않고 · 의심 종류(소송·제재)는 최소 건수를 채운다.
3. 종목틀 줄은 종목 이름표가 붙은 뉴스에서만 뽑히고(회사 이름을 함께 보인다) · 그 줄이 재지 않는 칸은 「해당없음」 이 미리 적히며 ·
   규칙이 부제에서 맞춘 줄은 ※부제 로 표시된다.
4. 채점 값 — 엄격 · 관대 · 윌슨 구간 · 층 크기 가중(가중 없는 값과 다르다) · 목표 판정(충족 · 미달 · 보류).
5. 빈 판정은 조용히 넘어가지 않는다(경고 + 0 이 아닌 종료 코드) · 알 수 없는 값은 줄 번호와 함께 오류.
6. 검색 색인은 읽기 전용으로만 연다(INSERT 가 막히고 · 뽑은 뒤에도 파일이 그대로다).

가짜 색인은 도구가 실제로 읽는 꼴(`doc` · `doc_tag` · `meta`)로 만든다. 실제 수집 DB 를 쓰는 시험은 마지막 스모크 하나뿐이고
색인이 없으면 건너뛴다. 네트워크를 쓰지 않는다.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Dict, List

import pytest

from scripts import tagging_sample as TS

_DDL = """
CREATE TABLE doc (rid INTEGER PRIMARY KEY, doc_id TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', published TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '', corp_name TEXT NOT NULL DEFAULT '', stock_code TEXT NOT NULL DEFAULT '',
    extra TEXT NOT NULL DEFAULT '{}');
CREATE TABLE doc_tag (rid INTEGER NOT NULL, tag_type TEXT NOT NULL, tag TEXT NOT NULL, method TEXT NOT NULL,
    PRIMARY KEY (rid, tag_type, tag));
CREATE INDEX ix_tag ON doc_tag(tag_type, tag, rid);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

COMPANIES = [("005930", "삼성전자"), ("000660", "SK하이닉스"), ("051910", "LG화학"), ("035720", "카카오뱅크")]


def build_index(path: Path) -> Path:
    """가짜 검색 색인 — 공시 459건(한 주제에 쏠린 모집단) · 뉴스 120건.

    공시 주제: 지분 400(+둘이 붙은 글 1) · 소송·제재 30(+1) · 배당 20 · 증자 6 · 감자 2.
    뉴스 주제: 소송·제재 40(앞 10건은 종목도 붙음) · 금리 12 · 환율 5 · 배당 3(하나는 제목이 아니라 부제에서 맞음).
    종목만 붙은 뉴스 50건.
    """
    conn = sqlite3.connect(path)
    conn.executescript(_DDL)
    state = {"rid": 0}

    def add(kind: str, doc_id: str, title: str, *, summary: str = "", published: str = "2026-10-01",
            corp_name: str = "", stock_code: str = "", tags=()) -> None:
        state["rid"] += 1
        conn.execute("INSERT INTO doc (rid, doc_id, kind, title, summary, url, published, source, corp_name, stock_code) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (state["rid"], doc_id, kind, title, summary, f"https://example.test/{doc_id}", published,
                      "dart" if kind == "disclosure" else "gdelt", corp_name, stock_code))
        for t in tags:
            conn.execute("INSERT INTO doc_tag (rid, tag_type, tag, method) VALUES (?,?,?,?)", (state["rid"],) + tuple(t))

    n = 0
    for topic, word, count in (("지분", "대량보유", 400), ("소송·제재", "소송", 30), ("배당", "배당", 20),
                               ("증자", "유상증자", 6), ("감자", "감자결정", 2)):
        for i in range(count):
            code, name = COMPANIES[n % len(COMPANIES)]
            n += 1
            add("disclosure", f"D:{topic}-{i:03d}", f"{word}관련공시{i}", corp_name=name, stock_code=code,
                published=f"2026-10-{1 + i % 28:02d}",
                tags=[("symbol", code, "dart_field"), ("topic", topic, f"rule:{word}")])
    add("disclosure", "D:both-001", "대량보유소송제기", corp_name="삼성전자", stock_code="005930", published="2026-10-05",
        tags=[("symbol", "005930", "dart_field"), ("topic", "지분", "rule:대량보유"), ("topic", "소송·제재", "rule:소송")])

    for topic, word, count in (("소송·제재", "소송", 40), ("금리", "금리 인하", 12), ("환율", "환율", 5), ("배당", "배당", 2)):
        for i in range(count):
            tags = [("topic", topic, f"rule:{word}")]
            title = f"{word} 관련 기사 {i}"
            if topic == "소송·제재" and i < 10:
                code, name = COMPANIES[i % len(COMPANIES)]
                title = f"{name}, {word} 관련 기사 {i}"
                tags.insert(0, ("symbol", code, "name_dict"))
            add("news", f"N:{topic}-{i:03d}", title, published=f"2026-10-{1 + i % 28:02d}T09:00:00+09:00", tags=tags)
    add("news", "N:sub-001", "코스피 하락 마감", summary="배당 확대 소식", published="2026-10-20T09:00:00+09:00",
        tags=[("topic", "배당", "rule:배당")])
    for i in range(50):
        code, name = COMPANIES[i % len(COMPANIES)]
        add("news", f"N:sym-{i:03d}", f"{name}, 신제품 공개 {i}", published=f"2026-10-{1 + i % 28:02d}T10:00:00+09:00",
            tags=[("symbol", code, "name_dict")])
    conn.execute("INSERT INTO meta (key, value) VALUES ('built_at', '2026-11-02T19:23:02+09:00')")
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def index_db(tmp_path: Path) -> Path:
    return build_index(tmp_path / "fake_search.sqlite3")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _draw(db: Path, out: Path, *extra: str) -> int:
    return TS.main(["draw", "--db", str(db), "--out", str(out), "--disclosure", "40", "--news", "30",
                    "--news-symbol", "10", *extra])


def _rows(path: Path) -> List[Dict[str, str]]:
    return [r for _, r in TS.read_rows(path)]


def _judge_all(path: Path, value: str = "맞음", blank: int = 0, bad_first: str = "") -> None:
    """그 줄이 재는 칸을 value 로 채운다. blank 건은 비워 두고, bad_first 가 있으면 첫 줄에 넣는다."""
    rows = _rows(path)
    left = blank
    for i, r in enumerate(rows):
        col = "주제판정" if r["층"].startswith("주제:") else "종목판정"
        if bad_first and i == 0:
            r[col] = bad_first
        elif left > 0:
            r[col] = ""
            left -= 1
        else:
            r[col] = value
    TS.write_tsv(path, TS.HEADER, rows)


def test_draw_is_reproducible_and_guards_overwrite(index_db: Path, tmp_path: Path):
    """TC-TGS-01 · 같은 시드는 같은 표본(바이트까지) · 다른 시드는 다른 표본 · 있는 파일은 --force 없이 덮지 않는다."""
    a, b, c = tmp_path / "a.tsv", tmp_path / "b.tsv", tmp_path / "c.tsv"
    assert _draw(index_db, a, "--seed", "7") == 0
    assert _draw(index_db, b, "--seed", "7") == 0
    assert _draw(index_db, c, "--seed", "8") == 0
    assert a.read_bytes() == b.read_bytes()
    rows = _rows(a)
    assert len(rows) == 40 + 30
    assert len({r["원천ID"] for r in rows}) == len(rows)                       # 한 문서가 두 줄이 되지 않는다(둘이 붙은 글 포함)
    assert [r["표본ID"] for r in rows] == [f"S{i:03d}" for i in range(1, 71)]
    assert {r["원천ID"] for r in rows} != {r["원천ID"] for r in _rows(c)}
    assert a.read_text(encoding="utf-8-sig").splitlines()[0].split("\t") == TS.HEADER
    assert all(r["메모"] == "" for r in rows)
    # 판정 칸: 그 줄이 재는 칸은 비워 두고, 재지 않는 칸은 「해당없음」
    for r in rows:
        mine, other = ("주제판정", "종목판정") if r["층"].startswith("주제:") else ("종목판정", "주제판정")
        assert r[mine] == "" and r[other] == TS.NA
    assert all(r["종목판정"] == TS.NA for r in rows if r["구분"] == "공시")     # 공시 종목은 DART 칸 그대로라 판정하지 않는다
    # 덮어쓰기 보호 — 사람 판정이 날아가지 않게
    before = a.read_bytes()
    assert _draw(index_db, a, "--seed", "7") == 2 and a.read_bytes() == before
    assert _draw(index_db, a, "--seed", "7", "--force") == 0


def test_stratification_does_not_let_one_stratum_dominate(index_db: Path, tmp_path: Path):
    """TC-TGS-02 · 층화 — 합이 n · 층 크기를 넘지 않고 · 작은 층도 빠지지 않고 · 큰 층이 삼키지 않고 · 의심 종류는 최소를 채운다.

    먼저 층 배정 함수 하나를, 이어서 같은 규칙을 가짜 색인으로 끝까지 본다.
    """
    sizes = {"지분": 10000, "소송·제재": 80, "배당": 30, "증자": 5, "감자": 1}
    alloc = TS.allocate(sizes, 40, suspects=("소송·제재",))
    assert sum(alloc.values()) == 40
    assert all(0 <= alloc[k] <= sizes[k] for k in sizes)
    assert alloc["감자"] == 1 and alloc["증자"] >= 2                              # 작은 층은 바닥을 받는다
    assert alloc["소송·제재"] >= TS.SUSPECT_MIN                                  # 의심 종류 최소
    assert alloc["지분"] / 40 < 0.5                                              # 모집단 비례였다면 99%
    assert TS.allocate(sizes, 40) == TS.allocate(sizes, 40)                       # 결정적
    assert TS.allocate({"가": 3, "나": 2}, 10) == {"가": 3, "나": 2}               # n 이 전체보다 크면 전부
    tiny = TS.allocate({"가": 50, "나": 40, "다": 30}, 2)                           # 층보다 표본이 적으면 큰 층부터 1건
    assert sum(tiny.values()) == 2 and tiny["다"] == 0

    # 끝까지 — 공시 지분(401건 · 모집단의 87%)이 표본의 절반을 넘지 않고 소송·제재가 최소를 채운다
    out = tmp_path / "s.tsv"
    assert _draw(index_db, out) == 0
    rows = _rows(out)
    by: Dict[str, int] = {}
    for r in rows:
        if r["구분"] == "공시":
            by[r["층"]] = by.get(r["층"], 0) + 1
    assert sum(by.values()) == 40
    assert by["주제:지분"] / 40 < 0.5
    assert by["주제:소송·제재"] >= TS.SUSPECT_MIN and by["주제:감자"] == 2 and by["주제:증자"] >= 2
    news_topic = [r for r in rows if r["구분"] == "뉴스" and r["층"].startswith("주제:")]
    assert len(news_topic) == 20 and sum(1 for r in news_topic if r["층"] == "주제:소송·제재") >= 12
    # 층크기는 모집단 수 그대로(채점 가중에 쓴다) — 둘이 붙은 글도 두 층에 모두 센다
    sizes = {r["층"]: int(r["층크기"]) for r in rows if r["구분"] == "공시"}
    assert sizes["주제:지분"] == 401 and sizes["주제:소송·제재"] == 31 and sizes["주제:감자"] == 2


def test_symbol_frame_and_subtitle_marks(index_db: Path, tmp_path: Path):
    """TC-TGS-03 · 종목틀은 종목 이름표가 붙은 뉴스에서만 · 회사 이름을 함께 보임 · 규칙이 부제에서 맞춘 줄은 ※부제."""
    out = tmp_path / "s.tsv"
    assert _draw(index_db, out) == 0
    sym = [r for r in _rows(out) if r["층"].startswith("종목:")]
    assert len(sym) == 10
    for r in sym:
        assert r["구분"] == "뉴스" and r["층"] == "종목:뉴스" and r["층크기"] == "60"   # 종목이 붙은 뉴스 60건 가운데
        assert any(f"{name}({code})" in r["종목 이름표"] for code, name in COMPANIES)
        assert r["주제 이름표"] == "" and r["주제판정"] == TS.NA
    # 뉴스 주제 글 전부(소송·제재 40 + 금리 12 + 환율 5 + 배당 3 = 60)를 뽑게 해서 부제에서 맞춘 글이 들어오게 한다
    conn = TS.open_readonly(index_db)
    try:
        rows, meta = TS.draw_sample(conn, seed=1, n_disclosure=0, n_news=100, n_news_symbol=0)
    finally:
        conn.close()
    assert len(rows) == 60 and meta["표본틀"]["뉴스/주제"]["뽑힘"] == 60
    marked = [r for r in rows if "※부제" in r["주제 이름표"]]
    assert [r["원천ID"] for r in marked] == ["N:sub-001"] and meta["부제표시줄"] == 1
    assert marked[0]["주제 이름표"].startswith("배당(배당)") and marked[0]["부제"] == "배당 확대 소식"
    assert all(r["부제"] == "" or r["원천ID"] == "N:sub-001" for r in rows)


def test_score_numbers_wilson_and_weights():
    """TC-TGS-04 · 점수 — 엄격 · 관대 · 윌슨 구간 · 층 크기 가중이 가중 없는 값과 다르다 · 목표 판정."""
    lo, hi = TS.wilson(0.9, 10)                                                   # 9/10 의 95% 윌슨 구간(교과서 값)
    assert (round(lo, 3), round(hi, 3)) == (0.596, 0.982)
    assert all(map(lambda x: x != x, TS.wilson(0.5, 0)))                          # n=0 → nan
    assert TS.verdict(0.91, 0.99) == "충족" and TS.verdict(0.50, 0.85) == "미달" and TS.verdict(0.80, 0.95).startswith("보류")
    assert "점수 ≥ 목표" in TS.verdict(0.80, 0.95, 0.9, 0.92) and "점수 < 목표" in TS.verdict(0.80, 0.95, 0.9, 0.88)

    def item(sid, kind, frame, stratum, size, value):
        return TS.Item(sid, kind, frame, stratum, size, value)

    items = [item("a1", "공시", "주제", "A", 900, "맞음"), item("a2", "공시", "주제", "A", 900, "틀림"),
             item("b1", "공시", "주제", "B", 100, "맞음"), item("b2", "공시", "주제", "B", 100, "맞음")]
    items += [item(f"s{i}", "뉴스", "종목", "뉴스", 9000, v) for i, v in enumerate(["맞음"] * 8 + ["부분", "틀림"])]
    s = TS.summarize(items)
    g = s["그룹"][("주제", "공시")]
    assert g["가중"].strict == pytest.approx((900 * 0.5 + 100 * 1.0) / 1000)       # 0.55 — A 층은 모집단의 90%
    assert g["표본그대로"].strict == pytest.approx(0.75)                            # 가중 없는 값은 큰 층 틀림을 가볍게 본다
    assert g["가중"].n_eff == pytest.approx(1000 ** 2 / (2 * 450 ** 2 + 2 * 50 ** 2))  # 유효 표본 크기 2.44
    e = s["그룹"][("종목", "뉴스")]["가중"]
    assert (e.n, e.ok, e.part, e.bad) == (10, 8, 1, 1)
    assert e.strict == pytest.approx(0.8) and e.lenient == pytest.approx(0.85)     # 맞음만 1 · 부분 0.5
    assert e.strict_ci == pytest.approx(TS.wilson(0.8, 10))

    c = TS.Collected(total=len(items), items=items)
    text = TS.render_report(c)
    assert "## 1. 요약" in text and "0.550" in text and "0.750" in text and "보류" in text


def test_score_warns_on_blank_and_invalid(index_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture):
    """TC-TGS-05 · 빈 판정은 세어 경고하고 끝낸다(조용히 무시하지 않는다) · 알 수 없는 값은 줄 번호와 함께 오류."""
    out = tmp_path / "s.tsv"
    assert _draw(index_db, out) == 0
    capsys.readouterr()

    _judge_all(out, blank=3)
    assert TS.main(["score", str(out)]) == 1
    printed = capsys.readouterr().out
    assert "빈 판정 3줄" in printed and "# 이름표 정밀도 채점" not in printed       # 표를 내지 않고 끝낸다
    assert TS.main(["score", str(out), "--partial"]) == 0                         # 중간 확인은 경고를 남기고 계속
    printed = capsys.readouterr().out
    assert "빈 판정 3줄" in printed and "# 이름표 정밀도 채점" in printed and "중간 확인" in printed

    _judge_all(out, bad_first="정답")                                              # 이 도구의 값은 맞음 · 부분 · 틀림
    assert TS.main(["score", str(out)]) == 2
    err = capsys.readouterr().err
    assert "정답" in err and "파일 2줄" in err

    _judge_all(out, value="맞음")
    assert TS.main(["score", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "| 판정함(맞음 · 부분 · 틀림) | 70 |" in printed and "| 빈 판정 | 0 |" in printed
    assert "공시 주제 이름표" in printed and "뉴스 종목 이름표" in printed

    # 엑셀이 다시 저장한 꼴도 읽는다 — 「유니코드 텍스트」(UTF-16) · 「텍스트(탭으로 분리)」(cp949)
    text = out.read_text(encoding="utf-8-sig")
    for enc, name in (("utf-16", "u16.tsv"), ("cp949", "cp949.tsv")):
        alt = tmp_path / name
        alt.write_bytes(text.replace("※", "*").encode(enc))   # cp949 에 없는 ※ 는 바꿔 쓴다(점수에는 쓰이지 않는 칸)
        assert TS.main(["score", str(alt)]) == 0, enc
        assert "| 판정함(맞음 · 부분 · 틀림) | 70 |" in capsys.readouterr().out
    broken = tmp_path / "broken.tsv"
    broken.write_bytes(b"\xff\x00\xfe\x81")                       # 어느 인코딩도 아님 → 오류 2
    assert TS.main(["score", str(broken)]) == 2


def test_index_is_opened_read_only(index_db: Path, tmp_path: Path):
    """TC-TGS-06 · 검색 색인은 읽기 전용 — INSERT 가 막히고 · 뽑은 뒤에도 파일이 그대로이며 · 색인이 아닌 파일은 거절한다."""
    conn = TS.open_readonly(index_db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO meta (key, value) VALUES ('x', 'y')")
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
    finally:
        conn.close()
    before = _sha(index_db)
    assert _draw(index_db, tmp_path / "s.tsv") == 0
    assert _sha(index_db) == before
    with pytest.raises(FileNotFoundError):
        TS.open_readonly(tmp_path / "없는파일.sqlite3")
    other = tmp_path / "other.sqlite3"
    sqlite3.connect(other).executescript("CREATE TABLE t (a)")
    with pytest.raises(ValueError):
        TS.open_readonly(other)
    assert TS.main(["draw", "--db", str(other), "--out", str(tmp_path / "o.tsv")]) == 2


@pytest.mark.skipif(not TS.DEFAULT_DB.exists(), reason="검색 색인(data/collector/search.sqlite3)이 없다")
def test_real_index_smoke_draws_200(tmp_path: Path):
    """TC-TGS-07 · 스모크 — 실제 검색 색인에서 기본값으로 200줄(공시 100 · 뉴스 100)이 나오고 색인 파일은 그대로다.

    수집 회차가 색인을 쓰는 중이면 잠금으로 열리지 않을 수 있다 — 그때는 건너뛴다(환경 문제이지 도구 결함이 아니다).
    """
    stat = TS.DEFAULT_DB.stat()
    out = tmp_path / "real.tsv"
    try:
        rc = TS.main(["draw", "--out", str(out)])
    except sqlite3.OperationalError as e:
        pytest.skip(f"검색 색인을 열 수 없다(수집 회차 중?): {e}")
    assert rc == 0
    rows = _rows(out)
    assert len(rows) == 200
    assert sum(1 for r in rows if r["구분"] == "공시") == 100 and sum(1 for r in rows if r["구분"] == "뉴스") == 100
    assert sum(1 for r in rows if r["층"] == "종목:뉴스") == 40
    assert len({r["원천ID"] for r in rows}) == 200
    after = TS.DEFAULT_DB.stat()
    assert (after.st_size, after.st_mtime_ns) == (stat.st_size, stat.st_mtime_ns)
