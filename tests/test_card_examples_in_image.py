"""TC-SC-IMG — 전략 카드 예시 폴더가 앱 이미지 · 개발 컨테이너 안에 있다 (2026-10-29 · 신장환 님 #392 가 짚은 S160 결함)

`GET /api/strategy-cards`(app/routes/strategy_cards.py)와 그림자 일지(app/services/paper_journal.py)는 `<앱 루트>/docs/phase-3/02-design/system/예시/` 를
읽는다. 그런데 Dockerfile 이 `app/ public/ prompts/ alembic/` 만 복사해 **앱 컨테이너 안에서는 이 폴더가 없고 카드 목록이 비었다**(실제로 cards 0건).
지금 약속: Dockerfile 이 이 폴더만 이미지에 넣고, 개발 compose 는 같은 폴더를 읽기 전용으로 붙이며, 두 곳이 코드가 읽는 경로와 같다.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from app.routes import strategy_cards as SC
from app.services import paper_journal as PJ

ROOT = Path(__file__).resolve().parents[1]
REL = "docs/phase-3/02-design/system/예시"


def test_code_reads_the_same_relative_path():
    """TC-SC-IMG-01 · 두 코드가 읽는 폴더가 REL 이고, 그 안에 카드 파일이 실제로 있다(판 1 · 판 2)."""
    assert SC.CARD_DIR == ROOT / REL
    assert PJ.CARD_PATH.parent == ROOT / REL and PJ.CARD_PATH.is_file()
    names = sorted(p.name for p in (ROOT / REL).glob("strategy-card-*.json"))
    assert "strategy-card-ma-cross-v1.json" in names and len(names) >= 2


def test_dockerfile_copies_only_that_docs_folder():
    """TC-SC-IMG-02 · Dockerfile 이 이 폴더를 같은 경로로 복사한다 — docs/ 전체가 아니라 이 폴더만."""
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    copies = re.findall(r"^COPY\s+(docs\S*)\s+(\S+)", text, re.M)
    assert copies == [(f"{REL}/", f"./{REL}/")], copies


def test_dev_compose_mounts_it_read_only():
    """TC-SC-IMG-03 · 개발 compose 의 앱 서비스가 같은 폴더를 /app/… 로 읽기 전용으로 붙인다(이미지를 다시 빌드하지 않아도 보이게)."""
    compose = yaml.safe_load((ROOT / "scripts" / "personal" / "compose.dev.yml").read_text(encoding="utf-8"))
    mounts = [v for svc in compose["services"].values() for v in (svc.get("volumes") or []) if isinstance(v, str) and REL in v]
    assert mounts == [f"./{REL}:/app/{REL}:ro"], mounts
