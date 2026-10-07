"""개념 학습 글 — 규격 `learn-v1`(머리말 + 마크다운) · 판 · 기본 교재 읽기 · 목록 만들기.

설계: docs/설계/개념학습-설계.md — 6절(규격) · 5.3절(두 저장소) · 5.6절(판)

글 한 편 = 마크다운 파일 하나다. 맨 위 `---` 사이의 머리말은 `이름: 값` 한 줄씩이고, 목록 칸은 쉼표로 나눈다.
YAML 전체를 받지 않는 까닭 — 칸이 열몇 개뿐이라 작은 읽기 코드로 충분하고, 팀원이 편집기에서 쓴 글을
서버가 읽을 때 YAML 의 태그 · 별칭 같은 기능이 끼어들 틈을 처음부터 없앤다.

저장소가 둘이다.
  기본 교재(builtin)  주담당이 쓰는 장 — `public/learn/content/<slug>.md` · 코드처럼 PR 로만 바뀐다 · 로그인 없이 읽는다
  팀 자료(team)       팀원이 앱 편집기로 쓰는 글 — HF 비공개 데이터셋(app/services/learn_team.py)
둘 다 이 파일의 규격 · 검사를 똑같이 지난다. 팀 자료만 글 속 스크립트 조각을 한 번 더 거절한다(화면의 DOMPurify 와 두 겹).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

CONTRACT = "learn-v1"

# 주소 이름 — 영문 소문자 · 숫자 · '-' 3~64자, 처음과 끝은 '-' 가 아니다. 파일 이름과 같아야 한다.
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
# 정렬 번호 「부.장」 — 기술 개념은 숫자 부(0~9), 금융 지식은 F 부.
ORDER_RE = re.compile(r"^(F|\d{1,2})\.\d{1,2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SECTIONS = ("tech", "finance")
STATUSES = ("ready", "draft", "skeleton")
LEVELS = ("입문", "기초", "심화")

REQUIRED = ("slug", "title", "section", "part", "order", "status", "summary")
OPTIONAL = ("level", "minutes", "owner", "updated_by", "feature", "work", "prereq", "tags", "updated")
KEY_ORDER = REQUIRED + OPTIONAL
LIST_KEYS = ("prereq", "tags")

MAX_TITLE = 120
MAX_SUMMARY = 200
MAX_VALUE = 300          # 그 밖의 칸 한 줄 상한
MAX_BODY = 200_000       # 글자 — RAG 장(가장 긴 장)의 몇 배

# 팀 자료에서 거절하는 조각. 화면은 모든 글을 DOMPurify 로 거른 뒤 그리지만, 서버도 한 번 더 막는다 —
# 비공개 저장소의 글이라도 팀원 PC 의 앱에서 그대로 열리므로 「어디서 온 글이든 실행되지 않는다」 를 두 곳에서 지킨다.
# 코드 블록 · 인라인 코드 안은 보지 않는다(_strip_code) — 화면이 글자로만 보여 주는 곳이고, 보안 설명 글이
# `<script>` 예시를 코드로 보여 주는 것까지 막으면 안 된다. 사건 속성(onclick= …)도 **태그 안**에서만 찾는다 —
# 본문의 `online = True` 같은 줄을 잘못 거르지 않게.
FORBIDDEN_RE = re.compile(
    r"<\s*/?\s*(script|iframe|object|embed|link|meta|base|form)\b"   # 실행 · 끌어오기 태그
    r"|javascript\s*:"                                                 # 주소에 숨긴 스크립트
    r"|<[a-z][^>]*\son[a-z]+\s*=",                                     # 태그 안의 onclick= 같은 사건 속성
    re.IGNORECASE,
)
_FENCE_RE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.MULTILINE | re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")

BUILTIN_DIR = Path(__file__).resolve().parents[2] / "public" / "learn" / "content"


class PageError(ValueError):
    """규격 위반 — 라우트가 400 으로 바꾼다. `field` 는 어느 칸이 틀렸는지(화면이 그 칸을 빨갛게)."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field


def git_blob_sha1(data: bytes) -> str:
    """git 블롭 해시 — `git hash-object` 와 같은 값.

    글의 「판」 으로 쓴다. HF 가 파일 목록에 주는 `blob_id` 가 이 값이라(2026-10-01 실측 · README.md 로 대조),
    저장할 때 서버에 따로 묻지 않고도 「내가 연 판이 아직 최신인가」 를 비교할 수 있다.
    """
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def normalize_body(body: str) -> str:
    """줄바꿈을 `\\n` 으로, 앞뒤 빈 줄을 걷고 끝에 줄바꿈 하나 — 같은 글이 PC 마다 다른 판이 되지 않게."""
    text = body.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    return text + "\n" if text else ""


def parse(text: str) -> tuple[dict, str]:
    """파일 글 → (머리말, 본문). 규격이 틀리면 PageError."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("﻿"):
        text = text[1:]
    if not text.startswith("---\n"):
        raise PageError("글 맨 위에 머리말(--- 로 시작)이 없습니다.", "meta")
    end = text.find("\n---", 3)          # 3 부터 — 머리말이 비어 「---\n---」 인 글도 닫는 줄을 찾는다
    if end < 0 or text[end + 4: end + 5] not in ("", "\n"):
        raise PageError("머리말을 닫는 --- 줄이 없습니다.", "meta")
    head = text[4:end]
    body = text[end + 4:]

    meta: dict = {}
    for n, raw in enumerate(head.split("\n"), start=2):
        line = raw.strip()
        if not line:
            continue
        if ":" not in line:
            raise PageError(f"머리말 {n}번째 줄이 「이름: 값」 모양이 아닙니다.", "meta")
        key, value = (s.strip() for s in line.split(":", 1))
        if key not in KEY_ORDER:
            raise PageError(f"모르는 머리말 칸입니다: {key}", key)
        if key in meta:
            raise PageError(f"머리말 칸이 두 번 나옵니다: {key}", key)
        meta[key] = value
    return _typed(meta), normalize_body(body)


def _typed(meta: dict) -> dict:
    """글자 그대로의 머리말 → 목록 칸은 list, minutes 는 int."""
    out: dict = {}
    for key, value in meta.items():
        if key in LIST_KEYS:
            items = value if isinstance(value, list) else str(value).split(",")
            out[key] = [s.strip() for s in items if str(s).strip()]
        elif key == "minutes":
            if value in ("", None):
                continue
            try:
                out[key] = int(value)
            except (TypeError, ValueError):
                raise PageError("읽는 시간(minutes)은 분 단위 숫자여야 합니다.", "minutes") from None
        else:
            out[key] = "" if value is None else str(value).strip()
    return out


def clean_meta(meta: dict) -> dict:
    """화면 · API 가 보낸 머리말을 규격 모양으로 — 모르는 칸은 거절, 빈 칸은 뺀다."""
    unknown = [k for k in meta if k not in KEY_ORDER]
    if unknown:
        raise PageError(f"모르는 머리말 칸입니다: {', '.join(unknown)}", unknown[0])
    typed = _typed(meta)
    return {k: v for k, v in typed.items() if v not in ("", [], None)}


def validate(meta: dict, body: str, *, team: bool) -> None:
    """규격 검사 — 기본 교재 · 팀 자료 공통. `team=True` 면 글 속 스크립트 조각도 거절한다."""
    for key in REQUIRED:
        if not meta.get(key):
            raise PageError(f"필수 칸이 비었습니다: {key}", key)
    for key, value in meta.items():
        values = value if isinstance(value, list) else [value]
        for v in values:
            if isinstance(v, str) and ("\n" in v or len(v) > MAX_VALUE):
                raise PageError(f"{key} 칸은 한 줄 · {MAX_VALUE}자 안이어야 합니다.", key)
    if not SLUG_RE.match(meta["slug"]):
        raise PageError("slug 는 영문 소문자 · 숫자 · '-' 3~64자여야 합니다(처음 · 끝은 '-' 가 아님).", "slug")
    if meta["section"] not in SECTIONS:
        raise PageError(f"section 은 {' · '.join(SECTIONS)} 중 하나여야 합니다.", "section")
    if meta["status"] not in STATUSES:
        raise PageError(f"status 는 {' · '.join(STATUSES)} 중 하나여야 합니다.", "status")
    if meta.get("level") and meta["level"] not in LEVELS:
        raise PageError(f"level 은 {' · '.join(LEVELS)} 중 하나여야 합니다.", "level")
    if not ORDER_RE.match(meta["order"]):
        raise PageError("order 는 「부.장」 모양이어야 합니다(예: 3.1 · F.2).", "order")
    if meta.get("updated") and not DATE_RE.match(meta["updated"]):
        raise PageError("updated 는 YYYY-MM-DD 모양이어야 합니다.", "updated")
    if "minutes" in meta and not (1 <= int(meta["minutes"]) <= 600):
        raise PageError("읽는 시간은 1~600분이어야 합니다.", "minutes")
    if len(meta["title"]) > MAX_TITLE:
        raise PageError(f"제목은 {MAX_TITLE}자 안이어야 합니다.", "title")
    if len(meta["summary"]) > MAX_SUMMARY:
        raise PageError(f"요약은 {MAX_SUMMARY}자 안이어야 합니다.", "summary")
    for p in meta.get("prereq", []):
        if not SLUG_RE.match(p):
            raise PageError(f"먼저 읽을 장(prereq)의 slug 모양이 틀렸습니다: {p}", "prereq")
    if len(body) > MAX_BODY:
        raise PageError(f"본문은 {MAX_BODY:,}자 안이어야 합니다.", "body")
    if team:
        joined = _strip_code(body) + "\n" + "\n".join(
            " ".join(v) if isinstance(v, list) else str(v) for v in meta.values())
        hit = FORBIDDEN_RE.search(joined)
        if hit:
            raise PageError(f"글에 실행되는 조각은 넣을 수 없습니다: {hit.group(0).strip()[:30]}", "body")


def _strip_code(body: str) -> str:
    """코드 블록(``` · ~~~)과 인라인 코드를 걷어 낸 본문 — 금지 조각 검사는 화면이 HTML 로 그리는 곳만 본다."""
    return _INLINE_CODE_RE.sub("", _FENCE_RE.sub("", body))


def serialize(meta: dict, body: str) -> str:
    """(머리말, 본문) → 파일 글. 칸 차례는 KEY_ORDER 로 늘 같게 — 같은 글이면 같은 판이 나온다."""
    lines = ["---"]
    for key in KEY_ORDER:
        if key not in meta or meta[key] in ("", [], None):
            continue
        value = meta[key]
        if key in LIST_KEYS:
            value = ", ".join(value)
        lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + normalize_body(body)


@dataclass(frozen=True)
class Page:
    """글 한 편 — 저장소(builtin · team)와 파일 글 그대로를 함께 들고 다닌다(판은 파일 글에서 계산)."""

    meta: dict
    body: str
    store: str
    text: str

    @property
    def slug(self) -> str:
        return self.meta["slug"]

    @property
    def version(self) -> str:
        return git_blob_sha1(self.text.encode("utf-8"))

    def entry(self) -> dict:
        """목록 한 줄 — 본문 없이."""
        return {**self.meta, "store": self.store, "version": self.version}

    def full(self) -> dict:
        return {"meta": self.meta, "body": self.body, "store": self.store, "version": self.version}


def page_from_text(text: str, store: str, *, team: bool) -> Page:
    meta, body = parse(text)
    validate(meta, body, team=team)
    return Page(meta=meta, body=body, store=store, text=text.replace("\r\n", "\n"))


def page_from_parts(meta: dict, body: str, store: str, *, team: bool) -> Page:
    """화면에서 받은 칸 → 검사 → 파일 글까지 만든 글."""
    meta = clean_meta(meta)
    body = normalize_body(body)
    validate(meta, body, team=team)
    text = serialize(meta, body)
    return Page(meta=meta, body=body, store=store, text=text)


def order_key(meta: dict) -> tuple:
    """목차 정렬 — 구역(기술 → 금융) · 부 · 장 · 제목."""
    major, _, minor = meta.get("order", "99.99").partition(".")
    section_rank = SECTIONS.index(meta["section"]) if meta.get("section") in SECTIONS else 9
    major_rank = 0 if major == "F" else int(major) if major.isdigit() else 99
    return (section_rank, major_rank, int(minor) if minor.isdigit() else 99, meta.get("title", ""))


# ── 기본 교재 읽기 ─────────────────────────────────────────────────────

_builtin_lock = Lock()
_builtin_cache: dict = {"sig": None, "pages": {}, "errors": []}


def _signature(folder: Path) -> tuple:
    try:
        return tuple(sorted((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in folder.glob("*.md")))
    except FileNotFoundError:
        return ()


def load_builtin(folder: Path | None = None) -> tuple[dict[str, Page], list[dict]]:
    """기본 교재 전부 → ({slug: Page}, [깨진 파일]).

    파일 목록 · 수정 시각이 그대로면 다시 읽지 않는다(개발 모드에서 파일을 저장하면 다음 요청에 바로 반영된다).
    깨진 파일은 목록에서 빼고 `errors` 로 알린다 — 앱이 죽지는 않되 숨기지도 않는다(시험 TC-LN 교재 검사가 막는다).
    """
    folder = folder or BUILTIN_DIR
    sig = _signature(folder)
    with _builtin_lock:
        if folder == BUILTIN_DIR and sig == _builtin_cache["sig"]:
            return _builtin_cache["pages"], _builtin_cache["errors"]
        pages: dict[str, Page] = {}
        errors: list[dict] = []
        for f in sorted(folder.glob("*.md")) if folder.exists() else []:
            try:
                page = page_from_text(f.read_text(encoding="utf-8"), "builtin", team=False)
                if page.slug != f.stem:
                    raise PageError(f"파일 이름({f.stem})과 slug({page.slug})가 다릅니다.", "slug")
                pages[page.slug] = page
            except (PageError, UnicodeDecodeError) as e:
                errors.append({"file": f.name, "message": getattr(e, "message", str(e))})
        if folder == BUILTIN_DIR:
            _builtin_cache.update(sig=sig, pages=pages, errors=errors)
        return pages, errors


def matches(meta: dict, q: str) -> bool:
    """검색 — 낱말을 모두 담은 글만(제목 · 요약 · 부 · 꼬리표 · slug). 대소문자를 가리지 않는다."""
    words = [w for w in q.lower().split() if w]
    if not words:
        return True
    hay = " ".join([meta.get("title", ""), meta.get("summary", ""), meta.get("part", ""),
                    meta.get("slug", ""), " ".join(meta.get("tags", []))]).lower()
    return all(w in hay for w in words)
