"""금융 강의 시험 (TC-LC) — 「금융 필수 지식」 › 강의실 · 주제 화면과 강의 시세 API.

무엇을 붙였나 —
통합본(rag-lab/)의 강의 4일치 · 교재 10단원을 앱 안의 강의실 · 주제 화면으로 이었다. 강의 파일은
scripts/lectures_build.py 가 사본에서 만들고(public/lectures/), 강의 그림이 부르는 시세 주소 일곱은
app/routes/lectures.py 로 옮겼다(수집 DB 먼저 · 야후는 표시만 · 저장 없음).

여기서 지키는 것 —
1. 빌드 결과가 저장소의 public/lectures/ 와 같다 — 누가 손으로 고치면 실패한다.
2. 강의 페이지의 시세 주소가 남김없이 우리 주소로 바뀌었고, 앱 안 싣기 표시 · 링크 신호가 들어갔다.
3. 강의실 목록(catalog.json)의 부제 · 질문이 엉뚱한 글을 잡지 않는다(만들며 찾은 결함 둘의 재발 방지).
4. 교재가 가리키는 그림이 모두 있다.
5. 시세 계산부: 수집 DB 가 기간을 덮으면 수집 DB, 아니면 야후 — 야후는 가짜로 바꿔 네트워크를 쓰지 않는다.
6. 기간 수익률: 고른 시작일이 가진 자료보다 한 주 넘게 앞서면 수익률을 내지 않는다(통합본의 결함).
7. 「더 앞선 이력」 요청은 아무것도 저장하지 않고 가장 이른 날짜만 답한다.
8. 화면 연결: 메뉴(core.js) · 화면 자리(app.html) · 주제 목록(finlearn.js)의 화면 키가 서로 맞는다.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import lectures_build  # noqa: E402

from app.services import collector_db, lecture_market as lm  # noqa: E402
from collector.db import SCHEMA  # noqa: E402

LECT = ROOT / "public" / "lectures"
pytestmark = pytest.mark.skipif(not (ROOT / "rag-lab" / "frontend" / "days").is_dir(), reason="통합본 사본(rag-lab/)이 없다")


# ── 1 · 2 · 3 · 4 빌드 ─────────────────────────────────────────────
@pytest.fixture(scope="module")
def built():
    files, report = lectures_build.build()
    return files, report


def test_build_matches_repository(built):
    """TC-LC-01 · 빌드 결과가 저장소의 public/lectures/ 와 한 바이트도 다르지 않다(손으로 고친 파일이 없다)."""
    files, _ = built
    now = {p.relative_to(LECT).as_posix(): p.read_bytes() for p in LECT.rglob("*") if p.is_file()}
    assert sorted(now) == sorted(files), "남거나 빠진 파일 — python scripts/lectures_build.py 를 다시 돌린다"
    changed = [k for k, v in files.items() if now[k] != v]
    assert not changed, f"빌드와 다른 파일: {changed[:5]}"


def test_market_urls_rewritten_and_embed_hooks_present(built):
    """TC-LC-02 · 강의 페이지 · 스크립트에 통합본 시세 주소(/market/ · /health · /learning/)가 남지 않고, 싣기 표시가 들어갔다."""
    files, _ = built
    for d in lectures_build.DAYS:
        html = files[f"days/{d}.html"].decode("utf-8")
        assert re.search(r"""["'`]/market/""", html) is None, f"{d}일차에 바꾸지 않은 /market/ 주소"
        assert re.search(r"""["'`]/health["'`?]""", html) is None
        assert "/learning/historic-bond-image" not in html
        assert "window.API_BASE = ''" not in html and 'window.API_BASE = ""' not in html, "API_BASE 를 비우는 줄이 남았다"
        assert 'window.API_BASE = "/api/lectures"' in html and "q-lecture-nav" in html and "q-embed" in html
    for rel, data in files.items():
        if rel.startswith("days/assets/") and rel.endswith(".js"):
            assert re.search(r"""["'`]/market/""", data.decode("utf-8")) is None, rel
    assert b"packages/pretendard" in files["hangul-scale.css"], "글꼴 경로를 새 경로로 바꾸지 않았다"
    for d in lectures_build.DAYS:
        for name in lectures_build._PARENT_ASSET.findall(files[f"days/{d}.html"].decode("utf-8")):
            assert f"assets/{name}" in files, f"{d}일차가 부르는 ../assets/{name} 가 빠졌다"


def test_catalog_subtitles_and_questions_are_clean(built):
    """TC-LC-03 · 강의실 목록 — 4일차 · 10단원, 부제는 그 일차의 설명 한 줄, 질문은 60자 이하 절 제목."""
    files, _ = built
    cat = json.loads(files["catalog.json"])
    assert [d["day"] for d in cat["days"]] == list(lectures_build.DAYS)
    assert [u["id"] for u in cat["units"]] == list(range(1, 11))
    titles = [d["title"] for d in cat["days"]]
    for d in cat["days"]:
        assert d["subtitle"] and d["blurb"], d["day"]
        # 만들며 찾은 결함 ① — 과정 목록 페이지의 위쪽 메뉴(다른 일차 제목)까지 설명으로 잘라 왔다
        others = [t for t in titles if t != d["title"]]
        assert not any(t in d["blurb"] for t in others), f"{d['day']}일차 설명에 다른 일차 제목이 섞였다: {d['blurb']}"
        # 결함 ② — 1일차 부제가 제목 줄 밖의 문장(퀴즈 문항)이었다
        assert "안전자산" not in d["subtitle"]
    for item in cat["days"] + cat["units"]:
        assert 1 <= len(item["questions"]) <= 4
        assert all(0 < len(q) <= 60 for q in item["questions"])


def test_curriculum_images_all_present(built):
    """TC-LC-04 · 교재 마크다운이 가리키는 그림(img/…)이 모두 빌드에 들어 있고 옛 주소(/images/ · /image/)가 남지 않는다."""
    files, report = built
    refs = set()
    for rel, data in files.items():
        if rel.startswith("curriculum/unit"):
            text = data.decode("utf-8")
            assert "](/images/" not in text and "](/image/" not in text, rel
            refs |= set(re.findall(r"\]\(img/([^)\s]+)\)", text))
    assert refs and all(f"curriculum/img/{r}" in files for r in refs)
    assert report["images"] == len(refs) == 19


# ── 5 · 6 · 7 시세 계산부 (가짜 수집 DB · 가짜 야후) ────────────────
def _bday_range(start: date, end: date):
    d = start
    while d < end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


@pytest.fixture
def fake_db(tmp_path, monkeypatch):
    """수집기의 실제 스키마로 2024-01-02 ~ 2024-06-28 평일 지수 · ETF · 종목 행을 만든다."""
    p = tmp_path / "market.sqlite3"
    conn = sqlite3.connect(p)
    conn.executescript(SCHEMA)
    days = list(_bday_range(date(2024, 1, 2), date(2024, 6, 29)))
    for i, d in enumerate(days):
        ymd = d.strftime("%Y%m%d")
        for nm, base in (("코스피", 2600.0), ("코스피 200", 350.0)):
            conn.execute("INSERT INTO index_daily (bas_dt, idx_csf, idx_nm, clpr) VALUES (?,?,?,?)",
                         (ymd, "KOSPI시리즈", nm, base + i))
        conn.execute("INSERT INTO etf_daily (bas_dt, srtn_cd, itms_nm, clpr) VALUES (?,?,?,?)",
                     (ymd, "148070", "가짜 국고채10년", 100000 + i * 10))
        conn.execute("INSERT INTO price_adjusted (bas_dt, srtn_cd, adj_clpr, cum_factor) VALUES (?,?,?,1.0)",
                     (ymd, "005930", 70000 + i * 100))
    conn.commit()
    conn.close()
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(p))
    lm.clear_caches()
    yield p
    lm.clear_caches()


@pytest.fixture
def no_yahoo(monkeypatch):
    """야후를 부르면 실패하게 — 수집 DB 로 끝나야 하는 경로를 확인한다."""
    calls = []

    async def boom(symbol, *a, **k):
        calls.append(symbol)
        raise AssertionError(f"야후를 불렀다: {symbol}")
    monkeypatch.setattr(lm, "yahoo_daily", boom)
    return calls


def test_kospi_history_reads_collector_when_covered(fake_db, no_yahoo):
    """TC-LC-05 · 수집 DB 가 기간을 덮으면 야후를 부르지 않고 수집 DB 로 그린다(출처 표시 포함)."""
    out = asyncio.run(lm.kospi_history(date(2024, 2, 1), date(2024, 3, 1)))
    assert out["source"] == lm.SOURCE_COLLECTOR and out["symbol"] == "^KS11"
    assert len(out["bars"]) == 21 and out["bars"][0]["close"] > 2600
    rate = asyncio.run(lm.rate_market_history(date(2024, 1, 2), date(2024, 6, 1)))
    assert rate["source"] == lm.SOURCE_COLLECTOR and rate["bond_etf"]["name"] == "가짜 국고채10년"
    assert len(rate["kospi"]["bars"]) == len(rate["bond_etf"]["bars"]) > 21
    bok = asyncio.run(lm.central_bank_event_history("bok", date(2024, 3, 15), 5))
    assert bok["source"] == lm.SOURCE_COLLECTOR and len(bok["benchmark"]["bars"]) >= 11
    assert not no_yahoo


def test_kospi_history_falls_back_to_yahoo_outside_coverage(fake_db, monkeypatch):
    """TC-LC-05b · 수집 DB 가 덮지 못하는 기간(2008 년)은 야후로 — 받은 값은 메모리 캐시에만 둔다."""
    asked = []

    async def fake_yahoo(symbol, start, end, tz=lm.KST, timeout=12.0):
        asked.append(symbol)
        return [(1220000000 + i * 86400, 1500.0 + i) for i in range(30)]
    monkeypatch.setattr(lm, "yahoo_daily", fake_yahoo)
    out = asyncio.run(lm.kospi_history(date(2008, 9, 1), date(2008, 12, 1)))
    assert out["source"] == lm.SOURCE_YAHOO and asked == ["%5EKS11"] and len(out["bars"]) == 30
    asyncio.run(lm.kospi_history(date(2008, 9, 1), date(2008, 12, 1)))
    assert asked == ["%5EKS11"], "같은 기간을 다시 물으면 캐시로 답해야 한다"


def test_range_limits_are_400(fake_db):
    """TC-LC-05c · 기간 한도(코스피 370일 · 코스피 200 270일)를 넘거나 거꾸로면 400."""
    for coro in (lm.kospi_history(date(2024, 1, 2), date(2025, 2, 1)),
                 lm.kospi200_history(date(2024, 1, 2), date(2024, 12, 1)),
                 lm.kospi_history(date(2024, 3, 1), date(2024, 2, 1))):
        with pytest.raises(lm.MarketDataError) as e:
            asyncio.run(coro)
        assert e.value.status_code == 400


def test_period_return_refuses_start_before_coverage(fake_db):
    """TC-LC-06 · 고른 시작일이 가진 자료보다 한 주 넘게 앞서면 수익률을 내지 않는다 — 통합본은 가진 첫날부터 계산했다."""
    early = lm.period_return("005930", date(2023, 6, 1), date(2024, 6, 1))
    assert early["available"] is False and early["reason"] == "needs_older_history"
    assert early["earliest_stored_date"] == "2024-01-02"
    ok = lm.period_return("005930", date(2024, 1, 1), date(2024, 3, 29))    # 1월 1일은 휴일 — 한 주 안이라 괜찮다
    assert ok["available"] is True and ok["start_date"] == "2024-01-02"
    assert ok["return_pct"] == round((ok["end_close"] / ok["start_close"] - 1) * 100, 2)
    etf = lm.period_return("148070", date(2024, 2, 1), date(2024, 3, 1))
    assert etf["available"] is True and etf["bar_count"] == 22      # 기간 수익률은 끝날을 포함한다(통합본과 같다) — 2월 평일 21 + 3/1
    assert lm.period_return("999999", date(2024, 2, 1), date(2024, 3, 1))["reason"] == "no_data"


def test_extend_stores_nothing(fake_db):
    """TC-LC-07 · 「더 앞선 이력」 요청은 저장하지 않고 가장 이른 날짜만 답한다 — 수집 DB 파일이 바뀌지 않는다."""
    before = fake_db.read_bytes()
    out = lm.extend_period_history("005930", date(2019, 1, 2))
    assert out["fetched_bars"] == 0 and out["earliest_date"] == "2024-01-02"
    assert fake_db.read_bytes() == before


# ── 8 화면 연결 ────────────────────────────────────────────────────
def test_menu_views_and_topics_agree():
    """TC-LC-08 · 메뉴(core.js) · 화면 자리(app.html) · 주제 목록(finlearn.js)의 화면 키가 서로 맞고, 앱 밖 /learn/ 금융 링크가 없다."""
    core = (ROOT / "public" / "js" / "core.js").read_text(encoding="utf-8")
    app = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    fl = (ROOT / "public" / "js" / "finlearn.js").read_text(encoding="utf-8")
    finance = core[core.index("  finance: {"):core.index("  learn: {")]
    menu_keys = re.findall(r'key: "(fin-[a-z-]+)"', finance)
    topic_keys = re.findall(r'key: "(fin-topic-[a-z]+)"', fl)
    assert "fin-lectures" in menu_keys and len(topic_keys) == 9
    assert set(topic_keys) <= set(menu_keys)
    for k in ["fin-lectures", *topic_keys]:
        assert f'data-view="{k}"' in app, f"app.html 에 {k} 화면 자리가 없다"
        assert f'"{k}"' in core.split("const VIEW_GUIDES")[1], f"{k} 사용법 안내가 없다"
    assert "/learn/#/s/finance" not in finance, "금융 지식은 앱 안에서 읽는다 — /learn/ 링크를 빼기로 했다"
    assert "/css/finlearn.css" in app and "onFinLearnViewActivated" in (ROOT / "public" / "js" / "main.js").read_text(encoding="utf-8")
