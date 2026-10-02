"""HF 백업(krx-daily-market) 표 목록 시험 (TC-HF) — 결함 DF-40 · `scripts/hf_dataset.py`.

무엇이 틀렸었나 —
2026-10-01 에 만든 OHLCV 원자료 표 넷(etf_daily · index_daily · price_intraday · intraday_universe)이 백업 목록
(`TABLES`)에도 제외 목록(`EXCLUDED`)에도 없었다. `krx-ohlcv` 는 규격 자료만 올려 ETF 순자산가치 · 기초지수 같은
칸은 어디에도 백업되지 않았고, 5분봉은 야후가 60일 지난 것을 다시 주지 않아 우리 PC 에만 남아 있었다.
넷을 백업에 넣으려 보니 함정이 하나 더 있었다 — 연도 파일의 경계가 `{y}0000`~`{y}9999` 라 `YYYY-MM-DD` 모양의
분봉 날짜는 `'2026-10-02' < '20260000'` 이 되어 **그해 행이 0행으로 잘렸다.**

여기서 지키는 것 —
1. 수집기가 만드는 표는 전부 백업하거나, 제외하면 이유를 적는다(조용히 빠지는 표가 없다).
2. 데이터 파트 결정대로 OHLCV 원자료 표 넷은 백업 대상이다.
3. 연도 경계는 날짜 모양(YYYYMMDD · YYYY-MM-DD)을 가리지 않고, 옛 표의 결과는 그대로다.
4. 넷을 내보내고 그 파케이만으로 되살리면 행 · 값이 그대로다(내용 지문 대조까지).
5. 검증의 값 게이트가 int64 를 넘는 정수 합(지수 상장 시가총액 9.87e19)에서 죽지 않는다(DF-41 — 넷을 처음
   검증하다 찾았다. 파케이 쪽 합은 조용히 음수로 감기고 있었다).
6. 일부 표만 본 검증 · 복원 기록은 「지워도 된다」 판정을 초록으로 만들지 않는다(DF-42 — 같은 날 넷만 검증하며 찾았다).

네트워크 · 실제 수집 DB 를 쓰지 않는다 — 임시 폴더에 작은 DB 를 만든다.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from collector import db as collector_db
from scripts import hf_dataset

OHLCV_TABLES = ("etf_daily", "index_daily", "price_intraday", "intraday_universe")


def _collector_tables(path: Path) -> set[str]:
    conn = collector_db.connect(path)
    try:
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    finally:
        conn.close()


def test_every_collector_table_is_backed_up_or_excluded(tmp_path):
    """TC-HF-01 · 수집기 SCHEMA 의 표는 전부 TABLES 나 EXCLUDED(이유 있음) 에 있다 — 둘 다에 있는 표는 없다."""
    names = _collector_tables(tmp_path / "m.sqlite3")
    assert names, "수집기 SCHEMA 가 표를 만들지 않았다"
    unmapped = names - set(hf_dataset.TABLES) - set(hf_dataset.EXCLUDED)
    assert not unmapped, f"백업에서 조용히 빠지는 표: {sorted(unmapped)}"
    assert not set(hf_dataset.TABLES) & set(hf_dataset.EXCLUDED)
    assert all(reason.strip() for reason in hf_dataset.EXCLUDED.values())


def test_ohlcv_raw_tables_are_backup_targets():
    """TC-HF-02 · OHLCV 원자료 표 넷은 백업 대상이고 빠뜨려도 되는 표(optional)가 아니다 — 분봉은 큰 표(heavy)."""
    for name in OHLCV_TABLES:
        spec = hf_dataset.TABLES[name]
        assert spec["optional"] is False, name
        assert spec["why"], name
        assert not spec.get("raw"), f"{name} 은 응답 원문이 아니다 — 공유 스위치 대상이 아니다"
    assert hf_dataset.TABLES["price_intraday"]["date_col"] == "trade_date"
    assert hf_dataset.TABLES["price_intraday"].get("heavy") is True


def _year_db(values: list[str]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (d TEXT NOT NULL, v INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?, ?)", [(d, i) for i, d in enumerate(values)])
    return conn


def _per_year(conn: sqlite3.Connection) -> dict[str, int]:
    spec = {"partition": "year", "date_col": "d"}
    return {y: hf_dataset._count(conn, "t", spec, y) for y in hf_dataset._partitions(conn, "t", spec)}


def test_year_partition_counts_iso_dates():
    """TC-HF-03 · `YYYY-MM-DD` 날짜도 그해 파일에 든다 — 옛 경계(`20260000`~`20269999`)로는 2026 년이 0행이었다."""
    conn = _year_db(["2023-09-27", "2025-12-31", "2026-01-01", "2026-10-02"])
    assert _per_year(conn) == {"2023": 1, "2025": 1, "2026": 2}
    # 옛 경계가 왜 틀렸나 — '-'(0x2D)가 '0'(0x30)보다 작다
    old = conn.execute("SELECT COUNT(*) FROM t WHERE d >= '20260000' AND d <= '20269999'").fetchone()[0]
    assert old == 0


def test_year_partition_unchanged_for_yyyymmdd():
    """TC-HF-04 · `YYYYMMDD` 표는 새 경계와 옛 경계의 결과가 같다(이미 올린 파일이 다시 바뀌지 않는다)."""
    vals = ["20200102", "20251230", "20251231", "20260101", "20261231", "20270101"]
    conn = _year_db(vals)
    got = _per_year(conn)
    for y, n in got.items():
        old = conn.execute("SELECT COUNT(*) FROM t WHERE d >= ? AND d <= ?",
                           (f"{y}0000", f"{y}9999")).fetchone()[0]
        assert n == old, y
    assert got == {"2020": 1, "2025": 2, "2026": 2, "2027": 1}


def _fill(path: Path) -> dict[str, int]:
    """수집기 SCHEMA 로 만든 DB 에 넷을 조금씩 — 해를 넘는 행 · 빈 칸(NULL) · 영문 섞인 단축코드를 섞는다."""
    conn = collector_db.connect(path)
    conn.executemany(
        "INSERT INTO etf_daily (bas_dt, srtn_cd, isin_cd, itms_nm, clpr, vs, flt_rt, nav, mkp, hipr, lopr, trqu, "
        "tr_prc, mrkt_tot_amt, st_lstg_cnt, bss_idx_nm, bss_idx_clpr, npt_tot_amt, halted, raw_sha256) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [("20251230", "069500", "KR7069500007", "KODEX 200", 51000, 300, 0.59, 51012.3, 50800, 51200, 50700,
          1_000_000, 51_000_000_000, 7_000_000_000_000, 137_000_000, "코스피 200", 401.2, 7_010_000_000_000, 0, "a" * 64),
         ("20260102", "0000D0", "KR70000D0003", "새 ETF", 10000, None, None, None, 0, 0, 0,
          0, 0, None, None, "", None, None, 1, "")])
    conn.executemany(
        "INSERT INTO index_daily (bas_dt, idx_csf, idx_nm, epy_itms_cnt, clpr, vs, flt_rt, mkp, hipr, lopr, trqu, "
        "tr_prc, lstg_mrkt_tot_amt, bas_pntm, bas_idx, raw_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [("20260102", "KOSPI시리즈", "IT 서비스", 40, 1234.5, 1.5, 0.12, 1230.0, 1240.0, 1229.0, 10, 20, 30,
          "19800104", 100.0, "b" * 64),
         ("20260102", "KRX시리즈", "IT 서비스", 20, 987.6, -2.0, -0.2, 990.0, 991.0, 985.0, 5, 6, 7, "", None, "")])
    conn.executemany(
        "INSERT INTO price_intraday (symbol, timeframe, bar_start, trade_date, open, high, low, close, volume, "
        "session, source, price_basis, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [("005930", "60m", "2025-12-30T14:00:00+09:00", "2025-12-30", 100.0, 101.0, 99.0, 100.5, 10,
          "regular", "yahoo", "adj_split", "2026-10-01T12:00:00+09:00"),
         ("005930", "60m", "2026-10-02T09:00:00+09:00", "2026-10-02", 200.0, 201.0, 199.0, 200.5, 20,
          "regular", "yahoo", "adj_split", "2026-10-02T12:40:00+09:00"),
         ("005930", "5m", "2026-10-02T09:05:00+09:00", "2026-10-02", 200.0, 200.5, 199.5, 200.0, 3,
          "regular", "yahoo", "adj_split", "2026-10-02T12:40:00+09:00")])
    conn.executemany(
        "INSERT INTO intraday_universe (version, symbol, itms_nm, market, reason, rank) VALUES (?,?,?,?,?,?)",
        [("u1-20260930", "005930", "삼성전자", "KOSPI", "KOSPI 시가총액 1위", 1),
         ("u2-20260930", "0220W0", "분할 신설", "KOSPI", "코스피 200 구성종목(임시 편입)", None)])
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in OHLCV_TABLES}
    conn.close()
    return counts


def _rows(path: Path, table: str) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3").fetchall()
    finally:
        conn.close()


def test_export_then_restore_round_trip(tmp_path, monkeypatch):
    """TC-HF-05 · 넷을 내보내고 그 파케이만으로 되살리면 행 · 값 · 인덱스가 그대로다(복원의 내용 지문 대조 포함)."""
    src = tmp_path / "market.sqlite3"
    counts = _fill(src)
    out = tmp_path / "hf_export"
    monkeypatch.setattr(hf_dataset.config, "DB_PATH", src)
    monkeypatch.setattr(hf_dataset, "EXPORT_DIR", out)
    monkeypatch.setattr(hf_dataset, "MANIFEST_PATH", out / "meta" / "manifest.json")
    monkeypatch.setattr(hf_dataset, "README_PATH", out / "README.md")
    monkeypatch.setattr(hf_dataset, "RESTORE_LOG_PATH", out / "meta" / "last_restore.json")

    tally = hf_dataset.export(tables=list(OHLCV_TABLES), verbose=False)
    man = hf_dataset._load_manifest()
    assert not man["partial"]
    assert {t: man["tables"][t]["rows"] for t in OHLCV_TABLES} == counts
    # 분봉은 해마다 한 파일 — 2025 · 2026 둘(옛 경계였다면 0행 파일 둘이었다)
    paths = sorted(f["path"] for f in man["tables"]["price_intraday"]["files"])
    assert paths == ["price_intraday/year=2025/part-00000.parquet", "price_intraday/year=2026/part-00000.parquet"]
    assert [f["rows"] for f in sorted(man["tables"]["price_intraday"]["files"], key=lambda f: f["path"])] == [1, 2]
    assert tally["total_rows"] == sum(counts.values())
    # 데이터 카드에 새 출처가 적힌다
    card = (out / "README.md").read_text(encoding="utf-8")
    assert "야후 파이낸스" in card and "증권상품시세정보" in card

    into = tmp_path / "restored.sqlite3"
    assert hf_dataset.restore(into=str(into), verbose=False) == 0
    for t in OHLCV_TABLES:
        assert _rows(into, t) == _rows(src, t), t
    conn = sqlite3.connect(into)
    idx = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")}
    conn.close()
    assert {"ix_etf_srtn", "ix_index_nm", "ix_intraday_day"} <= idx


def test_value_gate_survives_int64_overflowing_sums(tmp_path, monkeypatch):
    """TC-HF-06 · 값 게이트가 int64 를 넘는 정수 합에서 죽지도 · 감기지도 않는다(DF-41).

    지수 일봉의 상장 시가총액 합이 9.87e19(상한의 10.7 배)라 SQLite `SUM()` 이 `integer overflow` 로 죽었다.
    파케이 쪽 `pc.sum` 은 같은 합을 조용히 음수로 감아, 고치지 않았다면 「값이 뭉개졌다」 는 거짓 실패가 났다.
    """
    import pyarrow.parquet as pq

    src = tmp_path / "big.sqlite3"
    conn = sqlite3.connect(src)
    conn.execute("CREATE TABLE big (d TEXT NOT NULL, amt INTEGER, px REAL)")
    big = 7_740_000_000_000_000                      # 한 행 최대 7.74e15 — 실제 지수 일봉 값
    conn.executemany("INSERT INTO big VALUES (?, ?, ?)",
                     [(f"2026{m:02d}01", big, 1.5) for m in range(1, 13)] * 200)   # 합 1.86e19 > 9.22e18
    conn.execute("INSERT INTO big VALUES ('20261002', NULL, NULL)")
    conn.commit()
    with pytest.raises(sqlite3.OperationalError, match="integer overflow"):
        conn.execute("SELECT SUM(amt) FROM big").fetchone()       # 옛 게이트가 죽던 자리

    out = tmp_path / "hf_export"
    monkeypatch.setattr(hf_dataset, "EXPORT_DIR", out)
    spec = {"partition": None, "date_col": "d", "sort": ("d",), "why": "시험"}
    path = out / "big" / "big.parquet"
    info = hf_dataset._write_partition(conn, "big", spec, None, path, verbose=False)
    rec = {"files": [info], "rows": info["rows"]}
    assert hf_dataset._gate_values(conn, "big", rec, pq) is True
    conn.close()


def test_partial_verify_or_restore_is_not_a_deletion_green(tmp_path, monkeypatch):
    """TC-HF-07 · 표 몇 개만 본 `verify --tables` · `restore --tables` 기록은 「지워도 된다」 판정 ④ ⑤ 를 초록으로 만들지 않는다(DF-42).

    2026-10-02 에 새 표 넷만 검증했더니 그 기록(`full: false`)이 매니페스트 지문과 맞아 ④ 가 통과로 읽힐 수 있었다.
    """
    meta = tmp_path / "meta"
    monkeypatch.setattr(hf_dataset, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(hf_dataset, "VERIFY_LOG_PATH", meta / "last_verify.json")
    monkeypatch.setattr(hf_dataset, "RESTORE_LOG_PATH", meta / "last_restore.json")
    man = {"tables": {"price_daily": {"rows": 1, "files": [{"path": "p.parquet", "sha256": "x"}]},
                      "etf_daily": {"rows": 1, "files": [{"path": "e.parquet", "sha256": "y"}]}}}
    fp = hf_dataset._manifest_fp(man)

    def verdict(verify_log: dict, restore_log: dict) -> tuple:
        hf_dataset._write_json_atomic(meta / "last_verify.json", {"manifest_fp": fp, **verify_log})
        hf_dataset._write_json_atomic(meta / "last_restore.json", {"manifest_fp": fp, **restore_log})
        out = hf_dataset._deletion_verdict(man, {"price_daily": 1, "etf_daily": 1}, None)
        by = {label: ok for ok, label, _why in out}
        return (by["verify --deep 이 통과했다 (지문·행수·스키마·값)"], by["복구 리허설이 성공했다 (파케이 → SQLite)"])

    part = verdict({"deep": True, "fails": 0, "db_present": True, "full": False, "tables": ["etf_daily"]},
                   {"ok": True, "tables": ["etf_daily"]})
    assert part == (None, None)
    full = verdict({"deep": True, "fails": 0, "db_present": True, "full": True, "tables": ["price_daily", "etf_daily"]},
                   {"ok": True, "tables": ["price_daily", "etf_daily"]})
    assert full == (True, True)
