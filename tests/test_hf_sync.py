"""여러 PC 맞추기(`scripts/hf_sync.py`) 시험 (TC-HS) — 설계 `docs/phase-3/02-design/system/여러PC-회차-설계.md` 5절.

지키려는 것 —
1. 원격이 기준 그대로면 받지 않는다(머리만 옮겨도 · 임대 · 카드 커밋).
2. 원격만 바꾼 조각은 원격과 **똑같이** 갈아 끼운다 — 내용 지문이 같아야 커밋하고, 다음 내보내기가 아무것도 다시 쓰지 않는다.
3. 이 PC 만 바꾼 조각은 지우지 않는다(다음 올리기가 싣는다) · 둘 다 바꾼 조각은 겹침으로 멈춘다(``--discard-local`` 이면 원격 것).
4. 응답 원문은 없는 줄만 더한다 · 따라가는 PC 는 복구용 표를 건너뛰고, 그 PC 가 나중에 회차를 잡으면 전부 맞춘다.
5. 받은 파일 · 넣은 줄이 매니페스트와 다르면 아무것도 바꾸지 않는다 · 새 PC 는 전부 받아 복원한다.

실제 수집기 스키마(`collector.db`)로 만든 작은 DB 두 개(A = 회차를 돈 PC · B = 이 PC)와 진짜 내보내기(`hf_dataset.export`)를 쓴다.
원격은 A 의 내보내기 폴더를 판마다 담는 가짜(`FakeRemote`)다 — 진짜 HF 에 닿지 않는다.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sqlite3
import tempfile
import types
from pathlib import Path

import pytest

from collector import db as collector_db
from scripts import hf_dataset as hd
from scripts import hf_sync as hs

TABLES = ["price_daily", "ingest_day", "raw_response", "market_calendar"]
P2025 = "price_daily/year=2025/part-00000.parquet"
P2026 = "price_daily/year=2026/part-00000.parquet"
RAW = "raw_response/portal.parquet"


class FakeRemote:
    """가짜 HF main — 판마다(커밋 SHA) 내보내기 폴더의 파일을 담는다. 고정 SHA 로 받으면 그 판의 파일."""

    def __init__(self):
        self.snap, self.head, self.n, self.downloads = {}, None, 0, []

    def push(self, folder: Path) -> str:
        self.n += 1
        sha = f"{self.n:040x}"
        self.snap[sha] = {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*")
                          if p.is_file() and ".cache" not in p.parts}
        self.head = sha
        return sha

    def move_head_only(self) -> str:                    # 임대 · 카드처럼 데이터가 같은 커밋
        self.n += 1
        sha = f"{self.n:040x}"
        self.snap[sha] = dict(self.snap[self.head])
        self.head = sha
        return sha

    def repo_info(self, repo_id, *, repo_type=None, revision=None, timeout=None, **k):
        return types.SimpleNamespace(sha=self.head, private=True)

    def hf_hub_download(self, repo_id, filename, *, repo_type=None, revision=None, local_dir=None, **k):
        from huggingface_hub.errors import EntryNotFoundError

        files = self.snap.get(revision) or {}
        if filename not in files:
            raise EntryNotFoundError(filename)
        self.downloads.append(filename)
        p = (Path(local_dir) if local_dir else Path(tempfile.mkdtemp())) / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(files[filename])
        return str(p)


class PC:
    def __init__(self, root: Path):
        self.root = root
        self.db = root / "collector" / "market.sqlite3"
        self.exp = root / "hf_export"
        self.state = root / "state"
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self.state.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A · B 두 PC 와 원격 — ``use(pc)`` 로 모듈 경로를 그 PC 로 돌린다(내보내기 · 매니페스트 · 기준 · 판정 기록 모두)."""
    monkeypatch.setenv("QURIOUS_RAW_SHARING", "1")
    monkeypatch.setattr(hd, "write_status_snapshot", lambda **k: None)          # 진짜 상태 폴더를 건드리지 않게

    def use(pc: PC) -> PC:
        monkeypatch.setattr(hd.config, "DB_PATH", pc.db)
        for name, rel in (("EXPORT_DIR", None), ("MANIFEST_PATH", "meta/manifest.json"), ("README_PATH", "README.md"),
                          ("RESTORE_LOG_PATH", "meta/last_restore.json"), ("VERIFY_LOG_PATH", "meta/last_verify.json")):
            monkeypatch.setattr(hd, name, pc.exp / rel if rel else pc.exp)
        monkeypatch.setattr(hd, "RESTORE_OK_PATH", pc.state / "hf_restore_last_ok.json")
        monkeypatch.setattr(hs, "BASE_PATH", pc.state / "hf_sync_base.json")
        monkeypatch.setattr(hs, "LAST_PATH", pc.state / "hf_sync_last.json")
        monkeypatch.setattr(hs, "STAGE_DIR", pc.root / "stage")
        return pc

    return types.SimpleNamespace(a=PC(tmp_path / "A"), b=PC(tmp_path / "B"), remote=FakeRemote(), use=use)


def _raw(i: int) -> tuple:
    body = f"payload-{i}".encode()
    return ("portal", f"price/2026010{i}", f"2026-10-0{i}T12:31:00+09:00", gzip.compress(body),
            hashlib.sha256(body).hexdigest(), len(body), "gzip", 200, "")


def _fill(pc: PC) -> None:
    conn = collector_db.connect(pc.db)
    conn.executemany("INSERT INTO price_daily (bas_dt, srtn_cd, itms_nm, clpr, mkp) VALUES (?,?,?,?,?)",
                     [("20251230", "005930", "삼성전자", 53000, 52900), ("20251230", "000660", "SK하이닉스", 170000, 169000),
                      ("20260102", "005930", "삼성전자", 54000, 53500), ("20260102", "000660", "SK하이닉스", 172000, 171000)])
    conn.executemany("INSERT INTO ingest_day (source, bas_dt, status, rows, attempts, updated_at) VALUES (?,?,?,?,?,?)",
                     [("portal", "20260102", "ok", 2, 1, "2026-01-02T13:00:00+09:00")])
    conn.executemany("INSERT INTO raw_response (source, target, fetched_at, body, sha256, bytes, compression, http_status, note) "
                     "VALUES (?,?,?,?,?,?,?,?,?)", [_raw(1), _raw(2)])
    conn.executemany("INSERT INTO market_calendar (cal_date, is_trading_day, reason, basis, note, updated_at) VALUES (?,?,?,?,?,?)",
                     [("2026-01-01", 0, "신정", "kasi", "", "2026-01-01T00:00:00+09:00"),
                      ("2026-01-02", 1, "", "price", "", "2026-01-02T13:00:00+09:00")])
    conn.commit()
    conn.close()


def _sql(pc: PC, *stmts) -> None:
    conn = sqlite3.connect(pc.db)
    for s in stmts:
        conn.execute(*s) if isinstance(s, tuple) else conn.execute(s)
    conn.commit()
    conn.close()


def _rows(pc: PC, table: str, where: str = "") -> list:
    conn = sqlite3.connect(pc.db)
    try:
        return conn.execute(f"SELECT * FROM {table} {where} ORDER BY 1, 2, 3").fetchall()
    finally:
        conn.close()


def _export_upload(w, pc: PC) -> str:
    """그 PC 에서 내보내고 「올린 것」 으로 적은 뒤 원격에 판 하나 — 새 머리. 기준도 그 판으로(진짜 올리기와 같게)."""
    w.use(pc)
    hd.export(tables=TABLES, verbose=False)
    man = hd._load_manifest()
    man["uploaded"] = {"files": {p: e["sha256"] for p, e in hs.files_of(man).items()}, "repo_id": hd.REPO_ID}
    hd._write_json_atomic(hd.MANIFEST_PATH, man)
    sha = w.remote.push(pc.exp)
    hs.after_upload(man, sha)
    return sha


def _clone(w, src: PC, dst: PC) -> None:
    """dst 를 src 와 같은 판으로 — 수집 DB · 내보내기 폴더 · 기준(그 PC 가 마지막으로 원격과 같았던 판)."""
    shutil.copy2(src.db, dst.db)
    shutil.copytree(src.exp, dst.exp)
    shutil.copy2(src.state / "hf_sync_base.json", dst.state / "hf_sync_base.json")


@pytest.fixture
def synced(world):
    """A 가 돌고 올린 판 r1 · B 는 r1 과 같다."""
    w = world
    _fill(w.use(w.a))
    w.r1 = _export_upload(w, w.a)
    _clone(w, w.a, w.b)
    return w


def test_hs01_fingerprint_matches_backup_tool(synced):
    """TC-HS-01 · 파일 구성 지문은 백업 도구의 매니페스트 지문과 같은 셈이다."""
    w = synced
    w.use(w.a)
    man = hd._load_manifest()
    assert hs.fp_of(hs.files_of(man)) == hd._manifest_fp(man)


def test_hs02_nothing_to_do_when_remote_is_the_base(synced):
    """TC-HS-02 · 머리가 기준과 같으면 아무것도 받지 않는다 · 머리만 옮긴 판(데이터 같음)이면 기준의 머리만 바꾼다."""
    w = synced
    w.use(w.b)
    rc, rec = hs.pull(w.remote)
    assert (rc, rec["result"]) == (0, "same") and w.remote.downloads == []
    new = w.remote.move_head_only()
    rc, rec = hs.pull(w.remote)
    assert (rc, rec["result"]) == (0, "same") and hs.load_base()["main"] == new
    assert w.remote.downloads == ["meta/manifest.json"], "매니페스트 하나만 받았다"


def test_hs03_remote_only_change_is_replaced_exactly(synced):
    """TC-HS-03 · 원격만 바꾼 조각(A 가 2026 에 한 줄 더 · 한 값 고침)은 B 에서 원격과 똑같아지고, 기준 = 원격 · 다음 내보내기는 0파일."""
    w = synced
    _sql(w.use(w.a), "INSERT INTO price_daily (bas_dt, srtn_cd, itms_nm, clpr, mkp) VALUES ('20260105','005930','삼성전자',55000,54100)",
         "UPDATE price_daily SET clpr = 172500 WHERE bas_dt = '20260102' AND srtn_cd = '000660'")
    r2 = _export_upload(w, w.a)
    w.use(w.b)
    rc, rec = hs.pull(w.remote)
    assert (rc, rec["result"]) == (0, "synced") and rec["plan"]["replace"] >= 1 and rec["plan"]["conflict"] == 0
    assert _rows(w.b, "price_daily") == _rows(w.a, "price_daily")
    base = hs.load_base()
    assert base["main"] == r2 and not base["partial"]
    w.use(w.a)
    fp_a = hs.fp_of(hs.files_of(hd._load_manifest()))
    assert base["fp"] == fp_a
    w.use(w.b)
    remote_man = json.loads(w.remote.snap[w.remote.head]["meta/manifest.json"])
    assert hs.files_of(hd._load_manifest())[P2026]["sha256"] == hs.files_of(remote_man)[P2026]["sha256"]
    tally = hd.export(tables=TABLES, verbose=False)
    assert tally["files"] == 0, "맞춘 뒤 내보내기는 아무것도 다시 쓰지 않는다(내용 지문 · 파일 크기가 원격과 같다)"
    assert hd.changed_since_upload() == [], "원격에 있는 것은 올린 것으로 적었다"


def test_hs04_identical_local_content_is_adopted(synced):
    """TC-HS-04 · B 가 이미 원격과 같은 내용이면(같은 줄을 받았다) DB 를 다시 쓰지 않고 파일 · 목록만 받는다(adopt)."""
    w = synced
    stmt = "INSERT INTO price_daily (bas_dt, srtn_cd, itms_nm, clpr, mkp) VALUES ('20260105','005930','삼성전자',55000,54100)"
    _sql(w.use(w.a), stmt)
    _export_upload(w, w.a)
    _sql(w.b, stmt)
    w.use(w.b)
    rc, rec = hs.pull(w.remote)
    assert rc == 0 and rec["plan"]["adopt"] >= 1 and rec["plan"]["replace"] == 0 and rec["rows"] == 0
    assert (w.b.exp / P2026).exists() and _rows(w.b, "price_daily") == _rows(w.a, "price_daily")


def test_hs05_both_changed_same_part_is_a_conflict(synced):
    """TC-HS-05 · A 도 B 도 2026 조각을 다르게 바꿨다(B 는 아직 올리지 않음) → 65 · B 는 그대로(줄 · 매니페스트 · 기준) · 마지막
    결과 conflict. ``discard_local`` 이면 B 의 그 조각은 원격 것이 된다."""
    w = synced
    _sql(w.use(w.a), "UPDATE price_daily SET clpr = 54100 WHERE bas_dt = '20260102' AND srtn_cd = '005930'")
    _export_upload(w, w.a)
    _sql(w.b, "UPDATE price_daily SET clpr = 99999 WHERE bas_dt = '20260102' AND srtn_cd = '005930'")
    w.use(w.b)
    before_rows, before_man, before_base = _rows(w.b, "price_daily"), hd._load_manifest(), hs.load_base()
    rc, rec = hs.pull(w.remote)
    assert rc == hs.EX_CONFLICT and rec["result"] == "conflict" and P2026 in rec["parts"]
    assert _rows(w.b, "price_daily") == before_rows and hd._load_manifest() == before_man and hs.load_base() == before_base
    rc, rec = hs.pull(w.remote, discard_local=True)
    assert rc == 0 and rec["discarded"] == [P2026] and _rows(w.b, "price_daily") == _rows(w.a, "price_daily")


def test_hs06_local_only_change_in_other_part_is_kept(synced):
    """TC-HS-06 · A 는 2026 · B 는 2025 를 바꿨다 → 겹치지 않는다. B 의 2025 변경은 남고(다음 올리기가 싣는다) 2026 은 원격과 같다."""
    w = synced
    _sql(w.use(w.a), "INSERT INTO price_daily (bas_dt, srtn_cd, itms_nm, clpr, mkp) VALUES ('20260105','005930','삼성전자',55000,54100)")
    _export_upload(w, w.a)
    _sql(w.b, "UPDATE price_daily SET clpr = 53100 WHERE bas_dt = '20251230' AND srtn_cd = '005930'")
    w.use(w.b)
    rc, rec = hs.pull(w.remote)
    assert rc == 0 and rec["plan"]["conflict"] == 0
    assert _rows(w.b, "price_daily", "WHERE bas_dt LIKE '2026%'") == _rows(w.a, "price_daily", "WHERE bas_dt LIKE '2026%'")
    assert _rows(w.b, "price_daily", "WHERE bas_dt = '20251230' AND srtn_cd = '005930'")[0][5] == 53100
    w.use(w.b)
    hd.export(tables=TABLES, verbose=False)
    assert hd.changed_since_upload() == [P2025], "B 만 바꾼 조각은 올릴 것으로 남는다"


def test_hs07_raw_responses_are_merged_not_replaced(synced):
    """TC-HS-07 · 응답 원문은 없는 줄만 더한다 — B 가 올리지 않은 원문 한 줄이 있어도 겹침이 아니고, A 의 새 원문과 함께 남는다."""
    w = synced
    _sql(w.use(w.a), ("INSERT INTO raw_response VALUES (?,?,?,?,?,?,?,?,?)", _raw(3)))
    _export_upload(w, w.a)
    _sql(w.b, ("INSERT INTO raw_response VALUES (?,?,?,?,?,?,?,?,?)", _raw(4)))
    w.use(w.b)
    rc, rec = hs.pull(w.remote)
    assert rc == 0 and rec["plan"]["union"] == 1 and rec["plan"]["conflict"] == 0
    assert [r[1] for r in _rows(w.b, "raw_response")] == ["price/20260101", "price/20260102", "price/20260103", "price/20260104"]


def test_hs08_follow_skips_restore_only_and_lead_catches_up(synced):
    """TC-HS-08 · 따라가는 PC 는 복구용 표(원문 · 수집 상태)를 건너뛰고 기준을 「일부」 로 적는다 — 머리가 같아도 회차를 잡은 PC 의
    맞추기는 「같음」 으로 지나치지 않고 원문까지 맞춘다(올리기 앞의 「앞섰나」 도 앞섰다고 본다)."""
    w = synced
    _sql(w.use(w.a), ("INSERT INTO raw_response VALUES (?,?,?,?,?,?,?,?,?)", _raw(3)),
         "INSERT INTO price_daily (bas_dt, srtn_cd, itms_nm, clpr, mkp) VALUES ('20260105','005930','삼성전자',55000,54100)")
    head = _export_upload(w, w.a)
    w.use(w.b)
    rc, rec = hs.pull(w.remote, mode="follow")
    assert rc == 0 and rec["plan"]["skip"] >= 1 and len(_rows(w.b, "raw_response")) == 2
    base = hs.load_base()
    assert base["partial"] and base["main"] == head
    assert hs.pull(w.remote, mode="follow")[1]["result"] == "same", "따라가기는 같은 머리에서 다시 받지 않는다"
    assert hs.behind(w.remote) is not None, "일부만 맞춘 PC 는 올리기 앞에서 앞섰다고 본다"
    rc, rec = hs.pull(w.remote, mode="lead")
    assert rc == 0 and rec["result"] == "synced" and len(_rows(w.b, "raw_response")) == 3
    assert not hs.load_base()["partial"] and hs.behind(w.remote) is None


def test_hs09_table_missing_here_is_created_from_remote_ddl(synced):
    """TC-HS-09 · 이 PC 에 없는 표(예: 새 판 코드가 더한 표)는 원격 매니페스트의 DDL 로 만들고 채운다."""
    w = synced
    _sql(w.use(w.a), "INSERT INTO market_calendar VALUES ('2026-01-05', 1, '', 'price', '', '2026-01-05T13:00:00+09:00')")
    _export_upload(w, w.a)
    _sql(w.b, "DROP TABLE market_calendar")
    w.use(w.b)
    rc, rec = hs.pull(w.remote)
    assert rc == 0 and _rows(w.b, "market_calendar") == _rows(w.a, "market_calendar")


def test_hs10_bad_download_or_bad_rows_change_nothing(synced, monkeypatch):
    """TC-HS-10 · 받은 파일의 sha256 이 매니페스트와 다르면 아무것도 바꾸지 않는다 · 넣은 뒤 내용 지문이 다르면 그 조각을 되돌린다."""
    w = synced
    _sql(w.use(w.a), "UPDATE price_daily SET clpr = 54100 WHERE bas_dt = '20260102' AND srtn_cd = '005930'")
    _export_upload(w, w.a)
    w.use(w.b)
    before = _rows(w.b, "price_daily")
    w.remote.snap[w.remote.head][P2026] = b"broken"
    rc, rec = hs.pull(w.remote)
    assert rc == 1 and "sha256" in rec["why"] and _rows(w.b, "price_daily") == before
    # 매니페스트의 지문을 틀리게 — 파일은 맞지만 넣은 뒤 지문이 다르다 → 되돌림
    _sql(w.use(w.a), "UPDATE price_daily SET clpr = 54200 WHERE bas_dt = '20260102' AND srtn_cd = '005930'")
    _export_upload(w, w.a)
    man = json.loads(w.remote.snap[w.remote.head]["meta/manifest.json"])
    for f in man["tables"]["price_daily"]["files"]:
        if f["path"] == P2026:
            f["sig"] = "0" * 16
    w.remote.snap[w.remote.head]["meta/manifest.json"] = json.dumps(man).encode()
    w.use(w.b)
    rc, rec = hs.pull(w.remote)
    assert rc == 1 and "내용 지문" in rec["why"] and _rows(w.b, "price_daily") == before


def test_hs11_schema_difference_stops(synced):
    """TC-HS-11 · 이 PC 의 표 모양(칸)이 원격과 다르면 멈춘다 — 코드를 먼저 맞춘다(git pull)."""
    w = synced
    _sql(w.use(w.a), "UPDATE market_calendar SET note = '고침' WHERE cal_date = '2026-01-02'")
    _export_upload(w, w.a)
    _sql(w.b, "ALTER TABLE market_calendar ADD COLUMN extra TEXT")
    w.use(w.b)
    rc, rec = hs.pull(w.remote)
    assert rc == 1 and "표 모양" in rec["why"]


def test_hs12_bootstrap_base_from_upload_record(synced):
    """TC-HS-12 · 기준 파일이 없는 PC(이 판 앞) — 매니페스트의 올린 기록이 기준이다. 내용 지문은 지금 파일이 올린 것과 같을 때만 안다."""
    w = synced
    w.use(w.b)
    (w.b.state / "hf_sync_base.json").unlink()
    base = hs.base_or_bootstrap()
    assert base["by"] == "bootstrap" and base["fp"] == hs.fp_of(hs.files_of(hd._load_manifest()))
    assert base["files"][P2026]["sig"] == hs.files_of(hd._load_manifest())[P2026]["sig"]
    assert hs.behind(w.remote) is None
    man = hd._load_manifest()
    man["uploaded"]["files"][P2026] = "다른 판"
    hd._write_json_atomic(hd.MANIFEST_PATH, man)
    assert hs.bootstrap_base(man)["files"][P2026]["sig"] is None, "올린 것과 다르면 지문을 모른다(겹침 쪽으로)"


def test_hs13_behind_says_why(synced):
    """TC-HS-13 · 올리기 앞의 「앞섰나」 — 기준과 같으면 None · 다른 PC 가 올렸으면 까닭 · 원격에 아직 데이터가 없으면 None(처음 올리기)."""
    w = synced
    w.use(w.b)
    assert hs.behind(w.remote) is None
    _sql(w.use(w.a), "INSERT INTO price_daily (bas_dt, srtn_cd, itms_nm, clpr, mkp) VALUES ('20260106','005930','삼성전자',55500,55000)")
    _export_upload(w, w.a)
    w.use(w.b)
    why = hs.behind(w.remote)
    assert why and "앞섰다" in why and "sync" in why
    empty = FakeRemote()
    empty.head = "f" * 40
    empty.snap[empty.head] = {".gitattributes": b""}
    assert hs.behind(empty) is None


def test_hs14_full_restore_for_a_new_pc(synced):
    """TC-HS-14 · 수집 DB 가 없는 새 PC — 원격 전부를 받아 복원(내용 지문 대조)하고 기준 = 원격. DB 가 있으면 하지 않는다."""
    w = synced
    c = PC(w.a.root.parent / "C")
    w.use(c)
    rc, rec = hs.full(w.remote)
    assert (rc, rec["result"]) == (0, "full")
    for t in TABLES:
        assert _rows(c, t) == _rows(w.a, t), t
    assert hs.load_base()["main"] == w.remote.head and hd._load_manifest()["uploaded"]["files"]
    rc, rec = hs.full(w.remote)
    assert rc == 1 and rec["result"] == "exists"
