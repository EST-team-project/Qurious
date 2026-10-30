"""수집 회차 프로파일 — 단계별 시간 · 큰 단계 · 겹쳐 돌릴 때의 절감 어림 (할 일 P1 · 2026-10-30 · 강사님 피드백 「잘게 쪼개 속도」).

**읽기 전용**이다 — `state/daily_update_last.json` 만 읽고 아무것도 쓰지 않는다(러너 · 수집 DB 를 건드리지 않는다).
설계: `docs/phase-3/02-design/system/수집-파이프라인-분리-병렬화-설계.md` 2 ~ 5절.

    python scripts/pipeline_profile.py                  # 마지막 회차 — 묶음별 · 큰 단계 · 시나리오
    python scripts/pipeline_profile.py --md             # 설계 문서에 붙일 표
    python scripts/pipeline_profile.py --json
    python scripts/pipeline_profile.py --file <다른 회차 json>

⚠️ **의존 관계(`DEPS`)는 설계 문서 3절의 가설이다**(`STEPS` 주석에서 읽음 · H1 · H4 는 코드로 확인). 코드로 확인되면 여기를 고친다.
시나리오 숫자는 「이 의존이 맞다면」 의 어림이지 약속이 아니다 — 단계 안에서 쓰기 시간이 얼마인지는 아직 안 쟀다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

ROOT = Path(__file__).resolve().parents[1]
STATE_LAST = ROOT / "data" / "collector" / "state" / "daily_update_last.json"
STATE_STEPS = ROOT / "data" / "collector" / "state" / "daily_update_steps.json"
STATE_HISTORY = ROOT / "data" / "collector" / "state" / "daily_update_history.jsonl"
#: 이 단계 수 아래의 이력 줄은 한 단계만 다시 돌린 것(`--only` 등)이라 회차로 세지 않는다
MIN_ROUND_STEPS = 15

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

#: 단계 → 먼저 끝나야 하는 단계(설계 3절 · 가설). 받기 단계끼리는 의존이 없다고 본다(H3 — 쓰기 충돌은 RESOURCE 가 따로 막는다).
DEPS: Dict[str, List[str]] = {
    "price": [], "dividend": [], "disclosure": [], "financial": [], "financial_full": [], "company": [],
    "schedule": [], "news": [], "gdelt": [], "ecos": [],
    "search": ["price", "disclosure", "news", "gdelt"],                 # H1 확인 — 가격 계산 산출물을 읽지 않는다
    "calendar": ["price", "dividend", "schedule"],
    "adjusted": ["price", "calendar"],
    "total_return": ["adjusted", "dividend"],
    "benchmark": ["total_return"],
    "ohlcv": ["adjusted"],
    "quality": ["benchmark", "ohlcv"],                                   # 10-30 ohlcv 뒤로 옮김 — ETF · 지수 일봉 적재 뒤에 재야 거짓 경고가 없다
    "signals": ["ohlcv"],
    "journal": ["signals"],
    "manifest": [],
    "export": ["ohlcv", "benchmark", "journal"],
    "verify": ["export"],
    "upload": ["verify"],
    "ohlcv_upload": ["upload"],
    "journal_upload": ["ohlcv_upload"],
    "sector_laws": [],
}
#: 같은 자원에 쓰는 단계는 겹치지 않는다 — SQLite 는 쓰는 쪽이 하나(설계 5절). `None` 은 자원 충돌 없음.
RESOURCE: Dict[str, Optional[str]] = {n: None for n in DEPS}
for _n in ("price", "dividend", "disclosure", "financial", "financial_full", "company", "schedule", "news", "gdelt", "ecos",
           "calendar", "adjusted", "total_return", "benchmark", "ohlcv"):
    RESOURCE[_n] = "market_db_write"
RESOURCE["search"] = "search_db_write"                                   # 따로 둔 파일 — 수집 DB 쓰기와 충돌 없음


def load_steps(path: Path) -> List[dict]:
    d = json.loads(path.read_text(encoding="utf-8"))
    return [{"name": s["name"], "seconds": float(s.get("seconds") or 0), "status": s.get("status")} for s in d.get("steps", [])]


def groups(path: Path = STATE_STEPS) -> Dict[str, str]:
    try:
        cat = json.loads(path.read_text(encoding="utf-8"))
        return {s["name"]: s.get("group") or "?" for s in (cat["steps"] if isinstance(cat, dict) else cat)}
    except (OSError, ValueError, KeyError):
        return {}


def check_model(deps: Dict[str, List[str]] = DEPS) -> List[str]:
    """의존 모델 자체의 앞뒤 — 모르는 단계 · 순환(빈 목록이면 통과)."""
    bad = [f"{n} 의 선행 {d} 가 단계 목록에 없다" for n, ds in deps.items() for d in ds if d not in deps]
    seen: Set[str] = set()
    stack: Set[str] = set()

    def visit(n: str) -> bool:
        if n in stack:
            return True
        if n in seen:
            return False
        seen.add(n)
        stack.add(n)
        cyc = any(visit(d) for d in deps.get(n, []) if d in deps)
        stack.discard(n)
        return cyc
    if any(visit(n) for n in deps):
        bad.append("의존에 순환이 있다")
    return bad


def critical_path(sec: Dict[str, float], deps: Dict[str, List[str]] = DEPS) -> dict:
    """자원 충돌을 무시하고 일꾼이 무한할 때의 하한(가장 긴 의존 사슬)."""
    finish: Dict[str, float] = {}
    prev: Dict[str, Optional[str]] = {}

    def f(n: str) -> float:
        if n in finish:
            return finish[n]
        best, who = 0.0, None
        for d in deps.get(n, []):
            if d in sec and f(d) > best:
                best, who = f(d), d
        finish[n], prev[n] = best + sec.get(n, 0.0), who
        return finish[n]
    for n in sec:
        f(n)
    end = max(finish, key=finish.get)
    path, cur = [], end
    while cur:
        path.append(cur)
        cur = prev[cur]
    return {"seconds": finish[end], "path": path[::-1]}


def simulate(sec: Dict[str, float], order: List[str], workers: int, deps: Dict[str, List[str]] = DEPS,
             resource: Dict[str, Optional[str]] = RESOURCE, use_resource: bool = True) -> float:
    """목록 순서대로 가장 먼저 시작할 수 있는 단계를 일꾼에 붙이는 단순 계획기(어림) — 걸리는 총 시간(초)."""
    done: Dict[str, float] = {}
    free = [0.0] * workers
    res_free: Dict[str, float] = {}
    remaining = [n for n in order if n in sec]
    while remaining:
        ready = [n for n in remaining if all((d in done) or (d not in sec) for d in deps.get(n, []))]
        if not ready:
            raise ValueError("의존이 풀리지 않는다 — 모델을 확인한다")
        n = ready[0]                                            # 목록 순서 우선
        w = min(range(workers), key=lambda i: free[i])
        start = max(free[w], max((done[d] for d in deps.get(n, []) if d in done), default=0.0))
        r = resource.get(n) if use_resource else None
        if r:
            start = max(start, res_free.get(r, 0.0))
        end = start + sec[n]
        free[w] = end
        done[n] = end
        if r:
            res_free[r] = end
        remaining.remove(n)
    return max(done.values())


def report(steps: List[dict], group_of: Optional[Dict[str, str]] = None) -> dict:
    sec = {s["name"]: s["seconds"] for s in steps}
    order = [s["name"] for s in steps]
    total = sum(sec.values())
    big = sorted(sec.items(), key=lambda kv: -kv[1])
    top7 = sum(v for _, v in big[:7])
    out = {"steps": len(steps), "total_seconds": round(total, 1),
           "top": [{"name": n, "seconds": round(v, 1), "share": round(v / total, 3) if total else 0} for n, v in big[:10]],
           "top7_share": round(top7 / total, 3) if total else 0, "groups": {}}
    for n, v in sec.items():
        g = (group_of or {}).get(n, "?")
        out["groups"][g] = round(out["groups"].get(g, 0) + v, 1)
    unmodeled = [n for n in sec if n not in DEPS]
    out["unmodeled_steps"] = unmodeled                           # 모델에 없는 새 단계 — DEPS 에 더해야 시나리오가 맞다
    known = {n: v for n, v in sec.items() if n in DEPS}
    kn_order = [n for n in order if n in known]
    cp = critical_path(known)
    out["scenarios"] = {
        "지금(순차 · 일꾼 1)": round(simulate(known, kn_order, 1, use_resource=False), 1),
        "일꾼 2 · 수집 DB 쓰기는 한 줄(보수)": round(simulate(known, kn_order, 2), 1),
        "일꾼 3 · 수집 DB 쓰기는 한 줄(보수)": round(simulate(known, kn_order, 3), 1),
        "일꾼 2 · 의존만 지킴(낙관)": round(simulate(known, kn_order, 2, use_resource=False), 1),
        "일꾼 무한 · 의존만(하한)": round(cp["seconds"], 1),
    }
    out["critical_path"] = cp
    return out


def history_stats(path: Path = STATE_HISTORY) -> dict:
    """회차 이력(`daily_update_history.jsonl`)에서 단계마다 걸린 초의 분포 — **한 회차로 정한 어림을 버리고 날마다 다른 값을 본다**
    (10-30: `search` 가 10-28 468초 · 10-29 457초 · 10-30 13초로 달랐다). 한 단계만 다시 돌린 줄은 뺀다."""
    per: Dict[str, List[float]] = {}
    rounds = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"rounds": 0, "steps": {}}
    for ln in lines:
        try:
            h = json.loads(ln)
        except ValueError:
            continue
        steps = h.get("steps") or []
        if h.get("only") or len(steps) < MIN_ROUND_STEPS:
            continue
        rounds += 1
        for s in steps:
            if s.get("seconds") is not None:
                per.setdefault(s["name"], []).append(float(s["seconds"]))
    out: Dict[str, dict] = {}
    for name, v in per.items():
        v = sorted(v)
        mid = v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2
        out[name] = {"n": len(v), "min": round(v[0], 1), "median": round(mid, 1), "max": round(v[-1], 1),
                     "mean": round(sum(v) / len(v), 1), "spread": round(v[-1] - v[0], 1)}
    return {"rounds": rounds, "steps": out}


def render_history(h: dict) -> str:
    if not h["rounds"]:
        return "회차 이력이 없다(전체 회차 줄이 0)"
    rows = sorted(h["steps"].items(), key=lambda kv: -kv[1]["spread"])
    lines = [f"회차 {h['rounds']}번의 단계별 초(최소 · 중앙값 · 최대 · 폭) — 폭이 큰 단계는 날마다 다르다:"]
    lines += [f"  {n:16} n={v['n']} 최소 {v['min']:7.1f} 중앙 {v['median']:7.1f} 최대 {v['max']:7.1f} 폭 {v['spread']:7.1f}" for n, v in rows[:14]]
    if h["rounds"] < 5:
        lines.append(f"⚠ 회차가 {h['rounds']}번뿐이라 평균을 믿기 이르다(5번 이상 쌓인 뒤 겹치기 · 증분의 이득을 판단한다)")
    return "\n".join(lines)


def render(rep: dict) -> str:
    t = rep["total_seconds"]
    lines = [f"회차 {rep['steps']}단계 · 합 {t:,.0f}초({t / 60:.1f}분) · 큰 일곱 단계 {rep['top7_share']:.0%}", "", "묶음별 초:"]
    lines += [f"  {g:8} {v:8,.0f}초 {v / t:5.0%}" for g, v in sorted(rep["groups"].items(), key=lambda kv: -kv[1])]
    lines += ["", "큰 단계:"] + [f"  {r['seconds']:8,.0f}초 {r['share']:5.0%}  {r['name']}" for r in rep["top"]]
    lines += ["", "겹쳐 돌렸을 때 어림(의존 = 설계 3절 가설):"]
    base = rep["scenarios"]["지금(순차 · 일꾼 1)"]
    lines += [f"  {k:34} {v:8,.0f}초({v / 60:5.1f}분)  {(base - v) / base:5.0%} 절감" for k, v in rep["scenarios"].items()]
    lines += ["", "의존 하한 사슬: " + " → ".join(rep["critical_path"]["path"])]
    if rep["unmodeled_steps"]:
        lines.append("⚠️ 의존 모델에 없는 단계(시나리오에서 뺌): " + ", ".join(rep["unmodeled_steps"]))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="수집 회차 프로파일(읽기 전용)")
    ap.add_argument("--file", type=Path, default=STATE_LAST)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--history", action="store_true", help="회차 이력의 단계별 분포(최소 · 중앙값 · 최대) — 한 회차로 정하지 않게")
    args = ap.parse_args(argv)
    if args.history:
        h = history_stats()
        print(json.dumps(h, ensure_ascii=False, indent=1) if args.json else render_history(h))
        return 0
    bad = check_model()
    if bad:
        print("⚠️ 의존 모델 오류: " + " / ".join(bad), file=sys.stderr)
        return 2
    try:
        steps = load_steps(args.file)
    except (OSError, ValueError) as e:
        print(f"회차 기록을 읽지 못했다: {args.file} — {e}", file=sys.stderr)
        return 1
    rep = report(steps, groups())
    print(json.dumps(rep, ensure_ascii=False, indent=1) if args.json else render(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
