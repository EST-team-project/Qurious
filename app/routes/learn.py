"""개념 학습 API — /api/learn

설계: docs/설계/개념학습-설계.md 7절

- GET    /api/learn/catalog                  : 글 목록(머리말만) · 팀 자료 저장소 상태
- GET    /api/learn/pages/{slug}             : 글 한 편(머리말 · 본문 · 판 · 저장소)
- POST   /api/learn/pages                    : 팀 자료 새 글
- PUT    /api/learn/pages/{slug}             : 팀 자료 고치기 — base_version(내가 연 판) 필수
- DELETE /api/learn/pages/{slug}             : 팀 자료 지우기 — base_version 필수
- GET    /api/learn/pages/{slug}/history     : 팀 자료 고친 기록(HF 커밋)
- POST   /api/learn/sync                     : HF 에서 지금 받기

누가 읽고 쓰나
    기본 교재(public/learn/content)는 로그인 없이 읽는다 — 공개 저장소에 있는 우리 글이다. 쓰는 API 는 없다(파일 · PR 로만).
    팀 자료(HF 비공개)는 로그인 뒤에만 읽고 쓴다 — 강의 자료 발췌가 섞일 수 있는 비공개 글이다.

동기(def) 함수로 둔 까닭
    HF 호출이 블로킹(네트워크)이라 FastAPI 가 스레드 풀에서 돌리게 한다 — 이벤트 루프를 막지 않는다.
    로그인 확인(get_current_user)은 async 의존성이라 그대로 쓴다.
"""
from __future__ import annotations

from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.lib.session import get_current_user, get_optional_user
from app.services import learn_pages as lp
from app.services import learn_team as lt

router = APIRouter(prefix="/api/learn", tags=["learn"])

VERSION_PATTERN = r"^[0-9a-f]{40}$"
MetaValue = Union[str, int, list[str]]


class PageIn(BaseModel):
    meta: dict[str, MetaValue] = Field(..., description="머리말 칸(규격 learn-v1 · 설계서 6절 표 6)")
    body: str = Field("", max_length=lp.MAX_BODY, description="본문 마크다운")


class PageUpdate(PageIn):
    base_version: str = Field(..., pattern=VERSION_PATTERN, description="편집을 시작할 때 받은 판(git 블롭 해시)")


def _user_name(user: dict) -> str:
    """커밋 제목에 남길 이름 — 표시 이름만(이메일은 넣지 않는다)."""
    name = (user or {}).get("name") or "이름 없음"
    return str(name).replace("\n", " ")[:40]


def _page_error(e: lp.PageError) -> HTTPException:
    return HTTPException(400, detail={"code": "LEARN_INVALID", "message": e.message, "field": e.field})


def _conflict(e: lt.Conflict) -> HTTPException:
    cur = e.current
    message = ("편집을 시작한 뒤 다른 사람이 이 글을 지웠습니다." if cur is None
               else "편집을 시작한 뒤 다른 사람이 이 글을 고쳤습니다. 지금 글을 보고 다시 저장하세요.")
    return HTTPException(409, detail={"code": "LEARN_CONFLICT", "message": message,
                                      "current": cur.full() if cur else None})


def _store_error(e: lt.TeamStoreError) -> HTTPException:
    return HTTPException(e.status, detail={"code": "LEARN_TEAM_UNAVAILABLE", "message": e.message})


@router.get("/catalog", summary="개념 학습 글 목록")
def catalog(
    section: Optional[str] = Query(None, pattern="^(tech|finance)$", description="tech(개념 학습) · finance(금융 필수 지식)"),
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
        team = store.status()
    else:
        team = {"state": "login_required", "repo": store.repo_id, "editable": False,
                "message": "팀 자료는 로그인한 뒤 볼 수 있습니다."}
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
    return {**page.full(), "history_url": store.file_url(slug)}


@router.post("/pages", status_code=201, summary="팀 자료 새 글")
def create_page(payload: PageIn, user: dict = Depends(get_current_user)):
    builtin, _ = lp.load_builtin()
    try:
        page, oid = lt.store().create(dict(payload.meta), payload.body, _user_name(user), set(builtin))
    except lp.PageError as e:
        raise _page_error(e) from e
    except lt.Conflict as e:
        raise HTTPException(409, detail={"code": "LEARN_EXISTS", "message": "같은 slug 의 팀 자료가 이미 있습니다.",
                                         "current": e.current.full() if e.current else None}) from e
    except lt.TeamStoreError as e:
        raise _store_error(e) from e
    return {"slug": page.slug, "version": page.version, "commit": oid}


@router.put("/pages/{slug}", summary="팀 자료 고치기")
def update_page(slug: str, payload: PageUpdate, user: dict = Depends(get_current_user)):
    builtin, _ = lp.load_builtin()
    if slug in builtin:
        raise HTTPException(400, detail={"code": "LEARN_BUILTIN_READONLY",
                                         "message": "기본 교재는 앱에서 고치지 않습니다 — 저장소 파일을 고쳐 PR 로 올리세요."})
    try:
        page, oid = lt.store().update(slug, dict(payload.meta), payload.body, payload.base_version, _user_name(user))
    except lp.PageError as e:
        raise _page_error(e) from e
    except lt.NotFound:
        raise HTTPException(404, detail={"code": "LEARN_NOT_FOUND", "message": "없는 글입니다(그사이 지워졌을 수 있습니다)."})
    except lt.Conflict as e:
        raise _conflict(e) from e
    except lt.TeamStoreError as e:
        raise _store_error(e) from e
    return {"slug": page.slug, "version": page.version, "commit": oid, "changed": oid is not None}


@router.delete("/pages/{slug}", status_code=204, summary="팀 자료 지우기")
def delete_page(slug: str, base_version: str = Query(..., pattern=VERSION_PATTERN),
                user: dict = Depends(get_current_user)):
    builtin, _ = lp.load_builtin()
    if slug in builtin:
        raise HTTPException(400, detail={"code": "LEARN_BUILTIN_READONLY", "message": "기본 교재는 앱에서 지우지 않습니다."})
    try:
        lt.store().delete(slug, base_version, _user_name(user))
    except lt.NotFound:
        raise HTTPException(404, detail={"code": "LEARN_NOT_FOUND", "message": "없는 글입니다."})
    except lt.Conflict as e:
        raise _conflict(e) from e
    except lt.TeamStoreError as e:
        raise _store_error(e) from e
    return Response(status_code=204)


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


@router.post("/sync", summary="팀 자료 지금 받기")
def sync_now(user: dict = Depends(get_current_user)):
    store = lt.store()
    result = store.sync(manual=True)
    return {**result, "team": store.status()}
