"""자료 안내 — 「무엇이 있고 · 어떻게 모으고 · 무엇을 읽으면 되나」 (2026-10-08 · 화면 결정 안 B + 안 A 서랍 · 1단계).

`GET /api/data/guide` 가 부른다. 화면은 public/js/dataguide.js(「데이터 › 자료 안내」 · 데이터 관제 바로 아래).

설명과 숫자를 나눈다 (2026-10-08 결정 ④ · SSoT)
-----------------------------------------------
  설명  app/services/data_guide.json — 대장(docs/데이터/대장/자료안내-*.tsv)에서 `scripts/data_guide_scan.py --write` 가
        만든 생성물. 앱은 읽기만 한다(앱 이미지에 docs/ · scripts/ 가 없다). 대장과 어긋나면 시험 TC-DG-01(`--check`)이 알린다.
  숫자  요청 때 잰다 — 이미 있는 상태(`data_status.get_status` · 30초 캐시 · 줄 수는 뒤에서 센다)와 백업 매니페스트 두 장
        (`hf_export/meta/manifest.json` 의 연도 파일 · `collector/ohlcv_export/manifest.json` 의 처음 · 마지막 · 시장).
        이 서비스는 수집 DB 를 새로 열지 않는다 — 상태가 이미 쓰는 읽기 전용 연결 말고는 파일(JSON)만 읽는다.
        경로는 상태와 같은 길(`data_status.collector_dir`)로 찾는다 — 로컬 data/collector · 도커 /app/data/csv/collector.

숫자가 없으면 설명만 — 말없이 0 을 넣지 않는다
---------------------------------------------
수집 자료가 없는 PC(팀원 PC 대부분)에서도 설명 · 흐름 · 길잡이는 다 보인다. 숫자 칸은 None(화면의 「—」)으로 두고 까닭을
단다. 상태가 「수집 DB 가 없다」 · 「표가 아직 없다」 일 때 주는 줄 수 0 은 「없음」 이지 「0줄」 이 아니다(그 0 을 그대로
옮기면 화면이 「0줄」 이라고 거짓말을 한다).

개발 칸은 서버가 관리자에게만 (결정 ① ②)
---------------------------------------
표 이름 · 읽는 길(API) · 백업 경로 · 받는 명령은 관리자 응답에만 싣는다. 화면이 CSS 로 숨기면 응답(개발자 도구)에는 남는다.
일반 사용자의 「쓰는 화면」 · 「어디서」 에서는 관리자 화면 셋도 뺀다(그 사람이 열 수 있는 화면만).
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
SCHEMA = 1

#: 관리자 화면 — 일반 사용자 응답의 「쓰는 화면」 · 「어디서」 에서 뺀다. css/collect.css 가 일반 사용자의 메뉴에서 숨기는 셋과
#: 같다(TC-DG 가 맞댄다 — 관리자 화면이 늘면 두 곳을 함께 고친다).
ADMIN_VIEWS = frozenset({"crawl-auto", "crawl-manual", "crawl-ingest"})
#: 일봉 매니페스트의 시장 이름 → 화면 이름
MARKET_NAMES = {"KOSPI": "코스피", "KOSDAQ": "코스닥", "KONEX": "코넥스", "ETF": "ETF", "INDEX": "지수"}
#: 자료 한 줄의 숫자 상태 → 까닭(쉬운 말). 화면은 상태 열쇠로 모양을 고르고 이 글을 그대로 보인다(TC-DG-04 가 맞댄다).
ITEM_WHY = {
    "ok": "",
    "counting": "줄 수를 세는 중입니다",
    "partial": "줄 수는 이 PC 에서 세지 못했습니다 — 연도별은 백업 목록 기준입니다",
    "none": "이 PC 에는 이 자료가 없습니다",
    "no_link": "이 화면에서는 세지 않는 자료입니다 — 「쓰는 화면」 에서 봅니다",
    "error": "숫자를 읽지 못했습니다",
}

#: 상태를 기다리는 한도(초). 상태의 30초 캐시가 빈 뒤 첫 계산이 컨테이너에서 9 ~ 20초 걸린다(2026-10-08 실측 · 뒤에서 도는 줄 수
#: 세기와 겹칠 때 · 바인드 마운트). 그보다 오래 걸리면 설명 · 백업 목록 숫자를 먼저 보내고(`status_pending`) 화면이 잠시 뒤 다시
#: 묻는다 — 상태 계산은 뒤에서 끝까지 돌아 상태의 캐시를 채우므로 다음 요청은 바로 끝난다(설계 03 문서 11절 경우 표
#: 「불러오는 중 — 설명 먼저 · 숫자 칸 …」). 기다리는 동안 빈 화면을 두지 않으려는 것이지 숫자를 버리는 것이 아니다.
STATUS_WAIT_SECONDS = 2.5

_lock = threading.Lock()
_guide_cache: dict = {"sig": None, "value": None}
_file_cache: dict[str, tuple] = {}
_status_job: dict = {"thread": None, "box": None}

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


def public_guide(guide: dict, admin: bool) -> dict:
    """응답에 싣는 설명 — 숫자 잇는 칸(stats_from)은 누구에게도 · 개발 칸(dev · 뺀 표)은 관리자에게만 싣는다.

    일반 사용자 응답에는 표 이름 · API 경로 · 명령이 **글자로도** 남지 않아야 한다(TC-DG-03) — 화면이 숨기는 것으로는 모자란다.
    """
    g = copy.deepcopy(guide)
    for k in ("schema", "source"):
        g.pop(k, None)
    for it in g.get("items", []):
        it.pop("stats_from", None)
        if not admin:
            it.pop("dev", None)
            it["views"] = [v for v in it.get("views", []) if v not in ADMIN_VIEWS]
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


# ── 숫자 — 상태(기다림 한도) ───────────────────────────────────────────────
def _run_status(box: dict) -> None:
    try:
        box["value"] = data_status.get_status()
    except Exception as e:  # noqa: BLE001 — 부른 쪽(`status_within`)이 다시 올린다
        box["error"] = e


def status_within(wait: float) -> tuple[dict | None, bool]:
    """(상태, 아직 계산 중). 상태 계산이 `wait` 초 안에 끝나지 않으면 (None, True) — 계산은 뒤에서 계속된다.

    도는 계산이 있으면 새로 띄우지 않고 그것을 기다린다(새로 고침을 여러 번 눌러도 수집 DB 를 겹쳐 읽지 않게).
    상태가 예외를 내면 그대로 올린다(부른 쪽이 「자료 상태를 읽지 못했습니다」 를 단다 — 말없이 넘기지 않는다).
    """
    with _lock:
        t = _status_job["thread"]
        if t is None or not t.is_alive():
            box: dict = {}
            t = threading.Thread(target=_run_status, args=(box,), name="data-guide-status", daemon=True)
            _status_job.update(thread=t, box=box)
            t.start()
        box = _status_job["box"]
    t.join(wait)
    if t.is_alive():
        return None, True
    if "error" in box:
        raise box["error"]
    return box.get("value"), False


# ── 숫자 — 자료 한 줄 · 전체 ────────────────────────────────────────────────
def item_stats(item: dict, tables: dict[str, dict] | None, mans: dict, dev: list[str], pending: bool = False) -> dict:
    """자료 한 줄의 숫자. `tables` 는 상태 응답의 표 줄(열쇠 → 줄) · 상태를 못 읽었거나 아직 계산 중이면 None(`pending`).

    줄 수 · 마지막 날은 상태(지금 센 값)를 먼저 쓰고, 상태에 줄이 없는 자료(가격 조정 기록 · 분봉 대상 · 받은 원문 · 주봉)만
    백업 매니페스트의 합 · 마지막 날을 쓴다(rows_from 으로 어디서 왔는지 남긴다). 연도별 · 처음 · 시장별은 매니페스트에서만 온다.
    """
    sf = item.get("stats_from") or {}
    keys, spec = sf.get("status") or [], sf.get("backup") or ""
    out = {"state": "ok", "why": "", "rows": None, "rows_from": None, "last": None, "first": None,
           "first_year": None, "years": None, "markets": None}
    if not keys and not spec:
        return {**out, "state": "no_link", "why": ITEM_WHY["no_link"]}
    counting = error = False
    if keys:
        if tables is None:
            counting, error = pending, not pending      # 상태가 아직 계산 중이면 「세는 중」 · 못 읽었으면 「읽지 못함」
        else:
            rows = [tables.get(k) for k in keys]
            unknown = [k for k, r in zip(keys, rows) if r is None]
            if unknown:
                error = True
                dev.append(f"{item['key']}: 숫자_상태 {', '.join(unknown)} 가 상태 응답(data_status.TABLES)에 없다")
            # verdict missing = 수집 DB 나 표가 없다 · 행이 없다 — 그때 상태가 주는 줄 수 0 은 쓰지 않는다(「없음」)
            elif all(r.get("verdict") != "missing" for r in rows):
                vals = [r.get("rows") for r in rows]
                if any(v is None for v in vals):
                    counting = True                       # 상태가 아직 세는 중(앱을 켠 뒤 처음 · 컨테이너 15 ~ 20초)
                else:
                    out.update(rows=sum(vals), rows_from="status")
                lasts = [r["last_date"] for r in rows if r.get("last_date")]
                out["last"] = max(lasts) if lasts else None
    ser = series(spec, mans) if spec else None
    if spec and ser is None and mans.get("daily" if spec.startswith("hf:") else "ohlcv") is not None:
        dev.append(f"{item['key']}: 숫자_백업 {spec} 줄이 매니페스트에 없다")
    if ser:
        out["years"] = ser["years"] or None
        out["first"] = ser["first"]
        out["markets"] = ser["markets"]
        nonzero = [y for y, n in (ser["years"] or {}).items() if n]
        out["first_year"] = min(nonzero) if nonzero else None
        if not keys:
            out.update(rows=ser["rows"], rows_from="backup", last=ser["last"])
    if out["rows"] is None and out["last"] is None and not out["years"]:
        state = "error" if error else "counting" if counting else "none"
        return {**out, "state": state, "why": ITEM_WHY[state]}
    if counting:
        out.update(state="counting", why=ITEM_WHY["counting"])
    elif out["rows"] is None:
        # 연도별(백업 목록)만 있고 지금 줄 수가 없다 — 「ok」 로 두면 화면이 빈칸의 까닭을 못 단다
        out.update(state="partial", why=ITEM_WHY["partial"])
    return out


def runner_view(status: dict | None, catalog: dict | None) -> dict:
    """흐름 그림의 단계 — 단계 이름표 · 묶음은 러너가 쓴 단계 목록에서만 읽는다(결정 ④ · 앱에 사본 없음).

    묶음 설명(`note`)은 관리자 말(「Hugging Face 데이터셋으로 올린다」)이라 싣지 않는다 — 쉬운 말은 대장의 흐름 상자가 맡는다.
    단계 이름(price · ohlcv_upload)도 싣지 않고 이름표(시세 · 일봉 올리기)만 싣는다.
    """
    r = (status or {}).get("runner") or {}
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
    hh, mm = data_status.SCHEDULE_HM
    return {
        "schedule": r.get("schedule") or f"매일 {hh:02d}:{mm:02d}",
        "running": bool(r.get("running")),
        "total_steps": len(steps),
        "groups": [{"key": g, "count": sum(1 for s in steps if s.get("group") == g),
                    "steps": [s["label"] for s in steps if s.get("group") == g and s.get("label")],
                    "attention": attention.get(g, 0)} for g in order],
        "last": {k: last.get(k) for k in ("started_at", "finished_at", "minutes", "ok")} if last else None,
    }


def compute_stats(guide: dict, status: dict | None, mans: dict, catalog: dict | None,
                  problems: list[str], dev: list[str], pending: bool = False) -> dict:
    """숫자 전체 — 숫자 띠 · 바둑판 · 자료 줄 · 흐름. `status` 가 None 이면 상태를 못 읽었거나(`pending` 거짓) 아직 계산 중
    (`pending` 참)이다 — 어느 쪽이든 설명과 백업 목록의 숫자는 그대로 싣고, 상태에서 오는 칸만 비운 채 까닭을 단다."""
    tables = {t["key"]: t for t in (status or {}).get("tables") or [] if isinstance(t, dict) and t.get("key")} \
        if status is not None else None
    items = {it["key"]: item_stats(it, tables, mans, dev, pending) for it in guide.get("items", [])}

    # 모은 줄 — 상태가 센 표 줄의 합(주봉처럼 부를 때 계산하는 자료 · 근거 문서 · 용어는 빼고). 하나라도 세는 중이면 None.
    present = [t for t in (tables or {}).values() if t.get("verdict") != "missing"]
    vals = [t.get("rows") for t in present]
    if pending:
        total, total_state = None, "counting"
    elif not present:
        total, total_state = None, "none"
    elif any(v is None for v in vals):
        total, total_state = None, "counting"
    else:
        total, total_state = sum(vals), (status or {}).get("rows_state") or "fresh"
    firsts = [s["first"] for s in items.values() if s.get("first")]
    first = min(firsts) if firsts else None
    # 처음 날보다 이른 해가 있는 자료(재무는 보고서를 접수한 해 2019 부터) — 숫자 띠의 한 줄
    early = sorted(({"item": k, "year": s["first_year"]} for k, s in items.items()
                    if s.get("first_year") and first and s["first_year"] < first[:4]), key=lambda x: x["year"])
    grid_years = sorted({y for it in guide.get("items", []) if it.get("grid") for y in (items[it["key"]].get("years") or {})})
    years = [str(y) for y in range(int(grid_years[0]), int(grid_years[-1]) + 1)] if grid_years else []
    ats = [m.get("at") for m in mans.values() if m and m.get("at")]
    available = any(s["rows"] is not None or s["years"] for s in items.values())
    runner = runner_view(status, catalog)

    if pending:
        note = "자료 상태를 세는 중입니다 — 잠시 뒤 저절로 채워집니다"
    elif status is None:
        note = "자료 상태를 읽지 못했습니다 — 숫자 칸은 비워 두고 설명은 그대로 보입니다"
    elif not available:
        note = "이 PC 에는 모은 자료가 없습니다 — 설명 · 흐름 · 길잡이는 그대로 봅니다"
    elif runner["running"]:
        note = "매일 낮 수집이 도는 중입니다 — 숫자는 지난 회차 기준입니다"
    elif total_state == "counting":
        note = "줄 수를 세는 중입니다 — 잠시 뒤 저절로 채워집니다"
    elif total_state == "old":
        note = "자료가 바뀌어 줄 수를 다시 세는 중입니다 — 지금 보이는 것은 지난번 값입니다"
    else:
        note = ""
    if mans.get("daily") is None and mans.get("ohlcv") is None and available:
        # 화면에는 바둑판 카드가 「이 PC 에는 연도별 숫자가 없습니다」 로 이미 알린다 — 까닭(파일 위치)은 관리자에게만
        dev.append("백업 매니페스트 두 장(hf_export/meta/manifest.json · ohlcv_export/manifest.json)이 없어 연도별 · 처음 날이 없다"
                   " — 다음 회차의 내보내기 단계 뒤에 생긴다")
    return {
        "available": available, "note": note, "problems": problems, "status_pending": pending,
        "measured_at": (status or {}).get("checked_at"), "as_of": (status or {}).get("as_of"),
        "total_rows": total, "total_state": total_state,
        # 「일부」 는 있는 표와 없는 표가 섞일 때만 — 하나도 없으면 「없음」(total_state none)이지 일부가 아니다
        "total_partial": bool(present) and len(present) < len(tables or {}),
        "first": first, "early": early, "years": years, "backup_at": max(ats) if ats else None,
        "runner": runner, "items": items,
    }


def read(admin: bool, now: datetime | None = None) -> dict:
    """자료 안내 응답 — 설명(생성물) + 숫자(상태 · 매니페스트). 숫자를 못 읽어도 설명은 온다(까닭과 함께)."""
    guide = load_guide()
    now = now or data_status._now()  # noqa: SLF001 — 같은 시계(KST)
    problems: list[str] = []
    dev: list[str] = []
    status, pending = None, False
    try:
        status, pending = status_within(STATUS_WAIT_SECONDS)
    except Exception as e:  # noqa: BLE001 — 숫자를 못 읽어도 설명은 보인다. 말없이 넘기지 않고 까닭을 남긴다
        logger.warning("자료 안내 — 상태를 읽지 못했다: %s", e)
        problems.append("자료 상태를 읽지 못했습니다")
        dev.append(f"data_status.get_status: {type(e).__name__}: {e}")
    cdir = data_status.collector_dir()
    mans = manifests(cdir)
    catalog = data_status.load_catalog(cdir / "state" if cdir else None)
    stats = compute_stats(guide, status, mans, catalog, problems, dev, pending)
    if admin:
        # 관리자에게만 — 숫자를 잇지 못한 곳(대장 열쇠 · 매니페스트 줄)과 설명을 고치는 곳
        stats["dev"] = {"problems": dev, "ledgers": "docs/데이터/대장/자료안내-*.tsv",
                        "make": "python scripts/data_guide_scan.py --write"}
    elif dev:
        logger.info("자료 안내 — 숫자를 잇지 못한 곳: %s", " · ".join(dev))
    return {"checked_at": now.isoformat(timespec="seconds"), "viewer": {"admin": admin},
            "guide": public_guide(guide, admin), "stats": stats}
