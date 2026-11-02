"""TC-CPY — 할 일 ②-29 S14 · S17 : 지표 이름 옆 (i) 와 모의투자 결과 주의문 · 2026-11-02

S14  대사 화면(indicator-tradingview)의 「성과 비교」 표 — 지표 이름 옆 (i) 를 누르면 용어 카드가 열린다.
     1. 서버 compare_metrics() 의 rows[].key 와 화면의 대응표(METRIC_TERM_KEY)가 맞고, 대응표의 용어 키가 용어사전에서 실제로 풀린다.
        풀리지 않는 지표(거래 횟수)에는 (i) 를 달지 않는다 — 용어사전에 새 표제어를 만들지 않았다. (TC-CPY-01)
     2. (i) 는 core.js 의 termChip 으로 그리고, 그 단추는 openTermModal → QTerm.open 으로 용어 카드를 연다. (TC-CPY-02)
S17  모의투자 결과 곁 「가상 매매 기준 · 참고용 + 데모 데이터는 샘플」 주의문이 세 곳(paper-dashboard · robo-decision · 대시보드 로보 모의계좌)에 같은 글로 있다.
     3. 같은 글 · 사실만(비용 반영 여부는 쓰지 않는다 — 코인 · 대체자산 · 슬리피지는 코드로 확인하지 못했다) · 데모 데이터 문장을 담되
        「화면에 채워 보인다」고 단정하지 않는다 — 관리자 데모 단추(POST /api/paper/performance/simulate)가 만드는 행은 origin · completeness 가
        unknown 이라 성과 조회(valid_daily_row)가 거른다(S193 확인). 그 동작이 바뀌어 화면에 보이게 되면 이 글을 다시 본다. (TC-CPY-03)
     4. 팀원(강민석) 화면 JS(paper.js · robo.js)에는 이 문구도 표시 칸도 없다 — HTML 과 dashboard.js 만 고쳤다. (TC-CPY-04)
     5. 위치(사용자 결정 11-02: 가장 아래) — paper-dashboard 는 HTML 이 그리는 화면의 맨 아래, robo-decision 은 「모의 투자 성과 분석」 카드의 맨 아래
        (robo.js 가 innerHTML 을 바꾸는 칸의 형제), 대시보드 로보 탭은 패널의 맨 아래 한 줄. 좁은 화면에서 줄바꿈이 되도록 text-xs 를 쓰고 nowrap 이 없다. (TC-CPY-05)
        ※ paper.js 가 런타임에 pd-backtest-card 를 paper-dashboard 뷰 끝에 붙이므로, 화면에서 보이는 맨 끝은 그 카드다(안내 이슈에 요청).
네트워크 · 실제 DB 없이 돈다.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.services import tradingview as tv
from app.services.glossary import read_seed, seed_rows
from app.services.glossary_text import norm

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "public" / "js"
APP = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
TV_JS = (JS / "tradingview.js").read_text(encoding="utf-8")
CORE_JS = (JS / "core.js").read_text(encoding="utf-8")
DASH_JS = (JS / "dashboard.js").read_text(encoding="utf-8")


def _flat(s: str) -> str:
  return re.sub(r"\s+", " ", s)


def _term_keys() -> dict[str, str]:
  """tradingview.js 의 METRIC_TERM_KEY — 서버 key → 용어 키."""
  body = re.search(r"const METRIC_TERM_KEY = \{(.*?)\};", TV_JS, re.S).group(1)
  return dict(re.findall(r"(\w+):\s*\"([^\"]+)\"", body))


def _view_block(view: str) -> str:
  """app.html 의 화면 한 구역 — 시작 줄부터 다음 화면 시작 줄 앞까지."""
  start = APP.index(f'<div class="view" data-view="{view}">')
  nxt = APP.find('<div class="view" data-view="', start + 10)
  return APP[start: nxt if nxt != -1 else len(APP)]


def _notice_in(block: str) -> list[str]:
  return [_flat(t).strip() for t in re.findall(r"<p[^>]*data-paper-notice[^>]*>(.*?)</p>", block, re.S)]


def _dash_notice() -> str:
  """dashboard.js 의 PAPER_NOTICE 상수 — 로보 모의계좌 탭이 쓰는 글."""
  m = re.search(r"const PAPER_NOTICE = '([^']+)';", DASH_JS)
  assert m, "dashboard.js 에 PAPER_NOTICE 상수가 없다"
  return m.group(1)


def _markup_around_notice(block: str) -> tuple[str, str]:
  """표시 칸 `<p>` 앞 · `</p>` 뒤의 마크업 — 주석을 걷고 공백을 줄인다. (앞, 뒤)"""
  at = block.index("data-paper-notice")
  start, end = block.rindex("<p", 0, at), block.index("</p>", at) + len("</p>")
  strip = lambda s: _flat(re.sub(r"<!--.*?-->", "", s, flags=re.S)).strip()
  return strip(block[:start]), strip(block[end:])


def test_s14_term_keys_match_server_rows_and_resolve_in_glossary():
  """TC-CPY-01 · 대응표의 서버 key 는 compare_metrics 의 rows[].key 이고, 용어 키는 서버가 찾는 방식(norm → 별칭 표)으로 풀린다."""
  server_keys = [r["key"] for r in tv.compare_metrics({}, {})["rows"]]
  assert server_keys == ["net_profit_pct", "max_drawdown_pct", "total_trades", "win_rate_pct", "sharpe_ratio"]
  mapping = _term_keys()
  assert set(mapping) <= set(server_keys), "대응표에 서버가 안 주는 key 가 있다"
  assert "total_trades" not in mapping, "용어사전에 거래 횟수 표제어가 없다 — (i) 를 달지 않는다"

  # glossary.get_term 과 같은 규칙: norm(키) == 별칭 표의 alias_norm. 적재(seed_rows)가 겹친 이름을 건너뛰는 규칙까지 같이 반영된다.
  _, _, terms, aliases = seed_rows(read_seed()[0])
  owner = {a["alias_norm"]: a["term_id"] for a in aliases}
  ids = {t["id"] for t in terms}
  expected = {"net_profit_pct": "수익률", "max_drawdown_pct": "mdd", "win_rate_pct": "승률", "sharpe_ratio": "샤프-비율"}
  assert set(mapping) == set(expected)
  for key, term_key in mapping.items():
    assert "'" not in term_key and '"' not in term_key, "키는 인라인 onclick 따옴표 안에 들어간다"
    assert owner.get(norm(term_key)) == expected[key], f"{key} → {term_key} 가 {expected[key]} 로 풀리지 않는다"
    assert expected[key] in ids
  # 거래 횟수에 걸릴 만한 이름이 용어사전에 정말 없는지 — 있으면 (i) 를 달 수 있으니 이 시험이 알려 준다
  for name in ("거래 횟수", "거래횟수", "total_trades", "매매 횟수", "Number of Trades", "Total Trades"):
    assert norm(name) not in owner, f"용어사전에 「{name}」 가 생겼다 — total_trades 에도 (i) 를 달 수 있다"


def test_s14_chip_is_drawn_by_termchip_and_opens_the_term_card():
  """TC-CPY-02 · 성과 비교 표의 지표 칸은 termChip(용어 키, 서버 라벨)로 그리고, 대응이 없으면 지금처럼 글자만 — 단추는 QTerm.open 으로 이어진다."""
  flat = _flat(TV_JS)
  assert "const metricLabel = (x) => METRIC_TERM_KEY[x.key] && window.termChip ? window.termChip(METRIC_TERM_KEY[x.key], x.label) : escHtml(x.label);" in flat
  row = flat[flat.index("r.rows.map(x =>"):]
  assert row.startswith("r.rows.map(x => `<tr><td>${metricLabel(x)}</td>"), "표 첫 칸이 metricLabel 이어야 한다"
  assert "<td>${escHtml(x.label)}</td>" not in flat, "옛 글자만 칸이 남아 있다"
  # 이 화면에 새 용어 부품을 만들지 않는다 — core.js 의 termChip 이 (i) 아이콘 단추를 그리고, 누르면 용어 카드(QTerm)를 연다
  chip = CORE_JS[CORE_JS.index("function termChip(key, label)"):CORE_JS.index("window.termChip = termChip;")]
  assert "fa-circle-info" in chip and "openTermModal('${key}')" in chip and "escHtml(text)" in chip
  opener = CORE_JS[CORE_JS.index("function openTermModal(key)"):CORE_JS.index("function closeTermModal()")]
  assert "window.QTerm.open(key, { fallback: term })" in opener


def test_s17_notice_is_the_same_line_in_three_places_and_states_only_facts():
  """TC-CPY-03 · paper-dashboard · robo-decision · 대시보드 로보 모의계좌 — 같은 글 한 줄. 비용(수수료 · 슬리피지 · 세금) 얘기는 쓰지 않는다."""
  paper = _notice_in(_view_block("paper-dashboard"))
  robo = _notice_in(_view_block("robo-decision"))
  assert len(paper) == 1 and len(robo) == 1, "각 구역에 한 줄씩"
  assert APP.count("data-paper-notice") == 2, "다른 구역에 표시 칸이 번졌다"
  line = _dash_notice()
  assert paper[0] == robo[0] == line, "세 곳의 글이 같아야 한다"
  assert DASH_JS.count("가상 매매 기준") == 1, "dashboard.js 에 같은 글이 상수 밖에도 있다 — 한 곳에서만 바꾸게 한다"
  for must in ("가상 매매 기준", "참고용", "투자 권유가 아닙니다", "데모 데이터", "임의로 만든 샘플"):
    assert must in line
  # 확인한 사실만 — 주식 모의 체결의 수수료 · 세금은 확인했지만 코인 · 대체자산 · 슬리피지는 못 했으므로 한 줄에 싣지 않는다
  assert not re.search(r"수수료|슬리피지|세금|반영|보장|수익을 (?:낸|얻)", line)
  # 데모 데이터 문장은 「화면에 채워 보인다」고 단정하지 않는다 — 단추가 만든 행은 성과 조회가 거른다(위 설명). 단추 위치도 문장에 묶지 않는다
  assert not re.search(r"채운|화면의 값|보이는|표시된|단추|버튼", line)


def test_s17_teammate_js_is_untouched():
  """TC-CPY-04 · paper.js · robo.js (강민석 몫) 에는 이 문구도 표시 칸도 없다 — 숫자 곁 문구를 JS 에 더하지 않았다."""
  for name in ("paper.js", "robo.js"):
    src = (JS / name).read_text(encoding="utf-8")
    for token in ("가상 매매 기준", "data-paper-notice", "PAPER_NOTICE", "임의로 만든 샘플"):
      assert token not in src, f"{name} 에 {token} — 팀원 파일은 건드리지 않는다"


def test_s17_notice_sits_at_the_very_bottom_of_each_place_and_wraps_on_narrow_screens():
  """TC-CPY-05 · 사용자 결정(11-02) 「가장 아래」 — 세 곳의 위치와 좁은 화면(390px) 줄바꿈."""
  # paper-dashboard : HTML 이 그리는 화면의 마지막 요소(space-y-4 의 마지막 자식) — 앞은 「최근 체결」 카드
  before, after = _markup_around_notice(_view_block("paper-dashboard"))
  assert after.replace(" ", "") == "</div></div>", f"paper-dashboard 의 표시 칸 뒤에 다른 요소가 있다: {after[:80]}"
  assert re.search(r'<div id="pd-recent"[^>]*></div> </div>$', before), "paper-dashboard 의 표시 칸 앞이 「최근 체결」 카드의 끝이 아니다"
  # robo-decision : 「모의 투자 성과 분석」 카드의 마지막 요소. robo.js 가 innerHTML 을 바꾸는 칸(robo-metrics-table) 안이 아니라 그 형제여야 지워지지 않는다
  before, after = _markup_around_notice(_view_block("robo-decision"))
  assert after.replace(" ", "") == "</div></div></div>", f"robo-decision 의 표시 칸 뒤에 다른 요소가 있다: {after[:80]}"
  assert re.search(r'<div id="robo-metrics-table"[^>]*></div>$', before), "robo-decision 의 표시 칸 앞이 robo-metrics-table 의 닫힘이 아니다"
  # 대시보드 로보 모의계좌 탭 : 총 자산 곁 note 에서 빼고 패널의 마지막 조각 한 줄로 — 숫자가 있는 분기에만
  assert re.search(r"metric\('모의계좌 총 자산', number\(s\.total_asset, '원', 0\)\) \+", DASH_JS), "총 자산 곁 note 가 남아 있다"
  chain = re.search(r"roboTab\.html =(.*?);\s*\n\s*\} else \{", DASH_JS, re.S)
  assert chain, "roboTab.html 조립부를 찾지 못했다"
  assert chain.group(1).rstrip().endswith('`<div class="overview-metric wide" data-paper-notice><small>${escHtml(PAPER_NOTICE)}</small></div>`')
  assert DASH_JS.count("PAPER_NOTICE") == 2 and DASH_JS.count("data-paper-notice><small>") == 1, "자료 없음 · 오류 분기에 번졌다"
  # 좁은 화면 : text-xs 로 줄바꿈(전체가 keep-all 이라 단어 단위) — nowrap 금지
  for tag in re.findall(r"<p[^>]*data-paper-notice[^>]*>", APP):
    assert "text-xs" in tag and "nowrap" not in tag, tag
  css = (ROOT / "public" / "css" / "app.css").read_text(encoding="utf-8")
  for rule in re.findall(r"^\.overview-(?:metrics?|note)[^{]*\{[^}]*\}", css, re.M):
    assert "nowrap" not in rule, rule
