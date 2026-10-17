"""수집 자료 검색 · 재무 API 시험 (TC-DQ) — `GET /api/data/search` · `GET /api/data/financials` (목표 기능 ① W7 · 설계서 5.1.5 · 5.1.7).

여기서 지키는 것 —
1. 색인은 수집 DB 에서 바뀐 것만 더하고(두 번째 build 는 0건), 이름표 규칙이 바뀌면 통째로 다시 만든다.
2. 검색어는 낱말마다 이어진 글로 찾는다 — 「유상증자」 는 맞고 「증자유상」 은 안 맞는다 · 낱말끼리는 AND.
3. 이름표(종목 · 주제 · 유형) · 날짜로 거르고, 최신순이 기본이다. 고칠 수 있는 잘못은 422 · 색인이 없으면 503 과 할 일.
4. 공시 요약 — 정기보고서는 그 기간의 매출액 · 영업이익 · 순이익(정정본에서 왔으면 그 접수번호) · 배당 공시는 1주당 배당금.
5. 재무 pit — strict 는 기준일 전날까지 접수된 판만 · first 는 원본이 그 전에 나왔으면 가장 이른 판을 쓰고 「뒤에 고쳐짐」 을 알린다.
6. 두 API 모두 로그인 없이는 401.

네트워크 · 실제 수집 DB 를 쓰지 않는다.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import data as data_routes
from app.services import collector_db, data_financials as DF, data_search as DS
from collector import db, disclosure as D, financials as F, search_index as SI


_TICK = iter(range(0, 3600))


def _ts(i: int) -> str:
    return f"2026-10-04T19:{i // 60:02d}:{i % 60:02d}+09:00"


def _disc(conn, rcept_no, report_nm, *, stock="006360", corp="00126380", name="GS건설", ty="A"):
    # 받은 시각을 줄마다 1초씩 다르게 — 색인의 「바뀐 것만」 은 받은 시각으로 가른다
    D.upsert_rows(conn, [D.normalize_item({"corp_code": corp, "corp_name": name, "stock_code": stock, "corp_cls": "Y",
                                            "report_nm": report_nm, "rcept_no": rcept_no, "rcept_dt": rcept_no[:8]},
                                           ty, fetched_at=_ts(next(_TICK)))])


def _fin(conn, rcept_no, name, amount, *, sj="IS", year="2023", rc="11011", fs="CFS", ord_=1,
         dt="2023.01.01 ~ 2023.12.31", stock="006360"):
    F.upsert_rows(conn, [F.normalize_row({
        "rcept_no": rcept_no, "reprt_code": rc, "bsns_year": year, "corp_code": "00126380", "stock_code": stock,
        "fs_div": fs, "sj_div": sj, "account_nm": name, "thstrm_dt": dt, "thstrm_amount": amount, "ord": str(ord_),
        "currency": "KRW"}, fetched_at="2026-10-04T19:00:00+09:00")])


@pytest.fixture()
def env(tmp_path, monkeypatch):
    src = tmp_path / "collector" / "market.sqlite3"
    src.parent.mkdir()
    conn = db.connect(src)
    _disc(conn, "20240321001895", "사업보고서 (2023.12)")
    _disc(conn, "20260630000500", "[기재정정]사업보고서 (2023.12)")
    _disc(conn, "20261002000010", "주요사항보고서(유상증자결정)", ty="B")
    _disc(conn, "20261002000011", "현금ㆍ현물배당결정", ty="I")
    _disc(conn, "20261001000020", "단일판매ㆍ공급계약체결", stock="000660", corp="00164779", name="SK하이닉스", ty="I")
    # 재무 — 원본(2024-03-21)과 정정본(2026-06-30) 두 판
    for rno, rev in (("20240321001895", "13,436,000"), ("20260630000500", "13,400,000")):
        _fin(conn, rno, "매출액", rev, ord_=1)
        _fin(conn, rno, "영업이익", "-386,000", ord_=3)
        _fin(conn, rno, "당기순이익(손실)", "-420,000", ord_=5)
        _fin(conn, rno, "자산총계", "17,000,000", sj="BS", ord_=7, dt="2023.12.31 현재")
    # 정정본만 있는 기간(과거분이 그렇다) — 2024 사업보고서 원본 2025-03-17 · 정정본 2026-07-01
    _disc(conn, "20250317000736", "사업보고서 (2024.12)")
    _fin(conn, "20260701000540", "매출액", "12,000,000", year="2024", dt="2024.01.01 ~ 2024.12.31")
    conn.execute("INSERT INTO dividend (srtn_cd, record_dt, rcept_no, dps, div_kind, div_type, report_nm) "
                 "VALUES ('006360', '20261231', '20261002000011', 300, '결산배당', '현금배당', '현금ㆍ현물배당결정')")
    F.link_first_known(conn)
    # 거래일 달력 두 줄 — 원본 접수 다음 날(03-22)을 휴장으로 두어 「다음 거래일」 이 03-25 로 넘어가는지 본다
    conn.execute("INSERT INTO market_calendar VALUES ('2024-03-22', 0, '시험 휴장', 'rule', '', 'x')")
    conn.execute("INSERT INTO market_calendar VALUES ('2024-03-25', 1, '', 'rule', '', 'x')")
    conn.close()
    out = tmp_path / "collector" / "search.sqlite3"
    SI.build(src_path=src, out_path=out, quiet=True)
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(src))
    monkeypatch.setenv(DS.ENV_SEARCH_DB, str(out))
    app = FastAPI()
    app.include_router(data_routes.router)
    client = TestClient(app)
    return {"src": src, "out": out, "app": app, "client": client}


def _login(env):
    env["app"].dependency_overrides[get_current_user] = lambda: {"id": "u1", "name": "시험", "email": "t@example.com"}
    return env["client"]


def test_build_is_incremental_and_rules_change_rebuilds(env, monkeypatch):
    """TC-DQ-01 · 두 번째 build 는 0건(바뀐 것만) · 규칙 지문이 바뀌면 통째로 다시 만든다 · 롤백 저널이라 보조 파일 없이 읽힌다(DF-67).

    DF-67 — WAL 로 만들었더니 data/ 를 읽기 전용으로 붙인 도커 앱이 「unable to open database file」 로 열지 못했다
    (WAL 은 읽을 때도 -shm 이 있어야 하는데, 만든 뒤 닫으면 지워진다)."""
    c0 = SI.connect(env["out"])
    assert c0.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    c0.close()
    assert not env["out"].with_name(env["out"].name + "-shm").exists()
    assert not env["out"].with_name(env["out"].name + "-wal").exists()
    again = SI.build(src_path=env["src"], out_path=env["out"], quiet=True)
    assert again["disclosure"] == 1                       # 마지막 초 한 건만 다시 본다(같은 문서로 고쳐질 뿐)
    c = SI.connect(env["out"])
    n = c.execute("SELECT COUNT(*) FROM doc").fetchone()[0]
    c.close()
    assert n == 6                                         # 공시 여섯
    monkeypatch.setattr(SI, "rules_fingerprint", lambda: "changed")
    full = SI.build(src_path=env["src"], out_path=env["out"], quiet=True)
    assert full["disclosure"] == 6


def test_phrase_and_and_semantics(env):
    """TC-DQ-02 · 「유상증자」 · 「유상 증자」 는 맞고 「증자유상」 은 안 맞는다 · 영문 낱말도 찾는다."""
    c = _login(env)
    hit = c.get("/api/data/search", params={"q": "유상증자"}).json()
    assert [i["title"] for i in hit["items"]] == ["주요사항보고서(유상증자결정)"]
    assert c.get("/api/data/search", params={"q": "유상 증자"}).json()["total"] == 1
    assert c.get("/api/data/search", params={"q": "증자유상"}).json()["total"] == 0
    assert c.get("/api/data/search", params={"q": "SK하이닉스 공급계약"}).json()["total"] == 1
    assert c.get("/api/data/search", params={"q": "배당 공급계약"}).json()["total"] == 0     # 서로 다른 공시의 낱말 — AND


def test_filters_sort_and_errors(env):
    """TC-DQ-03 · 종목 · 주제 · 유형 · 날짜로 거르고 최신순 · 잘못은 422 · 색인이 없으면 503 과 할 일."""
    c = _login(env)
    j = c.get("/api/data/search", params={"symbol": "006360"}).json()
    dates = [i["published"] for i in j["items"]]
    assert j["total"] == 5 and dates == sorted(dates, reverse=True)
    assert c.get("/api/data/search", params={"topic": "배당"}).json()["total"] == 1
    assert c.get("/api/data/search", params={"dtype": "A", "from": "2025-01-01"}).json()["total"] == 2
    assert c.get("/api/data/search", params={"from": "2026-10-02", "to": "2026-10-02"}).json()["total"] == 2
    one = c.get("/api/data/search", params={"q": "공급계약"}).json()["items"][0]
    assert one["tags"]["symbol"] == ["000660"] and "공급계약" in one["tags"]["topic"]
    assert one["url"].startswith("https://dart.fss.or.kr/dsaf001/main.do?rcpNo=")
    for bad in ({"kind": "blog"}, {"sort": "random"}, {"symbol": "12345"}, {"from": "2026-13-01"},
                {"from": "2026-10-05", "to": "2026-10-01"}, {"dtype": "Z"}, {"q": "!!"}):
        assert c.get("/api/data/search", params=bad).status_code == 422, bad
    assert c.get("/api/data/search", params={"limit": 101}).status_code == 422
    env["out"].unlink()
    r = c.get("/api/data/search", params={"q": "배당"})
    assert r.status_code == 503 and "search_index build" in r.json()["detail"]["hint"]


def test_key_numbers_in_disclosure_summary(env):
    """TC-DQ-04 · 정기보고서는 같은 접수번호 판의 숫자(원본은 원본 값 · 정정은 정정 값) · 배당 공시는 1주당 배당금."""
    c = _login(env)
    items = {i["extra"]["rcept_no"]: i for i in c.get("/api/data/search", params={"symbol": "006360", "limit": 20}).json()["items"]}
    orig = items["20240321001895"]["key_numbers"]
    fixed = items["20260630000500"]["key_numbers"]
    assert (orig["revenue"], orig["same_filing"]) == (13436000, True)
    assert (fixed["revenue"], fixed["operating_income"], fixed["net_income"]) == (13400000, -386000, -420000)
    only_fixed = items["20250317000736"]["key_numbers"]                  # 원본 판 값이 없으면 그 기간 최신 판
    assert (only_fixed["revenue"], only_fixed["same_filing"], only_fixed["rcept_no"]) == (12000000, False, "20260701000540")
    assert items["20261002000011"]["key_numbers"]["dps"] == 300


def test_choose_version_strict_and_first():
    """TC-DQ-05 · strict 는 기준일 전날까지 접수된 판 · first 는 원본이 그 전에 나왔으면 가장 이른 판 + 「뒤에 고쳐짐」."""
    vs = [{"rcept_no": "20240321001895", "known_at": "20240321", "first_known_at": "20240321"},
          {"rcept_no": "20260630000500", "known_at": "20260630", "first_known_at": "20240321"}]
    assert DF.choose_version(vs, "2024-03-21", "strict") == (None, False)          # 접수한 그날은 아직 아니다
    assert DF.choose_version(vs, "2024-03-22", "strict")[0]["rcept_no"] == "20240321001895"
    assert DF.choose_version(vs, "2026-07-01", "strict")[0]["rcept_no"] == "20260630000500"
    assert DF.choose_version(vs, None, "strict")[0]["rcept_no"] == "20260630000500"
    only_fixed = [{"rcept_no": "20260701000540", "known_at": "20260701", "first_known_at": "20250317"}]
    assert DF.choose_version(only_fixed, "2025-06-01", "strict") == (None, False)
    v, revised = DF.choose_version(only_fixed, "2025-06-01", "first")
    assert v["rcept_no"] == "20260701000540" and revised is True
    assert DF.choose_version(only_fixed, "2025-03-17", "first") == (None, False)


def test_financials_api(env):
    """TC-DQ-06 · 재무 API — 기간마다 고른 판 · 처음 공개일 · 정정 표시 · 요약 칸 · 고칠 수 있는 잘못."""
    c = _login(env)
    j = c.get("/api/data/financials", params={"symbol": "006360", "as_of": "2025-06-01", "pit": "first"}).json()
    by_year = {p["bsns_year"]: p for p in j["periods"]}
    assert by_year["2023"]["rcept_no"] == "20240321001895" and by_year["2023"]["key"]["revenue"] == 13436000
    # 1차 규칙 — 접수일 다음 거래일부터(휴장 건너뜀) · 정정 표시는 그 판 자기 제목에서
    assert (by_year["2023"]["available_from"], by_year["2023"]["available_from_approx"]) == ("2024-03-25", False)
    assert by_year["2023"]["amended"] is False
    assert by_year["2024"]["values_revised_after_as_of"] is True and by_year["2024"]["first_known_at"] == "2025-03-17"
    strict = c.get("/api/data/financials", params={"symbol": "006360", "as_of": "2025-06-01"}).json()
    assert [p["bsns_year"] for p in strict["periods"]] == ["2023"]
    latest = c.get("/api/data/financials", params={"symbol": "006360"}).json()
    assert latest["periods"][0]["bsns_year"] == "2024" and latest["periods"][1]["restated"] is True
    assert (latest["periods"][1]["amended"], latest["periods"][1]["revision"]) == (True, "기재정정")
    assert latest["periods"][0]["amended"] is None                      # 그 판이 공시 목록에 없으면 모름
    assert latest["periods"][0]["available_from_approx"] is True        # 달력 밖 → 다음 평일로 어림
    assert latest["periods"][1]["key"]["assets"] == 17000000
    assert c.get("/api/data/financials", params={"symbol": "006360", "pit": "loose"}).status_code == 422
    assert c.get("/api/data/financials", params={"symbol": "006360", "as_of": "2025/06/01"}).status_code == 422
    r = c.get("/api/data/financials", params={"symbol": "006360", "fs": "OFS"})
    assert r.status_code == 404 and "CFS" in r.json()["detail"]["hint"]


def test_login_required(env):
    """TC-DQ-07 · 로그인 없이는 401(수집 자료는 로그인 뒤 · 설계서 7절)."""
    c = env["client"]
    assert c.get("/api/data/search", params={"q": "배당"}).status_code == 401
    assert c.get("/api/data/financials", params={"symbol": "006360"}).status_code == 401


def test_source_filter_and_facets_with_news(env):
    """TC-DQ-09 · 출처 거름(공시 · 정책뉴스 · 언론사 기사) · 출처별 개수는 종류 · 출처 거름을 빼고 센다 · 뉴스는 출처 표시를 싣는다
    · 모르는 출처는 422 (리서치 화면 결정 B + C 해석 1 · 2026-10-05)."""
    from collector import policy_news as PN

    conn = db.connect(env["src"])
    base = {"subtitle": "", "body": "", "publisher": "", "category": "", "kogl_type": "", "embargo_at": "",
            "modified_at": "", "revision": 1}
    rows = [dict(base, news_id="policy:1", source="policy_news", title="유상증자 공시 제도 개선", url="https://www.korea.kr/1",
                 publisher="금융위원회", kogl_type="1", pub_at="2026-10-02T10:00:00+09:00", available_at="2026-10-02T10:00:00+09:00"),
            dict(base, news_id="gdelt:abc", source="gdelt", title="GS건설 유상증자 흥행", url="https://www.example.co.kr/2",
                 publisher="example.co.kr", pub_at="2026-10-03T09:00:00+09:00", available_at="2026-10-03T09:00:00+09:00")]
    conn.execute("BEGIN IMMEDIATE")
    PN.upsert(conn, rows, at="2026-10-05T14:00:00+09:00")
    conn.execute("COMMIT")
    conn.close()
    SI.build(src_path=env["src"], out_path=env["out"], quiet=True)
    c = _login(env)
    j = c.get("/api/data/search", params={"q": "유상증자", "facets": "true"}).json()
    assert j["total"] == 3 and j["facets"]["source"] == {"dart": 1, "policy_news": 1, "gdelt": 1}
    assert j["facets"]["source_labels"]["gdelt"] == "언론사 기사"
    g = c.get("/api/data/search", params={"q": "유상증자", "source": "gdelt", "facets": "true"}).json()
    assert [i["source"] for i in g["items"]] == ["gdelt"] and g["facets"]["source"]["dart"] == 1   # 고른 출처와 상관없이 셋 다
    assert "GDELT Project" in g["items"][0]["extra"]["attribution"]
    p = c.get("/api/data/search", params={"q": "유상증자", "source": "policy_news"}).json()
    assert p["items"][0]["extra"]["attribution"].startswith("정책브리핑(www.korea.kr)") and "facets" not in p
    assert c.get("/api/data/search", params={"source": "naver"}).status_code == 422


def test_tagged_filter_drops_untagged_news(env):
    """TC-DQ-11 · tagged — 공시 + 종목 · 주제 이름표가 붙은 뉴스만 · 이름표 없는 일반 기사는 뺀다 · 개수도 그 거름으로 센다 ·
    기본(꺼짐)은 지금 그대로(2026-10-17 · 모의투자 점검 L4 — 첫 목록 맨 위가 정치 · 사회 기사)."""
    from collector import policy_news as PN

    conn = db.connect(env["src"])
    base = {"subtitle": "", "body": "", "publisher": "", "category": "", "kogl_type": "", "embargo_at": "",
            "modified_at": "", "revision": 1}
    rows = [dict(base, news_id="gdelt:tagged", source="gdelt", title="GS건설 유상증자 흥행", url="https://www.example.co.kr/2",
                 publisher="example.co.kr", pub_at="2026-10-03T09:00:00+09:00", available_at="2026-10-03T09:00:00+09:00"),
            dict(base, news_id="gdelt:plain", source="gdelt", title="선관위 특검 공방 격화", url="https://www.example.co.kr/3",
                 publisher="example.co.kr", pub_at="2026-10-05T09:00:00+09:00", available_at="2026-10-05T09:00:00+09:00")]
    conn.execute("BEGIN IMMEDIATE")
    PN.upsert(conn, rows, at="2026-10-05T14:00:00+09:00")
    conn.execute("COMMIT")
    conn.close()
    SI.build(src_path=env["src"], out_path=env["out"], quiet=True)
    c = _login(env)
    every = c.get("/api/data/search", params={"facets": "true"}).json()
    titles = [i["title"] for i in every["items"]]
    assert "선관위 특검 공방 격화" in titles and every["query"]["tagged"] is False
    assert every["facets"]["source"]["gdelt"] == 2
    only = c.get("/api/data/search", params={"facets": "true", "tagged": "true"}).json()
    kept = [i["title"] for i in only["items"]]
    assert "선관위 특검 공방 격화" not in kept and "GS건설 유상증자 흥행" in kept and only["query"]["tagged"] is True
    assert only["facets"]["source"]["gdelt"] == 1 and only["facets"]["source"]["dart"] == every["facets"]["source"]["dart"]
    assert only["total"] == every["total"] - 1
    # 낱말 · 출처 거름과 함께 써도 같은 뜻
    assert c.get("/api/data/search", params={"source": "gdelt", "tagged": "true"}).json()["total"] == 1


def _add_news(env, rows: list[dict]) -> None:
    """수집 DB 에 뉴스 줄을 넣고 색인을 다시 짓는다 — 줄마다 news_id · source · title · url · pub_at 만 주면 된다."""
    from collector import policy_news as PN

    base = {"subtitle": "", "body": "", "publisher": "example.co.kr", "category": "", "kogl_type": "", "embargo_at": "",
            "modified_at": "", "revision": 1}
    conn = db.connect(env["src"])
    conn.execute("BEGIN IMMEDIATE")
    PN.upsert(conn, [dict(base, available_at=r["pub_at"], **r) for r in rows], at="2026-10-05T14:00:00+09:00")
    conn.execute("COMMIT")
    conn.close()
    SI.build(src_path=env["src"], out_path=env["out"], quiet=True)


def test_facets_count_untagged_news_for_the_switch(env):
    """TC-DQ-12 · 스위치 「이름표 없는 기사까지 보기 (n건 숨김)」 의 수 — `facets.untagged` 는 같은 조건에서 종목 · 주제 이름표가 없는
    뉴스 수다(출처마다 · 공시는 늘 0). tagged 를 켜든 끄든 같은 수 · 켜면 출처 수 = 전체 − untagged · 낱말 · 기간 조건을 따른다
    (2026-10-17 · 리서치 설계 A — 숨긴 것을 수로 밝힌다 · 수는 서버 한 곳에서 센다)."""
    _add_news(env, [
        dict(news_id="gdelt:t1", source="gdelt", title="GS건설 유상증자 흥행", url="https://www.example.co.kr/t1",
             pub_at="2026-10-03T09:00:00+09:00"),
        dict(news_id="gdelt:p1", source="gdelt", title="선관위 특검 공방 격화", url="https://www.example.co.kr/p1",
             pub_at="2026-10-05T09:00:00+09:00"),
        dict(news_id="gdelt:p2", source="gdelt", title="가을 축제 개막 안내", url="https://www.example.co.kr/p2",
             pub_at="2026-09-20T09:00:00+09:00"),
        dict(news_id="policy:p1", source="policy_news", title="청년 정책 설명회 열려", url="https://www.korea.kr/p1",
             pub_at="2026-10-04T10:00:00+09:00", publisher="문화체육관광부", kogl_type="1"),
    ])
    c = _login(env)
    every = c.get("/api/data/search", params={"facets": "true"}).json()
    only = c.get("/api/data/search", params={"facets": "true", "tagged": "true"}).json()
    want = {"dart": 0, "policy_news": 1, "gdelt": 2}
    assert every["facets"]["untagged"] == want and only["facets"]["untagged"] == want
    for s in DS.SOURCES:
        assert only["facets"]["source"][s] == every["facets"]["source"][s] - want[s], s
    assert only["total"] == every["total"] - sum(want.values())
    # 낱말 조건을 따른다 — 「특검」 은 이름표 없는 기사 하나뿐이라 켜면 0건 · 숨긴 수 1
    q = c.get("/api/data/search", params={"facets": "true", "tagged": "true", "q": "특검"}).json()
    assert q["total"] == 0 and q["facets"]["untagged"] == {"dart": 0, "policy_news": 0, "gdelt": 1}
    # 기간 조건을 따른다 — 10-01 부터면 09-20 기사는 세지 않는다
    f = c.get("/api/data/search", params={"facets": "true", "tagged": "true", "from": "2026-10-01"}).json()
    assert f["facets"]["untagged"]["gdelt"] == 1
    # 출처 거름은 개수에서 빼고 센다(종류 칸과 같은 규칙) — 언론사 기사만 골라도 정책뉴스 숨긴 수가 보인다
    g = c.get("/api/data/search", params={"facets": "true", "tagged": "true", "source": "gdelt"}).json()
    assert g["facets"]["untagged"] == want
    assert "facets" not in c.get("/api/data/search", params={"tagged": "true"}).json()


def test_site_name_titles_are_marked(env):
    """TC-DQ-13 · 제목이 사이트 이름뿐인 언론사 기사(「KBS 뉴스」 처럼 같은 제목이 주소 10개 이상 · 3일 이상)는 `site_name_title`
    로 알린다 — 9개 · 하루에 몰린 10개 · 가장 최근 기사보다 30일 넘게 앞선 것은 아니다 · 공시 · 정책뉴스는 늘 아니다 · 색인을 다시
    지으면 다시 센다(2026-10-17 · 모의투자 점검 L11 — 첫 목록 맨 위 열 줄 가운데 여섯이 「KBS 뉴스」)."""
    rows = []
    for i in range(10):            # 사흘에 걸친 10개 — 사이트 이름 제목
        rows.append(dict(news_id=f"gdelt:kbs{i}", source="gdelt", title="KBS 뉴스", url=f"https://news.kbs.co.kr/{i}",
                         pub_at=f"2026-10-0{1 + i % 3}T09:{i:02d}:00+09:00", publisher="kbs.co.kr"))
    for i in range(9):             # 9개 — 아직 아니다
        rows.append(dict(news_id=f"gdelt:huff{i}", source="gdelt", title="허프포스트코리아", url=f"https://huffpost.kr/{i}",
                         pub_at=f"2026-10-0{1 + i % 3}T10:{i:02d}:00+09:00", publisher="huffingtonpost.kr"))
    for i in range(10):            # 하루에 몰린 10개(공지 · 사진 묶음 꼴) — 아니다
        rows.append(dict(news_id=f"gdelt:mtn{i}", source="gdelt", title="공지사항 - 머니투데이방송", url=f"https://mtn.co.kr/{i}",
                         pub_at=f"2026-10-03T11:{i:02d}:00+09:00", publisher="mtn.co.kr"))
    for i in range(10):            # 가장 최근 기사(10-03)보다 30일 넘게 앞선 10개 — 세지 않는다
        rows.append(dict(news_id=f"gdelt:old{i}", source="gdelt", title="씨네21", url=f"https://cine21.com/{i}",
                         pub_at=f"2026-08-0{1 + i % 3}T09:{i:02d}:00+09:00", publisher="cine21.com"))
    rows.append(dict(news_id="gdelt:plain", source="gdelt", title="가을 축제 개막 안내", url="https://www.example.co.kr/plain",
                     pub_at="2026-10-03T12:00:00+09:00"))
    _add_news(env, rows)
    c = _login(env)
    items = c.get("/api/data/search", params={"source": "gdelt", "limit": 100}).json()["items"]
    marked = {i["title"] for i in items if i["site_name_title"]}
    assert marked == {"KBS 뉴스"}, marked
    assert all(i["site_name_title"] is False for i in c.get("/api/data/search", params={"limit": 100}).json()["items"]
               if i["source"] != "gdelt")
    # 색인을 다시 지으면 다시 센다 — 허프포스트코리아가 10개가 되면 알린다
    _add_news(env, [dict(news_id="gdelt:huff9", source="gdelt", title="허프포스트코리아", url="https://huffpost.kr/9",
                         pub_at="2026-10-03T10:09:00+09:00", publisher="huffingtonpost.kr")])
    items = c.get("/api/data/search", params={"source": "gdelt", "limit": 100}).json()["items"]
    assert {i["title"] for i in items if i["site_name_title"]} == {"KBS 뉴스", "허프포스트코리아"}


def test_rules_fingerprint_ignores_line_endings(tmp_path):
    """TC-DQ-08 · 규칙 지문은 줄 끝(CRLF · LF)에 따라 바뀌지 않는다 — 글이 바뀌면 바뀐다(DF-68).

    Windows 의 `core.autocrlf=true` 는 저장소의 LF 파일을 작업 트리에 CRLF 로 내놓는다. 바이트 그대로 지문을 내면 규칙이
    그대로인데도 pull · 브랜치 바꾸기만으로 색인을 통째로 다시 만든다(2026-10-05 12:30 회차 search 447초).
    """
    lf, crlf, other = tmp_path / "lf.py", tmp_path / "crlf.py", tmp_path / "other.py"
    lf.write_bytes(b"A = 1\nB = 2\n")
    crlf.write_bytes(b"A = 1\r\nB = 2\r\n")
    other.write_bytes(b"A = 1\nB = 3\n")
    assert SI.files_fingerprint([lf]) == SI.files_fingerprint([crlf])
    assert SI.files_fingerprint([lf]) != SI.files_fingerprint([other])
    assert SI.files_fingerprint([tmp_path / "없음.py"]) == SI.files_fingerprint([tmp_path / "없음2.py"])   # 없는 파일은 같은 자리 표시
