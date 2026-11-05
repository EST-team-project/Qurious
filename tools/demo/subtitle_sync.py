"""자막(say)과 화면 동작의 어긋남을 점검 · 고친다(2026-11-05 사용자 「영상 재생 · 안내에 비해 자막이 밀리는 느낌」).

왜 밀리나:
  ① **순서** — 장면 파일에 「동작 → say」 로 쓰면 자막이 그 동작이 끝난 뒤에 뜬다(click · ring 은 1~3초 걸린다). say 는 기다리지 않으므로
     「say → 동작」 으로 써야 자막이 동작과 같이 뜬다.
  ② **노출 시간** — 자막은 다음 say(또는 장 제목)까지 떠 있다. 발표용 pace(빠르게)에서는 동작 사이 멈춤이 줄어 글을 읽기 전에 바뀐다.

무엇을 하나:
  python tools/demo/subtitle_sync.py check [장면.yaml …]     # 순서(동작 바로 뒤의 say) · 녹화 기록이 있으면 노출 시간 · 읽는 데 모자란 시간
  python tools/demo/subtitle_sync.py fix   [장면.yaml …]     # 동작 뒤의 say 를 그 동작 앞으로 옮긴다(줄 단위 · 주석 보존 · 이미 say 가 앞선 동작은 안 옮김 — 결과를 눈으로 확인할 것)
  python tools/demo/subtitle_sync.py pad   [장면.yaml …]     # 녹화 기록(--no-video 도 됨)으로 모자란 노출 시간만큼 다음 say 앞에 pause 를 더한다

  장면 파일을 안 주면 docs/phase-3/06-retrospective/videos/{발표,장면}/ 전부. 기록은 tools/demo/out(사용법) · out/present(발표).
읽는 시간 기준: 발표용(pace ≥ 1) 한 글자 1/7 초 · 사용법(pace < 1) 1/5.5 초 · 최소 2.0 · 2.5 초.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
V3 = ROOT / "docs" / "phase-3" / "06-retrospective" / "videos"
OUT = Path(__file__).resolve().parent / "out"
ACTIONS = {"ring", "click", "scroll", "select", "hover", "key", "fill"}


def kind(step):
  return next(iter(step))


def read_scene(path: Path):
  """(머리 줄들, [(줄, 단계 사전)], 꼬리 줄들, 장면 사전) — 단계는 한 줄짜리 `  - 열쇠: 값` 만 다룬다."""
  lines = path.read_text(encoding="utf-8").split("\n")
  scene = yaml.safe_load("\n".join(lines))
  idx = [i for i, l in enumerate(lines) if l.startswith("  - ")]
  if not idx:
    raise SystemExit(f"단계가 없다: {path}")
  head, steps, tail = lines[: idx[0]], [], lines[idx[-1] + 1:]
  for i in idx:
    steps.append((lines[i], yaml.safe_load(lines[i].strip()[2:])))
  between = [lines[a + 1: b] for a, b in zip(idx, idx[1:])]
  if any(any(x.strip() for x in b) for b in between):
    raise SystemExit(f"단계 사이에 다른 줄(주석 등)이 있다 — 한 줄짜리 단계만 지원: {path}")
  return head, steps, tail, scene


def write_scene(path: Path, head, steps, tail):
  path.write_text("\n".join(head + [s[0] for s in steps] + tail), encoding="utf-8", newline="")


def reorder(steps):
  """say 를 바로 앞에 이어진 동작(ring · click · scroll …) 묶음 앞으로 옮긴다. wait · pause · chapter · 다른 say 는 넘지 않는다."""
  out = list(steps)
  moved = 0
  i = 0
  while i < len(out):
    if kind(out[i][1]) == "say":
      j = i
      while j - 1 >= 0 and kind(out[j - 1][1]) in ACTIONS:
        j -= 1
      if j < i and not (j - 1 >= 0 and kind(out[j - 1][1]) == "say"):   # 동작 묶음 바로 앞에 이미 say 가 있으면 그 say 의 것으로 본다
        out.insert(j, out.pop(i))
        moved += 1
    i += 1
  return out, moved


def record_json(scene_file: Path, scene):
  name = scene["file"]
  for d in (OUT / "present", OUT):
    p = d / f"{name}.json"
    if p.exists():
      if p.stat().st_mtime < scene_file.stat().st_mtime:     # 장면 파일을 고친 뒤에 만든 기록만 믿는다(옛 기록은 단계가 어긋난다)
        return None
      d = json.loads(p.read_text(encoding="utf-8"))
      if not d.get("webm_bytes"):                           # --no-video 로 만든 기록 — wait cut 구간(영상에서는 잘림)이 시간에 들어 있어 노출 시간이 부풀려진다
        print(f"  ⚠ {name}: 영상 없이 녹화한 기록이라 노출 시간을 믿지 않는다(실제 녹화로 다시 만들 것)", file=sys.stderr)
        return None
      return d
  return None


def need_sec(text: str, pace: float) -> float:
  per, floor = (7.0, 2.0) if pace >= 1 else (5.5, 2.5)
  return max(floor, len(text) / per)


def timing(steps, rec):
  """say 마다 (단계 번호, 글, 시작, 노출 시간). 노출 = 다음 say 또는 장 제목이 시작할 때까지(없으면 끝까지)."""
  rs = rec.get("steps") or []
  if len(rs) != len(steps):
    return None
  end = float(rec.get("duration_sec") or 0)
  out = []
  for i, (_, st) in enumerate(steps):
    if kind(st) != "say":
      continue
    t0 = float(rs[i]["t"])
    t1 = end
    for k in range(i + 1, len(rs)):
      if kind(steps[k][1]) in ("say", "chapter"):
        t1 = float(rs[k]["t"])
        break
    out.append((i, st["say"], t0, t1 - t0))
  return out


def cmd_check(files):
  bad = 0
  for f in files:
    head, steps, tail, scene = read_scene(f)
    pace = float(scene.get("pace", 1.0))
    late = [i for i, (_, st) in enumerate(steps) if kind(st) == "say" and i > 0 and kind(steps[i - 1][1]) in ACTIONS]
    rec = record_json(f, scene)
    tm = timing(steps, rec) if rec else None
    short = [(i, txt, d, need_sec(txt, pace)) for i, txt, _, d in (tm or []) if d + 0.05 < need_sec(txt, pace)]
    state = "✅" if not late and not short else "❌"
    print(f"{state} {f.stem}  · 자막 {sum(1 for _, s in steps if kind(s) == 'say')}줄 · pace {pace} · "
          f"동작 뒤 자막 {len(late)}곳 · " + (f"읽을 시간 모자람 {len(short)}곳" if tm else "녹화 기록 없음/단계 수 다름(노출 시간은 못 봄)"))
    for i in late:
      print(f"     순서: {i + 1}번째 단계 say 가 동작 바로 뒤 — 「{steps[i][1]['say'][:28]}…」")
    for i, txt, d, n in short:
      print(f"     짧음: 「{txt[:28]}…」 {d:.1f}초 노출 < 읽는 데 {n:.1f}초 필요(글자 {len(txt)})")
    bad += 1 if state == "❌" else 0
  print("결과:", "모두 통과" if not bad else f"{bad}개 장면 손봐야 함")
  return 1 if bad else 0


def cmd_fix(files):
  for f in files:
    head, steps, tail, scene = read_scene(f)
    new, moved = reorder(steps)
    if moved:
      write_scene(f, head, new, tail)
    print(f"{'✂' if moved else '·'} {f.stem} — 자막 {moved}곳을 동작 앞으로 옮김" if moved else f"· {f.stem} — 옮길 것 없음")
  return 0


def cmd_pad(files):
  for f in files:
    head, steps, tail, scene = read_scene(f)
    pace = float(scene.get("pace", 1.0))
    rec = record_json(f, scene)
    tm = timing(steps, rec) if rec else None
    if tm is None:
      print(f"· {f.stem} — 녹화 기록이 없거나 단계 수가 달라 못 함(먼저 --no-video 로 녹화 기록을 만든다)")
      continue
    # 모자란 만큼을 그 자막 구간의 끝(다음 say · chapter 바로 앞)에 pause 로 더한다 — 동작을 늦추지 않고 자막만 더 오래 둔다
    add = {}
    for i, txt, _t0, dwell in tm:                      # timing() 은 (단계, 글, 시작, 노출 시간) — 시작 시각을 노출 시간으로 잘못 받던 버그(2026-11-05)를 고침
      deficit = need_sec(txt, pace) - dwell
      if deficit > 12:                                    # 이렇게 크게 모자랄 리 없다 — 계산 · 기록이 어긋난 것이다(2026-11-05 pad 버그로 첫 pause 가 수백 초가 됐던 일)
        print(f"  ⚠ {f.stem}: 「{txt[:16]}…」 부족 {deficit:.1f}초는 이상하다 — 적용하지 않고 건너뛴다(기록 · 단계를 확인)")
        continue
      if deficit > 0.05:
        k = i + 1
        while k < len(steps) and kind(steps[k][1]) not in ("say", "chapter"):
          k += 1
        add[k] = add.get(k, 0) + deficit
    if not add:
      print(f"· {f.stem} — 노출 시간 충분")
      continue
    out = []
    for k, (line, st) in enumerate(steps):
      if k in add:
        sec = round(add[k] * pace + 0.05, 1)
        if out and kind(out[-1][1]) == "pause":          # 바로 앞이 pause 면 늘린다
          old = float(out[-1][1]["pause"])
          out[-1] = (f"  - pause: {round(old + sec, 1)}", {"pause": round(old + sec, 1)})
        else:
          out.append((f"  - pause: {max(sec, 1.5)}", {"pause": max(sec, 1.5)}))
      out.append((line, st))
    if len(steps) in add:                                 # 마지막 자막이 모자라면 끝에
      sec = round(add[len(steps)] * pace + 0.05, 1)
      out.append((f"  - pause: {max(sec, 1.5)}", {"pause": max(sec, 1.5)}))
    write_scene(f, head, out, tail)
    print(f"⏱ {f.stem} — pause {len(add)}곳 더함(합계 약 {sum(add.values()):.1f}초 · pace 보정 전)")
  return 0


def main():
  ap = argparse.ArgumentParser(description="자막 · 동작 어긋남 점검 · 수정")
  ap.add_argument("cmd", choices=("check", "fix", "pad"))
  ap.add_argument("files", nargs="*")
  a = ap.parse_args()
  files = [Path(x) for x in a.files] or sorted((V3 / "발표").glob("P-*.yaml")) + sorted((V3 / "장면").glob("V-*.yaml"))
  return {"check": cmd_check, "fix": cmd_fix, "pad": cmd_pad}[a.cmd](files)


if __name__ == "__main__":
  sys.exit(main())
