"""자료 안내 — 「무엇이 있고 · 어떻게 모으고 · 무엇을 읽으면 되나」 (2026-10-08 · 화면 결정 안 B + 안 A 서랍 · 1단계 /
2026-10-11 · 2단계 — 칸 정의 · 러너가 회차마다 쓰는 숫자 파일).

`GET /api/data/guide` 가 부른다. 화면은 public/js/dataguide.js(「데이터 › 자료 안내」 · 데이터 관제 바로 아래).
2026-10-15 · 3단계 — 관제 밖 자료 여덟(일정 셋 · 근거 둘 · 검색 색인 · 용어 · 회차 기록)도 숫자 파일의 `extras` 에서 숫자를 받고,
숫자 파일 읽기는 관제와 같은 함수(`data_status.load_numbers` — 관제 행 수도 이 파일에서 읽는다)를 쓰고, 회차 시각은 러너 단계 목록
하나에서(D104), 오늘 회차가 없으면 안내 줄로 알린다.

설명과 숫자를 나눈다 (2026-10-08 결정 ④ · SSoT)
-----------------------------------------------
  설명  app/services/data_guide.json — 대장(docs/데이터/대장/자료안내-*.tsv)과 코드의 칸(수집기 CREATE 문 · 앱 모델)에서
        `scripts/data_guide_scan.py --write` 가 만든 생성물. 앱은 읽기만 한다(앱 이미지에 docs/ · scripts/ 가 없다). 대장과
        어긋나면 시험 TC-DG-01(`--check`)이 알린다. 2단계부터 자료마다 칸 정의(쉬운 이름 · 단위 · 뜻)가 함께 온다.
  숫자  러너가 회차 끝 · 한 단계 다시 뒤에 쓰는 파일 하나(`state/data_guide_stats.json` — 표마다 줄 수 · 마지막 날, 관제와
        같은 표 정의 · 셈법)와 백업 매니페스트 두 장(연도별 · 처음 · 시장별). **요청 때 수집 DB 를 세지 않는다** — 1단계는
        상태 계산(30초 캐시 · 뒤에서 세는 줄 수)을 2.5초까지 기다렸고, 수집이 도는 동안에는 줄 수가 「세는 중」 으로 비었다.
        2단계는 결정 ④ 를 다 지킨다: 이 서비스에는 수집 DB 를 여는 코드가 없고 파일(JSON)만 읽는다(TC-DG-06 이 지킨다).
        경로는 상태와 같은 길(`data_status.collector_dir`)로 찾는다 — 로컬 data/collector · 도커 /app/data/csv/collector.

숫자 파일의 상태 → 화면 안내 줄 (2026-10-11 사용자 결정 「카드 글 그대로」 · Figma 「자료 안내」 03-2 카드)
---------------------------------------------------------------------------------------------
  ok      마지막 수집(한 단계 다시 포함) 뒤에 쓰였다 — 안내 없음 · 머리 「숫자 기준 MM-DD HH:MM 수집」
  running 수집이 도는 중 — 숫자는 지난 수집 기준(파일은 회차가 끝날 때 새로 쓴다)
  stale   마지막 수집 뒤에 파일을 못 썼다(러너는 🟡 한 줄을 남기고 회차를 계속한다) — 숫자는 그대로 · 그 시각 기준이라고 알린다
  none    파일이 아직 없다(합친 날 · 첫 수집 전) — 다음 수집 뒤에 보인다
  old     파일의 판이 앱이 아는 판과 다르다 — 숫자를 비운다(다음 회차에 러너가 새 판으로 쓴다)
  error   파일을 읽지 못했다(깨진 JSON · 꼴이 다름) — 숫자를 비우고 「읽지 못했습니다」

숫자가 없으면 설명만 — 말없이 0 을 넣지 않는다
---------------------------------------------
수집 자료가 없는 PC(팀원 PC 대부분)에서도 설명 · 흐름 · 길잡이 · 칸 정의는 다 보인다. 숫자 칸은 None(화면의 「—」)으로 두고
까닭을 단다. 숫자 파일의 「없음」 표(수집 DB 나 표가 없다 · 행이 없다)는 줄 수 None 이지 「0줄」 이 아니다(러너가 None 으로
쓰고, 여기서도 0 을 넣지 않는다).

개발 칸은 서버가 관리자에게만 (결정 ① ② · 2026-10-11 「열쇠 표시는 관리자에게만」)
-------------------------------------------------------------------------------
표 이름 · 읽는 길(API) · 백업 경로 · 받는 명령 · 칸 이름 · 칸 타입 · 열쇠(한 줄을 가르는 칸)는 관리자 응답에만 싣는다. 화면이
CSS 로 숨기면 응답(개발자 도구)에는 남는다. 일반 사용자의 「쓰는 화면」 · 「어디서」 에서는 관리자 화면 셋도 뺀다(그 사람이 열
수 있는 화면만). 쉬운 이름이 아직 없는 칸(칸 대장에 줄이 없다)은 일반 사용자 응답에서 빠지고 「설명 n / 전체」 로만 남는다.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path

from app.services import data_status

logger = logging.getLogger(__name__)

GUIDE_PATH = Path(__file__).resolve().parent / "data_guide.json"
#: 설명 생성물의 판 — 2 = 자료마다 칸 정의(2026-10-11). 스캐너(`scripts/data_guide_scan.py` SCHEMA)와 같아야 한다(TC-DG-01).
SCHEMA = 2
#: 러너가 회차 끝 · 한 단계 다시 뒤에 쓰는 숫자 파일 — 이름 · 판 · 읽는 함수는 관제 모듈 한 곳(`data_status` · 2026-10-15 에
#: 옮김 · 관제 행 수도 같은 파일을 읽는다). 함수는 별칭 없이 `data_status.load_numbers` 처럼 부른다(그 함수를 고치면 여기도 같이
#: 바뀌게). 상수 이름은 시험 · 러너 주석이 부르므로 같은 이름으로 다시 내보낸다.
NUMBERS_FILE = data_status.NUMBERS_FILE
NUMBERS_SCHEMA = data_status.NUMBERS_SCHEMA

#: 관리자 화면 — 일반 사용자 응답의 「쓰는 화면」 · 「어디서」 에서 뺀다. css/collect.css 가 일반 사용자의 메뉴에서 숨기는 셋과
#: 같다(TC-DG 가 맞댄다 — 관리자 화면이 늘면 두 곳을 함께 고친다).
ADMIN_VIEWS = frozenset({"crawl-auto", "crawl-manual", "crawl-ingest"})
#: 일봉 매니페스트의 시장 이름 → 화면 이름
MARKET_NAMES = {"KOSPI": "코스피", "KOSDAQ": "코스닥", "KONEX": "코넥스", "ETF": "ETF", "INDEX": "지수"}
#: 자료 한 줄의 숫자 상태 → 까닭(쉬운 말). 화면은 상태 열쇠로 모양을 고르고 이 글을 그대로 보인다(TC-DG-04 가 맞댄다).
#: pending = 숫자 파일이 아직 없거나 옛 판이라 줄 수를 다음 수집 뒤에 보인다(2단계 — 1단계의 「세는 중」 을 바꿨다).
ITEM_WHY = {
    "ok": "",
    "pending": "줄 수는 매일 낮 수집이 끝날 때 셉니다",
    "partial": "줄 수는 이 PC 에서 세지 못했습니다 — 연도별은 백업 목록 기준입니다",
    "none": "이 PC 에는 이 자료가 없습니다",
    "no_link": "이 화면에서는 세지 않는 자료입니다 — 「쓰는 화면」 에서 봅니다",
    "error": "숫자를 읽지 못했습니다",
}
#: 숫자 띠 아래 안내 줄 — 숫자 파일 상태마다 하나(2026-10-11 사용자 결정 「카드 글 그대로」). {at} = 파일을 쓴 MM-DD HH:MM
NOTE = {
    "error": "숫자 파일을 읽지 못했습니다 — 숫자 칸은 비워 두고 설명은 그대로 보입니다",
    "old": "숫자 파일이 이 화면보다 옛 판이라 숫자를 비워 둡니다 — 다음 수집 때 새로 씁니다",
    "no_data": "이 PC 에는 모은 자료가 없습니다 — 설명 · 흐름 · 길잡이는 그대로 봅니다",
    "none": "숫자는 매일 낮 수집이 끝날 때 셉니다 — 다음 수집 뒤에 보입니다",
    "running": "매일 낮 수집이 도는 중입니다 — 숫자는 지난 수집({at}) 기준입니다",
    "stale": "숫자는 {at} 수집 기준입니다 — 마지막 수집 뒤에 숫자를 새로 쓰지 못했습니다",
    # 관제 「오늘 회차 없음」(러너 단계 목록의 회차 시각 + 1시간이 지나도 오늘 기록이 없다 · 2026-10-15 3단계) — 숫자는 그대로
    "late": "오늘 낮 수집이 아직 없습니다 — 숫자는 {at} 수집 기준입니다",
}

_lock = threading.Lock()
_guide_cache: dict = {"sig": None, "value": None}
_file_cache: dict[str, tuple] = {}

_YEAR = re.compile(r"(?:^|/)year=(\d{4})(?:/|$)")
_OHLCV = re.compile(r"timeframe=([^/]+)/basis=([^/]+)(?:/market=([^/]+))?/year=(\d{4})")


class GuideUnavailable(Exception):
    """설명 생성물을 읽지 못했다 — 라우트가 503 과 이 글을 돌려준다(화면은 「자료 안내를 읽지 못했습니다」)."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


# ── 설명(생성물) ──────────────────────────────────────────────────────────
def load_guide(path: Path | None = None) -> dict:
    """설명 생성물 — 파일이 바뀌었을 때만 다시 읽는다(크기 · 시각 지문)."""
    p = path or GUIDE_PATH
    try:
        st = p.stat()
    except OSError:
        raise GuideUnavailable("자료 안내 설명 파일이 없습니다") from None
    sig = (str(p), st.st_mtime_ns, st.st_size)
    with _lock:
        if _guide_cache["sig"] == sig:
            return _guide_cache["value"]
    try:
        guide = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise GuideUnavailable("자료 안내 설명 파일을 읽지 못했습니다") from e
    if not isinstance(guide, dict) or guide.get("schema") != SCHEMA:
        got = guide.get("schema") if isinstance(guide, dict) else None
        raise GuideUnavailable(f"자료 안내 설명 파일의 판({got})이 앱이 아는 판({SCHEMA})과 다릅니다")
    with _lock:
        _guide_cache.update(sig=sig, value=guide)
    return guide


def _public_columns(cols: dict | None) -> dict | None:
    """칸 정의의 일반 사용자 판 — 칸마다 쉬운 이름 · 단위 · 뜻만. 칸 이름 · 타입 · 열쇠(dev)와 표 이름(묶음 dev)은 빼고, 쉬운 이름이
    없는 칸(칸 대장에 줄이 없다)은 줄째 뺀다 — 그런 칸은 「설명 n / 전체」 의 숫자로만 남는다(2026-10-11 결정 ② 「열쇠는 관리자에게만」)."""
    if not cols:
        return cols
    for cg in cols.get("tables", []):
        cg.pop("dev", None)
        cg["cols"] = [{k: cc.get(k) for k in ("name", "unit", "text")} for cc in cg.get("cols", []) if cc.get("name")]
    return cols


def public_guide(guide: dict, admin: bool) -> dict:
    """응답에 싣는 설명 — 숫자 잇는 칸(stats_from)은 누구에게도 · 개발 칸(dev · 뺀 표 · 칸 이름 · 열쇠)은 관리자에게만 싣는다.

    일반 사용자 응답에는 표 이름 · 칸 이름 · API 경로 · 명령이 **글자로도** 남지 않아야 한다(TC-DG-03) — 화면이 숨기는 것으로는
    모자란다.
    """
    g = copy.deepcopy(guide)
    for k in ("schema", "source"):
        g.pop(k, None)
    for it in g.get("items", []):
        it.pop("stats_from", None)
        if not admin:
            it.pop("dev", None)
            it["views"] = [v for v in it.get("views", []) if v not in ADMIN_VIEWS]
            it["columns"] = _public_columns(it.get("columns"))
    for t in g.get("tasks", []):
        if not admin:
            t.pop("dev", None)
            t["views"] = [v for v in t.get("views", []) if v not in ADMIN_VIEWS]
    for f in g.get("flow", []):
        if not admin:
            f.pop("dev", None)
    if not admin:
        g.pop("excluded", None)
    return g


# ── 숫자 — 백업 매니페스트 두 장 ────────────────────────────────────────────
def _read_json_cached(path: Path) -> dict | None:
    """작은 JSON 파일(매니페스트 50KB 안팎) — 크기 · 시각이 그대로면 다시 읽지 않는다. 못 읽으면 None."""
    try:
        st = path.stat()
    except OSError:
        return None
    sig = (st.st_mtime_ns, st.st_size)
    with _lock:
        hit = _file_cache.get(str(path))
    if hit and hit[0] == sig:
        return hit[1]
    value = data_status._read_json(path)  # noqa: SLF001 — 같은 읽기(못 읽으면 None)
    with _lock:
        _file_cache[str(path)] = (sig, value)
    return value


def _daily_view(man: dict | None) -> dict | None:
    """krx-daily-market 매니페스트 → 표마다 {rows, years}. 연도는 파일 경로의 `year=YYYY` 에서(연도로 가르지 않는 표는 합만)."""
    if not isinstance(man, dict) or not isinstance(man.get("tables"), dict):
        return None
    tables: dict[str, dict] = {}
    for name, t in man["tables"].items():
        files = t.get("files") if isinstance(t, dict) else None
        if not isinstance(files, list):
            continue
        years: dict[str, int] = {}
        total = 0
        for f in files:
            rows = f.get("rows") if isinstance(f, dict) else None
            if not isinstance(rows, int):
                continue
            total += rows
            m = _YEAR.search(f.get("path") or "")
            if m:
                years[m.group(1)] = years.get(m.group(1), 0) + rows
        tables[name] = {"rows": total, "years": years}
    return {"at": man.get("generated_at"), "tables": tables}


def _ohlcv_view(man: dict | None) -> dict | None:
    """krx-ohlcv 매니페스트 → 파일 줄(주기 · 가격 · 시장 · 해 · 줄 수 · 처음 · 마지막). 시장 칸이 없는 분봉은 시장 「」."""
    if not isinstance(man, dict) or not isinstance(man.get("files"), list):
        return None
    files = []
    for f in man["files"]:
        if not isinstance(f, dict):
            continue
        m = _OHLCV.search(f.get("path") or "")
        if not m or not isinstance(f.get("rows"), int):
            continue
        tf, basis, market, year = m.groups()
        files.append({"tf": tf, "basis": basis, "market": market or "", "year": year, "rows": f["rows"],
                      "first": f.get("first"), "last": f.get("last")})
    return {"at": man.get("built_at"), "files": files}


def manifests(cdir: Path | None) -> dict:
    """백업 매니페스트 두 장(이 PC) — {"daily": … | None, "ohlcv": … | None}. 없거나 못 읽은 장은 None(숫자 없음)."""
    if cdir is None:
        return {"daily": None, "ohlcv": None}
    return {"daily": _daily_view(_read_json_cached(cdir.parent / "hf_export" / "meta" / "manifest.json")),
            "ohlcv": _ohlcv_view(_read_json_cached(cdir / "ohlcv_export" / "manifest.json"))}


def series(spec: str, mans: dict) -> dict | None:
    """대장의 숫자_백업 열쇠 → {rows, years, first, last, markets, at}. 매니페스트에 그 줄이 없으면 None.

    hf:<표>                      krx-daily-market 의 그 표 — 연도별 · 합(처음 · 마지막 날은 없다)
    ohlcv:<주기>[/<가격>[/<시장>+…]]  krx-ohlcv 파일 가운데 맞는 것 — 연도별 · 합 · 처음 · 마지막 · 시장별
    """
    kind, _, rest = spec.partition(":")
    if kind == "hf":
        daily = mans.get("daily")
        t = (daily or {}).get("tables", {}).get(rest)
        if t is None:
            return None
        return {"rows": t["rows"], "years": dict(sorted(t["years"].items())), "first": None, "last": None,
                "markets": None, "at": daily.get("at")}
    if kind == "ohlcv":
        ohlcv = mans.get("ohlcv")
        if not ohlcv:
            return None
        parts = (rest.split("/") + ["", ""])[:3]
        tf, basis = parts[0], parts[1]
        want = set(parts[2].split("+")) if parts[2] else None
        files = [f for f in ohlcv["files"] if f["tf"] == tf and (not basis or f["basis"] == basis)
                 and (want is None or f["market"] in want)]
        if not files:
            return None
        years: dict[str, int] = {}
        markets: dict[str, int] = {}
        for f in files:
            years[f["year"]] = years.get(f["year"], 0) + f["rows"]
            if f["market"]:
                markets[f["market"]] = markets.get(f["market"], 0) + f["rows"]
        firsts = [f["first"] for f in files if f.get("first")]
        lasts = [f["last"] for f in files if f.get("last")]
        return {"rows": sum(f["rows"] for f in files), "years": dict(sorted(years.items())),
                "first": min(firsts) if firsts else None, "last": max(lasts) if lasts else None,
                # 시장이 둘 이상일 때만 — 시장 하나뿐인 ETF · 지수는 시장별이 따로 뜻이 없다. 차례는 매니페스트 파일 차례가 아니라
                # 화면 차례(코스피 → 코스닥 → 코넥스 → ETF → 지수)
                "markets": [{"name": MARKET_NAMES.get(k, k), "rows": markets[k]}
                            for k in sorted(markets, key=lambda k: list(MARKET_NAMES).index(k) if k in MARKET_NAMES else 99)]
                if len(markets) > 1 else None,
                "at": ohlcv.get("at")}
    return None


# ── 숫자 — 러너가 쓴 숫자 파일(2단계) — 읽는 함수는 관제 모듈 한 곳(위에서 다시 내보냄 · 2026-10-15) ────────
def _hm(iso: str | None) -> str:
    """2026-10-08T13:25:30+09:00 → 10-08 13:25 (안내 줄 · 관리자 까닭)"""
    return f"{iso[5:10]} {iso[11:16]}" if iso and len(iso) >= 16 else "—"


# ── 숫자 — 자료 한 줄 · 전체 ────────────────────────────────────────────────
def item_stats(item: dict, tables: dict[str, dict] | None, mans: dict, dev: list[str], numbers_state: str = "ok") -> dict:
    """자료 한 줄의 숫자. `tables` 는 숫자 파일의 표 줄(열쇠 → 줄) · 파일이 ok 가 아니면 None(`numbers_state` 가 까닭).

    줄 수 · 마지막 날은 숫자 파일(러너가 회차 끝에 센 값)을 먼저 쓰고, 그 파일에 줄이 없는 자료(가격 조정 기록 · 분봉 대상 ·
    받은 원문 · 주봉)만 백업 매니페스트의 합 · 마지막 날을 쓴다(rows_from 으로 어디서 왔는지 남긴다). 연도별 · 처음 · 시장별은
    매니페스트에서 온다 — 관제 밖 자료 여덟(3단계)은 처음 날도 숫자 파일에서(`first_from` 으로 가른다 · 모은 기간 머리에는 백업 목록
    처음 날만). 파일이 아직 없거나 옛 판이면 「기다림(pending)」 · 깨졌으면 「읽지 못함(error)」 — 0 을 넣지 않는다. 옛 러너 파일에
    `extras` 칸이 없으면 그 여덟도 「기다림」 이다(`tables` 의 그 열쇠 줄에 `pending` 표시).
    """
    sf = item.get("stats_from") or {}
    keys, spec = sf.get("status") or [], sf.get("backup") or ""
    out = {"state": "ok", "why": "", "rows": None, "rows_from": None, "last": None, "first": None, "first_from": None,
           "first_year": None, "years": None, "markets": None}
    if not keys and not spec:
        return {**out, "state": "no_link", "why": ITEM_WHY["no_link"]}
    waiting = error = False
    if keys:
        if tables is None:
            error = numbers_state == "error"
            waiting = not error                    # 파일이 아직 없거나(합친 날) 옛 판 — 다음 수집 뒤에 보인다
        else:
            rows = [tables.get(k) for k in keys]
            unknown = [k for k, r in zip(keys, rows) if r is None]
            if any(r and r.get("pending") for r in rows):
                waiting = True                     # 옛 러너 파일 — 관제 밖 여덟(extras)이 아직 없다 · 다음 수집 뒤에 보인다
            elif unknown:
                error = True
                dev.append(f"{item['key']}: 숫자_상태 {', '.join(unknown)} 가 숫자 파일({NUMBERS_FILE})에 없다"
                           " — 러너는 관제 표 정의(data_status.TABLES · EXTRA_KEYS)의 열쇠로 쓴다")
            # verdict missing = 수집 DB 나 표가 없다 · 행이 없다 — 그때 줄 수는 None(「없음」)이라 쓰지 않는다
            elif all(r.get("verdict") != "missing" for r in rows):
                vals = [r.get("rows") for r in rows]
                if all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
                    out.update(rows=sum(vals), rows_from="numbers")
                else:
                    error = True
                    dev.append(f"{item['key']}: 숫자 파일의 줄 수가 정수가 아니다 — {vals}")
                lasts = [r["last_date"] for r in rows if r.get("last_date")]
                out["last"] = max(lasts) if lasts else None
                firsts = [r["first_date"] for r in rows if r.get("first_date")]
                if firsts:
                    out.update(first=min(firsts), first_from="numbers")
    ser = series(spec, mans) if spec else None
    if spec and ser is None and mans.get("daily" if spec.startswith("hf:") else "ohlcv") is not None:
        dev.append(f"{item['key']}: 숫자_백업 {spec} 줄이 매니페스트에 없다")
    if ser:
        out["years"] = ser["years"] or None
        if ser["first"]:
            out.update(first=ser["first"], first_from="backup")
        out["markets"] = ser["markets"]
        nonzero = [y for y, n in (ser["years"] or {}).items() if n]
        out["first_year"] = min(nonzero) if nonzero else None
        if not keys:
            out.update(rows=ser["rows"], rows_from="backup", last=ser["last"])
    if out["rows"] is None and out["last"] is None and not out["years"]:
        state = "error" if error else "pending" if waiting else "none"
        return {**out, "state": state, "why": ITEM_WHY[state]}
    if error:
        out.update(state="error", why=ITEM_WHY["error"])
    elif waiting:
        out.update(state="pending", why=ITEM_WHY["pending"])
    elif out["rows"] is None:
        # 연도별(백업 목록)만 있고 지금 줄 수가 없다 — 「ok」 로 두면 화면이 빈칸의 까닭을 못 단다
        out.update(state="partial", why=ITEM_WHY["partial"])
    return out


def runner_view(runner: dict | None, catalog: dict | None) -> dict:
    """흐름 그림의 단계 — 단계 이름표 · 묶음은 러너가 쓴 단계 목록에서만 읽는다(결정 ④ · 앱에 사본 없음).

    `runner` 는 `data_status.runner_state` 의 답(러너 기록 파일만 읽는다 — 수집 DB 를 열지 않는다).
    묶음 설명(`note`)은 관리자 말(「Hugging Face 데이터셋으로 올린다」)이라 싣지 않는다 — 쉬운 말은 대장의 흐름 상자가 맡는다.
    단계 이름(price · ohlcv_upload)도 싣지 않고 이름표(시세 · 일봉 올리기)만 싣는다.
    """
    r = runner or {}
    last = r.get("last") or {}
    steps = (catalog or {}).get("steps") or last.get("steps") or []
    order = [g.get("key") for g in ((catalog or {}).get("groups") or r.get("groups") or []) if isinstance(g, dict) and g.get("key")]
    for s in steps:
        if s.get("group") and s["group"] not in order:
            order.append(s["group"])          # 목록에 없는 묶음도 빠뜨리지 않는다(새 묶음이 생긴 날)
    attention: dict[str, int] = {}
    for s in last.get("steps") or []:
        if s.get("status") in ("failed", "warning") or s.get("followup"):
            attention[s.get("group") or ""] = attention.get(s.get("group") or "", 0) + 1
    return {
        # 회차 시각은 러너가 쓴 단계 목록 하나에서(D104) — 관제가 읽은 글 그대로 · 모르면 「회차 시각 모름」(12:30 으로 메우지 않는다)
        "schedule": r.get("schedule") or data_status.SCHEDULE_UNKNOWN,
        "running": bool(r.get("running")),
        "total_steps": len(steps),
        "groups": [{"key": g, "count": sum(1 for s in steps if s.get("group") == g),
                    "steps": [s["label"] for s in steps if s.get("group") == g and s.get("label")],
                    "attention": attention.get(g, 0)} for g in order],
        "last": {k: last.get(k) for k in ("started_at", "finished_at", "minutes", "ok")} if last else None,
    }


def compute_stats(guide: dict, nums: dict, runner: dict | None, mans: dict, catalog: dict | None,
                  problems: list[str], dev: list[str]) -> dict:
    """숫자 전체 — 숫자 띠 · 바둑판 · 자료 줄 · 흐름 · 안내 줄. `nums` 는 `load_numbers` 의 답 — ok 가 아니어도 설명과 백업 목록의
    숫자는 그대로 싣고, 숫자 파일에서 오는 칸만 비운 채 까닭을 단다(안내 줄 · 관리자 까닭)."""
    tables = nums.get("tables")
    state = nums.get("state") or "none"
    # 자료 줄이 읽는 열쇠 — 관제 표 열쇠 + 관제 밖 여덟(3단계). 「모은 줄」 합은 관제 표 열쇠만(아래 `present`)
    lookup = None
    if tables is not None:
        extras = nums.get("extras")
        if extras is None:                         # 옛 러너 파일 — 여덟은 기다림(깨짐이 아니다)
            extras = {k: {"pending": True} for k in data_status.EXTRA_KEYS}
            dev.append(f"{NUMBERS_FILE} 에 관제 밖 자료 여덟(extras)이 없다 — 옛 러너가 쓴 파일 · 다음 회차 · steps --write 뒤에 생긴다")
        lookup = {**tables, **extras}
    items = {it["key"]: item_stats(it, lookup, mans, dev, state) for it in guide.get("items", [])}
    written = nums.get("written_at") if state == "ok" else None
    stale = state == "ok" and data_status.numbers_stale(written, runner)

    # 모은 줄 — 숫자 파일 표 줄의 합(주봉처럼 부를 때 계산하는 자료 · 근거 문서 · 용어는 빼고). 「없음」 표는 빼고 센다.
    present = [t for t in (tables or {}).values() if t.get("verdict") != "missing"]
    vals = [t.get("rows") for t in present]
    if not present or not all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
        total, total_state = None, "none"
    else:
        total, total_state = sum(vals), ("stale" if stale else "fresh")
    # 모은 기간 머리 — 백업 목록(시세 · 공시 …)의 처음 날만. 관제 밖 여덟의 처음 날(공휴일 2020-01-01 등)은 섞지 않는다
    firsts = [s["first"] for s in items.values() if s.get("first") and s.get("first_from") == "backup"]
    first = min(firsts) if firsts else None
    # 처음 날보다 이른 해가 있는 자료(재무는 보고서를 접수한 해 2019 부터) — 숫자 띠의 한 줄
    early = sorted(({"item": k, "year": s["first_year"]} for k, s in items.items()
                    if s.get("first_year") and first and s["first_year"] < first[:4]), key=lambda x: x["year"])
    grid_years = sorted({y for it in guide.get("items", []) if it.get("grid") for y in (items[it["key"]].get("years") or {})})
    years = [str(y) for y in range(int(grid_years[0]), int(grid_years[-1]) + 1)] if grid_years else []
    ats = [m.get("at") for m in mans.values() if m and m.get("at")]
    available = any(s["rows"] is not None or s["years"] for s in items.values())
    view = runner_view(runner, catalog)

    # 안내 줄 — 차례가 뜻이 있다: 파일을 못 읽음 > 옛 판 > 모은 자료 없음 > 파일 아직 없음 > 수집 중 > 수집 뒤 못 씀 > 오늘 회차 없음
    if state == "error":
        note = NOTE["error"]
        problems.append("숫자 파일을 읽지 못했습니다")
    elif state == "old":
        note = NOTE["old"]
    elif not available:
        note = NOTE["no_data"]
    elif state == "none":
        note = NOTE["none"]
    elif view["running"]:
        note = NOTE["running"].format(at=_hm(written))
    elif stale:
        note = NOTE["stale"].format(at=_hm(written))
    elif (runner or {}).get("state") == "late":
        note = NOTE["late"].format(at=_hm(written))
    else:
        note = ""
    if nums.get("why"):
        dev.append(nums["why"])
    if stale:
        dev.append(f"{NUMBERS_FILE}({_hm(written)})이 마지막 수집({_hm(data_status.last_run_event(runner))})보다 앞이다 — 러너 로그의 "
                   "「기록 파일을 쓰지 못했다」 줄을 본다")
    if mans.get("daily") is None and mans.get("ohlcv") is None and available:
        # 화면에는 바둑판 카드가 「이 PC 에는 연도별 숫자가 없습니다」 로 이미 알린다 — 까닭(파일 위치)은 관리자에게만
        dev.append("백업 매니페스트 두 장(hf_export/meta/manifest.json · ohlcv_export/manifest.json)이 없어 연도별 · 처음 날이 없다"
                   " — 다음 회차의 내보내기 단계 뒤에 생긴다")
    return {
        "available": available, "note": note, "problems": problems,
        "numbers": {"state": "stale" if stale else state, "written_at": written},
        "measured_at": written, "as_of": ((tables or {}).get("price_daily") or {}).get("last_date"),
        "total_rows": total, "total_state": total_state,
        # 「일부」 는 있는 표와 없는 표가 섞일 때만 — 하나도 없으면 「없음」(total_state none)이지 일부가 아니다
        "total_partial": bool(present) and len(present) < len(tables or {}),
        "first": first, "early": early, "years": years, "backup_at": max(ats) if ats else None,
        "runner": view, "items": items,
    }


def read(admin: bool, now: datetime | None = None) -> dict:
    """자료 안내 응답 — 설명(생성물) + 숫자(러너가 쓴 숫자 파일 · 매니페스트 두 장 · 러너 기록). 모두 파일이다 — 수집 DB 를 열지
    않고, 요청 때 세지 않는다(2단계). 숫자를 못 읽어도 설명은 온다(까닭과 함께)."""
    guide = load_guide()
    now = now or data_status._now()  # noqa: SLF001 — 같은 시계(KST)
    problems: list[str] = []
    dev: list[str] = []
    cdir = data_status.collector_dir()
    sdir = cdir / "state" if cdir else None
    runner = data_status.runner_state(sdir, now)
    nums = data_status.load_numbers(sdir)
    mans = manifests(cdir)
    catalog = data_status.load_catalog(sdir)
    stats = compute_stats(guide, nums, runner, mans, catalog, problems, dev)
    if admin:
        # 관리자에게만 — 숫자를 잇지 못한 곳(대장 열쇠 · 매니페스트 줄 · 숫자 파일)과 설명을 고치는 곳
        stats["dev"] = {"problems": dev, "ledgers": "docs/데이터/대장/자료안내-*.tsv",
                        "make": "python scripts/data_guide_scan.py --write",
                        "numbers": f"data/collector/state/{NUMBERS_FILE} — python scripts/daily_update.py steps --write"}
    elif dev:
        logger.info("자료 안내 — 숫자를 잇지 못한 곳: %s", " · ".join(dev))
    return {"checked_at": now.isoformat(timespec="seconds"), "viewer": {"admin": admin},
            "guide": public_guide(guide, admin), "stats": stats}
