"""TC-AHS — app.html 구조 지킴이 (2026-11-03)

`public/app.html` 은 3,000줄이 넘는 단일 HTML 셸이다. 이 파일을 나누지 않고(조사 2026-11-03-app-html-분리방안, 추천 A안)
무거운 화면만 「뿌리 div + 화면별 JS」 꼴로 천천히 줄이는 동안, 어느 안으로 가든 지켜야 할 모양 네 가지를 고정한다.
기존 파일은 고치지 않고 이 시험 파일만 더했다 — 필요 없어지면 파일 하나만 지우면 된다.

  1. 화면 키(`data-view`)는 한 번씩만, 그리고 모두 `<div class="view">` 에 달려 있다. (TC-AHS-01)
  2. 화면 블록 안에는 `<script>` 가 없다 — 스크립트는 head 와 셸 끝에만. (TC-AHS-02)
  3. 인라인 이벤트 속성(onclick 등)은 알려진 둘뿐이고 화면 블록 안에는 없다. (TC-AHS-03)
  4. 메뉴(GNB_MENUS)의 항목은 외부 링크(href)가 아니면 실제 화면이 있다. (TC-AHS-04)

네트워크 · 실제 DB 없이 돈다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
CORE_JS = (ROOT / "public" / "js" / "core.js").read_text(encoding="utf-8")

VIEW_TAG = re.compile(r'<div class="view" data-view="([^"]+)"')


def _view_region() -> str:
  """첫 화면 시작부터 푸터 앞까지 — 화면 블록들이 몰려 있는 구간."""
  start = APP.index('<div class="view"')
  end = APP.index("<footer", start)
  return APP[start:end]


def test_view_keys_unique_and_all_on_view_divs():
  """TC-AHS-01: data-view 는 76개처럼 늘 `<div class="view">` 위에만 있고 같은 키가 두 번 나오지 않는다."""
  keys = VIEW_TAG.findall(APP)
  assert len(keys) >= 50, "화면 블록이 이상하게 적다 — 파일이 잘렸거나 마크업 꼴이 바뀌었다"
  dup = sorted({k for k in keys if keys.count(k) > 1})
  assert not dup, f"중복된 화면 키: {dup}"
  # view 가 아닌 곳에 data-view 가 달리면(예: 링크 속성) 화면 전환 코드가 헷갈린다
  assert APP.count("data-view=") == len(keys), "class=\"view\" 가 아닌 요소에 data-view 가 있다"


def test_no_script_tag_inside_view_blocks():
  """TC-AHS-02: 화면 블록 안에 `<script>` 가 없다 — 있으면 화면을 조각으로 옮길 때 실행되지 않는다."""
  assert "<script" not in _view_region().lower()
  # 스크립트는 head 와 셸 끝(main.js)에만
  last_view = APP.rindex('<div class="view"')
  tail_scripts = [m.start() for m in re.finditer(r"<script\b", APP) if m.start() > last_view]
  assert all(pos > APP.index("<footer", last_view) for pos in tail_scripts)


def test_inline_event_handlers_are_only_the_two_known():
  """TC-AHS-03: 인라인 이벤트 속성은 동기화 배지 onclick 과 폰트 link onload 둘뿐 — 화면 블록 안에는 없다."""
  pat = re.compile(r"<[a-zA-Z][^>]*?\s(on[a-z]+)=\"", re.S)
  found = sorted({m.group(1) for m in pat.finditer(APP)})
  assert found == ["onclick", "onload"], found
  assert not pat.search(_view_region()), "화면 블록 안에 인라인 이벤트가 생겼다 — addEventListener 로 붙인다"


def test_menu_items_without_href_have_a_view():
  """TC-AHS-04: GNB_MENUS 항목은 href(외부 링크)가 없으면 같은 키의 화면이 있다."""
  views = set(VIEW_TAG.findall(APP))
  start = CORE_JS.index("const GNB_MENUS = {")
  end = CORE_JS.index("\n};", start)
  items = re.findall(r'\{\s*key:\s*"([^"]+)"([^}]*)\}', CORE_JS[start:end])
  assert len(items) >= 50
  missing = sorted(k for k, rest in items if "href:" not in rest and k not in views)
  assert not missing, f"화면이 없는 메뉴 항목: {missing}"


# ── 2026-11-03 코드 검토(2026-11-03-app-html-코드검토) 뒤 더한 불변식 ─────────────────────────────

JS_DIR = ROOT / "public" / "js"
JS_ALL = "\n".join(p.read_text(encoding="utf-8") for p in sorted(JS_DIR.glob("*.js")))
ID_ATTR = re.compile(r'\sid="([^"]+)"')


def test_ids_are_unique():
  """TC-AHS-05: app.html 의 id 는 문서 안에서 한 번씩만 — 같은 id 가 둘이면 getElementById 가 앞쪽만 잡는다."""
  ids = ID_ATTR.findall(APP)
  assert len(ids) >= 500
  dup = sorted({i for i in ids if ids.count(i) > 1})
  assert not dup, f"중복 id: {dup}"


def test_inline_handler_functions_are_on_window():
  """TC-AHS-06: app.html 의 인라인 핸들러(onclick="fn()")가 부르는 함수는 `window.fn =` 으로 전역에 달려 있다.

  `triggerSync` 가 모듈 지역 함수여서 동기화 배지를 누르면 ReferenceError 였던 일(2026-11-03)을 막는다."""
  names = sorted(set(re.findall(r'\son(?:click|change|input|submit|keydown)="\s*([A-Za-z_$][\w$]*)\(', APP)))
  assert "triggerSync" in names
  missing = [n for n in names if not re.search(rf"window\.{re.escape(n)}\s*=", JS_ALL)]
  assert not missing, f"window 에 안 달린 인라인 핸들러 함수: {missing}"


def test_label_for_targets_exist():
  """TC-AHS-07: `<label for="x">` 의 x 는 같은 문서에 실제로 있는 id 다(짝 잃은 for 가 없다)."""
  ids = set(ID_ATTR.findall(APP))
  fors = re.findall(r'<label\b[^>]*\sfor="([^"]+)"', APP, re.S)
  assert len(fors) >= 130
  assert not [f for f in fors if f not in ids], "대상 id 가 없는 label for"


def test_orphan_labels_stay_near_zero():
  """TC-AHS-08: 컨트롤과 이어지지 않은 고아 `<label>` (for 도 없고 안에 컨트롤도 없음)은 2개 이하 — 2026-11-03 에 104개 중 102개를 풀었다."""
  orphans = 0
  for m in re.finditer(r"<label\b([^>]*)>(.*?)</label>", APP, re.S):
    if re.search(r"\sfor=", m.group(1)):
      continue
    if re.search(r"<(input|select|textarea)\b", m.group(2)):
      continue
    orphans += 1
  assert orphans <= 2, f"고아 label {orphans}개 — 새 label 에는 for= 를 단다"


def test_target_blank_links_have_rel():
  """TC-AHS-09: target="_blank" 링크에는 rel="noopener noreferrer" 가 있다."""
  bad = [m.group(0)[:80] for m in re.finditer(r"<a\b[^>]*target=\"_blank\"[^>]*>", APP, re.S) if "noopener" not in m.group(0)]
  assert not bad, bad


def test_close_icon_buttons_have_aria_label():
  """TC-AHS-10: 글자 없이 ✕ 만 있는 닫기 단추에는 aria-label 이 있다."""
  bad = []
  for m in re.finditer(r"<button\b([^>]*)>\s*✕\s*</button>", APP, re.S):
    if "aria-label" not in m.group(1) and "title=" not in m.group(1):
      bad.append(m.group(1)[:60].strip())
  assert not bad, bad


def test_module_top_bindings_exist_in_app_html():
  """TC-AHS-11: 모듈 로드 때 `document.getElementById("x").addEventListener` (`?.` 없음)로 묶는 id 는 app.html 에 있다.

  없으면 그 모듈 전체가 null 오류로 멈춘다. 31곳 중 JS 가 직접 만드는 요소는 허용 목록(DYNAMIC)에 이유와 함께 둔다."""
  ids = set(ID_ATTR.findall(APP))
  pat = re.compile(r'^document\.getElementById\("([^"]+)"\)\.addEventListener', re.M)
  bound = []
  for p in sorted(JS_DIR.glob("*.js")):
    bound += [(p.name, i) for i in pat.findall(p.read_text(encoding="utf-8"))]
  assert len(bound) >= 25
  DYNAMIC = set()   # JS 가 만드는 요소가 생기면 여기에 (파일, id) 로 이유와 함께
  missing = [(f, i) for f, i in bound if i not in ids and (f, i) not in DYNAMIC]
  assert not missing, f"app.html 에 없는데 모듈 로드 때 묶는 id: {missing}"
