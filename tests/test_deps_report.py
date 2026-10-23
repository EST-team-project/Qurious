"""의존성 갱신 보고서 시험 (TC-DR) — scripts/personal/deps_report.py (결정 D4 · D5 · 2026-10-23).

무엇을 지키나
1. 판 갈래(주 · 부 · 고침 · 새로 · 빠짐)를 바르게 가른다 — 날짜형 판(certifi 2026.x)도 같은 셈법.
2. 붙여 넣을 명령 — 고침 판은 한 PR 로 묶고(계약 패키지 밖), 계약 패키지는 하나씩 · 부 · 주 판은 「카나리아 먼저」.
3. 이미지 — 같은 태그의 새 다이제스트를 알아보고, 같은 꼴(v · -alpine · -community)의 태그만 견줘 같은 줄 · 위 줄 새 판을 고른다.
4. 동결 기간(11-05 ~ 11-12)에는 「보안 고침만」 · 식힘 7일.
5. 네트워크 없이도(--no-network) 끝까지 돌고, 알리기만 한다(잠금 · compose 를 고치지 않는다).

돌리는 법 — 호스트에서 네트워크 없이(가짜 응답).
"""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("deps_report", ROOT / "scripts" / "personal" / "deps_report.py")
dr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dr)


@pytest.mark.parametrize("old, new, kind", [
    ("1.19.1", "1.19.2", "고침"), ("1.19.1", "1.20.0", "부"), ("6.4.0", "7.0.0", "주"),
    ("2026.7.9", "2026.10.5", "부"), (None, "1.0", "새로"), ("1.0", None, "빠짐"), ("1.0", "1.0", "같음"),
])
def test_classify(old, new, kind):
    """TC-DR-01 · 판 갈래 — 셋째 자리 = 고침 · 둘째 = 부 · 첫째 = 주(날짜형 판도 같은 셈법)."""
    assert dr.classify(old, new) == kind


def test_diff_and_commands_bundle_patches_and_isolate_contracts():
    """TC-DR-02 · 고침 판(계약 밖)은 한 묶음 명령 · 계약 패키지 고침은 따로 · 계약 부 판은 「카나리아 먼저」 · 계약 밖 부 판은 명령 없음(표에만)."""
    old = dr.parse_lock("# 머리\nnumpy==2.5.3\nqdrant-client==1.19.1\nsqlalchemy==2.1.1\nlangchain-core==1.6.5\n"
                        "pandas==3.0.6\ncolorama==0.4.6 ; sys_platform == 'win32'\n    # via 줄\n")
    new = dr.parse_lock("numpy==2.5.4\nqdrant-client==1.20.0\nsqlalchemy==2.1.6\nlangchain-core==1.6.9\n"
                        "pandas==3.1.0\ncolorama==0.4.6\nopentelemetry-api==1.0\n")
    rows = {r["name"]: r for r in dr.diff_locks(old, new)}
    assert set(rows) == {"numpy", "qdrant-client", "sqlalchemy", "langchain-core", "pandas", "opentelemetry-api"}
    assert rows["qdrant-client"]["kind"] == "부" and rows["qdrant-client"]["contract"]
    assert rows["opentelemetry-api"]["kind"] == "새로"
    cmds = dr.upgrade_commands(list(rows.values()))
    bundle = cmds["고침 묶음(한 PR)"]
    assert "-P numpy" in bundle and "-P sqlalchemy" in bundle and "langchain-core" not in bundle and "pandas" not in bundle
    assert bundle.startswith("uv pip compile requirements-dev.txt --universal --python-version 3.12 -o requirements.lock")
    assert cmds["계약 고침 langchain-core"].endswith("-P langchain-core")
    assert "계약 부 판 qdrant-client — 카나리아 먼저" in cmds
    assert not any("pandas" in k for k in cmds)


def test_tag_picking_keeps_the_same_flavour():
    """TC-DR-03 · 같은 꼴 태그만 견준다 — -alpine 은 -alpine 끼리(-alpine3.22 · -bookworm 은 뺌) · v 머리 · 같은 줄(마지막 자리만 다름)과 위 줄."""
    q = dr.split_image("qdrant/qdrant:v1.19.1@sha256:" + "1" * 64)
    assert (q["repo"], q["tag"], q["nums"], q["prefix"], q["suffix"]) == ("qdrant/qdrant", "v1.19.1", (1, 19, 1), "v", "")
    assert dr.newer_tags(q, ["v1.19.0", "v1.19.2", "v1.20.0", "1.21.0", "v1.20.1-unprivileged", "latest"]) == \
        {"same_line": "v1.19.2", "higher": "v1.20.0"}
    pg = dr.split_image("postgres:16.15-alpine@sha256:" + "2" * 64)
    assert dr.newer_tags(pg, ["16.16-alpine", "16.16-alpine3.22", "17.0-alpine", "16.16-bookworm", "16.14-alpine"]) == \
        {"same_line": "16.16-alpine", "higher": "17.0-alpine"}
    neo = dr.split_image("neo4j:5.18.1-community@sha256:" + "3" * 64)
    assert dr.newer_tags(neo, ["5.26.32-community", "5.18.1-enterprise", "5.26.32"]) == {"same_line": "", "higher": "5.26.32-community"}


def test_image_rows_find_redigest_and_merge_same_image():
    """TC-DR-04 · 같은 태그의 새 다이제스트(바탕 OS 고침)를 알아본다 · 같은 이미지를 쓰는 서비스는 한 줄 · 응답이 없으면 「모름」."""
    pinned = "a" * 64
    images = {"ollama": f"ollama/ollama:0.32.5@sha256:{pinned}", "model-pull": f"ollama/ollama:0.32.5@sha256:{pinned}",
              "redis": f"redis:8.10.2-alpine@sha256:{pinned}"}
    seen: list[str] = []

    def fake(url):
        seen.append(url)
        if "/tags/0.32.5" in url:
            return {"digest": "sha256:" + pinned, "last_pushed": "2026-07-27T18:54:22Z"}
        if "/tags/8.10.2-alpine" in url:
            return {"digest": "sha256:" + "b" * 64, "last_pushed": "2026-10-22T15:05:53Z"}
        if "ollama" in url:
            return {"results": [{"name": "0.40.9"}, {"name": "0.32.6"}, {"name": "0.40.9-rocm"}]}
        return None

    rows = {r["service"]: r for r in dr.image_rows(images, fake)}
    assert set(rows) == {"ollama · model-pull", "redis"}
    assert sum("/tags/0.32.5" in u for u in seen) == 1, "같은 이미지를 두 번 물었다"
    assert not rows["ollama · model-pull"]["redigest"] and rows["ollama · model-pull"]["same_line"] == "0.32.6"
    assert rows["ollama · model-pull"]["higher"] == "0.40.9"
    assert rows["redis"]["redigest"] and rows["redis"]["pushed"] == "2026-10-22"
    text = dr.render(date(2026, 10, 26), date(2026, 10, 19), [], "", list(rows.values()), {})
    assert "있음(2026-10-22)" in text and "| 0.32.6 | 0.40.9 |" in text


def test_freeze_window_and_cooldown():
    """TC-DR-05 · 11-05 ~ 11-12 는 동결(보안 고침만) · 그 밖은 정기 갱신 · 식힘 7일."""
    assert "동결" in dr.phase_note(date(2026, 11, 5)) and "동결" in dr.phase_note(date(2026, 11, 12))
    assert "정기 갱신" in dr.phase_note(date(2026, 11, 4)) and "정기 갱신" in dr.phase_note(date(2026, 11, 13))
    assert dr.COOLDOWN_DAYS == 7


def test_no_network_run_writes_report_and_touches_nothing(tmp_path, monkeypatch):
    """TC-DR-06 · --no-network 로 끝까지 돈다 — 보고서 파일만 쓰고 잠금 · compose · Dockerfile 은 그대로(알리기만)."""
    watched = [ROOT / "requirements.lock", ROOT / "docker-compose.yml", ROOT / "Dockerfile"]
    before = [p.read_bytes() for p in watched]
    out = tmp_path / "r.md"
    assert dr.main(["--no-network", "--out", str(out), "--today", "2026-10-26"]) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# 의존성 갱신 보고서 — 2026-10-26") and "건너뜀 — --no-network" in text
    assert "| qdrant |" in text and "(바탕)" in text and "ollama · model-pull" in text
    assert [p.read_bytes() for p in watched] == before
    src = (ROOT / "scripts" / "personal" / "deps_report.py").read_text(encoding="utf-8")
    assert "api.github.com" not in src and "github.com/" not in src   # GitHub 은 부르지 않는다(계정 보호 규칙)
