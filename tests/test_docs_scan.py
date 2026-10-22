"""docs 판 도구 시험 (TC-DV) — 지난판 사본의 링크 · 이름 · 판 규칙 (2026-10-07 docs 정리 · 2026-10-21 차수 폴더 · 2026-10-22 번호 폴더).

판을 올릴 때 지금 파일을 지난판/ 에 그냥 복사하면 한 칸 아래 폴더라 상대 링크가 모두 어긋난다.
`--bump` 가 링크를 새 자리에 맞춰 사본을 만드는지, `--check` 가 맨 위의 판 붙은 문서 · 짝 없는 사본 ·
옛 자리(번호 폴더 전 `docs/2차` · `docs/3차` · 차수 폴더 전 `docs/<종류>/` · 맨 위 기록)에 남은 문서를 잡는지 본다.
네트워크 · git · DB 를 쓰지 않는다(임시 폴더). 실제 docs 를 시험으로 막지는 않는다 — 팀원 PR 이 옛 습관(판 붙은 새 파일)으로
실패하지 않게, 실제 폴더는 `--check` 와 점검으로 본다.
"""

import pytest

from scripts import docs_scan

HEAD = "# 요구사항 추적표(RTM) v1.12 — Qurious\r\n\r\n| 문서 정보 | |\r\n|---|---|\r\n| **판 · 상태** | v1.12 · 초안 |\r\n"
REQ = "docs/phase-3/01-analysis/requirements"
SYS3 = "docs/phase-3/02-design/system"


def _tree(tmp_path):
  (tmp_path / f"{REQ}/지난판").mkdir(parents=True)
  (tmp_path / f"{REQ}/대장").mkdir()
  (tmp_path / f"{REQ}/img").mkdir()
  (tmp_path / SYS3).mkdir(parents=True)
  (tmp_path / f"{SYS3}/기능설계.md").write_text("x", encoding="utf-8")
  (tmp_path / f"{REQ}/대장/요구-대장.tsv").write_text("x", encoding="utf-8")
  (tmp_path / f"{REQ}/img/a.png").write_bytes(b"x")
  (tmp_path / f"{REQ}/지난판/RTM_v1.11.md").write_text("x", encoding="utf-8")
  body = HEAD + (
    "[설계](../../02-design/system/기능설계.md) · [대장](대장/요구-대장.tsv) · [v1.11](지난판/RTM_v1.11.md)\r\n"
    "![그림](img/a.png) · [절](#2-요구) · [이 문서 부록](RTM.md#부록) · [밖](https://example.com/a.md)\r\n"
    "[깨진 예시](없는파일.md) · [대장 폴더](대장/) · [바로가기]\r\n\r\n[바로가기]: ../../02-design/system/기능설계.md\r\n")
  p = tmp_path / f"{REQ}/RTM.md"
  p.write_bytes(body.encode("utf-8"))
  return p


def test_dv01_bump_copies_with_links_moved_one_level_down(tmp_path):
  """TC-DV-01 · 사본 = 지난판/<이름>_v<머리표 판>.md · 상대 링크는 새 자리에 맞춤 · 주소 · 문서 안 · 깨진 링크는 그대로 · 원본 · 줄 끝 그대로."""
  src = _tree(tmp_path)
  before = src.read_bytes()
  dst = docs_scan.bump(src, root=tmp_path)
  assert dst == tmp_path / f"{REQ}/지난판/RTM_v1.12.md"
  t = dst.read_bytes().decode("utf-8")
  assert "[설계](../../../02-design/system/기능설계.md)" in t
  assert "[대장](../대장/요구-대장.tsv)" in t and "[대장 폴더](../대장/)" in t
  assert "[v1.11](RTM_v1.11.md)" in t                       # 지난판끼리는 같은 폴더
  assert "![그림](../img/a.png)" in t
  assert "[절](#2-요구)" in t and "(https://example.com/a.md)" in t
  assert "[이 문서 부록](RTM_v1.12.md#부록)" in t            # 자기 자신 링크는 사본 자신으로
  assert "[깨진 예시](없는파일.md)" in t                     # 원래 없던 대상은 글자 그대로
  assert "[바로가기]: ../../../02-design/system/기능설계.md" in t   # 참조식 링크 정의도
  assert t.count("\r\n") == before.decode("utf-8").count("\r\n")
  assert src.read_bytes() == before                          # 원본은 고치지 않는다


def test_dv02_bump_refuses_five_cases(tmp_path):
  """TC-DV-02 · 멈추는 경우 다섯 — 사본이 이미 있음 · 판 붙은 이름 · 머리표에 판 없음 · 종류 폴더 맨 위가 아님 · 번호 폴더 전 옛 자리."""
  src = _tree(tmp_path)
  docs_scan.bump(src, root=tmp_path)
  with pytest.raises(SystemExit, match="이미 있다"):
    docs_scan.bump(src, root=tmp_path)
  named = tmp_path / f"{REQ}/RTM_v1.12.md"
  named.write_text(HEAD, encoding="utf-8")
  with pytest.raises(SystemExit, match="판 붙은 이름"):
    docs_scan.bump(named, root=tmp_path)
  plain = tmp_path / f"{REQ}/메모.md"
  plain.write_text("# 메모\n본문의 v1.2 는 판이 아니다\n", encoding="utf-8")
  with pytest.raises(SystemExit, match="판\\(vX.Y\\)"):
    docs_scan.bump(plain, root=tmp_path)
  deep = tmp_path / f"{REQ}/대장/설명.md"
  deep.write_text(HEAD, encoding="utf-8")
  with pytest.raises(SystemExit, match="종류 폴더 맨 위"):
    docs_scan.bump(deep, root=tmp_path)
  (tmp_path / "docs/요구사항").mkdir()
  flat = tmp_path / "docs/요구사항/RTM.md"
  flat.write_text(HEAD, encoding="utf-8")
  with pytest.raises(SystemExit, match="번호 폴더다"):           # 옛 자리는 새 자리를 알려 주며 멈춘다
    docs_scan.bump(flat, root=tmp_path)


def test_dv03_head_version_reads_three_header_styles():
  """TC-DV-03 · 판 읽기 — 「판 · 상태」 칸 · API 명세서처럼 버전이라고 쓴 칸 · 없으면 첫 제목 · 본문의 vX.Y 는 판이 아니다."""
  assert docs_scan.head_version("| **판 · 상태** | v1.15 · 초안(검토 전) |") == "1.15"
  assert docs_scan.head_version("| **문서 버전** | v0.11 (Patch — 응답 칸 둘) |") == "0.11"
  assert docs_scan.head_version("# 문서 그림 지침 v0.4 — 그림\n") == "0.4"
  assert docs_scan.head_version("# 메모\n본문의 v1.2 는 판이 아니다\n") is None
  assert docs_scan.head_version("| 머리표 | 내용 |\n|---|---|\n| 판 | v0.2 (2026-10-18 · 새 메뉴) |\n") == "0.2"   # 굵지 않은 칸(영상 README)
  assert docs_scan.head_version("| 판 | 날짜 | 바뀐 것 |\n| v0.2 | 2026-10-18 | x |\n") is None             # 개정 이력 머리는 판이 아니다


def test_dv04_check_finds_top_versioned_and_orphan_copies(tmp_path):
  """TC-DV-04 · 검사 — 깨끗한 폴더는 통과 · 맨 위의 판 붙은 문서와 짝 없는 지난판 사본을 하나씩 잡는다(차수 폴더마다)."""
  _tree(tmp_path)
  (tmp_path / f"{REQ}/지난판/RTM_v1.11.md").unlink()
  docs_scan.bump(tmp_path / f"{REQ}/RTM.md", root=tmp_path)
  assert docs_scan.check(root=tmp_path) == []
  (tmp_path / f"{REQ}/RTM_v1.13.md").write_text(HEAD, encoding="utf-8")
  (tmp_path / "docs/phase-2/02-design/system/지난판").mkdir(parents=True)
  (tmp_path / "docs/phase-2/02-design/system/지난판/동작원리_v0.1.md").write_text("x", encoding="utf-8")
  got = docs_scan.check(root=tmp_path)
  assert len(got) == 2
  assert any("맨 위에 판 붙은 문서" in g and "RTM_v1.13.md" in g for g in got)
  assert any("짝 없는 지난판 사본" in g and "docs/phase-2/02-design/system/지난판/동작원리_v0.1.md" in g for g in got)


DECK = ('<!--\n  2차 발표 자료 v0.1 (2026-10-17 초안) — 틀\n-->\n<!doctype html><html><head><title>t</title></head><body>\n'
        '<video controls poster="../../common/06-retrospective/videos/파일/발표/P-V07.jpg" '
        'src="../../common/06-retrospective/videos/파일/발표/P-V07.mp4"></video>\n'
        '<img src="img/a.png"> <a href="#s3">셋째 장</a> <a href="https://example.com/x.html">밖</a>\n'
        '<video src="media/없는.webm"></video> <p>본문의 v9.9 는 판이 아니다</p>\n</body></html>\n')
VIDEOS = "docs/common/06-retrospective/videos"
DECK_DIR = "docs/phase-2/06-retrospective"


def _deck_tree(tmp_path):
  (tmp_path / f"{VIDEOS}/파일/발표").mkdir(parents=True)
  (tmp_path / f"{DECK_DIR}/img").mkdir(parents=True)
  for f in ("P-V07.mp4", "P-V07.jpg"):
    (tmp_path / f"{VIDEOS}/파일/발표" / f).write_bytes(b"x")
  (tmp_path / f"{DECK_DIR}/img/a.png").write_bytes(b"x")
  p = tmp_path / f"{DECK_DIR}/발표자료.html"
  p.write_bytes(DECK.replace("\n", "\r\n").encode("utf-8"))
  return p


def test_dv05_bump_presentation_html_moves_media_links(tmp_path):
  """TC-DV-05 · 발표 자료(docs/<차수>/06-retrospective/<이름>.html) — 사본 = 그 폴더의 지난판/<이름>_v<판>.html · 영상(src · poster) ·
  그림 · 링크는 새 자리에 맞춤(사본에서도 재생) · 문서 안 · 주소 · 없는 파일은 그대로 · 줄 끝 그대로(2026-10-19 사용자 「발표 자료가 판 관리로 갱신이 안 됐다」)."""
  src = _deck_tree(tmp_path)
  before = src.read_bytes()
  dst = docs_scan.bump(src, root=tmp_path)
  assert dst == tmp_path / f"{DECK_DIR}/지난판/발표자료_v0.1.html"
  out = dst.read_bytes().decode("utf-8")
  assert ('poster="../../../common/06-retrospective/videos/파일/발표/P-V07.jpg" '
          'src="../../../common/06-retrospective/videos/파일/발표/P-V07.mp4"') in out
  assert '<img src="../img/a.png">' in out and 'href="#s3"' in out and 'href="https://example.com/x.html"' in out
  assert 'src="media/없는.webm"' in out                                   # 원래 없던 파일은 고치지 않는다
  assert out.count("\r\n") == before.decode("utf-8").count("\r\n") and src.read_bytes() == before


def test_dv06_html_version_meta_first_then_first_comment():
  """TC-DV-06 · HTML 판 읽기 — <meta name="doc-version"> 가 먼저 · 없으면 첫 주석의 vX.Y · 본문 · 뒤 주석의 vX.Y 는 판이 아니다."""
  assert docs_scan.head_version(DECK, html=True) == "0.1"
  meta = '<!-- 2차 발표 자료 v0.1 -->\n<head><meta name="doc-version" content="0.2"></head>'
  assert docs_scan.head_version(meta, html=True) == "0.2"
  assert docs_scan.head_version("<html><p>v1.2</p><!-- 나중 주석 v3.4 --></html>", html=True) is None


def test_dv07_check_covers_presentation_and_top_assets(tmp_path):
  """TC-DV-07 · 검사가 차수 폴더의 발표(docs/<차수>/06-retrospective/) · 차수 밖 자산(docs/common/06-retrospective/videos/)도 본다
  — md · html 의 맨 위 판 붙은 이름 · 짝 없는 지난판 사본."""
  src = _deck_tree(tmp_path)
  docs_scan.bump(src, root=tmp_path)
  assert docs_scan.check(root=tmp_path) == []
  (tmp_path / f"{DECK_DIR}/발표자료_v0.3.html").write_text(DECK, encoding="utf-8")
  (tmp_path / f"{VIDEOS}/지난판").mkdir()
  (tmp_path / f"{VIDEOS}/지난판/README_v0.1.md").write_text("x", encoding="utf-8")
  got = docs_scan.check(root=tmp_path)
  assert len(got) == 2
  assert any("맨 위에 판 붙은 문서" in g and "발표자료_v0.3.html" in g for g in got)
  assert any("짝 없는 지난판 사본" in g and "README_v0.1.md" in g for g in got)
  (tmp_path / f"{VIDEOS}/README.md").write_text("# 영상 v0.2\n", encoding="utf-8")
  assert len(docs_scan.check(root=tmp_path)) == 1                        # 짝이 생기면 사본은 통과


def test_dv08_check_finds_docs_left_at_flat_place(tmp_path):
  """TC-DV-08 · 번호 폴더(2026-10-22) 뒤 옛 자리 — 차수 폴더 전 `docs/<종류>/` · `docs/발표/` · 번호 폴더 전 `docs/2차` · `docs/3차` ·
  맨 위 기록(`docs/영상` 등)에 문서가 남으면 잡는다 — 옛 습관으로 만든 새 문서 · 옮기다 빠진 문서. 그림 · 표(문서 아님)만 남은 폴더는
  문서 검사가 아니다(다른 PC 의 무시된 양식 docx 같은 것)."""
  _tree(tmp_path)
  assert docs_scan.check(root=tmp_path) == []
  (tmp_path / "docs/계획서").mkdir()
  (tmp_path / "docs/계획서/양식.docx").write_bytes(b"x")                  # 문서 검사 밖
  assert docs_scan.check(root=tmp_path) == []
  (tmp_path / "docs/시험").mkdir()
  (tmp_path / "docs/시험/새문서.md").write_text("# 새 v0.1\n", encoding="utf-8")
  (tmp_path / "docs/발표/3차").mkdir(parents=True)
  (tmp_path / "docs/발표/3차/발표자료.html").write_text("<!-- v0.1 -->", encoding="utf-8")
  (tmp_path / "docs/3차/시험").mkdir(parents=True)
  (tmp_path / "docs/3차/시험/테스트계획서.md").write_text("# 계획 v1.0\n", encoding="utf-8")
  (tmp_path / "docs/영상").mkdir()
  (tmp_path / "docs/영상/README.md").write_text("# 영상 v0.2\n", encoding="utf-8")
  got = docs_scan.check(root=tmp_path)
  assert len(got) == 4 and all("옛 자리에 문서가 남아 있다" in g for g in got)
  for p in ("docs/시험/새문서.md", "docs/발표/3차/발표자료.html", "docs/3차/시험/테스트계획서.md", "docs/영상/README.md"):
    assert any(p in g for g in got)


def test_dv09_to3_copies_2nd_only_doc_pointing_to_3rd_copies(tmp_path):
  """TC-DV-09 · --to3 — 2차에만 있는 문서(조사서 · 완료보고서)를 3차에 고치기 전에 3차로 사본 · 링크는 새 자리에 맞추고
  3차 사본이 있는 대상은 3차로 · 없는 대상은 2차 그대로 · 원본 · 줄 끝 그대로 · 이미 있음 · 2차 밖은 멈춤(2026-10-21 사용자 결정 ⓒ)."""
  for d in ("docs/phase-2/01-analysis/research/img", "docs/phase-2/02-design/system", SYS3):
    (tmp_path / d).mkdir(parents=True)
  for f in ("docs/phase-2/02-design/system/기능설계.md", f"{SYS3}/기능설계.md", "docs/phase-2/02-design/system/옛설계.md"):
    (tmp_path / f).write_text("x", encoding="utf-8")
  (tmp_path / "docs/phase-2/01-analysis/research/img/a.png").write_bytes(b"x")
  body = ("# 조사 v0.1\r\n[설계](../../02-design/system/기능설계.md) · [옛](../../02-design/system/옛설계.md) · "
          "![그림](img/a.png) · [깨진](없음.md) · [절](#1)\r\n")
  src = tmp_path / "docs/phase-2/01-analysis/research/x-조사.md"
  src.write_bytes(body.encode("utf-8"))
  dst = docs_scan.to3(src, root=tmp_path)
  assert dst == tmp_path / "docs/phase-3/01-analysis/research/x-조사.md"
  t = dst.read_bytes().decode("utf-8")
  assert "[설계](../../02-design/system/기능설계.md)" in t      # 3차 사본이 있는 대상은 3차(2차면 ../../../phase-2/… 가 된다)
  assert "[옛](../../../phase-2/02-design/system/옛설계.md)" in t  # 3차 사본이 없으면 2차 그대로
  assert "![그림](../../../phase-2/01-analysis/research/img/a.png)" in t and "[깨진](없음.md)" in t and "[절](#1)" in t
  assert t.count("\r\n") == 2 and src.read_bytes() == body.encode("utf-8")
  with pytest.raises(SystemExit, match="이미 있다"):
    docs_scan.to3(src, root=tmp_path)
  with pytest.raises(SystemExit, match="2차 종류 폴더 맨 위"):
    docs_scan.to3(tmp_path / f"{SYS3}/기능설계.md", root=tmp_path)


def test_dv10_number_folders_kind_depth_one_or_two(tmp_path):
  """TC-DV-10 · 번호 폴더(2026-10-22 강사님 피드백 · 사용자 결정 S134) — 종류는 번호 폴더 기준 한 칸(04-testing · 05-deployment) 또는
  두 칸(02-design/ui)이다. 한 칸 종류의 문서도 판을 올리고, 여러 종류를 묶은 번호 폴더 바로 아래 · 목록에 없는 종류 · 옛 차수 이름은 멈춘다."""
  plan = tmp_path / "docs/phase-3/04-testing/테스트계획서.md"
  plan.parent.mkdir(parents=True)
  plan.write_text("# 테스트 계획서 v1.52\n\n| **판 · 상태** | v1.52 · 초안 |\n", encoding="utf-8")
  assert docs_scan.bump(plan, root=tmp_path) == tmp_path / "docs/phase-3/04-testing/지난판/테스트계획서_v1.52.md"   # 대조군 — 한 칸 종류
  ui = tmp_path / "docs/phase-3/02-design/ui/IA.md"
  ui.parent.mkdir(parents=True)
  ui.write_text("# IA v1.8\n", encoding="utf-8")
  assert docs_scan.bump(ui, root=tmp_path) == tmp_path / "docs/phase-3/02-design/ui/지난판/IA_v1.8.md"             # 대조군 — 두 칸 종류
  group = tmp_path / "docs/phase-3/02-design/메모.md"                       # 묶음 폴더 바로 아래 — 종류가 아니다
  group.write_text("# 메모 v0.1\n", encoding="utf-8")
  with pytest.raises(SystemExit, match="종류 폴더 맨 위"):
    docs_scan.bump(group, root=tmp_path)
  odd = tmp_path / "docs/phase-3/02-design/없는종류/x.md"
  odd.parent.mkdir(parents=True)
  odd.write_text("# x v0.1\n", encoding="utf-8")
  with pytest.raises(SystemExit, match="종류 폴더 맨 위"):
    docs_scan.bump(odd, root=tmp_path)
  old = tmp_path / "docs/3차/시험/테스트계획서.md"                          # 번호 폴더 전 차수 이름
  old.parent.mkdir(parents=True)
  old.write_text("# 테스트 계획서 v1.52\n", encoding="utf-8")
  with pytest.raises(SystemExit, match="번호 폴더다"):
    docs_scan.bump(old, root=tmp_path)
