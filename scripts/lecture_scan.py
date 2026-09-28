"""강사님 자료(learning/th*) 변경 추적 스캐너 — 기준점과 비교해 바뀐 곳을 뽑는다.

강사님 원본은 수업 중에도 계속 바뀐다. 옛 이슈 #15(2026-09-17)는 5곳을 손으로 비교했는데,
지금은 th01~th23 이 23곳이라 손으로는 빠뜨린다. 그래서 「지난번에 본 커밋」을 기준점 파일에 적어 두고,
받아 올 때마다 그 뒤로 무엇이 들어왔는지 이 스크립트로 뽑는다.

**네트워크를 쓰지 않는다.** 받아 오기는 사용자가 모노레포에서 `bash scripts/sync-lecture.sh` 로 한다
(AI 는 원격에 닿지 않는다 — 전역 규칙 10절). 이 스크립트는 그 뒤 로컬의 `origin/main`·`origin/master` 만 읽는다.

    python scripts/lecture_scan.py            # 사람이 읽는 요약
    python scripts/lecture_scan.py --md       # 추적 이슈 댓글 초안 (마크다운)
    python scripts/lecture_scan.py --update   # 기준점을 지금 값으로 옮긴다 — 댓글 파일을 쓴 뒤에

⚠️ 커밋 **작성자·이메일은 읽지 않는다** — 강사님 원본 이력에 개인 Gmail 이 섞여 있다(모노레포 CLAUDE.md th10 절).
⚠️ 모노레포 밖에서 clone 한 Qurious 에는 `learning/` 이 없다 → `--learning` 으로 경로를 준다.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEARNING = ROOT.parent.parent / "learning"
DEFAULT_BASELINE = ROOT / "docs" / "github-archive" / "2026-09-28" / "이슈-강사님자료-변경추적" / "기준점.tsv"
FIELDS = ["th", "repo", "ref", "commit", "commit_date", "checked_at"]
LIST_CAP = 20


def git(repo: Path, *args: str) -> str | None:
  r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
  return r.stdout.strip() if r.returncode == 0 else None


def read_baseline(path: Path) -> dict[str, dict]:
  if not path.exists():
    return {}
  with path.open(encoding="utf-8", newline="") as f:
    return {row["th"]: row for row in csv.DictReader(f, delimiter="\t")}


def scan(learning: Path, baseline: dict[str, dict], since_days: int) -> list[dict]:
  rows = []
  for d in sorted(p for p in learning.iterdir() if p.is_dir() and p.name.startswith("th")):
    lecture = d / "lecture"
    if not (lecture / ".git").exists():
      rows.append({"th": d.name, "state": "lecture 없음"})
      continue
    ref = next((r for r in ("origin/main", "origin/master") if git(lecture, "rev-parse", "--verify", "--quiet", r)), None)
    if not ref:
      rows.append({"th": d.name, "state": "원격 참조 없음 — 받아 오기부터"})
      continue
    tip = git(lecture, "rev-parse", ref)
    url = (git(lecture, "remote", "get-url", "origin") or "").removeprefix("https://github.com/").removesuffix(".git")
    git_dir = Path(git(lecture, "rev-parse", "--absolute-git-dir") or lecture / ".git")
    fetch_head = git_dir / "FETCH_HEAD"
    row = {
      "th": d.name, "repo": url, "ref": ref, "commit": tip,
      "commit_date": git(lecture, "log", "-1", "--format=%cd", "--date=format-local:%Y-%m-%d %H:%M", ref),
      "fetched_at": dt.datetime.fromtimestamp(fetch_head.stat().st_mtime).strftime("%Y-%m-%d %H:%M") if fetch_head.exists() else "-",
      "head_matches": git(lecture, "rev-parse", "HEAD") == tip,
    }
    base = baseline.get(d.name)
    # 기준점에 짧은 해시가 적혀 있어도 비교가 맞도록 전체 해시로 푼다.
    base_commit = (git(lecture, "rev-parse", "--verify", "--quiet", f'{base["commit"]}^{{commit}}') or base["commit"]
                   if base and base.get("commit") else None)
    if not base_commit:
      row["state"] = "기준 없음"
      log = git(lecture, "log", "--reverse", f"--since={since_days}.days.ago", "--format=%h\t%cd\t%s",
                "--date=format-local:%m-%d %H:%M", ref)
    elif base_commit == tip:
      row["state"] = "변화 없음"
      log = ""
    elif subprocess.run(["git", "-C", str(lecture), "merge-base", "--is-ancestor", base_commit, tip]).returncode == 0:
      row["state"] = "바뀜"
      row["base"] = base_commit
      row["shortstat"] = git(lecture, "diff", "--shortstat", base_commit, tip) or ""
      log = git(lecture, "log", "--reverse", "--format=%h\t%cd\t%s", "--date=format-local:%m-%d %H:%M",
                f"{base_commit}..{tip}")
    else:
      row["state"] = "이력 바뀜 — 기준 커밋이 원격 이력에 없다"
      row["base"] = base_commit
      log = ""
    row["commits"] = [line.split("\t", 2) for line in (log or "").splitlines() if line]
    rows.append(row)
  gone = sorted(set(baseline) - {r["th"] for r in rows})
  rows += [{"th": th, "state": "사라짐 — 기준에는 있었다"} for th in gone]
  return rows


def to_text(rows: list[dict]) -> str:
  out = []
  for r in rows:
    head = f'{r["th"]:<26} {r["state"]}'
    if "commit" in r:
      head += f'  끝 {r["commit"][:7]} ({r["commit_date"]})  받은 시각 {r["fetched_at"]}'
      if not r["head_matches"]:
        head += "  ⚠️ 작업 트리가 원격 끝과 다름"
    out.append(head)
    for h, when, subject in r.get("commits", [])[:LIST_CAP]:
      out.append(f"    {h} {when} {subject}")
    if len(r.get("commits", [])) > LIST_CAP:
      out.append(f'    … 외 {len(r["commits"]) - LIST_CAP}커밋')
  return "\n".join(out)


def to_md(rows: list[dict], since_days: int) -> str:
  now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
  changed = [r for r in rows if r["state"] == "바뀜"]
  fresh = [r for r in rows if r["state"] == "기준 없음" and r.get("commits")]
  lines = [
    f"## 강사님 자료 변경 — {now} 확인",
    "",
    "| 폴더 | 원본 | 지금 끝 | 상태 |",
    "|---|---|---|---|",
  ]
  for r in rows:
    if "commit" not in r:
      lines.append(f'| {r["th"]} | — | — | {r["state"]} |')
      continue
    state = r["state"]
    if state == "바뀜":
      state = f'**{len(r["commits"])}커밋** (`{r["base"][:7]}` 부터)'
    elif state == "기준 없음":
      state = f"기준 없음 · 최근 {since_days}일 {len(r['commits'])}커밋"
    lines.append(f'| {r["th"]} | `{r["repo"]}` | `{r["commit"][:7]}` {r["commit_date"]} | {state} |')
  for r in changed + fresh:
    title = (f'`{r["base"][:7]}` → `{r["commit"][:7]}` · {r.get("shortstat", "")}'
             if r["state"] == "바뀜" else f"최근 {since_days}일")
    lines += ["", f'### {r["th"]} — {len(r["commits"])}커밋 ({title})', ""]
    if r["state"] == "바뀜":
      lines.append(f'비교: https://github.com/{r["repo"]}/compare/{r["base"][:7]}...{r["commit"][:7]}')
      lines.append("")
    lines += ["| 커밋 | 시각 (KST) | 제목 |", "|---|---|---|"]
    for h, when, subject in r["commits"][:LIST_CAP]:
      lines.append(f"| `{h}` | {when} | {subject.replace('|', '/')} |")
    if len(r["commits"]) > LIST_CAP:
      lines.append(f'| … | | 외 {len(r["commits"]) - LIST_CAP}커밋 — 비교 링크에서 |')
  return "\n".join(lines)


def write_baseline(path: Path, rows: list[dict]) -> None:
  now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
    w.writeheader()
    for r in rows:
      if "commit" in r:
        w.writerow({"th": r["th"], "repo": r["repo"], "ref": r["ref"], "commit": r["commit"],
                    "commit_date": r["commit_date"], "checked_at": now})


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("--learning", type=Path, default=DEFAULT_LEARNING, help="learning 폴더 (기본: 모노레포의 learning)")
  parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE, help="기준점 TSV")
  parser.add_argument("--since-days", type=int, default=7, help="기준이 없는 폴더는 최근 며칠을 보여 줄지")
  parser.add_argument("--md", action="store_true", help="추적 이슈 댓글 초안")
  parser.add_argument("--update", action="store_true", help="기준점을 지금 값으로 옮긴다")
  args = parser.parse_args()

  if not args.learning.is_dir():
    print(f"learning 폴더가 없습니다: {args.learning}\n"
          "EST-Camp-AI-Quant 모노레포 안의 Qurious 에서 돌리거나, --learning 으로 경로를 주세요.")
    return 0
  os.environ.setdefault("GIT_OPTIONAL_LOCKS", "0")  # 읽기만 하므로 index 잠금을 만들지 않는다
  rows = scan(args.learning, read_baseline(args.baseline), args.since_days)
  print(to_md(rows, args.since_days) if args.md else to_text(rows))
  if args.update:
    write_baseline(args.baseline, rows)
    print(f"\n기준점을 옮겼습니다: {args.baseline.relative_to(ROOT)}", file=sys.stderr)
  return 0


if __name__ == "__main__":
  sys.exit(main())
