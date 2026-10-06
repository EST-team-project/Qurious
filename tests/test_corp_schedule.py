"""주주총회 · 배당금 지급 일정 시험 (TC-CS) — `collector/corp_schedule.py` (목표 기능 ① W7 · 설계서 5.2.4 <표 15>).

여기서 지키는 것 —
1. 소집결의 본문 세 꼴을 읽는다 — 거래소 서식(일시 / 날짜 / 값 + 다음 줄 시간) · 정정본(앞에 정정 표 · 뒤에 고친 본문) · 리츠 서식.
2. 시각 글 꼴(오전 10시 · 오후 2시 30분 · 10:00 · 09 : 00)을 HH:MM 으로 · 못 읽으면 빈칸.
3. 배당금 지급일은 번호 붙은 본문 줄이 먼저 · 본문이 「-」 이면 정정 표의 정정후 · 둘 다 없으면 빈칸(추측하지 않는다).
4. 달력 일정 — 정정 공시가 원 공시를 대신한다(회의일을 바꾼 정정이면 옛 날짜가 남지 않는다) · 배당 지급은 배당 표가 고른 판만.
5. 받아 둔 원문에서 읽기 — 다시 돌려도 늘지 않는다 · 본문 받기는 이미 받은 것을 다시 부르지 않는다.
6. 과거분 받기(`backfill`) — 접수일 구간 안만 · 최근 것부터 · 호출 상한(다시 부른 것 포함) · 일시 오류는 쉬었다 다시 부르고
   그래도 안 되면 그 건만 건너뜀 · 하루 한도면 그 자리에서 멈춤. 매일 단계는 오류를 그대로 올린다(러너가 🟡).

네트워크 · 실제 수집 DB 를 쓰지 않는다. 본문 글은 2026-10-05 에 받은 실제 공시 셋(프롬바이오 · 크라우드웍스 · 코람코더원리츠)을
`dart.flatten` 한 줄 그대로 옮겼다(안건 · 장소는 줄였다).
"""
from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest
import requests

from collector import corp_schedule as C, db, disclosure as D, raw_store

KRX_FORM = [
    "프롬바이오/주주총회소집결의/(2026.10.02)주주총회소집결의(임시주주총회) 주주총회소집 결의 1. 일시\t날짜\t2026-11-10",
    "시간\t오전 10시",
    "2. 장소\t경기도 수원시 영통구 신원로 88",
    "3. 의결권행사기준일\t2026-10-19",
    "4. 이사회결의일(결정일)\t2026-10-02",
    "-주주총회 구분\t임시주주총회",
    "【주주총회 안건 세부내역】 번호\t회의목적사항\t비고",
    "1\t정관일부 변경의 건\t-",
    "2\t이사 선임의 건\t-",
    "3\t감사 선임의 건\t-",
]

CORRECTION = [
    "크라우드웍스/주주총회소집결의/(2026.10.02)주주총회소집결의(임시주주총회) 정정신고(보고) 정정일자\t2026-10-02",
    "1. 정정관련 공시서류\t주주총회소집 결의",
    "2. 정정관련 공시서류제출일\t2026-07-28",
    "3. 정정사유\t임시주주총회 안건 확정",
    "정정항목\t정정전\t정정후",
    "주주총회 안건 세부내역\t미확정\t확정(하기 공시 참조)",
    "주주총회소집 결의 1. 일시\t날짜\t2026-10-20",
    "시간\t10:00",
    "2. 장소\t서울특별시 강남구 테헤란로 309",
    "3. 의결권행사기준일\t2026-08-12",
    "【주주총회 안건 세부내역】 번호\t회의목적사항\t비고",
    "1\t사외이사 장은기 선임의 건\t-",
    "사외이사선임 세부내역 성명\t출생년월\t임기",
    "장은기\t1973-10\t3",
]

REIT_FORM = [
    "코람코더원리츠/주주총회소집결의/(2026.02.02)주주총회소집결의 주주총회소집 결의 1. 구분\t정기주주총회",
    "2. 일시\t2026-02-24\t09 : 00",
    "3. 장소\t서울시 강남구 테헤란로 425",
    "4. 의안 주요내용\t제1호 의안 : 제28기 재무제표 승인의 건 제2호 의안 : 제28기 현금배당 결의의 건",
    "5. 이사회결의일(결정일)\t2026-02-02",
]


def test_parse_agm_three_forms():
    """TC-CS-01 · 거래소 서식 · 정정본 · 리츠 서식에서 회의일 · 시각 · 구분 · 장소 · 안건을 읽는다."""
    a = C.parse_agm(KRX_FORM, "주주총회소집결의 (임시주주총회)")
    assert (a["date"], a["time"], a["label"]) == ("2026-11-10", "10:00", "임시주주총회")
    assert a["place"].startswith("경기도 수원시") and a["agenda"] == ["정관일부 변경의 건", "이사 선임의 건", "감사 선임의 건"]
    assert a["orig_filed"] == ""
    b = C.parse_agm(CORRECTION, "[기재정정]주주총회소집결의 (임시주주총회)")
    assert (b["date"], b["time"], b["orig_filed"]) == ("2026-10-20", "10:00", "2026-07-28")
    assert b["agenda"] == ["사외이사 장은기 선임의 건"]           # 다음 표(사외이사선임 세부내역)는 안건이 아니다
    r = C.parse_agm(REIT_FORM, "주주총회소집결의")
    assert (r["date"], r["time"], r["label"]) == ("2026-02-24", "09:00", "정기주주총회")   # 구분은 본문 칸에서
    assert r["agenda"][0].startswith("제1호 의안")


def test_parse_agm_correction_table_only_uses_after_value():
    """TC-CS-02 · 정정 표에만 일시가 있으면(정정전 · 정정후) 정정후를 · 본문의 다른 날짜(머리 · 기준일)는 회의일이 아니다."""
    lines = ["OO/주주총회소집결의/(2026.03.05) 정정신고(보고) 정정일자\t2026-03-05",
             "2. 정정관련 공시서류제출일\t2026-02-20",
             "정정항목\t정정전\t정정후",
             "1. 일시\t2026-03-20 09:00\t2026-03-27 10:00",
             "3. 의결권행사기준일\t2025-12-31"]
    p = C.parse_agm(lines)
    assert (p["date"], p["orig_filed"]) == ("2026-03-27", "2026-02-20")
    assert p["time"] == "10:00"                                   # 날짜와 같은 칸의 시각(정정후 칸)
    assert C.parse_agm(["주주총회소집 결의 1. 일시\t미정", "3. 의결권행사기준일\t2026-10-19"])["date"] == ""


@pytest.mark.parametrize("text,want", [("오전 10시", "10:00"), ("오후 2시 30분", "14:30"), ("10:00", "10:00"),
                                       ("09 : 00", "09:00"), ("오후 12시", "12:00"), ("09", "09:00"), ("-", ""),
                                       ("미정", ""), ("", ""), ("25", "")])
def test_clock_forms(text, want):
    """TC-CS-03 · 시각 글 꼴 → HH:MM · 시간 칸에 숫자만 있으면 그 시 정각(비츠로시스 「시간 / 09」) · 못 읽으면 빈칸."""
    assert C._clock(text) == want


def test_parse_dividend_pay_main_correction_dash():
    """TC-CS-04 · 지급일 — 본문 줄이 먼저 · 본문이 「-」 이면 정정 표의 정정후 · 둘 다 없으면 빈칸 + 칸 글."""
    main = ["6. 배당기준일\t2026-10-19", "7. 배당금지급 예정일자\t2026-11-09", "8. 주주총회 개최여부\t미개최"]
    assert C.parse_dividend_pay(main) == {"date": "2026-11-09", "text": ""}
    corr = ["정정항목\t정정전\t정정후", "배당금지급 예정일자 확정\t-\t2020-04-24",
            "6. 배당기준일\t2019-12-31", "7. 배당금지급 예정일자\t-"]
    assert C.parse_dividend_pay(corr)["date"] == "2020-04-24"
    dash = ["6. 배당기준일\t2025-12-31", "7. 배당금지급 예정일자\t-",
            "- 상기 7항의 배당금지급 예정일자는 정기주주총회 결의일로부터 1개월 이내입니다. (긴 안내 글은 라벨이 아니다)"]
    assert C.parse_dividend_pay(dash) == {"date": "", "text": "-"}


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "m.sqlite3")
    yield c
    c.close()


def _disc(conn, rcept_no, report_nm, code="114090", name="GKL"):
    D.upsert_rows(conn, [D.normalize_item({"corp_code": "00000001", "corp_name": name, "stock_code": code,
                                            "corp_cls": "Y", "report_nm": report_nm, "rcept_no": rcept_no,
                                            "rcept_dt": rcept_no[:8]}, "I", fetched_at="2026-10-05T11:00:00+09:00")])


def _zip_doc(rows):
    """`dart.flatten` 이 그대로 눕히는 작은 본문 — 표 한 줄 = <tr>, 칸 = <td>."""
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r.split("\t")) + "</tr>" for r in rows)
    xml = f'<?xml version="1.0" encoding="utf-8"?><html><body><table>{body}</table></body></html>'.encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("doc.xml", xml)
    return buf.getvalue()


def _raw(conn, target, rows):
    conn.execute("BEGIN IMMEDIATE")
    raw_store.save(conn, "dart", target, _zip_doc(rows), http_status=200)
    conn.execute("COMMIT")


def test_events_correction_replaces_original_and_dividend_uses_chosen_version(conn):
    """TC-CS-05 · 회의일을 바꾼 정정이 원 공시를 대신한다 · 정정이 둘이면 마지막 · 배당 지급은 배당 표가 고른 판만 · 같은 종목 같은 날은 하나."""
    _disc(conn, "20260220000001", "주주총회소집결의")
    _raw(conn, "agm/20260220000001", ["1. 일시\t2026-03-20\t09:00"])
    _disc(conn, "20260305000002", "[기재정정]주주총회소집결의")
    _raw(conn, "agm/20260305000002", ["2. 정정관련 공시서류제출일\t2026-02-20", "1. 일시\t2026-03-27\t10:00"])
    _disc(conn, "20260310000003", "[기재정정]주주총회소집결의")
    # 두 번째 정정은 원 공시가 아니라 앞 정정(03-05)을 가리킨다 — 실제 꼴(비츠로시스 08-31 → 09-03 → 09-08 → 09-17)
    _raw(conn, "agm/20260310000003", ["2. 정정관련 공시서류제출일\t2026-03-05", "1. 일시\t2026-03-31\t10:00"])
    _disc(conn, "20260220000009", "주주총회소집결의", code="034230", name="파라다이스")       # 다른 종목 · 같은 날 접수
    _raw(conn, "agm/20260220000009", ["1. 일시\t2026-03-27\t09:00"])
    conn.execute("INSERT INTO dividend (srtn_cd, record_dt, rcept_no, itms_nm, div_kind, dps) VALUES "
                 "('114090', '20251231', '20260220000101', 'GKL', '결산배당', 500)")
    _raw(conn, "dividend/20260220000101", ["7. 배당금지급 예정일자\t2026-04-17"])
    _raw(conn, "dividend/20260210000100", ["7. 배당금지급 예정일자\t2026-04-10"])   # 배당 표가 고르지 않은 옛 판
    out = C.build(conn)
    assert out == {"agm": 4, "agm_dated": 4, "dividend_pay": 1, "dividend_dated": 1}
    ev = C.schedule_events(conn, date(2026, 3, 25), "x")
    agm = sorted((e[5], e[2], e[3], e[8]) for e in ev if e[1] == "agm")
    assert agm == [("034230", "2026-03-27", "09:00", "scheduled"), ("114090", "2026-03-31", "10:00", "scheduled")]
    pay = [(e[5], e[2], e[6]) for e in ev if e[1] == "dividend_pay"]
    assert pay == [("114090", "2026-04-17", "GKL 배당금 지급(결산배당)")]
    assert all(e[9] == "dart" and e[10] for e in ev)                      # 근거 접수번호가 늘 붙는다
    # 배당 정정이 들어와 배당 표가 새 판을 고르면, 앞서 읽어 둔 옛 판 줄(04-17)은 달력에서 빠진다
    conn.execute("UPDATE dividend SET rcept_no='20260305000102' WHERE srtn_cd='114090'")
    _raw(conn, "dividend/20260305000102", ["정정항목\t정정전\t정정후", "배당금지급 예정일자 변경\t2026-04-17\t2026-04-24",
                                           "7. 배당금지급 예정일자\t2026-04-24"])
    assert C.build(conn)["dividend_pay"] == 1
    ev = C.schedule_events(conn, date(2026, 3, 25), "x")
    assert [(e[5], e[2]) for e in ev if e[1] == "dividend_pay"] == [("114090", "2026-04-24")]


def test_withdrawn_or_undecided_correction_removes_meeting_and_bad_pay_date_dropped(conn):
    """TC-CS-07 · 철회 정정 · 「일시 미정」 정정이면 원 공시의 옛 날짜도 달력에 없다 · 기준일보다 앞선 지급일은 버린다(제출 오기)."""
    _disc(conn, "20260528000001", "주주총회소집결의 (임시주주총회)")
    _raw(conn, "agm/20260528000001", ["1. 일시\t날짜\t2026-06-30", "시간\t오전 9시"])
    _disc(conn, "20260826000002", "[기재정정]주주총회소집결의 (임시주주총회-철회)")
    _raw(conn, "agm/20260826000002", ["2. 정정관련 공시서류제출일\t2026-05-28", "1. 일시\t날짜\t-", "시간\t-"])
    _disc(conn, "20260729000003", "주주총회소집결의 (임시주주총회)", code="210540", name="디에스케이")
    _raw(conn, "agm/20260729000003", ["1. 일시\t날짜\t2026-09-30", "시간\t오전9시"])
    _disc(conn, "20260915000004", "[기재정정]주주총회소집결의", code="210540", name="디에스케이")
    _raw(conn, "agm/20260915000004", ["2. 정정관련 공시서류제출일\t2026-07-29",
                                      "1. 일시  날짜  시간\t2026-09-30 오전9시\t- 미정", "1. 일시\t날짜\t-", "시간\t미정"])
    conn.execute("INSERT INTO dividend (srtn_cd, record_dt, rcept_no, itms_nm, div_kind, dps) VALUES "
                 "('006040', '20260831', '20260907000101', '동원산업', '중간배당', 600)")
    _raw(conn, "dividend/20260907000101", ["7. 배당금지급 예정일자\t2025-09-11"])     # 해를 잘못 적음
    C.build(conn)
    label = conn.execute("SELECT label FROM corp_schedule WHERE rcept_no='20260826000002'").fetchone()[0]
    assert label == "임시주주총회(철회)"
    ev = C.schedule_events(conn, date(2026, 6, 1), "x")
    assert [e for e in ev if e[1] == "agm"] == []                        # 철회 · 미정 — 옛 날짜(06-30 · 09-30)가 남지 않는다
    assert [e for e in ev if e[1] == "dividend_pay"] == []
    detail = conn.execute("SELECT detail FROM corp_schedule WHERE rcept_no='20260907000101'").fetchone()[0]
    assert "2025-09-11" in detail and "앞서" in detail


def test_same_day_new_resolution_is_not_merged_into_correction_chain(conn):
    """TC-CS-08 · 같은 날 낸 정정과 새 소집결의는 다른 회의일 수 있다 — 아무 정정도 가리키지 않은 날의 소집결의는 묶지 않는다
    (2026-10-05 실측 프리티: 09-17 에 「08-11 소집결의」 의 정정(→ 10-02)과 새 소집결의(→ 11-02)를 함께 냈다).
    원 공시가 창 밖이라 표에 없어도, 같은 원 공시를 가리키는 정정끼리는 묶인다."""
    _disc(conn, "20260811000001", "주주총회소집결의", code="006490", name="프리티")
    _raw(conn, "agm/20260811000001", ["1. 일시\t2026-09-22\t09:00"])
    _disc(conn, "20260904000002", "[기재정정]주주총회소집결의", code="006490", name="프리티")
    _raw(conn, "agm/20260904000002", ["2. 정정관련 공시서류제출일\t2026-08-11", "1. 일시\t2026-10-12\t09:00"])
    _disc(conn, "20260917000003", "[기재정정]주주총회소집결의", code="006490", name="프리티")
    _raw(conn, "agm/20260917000003", ["2. 정정관련 공시서류제출일\t2026-08-11", "1. 일시\t2026-10-02\t09:00"])
    _disc(conn, "20260917000004", "주주총회소집결의", code="006490", name="프리티")         # 같은 날 · 새 회의
    _raw(conn, "agm/20260917000004", ["1. 일시\t2026-11-02\t09:00"])
    # 원 공시(07-01)가 창 밖이라 표에 없다 — 같은 원 공시를 가리키는 정정 둘은 묶여 마지막 것만
    _disc(conn, "20260827000005", "[기재정정]주주총회소집결의", code="083660", name="CSA 코스믹")
    _raw(conn, "agm/20260827000005", ["2. 정정관련 공시서류제출일\t2026-07-01", "1. 일시\t2026-11-06\t10:00"])
    _disc(conn, "20260929000006", "[기재정정]주주총회소집결의", code="083660", name="CSA 코스믹")
    _raw(conn, "agm/20260929000006", ["2. 정정관련 공시서류제출일\t2026-07-01", "1. 일시\t2026-11-03\t10:00"])
    C.build(conn)
    ev = sorted((e[5], e[2]) for e in C.schedule_events(conn, date(2026, 9, 20), "x") if e[1] == "agm")
    assert ev == [("006490", "2026-10-02"), ("006490", "2026-11-02"), ("083660", "2026-11-03")]


def test_build_is_incremental_and_fetch_skips_kept_raw(conn, monkeypatch):
    """TC-CS-06 · 다시 읽어도 늘지 않는다 · 창 밖 · 이미 받은 본문은 부르지 않는다."""
    _disc(conn, "20261002000001", "주주총회소집결의 (임시주주총회)")
    _raw(conn, "agm/20261002000001", ["1. 일시\t날짜\t2026-11-10", "시간\t오전 10시"])
    _disc(conn, "20261001000002", "주주총회소집결의")                      # 본문 아직 없음 → 받을 것
    _disc(conn, "20260101000003", "주주총회소집결의")                      # 창(60일) 밖
    assert C.build(conn)["agm"] == 1
    assert C.build(conn)["agm"] == 0                                      # 두 번째는 0 — 늘지 않는다
    called = []
    monkeypatch.setattr(C.dart, "fetch_document", lambda conn, lim, rno, **kw: called.append((rno, kw["target_prefix"])))
    r = C.fetch_recent(conn, date(2026, 10, 5))
    assert called == [("20261001000002", "agm")] and r["todo"] == 1 and r["fetched"] == 1
    assert tuple(conn.execute("SELECT event_date, event_time, label FROM corp_schedule "
                              "WHERE rcept_no='20261002000001'").fetchone()) == ("2026-11-10", "10:00", "임시주주총회")


def test_backfill_range_newest_first_skips_kept_and_caps_calls(conn, monkeypatch):
    """TC-CS-09 · 과거분 받기 — 접수일 구간 안만 · 최근 것부터 · 이미 받은 본문은 부르지 않는다 · 호출 상한에서 멈추고 남은 수를 센다."""
    for rno in ("20240105000001", "20240320000002", "20240321000003", "20250310000004", "20231229000005"):
        _disc(conn, rno, "주주총회소집결의")
    _raw(conn, "agm/20240320000002", ["1. 일시\t2024-03-29\t09:00"])           # 이미 받음
    called = []
    monkeypatch.setattr(C.dart, "fetch_document", lambda conn, lim, rno, **kw: called.append((rno, kw["target_prefix"])))
    r = C.fetch_range(conn, "20240101", "20241231", max_calls=10, sleep=lambda s: None)
    # 구간 밖(2023-12-29 · 2025-03-10)은 부르지 않는다 · 최근 것부터
    assert called == [("20240321000003", "agm"), ("20240105000001", "agm")]
    assert (r["todo"], r["fetched"], r["calls"], r["left"], r["quota"]) == (2, 2, 2, 0, False)
    called.clear()
    r = C.fetch_range(conn, "20240101", "", max_calls=2, sleep=lambda s: None)  # 끝 없음 → 2025 도 · 상한 2
    assert [c[0] for c in called] == ["20250310000004", "20240321000003"]
    assert (r["todo"], r["calls"], r["left"]) == (3, 2, 1)


def test_backfill_retries_transient_errors_and_stops_on_quota(conn, monkeypatch):
    """TC-CS-10 · 과거분 받기는 일시 오류를 쉬었다 다시 부르고(그래도 안 되면 그 건만 건너뜀) · 하루 한도면 그 자리에서 멈춘다 ·
    매일 단계는 오류를 그대로 올린다(러너가 🟡 로 남긴다)."""
    for rno in ("20250101000001", "20250102000002", "20250103000003", "20250104000004"):
        _disc(conn, rno, "주주총회소집결의")
    plan = {"20250104000004": [requests.ConnectionError("reset"), None],     # 한 번 끊김 → 쉬었다 다시 불러 받음
            "20250103000003": [C.dart.DartError("HTTP 500")] * 4,            # 네 번 다 실패 → 이 건만 건너뜀
            "20250102000002": [C.dart.DartQuotaExceeded("status=020")],      # 하루 한도 → 여기서 멈춤
            "20250101000001": [None]}
    calls, waits = [], []

    def fake(conn, lim, rno, **kw):
        calls.append(rno)
        step = plan[rno].pop(0)
        if step is not None:
            raise step

    monkeypatch.setattr(C.dart, "fetch_document", fake)
    r = C.fetch_range(conn, "20250101", "", max_calls=100, sleep=waits.append)
    assert calls == ["20250104000004"] * 2 + ["20250103000003"] * 4 + ["20250102000002"]
    assert waits == [10, 10, 30, 60]
    assert (r["fetched"], r["errors"], r["quota"], r["calls"], r["left"]) == (1, 1, True, 7, 2)
    plan["20250101000001"] = [C.dart.DartError("HTTP 500")]
    with pytest.raises(C.dart.DartError):                                     # 매일 단계(오래된 것부터)는 첫 오류에 멈춘다
        C.fetch_recent(conn, date(2025, 1, 10))
