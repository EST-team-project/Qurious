"""TC-FRS — 재무 · 신용 위험 화면(public/js/riskcb.js) · 2026-10-13

무엇을 지키나
1. 화면이 읽는 칸이 서버 응답에 있다 — riskcb.js 가 「변수.칸」 으로 읽는 곳을 모두 모아 두 응답(재무 · 시장 신용)과 맞댄다
   (TC-PD-01 꼴). 서버가 칸 이름을 바꾸면 화면은 오류 없이 빈칸을 그리므로 시험이 먼저 깨지게. (TC-FRS-01)
2. 경계 · 기간 숫자를 화면에 따로 적지 않는다 — Z'' 경계(1.10 · 2.60) · 통계 기간(10년)은 서버 응답 한 곳에서만. (TC-FRS-02)
3. 낱말 · 색 — 점검은 「그렇다 · 아니다 · 자료 없음」(통과 · 실패는 투자 판단처럼 읽힌다 · 사용자 결정 2026-10-13) ·
   권유 낱말 없음 · 신호등 색 없음(빨강은 오류 글에만) · 차트 출처 표시. (TC-FRS-03)
4. 연결 — app.html 뿌리 칸 · 스타일 · main.js 부르는 줄 · 메뉴 이름 · 도움말 용어 셋 · 옛 단추 가드 · 진입 훅 꼴 · 차트 파일. (TC-FRS-04)
5. 설계 D(Figma 05 [결정]) — 띠의 「그림 · 읽는 법 →」 은 펼치지 않고 시장 신용 탭으로 옮긴다 · 탭마다 한쪽만 보인다 ·
   회사 탭은 점검 먼저 · 시장금리가 없으면 띠를 그리지 않는다 · 부르는 API 는 셋(재무 · 시장 신용 · 종목 찾기)뿐. (TC-FRS-05)

수집 DB 를 열지 않는다(S96) — 재무는 가짜 read_financials(TC-FH 꼴) · 시장금리는 임시 DB(TC-MC 꼴).
"""
from __future__ import annotations

import colorsys
import re
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from app.services import company_health as H
from app.services import macro_credit as M
from collector import ecos as E
from tests.test_company_health import BANNED, GOOD, _fake, _p
from tests.test_macro_credit import _fill, _weekdays

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
JS = PUB / "js" / "riskcb.js"
CSS = PUB / "css" / "riskcb.css"
#: riskcb.js 머리말의 변수 이름 규칙과 같다 — 객체마다 이름 하나(S.co · S.mc 는 co · mc 로 센다)
JS_READ = re.compile(r"(?<![\w.])(S\.co|S\.mc|co|lb|sm|mh|m|ck|zs|zh|op|oy|un|mc|sp|d)((?:\??\.[A-Za-z_]\w*)+)")
ALIAS = {"S.co": "co", "S.mc": "mc"}


@pytest.fixture(autouse=True)
def _no_real_collector_db(tmp_path, monkeypatch):
    """회사 이름 읽기가 이 PC 의 실제 수집 DB 를 열지 않게(S96) — 시장금리 자료는 아래에서 임시 DB 를 다시 준다."""
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "수집DB-없음.sqlite3"))


def _company_samples(monkeypatch) -> list[dict]:
    """일반 회사(해마다 셋 · 영업손실 한 해 · 정정된 반기) + 금융회사(값 대신 까닭) — 칸마다 값이 있는 쪽이 하나는 있게."""
    years = [_p(f"{y}-12-31", acc=dict(GOOD, operating_income=oi)) for y, oi in ((2022, 30), (2023, -10), (2024, 40))]
    _fake(monkeypatch, {"CFS": years + [_p("2025-06-30", "11012", restated=True)]})
    general = H.read_health("005930")
    bank = {k: v for k, v in GOOD.items() if k not in ("current_assets", "current_liabilities", "noncurrent_liabilities")}
    _fake(monkeypatch, {"CFS": [_p("2025-12-31", acc=bank, extra=("예수부채",))]})
    financial = H.read_health("105560")
    assert general["kind"] == "general" and financial["kind"] == "financial"
    return [general, financial]


def _macro_samples(tmp_path, monkeypatch) -> list[dict]:
    """시장금리가 있을 때(10년 넘게) + 아직 받지 못했을 때(관리자 — 할 일 칸까지)."""
    p = tmp_path / "market.sqlite3"
    c = sqlite3.connect(p)
    c.executescript(E.ECOS_SERIES_DDL)
    c.close()
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(p))
    empty = M.read_macro(admin=True)
    rows = []
    for i, d in enumerate(_weekdays(date(2026, 10, 12), 2700)):
        ds = d.isoformat()
        rows += [("010200000", ds, 3.0), ("010300000", ds, 3.5 + (i % 100) / 1000), ("010320000", ds, 9.0),
                 ("010502000", ds, 3.2), ("010503000", ds, 3.5)]
    _fill(p, rows)
    ok = M.read_macro(years=3, today=date(2026, 10, 13))
    assert ok["available"] and not empty["available"]
    return [ok, empty]


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
            return None          # 목록 · 글자 · 숫자에 붙은 것(.map · .at · .toFixed)은 JS 의 것이라 멈춘다
        if key not in obj:
            return key
        obj = obj[key]
    return None


def _code_only(src: str) -> str:
    """주석을 뺀 코드 — 머리말 · 설명 주석의 숫자 · 낱말은 시험 대상이 아니다(주소의 // 는 남긴다)."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)^\s*//[^\n]*$", "", src)
    return re.sub(r"(?<=[;{}),])[ \t]*//[^\n]*", "", src)


def test_screen_reads_only_fields_the_server_sends(tmp_path, monkeypatch):
    """TC-FRS-01"""
    cos = _company_samples(monkeypatch)
    mcs = _macro_samples(tmp_path, monkeypatch)
    ms = [m for co in cos for m in co["metrics"]]
    sps = mcs[0]["spreads"]
    objs = {
        "co": cos, "lb": [co["latest"] for co in cos], "sm": [co["summary"] for co in cos],
        "m": ms, "mh": [h for m in ms for h in m.get("history") or []],        # 자본잠식률은 그림이 없다(숫자 칸만)
        "ck": [ck for co in cos for ck in co["checks"]],
        "zs": [co["zscore"] for co in cos], "zh": [h for co in cos for h in co["zscore"]["history"]],
        "op": [co["operating"] for co in cos], "oy": [o for co in cos for o in co["operating"]["history"]],
        "un": [u for co in cos for u in co["unavailable"]],
        "mc": mcs, "sp": sps, "d": [d for sp in sps for d in sp["history"]],
    }
    src = JS.read_text(encoding="utf-8")
    reads = {(ALIAS.get(m.group(1), m.group(1)), tuple(re.findall(r"[A-Za-z_]\w*", m.group(2))))
             for m in JS_READ.finditer(src)}
    assert len(reads) > 50, "화면이 읽는 칸을 거의 못 모았다 — 변수 이름 규칙(riskcb.js 머리말)을 볼 것"
    assert {v for v, _ in reads} == set(objs), "변수 이름 규칙의 이름이 모두 쓰여야 한다(안 쓰는 이름은 머리말에서 뺀다)"
    missing = []
    for var, chain in sorted(reads):
        assert objs[var], f"시험 자료에 {var} 줄이 없다 — 맞대 볼 수 없다"
        miss = _missing(_merged(objs[var]), chain)
        if miss:
            missing.append(f"{var}.{'.'.join(chain)} — 응답에 「{miss}」 칸이 없다")
    assert missing == []


def test_no_threshold_or_period_numbers_in_screen():
    """TC-FRS-02 · 경계 · 기간은 서버 한 곳 — 화면 글에 따로 적으면 서버를 고칠 때 한쪽만 바뀐다."""
    code = _code_only(JS.read_text(encoding="utf-8"))
    assert not re.findall(r"(?<![\d.])(?:1\.10?|2\.60?)(?![\d])", code), "Z'' 경계는 zs.thresholds 에서만"
    assert "10년" not in code and "STATS_YEARS" not in code, "통계 기간은 sp.stats.years 에서만"
    assert "zs.thresholds.low" in code and "sp.stats.years" in code


def test_words_colors_and_credit():
    """TC-FRS-03"""
    src = JS.read_text(encoding="utf-8")
    assert 'const MARK = { pass: ["✔", "그렇다"], fail: ["✕", "아니다"], unknown: ["?", "자료 없음"] };' in src
    code = _code_only(src)
    for bad in ("통과", "실패", "합격", "등급") + BANNED:
        assert bad not in code, bad
    css = CSS.read_text(encoding="utf-8")
    red = [ln for ln in css.splitlines() if "var(--red" in ln]
    assert red and all(ln.startswith(".rc-error") for ln in red), "빨강은 오류 글에만"
    for bad in ("--green", "--yellow", "--amber", "--orange"):
        assert bad not in css and bad not in code, bad
    for hexv in re.findall(r"#[0-9a-fA-F]{6}\b", code + css):
        h, _l, s = colorsys.rgb_to_hls(*(int(hexv[i:i + 2], 16) / 255 for i in (1, 3, 5)))
        assert s < 0.35 or 180 <= h * 360 <= 260, f"{hexv} — 신호등 색(빨강 · 노랑 · 초록) 금지 · 회색 · 남색 · 강조 파랑만"
    assert "attributionLogo: true" in src and 'const CREDIT_URL = "https://www.tradingview.com/";' in src
    assert "차트: TradingView Lightweight Charts™" in src


def test_wiring():
    """TC-FRS-04"""
    html = (PUB / "app.html").read_text(encoding="utf-8")
    assert '<div class="view" data-view="agent-cb"><div class="rc-root"></div></div>' in html
    assert '<link rel="stylesheet" href="/css/riskcb.css" />' in html
    assert 'id="pcb-search"' not in html and 'id="ccb-search"' not in html          # 옛 칸은 뺐다
    main = (PUB / "js" / "main.js").read_text(encoding="utf-8")
    assert 'import { onRiskViewActivated } from "/js/riskcb.js";' in main
    assert "  onRiskViewActivated(view);" in main
    core = (PUB / "js" / "core.js").read_text(encoding="utf-8")
    assert 'key: "agent-cb",        icon: "fa-solid fa-chart-bar",             label: "재무 · 신용 위험"' in core
    assert 'relatedTerms: ["debt_ratio", "current_ratio", "credit_spread"]' in core
    for term in ("debt_ratio", "current_ratio", "credit_spread"):           # 도움말이 가리키는 용어가 용어 표에 있다
        assert re.search(rf"^  {term}:\s+\{{ title: ", core, re.M), term
    agent = (PUB / "js" / "agent.js").read_text(encoding="utf-8")
    for bid in ("pcb-search", "ccb-search"):                 # 옛 칸이 없으면 묶지 않는다 — 없으면 agent.js 모듈이 여기서 멈춘다
        assert f'document.getElementById("{bid}")?.addEventListener' in agent
    src = JS.read_text(encoding="utf-8")
    assert 'if (view !== "agent-cb") return;' in src      # 화면 스캐너(scripts/view_scan.py)가 읽는 진입 훅 꼴
    vendor = re.search(r'const LWC_SRC = "(/js/vendor/[^"]+)";', src).group(1)
    assert (PUB / vendor.lstrip("/")).is_file(), "차트 파일이 실제로 있다"


def test_design_d_strip_tabs_and_calls():
    """TC-FRS-05"""
    src = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert 'data-goto="macro">그림 · 읽는 법 →</button>' in src
    assert 'el.querySelector(".rc-strip-more")?.addEventListener("click", () => { S.tab = "macro"; paint(); });' in src
    assert "if (!mc || !mc.available) return \"\";" in src                       # 시장금리가 없으면 띠를 그리지 않는다
    assert "el.className = `rc-root is-tab-${S.tab}`;" in src
    assert ".rc-root.is-tab-company .rc-macro { display: none; }" in css
    assert ".rc-root.is-tab-macro .rc-company, .rc-root.is-tab-macro .rc-strip { display: none; }" in css
    assert ".rc-col-l .rc-checks-card { order: -1; }" in css                     # 회사 탭은 점검 먼저
    calls = set(re.findall(r"api\([`\"](/api/[a-z/]+)", src))
    assert calls == {"/api/risk/company", "/api/risk/macro", "/api/stocks/search"}, calls
