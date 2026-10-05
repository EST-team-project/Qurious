"""정책브리핑 정책뉴스 시험 (TC-NW) — `collector/policy_news.py` (목표 기능 ① W7 · 설계서 5.1.5).

여기서 지키는 것 —
1. 응답 읽기 — 시각 꼴(MM/DD/YYYY → KST ISO) · HTML 본문 → 글 · 부제 셋 잇기 · 볼 수 있게 된 시각 = 승인 · 엠바고 가운데 늦은 것.
2. **본문은 공공누리 제1유형 기사만** — 기사마다 KoglType 이 따로 온다. 다른 유형 · 빈칸이면 제목 · 부제 · 주소만.
3. 오류 응답 — 관문 코드 30(등록 안 된 키 · 주소 안내) · 22(하루 한도 → 멈춤 예외) · 결과 코드 98(창 3일 초과)을 조용히 0건으로 두지 않는다.
4. 쌓기 — 같은 판을 다시 받으면 그대로 · 고친 판이면 내용 · updated_at 만(처음 받은 시각 그대로) · 옛 판이 늦게 와도 되돌리지 않는다.
5. 받기 — 고정 3일 창(실행마다 이름이 같다) · 이미 받은 창은 부르지 않는다 · 최근 것부터 · 하루 한도에서 멈춤 · 매일은 3일 한 번.
6. 검색 색인 — 뉴스 문서는 제목 · 부제 · 주소 · 출처 표시만(본문은 색인에 넣지 않는다) · 이름표는 제목 · 부제에서.

네트워크 · 실제 수집 DB 를 쓰지 않는다. 응답은 2026-10-05 에 받은 실제 응답의 칸 이름 · 꼴만 따른 지어낸 글이다.
"""
from __future__ import annotations

from datetime import date

import pytest
import requests

from collector import db, policy_news as P, search_index as S, tagging as T


def _item(nid="148972963", title="온라인 불법 대부광고 신고시 포상금", kogl="1", approve="10/02/2026 17:47:00",
          embargo="", modify="10/02/2026 17:47:23", rev="21", body="<p>모든 온라인 대부광고에 &quot;사전심의&quot;</p><p>둘째 문단<br>이어짐</p>",
          sub1="'불법사금융 근절 TF' 개최<br>피해자 신고 독려", ctype="H", minister="국무조정실", group="policy"):
    return (f"<NewsItem><NewsItemId>{nid}</NewsItemId><ContentsStatus>U</ContentsStatus><ModifyId>{rev}</ModifyId>"
            f"<ModifyDate>{modify}</ModifyDate><ApproveDate>{approve}</ApproveDate><EmbargoDate>{embargo}</EmbargoDate>"
            f"<GroupingCode>{group}</GroupingCode><Title><![CDATA[{title}]]></Title><SubTitle1><![CDATA[{sub1}]]></SubTitle1>"
            f"<SubTitle2></SubTitle2><SubTitle3></SubTitle3><ContentsType>{ctype}</ContentsType>"
            f"<DataContents><![CDATA[{body}]]></DataContents><MinisterCode>{minister}</MinisterCode>"
            f"<OriginalUrl>https://www.korea.kr/news/policyNewsView.do?newsId={nid}&amp;call_from=openData</OriginalUrl>"
            f"<KoglType>{kogl}</KoglType></NewsItem>")


def _resp(*items: str) -> bytes:
    return ("<?xml version='1.0' encoding='UTF-8'?><response><header><resultCode>0</resultCode>"
            f"<resultMsg>NORMAL_SERVICE</resultMsg></header><body>{''.join(items)}<totalCount>{len(items)}</totalCount>"
            "</body></response>").encode("utf-8")


GATEWAY_30 = ("<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg><returnAuthMsg>"
              "SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg><returnReasonCode>30</returnReasonCode>"
              "</cmmMsgHeader></OpenAPI_ServiceResponse>").encode()
GATEWAY_22 = GATEWAY_30.replace(b">30<", b">22<").replace(b"SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
                                                          b"LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR")


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "m.sqlite3")
    yield c
    c.close()


def test_parse_item_fields_times_and_text():
    """TC-NW-01 · 시각 꼴 → KST ISO · HTML 본문 → 글(문단 · <br> 은 줄바꿈 · 문자 참조 풂) · 부제 · 엠바고가 늦으면 볼 수 있는 시각은 엠바고."""
    total, rows = P.parse(_resp(_item(embargo="10/03/2026 09:00:00")))
    assert total == 1 and len(rows) == 1
    r = rows[0]
    assert r["news_id"] == "policy:148972963" and r["source"] == "policy_news"
    assert r["pub_at"] == "2026-10-02T17:47:00+09:00" and r["embargo_at"] == "2026-10-03T09:00:00+09:00"
    assert r["available_at"] == "2026-10-03T09:00:00+09:00"            # 엠바고 기사는 승인 뒤에도 게시 전
    assert r["modified_at"] == "2026-10-02T17:47:23+09:00" and r["revision"] == 21
    assert r["body"] == '모든 온라인 대부광고에 "사전심의"\n둘째 문단\n이어짐'
    assert r["subtitle"] == "'불법사금융 근절 TF' 개최\n피해자 신고 독려"
    assert r["url"].endswith("newsId=148972963&call_from=openData") and r["publisher"] == "국무조정실"
    _, rows = P.parse(_resp(_item()))
    assert rows[0]["available_at"] == rows[0]["pub_at"]                  # 엠바고가 없으면 승인 시각


def test_html_text_keeps_original_spacing_and_drops_footer():
    """TC-NW-09 · 낱말을 잘게 나눈 <span> 사이에 띄어쓰기를 만들지 않는다 · 표 칸은 띄운다 · 끝의 이용 안내 문단은 지운다(출처 표시는 따로)."""
    raw = ('<p><span style="a">TV</span><span>는 3 </span><span>일 보도했습니다</span>.</p>'
           "<table><tr><td>구분</td><td>내용</td></tr></table>"
           "<p>정책브리핑의 자료는 「공공누리 제1유형:출처표시」의 조건에 따라 자유롭게 이용이 가능합니다. 다만, 사진의 경우 "
           "제3자에게 저작권이 있으므로 사용할 수 없습니다. &lt;자료출처=정책브리핑 www.korea.kr&gt;</p>")
    assert P.html_to_text(raw) == "TV는 3 일 보도했습니다.\n구분 내용"


def test_body_only_for_kogl_type_1_and_missing_title_skipped():
    """TC-NW-02 · 본문은 공공누리 제1유형만 — 제4유형 · 빈칸이면 제목 · 부제 · 주소만 · 제목 없는 기사는 버린다."""
    _, rows = P.parse(_resp(_item(nid="1", kogl="1"), _item(nid="2", kogl="4"), _item(nid="3", kogl=""),
                            _item(nid="4", title="")))
    by = {r["news_id"]: r for r in rows}
    assert set(by) == {"policy:1", "policy:2", "policy:3"}
    assert by["policy:1"]["body"] and by["policy:2"]["body"] == "" and by["policy:3"]["body"] == ""
    assert by["policy:2"]["title"] and by["policy:2"]["url"] and by["policy:2"]["kogl_type"] == "4"


def test_error_responses_are_not_silent_zero():
    """TC-NW-03 · 관문 30 은 주소 · 신청 안내와 함께 · 22 는 하루 한도 예외 · 결과 코드 98(창 3일 초과)도 예외."""
    with pytest.raises(P.PolicyNewsError) as e:
        P.parse(GATEWAY_30)
    assert e.value.code == "30" and "policyNewsService2" in str(e.value) and not isinstance(e.value, P.PolicyNewsQuota)
    with pytest.raises(P.PolicyNewsQuota):
        P.parse(GATEWAY_22)
    bad = _resp().replace(b"<resultCode>0</resultCode>", b"<resultCode>98</resultCode>")
    with pytest.raises(P.PolicyNewsError) as e:
        P.parse(bad)
    assert e.value.code == "98"


def test_upsert_same_changed_and_late_old_revision(conn):
    """TC-NW-04 · 같은 판은 그대로 · 고친 판은 내용 · updated_at 만(처음 받은 시각 그대로) · 옛 판이 늦게 와도 되돌리지 않는다."""
    _, v21 = P.parse(_resp(_item(rev="21")))
    _, v22 = P.parse(_resp(_item(rev="22", title="온라인 불법 대부광고 신고시 포상금 지급")))
    conn.execute("BEGIN IMMEDIATE")
    assert P.upsert(conn, v21, at="2026-10-05T14:00:00+09:00") == {"new": 1, "changed": 0, "same": 0}
    assert P.upsert(conn, v21, at="2026-10-05T14:10:00+09:00") == {"new": 0, "changed": 0, "same": 1}
    assert P.upsert(conn, v22, at="2026-10-06T12:30:00+09:00") == {"new": 0, "changed": 1, "same": 0}
    assert P.upsert(conn, v21, at="2026-10-06T12:40:00+09:00") == {"new": 0, "changed": 0, "same": 1}
    conn.execute("COMMIT")
    row = conn.execute("SELECT title, revision, fetched_at, updated_at FROM news_item").fetchone()
    assert tuple(row) == ("온라인 불법 대부광고 신고시 포상금 지급", 22, "2026-10-05T14:00:00+09:00", "2026-10-06T12:30:00+09:00")


def test_grid_windows_are_stable_and_capped():
    """TC-NW-05 · 고정 창 — 시작일이 달라도 창 이름이 같고(이미 받은 창을 알아본다) · 3일을 넘지 않으며 · 끝날에서 자른다."""
    a = P.grid_windows(date(2020, 1, 1), date(2020, 1, 20))
    b = P.grid_windows(date(2020, 1, 5), date(2020, 1, 20))
    assert set(b) <= set(a)
    assert all((e - s).days <= 2 for s, e in a) and a[-1][1] == date(2020, 1, 20)
    assert all(a[i + 1][0] == a[i][1].fromordinal(a[i][1].toordinal() + 1) for i in range(len(a) - 1))   # 빈틈 없음
    assert a[0][0] <= date(2020, 1, 1) <= a[0][1]


class _Resp:
    def __init__(self, content: bytes, status: int = 200):
        self.content, self.status_code = content, status


class _Session:
    """정해 둔 응답을 차례로 준다 — 부른 창을 적어 둔다."""

    def __init__(self, plan):
        self.plan, self.calls = plan, []

    def get(self, url, params=None, timeout=None):
        assert url.endswith("policyNewsService2/policyNewsList2")
        self.calls.append((params["startDate"], params["endDate"]))
        step = self.plan(params["startDate"]) if callable(self.plan) else self.plan.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def test_backfill_skips_kept_newest_first_and_stops_on_quota(conn, monkeypatch):
    """TC-NW-06 · 과거분 — 이미 받은 창은 부르지 않고 · 최근 창부터 · 일시 오류는 쉬었다 다시 · 하루 한도면 그 자리에서 멈춘다."""
    monkeypatch.setattr(P.config, "portal_key", lambda: "TESTKEY")
    monkeypatch.setattr(P, "SLEEP", 0)
    wins = P.grid_windows(date(2020, 1, 1), date(2020, 1, 12))          # 창 넷
    conn.execute("BEGIN IMMEDIATE")
    P.raw_store.save(conn, P.SOURCE, P.window_target(*wins[-1]), _resp(), http_status=200)   # 맨 뒤 창은 이미 받음
    conn.execute("COMMIT")
    seq = {f"{wins[2][0]:%Y%m%d}": [requests.ConnectionError("reset"), _Resp(_resp(_item(nid="9")))],
           f"{wins[1][0]:%Y%m%d}": [_Resp(GATEWAY_22, 403)]}
    sess = _Session(lambda start: seq[start].pop(0))
    waits = []
    r = P.backfill(conn, date(2020, 1, 1), date(2020, 1, 12), session=sess, sleep=waits.append)
    assert [c[0] for c in sess.calls] == [f"{wins[2][0]:%Y%m%d}"] * 2 + [f"{wins[1][0]:%Y%m%d}"]
    assert waits == [10]
    assert (r["todo"], r["windows"], r["new"], r["quota"], r["left"]) == (3, 1, 1, True, 2)
    sess2 = _Session(lambda start: _Resp(_resp()))
    P.backfill(conn, date(2020, 1, 1), date(2020, 1, 12), session=sess2, sleep=waits.append)
    assert [c[0] for c in sess2.calls] == [f"{wins[1][0]:%Y%m%d}", f"{wins[0][0]:%Y%m%d}"]   # 받은 창 둘은 다시 안 부름


def test_daily_one_call_for_three_days_and_window_split(conn, monkeypatch):
    """TC-NW-07 · 매일은 오늘까지 3일 한 번 · 7일이면 3일 창 셋(넘지 않게) · 원문 이름은 daily/."""
    monkeypatch.setattr(P.config, "portal_key", lambda: "TESTKEY")
    monkeypatch.setattr(P, "SLEEP", 0)
    sess = _Session(lambda start: _Resp(_resp(_item())))
    r = P.daily(conn, date(2026, 10, 5), session=sess)
    assert sess.calls == [("20261003", "20261005")] and (r["calls"], r["new"]) == (1, 1)
    sess = _Session(lambda start: _Resp(_resp(_item())))
    r = P.daily(conn, date(2026, 10, 5), days=7, session=sess)
    assert sess.calls == [("20261003", "20261005"), ("20260930", "20261002"), ("20260929", "20260929")]
    assert r["same"] == 3
    # 원문 이름(같은 초에 두 번 받으면 기본 키 — 받은 시각 — 가 같아 한 줄로 덮이므로 이름 모음으로 본다)
    assert {r[0] for r in conn.execute("SELECT target FROM raw_response WHERE source='policy_news'")} == {
        "daily/20261003-20261005", "daily/20260930-20261002", "daily/20260929-20260929"}


def test_reparse_from_kept_raw_without_network(conn):
    """TC-NW-10 · 받아 둔 원문만으로 다시 읽는다 — 처음은 새로 · 다시 하면 그대로 · 옛 규칙으로 쓴 본문이면 고친다(받은 시각 그대로)."""
    conn.execute("BEGIN IMMEDIATE")
    P.raw_store.save(conn, P.SOURCE, "window/20261001-20261003", _resp(_item(body="<span>TV</span><span>는</span>")),
                     http_status=200)
    conn.execute("COMMIT")
    assert P.reparse(conn) == {"raws": 1, "new": 1, "changed": 0, "same": 0}
    assert P.reparse(conn)["same"] == 1
    first = conn.execute("SELECT fetched_at FROM news_item").fetchone()[0]
    conn.execute("UPDATE news_item SET body='TV 는'")                       # 옛 규칙(태그 → 띄어쓰기)으로 쓴 본문
    assert P.reparse(conn)["changed"] == 1
    assert tuple(conn.execute("SELECT body, fetched_at FROM news_item").fetchone()) == ("TV는", first)


def test_search_doc_has_attribution_and_no_body_and_tags_from_subtitle():
    """TC-NW-08 · 검색 문서 — 제목 · 부제 · 주소 · 출처 표시(정책브리핑 · 공공누리)만 · 본문은 색인에 넣지 않는다 · 이름표는 제목 · 부제에서."""
    _, rows = P.parse(_resp(_item(title="대출 시장 점검 회의", sub1="한국은행 기준금리 결정에 따라<br>시장 점검")))
    row = dict(rows[0], fetched_at="2026-10-05T14:00:00+09:00", updated_at="2026-10-05T14:00:00+09:00")
    d = S.news_doc(row)
    assert d["doc_id"] == "N:policy:148972963" and d["kind"] == "news" and d["source"] == "policy_news"
    assert d["summary"] == "한국은행 기준금리 결정에 따라 · 시장 점검"
    assert d["published"] == row["available_at"] == "2026-10-02T17:47:00+09:00"   # 게시일 = 볼 수 있게 된 시각
    assert "모든 온라인" not in d["summary"] + d["extra"] + d["title"]           # 본문은 색인 문서에 없다
    assert '"attribution": "정책브리핑(www.korea.kr) · 공공누리 제1유형"' in d["extra"]
    assert any(t[0] == "topic" and t[1] == "금리" for t in T.news_tags(row, [], []))   # 제목에 없고 부제에만 있는 말
