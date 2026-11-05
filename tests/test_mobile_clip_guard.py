"""TC-MCG — 390px(모바일 폭)에서 화면이 오른쪽으로 잘리지 않게 하는 구조 점검 (2026-11-05 화면 눌러 보기 뒤)

배경: 문서 `scrollWidth` 로는 0 이어도 바깥 컨테이너가 넘친 부분을 잘라 버리는 화면이 10곳 있었다
(코인 모의매매 · TradingView 연동 · 패턴 인식 · LEAN · 학습 장 5개 · 학습 허브). 원인은 둘이다.
1. 1열 그리드의 트랙이 `1fr`(= minmax(auto, 1fr)) 이거나 기본 열이 없어서 긴 내용이 칸을 밀어냈다.
2. 줄바꿈이 안 되는 긴 글(주소 · 상태 문구)이나 넓은 표가 부모 안에서 줄지 못했다.
브라우저 없이 소스 문자열로만 확인한다(실제 폭 측정은 사람이 getBoundingClientRect 로 한다).
  1. finlearn.css 의 900px 이하 규칙이 minmax(0, 1fr) 이다. (TC-MCG-01)
  2. 긴 링크는 본문 안에서 줄바꿈된다. (TC-MCG-02)
  3. app.html — 코인 시세 줄 · TradingView 연동 · 패턴 표 · LEAN 상태 칸에 줄어들 수 있는 표시가 있다. (TC-MCG-03)
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "public" / "css" / "finlearn.css").read_text(encoding="utf-8")
HTML = (ROOT / "public" / "app.html").read_text(encoding="utf-8")


def _media_900() -> str:
  m = re.search(r"@media \(max-width: 900px\) \{ \.fl-grid.*?\}\s*\}", CSS, re.S)
  assert m, "finlearn.css 에 .fl-grid 의 900px 이하 규칙이 없다"
  return m.group(0)


def test_tc_mcg_01_finlearn_mobile_tracks_can_shrink():
  """TC-MCG-01 — `1fr` 은 minmax(auto, 1fr) 라 긴 내용이 칸을 밀어낸다. 모바일 규칙은 minmax(0, 1fr)."""
  grid = _media_900()
  assert "grid-template-columns: minmax(0, 1fr)" in grid
  assert not re.search(r"grid-template-columns:\s*1fr\b", grid)
  reader = re.search(r"@media \(max-width: 900px\) \{ \.fl-reader \{[^}]*\}", CSS)
  assert reader and "minmax(0, 1fr)" in reader.group(0)
  assert not re.search(r"grid-template-columns:\s*1fr\b", reader.group(0))


def test_tc_mcg_02_article_links_wrap():
  """TC-MCG-02 — 학습 본문의 긴 주소 링크가 본문 밖으로 밀려 잘리지 않는다."""
  assert re.search(r"\.fl-article a\s*\{[^}]*overflow-wrap:\s*anywhere", CSS)


def test_tc_mcg_03_app_html_shrinkable_spots():
  """TC-MCG-03 — 코인 시세 줄 · TradingView 연동 줄 · 패턴 표 · LEAN 상태 칸."""
  coin = re.search(r'<div class="grid ([^"]*)">\s*<div class="rounded-xl border border-white/10 bg-black/20 p-4">\s*<div class="flex gap-2 mb-2">\s*<select id="pc-market" class="([^"]*)"', HTML)
  assert coin, "코인 시세 줄 마크업을 찾지 못했다"
  assert "grid-cols-1" in coin.group(1), "기본 1열이 없으면 암묵 열이 auto 라 칸이 밀린다"
  assert "min-w-0" in coin.group(2) and "flex-1" in coin.group(2)
  tv = re.search(r'<div class="grid ([^"]*)">\s*<div class="min-w-0">\s*<h3 class="font-semibold text-sm mb-2">① Webhook URL', HTML)
  assert tv and "grid-cols-1" in tv.group(1)
  assert re.search(r'id="tv-webhook-url"\s*class="[^"]*break-all', HTML)
  assert re.search(r'id="pt-mtf" class="[^"]*overflow-x-auto', HTML)
  assert re.search(r'id="ql-status" class="[^"]*min-w-0[^"]*"[^>]*overflow-wrap:anywhere', HTML)
