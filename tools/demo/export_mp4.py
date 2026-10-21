"""녹화한 영상을 mp4 로 내보낸다 — 발표 자료가 바로 재생하게(2026-10-19 사용자 결정 · 2026-10-20 부터 파일도 git 에 — 팀원이 받아 재생).

쓰는 법 (저장소 뿌리에서 · 녹화한 PC)
  python tools/demo/export_mp4.py            # 새로 찍었거나 빠진 편만 내보냄(사용법 · 발표 둘 다)
  python tools/demo/export_mp4.py --check    # 쓰지 않고 편마다 상태만(내보냄 · 내보낼 것 · 장면이 바뀜 · 녹화 없음)
  python tools/demo/export_mp4.py --only P-V04-모의주문-국내미국   # 한 편만
  python tools/demo/export_mp4.py --readme   # 영상 README 의 파일 표를 목록.json 으로 다시 채움

나오는 것
  docs/영상/파일/사용법/<장면 이름>.mp4 · .jpg(첫 장 제목 카드 — 재생 전 그림)   ← git 에 커밋(2026-10-20)
  docs/영상/파일/발표/<장면 이름>.mp4 · .jpg                                        ← git 에 커밋(2026-10-20)
  docs/영상/파일/목록.json — 편마다 장면 · 제목 · 길이 · 크기 · 녹화 시각 · 앱 커밋 · 원본 · 결과 지문  ← git 에 넣는다

왜 이렇게 만들었나
- 영상에는 공식 자료 화면(금융위원회 시세 · 야후 · OpenDART · 용어 풀이)이 찍혀 있다 — 출처 대장(docs/3차/데이터/대장/자료안내-출처.tsv)의
  이용 조건(다시 나눠 주지 않음 · 비공개로만)대로 공개 저장소에 두지 않는다(2026-10-19 사용자 결정). 발표 PC 가 이 도구로 만들어 두면
  발표 자료 HTML · 기본 재생기가 파일을 바로 연다(인터넷 없이도) · 팀원은 HF 비공개 데이터셋에서 받는다.
- GitHub 저장소 화면은 어차피 영상을 재생하지 않는다(공식 문서 「Working with non-code files」 의 렌더 목록에 영상이 없다).
- H.264(mp4)는 브라우저 · 운영체제 기본 재생기가 모두 연다(GitHub 문서도 H.264 를 권한다) ·
  녹화기의 VP8 webm 보다 4 ~ 5배 작다(2분 영상 28 MB → 5.5 MB · 1080p 그대로 · 글자 그대로 읽힘 — 2026-10-19 실측).
- 편마다 10 MB 안 — GitHub 무료 요금제의 영상 첨부 한도라, 같은 파일을 웹 첨부 · YouTube 로도 그대로 쓴다.
- 녹화 뒤 장면 파일이 바뀐 영상은 내보내지 않는다 — 옛 화면이 새 이름으로 섞이지 않게.
  새 녹화는 기록의 장면 지문(scene_sha)으로, 지문이 없는 옛 녹화는 자막 · 장 제목을 장면 파일과 맞대 본다.
- 녹화기(record_demo.py)는 Playwright 의 ffmpeg(VP8 만)을 쓴다 — 여기는 H.264 가 되는 ffmpeg 이 따로 필요하다.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

for _s in (sys.stdout, sys.stderr):
  try:
    _s.reconfigure(encoding="utf-8", errors="replace")
  except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
DEST = ROOT / "docs" / "영상" / "파일"
MANIFEST = DEST / "목록.json"
README = ROOT / "docs" / "영상" / "README.md"
# 갈래 — (이름, 장면 폴더, 녹화 결과 폴더, 내보낼 폴더)
KINDS = (
  ("사용법", ROOT / "docs" / "영상" / "장면", OUT, DEST / "사용법"),
  ("발표", ROOT / "docs" / "영상" / "발표", OUT / "present", DEST / "발표"),
)
SIZE_LIMIT = 10_000_000          # GitHub 무료 요금제 영상 첨부 한도(10 MB)보다 크지 않게
CRF_STEPS = (28, 31, 34)         # 한도를 넘으면 차례로 더 줄인다(28 에서 글자가 그대로 읽힘을 확인)
TABLE_START = "<!-- 영상파일표:시작 · tools/demo/export_mp4.py --readme 가 채움 -->"
TABLE_END = "<!-- 영상파일표:끝 -->"


def file_sha(path, n=16):
  h = hashlib.sha256()
  with open(path, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
      h.update(chunk)
  return h.hexdigest()[:n]


def scene_sha(path):
  """장면 파일 지문 — 줄 끝(CRLF · LF)을 접어서(autocrlf 작업 트리에서도 같은 값)."""
  return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:16]


def vtt_texts(path):
  """WebVTT 의 글 줄만 차례대로(시각 줄 · 머리 · 빈 줄은 뺀다)."""
  if not Path(path).exists():
    return []
  out, lines = [], Path(path).read_text(encoding="utf-8").splitlines()
  for i, ln in enumerate(lines):
    if "-->" in ln:
      j = i + 1
      buf = []
      while j < len(lines) and lines[j].strip():
        buf.append(lines[j].strip())
        j += 1
      out.append(" ".join(buf))
  return out


def scene_texts(scene):
  """장면의 자막(say) · 장 제목(chapter.title)을 차례대로 — 빈 자막은 뺀다."""
  says, chaps = [], []
  for st in scene.get("steps") or []:
    if not isinstance(st, dict) or len(st) != 1:
      continue
    kind, v = next(iter(st.items()))
    if kind == "say":
      t = v if isinstance(v, str) else (v or {}).get("text", "")
      if t:
        says.append(t)
    elif kind == "chapter":
      chaps.append((v or {}).get("title", ""))
  return says, chaps


def recording_matches(scene, scene_bytes_sha, rec, sub_texts, chap_texts):
  """이 녹화가 지금 장면 파일로 찍은 것인가 — (맞음, 까닭)."""
  if not rec.get("ok"):
    return False, f"녹화 실패 — {rec.get('failed_at') or '까닭 없음'}"
  if rec.get("scene_sha"):
    if rec["scene_sha"] == scene_bytes_sha:
      return True, "장면 지문 같음"
    return False, "장면이 녹화 뒤 바뀜(지문 다름)"
  says, chaps = scene_texts(scene)
  if says != sub_texts:
    return False, f"장면이 녹화 뒤 바뀜(자막 {len(says)}줄 · 녹화 {len(sub_texts)}줄 중 다른 줄 있음)"
  if [c for c in chaps if c] != [c for c in chap_texts if c]:
    return False, "장면이 녹화 뒤 바뀜(장 제목 다름)"
  return True, "지문 없는 옛 녹화 — 자막 · 장 제목이 장면과 같음"


def entries():
  """장면 파일마다 (갈래, 장면 경로, 이름, 녹화 이름, 원본 webm, 기록 json, 내보낼 mp4)."""
  rows = []
  for kind, scene_dir, rec_dir, dest_dir in KINDS:
    for yml in sorted(scene_dir.glob("*.yaml")):
      scene = yaml.safe_load(yml.read_text(encoding="utf-8"))
      name = scene["file"]
      rows.append({
        "kind": kind, "yaml": yml, "stem": yml.stem, "scene": scene, "rec_name": name,
        "webm": rec_dir / f"{name}.webm", "json": rec_dir / f"{name}.json",
        "subs": rec_dir / f"{name}.ko.vtt", "chaps": rec_dir / f"{name}.chapters.vtt",
        "poster": rec_dir / f"{name}.ch1.jpg",
        "mp4": dest_dir / f"{yml.stem}.mp4", "jpg": dest_dir / f"{yml.stem}.jpg",
      })
  return rows


def load_manifest():
  if MANIFEST.exists():
    return {(e["kind"], e["stem"]): e for e in json.loads(MANIFEST.read_text(encoding="utf-8"))["videos"]}
  return {}


def save_manifest(items):
  videos = sorted(items.values(), key=lambda e: (e["kind"] != "사용법", e["stem"]))
  body = {"about": "발표 자료가 재생하는 시연 영상 목록(mp4 · 그림도 git 에 — 2026-10-20) — tools/demo/export_mp4.py 가 쓴다(손으로 고치지 않는다)", "videos": videos}
  MANIFEST.parent.mkdir(parents=True, exist_ok=True)
  MANIFEST.write_bytes((json.dumps(body, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def status(row, manifest):
  """(상태 낱말, 까닭) — 내보냄 · 내보낼 것 · 장면이 바뀜 · 녹화 없음."""
  if not row["webm"].exists() or not row["json"].exists():
    return "녹화 없음", f"{row['webm'].relative_to(ROOT).as_posix()} 가 없다"
  rec = json.loads(row["json"].read_text(encoding="utf-8"))
  ok, why = recording_matches(row["scene"], scene_sha(row["yaml"]), rec, vtt_texts(row["subs"]), vtt_texts(row["chaps"]))
  if not ok:
    return "장면이 바뀜", why
  have = manifest.get((row["kind"], row["stem"]))
  src = file_sha(row["webm"])
  if have and have.get("source_sha") == src and row["mp4"].exists() and file_sha(row["mp4"]) == have.get("sha"):
    return "내보냄", "원본 · 결과 지문이 목록과 같음"
  return "내보낼 것", why


def find_h264_ffmpeg():
  cands = []
  if os.environ.get("QURIOUS_FFMPEG"):
    cands.append(os.environ["QURIOUS_FFMPEG"])
  try:
    import imageio_ffmpeg  # noqa: 받아 둔 사람만 — pip install imageio-ffmpeg
    cands.append(imageio_ffmpeg.get_ffmpeg_exe())
  except Exception:
    pass
  if shutil.which("ffmpeg"):
    cands.append(shutil.which("ffmpeg"))
  for c in cands:
    try:
      r = subprocess.run([c, "-hide_banner", "-encoders"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except Exception:
      continue
    if "libx264" in r.stdout:
      return c
  raise SystemExit("H.264 인코더(libx264)가 든 ffmpeg 를 찾지 못했습니다 — `python -m pip install imageio-ffmpeg` 를 한 번 돌리거나"
                   " 환경 변수 QURIOUS_FFMPEG 에 ffmpeg.exe 경로를 넣으세요(Playwright 의 ffmpeg 은 VP8 만 됩니다)")


def encode(ff, src, dst, crf):
  tmp = dst.with_suffix(".part.mp4")
  cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
         "-c:v", "libx264", "-preset", "slow", "-tune", "stillimage", "-crf", str(crf), "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", "-an", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", str(tmp)]
  r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
  if r.returncode != 0 or not tmp.exists():
    tmp.unlink(missing_ok=True)
    raise SystemExit(f"인코딩 실패 — {src.name}: {r.stderr.strip()[:300]}")
  tmp.replace(dst)
  return dst.stat().st_size


def export(row, ff, manifest):
  rec = json.loads(row["json"].read_text(encoding="utf-8"))
  row["mp4"].parent.mkdir(parents=True, exist_ok=True)
  size = crf = None
  for crf in CRF_STEPS:
    size = encode(ff, row["webm"], row["mp4"], crf)
    if size <= SIZE_LIMIT:
      break
  if size > SIZE_LIMIT:
    row["mp4"].unlink(missing_ok=True)
    raise SystemExit(f"⛔ {row['stem']} — CRF {CRF_STEPS[-1]} 에서도 {size:,} 바이트(한도 {SIZE_LIMIT:,}) · 장면을 나누거나 줄이세요")
  if row["poster"].exists():
    shutil.copyfile(row["poster"], row["jpg"])
  manifest[(row["kind"], row["stem"])] = {
    "kind": row["kind"], "stem": row["stem"], "title": row["scene"].get("title", ""),
    "scene": row["yaml"].relative_to(ROOT).as_posix(), "mp4": row["mp4"].relative_to(ROOT).as_posix(),
    "jpg": row["jpg"].relative_to(ROOT).as_posix() if row["jpg"].exists() else None,
    "duration_sec": rec.get("duration_sec"), "bytes": size, "crf": crf, "sha": file_sha(row["mp4"]),
    "source_sha": file_sha(row["webm"]), "scene_sha": rec.get("scene_sha"),
    "recorded_at": rec.get("recorded_at"), "app_commit": rec.get("app_commit"),
  }
  return size, crf


def mmss(sec):
  sec = int(round(sec or 0))
  return f"{sec // 60}:{sec % 60:02d}"


def readme_table(manifest):
  """편 하나 = 한 줄 · 사용법 · 발표 두 칸 — 링크는 두지 않는다(파일은 git 밖 · 공개 저장소에서는 깨진 링크가 된다)."""
  by_code = {}
  for e in manifest.values():
    code = e["stem"].removeprefix("P-").split("-")[0]           # V01 · F06
    by_code.setdefault(code, {})[e["kind"]] = e

  def cell(e):
    if not e:
      return "—"
    return f"{mmss(e['duration_sec'])} · {e['bytes'] / 1_000_000:.1f} MB"

  lines = [TABLE_START, "", "| 편 | 제목 | 사용법 영상 | 발표 영상 | 녹화 |", "|---|---|---|---|---|"]
  order = sorted(by_code, key=lambda c: (c[0] != "V", c))
  for code in order:
    pair = by_code[code]
    head = pair.get("발표") or pair.get("사용법")
    when = max((x.get("recorded_at") or "")[:10] for x in pair.values())
    lines.append(f"| {code} | {head['title']} | {cell(pair.get('사용법'))} | {cell(pair.get('발표'))} | {when} |")
  lines += ["", TABLE_END]
  return "\n".join(lines)


def write_readme(manifest):
  text = README.read_bytes().decode("utf-8")
  nl = "\r\n" if "\r\n" in text else "\n"
  if TABLE_START not in text or TABLE_END not in text:
    raise SystemExit(f"README 에 표 자리 표시가 없습니다 — 「{TABLE_START}」 와 「{TABLE_END}」 두 줄을 먼저 넣으세요")
  a = text.index(TABLE_START)
  b = text.index(TABLE_END) + len(TABLE_END)
  new = text[:a] + readme_table(manifest).replace("\n", nl) + text[b:]
  if new == text:
    print("README 파일 표 — 바뀐 것 없음")
    return False
  README.write_bytes(new.encode("utf-8"))
  print("README 파일 표를 다시 채웠습니다")
  return True


def main():
  ap = argparse.ArgumentParser(description="녹화한 영상 → 발표 자료가 재생할 H.264 mp4 (docs/영상/파일/ · git 밖)")
  ap.add_argument("--check", action="store_true", help="쓰지 않고 편마다 상태만")
  ap.add_argument("--only", action="append", default=[], help="이 장면 이름만(여러 번 줄 수 있음)")
  ap.add_argument("--readme", action="store_true", help="영상 README 의 파일 표만 목록.json 으로 다시 채움")
  args = ap.parse_args()

  manifest = load_manifest()
  if args.readme:
    write_readme(manifest)
    return 0
  rows = [r for r in entries() if not args.only or r["stem"] in args.only]
  if args.only and len(rows) != len(set(args.only)):
    raise SystemExit(f"없는 장면 이름: {sorted(set(args.only) - {r['stem'] for r in rows})}")
  plan = [(r, *status(r, manifest)) for r in rows]
  todo = [p for p in plan if p[1] == "내보낼 것"]
  for r, st, why in plan:
    mark = {"내보냄": "✅", "내보낼 것": "🆕", "장면이 바뀜": "⚠️", "녹화 없음": "·"}[st]
    print(f"{mark} {r['kind']:<3} {r['stem']:<32} {st} — {why}")
  if args.check or not todo:
    print(f"내보낼 것 {len(todo)}편" + (" · --check 라 쓰지 않음" if args.check and todo else ""))
    return 0
  ff = find_h264_ffmpeg()
  for r, _, _ in todo:
    size, crf = export(r, ff, manifest)
    save_manifest(manifest)                       # 한 편마다 — 도중에 멈춰도 끝낸 편은 남는다
    print(f"  → {r['mp4'].relative_to(ROOT).as_posix()} · {size / 1_000_000:.1f} MB · CRF {crf}")
  print(f"내보냄 {len(todo)}편 · 목록 {MANIFEST.relative_to(ROOT).as_posix()}")
  return 0


if __name__ == "__main__":
  sys.exit(main())
