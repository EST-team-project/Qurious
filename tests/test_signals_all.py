"""신호 전체 종목 기록 — 대상 목록 · 분봉 없음 세기 · 보존 기준일 · 기간 상한 (TC-SGA · 할 일 `②-32`).

설계 `docs/phase-3/02-design/system/신호-전체종목-기록-설계.md` 3절. 합성 수집 DB(SQLite)로 돌아 앱 DB · 실제 수집 DB 가 필요 없다.
"""
import sqlite3
from datetime import date, timedelta

import pytest

from scripts import signals_all as sa


def _db(tmp_path, stocks, etfs=(), universe=()):
    """stocks: (bas_dt, 코드, 종가, 시장) · etfs: (bas_dt, 코드, 종가) · universe: 분봉 유니버스 코드."""
    p = tmp_path / "market.sqlite3"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE price_daily (bas_dt TEXT, srtn_cd TEXT, clpr REAL, mrkt_ctg TEXT)")
    c.execute("CREATE TABLE etf_daily (bas_dt TEXT, srtn_cd TEXT, clpr REAL)")
    c.execute("CREATE TABLE intraday_universe (version TEXT, symbol TEXT, rank INTEGER)")
    c.executemany("INSERT INTO price_daily VALUES (?,?,?,?)", stocks)
    c.executemany("INSERT INTO etf_daily VALUES (?,?,?)", etfs)
    c.executemany("INSERT INTO intraday_universe VALUES ('u2-20260930', ?, ?)", [(s, i) for i, s in enumerate(universe)])
    c.commit()
    c.close()
    return p


D = "20261030"


def test_targets_kospi_kosdaq_etf_minus_intraday_universe(tmp_path):
    p = _db(tmp_path,
            stocks=[(D, "005930", 70000, "KOSPI"), (D, "005935", 60000, "KOSPI"),      # 우선주도 들어간다
                    (D, "035720", 50000, "KOSDAQ"), (D, "900001", 1000, "KONEX"),     # KONEX 는 뺀다
                    (D, "000660", 90000, "KOSPI"),                                    # 분봉 유니버스 — 뺀다
                    (D, "111111", 0, "KOSPI"),                                        # 종가 0 — 거래 없음
                    ("20261029", "222222", 10, "KOSPI")],                             # 다른 날
            etfs=[(D, "069500", 35000), (D, "00088K", 12000), (D, "005930", 1)],     # 주식과 같은 코드는 한 번만
            universe=["000660"])
    got = sa.targets(["2026-10-30"], path=p)
    assert got == ["005930", "005935", "035720", "00088K", "069500"]
    assert "900001" not in got and "000660" not in got and "111111" not in got and "222222" not in got


def test_targets_unions_days_and_survives_missing_etf_table(tmp_path):
    p = _db(tmp_path, stocks=[(D, "005930", 1, "KOSPI"), ("20261029", "035720", 1, "KOSDAQ")])
    sqlite3.connect(p).execute("DROP TABLE etf_daily").connection.commit()
    assert sa.targets(["2026-10-29", "2026-10-30"], path=p) == ["005930", "035720"]


def test_targets_lives_in_app_services_and_script_shares_it(tmp_path):
    """#487 — 대상 목록은 앱(`app/services`)이 부를 수 있는 곳에 있고, 배치 스크립트는 같은 함수를 쓴다(규칙이 둘로 갈라지지 않게)."""
    from app.services import signal_targets as st

    assert sa.targets is st.targets
    p = _db(tmp_path, stocks=[(D, "005930", 1, "KOSPI"), (D, "000660", 1, "KOSPI")], universe=["000660"])
    assert st.targets(["2026-10-30"], path=p) == ["005930"]             # 앱 쪽에서 불러도 같은 결과
    assert st.MARKETS == ("KOSPI", "KOSDAQ")


def _rec(timeframes):
    return {"timeframes": timeframes}


def test_without_intraday_counts_only_missing_60m():
    ok = _rec([{"timeframe": "60m", "score": 1}, {"timeframe": "1d", "score": 2}])
    no60 = _rec([{"timeframe": "60m", "error": "시세 없음"}, {"timeframe": "1d", "score": 2}])
    odd = _rec([{"timeframe": "1d", "error": "시세 없음"}])          # 일봉이 비어도 「분봉 없음」 이 아니다
    assert sa.without_intraday([ok, no60, no60, odd, {"timeframes": None}]) == 2
    assert sa.without_intraday([]) == 0


def test_cutoff_day_keeps_exactly_keep_days_trading_days(tmp_path):
    start = date(2026, 5, 1)
    days = []
    d = start
    while len(days) < 130:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    p = _db(tmp_path, stocks=[(x.strftime("%Y%m%d"), "005930", 1, "KOSPI") for x in days])
    last = days[-1].isoformat()
    cut = sa.cutoff_day(last, 120, path=p)
    assert cut == days[-120].isoformat()                              # 이 날 포함 120거래일을 둔다
    assert sa.cutoff_day(last, 0, path=p) is None                     # 0 = 지우지 않음
    assert sa.cutoff_day(last, 200, path=p) is None                   # 거래일이 모자라면 지우지 않는다


class _Pool:
    def __init__(self, workers): pass
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def map(self, fn, items): return [fn(x) for x in items]


def test_main_rejects_long_range_before_anything_runs(monkeypatch, capsys):
    many = [(date(2026, 10, 1) + timedelta(days=i)).isoformat() for i in range(sa.MAX_DAYS + 1)]
    monkeypatch.setattr(sa.ms, "trading_days", lambda s, e, **kw: many)
    monkeypatch.setattr(sa, "targets", lambda days, **kw: pytest.fail("기간 상한에서 멈춰야 한다"))
    assert sa.main(["--from", "2026-10-01", "--to", "2026-10-10"]) == 2
    assert "까지만 받는다" in capsys.readouterr().out


def test_main_dry_run_never_touches_app_db(monkeypatch, capsys):
    monkeypatch.setattr(sa.ms, "trading_days", lambda s, e, **kw: ["2026-10-30"])
    monkeypatch.setattr(sa, "targets", lambda days, **kw: ["005930", "069500"])
    monkeypatch.setattr(sa, "ProcessPoolExecutor", _Pool)
    monkeypatch.setattr(sa.sd, "_check_db", lambda: pytest.fail("dry-run 은 DB 를 보지 않는다"))
    monkeypatch.setattr(sa.sd, "_write", lambda recs: pytest.fail("dry-run 은 쓰지 않는다"))

    def one(args):
        return args[0], [{"as_of": date(2026, 10, 30), "signal": "관망",
                          "timeframes": [{"timeframe": "60m", "error": "시세 없음"}]}], None

    monkeypatch.setattr(sa.sd, "_one", one)
    assert sa.main(["--date", "2026-10-30", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "종목 2" in out and "분봉 없이 계산(일봉 · 주봉만) — 2줄 / 2줄" in out


def test_main_stops_before_computing_when_app_db_down(monkeypatch, capsys):
    monkeypatch.setattr(sa.ms, "trading_days", lambda s, e, **kw: ["2026-10-30"])
    monkeypatch.setattr(sa, "targets", lambda days, **kw: ["005930"])
    calls = []

    async def check():
        calls.append("check")
        raise ConnectionRefusedError("앱 DB 꺼짐")

    monkeypatch.setattr(sa.sd, "_check_db", check)
    monkeypatch.setattr(sa.sd, "_one", lambda a: calls.append("compute"))
    assert sa.main(["--date", "2026-10-30"]) == 3
    assert calls == ["check"]
    assert "앱 DB 에 연결하지 못했다" in capsys.readouterr().out
