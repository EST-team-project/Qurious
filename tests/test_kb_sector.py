"""섹터별 · 연도별 근거 법령 시험 (TC-SG) — `collector/kb_sector.py` · `collector/kb_data/sector_laws.tsv`.

여기서 지키는 것 —
1. 섹터 표는 우리 섹터 분류(11섹터 + 공통)와 같은 코드 · 이름이고, 섹터마다 핵심 업법이 하나 이상 있다 · 같은 줄이 두 번 없다.
2. 받을 문서 — 법률은 한 번만, 시행령은 decree=Y 인 법률에서만.
3. 기준일 — 지난해들은 12월 31일, 올해는 오늘.
4. 받기 — 해마다 그해 시행 판을 고르고 조를 저장한다 · 그해에 시행 전이면 두지 않는다 · 목록에 없는 문서는 메모를 남긴다 ·
   다시 돌려 고른 판이 같으면 본문을 다시 받지 않는다.

네트워크 · 실제 법령 DB 를 쓰지 않는다 — 법령 API 와 같은 모양의 가짜 응답을 쓴다.
"""
from __future__ import annotations

from datetime import date

import pytest

from collector import kb_sector as K


def test_sector_map_matches_our_sectors_and_has_core_law_each():
    """TC-SG-01 · 섹터 표 — 11섹터 + 공통이 다 있고 이름이 섹터 파일과 같다 · 섹터마다 업법 하나 이상 · 중복 없음."""
    rows = K.load_map()
    assert {r.sector_code for r in rows} == set(K.SECTOR_CODES)
    for code in K.SECTOR_CODES:
        if code != "All":
            assert any(r.sector_code == code and r.role == "업법" for r in rows), f"{code} 에 업법이 없다"
    assert all(r.why for r in rows)
    assert "반도체산업 경쟁력 강화 및 지원에 관한 특별법" in {r.title for r in rows}   # 법안 때 이름이 아니라 시행된 이름


def test_load_map_rejects_wrong_row(tmp_path):
    """TC-SG-02 · 코드 · 이름 · 역할이 틀린 줄이 있으면 조용히 빼지 않고 멈춘다."""
    p = tmp_path / "m.tsv"
    p.write_text("sector_code\tsector\ttitle\trole\tdecree\twhy\nHe\t헬스\t약사법\t업법\tY\tx\n", encoding="utf-8")
    with pytest.raises(ValueError):
        K.load_map(p)


def test_documents_and_as_of():
    """TC-SG-03 · 법률은 한 번 · 시행령은 decree=Y 에서만 · 기준일은 연말(올해는 오늘)."""
    rows = [K.SectorLaw("Fi", "금융", "자본시장과 금융투자업에 관한 법률", "업법", True, "x"),
            K.SectorLaw("Re", "부동산", "자본시장과 금융투자업에 관한 법률", "관련", False, "x"),
            K.SectorLaw("Re", "부동산", "주택법", "관련", False, "x")]
    assert K.documents(rows) == [("자본시장과 금융투자업에 관한 법률", ""), ("주택법", ""),
                                 ("자본시장과 금융투자업에 관한 법률 시행령", "자본시장과 금융투자업에 관한 법률")]
    today = date(2026, 10, 5)
    assert K.as_of_for(2024, today) == "2024-12-31" and K.as_of_for(2026, today) == "2026-10-05"
    assert K.parse_years("", today) == [2020, 2021, 2022, 2023, 2024, 2025, 2026]


class FakeLaw:
    """법령 API 와 같은 모양 — 약사법 판 둘(2021-06-30 · 2026-09-11) · 새법은 2026-03-01 부터 · 없는법은 목록에 없음."""

    VERSIONS = {
        "약사법": [("100", "2021-06-30", "2021-01-01", "법률 제1호", "연혁"), ("200", "2026-09-11", "2026-03-11", "법률 제2호", "현행")],
        "새법": [("300", "2026-03-01", "2025-09-01", "법률 제3호", "현행")],
    }

    def __init__(self):
        self.calls = 0
        self.bodies = []

    def get(self, path, params, target):
        self.calls += 1
        if path == "lawSearch.do":
            rows = [{"법령명한글": params["query"], "법령일련번호": mst, "시행일자": ef.replace("-", ""),
                     "공포일자": pr.replace("-", ""), "공포번호": no.split("제")[1].rstrip("호"), "현행연혁코드": st,
                     "법령구분명": "법률", "제개정구분명": "일부개정"}
                    for mst, ef, pr, no, st in self.VERSIONS.get(params["query"], [])]
            return {"LawSearch": {"law": rows}}
        self.bodies.append((params["MST"], params["efYd"]))
        n = 2 if params["MST"] == "100" else 3
        units = [{"조문여부": "조문", "조문번호": str(i), "조문제목": f"제목{i}", "조문내용": f"제{i}조(제목{i}) 판 {params['MST']}"}
                 for i in range(1, n + 1)]
        return {"법령": {"기본정보": {"소관부처": {"content": "보건복지부"}}, "조문": {"조문단위": units}}}


def test_fetch_picks_year_end_version_skips_unchanged_and_notes_missing(tmp_path):
    """TC-SG-04 · 해마다 그해 시행 판 · 시행 전 해는 없음 · 목록에 없는 문서는 메모 · 다시 돌리면 본문을 다시 받지 않는다."""
    conn = K.connect(tmp_path / "s.sqlite3")
    fake = FakeLaw()
    docs = [("약사법", ""), ("새법", ""), ("없는법", "")]
    r = K.fetch(conn, fake, docs, [2020, 2021, 2025, 2026], date(2026, 10, 5))
    assert r["missing"] == 1 and r["not_in_force"] == 4          # 약사법 2020 · 새법 2020 · 2021 · 2025
    got = {(t, y): (ef, n) for t, y, ef, n in conn.execute("SELECT title, year, effective_at, n_articles FROM ks_choice")}
    assert got == {("약사법", 2021): ("2021-06-30", 2), ("약사법", 2025): ("2021-06-30", 2),
                   ("약사법", 2026): ("2026-09-11", 3), ("새법", 2026): ("2026-03-01", 3)}
    assert conn.execute("SELECT COUNT(*) FROM ks_article WHERE title='약사법' AND year=2026").fetchone()[0] == 3
    assert conn.execute("SELECT dept FROM ks_doc WHERE title='약사법'").fetchone()[0] == "보건복지부"
    assert "없다" in conn.execute("SELECT note FROM ks_doc WHERE title='없는법'").fetchone()[0]
    n_bodies = len(fake.bodies)
    r2 = K.fetch(conn, fake, docs, [2020, 2021, 2025, 2026], date(2026, 10, 5))
    assert r2["years_new"] == 0 and r2["years_same"] == 4 and len(fake.bodies) == n_bodies   # 목록만 묻고 본문은 안 받음
    conn.close()


class PagedLaw(FakeLaw):
    """첫 쪽에는 같은 이름의 시행령 줄과 최근 판만 — 2018년 판은 둘째 쪽에 있다(실제 목록의 모양 · 자동차관리법)."""

    def get(self, path, params, target):
        if path != "lawSearch.do":
            return super().get(path, params, target)
        self.calls += 1
        self.pages = getattr(self, "pages", []) + [params.get("page")]
        if params.get("page") == "1":
            rows = [{"법령명한글": "긴법 시행령", "법령일련번호": str(900 + i), "시행일자": "20260101", "공포일자": "20251201",
                     "공포번호": str(i), "현행연혁코드": "연혁"} for i in range(98)]
            rows += [{"법령명한글": "긴법", "법령일련번호": "200", "시행일자": "20240101", "공포일자": "20231201", "공포번호": "2",
                      "현행연혁코드": "현행"}]
            return {"LawSearch": {"law": rows, "totalCnt": "450"}}
        rows = [{"법령명한글": "긴법", "법령일련번호": "100", "시행일자": "20180101", "공포일자": "20171201", "공포번호": "1",
                 "현행연혁코드": "연혁"}]
        return {"LawSearch": {"law": rows, "totalCnt": "450"}}


def test_version_list_pages_until_oldest_year_is_covered(tmp_path):
    """TC-SG-05 · 판 목록이 시행령 줄과 섞여 첫 쪽에 최근 판만 오면 쪽을 넘겨 2020년에 시행 중인 판(2018 시행)을 찾는다."""
    conn = K.connect(tmp_path / "p.sqlite3")
    fake = PagedLaw()
    K.fetch(conn, fake, [("긴법", "")], [2020, 2026], date(2026, 10, 5))
    got = dict(conn.execute("SELECT year, effective_at FROM ks_choice WHERE title='긴법'").fetchall())
    assert got == {2020: "2018-01-01", 2026: "2024-01-01"}
    assert fake.pages == ["1", "2"]                                # 2020 판을 찾으면 더 넘기지 않는다
    conn.close()
