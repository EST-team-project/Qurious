"""언론사 기사 메타데이터 시험 (TC-GD) — `collector/gdelt_news.py` (목표 기능 ① W7 · 설계서 5.1.5).

여기서 지키는 것 —
1. 번역 GKG 줄에서 한국어 원문(`srclc:kor`) · 웹 기사(수집 경로 1)만 · 제목은 HTML 문자 참조를 풀고 · 시각은 UTC → KST.
2. **본문 · 요약은 두지 않는다**(언론사 저작물) — 제목 · 주소 · 시각 · 언론사만. 커뮤니티 · 블로그 주소 · 제목 없는 줄은 버린다.
3. 15분 파일 이름(:00 · :15 · :30 · :45) · 읽은 파일은 다시 받지 않는다 · 아직 안 올라온 최근 파일(404)은 다음에 ·
   오래된 404 는 「없음」 으로 적어 다시 부르지 않는다 · 받기 실패는 그 파일만 건너뛰고 상태에 안 적는다(다음에 다시).
4. 검색 문서에 GDELT 출처 표시가 붙는다.

네트워크를 쓰지 않는다. GKG 줄은 2026-10-05 에 받은 실제 파일의 칸 꼴(27칸 · 탭)만 따른 지어낸 글이다.
"""
from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, timedelta, timezone

import pytest

from collector import db, gdelt_news as G, search_index as S

KST = timezone(timedelta(hours=9))


def _row(url="https://www.fnnews.com/news/202610051157206913", title="&#xC544;&#xC2DC;&#xC548;&#xAC8C;&#xC784; &amp; 기아",
         lang="srclc:kor;eng:GT-KOR 1.0", collection="1", date_="20261005010000", domain="fnnews.com"):
    cells = [""] * 27
    cells[0], cells[1], cells[2], cells[3], cells[4] = f"{date_}-T1", date_, collection, domain, url
    cells[25] = lang
    cells[26] = f"<PAGE_TITLE>{title}</PAGE_TITLE><PAGE_AUTHORS>x</PAGE_AUTHORS>" if title is not None else "<X>y</X>"
    return "\t".join(cells)


def _zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.translation.gkg.csv", text.encode("utf-8"))
    return buf.getvalue()


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "m.sqlite3")
    yield c
    c.close()


def test_parse_keeps_korean_web_articles_title_time_only():
    """TC-GD-01 · 한국어 원문 · 웹 기사만 · 제목 문자 참조 풂 · UTC → KST · 본문 · 요약 칸은 비어 있다 · 같은 주소는 하나."""
    text = "\n".join([
        _row(),
        _row(),                                                                    # 같은 주소 두 번
        _row(url="https://news.pedaily.cn/1.shtml", lang="srclc:zho;eng:GT-ZHO 1.0", domain="pedaily.cn"),
        _row(url="https://www.hani.co.kr/arti/1.html", collection="2", domain="hani.co.kr"),   # 웹 기사가 아님
    ])
    rows = G.parse_gkg(text)
    assert len(rows) == 1
    r = rows[0]
    assert r["title"] == "아시안게임 & 기아" and r["source"] == "gdelt" and r["publisher"] == "fnnews.com"
    assert r["pub_at"] == r["available_at"] == "2026-10-05T10:00:00+09:00"
    assert r["body"] == "" and r["subtitle"] == "" and r["news_id"].startswith("gdelt:") and len(r["news_id"]) == 22


def test_parse_drops_community_and_untitled():
    """TC-GD-02 · 커뮤니티 · 블로그 주소와 제목 없는 줄은 버린다(2026-10-05 표본에 네이트판이 섞였다)."""
    text = "\n".join([
        _row(url="https://pann.nate.com/talk/375656100", domain="nate.com"),
        _row(url="https://blog.naver.com/x/1", domain="naver.com"),
        _row(url="https://www.kmib.co.kr/article/1", title=None, domain="kmib.co.kr"),
        _row(url="https://www.kmib.co.kr/article/2", title="  ", domain="kmib.co.kr"),
        _row(url="https://www.ddaily.co.kr/page/view/1", domain="ddaily.co.kr"),
    ])
    assert [r["publisher"] for r in G.parse_gkg(text)] == ["ddaily.co.kr"]


def test_stamps_are_quarter_hours():
    """TC-GD-03 · 15분 파일 이름 — 시작이 어중간하면 다음 15분부터 · 끝 포함."""
    s = datetime(2026, 10, 5, 0, 7, tzinfo=timezone.utc)
    assert G.stamps_between(s, datetime(2026, 10, 5, 1, 0, tzinfo=timezone.utc)) == [
        "20261005001500", "20261005003000", "20261005004500", "20261005010000"]


def test_daily_skips_read_files_and_handles_404_and_errors(conn, tmp_path):
    """TC-GD-04 · 읽은 파일은 다시 받지 않는다 · 최근 404 는 다음에(상태에 안 적음) · 오래된 404 는 「없음」 · 받기 실패는 다음에."""
    now = datetime(2026, 10, 5, 12, 30, tzinfo=KST)                         # = 03:30 UTC → 끝 03:00 UTC
    state = tmp_path / "state.json"
    calls = []

    def get(url):
        stamp = url.rsplit("/", 1)[1].split(".")[0]
        calls.append(stamp)
        if stamp == "20261005030000":
            raise G.GdeltMissing(url)                                         # 아직 안 올라옴(30분 전)
        if stamp == "20261004200000":
            raise G.GdeltMissing(url)                                         # 7시간 반 전 — GDELT 에 없음
        if stamp == "20261005021500":
            raise ConnectionError("reset")
        return _zip(_row(url=f"https://www.fnnews.com/news/{stamp}"))

    r = G.daily(conn, now, hours=7, get=get, sleep=lambda s: None, state_path=state)
    assert len(calls) == 29 and r["files"] == 26 and r["new"] == 26
    assert (r["missing"], r["later"], r["errors"]) == (1, 1, 1)
    st = G.load_state(state)
    assert st["20261004200000"] == -1 and "20261005030000" not in st and "20261005021500" not in st
    calls.clear()
    r = G.daily(conn, now, hours=7, get=get, sleep=lambda s: None, state_path=state)
    assert sorted(calls) == ["20261005021500", "20261005030000"] and r["new"] == 0   # 읽은 파일 · 없음은 다시 안 부름
    assert tuple(conn.execute("SELECT COUNT(*), SUM(body <> '') FROM news_item WHERE source='gdelt'").fetchone()) == (26, 0)


def test_backfill_range_in_utc_days(conn, tmp_path):
    """TC-GD-05 · 날짜(UTC) 구간은 그날 00:00 ~ 23:45 의 96파일 — 지금 − 30분을 넘지 않는다."""
    calls = []
    G.backfill(conn, date(2026, 10, 3), date(2026, 10, 3), now=datetime(2026, 10, 5, tzinfo=KST),
               get=lambda u: calls.append(u) or _zip(""), sleep=lambda s: None, state_path=tmp_path / "s.json")
    assert len(calls) == 96 and calls[0].endswith("/20261003000000.translation.gkg.csv.zip")
    assert calls[-1].endswith("/20261003234500.translation.gkg.csv.zip")


def test_search_doc_attribution_for_gdelt():
    """TC-GD-06 · 검색 문서 — 제목 · 주소 · 언론사 · GDELT 출처 표시 · 요약 칸 빈칸(본문 없음)."""
    row = dict(G.parse_gkg(_row())[0], fetched_at="2026-10-05T14:00:00+09:00", updated_at="2026-10-05T14:00:00+09:00")
    d = S.news_doc(row)
    assert d["source"] == "gdelt" and d["summary"] == "" and d["url"].startswith("https://www.fnnews.com/")
    assert "GDELT Project(www.gdeltproject.org)" in d["extra"] and '"publisher": "fnnews.com"' in d["extra"]
