"""TC-CLV · 개념 학습 앱 안 화면 (2026-10-19 · 사용자 「학습을 금융필수지식 + 개념학습으로 하기로 했는데 분리되어 있는 오류」)

개념 학습은 따로 된 쪽(/learn/ · 왼쪽 트리의 「새 화면」)에서 위 탭 「학습」 안의 앱 화면(public/js/conceptlearn.js)으로 옮겼다.
  1. 메뉴 — 개념 학습 묶음의 항목은 모두 앱 안 화면(href 없음)이고 app.html 에 자리 · 진입 훅이 있다
  2. 위 탭 — 「학습」 이 개념 학습 묶음에서도 켜진다(TAB_OF)
  3. 장 주소 — #learn/<slug> 이름 규칙이 서버(SLUG_RE)와 같고, 받은 주소를 화면 키로 바꾸며 장 이름은 기록 칸에(뒤로 가기)
  4. 거르기 — 장 글은 DOMPurify 로 거른 뒤 그린다(폼 · 입력 · style 막음)
  5. 다른 화면 — 앱 화면이 개념 학습을 /learn/ 새 화면으로 열지 않는다(관리자 팀 자료 원문 링크 하나만)
화면 동작(뒤로 가기 · 390 폭 · 그림)은 손 시험 tests/e2e/learn_inapp.py 가 본다.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
CL = PUB / "js" / "conceptlearn.js"


def _read(rel: str) -> str:
  return (PUB / rel).read_text(encoding="utf-8")


def _block(src: str, start: str, end: str) -> str:
  i = src.index(start)
  return src[i:src.index(end, i)]


def test_learn_menu_items_are_app_screens():
  """TC-CLV-01 · 학습 한 묶음(위 탭 「학습」 = finance · 2026-10-20 안 A) — 첫 줄이 학습 홈 · 네 갈래 화면(강의실 · 개발 개념 ·
  파이썬 중급 · 특강)과 사용법 영상이 모두 앱 안 화면(href 없음) · 장 한 편 · 부 목차는 메뉴 줄 없이 따를 줄(VIEW_PARENT)로 ·
  app.html 자리 · 진입 훅 · 옛 개념 학습 묶음 없음."""
  core = _read("js/core.js")
  menu = _block(core, "\n  finance: {", "\n  },")
  keys = re.findall(r'\{ key: "([^"]+)"', menu)
  assert keys[0] == "learn-home", "위 탭 「학습」 을 누르면 학습 홈이 열린다(묶음의 첫 화면)"
  assert {"fin-lectures", "fin-glossary", "learn-dev", "learn-python", "learn-special", "learn-videos"} <= set(keys)
  assert "learn-page" not in keys, "「장 읽기」 메뉴 줄은 뺐다(사용자 10-20 「굳이 필요 없는 화면」) — 장은 갈래 목차에서 연다"
  assert re.search(r'^const VIEW_PARENT = \{ "learn-page": "learn-home", "learn-part": "learn-home" \};', core, re.M)
  assert "href:" not in menu, "학습은 앱 안 화면 — 바깥 주소(/learn/)로 나가지 않는다"
  assert "\n  learn: {" not in core, "개념 학습 묶음은 「학습」 안으로 합쳤다(두 묶음이 겹쳐 헷갈림 — 사용자 10-20)"
  app = _read("app.html")
  for key, root in (("learn-videos", "hv-root"), ("learn-home", "cl-home"), ("learn-page", "cl-page"),
                    ("learn-dev", "cl-dev"), ("learn-python", "cl-python"), ("learn-special", "cl-special"), ("learn-part", "cl-part")):
    assert f'<div class="view" data-view="{key}">' in app and f'<div id="{root}"></div>' in app, key
  main = _read("js/main.js")
  assert 'from "/js/conceptlearn.js"' in main
  assert re.search(r"^\s+onConceptLearnViewActivated\(view\);", main, re.M), "화면 진입 훅"
  assert 'from "/js/helpvideos.js"' in main and re.search(r"^\s+onHelpVideosViewActivated\(view\);", main, re.M), "사용법 영상 진입 훅"
  cl = CL.read_text(encoding="utf-8")
  for view in ("learn-dev", "learn-python", "learn-special", "learn-home", "learn-part"):
    assert f'if (view === "{view}")' in cl, f"{view} 진입"


def test_learn_tab_lights_for_both_groups():
  """TC-CLV-02 · 위 탭 「학습」(finance)은 학습 묶음 하나의 지름길 — 위 탭이 따로 없는 묶음 표(TAB_OF)는 비어 있고,
  탭을 고르는 줄은 그 표를 거친다(묶음이 다시 생기면 표에 한 줄 · 2026-10-20 안 A)."""
  core = _read("js/core.js")
  assert re.search(r"^const TAB_OF = \{\};", core, re.M)
  nav = _block(core, "function navigate(viewKey)", "\n}\n")
  assert re.search(r"^\s+const tabGnb = TAB_OF\[currentGnb\] \|\| currentGnb;", nav, re.M)
  assert "el.dataset.gnb === tabGnb" in nav and "el.dataset.gnb === currentGnb" not in nav


def test_chapter_hash_follows_server_slug_rule():
  """TC-CLV-03 · #learn/<slug> 이름 규칙 = 서버 SLUG_RE · 받은 주소는 #learn-page 로 바꾸고 장 이름은 기록 칸에(뒤로 가기 · popstate)."""
  from app.services import learn_pages as lp
  src = CL.read_text(encoding="utf-8")
  m = re.search(r'^const SLUG = "([^"]+)";', src, re.M)
  assert m and lp.SLUG_RE.pattern == f"^{m.group(1)}$", "서버 장 이름 규칙과 같아야 한다"
  take = _block(src, "function takeHash()", "\n}\n")
  assert re.search(r'^\s+history\.replaceState\(\{ clSlug: m\[1\] \}, "", "#learn-page"\);', take, re.M)
  assert re.search(r'^window\.addEventListener\("hashchange",', src, re.M)
  assert re.search(r'^window\.addEventListener\("popstate",', src, re.M)


def test_chapter_markdown_is_sanitized():
  """TC-CLV-04 · 장 글은 DOMPurify 로 거른 뒤 그린다 — style · form · input · button · textarea · select 막음(팀 자료도 같은 길)."""
  fn = _block(CL.read_text(encoding="utf-8"), "function drawMarkdown(", "\n}\n")
  assert re.search(r"^\s+el\.innerHTML = window\.DOMPurify\.sanitize\(raw, \{", fn, re.M)
  forbid = re.search(r"FORBID_TAGS: \[([^\]]+)\]", fn)
  assert forbid and {t.strip(' "') for t in forbid.group(1).split(",")} >= {"style", "form", "input", "button", "textarea", "select"}


def test_app_screens_open_learning_in_the_app():
  """TC-CLV-05 · 앱 화면의 개념 학습 링크는 앱 안 주소(#learn/<slug> · #learn-home)다 — /learn/ 은 관리자 팀 자료 원문 링크 하나만."""
  out = []
  for f in sorted((PUB / "js").glob("*.js")):
    for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
      if 'href="/learn/' in line:
        out.append((f.name, line))
  assert len(out) == 1 and out[0][0] == "conceptlearn.js" and 'href="/learn/#/team"' in out[0][1], out
  hv = _read("js/howtoview.js")
  assert 'href="#learn/${esc(learn.slug)}" data-howto="leave"' in hv and 'href="#learn-home" data-howto="leave"' in hv
  assert 'href="/app.html#learn/${slug}" target="_blank" rel="noopener"' in _read("js/products.js")

def test_before_you_start_notice_one_place():
  """TC-CLV-06 · 「시작하기 전에」 고지(장 대장 F00 · 2026-10-20) — 글은 learnnotice.js 한 곳 · 강의실 맨 앞 카드 ·
  두 메뉴 화면 꼬리 한 줄 · 다섯 가지(모의 · 교육 · 실거래 · 투자 권유 · 기준일) · 「실시간」 낱말 없음(UI 명세서 2.2절)."""
  notice = _read("js/learnnotice.js")
  notice = notice[notice.index("export const NOTICE_TITLE"):]   # 머리 주석은 빼고 고지 글만 본다(주석의 낱말에 속지 않게)
  for word in ("모의", "교육", "실거래", "투자 권유", "기준일"):
    assert word in notice, word
  assert "실시간" not in notice
  fin, cl = _read("js/finlearn.js"), _read("js/conceptlearn.js")
  for src in (fin, cl):
    assert 'from "/js/learnnotice.js"' in src
    assert "투자 권유가 아닙니다 · 주문은 모의 계좌로만" not in src, "고지 글을 화면 파일에 다시 적지 않는다"
  hub = _block(fin, "async function renderHub(el)", "\n}\n")
  assert hub.index("fl-hub-head") < hub.index("${noticeCardHtml()}") < hub.index("4일 과정"), "강의실 맨 앞 카드"
  topic = _block(fin, "async function renderTopic(el, t", "\n}\n")
  assert "${noticeLineHtml()}" in topic, "주제 화면 꼬리 한 줄"
  assert "html += noticeLineHtml();" in _block(cl, "async function renderHome(el)", "\n}\n"), "개념 학습 목차 꼬리 한 줄"
  assert "${noticeLineHtml()}" in _block(cl, "async function renderPage(el, slug, h)", "\n}\n"), "장 화면 꼬리 한 줄"
