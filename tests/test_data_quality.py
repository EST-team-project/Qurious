"""TC-QUAL — 데이터 품질 검사 (collector/quality.py · 할 일 ①-12 `SCH-DQ` · 2026-10-29 착수)

작은 메모리 DB 에 일부러 결함을 넣어 **검사가 실제로 걸리는지** 본다(실제 DB 가 깨끗하면 검사는 늘 ✅ 라 고장을 못 가린다).
1. 깨끗한 데이터는 경고 0 · 참고(시가 0)만 센다. (TC-QUAL-01)
2. 결측 — 사유 없는 평일 공백 · 행 수가 적은 날 · ETF/지수/수정주가/총수익 빠짐을 잡고, 사유(설날)가 있는 휴장은 안 잡는다. (TC-QUAL-02)
3. 정합성 — 고가/저가 위반 · 종가 0 · 음수 거래량 · 적재 기록 이상을 잡고, 가장 최근 날 뒤의 미적재는 안 센다. (TC-QUAL-03)
4. 중복은 기본키가 막으므로 키 없는 표로 안전망을 시험한다. (TC-QUAL-04)
5. 한 검사가 예외를 내도 나머지는 돈다 · 시세가 없으면 빈 결과 · 읽기 전용 · 경고만(--strict 일 때만 1). (TC-QUAL-05)
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import quality  # noqa: E402

DAYS = ["20261020", "20261021", "20261022", "20261023", "20261026", "20261027"]   # 월~화(24·25 는 주말)
STOCKS = [f"{i:06d}" for i in range(1, 11)]


def _db(pk: bool = True) -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    key = ", primary key (bas_dt, srtn_cd)" if pk else ""
    c.executescript(f"""
      create table price_daily (bas_dt text, srtn_cd text, clpr int, mkp int, hipr int, lopr int, trqu int{key});
      create table price_adjusted (bas_dt text, srtn_cd text);
      create table price_total_return (bas_dt text, srtn_cd text);
      create table etf_daily (bas_dt text, srtn_cd text);
      create table index_daily (bas_dt text, idx_nm text);
      create table ingest_day (source text, bas_dt text, status text, rows int, attempts int, updated_at text, message text);
      create table market_calendar (cal_date text, is_trading_day int, reason text);
    """)
    for d in DAYS:
        for s in STOCKS:
            c.execute("insert into price_daily values (?,?,100,100,110,90,1000)", (d, s))
            c.execute("insert into price_adjusted values (?,?)", (d, s))
            c.execute("insert into price_total_return values (?,?)", (d, s))
        c.execute("insert into etf_daily values (?, 'E1')", (d,))
        c.execute("insert into index_daily values (?, 'KOSPI')", (d,))
        for src in quality.PORTAL_SOURCES:
            c.execute("insert into ingest_day values (?,?, 'done', 10, 1, '', '')", (src, d))
    for d in ("2026-10-24", "2026-10-25"):
        c.execute("insert into market_calendar values (?, 0, '주말')", (d,))
    for d in DAYS:
        c.execute("insert into market_calendar values (?, 1, '')", (f"{d[:4]}-{d[4:6]}-{d[6:]}",))
    return c


def _by(res: dict) -> dict:
    return {c["check"]: c for c in res["checks"]}


def test_clean_data_has_no_warnings():
    """TC-QUAL-01 · 깨끗한 데이터는 경고 0 · 오류 0 — 창은 시세 날짜로 센다."""
    res = quality.run(_db(), days=6)
    assert res["warn"] == 0 and res["error"] == 0 and res["window"] == ["20261020", "20261027"] and res["window_days"] == 6
    assert {c["check"] for c in res["checks"]} == set(quality.LABELS)
    assert all(c["status"] == "ok" for c in res["checks"])


def test_missing_data_is_caught_and_known_holidays_are_not():
    """TC-QUAL-02 · 사유 없는 평일 공백 · 행이 적은 날 · 빠진 짝을 잡는다 — 달력이 사유를 아는 휴장은 안 잡는다."""
    c = _db()
    # 10-22 시세 통째로 삭제 + 달력은 사유를 모른다 → PD-GAP · 10-23 은 행 수 절반 → PD-THIN
    c.execute("delete from price_daily where bas_dt='20261022'")
    c.execute("delete from price_adjusted where bas_dt='20261022'")
    c.execute("delete from price_total_return where bas_dt='20261022'")
    c.execute("delete from price_daily where bas_dt='20261023' and srtn_cd > '000005'")
    c.execute("delete from etf_daily where bas_dt='20261021'")
    c.execute("delete from index_daily where bas_dt='20261027'")
    c.execute("delete from price_adjusted where bas_dt='20261026' and srtn_cd='000003'")
    c.execute("delete from price_total_return where bas_dt='20261020'")
    r = _by(quality.run(c, days=6))
    assert r["PD-GAP"]["status"] == "warn" and r["PD-GAP"]["sample"] == ["20261022"]
    assert r["PD-THIN"]["status"] == "warn" and r["PD-THIN"]["sample"] == ["20261023:5행"]
    assert r["ETF-GAP"]["sample"] == ["20261021"] and r["IDX-GAP"]["sample"] == ["20261027"]
    assert r["ADJ-COVER"]["count"] == 1 and r["TR-COVER"]["count"] == 10            # 10-20 하루치(10행)
    # 같은 공백이라도 달력이 사유를 알면(설날 같은) 정상이다
    c2 = _db()
    c2.execute("delete from price_daily where bas_dt='20261022'")
    c2.execute("delete from price_adjusted where bas_dt='20261022'")
    c2.execute("delete from price_total_return where bas_dt='20261022'")
    c2.execute("insert into market_calendar values ('2026-10-22', 0, '임시공휴일')")
    assert _by(quality.run(c2, days=6))["PD-GAP"]["status"] == "ok"


def test_integrity_problems_are_caught():
    """TC-QUAL-03 · 고가/저가 위반 · 종가 0 · 음수 거래량 · 포털 적재 이상을 잡는다 — 시가 0 은 참고(info) · 가장 최근 날 뒤는 안 센다."""
    c = _db()
    c.execute("update price_daily set hipr=95 where bas_dt='20261027' and srtn_cd='000001'")        # 고가 < 종가
    c.execute("update price_daily set lopr=105 where bas_dt='20261026' and srtn_cd='000002'")       # 저가 > 종가
    c.execute("update price_daily set clpr=0 where bas_dt='20261023' and srtn_cd='000003'")
    c.execute("update price_daily set trqu=-5 where bas_dt='20261023' and srtn_cd='000004'")
    c.execute("update price_daily set mkp=0 where bas_dt='20261021'")                                # 시가 0 · 이 행들은 OHLC 대상에서 빠진다
    c.execute("update ingest_day set status='partial' where source='portal_etf' and bas_dt='20261022'")
    c.execute("insert into ingest_day values ('portal', '20261028', 'empty', 0, 1, '', '')")          # 아직 안 올라온 날 — 세지 않는다
    c.execute("insert into ingest_day values ('portal', '20261024', 'empty', 0, 1, '', '')")          # 시세 없는 날(휴장)의 empty — 정상이라 세지 않는다
    r = _by(quality.run(c, days=6))
    assert r["PD-OHLC"]["count"] == 2 and r["PD-NONPOS"]["count"] == 2
    assert r["PD-NOOPEN"]["status"] == "info" and r["PD-NOOPEN"]["count"] == 10
    assert r["INGEST"]["count"] == 1 and r["INGEST"]["sample"] == ["portal_etf/20261022=partial"]
    assert quality.run(c, days=6)["warn"] == 3                                                       # OHLC · NONPOS · INGEST(info 는 경고가 아니다)


def test_duplicates_are_caught_when_the_key_is_missing():
    """TC-QUAL-04 · 기본키가 막아 보통 0 — 키가 없는 표(다시 만들다 깨진 경우)에서 중복을 잡는 안전망."""
    c = _db(pk=False)
    c.execute("insert into price_daily values ('20261027','000001',100,100,110,90,1000)")
    r = _by(quality.run(c, days=6))["PD-DUP"]
    assert r["status"] == "warn" and r["sample"] == ["20261027/000001×2"]


def test_one_failing_check_does_not_stop_the_rest_and_empty_db_is_handled(monkeypatch, capsys):
    """TC-QUAL-05 · 검사 하나가 예외를 내도 그것만 error · 시세가 없으면 빈 결과 · 읽기 전용으로 열고 경고만(--strict 일 때만 1)."""
    c = _db()
    c.execute("drop table etf_daily")                                   # 한 검사만 터진다
    res = quality.run(c, days=6)
    st = {x["check"]: x["status"] for x in res["checks"]}
    assert st["ETF-GAP"] == "error" and res["error"] == 1 and st["PD-OHLC"] == "ok" and len(res["checks"]) == len(quality.CHECKS)
    empty = sqlite3.connect(":memory:")
    empty.execute("create table price_daily (bas_dt text, srtn_cd text)")
    out = quality.run(empty, days=20)
    assert out["window"] is None and out["checks"] == [] and out["error"] == 0
    assert "경고 0" in quality.render(quality.run(_db(), days=6))
    src = (ROOT / "collector" / "quality.py").read_text(encoding="utf-8")
    assert "mode=ro" in src and ".execute(\"insert" not in src and "commit(" not in src      # 이 검사는 DB 를 바꾸지 않는다


def test_cli_is_warn_only_unless_strict(tmp_path, capsys, monkeypatch):
    """TC-QUAL-05b · CLI — 경고가 있어도 기본은 종료코드 0 · --strict 는 1 · --write 가 상태 파일을 쓴다."""
    db = tmp_path / "m.sqlite3"
    disk = sqlite3.connect(db)
    mem = _db()
    mem.execute("update price_daily set clpr=0 where bas_dt='20261027' and srtn_cd='000001'")
    mem.commit()                                  # 열린 쓰기 트랜잭션이 있으면 backup 이 락을 기다리며 멈춘다
    mem.backup(disk)
    disk.close()
    assert quality.main(["--db", str(db), "--days", "6"]) == 0
    assert quality.main(["--db", str(db), "--days", "6", "--strict"]) == 1
    capsys.readouterr()
    assert quality.main(["--db", str(db), "--days", "6", "--json"]) == 0
    import json
    assert json.loads(capsys.readouterr().out)["warn"] >= 1
    # --write 는 상태 파일을 쓰고, 수집 DB 는 바꾸지 않는다(바이트가 그대로)
    from collector import config
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    before = db.read_bytes()
    assert quality.main(["--db", str(db), "--days", "6", "--write"]) == 0
    saved = json.loads((tmp_path / "state" / "data_quality_last.json").read_text(encoding="utf-8"))
    assert saved["warn"] >= 1 and saved["window"] == ["20261020", "20261027"]
    assert db.read_bytes() == before


def test_runner_step_runs_after_derived_steps_and_never_blocks():
    """TC-QUAL-06 · 러너 연결 — 품질 검사 단계는 수정주가 · 총수익 · 벤치마크 **뒤**(앞이면 ADJ-COVER · TR-COVER 거짓 경고), 일봉 · 신호 **앞**에 있고 회차를 막지 않으며
    HF 로 올리지 않는다. 인자는 quality CLI 가 실제로 받는 것만 쓴다(없는 인자를 쓰면 매 회차 argparse 오류)."""
    from scripts import daily_update as du
    names = [s.name for s in du.STEPS]
    q = next(s for s in du.STEPS if s.name == "quality")
    for before in ("price", "adjusted", "total_return", "benchmark"):
        assert names.index(before) < names.index("quality"), f"{before} 가 품질 검사보다 앞이어야 한다"
    assert names.index("quality") < names.index("ohlcv") < names.index("signals"), "일봉 · 신호 앞 — 기존 순서(일봉 → 신호 → 일지 → 목록표)를 안 깬다"
    assert q.fatal is False and not q.upload and not q.sharing and not q.app_db
    assert q.args[:2] == ["-m", "collector.quality"]
    # 단계가 넘기는 인자는 CLI 가 실제로 받는 것뿐이어야 한다(예: 없는 --quiet 를 넘기면 단계가 매 회차 argparse 오류로 끝난다)
    assert set(q.args[2:]) <= {"--write", "--days", "--json"}, q.args


def _view(snap, now_iso="2026-10-30T13:00:00+09:00"):
    from datetime import datetime
    from app.services import data_status as ds
    return ds.quality_view(snap, datetime.fromisoformat(now_iso))


def test_quality_view_states_from_synthetic_snapshots_and_never_invents():
    """TC-QUAL-07 · 데이터 관제 한 줄 — 합성 결과로 상태 다섯을 가른다(없음 · 이상 없음 · 경고 · 검사 오류 · 오래됨).
    파일이 없으면 지어내지 않고 「없음」이고, 검사 오류(검사가 예외)는 자료 경고와 따로 센다."""
    assert _view(None)["state"] == "none" and _view({})["state"] == "none"
    ok = _view({"at": "2026-10-30T12:50:00+09:00", "days": 20, "window_days": 20, "warn": 0, "error": 0})
    assert ok["state"] == "ok" and ok["state_label"] == "이상 없음"
    assert "최근 20거래일" in ok["label"] and "경고 0건" in ok["label"] and "10-30 검사" in ok["label"] and ok["days_ago"] == 0
    warn = _view({"at": "2026-10-30T12:50:00+09:00", "days": 20, "window_days": 20, "warn": 3, "error": 0})
    assert warn["state"] == "warn" and warn["warn"] == 3 and "경고 3건" in warn["label"]
    err = _view({"at": "2026-10-30T12:50:00+09:00", "days": 20, "window_days": 20, "warn": 0, "error": 1})
    assert err["state"] == "error" and "검사 오류 1건" in err["label"], "검사 예외는 경고 0 이어도 정상으로 보이면 안 된다"
    old = _view({"at": "2026-10-20T12:50:00+09:00", "days": 20, "window_days": 20, "warn": 0, "error": 0})
    assert old["state"] == "stale" and "10일 전이라 오래됨" in old["label"], "깨끗했던 옛 검사를 지금도 깨끗하다고 보이면 안 된다"
    # 경고가 있으면 오래된 것보다 경고가 먼저 보인다
    assert _view({"at": "2026-10-20T12:50:00+09:00", "window_days": 20, "warn": 2, "error": 0})["state"] == "warn"


def test_quality_line_is_wired_but_kept_out_of_the_overall_verdict():
    """TC-QUAL-08 · 한 줄은 `get_status` 응답에 실리고 화면이 그 글을 그대로 보이되, 전체 판정(verdict)에는 섞지 않는다(소스 구조).
    검사 파일 이름은 collector 가 쓰는 것과 같다."""
    src = (ROOT / "app" / "services" / "data_status.py").read_text(encoding="utf-8")
    body = src.split("def get_status(", 1)[1]
    assert '"quality": quality_view(' in body
    verdict_part = body.split('verdict = ["ok", "warning", "error"][worst]', 1)[0]
    assert "quality" not in verdict_part, "품질 검사는 처음엔 경고만 한다 — 판정에 섞으면 회차 판정이 흔들린다"
    from collector import config
    from app.services import data_status as ds
    assert ds.QUALITY_FILE == "data_quality_last.json" and (config.STATE_DIR / ds.QUALITY_FILE).name == ds.QUALITY_FILE
    js = (ROOT / "public" / "js" / "datahub.js").read_text(encoding="utf-8")
    assert '["데이터 품질 검사", qualityBrief(st.quality)]' in js and "q.state_label" in js and "escHtml(q.label)" in js
