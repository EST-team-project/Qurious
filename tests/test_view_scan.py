"""화면 스캐너 시험 (TC-VW) — IA 의 화면 수 · 메뉴 그림이 믿을 만한가.

IA 의 화면 전수표와 메뉴 그림은 `scripts/view_scan.py` 출력을 옮긴 것이다. 2026-10-02 에 메뉴 표에
소제목 아래 들여쓴 항목(`sub: true`)이 생기자, 스캐너가 그 아홉을 세지 못해 「메뉴에 없는 화면 9」 를 냈다.
그래서 메뉴 한 줄을 읽는 규칙과, 실제 메뉴 표의 「화면으로 가는 줄」 을 하나도 놓치지 않는지를 잰다.
지금의 화면 수(65 등)처럼 팀원이 화면을 더하면 바뀌는 숫자는 걸지 않는다.
"""
from __future__ import annotations

import re
from pathlib import Path

from scripts import view_scan

ROOT = Path(__file__).resolve().parents[1]


def test_menu_item_rule_reads_indented_items():
    """TC-VW-01 · 메뉴 한 줄 규칙 — 보통 항목과 들여쓴 항목(`sub: true`)은 읽고, 소제목 · 앱 밖 링크(`href`)는 화면으로 세지 않는다."""
    rule = view_scan.MENU_ITEM_RE
    plain = '      { key: "fin-lectures",  icon: "fa-solid fa-chalkboard-user",  label: "강의실 (전체 과정)" },'
    sub = '      { key: "fin-topic-futures", icon: "fa-solid fa-scale-unbalanced", label: "선물과 옵션", sub: true },'
    heading = '      { heading: "강의" },'
    link = '      { key: "learn-home", icon: "fa-solid fa-map", label: "전체 목차",  href: "/learn/#/" },'
    assert rule.search(plain).groups() == ("fin-lectures", "강의실 (전체 과정)")
    assert rule.search(sub).groups() == ("fin-topic-futures", "선물과 옵션")
    assert rule.search(heading) is None
    assert rule.search(link) is None


def test_scan_counts_every_menu_line_that_opens_a_screen():
    """TC-VW-02 · 실제 메뉴 표에서 화면으로 가는 줄(`key:` 가 있고 `href` 가 없는 줄)을 스캐너가 모두 세고, 그 화면이 모두 선언돼 있다."""
    core = (ROOT / "public" / "js" / "core.js").read_text(encoding="utf-8")
    menu_src = core[core.index("const GNB_MENUS = {"):]
    menu_src = menu_src[:menu_src.index("\n};\n") + 3]
    expected = [m.group(1) for line in menu_src.splitlines()
                if "href:" not in line and (m := re.search(r'\{ key: "([^"]+)"', line))]
    result = view_scan.scan()
    found = [r["key"] for r in result["rows"]]
    assert found == expected, "메뉴 표의 줄을 스캐너가 놓쳤거나 더 셌다"
    app = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    for key in found:
        assert f'data-view="{key}"' in app, f"메뉴 「{key}」 가 가리키는 화면이 app.html 에 없다"
