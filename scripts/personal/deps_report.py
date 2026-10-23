"""주 1회 의존성 갱신 보고서 — 무엇을 올릴 수 있나(고침 판 · 새 판 · 같은 태그의 새 다이제스트)를 표로 알린다 (2026-10-23).

왜 있나
- 판은 requirements.lock(파이썬)과 compose 의 「판 태그@다이제스트」(이미지)로 묶었다(결정 D1 ~ D3). 묶으면 빌드할 때마다 같은
  판이 깔리지만, 그대로 두면 고침 판(보안 · 데이터 손상 고침)도 들어오지 않는다 — Qdrant 서버 v1.19.2(10-05) 를 3주째 못 받았다.
- 그래서 주 1회 이 보고서로 후보를 보고, 사람이 골라 PR 한다(결정 D4 · 봇 · CI 는 쓰지 않는다 — ADR-0003 · 팀 논의 전).

규칙(결정 D4 · D5)
- 주 1회(월요일 세션 첫 점검) · 고침 판은 한 PR 로 묶는다 · 계약 패키지(아래 CONTRACT)의 부 판 · 주 판은 하나씩, 카나리아
  (test.ps1 -Canary)를 먼저 · 나온 지 7일 안 된 판은 빼고 본다(식힘 — uv --exclude-newer) · 11-05 부터 발표(11-12)까지 동결(보안 고침만).
- Qdrant 는 서버 먼저 · 부 판 하나씩(그 부 판의 마지막 고침 판을 거쳐) · 클라이언트는 서버와 부 판 1 이내.
- 이 스크립트는 알리기만 한다 — 잠금 · compose 를 고치지 않는다. GitHub 은 부르지 않는다(PyPI · Docker Hub 만 · 한 번씩 차례로).

쓰는 법(저장소 뿌리에서)::

    python scripts/personal/deps_report.py                 # 화면 + data/local-run/deps/deps-report-<날짜>.md
    python scripts/personal/deps_report.py --no-network    # 파일만 읽고 네트워크 단계는 건너뜀(시험 · 오프라인)

올리는 법 전체는 docs/phase-3/05-deployment/로컬실행안내서.md 「의존성 잠금 · 갱신」.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "requirements.lock"
COMPILE = ["uv", "pip", "compile", "requirements-dev.txt", "--universal", "--python-version", "3.12"]
COOLDOWN_DAYS = 7
FREEZE_FROM = date(2026, 11, 5)      # 3차 발표(11-12) 전 동결 — 보안 고침만
FREEZE_UNTIL = date(2026, 11, 12)
#: 계약 패키지 — 우리 코드가 기대는 동작이 판마다 바뀌는 것(조사 4.6). 부 판 · 주 판은 하나씩 · 카나리아 먼저.
CONTRACT = ("qdrant-client", "langchain", "langchain-core", "langchain-community", "langchain-ollama",
            "langchain-qdrant", "langgraph", "fastapi", "starlette", "pydantic", "pydantic-core")
UA = {"User-Agent": "Qurious-deps-report/1.0 (study project; weekly)"}   # ASCII 만 — 「·」 가 든 머리글은 Docker Hub 가 403


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# ── 파이썬 패키지 ─────────────────────────────────────────────────────────────

def parse_lock(text: str) -> dict[str, str]:
    """잠금 글 → {정규화 이름: 판} (표지는 버린다 — 플랫폼마다 판이 다른 줄은 두지 않는다)."""
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        spec = line.split(";", 1)[0].strip()
        name, _, ver = spec.partition("==")
        out[norm(name.split("[", 1)[0])] = ver.strip()
    return out


def _release(v: str) -> tuple[int, ...]:
    from packaging.version import Version
    return Version(v).release


def classify(old: str | None, new: str | None) -> str:
    """판이 어디서 바뀌었나 — 주 · 부 · 고침 · 새로 · 빠짐 · 같음(날짜형 판 certifi 2026.x 도 같은 셈법)."""
    if old is None:
        return "새로"
    if new is None:
        return "빠짐"
    if old == new:
        return "같음"
    try:
        a, b = _release(old), _release(new)
    except Exception:  # noqa: BLE001 — 판 꼴을 모르면 「부」 로 보고 사람이 본다
        return "부"
    if a[:1] != b[:1]:
        return "주"
    if a[:2] != b[:2]:
        return "부"
    return "고침"


def diff_locks(old: dict[str, str], new: dict[str, str]) -> list[dict]:
    rows = []
    for name in sorted(set(old) | set(new)):
        kind = classify(old.get(name), new.get(name))
        if kind != "같음":
            rows.append({"name": name, "old": old.get(name), "new": new.get(name), "kind": kind,
                         "contract": name in CONTRACT})
    return rows


def upgrade_commands(rows: list[dict]) -> dict[str, str]:
    """붙여 넣을 uv 명령 — 고침 묶음(계약 패키지 밖의 고침 판 · 한 PR) · 계약 패키지는 하나씩."""
    def cmd(names):
        return " ".join(COMPILE + ["-o", "requirements.lock"] + [f"-P {n}" for n in names])
    patch = [r["name"] for r in rows if r["kind"] == "고침" and not r["contract"]]
    contract_patch = [r["name"] for r in rows if r["kind"] == "고침" and r["contract"]]
    out = {}
    if patch:
        out["고침 묶음(한 PR)"] = cmd(patch)
    for n in contract_patch:
        out[f"계약 고침 {n}"] = cmd([n])
    for r in rows:
        if r["kind"] in ("부", "주") and r["contract"]:
            out[f"계약 {r['kind']} 판 {r['name']} — 카나리아 먼저"] = cmd([r["name"]])
    return out


def compile_upgrade(cutoff: date) -> tuple[dict[str, str] | None, str]:
    """식힘 기준일 전에 올라온 판만으로 다시 푼 잠금 — (판 표, 까닭). uv 가 없으면 (None, 안내)."""
    if not shutil.which("uv"):
        return None, "uv 가 없어 파이썬 쪽은 건너뜀 — 잠금을 고치는 사람만 uv 가 필요하다(pip install uv)"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "new.lock"
        args = COMPILE + ["--upgrade", "--exclude-newer", cutoff.isoformat(), "-o", str(out), "--quiet"]
        r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0 or not out.is_file():
            return None, f"uv pip compile 실패(종료 코드 {r.returncode}): {(r.stderr or '').strip()[-300:]}"
        return parse_lock(out.read_text(encoding="utf-8")), ""


def pypi_upload_date(name: str, version: str, fetch=None) -> str:
    """그 판의 첫 파일을 올린 날(PyPI JSON) — 모르면 빈 글."""
    fetch = fetch or _get_json
    d = fetch(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/{urllib.parse.quote(version)}/json")
    files = (d or {}).get("urls") or []
    times = sorted(f.get("upload_time_iso_8601", "") for f in files if f.get("upload_time_iso_8601"))
    return times[0][:10] if times else ""


# ── 이미지 ──────────────────────────────────────────────────────────────────

def compose_images(text: str) -> dict[str, str]:
    """docker-compose.yml → {서비스: image} — 직접 빌드하는 서비스(build:)는 뺀다."""
    out, cur, build, in_services = {}, None, {}, False
    for raw in text.splitlines():
        if raw.startswith("services:"):
            in_services = True
            continue
        if in_services and re.match(r"^\S", raw):
            in_services = False
        if not in_services:
            continue
        m = re.match(r"^  ([a-z][\w-]*):\s*$", raw)
        if m:
            cur = m.group(1)
            continue
        if cur:
            mi = re.match(r"^    image:\s*(\S+)", raw)
            if mi:
                out[cur] = mi.group(1)
            if re.match(r"^    build:", raw):
                build[cur] = True
    return {k: v for k, v in out.items() if not build.get(k)}


def dockerfile_bases(text: str) -> list[str]:
    return [ln.split()[1] for ln in text.splitlines() if ln.strip().startswith("FROM ")]


def split_image(ref: str) -> dict:
    """`repo:tag@sha256:…` → {repo, tag, digest, prefix, nums, suffix} — 판 태그 꼴(v1.19.1 · 16.15-alpine · 5.18.1-community)."""
    name, _, digest = ref.partition("@")
    repo, _, tag = name.rpartition(":")
    m = re.match(r"^(v?)(\d+(?:\.\d+)*)(.*)$", tag)
    nums = tuple(int(x) for x in m.group(2).split(".")) if m else ()
    return {"repo": repo, "tag": tag, "digest": digest, "prefix": m.group(1) if m else "",
            "nums": nums, "suffix": m.group(3) if m else ""}


def newer_tags(cur: dict, tags: list[str]) -> dict:
    """같은 꼴(머리 v · 꼬리 -alpine 등이 같은) 태그 가운데 — 같은 줄(마지막 자리만 다름)의 최신 · 그보다 위 줄의 최신."""
    same, higher = None, None
    n = len(cur["nums"])
    for t in tags:
        m = re.match(r"^(v?)(\d+(?:\.\d+)*)(.*)$", t)
        if not m or m.group(1) != cur["prefix"] or m.group(3) != cur["suffix"]:
            continue
        nums = tuple(int(x) for x in m.group(2).split("."))
        if len(nums) != n or nums <= cur["nums"]:
            continue
        if nums[:-1] == cur["nums"][:-1]:
            if same is None or nums > same[0]:
                same = (nums, t)
        elif higher is None or nums > higher[0]:
            higher = (nums, t)
    return {"same_line": same[1] if same else "", "higher": higher[1] if higher else ""}


def hub_tag(repo: str, tag: str, fetch=None) -> dict:
    fetch = fetch or _get_json
    ns, _, name = repo.rpartition("/")
    d = fetch(f"https://hub.docker.com/v2/repositories/{ns or 'library'}/{name}/tags/{urllib.parse.quote(tag)}")
    return {"digest": (d or {}).get("digest", ""), "pushed": ((d or {}).get("last_pushed") or "")[:10]}


def hub_tags(repo: str, name_filter: str, fetch=None) -> list[str]:
    fetch = fetch or _get_json
    ns, _, name = repo.rpartition("/")
    q = urllib.parse.urlencode({"page_size": 100, "name": name_filter, "ordering": "last_updated"})
    d = fetch(f"https://hub.docker.com/v2/repositories/{ns or 'library'}/{name}/tags?{q}")
    return [r.get("name", "") for r in (d or {}).get("results", [])]


def image_rows(images: dict[str, str], fetch=None) -> list[dict]:
    """이미지마다 한 줄 — 같은 이미지를 쓰는 서비스(ollama · model-pull)는 한 줄로 합친다(한 번만 묻는다)."""
    by_ref: dict[str, list[str]] = {}
    for svc, ref in images.items():
        by_ref.setdefault(ref, []).append(svc)
    rows = []
    for ref, svcs in by_ref.items():
        svc = " · ".join(svcs)
        cur = split_image(ref)
        tag = hub_tag(cur["repo"], cur["tag"], fetch)
        major = f"{cur['prefix']}{cur['nums'][0]}." if cur["nums"] else cur["tag"]
        nt = newer_tags(cur, hub_tags(cur["repo"], major, fetch)) if cur["nums"] else {"same_line": "", "higher": ""}
        rows.append({"service": svc, "ref": ref, "tag": cur["tag"], "repo": cur["repo"],
                     "redigest": bool(tag["digest"]) and tag["digest"] != cur["digest"], "hub_digest": tag["digest"],
                     "pushed": tag["pushed"], **nt})
    return rows


# ── 네트워크(한 번씩 차례로) ────────────────────────────────────────────────────

def _get_json(url: str):
    time.sleep(0.4)   # 사람 속도 — 한꺼번에 몰아 부르지 않는다
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001 — 보고서는 신호다 · 못 읽은 칸은 비워 두고 표에 「모름」
        return None


# ── 보고서 ──────────────────────────────────────────────────────────────────

def phase_note(today: date) -> str:
    if FREEZE_FROM <= today <= FREEZE_UNTIL:
        return f"🧊 동결 기간({FREEZE_FROM:%m-%d} ~ {FREEZE_UNTIL:%m-%d} · 3차 발표) — 보안 고침만 올린다(pip-audit · 레지스트리 보안 공지)"
    return "정기 갱신 — 고침 판은 한 PR 로 묶고, 계약 패키지의 부 · 주 판은 하나씩(카나리아 먼저)"


def render(today: date, cutoff: date, py_rows, py_note: str, img_rows, cmds: dict[str, str]) -> str:
    out = [f"# 의존성 갱신 보고서 — {today.isoformat()}", "",
           f"- {phase_note(today)}",
           f"- 식힘 {COOLDOWN_DAYS}일 — {cutoff.isoformat()} 뒤에 올라온 파이썬 판은 빼고 풀었다(uv --exclude-newer)",
           "- 이 보고서는 알리기만 한다 — 고칠 것은 사람이 골라 PR(로컬실행안내서 「의존성 잠금 · 갱신」)", ""]
    out += ["## 1. 파이썬 패키지(잠금 대비)", ""]
    if py_rows is None:
        out += [f"- 건너뜀 — {py_note}", ""]
    elif not py_rows:
        out += ["- 올릴 것 없음 — 식힘 기준일까지의 최신이 잠금과 같다", ""]
    else:
        out += ["| 패키지 | 잠금 | 새 판 | 갈래 | 올린 날 | 계약 |", "|---|---|---|---|---|---|"]
        order = {"주": 0, "부": 1, "고침": 2, "새로": 3, "빠짐": 4}
        for r in sorted(py_rows, key=lambda r: (not r["contract"], order.get(r["kind"], 9), r["name"])):
            out.append(f"| {r['name']} | {r['old'] or '—'} | {r['new'] or '—'} | {r['kind']} | {r.get('date') or '—'} | "
                       f"{'계약' if r['contract'] else ''} |")
        out.append("")
    out += ["## 2. 이미지(compose · Dockerfile 바탕)", "",
            "| 서비스 | 지금 태그 | 같은 태그 새 다이제스트 | 같은 줄 새 고침 판 | 위 줄 새 판 |", "|---|---|---|---|---|"]
    for r in img_rows:
        red = f"있음({r['pushed']})" if r["redigest"] else ("모름" if not r["hub_digest"] else "없음")
        out.append(f"| {r['service']} | `{r['repo']}:{r['tag']}` | {red} | {r['same_line'] or '—'} | {r['higher'] or '—'} |")
    out += ["", "- Qdrant 는 서버를 먼저 · 부 판 하나씩(그 부 판의 마지막 고침 판을 거쳐) · 클라이언트는 서버와 부 판 1 이내(TC-DL-05).", ""]
    out += ["## 3. 붙여 넣을 명령(골라서 · 한 번에 한 PR)", ""]
    if cmds:
        for label, c in cmds.items():
            out += [f"- {label}", "", "  ```bash", f"  {c}", "  ```", ""]
    else:
        out += ["- 파이썬 쪽 명령 없음", ""]
    out += ["- 이미지를 올리면 compose 의 그 줄을 `태그@다이제스트` 로 바꾸고(같은 태그의 새 다이제스트도 같은 꼴) "
            "`docker compose build app` → `test.ps1 -Split` 순서로 확인한다.", ""]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="주 1회 의존성 갱신 보고서(알리기만)")
    ap.add_argument("--no-network", action="store_true", help="파일만 읽고 네트워크 단계(uv · PyPI · Docker Hub)는 건너뜀")
    ap.add_argument("--out", type=Path, default=None, help="보고서를 쓸 곳(기본 data/local-run/deps/deps-report-<날짜>.md)")
    ap.add_argument("--today", default=None, help="오늘 날짜(시험용 · YYYY-MM-DD)")
    args = ap.parse_args(argv)
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone(timedelta(hours=9))).date()
    cutoff = today - timedelta(days=COOLDOWN_DAYS)
    lock = parse_lock(LOCK.read_text(encoding="utf-8"))

    if args.no_network:
        py_rows, py_note = None, "--no-network"
        fetch = lambda url: None  # noqa: E731
    else:
        new, py_note = compile_upgrade(cutoff)
        py_rows = diff_locks(lock, new) if new is not None else None
        fetch = None
        for r in py_rows or []:
            if r["new"]:
                r["date"] = pypi_upload_date(r["name"], r["new"])
    images = compose_images((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for i, ref in enumerate(dockerfile_bases((ROOT / "Dockerfile").read_text(encoding="utf-8"))):
        images[f"(바탕){'' if i == 0 else i}"] = ref
    img = image_rows(images, fetch)
    text = render(today, cutoff, py_rows, py_note, img, upgrade_commands(py_rows or []))
    out = args.out or ROOT / "data" / "local-run" / "deps" / f"deps-report-{today:%Y%m%d}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n(보고서 파일: {out})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
