"""사용법 영상 — 녹화 결과를 앱이 내보내는 로컬 폴더(data/help/)로 옮기고 영상 표(videos.json)를 만든다.

쓰는 법 (저장소 뿌리에서 · 앱이 켜져 있어도 된다)
  python tools/demo/help_videos.py build      # 녹화한 PC — tools/demo/out/ 의 녹화 결과로
  python tools/demo/help_videos.py pull       # 다른 PC — HF 비공개 qurious-quant/demo-videos 에서 받아서
  python tools/demo/help_videos.py status     # data/help/ 에 무엇이 있나
  python tools/demo/help_videos.py clear      # data/help/ 를 지운다(앱의 영상 칸 · 단추가 모두 숨는다)

결정 D132(2026-10-18 · 정할것-대장 3절)
  - 앱 안 영상의 원천은 로컬 폴더 — git · 도커 이미지 밖. compose 가 호스트 ./data 를 앱 컨테이너 /app/data/csv 에
    읽기 전용으로 이미 붙여 두어 data/help/ 가 그대로 보인다(compose 를 고치지 않는다).
    앱은 로그인한 사람에게 /help/… 로 낸다(app/routes/help_media.py).
  - 파일이 없으면 영상 표도 없어 화면의 영상 칸 · 단추가 숨는다(결정 ⑥).
  - 여러 화면에 걸친 영상은 그 화면이 처음 나오는 장부터(차트 패턴 = 신호로 종목 살피기 ② 0:15) · 처음부터는 장 단추 ①.
  - 영상 표는 손으로 쓰지 않는다 — 녹화 기록(.json)의 단계별 시각 · go 화면 키와 장 파일(.chapters.vtt)에서 만든다.
    화면 키가 없는 옛 녹화 기록은 장면 파일과 단계 차례 · 종류가 같을 때만 장면 파일의 go 를 쓴다(다르면 첫 화면만).

영상 표 꼴 — 화면(public/js/howtoview.js 의 videoOf)이 읽는다
  {"format": 1, "built_at": "…", "source": "out" | "hf",
   "videos": {"<이름>": {"title", "src", "captions", "chapters_src", "duration", "recorded_at", "app_commit",
                        "chapters": [{"title", "start", "end", "poster"}]}},
   "views": {"<화면 키>": {"video": "<이름>", "chapter": <장 차례 0 부터>}}}
  - 주소는 /help/media/<이름>.<꼴>?v=<내용 지문 12자> — 다시 녹화하면 주소가 바뀌어 브라우저가 옛 파일을 쓰지 않는다.
  - 한 화면이 여러 영상에 나오면: 그 화면에서 시작하는 영상 → 여정 영상(V) → 기능 영상(F) → 이름 차례.

읽기 토큰(pull): 환경 변수 또는 저장소 뿌리 .env 의 HUGGINGFACE_READ_TOKEN(없으면 HUGGINGFACE_ACCESS_TOKEN) —
받는 그 순간에만 쓰고 어디에도 남기지 않는다 · 값은 찍지 않는다 · HF 조직(qurious-quant) 회원이어야 받힌다.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, unquote

import yaml

for _s in (sys.stdout, sys.stderr):
  try:
    _s.reconfigure(encoding="utf-8", errors="replace")
  except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent / "out"
SCENE_DIR = ROOT / "docs" / "영상" / "장면"
DEST = ROOT / "data" / "help"
MANIFEST_NAME = "videos.json"
URL_BASE = "/help/media/"
REPO = "qurious-quant/demo-videos"
KST = timezone(timedelta(hours=9))
FORMAT = 1
MEDIA_SUFFIXES = (".webm", ".vtt", ".jpg")

#: 화면에 나가는 글(장 제목 · 영상 제목)에 쓰지 않는 말 — 개발 티(편 번호 · 파일 이름 · 작업 낱말)
FORBIDDEN_WORDS = ("장면", "HF", "시연 계정", "준비 중", ".webm", ".vtt", ".json")
FORBIDDEN_CODE = re.compile(r"(?<![A-Za-z0-9])[VF]\d{2}(?![0-9])")     # 편 번호 V01 · F03

_VTT_CUE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2})\.(\d{3})")


def parse_vtt(text):
  """WebVTT → [(시작 초, 끝 초, 글)] — 녹화기가 쓰는 꼴(빈 줄로 나뉜 「시각 줄 + 글 한 줄」)."""
  cues, lines = [], text.replace("\r\n", "\n").split("\n")
  for i, line in enumerate(lines):
    m = _VTT_CUE.match(line.strip())
    if not m:
      continue
    g = [int(x) for x in m.groups()]
    a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
    b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
    body = []
    for nxt in lines[i + 1:]:
      if not nxt.strip():
        break
      body.append(nxt.strip())
    cues.append((round(a, 3), round(b, 3), " ".join(body)))
  return cues


def content_tag(path):
  h = hashlib.sha256()
  with open(path, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
      h.update(chunk)
  return h.hexdigest()[:12]


def url_of(path):
  return f"{URL_BASE}{quote(path.name)}?v={content_tag(path)}"


def bad_words(text):
  """화면 글에 들어가면 안 되는 말 목록(없으면 빈 목록)."""
  found = [w for w in FORBIDDEN_WORDS if w in text]
  found += FORBIDDEN_CODE.findall(text)
  return found


def order_key(name):
  """여정 영상(V) → 기능 영상(F) → 그 밖, 같은 묶음은 이름 차례."""
  head = name[:1]
  return ({"V": 0, "F": 1}.get(head, 2), name)


def chapter_at(chapters, t):
  """시각 t 가 든 장 차례 — 장 시작이 t 보다 늦지 않은 마지막 장(장 사이 틈은 앞 장)."""
  idx = 0
  for k, ch in enumerate(chapters):
    if ch["start"] <= t + 0.01:
      idx = k
  return idx


def scene_views(meta, scene_dir):
  """화면 키가 없는 옛 녹화 기록 — 장면 파일의 go 를 단계 차례로 붙인다.

  녹화 뒤 장면 파일이 바뀌었으면(단계를 끼움 · 뺌) 차례 · 종류가 처음 어긋나는 단계 앞까지만 쓴다 — 그 앞의 go 는
  녹화 기록의 시각과 장면 파일의 화면 키가 같은 단계를 가리키므로 맞다. 어긋난 단계 수를 「same」 에 돌려준다."""
  path = scene_dir / f"{meta.get('file', '')}.yaml"
  if not path.exists():
    return None
  scene = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
  steps = scene.get("steps") or []
  log = meta.get("steps") or []
  out, same = [], 0
  for entry, step in zip(log, steps):
    kind = next(iter(step)) if isinstance(step, dict) and len(step) == 1 else None
    if kind != entry.get("step"):
      break
    same += 1
    if kind == "go":
      g = step["go"]
      out.append((g if isinstance(g, str) else g.get("view"), float(entry.get("t", 0))))
  return {"start": scene.get("start", "dashboard"), "title": scene.get("title", ""), "go": out,
          "same": same, "total": len(log)}


def read_recording(src, name, scene_dir, problems):
  """한 편의 녹화 결과를 읽어 표 한 줄과 옮길 파일을 돌려준다. 쓸 수 없으면 None(까닭은 problems 에)."""
  meta_path, webm = src / f"{name}.json", src / f"{name}.webm"
  if not meta_path.exists():
    problems.append(f"{name}: 녹화 기록(.json)이 없습니다")
    return None
  meta = json.loads(meta_path.read_text(encoding="utf-8"))
  if not meta.get("ok", False):
    problems.append(f"{name}: 녹화가 중간에 멈춘 판입니다(ok=false) — 다시 찍으세요")
    return None
  if not webm.exists():
    problems.append(f"{name}: 영상 파일(.webm)이 없습니다")
    return None
  chap_path, cap_path = src / f"{name}.chapters.vtt", src / f"{name}.ko.vtt"
  if not chap_path.exists():
    problems.append(f"{name}: 장 파일(.chapters.vtt)이 없습니다")
    return None
  cues = parse_vtt(chap_path.read_text(encoding="utf-8"))
  if not cues:
    problems.append(f"{name}: 장 파일에 장이 없습니다")
    return None
  posters = sorted(src.glob(f"{name}.ch*.jpg"), key=lambda p: int(re.search(r"\.ch(\d+)\.jpg$", p.name).group(1)))
  files = [webm] + [p for p in (cap_path, chap_path) if p.exists()] + posters
  chapters = []
  for k, (a, b, title) in enumerate(cues):
    poster = src / f"{name}.ch{k + 1}.jpg"
    chapters.append({"title": title, "start": a, "end": b, "poster": url_of(poster) if poster.exists() else ""})

  if any("view" in s for s in meta.get("steps") or []) or meta.get("start"):
    start = meta.get("start") or "dashboard"
    title = meta.get("title") or ""
    gos = [(s["view"], float(s.get("t", 0))) for s in meta.get("steps") or [] if s.get("step") == "go" and s.get("view")]
  else:
    old = scene_views(meta, scene_dir)
    if old is None:
      problems.append(f"{name}: 옛 녹화 기록인데 장면 파일이 없어 화면을 이을 수 없습니다(다시 찍으면 풀림)")
      return None
    start, title, gos = old["start"], old["title"], old["go"]
    if old["same"] < old["total"]:
      problems.append(f"{name}: 옛 녹화 기록 — 장면 파일이 녹화 뒤 바뀌어 {old['same'] + 1}번째 단계부터 달라 그 앞 화면만 잇습니다(다시 찍으면 풀림)")

  words = sorted({w for ch in chapters for w in bad_words(ch["title"])} | set(bad_words(title)))
  if words:
    problems.append(f"{name}: 화면에 나갈 장 · 영상 제목에 쓰지 않는 말 {words} — 장면 파일의 title · chapter title 을 고치세요")
    return None

  appear = [(start, 0.0)] + gos
  first = {}
  for view, t in appear:
    if view and view not in first:
      first[view] = chapter_at(chapters, t)
  duration = float(meta.get("duration_sec") or cues[-1][1])
  row = {
    "title": title,
    "src": url_of(webm),
    "captions": url_of(cap_path) if cap_path.exists() else "",
    "chapters_src": url_of(chap_path),
    "duration": round(duration, 2),
    "recorded_at": meta.get("recorded_at", ""),
    "app_commit": meta.get("app_commit", ""),
    "chapters": chapters,
  }
  return {"name": name, "row": row, "files": files, "views": first, "start": start}


def build_manifest(src, *, source, scene_dir=SCENE_DIR):
  """녹화 결과 폴더 → (영상 표, 옮길 파일, 문제 목록). 화면 하나는 영상 하나에만 잇는다."""
  problems, recs = [], []
  for meta_path in sorted(src.glob("*.json"), key=lambda p: order_key(p.stem)):
    rec = read_recording(src, meta_path.stem, scene_dir, problems)
    if rec:
      recs.append(rec)
  views = {}
  # 그 화면에서 시작하는 영상이 먼저 — 나머지는 여정(V) → 기능(F) → 이름 차례
  for prefer_start in (True, False):
    for rec in recs:
      for view, chap in rec["views"].items():
        if view in views or (view == rec["start"]) != prefer_start:
          continue
        views[view] = {"video": rec["name"], "chapter": chap}
  manifest = {
    "format": FORMAT,
    "built_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST"),
    "source": source,
    "videos": {rec["name"]: rec["row"] for rec in recs},
    "views": dict(sorted(views.items())),
  }
  files = [f for rec in recs for f in rec["files"]]
  return manifest, files, problems


def install(manifest, files, dest=DEST):
  """파일을 dest/media/ 로 옮기고(바뀐 것만) 영상 표를 마지막에 바꿔 쓴 뒤, 표에 없는 옛 파일을 지운다."""
  media = dest / "media"
  media.mkdir(parents=True, exist_ok=True)
  copied = 0
  for f in files:
    to = media / f.name
    s = f.stat()
    if to.exists():
      t = to.stat()
      if t.st_size == s.st_size and int(t.st_mtime) == int(s.st_mtime):
        continue
    shutil.copy2(f, to)
    copied += 1
  tmp = dest / (MANIFEST_NAME + ".tmp")
  tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
  os.replace(tmp, dest / MANIFEST_NAME)                # 화면은 늘 다 옮긴 뒤의 표만 본다
  keep = {f.name for f in files}
  removed = 0
  for old in media.iterdir():
    if old.is_file() and old.suffix.lower() in MEDIA_SUFFIXES and old.name not in keep:
      old.unlink()
      removed += 1
  return copied, removed


def summary(manifest):
  vids = manifest.get("videos", {})
  lines = [f"영상 {len(vids)}편 · 화면 {len(manifest.get('views', {}))}곳 · 만든 때 {manifest.get('built_at', '')} · 원천 {manifest.get('source', '')}"]
  for view, ref in manifest.get("views", {}).items():
    v = vids.get(ref["video"], {})
    chs = v.get("chapters", [])
    k = ref["chapter"]
    at = chs[k]["start"] if k < len(chs) else 0
    lines.append(f"  {view:<22} → {ref['video']} · 장 {k + 1}/{len(chs)} · {int(at // 60)}:{int(at % 60):02d} 부터")
  return "\n".join(lines)


def read_token():
  names = ("HUGGINGFACE_READ_TOKEN", "HUGGINGFACE_ACCESS_TOKEN")
  for n in names:
    if os.environ.get(n):
      return os.environ[n]
  env = ROOT / ".env"
  if env.exists():
    found = {}
    for line in env.read_text(encoding="utf-8").splitlines():
      k, sep, v = line.partition("=")
      if sep and k.strip() in names:
        found[k.strip()] = v.strip().strip('"').strip("'")
    for n in names:
      if found.get(n):
        return found[n]
  raise SystemExit("HF 읽기 토큰이 없습니다 — .env 에 HUGGINGFACE_READ_TOKEN 을 넣으세요(값은 화면에 찍지 마세요)")


def shown(dest):
  """보고에 쓸 폴더 이름 — 저장소 안이면 상대 경로."""
  try:
    return dest.resolve().relative_to(ROOT).as_posix() + "/"
  except ValueError:
    return str(dest)


def finish(manifest, files, problems, dest):
  for p in problems:
    print("  ⚠️", p)
  where = shown(dest)
  if not manifest["videos"]:
    print(f"❌ 옮길 영상이 없습니다 — {where} 는 그대로 둡니다")
    return 1
  bad = [p for p in problems if "쓰지 않는 말" in p]
  if bad:
    print(f"❌ 화면 글 점검에 걸려 멈춥니다 — {where} 는 그대로 둡니다")
    return 1
  copied, removed = install(manifest, files, dest)
  size = sum((dest / "media" / f.name).stat().st_size for f in files)
  print(f"✅ {where} — 파일 {len(files)}개({size / 1e6:.1f} MB · 새로 옮김 {copied} · 지움 {removed})")
  print(summary(manifest))
  print("앱에서 보기: 그 화면의 「사용법」 → 「영상으로 보기」(브라우저는 새로 고침)")
  return 0


def cmd_build(args):
  src = Path(args.src)
  if not src.is_dir():
    raise SystemExit(f"녹화 결과 폴더가 없습니다 — {src} (녹화한 PC 가 아니면 pull)")
  manifest, files, problems = build_manifest(src, source="out")
  return finish(manifest, files, problems, Path(args.dest))


def cmd_pull(args):
  from huggingface_hub import snapshot_download
  tok = read_token()
  stage = Path(tempfile.mkdtemp(prefix="help-videos-"))
  try:
    print(f"받는 중 — {args.repo}(비공개) videos/ …")
    snapshot_download(repo_id=args.repo, repo_type="dataset", allow_patterns=["videos/*"], local_dir=str(stage), token=tok)
    del tok
    manifest, files, problems = build_manifest(stage / "videos", source="hf")
    return finish(manifest, files, problems, Path(args.dest))
  finally:
    shutil.rmtree(stage, ignore_errors=True)


def cmd_status(args):
  dest = Path(args.dest)
  path = dest / MANIFEST_NAME
  if not path.exists():
    print(f"영상 표가 없습니다({path}) — 앱의 영상 칸 · 단추는 숨습니다. 녹화한 PC 는 build · 다른 PC 는 pull")
    return 0
  manifest = json.loads(path.read_text(encoding="utf-8"))
  print(summary(manifest))
  missing = []
  for name, v in manifest.get("videos", {}).items():
    urls = [v.get("src"), v.get("captions"), v.get("chapters_src")] + [c.get("poster") for c in v.get("chapters", [])]
    for u in filter(None, urls):
      if not (dest / "media" / unquote(u.split("?")[0].rsplit("/", 1)[-1])).exists():
        missing.append(f"{name}: {unquote(u.split('?')[0].rsplit('/', 1)[-1])}")
  print("빠진 파일 없음" if not missing else f"⚠️ 빠진 파일 {len(missing)} — {missing[:5]}")
  return 1 if missing else 0


def cmd_clear(args):
  dest = Path(args.dest)
  if not dest.exists():
    print("이미 비어 있습니다")
    return 0
  (dest / MANIFEST_NAME).unlink(missing_ok=True)       # 표를 먼저 지워 화면이 바로 칸을 숨기게
  shutil.rmtree(dest, ignore_errors=True)
  print("✅ data/help/ 를 지웠습니다 — 앱의 영상 칸 · 단추가 숨습니다")
  return 0


def main():
  ap = argparse.ArgumentParser(description="사용법 영상을 앱이 내보내는 로컬 폴더(data/help/)로 옮기고 영상 표를 만든다")
  sub = ap.add_subparsers(dest="cmd", required=True)
  b = sub.add_parser("build", help="녹화한 PC — tools/demo/out/ 의 녹화 결과로")
  b.add_argument("--src", default=str(OUT_DIR))
  p = sub.add_parser("pull", help="다른 PC — HF 비공개 데이터셋에서 받아서")
  p.add_argument("--repo", default=REPO)
  sub.add_parser("status", help="data/help/ 에 무엇이 있나")
  sub.add_parser("clear", help="data/help/ 를 지운다")
  for sp in sub.choices.values():
    sp.add_argument("--dest", default=str(DEST))
  args = ap.parse_args()
  return {"build": cmd_build, "pull": cmd_pull, "status": cmd_status, "clear": cmd_clear}[args.cmd](args)


if __name__ == "__main__":
  sys.exit(main())
