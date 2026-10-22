"""docs 문서 판 도구 — 지난판 사본 만들기 · 이름 · 판 규칙 검사 (2026-10-07 docs 정리 · 2026-10-21 차수 폴더 · 2026-10-22 번호 폴더).

docs 는 차수 폴더로 나뉜다(2026-10-21 · docs/README.md 2절) — `docs/phase-2/` 는 2차를 닫은 판(얼림),
`docs/phase-3/` 는 3차에도 고치는 살아 있는 문서의 사본이다. 2026-10-22 부터 차수 폴더 안은 업무 순서 번호 폴더
(00-management · 01-analysis · 02-design · 03-development · 04-testing · 05-deployment · 06-retrospective)이고,
여러 종류를 묶은 번호 폴더 안에는 종류 폴더(02-design/ui · 01-analysis/requirements …)를 하나 더 둔다(강사님 피드백 ·
사용자 결정 S134). 차수 밖 기록은 `docs/common/<번호>-<묶음>/` 이다. 종류 폴더 맨 위에는 문서마다 **판 번호 없는 이름
하나**만 두고, 지난 판은 같은 폴더의 `지난판/<이름>_v<판>.md` 사본으로 남긴다(docs/README.md 3절). 판을 올릴 때 지금
파일을 지난판/ 에 그냥 복사하면 한 칸 아래 폴더라 사본 속 상대 링크가 모두 한 단계 어긋난다. 이 도구는 링크를 옛
자리 기준으로 풀어 새 자리 기준으로 다시 써서 사본을 만든다. 네트워크 · git 을 쓰지 않는다.

    python scripts/docs_scan.py --bump docs/phase-3/04-testing/테스트계획서.md   지금 판(머리표)을 지난판/ 에 사본으로 — 그다음 원본을 고친다
    python scripts/docs_scan.py --check                                  맨 위의 판 붙은 문서 · 짝 없는 지난판 사본 · 옛 자리에 남은 문서 (있으면 종료코드 1)
    python scripts/docs_scan.py --to3 docs/phase-2/01-analysis/research/섹터별-근거법령-조사.md  2차에만 있는 문서를 3차에 고치기 전에 3차로 사본(한 번)

판 올리는 순서: ① --bump ② 원본(판 없는 이름)을 고치고 머리표의 판 · 최종 수정 · 개정 이력 ③ 산출물목록 0.1절 판 칸.
다른 문서의 링크는 고치지 않아도 된다 — 최신을 가리키는 이름이 그대로라서.

받는 자리 셋:
  docs/<차수>/<번호>-<묶음>[/<종류>]/<이름>.md   종류 12(KIND_DIRS — 04 · 05 는 번호 폴더가 곧 종류)
  docs/<차수>/06-retrospective/<이름>.md|html     발표 자료(2026-10-19 사용자 「발표 자료가 버전 관리로 갱신이 안됐다」) — HTML 은
                                        `<meta name="doc-version" content="0.2">`(없으면 첫 주석의 vX.Y)에서 판을 읽고,
                                        사본 속 src · href · poster 상대 경로도 새 자리에 맞춘다(영상 · 그림이 사본에서도 재생 · 표시되게)
  docs/<맨 위 자산>/<이름>.md           차수 밖 자산(TOP_DIRS — 앱 사용법 창 · 녹화 도구가 3차에도 쓰는 영상 폴더)

3차로 사본(--to3): 3차 사본은 2026-10-21 에 살아 있는 문서 · 대장 · 평가셋만 만들었다(사용자 결정 ⓒ). 조사서 · 완료보고서처럼
2차에만 있는 문서를 3차에 고칠 때는 고치기 전에 한 번 3차로 사본을 만든다 — 링크는 새 자리에 맞추고, 가리키던 2차 문서에
3차 사본이 있으면 3차를 가리키게 한다(2차 원본은 그대로 얼림).
"""

from __future__ import annotations

import argparse
import posixpath
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: 차수 폴더 안 종류 — 업무 순서 번호 폴더 기준 경로(2026-10-22 번호 폴더 · 옛 이름은 OLD_KIND_DIRS)
KIND_DIRS = ("00-management/plans", "00-management/standards", "01-analysis/requirements", "01-analysis/research",
             "02-design/system", "02-design/data", "02-design/ui", "02-design/api",
             "03-development/conventions", "03-development/data-collection", "04-testing", "05-deployment")
#: 차수 폴더 안의 발표 자료 — docs/<차수>/06-retrospective/<이름>.md|html (2026-10-19 · 차수 폴더 2026-10-21 · 번호 2026-10-22)
PRESENT_DIR = "06-retrospective"
#: 차수 폴더 이름 — docs/phase-2 · docs/phase-3 …(2026-10-21 사용자 결정 안 C · 2차 얼림 + 3차 사본 · 영어 이름 2026-10-22)
PHASE = re.compile(r"^phase-\d+$")
#: 차수 밖 자산 폴더(docs 기준) — 3차에 다시 찍어도 얼린 2차를 고치지 않게(2026-10-21 · 자리 2026-10-22)
TOP_DIRS = ("common/06-retrospective/videos",)
#: 옛 자리 — 이 이름의 docs 바로 아래 폴더에는 문서가 남아 있으면 안 된다(docs/README.md 7절 옛 자리 → 새 자리)
OLD_PHASES = ("2차", "3차")
OLD_KIND_DIRS = ("계획서", "요구사항", "설계", "데이터", "인터페이스", "화면", "시험", "조사", "배포", "개발", "문서기준", "데이터수집",
                 "발표")
OLD_TOP = ("영상", "TIL", "회의", "ADR", "img", "contracts", "github-archive")
DOC_SUFFIXES = (".md", ".html")
OLD_DIR = "지난판"
#: 판 붙은 이름 — `테스트계획서_v1.15` · `섹터법령-평가셋_v1`
VER_NAME = re.compile(r"^(?P<base>.+?)[_-]v(?P<ver>\d+(?:\.\d+)*)(?P<rest>.*)$")
#: 머리표의 판 칸 — 산출물은 `판 · 상태`, API 명세서처럼 버전이라고 쓴 칸도 읽는다. 없으면 첫 제목의 vX.Y.
#: 굵지 않은 「| 판 | v0.2 …」(영상 README 꼴)도 읽는다(2026-10-19).
HEAD_VERSION = re.compile(r"^\|\s*(?:\*\*)?(?:판[^*|]*|문서 ?버전)(?:\*\*)?\s*\|\s*v(\d+(?:\.\d+)*)", re.M)
TITLE_VERSION = re.compile(r"^#\s[^\n]*?\bv(\d+(?:\.\d+)+)", re.M)
LINK = re.compile(r"(!?\[[^\]\n]*\]\()(<[^>\n]+>|[^)\s\n]+)")
REFDEF = re.compile(r"^(\s{0,3}\[[^\]\n]+\]:[ \t]*)(\S+)", re.M)
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z+.-]*:")
#: HTML 문서의 판 — 기계가 읽는 meta 가 먼저, 없으면 첫 주석 안의 vX.Y(옛 발표 자료 v0.1 꼴)
HTML_META_VERSION = re.compile(r'<meta\s+name="doc-version"\s+content="v?(\d+(?:\.\d+)*)"')
HTML_COMMENT_VERSION = re.compile(r"<!--(?:(?!-->).)*?\bv(\d+(?:\.\d+)+)", re.S)
#: HTML 속 상대 경로를 가진 속성 — 영상(src · poster) · 그림 · 링크
HTML_ATTR = re.compile(r'(\b(?:src|href|poster)=")([^"]+)(")')
WHERE = ("docs/<차수>/<번호>-<묶음>[/<종류>]/<이름>.md · docs/<차수>/06-retrospective/<이름>.md|html · "
         + " · ".join(f"docs/{d}/<이름>.md" for d in TOP_DIRS))


def head_version(text: str, html: bool = False) -> str | None:
  """머리표의 판(`1.15`). 머리표에 없으면 첫 제목(`# … v0.4 — …`)에서. HTML 은 meta → 첫 주석. 없으면 None."""
  if html:
    m = HTML_META_VERSION.search(text)
    if not m:                                   # 머리(</head> · <body 앞)의 주석만 — 본문 · 뒤쪽 주석의 vX.Y 는 판이 아니다
      low = text.lower()
      cut = min((i for i in (low.find("</head>"), low.find("<body")) if i >= 0), default=0)
      m = HTML_COMMENT_VERSION.search(text[:cut])
    return m.group(1) if m else None
  m = HEAD_VERSION.search(text) or TITLE_VERSION.search(text)
  return m.group(1) if m else None


def _rel(target: str, start_dir: str) -> str:
  """저장소 안 두 경로(슬래시) 사이의 상대 경로 — 작업 폴더와 상관없이 글자로만 계산한다."""
  t = target.split("/") if target else []
  s = start_dir.split("/") if start_dir else []
  i = 0
  while i < len(t) and i < len(s) and t[i] == s[i]:
    i += 1
  return "/".join([".."] * (len(s) - i) + t[i:]) or "."


def relink(text: str, src: str, dst: str, exists, html: bool = False, remap=None) -> str:
  """`src` 자리 기준 상대 링크를 `dst` 자리 기준으로 다시 쓴다(경로는 저장소 기준 · 슬래시).

  대상이 원래 없던 링크(깨진 링크 · 예시 글) · 주소 · 문서 안(`#…`) 링크는 그대로 둔다.
  자기 자신을 가리키던 링크(`RTM.md#부록`)는 사본 자신으로 — 사본의 절은 사본 안에 있다.
  HTML 은 마크다운 링크 대신 src · href · poster 속성을 고친다.
  `remap`(있으면)은 있는 대상을 다른 대상으로 바꾼다 — --to3 이 2차 문서 대신 그 3차 사본을 가리키게 할 때.
  """
  def one(raw: str) -> str:
    angle = raw.startswith("<") and raw.endswith(">")
    t = raw[1:-1] if angle else raw
    if SCHEME.match(t) or t.startswith(("#", "/")):
      return raw
    m = re.match(r"^([^#?]*)(.*)$", t, re.S)
    path, tail = m.group(1), m.group(2)
    if not path:
      return raw
    dec = urllib.parse.unquote(path)
    tgt = posixpath.normpath(posixpath.join(posixpath.dirname(src), dec))
    if tgt == src:
      tgt = dst
    elif tgt.startswith("..") or not exists(tgt):
      return raw
    elif remap:
      tgt = remap(tgt)
    new = _rel(tgt, posixpath.dirname(dst))
    if dec.endswith("/") and not new.endswith("/"):
      new += "/"
    if "%" in path:
      new = urllib.parse.quote(new, safe="/._-~()!*'")
    out = new + tail
    return f"<{out}>" if angle else out

  if html:
    return HTML_ATTR.sub(lambda m: m.group(1) + one(m.group(2)) + m.group(3), text)
  text = LINK.sub(lambda m: m.group(1) + one(m.group(2)), text)
  return REFDEF.sub(lambda m: m.group(1) + one(m.group(2)), text)


def doc_place(parts: list[str], suffix: str) -> str | None:
  """판을 올릴 수 있는 자리면 그 갈래(`차수` · `맨 위`), 아니면 None. parts 는 저장소 기준 경로 조각.

  종류는 번호 폴더 기준 경로 한두 칸이다(`04-testing` · `02-design/ui`) — 차수와 파일 이름 사이를 이어 붙여 견준다.
  """
  if len(parts) >= 4 and parts[0] == "docs" and PHASE.match(parts[1]):
    kind = "/".join(parts[2:-1])
    if kind in KIND_DIRS and suffix == ".md":
      return "차수"
    if kind == PRESENT_DIR and suffix in DOC_SUFFIXES:
      return "차수"
  if len(parts) >= 3 and parts[0] == "docs" and "/".join(parts[1:-1]) in TOP_DIRS and suffix == ".md":
    return "맨 위"
  return None


def bump(path: Path, root: Path = ROOT) -> Path:
  """지금 판을 `지난판/<이름>_v<판>.<확장자>` 사본으로 만든다(링크를 새 자리에 맞춤 · 줄 끝 그대로). 원본은 고치지 않는다."""
  root = root.resolve()
  src = path if path.is_absolute() else root / path
  try:
    rel_src = src.resolve().relative_to(root).as_posix()
  except ValueError:
    raise SystemExit(f"멈춤 — 저장소 밖의 파일이다: {path}")
  parts = rel_src.split("/")
  suffix = posixpath.splitext(rel_src)[1]
  if not doc_place(parts, suffix):
    if len(parts) >= 3 and parts[0] == "docs" and parts[1] in OLD_PHASES + OLD_KIND_DIRS + OLD_TOP:
      raise SystemExit("멈춤 — 2026-10-22 부터 docs 는 번호 폴더다: 3차에 고치는 문서는 "
                       "docs/phase-3/<번호>-<묶음>[/<종류>]/<이름>.md "
                       f"(받은 것: {rel_src} · 옛 자리 → 새 자리는 docs/README.md 7절)")
    raise SystemExit(f"멈춤 — 종류 폴더 맨 위의 문서만 된다: {WHERE} (받은 것: {rel_src})")
  stem = parts[-1][:-len(suffix)]
  if VER_NAME.match(stem):
    raise SystemExit(f"멈춤 — 판 붙은 이름이다: {rel_src} → 맨 위에는 판 없는 이름만 둔다(docs/README.md 3절)")
  html = suffix == ".html"
  text = src.read_bytes().decode("utf-8")
  ver = head_version(text, html=html)
  if not ver:
    where = ('<meta name="doc-version" content="0.2"> 를 머리에' if html
             else "「판 · 상태」 칸이나 첫 제목에 판을 적는다")
    raise SystemExit(f"멈춤 — 판(vX.Y)을 찾지 못했다: {rel_src} — {where}")
  dst_rel = "/".join(parts[:-1] + [OLD_DIR, f"{stem}_v{ver}{suffix}"])
  dst = root / dst_rel
  if dst.exists():
    raise SystemExit(f"멈춤 — 이미 있다: {dst_rel} — 이 판은 이미 지난판에 있다(머리표 판을 먼저 올렸나?)")
  new = relink(text, rel_src, dst_rel, lambda p: (root / p).exists(), html=html)
  dst.parent.mkdir(parents=True, exist_ok=True)
  dst.write_bytes(new.encode("utf-8"))
  return dst


def to3(path: Path, root: Path = ROOT) -> Path:
  """2차에만 있는 문서를 3차로 사본 — docs/phase-2/<번호>-<묶음>[/<종류>]/<이름>.md|html → docs/phase-3/… (링크를 새 자리에 맞춤 · 줄 끝 그대로).

  가리키던 2차 문서 · 폴더에 3차 사본이 있으면 3차를 가리키게 바꾼다(없으면 2차 그대로). 원본은 고치지 않는다.
  """
  root = root.resolve()
  src = path if path.is_absolute() else root / path
  try:
    rel_src = src.resolve().relative_to(root).as_posix()
  except ValueError:
    raise SystemExit(f"멈춤 — 저장소 밖의 파일이다: {path}")
  parts = rel_src.split("/")
  suffix = posixpath.splitext(rel_src)[1]
  if not (doc_place(parts, suffix) == "차수" and parts[1] == "phase-2"):
    raise SystemExit("멈춤 — 2차 종류 폴더 맨 위의 문서만 된다: docs/phase-2/<번호>-<묶음>[/<종류>]/<이름>.md "
                     f"(받은 것: {rel_src})")
  dst_rel = "/".join(["docs", "phase-3"] + parts[2:])
  dst = root / dst_rel
  if dst.exists():
    raise SystemExit(f"멈춤 — 이미 있다: {dst_rel} — 3차에서는 그 사본을 고친다")

  def remap(t: str) -> str:
    if t.startswith("docs/phase-2/"):
      t3 = "docs/phase-3/" + t[len("docs/phase-2/"):]
      if (root / t3).exists():
        return t3
    return t
  new = relink(src.read_bytes().decode("utf-8"), rel_src, dst_rel, lambda p: (root / p).exists(),
               html=suffix == ".html", remap=remap)
  dst.parent.mkdir(parents=True, exist_ok=True)
  dst.write_bytes(new.encode("utf-8"))
  return dst


def _check_dir(d: Path, root: Path, suffixes: tuple[str, ...]) -> list[str]:
  """종류 폴더 하나 — 맨 위의 판 붙은 문서 · 지난판 사본마다 맨 위에 짝(판 없는 이름)이 있나."""
  problems = []
  for p in sorted(x for x in d.iterdir() if x.is_file() and x.suffix in suffixes):
    if VER_NAME.match(p.stem):
      problems.append(f"맨 위에 판 붙은 문서 — {p.relative_to(root).as_posix()} "
                      f"(판 없는 이름으로 두고 지난 판은 {OLD_DIR}/ 에)")
  old = d / OLD_DIR
  for p in sorted(x for x in old.iterdir() if x.is_file() and x.suffix in suffixes) if old.is_dir() else []:
    m = VER_NAME.match(p.stem)
    if not m or not (d / f"{m.group('base')}{m.group('rest')}{p.suffix}").exists():
      problems.append(f"짝 없는 지난판 사본 — {p.relative_to(root).as_posix()}")
  return problems


def check(root: Path = ROOT) -> list[str]:
  """이름 · 판 규칙 — 차수 폴더 · 맨 위 자산 폴더마다 맨 위의 판 붙은 문서 · 짝 없는 지난판 사본 · 옛 자리에 남은 문서."""
  problems = []
  docs = root / "docs"
  phases = sorted(x for x in docs.iterdir() if x.is_dir() and PHASE.match(x.name)) if docs.is_dir() else []
  for ph in phases:
    for kind in KIND_DIRS:
      if (ph / kind).is_dir():
        problems += _check_dir(ph / kind, root, (".md",))
    if (ph / PRESENT_DIR).is_dir():
      problems += _check_dir(ph / PRESENT_DIR, root, DOC_SUFFIXES)
  for top in TOP_DIRS:
    if (docs / top).is_dir():
      problems += _check_dir(docs / top, root, (".md",))
  for name in OLD_PHASES + OLD_KIND_DIRS + OLD_TOP:          # 옛 자리 — 2026-10-22 뒤에는 문서가 없어야 한다
    old = docs / name
    left = sorted(p for p in old.rglob("*") if p.is_file() and p.suffix in DOC_SUFFIXES) if old.is_dir() else []
    if left:
      problems.append(f"옛 자리에 문서가 남아 있다 — {left[0].relative_to(root).as_posix()} 등 {len(left)}개 "
                      f"(2026-10-22 부터 docs/common · docs/phase-2 · docs/phase-3 · docs/README.md 7절)")
  return problems


def main(argv: list[str] | None = None) -> int:
  sys.stdout.reconfigure(encoding="utf-8")
  ap = argparse.ArgumentParser(description="docs 문서 판 도구 — 지난판 사본 · 이름 · 판 규칙 검사")
  ap.add_argument("--bump", metavar="문서", type=Path, help="지금 판을 지난판/ 에 사본으로(링크를 새 자리에 맞춤)")
  ap.add_argument("--check", action="store_true", help="판 붙은 문서 · 짝 없는 지난판 사본 · 옛 자리 문서가 있으면 종료코드 1")
  ap.add_argument("--to3", metavar="문서", type=Path, help="2차에만 있는 문서를 3차로 사본(링크를 새 자리에 · 3차 사본이 있는 대상은 3차로)")
  args = ap.parse_args(argv)
  if args.to3:
    dst = to3(args.to3)
    print(f"✅ 3차 사본 → {dst.relative_to(ROOT).as_posix()}")
    print("   다음: 3차 사본을 고치고 머리표의 판 · 개정 이력 → 산출물목록 0.1절에 줄(2차 원본은 그대로 얼림)")
  if args.bump:
    dst = bump(args.bump)
    print(f"✅ 사본 → {dst.relative_to(ROOT).as_posix()}")
    if dst.relative_to(ROOT).parts[1:2] == ("phase-2",):
      print("   ⚠️ 2차는 얼린 자리다 — 바로잡기만(docs/README.md 3.3절) · 3차에 고치는 문서는 docs/phase-3/")
    print("   다음: 원본(판 없는 이름)을 고치고 머리표의 판 · 최종 수정 · 개정 이력 → 산출물목록 0.1절 판 칸")
  if args.check:
    problems = check()
    for p in problems:
      print(f"⚠️ {p}")
    print("✅ 이름 · 판 규칙을 지킨다" if not problems else f"⚠️ {len(problems)}건")
    return 1 if problems else 0
  if not (args.bump or args.check or args.to3):
    ap.print_help()
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
