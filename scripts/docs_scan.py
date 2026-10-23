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
    python scripts/docs_scan.py --sync                                   동기화 대장 — 원천(팀원 설계서)이 올랐거나 글이 바뀐 절 (오류만 종료코드 1)
    python scripts/docs_scan.py --sync-ack SY-01 SY-02                   읽고 옮긴 뒤 — 그 줄의 고정판 · 고정지문 · 옮긴날을 지금 원천 값으로

판 올리는 순서: ① --bump ② 원본(판 없는 이름)을 고치고 머리표의 판 · 최종 수정 · 개정 이력 ③ 산출물목록 0.1절 판 칸.
다른 문서의 링크는 고치지 않아도 된다 — 최신을 가리키는 이름이 그대로라서. 원천이 있는 통합 문서면 ④ --sync-ack · --sync 경고 0.

동기화(--sync · 2026-10-23 사용자 결정 · 동기화 조사 4.2 · 4.3): 통합 문서 절이 어느 팀원 설계서의 어느 절을 몇 판 기준으로
옮겼는지는 `대장/설계-동기화.tsv` 한 곳이 정본이다. 판만 고정하면 판이 안 오른 채 바뀐 글을 못 보므로 절 지문도 고정한다 —
지문 = 링크 주소를 빼고(글자는 남김) · 줄 끝 공백 지움 · 연속 공백 하나로 · 빈 줄 접기 뒤 SHA-256 앞 12자. 원천 절은 머리글
첫 낱말에서 끝의 점을 뗀 값(`## 4.` → 4 · `### 4.3` → 4.3)으로 찾고 다음 같은 · 높은 머리글 전까지 자른다(코드 울타리 안의
`#` 줄은 머리글이 아니다 · 원천절이 비면 파일 전체). 오류(대장이 틀렸다)만 종료코드 1 — 경고 A(원천이 올랐다) · 경고 B(판은
그대로인데 글이 바뀌었다) · 안내(미반영 · 아직 고정 안 함)는 머지를 막지 않는다. 통합 문서는 고치지 않는다(읽고 알리기 ·
고정 값 기록까지).

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
import hashlib
import posixpath
import re
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
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
#: 동기화 대장 — 요구 대장 · 시험-요구 대장 곁의 셋째 추적 대장(2026-10-23). 통합문서 · 원천파일 칸은 docs 기준 경로
SYNC_LEDGER = "docs/phase-3/01-analysis/requirements/대장/설계-동기화.tsv"
SYNC_COLS = ("동기화ID", "통합문서", "통합절", "원천파일", "원천절", "방식", "고정판", "고정지문", "옮긴날", "옮긴이", "상태", "비고")
#: 방식 다섯 — 앞의 셋은 통합 문서 절 머리에 「> 원천: [이름](경로) 4.3절 · v0.2 · 갈음 · SY-01」 줄을 둔다.
#: 링크만 · 미반영은 원천 줄이 없다(RTM 설계 칸은 원천을 이름으로 적는다) — 원천 쪽 판 · 지문만 본다.
SYNC_WAYS = ("옮김", "요약", "갈음", "링크만", "미반영")
SYNC_LINE_WAYS = ("옮김", "요약", "갈음")
NO_VER = "판 없음"
SYNC_LEVELS = ("오류", "경고 A", "경고 B", "안내")
HEADING = re.compile(r"^(#{1,6})[ \t]+(\S+)")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
#: 지문에서 뺄 링크 주소 — `[글](주소 "제목")` 은 `[글]` 로, 참조 정의 `[이름]: 주소` 는 `[이름]:` 로
FP_LINK = re.compile(r"(!?\[[^\]\n]*\])\((?:<[^>\n]*>|[^)\n]*)\)")
FP_REFDEF = re.compile(r"^([ \t]{0,3}\[[^\]\n]+\]:)[ \t]*\S.*$", re.M)
KST = timezone(timedelta(hours=9))


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


def section_text(text: str, sec: str) -> str | None:
  """원천 절 — 머리글 첫 낱말에서 끝의 점을 뗀 값이 `sec` 인 첫 머리글부터 다음 같은 · 높은 머리글 전까지(머리글 줄 포함).

  `sec` 가 비면 파일 전체. 코드 울타리(``` · ~~~) 안의 `#` 줄은 머리글이 아니다. 못 찾으면 None. 줄 끝은 LF 로 돌려준다.
  """
  lines = text.replace("\r\n", "\n").split("\n")
  if not sec:
    return "\n".join(lines)
  start = level = None
  fence = ""
  for i, line in enumerate(lines):
    f = FENCE.match(line)
    if f:
      mark = f.group(1)
      if not fence:
        fence = mark
      elif mark[0] == fence[0] and len(mark) >= len(fence):    # 여는 울타리와 같은 글자 · 같거나 긴 줄이 닫는다
        fence = ""
      continue
    h = None if fence else HEADING.match(line)
    if not h:
      continue
    if start is None:
      if h.group(2).rstrip(".") == sec:
        start, level = i, len(h.group(1))
    elif len(h.group(1)) <= level:
      return "\n".join(lines[start:i])
  return "\n".join(lines[start:]) if start is not None else None


def fingerprint(text: str) -> str:
  """절 지문 — 링크 주소를 빼고(글자는 남김) · 줄 끝 공백 지움 · 연속 공백 하나로 · 빈 줄 접기 뒤 SHA-256 앞 12자.

  폴더를 옮겨 링크만 다시 쓴 커밋 · 줄 바꿈 꼴 · 띄어쓰기 손질에는 지문이 그대로이고, 글자가 하나라도 바뀌면 달라진다.
  """
  t = FP_REFDEF.sub(r"\1", FP_LINK.sub(r"\1", text.replace("\r\n", "\n")))
  out: list[str] = []
  for line in t.split("\n"):
    line = re.sub(r"[ \t]+", " ", line.rstrip())
    if line or (out and out[-1]):                                # 빈 줄이 이어지면 하나만 · 맨 앞 빈 줄은 버림
      out.append(line)
  while out and not out[-1]:
    out.pop()
  return hashlib.sha256("\n".join(out).encode("utf-8")).hexdigest()[:12]


def _ver_key(v: str | None) -> tuple[int, ...] | None:
  """`v0.10` · `0.10` → (0, 10) — 판은 글자가 아니라 숫자로 견준다(0.10 > 0.9). 판 꼴이 아니면 None."""
  m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (v or "").strip())
  return tuple(int(x) for x in m.group(1).split(".")) if m else None


def _show_ver(v: str | None) -> str:
  """대장 · 원천 줄에 쓰는 꼴 — `v0.2`, 판이 없으면 「판 없음」."""
  k = _ver_key(v)
  return "v" + ".".join(map(str, k)) if k else NO_VER


def _ledger(root: Path):
  """동기화 대장 — (경로, 줄 끝, 줄 목록, 머리 칸, [(줄 번호, 칸 목록, 칸 사전)]). 빈 줄은 건너뛴다."""
  path = root / SYNC_LEDGER
  if not path.is_file():
    raise SystemExit(f"멈춤 — 동기화 대장이 없다: {SYNC_LEDGER}")
  raw = path.read_bytes().decode("utf-8")
  nl = "\r\n" if "\r\n" in raw else "\n"
  lines = raw.split(nl)
  head = lines[0].split("\t")
  missing = [c for c in SYNC_COLS if c not in head]
  if missing:
    raise SystemExit(f"멈춤 — 동기화 대장 머리에 칸이 없다: {' · '.join(missing)} ({SYNC_LEDGER})")
  rows = []
  for i, line in enumerate(lines[1:], 1):
    if line.strip():
      cells = line.split("\t")
      cells += [""] * (len(head) - len(cells))
      rows.append((i, cells, {c: cells[head.index(c)].strip() for c in SYNC_COLS}))
  return path, nl, lines, head, rows


def _source_lines(text: str, sid: str) -> list[tuple[int, str | None]]:
  """통합 문서의 `> 원천: … · SY-01` 줄 — (줄 번호, 그 줄의 판 `v0.2` · 「판 없음」 · 못 읽으면 None). SY-1 은 SY-10 에 맞지 않는다."""
  out = []
  idre = re.compile(rf"(?<![\w-]){re.escape(sid)}(?![\w-])")
  for n, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
    if re.match(r"^ {0,3}>\s*원천\s*:", line) and idre.search(line):
      parts = [p.strip() for p in FP_LINK.sub(r"\1", line).split("·")]
      out.append((n, next((p for p in parts if p == NO_VER or re.fullmatch(r"v\d+(?:\.\d+)*", p)), None)))
  return out


def _read_source(root: Path, row: dict):
  """원천 파일 · 절 — (파일 글, 절 글) · 못 찾으면 (None, 까닭)."""
  src = root / "docs" / row["원천파일"]
  if not row["원천파일"] or not src.is_file():
    return None, f"원천 파일이 없다 — docs/{row['원천파일']}"
  text = src.read_bytes().decode("utf-8")
  body = section_text(text, row["원천절"])
  if body is None:
    return None, f"원천 절 {row['원천절']} 을 못 찾았다 — docs/{row['원천파일']}(머리글 첫 낱말에서 끝의 점을 뗀 값)"
  return text, body


def sync_check(root: Path = ROOT) -> list[tuple[str, str, str]]:
  """동기화 대장 줄마다 — 원천 판 · 절 지문을 고정 값과 견주고, 통합 문서의 원천 줄이 대장과 맞는지(조사 4.3).

  돌려주는 것: [(단계, 동기화ID, 글)] — 단계는 SYNC_LEVELS. 오류 = 대장이 틀렸다(고칠 것) · 경고 A = 원천이 올랐다(옮길 일) ·
  경고 B = 판은 그대로인데 글이 바뀌었다(읽고 옮기거나 ack) · 안내 = 미반영 · 아직 고정 안 함.
  """
  _, _, _, _, rows = _ledger(root)
  out: list[tuple[str, str, str]] = []
  seen: set[str] = set()
  for _, _, r in rows:
    sid = r["동기화ID"]

    def add(level: str, msg: str) -> None:
      out.append((level, sid, msg))

    if sid in seen:
      add("오류", "대장에 같은 ID 가 두 줄이다")
      continue
    seen.add(sid)
    way = r["방식"]
    if way not in SYNC_WAYS:
      add("오류", f"방식 「{way}」 — {' · '.join(SYNC_WAYS)} 가운데 하나")
      continue
    stext, body = _read_source(root, r)
    if stext is None:
      add("오류", body)
      continue
    doc = root / "docs" / r["통합문서"]
    if not r["통합문서"] or not doc.is_file():
      add("오류", f"통합 문서가 없다 — docs/{r['통합문서']}")
      continue
    fixed_v, fixed_fp = r["고정판"], r["고정지문"]
    if fixed_v and fixed_v != NO_VER and _ver_key(fixed_v) is None:
      add("오류", f"고정판 「{fixed_v}」 을 못 읽는다 — v0.2 꼴 · 「{NO_VER}」 · 빈 칸(아직 고정 안 함)")
      continue
    if fixed_fp and not re.fullmatch(r"[0-9a-f]{12}", fixed_fp):
      add("오류", f"고정지문 「{fixed_fp}」 — 손으로 쓰지 않는다(--sync-ack {sid})")
      continue
    if way in SYNC_LINE_WAYS:
      found = _source_lines(doc.read_bytes().decode("utf-8"), sid)
      if not found:
        add("오류", f"통합 문서에 원천 줄(> 원천: … · {sid})이 없다 — docs/{r['통합문서']} {r['통합절']}")
      elif fixed_v:
        for n, lv in found:
          if lv != _show_ver(fixed_v):
            add("오류", f"원천 줄의 판 {lv or '(못 읽음)'} ≠ 대장 고정판 {_show_ver(fixed_v)} — docs/{r['통합문서']}:{n}")
    where = f"{r['원천절']}절" if r["원천절"] else "파일 전체"
    if way == "미반영":
      add("안내", f"미반영 — 아직 안 이어졌다(docs/{r['통합문서']} {r['통합절']} ← {where})")
    if not fixed_v or not fixed_fp:
      add("안내", f"아직 고정 안 함 — 원천을 읽은 뒤 --sync-ack {sid}")
      continue
    sver = head_version(stext)
    fk, sk = _ver_key(fixed_v), _ver_key(sver)
    now_fp = fingerprint(body)
    if fk and not sk:
      add("오류", f"원천 판을 못 읽는다(고정판 {_show_ver(fixed_v)}) — docs/{r['원천파일']} 머리표")
    elif fk and sk < fk:
      add("오류", f"원천 판 {_show_ver(sver)} < 고정판 {_show_ver(fixed_v)} — 대장이 틀렸다")
    elif sk and (not fk or sk > fk):
      same = "그대로(판만 올랐다면 확인 뒤 ack)" if now_fp == fixed_fp else "바뀜"
      add("경고 A", f"원천이 올랐다 {_show_ver(fixed_v)} → {_show_ver(sver)} · {where} 글 {same} — "
                   f"읽고 통합 절을 고친 뒤 --sync-ack {sid}")
    elif now_fp != fixed_fp:
      add("경고 B", f"판은 그대로({_show_ver(fixed_v)})인데 {where} 글이 바뀌었다 {fixed_fp} → {now_fp} — "
                   f"읽고 옮기거나 --sync-ack {sid}")
  return out


def sync_ack(ids: list[str], root: Path = ROOT, today: str | None = None) -> list[str]:
  """대장 줄의 고정판 · 고정지문 · 옮긴날(KST)을 지금 원천 값으로 쓴다 — 그 줄의 세 칸만(다른 줄 · 칸 · 줄 끝 그대로).
  미반영 줄은 옮긴 적이 없으므로 옮긴날을 두고 고정판 · 고정지문만 쓴다(원천이 바뀌면 경고로 알게).

  ID 하나라도 못 찾거나 원천 절이 없으면 아무것도 쓰지 않고 멈춘다. 통합 문서는 고치지 않는다 — 원천 줄의 판이 새 고정판과
  다르면 고칠 줄을 알려 준다(다음 --sync 에서 오류).
  """
  path, nl, lines, head, rows = _ledger(root)
  today = today or datetime.now(KST).date().isoformat()
  byid: dict[str, list] = {}
  for i, cells, r in rows:
    byid.setdefault(r["동기화ID"], []).append((i, cells, r))
  done = []
  for sid in ids:
    hits = byid.get(sid, [])
    if len(hits) != 1:
      raise SystemExit(f"멈춤 — 대장에 {sid} 줄이 {len(hits)}개다(하나여야 한다) · 아무것도 쓰지 않았다 ({SYNC_LEDGER})")
    i, cells, r = hits[0]
    stext, body = _read_source(root, r)
    if stext is None:
      raise SystemExit(f"멈춤 — {sid}: {body} · 아무것도 쓰지 않았다")
    ver = _show_ver(head_version(stext))
    put = [("고정판", ver), ("고정지문", fingerprint(body))] + ([] if r["방식"] == "미반영" else [("옮긴날", today)])
    for col, val in put:
      cells[head.index(col)] = val
    lines[i] = "\t".join(cells)
    msg = f"{sid} — {ver} · {cells[head.index('고정지문')]} · {r['원천절'] + '절' if r['원천절'] else '파일 전체'}"
    doc = root / "docs" / r["통합문서"]
    if r["방식"] in SYNC_LINE_WAYS and doc.is_file():
      for n, lv in _source_lines(doc.read_bytes().decode("utf-8"), sid):
        if lv != ver:
          msg += f" · ⚠️ 원천 줄도 {ver} 로: docs/{r['통합문서']}:{n}(지금 {lv or '못 읽음'})"
    done.append(msg)
  path.write_bytes(nl.join(lines).encode("utf-8"))
  return done


def main(argv: list[str] | None = None) -> int:
  sys.stdout.reconfigure(encoding="utf-8")
  ap = argparse.ArgumentParser(description="docs 문서 판 도구 — 지난판 사본 · 이름 · 판 규칙 검사")
  ap.add_argument("--bump", metavar="문서", type=Path, help="지금 판을 지난판/ 에 사본으로(링크를 새 자리에 맞춤)")
  ap.add_argument("--check", action="store_true", help="판 붙은 문서 · 짝 없는 지난판 사본 · 옛 자리 문서가 있으면 종료코드 1")
  ap.add_argument("--to3", metavar="문서", type=Path, help="2차에만 있는 문서를 3차로 사본(링크를 새 자리에 · 3차 사본이 있는 대상은 3차로)")
  ap.add_argument("--sync", action="store_true",
                  help="동기화 대장 — 원천이 올랐거나 글이 바뀐 절 · 원천 줄이 대장과 다른 곳(오류만 종료코드 1)")
  ap.add_argument("--sync-ack", metavar="ID", nargs="+",
                  help="읽고 옮긴 뒤 — 대장 그 줄의 고정판 · 고정지문 · 옮긴날을 지금 원천 값으로")
  args = ap.parse_args(argv)
  code = 0
  if args.sync_ack:
    for line in sync_ack(args.sync_ack, ROOT):
      print(f"✅ 고정 {line}")
  if args.sync:
    found = sync_check(ROOT)
    icon = {"오류": "❌", "경고 A": "⚠️", "경고 B": "⚠️", "안내": "ℹ️"}
    for level, sid, msg in sorted(found, key=lambda x: (SYNC_LEVELS.index(x[0]), x[1])):
      print(f"{icon[level]} {sid} {level} — {msg}")
    n = {lv: sum(1 for x in found if x[0] == lv) for lv in SYNC_LEVELS}
    rows = len(_ledger(ROOT)[4])
    warn = n["경고 A"] + n["경고 B"]
    head = "✅" if not n["오류"] and not warn else ("❌" if n["오류"] else "⚠️")
    print(f"{head} 동기화 대장 {rows}줄 — 오류 {n['오류']} · 경고 {warn}(A {n['경고 A']} · B {n['경고 B']}) · 안내 {n['안내']}")
    code = 1 if n["오류"] else 0
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
    return 1 if problems else code
  if not (args.bump or args.check or args.to3 or args.sync or args.sync_ack):
    ap.print_help()
  return code


if __name__ == "__main__":
  raise SystemExit(main())
