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
  """TC-CLV-01 · 개념 학습 메뉴 항목은 모두 앱 안 화면(href 없음 → 트리에 「새 화면」 꼬리표가 붙지 않음) · app.html 자리 · 진입 훅."""
  menu = _block(_read("js/core.js"), "\n  learn: {", "\n  },")
  assert re.findall(r'\{ key: "([^"]+)"', menu) == ["learn-home", "learn-page"]
  assert "href:" not in menu, "개념 학습은 앱 안 화면 — 바깥 주소(/learn/)로 나가지 않는다"
  app = _read("app.html")
  for key, root in (("learn-home", "cl-home"), ("learn-page", "cl-page")):
    assert f'<div class="view" data-view="{key}">' in app and f'<div id="{root}"></div>' in app, key
  main = _read("js/main.js")
  assert 'from "/js/conceptlearn.js"' in main
  assert re.search(r"^\s+onConceptLearnViewActivated\(view\);", main, re.M), "화면 진입 훅"


def test_learn_tab_lights_for_both_groups():
  """TC-CLV-02 · 위 탭 「학습」(finance)은 개념 학습 묶음(learn)에서도 켜진다 — 탭을 고르는 줄이 TAB_OF 를 거친다."""
  core = _read("js/core.js")
  assert re.search(r'^const TAB_OF = \{ learn: "finance" \};', core, re.M)
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
