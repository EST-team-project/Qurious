"""TC-HBE — 차트 패턴 화면의 종목 근거 입구 (#259 · #197 7 · #159 T1 · 2026-11-02)

입구는 단추 한 줄이다 — `data-hub-open="종목코드"` 를 `stockdrawer.js` 의 `mountStockDrawer`(main.js 가 문서에 붙임)가 받아 큰 모달을 연다(#485 — 입구는 모두 모달 직행).
1. 차트 패턴 화면은 차트 제목 끝에 단추를 두고, 입력이 「005930.KS」 여도 코드만 싣는다(영문 섞인 새 코드 포함) · 종목 코드가 아니면 두지 않는다. (TC-HBE-01)
2. 단추를 받는 쪽이 앱 전체에 붙어 있다. (TC-HBE-02)
node 가 없으면 1 은 건너뛴다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "public" / "js"
NODE = shutil.which("node")


def _cut(src: str, start: str, end: str) -> str:
    i = src.index(start)
    return src[i:src.index(end, i)]


def _node(js: str, arg) -> list:
    out = subprocess.run([NODE, "-e", js, json.dumps(arg, ensure_ascii=False)], capture_output=True, text=True,
                         encoding="utf-8", timeout=30, check=True)
    return json.loads(out.stdout)


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_pattern_chart_title_ends_with_the_hub_button():
    robo = (JS / "robo.js").read_text(encoding="utf-8")
    body = _cut(robo, 'const title = document.getElementById("pt-chart-title");', "if (!candles.length)")
    js = textwrap.dedent("""
        const results = [];
        for (const symbol of JSON.parse(process.argv[1])) {
          const pat = { as_of: "2026-10-15" };
          const el = { textContent: "", insertAdjacentHTML(where, html) { this.textContent += "|" + where + "|" + html; } };
          const document = { getElementById: () => el };
    """) + "{" + body + "}" + textwrap.dedent("""
          results.push(el.textContent);
        }
        console.log(JSON.stringify(results));
    """)
    ks, plain, new, us = _node(js, ["005930.KS", "005930", "0220W0", "AAPL"])
    assert ks.startswith("005930.KS · 일봉 캔들") and '|beforeend| <button type="button" class="sd-open-btn" data-hub-open="005930">' in ks
    assert 'data-hub-open="005930"' in plain and 'data-hub-open="0220W0"' in new
    assert "data-hub-open" not in us


def test_the_hub_listens_app_wide():
    main = (JS / "main.js").read_text(encoding="utf-8")
    assert "mountStockDrawer(document," in main
    assert "dataset.hubOpen" in (JS / "stockdrawer.js").read_text(encoding="utf-8")

