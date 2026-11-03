"""이름표 정밀도 표본 — 추출(draw)과 채점(score) (할 일 ①-23 C 조각 · 근거 답 품질 보고서 v0.2 항목).

공시 · 뉴스에 붙은 종목 · 주제 이름표가 **맞는 비율(정밀도)** 을 재기 위한 도구다. 지금까지는 「붙은 비율」(주제 이름표가 공시의
70.3%)만 있었다. 판정은 **사람이** 한다 — 이 도구는 표본을 뽑고 점수를 낼 뿐, 맞고 틀림을 정하지 않는다(LLM 판정은
믿기 어렵다 · 근거 답 품질 보고서 5절 3번).

    python scripts/tagging_sample.py draw                   # → docs/_local/이름표-표본200/표본_seed<시드>.tsv
    python scripts/tagging_sample.py draw --seed 7 --news-symbol 60
    python scripts/tagging_sample.py score 표본_seed20261102.tsv            # 판정 열을 채운 뒤
    python scripts/tagging_sample.py score 표본_seed20261102.tsv --partial  # 일부만 채운 중간 확인

어디서 읽나
-----------
이름표는 수집 DB(``market.sqlite3``)가 아니라 **검색 색인** ``data/collector/search.sqlite3`` 의 ``doc`` · ``doc_tag`` 에 있다
(``collector/search_index.py`` 머리말 — 이름표는 계산한 것이라 받은 자료와 파일을 나눴다). 앱이 사용자에게 내놓는 이름표가
바로 이 파일의 것이므로 정밀도도 이 파일로 잰다. **읽기 전용 연결**(``mode=ro`` + ``query_only``)로만 열고, 이 도구는 DB 에
아무것도 쓰지 않는다. ``collector.search_index.connect()`` 는 스키마를 쓰므로 일부러 쓰지 않았다.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import random
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collector import tagging  # noqa: E402
from collector.console import utf8_stdio  # noqa: E402

DEFAULT_DB = ROOT / "data" / "collector" / "search.sqlite3"
DEFAULT_OUT_DIR = ROOT / "docs" / "_local" / "이름표-표본200"  # git 밖 — 표본에 뉴스 제목 · 원문 주소가 들어 있어 올리지 않는다
DEFAULT_SEED = 20261102           # 뽑은 날 — 고정 시드(같은 DB · 같은 인자면 같은 표본)
TARGET = 0.9                      # 설계서 ① 인수 기준 6 — 이름표 정밀도 목표
SUSPECT_TOPICS = ("소송·제재",)    # 의심 종류 — 점검표 DF-128: 30일 뉴스의 13% 가 이 하나로만 붙는다
SUSPECT_MIN = 15                  # 의심 종류는 구분마다 적어도 이만큼(층 크기가 작으면 전부)
FLOOR_PER_STRATUM = 2             # 모든 층에 적어도 이만큼(층 크기가 작으면 전부) — 한 종류가 빠지지 않게
SUBTITLE_MAX = 160                # 부제 글자 수 — 본문은 넣지 않는다(뉴스 이름표는 제목 + 부제에서 붙는다)

KIND_DISCLOSURE = "공시"
KIND_NEWS = "뉴스"
FRAME_TOPIC = "주제"              # 주제틀 — 주제 이름표가 붙은 글을 주제 종류별로 층화해 뽑는다
FRAME_SYMBOL = "종목"             # 종목틀 — 종목 이름표가 붙은 뉴스를 단순 무작위로 뽑는다
NA = "해당없음"                   # 그 줄이 재는 이름표가 아닌 칸 — 미리 채워 둔다(판정하지 않는다)
JUDGE_VALUES = ("맞음", "부분", "틀림")

HEADER = ["표본ID", "구분", "원천ID", "날짜", "제목", "부제", "종목 이름표", "주제 이름표",
          "종목판정", "주제판정", "메모", "층", "층크기", "원문주소"]
REQUIRED_SCORE_COLUMNS = ("표본ID", "구분", "층", "층크기", "종목판정", "주제판정")

Z95 = 1.959964  # 정규분포 97.5% 분위수


# ==================================================
# 1. 읽기 전용 연결
# ==================================================
def open_readonly(path: Path) -> sqlite3.Connection:
    """검색 색인을 **읽기 전용**으로 연다 — INSERT 는 ``OperationalError`` 로 막힌다."""
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"검색 색인이 없다: {p} — python -m collector.search_index build")
    conn = sqlite3.connect(p.as_uri() + "?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"doc", "doc_tag"} <= have:
        conn.close()
        raise ValueError(f"검색 색인이 아니다(doc · doc_tag 표가 없다): {p}")
    return conn


def read_meta(conn: sqlite3.Connection) -> Dict[str, str]:
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "meta" not in have:
        return {}
    return {r[0]: r[1] for r in conn.execute("SELECT key, value FROM meta")}


def current_rules_fingerprint() -> Optional[str]:
    """지금 코드의 이름표 규칙 지문 — 색인을 만든 뒤 규칙이 바뀌었는지 보려고 쓴다. 못 구하면 None."""
    try:
        from collector import search_index
        return search_index.rules_fingerprint()
    except Exception:  # noqa: BLE001 — 지문은 참고용이다. 못 구해도 뽑기는 계속한다.
        return None


# ==================================================
# 2. 층 배정 — 층화 표본
# ==================================================
def allocate(sizes: Dict[str, int], n: int, suspects: Sequence[str] = (), floor: int = FLOOR_PER_STRATUM,
             suspect_min: int = SUSPECT_MIN) -> Dict[str, int]:
    """층(주제)별 크기 → 층마다 몇 건 뽑을지. 합이 ``n`` 이 되게 나눈다(층 크기를 넘기지 않는다).

    1) **바닥** — 모든 층에 ``floor`` 건(층이 작으면 전부). 건수가 적은 주제도 표본에서 빠지지 않는다.
    2) **의심 최소** — 의심 종류(``suspects``)는 ``suspect_min`` 건까지 올린다. 한 종류가 모집단의 큰 몫을 차지하는데
       (뉴스 주제의 31% 가 소송·제재) 바닥 2건으로는 정밀도가 낮은지 아닌지 볼 수 없다.
    3) **나머지** — 층 크기의 제곱근에 비례해 나눈다. 모집단 비례로 나누면 공시의 「지분」 (28%) 이 표본을 삼키고,
       균등으로 나누면 큰 층의 정밀도가 불확실해진다. 제곱근 비례는 그 중간이다. 층을 꽉 채운 몫은 남은 층에 다시 나눈다
       (물 채우기) · 소수는 최대 잔여법(동률은 이름순).

    비례가 아니므로 전체 정밀도는 **층 크기로 가중**해 낸다(``score``).
    """
    keys = sorted(k for k, v in sizes.items() if v > 0)
    if not keys or n <= 0:
        return {k: 0 for k in keys}
    if n >= sum(sizes[k] for k in keys):
        return {k: sizes[k] for k in keys}

    alloc = {k: 0 for k in keys}
    f = floor
    while f > 0 and sum(min(sizes[k], f) for k in keys) > n:
        f -= 1
    if f == 0:  # 층마다 1건도 못 줄 만큼 적다 — 큰 층부터 1건씩
        for k in sorted(keys, key=lambda x: (-sizes[x], x))[:n]:
            alloc[k] = 1
        return alloc
    for k in keys:
        alloc[k] = min(sizes[k], f)

    for k in sorted(s for s in suspects if s in alloc):
        add = min(min(sizes[k], suspect_min) - alloc[k], n - sum(alloc.values()))
        if add > 0:
            alloc[k] += add

    remaining = n - sum(alloc.values())
    while remaining > 0:
        open_keys = [k for k in keys if alloc[k] < sizes[k]]
        if not open_keys:
            break
        wsum = sum(math.sqrt(sizes[k]) for k in open_keys)
        ideal = {k: remaining * math.sqrt(sizes[k]) / wsum for k in open_keys}
        full = [k for k in open_keys if ideal[k] >= sizes[k] - alloc[k]]
        if full:  # 몫이 층 크기를 넘는 층은 꽉 채우고 남은 몫을 다시 나눈다
            for k in full:
                remaining -= sizes[k] - alloc[k]
                alloc[k] = sizes[k]
            continue
        base = {k: int(ideal[k]) for k in open_keys}
        left = remaining - sum(base.values())
        for k in sorted(open_keys, key=lambda x: (-(ideal[x] - base[x]), x))[:left]:
            base[k] += 1
        for k in open_keys:
            alloc[k] += base[k]
        remaining = 0
    return alloc


# ==================================================
# 3. 뽑기 (draw)
# ==================================================
@dataclass(frozen=True)
class Pick:
    rid: int
    kind: str       # 공시 | 뉴스
    frame: str      # 주제 | 종목
    stratum: str    # 주제 이름 | 뉴스
    size: int       # 층 크기(뽑을 때 모집단 수)


def _chunks(items: Sequence, size: int = 500) -> Iterable[Sequence]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def topic_strata(conn: sqlite3.Connection, kind_db: str) -> Dict[str, int]:
    """구분(disclosure | news)의 주제별 문서 수 — 층 크기."""
    sql = ("SELECT t.tag, COUNT(*) FROM doc_tag t JOIN doc d ON d.rid = t.rid "
           "WHERE t.tag_type = 'topic' AND d.kind = ? GROUP BY t.tag")
    return {r[0]: r[1] for r in conn.execute(sql, (kind_db,))}


def topic_rids(conn: sqlite3.Connection, kind_db: str, topic: str) -> List[int]:
    sql = ("SELECT t.rid FROM doc_tag t JOIN doc d ON d.rid = t.rid "
           "WHERE t.tag_type = 'topic' AND t.tag = ? AND d.kind = ? ORDER BY t.rid")
    return [r[0] for r in conn.execute(sql, (topic, kind_db))]


def symbol_news_rids(conn: sqlite3.Connection) -> List[int]:
    sql = ("SELECT DISTINCT t.rid FROM doc_tag t JOIN doc d ON d.rid = t.rid "
           "WHERE t.tag_type = 'symbol' AND d.kind = 'news' ORDER BY t.rid")
    return [r[0] for r in conn.execute(sql)]


def _fetch_docs(conn: sqlite3.Connection, rids: Sequence[int]) -> Dict[int, sqlite3.Row]:
    out: Dict[int, sqlite3.Row] = {}
    for part in _chunks(list(rids)):
        q = ",".join("?" * len(part))
        for r in conn.execute(f"SELECT rid, doc_id, kind, title, summary, url, published FROM doc "
                              f"WHERE rid IN ({q})", tuple(part)):
            out[r["rid"]] = r
    return out


def _fetch_tags(conn: sqlite3.Connection, rids: Sequence[int]) -> Dict[int, List[Tuple[str, str, str]]]:
    out: Dict[int, List[Tuple[str, str, str]]] = {}
    for part in _chunks(list(rids)):
        q = ",".join("?" * len(part))
        for r in conn.execute(f"SELECT rid, tag_type, tag, method FROM doc_tag "
                              f"WHERE rid IN ({q}) AND tag_type IN ('topic','symbol') ORDER BY rid, rowid",
                              tuple(part)):
            out.setdefault(r["rid"], []).append((r["tag_type"], r["tag"], r["method"]))
    return out


def _corp_names(conn: sqlite3.Connection, codes: Sequence[str]) -> Dict[str, str]:
    """종목 코드 → 회사 이름(공시에 나온 가장 최근 이름). 같은 색인의 공시 문서에서 얻는다."""
    out: Dict[str, str] = {}
    for part in _chunks(sorted(set(codes)), 200):
        q = ",".join("?" * len(part))
        # MAX(published) 와 함께 고른 bare column 은 그 최댓값 행의 값이다(SQLite 규칙) — 가장 최근 이름
        sql = (f"SELECT stock_code, corp_name, MAX(published) FROM doc "
               f"WHERE kind = 'disclosure' AND corp_name <> '' AND stock_code IN ({q}) GROUP BY stock_code")
        for r in conn.execute(sql, tuple(part)):
            out[r[0]] = r[1]
    return out


def _clean(text: str) -> str:
    """TSV 한 칸에 들어가도록 탭 · 줄바꿈을 공백으로."""
    return re.sub(r"[\t\r\n]+", " ", text or "").strip()


def _in_text(word: str, text: str) -> bool:
    """이름표 규칙과 같은 방식(NFKC · 공백 빼기)으로 낱말이 글에 있나."""
    w = tagging._squash(word)  # noqa: SLF001 — 규칙과 정규화가 어긋나지 않게 같은 함수를 쓴다
    return bool(w) and w in tagging._squash(text)  # noqa: SLF001


def draw_sample(conn: sqlite3.Connection, *, seed: int = DEFAULT_SEED, n_disclosure: int = 100, n_news: int = 100,
                n_news_symbol: int = 40, suspects: Sequence[str] = SUSPECT_TOPICS, suspect_min: int = SUSPECT_MIN,
                floor: int = FLOOR_PER_STRATUM) -> Tuple[List[Dict[str, str]], Dict]:
    """표본 줄(TSV 한 줄 = dict)과 뽑기 기록(곁 파일용)을 돌려준다.

    표본틀 둘 — ① 주제틀: 주제 이름표가 붙은 공시(``n_disclosure``)와 뉴스(``n_news - n_news_symbol``)를 주제 종류별로
    층화해 뽑는다. ② 종목틀: 종목 이름표가 붙은 뉴스 ``n_news_symbol`` 건을 단순 무작위로 뽑는다. 틀을 나눈 까닭은
    주제가 붙은 뉴스 4,978건 가운데 종목 이름표가 있는 것이 1,074건(22%)뿐이라 주제로만 뽑으면 뉴스 종목 판정이 20건
    남짓이어서다. 공시 종목은 DART 의 종목 코드 칸을 그대로 옮긴 것이라 판정하지 않는다.
    """
    if n_news_symbol < 0 or n_news_symbol > n_news:
        raise ValueError(f"뉴스 종목틀({n_news_symbol})은 0 이상 뉴스 전체({n_news}) 이하여야 한다")
    rng = random.Random(seed)
    chosen: Dict[int, Pick] = {}
    plan: Dict[str, Dict] = {}

    # 한 문서가 두 층에 걸리면(주제가 둘 붙은 글) 먼저 뽑힌 층에만 둔다 — 작은 층을 먼저 뽑아 작은 층이 비지 않게 한다.
    for label, kind_db, n in ((KIND_DISCLOSURE, "disclosure", n_disclosure), (KIND_NEWS, "news", n_news - n_news_symbol)):
        sizes = topic_strata(conn, kind_db)
        alloc = allocate(sizes, n, suspects, floor, suspect_min)
        strata: Dict[str, Dict[str, int]] = {}
        for topic in sorted(alloc, key=lambda t: (sizes[t], t)):
            k = alloc[topic]
            got = 0
            if k > 0:
                cand = [r for r in topic_rids(conn, kind_db, topic) if r not in chosen]
                take = rng.sample(cand, min(k, len(cand)))
                for r in take:
                    chosen[r] = Pick(r, label, FRAME_TOPIC, topic, sizes[topic])
                got = len(take)
            strata[topic] = {"층크기": sizes[topic], "배정": k, "뽑힘": got}
        plan[f"{label}/{FRAME_TOPIC}"] = {"요청": n, "뽑힘": sum(v["뽑힘"] for v in strata.values()), "층": strata}

    if n_news_symbol > 0:
        pool = symbol_news_rids(conn)
        cand = [r for r in pool if r not in chosen]
        take = rng.sample(cand, min(n_news_symbol, len(cand)))
        for r in take:
            chosen[r] = Pick(r, KIND_NEWS, FRAME_SYMBOL, KIND_NEWS, len(pool))
        plan[f"{KIND_NEWS}/{FRAME_SYMBOL}"] = {"요청": n_news_symbol, "뽑힘": len(take), "층크기": len(pool)}

    picks = sorted(chosen.values(), key=lambda p: p.rid)
    rng.shuffle(picks)  # 같은 주제가 줄줄이 나오면 판정이 쏠린다 — 섞는다(시드 고정이라 같은 순서)

    docs = _fetch_docs(conn, [p.rid for p in picks])
    tags = _fetch_tags(conn, [p.rid for p in picks])
    sym_codes = [t[1] for p in picks if p.frame == FRAME_SYMBOL for t in tags.get(p.rid, []) if t[0] == "symbol"]
    names = _corp_names(conn, sym_codes) if sym_codes else {}

    rows: List[Dict[str, str]] = []
    subtitle_marked = 0
    for i, p in enumerate(picks, 1):
        d = docs[p.rid]
        title, summary = d["title"] or "", d["summary"] or ""
        sym_cell, topic_cell, sym_judge, topic_judge = "", "", NA, NA
        by_subtitle = False
        if p.frame == FRAME_TOPIC:
            method = next((t[2] for t in tags.get(p.rid, []) if t[0] == "topic" and t[1] == p.stratum), "")
            word = method.split(":", 1)[1] if method.startswith("rule:") else ""
            topic_cell = f"{p.stratum}({word})" if word else p.stratum
            by_subtitle = bool(word) and not _in_text(word, title) and _in_text(word, summary)
            topic_judge = ""
        else:
            parts = []
            for t in tags.get(p.rid, []):
                if t[0] != "symbol":
                    continue
                nm = names.get(t[1], "")
                parts.append(f"{nm}({t[1]})" if nm else t[1])
                if nm and not _in_text(nm, title) and _in_text(nm, summary):
                    by_subtitle = True
            sym_cell = " · ".join(parts)
            sym_judge = ""
        if by_subtitle:  # 규칙이 부제에서 맞춘 줄 — 제목만 보고 틀림으로 보지 않도록 표시한다
            if p.frame == FRAME_TOPIC:
                topic_cell += " ※부제"
            else:
                sym_cell += " ※부제"
            subtitle_marked += 1
        sub = _clean(summary) if p.kind == KIND_NEWS else ""
        if len(sub) > SUBTITLE_MAX:
            sub = sub[:SUBTITLE_MAX] + "…"
        rows.append({
            "표본ID": f"S{i:03d}",
            "구분": p.kind,
            "원천ID": d["doc_id"],
            "날짜": (d["published"] or "")[:10],
            "제목": _clean(title),
            "부제": sub,
            "종목 이름표": sym_cell,
            "주제 이름표": topic_cell,
            "종목판정": sym_judge,
            "주제판정": topic_judge,
            "메모": "",
            "층": f"{p.frame}:{p.stratum}",
            "층크기": str(p.size),
            "원문주소": d["url"] or "",
        })

    meta = {
        "시드": seed,
        "뽑은때": time.strftime("%Y-%m-%dT%H:%M:%S+09:00", time.localtime()),
        "인자": {"공시": n_disclosure, "뉴스": n_news, "뉴스종목틀": n_news_symbol, "의심종류": list(suspects),
               "의심최소": suspect_min, "층바닥": floor},
        "표본틀": plan,
        "줄수": len(rows),
        "부제표시줄": subtitle_marked,
    }
    return rows, meta


def write_tsv(path: Path, header: Sequence[str], rows: Sequence[Dict[str, str]]) -> None:
    """TSV 를 BOM 이 있는 UTF-8 로 쓴다 — 엑셀이 한글을 깨뜨리지 않고, ``score`` 는 BOM 이 있든 없든 읽는다."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(header)
        for r in rows:
            w.writerow([r.get(h, "") for h in header])


def cmd_draw(args: argparse.Namespace) -> int:
    out = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"표본_seed{args.seed}.tsv"
    meta_path = out.with_name(out.stem + ".메타.json")
    if (out.exists() or meta_path.exists()) and not args.force:
        print(f"오류: 이미 있다 — {out}\n  사람 판정이 들어 있을 수 있어 덮어쓰지 않는다. 덮으려면 --force.", file=sys.stderr)
        return 2
    try:
        conn = open_readonly(Path(args.db))
    except (FileNotFoundError, ValueError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 2
    try:
        search_meta = read_meta(conn)
        rows, meta = draw_sample(conn, seed=args.seed, n_disclosure=args.disclosure, n_news=args.news,
                                 n_news_symbol=args.news_symbol, suspects=args.suspect,
                                 suspect_min=args.suspect_min, floor=args.floor)
    finally:
        conn.close()

    current = current_rules_fingerprint() if search_meta.get("rules") else None
    meta["색인"] = {"경로": str(Path(args.db).resolve()), "만든때": search_meta.get("built_at", ""),
                  "규칙지문": search_meta.get("rules", ""), "지금규칙지문": current or "",
                  "규칙일치": (None if current is None else current == search_meta.get("rules")),
                  "문서수": search_meta.get("docs", "")}
    out.parent.mkdir(parents=True, exist_ok=True)
    write_tsv(out, HEADER, rows)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_draw_summary(out, meta_path, meta)
    return 0


def print_draw_summary(out: Path, meta_path: Path, meta: Dict) -> None:
    idx = meta["색인"]
    print(f"표본 {meta['줄수']}줄 → {out}\n곁 파일 → {meta_path}")
    print(f"색인 만든 때 {idx['만든때'] or '?'} · 규칙 지문 {idx['규칙지문'] or '?'}")
    if idx["규칙일치"] is False:
        print(f"경고: 색인을 만든 뒤 이름표 규칙이 바뀌었다(지금 {idx['지금규칙지문']}) — 이 표본은 **옛 규칙의 이름표**다. "
              f"python -m collector.search_index build 로 다시 만든 뒤 뽑는 편이 맞다.")
    print(f"부제에서 맞춘 줄(※부제) {meta['부제표시줄']}건")
    for name, f in meta["표본틀"].items():
        if "층" in f:
            print(f"[{name}] 요청 {f['요청']} · 뽑힘 {f['뽑힘']}")
            for t, v in sorted(f["층"].items(), key=lambda kv: (-kv[1]["층크기"], kv[0])):
                print(f"  {t:<8} 층크기 {v['층크기']:>8,} · 배정 {v['배정']:>3} · 뽑힘 {v['뽑힘']:>3}")
        else:
            print(f"[{name}] 요청 {f['요청']} · 뽑힘 {f['뽑힘']} · 종목 이름표가 붙은 뉴스 {f['층크기']:,}건 가운데 단순 무작위")


# ==================================================
# 4. 채점 (score)
# ==================================================
def wilson(p: float, n: float, z: float = Z95) -> Tuple[float, float]:
    """이항 비율 p 의 윌슨 신뢰구간. ``n`` 은 실수여도 된다(유효 표본 크기). n<=0 이면 (nan, nan)."""
    if n <= 0:
        return (math.nan, math.nan)
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(max(p * (1 - p) / n + z * z / (4 * n * n), 0.0)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def verdict(lo: float, hi: float, target: float = TARGET, point: Optional[float] = None) -> str:
    """구간으로 목표를 판정: 하한이 목표 이상이면 충족 · 상한이 목표 미만이면 미달 · 걸치면 보류.

    보류일 때 ``point``(점수)가 있으면 점수가 목표 이상인지 미만인지를 덧붙인다 — 표본 200건으로는 하한이 0.9 를 넘으려면
    점수가 0.98 안팎이어야 해서 대부분 보류가 나오기 때문이다(무엇이 모자라 보류인지 보이게).
    """
    if math.isnan(lo):
        return "-"
    if lo >= target:
        return "충족"
    if hi < target:
        return "미달"
    if point is None or math.isnan(point):
        return "보류(구간이 목표를 걸침)"
    return f"보류(점수 {'≥' if point >= target else '<'} 목표 · 구간이 목표를 걸침)"


@dataclass(frozen=True)
class Item:
    sample_id: str
    kind: str
    frame: str
    stratum: str
    size: int
    value: str      # 맞음 | 부분 | 틀림


@dataclass
class Collected:
    total: int = 0
    items: List[Item] = field(default_factory=list)
    blanks: List[str] = field(default_factory=list)                    # 빈 판정 줄의 표본ID
    invalid: List[Tuple[int, str, str]] = field(default_factory=list)  # (파일 줄 번호, 표본ID, 값)
    excluded: List[str] = field(default_factory=list)                  # 그 줄이 재는 칸에 「해당없음」 을 적은 줄


def decode_text(raw: bytes) -> str:
    """TSV 바이트 → 글. ``draw`` 가 쓴 UTF-8(BOM) 외에 엑셀이 다시 저장한 꼴도 읽는다 —
    「유니코드 텍스트」 는 UTF-16(BOM) · 「텍스트(탭으로 분리)」 는 한국어 윈도우에서 cp949."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("글자 인코딩을 읽을 수 없다 — 표본 파일을 UTF-8 TSV 로 저장한다")


def read_rows(path: Path) -> List[Tuple[int, Dict[str, str]]]:
    """TSV → [(파일 줄 번호, 칸 dict)]. BOM 이 있든 없든 · 앞뒤 공백은 지운다."""
    reader = csv.DictReader(io.StringIO(decode_text(Path(path).read_bytes()), newline=""), delimiter="\t")
    missing = [c for c in REQUIRED_SCORE_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"표본 파일에 필요한 칸이 없다: {', '.join(missing)} (draw 가 만든 TSV 이고 탭으로 나뉘어 있나?)")
    out = []
    for row in reader:
        out.append((reader.line_num, {k: (v or "").strip() for k, v in row.items() if k is not None}))
    return out


def collect(rows: Sequence[Tuple[int, Dict[str, str]]]) -> Collected:
    """줄마다 **그 줄이 재는 칸**의 판정을 읽는다 — 주제틀 줄은 주제판정, 종목틀 줄은 종목판정. 다른 칸은 보지 않는다."""
    c = Collected()
    for line_no, r in rows:
        c.total += 1
        sid = r.get("표본ID", "") or f"줄{line_no}"
        frame, _, stratum = r.get("층", "").partition(":")
        if frame not in (FRAME_TOPIC, FRAME_SYMBOL) or not stratum:
            raise ValueError(f"{sid}(파일 {line_no}줄): 층 칸을 읽을 수 없다 — 「{r.get('층', '')}」")
        try:
            size = int(r.get("층크기", ""))
        except ValueError:
            raise ValueError(f"{sid}(파일 {line_no}줄): 층크기가 숫자가 아니다 — 「{r.get('층크기', '')}」") from None
        value = r.get("주제판정" if frame == FRAME_TOPIC else "종목판정", "")
        if value == "":
            c.blanks.append(sid)
        elif value == NA:
            c.excluded.append(sid)
        elif value in JUDGE_VALUES:
            c.items.append(Item(sid, r.get("구분", ""), frame, stratum, size, value))
        else:
            c.invalid.append((line_no, sid, value))
    return c


@dataclass
class Estimate:
    n: int
    ok: int
    part: int
    bad: int
    strict: float
    lenient: float
    strict_ci: Tuple[float, float]
    lenient_ci: Tuple[float, float]
    n_eff: float


def _score(value: str) -> Tuple[float, float]:
    """(엄격, 관대) — 엄격은 맞음만 1 · 관대는 맞음 1 + 부분 0.5."""
    return {"맞음": (1.0, 1.0), "부분": (0.0, 0.5), "틀림": (0.0, 0.0)}[value]


def estimate(items: Sequence[Item], weighted: bool) -> Estimate:
    """줄 모음의 정밀도. ``weighted`` 면 층 크기로 가중(층 안 줄은 같은 가중 ``N_h / n_h``)해 모집단 정밀도를 어림한다.

    가중이면 윌슨 구간에는 유효 표본 크기 ``(Σw)² / Σw²`` 를 쓴다 — 가중이 고르지 않을수록 줄 수보다 작아진다(설계 효과).
    부분(0.5)을 비율로 보고 윌슨을 쓰는 것은 근사다.
    """
    n = len(items)
    if n == 0:
        nan = math.nan
        return Estimate(0, 0, 0, 0, nan, nan, (nan, nan), (nan, nan), 0.0)
    by_stratum: Dict[Tuple[str, str, str], int] = {}
    for it in items:
        key = (it.kind, it.frame, it.stratum)
        by_stratum[key] = by_stratum.get(key, 0) + 1
    ws, xs, xl = [], [], []
    for it in items:
        w = (it.size / by_stratum[(it.kind, it.frame, it.stratum)]) if weighted else 1.0
        s, l = _score(it.value)
        ws.append(w)
        xs.append(s)
        xl.append(l)
    sw = sum(ws)
    p_s = sum(w * x for w, x in zip(ws, xs)) / sw
    p_l = sum(w * x for w, x in zip(ws, xl)) / sw
    n_eff = sw * sw / sum(w * w for w in ws)
    return Estimate(n, sum(1 for i in items if i.value == "맞음"), sum(1 for i in items if i.value == "부분"),
                    sum(1 for i in items if i.value == "틀림"), p_s, p_l, wilson(p_s, n_eff), wilson(p_l, n_eff), n_eff)


def _p(x: float) -> str:
    return "-" if math.isnan(x) else f"{x:.3f}"


def _ci(ci: Tuple[float, float]) -> str:
    return "-" if math.isnan(ci[0]) else f"{ci[0]:.3f} ~ {ci[1]:.3f}"


def summarize(items: Sequence[Item]) -> Dict:
    """채점 결과를 값으로 돌려준다(시험 · 화면 출력이 같은 값을 쓴다)."""
    groups: Dict[Tuple[str, str], List[Item]] = {}
    strata: Dict[Tuple[str, str, str], List[Item]] = {}
    for it in items:
        groups.setdefault((it.frame, it.kind), []).append(it)
        strata.setdefault((it.frame, it.kind, it.stratum), []).append(it)
    return {
        # 표 순서: 주제틀(공시 → 뉴스) 다음에 종목틀
        "그룹": {k: {"가중": estimate(v, True), "표본그대로": estimate(v, False)}
               for k, v in sorted(groups.items(), key=lambda kv: (kv[0][0] != FRAME_TOPIC, kv[0][1] != KIND_DISCLOSURE))},
        "층": {k: estimate(v, False) for k, v in strata.items()},
        "층크기": {k: v[0].size for k, v in strata.items()},
    }


def _group_label(frame: str, kind: str) -> str:
    return f"{kind} {frame} 이름표"


def render_report(c: Collected, target: float = TARGET, partial: bool = False) -> str:
    s = summarize(c.items)
    L: List[str] = []
    L.append("# 이름표 정밀도 채점")
    L.append("")
    if partial:
        L.append("> 중간 확인(--partial) — 판정된 줄만 센 값이다. 빈 판정이 남아 있어 최종 값이 아니다.")
        L.append("")
    L.append("## 1. 요약 — 모집단 가중")
    L.append("")
    L.append("| 대상 | 판정 줄 | 맞음 | 부분 | 틀림 | 정밀도 (엄격) | 95% 구간 | 정밀도 (관대) | 95% 구간 | "
             f"목표 {target:g} (엄격) | 목표 {target:g} (관대) |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for (frame, kind), g in s["그룹"].items():
        e = g["가중"]
        L.append(f"| {_group_label(frame, kind)} | {e.n} | {e.ok} | {e.part} | {e.bad} | {_p(e.strict)} | {_ci(e.strict_ci)} | "
                 f"{_p(e.lenient)} | {_ci(e.lenient_ci)} | {verdict(*e.strict_ci, target, e.strict)} | "
                 f"{verdict(*e.lenient_ci, target, e.lenient)} |")
    L.append("")
    L.append("엄격 = 맞음만 1 · 관대 = 맞음 1 + 부분 0.5. 목표 판정은 **가중 값의 95% 구간**으로 한다 — 하한이 목표 이상이면 "
             "「충족」, 상한이 목표 미만이면 「미달」, 구간이 목표를 걸치면 「보류」 (표본이 작으면 점수가 목표를 넘어도 보류가 나온다 — "
             "그래서 보류에는 점수가 목표 이상인지 미만인지를 함께 적는다).")
    L.append("")
    L.append("## 2. 참고 — 표본 그대로(가중 없음)")
    L.append("")
    L.append("| 대상 | 판정 줄 | 정밀도 (엄격) | 95% 구간 | 정밀도 (관대) | 95% 구간 | 유효 표본 크기(가중) |")
    L.append("|---|---|---|---|---|---|---|")
    for (frame, kind), g in s["그룹"].items():
        e, w = g["표본그대로"], g["가중"]
        L.append(f"| {_group_label(frame, kind)} | {e.n} | {_p(e.strict)} | {_ci(e.strict_ci)} | {_p(e.lenient)} | "
                 f"{_ci(e.lenient_ci)} | {w.n_eff:.1f} |")
    L.append("")
    L.append("표본은 층(주제)마다 비례가 아니게 뽑았으므로(소송·제재 같은 의심 종류를 더 뽑음) 「표본 그대로」 값은 모집단 정밀도가 "
             "아니다. 1절이 대표값이고, 이 표는 가중이 결과를 얼마나 움직였는지 보려는 것이다. 유효 표본 크기가 판정 줄 수보다 "
             "많이 작으면 가중이 고르지 않다는 뜻이다.")
    L.append("")
    L.append("## 3. 주제 종류별 (주제틀)")
    L.append("")
    L.append("| 구분 | 주제 | 층 크기 | 판정 줄 | 맞음 | 부분 | 틀림 | 정밀도 (엄격) | 95% 구간 | 정밀도 (관대) | 95% 구간 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    topic_keys = [k for k in s["층"] if k[0] == FRAME_TOPIC]
    for k in sorted(topic_keys, key=lambda k: (k[1], -s["층크기"][k], k[2])):
        e = s["층"][k]
        L.append(f"| {k[1]} | {k[2]} | {s['층크기'][k]:,} | {e.n} | {e.ok} | {e.part} | {e.bad} | {_p(e.strict)} | "
                 f"{_ci(e.strict_ci)} | {_p(e.lenient)} | {_ci(e.lenient_ci)} |")
    if not topic_keys:
        L.append("| (주제틀 판정 없음) | | | | | | | | | | |")
    L.append("")
    L.append("종류별 줄 수가 적어(보통 2 ~ 15건) 구간이 넓다 — 점수가 낮은 종류를 **찾는** 표이지 종류마다 목표를 판정하는 표가 아니다.")
    L.append("")
    L.append("## 4. 판정 현황")
    L.append("")
    judged = len(c.items)
    L.append("| 줄 | 건수 |")
    L.append("|---|---|")
    L.append(f"| 전체 줄 | {c.total} |")
    L.append(f"| 판정함(맞음 · 부분 · 틀림) | {judged} |")
    L.append(f"| 빈 판정 | {len(c.blanks)} |")
    L.append(f"| 판정 제외(그 줄이 재는 칸에 「{NA}」 을 적음) | {len(c.excluded)} |")
    if c.excluded:
        L.append("")
        L.append("제외한 줄: " + ", ".join(c.excluded))
    L.append("")
    L.append("부분(0.5)을 비율로 보고 윌슨 구간을 쓴 것은 근사다. 맞은 것만 센 정밀도라 **놓친 것(재현율)은 이 표본으로 재지 못한다**.")
    return "\n".join(L) + "\n"


def _head(ids: Sequence[str], k: int = 12) -> str:
    return ", ".join(ids[:k]) + (f" … 외 {len(ids) - k}줄" if len(ids) > k else "")


def cmd_score(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"오류: 파일이 없다 — {path}", file=sys.stderr)
        return 2
    try:
        c = collect(read_rows(path))
    except ValueError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 2
    if c.invalid:
        print(f"오류: 판정 칸에 알 수 없는 값 {len(c.invalid)}줄 — 맞음 · 부분 · 틀림 (또는 {NA}) 만 쓴다.", file=sys.stderr)
        for line_no, sid, v in c.invalid[:20]:
            print(f"  파일 {line_no}줄 · {sid} · 「{v}」", file=sys.stderr)
        return 2
    if c.blanks:
        print(f"경고: 빈 판정 {len(c.blanks)}줄 (전체 {c.total}줄 가운데) — {_head(c.blanks)}")
        if not args.partial:
            print("  판정을 마저 채운 뒤 다시 돌린다. 중간 확인만 하려면 --partial.")
            return 1
        print("  --partial 이라 판정된 줄만 세어 계속한다.")
        print()
    if not c.items:
        print("판정된 줄이 없다.")
        return 1
    text = render_report(c, args.target, partial=bool(c.blanks))
    print(text, end="")
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"\n→ {args.out}")
    return 0


# ==================================================
# 5. 명령줄
# ==================================================
HELP_EPILOG = f"""\
층화 방식과 까닭 (draw)
  표본틀 둘 — ① 주제틀: 주제 이름표가 붙은 공시 · 뉴스를 주제 종류별로 층화해 뽑는다. ② 종목틀: 종목 이름표가 붙은 뉴스를
  단순 무작위로 뽑는다(주제가 붙은 뉴스 중 종목 이름표가 있는 것은 22% 뿐이라, 주제로만 뽑으면 뉴스 종목 판정이 20건 남짓).
  공시 종목 이름표는 DART 의 종목 코드 칸을 그대로 옮긴 것이라 판정하지 않는다.
  주제틀 배정: 1) 모든 주제에 {FLOOR_PER_STRATUM}건 이상(건수가 적은 주제도 빠지지 않게) 2) 의심 종류({', '.join(SUSPECT_TOPICS)})는
  {SUSPECT_MIN}건 이상(뉴스 주제의 31% 가 이 하나라 바닥 {FLOOR_PER_STRATUM}건으론 낮은지 알 수 없다) 3) 나머지는 층 크기의 제곱근에
  비례(비례 배분은 공시 「지분」 28% 가 표본을 삼키고 균등 배분은 큰 층이 불확실하다). 비례가 아니므로 score 는 층 크기로 가중한다.
  고정 시드(--seed) · 후보를 rid 순으로 정렬해 뽑아, 같은 색인 · 같은 인자면 같은 표본이다. 뽑은 뒤 줄 순서는 섞는다.
판정 값
  종목판정 · 주제판정 칸에 맞음 / 부분 / 틀림 을 적는다. 「{NA}」 이 미리 적힌 칸은 그 줄이 재는 이름표가 아니니 건드리지 않는다.
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python scripts/tagging_sample.py", description="이름표 정밀도 표본 — 추출(draw)과 채점(score)",
                                epilog=HELP_EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("draw", help="표본 TSV 를 뽑는다(읽기 전용)", epilog=HELP_EPILOG,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    d.add_argument("--db", default=str(DEFAULT_DB), help="검색 색인 경로(기본 data/collector/search.sqlite3 — 이름표가 있는 파일)")
    d.add_argument("--out", help=f"표본 TSV 경로(기본 {DEFAULT_OUT_DIR}/표본_seed<시드>.tsv)")
    d.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"고정 난수 시드(기본 {DEFAULT_SEED})")
    d.add_argument("--disclosure", type=int, default=100, help="공시 줄 수(주제틀 · 기본 100)")
    d.add_argument("--news", type=int, default=100, help="뉴스 줄 수 합계(주제틀 + 종목틀 · 기본 100)")
    d.add_argument("--news-symbol", type=int, default=40, help="뉴스 가운데 종목틀 줄 수(기본 40 · 나머지는 주제틀)")
    d.add_argument("--suspect", type=lambda s: [x.strip() for x in s.split(",") if x.strip()], default=list(SUSPECT_TOPICS),
                   help=f"의심 주제(쉼표로 여럿 · 기본 {','.join(SUSPECT_TOPICS)})")
    d.add_argument("--suspect-min", type=int, default=SUSPECT_MIN, help=f"의심 주제의 구분별 최소 줄 수(기본 {SUSPECT_MIN})")
    d.add_argument("--floor", type=int, default=FLOOR_PER_STRATUM, help=f"모든 주제의 구분별 최소 줄 수(기본 {FLOOR_PER_STRATUM})")
    d.add_argument("--force", action="store_true", help="이미 있는 표본 파일을 덮어쓴다(사람 판정이 날아간다)")
    d.set_defaults(func=cmd_draw)

    s = sub.add_parser("score", help="판정을 채운 TSV 를 채점한다", epilog=HELP_EPILOG,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    s.add_argument("file", help="판정 열을 채운 표본 TSV")
    s.add_argument("--partial", action="store_true", help="빈 판정이 있어도 판정된 줄만 세어 중간 값을 본다(경고는 그대로)")
    s.add_argument("--target", type=float, default=TARGET, help=f"정밀도 목표(기본 {TARGET})")
    s.add_argument("--out", help="채점 표를 마크다운 파일로도 저장")
    s.set_defaults(func=cmd_score)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    utf8_stdio()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
