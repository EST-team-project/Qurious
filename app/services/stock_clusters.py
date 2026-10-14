"""종목 군집화 — 같이 움직인 묶음(상관 거리)과 위험 · 수익 특성 묶음(KMeans)을 숫자 · 지도 · 쉬운 말로 (API-CLUS-01 · 2026-10-14).

왜 새로 쓰나
-----------
강사님 화면(`app/services/ml_models.py` 의 `cluster_stocks`)은 기술 지표 평균(RSI · 이동평균 비 · 볼린저 폭 …)을 KMeans
**k=3 고정**으로 묶었다. ① 묶음 수를 자료가 고르지 않고 ② 「무엇이 닮았나」 를 지표 평균으로는 설명하기 어렵고 ③ 종목마다
시세를 차례로 불러 20초쯤 걸렸고 ④ 업종과 견주지 않았다. 여기서는 강사님 th10 `trading/stock_clustering.py` 꼴(KMeans ·
계층 군집 · PCA 지도 · 실루엣으로 k 고르기 · 군집 해석 표)을 가져와, Mantegna(1999, 「Hierarchical Structure in Financial
Markets」)의 상관 거리를 더했다(사용자 결정 2026-10-14). th11 의 「성장주 · 가치주 · 방어주」 이름은 쓰지 않는다 — 수익률 ·
변동성 묶음에 투자 스타일 이름을 붙이면 틀린다. 묶음 이름은 숫자로 만든 낱말(「변동성 높음」 …)이다.

두 방법
-------
- movement(같이 움직인 묶음): 일간 로그 수익률에서 **시장(코스피 총수익) 몫을 뺀 나머지**의 상관 ρ → 거리 d = √(2(1−ρ)) →
  계층 군집(Ward 연결) → k 는 거리 행렬 실루엣이 가장 큰 값(같으면 작은 k). 지도 = 그 거리의 고전 다차원 척도(MDS).
  시장 몫을 빼는 까닭(2026-10-14 실측): 날 수익률을 그대로 쓰면 시장 전체가 같이 움직인 몫이 상관을 지배해, 평균 연결로
  자르면 31종목이 29 + 2, 401종목이 347 + 1 처럼 「한 덩어리 + 외톨이」 로만 갈렸다(실루엣 0.12 · 0.15). 시장 몫을 빼면
  업종 같은 공통 움직임이 드러난다(Mantegna 이후 상관 군집 연구의 「시장 모드 제거」 관행). Ward 는 묶음 크기를 고르게
  만든다 — 이 거리는 표준화한 수익률 사이의 유클리드 거리와 비례해 Ward 를 쓸 수 있다. 시장 지수가 없으면 빼지 못한 채로
  묶고 그 사실을 문장으로 알린다(말없이 바꾸지 않는다).
- profile(위험 · 수익 특성 묶음): 연 수익률 · 연 변동성 · 시장 민감도(베타 — 우리 코스피 총수익 벤치마크) · 최대 낙폭을 표준화 →
  KMeans(n_init 10 · random_state 42 — 같은 입력이면 같은 답) → k 실루엣. 지도 = 표준화한 특성의 PCA 두 축.

대상 · 기간 · 빠진 종목
----------------------
- quant31 = 자동매매 31종목(`stock.QUANT_STOCKS` — 업종 이름이 있어 「같은 업종인데 다른 묶음」 과 조정 랜드 지수 ARI 로 견준다).
- u401 = 분봉 유니버스(`mtf_signals.UNIVERSE` 판 — 코스피 · 코스닥 지수 구성 · ETF 는 뺀다 · 업종 이름 없음).
- 기간 1y · 2y · 3y — 끝은 수집 시세의 마지막 날. 값은 총수익 지수(`price_total_return.tr_index` — 배당 재투자 · 세전).
- 기간 거래일의 `COVERAGE` 보다 적게 있는 종목은 빼고 응답 `excluded` 에 까닭을 적는다(말없이 빼지 않는다). 남은 빈 날은
  상관을 셀 때 쌍마다 있는 날만 쓴다(pandas pairwise).
- 실루엣 해석 경계(0.25 · 0.5)는 Kaufman · Rousseeuw(1990, 「Finding Groups in Data」)의 관행 — 0.25 아래면 「뚜렷한 묶음
  구조가 없다」 고 읽는다.

읽기만 한다 — 수집 DB 는 `?mode=ro`. 일반 사용자 답에는 표 이름 · 명령이 없고 관리자에게만 할 일.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.services import collector_db
from app.services.mtf_signals import UNIVERSE as U401_VERSION

KST = timezone(timedelta(hours=9))

UNIVERSES: Dict[str, Dict] = {
    "quant31": {"label": "자동매매 31종목", "has_sector": True},
    "u401": {"label": "분봉 수집 종목(코스피 · 코스닥 지수 구성)", "has_sector": False},
}
PERIODS = {"1y": 12, "2y": 24, "3y": 36}
PERIOD_TEXT = {"1y": "지난 1년", "2y": "지난 2년", "3y": "지난 3년"}
METHODS = {
    "movement": "같이 움직인 묶음(일간 수익률 상관)",
    "profile": "위험 · 수익 특성 묶음(연 수익률 · 변동성 · 시장 민감도 · 최대 낙폭)",
}
COVERAGE = 0.9
K_MIN, K_MAX = 2, 8
#: 종목이 이 수 이하일 때만 상관 행렬(묶음 차례)을 응답에 싣는다 — 31종목은 약 6KB · 401종목은 16만 칸이라 싣지 않는다.
MATRIX_MAX = 60
MIN_STOCKS = 3
TRADING_DAYS = 252
#: 묶음 평균이 전체 가운데 값보다 (전체 표준편차 × 이 값) 이상 높/낮으면 낱말을 붙인다.
WORD_Z = 0.5
SIL_WEAK, SIL_OK = 0.25, 0.5
FEATURES = ("ret", "vol", "beta", "mdd")
WORDS = {
    "ret": ("수익률 높음", "수익률 낮음"),
    "vol": ("변동성 높음", "변동성 낮음"),
    "beta": ("시장 민감도 높음", "시장 민감도 낮음"),
    "mdd": ("최대 낙폭 작음", "최대 낙폭 큼"),          # 낙폭은 음수 — 값이 크면(0 에 가까우면) 작은 낙폭
}
ATTRIBUTION = "공공데이터포털 주식시세정보(금융위원회) · 총수익 지수 · 시장 지수는 우리 계산"
NOTICE = "묶음은 고른 기간에 따라 바뀝니다. 과거에 같이 움직였다고 앞으로도 그렇다는 보장은 없습니다. 투자 권유가 아닙니다."
DEFINITIONS = {
    "movement": "날마다의 수익률이 같이 오르내린 정도(상관)를 거리로 바꿔(상관이 1 이면 0 · −1 이면 2) 가까운 종목끼리 묶습니다",
    "profile": "연 수익률 · 연 변동성 · 시장 민감도(코스피가 1% 움직일 때 평균 몇 % 움직였나) · 최대 낙폭이 닮은 종목끼리 묶습니다",
    "silhouette": "자기 묶음과는 가깝고 다른 묶음과는 먼 정도(−1 ~ 1). 1 에 가까울수록 묶음이 또렷합니다",
    "map": "종목 사이 거리를 평면에 가장 잘 옮긴 그림입니다. 가로 · 세로 축 자체에는 뜻이 없고 점 사이 거리만 봅니다",
    "coverage": f"고른 기간 거래일의 {COVERAGE * 100:.0f}%보다 적게 있는 종목(상장 · 거래정지)은 뺍니다",
    "ari": "업종과 묶음이 얼마나 같은지(1 = 같음 · 0 = 우연 수준)",
}


def choices() -> Dict:
    """화면이 고르기 단추를 그릴 값 — 화면 코드에 대상 · 기간 · 방법 · 묶음 수를 따로 적지 않게(서버 한 곳)."""
    return {
        "universe": [{"key": k, "label": v["label"]} for k, v in UNIVERSES.items()],
        "period": [{"key": k, "label": PERIOD_TEXT[k].replace("지난 ", "")} for k in PERIODS],
        "method": [{"key": k, "label": ("같이 움직임" if k == "movement" else "위험 · 수익 특성")} for k in METHODS],
        "k": list(range(K_MIN, K_MAX + 1)),
    }


class ClusterError(Exception):
    def __init__(self, status: int, message: str, hint: str = ""):
        super().__init__(message)
        self.status = status
        self.message = message
        self.hint = hint

    def detail(self, admin: bool) -> Dict:
        out: Dict = {"message": self.message}
        if admin and self.hint:
            out["admin_hint"] = self.hint
        return out


# ══════════════════════════════════════════════════════════════════
# 1. 계산 — DB 없는 순수 함수(시험이 직접 부른다)
# ══════════════════════════════════════════════════════════════════

def quant_universe() -> List[Dict]:
    """자동매매 31종목 — 코드(6자리) · 이름 · 업종. 정본은 `stock.QUANT_STOCKS`."""
    from app.services.stock import QUANT_STOCKS

    return [{"code": s["symbol"].split(".")[0], "name": s["name"], "sector": s["sector"]} for s in QUANT_STOCKS]


def apply_coverage(px: pd.DataFrame, coverage: float = COVERAGE) -> Tuple[pd.DataFrame, List[Dict]]:
    """기간 거래일(행)의 coverage 보다 적게 있는 종목(열)을 까닭과 함께 뺀다."""
    have = px.notna().mean()
    keep = [c for c in px.columns if have[c] >= coverage]
    excluded = [{"code": c, "reason": f"기간 거래일의 {have[c] * 100:.0f}%만 있습니다(상장 · 거래정지 등)"}
                for c in px.columns if have[c] < coverage]
    return px[keep], excluded


def _check_k(k: Optional[int], n: int) -> Optional[int]:
    if not k:
        return None
    hi = min(K_MAX, n - 1)
    if not K_MIN <= k <= hi:
        raise ClusterError(422, f"묶음 수는 {K_MIN} ~ {max(hi, K_MIN)} 사이로 고르세요(종목 {n}개).")
    return int(k)


def _sign_fix(coords: np.ndarray) -> np.ndarray:
    """축마다 절댓값이 가장 큰 칸이 양수가 되게 — 같은 자료면 지도가 뒤집히지 않는다."""
    for j in range(coords.shape[1]):
        i = int(np.argmax(np.abs(coords[:, j])))
        if coords[i, j] < 0:
            coords[:, j] *= -1
    return coords


def _classical_mds(dist: np.ndarray) -> Tuple[np.ndarray, List[float]]:
    n = dist.shape[0]
    j = np.eye(n) - np.ones((n, n)) / n
    b = -0.5 * j @ (dist ** 2) @ j
    w, v = np.linalg.eigh(b)
    order = np.argsort(w)[::-1]
    w, v = w[order], v[:, order]
    pos = np.clip(w, 0, None)
    coords = _sign_fix(v[:, :2] * np.sqrt(pos[:2]))
    total = float(pos.sum())
    return coords, [float(pos[i] / total) if total > 0 else 0.0 for i in range(2)]


def _renumber(raw: Dict[str, int], coords: Dict[str, List[float]]) -> Dict[str, int]:
    """묶음 번호를 1 부터 — 큰 묶음 먼저, 같으면 지도 가로 평균이 작은 쪽 먼저(같은 입력이면 같은 번호)."""
    groups: Dict[int, List[str]] = {}
    for c, g in raw.items():
        groups.setdefault(int(g), []).append(c)
    order = sorted(groups, key=lambda g: (-len(groups[g]), float(np.mean([coords[c][0] for c in groups[g]])), min(groups[g])))
    new = {g: i + 1 for i, g in enumerate(order)}
    return {c: new[int(g)] for c, g in raw.items()}


def log_returns(px: pd.DataFrame) -> pd.DataFrame:
    return np.log(px).diff().iloc[1:]


def market_residuals(r: pd.DataFrame, bench: Optional[pd.Series]) -> Optional[pd.DataFrame]:
    """종목 일간 로그 수익률에서 시장 몫(절편 + 베타 × 시장 로그 수익률)을 뺀 나머지. 시장 자료가 모자라면 None."""
    if bench is None:
        return None
    m = np.log1p(bench.reindex(r.index))
    if m.notna().sum() < 20 or m.var() == 0:
        return None
    out = {}
    for c in r.columns:
        both = pd.concat([r[c], m], axis=1).dropna()
        if len(both) < 20:
            out[c] = r[c]
            continue
        y, x = both.iloc[:, 0], both.iloc[:, 1]
        beta = float(y.cov(x) / x.var())
        alpha = float(y.mean() - beta * x.mean())
        out[c] = r[c] - (alpha + beta * m)
    return pd.DataFrame(out)


def movement_clusters(px: pd.DataFrame, k: Optional[int] = None, bench: Optional[pd.Series] = None) -> Dict:
    """같이 움직인 묶음 — (시장 몫을 뺀) 수익률 상관 거리 · Ward 계층 군집 · 실루엣으로 k · MDS 지도."""
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform
    from sklearn.metrics import silhouette_samples, silhouette_score

    n = px.shape[1]
    k = _check_k(k, n)
    raw = log_returns(px)
    resid = market_residuals(raw, bench)
    corr = (resid if resid is not None else raw).corr(min_periods=20).fillna(0.0)
    dist = np.sqrt(np.clip(2.0 * (1.0 - corr.values), 0.0, None))
    np.fill_diagonal(dist, 0.0)
    z = linkage(squareform(dist, checks=False), method="ward")
    scores = []
    for kk in range(K_MIN, min(K_MAX, n - 1) + 1):
        lab = fcluster(z, kk, criterion="maxclust")
        if len(set(lab)) < 2:
            continue
        scores.append({"k": kk, "silhouette": round(float(silhouette_score(dist, lab, metric="precomputed")), 4)})
    if k is None:
        best = max(scores, key=lambda s: (s["silhouette"], -s["k"]))     # 같으면 작은 k
        k_use, auto = best["k"], True
    else:
        k_use, auto = k, False
    lab = fcluster(z, k_use, criterion="maxclust")
    sil = silhouette_samples(dist, lab, metric="precomputed") if len(set(lab)) > 1 else np.zeros(n)
    xy, explained = _classical_mds(dist)
    coords = {c: [round(float(x), 6), round(float(y), 6)] for c, (x, y) in zip(corr.columns, xy)}
    labels = _renumber(dict(zip(corr.columns, lab)), coords)
    return {"k": len(set(lab)), "k_auto": auto, "k_scores": scores, "labels": labels, "coords": coords,
            "explained": [round(e, 4) for e in explained], "corr": corr, "market_removed": resid is not None,
            "dist": pd.DataFrame(dist, index=corr.index, columns=corr.columns),
            "silhouette": {c: round(float(s), 4) for c, s in zip(corr.columns, sil)},
            "silhouette_mean": round(float(np.mean(sil)), 4)}


def features(px: pd.DataFrame, bench: Optional[pd.Series]) -> pd.DataFrame:
    """종목마다 연 수익률(기하) · 연 변동성 · 베타(코스피 총수익 일 수익률) · 최대 낙폭 — 소수(0.1 = 10%)."""
    simple = px.pct_change(fill_method=None).iloc[1:]
    rows = {}
    for c in px.columns:
        s = px[c].dropna()
        n = len(s)
        ann = (s.iloc[-1] / s.iloc[0]) ** (TRADING_DAYS / max(n - 1, 1)) - 1 if n > 1 else math.nan
        vol = float(simple[c].std() * math.sqrt(TRADING_DAYS))
        beta = math.nan
        if bench is not None:
            both = pd.concat([simple[c], bench.reindex(simple.index)], axis=1).dropna()
            if len(both) >= 20 and both.iloc[:, 1].var() > 0:
                beta = float(both.iloc[:, 0].cov(both.iloc[:, 1]) / both.iloc[:, 1].var())
        mdd = float((s / s.cummax() - 1).min()) if n else math.nan
        rows[c] = {"ret": float(ann), "vol": vol, "beta": beta, "mdd": mdd}
    return pd.DataFrame.from_dict(rows, orient="index")[list(FEATURES)]


def profile_clusters(feat: pd.DataFrame, k: Optional[int] = None) -> Dict:
    """위험 · 수익 특성 묶음 — 표준화 KMeans · 실루엣으로 k · PCA 지도. 값이 비는 특성(시장 지수가 없을 때 베타)은 뺀다."""
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    from sklearn.metrics import silhouette_samples, silhouette_score

    used = [c for c in FEATURES if feat[c].notna().all()]
    n = len(feat)
    k = _check_k(k, n)
    sd = feat[used].std(ddof=0).replace(0, 1.0)
    x = ((feat[used] - feat[used].mean()) / sd).values
    fits: Dict[int, np.ndarray] = {}
    scores = []
    for kk in range(K_MIN, min(K_MAX, n - 1) + 1):
        lab = KMeans(n_clusters=kk, n_init=10, random_state=42).fit(x).labels_
        if len(set(lab)) < 2:
            continue
        fits[kk] = lab
        scores.append({"k": kk, "silhouette": round(float(silhouette_score(x, lab)), 4)})
    if k is None:
        best = max(scores, key=lambda s: (s["silhouette"], -s["k"]))
        k_use, auto = best["k"], True
    else:
        k_use, auto = k, False
    lab = fits.get(k_use)
    if lab is None:
        lab = KMeans(n_clusters=k_use, n_init=10, random_state=42).fit(x).labels_
    sil = silhouette_samples(x, lab) if len(set(lab)) > 1 else np.zeros(n)
    pca = PCA(n_components=min(2, x.shape[1]), svd_solver="full").fit(x)
    xy = _sign_fix(pca.transform(x))
    if xy.shape[1] < 2:
        xy = np.c_[xy, np.zeros(n)]
    coords = {c: [round(float(a), 6), round(float(b), 6)] for c, (a, b) in zip(feat.index, xy)}
    labels = _renumber(dict(zip(feat.index, lab)), coords)
    return {"k": len(set(lab)), "k_auto": auto, "k_scores": scores, "labels": labels, "coords": coords,
            "explained": [round(float(e), 4) for e in pca.explained_variance_ratio_], "used_features": used,
            "silhouette": {c: round(float(s), 4) for c, s in zip(feat.index, sil)},
            "silhouette_mean": round(float(np.mean(sil)), 4)}


def cluster_words(feat: pd.DataFrame, labels: Dict[str, int]) -> Dict[int, List[str]]:
    """묶음마다 특성 낱말 — 묶음 평균이 전체 가운데 값보다 (표준편차 × WORD_Z) 이상 높/낮으면."""
    out: Dict[int, List[str]] = {}
    for g in sorted(set(labels.values())):
        members = [c for c, v in labels.items() if v == g]
        words = []
        for f in FEATURES:
            col = feat[f].dropna()
            if col.empty or col.std(ddof=0) == 0:
                continue
            z = (feat.loc[members, f].mean() - col.median()) / col.std(ddof=0)
            if z >= WORD_Z:
                words.append(WORDS[f][0])
            elif z <= -WORD_Z:
                words.append(WORDS[f][1])
        out[g] = words or ["전체 평균에 가까움"]
    return out


def sector_match(labels: Dict[str, int], sectors: Dict[str, str], names: Dict[str, str]) -> Dict:
    """업종과 견줌 — 조정 랜드 지수 · 업종마다 많은 쪽 묶음과 다른 묶음에 든 종목(둘 이상인 업종만)."""
    from sklearn.metrics import adjusted_rand_score

    codes = [c for c in labels if c in sectors]
    ari = float(adjusted_rand_score([sectors[c] for c in codes], [labels[c] for c in codes])) if len(codes) > 1 else None
    by_sector: Dict[str, List[str]] = {}
    for c in codes:
        by_sector.setdefault(sectors[c], []).append(c)
    split = []
    for sec, cs in sorted(by_sector.items()):
        if len(cs) < 2:
            continue
        counts: Dict[int, int] = {}
        for c in cs:
            counts[labels[c]] = counts.get(labels[c], 0) + 1
        major = max(counts, key=lambda g: (counts[g], -g))
        split += [{"code": c, "name": names.get(c, c), "sector": sec, "cluster": labels[c], "major_cluster": major}
                  for c in sorted(cs) if labels[c] != major]
    table = []
    for g in sorted(set(labels.values())):
        cnt: Dict[str, int] = {}
        for c in codes:
            if labels[c] == g:
                cnt[sectors[c]] = cnt.get(sectors[c], 0) + 1
        table.append({"cluster": g, "sectors": dict(sorted(cnt.items(), key=lambda t: (-t[1], t[0])))})
    return {"ari": None if ari is None else round(ari, 4), "split": split, "table": table}


# ══════════════════════════════════════════════════════════════════
# 2. 읽기 — 수집 DB(읽기 전용) → 응답
# ══════════════════════════════════════════════════════════════════

_USER_DB_DOWN = "시세 자료를 지금 읽을 수 없습니다. 잠시 뒤 다시 시도해 주세요."


def _open() -> sqlite3.Connection:
    path = collector_db.db_path()
    if path is None:
        raise ClusterError(503, _USER_DB_DOWN, "수집 DB 가 없다 — COLLECTOR_DB_PATH 또는 data/collector/market.sqlite3 "
                                              "(python scripts/daily_update.py status)")
    try:
        return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as e:
        raise ClusterError(503, _USER_DB_DOWN, f"수집 DB 를 열지 못했다: {e}") from None


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _months_before(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - months, 12)
    last = (date(y + (m == 11), (m + 1) % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m + 1, min(d.day, last))


def _u401(conn: sqlite3.Connection) -> List[Dict]:
    if not _has_table(conn, "intraday_universe"):
        return []
    rows = conn.execute("SELECT symbol, itms_nm, market FROM intraday_universe WHERE version=? AND market != 'ETF' "
                        "ORDER BY rank, symbol", (U401_VERSION,)).fetchall()
    return [{"code": s, "name": nm or s, "sector": "", "market": mk} for s, nm, mk in rows]


def _prices(conn: sqlite3.Connection, codes: List[str], lo: str, hi: str) -> pd.DataFrame:
    rows: List[Tuple[str, str, float]] = []
    for i in range(0, len(codes), 400):                  # 자리표시자 수를 넉넉히 아래로
        part = codes[i:i + 400]
        q = (f"SELECT bas_dt, srtn_cd, tr_index FROM price_total_return WHERE srtn_cd IN ({','.join('?' * len(part))}) "
             "AND bas_dt >= ? AND bas_dt <= ? AND tr_index > 0")
        rows += conn.execute(q, (*part, lo, hi)).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["d", "c", "v"])
    df["d"] = df["d"].str.slice(0, 4) + "-" + df["d"].str.slice(4, 6) + "-" + df["d"].str.slice(6, 8)
    return df.pivot(index="d", columns="c", values="v").sort_index()


def _bench(conn: sqlite3.Connection, lo: str, hi: str) -> Optional[pd.Series]:
    if not _has_table(conn, "benchmark_index"):
        return None
    rows = conn.execute("SELECT bas_dt, ret FROM benchmark_index WHERE mrkt_ctg='KOSPI' AND variant='TR' "
                        "AND bas_dt >= ? AND bas_dt <= ? AND ret IS NOT NULL ORDER BY bas_dt", (lo, hi)).fetchall()
    if not rows:
        return None
    return pd.Series({f"{d[:4]}-{d[4:6]}-{d[6:8]}": float(r) for d, r in rows})


def _unavailable(universe: Dict, reason: str, admin: bool, hint: str) -> Dict:
    out = {"available": False, "universe": universe, "reason": reason, "source": ATTRIBUTION, "notice": NOTICE,
           "choices": choices()}
    if admin:
        out["admin_hint"] = hint
    return out


def _sil_text(s: float) -> str:
    """실루엣 낱말 — 2026-10-14 실측: 31종목 3년은 업종대로 8묶음이 나왔는데 실루엣 0.14 였다. 「묶음이 없다」 가 아니라
    「경계가 흐릿하다(두 묶음 사이에 걸친 종목이 많다)」 가 맞는 글이다 — 그래서 같은 묶음 · 다른 묶음 평균 상관을 함께 보인다."""
    if s >= SIL_OK:
        return "묶음이 또렷하게 나뉩니다"
    if s >= SIL_WEAK:
        return "묶음이 어느 정도 나뉩니다 — 경계에 있는 종목이 있습니다"
    return "묶음 사이 경계가 흐릿합니다 — 두 묶음 사이에 걸친 종목이 많습니다"


def separation(corr: pd.DataFrame, labels: Dict[str, int]) -> Dict[str, Optional[float]]:
    """같은 묶음 종목 쌍 · 다른 묶음 종목 쌍의 평균 상관(날 수익률) — 실루엣보다 읽기 쉬운 「묶음이 뜻이 있나」."""
    codes = list(corr.index)
    lab = np.array([labels[c] for c in codes])
    m = corr.values
    iu = np.triu_indices(len(codes), k=1)
    same = lab[iu[0]] == lab[iu[1]]
    vals = m[iu]
    w = float(vals[same].mean()) if same.any() else None
    b = float(vals[~same].mean()) if (~same).any() else None
    return {"within": None if w is None else round(w, 3), "between": None if b is None else round(b, 3)}


def read_clusters(universe: str, period: str, method: str, k: int = 0, admin: bool = False) -> Dict:
    """`GET /api/clusters` — 고른 종목 묶음 · 기간 · 방법으로 군집화한 결과."""
    if universe not in UNIVERSES:
        raise ClusterError(422, "대상은 quant31(자동매매 31종목) 또는 u401(분봉 수집 종목)입니다.")
    if period not in PERIODS:
        raise ClusterError(422, "기간은 1y · 2y · 3y 가운데 하나입니다.")
    if method not in METHODS:
        raise ClusterError(422, "방법은 movement(같이 움직임) 또는 profile(위험 · 수익 특성)입니다.")
    uni = {"key": universe, **UNIVERSES[universe]}
    conn = _open()
    try:
        stocks = quant_universe() if universe == "quant31" else _u401(conn)
        uni["n_requested"] = len(stocks)
        if not _has_table(conn, "price_total_return"):
            raise ClusterError(503, _USER_DB_DOWN, "price_total_return 표가 없다 — "
                                                   "python scripts/daily_update.py run --only total_return")
        last = conn.execute("SELECT MAX(bas_dt) FROM price_total_return").fetchone()[0]
        if not last or not stocks:
            return _unavailable(uni, "묶을 시세 자료가 아직 없습니다. 다음 정기 수집 뒤에 다시 보세요.", admin,
                                "price_total_return 이 비었거나 대상 목록이 비었다 — python scripts/daily_update.py status")
        hi_d = date(int(last[:4]), int(last[4:6]), int(last[6:8]))
        lo = _months_before(hi_d, PERIODS[period]).strftime("%Y%m%d")
        px = _prices(conn, [s["code"] for s in stocks], lo, last)
        bench = _bench(conn, lo, last)
    finally:
        conn.close()

    names = {s["code"]: s["name"] for s in stocks}
    sectors = {s["code"]: s["sector"] for s in stocks if s.get("sector")}
    markets = {s["code"]: s.get("market", "") for s in stocks}
    missing = [{"code": s["code"], "reason": "수집 시세에 없습니다"} for s in stocks if px.empty or s["code"] not in px.columns]
    kept, short = apply_coverage(px) if not px.empty else (px, [])
    excluded = [{**e, "name": names.get(e["code"], e["code"])} for e in missing + short]
    if kept.shape[1] < MIN_STOCKS:
        return {**_unavailable(uni, f"기간에 자료가 충분한 종목이 {MIN_STOCKS}개보다 적어 묶을 수 없습니다.", admin,
                               "대상 종목의 price_total_return 줄을 확인한다"), "excluded": excluded}

    feat = features(kept, bench)
    res = movement_clusters(kept, k or None, bench) if method == "movement" else profile_clusters(feat, k or None)
    # 「가장 같이 움직인 종목」 · 묶음 안 평균 상관은 두 방법 모두 날 수익률 상관(사람이 아는 「같이 오르내림」)으로 센다
    corr = log_returns(kept).corr(min_periods=20).fillna(0.0)
    labels = res["labels"]
    words = cluster_words(feat, labels)

    def pct(v, nd=1):
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v) * 100, nd)

    points = []
    for c in kept.columns:
        others = corr.loc[c].drop(c)
        near = others.idxmax() if len(others) else None
        points.append({
            "code": c, "name": names.get(c, c), "sector": sectors.get(c, ""), "market": markets.get(c, ""),
            "cluster": labels[c], "x": res["coords"][c][0], "y": res["coords"][c][1], "silhouette": res["silhouette"][c],
            "nearest": None if near is None else {"code": near, "name": names.get(near, near), "corr": round(float(others[near]), 3)},
            "ret": pct(feat.loc[c, "ret"]), "vol": pct(feat.loc[c, "vol"]),
            "beta": None if math.isnan(feat.loc[c, "beta"]) else round(float(feat.loc[c, "beta"]), 2),
            "mdd": pct(feat.loc[c, "mdd"]),
        })
    clusters = []
    for g in sorted(set(labels.values())):
        mem = [c for c in kept.columns if labels[c] == g]
        sub = corr.loc[mem, mem].values
        corr_in = float((sub.sum() - len(mem)) / (len(mem) * (len(mem) - 1))) if len(mem) > 1 else None
        clusters.append({
            "id": g, "size": len(mem), "words": words[g],
            "members": [{"code": c, "name": names.get(c, c), "sector": sectors.get(c, "")} for c in sorted(mem, key=lambda c: names.get(c, c))],
            "summary": {"ret": pct(feat.loc[mem, "ret"].mean()), "vol": pct(feat.loc[mem, "vol"].mean()),
                        "beta": None if feat.loc[mem, "beta"].isna().all() else round(float(feat.loc[mem, "beta"].mean()), 2),
                        "mdd": pct(feat.loc[mem, "mdd"].mean()),
                        "corr_in": None if corr_in is None else round(corr_in, 3)},
        })
    sm = sector_match(labels, sectors, names) if UNIVERSES[universe]["has_sector"] else None
    matrix = None
    if len(kept.columns) <= MATRIX_MAX:
        # 묶음 차례(같은 묶음 안은 이름 차례)로 줄 세운 날 수익률 상관 — 같은 묶음이 대각선 둘레에 네모로 모인다
        order = sorted(kept.columns, key=lambda c: (labels[c], names.get(c, c)))
        matrix = {"order": order, "values": [[round(float(corr.loc[a, b]), 2) for b in order] for a in order]}

    lo_iso = kept.index[0]
    hi_iso = kept.index[-1]
    sents = [f"{uni['label']} 가운데 {kept.shape[1]}종목을 {PERIOD_TEXT[period]}({lo_iso} ~ {hi_iso}) 총수익 일간 수익률로 묶었습니다."
             + (f" {len(excluded)}종목은 자료가 모자라 뺐습니다(아래 목록)." if excluded else "")]
    if method == "movement":
        sents.append("시장 전체(코스피)가 같이 움직인 몫을 빼고, 남은 움직임이 서로 같이 오르내린 종목끼리 묶었습니다."
                     if res["market_removed"] else
                     "시장 지수 자료가 없어 시장 몫을 빼지 못한 채, 서로 같이 오르내린 종목끼리 묶었습니다.")
    else:
        sents.append("연 수익률 · 변동성 · 시장 민감도 · 최대 낙폭이 닮은 종목끼리 묶었습니다.")
    sep = separation(corr, labels)
    sents.append(f"묶음 수 {res['k']}개는 {'실루엣 점수가 가장 높은 값' if res['k_auto'] else '고른 값'}입니다. "
                 f"평균 실루엣 {res['silhouette_mean']:.2f} — {_sil_text(res['silhouette_mean'])}.")
    if sep["within"] is not None and sep["between"] is not None:
        sents.append(f"같은 묶음 종목끼리는 날마다의 수익률 상관이 평균 {sep['within']:.2f}, "
                     f"다른 묶음 종목끼리는 {sep['between']:.2f}입니다.")
    big = max(clusters, key=lambda c: c["size"])
    sents.append(f"가장 큰 묶음 {big['id']}({big['size']}종목)은 {' · '.join(big['words'])}입니다.")
    if sm is not None:
        pure = []
        for row in sm["table"]:
            size = sum(row["sectors"].values())
            if size >= 2:
                top, cnt = next(iter(row["sectors"].items()))
                if cnt / size >= 2 / 3:
                    pure.append(f"묶음 {row['cluster']}({top} {cnt}/{size})")
        if pure:
            sents.append(f"업종이 같은 종목끼리 모인 묶음: {', '.join(pure)}.")
        if sm["split"]:
            ex = ", ".join(f"{s['name']}({s['sector']})" for s in sm["split"][:5])
            sents.append(f"같은 업종인데 다른 묶음에 든 종목: {ex}" + (f" 외 {len(sm['split']) - 5}종목" if len(sm["split"]) > 5 else "") + ".")
        else:
            sents.append("같은 업종 종목은 모두 같은 묶음에 들었습니다.")
    if method == "movement":
        sents.append("서로 다른 묶음의 종목은 지난 기간에 덜 같이 움직였습니다 — 분산을 생각할 때 참고만 하세요.")
    else:
        sents.append("같은 묶음은 지난 기간의 위험 · 수익 모습이 닮았다는 뜻입니다.")
    if "used_features" in res and len(res["used_features"]) < len(FEATURES):
        sents.append("시장 지수 자료가 없어 시장 민감도는 빼고 묶었습니다.")
    sents.append(NOTICE.split(" 투자 권유")[0])

    return {
        "available": True,
        "universe": uni,
        "period": {"key": period, "text": PERIOD_TEXT[period], "from": lo_iso, "to": hi_iso, "days": int(len(kept))},
        "method": {"key": method, "label": METHODS[method]},
        "as_of": hi_iso,
        "k": res["k"], "k_auto": res["k_auto"], "k_scores": res["k_scores"],
        "silhouette_mean": res["silhouette_mean"],
        "separation": sep,
        "market_removed": res.get("market_removed"),
        "map": {"kind": "mds" if method == "movement" else "pca", "explained": res["explained"]},
        "clusters": clusters,
        "points": points,
        "excluded": excluded,
        "sector_match": sm,
        "matrix": matrix,
        "thresholds": {"coverage": COVERAGE, "k_min": K_MIN, "k_max": K_MAX, "word_z": WORD_Z,
                       "silhouette_weak": SIL_WEAK, "silhouette_ok": SIL_OK, "matrix_max": MATRIX_MAX},
        "definitions": DEFINITIONS,
        "choices": choices(),
        "sentences": sents,
        "source": ATTRIBUTION,
        "notice": NOTICE,
    }
