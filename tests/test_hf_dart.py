"""HF 보관본 시험 (TC-HD) — `scripts/hf_dart.py`(공시 · 재무 · 정책 회의) · `scripts/hf_sector_laws.py`(섹터별 · 연도별 법령).

여기서 지키는 것 —
1. 기준일 거름 — 공시는 접수일, 재무는 known_at 이 기준일 뒤인 행을 담지 않고, 연도 파일로 나눈다(정책 회의는 거르지 않는다).
2. 같은 내용이면 같은 바이트 — 다시 내보내도 파일 sha256 이 같다(닫힌 해 파일이 바뀌지 않는다 · 올리기가 0바이트로 끝난다).
3. 카드의 칸 표는 DDL 주석에서 만들고, 주석 없는 칸은 보충 뜻을 쓴다.
4. 섹터 법령 — 섹터 폴더마다 해마다 파일 하나 · 시행령은 decree=Y 인 법률의 섹터에 · 이번에 쓴 것이 0 이면 옛 파일을 지우지 않는다.

네트워크 · 실제 수집 DB 를 쓰지 않는다 — 임시 폴더에 작은 DB 를 만든다.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest

from collector import config, db as collector_db, kb_sector
from scripts import hf_dart, hf_sector_laws


@pytest.fixture()
def dart_env(tmp_path, monkeypatch):
    path = tmp_path / "market.sqlite3"
    c = collector_db.connect(path)
    rows = [("20251230000001", "20251230"), ("20260102000002", "20260102"), ("20261005000003", "20261005")]
    for rno, dt in rows:
        c.execute("INSERT INTO disclosure (rcept_no, rcept_dt, corp_code, report_nm, fetched_at, updated_at) "
                  "VALUES (?, ?, '00000001', '보고서', 'x', 'x')", (rno, dt))
    for rno, known in (("20250314000001", "20250314"), ("20261005000009", "20261005")):
        c.execute("INSERT INTO financial_statement (corp_code, bsns_year, reprt_code, fs_div, sj_div, ord, account_nm, "
                  "rcept_no, known_at, fetched_at, thstrm_amount) VALUES ('00000001', '2024', '11011', 'CFS', 'BS', 1, "
                  "'자산총계', ?, ?, 'x', 100)", (rno, known))
    c.execute("INSERT INTO policy_meeting VALUES ('bok', '2026-11-26', '금통위', '', 'u', 'x')")
    c.close()
    out = tmp_path / "hf_dart"
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(hf_dart, "OUT_DIR", out)
    monkeypatch.setattr(hf_dart, "META_DIR", out / "meta")
    monkeypatch.setattr(hf_dart, "MANIFEST_PATH", out / "meta" / "manifest.json")
    return out


def test_dart_export_filters_by_as_of_and_splits_years(dart_env):
    """TC-HD-01 · 기준일 거름 · 연도 파일 · 정책 회의는 거르지 않음 · 거른 행 수를 매니페스트에."""
    assert hf_dart.export("2026-10-04") == 0
    man = json.loads((dart_env / "meta" / "manifest.json").read_text(encoding="utf-8"))
    d = man["tables"]["disclosure"]
    assert [f["path"] for f in d["files"]] == ["disclosure/rcept_2025.parquet", "disclosure/rcept_2026.parquet"]
    assert (d["rows"], d["excluded_rows"]) == (2, 1)                      # 10-05 접수는 기준일 뒤
    f = man["tables"]["financial_statement"]
    assert (f["rows"], f["excluded_rows"]) == (1, 1) and f["files"][0]["path"] == "financial_statement/known_2025.parquet"
    assert man["tables"]["policy_meeting"]["rows"] == 1
    assert man["as_of"] == "2026-10-04" and man["code"]["commit"] is not None


def test_dart_export_same_content_same_bytes(dart_env):
    """TC-HD-02 · 다시 내보내도 파일 sha256 이 같다(닫힌 해 파일이 바뀌지 않는다)."""
    hf_dart.export("2026-10-04")
    first = {f["path"]: f["sha256"] for t in json.loads((dart_env / "meta" / "manifest.json").read_text(encoding="utf-8"))
             ["tables"].values() for f in t["files"]}
    hf_dart.export("2026-10-04")
    second = {f["path"]: f["sha256"] for t in json.loads((dart_env / "meta" / "manifest.json").read_text(encoding="utf-8"))
              ["tables"].values() for f in t["files"]}
    assert first == second


def test_dart_card_columns_from_ddl_with_fallback(dart_env):
    """TC-HD-03 · 카드의 칸 표는 DDL 주석에서 · 주석 없는 칸(corp_code)은 보충 뜻 · private 까닭 · pit 절이 있다."""
    hf_dart.export("2026-10-04")
    card = (dart_env / "README.md").read_text(encoding="utf-8")
    assert "| `corp_code` | TEXT | DART 고유번호 8자리 |" in card
    assert "| `known_at` | TEXT | YYYYMMDD — 접수번호 앞 8자리 |" in card
    assert "private 인 까닭" in card and "strict(권장)" in card and "dart-2026-10-04" in card


def test_sector_laws_export_folders_years_and_decrees(tmp_path, monkeypatch):
    """TC-HD-04 · 섹터 폴더 · 해마다 파일 · 시행령은 decree=Y 섹터에만 · 쓴 것이 0 이면 옛 파일을 지우지 않는다."""
    m = tmp_path / "map.tsv"
    m.write_text("sector_code\tsector\ttitle\trole\tdecree\twhy\n"
                 "He\t헬스케어\t약사법\t업법\tY\t제약\n"
                 "All\t공통\t상법\t관련\tN\t회사\n", encoding="utf-8")
    dbp = tmp_path / "s.sqlite3"
    c = kb_sector.connect(dbp)
    for title, year, n in (("약사법", 2025, 2), ("약사법 시행령", 2025, 1), ("상법", 2025, 1), ("약사법", 2026, 2)):
        c.execute("INSERT INTO ks_choice(title, year, as_of, source_id, effective_at, chosen_at) VALUES (?,?,?,?,?, 'x')",
                  (title, year, f"{year}-12-31", "1", f"{year}-01-01"))
        for i in range(n):
            c.execute("INSERT INTO ks_article(title, year, seq, label, text) VALUES (?,?,?,?,?)",
                      (title, year, i, f"제{i + 1}조", f"{title} {year} 글 {i}"))
    c.close()
    out = tmp_path / "hf_sector"
    monkeypatch.setattr(kb_sector, "MAP_PATH", m)
    monkeypatch.setattr(kb_sector, "DB_PATH", dbp)
    for name, val in (("OUT_DIR", out), ("META_DIR", out / "meta"), ("MANIFEST_PATH", out / "meta" / "manifest.json")):
        monkeypatch.setattr(hf_sector_laws, name, val)
    assert hf_sector_laws.export(quiet=True) == 0
    man = json.loads((out / "meta" / "manifest.json").read_text(encoding="utf-8"))
    got = {(f["path"], f["rows"], f["docs"]) for f in man["files"]}
    assert got == {("by_sector/He/2025.parquet", 3, 2), ("by_sector/He/2026.parquet", 2, 1), ("by_sector/All/2025.parquet", 1, 1)}
    import pyarrow.parquet as pq
    t = pq.read_table(str(out / "by_sector" / "He" / "2025.parquet")).to_pydict()
    assert set(zip(t["title"], t["parent"])) == {("약사법", ""), ("약사법 시행령", "약사법")}
    assert all(u.startswith("https://www.law.go.kr/") for u in t["source_url"])
    # 섹터 법령 DB 가 비면(이번에 쓴 것 0) 옛 파일을 지우지 않는다
    c = kb_sector.connect(dbp)
    c.execute("DELETE FROM ks_choice")
    c.close()
    hf_sector_laws.export(quiet=True)
    assert (out / "by_sector" / "He" / "2025.parquet").exists()
