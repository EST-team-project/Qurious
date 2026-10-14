"""종목 군집화 화면 시험 (TC-CUS-01 ~ 04) — `public/js/clusters.js` · `public/css/clusters.css` (2026-10-14).

정적 시험(브라우저 없이 파일 글을 본다) — 화면이 지키는 약속:
1. 강사님 파일에는 뿌리 칸 · 부르는 줄만 — app.html 의 ml-cluster 칸은 뿌리 하나 · main.js 가 진입 훅을 부른다(글자 그대로).
2. 고르기 값(대상 · 기간 · 방법 · 묶음 수)과 기준값은 서버 응답(choices · thresholds)에서만 — 화면 코드에 그 값이 없다.
3. 종목 이름 · 업종 · 까닭처럼 서버에서 온 글은 escHtml 을 거친다.
4. DF-108 재발 막기 — 어느 화면도 공통 api() 에 이미 JSON 으로 바꾼 본문을 넘기지 않는다(옛 군집 단추가 늘 422 였다).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "public" / "js" / "clusters.js"
APP = ROOT / "public" / "app.html"
MAIN = ROOT / "public" / "js" / "main.js"


def _code(src: str) -> str:
    """주석을 뺀 코드 — /* */ 덩어리와 // 줄 끝 주석(문자열 안 // 는 드물어 단순히)."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", ln) for ln in src.splitlines())


def test_wiring_root_only_and_entry_hook():
    """TC-CUS-01 · app.html 의 군집화 칸은 뿌리 하나 · CSS 링크 · 옛 단추 없음 · main.js 가져오기 + 훅 · 훅은 글자 그대로."""
    html = APP.read_text(encoding="utf-8")
    assert '<div class="view" data-view="ml-cluster"><div class="cu-root"></div></div>' in html
    assert 'href="/css/clusters.css"' in html and "mlk-run-btn" not in html
    main = MAIN.read_text(encoding="utf-8")
    assert 'import { onClusterViewActivated } from "/js/clusters.js";' in main
    assert re.search(r"^\s+onClusterViewActivated\(view\);", main, re.M)
    js = JS.read_text(encoding="utf-8")
    assert 'if (view !== "ml-cluster") return;' in js


def test_choices_and_thresholds_come_from_the_server():
    """TC-CUS-02 · GET /api/clusters 만 부른다 · 고르기 값 · 기준값을 코드에 적지 않는다(응답 choices · thresholds)."""
    code = _code(JS.read_text(encoding="utf-8"))
    assert "/api/clusters" in code and "/api/ml/cluster" not in code
    for lit in ('"1y"', '"2y"', '"3y"', "'1y'", "'3y'", '"quant31"', '"u401"', '"movement"', '"profile"'):
        assert lit not in code, f"화면 코드에 고르기 값 {lit} 이 있다 — 응답 choices 에서 읽는다"
    assert "ch.universe" in code and "ch.period" in code and "ch.method" in code and "ch.k.map" in code
    for num in ("0.25", "0.5)", "K_MAX", "k_max"):
        assert num not in code, f"기준값 {num} 을 화면에 적지 않는다"


def test_server_text_is_escaped():
    """TC-CUS-03 · 서버에서 온 이름 · 업종 · 까닭 · 문장 · 낱말은 escHtml 을 거쳐 그린다."""
    code = _code(JS.read_text(encoding="utf-8"))
    for field in ("p.name", "m.name", "m.sector", "e.reason", "p.sector", "d.reason", "d.notice", "d.source"):
        # 날 값을 그대로 끼우는 꼴(`${p.name}`)만 막는다 — `${m.sector ? … escHtml(m.sector) … : ""}` 같은 조건식은 괜찮다
        for m in re.finditer(r"\$\{\s*" + re.escape(field) + r"\s*\}", code):
            raise AssertionError(f"{field} 을 escHtml 없이 끼운다: …{code[m.start() - 20:m.end() + 20]}…")
    assert "escHtml(s)" in code and "escHtml(w)" in code


def test_no_double_json_body_anywhere_df108():
    """TC-CUS-04 · 공통 api() 는 본문을 스스로 JSON 으로 바꾼다 — 모든 화면 파일에서 api(…, { body: JSON.stringify(…) }) 금지(DF-108)."""
    bad = []
    for f in sorted((ROOT / "public" / "js").glob("*.js")):
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"\bapi\(", src):
            window = src[m.start(): m.start() + 300]
            call = window[: window.find(");") + 2] if ");" in window else window
            if re.search(r"body:\s*JSON\.stringify\(", call):
                bad.append(f"{f.name}:{src[: m.start()].count(chr(10)) + 1}")
    assert not bad, f"api() 에 문자열 본문: {bad}"
