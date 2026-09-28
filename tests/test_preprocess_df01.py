"""DF-01 시험 — 장기 거래정지 뒤 감자·병합을 **주식 수로** 잡는가.

무엇이 틀렸었나 —
`preprocess` 의 조정계수는 ``(종가 − 전일대비) ÷ 직전 종가`` 다. 거래소가 기준가를 다시 매기면
포털의 ``vs`` 에 그 기준가가 들어 있어서 계수가 저절로 나온다(카카오 1:5 분할이 그랬다).
그런데 **장기 정지 → 감자 → 정리매매** 순서로 간 두 종목은 포털이 ``vs`` 를 감자 **전** 종가로
계산해 줬다. 그래서 계수가 1.0 — "가격이 이어진다" 로 읽혔다::

    제일바이오 052670  20260209  2,080 → 625,000  vs +622,920  주식 수 29,129,064 → 19,419 (1,500:1)
    큐러블     086460  20250807  1,454 →   1,250  vs −204      주식 수  2,939,400 → 146,970 (20:1)

제일바이오는 수정 종가가 하루에 **300배**(+29,948%) 뛰었고, 큐러블은 −14% 로 멀쩡해 보였지만
실제로는 20주가 1주가 된 날이라 **−95.7%** 다. 둘 다 원천 표(``price_adjusted``)의 오염이다.

여기서 지키는 것 —
1. 정지 뒤 첫 거래일에 ``vs`` 가 아무것도 말하지 않는데 주식 수가 크게 줄었으면 **주식 수 비율**로
   조정한다. 두 실제 사례가 옛 코드에서 먼저 실패한다(1.4절 원칙).
2. **이중 조정을 하지 않는다** — ``vs`` 가 이미 반영했거나(재개일 · 정지 중 기준가 재산정),
   주식 수가 정지 중에 먼저 바뀐 경우.
3. **정지가 없으면 건드리지 않는다** — 우선주 소각(한화우 20241219 주식 수 ×0.44 · 가격 그대로)은
   실제 사건이지 가격 조정이 아니다.
4. 병합 비율이 정수로 떨어지지 않으면 조정은 하되 **확인 필요**로 남긴다.

네트워크는 쓰지 않는다. 마지막 통합 시험만 실제 수집 DB 를 읽기 전용으로 열고, 파일이 없으면 건너뛴다.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from collector import preprocess
from collector.db import SCHEMA

REAL_DB = Path(__file__).resolve().parents[1] / "data" / "collector" / "market.sqlite3"


def _row(bas_dt, clpr, vs, lstg, halted=0, name="테스트"):
    """``preprocess._series`` 가 돌려주는 모양과 같은 한 행. 정지일은 시가·고가·저가가 0 이다."""
    px = 0 if halted else clpr
    return {"bas_dt": bas_dt, "clpr": clpr, "vs": vs, "mkp": px, "hipr": px, "lopr": px,
            "halted": halted, "itms_nm": name, "lstg_st_cnt": lstg}


def _events(rows):
    return [ev for _, _, ev in preprocess.factors(rows) if ev is not None]


def _adj_return(rows, bas_dt):
    """수정 종가로 낸 그날의 하루 수익률."""
    cum = preprocess.cumulative(preprocess.factors(rows))
    i = [r["bas_dt"] for r in rows].index(bas_dt)
    prev, cur = rows[i - 1], rows[i]
    return (cur["clpr"] * cum[cur["bas_dt"]]) / (prev["clpr"] * cum[prev["bas_dt"]]) - 1


# 실제 포털 값 그대로 (2026-09-28 수집 DB 에서 옮겼다).
JEIL = [
    _row("20260105", 2100, 0, 29129064, name="제일바이오"),
    _row("20260106", 2080, -20, 29129064, name="제일바이오"),
    _row("20260107", 2080, 0, 29129064, halted=1, name="제일바이오"),
    _row("20260206", 2080, 0, 29129064, halted=1, name="제일바이오"),
    _row("20260209", 625000, 622920, 19419, name="제일바이오"),
    _row("20260210", 503000, -122000, 19419, name="제일바이오"),
]
CURABLE = [
    _row("20250311", 1280, 155, 2939400, name="큐러블"),
    _row("20250312", 1454, 174, 2939400, name="큐러블"),
    _row("20250313", 1454, 0, 2939400, halted=1, name="큐러블"),
    _row("20250806", 1454, 0, 2939400, halted=1, name="큐러블"),
    _row("20250807", 1250, -204, 146970, name="큐러블"),
    _row("20250808", 699, -551, 146970, name="큐러블"),
]


# ── 1. 두 실제 사례 — 옛 코드에서 먼저 실패한다 ──────────────────────────────
def test_jeil_bio_1500_to_1_is_caught_by_share_count():
    evs = _events(JEIL)
    assert len(evs) == 1
    ev = evs[0]
    assert ev["bas_dt"] == "20260209"
    assert ev["kind"] == preprocess.EV_SHARES
    assert ev["factor"] == 1500          # 29,129,064 ÷ 19,419 = 1,500.03 → 선언된 비율 1,500
    assert ev["needs_review"] == 0
    # 1,500주(2,080원 = 312만 원)가 1주(625,000원)가 됐다 → −79.97%. 옛 코드는 +29,948%.
    assert _adj_return(JEIL, "20260209") == pytest.approx(625000 / (2080 * 1500) - 1)
    assert _adj_return(JEIL, "20260209") == pytest.approx(-0.7997, abs=1e-4)


def test_curable_20_to_1_is_caught_even_though_the_price_looked_normal():
    evs = _events(CURABLE)
    assert [(e["bas_dt"], e["kind"], e["factor"]) for e in evs] == [
        ("20250807", preprocess.EV_SHARES, 20)]
    # 옛 코드로는 −14.0% — 멀쩡한 하루처럼 보여서 벤치마크의 ③(가격제한폭 두 배) 도 못 잡았다.
    assert _adj_return(CURABLE, "20250807") == pytest.approx(1250 / (1454 * 20) - 1)
    assert _adj_return(CURABLE, "20250807") == pytest.approx(-0.9570, abs=1e-4)


def test_today_price_is_untouched():
    """조정은 과거만 고친다 — 가장 최근 날의 계수는 1.0 이다."""
    cum = preprocess.cumulative(preprocess.factors(JEIL))
    assert cum["20260210"] == 1.0 and cum["20260209"] == 1.0
    assert cum["20260206"] == 1500 and cum["20260105"] == 1500


# ── 2. 이중 조정을 하지 않는다 ────────────────────────────────────────────────
def test_vs_already_absorbed_on_resumption_day_is_not_doubled():
    """포털이 기준가를 반영해 준 보통의 감자 — 계수 20 한 번만."""
    rows = [
        _row("20240102", 2000, 0, 1000000),
        _row("20240103", 2000, 0, 1000000, halted=1),
        _row("20240104", 40500, 500, 50000),          # 기준가 40,000 = 2,000 × 20
    ]
    evs = _events(rows)
    assert [(e["kind"], e["factor"]) for e in evs] == [(preprocess.EV_SPLIT, 20.0)]


def test_share_count_changed_during_halt_and_vs_absorbed_is_not_doubled():
    """주식 수가 정지 **중에** 먼저 바뀌고, 재개일 ``vs`` 가 반영한 경우 — 새 규칙은 끼지 않는다."""
    rows = [
        _row("20230101", 1000, 0, 5000000),
        _row("20230102", 1000, 0, 5000000, halted=1),
        _row("20230103", 1000, 0, 500000, halted=1),  # 정지 중 주식 수 1/10
        _row("20230104", 10200, 200, 500000),          # 기준가 10,000 — 포털이 반영
    ]
    evs = _events(rows)
    assert len(evs) == 1 and evs[0]["factor"] == pytest.approx(10.0)
    assert evs[0]["kind"] != preprocess.EV_SHARES


def test_share_count_changed_during_halt_and_vs_silent_uses_the_whole_halt_window():
    """주식 수가 정지 중에 바뀌면 재개일 하루만 보면 비율이 1 이다 — 정지 **전** 마지막 거래일과 비교한다."""
    rows = [
        _row("20230101", 1000, 0, 5000000),
        _row("20230102", 1000, 0, 5000000, halted=1),
        _row("20230103", 1000, 0, 500000, halted=1),
        _row("20230104", 900, -100, 500000),           # 포털이 반영 안 함
    ]
    evs = _events(rows)
    assert [(e["bas_dt"], e["kind"], e["factor"]) for e in evs] == [
        ("20230104", preprocess.EV_SHARES, 10)]
    assert evs[0]["lstg_before"] == 5000000 and evs[0]["lstg_after"] == 500000


def test_exchange_rebased_during_halt_is_not_doubled():
    """정지 중에 거래소가 기준가를 다시 매긴 날(``halted=1`` 인데 계수 ≠ 1)이 이미 반영했다."""
    rows = [
        _row("20230101", 1000, 0, 5000000),
        _row("20230102", 1000, 0, 5000000, halted=1),
        _row("20230103", 20000, 0, 5000000, halted=1),  # 기준가 재산정 20,000 → 계수 20
        _row("20230104", 19000, -1000, 250000),         # 재개 — 주식 수는 이제야 1/20
    ]
    evs = _events(rows)
    assert [e["factor"] for e in evs] == [pytest.approx(20.0)]
    assert all(e["kind"] != preprocess.EV_SHARES for e in evs)


# ── 3. 정지가 없으면 건드리지 않는다 ─────────────────────────────────────────
def test_preferred_share_cancellation_without_halt_is_not_an_adjustment():
    """한화우 000885 20241219 — 주식 수 ×0.441 인데 가격은 39,900 → 40,000. 소각이지 병합이 아니다."""
    rows = [
        _row("20241218", 39900, 0, 4495023),
        _row("20241219", 40000, 100, 1982776),
    ]
    assert _events(rows) == []


@pytest.mark.parametrize("q", [0.60, 0.80, 0.95])
def test_small_share_drop_after_halt_is_left_alone(q):
    """정지 뒤라도 주식 수가 절반 넘게 남으면 자사주 소각 쪽이다 (세종텔레콤 20230908 ×0.815)."""
    rows = [
        _row("20230906", 599, 0, 1000000),
        _row("20230907", 599, 0, 1000000, halted=1),
        _row("20230908", 668, 69, int(1000000 * q)),
    ]
    assert _events(rows) == []


def test_halted_day_itself_never_triggers():
    """주식 수가 바뀐 날이 아직 정지 중이면 가격이 없다 — 판정은 재개일에."""
    rows = [
        _row("20230101", 1000, 0, 5000000),
        _row("20230102", 1000, 0, 5000000, halted=1),
        _row("20230103", 1000, 0, 250000, halted=1),
    ]
    assert _events(rows) == []


# ── 4. 비율이 깨끗하지 않으면 조정하되 확인 필요 ──────────────────────────────
def test_unclean_ratio_is_adjusted_but_flagged():
    """1/Q = 3.33 — 감자와 신주 상장이 같은 날 겹쳤을 수 있다. 사람이 봐야 한다."""
    rows = [
        _row("20230101", 1000, 0, 3000000),
        _row("20230102", 1000, 0, 3000000, halted=1),
        _row("20230103", 1100, 100, 900000),
    ]
    evs = _events(rows)
    assert len(evs) == 1
    assert evs[0]["kind"] == preprocess.EV_REVIEW and evs[0]["needs_review"] == 1
    assert evs[0]["factor"] == pytest.approx(3000000 / 900000)


# ── 5. 표에 쓰는 결과 — 몇 번을 돌려도 같다 ────────────────────────────────────
def test_rebuild_writes_shares_event_and_is_idempotent():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    cols = ["bas_dt", "srtn_cd", "itms_nm", "clpr", "vs", "mkp", "hipr", "lopr", "halted",
            "lstg_st_cnt"]
    conn.executemany(
        f"INSERT INTO price_daily ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        [(r["bas_dt"], "052670", r["itms_nm"], r["clpr"], r["vs"], r["mkp"], r["hipr"],
          r["lopr"], r["halted"], r["lstg_st_cnt"]) for r in JEIL])
    conn.commit()
    t1 = preprocess.rebuild(conn)
    snap1 = [tuple(r) for r in conn.execute("SELECT * FROM price_adjusted ORDER BY bas_dt")]
    t2 = preprocess.rebuild(conn)
    snap2 = [tuple(r) for r in conn.execute("SELECT * FROM price_adjusted ORDER BY bas_dt")]
    assert t1 == t2 and snap1 == snap2
    assert t1[preprocess.EV_SHARES] == 1
    ca = conn.execute("SELECT bas_dt, kind, factor, needs_review FROM corporate_action").fetchall()
    assert [tuple(r) for r in ca] == [("20260209", "shares", 1500.0, 0)]
    adj = dict(conn.execute("SELECT bas_dt, adj_clpr FROM price_adjusted").fetchall())
    assert adj["20260206"] == 2080 * 1500 and adj["20260209"] == 625000
    conn.close()


# ── 6. 실제 수집 DB — 전 종목에서 DF-01 유형이 0곳 ─────────────────────────────
@pytest.mark.skipif(not REAL_DB.exists(), reason="수집 DB 가 없다 (CI · 새 clone)")
def test_real_db_has_no_unadjusted_consolidation_left():
    """S57 실측의 두 곳이 조정됐고, 「주식 수 1/5 아래 · 조정 이벤트 없음」 이 **전 종목** 0곳이다.

    ⚠️ 이 시험은 코드가 아니라 **DB 상태**를 잰다. 코드를 고친 뒤 ``python -m collector.preprocess``
    를 다시 돌리지 않았다면 실패하는 것이 맞다.
    """
    conn = sqlite3.connect(f"{REAL_DB.resolve().as_uri()}?mode=ro", uri=True)
    try:
        got = dict(((cd, dt), (kind, f)) for cd, dt, kind, f in conn.execute(
            "SELECT srtn_cd, bas_dt, kind, factor FROM corporate_action "
            "WHERE (srtn_cd, bas_dt) IN (VALUES ('052670','20260209'), ('086460','20250807'))"))
        assert got == {("052670", "20260209"): ("shares", 1500.0),
                       ("086460", "20250807"): ("shares", 20.0)}

        collapsed = conn.execute("""
            WITH s AS (SELECT srtn_cd, bas_dt, lstg_st_cnt AS n, halted,
                              LAG(lstg_st_cnt) OVER (PARTITION BY srtn_cd ORDER BY bas_dt) AS pn
                         FROM price_daily)
            SELECT s.srtn_cd, s.bas_dt FROM s LEFT JOIN corporate_action AS ca USING (srtn_cd, bas_dt)
             WHERE s.pn > 0 AND s.n > 0 AND s.n * 5 < s.pn AND s.halted = 0
               AND ca.srtn_cd IS NULL""").fetchall()
        assert collapsed == [], f"조정이 빠진 감자·병합 후보(DF-01 유형): {collapsed}"

        # 수정 종가의 하루 수익률이 그날 −79.97% · −95.7% 다 (옛 값 +29,948% · −14.0%).
        for code, dt, want in (("052670", "20260209", -0.7997), ("086460", "20250807", -0.9570)):
            prev, cur = conn.execute(
                "SELECT adj_clpr FROM price_adjusted WHERE srtn_cd=? AND bas_dt<=? "
                "ORDER BY bas_dt DESC LIMIT 2", (code, dt)).fetchall()[::-1]
            assert cur[0] / prev[0] - 1 == pytest.approx(want, abs=1e-4), code
    finally:
        conn.close()
