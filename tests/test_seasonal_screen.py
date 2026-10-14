"""계절성 분석 화면 시험 (TC-SES-01 ~ 03) — `public/js/seasonal.js` · `public/css/seasonal.css` (2026-10-14).

정적 시험(브라우저 없이 파일 글을 본다) — 화면이 지키는 약속:
1. 강사님 파일에는 뿌리 칸 · 부르는 줄만 — app.html 의 quant-seasonal 칸은 뿌리 하나 · main.js 가 진입 훅을 부른다(글자 그대로).
2. 고르기 값(대상 · 값) · 판정 글 · 기준값은 서버 응답(choices · distinct_text · judge_text · thresholds)에서만 —
   화면 코드에 그 값이 없다(서버를 고칠 때 한쪽만 바뀌지 않게).
3. 서버에서 온 글(까닭 · 문장 · 이름 · 판정 글 · 출처)은 escHtml 을 거친다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "public" / "js" / "seasonal.js"
APP = ROOT / "public" / "app.html"
MAIN = ROOT / "public" / "js" / "main.js"


def _code(src: str) -> str:
    """주석을 뺀 코드 — /* */ 덩어리와 // 줄 끝 주석(문자열 안 // 는 드물어 단순히)."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", ln) for ln in src.splitlines())


def test_wiring_root_only_and_entry_hook():
    """TC-SES-01 · app.html 의 계절성 칸은 뿌리 하나 · CSS 링크 · 옛 단추 없음 · main.js 가져오기 + 훅 · 훅은 글자 그대로."""
    html = APP.read_text(encoding="utf-8")
    assert '<div class="view" data-view="quant-seasonal"><div class="se-root"></div></div>' in html
    assert 'href="/css/seasonal.css"' in html and "seas-run-btn" not in html and "seas-result" not in html
    main = MAIN.read_text(encoding="utf-8")
    assert 'import { onSeasonalViewActivated } from "/js/seasonal.js";' in main
    assert re.search(r"^\s+onSeasonalViewActivated\(view\);", main, re.M)
    js = JS.read_text(encoding="utf-8")
    assert 'if (view !== "quant-seasonal") return;' in js


def test_choices_judgements_and_thresholds_come_from_the_server():
    """TC-SES-02 · GET /api/seasonality 만 부른다 · 고르기 값 · 판정 글 · 기준값을 코드에 적지 않는다."""
    code = _code(JS.read_text(encoding="utf-8"))
    assert "/api/seasonality" in code and "/api/ml/seasonality" not in code
    for lit in ('"KOSPI"', '"KOSDAQ"', "'KOSPI'", '"tr"', '"pr"', "'tr'", "'pr'", '"코스피"', '"코스닥"', '"배당 포함"', '"가격만"'):
        assert lit not in code, f"화면 코드에 고르기 값 {lit} 이 있다 — 응답 choices 에서 읽는다"
    assert "ch.markets" in code and "ch.bases" in code and "ch.stock" in code and "d.choices.bases[0].key" in code
    for word in ("뚜렷하지 않음", "판정 안 함", "우연으로 보기 어려운", "우연으로도 생길"):
        assert word not in code, f"판정 글 「{word}」 은 서버(distinct_text · judge_text)에서 온다"
    assert "distinct_text" in code and "judge_text" in code and "thresholds.alpha" in code
    # 유의수준을 화면에 적어 견주는 꼴(`p < 0.05` · `alpha: 0.05`)만 막는다 — 그림 눈금 같은 다른 0.05 는 상관없다
    for pat in (r"[<>]=?\s*0?\.0[15]\b", r"alpha\s*[:=]\s*0?\.\d"):
        hit = re.search(pat, code)
        assert not hit, f"기준값을 화면에 적지 않는다: …{code[max(0, hit.start() - 30):hit.end() + 10]}…"


def test_server_text_is_escaped():
    """TC-SES-03 · 서버에서 온 까닭 · 문장 · 이름 · 판정 글 · 출처는 escHtml 을 거쳐 그린다."""
    code = _code(JS.read_text(encoding="utf-8"))
    fields = ("d.reason", "d.notice", "d.source", "d.basis_note", "d.admin_hint", "d.span.text", "m.label", "w.label",
              "m.distinct_text", "w.distinct_text", "c.judge_text", "tgt.name", "tgt.code", "x.name", "x.code", "S.err", "S.hint",
              "S.note", "s.name", "best.label", "worst.label")
    for field in fields:
        # 날 값을 그대로 끼우는 꼴(`${m.label}`)만 막는다 — 조건식 안의 escHtml(…) 은 괜찮다
        for m in re.finditer(r"\$\{\s*" + re.escape(field) + r"\s*\}", code):
            raise AssertionError(f"{field} 을 escHtml 없이 끼운다: …{code[m.start() - 20:m.end() + 20]}…")
    assert "escHtml(s)" in code                     # 읽는 법 문장
    assert "escHtml(d.reason)" in code and "escHtml(d.notice)" in code and "escHtml(d.source)" in code
