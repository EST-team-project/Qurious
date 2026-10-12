"""강사님 자료 변경 추적 스캐너 시험 (TC-LS) — 한 저장소를 부분(서버 · 화면)으로 나눈 기준점을 줄마다 비교한다.

2026-10-12 결정 Q7: th06(강사님 기초 코드)은 서버와 화면을 다른 때 받는다(서버 e815be3 · 화면 9478811). 기준점이 한 줄이면
「화면을 아직 안 받았다」 가 「서버도 안 받았다」 로 읽혀 서버 쪽 새 커밋이 이미 받은 커밋 사이에 섞인다. 그래서 같은 th 를 part
칸만 다르게 두 줄 두고, 스캐너는 줄마다 그 부분의 경로(PART_PATHS)를 건드린 커밋만 센다.

시험은 임시 폴더에 가짜 강사님 저장소(커밋 셋 — 처음 · 서버만 · 화면만)를 만들어 돌린다. 네트워크 · 실제 learning/ 을 쓰지 않는다.
"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import lecture_scan as ls  # noqa: E402

GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_CONFIG_NOSYSTEM": "1"}


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                       env=GIT_ENV, check=True)
    return r.stdout.strip()


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _lecture(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """learning/th99-demo/lecture — 처음(서버 · 화면) → 서버만 → 화면만, 원격 참조 origin/main 은 끝."""
    repo = tmp_path / "learning" / "th99-demo" / "lecture"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "core.autocrlf", "false")
    shas = {
        "first": _commit(repo, {"app/a.py": "a = 1\n", "public/x.js": "let x = 1;\n"}, "처음"),
        "server": _commit(repo, {"app/a.py": "a = 2\n"}, "서버만 고침"),
        "screen": _commit(repo, {"public/x.js": "let x = 2;\n"}, "화면만 고침"),
    }
    _git(repo, "update-ref", "refs/remotes/origin/main", shas["screen"])
    _git(repo, "remote", "add", "origin", "https://github.com/edumgt/demo.git")
    return repo, shas


def _baseline(path: Path, rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ls.FIELDS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({"th": "th99-demo", "repo": "edumgt/demo", "ref": "origin/main", "commit_date": "-", "checked_at": "-", **r})
    return path


def _subjects(row: dict) -> list[str]:
    return [subject for _h, _when, subject in row["commits"]]


def test_parts_count_only_their_own_paths(tmp_path):
    """TC-LS-01 · 서버 줄은 public/ 밖을 건드린 커밋만, 화면 줄은 public/ 을 건드린 커밋만 센다(같은 기준 커밋이어도)."""
    _repo, sha = _lecture(tmp_path)
    base = ls.read_baseline(_baseline(tmp_path / "b.tsv", [{"part": "서버", "commit": sha["first"]},
                                                            {"part": "화면", "commit": sha["first"]}]))
    rows = {r["part"]: r for r in ls.scan(tmp_path / "learning", base, since_days=7)}
    assert set(rows) == {"서버", "화면"}
    assert rows["서버"]["state"] == "바뀜" and _subjects(rows["서버"]) == ["서버만 고침"]
    assert rows["화면"]["state"] == "바뀜" and _subjects(rows["화면"]) == ["화면만 고침"]
    assert ls.label(rows["서버"]) == "th99-demo · 서버"


def test_part_with_no_new_commit_on_its_paths_is_unchanged(tmp_path):
    """TC-LS-02 · 끝은 움직였어도 그 부분의 경로를 건드린 새 커밋이 없으면 「변화 없음」 — 서버를 「서버만 고침」 까지 받은 경우."""
    _repo, sha = _lecture(tmp_path)
    base = ls.read_baseline(_baseline(tmp_path / "b.tsv", [{"part": "서버", "commit": sha["server"]},
                                                            {"part": "화면", "commit": sha["first"]}]))
    rows = {r["part"]: r for r in ls.scan(tmp_path / "learning", base, since_days=7)}
    assert rows["서버"]["state"] == "변화 없음" and rows["서버"]["commits"] == []
    assert rows["화면"]["state"] == "바뀜" and _subjects(rows["화면"]) == ["화면만 고침"]


def test_whole_repo_line_is_unchanged_behaviour(tmp_path):
    """TC-LS-03 · part 가 빈 줄(다른 th 모두)은 예전처럼 저장소 전체 — 두 커밋을 모두 센다. 기준점 쓰기는 part 를 지킨다."""
    _repo, sha = _lecture(tmp_path)
    base = ls.read_baseline(_baseline(tmp_path / "b.tsv", [{"part": "", "commit": sha["first"]}]))
    rows = ls.scan(tmp_path / "learning", base, since_days=7)
    assert len(rows) == 1 and rows[0]["state"] == "바뀜" and _subjects(rows[0]) == ["서버만 고침", "화면만 고침"]
    out = tmp_path / "written.tsv"
    two = ls.scan(tmp_path / "learning", ls.read_baseline(_baseline(tmp_path / "c.tsv", [
        {"part": "서버", "commit": sha["server"]}, {"part": "화면", "commit": sha["first"]}])), since_days=7)
    ls.write_baseline(out, two)
    with out.open(encoding="utf-8", newline="") as f:
        written = list(csv.DictReader(f, delimiter="\t"))
    assert [(r["th"], r["part"]) for r in written] == [("th99-demo", "서버"), ("th99-demo", "화면")]


def test_unknown_part_is_reported_not_silently_whole_repo(tmp_path):
    """TC-LS-04 · 모르는 부분 이름은 저장소 전체로 말없이 바꾸지 않고 상태 글로 알린다(말없는 fallback 금지)."""
    _repo, sha = _lecture(tmp_path)
    base = ls.read_baseline(_baseline(tmp_path / "b.tsv", [{"part": "문서", "commit": sha["first"]}]))
    row = ls.scan(tmp_path / "learning", base, since_days=7)[0]
    assert row["state"].startswith("모르는 부분") and row["commits"] == []


def test_real_baseline_splits_th06_into_server_and_screen():
    """TC-LS-05 · 실제 기준점 TSV — th06 은 서버 · 화면 두 줄이고 나머지 th 는 part 가 빈 한 줄씩이다."""
    rows = ls.read_baseline(ls.DEFAULT_BASELINE)
    assert sorted(r["part"] for r in rows["th06-lumina-invest"]) == ["서버", "화면"]
    others = [r for th, rs in rows.items() if th != "th06-lumina-invest" for r in rs]
    assert others and all(r["part"] == "" for r in others)
    assert all(len(rs) == 1 for th, rs in rows.items() if th != "th06-lumina-invest")
