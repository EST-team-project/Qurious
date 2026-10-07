"""개념 학습 — 팀 자료 저장소: HF 비공개 데이터셋 `qurious-quant/learn-pages`.

설계: docs/설계/개념학습-설계.md 5.3~5.8절

왜 HF 인가
    공용 서버가 없다(팀 결정 — 유료 클라우드 0원 · AWS 보류). 앱 DB 에 쓰면 쓴 사람 PC 에만 남는다.
    팀은 이미 데이터를 HF 비공개 데이터셋으로 나눠 쓰고 있어, 글도 같은 길로 보내면 네 명이 같은 글을 본다.
    HF 저장소는 git 이라 저장 하나가 커밋 하나 — 판 관리 · 되돌리기가 따로 필요 없다.

흐름
    읽기  앱은 내려받아 둔 글(`<캐시>/pages/*.md`)만 읽는다. 5분에 한 번 HF 최신 커밋을 묻고(API 1회),
          바뀌었으면 파일 목록의 블롭 해시를 비교해 **바뀐 글만** 받고 없어진 글은 지운다.
    쓰기  「저장」 을 누를 때만 커밋한다(HF 는 커밋 횟수 한도를 공개하지 않는다 — 자동 저장은 브라우저 안에만).
          커밋에는 `parent_commit`(내가 마지막으로 본 커밋)을 단다. 그사이 누가 저장했으면 HF 가 412 로 거절한다.
            · 다른 글이 바뀐 것이면  → 새로 받고 한 번 다시 커밋(사람에게 묻지 않는다)
            · 내 글이 바뀐 것이면    → Conflict(409) — 지금 글을 돌려주고 **말없이 덮어쓰지 않는다**

판(version)
    글 파일의 git 블롭 해시(learn_pages.git_blob_sha1). HF 파일 목록의 `blob_id` 와 같은 값이다(2026-10-01 실측).

huggingface_hub 판
    내 PC 0.36 · 앱 컨테이너 2.0 — 두 판에서 쓰는 함수 · 인자가 같은 것만 쓴다. 오류는 클래스 대신
    `e.response.status_code` 로 가른다(0.x 는 requests, 1.x 이후는 httpx 응답이지만 둘 다 status_code 가 있다).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.services.learn_pages import Page, PageError, git_blob_sha1, page_from_parts, page_from_text

log = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
REPO_ID = os.getenv("LEARN_HF_REPO", "qurious-quant/learn-pages")
SYNC_SECONDS = int(os.getenv("LEARN_SYNC_SECONDS", "300"))
MANUAL_SYNC_GAP = 10            # 「새로 받기」 를 10초 안에 또 누르면 HF 에 묻지 않는다
# 컨테이너 안에서는 /app/data(도커 볼륨 · 쓰기 가능)의 learn/team. 코드 폴더는 읽기 전용으로 붙어 있다.
CACHE_DIR = Path(os.getenv("LEARN_CACHE_DIR") or Path(__file__).resolve().parents[2] / "data" / "learn" / "team")
PAGES_DIR = "pages"


class TeamStoreError(Exception):
    """HF 저장소를 쓸 수 없을 때 — `status` 를 라우트가 그대로 HTTP 상태로 쓴다(403 권한 · 503 닿지 않음 등)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Conflict(Exception):
    """내가 연 판과 지금 판이 다르다 — `current` 는 지금 글(지워졌으면 None)."""

    def __init__(self, current: Page | None):
        super().__init__("conflict")
        self.current = current


class NotFound(Exception):
    pass


def _status(e: Exception) -> int | None:
    resp = getattr(e, "response", None)
    return getattr(resp, "status_code", None)


def _default_api() -> Any | None:
    """HF 토큰이 있으면 HfApi, 없으면 None(팀 자료 꺼짐). 토큰 값은 어디에도 찍지 않는다."""
    tok = os.getenv("HUGGINGFACE_ACCESS_TOKEN") or os.getenv("HF_TOKEN")
    if not tok:
        return None
    from huggingface_hub import HfApi
    return HfApi(token=tok)


def _iso(ts: float | None) -> str | None:
    return dt.datetime.fromtimestamp(ts, KST).isoformat(timespec="seconds") if ts else None


def today_kst() -> str:
    return dt.datetime.now(KST).date().isoformat()


class TeamStore:
    """팀 자료 한 저장소 — 앱 프로세스에 하나(store()). 받기 · 쓰기는 잠금 하나로 줄 세운다."""

    def __init__(self, api_factory: Callable[[], Any | None] = _default_api, repo_id: str = REPO_ID,
                 cache_dir: Path = CACHE_DIR, sync_seconds: int = SYNC_SECONDS,
                 clock: Callable[[], float] = time.time):
        self.api_factory = api_factory
        self.repo_id = repo_id
        self.cache_dir = Path(cache_dir)
        self.sync_seconds = sync_seconds
        self.clock = clock
        self._lock = threading.RLock()
        self._api: Any | None = None
        self._api_made = False
        self.head: str | None = None
        self.state = "never"          # never · ok · off(토큰 없음) · missing(저장소 없음 · 권한 없음) · error(닿지 않음)
        self.message: str | None = None
        self.checked_at: float | None = None
        self.synced_at: float | None = None
        self.errors: list[dict] = []
        self._pages: dict[str, Page] = {}
        self._loaded = False

    # ── 바깥에서 부르는 것 ─────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "state": self.state, "repo": self.repo_id, "head": self.head,
            "synced_at": _iso(self.synced_at), "checked_at": _iso(self.checked_at),
            "editable": self.state == "ok", "message": self.message,
            "errors": list(self.errors), "count": len(self._pages),
        }

    def pages(self) -> dict[str, Page]:
        with self._lock:
            self._load_local()
            return dict(self._pages)

    def maybe_sync(self) -> None:
        """읽기 전에 — 마지막 확인이 sync_seconds 전이면 HF 에 묻는다. 실패해도 내려받아 둔 글로 읽는다."""
        with self._lock:
            if self.checked_at is None or self.clock() - self.checked_at >= self.sync_seconds:
                self._sync(raise_errors=False)

    def sync(self, *, manual: bool = False) -> dict:
        """「새로 받기」 — 바뀐 수를 돌려준다. 10초 안에 다시 부르면 묻지 않는다."""
        with self._lock:
            if manual and self.checked_at and self.clock() - self.checked_at < MANUAL_SYNC_GAP:
                return {"head": self.head, "added": 0, "updated": 0, "removed": 0, "skipped": True}
            return self._sync(raise_errors=False)

    def create(self, meta: dict, body: str, user_name: str, builtin_slugs: set[str]) -> tuple[Page, str]:
        page = page_from_parts({**meta, "owner": meta.get("owner") or user_name,
                                "updated_by": user_name, "updated": today_kst()}, body, "team", team=True)
        if page.slug in builtin_slugs:
            raise PageError("기본 교재에 같은 slug 가 있습니다 — 다른 이름을 쓰세요.", "slug")
        with self._lock:
            api = self._require_api()
            self._sync(raise_errors=True)
            if page.slug in self._pages:
                raise Conflict(self._pages[page.slug])
            from huggingface_hub import CommitOperationAdd
            ops = [CommitOperationAdd(path_in_repo=self._path(page.slug), path_or_fileobj=page.text.encode("utf-8"))]
            oid = self._commit(api, ops, f"learn: {page.slug} 새 글 ({user_name})", {page.slug: None})
            self._write_local(page.slug, page.text)
            self._pages[page.slug] = page
            return page, oid

    def update(self, slug: str, meta: dict, body: str, base_version: str, user_name: str) -> tuple[Page, str | None]:
        if meta.get("slug", slug) != slug:
            raise PageError("slug 는 바꿀 수 없습니다 — 새 글로 만들고 옛 글을 지우세요.", "slug")
        with self._lock:
            api = self._require_api()
            self._sync(raise_errors=True)
            cur = self._pages.get(slug)
            if cur is None:
                raise NotFound(slug)
            if cur.version != base_version:
                raise Conflict(cur)
            page = page_from_parts({**meta, "slug": slug, "owner": cur.meta.get("owner") or user_name,
                                    "updated_by": user_name, "updated": today_kst()}, body, "team", team=True)
            if page.text == cur.text:
                return cur, None                              # 바뀐 것이 없으면 커밋하지 않는다
            from huggingface_hub import CommitOperationAdd
            ops = [CommitOperationAdd(path_in_repo=self._path(slug), path_or_fileobj=page.text.encode("utf-8"))]
            oid = self._commit(api, ops, f"learn: {slug} 고침 ({user_name})", {slug: base_version})
            self._write_local(slug, page.text)
            self._pages[slug] = page
            return page, oid

    def delete(self, slug: str, base_version: str, user_name: str) -> str:
        with self._lock:
            api = self._require_api()
            self._sync(raise_errors=True)
            cur = self._pages.get(slug)
            if cur is None:
                raise NotFound(slug)
            if cur.version != base_version:
                raise Conflict(cur)
            from huggingface_hub import CommitOperationDelete
            ops = [CommitOperationDelete(path_in_repo=self._path(slug))]
            oid = self._commit(api, ops, f"learn: {slug} 지움 ({user_name})", {slug: base_version})
            (self.cache_dir / PAGES_DIR / f"{slug}.md").unlink(missing_ok=True)
            self._pages.pop(slug, None)
            return oid

    def history(self, slug: str, limit: int = 30) -> list[dict]:
        """그 글의 커밋 — 커밋 제목 「learn: <slug> 」 로 거른다(HF 커밋 목록에는 경로 거르기가 없다)."""
        with self._lock:
            api = self._require_api()
        try:
            commits = api.list_repo_commits(self.repo_id, repo_type="dataset")
        except Exception as e:  # noqa: BLE001 — 어떤 실패든 화면에는 「이력을 못 받았다」 로
            raise TeamStoreError(503, f"HF 에서 이력을 받지 못했습니다({_status(e) or type(e).__name__}).") from e
        prefix = f"learn: {slug} "
        out = []
        for c in commits:
            if (c.title or "").startswith(prefix):
                created = c.created_at.isoformat() if hasattr(c.created_at, "isoformat") else str(c.created_at)
                out.append({"id": c.commit_id, "title": c.title, "date": created, "authors": list(c.authors or [])})
                if len(out) >= limit:
                    break
        return out

    def file_url(self, slug: str) -> str:
        return f"https://huggingface.co/datasets/{self.repo_id}/commits/main/{self._path(slug)}"

    # ── 안쪽 ────────────────────────────────────────────────────────────

    def _path(self, slug: str) -> str:
        return f"{PAGES_DIR}/{slug}.md"

    def _get_api(self) -> Any | None:
        if not self._api_made:
            self._api = self.api_factory()
            self._api_made = True
        return self._api

    def _require_api(self) -> Any:
        api = self._get_api()
        if api is None:
            self.state, self.message = "off", "HF 토큰이 없어 팀 자료를 쓸 수 없습니다(.env 의 HUGGINGFACE_ACCESS_TOKEN)."
            raise TeamStoreError(503, self.message)
        return api

    def _load_local(self) -> None:
        """앱이 막 켜졌을 때 — HF 에 묻기 전에 내려받아 둔 글과 마지막 커밋 해시를 읽는다(오프라인에서도 읽힌다)."""
        if self._loaded:
            return
        self._loaded = True
        state_file = self.cache_dir / "state.json"
        if state_file.exists():
            try:
                saved = json.loads(state_file.read_text(encoding="utf-8"))
                self.head = saved.get("head")
                self.synced_at = saved.get("synced_at")
            except (OSError, ValueError):
                pass
        self._reload_pages()

    def _reload_pages(self) -> None:
        pages: dict[str, Page] = {}
        errors: list[dict] = []
        folder = self.cache_dir / PAGES_DIR
        for f in sorted(folder.glob("*.md")) if folder.exists() else []:
            try:
                page = page_from_text(f.read_text(encoding="utf-8"), "team", team=True)
                if page.slug != f.stem:
                    raise PageError(f"파일 이름({f.stem})과 slug({page.slug})가 다릅니다.", "slug")
                pages[page.slug] = page
            except (PageError, UnicodeDecodeError) as e:
                # HF 웹에서 직접 고쳐 규격이 깨진 글 — 목록에서 빼고 화면에 「깨진 글」 로 알린다
                errors.append({"file": f.name, "message": getattr(e, "message", str(e))})
        self._pages, self.errors = pages, errors

    def _save_state(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_dir / "state.json.tmp"
        tmp.write_text(json.dumps({"repo": self.repo_id, "head": self.head, "synced_at": self.synced_at}), encoding="utf-8")
        os.replace(tmp, self.cache_dir / "state.json")

    def _write_local(self, slug: str, text: str) -> None:
        folder = self.cache_dir / PAGES_DIR
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f".{slug}.md.tmp"
        tmp.write_bytes(text.encode("utf-8"))       # 줄바꿈을 바꾸지 않게 바이트로 — 판(블롭 해시)이 그대로 남는다
        os.replace(tmp, folder / f"{slug}.md")

    def _sync(self, *, raise_errors: bool) -> dict:
        """HF 최신 커밋 확인 → 바뀌었으면 바뀐 글만 받기 · 없어진 글 지우기. 잠금 안에서만 부른다."""
        self._load_local()
        result = {"head": self.head, "added": 0, "updated": 0, "removed": 0}
        api = self._get_api()
        self.checked_at = self.clock()
        if api is None:
            self.state, self.message = "off", "HF 토큰이 없어 팀 자료를 받을 수 없습니다(.env 의 HUGGINGFACE_ACCESS_TOKEN)."
            if raise_errors:
                raise TeamStoreError(503, self.message)
            return result
        try:
            head = api.repo_info(self.repo_id, repo_type="dataset").sha
            if head != self.head or not (self.cache_dir / PAGES_DIR).exists():
                result.update(self._pull(api, head))
                self.head = head
                self._save_state()
        except TeamStoreError:
            raise
        except Exception as e:  # noqa: BLE001 — 네트워크 · 권한 · 없는 저장소를 상태로 바꿔 화면에 보인다
            code = _status(e)
            if code in (401, 403, 404):
                self.state = "missing"
                self.message = f"팀 자료 저장소({self.repo_id})를 찾지 못했거나 읽을 권한이 없습니다({code})."
            else:
                self.state = "error"
                self.message = f"HF 에 닿지 못했습니다({code or type(e).__name__}) — 마지막으로 받은 글을 보여 줍니다."
            log.warning("learn team sync failed: %s", self.message)
            if raise_errors:
                raise TeamStoreError(403 if code in (401, 403) else 503, self.message) from e
            return result
        self.state, self.message = "ok", None
        self.synced_at = self.checked_at
        result["head"] = self.head
        return result

    def _pull(self, api: Any, head: str) -> dict:
        try:
            entries = list(api.list_repo_tree(self.repo_id, path_in_repo=PAGES_DIR, repo_type="dataset", revision=head))
        except Exception as e:  # noqa: BLE001
            if _status(e) == 404:          # pages/ 폴더가 아직 없다 = 글 0편
                entries = []
            else:
                raise
        remote = {Path(e.path).name: e.blob_id for e in entries
                  if getattr(e, "blob_id", None) and e.path.endswith(".md") and e.path.count("/") == 1}
        folder = self.cache_dir / PAGES_DIR
        folder.mkdir(parents=True, exist_ok=True)
        local = {f.name: git_blob_sha1(f.read_bytes()) for f in folder.glob("*.md")}
        added = updated = removed = 0
        for name, blob in remote.items():
            if local.get(name) == blob:
                continue
            path = api.hf_hub_download(self.repo_id, f"{PAGES_DIR}/{name}", repo_type="dataset",
                                       revision=head, cache_dir=str(self.cache_dir / ".hub"))
            data = Path(path).read_bytes()
            if git_blob_sha1(data) != blob:         # 받다가 깨졌거나 다른 판 — 쓰지 않는다
                log.warning("learn team: %s 해시가 목록과 다르다 — 건너뜀", name)
                continue
            tmp = folder / f".{name}.tmp"
            tmp.write_bytes(data)
            os.replace(tmp, folder / name)
            added, updated = (added + 1, updated) if name not in local else (added, updated + 1)
        for name in set(local) - set(remote):
            (folder / name).unlink(missing_ok=True)
            removed += 1
        self._reload_pages()
        return {"added": added, "updated": updated, "removed": removed}

    def _commit(self, api: Any, ops: list, message: str, expect: dict[str, str | None]) -> str:
        """parent_commit 을 달아 커밋 — 412 면 다시 받아 「내 글이 그대로인가」 를 보고 한 번만 다시."""
        for attempt in (1, 2):
            try:
                info = api.create_commit(repo_id=self.repo_id, repo_type="dataset", operations=ops,
                                         commit_message=message, parent_commit=self.head)
                self.head = info.oid
                self._save_state()
                return info.oid
            except Exception as e:  # noqa: BLE001
                code = _status(e)
                if code == 412 and attempt == 1:
                    self._sync(raise_errors=True)
                    for slug, version in expect.items():
                        cur = self._pages.get(slug)
                        if (cur.version if cur else None) != version:
                            raise Conflict(cur) from e
                    continue
                if code in (401, 403):
                    raise TeamStoreError(403, "저장 권한이 없습니다 — HF 조직 qurious-quant 의 쓰기 권한과 토큰을 확인하세요.") from e
                raise TeamStoreError(503, f"HF 에 저장하지 못했습니다({code or type(e).__name__}).") from e
        raise TeamStoreError(503, "다시 시도했지만 그사이 저장소가 또 바뀌었습니다 — 잠시 뒤 다시 저장하세요.")


_store: TeamStore | None = None
_store_lock = threading.Lock()


def store() -> TeamStore:
    """앱 프로세스에 하나뿐인 팀 자료 저장소(처음 부를 때 만든다)."""
    global _store
    with _store_lock:
        if _store is None:
            _store = TeamStore()
        return _store
