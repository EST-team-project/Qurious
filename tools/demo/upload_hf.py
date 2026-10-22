"""녹화한 시연 영상 · 자막 · 기록을 HF 조직의 비공개 데이터셋에 올린다.

쓰는 법 (저장소 뿌리에서)
  python tools/demo/upload_hf.py --dry-run          # 올릴 파일 · 크기만 본다
  python tools/demo/upload_hf.py                    # tools/demo/out/ 의 사용법 영상 전부 → videos/
  python tools/demo/upload_hf.py V07-근거상담        # 이름을 주면 그 편만
  python tools/demo/upload_hf.py --src tools/demo/out/present --prefix present   # 발표 영상(자세한 판) → present/
  사용법 영상(앱 사용법 창 · 짧은 편)과 발표 영상(기능마다 2 ~ 3분)은 나눠 둔다(사용자 2026-10-18) — 앱이 받는 것은 videos/ 뿐

- 데이터셋: qurious-quant/demo-videos (없으면 비공개로 만든다 · 이미 있는데 공개면 멈춘다)
- 올리는 것: videos/<이름>.webm · .ko.vtt(자막) · .chapters.vtt(장) · .ch<n>.jpg(장 제목 카드) · .json(녹화 기록) + README.md(목록)
  프레임 확인용 사진(<이름>-frames/)은 올리지 않는다. 다른 PC 는 tools/demo/help_videos.py pull 로 받아 사용법 창에서 본다.
- 토큰: 환경 변수 또는 저장소 뿌리 .env 의 HUGGINGFACE_ACCESS_TOKEN(쓰기 권한) — 값은 찍지 않는다.
- 같은 이름으로 다시 올리면 새 커밋이 되고 지난 판은 HF 이력에 남는다(강사님 「영상은 바뀌면 늘 최신화」).
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
  try:
    _s.reconfigure(encoding="utf-8", errors="replace")
  except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent / "out"
REPO = "qurious-quant/demo-videos"
KST = timezone(timedelta(hours=9))


def token():
  tok = os.environ.get("HUGGINGFACE_ACCESS_TOKEN")
  env = ROOT / ".env"
  if not tok and env.exists():
    for line in env.read_text(encoding="utf-8").splitlines():
      k, sep, v = line.partition("=")
      if sep and k.strip() == "HUGGINGFACE_ACCESS_TOKEN":
        tok = v.strip().strip('"').strip("'")
  if not tok:
    raise SystemExit("HUGGINGFACE_ACCESS_TOKEN 이 없습니다 — .env 에 쓰기 권한 토큰을 넣으세요(값은 화면에 찍지 마세요)")
  return tok


def card(metas):
  rows = "\n".join(
    f"| {'발표' if m.get('_folder') == 'present' else '사용법'} | {m['file']} | {m.get('duration_sec', 0):.0f}초 | {m.get('recorded_at', '')} | `{m.get('app_commit', '')}` | {m.get('cut_sec', 0)}초 |"
    for m in metas)
  return f"""---
license: other
pretty_name: Qurious 시연 영상
---

# Qurious 시연 영상 (비공개)

2차 로보 어드바이저 여정을 장면 파일(저장소 `docs/common/06-retrospective/videos/장면/*.yaml`)로 녹화한 영상이다.
녹화 도구는 저장소 `tools/demo/record_demo.py` · 화면이 바뀌면 그 장면만 다시 찍어 같은 이름으로 올린다(지난 판은 이 저장소 이력에 남는다).

- 사용법 영상(앱 사용법 창 · 짧은 편): `videos/` · 발표 영상(기능마다 2 ~ 3분 · 더 자세히): `present/` — 장면 파일은 저장소 `docs/common/06-retrospective/videos/장면/` · `docs/common/06-retrospective/videos/발표/`
- 영상: `<폴더>/<이름>.webm`(VP8 · 1920×1080 · 25fps · 소리 없음 · 자막은 화면에 들어 있다)
- 자막 · 장: `videos/<이름>.ko.vtt` · `videos/<이름>.chapters.vtt`(WebVTT — 도움말 쪽에서 쓴다)
- 녹화 기록: `videos/<이름>.json`(단계별 시각 · 줄인 기다림 · 콘솔 오류 수 · 앱 커밋)
- 시연 전용 로컬 계정 · 가상 돈 · 키 · 계좌번호 없음 · 투자 권유가 아닌 기능 시연

| 갈래 | 이름 | 길이 | 녹화 시각 | 앱 커밋 | 줄인 기다림 |
|---|---|---|---|---|---|
{rows}
"""


def main():
  ap = argparse.ArgumentParser(description="시연 영상을 HF 비공개 데이터셋에 올린다")
  ap.add_argument("names", nargs="*", help="올릴 영상 이름(없으면 전부)")
  ap.add_argument("--repo", default=REPO)
  ap.add_argument("--src", default=str(OUT_DIR), help="녹화 결과 폴더(발표 영상은 tools/demo/out/present)")
  ap.add_argument("--prefix", default="videos", choices=("videos", "present"), help="데이터셋 안 폴더 — 사용법 videos · 발표 present")
  ap.add_argument("--dry-run", action="store_true")
  args = ap.parse_args()

  src = Path(args.src)
  vids = sorted(src.glob("*.webm"))
  if args.names:
    vids = [v for v in vids if v.stem in set(args.names)]
  if not vids:
    raise SystemExit(f"올릴 영상이 없습니다 — {src} 를 보세요")
  files, metas = [], []
  for v in vids:
    meta = src / f"{v.stem}.json"
    m = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {"file": v.stem}
    if not m.get("ok", True):
      raise SystemExit(f"{v.stem} 은 녹화가 중간에 멈춘 판입니다(ok=false) — 다시 찍은 뒤 올리세요")
    metas.append(m)
    files += [p for p in (v, src / f"{v.stem}.ko.vtt", src / f"{v.stem}.chapters.vtt", meta) if p.exists()]
    files += sorted(src.glob(f"{v.stem}.ch*.jpg"))   # 장 제목 카드 그림 — 다른 PC 가 help_videos.py pull 로 받는다
  total = sum(p.stat().st_size for p in files)
  print(f"올릴 파일 {len(files)}개 · {total / 1e6:.1f} MB → {args.repo}/{args.prefix}/(비공개)")
  for p in files:
    print(f"  {args.prefix}/{p.name}  {p.stat().st_size / 1e6:.2f} MB")
  if args.dry_run:
    return 0

  from huggingface_hub import HfApi
  api = HfApi(token=token())
  api.create_repo(args.repo, repo_type="dataset", private=True, exist_ok=True)
  info = api.dataset_info(args.repo)
  if not info.private:
    raise SystemExit(f"멈춤 — {args.repo} 가 공개 저장소입니다. 비공개로 바꾼 뒤 다시 돌리세요(영상은 비공개로만 둔다)")
  stage = Path(tempfile.mkdtemp(prefix="demo-hf-"))
  try:
    (stage / args.prefix).mkdir()
    for p in files:
      shutil.copy(p, stage / args.prefix / p.name)
    for m in metas:
      m["_folder"] = args.prefix
    old = {}
    try:                                    # 이미 올라간 다른 영상의 표 줄은 지키기
      mine = {(args.prefix, m["file"]) for m in metas}
      for f in api.list_repo_files(args.repo, repo_type="dataset"):
        folder = f.split("/", 1)[0]
        if folder in ("videos", "present") and f.endswith(".json"):
          name = Path(f).stem
          if (folder, name) not in mine:
            local = api.hf_hub_download(args.repo, f, repo_type="dataset")
            old[(folder, name)] = {**json.loads(Path(local).read_text(encoding="utf-8")), "_folder": folder}
    except Exception:
      pass
    allm = sorted(list(old.values()) + metas, key=lambda m: (m.get("_folder", "videos"), m["file"]))
    (stage / "README.md").write_text(card(allm), encoding="utf-8", newline="\n")
    when = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    r = api.upload_folder(folder_path=str(stage), repo_id=args.repo, repo_type="dataset",
                          commit_message=f"{'발표' if args.prefix == 'present' else '사용법'} 영상 {len(metas)}편 올림 · {when}")
    print(f"✅ 올림 — {len(metas)}편 · 커밋 {getattr(r, 'oid', '')[:10]} · https://huggingface.co/datasets/{args.repo}")
  finally:
    shutil.rmtree(stage, ignore_errors=True)
  return 0


if __name__ == "__main__":
  sys.exit(main())
