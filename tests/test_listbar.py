"""TC-LB — 목록 필터 · 새로고침 공용 도우미 (public/js/listbar.js · 2026-11-05 화면 전수 점검 뒤)

화면마다 따로 만들지 않고 한 곳을 쓴다. 순수 함수는 node 로 실제로 돌린다.
1. 칩은 aria-pressed 로 눌림을 알리고 새로고침 단추가 한 줄에 붙으며, 글은 이스케이프된다. (TC-LB-01)
2. applyFilters 는 빈 값 · 모르는 key 를 무시하고 겹쳐 건다. isAllowed 는 모르는 낱말을 막는다. (TC-LB-02)
3. filterSummary · refreshStamp 글. (TC-LB-03)
4. bindListBar 는 칩 · 새로고침 클릭만 받고 한 번만 묶인다. (TC-LB-04)
node 가 없으면 건너뛴다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "public" / "js" / "listbar.js").read_text(encoding="utf-8")
NODE = shutil.which("node")
MODULE = re.sub(r"^export ", "", SRC, flags=re.M)      # node -e 에서 바로 쓰도록 export 만 뗀다


def _run(body: str):
    js = MODULE + textwrap.dedent("""
        const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
    """) + textwrap.dedent(body)
    out = subprocess.run([NODE, "-"], input=js, capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


GROUPS = """
const GROUPS = [{ key: "side", label: "매매", value: "매수", options: [{ value: "", label: "전체" }, { value: "매수", label: "매수" }, { value: "매도", label: "매도" }] },
                { key: "src", label: "출처", value: "", options: [{ value: "", label: "전체" }, { value: "SIM", label: "SIM" }] }];
"""


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_bar_html_marks_pressed_chip_adds_refresh_and_escapes():
    """TC-LB-01 · 눌린 칩만 aria-pressed=true · 새로고침 단추는 마지막 묶음 줄에 붙는다 · 칩이 없으면 단추만 · 라벨 · 안내 글은 이스케이프."""
    got = _run(GROUPS + """
      const html = listBarHtml(esc, { groups: GROUPS, note: '<img src=x>' });
      const only = listBarHtml(esc, {});
      const none = listBarHtml(esc, { groups: GROUPS, refresh: false });
      console.log(JSON.stringify({
        pressed: (html.match(/aria-pressed="true"/g) || []).length, chips: (html.match(/data-lb-filter=/g) || []).length,
        refreshInLast: html.lastIndexOf("data-lb-refresh") > html.lastIndexOf("출처"), escaped: html.includes("&lt;img") && !html.includes("<img"),
        onlyRefresh: only.includes("data-lb-refresh") && !only.includes("data-lb-filter"), noRefresh: !none.includes("data-lb-refresh"),
        label: html.includes('aria-label="목록 필터"') }));
    """)
    assert got == {"pressed": 2, "chips": 5, "refreshInLast": True, "escaped": True, "onlyRefresh": True, "noRefresh": True, "label": True}, got


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_apply_filters_and_allowed():
    """TC-LB-02 · 겹쳐 걸면 모두 맞는 줄만 · 빈 값 · 모르는 key 는 안 건다 · 원본 배열을 바꾸지 않는다 · 허용 밖 낱말은 막는다."""
    got = _run(GROUPS + """
      const rows = [{ s: "매수", o: "SIM" }, { s: "매도", o: "SIM" }, { s: "매수", o: "KIS" }];
      const g = { side: r => r.s, src: r => r.o };
      const a = applyFilters(rows, { side: "매수", src: "SIM" }, g).length;
      const b = applyFilters(rows, { side: "", src: "" }, g).length;
      const c = applyFilters(rows, { nope: "x", side: "매도" }, g).length;
      const copy = applyFilters(rows, {}, g) !== rows;
      console.log(JSON.stringify({ a, b, c, copy, ok: isAllowed(GROUPS, "side", "매도"), bad: isAllowed(GROUPS, "side", "BUY"), badKey: isAllowed(GROUPS, "x", "") }));
    """)
    assert got == {"a": 1, "b": 3, "c": 1, "copy": True, "ok": True, "bad": False, "badKey": False}, got


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_summary_and_refresh_stamp():
    """TC-LB-03 · 걸린 조건 글(받은 N줄 중 M줄) · 조건이 없으면 빈 글 · 다시 읽은 시각은 KST HH:MM."""
    got = _run(GROUPS + """
      console.log(JSON.stringify({
        on: filterSummary(GROUPS, { side: "매수", src: "SIM" }, 30, 4), off: filterSummary(GROUPS, { side: "", src: "" }, 30, 30),
        stamp: refreshStamp("다시 읽었습니다", new Date(Date.UTC(2026, 10, 5, 3, 7))) }));
    """)
    assert got["on"] == "조건 매수 · SIM — 받은 30줄 중 4줄" and got["off"] == ""
    assert got["stamp"] == "다시 읽었습니다(12:07)", got


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_bind_receives_only_chip_and_refresh_clicks_once():
    """TC-LB-04 · bindListBar — 칩은 onFilter(key, value) · 새로고침은 onRefresh · 다른 클릭은 무시 · 두 번 묶어도 한 번만 받는다."""
    got = _run("""
      const listeners = [];
      const root = { contains: () => true, addEventListener: (t, f) => listeners.push(f) };
      const calls = [];
      bindListBar(root, { onFilter: (k, v) => calls.push(["f", k, v]), onRefresh: () => calls.push(["r"]) });
      bindListBar(root, { onFilter: () => calls.push(["dup"]) });
      const mk = sel => ({ closest: s => (s === sel ? { dataset: { lbFilter: "side", value: "매수" } } : null) });
      const click = target => listeners.forEach(f => f({ target }));
      click({ closest: s => (s === "button[data-lb-filter]" ? { dataset: { lbFilter: "side", value: "매수" } } : null) });
      click({ closest: s => (s === "button[data-lb-refresh]" ? {} : null) });
      click({ closest: () => null });
      console.log(JSON.stringify({ listeners: listeners.length, calls }));
    """)
    assert got == {"listeners": 1, "calls": [["f", "side", "매수"], ["r"]]}, got


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_server_refresh_note():
    """TC-LB-05 · serverRefreshNote — 서버가 붙인 refresh 칸을 한 줄로: 요청이 아니면 빈 글 · 저장본 재사용 · 다시 받음."""
    got = _run("""
      const t = new Date(Date.UTC(2026, 10, 5, 3, 7));
      console.log(JSON.stringify({
        none: serverRefreshNote(undefined, t), notReq: serverRefreshNote({ requested: false }, t),
        reused: serverRefreshNote({ requested: true, reused_cache: true, min_age_seconds: 60 }, t),
        fresh: serverRefreshNote({ requested: true, reused_cache: false, min_age_seconds: 60 }, t) }));
    """)
    assert got == {"none": "", "notReq": "", "reused": "60초 안에 받은 값이라 그대로 보입니다(12:07)", "fresh": "외부 시세를 다시 받았습니다(12:07)"}, got
