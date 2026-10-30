"""TC-BNC — 전략 분석 · 성과 검증 화면의 탭 띠 + 「기준 전략」 안내 카드(public/js/baselinenotice.js) · 2026-10-30 · ①-18

무엇을 지키나(Figma 「Qurious · 전략 분석」 03 설계 · 05 결정 기록)
1. 카드의 숫자는 요약 파일(public/js/baseline-result.json)에서 읽고, 그 파일은 신장환 님의 결과 원본(trials.json)과 같다 —
   원본을 다시 돌리고 scripts/baseline_summary.py 를 안 돌리면 이 시험이 실패한다. (TC-BNC-01)
2. 카드 판단 함수를 node 로 그대로 돌린다 — 합격 0개(기준 전략 없음 · 가장 가까운 시도는 참고용) · 합격이 있을 때(합성 값) ·
   요약을 못 읽을 때. 글에 개발 티(필드 이름)가 없고 화면 글은 이스케이프된다. (TC-BNC-02)
3. 화면 코드에 결과 숫자를 적지 않는다 — 시험 결과를 다시 돌리면 낡는다(서버 숫자를 화면에 다시 적지 않는 규칙). 탭 띠 · 카드 자리는
   합친 화면 안에 하나뿐이고(화면 경계로 가른다) 탭 칸 둘이 그 안에 있으며 스타일 · 진입 훅이 이어져 있다. (TC-BNC-03)
4. 전략 분석 결과 줄에 개발 티(entry_mode= · exit_mode= · 전략 약어)가 없다. (TC-BNC-04)
5. 요약 파일을 못 읽으면 null 로 돌아오고 다음 번에 다시 읽는다(한 번 실패가 굳지 않는다). (TC-BNC-05)
6. 완전 통합(결정 6번) — 화면 선언 하나 · 메뉴 줄 하나 · 옛 주소 #indicator-backtest 는 탭 2 로 잇는다(별칭). 탭 키로 고른 칸만 보이고,
   화면 · 메뉴 줄 · 주소 · 도움말 · 시작 주소가 별칭을 풀어 쓴다. (TC-BNC-06)
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
BN = PUB / "js" / "baselinenotice.js"
SUMMARY = PUB / "js" / "baseline-result.json"
APP_HTML = PUB / "app.html"


def _summary_module():
    spec = importlib.util.spec_from_file_location("baseline_summary", ROOT / "scripts" / "baseline_summary.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    return node


def _run(tmp_path: Path, body: str) -> dict:
    script = tmp_path / "run.mjs"
    script.write_text(f'import * as bn from "{BN.resolve().as_uri()}";\nconst out = {{}};\n{body}\n'
                      "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    run = subprocess.run([_node(), str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_summary_file_matches_trials_source():
    """TC-BNC-01 · 요약 파일 = 원본(trials.json)에서 계산한 값."""
    mod = _summary_module()
    src = mod.latest_trials()
    trials = json.loads(src.read_text(encoding="utf-8"))
    day = re.search(r"(\d{4}-\d{2}-\d{2})", src.parent.name).group(1)
    expected = mod.build_summary(trials, day)
    assert json.loads(SUMMARY.read_text(encoding="utf-8")) == expected, "결과를 다시 돌렸으면 python scripts/baseline_summary.py 로 요약 파일을 다시 쓴다"
    # 원본 값과 직접 맞대기 — 합격 수 · 기준별 넘은 수 · 시도 수
    rows = trials["trials"]
    assert expected["n_trials"] == len(rows) == trials["n_trials"]
    assert expected["passed"] == sum(1 for r in rows if r["pass"])
    line = trials["pass_line"]
    assert expected["counts"]["profit_factor"] == sum(1 for r in rows if r["profit_factor"] is not None and r["profit_factor"] > line["profit_factor"])
    assert expected["counts"]["mdd_pct"] == sum(1 for r in rows if r["mdd_pct"] > line["mdd_pct"])
    assert expected["counts"]["sharpe_ratio"] == sum(1 for r in rows if r["sharpe_ratio"] > line["sharpe_ratio"])
    if expected["passed"] == 0 and expected["nearest"]:
        n = expected["nearest"]
        assert (n["symbol"], n["short"], n["long"]) == (trials["nearest"]["symbol"], trials["nearest"]["short"], trials["nearest"]["long"])
        assert n["missed"], "합격하지 못한 시도는 못 넘은 기준이 하나 이상이다"
    assert expected["period"]["sealed_from"] > expected["period"]["end"], "봉인 구간은 자료 끝 다음 날부터"


def test_card_model_states_in_node(tmp_path):
    """TC-BNC-02 · 합격 0개 · 합격 있음(합성) · 못 읽음."""
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    found = json.loads(json.dumps(summary))
    found["passed"] = 2
    found["nearest"] = None
    found["passed_trials"] = [
        {"symbol": "005930.KS", "name": "삼성전자", "short": 5, "long": 20, "profit_factor": 1.9, "mdd_pct": -8.2, "sharpe_ratio": 1.21},
        {"symbol": "000660.KS", "name": "SK<b>하이닉스", "short": 10, "long": 60, "profit_factor": 2.4, "mdd_pct": -6.0, "sharpe_ratio": 1.05},
    ]
    (tmp_path / "s.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "f.json").write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    out = _run(tmp_path, f"""
const fs = await import("node:fs");
const s = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 's.json'))}, "utf-8"));
const f = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'f.json'))}, "utf-8"));
out.none = bn.baselineCardModel(s);
out.found = bn.baselineCardModel(f);
out.err = [bn.baselineCardModel(null), bn.baselineCardModel({{}}), bn.baselineCardModel("x")].map(m => [m.state, m.badge]);
out.foundHtml = bn.cardHtml(out.found);
out.noneHtml = bn.cardHtml(out.none);
""")
    s = summary
    none = out["none"]
    assert none["state"] == "none" and none["badge"] == "아직 없음"
    assert none["stats"][0]["value"] == f'{s["counts"]["profit_factor"]} / {s["n_trials"]}'
    assert none["stats"][2]["bad"] is (s["counts"]["sharpe_ratio"] == 0), "0 개 넘은 기준만 붉게"
    assert f'{s["pass_line"]["sharpe_ratio"]:.1f}' in none["stats"][2]["label"], "합격선 1 이 아니라 1.0 으로"
    assert none["near"]["label"].endswith("고른 것이 아닙니다"), "가장 가까운 시도는 참고용이라고 밝힌다"
    assert s["nearest"]["name"] in none["near"]["title"] and "합격하지 못했습니다" in none["near"]["reason"]
    assert str(s["nearest"]["profit_factor"]) in none["near"]["values"]
    assert out["found"]["state"] == "found" and out["found"]["badge"] == "있음" and len(out["found"]["found"]) == 2
    assert out["found"]["near"] is None, "합격이 있으면 가장 가까운 시도 칸은 없다"
    assert "<b>" not in out["foundHtml"] and "&lt;b&gt;" in out["foundHtml"], "글은 이스케이프한다"
    assert out["err"] == [["error", "확인 못 함"]] * 3
    for html in (out["noneHtml"], out["foundHtml"]):
        assert not re.search(r"profit_factor|sharpe_ratio|mdd_pct|entry_mode|exit_mode|undefined|NaN|\[object", html), "화면 글에 개발 티가 없다"


def test_screen_wiring_and_no_hardcoded_numbers():
    """TC-BNC-03 · 두 화면 안의 자리 · 스타일 · 진입 훅 + 화면 코드에 결과 숫자가 없다."""
    js = BN.read_text(encoding="utf-8")
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    near = s["nearest"]
    for literal in (str(near["profit_factor"]), str(near["sharpe_ratio"]), near["name"], "110", "41 /"):
        assert literal not in js, f"화면 코드에 결과 값 「{literal}」 을 적지 않는다 — 요약 파일에서 읽는다"
    html = APP_HTML.read_text(encoding="utf-8")
    parts = re.split(r'<div class="view" data-view="', html)
    by_view = {p.split('"', 1)[0]: p for p in parts[1:]}
    assert "indicator-backtest" not in by_view, "성과 검증은 따로 선언된 화면이 아니라 전략 분석 화면의 탭 2"
    body = by_view["quant-backtest"]
    head = body[: body.find('<div class="bn-pane"')]
    assert 'id="bn-mount-quant-backtest"' in head, "합친 화면 맨 위(탭 칸보다 앞)에 탭 띠 · 카드 자리"
    assert html.count('id="bn-mount-') == 1 and 'id="bn-mount-indicator-backtest"' not in html
    panes = re.findall(r'<div class="bn-pane" data-bn-pane="([^"]+)"( hidden)?', body)
    assert panes == [("quant-backtest", ""), ("indicator-backtest", " hidden")], "탭 칸 둘 — 전략 분석이 먼저 보이고 성과 검증은 숨어 있다"
    for needle in ('id="bt-symbol-pick"', 'id="bt-load"', 'id="ibt-symbol"', 'id="ibt-run-btn"', 'id="ibt-result"'):
        assert needle in body, f"{needle} 는 합친 화면 안에 있다(옛 두 화면의 입력 · 결과)"
    assert '/css/baselinenotice.css' in html
    main = (PUB / "js" / "main.js").read_text(encoding="utf-8")
    assert 'from "/js/baselinenotice.js"' in main and re.search(r'if \(view === "quant-backtest"\)[^\n]*renderBaselineNotice\(tab\)', main)
    assert re.search(r'if \(tab === "indicator-backtest"\) loadIndicatorBacktest\(\)', main), "성과 검증 탭에 들어올 때 옛 화면처럼 실행한다"
    css = (PUB / "css" / "baselinenotice.css").read_text(encoding="utf-8")
    assert "var(--accent)" in css and not re.search(r"^\.(card|btn|input|view)\b", css, re.M), "공용 이름을 덮어쓰지 않는다"


def test_quant_result_line_has_no_dev_jargon():
    """TC-BNC-04 · 결과 줄의 개발 티 — 체결 방식 낱말 · 전략 약어."""
    q = (PUB / "js" / "quant.js").read_text(encoding="utf-8")
    # 요청 주소(entry_mode=${entryMode})는 서버 인자라 둔다 — 화면에 그리는 글(escHtml 로 감싼 값)만 본다
    assert not re.search(r"(entry|exit)_mode=\$\{escHtml", q), "결과 줄에 필드 이름을 그대로 내보내지 않는다"
    assert 'BT_STRATEGY_NAMES = { ma: "이동평균 교차" }' in q and 'd.strategy || "ma")}</span>' not in q


def test_load_summary_failure_is_not_sticky(tmp_path):
    """TC-BNC-05 · 못 읽으면 null · 다음 번에 다시 읽는다 · 읽으면 그 값을 한 번만 받는다."""
    out = _run(tmp_path, """
let calls = 0;
const bad = async () => { calls++; throw new Error("끊김"); };
out.first = await bn.loadBaselineSummary(bad);
const ok = async () => { calls++; return { ok: true, json: async () => ({ version: 1 }) }; };
out.second = await bn.loadBaselineSummary(ok);
out.third = await bn.loadBaselineSummary(bad);
out.calls = calls;
""")
    assert out["first"] is None and out["second"] == {"version": 1}
    assert out["third"] == {"version": 1} and out["calls"] == 2, "한 번 읽은 뒤에는 다시 부르지 않는다"


def test_merged_screen_alias_and_panes(tmp_path):
    """TC-BNC-06 · 완전 통합 — 메뉴 줄 하나 · 별칭 · 탭 칸 · 화면 키를 풀어 쓰는 곳."""
    out = _run(tmp_path, """
const alias = await import(%r);
out.resolve = ["indicator-backtest", "quant-backtest", "dashboard", "constructor", "toString"].map(k => alias.resolveView(k));
const mk = (key) => ({ dataset: { bnPane: key }, hidden: key !== "quant-backtest" });
const panes = [mk("quant-backtest"), mk("indicator-backtest")];
const root = { querySelectorAll: () => panes };
out.second = [bn.showPane("indicator-backtest", root), panes.map(p => p.hidden)];
out.first = [bn.showPane("quant-backtest", root), panes.map(p => p.hidden)];
out.unknown = [bn.showPane("dashboard", root), panes.map(p => p.hidden)];
out.noDom = bn.showPane("quant-backtest", {});
out.tabs = bn.tabsHtml("indicator-backtest");
""" % (PUB / "js" / "viewalias.js").resolve().as_uri())
    assert out["resolve"] == ["quant-backtest", "quant-backtest", "dashboard", "constructor", "toString"], "별칭만 풀고 그 밖의 키(객체 기본 이름 포함)는 그대로"
    assert out["second"] == ["indicator-backtest", [True, False]] and out["first"] == ["quant-backtest", [False, True]]
    assert out["unknown"] == [None, [False, True]], "알 수 없는 탭 키는 아무것도 바꾸지 않는다"
    assert out["noDom"] is None
    assert out["tabs"].count('aria-current="page"') == 1 and 'href="#indicator-backtest"' in out["tabs"] and 'href="#quant-backtest"' in out["tabs"]
    core = (PUB / "js" / "core.js").read_text(encoding="utf-8")
    assert 'key: "indicator-backtest"' not in core, "성과 검증 메뉴 줄은 없앴다(전략 분석 한 곳)"
    assert core.count('key: "quant-backtest"') == 1
    assert "const shownView = resolveView(viewKey);" in core and "_viewActivated(shownView, viewKey);" in core
    assert 'resolveView(key)}"]`)) navigate(key);' in core, "주소창 해시가 별칭이어도 화면으로 닿는다"
    main = (PUB / "js" / "main.js").read_text(encoding="utf-8")
    assert 'querySelector(`[data-view="${resolveView(hash)}"]`)' in main, "북마크(#indicator-backtest)로 시작해도 탭 2 로 연다"
    howto = (PUB / "js" / "howto.js").read_text(encoding="utf-8")
    assert "resolveView(viewKey)" in howto and "row.dataset.howtoView" in howto, "한 화면의 탭마다 사용법 글이 다르다"
    assert "resolveView(item.view)" in (PUB / "js" / "helpvideos.js").read_text(encoding="utf-8")
