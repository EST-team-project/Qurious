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


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 판 문지기(할 일 ①-28 · 2026-10-26) — 프로토콜 번호. 이번 판은 「싣기」 까지 + 원격 `min_protocol` 이 있을 때만 읽는다(없으면 통과).
# 이번 판은 `min_protocol` 을 정하지 않는다 — 아직 이 코드를 받지 못한 PC 가 내일 12:30 에 멈추면 안 된다(Kafka 꼴 첫 단계:
# 모든 PC 가 새 코드를 받은 것을 상태 표에서 본 뒤에야 번호를 올린다).
# ─────────────────────────────────────────────────────────────────────────────────────────────
import importlib.util  # noqa: E402
import sys  # noqa: E402
import uuid  # noqa: E402

from collector import config as _config  # noqa: E402

OLD_FIXTURE = Path(__file__).parent / "fixtures" / "run_lease_v1_no_protocol.py"


@pytest.fixture
def old_rl(monkeypatch, tmp_path):
    """판 문지기를 넣기 전에 다른 PC 들이 돌리던 임대 코드(얼려 둔 사본) — 진짜 상태 파일 · HF 에 닿지 않게 막고 불러온다.

    ``tests/fixtures/run_lease_v1_no_protocol.py`` 는 2026-10-26 main ``e1399fe`` 의 ``scripts/run_lease.py`` 그대로다 — 고치지
    않는다(고치면 「옛 코드」 가 아니게 된다). 다음에 규칙이 또 바뀌면 그때의 사본을 곁에 하나 더 둔다."""
    spec = importlib.util.spec_from_file_location("run_lease_v1_no_protocol", OLD_FIXTURE)
    old = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, old)       # @dataclass 가 소속 모듈을 sys.modules 에서 찾는다(시험이 끝나면 되돌린다)
    spec.loader.exec_module(old)
    monkeypatch.setattr(old, "STATE_PATH", tmp_path / "old_run_lease.json")      # 진짜 상태 파일을 덮지 않는다

    def _blocked():
        raise old.LeaseError("시험 — 실제 Hugging Face 에 닿지 않는다")

    monkeypatch.setattr(old, "make_api", _blocked)
    return old


def _set_min(hub, value):
    """사람이 임대 문서에 ``min_protocol`` 을 적어 올린다 — 새 커밋 한 개."""
    rl._write(hub, dict(hub.lease(), min_protocol=value, write=uuid.uuid4().hex), hub.branches[rl.BRANCH], "min_protocol")


def _done_once(hub, pc="PC-A", now=T0):
    """한 회차를 잡고 닫아 두어 다음 PC 가 새로 잡게 한다(문서는 done)."""
    _, held, _, _ = _acquire(hub, now=now, pc=pc)
    rl.release(hub, held, now=now + datetime.timedelta(minutes=40), ok=True, rc=0, summary={"price_max": "20261023"})


def test_le13_protocol_constant_is_shared_with_the_manifest_writer():
    """TC-LE-13 · 규칙 판 번호는 `collector/config.py` 한 곳 — 임대 · 매니페스트가 같은 값을 쓴다(정수 · 1 이상)."""
    assert rl.PROTOCOL == _config.RUNNER_PROTOCOL
    assert type(rl.PROTOCOL) is int and rl.PROTOCOL >= 1


def test_le14_new_doc_carries_protocol_and_code_and_never_sets_min_protocol(monkeypatch):
    """TC-LE-14 · 쥔 PC 는 임대 문서에 규칙 판(protocol) · 코드(code · git 짧은 SHA)를 싣고 닫을 때 자리 기록에도 남긴다 ·
    `min_protocol` 은 코드가 정하지 않는다(사람이 적는다)."""
    monkeypatch.setattr(rl, "code_version", lambda: "abc1234")
    hub = FakeHub()
    _, held, doc, _ = _acquire(hub)
    assert doc["protocol"] == rl.PROTOCOL and doc["code"] == "abc1234" and "min_protocol" not in doc
    rl.release(hub, held, now=T0 + datetime.timedelta(minutes=40), ok=True, rc=0, summary={})
    rec = hub.lease()["slots"]["2026-10-26"]
    assert rec["protocol"] == rl.PROTOCOL and rec["code"] == "abc1234"
    assert "min_protocol" not in hub.lease()


def test_le15_code_version_is_a_short_sha_or_none(monkeypatch):
    """TC-LE-15 · git 이 없거나 실패하면 None(회차를 막지 않는다) · 있으면 짧은 SHA 한 줄."""
    monkeypatch.setattr(rl.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="abc1234\n"))
    assert rl.code_version() == "abc1234"

    def boom(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(rl.subprocess, "run", boom)
    assert rl.code_version() is None
    monkeypatch.setattr(rl.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=128, stdout=""))
    assert rl.code_version() is None


def test_le16_gate_stops_an_old_pc_when_remote_min_protocol_is_higher():
    """TC-LE-16 · 원격 `min_protocol` 이 이 코드의 번호보다 크면 임대를 잡지 않는다(ProtocolTooOld ⊂ LeaseError · 아무것도 쓰지 않음) —
    까닭에 `git pull` 이 있다. 읽기(status)는 막지 않는다."""
    hub = FakeHub()
    _done_once(hub)
    _set_min(hub, rl.PROTOCOL + 1)
    n, before = len(hub.commits), hub.lease()
    with pytest.raises(rl.ProtocolTooOld) as e:
        _acquire(hub, now=T0 + datetime.timedelta(days=1), pc="PC-B")
    assert isinstance(e.value, rl.LeaseError) and not e.value.later
    assert "git pull" in e.value.why and str(rl.PROTOCOL + 1) in e.value.why
    assert len(hub.commits) == n and hub.lease() == before, "멈춘 PC 는 원격에 아무것도 쓰지 않는다"
    head, doc = rl.read(hub)                                  # 읽기는 막지 않는다
    assert doc["min_protocol"] == rl.PROTOCOL + 1 and head == hub.branches[rl.BRANCH]


@pytest.mark.parametrize("value", [None, 0, 1, "9", 2.0, True, [3], {"n": 3}])
def test_le17_gate_ignores_absent_equal_lower_or_garbage(value):
    """TC-LE-17 · `min_protocol` 이 없거나 같거나 낮거나 정수가 아니면 통과 — 칸을 잘못 적어도 모든 PC 가 멈추지 않는다(fail-open 은
    이 칸 하나만 · 임대 자체의 닿지 못함은 그대로 fail-closed)."""
    hub = FakeHub()
    _done_once(hub)
    if value is not None:
        _set_min(hub, value)
    st, held, doc, _ = _acquire(hub, now=T0 + datetime.timedelta(days=1), pc="PC-B")
    assert st == "acquired" and doc["gen"] == 2


def test_le18_new_doc_keeps_a_human_written_min_protocol():
    """TC-LE-18 · 사람이 적어 둔 `min_protocol`(이 코드의 번호 이하)은 다음 회차 문서에 이어진다 — 새 문서를 처음부터 만드는 코드가
    칸을 지우면 문지기가 조용히 사라진다."""
    hub = FakeHub()
    _done_once(hub)
    _set_min(hub, rl.PROTOCOL)
    _, held, doc, _ = _acquire(hub, now=T0 + datetime.timedelta(days=1), pc="PC-B")
    assert doc["min_protocol"] == rl.PROTOCOL and hub.lease()["min_protocol"] == rl.PROTOCOL


def test_le19_holder_renew_does_not_erase_min_protocol_written_mid_run():
    """TC-LE-19 · 돌고 있는 회차 중에 사람이 `min_protocol` 을 적으면(원격 머리가 앞서 412) 쥔 PC 의 다음 갱신 · 닫기가 그 칸을
    지우지 않는다 · 올리기 앞(still_mine)은 번호가 모자라면 ProtocolTooOld 로 올리기를 막는다."""
    hub = FakeHub()
    _, held, _, _ = _acquire(hub)
    _set_min(hub, rl.PROTOCOL + 1)
    before = hub.branches[rl.BRANCH]
    with pytest.raises(rl.ProtocolTooOld):
        rl.still_mine(hub, held)                              # 올리기 앞 — 이 코드는 규칙보다 옛것
    held = rl.renew(hub, held, T0 + datetime.timedelta(minutes=20), force=True)
    assert hub.branches[rl.BRANCH] != before and hub.lease()["min_protocol"] == rl.PROTOCOL + 1
    rl.release(hub, held, now=T0 + datetime.timedelta(minutes=30), ok=True, rc=0, summary={})
    assert hub.lease()["min_protocol"] == rl.PROTOCOL + 1 and hub.lease()["state"] == "done"


def test_le20_status_lines_show_protocol_and_code_and_tolerate_old_docs(monkeypatch):
    """TC-LE-20 · 상태 표는 쥔 PC 의 규칙 판 · 코드를 보이고, 옛 문서(칸 없음)도 깨지지 않는다 — 「누가 어느 판인가」 를 화면 없이 본다."""
    monkeypatch.setattr(rl, "code_version", lambda: "abc1234")
    hub = FakeHub()
    _, _, doc, _ = _acquire(hub)
    text = "\n".join(rl.status_lines(doc, hub.branches[rl.BRANCH]))
    assert "abc1234" in text and f"규칙 {rl.PROTOCOL}" in text
    old_doc = {k: v for k, v in doc.items() if k not in ("protocol", "code")}
    assert "규칙" not in "\n".join(rl.status_lines(old_doc, "0" * 40))


# ── 판 섞임 — 지금 다른 PC 들이 도는 옛 코드(얼린 사본)와 새 코드가 같은 저장소를 쓴다 ────────────────────────


def test_le21_old_code_reads_and_continues_a_new_doc_without_crashing(old_rl):
    """TC-LE-21 · 새 코드가 쓴 문서(protocol · code · min_protocol · 자리 기록의 새 칸)를 옛 코드가 읽고 · 만료 뒤 이어받고 · 갱신하고 ·
    닫는다 — 죽지도 거절하지도 않는다(문지기는 옛 코드에 없다). 옛 코드는 문서를 처음부터 다시 만들어 최상위 새 칸 · `min_protocol`
    을 잃는다 — 그래서 `min_protocol` 은 모든 PC 가 새 코드가 된 뒤에만 올린다(알려진 한계 · 이 단언이 그 사실을 고정한다)."""
    hub = FakeHub()
    _done_once(hub, pc="NEW-A")
    _set_min(hub, rl.PROTOCOL)
    assert "protocol" in hub.lease() and "protocol" in hub.lease()["slots"]["2026-10-26"]
    later = T0 + datetime.timedelta(days=1)
    st, held, doc, _ = old_rl.acquire(hub, now=later, kind="schedule", run=later.isoformat(), pc="OLD-B", pid=7)
    assert st == "acquired" and doc["gen"] == 2 and doc["pc"] == "OLD-B"
    assert doc["slots"]["2026-10-26"]["protocol"] == rl.PROTOCOL, "자리 기록의 새 칸은 지나간다"
    held = old_rl.renew(hub, held, later + datetime.timedelta(minutes=20), force=True)
    assert old_rl.release(hub, held, now=later + datetime.timedelta(minutes=50), ok=True, rc=0, summary={}) is not None
    assert hub.lease()["state"] == "done" and hub.lease()["pc"] == "OLD-B"
    assert "min_protocol" not in hub.lease() and "protocol" not in hub.lease(), "옛 코드는 최상위 새 칸을 잃는다(알려진 한계)"


def test_le22_new_code_takes_over_a_doc_written_by_old_code():
    """TC-LE-22 · 옛 코드가 쓴 문서(protocol 칸 없음)를 새 코드가 이어받으면 새 칸을 싣는다 — 옛 문서는 통과(min_protocol 없음)."""
    hub = FakeHub()
    _acquire(hub, pc="OLD-A")
    d = hub.lease()
    for k in ("protocol", "code"):
        d.pop(k, None)
    rl._write(hub, dict(d, write=uuid.uuid4().hex), hub.branches[rl.BRANCH], "옛 코드가 쓴 꼴")
    st, _, doc, _ = _acquire(hub, now=T0 + datetime.timedelta(minutes=95), pc="NEW-B")
    assert st == "acquired" and doc["protocol"] == rl.PROTOCOL and doc["taken_from"]["pc"] == "OLD-A"


def test_le23_old_and_new_code_see_each_others_running_lease_as_busy(old_rl):
    """TC-LE-23 · 옛 코드가 도는 동안 새 코드는 busy · 새 코드가 도는 동안 옛 코드도 busy — 같은 회차 자리를 둘이 함께 돌지 않는다
    (판이 섞여도 임대 자체의 보장은 그대로)."""
    hub = FakeHub()
    st, _, _, _ = old_rl.acquire(hub, now=T0, kind="schedule", run=T0.isoformat(), pc="OLD-A", pid=1)
    assert st == "acquired"
    st2, held2, _, why2 = _acquire(hub, now=T0 + datetime.timedelta(minutes=5), pc="NEW-B")
    assert st2 == "busy" and held2 is None and "OLD-A" in why2
    hub2 = FakeHub()
    _acquire(hub2, pc="NEW-A")
    st3, held3, doc3, _ = old_rl.acquire(hub2, now=T0 + datetime.timedelta(minutes=5), kind="schedule", run="r", pc="OLD-B", pid=2)
    assert st3 == "busy" and held3 is None and doc3["pc"] == "NEW-A"


def test_le24_runner_turns_protocol_too_old_into_skip_and_blocks_upload(monkeypatch):
    """TC-LE-24 · 러너 연결 — 판 문지기에 걸리면 회차는 돌지 않고(skip · 까닭에 `git pull`) 임대를 쥔 채 규칙이 오른 회차는 백업 올리기를
    막는다(`LeaseError` 갈래의 기존 처리를 그대로 탄다 · 다음 반복 실행이 다시 본다)."""
    from scripts import daily_update as du
    from scripts import hf_sync

    msg = "원격이 규칙 판 2 이상을 요구한다 — 이 저장소에서 `git pull` 로 코드를 먼저 맞춘 뒤 다시"
    monkeypatch.setattr(hf_sync, "_read_json", lambda p: {})
    monkeypatch.setattr(rl, "make_api", lambda: object())

    def too_old(*a, **k):
        raise rl.ProtocolTooOld(msg)

    monkeypatch.setattr(rl, "acquire", too_old)
    run = types.SimpleNamespace(started=T0, say=lambda m: None)
    mode, coord, why, doc = du.coord_begin(run, "schedule")
    assert mode == "skip" and coord is None and doc is None and "git pull" in why

    monkeypatch.setattr(rl, "still_mine", lambda api, held: too_old())
    held = rl.Held("0" * 40, {"gen": 1, "nonce": "n"})
    block = du.coord_before_upload(run, du.Coord(api=object(), kind="schedule", held=held))
    assert block and "git pull" in block


# ── 상태 표의 PC 목록 — min_protocol 을 올려도 되는지 화면 없이 본다(판 문지기 ② · 2026-10-27) ────────────────


def _pc_doc(**slots_and_top) -> dict:
    """상태 표에 넘길 임대 문서 — 최상위(지금 문서를 쓴 PC)와 자리 기록을 직접 짠다."""
    top = {"state": "done", "gen": 7, "slot": "2026-10-26", "kind": "schedule", "pc": "PC-A", "protocol": rl.PROTOCOL, "code": "abc1234"}
    top.update(slots_and_top.pop("top", {}))
    return dict(top, slots=slots_and_top.get("slots", {}))


def test_le32_pc_list_marks_old_code_pcs_and_warns_that_unseen_is_not_new(monkeypatch):
    """TC-LE-32 · PC 가 여럿 — 새 코드(규칙 판 이상)는 ✅ · 규칙 칸이 없거나 낮은 PC 는 「옛 코드」 로 가르고, 그런 PC 가 있으면 올리지 말라고 말한다.
    표에 안 보이는 PC 는 새 코드라는 뜻이 아니다(자리 기록은 며칠만 남는다)."""
    doc = _pc_doc(slots={
        "2026-10-25": {"pc": "PC-B", "ok": True, "rc": 0, "finished_at": "2026-10-25T13:10:00+09:00"},                 # 규칙 칸 없음 = 옛 코드
        "2026-10-26": {"pc": "PC-A", "ok": True, "rc": 0, "protocol": rl.PROTOCOL, "code": "abc1234"},
    })
    text = "\n".join(rl.status_lines(doc, "0" * 40))
    assert "PC-A" in text and "PC-B" in text and "abc1234" in text
    line_b = next(ln for ln in text.splitlines() if "PC-B" in ln and "자리" in ln)
    line_a = next(ln for ln in text.splitlines() if "PC-A" in ln and "자리" in ln)
    assert "옛 코드" in line_b and "옛 코드" not in line_a
    warn = next(ln for ln in text.splitlines() if "올리지" in ln)
    assert "PC-B" in warn and "min_protocol" in warn, "옛 코드 PC 가 있는 동안 min_protocol 을 올리지 말라고 그 PC 를 짚는다"
    assert "안 보이는 PC" in text and "새 코드" in text


def test_le33_pc_list_with_everyone_on_the_new_code_says_so_but_keeps_the_unseen_caveat():
    """TC-LE-33 · 보이는 PC 가 전부 새 코드면 그렇게 말하되 「안 보이는 PC 는 모른다」 는 한 줄을 지우지 않는다 · 더 높은 규칙 판도 통과."""
    doc = _pc_doc(slots={"2026-10-26": {"pc": "PC-A", "ok": True, "rc": 0, "protocol": rl.PROTOCOL, "code": "abc1234"},
                         "2026-10-25": {"pc": "PC-B", "ok": True, "rc": 0, "protocol": rl.PROTOCOL + 1, "code": "def5678"}})
    text = "\n".join(rl.status_lines(doc, "0" * 40))
    assert "옛 코드" not in text and "올리지" not in text
    assert f"모두 규칙 {rl.PROTOCOL} 이상" in text and "안 보이는 PC" in text


def test_le34_pc_list_latest_record_wins_and_the_current_doc_counts():
    """TC-LE-34 · 같은 PC 의 기록이 여럿이면 가장 새 자리가 이긴다(옛 코드였다가 새 코드가 된 PC 는 새 코드) · 지금 문서를 쓴 PC 도 목록에 든다."""
    doc = _pc_doc(top={"pc": "PC-C", "protocol": rl.PROTOCOL, "code": "c0ffee1", "slot": "2026-10-27", "state": "running"},
                  slots={"2026-10-24": {"pc": "PC-B", "ok": True, "rc": 0},
                         "2026-10-26": {"pc": "PC-B", "ok": True, "rc": 0, "protocol": rl.PROTOCOL, "code": "bbb2222"}})
    lines = rl.status_lines(doc, "0" * 40)
    pcs = rl.pc_records(doc)
    assert set(pcs) == {"PC-B", "PC-C"} and pcs["PC-B"]["slot"] == "2026-10-26" and pcs["PC-B"]["protocol"] == rl.PROTOCOL
    assert pcs["PC-C"]["slot"] == "2026-10-27", "아직 닫히지 않은 지금 문서의 PC"
    assert not any("옛 코드" in ln and "PC-B" in ln for ln in lines)


def test_le35_pc_list_with_no_pc_at_all_adds_nothing_and_does_not_crash():
    """TC-LE-35 · PC 가 하나도 안 보이는 문서(옛 형식 · 비어 있음) · 문서 자체가 없는 경우 — 목록 구역을 만들지 않고 깨지지 않는다."""
    bare = {"state": "done", "gen": 1, "slot": "2026-10-20", "slots": {}}
    text = "\n".join(rl.status_lines(bare, "0" * 40))
    assert "PC 별" not in text
    assert rl.pc_records(bare) == {} and rl.pc_records(None) == {}
    assert "PC 별" not in "\n".join(rl.status_lines(None, None))


def test_le36_pythonw_without_stderr_turns_off_hf_progress_bars(monkeypatch):
    """TC-LE-36 · 작업 스케줄러의 ``pythonw`` 는 표준오류가 None — HF 다운로드 진행 막대(tqdm)가 ``None.write`` 로
    AttributeError 를 내 임대 파일을 못 받고 올리기를 건너뛰었다(2026-10-27 19:05 회차). 표준오류가 없을 때만 끄고, 터미널에서는 그대로 둔다."""
    import sys

    from huggingface_hub.utils import are_progress_bars_disabled, disable_progress_bars, enable_progress_bars

    monkeypatch.delenv("HF_HUB_DISABLE_PROGRESS_BARS", raising=False)   # 시험이 끝나면 원래대로
    enable_progress_bars()
    try:
        rl.quiet_hf_progress()
        assert not are_progress_bars_disabled(), "표준오류가 있으면(터미널) 건드리지 않는다"

        monkeypatch.setattr(sys, "stderr", None)
        rl.quiet_hf_progress()
        assert are_progress_bars_disabled(), "pythonw(표준오류 없음)에서는 끈다"
    finally:
        enable_progress_bars()
