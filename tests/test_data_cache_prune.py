"""TC-DCP — 외부 시세 캐시 정리 (app/services/data_cache.py `prune_external` · 할 일 ①-29 · 2026-10-30) + 앱 DB 백업 · 상태 키 복원 (2026-11-02)

`data_cache` 는 외부 시세 캐시와 함께 상태 · 결과(자동매매 사이클 로그 · 대사 기준선 · 모델 비교 결과 · AI 예측)도 담는다.
나이만 보고 지우면 상태가 사라지므로 **허용 목록 키만** 지운다. 가짜 세션으로 실제 SQL 을 만들어 본다(DB 없이).
1. 허용 목록 판정 — 외부 시세 키는 True · 상태 · 결과 키는 False. (TC-DCP-01)
2. 실제 코드의 캐시 키와 어긋나지 않는다 — 코드에 쓰이는 접두사가 목록에 있고, 상태 키는 목록에 없다. (TC-DCP-02)
3. 지우는 SQL — 허용 목록 조건 + 나이 조건이 붙고 `quant:` · `ai_predict:` 는 안 걸린다 · dry_run 은 지우지 않는다 · 1일 아래는 거부. (TC-DCP-03)
4. 하루 한 번 작업으로 예약돼 있다. (TC-DCP-04)
5. 앱 DB 백업 스크립트는 data_cache 의 줄을 덤프에서 뺀다. (TC-DCP-05)
6. 대신 다시 만들 수 없는 상태 키(`quant:` · `model_compare:`)만 .state.csv 로 짝을 지어 따로 내보낸다. (TC-DCP-06)
7. 복원 스크립트는 같은 접두사 · 같은 열로 upsert 하되 **대상이 더 최근이면 지키고**, 안전장치를 갖는다. (TC-DCP-07)
8. 상태 접두사는 정리 허용 목록과 겹치지 않고 목록끼리도 겹치지 않는다 — 정리가 상태 키를 지우는 길이 없다. (TC-DCP-08)
9. 세 스크립트(공용 정의 포함)는 UTF-8 BOM · ASCII SQL · PowerShell 문법 검사를 통과한다. (TC-DCP-09 · 10)
10. 공용 정의의 함수가 실제로 동작한다(조건 · 접두사 검사 · 파일 머리 읽기 · 암호화 파일 판별). (TC-DCP-11)
11. `.gitignore` 가 백업 산출물을 막고, 백업은 저장소 안의 무시되지 않는 폴더를 거부한다. (TC-DCP-12 · 13)
12. 복원은 Docker 없이도 입력 오류(선택자 · 머리글 · 암호화 파일)를 먼저 막는다. (TC-DCP-14)
13. **행동 시험** — 임시 DB 에서 백업 → 새 PC 흉내(DB 새로 만들기 + pg_restore) → 복원 왕복. 개발 DB 는 읽기만 한다. (TC-DCP-15 ~ 17)
14. 복원 -Apply 는 앱 · 워커 · 비트가 켜져 있으면 멈추고(-Force 로 감수), -DryRun · 임시 DB(-Database)는 막지 않는다. 가짜 docker 로 돌려
    Docker · 개발 DB 에 닿지 않는다. (TC-DCP-18)

**임시 DB 행동 시험(TC-DCP-15 ~ 17)은 기본으로 건너뛴다** — Docker 에서 임시 DB 를 만들어 백업 · pg_restore · 복원을 왕복하느라 전체 시험에 약 50초가 붙는다.
켜는 법: 환경변수 `QURIOUS_TEST_DOCKER_DB=1` 을 주고(앱 DB 컨테이너 fin-ai-postgres 가 켜져 있어야 한다) 돌린다. 건너뛴 까닭을 보려면 `-rs` 를 붙인다.
    PowerShell:  $env:QURIOUS_TEST_DOCKER_DB = '1'; python -m pytest tests/test_data_cache_prune.py -rs
    끄기:        Remove-Item Env:QURIOUS_TEST_DOCKER_DB
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import data_cache as dc  # noqa: E402


def test_allowlist_judgement():
    """TC-DCP-01 · 외부 시세 캐시는 정리 대상, 상태 · 결과 키는 아니다."""
    for k in ("candles:005930:1y:1d", "candles:kis:005930:1y:1d", "indicators:AAPL:2y", "fundamentals:005930",
              "market_indices", "macro_indicators", "sector_etfs", "us_stocks", "krx_company_list"):
        assert dc.is_external_key(k), k
    for k in ("quant:cycle_log:123", "quant:reconcile:baseline:u:env", "quant:reconcile:latest:u", "quant:last_beat_run",
              "ai_predict:v4:005930", "model_compare:abc", "", "candle", "indicator:x"):
        assert not dc.is_external_key(k), k


def test_allowlist_matches_keys_used_in_code_and_never_covers_state_keys():
    """TC-DCP-02 · 코드에서 쓰는 외부 시세 키 접두사가 목록에 있고(드리프트 방지), 상태 키 접두사는 목록에 없다."""
    src = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "app").rglob("*.py") if p.name != "data_cache.py")
    for prefix in dc.EXTERNAL_KEY_PREFIXES:
        assert re.search(r'f?["\']' + re.escape(prefix), src), f"코드에서 안 쓰는 접두사가 목록에 있다: {prefix}"
    for key in dc.EXTERNAL_KEYS:
        assert f'"{key}"' in src, f"코드에서 안 쓰는 키가 목록에 있다: {key}"
    for state_prefix in ("quant:", "ai_predict:"):
        assert state_prefix in src, f"상태 키 접두사 {state_prefix} 가 코드에서 사라졌다 — 이 시험을 갱신한다"
        assert not any(state_prefix.startswith(p) or p.startswith(state_prefix) for p in dc.EXTERNAL_KEY_PREFIXES)
        assert state_prefix not in dc.EXTERNAL_KEYS


class _FakeSession:
    def __init__(self, log, count=3):
        self.log, self.count = log, count

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        self.log.append(str(stmt.compile(dialect=postgresql.dialect())))
        return SimpleNamespace(rowcount=self.count, scalar_one=lambda: self.count)

    async def commit(self):
        self.log.append("COMMIT")


def _run(monkeypatch, *args, **kw):
    log: list[str] = []
    monkeypatch.setattr(dc, "get_session_factory", lambda: (lambda: _FakeSession(log)))
    return log, asyncio.run(dc.prune_external(*args, **kw))


def test_prune_sql_is_limited_to_allowlist_and_age(monkeypatch):
    """TC-DCP-03 · 지우는 SQL 은 나이 조건 + 허용 목록 조건이고 · dry_run 은 세기만 하며 · 1일 아래는 거부한다."""
    log, out = _run(monkeypatch)
    sql = log[0]
    assert sql.startswith("DELETE FROM data_cache") and "updated_at <" in sql and "LIKE" in sql and " IN " in sql
    assert "quant" not in sql and "ai_predict" not in sql
    assert log[-1] == "COMMIT" and out["deleted"] == 3 and out["dry_run"] is False and out["would_delete"] is None
    log, out = _run(monkeypatch, dry_run=True)
    assert log[0].startswith("SELECT count") and "COMMIT" not in log and out["deleted"] == 0 and out["would_delete"] == 3
    for bad in (0, 0.5, -1):
        with pytest.raises(ValueError, match="1 이상"):
            asyncio.run(dc.prune_external(bad))
    assert dc.PRUNE_DEFAULT_DAYS >= 7 * dc.PRUNE_MIN_DAYS, "읽는 쪽 최대 나이(24시간)보다 훨씬 길게"


def test_prune_is_scheduled_once_a_day_as_a_registered_task():
    """TC-DCP-04 · 비트가 등록 이름으로 하루 한 번 부른다(이름이 어긋나면 워커가 버린다 — celery_app 주석)."""
    from app.celery_app import celery_app
    entry = celery_app.conf.beat_schedule["prune-external-cache-daily"]
    assert entry["task"] == "sync.prune_external_cache"
    from app.tasks import sync_tasks
    assert sync_tasks.prune_external_cache.name == "sync.prune_external_cache"
    rep = repr(entry["schedule"]).replace(" ", "")
    assert "crontab" in rep.lower() and "3" in rep


def test_backup_script_excludes_data_cache_rows_by_default():
    """TC-DCP-05 · 앱 DB 백업 스크립트는 기본으로 data_cache 의 줄을 빼고(표 정의는 둠), 옵션을 줘야 포함한다."""
    from app.models import DataCache
    script = (ROOT / "scripts" / "personal" / "backup-appdb.ps1").read_text(encoding="utf-8-sig")
    # 표 이름이 바뀌면 스크립트도 같이 고쳐야 한다(드리프트 방지)
    assert DataCache.__tablename__ == "data_cache"
    assert f"--exclude-table-data={DataCache.__tablename__}" in script
    # 줄만 빼고 표 정의는 둔다 — 표 전체를 빼는 --exclude-table 은 복원 후 앱이 표를 못 찾는다
    assert "--exclude-table=" not in script
    # 기본이 「뺀다」 이고, 포함은 -IncludeDataCache 가 켰을 때만이다
    assert re.search(r"if \(-not \$IncludeDataCache\)\s*\{\s*\$dumpArgs \+= ' --exclude-table-data=data_cache'", script)
    assert "[switch]$IncludeDataCache" in script
    # DB 사용자 · 이름은 컨테이너 안에서 풀리게 작은따옴표로 넘긴다(비밀값을 호스트로 읽지 않음)
    assert "'pg_dump -U $POSTGRES_USER -d $POSTGRES_DB '" in script


# ── 앱 DB 백업 · 상태 키 파일(.state.csv) 내보내기 · 되돌리기 (할 일 ①-29 후속 · 2026-11-02) ─────────────────────

_PS_DIR = ROOT / "scripts" / "personal"
_LIB = "_appdb-state.ps1"
_STATE_SCRIPTS = ("backup-appdb.ps1", "restore-appdb-state.ps1")
_ALL_PS = (*_STATE_SCRIPTS, _LIB)
_PG = "fin-ai-postgres"


def _ps(name: str) -> str:
    # core.autocrlf=true 인 PC 는 체크아웃하면 CRLF 가 되므로 줄바꿈을 LF 로 맞춰 읽는다(스크립트 동작에는 영향 없음).
    return (_PS_DIR / name).read_bytes().decode("utf-8-sig").replace("\r\n", "\n")


def _flat(text: str) -> str:
    """공백 · 줄바꿈을 한 칸으로 줄인다 — 문자열 단언이 들여쓰기 · 줄 나눔에 덜 민감하게."""
    return " ".join(text.split())


def _here_strings(text: str) -> list[str]:
    return re.findall(r"@'\n(.*?)\n'@", text, re.S)


def _lib_const(name: str) -> str:
    """공용 정의 파일의 `$name = '값'` — 정확히 한 곳에만 정의돼야 한다."""
    found = re.findall(rf"^\${name} = '([^']+)'$", _ps(_LIB), re.M)
    assert len(found) == 1, f"${name} 정의가 {len(found)}곳이다(한 곳이어야 한다)"
    return found[0]


def _prefixes() -> list[str]:
    """공용 정의 파일의 상태 키 접두사 목록 — 백업 · 복원 · 시험이 모두 이 한 곳만 본다."""
    found = re.findall(r"^\$QStateKeyPrefixes = @\((.+)\)$", _ps(_LIB), re.M)
    assert len(found) == 1, f"$QStateKeyPrefixes 정의가 {len(found)}곳이다(한 곳이어야 한다)"
    items = re.findall(r"'([^']+)'", found[0])
    assert items, "접두사 목록이 비었다"
    return items


def _dot_sources_lib(text: str) -> bool:
    return bool(re.search(r'^\. "\$PSScriptRoot\\_appdb-state\.ps1"$', text, re.M))


def _run_ps(script: Path | str, *args, env: dict | None = None, timeout: int = 300) -> tuple[int, str, bytes]:
    """PowerShell 5.1 로 스크립트를 실행한다. (종료 코드, cp949 로 푼 글, 원본 바이트). 안내 문구는 한글이라 단언은 종료 코드 · ASCII 표지 · DB 상태로 한다."""
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), *map(str, args)]
    p = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env, cwd=str(ROOT))
    raw = p.stdout + b"\n" + p.stderr
    return p.returncode, raw.decode("cp949", errors="replace"), raw


def _has(raw: bytes, word: str) -> bool:
    """콘솔 코드 페이지(cp949 · utf-8) 어느 쪽으로 찍혔든 한글 낱말을 찾는다."""
    return any(word.encode(enc, errors="ignore") in raw for enc in ("cp949", "utf-8"))


def _need_powershell():
    if sys.platform != "win32" or shutil.which("powershell") is None:
        pytest.skip("Windows PowerShell 5.1 이 있는 PC 에서만")


def _param_names(text: str) -> list[str]:
    block = re.search(r"\[CmdletBinding\(\)\]\s*param\((.*?)\n\)", text, re.S)
    assert block, "param 블록이 없다"
    return re.findall(r"\[(?:string|switch)\]\$(\w+)", block.group(1))


def test_backup_script_exports_state_keys_to_a_paired_csv():
    """TC-DCP-06 · 백업은 덤프와 같은 시각(초까지) 이름으로 상태 키만 CSV 로 내보내고, 공용 정의를 쓰며, 실패하면 덤프를 .incomplete 로 바꾼다."""
    from app.models import DataCache
    backup = _ps("backup-appdb.ps1")
    flat = _flat(backup)
    # 접두사 목록 · 머리글 · 조건 함수는 공용 파일 한 곳. 백업에는 접두사 리터럴도 정의도 없다
    assert _dot_sources_lib(backup)
    prefixes = _prefixes()
    for p in prefixes:
        assert f"'{p}'" not in backup, f"접두사 {p} 리터럴이 백업 스크립트에 있다(공용 파일 한 곳에만)"
    assert not re.search(r"^\$QStateKeyPrefixes\s*=", backup, re.M)
    assert "$stateCond = Get-QStateKeyCondition" in backup and "Test-QStateKeyPrefixes" in backup
    # 내보내는 열 = 모델의 열. 열이 늘거나 이름이 바뀌면 여기서 걸린다(상태 파일이 새 열을 빠뜨리는 것 방지)
    cols = [c.name for c in DataCache.__table__.columns]
    assert sorted(cols) == ["data", "id", "key", "updated_at"]
    header = _lib_const("QStateCsvHeader")
    assert sorted(header.split(",")) == sorted(cols)
    assert _lib_const("QAppDbStampFormat") == "yyyyMMdd-HHmmss"
    # \copy 는 한 줄이어야 하고, 열 · 조건 · 임시 파일 이름은 변수로 조립한다
    copy_blocks = [b for b in _here_strings(backup) if "\\copy" in b]
    assert len(copy_blocks) == 1
    assert re.search(r"^\\copy \(SELECT @COLS@ FROM data_cache WHERE @COND@ ORDER BY key\) TO '@REMOTE@' WITH \(FORMAT csv, HEADER\)$",
                     copy_blocks[0], re.M), "\\copy (SELECT ... WHERE @COND@ ...) 한 줄이 없다"
    for rep in (".Replace('@COLS@', $QStateCsvColumns)", ".Replace('@COND@', $stateCond)", ".Replace('@REMOTE@', $remoteState)"):
        assert rep in backup, rep
    assert "PFX|" in backup, "접두사별 줄 수를 찍는다"
    # 덤프와 상태 파일은 한 번 계산한 시각(초까지)을 같이 쓴다 — 분이 넘어가도 짝이 어긋나지 않고, 임시 파일 이름에도 시각과 PID
    assert backup.count("Get-Date") == 1 and "$stamp = Get-Date -Format $QAppDbStampFormat" in backup
    assert 'appdb-${stamp}.dump' in backup and 'appdb-${stamp}.state.csv' in backup
    assert '/tmp/appdb-${stamp}-${PID}.dump' in backup and '/tmp/appdb-${stamp}-${PID}.state.csv' in backup
    # 이미 있는 이름이면 덮어쓰지 않고 거부한다
    assert re.search(r'foreach \(\$f in @\(\$outDump, \$outState, "\$outDump\.incomplete"\)\) \{ if \(Test-Path -LiteralPath \$f\) \{ Write-QFail', flat)
    # -IncludeDataCache 이면 표 전체가 덤프에 들어가므로 상태 파일은 만들지 않는다
    assert "$exportState = -not $IncludeDataCache" in backup and "if ($exportState)" in backup
    # 컨테이너 /tmp 임시 파일은 try/finally 로 성공 · 실패와 상관없이 지운다
    assert re.search(r"\btry \{ & docker exec \$pg sh -c \$remoteCmd .*\} finally \{ & docker exec \$pg rm -f \$remoteDump \$remoteState \| Out-Null \}", flat)
    # 상태 내보내기가 실패하면 덤프를 .incomplete 로 바꾸고 실패로 끝낸다 — 「백업 완료」 는 둘 다 만들어진 뒤에만 찍는다
    assert 'Rename-Item -LiteralPath $outDump -NewName "appdb-${stamp}.dump.incomplete"' in backup
    assert re.search(r"\$exportCode -ne 0 -or \$cpCode -ne 0 -or -not \(Test-Path -LiteralPath \$outState\)\) \{.*?Rename-Item.*?exit 1", flat)
    assert backup.index('Write-QOk "백업 완료') > backup.index("} finally {") > backup.index("Rename-Item -LiteralPath")
    # 오류 메시지에 값(JSON)이 새지 않게 · 폴더 권한 · 저장소 안 폴더의 .gitignore 확인 · 앱 끄기 권장 · 민감 파일 안내
    assert "-v VERBOSITY=terse -v SHOW_CONTEXT=never" in backup
    assert re.search(r'& icacls \$OutDir /inheritance:r /grant:r "\*\$\{me\}:\(OI\)\(CI\)F" \'\*S-1-5-18:\(OI\)\(CI\)F\' \'\*S-1-5-32-544:\(OI\)\(CI\)F\'', backup)
    assert "check-ignore -q --" in backup
    for sample in ("appdb-00000000-000000.dump", "appdb-00000000-000000.state.csv", "appdb-00000000-000000.dump.incomplete"):
        assert f"'{sample}'" in backup, f"저장소 안 폴더 점검에 {sample} 이 없다"
    assert "앱을 끄고" in backup and "권장" in backup
    assert "Write-QAppDbSensitiveNotice -Mode backup" in backup
    # 접두사 · -Database 검증은 \A…\z 와 대소문자 구분(-cmatch)으로 한다(공용 파일의 함수)
    lib = _ps(_LIB)
    assert r"-cmatch '\A[a-z_][a-z0-9_]*\z'" in lib and r"-cnotmatch '\A[A-Za-z0-9_\-]+(:[A-Za-z0-9_\-]+)*:\z'" in lib
    assert "Test-QAppDbName $Database" in backup
    # DB 사용자는 컨테이너 안 환경변수 · 비밀값을 읽지 않는다
    assert "psql -U $POSTGRES_USER -d $POSTGRES_DB" in backup
    for secret in ("POSTGRES_PASSWORD", "PGPASSWORD", ".env"):
        assert secret not in backup, secret


def test_restore_script_upserts_state_rows_and_protects_newer_target_rows():
    """TC-DCP-07 · 복원은 같은 접두사 · 열로 key 충돌 upsert 하되 대상이 더 최근이면 지키고, 접두사 밖 키 · 중복 · 표 없음을 막으며, 기본은 확인만 한다."""
    from app.models import DataCache
    restore = _ps("restore-appdb-state.ps1")
    flat = _flat(restore)
    # 접두사 · 머리글은 공용 파일 한 곳(리터럴 없음)
    assert _dot_sources_lib(restore)
    for p in _prefixes():
        assert f"'{p}'" not in restore
    assert not re.search(r"^\$QStateKeyPrefixes\s*=", restore, re.M) and "$stateCond = Get-QStateKeyCondition" in restore
    # ON CONFLICT (key) 는 key 의 UNIQUE 제약이 있어야 한다. 값 열 이름은 value 가 아니라 data(JSONB)다
    assert DataCache.__table__.c.key.unique
    assert "EXCLUDED.value" not in restore
    assert "EXCLUDED.id" not in restore, "기존 줄의 id 는 바꾸지 않는다"
    # 대상이 더 최근이면 덮어쓰지 않는 조건이 **실제 upsert 문장 안**에 있다
    upsert = re.search(r"INSERT INTO data_cache \(id, key, data, updated_at\) SELECT COALESCE\(id, gen_random_uuid\(\)\), key, data, updated_at "
                       r"FROM _qurious_state (ON CONFLICT .*?) RETURNING key\)", flat)
    assert upsert, "INSERT INTO data_cache ... ON CONFLICT ... RETURNING key 문장이 없다"
    assert upsert.group(1) == ("ON CONFLICT (key) DO UPDATE SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at "
                               "WHERE data_cache.updated_at <= EXCLUDED.updated_at")
    assert flat.count("INSERT INTO data_cache") == 1, "upsert 는 -DryRun · -Apply 가 같은 한 문장을 쓴다"
    # 새로 / 갱신 / 지킴 판정은 upsert 의 조건과 같은 비교(<=)다
    assert "WHEN d.key IS NULL THEN 'new' WHEN d.updated_at <= s.updated_at THEN 'update' ELSE 'keep'" in flat
    # 판정과 실제 upsert 결과가 다르면(실행 중 앱이 키를 바꿈) 되돌리고 멈춘다
    assert "(p.action = 'keep') = (p.key IN (SELECT key FROM _qurious_done))" in flat and "target rows changed while restoring" in flat
    # 결과 줄 — SQL 이 찍는 모양과 PowerShell 이 읽는 모양이 맞고, 지킨 키는 JSON 문자열로(개행 · 쉼표 안전) 찍는다
    assert "'RESULT|' || count(*) || '|' || count(*) FILTER (WHERE action = 'new') || '|' || count(*) FILTER (WHERE action = 'update') || '|' || count(*) FILTER (WHERE action = 'keep')" in flat
    assert r"'(?m)^RESULT\|(\d+)\|(\d+)\|(\d+)\|(\d+)\s*$'" in restore
    assert "'KEPT|' || regexp_replace(to_jsonb(key)::text" in flat and "LIMIT 50" in flat
    # 첫 줄 검사 상수 = 백업이 내보내는 열 순서(공용 정의)
    cols_sql = "(" + _lib_const("QStateCsvHeader").replace(",", ", ") + ")"
    assert f"\\copy _qurious_state {cols_sql} FROM '@REMOTE@' WITH (FORMAT csv, HEADER)" in restore
    assert "Get-QStateFileFirstLine" in restore and "ReadLines" not in restore
    # 안전장치 — 표 없음 / 접두사 밖 키(괄호로 감싼 조건의 NOT) / 중복 키 / 첫 오류에서 멈춤 / 오류에 값이 새지 않음
    assert "to_regclass('public.data_cache') IS NULL" in restore
    assert "NOT @COND@" in restore and ".Replace('@COND@', $stateCond)" in restore
    assert "HAVING count(*) > 1" in restore
    assert "ON_ERROR_STOP=1" in restore and "-v VERBOSITY=terse -v SHOW_CONTEXT=never" in restore
    # 한 트랜잭션 + 기본은 확인만(마지막만 ROLLBACK), -Apply 일 때만 COMMIT. 매개변수 이름과 대소문자만 다른 변수를 만들지 않는다
    assert "[switch]$Apply" in restore and "[switch]$DryRun" in restore
    assert "$doApply = [bool]$Apply.IsPresent" in restore
    assert not re.search(r"(?im)^\s*\$apply\s*=", restore), "$apply 는 매개변수 $Apply 와 대소문자만 다르다 — $doApply 를 쓴다"
    assert "BEGIN;" in restore and "@END@" in restore
    assert "if ($doApply) { $endSql = 'COMMIT;' } else { $endSql = 'ROLLBACK;' }" in restore
    assert "COMMIT;" not in "\n".join(_here_strings(restore)) and "ROLLBACK;" not in "\n".join(_here_strings(restore))
    # 앱 · 워커 · 비트가 켜져 있으면 -Apply 는 멈춘다(-Force 로 감수) · -DryRun 은 경고만 · 임시 DB(-Database)는 점검하지 않는다 (동작은 TC-DCP-18)
    assert "'fin-ai-app', 'fin-ai-celery-worker', 'fin-ai-celery-beat'" in restore
    assert "[switch]$Force" in restore and "$doForce = [bool]$Force.IsPresent" in restore
    gate = restore[restore.index("if (-not $Database) {\n  $appStates"):restore.index("# 4. 파일을 컨테이너로 보내")]
    assert "} elseif ($doApply -and -not $doForce) {" in gate and "exit 1" in gate.split("} elseif ($doApply) {")[0]
    assert "-Force" in gate and "stop.ps1" in gate and "자동매매 사이클" in gate
    assert restore.index("} elseif ($doApply -and -not $doForce) {") < restore.index("& docker cp"), "막는 점검은 파일을 컨테이너로 보내기 전에 한다"
    # 안내 문구 — 새 동작(대상이 더 최근이면 지킴)을 말하고, 옛 문구(파일 값으로 덮어쓴다)가 남아 있지 않다
    for phrase in ("새로 넣음", "갱신", "대상이 더 최근이라 지킴", "quant:cycle_log", "시계"):
        assert phrase in restore, phrase
    assert "파일 값으로 덮어쓴다" not in restore and "파일 값으로 바뀝니다" not in restore
    assert "[new=$newRows update=$updRows keep=$keepRows]" in restore
    # 짝 확인 · 파일 선택 — -Stamp · -DumpFile · 자동 선택(고른 파일 이름 · 시각을 보여 줌)
    for token in ("[string]$Stamp", "[string]$DumpFile", "백업 시각", "짝 덤프", "자동 선택"):
        assert token in restore, token
    assert "$Stamp -cnotmatch $QAppDbStampPattern" in restore
    # 암호화한 파일을 주면 복호화 안내
    assert "protect_database_backup.py --decrypt" in restore and "Test-QEncryptedBackup" in restore
    # 머리말에 순서(pg_restore 먼저)와 민감 파일 안내를 적었다
    help_text = restore.split("#>")[0]
    for token in ("1) pg_restore", "-DryRun", "-Apply", "내가 만든 파일만", "protect_database_backup.py", "secrets", "-Force", "stop.ps1", ".PARAMETER Force"):
        assert token in help_text, token
    # 비밀값을 읽지 않는다
    for secret in ("POSTGRES_PASSWORD", "PGPASSWORD", ".env"):
        assert secret not in restore, secret


def test_script_variables_never_shadow_parameters_by_case():
    """TC-DCP-07b · PowerShell 변수는 대소문자를 구분하지 않는다 — 매개변수와 대소문자만 다른 이름으로 값을 넣지 않는다(공용 파일의 변수 포함)."""
    lib_assigned = set(re.findall(r"^\s*\$(\w+)\s*=", _ps(_LIB), re.M))
    for name in _STATE_SCRIPTS:
        text = _ps(name)
        params = _param_names(text)
        assert params
        assigned = set(re.findall(r"^\s*\$(\w+)\s*=", text, re.M)) | lib_assigned
        for a in assigned:
            for p in params:
                if a.lower() == p.lower():
                    assert a == p, f"{name}: ${a} 가 매개변수 ${p} 와 대소문자만 다르다"


def _external_overlap_check(prefix: str) -> None:
    assert not dc.is_external_key(prefix) and not dc.is_external_key(prefix + "x")
    for p in dc.EXTERNAL_KEY_PREFIXES:
        assert not prefix.startswith(p) and not p.startswith(prefix), (prefix, p)
    for k in dc.EXTERNAL_KEYS:
        assert not k.startswith(prefix), (prefix, k)


def test_state_prefixes_never_overlap_the_prune_allowlist_or_each_other():
    """TC-DCP-08 · 상태 접두사 목록은 외부 시세 정리 허용 목록과 겹치지 않고(정리가 상태 키를 지우는 길이 없음) · 목록끼리도 서로의 접두사가 아니며 · 코드의 상태 키를 덮는다."""
    prefixes = _prefixes()
    assert prefixes == ["quant:", "model_compare:"]
    for prefix in prefixes:
        _external_overlap_check(prefix)
    for i, a in enumerate(prefixes):
        for j, b in enumerate(prefixes):
            if i != j:
                assert not a.startswith(b), f"접두사끼리 겹친다: {a} / {b}"
    # 외부 시세 캐시 접두사는 상태 목록에 들어가면 안 된다(반대 방향) — 정리 허용 목록의 각 항목이 어느 상태 접두사와도 겹치지 않는다
    for p in dc.EXTERNAL_KEY_PREFIXES:
        assert not any(p.startswith(s) or s.startswith(p) for s in prefixes), p
    # 되돌려야 할 대표 상태 키가 접두사에 잡히고, 코드가 아직 그 키를 만든다(키 이름이 바뀌면 이 시험을 갱신한다)
    src = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "app").rglob("*.py"))
    for key_head in ("quant:cycle_log:", "quant:reconcile:baseline:", "quant:reconcile:latest:", "model_compare:v1:"):
        assert any(key_head.startswith(p) for p in prefixes), key_head
        assert key_head in src, f"코드에서 사라진 상태 키: {key_head}"
        assert not dc.is_external_key(key_head + "x")
    # 일부러 뺀 ai_predict: 의 근거 — 읽는 쪽이 모두 3시간 안의 값만 쓴다. 이 근거가 깨지면(TTL 이 길어지면) 목록 포함을 다시 따진다
    assert "ai_predict:" not in prefixes
    ml = (ROOT / "app" / "routes" / "ml.py").read_text(encoding="utf-8")
    reads = re.findall(r"cache_get\(cache_key[^\n]*", ml)
    assert reads and all("max_age_hours=3" in r for r in reads), reads
    stocks = (ROOT / "app" / "routes" / "stocks.py").read_text(encoding="utf-8")
    ai_reads = re.findall(r'cache_get\(f"ai_predict:[^\n]*', stocks)
    assert ai_reads and all("max_age_hours=3" in r for r in ai_reads), ai_reads
    # model_compare: 를 넣은 근거 — 한 번에 10~30초가 드는 결과를 앱이 7일 안에서 쓴다
    jobs = (ROOT / "app" / "services" / "model_compare_jobs.py").read_text(encoding="utf-8")
    assert re.search(r"^CACHE_TTL_HOURS = 24 \* 7$", jobs, re.M)


@pytest.mark.parametrize("name", _ALL_PS)
def test_state_scripts_are_utf8_bom_with_ascii_sql(name):
    """TC-DCP-09 · 5.1 이 한글을 cp949 로 읽지 않게 UTF-8 BOM 으로 저장하고, 머리말이 있으며, stdin 으로 보내는 SQL(here-string)은 ASCII 만이다."""
    raw = (_PS_DIR / name).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), f"{name} 에 UTF-8 BOM 이 없다"
    text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    assert text.lstrip().startswith("<#") and ".SYNOPSIS" in text and ".DESCRIPTION" in text
    # PowerShell 5.1 은 native 프로세스 stdin 을 ASCII 로 보낸다 → here-string 안의 SQL 에 한글이 있으면 ?로 깨진다
    blocks = _here_strings(text)
    if name in _STATE_SCRIPTS:
        assert blocks, f"{name} 에 here-string(SQL)이 없다"
    for b in blocks:
        assert b.isascii(), f"{name} 의 here-string 에 ASCII 가 아닌 글자가 있다"
    # 5.1 에 없는 문법을 쓰지 않는다 — && · || (파이프라인 체인) · ?? (SQL 의 || 는 here-string 안이라 먼저 뺀다)
    code = re.sub(r"@'\n.*?\n'@", "", text, flags=re.S)
    code = re.sub(r"<#.*?#>", "", code, flags=re.S)
    code = "\n".join(line for line in code.split("\n") if not line.lstrip().startswith("#"))
    code = re.sub(r'"[^"\n]*"', '""', code)
    code = re.sub(r"'[^'\n]*'", "''", code)
    for bad in ("&&", "||", "??"):
        assert bad not in code, f"{name}: PowerShell 5.1 에 없는 {bad} 를 썼다"


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell 5.1 이 있는 PC 에서만")
@pytest.mark.parametrize("name", _ALL_PS)
def test_state_scripts_parse_in_windows_powershell(name):
    """TC-DCP-10 · 세 스크립트(공용 정의 포함)가 PowerShell 5.1 문법 검사를 통과한다(실행하지 않고 구문만)."""
    path = str(_PS_DIR / name)
    cmd = ("$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile("
           f"'{path}',[ref]$t,[ref]$e);$e.Count")
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                         capture_output=True, text=True, timeout=120)
    assert out.stdout.strip() == "0", out.stdout + out.stderr


def _lib_eval(tmp_path: Path, body: str) -> list[str]:
    """공용 정의를 dot-source 한 PowerShell 조각을 실행해 Write-Output 한 줄들을 돌려준다(안내 문구는 호스트로 가서 섞이지 않는다)."""
    script = tmp_path / "libeval.ps1"
    script.write_text(f". '{_PS_DIR / '_common.ps1'}'\n. '{_PS_DIR / _LIB}'\n{body}\n", encoding="utf-8-sig")
    code, text, raw = _run_ps(script)
    assert code == 0, text
    return [ln.strip()[2:] for ln in raw.decode("ascii", errors="ignore").splitlines() if ln.strip().startswith("@@")]


def test_shared_state_helpers_behave(tmp_path):
    """TC-DCP-11 · 공용 정의의 함수가 실제로 동작한다 — 조건은 괄호로 감싼다 · 겹치거나 따옴표가 든 접두사는 거부 · 파일 머리를 읽은 뒤 핸들이 닫혀 있다 · 암호화 파일을 가려낸다."""
    _need_powershell()
    body = r'''
function O($k, $v) { Write-Output ("@@" + $k + "=" + $v) }
O 'cond' (Get-QStateKeyCondition)
O 'default' (Test-QStateKeyPrefixes)
$QStateKeyPrefixes = @('quant:', 'quant:cycle_log:'); O 'overlap' (Test-QStateKeyPrefixes)
$QStateKeyPrefixes = @('quant:', 'quant:'); O 'dup' (Test-QStateKeyPrefixes)
$QStateKeyPrefixes = @("x'y:"); O 'quote' (Test-QStateKeyPrefixes)
$QStateKeyPrefixes = @('a b:'); O 'space' (Test-QStateKeyPrefixes)
$QStateKeyPrefixes = @('quant'); O 'nocolon' (Test-QStateKeyPrefixes)
$QStateKeyPrefixes = @(); O 'empty' (Test-QStateKeyPrefixes)
$QStateKeyPrefixes = @("quant:`n"); O 'newline' (Test-QStateKeyPrefixes)
$QStateKeyPrefixes = @('quant:', 'model_compare:', 'zz:'); O 'three' (Test-QStateKeyPrefixes)
O 'cond3' (Get-QStateKeyCondition)
O 'db' (@((Test-QAppDbName 'qurious_scratch'), (Test-QAppDbName 'Bad'), (Test-QAppDbName "ok`n"), (Test-QAppDbName 'a;b'), (Test-QAppDbName ('a' * 64))) -join ',')
$d = Join-Path $env:TEMP ('qdcp-' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $d | Out-Null
$csv = Join-Path $d 'a.state.csv'
[IO.File]::WriteAllBytes($csv, [Text.Encoding]::UTF8.GetBytes("key,id,data,updated_at`r`nquant:x,1,{},2026-01-01`n"))
O 'first' (Get-QStateFileFirstLine $csv)
Remove-Item -LiteralPath $csv -Force; O 'deleted_after_read' (-not (Test-Path -LiteralPath $csv))
$bom = Join-Path $d 'b.state.csv'
[IO.File]::WriteAllBytes($bom, [byte[]](0xEF,0xBB,0xBF) + [Text.Encoding]::UTF8.GetBytes("key,id,data,updated_at`n"))
O 'bomfirst' (Get-QStateFileFirstLine $bom)
$enc = Join-Path $d 'c.state.csv'
[IO.File]::WriteAllBytes($enc, [byte[]](0x51,0x44,0x42,0x31,0x00,1,2,3,4))
O 'enc' ([string](Test-QEncryptedBackup $enc) + "," + [string](Test-QEncryptedBackup $bom))
$nonl = Join-Path $d 'd.bin'; [IO.File]::WriteAllBytes($nonl, (New-Object byte[] 1000))
O 'nonl' ([string]($null -eq (Get-QStateFileFirstLine $nonl)))
Remove-Item -LiteralPath $d -Recurse -Force
'''
    got = dict(ln.split("=", 1) for ln in _lib_eval(tmp_path, body))
    assert got["cond"] == "(starts_with(key,'quant:') OR starts_with(key,'model_compare:'))"
    assert got["default"] == "True" and got["three"] == "True"
    assert got["cond3"] == "(starts_with(key,'quant:') OR starts_with(key,'model_compare:') OR starts_with(key,'zz:'))"
    for bad in ("overlap", "dup", "quote", "space", "nocolon", "empty", "newline"):
        assert got[bad] == "False", bad
    assert got["db"] == "True,False,False,False,False"
    assert got["first"] == "key,id,data,updated_at" and got["bomfirst"] == "key,id,data,updated_at"
    assert got["deleted_after_read"] == "True", "파일 머리를 읽은 뒤에도 핸들이 열려 있어 지우지 못했다"
    assert got["enc"] == "True,False" and got["nonl"] == "True"


def test_gitignore_blocks_backup_artifacts():
    """TC-DCP-12 · 앱 DB 백업 산출물(.dump · .state.csv · 상태 내보내기가 실패했을 때 덤프가 바뀌는 .dump.incomplete)은 어느 폴더에 만들어도 커밋되지 않는다 — .gitignore 세 줄."""
    lines = [ln.strip() for ln in (ROOT / ".gitignore").read_bytes().decode("utf-8").splitlines()]
    assert "*.dump" in lines and "*.state.csv" in lines and "*.dump.incomplete" in lines
    i = lines.index("*.dump")
    assert lines[i - 1].startswith("#"), "산출물 설명 주석 한 줄이 세 줄 바로 위에 있어야 한다"
    assert lines[i + 1:i + 3] == ["*.state.csv", "*.dump.incomplete"], "산출물 세 줄은 한 덩어리로 붙어 있다"
    if shutil.which("git"):
        # *.dump 는 .dump.incomplete 를 막지 못한다(끝이 다르다) — 그래서 세 번째 줄이 따로 필요하다
        for sample in ("appdb-20261102-210015.dump", "sub/dir/appdb-20261102-210015.state.csv", "sub/dir/appdb-20261102-210015.dump.incomplete"):
            p = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--", sample], capture_output=True, timeout=60)
            assert p.returncode == 0, sample


def _fake_git_env(tmp_path: Path, exit_code: int) -> dict:
    fake = tmp_path / f"fakegit{exit_code}"
    fake.mkdir(exist_ok=True)
    (fake / "git.cmd").write_text(f"@echo off\r\nexit /b {exit_code}\r\n", encoding="ascii")
    env = os.environ.copy()
    env["PATH"] = str(fake) + os.pathsep + env.get("PATH", "")
    return env


def _fake_git_env_only_incomplete_unignored(tmp_path: Path) -> dict:
    """check-ignore 에 .dump.incomplete 가 든 이름이 오면 종료 코드 1(무시 안 됨), 그 밖의 이름은 0(무시됨)이라고 답하는 가짜 git."""
    fake = tmp_path / "fakegit_incomplete"
    fake.mkdir(exist_ok=True)
    (fake / "git.cmd").write_text("@echo off\r\necho %* | findstr /C:\".dump.incomplete\" >nul\r\nif %errorlevel%==0 (exit /b 1) else (exit /b 0)\r\n", encoding="ascii")
    env = os.environ.copy()
    env["PATH"] = str(fake) + os.pathsep + env.get("PATH", "")
    return env


def test_backup_preflight_refuses_unignored_repo_folder_and_warns_on_sync_folder(tmp_path):
    """TC-DCP-12b · 백업은 저장소 안 출력 폴더가 .gitignore 에 안 걸리면 멈추고(git 종료 코드 1 · 128), 동기화 폴더 이름이면 경고하며, -DryRun 은 폴더를 만들지 않는다."""
    _need_powershell()
    backup = _PS_DIR / "backup-appdb.ps1"
    repo_out = _PS_DIR / "_pytest_unignored_out"
    for code in (1, 128):
        rc, text, raw = _run_ps(backup, "-DryRun", "-OutDir", repo_out, env=_fake_git_env(tmp_path, code))
        assert rc == 1, text
        assert _has(raw, ".gitignore") and not repo_out.exists()
    # git 이 「무시됨」(0)이라고 하면 통과
    rc, text, _ = _run_ps(backup, "-DryRun", "-OutDir", repo_out, env=_fake_git_env(tmp_path, 0))
    assert rc == 0, text
    if shutil.which("git"):
        # 진짜 git: .gitignore 의 세 줄(*.dump · *.state.csv · *.dump.incomplete)이 어느 폴더든 막으므로, 저장소 안 폴더도 통과한다.
        # 점검이 묻는 세 이름이 모두 실제로 무시되는지도 직접 확인한다 — .gitignore 에서 줄이 빠지면 점검이 멈추는 것이 맞다.
        rc, text, _ = _run_ps(backup, "-DryRun")
        assert rc == 0, text
        for name in ("appdb-00000000-000000.dump", "appdb-00000000-000000.state.csv", "appdb-00000000-000000.dump.incomplete"):
            probe = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--", f"scripts/personal/_pytest_unignored_out/{name}"],
                                   capture_output=True, timeout=60)
            assert probe.returncode == 0, f".gitignore 가 {name} 을 막지 못한다"
        rc, text, raw = _run_ps(backup, "-DryRun", "-OutDir", repo_out)
        assert rc == 0, text
    assert not repo_out.exists()
    # 세 이름 가운데 .dump.incomplete 만 안 막힌 상황(.gitignore 의 그 줄이 사라졌다)을 가짜 git 으로 만든다 — 점검이 그 이름도 묻는다는 증거.
    # 이 점검은 .gitignore 줄이 있어도 남겨 둔 안전망이다(줄이 빠지면 평문 덤프가 커밋될 수 있어 멈춘다).
    rc, text, raw = _run_ps(backup, "-DryRun", "-OutDir", repo_out, env=_fake_git_env_only_incomplete_unignored(tmp_path))
    assert rc == 1 and b".dump.incomplete" in raw and _has(raw, ".gitignore") and not repo_out.exists(), text
    # 저장소 밖 폴더는 git 을 묻지 않는다(종료 코드 1 짜리 가짜 git 이어도 통과). 동기화 폴더 이름이면 경고만 한다
    plain = tmp_path / "plain" / "bk"
    sync = tmp_path / "OneDrive" / "bk"
    rc, text, raw_plain = _run_ps(backup, "-DryRun", "-OutDir", plain, env=_fake_git_env(tmp_path, 1))
    assert rc == 0, text
    rc, text, raw_sync = _run_ps(backup, "-DryRun", "-OutDir", sync)
    assert rc == 0, text
    assert not _has(raw_plain, "동기화 폴더로 보입니다") and _has(raw_sync, "동기화 폴더로 보입니다")
    assert not plain.exists() and not sync.exists(), "-DryRun 은 폴더를 만들지 않는다"
    # 잘못된 -Database 는 Docker 에 닿기 전에 막는다
    for bad in ("Bad;rm", "UPPER", "a b"):
        rc, _, _ = _run_ps(backup, "-DryRun", "-Database", bad)
        assert rc == 1, bad


def test_restore_rejects_bad_input_before_touching_docker(tmp_path):
    """TC-DCP-14 · 복원은 Docker 없이도 입력 오류를 먼저 막는다 — 선택자 둘 · 잘못된 -Stamp · -Apply+-DryRun · 없는 파일 · 머리글 다른 파일 · 암호화한 파일(복호화 안내)."""
    _need_powershell()
    restore = _PS_DIR / "restore-appdb-state.ps1"
    good = tmp_path / "appdb-20261102-210015.state.csv"
    good.write_bytes(b"key,id,data,updated_at\n")
    cases = [
        ("-Apply", "-DryRun", "-StateFile", good),
        ("-StateFile", good, "-Stamp", "20261102-210015"),
        ("-Stamp", "2026-11-02"),
        ("-Stamp", "20261102-210015\n"),
        ("-DumpFile", tmp_path / "notappdb.dump"),
        ("-StateFile", tmp_path / "missing.state.csv"),
        ("-Stamp", "20201231-235959", "-BackupDir", tmp_path),
        ("-StateFile", good, "-Database", "Bad;name"),
    ]
    for args in cases:
        rc, text, _ = _run_ps(restore, *args)
        assert rc == 1, (args, text)
    wrong = tmp_path / "appdb-20261102-210016.state.csv"
    wrong.write_bytes(b"a,b,c\n1,2,3\n")
    rc, text, raw = _run_ps(restore, "-StateFile", wrong)
    assert rc == 1 and _has(raw, "복호화"), text
    sealed = tmp_path / "appdb-20261102-210017.state.csv"
    sealed.write_bytes(b"QDB1\x00" + b"\x01" * 40)
    rc, text, raw = _run_ps(restore, "-StateFile", sealed)
    assert rc == 1 and _has(raw, "암호화한 파일입니다") and b"protect_database_backup.py --decrypt" in raw, text
    # 짝 확인 — -DumpFile 은 같은 시각의 .state.csv 를 찾는다(없으면 그 이름을 말하며 멈춘다)
    rc, text, raw = _run_ps(restore, "-DumpFile", tmp_path / "appdb-20261102-210099.dump")
    assert rc == 1 and b"appdb-20261102-210099.state.csv" in raw, text


# ── 복원 -Apply 의 「앱 켜짐」 점검 — 가짜 docker (진짜 Docker · 개발 DB 에 닿지 않는다) ─────────────────────────────

#: 가짜 docker(배치 파일 — 파이썬을 띄우지 않아 호출마다 수십 밀리초) — 부른 인자 앞 세 개를 FAKE_DOCKER_LOG 에 한 줄씩 남기고,
#: 컨테이너 상태는 FAKE_DOCKER_DIR 의 <이름>.state 파일(첫 줄 = 상태)에서 읽는다(파일이 없으면 inspect 실패 = 컨테이너 없음).
#: psql(exec -i)에는 RESULT 줄을 돌려준다. FAKE_DOCKER_DOWN=1 이면 엔진이 꺼진 척한다.
_FAKE_DOCKER_CMD = "\r\n".join([
    "@echo off",
    "setlocal EnableDelayedExpansion",
    '>>"%FAKE_DOCKER_LOG%" echo %1 %2 %3',
    # 괄호 블록 안의 exit /b 는 뒤의 exit /b 0 에 덮여 종료 코드가 0 이 되는 cmd 의 버릇이 있어 goto 로 가른다
    'if "%1"=="version" goto :version',
    'if "%1"=="inspect" goto :inspect',
    'if "%1"=="cp" exit /b 0',
    'if "%1"=="exec" goto :exec',
    "exit /b 1",
    ":version",
    'if "%FAKE_DOCKER_DOWN%"=="1" exit /b 1',
    "exit /b 0",
    ":inspect",
    'if not exist "%FAKE_DOCKER_DIR%\\%2.state" exit /b 1',
    'set /p ST=<"%FAKE_DOCKER_DIR%\\%2.state"',
    'echo [{"State":{"Status":"!ST!"},"Config":{"Labels":{}},"Mounts":[]}]',
    "exit /b 0",
    ":exec",
    'if not "%2"=="-i" exit /b 0',
    "more >nul",
    "echo RESULT^|2^|1^|1^|0",
    "exit /b 0",
    "",
])


def _fake_docker_env(tmp_path: Path, tag: str, states: dict[str, str], down: bool = False) -> tuple[dict, Path]:
    d = tmp_path / f"fakedocker_{tag}"
    d.mkdir()
    log = d / "calls.txt"
    (d / "docker.cmd").write_text(_FAKE_DOCKER_CMD, encoding="ascii", newline="")
    for name, status in states.items():
        (d / f"{name}.state").write_text(status, encoding="ascii")
    env = os.environ.copy()
    env["PATH"] = str(d) + os.pathsep + env.get("PATH", "")
    env["FAKE_DOCKER_LOG"], env["FAKE_DOCKER_DIR"], env["FAKE_DOCKER_DOWN"] = str(log), str(d), "1" if down else "0"
    # PowerShell 도 같은 순서(PATH 앞쪽 · PATHEXT)로 찾는다 — 진짜 docker 로 새지 않는지 미리 확인한다
    assert Path(shutil.which("docker", path=env["PATH"])) == d / "docker.cmd", "가짜 docker 가 PATH 맨 앞에서 먼저 잡히지 않는다"
    return env, log


def test_restore_apply_stops_while_app_is_running_unless_forced(tmp_path):
    """TC-DCP-18 · 복원 -Apply 는 앱 · 워커 · 비트가 하나라도 켜져 있으면 파일을 컨테이너로 보내기 전에 멈추고(-Force · stop.ps1 안내), -Force 면 경고만 하고 진행하며,
    -DryRun 은 막지 않고 경고만 한다. 컨테이너가 없거나 꺼져 있으면 막지 않고 상태를 한 줄로 보이고, -Database(임시 DB)는 점검하지 않는다.
    Docker 엔진이 꺼져 있으면 기존대로 이유를 알리고 멈춘다. 전부 가짜 docker 라 진짜 Docker · 개발 DB 에는 닿지 않는다(상태 파일도 머리글뿐)."""
    _need_powershell()
    from concurrent.futures import ThreadPoolExecutor
    restore = _PS_DIR / "restore-appdb-state.ps1"
    state = tmp_path / "appdb-20261102-210015.state.csv"
    state.write_bytes(b"key,id,data,updated_at\n")
    up = {"fin-ai-postgres": "running"}
    apps = {"fin-ai-app": "running", "fin-ai-celery-worker": "running", "fin-ai-celery-beat": "running"}
    # (이름, 컨테이너 상태, 인자, 엔진 꺼짐) — 서로 독립이라 함께 돌린다(PowerShell 시작이 느려 차례로 하면 시험이 길어진다)
    cases = {
        "beat_only": ({**up, "fin-ai-celery-beat": "running", "fin-ai-app": "exited"}, ("-Apply",), False),
        "all_running_apply": ({**up, **apps}, ("-Apply",), False),
        "force": ({**up, **apps}, ("-Apply", "-Force"), False),
        "dry": ({**up, **apps}, (), False),
        "stopped": ({**up, "fin-ai-app": "exited"}, ("-Apply",), False),
        "scratch_db": ({**up, **apps}, ("-Apply", "-Database", "qurious_scratch_fake"), False),
        "engine_down": ({**up, **apps}, ("-Apply", "-Force"), True),
    }
    envs = {name: _fake_docker_env(tmp_path, name, states, down=down) for name, (states, _, down) in cases.items()}

    def go(name):
        env, log = envs[name]
        rc, text, raw = _run_ps(restore, "-StateFile", state, *cases[name][1], env=env)
        return rc, text, raw, ([ln.strip() for ln in log.read_text(encoding="utf-8").splitlines()] if log.exists() else [])

    with ThreadPoolExecutor(max_workers=len(cases)) as pool:
        got = dict(zip(cases, pool.map(go, cases)))

    def sent(calls):  # 상태 파일을 컨테이너로 보내거나 psql 을 실행한 호출
        return [c for c in calls if c.startswith("cp ") or c.startswith("exec ")]

    def cp_sent(calls):
        return any(c.startswith("cp ") for c in calls)

    for name, (_, _, _, calls) in got.items():  # 모든 실행이 가짜 docker 를 불렀다(진짜 docker 로 새지 않았다)
        assert any(c.startswith("version") for c in calls), f"{name}: 가짜 docker 가 불리지 않았다 {calls}"
    # 1) 켜져 있고 -Apply → 멈춘다(비트 하나만 켜져 있어도 · 셋 다 켜져 있어도). 파일은 컨테이너로 보내지 않았고, -Force · stop.ps1 · 사이클 위험을 알린다
    for name in ("beat_only", "all_running_apply"):
        rc, text, raw, calls = got[name]
        assert rc == 1, (name, text)
        assert _has(raw, "-Apply 를 멈춥니다") and b"-Force" in raw and b"stop.ps1" in raw and _has(raw, "자동매매 사이클") and _has(raw, "아무것도 바꾸지 않았습니다"), (name, text)
        assert sent(calls) == [] and "inspect fin-ai-app" in calls, (name, calls)
    assert b"fin-ai-celery-beat" in got["beat_only"][2], "켜져 있는 컨테이너 이름을 알려 준다"
    # 2) -Force → 경고만 하고 진행(가짜 psql 의 결과를 읽어 끝난다)
    rc, text, raw, calls = got["force"]
    assert rc == 0, text
    assert _has(raw, "-Force 라 진행합니다") and "[new=1 update=1 keep=0]" in text and _has(raw, "적용 완료"), text
    assert cp_sent(calls) and any(c.startswith("exec -i ") for c in calls), calls
    # 3) -DryRun(기본) → 막지 않고 경고만(적용하려면 끄거나 -Force)
    rc, text, raw, calls = got["dry"]
    assert rc == 0 and _has(raw, "-DryRun 은 아무것도 바꾸지 않아 진행합니다") and "[new=1 update=1 keep=0]" in text and cp_sent(calls), (text, calls)
    # 4) 앱 · 워커 · 비트가 꺼져 있거나 없다 → 막지 않고, 상태를 한 줄로 보인다
    rc, text, raw, calls = got["stopped"]
    assert rc == 0 and _has(raw, "켜져 있지 않아") and b"fin-ai-app=exited" in raw and b"fin-ai-celery-worker=missing" in raw and cp_sent(calls), (text, calls)
    # 5) -Database(임시 DB)는 앱이 쓰는 DB 가 아니라 점검하지 않는다 — 앱이 켜져 있어도 막지 않고 앱 컨테이너를 묻지도 않는다
    rc, text, raw, calls = got["scratch_db"]
    assert rc == 0 and not [c for c in calls if c.startswith("inspect fin-ai-app")] and cp_sent(calls), (text, calls)
    # 6) Docker 엔진이 꺼져 있으면 기존대로 이유(Docker Desktop 이 꺼져 있습니다)를 알리고 멈춘다 — 파일은 보내지 않는다
    rc, text, raw, calls = got["engine_down"]
    assert rc == 1 and _has(raw, "Docker Desktop 이 꺼져 있습니다") and sent(calls) == [], (text, calls)


# ── 행동 시험 — 임시 DB 왕복 (QURIOUS_TEST_DOCKER_DB=1 로 켰고 Docker 의 fin-ai-postgres 가 켜져 있을 때만) ───────────
# 개발 DB(POSTGRES_DB)에는 INSERT · UPDATE · DELETE 를 하지 않는다. 표 정의를 읽기 전용 pg_dump --schema-only 로 떠 와
# 이름이 qurious_scratch_ 로 시작하는 임시 DB 에서만 쓴다. 이름은 고유(uuid)하고 끝나면 반드시 DROP 한다.
# 기본은 건너뛴다(전체 시험에 약 50초가 붙는다) — 환경변수 QURIOUS_TEST_DOCKER_DB=1 로 켠다(파일 머리 설명 참고).

DOCKER_OPT_IN_ENV = "QURIOUS_TEST_DOCKER_DB"
DOCKER_OPT_IN_REASON = "QURIOUS_TEST_DOCKER_DB=1 로 켠다 (Docker 임시 DB 행동 시험 · 약 50초)"


def _docker_opted_in() -> bool:
    return os.environ.get(DOCKER_OPT_IN_ENV, "").strip().lower() in ("1", "true", "yes")


#: 행동 시험(TC-DCP-15 ~ 17)에 붙인다. 파일을 불러올 때 환경변수를 한 번 읽는다 — 켜거나 끈 뒤에는 pytest 를 새로 돌린다.
needs_docker_db = pytest.mark.skipif(not _docker_opted_in(), reason=DOCKER_OPT_IN_REASON)

_SPECIAL = {
    "cycles": [{"t": "2026-11-02T09:10:00+09:00", "msg": '삼성전자 매수 "시도", 줄바꿈\n두번째 줄 \\ 백슬래시 \t탭 / 쉼표,따옴표"', "n": 1, "emoji": "😀🚀"}],
    "x": None,
    "nested": {"a": [1, 2, {"b": "c,d"}]},
}
#: (키, 값, updated_at) — 내보낼 원본 줄. 접두사 목록 두 개를 모두 쓰고, 값에는 쉼표 · 따옴표 · 개행 · 한글 · 이모지 · 백슬래시 · 200KB 가 든다.
_FILE_ROWS = [
    ("quant:cycle_log:u1", _SPECIAL, "2026-10-16 03:12:45.123456+00"),
    ("quant:reconcile:baseline:u1:paper", {"base": 100000, "note": "기준선"}, "2026-10-01 12:00:00+09"),
    ("quant:reconcile:latest:u1", {"ok": True}, "2026-11-02 00:00:00+00"),
    ('quant:weird,"key"', {"k": 'comma, quote" and backslash \\'}, "2026-09-01 00:00:00+00"),
    ("quant:line\nbreak", {"nl": True}, "2026-09-02 00:00:00+00"),
    ("quant:big", {"blob": "x" * 200_000}, "2026-09-03 00:00:00+00"),
    ("model_compare:v1:005930:2y:abc", {"fingerprint": "f1", "rows": [1, 2, 3], "설명": "한글 값"}, "2026-10-30 00:00:00+00"),
    ("model_compare:v1:big", {"blob": "y" * 200_000}, "2026-10-30 01:00:00+00"),
    ("quant:keepme", {"file": "older"}, "2026-10-02 00:00:00+00"),
    ("quant:keep\nnl", {"file": "older2"}, "2026-10-03 00:00:00+00"),
]
#: 접두사 밖 키 — 상태 파일에 없어야 한다.
_OUTSIDE_ROWS = [("candles:005930:1y:1d", {"close": [1, 2, 3]}), ("ai_predict:v5:005930", {"p": 0.5}), ("indicators:AAPL:2y", {"i": 1})]
#: 새 PC 흉내 — 빈 표(pg_restore 직후)에 이미 있던 줄. 갱신(오래됨 · 같은 시각) · 지킴(더 최근) · 접두사 밖.
_TARGET_ROWS = [
    ("quant:cycle_log:u1", {"old": True}, "2026-10-01 00:00:00+00"),
    ("quant:reconcile:latest:u1", {"ok": False}, "2026-11-02 00:00:00+00"),
    ("quant:keepme", {"target": "newer"}, "2026-11-02 09:00:00+00"),
    ("quant:keep\nnl", {"target": "newer2"}, "2026-11-02 09:00:00+00"),
    ("candles:005930:1y:1d", {"target": "only"}, "2026-11-02 08:00:00+00"),
]
_EXPECT_NEW = {"quant:reconcile:baseline:u1:paper", 'quant:weird,"key"', "quant:line\nbreak", "quant:big", "model_compare:v1:005930:2y:abc", "model_compare:v1:big"}
_EXPECT_UPDATE = {"quant:cycle_log:u1", "quant:reconcile:latest:u1"}
_EXPECT_KEEP = {"quant:keepme", "quant:keep\nnl"}
_SENTINEL = "SENTINEL_SECRET_VALUE_4242"
_FP_ALL = ("SELECT md5(coalesce(string_agg(key || '|' || id::text || '|' || data::text || '|' || updated_at::text, E'\\n' ORDER BY key), '')) "
           "|| ' n=' || count(*) FROM data_cache;")


def _docker(*args, input: bytes | None = None, timeout: int = 240) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], input=input, capture_output=True, timeout=timeout)


def _psql(db: str, sql: str, check: bool = True) -> str:
    cmd = f"PGCLIENTENCODING=UTF8 psql -U $POSTGRES_USER -d {db} -X -A -t -v ON_ERROR_STOP=1 -f -"
    p = _docker("exec", "-i", _PG, "sh", "-c", cmd, input=sql.encode("utf-8"))
    if check:
        assert p.returncode == 0, p.stderr.decode("utf-8", errors="replace")
    return p.stdout.decode("utf-8", errors="replace").strip()


def _sql_key(key: str) -> str:
    return "E'" + key.replace("\\", "\\\\").replace("'", "''").replace("\n", "\\n") + "'"


def _sql_json(obj) -> str:
    text = json.dumps(obj, ensure_ascii=False)
    assert "$j$" not in text
    return f"$j${text}$j$::jsonb"


def _insert_sql(rows) -> str:
    values = ",\n".join(f"({_sql_key(k)}, {_sql_json(v)}, '{ts}')" if ts else f"({_sql_key(k)}, {_sql_json(v)}, now())" for k, v, ts in rows)
    return f"INSERT INTO data_cache (key, data, updated_at) VALUES\n{values};"


def _rows(db: str) -> dict[str, dict]:
    raw = _psql(db, "SELECT coalesce(jsonb_agg(jsonb_build_object('key', key, 'data', data, 'ts', updated_at::text, 'id', id::text) ORDER BY key), '[]'::jsonb) FROM data_cache;")
    return {r["key"]: r for r in json.loads(raw)}


def _docker_skip_reason() -> str | None:
    # 안전망: 위의 @needs_docker_db 를 빠뜨린 시험이 있어도 켜지 않았으면 Docker 에 닿지 않는다.
    if not _docker_opted_in():
        return DOCKER_OPT_IN_REASON
    if sys.platform != "win32" or shutil.which("powershell") is None:
        return "Windows PowerShell 5.1 이 있는 PC 에서만"
    if shutil.which("docker") is None:
        return "docker 명령이 없다"
    try:
        p = _docker("inspect", "-f", "{{.State.Running}}", _PG, timeout=30)
    except Exception as exc:  # noqa: BLE001 — Docker 가 응답하지 않으면 시험을 건너뛴다
        return f"Docker 가 응답하지 않는다: {exc}"
    if p.returncode != 0 or p.stdout.strip() != b"true":
        return f"{_PG} 컨테이너가 켜져 있지 않다"
    return None


def _scratch_name() -> str:
    """임시 DB 이름 — 고유(uuid)하다. QURIOUS_SCRATCH_DB 로 정해 줄 수 있어도 반드시 qurious_scratch_ 로 시작해야 한다(개발 DB 보호)."""
    name = os.environ.get("QURIOUS_SCRATCH_DB") or f"qurious_scratch_pytest_{uuid.uuid4().hex[:8]}"
    assert re.fullmatch(r"qurious_scratch_[a-z0-9_]{1,30}", name), f"임시 DB 이름 규칙 위반: {name}"
    return name


def _db_exists(name: str) -> bool:
    return _psql("postgres", f"SELECT count(*) FROM pg_database WHERE datname = '{name}';") != "0"


def _create_scratch(name: str, clone_schema: bool = True) -> None:
    assert not _db_exists(name), f"이미 {name} 이 있다 — 중단"
    _psql("postgres", f"CREATE DATABASE {name};")
    if clone_schema:  # 개발 DB 는 읽기만 한다(pg_dump --schema-only 는 읽기 전용)
        p = _docker("exec", _PG, "sh", "-c",
                    f"pg_dump -U $POSTGRES_USER -d $POSTGRES_DB --schema-only -t data_cache | psql -U $POSTGRES_USER -d {name} -X -q -v ON_ERROR_STOP=1")
        assert p.returncode == 0, p.stderr.decode("utf-8", errors="replace")


def _drop_scratch(name: str) -> None:
    assert name.startswith("qurious_scratch_")
    _psql("postgres", f"DROP DATABASE IF EXISTS {name} WITH (FORCE);", check=False)
    assert not _db_exists(name), f"임시 DB {name} 가 남아 있다"


@pytest.fixture(scope="module")
def docker_env():
    why = _docker_skip_reason()
    if why:
        pytest.skip(why)


@pytest.fixture(scope="module")
def env(docker_env, tmp_path_factory):
    """원본 줄을 넣고 → 실제 백업 스크립트로 백업 → 새 PC 흉내(DB 새로 만들기 + pg_restore) → 대상 줄을 넣는다. 끝나면 임시 DB 를 DROP 한다."""
    db = _scratch_name()
    base = tmp_path_factory.mktemp("appdb")
    ns = SimpleNamespace(db=db, out_dir=base / "out", base=base)
    try:
        _create_scratch(db)
        _psql(db, _insert_sql(_FILE_ROWS))
        _psql(db, _insert_sql([(k, v, None) for k, v in _OUTSIDE_ROWS]))
        ns.source = _rows(db)
        rc, text, raw = _run_ps(_PS_DIR / "backup-appdb.ps1", "-Database", db, "-OutDir", ns.out_dir)
        ns.backup = SimpleNamespace(code=rc, text=text, raw=raw)
        ns.dumps = sorted(ns.out_dir.glob("appdb-*.dump"))
        ns.states = sorted(ns.out_dir.glob("appdb-*.state.csv"))
        if rc != 0 or len(ns.dumps) != 1 or len(ns.states) != 1:
            pytest.fail(f"백업이 실패했다(종료 코드 {rc}): {text}")
        # 새 PC 흉내: 임시 DB 를 지우고 다시 만든 뒤 덤프를 pg_restore(표 정의만 돌아온다)
        _psql("postgres", f"DROP DATABASE {db} WITH (FORCE);")
        _psql("postgres", f"CREATE DATABASE {db};")
        tmp_dump = f"/tmp/pytest-{db}.dump"
        try:
            assert _docker("cp", str(ns.dumps[0]), f"{_PG}:{tmp_dump}").returncode == 0
            p = _docker("exec", _PG, "sh", "-c", f"pg_restore -U $POSTGRES_USER -d {db} --no-owner {tmp_dump}")
            assert p.returncode == 0, p.stderr.decode("utf-8", errors="replace")
        finally:
            _docker("exec", _PG, "rm", "-f", tmp_dump)
        ns.rows_after_pg_restore = _psql(db, "SELECT count(*) FROM data_cache;")
        _psql(db, _insert_sql([(k, v, ts) for k, v, ts in _TARGET_ROWS]))
        ns.target_before = _rows(db)
        ns.fp0 = _psql(db, _FP_ALL)
        yield ns
    finally:
        _drop_scratch(db)


def _restore(env, *args):
    return _run_ps(_PS_DIR / "restore-appdb-state.ps1", "-Database", env.db, *args)


def _counts(text: str) -> tuple[int, int, int]:
    m = re.search(r"\[new=(\d+) update=(\d+) keep=(\d+)\]", text)
    assert m, text
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


@pytest.fixture(scope="module")
def dry(env):
    """-DryRun(기본) — 같은 INSERT 를 실행한 뒤 ROLLBACK. 표는 그대로여야 한다."""
    rc, text, raw = _restore(env, "-StateFile", env.states[0])
    return SimpleNamespace(code=rc, text=text, raw=raw, fp=_psql(env.db, _FP_ALL), rows=_rows(env.db))


@pytest.fixture(scope="module")
def guards(env, dry):
    """잘못된 파일 · 선택 방식 — 실패해야 하고 표는 그대로여야 하며, 오류 출력에 값이 새지 않아야 한다. (Apply 보다 먼저 실행되게 dry 에만 기댄다)"""
    d = env.base / "bad"
    d.mkdir()
    header = b"key,id,data,updated_at\n"
    uid = b"0b0b0b0b-0000-4000-8000-000000000001"
    files = {
        "outside": header + b"candles:x," + uid + b',"{}",2026-01-01 00:00:00+00\n',
        "dup": header + b"quant:a," + uid + b',"{}",2026-01-01 00:00:00+00\nquant:a,' + uid.replace(b"1", b"2") + b',"{}",2026-01-01 00:00:00+00\n',
        "badjson": header + b"quant:a," + uid + b',"{' + _SENTINEL.encode() + b'",2026-01-01 00:00:00+00\n',
        "cols": b"key,id,data,updated_at\nquant:a," + uid + b"\n",
    }
    out = SimpleNamespace(results={}, paths={})
    for name, body in files.items():
        p = d / f"appdb-20261102-2100{len(out.results):02d}.state.csv"
        p.write_bytes(body)
        out.paths[name] = p
        out.results[name] = _restore(env, "-StateFile", p, "-Apply")
    # 실패한 -Apply 는 표를 바꾸지 않는다
    out.fp_after_failures = _psql(env.db, _FP_ALL)
    # 대조군: -v VERBOSITY=terse 없이 psql 을 부르면 같은 깨진 줄의 내용이 오류에 찍힌다 → 위 시험이 실제로 의미가 있다
    ctl = f"/tmp/pytest-ctl-{env.db}.csv"
    try:
        assert _docker("cp", str(out.paths["badjson"]), f"{_PG}:{ctl}").returncode == 0
        sql = ("BEGIN;\nCREATE TEMP TABLE t (key text, id uuid, data jsonb, updated_at timestamptz);\n"
               f"\\copy t FROM '{ctl}' WITH (FORMAT csv, HEADER)\nROLLBACK;\n")
        cmd = f"PGCLIENTENCODING=UTF8 psql -U $POSTGRES_USER -d {env.db} -X -A -t -v ON_ERROR_STOP=1 -f -"
        p = _docker("exec", "-i", _PG, "sh", "-c", cmd, input=sql.encode("utf-8"))
        out.control_stderr = p.stderr
    finally:
        _docker("exec", _PG, "rm", "-f", ctl)
    # 파일 선택 — 자동(가장 나중 이름) · -Stamp · -DumpFile. 폴더에는 더 오래된 이름의 빈 상태 파일(미끼)을 함께 둔다
    sel = env.base / "sel"
    sel.mkdir()
    for f in (*env.dumps, *env.states):
        shutil.copy(f, sel / f.name)
    (sel / "appdb-20200101-000000.state.csv").write_bytes(header)
    stamp = re.search(r"appdb-(\d{8}-\d{6})", env.states[0].name).group(1)
    out.stamp = stamp
    out.auto = _restore(env, "-BackupDir", sel)
    out.by_stamp = _restore(env, "-BackupDir", sel, "-Stamp", stamp)
    out.by_dump = _restore(env, "-DumpFile", sel / f"appdb-{stamp}.dump")
    out.by_missing_stamp = _restore(env, "-BackupDir", sel, "-Stamp", "20210101-000000")
    out.fp_after_selection = _psql(env.db, _FP_ALL)
    return out


@pytest.fixture(scope="module")
def applied(env, guards):
    first = _restore(env, "-StateFile", env.states[0], "-Apply")
    rows1, fp1 = _rows(env.db), _psql(env.db, _FP_ALL)
    second = _restore(env, "-StateFile", env.states[0], "-Apply")
    rows2, fp2 = _rows(env.db), _psql(env.db, _FP_ALL)
    return SimpleNamespace(first=first, rows1=rows1, fp1=fp1, second=second, rows2=rows2, fp2=fp2)


@needs_docker_db
def test_roundtrip_backup_makes_a_paired_utf8_csv(env):
    """TC-DCP-15 (백업) · 덤프와 상태 파일이 같은 시각(초까지) 이름 한 쌍이고, 상태 파일은 머리글 + 접두사 두 개의 줄만, 한글은 UTF-8 그대로(BOM 없음)이며, pg_restore 뒤 data_cache 는 빈 표다."""
    dump, state = env.dumps[0], env.states[0]
    m1, m2 = re.fullmatch(r"appdb-(\d{8}-\d{6})\.dump", dump.name), re.fullmatch(r"appdb-(\d{8}-\d{6})\.state\.csv", state.name)
    assert m1 and m2 and m1.group(1) == m2.group(1)
    assert list(env.out_dir.glob("*.incomplete")) == []
    data = state.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf") and data.startswith(b"key,id,data,updated_at\n")
    text = data.decode("utf-8")
    assert "삼성전자 매수" in text and "기준선" in text and "한글 값" in text
    csv.field_size_limit(10_000_000)  # 200KB 값이 한 칸에 든다(기본 한도는 128KB)
    rows = list(csv.reader(io.StringIO(text, newline="")))
    assert rows[0] == ["key", "id", "data", "updated_at"]
    keys = [r[0] for r in rows[1:]]
    assert sorted(keys) == sorted(k for k, _, _ in _FILE_ROWS), "상태 파일 키 = 접두사 두 개에 든 원본 줄 전부"
    assert any(k.startswith("quant:") for k in keys) and any(k.startswith("model_compare:") for k in keys)
    for outside, _ in _OUTSIDE_ROWS:
        assert outside not in keys and outside not in text, f"접두사 밖 키가 상태 파일에 있다: {outside}"
    assert env.rows_after_pg_restore == "0", "pg_restore 뒤 data_cache 는 줄이 빠진 빈 표여야 한다"
    assert _has(env.backup.raw, "백업 완료") and b"quant:*" in env.backup.raw and b"model_compare:*" in env.backup.raw


@needs_docker_db
def test_roundtrip_dry_run_changes_nothing_but_counts_the_real_upsert(env, dry):
    """TC-DCP-15 (바) · -DryRun 은 표를 바꾸지 않고(지문 같음), 같은 INSERT 를 실행해 새로 6 · 갱신 2 · 지킴 2 로 센다."""
    assert dry.code == 0, dry.text
    assert dry.fp == env.fp0 and dry.rows == env.target_before
    assert _counts(dry.text) == (6, 2, 2)
    assert _has(dry.raw, "대상이 더 최근이라 지킬") and b'"quant:keepme"' in dry.raw


@needs_docker_db
def test_roundtrip_bad_files_fail_without_changing_the_table_or_leaking_values(env, guards):
    """TC-DCP-15 (안전) · 접두사 밖 키 · 중복 키 · 깨진 JSON · 열 수가 다른 파일은 -Apply 도 실패하고 표는 그대로이며, 오류 출력에 값(JSON)이 새지 않는다."""
    for name, (rc, text, raw) in guards.results.items():
        assert rc == 1, (name, text)
        assert _SENTINEL.encode() not in raw, f"{name}: 오류 출력에 값이 새어 나왔다"
    assert guards.fp_after_failures == env.fp0
    # 대조군: terse 없이 부르면 값이 찍힌다 — 위 단언이 의미가 있다는 증거
    assert _SENTINEL.encode() in guards.control_stderr
    assert _psql(env.db, "SELECT count(*) FROM pg_tables WHERE tablename LIKE '\\_qurious%';") == "0", "임시 표가 남았다"


@needs_docker_db
def test_roundtrip_file_selection_pairs_by_stamp_and_shows_the_chosen_file(env, guards):
    """TC-DCP-15 (짝) · 자동 선택은 가장 나중 이름을 고르고 그 파일 이름 · 짝 덤프를 보여 주며, -Stamp · -DumpFile 도 같은 파일을 쓰고, 없는 시각은 멈춘다."""
    stamp_name = f"appdb-{guards.stamp}.state.csv".encode()
    for label in ("auto", "by_stamp", "by_dump"):
        rc, text, raw = getattr(guards, label)
        assert rc == 0, (label, text)
        assert stamp_name in raw, label
        assert _counts(text) == (6, 2, 2), f"{label}: 미끼(빈 파일)가 아니라 진짜 파일을 써야 한다"
    assert b"appdb-" + guards.stamp.encode() + b".dump" in guards.auto[2], "짝 덤프를 보여 준다"
    assert _has(guards.auto[2], "후보 2개")
    assert guards.by_missing_stamp[0] == 1
    assert guards.fp_after_selection == env.fp0


@needs_docker_db
def test_roundtrip_apply_updates_older_inserts_missing_and_keeps_newer(env, applied):
    """TC-DCP-15 (가)(나)(다) · -Apply: 파일이 더 최근(또는 같은 시각)이면 갱신(id 는 대상 것 그대로) · 대상이 더 최근이면 지킴(값 불변) · 대상에 없으면 새로 넣음(id · updated_at 원본 그대로)."""
    rc, text, raw = applied.first
    assert rc == 0, text
    assert _counts(text) == (6, 2, 2) and _has(raw, "적용 완료")
    before, after, source = env.target_before, applied.rows1, env.source
    for key in _EXPECT_UPDATE:  # (가) 갱신 — data · updated_at 은 파일 값, id 는 대상 줄의 것
        assert after[key]["data"] == source[key]["data"] and after[key]["ts"] == source[key]["ts"], key
        assert after[key]["id"] == before[key]["id"] != source[key]["id"], key
    for key in _EXPECT_KEEP:  # (나) 지킴 — 대상 줄이 한 글자도 안 바뀐다
        assert after[key] == before[key], key
        assert after[key]["data"] != source[key]["data"]
    for key in _EXPECT_NEW:  # (다) 새로 넣음 — id · updated_at 원본 그대로
        assert after[key] == source[key], key
    # 지킨 줄의 키는 목록으로 보인다(개행이 든 키도 JSON 문자열로)
    assert b'"quant:keepme"' in raw and b'"quant:keep\\nnl"' in raw
    assert _has(raw, "대상 DB 쪽이 파일보다 더 최근") and _has(raw, "사이클 이력 전체") and _has(raw, "시계")


@needs_docker_db
def test_roundtrip_special_values_survive(env, applied):
    """TC-DCP-15 (라) · 쉼표 · 따옴표 · 개행 · 한글 · 이모지 · 백슬래시가 든 JSON 과 개행 · 쉼표 · 따옴표가 든 키, 200KB 값이 그대로 돌아온다."""
    after = applied.rows1
    assert after["quant:cycle_log:u1"]["data"] == _SPECIAL
    msg = after["quant:cycle_log:u1"]["data"]["cycles"][0]["msg"]
    assert "\n" in msg and '"' in msg and "\\" in msg and "\t" in msg and "삼성전자" in msg
    assert after["quant:cycle_log:u1"]["data"]["cycles"][0]["emoji"] == "😀🚀"
    assert after['quant:weird,"key"']["data"] == {"k": 'comma, quote" and backslash \\'}
    assert after["quant:line\nbreak"]["data"] == {"nl": True}
    assert len(after["quant:big"]["data"]["blob"]) == 200_000 and len(after["model_compare:v1:big"]["data"]["blob"]) == 200_000
    assert after["model_compare:v1:005930:2y:abc"]["data"]["설명"] == "한글 값"


@needs_docker_db
def test_roundtrip_both_prefixes_restored_and_outside_keys_untouched(env, applied):
    """TC-DCP-15 (마) · quant: · model_compare: 두 접두사 모두 돌아오고, 접두사 밖 키는 상태 파일을 거치지 않아 되살아나지 않으며 대상에 있던 값은 그대로다."""
    after = applied.rows1
    assert any(k.startswith("quant:") for k in after) and any(k.startswith("model_compare:") for k in after)
    assert after["candles:005930:1y:1d"] == env.target_before["candles:005930:1y:1d"]
    assert "ai_predict:v5:005930" not in after and "indicators:AAPL:2y" not in after
    assert set(after) == set(env.target_before) | {k for k, _, _ in _FILE_ROWS}


@needs_docker_db
def test_roundtrip_second_apply_is_idempotent(env, applied):
    """TC-DCP-15 (사) · 같은 파일을 다시 -Apply 해도 표 전체 지문이 그대로다(값 · id · updated_at 불변). 같은 값은 updated_at 도 같아 「갱신」 으로 센다."""
    rc, text, _ = applied.second
    assert rc == 0, text
    assert applied.fp2 == applied.fp1 and applied.rows2 == applied.rows1
    assert _counts(text) == (0, 8, 2)


@needs_docker_db
def test_roundtrip_leaves_no_files_in_the_container_tmp(env, applied):
    """TC-DCP-15 (정리) · 컨테이너 /tmp 에 이 도구가 만든 임시 파일(appdb-*)이 남지 않는다 — 성공 · 실패 모두."""
    p = _docker("exec", _PG, "ls", "/tmp")
    left = [n for n in p.stdout.decode("utf-8", errors="replace").split() if n.startswith("appdb-") or n.startswith("pytest-")]
    assert left == [], left


@needs_docker_db
def test_backup_with_failed_state_export_marks_the_dump_incomplete(docker_env, tmp_path):
    """TC-DCP-16 · 상태 키 내보내기가 실패하면(표가 없음) 덤프는 .dump.incomplete 로 바뀌고, .dump · .state.csv 는 남지 않으며, 실패로 끝나 「백업 완료」 를 찍지 않는다."""
    db = _scratch_name() + "_empty"
    assert re.fullmatch(r"qurious_scratch_[a-z0-9_]{1,40}", db)
    out_dir = tmp_path / "out"
    try:
        _create_scratch(db, clone_schema=False)
        rc, text, raw = _run_ps(_PS_DIR / "backup-appdb.ps1", "-Database", db, "-OutDir", out_dir)
        assert rc == 1, text
        names = sorted(p.name for p in out_dir.iterdir())
        assert len(names) == 1 and re.fullmatch(r"appdb-\d{8}-\d{6}\.dump\.incomplete", names[0]), names
        assert not _has(raw, "백업 완료") and _has(raw, "백업 실패") and _has(raw, ".incomplete")
        left = [n for n in _docker("exec", _PG, "ls", "/tmp").stdout.decode("utf-8", errors="replace").split() if n.startswith("appdb-")]
        assert left == [], "실패했어도 컨테이너 /tmp 임시 파일은 지운다"
    finally:
        _drop_scratch(db)


@needs_docker_db
def test_backup_include_data_cache_makes_no_state_file(docker_env, tmp_path):
    """TC-DCP-17 · -IncludeDataCache 는 표 전체를 덤프에 담고 상태 파일은 만들지 않는다(성공으로 끝난다)."""
    db = _scratch_name() + "_inc"
    out_dir = tmp_path / "out"
    try:
        _create_scratch(db)
        _psql(db, _insert_sql([("quant:x", {"a": 1}, "2026-10-01 00:00:00+00"), ("candles:x", {}, "2026-10-01 00:00:00+00")]))
        rc, text, raw = _run_ps(_PS_DIR / "backup-appdb.ps1", "-Database", db, "-OutDir", out_dir, "-IncludeDataCache")
        assert rc == 0, text
        assert len(list(out_dir.glob("appdb-*.dump"))) == 1 and list(out_dir.glob("*.state.csv")) == []
    finally:
        _drop_scratch(db)
