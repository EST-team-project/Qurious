"""종목 군집화 시험 (TC-CU) — `app/services/stock_clusters.py` (API-CLUS-01 · ML·딥러닝 › 종목 군집화 · 2026-10-14).

여기서 지키는 것 —
1. 대상 — 31 = 자동매매 종목 표(`stock.QUANT_STOCKS` · 업종 이름) · 401 = 분봉 유니버스(`mtf_signals.UNIVERSE` 판 · ETF 제외).
2. 같이 움직임(movement) — 일간 로그 수익률 상관 → 거리 √(2(1−ρ)) → 계층 군집(평균 연결) · k 는 실루엣이 가장 큰 값(같으면 작은 k).
3. 위험 · 수익 특성(profile) — 연 수익률 · 연 변동성 · 시장 민감도(베타) · 최대 낙폭을 표준화해 KMeans.
4. 기간 거래일이 모자란 종목은 빼되 까닭과 함께(말없이 빼지 않는다) · 같은 입력이면 같은 답(지도 좌표 · 묶음 번호).
5. 응답 — 묶음 · 지도 점 · 묶음 이름 낱말(숫자 기준은 응답 thresholds) · 업종과 견줌(31) · 문장 · 출처 · 고지.
6. 수집 DB 는 읽기 전용(mode=ro)으로만 · 일반 사용자 답에는 표 이름 · 명령 없음.

실제 수집 DB 를 쓰지 않는다 — 임시 SQLite 를 COLLECTOR_DB_PATH 로 가리키고, 그 밖의 시험은 없는 경로(autouse).
"""
from __future__ import annotations

import asyncio
import random
import sqlite3
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.services import stock_clusters as C
from collector import benchmark as BM
from collector import db as CDB


@pytest.fixture(autouse=True)
def _no_real_db(tmp_path, monkeypatch):
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없는-수집DB.sqlite3"))


def _days(n: int, end: date = date(2026, 10, 12)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def _two_factor_prices(n_days=260, seed=7, per_group=6):
    """요인 둘 — A 묶음은 요인 1, B 묶음은 요인 2 를 따라 움직인다(잡음 작게)."""
    rng = np.random.default_rng(seed)
    f1 = rng.normal(0, 0.012, n_days)
    f2 = rng.normal(0, 0.012, n_days)
    cols = {}
    for g, f in (("A", f1), ("B", f2)):
        for i in range(per_group):
            r = f + rng.normal(0, 0.003, n_days)
            cols[f"{g}{i}"] = 100 * np.exp(np.cumsum(r))
    idx = [d.isoformat() for d in _days(n_days)]
    market = np.exp(np.cumsum((f1 + f2) / 2))
    return pd.DataFrame(cols, index=idx), pd.Series(np.r_[np.nan, np.diff(market) / market[:-1]], index=idx)


# ── 1. 대상 ────────────────────────────────────────────────────────────

def test_universes_follow_their_sources():
    """TC-CU-01 · 31 = QUANT_STOCKS(코드 · 이름 · 업종) · 401 = 분봉 유니버스 판(mtf_signals.UNIVERSE) · ETF 는 뺀다."""
    from app.services import mtf_signals
    from app.services.stock import QUANT_STOCKS
    q = C.quant_universe()
    assert [(s["code"], s["name"], s["sector"]) for s in q] == [
        (x["symbol"].split(".")[0], x["name"], x["sector"]) for x in QUANT_STOCKS]
    assert C.U401_VERSION == mtf_signals.UNIVERSE
    assert set(C.UNIVERSES) == {"quant31", "u401"} and C.UNIVERSES["quant31"]["has_sector"] is True


# ── 2. 같이 움직임 — 상관 거리 · 계층 군집 ──────────────────────────────

def test_movement_finds_the_two_factor_groups_with_auto_k():
    """TC-CU-02 · 요인 둘 자료 → k=2(실루엣 최대) · 묶음이 요인과 같다 · 거리 √(2(1−ρ)) · 시장 몫을 빼도 · 안 빼도(시장 자료 없음)."""
    px, m = _two_factor_prices()
    for bench in (m, None):
        out = C.movement_clusters(px, bench=bench)
        assert out["market_removed"] is (bench is not None)
        assert out["k"] == 2 and out["k_auto"] is True
        lab = out["labels"]
        assert len({lab[f"A{i}"] for i in range(6)}) == 1 and len({lab[f"B{i}"] for i in range(6)}) == 1
        assert lab["A0"] != lab["B0"]
        rho = out["corr"].loc["A0", "A1"]
        assert out["dist"].loc["A0", "A1"] == pytest.approx(np.sqrt(2 * (1 - rho)))
        best = max(out["k_scores"], key=lambda s: s["silhouette"])
        assert best["k"] == 2 and [s["k"] for s in out["k_scores"]] == sorted(s["k"] for s in out["k_scores"])
        assert set(out["coords"]) == set(px.columns) and all(len(v) == 2 for v in out["coords"].values())


def test_market_mode_removed_before_grouping():
    """TC-CU-02b · 모든 종목이 같은 시장 요인을 크게 타고 업종 요인은 작을 때 — 시장 몫을 빼야 업종 묶음이 나온다(2026-10-14 실측 꼴)."""
    rng = np.random.default_rng(11)
    n = 300
    mkt = rng.normal(0, 0.015, n)
    s1, s2, s3 = (rng.normal(0, 0.004, n) for _ in range(3))
    cols = {}
    for g, s in (("P", s1), ("Q", s2), ("R", s3)):
        for i in range(5):
            cols[f"{g}{i}"] = 100 * np.exp(np.cumsum(mkt + s + rng.normal(0, 0.004, n)))
    idx = [d.isoformat() for d in _days(n)]
    px = pd.DataFrame(cols, index=idx)
    mk = np.exp(np.cumsum(mkt))
    bench = pd.Series(np.r_[np.nan, np.diff(mk) / mk[:-1]], index=idx)
    out = C.movement_clusters(px, bench=bench)
    lab = out["labels"]
    assert out["k"] == 3 and all(len({lab[f"{g}{i}"] for i in range(5)}) == 1 for g in "PQR")
    assert len({lab["P0"], lab["Q0"], lab["R0"]}) == 3


def test_ward_keeps_groups_when_an_outlier_is_present():
    """TC-CU-02c · 따로 노는 종목 하나가 섞여도 k=2 는 두 묶음을 가른다(Ward) — 평균 연결은 외톨이 하나를 떼어 「11 + 1」 로
    가르기 쉽다(2026-10-14 실제 자료: 29 + 2 · 347 + 1). 깨 보기에서 연결 방법을 바꿔도 통과하던 빈틈(C3)을 막는다."""
    # 실제 자료처럼 모두가 같은 시장 요인을 크게 타고(날 수익률 · 시장 몫을 빼지 못한 경우) 묶음 요인이 그다음 · 외톨이 하나
    rng = np.random.default_rng(21)
    n = 260
    mkt = rng.normal(0, 0.012, n)
    f1, f2 = rng.normal(0, 0.012, n), rng.normal(0, 0.012, n)
    cols = {}
    for g, f in (("A", f1), ("B", f2)):
        for i in range(6):
            cols[f"{g}{i}"] = 100 * np.exp(np.cumsum(mkt + f + rng.normal(0, 0.003, n)))
    cols["Z0"] = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, n)))           # 어느 요인도 타지 않는 큰 잡음
    px = pd.DataFrame(cols, index=[d.isoformat() for d in _days(n)])
    out = C.movement_clusters(px, k=2)                                     # 시장 자료 없음 — 날 수익률 그대로
    lab = out["labels"]
    assert out["market_removed"] is False and lab["A0"] != lab["B0"]
    assert sorted(list(lab.values()).count(g) for g in set(lab.values())) != [1, 12]


def test_k_param_validated_and_respected():
    """TC-CU-03 · k 를 고르면 그 수로(자동 아님) · 범위 밖 422 · 종목 수보다 크면 422."""
    px, _m = _two_factor_prices()
    out = C.movement_clusters(px, k=3)
    assert out["k"] == 3 and out["k_auto"] is False and len(set(out["labels"].values())) == 3
    for bad in (1, C.K_MAX + 1):
        with pytest.raises(C.ClusterError) as e:
            C.movement_clusters(px, k=bad)
        assert e.value.status == 422
    with pytest.raises(C.ClusterError) as e:
        C.movement_clusters(px.iloc[:, :3], k=3)
    assert e.value.status == 422


# ── 3. 위험 · 수익 특성 — KMeans ─────────────────────────────────────

def test_profile_separates_high_and_low_volatility_and_names_words():
    """TC-CU-04 · 변동성 큰 묶음 · 작은 묶음 → k=2 · 낱말 「변동성 높음 / 낮음」 · 베타 · 최대 낙폭 계산."""
    rng = np.random.default_rng(3)
    n = 260
    f = rng.normal(0, 0.01, n)
    cols = {}
    for i in range(6):
        cols[f"H{i}"] = 100 * np.exp(np.cumsum(2.0 * f + rng.normal(0, 0.004, n)))
        cols[f"L{i}"] = 100 * np.exp(np.cumsum(0.4 * f + rng.normal(0, 0.001, n)))
    idx = [d.isoformat() for d in _days(n)]
    px = pd.DataFrame(cols, index=idx)
    mk = np.exp(np.cumsum(f))
    bench = pd.Series(np.r_[np.nan, np.diff(mk) / mk[:-1]], index=idx)
    feat = C.features(px, bench)
    assert list(feat.columns) == ["ret", "vol", "beta", "mdd"]
    assert feat.loc["H0", "vol"] > feat.loc["L0", "vol"] and feat.loc["H0", "beta"] > 1.5 > 0.6 > feat.loc["L0", "beta"]
    assert (feat["mdd"] <= 0).all()
    out = C.profile_clusters(feat)
    lab = out["labels"]
    assert out["k"] == 2 and len({lab[f"H{i}"] for i in range(6)}) == 1 and lab["H0"] != lab["L0"]
    words = C.cluster_words(feat, lab)
    assert "변동성 높음" in words[lab["H0"]] and "변동성 낮음" in words[lab["L0"]]
    # 특성 하나의 단위를 바꿔도(연 수익률 × 1000) 묶음이 같다 — 표준화가 없으면 큰 단위 칸이 거리를 지배한다(깨 보기 C13)
    scaled = feat.copy()
    scaled["ret"] = scaled["ret"] * 1000
    assert C.profile_clusters(scaled)["labels"] == lab


# ── 4. 빠진 종목 · 같은 답 ────────────────────────────────────────────

def test_coverage_excludes_with_reason_and_results_are_deterministic():
    """TC-CU-05 · 기간 거래일의 COVERAGE 보다 적은 종목은 까닭과 함께 빠진다 · 같은 입력 두 번 = 같은 답."""
    px, _m = _two_factor_prices()
    px = px.copy()
    px.loc[px.index[: len(px) // 2], "B5"] = np.nan                     # 반만 있음(상장이 늦음)
    kept, excluded = C.apply_coverage(px)
    assert "B5" not in kept.columns and [e["code"] for e in excluded] == ["B5"]
    assert "50" in excluded[0]["reason"] and "%" in excluded[0]["reason"]
    a = C.movement_clusters(kept)
    b = C.movement_clusters(kept)
    assert a["labels"] == b["labels"] and a["coords"] == b["coords"] and a["k_scores"] == b["k_scores"]


# ── 5. 응답(가짜 수집 DB) ─────────────────────────────────────────────

@pytest.fixture()
def dbfile(tmp_path, monkeypatch):
    p = tmp_path / "market.sqlite3"
    c = sqlite3.connect(p)
    c.executescript(CDB.SCHEMA)
    c.executescript(BM.SCHEMA)                                           # benchmark_index 는 벤치마크 단계가 만든다
    c.close()
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(p))
    return p


def _fill(p, px: pd.DataFrame, bench: pd.Series, names=None, universe_rows=None):
    c = sqlite3.connect(p)
    rows = []
    for code in px.columns:
        for d, v in px[code].items():
            if not np.isnan(v):
                rows.append((d.replace("-", ""), code, float(v), float(v), float(v)))
    c.executemany("INSERT INTO price_total_return (bas_dt, srtn_cd, tr_index, tr_index_net, pr_index, div_factor) "
                  "VALUES (?, ?, ?, ?, ?, 1.0)", rows)
    lvl = 1000.0
    brows = []
    for d, r in bench.items():
        lvl = lvl * (1 + (0 if np.isnan(r) else r))
        brows.append((d.replace("-", ""), "KOSPI", "TR", None if np.isnan(r) else float(r), lvl, 10, 1.0))
    c.executemany("INSERT INTO benchmark_index (bas_dt, mrkt_ctg, variant, ret, level, n_const, mcap_total) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?)", brows)
    if names:
        last = px.index[-1].replace("-", "")
        c.executemany("INSERT INTO price_daily (bas_dt, srtn_cd, itms_nm, mrkt_ctg, clpr) VALUES (?, ?, ?, ?, 1)",
                      [(last, code, nm, mk) for code, (nm, mk) in names.items()])
    if universe_rows:
        c.executemany("INSERT INTO intraday_universe (version, symbol, itms_nm, market, reason, rank) VALUES (?, ?, ?, ?, '', ?)",
                      universe_rows)
    c.commit()
    c.close()


def test_read_quant31_fields_sector_match_sentences(dbfile, monkeypatch):
    """TC-CU-06 · 31(가짜 열둘) — 묶음 · 점 · 빠진 종목 · 업종과 견줌(ARI · 같은 업종 다른 묶음) · 문장 · 기준값 · 출처 · 고지."""
    px, bench = _two_factor_prices(n_days=300)
    px = px.copy()
    px.loc[px.index[:200], "B5"] = np.nan
    _fill(dbfile, px, bench)
    fake = [{"code": c, "name": f"종목{c}", "sector": ("반도체" if c.startswith("A") else "금융") if c != "A5" else "금융"}
            for c in px.columns]
    monkeypatch.setattr(C, "quant_universe", lambda: fake)
    out = C.read_clusters("quant31", "1y", "movement", 0, admin=False)
    assert out["available"] is True and out["k"] == 2 and out["universe"]["key"] == "quant31"
    assert [e["code"] for e in out["excluded"]] == ["B5"]
    assert len(out["points"]) == 11 and {p["cluster"] for p in out["points"]} == {1, 2}
    assert all(set(p) >= {"code", "name", "sector", "cluster", "x", "y", "silhouette", "nearest", "ret", "vol", "beta", "mdd"}
               for p in out["points"])
    sm = out["sector_match"]
    assert sm is not None and -1 <= sm["ari"] <= 1 and any(m["code"] == "A5" for m in sm["split"])   # A5 는 금융인데 A 묶음
    assert out["thresholds"]["coverage"] == C.COVERAGE and out["thresholds"]["k_max"] == C.K_MAX
    text = " ".join(out["sentences"])
    assert "실루엣" in text and "보장" in text and "같은 업종" in text and "평균" in text
    assert out["separation"]["within"] > out["separation"]["between"]          # 같은 묶음끼리 더 같이 움직였다
    assert "업종이 같은 종목끼리 모인 묶음" in text                             # 반도체 다섯 · 금융 다섯(+A5) 묶음
    assert "조정 랜드" not in text and out["sector_match"]["ari"] is not None     # ARI 는 응답에만(문장에선 오해 — 2026-10-14)
    mx = out["matrix"]                                                         # 작은 대상만 — 묶음 차례 · 대칭 · 대각 1
    assert mx is not None and len(mx["order"]) == 11 and len(mx["values"]) == 11
    lab = {p["code"]: p["cluster"] for p in out["points"]}
    assert [lab[c] for c in mx["order"]] == sorted(lab[c] for c in mx["order"])
    assert all(mx["values"][i][i] == 1.0 and mx["values"][i][j] == mx["values"][j][i] for i in range(11) for j in range(11))
    assert out["source"] and out["notice"] and "admin_hint" not in out
    ch = out["choices"]                                                        # 화면 고르기 단추의 정본은 서버
    assert [c["key"] for c in ch["universe"]] == list(C.UNIVERSES) and [c["key"] for c in ch["period"]] == list(C.PERIODS)
    assert [c["key"] for c in ch["method"]] == list(C.METHODS) and ch["k"] == list(range(C.K_MIN, C.K_MAX + 1))


def test_read_u401_excludes_etf_and_has_no_sector_match(dbfile):
    """TC-CU-07 · 401 — 분봉 유니버스 판의 주식만(ETF 제외) · 업종 견줌 없음 · 위험 · 수익 특성 방법도 같은 꼴."""
    px, bench = _two_factor_prices(n_days=300)
    rows = [(C.U401_VERSION, c, f"종목{c}", "KOSPI", i) for i, c in enumerate(px.columns)]
    rows.append((C.U401_VERSION, "069500", "KODEX 200", "ETF", 99))
    rows.append(("u1-20260929", "999999", "옛 판", "KOSPI", 1))
    _fill(dbfile, px, bench, universe_rows=rows)
    out = C.read_clusters("u401", "1y", "profile", 0)
    assert out["available"] is True and out["sector_match"] is None and out["universe"]["n_requested"] == 12
    assert out["thresholds"]["matrix_max"] == C.MATRIX_MAX and (out["matrix"] is None) is (12 > C.MATRIX_MAX)
    assert {p["code"] for p in out["points"]} == set(px.columns)


def test_errors_and_unavailable_and_admin_hint(dbfile, tmp_path, monkeypatch):
    """TC-CU-08 · 모르는 대상 · 기간 · 방법 422 · 종목이 셋보다 적으면 available False · DB 없음 503 — 할 일은 관리자에게만."""
    for args in (("x", "1y", "movement"), ("quant31", "9y", "movement"), ("quant31", "1y", "magic")):
        with pytest.raises(C.ClusterError) as e:
            C.read_clusters(*args, 0)
        assert e.value.status == 422
    monkeypatch.setattr(C, "quant_universe", lambda: [{"code": "000001", "name": "가", "sector": "x"}])
    out = C.read_clusters("quant31", "1y", "movement", 0, admin=False)
    assert out["available"] is False and out["reason"] and "admin_hint" not in out and "price_total_return" not in str(out)
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "없음.sqlite3"))
    with pytest.raises(C.ClusterError) as e:
        C.read_clusters("quant31", "1y", "movement", 0)
    assert e.value.status == 503 and "admin_hint" not in e.value.detail(False) and "admin_hint" in e.value.detail(True)


def test_opens_collector_db_read_only(dbfile, monkeypatch):
    """TC-CU-09 · 수집 DB 는 mode=ro 로만 연다."""
    px, bench = _two_factor_prices(n_days=300)
    _fill(dbfile, px, bench)
    monkeypatch.setattr(C, "quant_universe", lambda: [{"code": c, "name": c, "sector": "x"} for c in px.columns])
    seen, real = [], sqlite3.connect

    def spy(target, *a, **k):
        seen.append(str(target))
        return real(target, *a, **k)

    monkeypatch.setattr(C.sqlite3, "connect", spy)
    C.read_clusters("quant31", "1y", "movement", 0)
    assert seen and all("mode=ro" in t for t in seen)


def test_route_passes_admin_flag_and_maps_errors(monkeypatch):
    """TC-CU-10 · 라우트 — 관리자 여부를 서비스에 넘기고 서비스 오류를 그 상태 코드로."""
    from fastapi import HTTPException
    from app.routes import clusters as R

    got = {}

    def fake(universe, period, method, k, admin=False):
        got.update(universe=universe, period=period, method=method, k=k, admin=admin)
        return {"available": True}

    monkeypatch.setattr(R.stock_clusters, "read_clusters", fake)
    assert asyncio.run(R.clusters_route(universe="u401", period="2y", method="profile", k=4, user={"roles": ["admin"]})) \
        == {"available": True}
    assert got == {"universe": "u401", "period": "2y", "method": "profile", "k": 4, "admin": True}

    def boom(*a, **k):
        raise C.ClusterError(422, "모르는 대상", "hint")

    monkeypatch.setattr(R.stock_clusters, "read_clusters", boom)
    with pytest.raises(HTTPException) as e:
        asyncio.run(R.clusters_route(universe="x", period="1y", method="movement", k=0, user={"roles": []}))
    assert e.value.status_code == 422 and "admin_hint" not in e.value.detail
