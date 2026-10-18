"""사용법 영상 파일 — 결정 D132(2026-10-18) 「앱 안 영상의 원천은 로컬 폴더」.

녹화한 영상 · 자막 · 장 · 장 그림과 영상 표(videos.json)는 git · 도커 이미지 밖 로컬 폴더에 있다.
채우는 것은 tools/demo/help_videos.py — 녹화한 PC 는 `build`(tools/demo/out/ 에서), 다른 PC 는 `pull`(HF 비공개에서).
화면(public/js/howto.js)은 영상 표를 받으면 그 화면의 사용법 창에 「영상으로 보기」 칸을 그리고, 빈 표면 칸 · 단추를 숨긴다.

라우트 둘
  GET /help/videos.json      영상 표(API-HELP-01) — 영상을 받지 않은 PC 는 빈 표(200)
  GET /help/media/{이름}     영상 · 자막 · 장 · 장 그림(API-HELP-02) — 이름에 「/」 가 들어갈 수 없어 폴더 밖으로 나갈 길이 처음부터 없다

폴더는 어디인가 — 수집 DB 와 같은 길(app/services/collector_db.py)
  1. 환경 변수 HELP_MEDIA_DIR — 시험
  2. 도커 — compose 가 호스트 ./data 를 /app/data/csv 에 읽기 전용으로 이미 붙여 둔다 → <앱>/data/csv/help
     (compose 를 고치지 않는다 · 호스트의 data/help/ 가 그대로 보인다)
  3. 로컬 실행 — <저장소>/data/help

왜 정적 마운트(StaticFiles)가 아니라 라우트인가
  - 영상은 HF 비공개 자료다 — 개념 학습 팀 자료(HF 비공개 · app/routes/learn.py)처럼 로그인한 사람에게만 낸다.
  - 영상을 받지 않은 PC 는 폴더가 없다. StaticFiles 는 그때 첫 요청에 RuntimeError(500)를 낸다 —
    여기서는 영상 표에 빈 표(200)를 주고 화면은 영상 칸을 숨긴다(결정 ⑥ 「영상이 없으면 칸을 숨긴다」). 파일은 404.
    영상 표까지 404 로 두면 브라우저가 화면을 열 때마다 콘솔 오류를 찍는다(S125 녹화 기록의 콘솔 오류 2 에서 찾음).
  - FileResponse 가 Range 요청(장 단추 · 건너뛰기)에 206 으로 답한다.
  - 처음엔 한 라우트 `/help/{경로:path}` 였다 — OpenAPI 는 그 길을 `/help/{경로}` 로 적어 명세서 대조가 갈렸고(S125),
    파일은 한 폴더뿐이라 둘로 나누니 경로 검사도 단순해졌다.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from app.lib.session import get_current_user

router = APIRouter(tags=["사용법 영상"])

ENV_DIR = "HELP_MEDIA_DIR"
MANIFEST = "videos.json"
#: 영상을 받지 않은 PC 의 영상 표 — 판은 tools/demo/help_videos.py FORMAT · public/js/howtoview.js VIDEO_FORMAT 과 같다
EMPTY_MANIFEST = {"format": 1, "videos": {}, "views": {}, "missing": True}
_ROOT = Path(__file__).resolve().parents[2]

#: 내보내는 꼴 — 폴더에 다른 것이 있어도 내지 않는다(404). 파일 라우트는 영상 표(.json)를 내지 않는다
MEDIA_TYPES = {
    ".webm": "video/webm",
    ".vtt": "text/vtt; charset=utf-8",
    ".jpg": "image/jpeg",
    ".json": "application/json",
}
MEDIA_FILE_TYPES = (".webm", ".vtt", ".jpg")


def help_dir() -> Path:
    """사용법 영상 폴더 — 없어도 그 자리를 돌려준다(영상 표는 빈 표 · 파일은 404)."""
    env = os.environ.get(ENV_DIR)
    if env:
        return Path(env)
    if (_ROOT / "data" / "csv").is_dir():          # 도커 — ./data 가 /app/data/csv 에 붙어 있다
        return _ROOT / "data" / "csv" / "help"
    return _ROOT / "data" / "help"


def resolve(rel_path: str) -> Path | None:
    """폴더 안 경로 → 실제 파일. 폴더 밖 · 숨은 이름 · 내지 않는 꼴 · 없는 파일이면 None."""
    base = help_dir()
    if not base.is_dir():
        return None
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
    if not parts or any(p in (".", "..") or p.startswith(".") for p in parts):
        return None
    target = base.joinpath(*parts)
    if target.suffix.lower() not in MEDIA_TYPES:
        return None
    try:
        real, root = target.resolve(strict=True), base.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return None
    if root not in real.parents or not real.is_file():   # 링크로 폴더 밖을 가리켜도 내지 않는다
        return None
    return real


@router.get("/help/videos.json", summary="사용법 영상 표 — 화면 키 → 영상 · 장(로그인 · 영상을 받지 않은 PC 는 빈 표)")
def help_manifest(user: dict = Depends(get_current_user)):
    path = resolve(MANIFEST)
    if path is None:                                # 영상을 받지 않은 PC — 빈 표(화면은 칸을 숨긴다 · 콘솔 오류 없음)
        return JSONResponse(EMPTY_MANIFEST, headers={"Cache-Control": "no-cache"})
    # 다시 녹화하면 바뀐다 — 매번 묻기(ETag 로 304)
    return FileResponse(path, media_type=MEDIA_TYPES[".json"], headers={"Cache-Control": "no-cache"})


@router.get("/help/media/{name}", summary="사용법 영상 파일 — 영상 · 자막 · 장 · 장 그림(로그인 · Range 206)")
def help_media_file(name: str, user: dict = Depends(get_current_user)) -> FileResponse:
    path = resolve(f"media/{name}")
    if path is None or path.suffix.lower() not in MEDIA_FILE_TYPES:
        raise HTTPException(status_code=404, detail="사용법 영상 파일이 없습니다.")
    # 표의 주소에 내용 지문(?v=)이 붙어 다시 녹화하면 주소가 바뀐다 — 하루 동안 그대로(로그인한 사람의 것이라 private)
    return FileResponse(path, media_type=MEDIA_TYPES[path.suffix.lower()], headers={"Cache-Control": "private, max-age=86400"})
