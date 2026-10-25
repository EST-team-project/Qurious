"""여러 PC 회차 임대(`scripts/run_lease.py`) 시험 (TC-LE) — 설계 `docs/phase-3/02-design/system/여러PC-회차-설계.md` 4절.

지키려는 것 —
1. 한 회차 자리는 한 PC 만 잡는다 — 같은 머리를 읽고 함께 써도 앞 커밋 비교(412)로 하나만 이긴다.
2. 만료(90분 무소식) · 같은 PC 의 죽은 실행이 남긴 임대만 이어받는다 — 살아 있는 남의 임대는 빼앗지 않는다.
3. 빼앗긴 쪽은 다음 갱신 · 닫기에서 멈춘다(LeaseLost) · 응답을 잃은 쓰기는 다시 읽어 내 것인지 가린다.
4. 닫을 때 정기 · 전체 수집만 회차 자리 기록을 남긴다(14개까지) · 맞추기가 멈춘 회차는 자리를 채우지 않는다.
5. 새 임대 가지는 main 에서 따라온 데이터 파일을 지우고 안내만 둔다(2026-10-25 시험 사고로 생긴 가지가 데이터 사본이었다).

진짜 HF 에 닿지 않는다 — 가지 · 머리 · 파일을 메모리에 둔 가짜 저장소(``FakeHub``)를 넘긴다(conftest 가 오프라인으로 막는다).
"""
from __future__ import annotations

import datetime
import json
import tempfile
import types
from pathlib import Path

import httpx2
import pytest
from huggingface_hub import CommitOperationAdd, CommitOperationDelete
from huggingface_hub.errors import EntryNotFoundError, HfHubHTTPError, RevisionNotFoundError

from scripts import run_lease as rl

KST = rl.KST
T0 = datetime.datetime(2026, 10, 26, 12, 30, 5, tzinfo=KST)


def _http(code: int) -> HfHubHTTPError:
    return HfHubHTTPError(f"HTTP {code}", response=httpx2.Response(code, request=httpx2.Request("POST", "https://hub.test/x")))


class FakeHub:
    """가짜 HF 저장소 — 가지마다 (머리, 파일). create_commit 은 앞 커밋이 머리와 다르면 412 · 내용이 같으면 커밋 없음(진짜와 같게)."""

    def __init__(self):
        self.n = 0
        self.snap = {}
        main = self._new({".gitattributes": b"*.parquet filter=xet", "README.md": b"card",
                          "price_daily/year=2026/part-00000.parquet": b"p", "meta/manifest.json": b"{}"})
        self.branches = {"main": main}
        self.commits = []
        self.squashed = 0
        self.before_commit = None          # 다음 커밋 앞에 끼워 넣을 일(다른 PC)
        self.raise_after_commit = None     # 커밋은 들어가고 응답만 잃음
        self.raise_before_commit = None    # 커밋 없이 실패

    def _new(self, files: dict) -> str:
        self.n += 1
        sha = f"{self.n:040x}"
        self.snap[sha] = dict(files)
        return sha

    def repo_info(self, repo_id, *, repo_type=None, revision=None, timeout=None, **k):
        if revision not in self.branches:
            raise RevisionNotFoundError("없는 가지", response=httpx2.Response(404, request=httpx2.Request("GET", "https://hub.test/r")))
        return types.SimpleNamespace(sha=self.branches[revision], private=True)

    def create_branch(self, repo_id, *, branch, repo_type=None, exist_ok=False, revision=None):
        if branch in self.branches:
            if not exist_ok:
                raise _http(409)
            return
        self.branches[branch] = self._new(self.snap[self.branches["main"]])

    def hf_hub_download(self, repo_id, filename, *, repo_type=None, revision=None, **k):
        files = self.snap[revision]
        if filename not in files:
            raise EntryNotFoundError(f"없는 파일 {filename}")
        p = Path(tempfile.mkdtemp()) / Path(filename).name
        p.write_bytes(files[filename])
        return str(p)

    def list_repo_files(self, repo_id, *, repo_type=None, revision=None):
        return sorted(self.snap[revision])

    def create_commit(self, repo_id, operations, *, commit_message, repo_type=None, revision=None, parent_commit=None, **k):
        if self.before_commit:
            hook, self.before_commit = self.before_commit, None
            hook()
        if self.raise_before_commit:
            err, self.raise_before_commit = self.raise_before_commit, None
            raise err
        head = self.branches[revision]
        if parent_commit and parent_commit != head:
            raise _http(412)
        files = dict(self.snap[head])
        for op in operations:
            if isinstance(op, CommitOperationAdd):
                data = op.path_or_fileobj
                files[op.path_in_repo] = data if isinstance(data, bytes) else Path(data).read_bytes()
            elif isinstance(op, CommitOperationDelete):
                files.pop(op.path_in_repo, None)
        if files == self.snap[head]:
            return types.SimpleNamespace(oid=head)          # 내용이 같으면 커밋하지 않는다(진짜 라이브러리 꼴)
        sha = self._new(files)
        self.branches[revision] = sha
        self.commits.append((revision, commit_message))
        if self.raise_after_commit:
            err, self.raise_after_commit = self.raise_after_commit, None
            raise err
        return types.SimpleNamespace(oid=sha)

    def super_squash_history(self, repo_id, *, branch=None, commit_message=None, repo_type=None, **k):
        self.squashed += 1
        self.branches[branch] = self._new(self.snap[self.branches[branch]])

    def lease(self) -> dict:
        return json.loads(self.snap[self.branches[rl.BRANCH]][rl.PATH_IN_REPO])


def _acquire(hub, *, now=T0, kind="schedule", pc="PC-A", pid=111):
    return rl.acquire(hub, now=now, kind=kind, run=now.isoformat(), pc=pc, pid=pid)


def test_le01_constants_match_runner_and_backup():
    """TC-LE-01 · 같은 백업 저장소 · 회차 경계는 러너의 12:30 − 따라잡기 여유 · 만료는 가장 긴 단계 한도 + 갱신 간격보다 길다 ·
    올리기 앞 커밋 환경 이름은 러너와 백업 도구가 같다."""
    from scripts import daily_update as du
    from scripts import hf_dataset

    assert rl.REPO_ID == hf_dataset.REPO_ID
    h, m = (int(x) for x in du.DEFAULT_TIME.split(":"))
    edge = datetime.datetime(2026, 1, 1, h, m) - datetime.timedelta(minutes=du.CATCH_UP_SLACK_MIN)
    assert rl.SLOT_FROM == edge.time()
    longest = max(s.timeout_min for s in du.STEPS)
    assert rl.EXPIRE_MIN > longest + rl.RENEW_MIN, (longest, rl.RENEW_MIN, rl.EXPIRE_MIN)
    assert du.ENV_HF_PARENT == hf_dataset.ENV_PARENT
    assert rl.WAIT_MAX_MIN * 60 < du.LOCK_STALE_HOURS * 3600, "따라가며 기다리는 끝이 작업 스케줄러 한도(4시간) 안"


def test_le02_slot_boundary():
    """TC-LE-02 · 12:28 부터 그날 자리 · 그 앞은 전날 자리(전날 12:30 을 놓친 따라잡기)."""
    d = datetime.date(2026, 10, 26)
    at = lambda hh, mm, ss=0: datetime.datetime(2026, 10, 26, hh, mm, ss, tzinfo=KST)  # noqa: E731
    assert rl.slot_of(at(12, 28)) == d.isoformat()
    assert rl.slot_of(at(12, 27, 59)) == (d - datetime.timedelta(days=1)).isoformat()
    assert rl.slot_of(at(0, 30)) == (d - datetime.timedelta(days=1)).isoformat()
    assert rl.slot_of(at(22, 30)) == d.isoformat()


def test_le03_first_acquire_makes_a_clean_branch_and_leaves_main():
    """TC-LE-03 · 가지가 없으면 main 에서 내고 데이터 파일을 지운 뒤(안내 README · lease.json · .gitattributes 만) 세대 1 로 잡는다 ·
    main 은 그대로."""
    hub = FakeHub()
    main_before = hub.branches["main"]
    status, held, doc, why = _acquire(hub)
    assert status == "acquired" and doc["gen"] == 1 and doc["state"] == "running" and doc["slot"] == "2026-10-26"
    files = set(hub.snap[hub.branches[rl.BRANCH]])
    assert files == {".gitattributes", "README.md", rl.PATH_IN_REPO}, files
    assert b"main" in hub.snap[hub.branches[rl.BRANCH]]["README.md"] and "데이터 아님" in rl.BRANCH_README
    assert hub.branches["main"] == main_before and held.head == hub.branches[rl.BRANCH]
    assert all(b == rl.BRANCH for b, _ in hub.commits), "main 에 커밋하지 않는다"


def test_le04_two_pcs_same_head_only_one_wins():
    """TC-LE-04 · 두 PC 가 같은 머리를 읽고 함께 쓰면 앞 커밋 비교(412)로 하나만 이긴다 — 진 쪽은 다시 읽어 남의 running 을 보고 busy."""
    hub = FakeHub()
    _acquire(hub, pc="PC-A")
    rl.release(hub, rl.Held(hub.branches[rl.BRANCH], hub.lease()), now=T0, ok=True, rc=0, summary={}, fill_slot=False)
    later = T0 + datetime.timedelta(days=1)
    # PC-B 가 읽은 뒤 쓰기 직전에 PC-C 가 먼저 잡는다
    hub.before_commit = lambda: _acquire(hub, now=later, pc="PC-C", pid=333)
    status, held, doc, why = _acquire(hub, now=later, pc="PC-B", pid=222)
    assert status == "busy" and held is None and doc["pc"] == "PC-C" and "PC-C" in why
    assert hub.lease()["pc"] == "PC-C" and hub.lease()["gen"] == 2


def test_le05_done_slot_follows_only_for_schedule():
    """TC-LE-05 · 정기 회차는 그 자리가 끝났으면(성공이든 실패든) done — 화면 전체 수집 · 한 단계 다시는 남이 도는 중일 때만 막힌다."""
    hub = FakeHub()
    _, held, _, _ = _acquire(hub, pc="PC-A")
    rl.release(hub, held, now=T0 + datetime.timedelta(minutes=50), ok=False, rc=1, summary={"price_max": "20261023"})
    st, _, doc, why = _acquire(hub, now=T0 + datetime.timedelta(hours=2), pc="PC-B")
    assert st == "done" and "PC-A" in why and doc["slots"]["2026-10-26"]["ok"] is False
    st2, held2, _, _ = _acquire(hub, now=T0 + datetime.timedelta(hours=2), kind="manual", pc="PC-B")
    assert st2 == "acquired" and held2.doc["gen"] == 2


def test_le06_expiry_and_same_pc_takeover():
    """TC-LE-06 · 남의 running 은 마지막 갱신 뒤 90분까지 busy · 넘으면 세대를 올려 이어받고 누구에게서 받았는지 적는다 ·
    같은 PC 의 running(이 PC 잠금을 잡았으니 그 실행은 끝났다)은 바로 이어받는다."""
    hub = FakeHub()
    _acquire(hub, pc="PC-A")
    st, _, _, _ = _acquire(hub, now=T0 + datetime.timedelta(minutes=89), pc="PC-B")
    assert st == "busy"
    st, held, doc, why = _acquire(hub, now=T0 + datetime.timedelta(minutes=91), pc="PC-B")
    assert st == "acquired" and doc["gen"] == 2 and doc["taken_from"]["pc"] == "PC-A" and "90분" in why
    st, held3, doc3, why3 = _acquire(hub, now=T0 + datetime.timedelta(minutes=95), pc="PC-B", pid=999)
    assert st == "acquired" and doc3["gen"] == 3 and "이 PC" in why3


def test_le07_renew_only_after_interval_and_lost_after_takeover():
    """TC-LE-07 · 갱신은 15분이 지났을 때만 커밋 · 남이 이어받은 뒤의 갱신 · 닫기는 LeaseLost / None(쓰지 않음)."""
    hub = FakeHub()
    _, held, _, _ = _acquire(hub, pc="PC-A")
    n = len(hub.commits)
    held = rl.renew(hub, held, T0 + datetime.timedelta(minutes=10))
    assert len(hub.commits) == n, "15분 안에는 쓰지 않는다"
    held = rl.renew(hub, held, T0 + datetime.timedelta(minutes=16))
    assert len(hub.commits) == n + 1 and hub.lease()["renewed_at"].startswith("2026-10-26T12:46")
    assert rl.still_mine(hub, held) == (True, "")
    _acquire(hub, now=T0 + datetime.timedelta(minutes=16 + 91), pc="PC-B")          # 만료 뒤 이어받기
    ok, why = rl.still_mine(hub, held)
    assert not ok and "PC-B" in why
    with pytest.raises(rl.LeaseLost):
        rl.renew(hub, held, T0 + datetime.timedelta(minutes=120))
    n = len(hub.commits)
    assert rl.release(hub, held, now=T0 + datetime.timedelta(minutes=121), ok=True, rc=0, summary={}) is None
    assert len(hub.commits) == n and hub.lease()["pc"] == "PC-B", "빼앗긴 임대는 닫지 않는다"


def test_le08_lost_response_is_settled_by_reading_back():
    """TC-LE-08 · 커밋은 들어갔는데 응답만 잃으면(시간 초과) 다시 읽어 내 쓰기가 있으므로 이긴 것 · 커밋 없이 실패하면 LeaseError ·
    429 는 「나중에」(later)."""
    hub = FakeHub()
    hub.raise_after_commit = httpx2.ReadTimeout("응답 없음")             # 가지 정리 커밋 — 들어갔는데 응답을 잃음
    st, held, doc, _ = _acquire(hub)
    assert st == "acquired" and set(hub.snap[hub.branches[rl.BRANCH]]) == {".gitattributes", "README.md", rl.PATH_IN_REPO}
    rl.release(hub, held, now=T0, ok=True, rc=0, summary={}, fill_slot=False)
    hub.raise_after_commit = httpx2.ReadTimeout("응답 없음")             # 임대 쓰기 — 들어갔는데 응답을 잃음
    st, held, doc, _ = _acquire(hub, now=T0 + datetime.timedelta(days=1))
    assert st == "acquired" and hub.lease()["write"] == doc["write"] and held.head == hub.branches[rl.BRANCH]
    hub0 = FakeHub()                                                     # 정리 커밋이 들어가지 않은 채 끊김 → 다음 실행이 다시 정리
    hub0.raise_before_commit = httpx2.ConnectError("끊김")
    with pytest.raises(rl.LeaseError):
        _acquire(hub0)
    st0, _, _, _ = _acquire(hub0)
    assert st0 == "acquired" and set(hub0.snap[hub0.branches[rl.BRANCH]]) == {".gitattributes", "README.md", rl.PATH_IN_REPO}
    hub2 = FakeHub()
    _acquire(hub2)
    rl.release(hub2, rl.Held(hub2.branches[rl.BRANCH], hub2.lease()), now=T0, ok=True, rc=0, summary={}, fill_slot=False)
    hub2.raise_before_commit = httpx2.ConnectError("끊김")
    with pytest.raises(rl.LeaseError):
        _acquire(hub2, now=T0 + datetime.timedelta(days=1), pc="PC-B")
    hub2.raise_before_commit = _http(429)
    with pytest.raises(rl.LeaseError) as e:
        _acquire(hub2, now=T0 + datetime.timedelta(days=1), pc="PC-B")
    assert e.value.later


def test_le09_noop_commit_is_not_a_win():
    """TC-LE-09 · 커밋이 생기지 않으면(받은 oid 가 앞 커밋과 같음 — 내용이 같아 비교도 빠진 경우) 이긴 것으로 보지 않는다."""
    hub = FakeHub()
    _acquire(hub)
    head = hub.branches[rl.BRANCH]
    with pytest.raises(rl.LeaseError):
        rl._write(hub, hub.lease(), head, "같은 내용")


def test_le10_release_slot_record_prune_and_squash():
    """TC-LE-10 · 닫기 — 정기 · 전체 수집은 자리 기록(요약 · 단계 줄)을 남기고 14개까지만 · 한 단계 다시 · 맞추기 멈춤은 남기지
    않는다 · 처음 닫을 때와 30일마다 임대 가지 이력을 하나로 줄인다(가지만)."""
    hub = FakeHub()
    for i in range(16):
        now = T0 + datetime.timedelta(days=i)
        _, held, _, _ = _acquire(hub, now=now)
        rl.release(hub, held, now=now + datetime.timedelta(minutes=40), ok=True, rc=0,
                   summary={"started_at": now.isoformat(), "steps": [["price", 0], ["calendar", 0]], "price_max": "20261023"})
    slots = hub.lease()["slots"]
    assert len(slots) == rl.KEEP_SLOTS and min(slots) == (T0 + datetime.timedelta(days=2)).date().isoformat()
    last = slots[max(slots)]
    assert last["steps"] == [["price", 0], ["calendar", 0]] and last["pc"] == "PC-A" and last["ok"] is True
    assert hub.squashed == 1, "처음 닫을 때 한 번 · 30일 안에는 다시 하지 않는다"
    later = T0 + datetime.timedelta(days=40)
    _, held, _, _ = _acquire(hub, now=later, kind="only")
    rl.release(hub, held, now=later, ok=True, rc=0, summary={})
    assert later.date().isoformat() not in hub.lease()["slots"] and hub.squashed == 2
    _, held, _, _ = _acquire(hub, now=later + datetime.timedelta(days=1))
    rl.release(hub, held, now=later + datetime.timedelta(days=1), ok=False, rc=65, summary={}, fill_slot=False)
    assert (later + datetime.timedelta(days=1)).date().isoformat() not in hub.lease()["slots"]
    assert hub.lease()["state"] == "failed" and hub.lease()["result"]["rc"] == 65


def test_le11_wait_done_outcomes():
    """TC-LE-11 · 따라가며 기다리기 — 그 자리가 끝나면 done · 쥔 PC 가 자리를 채우지 않고 닫으면 free · 90분 무소식이면 expired ·
    끝이 오면 timeout. 읽기만 한다(커밋 없음)."""
    hub = FakeHub()
    _, held, _, _ = _acquire(hub, pc="PC-A")
    clock = {"t": T0 + datetime.timedelta(minutes=1)}
    slept = []

    def sleep(sec):
        slept.append(sec)
        clock["t"] += datetime.timedelta(seconds=sec)
        if len(slept) == 2:
            rl.release(hub, held, now=clock["t"], ok=True, rc=0, summary={"steps": [["price", 0]]})

    n = len(hub.commits)
    out, doc, _ = rl.wait_done(hub, "2026-10-26", now_fn=lambda: clock["t"], sleep_fn=sleep)
    assert out == "done" and len(slept) == 2 and slept[0] == rl.POLL_MIN * 60 and len(hub.commits) == n + 1
    hub2 = FakeHub()
    _acquire(hub2, pc="PC-A")
    clock2 = {"t": T0}
    out2, _, _ = rl.wait_done(hub2, "2026-10-26", now_fn=lambda: clock2["t"],
                              sleep_fn=lambda s: clock2.__setitem__("t", clock2["t"] + datetime.timedelta(seconds=s)))
    assert out2 == "expired"
    out3, _, _ = rl.wait_done(hub2, "2026-10-26", now_fn=lambda: T0 + datetime.timedelta(minutes=5),
                              sleep_fn=lambda s: None, max_min=0)
    assert out3 == "timeout"
    hub3 = FakeHub()
    _, h3, _, _ = _acquire(hub3, kind="only")
    rl.release(hub3, h3, now=T0, ok=True, rc=0, summary={})
    assert rl.wait_done(hub3, "2026-10-26", now_fn=lambda: T0, sleep_fn=lambda s: None)[0] == "free"


def test_le12_unreachable_hub_is_a_lease_error_not_a_crash():
    """TC-LE-12 · 닿지 못함 · 읽기 실패는 LeaseError(회차를 잡지 않는다 · fail-closed) — 예외가 러너 오류로 새지 않는다 · 토큰이
    없으면 make_api 가 LeaseError."""
    class Down(FakeHub):
        def repo_info(self, *a, **k):
            raise httpx2.ConnectError("망 없음")

    with pytest.raises(rl.LeaseError) as e:
        _acquire(Down())
    assert "닿지 못했다" in e.value.why
