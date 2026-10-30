"""TC-BS — 코인 봉 저장 · 개인 수집 스크립트 (collector/binance_store.py · scripts/personal_binance.py · 할 일 ①-13 · 2026-10-30)

받기 → 정제 → 적재를 나눈 부품을 합성 zip · 가짜 HF 로 확인한다(네트워크 없음).
1. 월 파일 쓰기(멱등) · 적재 — 잘게(1 ~ 30분)는 해 · 종목 파일, 거친 주기는 종목당 하나, 정렬 · 키 중복 검사 · 달이 없으면 None. (TC-BS-01)
2. 받기 한 건 — 이미 받은 달은 건너뜀 · 없는 달(404)은 `none` · 체크섬이 다르면 막음. (TC-BS-02)
3. 올리기 — 팀 조직에는 거부 · 토큰 없음 · 권한 없음은 건너뜀(에러 아님) · dry-run 은 안 올림 · 100개 안팎씩 커밋. (TC-BS-03)
4. 팀 러너에 연결되지 않았다. (TC-BS-04)
"""
from __future__ import annotations

import io
import sys
import types
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from collector import binance_store as bs  # noqa: E402
from collector import binance_vision as bv  # noqa: E402
import personal_binance as pb  # noqa: E402


def _ms(y, m, d, h=0, mi=0):
    return int(datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)


def _zip(rows):
    lines = [f"{t},100,110,90,105,12.5,{t + 59_999},1300,10,5.5,600,0" for t in rows]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", "\n".join(lines) + "\n")
    return buf.getvalue()


def _v2(interval, times, symbol="BTCUSDT"):
    return bv.to_v2_rows(_zip(times), symbol, interval)["rows"]


def test_month_files_and_partitions(tmp_path):
    """TC-BS-01 · 월 파일(멱등) → 적재(잘게는 해 · 종목 · 거친 주기는 종목당 하나) · 정렬 · 키 중복 · 달 없음."""
    root = tmp_path
    d1, d2 = _ms(2026, 8, 31), _ms(2026, 9, 1)
    bs.write_month(root, "1m", "BTCUSDT", 2026, 9, _v2("1m", [d2 + 60_000, d2]))        # 일부러 뒤집은 순서
    bs.write_month(root, "1m", "BTCUSDT", 2026, 8, _v2("1m", [d1]))
    bs.write_month(root, "1m", "BTCUSDT", 2026, 9, _v2("1m", [d2 + 60_000, d2]))        # 같은 달 다시 — 덮어쓰기라 중복이 안 생긴다
    r = bs.compile_partition(root, root, "1m", "BTCUSDT", 2026)
    assert r["rows"] == 3 and r["first"] == "2026-08-31" and r["last"] == "2026-09-01"
    assert r["path"].as_posix().endswith("ohlcv/timeframe=1m/market=BINANCE_SPOT_USDT/year=2026/symbol=BTCUSDT.parquet")
    import pandas as pd
    df = pd.read_parquet(r["path"])
    assert list(df.columns) == bs.COLUMNS and list(df["bar_start"]) == sorted(df["bar_start"]), "열 차례 · 시간순"
    assert df["trades"].iloc[0] == 10 and df["venue"].iloc[0] == "BINANCE_SPOT_USDT"
    assert bs.compile_partition(root, root, "1m", "ETHUSDT", 2026) is None, "달 파일이 없으면 None"
    with pytest.raises(ValueError, match="해"):
        bs.compile_partition(root, root, "1m", "BTCUSDT")
    # 거친 주기 — 해를 무시하고 모든 달을 종목당 한 파일로
    bs.write_month(root, "1h", "BTCUSDT", 2025, 12, _v2("1h", [_ms(2025, 12, 31, 23)]))
    bs.write_month(root, "1h", "BTCUSDT", 2026, 1, _v2("1h", [_ms(2026, 1, 1)]))
    c = bs.compile_partition(root, root, "1h", "BTCUSDT")
    assert c["rows"] == 2 and c["path"].as_posix().endswith("timeframe=1h/market=BINANCE_SPOT_USDT/symbol=BTCUSDT.parquet")
    # 서로 다른 달 파일이 같은 봉을 가지면 숨기지 않는다
    bs.write_month(root, "5m", "BTCUSDT", 2026, 9, _v2("5m", [d2]))
    bs.write_month(root, "5m", "BTCUSDT", 2026, 8, _v2("5m", [d2]))                      # 8월 파일에 9월 봉이 섞였다
    with pytest.raises(ValueError, match="겹치는"):
        bs.compile_partition(root, root, "5m", "BTCUSDT", 2026)
    # 한 달 파일 안에서 모든 칸이 같은 줄이 두 번 오면(원천 CSV 중복) 한 줄로 줄이고 개수를 알린다
    bs.write_month(root, "15m", "BTCUSDT", 2026, 9, _v2("15m", [d2, d2, d2 + 900_000]))
    dd = bs.compile_partition(root, root, "15m", "BTCUSDT", 2026)
    assert dd["rows"] == 2 and dd["dropped_exact_dups"] == 1 and r["dropped_exact_dups"] == 0
    with pytest.raises(ValueError, match="쓸 줄이 없다"):
        bs.write_month(root, "1m", "BTCUSDT", 2026, 10, [])
    s = bs.summarize(root)
    assert s["1m"]["files"] == 1 and s["1h"]["files"] == 1 and s["1m"]["bytes"] > 0


def test_fetch_one_skips_existing_handles_missing_and_verifies_checksum(tmp_path, monkeypatch):
    """TC-BS-02 · 이미 받은 달은 건너뜀 · 404 는 none · 체크섬이 다르면 막음 · 값 규칙 위반 줄은 보관."""
    data = _zip([_ms(2026, 9, 1)])
    good = bv.sha256_hex(data)
    calls = []

    def fake(url, timeout=60):
        calls.append(url)
        if url.endswith(".CHECKSUM"):
            return f"{good}  x.zip\n".encode()
        return data
    monkeypatch.setattr(pb, "_http", fake)
    monkeypatch.setattr(pb, "DELAY_S", 0)
    assert pb.fetch_one(tmp_path, "BTCUSDT", "1d", 2026, 9) == "ok" and len(calls) == 2
    assert pb.fetch_one(tmp_path, "BTCUSDT", "1d", 2026, 9) == "skip" and len(calls) == 2, "받은 달은 다시 안 부른다"
    assert pb.fetch_one(tmp_path, "BTCUSDT", "1d", 2026, 9, force=True) == "ok" and len(calls) == 4
    monkeypatch.setattr(pb, "_http", lambda url, timeout=60: None)
    assert pb.fetch_one(tmp_path, "NEWUSDT", "1d", 2026, 9) == "none", "상장 전 달(404)은 오류가 아니다"
    monkeypatch.setattr(pb, "_http", lambda url, timeout=60: (f"{'0' * 64}  x\n".encode() if url.endswith(".CHECKSUM") else data))
    with pytest.raises(ValueError, match="지문이 체크섬과 다르다"):
        pb.fetch_one(tmp_path, "ETHUSDT", "1d", 2026, 9)


class _Api:
    def __init__(self, ok=True, boom=None):
        self.commits, self._ok, self._boom = [], ok, boom

    def whoami(self):
        perms = ["repo.write"] if self._ok else ["repo.content.read"]
        return {"orgs": [{"name": "Finance-Data", "roleInOrg": "admin"}],
                "auth": {"accessToken": {"fineGrained": {"scoped": [{"entity": {"name": "Finance-Data"}, "permissions": perms}]}}}}

    def create_commit(self, **kw):
        if self._boom:
            raise self._boom
        self.commits.append(kw)


def _fake_hub(monkeypatch, api):
    mod = types.ModuleType("huggingface_hub")
    mod.HfApi = lambda token=None: api
    mod.CommitOperationAdd = lambda path_in_repo, path_or_fileobj: (path_in_repo, path_or_fileobj)
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)


def _args(root, repo="Finance-Data/binance-spot-ohlcv", dry=False):
    return types.SimpleNamespace(root=str(root), repo=repo, dry_run=dry)


def test_upload_is_personal_only_and_skips_without_error(tmp_path, monkeypatch, capsys):
    """TC-BS-03 · 팀 조직 거부 · 토큰 없음 · 권한 없음 · 접근 불가는 건너뜀 · dry-run 은 안 올림 · 90개씩 커밋."""
    for i in range(200):
        f = tmp_path / "ohlcv" / "timeframe=1d" / "market=M" / f"symbol=S{i}.parquet"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    assert pb.cmd_upload(_args(tmp_path, repo="qurious-quant/crypto-ohlcv")) == 2, "팀 조직에는 대용량 개인 자료를 올리지 않는다"
    monkeypatch.setattr(pb.hf_orgs, "personal_token", lambda: None)
    assert pb.cmd_upload(_args(tmp_path)) == 0 and "토큰이 없다" in capsys.readouterr().out
    monkeypatch.setattr(pb.hf_orgs, "personal_token", lambda: "t")
    api = _Api(ok=False)
    _fake_hub(monkeypatch, api)
    assert pb.cmd_upload(_args(tmp_path)) == 0 and api.commits == [] and "repo.write 가 없다" in capsys.readouterr().out
    api = _Api()
    _fake_hub(monkeypatch, api)
    assert pb.cmd_upload(_args(tmp_path, dry=True)) == 0 and api.commits == [] and "dry-run" in capsys.readouterr().out
    assert pb.cmd_upload(_args(tmp_path)) == 0
    assert [len(c["operations"]) for c in api.commits] == [90, 90, 20], "한 커밋 100개 미만"
    assert api.commits[0]["repo_type"] == "dataset" and api.commits[0]["operations"][0][0].startswith("ohlcv/timeframe=1d/")

    class RepositoryNotFoundError(Exception):
        pass
    api = _Api(boom=RepositoryNotFoundError("404"))
    _fake_hub(monkeypatch, api)
    assert pb.cmd_upload(_args(tmp_path)) == 0 and "접근 불가" in capsys.readouterr().out


def test_personal_script_is_not_wired_into_the_team_runner():
    """TC-BS-04 · 팀 러너 · 앱이 개인 수집 부품을 부르지 않는다(기존 팀 로직 유지)."""
    for rel in ("scripts/daily_update.py", "scripts/hf_dataset.py", "scripts/hf_sync.py", "app/main.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "personal_binance" not in src and "binance_store" not in src and "binance_vision" not in src, rel
