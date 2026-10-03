"""개념 학습 시험 (TC-LN) — docs/설계/개념학습-설계_v0.1.md 10절.

무엇을 지키는가 —
글은 파일(규격 learn-v1) → 저장소 둘(기본 교재 · 팀 자료) → API → 화면으로 흐른다. 조용히 틀어질 수 있는 곳을 건다.

1. 규격: 머리말 읽기 · 쓰기가 왕복하고, 틀린 칸은 어느 칸인지 알려 준다. 팀 자료만 글 속 실행 조각을 거절한다.
2. 판: 글의 판(git 블롭 해시)이 `git hash-object` 와 같다 — HF 의 blob_id 와 비교하는 근거다.
3. 팀 자료 저장소(가짜 HF): 새 글 · 고치기 · 지우기 · 낡은 판은 Conflict · 다른 글 때문의 412 는 한 번 다시 ·
   내 글이 바뀐 412 는 Conflict · 권한 없음은 403 · 받아 오기가 더하고 바꾸고 지운다 · 해시가 다르면 쓰지 않는다.
4. API: 기본 교재는 로그인 없이 · 팀 자료 읽기 · 쓰기는 로그인 뒤 · 기본 교재 이름은 팀 자료가 못 쓴다.
5. 교재: 기본 교재 34편이 규격 · 링크 · 선수 장을 지키고, 3.1 RAG 장의 「직접 해 보기」 출력이 지금 예제 코드와 같다.

네트워크 · DB 없이 돈다(HF 는 가짜, 로그인은 의존성 덮어쓰기).
"""
from __future__ import annotations

import importlib.util
import re
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user, get_optional_user
from app.routes import learn as learn_routes
from app.services import learn_pages as lp
from app.services import learn_team as lt

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "public" / "learn" / "content"

META = {"slug": "team-note", "title": "팀 메모", "section": "tech", "part": "팀 자료", "order": "9.1",
        "status": "draft", "summary": "시험용 팀 메모"}


def page_text(slug="team-note", body="본문입니다.", **extra) -> str:
    return lp.serialize({**META, "slug": slug, **extra}, body)


# ── 1. 규격 ───────────────────────────────────────────────────────────

def test_parse_serialize_roundtrip_and_types():
    """TC-LN-01 · 머리말 → 파일 글 → 머리말이 같고, 목록 칸은 list · minutes 는 int 로 돌아온다."""
    meta = {**META, "tags": ["RAG", "임베딩"], "prereq": ["map"], "minutes": 30, "level": "입문"}
    text = lp.serialize(meta, "\n\n## 제목\n\n본문\n\n\n")
    back_meta, back_body = lp.parse(text)
    assert back_meta == {**meta}
    assert back_body == "## 제목\n\n본문\n"
    # 같은 글은 PC 가 달라도 같은 판 — 줄바꿈(CRLF) · BOM 이 섞여도
    crlf = "﻿" + text.replace("\n", "\r\n")
    assert lp.parse(crlf) == (back_meta, back_body)


@pytest.mark.parametrize("change, field", [
    ({"slug": "A-B"}, "slug"),
    ({"slug": "-ab"}, "slug"),
    ({"section": "misc"}, "section"),
    ({"status": "done"}, "status"),
    ({"order": "3"}, "order"),
    ({"updated": "2026/10/01"}, "updated"),
    ({"level": "중급"}, "level"),
    ({"title": "가" * 121}, "title"),
    ({"summary": ""}, "summary"),
    ({"prereq": ["Bad Slug"]}, "prereq"),
])
def test_validate_points_to_the_wrong_field(change, field):
    """TC-LN-02 · 규격 위반은 어느 칸인지(field) 알려 준다 — 편집기가 그 칸을 빨갛게 한다."""
    with pytest.raises(lp.PageError) as e:
        lp.page_from_parts({**META, **change}, "본문", "team", team=True)
    assert e.value.field == field


def test_parse_rejects_unknown_or_duplicate_keys_and_missing_fence():
    """TC-LN-02b · 모르는 칸 · 두 번 나온 칸 · 닫는 --- 없는 글 · 빈 머리말은 거절한다."""
    with pytest.raises(lp.PageError):
        lp.parse("---\nslug: a-b\nauthor: x\n---\n본문")
    with pytest.raises(lp.PageError):
        lp.parse("---\nslug: a-b\nslug: c-d\n---\n본문")
    with pytest.raises(lp.PageError):
        lp.parse("---\nslug: a-b\n본문")
    meta, body = lp.parse("---\n---\n본문")
    assert meta == {} and body == "본문\n"
    with pytest.raises(lp.PageError):
        lp.validate(meta, body, team=False)


@pytest.mark.parametrize("body", [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "[눌러](javascript:alert(1))",
    "<iframe src='https://example.com'></iframe>",
])
def test_team_pages_reject_executable_fragments(body):
    """TC-LN-03 · 팀 자료는 실행되는 조각을 거절한다(화면의 DOMPurify 와 두 겹)."""
    with pytest.raises(lp.PageError) as e:
        lp.page_from_parts(META, body, "team", team=True)
    assert e.value.field == "body"


def test_code_and_ordinary_text_are_not_mistaken_for_scripts():
    """TC-LN-03b · (보존 확인) 코드 블록 · 인라인 코드 속 예시와 `online = True` 같은 본문은 거르지 않는다."""
    body = ("보안 장에서 보이는 예:\n\n```html\n<script>alert(1)</script>\n<img onerror=x>\n```\n\n"
            "인라인 `<script>` 도 글자일 뿐입니다.\n\nonline = True 처럼 쓴 줄 · 「on 이 붙은 낱말」\n")
    page = lp.page_from_parts(META, body, "team", team=True)
    assert "online = True" in page.body


# ── 2. 판 ────────────────────────────────────────────────────────────

def test_version_is_git_blob_sha1():
    """TC-LN-04 · 판 = git 블롭 해시. `printf 'hello\\n' | git hash-object --stdin` 의 알려진 값과 같다."""
    assert lp.git_blob_sha1(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"
    page = lp.page_from_text(page_text(), "team", team=True)
    assert page.version == lp.git_blob_sha1(page.text.encode("utf-8"))


# ── 3. 팀 자료 저장소 — 가짜 HF ───────────────────────────────────────

class FakeHTTPError(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.response = types.SimpleNamespace(status_code=status)


class FakeHf:
    """HF 데이터셋 저장소 흉내 — 커밋마다 파일 묶음을 통째로 기억한다. parent_commit 이 낡으면 412."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.commits = [("c0", {}, "init")]          # (id, {path: bytes}, title)
        self.fail_next_commit: int | None = None     # 다음 커밋에 낼 오류(403 등)
        self.race: dict | None = None                # 다음 커밋 직전에 끼어들 다른 사람의 변경
        self.calls: list[str] = []
        self.corrupt: set[str] = set()               # 받을 때 내용을 깨뜨릴 경로

    @property
    def head(self):
        return self.commits[-1][0]

    def files(self):
        return dict(self.commits[-1][1])

    def push(self, changes: dict, title: str):
        files = self.files()
        for path, data in changes.items():
            if data is None:
                files.pop(path, None)
            else:
                files[path] = data
        cid = f"c{len(self.commits)}"
        self.commits.append((cid, files, title))
        return cid

    def repo_info(self, repo_id, repo_type=None, **kw):
        self.calls.append("repo_info")
        return types.SimpleNamespace(sha=self.head, private=True)

    def list_repo_tree(self, repo_id, path_in_repo=None, repo_type=None, revision=None, **kw):
        self.calls.append("list_repo_tree")
        files = dict(next(f for c, f, _ in self.commits if c == revision))
        prefix = f"{path_in_repo}/"
        entries = [types.SimpleNamespace(path=p, blob_id=lp.git_blob_sha1(b)) for p, b in files.items() if p.startswith(prefix)]
        if not entries:
            raise FakeHTTPError(404)
        return entries

    def hf_hub_download(self, repo_id, filename, repo_type=None, revision=None, cache_dir=None, **kw):
        self.calls.append(f"download:{filename}")
        files = dict(next(f for c, f, _ in self.commits if c == revision))
        data = files[filename] + (b" broken" if filename in self.corrupt else b"")
        out = self.tmp / "downloads" / revision / filename
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return str(out)

    def create_commit(self, repo_id, repo_type=None, operations=(), commit_message="", parent_commit=None, **kw):
        self.calls.append("create_commit")
        if self.race:
            race, self.race = self.race, None
            self.push(race, "learn: 다른 사람")
        if self.fail_next_commit:
            code, self.fail_next_commit = self.fail_next_commit, None
            raise FakeHTTPError(code)
        if parent_commit != self.head:
            raise FakeHTTPError(412)
        changes = {}
        for op in operations:
            changes[op.path_in_repo] = op.path_or_fileobj if hasattr(op, "path_or_fileobj") else None
        return types.SimpleNamespace(oid=self.push(changes, commit_message))

    def list_repo_commits(self, repo_id, repo_type=None, **kw):
        import datetime as dt
        return [types.SimpleNamespace(commit_id=c, title=t, created_at=dt.datetime(2026, 10, 1, 12, 0), authors=["data-student"])
                for c, _, t in reversed(self.commits)]


@pytest.fixture
def fake(tmp_path):
    return FakeHf(tmp_path)


@pytest.fixture
def store(tmp_path, fake):
    clock = {"t": 1000.0}
    s = lt.TeamStore(api_factory=lambda: fake, repo_id="qurious-quant/learn-pages",
                     cache_dir=tmp_path / "cache", sync_seconds=300, clock=lambda: clock["t"])
    s._clock = clock
    return s


def test_create_update_delete_and_history(store, fake):
    """TC-LN-05 · 새 글 → 고치기 → 지우기가 커밋 셋이 되고, 이력은 커밋 제목으로 그 글만 거른다."""
    page, oid = store.create(dict(META), "첫 판", "이동원", builtin_slugs={"rag-basics"})
    assert oid == fake.head and fake.files()["pages/team-note.md"] == page.text.encode()
    assert page.meta["owner"] == "이동원" and page.meta["updated_by"] == "이동원"
    page2, oid2 = store.update("team-note", dict(META), "둘째 판", page.version, "신장환")
    assert oid2 and page2.meta["owner"] == "이동원" and page2.meta["updated_by"] == "신장환"
    same, none = store.update("team-note", dict(META), "둘째 판", page2.version, "신장환")
    assert none is None and same.version == page2.version            # 바뀐 것이 없으면 커밋하지 않는다
    store.delete("team-note", page2.version, "이동원")
    assert "pages/team-note.md" not in fake.files() and store.pages() == {}
    titles = [h["title"] for h in store.history("team-note")]
    assert titles == ["learn: team-note 지움 (이동원)", "learn: team-note 고침 (신장환)", "learn: team-note 새 글 (이동원)"]


def test_stale_version_is_a_conflict_with_the_current_page(store, fake):
    """TC-LN-06 · 내가 연 판이 낡았으면 Conflict — 지금 글을 함께 돌려주고 덮어쓰지 않는다."""
    v1 = store.create(dict(META), "첫 판", "이동원", set())[0].version
    v2 = store.update("team-note", dict(META), "둘째 판", v1, "오준영")[0].version
    before = fake.head
    with pytest.raises(lt.Conflict) as e:
        store.update("team-note", dict(META), "낡은 판에서 고침", v1, "이동원")
    assert e.value.current.version == v2 and fake.head == before
    with pytest.raises(lt.Conflict):
        store.delete("team-note", v1, "이동원")


def test_412_from_another_page_retries_once(store, fake):
    """TC-LN-07 · 동기화와 커밋 사이에 **다른 글**이 바뀌어 412 가 나면 새로 받고 한 번 다시 커밋한다."""
    v1 = store.create(dict(META), "첫 판", "이동원", set())[0].version
    fake.race = {"pages/other-note.md": page_text("other-note", "다른 사람 글").encode()}
    page, oid = store.update("team-note", dict(META), "둘째 판", v1, "이동원")
    assert oid == fake.head and fake.calls.count("create_commit") == 3      # 새 글 1 + 412 1 + 다시 1
    assert set(store.pages()) == {"team-note", "other-note"}


def test_412_from_my_page_is_a_conflict(store, fake):
    """TC-LN-07b · 경합으로 끼어든 변경이 **내 글**이면 다시 시도하지 않고 Conflict."""
    v1 = store.create(dict(META), "첫 판", "이동원", set())[0].version
    theirs = page_text(body="강민석이 먼저 고침").encode()
    fake.race = {"pages/team-note.md": theirs}
    with pytest.raises(lt.Conflict) as e:
        store.update("team-note", dict(META), "내 고침", v1, "이동원")
    assert e.value.current.text.encode() == theirs


def test_permission_error_and_missing_token(store, fake, tmp_path):
    """TC-LN-08 · 쓰기 권한이 없으면 403 으로, 토큰이 없으면 503 「꺼짐」 으로 알린다."""
    fake.fail_next_commit = 403
    with pytest.raises(lt.TeamStoreError) as e:
        store.create(dict(META), "본문", "이동원", set())
    assert e.value.status == 403
    off = lt.TeamStore(api_factory=lambda: None, cache_dir=tmp_path / "off")
    off.maybe_sync()
    assert off.status()["state"] == "off" and off.status()["editable"] is False
    with pytest.raises(lt.TeamStoreError) as e:
        off.create(dict(META), "본문", "이동원", set())
    assert e.value.status == 503


def test_sync_adds_updates_removes_and_skips_corrupt_downloads(store, fake):
    """TC-LN-09 · 받아 오기는 바뀐 글만 받고, 없어진 글은 지우고, 해시가 목록과 다른 내용은 쓰지 않는다."""
    fake.push({"pages/a-note.md": page_text("a-note").encode(), "pages/b-note.md": page_text("b-note").encode()}, "x")
    r = store.sync()
    assert (r["added"], r["updated"], r["removed"]) == (2, 0, 0)
    store._clock["t"] += 60                     # 10초 규칙 밖
    fake.push({"pages/a-note.md": page_text("a-note", "고친 글").encode(), "pages/b-note.md": None}, "y")
    downloads_before = len([c for c in fake.calls if c.startswith("download")])
    r = store.sync(manual=True)
    assert (r["added"], r["updated"], r["removed"]) == (0, 1, 1)
    assert len([c for c in fake.calls if c.startswith("download")]) == downloads_before + 1     # 바뀐 a 만
    store._clock["t"] += 60
    fake.corrupt.add("pages/c-note.md")
    fake.push({"pages/c-note.md": page_text("c-note").encode()}, "z")
    store.sync(manual=True)
    assert "c-note" not in store.pages()


def test_manual_sync_within_10_seconds_does_not_call_hf(store, fake):
    """TC-LN-09b · 「새로 받기」 를 10초 안에 또 누르면 HF 에 묻지 않는다(호출 한도 보호)."""
    store.sync(manual=True)
    calls = len(fake.calls)
    store._clock["t"] += 5
    assert store.sync(manual=True).get("skipped") is True and len(fake.calls) == calls


def test_broken_team_file_is_listed_not_hidden(store, fake):
    """TC-LN-09c · HF 웹에서 직접 고쳐 규격이 깨진 글은 목록에서 빼되 errors 로 알린다."""
    fake.push({"pages/bad-note.md": b"no front matter"}, "x")
    store.sync()
    assert "bad-note" not in store.pages()
    assert [e["file"] for e in store.status()["errors"]] == ["bad-note.md"]


def test_create_rejects_builtin_slug(store):
    """TC-LN-10 · 팀 자료는 기본 교재와 같은 slug 를 쓸 수 없다(기본 교재를 가리지 못하게)."""
    with pytest.raises(lp.PageError) as e:
        store.create({**META, "slug": "rag-basics"}, "x", "이동원", builtin_slugs={"rag-basics"})
    assert e.value.field == "slug"


# ── 4. API ───────────────────────────────────────────────────────────

@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr(lt, "_store", store)
    app = FastAPI()
    app.include_router(learn_routes.router)
    return app


def login(app, name="시험 사용자"):
    user = {"id": "u1", "name": name, "email": "t@example.com"}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user


def test_builtin_pages_are_public_team_pages_need_login(client, store):
    """TC-LN-11 · 기본 교재는 로그인 없이 읽고, 팀 자료는 목록에도 안 보이며 읽기 · 쓰기는 401."""
    store.create(dict(META), "팀 메모", "이동원", set())
    c = TestClient(client)
    cat = c.get("/api/learn/catalog").json()
    assert cat["team"]["state"] == "login_required"
    assert {p["store"] for p in cat["pages"]} == {"builtin"}
    assert c.get("/api/learn/pages/rag-basics").status_code == 200
    assert c.get("/api/learn/pages/team-note").status_code == 401
    assert c.post("/api/learn/pages", json={"meta": META, "body": "x"}).status_code == 401


def test_logged_in_crud_and_conflict_through_api(client):
    """TC-LN-12 · 로그인하면 새 글 201 · 고치기 200 · 낡은 판 409(지금 글 포함) · 지우기 204."""
    login(client)
    c = TestClient(client)
    r = c.post("/api/learn/pages", json={"meta": META, "body": "첫 판"})
    assert r.status_code == 201
    v1 = r.json()["version"]
    r = c.put("/api/learn/pages/team-note", json={"meta": META, "body": "둘째 판", "base_version": v1})
    assert r.status_code == 200 and r.json()["changed"] is True
    v2 = r.json()["version"]
    r = c.put("/api/learn/pages/team-note", json={"meta": META, "body": "낡은 판", "base_version": v1})
    assert r.status_code == 409 and r.json()["detail"]["current"]["version"] == v2
    cat = c.get("/api/learn/catalog").json()
    assert any(p["slug"] == "team-note" and p["store"] == "team" for p in cat["pages"])
    assert c.delete(f"/api/learn/pages/team-note?base_version={v2}").status_code == 204
    assert c.get("/api/learn/pages/team-note").status_code == 404


def test_api_rejects_builtin_writes_and_bad_input(client):
    """TC-LN-13 · 기본 교재는 앱에서 못 고치고(400), 규격 위반은 어느 칸인지 400 으로 알린다."""
    login(client)
    c = TestClient(client)
    v = "0" * 40
    assert c.put("/api/learn/pages/rag-basics", json={"meta": META, "body": "x", "base_version": v}).status_code == 400
    assert c.delete(f"/api/learn/pages/rag-basics?base_version={v}").status_code == 400
    r = c.post("/api/learn/pages", json={"meta": {**META, "section": "misc"}, "body": "x"})
    assert r.status_code == 400 and r.json()["detail"]["field"] == "section"
    assert c.put("/api/learn/pages/team-note", json={"meta": META, "body": "x", "base_version": "not-a-sha"}).status_code == 422


def test_main_registers_router_and_learn_site():
    """TC-LN-14 · 앱이 학습 API 를 붙이고 /learn/ 을 별도 HTML 로 내준다(main.py 를 띄우지 않고 글자로 확인)."""
    src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "app.include_router(learn_routes.router)" in src
    assert re.search(r'app\.mount\("/learn", _RevalidateHtml\(directory=os\.path\.join\(_public, "learn"\), html=True', src)
    assert 'resp.headers["Cache-Control"] = "no-cache"' in src
    assert (ROOT / "public" / "learn" / "index.html").exists()


# ── 5. 교재 ──────────────────────────────────────────────────────────

def test_builtin_textbook_pages_are_valid_and_linked():
    """TC-LN-15 · 기본 교재 전부가 규격을 지키고, 선수 장 · 장 안 링크(#/p/…)가 있는 장을 가리킨다."""
    pages, errors = lp.load_builtin(CONTENT)
    assert errors == []
    assert len(pages) == 34
    assert {p.meta["section"] for p in pages.values()} == {"tech", "finance"}
    for page in pages.values():
        for pre in page.meta.get("prereq", []):
            assert pre in pages, (page.slug, pre)
        for target in re.findall(r"\(#/p/([a-z0-9-]+)\)", page.body):
            assert target in pages, (page.slug, target)
        assert "<script" not in page.body.lower()
    ready = {s for s, p in pages.items() if p.meta["status"] == "ready"}
    assert {"map", "rag-basics"} <= ready
    for slug in ready:      # 완성 장은 장 틀의 머리(학습 목표)와 끝(더 읽을거리)을 갖는다
        assert pages[slug].body.lstrip().startswith("> [!GOAL]") and "## 더 읽을거리" in pages[slug].body
    for slug, page in pages.items():
        if page.meta["status"] == "skeleton":
            assert "**뼈대**" in page.body and "## 다룰 질문" in page.body, slug


SETEXT_TRAP = re.compile(r"^(?:>\s*)?[^\s>|#`<-][^\n]*\n(?:>\s*)?-\s*$", re.MULTILINE)


def test_no_empty_list_line_under_text_becomes_a_heading():
    """TC-LN-17 · 글 한 줄 바로 아래의 빈 목록 줄(`-` · `> -`)은 마크다운에서 제목 밑줄로 읽혀 그 줄이 큰 제목이 된다.
    기본 교재와 편집기의 「장 틀」 에 그런 자리가 없다(2026-10-01 미리보기에서 `[!GOAL]` 이 제목이 된 일)."""
    for f in CONTENT.glob("*.md"):
        hit = SETEXT_TRAP.search(lp.parse(f.read_text(encoding="utf-8"))[1])
        assert hit is None, (f.name, hit.group(0) if hit else "")
    js = (ROOT / "public" / "learn" / "learn.js").read_text(encoding="utf-8")
    template = re.search(r"const TEMPLATE = \[(.*?)\]\.join", js, re.DOTALL).group(1)
    lines = re.findall(r'"((?:[^"\\]|\\.)*)"', template)
    assert SETEXT_TRAP.search("\n".join(lines)) is None


def _rag_mini():
    spec = importlib.util.spec_from_file_location("rag_mini", ROOT / "public" / "learn" / "examples" / "rag_mini.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_rag_chapter_outputs_match_the_example_code():
    """TC-LN-16 · 3.1 RAG 장에 실은 「직접 해 보기」 출력이 지금 예제 코드의 결과와 같다(교재가 거짓이 되지 않게)."""
    m = _rag_mini()
    db = m.build_index()
    kw = m.keyword_search(db, m.QUESTION)
    names = [m.CHUNKS[i]["title"] for i in kw]
    chapter = (CONTENT / "rag-basics.md").read_text(encoding="utf-8")
    assert f"[낱말 검색] 순위: {names}" in chapter                  # 첫째 실행(표준 라이브러리)
    # 표 5 의 RRF 계산 — 장에 적은 낱말 · 뜻 순위로 다시 계산하면 같은 점수 · 차례가 나온다
    titles = [c["title"] for c in m.CHUNKS]
    dense = [titles.index(t) for t in ["설명 · 수수료", "증권거래세법 시행령 제5조 제3호", "농어촌특별세법 제5조 제1항 표 제5호",
                                         "증권거래세법 시행령 제5조 제2호", "증권거래세법 시행령 제5조 제1호"]]
    fused = m.rrf([kw, dense])
    assert [titles[i] for i in fused[:4]] == ["설명 · 수수료", "증권거래세법 시행령 제5조 제1호",
                                              "증권거래세법 시행령 제5조 제2호", "설명 · 옵션 만기"]
    assert "1/63 + 1/61 = 0.03227" in chapter and round(1 / 63 + 1 / 61, 5) == 0.03227
    # 검사 함수 — 장에 실은 셋째 실행의 답에서 「근거 밖 숫자 0.5%」 를 잡는다
    answer = ("[출처 1] 증권거래세법 시행령 제5조 제1호 (대통령령 제36001호, 시행 2026-01-01)에 따르면, 유가증권시장에서 양도되는 "
              "주권의 세율은 1만분의 5입니다.\n\n따라서, 2026년 현재 코스피 시장에서 주식을 팔 때 내는 세금은 1만분의 5, 즉 0.5%입니다.")
    ids = [titles.index("증권거래세법 시행령 제5조 제1호"), titles.index("농어촌특별세법 제5조 제1항 표 제5호")]
    assert m.check_citations(answer, 4) == []
    assert m.unsupported_numbers(answer, ids) == ["0.5%"]
    assert m.check_citations("[출처 7] 없는 번호", 4) == [7]


# ── 6. 1부 시세 데이터 장 (2026-10-01) ──────────────────────────────────

def _example(name: str):
    import sys
    spec = importlib.util.spec_from_file_location(name, ROOT / "public" / "learn" / "examples" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod            # dataclass 가 자기 모듈을 sys.modules 에서 찾는다
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("slug, example, fn", [
    ("ohlcv-bars", "ohlcv_bars", "main"),
    ("adjusted-price", "adjusted_price", "main"),
    ("intraday-timezone", "intraday_kst", "offline"),
    ("data-quality-check", "quality_check", "main"),
    ("chunking-legal-versions", "legal_versions", "main"),   # 3부 3.4 (2026-10-03)
])
def test_part1_chapter_outputs_match_example_code(slug, example, fn, capsys):
    """TC-LN-18 · 1부 장에 실은 「직접 해 보기」 출력 줄이 지금 예제 코드(네트워크 없는 부분)의 출력과 한 글자도
    다르지 않다 — 예제를 고치고 장을 안 고치면 여기서 멈춘다. 네트워크로 받은 출력(`--live`)은 날마다 달라 대조하지 않는다."""
    getattr(_example(example), fn)()
    printed = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    chapter = (CONTENT / f"{slug}.md").read_text(encoding="utf-8")
    missing = [line for line in printed if line not in chapter]
    assert printed and missing == [], missing[:3]


def test_part1_chapters_read_like_a_service_not_a_project():
    """TC-LN-19 · 1부 장 본문에 프로젝트 내부 표현(차수 · 담당 · 요구 ID · 구현 묶음 W 번호 · 「팀원」 · 「설계서」)이 없다.
    2026-10-01 사용자 피드백 — 실제 서비스의 교재처럼, 내용 위주로. 머리말의 쓴 사람(owner) 칸은 서명이라 예외."""
    banned = re.compile(r"W[0-9]\b|P0[12]-|주담당|부담당|[23]차 프로젝트|팀원|설계서|요구 ID")
    for slug in ("ohlcv-bars", "adjusted-price", "intraday-timezone", "data-quality-check",
                 "chunking-legal-versions"):                      # 3.4 도 같은 규칙(2026-10-03)
        body = lp.parse((CONTENT / f"{slug}.md").read_text(encoding="utf-8"))[1]
        hits = banned.findall(body)
        assert hits == [], (slug, hits)
        meta = lp.parse((CONTENT / f"{slug}.md").read_text(encoding="utf-8"))[0]
        assert "feature" not in meta and "work" not in meta, slug
