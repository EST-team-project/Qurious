"""실제 격리 PostgreSQL의 임시 정책 복구. 주문 전송은 합성, 종료 감시는 별도 프로세스."""
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func

from app.models import BrokerSettings, LiveOrder
from scripts import kis_recovery_trial as trial
from test_kis_connection_probe import runtime  # noqa: F401
from test_kis_order_recovery import env, setup  # noqa: F401

pytestmark = [pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="격리 PostgreSQL 필요"),
              pytest.mark.usefixtures("rebalance_db_schema")]


async def seed(sessions):
    uid, parent_id = await setup(sessions, risk_cooldown_min=30)
    async with sessions() as db:
        parent = await db.get(LiveOrder, parent_id)
        parent.strategy_id = "manual_broker"
        parent.quantity = 1
        parent.filled_quantity = 0
        parent.created_at = trial.recovery.datetime.now(trial.recovery.control.KST) - timedelta(minutes=31)
        await db.commit()
    return uid, parent_id


@pytest.fixture
def sessions(env, monkeypatch):
    sessions, _, _ = env
    monkeypatch.setattr(trial.pg, "get_session_factory", lambda: sessions)
    return sessions


def test_dry_run_does_not_mutate_or_create_journal(sessions, tmp_path):
    async def scenario():
        uid, parent_id = await seed(sessions)
        result = await trial.run(uid, parent_id, tmp_path)
        assert result["status"] == "DRY_RUN"
        assert not list(tmp_path.iterdir())
        async with sessions() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            assert row.quant_execution_policy == {}
            assert await db.scalar(select(func.count()).select_from(LiveOrder).where(LiveOrder.retry_of == parent_id)) == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["yesterday", "too_early", "too_late", "filled", "wrong_strategy", "two_shares",
                                  "auto", "kill", "retry_auto", "cooldown", "window", "deviation", "attempts"])
def test_ineligible_trial_never_changes_settings(sessions, case):
    async def scenario():
        uid, parent_id = await seed(sessions)
        async with sessions() as db:
            parent = await db.get(LiveOrder, parent_id)
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            if case == "yesterday": parent.created_at -= timedelta(days=1)
            if case == "too_early": parent.created_at += timedelta(minutes=2)
            if case == "too_late": parent.created_at -= timedelta(minutes=12)
            if case == "filled": parent.filled_quantity = 1
            if case == "wrong_strategy": parent.strategy_id = "kis_connection_check"
            if case == "two_shares": parent.quantity = 2
            if case == "auto": row.quant_auto_enabled = True
            if case == "kill": row.risk_kill_switch = True
            if case == "retry_auto": row.quant_execution_policy = {"retry_enabled": True}
            if case == "cooldown": row.risk_cooldown_min = 0
            if case == "window": row.quant_execution_policy = {"retry_window_min": 45}
            if case == "deviation": row.quant_execution_policy = {"retry_price_deviation_pct": 2}
            if case == "attempts": row.quant_execution_policy = {"retry_max_attempts": 2}
            before = dict(row.quant_execution_policy)
            await db.commit()
        with pytest.raises(ValueError): await trial.inspect(uid, parent_id)
        async with sessions() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            assert row.quant_execution_policy == before
    asyncio.run(scenario())


@pytest.mark.parametrize("stored_window", [False, True])
def test_recovery_after_commit_and_preserve_later_user_settings(sessions, tmp_path, stored_window):
    async def scenario():
        uid, parent_id = await seed(sessions)
        if stored_window:
            async with sessions() as db:
                row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
                row.quant_execution_policy = {"retry_window_min": 15}
                await db.commit()
        record = await trial.inspect(uid, parent_id)
        path = tmp_path / "attempt.json"
        trial.write(path, record, exclusive=True)
        await trial.activate(record)
        # 설정 변경 커밋 직후 실행기가 종료된 상태. 별도 세션에서 새 사용자 변경도 발생.
        async with sessions() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            row.risk_kill_switch = True
            row.quant_execution_policy = {**row.quant_execution_policy, "risk_pct": 2}
            await db.commit()
        assert (await trial.restore(path))["policy_restored"]
        assert (await trial.restore(path))["duplicate"]
        async with sessions() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            assert row.quant_execution_policy == {**record["original_policy"], "risk_pct": 2}
            assert row.risk_kill_switch and not row.quant_auto_enabled and row.risk_cooldown_min == 30
        assert path.stat().st_mode & 0o777 == 0o600
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["policy", "account"])
def test_changed_window_or_account_needs_review_without_overwrite(sessions, tmp_path, change):
    async def scenario():
        uid, parent_id = await seed(sessions)
        record = await trial.inspect(uid, parent_id)
        path = tmp_path / "attempt.json"
        trial.write(path, record, exclusive=True)
        await trial.activate(record)
        async with sessions() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            if change == "policy": row.quant_execution_policy = {"retry_window_min": 20}
            else: row.account_no = "9999999901"
            await db.commit()
        with pytest.raises(ValueError): await trial.restore(path)
        assert json.loads(path.read_text())["status"] == "prepared"
    asyncio.run(scenario())


def test_changed_settings_before_commit_and_prepare_only_crash(sessions, tmp_path):
    async def scenario():
        uid, parent_id = await seed(sessions)
        record = await trial.inspect(uid, parent_id)
        path = tmp_path / "attempt.json"
        trial.write(path, record, exclusive=True)
        async with sessions() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            row.quant_execution_policy = {"risk_pct": 2}
            await db.commit()
        with pytest.raises(ValueError): await trial.activate(record)
        assert (await trial.restore(path))["status"] == "unchanged"
        async with sessions() as db:
            assert (await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))).quant_execution_policy == {"risk_pct": 2}
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", [False, True])
def test_retry_result_and_exception_always_restore(sessions, tmp_path, monkeypatch, failure):
    async def scenario():
        uid, parent_id = await seed(sessions)
        async def retry(*args):
            async with sessions() as db:
                row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
                assert row.quant_execution_policy == {"retry_window_min": 45}
            if failure: raise RuntimeError("synthetic lookup loss")
            return {"status": "skipped", "code": "PRICE_DEVIATION"}
        def spawn(command, **kwargs):
            Path(command[-1]).with_suffix(".ready").touch()
            return SimpleNamespace(poll=lambda: None)
        monkeypatch.setattr(trial.subprocess, "Popen", spawn)
        monkeypatch.setattr(trial.recovery, "retry", AsyncMock(side_effect=retry))
        if failure:
            with pytest.raises(RuntimeError): await trial.run(uid, parent_id, tmp_path, execute=True)
        else:
            assert (await trial.run(uid, parent_id, tmp_path, execute=True))["code"] == "PRICE_DEVIATION"
        assert trial.recovery.retry.await_count == 1
        async with sessions() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            assert row.quant_execution_policy == {}
        with pytest.raises(FileExistsError): await trial.run(uid, parent_id, tmp_path, execute=True)
        assert trial.recovery.retry.await_count == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("kill_owner", [False, True])
def test_independent_watchdog_observes_deadline_and_sigkill(tmp_path, kill_owner):
    owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    journal = tmp_path / "attempt.json"
    marker = tmp_path / "restore_called"
    trial.write(journal, {"status": "prepared", "owner_pid": owner.pid,
                         "deadline": time.time() + (60 if kill_owner else 1)}, exclusive=True)
    command = [sys.executable, "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).touch()", str(marker)]
    code = "from scripts.kis_recovery_trial import watch; import json,sys; watch(sys.argv[1],json.loads(sys.argv[2]))"
    watcher = subprocess.Popen([sys.executable, "-c", code, str(journal), json.dumps(command)],
                               cwd=Path(__file__).resolve().parents[1])
    try:
        if kill_owner:
            owner.kill()
            owner.wait(timeout=5)
        assert watcher.wait(timeout=15) == 0
        assert marker.exists() and not journal.with_suffix(".ready").exists()
    finally:
        for process in (owner, watcher):
            if process.poll() is None: process.kill()
            process.wait(timeout=5)


def test_sigkill_guard_restores_real_test_database_from_separate_process(sessions, tmp_path):
    owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    path = tmp_path / "attempt.json"
    async def prepare():
        uid, parent_id = await seed(sessions)
        record = await trial.inspect(uid, parent_id)
        record["owner_pid"] = owner.pid
        trial.write(path, record, exclusive=True)
        await trial.activate(record)
        return uid
    uid = asyncio.run(prepare())
    trial_env = {**os.environ, "DATABASE_URL": os.environ["QURIOUS_TEST_DATABASE_URL"],
                 "QURIOUS_ALLOW_LIVE_TRADING": "0", "STOCK_COIN_TRADE_BASE_URL": "",
                 "STOCK_COIN_TRADE_API_KEY": ""}
    watcher = subprocess.Popen([sys.executable, trial.__file__, "watch", "--journal", str(path)],
                               env=trial_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        owner.kill()
        owner.wait(timeout=5)
        assert watcher.wait(timeout=20) == 0
        assert json.loads(path.read_text())["status"] == "restored"
        async def verify():
            async with sessions() as db:
                row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
                assert row.quant_execution_policy == {} and row.risk_cooldown_min == 30
                assert not row.quant_auto_enabled
        asyncio.run(verify())
    finally:
        for process in (owner, watcher):
            if process.poll() is None: process.kill()
            process.wait(timeout=5)


def test_journal_fsync_failure_never_changes_policy_or_sends(sessions, tmp_path, monkeypatch):
    async def scenario():
        uid, parent_id = await seed(sessions)
        def no_space(*args):
            raise OSError("synthetic disk full")
        send = AsyncMock()
        monkeypatch.setattr(trial.os, "fsync", no_space)
        monkeypatch.setattr(trial.recovery, "retry", send)
        with pytest.raises(OSError): await trial.run(uid, parent_id, tmp_path, execute=True)
        send.assert_not_awaited()
        async with sessions() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            assert row.quant_execution_policy == {} and not row.quant_auto_enabled
    asyncio.run(scenario())


def test_restore_receipt_write_failure_blocks_new_trial_until_reconciled(sessions, tmp_path, monkeypatch):
    async def scenario():
        uid, parent_id = await seed(sessions)
        record = await trial.inspect(uid, parent_id)
        path = tmp_path / f"{uid}-{parent_id}.json"
        trial.write(path, record, exclusive=True)
        await trial.activate(record)
        original_write = trial.write
        def no_space(*args, **kwargs):
            raise OSError("synthetic receipt failure after DB restoration")
        monkeypatch.setattr(trial, "write", no_space)
        with pytest.raises(OSError): await trial.restore(path)
        async with sessions() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            assert row.quant_execution_policy == {}
        assert json.loads(path.read_text())["status"] == "prepared"
        with pytest.raises(ValueError, match="미원복"):
            await trial.run(uid, parent_id, tmp_path, execute=True)
        monkeypatch.setattr(trial, "write", original_write)
        assert (await trial.restore(path))["status"] == "unchanged"
        assert (await trial.restore(path))["duplicate"]
    asyncio.run(scenario())
