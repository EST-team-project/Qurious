"""GitHub 에 올릴 글 파일 검사기 — 올리기 전에 길이·링크·멘션을 본다.

2026-09-23 옛 계정이 flagged 되자 GitHub 에만 있던 이슈·PR·논의가 남에게 보이지 않게 됐다.
그래서 조직 저장소에 올리는 글은 `docs/github-archive/<날짜>/<글 폴더>/` 에 **파일로 먼저** 쓰고, 사람이
git bash 나 웹에서 올린다(docs/github-archive/README.md). 이 스크립트는 그 파일이 GitHub 에 그대로 올라갈 수
있는지 확인한다. 네트워크를 쓰지 않는다.

    python scripts/post_check.py                                  # 새 글 전부 + 한도에 걸리는 옛 글
    python scripts/post_check.py docs/github-archive/2026-09-17   # 그날 폴더만 (옛 글도 전부 보여 준다)
    python scripts/post_check.py ../_discord --limit 2000         # Discord 글 (메시지당 2,000자)

옛 글(`00-기록.md`)은 옛 저장소 기록이라 상대 링크가 정상이다. 폴더 전체를 볼 때는 **한도에 걸리는 옛 글만**
보여 주고, 날짜 폴더나 파일을 직접 주면 전부 보여 준다.

검사
- 길이: GitHub 는 이슈·댓글·PR 본문이 **65,536자**를 넘으면 422 "body is too long" 으로 거절한다.
  이모지를 2자로 세는 경우를 대비해 **UTF-16 단위**로 보수적으로 센다. 60,000자부터 경고한다.
  `--- 메시지 N ---` 줄이 있으면(Discord 글 관례) 그 사이를 한 덩어리로 따로 잰다.
- 상대 링크: `](../x.md)` 같은 링크는 저장소 안에서는 열리지만 **GitHub 글 안에서는 깨진다** → 절대 주소로.
- 멘션: 백틱 밖의 `@아이디` 는 올리는 순간 알림이 간다 → 부를 사람만 사용자가 직접 붙인다.

⚠️ 길이 초과만 실패(종료 코드 1)로 본다. 링크·멘션은 알림일 뿐이다 — 옛 기록 문서는 상대 링크가 정상이다.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = ROOT / "docs" / "github-archive"
OLD_RECORD = "00-기록.md"
GITHUB_LIMIT = 65_536
WARN_RATIO = 60_000 / 65_536

CHUNK_RE = re.compile(r"^--- 메시지 \d+ ---\s*$", re.M)
FENCE_RE = re.compile(r"^```.*?^```", re.M | re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
RELATIVE_LINK_RE = re.compile(r"\]\((?!https?://|mailto:|#)([^)\s]+)\)")
MENTION_RE = re.compile(r"(?<![\w.`/@])@([A-Za-z0-9][A-Za-z0-9-]{0,38})\b")


def utf16_len(text: str) -> int:
  return len(text.encode("utf-16-le")) // 2


def check_file(path: Path, limit: int) -> dict:
  text = path.read_text(encoding="utf-8")
  chunks = [c for c in CHUNK_RE.split(text) if c.strip()] or [text]
  sizes = [utf16_len(c.strip()) for c in chunks]
  prose = INLINE_CODE_RE.sub("", FENCE_RE.sub("", text))
  worst = max(sizes)
  if worst > limit:
    status = "초과"
  elif worst > limit * WARN_RATIO:
    status = "경고"
  else:
    status = "통과"
  return {
    "path": path,
    "sizes": sizes,
    "status": status,
    "relative_links": sorted(set(RELATIVE_LINK_RE.findall(prose))),
    "mentions": sorted(set(MENTION_RE.findall(prose))),
  }


def targets(paths: list[str]) -> list[Path]:
  found: list[Path] = []
  for p in paths or [str(DEFAULT_TARGET)]:
    base = Path(p)
    if base.is_file():
      found.append(base)
    elif base.is_dir():
      found += sorted(f for f in base.rglob("*.md") if f.name != "README.md")
    else:
      print(f"없는 경로: {p} — 저장소 루트에서 실행했는지 확인하세요.", file=sys.stderr)
  return found


def main() -> int:
  # git bash(mintty)에서는 표준출력이 파이프로 잡혀 cp949 가 된다 → ✅ 에서 UnicodeEncodeError.
  # S51 부터 PR 블록의 이 단계가 사용자 셸에서 한 번도 끝까지 돌지 않았다(2026-09-28 S54 실측).
  for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
      stream.reconfigure(encoding="utf-8")
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("paths", nargs="*", help="파일이나 폴더 (기본: docs/github-archive 전체)")
  parser.add_argument("--limit", type=int, default=GITHUB_LIMIT, help="한 글의 최대 글자 수 (기본 65536)")
  args = parser.parse_args()

  files = targets(args.paths)
  if not files:
    print("검사할 .md 파일이 없습니다.")
    return 0
  whole_archive = not args.paths
  over = hidden = 0
  for f in files:
    r = check_file(f, args.limit)
    if whole_archive and f.name == OLD_RECORD and r["status"] == "통과":
      hidden += 1
      continue
    try:
      shown = f.resolve().relative_to(ROOT)
    except ValueError:
      shown = f
    size = " + ".join(f"{s:,}" for s in r["sizes"])
    mark = {"통과": "✅", "경고": "⚠️", "초과": "❌"}[r["status"]]
    print(f"{mark} {r['status']}  {size}자 / {args.limit:,}  {shown}")
    if r["relative_links"] and f.name != OLD_RECORD:
      print(f"     상대 링크 {len(r['relative_links'])}개 — GitHub 글 안에서는 깨진다: {', '.join(r['relative_links'][:3])}"
            + (" …" if len(r["relative_links"]) > 3 else ""))
    if r["mentions"]:
      print(f"     백틱 밖 멘션 — 올리면 알림이 간다: {', '.join('@' + m for m in r['mentions'])}")
    over += r["status"] == "초과"
  note = f" · 한도 안의 옛 글 {hidden}개는 줄임" if hidden else ""
  print(f"\n파일 {len(files)}개 · 초과 {over}개{note}")
  return 1 if over else 0


if __name__ == "__main__":
  sys.exit(main())
