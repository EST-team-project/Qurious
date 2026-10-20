"""TC-HT — 화면 사용법 창(public/js/howto.js · howtoview.js) · 2026-10-16

결정(Figma 「투자 대시보드 · 메뉴 정리」 05 결정 기록 ④ ~ ⑧ · 설계 docs/화면/설계안/2026-10-16-사용법모달/설계안.md):
가운데 창 · 화면 맨 위 윗줄 단추 · 영상이 없으면 칸을 숨김 · 창 크기는 화면마다 · 끝줄 = 그 화면의 개념 학습 장 + 용어사전 + 목차.

무엇을 지키나
1. 기초 코드 지킴이 — core.js 의 renderViewGuide 는 window.QHowto 에 넘기기만 한다. 옛 접이식 · 열림 기억(localStorage)
   · 기초 코드 판의 <dialog> 가 3-way 반영으로 소리 없이 돌아오면 깨진다. (TC-HT-01)
2. 연결 — app.html 이 howto.css · howto.js 를 싣고, howto.js 가 main.js 보다 먼저 돈다(첫 화면을 그릴 때 QHowto 가 있어야). (TC-HT-02)
3. 자료 — 메뉴의 앱 안 화면(바깥 주소 · 소제목 빼고)은 모두 사용법 글이 있고, 글의 용어 키는 모두 TERMS 에 있다 · 글에 「실시간」 낱말이 없다(지연 시세 · 지난 종가를 실시간이라 부르지 않는다 — UI 명세서 2.2절 ① · 2026-10-20). (TC-HT-03)
4. 무엇도 브라우저에 남기지 않는다(열림 기억을 버림). (TC-HT-04)
5. 두 단 화면(거시경제 지표)이 윗줄을 두 단 안으로 옮기지 않는다. (TC-HT-05)
6. 창 안 내용 — node 로 howtoview.js 를 그대로 돌린다: 요약 · 단계 번호 · TERMS 에 있는 용어만 칩 · 글은 글자로(꺾쇠 주입 막음) ·
   영상은 있을 때만 · 끝줄 셋. (TC-HT-06)
7. 윗줄 · 창 크기 — 지금 위치(묶음 › 화면) · 영상 단추는 있을 때만 · 차트 · 분석 화면과 영상이 있으면 「크게」 · 아니면 글 양 문턱. (TC-HT-07)
8. 개념 학습 장 — 이어 준 장이 실제로 있고, 적어 둔 제목이 장 머리말 제목과 같다 · 표의 화면이 모두 사용법이 있는 화면이다. (TC-HT-08)
9. 창 동작의 줄 — showModal(뒤 화면 막음 · 초점 가둠은 브라우저) · Esc 는 창 안 용어 카드부터 · 화면을 바꾸면 닫힘 · 닫으면 단추로 초점 ·
   용어 받기는 용어 서랍과 같은 함수 한 곳(termcard.js fillTermCard). (TC-HT-09)
   손으로 보는 것(창 · Esc · 초점 · 폭 넷 · 다시 그리는 화면)은 tests/e2e/howto_dialog.py.
10. 영상 표 읽기(D132 첫 단계 · 2026-10-18) — videoOf 는 표의 판 · 그 화면 줄 · 우리 폴더 주소만 받고, 그 화면이 나오는 장부터
    (차트 패턴 = 장 2) · 장 차례는 표 범위 안으로 · 길이는 브라우저처럼 내림. 표가 없거나 꼴이 틀리면 null. (TC-HT-10)
11. 재생 칸 — 그 장의 시각부터(#t=) · 장 단추(지금 장 aria-current) · 장 표시 「② / 3」 · 장 제목은 글자로 · 자막 트랙은 켜지 않음
    (자막이 영상에 들어 있어 겹친다) · 창 바닥 고지 한 줄. (TC-HT-11)
12. 창의 영상 줄 — 영상 표는 한 번(no-cache) · 받으면 그린 윗줄을 다시 · 로그인 전(401)은 나중에 다시 · 창을 닫으면 영상 멈춤 ·
    장 단추가 시각을 옮긴다. 손 몫(재생 · 장부터 · 장 단추 · Range · 404 숨김 · 390)은 tests/e2e/howto_video.py. (TC-HT-12)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
CORE = PUB / "js" / "core.js"
HOWTO = PUB / "js" / "howto.js"
VIEW = PUB / "js" / "howtoview.js"
LEARN = PUB / "learn" / "content"
APP_HTML = PUB / "app.html"
CALENDAR = PUB / "js" / "calendar.js"
TERMCARD = PUB / "js" / "termcard.js"
COMMON = PUB / "js" / "common.js"
HOWTO_CSS = PUB / "css" / "howto.css"
#: 결정 ④ 의 까닭(차트 · 시각 자료 자리)을 대표하는 화면 — 표(howtoview.js WIDE_VIEWS)에서 빠지면 깨진다
CHART_EXAMPLES = ("trading-chart", "us-chart", "robo-patterns", "quant-backtest", "ml-compare", "data-status", "robo-portfolio")


def _block(src: str, start: str, end: str) -> str:
    i = src.index(start)
    return src[i:src.index(end, i)]


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    return node


# core.js 의 자료 셋을 node 로 꺼낸다(시제품 추출기와 같은 꼴 — 실행하지 않고 객체 글자만 읽는다)
NODE_DATA = r"""
import { readFileSync } from "node:fs";
const src = readFileSync(process.argv[2], "utf8");
const grab = (name) => {
  const s = src.indexOf(`const ${name} = {`);
  const e = src.indexOf("\n};", s);
  return Function(`"use strict"; return ${src.slice(s + `const ${name} = `.length, e + 2)}`)();
};
process.stdout.write(JSON.stringify({ guides: grab("VIEW_GUIDES"), terms: grab("TERMS"), menus: grab("GNB_MENUS") }));
"""


@pytest.fixture(scope="module")
def data(tmp_path_factory) -> dict:
    node = _node()
    script = tmp_path_factory.mktemp("howto") / "data.mjs"
    script.write_text(NODE_DATA, encoding="utf-8")
    run = subprocess.run([node, str(script), str(CORE)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _run(tmp_path: Path, body: str) -> dict:
    """howtoview.js 를 node 로 불러 body(그 안에서 out 을 채움)를 돌린다 — 화면 파일을 바꾸지 않는다."""
    node = _node()
    script = tmp_path / "run.mjs"
    script.write_text(f'import * as hv from "{VIEW.resolve().as_uri()}";\nconst out = {{}};\n{body}\n'
                      "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    run = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_core_only_hands_over_to_howto():
    """TC-HT-01 · core.js 는 넘기기만 — 옛 접이식 · 열림 기억 · 기초 코드 판의 <dialog> 가 돌아오면 깨진다"""
    core = CORE.read_text(encoding="utf-8")
    fn = _block(core, "function renderViewGuide", "\n}\n")
    assert "window.QHowto?.render(viewKey, VIEW_GUIDES[viewKey]" in fn, "자료를 넘긴다"
    assert "terms: TERMS" in fn and "label: item?.label" in fn and "group:" in fn
    for bad in ("localStorage", "vg_open_", "<dialog", "showModal", "view-guide-toggle", "innerHTML"):
        assert bad not in fn, f"renderViewGuide 에 {bad}"
    assert "VIEW_GUIDE_OPEN_KEY" not in core, "열림 기억 열쇠는 지웠다"
    for f in (HOWTO, VIEW):
        assert '"/js/core.js"' not in f.read_text(encoding="utf-8"), f"{f.name} 가 core.js 를 가져오면 화면 시작 차례가 바뀐다"


def test_app_html_loads_howto_before_main():
    """TC-HT-02 · app.html 이 사용법 모양 · 모듈을 싣고, 모듈은 main.js 보다 먼저"""
    html = APP_HTML.read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="/css/howto.css" />' in html
    i_howto = html.index('<script type="module" src="/js/howto.js"></script>')
    i_main = html.index('<script type="module" src="/js/main.js"></script>')
    assert i_howto < i_main, "첫 화면을 그릴 때 window.QHowto 가 있어야 한다"
    assert HOWTO_CSS.exists() and HOWTO.exists() and VIEW.exists()


def test_every_menu_screen_has_a_guide(data):
    """TC-HT-03 · 메뉴의 앱 안 화면은 모두 사용법 글이 있고 · 글의 용어 키는 모두 TERMS 에"""
    guides, terms = data["guides"], data["terms"]
    screens = [it["key"] for m in data["menus"].values() for it in m["items"] if it.get("key") and not it.get("href")]
    assert len(screens) >= 70
    missing = [k for k in screens if k not in guides]
    assert missing == [], f"사용법 글이 없는 화면 {missing}"
    bad_terms = [(k, t) for k, g in guides.items() for t in g.get("relatedTerms", []) if t not in terms]
    assert bad_terms == [], f"TERMS 에 없는 용어 키 {bad_terms}"
    for k, g in guides.items():
        assert g["summary"].strip() and g["steps"], f"{k} 요약 · 단계"
    # UI 명세서 2.2절 ① — 지연 시세 · 지난 종가를 「실시간」 이라 부르지 않는다(2026-10-20 · 사용법 글 셋을 고침)
    live = [k for k, g in guides.items() if "실시간" in g["summary"] + "".join(g["steps"])]
    assert live == [], f"「실시간」 낱말이 남은 사용법 글 {live}"


def test_nothing_is_stored_in_the_browser():
    """TC-HT-04 · 열림 기억을 버렸다 — 사용법 두 파일에 브라우저 저장소가 없다"""
    for f in (HOWTO, VIEW):
        src = f.read_text(encoding="utf-8")
        for bad in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
            assert bad not in src, f"{f.name} 에 {bad}"


def test_two_column_screen_keeps_the_top_row_outside():
    """TC-HT-05 · 두 단으로 옮기는 화면(거시경제 지표)은 윗줄을 옮기지 않는다"""
    cal = CALENDAR.read_text(encoding="utf-8")
    move = _block(cal, "function mountSideCard", "\n}\n")
    assert '!c.classList.contains("q-howto-top")' in move, "윗줄이 두 단 안으로 들어가면 오른쪽 일정 카드 옆으로 밀린다"


def test_dialog_content(tmp_path, data):
    """TC-HT-06 · 창 안 — 요약 · 단계 번호 · 있는 용어만 칩 · 글은 글자로 · 영상은 있을 때만 · 끝줄 셋"""
    guide = {"summary": "요약 <b>굵게</b> & 끝", "steps": ["첫째 <img src=x onerror=alert(1)>", "둘째 & 셋"],
             "relatedTerms": ["mdd", "없는용어", "sharpe"]}
    terms = {k: data["terms"][k] for k in ("mdd", "sharpe")}
    video = {"src": "/help/media/agent-products.webm", "captions": "/help/media/agent-products.ko.vtt", "duration": "0:45"}
    out = _run(tmp_path, f"""
const g = {json.dumps(guide, ensure_ascii=False)};
const terms = {json.dumps(terms, ensure_ascii=False)};
const v = {json.dumps(video)};
out.plain = hv.howtoHtml("agent-products", g, {{ terms, label: "투자 성향별 상품 안내" }});
out.video = hv.howtoHtml("agent-products", g, {{ terms, label: "투자 성향별 상품 안내", video: v }});
out.nolabel = hv.howtoHtml("mypage", {{ summary: "s", steps: ["a"] }}, {{ terms }});
out.glossary = hv.howtoHtml("fin-glossary", {{ summary: "s", steps: ["a"] }}, {{ terms }});
""")
    h = out["plain"]
    assert '<h2 id="q-howto-title" tabindex="-1">투자 성향별 상품 안내</h2>' in h, "창 제목 = 화면 이름(카드 제목을 잡지 않음)"
    assert "요약 &lt;b&gt;굵게&lt;/b&gt; &amp; 끝" in h and "<b>굵게</b>" not in h
    assert "&lt;img src=x onerror=alert(1)&gt;" in h and "<img" not in h, "단계 글은 글자로"
    assert h.count('<span class="q-howto-n" aria-hidden="true">') == 2, "단계 수만큼 번호"
    assert 'data-howto-term="mdd"' in h and 'data-howto-term="sharpe"' in h and "없는용어" not in h, "TERMS 에 있는 용어만"
    assert "q-howto-video" not in h, "영상이 없으면 칸을 숨긴다(결정 ⑥)"
    assert '<a class="q-howto-link" href="#learn/funds-etf" data-howto="leave">개념 학습 「펀드와 ETF」 →</a>' in h, "개념 학습은 앱 안 화면(2026-10-19)"
    assert '<a class="q-howto-link" href="#fin-glossary" data-howto="leave">용어사전에서 더 찾기 →</a>' in h
    assert '<a class="q-howto-link" href="#learn-home" data-howto="leave">학습 홈 →</a>' in h
    assert h.index("q-howto-summary") < h.index("이렇게 써요") < h.index("이 화면의 용어") < h.index("q-howto-foot"), "차례"
    hv_ = out["video"]
    assert 'data-howto-video="agent-products"' in hv_ and "영상으로 보기" in hv_ and "0:45 · 한국어 자막" in hv_
    assert hv_.index("q-howto-summary") < hv_.index("q-howto-video") < hv_.index("이렇게 써요"), "영상 칸은 요약 바로 아래"
    assert '>이 화면</h2>' in out["nolabel"] and "개념 학습 「" not in out["nolabel"], "이름이 없으면 「이 화면」 · 이어 줄 장이 없으면 목차만"
    assert "이 화면의 용어" not in out["nolabel"], "용어가 없으면 소제목도 없다"
    assert "용어사전에서 더 찾기" not in out["glossary"], "용어사전 화면에서는 자기 자신으로 가는 줄을 빼다"
    # 창 바닥 고지 한 줄(10-1 시안 ④) — 영상이 있든 없든 끝줄 아래
    for html in (h, hv_, out["nolabel"]):
        assert '<p class="q-howto-note">투자 권유가 아닙니다 · 투자 판단과 결과는 이용자 몫입니다</p>' in html
        assert html.index("q-howto-foot") < html.index("q-howto-note"), "고지는 끝줄 아래"


def test_top_row_and_sizes(tmp_path, data):
    """TC-HT-07 · 윗줄(지금 위치 · 영상은 있을 때만) · 창 크기(차트 · 분석 화면과 영상은 「크게」 · 그 밖은 글 양 문턱)"""
    guides = data["guides"]
    out = _run(tmp_path, f"""
const guides = {json.dumps(guides, ensure_ascii=False)};
out.row = hv.topRowHtml("agent-products", {{ group: "로보 어드바이저", label: "투자 성향별 상품 안내" }});
out.rowNoGroup = hv.topRowHtml("x", {{ label: "<화면>" }});
out.rowVideo = hv.topRowHtml("data-status", {{ group: "데이터", label: "데이터 관제", video: {{ src: "a.webm", duration: "0:45" }} }});
out.sizes = Object.fromEntries(Object.entries(guides).map(([k, g]) => [k, hv.sizeOf(k, g)]));
out.amount = Object.fromEntries(Object.entries(guides).map(([k, g]) => [k, hv.textAmount(g)]));
out.withVideo = hv.sizeOf("fin-topic-funds", guides["fin-topic-funds"], {{ video: {{ src: "a" }} }});
out.limits = hv.SIZE_LIMITS; out.px = hv.SIZE_PX; out.wide = [...hv.WIDE_VIEWS];
const mk = (n) => ({{ summary: "가".repeat(n), steps: [], relatedTerms: [] }});
out.edges = [119, 120, 259, 260].map((n) => hv.sizeOf("x", mk(n)));
""")
    row = out["row"]
    assert '<span class="q-howto-path-group">로보 어드바이저</span>' in row and 'aria-current="page">투자 성향별 상품 안내</span>' in row
    assert 'data-howto-open="guide"' in row and 'aria-haspopup="dialog"' in row and 'aria-controls="q-howto-dialog"' in row
    assert 'data-howto-open="video"' not in row, "영상이 없으면 윗줄에 영상 단추도 없다"
    assert "q-howto-path-group" not in out["rowNoGroup"] and "&lt;화면&gt;" in out["rowNoGroup"]
    assert 'data-howto-open="video"' in out["rowVideo"] and "영상 0:45" in out["rowVideo"]
    assert out["px"] == {"s": 560, "m": 680, "l": 840} and out["limits"] == {"s": 120, "m": 260}
    assert out["edges"] == ["s", "m", "m", "l"], "문턱 — 120 미만 작게 · 260 미만 보통 · 그 위 크게"
    assert set(out["sizes"].values()) <= {"s", "m", "l"} and len(out["sizes"]) == len(guides)
    for k in out["wide"]:
        assert out["sizes"][k] == "l", f"차트 · 분석 화면 {k} 은 「크게」(결정 ④ 의 까닭 — 시각 자료 자리)"
    for k, n in out["amount"].items():
        if k in out["wide"]:
            continue
        want = "s" if n < 120 else "m" if n < 260 else "l"
        assert out["sizes"][k] == want, (k, n, out["sizes"][k])
    assert out["withVideo"] == "l", "영상이 생기면 「크게」"
    # 화면마다 다르게(결정 ⑦) — 셋 모두 쓰인다 · 차트 · 분석 화면의 대표는 늘 「크게」
    assert {"s", "m", "l"} <= set(out["sizes"].values())
    for k in CHART_EXAMPLES:
        assert k in out["wide"] and out["sizes"][k] == "l", f"차트 · 분석 화면 {k}"
    # 창 폭은 JS(SIZE_PX)와 CSS(--howto-w) 두 곳에 적힌다 — 어긋나면 크기를 정한 뜻과 실제 폭이 다르다
    css = HOWTO_CSS.read_text(encoding="utf-8")
    for size, px in out["px"].items():
        assert f".q-howto-dialog--{size} {{ --howto-w: {px}px; }}" in css, f"howto.css 의 {size} 폭이 {px}px 이 아니다"


def test_learn_links_point_to_real_chapters(tmp_path, data):
    """TC-HT-08 · 이어 준 개념 학습 장이 있고 · 제목이 장 머리말과 같고 · 표의 화면은 사용법이 있는 화면"""
    out = _run(tmp_path, "out.learn = hv.LEARN_OF; out.wide = [...hv.WIDE_VIEWS];")
    guides = data["guides"]
    assert len(out["learn"]) >= 30
    for view, ch in out["learn"].items():
        assert view in guides, f"사용법이 없는 화면 {view}"
        md = LEARN / f"{ch['slug']}.md"
        assert md.exists(), f"없는 장 {ch['slug']}"
        head = md.read_text(encoding="utf-8").split("---")[1]
        full = re.search(r"^title:\s*(.+)$", head, re.M).group(1).strip()
        assert full.split(" — ")[0].strip() == ch["title"], (view, ch["title"], full)
    for view in out["wide"]:
        assert view in guides, f"차트 · 분석 화면 표에 사용법이 없는 화면 {view}"
    # 상품 안내 화면이 머리에서 잇는 장(TC-PD-07)과 사용법 끝줄의 장이 어긋나지 않게
    assert out["learn"]["agent-products"]["slug"] == "funds-etf"


def test_dialog_behavior_lines():
    """TC-HT-09 · 창 동작의 줄 — showModal · Esc 는 창 안 용어부터 · 화면을 바꾸면 닫힘 · 닫으면 단추로 · 용어 받기는 한 곳"""
    src = HOWTO.read_text(encoding="utf-8")
    assert "dlg.showModal()" in src and ".show()" not in src, "뒤 화면 막음 · 초점 가둠은 브라우저(showModal)"
    cancel = _block(src, 'addEventListener("cancel"', "});")
    assert "termViewOpen()" in cancel and "e.preventDefault()" in cancel and "backToGuide()" in cancel, "Esc 는 창 안 용어 카드부터"
    closed = _block(src, 'addEventListener("close"', "});")
    assert "trigger?.isConnected" in closed and "trigger.focus()" in closed, "닫으면 연 단추로 초점"
    changed = _block(src, '"lumina:view-changed"', "});")
    assert "dialog.close()" in changed and "trigger = null" in changed, "화면을 바꾸면 닫고 숨은 단추로는 초점을 돌리지 않는다"
    assert 'import { fillTermCard } from "/js/termcard.js"' in src and "/api/glossary" not in src, "용어 받기는 용어 서랍과 같은 함수"
    card = TERMCARD.read_text(encoding="utf-8")
    show = _block(card, "async function show(", "\n}\n")
    assert "fillTermCard(body, key" in show and "/api/glossary" not in show, "용어 서랍도 같은 함수(받기 한 곳)"
    assert card.count("/api/glossary/${encodeURIComponent(key)}") == 1
    assert 'data-howto="leave"' in VIEW.read_text(encoding="utf-8") and 't.dataset.howto === "leave"' in src, "앱 안 다른 화면으로 가는 줄은 창을 닫고 간다"


def test_escape_matches_common(tmp_path):
    """TC-HT-06 덧 · howtoview.js 의 esc 는 common.js 의 escHtml 과 같은 규칙(node 시험에서 쓰려고 가져오지 않았다)"""
    def chain(src: str, start: str) -> list[tuple[str, str]]:
        body = _block(src, start, "\n}\n")
        return re.findall(r'\.replace\(/(.+?)/g, "(.+?)"\)', body)
    mine = chain(VIEW.read_text(encoding="utf-8"), "export function esc(")
    theirs = chain(COMMON.read_text(encoding="utf-8"), "export function escHtml(")
    assert mine == theirs and len(mine) == 5, (mine, theirs)


# 영상 표 본보기 — tools/demo/help_videos.py 가 쓰는 꼴(판 1). 신호로 종목 살피기 = 스크리닝(장 1) → 차트 패턴(장 2 · 15.48초)
_TAG = "0123456789ab"
MANIFEST = {
    "format": 1,
    "videos": {
        "A": {"title": "t", "src": f"/help/media/A.webm?v={_TAG}", "captions": f"/help/media/A.ko.vtt?v={_TAG}",
              "chapters_src": f"/help/media/A.chapters.vtt?v={_TAG}", "duration": 38.64,
              "chapters": [{"title": "하나", "start": 0, "end": 15.48, "poster": f"/help/media/A.ch1.jpg?v={_TAG}"},
                           {"title": "둘 <b>굵게</b>", "start": 15.48, "end": 30.6, "poster": f"/help/media/A.ch2.jpg?v={_TAG}"},
                           {"title": "셋", "start": 30.6, "end": 38.36, "poster": ""}]},
        "EVIL": {"src": "https://example.com/x.webm", "chapters": [{"title": "x", "start": 0, "end": 1}]},
        "UP": {"src": "/help/media/../../.env", "chapters": [{"title": "x", "start": 0, "end": 1}]},
        "NOCH": {"src": f"/help/media/N.webm?v={_TAG}", "chapters": []},
    },
    "views": {"robo-screening": {"video": "A", "chapter": 0}, "robo-patterns": {"video": "A", "chapter": 1},
              "far": {"video": "A", "chapter": 9}, "neg": {"video": "A", "chapter": -3},
              "evil": {"video": "EVIL", "chapter": 0}, "up": {"video": "UP", "chapter": 0},
              "noch": {"video": "NOCH", "chapter": 0}, "ghost": {"video": "NONE", "chapter": 0}},
}


def test_video_of_reads_the_table(tmp_path):
    """TC-HT-10 · 영상 표 읽기 — 판 · 그 화면 줄 · 우리 폴더 주소만 · 그 화면이 나오는 장부터 · 장 차례는 범위 안 · 길이는 내림"""
    out = _run(tmp_path, f"""
const m = {json.dumps(MANIFEST, ensure_ascii=False)};
out.first = hv.videoOf("robo-screening", m);
out.mid = hv.videoOf("robo-patterns", m);
out.far = hv.videoOf("far", m); out.neg = hv.videoOf("neg", m);
out.bad = ["evil", "up", "noch", "ghost", "missing"].map((k) => hv.videoOf(k, m));
out.none = [hv.videoOf("robo-patterns", null), hv.videoOf("robo-patterns", {{ ...m, format: 2 }}), hv.videoOf("robo-patterns", {{}})];
const A = m.videos.A;
out.badPoster = hv.videoOf("robo-patterns", {{ ...m, videos: {{ ...m.videos, A: {{ ...A, chapters: A.chapters.map((c) => ({{ ...c, poster: "javascript:alert(1)" }})) }} }} }});
out.fmt = [0, 0.9, 15.48, 30.6, 59.99, 63, 3600.2].map(hv.fmtTime);
out.at = [0, 15.0, 15.46, 15.48, 30, 31, 99].map((t) => hv.chapterIndexAt(A.chapters, t));
out.badge = [hv.chapterBadge(0, 3), hv.chapterBadge(1, 3), hv.chapterBadge(25, 30)];
out.url = hv.VIDEO_MANIFEST_URL;
""")
    f, m = out["first"], out["mid"]
    assert f["startChapter"] == 0 and f["start"] == 0 and f["poster"].endswith("A.ch1.jpg?v=" + _TAG)
    assert f["src"] == f"/help/media/A.webm?v={_TAG}" and f["duration"] == "0:38" and f["durationSec"] == 38.64
    assert m["startChapter"] == 1 and m["start"] == 15.48 and m["poster"].endswith("A.ch2.jpg?v=" + _TAG), "그 화면이 나오는 장부터(차트 패턴 = 장 2)"
    assert out["far"]["startChapter"] == 2 and out["neg"]["startChapter"] == 0, "표의 장 차례가 범위 밖이면 끝 · 처음으로"
    assert out["bad"] == [None] * 5, "바깥 주소 · 경로 오르기 · 장 없음 · 없는 영상 · 없는 화면은 숨김"
    assert out["none"] == [None] * 3, "표가 없거나 판이 다르면 숨김(결정 ⑥)"
    assert out["badPoster"]["poster"] == "" and out["badPoster"]["src"], "우리 폴더 밖 그림 주소는 버린다"
    assert out["fmt"] == ["0:00", "0:00", "0:15", "0:30", "0:59", "1:03", "60:00"], "브라우저 재생 막대처럼 내림"
    assert out["at"] == [0, 0, 1, 1, 1, 2, 2], "지금 장 = 시작이 지금보다 늦지 않은 마지막 장"
    assert out["badge"] == ["① / 3", "② / 3", "26 / 30"]
    assert out["url"] == "/help/videos.json"


def test_player_html(tmp_path):
    """TC-HT-11 · 재생 칸 — 그 장의 시각부터 · 장 단추(지금 장 aria-current) · 장 표시 · 장 제목은 글자로 · 자막 트랙은 켜지 않음"""
    out = _run(tmp_path, f"""
const m = {json.dumps(MANIFEST, ensure_ascii=False)};
out.mid = hv.playerHtml(hv.videoOf("robo-patterns", m));
out.first = hv.playerHtml(hv.videoOf("robo-screening", m));
out.slot = hv.howtoHtml("robo-patterns", {{ summary: "s", steps: ["a"] }}, {{ video: hv.videoOf("robo-patterns", m) }});
""")
    h = out["mid"]
    assert f'src="/help/media/A.webm?v={_TAG}#t=15.48"' in h, "그 화면이 나오는 장의 시각부터(미디어 조각 #t=)"
    assert f'poster="/help/media/A.ch2.jpg?v={_TAG}"' in h, "첫 그림 = 그 장의 제목 카드"
    assert f'<track kind="captions" srclang="ko" label="한국어" src="/help/media/A.ko.vtt?v={_TAG}">' in h
    assert "default" not in h, "자막은 영상에 들어 있다 — 트랙을 켜면 같은 글이 두 줄로 겹친다"
    assert f'<track kind="chapters" srclang="ko" label="장" src="/help/media/A.chapters.vtt?v={_TAG}">' in h
    assert h.count('data-howto-chap="') == 3 and h.count('aria-current="true"') == 1 and 'data-howto-chap="1" aria-current="true"' in h
    assert "둘 &lt;b&gt;굵게&lt;/b&gt;" in h and "<b>굵게</b>" not in h, "장 제목은 글자로"
    assert "<small>0:00</small>" in h and "<small>0:15</small>" in h and "<small>0:30</small>" in h
    assert '<span class="q-howto-chapbadge" aria-hidden="true">② / 3</span>' in h
    assert 'role="group" aria-label="장으로 가기"' in h and h.index("q-howto-stage") < h.index("q-howto-chaps"), "장 단추는 영상 아래"
    f = out["first"]
    assert "#t=" not in f and 'data-howto-chap="0" aria-current="true"' in f and "① / 3" in f, "처음부터 트는 화면은 시각 조각 없이"
    s = out["slot"]
    assert "영상으로 보기" in s and "0:38 · 한국어 자막" in s and "<video" not in s, "창을 열면 칸만 — 누르면 그 자리에서 튼다"


def test_dialog_video_lines():
    """TC-HT-12 · 창의 영상 줄 — 표는 한 번(no-cache) · 받으면 다시 그림 · 401 은 나중에 · 닫으면 멈춤 · 장 단추가 시각을 옮김"""
    src = HOWTO.read_text(encoding="utf-8")
    load = _block(src, "async function loadVideos()", "\n}\n")
    assert 'fetch(VIDEO_MANIFEST_URL, { cache: "no-cache"' in load, "다시 녹화한 표를 놓치지 않게 매번 묻기"
    assert "r.status === 401" in load and "retryAt = Date.now() + 60_000" in load, "로그인 전이면 1분 뒤 다시"
    assert "for (const [k, d] of DATA) render(k, d.guide, d)" in load, "표가 늦게 와도 그린 윗줄에 단추가 나타나게"
    ensure = _block(src, "function ensureVideos()", "\n}\n")
    assert 'videosState === "idle"' in ensure and 'videosState === "later" && Date.now() >= retryAt' in ensure
    render = _block(src, "function render(", "\n}\n")
    assert "ensureVideos();" in render and "video: videoFor(viewKey)" in render
    assert "const video = videoFor(viewKey);" in _block(src, "function open(", "\n}\n")
    closed = _block(src, 'addEventListener("close"', "});")
    assert 'dialog.querySelectorAll("video").forEach((v) => v.pause())' in closed, "닫힌 창 뒤에서 영상이 돌지 않게"
    play = _block(src, "function playVideo(", "\n}\n")
    assert "wrap.innerHTML = playerHtml(v);" in play and "video.currentTime = ch.start;" in play
    assert 'video.addEventListener("timeupdate", mark);' in play and "chapterIndexAt(v.chapters, video.currentTime)" in play
    assert "VIDEOS" not in src and "VIDEOS" not in VIEW.read_text(encoding="utf-8"), "고정 영상 표는 없앴다 — 표는 영상 폴더 한 곳"
    # 좁은 화면 경계는 CSS 두 곳(창 화면 전체 · 장 단추 세로)이 같은 값 — 어긋나면 창은 전체인데 단추는 가로로 넘친다
    css = HOWTO_CSS.read_text(encoding="utf-8")
    edges = re.findall(r"@media \(max-width: (\d+)px\) \{\s*/\*[^*]*\*/\s*\.q-howto-(dialog|chaps) \{", css)
    assert sorted(edges) == [("760", "chaps"), ("760", "dialog")], edges
    assert '.q-howto-chap[aria-current="true"] { border-color: var(--accent);' in css, "지금 장은 파랑"
