"""TC-E2E — ③ 마무리 E2E 뼈대(3차 ①-22) · 2026-10-31 · 「기준 전략 = 없음」 결과가 원본에서 화면 글까지 이어지는 한 줄

왜 따로 두나
- TC-BNC 는 조각(요약 파일 = 원본 · 카드 판단 함수 · 화면 자리)을 따로 지킨다. 여기서는 그 조각을 **한 줄로 끝까지** 잇는다:
  신장환 님 결과 원본(trials.json) → 앱이 실제로 내주는 요약(GET /js/baseline-result.json) → 화면 코드가 읽는 함수(loadBaselineSummary) →
  탭 2(성과 검증)로 들어올 때 부르는 renderBaselineNotice → 카드 글. 한 고리가 끊기면(경로 · 서빙 · 읽기 · 그리기) 조각 시험은 통과해도 여기서 실패한다.
- 화면에 나온 숫자는 요약 파일이 아니라 **원본 trials.json 에서 직접 센 값**과 맞댄다(요약 파일이 틀려도 잡힌다).

무엇을 지키나
1. 앱이 내주는 요약 = 원본에서 계산한 값이고 JSON 으로 나간다. 카드 코드와 별칭 코드도 같은 서버가 내준다. (TC-E2E-01)
2. 탭 2 로 들어오면 탭 칸이 바뀌고(성과 검증 칸만 보임) 카드가 「아직 없음」 으로 그려지며, 글 속 숫자가 원본에서 센 값과 같다 —
   넘은 기준 수 · 시도 수 · 합격선 · 가장 가까운 시도(참고용) · 개발 티 없음. (TC-E2E-02)
3. 요약을 못 읽으면 카드는 「확인 못 함」 이고(「없음」 이라 우기지 않는다), 뒤에 다시 들어오면 읽어서 「아직 없음」 으로 바뀐다 — 한 번의 실패가 굳지 않는다. (TC-E2E-03)

남은 칸(11-05 ①-22 에서 채움 — 지금은 앞 고리가 없어 시험하지 않는다)
- (S181 에 채움) 웹훅 → 기록 → 알림 → DB 한 흐름은 `tests/test_alert_chain_pg.py`(TC-ECH 4)가 일회용 PG 로 끝까지 잇는다.
- 설계서 v1.0 · 대사 결과 보고(차이 원인 표) — ①-11 판 2 대사 뒤.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BN = ROOT / "public" / "js" / "baselinenotice.js"


def _summary_module():
    spec = importlib.util.spec_from_file_location("baseline_summary", ROOT / "scripts" / "baseline_summary.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def client():
    from app.main import app  # 라우트 · 정적 파일 마운트가 실제 앱과 같다(생명주기는 켜지 않는다 — DB 불필요)

    return TestClient(app)


@pytest.fixture(scope="module")
def trials():
    mod = _summary_module()
    return json.loads(mod.latest_trials().read_text(encoding="utf-8"))


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    return node


def _run_screen(tmp_path: Path, served: dict) -> dict:
    """화면 코드를 node 로 돌린다 — fetch 는 앱이 내준 응답을 그대로 흉내 낸다.

    served: {"first": {"status": int, "body": str}, "second": {...}} — 첫 번째 · 두 번째 요청에 줄 응답(두 번째가 없으면 첫 번째를 다시 준다).
    """
    (tmp_path / "served.json").write_text(json.dumps(served, ensure_ascii=False), encoding="utf-8")
    script = tmp_path / "run.mjs"
    script.write_text(
        f"""
import * as fs from "node:fs";
const served = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / "served.json"))}, "utf-8"));
const bn = await import({json.dumps(BN.resolve().as_uri())});
let calls = 0, lastUrl = null;
globalThis.fetch = async (url) => {{
  lastUrl = url;
  const r = calls === 0 ? served.first : (served.second || served.first);
  calls += 1;
  return {{ ok: r.status >= 200 && r.status < 300, status: r.status, json: async () => JSON.parse(r.body) }};
}};
// 화면 뼈대 흉내 — 탭 칸 둘 · 카드 자리 하나
const panes = bn.TABS.map((t) => ({{ dataset: {{ bnPane: t.view }}, hidden: false }}));
const slot = {{ innerHTML: "" }};
const mount = {{ innerHTML: "", querySelector: (sel) => (sel === ".bn-slot" ? slot : null) }};
const root = {{ getElementById: (id) => (id === bn.MOUNT_ID ? mount : null), querySelectorAll: () => panes }};
const out = {{ tabs: bn.TABS.map((t) => t.view) }};
const snap = () => ({{ tabHtml: mount.innerHTML, card: slot.innerHTML, visible: panes.filter((p) => !p.hidden).map((p) => p.dataset.bnPane) }});
await bn.renderBaselineNotice(bn.TABS[1].view, root);
out.first = snap();
out.firstUrl = lastUrl;
if (served.second) {{
  await bn.renderBaselineNotice(bn.TABS[1].view, root);
  out.second = snap();
}}
out.calls = calls;
process.stdout.write(JSON.stringify(out));
""",
        encoding="utf-8",
    )
    run = subprocess.run([_node(), str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def test_served_summary_is_source_and_code_is_served(client, trials):
    """TC-E2E-01 · 앱이 내주는 요약 = 원본 계산값 · 카드 · 별칭 코드도 같은 서버가 내준다."""
    mod = _summary_module()
    src = mod.latest_trials()
    day = re.search(r"(\d{4}-\d{2}-\d{2})", src.parent.name).group(1)
    served = client.get("/js/baseline-result.json", headers={"Cache-Control": "no-cache"})
    assert served.status_code == 200 and "json" in served.headers["content-type"]
    assert served.json() == mod.build_summary(trials, day), "서버가 내주는 요약이 원본과 다르다 — python scripts/baseline_summary.py"
    for path in ("/js/baselinenotice.js", "/js/viewalias.js"):
        r = client.get(path)
        assert r.status_code == 200 and "javascript" in r.headers["content-type"], path
    assert client.get("/js/baseline-result-없음.json").status_code == 404, "없는 파일은 404 (200 으로 대신 내주지 않는다)"


def test_tab2_shows_none_card_with_numbers_from_source(client, trials, tmp_path):
    """TC-E2E-02 · 탭 2 로 들어오면 「아직 없음」 카드 — 글 속 숫자가 원본에서 센 값과 같다."""
    body = client.get("/js/baseline-result.json").text
    out = _run_screen(tmp_path, {"first": {"status": 200, "body": body}})
    assert out["firstUrl"] == "/js/baseline-result.json"
    assert out["first"]["visible"] == ["indicator-backtest"], "성과 검증 탭 칸만 보인다"
    assert out["tabs"] == ["quant-backtest", "indicator-backtest"]
    text = _text(out["first"]["card"])

    rows = trials["trials"]
    line = trials["pass_line"]
    n = len(rows)
    assert sum(1 for r in rows if r["pass"]) == 0, "이 시험은 합격 0개 결과를 전제로 한다 — 결과가 바뀌면 이 단언을 합격 있음 꼴로 고친다"
    assert "아직 없음" in text and "있음" not in text.replace("아직 없음", ""), "합격이 없는데 있다고 하면 안 된다"
    counts = {
        "pf": sum(1 for r in rows if r["profit_factor"] is not None and r["profit_factor"] > line["profit_factor"]),
        "mdd": sum(1 for r in rows if r["mdd_pct"] > line["mdd_pct"]),
        "sharpe": sum(1 for r in rows if r["sharpe_ratio"] > line["sharpe_ratio"]),
    }
    for c in counts.values():
        assert f"{c} / {n}" in text, f"원본에서 센 넘은 수 {c} / {n} 이 카드에 없다"
    assert f'{line["sharpe_ratio"]:.1f}' in text, "합격선은 1 이 아니라 1.0 으로"
    near = trials["nearest"]
    assert str(near["short"]) in text and str(near["long"]) in text, "가장 가까운 시도의 이동평균 기간"
    assert "고른 것이 아닙니다" in text, "가장 가까운 시도는 참고용이라고 밝힌다"
    assert not re.search(r"profit_factor|sharpe_ratio|mdd_pct|entry_mode|exit_mode|undefined|NaN|\[object|null", out["first"]["card"]), "화면 글에 개발 티가 없다"
    assert "성과 검증" in _text(out["first"]["tabHtml"]) and "전략 분석" in _text(out["first"]["tabHtml"]), "탭 띠에 두 탭이 있다"


def test_unreadable_summary_is_not_none_and_retries_next_entry(client, tmp_path):
    """TC-E2E-03 · 요약을 못 읽으면 「확인 못 함」 · 다시 들어오면 읽어서 「아직 없음」."""
    good = client.get("/js/baseline-result.json").text
    out = _run_screen(tmp_path, {"first": {"status": 404, "body": "{}"}, "second": {"status": 200, "body": good}})
    first, second = _text(out["first"]["card"]), _text(out["second"]["card"])
    assert "확인 못 함" in first and "아직 없음" not in first, "못 읽었는데 「없음」 이라 우기지 않는다"
    assert "아직 없음" in second and "확인 못 함" not in second, "실패가 굳지 않고 다음 번에 다시 읽는다"
    assert out["calls"] == 2, "실패한 읽기는 다시 시도한다 · 성공하면 더 부르지 않는다"
