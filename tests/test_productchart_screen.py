"""TC-PCS — 상품 상세 창 화면(public/js/productchart.js · 벤더 차트 파일 · NOTICE) · 2026-10-12

무엇을 지키나
1. 화면이 읽는 칸이 서버 응답에 있다 — productchart.js 가 「변수.칸」 으로 읽는 곳을 모두 모아 실제 응답(TC-PCH 고정물)과
   맞댄다(TC-PD-01 꼴). 서버가 칸 이름을 바꾸면 화면은 오류 없이 빈칸을 그리므로 시험이 먼저 깨지게. (TC-PCS-01)
2. 화면은 문장을 다시 짓지 않는다 — 부호를 낱말로 바꾸는 문장(「올랐습니다 · 내렸습니다」)은 서버 한 곳에서만 만든다(SSoT).
   칩은 만든 것만(다음 단계 칩을 점선으로 미리 보이지 않는다 · 사용자 결정) · 서버가 새 칩을 내면 화면 차례표에 없어 숨지
   않게 시험이 깨진다. (TC-PCS-02)
3. 차트 라이브러리는 저장소 안 벤더 파일(5.2.1 · 강사님 기초 코드 사본 = npm 5.2.1)에서 창을 열 때만 불러온다 — 바깥 CDN 이
   아니고 app.html 에 미리 싣지 않는다 · 파일 지문(줄 끝을 접은 sha256)이 그 판과 같다 · 앱의 ApexCharts 는 3.49.2 그대로
   (5.2.0 부터 MIT 가 아니다). (TC-PCS-03)
4. 표시 의무 — 차트 위 로고(attributionLogo)를 끄지 않고, NOTICE 의 문구(키릴 「с」 그대로)를 저장소 NOTICE.md 와 창
   크레딧 줄(tradingview.com 링크)에 둔다. (TC-PCS-04)
5. 목록과 이어짐 · 회귀 — ETF 이름 단추가 창(가운데 모달)을 연다 · 창 본문 칸이 줄어들지 않는다(그림 칸이 270 → 140 · 폭 390
   에서 27 로 찌그러진 것을 막은 줄) · 한 단에서는 칸을 다시 가로로 늘인다(두 단의 세로 맞춤이 한 단에서 가로 맞춤이 되어 그림
   칸이 이전 폭 810 에 묶여 창 밖으로 나간 것을 막은 줄) · 창 크기가 바뀌어도 그린 기간 전체가 보인다(폭이 줄면 기준일 쪽이
   잘린 것을 막은 줄) · 창이 열린 동안 기능 완성도 배지를 숨긴다. (TC-PCS-05)
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from app.services import product_chart as pc
from app.services import product_etfs as pe
from tests.test_product_chart import _make_db

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
JS = PUB / "js" / "productchart.js"
VENDOR = PUB / "js" / "vendor" / "lightweight-charts"
#: productchart.js 머리말의 변수 이름 규칙과 같다 — 객체마다 이름 하나
JS_READ = re.compile(r"(?<![\w.])(r|it|st|sr|dd|lv|ex|s|pr|ev)((?:\??\.[A-Za-z_]\w*)+)")
#: 줄 끝을 LF 로 접은 sha256 — Windows 체크아웃(autocrlf)에서도 같은 값(S90 규칙)
VENDOR_SHA256 = {
    "lightweight-charts-5.2.1.min.js": "e21cc5caa0226ef30bd8549c50b9ef926615f2a4ee6b4e486353477a55f598cf",
    "LICENSE": "70c9d5382506dd184465425c08a99ad9bd6d9ac1313c252968ba0b585e5ef823",
    "NOTICE": "f76c6afab94884448f0426e30d6e9d555ca7247894cd3484e477d2f87513036e",
}
NOTICE_TEXT = "TradingView Lightweight Charts™\nCopyright (с) 2025 TradingView, Inc. https://www.tradingview.com/"


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "market.sqlite3"
    _make_db(p)
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(p))
    pe.clear_cache()
    pc.clear_cache()
    yield p
    pe.clear_cache()
    pc.clear_cache()


def _merged(objs: list[dict]) -> dict:
    out: dict = {}
    for obj in objs:
        for k, v in obj.items():
            if out.get(k) is None:
                out[k] = v
    return out


def _missing(obj, chain: tuple[str, ...]) -> str | None:
    for key in chain:
        if not isinstance(obj, dict):
            return None          # 목록 · 글자에 붙은 것(.map · .length · .find)은 JS 의 것이라 멈춘다
        if key not in obj:
            return key
        obj = obj[key]
    return None


def _samples() -> dict[str, dict]:
    """변수 이름 → 그 변수가 가리키는 응답 칸(여러 상태를 합침): 1배 · 견줄 수 있는 2배 · 견줄 수 없는 2배 · 기간 모자람."""
    ok = [pc.chart("069500", "1y"), pc.chart("122630", "1y"), pc.chart("418660", "1y"), pc.chart("0000N0", "1m")]
    short = pc.chart("0000N0", "1y")
    assert {r["status"] for r in ok} == {"ok"} and short["status"] == "short"
    rs = ok + [short]
    lv = [r["stats"]["leverage"] for r in ok if r["stats"]["leverage"]]
    return {
        "r": _merged(rs),
        "it": _merged([r["item"] for r in rs]),
        "st": _merged([r["stats"] for r in ok]),
        "sr": _merged([r["stats"]["return"] for r in ok]),
        "dd": _merged([r["stats"]["drawdown"] for r in ok if r["stats"]["drawdown"]]),
        "lv": _merged(lv),
        "ex": _merged([e for r in ok for e in r["explain"]]),
        "s": _merged([r["series"] for r in ok]),
        "pr": _merged([p for r in rs for p in r["periods"]]),
        "ev": _merged([r["events"] for r in ok]),
    }


def test_screen_reads_fields_the_server_sends(db):
    src = JS.read_text(encoding="utf-8")
    samples = _samples()
    reads = JS_READ.findall(src)
    assert len(reads) > 40                                     # 고르는 식이 실제로 읽는 곳을 잡고 있다
    bad = []
    for var, chain in reads:
        keys = tuple(k for k in chain.replace("?.", ".").split(".") if k)
        miss = _missing(samples[var], keys)
        if miss:
            bad.append(f"{var}{chain} — '{miss}' 없음")
    assert not bad, bad


def _code_only(src: str) -> str:
    """주석을 뺀 코드 — 낱말 검사가 설명 주석(「다음 단계 칩을 … 보이지 않는다」)에 속지 않게(S92 규칙)."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?<![:\"'])//.*$", "", src, flags=re.M)


def test_screen_does_not_rebuild_sentences():
    src = _code_only(JS.read_text(encoding="utf-8"))
    for w in ("올랐습니다", "내렸습니다", "올랐고", "내렸고", "생각하기 쉽지만"):
        assert w not in src, w                                  # 문장은 서버 explain 그대로(SSoT)
    for w in ("추천", "유망", "최적", "is-later", "다음 단계", "곧 나옵니다"):
        assert w not in src, w                                  # 권유 낱말 · 점선 예고 칩 없음


def test_chip_order_covers_every_server_chip(db):
    src = JS.read_text(encoding="utf-8")
    order = re.search(r"const CHIP_ORDER = \[(.*?)\];", src).group(1)
    screen = set(re.findall(r'"(\w+)"', order))
    server = {e["chip"] for code in ("069500", "122630", "418660") for e in pc.chart(code, "1y")["explain"]}
    assert server <= screen, server - screen                   # 서버가 새 칩을 내면 화면이 말없이 숨기지 않게
    assert screen == {"leverage", "return", "drawdown"}         # 1단계 칩 셋만(만든 칩만 보인다)


def _lf_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_vendor_library_local_lazy_and_pinned():
    src = JS.read_text(encoding="utf-8")
    assert 'const LWC_SRC = "/js/vendor/lightweight-charts/lightweight-charts-5.2.1.min.js";' in src
    assert not re.search(r"https?://[^\"' ]*(cdn|unpkg|jsdelivr)[^\"' ]*lightweight", src, re.I)
    for name, want in VENDOR_SHA256.items():
        assert _lf_sha(VENDOR / name) == want, name
    app = (PUB / "app.html").read_text(encoding="utf-8")
    assert "lightweight-charts" not in app                      # 미리 싣지 않는다 — 창을 열 때만
    assert "apexcharts@3.49.2/" in app                          # 판을 올리지 않는다(5.2.0 부터 MIT 아님)


def test_attribution_kept():
    src = JS.read_text(encoding="utf-8")
    assert "attributionLogo: true" in src and "attributionLogo: false" not in src
    assert 'const CREDIT_URL = "https://www.tradingview.com/";' in src and "TradingView Lightweight Charts™" in src
    notice = (VENDOR / "NOTICE").read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    assert notice.strip() == NOTICE_TEXT                       # 키릴 「с」(U+0441) 그대로
    md = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
    assert NOTICE_TEXT.split("\n")[1] in md and "public/js/vendor/lightweight-charts/" in md


def test_list_opens_modal_and_layout_guards():
    prod = (PUB / "js" / "products.js").read_text(encoding="utf-8")
    assert 'import { openProductChart } from "/js/productchart.js";' in prod
    assert 'data-chart="${escHtml(it.code)}"' in prod and "openProductChart(d.chart" in prod
    src = JS.read_text(encoding="utf-8")
    assert 'el.id = "pc-modal";' in src and 'aria-modal="true"' in src
    assert "lockVisibleTimeRangeOnResize: true" in src            # 창 폭이 바뀌어도 기준일 쪽이 잘리지 않게
    css = (PUB / "css" / "products.css").read_text(encoding="utf-8")
    assert re.search(r"^\.pc-body > \*, \.pc-top > \*, \.pc-left > \*, \.pc-right > \* \{ flex-shrink: 0; \}", css, re.M)
    one = re.search(r"@media \(max-width: 1023px\) \{(.*?)\n\}", css, re.S)
    assert one and re.search(r"\.pc-body \{[^}]*align-items: stretch;", one.group(1))   # 한 단에서 그림 칸이 이전 폭에 묶이지 않게
    assert "body:has(#pc-modal.open) #view-completion-indicator { display: none; }" in css
