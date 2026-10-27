import copy
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from scripts import hf_collector_follower as s
from app.services import hf_snapshot as proof

import os
import tempfile


def _can_symlink():
    """수신기는 releases/<세대> 를 심볼릭 링크로 바꾸고 ``current`` 를 ``os.replace`` 로 원자적으로 갈아 끼운다 — POSIX 전용 동작이다.
    Windows 는 일반 권한이면 링크를 못 만들고(WinError 1314), 개발자 모드로 만들 수 있어도 링크 디렉터리를 ``os.replace`` 로 못 바꾼다(WinError 5)."""
    if os.name == "nt":
        return False
    with tempfile.TemporaryDirectory() as folder:
        try:
            os.symlink(folder, os.path.join(folder, "link"), target_is_directory=True)
            return True
        except OSError:
            return False


needs_symlink = pytest.mark.skipif(not _can_symlink(), reason="수신기의 원자적 세대 전환은 POSIX 전용(Windows 는 링크 권한 · os.replace 모두 안 됨) — 수신기는 Linux 컨테이너 전용")


@pytest.mark.parametrize("stamp,expected", [
    ("2026-10-27T12:40:00+09:00", 900),
    ("2026-10-27T12:55:00+09:00", 300),
    ("2026-10-27T13:00:00+09:00", 60),
    ("2026-10-27T04:05:00+00:00", 60),
    ("2026-10-27T15:29:00+09:00", 60),
    ("2026-10-27T15:30:00+09:00", 900),
])
def test_publication_poll_interval_uses_kst(stamp, expected):
    assert s.next_poll_seconds(datetime.fromisoformat(stamp), interval=900) == expected


@pytest.fixture
def metadata():
    files = {name: {"files": [{"path": name + "/2026.parquet", "sha256": "a" * 64, "bytes": 4}]}
             for name in ("price_daily", "price_adjusted", "market_calendar")}
    manifest = {"partial": False, "generated_at": "2026-10-26T19:49:02+09:00", "tables": files}
    verification = {"at": "2026-10-26T19:49:24+09:00", "fails": 0, "checks": 97, "full": True,
                    "manifest_fp": proof.manifest_fingerprint(manifest), "manifest_generated_at": manifest["generated_at"]}
    record = {"run": {"started_at": "2026-10-26T18:54:23+09:00", "recorded_at": "2026-10-26T19:49:26+09:00",
        "finished_at": None, "stopped": None, "after": {"price_max": "20261023"},
        "steps": [{"name": n, "rc": 0} for n in proof.REQUIRED_STEPS],
        "pending_steps": ["upload", "ohlcv_upload", "journal_upload", "sector_laws"]}, "history": []}
    return record, manifest, verification


def test_uploaded_data_is_ready_without_whole_run_completion(metadata):
    record, manifest, verification = metadata
    result = proof.validate_snapshot("a" * 40, record, manifest, verification)
    assert result["price_max"] == "20261023"
    assert result["finished_at"] is None and result["completion_is_original"] is False
    assert record["run"]["finished_at"] is None


@pytest.mark.parametrize("bad", ["partial", "missing_table", "wrong_fingerprint", "old_verify", "old_run", "future",
    "failed_verify", "not_full", "bool_fails", "bad_step", "duplicate_step", "stopped", "unknown_pending", "bad_price",
    "path_escape", "duplicate_path", "missing_time", "missing_pending", "warn", "bool_rc"])
def test_invalid_evidence_is_rejected(metadata, bad):
    record, manifest, verification = metadata
    run = record["run"]
    if bad == "partial": manifest["partial"] = True
    if bad == "missing_table": manifest["tables"].pop("price_daily")
    if bad == "wrong_fingerprint": verification["manifest_fp"] = "different"
    if bad == "old_verify": verification["manifest_generated_at"] = "2026-10-25T19:49:02+09:00"
    if bad == "old_run": run["recorded_at"] = "2026-10-25T19:49:26+09:00"
    if bad == "future": run["recorded_at"] = "2099-10-25T19:49:26+09:00"
    if bad == "failed_verify": verification["fails"] = 1
    if bad == "not_full": verification["full"] = False
    if bad == "bool_fails": verification["fails"] = False
    if bad == "bad_step": run["steps"][0]["rc"] = 69
    if bad == "bool_rc": run["steps"][0]["rc"] = False
    if bad == "warn": run["steps"][0]["warn"] = True
    if bad == "duplicate_step": run["steps"].append(dict(run["steps"][0]))
    if bad == "stopped": run["stopped"] = "price failed"
    if bad == "unknown_pending": run["pending_steps"].append("mutate_prices")
    if bad == "missing_pending": run.pop("pending_steps")
    if bad == "bad_price": run["after"]["price_max"] = "20260230"
    if bad == "path_escape": manifest["tables"]["price_daily"]["files"][0]["path"] = "../escape"
    if bad == "duplicate_path": manifest["tables"]["price_daily"]["files"].append(dict(manifest["tables"]["price_daily"]["files"][0]))
    if bad == "missing_time": run["started_at"] = None
    with pytest.raises(ValueError):
        proof.validate_snapshot("a" * 40, record, manifest, verification)


def install_receipt(folder, metadata, commit="a" * 40, now=None):
    record, manifest, verification = metadata
    receipt = proof.validate_snapshot(commit, record, manifest, verification, now=now)
    receipt.update(files_verified=True, data_ready_at="2026-10-26T20:00:00+09:00")
    for name, value in {"meta/run_record.json": record, "meta/manifest.json": manifest, "meta/last_verify.json": verification,
                        "provenance.json": receipt, "state/daily_update_last.json": record["run"]}.items():
        s.atomic_json(folder / name, value)
    return receipt


@pytest.fixture
def received(tmp_path, metadata):
    from datetime import date, timedelta
    folder = tmp_path / 'releases' / 'fixture'
    install_receipt(folder, metadata)
    with sqlite3.connect(folder / 'market.sqlite3') as conn:
        conn.execute('CREATE TABLE market_calendar (cal_date TEXT PRIMARY KEY, is_trading_day INTEGER)')
        for n in range(40):
            day = date(2026, 10, 1) + timedelta(days=n)
            conn.execute('INSERT INTO market_calendar VALUES (?,?)', (day.isoformat(), int(day.weekday() < 5)))
    s.publish(tmp_path, folder)
    return tmp_path, folder, metadata


@pytest.mark.parametrize('hour,state', [(12, 'before_publication'), (13, 'waiting_for_hf'), (16, 'late')])
@needs_symlink
def test_hf_waits_for_required_day_without_using_old_prices(received, hour, state):
    root, _, _ = received
    result = s.price_readiness(root, datetime.fromisoformat(f'2026-10-27T{hour}:05:00+09:00'))
    assert result['ready'] is False and result['state'] == state
    assert result['price_date'] == '2026-10-23' and result['required_price_date'] == '2026-10-26'


@needs_symlink
def test_received_current_day_proof_is_ready_but_does_not_order(received):
    root, folder, metadata = received
    record, manifest, verification = metadata
    record['run'].update(started_at='2026-10-27T12:30:00+09:00', recorded_at='2026-10-27T12:55:00+09:00')
    record['run']['after']['price_max'] = '20261026'
    manifest['generated_at'] = '2026-10-27T12:50:00+09:00'
    verification.update(at='2026-10-27T12:54:00+09:00', manifest_generated_at=manifest['generated_at'])
    receipt = install_receipt(folder, metadata, now=datetime.fromisoformat('2026-10-27T13:05:00+09:00'))
    receipt['data_ready_at'] = '2026-10-27T13:01:00+09:00'
    s.atomic_json(folder / 'provenance.json', receipt)
    result = s.price_readiness(root, datetime.fromisoformat('2026-10-27T13:05:00+09:00'))
    assert result['ready'] is True and result['state'] == 'ready'
    assert result['price_date'] == result['required_price_date'] == '2026-10-26'
    assert record['run']['finished_at'] is None


@needs_symlink
def test_calendar_gap_and_corrupted_proof_fail_closed(received):
    root, folder, _ = received
    now = datetime.fromisoformat('2026-10-27T13:05:00+09:00')
    with sqlite3.connect(folder / 'market.sqlite3') as conn:
        conn.execute("DELETE FROM market_calendar WHERE cal_date='2026-10-26'")
    assert s.price_readiness(root, now)['state'] == 'unavailable'
    (folder / 'provenance.json').write_text('{invalid')
    assert s.price_readiness(root, now)['ready'] is False


@needs_symlink
def test_holiday_does_not_wait_for_nonexistent_bar(received):
    root, _, _ = received
    result = s.price_readiness(root, datetime.fromisoformat('2026-10-31T13:05:00+09:00'))
    assert result['state'] == 'closed' and result['ready'] is False


def test_proof_rejects_mutated_local_record_or_fabricated_finish(tmp_path, metadata):
    install_receipt(tmp_path, metadata)
    assert proof.read_ready_proof(tmp_path)["finished_at"] is None
    local = metadata[0]["run"]
    local["finished_at"] = "2026-10-26T19:50:00+09:00"
    s.atomic_json(tmp_path / "state/daily_update_last.json", local)
    with pytest.raises(ValueError, match="local run record"):
        proof.read_ready_proof(tmp_path)


@needs_symlink
def test_follower_uses_head_commit_without_date_tag_and_reuses_verified_generation(tmp_path, metadata, monkeypatch):
    head = "a" * 40
    folder = tmp_path / "releases" / (head + "-ready-v1")
    install_receipt(folder, metadata)
    (folder / "market.sqlite3").write_bytes(b"verified-db-fixture")
    follower = s.Follower("test-token", tmp_path)
    calls = []
    def get(url):
        calls.append(url)
        responses = {s.API: {"private": True, "sha": head},
            f"{s.RESOLVE}/{head}/meta/run_record.json": metadata[0],
            f"{s.RESOLVE}/{head}/meta/manifest.json": metadata[1],
            f"{s.RESOLVE}/{head}/meta/last_verify.json": metadata[2]}
        return copy.deepcopy(responses[url])  # /refs와 날짜 태그를 부르면 실패한다.
    monkeypatch.setattr(follower, "get_json", get)
    result = follower.cycle()
    assert result["generation"] == folder.name
    assert result["provenance"]["finished_at"] is None
    s.atomic_json(tmp_path / "status.json", result)
    calls.clear()
    assert follower.cycle()["status"] == "current"
    assert calls == [s.API]


@needs_symlink
def test_mismatched_metadata_keeps_current_generation(tmp_path, metadata, monkeypatch):
    old = generation(tmp_path, "old", "old")
    s.publish(tmp_path, old)
    record, manifest, verification = metadata
    verification["manifest_fp"] = "wrong"
    follower = s.Follower("test-token", tmp_path)
    monkeypatch.setattr(follower, "get_json", lambda url: {s.API: {"private": True, "sha": "a" * 40},
        f"{s.RESOLVE}/{'a' * 40}/meta/run_record.json": record,
        f"{s.RESOLVE}/{'a' * 40}/meta/manifest.json": manifest,
        f"{s.RESOLVE}/{'a' * 40}/meta/last_verify.json": verification}[url])
    with pytest.raises(ValueError, match="verification"):
        follower.cycle()
    assert (tmp_path / "current").resolve() == old


def generation(root,name,text):
 p=root/'releases'/name;p.mkdir(parents=True)
 (p/'market.sqlite3').write_text(text)
 s.atomic_json(p/'state/daily_update_last.json',{'source':text})
 return p

@needs_symlink
def test_whole_generation_switch_is_atomic_and_rejects_incomplete(tmp_path):
 a=generation(tmp_path,'a','old');b=generation(tmp_path,'b','new')
 s.publish(tmp_path,a)
 assert (tmp_path/'current/market.sqlite3').read_text()=='old'
 s.publish(tmp_path,b)
 assert (tmp_path/'current/market.sqlite3').read_text()=='new'
 assert json.loads((tmp_path/'current/state/daily_update_last.json').read_text())=={'source':'new'}
 assert (a/'market.sqlite3').read_text()=='old'
 bad=tmp_path/'releases/bad';bad.mkdir()
 with pytest.raises(ValueError):s.publish(tmp_path,bad)
 assert (tmp_path/'current').resolve()==b

@needs_symlink
def test_read_private_info_failure_keeps_current_pointer(tmp_path,monkeypatch):
 old=generation(tmp_path,'old','old')
 s.publish(tmp_path,old)
 follower=s.Follower('test-token',tmp_path)
 monkeypatch.setattr(follower,'get_json',lambda url:{'private':False,'sha':'a'*40})
 with pytest.raises(ValueError,match='privacy'):follower.cycle()
 assert (tmp_path/'current').resolve()==old

@needs_symlink
def test_network_failure_keeps_current_pointer(tmp_path,monkeypatch):
 old=generation(tmp_path,'old','old');s.publish(tmp_path,old)
 follower=s.Follower('test-token',tmp_path)
 def fail(url):raise s.requests.Timeout('offline')
 monkeypatch.setattr(follower,'get_json',fail)
 with pytest.raises(s.requests.Timeout):follower.cycle()
 assert (tmp_path/'current/market.sqlite3').read_text()=='old'

@pytest.mark.parametrize('body', [b'wrong',b'too-long-body'])
def test_bad_download_never_enters_cache_or_generation(tmp_path,monkeypatch,body):
 follower=s.Follower('test-token',tmp_path)
 class Response:
  def __enter__(self):return self
  def __exit__(self,*args):pass
  def raise_for_status(self):pass
  def iter_content(self,*args):yield body
 monkeypatch.setattr(s.requests,'get',lambda *args,**kw:Response())
 want=hashlib.sha256(b'good').hexdigest()
 with pytest.raises(ValueError):follower.fetch_file('a'*40,{'path':'table/data.parquet','sha256':want,'bytes':4},tmp_path/'stage')
 assert not (follower.cache/want).exists()
 assert not (tmp_path/'stage/table/data.parquet').exists()
 assert not list(follower.cache.glob('*.part'))

@pytest.mark.parametrize('path', ['../escape','/absolute'])
def test_manifest_path_cannot_escape(tmp_path,path):
 follower=s.Follower('test-token',tmp_path)
 with pytest.raises(ValueError,match='unsafe'):follower.fetch_file('a'*40,{'path':path,'sha256':'a'*64,'bytes':1},tmp_path/'stage')

def test_verified_cache_reused_without_network(tmp_path,monkeypatch):
 follower=s.Follower('test-token',tmp_path)
 payload=b'good';sha=hashlib.sha256(payload).hexdigest();(follower.cache/sha).write_bytes(payload)
 def fail(*args,**kw):raise AssertionError('cache should not need network')
 monkeypatch.setattr(s.requests,'get',fail)
 follower.fetch_file('a'*40,{'path':'table/data.parquet','sha256':sha,'bytes':4},tmp_path/'stage')
 assert (tmp_path/'stage/table/data.parquet').read_bytes()==payload

def test_calendar_preserves_local_tables_without_replacing_exported_values(tmp_path,monkeypatch):
 import sqlite3
 from collector import market_calendar
 seed=tmp_path/'seed.sqlite3';target=tmp_path/'target.sqlite3'
 with sqlite3.connect(seed) as c:
  for table,value in [('holiday_kasi','official'),('policy_meeting','prior-policy'),('corp_schedule','prior-company')]:
   c.execute(f'CREATE TABLE {table} (value TEXT)');c.execute(f'INSERT INTO {table} VALUES (?)',(value,))
 with sqlite3.connect(target) as c:
  c.execute('CREATE TABLE policy_meeting (value TEXT)');c.execute("INSERT INTO policy_meeting VALUES ('new-export-policy')")
 def build(conn,**kw):
  assert kw=={'fetch':False,'quiet':True}
  assert not conn.in_transaction
  assert conn.execute('SELECT value FROM holiday_kasi').fetchone()[0]=='official'
  assert conn.execute('SELECT value FROM corp_schedule').fetchone()[0]=='prior-company'
  assert conn.execute('SELECT value FROM policy_meeting').fetchone()[0]=='new-export-policy'
  return {'ex_changes':[],'stats':{'rule_closed_but_traded':0,'rule_open_but_closed':0}}
 monkeypatch.setattr(market_calendar,'build',build)
 result=s.Follower('test-token',tmp_path/'sync',seed).calendar(target)
 assert result['preserved_local_tables']==['holiday_kasi','corp_schedule']
