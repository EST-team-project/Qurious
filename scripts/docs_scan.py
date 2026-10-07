"""docs 문서 판 도구 — 지난판 사본 만들기 · 이름 · 판 규칙 검사 (2026-10-07 docs 정리 뒤).

docs 의 종류 폴더(계획서 · 요구사항 · 설계 · …) 맨 위에는 문서마다 **판 번호 없는 이름 하나**만 두고,
지난 판은 같은 폴더의 `지난판/<이름>_v<판>.md` 사본으로 남긴다(docs/README.md 3절). 판을 올릴 때
지금 파일을 지난판/ 에 그냥 복사하면 한 칸 아래 폴더라 사본 속 상대 링크가 모두 한 단계 어긋난다.
이 도구는 링크를 옛 자리 기준으로 풀어 새 자리 기준으로 다시 써서 사본을 만든다. 네트워크 · git 을 쓰지 않는다.

    python scripts/docs_scan.py --bump docs/시험/테스트계획서.md   지금 판(머리표)을 지난판/ 에 사본으로 — 그다음 원본을 고친다
    python scripts/docs_scan.py --check                              맨 위의 판 붙은 문서 · 짝 없는 지난판 사본 (있으면 종료코드 1)

판 올리는 순서: ① --bump ② 원본(판 없는 이름)을 고치고 머리표의 판 · 최종 수정 · 개정 이력 ③ 산출물목록 0.1절 판 칸.
다른 문서의 링크는 고치지 않아도 된다 — 최신을 가리키는 이름이 그대로라서.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIND_DIRS = ("계획서", "요구사항", "설계", "데이터", "인터페이스", "화면", "시험", "조사", "배포", "개발", "문서기준")
OLD_DIR = "지난판"
#: 판 붙은 이름 — `테스트계획서_v1.15` · `섹터법령-평가셋_v1`
VER_NAME = re.compile(r"^(?P<base>.+?)[_-]v(?P<ver>\d+(?:\.\d+)*)(?P<rest>.*)$")
#: 머리표의 판 칸 — 산출물은 `판 · 상태`, API 명세서처럼 버전이라고 쓴 칸도 읽는다. 없으면 첫 제목의 vX.Y.
HEAD_VERSION = re.compile(r"^\|\s*\*\*(?:판[^*|]*|문서 ?버전)\*\*\s*\|\s*v(\d+(?:\.\d+)*)", re.M)
TITLE_VERSION = re.compile(r"^#\s[^\n]*?\bv(\d+(?:\.\d+)+)", re.M)
LINK = re.compile(r"(!?\[[^\]\n]*\]\()(<[^>\n]+>|[^)\s\n]+)")
REFDEF = re.compile(r"^(\s{0,3}\[[^\]\n]+\]:[ \t]*)(\S+)", re.M)
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z+.-]*:")


def head_version(text: str) -> str | None:
  """머리표의 판(`1.15`). 머리표에 없으면 첫 제목(`# … v0.4 — …`)에서. 둘 다 없으면 None."""
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


def relink(text: str, src: str, dst: str, exists) -> str:
  """`src` 자리 기준 상대 링크를 `dst` 자리 기준으로 다시 쓴다(경로는 저장소 기준 · 슬래시).

  대상이 원래 없던 링크(깨진 링크 · 예시 글) · 주소 · 문서 안(`#…`) 링크는 그대로 둔다.
  자기 자신을 가리키던 링크(`RTM.md#부록`)는 사본 자신으로 — 사본의 절은 사본 안에 있다.
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
    new = _rel(tgt, posixpath.dirname(dst))
    if dec.endswith("/") and not new.endswith("/"):
      new += "/"
    if "%" in path:
      new = urllib.parse.quote(new, safe="/._-~()!*'")
    out = new + tail
    return f"<{out}>" if angle else out

  text = LINK.sub(lambda m: m.group(1) + one(m.group(2)), text)
  return REFDEF.sub(lambda m: m.group(1) + one(m.group(2)), text)


def bump(path: Path, root: Path = ROOT) -> Path:
  """지금 판을 `지난판/<이름>_v<판>.md` 사본으로 만든다(링크를 새 자리에 맞춤 · 줄 끝 그대로). 원본은 고치지 않는다."""
  root = root.resolve()
  src = path if path.is_absolute() else root / path
  try:
    rel_src = src.resolve().relative_to(root).as_posix()
  except ValueError:
    raise SystemExit(f"멈춤 — 저장소 밖의 파일이다: {path}")
  parts = rel_src.split("/")
  if len(parts) != 3 or parts[0] != "docs" or parts[1] not in KIND_DIRS or not rel_src.endswith(".md"):
    raise SystemExit(f"멈춤 — 종류 폴더 맨 위의 문서만 된다: docs/<종류>/<이름>.md (받은 것: {rel_src})")
  stem = parts[2][:-3]
  if VER_NAME.match(stem):
    raise SystemExit(f"멈춤 — 판 붙은 이름이다: {rel_src} → 맨 위에는 판 없는 이름만 둔다(docs/README.md 3절)")
  text = src.read_bytes().decode("utf-8")
  ver = head_version(text)
  if not ver:
    raise SystemExit(f"멈춤 — 머리표에서 판(vX.Y)을 찾지 못했다: {rel_src} — 「판 · 상태」 칸이나 첫 제목에 판을 적는다")
  dst_rel = f"docs/{parts[1]}/{OLD_DIR}/{stem}_v{ver}.md"
  dst = root / dst_rel
  if dst.exists():
    raise SystemExit(f"멈춤 — 이미 있다: {dst_rel} — 이 판은 이미 지난판에 있다(머리표 판을 먼저 올렸나?)")
  new = relink(text, rel_src, dst_rel, lambda p: (root / p).exists())
  dst.parent.mkdir(parents=True, exist_ok=True)
  dst.write_bytes(new.encode("utf-8"))
  return dst


def check(root: Path = ROOT) -> list[str]:
  """이름 · 판 규칙 — 종류 폴더 맨 위에 판 붙은 md 가 있나 · 지난판 사본마다 맨 위에 짝(판 없는 이름)이 있나."""
  problems = []
  for kind in KIND_DIRS:
    d = root / "docs" / kind
    if not d.is_dir():
      continue
    for p in sorted(d.glob("*.md")):
      if VER_NAME.match(p.stem):
        problems.append(f"맨 위에 판 붙은 문서 — {p.relative_to(root).as_posix()} "
                        f"(판 없는 이름으로 두고 지난 판은 {OLD_DIR}/ 에)")
    old = d / OLD_DIR
    for p in sorted(old.glob("*.md")) if old.is_dir() else []:
      m = VER_NAME.match(p.stem)
      if not m or not (d / f"{m.group('base')}{m.group('rest')}.md").exists():
        problems.append(f"짝 없는 지난판 사본 — {p.relative_to(root).as_posix()}")
  return problems


def main(argv: list[str] | None = None) -> int:
  sys.stdout.reconfigure(encoding="utf-8")
  ap = argparse.ArgumentParser(description="docs 문서 판 도구 — 지난판 사본 · 이름 · 판 규칙 검사")
  ap.add_argument("--bump", metavar="문서", type=Path, help="지금 판을 지난판/ 에 사본으로(링크를 새 자리에 맞춤)")
  ap.add_argument("--check", action="store_true", help="맨 위의 판 붙은 문서 · 짝 없는 지난판 사본이 있으면 종료코드 1")
  args = ap.parse_args(argv)
  if args.bump:
    dst = bump(args.bump)
    print(f"✅ 사본 → {dst.relative_to(ROOT).as_posix()}")
    print("   다음: 원본(판 없는 이름)을 고치고 머리표의 판 · 최종 수정 · 개정 이력 → 산출물목록 0.1절 판 칸")
  if args.check:
    problems = check()
    for p in problems:
      print(f"⚠️ {p}")
    print("✅ 이름 · 판 규칙을 지킨다" if not problems else f"⚠️ {len(problems)}건")
    return 1 if problems else 0
  if not (args.bump or args.check):
    ap.print_help()
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
