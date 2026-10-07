"""docs 판 도구 시험 (TC-DV) — 지난판 사본의 링크 · 이름 · 판 규칙 (2026-10-07 docs 정리 뒤).

판을 올릴 때 지금 파일을 지난판/ 에 그냥 복사하면 한 칸 아래 폴더라 상대 링크가 모두 어긋난다.
`--bump` 가 링크를 새 자리에 맞춰 사본을 만드는지, `--check` 가 맨 위의 판 붙은 문서 · 짝 없는 사본을
잡는지 본다. 네트워크 · git · DB 를 쓰지 않는다(임시 폴더). 실제 docs 를 시험으로 막지는 않는다 —
팀원 PR 이 옛 습관(판 붙은 새 파일)으로 실패하지 않게, 실제 폴더는 `--check` 와 점검으로 본다.
"""

import pytest

from scripts import docs_scan

HEAD = "# 요구사항 추적표(RTM) v1.12 — Qurious\r\n\r\n| 문서 정보 | |\r\n|---|---|\r\n| **판 · 상태** | v1.12 · 초안 |\r\n"


def _tree(tmp_path):
  (tmp_path / "docs/요구사항/지난판").mkdir(parents=True)
  (tmp_path / "docs/요구사항/대장").mkdir()
  (tmp_path / "docs/요구사항/img").mkdir()
  (tmp_path / "docs/설계").mkdir(parents=True)
  (tmp_path / "docs/설계/기능설계.md").write_text("x", encoding="utf-8")
  (tmp_path / "docs/요구사항/대장/요구-대장.tsv").write_text("x", encoding="utf-8")
  (tmp_path / "docs/요구사항/img/a.png").write_bytes(b"x")
  (tmp_path / "docs/요구사항/지난판/RTM_v1.11.md").write_text("x", encoding="utf-8")
  body = HEAD + (
    "[설계](../설계/기능설계.md) · [대장](대장/요구-대장.tsv) · [v1.11](지난판/RTM_v1.11.md)\r\n"
    "![그림](img/a.png) · [절](#2-요구) · [이 문서 부록](RTM.md#부록) · [밖](https://example.com/a.md)\r\n"
    "[깨진 예시](없는파일.md) · [대장 폴더](대장/) · [바로가기]\r\n\r\n[바로가기]: ../설계/기능설계.md\r\n")
  p = tmp_path / "docs/요구사항/RTM.md"
  p.write_bytes(body.encode("utf-8"))
  return p


def test_dv01_bump_copies_with_links_moved_one_level_down(tmp_path):
  """TC-DV-01 · 사본 = 지난판/<이름>_v<머리표 판>.md · 상대 링크는 새 자리에 맞춤 · 주소 · 문서 안 · 깨진 링크는 그대로 · 원본 · 줄 끝 그대로."""
  src = _tree(tmp_path)
  before = src.read_bytes()
  dst = docs_scan.bump(src, root=tmp_path)
  assert dst == tmp_path / "docs/요구사항/지난판/RTM_v1.12.md"
  t = dst.read_bytes().decode("utf-8")
  assert "[설계](../../설계/기능설계.md)" in t
  assert "[대장](../대장/요구-대장.tsv)" in t and "[대장 폴더](../대장/)" in t
  assert "[v1.11](RTM_v1.11.md)" in t                       # 지난판끼리는 같은 폴더
  assert "![그림](../img/a.png)" in t
  assert "[절](#2-요구)" in t and "(https://example.com/a.md)" in t
  assert "[이 문서 부록](RTM_v1.12.md#부록)" in t            # 자기 자신 링크는 사본 자신으로
  assert "[깨진 예시](없는파일.md)" in t                     # 원래 없던 대상은 글자 그대로
  assert "[바로가기]: ../../설계/기능설계.md" in t            # 참조식 링크 정의도
  assert t.count("\r\n") == before.decode("utf-8").count("\r\n")
  assert src.read_bytes() == before                          # 원본은 고치지 않는다


def test_dv02_bump_refuses_four_cases(tmp_path):
  """TC-DV-02 · 멈추는 경우 넷 — 사본이 이미 있음 · 판 붙은 이름 · 머리표에 판 없음 · 종류 폴더 맨 위가 아님."""
  src = _tree(tmp_path)
  docs_scan.bump(src, root=tmp_path)
  with pytest.raises(SystemExit, match="이미 있다"):
    docs_scan.bump(src, root=tmp_path)
  named = tmp_path / "docs/요구사항/RTM_v1.12.md"
  named.write_text(HEAD, encoding="utf-8")
  with pytest.raises(SystemExit, match="판 붙은 이름"):
    docs_scan.bump(named, root=tmp_path)
  plain = tmp_path / "docs/요구사항/메모.md"
  plain.write_text("# 메모\n본문의 v1.2 는 판이 아니다\n", encoding="utf-8")
  with pytest.raises(SystemExit, match="판\\(vX.Y\\)"):
    docs_scan.bump(plain, root=tmp_path)
  deep = tmp_path / "docs/요구사항/대장/설명.md"
  deep.write_text(HEAD, encoding="utf-8")
  with pytest.raises(SystemExit, match="종류 폴더 맨 위"):
    docs_scan.bump(deep, root=tmp_path)


def test_dv03_head_version_reads_three_header_styles():
  """TC-DV-03 · 판 읽기 — 「판 · 상태」 칸 · API 명세서처럼 버전이라고 쓴 칸 · 없으면 첫 제목 · 본문의 vX.Y 는 판이 아니다."""
  assert docs_scan.head_version("| **판 · 상태** | v1.15 · 초안(검토 전) |") == "1.15"
  assert docs_scan.head_version("| **문서 버전** | v0.11 (Patch — 응답 칸 둘) |") == "0.11"
  assert docs_scan.head_version("# 문서 그림 지침 v0.4 — 그림\n") == "0.4"
  assert docs_scan.head_version("# 메모\n본문의 v1.2 는 판이 아니다\n") is None


def test_dv04_check_finds_top_versioned_and_orphan_copies(tmp_path):
  """TC-DV-04 · 검사 — 깨끗한 폴더는 통과 · 맨 위의 판 붙은 문서와 짝 없는 지난판 사본을 하나씩 잡는다."""
  _tree(tmp_path)
  (tmp_path / "docs/요구사항/지난판/RTM_v1.11.md").unlink()
  docs_scan.bump(tmp_path / "docs/요구사항/RTM.md", root=tmp_path)
  assert docs_scan.check(root=tmp_path) == []
  (tmp_path / "docs/요구사항/RTM_v1.13.md").write_text(HEAD, encoding="utf-8")
  (tmp_path / "docs/설계/지난판").mkdir()
  (tmp_path / "docs/설계/지난판/동작원리_v0.1.md").write_text("x", encoding="utf-8")
  got = docs_scan.check(root=tmp_path)
  assert len(got) == 2
  assert any("맨 위에 판 붙은 문서" in g and "RTM_v1.13.md" in g for g in got)
  assert any("짝 없는 지난판 사본" in g and "동작원리_v0.1.md" in g for g in got)
