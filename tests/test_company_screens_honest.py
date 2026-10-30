"""TC-CPH · 투자 인디케이터 › 지표 대시보드 · 지표 비교 · 섹터 인디케이터에 고정 값이 없다 (3차 ①-16 · 2026-10-30).

무엇이 틀렸었나 — 지표 비교 표와 섹터 카드는 화면 파일에 적어 둔 고정 숫자(삼성전자 PER 16.2 · 평균 PER 22.3 · 「긍정 · 중립 · 부정」 전망)를 출처 · 기준일 없이
실제 지표처럼 보였고, 지표 대시보드는 야후 재무 요약(기준일 없음)을 그대로 보였다. 같은 날 첫 단계로 「고정 예시 값」 안내 글을 붙였다가(10-30 오전),
본 작업(전자공시 · 업종코드 KSIC 로 계산)이 끝나 세 화면이 모두 서버가 계산한 값을 그리게 되면서 안내 글 · 고정 값을 지웠다.

이 시험은 고정 값 · 옛 안내가 다시 들어오지 않는지만 본다. 값 계산은 TC-CIN(서비스) · 글 규칙은 TC-CV(화면 판단)가 시험한다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
COMPANY = (ROOT / "public" / "js" / "company.js").read_text(encoding="utf-8")


def _view(name: str) -> str:
    m = re.search(rf'data-view="{name}">(.*?)data-view=', APP, flags=re.S)
    assert m, f"app.html 에서 {name} 화면을 찾지 못했다"
    return m.group(1)


def test_no_fixed_example_numbers_or_notes_remain():
    """고정 예시 값 상수 · 안내 상자가 세 화면 어디에도 없다."""
    for name in ("company-dashboard", "company-compare", "company-sector"):
        assert "data-co-static-note" not in _view(name) and "고정 예시 값입니다" not in _view(name), name
    for fixed in ("CO_DATA", "avgPer", "outlook", "긍정", "/api/stocks/fundamentals"):
        assert fixed not in COMPANY, fixed


def test_dashboard_reads_our_own_data_not_yahoo_summary():
    """지표 대시보드는 야후 재무 요약(근거 · 기준일 없음)이 아니라 전자공시 · 수집 일봉을 읽는다(TC-CV 가 글 규칙을 시험한다)."""
    m = re.search(r"function renderCompanyData\(p\) \{.*?\n\}\n", COMPANY, flags=re.S)
    assert m, "renderCompanyData 를 찾지 못했다"
    body = m.group(0)
    assert "cvOverviewCards" in body and "cvValuationRows" in body and "cvProfitRows" in body and "escHtml" in body
    assert 'id="co-chart"' in APP and 'id="co-chart-note"' in APP


def test_compare_and_sector_read_server_values_and_link_each_other():
    """비교 · 섹터는 서버 응답을 그리고(고정 배열 없음) 섹터 ↔ 산업 화면이 서로를 가리킨다(설계 결정 ③ 안 C)."""
    assert "cvCompareLoad" in COMPANY and "cvCompareTable" in COMPANY and "/api/data/indicators/universe" in COMPANY
    assert "/api/data/indicators/sectors" in COMPANY and "cvSectorCards" in COMPANY
    assert 'href="#macro-industry"' in _view("company-sector")
    assert 'href="#company-sector"' in _view("macro-industry")
    assert 'id="co-compare-form"' in _view("company-compare") and 'id="co-sector-note"' in _view("company-sector")
