"""개념 학습 API — /api/learn

설계: docs/설계/개념학습-설계.md 7절

- GET    /api/learn/catalog                  : 글 목록(머리말만) · 팀 자료 저장소 상태
- GET    /api/learn/pages/{slug}             : 글 한 편(머리말 · 본문 · 판 · 저장소)
- GET    /api/learn/pages/{slug}/history     : 팀 자료 고친 기록(HF 커밋)
- POST   /api/learn/sync                     : HF 에서 지금 받기(관리자 · 일반 사용자는 403)

저장소 이름 · 서버 글(개발 낱말)은 관리자 응답에만 — 일반 사용자 · 익명은 상태 · 받은 때만(2026-10-19 결정 · _team_view)

누가 읽나 — 쓰는 API 는 없다
    기본 교재(public/learn/content)는 로그인 없이 읽는다 — 공개 저장소에 있는 우리 글이다(고치기는 파일 · PR 로만).
    팀 자료(HF 비공개)는 로그인 뒤에만 읽는다 — 강의 자료 발췌가 섞일 수 있는 비공개 글이다.
    앱 안 새 글 · 고치기 · 지우기는 없앴다(2026-10-19 사용자 결정 D133) — 가입만 하면 누구나 서버의 쓰기 토큰으로 팀 저장소를
    바꿀 수 있었고, 팀 자료는 이동원이 모두 맡아 HF 데이터셋에서 직접 관리한다. 앱은 5분마다 받아 읽기만 한다.

동기(def) 함수로 둔 까닭
    HF 호출이 블로킹(네트워크)이라 FastAPI 가 스레드 풀에서 돌리게 한다 — 이벤트 루프를 막지 않는다.
    로그인 확인(get_current_user)은 async 의존성이라 그대로 쓴다.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.lib.session import get_current_user, get_optional_user
from app.services import learn_pages as lp
from app.services import learn_team as lt

router = APIRouter(prefix="/api/learn", tags=["learn"])


def _store_error(e: lt.TeamStoreError) -> HTTPException:
    return HTTPException(e.status, detail={"code": "LEARN_TEAM_UNAVAILABLE", "message": e.message})


def _is_admin(user: Optional[dict]) -> bool:
    return bool(user) and "admin" in (user.get("roles") or [])


# 일반 사용자 · 익명에게 보일 팀 자료 상태 칸 — 저장소 이름 · 머리 판 · 서버 글(HF · 토큰 같은 개발 낱말) ·
# 깨진 파일 목록은 관리자에게만 낸다(사용자 결정 2026-10-19). 화면이 가리는 것이 아니라 응답에서 뺀다 — 한 곳(SSoT).
TEAM_PUBLIC_KEYS = ("state", "synced_at")


def _team_view(team: dict, user: Optional[dict]) -> dict:
    if _is_admin(user):
        return {**team, "admin": True}
    return {**{k: team[k] for k in TEAM_PUBLIC_KEYS if k in team}, "admin": False}


@router.get("/catalog", summary="개념 학습 글 목록")
def catalog(
    section: Optional[str] = Query(None, pattern="^(tech|finance|special)$", description="tech(개념 학습) · finance(금융 필수 지식) · special(특강)"),
    q: str = Query("", max_length=60, description="검색어 — 제목 · 요약 · 부 · 꼬리표 · slug 에 모두 든 글"),
    user: Optional[dict] = Depends(get_optional_user),
):
    """기본 교재 + (로그인했으면) 팀 자료의 머리말 목록. 팀 자료는 5분에 한 번 HF 에서 새로 받는다."""
    builtin, errors = lp.load_builtin()
    entries = [p.entry() for p in builtin.values()]
    store = lt.store()
    if user:
        store.maybe_sync()
        entries += [p.entry() for p in store.pages().values()]
        team = _team_view(store.status(), user)
    else:
        team = _team_view({"state": "login_required"}, None)
    entries = [e for e in entries if (not section or e["section"] == section) and lp.matches(e, q)]
    entries.sort(key=lambda e: (e["store"] != "builtin",) + lp.order_key(e))
    return {"contract": lp.CONTRACT, "pages": entries, "builtin_errors": errors, "team": team}


@router.get("/pages/{slug}", summary="글 한 편")
def get_page(slug: str, user: Optional[dict] = Depends(get_optional_user)):
    """기본 교재는 누구나, 팀 자료는 로그인한 사람만. 같은 slug 면 기본 교재가 먼저다(팀 자료가 가리지 못한다)."""
    if not lp.SLUG_RE.match(slug):
        raise HTTPException(404, detail={"code": "LEARN_NOT_FOUND", "message": "없는 글입니다."})
    builtin, _ = lp.load_builtin()
    if slug in builtin:
        return builtin[slug].full()
    if not user:
        raise HTTPException(401, detail={"code": "LEARN_LOGIN_REQUIRED", "message": "팀 자료는 로그인한 뒤 볼 수 있습니다."})
    store = lt.store()
    store.maybe_sync()
    page = store.pages().get(slug)
    if page is None:
        raise HTTPException(404, detail={"code": "LEARN_NOT_FOUND", "message": "없는 글입니다."})
    out = page.full()
    if _is_admin(user):                                  # HF 주소는 관리자에게만 — 개발 낱말은 서버가 뺀다(2026-10-19 결정)
        out["history_url"] = store.file_url(slug)
    return out


@router.get("/pages/{slug}/history", summary="팀 자료 고친 기록")
def page_history(slug: str, user: dict = Depends(get_current_user)):
    if not lp.SLUG_RE.match(slug):
        raise HTTPException(404, detail={"code": "LEARN_NOT_FOUND", "message": "없는 글입니다."})
    store = lt.store()
    try:
        commits = store.history(slug)
    except lt.TeamStoreError as e:
        raise _store_error(e) from e
    return {"slug": slug, "commits": commits, "url": store.file_url(slug)}


@router.post("/sync", summary="팀 자료 지금 받기 (관리자)")
def sync_now(user: dict = Depends(get_current_user)):
    """관리자만 — 일반 사용자는 5분마다 저절로 받은 글을 본다(화면의 「새로 받기」 도 관리자에게만 · 2026-10-19 결정)."""
    if not _is_admin(user):
        raise HTTPException(403, detail={"code": "LEARN_ADMIN_ONLY",
                                         "message": "관리자만 지금 받을 수 있습니다. 팀 자료는 5분마다 저절로 새로 받습니다."})
    store = lt.store()
    result = store.sync(manual=True)
    return {**result, "team": _team_view(store.status(), user)}
