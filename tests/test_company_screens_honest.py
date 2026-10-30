"""TC-CPH · 투자 인디케이터 › 지표 대시보드 · 지표 비교 · 섹터 인디케이터의 정직한 표시 (3차 ①-16 첫 단계 · 2026-10-30).

무엇이 틀렸었나 — 지표 비교 표와 섹터 카드는 화면 파일에 적어 둔 고정 숫자(삼성전자 PER 16.2 · 평균 PER 22.3 ·
「긍정 · 중립 · 부정」 전망)를 출처 · 기준일 없이 실제 지표처럼 보였다. 지표 대시보드의 재무 값은 야후 재무 요약
(서버 저장본 최대 6시간)인데 그 사실과 기준일 없음이 화면에 없었다.

이 시험은 「밝히는 글」 이 화면에 있는지만 본다. 고정 값을 DART 재무 · 업종코드(KSIC)로 바꾸는 일은 ①-16 본 작업이다
(그 일이 끝나면 compare · sector 의 안내 글과 이 시험의 해당 줄을 함께 지운다).
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


def test_compare_and_sector_say_their_numbers_are_fixed_examples():
    for name in ("company-compare", "company-sector"):
        view = _view(name)
        assert "data-co-static-note" in view, name
        assert "고정 예시 값입니다" in view and "투자 판단 근거로 쓰지 마세요" in view and "①-16" in view, name
    assert "실제 재무가 아닙니다" in _view("company-compare")
    assert "「긍정 · 중립 · 부정」 전망" in _view("company-sector"), "섹터 전망이 근거 없는 값임을 말한다"


def test_static_note_sits_before_the_numbers_it_warns_about():
    compare, sector = _view("company-compare"), _view("company-sector")
    assert compare.index("data-co-static-note") < compare.index('id="co-compare-table"')
    assert sector.index("data-co-static-note") < sector.index('id="co-sector-cards"')


def test_dashboard_names_its_source_and_missing_base_date():
    m = re.search(r"function renderCompanyData\(d\) \{.*?\n\}\n", COMPANY, flags=re.S)
    assert m, "renderCompanyData 를 찾지 못했다"
    body = m.group(0)
    assert "data-co-basis" in body and "야후 파이낸스 재무 요약" in body
    assert "최대 6시간" in body and "기준 분기 · 기준일을 응답이 알려 주지 않습니다" in body
    assert "escHtml(d.priceNote" in body, "현재가 글은 서버 글을 이스케이프해 쓴다"


def test_compare_and_sector_functions_still_render_the_fixed_values():
    """안내 글은 값을 지우지 않고 덧붙인 것이다 — 본 작업 전까지 표 · 카드는 그대로 그려진다."""
    assert "function loadCompanyCompare()" in COMPANY and "function loadCompanySector()" in COMPANY
