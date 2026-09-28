"""`post_check.py` 의 색인 검사 — 글 폴더를 더하고 README 색인에 줄을 안 더하면 알려 주는지 본다.

2026-09-28 S54 의 PR #28 이 `이슈-화면결함-파트별/` · `PR-docs-wireframe-v0-2/` 를 더하면서 색인(README 3절)을
비워 뒀다. 번호가 올린 뒤에 나오니 "다음 기록 PR 에서" 로 미룬 것인데, 미룬 사실이 어디에도 안 남아 S55 에
폴더를 하나씩 대조해서야 알았다. 색인 표의 링크는 `(<날짜>/<글 폴더>/00-본문.md)` 꼴이라 그 문자열로 센다.
"""
from __future__ import annotations

from scripts import post_check


def _archive(tmp_path, readme: str):
    base = tmp_path / "github-archive"
    for post in ["이슈-001", "PR-새글"]:
        (base / "2026-09-28" / post).mkdir(parents=True)
    (base / "attachments" / "img").mkdir(parents=True)   # 날짜 폴더가 아닌 것은 세지 않는다
    (base / "README.md").write_text(readme, encoding="utf-8")
    return base


def test_unindexed_folders_lists_only_missing(tmp_path):
    base = _archive(tmp_path, "| [이슈 #1](2026-09-28/이슈-001/00-기록.md) | … |\n")
    assert post_check.unindexed_folders(base) == ["2026-09-28/PR-새글/"]


def test_unindexed_folders_empty_when_all_linked(tmp_path):
    base = _archive(tmp_path, "(2026-09-28/이슈-001/00-기록.md)\n(2026-09-28/PR-새글/00-본문.md)\n")
    assert post_check.unindexed_folders(base) == []


def test_unindexed_folders_ignores_name_prefix(tmp_path):
    """`PR-새글` 이 색인에 있어도 `PR-새` 는 없는 것이다 — 폴더 이름 뒤 `/` 까지 맞춘다."""
    base = _archive(tmp_path, "(2026-09-28/이슈-001/x.md) (2026-09-28/PR-새글/x.md)\n")
    (base / "2026-09-28" / "PR-새").mkdir()
    assert post_check.unindexed_folders(base) == ["2026-09-28/PR-새/"]
