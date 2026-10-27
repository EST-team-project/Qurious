"""HF main의 검증된 수집 자료를 원자적으로 받는다. 원격 쓰기·수집·계좌 DB 변경은 하지 않는다."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone, time as daytime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import sys
import time
import requests
from zoneinfo import ZoneInfo

from app.services.hf_snapshot import PROOF_VERSION, validate_snapshot, read_ready_proof

REPO = 'qurious-quant/krx-daily-market'
API = f'https://huggingface.co/api/datasets/{REPO}'
RESOLVE = f'https://huggingface.co/datasets/{REPO}/resolve'
ROOT = Path(os.environ.get('HF_SYNC_ROOT', '/sync'))
INTERVAL = int(os.environ.get('HF_SYNC_INTERVAL', '900'))
SEED = Path(os.environ.get('HF_SYNC_SEED', '/seed/market.sqlite3'))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def next_poll_seconds(now=None, interval=INTERVAL):
    """공개 이후에는 main 변경을 1분마다 확인한다. 그 밖에는 기존 간격을 유지한다."""
    now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('Asia/Seoul'))
    if daytime(13) <= now.time() < daytime(15, 30):
        return min(interval, 60)
    if now.time() < daytime(13):
        edge = now.replace(hour=13, minute=0, second=0, microsecond=0)
        return min(interval, max(1, int((edge - now).total_seconds())))
    return interval


def price_readiness(root=ROOT, now=None):
    """수신한 세대의 전 거래일 봉 준비 상태. 원본 수집·업로드·주문은 하지 않는다."""
    now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('Asia/Seoul'))
    result = {'ready': False, 'decision_date': now.date().isoformat(),
              'required_price_date': None, 'price_date': None,
              'next_check_seconds': next_poll_seconds(now)}
    def state(name, message):
        return {**result, 'state': name, 'message': message}
    try:
        generation = (Path(root) / 'current').resolve()
        proof = read_ready_proof(generation, now=now)
        result['price_date'] = datetime.strptime(proof['price_max'], '%Y%m%d').date().isoformat()
        with sqlite3.connect((generation / 'market.sqlite3').as_uri() + '?mode=ro', uri=True) as conn:
            rows = conn.execute('SELECT cal_date,is_trading_day FROM market_calendar WHERE cal_date BETWEEN ? AND ? ORDER BY cal_date',
                                ((now.date() - timedelta(days=31)).isoformat(), now.date().isoformat())).fetchall()
        days = dict(rows)
        if now.date().isoformat() not in days:
            raise ValueError('calendar does not cover today')
        if not days[now.date().isoformat()]:
            return state('closed', '휴장일입니다. 다음 거래일에 필요한 HF 자료를 확인합니다.')
        previous = None
        for offset in range(1, 32):
            day = (now.date() - timedelta(days=offset)).isoformat()
            if day not in days:
                raise ValueError('calendar gap')
            if days[day]:
                previous = day
                break
        if previous is None:
            raise ValueError('previous trading day unavailable')
        result['required_price_date'] = previous
        if result['price_date'] > previous:
            return state('date_mismatch', '자료 날짜가 예상 거래일과 달라 주문 입력으로 인정하지 않습니다.')
        if result['price_date'] == previous:
            started = dated(proof['started_at']).astimezone(ZoneInfo('Asia/Seoul'))
            if started.date() != now.date() or started.time() < daytime(12, 30):
                return state('waiting_for_today_run', '전 거래일 봉은 있지만 오늘 회차의 HF 자료를 기다립니다.')
            result['ready'] = True
            return state('ready', '전 거래일 봉의 수신·검증을 마쳤습니다. 전략·계좌·위험 조건은 별도 확인합니다.')
        if now.time() < daytime(13):
            return state('before_publication', '전 거래일 봉이 없습니다. 13시 이후 HF 변경을 1분마다 확인합니다.')
        if now.time() < daytime(15, 30):
            return state('waiting_for_hf', '전 거래일 봉이 포함된 HF 자료를 기다립니다. 오래된 봉으로 주문하지 않습니다.')
        return state('late', '전 거래일 봉을 아직 받지 못했습니다. 기존 간격으로 HF 확인을 계속합니다.')
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        return state('unavailable', '자료 검증 근거나 거래일 달력을 확인하지 못해 주문 준비로 인정하지 않습니다.')


def dated(value):
    d = datetime.fromisoformat(value)
    if d.tzinfo is None:
        raise ValueError('record timestamp must have timezone')
    return d


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def publish(root, generation):
    """One pointer replaces DB and state together. Generation is immutable after this."""
    if not (generation / 'market.sqlite3').is_file() or not (generation / 'state/daily_update_last.json').is_file():
        raise ValueError('incomplete generation')
    pointer = root / '.current-next'
    pointer.unlink(missing_ok=True)
    pointer.symlink_to(generation.relative_to(root), target_is_directory=True)
    pointer.replace(root / 'current')


class Follower:
    def __init__(self, token, root=ROOT, seed=SEED):
        if not token:
            raise ValueError('HF access token is missing')
        self.root, self.seed = Path(root), Path(seed)
        self.headers = {'Authorization': 'Bearer ' + token}
        self.cache = self.root / 'cache'
        self.cache.mkdir(parents=True, exist_ok=True)

    def get_json(self, url):
        with requests.get(url, headers=self.headers, timeout=(15, 90)) as r:
            r.raise_for_status()
            return r.json()

    def record(self, sha):
        if not re.fullmatch('[a-f0-9]{40}', sha):
            raise ValueError('invalid revision')
        return self.get_json(f'{RESOLVE}/{sha}/meta/run_record.json')

    def fetch_file(self, sha, rec, folder):
        rel = PurePosixPath(rec['path'])
        if rel.is_absolute() or '..' in rel.parts or not rel.parts:
            raise ValueError('unsafe manifest path')
        want = rec['sha256']
        if not re.fullmatch('[a-f0-9]{64}', want):
            raise ValueError('invalid file digest')
        cached = self.cache / want
        if not cached.is_file() or cached.stat().st_size != rec['bytes'] or digest(cached) != want:
            part = cached.with_suffix('.part')
            try:
                count = 0
                with requests.get(f'{RESOLVE}/{sha}/{rel.as_posix()}', headers=self.headers,
                                  timeout=(15, 120), stream=True) as r:
                    r.raise_for_status()
                    with part.open('wb') as f:
                        for chunk in r.iter_content(1024 * 1024):
                            count += len(chunk)
                            if count > rec['bytes']:
                                raise ValueError('download exceeds manifest size')
                            f.write(chunk)
                if count != rec['bytes'] or digest(part) != want:
                    raise ValueError('download digest or size mismatch')
                part.replace(cached)
            finally:
                part.unlink(missing_ok=True)
        cached.touch()  # Retain partitions reused by the latest snapshots.
        dest = folder.joinpath(*rel.parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.link(cached, dest)

    def calendar(self, db):
        from collector import market_calendar
        if not self.seed.is_file():
            raise ValueError('stored official calendar seed unavailable')
        preserved = []
        with sqlite3.connect(self.seed.resolve().as_uri() + '?mode=ro', uri=True) as seed:
            with sqlite3.connect(db) as conn:
                for table in ['holiday_kasi', 'policy_meeting', 'corp_schedule']:
                    # These local-only tables are not in current HF exports. Never replace a newer exported table.
                    if conn.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type='table'", (table,)).fetchone():
                        continue
                    ddl = seed.execute("SELECT sql FROM sqlite_master WHERE name=? AND type='table'", (table,)).fetchone()
                    if ddl is None:
                        if table == 'holiday_kasi':
                            raise ValueError('official holiday table unavailable')
                        continue
                    rows = seed.execute('SELECT * FROM ' + table).fetchall()
                    conn.execute(ddl[0])
                    if rows:
                        conn.executemany('INSERT INTO ' + table + ' VALUES (' + ','.join('?' * len(rows[0])) + ')', rows)
                    preserved.append(table)
                conn.commit()
                result = market_calendar.build(conn, fetch=False, quiet=True)
                if result.get('ex_changes') or result['stats']['rule_closed_but_traded'] or result['stats']['rule_open_but_closed']:
                    raise ValueError('calendar conflicts with restored prices or changes dividend dates')
                result['preserved_local_tables'] = preserved
                return result

    def cycle(self):
        info = self.get_json(API)
        if info.get('private') is not True:
            raise ValueError('team dataset privacy check failed')
        head = info['sha']
        previous = {}
        if (self.root / 'status.json').exists():
            previous = json.loads((self.root / 'status.json').read_text())
        current = self.root / 'current'
        if (current.is_dir() and previous.get('source_head') == head
                and previous.get('generation') == current.resolve().name
                and previous.get('proof_version') == PROOF_VERSION):
            proof = read_ready_proof(current)
            if proof['snapshot_commit'] != head:
                raise ValueError('current generation belongs to another commit')
            return {**previous, 'status': 'current', 'checked_at': stamp(), 'last_error': None}
        # 날짜 태그는 그날 첫 업로드에 머물 수 있다. 세 파일을 같은 main SHA에서 읽는다.
        sha = head
        archive = self.record(sha)
        man = self.get_json(f'{RESOLVE}/{sha}/meta/manifest.json')
        verification = self.get_json(f'{RESOLVE}/{sha}/meta/last_verify.json')
        evidence = validate_snapshot(sha, archive, man, verification)
        joined = archive['run']  # 업로드 직전 원본 기록. finished_at은 추정하지 않는다.
        generation = self.root / 'releases' / (sha + '-ready-v1')
        expected = evidence['price_max']
        if current.is_dir():
            old = json.loads((current / 'provenance.json').read_text())
            if dated(joined['started_at']) < dated(old['started_at']):
                raise ValueError('refusing to replace current data with an older run')
            if expected < old['price_max']:
                raise ValueError('refusing to regress the current price date')
        if not generation.exists():
            stage = self.root / 'staging'
            if stage.exists():
                shutil.rmtree(stage)
            stage.mkdir()
            exports = stage / 'export'
            (exports / 'meta').mkdir(parents=True)
            if man.get('partial') or not man.get('tables'):
                raise ValueError('incomplete manifest')
            files = [f for table in man['tables'].values() for f in table['files']]
            if len(files) > 5000 or sum(f['bytes'] for f in files) > 20 * 1024**3:
                raise ValueError('snapshot exceeds local sync limits')
            atomic_json(exports / 'meta/manifest.json', man)
            print(json.dumps({'phase': 'download', 'snapshot': sha, 'files': len(files)}, ensure_ascii=False), flush=True)
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda rec: self.fetch_file(sha, rec, exports), files))
            print(json.dumps({'phase': 'restore', 'snapshot': sha}), flush=True)
            from scripts import hf_dataset
            with (self.root / 'restore-latest.log').open('w') as log, redirect_stdout(log), redirect_stderr(log):
                rc = hf_dataset.restore(into=str(stage / 'market.sqlite3'), src=str(exports))
                if rc != 0:
                    raise ValueError('restored snapshot failed source verification')
                calendar = self.calendar(stage / 'market.sqlite3')
            print(json.dumps({'phase': 'sqlite_integrity', 'snapshot': sha}), flush=True)
            with sqlite3.connect((stage / 'market.sqlite3').as_uri() + '?mode=ro', uri=True) as conn:
                if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('restored SQLite failed integrity check')
                if conn.execute('SELECT MAX(bas_dt) FROM price_daily').fetchone()[0] != expected:
                    raise ValueError('restored DB and original run price dates differ')
            shutil.rmtree(exports)  # Cache hardlinks retain source partitions; no duplicate cache tree.
            atomic_json(stage / 'meta/run_record.json', archive)
            atomic_json(stage / 'meta/manifest.json', man)
            atomic_json(stage / 'meta/last_verify.json', verification)
            atomic_json(stage / 'meta/calendar.json', calendar)
            atomic_json(stage / 'state/daily_update_last.json', joined)
            evidence.update(files_verified=True, data_ready_at=stamp())
            atomic_json(stage / 'provenance.json', evidence)
            generation.parent.mkdir(parents=True, exist_ok=True)
            stage.replace(generation)
        else:
            saved = read_ready_proof(generation)
            if any(saved[k] != evidence[k] for k in evidence):
                raise ValueError('existing generation provenance mismatch')
            evidence = saved
        publish(self.root, generation)
        self.cleanup(generation)
        return {'status': 'updated', 'checked_at': stamp(), 'updated_at': stamp(), 'source_head': head,
                'generation': generation.name, 'proof_version': PROOF_VERSION, 'provenance': evidence, 'last_error': None,
                'note': 'Verified data readiness and whole-run completion are recorded separately.'}

    def cleanup(self, current):
        # Retain three generations, and keep every generation newer than two days.
        generations = sorted((self.root / 'releases').iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in generations[3:]:
            if p != current and p.stat().st_mtime < time.time() - 2 * 86400:
                shutil.rmtree(p)
        # Bound unused content cache while retaining recent data for incremental downloads.
        for p in self.cache.iterdir():
            if p.is_file() and p.stat().st_mtime < time.time() - 7 * 86400:
                p.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--health', action='store_true')
    args = parser.parse_args()
    if args.health:
        try:
            state = json.loads((ROOT / 'status.json').read_text())
            fresh = (datetime.now(timezone.utc) - dated(state['checked_at'])).total_seconds() < max(2700, INTERVAL * 3)
            return 0 if fresh and not state.get('last_error') and (ROOT / 'current/market.sqlite3').is_file() else 1
        except (OSError, ValueError, KeyError):
            return 1
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / 'sync.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('another local HF sync is running', flush=True)
            return 0
        follower = Follower(os.environ.get('HUGGINGFACE_ACCESS_TOKEN', ''))
        while True:
            try:
                result = follower.cycle()
                result['publication'] = price_readiness()
                atomic_json(ROOT / 'status.json', result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
            except Exception as exc:
                # Never print auth headers or raw remote response bodies.
                try:
                    result = json.loads((ROOT / 'status.json').read_text())
                except (OSError, ValueError):
                    result = {}
                result.update(status='error', checked_at=stamp(), last_error=type(exc).__name__ + ': ' + str(exc))
                result['publication'] = {'ready': False, 'state': 'sync_error',
                                         'message': 'HF 수신 오류로 자료 준비를 확인하지 못했습니다.'}
                atomic_json(ROOT / 'status.json', result)
                print(json.dumps({'status': 'error', 'checked_at': result['checked_at'], 'error_type': type(exc).__name__}, ensure_ascii=False), flush=True)
                if args.once:
                    return 1
            if args.once:
                return 0
            time.sleep(next_poll_seconds())


if __name__ == '__main__':
    sys.exit(main())
