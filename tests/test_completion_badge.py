"""기능 완성도 배지 시험 (TC-CP) — 배지에 뜨는 팀 점검 줄이 점검표(정본)와 같은가.

배경 (2026-10-04 기능 완성도 전체 점검)
  화면 오른쪽 아래 배지는 public/js/completion.js 의 ASSESSMENTS(강사님 2026-09-29 감사)를 읽는다. 그 표는 점수를
  글자로 박아 둔 고정 표라 개발해도 숫자가 바뀌지 않는다(09-30 뒤 아무도 안 고침 · 새 화면 16개가 「미평가 0%」).
  그래서 이동원 몫 화면을 같은 기준으로 다시 매겨 public/js/teamcompletion.js 에 두고 completion.js 가 덮게 했다.
  정본은 docs/시험/대장/기능완성도-점검표.tsv 이고, 이 시험은 둘이 어긋나면 실패한다.

이 시험이 보지 않는 것 — 팀원 화면의 점수 · 새로 생긴 화면의 평가 유무. 그것을 시험으로 막으면 팀원 PR 이 실패하므로
팀 결정(점검 이슈) 뒤로 미룬다. 여기서는 이동원 몫 줄과 점검표 자체의 셈만 본다.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
TSV = ROOT / "docs" / "시험" / "대장" / "기능완성도-점검표.tsv"
MAX = {"UI": 20, "서버": 30, "연동": 25, "시험": 25}
LINE_RE = re.compile(r'^\s*"?([a-z0-9-]+)"?:\s*A\((\d+),\s*"([^"]+)",\s*"([^"]+)"\)', re.M)


def _rows() -> list[dict]:
    with TSV.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _team() -> dict[str, tuple[int, str, str]]:
    src = (PUB / "js" / "teamcompletion.js").read_text(encoding="utf-8")
    return {m.group(1): (int(m.group(2)), m.group(3), m.group(4)) for m in LINE_RE.finditer(src)}


def test_team_lines_match_the_audit_sheet():
    """TC-CP-01 · 배지 팀 줄 = 점검표의 「배지반영 = 예」 줄(키 · 점수 · 이름표가 같다)."""
    team = _team()
    sheet = {r["화면키"]: (int(r["점수"]), r["이름표"]) for r in _rows() if r["배지반영"] == "예"}
    assert team, "teamcompletion.js 에서 줄을 하나도 못 읽었다 — A(점수, \"이름표\", \"근거\") 꼴인지 볼 것"
    assert set(team) == set(sheet), f"배지에만 {sorted(set(team) - set(sheet))} · 점검표에만 {sorted(set(sheet) - set(team))}"
    for key, (score, label, _ev) in team.items():
        assert (score, label) == sheet[key], f"{key}: 배지 {score} {label} ↔ 점검표 {sheet[key]}"


def test_team_keys_are_real_screens():
    """TC-CP-02 · 팀 줄의 키가 실제 화면이다 — app.html 의 data-view 또는 따로 쪽(login · register)의 body data-view."""
    views = set(re.findall(r'<div class="view" data-view="([^"]+)">', (PUB / "app.html").read_text(encoding="utf-8")))
    for page in ("login.html", "register.html"):
        views |= set(re.findall(r'<body data-view="([^"]+)"', (PUB / page).read_text(encoding="utf-8")))
    missing = sorted(set(_team()) - views)
    assert not missing, f"화면에 없는 키: {missing}"


def test_completion_js_lets_team_lines_win():
    """TC-CP-03 · completion.js 가 팀 줄을 들여와 강사님 표 **뒤에서** 덮는다(같은 키면 팀 줄이 이긴다)."""
    src = (PUB / "js" / "completion.js").read_text(encoding="utf-8")
    assert 'import { TEAM_ASSESSMENTS } from "/js/teamcompletion.js";' in src
    table_end = src.index("\n};", src.index("const ASSESSMENTS = {"))
    merge = src.index("Object.assign(ASSESSMENTS, TEAM_ASSESSMENTS);")
    assert merge > table_end
    assert "ASSESSMENTS[view]" in src   # 그리는 쪽이 같은 표를 읽는다


def test_audit_sheet_arithmetic():
    """TC-CP-04 · 점검표의 셈 — 배점표 줄은 점수 = UI + 서버 + 연동 + 시험(칸마다 상한 안), 강사님+고침 줄은 강사님 + 고침 합."""
    rows = _rows()
    assert len(rows) == len({r["화면키"] for r in rows}), "같은 화면이 두 번 적혔다"
    for r in rows:
        score = int(r["점수"])
        assert 0 <= score <= 100, r["화면키"]
        if r["방법"] == "배점표":
            parts = {k: int(r[k]) for k in MAX}
            assert all(0 <= parts[k] <= MAX[k] for k in MAX), (r["화면키"], parts)
            assert score == sum(parts.values()), r["화면키"]
        else:
            assert r["방법"] == "강사님+고침", r["화면키"]
            deltas = [int(m) for m in re.findall(r"(?:^| · )([+-]\d+) ", r["고침"])]
            assert score == max(0, min(95, int(r["강사님"]) + sum(deltas))), (r["화면키"], deltas)


def test_team_evidence_marks_itself():
    """TC-CP-05 · 팀 줄의 근거 글은 「팀 점검 10-04」 를 앞에 붙인다(마우스를 올린 사람이 강사님 감사와 구별하게)."""
    src = (PUB / "js" / "teamcompletion.js").read_text(encoding="utf-8")
    assert "evidence: `팀 점검 10-04 · ${evidence}`" in src
