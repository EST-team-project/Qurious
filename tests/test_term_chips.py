"""글 끝 「이 글의 용어」 칩 부품 화면 시험 (TC-TCH) · 2026-10-17 · 모의투자 점검 L5.

결정: Figma 「AI 투자 상담 — 근거 답과 출처」 03-2 [결정] 용어 칩 (가) — 본문 글에서 용어 풀이(오른쪽 서랍)로 가는 길을 글 끝 칩 줄로.
AI 답 글은 건드리지 않는다(몰래 고치지 않음). 글 속 용어는 서버가 찾는다(POST /api/glossary/scan · TC-GS) — 부품은 그리고 잇기만.
같은 부품을 다른 화면(차트 패턴 · 스크리닝 — 다른 주담당)도 부를 수 있게 따로 둔다(js/termchips.js).

여기서 지키는 것 —
1. 부품: 서버 상한(글 4,000자 · 용어 수)을 넘겨 보내지 않는다(화면 → API) · 칩은 용어 ID 로 서랍을 연다(termcard.js openTerm) ·
   글자를 막는다 · 찾은 용어가 없거나 찾기가 실패하면 줄을 그리지 않는다(답은 그대로) · 다른 화면이 부를 이름은 하나.
2. 상담 연결(js/kbchat.js): 일반 AI 답 · 근거 답 · 다른 엔진 답 끝에 「이 답의 용어」 · 답하지 않는 질문에는 붙이지 않는다.
네트워크 · 실제 DB 없이 돈다.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.services import glossary_scan

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "public" / "js"


def _code(name: str) -> str:
    return re.sub(r"^\s*//.*$", "", (JS / name).read_text(encoding="utf-8"), flags=re.M)


def test_chip_part_respects_the_server_limits_and_opens_the_card():
    """TC-TCH-01 · 부품 — 글은 서버 상한(MAX_TEXT)까지 잘라 보내고 · 용어 수는 서버 상한 안 · 칩은 data-term(용어 ID)으로 서랍을 연다 ·
    글자를 막는다 · 줄 이름은 부른 쪽이 준다(기본 「이 글의 용어」)."""
    src = _code("termchips.js")
    assert int(re.search(r"export const TERM_SCAN_MAX = (\d+);", src).group(1)) == glossary_scan.MAX_TEXT
    limit = int(re.search(r"export const TERM_CHIPS_MAX = (\d+);", src).group(1))
    assert 1 <= limit <= glossary_scan.MAX_LIMIT and limit == 6                    # 결정 — 최대 여섯
    assert 'api("/api/glossary/scan", { method: "POST", body: { text: String(text).slice(0, TERM_SCAN_MAX), limit } })' in src
    assert 'import { openTerm } from "/js/termcard.js";' in src
    assert re.search(r'data-term="\$\{escHtml\(t\.id\)\}"', src) and "escHtml(t.term)" in src and "escHtml(label)" in src
    assert re.search(r'addEventListener\("click", \(\) => openTerm\(b\.dataset\.term\)\)', src)
    assert 'label = "이 글의 용어"' in src


def test_chip_part_draws_nothing_when_nothing_was_found():
    """TC-TCH-02 · 찾은 용어가 없거나 찾기가 실패하면 줄을 그리지 않는다 — 답은 그대로 두고, 실패는 콘솔에 남긴다(말없이 삼키지 않음)."""
    src = _code("termchips.js")
    fn = src[src.index("export async function appendTermChips"):src.index("\n}\n", src.index("export async function appendTermChips"))]
    assert re.search(r"if \(!items\.length\) return null;", fn)
    assert re.search(r"catch \(err\) \{\s*console\.warn\(", fn)
    assert "host.appendChild(row)" in fn


def test_chat_answers_get_the_chip_row():
    """TC-TCH-03 · 상담 연결 — 일반 AI 답 · 근거 답 · 다른 엔진 답 끝에 「이 답의 용어」 · 답하지 않는 질문(declined)에는 붙이지 않는다 ·
    다른 화면이 부를 부품 이름은 하나(appendTermChips)."""
    code = _code("kbchat.js")
    assert 'import { appendTermChips } from "/js/termchips.js";' in code
    general = code[code.index("async function askGeneralAi"):code.index("export async function sendKbChat")]
    assert re.search(r'appendTermChips\(bubble, chat\.answer, \{ label: "이 답의 용어" \}\)', general)
    kb = code[code.index("function renderKbAnswer"):code.index("function renderDeclined")]
    assert re.search(r'if \(!excerpt\) appendTermChips\(bubble, res\.answer, \{ label: "이 답의 용어" \}\);', kb)
    declined = code[code.index("function renderDeclined"):code.index("function failedExcerpt")]
    assert "appendTermChips" not in declined
    after = code[code.index("export function afterChatAnswer"):]
    # 다른 엔진 답 — 칩 자리를 먼저 잡아(「근거 답으로 다시 묻기」 단추보다 위) 거기에 채운다
    assert re.search(r'appendTermChips\(chipsHost, bubble\.querySelector\("pre"\)\?\.textContent \|\| "", \{ label: "이 답의 용어" \}\)', after)
    assert after.index("bubble.appendChild(chipsHost)") < after.index("bubble.appendChild(wrap)")
