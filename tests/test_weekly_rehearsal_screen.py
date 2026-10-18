"""TC-WRS · 복구 시험 줄 — 관제(datahub.js) · 적재 · 백업(collect.js) 화면이 서버의 rehearsal 칸을 그대로 보인다(2차-3 · 2026-10-18).

화면은 날 수 · 상태를 다시 세지 않는다(서버 `data_status.rehearsal_view` 한 곳) — 상태 이름이 서버와 같고, 글은 서버 글을 이스케이프해 싣는다.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.services import data_status as ds

ROOT = Path(__file__).resolve().parents[1]
DATAHUB = (ROOT / "public" / "js" / "datahub.js").read_text(encoding="utf-8")
COLLECT = (ROOT / "public" / "js" / "collect.js").read_text(encoding="utf-8")


def test_관제_화면의_상태_색은_서버_상태_다섯을_다_덮는다():
  m = re.search(r"^const REHEARSAL_CLASS = \{([^}]*)\};", DATAHUB, re.M)
  assert m, "상태 → 색 표가 없다"
  assert set(re.findall(r"(\w+):", m.group(1))) == set(ds.REHEARSAL_STATE)


def test_관제_요약과_카드_둘_다_복원_리허설_줄을_싣는다():
  assert re.search(r'^\s+\["복원 리허설", rehearsalBrief\(st\.rehearsal\)\],', DATAHUB, re.M)
  assert re.search(r'^\s+\["복원 리허설", `<span class="dh-big q-tone--\$\{REHEARSAL_CLASS\[st\.rehearsal\?\.state\]', DATAHUB, re.M)
  brief = DATAHUB[DATAHUB.index("function rehearsalBrief("):]
  brief = brief[: brief.index("\n}") + 2]
  assert "escHtml(rh.label)" in brief and "escHtml(rh.schedule_label)" in brief
  assert "Date" not in brief, "화면이 날 수를 다시 세지 않는다"


def test_적재_백업의_복원_리허설_줄에_서버_글을_붙인다():
  assert re.search(r'g\.key === "restore" && b\.rehearsal \? `복원 리허설 — \$\{b\.rehearsal\.label\} · \$\{b\.rehearsal\.schedule_label\}`',
                   COLLECT)
